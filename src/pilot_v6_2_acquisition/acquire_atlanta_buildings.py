from pathlib import Path
import requests,json,hashlib,zipfile
import geopandas as gpd
ROOT=Path(__file__).resolve().parents[2];out=ROOT/'data/raw/v2/pilot_v6_2_20260919/atlanta_context';out.mkdir(parents=True,exist_ok=True)
url='https://minedbuildings.z5.web.core.windows.net/legacy/usbuildings-v2/Georgia.geojson.zip';dest=out/'Georgia_usbuildings_v2.geojson.zip'
if not dest.exists():
 with requests.get(url,stream=True,timeout=120) as r:
  r.raise_for_status()
  with dest.with_suffix('.partial').open('wb') as f:
   for chunk in r.iter_content(4*1024*1024):f.write(chunk)
 dest.with_suffix('.partial').replace(dest)
print('BUILDING_ARCHIVE_BYTES',dest.stat().st_size,flush=True)
g=gpd.read_file(ROOT/'data/raw/v2/domains/census_urban_areas.geojson');domain=g[g.city=='atlanta'];bounds=tuple(domain.total_bounds)
# GDAL's bbox filter streams features from the state archive into this pilot domain.
with zipfile.ZipFile(dest) as z: member=[n for n in z.namelist() if n.endswith('.geojson')][0]
b=gpd.read_file('/vsizip/'+str(dest)+'/'+member,bbox=bounds,engine='pyogrio');b=b.to_crs(32616);b.to_parquet(out/'atlanta_buildings_32616.parquet')
(out/'buildings_provenance.json').write_text(json.dumps({'source':url,'license':'ODbL','release':'legacy/usbuildings-v2_same_release_family_as_inherited_Phoenix','vintage':'varies_by_source_imagery_not_asserted_all_2022','archive_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'bbox_features':len(b),'source_crs':'EPSG:4326'},indent=2));print('ATLANTA_BUILDING_FEATURES',len(b))
