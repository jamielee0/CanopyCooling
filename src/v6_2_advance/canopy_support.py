"""Predictor-only Step5 support and protected quadratic-design diagnostics."""
from dataclasses import dataclass
import hashlib
import numpy as np
import pandas as pd
from scipy.linalg import qr
from scipy.spatial import cKDTree
from urban_cooling_v2.pooled_city_pass import CONTEXT, _group_sum

PREDICTORS = ("canopy_fraction", *CONTEXT)
READ_COLUMNS = ("cell_id", "block", *PREDICTORS, "x", "y", "native_crs", "native_x", "native_y")
FORBIDDEN_COLUMNS = ("LST_K", "M_W_m2", "emissivity")


def assert_predictor_columns(columns):
    if not set(columns).issubset(READ_COLUMNS): raise ValueError("Audit read requests an outcome or unapproved column")


def band_mask(f, endpoint, halfwidth):
    if not 0<=endpoint<=1 or not 0<halfwidth<=.05: raise ValueError("Invalid diagnostic endpoint/width")
    lo, hi = max(0., endpoint-halfwidth), min(1., endpoint+halfwidth)
    values = np.asarray(f, float)
    return (values>=lo)&(values<=hi), lo, hi


def endpoint_support(frame, f0, f1, halfwidth):
    if not np.isclose(f1-f0,.1,atol=1e-12,rtol=0) or not 0<=f0<f1<=1: raise ValueError("Need a 10pp pair inside fraction range")
    bounds=frame.groupby("block").canopy_fraction.agg(["min","max"])
    spanning=bounds.index[(bounds["min"]<=f0)&(bounds["max"]>=f1)]
    ref=frame.block.isin(spanning).to_numpy()
    masks=[]; result={"f0":f0,"f1":f1,"halfwidth_fraction":halfwidth,
        "spanning_blocks":len(spanning),"reference_cells":int(ref.sum()),
        "reference_whole_native_area_km2":int(ref.sum())*.0049,
        "reference_cell_fraction":float(ref.mean()),
        "endpoint_status":"BLOCK_SPANNED" if len(spanning) else "NO_BLOCK_SPANS_BOTH_ENDPOINTS"}
    for label, point in (("lower",f0),("upper",f1)):
        mask,lo,hi=band_mask(frame.canopy_fraction,point,halfwidth); masks.append(mask)
        result.update({label+"_band_lo":lo,label+"_band_hi":hi,label+"_cells":int(mask.sum()),
            label+"_blocks":int(frame.loc[mask,"block"].nunique()),label+"_cells_in_reference":int((mask&ref).sum()),
            label+"_fraction":float(mask.mean()),label+"_density_per_fraction":float(mask.mean()/(hi-lo))})
    lower_blocks=set(frame.loc[masks[0],"block"]);upper_blocks=set(frame.loc[masks[1],"block"])
    result["blocks_with_both_neighbourhoods"]=len(lower_blocks&upper_blocks)
    result["cells_in_both_neighbourhoods"]=int((masks[0]&masks[1]).sum())
    return result, masks, ref


def distribution(values):
    a=np.asarray(values,float)
    if not np.isfinite(a).all():raise ValueError("Nonfinite predictor")
    if not len(a):return {"n":0,**{k:None for k in ("min","p05","p25","median","p75","p95","max","mean","sd")}}
    q=np.quantile(a,[0,.05,.25,.5,.75,.95,1])
    return dict(n=len(a),**dict(zip(("min","p05","p25","median","p75","p95","max"),map(float,q))),mean=float(a.mean()),sd=float(a.std(ddof=1)) if len(a)>1 else None)


@dataclass
class PredictorDesign:
    names: tuple
    kept_indices: list
    block_labels: np.ndarray
    row_blocks: np.ndarray
    means: np.ndarray
    norms: np.ndarray
    scaled: np.ndarray
    xx: np.ndarray
    diagnostics: dict


def protected_design(frame, quadratic=True, context=CONTEXT):
    """Transform raw f² first. Select dependent context without using canopy/Y.

    Both canopy terms remain mandatory; confounding with either is a failure,
    never a reason to discard that protected term or a retained control.
    """
    f=frame.canopy_fraction.to_numpy(float)
    if not np.isfinite(f).all() or ((f<0)|(f>1)).any():raise ValueError("Invalid canopy fraction")
    basis=np.column_stack((f,f*f)) if quadratic else f[:,None]
    bcount=basis.shape[1]
    names=("canopy_fraction","canopy_squared") if quadratic else ("canopy_fraction",)
    names=(*names,*context)
    x=np.column_stack((basis,frame[list(context)].to_numpy(float))) if context else basis
    if not np.isfinite(x).all():raise ValueError("Nonfinite predictor design")
    labels,bi=np.unique(frame.block.astype(str),return_inverse=True)
    counts=np.bincount(bi);means=_group_sum(x,bi,len(labels))/counts[:,None]
    xc=x-means[bi];norms=np.sqrt((xc*xc).sum(axis=0))
    if (norms[:bcount]<=1e-12).any():raise ValueError("Protected canopy term has no within-block information")
    candidates=[j for j in range(bcount,x.shape[1]) if norms[j]>1e-12]
    keep=[]
    if candidates:
        z=xc[:,candidates]/norms[candidates]
        _,r,pivot=qr(z,mode="economic",pivoting=True)
        rank=int((np.abs(np.diag(r))>1e-10).sum())
        keep=sorted(candidates[j] for j in pivot[:rank])
    chosen=[*range(bcount),*keep];a=xc[:,chosen]/norms[chosen]
    s=np.linalg.svd(a,compute_uv=False);rank=int((s>1e-10).sum())
    p=len(chosen);dof=len(frame)-len(labels)-p
    if rank!=p or dof<=0:raise ValueError("Protected canopy design not identifiable after context/block adjustment")
    xx=np.empty((len(labels),p,p))
    for i in range(p):
        for j in range(i,p):xx[:,i,j]=xx[:,j,i]=np.bincount(bi,weights=a[:,i]*a[:,j],minlength=len(labels))
    target=1 if quadratic else 0
    others=[j for j in range(p) if j!=target]
    residual=xc[:,chosen[target]]-a[:,others]@np.linalg.lstsq(a[:,others],xc[:,chosen[target]],rcond=1e-10)[0] if others else xc[:,chosen[target]]
    info=np.bincount(bi,weights=residual*residual,minlength=len(labels));total=float(info.sum())
    shares=info/total
    diagnostics=dict(status="ESTIMABLE_DESIGN",n_cells=len(frame),n_blocks=len(labels),n_parameters=p,rank=rank,
        residual_dof=dof,protected_terms=bcount,removed_context_terms=[names[j] for j in range(bcount,len(names)) if j not in keep],
        scaled_design_condition=float(s[0]/s[-1]),scaled_design_smallest_singular=float(s[-1]),
        partial_canopy_term="raw_f_squared" if quadratic else "raw_f",partial_canopy_information=total,
        partial_canopy_effective_information_blocks=float(1/np.sum(shares**2)),
        maximum_partial_canopy_information_share=float(shares.max()),
        top_five_partial_canopy_information_share=float(np.sort(shares)[-5:].sum()))
    return PredictorDesign(tuple(names[j] for j in chosen),chosen,labels,bi,means[:,chosen],norms[chosen],a,xx,diagnostics)


def group_statistics(design, size):
    if size not in (1,8):raise ValueError("Frozen groups are 1km/8km")
    labels=np.array([f"{int(v.split('_')[0])//size}_{int(v.split('_')[1])//size}" for v in design.block_labels])
    groups,inv=np.unique(labels,return_inverse=True)
    return groups,inv,_group_sum(design.xx,inv,len(groups))


def resampled_design_rank(linear, quadratic, *, size, replicates, seed):
    g,_,lx=group_statistics(linear,size);gq,_,qx=group_statistics(quadratic,size)
    if not np.array_equal(g,gq) or len(g)<2:raise ValueError("Physical resampling universe mismatch/insufficient groups")
    rng=np.random.default_rng(seed);valid=np.zeros((replicates,2),bool);h=hashlib.sha256()
    for i in range(replicates):
        w=rng.multinomial(len(g),np.full(len(g),1/len(g)));h.update(w.astype("<i8").tobytes())
        for j,xx in enumerate((lx,qx)):valid[i,j]=np.linalg.matrix_rank(np.einsum("g,gij->ij",w,xx),tol=1e-10)==xx.shape[1]
    return dict(group_km=size,groups=len(g),requested=replicates,linear_estimable=int(valid[:,0].sum()),quadratic_estimable=int(valid[:,1].sum()),
        paired_estimable=int(valid.all(axis=1).sum()),paired_failed=int((~valid.all(axis=1)).sum()),
        draw_multiplicity_sha256=h.hexdigest(),linear_failed_indices=np.flatnonzero(~valid[:,0]).tolist(),quadratic_failed_indices=np.flatnonzero(~valid[:,1]).tolist())


def quadratic_contrast(coefficients, f0, f1):
    """Positive cooling; both raw basis columns change at the endpoints."""
    b=np.asarray(coefficients,float)
    return -(b[0]*(f1-f0)+b[1]*(f1*f1-f0*f0))


def weighted_scaling(samples):
    """Equal city, equal pass within city, equal sampled cell within pass."""
    cities=sorted({s["city"] for s in samples});means=[];seconds=[]
    for city in cities:
        q=[s["values"] for s in samples if s["city"]==city]
        means.append(np.mean([x.mean(axis=0) for x in q],axis=0))
        seconds.append(np.mean([(x*x).mean(axis=0) for x in q],axis=0))
    mean=np.mean(means,axis=0);sd=np.sqrt(np.maximum(np.mean(seconds,axis=0)-mean*mean,0))
    return mean,sd


def cross_distances(query, reference, mean, sd):
    keep=sd>0
    if not len(query) or not len(reference) or not keep.any():return None
    q=(query[:,keep]-mean[keep])/sd[keep];r=(reference[:,keep]-mean[keep])/sd[keep]
    distances=cKDTree(r).query(q,k=1,workers=1)[0]
    return distribution(distances)
