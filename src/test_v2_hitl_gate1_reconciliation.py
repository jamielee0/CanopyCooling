#!/usr/bin/env python3
"""Network-free synthetic tests for the Gate-1 reconciliation logic."""

from __future__ import annotations

import pandas as pd

from urban_cooling_v2.hitl_gate1_reconciliation import (
    build_within_city_support,
    classify_final_status,
    expand_hrrr_brackets,
    validated_clear_domain_weights,
)


def test_final_statuses_are_mutually_exclusive_and_complete() -> None:
    frame = pd.DataFrame(
        {
            "daytime": [False, True, True, True, True, True, True, True, True],
            "geolocation_usable": [False, False, True, True, True, True, True, True, True],
            "metadata_candidate": [False, False, False, True, True, True, True, True, True],
            "d0047_profile_included": [False, False, False, False, True, True, True, True, True],
            "quality_candidate_pre_cloud_l1b": [
                False,
                False,
                False,
                False,
                False,
                False,
                False,
                True,
                True,
            ],
            "l1b_geometry_status": [
                None,
                None,
                None,
                "archive_unavailable_pre_geometry",
                "coverage_and_angle_fail",
                "angle_fail",
                "coverage_fail",
                "geometry_pass",
                "geometry_pass",
            ],
            "time_stratum": [
                None,
                "10-12",
                "10-12",
                "12-14",
                "14-16",
                "16-18",
                "10-12",
                "12-14",
                "16-18",
            ],
        }
    )
    assert classify_final_status(frame).tolist() == [
        "outside_daytime_10_18",
        "daytime_geolocation_excluded",
        "daytime_metadata_or_obstruction_excluded",
        "archive_unavailable_pre_geometry",
        "geometry_coverage_and_angle_fail",
        "geometry_angle_fail",
        "geometry_coverage_fail",
        "retained_midday_not_early_late",
        "retained_early_late_stratum_eligible",
    ]


def test_hrrr_brackets_count_assets_separately_from_passes() -> None:
    passes = pd.DataFrame(
        {
            "observation_id": ["a", "b"],
            "city": ["atlanta", "miami"],
            "acquisition": [
                "2020-06-01T12:30:00Z",
                "2020-06-01T12:45:00Z",
            ],
        }
    )
    links = expand_hrrr_brackets(passes)
    assert len(links) == 4
    assert links["observation_id"].nunique() == 2
    assert links["analysis_utc"].nunique() == 2
    assert set(links["bracket_role"]) == {"floor", "ceiling"}

    exact = expand_hrrr_brackets(
        pd.DataFrame(
            {
                "observation_id": ["c"],
                "city": ["phoenix"],
                "acquisition": ["2020-06-01T12:00:00Z"],
            }
        )
    )
    assert len(exact) == 1
    assert exact.loc[0, "bracket_role"] == "exact"


def test_pass_equivalent_formula_is_exact_and_fails_closed() -> None:
    frame = pd.DataFrame(
        {
            "n_clear_pixels_independent_of_view": [25, 0],
            "n_domain_pixels_cloud": [100, 40],
            "clear_domain_fraction": [0.25, 0.0],
        }
    )
    assert validated_clear_domain_weights(frame).tolist() == [0.25, 0.0]
    invalid = frame.copy()
    invalid.loc[0, "clear_domain_fraction"] = 0.30
    try:
        validated_clear_domain_weights(invalid)
    except ValueError as error:
        assert "clear-domain weights" in str(error)
    else:
        raise AssertionError("invalid clear-domain fraction must fail closed")


def test_within_city_support_keeps_zero_cells_and_raw_counts() -> None:
    passes = pd.DataFrame(
        {
            "city": ["atlanta", "atlanta"],
            "demand_level": ["low", "high"],
            "dryness_level": ["dry", "wet"],
            "early_late_stratum_eligible": [True, False],
            "clear_domain_fraction": [0.25, 0.75],
        }
    )
    result = build_within_city_support(passes)
    assert len(result) == 18  # nine cells for Atlanta plus nine overall
    low_dry = result.loc[
        result["city"].eq("ALL_CITIES")
        & result["condition_cell"].eq("demand_low__antecedent_dry")
    ].iloc[0]
    assert low_dry["retained_physical_passes"] == 1
    assert low_dry["retained_pass_equivalent_sum"] == 0.25
    assert low_dry["early_late_stratum_eligible_physical_passes"] == 1
    assert low_dry["early_late_stratum_eligible_pass_equivalent_sum"] == 0.25
    zero = result.loc[
        result["city"].eq("atlanta")
        & result["condition_cell"].eq("demand_middle__antecedent_middle")
    ].iloc[0]
    assert zero["retained_physical_passes"] == 0
    assert zero["retained_pass_equivalent_sum"] == 0.0


if __name__ == "__main__":
    test_final_statuses_are_mutually_exclusive_and_complete()
    test_hrrr_brackets_count_assets_separately_from_passes()
    test_pass_equivalent_formula_is_exact_and_fails_closed()
    test_within_city_support_keeps_zero_cells_and_raw_counts()
    print("Gate-1 reconciliation tests passed (4 tests).")
