"""Readable released figures; archived source figures remain unchanged."""
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[5]
OUT=ROOT/'deliverables/Pilot_Results_Review_2023_v6_2_20261006'
plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False})

def forest(ax,d,labels,point='point',lo='q025',hi='q975',color='#187d89'):
 y=np.arange(len(d));ax.hlines(y,d[lo],d[hi],color=color,lw=2);ax.scatter(d[point],y,color=color,s=42,zorder=3)
 ax.set(yticks=y,yticklabels=labels);ax.invert_yaxis();ax.axvline(0,color='#9aa1a7',lw=.8);ax.grid(axis='x',alpha=.15)

def save(fig,name,footnote):
 fig.supxlabel(footnote,fontsize=9);fig.savefig(OUT/name,dpi=180);plt.close(fig)

def main():
 w=pd.read_csv(OUT/'phoenix_window_comparisons.csv');w=w[w.group_km.eq(8)]
 j=pd.read_csv(OUT/'joint_window_sensitivities.csv');j=j[j.group_km.eq(8)]
 fig,axes=plt.subplots(1,2,figsize=(13,5.5),layout='constrained')
 q=w[w.quantity.eq('temperature')].set_index('comparison').loc[['combined','June','August','drop_Aug06','drop_Aug23']]
 forest(axes[0],q,['June + August','June','August','Omit August 6','Omit August 23'])
 axes[0].set(title='Original populations: fixed-date contrasts',xlabel='Afternoon − morning cooling (K per +10pp canopy)')
 q=j[j.quantity.eq('temperature')].set_index('comparison').loc[['original','common','quadratic']]
 forest(axes[1],q,['Linear, original footprint','Linear, common footprint','Quadratic, original footprint'],color='#8153a0')
 axes[1].set(title='Matched sensitivity comparison',xlabel='Afternoon − morning cooling (K per +10pp canopy)')
 fig.suptitle('Phoenix: weaker afternoon cooling on the selected 2023 dates',fontsize=15)
 save(fig,'phoenix_time_comparison.png','95% spatial intervals using 8 km groups; dates and weights held fixed. Right panel is a recorded post-disclosure follow-up.\nThese intervals do not establish a general summer or causal time-of-day effect.')
 c=pd.read_csv(OUT/'common_footprint_comparisons.csv');c=c[c.group_km.eq(8)&c.quantity.eq('temperature')].sort_values('date')
 fig,axes=plt.subplots(1,2,figsize=(12,6),layout='constrained')
 for offset,label,color in [(-.15,'original','#356b91'),(.15,'common','#29927b')]:
  y=np.arange(len(c))+offset;axes[0].hlines(y,c[label+'_q025'],c[label+'_q975'],color=color);axes[0].scatter(c[label+'_point'],y,color=color,label=label.capitalize())
 axes[0].set(yticks=np.arange(len(c)),yticklabels=c.date.str[5:],xlabel='Cooling (K per +10pp)',title='Original and common populations');axes[0].invert_yaxis();axes[0].legend(frameon=False)
 forest(axes[1],c,c.date.str[5:],'common_minus_original_point','common_minus_original_q025','common_minus_original_q975',color='#8153a0')
 axes[1].set(xlabel='Common − original cooling (K per +10pp)',title='Paired population-sensitivity changes')
 fig.suptitle('Common-footprint estimates are lower for all eleven Phoenix passes',fontsize=14)
 save(fig,'common_footprint_review.png','8 km spatial percentile intervals. The common footprint retains 35%–57% of each original pass and represents a different population.\nNo retrospective sample selection or new adequacy cutoff was applied.')
 q=pd.read_csv(OUT/'quadratic_historical_contrasts.csv');q=q[q.group_km.eq(8)&q.model.eq('quadratic_minus_linear')]
 fig,axes=plt.subplots(1,2,figsize=(12,6),layout='constrained')
 for ax,city in zip(axes,['phoenix','atlanta']):
  d=q[q.city.eq(city)].sort_values('date');forest(ax,d,d.date.str[5:],color='#187d89');ax.set(title=city.title(),xlabel='Quadratic − linear cooling (K per +10pp)',xlim=(-.11,.18))
 fig.suptitle('Model sensitivity at the historical 2.85% → 12.85% canopy endpoints',fontsize=14)
 save(fig,'quadratic_model_review.png','Paired 8 km spatial intervals. Both models use the same original cells and six controls.\nIndividual exploratory intervals are not multiplicity-adjusted; endpoint/context support differs between cities.')
 fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout='constrained');order=['combined','June','August']
 for offset,quantity,color,label in [(-.13,'temperature','#187d89','Temperature primary'),(.13,'temperature_equivalent','#b27a29','Energy equivalent diagnostic')]:
  d=w[w.quantity.eq(quantity)].set_index('comparison').loc[order];y=np.arange(3)+offset
  axes[0].hlines(y,d.q025,d.q975,color=color,lw=2);axes[0].scatter(d.point,y,color=color,label=label)
 axes[0].set(yticks=np.arange(3),yticklabels=['June + August','June','August'],xlabel='Afternoon − morning cooling (K per +10pp)',title='Same direction; different magnitudes');axes[0].invert_yaxis();axes[0].legend(frameon=False,fontsize=9)
 d=w[w.quantity.eq('temperature_minus_equivalent')].set_index('comparison').loc[order]
 forest(axes[1],d,['June + August','June','August'],color='#8153a0');axes[1].set(xlabel='Temperature − energy-equivalent contrast (K per +10pp)',title='Paired diagnostic discrepancy')
 fig.suptitle('Temperature–energy comparison: descriptive release, no agreement ruling',fontsize=14)
 save(fig,'temperature_energy_review.png','8 km paired spatial intervals. Flux is averaged within each arm before exact reference conversion.\nThe two routes share the same retrievals; they are not independent validation. No numerical agreement tolerance has been chosen.')
 f=pd.read_csv(OUT/'fixed_registration_comparisons.csv');f=f[f.quantity.eq('temperature')].sort_values(['date','variant'])
 labels=f.date.str[5:]+' · '+f.variant.str.replace('registration_fixed_support_','',regex=False)
 fig,ax=plt.subplots(figsize=(10,8.5),layout='constrained');forest(ax,f,labels);ax.tick_params(axis='y',labelsize=8)
 ax.set(title='One-cell alignment stress tests on identical cells',xlabel='Shifted − unshifted cooling (K per +10pp canopy)')
 save(fig,'registration_review.png','24 one-native-cell (70 m) perturbations across six added Phoenix passes; inherited paired 1 km spatial intervals.\nThis measures sensitivity to imposed shifts; it does not establish actual misregistration.')
 p=pd.read_csv(OUT/'paired_scale_diagnostics.csv');p=p[p.group_km.eq(8)]
 fig,axes=plt.subplots(1,2,figsize=(12,6),layout='constrained')
 for ax,city in zip(axes,['phoenix','atlanta']):
  d=p[p.city.eq(city)].sort_values('date');forest(ax,d,d.date.str[5:],'difference','difference_q025','difference_q975')
  ax.set(title=city.title(),xlabel='Temperature − energy-equivalent cooling (K per +10pp)')
 fig.suptitle('Paired pass-level discrepancies at the fixed reference',fontsize=14)
 save(fig,'paired_pass_review.png','8 km paired spatial intervals; different horizontal scales by city. No practical equivalence or scale agreement is declared.')
 print('Six released review figures rendered')

if __name__=='__main__':main()
