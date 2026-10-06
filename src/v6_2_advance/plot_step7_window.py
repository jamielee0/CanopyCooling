"""Sealed effect figures, public precision and clearly labelled synthetic coverage."""
import argparse
import json
import os
import shutil
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image
from .run_step7_window import ROOT,RUN,EXEC,PACKET,public,synthetic,sha,write
from .quadratic_sensitivity import sealed_path

def empirical():
 os.umask(0o077);PACKET.mkdir(parents=True,exist_ok=True)
 records=json.loads(sealed_path(ROOT,RUN,'phoenix_window_comparisons_SEALED.json').read_text());data=pd.DataFrame(records);qa=[]
 for size in (1,8):
  fig,ax=plt.subplots(figsize=(9,5),layout='constrained')
  order=['combined','June','August','drop_Aug06','drop_Aug23','influence_Aug06','influence_Aug23']
  d=data[data.quantity.eq('temperature')&data.group_km.eq(size)].set_index('comparison').loc[order]
  if d.point.isna().any():raise ValueError('Non-estimable contrast needs explicit figure handling')
  # Percentile endpoints need not surround a point, so draw segments independently.
  ax.hlines(np.arange(len(d)),d.q025,d.q975,color='#217f87');ax.scatter(d.point,np.arange(len(d)),color='#217f87')
  ax.axvline(0,color='#aaa',lw=.8);ax.set(yticks=np.arange(len(d)),yticklabels=order,
   xlabel='Afternoon-minus-morning canopy cooling (K per +10pp)',title=f'Phoenix fixed dates · {size} km whole-group intervals')
  ax.invert_yaxis();fig.supxlabel('Influence rows are deletion-minus-full differences. June11, June26 and August11 deletions are unsupported.\nFixed-date spatial uncertainty only; no general summer interval.',fontsize=9)
  p=sealed_path(ROOT,RUN,f'phoenix_{size}km_comparisons_SEALED.png');fig.savefig(p,dpi=180);plt.close(fig);p.chmod(0o600)
  with Image.open(p) as im:im.verify()
  with Image.open(p) as im:
   if np.asarray(im.convert('RGB')).std()<5:raise ValueError('Blank sealed figure')
   pixels=[im.width,im.height]
  qa.append(dict(path=str(p.relative_to(ROOT)),sha256=sha(p),pixels=pixels,visually_reviewed=False))
 d=pd.read_csv(public('fixed_date_precision.csv'));d=d[d.quantity.eq('temperature')]
 fig,ax=plt.subplots(figsize=(10,5),layout='constrained')
 order=['combined','June','August','drop_Aug06','drop_Aug23','influence_Aug06','influence_Aug23'];y=np.arange(len(order))
 for size,shift,color in [(1,-.17,'#80b9b0'),(8,.17,'#176775')]:
  q=d[d.group_km.eq(size)].set_index('comparison').loc[order]
  ax.barh(y+shift,q.SE,height=.3,color=color,label=f'{size} km groups')
 ax.set(yticks=y,yticklabels=order,xlabel='Spatial bootstrap SE (K per +10pp)',title='Fixed-date precision only — new time effects remain sealed');ax.invert_yaxis();ax.legend(frameon=False)
 fig.supxlabel('Same physical-group multiplicities across dates. Spatial precision does not supply additional independent days.',fontsize=9)
 p=public('fixed_date_precision.png');fig.savefig(p,dpi=180);plt.close(fig);shutil.copy2(p,PACKET/p.name)
 write(EXEC/'empirical_figure_verification.json',dict(sealed_figures=qa,effect_visual_review='DEFERRED_UNDER_SEALING'))
 for name in ('fixed_date_precision.csv','resampling_audit.json','unsupported_deletions.json','empirical_completion.json'):
  shutil.copy2(public(name),PACKET/name)

def calibration():
 d=pd.read_csv(synthetic('SYNTHETIC_DATA_production_calibration.csv'))
 methods=['oracle_known_variance','fixed_date_spatial_only','existing_day_slope_bootstrap','stratified_window_day_bootstrap','moment_separated_t','double_spatial_noise_negative_control']
 labels=['Oracle: known variance','Spatial only','Existing day-slope bootstrap','Within-arm day bootstrap','Separated variance + t','Extra spatial noise control']
 profiles=['linear','season_offsets','curved_time','month_slope','heterogeneous_day','serial_days']
 fig,axes=plt.subplots(1,2,figsize=(14,6),layout='constrained')
 for ax,city in zip(axes,('phoenix','atlanta')):
  a=d[d.city.eq(city)].pivot_table(index='method',columns='profile',values='population_target_coverage',aggfunc='min').loc[methods,profiles]
  im=ax.imshow(a.to_numpy(),vmin=0,vmax=1,cmap='viridis',aspect='auto')
  ax.set(xticks=np.arange(6),xticklabels=['Linear','Season','Curved','Month slope','Unequal days','Serial days'],yticks=np.arange(6),yticklabels=labels,title=city.title())
  ax.tick_params(axis='x',rotation=35)
  for i in range(6):
   for j in range(6):ax.text(j,i,f'{a.iloc[i,j]*100:.1f}%',ha='center',va='center',color='white' if a.iloc[i,j]<.65 else 'black',fontsize=9)
 fig.colorbar(im,ax=axes,label='Minimum coverage across the frozen amplitude / day-SD / spatial-correlation grid',shrink=.8)
 fig.suptitle('SYNTHETIC DATA — population-target interval coverage under actual sampling schedules',fontsize=14)
 fig.supxlabel('Nominal 95%. 2,000 datasets per scenario; minima are exploratory stress summaries.\nSynthetic scheduled-date targets, not observed cooling or a validated general-season result.',fontsize=10)
 p=synthetic('SYNTHETIC_DATA_coverage.png');fig.savefig(p,dpi=180);plt.close(fig);shutil.copy2(p,PACKET/p.name)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('kind',choices=['empirical','calibration']);args=p.parse_args()
 empirical() if args.kind=='empirical' else calibration()
