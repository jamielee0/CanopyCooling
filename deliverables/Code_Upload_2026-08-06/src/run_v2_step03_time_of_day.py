#!/usr/bin/env python3
"""Validate and run the nonthermal D0056 time-of-day-only Step-3 profile."""

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

from urban_cooling_v2.config import load_config
from urban_cooling_v2.step03_time_of_day_power import (
    ANALYSIS_PROFILE,
    DECISION_ID,
    INTERACTION_STATUS,
    PASS_STATUS,
    PERMITTED_NON_PHOENIX_HOLDOUTS,
    PRIMARY_ESTIMAND,
    SCIENTIFIC_GATE_SCOPE,
    TimeOfDayDiagnosticThresholds,
    TimeOfDaySimulationSpec,
    empirical_strata_census,
    leave_one_city_out_census,
    primary_contrast_template,
    run_time_of_day_simulation_study,
    validate_time_template,
    write_time_of_day_deliverables,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/v2_cities.toml"
STEP2 = ROOT / (
    "data/processed/v2/task1/"
    "step2_definitive_l1b_geo_D0047_archive_available"
)
PLANNING = STEP2 / "step3_planning_count.json"
STEP2_GATE = STEP2 / "step2_gate_record.json"
OUTPUT_RELATIVE = Path(
    "data/processed/v2/task1/step3_time_of_day_only_D0056"
)
OUTPUT = ROOT / OUTPUT_RELATIVE

EXPECTED_TEMPLATE_ROWS = 219
EXPECTED_TOTAL_WEIGHT = 159.08708404623306
EXPECTED_TOTAL_PLANNING_N = 159
EXPECTED_PRIMARY_ROWS = 102
EXPECTED_PRIMARY_WEIGHT = 72.68902899522442
EXPECTED_PRIMARY_PLANNING_N = 72
EXPECTED_CENSUS: dict[tuple[str, str], tuple[int, float]] = {
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
EXPECTED_LOCO: dict[str, tuple[int, float, int]] = {
    "atlanta": (79, 57.42421755160162, 57),
    "los_angeles": (79, 54.05826500543519, 54),
    "miami": (94, 66.36341549393057, 66),
    "minneapolis_st_paul": (74, 56.51165197128533, 56),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_file(root: Path, value: Any, *, label: str) -> Path:
    raw = Path(str(value))
    if raw.is_absolute():
        raise ValueError(f"{label} must be repository-relative")
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escapes the repository") from exc
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    return path


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must contain a JSON object")
    return value


def _validate_exact_census(census: pd.DataFrame) -> None:
    observed = {
        (str(row.city), str(row.time_stratum)): (
            int(row.physical_passes),
            float(row.expected_pass_equivalents),
        )
        for row in census.itertuples(index=False)
    }
    if set(observed) != set(EXPECTED_CENSUS):
        raise RuntimeError("D0056 city/time-stratum census keys changed")
    for key, (expected_count, expected_weight) in EXPECTED_CENSUS.items():
        count, weight = observed[key]
        if count != expected_count or not np.isclose(
            weight, expected_weight, rtol=0, atol=1e-10
        ):
            raise RuntimeError(f"D0056 city/time-stratum census changed at {key}")


def _validate_exact_loco(loco: pd.DataFrame) -> None:
    if set(loco["excluded_city"].astype(str)) != set(
        PERMITTED_NON_PHOENIX_HOLDOUTS
    ):
        raise RuntimeError("D0056 permitted holdout set changed")
    indexed = loco.set_index("excluded_city")
    for city, (rows, expected, planning_n) in EXPECTED_LOCO.items():
        row = indexed.loc[city]
        if (
            int(row["physical_passes"]) != rows
            or not np.isclose(
                float(row["expected_pass_equivalents"]),
                expected,
                rtol=0,
                atol=1e-10,
            )
            or int(row["planning_n"]) != planning_n
        ):
            raise RuntimeError(f"D0056 leave-one-city-out support changed for {city}")


def load_inputs(*, root: Path = ROOT) -> dict[str, Any]:
    """Validate the exact nonthermal D0047 evidence chain without opening rasters."""

    root = root.resolve()
    planning_path = root / PLANNING.relative_to(ROOT)
    gate_path = root / STEP2_GATE.relative_to(ROOT)
    config_path = root / CONFIG.relative_to(ROOT)
    planning = _read_json(planning_path, label="D0047 Step-3 planning record")
    gate = _read_json(gate_path, label="D0047 Step-2 gate record")
    if planning.get("step2_gate_record_path") != str(
        gate_path.relative_to(root)
    ) or planning.get("step2_gate_record_sha256") != _sha256(gate_path):
        raise RuntimeError("D0056 planning record does not bind the Step-2 gate")
    required_gate = {
        "decision_id": "D0047",
        "analysis_profile": "D0047_archive_available",
        "scientific_gate_scope": "archive_available_only",
        "status": "STOP",
        "scientific_gate_eligible": False,
        "all_checks_pass": True,
        "checks_pass": True,
        "count_support_pass": False,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
    }
    for key, expected in required_gate.items():
        if gate.get(key) != expected:
            raise RuntimeError(f"D0056 requires Step-2 {key}={expected!r}")
    if gate.get("failure_domains") != ["count_support"]:
        raise RuntimeError("D0056 requires count support as the sole Step-2 failure")
    checks = gate.get("checks")
    if (
        not isinstance(checks, list)
        or len(checks) != 6
        or not all(isinstance(item, dict) and item.get("pass") is True for item in checks)
    ):
        raise RuntimeError("D0056 requires all six Step-2 integrity checks")
    if planning.get("step2_gate") != "STOP":
        raise RuntimeError("D0056 must preserve the interaction Step-2 STOP")
    if (
        int(planning.get("near_nadir_physical_passes", -1))
        != EXPECTED_TEMPLATE_ROWS
        or not np.isclose(
            float(planning.get("expected_pass_equivalents_total", np.nan)),
            EXPECTED_TOTAL_WEIGHT,
            rtol=0,
            atol=1e-10,
        )
        or int(planning.get("planning_pass_count_floor", -1))
        != EXPECTED_TOTAL_PLANNING_N
    ):
        raise RuntimeError("D0056 total Step-2 counts changed")

    template_path = _repo_file(
        root, planning.get("template_path"), label="D0056 empirical pass template"
    )
    if planning.get("template_sha256") != _sha256(template_path):
        raise RuntimeError("D0056 empirical template hash changed")
    artifact_ledger = gate.get("artifact_sha256")
    if (
        not isinstance(artifact_ledger, dict)
        or artifact_ledger.get(str(template_path.relative_to(root)))
        != _sha256(template_path)
    ):
        raise RuntimeError("D0056 Step-2 gate does not bind the empirical template")
    raw_template = pd.read_csv(template_path)
    template = validate_time_template(raw_template)
    if len(template) != EXPECTED_TEMPLATE_ROWS:
        raise RuntimeError("D0056 empirical template row count changed")
    total_weight = float(template["sampling_weight"].sum())
    if not np.isclose(
        total_weight, EXPECTED_TOTAL_WEIGHT, rtol=0, atol=1e-10
    ) or math.floor(total_weight) != EXPECTED_TOTAL_PLANNING_N:
        raise RuntimeError("D0056 empirical template total weight changed")
    primary = primary_contrast_template(template)
    primary_weight = float(primary["sampling_weight"].sum())
    if (
        len(primary) != EXPECTED_PRIMARY_ROWS
        or not np.isclose(
            primary_weight, EXPECTED_PRIMARY_WEIGHT, rtol=0, atol=1e-10
        )
        or math.floor(primary_weight) != EXPECTED_PRIMARY_PLANNING_N
    ):
        raise RuntimeError("D0056 primary-contrast support changed")
    census = empirical_strata_census(template)
    _validate_exact_census(census)
    loco = leave_one_city_out_census(template)
    _validate_exact_loco(loco)

    config = load_config(config_path)
    spec = TimeOfDaySimulationSpec.from_mapping(config.simulation)
    thresholds = TimeOfDayDiagnosticThresholds.from_mapping(config.simulation)
    spec.validate()
    thresholds.validate()
    frozen_spec = TimeOfDaySimulationSpec()
    if asdict(spec) != asdict(frozen_spec):
        raise RuntimeError("D0056 simulation specification differs from frozen values")
    pass_counts = tuple(int(value) for value in config.simulation["planning_pass_counts"])
    settings = {
        "n_replicates": int(config.simulation["full_power_replicates"]),
        "n_coverage_replicates": int(
            config.simulation["full_coverage_replicates"]
        ),
        "n_boot": int(config.simulation["full_bootstrap_replicates"]),
    }
    if pass_counts != (50, 100, 200, 400, 800) or settings != {
        "n_replicates": 200,
        "n_coverage_replicates": 60,
        "n_boot": 120,
    }:
        raise RuntimeError("D0056 full profile differs from frozen D0021 values")
    validation = {
        "schema_version": 1,
        "decision_ids": ["D0007", "D0008", "D0012", "D0021", "D0027", "D0029", "D0047", "D0053", "D0054", DECISION_ID],
        "analysis_profile": ANALYSIS_PROFILE,
        "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
        "primary_estimand": PRIMARY_ESTIMAND,
        "interaction_status": INTERACTION_STATUS,
        "interaction_step2_gate_status": "STOP",
        "total_eligible_physical_passes": len(template),
        "total_expected_pass_equivalents": total_weight,
        "total_planning_n": math.floor(total_weight),
        "full_panel_primary_contrast_physical_passes": len(primary),
        "full_panel_primary_contrast_expected_pass_equivalents": primary_weight,
        "full_panel_primary_contrast_planning_n": math.floor(primary_weight),
        "minimum_leave_one_city_out_primary_contrast_planning_n": int(
            loco["planning_n"].min()
        ),
        "minneapolis_st_paul_excluded_primary_contrast_planning_n": int(
            loco.loc[
                loco["excluded_city"].eq("minneapolis_st_paul"), "planning_n"
            ].iloc[0]
        ),
        "template_rows": len(template),
        "template_sha256": _sha256(template_path),
        "planning_sha256": _sha256(planning_path),
        "step2_gate_record_sha256": _sha256(gate_path),
        "config_sha256": _sha256(config_path),
        "pass_counts": list(pass_counts),
        **settings,
        "simulation_spec": asdict(spec),
        "diagnostic_thresholds": asdict(thresholds),
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
        "status": "READY_FOR_D0056_TIME_OF_DAY_POWER",
    }
    input_bindings = {
        "planning_path": str(planning_path.relative_to(root)),
        "planning_sha256": _sha256(planning_path),
        "step2_gate_record_path": str(gate_path.relative_to(root)),
        "step2_gate_record_sha256": _sha256(gate_path),
        "template_path": str(template_path.relative_to(root)),
        "template_sha256": _sha256(template_path),
        "config_path": str(config_path.relative_to(root)),
        "config_sha256": _sha256(config_path),
    }
    return {
        "template": template,
        "spec": spec,
        "thresholds": thresholds,
        "pass_counts": pass_counts,
        "settings": settings,
        "validation": validation,
        "input_bindings": input_bindings,
    }


def run_definitive(*, root: Path = ROOT) -> dict[str, Path]:
    """Run atomically and never overwrite an existing D0056 result."""

    root = root.resolve()
    output = root / OUTPUT_RELATIVE
    if output.exists():
        raise FileExistsError(f"D0056 Step-3 output already exists: {output}")
    inputs = load_inputs(root=root)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".step3-time-of-day-D0056-", dir=output.parent)
    )
    try:
        results = run_time_of_day_simulation_study(
            inputs["template"],
            pass_counts=inputs["pass_counts"],
            spec=inputs["spec"],
            input_eligible=True,
            interaction_stop_preserved=True,
            **inputs["settings"],
        )
        paths = write_time_of_day_deliverables(
            results,
            staging,
            output_relative_root=str(OUTPUT_RELATIVE),
            input_bindings=inputs["input_bindings"],
            thresholds=inputs["thresholds"],
        )
        gate_path = paths["gate"]
        gate = _read_json(gate_path, label="D0056 time-of-day gate")
        run_record = {
            **inputs["validation"],
            "status": gate["status"],
            "scientific_gate_eligible": gate["scientific_gate_eligible"],
            "all_required_checks_pass": gate["all_required_checks_pass"],
            "failed_check_ids": gate["failed_check_ids"],
            "step3_time_of_day_gate_path": str(
                OUTPUT_RELATIVE / "step3_time_of_day_gate.json"
            ),
            "step3_time_of_day_gate_sha256": _sha256(gate_path),
            "step3_module_sha256": _sha256(
                root / "src/urban_cooling_v2/step03_time_of_day_power.py"
            ),
            "runner_sha256": _sha256(Path(__file__).resolve()),
            "input_bindings": inputs["input_bindings"],
        }
        run_path = staging / "run_record.json"
        run_path.write_text(
            json.dumps(run_record, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        required = {
            "F3T.1",
            "F3T.2",
            "F3T.3",
            "F3T.4",
            "F3T.5",
            "T3T.1",
            "T3T.2",
            "T3T.3",
            "checks",
            "memo",
            "settings",
            "gate",
        }
        if required - set(paths) or any(not paths[key].is_file() for key in required):
            raise RuntimeError("D0056 staging validation found missing deliverables")
        staging.replace(output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    resolved = {
        name: output / path.relative_to(staging) for name, path in paths.items()
    }
    resolved["run_record"] = output / "run_record.json"
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the nonthermal D0056 time-of-day-only Step-3 power gate."
    )
    parser.add_argument(
        "command", choices=("validate-inputs", "run"), help="D0056 action"
    )
    args = parser.parse_args()
    if args.command == "validate-inputs":
        inputs = load_inputs()
        print(json.dumps(inputs["validation"], indent=2, sort_keys=True))
        return 0
    paths = run_definitive()
    gate = _read_json(paths["gate"], label="D0056 time-of-day gate")
    print(
        json.dumps(
            {"output": str(OUTPUT), "time_of_day_gate": gate},
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if gate.get("status") == PASS_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
