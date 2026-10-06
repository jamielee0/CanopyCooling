"""Step7 joint geography resampling and explicitly synthetic day calibration."""
import hashlib
import numpy as np
from scipy.stats import norm, t as student_t
from urban_cooling_v2.pooled_city_pass import _group_sum, temperature_equivalent, SIGMA
from .spatial_review import physical_groups, identity_hash

PRECISION_FIELDS={"comparison","group_km","quantity","units","independent_dates","requested","estimable","failed",
                  "SE","width95","effect_status","uncertainty_scope"}


def joint_passes(stats, *, group_km, replicates, seed):
    """One physical-union multiplicity vector for every date/outcome in a city."""
    union=np.unique(np.concatenate([s.labels for s in stats]))
    group_names,gi=np.unique(physical_groups(union,group_km),return_inverse=True)
    if len(group_names)<2:raise ValueError("Too few spatial resampling groups")
    matrices=[];presence=[]
    for s in stats:
        if len(set(s.labels))!=len(s.labels):raise ValueError("Duplicate physical block")
        inv=gi[np.searchsorted(union,s.labels)]
        matrices.append((_group_sum(s.xx,inv,len(group_names)),_group_sum(s.xy,inv,len(group_names))))
        presence.append(np.bincount(inv,minlength=len(group_names))>0)
    points=np.stack([-.1*s.solve()[0] for s in stats])
    draws=np.full((replicates,len(stats),2),np.nan);rng=np.random.default_rng(seed);h=hashlib.sha256()
    for b in range(replicates):
        counts=rng.multinomial(len(group_names),np.full(len(group_names),1/len(group_names)))
        h.update(counts.astype('<i8').tobytes())
        for j,s in enumerate(stats):
            xx=np.einsum('g,gij->ij',counts,matrices[j][0]);xy=np.einsum('g,gik->ik',counts,matrices[j][1])
            if np.linalg.matrix_rank(xx,tol=1e-10)!=len(s.predictors):continue
            draws[b,j]=-.1*(np.linalg.solve(xx,xy)/s.norms[:,None])[0]
    valid=np.isfinite(draws).all(axis=2)
    audit=dict(group_km=group_km,groups=len(group_names),physical_union_blocks=len(union),requested=replicates,
        complete_city_draws=int(valid.all(axis=1).sum()),per_pass_estimable=valid.sum(axis=0).tolist(),
        per_pass_failed_indices=[np.flatnonzero(~valid[:,j]).tolist() for j in range(len(stats))],
        structural_absent_groups=[int((~v).sum()) for v in presence],
        physical_group_identity_sha256=identity_hash(group_names),draw_multiplicity_sha256=h.hexdigest())
    return points,draws,audit


def window_quantities(cooling, weights, reference_K, reference_emissivity):
    """Arm-mean flux first, exact fixed-reference inversion second, time difference last."""
    c=np.asarray(cooling,float);w=np.asarray(weights,float)
    if c.shape[-2:]!=(len(w),2) or not np.isclose(w[w>0].sum(),1) or not np.isclose(-w[w<0].sum(),1):
        raise ValueError("Both frozen arms must sum to one")
    selected=w!=0;active=c[...,selected,:];ww=w[selected]
    a=np.einsum('p,...po->...o',np.maximum(ww,0),active)
    m=np.einsum('p,...po->...o',np.maximum(-ww,0),active)
    difference=a-m
    equivalents=[];anchor=reference_emissivity*SIGMA*reference_K**4
    for arm in (a,m):
        value=np.full(arm.shape[:-1],np.nan)
        valid=np.isfinite(arm).all(axis=-1)&(anchor-arm[...,1]>0)
        value[valid]=-temperature_equivalent(-arm[...,1][valid],reference_K,reference_emissivity)
        equivalents.append(value)
    deq=equivalents[0]-equivalents[1]
    return np.stack((difference[...,0],difference[...,1],deq,difference[...,0]-deq),axis=-1)


def summarize(point, draws):
    values=np.asarray(draws,float);valid=np.isfinite(values);n=int(valid.sum())
    if not np.isfinite(point) or n<2:return dict(status="NOT_ESTIMABLE",point=None,q025=None,q975=None,SE=None,width95=None,estimable=n,failed=len(values)-n)
    lo,hi=np.quantile(values[valid],[.025,.975])
    return dict(status="ESTIMABLE",point=float(point),q025=float(lo),q975=float(hi),SE=float(values[valid].std(ddof=1)),
                width95=float(hi-lo),estimable=n,failed=len(values)-n)


def precision_only(row):
    if set(row)!=PRECISION_FIELDS or row['effect_status']!='SEALED_USER_REQUEST':raise ValueError("Unapproved public fields")
    if row['uncertainty_scope']!='fixed_dates_spatial_only':raise ValueError("Unapproved inference scope")
    for k in ('SE','width95'):
        if row[k] is not None and (not np.isfinite(row[k]) or row[k]<0):raise ValueError("Invalid precision")
    return dict(row)


def nuisance_design(times,months):
    t=np.asarray(times,float);m=np.asarray(months,int)
    x=np.column_stack((np.ones(len(t)),t-t.mean(),*[m==v for v in np.unique(m)[1:]]))
    if np.linalg.matrix_rank(x)!=x.shape[1] or len(t)<=x.shape[1]:raise ValueError("No full-rank day-variance design with residual degrees of freedom")
    residual=np.eye(len(t))-x@np.linalg.pinv(x)
    return x,residual,len(t)-x.shape[1]


def day_slope_bank(times, *, early,late,replicates,seed):
    """Exactly the existing independent-day benchmark, as reusable linear weights."""
    t=np.asarray(times,float);x=np.column_stack((np.ones(len(t)),t-early));n=len(t)
    if not t.min()<=early<late<=t.max():raise ValueError("Unsupported original time target")
    rng=np.random.default_rng(seed);bank=[];failed=0;outside=0
    # ISO dates in the callers are ordered, unique independent-day identities.
    for _ in range(replicates):
        ids=rng.choice(np.arange(n),n,replace=True)
        if np.linalg.matrix_rank(x[ids])<2:failed+=1;continue
        coefficients=(late-early)*np.linalg.pinv(x[ids])[1]
        bank.append(np.bincount(ids,weights=coefficients,minlength=n))
        outside+=int(t[ids].min()>early or t[ids].max()<late)
    point=(late-early)*np.linalg.pinv(x)[1]
    return point,np.asarray(bank),dict(requested=replicates,estimable=len(bank),rank_failed=failed,
                                    target_outside_resampled_time_range=outside)


def stratified_window_bank(weights,months, *,replicates,seed):
    w=np.asarray(weights,float);m=np.asarray(months);rng=np.random.default_rng(seed);out=np.zeros((replicates,len(w)))
    groups=[np.flatnonzero((m==month)&(np.sign(w)==sign)) for month in np.unique(m[w!=0]) for sign in (-1,1)]
    if any(not len(g) for g in groups):raise ValueError("Empty month/arm")
    for b in range(replicates):
        for ids in groups:
            sampled=rng.choice(ids,len(ids),replace=True)
            out[b]+=np.bincount(sampled,minlength=len(w))*w[ids].sum()/len(ids)
    return out


def moment_variance_intervals(y,weights,spatial_covariance,times,months):
    """Synthetic candidate: subtract spatial residual variance once, truncate tau² at zero.

    Point remains the prespecified unweighted window contrast. Month intercepts
    plus linear time estimate a shared day variance; this is an assumption under
    calibration, not an adopted empirical time model or a REML estimator.
    """
    y=np.atleast_2d(y);w=np.asarray(weights);s=np.asarray(spatial_covariance)
    _,p,df=nuisance_design(times,months)
    residual_ss=np.einsum('bi,ij,bj->b',y,p,y)
    tau2=np.maximum(0,(residual_ss-np.trace(p@s))/df)
    spatial=float(w@s@w);variance=spatial+tau2*(w@w)
    center=y@w;half=student_t.ppf(.975,df)*np.sqrt(np.maximum(variance,0))
    return center-half,center+half,tau2,df


def covariance_root(cov):
    c=np.asarray(cov,float);values,vectors=np.linalg.eigh((c+c.T)/2)
    if values.min() < -1e-10:raise ValueError("Non-positive-semidefinite covariance")
    return vectors@np.diag(np.sqrt(np.maximum(values,0)))


def assess_interval(point,lo,hi,target,fixed_target):
    target=np.broadcast_to(target,np.shape(point));valid=np.isfinite(point)&np.isfinite(lo)&np.isfinite(hi)
    n=int(valid.sum());coverage=(lo[valid]<=target[valid])&(hi[valid]>=target[valid])
    fixed=(lo[valid]<=fixed_target[valid])&(hi[valid]>=fixed_target[valid])
    p=float(coverage.mean()) if n else None
    return dict(datasets_requested=len(point),estimable=n,failed=len(point)-n,
        population_target_coverage=p,coverage_MCSE=float(np.sqrt(p*(1-p)/n)) if n else None,
        fixed_dates_target_coverage=float(fixed.mean()) if n else None,
        mean_width=float(np.mean(hi[valid]-lo[valid])) if n else None,
        bias=float(np.mean(point[valid]-target[valid])) if n else None,
        bias_MCSE=float(np.std(point[valid]-target[valid],ddof=1)/np.sqrt(n)) if n>1 else None)


def simulate_scenario(design,S, *,amplitude,day_sd,correlation_fraction,profile,datasets,seed,banks):
    """SYNTHETIC DATA: scheduled population mean differs from realized-date target."""
    times=np.asarray(design['times']);months=np.asarray(design['months']);days=np.asarray(design['day_numbers'])
    w=np.asarray(design['weights']);n=len(w);span=float(w@times)
    mu=amplitude*(times-times.mean())/span
    if profile=='season_offsets':mu=mu+.15*(months-months.min())
    if profile=='curved_time':mu=mu+.025*(times-13)**2
    if profile=='month_slope':mu=mu+.04*(months-months.min())*(times-13)
    cday=np.eye(n)*day_sd**2
    if profile=='heterogeneous_day':cday=np.diag((day_sd*np.where(w>0,2.,1.))**2)
    if profile=='serial_days':cday=day_sd**2*np.exp(-np.abs(days[:,None]-days[None,:])/14)
    spatial=(1-correlation_fraction)*np.diag(np.diag(S))+correlation_fraction*S
    rng=np.random.default_rng(seed)
    latent=mu+rng.normal(size=(datasets,n))@covariance_root(cday).T
    observed=latent+rng.normal(size=(datasets,n))@covariance_root(spatial).T
    target=float(w@mu);fixed=latent@w;point=observed@w;rows={}
    se=np.sqrt(max(float(w@spatial@w),0));lo=point-norm.ppf(.975)*se;hi=point+norm.ppf(.975)*se
    rows['fixed_date_spatial_only']=assess_interval(point,lo,hi,target,fixed)
    lo,hi,tau2,df=moment_variance_intervals(observed,w,spatial,times,months)
    rows['moment_separated_t']=assess_interval(point,lo,hi,target,fixed)
    rows['moment_separated_t'].update(day_variance_df=df,zero_day_variance_fraction=float((tau2==0).mean()))
    # Explicit negative control: a second copy of known pass-estimation variance.
    half=student_t.ppf(.975,df)*np.sqrt(2*se**2+tau2*(w@w))
    rows['double_spatial_noise_negative_control']=assess_interval(point,point-half,point+half,target,fixed)
    oracle=np.sqrt(float(w@(spatial+cday)@w));half=norm.ppf(.975)*oracle
    rows['oracle_known_variance']=assess_interval(point,point-half,point+half,target,fixed)
    slope_point,slope_bank,bank_audit,strat_bank=banks
    for name,weights,center in [('existing_day_slope_bootstrap',slope_bank,observed@slope_point),
                                ('stratified_window_day_bootstrap',strat_bank,point)]:
        draws=observed@weights.T;lo,hi=np.quantile(draws,[.025,.975],axis=1)
        rows[name]=assess_interval(center,lo,hi,target,fixed)
        rows[name].update(bootstrap_requested=len(strat_bank) if name.startswith('stratified') else bank_audit['requested'],
                         bootstrap_estimable=len(weights),
                         target_outside_resampled_range_fraction=0. if name.startswith('stratified') else bank_audit['target_outside_resampled_time_range']/len(weights))
    return rows,dict(population_target=target,independent_days=n,day_variance_model_df=df,
                     observational_time_span=span,true_spatial_variance=se**2,true_day_variance=float(w@cday@w))
