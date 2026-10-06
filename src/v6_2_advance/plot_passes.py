"""Disclose authorized exploratory LST gradients and plot before a new time model."""
from pathlib import Path
import json,sys,hashlib,datetime
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
OUT=ROOT/'deliverables/Methodology_and_Expansion_v6_2_20260921';OUT.mkdir(parents=True,exist_ok=True)
P=lambda n:guarded_output_path(ROOT,'scientific','exploratory_review_20260921/'+n);P('gradient_disclosure.json').parent.mkdir(parents=True,exist_ok=True)
record={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'authorization':'User explicitly requested gradients on 19 September and on 21 September requested continued implementation and increased passes after discussing the pass-level plot.','scope':'LST signed city-pass gradients and bootstrap precision/interval derivatives only, original Phoenix+Atlanta and six additional Phoenix passes. Raw coefficients and bootstraps remain in sealed model storage; no release of prior time-comparison effects.','analysis_status':'exploratory_after_prior_disclosure','new_time_regression_fitted':False,'original_pilot_artifacts':'unchanged'}
P('gradient_disclosure.json').write_text(json.dumps(record,indent=2))
metadata=pd.read_csv(ROOT/'docs/v2/hitl/G3_SAMPLING_DESIGN/angle_threshold_pass_detail_existing_five.csv').drop_duplicates(['city','orbit']).set_index(['city','orbit'])
frames=[]
for city,runid in [('phoenix','pooled_pilot_20260919_phoenix'),('atlanta','pooled_pilot_20260919_atlanta'),('phoenix','pooled_extension_20260921_phoenix')]:
 public=ROOT/'outputs/v6_2/scientific'/runid;sealed=ROOT/'outputs/v6_2/sealed_coefficients'/runid
 df=pd.read_csv(public/'precision.csv');stress=pd.read_csv(public/'spatial_stress_precision.csv') if (public/'spatial_stress_precision.csv').exists() else df
 for _,row in df[df.variant=='paired_primary'].iterrows():
  orbit=int(row.pass_id.split(':')[1]);meta=metadata.loc[(city,orbit)];r=row.to_dict();r.update(orbit=orbit,run_id=runid,sample='Original pilot' if 'pilot_20260919' in runid else 'Added 21 Sep',solar_hour=float(meta.local_solar_time_hours),date=str(meta.acquisition_utc)[:10],vpd_kpa_inherited_metadata=meta.vpd_kpa_at_acquisition,month=int(str(meta.acquisition_utc)[5:7]),clear_domain_fraction_inherited=meta.clear_domain_fraction)
  for size in [1,2,4,8]:
   name='paired_primary' if size==1 else f'spatial_{size}km'
   with np.load(sealed/f'{orbit}_{name}_SEALED.npz',allow_pickle=True) as z:
    gradient=float(.1*z['coefficients'][0,0]);boot=.1*z['bootstrap_coefficients'][:,0,0]
   if size==1:r['gradient_K_per_10pp']=gradient;r['cooling_K_per_10pp']=-gradient
   else:assert np.isclose(r['gradient_K_per_10pp'],gradient,atol=1e-10),'Resampling should not change the mean model'
   r[f'SE_{size}km_K_per_10pp']=float(np.nanstd(boot,ddof=1));r[f'cooling_q025_{size}km']=float(np.nanquantile(-boot,.025));r[f'cooling_q975_{size}km']=float(np.nanquantile(-boot,.975))
  frames.append(r)
d=pd.DataFrame(frames).sort_values(['city','acquisition_utc']);d['analysis_status']='exploratory; 2023 candidate frame; not full archive'
d.to_csv(P('pass_gradients_exploratory.csv'),index=False);d.to_csv(OUT/'pass_gradients_exploratory.csv',index=False)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(1,2,figsize=(13,5.7),sharey=True);colors={6:'#2878b5',7:'#e69f00',8:'#ad4fa5',9:'#25856d'}
for ax,city in zip(axes,['phoenix','atlanta']):
 q=d[d.city==city]
 for _,r in q.iterrows():
  x=r.solar_hour;y=r.cooling_K_per_10pp;c=colors[r.month];marker='s' if r['sample'].startswith('Added') else 'o'
  ax.vlines(x,r.cooling_q025_8km,r.cooling_q975_8km,color=c,alpha=.65,linewidth=1.4)
  ax.scatter([x],[y],color=c,s=62,marker=marker,edgecolor='white',linewidth=.7,zorder=3)
  offset={27963:(12,-15),28909:(-38,18),29545:(10,5),28024:(8,16),28970:(-53,8),29606:(8,-11)}.get(int(r.orbit),(5,6))
  ax.annotate(r.date[5:],(x,y),xytext=offset,textcoords='offset points',fontsize=8.5,color='#394453')
 ax.axvline(10.5,color='#9299a1',lw=.8,ls='--');ax.axvline(16,color='#9299a1',lw=.8,ls='--');ax.axhline(0,color='#aab0b6',lw=.8)
 ax.set_title(f'{city.title()} · {len(q)} passes',loc='left',weight='bold');ax.set_xlim(9.7,17.7);ax.set_xlabel('Apparent local solar time (hours)');ax.grid(axis='y',alpha=.14)
axes[0].set_ylabel('Canopy-associated cooling (K per +10 pp canopy)\nPositive = lower mixed-pixel LST');axes[0].set_ylim(-.05,max(d.cooling_q975_8km)+.20)
from matplotlib.lines import Line2D
legend=[Line2D([0],[0],color=c,marker='o',ls='',label={6:'June',7:'July',8:'August',9:'September'}[m]) for m,c in colors.items()]+[Line2D([0],[0],color='#555',marker='s',ls='',label='Added Phoenix pass')]
fig.legend(handles=legend,loc='lower center',ncol=5,bbox_to_anchor=(.5,.05),frameon=False)
fig.suptitle('Canopy-associated surface cooling across observed overpass times',x=.08,ha='left',weight='bold',fontsize=16)
fig.text(.08,.02,'2023 observations · Bars: 95% percentile intervals from 8 km spatial-group bootstrap · No time regression fitted',fontsize=10,color='#4b5563')
fig.subplots_adjust(left=.08,right=.98,top=.83,bottom=.22,wspace=.12)
fig.savefig(OUT/'pass_gradients_vs_solar_time.png',dpi=170);fig.savefig(OUT/'pass_gradients_vs_solar_time.pdf');plt.close(fig)
# Temporal coverage reveals which months actually inform each time region.
fig,axes=plt.subplots(1,2,figsize=(12,4.5),sharey=True)
for ax,city in zip(axes,['phoenix','atlanta']):
 q=d[d.city==city].copy();dates=pd.to_datetime(q.date);ax.scatter(q.solar_hour,dates,c=[colors[m] for m in q.month],s=65,edgecolor='white');ax.set_title(city.title(),loc='left',weight='bold');ax.set_xlabel('Apparent local solar time (hours)');ax.set_xlim(9.7,17.7);ax.grid(alpha=.2)
 import matplotlib.dates as mdates
 ax.yaxis.set_major_locator(mdates.MonthLocator());ax.yaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
fig.suptitle('More passes still need overlap between time of day and season',x=.08,ha='left',weight='bold');fig.tight_layout(rect=(0,.03,1,.92));fig.savefig(OUT/'time_season_coverage.png',dpi=160);plt.close(fig)
summary={'passes':d.groupby('city').size().to_dict(),'phoenix_primary_SE_range':d[d.city=='phoenix'].SE_1km_K_per_10pp.agg(['min','max']).to_dict(),'phoenix_8km_SE_range':d[d.city=='phoenix'].SE_8km_K_per_10pp.agg(['min','max']).to_dict(),'stage1_below_0_10_benchmark_8km':d.assign(below=d.SE_8km_K_per_10pp<=.10).groupby('city').below.sum().to_dict(),'new_time_regression_fitted':False,'source_precision_files':[str(p.relative_to(ROOT)) for p in [ROOT/'outputs/v6_2/scientific/pooled_extension_20260921_phoenix/precision.csv']]}
P('expansion_summary.json').write_text(json.dumps(summary,indent=2));(OUT/'expansion_summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
