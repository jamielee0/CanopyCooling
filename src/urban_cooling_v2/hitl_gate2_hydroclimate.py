"""Build the nonthermal Gate-2 hydroclimatic-support review package.

This module reads only daily weather, the approved Gate-1 pass census, and
governance records. It never opens an ECOSTRESS temperature/LST value.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DAILY_REL = Path("data/raw/v2/weather/city_daily_2018_2025_valid_geometry.csv")
DAILY_PROVENANCE_REL = Path(
    "data/raw/v2/weather/city_daily_2018_2025_valid_geometry.csv.provenance.json"
)
CANONICAL_AXES_REL = Path("data/processed/v2/step1_condition_axes.csv")
G1_PASS_REL = Path(
    "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/pass_quality_219.csv"
)
G1_LEDGER_REL = Path(
    "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/observation_ledger.csv"
)
G1_CHECKS_REL = Path("docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/checks.json")
D0062_REL = Path("docs/v2/D0062_G1_APPROVAL_AND_G2_AUTHORIZATION.md")
D0063_REL = Path("docs/v2/D0063_G2_PRE_RESULT_HYDROCLIMATE_RULES.md")
GENERATOR_REL = Path("src/urban_cooling_v2/hitl_gate2_hydroclimate.py")
RUNNER_REL = Path("src/run_v2_hitl_gate2.py")
OUTPUT_REL = Path("docs/v2/hitl/G2_HYDROCLIMATE_SUPPORT")

WINDOWS = (30, 60)
MEANINGFUL_RAIN_MM = 5.0
BOOTSTRAP_REPLICATES = 2_000
BOOTSTRAP_SEED = 20260813
PREDICTORS = (
    (
        "precipitation",
        "antecedent_precipitation_{window}d_mm",
        "antecedent_precipitation_{window}d_wetness_percentile",
        "mm",
        "higher_is_wetter",
        "candidate_primary",
    ),
    (
        "days_since_meaningful_rain",
        "days_since_meaningful_rain_{window}d",
        "days_since_meaningful_rain_{window}d_wetness_percentile",
        "days",
        "lower_is_wetter",
        "candidate_primary",
    ),
    (
        "climatic_water_balance",
        "antecedent_climatic_water_balance_{window}d_mm",
        "antecedent_climatic_water_balance_{window}d_wetness_percentile",
        "mm",
        "higher_is_wetter",
        "sensitivity_only",
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _atomic_json(value: Any, path: Path) -> None:
    _atomic_text(json.dumps(value, indent=2, sort_keys=True) + "\n", path)


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False, float_format="%.15g")
    temporary.replace(path)


def _empirical_percentile(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = numeric.notna()
    count = int(valid.sum())
    if count == 0:
        return result
    if count == 1:
        result.loc[valid] = 0.5
        return result
    rank = numeric.loc[valid].rank(method="average")
    result.loc[valid] = (rank - 1.0) / (count - 1.0)
    return result


def _level(values: pd.Series, *, wetness: bool = False) -> pd.Series:
    labels = ["dry", "middle", "wet"] if wetness else ["low", "middle", "high"]
    return pd.cut(
        pd.to_numeric(values, errors="coerce"),
        bins=[-np.inf, 1.0 / 3.0, 2.0 / 3.0, np.inf],
        labels=labels,
        right=False,
        ordered=True,
    ).astype("string")


def _specs() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in WINDOWS:
        for name, raw, wetness, units, direction, role in PREDICTORS:
            rows.append(
                {
                    "predictor": name,
                    "window_days": window,
                    "raw_column": raw.format(window=window),
                    "wetness_column": wetness.format(window=window),
                    "units": units,
                    "wetness_direction": direction,
                    "role": role,
                }
            )
    return rows


def compute_daily_predictors(daily: pd.DataFrame) -> pd.DataFrame:
    """Compute 30/60-day predictors with a strict prior-day window."""

    required = {"city", "date", "pr_mm", "eto_mm", "vpd_kpa"}
    missing = sorted(required - set(daily.columns))
    if missing:
        raise ValueError(f"daily weather is missing {missing}")
    work = daily.copy()
    work["city"] = work["city"].astype(str)
    work["date"] = pd.to_datetime(work["date"], errors="raise").dt.normalize()
    for column in ("pr_mm", "eto_mm", "vpd_kpa"):
        work[column] = pd.to_numeric(work[column], errors="raise")
    if work.duplicated(["city", "date"]).any():
        raise ValueError("daily city-date keys must be unique")
    work["calendar_year"] = work["date"].dt.year.astype(int)
    work = work.sort_values(["city", "calendar_year", "date"]).reset_index(drop=True)

    pieces: list[pd.DataFrame] = []
    for (city, year), group in work.groupby(
        ["city", "calendar_year"], sort=True, observed=True
    ):
        group = group.copy().sort_values("date").reset_index(drop=True)
        differences = group["date"].diff().dropna().dt.days
        if not differences.eq(1).all():
            raise ValueError(f"daily record is not calendar-contiguous for {city} {year}")
        daily_balance = group["pr_mm"] - group["eto_mm"]
        positions = np.arange(len(group), dtype=int)
        event_positions = np.where(
            group["pr_mm"].to_numpy(dtype=float) >= MEANINGFUL_RAIN_MM,
            positions,
            -10_000,
        )
        latest_event_including_today = np.maximum.accumulate(event_positions)
        latest_event_prior_day = np.concatenate(
            [np.asarray([-10_000], dtype=int), latest_event_including_today[:-1]]
        )
        days_since_latest = positions - latest_event_prior_day
        for window in WINDOWS:
            group[f"antecedent_precipitation_{window}d_mm"] = (
                group["pr_mm"].shift(1).rolling(window, min_periods=window).sum()
            )
            group[f"antecedent_climatic_water_balance_{window}d_mm"] = (
                daily_balance.shift(1).rolling(window, min_periods=window).sum()
            )
            complete = positions >= window
            within_window = days_since_latest <= window
            days = np.where(within_window, days_since_latest, window + 1).astype(float)
            days[~complete] = np.nan
            group[f"days_since_meaningful_rain_{window}d"] = days
            group[f"meaningful_rain_right_censored_{window}d"] = (
                complete & ~within_window
            )
        pieces.append(group)

    result = pd.concat(pieces, ignore_index=True)
    summer = result["date"].dt.month.between(6, 9)
    result = result.loc[summer].copy().reset_index(drop=True)
    result["summer_year"] = result["date"].dt.year.astype(int)
    result["month"] = result["date"].dt.month.astype(int)
    for spec in _specs():
        raw_column = spec["raw_column"]
        wetness_column = spec["wetness_column"]
        percentile = result.groupby("city", sort=False, observed=True)[raw_column].transform(
            _empirical_percentile
        )
        if spec["wetness_direction"] == "lower_is_wetter":
            percentile = 1.0 - percentile
        result[wetness_column] = percentile
    predictor_columns = [spec["raw_column"] for spec in _specs()]
    if result[predictor_columns].isna().any().any():
        raise ValueError("antecedent predictors are incomplete on summer dates")
    return result.sort_values(["city", "date"]).reset_index(drop=True)


def audit_exclusive_windows(
    source_daily: pd.DataFrame, daily_predictors: pd.DataFrame
) -> pd.DataFrame:
    """Recompute every summer window explicitly and compare all three predictors."""

    source = source_daily.copy()
    source["date"] = pd.to_datetime(source["date"], errors="raise").dt.normalize()
    source["balance"] = pd.to_numeric(source["pr_mm"], errors="raise") - pd.to_numeric(
        source["eto_mm"], errors="raise"
    )
    lookups: dict[str, dict[pd.Timestamp, tuple[float, float]]] = {}
    for city, group in source.groupby("city", sort=False, observed=True):
        lookups[str(city)] = {
            pd.Timestamp(row.date): (float(row.pr_mm), float(row.balance))
            for row in group.itertuples()
        }

    rows: list[dict[str, Any]] = []
    for window in WINDOWS:
        precipitation_mismatches = 0
        balance_mismatches = 0
        days_since_mismatches = 0
        incomplete = 0
        for row in daily_predictors.itertuples():
            city_lookup = lookups[str(row.city)]
            target = pd.Timestamp(row.date)
            prior_dates = [target - timedelta(days=offset) for offset in range(window, 0, -1)]
            if any(date not in city_lookup for date in prior_dates):
                incomplete += 1
                continue
            precipitation = np.asarray([city_lookup[date][0] for date in prior_dates])
            balance = np.asarray([city_lookup[date][1] for date in prior_dates])
            actual_precipitation = float(
                getattr(row, f"antecedent_precipitation_{window}d_mm")
            )
            actual_balance = float(
                getattr(row, f"antecedent_climatic_water_balance_{window}d_mm")
            )
            if not np.isclose(actual_precipitation, precipitation.sum(), atol=1e-10):
                precipitation_mismatches += 1
            if not np.isclose(actual_balance, balance.sum(), atol=1e-10):
                balance_mismatches += 1
            event_offsets = np.flatnonzero(precipitation >= MEANINGFUL_RAIN_MM)
            expected_days = window - int(event_offsets[-1]) if len(event_offsets) else window + 1
            actual_days = int(getattr(row, f"days_since_meaningful_rain_{window}d"))
            if actual_days != expected_days:
                days_since_mismatches += 1
        rows.append(
            {
                "window_days": window,
                "checked_summer_city_days": len(daily_predictors),
                "incomplete_prior_day_windows": incomplete,
                "precipitation_sum_mismatches": precipitation_mismatches,
                "climatic_balance_sum_mismatches": balance_mismatches,
                "days_since_event_mismatches": days_since_mismatches,
                "observation_day_exclusion_violations": (
                    precipitation_mismatches + balance_mismatches + days_since_mismatches
                ),
                "window_definition": "date-window through date-1 inclusive",
            }
        )
    return pd.DataFrame(rows)


def build_pass_predictors(
    pass_quality: pd.DataFrame,
    observation_ledger: pd.DataFrame,
    daily_predictors: pd.DataFrame,
) -> pd.DataFrame:
    """Join daily antecedent predictors to the approved 219-pass census."""

    if len(pass_quality) != 219 or pass_quality["observation_id"].duplicated().any():
        raise ValueError("Gate-1 pass table must contain 219 unique observations")
    retained = observation_ledger.loc[
        observation_ledger["final_reconciliation_status"].isin(
            [
                "retained_midday_not_early_late",
                "retained_early_late_stratum_eligible",
            ]
        ),
        ["observation_id", "local_solar_date"],
    ]
    if len(retained) != 219 or retained["observation_id"].duplicated().any():
        raise ValueError("Gate-1 ledger does not identify exactly 219 retained passes")
    passes = pass_quality.merge(
        retained, how="inner", on="observation_id", validate="one_to_one"
    )
    passes["local_solar_date"] = pd.to_datetime(
        passes["local_solar_date"], errors="raise"
    ).dt.normalize()
    columns = ["city", "date", "summer_year", "month"]
    for spec in _specs():
        columns.extend([spec["raw_column"], spec["wetness_column"]])
        if spec["predictor"] == "days_since_meaningful_rain":
            columns.append(f"meaningful_rain_right_censored_{spec['window_days']}d")
    columns = list(dict.fromkeys(columns))
    result = passes.merge(
        daily_predictors[columns],
        how="left",
        left_on=["city", "local_solar_date"],
        right_on=["city", "date"],
        validate="many_to_one",
    )
    predictor_columns = [spec["raw_column"] for spec in _specs()]
    if result[predictor_columns].isna().any().any():
        raise ValueError("some retained passes lack Gate-2 predictors")
    result["demand_level_gate2"] = _level(result["demand_percentile"])
    result["meaningful_rain_threshold_mm"] = MEANINGFUL_RAIN_MM
    result["antecedent_window_end"] = "day_before_local_solar_date"
    result["temperature_or_lst_value_opened"] = False
    result["data_origin"] = "empirical_nonthermal"
    return result.sort_values(["city", "local_solar_date", "acquisition_utc"]).reset_index(
        drop=True
    )


def _population_groups(frame: pd.DataFrame) -> Iterable[tuple[str, pd.DataFrame]]:
    yield "ALL_CITIES", frame
    for city, group in frame.groupby("city", sort=True, observed=True):
        yield str(city), group


def build_continuous_distributions(
    daily_predictors: pd.DataFrame, pass_predictors: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for population, frame in (
        ("summer_day_reference", daily_predictors),
        ("retained_physical_pass", pass_predictors),
    ):
        for city, group in _population_groups(frame):
            for spec in _specs():
                values = pd.to_numeric(group[spec["raw_column"]], errors="coerce").dropna()
                quantiles = values.quantile([0.10, 0.25, 0.50, 0.75, 0.90])
                censor_column = f"meaningful_rain_right_censored_{spec['window_days']}d"
                rows.append(
                    {
                        "population": population,
                        "population_unit": (
                            "city_day" if population == "summer_day_reference" else "physical_pass"
                        ),
                        "city": city,
                        "predictor": spec["predictor"],
                        "predictor_role": spec["role"],
                        "window_days": spec["window_days"],
                        "units": spec["units"],
                        "wetness_direction": spec["wetness_direction"],
                        "physical_unit_count": len(values),
                        "clear_domain_pass_equivalent_sum": (
                            float(group.loc[values.index, "clear_domain_fraction"].sum())
                            if population == "retained_physical_pass"
                            else np.nan
                        ),
                        "right_censored_count": (
                            int(group.loc[values.index, censor_column].sum())
                            if spec["predictor"] == "days_since_meaningful_rain"
                            else 0
                        ),
                        "minimum": float(values.min()),
                        "q10": float(quantiles.loc[0.10]),
                        "q25": float(quantiles.loc[0.25]),
                        "median": float(quantiles.loc[0.50]),
                        "q75": float(quantiles.loc[0.75]),
                        "q90": float(quantiles.loc[0.90]),
                        "maximum": float(values.max()),
                        "mean": float(values.mean()),
                        "standard_deviation": float(values.std(ddof=1)),
                    }
                )
    return pd.DataFrame(rows)


def _spearman(x: pd.Series, y: pd.Series) -> float:
    pair = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(pair) < 3:
        return float("nan")
    ranked = pair.rank(method="average")
    if ranked["x"].nunique() < 2 or ranked["y"].nunique() < 2:
        return float("nan")
    return float(ranked["x"].corr(ranked["y"]))


def _block_bootstrap_spearman(
    frame: pd.DataFrame,
    *,
    x: str,
    y: str,
    block: str,
    seed: int,
    n_boot: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    clean = frame[[x, y, block]].dropna()
    observed = _spearman(clean[x], clean[y])
    labels = sorted(clean[block].astype(str).unique())
    blocks = {
        label: clean.loc[clean[block].astype(str).eq(label), [x, y]] for label in labels
    }
    rng = np.random.default_rng(seed)
    draws: list[float] = []
    if len(labels) >= 2:
        for _ in range(n_boot):
            sampled = rng.choice(labels, size=len(labels), replace=True)
            replicate = pd.concat([blocks[str(label)] for label in sampled], ignore_index=True)
            rho = _spearman(replicate[x], replicate[y])
            if np.isfinite(rho):
                draws.append(rho)
    low, high = (
        np.quantile(draws, [0.025, 0.975]).tolist()
        if draws
        else [float("nan"), float("nan")]
    )
    return {
        "spearman": observed,
        "spearman_ci_low": float(low),
        "spearman_ci_high": float(high),
        "n_physical_passes": len(clean),
        "n_blocks": len(labels),
        "n_boot": n_boot,
        "n_valid_boot": len(draws),
        "bootstrap_unit": "whole_city_summer",
    }


def build_demand_correlations(pass_predictors: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    index = 0
    work = pass_predictors.copy()
    work["city_summer_block"] = (
        work["city"].astype(str) + "|" + work["summer_year"].astype(str)
    )
    for city, group in _population_groups(work):
        for spec in _specs():
            result = _block_bootstrap_spearman(
                group,
                x="vpd_kpa_at_acquisition",
                y=spec["raw_column"],
                block="city_summer_block",
                seed=BOOTSTRAP_SEED + index * 101,
            )
            rows.append(
                {
                    "city": city,
                    "demand_variable": "vpd_kpa_at_acquisition",
                    "predictor": spec["predictor"],
                    "predictor_role": spec["role"],
                    "window_days": spec["window_days"],
                    "raw_predictor_units": spec["units"],
                    "wetness_direction": spec["wetness_direction"],
                    **result,
                    "spearman_demand_vs_wetness_percentile": _spearman(
                        group["vpd_kpa_at_acquisition"], group[spec["wetness_column"]]
                    ),
                }
            )
            index += 1
    return pd.DataFrame(rows)


def build_predictor_pair_correlations(pass_predictors: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for city, group in _population_groups(pass_predictors):
        for window in WINDOWS:
            specs = [spec for spec in _specs() if spec["window_days"] == window]
            for left_index, left in enumerate(specs):
                for right in specs[left_index + 1 :]:
                    rows.append(
                        {
                            "city": city,
                            "window_days": window,
                            "left_predictor": left["predictor"],
                            "right_predictor": right["predictor"],
                            "n_physical_passes": len(group),
                            "raw_spearman": _spearman(
                                group[left["raw_column"]], group[right["raw_column"]]
                            ),
                            "wetness_oriented_percentile_spearman": _spearman(
                                group[left["wetness_column"]],
                                group[right["wetness_column"]],
                            ),
                            "interpretation": (
                                "descriptive_predictor_collinearity_not_outcome_evidence"
                            ),
                        }
                    )
    return pd.DataFrame(rows)


def build_descriptive_grid(pass_predictors: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for city, group in _population_groups(pass_predictors):
        for spec in _specs():
            wetness_level = _level(group[spec["wetness_column"]], wetness=True)
            for demand in ("low", "middle", "high"):
                for wetness in ("dry", "middle", "wet"):
                    selected = group.loc[
                        group["demand_level_gate2"].eq(demand)
                        & wetness_level.eq(wetness)
                    ]
                    rows.append(
                        {
                            "city": city,
                            "predictor": spec["predictor"],
                            "predictor_role": spec["role"],
                            "window_days": spec["window_days"],
                            "demand_level": demand,
                            "wetness_level": wetness,
                            "physical_passes": len(selected),
                            "clear_domain_pass_equivalent_sum": float(
                                selected["clear_domain_fraction"].sum()
                            ),
                            "descriptive_only": True,
                            "scientific_gate_eligible": False,
                        }
                    )
    return pd.DataFrame(rows)


def build_high_demand_support(
    pass_predictors: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    support_rows: list[dict[str, Any]] = []
    overlap_rows: list[dict[str, Any]] = []
    for city, group in _population_groups(pass_predictors):
        high = group.loc[group["demand_level_gate2"].eq("high")].copy()
        for spec in _specs():
            high["_wetness_level"] = _level(high[spec["wetness_column"]], wetness=True)
            strata: dict[str, pd.DataFrame] = {}
            for wetness in ("dry", "middle", "wet"):
                selected = high.loc[high["_wetness_level"].eq(wetness)]
                strata[wetness] = selected
                support_rows.append(
                    {
                        "city": city,
                        "predictor": spec["predictor"],
                        "predictor_role": spec["role"],
                        "window_days": spec["window_days"],
                        "wetness_level": wetness,
                        "high_demand_physical_passes": len(selected),
                        "high_demand_pass_equivalent_sum": float(
                            selected["clear_domain_fraction"].sum()
                        ),
                        "median_vpd_kpa_at_acquisition": (
                            float(selected["vpd_kpa_at_acquisition"].median())
                            if len(selected)
                            else np.nan
                        ),
                        "descriptive_only_gate4_decides_overlap": True,
                    }
                )
            wet_values = strata["wet"]["vpd_kpa_at_acquisition"].dropna()
            dry_values = strata["dry"]["vpd_kpa_at_acquisition"].dropna()
            if len(wet_values) and len(dry_values):
                lower = max(float(wet_values.min()), float(dry_values.min()))
                upper = min(float(wet_values.max()), float(dry_values.max()))
                width = max(0.0, upper - lower)
                union_width = max(
                    float(wet_values.max()), float(dry_values.max())
                ) - min(float(wet_values.min()), float(dry_values.min()))
                fraction = width / union_width if union_width > 0 else 0.0
            else:
                lower = upper = width = union_width = fraction = np.nan
            overlap_rows.append(
                {
                    "city": city,
                    "predictor": spec["predictor"],
                    "predictor_role": spec["role"],
                    "window_days": spec["window_days"],
                    "high_demand_wet_physical_passes": len(wet_values),
                    "high_demand_dry_physical_passes": len(dry_values),
                    "absolute_vpd_overlap_lower_kpa": lower,
                    "absolute_vpd_overlap_upper_kpa": upper,
                    "absolute_vpd_overlap_width_kpa": width,
                    "absolute_vpd_union_width_kpa": union_width,
                    "absolute_vpd_range_overlap_fraction": fraction,
                    "both_groups_present": bool(len(wet_values) and len(dry_values)),
                    "positive_absolute_vpd_range_overlap": bool(
                        np.isfinite(width) and width > 0
                    ),
                    "status": "DESCRIPTIVE_ONLY_G4_FORMAL_AUDIT_REQUIRED",
                }
            )
    return pd.DataFrame(support_rows), pd.DataFrame(overlap_rows)


def build_seasonal_variance(
    pass_predictors: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    annual_rows: list[dict[str, Any]] = []
    for city, city_group in pass_predictors.groupby("city", sort=True, observed=True):
        for spec in _specs():
            for year, group in city_group.groupby("summer_year", sort=True, observed=True):
                values = group[spec["raw_column"]].dropna()
                annual_rows.append(
                    {
                        "city": str(city),
                        "summer_year": int(year),
                        "predictor": spec["predictor"],
                        "predictor_role": spec["role"],
                        "window_days": spec["window_days"],
                        "units": spec["units"],
                        "physical_passes": len(values),
                        "clear_domain_pass_equivalent_sum": float(
                            group.loc[values.index, "clear_domain_fraction"].sum()
                        ),
                        "mean": float(values.mean()),
                        "median": float(values.median()),
                        "within_summer_variance": (
                            float(values.var(ddof=1)) if len(values) > 1 else np.nan
                        ),
                    }
                )
    annual = pd.DataFrame(annual_rows)
    summary_rows: list[dict[str, Any]] = []
    for keys, group in annual.groupby(
        ["city", "predictor", "predictor_role", "window_days", "units"],
        sort=True,
        observed=True,
    ):
        city, predictor, role, window, units = keys
        summary_rows.append(
            {
                "city": city,
                "predictor": predictor,
                "predictor_role": role,
                "window_days": int(window),
                "units": units,
                "summers_with_passes": int(group["summer_year"].nunique()),
                "total_physical_passes": int(group["physical_passes"].sum()),
                "minimum_passes_in_observed_summer": int(group["physical_passes"].min()),
                "maximum_passes_in_observed_summer": int(group["physical_passes"].max()),
                "mean_within_summer_variance": float(
                    group["within_summer_variance"].mean()
                ),
                "between_summer_mean_variance": (
                    float(group["mean"].var(ddof=1)) if len(group) > 1 else np.nan
                ),
                "between_summer_median_variance": (
                    float(group["median"].var(ddof=1)) if len(group) > 1 else np.nan
                ),
                "minimum_summer_median": float(group["median"].min()),
                "maximum_summer_median": float(group["median"].max()),
            }
        )
    return annual, pd.DataFrame(summary_rows)


def phoenix_independent_sign_check(
    source_daily: pd.DataFrame,
    daily_predictors: pd.DataFrame,
    canonical_axes: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compare an independent raw-input balance calculation to canonical Step 1."""

    independent = daily_predictors.loc[
        daily_predictors["city"].eq("phoenix") & daily_predictors["month"].eq(6),
        ["date", "summer_year", "antecedent_climatic_water_balance_30d_mm"],
    ].copy()
    canonical = canonical_axes.copy()
    canonical["date"] = pd.to_datetime(canonical["date"], errors="raise").dt.normalize()
    canonical = canonical.loc[
        canonical["city"].eq("phoenix") & canonical["date"].dt.month.eq(6),
        ["date", "balance_30d_mm"],
    ]
    comparison = independent.merge(canonical, on="date", how="inner", validate="one_to_one")
    comparison["absolute_difference_mm"] = (
        comparison["antecedent_climatic_water_balance_30d_mm"]
        - comparison["balance_30d_mm"]
    ).abs()

    raw = source_daily.copy()
    raw["date"] = pd.to_datetime(raw["date"], errors="raise").dt.normalize()
    raw["daily_balance"] = raw["pr_mm"] - raw["eto_mm"]
    phoenix_lookup = {
        pd.Timestamp(row.date): float(row.daily_balance)
        for row in raw.loc[raw["city"].eq("phoenix")].itertuples()
    }
    explicit_mismatches = 0
    for row in comparison.itertuples():
        target = pd.Timestamp(row.date)
        explicit = sum(
            phoenix_lookup[target - timedelta(days=offset)] for offset in range(30, 0, -1)
        )
        if not np.isclose(
            explicit,
            float(row.antecedent_climatic_water_balance_30d_mm),
            atol=1e-10,
        ):
            explicit_mismatches += 1

    rows: list[dict[str, Any]] = []
    for year, group in comparison.groupby("summer_year", sort=True, observed=True):
        median = float(group["antecedent_climatic_water_balance_30d_mm"].median())
        rows.append(
            {
                "summer_year": int(year),
                "june_days": len(group),
                "independent_june_median_balance_30d_mm": median,
                "june_median_is_negative": median < 0,
                "maximum_absolute_difference_from_canonical_mm": float(
                    group["absolute_difference_mm"].max()
                ),
            }
        )
    table = pd.DataFrame(rows)
    pooled_median = float(
        comparison["antecedent_climatic_water_balance_30d_mm"].median()
    )
    maximum_difference = float(comparison["absolute_difference_mm"].max())
    summary = {
        "summer_years_checked": len(table),
        "summer_years_with_negative_june_median": int(
            table["june_median_is_negative"].sum()
        ),
        "pooled_june_median_balance_30d_mm": pooled_median,
        "strongly_negative_threshold_mm": -100.0,
        "pooled_strongly_negative_pass": pooled_median <= -100.0,
        "maximum_absolute_difference_from_canonical_mm": maximum_difference,
        "canonical_agreement_tolerance_mm": 1e-9,
        "canonical_agreement_pass": maximum_difference <= 1e-9,
        "explicit_prior_day_recalculation_mismatches": explicit_mismatches,
        "observation_day_exclusion_violations": explicit_mismatches,
    }
    summary["overall_pass"] = bool(
        len(table) == 8
        and table["june_median_is_negative"].all()
        and summary["pooled_strongly_negative_pass"]
        and summary["canonical_agreement_pass"]
        and explicit_mismatches == 0
    )
    return table, summary


def _plot_distributions(pass_predictors: pd.DataFrame, path: Path) -> None:
    figure, axes = plt.subplots(2, 3, figsize=(15, 8.5), constrained_layout=True)
    colours = plt.get_cmap("tab10")
    for axis, spec in zip(axes.ravel(), _specs(), strict=True):
        for index, (city, group) in enumerate(
            pass_predictors.groupby("city", sort=True, observed=True)
        ):
            values = np.sort(group[spec["raw_column"]].to_numpy(dtype=float))
            ecdf = np.arange(1, len(values) + 1) / len(values)
            axis.step(values, ecdf, where="post", label=str(city), color=colours(index))
        axis.set_title(
            f"{spec['window_days']}d {spec['predictor'].replace('_', ' ')}"
        )
        axis.set_xlabel(spec["units"])
        axis.set_ylabel("Empirical cumulative share")
        axis.grid(alpha=0.2)
    axes[0, 0].legend(fontsize=8, frameon=False)
    figure.suptitle(
        "Gate 2 — continuous nonthermal predictor distributions across 219 physical passes",
        fontsize=14,
    )
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _plot_high_demand_support(high_support: pd.DataFrame, path: Path) -> None:
    city_order = sorted(
        high_support.loc[~high_support["city"].eq("ALL_CITIES"), "city"].unique()
    )
    metric_order = [
        f"{spec['window_days']}d\n{spec['predictor'].replace('_', ' ')}" for spec in _specs()
    ]
    figure, axes = plt.subplots(1, 2, figsize=(15, 5.5), constrained_layout=True)
    for axis, wetness in zip(axes, ("wet", "dry"), strict=True):
        matrix = np.zeros((len(city_order), len(_specs())), dtype=int)
        for column, spec in enumerate(_specs()):
            for row, city in enumerate(city_order):
                selected = high_support.loc[
                    high_support["city"].eq(city)
                    & high_support["predictor"].eq(spec["predictor"])
                    & high_support["window_days"].eq(spec["window_days"])
                    & high_support["wetness_level"].eq(wetness),
                    "high_demand_physical_passes",
                ]
                matrix[row, column] = int(selected.iloc[0])
        image = axis.imshow(matrix, cmap="Blues", aspect="auto", vmin=0)
        for row in range(matrix.shape[0]):
            for column in range(matrix.shape[1]):
                axis.text(column, row, str(matrix[row, column]), ha="center", va="center")
        axis.set_xticks(range(len(metric_order)), metric_order, rotation=25, ha="right")
        axis.set_yticks(range(len(city_order)), city_order)
        axis.set_title(f"High-demand / {wetness} physical passes")
        figure.colorbar(image, ax=axis, shrink=0.75, label="Physical passes")
    figure.suptitle(
        "Gate 2 — descriptive high-demand support (Gate 4 decides formal overlap)",
        fontsize=14,
    )
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _review_markdown(
    high_support: pd.DataFrame,
    overlap: pd.DataFrame,
    demand_correlations: pd.DataFrame,
    pair_correlations: pd.DataFrame,
    distributions: pd.DataFrame,
    phoenix_summary: dict[str, Any],
) -> str:
    totals = high_support.loc[high_support["city"].eq("ALL_CITIES")]
    lines = []
    for spec in _specs():
        selected = totals.loc[
            totals["predictor"].eq(spec["predictor"])
            & totals["window_days"].eq(spec["window_days"])
        ].set_index("wetness_level")
        lines.append(
            f"| {spec['window_days']} | {spec['predictor'].replace('_', ' ')} | "
            f"{int(selected.loc['wet', 'high_demand_physical_passes'])} | "
            f"{int(selected.loc['dry', 'high_demand_physical_passes'])} | "
            f"{float(selected.loc['wet', 'high_demand_pass_equivalent_sum']):.3f} | "
            f"{float(selected.loc['dry', 'high_demand_pass_equivalent_sum']):.3f} |"
        )
    city_overlap = overlap.loc[
        ~overlap["city"].eq("ALL_CITIES")
        & overlap["positive_absolute_vpd_range_overlap"]
    ].groupby(["predictor", "window_days"], observed=True)["city"].nunique()
    correlations = demand_correlations.loc[demand_correlations["city"].eq("ALL_CITIES")]
    correlation_lines = []
    for row in correlations.itertuples():
        correlation_lines.append(
            f"- {row.window_days}d {row.predictor.replace('_', ' ')}: raw Spearman "
            f"{row.spearman:.3f} (whole-city-summer 95% interval "
            f"{row.spearman_ci_low:.3f} to {row.spearman_ci_high:.3f})."
        )
    overlap_lines = []
    for spec in _specs():
        count = int(city_overlap.get((spec["predictor"], spec["window_days"]), 0))
        overlap_lines.append(
            f"- {spec['window_days']}d {spec['predictor'].replace('_', ' ')}: "
            f"{count}/5 cities have both high-demand wet/dry passes with positive raw-VPD "
            "range overlap."
        )
    censor = distributions.loc[
        distributions["population"].eq("retained_physical_pass")
        & distributions["predictor"].eq("days_since_meaningful_rain")
    ]
    censor_lines = []
    for window in WINDOWS:
        selected = censor.loc[censor["window_days"].eq(window)].set_index("city")
        cells = []
        for city in (
            "atlanta",
            "los_angeles",
            "miami",
            "minneapolis_st_paul",
            "phoenix",
        ):
            cells.append(
                f"{int(selected.loc[city, 'right_censored_count'])}/"
                f"{int(selected.loc[city, 'physical_unit_count'])}"
            )
        censor_lines.append(f"| {window} | " + " | ".join(cells) + " |")
    pair = pair_correlations.loc[
        pair_correlations["city"].eq("ALL_CITIES")
        & pair_correlations["left_predictor"].eq("precipitation")
        & pair_correlations["right_predictor"].eq("climatic_water_balance")
    ].set_index("window_days")
    return f"""# Gate 2 review — Antecedent hydroclimatic support

**Gate status:** `COMPLETE_AWAITING_HUMAN_APPROVAL`  
**Authorized by:** `D0062`; pre-result rules frozen by `D0063`  
**Next gate remains locked:** `G3`

## Bottom line

Gate 2 rebuilt all three nonthermal predictor definitions for both 30- and 60-day
prior-day windows across the approved 219 physical passes and the 4,880-day summer reference.
The continuous values are primary; every 3×3 count is explicitly descriptive. No predictor
has been adopted as the final study definition, and formal high-demand overlap remains assigned
to Gate 4.

## High-demand support

| Window (days) | Predictor | Wet passes | Dry passes | Wet pass-equivalents | Dry pass-equivalents |
|---:|---|---:|---:|---:|---:|
{chr(10).join(lines)}

These pooled totals do not establish a pooled comparison. The within-city absolute-demand
range check is still descriptive:

{chr(10).join(overlap_lines)}

## Demand–predictor correlations

{chr(10).join(correlation_lines)}

The pooled rows are descriptive because city climate differences remain a confounding source;
the CSV also reports every city separately. `P - ET0` is retained only as antecedent climatic
water-balance sensitivity because ET0 partly contains atmospheric demand.

## Material support limitations and carry-forward assessment

The days-since metric is heavily right-censored where no ≥5 mm event occurred in the window:

| Window (days) | Atlanta | Los Angeles | Miami | Minneapolis–St. Paul | Phoenix |
|---:|---:|---:|---:|---:|---:|
{chr(10).join(censor_lines)}

This is especially material for Los Angeles: 44/48 passes are censored at 31 days in the
30-day definition, producing no high-demand wet or dry tertile observations; the 60-day
definition still has 34/48 censored and no high-demand dry observations. Phoenix is also
substantially censored. The metric remains reported as requested, but it is not a broadly
discriminating five-city primary definition at the frozen 5 mm threshold.

Accumulated precipitation has high-demand wet and dry passes with positive raw-VPD range
overlap in all five cities for both windows, so it is the cleaner primary candidate to carry
into Gate 3. This is a support recommendation, not final adoption. Climatic water balance
remains sensitivity-only: its pooled raw correlation with precipitation is
**{float(pair.loc[30, 'raw_spearman']):.3f}** at 30 days and
**{float(pair.loc[60, 'raw_spearman']):.3f}** at 60 days, while its demand correlation is
stronger than precipitation's.

## Independent Phoenix sign check

The raw-input implementation reproduced all eight negative June medians. The pooled June
30-day balance median was **{phoenix_summary['pooled_june_median_balance_30d_mm']:.3f} mm**, satisfying
the prospectively frozen strongly-negative threshold of -100 mm. Maximum disagreement with
the canonical Step-1 series was
**{phoenix_summary['maximum_absolute_difference_from_canonical_mm']:.3g} mm**, with zero
observation-day leakage violations.

## Interpretation boundary

- Precipitation and days since ≥5 mm rain are candidate wetness definitions.
- `P - ET0` is a sensitivity; it is not irrigation, soil moisture, root-zone water, or plant
  water availability.
- A day with ≥5 mm rain is an operational event flag, not proof that the rain reached a tree's
  root zone.
- Clear-domain pass-equivalents remain secondary exposure diagnostics beside physical counts.
- Existing D0060/D0061 deviations remain in the study history; Gate 2 introduced no new
  query or data-access deviation.

## Files to review

1. `pass_hydroclimate_219.csv` — continuous predictors for every approved physical pass.
2. `continuous_distributions.csv` — all quantiles for passes and summer-day references.
3. `demand_predictor_correlations.csv` and `predictor_pair_correlations.csv` — correlations
   and whole-city-summer uncertainty.
4. `high_demand_wet_dry_support.csv` and `high_demand_absolute_vpd_overlap.csv` — physical and
   weighted support with descriptive overlap.
5. `descriptive_3x3_support.csv` — explicitly non-gating grid counts.
6. `city_year_predictor_support.csv` and `seasonal_variance.csv` — interannual support.
7. `phoenix_june_sign_check.csv`, `window_exclusion_audit.csv`, and `checks.json` — known-answer,
   leakage, binding, and sealed-state checks.
8. `figures/continuous_predictor_distributions.png` and
   `figures/high_demand_wet_dry_support.png` — the two essential Gate-2 figures.

## Your decision

- `APPROVE G2` — bind this support audit and authorize G3 nonthermal sampling-design work only.
- `REVISE G2: <change>` — revise this package; do not begin G3.
- `STOP` — preserve all locks and do not continue.
"""


def _source_bindings(root: Path) -> dict[str, Any]:
    roles = {
        DAILY_REL: "checksum-bound corrected daily nonthermal weather",
        DAILY_PROVENANCE_REL: "daily-weather retrieval and product provenance",
        CANONICAL_AXES_REL: "canonical Step-1 balance series for independent comparison",
        G1_PASS_REL: "approved Gate-1 219-pass quality census",
        G1_LEDGER_REL: "approved Gate-1 physical observation ledger and local-solar dates",
        G1_CHECKS_REL: "approved Gate-1 checks and sealed state",
        D0062_REL: "user approval and Gate-2 authorization",
        D0063_REL: "prospectively frozen Gate-2 definitions",
        GENERATOR_REL: "Gate-2 implementation",
        RUNNER_REL: "Gate-2 reproducible runner",
    }
    return {
        "schema_version": 1,
        "gate": "G2",
        "authorized_by": "D0062",
        "pre_result_rule": "D0063",
        "inputs": {
            path.as_posix(): {"sha256": sha256_file(root / path), "role": role}
            for path, role in roles.items()
        },
    }


def write_gate2_package(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    output = root_path / OUTPUT_REL
    figures = output / "figures"
    output.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)

    source_daily = pd.read_csv(root_path / DAILY_REL)
    canonical_axes = pd.read_csv(root_path / CANONICAL_AXES_REL)
    pass_quality = pd.read_csv(root_path / G1_PASS_REL)
    ledger = pd.read_csv(root_path / G1_LEDGER_REL, low_memory=False)

    daily_predictors = compute_daily_predictors(source_daily)
    if len(daily_predictors) != 5 * 8 * 122:
        raise ValueError(
            f"expected 4,880 summer city-days, found {len(daily_predictors)}"
        )
    window_audit = audit_exclusive_windows(source_daily, daily_predictors)
    pass_predictors = build_pass_predictors(pass_quality, ledger, daily_predictors)
    distributions = build_continuous_distributions(daily_predictors, pass_predictors)
    demand_correlations = build_demand_correlations(pass_predictors)
    pair_correlations = build_predictor_pair_correlations(pass_predictors)
    grid = build_descriptive_grid(pass_predictors)
    high_support, overlap = build_high_demand_support(pass_predictors)
    annual_support, seasonal_variance = build_seasonal_variance(pass_predictors)
    phoenix_table, phoenix_summary = phoenix_independent_sign_check(
        source_daily, daily_predictors, canonical_axes
    )

    output_tables = {
        "daily_reference_predictors_4880.csv": daily_predictors,
        "pass_hydroclimate_219.csv": pass_predictors,
        "continuous_distributions.csv": distributions,
        "demand_predictor_correlations.csv": demand_correlations,
        "predictor_pair_correlations.csv": pair_correlations,
        "descriptive_3x3_support.csv": grid,
        "high_demand_wet_dry_support.csv": high_support,
        "high_demand_absolute_vpd_overlap.csv": overlap,
        "city_year_predictor_support.csv": annual_support,
        "seasonal_variance.csv": seasonal_variance,
        "phoenix_june_sign_check.csv": phoenix_table,
        "window_exclusion_audit.csv": window_audit,
    }
    for name, frame in output_tables.items():
        _atomic_csv(frame, output / name)

    _plot_distributions(pass_predictors, figures / "continuous_predictor_distributions.png")
    _plot_high_demand_support(
        high_support, figures / "high_demand_wet_dry_support.png"
    )
    _atomic_text(
        _review_markdown(
            high_support,
            overlap,
            demand_correlations,
            pair_correlations,
            distributions,
            phoenix_summary,
        ),
        output / "review.md",
    )
    _atomic_json(_source_bindings(root_path), output / "source_bindings.json")

    all_windows_exclusive = bool(
        window_audit[
            [
                "incomplete_prior_day_windows",
                "precipitation_sum_mismatches",
                "climatic_balance_sum_mismatches",
                "days_since_event_mismatches",
                "observation_day_exclusion_violations",
            ]
        ].eq(0).all().all()
    )
    checks = [
        {
            "check_id": "G2-C01",
            "name": "approved_populations_complete",
            "status": "PASS",
            "evidence": {
                "source_daily_rows": len(source_daily),
                "summer_reference_city_days": len(daily_predictors),
                "retained_physical_passes": len(pass_predictors),
                "unique_pass_ids": int(pass_predictors["observation_id"].nunique()),
            },
        },
        {
            "check_id": "G2-C02",
            "name": "antecedent_windows_end_day_before_observation",
            "status": "PASS" if all_windows_exclusive else "FAIL",
            "evidence": window_audit.to_dict("records"),
        },
        {
            "check_id": "G2-C03",
            "name": "all_three_predictors_both_windows_complete",
            "status": "PASS",
            "evidence": {
                "predictors": [spec["predictor"] for spec in _specs()],
                "windows_days": list(WINDOWS),
                "missing_pass_values": int(
                    pass_predictors[[spec["raw_column"] for spec in _specs()]]
                    .isna()
                    .sum()
                    .sum()
                ),
            },
        },
        {
            "check_id": "G2-C04",
            "name": "meaningful_rain_threshold_frozen_before_results",
            "status": "PASS",
            "evidence": {
                "decision": "D0063",
                "threshold_mm_per_day": MEANINGFUL_RAIN_MM,
                "no_event_encoding": "window_plus_one_with_separate_right_censor_flag",
                "alternative_thresholds_evaluated": 0,
            },
        },
        {
            "check_id": "G2-C05",
            "name": "continuous_distributions_correlations_and_seasonal_variance_reported",
            "status": "PASS",
            "evidence": {
                "distribution_rows": len(distributions),
                "demand_correlation_rows": len(demand_correlations),
                "predictor_pair_rows": len(pair_correlations),
                "city_year_rows": len(annual_support),
                "bootstrap_unit": "whole_city_summer",
                "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            },
        },
        {
            "check_id": "G2-C06",
            "name": "physical_counts_accompany_pass_equivalents",
            "status": "PASS",
            "evidence": {
                "tables": [
                    "continuous_distributions.csv",
                    "descriptive_3x3_support.csv",
                    "high_demand_wet_dry_support.csv",
                    "city_year_predictor_support.csv",
                ]
            },
        },
        {
            "check_id": "G2-C07",
            "name": "high_demand_support_and_grid_are_descriptive",
            "status": "PASS_G4_FORMAL_OVERLAP_STILL_REQUIRED",
            "evidence": {
                "grid_rows": len(grid),
                "all_grid_rows_descriptive_only": bool(grid["descriptive_only"].all()),
                "formal_overlap_gate": "G4",
            },
        },
        {
            "check_id": "G2-C08",
            "name": "independent_phoenix_june_balance_reproduced",
            "status": "PASS" if phoenix_summary["overall_pass"] else "FAIL",
            "evidence": phoenix_summary,
        },
        {
            "check_id": "G2-C09",
            "name": "construct_interpretation_limited",
            "status": "PASS",
            "evidence": {
                "water_balance_name": "antecedent_climatic_water_balance",
                "water_balance_role": "sensitivity_only",
                "prohibited_interpretations": [
                    "irrigation",
                    "root_zone_water",
                    "soil_moisture_availability",
                    "direct_plant_water_measurement",
                ],
            },
        },
        {
            "check_id": "G2-C10",
            "name": "gate2_data_access_scope_preserved",
            "status": "PASS_NO_NEW_DEVIATION",
            "evidence": {
                "temperature_or_lst_layers_opened_during_gate2": 0,
                "record_2026_queries_during_gate2": 0,
                "record_2026_science_data_status": "UNOPENED",
                "holdout_status": "UNSELECTED",
                "task2_result_bearing_actions_enabled": False,
                "prior_protocol_deviations_preserved": ["D0060", "D0061"],
                "next_gate_authorized": False,
            },
        },
        {
            "check_id": "G2-C11",
            "name": "days_since_meaningful_rain_right_censoring_reported",
            "status": "PASS_WITH_MATERIAL_SUPPORT_LIMITATION",
            "evidence": distributions.loc[
                distributions["population"].eq("retained_physical_pass")
                & distributions["predictor"].eq("days_since_meaningful_rain"),
                [
                    "city",
                    "window_days",
                    "physical_unit_count",
                    "right_censored_count",
                ],
            ].to_dict("records"),
        },
    ]
    if not all_windows_exclusive or not phoenix_summary["overall_pass"]:
        raise ValueError("Gate-2 known-answer or prior-day window check failed")

    artifact_paths = [
        *(output / name for name in output_tables),
        output / "review.md",
        output / "source_bindings.json",
        figures / "continuous_predictor_distributions.png",
        figures / "high_demand_wet_dry_support.png",
    ]
    checks_json = {
        "schema_version": 1,
        "gate": "G2",
        "gate_name": "rebuild_antecedent_hydroclimatic_support",
        "prepared_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorized_by": "D0062",
        "pre_result_rule": "D0063",
        "gate_status": "COMPLETE_AWAITING_HUMAN_APPROVAL",
        "technical_checks_pass": True,
        "gate2_scope_compliance_pass": True,
        "study_clean_protocol_compliance": False,
        "study_protocol_deviation_records": ["D0060", "D0061"],
        "approval_received": False,
        "next_gate_authorized": False,
        "next_gate_if_approved": "G3",
        "sealed_state": {
            "thermal_or_lst_layers_opened_during_gate2": 0,
            "record_2026_queries_during_gate2": 0,
            "record_2026_science_data_status": "UNOPENED",
            "holdout_status": "UNSELECTED",
            "task2_result_bearing_actions_enabled": False,
        },
        "artifact_sha256": {
            path.relative_to(root_path).as_posix(): sha256_file(path)
            for path in artifact_paths
        },
        "checks": checks,
        "user_action_required": "APPROVE_G2_REVISE_G2_OR_STOP",
    }
    _atomic_json(checks_json, output / "checks.json")
    return {
        "gate_status": checks_json["gate_status"],
        "output_directory": output.as_posix(),
        "summer_reference_city_days": len(daily_predictors),
        "retained_physical_passes": len(pass_predictors),
        "predictor_definitions": 3,
        "antecedent_windows": list(WINDOWS),
        "meaningful_rain_threshold_mm": MEANINGFUL_RAIN_MM,
        "phoenix_sign_check_pass": phoenix_summary["overall_pass"],
        "next_gate_authorized": False,
    }
