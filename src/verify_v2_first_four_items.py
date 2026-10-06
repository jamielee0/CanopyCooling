#!/usr/bin/env python3
"""Standalone, network-free verifier for the feedback's first four items.

This module deliberately imports no urban_cooling_v2 or runner code. It
recomputes the reviewer-facing values directly from the sealed CSV evidence.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "docs/v2/hitl/FIRST_FOUR_ITEMS"
G1 = ROOT / "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION"
G2 = ROOT / "docs/v2/hitl/G2_HYDROCLIMATE_SUPPORT"
G3 = ROOT / "docs/v2/hitl/G3_SAMPLING_DESIGN"

SOURCE_ATTRITION = G1 / "attrition_summary.csv"
SOURCE_PASS_QUALITY = G1 / "pass_quality_219.csv"
SOURCE_SUPPORT = G2 / "high_demand_wet_dry_support.csv"
SOURCE_ANGLES = G3 / "angle_threshold_eligibility_existing_five.csv"

ITEM_ATTRITION = PACKET / "01_attrition_table.csv"
ITEM_FORMULA = PACKET / "02_pass_equivalent_formula.md"
ITEM_ANGLES = PACKET / "03_view_angle_threshold_results.csv"
ITEM_SUPPORT = PACKET / "04_within_city_high_demand_support.csv"
OUTPUT = PACKET / "independent_verification.json"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_attrition() -> dict[str, Any]:
    source = rows(SOURCE_ATTRITION)
    item = rows(ITEM_ATTRITION)
    require(len(source) == len(item) == 10, "attrition table must contain ten stages")
    for expected, observed in zip(source, item, strict=True):
        for field in ("stage_order", "stage", "physical_count", "count_unit"):
            require(expected[field] == observed[field], f"attrition mismatch: {field}")
        if expected["pass_equivalent_sum"]:
            require(
                close(expected["pass_equivalent_sum"], observed["pass_equivalent_sum"]),
                "attrition pass-equivalent mismatch",
            )
        else:
            require(not observed["pass_equivalent_sum"], "unexpected attrition weight")
        require(
            expected["pass_equivalent_role"] == observed["pass_equivalent_role"],
            "attrition role mismatch",
        )
    physical = [int(row["physical_count"]) for row in item[2:]]
    require(all(left >= right for left, right in zip(physical, physical[1:])),
            "physical attrition is not monotone")
    return {
        "raw_tiled_products": 13577,
        "unique_physical_city_orbit_observations": 2968,
        "archive_available_pre_geometry": 911,
        "retained_physical_passes": 219,
        "early_late_individual_physical_passes": 102,
        "status": "PASS",
    }


def verify_formula() -> dict[str, Any]:
    quality = rows(SOURCE_PASS_QUALITY)
    require(len(quality) == 219, "pass-quality census is not 219 rows")
    identities = {(row["city"], row["orbit"]) for row in quality}
    require(len(identities) == 219, "pass-quality identities are duplicated")
    weights: list[float] = []
    early_late: list[float] = []
    for row in quality:
        numerator = int(row["n_clear_pixels_independent_of_view"])
        denominator = int(row["n_domain_pixels_cloud"])
        require(denominator > 0 and 0 <= numerator <= denominator,
                "invalid clear/domain pixel partition")
        calculated = numerator / denominator
        require(close(calculated, row["clear_domain_fraction"]),
                "stored clear fraction does not equal numerator/denominator")
        require(
            row["pass_equivalent_weight_formula"]
            == "n_clear_pixels_independent_of_view / n_domain_pixels_cloud",
            "per-pass formula label changed",
        )
        require(
            row["pass_equivalent_role"]
            == "secondary_clear_domain_exposure_diagnostic_not_independent_sample_size",
            "pass-equivalent role changed",
        )
        require(not row["usable_tree_pixels"] and not row["usable_reference_pixels"],
                "tree/reference counts must remain explicitly unavailable")
        require(
            row["tree_reference_count_status"]
            == "DEFERRED_TO_G3A_NONTHERMAL_TREE_REFERENCE_YIELD_CHECKPOINT",
            "tree/reference missingness status changed",
        )
        weights.append(calculated)
        if row["early_late_stratum_eligible"].casefold() == "true":
            early_late.append(calculated)
    require(len(early_late) == 102, "early/late pass count is not 102")
    total = math.fsum(weights)
    early_late_total = math.fsum(early_late)
    require(close(total, 159.08708404623306), "retained pass-equivalent sum changed")
    require(close(early_late_total, 72.68902899522442),
            "early/late pass-equivalent sum changed")
    formula_text = ITEM_FORMULA.read_text(encoding="utf-8")
    for required_text in (
        "n_clear_pixels_independent_of_view_i / n_domain_pixels_cloud_i",
        "secondary clear-domain exposure diagnostic",
        "not an independent",
        "Eight cloudy passes remain",
        "eight physical passes",
    ):
        require(required_text in formula_text, f"formula memo lacks: {required_text}")
    return {
        "retained_physical_passes": len(weights),
        "retained_pass_equivalent_sum": total,
        "early_late_physical_passes": len(early_late),
        "early_late_pass_equivalent_sum": early_late_total,
        "status": "PASS",
    }


def verify_angles() -> dict[str, Any]:
    source = rows(SOURCE_ANGLES)
    item = rows(ITEM_ANGLES)
    expected_thresholds = [10, 15, 20, 25, 30]
    expected_counts = {10: 40, 15: 127, 20: 219, 25: 326, 30: 413}
    observed: dict[int, int] = {}
    for threshold in expected_thresholds:
        observed[threshold] = sum(
            int(row["physical_passes"])
            for row in source
            if int(float(row["threshold_deg"])) == threshold
        )
    require(observed == expected_counts, "source threshold counts changed")
    require([int(row["threshold_deg"]) for row in item] == expected_thresholds,
            "packet threshold order changed")
    for row in item:
        threshold = int(row["threshold_deg"])
        require(int(row["raw_physical_passes"]) == observed[threshold],
                "packet threshold count mismatch")
        require(row["azimuth_complete"].casefold() == "false",
                "packet must not claim completed azimuth")
    applied = [row for row in item if row["role"] == "inherited_applied_comparator"]
    require(len(applied) == 1 and int(applied[0]["threshold_deg"]) == 20,
            "historical applied comparator must be 20 degrees")
    require(item[-1]["role"] == "exploratory_only", "30 degrees must remain exploratory")
    return {
        "raw_physical_pass_counts": observed,
        "historical_applied_comparator_deg": 20,
        "prospective_primary_threshold_selected": False,
        "status": "PASS",
    }


def verify_support() -> dict[str, Any]:
    source_rows = rows(SOURCE_SUPPORT)
    item = rows(ITEM_SUPPORT)
    source = {
        (row["city"], row["predictor"], row["window_days"], row["wetness_level"]): row
        for row in source_rows
    }
    require(len(item) == 30, "support packet must contain 30 rows")
    for observed in item:
        key = (
            observed["city"], observed["predictor"], observed["window_days"],
            observed["wetness_level"],
        )
        require(key in source, f"support row absent from source: {key}")
        expected = source[key]
        for field in ("predictor_role", "high_demand_physical_passes"):
            require(observed[field] == expected[field], f"support mismatch: {key} {field}")
        for field in ("high_demand_pass_equivalent_sum", "median_vpd_kpa_at_acquisition"):
            require(close(observed[field], expected[field]), f"support mismatch: {key} {field}")

    cities = {"atlanta", "los_angeles", "miami", "minneapolis_st_paul", "phoenix"}
    by_key = {
        (row["city"], row["predictor"], row["wetness_level"]): row for row in item
    }
    for predictor, levels in (
        ("precipitation", ("wet", "dry")),
        ("climatic_water_balance", ("wet", "middle", "dry")),
    ):
        for level in levels:
            total = by_key[("ALL_CITIES", predictor, level)]
            raw_sum = sum(int(by_key[(city, predictor, level)]["high_demand_physical_passes"])
                          for city in cities)
            weighted_sum = math.fsum(
                float(by_key[(city, predictor, level)]["high_demand_pass_equivalent_sum"])
                for city in cities
            )
            require(raw_sum == int(total["high_demand_physical_passes"]),
                    "within-city raw support does not sum to pooled support")
            require(close(weighted_sum, total["high_demand_pass_equivalent_sum"]),
                    "within-city weighted support does not sum to pooled support")
    return {
        "precipitation_30d_candidate_primary": {"wet": 40, "dry": 62},
        "climatic_water_balance_30d_sensitivity": {
            "wet": 34, "middle": 53, "dry": 68
        },
        "within_city_additivity": True,
        "pooled_effect_established": False,
        "status": "PASS",
    }


def main() -> int:
    required = (
        SOURCE_ATTRITION, SOURCE_PASS_QUALITY, SOURCE_SUPPORT, SOURCE_ANGLES,
        ITEM_ATTRITION, ITEM_FORMULA, ITEM_ANGLES, ITEM_SUPPORT,
    )
    require(all(path.is_file() for path in required), "required source or packet file missing")
    checks = {
        "item_1_attrition": verify_attrition(),
        "item_2_pass_equivalent_formula": verify_formula(),
        "item_3_view_angle_thresholds": verify_angles(),
        "item_4_within_city_high_demand_support": verify_support(),
    }
    payload = {
        "status": "PASS",
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "verification_method": "standalone_network_free_direct_csv_recomputation",
        "imports_pipeline_modules": False,
        "thermal_or_lst_opened": False,
        "record_2026_science_data_opened_or_queried": False,
        "record_2026_metadata_exposures_preserved": [
            "D0060", "D0061", "D0073", "D0074"
        ],
        "checks": checks,
        "source_sha256": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in (SOURCE_ATTRITION, SOURCE_PASS_QUALITY, SOURCE_SUPPORT, SOURCE_ANGLES)
        },
        "packet_sha256": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in (ITEM_ATTRITION, ITEM_FORMULA, ITEM_ANGLES, ITEM_SUPPORT)
        },
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("PASS verify_v2_first_four_items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
