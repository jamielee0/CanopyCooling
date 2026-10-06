"""Preserve incomplete primary windows and label independent full-window fallback."""
import json
from pathlib import Path
import shutil
import numpy as np
import pandas as pd
from .run_step6_inputs import EXEC,PACKET,dest,check,sha,write
from .step6_inputs import rain_hours,accumulate_rain


def main():
 cfg=json.loads((EXEC/"execution_freeze.json").read_text());check(cfg)
 ledger=json.loads(dest("rain/retrieval_completion.json").read_text())
 fallback=json.loads(dest("stage4/fallback_result.json").read_text())
 code=dict(path=str(Path(__file__)),sha256=sha(Path(__file__)),policy="retain primary missing total and report only prospectively frozen whole-window fallback separately")
 record=EXEC/"rainfall_assembly_corrected_freeze.json"
 if record.exists() and json.loads(record.read_text())!=code:raise ValueError("Rainfall assembler changed")
 if not record.exists():write(record,code)
 grids={};dates={};values={};hours=[];missing=[]
 for city in ("phoenix","atlanta"):
  with np.load(dest(f"rain/{city}_grid.npz")) as z:grids[city]=z["weights"]
  dates[city]=[];values[city]=[]
 for job in cfg["rain_jobs"]:
  t=pd.Timestamp(job["time"]);key=t.strftime("%Y%m%dT%HZ");p=dest(f"rain/{key}_summary.json")
  if not p.exists():missing.append(job);continue
  meta=json.loads(p.read_text());hours.extend(meta["rows"])
  with np.load(dest(f"rain/{key}_cells.npz")) as z:
   for city in job["cities"]:dates[city].append(t);values[city].append(z[city])
 arrays={c:np.asarray(a) for c,a in values.items()};records=[]
 for p in cfg["passes"]:
  t=pd.Timestamp(p["acquisition_utc"]);end=t.floor("h")
  for days in (1,3,7):
   primary=accumulate_rain(arrays[p["city"]],dates[p["city"]],rain_hours(t,days),grids[p["city"]])
   r=dict(city=p["city"],orbit=p["orbit"],acquisition_utc=p["acquisition_utc"],days=days,
    window_start_utc=(end-pd.Timedelta(days=days)).isoformat(),window_end_utc=end.isoformat(),acquisition_minus_window_end_seconds=(t-end).total_seconds(),
    n_domain_cells=len(grids[p["city"]]),exact_acquisition_ended_total_mm=None,exact_window_status="NOT_IDENTIFIED_AT_SUBHOURLY_RESOLUTION",
    product="MRMS_MultiSensor_QPE_01H_Pass2",MRMS_total_mm=primary["total_mm"],MRMS_status=primary["status"],
    Stage_IV_total_mm=None,Stage_IV_status="NOT_NEEDED",**primary)
   if primary["total_mm"] is None and (p["city"],p["orbit"],days)==(fallback["city"],fallback["orbit"],fallback["days"]):
    r.update(Stage_IV_total_mm=fallback["total_mm"],Stage_IV_status=fallback["status"])
    if fallback["total_mm"] is not None:
     r.update(total_mm=fallback["total_mm"],status="COMPLETE_STAGE_IV_WHOLE_WINDOW_FALLBACK",product="NOAA_Stage_IV",
              n_domain_cells=fallback["n_domain_cells"],complete_cell_fraction=fallback["complete_cell_fraction"],
              required_hours=fallback["required_hours"],available_hours=fallback["available_hours"])
   records.append(r)
 rain=pd.DataFrame(records);rain.to_csv(dest("antecedent_rainfall.csv"),index=False)
 pd.DataFrame(hours).to_csv(dest("hourly_rainfall.csv"),index=False)
 conditions=pd.read_csv(dest("acquisition_conditions.csv"))
 for days in (1,3,7):
  q=rain[rain.days.eq(days)][["city","orbit","total_mm","status","product"]].rename(columns={"total_mm":f"rainfall_{days}d_hour_ended_mm","status":f"rainfall_{days}d_status","product":f"rainfall_{days}d_product"})
  conditions=conditions.merge(q,on=["city","orbit"],validate="one_to_one")
 conditions.to_csv(dest("conditions_with_rainfall.csv"),index=False)
 write(dest("rainfall_source_gaps.json"),dict(missing_MRMS_hours=missing,primary_download_failures=ledger["failures"],whole_window_fallback=fallback,
  note="No fabricated primary total; no interpolation or single-hour cross-product replacement"))
 result=dict(status="STEP6_INPUT_ASSEMBLY_COMPLETE_WITH_EXPLICIT_GEOMETRY_AND_HOURLY_RAIN_LIMITS",passes=16,
  exact_acquisition_weather_complete=16,rainfall_windows=48,complete_rainfall_windows=int(rain.total_mm.notna().sum()),
  missing_rainfall_windows=int(rain.total_mm.isna().sum()),complete_primary_MRMS_windows=int(rain.MRMS_total_mm.notna().sum()),
  Stage_IV_fallback_windows=int(rain["product"].eq("NOAA_Stage_IV").sum()),MRMS_source_hours=ledger["completed"],
  MRMS_missing_hours=len(missing),Stage_IV_source_hours=fallback["available_hours"],
  exact_subhourly_rainfall_windows=0,empirical_time_effect_computed=False,new_effect_display=False,
  geometry_modeled_cell_coverage="not established by domain evidence",new_inclusion_cutoff=None,scale_ruling=None)
 write(dest("completion.json"),result)
 PACKET.mkdir(parents=True,exist_ok=True)
 for p in dest("marker").parent.iterdir():
  if p.is_file() and p.suffix in (".csv",".json"):shutil.copy2(p,PACKET/p.name)
 print(json.dumps(result))


if __name__=="__main__":main()
