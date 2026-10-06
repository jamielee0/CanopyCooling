"""Cross-document preservation and public-only completion records for Step3."""
import copy
import difflib
import hashlib
import json
import re
import textwrap
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[5]
EXEC=Path(__file__).resolve().parent
ARCHIVE=ROOT/"docs/v2/v6_2/archive/before_spatial_scale_review_20261004"
PUB=ROOT/"outputs/v6_2/scientific/spatial_scale_review_20261004"
OUT=ROOT/"deliverables/Spatial_Scale_Review_2023_v6_2_20261004"


def sha(p):
    with p.open("rb") as h:return hashlib.file_digest(h,"sha256").hexdigest()


def save(p,d):p.write_text(json.dumps(d,indent=2)+"\n")


class UniqueLoader(yaml.SafeLoader):pass


def mapping(loader,node,deep=False):
    loader.flatten_mapping(node);result={}
    for k,v in node.value:
        key=loader.construct_object(k,deep=deep)
        if key in result:raise ValueError("Duplicate YAML key: "+str(key))
        result[key]=loader.construct_object(v,deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)


def verify_documents():
    old=yaml.load((ARCHIVE/"docs/v2/v6_2/protocol_v6_2.yml").read_text(),Loader=UniqueLoader)
    now=yaml.load((ROOT/"docs/v2/v6_2/protocol_v6_2.yml").read_text(),Loader=UniqueLoader)
    normalized=copy.deepcopy(now);normalized.pop("results_review_third_step_20261004")
    normalized["status"]=old["status"]
    for field in ("current_user_request","current_pre_update_snapshot"):normalized["authority"][field]=old["authority"][field]
    normalized["control_boundary"]["analysis_executed_by_this_update"]=old["control_boundary"]["analysis_executed_by_this_update"]
    normalized["control_boundary"].pop("bounded_internal_spatial_review_executed")
    assert normalized==old,"Unplanned change to existing protocol/scientific settings"
    step=now["results_review_third_step_20261004"]
    assert (step["Phoenix_passes"],step["Atlanta_passes"],step["year"])==(11,5,2023)
    assert step["new_effects_or_endpoints_displayed"] is False and step["scale_tolerance"] is None
    assert step["joint_requested_draws"]==step["joint_estimable_draws"]+step["joint_nonestimable_draws"]==22000
    assert step["joint_nonestimable_draws"]==48 and step["known_answer_boundary_tests_passed"]==20
    rank=json.loads((PUB/"sparse_control_rank_audit.json").read_text())
    assert rank["all_failures_exactly_match_absence_of_common_bare_variation"] is True
    assert rank["common_cells_with_positive_bare_fraction"]==54 and rank["common_blocks_with_within_block_bare_variation"]==10
    assert rank["reported_joint_nonestimable_draws"]==48 and rank["outcome_columns_read"] is False
    rankfreeze=json.loads((EXEC/"sparse_control_audit_freeze.json").read_text())
    assert sha(EXEC/"audit_sparse_control.py")==rankfreeze["code_sha256"]
    for check in rank["checks"]:
        p=ROOT/f"outputs/v6_2/sealed_coefficients/spatial_scale_review_20261004/{check['orbit']}_joint_original_common_{check['group_km']}km_SEALED.npz"
        assert sha(p)==check["private_validity_file_sha256"] and check["mismatch_count"]==0
    snapshot=json.loads((ARCHIVE/"snapshot.json").read_text())
    oldmanifest=json.loads((ROOT/"docs/v2/v6_2/execution/results_packet_20261004/completion_manifest.json").read_text())
    oldhash={r["path"]:r["sha256"] for r in oldmanifest["files"]}
    previews=[]
    font=ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf",18)
    title=ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf",23)
    for i,r in enumerate(snapshot["files"],1):
        archived=ROOT/r["archive_path"];current=ROOT/r["original_path"]
        assert sha(archived)==r["sha256"]==oldhash[r["original_path"]]
        additions=[line[2:] for line in difflib.ndiff(archived.read_text().splitlines(),current.read_text().splitlines()) if line.startswith("+ ")]
        lines=[part for line in additions for part in (textwrap.wrap(line,width=108) or [""])]
        for page,start in enumerate(range(0,len(lines),48),1):
            image=Image.new("RGB",(1240,1420),"white");draw=ImageDraw.Draw(image)
            draw.text((45,35),f"Step 3 completion · document {i}, page {page}",font=title,fill="#20334D")
            draw.text((45,78),r["original_path"],font=font,fill="#475467")
            for j,line in enumerate(lines[start:start+48]):draw.text((45,140+j*25),line,font=font,fill="#172B4D")
            path=EXEC/f"qa/document_{i:02d}_page_{page:02d}.png";image.save(path);previews.append(str(path.relative_to(ROOT)))
        for line in additions:
            for target in re.findall(r"\]\(([^)]+)\)",line):
                if not target.startswith(("http","#")):assert (current.parent/target).exists(),target
        assert "Step 3" in current.read_text() or current.suffix==".yml"
    save(EXEC/"documentation_verification.json",dict(status="PASSED_NUMERICAL_AND_TEXT_PREVIEWS_PENDING_VISUAL_INSPECTION",
        yaml_parse_and_duplicate_keys="passed",unchanged_scientific_settings_and_old_step_records=True,
        allowed_differences="status, latest authority/snapshot, internal-analysis flags, new Step3 section only",
        six_Step2_documents_preserved_exactly=True,archived_hashes_match_Step2_completion=True,
        sample_and_sealing_consistent=True,draw_and_rank_audit_counts_consistent=True,new_local_links_exist=True,
        offline_previews=previews,native_Codex_preview_inspected=False))
    verification=json.loads((EXEC/"verification.json").read_text())
    verification["sparse_control_audit"]="passed; all48 failed draws omit common bare-cover variation; no outcomes/effects read"
    verification["public_visual_qa"]={"map":"passed after footer-spacing repair", "retention":"passed, eleven dates and counts readable", "seven_predictor_distributions":"passed", "CSV_previews":"all four views passed"}
    verification["sealed_effect_visual_qa"]="deferred at user request; metadata/nonblank/permissions checks only"
    save(EXEC/"verification.json",verification)
    print(json.dumps(dict(document_previews=previews,scientific_preservation=True,rank_audit=True),indent=2))


if __name__=="__main__":verify_documents()
