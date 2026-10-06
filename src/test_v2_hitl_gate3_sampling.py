#!/usr/bin/env python3
"""Network-free known-answer tests for the frozen Gate-3 rules."""

from __future__ import annotations

from contextlib import contextmanager

import pandas as pd

from urban_cooling_v2.hitl_gate3_sampling import (
    add_antecedent_predictors,
    build_archive_bound_diagnostics,
    build_balance_diagnostics,
    circular_mean_concentration,
    histogram_overlap_coefficient,
    relative_azimuth_deg,
    selection_result,
    summarize_leaf_on,
    summarize_phenology_sensitivities,
)


@contextmanager
def _raises(error_type: type[Exception], message: str):
    try:
        yield
    except error_type as exc:
        assert message in str(exc), str(exc)
    else:
        raise AssertionError(f"Expected {error_type.__name__} containing {message!r}")


def _qualifying_pass_detail() -> pd.DataFrame:
    cities = ("atlanta", "denver_aurora", "minneapolis_st_paul", "phoenix")
    rows = []
    for threshold in (10, 15, 20, 25):
        for city_index, city in enumerate(cities):
            for index in range(6):
                rows.append(
                    {
                        "threshold_deg": threshold,
                        "physical_pass_id": f"{city}:{index}",
                        "city": city,
                        "window_id": "phoenix_apr_may" if city == "phoenix" else "jun_sep",
                        "time_stratum": "10-12" if index < 3 else "16-18",
                        "demand_level": "high",
                        "wetness_level": "wet" if index % 2 else "dry",
                        "vpd_kpa_at_acquisition": 1.0 + city_index / 10 + index / 100,
                        "antecedent_precipitation_30d_mm": 10.0 + index,
                        "l1b_geometry_coverage_fraction": 0.99,
                        "l1b_view_zenith_abs_p95_deg": 8.0,
                        "view_azimuth_circular_mean_deg": 120.0 + index,
                        "solar_azimuth_circular_mean_deg": 150.0 + index,
                        "relative_azimuth_median_deg": 30.0,
                        "geometry_azimuth_complete": True,
                        "cloud_complete": True,
                        "exact_weather_complete": True,
                        "day_of_window": 10 + index,
                        "air_temperature_k_at_acquisition": 295.0 + index / 10,
                        "wind_speed_m_s_at_acquisition": 2.0 + index / 20,
                    }
                )
    return pd.DataFrame(rows)


def test_leaf_on_rule() -> None:
    rows = []
    for year in range(2018, 2026):
        for month, ndvi in [(4, 0.50), (5, 0.80), (6, 0.95), (7, 1.00), (8, 0.96), (9, 0.91), (10, 0.70)]:
            rows.append(
                {
                    "city": "phoenix",
                    "date": pd.Timestamp(year=year, month=month, day=1),
                    "year": year,
                    "month": month,
                    "primary_median": ndvi,
                    "primary_valid_fraction": 0.9,
                    "primary_composite_usable": True,
                }
            )
    monthly, windows = summarize_leaf_on(pd.DataFrame(rows))
    stable = set(monthly.loc[monthly["stable_leaf_on"], "month"])
    assert stable == {6, 7, 8, 9}
    summer = windows.loc[
        windows["city"].eq("phoenix") & windows["window_id"].eq("jun_sep")
    ].iloc[0]
    shoulder = windows.loc[
        windows["city"].eq("phoenix") & windows["window_id"].eq("phoenix_apr_may")
    ].iloc[0]
    assert bool(summer["all_months_stable_leaf_on"])
    assert not bool(shoulder["all_months_stable_leaf_on"])


def test_prior_day_windows() -> None:
    frame = pd.DataFrame(
        {
            "city": ["x"] * 65,
            "date": pd.date_range("2020-01-01", periods=65),
            "pr_mm": [1.0] * 64 + [1000.0],
            "eto_mm": [0.0] * 65,
            "vpd_kpa": [1.0] * 65,
            "tmmx_k": [300.0] * 65,
        }
    )
    result = add_antecedent_predictors(frame)
    assert result.iloc[-1]["antecedent_precipitation_30d_mm"] == 30.0
    assert result.iloc[-1]["antecedent_precipitation_60d_mm"] == 60.0


def test_selection_fails_closed() -> None:
    eligibility = pd.DataFrame(
        {
            "threshold_deg": [10, 15, 20, 25],
            "eligible_city_window": [True, True, True, True],
        }
    )
    result = selection_result(eligibility)
    assert result["gate_status"] == "REVISE_REQUIRED"
    assert result["sampling_design_selected"] is False
    assert result["primary_view_zenith_threshold_deg"] is None


def test_selection_requires_explicit_phenology_evidence() -> None:
    cities = ["atlanta", "minneapolis_st_paul", "denver_aurora", "phoenix"]
    eligibility = pd.DataFrame(
        [
            {
                "threshold_deg": threshold,
                "city": city,
                "window_id": "phoenix_apr_may" if city == "phoenix" else "jun_sep",
                "archive_bounds_invariant": True,
                "eligible_city_window": True,
            }
            for threshold in (10, 15, 20, 25)
            for city in cities
        ]
    )
    membership = [
        "atlanta/jun_sep",
        "denver_aurora/jun_sep",
        "minneapolis_st_paul/jun_sep",
        "phoenix/phoenix_apr_may",
    ]
    balance = pd.DataFrame(
        [
            {
                "threshold_deg": threshold,
                "unique_cities": 4,
                "city_window_membership": pd.Series(membership).to_json(orient="values"),
                "histogram_diagnostics_complete": True,
                "entropy_diagnostic_complete": True,
                "geometry_diagnostics_complete": True,
                "city_share_cap_pass": True,
                "am_pm_support_diagnostics_complete": True,
                "wet_dry_support_diagnostics_complete": True,
                "within_city_vpd_overlap_complete_and_positive": True,
                "season_overlap_diagnostics_complete": True,
                "weather_overlap_diagnostics_complete": True,
                "archive_bounds_invariant": True,
            }
            for threshold in (10, 15, 20, 25)
        ]
    )
    assert selection_result(eligibility, balance)["sampling_design_selected"] is False


def test_phenology_sensitivities_detect_reversal() -> None:
    rows = []
    for year in range(2018, 2026):
        for month in range(4, 11):
            primary = 1.0 if month in {6, 7, 8, 9} else 0.5
            good = primary if month != 9 else 0.4
            rows.append(
                {
                    "city": "atlanta",
                    "year": year,
                    "month": month,
                    "primary_median": primary,
                    "primary_valid_fraction": 0.9,
                    "primary_composite_usable": True,
                    "good_median": good,
                    "good_valid_fraction": 0.9,
                    "good_composite_usable": True,
                    "canopy_primary_median": primary,
                    "canopy_primary_valid_fraction": 0.9,
                    "canopy_primary_composite_usable": True,
                }
            )
    _, _, decisions = summarize_phenology_sensitivities(pd.DataFrame(rows))
    summer = decisions.loc[
        decisions["city"].eq("atlanta") & decisions["window_id"].eq("jun_sep")
    ].iloc[0]
    assert bool(summer["primary_phenology_pass"])
    assert not bool(summer["qa0_sensitivity_pass"])
    assert summer["qa0_sensitivity_status"] == "QA0_THRESHOLD_REVERSAL"
    assert summer["phenology_status"] == "PRIMARY_AND_CANOPY_CONFIRMED"
    assert bool(summer["phenology_auto_eligible"])


def test_phenology_sensitivities_distinguish_incomplete_qa0_coverage() -> None:
    rows = []
    for year in range(2018, 2026):
        for month in range(4, 11):
            primary = 1.0 if month in {6, 7, 8, 9} else 0.5
            qa0_usable = not (month == 7 and year < 2023)
            rows.append(
                {
                    "city": "atlanta",
                    "year": year,
                    "month": month,
                    "primary_median": primary,
                    "primary_valid_fraction": 0.9,
                    "primary_composite_usable": True,
                    "good_median": primary,
                    "good_valid_fraction": 0.9 if qa0_usable else 0.1,
                    "good_composite_usable": qa0_usable,
                    "canopy_primary_median": primary,
                    "canopy_primary_valid_fraction": 0.9,
                    "canopy_primary_composite_usable": True,
                }
            )
    _, _, decisions = summarize_phenology_sensitivities(pd.DataFrame(rows))
    summer = decisions.loc[
        decisions["city"].eq("atlanta") & decisions["window_id"].eq("jun_sep")
    ].iloc[0]
    assert summer["qa0_sensitivity_status"] == "QA0_INCOMPLETE_YEAR_COVERAGE"
    assert not bool(summer["qa0_sensitivity_coverage_complete"])
    assert bool(summer["phenology_auto_eligible"])


def test_phenology_requires_canopy_confirmation() -> None:
    rows = []
    for year in range(2018, 2026):
        for month in range(4, 11):
            primary = 1.0 if month in {6, 7, 8, 9} else 0.5
            canopy = 0.4 if month == 9 else primary
            rows.append(
                {
                    "city": "atlanta",
                    "year": year,
                    "month": month,
                    "primary_median": primary,
                    "primary_valid_fraction": 0.9,
                    "primary_composite_usable": True,
                    "good_median": primary,
                    "good_valid_fraction": 0.9,
                    "good_composite_usable": True,
                    "canopy_primary_median": canopy,
                    "canopy_primary_valid_fraction": 0.9,
                    "canopy_primary_composite_usable": True,
                }
            )
    _, _, decisions = summarize_phenology_sensitivities(pd.DataFrame(rows))
    summer = decisions.loc[
        decisions["city"].eq("atlanta") & decisions["window_id"].eq("jun_sep")
    ].iloc[0]
    assert bool(summer["primary_phenology_pass"])
    assert not bool(summer["canopy_sensitivity_pass"])
    assert summer["phenology_status"] == "CANOPY_CONFIRMATION_FAIL"
    assert not bool(summer["phenology_auto_eligible"])


def test_azimuth_and_overlap_helpers() -> None:
    relative = relative_azimuth_deg([350.0, 10.0], [10.0, 350.0])
    assert relative.tolist() == [20.0, 20.0]
    mean, concentration = circular_mean_concentration([350.0, 10.0])
    assert min(abs(mean), abs(mean - 360.0)) < 1e-9
    assert 0.98 < concentration <= 1.0
    assert histogram_overlap_coefficient([0, 1, 2], [0, 1, 2]) == 1.0


def test_balance_diagnostics_and_successful_smallest_selector() -> None:
    cities = ["atlanta", "minneapolis_st_paul", "denver_aurora", "phoenix"]
    passes = []
    for threshold in (10, 15, 20, 25):
        for city_index, city in enumerate(cities):
            for index in range(6):
                passes.append(
                    {
                        "threshold_deg": threshold,
                        "physical_pass_id": f"{city}:{index}",
                        "city": city,
                        "window_id": "phoenix_apr_may" if city == "phoenix" else "jun_sep",
                        "time_stratum": "10-12" if index < 3 else "16-18",
                        "demand_level": "high",
                        "wetness_level": "wet" if index % 2 else "dry",
                        "vpd_kpa_at_acquisition": 1.0 + 0.1 * city_index + 0.01 * index,
                        "antecedent_precipitation_30d_mm": 10.0 + index,
                        "l1b_geometry_coverage_fraction": 0.99,
                        "l1b_view_zenith_abs_p95_deg": 8.0 + 0.5 * city_index,
                        "view_azimuth_circular_mean_deg": 120.0 + index,
                        "solar_azimuth_circular_mean_deg": 150.0 + index,
                        "relative_azimuth_median_deg": 30.0 + index,
                        "geometry_azimuth_complete": True,
                        "cloud_complete": True,
                        "exact_weather_complete": True,
                        "day_of_window": 10 + index,
                        "air_temperature_k_at_acquisition": 295.0 + 0.1 * index,
                        "wind_speed_m_s_at_acquisition": 2.0 + 0.05 * index,
                    }
                )
    balance, pairs = build_balance_diagnostics(pd.DataFrame(passes))
    assert len(pairs) == 24
    assert balance["city_share_cap_pass"].all()
    assert balance["am_pm_support_diagnostics_complete"].all()
    assert balance["wet_dry_support_diagnostics_complete"].all()
    assert balance["within_city_vpd_overlap_complete_and_positive"].all()
    assert balance["season_overlap_diagnostics_complete"].all()
    assert balance["weather_overlap_diagnostics_complete"].all()
    assert balance["geometry_diagnostics_complete"].all()
    balance["archive_bounds_invariant"] = True

    eligibility_rows = []
    for threshold in (10, 15, 20, 25):
        binding = balance.loc[balance["threshold_deg"].eq(threshold)].iloc[0]
        for city in cities:
            eligibility_rows.append(
                {
                    "threshold_deg": threshold,
                    "city": city,
                    "window_id": "phoenix_apr_may" if city == "phoenix" else "jun_sep",
                    "phenology_auto_eligible": True,
                    "archive_bounds_invariant": True,
                    "eligible_city_window": threshold >= 15,
                    "qualifying_pass_count": int(binding["qualifying_pass_count"]),
                    "qualifying_pass_set_sha256": binding["qualifying_pass_set_sha256"],
                }
            )
    result = selection_result(pd.DataFrame(eligibility_rows), balance)
    assert result["gate_status"] == "SELECTED_AWAITING_HUMAN_APPROVAL"
    assert result["sampling_design_selected"] is True
    assert result["primary_view_zenith_threshold_deg"] == 15


def test_selector_rejects_city_share_and_archive_bound_failures() -> None:
    cities = ["atlanta", "minneapolis_st_paul", "denver_aurora", "phoenix"]
    eligibility = pd.DataFrame(
        [
            {
                "threshold_deg": threshold,
                "city": city,
                "window_id": "jun_sep",
                "phenology_auto_eligible": True,
                "archive_bounds_invariant": city != "atlanta",
                "eligible_city_window": True,
            }
            for threshold in (10, 15, 20, 25)
            for city in cities
        ]
    )
    balance = pd.DataFrame(
        {
            "threshold_deg": [10, 15, 20, 25],
            "histogram_diagnostics_complete": [True] * 4,
            "entropy_diagnostic_complete": [True] * 4,
            "city_share_cap_pass": [False] * 4,
            "am_pm_support_diagnostics_complete": [True] * 4,
            "wet_dry_support_diagnostics_complete": [True] * 4,
            "within_city_vpd_overlap_complete_and_positive": [True] * 4,
            "season_overlap_diagnostics_complete": [True] * 4,
            "weather_overlap_diagnostics_complete": [True] * 4,
            "archive_bounds_invariant": [True] * 4,
        }
    )
    assert selection_result(eligibility, balance)["sampling_design_selected"] is False


def test_selector_rejects_false_support_and_weather_flags() -> None:
    cities = ["atlanta", "minneapolis_st_paul", "denver_aurora", "phoenix"]
    eligibility = pd.DataFrame(
        [
            {
                "threshold_deg": threshold,
                "city": city,
                "window_id": "phoenix_apr_may" if city == "phoenix" else "jun_sep",
                "phenology_auto_eligible": True,
                "archive_bounds_invariant": True,
                "eligible_city_window": True,
            }
            for threshold in (10, 15, 20, 25)
            for city in cities
        ]
    )
    balance = pd.DataFrame(
        {
            "threshold_deg": [10, 15, 20, 25],
            "histogram_diagnostics_complete": [True] * 4,
            "entropy_diagnostic_complete": [True] * 4,
            "city_share_cap_pass": [True] * 4,
            "am_pm_support_diagnostics_complete": [False] * 4,
            "wet_dry_support_diagnostics_complete": [False] * 4,
            "within_city_vpd_overlap_complete_and_positive": [True] * 4,
            "season_overlap_diagnostics_complete": [True] * 4,
            "weather_overlap_diagnostics_complete": [False] * 4,
            "archive_bounds_invariant": [True] * 4,
        }
    )
    result = selection_result(eligibility, balance)
    assert result["sampling_design_selected"] is False
    assert result["primary_view_zenith_threshold_deg"] is None


def test_selector_rejects_balance_membership_mismatch() -> None:
    passes = _qualifying_pass_detail()
    passes = passes.loc[~passes["city"].eq("phoenix")].copy()
    balance, _ = build_balance_diagnostics(passes)
    assert balance["threshold_deg"].tolist() == [10, 15, 20, 25]
    assert balance["unique_cities"].eq(3).all()
    assert not balance["exact_primary_city_window_membership"].any()
    assert not balance["histogram_diagnostics_complete"].any()


def test_balance_rejects_substituted_membership_and_duplicate_inflation() -> None:
    cities = ["atlanta", "minneapolis_st_paul", "denver_aurora", "phoenix"]
    rows = []
    for city_index, city in enumerate(cities):
        for index in range(6):
            rows.append(
                {
                    "threshold_deg": 10,
                    "physical_pass_id": f"{city}:{index}",
                    "city": city,
                    "window_id": "phoenix_apr_may" if city == "phoenix" else "jun_sep",
                    "time_stratum": "10-12" if index < 3 else "16-18",
                    "demand_level": "high",
                    "wetness_level": "wet" if index % 2 else "dry",
                    "vpd_kpa_at_acquisition": 1.0 + 0.1 * city_index + 0.01 * index,
                    "antecedent_precipitation_30d_mm": 10.0 + index,
                    "l1b_geometry_coverage_fraction": 0.99,
                    "l1b_view_zenith_abs_p95_deg": 8.0,
                    "view_azimuth_circular_mean_deg": 120.0 + index,
                    "solar_azimuth_circular_mean_deg": 150.0 + index,
                    "relative_azimuth_median_deg": 30.0 + index,
                    "geometry_azimuth_complete": True,
                    "cloud_complete": True,
                    "exact_weather_complete": True,
                    "day_of_window": 10 + index,
                    "air_temperature_k_at_acquisition": 295.0 + index / 10,
                    "wind_speed_m_s_at_acquisition": 2.0 + index / 20,
                }
            )
    valid = pd.DataFrame(rows)
    substituted = valid.copy()
    substituted.loc[substituted["city"].eq("phoenix"), ["city", "window_id"]] = [
        "los_angeles",
        "jun_sep",
    ]
    with _raises(ValueError, "out-of-scope city-window"):
        build_balance_diagnostics(substituted)

    duplicated = pd.concat([valid, valid.iloc[[0]]], ignore_index=True)
    with _raises(ValueError, "duplicate physical pass identities"):
        build_balance_diagnostics(duplicated)


def test_balance_requires_all_weather_and_geometry_fields() -> None:
    base = _qualifying_pass_detail()
    for column in (
        "wind_speed_m_s_at_acquisition",
        "view_azimuth_circular_mean_deg",
        "relative_azimuth_median_deg",
        "l1b_view_zenith_abs_p95_deg",
    ):
        with _raises(ValueError, "missing"):
            build_balance_diagnostics(base.drop(columns=column))


def test_balance_rejects_nonqualifying_duplicate_and_nonnested_rows() -> None:
    valid = _qualifying_pass_detail()

    nonqualifying = valid.copy()
    nonqualifying.loc[0, "l1b_geometry_coverage_fraction"] = 0.94
    with _raises(ValueError, "nonqualifying physical passes"):
        build_balance_diagnostics(nonqualifying)

    duplicated = pd.concat([valid, valid.iloc[[0]]], ignore_index=True)
    with _raises(ValueError, "duplicate physical pass identities"):
        build_balance_diagnostics(duplicated)

    nonnested = valid.loc[
        ~(
            valid["threshold_deg"].eq(15)
            & valid["physical_pass_id"].eq("atlanta:0")
        )
    ].copy()
    with _raises(ValueError, "not nested"):
        build_balance_diagnostics(nonnested)


def test_selector_rejects_string_booleans_and_substituted_membership() -> None:
    cities = ["atlanta", "denver_aurora", "minneapolis_st_paul", "phoenix"]
    membership = sorted(
        f"{city}/{'phoenix_apr_may' if city == 'phoenix' else 'jun_sep'}"
        for city in cities
    )
    eligibility = pd.DataFrame(
        [
            {
                "threshold_deg": threshold,
                "city": city,
                "window_id": "phoenix_apr_may" if city == "phoenix" else "jun_sep",
                "phenology_auto_eligible": True,
                "archive_bounds_invariant": True,
                "eligible_city_window": True,
            }
            for threshold in (10, 15, 20, 25)
            for city in cities
        ]
    )
    balance = pd.DataFrame(
        [
            {
                "threshold_deg": threshold,
                "unique_cities": 4,
                "city_window_membership": pd.Series(membership).to_json(orient="values"),
                "histogram_diagnostics_complete": "False",
                "entropy_diagnostic_complete": True,
                "geometry_diagnostics_complete": True,
                "city_share_cap_pass": True,
                "am_pm_support_diagnostics_complete": True,
                "wet_dry_support_diagnostics_complete": True,
                "within_city_vpd_overlap_complete_and_positive": True,
                "season_overlap_diagnostics_complete": True,
                "weather_overlap_diagnostics_complete": True,
                "archive_bounds_invariant": True,
            }
            for threshold in (10, 15, 20, 25)
        ]
    )
    result = selection_result(eligibility, balance)
    assert result["sampling_design_selected"] is False
    assert result["threshold_status"]["10"]["eligible_city_windows"] == 4

    balance["histogram_diagnostics_complete"] = True
    eligibility["phenology_auto_eligible"] = eligibility["phenology_auto_eligible"].astype(object)
    eligibility.loc[eligibility["city"].eq("atlanta"), "phenology_auto_eligible"] = "False"
    result = selection_result(eligibility, balance)
    assert result["sampling_design_selected"] is False

    substituted = eligibility.copy()
    substituted["phenology_auto_eligible"] = True
    substituted.loc[
        substituted["city"].eq("phoenix"), ["city", "window_id"]
    ] = ["los_angeles", "jun_sep"]
    result = selection_result(substituted, balance)
    assert result["sampling_design_selected"] is False
    assert not result["threshold_status"]["10"]["exact_d0069_city_window_membership"]


def test_selector_requires_matching_certified_pass_set_hash_and_count() -> None:
    balance, _ = build_balance_diagnostics(_qualifying_pass_detail())
    balance["archive_bounds_invariant"] = True
    rows = []
    for threshold in (10, 15, 20, 25):
        binding = balance.loc[balance["threshold_deg"].eq(threshold)].iloc[0]
        for city in ("atlanta", "denver_aurora", "minneapolis_st_paul", "phoenix"):
            rows.append(
                {
                    "threshold_deg": threshold,
                    "city": city,
                    "window_id": "phoenix_apr_may" if city == "phoenix" else "jun_sep",
                    "phenology_auto_eligible": True,
                    "archive_bounds_invariant": True,
                    "eligible_city_window": True,
                    "qualifying_pass_count": int(binding["qualifying_pass_count"]),
                    "qualifying_pass_set_sha256": (
                        "0" * 64
                        if threshold == 10
                        else binding["qualifying_pass_set_sha256"]
                    ),
                }
            )
    result = selection_result(pd.DataFrame(rows), balance)
    assert result["primary_view_zenith_threshold_deg"] == 15
    assert not result["threshold_status"]["10"]["eligibility_pass_set_matches_balance"]
    assert result["threshold_status"]["15"]["eligibility_pass_set_matches_balance"]

    mismatched_count = pd.DataFrame(rows)
    mismatched_count.loc[
        mismatched_count["threshold_deg"].eq(15), "qualifying_pass_count"
    ] += 1
    result = selection_result(mismatched_count, balance)
    assert result["primary_view_zenith_threshold_deg"] == 20
    assert not result["threshold_status"]["15"]["eligibility_pass_set_matches_balance"]


def test_sparse_10_degree_threshold_does_not_block_15_degree_selection() -> None:
    passes = _qualifying_pass_detail()
    passes = passes.loc[
        ~(passes["threshold_deg"].eq(10) & passes["city"].eq("phoenix"))
    ].copy()
    balance, _ = build_balance_diagnostics(passes)
    assert balance["threshold_deg"].tolist() == [10, 15, 20, 25]
    ten = balance.loc[balance["threshold_deg"].eq(10)].iloc[0]
    assert ten["qualifying_pass_count"] == 18
    assert ten["unique_cities"] == 3
    assert not bool(ten["am_pm_support_diagnostics_complete"])
    balance["archive_bounds_invariant"] = True

    eligibility_rows = []
    for threshold in (10, 15, 20, 25):
        binding = balance.loc[balance["threshold_deg"].eq(threshold)].iloc[0]
        for city in ("atlanta", "denver_aurora", "minneapolis_st_paul", "phoenix"):
            eligibility_rows.append(
                {
                    "threshold_deg": threshold,
                    "city": city,
                    "window_id": "phoenix_apr_may" if city == "phoenix" else "jun_sep",
                    "phenology_auto_eligible": True,
                    "archive_bounds_invariant": True,
                    "eligible_city_window": True,
                    "qualifying_pass_count": int(binding["qualifying_pass_count"]),
                    "qualifying_pass_set_sha256": binding["qualifying_pass_set_sha256"],
                }
            )
    result = selection_result(pd.DataFrame(eligibility_rows), balance)
    assert result["primary_view_zenith_threshold_deg"] == 15
    assert not result["threshold_status"]["10"]["balance_membership_matches_candidates"]
    assert result["threshold_status"]["15"]["threshold_eligible"]


def test_explicit_threshold_ledger_emits_zero_pass_row() -> None:
    passes = _qualifying_pass_detail()
    passes = passes.loc[~passes["threshold_deg"].eq(10)].copy()
    balance, pairs = build_balance_diagnostics(passes)
    ten = balance.loc[balance["threshold_deg"].eq(10)].iloc[0]
    assert ten["qualifying_pass_count"] == 0
    assert ten["physical_passes"] == 0
    assert ten["city_window_membership"] == "[]"
    assert not bool(ten["histogram_diagnostics_complete"])
    assert not pairs["threshold_deg"].eq(10).any()


def test_archive_bounds_are_calculated_not_asserted() -> None:
    cities = ["atlanta", "minneapolis_st_paul", "denver_aurora", "phoenix"]
    observed_rows = []
    for threshold in (10, 15, 20, 25):
        for city in cities:
            for index in range(8):
                observed_rows.append(
                    {
                        "threshold_deg": threshold,
                        "physical_pass_id": f"{city}:{index}",
                        "city": city,
                        "window_id": "phoenix_apr_may" if city == "phoenix" else "jun_sep",
                        "year": 2018 + index % 4,
                        "time_stratum": "10-12" if index < 4 else "16-18",
                        "demand_level": "high",
                        "wetness_level": "wet" if index % 2 else "dry",
                    }
                )
    missing = pd.DataFrame(
        [
            {
                "city": "atlanta",
                "physical_pass_id": "unavailable:atlanta:2024",
                "window_id": "jun_sep",
                "year": 2024,
                "time_stratum": "10-12",
                "demand_level": "high",
                "wetness_level": "dry",
                "pass_recheck_classification": "RESOLVED_UNAVAILABLE",
            }
        ]
    )
    bounds = build_archive_bound_diagnostics(pd.DataFrame(observed_rows), missing)
    assert bounds["lower_physical_passes"].eq(32).all()
    assert bounds["upper_physical_passes"].eq(33).all()
    assert bounds["lower_city_share_cap_pass"].all()
    assert bounds["upper_city_share_cap_pass"].all()
    assert bounds["archive_count_conclusions_invariant"].all()
    assert bounds["archive_threshold_choice_invariant"].all()
    assert bounds["lower_first_count_eligible_threshold_deg"].eq(10).all()
    assert bounds["upper_first_count_eligible_threshold_deg"].eq(10).all()


def test_archive_bounds_detect_first_threshold_change() -> None:
    cities = ["atlanta", "minneapolis_st_paul", "denver_aurora", "phoenix"]
    rows = []
    for threshold in (10, 15, 20, 25):
        for city in cities:
            count = 5 if threshold == 10 and city == "atlanta" else 8
            for index in range(count):
                rows.append(
                    {
                        "threshold_deg": threshold,
                        "physical_pass_id": f"{city}:{index}",
                        "city": city,
                        "window_id": "phoenix_apr_may" if city == "phoenix" else "jun_sep",
                        "year": 2018 + index % 4,
                        "time_stratum": "10-12" if index < count / 2 else "16-18",
                        "demand_level": "high",
                        "wetness_level": "wet" if index % 2 else "dry",
                    }
                )
    missing = pd.DataFrame(
        [
            {
                "city": "atlanta",
                "physical_pass_id": "unavailable:atlanta:2024",
                "window_id": "jun_sep",
                "year": 2024,
                "time_stratum": "16-18",
                "demand_level": "high",
                "wetness_level": "wet",
                "pass_recheck_classification": "RESOLVED_UNAVAILABLE",
            },
            {
                "city": "atlanta",
                "physical_pass_id": "unavailable:atlanta:2025",
                "window_id": "jun_sep",
                "year": 2025,
                "time_stratum": "16-18",
                "demand_level": "high",
                "wetness_level": "wet",
                "pass_recheck_classification": "RESOLVED_UNAVAILABLE",
            },
        ]
    )
    bounds = build_archive_bound_diagnostics(pd.DataFrame(rows), missing)
    assert bounds["lower_first_count_eligible_threshold_deg"].eq(15).all()
    assert bounds["upper_first_count_eligible_threshold_deg"].eq(10).all()
    assert not bounds["archive_threshold_choice_invariant"].any()
    assert not bounds["archive_bounds_invariant"].any()


def test_archive_bounds_allow_missing_observed_window_and_upper_restoration() -> None:
    observed_rows = []
    for threshold in (10, 15, 20, 25):
        for city in ("atlanta", "denver_aurora", "minneapolis_st_paul"):
            for index in range(6):
                observed_rows.append(
                    {
                        "threshold_deg": threshold,
                        "physical_pass_id": f"{city}:{index}",
                        "city": city,
                        "window_id": "jun_sep",
                        "year": 2018 + index % 4,
                        "time_stratum": "10-12" if index < 3 else "16-18",
                        "demand_level": "high",
                        "wetness_level": "wet" if index % 2 else "dry",
                    }
                )
    unavailable_rows = []
    for index in range(6):
        unavailable_rows.append(
            {
                "physical_pass_id": f"phoenix:unavailable:{index}",
                "city": "phoenix",
                "window_id": "phoenix_apr_may",
                "year": 2018 + index % 4,
                "time_stratum": "10-12" if index < 3 else "16-18",
                "demand_level": "high",
                "wetness_level": "wet" if index % 2 else "dry",
                "pass_recheck_classification": "RESOLVED_UNAVAILABLE",
            }
        )
    bounds = build_archive_bound_diagnostics(
        pd.DataFrame(observed_rows), pd.DataFrame(unavailable_rows)
    )
    assert bounds["threshold_deg"].tolist() == [10, 15, 20, 25]
    assert bounds["lower_unique_cities"].eq(3).all()
    assert not bounds["lower_four_city_minimum_pass"].any()
    assert bounds["upper_unique_cities"].eq(4).all()
    assert bounds["upper_four_city_minimum_pass"].all()
    assert bounds["upper_required_count_support_pass"].all()
    assert bounds["upper_count_eligible"].all()
    assert not bounds["archive_bounds_invariant"].any()


def test_archive_bounds_reject_unresolved_duplicates_scope_and_non_nested_ids() -> None:
    cities = ["atlanta", "denver_aurora", "minneapolis_st_paul", "phoenix"]
    rows = []
    for threshold in (10, 15, 20, 25):
        for city in cities:
            for index in range(6):
                rows.append(
                    {
                        "threshold_deg": threshold,
                        "physical_pass_id": f"{city}:{index}",
                        "city": city,
                        "window_id": "phoenix_apr_may" if city == "phoenix" else "jun_sep",
                        "year": 2018 + index % 4,
                        "time_stratum": "10-12" if index < 3 else "16-18",
                        "demand_level": "high",
                        "wetness_level": "wet" if index % 2 else "dry",
                    }
                )
    observed = pd.DataFrame(rows)
    unavailable = pd.DataFrame(
        [
            {
                "physical_pass_id": "unavailable:1",
                "city": "atlanta",
                "window_id": "jun_sep",
                "year": 2024,
                "time_stratum": "10-12",
                "demand_level": "high",
                "wetness_level": "wet",
                "pass_recheck_classification": "UNRESOLVED",
            }
        ]
    )
    with _raises(ValueError, "not classified RESOLVED_UNAVAILABLE"):
        build_archive_bound_diagnostics(observed, unavailable)

    unavailable["pass_recheck_classification"] = "RESOLVED_UNAVAILABLE"
    duplicate = pd.concat([observed, observed.iloc[[0]]], ignore_index=True)
    with _raises(ValueError, "duplicate physical pass identities"):
        build_archive_bound_diagnostics(duplicate, unavailable)

    wrong_scope = unavailable.copy()
    wrong_scope[["city", "window_id"]] = ["los_angeles", "jun_sep"]
    with _raises(ValueError, "non-primary city-window"):
        build_archive_bound_diagnostics(observed, wrong_scope)

    non_nested = observed.loc[
        ~(
            observed["threshold_deg"].eq(15)
            & observed["physical_pass_id"].eq("atlanta:0")
        )
    ].copy()
    with _raises(ValueError, "not nested"):
        build_archive_bound_diagnostics(non_nested, unavailable)


if __name__ == "__main__":
    test_leaf_on_rule()
    test_prior_day_windows()
    test_selection_fails_closed()
    test_selection_requires_explicit_phenology_evidence()
    test_phenology_sensitivities_detect_reversal()
    test_phenology_sensitivities_distinguish_incomplete_qa0_coverage()
    test_phenology_requires_canopy_confirmation()
    test_azimuth_and_overlap_helpers()
    test_balance_diagnostics_and_successful_smallest_selector()
    test_selector_rejects_city_share_and_archive_bound_failures()
    test_selector_rejects_false_support_and_weather_flags()
    test_selector_rejects_balance_membership_mismatch()
    test_balance_rejects_substituted_membership_and_duplicate_inflation()
    test_balance_requires_all_weather_and_geometry_fields()
    test_balance_rejects_nonqualifying_duplicate_and_nonnested_rows()
    test_selector_rejects_string_booleans_and_substituted_membership()
    test_selector_requires_matching_certified_pass_set_hash_and_count()
    test_sparse_10_degree_threshold_does_not_block_15_degree_selection()
    test_explicit_threshold_ledger_emits_zero_pass_row()
    test_archive_bounds_are_calculated_not_asserted()
    test_archive_bounds_detect_first_threshold_change()
    test_archive_bounds_allow_missing_observed_window_and_upper_restoration()
    test_archive_bounds_reject_unresolved_duplicates_scope_and_non_nested_ids()
    print("PASS test_v2_hitl_gate3_sampling")
