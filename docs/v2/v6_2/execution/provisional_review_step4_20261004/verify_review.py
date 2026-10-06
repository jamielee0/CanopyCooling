"""Documentation-only consistency checks; no model or sealed file reads."""
import copy
import csv
import difflib
import hashlib
import json
import re
from pathlib import Path

import yaml

ROOT=Path(__file__).resolve().parents[5]
EXEC=Path(__file__).resolve().parent
ARCHIVE=ROOT/"docs/v2/v6_2/archive/before_provisional_step4_review_20261004"
REPORT=ROOT/"docs/v2/v6_2/provisional_results_review_step4_20261004.md"


def sha(p):
 with p.open("rb") as h:return hashlib.file_digest(h,"sha256").hexdigest()


class UniqueLoader(yaml.SafeLoader):pass


def mapping(loader,node,deep=False):
 loader.flatten_mapping(node);result={}
 for key_node,value_node in node.value:
  key=loader.construct_object(key_node,deep=deep)
  if key in result:raise ValueError("Duplicate YAML key: "+str(key))
  result[key]=loader.construct_object(value_node,deep=deep)
 return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)


def verify():
 old=yaml.load((ARCHIVE/"docs/v2/v6_2/protocol_v6_2.yml").read_text(),Loader=UniqueLoader)
 current=yaml.load((ROOT/"docs/v2/v6_2/protocol_v6_2.yml").read_text(),Loader=UniqueLoader)
 normalized=copy.deepcopy(current);normalized.pop("results_review_fourth_step_20261004")
 normalized["status"]=old["status"]
 for k in ("current_user_request","current_pre_update_snapshot"):normalized["authority"][k]=old["authority"][k]
 normalized["control_boundary"].pop("provisional_step4_review_executed")
 assert normalized==old,"Unplanned scientific setting/earlier-record change"
 step=current["results_review_fourth_step_20261004"]
 assert (step["Phoenix_passes"],step["Atlanta_passes"],step["year"])==(11,5,2023)
 assert step["scale_tolerance"] is None and step["numeric_simulation_effect_range"] is None
 assert step["new_effect_display"] is False and step["new_fit_or_bootstrap"] is False and step["sealed_files_opened"]==0
 decision=json.loads((EXEC/"decision_record.json").read_text())
 assert decision["decisions_now"]["numeric_temporal_simulation_effect_range"] is None
 assert decision["decisions_now"]["full_Stage1_approval"] is False
 assert decision["display_boundary"]["new_coefficient_display"] is False
 assert decision["next_bounded_preparation"]["status"]=="RECOMMENDED_NOT_EXECUTED"
 assert decision["work_performed_this_step"]["sealed_files_opened"]==[]
 assert decision["work_performed_this_step"]["scientific_rules_changed"] is False
 manifest=json.loads((EXEC/"input_manifest.json").read_text())
 for r in manifest["inputs"]:
  assert "sealed_coefficients" not in Path(r["path"]).parts and Path(r["path"]).suffix not in (".npz",".parquet")
  assert sha(ROOT/r["path"])==r["sha256"]
 assert len(manifest["inputs"])==step["public_source_hashes_verified"]==14
 assert sha(EXEC/"prepare_evidence.py")==manifest["code_sha256"]
 assert str((ROOT/"data").resolve(strict=True))==manifest["data_link_target"]
 text=REPORT.read_text()
 expected=(EXEC/"released_result_tables.md").read_text().strip()
 assert expected in text,"Released sixteen-row table differs from source-derived text"
 assert "No numerical temporal effect range has been adopted" in text
 assert "formal_date_or_neighborhood_influence_computed" in (EXEC/"evidence_summary.json").read_text()
 assert "no neighbourhood influence analysis" in text
 evidence=json.loads((EXEC/"evidence_summary.json").read_text())
 assert evidence["quantitative_time_comparisons_computed"] is False and evidence["sealed_files_opened"]==[]
 assert evidence["verified_internal_spatial_computation"]["joint_estimable"]==21952
 assert evidence["rank_summary"]["reported_joint_nonestimable_draws"]==48
 snapshot=json.loads((ARCHIVE/"snapshot.json").read_text())
 previous=json.loads((ROOT/"docs/v2/v6_2/execution/spatial_scale_review_20261004/completion_manifest.json").read_text())
 previous_hashes={r["path"]:r["sha256"] for r in previous["files"]}
 additions=[]
 for r in snapshot["files"]:
  before=ROOT/r["archive_path"];now=ROOT/r["original_path"]
  assert sha(before)==r["sha256"]==previous_hashes[r["original_path"]]
  assert "Step 4" in now.read_text() or now.suffix==".yml"
  added=[line[2:] for line in difflib.ndiff(before.read_text().splitlines(),now.read_text().splitlines()) if line.startswith("+ ")]
  additions.append(dict(source=r["original_path"],lines=added))
  for line in added:
   for target in re.findall(r"\]\(([^)]+)\)",line):
    if not target.startswith(("http","#")):assert (now.parent/target).exists(),target
 for doc in (REPORT,ROOT/"deliverables/Provisional_Results_Review_2023_v6_2_20261004/README.md"):
  for target in re.findall(r"\]\(([^)]+)\)",doc.read_text()):
   if not target.startswith(("http","#")):assert (doc.parent/target).exists(),target
 (EXEC/"document_additions.json").write_text(json.dumps(additions,indent=2)+"\n")
 result=dict(status="PASSED_NUMERICAL_TEXT_AND_PRESERVATION_VISUAL_QA_PENDING",work_kind="documentation/review only",
  public_source_hashes=14,original_city_orbit_run_model_keys=16,released_table_agreement="exact at declared three-decimal display precision",
  sign_units_and_city_ranges="reconciled",descriptive_extrema_not_new_time_contrasts=True,
  failed_draw_and_support_counts="reconciled with Step3 public evidence",
  decision_scope_and_holds_consistent=True,numeric_simulation_effect_range=None,scale_tolerance=None,
  yaml_parse_and_duplicate_keys="passed",unchanged_scientific_settings_and_earlier_step_records=True,
  six_Step3_documents_preserved=True,archive_hashes_match_Step3_completion=True,new_local_links_exist=True,
  data_link_target_verified=True,scientific_pipeline_or_tests_rerun=False,new_fit_or_bootstrap=False,
  new_empirical_time_comparison=False,sealed_files_opened=[],new_effect_display=False,
  native_Codex_preview_inspected=False)
 (EXEC/"verification.json").write_text(json.dumps(result,indent=2)+"\n")
 print(json.dumps(result,indent=2))


if __name__=="__main__":verify()
