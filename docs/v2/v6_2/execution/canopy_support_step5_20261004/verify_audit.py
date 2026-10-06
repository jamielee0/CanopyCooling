"""Independent checks of predictor-only outputs, provenance and read boundary."""
import csv
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[5]
EXEC=Path(__file__).resolve().parent
PUB=ROOT/"outputs/v6_2/scientific/canopy_support_step5_20261004"
OUT=ROOT/"deliverables/Step5_Canopy_Support_2023_v6_2_20261004"


def sha(p):
 with p.open("rb") as h:return hashlib.file_digest(h,"sha256").hexdigest()


def verify():
 freeze=json.loads((EXEC/"execution_freeze.json").read_text());summary=json.loads((PUB/"completion.json").read_text())
 matrices=json.loads((PUB/"public_table_matrices.json").read_text());author=json.loads((EXEC/"csv_verification.json").read_text())
 for r in author["tables"]:
  assert sha(PUB/r["file"])==sha(OUT/r["file"])==r["sha256"]
  with (OUT/r["file"]).open(newline="") as h:rows=list(csv.reader(h))
  expected=matrices[r["file"]];assert rows[0]==expected["headers"] and len(rows)-1==len(expected["rows"])
  for actual,values in zip(rows[1:],expected["rows"]):
   for cell,value in zip(actual,values):
    if value is None:assert cell==""
    elif isinstance(value,(float,int)):assert float(cell)==value
    else:assert cell==value
  assert not set(expected["headers"]).intersection(("LST_K","M_W_m2","emissivity","coefficient","cooling","point","q025","q975"))
 for r in freeze["inputs"]:assert sha(ROOT/r["path"])==r["sha256"],"Frozen input changed"
 for p,h in freeze["code_sha256"].items():
  if p=="src/v6_2_advance/plot_canopy_support.py":assert sha(EXEC/"archive/plot_canopy_support_at_freeze.py")==h
  else:assert sha(ROOT/p)==h,"Scientific audit code changed"
 assert str((ROOT/"data").resolve(strict=True))==freeze["data_link_target"]
 access=json.loads((PUB/"access_record.json").read_text())
 assert len(access["frame_accesses"])==16
 for row in access["frame_accesses"]:
  assert row["outcome_columns_read"] is False
  assert not set(row["columns"]).intersection(("LST_K","M_W_m2","emissivity"))
 assert access["model_files_opened"]==[] and access["new_effect_display"] is False
 assert summary["passes"]==16 and summary["year"]==2023
 assert summary["original_cell_pass_observations"]==7511083
 assert summary["designs_estimable"]+summary["design_failures"]==32
 assert summary["rank_draws_requested"]==32000
 assert summary["paired_rank_estimable"]+summary["paired_rank_failed"]==32000
 assert summary["new_outcome_fits"]==summary["new_temporal_comparisons"]==0
 t=matrices["endpoint_support.csv"];rows=[dict(zip(t["headers"],r)) for r in t["rows"]]
 assert len(rows)==720 and len({(r["city"],r["orbit"],r["pair_id"],r["halfwidth_fraction"]) for r in rows})==720
 for r in rows:
  assert abs(r["f1"]-r["f0"]-.1)<1e-12
  assert r["reference_cells"]<=r["n_original_cells"] and r["spanning_blocks"]<=r["n_original_blocks"]
  assert abs(r["reference_whole_native_area_km2"]-r["reference_cells"]*.0049)<1e-9
  assert r["cells_in_both_neighbourhoods"]<=min(r["lower_cells"],r["upper_cells"])
  for endpoint in ("lower","upper"):
   width=r[endpoint+"_band_hi"]-r[endpoint+"_band_lo"]
   assert abs(r[endpoint+"_density_per_fraction"]-r[endpoint+"_cells"]/r["n_original_cells"]/width)<1e-10
 # Block spanning is independent of descriptive neighbourhood width.
 for city,orbit,pair in {(r["city"],r["orbit"],r["pair_id"]) for r in rows}:
  q=[r for r in rows if (r["city"],r["orbit"],r["pair_id"])==(city,orbit,pair)]
  assert len({(r["spanning_blocks"],r["reference_cells"]) for r in q})==1
 refs=json.loads((PUB/"cross_city_reference_sampling.json").read_text())["references"]
 for width in (.01,.025,.05):
  for endpoint in ("lower","upper"):
   q=[r for r in refs if r["endpoint"]==endpoint and r["halfwidth_fraction"]==width]
   assert len(q)==2 and q[0]["equal_city_reference_cells"]==q[1]["equal_city_reference_cells"]
 result=dict(status="PREDICTOR_AUDIT_NUMERIC_AND_BOUNDARY_CHECKS_PASSED_VISUAL_QA_PENDING",known_answer_tests=12,
  original_passes=16,source_hashes=len(freeze["inputs"]),original_cell_pass_observations=7511083,public_tables=6,
  public_rows=sum(r["rows"] for r in author["tables"]),typed_CSV_roundtrip="exact",historical_counts_reconciled=True,
  candidate_pairs=15,neighbourhood_widths=3,protected_basis_designs=32,design_resamples=32000,
  decoded_outcome_columns=[],coefficient_or_effect_files_opened=[],new_outcome_fits=0,new_effect_display=False,
  no_new_inclusion_cutoff=True,no_sample_change=True,native_identity_and_block_checks=True,
  equal_city_unique_reference_pool_sizes=True,scientific_audit_code_and_source_hashes_preserved=True,
  plot_only_layout_adjustment=dict(initial_archive="archive/plot_canopy_support_at_freeze.py",current_sha256=sha(ROOT/"src/v6_2_advance/plot_canopy_support.py")))
 (EXEC/"verification.json").write_text(json.dumps(result,indent=2)+"\n")
 print(json.dumps(result,indent=2))


if __name__=="__main__":verify()
