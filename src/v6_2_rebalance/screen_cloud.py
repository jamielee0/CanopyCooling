"""Fixed-block cloud screen; outcome-free, not a valid-cell certification."""
from pathlib import Path
import argparse, concurrent.futures, hashlib, json, datetime
import numpy as np
import pandas as pd
import requests, rasterio
from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import shape,box
from shapely.ops import transform
from sampling_design import revision_dedup

def main(root):
    out=root/'docs/v2/v6_2/execution/rebalance_20260921'
    previous=root/'docs/v2/v6_2/execution/advance_20260921'
    raw=root/'data/raw/v2/rebalance_v6_2_20260921/cloud';raw.mkdir(parents=True,exist_ok=True)
    population=pd.read_csv(out/'cloud_screen_population.csv')
    cat=revision_dedup(json.loads((root/'docs/v2/v6_2/execution/catalogue_phoenix_002.json').read_text())['granules'])
    cat=cat[cat.orbit.isin(population.orbit)]
    feature=next(f for f in json.loads((previous/'candidate_domains.geojson').read_text())['features'] if f['properties']['city']=='phoenix')
    g=make_valid(transform(Transformer.from_crs(4326,32612,always_xy=True).transform,make_valid(shape(feature['geometry']))))
    back=Transformer.from_crs(32612,4326,always_xy=True)
    blocks=json.loads((previous/'phoenix_canopy_screen.json').read_text())['blocks']
    xy=[];ids=[]
    for b in blocks:
        x,y=map(int,b['block'].split('_'));cell=box(x,y,x+1000,y+1000);part=cell.intersection(g);pt=cell.centroid
        if not part.covers(pt):pt=part.representative_point()
        xy.append(back.transform(pt.x,pt.y));ids.append(b['block'])
    xy=np.asarray(xy)
    token=(Path.home()/'.config/urban-tree-cooling/earthdata_token').read_text().strip()
    caches=[root/'data/raw/ecostress_lst',root/'data/raw/v2/advance_v6_2_20260921/candidate_cloud_masks',raw]
    def fetch(row):
        name=row.granule_id+'_cloud.tif';path=next((x/name for x in caches if (x/name).exists()),raw/name)
        url=f'https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/ECO_L2T_LSTE.002/{row.granule_id}/{name}'
        vals=np.full(len(xy),np.nan)
        try:
            if not path.exists():
                for attempt in range(3):
                    try:
                        r=requests.get(url,headers={'Authorization':'Bearer '+token},timeout=90);r.raise_for_status();tmp=path.with_suffix('.partial');tmp.write_bytes(r.content)
                        with rasterio.open(tmp) as z: assert z.count==1
                        tmp.replace(path);break
                    except Exception:
                        if attempt==2:raise
            with rasterio.open(path) as z:
                co=np.column_stack(Transformer.from_crs(4326,z.crs,always_xy=True).transform(xy[:,0],xy[:,1]))
                inside=(co[:,0]>=z.bounds.left)&(co[:,0]<z.bounds.right)&(co[:,1]>z.bounds.bottom)&(co[:,1]<=z.bounds.top)
                if inside.any():vals[inside]=np.ma.vstack(list(z.sample(co[inside],masked=True))).astype(float).filled(np.nan)[:,0]
            a={'orbit':int(row.orbit),'path':str(path.relative_to(root)),'url':url,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size,'status':'VERIFIED_CLOUD_ONLY'}
        except Exception as e:a={'orbit':int(row.orbit),'asset':name,'status':'FAILED','error_type':type(e).__name__}
        return a,vals
    byorbit={int(x):[] for x in population.orbit};assets=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for i,(a,v) in enumerate(pool.map(fetch,cat.itertuples(index=False))):
            assets.append(a);byorbit[a['orbit']].append(v)
            if (i+1)%20==0:print(json.dumps({'cloud_assets_finished':i+1,'total':len(cat)}),flush=True)
    rows=[];points=[]
    for p in population.itertuples(index=False):
        m=np.asarray(byorbit[p.orbit]);observed=((m==0)|(m==1)).any(axis=0);clear=observed&~(m==1).any(axis=0)
        rows.append({'orbit':int(p.orbit),'sample_points':len(xy),'observed_points':int(observed.sum()),'clear_points':int(clear.sum()),'observed_fraction':float(observed.mean()),'clear_fraction_all_points':float(clear.mean()),'failed_assets':sum(a['status']=='FAILED' for a in assets if a['orbit']==p.orbit)})
        points.extend({'orbit':int(p.orbit),'block':b,'observed':bool(o),'clear':bool(c)} for b,o,c in zip(ids,observed,clear))
    pd.DataFrame(rows).to_csv(out/'cloud_screen_summary.csv',index=False)
    pd.DataFrame(points).to_csv(out/'cloud_screen_points.csv',index=False)
    (out/'cloud_asset_manifest.json').write_text(json.dumps({'recorded_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'design':'selection_design.json','sampling':'Same frozen 300 Phoenix canopy-screen blocks; one point per block; overlap any-cloud veto. All 2023 endpoints and all geometry-supported multiyear endpoint strata, without outcome access.','limit':'Proxy only: missing observations are not cloudy; not native-cell joint-support certification.','assets':assets},indent=2)+'\n')
    print(json.dumps({'assets':len(assets),'failed':sum(a['status']=='FAILED' for a in assets),'screened_passes':len(rows)}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);main(p.parse_args().root)
