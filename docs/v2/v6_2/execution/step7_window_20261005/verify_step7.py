"""Read new sealed outputs programmatically; return only checks and counts."""
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[5];sys.path.insert(0,str(ROOT/'src'))
from v6_2_advance.run_step7_window import EXEC,PACKET,RUN,public,synthetic,sha,write,check,comparisons,QUANTITIES
from v6_2_advance.quadratic_sensitivity import sealed_path
from v6_2_advance.window_uncertainty import window_quantities,summarize,precision_only
from urban_cooling_v2.v6_2_output_boundary import validate

def main():
 cfg=json.loads((EXEC/'execution_freeze.json').read_text());check(cfg)
 records=json.loads(sealed_path(ROOT,RUN,'phoenix_window_comparisons_SEALED.json').read_text())
 if len(records)!=56:raise ValueError('Incomplete sealed comparisons')
 for size in (1,8):
  with np.load(sealed_path(ROOT,RUN,f'phoenix_{size}km_joint_SEALED.npz'),allow_pickle=False) as z:
   points=z['points'];draws=z['draws'];orbits=z['orbits']
   if orbits.tolist()!=cfg['designs']['phoenix']['orbits']:raise ValueError('Date identity mismatch')
  weights=comparisons(cfg['designs']['phoenix'],cfg['leave_one_date_schedule'])
  expected={}
  for name,w in weights.items():
   p=window_quantities(points,w,cfg['reference']['reference_K'],cfg['reference']['reference_emissivity'])
   b=window_quantities(draws,w,cfg['reference']['reference_K'],cfg['reference']['reference_emissivity'])
   # Independent temperature/flux matrix multiplication verifies signed temporal weights.
   if not np.allclose(p[:2],w@points,atol=1e-10,rtol=0):raise ValueError('Window sign/weight mismatch')
   expected[name]=(p,b)
  for label in ('Aug06','Aug23'):
   expected['influence_'+label]=tuple(a-b for a,b in zip(expected['drop_'+label],expected['combined']))
  for row in records:
   if row['group_km']!=size:continue
   k=[q[0] for q in QUANTITIES].index(row['quantity']);p,b=expected[row['comparison']];s=summarize(p[k],b[:,k])
   for field in ('point','q025','q975','SE','width95'):
    if not np.isclose(row[field],s[field],atol=1e-10,rtol=1e-10):raise ValueError('Comparison summary mismatch')
  for city in ('phoenix','atlanta'):
   cov=json.loads(public(f'{city}_{size}km_spatial_covariance.json').read_text())
   with np.load(sealed_path(ROOT,RUN,f'{city}_{size}km_joint_SEALED.npz'),allow_pickle=False) as z:
    b=z['draws'];valid=np.isfinite(b).all(axis=(1,2));computed=np.cov(b[valid,:,0],rowvar=False,ddof=1)
   if not np.allclose(cov['covariance_K2_per_10pp2'],computed,atol=1e-14,rtol=1e-12):raise ValueError('Covariance failed reconstruction')
 table=pd.read_csv(public('fixed_date_precision.csv'))
 for row in table.to_dict('records'):precision_only(row)
 if len(json.loads(public('unsupported_deletions.json').read_text()))!=3:raise ValueError('Unsupported deletions lost')
 for p in sealed_path(ROOT,RUN,'phoenix_window_comparisons_SEALED.json').parent.iterdir():
  if p.is_file() and p.stat().st_mode&0o777!=0o600:raise ValueError('Private file mode mismatch')
 if sealed_path(ROOT,RUN,'phoenix_window_comparisons_SEALED.json').parent.stat().st_mode&0o777!=0o700:raise ValueError('Private directory mode mismatch')
 d=pd.read_csv(synthetic('SYNTHETIC_DATA_production_calibration.csv'))
 if len(d)!=1296 or d.scenario_id.nunique()!=216 or not d.datasets_requested.eq(2000).all() or not d.failed.eq(0).all():raise ValueError('Incomplete simulation accounting')
 if not d.label.eq('SYNTHETIC_DATA').all():raise ValueError('Synthetic labelling failed')
 oracle=d[d.method.eq('oracle_known_variance')].population_target_coverage.mean()
 fixed=d[d.method.eq('fixed_date_spatial_only')].fixed_dates_target_coverage.mean()
 # Known Gaussian oracles, numerical implementation check, not a scientific acceptance gate.
 if abs(oracle-.95)>.005 or abs(fixed-.95)>.005:raise ValueError('Known-variance simulation coverage check failed')
 dev=json.loads(synthetic('SYNTHETIC_DATA_development_completion.json').read_text())
 prod=json.loads(synthetic('SYNTHETIC_DATA_production_completion.json').read_text())
 if dev['simulated_datasets']!=21600 or prod['simulated_datasets']!=432000:raise ValueError('Phase accounting mismatch')
 production=json.loads((EXEC/'production_calibration_freeze.json').read_text())
 if not production['methods_unchanged_after_development']:raise ValueError('Unrecorded method tuning')
 for rel,h in production['code_sha256'].items():
  if sha(ROOT/rel)!=h:raise ValueError('Production code changed')
 if validate(ROOT):raise ValueError('Output boundary failed')
 p=sealed_path(ROOT,RUN,'phoenix_window_comparisons_SEALED.csv')
 if p.exists():raise ValueError('Preserve comparison CSV')
 pd.DataFrame(records).to_csv(p,index=False);p.chmod(0o600)
 result=dict(status='PASS',known_answer_tests=13,frozen_inputs_verified=len(cfg['inputs']),frozen_code_files_verified=len(cfg['code_sha256']),
  original_points_recovered=16,joint_pass_draws=32000,estimable_pass_draws=32000,precision_rows=56,
  supported_window_and_influence_configurations=14,unsupported_date_deletions=3,
  development_datasets=21600,production_datasets=432000,production_scenarios=216,methods=6,
  oracle_mean_population_coverage=float(oracle),spatial_only_mean_realized_date_coverage=float(fixed),
  empirical_Atlanta_contrast=False,new_effect_display=False,general_summer_interval=False,scale_ruling=None,
  verification_code_sha256=sha(Path(__file__)))
 write(EXEC/'verification.json',result);print(json.dumps(result))

if __name__=='__main__':main()
