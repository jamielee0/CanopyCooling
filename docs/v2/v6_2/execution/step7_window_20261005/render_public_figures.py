"""Layout-only refinement of public precision and synthetic coverage figures."""
from pathlib import Path
import sys
import shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[5];sys.path.insert(0,str(ROOT/'src'))
from v6_2_advance.run_step7_window import EXEC,PACKET,public,synthetic,sha,write

def main():
 qa=EXEC/'qa_initial_layout';qa.mkdir(exist_ok=True)
 for p in [public('fixed_date_precision.png'),synthetic('SYNTHETIC_DATA_coverage.png')]:
  if not (qa/p.name).exists():shutil.copy2(p,qa/p.name)
 d=pd.read_csv(public('fixed_date_precision.csv'));d=d[d.quantity.eq('temperature')]
 order=['combined','June','August','drop_Aug06','drop_Aug23','influence_Aug06','influence_Aug23']
 labels=['June + August','June','August','Omit August 6','Omit August 23','Change when omitting August 6','Change when omitting August 23']
 fig,ax=plt.subplots(figsize=(11,5),layout='constrained');y=np.arange(len(order))
 for size,offset,color in [(1,-.17,'#80b9b0'),(8,.17,'#176775')]:
  q=d[d.group_km.eq(size)].set_index('comparison').loc[order]
  ax.barh(y+offset,q.SE,height=.3,color=color,label=f'{size} km groups')
 ax.set(yticks=y,yticklabels=labels,xlabel='Spatial bootstrap SE (K per +10pp canopy)',title='Fixed-date precision only — new time effects remain sealed')
 ax.invert_yaxis();ax.legend(frameon=False);fig.supxlabel('The same physical-group draws are shared across dates. Spatial precision does not add independent days.',fontsize=9)
 p=public('fixed_date_precision.png');fig.savefig(p,dpi=180);plt.close(fig);shutil.copy2(p,PACKET/p.name)
 d=pd.read_csv(synthetic('SYNTHETIC_DATA_production_calibration.csv'))
 methods=['oracle_known_variance','fixed_date_spatial_only','existing_day_slope_bootstrap','stratified_window_day_bootstrap','moment_separated_t','double_spatial_noise_negative_control']
 labels=['Oracle: known variance','Spatial only','Existing day-slope bootstrap','Within-arm day bootstrap','Separated variance + t','Extra spatial noise control']
 profiles=['linear','season_offsets','curved_time','month_slope','heterogeneous_day','serial_days']
 fig,axes=plt.subplots(1,2,figsize=(14,7),layout='constrained')
 for ax,city in zip(axes,('phoenix','atlanta')):
  a=d[d.city.eq(city)].pivot_table(index='method',columns='profile',values='population_target_coverage',aggfunc='min').loc[methods,profiles]
  im=ax.imshow(a.to_numpy(),vmin=0,vmax=1,cmap='viridis',aspect='auto')
  ax.set(xticks=np.arange(6),xticklabels=['Linear','Season','Curved','Month slope','Unequal days','Serial days'],yticks=np.arange(6),yticklabels=labels,title=city.title())
  ax.tick_params(axis='x',rotation=30)
  for i in range(6):
   for j in range(6):ax.text(j,i,f'{a.iloc[i,j]*100:.1f}%',ha='center',va='center',color='white' if a.iloc[i,j]<.65 else 'black',fontsize=9)
 fig.colorbar(im,ax=axes,label='Minimum interval coverage',shrink=.7)
 fig.suptitle('SYNTHETIC DATA — coverage of population-target intervals',fontsize=15)
 fig.supxlabel('Nominal 95%. Each cell is the minimum across the frozen amplitude, day-variability and spatial-correlation scenarios.\n2,000 datasets per scenario; these are hypothetical scheduled-date targets, not observed cooling or a validated summer result.',fontsize=10)
 p=synthetic('SYNTHETIC_DATA_coverage.png');fig.savefig(p,dpi=180);plt.close(fig);shutil.copy2(p,PACKET/p.name)
 write(EXEC/'public_layout_record.json',dict(scientific_settings_changed=False,sealed_effects_read=False,
  reason='Shorter colorbar label and human-readable comparison names; no table/data changes',script_sha256=sha(Path(__file__))))

if __name__=='__main__':main()
