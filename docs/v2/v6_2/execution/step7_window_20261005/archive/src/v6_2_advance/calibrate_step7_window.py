"""SYNTHETIC DATA calibration; actual schedule/precision, no empirical effect means."""
import argparse
import itertools
import json
from pathlib import Path
import shutil
import time

import numpy as np
import pandas as pd
from .run_step7_window import ROOT,RUN,EXEC,PACKET,public,synthetic,sha,write,check
from .window_uncertainty import day_slope_bank,stratified_window_bank,simulate_scenario,nuisance_design


def run(phase):
 cfg=json.loads((EXEC/'execution_freeze.json').read_text());check(cfg);sim=cfg['simulation']
 if phase=='production':
  development=json.loads(synthetic('SYNTHETIC_DATA_development_completion.json').read_text())
  if development['scenarios']!=216:raise ValueError('Complete development before production')
  decision=EXEC/'production_calibration_freeze.json'
  record=dict(methods_unchanged_after_development=True,execution_freeze_sha256=sha(EXEC/'execution_freeze.json'),
    code_sha256={p:sha(ROOT/p) for p in cfg['code_sha256']},production_seed=sim['production_seed'],
    production_bank_seed=sim['production_bank_seed'],datasets_each=2000,empirical_effect_means_read=False)
  if decision.exists() and json.loads(decision.read_text())!=record:raise ValueError('Production settings changed')
  if not decision.exists():write(decision,record)
 datasets=sim[phase+'_datasets'];rows=[];truths=[];bank_audits=[];start=time.monotonic();index=0
 for c,city in enumerate(sim['cities']):
  design=cfg['designs'][city]
  meta=json.loads(public(f'{city}_8km_spatial_covariance.json').read_text())
  if meta['orbits']!=design['orbits']:raise ValueError('Precision identity mismatch')
  s=np.asarray(meta['covariance_K2_per_10pp2'])
  if (np.diag(s)<=0).any():raise ValueError('Nonpositive calibration precision')
  point,bank,audit=day_slope_bank(design['times'],early=design['early'],late=design['late'],replicates=sim['bootstrap_replicates'],seed=sim[phase+'_bank_seed']+c)
  strat=stratified_window_bank(design['weights'],design['months'],replicates=sim['bootstrap_replicates'],seed=sim[phase+'_bank_seed']+100+c)
  audit.update(city=city,phase=phase,independent_dates=len(design['orbits']),
               moment_residual_df=nuisance_design(design['times'],design['months'])[2],
               resampled_month_arms='stratified window retains singleton arms; unrestricted day-slope bank can omit target support')
  bank_audits.append(audit)
  for amplitude,sd,correlation,profile in itertools.product(sim['amplitudes_K_per_10pp'],sim['day_SDs_K_per_10pp'],sim['spatial_correlation_fractions'],sim['profiles']):
   index+=1;identity=dict(scenario_id=index,city=city,amplitude_K_per_10pp=amplitude,day_SD_K_per_10pp=sd,
    spatial_correlation_fraction=correlation,profile=profile,phase=phase,label='SYNTHETIC_DATA')
   results,truth=simulate_scenario(design,s,amplitude=amplitude,day_sd=sd,correlation_fraction=correlation,profile=profile,
    datasets=datasets,seed=sim[phase+'_seed']+index,banks=(point,bank,audit,strat))
   truths.append({**identity,**truth})
   for method,result in results.items():rows.append({**identity,'method':method,**result})
   if index%18==0:print(json.dumps(dict(stage=phase,scenarios=index,total=216,synthetic=True)),flush=True)
 pd.DataFrame(rows).to_csv(synthetic(f'SYNTHETIC_DATA_{phase}_calibration.csv'),index=False)
 pd.DataFrame(truths).to_csv(synthetic(f'SYNTHETIC_DATA_{phase}_truth.csv'),index=False)
 write(synthetic(f'SYNTHETIC_DATA_{phase}_bank_audit.json'),bank_audits)
 completion=dict(status='SYNTHETIC_CALIBRATION_COMPLETE',phase=phase,scenarios=index,datasets_each=datasets,
  simulated_datasets=index*datasets,method_rows=len(rows),elapsed_seconds=round(time.monotonic()-start,2),
  empirical_effect_means_used=False,actual_covariance_source='8km joint spatial precision, treated as known in simulation',
  general_summer_interval_authorized=False,scale_ruling=None)
 write(synthetic(f'SYNTHETIC_DATA_{phase}_completion.json'),completion)
 if phase=='production':
  PACKET.mkdir(parents=True,exist_ok=True)
  for suffix in ('calibration.csv','truth.csv','bank_audit.json','completion.json'):
   p=synthetic(f'SYNTHETIC_DATA_{phase}_{suffix}');shutil.copy2(p,PACKET/p.name)
 print(json.dumps(completion),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('phase',choices=['development','production']);args=p.parse_args();run(args.phase)
