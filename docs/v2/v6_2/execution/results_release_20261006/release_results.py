"""Release existing 2023 tables/figures and derive labeled review arithmetic only."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import numpy as np
import pandas as pd
from PIL import Image,ImageOps,ImageDraw

ROOT=Path(__file__).resolve().parents[5];sys.path.insert(0,str(ROOT/'src'))
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
EXEC=Path(__file__).resolve().parent
PACKET=ROOT/'deliverables/Pilot_Results_Review_2023_v6_2_20261006'
RUN='results_release_20261006'

def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
def output(name):
 p=guarded_output_path(ROOT,'scientific',f'{RUN}/{name}');p.parent.mkdir(parents=True,exist_ok=True);return p
def table(name,rows):
 d=rows if isinstance(rows,pd.DataFrame) else pd.DataFrame(rows);p=output(name);d.to_csv(p,index=False)
 PACKET.mkdir(parents=True,exist_ok=True);shutil.copy2(p,PACKET/name);return d

def main():
 auth=json.loads((EXEC/'authorization.json').read_text());scope=json.loads((EXEC/'scope.json').read_text())
 if not auth['new_effect_display_authorized'] or auth['formal_scale_agreement_ruling']:raise ValueError('Wrong release authority')
 if str((ROOT/'data').resolve(strict=True))!=scope['data_link_target']:raise ValueError('Data target changed')
 earlier={}
 for run in auth['allowed_runs']:
  for r in json.loads((ROOT/'docs/v2/v6_2/execution'/run/'completion_manifest.json').read_text())['files']:earlier[r['path']]=r['sha256']
 for row in scope['inputs']:
  if row['path'] not in earlier or earlier[row['path']]!=row['sha256'] or sha(ROOT/row['path'])!=row['sha256']:
   raise ValueError('Historical result checksum mismatch')
 copied=[];base=ROOT/'outputs/v6_2/sealed_coefficients'
 # Reproducible copies preserve all archived originals and their original access labels.
 for run in auth['allowed_runs']:
  for p in sorted((base/run).iterdir()):
   if p.suffix not in ('.json','.csv','.png','.pdf'):continue
   target=PACKET/'released_source_artifacts'/run/p.name.replace('_SEALED','')
   target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
   copied.append(dict(source=str(p.relative_to(ROOT)),released_copy=str(target.relative_to(ROOT)),sha256=sha(target)))
 spatial=base/'spatial_scale_review_20261004'
 load=lambda name:json.loads((spatial/f'{name}_SEALED.json').read_text())
 common=[]
 for r in load('common_footprint_review'):
  for k,(quantity,unit) in enumerate([('temperature','K_per_10pp'),('emitted_flux','W_m2_per_10pp')]):
   row={x:r[x] for x in ('city','orbit','date','group_km','requested','estimable','failed')};row.update(quantity=quantity,units=unit)
   for label in ('original','common','common_minus_original'):
    for field in ('point','q025','q975','SE'):row[label+'_'+field]=r[label][field][k]
   row['relative_change_percent']=100*row['common_minus_original_point']/row['original_point'];common.append(row)
 common=table('common_footprint_comparisons.csv',common)
 fixed=[]
 for r in load('fixed_registration_review'):
  for k,(quantity,unit) in enumerate([('temperature','K_per_10pp'),('emitted_flux','W_m2_per_10pp')]):
   fixed.append(dict(city='phoenix',orbit=r['orbit'],date=r['date'],variant=r['variant'],group_km=1,quantity=quantity,units=unit,
    point=r['point'][k],q025=r['q025'][k],q975=r['q975'][k],SE=r['SE'][k],estimable=r['estimable']))
 table('fixed_registration_comparisons.csv',fixed)
 available=[]
 for r in load('available_registration_review'):
  for k,(quantity,unit) in enumerate([('temperature','K_per_10pp'),('emitted_flux','W_m2_per_10pp')]):
   available.append(dict(city='phoenix',orbit=r['orbit'],date=r['date'],variant=r['variant'],quantity=quantity,units=unit,
    original_point=r['original']['point'][k],shifted_point=r['shifted']['point'][k],change=r['shifted_minus_original'][k],
    change_q025=None,change_q975=None,difference_interval_status=r['difference_interval_status']))
 table('available_registration_points.csv',available)
 paired=[]
 for r in load('paired_scale_review'):
  d=r['paired_T_minus_equivalent'];paired.append(dict(city=r['city'],orbit=r['orbit'],date=r['date'],group_km=r['group_km'],
   temperature_point=r['point'][0],equivalent_point=r['point'][1],temperature_q025=r['q025'][0],temperature_q975=r['q975'][0],
   equivalent_q025=r['q025'][1],equivalent_q975=r['q975'][1],difference=d['point'],difference_q025=d['q025'],difference_q975=d['q975'],
   reference_K=r['reference_K'],reference_emissivity=r['reference_emissivity'],agreement_ruling='NOT_MADE_TOLERANCE_UNSET'))
 table('paired_scale_diagnostics.csv',paired)
 refs=[]
 for r in load('reference_sensitivity_review'):
  refs.append(dict(city=r['city'],orbit=r['orbit'],date=r['date'],temperature_offset_K=r['temperature_offset_K'],emissivity_offset=r['emissivity_offset'],
   reference_K=r['reference_K'],reference_emissivity=r['reference_emissivity'],temperature_point=r['point'][0],equivalent_point=r['point'][1],
   difference=r['paired_T_minus_equivalent']['point']))
 table('reference_sensitivity.csv',refs)
 q=pd.read_csv(base/'quadratic_step5_20261005/finite_contrasts_SEALED.csv');table('quadratic_all_finite_contrasts.csv',q)
 h=q[q.pair_id.eq('historical') & q.quantity.eq('temperature')].copy();table('quadratic_historical_contrasts.csv',h)
 curves=pd.read_csv(base/'quadratic_step5_20261005/curves_SEALED.csv');table('quadratic_all_curves.csv',curves)
 w=pd.read_csv(base/'step7_window_20261005/phoenix_window_comparisons_SEALED.csv');table('phoenix_window_comparisons.csv',w)
 # Arithmetic review of existing pass points; no new fit and no fabricated date pairing.
 weights={27963:.5,28909:.5,28192:-.5,28828:-.25,29092:-.25}
 c=common[common.group_km.eq(8)&common.quantity.eq('temperature')].set_index(common[common.group_km.eq(8)&common.quantity.eq('temperature')].orbit.astype(int))
 hs=h[h.group_km.eq(8)&h.city.eq('phoenix')&h.model.eq('quadratic')].set_index('orbit')
 original=sum(weight*c.loc[orbit,'original_point'] for orbit,weight in weights.items())
 shared=sum(weight*c.loc[orbit,'common_point'] for orbit,weight in weights.items())
 quadratic=sum(weight*hs.loc[orbit,'point'] for orbit,weight in weights.items())
 baseline=w[w.comparison.eq('combined')&w.quantity.eq('temperature')&w.group_km.eq(8)].iloc[0]
 if not np.isclose(original,baseline.point,atol=1e-9,rtol=0):raise ValueError('Frozen-weight original reconstruction failed')
 table('window_point_sensitivities.csv',[
  dict(variant='Original linear / original populations',point=original,q025=baseline.q025,q975=baseline.q975,interval_status='JOINT_8KM_FIXED_DATE_INTERVAL'),
  dict(variant='Original linear / common footprint',point=shared,q025=None,q975=None,interval_status='POINT_ONLY_NO_JOINT_CROSS_DATE_INTERVAL'),
  dict(variant='Quadratic / original populations',point=quadratic,q025=None,q975=None,interval_status='POINT_ONLY_NO_JOINT_CROSS_DATE_INTERVAL')])
 prior=pd.read_csv(ROOT/'outputs/v6_2/scientific/exploratory_review_20260921/pass_gradients_exploratory.csv')
 table('original_pass_results.csv',prior)
 for folder,names in [('Step6_Conditions_2023_v6_2_20261005',['conditions_with_rainfall.csv','geometry_support.csv']),
  ('Spatial_Scale_Review_2023_v6_2_20261004',['common_footprint_predictor_map.png','common_footprint_retention.png'])]:
  for name in names:shutil.copy2(ROOT/'deliverables'/folder/name,PACKET/name)
 # Contact sheets allow every archived quadratic figure to be inspected, both uncertainty sizes.
 qa=EXEC/'qa';qa.mkdir(exist_ok=True)
 images=sorted((base/'quadratic_step5_20261005').glob('*comparison_SEALED.png'))
 sheets=[]
 for i in range(0,len(images),4):
  canvas=Image.new('RGB',(1800,1440),'white');draw=ImageDraw.Draw(canvas)
  for j,p in enumerate(images[i:i+4]):
   im=Image.open(p).convert('RGB');im.thumbnail((900,700));x=(j%2)*900;y=(j//2)*720
   canvas.paste(im,(x,y+20));draw.text((x+10,y+3),p.name,fill='black')
  path=qa/f'quadratic_contact_{i//4+1:02d}.png';canvas.save(path);sheets.append(str(path.relative_to(ROOT)))
 write(EXEC/'release_manifest.json',dict(request=auth['request'],scope_sha256=sha(EXEC/'scope.json'),historical_files_verified=len(scope['inputs']),
  released_copies=copied,raw_model_storage='Preserved under historical filenames; current2023 access authorized, no other-year release',
  post_disclosure_arithmetic='Frozen weights applied to archived common-footprint and quadratic pass points; no new mean fit or bootstrap; alternative joint time intervals unavailable',
  quadratic_contact_sheets=sheets,formal_scale_ruling=None))
 print(json.dumps(dict(released_source_artifacts=len(copied),historical_files_verified=len(scope['inputs']),review_tables=11,quadratic_contact_sheets=len(sheets),
  original_window=original,common_window_point_only=shared,quadratic_window_point_only=quadratic)))

if __name__=='__main__':main()
