from pathlib import Path
import geopandas as gpd,numpy as np,rasterio,json,math
from rasterio.features import rasterize
from rasterio.transform import from_origin
ROOT=Path(__file__).resolve().parents[2];out=ROOT/'data/raw/v2/pilot_v6_2_20260919/atlanta_context'
p=out/'atlanta_building_presence_10m.tif'
if not p.exists():
 d=gpd.read_parquet(out/'atlanta_buildings_32616.parquet');g=gpd.read_file(ROOT/'data/raw/v2/domains/census_urban_areas.geojson');bounds=g[g.city=='atlanta'].to_crs(32616).total_bounds
 l,b,r,t=[math.floor(bounds[i]/10)*10 if i<2 else math.ceil(bounds[i]/10)*10 for i in range(4)];l-=100;b-=100;r+=100;t+=100;tr=from_origin(l,t,10,10)
 a=rasterize(((v,1) for v in d.geometry),out_shape=(int((t-b)/10),int((r-l)/10)),transform=tr,fill=0,all_touched=False,dtype='uint8')
 with rasterio.open(p,'w',driver='GTiff',width=a.shape[1],height=a.shape[0],count=1,dtype='uint8',crs='EPSG:32616',transform=tr,compress='deflate',tiled=True) as ds:ds.write(a,1)
 print('BUILDING_RASTER',a.shape,len(d),flush=True)
