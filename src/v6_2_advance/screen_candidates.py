"""Nonthermal city screen: Census urban areas, canopy heterogeneity, CMR opportunity."""
from pathlib import Path
import sys,json,requests,concurrent.futures,hashlib,datetime
import numpy as np,pandas as pd,ee
from shapely.geometry import shape,box,mapping,Polygon
from shapely import make_valid
from shapely.ops import transform
from pyproj import Transformer
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from urban_cooling_v2.independent_foundation_audit import local_solar_hour
OUT=ROOT/'docs/v2/v6_2/execution/advance_20260921';ee.Initialize(project='tree-497018')
EXTRA={'raleigh':('73261',32617),'washington':('92242',32618),'baltimore':('04843',32618),'philadelphia':('69076',32618),'new_york':('63217',32618),'boston':('09271',32619),'chicago':('16264',32616),'houston':('40429',32615),'dallas':('22042',32614),'denver':('23527',32613),'sacramento':('77068',32610),'portland':('71317',32610),'seattle':('80389',32610)}
EPSG={'phoenix':32612,'los_angeles':32611,'atlanta':32616,'minneapolis_st_paul':32615,'miami':32617,'charlotte':32617,**{c:v[1] for c,v in EXTRA.items()}}
DOM=OUT/'candidate_domains.geojson'
if DOM.exists():domains={f['properties']['city']:f for f in json.loads(DOM.read_text())['features']}
else:
 domains={f['properties']['city']:f for f in json.loads((ROOT/'data/raw/v2/domains/census_urban_areas.geojson').read_text())['features']}
 f=json.loads((ROOT/'docs/v2/v6_2/execution/charlotte_domain.geojson').read_text())['features'][0];f['properties']['city']='charlotte';domains['charlotte']=f
 url='https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Urban/MapServer/0/query'
 for city,(geoid,epsg) in EXTRA.items():
  response=requests.get(url,params={'where':f"GEOID='{geoid}'",'outFields':'GEOID,NAME','outSR':4326,'returnGeometry':'true','f':'geojson'},timeout=120);response.raise_for_status();features=response.json()['features'];assert len(features)==1,(city,len(features));f=features[0];f['properties']['city']=city;domains[city]=f
 DOM.write_text(json.dumps({'type':'FeatureCollection','features':list(domains.values())}))
index=[]
for city,f in domains.items():
 g=make_valid(shape(f['geometry']));cent=g.centroid
 index.append({'city':city,'geoid':f['properties'].get('GEOID'),'name':f['properties'].get('NAME',city),'epsg':EPSG[city],'longitude':cent.x,'latitude':cent.y,'domain_source':'Census TIGERweb urban areas','bounds':list(g.bounds)})
(OUT/'candidate_domain_index.json').write_text(json.dumps(index,indent=2))
collection='projects/gtac-data-publish/assets/TCC/Product_Version/2025-6'
images=ee.ImageCollection.fromImages([ee.Image(f'{collection}/TCC_v2025-6_CONUS_{y}').select('Science_Percent_Tree_Canopy_Cover').rename('canopy') for y in range(2019,2026)])
first=images.first();stable=images.count().eq(7).And(images.max().subtract(images.min()).lte(15));canopy=images.median().divide(100).updateMask(stable)
def screen(city):
 path=OUT/f'{city}_canopy_screen.json';old=ROOT/f'docs/v2/v6_2/execution/{city}_canopy_screen.json'
 if path.exists():return json.loads(path.read_text())['summary']
 if old.exists():
  j=json.loads(old.read_text());j['reused_from']=str(old.relative_to(ROOT));j['reused_source_sha256']=hashlib.sha256(old.read_bytes()).hexdigest();path.write_text(json.dumps(j,indent=2));return j['summary']
 geom=make_valid(shape(domains[city]['geometry']));tf=Transformer.from_crs(4326,EPSG[city],always_xy=True).transform;back=Transformer.from_crs(EPSG[city],4326,always_xy=True).transform;g=make_valid(transform(tf,geom));xmin,ymin,xmax,ymax=g.bounds
 cells=[]
 for x in range(int(np.floor(xmin/1000)*1000),int(xmax),1000):
  for y in range(int(np.floor(ymin/1000)*1000),int(ymax),1000):
   b=box(x,y,x+1000,y+1000).intersection(g)
   if not b.is_empty and b.area>=500000:cells.append((x,y,b))
 selected=np.random.default_rng(20260919).choice(len(cells),min(300,len(cells)),replace=False)
 fc=ee.FeatureCollection([ee.Feature(ee.Geometry(mapping(transform(back,cells[i][2])),geodesic=False),{'block':f'{cells[i][0]}_{cells[i][1]}'}) for i in selected])
 reducer=ee.Reducer.variance().combine(ee.Reducer.count(),sharedInputs=True).combine(ee.Reducer.mean(),sharedInputs=True)
 result=canopy.reduceRegions(collection=fc,reducer=reducer,crs=first.projection(),scale=30,tileScale=4).getInfo();rows=[f['properties'] for f in result['features']];valid=[r for r in rows if r.get('count',0)>1 and r.get('variance') is not None]
 counts=np.array([r['count'] for r in valid]);variances=np.array([r['variance'] for r in valid]);sxx=(counts-1)*variances
 summary={'city':city,'design':'seeded_300_1km_blocks_at_least_50pct_urban_area_30m_stable_Science_TCC_not_yet_ECOSTRESS_pass_mask','seed':20260919,'eligible_blocks':len(cells),'sampled_blocks':len(selected),'valid_blocks':len(valid),'sampled_Sxx':float(sxx.sum()),'sampled_within_block_variance':float(sxx.sum()/counts.sum()),'median_block_variance':float(np.median(variances)),'max_block_information_share':float(sxx.max()/sxx.sum()),'block_variance_quantiles':np.quantile(variances,[0,.1,.5,.9,1]).tolist(),'sampled_mean_canopy':float(np.average([r['mean'] for r in valid],weights=counts))}
 path.write_text(json.dumps({'summary':summary,'blocks':rows},indent=2));print(json.dumps({'canopy_completed':city,'variance':summary['sampled_within_block_variance']}),flush=True);return summary

def catalogue(city):
 path=OUT/f'{city}_2023_catalogue.json'
 if path.exists():return json.loads(path.read_text())['audit']
 geom=make_valid(shape(domains[city]['geometry']));lon=geom.centroid.x;headers={};rows=[];received=0;pages=0;seen=set()
 while True:
  r=requests.get('https://cmr.earthdata.nasa.gov/search/granules.json',params={'concept_id':'C2076090826-LPCLOUD','bounding_box':','.join(map(str,geom.bounds)),'temporal':'2023-06-01T00:00:00Z,2023-09-30T23:59:59Z','page_size':2000,'sort_key':'start_date'},headers=headers,timeout=120);r.raise_for_status();items=r.json()['feed']['entry'];hits=int(r.headers['CMR-Hits']);received+=len(items);pages+=1
  for x in items:
   fp=[]
   for parts in x.get('polygons',[]):
    for p in parts:
     v=list(map(float,p.split()));fp.append(make_valid(Polygon([(v[i+1],v[i]) for i in range(0,len(v),2)])))
   for b in x.get('boxes',[]):
    south,west,north,east=map(float,b.split());fp.append(box(west,south,east,north))
   if not fp or not any(geom.intersects(f) for f in fp):continue
   gid=x['producer_granule_id'];bits=gid.split('_');dt=pd.Timestamp(x['time_start']).to_pydatetime();h=local_solar_hour(dt,lon)
   rows.append({'city':city,'orbit':int(bits[3]),'scene':int(bits[4]),'tile':bits[5],'granule_id':gid,'acquisition_utc':x['time_start'],'apparent_solar_hour_at_domain_centroid':h,'cloud_cover_metadata':x.get('cloud_cover')})
  if received>=hits or not items:break
  token=r.headers.get('CMR-Search-After');assert token and token not in seen;seen.add(token);headers={'CMR-Search-After':token}
 assert received==hits,(city,received,hits)
 d=pd.DataFrame(rows);d['cloud_cover_metadata']=pd.to_numeric(d.cloud_cover_metadata,errors='coerce');d.loc[~d.cloud_cover_metadata.between(0,100),'cloud_cover_metadata']=np.nan
 # Revisions deduplicated without temperature or QA-outcome selection.
 d=d.sort_values('granule_id').drop_duplicates(['orbit','scene','tile'],keep='last');p=d.groupby('orbit').agg(acquisition_utc=('acquisition_utc','min'),solar_hour=('apparent_solar_hour_at_domain_centroid','median'),tiles=('tile','nunique'),tile_mean_cloud_pct=('cloud_cover_metadata','mean')).reset_index();p['city']=city
 a=p[p.solar_hour.between(15,18,inclusive='left')];m=p[p.solar_hour.between(9.5,11.5,inclusive='left')]
 audit={'city':city,'retrieved_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'period_utc':'2023-06-01/2023-09-30','CMR_bbox_hits':hits,'CMR_rows_received':received,'pages':pages,'intersecting_granules_before_revision_dedup':len(rows),'unique_passes':len(p),'morning_0930_1130_passes':len(m),'afternoon_1500_1800_passes':len(a),'afternoon_months':sorted(a.acquisition_utc.str[5:7].unique().tolist()),'afternoon_tile_mean_cloud_pct_median':float(a.tile_mean_cloud_pct.median()) if a.tile_mean_cloud_pct.notna().any() else None,'afternoon_passes_with_cloud_metadata':int(a.tile_mean_cloud_pct.notna().sum()),'limitation':'CMR tile cloud metadata is not urban-domain clear fraction; no view-angle, full-domain coverage or usable-cell certification; windows are descriptive summaries, not selection gates.'}
 path.write_text(json.dumps({'audit':audit,'granules':rows},indent=2));p.to_csv(OUT/f'{city}_2023_pass_opportunities.csv',index=False);print(json.dumps({'catalogue_completed':city,'passes':len(p),'afternoon':len(a)}),flush=True);return audit

cities=json.loads((OUT/'advance_scope.json').read_text())['screen_candidate_pool']
fail=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
 jobs={ex.submit(fn,city):(fn.__name__,city) for fn in [screen,catalogue] for city in cities}
 for future in concurrent.futures.as_completed(jobs):
  try:future.result()
  except Exception as e:
   record={'task':jobs[future],'error':type(e).__name__,'message':str(e)[:300]};fail.append(record);print(json.dumps(record),flush=True)
can=[json.loads((OUT/f'{c}_canopy_screen.json').read_text())['summary'] for c in cities if (OUT/f'{c}_canopy_screen.json').exists()]
cat=[json.loads((OUT/f'{c}_2023_catalogue.json').read_text())['audit'] for c in cities if (OUT/f'{c}_2023_catalogue.json').exists()]
pd.DataFrame(can).merge(pd.DataFrame(cat),on='city',how='outer').sort_values('sampled_within_block_variance',ascending=False).to_csv(OUT/'candidate_city_screen.csv',index=False);(OUT/'screen_failures.json').write_text(json.dumps(fail,indent=2))
