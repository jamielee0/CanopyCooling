#!/usr/bin/env python3
"""Frozen interannual cloud-survival calibration for Task 1 Step 2."""

from __future__ import annotations

import numpy as np
import pandas as pd


REFERENCE_CITIES = ("phoenix", "miami")
TOLERANCE = 0.10
EXPANSION_STAGES = (
    ("primary_2023_validation_2022", (2023, 2022)),
    ("expanded_2021_through_2024", (2021, 2022, 2023, 2024)),
    ("expanded_2020_through_2025", (2020, 2021, 2022, 2023, 2024, 2025)),
    ("expanded_2018_through_2025", tuple(range(2018, 2026))),
)


def _month_key(year: int) -> str:
    return f"{year:04d}-07"


def evaluate_cloud_stability(
    month_summary: pd.DataFrame,
    *,
    tolerance: float = TOLERANCE,
    attempted_years: tuple[int, ...] | list[int] | set[int] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply D0019/D0026/D0030 without selecting favourable months.

    The original two-month stage compares July 2023 directly with July 2022.
    Expanded stages require every included July to lie within ``tolerance`` of
    the pixel-pooled leave-one-month-out estimate for its city.  Both cities
    must pass the same complete stage.
    """

    required = {
        "city",
        "month_key",
        "n_near_nadir_passes",
        "n_domain_pixels",
        "n_clear_pixels",
    }
    missing = sorted(required.difference(month_summary.columns))
    if missing:
        raise ValueError(f"cloud month summary lacks columns: {missing}")
    if not 0 < tolerance < 1:
        raise ValueError("tolerance must lie between zero and one")
    work = month_summary.copy()
    work["city"] = work["city"].astype(str)
    work["month_key"] = work["month_key"].astype(str)
    attempted = (
        {int(year) for year in attempted_years}
        if attempted_years is not None
        else {
            int(value[:4])
            for value in work["month_key"]
            if len(value) >= 7 and value[5:7] == "07"
        }
    )
    duplicate = work.duplicated(["city", "month_key"], keep=False)
    if duplicate.any():
        raise ValueError("cloud month summary must be unique by city/month_key")

    stage_rows: list[dict[str, object]] = []
    stage_status: list[tuple[str, tuple[int, ...], bool, bool, bool]] = []
    for stage_index, (stage, years) in enumerate(EXPANSION_STAGES):
        stage_attempted = set(years).issubset(attempted)
        city_passes: list[bool] = []
        city_complete: list[bool] = []
        for city in REFERENCE_CITIES:
            indexed = work.loc[work["city"].eq(city)].set_index("month_key")
            keys = [_month_key(year) for year in years]
            missing_or_zero = [key for key in keys if key not in indexed.index]
            complete = not missing_or_zero
            if complete:
                selected = indexed.loc[keys]
                missing_or_zero = [
                    key
                    for key, row in selected.iterrows()
                    if row["n_near_nadir_passes"] <= 0
                    or row["n_domain_pixels"] <= 0
                ]
                complete = bool(
                    not missing_or_zero
                )
            differences: dict[str, float] = {}
            if complete:
                selected = indexed.loc[keys]
                clear = selected["n_clear_pixels"].to_numpy(dtype=float)
                domain = selected["n_domain_pixels"].to_numpy(dtype=float)
                fractions = clear / domain
                if stage_index == 0:
                    differences = {
                        keys[0]: float(abs(fractions[0] - fractions[1])),
                        keys[1]: float(abs(fractions[1] - fractions[0])),
                    }
                else:
                    differences = {
                        key: float(
                            abs(
                                fractions[index]
                                - (clear.sum() - clear[index])
                                / (domain.sum() - domain[index])
                            )
                        )
                        for index, key in enumerate(keys)
                    }
                maximum = max(differences.values())
                passed = bool(maximum <= tolerance)
                pooled = float(clear.sum() / domain.sum())
            else:
                maximum = np.nan
                passed = False
                pooled = np.nan
            city_complete.append(complete)
            city_passes.append(passed)
            stage_rows.append(
                {
                    "stage_order": stage_index + 1,
                    "calibration_stage": stage,
                    "city": city,
                    "stage_attempted": stage_attempted,
                    "included_months": "|".join(keys),
                    "required_data_complete": complete,
                    "missing_or_zero_pass_months": (
                        "" if complete else "|".join(missing_or_zero)
                    ),
                    "maximum_absolute_difference_fraction": maximum,
                    "tolerance_fraction": tolerance,
                    "city_pass": passed,
                    "pixel_pooled_survival_fraction": pooled,
                    "month_leave_one_out_differences": "|".join(
                        f"{key}:{value:.12g}"
                        for key, value in differences.items()
                    ),
                }
            )
        stage_status.append(
            (stage, years, stage_attempted, all(city_complete), all(city_passes))
        )

    selected_stage: tuple[str, tuple[int, ...], bool, bool, bool] | None = None
    initial = stage_status[0]
    if initial[2] and initial[3] and initial[4]:
        selected_stage = initial
    else:
        selected_stage = next(
            (
                status
                for status in stage_status[1:]
                if status[2] and status[3] and status[4]
            ),
            None,
        )

    attempted_stages = [status for status in stage_status if status[2]]
    latest_attempted = attempted_stages[-1] if attempted_stages else None
    if selected_stage is not None:
        next_action = "extrapolation_allowed"
    elif latest_attempted is None or latest_attempted[0] == EXPANSION_STAGES[0][0]:
        next_action = "add_frozen_2021_and_2024_july_pair_for_both_cities"
    elif latest_attempted[0] == EXPANSION_STAGES[1][0]:
        next_action = "add_frozen_2020_and_2025_july_pair_for_both_cities"
    elif latest_attempted[0] == EXPANSION_STAGES[2][0]:
        next_action = "add_frozen_2019_and_2018_july_pair_for_both_cities"
    else:
        next_action = "stop_cloud_survival_unstable"

    chosen = selected_stage or latest_attempted or stage_status[0]
    stage, years, stage_attempted, data_complete, passed = chosen
    audit = pd.DataFrame(stage_rows)
    summaries: list[dict[str, object]] = []
    for city in REFERENCE_CITIES:
        keys = [_month_key(year) for year in years]
        indexed = work.loc[work["city"].eq(city)].set_index("month_key")
        chosen_audit = audit.loc[
            audit["calibration_stage"].eq(stage) & audit["city"].eq(city)
        ].iloc[0]
        if selected_stage is not None and data_complete and passed:
            selected = indexed.loc[keys]
            if stage == EXPANSION_STAGES[0][0]:
                survival = float(
                    selected.loc["2023-07", "n_clear_pixels"]
                    / selected.loc["2023-07", "n_domain_pixels"]
                )
                validation_fraction = float(
                    selected.loc["2022-07", "n_clear_pixels"]
                    / selected.loc["2022-07", "n_domain_pixels"]
                )
                method = (
                    "July 2023 pixel-pooled clear/domain fraction; July 2022 "
                    "independent validation"
                )
            else:
                survival = float(
                    selected["n_clear_pixels"].sum()
                    / selected["n_domain_pixels"].sum()
                )
                validation_fraction = survival
                method = (
                    "pixel-pooled clear/domain fraction across the first frozen "
                    "July expansion stage passing all leave-one-month-out checks"
                )
        else:
            survival = np.nan
            validation_fraction = np.nan
            method = "withheld because no complete frozen stage passed"
        summaries.append(
            {
                "reference_city": city,
                "measured_city": city,
                "primary_month": "2023-07",
                "validation_months": "|".join(key for key in keys if key != "2023-07"),
                "included_months": "|".join(keys),
                "calibration_stage": stage,
                "cloud_survival_fraction": survival,
                "validation_fraction": validation_fraction,
                "absolute_difference": float(
                    chosen_audit["maximum_absolute_difference_fraction"]
                ),
                "absolute_difference_fraction": float(
                    chosen_audit["maximum_absolute_difference_fraction"]
                ),
                "tolerance": tolerance,
                "tolerance_fraction": tolerance,
                "representative": bool(selected_stage is not None),
                "representative_within_tolerance": bool(selected_stage is not None),
                "estimation_method": method,
                "next_action": next_action,
            }
        )
    return pd.DataFrame(summaries), audit


__all__ = [
    "EXPANSION_STAGES",
    "REFERENCE_CITIES",
    "TOLERANCE",
    "evaluate_cloud_stability",
]
