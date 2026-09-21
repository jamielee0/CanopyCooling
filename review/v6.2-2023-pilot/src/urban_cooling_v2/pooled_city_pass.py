"""v6.2 shared canopy slope with block intercepts; never print fitted effects.

All outcomes use one complete-case sample and the same spatial bootstrap draws.
Public serialization is an explicit allowlist. Within-block sufficient statistics
make repeated sampled blocks algebraically equivalent to giving them fresh IDs.
"""
from dataclasses import dataclass
import numpy as np
from scipy.linalg import qr

SIGMA = 5.670374419e-8
CONTEXT = ('impervious_fraction', 'low_vegetation_fraction', 'bare_fraction',
           'building_fraction', 'elevation', 'distance_to_water')

def emitted_energy(temperature_K, emissivity):
    t, e = np.broadcast_arrays(np.asarray(temperature_K, float), np.asarray(emissivity, float))
    if not (np.isfinite(t).all() and np.isfinite(e).all() and (t > 0).all() and ((e > 0) & (e <= 1)).all()):
        raise ValueError('Positive Kelvin temperatures and emissivity in (0,1] required')
    return e * SIGMA * t ** 4

def temperature_equivalent(delta_M, reference_K, reference_emissivity):
    anchor = float(emitted_energy(reference_K, reference_emissivity))
    upper = anchor + np.asarray(delta_M, float)
    if not np.isfinite(upper).all() or (upper <= 0).any():
        raise ValueError('Nonpositive/nonfinite standardized emitted-energy prediction')
    return (upper / (reference_emissivity * SIGMA)) ** .25 - reference_K

def _group_sum(a, inv, n):
    result = np.zeros((n,) + a.shape[1:], float)
    np.add.at(result, inv, a)
    return result

@dataclass
class PooledFit:
    coefficients: np.ndarray
    bootstrap_coefficients: np.ndarray
    diagnostics: dict
    predictor_names: list
    block_labels: np.ndarray
    block_x_means: np.ndarray
    block_y_means: np.ndarray
    outcome_names: list

    def prediction_difference(self, frame, f0, f1, weights=None):
        """Use frozen reference rows, training centers and known block labels.

        Average predictions at each raw canopy value before exact inversion.
        Both endpoints must be supported within every reference block.
        """
        if not np.isclose(f1-f0, .1) or not 0 <= f0 < f1 <= 1:
            raise ValueError('Need supported canopy values separated by 0.10')
        index = {b:i for i,b in enumerate(self.block_labels)}
        ids = np.array([index[b] for b in frame['block'].astype(str)])
        x = frame[self.predictor_names].to_numpy(float)
        w = np.ones(len(x)) if weights is None else np.asarray(weights,float)
        if not np.isfinite(x).all() or not np.isfinite(w).all() or (w <= 0).any():
            raise ValueError('Invalid reference rows or weights')
        for b in frame['block'].unique():
            f = frame.loc[frame['block'].eq(b),'canopy_fraction']
            if f.min() > f0 or f.max() < f1:
                raise ValueError('Reference block lacks both canopy endpoints')
        means=[]
        for f in (f0,f1):
            replacement=x.copy(); replacement[:,0]=f
            pred=self.block_y_means[ids] + (replacement-self.block_x_means[ids]) @ self.coefficients
            means.append(np.average(pred,axis=0,weights=w))
        return {'mu0':means[0], 'mu1':means[1], 'delta':means[1]-means[0]}


def fit_city_pass(frame, *, outcomes=('LST_K','M_W_m2'), context=CONTEXT,
                  bootstrap_replicates=1000, seed=20260919, cluster_column='block', weights=None):
    """Weighted FE OLS. No minimum canopy span, cells/block, or block count gate.

    Numerical rank checks (1e-10 on scaled design) diagnose non-estimability,
    not scientific support. Context dependencies are removed before canopy is
    tested, so an unidentified canopy effect cannot be rescued by dropping a
    confounder. Coefficient access is the caller's sealing responsibility.
    """
    columns=['canopy_fraction',*context]
    required=['block',cluster_column,*columns,*outcomes]
    missing=set(required)-set(frame.columns)
    if missing: raise ValueError('Missing columns: '+','.join(sorted(missing)))
    x=frame[columns].to_numpy(float); y=frame[list(outcomes)].to_numpy(float)
    n=len(x); w=np.ones(n) if weights is None else np.asarray(weights,float)
    if n<3 or w.shape!=(n,) or not np.isfinite(x).all() or not np.isfinite(y).all() or not np.isfinite(w).all() or (w<=0).any():
        raise ValueError('Caller must supply identical finite paired rows and positive weights')
    if ((x[:,0]<0)|(x[:,0]>1)).any(): raise ValueError('Canopy must be a fraction')
    labels, bi=np.unique(frame['block'].astype(str),return_inverse=True); B=len(labels)
    sw=_group_sum(w,bi,B)
    xm=_group_sum(w[:,None]*x,bi,B)/sw[:,None]
    ym=_group_sum(w[:,None]*y,bi,B)/sw[:,None]
    xc=x-xm[bi]; yc=y-ym[bi]
    sxx_b=_group_sum(w*xc[:,0]**2,bi,B)
    sxx=float(sxx_b.sum())
    if sxx<=np.finfo(float).eps*max(float(w.sum()),1): raise ValueError('No estimable within-block canopy variation')
    norms=np.sqrt((w[:,None]*xc**2).sum(axis=0))
    candidates=[j for j in range(1,x.shape[1]) if norms[j]>1e-12]
    keep=[]
    if candidates:
        z=xc[:,candidates]*np.sqrt(w[:,None])/norms[candidates]
        _,r,pivot=qr(z,mode='economic',pivoting=True)
        rank=int(np.sum(np.abs(np.diag(r))>1e-10))
        keep=sorted(candidates[i] for i in pivot[:rank])
    indices=[0,*keep]; names=[columns[i] for i in indices]
    a=xc[:,indices]/norms[indices]
    weighted=a*np.sqrt(w[:,None])
    if np.linalg.matrix_rank(weighted,tol=1e-10)!=len(indices):
        raise ValueError('Canopy not identifiable after context and block adjustment')
    p=len(indices); dof=n-B-p
    if dof<=0: raise ValueError('No residual degrees of freedom')
    groups, gi=np.unique(frame[cluster_column].astype(str),return_inverse=True); G=len(groups)
    if G<2: raise ValueError('Spatial uncertainty needs at least two independent resampling groups')
    xx=_group_sum(w[:,None,None]*a[:,:,None]*a[:,None,:],gi,G)
    xy=_group_sum(w[:,None,None]*a[:,:,None]*yc[:,None,:],gi,G)
    xtx=xx.sum(axis=0); inv=np.linalg.inv(xtx)
    coef_scaled=np.linalg.solve(xtx,xy.sum(axis=0)); coef=coef_scaled/norms[indices,None]
    residual=yc-a@coef_scaled
    scores=_group_sum(w[:,None,None]*a[:,:,None]*residual[:,None,:],gi,G)
    factor=G/(G-1)*(n-1)/dof
    cluster_se=[]
    for k in range(y.shape[1]):
        meat=scores[:,:,k].T@scores[:,:,k]
        cluster_se.append(np.sqrt(max(0.,(inv@meat@inv)[0,0]*factor))/norms[0]*.1)
    rng=np.random.default_rng(seed)
    boots=np.full((bootstrap_replicates,p,y.shape[1]),np.nan)
    for r in range(bootstrap_replicates):
        counts=rng.multinomial(G,np.full(G,1/G))
        bx=np.einsum('g,gij->ij',counts,xx); by=np.einsum('g,gik->ik',counts,xy)
        if np.linalg.matrix_rank(bx,tol=1e-10)<p: continue
        boots[r]=np.linalg.solve(bx,by)/norms[indices,None]
    valid=np.isfinite(boots).all(axis=(1,2)); nb=int(valid.sum())
    if nb<2: raise ValueError('Fewer than two estimable spatial bootstrap replicates')
    slopes=boots[valid,0,:]*.1
    if len(keep):
        cz=xc[:,keep]/norms[keep]
        residual_f=xc[:,0]-cz@np.linalg.lstsq(cz*np.sqrt(w[:,None]),xc[:,0]*np.sqrt(w),rcond=None)[0]
    else: residual_f=xc[:,0]
    info=_group_sum(w*residual_f**2,bi,B); total=float(info.sum())
    shares=info/total
    rawshares=sxx_b/sxx
    diagnostics={
        'n_cells':n,'n_blocks':B,'contributing_blocks':int((sxx_b>np.finfo(float).eps*np.maximum(sw,1)).sum()),
        'within_block_Sxx':sxx,'within_block_variance':sxx/float(w.sum()),
        'residualized_canopy_Sxx':total,'maximum_block_information_share':float(shares.max()),
        'top_five_block_information_share':float(np.sort(shares)[-5:].sum()),
        'effective_information_blocks':float(1/(shares@shares)),
        'maximum_raw_block_information_share':float(rawshares.max()),
        'design_rank':p,'residual_degrees_of_freedom':dof,
        'removed_context_terms':[columns[j] for j in range(1,len(columns)) if j not in keep],
        'bootstrap_requested':bootstrap_replicates,'bootstrap_estimable':nb,
        'bootstrap_failed':bootstrap_replicates-nb,'resampling_groups':G,'seed':seed,
        'maximum_slope_design_leverage':float(np.max(w*np.einsum('ij,jk,ik->i',a,inv,a))),
    }
    for k,name in enumerate(outcomes):
        diagnostics[name+'_SE_per_10pp']=float(np.std(slopes[:,k],ddof=1))
        diagnostics[name+'_bootstrap_width_95_per_10pp']=float(np.diff(np.quantile(slopes[:,k],[.025,.975]))[0])
        diagnostics[name+'_cluster_sandwich_SE_per_10pp']=float(cluster_se[k])
    return PooledFit(coef,boots,diagnostics,names,labels,xm[:,indices],ym,list(outcomes))


def public_precision(fit, *, city, pass_id, variant='paired_primary'):
    """Never serialize arbitrary fit attributes or open bootstrap endpoints."""
    return {'city':str(city),'pass_id':str(pass_id),'variant':str(variant),**fit.diagnostics}


def supported_canopy_pair(frames):
    """Outcome-blind central support: intersect pass P10-P90, center a 0.10 pair.

    Frozen reference rows use only blocks whose observed min/max cover both
    endpoints. All other valid blocks still contribute to model fitting.
    """
    ranges=[np.quantile(f['canopy_fraction'],[.1,.9]) for f in frames]
    lo=max(x[0] for x in ranges); hi=min(x[1] for x in ranges)
    if hi-lo<.1: raise ValueError('No shared 0.10 interval in central canopy support')
    f0=(lo+hi-.1)/2; f1=f0+.1; refs=[]
    for frame in frames:
        bounds=frame.groupby('block')['canopy_fraction'].agg(['min','max'])
        ids=bounds.index[(bounds['min']<=f0)&(bounds['max']>=f1)]
        ref=frame.loc[frame['block'].isin(ids)].copy()
        if ref.empty: raise ValueError('No reference blocks support both endpoints')
        refs.append(ref)
    return float(f0),float(f1),refs


def mix_pixels(canopy, background_K, emissivity, contrast_K, tree_emissivity=None):
    """Clearly synthetic assumed components; never a recovered tree temperature."""
    f,tb,eb=np.broadcast_arrays(np.asarray(canopy,float),np.asarray(background_K,float),np.asarray(emissivity,float))
    et=eb if tree_emissivity is None else np.broadcast_to(tree_emissivity,eb.shape)
    if ((f<0)|(f>1)).any() or contrast_K<0: raise ValueError('Invalid synthetic inputs')
    mix=(1-f)*emitted_energy(tb,eb)+f*emitted_energy(tb-contrast_K,et)
    emix=(1-f)*eb+f*et
    return (mix/(emix*SIGMA))**.25,mix,emix


def scale_ruling(delta_T, delta_M_equivalent, tolerance, *, released=False, supported=True):
    if not released: return 'PENDING_COEFFICIENT_RELEASE'
    if tolerance is None: return 'PENDING_REZA_TOLERANCE'
    if not np.isfinite(tolerance) or tolerance<=0: raise ValueError('Tolerance must be positive')
    if not supported or not np.isfinite([delta_T,delta_M_equivalent]).all(): return 'NOT_ESTIMABLE'
    if delta_T==0 or delta_M_equivalent==0: return 'DIRECTION_UNRESOLVED_AT_ZERO'
    agree=np.sign(delta_T)==np.sign(delta_M_equivalent) and abs(delta_T-delta_M_equivalent)<tolerance
    return 'LST_HEADLINE_SUPPORTED' if agree else 'EMITTED_ENERGY_PRIMARY_LST_SCALE_DEPENDENT'
