"""Assemble nonthermal Step6 evidence without reading any cooling outcomes."""
import argparse
import json
from pathlib import Path
import shutil

import eccodes as ec
import numpy as np
import pandas as pd
from .run_step6_inputs import ROOT,RUN,EXEC,PACKET,HOURLY,dest,sha,write,domains,check
from .step6_inputs import brackets,interpolate,rain_hours,accumulate_rain,solar_geometry,vpd_kpa


def prepare():
 cfg=json.loads((EXEC/"execution_freeze.json").read_text());check(cfg)
 passes=pd.DataFrame(cfg["passes"]);polys=domains();rows=[]
 hourly=[];validation=[]
 old=pd.read_csv(ROOT/HOURLY);old["t"]=pd.to_datetime(old.timestamp_utc,utc=True)
 for job in cfg["weather_jobs"]:
  key=pd.Timestamp(job["time"]).strftime("%Y%m%dT%HZ");p=dest(f"weather/{key}_summary.json")
  if not p.exists():continue
  record=json.loads(p.read_text())
  grid_hashes=[]
  for source in dest("cache/hrrr/marker").parent.glob(key+"_*.grib2"):
   h=ec.codes_new_from_message(source.read_bytes())
   try:
    grid_hashes.append(ec.codes_get(h,"md5Section3"))
    if ec.codes_get(h,"numberOfMissing") != 0:raise ValueError("Missing HRRR grid values require explicit treatment")
   finally:ec.codes_release(h)
  if len(grid_hashes)!=4 or len(set(grid_hashes))!=1:raise ValueError("HRRR fields do not share an identical grid")
  for r in record["rows"]:
   hourly.append(r);o=old[old.city.eq(r["city"]) & old.t.eq(pd.Timestamp(r["timestamp_utc"]))]
   if len(o)>1:raise ValueError("Duplicate historical weather hour")
   if not len(o):continue
   with np.load(dest(f"weather/{key}_{r['city']}_cells.npz")) as z:
    # The inherited xarray extracts rounded GRIB Kelvin values to float32.
    rounded=vpd_kpa(z["t2m"].astype("float32").astype("float64"),z["d2m"].astype("float32").astype("float64"))
   v=dict(city=r["city"],timestamp_utc=r["timestamp_utc"],domain_count_equal=int(r["n_domain_cells"])==int(o.iloc[0].n_domain_cells),
          temperature_difference_K=float(r["t2m_mean"]-o.iloc[0].t2m_k),
          dewpoint_difference_K=float(r["d2m_mean"]-o.iloc[0].d2m_k),
          VPD_difference_kPa=float(r["vpd_mean"]-o.iloc[0].vpd_kpa),
          VPD_difference_after_prior_decode_precision_kPa=float(rounded.mean()-o.iloc[0].vpd_kpa))
   if not v["domain_count_equal"] or abs(v["temperature_difference_K"])>1e-9 or abs(v["VPD_difference_after_prior_decode_precision_kPa"])>1e-10:
    raise ValueError("Historical weather reconstruction failed")
   validation.append(v)
 weather=pd.DataFrame(hourly);weather["t"]=pd.to_datetime(weather.timestamp_utc,utc=True)
 for r in passes.itertuples():
  d=weather[weather.city.eq(r.city)].set_index("t");fields=["t2m_mean","d2m_mean","vpd_mean","wind_speed_mean"]
  value=interpolate(r.acquisition_utc,d,fields);lo,hi,w=brackets(r.acquisition_utc)
  z,a=solar_geometry(polys[r.city].centroid.y,r.apparent_solar_hour,pd.Timestamp(r.acquisition_utc).dayofyear)
  rows.append(dict(city=r.city,orbit=r.orbit,date=r.local_date,acquisition_utc=r.acquisition_utc,
   apparent_solar_hour=r.apparent_solar_hour,time_arm=r.time_arm,window_weight=r.window_weight,
   hrrr_floor_utc=lo.isoformat(),hrrr_ceiling_utc=hi.isoformat(),hrrr_interpolation_weight=w,
   weather_status="COMPLETE_EXACT_TIME_HRRR" if value else "MISSING_HOURLY_BRACKETS",
   air_temperature_K=value["t2m_mean"] if value else None,dewpoint_K=value["d2m_mean"] if value else None,
   VPD_kPa=value["vpd_mean"] if value else None,wind_speed_m_s=value["wind_speed_mean"] if value else None,
   solar_zenith_centroid_deg=z,solar_azimuth_centroid_deg=a,solar_geometry_method="calculated harmonic declination at domain centroid, not observed per-cell geometry",
   view_zenith_p95_inherited_deg=r.view_zenith_p95_deg))
 pd.DataFrame(rows).to_csv(dest("acquisition_conditions.csv"),index=False)
 weather.drop(columns="t").to_csv(dest("hourly_weather.csv"),index=False)
 pd.DataFrame(validation).to_csv(dest("historical_weather_reconciliation.csv"),index=False)
 geometry=[]
 for g in cfg["geometry"]:
  record=dict(city=g["city"],orbit=g["orbit"],source=g["evidence"],source_sha256=sha(ROOT/g["evidence"]) if g["evidence"] else None,
              coverage_population="archived canonical city-domain target cells; not directly joined to modeled cells",
              modeled_cell_coverage_status="NOT_ESTABLISHED_BY_DOMAIN_SUMMARY")
  if not g["evidence"]:
   record["status"]="NO_CACHED_GEOMETRY_EVIDENCE";geometry.append(record);continue
  e=json.loads((ROOT/g["evidence"]).read_text());s=e["summary"]
  t=s.get("acquisition_utc",e.get("binding",{}).get("acquisition_utc"))
  target=passes[passes.city.eq(g["city"]) & passes.orbit.eq(g["orbit"])].iloc[0]
  delta=(pd.Timestamp(t)-pd.Timestamp(target.acquisition_utc)).total_seconds()
  record.update(geometry_acquisition_utc=t,geometry_time_offset_seconds=delta,
                identity_rule="same city/orbit; separate archived acquisition timestamp retained",
                old_eligibility_flags="historical only; no current pass removal")
  if g["artifact"]:
   with np.load(ROOT/g["artifact"],allow_pickle=False) as z:
    if str(z["city"])!=g["city"] or int(z["orbit"])!=g["orbit"]:raise ValueError("Geometry orbit mismatch")
    idx=z["valid_target_index"];view=z["view_zenith_abs_deg"];az=z["view_azimuth_deg"];solar=z["solar_azimuth_deg"]
    n=int(z["n_domain_pixels"])
    if len(set(idx))!=len(idx) or (idx<0).any() or (idx>=n).any():raise ValueError("Duplicate/outside geometry target identity")
    valid=np.isfinite(view);av=valid & np.isfinite(az) & np.isfinite(solar)
    record.update(evidence_level="cached arrays independently checked",n_domain_cells=n,n_view_valid=int(valid.sum()),
                  view_coverage_fraction=float(valid.sum()/n),view_p95_recalculated_deg=float(np.quantile(view[valid],.95)),
                  joint_view_solar_azimuth_cells=int(av.sum()),azimuth_fraction_of_view_cells=float(av.sum()/valid.sum()),
                  azimuth_status="COMPLETE" if av.sum()==valid.sum() else "INCOMPLETE",artifact_sha256=sha(ROOT/g["artifact"]))
  else:
   record.update(evidence_level="cached view-only source evidence; arrays not reconstructed",n_domain_cells=s["n_domain_pixels"],
                  n_view_valid=s["n_view_valid_pixels"],view_coverage_fraction=s.get("l1b_geometry_coverage_fraction",s.get("view_valid_fraction")),
                  view_p95_recalculated_deg=None,view_p95_archived_deg=s.get("l1b_view_zenith_abs_p95_deg",s.get("view_zenith_abs_p95_deg")),
                  joint_view_solar_azimuth_cells=None,azimuth_fraction_of_view_cells=None,azimuth_status="NOT_AVAILABLE_IN_VIEW_ONLY_EVIDENCE")
  geometry.append(record)
 pd.DataFrame(geometry).to_csv(dest("geometry_support.csv"),index=False)
 passes.to_csv(dest("comparison_schedule.csv"),index=False)
 passes["month"]=pd.to_datetime(passes.acquisition_utc,utc=True).dt.month
 counts=passes.groupby(["city","month","time_arm"]).size().rename("independent_acquisition_dates").reset_index()
 counts.to_csv(dest("month_time_coverage.csv"),index=False)
 # Deleting an only date invalidates the fixed target; no effect is computed.
 sensitivity=[]
 selected=passes[passes.window_weight.ne(0)]
 for dropped in selected.itertuples():
  remaining=selected[selected.orbit.ne(dropped.orbit)].copy();counts=remaining.groupby(["month","time_arm"]).size()
  required={(6,"morning"),(6,"afternoon"),(8,"morning"),(8,"afternoon")}
  missing=sorted(required-set(counts.index));weights={}
  if not missing:
   for k,grp in remaining.groupby(["month","time_arm"]):
    for row in grp.itertuples():weights[str(row.orbit)]=(.5 if k[1]=="afternoon" else -.5)/len(grp)
  sensitivity.append(dict(dropped_orbit=dropped.orbit,date=dropped.local_date,status="UNSUPPORTED_EMPTY_MONTH_ARM" if missing else "SUPPORTED_SCHEDULE_ONLY",missing_month_arms=missing,remaining_weights=weights))
 write(dest("leave_one_date_schedule.json"),sensitivity)
 write(dest("preparation_completion.json"),dict(weather_complete=sum(r["weather_status"]=="COMPLETE_EXACT_TIME_HRRR" for r in rows),
  historical_hourly_records_reconciled=len(validation),geometry_records=len(geometry),geometry_arrays_checked=sum(bool(g["artifact"]) for g in cfg["geometry"]),
  geometry_timestamp_mismatches=sum(g["geometry_time_offset_seconds"]!=0 for g in geometry),
  effect_files_opened=False,empirical_comparison_computed=False))
 print(json.dumps(json.loads(dest("preparation_completion.json").read_text())))


def finish_rain():
 cfg=json.loads((EXEC/"execution_freeze.json").read_text());check(cfg)
 completion=json.loads(dest("rain/retrieval_completion.json").read_text())
 if completion["failures"]:raise ValueError("Resolve/document source failures before rainfall finalization")
 grids={}
 for city in ("phoenix","atlanta"):
  with np.load(dest(f"rain/{city}_grid.npz")) as z:grids[city]=dict(weights=z["weights"],n=len(z["weights"]))
 dates={city:[] for city in grids};values={city:[] for city in grids};hours=[]
 for job in cfg["rain_jobs"]:
  t=pd.Timestamp(job["time"]);key=t.strftime("%Y%m%dT%HZ")
  meta=json.loads(dest(f"rain/{key}_summary.json").read_text());hours.extend(meta["rows"])
  with np.load(dest(f"rain/{key}_cells.npz")) as z:
   for city in job["cities"]:dates[city].append(t);values[city].append(z[city])
 arrays={c:np.asarray(v) for c,v in values.items()};records=[]
 for p in cfg["passes"]:
  t=pd.Timestamp(p["acquisition_utc"]);end=t.floor("h")
  for days in (1,3,7):
   record=accumulate_rain(arrays[p["city"]],dates[p["city"]],rain_hours(t,days),grids[p["city"]]["weights"])
   records.append(dict(city=p["city"],orbit=p["orbit"],acquisition_utc=p["acquisition_utc"],days=days,
    window_start_utc=(end-pd.Timedelta(days=days)).isoformat(),window_end_utc=end.isoformat(),
    acquisition_minus_window_end_seconds=(t-end).total_seconds(),n_domain_cells=grids[p["city"]]["n"],
    exact_acquisition_ended_total_mm=None,exact_window_status="NOT_IDENTIFIED_AT_SUBHOURLY_RESOLUTION",
    product="MRMS_MultiSensor_QPE_01H_Pass2",**record))
 pd.DataFrame(records).to_csv(dest("antecedent_rainfall.csv"),index=False)
 pd.DataFrame(hours).to_csv(dest("hourly_rainfall.csv"),index=False)
 conditions=pd.read_csv(dest("acquisition_conditions.csv"))
 for days in (1,3,7):
  q=pd.DataFrame(records);q=q[q.days.eq(days)][["city","orbit","total_mm","status"]].rename(columns={"total_mm":f"rainfall_{days}d_hour_ended_mm","status":f"rainfall_{days}d_status"})
  conditions=conditions.merge(q,on=["city","orbit"],validate="one_to_one")
 conditions.to_csv(dest("conditions_with_rainfall.csv"),index=False)
 PACKET.mkdir(parents=True,exist_ok=True)
 for p in dest("marker").parent.iterdir():
  if p.is_file() and p.suffix in (".csv",".json"):shutil.copy2(p,PACKET/p.name)
 result=dict(status="STEP6_INPUT_ASSEMBLY_COMPLETE_WITH_EXPLICIT_GEOMETRY_AND_HOURLY_RAIN_LIMITS",passes=16,
  exact_acquisition_weather_complete=16,rainfall_windows=len(records),complete_rainfall_windows=sum(r["total_mm"] is not None for r in records),
  missing_rainfall_windows=sum(r["total_mm"] is None for r in records),source_rainfall_hours=completion["completed"],
  exact_subhourly_rainfall_windows=0,empirical_time_effect_computed=False,new_effect_display=False,
  geometry_modeled_cell_coverage="not established by domain evidence",new_inclusion_cutoff=None,scale_ruling=None)
 write(dest("completion.json"),result);write(PACKET/"completion.json",result);print(json.dumps(result))


if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("action",choices=["prepare","rain"]);args=p.parse_args()
 # Preserve the post-processing source before computing summaries.
 record=EXEC/"assembly_code_freeze.json";current={"path":str(Path(__file__).relative_to(ROOT)),"sha256":sha(Path(__file__))}
 if record.exists() and json.loads(record.read_text())!=current:raise ValueError("Assembly source changed")
 if not record.exists():write(record,current);shutil.copy2(Path(__file__),EXEC/"archive/assemble_step6_inputs.py")
 if args.action=="prepare":prepare()
 else:finish_rain()
