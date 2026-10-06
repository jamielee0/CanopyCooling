"""Scientific predictor-only support figures; no empirical effect access."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path


def save(root,run,name,fig):
 for ext in ("png","pdf"):
  p=guarded_output_path(root,"scientific",f"{run}/{name}.{ext}");p.parent.mkdir(parents=True,exist_ok=True);fig.savefig(p,dpi=170)
 plt.close(fig)


def plot_support(root,run,endpoints,designs,draws,distances):
 plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.spines.top":False,"axes.spines.right":False})
 fig,axes=plt.subplots(1,2,figsize=(13,6))
 for ax,city in zip(axes,("phoenix","atlanta")):
  rows=sorted([r for r in endpoints if r["city"]==city and r["pair_id"]=="historical" and r["halfwidth_fraction"]==.01],key=lambda r:r["date"])
  y=np.arange(len(rows));lo=[r["lower_fraction"] for r in rows];hi=[r["upper_fraction"] for r in rows]
  ax.barh(y-.17,lo,height=.3,color="#2878b5",label="Lower endpoint neighbourhood")
  ax.barh(y+.17,hi,height=.3,color="#d77d00",label="Upper endpoint neighbourhood")
  ax.set_yticks(y,[r["date"][5:] for r in rows]);ax.invert_yaxis();ax.set_xlim(0,max(lo+hi)*1.13)
  ax.set_xlabel("Fraction of original cells within ±1 percentage point")
  ax.set_title(city.title(),loc="left",weight="bold");ax.grid(axis="x",alpha=.18);ax.set_axisbelow(True)
 axes[0].legend(loc="lower right",fontsize=9,frameon=False)
 fig.suptitle("Historical canopy pair · endpoint neighbourhood support",x=.08,ha="left",weight="bold",fontsize=17)
 fig.text(.08,.025,"Endpoints: 2.851% and 12.851% canopy. All cells retained. Wider neighbourhoods and block support are reported in the tables.",fontsize=9)
 fig.subplots_adjust(left=.08,right=.98,top=.86,bottom=.14,wspace=.25)
 save(root,run,"historical_endpoint_support",fig)
 fig,axes=plt.subplots(1,2,figsize=(14,6.4))
 for ax,city in zip(axes,("phoenix","atlanta")):
  rows=[r for r in endpoints if r["city"]==city and r["halfwidth_fraction"]==.01]
  dates=sorted({r["date"] for r in rows});pairs=sorted({(r["f0"],r["pair_id"]) for r in rows})
  values=np.array([[next(r["reference_cell_fraction"] for r in rows if r["date"]==d and r["pair_id"]==pair) for _,pair in pairs] for d in dates])
  image=ax.imshow(values,vmin=0,vmax=1,cmap="Blues",aspect="auto",interpolation="nearest")
  ax.set_yticks(range(len(dates)),[d[5:] for d in dates]);ax.set_xticks(range(len(pairs)),[f"{100*f:.1f}" for f,_ in pairs],rotation=65,ha="right",fontsize=8)
  ax.set_xlabel("Lower canopy endpoint (%) · upper endpoint = lower +10pp")
  ax.set_title(city.title(),loc="left",weight="bold")
 fig.colorbar(image,ax=axes.ravel().tolist(),fraction=.026,pad=.02,label="Fraction of original cells in blocks spanning both exact endpoints")
 fig.suptitle("Candidate contrasts · within-block range support",x=.07,ha="left",weight="bold",fontsize=17)
 fig.text(.07,.025,"Zero means no block spans the exact pair. Nonzero range support is not proof of conditional covariate overlap. No pair selected by outcomes.",fontsize=9)
 fig.subplots_adjust(left=.07,right=.88,top=.86,bottom=.23,wspace=.24)
 save(root,run,"candidate_pair_block_support",fig)
 fig,axes=plt.subplots(1,2,figsize=(13,6.2))
 for ax,city in zip(axes,("phoenix","atlanta")):
  rows=sorted([r for r in draws if r["city"]==city and r["group_km"]==8],key=lambda r:r["date"])
  y=np.arange(len(rows));a=[1000-r["linear_estimable"] for r in rows];b=[1000-r["quadratic_estimable"] for r in rows]
  ax.barh(y-.17,a,height=.3,color="#2878b5",label="Linear design")
  ax.barh(y+.17,b,height=.3,color="#9b4f96",label="Protected quadratic design")
  ax.set_yticks(y,[r["date"][5:] for r in rows]);ax.invert_yaxis();ax.set_xlim(0,max(1,max(a+b))*1.15)
  ax.set_xlabel("Non-estimable design resamples out of 1,000")
  ax.set_title(city.title()+" · 8km groups",loc="left",weight="bold");ax.grid(axis="x",alpha=.18);ax.set_axisbelow(True)
 axes[0].legend(loc="lower right",frameon=False,fontsize=9)
 fig.suptitle("Predictor-only resampling · design identifiability",x=.08,ha="left",weight="bold",fontsize=17)
 fig.text(.08,.025,"Same physical draws for both designs; no outcome fitted, no predictor removed or draw replaced to rescue a resample. 1km counts are in the table.",fontsize=9)
 fig.subplots_adjust(left=.08,right=.98,top=.86,bottom=.14,wspace=.25)
 save(root,run,"quadratic_design_rank_support",fig)
 fig,axes=plt.subplots(1,2,figsize=(12,5.5))
 for ax,endpoint in zip(axes,("lower","upper")):
  rows=sorted([r for r in distances if r["endpoint"]==endpoint and r["halfwidth_fraction"]==.025],key=lambda r:(r["city"],r["date"]))
  for i,r in enumerate(rows):
   if r["median"] is None:continue
   c="#2878b5" if r["city"]=="phoenix" else "#d77d00"
   ax.vlines(i,r["p05"],r["p95"],color=c,lw=1);ax.scatter(i,r["median"],color=c,s=30)
  ax.set_xticks(range(len(rows)),[r["city"][0].upper()+" "+r["date"][5:] for r in rows],rotation=70,ha="right",fontsize=8)
  ax.set_title(endpoint.title()+" endpoint · ±2.5pp",loc="left",weight="bold");ax.set_ylabel("Other-city nearest-neighbour distance")
  ax.grid(axis="y",alpha=.18)
 fig.suptitle("Joint context support · descriptive cross-city distances",x=.08,ha="left",weight="bold",fontsize=16)
 fig.text(.08,.025,"Six standardized controls; median and P5–P95 distances, not confidence intervals. Equal-size unique-cell reference pools; no cutoff or city-ranking claim.",fontsize=8.5)
 fig.subplots_adjust(left=.08,right=.98,top=.84,bottom=.27,wspace=.25)
 save(root,run,"cross_city_context_support",fig)
