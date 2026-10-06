"""Scoped Task-1 gate for the D0056 time-of-day-only continuation.

This module is deliberately separate from :mod:`task1_pass_gate`.  R0015's
original demand-by-dryness Step-2 gate is a valid ``STOP`` and must remain one.
D0056 permits a different, guide-prescribed estimand only: the late-afternoon
minus late-morning cooling contrast.  The writer below can therefore issue only
``PASS_TIME_OF_DAY_ONLY`` and only after it has revalidated the immutable R0015
STOP plus the separately namespaced D0056 Step-3 evidence.

Validation is local and non-result-bearing.  It reads JSON/CSV metadata and
hashes named files; it never opens a thermal raster, chooses a holdout, contacts
the network, or reads a 2026 observation.
"""

from __future__ import annotations

from collections.abc import Mapping
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any
import uuid


REPO_ROOT = Path(__file__).resolve().parents[2]

DECISION_ID = "D0056"
SCHEMA_VERSION = 1
TASK1_GATE_STATUS = "PASS_TIME_OF_DAY_ONLY"
PROFILE_GATE_STATUS = "PASS_D0056_TIME_OF_DAY_ONLY_TASK1"
ANALYSIS_PROFILE = "D0056_time_of_day_only"
SCIENTIFIC_GATE_SCOPE = "time_of_day_only_archive_available_D0047"
PRIMARY_ESTIMAND = (
    "late_afternoon_16_18_minus_late_morning_10_12_cooling_contrast_k"
)
INTERACTION_STATUS = "STOP_REPORTED_R0015"
HYDROCLIMATE_STATUS = "NOT_ESTIMABLE_R0015_SUPPORT_STOP"
STEP3_PASS_STATUS = "PASS_TIME_OF_DAY_ONLY_STEP3"
ORIGINAL_STEP2_STATUS = "STOP"
ORIGINAL_STEP2_DECISION_ID = "D0047"
ORIGINAL_STEP2_ANALYSIS_PROFILE = "D0047_archive_available"
ORIGINAL_STEP2_SCOPE = "archive_available_only"
ORIGINAL_STEP2_PATH = (
    "data/processed/v2/task1/"
    "step2_definitive_l1b_geo_D0047_archive_available/step2_gate_record.json"
)
DEFAULT_GATE_PATH = "data/processed/v2/task1/TASK1_GATE_TIME_OF_DAY_ONLY.json"
DEFAULT_STEP3_ROOT = (
    "data/processed/v2/task1/step3_time_of_day_only_D0056"
)
ORIGINAL_PLANNING_PATH = (
    "data/processed/v2/task1/"
    "step2_definitive_l1b_geo_D0047_archive_available/step3_planning_count.json"
)
ORIGINAL_TEMPLATE_PATH = (
    "data/processed/v2/task1/"
    "step2_definitive_l1b_geo_D0047_archive_available/"
    "tables/step3_empirical_template.csv"
)
CONFIG_PATH = "configs/v2_cities.toml"
STEP3_GATE_PATH = f"{DEFAULT_STEP3_ROOT}/step3_time_of_day_gate.json"
STEP3_RUN_PATH = f"{DEFAULT_STEP3_ROOT}/run_record.json"
STEP3_MODEL_SUPPORT_PATH = (
    f"{DEFAULT_STEP3_ROOT}/tables/T3T.1_time_of_day_model_support.csv"
)
STEP3_LOCO_SUPPORT_PATH = (
    f"{DEFAULT_STEP3_ROOT}/tables/T3T.2_leave_one_city_out_support.csv"
)
STEP3_STRATA_CENSUS_PATH = (
    f"{DEFAULT_STEP3_ROOT}/tables/T3T.3_empirical_strata_census.csv"
)
STEP3_CHECKS_PATH = f"{DEFAULT_STEP3_ROOT}/tables/step3_time_of_day_checks.csv"

EXPECTED_ORIGINAL_COUNTS = {
    "original_metadata_candidates": 942,
    "excluded_pre_geometry_candidates": 31,
    "retained_geometry_candidates": 911,
    "near_nadir_physical_passes": 219,
    "planning_pass_count_floor": 159,
    "step2_checks": 6,
    "step2_checks_passed": 6,
}
EXPECTED_PASS_EQUIVALENTS = 159.0870840462331

REQUIRED_ARTIFACT_NAMES = (
    "original_interaction_step2_gate",
    "step3_time_of_day_gate",
    "step3_time_of_day_run_record",
    "t3t1_time_of_day_model_support",
    "t3t2_leave_one_city_out_support",
)
DEFAULT_ARTIFACT_PATHS = {
    "original_interaction_step2_gate": ORIGINAL_STEP2_PATH,
    "step3_time_of_day_gate": STEP3_GATE_PATH,
    "step3_time_of_day_run_record": STEP3_RUN_PATH,
    "t3t1_time_of_day_model_support": STEP3_MODEL_SUPPORT_PATH,
    "t3t2_leave_one_city_out_support": STEP3_LOCO_SUPPORT_PATH,
}

EXPECTED_INPUT_BINDING_PATHS = {
    "planning_path": ORIGINAL_PLANNING_PATH,
    "step2_gate_record_path": ORIGINAL_STEP2_PATH,
    "template_path": ORIGINAL_TEMPLATE_PATH,
    "config_path": CONFIG_PATH,
}

EXPECTED_LOCO_SUPPORT = {
    "atlanta": (79, 57.42421755160162, 57),
    "los_angeles": (79, 54.05826500543519, 54),
    "miami": (94, 66.36341549393057, 66),
    "minneapolis_st_paul": (74, 56.51165197128533, 56),
}

EXPECTED_STRATA_CENSUS = {
    ("atlanta", "10-12"): (12, 9.158032023756974),
    ("atlanta", "12-14"): (11, 4.348856841621398),
    ("atlanta", "14-16"): (6, 4.803003914501165),
    ("atlanta", "16-18"): (11, 6.106779419865819),
    ("los_angeles", "10-12"): (8, 5.973525400594218),
    ("los_angeles", "12-14"): (12, 11.584511461961696),
    ("los_angeles", "14-16"): (13, 12.180573481045723),
    ("los_angeles", "16-18"): (15, 12.657238589195016),
    ("miami", "10-12"): (6, 4.798586743253619),
    ("miami", "12-14"): (2, 0.958259163420252),
    ("miami", "14-16"): (6, 5.160370517814997),
    ("miami", "16-18"): (2, 1.5270267580402082),
    ("minneapolis_st_paul", "10-12"): (16, 8.144491841255288),
    ("minneapolis_st_paul", "12-14"): (21, 13.683397663131153),
    ("minneapolis_st_paul", "14-16"): (22, 11.82856487977968),
    ("minneapolis_st_paul", "16-18"): (12, 8.032885182683795),
    ("phoenix", "10-12"): (13, 11.946362437907297),
    ("phoenix", "12-14"): (13, 12.569712012177305),
    ("phoenix", "14-16"): (11, 9.280805115555284),
    ("phoenix", "16-18"): (7, 4.344100598672185),
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_STEP2_LEDGER_PREFIXES = (
    "data/processed/v2/task1/",
    "data/raw/v2/ecostress/enrichment_assets/",
    "data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available/",
    "data/raw/v2/weather/",
)
_FORBIDDEN_PATH_PARTS = frozenset(
    {
        "lst",
        "temperature",
        "thermal",
        "2026",
        "holdout",
        "heldout",
    }
)


class TimeOfDayTask1GateError(ValueError):
    """Raised when the scoped D0056 evidence chain is incomplete or altered."""


def _fail(message: str) -> None:
    raise TimeOfDayTask1GateError(message)


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside_repo(
    value: str | os.PathLike[str],
    *,
    repo_root: Path,
    label: str,
    require_file: bool = True,
) -> Path:
    supplied = Path(value)
    resolved = (supplied if supplied.is_absolute() else repo_root / supplied).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        _fail(f"{label} escapes the repository")
    if require_file and not resolved.is_file():
        _fail(f"{label} does not exist: {resolved}")
    return resolved


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is unreadable JSON: {exc}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _read_csv(path: Path, *, label: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        _fail(f"{label} is unreadable CSV: {exc}")
    if not fields:
        _fail(f"{label} has no header")
    return fields, rows


def _require_sha256(value: Any, *, label: str) -> str:
    text = str(value or "")
    if not _SHA256_RE.fullmatch(text):
        _fail(f"{label} is not a lowercase SHA-256")
    return text


def _require_false(value: Any, *, label: str) -> None:
    if value is not False:
        _fail(f"{label} must be false")


def _require_true(value: Any, *, label: str) -> None:
    if value is not True:
        _fail(f"{label} must be true")


def _integer(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        _fail(f"{label} is not an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        _fail(f"{label} is not an integer")
    if isinstance(value, float) and not value.is_integer():
        _fail(f"{label} is not an integer")
    return parsed


def _finite_float(value: Any, *, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        _fail(f"{label} is not numeric")
    if not math.isfinite(parsed):
        _fail(f"{label} is not finite")
    return parsed


def _safe_nonthermal_relative_path(value: Any, *, label: str) -> str:
    text = str(value or "")
    path = Path(text)
    if not text or path.is_absolute() or ".." in path.parts:
        _fail(f"{label} must be a safe repository-relative path")
    lowered = {part.casefold() for part in path.parts}
    if lowered & _FORBIDDEN_PATH_PARTS:
        _fail(f"{label} points into a prohibited result-bearing namespace")
    return path.as_posix()


def _validate_original_step2(
    gate: Mapping[str, Any],
    *,
    gate_path: Path,
    repo_root: Path,
) -> None:
    exact = {
        "schema_version": 1,
        "decision_id": ORIGINAL_STEP2_DECISION_ID,
        "implementation_decision_id": "D0048",
        "band_mode_metadata_decision_id": "D0054",
        "analysis_profile": ORIGINAL_STEP2_ANALYSIS_PROFILE,
        "scientific_gate_scope": ORIGINAL_STEP2_SCOPE,
        "status": ORIGINAL_STEP2_STATUS,
        "planning_count_status": (
            "certified_archive_available_expected_pass_equivalent_floor"
        ),
        "profile_scope_label": (
            "archive_available_after_pre_geometry_exclusion_D0047"
        ),
        "frozen_years": "2018-2025",
        "holdout_status": "UNSELECTED",
    }
    for field, expected in exact.items():
        if gate.get(field) != expected:
            _fail(f"original interaction Step-2 gate has stale {field}")
    _require_false(
        gate.get("scientific_gate_eligible"),
        label="original interaction scientific_gate_eligible",
    )
    _require_true(gate.get("all_checks_pass"), label="original all_checks_pass")
    _require_true(gate.get("checks_pass"), label="original checks_pass")
    _require_false(gate.get("count_support_pass"), label="original count_support_pass")
    if gate.get("failure_domains") != ["count_support"]:
        _fail("original interaction gate must fail only count_support")
    for field in ("lst_opened", "thermal_opened", "record_2026_opened"):
        _require_false(gate.get(field), label=f"original Step-2 {field}")

    checks = gate.get("checks")
    if (
        not isinstance(checks, list)
        or len(checks) != EXPECTED_ORIGINAL_COUNTS["step2_checks"]
        or not all(isinstance(item, dict) and item.get("pass") is True for item in checks)
    ):
        _fail("original Step-2 integrity checks are incomplete or failed")
    counts = gate.get("counts")
    if not isinstance(counts, dict):
        _fail("original Step-2 gate has no count record")
    for field, expected in EXPECTED_ORIGINAL_COUNTS.items():
        if _integer(counts.get(field), label=f"original count {field}") != expected:
            _fail(f"original Step-2 count {field} changed")
    expected_total = _finite_float(
        counts.get("expected_pass_equivalents_total"),
        label="original expected pass-equivalents",
    )
    if not math.isclose(expected_total, EXPECTED_PASS_EQUIVALENTS, abs_tol=1e-10):
        _fail("original Step-2 expected pass-equivalent total changed")
    if math.floor(expected_total) != counts["planning_pass_count_floor"]:
        _fail("original Step-2 floor rule is inconsistent")

    upstream = gate.get("upstream_quality_profile")
    if not isinstance(upstream, dict):
        _fail("original Step-2 gate lacks its D0047 quality-profile seal")
    upstream_exact = {
        "decision_id": "D0047",
        "analysis_profile": "D0047_archive_available",
        "scientific_gate_scope": "archive_available_only",
        "status": "PASS_D0047_ARCHIVE_AVAILABLE_GEOMETRY_AND_EXHAUSTIVE_CLOUD",
        "scientific_gate_eligible": True,
        "original_exhaustive_gate_status": "STOP_D0035_INCOMPLETE_GEOMETRY",
        "restored_archive_sensitivity_required": True,
    }
    for field, expected in upstream_exact.items():
        if upstream.get(field) != expected:
            _fail(f"original Step-2 D0047 seal has stale {field}")
    hrrr = gate.get("hrrr_run_seal")
    if not isinstance(hrrr, dict) or hrrr.get("status") != (
        "PASS_EXACT_HRRR_RUN_SEAL_D0047_ARCHIVE_AVAILABLE"
    ):
        _fail("original Step-2 gate lacks the exact D0047 HRRR seal")
    if _integer(hrrr.get("counts", {}).get("manifest_items"), label="HRRR manifest items") != 413:
        _fail("original Step-2 HRRR manifest count changed")

    checks_path = _inside_repo(
        str(gate.get("checks_path", "")),
        repo_root=repo_root,
        label="original Step-2 checks",
    )
    checks_sha = _require_sha256(gate.get("checks_sha256"), label="checks_sha256")
    if sha256_file(checks_path) != checks_sha:
        _fail("original Step-2 checks changed")

    ledger = gate.get("artifact_sha256")
    if not isinstance(ledger, dict) or not ledger:
        _fail("original Step-2 gate has no artifact hash ledger")
    gate_relative = gate_path.relative_to(repo_root).as_posix()
    if gate_relative in ledger:
        _fail("original Step-2 gate may not recursively bind itself")
    for relative, expected_sha in ledger.items():
        relative = _safe_nonthermal_relative_path(
            relative, label="original Step-2 artifact ledger path"
        )
        if not relative.startswith(_ALLOWED_STEP2_LEDGER_PREFIXES):
            _fail(f"original Step-2 ledger contains an out-of-scope path: {relative}")
        artifact = _inside_repo(
            relative,
            repo_root=repo_root,
            label=f"original Step-2 artifact {relative}",
        )
        if sha256_file(artifact) != _require_sha256(
            expected_sha, label=f"original Step-2 artifact hash {relative}"
        ):
            _fail(f"original Step-2 artifact changed: {relative}")
    checks_relative = checks_path.relative_to(repo_root).as_posix()
    if ledger.get(checks_relative) != checks_sha:
        _fail("original Step-2 checks are absent from its artifact ledger")


def _validate_step3_gate(
    gate: Mapping[str, Any],
    *,
    original_step2_sha256: str,
    gate_path: Path,
    repo_root: Path,
) -> None:
    exact = {
        "schema_version": 1,
        "decision_id": DECISION_ID,
        "analysis_profile": ANALYSIS_PROFILE,
        "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
        "primary_estimand": PRIMARY_ESTIMAND,
        "status": STEP3_PASS_STATUS,
        "interaction_status": INTERACTION_STATUS,
        "interaction_step2_gate_status": ORIGINAL_STEP2_STATUS,
        "frozen_years": "2018-2025",
        "holdout_status": "UNSELECTED",
    }
    for field, expected in exact.items():
        if gate.get(field) != expected:
            _fail(f"time-of-day Step-3 gate has stale {field}")
    _require_true(
        gate.get("scientific_gate_eligible"),
        label="time-of-day Step-3 scientific_gate_eligible",
    )
    _require_true(
        gate.get("all_required_checks_pass"),
        label="time-of-day Step-3 all_required_checks_pass",
    )
    if gate.get("failed_check_ids") != []:
        _fail("time-of-day Step-3 gate reports failed checks")
    for field in ("lst_opened", "thermal_opened", "record_2026_opened"):
        _require_false(gate.get(field), label=f"time-of-day Step-3 {field}")
    expected_counts = {
        "total_eligible_physical_passes": 219,
        "total_planning_n": 159,
        "full_panel_primary_contrast_physical_passes": 102,
        "full_panel_primary_contrast_planning_n": 72,
        "minneapolis_st_paul_excluded_primary_contrast_planning_n": 56,
        "minimum_leave_one_city_out_primary_contrast_planning_n": 54,
    }
    for field, expected in expected_counts.items():
        if _integer(gate.get(field), label=f"Step-3 {field}") != expected:
            _fail(f"time-of-day Step-3 {field} changed")
    total_expected = _finite_float(
        gate.get("total_expected_pass_equivalents"),
        label="Step-3 total expected pass-equivalents",
    )
    if not math.isclose(total_expected, EXPECTED_PASS_EQUIVALENTS, abs_tol=1e-10):
        _fail("time-of-day Step-3 total expected pass-equivalents changed")
    contrast_expected = _finite_float(
        gate.get("full_panel_primary_contrast_expected_pass_equivalents"),
        label="Step-3 primary-contrast expected pass-equivalents",
    )
    if not math.isclose(contrast_expected, 72.68902899522442, abs_tol=1e-10):
        _fail("time-of-day Step-3 primary-contrast expected support changed")
    if math.floor(contrast_expected) != gate[
        "full_panel_primary_contrast_planning_n"
    ]:
        _fail("time-of-day Step-3 primary-contrast floor rule is inconsistent")
    _require_true(
        gate.get("all_permitted_non_phoenix_holdouts_supported"),
        label="time-of-day Step-3 leave-one-city-out support verdict",
    )
    checks = gate.get("checks")
    if not isinstance(checks, list) or not checks:
        _fail("time-of-day Step-3 gate has no diagnostic check records")
    if any(
        not isinstance(item, dict)
        or item.get("required_for_gate") is not True
        or item.get("passed") is not True
        for item in checks
    ):
        _fail("time-of-day Step-3 gate contains a failed or optional check")
    if _integer(
        gate.get("total_required_checks"), label="Step-3 total_required_checks"
    ) != len(checks):
        _fail("time-of-day Step-3 check count does not match its records")
    if _integer(
        gate.get("passed_required_checks"), label="Step-3 passed_required_checks"
    ) != len(checks):
        _fail("time-of-day Step-3 passed-check count is incomplete")

    input_bindings = gate.get("input_bindings")
    expected_binding_keys = set(EXPECTED_INPUT_BINDING_PATHS) | {
        f"{field.removesuffix('_path')}_sha256"
        for field in EXPECTED_INPUT_BINDING_PATHS
    }
    if not isinstance(input_bindings, dict) or set(input_bindings) != expected_binding_keys:
        _fail("time-of-day Step-3 gate has no input bindings")
    for path_field, expected_relative in EXPECTED_INPUT_BINDING_PATHS.items():
        if input_bindings.get(path_field) != expected_relative:
            _fail(f"time-of-day Step-3 gate has a stale {path_field}")
        input_path = _inside_repo(
            expected_relative,
            repo_root=repo_root,
            label=f"time-of-day Step-3 input {path_field}",
        )
        hash_field = f"{path_field.removesuffix('_path')}_sha256"
        expected_sha = _require_sha256(
            input_bindings.get(hash_field),
            label=f"time-of-day Step-3 input {hash_field}",
        )
        if sha256_file(input_path) != expected_sha:
            _fail(f"time-of-day Step-3 input changed: {expected_relative}")
    if input_bindings["step2_gate_record_sha256"] != original_step2_sha256:
        _fail("time-of-day Step-3 gate does not bind the immutable R0015 gate")

    top_level_artifacts = {
        "model_support": STEP3_MODEL_SUPPORT_PATH,
        "leave_one_city_out_support": STEP3_LOCO_SUPPORT_PATH,
        "strata_census": STEP3_STRATA_CENSUS_PATH,
        "checks": STEP3_CHECKS_PATH,
    }
    ledger = gate.get("artifact_sha256")
    if not isinstance(ledger, dict) or not ledger:
        _fail("time-of-day Step-3 gate has no artifact hash ledger")
    canonical_gate_relative = gate_path.relative_to(repo_root).as_posix()
    if canonical_gate_relative in ledger:
        _fail("time-of-day Step-3 gate may not recursively bind itself")
    for relative, expected_sha in ledger.items():
        relative = _safe_nonthermal_relative_path(
            relative, label="time-of-day Step-3 artifact ledger path"
        )
        if not relative.startswith(f"{DEFAULT_STEP3_ROOT}/"):
            _fail(f"time-of-day Step-3 ledger contains an out-of-scope path: {relative}")
        artifact = _inside_repo(
            relative,
            repo_root=repo_root,
            label=f"time-of-day Step-3 artifact {relative}",
        )
        if sha256_file(artifact) != _require_sha256(
            expected_sha, label=f"time-of-day Step-3 artifact hash {relative}"
        ):
            _fail(f"time-of-day Step-3 artifact changed: {relative}")
    for prefix, expected_relative in top_level_artifacts.items():
        path_field = f"{prefix}_path"
        hash_field = f"{prefix}_sha256"
        if gate.get(path_field) != expected_relative:
            _fail(f"time-of-day Step-3 gate has a stale {path_field}")
        expected_sha = _require_sha256(
            gate.get(hash_field), label=f"time-of-day Step-3 {hash_field}"
        )
        artifact = _inside_repo(
            expected_relative,
            repo_root=repo_root,
            label=f"time-of-day Step-3 {prefix}",
        )
        if sha256_file(artifact) != expected_sha:
            _fail(f"time-of-day Step-3 {prefix} changed")
        if ledger.get(expected_relative) != expected_sha:
            _fail(f"time-of-day Step-3 {prefix} is absent from its artifact ledger")


def _validate_step3_run_record(
    run: Mapping[str, Any],
    *,
    step3_gate: Mapping[str, Any],
    step3_gate_sha256: str,
    original_step2_sha256: str,
    repo_root: Path,
) -> None:
    exact = {
        "schema_version": 1,
        "decision_id": DECISION_ID,
        "analysis_profile": ANALYSIS_PROFILE,
        "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
        "primary_estimand": PRIMARY_ESTIMAND,
        "interaction_status": INTERACTION_STATUS,
        "interaction_step2_gate_status": ORIGINAL_STEP2_STATUS,
        "status": STEP3_PASS_STATUS,
        "scientific_gate_eligible": True,
        "all_required_checks_pass": True,
        "failed_check_ids": [],
        "frozen_years": "2018-2025",
        "holdout_status": "UNSELECTED",
        "total_eligible_physical_passes": 219,
        "total_planning_n": 159,
        "full_panel_primary_contrast_physical_passes": 102,
        "full_panel_primary_contrast_planning_n": 72,
        "minneapolis_st_paul_excluded_primary_contrast_planning_n": 56,
        "minimum_leave_one_city_out_primary_contrast_planning_n": 54,
    }
    for field, expected in exact.items():
        if run.get(field) != expected:
            _fail(f"time-of-day Step-3 run record has a stale {field}")
    decision_ids = run.get("decision_ids", [])
    if not isinstance(decision_ids, list) or DECISION_ID not in decision_ids:
        _fail("time-of-day Step-3 run record does not cite D0056")
    for field in ("lst_opened", "thermal_opened", "record_2026_opened"):
        _require_false(run.get(field), label=f"time-of-day Step-3 run {field}")
    run_bindings = run.get("input_bindings")
    if not isinstance(run_bindings, dict) or run_bindings != step3_gate.get(
        "input_bindings"
    ):
        _fail("time-of-day Step-3 run/gate input bindings differ")
    if run_bindings.get("step2_gate_record_sha256") != original_step2_sha256:
        _fail("time-of-day Step-3 run does not bind the immutable R0015 gate")
    if run.get("step3_time_of_day_gate_path") != STEP3_GATE_PATH:
        _fail("time-of-day Step-3 run has a stale gate path")
    if run.get("step3_time_of_day_gate_sha256") != step3_gate_sha256:
        _fail("time-of-day Step-3 run has a stale gate hash")
    for name, relative in (
        ("step3_module_sha256", "src/urban_cooling_v2/step03_time_of_day_power.py"),
        ("runner_sha256", "src/run_v2_step03_time_of_day.py"),
    ):
        expected_sha = _require_sha256(
            run.get(name), label=f"time-of-day Step-3 run {name}"
        )
        if sha256_file(repo_root / relative) != expected_sha:
            _fail(f"time-of-day Step-3 run code seal changed: {relative}")
    for prefix in ("planning", "template", "step2_gate_record", "config"):
        field = f"{prefix}_sha256"
        if run.get(field) != run_bindings.get(field):
            _fail(f"time-of-day Step-3 run has a stale top-level {field}")
    expected_total = _finite_float(
        run.get("total_expected_pass_equivalents"),
        label="Step-3 run total expected pass-equivalents",
    )
    if not math.isclose(expected_total, EXPECTED_PASS_EQUIVALENTS, abs_tol=1e-10):
        _fail("time-of-day Step-3 run total expected support changed")
    primary_expected = _finite_float(
        run.get("full_panel_primary_contrast_expected_pass_equivalents"),
        label="Step-3 run primary expected pass-equivalents",
    )
    if not math.isclose(primary_expected, 72.68902899522442, abs_tol=1e-10):
        _fail("time-of-day Step-3 run primary expected support changed")


def _parse_bool_text(value: Any, *, label: str) -> bool:
    normalized = str(value).strip().casefold()
    if normalized not in {"true", "false", "1", "0"}:
        _fail(f"{label} is not a boolean")
    return normalized in {"true", "1"}


def _validate_t3t1(path: Path, *, expected_planning_n: int) -> None:
    fields, rows = _read_csv(path, label="T3T.1 time-of-day model-support table")
    expected_fields = {
        "model",
        "primary_estimand",
        "effect_size_k",
        "minimum_passes_for_target_power",
        "full_panel_primary_contrast_planning_n",
        "power_at_planning_n",
        "power_mc_ci_low",
        "power_mc_ci_high",
        "target_power",
        "statistically_supportable_at_planning_n",
        "scientific_gate_eligible",
        "interaction_status",
        "smallest_detectable_effect_at_planning_n_k",
    }
    if set(fields) != expected_fields or len(rows) != 3:
        _fail(
            "T3T.1 must contain exactly three effect-size rows and the frozen schema"
        )
    by_effect: dict[float, dict[str, str]] = {}
    for row in rows:
        effect = _finite_float(row["effect_size_k"], label="T3T.1 effect_size_k")
        if effect in by_effect:
            _fail("T3T.1 contains a duplicate effect-size row")
        by_effect[effect] = row
    if set(by_effect) != {0.75, 1.5, 2.25}:
        _fail("T3T.1 effect sizes differ from the D0056 Step-3 contract")
    support_by_effect: dict[float, bool] = {}
    detectable_values: set[float] = set()
    for row_number, (effect, row) in enumerate(by_effect.items(), start=2):
        if row["model"] != "pass_clustered_late_afternoon_minus_late_morning":
            _fail(f"T3T.1 row {row_number} has a stale model")
        if row["primary_estimand"] != PRIMARY_ESTIMAND:
            _fail(f"T3T.1 row {row_number} has a stale primary estimand")
        if row["interaction_status"] != INTERACTION_STATUS:
            _fail(f"T3T.1 row {row_number} does not preserve the R0015 STOP")
        if not math.isclose(
            _finite_float(row["target_power"], label=f"T3T.1 row {row_number} target power"),
            0.8,
            abs_tol=1e-12,
        ):
            _fail(f"T3T.1 row {row_number} has a stale target power")
        if _integer(
            row["full_panel_primary_contrast_planning_n"],
            label=f"T3T.1 row {row_number} planning_n",
        ) != expected_planning_n:
            _fail(f"T3T.1 row {row_number} has a stale planning count")
        power = _finite_float(
            row["power_at_planning_n"], label=f"T3T.1 row {row_number} power"
        )
        low = _finite_float(
            row["power_mc_ci_low"], label=f"T3T.1 row {row_number} MC CI low"
        )
        high = _finite_float(
            row["power_mc_ci_high"], label=f"T3T.1 row {row_number} MC CI high"
        )
        if not 0.0 <= low <= power <= high <= 1.0:
            _fail(f"T3T.1 row {row_number} has an invalid power interval")
        minimum = row["minimum_passes_for_target_power"]
        if str(minimum).strip() and str(minimum).strip().casefold() not in {
            "nan",
            "na",
            "not_reached",
        }:
            if _integer(minimum, label=f"T3T.1 row {row_number} minimum passes") <= 0:
                _fail(f"T3T.1 row {row_number} has an invalid minimum pass count")
        detectable = _finite_float(
            row["smallest_detectable_effect_at_planning_n_k"],
            label=f"T3T.1 row {row_number} detectable effect",
        )
        if detectable <= 0:
            _fail(f"T3T.1 row {row_number} has a nonpositive detectable effect")
        detectable_values.add(detectable)
        support_by_effect[effect] = _parse_bool_text(
            row["statistically_supportable_at_planning_n"],
            label=f"T3T.1 row {row_number} supportable",
        )
        if not _parse_bool_text(
            row["scientific_gate_eligible"],
            label=f"T3T.1 row {row_number} scientific eligibility",
        ):
            _fail(f"T3T.1 row {row_number} is not scientifically gate-eligible")
    if support_by_effect.get(1.5) is not True:
        _fail("T3T.1 primary 1.5 K effect is not statistically supportable")
    supported_effects = {effect for effect, supported in support_by_effect.items() if supported}
    if len(detectable_values) != 1 or next(iter(detectable_values)) != min(
        supported_effects
    ):
        _fail("T3T.1 smallest detectable effect is inconsistent")


def _validate_t3t2(path: Path) -> None:
    fields, rows = _read_csv(path, label="T3T.2 leave-one-city-out support table")
    expected_fields = {
        "excluded_city",
        "physical_passes",
        "expected_pass_equivalents",
        "planning_n",
        "effect_size_k",
        "n_replicates",
        "mean_estimate_k",
        "power_at_primary_effect",
        "power_mc_ci_low",
        "power_mc_ci_high",
        "target_power",
        "statistically_supportable",
        "scientific_gate_eligible",
    }
    if set(fields) != expected_fields or len(rows) != 4:
        _fail("T3T.2 must contain the four permitted non-Phoenix exclusions")
    actual_cities = {str(row["excluded_city"]).strip() for row in rows}
    if actual_cities != set(EXPECTED_LOCO_SUPPORT):
        _fail("T3T.2 has a missing, duplicate, or prohibited holdout candidate")
    planning_by_city: dict[str, int] = {}
    for row_number, row in enumerate(rows, start=2):
        city = str(row["excluded_city"]).strip()
        expected_physical, expected_weight, expected_n = EXPECTED_LOCO_SUPPORT[city]
        physical = _integer(
            row["physical_passes"],
            label=f"T3T.2 row {row_number} physical passes",
        )
        expected = _finite_float(
            row["expected_pass_equivalents"],
            label=f"T3T.2 row {row_number} expected support",
        )
        planning_by_city[city] = _integer(
            row["planning_n"], label=f"T3T.2 row {row_number} planning_n"
        )
        if (
            physical != expected_physical
            or not math.isclose(expected, expected_weight, abs_tol=1e-10)
            or planning_by_city[city] != expected_n
        ):
            _fail(f"T3T.2 frozen support changed for {city}")
        if not math.isclose(
            _finite_float(row["effect_size_k"], label=f"T3T.2 row {row_number} effect"),
            1.5,
            abs_tol=1e-12,
        ):
            _fail(f"T3T.2 row {row_number} has a stale primary effect")
        if _integer(
            row["n_replicates"], label=f"T3T.2 row {row_number} replicates"
        ) != 200:
            _fail(f"T3T.2 row {row_number} has a stale replicate count")
        _finite_float(
            row["mean_estimate_k"], label=f"T3T.2 row {row_number} mean estimate"
        )
        if not math.isclose(
            _finite_float(row["target_power"], label=f"T3T.2 row {row_number} target power"),
            0.8,
            abs_tol=1e-12,
        ):
            _fail(f"T3T.2 row {row_number} has a stale target power")
        power = _finite_float(
            row["power_at_primary_effect"],
            label=f"T3T.2 row {row_number} primary-effect power",
        )
        low = _finite_float(
            row["power_mc_ci_low"], label=f"T3T.2 row {row_number} MC CI low"
        )
        high = _finite_float(
            row["power_mc_ci_high"], label=f"T3T.2 row {row_number} MC CI high"
        )
        if not 0.0 <= low <= power <= high <= 1.0:
            _fail(f"T3T.2 row {row_number} has an invalid power interval")
        if not _parse_bool_text(
            row["statistically_supportable"],
            label=f"T3T.2 row {row_number} support verdict",
        ):
            _fail(f"T3T.2 row {row_number} is not statistically supportable")
        if not _parse_bool_text(
            row["scientific_gate_eligible"],
            label=f"T3T.2 row {row_number} scientific eligibility",
        ):
            _fail(f"T3T.2 row {row_number} is not scientifically gate-eligible")
    if min(planning_by_city.values()) != 54:
        _fail("T3T.2 worst permitted holdout planning count is not 54")
    if planning_by_city.get("minneapolis_st_paul") != 56:
        _fail("T3T.2 Minneapolis-St Paul exclusion planning count is not 56")


def _validate_t3t3(path: Path) -> None:
    fields, rows = _read_csv(path, label="T3T.3 empirical-strata census")
    expected_fields = {
        "city",
        "time_stratum",
        "physical_passes",
        "expected_pass_equivalents",
        "is_primary_contrast_stratum",
    }
    if set(fields) != expected_fields or len(rows) != len(EXPECTED_STRATA_CENSUS):
        _fail("T3T.3 must contain the frozen five-city by four-stratum census")
    observed: dict[tuple[str, str], tuple[int, float]] = {}
    for row_number, row in enumerate(rows, start=2):
        key = (str(row["city"]).strip(), str(row["time_stratum"]).strip())
        if key in observed:
            _fail("T3T.3 contains a duplicate city/time stratum")
        observed[key] = (
            _integer(row["physical_passes"], label=f"T3T.3 row {row_number} physical passes"),
            _finite_float(
                row["expected_pass_equivalents"],
                label=f"T3T.3 row {row_number} expected support",
            ),
        )
        expected_primary = key[1] in {"10-12", "16-18"}
        if _parse_bool_text(
            row["is_primary_contrast_stratum"],
            label=f"T3T.3 row {row_number} primary-stratum flag",
        ) is not expected_primary:
            _fail(f"T3T.3 row {row_number} has a stale primary-stratum flag")
    if set(observed) != set(EXPECTED_STRATA_CENSUS):
        _fail("T3T.3 city/time stratum keys changed")
    for key, (expected_physical, expected_weight) in EXPECTED_STRATA_CENSUS.items():
        physical, weight = observed[key]
        if physical != expected_physical or not math.isclose(
            weight, expected_weight, abs_tol=1e-10
        ):
            _fail(f"T3T.3 frozen support changed for {key}")


def _validate_step3_checks(path: Path, gate: Mapping[str, Any]) -> None:
    fields, rows = _read_csv(path, label="Step-3 time-of-day checks")
    expected_fields = {
        "check_id",
        "category",
        "criterion",
        "observed_value",
        "n_monte_carlo",
        "mc_ci_low",
        "mc_ci_high",
        "passed",
        "required_for_gate",
        "detail",
    }
    if set(fields) != expected_fields or len(rows) != len(gate["checks"]):
        _fail("Step-3 checks table does not match the frozen check schema")
    csv_ids: list[str] = []
    for row_number, row in enumerate(rows, start=2):
        check_id = str(row["check_id"]).strip()
        if not check_id or check_id in csv_ids:
            _fail("Step-3 checks table has a missing or duplicate check ID")
        csv_ids.append(check_id)
        if not _parse_bool_text(row["passed"], label=f"Step-3 check row {row_number} passed"):
            _fail(f"Step-3 check row {row_number} failed")
        if not _parse_bool_text(
            row["required_for_gate"],
            label=f"Step-3 check row {row_number} required flag",
        ):
            _fail(f"Step-3 check row {row_number} is not gate-required")
    embedded_ids = [str(item.get("check_id", "")) for item in gate["checks"]]
    if csv_ids != embedded_ids:
        _fail("Step-3 checks table and gate check records differ")


def _binding_paths(
    gate: Mapping[str, Any],
    *,
    repo_root: Path,
    gate_path: Path,
) -> dict[str, Path]:
    artifacts = gate.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(REQUIRED_ARTIFACT_NAMES):
        _fail("time-of-day Task-1 gate has the wrong artifact set")
    resolved: dict[str, Path] = {}
    for name in REQUIRED_ARTIFACT_NAMES:
        binding = artifacts.get(name)
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
            _fail(f"time-of-day Task-1 artifact {name} has a malformed binding")
        relative = _safe_nonthermal_relative_path(
            binding.get("path"), label=f"time-of-day Task-1 artifact {name} path"
        )
        if relative != DEFAULT_ARTIFACT_PATHS[name]:
            _fail(f"time-of-day Task-1 artifact {name} is noncanonical")
        path = _inside_repo(
            relative, repo_root=repo_root, label=f"time-of-day Task-1 artifact {name}"
        )
        if path == gate_path:
            _fail(f"time-of-day Task-1 artifact {name} may not be the gate itself")
        expected_sha = _require_sha256(
            binding.get("sha256"), label=f"time-of-day Task-1 artifact {name} hash"
        )
        if sha256_file(path) != expected_sha:
            _fail(f"time-of-day Task-1 artifact changed: {name}")
        resolved[name] = path
    return resolved


def validate_time_of_day_task1_pass(
    gate: Mapping[str, Any],
    *,
    gate_path: str | os.PathLike[str] = DEFAULT_GATE_PATH,
    repo_root: str | os.PathLike[str] = REPO_ROOT,
) -> dict[str, Path]:
    """Validate the complete D0056 Task-1 chain and return bound paths."""

    root = Path(repo_root).expanduser().resolve()
    target = _inside_repo(
        gate_path,
        repo_root=root,
        label="time-of-day Task-1 gate path",
        require_file=False,
    )
    exact = {
        "schema_version": SCHEMA_VERSION,
        "task1_gate": TASK1_GATE_STATUS,
        "profile_gate": PROFILE_GATE_STATUS,
        "analysis_profile": ANALYSIS_PROFILE,
        "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
        "scientific_gate_eligible": True,
        "primary_estimand": PRIMARY_ESTIMAND,
        "interaction_status": INTERACTION_STATUS,
        "hydroclimate_inference_status": HYDROCLIMATE_STATUS,
        "original_interaction_step2_gate_status": ORIGINAL_STEP2_STATUS,
        "original_interaction_count_support_pass": False,
        "definitive_step2": "complete_with_interaction_support_stop",
        "definitive_step3_time_of_day": "complete",
        "full_panel_primary_contrast_planning_n": 72,
        "minneapolis_st_paul_excluded_primary_contrast_planning_n": 56,
        "minimum_leave_one_city_out_primary_contrast_planning_n": 54,
        "all_permitted_non_phoenix_holdouts_supported": True,
        "lst_or_thermal_layers_opened": 0,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "season_2026": "UNOPENED",
    }
    for field, expected in exact.items():
        if gate.get(field) != expected:
            _fail(f"time-of-day Task-1 gate has stale {field}")
    decision_ids = gate.get("decision_ids")
    if not isinstance(decision_ids, list) or DECISION_ID not in decision_ids:
        _fail("time-of-day Task-1 gate does not cite D0056")
    prohibited = gate.get("prohibited_inference")
    required_prohibitions = {
        "demand_by_dryness_interaction",
        "demand_by_dryness_by_time_interaction",
        "hydroclimatic_transition_threshold",
        "unsupported_surface_regions",
    }
    if not isinstance(prohibited, list) or set(prohibited) != required_prohibitions:
        _fail("time-of-day Task-1 gate does not preserve the D0056 inference limits")

    paths = _binding_paths(gate, repo_root=root, gate_path=target)
    original_path = paths["original_interaction_step2_gate"]
    if original_path.relative_to(root).as_posix() != ORIGINAL_STEP2_PATH:
        _fail("time-of-day Task-1 gate points to a noncanonical R0015 gate")
    original_sha = sha256_file(original_path)
    if gate.get("original_interaction_step2_gate_sha256") != original_sha:
        _fail("time-of-day Task-1 gate has a stale R0015 gate hash")
    original = _read_json(original_path, label="original interaction Step-2 gate")
    _validate_original_step2(
        original, gate_path=original_path, repo_root=root
    )

    step3_gate_path = paths["step3_time_of_day_gate"]
    step3_gate_sha = sha256_file(step3_gate_path)
    step3_gate = _read_json(step3_gate_path, label="time-of-day Step-3 gate")
    _validate_step3_gate(
        step3_gate,
        original_step2_sha256=original_sha,
        gate_path=step3_gate_path,
        repo_root=root,
    )
    run = _read_json(
        paths["step3_time_of_day_run_record"],
        label="time-of-day Step-3 run record",
    )
    _validate_step3_run_record(
        run,
        step3_gate=step3_gate,
        step3_gate_sha256=step3_gate_sha,
        original_step2_sha256=original_sha,
        repo_root=root,
    )
    _validate_t3t1(
        paths["t3t1_time_of_day_model_support"],
        expected_planning_n=_integer(
            step3_gate.get("full_panel_primary_contrast_planning_n"),
            label="time-of-day primary contrast planning_n",
        ),
    )
    loco_path = paths["t3t2_leave_one_city_out_support"]
    _validate_t3t2(loco_path)
    _validate_t3t3(root / STEP3_STRATA_CENSUS_PATH)
    _validate_step3_checks(root / STEP3_CHECKS_PATH, step3_gate)
    expected_loco_path = loco_path.relative_to(root).as_posix()
    if step3_gate.get("leave_one_city_out_support_path") != expected_loco_path:
        _fail("time-of-day Step-3 gate has a stale leave-one-city-out table path")
    if step3_gate.get("leave_one_city_out_support_sha256") != sha256_file(loco_path):
        _fail("time-of-day Step-3 gate has a stale leave-one-city-out table hash")
    t3_binding = gate.get("t3t1_time_of_day_model_support_path")
    expected_t3 = paths["t3t1_time_of_day_model_support"].relative_to(root).as_posix()
    if t3_binding != expected_t3:
        _fail("time-of-day Task-1 gate has a stale T3T.1 path")
    return paths


def write_time_of_day_task1_pass(
    artifact_paths: Mapping[str, str | os.PathLike[str]],
    *,
    gate_path: str | os.PathLike[str] = DEFAULT_GATE_PATH,
    repo_root: str | os.PathLike[str] = REPO_ROOT,
) -> Path:
    """Write the scoped D0056 PASS after full local revalidation.

    The output is append-only: an existing gate is never overwritten.
    """

    root = Path(repo_root).expanduser().resolve()
    target = _inside_repo(
        gate_path,
        repo_root=root,
        label="time-of-day Task-1 gate output",
        require_file=False,
    )
    if target.exists():
        _fail("time-of-day Task-1 gate already exists; refusing to overwrite it")
    if set(map(str, artifact_paths)) != set(REQUIRED_ARTIFACT_NAMES):
        _fail("time-of-day writer requires exactly the frozen artifact set")
    bindings: dict[str, dict[str, str]] = {}
    for name in REQUIRED_ARTIFACT_NAMES:
        path = _inside_repo(
            artifact_paths[name],
            repo_root=root,
            label=f"time-of-day writer artifact {name}",
        )
        if path == target:
            _fail(f"time-of-day writer artifact {name} may not be the gate output")
        bindings[name] = {
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
        }
    original_sha = bindings["original_interaction_step2_gate"]["sha256"]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task1_gate": TASK1_GATE_STATUS,
        "profile_gate": PROFILE_GATE_STATUS,
        "analysis_profile": ANALYSIS_PROFILE,
        "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
        "scientific_gate_eligible": True,
        "primary_estimand": PRIMARY_ESTIMAND,
        "interaction_status": INTERACTION_STATUS,
        "hydroclimate_inference_status": HYDROCLIMATE_STATUS,
        "prohibited_inference": [
            "demand_by_dryness_interaction",
            "demand_by_dryness_by_time_interaction",
            "hydroclimatic_transition_threshold",
            "unsupported_surface_regions",
        ],
        "decision_ids": ["D0047", "D0053", "D0054", DECISION_ID],
        "original_interaction_step2_gate_status": ORIGINAL_STEP2_STATUS,
        "original_interaction_count_support_pass": False,
        "original_interaction_step2_gate_sha256": original_sha,
        "definitive_step2": "complete_with_interaction_support_stop",
        "definitive_step3_time_of_day": "complete",
        "full_panel_primary_contrast_planning_n": 72,
        "minneapolis_st_paul_excluded_primary_contrast_planning_n": 56,
        "minimum_leave_one_city_out_primary_contrast_planning_n": 54,
        "all_permitted_non_phoenix_holdouts_supported": True,
        "lst_or_thermal_layers_opened": 0,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "season_2026": "UNOPENED",
        "t3t1_time_of_day_model_support_path": bindings[
            "t3t1_time_of_day_model_support"
        ]["path"],
        "artifacts": bindings,
    }
    validate_time_of_day_task1_pass(
        payload, gate_path=target, repo_root=root
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def write_default_time_of_day_task1_pass(
    *,
    repo_root: str | os.PathLike[str] = REPO_ROOT,
    gate_path: str | os.PathLike[str] = DEFAULT_GATE_PATH,
) -> Path:
    return write_time_of_day_task1_pass(
        DEFAULT_ARTIFACT_PATHS,
        gate_path=gate_path,
        repo_root=repo_root,
    )


__all__ = [
    "ANALYSIS_PROFILE",
    "DEFAULT_ARTIFACT_PATHS",
    "DEFAULT_GATE_PATH",
    "DECISION_ID",
    "PRIMARY_ESTIMAND",
    "PROFILE_GATE_STATUS",
    "SCHEMA_VERSION",
    "SCIENTIFIC_GATE_SCOPE",
    "TASK1_GATE_STATUS",
    "TimeOfDayTask1GateError",
    "sha256_file",
    "validate_time_of_day_task1_pass",
    "write_default_time_of_day_task1_pass",
    "write_time_of_day_task1_pass",
]
