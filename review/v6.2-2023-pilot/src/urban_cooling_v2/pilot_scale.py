"""Frozen reference contrasts, supported time models and synthetic diagnostics.

Functions return sensitive empirical effects to the caller; never print them.
An executable runner must save them under the sealed output boundary.
"""
import numpy as np
import pandas as pd
from .pooled_city_pass import temperature_equivalent,fit_city_pass,mix_pixels,CONTEXT

def supported_reference_pair(frames):
    """Find a shared 0.10 pair maximizing the minimum block coverage by pass.

    No block is removed from slope estimation. Candidate lower endpoints are
    the exact boundaries at which a reference block begins/ends supporting a
    0.10 contrast. Ties use the smaller lower endpoint. Only canopy/block data
    enter this rule; every reference block must contain both raw endpoints.
    """
    intervals=[]
    for f in frames:
        b=f.groupby('block').canopy_fraction.agg(['min','max'])
        b=b[b['max']-b['min']>=.1].copy()
        if b.empty:raise ValueError('No block supports a 0.10 reference contrast in at least one pass')
        intervals.append(b)
    candidates=np.unique(np.concatenate([b['min'].to_numpy() for b in intervals]+[(b['max']-.1).to_numpy() for b in intervals]))
    count_by_pass=[]
    for b in intervals:
        starts=np.sort(b['min'].to_numpy());ends=np.sort((b['max']-.1).to_numpy())
        counts=np.searchsorted(starts,candidates+1e-12,side='right')-np.searchsorted(ends,candidates-1e-12,side='left')
        count_by_pass.append(counts)
    scores=np.min(count_by_pass,axis=0)
    best=int(np.argmax(scores));f0=float(candidates[best]);f1=f0+.1
    if scores[best]==0:raise ValueError('No shared block-supported 0.10 contrast across passes')
    refs=[]
    for f,b in zip(frames,intervals):
        ids=b.index[(b['min']<=f0)&(b['max']>=f1)]
        refs.append(f[f.block.isin(ids)].copy())
    return f0,f1,refs

def freeze_references(frames,city_labels):
    f0,f1,refs=supported_reference_pair(frames)
    # Equal city, equal pass within city; pixel medians are robust absolute
    # distribution anchors, not coefficients. Selection is frozen in advance.
    values=pd.DataFrame({'city':city_labels,'T':[f.LST_K.median() for f in frames],'e':[f.emissivity.median() for f in frames]})
    reference=values.groupby('city')[['T','e']].mean().mean()
    return {'f0':f0,'f1':f1,'reference_K':float(reference['T']),'reference_emissivity':float(reference['e']),
            'rule':'equal_city_average_of_equal_pass_medians; covariance_reference_rows_within_support_blocks',
            'reference_rows':[len(f) for f in refs],'reference_blocks':[f.block.nunique() for f in refs]},refs

def contrast_from_pass_predictions(fit,reference_frame,settings):
    p=fit.prediction_difference(reference_frame,settings['f0'],settings['f1'])
    jT=fit.outcome_names.index('LST_K');jM=fit.outcome_names.index('M_W_m2')
    valid=np.isfinite(fit.bootstrap_coefficients).all(axis=(1,2))
    bt=fit.bootstrap_coefficients[valid,0,jT]*.1;bm=fit.bootstrap_coefficients[valid,0,jM]*.1
    return {'CE_T':-float(p['delta'][jT]),'CE_M_W_m2':-float(p['delta'][jM]),
            'CE_M_equivalent':-float(temperature_equivalent(p['delta'][jM],settings['reference_K'],settings['reference_emissivity'])),
            'bootstrap_CE_T':-bt,'bootstrap_CE_M_equivalent':-temperature_equivalent(bm,settings['reference_K'],settings['reference_emissivity'])}

def time_contrast(times,CE, *,early=10.5,late=16.,geometry=None,day_of_year=None,day_clusters=None,
                  bootstrap_CE=None,replicates=1000,seed=20260919):
    """One city's prefrozen linear time model, optional additive geometry/season.

    Primary unweighted linear model includes the total solar-geometry change.
    Secondary adds centered solar elevation and day of year (only if both
    targets' observed covariate neighborhoods overlap). At least residual df
    and a full-rank design are mathematical requirements, not pass-count gates.
    Independent day clusters are resampled; paired model-space draws remain
    paired. Stage-1 bootstrap draws propagate cell-level uncertainty.
    """
    t=np.asarray(times,float);y=np.asarray(CE,float)
    if y.ndim==1:y=y[:,None]
    if len(t)!=len(y) or not np.isfinite(t).all() or not np.isfinite(y).all():raise ValueError('Invalid time inputs')
    if not t.min()<=early<late<=t.max():raise ValueError('Time targets outside observed support')
    x=np.column_stack([np.ones(len(t)),t-early]);kind='total_observation_time'
    if geometry is not None or day_of_year is not None:
        if geometry is None or day_of_year is None:raise ValueError('Both geometry and season required for secondary model')
        g=np.asarray(geometry,float);d=np.asarray(day_of_year,float)
        # Convex hull overlap of geometry/season vectors across earlier/later
        # observations is necessary for a common standardized reference.
        if not secondary_overlap(t,g,d,(early+late)/2):raise ValueError('Secondary geometry/season common support absent')
        x=np.column_stack([x,g-g.mean(),d-d.mean()]);kind='geometry_season_standardized'
    if len(t)<=x.shape[1] or np.linalg.matrix_rank(x)<x.shape[1]:raise ValueError('Time model not estimable with residual degrees of freedom')
    labels=np.arange(len(t)).astype(str) if day_clusters is None else np.asarray(day_clusters,str)
    unique=np.unique(labels);rng=np.random.default_rng(seed);draws=[]
    beta=np.linalg.lstsq(x,y,rcond=None)[0];point=beta[1]*(late-early)
    for r in range(replicates):
        sampled=rng.choice(unique,len(unique),replace=True);ids=np.concatenate([np.flatnonzero(labels==v) for v in sampled])
        if np.linalg.matrix_rank(x[ids])<x.shape[1]:continue
        yy=y.copy()
        if bootstrap_CE is not None:
            b=np.asarray(bootstrap_CE,float) # pass, draw, outcome
            idx=rng.integers(b.shape[1],size=len(t));perturb=b[np.arange(len(t)),idx,:]-np.nanmean(b,axis=1)
            yy+=perturb
        coef=np.linalg.lstsq(x[ids],yy[ids],rcond=None)[0];draws.append(coef[1]*(late-early))
    return {'model':kind,'point':point,'draws':np.asarray(draws),'estimable_resamples':len(draws),'requested_resamples':replicates,
            'independent_days':len(unique),'early':early,'late':late}

def secondary_overlap(t,g,d,split):
    """Feasibility of equal convex combinations of observed covariate vectors."""
    from scipy.optimize import linprog
    a=np.column_stack([g,d])[np.asarray(t)<=split];b=np.column_stack([g,d])[np.asarray(t)>split]
    if len(a)==0 or len(b)==0:return False
    scale=np.maximum(np.std(np.vstack([a,b]),axis=0),1e-12);a=a/scale;b=b/scale
    A=np.vstack([np.column_stack([a.T,-b.T]),np.r_[np.ones(len(a)),np.zeros(len(b))],np.r_[np.zeros(len(a)),np.ones(len(b))]])
    return bool(linprog(np.zeros(len(a)+len(b)),A_eq=A,b_eq=[0,0,1,1],bounds=(0,None),method='highs').success)

def simulate_pass(frame, *,contrasts=(0,2,5,10),reference_K,reference_emissivity,seed=20260919,replicates=100):
    """Synthetic constant contrast, observed canopy and block T/emissivity anchors.

    Block medians remove the empirical canopy-LST association. Sensitivities
    permute observed within-block temperatures, rather than copying a sealed
    empirical outcome into a nominally synthetic zero-contrast result.
    Transform-only uses constant background temperature and epsilon per block.
    Noise is a reproducible block-correlated Gaussian process (0.5 K each for
    block and individual terms). Different-support halves each block's observed
    canopy range around its observed mean; it is explicitly synthetic.
    """
    if not contrasts or contrasts[0]!=0: raise ValueError('Zero control must be first')
    d=frame.copy();rng=np.random.default_rng(seed);blocks=d.groupby('block',sort=True)
    background=blocks.LST_K.transform('median').to_numpy();eps=blocks.emissivity.transform('median').to_numpy()
    f=d.canopy_fraction.to_numpy();rows=[]
    for scenario in ['transformation_only','spatial_error','unequal_emissivity','narrower_canopy_support','baseline_minus_10K','baseline_plus_10K','permuted_observed_within_block_T']:
        ff=f.copy();tb=background.copy();eb=eps.copy();et=None;error=np.zeros(len(d))
        if scenario=='narrower_canopy_support':ff=blocks.canopy_fraction.transform('mean').to_numpy()+.5*(f-blocks.canopy_fraction.transform('mean').to_numpy())
        if scenario=='baseline_minus_10K':tb-=10
        if scenario=='baseline_plus_10K':tb+=10
        if scenario=='unequal_emissivity':eb=d.emissivity.to_numpy();et=np.minimum(.999,eb+.01)
        if scenario=='spatial_error':
            labels,bi=np.unique(d.block,return_inverse=True);error=rng.normal(0,.5,len(labels))[bi]+rng.normal(0,.5,len(d))
        if scenario=='permuted_observed_within_block_T':
            for ids in blocks.indices.values():tb[ids]=rng.permutation(frame.LST_K.to_numpy()[ids])
        zero=None
        for delta in contrasts:
            temp,energy,e=mix_pixels(ff,tb,eb,delta,et)
            temp+=error
            from .pooled_city_pass import emitted_energy
            energy=emitted_energy(temp,e)
            d['canopy_fraction']=ff;d['LST_K']=temp;d['M_W_m2']=energy
            fit=fit_city_pass(d,bootstrap_replicates=replicates,seed=seed)
            ceT=-fit.coefficients[0,0]*.1;ceM=-fit.coefficients[0,1]*.1
            if delta==0:zero=(ceT,ceM);zero_boot=-.1*fit.bootstrap_coefficients[:,0,:]
            ceTeq=-float(temperature_equivalent(-ceM,reference_K,reference_emissivity))
            isolatedT=ceT-zero[0];isolatedM=ceM-zero[1]
            isolatedMeq=-float(temperature_equivalent(-isolatedM,reference_K,reference_emissivity))
            isolated_boot=-.1*fit.bootstrap_coefficients[:,0,:]-zero_boot
            artifact_boot=isolated_boot[:,0]-delta*.1
            rows.append({'label':'SYNTHETIC_DATA','scenario':scenario,'constant_component_contrast_K':delta,
                         'CE_T_K_per_10pp':float(ceT),'CE_M_W_m2_per_10pp':float(ceM),'CE_M_equiv_K_per_10pp':ceTeq,
                         'CE_T_minus_zero_control':float(isolatedT),'CE_Mequiv_minus_zero_control':isolatedMeq,
                         'linear_temperature_benchmark_K_per_10pp':delta*.1,'transformation_departure_K_per_10pp':float(isolatedT-delta*.1),
                         'paired_scale_discrepancy_K_per_10pp':float(isolatedT-isolatedMeq),
                         'synthetic_bootstrap_SE_T':fit.diagnostics['LST_K_SE_per_10pp'],
                         'artifact_bootstrap_q025':float(np.nanquantile(artifact_boot,.025)),
                         'artifact_bootstrap_q975':float(np.nanquantile(artifact_boot,.975)),
                         'opposite_to_component_cooling_frequency':float(np.nanmean(isolated_boot[:,0]<0)) if delta else None})
    return rows
