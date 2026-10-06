"""Canonical, filesystem-bound Task 1 PASS writer and validator.

The Task 2 coordinator must not trust a JSON document merely because it says
``PASS``.  This module binds that claim either to the original complete D0035
chain or to the separately scoped D0047 archive-available chain, followed by
exact HRRR and definitive D0027 evidence.  Validation is local and read-only:
it opens only named metadata/CSV artifacts and never opens an LST/thermal
raster, selects a holdout, contacts a network service, or reads a 2026 record.
"""

from __future__ import annotations

from collections.abc import Mapping
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any
import uuid


REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_TASK1_GATE_SCHEMA_VERSION = 2
CANONICAL_TASK1_GATE_STATUS = "PASS"
D0047_CANONICAL_TASK1_GATE_SCHEMA_VERSION = 3
D0035_DECISION_ID = "D0035"
D0027_DECISION_ID = "D0027"
D0035_PASS_STATUS = "PASS_D0035_GEOMETRY_AND_EXHAUSTIVE_CLOUD"
HRRR_PASS_STATUS = "PASS_EXACT_HRRR_RUN_SEAL"
CERTIFIED_COUNT_STATUS = "certified_expected_pass_equivalent_floor"

D0035_PROFILE = "d0035_exhaustive"
D0047_PROFILE = "d0047_archive_available"
D0047_ANALYSIS_PROFILE = "D0047_archive_available"
D0047_DECISION_ID = "D0047"
D0047_PASS_STATUS = "PASS_D0047_ARCHIVE_AVAILABLE_GEOMETRY_AND_EXHAUSTIVE_CLOUD"
D0047_HRRR_PASS_STATUS = "PASS_EXACT_HRRR_RUN_SEAL_D0047_ARCHIVE_AVAILABLE"
D0047_CERTIFIED_COUNT_STATUS = (
    "certified_archive_available_expected_pass_equivalent_floor"
)
D0047_PROFILE_GATE_STATUS = "PASS_D0047_ARCHIVE_AVAILABLE_TASK1"
D0047_SCIENTIFIC_GATE_SCOPE = "archive_available_only"
D0047_PROFILE_SCOPE_LABEL = "archive_available_after_pre_geometry_exclusion_D0047"
D0047_ESTIMAND = "2018-2025 five-city archive-available candidate population"
D0047_ORIGINAL_CANDIDATES = 942
D0047_EXCLUDED_CANDIDATES = 31
D0047_RETAINED_CANDIDATES = 911
D0047_RETAINED_CITY_SCENE_LINKS = 1355
D0047_RETAINED_UNIQUE_SCENES = 1323
D0047_ORIGINAL_STOP = "STOP_D0035_INCOMPLETE_GEOMETRY"
D0047_LATEST_UNAVAILABILITY_STOP = "STOP_D0046_DIRECT_DOWNLOADS_INCOMPLETE"
D0047_RETAINED_STATUS = "retained_archive_available"
D0047_EXCLUDED_STATUS = "archive_unavailable_pre_geometry"
D0047_PROFILE_SEAL_STATUS = "PASS_D0047_ARCHIVE_AVAILABLE_PROFILE_SEALED"
D0047_ALGORITHM_VERSION = "d0047-archive-available-l1b-dmrpp-pass-stream-v1"
D0047_EXCLUDED_BY_CITY = {
    "atlanta": 8,
    "los_angeles": 8,
    "miami": 1,
    "minneapolis_st_paul": 8,
    "phoenix": 6,
}
D0047_ORIGINAL_BY_CITY = {
    "atlanta": 196,
    "los_angeles": 196,
    "miami": 91,
    "minneapolis_st_paul": 266,
    "phoenix": 193,
}
D0047_RETAINED_BY_CITY = {
    "atlanta": 188,
    "los_angeles": 188,
    "miami": 90,
    "minneapolis_st_paul": 258,
    "phoenix": 187,
}

REQUIRED_ARTIFACT_NAMES = (
    "d0035_combined_validation",
    "d0035_run_record",
    "step2_gate",
    "hrrr_run_seal",
    "hrrr_manifest",
    "hrrr_shard_index",
    "hrrr_summary",
    "step3_run_record",
    "step3_diagnostic_gate",
    "t3_model_support",
)

DEFAULT_TASK1_ARTIFACT_PATHS = {
    "d0035_combined_validation": (
        "data/processed/v2/task1/step2_quality_screening_l1b_geo/"
        "combined_validation.json"
    ),
    "d0035_run_record": (
        "data/processed/v2/task1/step2_quality_screening_l1b_geo/run_record.json"
    ),
    "step2_gate": (
        "data/processed/v2/task1/step2_definitive_l1b_geo/step2_gate_record.json"
    ),
    "hrrr_run_seal": (
        "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo/hrrr_run_seal.json"
    ),
    "hrrr_manifest": (
        "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo_manifest.csv"
    ),
    "hrrr_shard_index": (
        "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo/"
        "hrrr_hourly_shard_index.csv"
    ),
    "hrrr_summary": (
        "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo/"
        "hrrr_hourly_domain_summary.csv"
    ),
    "step3_run_record": (
        "data/processed/v2/task1/step3_definitive_l1b_geo/run_record.json"
    ),
    "step3_diagnostic_gate": (
        "data/processed/v2/task1/step3_definitive_l1b_geo/"
        "step3_diagnostic_gate.json"
    ),
    "t3_model_support": (
        "data/processed/v2/task1/step3_definitive_l1b_geo/"
        "tables/T3.1_model_support.csv"
    ),
}

D0047_REQUIRED_ARTIFACT_NAMES = (
    "d0035_exhaustive_stop_combined_validation",
    "d0035_exhaustive_stop_run_record",
    "d0046_direct_download_probe",
    "d0046_direct_download_controls",
    "d0046_direct_download_validation",
    "d0046_direct_download_run_record",
    "d0047_profile_validation",
    "d0047_combined_validation",
    "d0047_run_record",
    "candidate_availability_ledger",
    "archive_unavailable_pre_geometry_exclusions",
    "archive_available_attrition_summary",
    "retained_city_scene_links",
    "step2_gate",
    "hrrr_run_seal",
    "hrrr_manifest",
    "hrrr_shard_index",
    "hrrr_summary",
    "step3_run_record",
    "step3_diagnostic_gate",
    "t3_model_support",
)

D0047_TASK1_ARTIFACT_PATHS = {
    "d0035_exhaustive_stop_combined_validation": (
        "data/processed/v2/task1/step2_quality_screening_l1b_geo/"
        "combined_validation.json"
    ),
    "d0035_exhaustive_stop_run_record": (
        "data/processed/v2/task1/step2_quality_screening_l1b_geo/run_record.json"
    ),
    "d0046_direct_download_probe": (
        "data/processed/v2/task1/step2_l1b_repeat_retry_D0046/"
        "direct_download_probe.csv"
    ),
    "d0046_direct_download_controls": (
        "data/processed/v2/task1/step2_l1b_repeat_retry_D0046/"
        "direct_download_controls.json"
    ),
    "d0046_direct_download_validation": (
        "data/processed/v2/task1/step2_l1b_repeat_retry_D0046/"
        "direct_download_validation.json"
    ),
    "d0046_direct_download_run_record": (
        "data/processed/v2/task1/step2_l1b_repeat_retry_D0046/"
        "direct_download_run_record.json"
    ),
    "d0047_profile_validation": (
        "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/"
        "profile_validation.json"
    ),
    "d0047_combined_validation": (
        "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/"
        "combined_validation.json"
    ),
    "d0047_run_record": (
        "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/"
        "run_record.json"
    ),
    "candidate_availability_ledger": (
        "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/"
        "candidate_availability_ledger.csv"
    ),
    "archive_unavailable_pre_geometry_exclusions": (
        "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/"
        "archive_unavailable_pre_geometry_exclusions.csv"
    ),
    "archive_available_attrition_summary": (
        "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/"
        "archive_available_attrition_summary.csv"
    ),
    "retained_city_scene_links": (
        "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/"
        "retained_city_scene_links.csv"
    ),
    "step2_gate": (
        "data/processed/v2/task1/step2_definitive_l1b_geo_D0047_archive_available/"
        "step2_gate_record.json"
    ),
    "hrrr_run_seal": (
        "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo_D0047_archive_available/"
        "hrrr_run_seal.json"
    ),
    "hrrr_manifest": (
        "data/raw/v2/weather/"
        "hrrr_exact_acquisition_l1b_geo_D0047_archive_available_manifest.csv"
    ),
    "hrrr_shard_index": (
        "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo_D0047_archive_available/"
        "hrrr_hourly_shard_index.csv"
    ),
    "hrrr_summary": (
        "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo_D0047_archive_available/"
        "hrrr_hourly_domain_summary.csv"
    ),
    "step3_run_record": (
        "data/processed/v2/task1/step3_definitive_l1b_geo_D0047_archive_available/"
        "run_record.json"
    ),
    "step3_diagnostic_gate": (
        "data/processed/v2/task1/step3_definitive_l1b_geo_D0047_archive_available/"
        "step3_diagnostic_gate.json"
    ),
    "t3_model_support": (
        "data/processed/v2/task1/step3_definitive_l1b_geo_D0047_archive_available/"
        "tables/T3.1_model_support.csv"
    ),
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HRRR_MANIFEST_FIELDS = (
    "item_id",
    "analysis_utc",
    "cities",
    "n_target_passes",
    "model",
    "product",
    "forecast_hour",
    "variable_search",
    "source",
    "object_key",
)
_HRRR_SOURCE = "NOAA HRRR public AWS archive; surface analysis f00"
_D0053_HRRR_MANIFEST_FIELDS = (*_HRRR_MANIFEST_FIELDS, "product_resolution")
_D0053_HRRR_SOURCE = (
    "NOAA HRRR public AWS archive; exact analysis f00 2-m fields; "
    "sfc with frozen prs fallback"
)
_D0053_HRRR_FALLBACK_HOURS = frozenset(
    {
        "20180728T23Z",
        "20180802T23Z",
        "20180807T19Z",
        "20180815T23Z",
    }
)
_D0053_HRRR_PRIMARY_RESOLUTION = "primary_sfc"
_D0053_HRRR_FALLBACK_RESOLUTION = (
    "frozen_prs_fallback_for_missing_official_sfc_object"
)
_D0053_HRRR_MANIFEST_ITEMS = 413
_D0053_HRRR_PRIMARY_ITEMS = 409
_D0053_HRRR_FALLBACK_ITEMS = 4
_HRRR_SEARCH = r":(?:TMP|DPT):2 m"
_HRRR_HTTPS_ROOT = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com"


class Task1GateError(ValueError):
    """Raised when a claimed Task 1 PASS cannot be independently proven."""


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fail(detail: str) -> None:
    raise Task1GateError(detail)


def _json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        _fail(f"{label} is not a readable JSON object")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _int(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        _fail(f"{label} must be an integer")
    try:
        converted = int(value)
    except (TypeError, ValueError):
        _fail(f"{label} must be an integer")
    if str(value).strip() not in {str(converted), f"{converted}.0"}:
        _fail(f"{label} must be an exact integer")
    return converted


def _float(value: Any, *, label: str) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        _fail(f"{label} must be numeric")
    if not math.isfinite(converted):
        _fail(f"{label} must be finite")
    return converted


def _boolean_text(value: Any, *, label: str) -> bool:
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    _fail(f"{label} must be true or false")


def _require_sha256(value: Any, *, label: str) -> str:
    text = str(value)
    if not _SHA256_RE.fullmatch(text):
        _fail(f"{label} must be a lowercase SHA-256 digest")
    return text


def _inside_repo(
    value: str | os.PathLike[str],
    *,
    repo_root: Path,
    label: str,
    require_relative: bool,
    require_file: bool = True,
) -> Path:
    text = str(value).strip()
    if not text or "\\" in text:
        _fail(f"{label} must be a non-empty canonical repository path")
    supplied = Path(text)
    if require_relative and supplied.is_absolute():
        _fail(f"{label} must be repository-relative")
    if require_relative and supplied.as_posix() != text:
        _fail(f"{label} is not a canonical repository-relative path")
    candidate = supplied if supplied.is_absolute() else repo_root / supplied
    resolved = candidate.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        _fail(f"{label} escapes the repository")
    if require_file and not resolved.is_file():
        _fail(f"{label} does not identify an existing file")
    return resolved


def _binding_paths(
    gate: Mapping[str, Any],
    *,
    repo_root: Path,
    gate_path: Path,
    required_artifact_names: tuple[str, ...] = REQUIRED_ARTIFACT_NAMES,
) -> dict[str, Path]:
    artifacts = gate.get("artifacts")
    if not isinstance(artifacts, Mapping):
        _fail("canonical Task 1 gate artifacts must be an object")
    actual_names = set(map(str, artifacts))
    required_names = set(required_artifact_names)
    if actual_names != required_names:
        _fail(
            "canonical Task 1 artifact set differs from the frozen schema: "
            f"missing={sorted(required_names - actual_names)}, "
            f"unexpected={sorted(actual_names - required_names)}"
        )
    resolved_gate = gate_path.resolve()
    output: dict[str, Path] = {}
    seen: set[Path] = set()
    for name in required_artifact_names:
        binding = artifacts.get(name)
        if not isinstance(binding, Mapping) or set(binding) != {"path", "sha256"}:
            _fail(f"artifact {name} must contain exactly path and sha256")
        path = _inside_repo(
            binding.get("path", ""),
            repo_root=repo_root,
            label=f"artifact {name} path",
            require_relative=True,
        )
        if path == resolved_gate:
            _fail(f"artifact {name} may not bind the canonical gate itself")
        if path in seen:
            _fail(f"artifact {name} duplicates another canonical artifact path")
        seen.add(path)
        expected = _require_sha256(
            binding.get("sha256"), label=f"artifact {name} sha256"
        )
        actual = sha256_file(path)
        if actual != expected:
            _fail(f"artifact {name} content differs from its canonical SHA-256")
        output[name] = path
    return output


def _validate_d0035(combined_path: Path, run_path: Path, *, repo_root: Path) -> None:
    combined = _json_object(combined_path, label="D0035 combined validation")
    exact = {
        "decision_id": D0035_DECISION_ID,
        "geometry_source": "ECO_L1B_GEO.002",
        "geometry_complete": True,
        "cloud_complete": True,
        "combined_complete": True,
        "scientific_gate_eligible": True,
        "candidate_seal_geometry_only": True,
        "candidate_view_mask_cloud_independent": True,
        "view_gate_cloud_conditioned": False,
        "cloud_extrapolation_used": False,
        "canonical_status": D0035_PASS_STATUS,
        "gate_status": D0035_PASS_STATUS,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
    }
    for field, expected in exact.items():
        if combined.get(field) != expected:
            _fail(f"D0035 combined validation has non-PASS {field}")
    counts = {
        "expected_metadata_candidates": 942,
        "resolved_geometry_candidate_count": 942,
        "definitive_geometry_status_count": 942,
        "unresolved_geometry_candidate_count": 0,
    }
    for field, expected in counts.items():
        if _int(combined.get(field), label=f"D0035 {field}") != expected:
            _fail(f"D0035 combined validation has stale {field}")
    passing = _int(
        combined.get("geometry_passing_candidate_count"),
        label="D0035 geometry_passing_candidate_count",
    )
    if not 0 < passing <= 942:
        _fail("D0035 has no valid geometry-passing population")
    for field in (
        "expected_cloud_candidates",
        "resolved_cloud_candidate_count",
        "finite_cloud_fraction_count",
    ):
        if _int(combined.get(field), label=f"D0035 {field}") != passing:
            _fail(f"D0035 exhaustive-cloud count {field} is incomplete")
    planning_sum = _float(
        combined.get("planning_pass_equivalent_sum"),
        label="D0035 planning_pass_equivalent_sum",
    )
    planning_floor = _int(
        combined.get("planning_pass_equivalent_floor"),
        label="D0035 planning_pass_equivalent_floor",
    )
    if planning_sum < 0 or planning_floor != math.floor(planning_sum):
        _fail("D0035 planning pass-equivalent count is inconsistent")

    run = _json_object(run_path, label="D0035 run record")
    run_exact = {
        "schema_version": 2,
        "run_id": "R0004_D0035",
        "decision_id": D0035_DECISION_ID,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
    }
    for field, expected in run_exact.items():
        if run.get(field) != expected:
            _fail(f"D0035 run record has stale {field}")
    if run.get("combined_validation") != combined:
        _fail("D0035 run record does not embed the bound combined validation")
    combined_sha = sha256_file(combined_path)
    provenance = run.get("provenance_sha256")
    if not isinstance(provenance, Mapping) or provenance.get(
        "combined_validation"
    ) != combined_sha:
        _fail("D0035 run record does not hash-bind combined validation")
    artifacts = run.get("artifact_sha256")
    combined_rel = combined_path.relative_to(repo_root).as_posix()
    if not isinstance(artifacts, Mapping) or artifacts.get(combined_rel) != combined_sha:
        _fail("D0035 artifact map does not bind combined validation")
    provenance_counts = run.get("provenance_counts")
    required_provenance_counts = {
        "metadata_candidates": 942,
        "city_scene_links": 1404,
        "unique_scenes": 1370,
    }
    if not isinstance(provenance_counts, Mapping):
        _fail("D0035 run record lacks provenance counts")
    for field, expected in required_provenance_counts.items():
        if _int(
            provenance_counts.get(field), label=f"D0035 provenance {field}"
        ) != expected:
            _fail(f"D0035 run record has stale provenance count {field}")
    if _int(
        provenance_counts.get("pass_evidence_files"),
        label="D0035 pass_evidence_files",
    ) <= 0:
        _fail("D0035 run record has no full-resolution pass evidence")


def _validate_d0035_preserved_stop(
    combined_path: Path, run_path: Path, *, repo_root: Path
) -> None:
    """Prove that D0047 did not relabel the original exhaustive failure."""

    combined = _json_object(combined_path, label="preserved D0035 STOP validation")
    exact = {
        "decision_id": D0035_DECISION_ID,
        "geometry_source": "ECO_L1B_GEO.002",
        "geometry_complete": False,
        "cloud_complete": False,
        "combined_complete": False,
        "scientific_gate_eligible": False,
        "candidate_seal_geometry_only": False,
        "candidate_view_mask_cloud_independent": False,
        "view_gate_cloud_conditioned": False,
        "cloud_extrapolation_used": False,
        "gate_status": D0047_ORIGINAL_STOP,
        "canonical_status": D0047_ORIGINAL_STOP,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
    }
    for field, expected in exact.items():
        if combined.get(field) != expected:
            _fail(f"preserved D0035 STOP has stale {field}")
    counts = {
        "expected_metadata_candidates": D0047_ORIGINAL_CANDIDATES,
        "resolved_geometry_candidate_count": 0,
        "definitive_geometry_status_count": 0,
        "unresolved_geometry_candidate_count": D0047_ORIGINAL_CANDIDATES,
        "geometry_passing_candidate_count": 0,
        "expected_cloud_candidates": 0,
        "resolved_cloud_candidate_count": 0,
        "finite_cloud_fraction_count": 0,
    }
    for field, expected in counts.items():
        if _int(combined.get(field), label=f"preserved D0035 {field}") != expected:
            _fail(f"preserved D0035 STOP has stale {field}")

    run = _json_object(run_path, label="preserved D0035 STOP run record")
    run_exact = {
        "schema_version": 2,
        "run_id": "R0004_D0035",
        "decision_id": D0035_DECISION_ID,
        "implementation_decision_id": "D0036",
        "algorithm_version": "d0035-l1b-dmrpp-pass-stream-v4",
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
    }
    for field, expected in run_exact.items():
        if run.get(field) != expected:
            _fail(f"preserved D0035 STOP run record has stale {field}")
    if run.get("combined_validation") != combined:
        _fail("preserved D0035 run record does not embed the STOP validation")
    counts_record = run.get("provenance_counts")
    if not isinstance(counts_record, Mapping):
        _fail("preserved D0035 run record lacks provenance counts")
    for field, expected in {
        "metadata_candidates": 942,
        "city_scene_links": 1404,
        "unique_scenes": 1370,
    }.items():
        if _int(
            counts_record.get(field), label=f"preserved D0035 provenance {field}"
        ) != expected:
            _fail(f"preserved D0035 provenance has stale {field}")
    combined_sha = sha256_file(combined_path)
    provenance = run.get("provenance_sha256")
    artifact_hashes = run.get("artifact_sha256")
    combined_rel = combined_path.relative_to(repo_root).as_posix()
    if (
        not isinstance(provenance, Mapping)
        or provenance.get("combined_validation") != combined_sha
        or not isinstance(artifact_hashes, Mapping)
        or artifact_hashes.get(combined_rel) != combined_sha
    ):
        _fail("preserved D0035 STOP is not hash-bound by its run record")


def _validate_d0046_unavailability(
    artifacts: Mapping[str, Path], *, repo_root: Path
) -> set[tuple[int, int]]:
    """Validate the bracketed 41-scene D0046 direct-download evidence."""

    validation_path = artifacts["d0046_direct_download_validation"]
    run_path = artifacts["d0046_direct_download_run_record"]
    probe_path = artifacts["d0046_direct_download_probe"]
    controls_path = artifacts["d0046_direct_download_controls"]
    validation = _json_object(validation_path, label="D0046 direct-download validation")
    exact = {
        "decision_id": "D0046",
        "source_gate_decision_id": "D0045",
        "expected_scene_count": 41,
        "attempted_scene_count": 41,
        "control_bracket_valid": True,
        "control_statuses": ["range_readable_now", "range_readable_now"],
        "status_counts": {"not_downloadable_at_exact_url_now": 41},
        "range_readable_now_count": 0,
        "not_downloadable_at_exact_url_now_count": 41,
        "transient_or_transport_count": 0,
        "all_exact_hdf_downloads_available": False,
        "identity_gate_complete": False,
        "gate_status": D0047_LATEST_UNAVAILABILITY_STOP,
        "maximum_payload_bytes_read_per_scene": 0,
        "payload_bytes_retained": 0,
        "geometry_values_opened": False,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "downstream_authorized": False,
    }
    for field, expected in exact.items():
        if validation.get(field) != expected:
            _fail(f"D0046 direct-download validation has stale {field}")

    _, probe_rows = _read_csv(probe_path, label="D0046 direct-download probe")
    if len(probe_rows) != 41:
        _fail("D0046 direct-download probe is not exactly 41 rows")
    target_keys: set[tuple[int, int]] = set()
    for row_number, row in enumerate(probe_rows, start=2):
        key = (
            _int(row.get("orbit"), label=f"D0046 probe row {row_number} orbit"),
            _int(row.get("scene"), label=f"D0046 probe row {row_number} scene"),
        )
        if key in target_keys:
            _fail("D0046 direct-download probe contains duplicate scene keys")
        target_keys.add(key)
        row_exact = {
            "probe_role": "target",
            "range_header": "bytes=0-7",
            "http_status": "404",
            "download_probe_status": "not_downloadable_at_exact_url_now",
            "payload_bytes_retained": "0",
            "decision_id": "D0046",
        }
        for field, expected in row_exact.items():
            if str(row.get(field, "")) != expected:
                _fail(f"D0046 probe row {row_number} has stale {field}")
        for field, expected in {
            "host_chain_allowed": True,
            "hdf5_signature_verified": False,
            "geometry_values_opened": False,
            "lst_opened": False,
            "record_2026_opened": False,
            "control_bracket_valid": True,
        }.items():
            if _boolean_text(
                row.get(field), label=f"D0046 probe row {row_number} {field}"
            ) is not expected:
                _fail(f"D0046 probe row {row_number} has stale {field}")

    controls = _json_object(controls_path, label="D0046 bracket controls")
    control_rows = controls.get("controls")
    if controls.get("decision_id") != "D0046" or not isinstance(
        control_rows, list
    ) or len(control_rows) != 2:
        _fail("D0046 bracket controls are incomplete")
    if [row.get("probe_role") for row in control_rows] != [
        "control_before",
        "control_after",
    ]:
        _fail("D0046 controls do not bracket the target batch")
    for index, row in enumerate(control_rows, start=1):
        if not isinstance(row, Mapping):
            _fail("D0046 bracket control is not an object")
        control_exact = {
            "range_header": "bytes=0-7",
            "http_status": 206,
            "download_probe_status": "range_readable_now",
            "prefix_bytes_read": 8,
            "hdf5_signature_verified": True,
            "payload_bytes_retained": 0,
            "geometry_values_opened": False,
            "lst_opened": False,
            "record_2026_opened": False,
            "decision_id": "D0046",
        }
        for field, expected in control_exact.items():
            if row.get(field) != expected:
                _fail(f"D0046 control {index} has stale {field}")

    run = _json_object(run_path, label="D0046 direct-download run record")
    run_exact = {
        "schema_version": 1,
        "run_id": "R0010",
        "decision_id": "D0046",
    }
    for field, expected in run_exact.items():
        if run.get(field) != expected:
            _fail(f"D0046 run record has stale {field}")
    if run.get("validation") != validation:
        _fail("D0046 run record does not embed its bound validation")
    ledger = run.get("artifact_sha256")
    if not isinstance(ledger, Mapping):
        _fail("D0046 run record lacks its artifact hash ledger")
    for name in (
        "d0046_direct_download_probe",
        "d0046_direct_download_controls",
        "d0046_direct_download_validation",
    ):
        path = artifacts[name]
        relative = path.relative_to(repo_root).as_posix()
        if ledger.get(relative) != sha256_file(path):
            _fail(f"D0046 run record does not hash-bind {name}")

    resolution_path = _inside_repo(
        run.get("input_resolution_path"),
        repo_root=repo_root,
        label="D0046 input_resolution_path",
        require_relative=True,
    )
    if run.get("input_resolution_sha256") != sha256_file(resolution_path):
        _fail("D0046 input scene-resolution hash is stale")
    resolution_fields, resolution_rows = _read_csv(
        resolution_path, label="D0046 input scene-resolution evidence"
    )
    if {"orbit", "scene"} - set(resolution_fields) or len(resolution_rows) != 41:
        _fail("D0046 input scene-resolution evidence is not the 41-scene census")
    resolution_keys = {
        (
            _int(row.get("orbit"), label="D0046 resolution orbit"),
            _int(row.get("scene"), label="D0046 resolution scene"),
        )
        for row in resolution_rows
    }
    if resolution_keys != target_keys or any(
        row.get("identity_resolution_status") != "unresolved_missing"
        for row in resolution_rows
    ):
        _fail("D0046 probe identities differ from its sealed input census")
    identity_path = _inside_repo(
        run.get("identity_validation_path"),
        repo_root=repo_root,
        label="D0046 identity_validation_path",
        require_relative=True,
    )
    if run.get("identity_validation_sha256") != sha256_file(identity_path):
        _fail("D0046 upstream identity-validation hash is stale")
    identity = _json_object(identity_path, label="D0046 upstream identity validation")
    identity_exact = {
        "expected_missing_scene_count": 41,
        "unresolved_missing_count": 41,
        "identity_complete": False,
        "geometry_values_opened": False,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "downstream_authorized": False,
    }
    for field, expected in identity_exact.items():
        if identity.get(field) != expected:
            _fail(f"D0046 upstream identity validation has stale {field}")
    return target_keys


def _parse_utc(value: Any, *, label: str) -> datetime:
    text = str(value).strip()
    if not text:
        _fail(f"{label} is empty")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        _fail(f"{label} is not an ISO-8601 timestamp")
    if parsed.tzinfo is None:
        _fail(f"{label} must include a UTC offset")
    parsed = parsed.astimezone(timezone.utc)
    if parsed.minute or parsed.second or parsed.microsecond:
        _fail(f"{label} must be an exact HRRR analysis hour")
    if not 2018 <= parsed.year <= 2025:
        _fail(f"{label} is outside the frozen 2018-2025 record")
    return parsed


def _read_csv(path: Path, *, label: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error):
        _fail(f"{label} is not a readable CSV file")
    if not fields:
        _fail(f"{label} has no header")
    return fields, rows


def _parse_record_datetime(value: Any, *, label: str) -> datetime:
    text = str(value).strip()
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        _fail(f"{label} is not an ISO-8601 timestamp")
    if parsed.tzinfo is None:
        _fail(f"{label} must include a UTC offset")
    parsed = parsed.astimezone(timezone.utc)
    if not 2018 <= parsed.year <= 2025:
        _fail(f"{label} is outside the frozen 2018-2025 record")
    return parsed


def _d0047_scene_keys_from_ledger(
    ledger_rows: list[dict[str, str]], *, label: str
) -> set[tuple[int, int]]:
    keys: set[tuple[int, int]] = set()
    for row_number, row in enumerate(ledger_rows, start=2):
        raw = str(row.get("d0047_unavailable_scene_keys", "")).strip()
        for value in filter(None, raw.split(";")):
            match = re.fullmatch(r"(\d{5})_(\d{3})", value)
            if match is None:
                _fail(f"{label} row {row_number} has a malformed missing scene key")
            keys.add((int(match.group(1)), int(match.group(2))))
    return keys


def _validate_d0047_quality_profile(
    artifacts: Mapping[str, Path],
    *,
    repo_root: Path,
    d0046_scene_keys: set[tuple[int, int]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the 942/31/911 archive-available quality evidence chain."""

    ledger_path = artifacts["candidate_availability_ledger"]
    exclusions_path = artifacts["archive_unavailable_pre_geometry_exclusions"]
    attrition_path = artifacts["archive_available_attrition_summary"]
    links_path = artifacts["retained_city_scene_links"]
    profile_path = artifacts["d0047_profile_validation"]
    combined_path = artifacts["d0047_combined_validation"]
    run_path = artifacts["d0047_run_record"]

    ledger_fields, ledger_rows = _read_csv(
        ledger_path, label="D0047 candidate availability ledger"
    )
    required_ledger = {
        "city",
        "orbit",
        "acquisition_utc",
        "year",
        "month",
        "time_stratum",
        "d0047_candidate_status",
        "d0047_profile_included",
        "d0047_exclusion_reason",
        "d0047_unavailable_scene_count",
        "d0047_unavailable_scene_keys",
        "d0047_profile_scope",
        "d0047_missing_scene_evidence_sha256",
        "decision_id",
        "lst_opened",
        "thermal_opened",
        "record_2026_opened",
        "holdout_status",
    }
    if required_ledger - set(ledger_fields) or len(ledger_rows) != 942:
        _fail("D0047 candidate availability ledger is not the frozen 942-row schema")
    candidate_keys: set[tuple[str, int]] = set()
    retained_keys: set[tuple[str, int]] = set()
    excluded_keys: set[tuple[str, int]] = set()
    observed_by_city: dict[str, int] = {}
    retained_by_city: dict[str, int] = {}
    excluded_by_city: dict[str, int] = {}
    excluded_by_year: dict[str, int] = {}
    excluded_by_month: dict[str, int] = {}
    excluded_by_stratum: dict[str, int] = {}
    evidence_hashes: set[str] = set()
    for row_number, row in enumerate(ledger_rows, start=2):
        city = str(row.get("city", "")).strip()
        orbit = _int(row.get("orbit"), label=f"D0047 ledger row {row_number} orbit")
        key = (city, orbit)
        if not city or key in candidate_keys:
            _fail("D0047 candidate availability ledger has duplicate/empty keys")
        candidate_keys.add(key)
        timestamp = _parse_record_datetime(
            row.get("acquisition_utc"),
            label=f"D0047 ledger row {row_number} acquisition_utc",
        )
        year = _int(row.get("year"), label=f"D0047 ledger row {row_number} year")
        month = _int(row.get("month"), label=f"D0047 ledger row {row_number} month")
        if year != timestamp.year or month != timestamp.month:
            _fail(f"D0047 ledger row {row_number} has stale year/month")
        included = _boolean_text(
            row.get("d0047_profile_included"),
            label=f"D0047 ledger row {row_number} profile inclusion",
        )
        status = str(row.get("d0047_candidate_status", ""))
        missing_count = _int(
            row.get("d0047_unavailable_scene_count"),
            label=f"D0047 ledger row {row_number} missing-scene count",
        )
        missing_keys = tuple(
            filter(None, str(row.get("d0047_unavailable_scene_keys", "")).split(";"))
        )
        if included:
            retained_keys.add(key)
            retained_by_city[city] = retained_by_city.get(city, 0) + 1
            if (
                status != D0047_RETAINED_STATUS
                or missing_count != 0
                or missing_keys
                or str(row.get("d0047_exclusion_reason", ""))
            ):
                _fail(f"D0047 retained ledger row {row_number} has exclusion data")
        else:
            excluded_keys.add(key)
            excluded_by_city[city] = excluded_by_city.get(city, 0) + 1
            excluded_by_year[str(year)] = excluded_by_year.get(str(year), 0) + 1
            excluded_by_month[str(month)] = excluded_by_month.get(str(month), 0) + 1
            stratum = str(row.get("time_stratum", ""))
            excluded_by_stratum[stratum] = excluded_by_stratum.get(stratum, 0) + 1
            if (
                status != D0047_EXCLUDED_STATUS
                or missing_count <= 0
                or len(missing_keys) != missing_count
                or not str(row.get("d0047_exclusion_reason", "")).strip()
            ):
                _fail(f"D0047 excluded ledger row {row_number} is incomplete")
        observed_by_city[city] = observed_by_city.get(city, 0) + 1
        if (
            row.get("decision_id") != D0047_DECISION_ID
            or row.get("d0047_profile_scope") != D0047_PROFILE_SCOPE_LABEL
            or _boolean_text(row.get("lst_opened"), label="D0047 ledger lst_opened")
            or _boolean_text(
                row.get("thermal_opened"), label="D0047 ledger thermal_opened"
            )
            or _boolean_text(
                row.get("record_2026_opened"),
                label="D0047 ledger record_2026_opened",
            )
            or str(row.get("holdout_status", "")).upper() != "UNSELECTED"
        ):
            _fail(f"D0047 ledger row {row_number} breaks a safety/scope seal")
        evidence_hashes.add(
            _require_sha256(
                row.get("d0047_missing_scene_evidence_sha256"),
                label=f"D0047 ledger row {row_number} evidence hash",
            )
        )
    if (
        len(retained_keys) != D0047_RETAINED_CANDIDATES
        or len(excluded_keys) != D0047_EXCLUDED_CANDIDATES
        or observed_by_city != D0047_ORIGINAL_BY_CITY
        or retained_by_city != D0047_RETAINED_BY_CITY
        or excluded_by_city != D0047_EXCLUDED_BY_CITY
        or excluded_by_year != {"2020": 24, "2024": 7}
        or excluded_by_month != {"6": 8, "7": 4, "8": 13, "9": 6}
        or excluded_by_stratum != {"10-12": 9, "12-14": 9, "14-16": 8, "16-18": 5}
        or len(evidence_hashes) != 1
    ):
        _fail("D0047 candidate ledger count/distribution seal is stale")
    missing_scene_keys = _d0047_scene_keys_from_ledger(
        ledger_rows, label="D0047 candidate ledger"
    )
    if len(missing_scene_keys) != 41 or missing_scene_keys != d0046_scene_keys:
        _fail("D0047 excluded scene identities differ from the D0046 evidence")

    _, exclusion_rows = _read_csv(
        exclusions_path, label="D0047 pre-geometry exclusion table"
    )
    exclusion_table_keys = {
        (
            str(row.get("city", "")).strip(),
            _int(row.get("orbit"), label="D0047 exclusion orbit"),
        )
        for row in exclusion_rows
    }
    if (
        len(exclusion_rows) != D0047_EXCLUDED_CANDIDATES
        or len(exclusion_table_keys) != D0047_EXCLUDED_CANDIDATES
        or exclusion_table_keys != excluded_keys
        or any(
            row.get("d0047_candidate_status") != D0047_EXCLUDED_STATUS
            or _boolean_text(
                row.get("d0047_profile_included"),
                label="D0047 exclusion profile inclusion",
            )
            for row in exclusion_rows
        )
    ):
        _fail("D0047 31-row pre-geometry exclusion table is stale")

    attrition_fields, attrition_rows = _read_csv(
        attrition_path, label="D0047 archive-available attrition summary"
    )
    required_attrition = {
        "original_candidate_count",
        "excluded_pre_geometry_candidate_count",
        "retained_geometry_candidate_count",
        "decision_id",
        "target_scope",
    }
    if required_attrition - set(attrition_fields) or not attrition_rows:
        _fail("D0047 attrition summary lacks the frozen schema")
    attrition_totals = {
        field: sum(_int(row.get(field), label=f"D0047 attrition {field}") for row in attrition_rows)
        for field in (
            "original_candidate_count",
            "excluded_pre_geometry_candidate_count",
            "retained_geometry_candidate_count",
        )
    }
    if attrition_totals != {
        "original_candidate_count": 942,
        "excluded_pre_geometry_candidate_count": 31,
        "retained_geometry_candidate_count": 911,
    } or any(
        row.get("decision_id") != D0047_DECISION_ID
        or row.get("target_scope") != D0047_PROFILE_SCOPE_LABEL
        for row in attrition_rows
    ):
        _fail("D0047 attrition summary count/scope seal is stale")

    links_fields, links_rows = _read_csv(
        links_path, label="D0047 retained city-scene links"
    )
    required_links = {
        "city",
        "orbit",
        "scene",
        "d0047_scene_archive_available",
        "decision_id",
        "d0047_profile_scope",
    }
    if required_links - set(links_fields) or len(links_rows) != 1355:
        _fail("D0047 retained city-scene link census is stale")
    city_scene_keys: set[tuple[str, int, int]] = set()
    unique_scene_keys: set[tuple[int, int]] = set()
    linked_candidate_keys: set[tuple[str, int]] = set()
    for row_number, row in enumerate(links_rows, start=2):
        city = str(row.get("city", "")).strip()
        orbit = _int(row.get("orbit"), label=f"D0047 link row {row_number} orbit")
        scene = _int(row.get("scene"), label=f"D0047 link row {row_number} scene")
        city_scene_key = (city, orbit, scene)
        if city_scene_key in city_scene_keys:
            _fail("D0047 retained links contain duplicate city/orbit/scene rows")
        city_scene_keys.add(city_scene_key)
        unique_scene_keys.add((orbit, scene))
        linked_candidate_keys.add((city, orbit))
        if (
            not _boolean_text(
                row.get("d0047_scene_archive_available"),
                label=f"D0047 link row {row_number} availability",
            )
            or row.get("decision_id") != D0047_DECISION_ID
            or row.get("d0047_profile_scope") != D0047_PROFILE_SCOPE_LABEL
        ):
            _fail(f"D0047 retained link row {row_number} is outside scope")
    if (
        len(unique_scene_keys) != D0047_RETAINED_UNIQUE_SCENES
        or linked_candidate_keys != retained_keys
        or unique_scene_keys.intersection(missing_scene_keys)
    ):
        _fail("D0047 retained link identities/counts are stale")

    profile = _json_object(profile_path, label="D0047 profile validation")
    profile_exact = {
        "schema_version": 1,
        "decision_id": D0047_DECISION_ID,
        "implementation_decision_id": D0047_DECISION_ID,
        "algorithm_version": D0047_ALGORITHM_VERSION,
        "target_scope": D0047_PROFILE_SCOPE_LABEL,
        "analysis_profile": D0047_ANALYSIS_PROFILE,
        "scientific_gate_scope": D0047_SCIENTIFIC_GATE_SCOPE,
        "original_metadata_candidate_count": 942,
        "excluded_pre_geometry_candidate_count": 31,
        "retained_geometry_candidate_count": 911,
        "original_city_scene_link_count": 1404,
        "retained_city_scene_link_count": 1355,
        "original_unique_scene_count": 1370,
        "sealed_unavailable_unique_scene_count": 41,
        "retained_unique_scene_count": 1323,
        "candidate_ledger_complete": True,
        "retained_candidate_keys_exact": True,
        "whole_candidate_exclusion_rule": True,
        "missing_scene_imputation_used": False,
        "missing_scene_zero_coverage_assigned": False,
        "adjacent_scene_substitution_used": False,
        "geometry_values_opened": False,
        "cloud_values_opened": False,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
        "profile_gate_status": D0047_PROFILE_SEAL_STATUS,
        "excluded_by_city": D0047_EXCLUDED_BY_CITY,
        "original_by_city": D0047_ORIGINAL_BY_CITY,
        "retained_by_city": D0047_RETAINED_BY_CITY,
        "excluded_by_year": {"2020": 24, "2024": 7},
        "excluded_by_utc_month": {"6": 8, "7": 4, "8": 13, "9": 6},
        "excluded_by_time_stratum": {
            "10-12": 9,
            "12-14": 9,
            "14-16": 8,
            "16-18": 5,
        },
    }
    for field, expected in profile_exact.items():
        if profile.get(field) != expected:
            _fail(f"D0047 profile validation has stale {field}")
    if profile.get("missing_scene_evidence_sha256") not in evidence_hashes:
        _fail("D0047 profile validation has a stale missing-scene evidence hash")
    expected_profile_paths = {
        "candidate_ledger_relative_path": ledger_path,
        "exclusion_ledger_relative_path": exclusions_path,
        "retained_links_relative_path": links_path,
    }
    for field, path in expected_profile_paths.items():
        if profile.get(field) != path.relative_to(repo_root).as_posix():
            _fail(f"D0047 profile validation has stale {field}")

    combined = _json_object(combined_path, label="D0047 combined validation")
    combined_exact = {
        "decision_id": D0047_DECISION_ID,
        "implementation_decision_id": D0047_DECISION_ID,
        "analysis_profile": D0047_ANALYSIS_PROFILE,
        "scientific_gate_scope": D0047_SCIENTIFIC_GATE_SCOPE,
        "original_metadata_candidate_count": 942,
        "excluded_pre_geometry_candidate_count": 31,
        "retained_geometry_candidate_count": 911,
        "retained_city_scene_link_count": 1355,
        "retained_unique_scene_count": 1323,
        "expected_metadata_candidates": 911,
        "resolved_geometry_candidate_count": 911,
        "definitive_geometry_status_count": 911,
        "unresolved_geometry_candidate_count": 0,
        "geometry_source": "ECO_L1B_GEO.002",
        "geometry_complete": True,
        "cloud_complete": True,
        "combined_complete": True,
        "scientific_gate_eligible": True,
        "candidate_seal_geometry_only": True,
        "candidate_view_mask_cloud_independent": True,
        "view_gate_cloud_conditioned": False,
        "cloud_extrapolation_used": False,
        "missing_scene_imputation_used": False,
        "missing_scene_zero_coverage_assigned": False,
        "adjacent_scene_substitution_used": False,
        "gate_status": D0047_PASS_STATUS,
        "canonical_status": D0047_PASS_STATUS,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
    }
    for field, expected in combined_exact.items():
        if combined.get(field) != expected:
            _fail(f"D0047 combined validation has stale {field}")
    passing = _int(
        combined.get("geometry_passing_candidate_count"),
        label="D0047 geometry_passing_candidate_count",
    )
    if not 0 < passing <= D0047_RETAINED_CANDIDATES:
        _fail("D0047 has no valid geometry-passing population")
    for field in (
        "expected_cloud_candidates",
        "resolved_cloud_candidate_count",
        "finite_cloud_fraction_count",
    ):
        if _int(combined.get(field), label=f"D0047 {field}") != passing:
            _fail(f"D0047 exhaustive-cloud count {field} is incomplete")
    planning_sum = _float(
        combined.get("planning_pass_equivalent_sum"),
        label="D0047 planning_pass_equivalent_sum",
    )
    planning_floor = _int(
        combined.get("planning_pass_equivalent_floor"),
        label="D0047 planning_pass_equivalent_floor",
    )
    if planning_sum < 0 or planning_floor != math.floor(planning_sum):
        _fail("D0047 planning pass-equivalent count is inconsistent")

    run = _json_object(run_path, label="D0047 run record")
    run_exact = {
        "schema_version": 3,
        "run_id": "R0011_D0047",
        "decision_id": D0047_DECISION_ID,
        "implementation_decision_id": D0047_DECISION_ID,
        "algorithm_version": D0047_ALGORITHM_VERSION,
        "analysis_profile": D0047_ANALYSIS_PROFILE,
        "scientific_gate_scope": D0047_SCIENTIFIC_GATE_SCOPE,
        "missing_scene_imputation_used": False,
        "missing_scene_zero_coverage_assigned": False,
        "adjacent_scene_substitution_used": False,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
    }
    for field, expected in run_exact.items():
        if run.get(field) != expected:
            _fail(f"D0047 run record has stale {field}")
    if run.get("combined_validation") != combined:
        _fail("D0047 run record does not embed the combined validation")
    provenance_counts = run.get("provenance_counts")
    required_counts = {
        "original_metadata_candidate_count": 942,
        "excluded_pre_geometry_candidate_count": 31,
        "retained_geometry_candidate_count": 911,
        "retained_city_scene_link_count": 1355,
        "retained_unique_scene_count": 1323,
    }
    if not isinstance(provenance_counts, Mapping):
        _fail("D0047 run record lacks provenance counts")
    for field, expected in required_counts.items():
        if _int(provenance_counts.get(field), label=f"D0047 provenance {field}") != expected:
            _fail(f"D0047 run record has stale provenance count {field}")
    provenance = run.get("provenance_sha256")
    artifact_hashes = run.get("artifact_sha256")
    if not isinstance(provenance, Mapping) or not isinstance(artifact_hashes, Mapping):
        _fail("D0047 run record lacks its hash ledgers")
    run_bindings = {
        "candidate_availability_ledger": ledger_path,
        "archive_unavailable_pre_geometry_exclusions": exclusions_path,
        "archive_available_attrition_summary": attrition_path,
        "retained_city_scene_links": links_path,
        "profile_validation": profile_path,
        "combined_validation": combined_path,
    }
    for field, path in run_bindings.items():
        digest = sha256_file(path)
        relative = path.relative_to(repo_root).as_posix()
        if provenance.get(field) != digest or artifact_hashes.get(relative) != digest:
            _fail(f"D0047 run record does not hash-bind {field}")
    return combined, run


def _manifest_binding(
    row: Mapping[str, Any],
    *,
    row_number: int,
    d0053_contract: bool = False,
) -> tuple[dict[str, Any], datetime]:
    timestamp = _parse_utc(
        row.get("analysis_utc"), label=f"HRRR manifest row {row_number} analysis_utc"
    )
    timestamp_key = timestamp.strftime("%Y%m%dT%HZ")
    fallback = d0053_contract and timestamp_key in _D0053_HRRR_FALLBACK_HOURS
    product = "prs" if fallback else "sfc"
    object_stem = "wrfprs" if fallback else "wrfsfc"
    item_id = f"hrrr-{product}-f00-{timestamp:%Y%m%dT%H}Z"
    key = (
        f"hrrr.{timestamp:%Y%m%d}/conus/"
        f"hrrr.t{timestamp:%H}z.{object_stem}f00.grib2"
    )
    grib_url = f"{_HRRR_HTTPS_ROOT}/{key}"
    cities = tuple(filter(None, str(row.get("cities", "")).split("|")))
    if not cities or tuple(sorted(set(cities))) != cities:
        _fail(f"HRRR manifest row {row_number} cities are not sorted and unique")
    source = _D0053_HRRR_SOURCE if d0053_contract else _HRRR_SOURCE
    exact = {
        "item_id": item_id,
        "model": "hrrr",
        "product": product,
        "forecast_hour": "0",
        "variable_search": _HRRR_SEARCH,
        "source": source,
        "object_key": key,
        "grib_url": grib_url,
        "index_url": f"{grib_url}.idx",
    }
    if d0053_contract:
        exact["product_resolution"] = (
            _D0053_HRRR_FALLBACK_RESOLUTION
            if fallback
            else _D0053_HRRR_PRIMARY_RESOLUTION
        )
    for field, expected in exact.items():
        if str(row.get(field, "")) != expected:
            _fail(f"HRRR manifest row {row_number} has stale {field}")
    target_count = _int(
        row.get("n_target_passes"),
        label=f"HRRR manifest row {row_number} n_target_passes",
    )
    if target_count <= 0:
        _fail(f"HRRR manifest row {row_number} has no target passes")
    return (
        {
            "item_id": item_id,
            "analysis_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cities": "|".join(cities),
            "n_target_passes": target_count,
            "model": "hrrr",
            "product": product,
            "forecast_hour": 0,
            "variable_search": _HRRR_SEARCH,
            "source": source,
            "object_key": key,
            **(
                {"product_resolution": exact["product_resolution"]}
                if d0053_contract
                else {}
            ),
        },
        timestamp,
    )


def _validate_hrrr(
    seal_path: Path,
    manifest_path: Path,
    shard_index_path: Path,
    summary_path: Path,
    *,
    repo_root: Path,
    gate_path: Path,
    expected_status: str = HRRR_PASS_STATUS,
    expected_profile_binding: Mapping[str, Any] | None = None,
) -> None:
    d0053_contract = expected_status == D0047_HRRR_PASS_STATUS
    manifest_binding_fields = (
        _D0053_HRRR_MANIFEST_FIELDS
        if d0053_contract
        else _HRRR_MANIFEST_FIELDS
    )
    source_label = _D0053_HRRR_SOURCE if d0053_contract else _HRRR_SOURCE
    run_seal_schema_version = 2 if d0053_contract else 1
    checkpoint_schema_version = 3 if d0053_contract else 2
    manifest_fields, manifest_rows = _read_csv(
        manifest_path, label="HRRR request manifest"
    )
    required_manifest = set(manifest_binding_fields) | {"grib_url", "index_url"}
    if required_manifest - set(manifest_fields) or not manifest_rows:
        _fail("HRRR request manifest is empty or lacks the frozen schema")
    manifest: list[tuple[dict[str, Any], datetime]] = [
        _manifest_binding(
            row,
            row_number=index,
            d0053_contract=d0053_contract,
        )
        for index, row in enumerate(manifest_rows, start=2)
    ]
    manifest.sort(key=lambda pair: pair[1])
    bindings = [pair[0] for pair in manifest]
    item_ids = [str(row["item_id"]) for row in bindings]
    if len(item_ids) != len(set(item_ids)):
        _fail("HRRR manifest item IDs are not unique")
    if d0053_contract:
        primary_count = sum(row["product"] == "sfc" for row in bindings)
        fallback_count = sum(row["product"] == "prs" for row in bindings)
        fallback_hours = {
            timestamp.strftime("%Y%m%dT%HZ")
            for row, timestamp in manifest
            if row["product"] == "prs"
        }
        if (
            len(bindings) != _D0053_HRRR_MANIFEST_ITEMS
            or primary_count != _D0053_HRRR_PRIMARY_ITEMS
            or fallback_count != _D0053_HRRR_FALLBACK_ITEMS
            or fallback_hours != _D0053_HRRR_FALLBACK_HOURS
        ):
            _fail("D0053 HRRR manifest does not contain the frozen 409 sfc + 4 prs census")
    manifest_canonical_sha = _json_sha256(bindings)

    seal = _json_object(seal_path, label="HRRR run seal")
    seal_exact = {
        "schema_version": run_seal_schema_version,
        "status": expected_status,
        "manifest_canonical_sha256": manifest_canonical_sha,
        "manifest_fields": list(manifest_binding_fields),
        "checkpoint_schema_version": checkpoint_schema_version,
        "shard_schema_version": 1,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
    }
    for field, expected in seal_exact.items():
        if seal.get(field) != expected:
            _fail(f"HRRR run seal has stale {field}")
    if expected_profile_binding is None:
        if seal.get("profile_binding") is not None or seal.get(
            "profile_binding_sha256"
        ) is not None:
            _fail("D0035 HRRR run seal unexpectedly carries a profile binding")
    else:
        binding = dict(expected_profile_binding)
        if (
            seal.get("profile_binding") != binding
            or seal.get("profile_binding_sha256") != _json_sha256(binding)
        ):
            _fail("D0047 HRRR run seal has a stale archive-profile binding")
    minimum_cells = _int(
        seal.get("minimum_domain_cells"), label="HRRR minimum_domain_cells"
    )
    if minimum_cells < 1:
        _fail("HRRR minimum-domain-cell rule is invalid")
    domain_names = seal.get("domain_names")
    if (
        not isinstance(domain_names, list)
        or not domain_names
        or domain_names != sorted(set(map(str, domain_names)))
    ):
        _fail("HRRR frozen domain names are absent or noncanonical")
    domain_sha = _require_sha256(
        seal.get("frozen_domain_sha256"), label="HRRR frozen_domain_sha256"
    )

    declared_files = {
        "manifest": manifest_path,
        "shard_index": shard_index_path,
        "summary": summary_path,
    }
    for name, expected_path in declared_files.items():
        stored_path = seal.get(f"{name}_path")
        actual_path = _inside_repo(
            stored_path,
            repo_root=repo_root,
            label=f"HRRR seal {name}_path",
            require_relative=False,
        )
        if actual_path != expected_path:
            _fail(f"HRRR run seal points to a different {name}")
        hash_field = "manifest_file_sha256" if name == "manifest" else f"{name}_sha256"
        if seal.get(hash_field) != sha256_file(expected_path):
            _fail(f"HRRR run seal has stale {hash_field}")

    checkpoint_path = _inside_repo(
        seal.get("checkpoint_path"),
        repo_root=repo_root,
        label="HRRR seal checkpoint_path",
        require_relative=False,
    )
    if checkpoint_path == gate_path.resolve():
        _fail("HRRR checkpoint may not be the canonical gate itself")
    if seal.get("checkpoint_sha256") != sha256_file(checkpoint_path):
        _fail("HRRR run seal has a stale checkpoint hash")
    checkpoint = _json_object(checkpoint_path, label="HRRR checkpoint")
    checkpoint_exact = {
        "schema_version": checkpoint_schema_version,
        "checkpoint_kind": "hrrr_exact_acquisition_domain_shards",
        "manifest_sha256": manifest_canonical_sha,
        "frozen_domain_sha256": domain_sha,
        "shard_schema_version": 1,
        "minimum_domain_cells": minimum_cells,
    }
    for field, expected in checkpoint_exact.items():
        if checkpoint.get(field) != expected:
            _fail(f"HRRR checkpoint has stale {field}")
    checkpoint_items = checkpoint.get("items")
    if not isinstance(checkpoint_items, Mapping) or set(checkpoint_items) != set(item_ids):
        _fail("HRRR checkpoint items differ from the canonical manifest")

    index_fields, index_rows = _read_csv(
        shard_index_path, label="HRRR shard index"
    )
    required_index = {
        "schema_version",
        "shard_schema_version",
        "item_id",
        "analysis_utc",
        "cities",
        "n_target_passes",
        "model",
        "product",
        "forecast_hour",
        "variable_search",
        "object_key",
        "request_sha256",
        "frozen_domain_sha256",
        "local_path",
        "size_bytes",
        "sha256",
        "n_rows",
        "city_row_counts",
        "source",
    }
    if d0053_contract:
        required_index.add("product_resolution")
    if required_index - set(index_fields) or not index_rows:
        _fail("HRRR shard index is empty or lacks the frozen schema")
    by_item: dict[str, dict[str, str]] = {}
    total_shard_rows = 0
    shard_set: list[dict[str, Any]] = []
    for row_number, row in enumerate(index_rows, start=2):
        item_id = str(row.get("item_id", ""))
        if not item_id or item_id in by_item:
            _fail(f"HRRR shard index row {row_number} has a duplicate item_id")
        by_item[item_id] = row
    if set(by_item) != set(item_ids):
        _fail("HRRR shard index items differ from the canonical manifest")

    binding_by_item = {str(item["item_id"]): item for item in bindings}
    timestamp_by_item = {
        str(item["item_id"]): timestamp for item, timestamp in manifest
    }
    manifest_cities = {
        str(item["item_id"]): str(item["cities"]).split("|") for item in bindings
    }
    for item_id in item_ids:
        row = by_item[item_id]
        binding = binding_by_item[item_id]
        expected_request_sha = _json_sha256(binding)
        if (
            _int(row.get("schema_version"), label=f"{item_id} schema_version")
            != checkpoint_schema_version
            or _int(
                row.get("shard_schema_version"),
                label=f"{item_id} shard_schema_version",
            )
            != 1
            or row.get("request_sha256") != expected_request_sha
            or row.get("frozen_domain_sha256") != domain_sha
            or row.get("source") != source_label
            or _int(
                row.get("n_target_passes"),
                label=f"{item_id} n_target_passes",
            )
            != binding["n_target_passes"]
            or row.get("model") != binding["model"]
            or row.get("product") != binding["product"]
            or _int(
                row.get("forecast_hour"),
                label=f"{item_id} forecast_hour",
            )
            != binding["forecast_hour"]
            or row.get("variable_search") != binding["variable_search"]
            or row.get("object_key") != binding["object_key"]
            or (
                d0053_contract
                and row.get("product_resolution")
                != binding["product_resolution"]
            )
        ):
            _fail(f"HRRR shard index binding is stale for {item_id}")
        row_time = _parse_utc(
            row.get("analysis_utc"), label=f"{item_id} shard analysis_utc"
        )
        if row_time != timestamp_by_item[item_id] or row.get("cities") != binding["cities"]:
            _fail(f"HRRR shard index request fields differ for {item_id}")
        shard_path = _inside_repo(
            row.get("local_path"),
            repo_root=repo_root,
            label=f"HRRR shard {item_id} local_path",
            require_relative=False,
        )
        if (
            shard_path.name != f"{item_id}.csv.gz"
            or shard_path.parent.name != "hourly_domain_cells"
        ):
            _fail(f"HRRR shard {item_id} is not at its canonical shard path")
        size = _int(row.get("size_bytes"), label=f"{item_id} size_bytes")
        digest = _require_sha256(row.get("sha256"), label=f"{item_id} sha256")
        if shard_path.stat().st_size != size or sha256_file(shard_path) != digest:
            _fail(f"HRRR shard {item_id} differs from its index binding")
        n_rows = _int(row.get("n_rows"), label=f"{item_id} n_rows")
        if n_rows < minimum_cells:
            _fail(f"HRRR shard {item_id} is below the minimum cell count")
        try:
            city_counts = json.loads(str(row.get("city_row_counts", "")))
        except (json.JSONDecodeError, TypeError):
            _fail(f"HRRR shard {item_id} city counts are invalid JSON")
        if (
            not isinstance(city_counts, dict)
            or set(city_counts) != set(manifest_cities[item_id])
            or any(
                not isinstance(value, int) or value < minimum_cells
                for value in city_counts.values()
            )
            or sum(city_counts.values()) != n_rows
        ):
            _fail(f"HRRR shard {item_id} city counts are inconsistent")
        checkpoint_item = checkpoint_items.get(item_id)
        if not isinstance(checkpoint_item, Mapping):
            _fail(f"HRRR checkpoint item {item_id} is invalid")
        checkpoint_exact_item = {
            "schema_version": checkpoint_schema_version,
            "shard_schema_version": 1,
            "status": "complete",
            "frozen_domain_sha256": domain_sha,
            "request_binding": binding,
            "request_sha256": expected_request_sha,
            "local_path": str(shard_path),
            "size_bytes": size,
            "sha256": digest,
            "n_rows": n_rows,
            "city_row_counts": city_counts,
        }
        for field, expected in checkpoint_exact_item.items():
            actual = checkpoint_item.get(field)
            if field == "local_path":
                actual_path = _inside_repo(
                    actual,
                    repo_root=repo_root,
                    label=f"HRRR checkpoint {item_id} local_path",
                    require_relative=False,
                )
                if actual_path != shard_path:
                    _fail(f"HRRR checkpoint item {item_id} has stale local_path")
            elif actual != expected:
                _fail(f"HRRR checkpoint item {item_id} has stale {field}")
        total_shard_rows += n_rows
        shard_set.append(
            {
                "item_id": item_id,
                "request_sha256": expected_request_sha,
                "sha256": digest,
                "n_rows": n_rows,
                "city_row_counts": city_counts,
            }
        )
    if seal.get("shard_set_sha256") != _json_sha256(shard_set):
        _fail("HRRR run seal has a stale shard-set hash")

    summary_fields, summary_rows = _read_csv(summary_path, label="HRRR summary")
    required_summary = {
        "city",
        "timestamp_utc",
        "vpd_kpa",
        "t2m_k",
        "d2m_k",
        "n_domain_cells",
        "source",
        "domain_cell_rule",
    }
    if required_summary - set(summary_fields) or not summary_rows:
        _fail("HRRR summary is empty or lacks the frozen schema")
    expected_city_times = {
        (city, timestamp)
        for item, timestamp in manifest
        for city in str(item["cities"]).split("|")
    }
    actual_city_times: set[tuple[str, datetime]] = set()
    for row_number, row in enumerate(summary_rows, start=2):
        timestamp = _parse_utc(
            row.get("timestamp_utc"), label=f"HRRR summary row {row_number} timestamp"
        )
        key = (str(row.get("city", "")), timestamp)
        if key in actual_city_times:
            _fail("HRRR summary contains duplicate city-hour rows")
        actual_city_times.add(key)
        if (
            key not in expected_city_times
            or row.get("source") != source_label
            or row.get("domain_cell_rule")
            != "HRRR grid-cell center covered by frozen Census Urban Area"
        ):
            _fail(f"HRRR summary row {row_number} has stale provenance")
        t2m = _float(row.get("t2m_k"), label="HRRR summary t2m_k")
        d2m = _float(row.get("d2m_k"), label="HRRR summary d2m_k")
        vpd = _float(row.get("vpd_kpa"), label="HRRR summary vpd_kpa")
        cells = _int(row.get("n_domain_cells"), label="HRRR summary n_domain_cells")
        if not (180 <= t2m <= 350 and 170 <= d2m <= 340 and vpd >= 0):
            _fail(f"HRRR summary row {row_number} has implausible weather values")
        if cells < minimum_cells:
            _fail(f"HRRR summary row {row_number} is below the cell-count rule")
    if actual_city_times != expected_city_times:
        _fail("HRRR summary city-hour population differs from the manifest")

    counts = seal.get("counts")
    expected_counts = {
        "manifest_items": len(manifest_rows),
        "checkpoint_items": len(checkpoint_items),
        "shard_index_rows": len(index_rows),
        "summary_rows": len(summary_rows),
        "shard_cell_rows": total_shard_rows,
        "requested_city_hours": sum(
            len(str(row["cities"]).split("|")) for row in bindings
        ),
    }
    if counts != expected_counts:
        _fail("HRRR run-seal counts differ from bound artifacts")


def _validate_step2_gate(
    gate_path: Path,
    artifacts: Mapping[str, Path],
    *,
    repo_root: Path,
) -> None:
    gate = _json_object(gate_path, label="machine-readable Step 2 gate")
    exact = {
        "schema_version": 1,
        "decision_id": D0035_DECISION_ID,
        "implementation_decision_id": "D0036",
        "status": "PASS",
        "scientific_gate_eligible": True,
        "all_checks_pass": True,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
    }
    for field, expected in exact.items():
        if gate.get(field) != expected:
            _fail(f"machine-readable Step 2 gate has stale {field}")
    checks = gate.get("checks")
    counts = gate.get("counts")
    if (
        not isinstance(checks, list)
        or not checks
        or not all(
            isinstance(item, Mapping)
            and item.get("pass") is True
            and str(item.get("check", "")).strip()
            for item in checks
        )
        or not isinstance(counts, Mapping)
        or _int(counts.get("step2_checks"), label="Step 2 check count")
        != len(checks)
        or _int(counts.get("step2_checks_passed"), label="Step 2 passed checks")
        != len(checks)
    ):
        _fail("machine-readable Step 2 checks are not a complete PASS")

    checks_path = _inside_repo(
        gate.get("checks_path"),
        repo_root=repo_root,
        label="Step 2 checks_path",
        require_relative=True,
    )
    checks_sha = sha256_file(checks_path)
    if gate.get("checks_sha256") != checks_sha:
        _fail("machine-readable Step 2 checks hash is stale")

    hashes = gate.get("artifact_sha256")
    if not isinstance(hashes, Mapping) or not hashes:
        _fail("machine-readable Step 2 gate has no artifact hash ledger")
    resolved_ledger: dict[Path, str] = {}
    for raw_path, raw_hash in hashes.items():
        path = _inside_repo(
            raw_path,
            repo_root=repo_root,
            label=f"Step 2 artifact {raw_path}",
            require_relative=True,
        )
        if path == gate_path.resolve():
            _fail("machine-readable Step 2 gate may not hash itself")
        expected_hash = _require_sha256(
            raw_hash, label=f"Step 2 artifact {raw_path} sha256"
        )
        if path in resolved_ledger or sha256_file(path) != expected_hash:
            _fail(f"machine-readable Step 2 artifact changed: {raw_path}")
        resolved_ledger[path] = expected_hash
    if resolved_ledger.get(checks_path) != checks_sha:
        _fail("Step 2 checks are absent from the artifact ledger")
    for name in (
        "d0035_combined_validation",
        "d0035_run_record",
        "hrrr_run_seal",
        "hrrr_manifest",
        "hrrr_shard_index",
        "hrrr_summary",
    ):
        path = artifacts[name]
        if resolved_ledger.get(path) != sha256_file(path):
            _fail(f"Step 2 artifact ledger does not bind canonical {name}")

    d0035_run = _json_object(
        artifacts["d0035_run_record"], label="D0035 run record"
    )
    upstream = gate.get("upstream_d0035")
    if not isinstance(upstream, Mapping):
        _fail("Step 2 gate lacks its upstream D0035 record")
    upstream_path = _inside_repo(
        upstream.get("run_record_path"),
        repo_root=repo_root,
        label="Step 2 upstream D0035 run_record_path",
        require_relative=True,
    )
    if (
        upstream.get("status") != D0035_PASS_STATUS
        or upstream.get("scientific_gate_eligible") is not True
        or upstream.get("algorithm_version") != "d0035-l1b-dmrpp-pass-stream-v4"
        or upstream_path != artifacts["d0035_run_record"]
        or upstream.get("run_record_sha256") != sha256_file(upstream_path)
        or upstream.get("provenance_counts") != d0035_run.get("provenance_counts")
        or upstream.get("provenance_sha256") != d0035_run.get("provenance_sha256")
    ):
        _fail("Step 2 upstream D0035 binding is stale")

    seal = _json_object(artifacts["hrrr_run_seal"], label="HRRR run seal")
    hrrr = gate.get("hrrr_run_seal")
    if not isinstance(hrrr, Mapping):
        _fail("Step 2 gate lacks its exact HRRR run seal")
    hrrr_path = _inside_repo(
        hrrr.get("path"),
        repo_root=repo_root,
        label="Step 2 HRRR run-seal path",
        require_relative=True,
    )
    if (
        hrrr.get("status") != HRRR_PASS_STATUS
        or hrrr_path != artifacts["hrrr_run_seal"]
        or hrrr.get("sha256") != sha256_file(hrrr_path)
        or hrrr.get("manifest_canonical_sha256")
        != seal.get("manifest_canonical_sha256")
        or hrrr.get("frozen_domain_sha256") != seal.get("frozen_domain_sha256")
        or hrrr.get("counts") != seal.get("counts")
    ):
        _fail("Step 2 exact HRRR binding is stale")

    combined = _json_object(
        artifacts["d0035_combined_validation"], label="D0035 combined validation"
    )
    physical = _int(
        counts.get("near_nadir_physical_passes"),
        label="Step 2 near_nadir_physical_passes",
    )
    expected_total = _float(
        counts.get("expected_pass_equivalents_total"),
        label="Step 2 expected_pass_equivalents_total",
    )
    planning_floor = _int(
        counts.get("planning_pass_count_floor"),
        label="Step 2 planning_pass_count_floor",
    )
    if (
        physical != int(combined["geometry_passing_candidate_count"])
        or not math.isclose(
            expected_total,
            float(combined["planning_pass_equivalent_sum"]),
            rel_tol=0,
            abs_tol=1e-10,
        )
        or planning_floor != int(combined["planning_pass_equivalent_floor"])
    ):
        _fail("Step 2 certified counts differ from the D0035 gate")


def _validate_d0047_step2_gate(
    gate_path: Path,
    artifacts: Mapping[str, Path],
    *,
    repo_root: Path,
    combined: Mapping[str, Any],
    d0047_run: Mapping[str, Any],
    expected_hrrr_profile_binding: Mapping[str, Any],
) -> None:
    gate = _json_object(gate_path, label="D0047 machine-readable Step 2 gate")
    exact = {
        "schema_version": 1,
        "decision_id": D0047_DECISION_ID,
        "implementation_decision_id": D0047_DECISION_ID,
        "analysis_profile": D0047_ANALYSIS_PROFILE,
        "scientific_gate_scope": D0047_SCIENTIFIC_GATE_SCOPE,
        "profile_scope_label": D0047_PROFILE_SCOPE_LABEL,
        "planning_count_status": D0047_CERTIFIED_COUNT_STATUS,
        "status": "PASS",
        "scientific_gate_eligible": True,
        "all_checks_pass": True,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
    }
    for field, expected in exact.items():
        if gate.get(field) != expected:
            _fail(f"D0047 Step 2 gate has stale {field}")
    checks = gate.get("checks")
    counts = gate.get("counts")
    if (
        not isinstance(checks, list)
        or not checks
        or not all(
            isinstance(item, Mapping)
            and item.get("pass") is True
            and str(item.get("check", "")).strip()
            for item in checks
        )
        or not isinstance(counts, Mapping)
        or _int(counts.get("step2_checks"), label="D0047 Step 2 check count")
        != len(checks)
        or _int(
            counts.get("step2_checks_passed"),
            label="D0047 Step 2 passed checks",
        )
        != len(checks)
    ):
        _fail("D0047 Step 2 checks are not a complete PASS")
    checks_path = _inside_repo(
        gate.get("checks_path"),
        repo_root=repo_root,
        label="D0047 Step 2 checks_path",
        require_relative=True,
    )
    checks_sha = sha256_file(checks_path)
    if gate.get("checks_sha256") != checks_sha:
        _fail("D0047 Step 2 checks hash is stale")

    hashes = gate.get("artifact_sha256")
    if not isinstance(hashes, Mapping) or not hashes:
        _fail("D0047 Step 2 gate has no artifact hash ledger")
    resolved_ledger: dict[Path, str] = {}
    for raw_path, raw_hash in hashes.items():
        path = _inside_repo(
            raw_path,
            repo_root=repo_root,
            label=f"D0047 Step 2 artifact {raw_path}",
            require_relative=True,
        )
        if path == gate_path.resolve():
            _fail("D0047 Step 2 gate may not hash itself")
        expected_hash = _require_sha256(
            raw_hash, label=f"D0047 Step 2 artifact {raw_path} sha256"
        )
        if path in resolved_ledger or sha256_file(path) != expected_hash:
            _fail(f"D0047 Step 2 artifact changed: {raw_path}")
        resolved_ledger[path] = expected_hash
    if resolved_ledger.get(checks_path) != checks_sha:
        _fail("D0047 Step 2 checks are absent from the artifact ledger")
    for name in (
        "d0047_profile_validation",
        "d0047_combined_validation",
        "d0047_run_record",
        "candidate_availability_ledger",
        "archive_unavailable_pre_geometry_exclusions",
        "archive_available_attrition_summary",
        "retained_city_scene_links",
        "hrrr_run_seal",
        "hrrr_manifest",
        "hrrr_shard_index",
        "hrrr_summary",
    ):
        path = artifacts[name]
        if resolved_ledger.get(path) != sha256_file(path):
            _fail(f"D0047 Step 2 ledger does not bind canonical {name}")

    f25_path = (
        repo_root
        / "data/processed/v2/task1/"
        "step2_definitive_l1b_geo_D0047_archive_available/figures/"
        "F2.5_definitive_conditions.png"
    ).resolve()
    if not f25_path.is_file() or resolved_ledger.get(f25_path) != sha256_file(f25_path):
        _fail("D0047 Step 2 PASS does not hash-bind definitive F2.5")

    upstream = gate.get("upstream_quality_profile")
    if not isinstance(upstream, Mapping):
        _fail("D0047 Step 2 gate lacks its upstream quality profile")
    upstream_path = _inside_repo(
        upstream.get("run_record_path"),
        repo_root=repo_root,
        label="D0047 Step 2 upstream run_record_path",
        require_relative=True,
    )
    upstream_exact = {
        "decision_id": D0047_DECISION_ID,
        "status": D0047_PASS_STATUS,
        "scientific_gate_eligible": True,
        "analysis_profile": D0047_ANALYSIS_PROFILE,
        "scientific_gate_scope": D0047_SCIENTIFIC_GATE_SCOPE,
        "profile_scope_label": D0047_PROFILE_SCOPE_LABEL,
        "algorithm_version": D0047_ALGORITHM_VERSION,
        "run_record_sha256": sha256_file(upstream_path),
        "provenance_counts": d0047_run.get("provenance_counts"),
        "provenance_sha256": d0047_run.get("provenance_sha256"),
        "candidate_availability_ledger_path": artifacts[
            "candidate_availability_ledger"
        ].relative_to(repo_root).as_posix(),
        "candidate_availability_ledger_sha256": sha256_file(
            artifacts["candidate_availability_ledger"]
        ),
        "exclusion_summary_path": artifacts[
            "archive_unavailable_pre_geometry_exclusions"
        ].relative_to(repo_root).as_posix(),
        "exclusion_summary_sha256": sha256_file(
            artifacts["archive_unavailable_pre_geometry_exclusions"]
        ),
        "attrition_summary_path": artifacts[
            "archive_available_attrition_summary"
        ].relative_to(repo_root).as_posix(),
        "attrition_summary_sha256": sha256_file(
            artifacts["archive_available_attrition_summary"]
        ),
        "retained_links_path": artifacts["retained_city_scene_links"]
        .relative_to(repo_root)
        .as_posix(),
        "retained_links_sha256": sha256_file(artifacts["retained_city_scene_links"]),
        "original_exhaustive_gate_status": D0047_ORIGINAL_STOP,
        "restored_archive_sensitivity_required": True,
    }
    if upstream_path != artifacts["d0047_run_record"]:
        _fail("D0047 Step 2 gate points to a different upstream run record")
    for field, expected in upstream_exact.items():
        if upstream.get(field) != expected:
            _fail(f"D0047 Step 2 upstream profile has stale {field}")

    seal = _json_object(artifacts["hrrr_run_seal"], label="D0047 HRRR run seal")
    hrrr = gate.get("hrrr_run_seal")
    if not isinstance(hrrr, Mapping):
        _fail("D0047 Step 2 gate lacks its exact HRRR run seal")
    hrrr_path = _inside_repo(
        hrrr.get("path"),
        repo_root=repo_root,
        label="D0047 Step 2 HRRR run-seal path",
        require_relative=True,
    )
    if (
        hrrr.get("status") != D0047_HRRR_PASS_STATUS
        or hrrr_path != artifacts["hrrr_run_seal"]
        or hrrr.get("sha256") != sha256_file(hrrr_path)
        or hrrr.get("manifest_canonical_sha256")
        != seal.get("manifest_canonical_sha256")
        or hrrr.get("frozen_domain_sha256") != seal.get("frozen_domain_sha256")
        or hrrr.get("counts") != seal.get("counts")
        or hrrr.get("profile_binding") != dict(expected_hrrr_profile_binding)
        or hrrr.get("profile_binding_sha256")
        != _json_sha256(dict(expected_hrrr_profile_binding))
    ):
        _fail("D0047 Step 2 exact HRRR binding is stale")

    physical = _int(
        counts.get("near_nadir_physical_passes"),
        label="D0047 Step 2 near_nadir_physical_passes",
    )
    expected_total = _float(
        counts.get("expected_pass_equivalents_total"),
        label="D0047 Step 2 expected_pass_equivalents_total",
    )
    planning_floor = _int(
        counts.get("planning_pass_count_floor"),
        label="D0047 Step 2 planning_pass_count_floor",
    )
    frozen_counts = {
        "original_metadata_candidates": 942,
        "excluded_pre_geometry_candidates": 31,
        "retained_geometry_candidates": 911,
    }
    for field, expected in frozen_counts.items():
        if _int(counts.get(field), label=f"D0047 Step 2 {field}") != expected:
            _fail(f"D0047 Step 2 gate has stale {field}")
    if (
        physical != int(combined["geometry_passing_candidate_count"])
        or not math.isclose(
            expected_total,
            float(combined["planning_pass_equivalent_sum"]),
            rel_tol=0,
            abs_tol=1e-10,
        )
        or planning_floor != int(combined["planning_pass_equivalent_floor"])
    ):
        _fail("D0047 Step 2 certified counts differ from the quality gate")


def _validate_step3(
    run_path: Path,
    diagnostic_path: Path,
    support_path: Path,
    *,
    hrrr_summary_path: Path,
    expected_decision_id: str = D0035_DECISION_ID,
    expected_count_status: str = CERTIFIED_COUNT_STATUS,
    expected_analysis_profile: str | None = None,
    expected_scientific_scope: str | None = None,
    step2_gate_path: Path | None = None,
    hrrr_run_seal_path: Path | None = None,
) -> None:
    diagnostic = _json_object(diagnostic_path, label="Step 3 diagnostic gate")
    if diagnostic.get("decision_id") != D0027_DECISION_ID:
        _fail("Step 3 diagnostic gate is not D0027")
    if diagnostic.get("status") != "PASS":
        _fail("Step 3 diagnostic gate status is not PASS")
    if diagnostic.get("scientific_gate_eligible") is not True:
        _fail("Step 3 diagnostic gate is not scientifically eligible")
    failed = diagnostic.get("failed_check_ids")
    if failed != []:
        _fail("Step 3 diagnostic gate has failed required checks")
    passed = _int(
        diagnostic.get("passed_required_checks"),
        label="Step 3 passed_required_checks",
    )
    total = _int(
        diagnostic.get("total_required_checks"),
        label="Step 3 total_required_checks",
    )
    actual_n = _int(
        diagnostic.get("actual_n_passes"), label="Step 3 actual_n_passes"
    )
    if total <= 0 or passed != total or actual_n <= 0:
        _fail("Step 3 diagnostic check population is not a complete PASS")
    if not isinstance(diagnostic.get("thresholds"), Mapping):
        _fail("Step 3 diagnostic gate lacks frozen D0027 thresholds")

    run = _json_object(run_path, label="Step 3 run record")
    decisions = run.get("decision_ids")
    if not isinstance(decisions, list) or not {
        expected_decision_id,
        D0027_DECISION_ID,
    }.issubset(set(map(str, decisions))):
        _fail(
            "Step 3 run record lacks the required "
            f"{expected_decision_id} and D0027 decisions"
        )
    if (
        run.get("status") != "ready_for_frozen_full_profile"
        or run.get("count_status") != expected_count_status
        or run.get("step2_gate") != "PASS"
        or run.get("lst_opened") is not False
        or run.get("thermal_opened") is not False
        or run.get("record_2026_opened") is not False
        or str(run.get("holdout_status", "")).upper() != "UNSELECTED"
        or run.get("frozen_years") != "2018-2025"
        or _int(run.get("actual_n_passes"), label="Step 3 run actual_n_passes")
        != actual_n
        or run.get("diagnostic_gate") != diagnostic
    ):
        _fail("Step 3 run record is stale or does not embed the PASS diagnostic")
    if run.get("hrrr_summary_sha256") != sha256_file(hrrr_summary_path):
        _fail("Step 3 run record does not bind the canonical HRRR summary")
    if expected_analysis_profile is not None and (
        run.get("analysis_profile") != expected_analysis_profile
        or run.get("scientific_gate_scope") != expected_scientific_scope
    ):
        _fail("Step 3 run record has a stale archive-profile scope")
    if step2_gate_path is not None and run.get(
        "step2_gate_record_sha256"
    ) != sha256_file(step2_gate_path):
        _fail("Step 3 run record does not bind the canonical Step 2 gate")
    if hrrr_run_seal_path is not None and run.get(
        "hrrr_run_seal_sha256"
    ) != sha256_file(hrrr_run_seal_path):
        _fail("Step 3 run record does not bind the canonical HRRR seal")
    for field in ("planning_sha256", "config_sha256", "template_sha256"):
        _require_sha256(run.get(field), label=f"Step 3 run {field}")

    fields, rows = _read_csv(support_path, label="T3.1 model-support table")
    required = {
        "model",
        "effect_size_k",
        "planning_n_passes",
        "power_at_planning_n",
        "target_power",
        "statistically_supportable_at_planning_n",
        "count_status",
        "scientific_gate_eligible",
        "smallest_detectable_effect_at_planning_n_k",
    }
    if required - set(fields) or not rows:
        _fail("T3.1 model-support table is empty or lacks the frozen schema")
    models: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        model = str(row.get("model", "")).strip()
        if not model:
            _fail(f"T3.1 row {row_number} has no model")
        models.add(model)
        if row.get("count_status") != expected_count_status:
            _fail(f"T3.1 row {row_number} uses an uncertified count")
        if not _boolean_text(
            row.get("scientific_gate_eligible"),
            label=f"T3.1 row {row_number} scientific_gate_eligible",
        ):
            _fail(f"T3.1 row {row_number} is not scientifically eligible")
        _boolean_text(
            row.get("statistically_supportable_at_planning_n"),
            label=f"T3.1 row {row_number} statistically_supportable",
        )
        if (
            _int(
                row.get("planning_n_passes"),
                label=f"T3.1 row {row_number} planning_n_passes",
            )
            != actual_n
        ):
            _fail(f"T3.1 row {row_number} differs from the diagnostic count")
        effect = _float(
            row.get("effect_size_k"), label=f"T3.1 row {row_number} effect_size_k"
        )
        power = _float(
            row.get("power_at_planning_n"),
            label=f"T3.1 row {row_number} power_at_planning_n",
        )
        target = _float(
            row.get("target_power"), label=f"T3.1 row {row_number} target_power"
        )
        if effect < 0 or not (0 <= power <= 1) or not (0 < target <= 1):
            _fail(f"T3.1 row {row_number} contains invalid power quantities")
    if not {"demand_by_dryness", "demand_by_dryness_by_time"}.issubset(models):
        _fail("T3.1 lacks both frozen candidate model families")


def validate_d0047_task2_activation_contract(gate: Mapping[str, Any]) -> None:
    """Require the scope-qualified D0047 contract; a generic PASS is invalid."""

    exact = {
        "schema_version": D0047_CANONICAL_TASK1_GATE_SCHEMA_VERSION,
        "task1_gate": CANONICAL_TASK1_GATE_STATUS,
        "profile_gate": D0047_PROFILE_GATE_STATUS,
        "analysis_profile": D0047_ANALYSIS_PROFILE,
        "scientific_gate_eligible": True,
        "scientific_gate_scope": D0047_SCIENTIFIC_GATE_SCOPE,
        "estimand": D0047_ESTIMAND,
        "candidate_ledger_count": D0047_ORIGINAL_CANDIDATES,
        "archive_unavailable_pre_geometry_count": D0047_EXCLUDED_CANDIDATES,
        "retained_geometry_candidate_count": D0047_RETAINED_CANDIDATES,
        "original_exhaustive_gate_status": D0047_ORIGINAL_STOP,
        "latest_unavailability_confirmation": D0047_LATEST_UNAVAILABILITY_STOP,
        "restored_archive_sensitivity_required": True,
        "decision_ids": [
            D0027_DECISION_ID,
            D0035_DECISION_ID,
            "D0046",
            D0047_DECISION_ID,
        ],
        "definitive_step2": "complete",
        "hrrr_exact_acquisition_fetch": "complete",
        "definitive_step3": "complete",
        "lst_or_thermal_layers_opened": 0,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "season_2026": "UNOPENED",
    }
    for field, expected in exact.items():
        if gate.get(field) != expected:
            _fail(f"Task 2 requires exact D0047 activation field {field}")


def _validate_d0047_canonical_task1_pass(
    gate: Mapping[str, Any],
    *,
    gate_path: Path,
    repo_root: Path,
) -> dict[str, Path]:
    validate_d0047_task2_activation_contract(gate)
    artifacts = _binding_paths(
        gate,
        repo_root=repo_root,
        gate_path=gate_path,
        required_artifact_names=D0047_REQUIRED_ARTIFACT_NAMES,
    )
    expected_t3_path = artifacts["t3_model_support"].relative_to(repo_root).as_posix()
    if gate.get("t3_model_support_path") != expected_t3_path:
        _fail("D0047 canonical Task 1 gate T3.1 path differs from its binding")

    _validate_d0035_preserved_stop(
        artifacts["d0035_exhaustive_stop_combined_validation"],
        artifacts["d0035_exhaustive_stop_run_record"],
        repo_root=repo_root,
    )
    d0046_scene_keys = _validate_d0046_unavailability(
        artifacts, repo_root=repo_root
    )
    combined, d0047_run = _validate_d0047_quality_profile(
        artifacts,
        repo_root=repo_root,
        d0046_scene_keys=d0046_scene_keys,
    )
    hrrr_profile_binding = {
        "decision_id": D0047_DECISION_ID,
        "analysis_profile": D0047_ANALYSIS_PROFILE,
        "scientific_gate_scope": D0047_SCIENTIFIC_GATE_SCOPE,
        "profile_scope_label": D0047_PROFILE_SCOPE_LABEL,
        "geometry_passing_candidate_count": int(
            combined["geometry_passing_candidate_count"]
        ),
        "combined_validation_path": artifacts["d0047_combined_validation"]
        .relative_to(repo_root)
        .as_posix(),
        "combined_validation_sha256": sha256_file(
            artifacts["d0047_combined_validation"]
        ),
        "upstream_run_record_path": artifacts["d0047_run_record"]
        .relative_to(repo_root)
        .as_posix(),
        "upstream_run_record_sha256": sha256_file(artifacts["d0047_run_record"]),
        "candidate_availability_ledger_path": artifacts[
            "candidate_availability_ledger"
        ].relative_to(repo_root).as_posix(),
        "candidate_availability_ledger_sha256": sha256_file(
            artifacts["candidate_availability_ledger"]
        ),
        "exclusion_summary_path": artifacts[
            "archive_unavailable_pre_geometry_exclusions"
        ].relative_to(repo_root).as_posix(),
        "exclusion_summary_sha256": sha256_file(
            artifacts["archive_unavailable_pre_geometry_exclusions"]
        ),
    }
    _validate_hrrr(
        artifacts["hrrr_run_seal"],
        artifacts["hrrr_manifest"],
        artifacts["hrrr_shard_index"],
        artifacts["hrrr_summary"],
        repo_root=repo_root,
        gate_path=gate_path,
        expected_status=D0047_HRRR_PASS_STATUS,
        expected_profile_binding=hrrr_profile_binding,
    )
    _validate_d0047_step2_gate(
        artifacts["step2_gate"],
        artifacts,
        repo_root=repo_root,
        combined=combined,
        d0047_run=d0047_run,
        expected_hrrr_profile_binding=hrrr_profile_binding,
    )
    _validate_step3(
        artifacts["step3_run_record"],
        artifacts["step3_diagnostic_gate"],
        artifacts["t3_model_support"],
        hrrr_summary_path=artifacts["hrrr_summary"],
        expected_decision_id=D0047_DECISION_ID,
        expected_count_status=D0047_CERTIFIED_COUNT_STATUS,
        expected_analysis_profile=D0047_ANALYSIS_PROFILE,
        expected_scientific_scope=D0047_SCIENTIFIC_GATE_SCOPE,
        step2_gate_path=artifacts["step2_gate"],
        hrrr_run_seal_path=artifacts["hrrr_run_seal"],
    )
    return artifacts


def validate_canonical_task1_pass(
    gate: Mapping[str, Any],
    *,
    gate_path: str | os.PathLike[str],
    repo_root: str | os.PathLike[str] = REPO_ROOT,
) -> dict[str, Path]:
    """Validate a Task 1 PASS and every bound upstream artifact.

    A mapping supplied by a caller is never trusted on its own.  The selected
    D0035 or D0047 artifact set, hashes, nested decisions, and HRRR shard
    bindings are independently recomputed from files under ``repo_root``.
    """

    root = Path(repo_root).expanduser().resolve()
    if not root.is_dir():
        _fail("repository root does not exist")
    resolved_gate_path = _inside_repo(
        gate_path,
        repo_root=root,
        label="canonical Task 1 gate path",
        require_relative=False,
        require_file=False,
    )
    d0047_markers = (
        gate.get("schema_version") == D0047_CANONICAL_TASK1_GATE_SCHEMA_VERSION,
        gate.get("profile_gate") is not None,
        gate.get("analysis_profile") == D0047_ANALYSIS_PROFILE,
        gate.get("scientific_gate_scope") == D0047_SCIENTIFIC_GATE_SCOPE,
    )
    if any(d0047_markers):
        return _validate_d0047_canonical_task1_pass(
            gate,
            gate_path=resolved_gate_path,
            repo_root=root,
        )
    exact = {
        "schema_version": CANONICAL_TASK1_GATE_SCHEMA_VERSION,
        "task1_gate": CANONICAL_TASK1_GATE_STATUS,
        "scientific_gate_eligible": True,
        "decision_ids": [D0027_DECISION_ID, D0035_DECISION_ID],
        "definitive_step2": "complete",
        "hrrr_exact_acquisition_fetch": "complete",
        "definitive_step3": "complete",
        "lst_or_thermal_layers_opened": 0,
        "holdout_status": "UNSELECTED",
        "season_2026": "UNOPENED",
    }
    for field, expected in exact.items():
        if gate.get(field) != expected:
            _fail(f"canonical Task 1 gate has stale {field}")
    artifacts = _binding_paths(gate, repo_root=root, gate_path=resolved_gate_path)
    expected_t3_path = artifacts["t3_model_support"].relative_to(root).as_posix()
    if gate.get("t3_model_support_path") != expected_t3_path:
        _fail("canonical Task 1 gate T3.1 path differs from its artifact binding")

    _validate_d0035(
        artifacts["d0035_combined_validation"],
        artifacts["d0035_run_record"],
        repo_root=root,
    )
    _validate_hrrr(
        artifacts["hrrr_run_seal"],
        artifacts["hrrr_manifest"],
        artifacts["hrrr_shard_index"],
        artifacts["hrrr_summary"],
        repo_root=root,
        gate_path=resolved_gate_path,
    )
    _validate_step2_gate(
        artifacts["step2_gate"], artifacts, repo_root=root
    )
    _validate_step3(
        artifacts["step3_run_record"],
        artifacts["step3_diagnostic_gate"],
        artifacts["t3_model_support"],
        hrrr_summary_path=artifacts["hrrr_summary"],
    )
    return artifacts


def write_canonical_task1_pass(
    artifact_paths: Mapping[str, str | os.PathLike[str]],
    *,
    gate_path: str | os.PathLike[str],
    repo_root: str | os.PathLike[str] = REPO_ROOT,
) -> Path:
    """Atomically write PASS only after the entire bound chain validates.

    Existing canonical gates are never overwritten.  Callers normally use
    :func:`write_default_canonical_task1_pass` after definitive Step 3 has
    finished and its D0027 diagnostic status is PASS.
    """

    root = Path(repo_root).expanduser().resolve()
    target = _inside_repo(
        gate_path,
        repo_root=root,
        label="canonical Task 1 gate output",
        require_relative=False,
        require_file=False,
    )
    if target.exists():
        _fail("canonical Task 1 gate already exists; refusing to overwrite it")
    if set(map(str, artifact_paths)) != set(REQUIRED_ARTIFACT_NAMES):
        _fail("writer requires exactly the ten canonical Task 1 artifacts")
    bindings: dict[str, dict[str, str]] = {}
    for name in REQUIRED_ARTIFACT_NAMES:
        path = _inside_repo(
            artifact_paths[name],
            repo_root=root,
            label=f"writer artifact {name}",
            require_relative=False,
        )
        if path == target:
            _fail(f"writer artifact {name} may not be the gate output")
        bindings[name] = {
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
        }
    payload: dict[str, Any] = {
        "schema_version": CANONICAL_TASK1_GATE_SCHEMA_VERSION,
        "task1_gate": CANONICAL_TASK1_GATE_STATUS,
        "scientific_gate_eligible": True,
        "decision_ids": [D0027_DECISION_ID, D0035_DECISION_ID],
        "definitive_step2": "complete",
        "hrrr_exact_acquisition_fetch": "complete",
        "definitive_step3": "complete",
        "lst_or_thermal_layers_opened": 0,
        "holdout_status": "UNSELECTED",
        "season_2026": "UNOPENED",
        "t3_model_support_path": bindings["t3_model_support"]["path"],
        "artifacts": bindings,
    }
    validate_canonical_task1_pass(payload, gate_path=target, repo_root=root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def write_default_canonical_task1_pass(
    *,
    repo_root: str | os.PathLike[str] = REPO_ROOT,
    gate_path: str | os.PathLike[str] = "data/processed/v2/task1/TASK1_GATE.json",
) -> Path:
    """Validate the frozen default artifact chain and write its canonical PASS."""

    return write_canonical_task1_pass(
        DEFAULT_TASK1_ARTIFACT_PATHS,
        gate_path=gate_path,
        repo_root=repo_root,
    )


def write_d0047_canonical_task1_pass(
    artifact_paths: Mapping[str, str | os.PathLike[str]],
    *,
    gate_path: str | os.PathLike[str],
    repo_root: str | os.PathLike[str] = REPO_ROOT,
) -> Path:
    """Write the scope-qualified D0047 PASS after every bound gate validates."""

    root = Path(repo_root).expanduser().resolve()
    target = _inside_repo(
        gate_path,
        repo_root=root,
        label="D0047 canonical Task 1 gate output",
        require_relative=False,
        require_file=False,
    )
    if target.exists():
        _fail("canonical Task 1 gate already exists; refusing to overwrite it")
    if set(map(str, artifact_paths)) != set(D0047_REQUIRED_ARTIFACT_NAMES):
        _fail("D0047 writer requires exactly the frozen D0047 artifact set")
    bindings: dict[str, dict[str, str]] = {}
    for name in D0047_REQUIRED_ARTIFACT_NAMES:
        path = _inside_repo(
            artifact_paths[name],
            repo_root=root,
            label=f"D0047 writer artifact {name}",
            require_relative=False,
        )
        if path == target:
            _fail(f"D0047 writer artifact {name} may not be the gate output")
        bindings[name] = {
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
        }
    payload: dict[str, Any] = {
        "schema_version": D0047_CANONICAL_TASK1_GATE_SCHEMA_VERSION,
        "task1_gate": CANONICAL_TASK1_GATE_STATUS,
        "profile_gate": D0047_PROFILE_GATE_STATUS,
        "analysis_profile": D0047_ANALYSIS_PROFILE,
        "scientific_gate_eligible": True,
        "scientific_gate_scope": D0047_SCIENTIFIC_GATE_SCOPE,
        "estimand": D0047_ESTIMAND,
        "candidate_ledger_count": D0047_ORIGINAL_CANDIDATES,
        "archive_unavailable_pre_geometry_count": D0047_EXCLUDED_CANDIDATES,
        "retained_geometry_candidate_count": D0047_RETAINED_CANDIDATES,
        "original_exhaustive_gate_status": D0047_ORIGINAL_STOP,
        "latest_unavailability_confirmation": D0047_LATEST_UNAVAILABILITY_STOP,
        "restored_archive_sensitivity_required": True,
        "decision_ids": [
            D0027_DECISION_ID,
            D0035_DECISION_ID,
            "D0046",
            D0047_DECISION_ID,
        ],
        "definitive_step2": "complete",
        "hrrr_exact_acquisition_fetch": "complete",
        "definitive_step3": "complete",
        "lst_or_thermal_layers_opened": 0,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "season_2026": "UNOPENED",
        "t3_model_support_path": bindings["t3_model_support"]["path"],
        "artifacts": bindings,
    }
    validate_canonical_task1_pass(payload, gate_path=target, repo_root=root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def write_default_d0047_canonical_task1_pass(
    *,
    repo_root: str | os.PathLike[str] = REPO_ROOT,
    gate_path: str | os.PathLike[str] = "data/processed/v2/task1/TASK1_GATE.json",
) -> Path:
    """Validate the append-only D0047 chain and write its canonical PASS."""

    return write_d0047_canonical_task1_pass(
        D0047_TASK1_ARTIFACT_PATHS,
        gate_path=gate_path,
        repo_root=repo_root,
    )


__all__ = [
    "CANONICAL_TASK1_GATE_SCHEMA_VERSION",
    "DEFAULT_TASK1_ARTIFACT_PATHS",
    "D0047_ANALYSIS_PROFILE",
    "D0047_CANONICAL_TASK1_GATE_SCHEMA_VERSION",
    "D0047_PROFILE_GATE_STATUS",
    "D0047_REQUIRED_ARTIFACT_NAMES",
    "D0047_SCIENTIFIC_GATE_SCOPE",
    "D0047_TASK1_ARTIFACT_PATHS",
    "REQUIRED_ARTIFACT_NAMES",
    "Task1GateError",
    "sha256_file",
    "validate_canonical_task1_pass",
    "validate_d0047_task2_activation_contract",
    "write_canonical_task1_pass",
    "write_default_canonical_task1_pass",
    "write_d0047_canonical_task1_pass",
    "write_default_d0047_canonical_task1_pass",
]
