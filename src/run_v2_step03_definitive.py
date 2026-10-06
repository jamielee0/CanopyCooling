#!/usr/bin/env python3
"""Validate and run the frozen cloud-independent/D0027 Step-3 profile.

The runner consumes only the normalized Step-2 planning count and empirical
predictor template.  It never opens a thermal response, 2026 data, or a holdout.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
from typing import Any

import numpy as np
import pandas as pd

from urban_cooling_v2 import step02_hrrr_fetch as hrrr_fetch
from urban_cooling_v2.config import load_config
from urban_cooling_v2.step02_archive_available import (
    ALGORITHM_VERSION as D0047_ALGORITHM_VERSION,
    CANDIDATE_STATUS_COLUMN as D0047_STATUS_COLUMN,
    DECISION_ID as D0047_DECISION_ID,
    EXCLUDED_STATUS as D0047_EXCLUDED_STATUS,
    FROZEN_COUNTS as D0047_COUNTS,
    PROFILE_INCLUDED_COLUMN as D0047_INCLUDED_COLUMN,
    RETAINED_STATUS as D0047_RETAINED_STATUS,
)
from urban_cooling_v2.step03_power import (
    DiagnosticThresholds,
    OBSERVED_GEOMETRY_STATUS,
    SimulationSpec,
    run_simulation_study,
    validate_template,
    write_step3_deliverables,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/v2_cities.toml"
STEP2 = ROOT / "data/processed/v2/task1/step2_definitive_l1b_geo"
PLANNING = STEP2 / "step3_planning_count.json"
STEP2_GATE_RECORD = STEP2 / "step2_gate_record.json"
OUTPUT = ROOT / "data/processed/v2/task1/step3_definitive_l1b_geo"

D0035_DECISION_ID = "D0035"
D0035_GEOMETRY_SOURCE = "ECO_L1B_GEO.002"
EXPECTED_METADATA_CANDIDATES = 942
D0035_PASS_STATUS = "PASS_D0035_GEOMETRY_AND_EXHAUSTIVE_CLOUD"
D0035_ALGORITHM_VERSION = "d0035-l1b-dmrpp-pass-stream-v4"
HRRR_RUN_SEAL_STATUS = "PASS_EXACT_HRRR_RUN_SEAL"
STEP2_GATE_RECORD_SCHEMA_VERSION = 1
D0047_PASS_STATUS = "PASS_D0047_ARCHIVE_AVAILABLE_GEOMETRY_AND_EXHAUSTIVE_CLOUD"
D0047_HRRR_RUN_SEAL_STATUS = (
    "PASS_EXACT_HRRR_RUN_SEAL_D0047_ARCHIVE_AVAILABLE"
)
D0047_COUNT_STATUS = "certified_archive_available_expected_pass_equivalent_floor"
ACTIVE_PROFILE = "d0035_exhaustive"
UPSTREAM_GATE_KEY = "upstream_d0035"
COUNT_STATUS = "certified_expected_pass_equivalent_floor"
SCIENTIFIC_GATE_SCOPE = "exhaustive_942_candidates"
ANALYSIS_PROFILE = "D0035_exhaustive"


def configure_profile(name: str, *, root: Path | None = None) -> None:
    """Activate the matching append-only Step-2/3 namespace."""

    global ACTIVE_PROFILE, STEP2, PLANNING, STEP2_GATE_RECORD, OUTPUT
    global D0035_DECISION_ID, D0035_PASS_STATUS, D0035_ALGORITHM_VERSION
    global EXPECTED_METADATA_CANDIDATES, HRRR_RUN_SEAL_STATUS
    global UPSTREAM_GATE_KEY, COUNT_STATUS, SCIENTIFIC_GATE_SCOPE, ANALYSIS_PROFILE
    base = Path(ROOT if root is None else root).resolve()
    ACTIVE_PROFILE = str(name)
    if name == "d0047_archive_available":
        STEP2 = base / (
            "data/processed/v2/task1/"
            "step2_definitive_l1b_geo_D0047_archive_available"
        )
        OUTPUT = base / (
            "data/processed/v2/task1/"
            "step3_definitive_l1b_geo_D0047_archive_available"
        )
        D0035_DECISION_ID = D0047_DECISION_ID
        D0035_PASS_STATUS = D0047_PASS_STATUS
        D0035_ALGORITHM_VERSION = D0047_ALGORITHM_VERSION
        EXPECTED_METADATA_CANDIDATES = D0047_COUNTS.retained_candidates
        HRRR_RUN_SEAL_STATUS = D0047_HRRR_RUN_SEAL_STATUS
        UPSTREAM_GATE_KEY = "upstream_quality_profile"
        COUNT_STATUS = D0047_COUNT_STATUS
        SCIENTIFIC_GATE_SCOPE = "archive_available_only"
        ANALYSIS_PROFILE = "D0047_archive_available"
    elif name == "d0035_exhaustive":
        STEP2 = base / "data/processed/v2/task1/step2_definitive_l1b_geo"
        OUTPUT = base / "data/processed/v2/task1/step3_definitive_l1b_geo"
        D0035_DECISION_ID = "D0035"
        D0035_PASS_STATUS = "PASS_D0035_GEOMETRY_AND_EXHAUSTIVE_CLOUD"
        D0035_ALGORITHM_VERSION = "d0035-l1b-dmrpp-pass-stream-v4"
        EXPECTED_METADATA_CANDIDATES = 942
        HRRR_RUN_SEAL_STATUS = "PASS_EXACT_HRRR_RUN_SEAL"
        UPSTREAM_GATE_KEY = "upstream_d0035"
        COUNT_STATUS = "certified_expected_pass_equivalent_floor"
        SCIENTIFIC_GATE_SCOPE = "exhaustive_942_candidates"
        ANALYSIS_PROFILE = "D0035_exhaustive"
    else:
        raise ValueError(f"unknown definitive Step-3 profile: {name}")
    PLANNING = STEP2 / "step3_planning_count.json"
    STEP2_GATE_RECORD = STEP2 / "step2_gate_record.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _step3_decision_ids(decision_id: str) -> list[str]:
    decision_ids = ["D0021", "D0027", "D0029", str(decision_id)]
    if ACTIVE_PROFILE == "d0047_archive_available":
        decision_ids.append("D0053")
    return decision_ids


def _true_series(values: pd.Series, *, label: str) -> pd.Series:
    """Parse a non-null boolean series without treating unknown text as false."""

    normalized = values.astype("string").str.strip().str.casefold()
    if normalized.isna().any() or not normalized.isin(
        {"true", "false", "1", "0"}
    ).all():
        raise RuntimeError(f"{label} contains values other than true/false")
    return normalized.isin({"true", "1"})


def _nullable_true_series(values: pd.Series, *, label: str) -> pd.Series:
    """Parse a nullable boolean series while preserving not-evaluated rows."""

    normalized = values.astype("string").str.strip().str.casefold()
    invalid = normalized.notna() & ~normalized.isin({"true", "false", "1", "0"})
    if invalid.any():
        raise RuntimeError(f"{label} contains values other than true/false/NA")
    return normalized.map(
        {"true": True, "1": True, "false": False, "0": False}
    ).astype("boolean")


def _repo_path(value: Any, *, label: str) -> Path:
    path = (ROOT / str(value)).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the repository") from exc
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    return path


def _load_step2_gate_record(planning: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    gate_path = _repo_path(
        planning["step2_gate_record_path"], label="step2_gate_record_path"
    )
    if gate_path.resolve() != STEP2_GATE_RECORD.resolve():
        raise RuntimeError("Step-3 planning points to a noncanonical Step-2 gate record")
    if _sha256(gate_path) != planning["step2_gate_record_sha256"]:
        raise RuntimeError("Step-2 gate record does not match its planning checksum")
    try:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        raise RuntimeError("Step-2 gate record is unreadable") from None
    required = {
        "schema_version",
        "decision_id",
        "status",
        "scientific_gate_eligible",
        "all_checks_pass",
        "checks_path",
        "checks_sha256",
        "checks",
        UPSTREAM_GATE_KEY,
        "hrrr_run_seal",
        "counts",
        "artifact_sha256",
        "lst_opened",
        "thermal_opened",
        "record_2026_opened",
        "holdout_status",
        "frozen_years",
    }
    missing = required - set(gate)
    if missing:
        raise RuntimeError(f"Step-2 gate record lacks {sorted(missing)}")
    if (
        gate.get("schema_version") != STEP2_GATE_RECORD_SCHEMA_VERSION
        or gate.get("decision_id") != D0035_DECISION_ID
        or gate.get("status") != "PASS"
        or gate.get("scientific_gate_eligible") is not True
        or gate.get("all_checks_pass") is not True
    ):
        raise RuntimeError(
            f"Definitive Step 3 requires an exact PASS Step-2 gate record; "
            f"found {gate.get('status')!r}"
        )
    if ACTIVE_PROFILE == "d0047_archive_available" and (
        gate.get("analysis_profile") != ANALYSIS_PROFILE
        or gate.get("scientific_gate_scope") != SCIENTIFIC_GATE_SCOPE
        or gate.get("profile_scope_label")
        != "archive_available_after_pre_geometry_exclusion_D0047"
        or gate.get("planning_count_status") != COUNT_STATUS
    ):
        raise RuntimeError("Step-2 PASS is not scoped to the D0047 archive-available profile")
    if planning.get("step2_gate") != gate["status"]:
        raise RuntimeError("Step-3 planning gate string disagrees with the PASS gate record")
    if (
        gate.get("lst_opened") is not False
        or gate.get("thermal_opened") is not False
        or gate.get("record_2026_opened") is not False
        or str(gate.get("holdout_status", "")).upper() != "UNSELECTED"
        or str(gate.get("frozen_years", "")) != "2018-2025"
    ):
        raise RuntimeError("Step-2 gate-record thermal/2026/holdout seals are broken")

    checks = gate.get("checks")
    if (
        not isinstance(checks, list)
        or not checks
        or not all(isinstance(item, dict) and item.get("pass") is True for item in checks)
    ):
        raise RuntimeError("Step-2 gate record contains a failed or malformed check")
    counts = gate.get("counts")
    if (
        not isinstance(counts, dict)
        or int(counts.get("step2_checks", -1)) != len(checks)
        or int(counts.get("step2_checks_passed", -1)) != len(checks)
    ):
        raise RuntimeError("Step-2 gate-record check counts are stale")
    if ACTIVE_PROFILE == "d0047_archive_available" and (
        int(counts.get("original_metadata_candidates", -1))
        != D0047_COUNTS.original_candidates
        or int(counts.get("excluded_pre_geometry_candidates", -1))
        != D0047_COUNTS.excluded_candidates
        or int(counts.get("retained_geometry_candidates", -1))
        != D0047_COUNTS.retained_candidates
        or int(counts.get("near_nadir_physical_passes", -1)) <= 0
    ):
        raise RuntimeError("D0047 Step-2 gate-record candidate counts are stale")
    checks_path = _repo_path(gate["checks_path"], label="Step-2 checks path")
    if _sha256(checks_path) != gate["checks_sha256"]:
        raise RuntimeError("Step-2 checks hash differs from the gate record")

    artifact_hashes = gate.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict) or not artifact_hashes:
        raise RuntimeError("Step-2 gate record has no artifact hash ledger")
    for relative_path, expected_hash in artifact_hashes.items():
        artifact = _repo_path(relative_path, label=f"Step-2 artifact {relative_path}")
        if _sha256(artifact) != expected_hash:
            raise RuntimeError(f"Step-2 gate artifact changed: {relative_path}")
    checks_key = str(checks_path.relative_to(ROOT))
    if artifact_hashes.get(checks_key) != gate["checks_sha256"]:
        raise RuntimeError("Step-2 check table is absent from the gate artifact ledger")

    upstream = gate.get(UPSTREAM_GATE_KEY)
    if (
        not isinstance(upstream, dict)
        or upstream.get("status") != D0035_PASS_STATUS
        or upstream.get("scientific_gate_eligible") is not True
        or upstream.get("algorithm_version") != D0035_ALGORITHM_VERSION
    ):
        raise RuntimeError("Step-2 gate record has a stale upstream quality-profile seal")
    if ACTIVE_PROFILE == "d0047_archive_available" and (
        upstream.get("decision_id") != D0047_DECISION_ID
        or upstream.get("analysis_profile") != ANALYSIS_PROFILE
        or upstream.get("scientific_gate_scope") != SCIENTIFIC_GATE_SCOPE
        or upstream.get("profile_scope_label")
        != "archive_available_after_pre_geometry_exclusion_D0047"
        or upstream.get("original_exhaustive_gate_status")
        != "STOP_D0035_INCOMPLETE_GEOMETRY"
        or upstream.get("restored_archive_sensitivity_required") is not True
    ):
        raise RuntimeError("D0047 upstream profile binding is incomplete")
    if ACTIVE_PROFILE == "d0047_archive_available":
        provenance_counts = upstream.get("provenance_counts")
        expected_provenance_counts = {
            "original_metadata_candidate_count": D0047_COUNTS.original_candidates,
            "excluded_pre_geometry_candidate_count": D0047_COUNTS.excluded_candidates,
            "retained_geometry_candidate_count": D0047_COUNTS.retained_candidates,
            "retained_city_scene_link_count": D0047_COUNTS.retained_city_scene_links,
            "retained_unique_scene_count": D0047_COUNTS.retained_unique_scenes,
        }
        if not isinstance(provenance_counts, dict) or any(
            int(provenance_counts.get(field, -1)) != expected
            for field, expected in expected_provenance_counts.items()
        ):
            raise RuntimeError("D0047 upstream quality-profile census is stale")
    upstream_path = _repo_path(
        upstream.get("run_record_path"), label="upstream quality-profile run record"
    )
    if (
        _sha256(upstream_path) != upstream.get("run_record_sha256")
        or planning.get("upstream_run_record_path")
        != upstream.get("run_record_path")
        or planning.get("upstream_run_record_sha256")
        != upstream.get("run_record_sha256")
        or planning.get("upstream_algorithm_version") != D0035_ALGORITHM_VERSION
        or artifact_hashes.get(str(upstream_path.relative_to(ROOT)))
        != upstream.get("run_record_sha256")
    ):
        raise RuntimeError("upstream quality-profile run-record binding is stale")

    hrrr = gate.get("hrrr_run_seal")
    if not isinstance(hrrr, dict) or hrrr.get("status") != HRRR_RUN_SEAL_STATUS:
        raise RuntimeError("Step-2 gate record lacks the exact HRRR run seal")
    if ACTIVE_PROFILE == "d0047_archive_available":
        binding = hrrr.get("profile_binding")
        if (
            not isinstance(binding, dict)
            or binding.get("decision_id") != D0047_DECISION_ID
            or binding.get("analysis_profile") != ANALYSIS_PROFILE
            or binding.get("scientific_gate_scope") != SCIENTIFIC_GATE_SCOPE
            or binding.get("profile_scope_label")
            != "archive_available_after_pre_geometry_exclusion_D0047"
            or int(binding.get("geometry_passing_candidate_count", -1))
            != int(counts.get("near_nadir_physical_passes", -2))
            or hrrr.get("profile_binding_sha256") != _json_sha256(binding)
        ):
            raise RuntimeError("D0047 exact-HRRR seal lacks its profile binding")
        expected_binding_pairs = {
            "upstream_run_record": (
                upstream.get("run_record_path"),
                upstream.get("run_record_sha256"),
            ),
            "candidate_availability_ledger": (
                upstream.get("candidate_availability_ledger_path"),
                upstream.get("candidate_availability_ledger_sha256"),
            ),
            "exclusion_summary": (
                upstream.get("exclusion_summary_path"),
                upstream.get("exclusion_summary_sha256"),
            ),
        }
        for label, (expected_path, expected_sha) in expected_binding_pairs.items():
            if (
                binding.get(f"{label}_path") != expected_path
                or binding.get(f"{label}_sha256") != expected_sha
            ):
                raise RuntimeError(f"D0047 HRRR {label} profile binding is stale")
        for label in (
            "combined_validation",
            "upstream_run_record",
            "candidate_availability_ledger",
            "exclusion_summary",
        ):
            artifact = _repo_path(
                binding.get(f"{label}_path"),
                label=f"D0047 HRRR {label}",
            )
            expected_sha = binding.get(f"{label}_sha256")
            if (
                _sha256(artifact) != expected_sha
                or artifact_hashes.get(str(artifact.relative_to(ROOT)))
                != expected_sha
            ):
                raise RuntimeError(f"D0047 HRRR {label} hash binding is stale")
    hrrr_path = _repo_path(hrrr.get("path"), label="exact HRRR run seal")
    if (
        _sha256(hrrr_path) != hrrr.get("sha256")
        or planning.get("hrrr_run_seal_path") != hrrr.get("path")
        or planning.get("hrrr_run_seal_sha256") != hrrr.get("sha256")
        or artifact_hashes.get(str(hrrr_path.relative_to(ROOT))) != hrrr.get("sha256")
    ):
        raise RuntimeError("exact HRRR run-seal binding is stale")
    try:
        hrrr_document = json.loads(hrrr_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        raise RuntimeError("exact HRRR run seal is unreadable") from None
    if (
        hrrr_document.get("schema_version")
        != hrrr_fetch.HRRR_RUN_SEAL_SCHEMA_VERSION
        or hrrr_document.get("status") != HRRR_RUN_SEAL_STATUS
        or hrrr_document.get("manifest_fields")
        != list(hrrr_fetch.HRRR_CHECKPOINT_REQUEST_FIELDS)
        or hrrr_document.get("checkpoint_schema_version")
        != hrrr_fetch.HRRR_CHECKPOINT_SCHEMA_VERSION
        or hrrr_document.get("shard_schema_version")
        != hrrr_fetch.HRRR_SHARD_SCHEMA_VERSION
        or hrrr_document.get("manifest_canonical_sha256")
        != hrrr.get("manifest_canonical_sha256")
        or hrrr_document.get("frozen_domain_sha256")
        != hrrr.get("frozen_domain_sha256")
        or hrrr_document.get("counts") != hrrr.get("counts")
        or hrrr_document.get("profile_binding") != hrrr.get("profile_binding")
        or hrrr_document.get("profile_binding_sha256")
        != hrrr.get("profile_binding_sha256")
        or (
            ACTIVE_PROFILE == "d0047_archive_available"
            and hrrr_document.get("profile_binding_sha256")
            != _json_sha256(hrrr_document.get("profile_binding"))
        )
        or hrrr_document.get("lst_opened") is not False
        or hrrr_document.get("thermal_opened") is not False
        or hrrr_document.get("record_2026_opened") is not False
        or str(hrrr_document.get("holdout_status", "")).upper() != "UNSELECTED"
    ):
        raise RuntimeError("exact HRRR run seal content is stale")
    manifest_path = _repo_path(
        hrrr_document.get("manifest_path"), label="exact HRRR manifest"
    )
    manifest_file_sha256 = hrrr_document.get("manifest_file_sha256")
    if (
        _sha256(manifest_path) != manifest_file_sha256
        or artifact_hashes.get(str(manifest_path.relative_to(ROOT)))
        != manifest_file_sha256
    ):
        raise RuntimeError("exact HRRR manifest binding is stale")
    try:
        hrrr_manifest = pd.read_csv(manifest_path)
        manifest_canonical_sha256 = hrrr_fetch.canonical_hrrr_manifest_sha256(
            hrrr_manifest
        )
    except (OSError, TypeError, ValueError):
        raise RuntimeError(
            "exact HRRR manifest violates the frozen NOAA/AWS object rule"
        ) from None
    if manifest_canonical_sha256 != hrrr_document.get(
        "manifest_canonical_sha256"
    ):
        raise RuntimeError("exact HRRR canonical manifest binding is stale")
    hrrr_counts = hrrr_document.get("counts")
    requested_city_hours = int(
        sum(len(str(value).split("|")) for value in hrrr_manifest["cities"])
    )
    if (
        not isinstance(hrrr_counts, dict)
        or hrrr_counts.get("manifest_items") != len(hrrr_manifest)
        or hrrr_counts.get("requested_city_hours") != requested_city_hours
    ):
        raise RuntimeError("exact HRRR manifest counts are stale")
    for artifact_name in ("checkpoint", "shard_index", "summary"):
        artifact = _repo_path(
            hrrr_document.get(f"{artifact_name}_path"),
            label=f"HRRR {artifact_name}",
        )
        expected_hash = hrrr_document.get(f"{artifact_name}_sha256")
        if (
            _sha256(artifact) != expected_hash
            or artifact_hashes.get(str(artifact.relative_to(ROOT))) != expected_hash
        ):
            raise RuntimeError(f"exact HRRR {artifact_name} binding is stale")
    return gate, gate_path


def load_definitive_inputs() -> dict[str, Any]:
    """Fail closed on any count, hash, geometry, or profile mismatch."""

    planning = json.loads(PLANNING.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "decision_id",
        "count_status",
        "step2_gate",
        "step2_gate_record_path",
        "step2_gate_record_sha256",
        "near_nadir_physical_passes",
        "expected_pass_equivalents_total",
        "planning_pass_count_floor",
        "template_path",
        "template_sha256",
        "hrrr_summary_sha256",
        "hrrr_run_seal_path",
        "hrrr_run_seal_sha256",
        "upstream_run_record_path",
        "upstream_run_record_sha256",
        "upstream_algorithm_version",
        "geometry_pass_summary_path",
        "geometry_pass_summary_sha256",
        "geometry_validation_path",
        "geometry_validation_sha256",
        "quality_screen_path",
        "quality_screen_sha256",
        "legacy_quality_screen_path",
        "legacy_quality_screen_sha256",
        "cloud_pass_summary_path",
        "cloud_pass_summary_sha256",
        "cloud_validation_path",
        "cloud_validation_sha256",
    }
    missing = required - set(planning)
    if missing:
        raise ValueError(f"Step-3 planning input lacks {sorted(missing)}")
    decision_id = str(planning["decision_id"]).strip()
    if int(planning["schema_version"]) != 4 or decision_id != D0035_DECISION_ID:
        raise RuntimeError("Step-3 planning input lacks a frozen remediation decision")
    if planning["count_status"] != COUNT_STATUS:
        raise RuntimeError("Step-3 planning count is not scientifically certified")
    if ACTIVE_PROFILE == "d0047_archive_available":
        d0047_required = {
            "analysis_profile",
            "scientific_gate_scope",
            "profile_scope_label",
            "original_metadata_candidate_count",
            "excluded_pre_geometry_candidate_count",
            "retained_geometry_candidate_count",
            "candidate_availability_ledger_path",
            "candidate_availability_ledger_sha256",
            "exclusion_summary_path",
            "exclusion_summary_sha256",
            "original_exhaustive_gate_status",
            "restored_archive_sensitivity_required",
        }
        missing_d0047 = d0047_required - set(planning)
        if missing_d0047:
            raise RuntimeError(f"D0047 planning lacks {sorted(missing_d0047)}")
        if (
            planning.get("analysis_profile") != ANALYSIS_PROFILE
            or planning.get("scientific_gate_scope") != SCIENTIFIC_GATE_SCOPE
            or planning.get("profile_scope_label")
            != "archive_available_after_pre_geometry_exclusion_D0047"
            or int(planning.get("original_metadata_candidate_count", -1))
            != D0047_COUNTS.original_candidates
            or int(planning.get("excluded_pre_geometry_candidate_count", -1))
            != D0047_COUNTS.excluded_candidates
            or int(planning.get("retained_geometry_candidate_count", -1))
            != D0047_COUNTS.retained_candidates
            or planning.get("original_exhaustive_gate_status")
            != "STOP_D0035_INCOMPLETE_GEOMETRY"
            or planning.get("restored_archive_sensitivity_required") is not True
        ):
            raise RuntimeError("D0047 planning profile/count/sensitivity seal is stale")
    gate_record, gate_record_path = _load_step2_gate_record(planning)
    expected_candidates = int(planning["near_nadir_physical_passes"])
    if expected_candidates <= 0:
        raise RuntimeError("Step-3 planning input has no geometry-screened candidates")

    template_path = _repo_path(planning["template_path"], label="template_path")
    template_key = str(template_path.relative_to(ROOT))
    if gate_record["artifact_sha256"].get(template_key) != planning["template_sha256"]:
        raise RuntimeError("template is absent from the exact PASS gate artifact ledger")
    geometry_path = _repo_path(
        planning["geometry_pass_summary_path"], label="geometry_pass_summary_path"
    )
    geometry_validation_path = _repo_path(
        planning["geometry_validation_path"], label="geometry_validation_path"
    )
    quality_screen_path = _repo_path(
        planning["quality_screen_path"], label="quality_screen_path"
    )
    legacy_quality_screen_path = _repo_path(
        planning["legacy_quality_screen_path"], label="legacy_quality_screen_path"
    )
    cloud_path = _repo_path(
        planning["cloud_pass_summary_path"], label="cloud_pass_summary_path"
    )
    cloud_validation_path = _repo_path(
        planning["cloud_validation_path"], label="cloud_validation_path"
    )
    hash_checks = {
        "template_sha256": (template_path, planning["template_sha256"]),
        "geometry_pass_summary_sha256": (
            geometry_path,
            planning["geometry_pass_summary_sha256"],
        ),
        "geometry_validation_sha256": (
            geometry_validation_path,
            planning["geometry_validation_sha256"],
        ),
        "quality_screen_sha256": (
            quality_screen_path,
            planning["quality_screen_sha256"],
        ),
        "legacy_quality_screen_sha256": (
            legacy_quality_screen_path,
            planning["legacy_quality_screen_sha256"],
        ),
        "cloud_pass_summary_sha256": (
            cloud_path,
            planning["cloud_pass_summary_sha256"],
        ),
        "cloud_validation_sha256": (
            cloud_validation_path,
            planning["cloud_validation_sha256"],
        ),
    }
    for label, (path, expected) in hash_checks.items():
        if _sha256(path) != expected:
            raise RuntimeError(f"{label} does not match its planning checksum")
    archive_ledger = None
    archive_exclusions = None
    if ACTIVE_PROFILE == "d0047_archive_available":
        archive_ledger_path = _repo_path(
            planning["candidate_availability_ledger_path"],
            label="D0047 candidate availability ledger",
        )
        archive_exclusions_path = _repo_path(
            planning["exclusion_summary_path"],
            label="D0047 pre-geometry exclusion ledger",
        )
        if (
            _sha256(archive_ledger_path)
            != planning["candidate_availability_ledger_sha256"]
            or _sha256(archive_exclusions_path)
            != planning["exclusion_summary_sha256"]
            or gate_record["artifact_sha256"].get(
                str(archive_ledger_path.relative_to(ROOT))
            )
            != planning["candidate_availability_ledger_sha256"]
            or gate_record["artifact_sha256"].get(
                str(archive_exclusions_path.relative_to(ROOT))
            )
            != planning["exclusion_summary_sha256"]
        ):
            raise RuntimeError("D0047 full/exclusion ledger hash binding is stale")
        archive_ledger = pd.read_csv(archive_ledger_path)
        archive_exclusions = pd.read_csv(archive_exclusions_path)
        required_availability = {
            "city",
            "orbit",
            D0047_STATUS_COLUMN,
            D0047_INCLUDED_COLUMN,
        }
        if required_availability - set(archive_ledger.columns):
            raise RuntimeError("D0047 candidate ledger lacks availability fields")
        included = _true_series(
            archive_ledger[D0047_INCLUDED_COLUMN],
            label="D0047 candidate-ledger inclusion flag",
        )
        exclusion_required = {
            "city",
            "orbit",
            D0047_STATUS_COLUMN,
            D0047_INCLUDED_COLUMN,
        }
        if exclusion_required - set(archive_exclusions.columns):
            raise RuntimeError("D0047 exclusion ledger lacks availability fields")
        exclusion_included = _true_series(
            archive_exclusions[D0047_INCLUDED_COLUMN],
            label="D0047 exclusion-ledger inclusion flag",
        )
        ledger_exclusion_keys = set(
            archive_ledger.loc[~included, ["city", "orbit"]].itertuples(
                index=False, name=None
            )
        )
        exclusion_keys = set(
            archive_exclusions[["city", "orbit"]].itertuples(index=False, name=None)
        )
        if (
            len(archive_ledger) != D0047_COUNTS.original_candidates
            or archive_ledger.duplicated(["city", "orbit"]).any()
            or int(included.sum()) != D0047_COUNTS.retained_candidates
            or int((~included).sum()) != D0047_COUNTS.excluded_candidates
            or not archive_ledger.loc[included, D0047_STATUS_COLUMN]
            .astype(str)
            .eq(D0047_RETAINED_STATUS)
            .all()
            or not archive_ledger.loc[~included, D0047_STATUS_COLUMN]
            .astype(str)
            .eq(D0047_EXCLUDED_STATUS)
            .all()
            or len(archive_exclusions) != D0047_COUNTS.excluded_candidates
            or archive_exclusions.duplicated(["city", "orbit"]).any()
            or exclusion_included.any()
            or not archive_exclusions[D0047_STATUS_COLUMN]
            .astype(str)
            .eq(D0047_EXCLUDED_STATUS)
            .all()
            or exclusion_keys != ledger_exclusion_keys
        ):
            raise RuntimeError("D0047 full/exclusion ledger census is stale")
    geometry_gate = json.loads(geometry_validation_path.read_text(encoding="utf-8"))
    geometry_counts = {
        "expected_metadata_candidates": EXPECTED_METADATA_CANDIDATES,
        "resolved_geometry_candidate_count": EXPECTED_METADATA_CANDIDATES,
        "definitive_geometry_status_count": EXPECTED_METADATA_CANDIDATES,
        "unresolved_geometry_candidate_count": 0,
    }
    if (
        str(geometry_gate.get("decision_id", "")) != D0035_DECISION_ID
        or str(geometry_gate.get("geometry_source", "")) != D0035_GEOMETRY_SOURCE
        or geometry_gate.get("geometry_complete") is not True
        or geometry_gate.get("candidate_seal_geometry_only") is not True
        or any(int(geometry_gate.get(field, -1)) != expected for field, expected in geometry_counts.items())
    ):
        raise RuntimeError("definitive Step 3 is blocked by the D0035 geometry seal")
    if ACTIVE_PROFILE == "d0047_archive_available" and (
        geometry_gate.get("analysis_profile") != ANALYSIS_PROFILE
        or geometry_gate.get("scientific_gate_scope") != SCIENTIFIC_GATE_SCOPE
        or int(geometry_gate.get("original_metadata_candidate_count", -1))
        != D0047_COUNTS.original_candidates
        or int(geometry_gate.get("excluded_pre_geometry_candidate_count", -1))
        != D0047_COUNTS.excluded_candidates
        or int(geometry_gate.get("retained_geometry_candidate_count", -1))
        != D0047_COUNTS.retained_candidates
        or int(geometry_gate.get("excluded_geometry_metric_null_row_count", -1))
        != D0047_COUNTS.excluded_candidates
        or geometry_gate.get("excluded_geometry_nonnull_columns") != []
        or geometry_gate.get("missing_scene_imputation_used") is not False
        or geometry_gate.get("missing_scene_zero_coverage_assigned") is not False
        or geometry_gate.get("adjacent_scene_substitution_used") is not False
    ):
        raise RuntimeError("D0047 geometry seal lacks its scoped null-exclusion census")
    geometry_passing = int(geometry_gate.get("geometry_passing_candidate_count", -1))
    if geometry_passing != expected_candidates:
        raise RuntimeError("Step-3 candidate count disagrees with the D0035 geometry seal")
    geometry_summary = pd.read_csv(geometry_path)
    quality_screen = pd.read_csv(quality_screen_path)
    if ACTIVE_PROFILE == "d0047_archive_available":
        availability_columns = {
            D0047_STATUS_COLUMN,
            D0047_INCLUDED_COLUMN,
            "city",
            "orbit",
        }
        if (
            availability_columns - set(geometry_summary.columns)
            or availability_columns - set(quality_screen.columns)
            or len(geometry_summary) != D0047_COUNTS.original_candidates
            or len(quality_screen) != D0047_COUNTS.original_candidates
        ):
            raise RuntimeError("D0047 geometry/quality provenance lost the 942-row ledger")
        geometry_included = _true_series(
            geometry_summary[D0047_INCLUDED_COLUMN],
            label="D0047 geometry inclusion flag",
        )
        quality_included = _true_series(
            quality_screen[D0047_INCLUDED_COLUMN],
            label="D0047 quality inclusion flag",
        )
        for frame, included_mask, label in (
            (geometry_summary, geometry_included, "geometry"),
            (quality_screen, quality_included, "quality"),
        ):
            expected_status = included_mask.map(
                {
                    True: D0047_RETAINED_STATUS,
                    False: D0047_EXCLUDED_STATUS,
                }
            )
            if not frame[D0047_STATUS_COLUMN].astype(str).equals(expected_status):
                raise RuntimeError(f"D0047 {label} availability status is stale")
        geometry_excluded = geometry_summary.loc[~geometry_included]
        quality_excluded = quality_screen.loc[~quality_included]
        excluded_metric_columns = [
            "l1b_geometry_covered_cells",
            "l1b_geometry_domain_cells",
            "l1b_geometry_coverage_fraction",
            "l1b_view_zenith_abs_p95_deg",
            "l1b_geometry_complete",
        ]
        excluded_flag_columns = [
            "quality_candidate_pre_cloud",
            "quality_candidate_pre_cloud_l1b",
            "quality_candidate_pre_cloud_l2t_invalid",
        ]
        excluded_contract_columns = {
            *excluded_metric_columns,
            *excluded_flag_columns,
            "l1b_geometry_status",
        }
        if (
            excluded_contract_columns - set(geometry_summary.columns)
            or excluded_contract_columns - set(quality_screen.columns)
        ):
            raise RuntimeError("D0047 excluded-row null contract lacks required fields")
        if (
            int(geometry_included.sum()) != D0047_COUNTS.retained_candidates
            or int(quality_included.sum()) != D0047_COUNTS.retained_candidates
            or not geometry_excluded[excluded_metric_columns].isna().all(axis=None)
            or not quality_excluded[excluded_metric_columns].isna().all(axis=None)
            or any(
                _nullable_true_series(
                    geometry_excluded[column],
                    label=f"D0047 excluded geometry {column}",
                ).notna().any()
                for column in excluded_flag_columns
            )
            or any(
                _nullable_true_series(
                    quality_excluded[column],
                    label=f"D0047 excluded quality {column}",
                ).notna().any()
                for column in excluded_flag_columns
            )
            or not geometry_excluded["l1b_geometry_status"]
            .astype(str)
            .eq(D0047_EXCLUDED_STATUS)
            .all()
            or not quality_excluded["l1b_geometry_status"]
            .astype(str)
            .eq(D0047_EXCLUDED_STATUS)
            .all()
        ):
            raise RuntimeError("D0047 excluded rows contain geometry results")
        ledger_keys = set(
            archive_ledger[["city", "orbit"]].itertuples(index=False, name=None)
        )
        geometry_keys = set(
            geometry_summary[["city", "orbit"]].itertuples(index=False, name=None)
        )
        quality_keys = set(
            quality_screen[["city", "orbit"]].itertuples(index=False, name=None)
        )
        exclusion_keys = set(
            archive_exclusions[["city", "orbit"]].itertuples(index=False, name=None)
        )
        observed_excluded_keys = set(
            geometry_excluded[["city", "orbit"]].itertuples(index=False, name=None)
        )
        observed_quality_excluded_keys = set(
            quality_excluded[["city", "orbit"]].itertuples(index=False, name=None)
        )
        if (
            ledger_keys != geometry_keys
            or ledger_keys != quality_keys
            or geometry_summary.duplicated(["city", "orbit"]).any()
            or quality_screen.duplicated(["city", "orbit"]).any()
            or exclusion_keys != observed_excluded_keys
            or exclusion_keys != observed_quality_excluded_keys
        ):
            raise RuntimeError("D0047 geometry keys differ from the bound attrition ledgers")
        geometry_summary = geometry_summary.loc[geometry_included].copy()
        quality_screen = quality_screen.loc[quality_included].copy()
    if (
        len(geometry_summary) != EXPECTED_METADATA_CANDIDATES
        or len(quality_screen) != EXPECTED_METADATA_CANDIDATES
    ):
        raise RuntimeError("Step-3 provenance does not preserve all 942 geometry records")
    geometry_required = {
        "l1b_geometry_covered_cells",
        "l1b_geometry_domain_cells",
        "l1b_geometry_coverage_fraction",
        "l1b_view_zenith_abs_p95_deg",
        "l1b_geometry_complete",
        "l1b_geometry_status",
        "quality_candidate_pre_cloud",
        "quality_candidate_pre_cloud_l1b",
        "quality_candidate_pre_cloud_l2t_invalid",
    }
    if geometry_required - set(geometry_summary.columns):
        raise RuntimeError("Step-3 geometry provenance lacks definitive row statuses")
    geometry_definitive = (
        geometry_summary["l1b_geometry_complete"]
        .astype(str)
        .str.strip()
        .str.casefold()
    )
    geometry_candidates = (
        geometry_summary["quality_candidate_pre_cloud_l1b"]
        .astype(str)
        .str.strip()
        .str.casefold()
    )
    canonical_candidates = (
        geometry_summary["quality_candidate_pre_cloud"]
        .astype(str)
        .str.strip()
        .str.casefold()
    )
    geometry_status = geometry_summary["l1b_geometry_status"].astype(str)
    allowed_geometry_statuses = {
        "geometry_pass",
        "coverage_fail",
        "angle_fail",
        "coverage_and_angle_fail",
    }
    covered = pd.to_numeric(
        geometry_summary["l1b_geometry_covered_cells"], errors="coerce"
    )
    denominator = pd.to_numeric(
        geometry_summary["l1b_geometry_domain_cells"], errors="coerce"
    )
    coverage = pd.to_numeric(
        geometry_summary["l1b_geometry_coverage_fraction"], errors="coerce"
    )
    p95 = pd.to_numeric(
        geometry_summary["l1b_view_zenith_abs_p95_deg"], errors="coerce"
    )
    coverage_pass = coverage.ge(0.95)
    angle_pass = p95.notna() & p95.ge(0.0) & p95.le(20.0)
    expected_status = pd.Series(
        np.select(
            [
                coverage_pass & angle_pass,
                ~coverage_pass & angle_pass,
                coverage_pass & ~angle_pass,
            ],
            ["geometry_pass", "coverage_fail", "angle_fail"],
            default="coverage_and_angle_fail",
        ),
        index=geometry_summary.index,
    )
    if (
        not geometry_definitive.isin({"true", "1"}).all()
        or not geometry_candidates.isin({"true", "false", "1", "0"}).all()
        or not geometry_candidates.equals(canonical_candidates)
        or not geometry_status.isin(allowed_geometry_statuses).all()
        or covered.isna().any()
        or denominator.isna().any()
        or coverage.isna().any()
        or (covered < 0).any()
        or (denominator <= 0).any()
        or (covered > denominator).any()
        or not np.equal(covered, np.floor(covered)).all()
        or not np.equal(denominator, np.floor(denominator)).all()
        or not bool(coverage.between(0.0, 1.0).all())
        or ((covered == 0) != p95.isna()).any()
        or (p95.dropna() < 0).any()
        or not np.allclose(
            coverage.to_numpy(float),
            (covered / denominator).to_numpy(float),
            rtol=0,
            atol=1e-12,
        )
        or int(geometry_candidates.isin({"true", "1"}).sum())
        != expected_candidates
        or not geometry_candidates.isin({"true", "1"}).equals(
            geometry_status.eq("geometry_pass")
        )
        or not geometry_status.equals(expected_status)
    ):
        raise RuntimeError("Step-3 geometry provenance is not a definitive D0035 seal")
    candidate_columns = {
        "quality_candidate_pre_cloud",
        "quality_candidate_pre_cloud_l1b",
        "quality_candidate_pre_cloud_l2t_invalid",
    }
    if candidate_columns - set(quality_screen.columns):
        raise RuntimeError("Step-3 quality provenance lacks the D0035 candidate flag")
    candidate_values = (
        quality_screen["quality_candidate_pre_cloud_l1b"]
        .astype(str)
        .str.strip()
        .str.casefold()
    )
    canonical_values = (
        quality_screen["quality_candidate_pre_cloud"]
        .astype(str)
        .str.strip()
        .str.casefold()
    )
    if (
        not candidate_values.isin({"true", "false", "1", "0"}).all()
        or not candidate_values.equals(canonical_values)
        or int(candidate_values.isin({"true", "1"}).sum()) != expected_candidates
    ):
        raise RuntimeError("Step-3 quality provenance disagrees with the D0035 count")
    cloud_gate = json.loads(cloud_validation_path.read_text(encoding="utf-8"))
    if ACTIVE_PROFILE == "d0047_archive_available" and (
        cloud_gate.get("analysis_profile") != ANALYSIS_PROFILE
        or cloud_gate.get("scientific_gate_scope") != SCIENTIFIC_GATE_SCOPE
        or int(cloud_gate.get("original_metadata_candidate_count", -1))
        != D0047_COUNTS.original_candidates
        or int(cloud_gate.get("excluded_pre_geometry_candidate_count", -1))
        != D0047_COUNTS.excluded_candidates
        or int(cloud_gate.get("retained_geometry_candidate_count", -1))
        != D0047_COUNTS.retained_candidates
    ):
        raise RuntimeError("D0047 cloud gate lacks the archive-available scope/count seal")
    if (
        str(cloud_gate.get("decision_id", "")) != D0035_DECISION_ID
        or str(cloud_gate.get("geometry_source", "")) != D0035_GEOMETRY_SOURCE
        or int(cloud_gate.get("expected_metadata_candidates", -1))
        != EXPECTED_METADATA_CANDIDATES
        or int(cloud_gate.get("resolved_geometry_candidate_count", -1))
        != EXPECTED_METADATA_CANDIDATES
        or int(cloud_gate.get("definitive_geometry_status_count", -1))
        != EXPECTED_METADATA_CANDIDATES
        or int(cloud_gate.get("unresolved_geometry_candidate_count", -1)) != 0
        or int(cloud_gate.get("geometry_passing_candidate_count", -1))
        != expected_candidates
        or int(cloud_gate.get("expected_cloud_candidates", -1))
        != expected_candidates
        or int(cloud_gate.get("resolved_cloud_candidate_count", -1))
        != expected_candidates
        or int(cloud_gate.get("finite_cloud_fraction_count", -1))
        != expected_candidates
        or cloud_gate.get("geometry_complete") is not True
        or cloud_gate.get("cloud_complete") is not True
        or cloud_gate.get("combined_complete") is not True
        or cloud_gate.get("scientific_gate_eligible") is not True
        or cloud_gate.get("candidate_seal_geometry_only") is not True
        or cloud_gate.get("candidate_view_mask_cloud_independent") is not True
        or cloud_gate.get("view_gate_cloud_conditioned") is not False
        or cloud_gate.get("cloud_extrapolation_used") is not False
        or cloud_gate.get("canonical_status") != D0035_PASS_STATUS
        or cloud_gate.get("gate_status") != D0035_PASS_STATUS
    ):
        status = cloud_gate.get(
            "gate_status", cloud_gate.get("canonical_status", "not_gate_eligible")
        )
        raise RuntimeError(f"definitive Step 3 is blocked by cloud gate {status}")
    if (
        cloud_gate.get("lst_opened") is not False
        or cloud_gate.get("thermal_opened") is not False
        or cloud_gate.get("record_2026_opened") is not False
        or str(cloud_gate.get("holdout_status", "")).upper() != "UNSELECTED"
        or str(cloud_gate.get("frozen_years", "")) != "2018-2025"
    ):
        raise RuntimeError("D0035 thermal/2026/holdout seals are not intact")
    if (
        not np.isclose(
            float(planning["expected_pass_equivalents_total"]),
            float(cloud_gate.get("planning_pass_equivalent_sum", np.nan)),
            rtol=0,
            atol=1e-10,
        )
        or int(planning["planning_pass_count_floor"])
        != int(cloud_gate.get("planning_pass_equivalent_floor", -1))
    ):
        raise RuntimeError("Step-3 planning count disagrees with the combined D0035 gate")
    # The summary is intentionally resolved from the Step-2 raw provenance,
    # not guessed from the template.  Its D0035 path is separate from R0002.
    hrrr_relative = (
        "hrrr_exact_acquisition_l1b_geo_D0047_archive_available"
        if ACTIVE_PROFILE == "d0047_archive_available"
        else "hrrr_exact_acquisition_l1b_geo"
    )
    hrrr_summary = (
        ROOT / "data/raw/v2/weather" / hrrr_relative / "hrrr_hourly_domain_summary.csv"
    )
    if (
        not hrrr_summary.is_file()
        or _sha256(hrrr_summary) != planning["hrrr_summary_sha256"]
        or gate_record["artifact_sha256"].get(str(hrrr_summary.relative_to(ROOT)))
        != planning["hrrr_summary_sha256"]
    ):
        raise RuntimeError("exact-acquisition HRRR summary is absent or changed")

    raw_template = pd.read_csv(template_path)
    template = validate_template(raw_template)
    if len(template) != expected_candidates:
        raise RuntimeError(
            "empirical Step-3 template does not contain every geometry-screened candidate"
        )
    if set(template["template_geometry_status"].astype(str)) != {
        OBSERVED_GEOMETRY_STATUS
    }:
        raise RuntimeError("definitive template lacks observed solar geometry")
    if "sampling_weight" not in template:
        raise RuntimeError("definitive template lacks candidate-specific sampling weights")
    weight_sum = float(template["sampling_weight"].sum())
    expected_total = float(planning["expected_pass_equivalents_total"])
    actual_count = int(planning["planning_pass_count_floor"])
    if (
        not np.isclose(weight_sum, expected_total, rtol=0, atol=1e-10)
        or math.floor(weight_sum) != actual_count
    ):
        raise RuntimeError("template weights disagree with the certified planning count")
    if actual_count < 5:
        raise RuntimeError("certified planning count is below the simulator minimum of five")

    config = load_config(CONFIG)
    spec = SimulationSpec.from_mapping(config.simulation)
    thresholds = DiagnosticThresholds.from_mapping(config.simulation)
    spec.validate()
    thresholds.validate()
    pass_counts = tuple(int(value) for value in config.simulation["planning_pass_counts"])
    settings = {
        "n_replicates": int(config.simulation["full_power_replicates"]),
        "n_coverage_replicates": int(
            config.simulation["full_coverage_replicates"]
        ),
        "n_boot": int(config.simulation["full_bootstrap_replicates"]),
    }
    if (
        pass_counts != (50, 100, 200, 400, 800)
        or settings != {
            "n_replicates": 200,
            "n_coverage_replicates": 60,
            "n_boot": 120,
        }
    ):
        raise RuntimeError("full Step-3 profile differs from frozen D0021/D0027")
    validation = {
        "decision_ids": _step3_decision_ids(decision_id),
        "analysis_profile": ANALYSIS_PROFILE,
        "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
        "actual_n_passes": actual_count,
        "count_status": planning["count_status"],
        "step2_gate": gate_record["status"],
        "step2_gate_record_sha256": _sha256(gate_record_path),
        "hrrr_run_seal_sha256": planning["hrrr_run_seal_sha256"],
        "template_rows": int(len(template)),
        "template_sampling_weight_sum": weight_sum,
        "zero_weight_template_rows": int(template["sampling_weight"].eq(0).sum()),
        "template_sha256": _sha256(template_path),
        "planning_sha256": _sha256(PLANNING),
        "config_sha256": _sha256(CONFIG),
        "hrrr_summary_sha256": _sha256(hrrr_summary),
        "pass_counts": list(pass_counts),
        **settings,
        "simulation_spec": asdict(spec),
        "diagnostic_thresholds": asdict(thresholds),
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
        "status": "ready_for_frozen_full_profile",
    }
    return {
        "planning": planning,
        "template": template,
        "template_path": template_path,
        "hrrr_summary": hrrr_summary,
        "spec": spec,
        "thresholds": thresholds,
        "pass_counts": pass_counts,
        "settings": settings,
        "validation": validation,
    }


def run_definitive() -> dict[str, Path]:
    inputs = load_definitive_inputs()
    if OUTPUT.exists():
        raise FileExistsError(
            f"Definitive Step-3 output already exists; refusing to overwrite {OUTPUT}"
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".step3-definitive-staging-", dir=OUTPUT.parent)
    )
    try:
        results = run_simulation_study(
            actual_n_passes=inputs["validation"]["actual_n_passes"],
            pass_counts=inputs["pass_counts"],
            spec=inputs["spec"],
            template=inputs["template"],
            count_status=inputs["planning"]["count_status"],
            template_status=(
                "cloud_independent_geometry_candidate_specific_"
                "exact_acquisition_conditions"
            ),
            **inputs["settings"],
        )
        paths = write_step3_deliverables(
            results,
            staging,
            diagnostic_thresholds=inputs["thresholds"],
        )
        run_record = dict(inputs["validation"])
        run_record["step3_module_sha256"] = _sha256(
            ROOT / "src/urban_cooling_v2/step03_power.py"
        )
        run_record["runner_sha256"] = _sha256(Path(__file__).resolve())
        run_record["diagnostic_gate"] = json.loads(
            (staging / "step3_diagnostic_gate.json").read_text(encoding="utf-8")
        )
        (staging / "run_record.json").write_text(
            json.dumps(run_record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        required = {
            "F3.1",
            "F3.2",
            "F3.3",
            "F3.4",
            "F3.5",
            "T3.1",
            "M3.1",
            "diagnostic_checks",
            "diagnostic_gate",
            "provenance",
        }
        missing = required - set(paths)
        if missing or any(not paths[name].is_file() for name in required):
            raise RuntimeError(f"Step-3 staging validation failed: {sorted(missing)}")
        staging.replace(OUTPUT)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {name: OUTPUT / path.relative_to(staging) for name, path in paths.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        choices=("d0035_exhaustive", "d0047_archive_available"),
        default="d0035_exhaustive",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-inputs")
    subparsers.add_parser("run")
    args = parser.parse_args()
    configure_profile(args.profile)
    if args.command == "validate-inputs":
        inputs = load_definitive_inputs()
        print(json.dumps(inputs["validation"], indent=2, sort_keys=True))
    else:
        paths = run_definitive()
        gate = json.loads(paths["diagnostic_gate"].read_text(encoding="utf-8"))
        print(json.dumps({"output": str(OUTPUT), "diagnostic_gate": gate}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
