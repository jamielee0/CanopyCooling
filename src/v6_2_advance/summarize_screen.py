from pathlib import Path
import json
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[2];E=ROOT/'docs/v2/v6_2/execution/advance_20260921';D=ROOT/'deliverables/Methodology_and_Expansion_v6_2_20260921'
s=pd.read_csv(E/'candidate_city_screen.csv');cloud=pd.read_csv(E/'afternoon_cloud_pass_screen.csv');summ=cloud.groupby('city').agg(afternoon_cloud_screened_passes=('orbit','nunique'),median_sample_point_coverage=('sample_point_coverage_fraction','median'),median_clear_fraction_of_observed=('clear_fraction_of_observed_points','median'),median_clear_fraction_of_all_points=('clear_fraction_of_all_sample_points','median'),summed_clear_area_equivalent_passes=('clear_fraction_of_all_sample_points','sum'),cloud_asset_failures=('failed_assets','sum')).reset_index()
s=s.merge(summ,on='city');unc=[]
for city in s.city:
 j=json.loads((E/f'{city}_canopy_screen.json').read_text());v=[r for r in j['blocks'] if r.get('count',0)>1 and r.get('variance') is not None];cnt=np.array([r['count'] for r in v]);ss=np.array([(r['count']-1)*r['variance'] for r in v]);rng=np.random.default_rng(20260921);ids=rng.integers(len(v),size=(2000,len(v)));b=ss[ids].sum(axis=1)/cnt[ids].sum(axis=1);lo,hi=np.quantile(b,[.025,.975]);unc.append({'city':city,'canopy_screen_q025':lo,'canopy_screen_q975':hi})
s=s.merge(pd.DataFrame(unc),on='city').sort_values('sampled_within_block_variance',ascending=False);s['variance_relative_to_phoenix']=s.sampled_within_block_variance/float(s.loc[s.city=='phoenix','sampled_within_block_variance'].iloc[0]);s['status']='provisional nonthermal screen; 2023 only; no final eligibility ruling';s.to_csv(D/'candidate_city_screen.csv',index=False)
names={'minneapolis_st_paul':'Minneapolis–St Paul','los_angeles':'Los Angeles','new_york':'New York','washington':'Washington–Arlington'}
labels=[names.get(c,c.replace('_',' ').title()) for c in s.city];yy=np.arange(len(s));fig,axes=plt.subplots(1,3,figsize=(14,10),gridspec_kw={'width_ratios':[1.4,1,1]})
axes[0].barh(yy,s.sampled_within_block_variance,color=['#ba7645' if c in ['phoenix','los_angeles'] else '#347c75' for c in s.city],height=.65);axes[0].errorbar(s.sampled_within_block_variance,yy,xerr=np.vstack([s.sampled_within_block_variance-s.canopy_screen_q025,s.canopy_screen_q975-s.sampled_within_block_variance]),fmt='none',color='#283a3b',lw=.7,capsize=2)
axes[0].set_yticks(yy,labels);axes[0].set_xlabel('Within-block canopy variance\n(fraction²; 300 sampled blocks)');axes[0].set_title('Canopy information first',loc='left',weight='bold')
axes[1].barh(yy,s.afternoon_1500_1800_passes,color='#597eaa',height=.65);axes[1].set_xlabel('Distinct afternoon acquisition passes\n15:00–18:00 apparent solar time');axes[1].set_title('Afternoon opportunities',loc='left',weight='bold')
axes[2].barh(yy,100*s.median_clear_fraction_of_all_points,color='#bf9244',height=.65);axes[2].set_xlabel('Median clear coverage (%)\nof all sampled urban-block points');axes[2].set_xlim(0,100);axes[2].set_title('Cloud masks checked',loc='left',weight='bold')
for ax in axes:
 ax.invert_yaxis();ax.spines[['right','top']].set_visible(False);ax.grid(axis='x',alpha=.14);ax.set_axisbelow(True)
for ax in axes[1:]:ax.set_yticks(yy,[])
fig.suptitle('U.S. candidate cities: canopy variation and observed afternoon opportunity',x=.17,ha='left',fontsize=15,weight='bold')
fig.text(.17,.025,'Census urban areas · June–September 2023 · Cloud masks only for new cities; no LST downloads\nCloud coverage is a sampled proxy, not final valid-cell coverage. Canopy error bars describe block-sampling uncertainty only.',fontsize=10,color='#48545d')
fig.subplots_adjust(left=.17,right=.98,top=.92,bottom=.18,wspace=.15);fig.savefig(D/'candidate_city_screen.png',dpi=155);fig.savefig(D/'candidate_city_screen.pdf');plt.close(fig)
print(s[['city','sampled_within_block_variance','afternoon_cloud_screened_passes','median_sample_point_coverage','median_clear_fraction_of_all_points','summed_clear_area_equivalent_passes']].round(4).to_string(index=False))
