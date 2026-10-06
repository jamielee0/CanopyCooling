#!/usr/bin/env python3
"""Guide Step 3: clustered simulation, power, transition error, and coverage.

The weather predictors live at pass level while matched observations repeat inside
passes.  The simulator therefore makes the pass the independent sampling unit and
fits a pass-cluster sandwich covariance.  A row bootstrap is retained only as the
deliberately naive comparator requested by F3.5.

``interaction_effect_k`` is the cooling-advantage contrast across the full scaled
interaction range, because ``interaction = 2 * (demand_pct-.5) * (dryness_pct-.5)``
ranges from -0.5 to +0.5.  It is therefore directly interpretable in kelvin.

Empirical pass templates must carry observed solar zenith and azimuth.  Zenith is
scaled linearly and azimuth enters as sine/cosine controls, so the 0/360-degree
boundary is continuous.  Acquisition timestamps/dates are retained as provenance
but never enter a fitted model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from math import ceil
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


OBSERVED_GEOMETRY_STATUS = "observed_solar_geometry"
SYNTHETIC_GEOMETRY_STATUS = "synthetic_astronomical_geometry"
LEGACY_PRELIMINARY_GEOMETRY_STATUS = (
    "legacy_preliminary_geometry_omitted_gate_ineligible"
)
LEGACY_RECONSTRUCTED_GEOMETRY_STATUS = (
    "legacy_preliminary_geometry_reconstructed_gate_ineligible"
)
CERTIFIED_COUNT_STATUSES = frozenset(
    {
        "certified_usable_passes",
        "certified_expected_pass_equivalent_floor",
        "certified_archive_available_expected_pass_equivalent_floor",
    }
)

# Frozen Census-domain centroids, used only to create synthetic geometry or an
# explicitly requested reconstruction of the already gate-ineligible preliminary
# ceiling template.  Definitive empirical templates must provide observed geometry.
CITY_SOLAR_COORDINATES: Mapping[str, tuple[float, float]] = {
    "phoenix": (33.5014810, -111.9611870),
    "los_angeles": (33.9845493, -118.1231631),
    "atlanta": (33.8362691, -84.3365018),
    "minneapolis_st_paul": (44.9742269, -93.2837529),
    "miami": (26.1955769, -80.2284942),
}


@dataclass(frozen=True)
class SimulationSpec:
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

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "SimulationSpec":
        fields = {name: values[name] for name in cls.__dataclass_fields__ if name in values}
        if "effect_sizes_k" in fields:
            fields["effect_sizes_k"] = tuple(float(x) for x in fields["effect_sizes_k"])
        return cls(**fields)

    def validate(self) -> None:
        if not 0 < self.alpha < 1:
            raise ValueError("alpha must be between zero and one")
        if not 0 < self.target_power < 1:
            raise ValueError("target_power must be between zero and one")
        if self.rows_per_pass < self.matched_sets_per_pass:
            raise ValueError("rows_per_pass must be at least matched_sets_per_pass")
        if self.matched_sets_per_pass < 1:
            raise ValueError("matched_sets_per_pass must be positive")
        if any(x <= 0 for x in self.effect_sizes_k):
            raise ValueError("effect sizes must be positive")
        geometry_effects = (
            self.solar_zenith_effect_k,
            self.solar_azimuth_sin_effect_k,
            self.solar_azimuth_cos_effect_k,
        )
        if not np.isfinite(geometry_effects).all():
            raise ValueError("solar-geometry nuisance effects must be finite")


@dataclass(frozen=True)
class DiagnosticThresholds:
    """Frozen D0027 checks applied to a full-profile Step-3 result."""

    large_n_max_abs_bias_k: float = 0.20
    null_rate_max: float = 0.10
    block_bootstrap_coverage_min: float = 0.90
    naive_coverage_gap_min: float = 0.10
    nominal_coverage: float = 0.95
    interval_alpha: float = 0.05

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "DiagnosticThresholds":
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
            value = float(getattr(self, name))
            if not 0 < value < 1:
                raise ValueError(f"{name} must be between zero and one")


@dataclass(frozen=True)
class FitResult:
    term: str
    estimate: float
    std_error: float
    ci_low: float
    ci_high: float
    p_value: float
    n_rows: int
    n_passes: int
    covariance: str


def _rank_percentile(values: np.ndarray) -> np.ndarray:
    return pd.Series(values).rank(method="average", pct=True).to_numpy(dtype=float)


def _solar_geometry_from_local_time(
    city: Sequence[str] | np.ndarray,
    source_date: Sequence[Any] | pd.Series,
    local_solar_time: Sequence[float] | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Approximate solar zenith/azimuth from city, date, and apparent solar time.

    This transparent astronomical calculation is for synthetic fixtures and an
    explicitly marked legacy reconstruction only.  It is not a substitute for the
    observed geometry required from the definitive Step-2 pass table.
    """

    city_values = np.asarray(city, dtype=str)
    dates = pd.DatetimeIndex(pd.to_datetime(source_date, errors="coerce"))
    hours = np.asarray(local_solar_time, dtype=float)
    if len(city_values) != len(dates) or len(hours) != len(dates):
        raise ValueError("city, source_date, and local_solar_time must have equal length")
    if dates.isna().any():
        raise ValueError("source_date is required to reconstruct solar geometry")
    unknown = sorted(set(city_values).difference(CITY_SOLAR_COORDINATES))
    if unknown:
        raise ValueError(f"no frozen centroid is available for cities: {unknown}")
    latitude = np.asarray([CITY_SOLAR_COORDINATES[value][0] for value in city_values])
    day_of_year = dates.dayofyear.to_numpy(dtype=float)
    latitude_rad = np.deg2rad(latitude)
    declination_rad = np.deg2rad(
        23.44 * np.sin(2.0 * np.pi * (284.0 + day_of_year) / 365.0)
    )
    hour_angle_rad = np.deg2rad(15.0 * (hours - 12.0))
    cosine_zenith = (
        np.sin(latitude_rad) * np.sin(declination_rad)
        + np.cos(latitude_rad) * np.cos(declination_rad) * np.cos(hour_angle_rad)
    )
    zenith = np.rad2deg(np.arccos(np.clip(cosine_zenith, -1.0, 1.0)))
    azimuth = (
        np.rad2deg(
            np.arctan2(
                np.sin(hour_angle_rad),
                np.cos(hour_angle_rad) * np.sin(latitude_rad)
                - np.tan(declination_rad) * np.cos(latitude_rad),
            )
        )
        + 180.0
    ) % 360.0
    return zenith.astype(float), azimuth.astype(float)


def _synthetic_acquisition_utc(
    city: np.ndarray,
    source_dates: pd.DatetimeIndex,
    local_solar_time: np.ndarray,
) -> pd.DatetimeIndex:
    """Map synthetic apparent solar time to a plausible UTC timestamp."""

    longitude = np.asarray([CITY_SOLAR_COORDINATES[value][1] for value in city])
    day_of_year = source_dates.dayofyear.to_numpy(dtype=float)
    angle = 2.0 * np.pi * (day_of_year - 81.0) / 364.0
    equation_of_time_minutes = (
        9.87 * np.sin(2.0 * angle) - 7.53 * np.cos(angle) - 1.50 * np.sin(angle)
    )
    utc_hour = local_solar_time - longitude / 15.0 - equation_of_time_minutes / 60.0
    midnight_utc = source_dates.tz_localize("UTC")
    return midnight_utc + pd.to_timedelta(utc_hour, unit="h")


def synthetic_pass_template(n: int, rng: np.random.Generator, rho: float = 0.60) -> pd.DataFrame:
    """Create a correlated five-city pass distribution with plausible solar geometry."""
    if n < 2:
        raise ValueError("at least two passes are required")
    if not -0.95 < rho < 0.95:
        raise ValueError("rho must lie in (-0.95, 0.95)")
    latent = rng.multivariate_normal([0.0, 0.0], [[1.0, rho], [rho, 1.0]], size=n)
    demand = _rank_percentile(latent[:, 0])
    dryness = _rank_percentile(latent[:, 1])
    cities = np.array(["phoenix", "los_angeles", "atlanta", "minneapolis_st_paul", "miami"])
    city = cities[np.arange(n) % len(cities)]
    # ISS sampling is broad rather than tied to a single clock hour.
    local_solar = np.clip(rng.normal(14.0, 2.0, n), 10.0, 18.0)
    years = rng.integers(2018, 2026, size=n)
    summer_offsets = rng.integers(0, 122, size=n)
    source_dates = pd.DatetimeIndex(
        [
            pd.Timestamp(year=int(year), month=6, day=1) + pd.Timedelta(days=int(offset))
            for year, offset in zip(years, summer_offsets, strict=True)
        ]
    )
    zenith, azimuth = _solar_geometry_from_local_time(
        city, source_dates, local_solar
    )
    acquisition_utc = _synthetic_acquisition_utc(city, source_dates, local_solar)
    return pd.DataFrame(
        {
            "source_pass_id": [f"template_{i:05d}" for i in range(n)],
            "city": city,
            "demand_pct": demand,
            "dryness_pct": dryness,
            "local_solar_time": local_solar,
            "solar_zenith_deg": zenith,
            "solar_azimuth_deg": azimuth,
            "source_date": source_dates.strftime("%Y-%m-%d"),
            "acquisition_utc": acquisition_utc,
            "template_geometry_status": SYNTHETIC_GEOMETRY_STATUS,
        }
    )


def validate_template(
    template: pd.DataFrame,
    *,
    allow_legacy_preliminary_geometry: bool = False,
) -> pd.DataFrame:
    """Normalize a pass template without silently discarding solar geometry.

    Missing geometry is rejected.  The sole compatibility path requires both an
    explicit opt-in and the exact gate-ineligible legacy status; it reconstructs
    approximate geometry from frozen centroids/date/local solar time and remains
    ineligible for the definitive scientific gate.
    """

    aliases = {
        "demand_percentile": "demand_pct",
        "antecedent_dryness_30d_pct": "dryness_pct",
        "antecedent_dryness_percentile": "dryness_pct",
        "local_solar_time_hours": "local_solar_time",
        "local_solar_hour": "local_solar_time",
        "solar_zenith": "solar_zenith_deg",
        "solar_azimuth": "solar_azimuth_deg",
        "local_solar_date": "source_date",
        "date": "source_date",
        "scene_key": "source_pass_id",
    }
    renames: dict[str, str] = {}
    for source, target in aliases.items():
        if (
            source in template
            and target not in template
            and target not in renames.values()
        ):
            renames[source] = target
    out = template.rename(columns=renames).copy()
    basic = ("city", "demand_pct", "dryness_pct", "local_solar_time")
    geometry = ("solar_zenith_deg", "solar_azimuth_deg")
    required = basic + geometry
    missing_basic = [name for name in basic if name not in out]
    if missing_basic:
        raise ValueError(f"pass template missing columns: {missing_basic}")
    missing_geometry = [name for name in geometry if name not in out]
    if missing_geometry:
        statuses = set(out.get("template_geometry_status", pd.Series(dtype=str)).astype(str))
        explicitly_legacy = statuses == {LEGACY_PRELIMINARY_GEOMETRY_STATUS}
        if not allow_legacy_preliminary_geometry or not explicitly_legacy:
            raise ValueError(
                "pass template missing required observed solar geometry columns: "
                f"{missing_geometry}; definitive templates may not discard geometry. "
                "The gate-ineligible legacy reconstruction requires explicit opt-in "
                f"and status {LEGACY_PRELIMINARY_GEOMETRY_STATUS!r}."
            )
        if "source_date" not in out:
            raise ValueError("legacy geometry reconstruction requires source_date/date")
        zenith, azimuth = _solar_geometry_from_local_time(
            out["city"].astype(str), out["source_date"], out["local_solar_time"]
        )
        out["solar_zenith_deg"] = zenith
        out["solar_azimuth_deg"] = azimuth
        out["template_geometry_status"] = LEGACY_RECONSTRUCTED_GEOMETRY_STATUS
    missing = [name for name in required if name not in out]
    if missing:
        raise ValueError(f"pass template missing columns: {missing}")
    for name in (*basic[1:], *geometry):
        out[name] = pd.to_numeric(out[name], errors="coerce")
    incomplete = out[list(required)].isna().any(axis=1)
    if incomplete.any():
        raise ValueError(
            "pass template contains missing/non-numeric required values at rows "
            f"{np.flatnonzero(incomplete.to_numpy())[:10].tolist()}"
        )
    out = out.reset_index(drop=True)
    if len(out) < 5:
        raise ValueError("pass template needs at least five complete rows")
    if not out["demand_pct"].between(0, 1).all() or not out["dryness_pct"].between(0, 1).all():
        raise ValueError("demand and dryness percentiles must be in [0, 1]")
    if not out["local_solar_time"].between(0, 24).all():
        raise ValueError("local_solar_time must be in [0, 24]")
    if not out["solar_zenith_deg"].between(0, 180).all():
        raise ValueError("solar_zenith_deg must be in [0, 180]")
    if not ((out["solar_azimuth_deg"] >= 0) & (out["solar_azimuth_deg"] < 360)).all():
        raise ValueError("solar_azimuth_deg must be in [0, 360)")
    out["city"] = out["city"].astype(str)
    if "source_pass_id" not in out:
        out["source_pass_id"] = [f"source_{i:06d}" for i in range(len(out))]
    out["source_pass_id"] = out["source_pass_id"].astype(str)
    if out["source_pass_id"].duplicated().any():
        raise ValueError("source_pass_id must be unique in a pass template")
    if "template_geometry_status" not in out:
        out["template_geometry_status"] = OBSERVED_GEOMETRY_STATUS
    out["template_geometry_status"] = out["template_geometry_status"].astype(str)
    if "sampling_weight" in out:
        out["sampling_weight"] = pd.to_numeric(
            out["sampling_weight"], errors="coerce"
        )
        if (
            out["sampling_weight"].isna().any()
            or not bool(np.isfinite(out["sampling_weight"]).all())
            or (out["sampling_weight"] < 0).any()
            or float(out["sampling_weight"].sum()) <= 0
        ):
            raise ValueError(
                "sampling_weight must contain finite nonnegative values with a positive total"
            )
    provenance: list[str] = []
    if "source_date" in out:
        parsed_date = pd.to_datetime(out["source_date"], errors="coerce")
        if parsed_date.isna().any():
            raise ValueError("source_date contains unparseable values")
        out["source_date"] = parsed_date.dt.strftime("%Y-%m-%d")
        provenance.append("source_date")
    if "acquisition_utc" in out:
        try:
            parsed_utc = pd.to_datetime(
                out["acquisition_utc"],
                utc=True,
                errors="coerce",
                format="mixed",
            )
        except TypeError:  # pragma: no cover - compatibility with older pandas
            parsed_utc = pd.to_datetime(
                out["acquisition_utc"], utc=True, errors="coerce"
            )
        if parsed_utc.isna().any():
            raise ValueError("acquisition_utc contains unparseable values")
        out["acquisition_utc"] = parsed_utc
        provenance.append("acquisition_utc")
    optional = ["sampling_weight"] if "sampling_weight" in out else []
    ordered = list(required) + [
        "source_pass_id",
        "template_geometry_status",
        *optional,
        *provenance,
    ]
    return out[ordered]


def _sample_passes(template: pd.DataFrame, n_passes: int, rng: np.random.Generator) -> pd.DataFrame:
    replace = n_passes > len(template)
    probability = None
    if "sampling_weight" in template:
        weight = template["sampling_weight"].to_numpy(dtype=float)
        probability = weight / weight.sum()
        replace = n_passes > int(np.count_nonzero(weight))
    chosen = rng.choice(
        len(template), size=n_passes, replace=replace, p=probability
    )
    out = template.iloc[chosen].reset_index(drop=True).copy()
    out["pass_id"] = [f"pass_{i:05d}" for i in range(n_passes)]
    return out


def simulate_clustered_data(
    template: pd.DataFrame,
    n_passes: int,
    interaction_effect_k: float,
    spec: SimulationSpec,
    rng: np.random.Generator,
    *,
    three_way_effect_k: float = 0.0,
) -> pd.DataFrame:
    """Simulate matched rows nested in passes while retaining real predictor support."""
    spec.validate()
    base = _sample_passes(validate_template(template), n_passes, rng)
    rows_per_set = int(ceil(spec.rows_per_pass / spec.matched_sets_per_pass))
    city_effects = {
        city: effect
        for city, effect in zip(sorted(base["city"].unique()), np.linspace(-0.35, 0.35, base["city"].nunique()))
    }
    # Allocate one result table rather than constructing one DataFrame per pass.
    # The random draws remain in the exact historical pass-by-pass order, so a
    # frozen seed produces the same artificial data while large planning runs
    # avoid millions of small pandas allocations.
    n_rows = spec.rows_per_pass
    n_total = n_passes * n_rows
    row_pass_index = np.repeat(np.arange(n_passes), n_rows)
    pass_ids = base["pass_id"].astype(str).to_numpy()
    source_pass_ids = base["source_pass_id"].astype(str).to_numpy()
    city_values = base["city"].astype(str).to_numpy()
    set_ids_one_pass = np.repeat(
        np.arange(spec.matched_sets_per_pass), rows_per_set
    )[:n_rows]
    set_ids = np.tile(set_ids_one_pass, n_passes)
    demand_by_pass = base["demand_pct"].to_numpy(float) - 0.5
    dryness_by_pass = base["dryness_pct"].to_numpy(float) - 0.5
    time_by_pass = (base["local_solar_time"].to_numpy(float) - 14.0) / 4.0
    solar_zenith_by_pass = base["solar_zenith_deg"].to_numpy(float)
    solar_azimuth_by_pass = base["solar_azimuth_deg"].to_numpy(float)
    solar_zenith_c_by_pass = (solar_zenith_by_pass - 45.0) / 45.0
    solar_azimuth_rad = np.deg2rad(solar_azimuth_by_pass)
    solar_azimuth_sin_by_pass = np.sin(solar_azimuth_rad)
    solar_azimuth_cos_by_pass = np.cos(solar_azimuth_rad)
    interaction_by_pass = 2.0 * demand_by_pass * dryness_by_pass
    three_way_by_pass = interaction_by_pass * time_by_pass
    outcome = np.empty(n_total, dtype=float)
    for pass_index, pass_row in base.iterrows():
        d = demand_by_pass[pass_index]
        w = dryness_by_pass[pass_index]
        time_scaled = time_by_pass[pass_index]
        interaction = interaction_by_pass[pass_index]
        pass_noise = rng.normal(0.0, spec.pass_sd_k)
        set_noise_values = rng.normal(0.0, spec.matched_set_sd_k, spec.matched_sets_per_pass)
        start = pass_index * n_rows
        stop = start + n_rows
        outcome[start:stop] = (
            3.0
            - 0.45 * d
            - 0.35 * w
            + interaction_effect_k * interaction
            + 0.30 * time_scaled
            + spec.solar_zenith_effect_k * solar_zenith_c_by_pass[pass_index]
            + spec.solar_azimuth_sin_effect_k * solar_azimuth_sin_by_pass[pass_index]
            + spec.solar_azimuth_cos_effect_k * solar_azimuth_cos_by_pass[pass_index]
            + three_way_effect_k * interaction * time_scaled
            + city_effects[str(pass_row["city"])]
            + pass_noise
            + set_noise_values[set_ids_one_pass]
            + rng.normal(0.0, spec.row_sd_k, n_rows)
        )
    repeated_pass_ids = pass_ids[row_pass_index]
    output: dict[str, Any] = {
        "pass_id": repeated_pass_ids,
        "source_pass_id": source_pass_ids[row_pass_index],
        "city": city_values[row_pass_index],
        "matched_set_id": [
            f"{pass_id}_set_{set_id}"
            for pass_id, set_id in zip(repeated_pass_ids, set_ids, strict=True)
        ],
        "demand_c": demand_by_pass[row_pass_index],
        "dryness_c": dryness_by_pass[row_pass_index],
        "local_time_c": time_by_pass[row_pass_index],
        "solar_zenith_deg": solar_zenith_by_pass[row_pass_index],
        "solar_azimuth_deg": solar_azimuth_by_pass[row_pass_index],
        "solar_zenith_c": solar_zenith_c_by_pass[row_pass_index],
        "solar_azimuth_sin": solar_azimuth_sin_by_pass[row_pass_index],
        "solar_azimuth_cos": solar_azimuth_cos_by_pass[row_pass_index],
        "interaction": interaction_by_pass[row_pass_index],
        "three_way": three_way_by_pass[row_pass_index],
        "cooling_advantage_k": outcome,
        "template_geometry_status": base["template_geometry_status"].astype(str).to_numpy()[
            row_pass_index
        ],
    }
    for provenance_name in ("source_date", "acquisition_utc"):
        if provenance_name in base:
            output[provenance_name] = base[provenance_name].to_numpy()[row_pass_index]
    return pd.DataFrame(output)


def _design_matrix(data: pd.DataFrame, *, include_three_way: bool) -> tuple[np.ndarray, list[str]]:
    names = [
        "intercept",
        "demand_c",
        "dryness_c",
        "interaction",
        "local_time_c",
        "solar_zenith_c",
        "solar_azimuth_sin",
        "solar_azimuth_cos",
    ]
    columns = [
        np.ones(len(data)),
        data["demand_c"].to_numpy(float),
        data["dryness_c"].to_numpy(float),
        data["interaction"].to_numpy(float),
        data["local_time_c"].to_numpy(float),
        data["solar_zenith_c"].to_numpy(float),
        data["solar_azimuth_sin"].to_numpy(float),
        data["solar_azimuth_cos"].to_numpy(float),
    ]
    if include_three_way:
        names.append("three_way")
        columns.append(data["three_way"].to_numpy(float))
    cities = pd.get_dummies(data["city"], prefix="city", drop_first=True, dtype=float)
    for name in cities.columns:
        names.append(str(name))
        columns.append(cities[name].to_numpy(float))
    return np.column_stack(columns), names


def _ols_covariance(
    x: np.ndarray,
    residual: np.ndarray,
    clusters: np.ndarray | None,
) -> tuple[np.ndarray, int, str]:
    n, k = x.shape
    bread = np.linalg.pinv(x.T @ x)
    if clusters is None:
        df = max(n - k, 1)
        sigma2 = float(residual @ residual) / df
        return bread * sigma2, df, "naive_row"
    unique = pd.unique(clusters)
    g = len(unique)
    if g <= 1:
        raise ValueError("cluster covariance requires at least two passes")
    meat = np.zeros((k, k), dtype=float)
    for cluster in unique:
        mask = clusters == cluster
        score = x[mask].T @ residual[mask]
        meat += np.outer(score, score)
    correction = (g / (g - 1)) * ((n - 1) / max(n - k, 1))
    return correction * bread @ meat @ bread, g - 1, "pass_cluster"


def fit_interaction(
    data: pd.DataFrame,
    *,
    term: str = "interaction",
    covariance: str = "pass_cluster",
) -> FitResult:
    """Fit the intended linear interaction model with pass-cluster inference."""
    if term not in {"interaction", "three_way"}:
        raise ValueError("term must be 'interaction' or 'three_way'")
    include_three_way = term == "three_way"
    required = {
        "pass_id",
        "city",
        "demand_c",
        "dryness_c",
        "interaction",
        "local_time_c",
        "solar_zenith_c",
        "solar_azimuth_sin",
        "solar_azimuth_cos",
        "three_way",
        "cooling_advantage_k",
    }
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"model data missing columns {sorted(missing)}")
    clean = data.dropna(subset=list(required)).copy()
    x, names = _design_matrix(clean, include_three_way=include_three_way)
    y = clean["cooling_advantage_k"].to_numpy(float)
    beta = np.linalg.pinv(x) @ y
    residual = y - x @ beta
    clusters = clean["pass_id"].to_numpy() if covariance == "pass_cluster" else None
    if covariance not in {"pass_cluster", "naive_row"}:
        raise ValueError("covariance must be pass_cluster or naive_row")
    cov, df, cov_name = _ols_covariance(x, residual, clusters)
    index = names.index(term)
    se = float(np.sqrt(max(cov[index, index], 0.0)))
    estimate = float(beta[index])
    critical = float(stats.t.ppf(0.975, df))
    if se == 0:
        p_value = 0.0 if estimate != 0 else 1.0
    else:
        p_value = float(2 * stats.t.sf(abs(estimate / se), df))
    return FitResult(
        term=term,
        estimate=estimate,
        std_error=se,
        ci_low=estimate - critical * se,
        ci_high=estimate + critical * se,
        p_value=p_value,
        n_rows=len(clean),
        n_passes=clean["pass_id"].nunique(),
        covariance=cov_name,
    )


def bootstrap_interval(
    data: pd.DataFrame,
    *,
    term: str,
    method: str,
    n_boot: int,
    rng: np.random.Generator,
) -> tuple[float, float]:
    """Percentile interval using whole-pass or deliberately naive row resampling.

    Only the coefficient is needed in each bootstrap draw.  Compute it from
    cross-products of a fixed design matrix instead of rebuilding a pandas table
    and refitting the same design formula hundreds of times.  This is algebraically
    the same OLS estimate and leaves the random resampling sequence unchanged.
    """
    if method not in {"pass", "row"}:
        raise ValueError("method must be pass or row")
    if n_boot <= 0:
        raise ValueError("n_boot must be positive")
    required = [
        "pass_id",
        "city",
        "demand_c",
        "dryness_c",
        "interaction",
        "local_time_c",
        "solar_zenith_c",
        "solar_azimuth_sin",
        "solar_azimuth_cos",
        "three_way",
        "cooling_advantage_k",
    ]
    missing = set(required).difference(data.columns)
    if missing:
        raise ValueError(f"model data missing columns {sorted(missing)}")
    base = data.reset_index(drop=True)
    valid_mask = base[required].notna().all(axis=1).to_numpy()
    clean = base.loc[valid_mask].reset_index(drop=True)
    if clean.empty:
        return np.nan, np.nan
    x, names = _design_matrix(clean, include_three_way=term == "three_way")
    if term not in names:
        raise ValueError("term must be 'interaction' or 'three_way'")
    y = clean["cooling_advantage_k"].to_numpy(float)
    term_index = names.index(term)

    def estimate_from_crossproducts(xtx: np.ndarray, xty: np.ndarray) -> float:
        return float((np.linalg.pinv(xtx) @ xty)[term_index])

    estimates: list[float] = []
    if method == "pass":
        pass_ids = pd.unique(base["pass_id"])
        clean_pass_ids = clean["pass_id"].to_numpy()
        k = x.shape[1]
        block_xtx: dict[Any, np.ndarray] = {}
        block_xty: dict[Any, np.ndarray] = {}
        for pass_id in pass_ids:
            mask = clean_pass_ids == pass_id
            block_x = x[mask]
            block_y = y[mask]
            block_xtx[pass_id] = block_x.T @ block_x if len(block_x) else np.zeros((k, k))
            block_xty[pass_id] = block_x.T @ block_y if len(block_x) else np.zeros(k)
        for _ in range(n_boot):
            selected = rng.choice(pass_ids, size=len(pass_ids), replace=True)
            xtx = np.sum([block_xtx[pass_id] for pass_id in selected], axis=0)
            xty = np.sum([block_xty[pass_id] for pass_id in selected], axis=0)
            if np.linalg.matrix_rank(xtx) < xtx.shape[0]:
                # Preserve the historical Moore-Penrose solution in tiny or
                # pathological draws where the sampled design loses a city or
                # another column.  This fallback is effectively never reached in
                # the intended hundreds-of-passes profile.
                sample = pd.concat(
                    [base.loc[base["pass_id"] == pass_id] for pass_id in selected],
                    ignore_index=True,
                )
                estimates.append(
                    fit_interaction(sample, term=term, covariance="naive_row").estimate
                )
            else:
                estimates.append(estimate_from_crossproducts(xtx, xty))
    else:
        # Draw from the original row positions to retain historical missing-row
        # semantics, then map valid selections to the fixed clean design.
        original_to_clean = np.full(len(base), -1, dtype=int)
        original_to_clean[np.flatnonzero(valid_mask)] = np.arange(len(clean))
        for _ in range(n_boot):
            selected = rng.integers(0, len(base), len(base))
            selected_clean = original_to_clean[selected]
            selected_clean = selected_clean[selected_clean >= 0]
            sample_x = x[selected_clean]
            sample_y = y[selected_clean]
            xtx = sample_x.T @ sample_x
            if np.linalg.matrix_rank(xtx) < xtx.shape[0]:
                estimates.append(
                    fit_interaction(
                        base.iloc[selected].reset_index(drop=True),
                        term=term,
                        covariance="naive_row",
                    ).estimate
                )
            else:
                estimates.append(
                    estimate_from_crossproducts(xtx, sample_x.T @ sample_y)
                )
    finite = np.asarray(estimates, dtype=float)
    finite = finite[np.isfinite(finite)]
    if len(finite) < max(10, n_boot // 2):
        return np.nan, np.nan
    return tuple(np.quantile(finite, [0.025, 0.975]).tolist())


def simulate_smooth_no_breakpoint(
    template: pd.DataFrame,
    n_passes: int,
    spec: SimulationSpec,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Simulate a genuinely smooth quadratic response with no threshold."""
    data = simulate_clustered_data(template, n_passes, 0.0, spec, rng)
    stress = 0.5 * (data["demand_c"] + 0.5) + 0.5 * (data["dryness_c"] + 0.5)
    pass_noise = data.groupby("pass_id")["cooling_advantage_k"].transform("mean") - 3.0
    data["stress"] = stress
    data["cooling_advantage_k"] = 3.2 - 0.7 * stress - 0.9 * (stress - 0.5) ** 2 + pass_noise
    return data


def transition_test(data: pd.DataFrame, *, alpha: float = 0.05) -> dict[str, float | bool | int]:
    """Bonferroni-corrected hinge search against a smooth quadratic null.

    The input is collapsed to pass means before testing.  Candidate locations are
    fixed quantiles, and the multiple-search correction is part of the test rather
    than an after-the-fact interpretation.
    """
    pass_data = (
        data.groupby("pass_id", as_index=False)
        .agg(
            stress=("stress", "first"),
            outcome=("cooling_advantage_k", "mean"),
            city=("city", "first"),
            local_time_c=("local_time_c", "first"),
            solar_zenith_c=("solar_zenith_c", "first"),
            solar_azimuth_sin=("solar_azimuth_sin", "first"),
            solar_azimuth_cos=("solar_azimuth_cos", "first"),
        )
        .dropna()
    )
    stress = pass_data["stress"].to_numpy(float)
    y = pass_data["outcome"].to_numpy(float)
    if len(np.unique(stress)) < 8:
        return {
            "best_breakpoint": np.nan,
            "raw_p_value": np.nan,
            "adjusted_p_value": np.nan,
            "detected": False,
            "n_passes": len(pass_data),
        }
    city = pd.get_dummies(pass_data["city"], drop_first=True, dtype=float).to_numpy()
    base_columns = [
        np.ones(len(stress)),
        stress,
        stress**2,
        pass_data["local_time_c"].to_numpy(float),
        pass_data["solar_zenith_c"].to_numpy(float),
        pass_data["solar_azimuth_sin"].to_numpy(float),
        pass_data["solar_azimuth_cos"].to_numpy(float),
    ]
    if city.size:
        base_columns.extend(city[:, i] for i in range(city.shape[1]))
    base = np.column_stack(base_columns)
    candidates = np.unique(np.quantile(stress, np.linspace(0.20, 0.80, 7)))
    tests: list[tuple[float, float]] = []
    for knot in candidates:
        hinge = np.maximum(stress - knot, 0.0)
        x = np.column_stack([base, hinge])
        beta = np.linalg.pinv(x) @ y
        residual = y - x @ beta
        cov, df, _ = _ols_covariance(x, residual, None)
        se = float(np.sqrt(max(cov[-1, -1], 0.0)))
        p_value = 1.0 if se == 0 else float(2 * stats.t.sf(abs(float(beta[-1]) / se), df))
        tests.append((p_value, float(knot)))
    raw_p, best = min(tests, key=lambda item: item[0])
    adjusted = min(1.0, raw_p * len(tests))
    return {
        "best_breakpoint": best,
        "raw_p_value": raw_p,
        "adjusted_p_value": adjusted,
        "detected": bool(adjusted < alpha),
        "n_passes": len(pass_data),
    }


def run_simulation_study(
    *,
    actual_n_passes: int,
    pass_counts: Sequence[int],
    spec: SimulationSpec = SimulationSpec(),
    template: pd.DataFrame | None = None,
    n_replicates: int = 200,
    n_coverage_replicates: int = 60,
    n_boot: int = 120,
    count_status: str = "not_certified",
    template_status: str = "empirical_exact_acquisition_conditions",
    allow_legacy_preliminary_geometry: bool = False,
) -> dict[str, Any]:
    """Run the complete Step 3 study with deterministic child random streams."""
    spec.validate()
    if actual_n_passes < 5:
        raise ValueError("actual_n_passes must be at least five")
    for name, value in (
        ("n_replicates", n_replicates),
        ("n_coverage_replicates", n_coverage_replicates),
        ("n_boot", n_boot),
    ):
        if int(value) <= 0:
            raise ValueError(f"{name} must be positive")
    counts = sorted(set(int(x) for x in (*pass_counts, actual_n_passes)))
    if any(x < 5 for x in counts):
        raise ValueError("every pass count must be at least five")
    master = np.random.SeedSequence(spec.seed)
    if template is None:
        template_rng = np.random.default_rng(master.spawn(1)[0])
        template = synthetic_pass_template(max(1000, actual_n_passes * 3), template_rng)
    template = validate_template(
        template,
        allow_legacy_preliminary_geometry=allow_legacy_preliminary_geometry,
    )
    geometry_statuses = sorted(template["template_geometry_status"].unique().astype(str))
    geometry_gate_eligible = geometry_statuses == [OBSERVED_GEOMETRY_STATUS]
    if not geometry_gate_eligible and count_status in CERTIFIED_COUNT_STATUSES:
        raise ValueError(
            "a certified pass count requires observed solar geometry; synthetic or "
            "legacy-reconstructed geometry is scientifically gate-ineligible"
        )
    canonical_template = template.sort_values(
        ["source_pass_id", "city", "demand_pct", "dryness_pct", "local_solar_time"],
        kind="stable",
    ).to_csv(index=False, float_format="%.17g", lineterminator="\n")
    template_sha256 = hashlib.sha256(canonical_template.encode("utf-8")).hexdigest()
    rng = np.random.default_rng(master.spawn(1)[0])

    power_rows: list[dict[str, Any]] = []
    transition_rows: list[dict[str, Any]] = []
    three_way_rows: list[dict[str, Any]] = []
    for n_passes in counts:
        for effect in spec.effect_sizes_k:
            for replicate in range(n_replicates):
                data = simulate_clustered_data(template, n_passes, effect, spec, rng)
                fit = fit_interaction(data)
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
        for replicate in range(n_replicates):
            smooth = simulate_smooth_no_breakpoint(template, n_passes, spec, rng)
            transition_rows.append(
                {"n_passes": n_passes, "replicate": replicate, **transition_test(smooth, alpha=spec.alpha)}
            )
            data = simulate_clustered_data(
                template,
                n_passes,
                spec.primary_effect_size_k,
                spec,
                rng,
                three_way_effect_k=spec.primary_effect_size_k,
            )
            fit = fit_interaction(data, term="three_way")
            three_way_rows.append(
                {
                    "n_passes": n_passes,
                    "replicate": replicate,
                    "effect_size_k": spec.primary_effect_size_k,
                    "estimate_k": fit.estimate,
                    "p_value": fit.p_value,
                    "detected": fit.p_value < spec.alpha,
                }
            )

    coverage_rows: list[dict[str, Any]] = []
    for n_passes in counts:
        for replicate in range(n_coverage_replicates):
            data = simulate_clustered_data(template, n_passes, spec.primary_effect_size_k, spec, rng)
            for method in ("pass", "row"):
                low, high = bootstrap_interval(
                    data,
                    term="interaction",
                    method=method,
                    n_boot=n_boot,
                    rng=rng,
                )
                coverage_rows.append(
                    {
                        "n_passes": n_passes,
                        "replicate": replicate,
                        "method": "pass-level block bootstrap" if method == "pass" else "naive row bootstrap",
                        "true_effect_k": spec.primary_effect_size_k,
                        "ci_low_k": low,
                        "ci_high_k": high,
                        "covered": bool(np.isfinite(low) and low <= spec.primary_effect_size_k <= high),
                        "interval_width_k": high - low,
                    }
                )

    # The guide requires explicit no-interaction runs, separately from the
    # smooth-no-breakpoint transition experiment.  Use an independent named
    # child stream so adding this mandatory check does not alter any historical
    # power, transition, three-way, or coverage draws for the frozen main seed.
    null_rng = np.random.default_rng(np.random.SeedSequence([spec.seed, 0x4E554C4C]))
    interaction_null_rows: list[dict[str, Any]] = []
    three_way_null_rows: list[dict[str, Any]] = []
    for n_passes in counts:
        for replicate in range(n_replicates):
            no_interaction = simulate_clustered_data(
                template, n_passes, 0.0, spec, null_rng
            )
            null_fit = fit_interaction(no_interaction)
            interaction_null_rows.append(
                {
                    "n_passes": n_passes,
                    "replicate": replicate,
                    "true_effect_k": 0.0,
                    "estimate_k": null_fit.estimate,
                    "p_value": null_fit.p_value,
                    "detected": null_fit.p_value < spec.alpha,
                }
            )
            no_three_way = simulate_clustered_data(
                template,
                n_passes,
                spec.primary_effect_size_k,
                spec,
                null_rng,
                three_way_effect_k=0.0,
            )
            null_three_fit = fit_interaction(no_three_way, term="three_way")
            three_way_null_rows.append(
                {
                    "n_passes": n_passes,
                    "replicate": replicate,
                    "true_effect_k": 0.0,
                    "estimate_k": null_three_fit.estimate,
                    "p_value": null_three_fit.p_value,
                    "detected": null_three_fit.p_value < spec.alpha,
                }
            )
    return {
        "actual_n_passes": actual_n_passes,
        "count_status": str(count_status),
        "template_status": str(template_status),
        "template_geometry_status": geometry_statuses,
        "geometry_gate_eligible": geometry_gate_eligible,
        "spec": spec,
        "run_settings": {
            "tested_pass_counts": counts,
            "n_replicates": int(n_replicates),
            "n_coverage_replicates": int(n_coverage_replicates),
            "n_boot": int(n_boot),
            "template_rows": int(len(template)),
            "sampling_weight_status": (
                "cloud_survival_weighted"
                if "sampling_weight" in template
                else "uniform"
            ),
            "sampling_weight_sum": (
                float(template["sampling_weight"].sum())
                if "sampling_weight" in template
                else float(len(template))
            ),
            "normalized_template_sha256": template_sha256,
            "template_geometry_status": geometry_statuses,
            "null_seed_stream": "SeedSequence([seed, 0x4E554C4C])",
        },
        "power": pd.DataFrame(power_rows),
        "transition": pd.DataFrame(transition_rows),
        "three_way": pd.DataFrame(three_way_rows),
        "coverage": pd.DataFrame(coverage_rows),
        "interaction_null": pd.DataFrame(interaction_null_rows),
        "three_way_null": pd.DataFrame(three_way_null_rows),
    }


def _binomial_wilson(successes: int, total: int, *, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson interval used to expose Monte Carlo uncertainty on detection rates."""

    if total <= 0 or successes < 0 or successes > total:
        return np.nan, np.nan
    z = float(stats.norm.ppf(1.0 - alpha / 2.0))
    proportion = successes / total
    denominator = 1.0 + z * z / total
    centre = (proportion + z * z / (2.0 * total)) / denominator
    half = z * np.sqrt(
        proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
    ) / denominator
    return float(max(0.0, centre - half)), float(min(1.0, centre + half))


def _detection_summary(
    frame: pd.DataFrame,
    group_columns: Sequence[str],
    *,
    alpha: float,
    rate_name: str,
) -> pd.DataFrame:
    """Summarize a binary Monte Carlo result with a Wilson interval."""

    summary = (
        frame.groupby(list(group_columns), as_index=False)
        .agg(n_replicates=("detected", "size"), n_detected=("detected", "sum"))
    )
    summary[rate_name] = summary["n_detected"] / summary["n_replicates"]
    intervals = [
        _binomial_wilson(int(row.n_detected), int(row.n_replicates), alpha=alpha)
        for row in summary.itertuples(index=False)
    ]
    summary[f"{rate_name}_mc_ci_low"] = [value[0] for value in intervals]
    summary[f"{rate_name}_mc_ci_high"] = [value[1] for value in intervals]
    return summary


def evaluate_diagnostic_gate(
    results: Mapping[str, Any],
    thresholds: DiagnosticThresholds = DiagnosticThresholds(),
) -> dict[str, Any]:
    """Evaluate every frozen D0027 diagnostic and retain Monte Carlo intervals.

    Null rates are pooled across the preregistered pass-count scenarios before
    their Wilson intervals are calculated.  Coefficient recovery is checked at
    the largest simulated pass count for every frozen nonzero effect.  Coverage
    is checked at the certified cloud-adjusted planning count.
    """

    thresholds.validate()
    spec: SimulationSpec = results["spec"]
    actual = int(results["actual_n_passes"])
    count_status = str(results.get("count_status", "not_certified"))
    eligible = bool(
        count_status in CERTIFIED_COUNT_STATUSES
        and results.get("geometry_gate_eligible", False)
    )
    rows: list[dict[str, Any]] = []

    def add_check(
        check_id: str,
        category: str,
        criterion: str,
        observed_value: float,
        passed: bool,
        *,
        n_monte_carlo: int | None = None,
        mc_ci_low: float = np.nan,
        mc_ci_high: float = np.nan,
        detail: str = "",
    ) -> None:
        rows.append(
            {
                "check_id": check_id,
                "category": category,
                "criterion": criterion,
                "observed_value": float(observed_value),
                "n_monte_carlo": (
                    int(n_monte_carlo) if n_monte_carlo is not None else np.nan
                ),
                "mc_ci_low": float(mc_ci_low),
                "mc_ci_high": float(mc_ci_high),
                "passed": bool(passed),
                "required_for_gate": True,
                "detail": str(detail),
            }
        )

    add_check(
        "certified_inputs",
        "eligibility",
        "certified count status and observed solar geometry",
        float(eligible),
        eligible,
        detail=f"count_status={count_status}",
    )

    power: pd.DataFrame = results["power"]
    primary = power.loc[
        (power["n_passes"].eq(actual))
        & np.isclose(power["effect_size_k"], spec.primary_effect_size_k)
    ]
    if primary.empty:
        raise ValueError("power results lack the primary effect at the planning count")
    primary_successes = int(primary["detected"].sum())
    primary_total = int(len(primary))
    primary_rate = primary_successes / primary_total
    primary_ci = _binomial_wilson(
        primary_successes, primary_total, alpha=thresholds.interval_alpha
    )
    add_check(
        "primary_effect_power",
        "power",
        f"power >= {spec.target_power:.3f} at planning n={actual}",
        primary_rate,
        primary_rate >= spec.target_power,
        n_monte_carlo=primary_total,
        mc_ci_low=primary_ci[0],
        mc_ci_high=primary_ci[1],
        detail=f"effect_size_k={spec.primary_effect_size_k:g}",
    )

    large_n = int(pd.to_numeric(power["n_passes"]).max())
    for effect in sorted(pd.to_numeric(power["effect_size_k"]).unique()):
        subset = power.loc[
            power["n_passes"].eq(large_n)
            & np.isclose(power["effect_size_k"], effect)
        ]
        if subset.empty:
            raise ValueError(f"power results lack effect {effect:g} at n={large_n}")
        mean_estimate = float(subset["estimate_k"].mean())
        absolute_bias = abs(mean_estimate - float(effect))
        add_check(
            f"large_n_bias_{effect:g}k".replace(".", "p"),
            "coefficient_recovery",
            (
                "absolute mean coefficient bias <= "
                f"{thresholds.large_n_max_abs_bias_k:.3f} K at largest n={large_n}"
            ),
            absolute_bias,
            absolute_bias <= thresholds.large_n_max_abs_bias_k,
            n_monte_carlo=len(subset),
            detail=(
                f"truth_k={effect:g}; mean_estimate_k={mean_estimate:.6f}; "
                f"large_n={large_n}"
            ),
        )

    null_frames = (
        ("interaction_null", results["interaction_null"]),
        ("three_way_null", results["three_way_null"]),
        ("smooth_transition_null", results["transition"]),
    )
    for name, frame in null_frames:
        total = int(len(frame))
        if total == 0:
            raise ValueError(f"{name} results are empty")
        successes = int(frame["detected"].sum())
        rate = successes / total
        interval = _binomial_wilson(
            successes, total, alpha=thresholds.interval_alpha
        )
        interval_contains_alpha = interval[0] <= spec.alpha <= interval[1]
        passed = rate <= thresholds.null_rate_max and interval_contains_alpha
        add_check(
            f"pooled_{name}_rate",
            "false_positive_control",
            (
                f"pooled rate <= {thresholds.null_rate_max:.3f} and Wilson "
                f"interval contains nominal alpha={spec.alpha:.3f}"
            ),
            rate,
            passed,
            n_monte_carlo=total,
            mc_ci_low=interval[0],
            mc_ci_high=interval[1],
            detail=f"interval_contains_alpha={interval_contains_alpha}",
        )

    coverage: pd.DataFrame = results["coverage"]
    at_actual = coverage.loc[coverage["n_passes"].eq(actual)]
    coverage_by_method: dict[str, tuple[float, tuple[float, float], int]] = {}
    for method in ("pass-level block bootstrap", "naive row bootstrap"):
        subset = at_actual.loc[at_actual["method"].eq(method)]
        if subset.empty:
            raise ValueError(f"coverage results lack {method!r} at planning n={actual}")
        successes = int(subset["covered"].sum())
        total = int(len(subset))
        rate = successes / total
        interval = _binomial_wilson(
            successes, total, alpha=thresholds.interval_alpha
        )
        coverage_by_method[method] = (rate, interval, total)

    block_rate, block_interval, block_total = coverage_by_method[
        "pass-level block bootstrap"
    ]
    interval_contains_nominal = (
        block_interval[0]
        <= thresholds.nominal_coverage
        <= block_interval[1]
    )
    add_check(
        "planning_count_block_coverage",
        "coverage",
        (
            f"pass-block coverage >= {thresholds.block_bootstrap_coverage_min:.3f} "
            f"and Wilson interval contains {thresholds.nominal_coverage:.3f}"
        ),
        block_rate,
        block_rate >= thresholds.block_bootstrap_coverage_min
        and interval_contains_nominal,
        n_monte_carlo=block_total,
        mc_ci_low=block_interval[0],
        mc_ci_high=block_interval[1],
        detail=f"planning_n={actual}; interval_contains_nominal={interval_contains_nominal}",
    )
    naive_rate = coverage_by_method["naive row bootstrap"][0]
    coverage_gap = block_rate - naive_rate
    add_check(
        "planning_count_naive_coverage_gap",
        "coverage",
        (
            "pass-block coverage minus naive-row coverage >= "
            f"{thresholds.naive_coverage_gap_min:.3f}"
        ),
        coverage_gap,
        coverage_gap >= thresholds.naive_coverage_gap_min,
        n_monte_carlo=block_total,
        detail=(
            f"planning_n={actual}; block_coverage={block_rate:.6f}; "
            f"naive_coverage={naive_rate:.6f}"
        ),
    )

    checks = pd.DataFrame(rows)
    failed = checks.loc[
        checks["required_for_gate"] & ~checks["passed"], "check_id"
    ].astype(str).tolist()
    status = "PASS" if not failed else ("NOT_ELIGIBLE" if not eligible else "FAIL")
    summary = {
        "decision_id": "D0027",
        "status": status,
        "scientific_gate_eligible": eligible,
        "actual_n_passes": actual,
        "large_count_n_passes": large_n,
        "passed_required_checks": int(checks["passed"].sum()),
        "total_required_checks": int(len(checks)),
        "failed_check_ids": failed,
        "thresholds": asdict(thresholds),
    }
    return {"summary": summary, "checks": checks}


def summarize_support(results: Mapping[str, Any]) -> pd.DataFrame:
    """Build T3.1 model support and minimum-pass decisions."""
    spec: SimulationSpec = results["spec"]
    actual = int(results["actual_n_passes"])
    count_status = str(results.get("count_status", "not_certified"))
    gate_eligible = bool(
        count_status in CERTIFIED_COUNT_STATUSES
        and results.get("geometry_gate_eligible", False)
    )
    geometry_status = "|".join(
        map(str, results.get("template_geometry_status", ["not_recorded"]))
    )
    power = results["power"]
    three_way = results["three_way"]
    interaction_null = results["interaction_null"]
    three_way_null = results["three_way_null"]
    rows: list[dict[str, Any]] = []
    grouped = _detection_summary(
        power,
        ("effect_size_k", "n_passes"),
        alpha=spec.alpha,
        rate_name="power",
    )
    interaction_error = _detection_summary(
        interaction_null,
        ("n_passes",),
        alpha=spec.alpha,
        rate_name="type_i_error",
    ).set_index("n_passes")
    three_way_error = _detection_summary(
        three_way_null,
        ("n_passes",),
        alpha=spec.alpha,
        rate_name="type_i_error",
    ).set_index("n_passes")
    for effect in spec.effect_sizes_k:
        subset = grouped.loc[grouped["effect_size_k"] == effect].sort_values("n_passes")
        meeting = subset.loc[subset["power"] >= spec.target_power, "n_passes"]
        actual_power = subset.loc[subset["n_passes"] == actual].iloc[0]
        error = interaction_error.loc[actual]
        rows.append(
            {
                "model": "demand_by_dryness",
                "effect_size_k": effect,
                "minimum_passes_for_target_power": int(meeting.iloc[0]) if len(meeting) else np.nan,
                "planning_n_passes": actual,
                "power_at_planning_n": float(actual_power["power"]),
                "power_mc_ci_low": float(actual_power["power_mc_ci_low"]),
                "power_mc_ci_high": float(actual_power["power_mc_ci_high"]),
                "target_power": spec.target_power,
                "statistically_supportable_at_planning_n": bool(
                    float(actual_power["power"]) >= spec.target_power
                ),
                "type_i_error_at_planning_n": float(error["type_i_error"]),
                "type_i_error_mc_ci_low": float(error["type_i_error_mc_ci_low"]),
                "type_i_error_mc_ci_high": float(error["type_i_error_mc_ci_high"]),
                "count_status": count_status,
                "template_geometry_status": geometry_status,
                "scientific_gate_eligible": gate_eligible,
            }
        )
    three = _detection_summary(
        three_way,
        ("n_passes",),
        alpha=spec.alpha,
        rate_name="power",
    )
    meeting = three.loc[three["power"] >= spec.target_power, "n_passes"]
    actual_power = three.loc[three["n_passes"] == actual].iloc[0]
    error = three_way_error.loc[actual]
    rows.append(
        {
            "model": "demand_by_dryness_by_time",
            "effect_size_k": spec.primary_effect_size_k,
            "minimum_passes_for_target_power": int(meeting.iloc[0]) if len(meeting) else np.nan,
            "planning_n_passes": actual,
            "power_at_planning_n": float(actual_power["power"]),
            "power_mc_ci_low": float(actual_power["power_mc_ci_low"]),
            "power_mc_ci_high": float(actual_power["power_mc_ci_high"]),
            "target_power": spec.target_power,
            "statistically_supportable_at_planning_n": bool(
                float(actual_power["power"]) >= spec.target_power
            ),
            "type_i_error_at_planning_n": float(error["type_i_error"]),
            "type_i_error_mc_ci_low": float(error["type_i_error_mc_ci_low"]),
            "type_i_error_mc_ci_high": float(error["type_i_error_mc_ci_high"]),
            "count_status": count_status,
            "template_geometry_status": geometry_status,
            "scientific_gate_eligible": gate_eligible,
        }
    )
    frame = pd.DataFrame(rows)
    detectable = frame.loc[
        (frame["model"] == "demand_by_dryness")
        & frame["statistically_supportable_at_planning_n"],
        "effect_size_k",
    ]
    frame["smallest_detectable_effect_at_planning_n_k"] = (
        float(detectable.min()) if len(detectable) else np.nan
    )
    return frame


def _save_figure(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_step3_deliverables(
    results: Mapping[str, Any],
    output_dir: str | Path,
    *,
    diagnostic_thresholds: DiagnosticThresholds = DiagnosticThresholds(),
) -> dict[str, Path]:
    """Write F3.1-F3.5, T3.1, frozen diagnostics, and a gate memo."""
    root = Path(output_dir)
    figures = root / "figures"
    tables = root / "tables"
    figures.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)
    spec: SimulationSpec = results["spec"]
    actual = int(results["actual_n_passes"])
    count_status = str(results.get("count_status", "not_certified"))
    template_status = str(
        results.get("template_status", "empirical_exact_acquisition_conditions")
    )
    geometry_statuses = list(results.get("template_geometry_status", []))
    geometry_gate_eligible = bool(results.get("geometry_gate_eligible", False))
    gate_eligible = bool(
        count_status in CERTIFIED_COUNT_STATUSES and geometry_gate_eligible
    )
    run_settings = dict(results.get("run_settings", {}))
    power: pd.DataFrame = results["power"]
    transition: pd.DataFrame = results["transition"]
    coverage: pd.DataFrame = results["coverage"]
    support = summarize_support(results)
    diagnostic = evaluate_diagnostic_gate(results, diagnostic_thresholds)
    diagnostic_summary = dict(diagnostic["summary"])
    diagnostic_checks: pd.DataFrame = diagnostic["checks"]
    paths: dict[str, Path] = {}

    power_detection = _detection_summary(
        power,
        ("effect_size_k", "n_passes"),
        alpha=spec.alpha,
        rate_name="power",
    )
    coefficient_summary = (
        power.groupby(["effect_size_k", "n_passes"], as_index=False)
        .agg(power=("detected", "mean"), mean_estimate_k=("estimate_k", "mean"),
             q025_estimate_k=("estimate_k", lambda x: x.quantile(0.025)),
             q975_estimate_k=("estimate_k", lambda x: x.quantile(0.975)))
    )
    power_summary = coefficient_summary.drop(columns="power").merge(
        power_detection,
        on=["effect_size_k", "n_passes"],
        how="inner",
        validate="one_to_one",
    )
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    for effect, group in power_summary.groupby("effect_size_k"):
        ax.errorbar(
            group["n_passes"],
            group["power"],
            yerr=[
                group["power"] - group["power_mc_ci_low"],
                group["power_mc_ci_high"] - group["power"],
            ],
            marker="o",
            capsize=2,
            label=f"{effect:g} K",
        )
    count_label = "certified count" if gate_eligible else "planning ceiling"
    ax.axvline(
        actual, color="black", linestyle="--", label=f"{count_label} ({actual})"
    )
    ax.axhline(spec.target_power, color="0.45", linestyle=":", label=f"target {spec.target_power:.0%}")
    ax.set(xlabel="Independent passes (planning scenarios)", ylabel="Detection probability", ylim=(0, 1.02), title="F3.1 Interaction power")
    ax.legend(frameon=False, ncol=2)
    paths["F3.1"] = figures / "F3.1_power_curves.png"
    _save_figure(fig, paths["F3.1"])

    false_positive = _detection_summary(
        transition,
        ("n_passes",),
        alpha=spec.alpha,
        rate_name="transition_false_positive_rate",
    )
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.errorbar(
        false_positive["n_passes"],
        false_positive["transition_false_positive_rate"],
        yerr=[
            false_positive["transition_false_positive_rate"]
            - false_positive["transition_false_positive_rate_mc_ci_low"],
            false_positive["transition_false_positive_rate_mc_ci_high"]
            - false_positive["transition_false_positive_rate"],
        ],
        marker="o",
        capsize=2,
    )
    ax.axhline(spec.alpha, color="black", linestyle="--", label=f"nominal {spec.alpha:.0%}")
    ax.set(xlabel="Independent passes (planning scenarios)", ylabel="False-positive rate", ylim=(0, max(0.15, false_positive["transition_false_positive_rate_mc_ci_high"].max() * 1.1 + 0.01)), title="F3.2 Smooth truth: false transition detections")
    ax.legend(frameon=False)
    paths["F3.2"] = figures / "F3.2_transition_false_positive.png"
    _save_figure(fig, paths["F3.2"])

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    finite_breaks = transition["best_breakpoint"].dropna()
    ax.hist(finite_breaks, bins=16, color="#8c6bb1", edgecolor="white")
    ax.set(xlabel="Selected breakpoint on smooth stress axis", ylabel="Simulation count", title="F3.3 Spurious breakpoint locations (no true break)")
    paths["F3.3"] = figures / "F3.3_spurious_breakpoints.png"
    _save_figure(fig, paths["F3.3"])

    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    for effect, group in power_summary.groupby("effect_size_k"):
        ax.errorbar(
            group["n_passes"],
            group["mean_estimate_k"],
            yerr=[group["mean_estimate_k"] - group["q025_estimate_k"], group["q975_estimate_k"] - group["mean_estimate_k"]],
            marker="o",
            capsize=3,
            label=f"truth {effect:g} K",
        )
        ax.axhline(effect, color=ax.lines[-1].get_color(), alpha=0.35, linestyle=":")
    ax.set(xlabel="Independent passes (planning scenarios)", ylabel="Estimated interaction (K)", title="F3.4 Recovery of known interaction")
    ax.legend(frameon=False)
    paths["F3.4"] = figures / "F3.4_coefficient_recovery.png"
    _save_figure(fig, paths["F3.4"])

    coverage_detection = _detection_summary(
        coverage.rename(columns={"covered": "detected"}),
        ("method", "n_passes"),
        alpha=spec.alpha,
        rate_name="coverage",
    )
    coverage_width = coverage.groupby(["method", "n_passes"], as_index=False).agg(
        mean_width_k=("interval_width_k", "mean")
    )
    coverage_summary = coverage_width.merge(
        coverage_detection,
        on=["method", "n_passes"],
        how="inner",
        validate="one_to_one",
    )
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    for method, group in coverage_summary.groupby("method"):
        ax.errorbar(
            group["n_passes"],
            group["coverage"],
            yerr=[
                group["coverage"] - group["coverage_mc_ci_low"],
                group["coverage_mc_ci_high"] - group["coverage"],
            ],
            marker="o",
            capsize=2,
            label=method,
        )
    ax.axhline(0.95, color="black", linestyle="--", label="nominal 95%")
    ax.set(xlabel="Independent passes (planning scenarios)", ylabel="95% interval coverage", ylim=(0, 1.02), title="F3.5 Bootstrap coverage")
    ax.legend(frameon=False)
    paths["F3.5"] = figures / "F3.5_bootstrap_coverage.png"
    _save_figure(fig, paths["F3.5"])

    paths["T3.1"] = tables / "T3.1_model_support.csv"
    support.to_csv(paths["T3.1"], index=False)
    error_parts = []
    for test_name, frame in (
        ("demand_by_dryness_null", results["interaction_null"]),
        ("demand_by_dryness_by_time_null", results["three_way_null"]),
        ("smooth_truth_transition_test", transition),
    ):
        part = _detection_summary(
            frame,
            ("n_passes",),
            alpha=spec.alpha,
            rate_name="false_positive_rate",
        )
        part.insert(0, "test", test_name)
        error_parts.append(part)
    model_error_summary = pd.concat(error_parts, ignore_index=True)
    model_error_summary["nominal_alpha"] = spec.alpha
    paths["model_error_summary"] = tables / "model_error_summary.csv"
    model_error_summary.to_csv(paths["model_error_summary"], index=False)
    paths["diagnostic_checks"] = tables / "D3.1_frozen_diagnostic_checks.csv"
    diagnostic_checks.to_csv(paths["diagnostic_checks"], index=False)
    paths["diagnostic_gate"] = root / "step3_diagnostic_gate.json"
    paths["diagnostic_gate"].write_text(
        json.dumps(diagnostic_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["provenance"] = tables / "run_provenance.json"
    paths["provenance"].write_text(
        json.dumps(
            {
                "actual_n_passes": actual,
                "count_status": count_status,
                "template_status": template_status,
                "template_geometry_status": geometry_statuses,
                "geometry_gate_eligible": geometry_gate_eligible,
                "scientific_gate_eligible": gate_eligible,
                "simulation_spec": asdict(spec),
                "diagnostic_thresholds": asdict(diagnostic_thresholds),
                "diagnostic_gate": diagnostic_summary,
                "run_settings": run_settings,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for name, frame in (
        ("power_replicates", power),
        ("transition_replicates", transition),
        ("three_way_replicates", results["three_way"]),
        ("interaction_null_replicates", results["interaction_null"]),
        ("three_way_null_replicates", results["three_way_null"]),
        ("coverage_replicates", coverage),
        ("power_summary", power_summary),
        ("coverage_summary", coverage_summary),
    ):
        path = tables / f"{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = path

    central = support.loc[
        (support["model"] == "demand_by_dryness")
        & (support["effect_size_k"] == spec.primary_effect_size_k)
    ].iloc[0]
    three = support.loc[support["model"] == "demand_by_dryness_by_time"].iloc[0]
    max_fp = float(false_positive["transition_false_positive_rate"].max())
    interaction_type_i = model_error_summary.loc[
        model_error_summary["test"] == "demand_by_dryness_null",
        "false_positive_rate",
    ]
    three_way_type_i = model_error_summary.loc[
        model_error_summary["test"] == "demand_by_dryness_by_time_null",
        "false_positive_rate",
    ]
    failed_checks = diagnostic_summary["failed_check_ids"]
    failed_text = ", ".join(f"`{value}`" for value in failed_checks) or "none"
    memo = root / "M3.1_power_gate.md"
    memo.write_text(
        "# Step 3 simulation and power gate\n\n"
        f"- Planning pass count supplied to the simulation: **{actual}** (`{count_status}`).\n"
        f"- Predictor template status: `{template_status}`.\n"
        f"- Solar-geometry template status: `{geometry_statuses}`; observed-geometry eligible: **{geometry_gate_eligible}**.\n"
        f"- Eligible to satisfy the scientific Step-3 gate: **{gate_eligible}**.\n"
        f"- Frozen D0027 diagnostic verdict: **{diagnostic_summary['status']}** "
        f"({diagnostic_summary['passed_required_checks']}/{diagnostic_summary['total_required_checks']} required checks passed).\n"
        f"- Failed required checks: {failed_text}.\n"
        f"- Monte Carlo profile: **{run_settings.get('n_replicates', 'not recorded')}** power/transition replicates, "
        f"**{run_settings.get('n_coverage_replicates', 'not recorded')}** coverage replicates, and "
        f"**{run_settings.get('n_boot', 'not recorded')}** bootstrap draws per interval.\n"
        f"- Primary interaction effect: **{spec.primary_effect_size_k:g} K**; power at the planning count: **{central['power_at_planning_n']:.1%}**.\n"
        f"- Three-way time-of-day interaction power at the planning count: **{three['power_at_planning_n']:.1%}**; statistically supportable: **{bool(three['statistically_supportable_at_planning_n'])}**.\n"
        f"- Maximum demand-by-dryness null Type-I error across tested counts: **{float(interaction_type_i.max()):.1%}**; "
        f"maximum three-way null Type-I error: **{float(three_way_type_i.max()):.1%}** (nominal {spec.alpha:.1%}).\n"
        f"- Maximum corrected transition-test false-positive rate across tested counts: **{max_fp:.1%}** (nominal {spec.alpha:.1%}).\n"
        "- Uncertainty comparison: whole-pass block bootstrap is primary; row bootstrap is a deliberately naive diagnostic.\n\n"
        + (
            "This is a preliminary ceiling sensitivity, not a definitive power gate, because "
            "the supplied pass count is not yet a certified usable-pass count.\n\n"
            if not gate_eligible
            else ""
        )
        + "Effect-size rationale: the 1.5 K target is materially below published tree-versus-built land-surface-temperature contrasts (often several kelvin), while exceeding the sub-kelvin reported per-retrieval uncertainty cited by the guide. It is a planning target, not an observed effect.\n",
        encoding="utf-8",
    )
    paths["M3.1"] = memo
    return paths


__all__ = [
    "CERTIFIED_COUNT_STATUSES",
    "DiagnosticThresholds",
    "FitResult",
    "LEGACY_PRELIMINARY_GEOMETRY_STATUS",
    "LEGACY_RECONSTRUCTED_GEOMETRY_STATUS",
    "OBSERVED_GEOMETRY_STATUS",
    "SimulationSpec",
    "SYNTHETIC_GEOMETRY_STATUS",
    "bootstrap_interval",
    "evaluate_diagnostic_gate",
    "fit_interaction",
    "run_simulation_study",
    "simulate_clustered_data",
    "simulate_smooth_no_breakpoint",
    "summarize_support",
    "synthetic_pass_template",
    "transition_test",
    "validate_template",
    "write_step3_deliverables",
]
