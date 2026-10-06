"""Preserve access, documentation, visual QA and checksums after Step 2 review."""
import copy
import difflib
import hashlib
import json
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[5]
EXEC = Path(__file__).resolve().parent
OUT = ROOT/"deliverables/Results_Review_2023_v6_2_20261004"
ARCHIVE = ROOT/"docs/v2/v6_2/archive/before_results_packet_20261004"


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def save(path, value): path.write_text(json.dumps(value, indent=2)+"\n")


class UniqueLoader(yaml.SafeLoader): pass


def mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result: raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def finalize():
    freeze = json.loads((EXEC/"execution_freeze.json").read_text())
    assembly = json.loads((EXEC/"assembly_verification.json").read_text())
    snapshot = json.loads((ARCHIVE/"snapshot.json").read_text())
    old_protocol = yaml.load((ARCHIVE/"docs/v2/v6_2/protocol_v6_2.yml").read_text(), Loader=UniqueLoader)
    current_protocol = yaml.load((ROOT/"docs/v2/v6_2/protocol_v6_2.yml").read_text(), Loader=UniqueLoader)
    normalized = copy.deepcopy(current_protocol)
    normalized.pop("results_review_second_step_20261004")
    normalized["status"] = old_protocol["status"]
    normalized["authority"]["current_user_request"] = old_protocol["authority"]["current_user_request"]
    normalized["authority"]["current_pre_update_snapshot"] = old_protocol["authority"]["current_pre_update_snapshot"]
    normalized["control_boundary"].pop("existing_released_result_assembly_executed")
    assert normalized == old_protocol, "Unplanned scientific protocol change"
    step = current_protocol["results_review_second_step_20261004"]
    assert (step["Phoenix_passes"], step["Atlanta_passes"], step["year"]) == (11, 5, 2023)
    assert step["paired_flux_and_equivalent_effects"] == "SEALED_NOT_RELEASED"
    assert step["new_model_fits"] == step["new_empirical_time_comparisons"] == step["sealed_files_opened"] == 0
    old_manifest = json.loads((ROOT/"docs/v2/v6_2/execution/results_review_20261004/manifest.json").read_text())
    old_hashes = {r["path"]: r["sha256"] for r in old_manifest["active_documents"]}
    for row in snapshot["files"]:
        assert sha(ROOT/row["archive_path"]) == row["sha256"] == old_hashes[row["original_path"]]
    implementation = []
    for row in freeze["code_at_freeze"]:
        archived = EXEC/"archive/initial_implementation"/Path(row["path"]).name
        assert sha(archived) == row["sha256"], row["path"]
        implementation.append({"path": row["path"], "initial_sha256": row["sha256"], "final_sha256": sha(ROOT/row["path"]), "initial_archive": str(archived.relative_to(ROOT))})
    save(EXEC/"implementation_adjustments.json", {
        "initial_implementation_corresponds_to_freeze": True, "versions": implementation,
        "changes_after_freeze": [
            "Rejecting acquisition/product check exposed older numeric CSV label 2; verify collection equivalence against exact manifest, author 002 and preserve original source label. Added one known-answer test.",
            "Artifact value setter coerced exact ISO strings to Date and lost original offsets/subseconds formatting. Guard rejected those attempts. Preserve exact text with reversible prefix, verify encoded sheet and decoded matrix before CSV serialization.",
            "Public API documents native XLSX export only; requested CSV uses RFC4180 serialization of verified artifact sheet values, not rounded display values.",
            "Visual QA moved close Phoenix labels and added two leader lines; moved footnotes clear of bottom edge. No numerical plot coordinate or interval changed.",
        ], "scientific_design_changed": False, "source_files_changed": False,
        "accepted_csv_numeric_roundtrip": "exact", "original_code_preserved": True,
    })
    save(EXEC/"reuse_and_access_record.json", {
        "created_utc": datetime.now(timezone.utc).isoformat(), "status": "COMPLETED_RELEASED_RESULT_ASSEMBLY",
        "user_request": "ok, do the next part", "authorized_plan_step": 2,
        "original_pass_count": {"phoenix": 11, "atlanta": 5}, "year": 2023, "other_year_weight": 0,
        "output_scope": "Previously released LST pass effects and 1/2/4/8km bootstrap interval derivatives reformatted; no newly disclosed effect",
        "prior_release_records": ["outputs/v6_2/scientific/exploratory_review_20260921/gradient_disclosure.json", "docs/v2/v6_2/execution/limited_gradient_disclosure_20260919.json"],
        "public_numeric_reference_metadata_read": "outputs/v6_2/scientific/scale_diagnostics_20260919/frozen_numeric_references.json; historical ten-pass reference only",
        "public_sources_parsed": assembly["public_sources_read"], "public_sources_hashed": [r["path"] for r in freeze["inputs"]],
        "sealed_model_arrays_or_draws_opened": [], "cached_native_thermal_frames_opened": [],
        "historical_native_frame_hashes": "reused from predictor-only freeze; no new access to referenced frames",
        "paired_flux_and_equivalent_effects": "SEALED_NOT_RELEASED", "spatial_comparison_effects": "remain sealed",
        "new_coefficient_unsealing": False, "new_model_fits": 0, "new_empirical_time_comparisons": 0,
        "new_weather_retrieval": False, "scale_tolerance": None, "scale_ruling": "pending Reza; no ruling",
        "next_plan_step": 3, "extension_authorized": False, "professor_approval": "not implied",
        "packet": str(OUT.relative_to(ROOT)), "csv_sha256": sha(OUT/"pass_results_long.csv"),
    })
    # Independently rasterize added document text for scope/status visual QA.
    font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
    font = ImageFont.truetype(font_path, 18)
    titlefont = ImageFont.truetype(font_path, 23)
    preview_paths = []
    for index, row in enumerate(snapshot["files"], 1):
        path = ROOT/row["original_path"]
        before = (ROOT/row["archive_path"]).read_text().splitlines()
        after = path.read_text().splitlines()
        added = [line[1:] for line in difflib.ndiff(before, after) if line.startswith("+ ")]
        wrapped = [part for line in added for part in (textwrap.wrap(line, width=106) or [""])]
        for page, start in enumerate(range(0, len(wrapped), 48), 1):
            im = Image.new("RGB", (1220, 1420), "white")
            draw = ImageDraw.Draw(im)
            draw.text((45, 35), f"Step 2 completion · document {index}, page {page}", font=titlefont, fill="#20334D")
            draw.text((45, 78), row["original_path"], font=font, fill="#475467")
            for i, line in enumerate(wrapped[start:start+48]):
                draw.text((45, 140+i*25), line, font=font, fill="#172B4D")
            target = EXEC/f"qa/document_{index:02d}_page_{page:02d}.png"
            im.save(target)
            preview_paths.append(str(target.relative_to(ROOT)))
        # Check the new/changed local links only; historical link formats are preserved.
        for line in added:
            for match in re.finditer(r"\]\(([^)]+)\)", line):
                link = match.group(1)
                if not link.startswith(("http", "#")):
                    assert (path.parent/link).exists(), (row["original_path"], link)
        assert "Step 2" in path.read_text() or path.suffix == ".yml"
    save(EXEC/"documentation_verification.json", {
        "status": "PASSED_NUMERIC_AND_TEXT; document preview visual inspection pending",
        "yaml_parse_and_duplicate_keys": "passed", "unchanged_scientific_specification": True,
        "allowed_yaml_differences": "status, latest request/snapshot, assembly flag, Step2 completion section only",
        "six_step1_documents_archived_exactly": True, "archive_hashes_match_step1_manifest": True,
        "cross_document_step2_and_scope": True, "new_local_links_exist": True,
        "offline_document_addition_previews": preview_paths,
        "native_Codex_preview_inspected": False,
    })
    verification = json.loads((EXEC/"final_verification.json").read_text())
    verification["visual_qa"] = {"phoenix": "passed; both panels, all eleven dates and close-point leader lines", "atlanta": "passed; both panels, all five dates", "table_preview": "passed; 16 identities, values and both interval sizes readable", "scope": "offline PNGs; no claim of native Codex preview"}
    verification["final_code"] = [{"path": r["path"], "sha256": r["final_sha256"]} for r in implementation]
    save(EXEC/"final_verification.json", verification)
    print(json.dumps({"status": "READY_FOR_DOCUMENT_VISUAL_CHECK", "document_previews": preview_paths}, indent=2))


if __name__ == "__main__": finalize()
