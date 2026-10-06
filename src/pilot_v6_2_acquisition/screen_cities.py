import ee,json,concurrent.futures,hashlib
from pathlib import Path
import numpy as np,geopandas as gpd
from shapely.geometry import shape,box,mapping
from shapely import make_valid
from shapely.ops import transform
from pyproj import Transformer
ROOT=Path(__file__).resolve().parents[2];OUT=(ROOT/'docs/v2/v6_2/execution');OUT.mkdir(exist_ok=True)
ee.Initialize(project='tree-497018')
domains={x['properties']['city']:x for x in json.loads((ROOT/'data/raw/v2/domains/census_urban_areas.geojson').read_text())['features']}
cf=[f for f in json.loads((ROOT/'docs/v2/v6_2/execution/charlotte_domain.geojson').read_text())['features'] if f['properties']['GEOID']=='15670'][0];cf['properties']['city']='charlotte';domains['charlotte']=cf
collection='projects/gtac-data-publish/assets/TCC/Product_Version/2025-6'
images=ee.ImageCollection.fromImages([ee.Image(f'{collection}/TCC_v2025-6_CONUS_{y}').select('Science_Percent_Tree_Canopy_Cover').rename('canopy') for y in range(2019,2026)])
first=images.first();stable=images.count().eq(7).And(images.max().subtract(images.min()).lte(15));canopy=images.median().divide(100).updateMask(stable)
def one(city,epsg):
 if (OUT/f'{city}_canopy_screen.json').exists(): return json.loads((OUT/f'{city}_canopy_screen.json').read_text())['summary']
 geom=make_valid(shape(domains[city]['geometry']));tf=Transformer.from_crs(4326,epsg,always_xy=True).transform;back=Transformer.from_crs(epsg,4326,always_xy=True).transform;g=make_valid(transform(tf,geom));xmin,ymin,xmax,ymax=g.bounds
 cells=[]
 for x in range(int(np.floor(xmin/1000)*1000),int(xmax),1000):
  for y in range(int(np.floor(ymin/1000)*1000),int(ymax),1000):
   b=box(x,y,x+1000,y+1000).intersection(g)
   if not b.is_empty and b.area>=500000: cells.append((x,y,b))
 selected=np.random.default_rng(20260919).choice(len(cells),min(300,len(cells)),replace=False)
 fc=ee.FeatureCollection([ee.Feature(ee.Geometry(mapping(transform(back,cells[i][2])),geodesic=False),{'block':f'{cells[i][0]}_{cells[i][1]}'}) for i in selected])
 reducer=ee.Reducer.variance().combine(ee.Reducer.count(),sharedInputs=True).combine(ee.Reducer.mean(),sharedInputs=True)
 result=canopy.reduceRegions(collection=fc,reducer=reducer,crs=first.projection(),scale=30,tileScale=4).getInfo()
 rows=[f['properties'] for f in result['features']];valid=[r for r in rows if r.get('count',0)>1 and r.get('variance') is not None]
 counts=np.array([r['count'] for r in valid]);variances=np.array([r['variance'] for r in valid]);sxx=(counts-1)*variances
 summary={'city':city,'design':'seeded_300_1km_blocks_at_least_50pct_urban_area_30m_stable_Science_TCC_not_yet_ECOSTRESS_pass_mask','seed':20260919,'eligible_blocks':len(cells),'sampled_blocks':len(selected),'valid_blocks':len(valid),'sampled_Sxx':float(sxx.sum()),'sampled_within_block_variance':float(sxx.sum()/counts.sum()),'median_block_variance':float(np.median(variances)),'max_block_information_share':float(sxx.max()/sxx.sum()),'block_variance_quantiles':np.quantile(variances,[0,.1,.5,.9,1]).tolist(),'sampled_mean_canopy':float(np.average([r['mean'] for r in valid],weights=counts))}
 (OUT/f'{city}_canopy_screen.json').write_text(json.dumps({'summary':summary,'blocks':rows},indent=2)); print(json.dumps(summary),flush=True)
 return summary
(OUT/'candidate_domains.geojson').write_text(json.dumps({'type':'FeatureCollection','features':[domains[c] for c in ['phoenix','atlanta','charlotte']]}))
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
 summaries=list(ex.map(lambda x:one(*x),[('phoenix',32612),('atlanta',32616),('charlotte',32617)]))
(OUT/'canopy_screen_summary.json').write_text(json.dumps(summaries,indent=2))
