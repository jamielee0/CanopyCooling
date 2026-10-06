from pathlib import Path
import requests,json,math,hashlib
import geopandas as gpd,rasterio,numpy as np
ROOT=Path(__file__).resolve().parents[2];out=ROOT/'data/raw/v2/pilot_v6_2_20260919/atlanta_context'
g=gpd.read_file(ROOT/'data/raw/v2/domains/census_urban_areas.geojson');bounds=g[g.city=='atlanta'].to_crs(32616).total_bounds
l,b,r,t=[math.floor(bounds[i]/30)*30 if i<2 else math.ceil(bounds[i]/30)*30 for i in range(4)];l-=3000;b-=3000;r+=3000;t+=3000
u='https://di-nlcd.img.arcgis.com/arcgis/rest/services/USA_NLCD_Annual_LandCover/ImageServer'
s=requests.Session();q=s.get(u+'/query',params={'where':'Year=2024','outFields':'OBJECTID,Name,Year,Version','returnGeometry':'false','f':'json'},timeout=60);q.raise_for_status();rows=q.json();print('NLCD YEAR IDENTITIES',rows,flush=True)
ids=[f['attributes']['OBJECTID'] for f in rows.get('features',[]) if '1.1' in str(f['attributes'].get('Version',''))]
if not ids:raise ValueError('Cannot verify Annual NLCD Collection 1.1 2024 source')
params={'bbox':','.join(map(str,[l,b,r,t])),'bboxSR':32616,'imageSR':32616,'size':f'{int((r-l)/30)},{int((t-b)/30)}','format':'tiff','pixelType':'U8','noData':0,'interpolation':'+RSP_NearestNeighbor','mosaicRule':json.dumps({'mosaicMethod':'esriMosaicLockRaster','lockRasterIds':ids}),'renderingRule':json.dumps({'rasterFunction':'None'}),'f':'json'}
r=s.post(u+'/exportImage',data=params,timeout=180);r.raise_for_status();d=r.json()
if 'href' not in d:raise ValueError(str(d))
r=s.get(d['href'],timeout=180);r.raise_for_status();p=out/'atlanta_annual_nlcd_c1_1_2024_land_cover.tif';p.write_bytes(r.content)
with rasterio.open(p) as ds:print('EXPORTED_NLCD',ds.shape,'classes',np.unique(ds.read(1)).tolist())
(out/'annual_nlcd_export_provenance.json').write_text(json.dumps({'service':u,'source_items':rows,'request':params,'response':d,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()},indent=2))
