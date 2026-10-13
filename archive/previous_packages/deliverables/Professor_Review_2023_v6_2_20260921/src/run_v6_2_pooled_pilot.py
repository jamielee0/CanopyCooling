#!/usr/bin/env python3
"""Run the explicitly authorized small pilot, publishing precision only.

Usage: python src/run_v6_2_pooled_pilot.py --manifest path.json
The manifest is frozen before any new fit. A second-city manifest must include
its prior nonthermal selection record. Existing historical runners are untouched.
"""
import argparse,json,hashlib,os,sys
from pathlib import Path
from datetime import datetime,timezone
import numpy as np,pandas as pd
from urban_cooling_v2.pooled_city_pass import fit_city_pass,public_precision
from urban_cooling_v2.pilot_native import ContextGrid,discover,build_pass
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path

def digest(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

def write_json(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(value,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else str(x))+'\n')

def run(manifest_path):
 config=json.loads(manifest_path.read_text());root=Path(config['repository']);runid=config['run_id']
 P=lambda name:guarded_output_path(root,'scientific',runid+'/'+name)
 S=lambda name:guarded_output_path(root,'sealed',runid+'/'+name)
 public=P('execution_freeze.json').parent;sealed=S('manifest_SEALED.json').parent
 public.mkdir(parents=True,exist_ok=True);sealed.mkdir(parents=True,exist_ok=True);sealed.chmod(0o700)
 if config.get('coefficient_release_authorized') is not False:raise ValueError('This runner requires sealed precision-only operation')
 if config['city']!='phoenix' and not config.get('nonthermal_selection_record'):raise ValueError('Second city must be selected before thermal access')
 frozen=P('execution_freeze.json')
 code_paths=[Path(__file__),Path(__file__).parent/'urban_cooling_v2/pooled_city_pass.py',Path(__file__).parent/'urban_cooling_v2/pilot_native.py']
 stamp={'started_utc':datetime.now(timezone.utc).isoformat(),'manifest_sha256':digest(manifest_path),'configuration':config,'code_sha256':{p.name:digest(p) for p in code_paths},'thermal_access':'authorized_existing_selected_passes_for_sealed_fit_and_aggregate_simulation_inputs','effects_not_examined':True}
 if frozen.exists():
  prior=json.loads(frozen.read_text())
  if prior['manifest_sha256']!=stamp['manifest_sha256'] or prior['code_sha256']!=stamp['code_sha256']:raise ValueError('Run already frozen under different settings/code; use a new run id and record reason')
 else:write_json(frozen,stamp)
 building=None
 if config.get('building_source')=='inherited_phoenix_footprints_10m':
  import run_v6_2_d1d_stage1_precision as old
  import geopandas as gpd
  from shapely.geometry import shape
  from shapely import make_valid
  g=gpd.GeoSeries([make_valid(shape(config['domain']))],crs=4326).to_crs(config['city_epsg']).iloc[0]
  a,t,c,n=old._building_presence_10m(g.bounds);building=(a.astype(np.float32),t,c)
  write_json(P('building_aggregation.json'),{'footprints':n,'method':'center-rasterized_10m_binary_footprints_then_area_average','limitation':'10m raster approximation_to_exact_vector_area_fraction'})
 ctx=ContextGrid(config['context_paths'],building)
 bundles=discover(config['thermal_root'],config['orbits'],config['emissivity_root'])
 rows=[];audits=[];failures=[];primary_paths=[]
 def fit_and_save(frame,orbit,variant,cluster='block'):
  fit=fit_city_pass(frame,bootstrap_replicates=config['bootstrap_replicates'],seed=config['seed'],cluster_column=cluster)
  row=public_precision(fit,city=config['city'],pass_id=f'{config["city"]}:{orbit}',variant=variant)
  row.update(config.get('pass_metadata',{}).get(str(orbit),{}));rows.append(row)
  dest=S(f'{orbit}_{variant}_SEALED.npz')
  np.savez_compressed(dest,coefficients=fit.coefficients,bootstrap_coefficients=fit.bootstrap_coefficients,predictor_names=fit.predictor_names,outcome_names=fit.outcome_names,block_labels=fit.block_labels,block_x_means=fit.block_x_means,block_y_means=fit.block_y_means)
  dest.chmod(0o600)
  pd.DataFrame(rows).to_csv(P('precision.csv'),index=False)
  print(json.dumps({'city':config['city'],'orbit':orbit,'variant':variant,'cells':len(frame),'SE_K_per_10pp':row['LST_K_SE_per_10pp'],'contributing_blocks':row['contributing_blocks']}),flush=True)
 for orbit in config['orbits']:
  frames,ledger=build_pass([b for b in bundles if int(b['orbit'])==orbit],config['domain'],config['city'],config['city_epsg'],ctx,shifts=[tuple(x) for x in config['registration_shifts']])
  for row in ledger:row['orbit']=orbit
  audits.extend(ledger);pd.DataFrame(audits).to_csv(P('native_ownership_audit.csv'),index=False)
  base=frames[(0,0)];p=S(f'{orbit}_paired_native_cells_SEALED.parquet');base.to_parquet(p,index=False);p.chmod(0o600);primary_paths.append((orbit,p))
  # Fit support diagnostics contain no arbitrary .20/.10 or minimum-cell gates.
  for shift,frame in frames.items():
   variant='paired_primary' if shift==(0,0) else f'registration_dx{shift[0]}_dy{shift[1]}'
   try:fit_and_save(frame,orbit,variant)
   except ValueError as e:failures.append({'orbit':orbit,'variant':variant,'status':'NOT_ESTIMABLE','reason':str(e)})
  try:fit_and_save(base,orbit,'spatial_2km',cluster='block_2km')
  except ValueError as e:failures.append({'orbit':orbit,'variant':'spatial_2km','status':'NOT_ESTIMABLE','reason':str(e)})
  del frames,base
 sets=[set(pd.read_parquet(p,columns=['cell_id']).cell_id) for _,p in primary_paths];common=set.intersection(*sets)
 write_json(P('common_cell_support.json'),{'common_cells':len(common),'pass_count':len(sets),'method':'exact_native_grid_cell_identity_across_all_five_passes'})
 for orbit,p in primary_paths:
  frame=pd.read_parquet(p);frame=frame[frame.cell_id.isin(common)]
  try:fit_and_save(frame,orbit,'common_cells')
  except ValueError as e:failures.append({'orbit':orbit,'variant':'common_cells','status':'NOT_ESTIMABLE','reason':str(e)})
 write_json(P('nonestimable_variants.json'),failures)
 primary=pd.DataFrame(rows);primary=primary[primary.variant=='paired_primary']
 summary={'city':config['city'],'passes_reported':len(primary),'planned_passes':len(config['orbits']),'median_SE_K_per_10pp':float(primary.LST_K_SE_per_10pp.median()) if len(primary) else None,'min_SE_K_per_10pp':float(primary.LST_K_SE_per_10pp.min()) if len(primary) else None,'max_SE_K_per_10pp':float(primary.LST_K_SE_per_10pp.max()) if len(primary) else None,'passes_at_or_below_0_10_SE_benchmark':int((primary.LST_K_SE_per_10pp<=.10).sum()) if len(primary) else 0,'precision_decision':'DESCRIPTIVE_FOR_REVIEW_NO_FOUR_OF_FIVE_GATE','scale_ruling':'PENDING_REZA_TOLERANCE_AND_COEFFICIENT_RELEASE','nonestimable_variants':failures}
 write_json(P('precision_summary.json'),summary)
 return summary
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);args=p.parse_args();run(args.manifest)
