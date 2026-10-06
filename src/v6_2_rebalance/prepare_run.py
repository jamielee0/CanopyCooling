from pathlib import Path
import json,hashlib,datetime,sys
import pandas as pd,numpy as np
ROOT=Path(sys.argv[1]).resolve();sys.path.insert(0,str(ROOT/'src/v6_2_rebalance'))
from sampling_design import balanced_weights,cloud_priority_split
out=ROOT/'docs/v2/v6_2/execution/rebalance_20260921'
d=pd.read_csv(out/'matched_year_month_candidates.csv');s=pd.read_csv(out/'cloud_screen_summary.csv');d=d.merge(s,on='orbit',validate='one_to_one')
p=pd.read_csv(out/'cloud_screen_points.csv').pivot(index='block',columns='orbit',values='clear')
groups=[]
for ym,g in d.groupby('year_month'):
    groups.append({'year_month':ym,'passes':len(g),'common_clear_points_all_passes':int(p[g.orbit].all(axis=1).sum()),'min_pass_clear_points':int(g.clear_points.min()),'sampled_blocks':len(p)})
groups=pd.DataFrame(groups)
lower,upper=cloud_priority_split(groups.common_clear_points_all_passes)
groups['batch_priority']=np.where(groups.common_clear_points_all_passes.ge(upper),'first_rebalance_batch','cloud_support_review_queue')
groups.to_csv(out/'matched_strata_cloud_support.csv',index=False)
chosen=d[d.year_month.isin(groups.loc[groups.batch_priority.eq('first_rebalance_batch'),'year_month'])].copy()
chosen=balanced_weights(chosen.drop(columns=['balanced_arm_weight','balanced_season_supported']))
chosen['balanced_design_weight']=chosen.balanced_arm_weight/2
chosen.to_csv(out/'balanced12_selection.csv',index=False)
added=chosen[~chosen.previously_processed_2023].copy();added.to_csv(out/'new7_selected_passes.csv',index=False)
current=pd.read_csv(out/'current11_rebalanced_roles.csv');current['balanced_design_weight']=current.balanced_arm_weight/2;current.to_csv(out/'current11_rebalanced_roles.csv',index=False)
freeze={'recorded_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'selection_inputs':'acquisition dates/times; definitive inherited geometry; cloud masks at frozen 300 sample blocks; no new LST or fitted gradients',
'priority_rationale':f'Among seven matched year-month strata, the largest observed gap in common clear block-point counts is {lower} to {upper} of 300. Prioritize the upper group for the bounded thermal batch. This is a documented distribution-based acquisition priority, not a universal cloud QA cutoff or permanent exclusion of the lower group; no target pass count was chosen.',
'cloud_support_distribution':groups.to_dict('records'),'selected_new_orbits':added.orbit.astype(int).tolist(),'balanced_endpoint_orbits':chosen.orbit.astype(int).tolist(),
'total_processed_if_all_new_succeed':18,'balanced_endpoint_count_if_all_succeed':12,'balanced_year_month_count':5,
'retention':'All eleven existing fits remain. Three July/September passes are descriptive-only for the matched-season analysis. Three other June/August middle-time passes remain for shape/context, outside the endpoint-window contrast.',
'primary_analysis_limit':'Window balance does not establish an exact 10:30-to-16:00 contrast. Current original total-time interpretation remains; exact-target model/support and secondary geometry/season standardization still pending.',
'execution':'Same paired native-cell block-intercept Stage1, 1000 paired block bootstrap draws, 1/2/4/8km groups; report precision, no new empirical time regression.',
'coefficient_handling':'New point estimates remain sealed in this rebalancing run; current public gradients stay as previously disclosed. No old sealed time contrasts opened.',
'context_limit':'Uses the same stable 2019-2025 median canopy and frozen context surfaces as the eleven-pass pilot. Earlier years increase possible context-vintage mismatch; matched annual context remains a sensitivity, not a silently changed estimator.',
'selection_inputs_sha256':{n:hashlib.sha256((out/n).read_bytes()).hexdigest() for n in ['selection_design.json','matched_year_month_candidates.csv','cloud_screen_summary.csv','cloud_screen_points.csv','matched_strata_cloud_support.csv']}}
fp=out/'thermal_batch_selection_freeze.json'
if fp.exists():assert json.loads(fp.read_text())['selected_new_orbits']==freeze['selected_new_orbits']
else:fp.write_text(json.dumps(freeze,indent=2)+'\n')
c=json.loads((ROOT/'docs/v2/v6_2/execution/phoenix_execution_manifest.json').read_text());c.update(run_id='pooled_rebalance_20260921_phoenix',orbits=added.orbit.astype(int).tolist(),thermal_root=str(ROOT/'data/raw/v2/rebalance_v6_2_20260921/thermal'),emissivity_root=str(ROOT/'data/raw/v2/rebalance_v6_2_20260921/emissivity'),seed=20260921,registration_shifts=[[0,0]],analysis_status='exploratory_rebalanced_multiyear_extension_new_gradients_sealed',coefficient_release_authorized=False)
c['pass_metadata']={str(r.orbit):{'acquisition_utc':r.acquisition_utc,'local_solar_time_hours':float(r.solar_hour),'local_date':r.local_date,'year_month':r.year_month,'time_window':r.time_window,'l1b_view_zenith_abs_p95_deg':float(r.l1b_view_zenith_abs_p95_deg),'l1b_geometry_coverage_fraction':float(r.l1b_geometry_coverage_fraction)} for r in added.itertuples(index=False)}
c['sampling_selection_freeze']='docs/v2/v6_2/execution/rebalance_20260921/thermal_batch_selection_freeze.json'
mp=out/'phoenix_execution_manifest.json'
if not mp.exists():mp.write_text(json.dumps(c,indent=2)+'\n')
print(json.dumps({'new_orbits':c['orbits'],'strata':groups.to_dict('records')}))
