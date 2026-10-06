#!/usr/bin/env python3
"""Nonthermal Step-3 power study for the D0056 time-of-day-only branch.

The hydroclimatic interaction remains stopped.  This module powers only the
predeclared primary time-of-day estimand: the adjusted cooling contrast in the
16--18 local-solar-time stratum minus the corresponding contrast in 10--12.
Weather and geometry predictors live at pass level, so inference and bootstrap
resampling use whole passes.  Middle daytime strata remain in the empirical
census but do not inflate the effective sample size of the two-stratum primary
contrast.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from urban_cooling_v2.step02_catalog import TIME_STRATA, assign_time_stratum
from urban_cooling_v2.step03_power import (
    OBSERVED_GEOMETRY_STATUS,
    validate_template as validate_step3_template,
)


DECISION_ID = "D0056"
ANALYSIS_PROFILE = "D0056_time_of_day_only"
SCIENTIFIC_GATE_SCOPE = "time_of_day_only_archive_available_D0047"
PASS_STATUS = "PASS_TIME_OF_DAY_ONLY_STEP3"
STOP_STATUS = "STOP_TIME_OF_DAY_ONLY_STEP3"
INTERACTION_STATUS = "STOP_REPORTED_R0015"
PRIMARY_ESTIMAND = (
    "late_afternoon_16_18_minus_late_morning_10_12_cooling_contrast_k"
)
MORNING_STRATUM = "10-12"
AFTERNOON_STRATUM = "16-18"
PRIMARY_STRATA = (MORNING_STRATUM, AFTERNOON_STRATUM)
EXPECTED_CITIES = (
    "atlanta",
    "los_angeles",
    "miami",
    "minneapolis_st_paul",
    "phoenix",
)
PERMITTED_NON_PHOENIX_HOLDOUTS = tuple(
    city for city in EXPECTED_CITIES if city != "phoenix"
)


@dataclass(frozen=True)
class TimeOfDaySimulationSpec:
    """Frozen D0056 planning values, inherited numerically from D0021."""

    seed: int = 20260801
    alpha: float = 0.05
    target_power: float = 0.80
    effect_sizes_k: tuple[float, ...] = (0.75, 1.50, 2.25)
    primary_effect_size_k: float = 1.50
    rows_per_pass: int = 24
    matched_sets_per_pass: int = 6
    pass_sd_k: float = 0.80
    matched_set_sd_k: float = 0.50
    row_sd_k: float = 1.50
    solar_zenith_effect_k: float = 0.30
    solar_azimuth_sin_effect_k: float = 0.12
    solar_azimuth_cos_effect_k: float = -0.08
    demand_effect_k: float = -0.45
    dryness_main_effect_k: float = -0.35
    season_effect_k: float = 0.20

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "TimeOfDaySimulationSpec":
        fields = {
            name: values[name]
            for name in cls.__dataclass_fields__
            if name in values
        }
        if "effect_sizes_k" in fields:
            fields["effect_sizes_k"] = tuple(
                float(value) for value in fields["effect_sizes_k"]
            )
        return cls(**fields)

    def validate(self) -> None:
        if not 0 < self.alpha < 1 or not 0 < self.target_power < 1:
            raise ValueError("alpha and target_power must lie in (0, 1)")
        if self.rows_per_pass < self.matched_sets_per_pass:
            raise ValueError("rows_per_pass must be at least matched_sets_per_pass")
        if self.matched_sets_per_pass < 1:
            raise ValueError("matched_sets_per_pass must be positive")
        if any(value <= 0 for value in self.effect_sizes_k):
            raise ValueError("effect sizes must be positive")
        if self.primary_effect_size_k not in self.effect_sizes_k:
            raise ValueError("primary effect must be included in effect_sizes_k")
        numeric = [
            self.pass_sd_k,
            self.matched_set_sd_k,
            self.row_sd_k,
            self.solar_zenith_effect_k,
            self.solar_azimuth_sin_effect_k,
            self.solar_azimuth_cos_effect_k,
            self.demand_effect_k,
            self.dryness_main_effect_k,
            self.season_effect_k,
        ]
        if not np.isfinite(numeric).all() or min(numeric[:3]) < 0:
            raise ValueError("simulation variances/effects must be finite and valid")


@dataclass(frozen=True)
class TimeOfDayDiagnosticThresholds:
    """Frozen D0056 checks, numerically preserving D0027 tolerances."""

    large_n_max_abs_bias_k: float = 0.20
    null_rate_max: float = 0.10
    block_bootstrap_coverage_min: float = 0.90
    naive_coverage_gap_min: float = 0.10
    nominal_coverage: float = 0.95
    interval_alpha: float = 0.05

    @classmethod
    def from_mapping(
        cls, values: Mapping[str, Any]
    ) -> "TimeOfDayDiagnosticThresholds":
        fields = {
            name: values[name]
            for name in cls.__dataclass_fields__
            if name in values
        }
        return cls(**fields)

    def validate(self) -> None:
        if self.large_n_max_abs_bias_k < 0:
            raise ValueError("large_n_max_abs_bias_k must be nonnegative")
        for name in (
            "null_rate_max",
            "block_bootstrap_coverage_min",
            "naive_coverage_gap_min",
            "nominal_coverage",
            "interval_alpha",
        ):
            if not 0 < float(getattr(self, name)) < 1:
                raise ValueError(f"{name} must lie in (0, 1)")


@dataclass(frozen=True)
class TimeContrastFit:
    estimate: float
    std_error: float
    ci_low: float
    ci_high: float
    p_value: float
    n_rows: int
    n_passes: int
    covariance: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def validate_time_template(template: pd.DataFrame) -> pd.DataFrame:
    """Normalize the certified Step-2 template and attach frozen time strata."""

    validated = validate_step3_template(template)
    if set(validated["template_geometry_status"].astype(str)) != {
        OBSERVED_GEOMETRY_STATUS
    }:
        raise ValueError("D0056 requires observed solar geometry on every pass")
    if "sampling_weight" not in validated:
        raise ValueError("D0056 requires candidate-specific cloud-survival weights")
    if "source_date" not in validated:
        raise ValueError("D0056 requires source_date for the season control")
    validated = validated.copy()
    validated["time_stratum"] = assign_time_stratum(
        validated["local_solar_time"]
    ).to_numpy()
    if validated["time_stratum"].isna().any():
        raise ValueError("D0056 template contains a pass outside 10:00--18:00")
    unexpected_cities = sorted(set(validated["city"]) - set(EXPECTED_CITIES))
    if unexpected_cities:
        raise ValueError(f"unexpected cities in D0056 template: {unexpected_cities}")
    parsed_dates = pd.to_datetime(validated["source_date"], errors="coerce")
    if parsed_dates.isna().any():
        raise ValueError("D0056 source_date contains an invalid date")
    validated["day_of_year_c"] = (
        parsed_dates.dt.dayofyear.to_numpy(dtype=float) - 213.0
    ) / 62.0
    return validated


def empirical_strata_census(template: pd.DataFrame) -> pd.DataFrame:
    """Return every city x frozen daytime-stratum count, including zeros."""

    validated = validate_time_template(template)
    index = pd.MultiIndex.from_product(
        [EXPECTED_CITIES, TIME_STRATA], names=["city", "time_stratum"]
    )
    census = (
        validated.groupby(["city", "time_stratum"], observed=True)
        .agg(
            physical_passes=("source_pass_id", "size"),
            expected_pass_equivalents=("sampling_weight", "sum"),
        )
        .reindex(index, fill_value=0)
        .reset_index()
    )
    census["physical_passes"] = census["physical_passes"].astype(int)
    census["is_primary_contrast_stratum"] = census["time_stratum"].isin(
        PRIMARY_STRATA
    )
    return census


def primary_contrast_template(
    template: pd.DataFrame, *, excluded_city: str | None = None
) -> pd.DataFrame:
    """Select the two strata that directly identify the primary endpoint."""

    validated = validate_time_template(template)
    selected = validated.loc[validated["time_stratum"].isin(PRIMARY_STRATA)].copy()
    if excluded_city is not None:
        if excluded_city not in PERMITTED_NON_PHOENIX_HOLDOUTS:
            raise ValueError("excluded_city must be a permitted non-Phoenix holdout")
        selected = selected.loc[selected["city"].ne(excluded_city)].copy()
    if selected.empty:
        raise ValueError("primary time-of-day template is empty")
    groups = selected.groupby(["city", "time_stratum"], observed=True)[
        "sampling_weight"
    ].sum()
    expected_cities = set(EXPECTED_CITIES) - (
        {excluded_city} if excluded_city is not None else set()
    )
    required = {
        (city, stratum) for city in expected_cities for stratum in PRIMARY_STRATA
    }
    missing = sorted(key for key in required if float(groups.get(key, 0.0)) <= 0)
    if missing:
        raise ValueError(f"primary time-of-day strata have no support: {missing}")
    return selected.reset_index(drop=True)


def leave_one_city_out_census(template: pd.DataFrame) -> pd.DataFrame:
    """Outcome-blind support available under every permitted holdout choice."""

    rows: list[dict[str, Any]] = []
    for city in PERMITTED_NON_PHOENIX_HOLDOUTS:
        selected = primary_contrast_template(template, excluded_city=city)
        expected = float(selected["sampling_weight"].sum())
        rows.append(
            {
                "excluded_city": city,
                "physical_passes": int(len(selected)),
                "expected_pass_equivalents": expected,
                "planning_n": math.floor(expected),
            }
        )
    return pd.DataFrame(rows)


def _largest_remainder_allocation(weights: np.ndarray, total: int) -> np.ndarray:
    if total < 1:
        raise ValueError("simulation pass count must be positive")
    weights = np.asarray(weights, dtype=float)
    if (
        len(weights) == 0
        or not np.isfinite(weights).all()
        or (weights <= 0).any()
        or float(weights.sum()) <= 0
    ):
        raise ValueError("stratum allocation weights must be finite and positive")
    quotas = total * weights / weights.sum()
    allocation = np.floor(quotas).astype(int)
    remaining = total - int(allocation.sum())
    if remaining:
        order = np.argsort(-(quotas - allocation), kind="stable")
        allocation[order[:remaining]] += 1
    if int(allocation.sum()) != total:
        raise AssertionError("largest-remainder allocation lost passes")
    return allocation


def sample_primary_passes(
    template: pd.DataFrame,
    n_passes: int,
    rng: np.random.Generator,
    *,
    excluded_city: str | None = None,
) -> pd.DataFrame:
    """Cloud-weighted, city x stratum stratified pass resampling."""

    selected = primary_contrast_template(template, excluded_city=excluded_city)
    grouped = list(selected.groupby(["city", "time_stratum"], sort=True, observed=True))
    group_weights = np.asarray(
        [float(group["sampling_weight"].sum()) for _, group in grouped]
    )
    allocation = _largest_remainder_allocation(group_weights, int(n_passes))
    chunks: list[pd.DataFrame] = []
    for (_, group), count in zip(grouped, allocation, strict=True):
        if count == 0:
            continue
        positive = group.loc[group["sampling_weight"].gt(0)].copy()
        if positive.empty:
            raise ValueError("a primary city-stratum has no positive-weight pass")
        probabilities = positive["sampling_weight"].to_numpy(dtype=float)
        probabilities /= probabilities.sum()
        chosen = rng.choice(
            len(positive),
            size=int(count),
            replace=bool(count > len(positive)),
            p=probabilities,
        )
        chunks.append(positive.iloc[chosen].copy())
    sampled = pd.concat(chunks, ignore_index=True)
    sampled = sampled.iloc[rng.permutation(len(sampled))].reset_index(drop=True)
    sampled["pass_id"] = [f"pass_{index:05d}" for index in range(len(sampled))]
    if len(sampled) != n_passes:
        raise AssertionError("stratified sampler returned the wrong pass count")
    return sampled


def simulate_clustered_time_of_day_data(
    template: pd.DataFrame,
    n_passes: int,
    effect_k: float,
    spec: TimeOfDaySimulationSpec,
    rng: np.random.Generator,
    *,
    excluded_city: str | None = None,
) -> pd.DataFrame:
    """Simulate rows nested in matched sets and passes with a known TOD effect."""

    spec.validate()
    base = sample_primary_passes(
        template, n_passes, rng, excluded_city=excluded_city
    )
    rows_per_set = int(math.ceil(spec.rows_per_pass / spec.matched_sets_per_pass))
    set_ids_one_pass = np.repeat(
        np.arange(spec.matched_sets_per_pass), rows_per_set
    )[: spec.rows_per_pass]
    row_pass = np.repeat(np.arange(n_passes), spec.rows_per_pass)
    set_ids = np.tile(set_ids_one_pass, n_passes)
    n_total = n_passes * spec.rows_per_pass

    late = base["time_stratum"].astype(str).eq(AFTERNOON_STRATUM).to_numpy(float)
    demand = base["demand_pct"].to_numpy(float) - 0.5
    dryness = base["dryness_pct"].to_numpy(float) - 0.5
    zenith = (base["solar_zenith_deg"].to_numpy(float) - 45.0) / 45.0
    azimuth = np.deg2rad(base["solar_azimuth_deg"].to_numpy(float))
    azimuth_sin = np.sin(azimuth)
    azimuth_cos = np.cos(azimuth)
    season = base["day_of_year_c"].to_numpy(float)
    city_order = {city: value for city, value in zip(EXPECTED_CITIES, np.linspace(-0.3, 0.3, 5), strict=True)}
    city_effect = base["city"].map(city_order).to_numpy(float)

    pass_noise = rng.normal(0.0, spec.pass_sd_k, n_passes)
    set_noise = rng.normal(
        0.0, spec.matched_set_sd_k, (n_passes, spec.matched_sets_per_pass)
    )
    row_noise = rng.normal(0.0, spec.row_sd_k, n_total)
    pass_mean = (
        3.0
        + float(effect_k) * late
        + spec.demand_effect_k * demand
        + spec.dryness_main_effect_k * dryness
        + spec.solar_zenith_effect_k * zenith
        + spec.solar_azimuth_sin_effect_k * azimuth_sin
        + spec.solar_azimuth_cos_effect_k * azimuth_cos
        + spec.season_effect_k * season
        + city_effect
        + pass_noise
    )
    outcome = (
        pass_mean[row_pass]
        + set_noise[row_pass, set_ids]
        + row_noise
    )
    base_city = base["city"].astype(str).to_numpy()
    base_stratum = base["time_stratum"].astype(str).to_numpy()
    base_pass = base["pass_id"].astype(str).to_numpy()
    base_source = base["source_pass_id"].astype(str).to_numpy()
    return pd.DataFrame(
        {
            "pass_id": base_pass[row_pass],
            "source_pass_id": base_source[row_pass],
            "matched_set_id": [
                f"{base_pass[pass_index]}_set_{set_index}"
                for pass_index, set_index in zip(row_pass, set_ids, strict=True)
            ],
            "city": base_city[row_pass],
            "time_stratum": base_stratum[row_pass],
            "late_afternoon": late[row_pass],
            "demand_c": demand[row_pass],
            "dryness_c": dryness[row_pass],
            "solar_zenith_c": zenith[row_pass],
            "solar_azimuth_sin": azimuth_sin[row_pass],
            "solar_azimuth_cos": azimuth_cos[row_pass],
            "day_of_year_c": season[row_pass],
            "cooling_contrast_k": outcome,
        }
    )


def _design_matrix(data: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    columns = [
        np.ones(len(data)),
        data["late_afternoon"].to_numpy(float),
        data["demand_c"].to_numpy(float),
        data["dryness_c"].to_numpy(float),
        data["solar_zenith_c"].to_numpy(float),
        data["solar_azimuth_sin"].to_numpy(float),
        data["solar_azimuth_cos"].to_numpy(float),
        data["day_of_year_c"].to_numpy(float),
    ]
    names = [
        "intercept",
        "late_afternoon",
        "demand_c",
        "dryness_c",
        "solar_zenith_c",
        "solar_azimuth_sin",
        "solar_azimuth_cos",
        "day_of_year_c",
    ]
    city_values = sorted(pd.unique(data["city"].astype(str)))
    for city in city_values[1:]:
        columns.append(data["city"].astype(str).eq(city).to_numpy(float))
        names.append(f"city_{city}")
    return np.column_stack(columns), names


def _ols_covariance(
    x: np.ndarray, residual: np.ndarray, clusters: np.ndarray | None
) -> tuple[np.ndarray, int, str]:
    n, k = x.shape
    bread = np.linalg.pinv(x.T @ x)
    if clusters is None:
        df = max(n - k, 1)
        sigma2 = float(residual @ residual) / df
        return sigma2 * bread, df, "naive_row"
    unique = pd.unique(clusters)
    g = len(unique)
    if g < 2:
        raise ValueError("pass-cluster covariance requires at least two passes")
    meat = np.zeros((k, k), dtype=float)
    for cluster in unique:
        mask = clusters == cluster
        score = x[mask].T @ residual[mask]
        meat += np.outer(score, score)
    correction = (g / (g - 1)) * ((n - 1) / max(n - k, 1))
    return correction * bread @ meat @ bread, g - 1, "pass_cluster"


def fit_time_contrast(
    data: pd.DataFrame, *, covariance: str = "pass_cluster"
) -> TimeContrastFit:
    """Fit the categorical late-afternoon minus late-morning coefficient."""

    required = {
        "pass_id",
        "city",
        "late_afternoon",
        "demand_c",
        "dryness_c",
        "solar_zenith_c",
        "solar_azimuth_sin",
        "solar_azimuth_cos",
        "day_of_year_c",
        "cooling_contrast_k",
    }
    missing = required - set(data)
    if missing:
        raise ValueError(f"time-of-day model data lack {sorted(missing)}")
    clean = data.dropna(subset=list(required)).copy()
    x, names = _design_matrix(clean)
    if np.linalg.matrix_rank(x) < x.shape[1]:
        raise ValueError("time-of-day model design is rank deficient")
    y = clean["cooling_contrast_k"].to_numpy(float)
    beta = np.linalg.pinv(x) @ y
    residual = y - x @ beta
    if covariance == "pass_cluster":
        clusters: np.ndarray | None = clean["pass_id"].to_numpy()
    elif covariance == "naive_row":
        clusters = None
    else:
        raise ValueError("covariance must be pass_cluster or naive_row")
    cov, df, covariance_name = _ols_covariance(x, residual, clusters)
    index = names.index("late_afternoon")
    estimate = float(beta[index])
    se = float(np.sqrt(max(cov[index, index], 0.0)))
    critical = float(stats.t.ppf(0.975, df))
    p_value = (
        1.0
        if se == 0 and estimate == 0
        else 0.0
        if se == 0
        else float(2 * stats.t.sf(abs(estimate / se), df))
    )
    return TimeContrastFit(
        estimate=estimate,
        std_error=se,
        ci_low=estimate - critical * se,
        ci_high=estimate + critical * se,
        p_value=p_value,
        n_rows=len(clean),
        n_passes=clean["pass_id"].nunique(),
        covariance=covariance_name,
    )


def bootstrap_interval(
    data: pd.DataFrame,
    *,
    method: str,
    n_boot: int,
    rng: np.random.Generator,
) -> tuple[float, float]:
    """Percentile interval from whole-pass or deliberately naive row draws."""

    if method not in {"pass", "row"}:
        raise ValueError("bootstrap method must be pass or row")
    if n_boot < 10:
        raise ValueError("n_boot must be at least ten")
    base = data.reset_index(drop=True)
    x, names = _design_matrix(base)
    y = base["cooling_contrast_k"].to_numpy(float)
    term_index = names.index("late_afternoon")

    def coefficient(xtx: np.ndarray, xty: np.ndarray) -> float:
        return float((np.linalg.pinv(xtx) @ xty)[term_index])

    estimates: list[float] = []
    if method == "pass":
        pass_ids = pd.unique(base["pass_id"])
        row_pass_ids = base["pass_id"].to_numpy()
        block_xtx = []
        block_xty = []
        for pass_id in pass_ids:
            mask = row_pass_ids == pass_id
            block_x = x[mask]
            block_y = y[mask]
            block_xtx.append(block_x.T @ block_x)
            block_xty.append(block_x.T @ block_y)
        block_xtx_array = np.asarray(block_xtx)
        block_xty_array = np.asarray(block_xty)
        for _ in range(n_boot):
            selected = rng.integers(0, len(pass_ids), len(pass_ids))
            estimates.append(
                coefficient(
                    block_xtx_array[selected].sum(axis=0),
                    block_xty_array[selected].sum(axis=0),
                )
            )
    else:
        for _ in range(n_boot):
            selected = rng.integers(0, len(base), len(base))
            sample_x = x[selected]
            estimates.append(coefficient(sample_x.T @ sample_x, sample_x.T @ y[selected]))
    finite = np.asarray(estimates, dtype=float)
    finite = finite[np.isfinite(finite)]
    if len(finite) < max(10, n_boot // 2):
        return np.nan, np.nan
    low, high = np.quantile(finite, [0.025, 0.975])
    return float(low), float(high)


def _binomial_wilson(
    successes: int, trials: int, *, alpha: float = 0.05
) -> tuple[float, float]:
    if trials <= 0 or successes < 0 or successes > trials:
        raise ValueError("invalid binomial counts")
    z = float(stats.norm.ppf(1 - alpha / 2))
    probability = successes / trials
    denominator = 1 + z * z / trials
    center = (probability + z * z / (2 * trials)) / denominator
    radius = (
        z
        * math.sqrt(
            probability * (1 - probability) / trials
            + z * z / (4 * trials * trials)
        )
        / denominator
    )
    return center - radius, center + radius


def _rate_summary(
    frame: pd.DataFrame,
    group_columns: Sequence[str],
    *,
    rate_name: str,
    interval_alpha: float,
) -> pd.DataFrame:
    summary = (
        frame.groupby(list(group_columns), as_index=False, observed=True)["detected"]
        .agg(n_replicates="size", n_detected="sum")
    )
    summary[rate_name] = summary["n_detected"] / summary["n_replicates"]
    intervals = [
        _binomial_wilson(
            int(row.n_detected), int(row.n_replicates), alpha=interval_alpha
        )
        for row in summary.itertuples(index=False)
    ]
    summary[f"{rate_name}_mc_ci_low"] = [value[0] for value in intervals]
    summary[f"{rate_name}_mc_ci_high"] = [value[1] for value in intervals]
    return summary


def run_time_of_day_simulation_study(
    template: pd.DataFrame,
    *,
    pass_counts: Sequence[int],
    spec: TimeOfDaySimulationSpec = TimeOfDaySimulationSpec(),
    n_replicates: int = 200,
    n_coverage_replicates: int = 60,
    n_boot: int = 120,
    input_eligible: bool = False,
    interaction_stop_preserved: bool = False,
) -> dict[str, Any]:
    """Run full-panel and every permitted-holdout planning simulations."""

    spec.validate()
    if n_replicates < 1 or n_coverage_replicates < 1 or n_boot < 10:
        raise ValueError("replicate counts must be positive and n_boot at least ten")
    validated = validate_time_template(template)
    census = empirical_strata_census(validated)
    full_primary = primary_contrast_template(validated)
    full_expected = float(full_primary["sampling_weight"].sum())
    full_n = math.floor(full_expected)
    if full_n < 20:
        raise ValueError("full-panel primary-contrast planning count is too small")
    loco_census = leave_one_city_out_census(validated)
    counts = sorted(
        set(
            int(value)
            for value in (
                *pass_counts,
                full_n,
                *loco_census["planning_n"].astype(int).tolist(),
            )
        )
    )
    if any(value < 20 for value in counts):
        raise ValueError("every time-of-day simulation count must be at least 20")
    rng = np.random.default_rng(spec.seed)

    power_rows: list[dict[str, Any]] = []
    for n_passes in counts:
        for effect in spec.effect_sizes_k:
            for replicate in range(n_replicates):
                data = simulate_clustered_time_of_day_data(
                    validated, n_passes, effect, spec, rng
                )
                fit = fit_time_contrast(data)
                power_rows.append(
                    {
                        "n_passes": n_passes,
                        "effect_size_k": effect,
                        "replicate": replicate,
                        "estimate_k": fit.estimate,
                        "std_error_k": fit.std_error,
                        "ci_low_k": fit.ci_low,
                        "ci_high_k": fit.ci_high,
                        "p_value": fit.p_value,
                        "detected": fit.p_value < spec.alpha,
                    }
                )

    null_rows: list[dict[str, Any]] = []
    for n_passes in counts:
        for replicate in range(n_replicates):
            data = simulate_clustered_time_of_day_data(
                validated, n_passes, 0.0, spec, rng
            )
            fit = fit_time_contrast(data)
            null_rows.append(
                {
                    "n_passes": n_passes,
                    "replicate": replicate,
                    "estimate_k": fit.estimate,
                    "p_value": fit.p_value,
                    "detected": fit.p_value < spec.alpha,
                }
            )

    coverage_rows: list[dict[str, Any]] = []
    for replicate in range(n_coverage_replicates):
        data = simulate_clustered_time_of_day_data(
            validated, full_n, spec.primary_effect_size_k, spec, rng
        )
        for method, label in (
            ("pass", "pass-level block bootstrap"),
            ("row", "naive row bootstrap"),
        ):
            low, high = bootstrap_interval(
                data, method=method, n_boot=n_boot, rng=rng
            )
            coverage_rows.append(
                {
                    "n_passes": full_n,
                    "replicate": replicate,
                    "method": label,
                    "ci_low_k": low,
                    "ci_high_k": high,
                    "true_effect_k": spec.primary_effect_size_k,
                    "covered": bool(
                        np.isfinite(low)
                        and low <= spec.primary_effect_size_k <= high
                    ),
                }
            )

    holdout_rows: list[dict[str, Any]] = []
    for census_row in loco_census.itertuples(index=False):
        detected: list[bool] = []
        estimates: list[float] = []
        for _ in range(n_replicates):
            data = simulate_clustered_time_of_day_data(
                validated,
                int(census_row.planning_n),
                spec.primary_effect_size_k,
                spec,
                rng,
                excluded_city=str(census_row.excluded_city),
            )
            fit = fit_time_contrast(data)
            detected.append(fit.p_value < spec.alpha)
            estimates.append(fit.estimate)
        successes = int(sum(detected))
        interval = _binomial_wilson(
            successes, n_replicates, alpha=0.05
        )
        power = successes / n_replicates
        holdout_rows.append(
            {
                "excluded_city": str(census_row.excluded_city),
                "physical_passes": int(census_row.physical_passes),
                "expected_pass_equivalents": float(
                    census_row.expected_pass_equivalents
                ),
                "planning_n": int(census_row.planning_n),
                "effect_size_k": spec.primary_effect_size_k,
                "n_replicates": n_replicates,
                "mean_estimate_k": float(np.mean(estimates)),
                "power_at_primary_effect": power,
                "power_mc_ci_low": interval[0],
                "power_mc_ci_high": interval[1],
                "target_power": spec.target_power,
                "statistically_supportable": power >= spec.target_power,
                "scientific_gate_eligible": bool(input_eligible),
            }
        )

    return {
        "spec": spec,
        "template": validated,
        "strata_census": census,
        "full_panel_primary_contrast_physical_passes": int(len(full_primary)),
        "full_panel_primary_contrast_expected_pass_equivalents": full_expected,
        "full_panel_primary_contrast_planning_n": full_n,
        "total_eligible_physical_passes": int(len(validated)),
        "total_expected_pass_equivalents": float(
            validated["sampling_weight"].sum()
        ),
        "total_planning_n": math.floor(float(validated["sampling_weight"].sum())),
        "power": pd.DataFrame(power_rows),
        "null": pd.DataFrame(null_rows),
        "coverage": pd.DataFrame(coverage_rows),
        "leave_one_city_out": pd.DataFrame(holdout_rows),
        "input_eligible": bool(input_eligible),
        "interaction_stop_preserved": bool(interaction_stop_preserved),
        "pass_counts": counts,
        "run_settings": {
            "n_replicates": int(n_replicates),
            "n_coverage_replicates": int(n_coverage_replicates),
            "n_boot": int(n_boot),
        },
    }


def summarize_model_support(results: Mapping[str, Any]) -> pd.DataFrame:
    spec: TimeOfDaySimulationSpec = results["spec"]
    power = _rate_summary(
        results["power"],
        ("effect_size_k", "n_passes"),
        rate_name="power",
        interval_alpha=0.05,
    )
    planning_n = int(results["full_panel_primary_contrast_planning_n"])
    rows: list[dict[str, Any]] = []
    for effect in spec.effect_sizes_k:
        subset = power.loc[np.isclose(power["effect_size_k"], effect)].sort_values(
            "n_passes"
        )
        at_planning = subset.loc[subset["n_passes"].eq(planning_n)].iloc[0]
        meeting = subset.loc[subset["power"].ge(spec.target_power), "n_passes"]
        rows.append(
            {
                "model": "pass_clustered_late_afternoon_minus_late_morning",
                "primary_estimand": PRIMARY_ESTIMAND,
                "effect_size_k": float(effect),
                "minimum_passes_for_target_power": (
                    int(meeting.iloc[0]) if len(meeting) else np.nan
                ),
                "full_panel_primary_contrast_planning_n": planning_n,
                "power_at_planning_n": float(at_planning["power"]),
                "power_mc_ci_low": float(at_planning["power_mc_ci_low"]),
                "power_mc_ci_high": float(at_planning["power_mc_ci_high"]),
                "target_power": spec.target_power,
                "statistically_supportable_at_planning_n": bool(
                    at_planning["power"] >= spec.target_power
                ),
                "scientific_gate_eligible": bool(results["input_eligible"]),
                "interaction_status": INTERACTION_STATUS,
            }
        )
    frame = pd.DataFrame(rows)
    detectable = frame.loc[
        frame["statistically_supportable_at_planning_n"], "effect_size_k"
    ]
    frame["smallest_detectable_effect_at_planning_n_k"] = (
        float(detectable.min()) if len(detectable) else np.nan
    )
    return frame


def evaluate_time_of_day_gate(
    results: Mapping[str, Any],
    thresholds: TimeOfDayDiagnosticThresholds = TimeOfDayDiagnosticThresholds(),
) -> dict[str, Any]:
    """Evaluate the frozen D0056 nonthermal gate, including every holdout choice."""

    thresholds.validate()
    spec: TimeOfDaySimulationSpec = results["spec"]
    rows: list[dict[str, Any]] = []

    def add(
        check_id: str,
        category: str,
        criterion: str,
        observed_value: float,
        passed: bool,
        *,
        n_monte_carlo: int | None = None,
        mc_ci_low: float | None = None,
        mc_ci_high: float | None = None,
        detail: str = "",
    ) -> None:
        rows.append(
            {
                "check_id": check_id,
                "category": category,
                "criterion": criterion,
                "observed_value": float(observed_value),
                "n_monte_carlo": n_monte_carlo,
                "mc_ci_low": mc_ci_low,
                "mc_ci_high": mc_ci_high,
                "passed": bool(passed),
                "required_for_gate": True,
                "detail": detail,
            }
        )

    input_eligible = bool(results["input_eligible"])
    add(
        "certified_nonthermal_inputs",
        "eligibility",
        "checksum-bound D0047 nonthermal inputs",
        float(input_eligible),
        input_eligible,
    )
    interaction_stop = bool(results["interaction_stop_preserved"])
    add(
        "interaction_stop_preserved",
        "scope",
        "R0015 interaction STOP remains binding",
        float(interaction_stop),
        interaction_stop,
        detail=INTERACTION_STATUS,
    )
    census: pd.DataFrame = results["strata_census"]
    primary_cells = census.loc[census["is_primary_contrast_stratum"]]
    primary_complete = bool(
        len(primary_cells) == len(EXPECTED_CITIES) * 2
        and primary_cells["physical_passes"].gt(0).all()
        and primary_cells["expected_pass_equivalents"].gt(0).all()
    )
    add(
        "primary_city_strata_observed",
        "support",
        "both primary strata have positive support in every city",
        float(primary_complete),
        primary_complete,
    )

    power_summary = _rate_summary(
        results["power"],
        ("effect_size_k", "n_passes"),
        rate_name="power",
        interval_alpha=thresholds.interval_alpha,
    )
    planning_n = int(results["full_panel_primary_contrast_planning_n"])
    primary = power_summary.loc[
        power_summary["n_passes"].eq(planning_n)
        & np.isclose(power_summary["effect_size_k"], spec.primary_effect_size_k)
    ].iloc[0]
    add(
        "full_panel_primary_effect_power",
        "power",
        f"power >= {spec.target_power:.3f} at full-panel primary n={planning_n}",
        float(primary["power"]),
        bool(primary["power"] >= spec.target_power),
        n_monte_carlo=int(primary["n_replicates"]),
        mc_ci_low=float(primary["power_mc_ci_low"]),
        mc_ci_high=float(primary["power_mc_ci_high"]),
        detail=f"effect_size_k={spec.primary_effect_size_k:g}",
    )

    holdout = results["leave_one_city_out"]
    all_holdouts = bool(
        set(holdout["excluded_city"]) == set(PERMITTED_NON_PHOENIX_HOLDOUTS)
        and holdout["statistically_supportable"].all()
    )
    add(
        "all_permitted_non_phoenix_holdouts_power",
        "power",
        "primary effect reaches target power after every permitted holdout exclusion",
        float(all_holdouts),
        all_holdouts,
        n_monte_carlo=int(holdout["n_replicates"].sum()),
        detail=(
            "powers="
            + json.dumps(
                dict(
                    zip(
                        holdout["excluded_city"],
                        holdout["power_at_primary_effect"],
                        strict=True,
                    )
                ),
                sort_keys=True,
            )
        ),
    )

    large_n = int(results["power"]["n_passes"].max())
    for effect in spec.effect_sizes_k:
        subset = results["power"].loc[
            results["power"]["n_passes"].eq(large_n)
            & np.isclose(results["power"]["effect_size_k"], effect)
        ]
        bias = abs(float(subset["estimate_k"].mean()) - float(effect))
        add(
            f"large_n_bias_{effect:g}k".replace(".", "p"),
            "coefficient_recovery",
            f"absolute mean bias <= {thresholds.large_n_max_abs_bias_k:.3f} K",
            bias,
            bias <= thresholds.large_n_max_abs_bias_k,
            n_monte_carlo=len(subset),
            detail=f"large_n={large_n}",
        )

    null = results["null"]
    null_successes = int(null["detected"].sum())
    null_total = int(len(null))
    null_rate = null_successes / null_total
    null_interval = _binomial_wilson(
        null_successes, null_total, alpha=thresholds.interval_alpha
    )
    null_pass = bool(
        null_rate <= thresholds.null_rate_max
        and null_interval[0] <= spec.alpha <= null_interval[1]
    )
    add(
        "pooled_time_of_day_null_rate",
        "false_positive_control",
        (
            f"rate <= {thresholds.null_rate_max:.3f} and Wilson interval contains "
            f"alpha={spec.alpha:.3f}"
        ),
        null_rate,
        null_pass,
        n_monte_carlo=null_total,
        mc_ci_low=null_interval[0],
        mc_ci_high=null_interval[1],
    )

    coverage: pd.DataFrame = results["coverage"]
    coverage_values: dict[str, tuple[float, tuple[float, float], int]] = {}
    for method in ("pass-level block bootstrap", "naive row bootstrap"):
        subset = coverage.loc[coverage["method"].eq(method)]
        successes = int(subset["covered"].sum())
        total = int(len(subset))
        interval = _binomial_wilson(
            successes, total, alpha=thresholds.interval_alpha
        )
        coverage_values[method] = (successes / total, interval, total)
    block_rate, block_interval, block_total = coverage_values[
        "pass-level block bootstrap"
    ]
    block_pass = bool(
        block_rate >= thresholds.block_bootstrap_coverage_min
        and block_interval[0]
        <= thresholds.nominal_coverage
        <= block_interval[1]
    )
    add(
        "planning_count_block_coverage",
        "coverage",
        (
            f"pass-block coverage >= {thresholds.block_bootstrap_coverage_min:.3f} "
            f"and interval contains {thresholds.nominal_coverage:.3f}"
        ),
        block_rate,
        block_pass,
        n_monte_carlo=block_total,
        mc_ci_low=block_interval[0],
        mc_ci_high=block_interval[1],
    )
    naive_rate = coverage_values["naive row bootstrap"][0]
    gap = block_rate - naive_rate
    add(
        "planning_count_naive_coverage_gap",
        "coverage",
        f"pass-block minus naive-row coverage >= {thresholds.naive_coverage_gap_min:.3f}",
        gap,
        gap >= thresholds.naive_coverage_gap_min,
        n_monte_carlo=block_total,
        detail=f"block={block_rate:.6f}; naive={naive_rate:.6f}",
    )

    checks = pd.DataFrame(rows)
    failed = checks.loc[
        checks["required_for_gate"] & ~checks["passed"], "check_id"
    ].astype(str).tolist()
    eligible = not failed
    return {
        "summary": {
            "schema_version": 1,
            "decision_id": DECISION_ID,
            "analysis_profile": ANALYSIS_PROFILE,
            "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
            "status": PASS_STATUS if eligible else STOP_STATUS,
            "scientific_gate_eligible": eligible,
            "primary_estimand": PRIMARY_ESTIMAND,
            "interaction_status": INTERACTION_STATUS,
            "all_required_checks_pass": eligible,
            "passed_required_checks": int(checks["passed"].sum()),
            "total_required_checks": int(len(checks)),
            "failed_check_ids": failed,
            "thresholds": asdict(thresholds),
            "large_count_n_passes": large_n,
        },
        "checks": checks,
    }


def _artifact_path(
    output_relative_root: str, path: Path, output_dir: Path
) -> str:
    return str(Path(output_relative_root) / path.relative_to(output_dir))


def write_time_of_day_deliverables(
    results: Mapping[str, Any],
    output_dir: str | Path,
    *,
    output_relative_root: str,
    input_bindings: Mapping[str, Any],
    thresholds: TimeOfDayDiagnosticThresholds = TimeOfDayDiagnosticThresholds(),
) -> dict[str, Path]:
    """Write the isolated D0056 figures, tables, memo, and gate record."""

    root = Path(output_dir)
    figures = root / "figures"
    tables = root / "tables"
    figures.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)
    support = summarize_model_support(results)
    gate = evaluate_time_of_day_gate(results, thresholds)
    checks: pd.DataFrame = gate["checks"]
    holdout: pd.DataFrame = results["leave_one_city_out"]
    census: pd.DataFrame = results["strata_census"]

    paths = {
        "F3T.1": figures / "F3T.1_time_of_day_power.png",
        "F3T.2": figures / "F3T.2_time_of_day_recovery.png",
        "F3T.3": figures / "F3T.3_time_of_day_type_i_error.png",
        "F3T.4": figures / "F3T.4_time_of_day_coverage.png",
        "F3T.5": figures / "F3T.5_empirical_strata_support.png",
        "T3T.1": tables / "T3T.1_time_of_day_model_support.csv",
        "T3T.2": tables / "T3T.2_leave_one_city_out_support.csv",
        "T3T.3": tables / "T3T.3_empirical_strata_census.csv",
        "power": tables / "time_of_day_power_replicates.csv",
        "null": tables / "time_of_day_null_replicates.csv",
        "coverage": tables / "time_of_day_coverage_replicates.csv",
        "checks": tables / "step3_time_of_day_checks.csv",
        "memo": root / "M3T.1_time_of_day_power.md",
        "settings": root / "simulation_settings.json",
        "gate": root / "step3_time_of_day_gate.json",
    }
    support.to_csv(paths["T3T.1"], index=False)
    holdout.to_csv(paths["T3T.2"], index=False)
    census.to_csv(paths["T3T.3"], index=False)
    results["power"].to_csv(paths["power"], index=False)
    results["null"].to_csv(paths["null"], index=False)
    results["coverage"].to_csv(paths["coverage"], index=False)
    checks.to_csv(paths["checks"], index=False)
    settings = {
        "schema_version": 1,
        "decision_id": DECISION_ID,
        "analysis_profile": ANALYSIS_PROFILE,
        "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
        "primary_estimand": PRIMARY_ESTIMAND,
        "interaction_status": INTERACTION_STATUS,
        "simulation_spec": asdict(results["spec"]),
        "diagnostic_thresholds": asdict(thresholds),
        "pass_counts": list(results["pass_counts"]),
        **results["run_settings"],
    }
    _atomic_json(paths["settings"], settings)

    power_summary = _rate_summary(
        results["power"],
        ("effect_size_k", "n_passes"),
        rate_name="power",
        interval_alpha=0.05,
    )
    figure, axis = plt.subplots(figsize=(7.2, 4.6))
    for effect, group in power_summary.groupby("effect_size_k"):
        axis.plot(group["n_passes"], group["power"], marker="o", label=f"{effect:g} K")
    axis.axhline(results["spec"].target_power, color="0.4", linestyle=":")
    axis.axvline(
        results["full_panel_primary_contrast_planning_n"], color="#1f77b4", linestyle="--", label="full five-city N"
    )
    axis.axvline(
        int(holdout["planning_n"].min()), color="#d62728", linestyle="--", label="minimum permitted holdout N"
    )
    axis.set(
        xlabel="Pass-equivalent planning count for the primary contrast",
        ylabel="Detection probability",
        ylim=(0, 1.03),
        title="F3T.1 — Time-of-day contrast power",
    )
    axis.legend(fontsize=8)
    figure.tight_layout()
    figure.savefig(paths["F3T.1"], dpi=180, bbox_inches="tight")
    plt.close(figure)

    recovery = (
        results["power"]
        .groupby(["effect_size_k", "n_passes"], as_index=False)
        .agg(mean_estimate_k=("estimate_k", "mean"), sd_estimate_k=("estimate_k", "std"))
    )
    figure, axis = plt.subplots(figsize=(7.2, 4.6))
    for effect, group in recovery.groupby("effect_size_k"):
        axis.errorbar(
            group["n_passes"], group["mean_estimate_k"], yerr=group["sd_estimate_k"], marker="o", capsize=2, label=f"truth {effect:g} K"
        )
        axis.axhline(effect, color=axis.lines[-1].get_color(), alpha=0.25)
    axis.set(xlabel="Pass-equivalent planning count", ylabel="Estimated contrast (K)", title="F3T.2 — Coefficient recovery")
    axis.legend(fontsize=8)
    figure.tight_layout()
    figure.savefig(paths["F3T.2"], dpi=180, bbox_inches="tight")
    plt.close(figure)

    null_summary = _rate_summary(
        results["null"], ("n_passes",), rate_name="type_i_error", interval_alpha=0.05
    )
    figure, axis = plt.subplots(figsize=(7.2, 4.6))
    axis.plot(null_summary["n_passes"], null_summary["type_i_error"], marker="o")
    axis.fill_between(
        null_summary["n_passes"], null_summary["type_i_error_mc_ci_low"], null_summary["type_i_error_mc_ci_high"], alpha=0.2
    )
    axis.axhline(results["spec"].alpha, color="0.4", linestyle=":")
    axis.set(xlabel="Pass-equivalent planning count", ylabel="False-positive rate", ylim=(0, 0.2), title="F3T.3 — Null time-of-day false-positive rate")
    figure.tight_layout()
    figure.savefig(paths["F3T.3"], dpi=180, bbox_inches="tight")
    plt.close(figure)

    coverage_summary = (
        results["coverage"].groupby("method", as_index=False)["covered"].mean()
    )
    figure, axis = plt.subplots(figsize=(6.3, 4.4))
    axis.bar(coverage_summary["method"], coverage_summary["covered"], color=["#2ca02c", "#999999"])
    axis.axhline(thresholds.nominal_coverage, color="0.4", linestyle=":")
    axis.set(ylabel="Coverage", ylim=(0, 1.03), title="F3T.4 — Pass-block versus naive-row coverage")
    axis.tick_params(axis="x", rotation=12)
    figure.tight_layout()
    figure.savefig(paths["F3T.4"], dpi=180, bbox_inches="tight")
    plt.close(figure)

    pivot = census.pivot(index="city", columns="time_stratum", values="expected_pass_equivalents").reindex(columns=TIME_STRATA)
    figure, axis = plt.subplots(figsize=(7.5, 4.4))
    image = axis.imshow(pivot.to_numpy(), aspect="auto", cmap="viridis")
    axis.set_xticks(range(len(TIME_STRATA)), TIME_STRATA)
    axis.set_yticks(range(len(pivot.index)), pivot.index)
    for row_index in range(len(pivot.index)):
        for column_index in range(len(TIME_STRATA)):
            value = float(pivot.iloc[row_index, column_index])
            axis.text(column_index, row_index, f"{value:.1f}", ha="center", va="center", color="white" if value > 7 else "black", fontsize=8)
    axis.set(title="F3T.5 — Empirical expected pass-equivalents by time stratum", xlabel="Local solar time", ylabel="City")
    figure.colorbar(image, ax=axis, label="Expected pass-equivalents")
    figure.tight_layout()
    figure.savefig(paths["F3T.5"], dpi=180, bbox_inches="tight")
    plt.close(figure)

    gate_summary = gate["summary"]
    memo = (
        "# M3T.1 — Time-of-day-only Step 3 power gate\n\n"
        f"**Gate: {gate_summary['status']}.**\n\n"
        "The demand-by-antecedent-dryness interaction remains stopped and was not "
        "simulated as an estimable scientific target. This branch powers only the "
        "late-afternoon minus late-morning cooling contrast.\n\n"
        f"- Full five-city primary-contrast planning N: **{results['full_panel_primary_contrast_planning_n']}** "
        f"from {results['full_panel_primary_contrast_expected_pass_equivalents']:.3f} expected pass-equivalents.\n"
        f"- Minimum planning N after any permitted non-Phoenix holdout: **{int(holdout['planning_n'].min())}**.\n"
        f"- Required checks passed: **{gate_summary['passed_required_checks']}/{gate_summary['total_required_checks']}**.\n"
        f"- Interaction status: **{INTERACTION_STATUS}**.\n\n"
        "No LST/thermal value, held-out outcome, or 2026 observation was opened.\n"
    )
    paths["memo"].write_text(memo, encoding="utf-8")

    artifact_paths = [path for key, path in paths.items() if key != "gate"]
    artifact_hashes = {
        _artifact_path(output_relative_root, path, root): _sha256(path)
        for path in artifact_paths
    }
    relative = lambda path: _artifact_path(output_relative_root, path, root)
    holdout_msp = holdout.loc[
        holdout["excluded_city"].eq("minneapolis_st_paul")
    ].iloc[0]
    check_records = (
        checks.astype(object).where(checks.notna(), None).to_dict("records")
    )
    payload = {
        **gate_summary,
        "interaction_step2_gate_status": "STOP",
        "total_eligible_physical_passes": int(results["total_eligible_physical_passes"]),
        "total_expected_pass_equivalents": float(results["total_expected_pass_equivalents"]),
        "total_planning_n": int(results["total_planning_n"]),
        "full_panel_primary_contrast_physical_passes": int(results["full_panel_primary_contrast_physical_passes"]),
        "full_panel_primary_contrast_expected_pass_equivalents": float(results["full_panel_primary_contrast_expected_pass_equivalents"]),
        "full_panel_primary_contrast_planning_n": int(results["full_panel_primary_contrast_planning_n"]),
        "minneapolis_st_paul_excluded_primary_contrast_planning_n": int(holdout_msp["planning_n"]),
        "minimum_leave_one_city_out_primary_contrast_planning_n": int(holdout["planning_n"].min()),
        "all_permitted_non_phoenix_holdouts_supported": bool(holdout["statistically_supportable"].all()),
        "model_support_path": relative(paths["T3T.1"]),
        "model_support_sha256": _sha256(paths["T3T.1"]),
        "leave_one_city_out_support_path": relative(paths["T3T.2"]),
        "leave_one_city_out_support_sha256": _sha256(paths["T3T.2"]),
        "strata_census_path": relative(paths["T3T.3"]),
        "strata_census_sha256": _sha256(paths["T3T.3"]),
        "checks_path": relative(paths["checks"]),
        "checks_sha256": _sha256(paths["checks"]),
        "checks": check_records,
        "input_bindings": dict(input_bindings),
        "artifact_sha256": artifact_hashes,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
    }
    _atomic_json(paths["gate"], payload)
    return paths


__all__ = [
    "AFTERNOON_STRATUM",
    "ANALYSIS_PROFILE",
    "DECISION_ID",
    "EXPECTED_CITIES",
    "INTERACTION_STATUS",
    "MORNING_STRATUM",
    "PASS_STATUS",
    "PERMITTED_NON_PHOENIX_HOLDOUTS",
    "PRIMARY_ESTIMAND",
    "SCIENTIFIC_GATE_SCOPE",
    "STOP_STATUS",
    "TimeContrastFit",
    "TimeOfDayDiagnosticThresholds",
    "TimeOfDaySimulationSpec",
    "bootstrap_interval",
    "empirical_strata_census",
    "evaluate_time_of_day_gate",
    "fit_time_contrast",
    "leave_one_city_out_census",
    "primary_contrast_template",
    "run_time_of_day_simulation_study",
    "sample_primary_passes",
    "simulate_clustered_time_of_day_data",
    "summarize_model_support",
    "validate_time_template",
    "write_time_of_day_deliverables",
]
