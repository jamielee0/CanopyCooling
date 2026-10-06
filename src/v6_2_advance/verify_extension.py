"""Validate the bounded extension and freeze a complete new-run inventory."""
from pathlib import Path
import sys,json,hashlib,datetime,subprocess,re
import numpy as np,pandas as pd,yaml
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from urban_cooling_v2.pilot_native import discover
from urban_cooling_v2.v6_2_output_boundary import validate
E=ROOT/'docs/v2/v6_2/execution/advance_20260921';D=ROOT/'deliverables/Methodology_and_Expansion_v6_2_20260921'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
errors=validate(ROOT);checks={};c=json.loads((E/'phoenix_execution_manifest.json').read_text());run=ROOT/'outputs/v6_2/scientific'/c['run_id'];sealed=ROOT/'outputs/v6_2/sealed_coefficients'/c['run_id'];p=pd.read_csv(run/'precision.csv')
checks['six_new_passes_and_24_fits']=p[p.variant=='paired_primary'].pass_id.nunique()==6 and len(p)==24
checks['full_primary_bootstrap_success']=int(p[p.variant=='paired_primary'].bootstrap_failed.sum())==0
checks['one_logged_8km_rank_failure']=int(p.bootstrap_failed.sum())==1
checks['new_model_failure_list_empty']=json.loads((run/'failures.json').read_text())==[]
for city in ['phoenix','atlanta']:
 freeze=json.loads((ROOT/f'outputs/v6_2/scientific/pooled_pilot_20260919_{city}/execution_freeze.json').read_text())
 baseline_root=ROOT/'docs/v2/v6_2/execution/phoenix_frozen_code' if city=='phoenix' else ROOT/'src'
 candidates={q.name:q for q in [baseline_root/'run_v6_2_pooled_pilot.py',baseline_root/'urban_cooling_v2/pooled_city_pass.py',baseline_root/'urban_cooling_v2/pilot_native.py']}
 checks[f'{city}_estimator_and_native_builder_match_current']=all(sha(candidates[name])==sha(ROOT/'src/urban_cooling_v2'/name) for name in ['pooled_city_pass.py','pilot_native.py'])
 checks[f'original_{city}_frozen_primary_code_unchanged']=all(sha(candidates[name])==digest for name,digest in freeze['code_sha256'].items())
 checks[f'original_{city}_execution_manifest_unchanged']=sha(ROOT/f'docs/v2/v6_2/execution/{city}_execution_manifest.json')==freeze['manifest_sha256']
for name in ['pooled','advance']:
 x=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(ROOT/f'tests/v6_2_{name}'),'-q'],cwd=ROOT,text=True,capture_output=True)
 checks[f'{name}_test_suite']=x.returncode==0
 if x.returncode:errors.append(x.stderr)
# Check projection ownership/duplication and paired energy reconstruction in all new passes.
from urban_cooling_v2.pooled_city_pass import emitted_energy
for orbit in c['orbits']:
 x=pd.read_parquet(sealed/f'{orbit}_paired_native_cells_SEALED.parquet',columns=['cell_id','native_crs','native_x','native_y','LST_K','M_W_m2','emissivity'])
 checks[f'{orbit}_unique_native_cells']=not x.cell_id.duplicated().any() and not x[['native_crs','native_x','native_y']].duplicated().any()
 checks[f'{orbit}_paired_physical_units']=np.allclose(x.M_W_m2,emitted_energy(x.LST_K,x.emissivity),rtol=1e-12)
 del x
screen=pd.read_csv(D/'candidate_city_screen.csv');cloud=pd.read_csv(E/'afternoon_cloud_pass_screen.csv');assets=json.loads((E/'candidate_cloud_assets.json').read_text())['assets'];unique={a['asset']:a for a in assets}
checks['nineteen_screened_cities']=screen.city.nunique()==19
checks['all_catalogue_pages_accounted_for']=bool((screen.CMR_bbox_hits==screen.CMR_rows_received).all())
checks['155_cloud_passes_and_535_unique_assets']=len(cloud)==155 and len(unique)==535
checks['no_failed_cloud_assets']=all(a['status']=='VERIFIED_RASTER' for a in assets)
checks['clear_coverage_bounds']=bool((cloud.clear_points<=cloud.observed_points).all() and (cloud.observed_points<=cloud.sample_points).all())
checks['candidate_cloud_directory_contains_only_cloud_masks']=all(q.name.endswith('_cloud.tif') for q in (ROOT/'data/raw/v2/advance_v6_2_20260921/candidate_cloud_masks').glob('*.tif'))
proto=yaml.safe_load((ROOT/'docs/v2/v6_2/protocol_v6_2.yml').read_text());checks['same_protocol_version_and_no_scale_ruling']=proto['protocol_version']=='6.2' and proto['scale_decision']['tolerance_K_per_10pp'] is None
checks['new_time_model_not_fitted']=json.loads((D/'expansion_summary.json').read_text())['new_time_regression_fitted'] is False
checks['no_effect_columns_in_public_precision']=not any('gradient' in col or 'coefficients' in col for col in p.columns)
for path in D.glob('*.md'):
 for link in re.findall(r'\]\(([^)]+)\)',path.read_text()):
  if not link.startswith(('http:','https:','#')) and not (path.parent/link.split('#')[0]).exists():errors.append(f'Broken package link: {path.name}: {link}')
for k,v in checks.items():
 if not v:errors.append('Failed '+k)
# Source rasters used by this extension, including cached legacy inputs, are hashed explicitly.
bundles=discover(c['thermal_root'],c['orbits'],c['emissivity_root']);paths={Path(b[k]) for b in bundles for k in ['LST','QC','cloud','water','EmisWB']}
for v in c['context_paths'].values():
 for value in (v if isinstance(v,list) else [v]):paths.add(Path(value))
paths.add(ROOT/'data/raw/footprints/ms_buildings_phoenix_bbox_4326.parquet')
inputs=[{'path':str(path.relative_to(ROOT)),'bytes':path.stat().st_size,'sha256':sha(path)} for path in sorted(paths)]
(E/'new_run_inputs_sha256.json').write_text(json.dumps({'selected_orbits':c['orbits'],'paths':inputs,'cloud_assets_manifest':'candidate_cloud_assets.json'},indent=2))
# Inventory source files, freezes, new outputs, sealed files and isolated synthetic outputs.
inventory=set()
for folder in [E,ROOT/'src/v6_2_advance',ROOT/'tests/v6_2_advance',run,sealed,ROOT/'outputs/v6_2/scientific/exploratory_review_20260921',ROOT/'tests/fixtures/synthetic_demo/advance_20260921']:
 inventory.update(q for q in folder.rglob('*') if q.is_file() and '__pycache__' not in q.parts)
for q in [ROOT/'AGENTS.md',ROOT/'README.md',ROOT/'docs/v2/v6_2/protocol_v6_2.yml',ROOT/'docs/v2/v6_2/pilot_plan_v6_2.md',ROOT/'docs/v2/v6_2/decision_log_v6_2.md',ROOT/'src/run_v6_2_d1d_stage1_precision.py',ROOT/'src/urban_cooling_v2/pilot_scale.py',ROOT/'src/urban_cooling_v2/pooled_city_pass.py',ROOT/'src/urban_cooling_v2/pilot_native.py']:
 inventory.add(q)
manifest=ROOT/'docs/v2/v6_2/advance_checksums_20260921.sha256';manifest.write_text(''.join(f'{sha(q)}  {q.relative_to(ROOT)}\n' for q in sorted(inventory)))
report={'verified_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'PASS' if not errors else 'FAIL','checks':{k:bool(v) for k,v in checks.items()},'errors':errors,'test_counts':{'existing_scientific':21,'new_time_resampling':3},'new_bootstrap_draws':24000,'estimable_new_draws':23999,'rank_failure':'phoenix:29545 spatial_8km; 999/1000 draws','input_files_hashed':len(inputs),'new_run_inventory_files':len(inventory),'new_run_inventory':str(manifest.relative_to(ROOT)),'baseline_provenance_note':'Phoenix runner is checked against its archived frozen source; the active original runner acquired guarded output paths before the Atlanta run on 19 September. Estimator and native-builder hashes match both baseline freezes. Initial verification used the wrong current runner for Phoenix; this was corrected without changing the historical code or results.', 'visual_review':'gradient scatter and city screen inspected; figure spacing corrected; no new empirical time regression','limits':'All checks are for the bounded extension; they do not certify full-city readiness, a scale agreement ruling, final Stage2 coverage or independence of 8km groups.'}
(D/'verification.json').write_text(json.dumps(report,indent=2));(D/'SHA256SUMS').write_text(''.join(f'{sha(q)}  {q.name}\n' for q in sorted(D.iterdir()) if q.is_file() and q.name!='SHA256SUMS'))
print(json.dumps({k:report[k] for k in ['status','errors','test_counts','input_files_hashed','new_run_inventory_files','estimable_new_draws']},indent=2))
if errors:raise SystemExit(1)
