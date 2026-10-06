from pathlib import Path
import requests,json,hashlib,re,concurrent.futures,rasterio
ROOT=Path(__file__).resolve().parents[2]
RAW=ROOT/'data/raw/ecostress_lst'; OUT=ROOT/'data/raw/v2/advance_v6_2_20260921/emissivity';OUT.mkdir(parents=True,exist_ok=True)
TOKEN=Path.home()/'.config/urban-tree-cooling/earthdata_token'
if not TOKEN.is_file(): raise SystemExit('EARTHDATA_TOKEN_MISSING')
token=TOKEN.read_text().strip()
orbits=set(json.loads((ROOT/'docs/v2/v6_2/execution/advance_20260921/advance_scope.json').read_text())['new_orbits'])
files=[p for p in RAW.glob('*_LST.tif') if int(p.name.split('_')[3]) in orbits]
def get(p):
 stem=p.name[:-8];name=stem+'_EmisWB.tif';dest=OUT/name
 url=f'https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/ECO_L2T_LSTE.002/{stem}/{name}'
 if not dest.exists():
  r=requests.get(url,headers={'Authorization':'Bearer '+token},timeout=120)
  if r.status_code!=200: return {'asset':name,'status':'DOWNLOAD_FAILED','http_status':r.status_code}
  tmp=dest.with_suffix('.partial');tmp.write_bytes(r.content)
  try:
   with rasterio.open(tmp) as d: assert d.count==1
  except Exception: tmp.unlink(missing_ok=True);return {'asset':name,'status':'NOT_A_VALID_RASTER'}
  tmp.replace(dest)
 with rasterio.open(p) as a,rasterio.open(dest) as b:
  match=(a.crs==b.crs and a.transform==b.transform and a.shape==b.shape)
  scales=b.scales;offsets=b.offsets
 return {'asset':name,'url':url,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'grid_matches_LST':match,'scale':scales,'offset':offsets,'status':'VERIFIED' if match else 'GRID_MISMATCH'}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
 rows=list(ex.map(get,files))
(OUT/'manifest.json').write_text(json.dumps({'collection':'002','orbits':sorted(orbits),'files':rows},indent=2))
print(json.dumps({'requested':len(rows),'verified':sum(r['status']=='VERIFIED' for r in rows),'failure_statuses':[r for r in rows if r['status']!='VERIFIED']}))
