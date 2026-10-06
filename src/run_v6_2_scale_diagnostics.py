#!/usr/bin/env python3
"""Freeze reference numbers, compute sealed paired contrasts, run labeled mixing tests.

No empirical point estimate is written to stdout or to the public/synthetic roots.
Supply exactly the two completed pilot execution manifests.
"""
import argparse,json,hashlib,sys
from pathlib import Path
from datetime import datetime,timezone
import numpy as np,pandas as pd
from urban_cooling_v2.pooled_city_pass import PooledFit
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
from urban_cooling_v2.pilot_scale import freeze_references,contrast_from_pass_predictions,time_contrast,simulate_pass,secondary_overlap
from urban_cooling_v2.independent_foundation_audit import local_solar_hour
from urban_cooling_v2.demand_geometry_audit import solar_position_from_local_solar_time

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,default=lambda v:v.tolist() if hasattr(v,'tolist') else str(v))+'\n')
def run(paths):
 configs=[json.loads(p.read_text()) for p in paths]
 if len(configs)!=2 or len({c['city'] for c in configs})!=2:raise ValueError('Exactly two pilot cities required')
 root=Path(configs[0]['repository'])
 P=lambda name:guarded_output_path(root,'scientific','scale_diagnostics_20260919/'+name)
 S=lambda name:guarded_output_path(root,'sealed','scale_diagnostics_20260919/'+name)
 Y=lambda name:guarded_output_path(root,'synthetic','mixing_20260919/'+name)
 pub=P('scale_simulation_design.json').parent;sealed=S('manifest_SEALED.json').parent;syn=Y('SYNTHETIC_DATA_manifest.json').parent
 for p in [pub,sealed,syn]:p.mkdir(parents=True,exist_ok=True)
 sealed.chmod(0o700)
 plan={'created_utc':datetime.now(timezone.utc).isoformat(),'early_solar_hour':10.5,'late_solar_hour':16.,'time_basis':'linear_city_specific_total_unweighted; equal_city_mean_when_all_supported','secondary_basis':'linear_time_plus_solar_elevation_plus_day_of_year_only_with_convex_hull_overlap','reference_rule':'maximize_minimum_number_of_supporting_blocks_across_passes_then_lowest_f0; equal_city_equal_pass_medians_T_and_epsilon','contrast_grid_K':[0,2,5,10],'simulation_blocks_per_pass':200,'simulation_block_selection':'seeded_uniform_whole_block_sample_same_blocks_all_scenarios','simulation_bootstrap_replicates':100,'empirical_time_bootstrap_replicates':1000,'stage1_uncertainty_sensitivity':'paired_8km_spatial_bootstrap_in_addition_to_1km_primary','seed':20260919,'tolerance':None,'unsealing_authorized':False,'input_execution_manifest_hashes':[sha(p) for p in paths],'absolute_thermal_access':'allowed_for_aggregate_reference_and_simulation_anchors_only_effects_stay_sealed','simulation_assumptions':'block_median_T_and_emissivity_primary; 0.5K_block_and_0.5K_cell_noise; tree_epsilon_plus_0.01_capped_0.999; halve_canopy_range; background_plus_minus_10K; within_block_permutation_T_sensitivity'}
 plan['code_hashes']={str(q.relative_to(root)):sha(q) for q in [Path(__file__),root/'src/urban_cooling_v2/pilot_scale.py',root/'src/urban_cooling_v2/pooled_city_pass.py']}
 design=P('scale_simulation_design.json')
 if design.exists():raise ValueError('Design already frozen; use saved results or explicitly record a rerun')
 write(design,plan)
 # Reference selection reads native observations, never stored empirical coefficients.
 frames=[];identities=[];metas=[]
 for c in configs:
  for orbit in c['orbits']:
   p=root/'outputs/v6_2/sealed_coefficients'/c['run_id']/f'{orbit}_paired_native_cells_SEALED.parquet'
   frames.append(pd.read_parquet(p));identities.append((c,orbit));metas.append(c['pass_metadata'][str(orbit)])
 settings,refs=freeze_references(frames,[c['city'] for c,_ in identities]);write(P('frozen_numeric_references.json'),settings)
 # Store reference row identities in a non-effect artifact and seal prediction values.
 for ref,(c,orbit) in zip(refs,identities):ref[['cell_id','block']].to_parquet(P(f'{c["city"]}_{orbit}_reference_rows.parquet'),index=False)
 pass_results=[];bootstrap=[];bootstrap8=[];time_support=[]
 for d,ref,(c,orbit),meta in zip(frames,refs,identities,metas):
  p=root/'outputs/v6_2/sealed_coefficients'/c['run_id']/f'{orbit}_paired_primary_SEALED.npz'
  with np.load(p,allow_pickle=True) as z:
   fit=PooledFit(z['coefficients'],z['bootstrap_coefficients'],{},list(z['predictor_names']),z['block_labels'],z['block_x_means'],z['block_y_means'],list(z['outcome_names']))
  contrast=contrast_from_pass_predictions(fit,ref,settings)
  bootstrap.append(np.column_stack([contrast.pop('bootstrap_CE_T'),contrast.pop('bootstrap_CE_M_equivalent')]))
  stress=root/'outputs/v6_2/sealed_coefficients'/c['run_id']/f'{orbit}_spatial_8km_SEALED.npz'
  if not stress.exists(): raise ValueError('Complete spatial stress checks before time diagnostics')
  with np.load(stress) as z: fit.bootstrap_coefficients=z['bootstrap_coefficients']
  robust=contrast_from_pass_predictions(fit,ref,settings)
  bootstrap8.append(np.column_stack([robust['bootstrap_CE_T'],robust['bootstrap_CE_M_equivalent']]))
  stamp=pd.Timestamp(meta['acquisition_utc']).to_pydatetime();lon=c.get('centroid_longitude',-111.961187 if c['city']=='phoenix' else -84.3365018);lat=c.get('centroid_latitude',33.501481 if c['city']=='phoenix' else 33.8362691);hour=local_solar_hour(stamp,lon)
  # NOAA apparent solar time; do not silently relabel mean solar hours.
  doy=stamp.timetuple().tm_yday
  gamma=2*np.pi/365*(doy-1);decl=.006918-.399912*np.cos(gamma)+.070257*np.sin(gamma)-.006758*np.cos(2*gamma)+.000907*np.sin(2*gamma)-.002697*np.cos(3*gamma)+.00148*np.sin(3*gamma)
  altitude=np.degrees(np.arcsin(np.sin(np.radians(lat))*np.sin(decl)+np.cos(np.radians(lat))*np.cos(decl)*np.cos(np.radians((hour-12)*15))))
  pass_results.append({'city':c['city'],'orbit':orbit,'solar_hour':hour,'solar_elevation':altitude,'day_of_year':doy,'date':stamp.date().isoformat(),**contrast})
 from urban_cooling_v2.pooled_city_pass import temperature_equivalent
 reference_sensitivity=[]
 for r in pass_results:
  for dt in [-10,0,10]:
   for de in [-.01,0,.01]:
    temp=settings['reference_K']+dt;eps=min(.999,settings['reference_emissivity']+de)
    reference_sensitivity.append({'city':r['city'],'orbit':r['orbit'],'reference_K':temp,'reference_emissivity':eps,'CE_M_equivalent':-float(temperature_equivalent(-r['CE_M_W_m2'],temp,eps))})
 pd.DataFrame(reference_sensitivity).to_csv(S('reference_sensitivity_SEALED.csv'),index=False)
 pd.DataFrame(pass_results).to_csv(S('pass_contrasts_SEALED.csv'),index=False)
 empirical=pd.DataFrame(pass_results);time_results={}
 for city_index,city in enumerate(empirical.city.unique()):
  ids=np.flatnonzero(empirical.city.eq(city));q=empirical.iloc[ids];nb=min(len(bootstrap[i]) for i in ids);bs=np.stack([bootstrap[i][:nb] for i in ids]);responses=q[['CE_T','CE_M_equivalent']].to_numpy()
  for variant in ['total','total_spatial8km','geometry_season']:
   if variant=='total_spatial8km':
    nb=min(len(bootstrap8[i]) for i in ids);bs=np.stack([bootstrap8[i][:nb] for i in ids])
   else:
    nb=min(len(bootstrap[i]) for i in ids);bs=np.stack([bootstrap[i][:nb] for i in ids])
   kwargs={} if variant.startswith('total') else {'geometry':q.solar_elevation,'day_of_year':q.day_of_year}
   try:
    result=time_contrast(q.solar_hour,responses,early=10.5,late=16,day_clusters=q.date,bootstrap_CE=bs,replicates=1000,seed=20260919+city_index,**kwargs)
    time_results[city+'_'+variant]=result;time_support.append({'city':city,'variant':variant,'status':'COMPUTED_SEALED','independent_days':result['independent_days'],'estimable_resamples':result['estimable_resamples']})
   except ValueError as e:time_support.append({'city':city,'variant':variant,'status':'NOT_ESTIMABLE','reason':str(e)})
 keys=[c['city']+'_total' for c in configs]
 if all(k in time_results for k in keys):
  n=min(len(time_results[k]['draws']) for k in keys)
  time_results['equal_city_total']={'point':np.mean([time_results[k]['point'] for k in keys],axis=0),'draws':np.mean([time_results[k]['draws'][:n] for k in keys],axis=0),'interpretation':'equal_average_of_two_pilot_cities_not_population_of_cities','leave_one_city_out':'the_two_city_specific_results'}
 write(S('time_contrasts_SEALED.json'),time_results);write(P('time_support_status.json'),time_support)
 write(P('scale_ruling_status.json'),{'status':'PENDING_REZA_TOLERANCE_AND_COEFFICIENT_RELEASE','empirical_effects_displayed':False,'tolerance':None})
 synthetic=[]
 for d,(c,orbit),emp in zip(frames,identities,pass_results):
  rng=np.random.default_rng(20260919);labels=np.sort(d.block.unique());chosen=rng.choice(labels,min(200,len(labels)),replace=False);sample=d[d.block.isin(chosen)].copy().reset_index(drop=True)
  rows=simulate_pass(sample,reference_K=settings['reference_K'],reference_emissivity=settings['reference_emissivity'],replicates=100)
  for r in rows:r.update(city=c['city'],orbit=orbit,solar_hour=emp['solar_hour'],sampled_blocks=len(chosen),sampled_cells=len(sample))
  synthetic.extend(rows);pd.DataFrame(synthetic).to_csv(Y('SYNTHETIC_DATA_mixing_pass_results.csv'),index=False)
  print(json.dumps({'completed':'SYNTHETIC_DATA','city':c['city'],'orbit':orbit,'scenarios':len(rows)}),flush=True)
 s=pd.DataFrame(synthetic);summary=[]
 for (scenario,delta),q in s.groupby(['scenario','constant_component_contrast_K']):
  citymeans=q.groupby('city')[['CE_T_minus_zero_control','CE_Mequiv_minus_zero_control']].mean()
  summary.append({'label':'SYNTHETIC_DATA','scenario':scenario,'constant_contrast_K':delta,'T_cross_pass_range_K_per_10pp':float(q.CE_T_minus_zero_control.max()-q.CE_T_minus_zero_control.min()),'T_city_mean_difference_atlanta_minus_phoenix':float(citymeans.loc['atlanta','CE_T_minus_zero_control']-citymeans.loc['phoenix','CE_T_minus_zero_control']),'M_equiv_city_mean_difference_atlanta_minus_phoenix':float(citymeans.loc['atlanta','CE_Mequiv_minus_zero_control']-citymeans.loc['phoenix','CE_Mequiv_minus_zero_control']),'max_abs_transformation_departure_K_per_10pp':float(q.transformation_departure_K_per_10pp.abs().max())})
 pd.DataFrame(summary).to_csv(Y('SYNTHETIC_DATA_mixing_summary.csv'),index=False)
 st=[]
 for (city,scenario,delta),q in s.groupby(['city','scenario','constant_component_contrast_K']):
  try:
   r=time_contrast(q.solar_hour,q[['CE_T_minus_zero_control','CE_Mequiv_minus_zero_control']],replicates=100)
   st.append({'label':'SYNTHETIC_DATA','city':city,'scenario':scenario,'constant_contrast_K':delta,'artificial_time_contrast_T':float(r['point'][0]),'time_contrast_M_equivalent':float(r['point'][1]),'signs_differ':bool(np.sign(r['point'][0])!=np.sign(r['point'][1])),'time_contrast_T_q025':float(np.quantile(r['draws'][:,0],.025)),'time_contrast_T_q975':float(np.quantile(r['draws'][:,0],.975))})
  except ValueError:pass
 pd.DataFrame(st).to_csv(Y('SYNTHETIC_DATA_time_comparison.csv'),index=False)
 import matplotlib;matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 fig,axes=plt.subplots(1,2,figsize=(10,4),sharey=True)
 for ax,city in zip(axes,['phoenix','atlanta']):
  for delta in [2,5,10]:
   q=s[(s.city==city)&(s.scenario=='transformation_only')&(s.constant_component_contrast_K==delta)].sort_values('solar_hour')
   ax.plot(q.solar_hour,q.transformation_departure_K_per_10pp,marker='o',label=f'Component contrast {delta} K')
  ax.axhline(0,color='black',linewidth=.7);ax.set_title(city.title());ax.set_xlabel('Apparent local solar hour');ax.grid(alpha=.2)
 axes[0].set_ylabel('Departure from constant linear-temperature benchmark\n(K per 10 percentage points canopy)');axes[1].legend(fontsize=8)
 fig.suptitle('SYNTHETIC DATA — constant tree–background temperature contrast');fig.tight_layout();fig.savefig(Y('SYNTHETIC_DATA_transformation_artifact.png'),dpi=180);plt.close(fig)
 for p in sealed.iterdir():p.chmod(0o600)
 return {'status':'precision_review_only','simulation_rows':len(synthetic)}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('manifests',nargs=2,type=Path);args=p.parse_args();run(args.manifests)
