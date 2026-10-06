from pathlib import Path
import pandas as pd,json,hashlib,requests,concurrent.futures,rasterio
ROOT=Path(__file__).resolve().parents[2];stage=(ROOT/'docs/v2/v6_2/execution');out=ROOT/'data/raw/v2/pilot_v6_2_20260919';(out/'atlanta_lste').mkdir(exist_ok=True)
screen=json.loads((stage/'canopy_screen_summary.json').read_text());score={r['city']:r['sampled_within_block_variance'] for r in screen};assert score['atlanta']>score['charlotte']>score['phoenix']
m=pd.read_csv(ROOT/'docs/v2/hitl/G3_SAMPLING_DESIGN/angle_threshold_pass_detail_existing_five.csv')
m=m[(m.city=='atlanta')&(m.year==2023)&(m.l1b_view_zenith_abs_p95_deg<=25)&(m.l1b_geometry_coverage_fraction>=.95)].drop_duplicates('orbit').sort_values('acquisition_utc').head(5)
assert len(m)==5;orbits=m.orbit.astype(int).tolist()
columns=['orbit','acquisition_utc','l1b_view_zenith_abs_p95_deg','l1b_geometry_coverage_fraction','local_solar_time_hours','clear_domain_fraction','view_azimuth_complete','relative_azimuth_complete']
freeze={'created_utc':pd.Timestamp.now(tz='UTC').isoformat(),'selected_city':'atlanta','canopy_variance_screen':score,'rule':'largest_sampled_stable_canopy_within_block_variance_among_Atlanta_Charlotte_then_verified_afternoon_acquisitions; first_five_chronological_2023_Jun_Sep_in_inherited_nonthermal_inventory_with_L1B_p95_at_most_25_and_domain_geometry_coverage_at_least_0_95','catalogue_complete_audit':json.loads((stage/'catalogue_audit_summary.json').read_text()),'sample_frame_limitation':'first_five_from_existing_verified_L1B_geometry_inventory_not_claimed_exhaustive_near_nadir_inventory','collection':'002','orbits':orbits,'passes':json.loads(m[columns].to_json(orient='records')),'thermal_values_seen_before_selection':False,'geometry_exception':'25deg_precision_set_matches_inherited_Phoenix_design_missing_azimuth_prevents_claim_of_complete_secondary_geometry_model','season':'2023-06-01_through_2023-09-30','selection_basis':'canopy_and_acquisition_metadata_only_no_precision_or_effect_selection'}
freeze_path=stage/'atlanta_selection_freeze.json'
if freeze_path.exists():
 old=json.loads(freeze_path.read_text());assert old['orbits']==orbits;freeze=old
else:freeze_path.write_text(json.dumps(freeze,indent=2))
print('FROZEN ATLANTA ORBITS',orbits,flush=True)
rows=json.loads((stage/'catalogue_atlanta_002.json').read_text())['granules'];chosen={}
for r in rows:
 if r['orbit'] not in orbits:continue
 key=(r['orbit'],r['scene'],r['tile']);parts=r['granule_id'].split('_');priority=(int(parts[-2]),int(parts[-1]))
 if key not in chosen or priority>chosen[key][0]:chosen[key]=(priority,r)
token=(Path.home()/'.config/urban-tree-cooling/earthdata_token').read_text().strip()
tasks=[]
for _,r in chosen.values():
 for band in ['LST','QC','cloud','water','EmisWB','height']:
  name=r['granule_id']+'_'+band+'.tif';url=f'https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/ECO_L2T_LSTE.002/{r["granule_id"]}/{name}';tasks.append((name,url))
def fetch(item):
 name,url=item;p=out/'atlanta_lste'/name
 if not p.exists():
  for attempt in range(3):
   try:
    r=requests.get(url,headers={'Authorization':'Bearer '+token},timeout=120);r.raise_for_status();tmp=p.with_suffix('.partial');tmp.write_bytes(r.content)
    with rasterio.open(tmp) as d:assert d.count==1
    tmp.replace(p);break
   except Exception:
    if attempt==2:return {'asset':name,'status':'DOWNLOAD_FAILED'}
 return {'asset':name,'url':url,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'status':'VERIFIED_RASTER'}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:result=list(ex.map(fetch,tasks))
(out/'atlanta_lste/download_manifest.json').write_text(json.dumps({'selection_freeze_sha256':hashlib.sha256(freeze_path.read_bytes()).hexdigest(),'assets':result},indent=2))
print(json.dumps({'assets':len(result),'failed':[r['asset'] for r in result if r['status']!='VERIFIED_RASTER']}))
