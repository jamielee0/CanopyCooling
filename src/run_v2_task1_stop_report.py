#!/usr/bin/env python3
"""Write the honest Task-1 STOP package after the frozen cloud gate fails."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from urban_cooling_v2.step02_catalog import (
    deduplicate_passes,
    filter_usable_passes,
    plot_attrition_waterfall,
    plot_count_heatmaps,
    plot_local_solar_histogram,
    plot_pass_date_strip,
    run_step2_checks,
    scene_metadata_dictionary,
    usable_pass_counts,
)


ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / "data/processed/v2/task1/step2_quality_screening"
BASE = (
    ROOT
    / "data/processed/v2/task1/step2_catalogue_audit/tables/"
    "step2_scene_catalogue_metadata_only.csv"
)
OUTPUT = ROOT / "data/processed/v2/task1/step2"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assemble_catalogue() -> pd.DataFrame:
    base = pd.read_csv(BASE)
    screened = pd.read_csv(QUALITY / "passes_quality_screened_pre_cloud.csv")
    base_keys = pd.MultiIndex.from_frame(base[["city", "orbit"]])
    screened_keys = pd.MultiIndex.from_frame(screened[["city", "orbit"]])
    if base_keys.duplicated().any() or screened_keys.duplicated().any():
        raise ValueError("catalogue rows must be unique by city/orbit")
    if int(base_keys.isin(screened_keys).sum()) != len(screened):
        raise ValueError("quality-screened daytime rows do not match the catalogue")
    screened["view_zenith_deg"] = screened["view_zenith_abs_p95_deg"]
    non_daytime = base.loc[~base_keys.isin(screened_keys)].copy()
    full = pd.concat([non_daytime, screened], ignore_index=True, sort=False)
    if len(full) != len(base) or full.duplicated(["city", "orbit"]).any():
        raise AssertionError("physical-pass catalogue identity changed")
    return full.sort_values(["city", "acquisition_utc", "orbit"])


def main() -> int:
    figures = OUTPUT / "figures"
    tables = OUTPUT / "tables"
    figures.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)

    catalogue = deduplicate_passes(_assemble_catalogue())
    candidates = filter_usable_passes(catalogue)
    counts = usable_pass_counts(candidates, years=range(2018, 2026))
    validation = pd.read_csv(QUALITY / "cloud_validation.csv")
    attrition_source = pd.read_csv(QUALITY / "T2.2_quality_attrition.csv")
    stage_order = {
        stage: index + 1
        for index, stage in enumerate(
            [
                "catalogue_physical_passes_all_local_solar_times",
                "daytime_10_to_18_local_solar",
                "geolocation_best_or_good",
                "no_obstruction_after_geolocation",
                "near_nadir_and_95pct_domain_coverage",
                "expected_cloud_surviving_pass_equivalents",
            ]
        )
    }
    attrition = attrition_source.assign(
        stage_order=attrition_source["stage"].map(stage_order),
        count_or_expected_count=attrition_source[
            "surviving_passes_or_equivalents"
        ],
        total_retention_pct=100 * attrition_source["fraction_of_catalogue"],
        stage_retention_pct=100
        * attrition_source["fraction_of_previous_stage"],
    )

    solar_cases = pd.DataFrame(
        [
            {"case": "phoenix", "date": "2023-07-15", "latitude": 33.5014810, "longitude": -111.9611870},
            {"case": "atlanta", "date": "2023-07-15", "latitude": 33.8362691, "longitude": -84.3365018},
            {"case": "miami", "date": "2023-07-15", "latitude": 26.1955769, "longitude": -80.2284942},
        ]
    )
    checks = run_step2_checks(
        catalogue,
        candidates,
        counts,
        validation,
        solar_cases,
        solar_engine="pvlib",
    )

    plot_local_solar_histogram(
        catalogue, figures / "F2.1_local_solar_time_histogram.png"
    )
    plot_count_heatmaps(
        candidates,
        figures / "F2.2_pre_cloud_near_nadir_candidate_heatmaps.png",
        figure_title="F2.2 partial — Near-nadir candidates before cloud extrapolation",
        count_label="Pre-cloud near-nadir candidates",
    )
    plot_attrition_waterfall(
        attrition, figures / "F2.3_attrition_waterfall_cloud_withheld.png"
    )
    plot_pass_date_strip(
        catalogue.loc[catalogue["daytime"].astype(bool)],
        figures / "F2.4_pass_date_strip.png",
    )

    counts.to_csv(tables / "T2.1_pre_cloud_candidate_counts.csv", index=False)
    attrition_source.to_csv(tables / "T2.2_attrition_cloud_withheld.csv", index=False)
    scene_metadata_dictionary().to_csv(
        tables / "T2.3_scene_metadata_dictionary.csv", index=False
    )
    catalogue.to_csv(tables / "step2_scene_catalogue_quality_screened.csv", index=False)
    checks.to_csv(tables / "step2_checks.csv", index=False)

    missing = OUTPUT / "F2.5_NOT_PRODUCED.md"
    missing.write_text(
        "# F2.5 not produced\n\n"
        "The exact-acquisition HRRR join was intentionally not launched because the "
        "frozen cloud-survival calibration exhausted every preregistered July stage "
        "without a complete two-city comparison. Under D0030, cloud extrapolation is "
        "withheld and the Step-2 gate is STOP. A plot labelled definitive would therefore "
        "overstate the available evidence.\n",
        encoding="utf-8",
    )

    city_counts = (
        candidates.groupby("city").size().sort_index().astype(int).to_dict()
    )
    cloud_audit = pd.read_csv(QUALITY / "cloud_stability_stage_audit.csv")
    zero_months = {
        city: str(
            cloud_audit.loc[
                cloud_audit["calibration_stage"].eq(
                    "expanded_2018_through_2025"
                )
                & cloud_audit["city"].eq(city),
                "missing_or_zero_pass_months",
            ].iloc[0]
        )
        for city in ("phoenix", "miami")
    }
    report = {
        "schema_version": 1,
        "task1_gate": "STOP_INCOMPLETE_CLOUD_CALIBRATION",
        "step1_gate": "cross_city_separation_only",
        "n_catalogue_physical_passes": int(len(catalogue)),
        "n_daytime_passes": int(catalogue["daytime"].sum()),
        "n_near_nadir_candidates": int(len(candidates)),
        "near_nadir_candidates_by_city": city_counts,
        "cloud_final_stage": "expanded_2018_through_2025",
        "cloud_reference_zero_or_missing_months": zero_months,
        "cloud_extrapolation": "withheld",
        "hrrr_exact_acquisition_fetch": "not_started_due_to_frozen_stop",
        "definitive_step3": "not_run_due_to_uncertified_count",
        "preliminary_step3": "retained_gate_ineligible",
        "quality_run_record_sha256": _sha256(QUALITY / "run_record.json"),
        "final_cloud_manifest_sha256": _sha256(
            ROOT / "data/raw/v2/ecostress/enrichment_manifest_cloud_final.csv"
        ),
        "checks_passed": int(checks["pass"].sum()),
        "checks_total": int(len(checks)),
    }
    (OUTPUT / "task1_stop_gate.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    failed_checks = checks.loc[~checks["pass"], ["check", "detail"]]
    failed_text = "\n".join(
        f"- **{row.check}:** {row.detail}" for row in failed_checks.itertuples()
    )
    memo = OUTPUT / "M2.1_stop_gate.md"
    memo.write_text(
        "# Step 2 feasibility gate\n\n"
        "**Gate: STOP — cloud survival cannot be extrapolated under the frozen rule.**\n\n"
        f"The catalogue contains 2,968 physical passes, including 1,055 in the "
        f"10:00–18:00 local-solar window. After geolocation, obstruction, 95% domain "
        f"coverage, and p95 |view zenith| ≤20° screening, **107** candidates remain: "
        f"{city_counts}.\n\n"
        "Phoenix's original July 2023/2022 comparison itself differs by only 1.67 "
        "percentage points. The gate fails because Miami has no qualifying pass in "
        "seven of eight required July years; Phoenix is also empty in 2018, 2021, and "
        "2025. Missing/zero-pass months were predeclared as non-validating. All three "
        "allowed expansion stages were exhausted, so the survival fraction is withheld.\n\n"
        "## Failed checks\n\n"
        + failed_text
        + "\n\n## Consequence\n\n"
        "F2.5 is not labelled or produced as definitive, exact-time HRRR acquisition "
        "was not launched, and the definitive Step 3 simulation was not run. The prior "
        "catalogue-ceiling simulation remains code validation only. A new scientific "
        "decision is required before changing the near-nadir/coverage definition, "
        "cloud-calibration design, or city panel.\n",
        encoding="utf-8",
    )

    task1 = ROOT / "data/processed/v2/task1/TASK1_GATE.md"
    task1.write_text(
        "# Task 1 feasibility result\n\n"
        "**Overall status: STOP / scientifically incomplete.**\n\n"
        "- Step 1 is complete and canonical: `cross_city_separation_only`; only Los "
        "Angeles and Minneapolis–St. Paul have adequate within-city off-diagonal support.\n"
        "- Step 2 catalogue, metadata, view-angle, and frozen cloud-expansion audits are "
        "complete. There are 107 pre-cloud near-nadir candidates, but cloud survival "
        "cannot be validated because required reference city-months contain zero such passes.\n"
        "- Step 3 definitive power is intentionally not run because the usable count is "
        "uncertified. The preliminary ceiling run is gate-ineligible.\n\n"
        "Do not proceed to thermal-response modelling until a supervisor/user explicitly "
        "chooses and freezes a redesigned feasibility rule. The 2026 season remains unopened, "
        "and no holdout city has been selected.\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
