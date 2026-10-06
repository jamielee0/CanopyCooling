"""Frozen predictor-only Step5 audit of all sixteen 2023 native-cell samples."""
import argparse
import gc
import json
from datetime import datetime,timezone
from pathlib import Path

import numpy as np
import pandas as pd

from urban_cooling_v2.pooled_city_pass import CONTEXT
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
from v6_2_advance.results_packet import sha256,solar_times,timestamp
from v6_2_advance.spatial_review import validate_native_rows
from v6_2_advance.canopy_support import (
 READ_COLUMNS,assert_predictor_columns,endpoint_support,distribution,protected_design,
 resampled_design_rank,weighted_scaling,cross_distances,
)

ROOT=Path(__file__).resolve().parents[2]
RUN="canopy_support_step5_20261004"
EXEC=ROOT/"docs/v2/v6_2/execution"/RUN
OUT=ROOT/"deliverables/Step5_Canopy_Support_2023_v6_2_20261004"
SUPPORT="docs/v2/v6_2/execution/nonlinear_association_20260930/numeric_support_freeze.json"
REFERENCES="outputs/v6_2/scientific/scale_diagnostics_20260919/frozen_numeric_references.json"
CODE=("src/v6_2_advance/canopy_support.py","src/v6_2_advance/run_canopy_support.py",
      "src/v6_2_advance/plot_canopy_support.py","tests/v6_2_advance/test_canopy_support.py",
      "src/urban_cooling_v2/pooled_city_pass.py","src/urban_cooling_v2/v6_2_output_boundary.py",
      "src/v6_2_advance/spatial_review.py","src/v6_2_advance/results_packet.py")


def public(name):
 p=guarded_output_path(ROOT,"scientific",f"{RUN}/{name}");p.parent.mkdir(parents=True,exist_ok=True);return p


def write(name,value):public(name).write_text(json.dumps(value,indent=2,allow_nan=False)+"\n")


def freeze():
 dest=EXEC/"execution_freeze.json"
 if dest.exists():raise ValueError("Preserve existing audit freeze")
 old=json.loads((ROOT/SUPPORT).read_text())
 ref=json.loads((ROOT/REFERENCES).read_text())
 sources=[SUPPORT,REFERENCES,"docs/v2/v6_2/execution/results_review_20261004/scope.json",
          "docs/v2/v6_2/execution/results_packet_20261004/execution_freeze.json",
          "docs/v2/v6_2/execution/phoenix_execution_manifest.json","docs/v2/v6_2/execution/atlanta_execution_manifest.json",
          "docs/v2/v6_2/execution/advance_20260921/phoenix_execution_manifest.json",
          "deliverables/Spatial_Scale_Review_2023_v6_2_20261004/footprint_and_reference_support.csv"]
 inputs=[dict(path=p,sha256=sha256(ROOT/p),role="public_metadata") for p in sources]
 for spec in old["passes"]:
  h=sha256(ROOT/spec["path"])
  if h!=spec["sha256"]:raise ValueError("Native frame changed since prior support freeze")
  inputs.append(dict(path=spec["path"],sha256=h,role="cached_frame_predictor_columns_only"))
  print(json.dumps(dict(stage="predictor_input_verified",city=spec["city"],orbit=spec["orbit"])),flush=True)
 f0=ref["f0"]
 candidates=[dict(pair_id="historical" if delta==0 else f"near_{delta:+.2f}",f0=f0+delta,f1=f0+delta+.1) for delta in (-.02,-.01,0,.01,.02)]
 candidates += [dict(pair_id=f"grid_{k:02d}",f0=k/10,f1=(k+1)/10) for k in range(10)]
 record=dict(created_utc=datetime.now(timezone.utc).isoformat(),record_date_local="2026-10-04",
  authority=dict(request="go to the next step 5",authorized_now="predictor support/design audit",quadratic_fit_scope="clarification pending; not executed by this audit",new_effect_display=False),
  status="FROZEN_BEFORE_PREDICTOR_AUDIT",sample=dict(year=2023,Phoenix_passes=11,Atlanta_passes=5,other_year_weight=0),
  data_link_target=str((ROOT/"data").resolve(strict=True)),passes=old["passes"],inputs=inputs,
  allowed_frame_columns=list(READ_COLUMNS),outcome_columns_read=False,model_or_bootstrap_effect_files_read=False,
  settings=dict(candidate_pairs=candidates,halfwidths_fraction=[.01,.025,.05],band_rule="closed endpoints clipped to [0,1]; report clipped width and any shared cells",
   pair_selection="report every prospectively listed pair; do not optimize against effects or nominate a city-ranking contrast",
   neighbourhood_counts="all original cells; additionally report counts in blocks spanning exact endpoints; neighbourhood counts do not prove exact endpoint support",
   covariate_profiles="historical pair at all three widths, each endpoint and each of six controls; exact full-band quantiles",
   predictor_sample_seed=20261004,query_sample_max_cells_per_pass_band=2000,cross_city_reference_max_unique_cells=5000,
   joint_context_distance="standardized 6D Euclidean nearest-neighbour distance to other-city equal-size unique-footprint reference pools; no acceptance cutoff or CI",
   scaling="full-predictor samples, equal city/equal pass/equal sampled cell; zero-SD dimensions excluded from distance only and recorded",
   display="support counts and distances only; cross-city proximity is a descriptive diagnostic, not proof of causal positivity or city comparability",
   mean_design="raw canopy f and raw f squared before separate within-block centering; both protected",
   context_rank_rule="existing context-only scaled QR selection before protected basis rank check; never drop a protected canopy term or retained confounder to rescue a design",
   design_rank_tolerance=1e-10,zero_norm_tolerance=1e-12,design_resampling_groups_km=[1,8],design_resampling_replicates=1000,
   design_seed_rule="20261004 + 100000 + integer orbit; same multiplicities for linear/quadratic designs",
   outcome_model_fits=0,cell_or_pass_inclusion_change=False,support_threshold=None,scale_tolerance=None),
  code_sha256={p:sha256(ROOT/p) for p in CODE})
 dest.write_text(json.dumps(record,indent=2)+"\n")
 print(json.dumps(dict(stage="freeze_complete",inputs=len(inputs),candidate_pairs=len(candidates),outcome_access=False)),flush=True)


class PredictorReader:
 def __init__(self,record):
  self.record=record;self.hashes={r["path"]:r["sha256"] for r in record["inputs"]};self.checked=set();self.access=[]
  if str((ROOT/"data").resolve(strict=True))!=record["data_link_target"]:raise ValueError("Data-link target changed")
 def path(self,p):
  if p not in self.hashes:raise ValueError("Source outside predictor-audit allowlist")
  if p not in self.checked:
   if sha256(ROOT/p)!=self.hashes[p]:raise ValueError("Frozen audit source changed")
   self.checked.add(p)
  return ROOT/p
 def frame(self,p,columns=READ_COLUMNS):
  assert_predictor_columns(columns)
  self.access.append(dict(path=p,columns=list(columns),outcome_columns_read=False))
  return pd.read_parquet(self.path(p),columns=list(columns))
 def metadata(self,p):
  path=self.path(p)
  if path.suffix!=".json":raise ValueError("Metadata JSON required")
  return json.loads(path.read_text())


def run():
 from v6_2_advance.plot_canopy_support import plot_support
 record=json.loads((EXEC/"execution_freeze.json").read_text());reader=PredictorReader(record);settings=record["settings"]
 for p,h in record["code_sha256"].items():
  if sha256(ROOT/p)!=h:raise ValueError("Frozen code changed")
 city_meta=reader.metadata("docs/v2/v6_2/execution/results_packet_20261004/execution_freeze.json")["cities"]
 manifests={"pooled_pilot_20260919_phoenix":reader.metadata("docs/v2/v6_2/execution/phoenix_execution_manifest.json"),
  "pooled_pilot_20260919_atlanta":reader.metadata("docs/v2/v6_2/execution/atlanta_execution_manifest.json"),
  "pooled_extension_20260921_phoenix":reader.metadata("docs/v2/v6_2/execution/advance_20260921/phoenix_execution_manifest.json")}
 previous=pd.read_csv(reader.path("deliverables/Spatial_Scale_Review_2023_v6_2_20261004/footprint_and_reference_support.csv"),dtype={"orbit":str})
 endpoint_rows=[];covariate_rows=[];design_rows=[];resampling_rows=[];bare_rows=[];span_rows=[]
 full_samples=[];band_samples=[];failures=[];physical_checks=[]
 for spec in record["passes"]:
  city,orbit=spec["city"],str(spec["orbit"]);d=reader.frame(spec["path"]);validate_native_rows(d)
  if len(d)!=spec["n_cells"] or d.block.nunique()!=spec["n_blocks"]:raise ValueError("Original sample identity/count changed")
  meta=manifests[spec["run_id"]]["pass_metadata"][orbit]
  time=timestamp(meta["acquisition_utc"]);_,hour,_=solar_times(time,city_meta[city]["longitude_deg"])
  identity=dict(city=city,orbit=orbit,date=spec["date"],month=int(spec["date"][5:7]),apparent_solar_hour=hour,source_run_id=spec["run_id"])
  if not spec["date"].startswith("2023-"):raise ValueError("Outside 2023 pilot")
  physical_checks.append(dict(**identity,n_cells=len(d),unique_cell_ids=True,unique_native_footprints=True,physical_block_labels=True))
  bounds=d.groupby("block").canopy_fraction.agg(["min","max"])
  span_rows.append(dict(**identity,**distribution((bounds["max"]-bounds["min"]).to_numpy())))
  rng=np.random.default_rng(20261004+int(orbit))
  full_ix=rng.choice(len(d),min(2000,len(d)),replace=False)
  full_samples.append(dict(city=city,orbit=orbit,values=d.iloc[full_ix][list(CONTEXT)].to_numpy(float)))
  for pair in settings["candidate_pairs"]:
   for width in settings["halfwidths_fraction"]:
    result,masks,ref=endpoint_support(d,pair["f0"],pair["f1"],width)
    endpoint_rows.append(dict(**identity,pair_id=pair["pair_id"],n_original_cells=len(d),n_original_blocks=d.block.nunique(),**result))
    if pair["pair_id"]!="historical":continue
    old=previous[(previous.city.eq(city))&previous.orbit.eq(orbit)].iloc[0]
    if result["spanning_blocks"]!=int(old.reference_supporting_blocks) or result["reference_cells"]!=int(old.reference_cells):raise ValueError("Historical support differs from Step3")
    for endpoint,mask in zip(("lower","upper"),masks):
     for variable in CONTEXT:
      covariate_rows.append(dict(**identity,halfwidth_fraction=width,endpoint=endpoint,variable=variable,
       unit="m" if variable in ("elevation","distance_to_water") else "fraction",**distribution(d.loc[mask,variable])))
     indices=np.flatnonzero(mask);n=min(len(indices),2000)
     picked=rng.choice(indices,n,replace=False) if n else np.array([],int)
     sample=d.iloc[picked][["cell_id",*CONTEXT]].copy();sample["city"]=city;sample["orbit"]=orbit
     band_samples.append(dict(identity=identity,width=width,endpoint=endpoint,frame=sample))
  for variable in CONTEXT:
   b=d.groupby("block")[variable].agg(["min","max"])
   varying=b.index[b["max"]>b["min"]]
   groups={f"{int(v.split('_')[0])//8}_{int(v.split('_')[1])//8}" for v in varying}
   bare_rows.append(dict(**identity,variable=variable,nonzero_cells=int((d[variable]!=0).sum()),within_block_varying_blocks=len(varying),varying_8km_groups=len(groups)))
  designs={}
  for quadratic in (False,True):
   kind="quadratic" if quadratic else "linear"
   try:
    design=protected_design(d,quadratic=quadratic);designs[kind]=design
    diagnostic=design.diagnostics.copy();diagnostic["removed_context_terms"]=json.dumps(diagnostic["removed_context_terms"])
    design_rows.append(dict(**identity,model=kind,**diagnostic))
   except ValueError as error:
    failures.append(dict(**identity,model=kind,status="NOT_ESTIMABLE_DESIGN",reason=str(error)))
  if len(designs)==2:
   for size in (1,8):
    r=resampled_design_rank(designs["linear"],designs["quadratic"],size=size,replicates=1000,seed=20261004+100000+int(orbit))
    resampling_rows.append(dict(**identity,**r))
  print(json.dumps(dict(stage="predictor_audit_pass_complete",city=city,orbit=orbit,models_estimable=list(designs),outcome_columns_read=False)),flush=True)
  del d,designs;gc.collect()
 mean,sd=weighted_scaling(full_samples)
 distance_rows=[];city_profile_rows=[];reference_rows=[]
 for width in settings["halfwidths_fraction"]:
  for endpoint in ("lower","upper"):
   samples=[s for s in band_samples if s["width"]==width and s["endpoint"]==endpoint]
   pools={}
   for city in ("phoenix","atlanta"):
    pool=pd.concat([s["frame"] for s in samples if s["identity"]["city"]==city],ignore_index=True)
    # Unique ground identity within the sampled reference pool; recurring cells
    # are not counted as distinct reference support merely for another date.
    duplicate=pool.groupby("cell_id")[list(CONTEXT)].nunique()
    if (duplicate>1).any().any():raise ValueError("Recurring reference cell predictor values changed")
    pools[city]=pool.drop_duplicates("cell_id").sort_values("cell_id").reset_index(drop=True)
   n=min(5000,len(pools["phoenix"]),len(pools["atlanta"]))
   refs={}
   for k,city in enumerate(("phoenix","atlanta")):
    pool=pools[city];rng=np.random.default_rng(20261004+int(width*1e6)+(0 if endpoint=="lower" else 100)+k)
    chosen=rng.choice(len(pool),n,replace=False) if n else np.array([],int)
    refs[city]=pool.iloc[chosen][list(CONTEXT)].to_numpy(float)
    reference_rows.append(dict(city=city,endpoint=endpoint,halfwidth_fraction=width,sampled_unique_candidates=len(pool),equal_city_reference_cells=n))
    for j,variable in enumerate(CONTEXT):city_profile_rows.append(dict(city=city,endpoint=endpoint,halfwidth_fraction=width,variable=variable,**distribution(refs[city][:,j])))
   for sample in samples:
    city=sample["identity"]["city"];other="atlanta" if city=="phoenix" else "phoenix"
    q=sample["frame"][list(CONTEXT)].to_numpy(float);distance=cross_distances(q,refs[other],mean,sd)
    distance_rows.append(dict(**sample["identity"],endpoint=endpoint,halfwidth_fraction=width,query_cells=len(q),other_city_reference_cells=n,
     status="DESCRIPTIVE_DISTANCE_NO_CUTOFF" if distance is not None else "NOT_ASSESSABLE_EMPTY_SUPPORT",
     **({k:v for k,v in distance.items() if k!="n"} if distance else {k:None for k in ("min","p05","p25","median","p75","p95","max","mean","sd")})))
 tables={"endpoint_support.csv":endpoint_rows,"endpoint_covariate_profiles.csv":covariate_rows,
         "design_diagnostics.csv":design_rows,"design_resampling.csv":[{k:v for k,v in r.items() if not k.endswith("_indices")} for r in resampling_rows],
         "cross_city_context_distances.csv":distance_rows,"cross_city_reference_profiles.csv":city_profile_rows}
 write("public_table_matrices.json",{name:dict(headers=list(rows[0]),rows=[[r.get(k) for k in rows[0]] for r in rows]) for name,rows in tables.items() if rows})
 write("design_resampling_detail.json",resampling_rows);write("control_information_support.json",bare_rows);write("within_block_canopy_span.json",span_rows)
 write("cross_city_reference_sampling.json",dict(scaling_mean=dict(zip(CONTEXT,mean.tolist())),scaling_sd=dict(zip(CONTEXT,sd.tolist())),zero_SD_dimensions=[n for n,s in zip(CONTEXT,sd) if s==0],references=reference_rows,diagnostic_only=True))
 write("failures.json",failures)
 summary=dict(status="PREDICTOR_SUPPORT_AND_DESIGN_AUDIT_COMPLETE",passes=16,year=2023,cities={"phoenix":11,"atlanta":5},
  original_cell_pass_observations=sum(p["n_cells"] for p in record["passes"]),candidate_pairs=15,neighbourhood_halfwidths=[.01,.025,.05],
  table_rows={n:len(r) for n,r in tables.items()},designs_estimable=len(design_rows),design_failures=len(failures),
  rank_resampling_configurations=len(resampling_rows),rank_draws_requested=sum(r["requested"] for r in resampling_rows),
  linear_rank_estimable=sum(r["linear_estimable"] for r in resampling_rows),quadratic_rank_estimable=sum(r["quadratic_estimable"] for r in resampling_rows),
  paired_rank_estimable=sum(r["paired_estimable"] for r in resampling_rows),paired_rank_failed=sum(r["paired_failed"] for r in resampling_rows),
  outcome_columns_read=False,coefficient_or_effect_files_read=False,new_outcome_fits=0,new_temporal_comparisons=0,new_inclusion_cutoff=None,
  cross_city_ranking_or_positivity_claim=False,historical_reference_reselected=False,all_historical_counts_reconcile_with_Step3=True,
  prior_disclosure="predictor-only calculations after prior released LST results; no claim of global blindness",
  physical_identity_checks=physical_checks)
 write("completion.json",summary);write("access_record.json",dict(frame_accesses=reader.access,decoded_outcomes=False,model_files_opened=[],new_effect_display=False,source_inputs_modified=False))
 plot_support(ROOT,RUN,endpoint_rows,design_rows,resampling_rows,distance_rows)
 print(json.dumps({k:summary[k] for k in ("status","designs_estimable","design_failures","rank_draws_requested","paired_rank_estimable","paired_rank_failed","outcome_columns_read")}),flush=True)


if __name__=="__main__":
 p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True);g.add_argument("--freeze",action="store_true");g.add_argument("--run",action="store_true");args=p.parse_args()
 freeze() if args.freeze else run()
