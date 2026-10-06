"""Fail-closed, network-free preflight for conditional Guide Steps 4--9.

This module deliberately performs no catalogue query, download, raster open, or
holdout selection.  It only evaluates whether the evidence and frozen decisions
required to begin result-bearing Task 2 work are present.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import tomllib
from typing import Any, Mapping

from urban_cooling_v2.task1_pass_gate import (
    CANONICAL_TASK1_GATE_STATUS,
    Task1GateError,
    validate_canonical_task1_pass,
    validate_d0047_task2_activation_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "v2_task2.toml"

REQUIRED_FROZEN_DECISIONS = (
    "cross_city_scope_status",
    "holdout_eligibility_rule_status",
    "holdout_selection_status",
    "collection_chain_status",
    "time_strata_status",
    "scene_pixel_qa_status",
    "supporting_product_chain_status",
    "optical_landcover_status",
    "classification_matching_status",
    "analysis_schema_status",
)

REQUIRED_TASK1_COMPLETIONS = {
    "definitive_step2": "complete",
    "hrrr_exact_acquisition_fetch": "complete",
    "definitive_step3": "complete",
}


@dataclass(frozen=True)
class Blocker:
    code: str
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    ready: bool
    blockers: tuple[Blocker, ...]
    task1_gate_path: str
    task1_gate_value: str
    free_bytes: int
    projected_peak_bytes: int

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = [asdict(item) for item in self.blockers]
        return payload


def _block(blockers: list[Blocker], code: str, detail: str) -> None:
    blockers.append(Blocker(code=code, detail=detail))


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_task2_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    with source.open("rb") as handle:
        return tomllib.load(handle)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def evaluate_preflight(
    config: Mapping[str, Any],
    task1_gate: Mapping[str, Any] | None,
    *,
    task1_gate_path: str,
    free_bytes: int,
    repo_root: str | Path = REPO_ROOT,
) -> PreflightReport:
    """Evaluate readiness without touching any result-bearing source."""

    blockers: list[Blocker] = []
    task2 = config.get("task2", {})
    decisions = config.get("decisions", {})
    storage = config.get("storage", {})
    safety = config.get("safety", {})

    if task1_gate is None:
        gate_value = "MISSING"
        _block(
            blockers,
            "TASK1_CANONICAL_GATE_MISSING",
            "A canonical machine-readable Task 1 PASS record does not exist.",
        )
    else:
        gate_value = str(task1_gate.get("task1_gate", "MISSING"))
        if gate_value != CANONICAL_TASK1_GATE_STATUS:
            _block(
                blockers,
                "TASK1_NOT_PASS",
                f"Task 1 gate is {gate_value!r}; the only accepted value is 'PASS'.",
            )
        try:
            validate_canonical_task1_pass(
                task1_gate,
                gate_path=task1_gate_path,
                repo_root=repo_root,
            )
        except (Task1GateError, OSError, ValueError) as exc:
            _block(
                blockers,
                "TASK1_CANONICAL_GATE_INVALID",
                f"The Task 1 PASS evidence chain did not validate: {exc}",
            )
        else:
            try:
                validate_d0047_task2_activation_contract(task1_gate)
            except Task1GateError as exc:
                _block(
                    blockers,
                    "TASK1_D0047_PROFILE_REQUIRED",
                    "Task 2 accepts only the scope-qualified D0047 "
                    f"archive-available PASS: {exc}",
                )

    if _as_int(task2.get("development_end_year"), 9999) > 2025:
        _block(blockers, "TASK2_2026_IN_SCOPE", "Task 2 development may not include 2026.")
    if str(task2.get("season_2026_status", "")) != "UNOPENED":
        _block(blockers, "TASK2_2026_NOT_LOCKED", "Task 2 must keep 2026 UNOPENED.")
    if str(task2.get("heldout_thermal_status", "")) != "UNOPENED":
        _block(
            blockers,
            "HOLDOUT_THERMAL_NOT_LOCKED",
            "The held-out city's thermal archive must remain UNOPENED during Task 2 development.",
        )

    holdout_status = str(task2.get("holdout_status", "UNSELECTED"))
    holdout_city = str(task2.get("holdout_city", "")).strip()
    if holdout_status != "SELECTED" or not holdout_city:
        _block(
            blockers,
            "HOLDOUT_NOT_SELECTED",
            "Select and log the quality-only holdout after Task 1 PASS and before any LST access.",
        )

    for key in REQUIRED_FROZEN_DECISIONS:
        if str(decisions.get(key, "MISSING")) != "FROZEN":
            _block(
                blockers,
                f"DECISION_{key.upper()}_NOT_FROZEN",
                f"{key} must be FROZEN before result-bearing Task 2 work.",
            )
    if not str(decisions.get("cross_city_scope_choice", "")).strip():
        _block(
            blockers,
            "CROSS_CITY_SCOPE_CHOICE_MISSING",
            "O0009 requires a recorded user/supervisor scope choice.",
        )
    if not str(decisions.get("holdout_eligibility_rule", "")).strip():
        _block(
            blockers,
            "HOLDOUT_RULE_MISSING",
            "The quality-only holdout eligibility and ranking rule must be recorded.",
        )
    if not str(decisions.get("collection_chain_decision_id", "")).strip():
        _block(
            blockers,
            "COLLECTION_DECISION_ID_MISSING",
            "The frozen version-specific product-chain decision ID is required.",
        )

    projected = _as_int(storage.get("projected_peak_bytes"), 0)
    multiplier = _as_float(storage.get("headroom_multiplier"), 0.0)
    reserve = _as_int(storage.get("minimum_reserve_bytes"), 0)
    if str(storage.get("status", "")) != "FROZEN":
        _block(
            blockers,
            "STORAGE_PLAN_NOT_FROZEN",
            "Inventory source asset sizes and freeze the staged storage plan first.",
        )
    if projected <= 0:
        _block(
            blockers,
            "STORAGE_PROJECTION_MISSING",
            "projected_peak_bytes must be a positive evidence-backed estimate.",
        )
    elif multiplier < 1.0 or reserve < 0:
        _block(
            blockers,
            "STORAGE_HEADROOM_RULE_INVALID",
            "headroom_multiplier must be at least 1 and the reserve cannot be negative.",
        )
    elif free_bytes < int(projected * multiplier) + reserve:
        _block(
            blockers,
            "INSUFFICIENT_STORAGE_HEADROOM",
            "Free space is below projected_peak_bytes × headroom_multiplier plus the reserve.",
        )

    if storage.get("delete_existing_data") is not False:
        _block(
            blockers,
            "DESTRUCTIVE_STORAGE_PLAN",
            "Task 2 preflight never authorizes deleting existing user data.",
        )
    if storage.get("persist_signed_urls") is not False:
        _block(
            blockers,
            "SIGNED_URL_PERSISTENCE_ENABLED",
            "Persist stable granule identifiers and checksums, never signed URLs.",
        )
    if storage.get("preserve_native_temperature_grid") is not True:
        _block(
            blockers,
            "NATIVE_GRID_NOT_ENFORCED",
            "Temperature must remain on the native ECOSTRESS tiled grid.",
        )

    forbidden_true = {
        "open_2026": "Opening 2026 is prohibited.",
        "mix_primary_collection_versions": "Mixed primary collection versions are prohibited.",
        "resample_temperature": "Temperature resampling is prohibited.",
        "use_future_optical_imagery": "Future optical imagery is prohibited.",
        "use_thermal_outcome_to_tune_thresholds": "Outcome-driven threshold tuning is prohibited.",
    }
    for key, detail in forbidden_true.items():
        if safety.get(key) is not False:
            _block(blockers, f"SAFETY_{key.upper()}", detail)

    if task2.get("result_bearing_actions_enabled") is not True:
        _block(
            blockers,
            "RESULT_BEARING_ACTIONS_DISABLED",
            "The coordinator has not enabled Task 2 after reviewing every preflight item.",
        )

    return PreflightReport(
        ready=not blockers,
        blockers=tuple(blockers),
        task1_gate_path=task1_gate_path,
        task1_gate_value=gate_value,
        free_bytes=int(free_bytes),
        projected_peak_bytes=projected,
    )


def run_preflight(
    config_path: str | Path = DEFAULT_CONFIG,
    *,
    repo_root: str | Path = REPO_ROOT,
) -> PreflightReport:
    root = Path(repo_root).expanduser().resolve()
    config = load_task2_config(config_path)
    gate_rel = str(config.get("task2", {}).get("canonical_task1_gate", ""))
    gate_path = (root / gate_rel).resolve()
    path_error = ""
    try:
        gate_path.relative_to(root)
        if Path(gate_rel).is_absolute():
            raise ValueError("canonical_task1_gate must be repository-relative")
    except ValueError as exc:
        path_error = str(exc) or "canonical_task1_gate escapes the repository"
        gate_path = root / "__INVALID_TASK1_GATE_PATH__"
    read_error = ""
    try:
        gate = _read_json(gate_path) if not path_error else None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        gate = None
        read_error = str(exc)
    free_bytes = shutil.disk_usage(root).free
    report = evaluate_preflight(
        config,
        gate,
        task1_gate_path=str(gate_path),
        free_bytes=free_bytes,
        repo_root=root,
    )

    blockers = list(report.blockers)
    if path_error:
        _block(
            blockers,
            "TASK1_CANONICAL_GATE_PATH_INVALID",
            f"Configured canonical Task 1 gate path is unsafe: {path_error}",
        )
    if read_error:
        _block(
            blockers,
            "TASK1_CANONICAL_GATE_UNREADABLE",
            f"Configured canonical Task 1 gate is unreadable: {read_error}",
        )
    if gate is None:
        stop_rel = str(config.get("task2", {}).get("current_task1_stop_gate", ""))
        stop_path = (root / stop_rel).resolve()
        try:
            stop_path.relative_to(root)
            current_stop = _read_json(stop_path)
        except (ValueError, OSError, json.JSONDecodeError):
            current_stop = None
        if current_stop is not None:
            current_value = str(current_stop.get("task1_gate", "UNKNOWN"))
            _block(
                blockers,
                "CURRENT_TASK1_STOP",
                f"Latest observed Task 1 record is {current_value!r} at {stop_rel}.",
            )

    if len(blockers) != len(report.blockers):
        report = PreflightReport(
            ready=False,
            blockers=tuple(blockers),
            task1_gate_path=report.task1_gate_path,
            task1_gate_value=report.task1_gate_value,
            free_bytes=report.free_bytes,
            projected_peak_bytes=report.projected_peak_bytes,
        )
    return report


__all__ = [
    "Blocker",
    "DEFAULT_CONFIG",
    "PreflightReport",
    "evaluate_preflight",
    "load_task2_config",
    "run_preflight",
]
