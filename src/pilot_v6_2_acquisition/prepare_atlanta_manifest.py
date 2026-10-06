from pathlib import Path
import json,rasterio,numpy as np
ROOT=Path(__file__).resolve().parents[2];stage=(ROOT/'docs/v2/v6_2/execution');ctx=ROOT/'data/raw/v2/pilot_v6_2_20260919/atlanta_context'
canopy=sorted(ctx.glob('science_tcc_v2025-6_atlanta_*_native30m.tif'))
if len(canopy)!=7:raise SystemExit(f'WAITING_ANNUAL_CANOPY {len(canopy)}/7')
source=ctx/'atlanta_nlcd_2021_impervious_and_validity.tif';dem=ctx/'usgs_3dep_10m_atlanta_frozen_census_domain.tif'
if not source.exists() or not dem.exists():raise SystemExit('WAITING_NLCD_OR_DEM')
with rasterio.open(source) as ds:
 for band,name in [(1,'atlanta_nlcd_impervious_2021_30m.tif'),(2,'atlanta_nlcd_validity_2021_30m.tif')]:
  a=ds.read(band);a=np.where(a==-9999,0,a).astype('uint8');profile=ds.profile;profile.update(count=1,dtype='uint8',nodata=0)
  with rasterio.open(ctx/name,'w',**profile) as dst:dst.write(a,1)
# Preserve the first same-city manifest and its thermal-access freeze unchanged.
p=json.loads((stage/'phoenix_execution_manifest.json').read_text());freeze=json.loads((stage/'atlanta_selection_freeze.json').read_text())
domain=[f['geometry'] for f in json.loads((stage/'candidate_domains.geojson').read_text())['features'] if f['properties']['city']=='atlanta'][0]
p.update(run_id='pooled_pilot_20260919_atlanta',city='atlanta',city_epsg=32616,domain=domain,orbits=freeze['orbits'],thermal_root=str(ROOT/'data/raw/v2/pilot_v6_2_20260919/atlanta_lste'),emissivity_root=str(ROOT/'data/raw/v2/pilot_v6_2_20260919/atlanta_lste'),building_source='verified_atlanta_10m_presence',centroid_longitude=-84.3365018,centroid_latitude=33.8362691,nonthermal_selection_record='docs/v2/v6_2/execution/atlanta_selection_freeze.json')
p['context_paths']={'canopy_annual':list(map(str,canopy)),'impervious_fraction':str(ctx/'atlanta_nlcd_impervious_2021_30m.tif'),'impervious_validity':str(ctx/'atlanta_nlcd_validity_2021_30m.tif'),'land_cover':str(ctx/'atlanta_annual_nlcd_c1_1_2024_land_cover.tif'),'elevation':str(dem),'building_fraction':str(ctx/'atlanta_building_presence_10m.tif')}
p['pass_metadata']={str(r['orbit']):{'acquisition_utc':r['acquisition_utc'],'local_solar_hour_inherited_metadata':r['local_solar_time_hours'],'view_zenith_p95_deg':r['l1b_view_zenith_abs_p95_deg'],'collection':'002','frozen_25_degree_precision_exception':True} for r in freeze['passes']}
(stage/'atlanta_execution_manifest.json').write_text(json.dumps(p,indent=2));q=(ROOT/'docs/v2/v6_2/execution/atlanta_execution_manifest.json');q.write_text(json.dumps(p,indent=2));print('ATLANTA_READY')
