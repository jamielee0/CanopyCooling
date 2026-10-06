#!/usr/bin/env python3
"""Network-free synthetic tests for Gate-2 hydroclimatic support."""

from __future__ import annotations

import numpy as np
import pandas as pd

from urban_cooling_v2.hitl_gate2_hydroclimate import (
    MEANINGFUL_RAIN_MM,
    audit_exclusive_windows,
    compute_daily_predictors,
)


def _fixture() -> pd.DataFrame:
    dates = pd.date_range("2018-04-01", "2018-09-30", freq="D")
    precipitation = np.zeros(len(dates), dtype=float)
    precipitation[dates.get_loc("2018-05-31")] = MEANINGFUL_RAIN_MM
    precipitation[dates.get_loc("2018-06-15")] = 7.0
    return pd.DataFrame(
        {
            "city": "test_city",
            "date": dates,
            "pr_mm": precipitation,
            "eto_mm": 2.0,
            "vpd_kpa": np.linspace(1.0, 3.0, len(dates)),
        }
    )


def test_windows_exclude_observation_day() -> None:
    source = _fixture()
    result = compute_daily_predictors(source)
    june_1 = result.loc[result["date"].eq(pd.Timestamp("2018-06-01"))].iloc[0]
    assert june_1["antecedent_precipitation_30d_mm"] == 5.0
    assert june_1["days_since_meaningful_rain_30d"] == 1
    june_15 = result.loc[result["date"].eq(pd.Timestamp("2018-06-15"))].iloc[0]
    assert june_15["antecedent_precipitation_30d_mm"] == 5.0
    assert june_15["days_since_meaningful_rain_30d"] == 15
    june_16 = result.loc[result["date"].eq(pd.Timestamp("2018-06-16"))].iloc[0]
    assert june_16["antecedent_precipitation_30d_mm"] == 12.0
    assert june_16["days_since_meaningful_rain_30d"] == 1


def test_no_event_is_right_censored_at_window_plus_one() -> None:
    source = _fixture()
    source["pr_mm"] = 0.0
    result = compute_daily_predictors(source)
    row = result.loc[result["date"].eq(pd.Timestamp("2018-06-20"))].iloc[0]
    assert row["days_since_meaningful_rain_30d"] == 31
    assert bool(row["meaningful_rain_right_censored_30d"])
    assert row["days_since_meaningful_rain_60d"] == 61
    assert bool(row["meaningful_rain_right_censored_60d"])


def test_days_since_wetness_orientation_is_reversed() -> None:
    result = compute_daily_predictors(_fixture())
    recent = result.loc[result["days_since_meaningful_rain_30d"].eq(1)]
    old = result.loc[result["days_since_meaningful_rain_30d"].ge(20)]
    assert recent["days_since_meaningful_rain_30d_wetness_percentile"].median() > old[
        "days_since_meaningful_rain_30d_wetness_percentile"
    ].median()


def test_explicit_window_audit_passes() -> None:
    source = _fixture()
    result = compute_daily_predictors(source)
    audit = audit_exclusive_windows(source, result)
    checked = audit[
        [
            "incomplete_prior_day_windows",
            "precipitation_sum_mismatches",
            "climatic_balance_sum_mismatches",
            "days_since_event_mismatches",
            "observation_day_exclusion_violations",
        ]
    ]
    assert checked.eq(0).all().all()


if __name__ == "__main__":
    test_windows_exclude_observation_day()
    test_no_event_is_right_censored_at_window_plus_one()
    test_days_since_wetness_orientation_is_reversed()
    test_explicit_window_audit_passes()
    print("Gate-2 hydroclimate tests passed (4 tests).")
