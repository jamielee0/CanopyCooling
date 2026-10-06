#!/usr/bin/env python3
"""Network-free known-answer tests for the feedback closeout helpers."""

from __future__ import annotations

import math

import pandas as pd

import run_v2_feedback_closeout as closeout


def test_range_overlap_is_strict_and_missing_safe() -> None:
    assert closeout.finite_range_overlap([1, 3], [2, 4]) == 1
    assert closeout.finite_range_overlap([1, 2], [2, 3]) == 0
    assert closeout.finite_range_overlap([1], [3]) == -2
    assert math.isnan(closeout.finite_range_overlap([], [1]))


def test_vpd_known_answer_uses_kelvin_inputs_and_returns_kpa() -> None:
    value = closeout.vpd_kpa_from_kelvin(303.15, 293.15)
    assert abs(value - 1.9047837878315672) < 1e-12


def test_cloud_fill_semantics_do_not_turn_255_or_nan_into_cloud() -> None:
    assert closeout.cloud_semantics([0, 1, 254, 255, math.nan]) == {
        "clear": 1,
        "cloud": 2,
        "fill_or_missing": 2,
    }


def test_g4_requires_counts_and_both_positive_overlaps() -> None:
    rows = []
    for threshold in closeout.THRESHOLDS:
        for city, window in closeout.PRIMARY_CITY_WINDOWS:
            for wetness, vpds, days in (
                ("wet", [2.0, 2.5], [20, 40]),
                ("dry", [2.2, 2.7], [30, 50]),
            ):
                for index, (vpd, day) in enumerate(zip(vpds, days, strict=True)):
                    rows.append(
                        {
                            "threshold_deg": threshold,
                            "city": city,
                            "window_id": window,
                            "demand_level": "high",
                            "wetness_level": wetness,
                            "vpd_kpa_at_acquisition": vpd,
                            "day_of_window": day,
                            "physical_pass_id": f"{threshold}-{city}-{wetness}-{index}",
                        }
                    )
    result, checks = closeout.build_g4_high_demand_audit(pd.DataFrame(rows))
    assert result["city_case_support_pass"].all()
    assert all(value["pooled_high_demand_contrast_eligible"] for value in checks["thresholds"].values())
    broken = pd.DataFrame(rows)
    broken.loc[
        broken["city"].eq("phoenix") & broken["wetness_level"].eq("dry"),
        "vpd_kpa_at_acquisition",
    ] = 4.0
    _, failed = closeout.build_g4_high_demand_audit(broken)
    assert not any(value["pooled_high_demand_contrast_eligible"] for value in failed["thresholds"].values())


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"PASS test_v2_feedback_closeout ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
