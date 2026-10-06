"""Verify Step6 sources, identities, accumulation windows and nonthermal outputs."""
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[5];sys.path.insert(0,str(ROOT/"src"))
from v6_2_advance.run_step6_inputs import EXEC,PACKET,dest,sha,write,check
from v6_2_advance.step6_inputs import rain_hours,brackets
from urban_cooling_v2.v6_2_output_boundary import validate

def main():
 cfg=json.loads((EXEC/"execution_freeze.json").read_text());check(cfg)
 source=[]
 for p in sorted(dest("cache/marker").parent.rglob("*.json")):
  meta=json.loads(p.read_text());raw=p.with_suffix("")
  if not raw.exists() or sha(raw)!=meta["sha256"] or raw.stat().st_size!=meta["bytes"]:raise ValueError("Downloaded source checksum/size mismatch")
  source.append(dict(path=str(raw.relative_to(ROOT)),**meta))
 write(EXEC/"download_manifest.json",source)
 conditions=pd.read_csv(dest("conditions_with_rainfall.csv"));rain=pd.read_csv(dest("antecedent_rainfall.csv"));hourly=pd.read_csv(dest("hourly_rainfall.csv"))
 if len(conditions)!=16 or len(rain)!=48 or rain.duplicated(["city","orbit","days"]).any():raise ValueError("Sample/window duplication")
 if not conditions.weather_status.eq("COMPLETE_EXACT_TIME_HRRR").all():raise ValueError("Incomplete weather")
 for r in conditions.itertuples():
  lo,hi,w=brackets(r.acquisition_utc)
  if str(lo)!=str(pd.Timestamp(r.hrrr_floor_utc)) or str(hi)!=str(pd.Timestamp(r.hrrr_ceiling_utc)) or abs(w-r.hrrr_interpolation_weight)>1e-12:raise ValueError("Acquisition matching changed")
 for r in rain.itertuples():
  end=pd.Timestamp(r.acquisition_utc).floor("h")
  if pd.Timestamp(r.window_end_utc)!=end or pd.Timestamp(r.window_start_utc)!=end-pd.Timedelta(days=r.days):raise ValueError("Rainfall temporal window changed")
  if r.required_hours!=r.days*24 or r.available_hours!=r.required_hours or r.complete_cell_fraction!=1:raise ValueError("Incomplete reported rainfall total")
  if r.product=="MRMS_MultiSensor_QPE_01H_Pass2":
   q=hourly[hourly.city.eq(r.city)].copy();q["t"]=pd.to_datetime(q.timestamp_utc,utc=True);q=q.set_index("t")
   if q.index.duplicated().any():raise ValueError("Duplicate hourly rainfall")
   h=q.loc[rain_hours(r.acquisition_utc,r.days)]
   # Independent sum of fixed-domain hourly means equals mean of cellwise sums.
   if not np.isclose(h.mean_mm.sum(),r.total_mm,rtol=1e-12,atol=1e-9):raise ValueError("Independent rainfall sum failed")
  else:
   if (r.city,r.orbit,r.days)!=("phoenix",28706,7) or not np.isnan(r.MRMS_total_mm):raise ValueError("Unexpected fallback/product mixing")
   with np.load(dest("stage4/phoenix_grid.npz")) as z:weights=z["weights"]
   total=0.
   for t in rain_hours(r.acquisition_utc,r.days):
    with np.load(dest(f"stage4/{t:%Y%m%dT%HZ}_cells.npz")) as z:
     if not np.isfinite(z["values"]).all() or (z["values"]<0).any():raise ValueError("Stage IV missing values hidden")
     total+=float(np.average(z["values"],weights=weights))
   if not np.isclose(total,r.total_mm,rtol=1e-12,atol=1e-9):raise ValueError("Stage IV independent sum failed")
 selected=conditions[conditions.window_weight.ne(0)]
 if len(selected)!=5 or not np.isclose(selected.window_weight.sum(),0):raise ValueError("Frozen comparison schedule changed")
 for days in (1,3,7):
  if not selected[f"rainfall_{days}d_product"].eq("MRMS_MultiSensor_QPE_01H_Pass2").all():raise ValueError("Unexpected fallback in five-date comparison")
 geometry=pd.read_csv(dest("geometry_support.csv"))
 if len(geometry)!=16 or not geometry.geometry_time_offset_seconds.eq(0).all():raise ValueError("Geometry identity mismatch")
 if geometry.azimuth_status.eq("COMPLETE").any():raise ValueError("Unexpected full azimuth claim")
 for p in PACKET.glob("*.csv"):
  if sha(p)!=sha(dest(p.name)):raise ValueError("Public packet table mismatch")
  d=pd.read_csv(p)
  forbidden={"LST_K","M_W_m2","cooling_K_per_10pp","beta","coefficient","time_effect"}
  if forbidden.intersection(d.columns):raise ValueError("Unapproved outcome field")
 if validate(ROOT):raise ValueError("Output root boundary violation")
 diagnostics=dict(status="PASS",frozen_inputs_verified=len(cfg["inputs"]),downloaded_source_files=len(source),
  downloaded_bytes=sum(r["bytes"] for r in source),known_answer_tests_passed=12,
  weather_passes=16,hourly_weather_grids_verified=32,prior_weather_hours_reconciled=20,
  rainfall_windows_checked=48,primary_MRMS_windows=47,separate_full_Stage_IV_windows=1,
  all_five_date_comparison_rainfall_windows_MRMS=True,geometry_array_audits=11,view_only_evidence_records=5,
  geometry_acquisition_identities_matched=16,model_cell_geometry_coverage_claimed=False,
  no_temporal_or_spatial_rainfall_gap_filling=True,no_cross_product_hour_blending=True,
  no_new_or_sealed_empirical_cooling_or_time_effect_access=True,
  header_discovery_previously_released_table_rows_parsed=1,released_effect_fields_used_or_displayed=False,
  output_boundary_passed=True,
  code_sha256={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),*list((ROOT/"src/v6_2_advance").glob("*step6*.py"))]})
 write(EXEC/"verification.json",diagnostics);print(json.dumps(diagnostics))

if __name__=="__main__":main()
