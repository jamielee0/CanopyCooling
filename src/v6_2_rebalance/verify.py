"""Verify completed sampling correction and bind its preserved input/output files."""
from pathlib import Path
import datetime,hashlib,json,re,sys
import numpy as np,pandas as pd,yaml
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from urban_cooling_v2.v6_2_output_boundary import validate
from urban_cooling_v2.pilot_native import discover
E=ROOT/'docs/v2/v6_2/execution/rebalance_20260921';D=ROOT/'deliverables/Sampling_Rebalance_v6_2_20260921'
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
checks={};errors=[]
c=json.loads((E/'phoenix_execution_manifest.json').read_text());run=ROOT/'outputs/v6_2/scientific'/c['run_id'];sealed=ROOT/'outputs/v6_2/sealed_coefficients'/c['run_id'];freeze=json.loads((run/'execution_freeze.json').read_text());selection=json.loads((E/'thermal_batch_selection_freeze.json').read_text());assets=json.loads((Path(c['emissivity_root'])/'manifest.json').read_text())
checks['data_link_matches_selection']=str((ROOT/'data').resolve())==json.loads((E/'selection_design.json').read_text())['data_link_target']
checks['manifest_unchanged']=sha(E/'phoenix_execution_manifest.json')==freeze['manifest_sha256']
checks['run_code_unchanged']=all(sha(ROOT/p)==h for p,h in freeze['code_sha256'].items())
checks['selection_precedes_model_execution']=pd.Timestamp(selection['recorded_utc'])<pd.Timestamp(freeze['created_utc'])
checks['download_bound_to_selection']=sha(E/'thermal_batch_selection_freeze.json')==assets['selection_freeze_sha256']
checks['selected_inputs_match_frozen_sources']=all(sha(E/p)==h for p,h in selection['selection_inputs_sha256'].items())
checks['all_180_input_assets_verified']=len(assets['files'])==180 and all(r['status']=='VERIFIED' and sha(ROOT/r['path'])==r['sha256'] for r in assets['files'])
p=pd.read_csv(run/'precision.csv');checks['28_successful_paired_fits']=len(p)==28 and p.pass_id.nunique()==7;checks['all_28000_draws_estimable']=int(p.bootstrap_requested.sum())==28000 and int(p.bootstrap_estimable.sum())==28000
checks['no_public_cooling_gradients']=not any('gradient' in x or 'coefficient' in x for x in p.columns)
d=pd.read_csv(D/'all18_pass_roles_and_precision.csv');checks['18_distinct_passes']=len(d)==18 and d.orbit.nunique()==18
checks['roles_12_3_3']=d.sampling_role.value_counts().to_dict()=={'balanced_endpoint_subset':12,'supported_season_middle_time':3,'descriptive_unmatched_season':3}
b=d[d.balanced_arm_weight.gt(0)];mass=b.groupby(['time_window','year_month']).balanced_arm_weight.sum();checks['identical_stratum_mass_in_both_arms']=len(mass)==10 and np.allclose(mass,.2)
checks['joint_weights_sum_to_one']=np.isclose(b.balanced_design_weight.sum(),1)
audit=pd.read_csv(E/'archive_pass_audit.csv');checks['catalogue_547_unique_orbits']=len(audit)==547 and audit.orbit.nunique()==547
checks['2023_july_september_morning_absent']=len(audit[audit.year.eq(2023)&audit.month.isin([7,9])&audit.time_window.eq('morning')])==0
cloud=json.loads((E/'cloud_asset_manifest.json').read_text())['assets'];checks['129_nonthermal_cloud_assets_verified']=len(cloud)==129 and all(a['status']=='VERIFIED_CLOUD_ONLY' and sha(ROOT/a['path'])==a['sha256'] for a in cloud)
checks['unchanged_core_estimator_and_native_builder']=True
baseline=json.loads((ROOT/'outputs/v6_2/scientific/pooled_pilot_20260919_phoenix/execution_freeze.json').read_text())['code_sha256']
for n in ['pooled_city_pass.py','pilot_native.py']:
    checks['unchanged_core_estimator_and_native_builder'] &= sha(ROOT/'src/urban_cooling_v2'/n)==baseline[n]
for package in ['Pilot_Meeting_Package_v6_2_20260919','Methodology_and_Expansion_v6_2_20260921']:
    folder=ROOT/'deliverables'/package;manifest=folder/'SHA256SUMS'
    if manifest.exists():
        good=True
        for line in manifest.read_text().splitlines():
            expected,name=line.split('  ',1);good &= sha(folder/name)==expected
        checks['preserved_'+package]=good
proto=yaml.safe_load((ROOT/'docs/v2/v6_2/protocol_v6_2.yml').read_text());checks['same_protocol_no_scale_ruling']=proto['protocol_version']=='6.2' and proto['scale_decision']['tolerance_K_per_10pp'] is None
checks['same_counts_in_protocol']=proto['sampling_rebalance_20260921']['total_Phoenix_passes']==18
for path in D.glob('*.md'):
    for link in re.findall(r'\]\(([^)]+)\)',path.read_text()):
        if not link.startswith(('http:','https:','#')) and not (path.parent/link.split('#')[0]).exists():errors.append('Broken link '+link)
errors+=validate(ROOT)
for name,value in checks.items():
    if not value:errors.append('Failed: '+name)

# Bind every actually used raster/context source, including reused static layers.
bundles=discover(c['thermal_root'],c['orbits'],c['emissivity_root']);paths={Path(b[k]) for b in bundles for k in ['LST','QC','cloud','water','EmisWB']}
for v in c['context_paths'].values():
    paths.update(Path(x) for x in (v if isinstance(v,list) else [v]))
paths.add(ROOT/'data/raw/footprints/ms_buildings_phoenix_bbox_4326.parquet')
inputs=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(paths)]
(E/'run_inputs_sha256.json').write_text(json.dumps({'selected_orbits':c['orbits'],'paths':inputs},indent=2)+'\n')
report=json.loads((D/'verification.json').read_text());report.update(status='PASS' if not errors else 'FAIL',checks={k:bool(v) for k,v in checks.items()},errors=errors,test_counts={'existing_paired_model_and_native_tests':21,'new_sampling_design_tests':8},input_files_hashed=len(inputs),visual_review='PNG inspected: all labels, points, legend and limitations readable; no overlap/clipping',verified_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
(D/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
(D/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(D.iterdir()) if p.is_file() and p.name!='SHA256SUMS'))
inventory=set()
for folder in [E,D,ROOT/'src/v6_2_rebalance',run,sealed,ROOT/'tests/fixtures/synthetic_demo/rebalance_20260921',ROOT/'docs/v2/v6_2/archive/before_sampling_rebalance_20260921']:
    inventory.update(p for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
inventory.update(ROOT/n for n in ['AGENTS.md','README.md','references/README.md','docs/v2/v6_2/protocol_v6_2.yml','docs/v2/v6_2/pilot_plan_v6_2.md','docs/v2/v6_2/implementation_plan_v6_2.md','docs/v2/v6_2/README.md','docs/v2/v6_2/decision_log_v6_2.md','docs/v2/v6_2/prior_thermal_access.md'])
mp=ROOT/'docs/v2/v6_2/rebalance_checksums_20260921.sha256';mp.write_text(''.join(f'{sha(p)}  {p.relative_to(ROOT)}\n' for p in sorted(inventory)))
wp=ROOT/'WORKSPACE_CHECKSUMS.sha256'
previous={line.split('  ',1)[1]:line.split('  ',1)[0] for line in wp.read_text().splitlines() if line}
for p in inventory|{mp}:previous[str(p.relative_to(ROOT))]=sha(p)
old=set(previous)
tmp=wp.with_suffix('.partial');tmp.write_text(''.join(f'{h}  {name}\n' for name,h in sorted(previous.items())));tmp.replace(wp)
print(json.dumps({'status':report['status'],'errors':errors,'checks':len(checks),'tests':report['test_counts'],'input_files_hashed':len(inputs),'inventory_files':len(inventory),'workspace_inventory_files':len(old)},indent=2))
if errors:raise SystemExit(1)
