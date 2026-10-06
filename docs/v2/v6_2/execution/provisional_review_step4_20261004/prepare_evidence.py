"""Read public evidence for a provisional prose review; never open sealed files."""
import csv
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[5]
EXEC=Path(__file__).resolve().parent
SOURCES=[
 "deliverables/Results_Review_2023_v6_2_20261004/pass_results_long.csv",
 "deliverables/Results_Review_2023_v6_2_20261004/descriptive_summary.json",
 "deliverables/Results_Review_2023_v6_2_20261004/missing_inputs.json",
 "deliverables/Results_Review_2023_v6_2_20261004/README.md",
 "deliverables/Spatial_Scale_Review_2023_v6_2_20261004/footprint_and_reference_support.csv",
 "deliverables/Spatial_Scale_Review_2023_v6_2_20261004/canopy_context_distributions.csv",
 "deliverables/Spatial_Scale_Review_2023_v6_2_20261004/nonthermal_summary.json",
 "deliverables/Spatial_Scale_Review_2023_v6_2_20261004/sparse_control_rank_audit.json",
 "deliverables/Spatial_Scale_Review_2023_v6_2_20261004/remaining_limits.json",
 "deliverables/Spatial_Scale_Review_2023_v6_2_20261004/README.md",
 "docs/v2/v6_2/execution/results_review_20261004/scope.json",
 "docs/v2/v6_2/execution/spatial_scale_review_20261004/verification.json",
 "docs/v2/v6_2/phoenix_2023_sample_scope.md",
 "outputs/v6_2/scientific/exploratory_review_20260921/gradient_disclosure.json",
]


def sha(path):
 with path.open("rb") as h:return hashlib.file_digest(h,"sha256").hexdigest()


def read_public(path):
 if path not in SOURCES or "sealed_coefficients" in Path(path).parts or Path(path).suffix in (".npz",".parquet"):
  raise ValueError("Outside public Step4 review allowlist")
 p=ROOT/path
 if p.suffix==".csv":
  with p.open(newline="") as h:return list(csv.DictReader(h))
 if p.suffix==".json":return json.loads(p.read_text())
 return p.read_text()


def run():
 scope=json.loads((EXEC/"scope.json").read_text())
 assert str((ROOT/"data").resolve(strict=True))==scope["data_link_target"]
 hashes=[dict(path=p,bytes=(ROOT/p).stat().st_size,sha256=sha(ROOT/p)) for p in SOURCES]
 data=read_public(SOURCES[0]);original=[r for r in data if r["variant"]=="original"]
 assert len(original)==16
 keys={(r["city"],r["orbit"],r["source_run_id"],r["source_model_variant"]) for r in original}
 original_scope=read_public(SOURCES[10])["main_pilot"]["pass_identities"]
 expected={(r["city"],str(r["orbit"]),r["run_id"],r["variant"]) for r in original_scope}
 assert keys==expected
 assert all(r["local_date"].startswith("2023-") for r in original)
 for r in original:
  assert abs(float(r["cooling_K_per_10pp"])+float(r["signed_change_T_K_per_10pp"]))<1e-12
  assert r["paired_effect_status"]=="SEALED_NOT_RELEASED"
  for field in ("signed_flux_change_W_m2_per_10pp","flux_reduction_W_m2_per_10pp","signed_equivalent_change_K_per_10pp","equivalent_cooling_K_per_10pp"):
   assert r[field]==""
 summaries=read_public(SOURCES[1]);spatial=read_public(SOURCES[6]);rank=read_public(SOURCES[7]);verified=read_public(SOURCES[11])
 assert rank["all_failures_exactly_match_absence_of_common_bare_variation"]
 assert rank["reported_joint_nonestimable_draws"]==verified["joint_nonestimable_draws"]==48
 assert verified["joint_estimable_draws"]==21952 and verified["scale_tolerance"] is None
 summary={}
 tables=[]
 for city in ("phoenix","atlanta"):
  rows=sorted([r for r in original if r["city"]==city],key=lambda r:r["local_date"])
  assert len(rows)==(11 if city=="phoenix" else 5)
  values=[float(r["cooling_K_per_10pp"]) for r in rows]
  assert [min(values),max(values)]==summaries[city]["cooling_K_per_10pp_range"]
  extremes={kind:{k:r[k] for k in ("city","orbit","local_date","apparent_solar_hour","cooling_K_per_10pp","source_run_id")} for kind,r in (("minimum",min(rows,key=lambda r:float(r["cooling_K_per_10pp"]))),("maximum",max(rows,key=lambda r:float(r["cooling_K_per_10pp"]))))}
  summary[city]=dict(count=len(rows),released_extremes=extremes,range_K_per_10pp=[min(values),max(values)],
                   linked_weather=sum(r["air_temperature_K"]!="" for r in rows),all_8km_intervals_above_zero=all(float(r["cooling_q025_K_per_10pp"])>0 for r in rows))
  tables += ["### "+city.title(),"","| Date in 2023 | Solar hour | Cooling K per 10pp | 95% interval 1km | 95% interval 8km | HRRR linked |","| --- | ---: | ---: | --- | --- | --- |"]
  for r in rows:
   ci=lambda size:"["+format(float(next(x for x in data if x["city"]==city and x["orbit"]==r["orbit"] and x["variant"]==("original" if size==1 else "spatial_uncertainty_8km"))["cooling_q025_K_per_10pp"]),".3f")+", "+format(float(next(x for x in data if x["city"]==city and x["orbit"]==r["orbit"] and x["variant"]==("original" if size==1 else "spatial_uncertainty_8km"))["cooling_q975_K_per_10pp"]),".3f")+"]"
   tables.append("| "+r["local_date"][5:]+" | "+format(float(r["apparent_solar_hour"]),".3f")+" | "+format(float(r["cooling_K_per_10pp"]),".3f")+" | "+ci(1)+" | "+ci(8)+" | "+("yes" if r["air_temperature_K"] else "missing")+" |")
  tables += [""]
 (EXEC/"released_result_tables.md").write_text("\n".join(tables)+"\n")
 evidence=dict(status="PUBLIC_EVIDENCE_RECONCILED",year=2023,cities=summary,spatial_support=spatial,
              rank_summary={k:rank[k] for k in ("common_cells_with_positive_bare_fraction","common_blocks_with_within_block_bare_variation","information_groups_8km","reported_joint_nonestimable_draws","all_failures_exactly_match_absence_of_common_bare_variation")},
              verified_internal_spatial_computation=dict(joint_estimable=21952,joint_nonestimable=48,fixed_registration_pairs=24,paired_scale_configurations=32),
              quantitative_time_comparisons_computed=False,formal_date_or_neighborhood_influence_computed=False,simulation_effect_range_selected=False,sealed_files_opened=[])
 (EXEC/"evidence_summary.json").write_text(json.dumps(evidence,indent=2)+"\n")
 (EXEC/"input_manifest.json").write_text(json.dumps(dict(record_date_local="2026-10-04",inputs=hashes,code_sha256=sha(Path(__file__)),data_link_target=scope["data_link_target"],public_evidence_only=True,sealed_files_opened=[]),indent=2)+"\n")
 for r in hashes:assert sha(ROOT/r["path"])==r["sha256"]
 print(json.dumps(dict(status="PUBLIC_EVIDENCE_RECONCILED",originals=16,input_hashes=len(hashes),sealed_reads=0,new_comparisons=0)))


if __name__=="__main__":run()
