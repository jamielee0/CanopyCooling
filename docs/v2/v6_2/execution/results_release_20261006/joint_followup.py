"""Prospectively record a post-disclosure follow-up, then reuse existing models."""
from pathlib import Path
import json,sys,os,hashlib,gc
from datetime import datetime,timezone
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parents[5];sys.path.insert(0,str(ROOT/'src'))
from urban_cooling_v2.pooled_city_pass import CONTEXT
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
from v6_2_advance.spatial_review import block_stats,common_ids,identity_hash,validate_native_rows
from v6_2_advance.window_uncertainty import joint_passes,window_quantities,summarize
from v6_2_advance.released_window_sensitivity import reference_quadratic_stats
EXEC=Path(__file__).resolve().parent;RUN='results_release_20261006';PACKET=ROOT/'deliverables/Pilot_Results_Review_2023_v6_2_20261006'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
def output(name):
 p=guarded_output_path(ROOT,'scientific',f'{RUN}/{name}');p.parent.mkdir(parents=True,exist_ok=True);return p

def main():
 os.umask(0o077)
 prior=json.loads((ROOT/'docs/v2/v6_2/execution/quadratic_step5_20261005/execution_freeze.json').read_text())
 specs=[p for p in prior['passes'] if p['city']=='phoenix'];selected=[27963,28192,28828,28909,29092];weights=np.array([.5,-.5,-.25,.5,-.25])
 reference=json.loads((ROOT/'outputs/v6_2/scientific/scale_diagnostics_20260919/frozen_numeric_references.json').read_text())
 code=[Path(__file__),ROOT/'src/v6_2_advance/released_window_sensitivity.py',ROOT/'src/v6_2_advance/window_uncertainty.py',ROOT/'src/v6_2_advance/spatial_review.py',ROOT/'tests/v6_2_advance/test_released_window_sensitivity.py']
 freeze=EXEC/'post_disclosure_joint_freeze.json'
 record=dict(request='lets not keep it sealed then? Can you do the next steps?',recorded_utc=datetime.now(timezone.utc).isoformat(),
  reason='Released point summaries show time-contrast sensitivity to footprint and model; compute the missing joint uncertainty before final synthesis',
  timing='post-disclosure exploratory follow-up; not blinded or preplanned before effect review',
  scope='existing five dates, original linear/common linear/original quadratic; same six controls and old reference; no new data or model selection',
  supersedes_release_scope_no_new_computation_only_for_this_check=True,new_mean_model_specifications=False,new_joint_bootstrap=True,
  data_link_target=prior['data_link_target'],native_inputs=[{'path':p['path'],'sha256':p['sha256']} for p in specs],
  selected_orbits=selected,weights=weights.tolist(),common_definition='exact all-eleven intersection196090 cells, unchanged from Step3',
  reference=reference,groups_km=[1,8],replicates=1000,seeds={'1':20261707,'8':20261714},
  basis='quadratic f²-(f0+f1)f formed from raw squared canopy; algebraically identical finite contrast; all controls protected by full-rank checks',
  draw_rule='same physical-union multiplicities across all dates and all three variants; failures retained without replacement',
  new_effect_display_authorized=True,scale_ruling=None,code_sha256={str(p.relative_to(ROOT)):sha(p) for p in code})
 if freeze.exists():raise ValueError('Preserve existing follow-up freeze and outputs')
 write(freeze,record)
 assert str((ROOT/'data').resolve(strict=True))==record['data_link_target']
 for p in specs:
  if sha(ROOT/p['path'])!=p['sha256']:raise ValueError('Original native sample changed')
 idframes=[pd.read_parquet(ROOT/p['path'],columns=['cell_id']) for p in specs];ids=common_ids(idframes);del idframes
 if len(ids)!=196090 or identity_hash(ids)!='1dbbd7fdd7c00023c97d0858dcc271b27ab5eef1d46cf393878f3bf504487db3':raise ValueError('Common footprint changed')
 expected_common=json.loads((ROOT/'outputs/v6_2/sealed_coefficients/spatial_scale_review_20261004/common_footprint_review_SEALED.json').read_text())
 expected_quad=pd.read_csv(PACKET/'quadratic_all_finite_contrasts.csv')
 stats={k:[] for k in ('original','common','quadratic')};access=[]
 for orbit in selected:
  p=next(p for p in specs if p['orbit']==orbit);columns=['cell_id','block','x','y','native_crs','native_x','native_y','canopy_fraction',*CONTEXT,'LST_K','M_W_m2']
  f=pd.read_parquet(ROOT/p['path'],columns=columns);validate_native_rows(f);c=f[f.cell_id.isin(ids)]
  a=block_stats(f,['canopy_fraction',*CONTEXT]);b=block_stats(c,['canopy_fraction',*CONTEXT]);q=reference_quadratic_stats(f,reference['f0'],reference['f1'],CONTEXT)
  expected=next(r for r in expected_common if int(r['orbit'])==orbit and r['group_km']==8)
  for model,point in [(a,expected['original']['point']),(b,expected['common']['point'])]:
   if not np.allclose(-.1*model.solve()[0],point,atol=1e-8,rtol=0):raise ValueError('Original/common point recovery failed')
  oldq=expected_quad[expected_quad.city.eq('phoenix')&expected_quad.orbit.eq(orbit)&expected_quad.pair_id.eq('historical')&expected_quad.group_km.eq(8)&expected_quad.model.eq('quadratic')].set_index('quantity')
  if not np.allclose(-.1*q.solve()[0],oldq.loc[['temperature','emitted_flux'],'point'],atol=1e-8,rtol=0):raise ValueError('Quadratic finite-contrast recovery failed')
  for label,value in [('original',a),('common',b),('quadratic',q)]:stats[label].append(value)
  access.append(dict(orbit=orbit,path=p['path'],columns=columns,original_cells=len(f),common_cells=len(c),all_points_recovered=True))
  del f,c;gc.collect()
 write(EXEC/'post_disclosure_access.json',access)
 allstats=[s for models in stats.values() for s in models];rows=[];audits=[]
 for size in (1,8):
  points,draws,audit=joint_passes(allstats,group_km=size,replicates=1000,seed=record['seeds'][str(size)])
  pv={};bv={}
  for j,label in enumerate(stats):
   pv[label]=window_quantities(points[j*5:(j+1)*5],weights,reference['reference_K'],reference['reference_emissivity'])
   bv[label]=window_quantities(draws[:,j*5:(j+1)*5],weights,reference['reference_K'],reference['reference_emissivity'])
  for label in ('common','quadratic'):
   pv[label+'_minus_original']=pv[label]-pv['original'];bv[label+'_minus_original']=bv[label]-bv['original']
  for label in pv:
   for j,quantity in enumerate(['temperature','emitted_flux','temperature_equivalent','temperature_minus_equivalent']):
    rows.append(dict(comparison=label,group_km=size,quantity=quantity,units='W_m2_per_10pp' if quantity=='emitted_flux' else 'K_per_10pp',
     review_status='EXPLORATORY_POST_DISCLOSURE',**summarize(pv[label][j],bv[label][:,j])))
  audit['variant_order']=list(stats);audit['orbits_per_variant']=selected;audits.append(audit)
  private=guarded_output_path(ROOT,'sealed',f'{RUN}/joint_followup_{size}km_SEALED.npz');private.parent.mkdir(parents=True,exist_ok=True);private.parent.chmod(0o700)
  np.savez_compressed(private,points=points,draws=draws,**bv);private.chmod(0o600)
  print(json.dumps(dict(group_km=size,complete_all_variant_draws=audit['complete_city_draws'],per_variant_pass_estimable=audit['per_pass_estimable'])),flush=True)
 d=pd.DataFrame(rows);d.to_csv(output('joint_window_sensitivities.csv'),index=False);d.to_csv(PACKET/'joint_window_sensitivities.csv',index=False)
 write(output('joint_window_resampling_audit.json'),audits);write(PACKET/'joint_window_resampling_audit.json',audits)
 print(d[d.group_km.eq(8)&d.quantity.eq('temperature')][['comparison','point','q025','q975','estimable','failed']].to_string(index=False))

if __name__=='__main__':main()
