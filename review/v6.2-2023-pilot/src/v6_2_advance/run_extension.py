"""Bounded, resumable exploratory extension; preserve the original pilot."""
from pathlib import Path
import json,sys,hashlib,datetime
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from urban_cooling_v2.pooled_city_pass import fit_city_pass,public_precision
from urban_cooling_v2.pilot_native import ContextGrid,discover,build_pass
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
from run_v6_2_pooled_pilot import digest,write_json
import geopandas as gpd
from shapely.geometry import shape
from shapely import make_valid
import run_v6_2_d1d_stage1_precision as old

def run():
 manifest=ROOT/'docs/v2/v6_2/execution/advance_20260921/phoenix_execution_manifest.json'
 c=json.loads(manifest.read_text());P=lambda n:guarded_output_path(ROOT,'scientific',c['run_id']+'/'+n);S=lambda n:guarded_output_path(ROOT,'sealed',c['run_id']+'/'+n)
 P('execution_freeze.json').parent.mkdir(parents=True,exist_ok=True);S('manifest_SEALED.json').parent.mkdir(parents=True,exist_ok=True);S('manifest_SEALED.json').parent.chmod(0o700)
 paths=[Path(__file__),ROOT/'src/urban_cooling_v2/pooled_city_pass.py',ROOT/'src/urban_cooling_v2/pilot_native.py']
 stamp={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'manifest_sha256':digest(manifest),'code_sha256':{str(p.relative_to(ROOT)):digest(p) for p in paths},'prior_effect_access':'original ten gradients disclosed 20260919','analysis_status':'exploratory_extension','new_time_model':'none; plot first','original_pilot':'unchanged'}
 fp=P('execution_freeze.json')
 if fp.exists():
  before=json.loads(fp.read_text());assert before['manifest_sha256']==stamp['manifest_sha256'] and before['code_sha256']==stamp['code_sha256'],'Changed frozen execution'
 else:write_json(fp,stamp)
 verified=json.loads((Path(c['emissivity_root'])/'manifest.json').read_text());assert all(x['status']=='VERIFIED' for x in verified['files'])
 g=gpd.GeoSeries([make_valid(shape(c['domain']))],crs=4326).to_crs(c['city_epsg']).iloc[0]
 a,t,crs,n=old._building_presence_10m(g.bounds);ctx=ContextGrid(c['context_paths'],(a.astype(np.float32),t,crs))
 bundles=discover(c['thermal_root'],c['orbits'],c['emissivity_root']);rows=[];failures=[]
 for orbit in c['orbits']:
  path=S(f'{orbit}_paired_native_cells_SEALED.parquet')
  if path.exists():base=pd.read_parquet(path)
  else:
   frames,ledger=build_pass([b for b in bundles if int(b['orbit'])==orbit],c['domain'],c['city'],c['city_epsg'],ctx,shifts=[(0,0)])
   base=frames[(0,0)];base.to_parquet(path,index=False);path.chmod(0o600);pd.DataFrame(ledger).to_csv(P(f'{orbit}_native_ownership_audit.csv'),index=False)
  for size in [1,2,4,8]:
   variant='paired_primary' if size==1 else f'spatial_{size}km';jp=P(f'{orbit}_{variant}_precision.json');dest=S(f'{orbit}_{variant}_SEALED.npz')
   if jp.exists() and dest.exists():rows.append(json.loads(jp.read_text()));continue
   cluster='block'
   if size>1:
    cluster='spatial_group';base[cluster]=[f'{x}_{y}' for x,y in zip(np.floor(base.x/(size*1000)).astype(int),np.floor(base.y/(size*1000)).astype(int))]
   try:
    fit=fit_city_pass(base,bootstrap_replicates=c['bootstrap_replicates'],seed=c['seed'],cluster_column=cluster)
    row=public_precision(fit,city=c['city'],pass_id=f'{c["city"]}:{orbit}',variant=variant);row.update(c['pass_metadata'][str(orbit)])
    np.savez_compressed(dest,coefficients=fit.coefficients,bootstrap_coefficients=fit.bootstrap_coefficients,predictor_names=fit.predictor_names,outcome_names=fit.outcome_names,block_labels=fit.block_labels,block_x_means=fit.block_x_means,block_y_means=fit.block_y_means);dest.chmod(0o600)
    write_json(jp,row);rows.append(row)
    print(json.dumps({'orbit':orbit,'variant':variant,'cells':len(base),'SE_K_per_10pp':row['LST_K_SE_per_10pp']}),flush=True)
   except ValueError as e:
    failures.append({'orbit':orbit,'variant':variant,'status':'NOT_ESTIMABLE','reason':str(e)});print(json.dumps(failures[-1]),flush=True)
   pd.DataFrame(rows).to_csv(P('precision.csv'),index=False);write_json(P('failures.json'),failures)
  del base
 pd.DataFrame(rows).to_csv(P('precision.csv'),index=False)
 write_json(P('completion.json'),{'completed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'requested_passes':len(c['orbits']),'primary_fits':sum(x['variant']=='paired_primary' for x in rows),'fits':len(rows),'failures':failures,'registration_and_full_composition_sensitivity':'pending_for_added_passes'})
if __name__=='__main__':run()
