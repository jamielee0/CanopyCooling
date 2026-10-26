"""Bounded nonthermal weather retrieval and timing preparation for sixteen passes."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import time

import eccodes as ec
import numpy as np
import pandas as pd
from pyproj import Geod
import requests
import shapely

from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
from .step6_inputs import PASS_COLUMNS, assert_nonthermal_columns, brackets, rain_hours, grib_ranges, vpd_kpa, window_plan

ROOT=Path(__file__).resolve().parents[2]
RUN="step6_inputs_20261005"
EXEC=ROOT/"docs/v2/v6_2/execution"/RUN
PACKET=ROOT/"deliverables/Step6_Conditions_2023_v6_2_20261005"
TABLE="deliverables/Results_Review_2023_v6_2_20261004/pass_results_long.csv"
HOURLY="data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo_D0047_archive_available/hrrr_hourly_domain_summary.csv"
GEODOM="data/raw/v2/domains/census_urban_areas.geojson"
CODE=["src/v6_2_advance/step6_inputs.py","src/v6_2_advance/run_step6_inputs.py","tests/v6_2_advance/test_step6_inputs.py"]
ACTIVE=["AGENTS.md",*["docs/v2/v6_2/"+p for p in ("protocol_v6_2.yml","pilot_plan_v6_2.md","decision_log_v6_2.md","prior_thermal_access.md","results_review_and_targeted_analysis_plan_20260930.md")]]
FIELDS={"t2m":("TMP","2 m above ground"),"d2m":("DPT","2 m above ground"),"u10":("UGRD","10 m above ground"),"v10":("VGRD","10 m above ground")}


def sha(path):
 with Path(path).open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()


def dest(name):
 p=guarded_output_path(ROOT,"scientific",f"{RUN}/{name}");p.parent.mkdir(parents=True,exist_ok=True);return p


def write(p,record):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(record,indent=2,allow_nan=False)+"\n")


def freeze():
 if (EXEC/"execution_freeze.json").exists():raise ValueError("Preserve Step6 freeze")
 assert_nonthermal_columns(PASS_COLUMNS)
 passes=pd.read_csv(ROOT/TABLE,usecols=list(PASS_COLUMNS));passes=passes[passes.variant.eq("original")].copy()
 if len(passes)!=16 or not pd.to_datetime(passes.acquisition_utc,utc=True).dt.year.eq(2023).all():raise ValueError("Pilot changed")
 passes=window_plan(passes)
 prior=json.loads((ROOT/"docs/v2/v6_2/execution/quadratic_step5_20261005/execution_freeze.json").read_text())
 if str((ROOT/"data").resolve(strict=True))!=prior["data_link_target"]:raise ValueError("Data target changed")
 sources={TABLE,HOURLY,GEODOM,*CODE}
 geometry=[]
 for r in passes.itertuples():
  candidates=[f"data/raw/v2/hitl/g3_sampling_design_revision2/geometry_azimuth_pass_evidence/{r.city}/{r.orbit}.json",
              f"data/raw/v2/v6_2/d1a_geometry_recovery/pass_evidence/{r.city}/{r.orbit}.json",
              f"data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available/pass_evidence/{r.city}/{r.orbit}.json"]
  source=next((p for p in candidates if (ROOT/p).exists()),None)
  record=dict(city=r.city,orbit=r.orbit,evidence=source,artifact=None)
  if source:
   sources.add(source); e=json.loads((ROOT/source).read_text()); a=e.get("reconstruction_artifact",{})
   if a.get("path"):
    rel="data/"+a["path"].split("/data/",1)[1]
    if not (ROOT/rel).is_file() or sha(ROOT/rel)!=a["sha256"]:raise ValueError("Geometry artifact identity failed")
    record["artifact"]=rel;sources.add(rel)
  geometry.append(record)
 weather={};rain={}
 for r in passes.itertuples():
  for t in set(brackets(r.acquisition_utc)[:2]):weather.setdefault(t.isoformat(),set()).add(r.city)
  for t in rain_hours(r.acquisition_utc,7):rain.setdefault(t.isoformat(),set()).add(r.city)
 inputs=[dict(path=p,sha256=sha(ROOT/p)) for p in sorted(sources)]
 record=dict(created_utc=datetime.now(timezone.utc).isoformat(),record_date_local="2026-10-05",
  authority=dict(request="then proceed with step 6",scope="nonthermal acquisition-linked weather/rainfall, geometry and comparison schedule; no empirical cooling/time inference",new_effect_display=False),
  data_link_target=prior["data_link_target"],passes=passes.to_dict("records"),geometry=geometry,inputs=inputs,
  settings=dict(hrrr="NOAA operational f00, AWS archive; sfc with prs fallback only if absent; TMP/DPT2m and U/V10m",
   weather_timing="linear interpolation of cell-derived hourly frozen-domain summaries to exact acquisition including subseconds",
   weather_spatial="grid-cell centers covered by make_valid frozen Census Urban Area; equal-cell means, as inherited HRRR archive",
   vpd="cellwise FAO 0.6108/17.27/237.3, clip below zero, then domain mean; descriptive only",
   rainfall_product="MRMS_MultiSensor_QPE_01H_Pass2",rainfall_grib_parameter=[209,6,37],rainfall_units="mm",
   rainfall_archive="Iowa State IEM mirror of NOAA operational MRMS",rainfall_windows_days=[1,3,7],
   rainfall_timing="24/72/168 nonoverlapping complete hours ending floor(acquisition UTC); report subhour lag, never include future rain or interpolate accumulation",
   rainfall_spatial="MRMS 0.01deg cell centers in frozen Census polygons, WGS84 geodesic cell-area weights; same cells every hour",
   rainfall_missing="negative flags/bitmap missing are missing, never zero; incomplete hourly or spatial windows have no complete-domain total",
   rainfall_fallback="NOAA Stage IV only after logged MRMS archive failure; never silently blend product values",
   rainfall_exact_instant_total="not identified by hourly product; hour-ended totals are explicit descriptors",
   geometry="verify cached nonthermal evidence/arrays for same orbit; separate full-domain coverage from modeled-cell coverage, no imputation",
   time_model="no model fitted; inherited Phoenix June/August weights and two solar windows retained",
   weights=WEIGHTS_JSON(),Atlanta="independent month/time inventory, no copied Phoenix weights",
   sealed_models_opened=False,raw_thermal_opened=False,scale_ruling=None,new_inclusion_cutoff=None),
  weather_jobs=[dict(time=t,cities=sorted(c)) for t,c in sorted(weather.items())],
  rain_jobs=[dict(time=t,cities=sorted(c)) for t,c in sorted(rain.items())],
  code_sha256={p:sha(ROOT/p) for p in CODE},
  authoritative_sources=["https://www.nssl.noaa.gov/projects/mrms/operational/tables.php","https://registry.opendata.aws/noaa-hrrr-pds/","https://mtarchive.geol.iastate.edu/"])
 archive=ROOT/"docs/v2/v6_2/archive/before_step6_inputs_20261005";snap=[]
 for rel in ACTIVE:
  p=archive/rel;p.parent.mkdir(parents=True,exist_ok=True)
  if p.exists():raise ValueError("Archive already exists")
  shutil.copy2(ROOT/rel,p);snap.append(dict(path=rel,sha256=sha(p)))
 write(archive/"snapshot.json",dict(files=snap))
 write(EXEC/"execution_freeze.json",record)
 write(EXEC/"scope.json",record["authority"])
 for rel in CODE:
  p=EXEC/"archive"/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,p)
 print(json.dumps(dict(stage="frozen",passes=16,weather_hours=len(weather),rain_hours=len(rain))))


def WEIGHTS_JSON():
 from .step6_inputs import WEIGHTS
 return {str(k):v for k,v in WEIGHTS.items()}


def check(cfg):
 if str((ROOT/"data").resolve(strict=True))!=cfg["data_link_target"]:raise ValueError("Data target changed")
 revision=EXEC/"implementation_repair.json"
 approved=json.loads(revision.read_text()) if revision.exists() else {}
 if approved and (approved["science_settings_changed"] or approved["freeze_sha256"]!=sha(EXEC/"execution_freeze.json")):
  raise ValueError("Invalid implementation-only repair record")
 for p,h in cfg["code_sha256"].items():
  expected=approved.get("updated_code_sha256",{}).get(p,h)
  if sha(ROOT/p)!=expected:raise ValueError("Frozen source changed")
 for r in cfg["inputs"]:
  expected=approved.get("updated_code_sha256",{}).get(r["path"],r["sha256"])
  if sha(ROOT/r["path"])!=expected:raise ValueError("Frozen input changed")


def download(url,path,byte_range=None):
 sidecar=path.with_suffix(path.suffix+".json")
 if path.exists() and sidecar.exists():
  meta=json.loads(sidecar.read_text())
  if meta["url"]!=url or sha(path)!=meta["sha256"]:raise ValueError("Cached download identity failed")
  return meta
 headers={"Range":f"bytes={byte_range[0]}-{byte_range[1]}"} if byte_range else {}
 last=None
 for attempt in range(3):
  try:
   response=requests.get(url,headers=headers,timeout=(15,60));response.raise_for_status()
   if byte_range and (response.status_code!=206 or len(response.content)!=byte_range[1]-byte_range[0]+1):raise ValueError("Server ignored requested GRIB byte range")
   path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(response.content)
   meta=dict(url=url,status=response.status_code,bytes=len(response.content),sha256=sha(path),
    retrieved_utc=datetime.now(timezone.utc).isoformat(),etag=response.headers.get("ETag"),last_modified=response.headers.get("Last-Modified"),byte_range=byte_range)
   write(sidecar,meta);return meta
  except requests.RequestException as error:
   last=error
   if getattr(error.response,"status_code",None)==404:break
   time.sleep(attempt+1)
 raise last


def domains():
 d=json.loads((ROOT/GEODOM).read_text())
 return {f["properties"]["city"]:shapely.make_valid(shapely.geometry.shape(f["geometry"])) for f in d["features"] if f["properties"]["city"] in ("phoenix","atlanta")}


def weather_job(job,polygons):
 t=pd.Timestamp(job["time"]);key=t.strftime("%Y%m%dT%HZ");out=dest(f"weather/{key}_summary.json")
 if out.exists():return json.loads(out.read_text())
 cache=dest(f"cache/hrrr/{key}.idx")
 for product in ("sfc","prs"):
  base=f"https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.{t:%Y%m%d}/conus/hrrr.t{t:%H}z.wrf{product}f00.grib2"
  try:
   ip=cache.with_name(key+f"_{product}.idx");download(base+".idx",ip);ranges=grib_ranges(ip.read_text(),FIELDS);break
  except requests.HTTPError as error:
   if error.response.status_code!=404:raise
 else:raise ValueError("No official HRRR analysis object")
 arrays={};lat=lon=None;metas=[]
 for name,span in ranges.items():
  p=dest(f"cache/hrrr/{key}_{product}_{name}.grib2");metas.append(download(base,p,span))
  h=ec.codes_new_from_message(p.read_bytes())
  try:
   expected_name={"t2m":"2t","d2m":"2d","u10":"10u","v10":"10v"}[name]
   if ec.codes_get(h,"shortName")!=expected_name or ec.codes_get(h,"forecastTime")!=0:raise ValueError("HRRR variable/forecast mismatch")
   if int(ec.codes_get(h,"validityDate"))!=int(t.strftime("%Y%m%d")) or int(ec.codes_get(h,"validityTime"))!=t.hour*100:raise ValueError("HRRR validity mismatch")
   unit=ec.codes_get(h,"units")
   if unit != ("K" if name in ("t2m","d2m") else "m s**-1"):raise ValueError("HRRR units mismatch")
   arrays[name]=ec.codes_get_values(h)
   if lat is None:
    lat=ec.codes_get_array(h,"latitudes");lon=(ec.codes_get_array(h,"longitudes")+180)%360-180
   if len(arrays[name])!=len(lat) or not np.isfinite(arrays[name]).all():raise ValueError("HRRR incomplete grid")
  finally:ec.codes_release(h)
 rows=[];points=shapely.points(lon,lat)
 for city in job["cities"]:
  mask=shapely.covers(polygons[city],points);idx=np.flatnonzero(mask)
  if not len(idx):raise ValueError("Empty weather domain")
  v={k:a[idx] for k,a in arrays.items()};v["vpd"]=vpd_kpa(v["t2m"],v["d2m"]);v["wind_speed"]=np.hypot(v["u10"],v["v10"])
  np.savez_compressed(dest(f"weather/{key}_{city}_cells.npz"),indices=idx,latitude=lat[idx],longitude=lon[idx],**v)
  rows.append(dict(city=city,timestamp_utc=t.isoformat(),n_domain_cells=len(idx),product=product,
    **{k+"_mean":float(a.mean()) for k,a in v.items()},source="NOAA_HRRR_f00_AWS"))
 record=dict(time=t.isoformat(),rows=rows,downloads=metas);write(out,record);return record


def rain_grids(polygons):
 geod=Geod(ellps="WGS84");result={}
 for city,poly in polygons.items():
  xmin,ymin,xmax,ymax=poly.bounds
  ii=np.arange(max(0,int((xmin+129.995)/.01)-1),min(7000,int((xmax+129.995)/.01)+2))
  jj=np.arange(max(0,int((54.995-ymax)/.01)-1),min(3500,int((54.995-ymin)/.01)+2))
  i,j=np.meshgrid(ii,jj);x=-129.995+i*.01;y=54.995-j*.01;inside=shapely.covers(poly,shapely.points(x,y))
  idx=(j[inside]*7000+i[inside]).astype(np.int64);lat=y[inside];lon=x[inside]
  areas={v:abs(geod.polygon_area_perimeter([0,.01,.01,0],[v-.005,v-.005,v+.005,v+.005])[0]) for v in np.unique(lat)}
  weights=np.array([areas[v] for v in lat]);result[city]=dict(indices=idx,latitude=lat,longitude=lon,weights=weights)
  p=dest(f"rain/{city}_grid.npz")
  if not p.exists():np.savez_compressed(p,**result[city])
 return result


def rain_job(job,grids):
 t=pd.Timestamp(job["time"]);key=t.strftime("%Y%m%dT%HZ");out=dest(f"rain/{key}_summary.json")
 if out.exists():return json.loads(out.read_text())
 url=f"https://mtarchive.geol.iastate.edu/{t:%Y/%m/%d}/mrms/ncep/MultiSensor_QPE_01H_Pass2/MultiSensor_QPE_01H_Pass2_00.00_{t:%Y%m%d-%H}0000.grib2.gz"
 p=dest(f"cache/mrms/{key}.grib2.gz");meta=download(url,p)
 h=ec.codes_new_from_message(gzip.decompress(p.read_bytes()))
 try:
  for k,v in {"discipline":209,"parameterCategory":6,"parameterNumber":37,"Ni":7000,"Nj":3500,"jScansPositively":0,"iScansNegatively":0}.items():
   if ec.codes_get(h,k)!=v:raise ValueError("MRMS parameter/grid identity mismatch")
  for k,v in {"latitudeOfFirstGridPointInDegrees":54.995,"longitudeOfFirstGridPointInDegrees":230.005,"iDirectionIncrementInDegrees":.01,"jDirectionIncrementInDegrees":.01}.items():
   if not np.isclose(ec.codes_get(h,k),v,atol=1e-8,rtol=0):raise ValueError("MRMS coordinates changed")
  if ec.codes_get(h,"dataDate")!=int(t.strftime("%Y%m%d")) or ec.codes_get(h,"dataTime")!=t.hour*100:raise ValueError("MRMS accumulation label mismatch")
  rows=[];payload={}
  for city in job["cities"]:
   grid=grids[city];a=np.asarray(ec.codes_get_elements(h,"values",grid["indices"].tolist()),float)
   valid=np.isfinite(a)&(a>=0)&(a!=ec.codes_get(h,"missingValue"));a[~valid]=np.nan
   payload[city]=a
   rows.append(dict(city=city,timestamp_utc=t.isoformat(),n_domain_cells=len(a),valid_cells=int(valid.sum()),
                    complete_domain=bool(valid.all()),mean_mm=float(np.average(a,weights=grid["weights"])) if valid.all() else None,
                    missing_cells=int((~valid).sum())))
 finally:ec.codes_release(h)
 np.savez_compressed(dest(f"rain/{key}_cells.npz"),**payload)
 record=dict(time=t.isoformat(),rows=rows,download=meta);write(out,record);return record


def retrieve(kind):
 cfg=json.loads((EXEC/"execution_freeze.json").read_text());check(cfg)
 polys=domains();jobs=cfg[kind+"_jobs"];grids=rain_grids(polys) if kind=="rain" else polys
 function=rain_job if kind=="rain" else weather_job
 errors=[];count=0
 with ThreadPoolExecutor(max_workers=4 if kind=="rain" else 2) as pool:
  future={pool.submit(function,job,grids):job for job in jobs}
  for f in as_completed(future):
   job=future[f]
   try:f.result()
   except Exception as e:
    errors.append(dict(job=job,error_type=type(e).__name__,message=str(e)[:500]))
    write(dest(kind+"/failures.json"),errors)
   count+=1
   if count%25==0 or count==len(jobs):print(json.dumps(dict(stage=kind,completed=count,total=len(jobs),failures=len(errors))),flush=True)
 write(dest(kind+"/retrieval_completion.json"),dict(requested=len(jobs),completed=count-len(errors),failures=errors))


if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("action",choices=["freeze","weather","rain"]);args=p.parse_args()
 if args.action=="freeze":freeze()
 else:retrieve(args.action)
