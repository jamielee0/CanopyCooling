"""Cloud-mask-only opportunity screen at the frozen canopy-screen block points."""
from pathlib import Path
import json,sys,hashlib,concurrent.futures,datetime
import requests,numpy as np,pandas as pd,rasterio
from shapely.geometry import shape,box
from shapely import make_valid
from shapely.ops import transform
from pyproj import Transformer
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'docs/v2/v6_2/execution/advance_20260921';RAW=ROOT/'data/raw/v2/advance_v6_2_20260921/candidate_cloud_masks';RAW.mkdir(parents=True,exist_ok=True)
TOKEN=(Path.home()/'.config/urban-tree-cooling/earthdata_token').read_text().strip()
domains={f['properties']['city']:f for f in json.loads((OUT/'candidate_domains.geojson').read_text())['features']};index={r['city']:r for r in json.loads((OUT/'candidate_domain_index.json').read_text())}
freeze=OUT/'cloud_screen_design.json'
if not freeze.exists():freeze.write_text(json.dumps({'recorded_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'all nineteen candidate cities; 2023 June-September apparent solar 15:00<=hour<18:00 CMR passes; cloud masks only, no LST/emissivity','sample':'one point at center of each frozen sampled canopy-screen block if inside urban domain; otherwise representative point of block/domain intersection; equal block weights','rule':'report observed point coverage, clear among observed, and clear fraction of all sampled points; no inclusion threshold; any-cloud veto over overlapping tiles/scenes; retain missing masks as missing','limits':'sampling proxy for urban cloud opportunity, not full-resolution valid-cell coverage; no water/view-angle/thermal-quality screening; morning cloud availability remains to audit'},indent=2))
assets=[];summary=[];point_rows=[]
for city in index:
 out=OUT/f'{city}_afternoon_cloud_screen.json'
 if out.exists():
  j=json.loads(out.read_text());summary.extend(j['passes']);assets.extend(j['assets']);continue
 epsg=index[city]['epsg'];g=make_valid(transform(Transformer.from_crs(4326,epsg,always_xy=True).transform,make_valid(shape(domains[city]['geometry']))));back=Transformer.from_crs(epsg,4326,always_xy=True)
 blocks=json.loads((OUT/f'{city}_canopy_screen.json').read_text())['blocks'];coordinates=[];block_ids=[]
 for b in blocks:
  x,y=map(int,b['block'].split('_'));part=box(x,y,x+1000,y+1000).intersection(g);pt=box(x,y,x+1000,y+1000).centroid
  if not part.covers(pt):pt=part.representative_point()
  coordinates.append(back.transform(pt.x,pt.y));block_ids.append(b['block'])
 coordinates=np.asarray(coordinates);passes=pd.read_csv(OUT/f'{city}_2023_pass_opportunities.csv');passes=passes[passes.solar_hour.between(15,18,inclusive='left')]
 cat=pd.DataFrame(json.loads((OUT/f'{city}_2023_catalogue.json').read_text())['granules']);cat=cat[cat.orbit.isin(passes.orbit)].sort_values('granule_id').drop_duplicates(['orbit','scene','tile'],keep='last')
 def asset(row):
  gid=row.granule_id;p=RAW/(gid+'_cloud.tif');url=f'https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/ECO_L2T_LSTE.002/{gid}/{p.name}'
  try:
   if not p.exists():
    for k in range(3):
     try:
      response=requests.get(url,headers={'Authorization':'Bearer '+TOKEN},timeout=120);response.raise_for_status();tmp=p.with_suffix('.partial');tmp.write_bytes(response.content)
      with rasterio.open(tmp) as z:assert z.count==1
      tmp.replace(p);break
     except Exception:
      if k==2:raise
   with rasterio.open(p) as z:
    xy=Transformer.from_crs(4326,z.crs,always_xy=True).transform(coordinates[:,0],coordinates[:,1]);xy=np.column_stack(xy);inside=(xy[:,0]>=z.bounds.left)&(xy[:,0]<z.bounds.right)&(xy[:,1]>z.bounds.bottom)&(xy[:,1]<=z.bounds.top)
    vals=np.full(len(coordinates),np.nan)
    if inside.any():
     s=np.ma.vstack(list(z.sample(xy[inside],masked=True))).astype(float).filled(np.nan)[:,0];vals[inside]=s
   return {'city':city,'orbit':int(row.orbit),'asset':p.name,'url':url,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'status':'VERIFIED_RASTER'},vals
  except Exception as e:return {'city':city,'orbit':int(row.orbit),'asset':p.name,'status':'FAILED','error_type':type(e).__name__},np.full(len(coordinates),np.nan)
 byorbit={int(o):[] for o in passes.orbit};cityassets=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
  for a,v in ex.map(asset,cat.itertuples(index=False)):
   cityassets.append(a);byorbit[a['orbit']].append(v)
 rows=[]
 for row in passes.itertuples(index=False):
  matrix=np.asarray(byorbit[int(row.orbit)]);valid=(matrix==0)|(matrix==1);observed=valid.any(axis=0);cloud=(matrix==1).any(axis=0);clear=observed&~cloud
  record={'city':city,'orbit':int(row.orbit),'acquisition_utc':row.acquisition_utc,'solar_hour':row.solar_hour,'sample_points':len(coordinates),'observed_points':int(observed.sum()),'clear_points':int(clear.sum()),'sample_point_coverage_fraction':float(observed.mean()),'clear_fraction_of_observed_points':float(clear.sum()/observed.sum()) if observed.any() else None,'clear_fraction_of_all_sample_points':float(clear.mean()),'failed_assets':sum(a['status']!='VERIFIED_RASTER' for a in cityassets if a['orbit']==row.orbit)};rows.append(record)
  point_rows.extend({'city':city,'orbit':int(row.orbit),'block':b,'observed':bool(o),'clear':bool(c)} for b,o,c in zip(block_ids,observed,clear))
 out.write_text(json.dumps({'design':'cloud_screen_design.json','passes':rows,'assets':cityassets},indent=2));summary.extend(rows);assets.extend(cityassets)
 print(json.dumps({'cloud_completed':city,'passes':len(rows),'median_clear_fraction_all_points':float(np.median([x['clear_fraction_of_all_sample_points'] for x in rows])),'failed_assets':sum(a['status']!='VERIFIED_RASTER' for a in cityassets)}),flush=True)
 pd.DataFrame(summary).to_csv(OUT/'afternoon_cloud_pass_screen.csv',index=False)
pd.DataFrame(summary).to_csv(OUT/'afternoon_cloud_pass_screen.csv',index=False);pd.DataFrame(point_rows).to_csv(OUT/'afternoon_cloud_sample_points.csv',index=False)
(OUT/'candidate_cloud_assets.json').write_text(json.dumps({'cloud_only':True,'assets':assets},indent=2))
