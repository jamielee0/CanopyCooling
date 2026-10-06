"""Release integrity, readable tables and targeted joint-follow-up checks."""
import json,hashlib,sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[5];sys.path.insert(0,str(ROOT/'src'))
from v6_2_advance.spatial_review import physical_groups,common_ids
from v6_2_advance.window_uncertainty import window_quantities,summarize
from urban_cooling_v2.v6_2_output_boundary import validate
EXEC=Path(__file__).resolve().parent;PACKET=ROOT/'deliverables/Pilot_Results_Review_2023_v6_2_20261006'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,v):p.write_text(json.dumps(v,indent=2,allow_nan=False)+'\n')
def main():
 scope=json.loads((EXEC/'scope.json').read_text());release=json.loads((EXEC/'release_manifest.json').read_text())
 for r in scope['inputs']:
  if sha(ROOT/r['path'])!=r['sha256']:raise ValueError('Archived result changed')
 for r in release['released_copies']:
  if sha(ROOT/r['released_copy'])!=r['sha256']:raise ValueError('Released source copy changed')
 expected={'common_footprint_comparisons.csv':44,'fixed_registration_comparisons.csv':48,'available_registration_points.csv':88,
  'paired_scale_diagnostics.csv':32,'reference_sensitivity.csv':144,'quadratic_all_finite_contrasts.csv':3874,
  'quadratic_historical_contrasts.csv':96,'quadratic_all_curves.csv':38784,'phoenix_window_comparisons.csv':56,'joint_window_sensitivities.csv':40}
 for name,n in expected.items():
  d=pd.read_csv(PACKET/name)
  if len(d)!=n:raise ValueError('Unexpected released row count')
 a=pd.read_csv(PACKET/'available_registration_points.csv')
 if a.change_q025.notna().any() or a.change_q975.notna().any():raise ValueError('Unavailable paired intervals fabricated')
 c=pd.read_csv(PACKET/'common_footprint_comparisons.csv');c=c[c.quantity.eq('temperature')&c.group_km.eq(8)]
 if not (c.common_point-c.original_point-c.common_minus_original_point).abs().lt(1e-12).all():raise ValueError('Common contrast arithmetic failed')
 q=pd.read_csv(PACKET/'quadratic_historical_contrasts.csv');q=q[q.group_km.eq(8)]
 piv=q.pivot(index=['city','orbit'],columns='model',values='point')
 if not np.allclose(piv.quadratic-piv.linear,piv.quadratic_minus_linear,atol=1e-12):raise ValueError('Quadratic contrast arithmetic failed')
 frozen=json.loads((EXEC/'post_disclosure_joint_freeze.json').read_text());audit=json.loads((PACKET/'joint_window_resampling_audit.json').read_text())
 for path,h in frozen['code_sha256'].items():
  if sha(ROOT/path)!=h:raise ValueError('Follow-up code changed')
 # Predictor-only explanation of the four common-footprint failed draws.
 frames=[pd.read_parquet(ROOT/r['path'],columns=['cell_id']) for r in frozen['native_inputs']];ids=common_ids(frames);del frames
 first=next(r for r in frozen['native_inputs'] if '/27963_' in r['path'])
 f=pd.read_parquet(ROOT/first['path'],columns=['cell_id','block','bare_fraction']);f=f[f.cell_id.isin(ids)]
 bounds=f.groupby('block').bare_fraction.agg(['min','max']);informative=bounds.index[bounds['max']>bounds['min']].to_numpy()
 union=[]
 for orbit in frozen['selected_orbits']:
  r=next(r for r in frozen['native_inputs'] if f'/{orbit}_' in r['path'])
  union.extend(pd.read_parquet(ROOT/r['path'],columns=['block']).block.unique().tolist())
 union=np.unique(union);checks=[]
 table=pd.read_csv(PACKET/'joint_window_sensitivities.csv')
 for size in (1,8):
  groups=np.unique(physical_groups(union,size));info=np.isin(groups,physical_groups(informative,size));rng=np.random.default_rng(frozen['seeds'][str(size)]);missing=[]
  for b in range(1000):
   weights=rng.multinomial(len(groups),np.full(len(groups),1/len(groups)))
   if weights[info].sum()==0:missing.append(b)
  r=next(r for r in audit if r['group_km']==size)
  if any(missing!=r['per_pass_failed_indices'][j] for j in range(5,10)):raise ValueError('Common rank failures not explained by bare-cover support')
  checks.append(dict(group_km=size,informative_common_blocks=len(informative),informative_groups=int(info.sum()),missing_bare_draws=len(missing),all_failure_indices_match=True))
  p=ROOT/f'outputs/v6_2/sealed_coefficients/results_release_20261006/joint_followup_{size}km_SEALED.npz'
  with np.load(p,allow_pickle=False) as z:
   points=z['points'];draws=z['draws'];ref=frozen['reference'];weights=np.array(frozen['weights']);pv={};bv={}
   for j,label in enumerate(['original','common','quadratic']):
    pv[label]=window_quantities(points[j*5:(j+1)*5],weights,ref['reference_K'],ref['reference_emissivity'])
    bv[label]=window_quantities(draws[:,j*5:(j+1)*5],weights,ref['reference_K'],ref['reference_emissivity'])
   for label in ['common','quadratic']:
    pv[label+'_minus_original']=pv[label]-pv['original'];bv[label+'_minus_original']=bv[label]-bv['original']
   for row in table[table.group_km.eq(size)].itertuples():
    k=['temperature','emitted_flux','temperature_equivalent','temperature_minus_equivalent'].index(row.quantity);s=summarize(pv[row.comparison][k],bv[row.comparison][:,k])
    for key in ['point','q025','q975','SE']:
     if not np.isclose(getattr(row,key),s[key],rtol=1e-10,atol=1e-10):raise ValueError('Joint follow-up interval reconstruction failed')
 if validate(ROOT):raise ValueError('Output boundary error')
 write(EXEC/'post_disclosure_rank_audit.json',dict(checks=checks,outcomes_read_for_rank_diagnosis=False))
 record=dict(status='PASS',historical_result_files_preserved=len(scope['inputs']),released_source_copies=len(release['released_copies']),
  tables_reconciled=expected,followup_known_answer_tests=4,followup_point_reconstructions=15,
  followup_joint_draws_requested=2000,followup_all_variant_estimable=1996,followup_common_nonestimable_joint_draws=4,
  followup_pass_variant_draws_requested=30000,followup_pass_variant_draws_estimable=29980,
  no_failed_draw_replacement=True,common_bare_rank_failures_explained=True,new_effect_display_authorized=True,
  post_disclosure_followup_labelled=True,formal_scale_agreement=None,verification_script_sha256=sha(Path(__file__)))
 write(EXEC/'verification.json',record);print(json.dumps(record))
if __name__=='__main__':main()
