#!/usr/bin/env python3
"""Guide Step 1: screen the joint weather-condition support before downloads.

The module is deliberately independent of Google Earth Engine.  Its input is a
city-day table exported by any reproducible adapter, with these canonical fields:

``city, date, pr_mm, eto_mm, vpd_kpa, tmmx_k[, clear_sky]``.

Raw antecedent balance is precipitation minus reference evapotranspiration.  A
larger balance is wetter, so ``antecedent_dryness_*_pct`` is explicitly the
*reverse* empirical percentile.  This makes 1 = driest and puts the scientifically
useful combinations in the off-diagonal cells requested by the guide:

* high demand after wet conditions: demand high, dryness low;
* low demand after dry conditions: demand low, dryness high.

All random procedures accept a seed.  Correlation uncertainty resamples whole
summer-years; it never treats daily observations as independent bootstrap units.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
from statistics import NormalDist
from typing import Iterable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REQUIRED_COLUMNS: tuple[str, ...] = (
    "city",
    "date",
    "pr_mm",
    "eto_mm",
    "vpd_kpa",
    "tmmx_k",
)
WEATHER_COLUMNS: tuple[str, ...] = ("pr_mm", "eto_mm", "vpd_kpa", "tmmx_k")
TERCILES: tuple[str, ...] = ("low", "middle", "high")
OFF_DIAGONAL_CORNERS: frozenset[tuple[str, str]] = frozenset(
    {("high", "low"), ("low", "high")}
)


@dataclass(frozen=True)
class GateThresholds:
    """Predeclared operational reading of the guide's qualitative gate.

    ``min_combined_corner_share`` applies to the sum of the two off-diagonal
    corners.  ``min_each_corner_count`` prevents a result driven by only one corner.
    These are screening thresholds, not inferential cut-offs.
    """

    min_combined_corner_share: float = 0.10
    min_each_corner_count: int = 5
    max_abs_spearman: float = 0.80
    min_cities_for_within_city: int = 3
    essentially_empty_share: float = 0.02
    nearly_identical_abs_spearman: float = 0.90


def _normalise_daily_input(daily: pd.DataFrame) -> pd.DataFrame:
    """Validate names/types/keys and return a sorted defensive copy."""

    missing = [name for name in REQUIRED_COLUMNS if name not in daily.columns]
    if missing:
        raise ValueError(f"missing required city-day columns: {missing}")
    out = daily.copy()
    out["city"] = out["city"].astype("string").str.strip()
    if out["city"].isna().any() or (out["city"] == "").any():
        raise ValueError("city must be non-empty for every row")
    parsed = pd.to_datetime(out["date"], errors="coerce")
    if parsed.isna().any():
        bad = out.loc[parsed.isna(), "date"].head(3).tolist()
        raise ValueError(f"date contains unparsable values, for example {bad}")
    # Weather is daily and timezone-free; a time component would make rolling
    # calendar windows ambiguous, so normalise explicitly.
    if getattr(parsed.dt, "tz", None) is not None:
        parsed = parsed.dt.tz_convert(None)
    out["date"] = parsed.dt.normalize()
    for name in WEATHER_COLUMNS:
        out[name] = pd.to_numeric(out[name], errors="coerce")
    duplicated = out.duplicated(["city", "date"], keep=False)
    if duplicated.any():
        keys = out.loc[duplicated, ["city", "date"]].head(3).to_dict("records")
        raise ValueError(f"city-date keys must be unique; duplicates include {keys}")
    if "clear_sky" in out:
        # Preserve unknown as False for observable-day counts; callers can audit the
        # original column before this transform if missingness is scientifically useful.
        out["clear_sky"] = out["clear_sky"].fillna(False).astype(bool)
    else:
        out["clear_sky"] = False
    return out.sort_values(["city", "date"], kind="mergesort").reset_index(drop=True)


def add_antecedent_balances(
    daily: pd.DataFrame,
    *,
    windows: Sequence[int] = (30, 60),
) -> pd.DataFrame:
    """Add calendar-day sums of ``pr_mm - eto_mm`` ending the day before.

    Each city is expanded to a daily calendar before rolling.  A missing day thus
    invalidates every window that crosses it instead of silently turning a 30-day
    window into the previous 30 *observations*.  Rows introduced only for this check
    are removed before return.
    """

    base = _normalise_daily_input(daily)
    clean_windows = tuple(int(window) for window in windows)
    if not clean_windows or any(window <= 0 for window in clean_windows):
        raise ValueError("windows must contain positive integers")

    pieces: list[pd.DataFrame] = []
    for city, group in base.groupby("city", sort=False, observed=True):
        group = group.set_index("date")
        calendar = pd.date_range(group.index.min(), group.index.max(), freq="D")
        expanded = group.reindex(calendar)
        expanded.index.name = "date"
        expanded["city"] = str(city)
        expanded["_source_row"] = expanded.index.isin(group.index)
        daily_balance = expanded["pr_mm"] - expanded["eto_mm"]
        expanded["daily_balance_mm"] = daily_balance
        for window in clean_windows:
            # shift(1) is the no-lookahead guard: today's weather never enters
            # today's antecedent value.
            expanded[f"balance_{window}d_mm"] = (
                daily_balance.shift(1).rolling(window, min_periods=window).sum()
            )
        pieces.append(expanded.loc[expanded["_source_row"]].reset_index())

    result = pd.concat(pieces, ignore_index=True)
    return result.drop(columns=["_source_row"]).sort_values(
        ["city", "date"], kind="mergesort"
    ).reset_index(drop=True)


def summer_mask(
    dates: Iterable[object],
    *,
    start_year: int = 2018,
    end_year: int = 2025,
) -> np.ndarray:
    """Return June 1--September 30 dates within the inclusive year range."""

    if int(start_year) > int(end_year):
        raise ValueError("start_year must not exceed end_year")
    dt = pd.DatetimeIndex(pd.to_datetime(list(dates)))
    month_day = dt.month * 100 + dt.day
    return np.asarray(
        (dt.year >= int(start_year))
        & (dt.year <= int(end_year))
        & (month_day >= 601)
        & (month_day <= 930),
        dtype=bool,
    )


def empirical_percentile(values: pd.Series) -> pd.Series:
    """Mid-rank empirical percentile on [0, 1], retaining missing values.

    With no ties the minimum and maximum are exactly 0 and 1.  Ties share the
    average rank.  A singleton receives 0.5 because neither endpoint is meaningful.
    """

    numeric = pd.to_numeric(values, errors="coerce")
    result = pd.Series(np.nan, index=values.index, dtype="float64")
    valid = numeric.notna()
    count = int(valid.sum())
    if count == 0:
        return result
    if count == 1:
        result.loc[valid] = 0.5
        return result
    ranks = numeric.loc[valid].rank(method="average")
    result.loc[valid] = (ranks - 1.0) / (count - 1.0)
    return result


def _tercile(values: pd.Series) -> pd.Categorical:
    """Classify percentiles with left-closed [0, 1/3, 2/3, 1] bins."""

    numeric = pd.to_numeric(values, errors="coerce")
    return pd.cut(
        numeric,
        bins=[-np.inf, 1.0 / 3.0, 2.0 / 3.0, np.inf],
        labels=list(TERCILES),
        right=False,
        ordered=True,
    )


def prepare_condition_axes(
    daily: pd.DataFrame,
    *,
    start_year: int = 2018,
    end_year: int = 2025,
) -> pd.DataFrame:
    """Build summer demand and 30/60-day antecedent-dryness axes.

    The returned table keeps a row even when an antecedent window is unavailable;
    its balance/percentile/cell fields remain missing so support loss is visible.
    """

    result = add_antecedent_balances(daily, windows=(30, 60))
    result = result.loc[
        summer_mask(result["date"], start_year=start_year, end_year=end_year)
    ].copy()
    result["summer_year"] = result["date"].dt.year.astype(int)

    result["demand_pct"] = result.groupby("city", sort=False, observed=True)[
        "vpd_kpa"
    ].transform(empirical_percentile)
    for window in (30, 60):
        balance = f"balance_{window}d_mm"
        wetness = f"antecedent_wetness_{window}d_pct"
        dryness = f"antecedent_dryness_{window}d_pct"
        result[wetness] = result.groupby("city", sort=False, observed=True)[
            balance
        ].transform(empirical_percentile)
        result[dryness] = 1.0 - result[wetness]
        result[f"demand_tercile_{window}d"] = _tercile(result["demand_pct"])
        result[f"dryness_tercile_{window}d"] = _tercile(result[dryness])
        result[f"cell_{window}d"] = (
            result[f"demand_tercile_{window}d"].astype("string")
            + "|"
            + result[f"dryness_tercile_{window}d"].astype("string")
        )
        invalid = result[["demand_pct", dryness]].isna().any(axis=1)
        result.loc[invalid, f"cell_{window}d"] = pd.NA
        result[f"off_diagonal_corner_{window}d"] = [
            (str(demand), str(dryness_level)) in OFF_DIAGONAL_CORNERS
            if not (pd.isna(demand) or pd.isna(dryness_level))
            else False
            for demand, dryness_level in zip(
                result[f"demand_tercile_{window}d"],
                result[f"dryness_tercile_{window}d"],
            )
        ]
    return result.reset_index(drop=True)


def spearman_correlation(x: Iterable[float], y: Iterable[float]) -> float:
    """Spearman's rho without a SciPy dependency (average ranks for ties)."""

    frame = pd.DataFrame({"x": list(x), "y": list(y)}).dropna()
    if len(frame) < 3:
        return float("nan")
    rx = frame["x"].rank(method="average").to_numpy(dtype=float)
    ry = frame["y"].rank(method="average").to_numpy(dtype=float)
    if np.ptp(rx) == 0.0 or np.ptp(ry) == 0.0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def summer_block_spearman(
    frame: pd.DataFrame,
    *,
    x: str = "demand_pct",
    y: str = "antecedent_dryness_30d_pct",
    year: str = "summer_year",
    n_boot: int = 2_000,
    seed: int = 20260801,
    ci: float = 0.95,
) -> dict[str, float | int | str]:
    """Estimate Spearman rho and a whole-summer percentile bootstrap CI."""

    if n_boot <= 0:
        raise ValueError("n_boot must be positive")
    needed = [x, y, year]
    missing = [name for name in needed if name not in frame]
    if missing:
        raise ValueError(f"missing columns for block bootstrap: {missing}")
    clean = frame[needed].dropna().copy()
    observed = spearman_correlation(clean[x], clean[y])
    years = np.asarray(sorted(clean[year].unique()))
    if len(years) < 2:
        return {
            "spearman": observed,
            "ci_low": float("nan"),
            "ci_high": float("nan"),
            "n_boot": int(n_boot),
            "n_valid_boot": 0,
            "n_summers": int(len(years)),
            "bootstrap_unit": "whole_summer",
            "status": "insufficient_summers",
        }
    blocks = {
        value: clean.loc[clean[year] == value, [x, y]].reset_index(drop=True)
        for value in years
    }
    rng = np.random.default_rng(seed)
    draws: list[float] = []
    for _ in range(int(n_boot)):
        sampled = rng.choice(years, size=len(years), replace=True)
        boot = pd.concat([blocks[value] for value in sampled], ignore_index=True)
        rho = spearman_correlation(boot[x], boot[y])
        if np.isfinite(rho):
            draws.append(rho)
    if not draws:
        low = high = float("nan")
        status = "no_valid_resamples"
    else:
        alpha = (1.0 - float(ci)) / 2.0
        low, high = np.quantile(draws, [alpha, 1.0 - alpha]).tolist()
        status = "ok"
    return {
        "spearman": observed,
        "ci_low": float(low),
        "ci_high": float(high),
        "n_boot": int(n_boot),
        "n_valid_boot": int(len(draws)),
        "n_summers": int(len(years)),
        "bootstrap_unit": "whole_summer",
        "status": status,
    }


def _is_corner(demand: pd.Series, dryness: pd.Series) -> np.ndarray:
    d = _tercile(demand).astype("string")
    a = _tercile(dryness).astype("string")
    return np.asarray(
        [
            (str(dx), str(ay)) in OFF_DIAGONAL_CORNERS
            if not (pd.isna(dx) or pd.isna(ay))
            else False
            for dx, ay in zip(d, a)
        ],
        dtype=bool,
    )


def permutation_corner_test(
    frame: pd.DataFrame,
    *,
    demand: str = "demand_pct",
    dryness: str = "antecedent_dryness_30d_pct",
    n_permutations: int = 2_000,
    seed: int = 20260801,
) -> dict[str, float | int]:
    """Shuffle antecedent dryness relative to demand and test corner occupancy."""

    if n_permutations <= 0:
        raise ValueError("n_permutations must be positive")
    clean = frame[[demand, dryness]].dropna()
    n = len(clean)
    if n == 0:
        return {
            "n": 0,
            "observed_count": 0,
            "observed_share": float("nan"),
            "permutation_mean_share": float("nan"),
            "permutation_ci_low": float("nan"),
            "permutation_ci_high": float("nan"),
            "observed_percentile": float("nan"),
            "two_sided_p": float("nan"),
            "n_permutations": int(n_permutations),
        }
    x = clean[demand].reset_index(drop=True)
    y = clean[dryness].to_numpy(dtype=float)
    observed_count = int(_is_corner(x, pd.Series(y)).sum())
    observed_share = observed_count / n
    rng = np.random.default_rng(seed)
    shares = np.empty(int(n_permutations), dtype=float)
    for index in range(int(n_permutations)):
        shares[index] = _is_corner(x, pd.Series(rng.permutation(y))).mean()
    lower_tail = (np.count_nonzero(shares <= observed_share) + 1.0) / (
        len(shares) + 1.0
    )
    upper_tail = (np.count_nonzero(shares >= observed_share) + 1.0) / (
        len(shares) + 1.0
    )
    return {
        "n": int(n),
        "observed_count": observed_count,
        "observed_share": float(observed_share),
        "permutation_mean_share": float(np.mean(shares)),
        "permutation_ci_low": float(np.quantile(shares, 0.025)),
        "permutation_ci_high": float(np.quantile(shares, 0.975)),
        "observed_percentile": float(lower_tail),
        "two_sided_p": float(min(1.0, 2.0 * min(lower_tail, upper_tail))),
        "n_permutations": int(n_permutations),
    }


def wilson_interval(successes: int, total: int, *, ci: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""

    if total < 0 or successes < 0 or successes > total:
        raise ValueError("require 0 <= successes <= total")
    if total == 0:
        return float("nan"), float("nan")
    z = NormalDist().inv_cdf(0.5 + float(ci) / 2.0)
    p = successes / total
    denominator = 1.0 + z * z / total
    centre = (p + z * z / (2.0 * total)) / denominator
    half = (
        z
        * np.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total * total))
        / denominator
    )
    return float(max(0.0, centre - half)), float(min(1.0, centre + half))


def cell_count_table(
    axes: pd.DataFrame,
    *,
    window: int = 30,
    n_boot: int = 2_000,
    seed: int = 20260801,
) -> pd.DataFrame:
    """Build canonical long-form T1.1 for all and clear-sky summer days."""

    demand_cell = f"demand_tercile_{int(window)}d"
    dryness_cell = f"dryness_tercile_{int(window)}d"
    dryness_pct = f"antecedent_dryness_{int(window)}d_pct"
    required = ["city", "clear_sky", "summer_year", "demand_pct", demand_cell, dryness_cell, dryness_pct]
    missing = [name for name in required if name not in axes]
    if missing:
        raise ValueError(f"axes table is missing columns: {missing}")
    rows: list[dict[str, object]] = []
    for city_index, (city, city_frame) in enumerate(
        axes.groupby("city", sort=True, observed=True)
    ):
        for subset_name, subset in (
            ("all_days", city_frame),
            ("clear_sky", city_frame.loc[city_frame["clear_sky"]]),
        ):
            valid = subset.dropna(subset=["demand_pct", dryness_pct])
            boot = summer_block_spearman(
                valid,
                y=dryness_pct,
                n_boot=n_boot,
                seed=seed + city_index * 101 + (1 if subset_name == "clear_sky" else 0),
            )
            total = len(valid)
            for demand_level in TERCILES:
                for dryness_level in TERCILES:
                    count = int(
                        (
                            (valid[demand_cell].astype("string") == demand_level)
                            & (valid[dryness_cell].astype("string") == dryness_level)
                        ).sum()
                    )
                    corner = (demand_level, dryness_level) in OFF_DIAGONAL_CORNERS
                    low, high = wilson_interval(count, total)
                    rows.append(
                        {
                            "city": str(city),
                            "subset": subset_name,
                            "window_days": int(window),
                            "demand_tercile": demand_level,
                            "dryness_tercile": dryness_level,
                            "cell": f"{demand_level}|{dryness_level}",
                            "is_off_diagonal_corner": corner,
                            "count": count,
                            "total_valid_days": int(total),
                            "proportion": count / total if total else np.nan,
                            "proportion_ci_low": low,
                            "proportion_ci_high": high,
                            "spearman": boot["spearman"],
                            "spearman_ci_low": boot["ci_low"],
                            "spearman_ci_high": boot["ci_high"],
                            "n_summers": boot["n_summers"],
                            "bootstrap_unit": boot["bootstrap_unit"],
                            "bootstrap_status": boot["status"],
                        }
                    )
    return pd.DataFrame(rows)


def domain_record_table(
    axes: pd.DataFrame,
    domain_records: pd.DataFrame,
) -> pd.DataFrame:
    """Build T1.2 from frozen domain metadata and observed-day counts."""

    required = {"city", "domain_source", "area_km2"}
    missing = sorted(required.difference(domain_records.columns))
    if missing:
        raise ValueError(f"domain_records missing columns: {missing}")
    records = domain_records.copy()
    if records["city"].duplicated().any():
        raise ValueError("domain_records must contain one row per city")
    summaries: list[dict[str, object]] = []
    for city, group in axes.groupby("city", sort=True, observed=True):
        n_summer = len(group)
        n_clear = int(group["clear_sky"].sum())
        summaries.append(
            {
                "city": str(city),
                "n_summer_days": int(n_summer),
                "n_clear_sky_days": n_clear,
                "percent_clear": 100.0 * n_clear / n_summer if n_summer else np.nan,
            }
        )
    result = records.merge(pd.DataFrame(summaries), on="city", how="outer", validate="one_to_one")
    if result[["domain_source", "area_km2"]].isna().any().any():
        missing_cities = result.loc[
            result[["domain_source", "area_km2"]].isna().any(axis=1), "city"
        ].tolist()
        raise ValueError(f"missing frozen domain metadata for cities: {missing_cities}")
    return result.sort_values("city").reset_index(drop=True)


def unit_diagnostics(daily: pd.DataFrame) -> pd.DataFrame:
    """Min/median/max and conservative unit plausibility checks by city/band."""

    base = _normalise_daily_input(daily)
    expectations: Mapping[str, tuple[str, float, float]] = {
        "pr_mm": ("mm day-1", 0.0, 500.0),
        "eto_mm": ("mm day-1", 0.0, 25.0),
        "vpd_kpa": ("kPa", 0.0, 15.0),
        "tmmx_k": ("K", 200.0, 360.0),
    }
    rows: list[dict[str, object]] = []
    for city, group in base.groupby("city", sort=True, observed=True):
        for band, (units, lower, upper) in expectations.items():
            values = group[band].dropna()
            minimum = float(values.min()) if len(values) else np.nan
            median = float(values.median()) if len(values) else np.nan
            maximum = float(values.max()) if len(values) else np.nan
            plausible = bool(
                len(values)
                and minimum >= lower
                and maximum <= upper
                and np.isfinite([minimum, median, maximum]).all()
            )
            phoenix_reference = pd.NA
            if band == "vpd_kpa" and "phoenix" in str(city).casefold():
                phoenix_reference = bool(2.0 <= median <= 6.0)
            rows.append(
                {
                    "city": str(city),
                    "band": band,
                    "expected_units": units,
                    "min": minimum,
                    "median": median,
                    "max": maximum,
                    "plausible_range_pass": plausible,
                    "phoenix_summer_2_to_6_kpa_reference_pass": phoenix_reference,
                }
            )
    return pd.DataFrame(rows)


def phoenix_water_balance_diagnostic(axes: pd.DataFrame) -> pd.DataFrame:
    """Check negative June balance and a July monsoon rise for Phoenix summers."""

    phoenix = axes.loc[axes["city"].astype(str).str.casefold().str.contains("phoenix")].copy()
    if phoenix.empty:
        return pd.DataFrame(
            columns=[
                "city",
                "summer_year",
                "june_median_balance_30d_mm",
                "july_median_balance_30d_mm",
                "june_negative",
                "july_rises_from_june",
                "pass",
            ]
        )
    rows: list[dict[str, object]] = []
    for (city, year), group in phoenix.groupby(["city", "summer_year"], sort=True, observed=True):
        june = group.loc[group["date"].dt.month == 6, "balance_30d_mm"].median()
        july = group.loc[group["date"].dt.month == 7, "balance_30d_mm"].median()
        june_negative = bool(np.isfinite(june) and june < 0.0)
        july_rise = bool(np.isfinite(june) and np.isfinite(july) and july > june)
        rows.append(
            {
                "city": str(city),
                "summer_year": int(year),
                "june_median_balance_30d_mm": float(june),
                "july_median_balance_30d_mm": float(july),
                "june_negative": june_negative,
                "july_rises_from_june": july_rise,
                "pass": june_negative and july_rise,
            }
        )
    return pd.DataFrame(rows)


def percentile_uniformity_diagnostic(axes: pd.DataFrame) -> pd.DataFrame:
    """Report an empirical-CDF distance from Uniform(0,1) for each city/axis."""

    variables = (
        "demand_pct",
        "antecedent_dryness_30d_pct",
        "antecedent_dryness_60d_pct",
    )
    rows: list[dict[str, object]] = []
    for city, group in axes.groupby("city", sort=True, observed=True):
        for variable in variables:
            values = np.sort(group[variable].dropna().to_numpy(dtype=float))
            if not len(values):
                distance = np.nan
                passes = False
                unique_share = np.nan
            else:
                empirical = np.arange(1, len(values) + 1, dtype=float) / len(values)
                distance = float(
                    max(
                        np.max(np.abs(empirical - values)),
                        np.max(np.abs((empirical - 1.0 / len(values)) - values)),
                    )
                )
                unique_share = float(len(np.unique(values)) / len(values))
                # Ties can legitimately reduce apparent uniformity.  A distance over
                # 0.10 is large enough to flag wrong grouping without false precision.
                passes = bool(distance <= max(0.10, 2.0 / len(values)))
            rows.append(
                {
                    "city": str(city),
                    "variable": variable,
                    "n": int(len(values)),
                    "unique_share": unique_share,
                    "uniform_ecdf_distance": distance,
                    "pass": passes,
                }
            )
    return pd.DataFrame(rows)


def permutation_table(
    axes: pd.DataFrame,
    *,
    windows: Sequence[int] = (30, 60),
    n_permutations: int = 2_000,
    seed: int = 20260801,
) -> pd.DataFrame:
    """Run the within-city independence diagnostic for all/clear subsets."""

    rows: list[dict[str, object]] = []
    index = 0
    for city, city_frame in axes.groupby("city", sort=True, observed=True):
        for window in windows:
            for subset_name, subset in (
                ("all_days", city_frame),
                ("clear_sky", city_frame.loc[city_frame["clear_sky"]]),
            ):
                result = permutation_corner_test(
                    subset,
                    dryness=f"antecedent_dryness_{int(window)}d_pct",
                    n_permutations=n_permutations,
                    seed=seed + index * 101,
                )
                rows.append(
                    {
                        "city": str(city),
                        "window_days": int(window),
                        "subset": subset_name,
                        **result,
                    }
                )
                index += 1
    return pd.DataFrame(rows)


def window_agreement_table(
    axes: pd.DataFrame,
    *,
    combined_share_threshold: float = 0.10,
) -> pd.DataFrame:
    """Compare 30- and 60-day corner support using the same qualitative threshold."""

    rows: list[dict[str, object]] = []
    for city, group in axes.groupby("city", sort=True, observed=True):
        subset = group.loc[group["clear_sky"]]
        row: dict[str, object] = {"city": str(city), "subset": "clear_sky"}
        statuses: list[bool] = []
        for window in (30, 60):
            valid = subset.dropna(
                subset=["demand_pct", f"antecedent_dryness_{window}d_pct"]
            )
            count = int(valid[f"off_diagonal_corner_{window}d"].sum())
            share = count / len(valid) if len(valid) else np.nan
            row[f"corner_count_{window}d"] = count
            row[f"valid_days_{window}d"] = int(len(valid))
            row[f"corner_share_{window}d"] = share
            statuses.append(bool(np.isfinite(share) and share >= combined_share_threshold))
        row["qualitative_same"] = statuses[0] == statuses[1]
        rows.append(row)
    return pd.DataFrame(rows)


def evaluate_gate(
    axes: pd.DataFrame,
    *,
    thresholds: GateThresholds = GateThresholds(),
) -> dict[str, object]:
    """Apply a transparent operational version of the Guide Step-1 decision gate."""

    city_results: list[dict[str, object]] = []
    for city, group in axes.groupby("city", sort=True, observed=True):
        clear = group.loc[group["clear_sky"]].dropna(
            subset=["demand_pct", "antecedent_dryness_30d_pct"]
        )
        n = len(clear)
        hi_wet = int(
            (
                (clear["demand_tercile_30d"].astype("string") == "high")
                & (clear["dryness_tercile_30d"].astype("string") == "low")
            ).sum()
        )
        lo_dry = int(
            (
                (clear["demand_tercile_30d"].astype("string") == "low")
                & (clear["dryness_tercile_30d"].astype("string") == "high")
            ).sum()
        )
        share = (hi_wet + lo_dry) / n if n else np.nan
        rho = spearman_correlation(
            clear["demand_pct"], clear["antecedent_dryness_30d_pct"]
        )
        reasonable = bool(
            n
            and share >= thresholds.min_combined_corner_share
            and min(hi_wet, lo_dry) >= thresholds.min_each_corner_count
            and np.isfinite(rho)
            and abs(rho) < thresholds.max_abs_spearman
        )
        city_results.append(
            {
                "city": str(city),
                "n_clear_valid": int(n),
                "high_demand_wet_count": hi_wet,
                "low_demand_dry_count": lo_dry,
                "combined_corner_share": float(share) if np.isfinite(share) else np.nan,
                "spearman": rho,
                "within_city_support": reasonable,
            }
        )

    available = [row for row in city_results if int(row["n_clear_valid"]) > 0]
    supported = sum(bool(row["within_city_support"]) for row in available)
    if not available:
        decision = "insufficient_data"
        recommendation = "Do not pass the gate until a clear-sky indicator is supplied."
    elif supported >= thresholds.min_cities_for_within_city:
        decision = "within_city_separation_may_be_possible"
        recommendation = "Proceed to Steps 2 and 3; retain the within-city interaction as provisional."
    else:
        essentially_empty = all(
            float(row["combined_corner_share"]) < thresholds.essentially_empty_share
            for row in available
            if np.isfinite(float(row["combined_corner_share"]))
        )
        nearly_identical = all(
            np.isfinite(float(row["spearman"]))
            and abs(float(row["spearman"])) >= thresholds.nearly_identical_abs_spearman
            for row in available
        )
        if essentially_empty and nearly_identical:
            decision = "interaction_not_estimable"
            recommendation = "Drop the interaction; retain the time-of-day study and report sampling limits."
        else:
            decision = "cross_city_separation_only"
            recommendation = (
                "Proceed only as a cross-city comparison, state the city-confounding limitation, "
                "and consider adding a sixth city."
            )
    return {
        "decision": decision,
        "recommendation": recommendation,
        "n_cities_with_clear_data": len(available),
        "n_cities_with_within_city_support": int(supported),
        "thresholds": thresholds.__dict__.copy(),
        "cities": city_results,
        "provisional_only": True,
    }


def _joint_counts(frame: pd.DataFrame, *, window: int) -> dict[tuple[str, str], int]:
    valid = frame.dropna(
        subset=["demand_pct", f"antecedent_dryness_{window}d_pct"]
    )
    result: dict[tuple[str, str], int] = {}
    demand = valid[f"demand_tercile_{window}d"].astype("string")
    dryness = valid[f"dryness_tercile_{window}d"].astype("string")
    for d_level in TERCILES:
        for a_level in TERCILES:
            result[(d_level, a_level)] = int(((demand == d_level) & (dryness == a_level)).sum())
    return result


def plot_joint_panels(
    axes: pd.DataFrame,
    path: str | Path,
    *,
    window: int = 30,
    clear_overlay: bool = False,
) -> Path:
    """Write F1.1/F1.2/F1.4-style panels."""

    cities = sorted(axes["city"].dropna().astype(str).unique())
    if not cities:
        raise ValueError("cannot plot an empty axes table")
    ncols = min(3, len(cities))
    nrows = ceil(len(cities) / ncols)
    fig, panels = plt.subplots(nrows, ncols, figsize=(5.0 * ncols, 4.2 * nrows), squeeze=False)
    y_name = f"antecedent_dryness_{window}d_pct"
    for index, city in enumerate(cities):
        ax = panels.flat[index]
        group = axes.loc[axes["city"].astype(str) == city].dropna(subset=["demand_pct", y_name])
        ax.axvspan(2 / 3, 1, ymin=0, ymax=1 / 3, color="#f4c95d", alpha=0.22, zorder=0)
        ax.axvspan(0, 1 / 3, ymin=2 / 3, ymax=1, color="#f4c95d", alpha=0.22, zorder=0)
        if clear_overlay:
            ax.scatter(group["demand_pct"], group[y_name], s=10, color="#9aa0a6", alpha=0.32, label="all")
            clear = group.loc[group["clear_sky"]]
            ax.scatter(clear["demand_pct"], clear[y_name], s=14, color="#1769aa", alpha=0.70, label="clear sky")
            all_counts = _joint_counts(group, window=window)
            clear_counts = _joint_counts(clear, window=window)
            for d_level, a_level in OFF_DIAGONAL_CORNERS:
                x = {"low": 1 / 6, "middle": 1 / 2, "high": 5 / 6}[d_level]
                y = {"low": 1 / 6, "middle": 1 / 2, "high": 5 / 6}[a_level]
                ax.text(x, y, f"{all_counts[(d_level, a_level)]}/{clear_counts[(d_level, a_level)]}", ha="center", va="center", fontsize=9, fontweight="bold")
        else:
            ax.scatter(group["demand_pct"], group[y_name], s=12, color="#1769aa", alpha=0.52)
            counts = _joint_counts(group, window=window)
            for d_index, d_level in enumerate(TERCILES):
                for a_index, a_level in enumerate(TERCILES):
                    ax.text((d_index + 0.5) / 3, (a_index + 0.5) / 3, str(counts[(d_level, a_level)]), ha="center", va="center", fontsize=8)
        ax.axvline(1 / 3, color="black", lw=0.8)
        ax.axvline(2 / 3, color="black", lw=0.8)
        ax.axhline(1 / 3, color="black", lw=0.8)
        ax.axhline(2 / 3, color="black", lw=0.8)
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)
        rho = spearman_correlation(group["demand_pct"], group[y_name])
        ax.set_title(f"{city}  Spearman ρ={rho:.2f}" if np.isfinite(rho) else f"{city}  Spearman ρ=NA")
        ax.set_xlabel("Demand percentile (VPD; high = demanding)")
        ax.set_ylabel(f"Antecedent dryness percentile ({window} d; high = dry)")
        if clear_overlay and index == 0:
            ax.legend(frameon=False, loc="lower left")
    for index in range(len(cities), nrows * ncols):
        panels.flat[index].axis("off")
    title = f"Joint weather support: {window}-day antecedent climatic dryness"
    if clear_overlay:
        title += " (all / clear-sky corner counts)"
    fig.suptitle(title, fontsize=14)
    fig.tight_layout()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Matplotlib 3.11.1 can corrupt subplot-title glyphs when a multi-panel
    # transparency overlay is redrawn for ``bbox_inches="tight"``.  The explicit
    # figure size plus ``tight_layout`` already provides complete margins.
    fig.savefig(destination, dpi=180)
    plt.close(fig)
    return destination


def plot_corner_bars(axes: pd.DataFrame, path: str | Path) -> Path:
    """Write F1.3: each off-diagonal share with counts and Wilson CIs."""

    corners = (
        ("high demand / wet antecedent", "high", "low"),
        ("low demand / dry antecedent", "low", "high"),
    )
    rows: list[dict[str, object]] = []
    for city, group in axes.groupby("city", sort=True, observed=True):
        for label, subset in (("all days", group), ("clear sky", group.loc[group["clear_sky"]])):
            valid = subset.dropna(subset=["demand_pct", "antecedent_dryness_30d_pct"])
            demand_levels = valid["demand_tercile_30d"].astype("string")
            dryness_levels = valid["dryness_tercile_30d"].astype("string")
            for corner_label, demand_level, dryness_level in corners:
                count = int(((demand_levels == demand_level) & (dryness_levels == dryness_level)).sum())
                low, high = wilson_interval(count, len(valid))
                rows.append({"city": str(city), "subset": label, "corner": corner_label, "count": count, "total": len(valid), "share": count / len(valid) if len(valid) else np.nan, "low": low, "high": high})
    summary = pd.DataFrame(rows)
    cities = sorted(summary["city"].unique())
    x = np.arange(len(cities), dtype=float)
    width = 0.34
    fig, panels = plt.subplots(1, 2, figsize=(max(11.0, len(cities) * 3.0), 5.0), sharey=True)
    for ax, (corner_label, _, _) in zip(panels, corners):
        corner_summary = summary.loc[summary["corner"] == corner_label]
        for offset, (label, color) in zip((-width / 2, width / 2), (("all days", "#9aa0a6"), ("clear sky", "#1769aa"))):
            part = corner_summary.set_index(["city", "subset"]).reindex([(city, label) for city in cities]).reset_index()
            values = part["share"].to_numpy(dtype=float)
            lower = values - part["low"].to_numpy(dtype=float)
            upper = part["high"].to_numpy(dtype=float) - values
            bars = ax.bar(x + offset, values, width, label=label, color=color, yerr=np.vstack([lower, upper]), capsize=3)
            for bar, count in zip(bars, part["count"]):
                if np.isfinite(bar.get_height()):
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.008, f"n={int(count)}", ha="center", va="bottom", fontsize=8)
        ax.set_xticks(x, cities, rotation=20, ha="right")
        ax.set_ylim(bottom=0)
        ax.set_title(corner_label.capitalize())
    panels[0].set_ylabel("Corner-cell proportion (95% Wilson CI)")
    panels[0].legend(frameon=False)
    fig.suptitle("Off-diagonal support before and after clear-sky sampling")
    fig.tight_layout()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return destination


def plot_phoenix_balance(axes: pd.DataFrame, path: str | Path) -> Path:
    """Write the physical-sign diagnostic requested by Check 2."""

    group = axes.loc[axes["city"].astype(str).str.casefold().str.contains("phoenix")]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    if group.empty:
        ax.text(0.5, 0.5, "Phoenix not present", ha="center", va="center", transform=ax.transAxes)
    else:
        for year, summer in group.groupby("summer_year", sort=True, observed=True):
            day = summer["date"].dt.dayofyear - pd.Timestamp(year=int(year), month=1, day=1).dayofyear
            ax.plot(day, summer["balance_30d_mm"], lw=1.1, alpha=0.75, label=str(year))
        ax.axhline(0, color="black", lw=0.8)
        ax.set_xlabel("Day of year")
        ax.set_ylabel("Previous-30-day P − ET0 (mm)")
        ax.legend(ncol=4, frameon=False, fontsize=8)
    ax.set_title("Phoenix antecedent climatic water balance: June dryness and monsoon rise")
    fig.tight_layout()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return destination


def plot_percentile_histograms(axes: pd.DataFrame, path: str | Path) -> Path:
    """Write the construction/uniformity diagnostic requested by Check 3."""

    variables = (
        ("demand_pct", "Demand"),
        ("antecedent_dryness_30d_pct", "30-day dryness"),
        ("antecedent_dryness_60d_pct", "60-day dryness"),
    )
    fig, panels = plt.subplots(1, 3, figsize=(12, 3.7), sharey=True)
    for ax, (variable, label) in zip(panels, variables):
        for city, group in axes.groupby("city", sort=True, observed=True):
            ax.hist(group[variable].dropna(), bins=np.linspace(0, 1, 11), histtype="step", lw=1.2, label=str(city))
        ax.set_title(label)
        ax.set_xlabel("Within-city percentile")
    panels[0].set_ylabel("Summer-day count")
    panels[-1].legend(frameon=False, fontsize=7)
    fig.tight_layout()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return destination


def write_gate_memo(
    gate: Mapping[str, object],
    window_agreement: pd.DataFrame,
    path: str | Path,
    phoenix_balance: pd.DataFrame | None = None,
) -> Path:
    """Write concise M1.1, preserving the guide's provisional-support caveat."""

    lines = [
        "# M1.1 — Weather-condition feasibility gate",
        "",
        "**Status:** Provisional feasibility screen; this is not a final identifiability decision.",
        "",
        f"**Decision:** `{gate['decision']}`",
        "",
        str(gate["recommendation"]),
        "",
        "## City evidence",
        "",
        "| City | Clear valid days | High-demand / wet | Low-demand / dry | Combined share | Spearman ρ | Within-city support |",
        "|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for row in gate["cities"]:  # type: ignore[index]
        share = row["combined_corner_share"]
        rho = row["spearman"]
        lines.append(
            f"| {row['city']} | {row['n_clear_valid']} | {row['high_demand_wet_count']} | "
            f"{row['low_demand_dry_count']} | "
            f"{share:.1%} | {rho:.2f} | {'yes' if row['within_city_support'] else 'no'} |"
            if np.isfinite(float(share)) and np.isfinite(float(rho))
            else f"| {row['city']} | {row['n_clear_valid']} | {row['high_demand_wet_count']} | "
            f"{row['low_demand_dry_count']} | NA | NA | no |"
        )
    lines += ["", "## Window sensitivity", ""]
    if window_agreement.empty:
        lines.append("No 30/60-day comparison was available.")
    else:
        disagree = window_agreement.loc[~window_agreement["qualitative_same"], "city"].tolist()
        if disagree:
            lines.append(
                "The qualitative support threshold changes between 30 and 60 days for: "
                + ", ".join(map(str, disagree))
                + ". Both windows must be retained in later steps."
            )
        else:
            lines.append("The 30- and 60-day windows give the same qualitative support classification in every city.")
    lines += ["", "## Documented diagnostic failures", ""]
    if phoenix_balance is None or phoenix_balance.empty:
        lines.append("The Phoenix water-balance diagnostic was unavailable.")
    else:
        june_passes = int(phoenix_balance["june_negative"].sum())
        july_rises = int(phoenix_balance["july_rises_from_june"].sum())
        n_summers = len(phoenix_balance)
        lines.append(
            f"Phoenix's 30-day balance is negative in June in {june_passes}/{n_summers} "
            f"summers, but the July median rises above the June median in only "
            f"{july_rises}/{n_summers}. The sign check passes; the strict annual July-rise "
            "check does not. Monsoon timing varies, so the plotted trajectory and both "
            "antecedent windows remain required rather than treating this diagnostic as "
            "uniform support."
        )
    thresholds = gate["thresholds"]  # type: ignore[assignment]
    lines += [
        "",
        "## Predeclared screening rule",
        "",
        f"A city passes this screen when combined clear-sky corner share is at least "
        f"{float(thresholds['min_combined_corner_share']):.0%}, each corner has at least "
        f"{int(thresholds['min_each_corner_count'])} days, and |Spearman ρ| is below "
        f"{float(thresholds['max_abs_spearman']):.2f}. The strong case requires at least "
        f"{int(thresholds['min_cities_for_within_city'])} cities.",
        "",
        "## Limit",
        "",
        "This is a feasibility screen, not proof of identifiability. Step 2 overpass-time support, "
        "Step 3 simulation, common-support diagnostics, and model concurvity remain binding.",
        "",
    ]
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination


def write_step1_deliverables(
    daily: pd.DataFrame,
    domain_records: pd.DataFrame,
    output_dir: str | Path,
    *,
    start_year: int = 2018,
    end_year: int = 2025,
    n_boot: int = 2_000,
    n_permutations: int = 2_000,
    seed: int = 20260801,
    strict_five_cities: bool = True,
) -> dict[str, Path | dict[str, object]]:
    """Create F1.1–F1.4, T1.1–T1.2, M1.1 and all six check artifacts."""

    axes = prepare_condition_axes(daily, start_year=start_year, end_year=end_year)
    cities = sorted(axes["city"].astype(str).unique())
    if strict_five_cities and len(cities) != 5:
        raise ValueError(f"Guide deliverables require exactly five cities; found {len(cities)}")
    root = Path(output_dir)
    figure_dir = root / "figures"
    table_dir = root / "tables"
    memo_dir = root / "memos"
    check_dir = root / "checks"
    for directory in (figure_dir, table_dir, memo_dir, check_dir):
        directory.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path | dict[str, object]] = {}
    paths["F1.1"] = plot_joint_panels(axes, figure_dir / "F1.1_joint_30d.png", window=30)
    paths["F1.2"] = plot_joint_panels(axes, figure_dir / "F1.2_clear_sky_overlay.png", window=30, clear_overlay=True)
    paths["F1.3"] = plot_corner_bars(axes, figure_dir / "F1.3_corner_counts.png")
    paths["F1.4"] = plot_joint_panels(axes, figure_dir / "F1.4_joint_60d.png", window=60)

    t11 = cell_count_table(axes, window=30, n_boot=n_boot, seed=seed)
    t11_path = table_dir / "T1.1_city_cell_counts.csv"
    t11.to_csv(t11_path, index=False)
    paths["T1.1"] = t11_path
    t12 = domain_record_table(axes, domain_records)
    t12_path = table_dir / "T1.2_city_domains.csv"
    t12.to_csv(t12_path, index=False)
    paths["T1.2"] = t12_path

    units = unit_diagnostics(daily)
    units_path = check_dir / "C1_units.csv"
    units.to_csv(units_path, index=False)
    paths["C1"] = units_path
    paths["C2.figure"] = plot_phoenix_balance(axes, check_dir / "C2_phoenix_balance.png")
    physical = phoenix_water_balance_diagnostic(axes)
    physical_path = check_dir / "C2_phoenix_balance.csv"
    physical.to_csv(physical_path, index=False)
    paths["C2.table"] = physical_path
    paths["C3.figure"] = plot_percentile_histograms(axes, check_dir / "C3_percentile_histograms.png")
    uniformity = percentile_uniformity_diagnostic(axes)
    uniformity_path = check_dir / "C3_percentile_uniformity.csv"
    uniformity.to_csv(uniformity_path, index=False)
    paths["C3.table"] = uniformity_path
    # C4 is carried in T1.1: explicit whole-summer unit + CI fields.
    paths["C4"] = t11_path
    permutation = permutation_table(axes, n_permutations=n_permutations, seed=seed)
    permutation_path = check_dir / "C5_permutation_corner_occupancy.csv"
    permutation.to_csv(permutation_path, index=False)
    paths["C5"] = permutation_path
    agreement = window_agreement_table(axes)
    agreement_path = check_dir / "C6_window_agreement.csv"
    agreement.to_csv(agreement_path, index=False)
    paths["C6"] = agreement_path

    gate = evaluate_gate(axes)
    memo_path = memo_dir / "M1.1_feasibility_gate.md"
    write_gate_memo(gate, agreement, memo_path, phoenix_balance=physical)
    paths["M1.1"] = memo_path
    paths["gate"] = gate
    return paths


__all__ = [
    "GateThresholds",
    "OFF_DIAGONAL_CORNERS",
    "TERCILES",
    "add_antecedent_balances",
    "cell_count_table",
    "domain_record_table",
    "empirical_percentile",
    "evaluate_gate",
    "percentile_uniformity_diagnostic",
    "permutation_corner_test",
    "permutation_table",
    "phoenix_water_balance_diagnostic",
    "plot_corner_bars",
    "plot_joint_panels",
    "plot_percentile_histograms",
    "plot_phoenix_balance",
    "prepare_condition_axes",
    "spearman_correlation",
    "summer_block_spearman",
    "summer_mask",
    "unit_diagnostics",
    "wilson_interval",
    "window_agreement_table",
    "write_gate_memo",
    "write_step1_deliverables",
]
