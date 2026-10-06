from pathlib import Path
import requests,json,concurrent.futures,hashlib,time
from shapely.geometry import shape,Polygon,box
from shapely import make_valid
import pandas as pd
ROOT=Path(__file__).resolve().parents[2];OUT=(ROOT/'docs/v2/v6_2/execution')
domains={f['properties']['city']:make_valid(shape(f['geometry'])) for f in json.loads((OUT/'candidate_domains.geojson').read_text())['features']}
collections={'002':'C2076090826-LPCLOUD','003':'C3998139651-LPCLOUD'}
def one(pair):
 city,version=pair;target=OUT/f'catalogue_{city}_{version}.json'
 if target.exists(): return json.loads(target.read_text())['audit']
 geom=domains[city];session=requests.Session();headers={};rows=[];count=0;page=0;seen=set();started=None
 while True:
  p={'concept_id':collections[version],'bounding_box':','.join(str(x) for x in geom.bounds),'page_size':2000,'sort_key':'start_date'}
  r=session.get('https://cmr.earthdata.nasa.gov/search/granules.json',params=p,headers=headers,timeout=120);r.raise_for_status();items=r.json()['feed']['entry'];hits=int(r.headers['CMR-Hits']);page+=1;count+=len(items)
  for x in items:
   gid=x['producer_granule_id'];footprints=[]
   for parts in x.get('polygons',[]):
    for polygon in parts:
     nums=list(map(float,polygon.split()));footprints.append(make_valid(Polygon([(nums[i+1],nums[i]) for i in range(0,len(nums),2)])))
   for bounds in x.get('boxes',[]):
    south,west,north,east=map(float,bounds.split());footprints.append(box(west,south,east,north))
   if not footprints or not any(geom.intersects(f) for f in footprints): continue
   bits=gid.split('_');orbit=int(bits[3]);scene=int(bits[4]);tile=bits[5]
   rows.append({'city':city,'collection':version,'granule_id':gid,'orbit':orbit,'scene':scene,'tile':tile,'acquisition_utc':x['time_start'],'cloud_cover_metadata':x.get('cloud_cover'),'concept_id':x['id'],'links':[a['href'] for a in x.get('links',[]) if a.get('href','').startswith('https://') and a['href'].endswith('.tif')]})
  token=r.headers.get('CMR-Search-After')
  if count>=hits or not items:break
  if not token or token in seen:raise ValueError('Pagination did not advance')
  seen.add(token);headers['CMR-Search-After']=token
 if count!=hits:raise ValueError(f'CMR count mismatch {count} vs {hits}')
 data=pd.DataFrame(rows,columns=['city','collection','granule_id','orbit','scene','tile','acquisition_utc','cloud_cover_metadata','concept_id','links']);study=data[data.acquisition_utc.astype(str).str[:4].between('2019','2025')]
 audit={'city':city,'version':version,'query':'all_mission_dates_before_explicit_2019_2025_filter','pages':page,'bbox_CMR_hits':hits,'bbox_rows_received':count,'exact_intersection_rows':len(rows),'unique_granules':int(data.granule_id.nunique()),'study_granules':len(study),'study_unique_orbits':int(study.orbit.nunique()),'first_acquisition':data.acquisition_utc.min(),'last_acquisition':data.acquisition_utc.max(),'retrieved_utc':pd.Timestamp.now(tz='UTC').isoformat()}
 target.write_text(json.dumps({'audit':audit,'granules':rows},indent=2));print(json.dumps(audit),flush=True);return audit
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
 audits=list(ex.map(one,[(c,v) for c in domains for v in collections]))
(OUT/'catalogue_audit_summary.json').write_text(json.dumps(audits,indent=2))
