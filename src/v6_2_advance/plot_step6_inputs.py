"""Public nonthermal weather and temporal-support figures only."""
import argparse
import json
import shutil
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from .run_step6_inputs import PACKET, dest

COLORS={"morning":"#287a8f","afternoon":"#ca7424","outside_windows":"#77818b"}


def plot_prepare():
 d=pd.read_csv(dest("acquisition_conditions.csv"));PACKET.mkdir(parents=True,exist_ok=True)
 fig,axes=plt.subplots(1,2,figsize=(12,7),constrained_layout=True)
 for ax,city in zip(axes,("phoenix","atlanta")):
  q=d[d.city.eq(city)].sort_values("date");y=np.arange(len(q))
  ax.axvspan(9.5,11.5,color=COLORS["morning"],alpha=.1)
  ax.axvspan(15,18,color=COLORS["afternoon"],alpha=.1)
  for j,r in enumerate(q.itertuples()):
   ax.scatter(r.apparent_solar_hour,j,c=COLORS[r.time_arm],s=85 if r.window_weight else 45,
              marker="s" if r.window_weight else "o",edgecolors="white",zorder=3)
  ax.set(yticks=y,yticklabels=q.date,xlim=(9,18.5),xlabel="Apparent solar time (hours)",title=city.title())
  ax.invert_yaxis();ax.grid(axis="x",alpha=.2)
 fig.suptitle("2023 acquisition coverage — all sixteen original passes",fontsize=15)
 fig.supxlabel("Shaded windows: 09:30–11:30 and 15:00–18:00. Squares: the five frozen Phoenix comparison dates.\n"
  "Dates are distinct sampling units; shaded windows do not make weather or season comparable.",fontsize=10)
 p=dest("month_time_support.png");fig.savefig(p,dpi=180);plt.close(fig);shutil.copy2(p,PACKET/p.name)
 fig,axes=plt.subplots(1,2,figsize=(12,7))
 fig.subplots_adjust(left=.10,right=.97,top=.89,bottom=.24,wspace=.35)
 for ax,city in zip(axes,("phoenix","atlanta")):
  q=d[d.city.eq(city)].sort_values("date")
  for j,r in enumerate(q.itertuples()):
   ax.scatter(r.air_temperature_K-273.15,j,c=COLORS[r.time_arm],s=85 if r.window_weight else 45,
              marker="s" if r.window_weight else "o",edgecolors="white",zorder=3)
   ax.annotate(f"{r.air_temperature_K-273.15:.1f}",(r.air_temperature_K-273.15,j),xytext=(7,0),textcoords="offset points",va="center",fontsize=9)
  ax.set(yticks=np.arange(len(q)),yticklabels=q.date,xlabel="HRRR 2 m air temperature (°C)",title=city.title())
  ax.invert_yaxis();ax.margins(x=.25);ax.grid(axis="x",alpha=.2)
 handles=[plt.Line2D([],[],marker="o",ls="",color=c,label=a.replace("_"," ")) for a,c in COLORS.items()]
 fig.legend(handles=handles,loc="lower center",bbox_to_anchor=(.5,.015),ncol=3,frameon=False)
 fig.suptitle("Acquisition-linked weather — temperature is complete for every pass",fontsize=14)
 fig.supxlabel("Frozen city-domain means, interpolated between exact bracketing hourly f00 analyses.\n"
  "These are modeled air temperatures, not satellite surface temperatures or cooling effects.",fontsize=10,y=.075)
 p=dest("air_temperature_conditions.png");fig.savefig(p,dpi=180);plt.close(fig);shutil.copy2(p,PACKET/p.name)


def plot_rain():
 d=pd.read_csv(dest("antecedent_rainfall.csv"));fig,axes=plt.subplots(1,2,figsize=(12,7),constrained_layout=True)
 for ax,city in zip(axes,("phoenix","atlanta")):
  q=d[d.city.eq(city)];orbits=q.sort_values("acquisition_utc").orbit.drop_duplicates().tolist()
  y=np.arange(len(orbits))
  for j,(days,color) in enumerate(((1,"#a8c9b8"),(3,"#579e9a"),(7,"#226476"))):
   x=q[q.days.eq(days)].set_index("orbit").loc[orbits]
   bars=ax.barh(y+(j-1)*.24,x.total_mm,height=.22,color=color,label=f"{days} day"+('s' if days>1 else ''))
   for k,(_,row) in enumerate(x.iterrows()):
    if row['product']=='NOAA_Stage_IV':
     bars[k].set_hatch('///');bars[k].set_edgecolor('#222222')
     ax.annotate('Stage IV',(row.total_mm,k+(j-1)*.24),xytext=(4,0),textcoords='offset points',fontsize=8,va='center')
   for k,v in enumerate(x.total_mm):
    if pd.isna(v):ax.text(0,k+(j-1)*.24,"missing",fontsize=7)
  dates=q.drop_duplicates("orbit").set_index("orbit").loc[orbits].acquisition_utc.str[:10]
  ax.set(yticks=y,yticklabels=dates,xlabel="Area-weighted antecedent rainfall (mm)",title=city.title());ax.invert_yaxis();ax.grid(axis="x",alpha=.15)
 axes[0].legend(frameon=False)
 fig.suptitle("Antecedent rainfall — MRMS with one labeled Stage IV fallback",fontsize=14)
 fig.supxlabel("24, 72 and 168 complete hours ending at floor(acquisition UTC); subhour gaps are recorded.\n"
  "Hatched July 29 seven-day bar uses a different product; it need not exceed the MRMS three-day estimate.",fontsize=10)
 p=dest("antecedent_rainfall.png");fig.savefig(p,dpi=180);plt.close(fig);shutil.copy2(p,PACKET/p.name)


if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("action",choices=["prepare","rain"]);a=p.parse_args()
 plot_prepare() if a.action=="prepare" else plot_rain()
