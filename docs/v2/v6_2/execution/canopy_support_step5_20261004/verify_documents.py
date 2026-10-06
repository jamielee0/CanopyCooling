import copy
import difflib
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[5]
EXEC=Path(__file__).resolve().parent
ARCHIVE=ROOT/"docs/v2/v6_2/archive/before_canopy_support_step5_20261004"
OUT=ROOT/"deliverables/Step5_Canopy_Support_2023_v6_2_20261004"


def sha(p):
 with p.open("rb") as h:return hashlib.file_digest(h,"sha256").hexdigest()


class UniqueLoader(yaml.SafeLoader):pass
def mapping(loader,node,deep=False):
 loader.flatten_mapping(node);result={}
 for k,v in node.value:
  key=loader.construct_object(k,deep=deep)
  if key in result:raise ValueError("Duplicate YAML key")
  result[key]=loader.construct_object(v,deep=deep)
 return result
UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)


def run():
 old=yaml.load((ARCHIVE/"docs/v2/v6_2/protocol_v6_2.yml").read_text(),Loader=UniqueLoader)
 current=yaml.load((ROOT/"docs/v2/v6_2/protocol_v6_2.yml").read_text(),Loader=UniqueLoader)
 normalized=copy.deepcopy(current);normalized.pop("step5_predictor_support_audit_20261004")
 normalized["status"]=old["status"]
 for k in ("current_user_request","current_pre_update_snapshot"):normalized["authority"][k]=old["authority"][k]
 normalized["control_boundary"].pop("Step5_predictor_audit_executed")
 assert normalized==old,"Unplanned scientific or earlier-record change"
 step=current["step5_predictor_support_audit_20261004"]
 assert (step["Phoenix_passes"],step["Atlanta_passes"],step["year"])==(11,5,2023)
 assert step["new_outcome_model_fits"]==0 and step["fitting_scope_question_answer"] is None
 assert step["paired_design_draws_estimable"]==step["design_draws_requested"]==32000
 assert step["scale_tolerance"] is None and step["new_support_inclusion_cutoff"] is None
 snapshot=json.loads((ARCHIVE/"snapshot.json").read_text())
 previous=json.loads((ROOT/"docs/v2/v6_2/execution/provisional_review_step4_20261004/completion_manifest.json").read_text())
 oldhash={r["path"]:r["sha256"] for r in previous["files"]}
 renderer_path=ROOT/"docs/v2/v6_2/execution/provisional_review_step4_20261004/render_review_qa.py"
 spec=importlib.util.spec_from_file_location("step5_doc_renderer",renderer_path);renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
 renderer.QA=EXEC/"qa"
 previews=renderer.render((OUT/"README.md").read_text().splitlines(),"report_page","Step5 predictor support and design audit")
 for i,r in enumerate(snapshot["files"],1):
  archived=ROOT/r["archive_path"];path=ROOT/r["original_path"]
  assert sha(archived)==r["sha256"]==oldhash[r["original_path"]]
  additions=[line[2:] for line in difflib.ndiff(archived.read_text().splitlines(),path.read_text().splitlines()) if line.startswith("+ ")]
  for line in additions:
   for target in re.findall(r"\]\(([^)]+)\)",line):
    if not target.startswith(("http","#")):assert (path.parent/target).exists(),target
  previews+=renderer.render(additions,f"document_{i:02d}_page",f"Step5 document additions {i}")
 for target in re.findall(r"\]\(([^)]+)\)",(OUT/"README.md").read_text()):
  if not target.startswith(("http","#")):assert (OUT/target).exists(),target
 decision=json.loads((EXEC/"audit_decision.json").read_text())
 assert decision["scope_question"]["answer_recorded"] is None
 assert decision["evidence"]["outcome_columns_read"] is False
 result=dict(status="PASSED_TEXT_YAML_AND_PRESERVATION_VISUAL_INSPECTION_PENDING",unchanged_scientific_settings=True,
  earlier_steps_preserved=True,six_Step4_documents_archived_exactly=True,archive_hashes_match_prior_completion=True,
  sample_and_scope_consistent=True,fit_scope_pending_explicit=True,new_local_links_exist=True,previews=previews,
  native_Codex_preview_inspected=False,renderer="basic offline text/table layout")
 (EXEC/"documentation_verification.json").write_text(json.dumps(result,indent=2)+"\n")
 print(json.dumps(result,indent=2))


if __name__=="__main__":run()
