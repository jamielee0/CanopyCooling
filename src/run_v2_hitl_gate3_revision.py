#!/usr/bin/env python3
"""Build the D0066–D0068 revised nonthermal Gate-3 review packet."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any

import pandas as pd

from urban_cooling_v2.hitl_gate3_sampling import (
    PRIMARY_ANGLE_THRESHOLDS,
    selection_result,
    summarize_phenology_sensitivities,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/v2/hitl/G3_SAMPLING_DESIGN_REVISION"
PHENOLOGY_RAW = ROOT / "data/raw/v2/hitl/g3_sampling_design_revision/mod13q1_tcc_2018_2025_composite_ndvi.csv"
ARCHIVE_SUMMARY = OUTPUT / "archive_bounded_recheck_summary.json"
ARCHIVE_PASSES = OUTPUT / "archive_pass_bounded_recheck_and_bounds.csv"

# R0020 is immutable evidence reviewed by the user and bound by D0069.  This
# historical generator is retained for provenance only; subsequent Gate-3
# packets must use a new output namespace and must never rewrite R0020.
IMMUTABLE_R0020_HASHES = {
    "checks_revised.json": "3cd10249ef78a7e0f401dca81eaea7789f657ee2ba14c68253db0e04fb1f127f",
    "review_revised.md": "9f1460ab817bb9ca8af133494f1d34c05468a615ff8e8134d434f5eeb36207ed",
    "source_bindings_revised.json": "aadb72f491debd7b4486f77c4d8c848d7517ceada75385895463b7ba39aa8828",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _passing_windows(decisions: pd.DataFrame, column: str) -> str:
    selected = decisions.loc[decisions[column], ["city", "window_id"]]
    return ", ".join(
        f"{row.city}/{row.window_id}" for row in selected.itertuples(index=False)
    ) or "none"


def _test_selector() -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(ROOT / "src/test_v2_hitl_gate3_sampling.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "command": "current Python; src/test_v2_hitl_gate3_sampling.py",
        "returncode": int(result.returncode),
        "passed": result.returncode == 0 and "PASS test_v2_hitl_gate3_sampling" in result.stdout,
        "stdout_last_line": result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "",
        "stderr_present": bool(result.stderr.strip()),
    }


def run_full_regression_suite() -> dict[str, Any]:
    """Execute and record every discovered v2 and legacy test program."""

    v2_programs = sorted((ROOT / "src").glob("test_v2_*.py"))
    legacy_programs = sorted(
        path for path in (ROOT / "src").glob("test_*.py") if not path.name.startswith("test_v2_")
    )
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="g3-regression-") as cache_dir:
        environment = os.environ.copy()
        environment.update(
            {
                "MPLCONFIGDIR": str(Path(cache_dir) / "matplotlib"),
                "XDG_CACHE_HOME": str(Path(cache_dir) / "xdg"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        for suite, programs in (("v2", v2_programs), ("legacy", legacy_programs)):
            for path in programs:
                started = time.monotonic()
                result = subprocess.run(
                    [sys.executable, str(path)],
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                results.append(
                    {
                        "suite": suite,
                        "program": str(path.relative_to(ROOT)),
                        "program_sha256": sha256_file(path),
                        "returncode": int(result.returncode),
                        "passed": result.returncode == 0,
                        "duration_seconds": round(time.monotonic() - started, 3),
                        "stdout_last_line": result.stdout.strip().splitlines()[-1]
                        if result.stdout.strip()
                        else "",
                        "stderr_last_line": result.stderr.strip().splitlines()[-1]
                        if result.stderr.strip()
                        else "",
                    }
                )
    counts = {
        suite: {
            "discovered": sum(item["suite"] == suite for item in results),
            "passed": sum(item["suite"] == suite and item["passed"] for item in results),
            "failed": sum(item["suite"] == suite and not item["passed"] for item in results),
        }
        for suite in ("v2", "legacy")
    }
    return {
        "python_executable": sys.executable,
        "counts": counts,
        "all_passed": bool(results and all(item["passed"] for item in results)),
        "programs": results,
    }


def run() -> dict[str, Any]:
    mismatches = {
        name: (sha256_file(OUTPUT / name) if (OUTPUT / name).is_file() else "MISSING")
        for name, expected in IMMUTABLE_R0020_HASHES.items()
        if not (OUTPUT / name).is_file() or sha256_file(OUTPUT / name) != expected
    }
    if mismatches:
        raise RuntimeError(f"Immutable R0020 evidence failed its D0069 hash seal: {mismatches}")
    raise RuntimeError(
        "R0020 is immutable reviewed evidence. Use the D0069 second-revision packet runner."
    )


def _historical_unreachable_run_body() -> dict[str, Any]:
    """Retained solely to document how R0020 was originally assembled."""

    composites = pd.read_csv(PHENOLOGY_RAW, parse_dates=["date"])
    if composites["year"].min() != 2018 or composites["year"].max() != 2025:
        raise ValueError("Phenology evidence escaped 2018–2025")
    monthly, windows, decisions = summarize_phenology_sensitivities(composites)
    archive = json.loads(ARCHIVE_SUMMARY.read_text(encoding="utf-8"))
    archive_passes = pd.read_csv(ARCHIVE_PASSES)
    archive_clean = bool(
        archive.get("finite_budget_observed")
        and int(archive.get("unresolved_error_count", -1)) == 0
        and not archive.get("record_2026_queried")
    )

    candidate_rows: list[dict[str, Any]] = []
    for threshold in PRIMARY_ANGLE_THRESHOLDS:
        for row in decisions.to_dict("records"):
            nonexploratory = row["city"] != "miami"
            candidate_rows.append(
                {
                    **row,
                    "threshold_deg": threshold,
                    "nonexploratory_candidate": nonexploratory,
                    "archive_accounting_finitely_classified": archive_clean,
                    "archive_bounds_invariant": archive_clean,
                    "geometry_azimuth_cloud_exact_weather_complete": False,
                    "eligible_city_window": False,
                    "ineligibility_reason": (
                        "PRIMARY_PHENOLOGY_FAIL"
                        if not row["primary_phenology_pass"]
                        else (
                            "PHENOLOGY_SENSITIVITY_REVERSAL"
                            if not row["phenology_auto_eligible"]
                            else "REQUIRED_AUGMENTATION_NOT_EXECUTED_AFTER_FOUR_CITY_FAILURE"
                        )
                    ),
                }
            )
    eligibility = pd.DataFrame(candidate_rows)
    stable_city_count = int(
        decisions.loc[
            decisions["phenology_auto_eligible"] & ~decisions["city"].eq("miami"),
            "city",
        ].nunique()
    )
    balance = pd.DataFrame(
        [
            {
                "threshold_deg": threshold,
                "candidate_primary_unique_cities_after_phenology": stable_city_count,
                "four_city_minimum_pass": stable_city_count >= 4,
                "maximum_city_share": None,
                "city_share_cap_pass": False,
                "normalized_shannon_entropy": None,
                "histogram_diagnostics_complete": False,
                "am_pm_support_diagnostics_complete": False,
                "wet_dry_support_diagnostics_complete": False,
                "weather_overlap_diagnostics_complete": False,
                "archive_bounds_invariant": archive_clean,
                "diagnostic_status": "NOT_COMPUTABLE_UPSTREAM_FOUR_CITY_PHENOLOGY_FAILURE",
            }
            for threshold in PRIMARY_ANGLE_THRESHOLDS
        ]
    )
    selection = selection_result(eligibility, balance)
    selector_test = _test_selector()
    regression = run_full_regression_suite()
    regression_path = OUTPUT / "full_regression_suite.json"
    write_json(regression_path, regression)

    qa_rows: list[dict[str, Any]] = []
    for city, group in composites.groupby("city", sort=True):
        qa_rows.append(
            {
                "city": city,
                "composites": len(group),
                "primary_qa_0_1_usable": int(group["primary_composite_usable"].sum()),
                "qa_0_only_usable": int(group["good_composite_usable"].sum()),
                "canopy_masked_qa_0_1_usable": int(group["canopy_primary_composite_usable"].sum()),
                "canopy_masked_cell_fraction_min": float(group["canopy_masked_cell_fraction"].min()),
                "canopy_masked_cell_fraction_median": float(group["canopy_masked_cell_fraction"].median()),
                "canopy_masked_cell_fraction_max": float(group["canopy_masked_cell_fraction"].max()),
            }
        )
    qa_audit = pd.DataFrame(qa_rows)

    artifacts: list[Path] = []
    artifacts.append(regression_path)
    tables = {
        "phenology_sensitivity_monthly.csv": monthly,
        "phenology_sensitivity_windows_long.csv": windows,
        "phenology_sensitivity_decisions.csv": decisions,
        "phenology_composite_qa_and_canopy_coverage.csv": qa_audit,
        "threshold_city_window_eligibility_revised.csv": eligibility,
        "balance_diagnostics_readiness.csv": balance,
    }
    for name, frame in tables.items():
        path = OUTPUT / name
        frame.to_csv(path, index=False)
        artifacts.append(path)
    selection_path = OUTPUT / "selection_revised.json"
    write_json(selection_path, selection)
    artifacts.append(selection_path)

    primary_text = _passing_windows(decisions, "primary_phenology_pass")
    qa0_text = _passing_windows(decisions, "qa0_sensitivity_pass")
    canopy_text = _passing_windows(decisions, "canopy_sensitivity_pass")
    stable_text = _passing_windows(decisions, "phenology_auto_eligible")
    archive_counts = archive.get("pass_classification_counts", {})
    review = f"""# Gate 3 revised review — prospective sampling design

## Decision

`REVISE_REQUIRED — NO PRIMARY DESIGN IDENTIFIABLE UNDER D0067`

The requested revision was run without opening temperature/LST, thermal outcomes,
holdout data, or any 2026 record. The amended pre-result rule now fails before a
view-zenith threshold can be selected: only **{stable_city_count}** nonexploratory
cities remain stable across the primary, QA-rank-0-only, and canopy-masked
phenology analyses, versus the frozen minimum of four including Denver.

## Phenology reconciliation

- Whole-city QA ranks 0+1 pass: **{primary_text}**.
- Whole-city QA rank 0 only pass: **{qa0_text}**.
- Canopy-masked QA ranks 0+1 pass: **{canopy_text}**.
- Stable in all three analyses: **{stable_text}**.
- Usable composite counts are **{int(composites['primary_composite_usable'].sum())}/742**
  for the primary analysis, **{int(composites['good_composite_usable'].sum())}/742**
  for QA rank 0 only, and **{int(composites['canopy_primary_composite_usable'].sum())}/742**
  for the canopy-masked sensitivity.

Atlanta June–September and Phoenix April–May pass the primary city-level screen
but reverse under QA rank 0 only. Their canopy-masked results remain stable. Under
the frozen D0067 fail-closed rule they are `PHENOLOGY_SENSITIVE` and cannot be
auto-selected.

Phoenix's canopy-mask coverage is reported explicitly: its median retained
MODIS-cell fraction is **{float(qa_audit.loc[qa_audit['city'].eq('phoenix'), 'canopy_masked_cell_fraction_median'].iloc[0]):.3f}**.
The canopy result is therefore informative but spatially sparse and is not being
presented as a whole-city tree-health estimate.

## Inaccessible-pass resolution

The finite one-query/one-access-attempt recheck completed for all 31 historical
passes. Pass classifications: **{json.dumps(archive_counts, sort_keys=True)}**.
There were **{int(archive.get('unresolved_error_count', -1))}** unresolved query
errors; version-003 L1B was not queried because the official collection does not
exist. Lower/upper contributions are retained in
`archive_pass_bounded_recheck_and_bounds.csv` rather than silently dropping these
passes.

## Selector and balance diagnostics

The selector is no longer hard-coded to fail. Its successful known-answer test
selects 15° after rejecting 10°, and fail-closed tests cover phenotype reversal,
archive-bound failure, city share, missing balance evidence, and azimuth helpers.
Test status: **{'PASS' if selector_test['passed'] else 'FAIL'}**.
The complete regression run {'passed' if regression['all_passed'] else 'failed'}:
**{regression['counts']['v2']['passed']}/{regression['counts']['v2']['discovered']} v2 test
programs and {regression['counts']['legacy']['passed']}/{regression['counts']['legacy']['discovered']}
legacy test programs passed**.

The revised real-data selector still returns `REVISE_REQUIRED`. City-share,
entropy, AM/PM, wet/dry, and continuous-overlap diagnostics are implemented but
correctly marked not computable: with only two sensitivity-stable cities, no
threshold can meet the four-city rule. Completing thousands of new geometry,
cloud, and HRRR reads cannot change that upstream result. Those reads were
therefore not launched, and the packet does not mislabel metadata ceilings as
usable observations.

## What remains unresolved

The requested azimuth/cloud/exact-weather augmentation is not complete. This is
now a downstream evidence gap rather than the reason no design was selected. It
should be run only after the human chooses one of the following pre-result design
amendments:

1. keep QA-rank-0 and canopy results as reported sensitivities but remove automatic
   disqualification on a QA-0 reversal; or
2. retain D0067's strict confirmation rule and add enough predeclared candidate
   cities to restore at least four sensitivity-stable cities.

No larger angle threshold, Miami promotion, or favourable count can override the
current frozen four-city phenology failure.

## Locks

- Sampling design: `UNSELECTED`
- G3A: `LOCKED`
- Gate 4+: `LOCKED`
- Holdout: `UNSELECTED / UNOPENED`
- Temperature/LST and thermal outcomes: `UNOPENED`
- 2026 query or record: `NOT PERFORMED`

Human options: `APPROVE REVISE RESULT AND AMEND PHENOLOGY ROLE`, `ADD CANDIDATE
CITIES UNDER A NEW PRE-RESULT RULE`, or `STOP`.
"""
    review_path = OUTPUT / "review_revised.md"
    review_path.write_text(review, encoding="utf-8")
    artifacts.append(review_path)

    sources = [
        ROOT / "docs/v2/D0065_G3_PRE_RESULT_SAMPLING_RULES.md",
        ROOT / "docs/v2/D0066_G3_REVISION_AUTHORIZATION.md",
        ROOT / "docs/v2/D0067_G3_REVISION_PRE_RESULT_RULES.md",
        ROOT / "docs/v2/D0068_G3_L1B_COLLECTION_CLARIFICATION.md",
        PHENOLOGY_RAW,
        PHENOLOGY_RAW.with_suffix(PHENOLOGY_RAW.suffix + ".provenance.json"),
        ARCHIVE_SUMMARY,
        ARCHIVE_PASSES,
        ROOT / "src/urban_cooling_v2/hitl_gate3_sampling.py",
        ROOT / "src/run_v2_hitl_gate3_archive_recheck.py",
        ROOT / "src/run_v2_hitl_gate3_revision.py",
        ROOT / "src/test_v2_hitl_gate3_sampling.py",
    ]
    source_bindings = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "decision_ids": ["D0065", "D0066", "D0067", "D0068"],
        "sources": {str(path.relative_to(ROOT)): sha256_file(path) for path in sources},
        "temperature_or_lst_opened": False,
        "holdout_opened": False,
        "record_2026_queried": False,
    }
    source_path = OUTPUT / "source_bindings_revised.json"
    write_json(source_path, source_bindings)

    checks = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "decision_ids": ["D0065", "D0066", "D0067", "D0068"],
        "gate_status": selection["gate_status"],
        "sampling_design_selected": selection["sampling_design_selected"],
        "phenology_year_bounds_pass": bool(composites["year"].min() == 2018 and composites["year"].max() == 2025),
        "phenology_row_count": len(composites),
        "primary_usable_composites": int(composites["primary_composite_usable"].sum()),
        "qa0_usable_composites": int(composites["good_composite_usable"].sum()),
        "canopy_usable_composites": int(composites["canopy_primary_composite_usable"].sum()),
        "phenology_all_three_stable_unique_nonexploratory_cities": stable_city_count,
        "four_city_minimum_pass": stable_city_count >= 4,
        "archive_finite_recheck_pass": archive_clean,
        "archive_pass_count": len(archive_passes),
        "selector_known_answer_tests": selector_test,
        "full_v2_test_programs_discovered": regression["counts"]["v2"]["discovered"],
        "full_v2_test_programs_passed": regression["counts"]["v2"]["passed"],
        "full_legacy_test_programs_discovered": regression["counts"]["legacy"]["discovered"],
        "full_legacy_test_programs_passed": regression["counts"]["legacy"]["passed"],
        "full_regression_suite_passed": regression["all_passed"],
        "full_regression_suite_sha256": sha256_file(regression_path),
        "geometry_azimuth_cloud_exact_weather_augmentation_complete": False,
        "balance_diagnostics_implemented": True,
        "balance_diagnostics_real_data_computable": False,
        "all_declared_artifact_hashes": {
            str(path.relative_to(ROOT)): sha256_file(path) for path in artifacts
        },
        "source_bindings_sha256": sha256_file(source_path),
        "temperature_or_lst_opened": False,
        "holdout_opened": False,
        "record_2026_queried": False,
        "g3a_authorized": False,
        "gate4_authorized": False,
    }
    checks_path = OUTPUT / "checks_revised.json"
    write_json(checks_path, checks)
    return checks


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
