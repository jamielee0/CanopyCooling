"""Render the already-computed, explicitly synthetic mixing diagnostic."""
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
p=guarded_output_path(ROOT,'synthetic','mixing_20260919/SYNTHETIC_DATA_transformation_artifact.png').parent
s=pd.read_csv(p/'SYNTHETIC_DATA_mixing_pass_results.csv')
fig,axes=plt.subplots(1,2,figsize=(10,4),sharey=True,layout='constrained')
for ax,city in zip(axes,['phoenix','atlanta']):
 for delta in [2,5,10]:
  q=s[(s.city==city)&(s.scenario=='transformation_only')&(s.constant_component_contrast_K==delta)].sort_values('solar_hour')
  ax.plot(q.solar_hour,q.transformation_departure_K_per_10pp,marker='o',label=f'Component contrast {delta} K')
 ax.axhline(0,color='black',linewidth=.7);ax.set_title(city.title());ax.set_xlabel('Apparent local solar hour');ax.grid(alpha=.2)
axes[0].set_ylabel('Temperature-scale departure\n(K per 10 percentage points canopy)');axes[1].legend(fontsize=8)
fig.suptitle('SYNTHETIC DATA — constant tree–background temperature contrast',fontsize=13)
fig.savefig(p/'SYNTHETIC_DATA_transformation_artifact.png',dpi=180);plt.close(fig)
