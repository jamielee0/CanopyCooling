"""Acquire exact matched C2 bundles after the nonthermal batch freeze."""
from pathlib import Path
import json,sys,hashlib,concurrent.futures
import requests,rasterio,pandas as pd
from sampling_design import revision_dedup
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/v2/v6_2/execution/rebalance_20260921'
c=json.loads((OUT/'phoenix_execution_manifest.json').read_text());freeze=json.loads((OUT/'thermal_batch_selection_freeze.json').read_text());assert c['orbits']==freeze['selected_new_orbits']
raw=Path(c['thermal_root']);em=Path(c['emissivity_root']);raw.mkdir(parents=True,exist_ok=True);em.mkdir(parents=True,exist_ok=True)
cat=revision_dedup(json.loads((ROOT/'docs/v2/v6_2/execution/catalogue_phoenix_002.json').read_text())['granules']);cat=cat[cat.orbit.isin(c['orbits'])]
token=(Path.home()/'.config/urban-tree-cooling/earthdata_token').read_text().strip()
jobs=[(r.granule_id,int(r.orbit),band) for r in cat.itertuples(index=False) for band in ['LST','QC','cloud','water','EmisWB']]
def fetch(job):
    gid,orbit,band=job;name=gid+'_'+band+'.tif';path=(em if band=='EmisWB' else raw)/name
    url=f'https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/ECO_L2T_LSTE.002/{gid}/{name}'
    for attempt in range(3):
        try:
            if not path.exists():
                cached=ROOT/'data/raw/v2/rebalance_v6_2_20260921/cloud'/name
                if band=='cloud' and cached.exists():path.write_bytes(cached.read_bytes())
                else:
                    r=requests.get(url,headers={'Authorization':'Bearer '+token},timeout=120);r.raise_for_status();tmp=path.with_suffix('.partial');tmp.write_bytes(r.content)
                    with rasterio.open(tmp) as z:assert z.count==1
                    tmp.replace(path)
            with rasterio.open(path) as z:assert z.count==1
            return {'orbit':orbit,'granule_id':gid,'band':band,'path':str(path.relative_to(ROOT)),'url':url,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'status':'VERIFIED'}
        except Exception as e:
            if attempt==2:return {'orbit':orbit,'granule_id':gid,'band':band,'status':'FAILED','error_type':type(e).__name__}
rows=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    for i,a in enumerate(ex.map(fetch,jobs)):
        rows.append(a)
        if (i+1)%20==0:print(json.dumps({'assets_finished':i+1,'total':len(jobs)}),flush=True)
fail=[r for r in rows if r['status']!='VERIFIED']
if not fail:
    for gid,g in pd.DataFrame(rows).groupby('granule_id'):
        expected=None
        for r in g.itertuples(index=False):
            with rasterio.open(ROOT/r.path) as z:
                grid=(z.crs,z.shape,z.transform)
                if expected is not None:assert grid==expected,(gid,r.band,'GRID_MISMATCH')
                expected=grid
(em/'manifest.json').write_text(json.dumps({'collection':'002','orbits':c['orbits'],'files':rows,'selection_freeze_sha256':hashlib.sha256((OUT/'thermal_batch_selection_freeze.json').read_bytes()).hexdigest()},indent=2)+'\n')
print(json.dumps({'assets':len(rows),'failures':fail,'bytes':sum(r.get('bytes',0) for r in rows)}),flush=True)
if fail:raise SystemExit('Input acquisition incomplete')
