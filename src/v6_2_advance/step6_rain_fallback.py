"""Whole-window Stage IV fallback; never fill one missing MRMS hour with it."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path

import eccodes as ec
import numpy as np
import pandas as pd
import shapely
from .run_step6_inputs import ROOT,EXEC,dest,write,sha,download,domains
from .step6_inputs import rain_hours,accumulate_rain


def get_field(t,indices=None):
 key=t.strftime("%Y%m%dT%HZ")
 url=f"https://mesonet.agron.iastate.edu/archive/data/{t:%Y/%m/%d}/stage4/ST4.{t:%Y%m%d%H}.01h.grib"
 path=dest(f"cache/stage4/{key}.grib");download(url,path)
 h=ec.codes_new_from_message(path.read_bytes())
 try:
  if ec.codes_get(h,"shortName")!="tp" or ec.codes_get(h,"units")!="kg m**-2" or ec.codes_get(h,"stepType")!="accum":raise ValueError("Stage IV quantity/unit mismatch")
  if ec.codes_get(h,"validityDate")!=int(t.strftime("%Y%m%d")) or ec.codes_get(h,"validityTime")!=t.hour*100 or ec.codes_get(h,"endStep")-ec.codes_get(h,"startStep")!=1:
   raise ValueError("Stage IV accumulation end/duration mismatch")
  if ec.codes_get(h,"gridType")!="polar_stereographic" or ec.codes_get(h,"LaDInDegrees")!=60 or ec.codes_get(h,"projectionCentreFlag")!=0:raise ValueError("Unexpected Stage IV projection")
  if ec.codes_get(h,"shapeOfTheEarth") not in (0,1,6,8):raise ValueError("Expected spherical polar stereographic Stage IV grid")
  grid_hash=ec.codes_get(h,"md5Section3")
  if indices is None:
   lat=ec.codes_get_array(h,"latitudes");lon=(ec.codes_get_array(h,"longitudes")+180)%360-180
   inside=shapely.covers(domains()["phoenix"],shapely.points(lon,lat));indices=np.flatnonzero(inside)
   # Inverse squared spherical polar-stereographic map scale, common factors cancel.
   weights=(1+np.sin(np.deg2rad(lat[indices])))**2
   return dict(indices=indices,latitude=lat[indices],longitude=lon[indices],weights=weights,grid_hash=grid_hash)
  a=np.asarray(ec.codes_get_elements(h,"values",indices.tolist()),float)
  a[(a<0)|(a==ec.codes_get(h,"missingValue"))|(~np.isfinite(a))]=np.nan
  return a,grid_hash
 finally:ec.codes_release(h)


def main():
 cfg=json.loads((EXEC/"execution_freeze.json").read_text());p=next(p for p in cfg["passes"] if p["city"]=="phoenix" and p["orbit"]==28706)
 times=rain_hours(p["acquisition_utc"],7)
 freeze=EXEC/"rainfall_fallback_freeze.json"
 record=dict(reason="MRMS hour 2023-07-24T15:00Z absent from IEM, NOAA AWS and NCSU GET/catalogue; Stage IV is the protocol fallback",
  failed_primary_hour="2023-07-24T15:00:00+00:00",city="phoenix",orbit=28706,days=7,
  policy="preserve missing MRMS total; independently sum all168 Stage IV hours for this entire window; no product blending",
  spatial_rule="fixed Stage IV cell centers covered by frozen Phoenix domain; spherical polar-stereographic inverse-map-scale-squared area weights",
  unit_rule="1 kg/m2 liquid precipitation equals 1 mm",windows=[t.isoformat() for t in times],
  missing_rule="all hours and all selected cells required for complete-domain total; otherwise retain gap",
  source="NOAA Stage IV via Iowa Environmental Mesonet archive",code_sha256=sha(Path(__file__)),effects_accessed=False)
 if freeze.exists() and json.loads(freeze.read_text())!=record:raise ValueError("Fallback settings changed")
 if not freeze.exists():write(freeze,record)
 grid=get_field(times[0]);np.savez_compressed(dest("stage4/phoenix_grid.npz"),**grid)
 def one(t):
  key=t.strftime("%Y%m%dT%HZ");p=dest(f"stage4/{key}_cells.npz")
  if p.exists():return
  a,h=get_field(t,grid["indices"])
  if h!=grid["grid_hash"]:raise ValueError("Stage IV grid changed")
  np.savez_compressed(p,values=a)
 errors=[];done=0
 with ThreadPoolExecutor(max_workers=4) as pool:
  futures={pool.submit(one,t):t for t in times}
  for f in as_completed(futures):
   try:f.result()
   except Exception as e:errors.append(dict(time=futures[f].isoformat(),type=type(e).__name__,message=str(e)[:300]))
   done+=1
   if done%25==0 or done==len(times):print(json.dumps(dict(stage="StageIV",completed=done,total=len(times),failures=len(errors))),flush=True)
 dates=[];values=[]
 for t in times:
  p=dest(f"stage4/{t:%Y%m%dT%HZ}_cells.npz")
  if p.exists():
   with np.load(p) as z:values.append(z["values"]);dates.append(t)
 q=accumulate_rain(np.asarray(values),dates,times,grid["weights"])
 result=dict(city="phoenix",orbit=28706,days=7,product="NOAA_Stage_IV",n_domain_cells=len(grid["weights"]),
  weights="inverse squared spherical polar-stereographic scale",download_failures=errors,**q)
 write(dest("stage4/fallback_result.json"),result);print(json.dumps(result))


if __name__=="__main__":main()
