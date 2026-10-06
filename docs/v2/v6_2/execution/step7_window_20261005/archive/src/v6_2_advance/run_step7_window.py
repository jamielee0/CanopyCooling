"""Freeze and compute Step7 fixed-date effects internally; publish precision only."""
import argparse
from datetime import datetime,timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
from urban_cooling_v2.pooled_city_pass import CONTEXT,emitted_energy
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
from .spatial_review import block_stats,validate_native_rows
from .quadratic_sensitivity import sealed_path,write_sealed_json
from .window_uncertainty import joint_passes,window_quantities,summarize,precision_only

ROOT=Path(__file__).resolve().parents[2];RUN='step7_window_20261005'
EXEC=ROOT/'docs/v2/v6_2/execution'/RUN
PACKET=ROOT/'deliverables/Step7_Window_2023_v6_2_20261005'
PREVIOUS='docs/v2/v6_2/execution/quadratic_step5_20261005/execution_freeze.json'
SCHEDULE='deliverables/Step6_Conditions_2023_v6_2_20261005/comparison_schedule.csv'
LOO='deliverables/Step6_Conditions_2023_v6_2_20261005/leave_one_date_schedule.json'
REF='outputs/v6_2/scientific/scale_diagnostics_20260919/frozen_numeric_references.json'
RELEASED='outputs/v6_2/scientific/exploratory_review_20260921/pass_gradients_exploratory.csv'
CODE=['src/v6_2_advance/'+p for p in ['window_uncertainty.py','run_step7_window.py','calibrate_step7_window.py','plot_step7_window.py',
 'time_resampling.py','spatial_review.py','quadratic_sensitivity.py']]+['tests/v6_2_advance/test_window_uncertainty.py',
 'src/urban_cooling_v2/pooled_city_pass.py','src/urban_cooling_v2/pilot_scale.py','src/urban_cooling_v2/v6_2_output_boundary.py']
ACTIVE=['AGENTS.md']+['docs/v2/v6_2/'+p for p in ['protocol_v6_2.yml','pilot_plan_v6_2.md','decision_log_v6_2.md','prior_thermal_access.md','results_review_and_targeted_analysis_plan_20260930.md']]
QUANTITIES=[('temperature','K_per_10pp'),('emitted_flux','W_m2_per_10pp'),('temperature_equivalent','K_per_10pp'),('temperature_minus_equivalent','K_per_10pp')]

def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def public(name):
 p=guarded_output_path(ROOT,'scientific',f'{RUN}/{name}');p.parent.mkdir(parents=True,exist_ok=True);return p
def synthetic(name):
 p=guarded_output_path(ROOT,'synthetic',f'{RUN}/{name}');p.parent.mkdir(parents=True,exist_ok=True);return p
def write(p,d):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')

def freeze():
 target=EXEC/'execution_freeze.json'
 if target.exists():raise ValueError('Preserve existing Step7 freeze')
 prior=json.loads((ROOT/PREVIOUS).read_text());schedule=pd.read_csv(ROOT/SCHEDULE);loo=json.loads((ROOT/LOO).read_text())
 if str((ROOT/'data').resolve(strict=True))!=prior['data_link_target']:raise ValueError('Data-link target changed')
 passes=prior['passes'];inputs=[]
 for spec in passes:
  if sha(ROOT/spec['path'])!=spec['sha256']:raise ValueError('Cached frame changed')
  inputs.append(dict(path=spec['path'],sha256=spec['sha256'],role='internal_paired_native_frame'))
 for rel in [PREVIOUS,SCHEDULE,LOO,REF,RELEASED,'deliverables/Step6_Conditions_2023_v6_2_20261005/conditions_with_rainfall.csv']:
  inputs.append(dict(path=rel,sha256=sha(ROOT/rel),role='existing_public_record'))
 designs={}
 for city in ('phoenix','atlanta'):
  q=schedule[schedule.city.eq(city)].sort_values('local_date')
  w=q.window_weight.to_numpy()
  if city=='atlanta':
   # A separate synthetic-only design check; no empirical Atlanta contrast is produced.
   w=np.where(q.orbit.eq(27916),1.,np.where(q.orbit.eq(27896),-1.,0.))
  designs[city]=dict(orbits=q.orbit.astype(int).tolist(),dates=q.local_date.tolist(),times=q.apparent_solar_hour.tolist(),
   months=pd.to_datetime(q.local_date).dt.month.tolist(),day_numbers=pd.to_datetime(q.local_date).dt.dayofyear.tolist(),
   weights=w.tolist(),early=float(np.dot(np.maximum(-w,0),q.apparent_solar_hour)),late=float(np.dot(np.maximum(w,0),q.apparent_solar_hour)),
   empirical_use=city=='phoenix',target_description='expected weighted scheduled-date contrast; not a causal clock effect or exact10:30-versus16:00 target')
 snapshot=ROOT/'docs/v2/v6_2/archive/before_step7_window_20261005';saved=[]
 for rel in ACTIVE:
  p=snapshot/rel;p.parent.mkdir(parents=True,exist_ok=True)
  if p.exists():raise ValueError('Snapshot exists')
  shutil.copy2(ROOT/rel,p);saved.append(dict(path=rel,sha256=sha(p)))
 write(snapshot/'snapshot.json',dict(files=saved))
 record=dict(created_utc=datetime.now(timezone.utc).isoformat(),record_date_local='2026-10-05',
  authority=dict(request='do the next steps',scope='Step7 fixed-date internal Phoenix contrasts, actual-design synthetic uncertainty assessment, methods/captions and bounded next-observation proposal',
   supersedes='earlier hold on this bounded empirical window computation and assumption-based synthetic calibration only',
   new_effect_display=False,scale_tolerance=None,thermal_expansion=False),passes=passes,inputs=inputs,
  data_link_target=prior['data_link_target'],code_sha256={p:sha(ROOT/p) for p in CODE},
  reference=json.loads((ROOT/REF).read_text()),designs=designs,leave_one_date_schedule=loo,
  empirical=dict(mean_model='frozen original linear canopy plus all six controls and1km block intercepts; no quadratic promotion',
   groups_km=[1,8],replicates=1000,seeds={'phoenix':20262005,'atlanta':20263005},
   resampling='city-specific union of physical groups; same multiplicities across dates and paired outcomes; absent groups contribute zero',
   missing_draws='retain per-pass failure; each contrast uses only required dates, complete-city rows for covariance, no replacement',
   comparisons=['combined','June','August','drop_Aug06','drop_Aug23','influence_Aug06','influence_Aug23'],
   unsupported_deletions=[27963,28192,28909],
   flux_order='average canopy flux changes within each fixed arm, reanchor and invert, then subtract morning equivalent from afternoon equivalent',
   public_fields='support, covariance/precision, failures, hashes; no new effect points, interval endpoints, signs or significance',
   raw_thermal_raster_reads=False,old_empirical_time_files_opened=False,general_summer_interval=False),
  simulation=dict(label='SYNTHETIC_DATA; hypothetical assumptions, not observed effects or Reza tolerance',
   cities=['phoenix','atlanta'],amplitudes_K_per_10pp=[-.3,0,.3],day_SDs_K_per_10pp=[0,.05,.15],spatial_correlation_fractions=[0,1],
   profiles=['linear','season_offsets','curved_time','month_slope','heterogeneous_day','serial_days'],
   mean_details='linear term amplitude*(time-mean(time))/(w*time); add0.15*(month-minmonth),0.025*(time-13)^2,or0.04*(month-minmonth)*(time-13) in named scenarios',
   day_details='independent Gaussian days by default; afternoon SD doubled in heterogeneous case; exp(-date_gap/14) dependence in serial stress',
   measurement='Gaussian error with actual8km joint spatial covariance or its diagonal; fixed plug-in covariance, no estimation-error uncertainty for S',
   development_datasets=100,production_datasets=2000,development_seed=70261005,production_seed=80261005,
   bootstrap_replicates=499,development_bank_seed=90261005,production_bank_seed=100261005,
   bank_rule='independent date-cluster resampling; same frozen bank across independent simulated datasets within city/phase; MC error conditional on bank',
   candidate='unweighted fixed-window point, tau2=max(0,(yP y-tr(P S))/(n-p)); P residualizes month intercepts and linear time; t(n-p) interval with w(S+tau2 I)w',
   benchmark='existing day-cluster linear-time benchmark evaluated at fixed arm-mean times; equals weighted-window target only under its mean assumptions',
   other_methods=['stratified_window_day_bootstrap','fixed_date_spatial_only','oracle_known_variance','double_spatial_noise_negative_control'],
   selection='no tuning to empirical sign or retrospective method promotion; synthetic-only Atlanta June7/June8 check is not an adopted empirical contrast',
   generalization='hypothetical scheduled-date population means only; no general-season empirical interval or causal interpretation'),
  sources=['https://pmc.ncbi.nlm.nih.gov/articles/PMC5157768/','https://metafor-project.org/doku.php/faq'],
  method_note='The implemented moment-based unweighted candidate is not REML or Hartung-Knapp; sources motivate explicit variance separation and small-sample assessment only')
 write(target,record);write(EXEC/'scope.json',record['authority'])
 for rel in CODE:
  p=EXEC/'archive'/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,p)
 print(json.dumps(dict(stage='frozen',passes=16,spatial_draws_per_city_and_size=1000,simulation_scenarios=216,new_effects='SEALED')))

def check(cfg):
 if str((ROOT/'data').resolve(strict=True))!=cfg['data_link_target']:raise ValueError('Data-link target changed')
 for r in cfg['inputs']:
  if sha(ROOT/r['path'])!=r['sha256']:raise ValueError('Input checksum changed')
 for rel,h in cfg['code_sha256'].items():
  if sha(ROOT/rel)!=h:raise ValueError('Frozen analysis code changed')

def comparisons(design,loo):
 orbits=design['orbits'];w=np.asarray(design['weights']);result={'combined':w}
 months=np.asarray(design['months'])
 for month,label in [(6,'June'),(8,'August')]:result[label]=np.where(months==month,w*2,0)
 for row in loo:
  if row['status']!='SUPPORTED_SCHEDULE_ONLY':continue
  name='drop_Aug06' if row['dropped_orbit']==28828 else 'drop_Aug23'
  result[name]=np.asarray([row['remaining_weights'].get(str(o),0) for o in orbits],float)
 return result

def run():
 os.umask(0o077);cfg=json.loads((EXEC/'execution_freeze.json').read_text());check(cfg)
 old=pd.read_csv(ROOT/RELEASED,usecols=['city','orbit','gradient_K_per_10pp']).set_index(['city','orbit'])
 all_audits=[];public_rows=[];access=[];sealed_records=[]
 for city in ('phoenix','atlanta'):
  stats=[];design=cfg['designs'][city]
  specs=sorted([p for p in cfg['passes'] if p['city']==city],key=lambda p:p['date'])
  for spec in specs:
   cols=['cell_id','block','x','y','native_crs','native_x','native_y','canopy_fraction',*CONTEXT,'LST_K','M_W_m2','emissivity']
   access.append(dict(path=spec['path'],columns=cols,purpose='internal original-model recovery and joint spatial uncertainty'))
   write(EXEC/'access_log.json',access)
   frame=pd.read_parquet(ROOT/spec['path'],columns=cols);validate_native_rows(frame)
   if len(frame)!=spec['n_cells'] or not np.allclose(frame.M_W_m2,emitted_energy(frame.LST_K,frame.emissivity),atol=1e-9,rtol=0):raise ValueError('Sample/energy identity failed')
   stat=block_stats(frame,['canopy_fraction',*CONTEXT]);coef=stat.solve()
   if not np.isclose(.1*coef[0,0],old.loc[(city,spec['orbit']),'gradient_K_per_10pp'],atol=1e-8,rtol=0):raise ValueError('Original temperature estimate not recovered')
   stats.append(stat);del frame;gc.collect()
  for size in cfg['empirical']['groups_km']:
   point,draws,audit=joint_passes(stats,group_km=size,replicates=1000,seed=cfg['empirical']['seeds'][city]+size)
   audit.update(city=city,orbits=design['orbits']);all_audits.append(audit)
   p=sealed_path(ROOT,RUN,f'{city}_{size}km_joint_SEALED.npz')
   with p.open('xb') as f:np.savez_compressed(f,points=point,draws=draws,orbits=design['orbits'])
   p.chmod(0o600)
   valid=np.isfinite(draws).all(axis=(1,2))
   if valid.sum()<2:raise ValueError('Too few complete-city draws for covariance; no rescue')
   covariance=np.cov(draws[valid,:,0],rowvar=False,ddof=1)
   cov_record=dict(city=city,group_km=size,orbits=design['orbits'],covariance_K2_per_10pp2=covariance.tolist(),complete_city_draws=int(valid.sum()),
                   role='spatial estimation precision only; plug-in synthetic input, not between-day variance')
   write(public(f'{city}_{size}km_spatial_covariance.json'),cov_record)
   if city=='phoenix':
    weights=comparisons(design,cfg['leave_one_date_schedule']);points={};boots={}
    for name,w in weights.items():
     points[name]=window_quantities(point,w,cfg['reference']['reference_K'],cfg['reference']['reference_emissivity'])
     boots[name]=window_quantities(draws,w,cfg['reference']['reference_K'],cfg['reference']['reference_emissivity'])
    for label in ('Aug06','Aug23'):
     points['influence_'+label]=points['drop_'+label]-points['combined']
     boots['influence_'+label]=boots['drop_'+label]-boots['combined']
    for name,values in boots.items():
     dates=int(np.count_nonzero(weights[name])) if name in weights else 5
     for k,(quantity,units) in enumerate(QUANTITIES):
      s=summarize(points[name][k],values[:,k]);sealed_records.append(dict(comparison=name,group_km=size,quantity=quantity,units=units,**s))
      public_rows.append(precision_only(dict(comparison=name,group_km=size,quantity=quantity,units=units,independent_dates=dates,
       requested=1000,estimable=s['estimable'],failed=s['failed'],SE=s['SE'],width95=s['width95'],effect_status='SEALED_USER_REQUEST',uncertainty_scope='fixed_dates_spatial_only')))
    p=sealed_path(ROOT,RUN,f'phoenix_{size}km_window_draws_SEALED.npz')
    with p.open('xb') as f:np.savez_compressed(f,**boots)
    p.chmod(0o600)
   print(json.dumps(dict(city=city,group_km=size,passes=len(stats),complete_city_draws=audit['complete_city_draws'],new_effects='SEALED')),flush=True)
  del stats,draws;gc.collect()
 write_sealed_json(ROOT,RUN,'phoenix_window_comparisons_SEALED.json',sealed_records)
 pd.DataFrame(public_rows).to_csv(public('fixed_date_precision.csv'),index=False)
 write(public('resampling_audit.json'),all_audits)
 write(public('unsupported_deletions.json'),[r for r in cfg['leave_one_date_schedule'] if r['status']!='SUPPORTED_SCHEDULE_ONLY'])
 completion=dict(status='FIXED_DATE_INTERNAL_COMPUTATION_COMPLETE',original_points_recovered=16,city_group_configurations=4,
  pass_draws_requested=32000,pass_draws_estimable=sum(sum(a['per_pass_estimable']) for a in all_audits),precision_rows=len(public_rows),
  empirical_Atlanta_contrast=False,new_effect_display=False,general_summer_interval=False,scale_ruling=None)
 write(public('empirical_completion.json'),completion);print(json.dumps(completion))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');args=p.parse_args()
 freeze() if args.freeze else run()
