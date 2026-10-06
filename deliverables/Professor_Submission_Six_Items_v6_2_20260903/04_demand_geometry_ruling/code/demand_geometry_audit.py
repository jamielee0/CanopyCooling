"""Outcome-blind demand--geometry support audit for protocol v6.2 D1a.

This module reads historical nonthermal pass, geometry, and HRRR summaries only.
It never imports the legacy thermal pipeline and never reads an LST value.
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import r2_score
from sklearn.model_selection import LeaveOneOut, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import SplineTransformer, StandardScaler


GATE_CITIES = ("phoenix", "los_angeles")
VIEW_SETS = (15, 25)


@dataclass(frozen=True)
class DecisionThresholds:
    minimum_complete_passes: int = 30
    maximum_vpd_vif: float = 5.0
    maximum_condition_index: float = 30.0
    maximum_nonlinear_concurvity_r2: float = 0.80
    minimum_residual_vpd_sd_kpa: float = 0.25
    minimum_continuous_support_width_kpa: float = 0.50


THRESHOLDS = DecisionThresholds()


INPUT_PATHS = {
    "pass_detail": Path(
        "docs/v2/hitl/G3_SAMPLING_DESIGN/angle_threshold_pass_detail_existing_five.csv"
    ),
    "observation_ledger": Path(
        "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/observation_ledger.csv"
    ),
    "hrrr_crosswalk": Path(
        "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/hrrr_pass_hour_crosswalk.csv"
    ),
    "hrrr_hourly": Path(
        "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo_D0047_archive_available/"
        "hrrr_hourly_domain_summary.csv"
    ),
    "city_config": Path("configs/v2_cities.toml"),
    "source_document_checksums": Path("docs/v2/v6_2/source_document_checksums.txt"),
    "geometry_recovery": Path(
        "data/processed/v2/v6_2/d1a_geometry_recovery/pass_summary.csv"
    ),
    "geometry_recovery_manifest": Path(
        "data/processed/v2/v6_2/d1a_geometry_recovery/manifest.json"
    ),
}


VARIABLE_LABELS = {
    "vpd_kpa": "exact_time_VPD_kPa",
    "air_temperature_k": "exact_time_air_temperature_K",
    "actual_vapour_pressure_kpa": "actual_vapour_pressure_kPa",
    "local_solar_time_hours": "local_solar_time_hours",
    "solar_zenith_deg": "solar_zenith_deg",
    "solar_azimuth_deg": "solar_azimuth_deg",
    "view_zenith_p95_deg": "view_zenith_p95_deg",
    "relative_sun_sensor_azimuth_deg": "relative_sun_sensor_azimuth_deg",
    "day_of_year": "day_of_year",
}


REDUCED_NUISANCE_COLUMNS = [
    "air_temperature_k",
    "actual_vapour_pressure_kpa",
    "local_solar_time_hours",
    "solar_zenith_deg",
    "solar_azimuth_sin",
    "solar_azimuth_cos",
    "view_zenith_p95_deg",
    "day_of_year_sin",
    "day_of_year_cos",
]


FULL_NUISANCE_COLUMNS = REDUCED_NUISANCE_COLUMNS + [
    "view_azimuth_sin",
    "view_azimuth_cos",
    "relative_azimuth_sin",
    "relative_azimuth_cos",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def saturation_vapour_pressure_kpa(temperature_c: np.ndarray | pd.Series) -> Any:
    """Magnus saturation vapour pressure over water, in kPa."""

    values = np.asarray(temperature_c, dtype=float)
    return 0.6108 * np.exp((17.27 * values) / (values + 237.3))


def solar_position_from_local_solar_time(
    latitude_deg: Iterable[float] | float,
    day_of_year: Iterable[float] | float,
    local_solar_time_hours: Iterable[float] | float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return approximate solar zenith and north-clockwise azimuth in degrees.

    Local *solar* time is used, so longitude and equation-of-time correction are
    already absorbed by the input clock.
    """

    latitude = np.deg2rad(np.asarray(latitude_deg, dtype=float))
    doy = np.asarray(day_of_year, dtype=float)
    lst = np.asarray(local_solar_time_hours, dtype=float)
    fractional_year = (2.0 * np.pi / 365.0) * (doy - 1.0 + (lst - 12.0) / 24.0)
    declination = (
        0.006918
        - 0.399912 * np.cos(fractional_year)
        + 0.070257 * np.sin(fractional_year)
        - 0.006758 * np.cos(2.0 * fractional_year)
        + 0.000907 * np.sin(2.0 * fractional_year)
        - 0.002697 * np.cos(3.0 * fractional_year)
        + 0.001480 * np.sin(3.0 * fractional_year)
    )
    hour_angle = np.deg2rad(15.0 * (lst - 12.0))
    cosine_zenith = (
        np.sin(latitude) * np.sin(declination)
        + np.cos(latitude) * np.cos(declination) * np.cos(hour_angle)
    )
    zenith = np.rad2deg(np.arccos(np.clip(cosine_zenith, -1.0, 1.0)))
    azimuth = (
        np.rad2deg(
            np.arctan2(
                np.sin(hour_angle),
                np.cos(hour_angle) * np.sin(latitude)
                - np.tan(declination) * np.cos(latitude),
            )
        )
        + 180.0
    ) % 360.0
    return zenith, azimuth


def _bool_series(values: pd.Series) -> pd.Series:
    return values.astype(str).str.lower().eq("true")


def _load_city_centroids(path: Path) -> dict[str, tuple[float, float]]:
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    cities: dict[str, tuple[float, float]] = {}
    for record in config.get("cities", []):
        slug = str(record["slug"])
        cities[slug] = (float(record["centroid_lat"]), float(record["centroid_lon"]))
    return cities


def _interpolate_exact_weather(
    passes: pd.DataFrame,
    ledger: pd.DataFrame,
    crosswalk: pd.DataFrame,
    hourly: pd.DataFrame,
) -> pd.DataFrame:
    ledger_subset = ledger[["observation_id", "city", "orbit"]].copy()
    ledger_subset["orbit"] = pd.to_numeric(ledger_subset["orbit"], errors="raise").astype(int)
    if ledger_subset.duplicated(["city", "orbit"]).any():
        duplicates = ledger_subset.loc[
            ledger_subset.duplicated(["city", "orbit"], keep=False), ["city", "orbit"]
        ]
        raise ValueError(f"Non-unique city/orbit keys in observation ledger: {duplicates.head()}")

    merged = passes.merge(ledger_subset, on=["city", "orbit"], how="left", validate="many_to_one")
    if merged["observation_id"].isna().any():
        missing = merged.loc[merged["observation_id"].isna(), ["city", "orbit"]]
        raise ValueError(f"Passes absent from observation ledger: {missing.to_dict('records')}")

    cross = crosswalk[["observation_id", "city", "bracket_role", "analysis_utc"]].copy()
    cross["analysis_utc"] = pd.to_datetime(cross["analysis_utc"], utc=True)
    if cross.duplicated(["observation_id", "bracket_role"]).any():
        raise ValueError("HRRR crosswalk has duplicate observation/bracket rows")

    weather = hourly[["city", "timestamp_utc", "t2m_k", "d2m_k"]].copy()
    weather["timestamp_utc"] = pd.to_datetime(weather["timestamp_utc"], utc=True)
    if weather.duplicated(["city", "timestamp_utc"]).any():
        raise ValueError("HRRR hourly summary has duplicate city/timestamp rows")

    cross = cross.merge(
        weather,
        left_on=["city", "analysis_utc"],
        right_on=["city", "timestamp_utc"],
        how="left",
        validate="many_to_one",
    )
    wide = cross.pivot(
        index="observation_id",
        columns="bracket_role",
        values=["analysis_utc", "t2m_k", "d2m_k"],
    )
    wide.columns = [f"{value}_{role}" for value, role in wide.columns]
    wide = wide.reset_index()
    merged = merged.merge(wide, on="observation_id", how="left", validate="many_to_one")

    acquired = pd.to_datetime(merged["acquisition_utc"], utc=True)
    floor_time = pd.to_datetime(merged["analysis_utc_floor"], utc=True)
    ceiling_time = pd.to_datetime(merged["analysis_utc_ceiling"], utc=True)
    duration = (ceiling_time - floor_time).dt.total_seconds()
    elapsed = (acquired - floor_time).dt.total_seconds()
    weight = np.where(duration > 0.0, elapsed / duration, 0.0)
    merged["hrrr_interpolation_weight"] = weight
    for source, target in (("t2m_k", "air_temperature_k"), ("d2m_k", "dewpoint_k")):
        floor_values = pd.to_numeric(merged[f"{source}_floor"], errors="coerce")
        ceiling_values = pd.to_numeric(merged[f"{source}_ceiling"], errors="coerce")
        merged[target] = floor_values + weight * (ceiling_values - floor_values)
    merged["actual_vapour_pressure_kpa"] = saturation_vapour_pressure_kpa(
        merged["dewpoint_k"] - 273.15
    )
    return merged


def load_analysis_passes(repo_root: Path) -> pd.DataFrame:
    resolved = {key: repo_root / relative for key, relative in INPUT_PATHS.items()}
    detail = pd.read_csv(resolved["pass_detail"])
    detail = detail.loc[
        detail["city"].isin(GATE_CITIES)
        & pd.to_numeric(detail["threshold_deg"], errors="coerce").isin(VIEW_SETS)
        & _bool_series(detail["quality_and_exact_weather_complete"])
    ].copy()
    detail["orbit"] = pd.to_numeric(detail["orbit"], errors="raise").astype(int)
    detail["view_set_max_deg"] = pd.to_numeric(detail["threshold_deg"], errors="raise").astype(int)
    detail["vpd_kpa"] = pd.to_numeric(detail["vpd_kpa_at_acquisition"], errors="coerce")
    detail["view_zenith_p95_deg"] = pd.to_numeric(
        detail["view_zenith_abs_p95_deg"], errors="coerce"
    )
    detail["local_solar_time_hours"] = pd.to_numeric(
        detail["local_solar_time_hours"], errors="coerce"
    )
    recovery_manifest = json.loads(
        resolved["geometry_recovery_manifest"].read_text(encoding="utf-8")
    )
    if not (
        recovery_manifest.get("source_product") == "ECO_L1B_GEO.002"
        and recovery_manifest.get("candidate_passes") == 92
        and recovery_manifest.get("temperature_or_lst_opened") is False
        and recovery_manifest.get("new_v6_2_coefficient_opened") is False
    ):
        raise ValueError("D1a geometry-recovery manifest is not admissible")
    geometry = pd.read_csv(resolved["geometry_recovery"])
    required_geometry = {
        "city",
        "orbit",
        "view_azimuth_circular_mean_deg",
        "relative_azimuth_median_deg",
        "azimuth_valid_fraction_of_view_cells",
        "geometry_azimuth_complete",
        "geometry_azimuth_status",
        "temperature_or_lst_opened",
        "record_2026_opened",
    }
    missing_geometry = sorted(required_geometry.difference(geometry.columns))
    if missing_geometry or len(geometry) != 92 or geometry.duplicated(["city", "orbit"]).any():
        raise ValueError(f"D1a geometry recovery is not ledger-complete: {missing_geometry}")
    geometry["orbit"] = pd.to_numeric(geometry["orbit"], errors="raise").astype(int)
    complete_geometry = (
        _bool_series(geometry["geometry_azimuth_complete"])
        & geometry["geometry_azimuth_status"].astype(str).eq("COMPLETE")
        & pd.to_numeric(
            geometry["azimuth_valid_fraction_of_view_cells"], errors="coerce"
        ).eq(1.0)
        & pd.to_numeric(
            geometry["view_azimuth_circular_mean_deg"], errors="coerce"
        ).notna()
        & pd.to_numeric(geometry["relative_azimuth_median_deg"], errors="coerce").notna()
        & ~_bool_series(geometry["temperature_or_lst_opened"])
        & ~_bool_series(geometry["record_2026_opened"])
    )
    geometry["view_azimuth_deg_recovered"] = np.where(
        complete_geometry,
        pd.to_numeric(geometry["view_azimuth_circular_mean_deg"], errors="coerce"),
        np.nan,
    )
    geometry["relative_azimuth_deg_recovered"] = np.where(
        complete_geometry,
        pd.to_numeric(geometry["relative_azimuth_median_deg"], errors="coerce"),
        np.nan,
    )
    geometry["recovered_azimuth_complete"] = complete_geometry
    detail = detail.merge(
        geometry[
            [
                "city",
                "orbit",
                "view_azimuth_deg_recovered",
                "relative_azimuth_deg_recovered",
                "recovered_azimuth_complete",
            ]
        ],
        on=["city", "orbit"],
        how="left",
        validate="many_to_one",
    )
    if detail["recovered_azimuth_complete"].isna().any():
        raise ValueError("A D1a analysis pass lacks a geometry-recovery ledger row")
    detail["view_azimuth_deg"] = detail["view_azimuth_deg_recovered"]
    detail["relative_sun_sensor_azimuth_deg"] = detail[
        "relative_azimuth_deg_recovered"
    ]

    ledger = pd.read_csv(resolved["observation_ledger"])
    crosswalk = pd.read_csv(resolved["hrrr_crosswalk"])
    hourly = pd.read_csv(resolved["hrrr_hourly"])
    passes = _interpolate_exact_weather(detail, ledger, crosswalk, hourly)
    passes["local_solar_date"] = pd.to_datetime(passes["acquisition_utc"], utc=True).dt.date
    passes["day_of_year"] = pd.to_datetime(passes["local_solar_date"]).dt.dayofyear.astype(float)

    centroids = _load_city_centroids(resolved["city_config"])
    passes["centroid_lat"] = passes["city"].map(lambda city: centroids[city][0])
    passes["centroid_lon"] = passes["city"].map(lambda city: centroids[city][1])
    zenith, azimuth = solar_position_from_local_solar_time(
        passes["centroid_lat"], passes["day_of_year"], passes["local_solar_time_hours"]
    )
    passes["solar_zenith_deg"] = zenith
    passes["solar_azimuth_deg"] = azimuth
    passes["solar_azimuth_sin"] = np.sin(np.deg2rad(azimuth))
    passes["solar_azimuth_cos"] = np.cos(np.deg2rad(azimuth))
    passes["day_of_year_sin"] = np.sin(2.0 * np.pi * passes["day_of_year"] / 365.25)
    passes["day_of_year_cos"] = np.cos(2.0 * np.pi * passes["day_of_year"] / 365.25)
    passes["view_azimuth_sin"] = np.sin(np.deg2rad(passes["view_azimuth_deg"]))
    passes["view_azimuth_cos"] = np.cos(np.deg2rad(passes["view_azimuth_deg"]))
    passes["relative_azimuth_sin"] = np.sin(
        np.deg2rad(passes["relative_sun_sensor_azimuth_deg"])
    )
    passes["relative_azimuth_cos"] = np.cos(
        np.deg2rad(passes["relative_sun_sensor_azimuth_deg"])
    )
    passes["view_azimuth_source_complete"] = _bool_series(
        passes["recovered_azimuth_complete"]
    )
    passes["relative_azimuth_source_complete"] = _bool_series(
        passes["recovered_azimuth_complete"]
    )
    return passes


def condition_index(matrix: pd.DataFrame) -> tuple[float, int]:
    numeric = matrix.astype(float)
    varying = numeric.loc[:, numeric.std(ddof=0) > 1e-12]
    if varying.empty:
        return math.inf, 0
    standardized = StandardScaler().fit_transform(varying)
    singular_values = np.linalg.svd(standardized, compute_uv=False)
    rank = int(np.linalg.matrix_rank(standardized))
    if singular_values.size == 0 or singular_values[-1] <= 1e-12:
        return math.inf, rank
    return float(singular_values[0] / singular_values[-1]), rank


def vpd_linear_diagnostics(frame: pd.DataFrame, nuisance_columns: list[str]) -> tuple[float, float]:
    y = frame["vpd_kpa"].to_numpy(dtype=float)
    x = frame[nuisance_columns].to_numpy(dtype=float)
    score = float(LinearRegression().fit(x, y).score(x, y))
    vif = math.inf if score >= 1.0 - 1e-12 else 1.0 / (1.0 - score)
    return score, float(vif)


def vpd_nonlinear_concurvity(frame: pd.DataFrame) -> tuple[float, float]:
    continuous = [
        "air_temperature_k",
        "actual_vapour_pressure_kpa",
        "local_solar_time_hours",
        "solar_zenith_deg",
        "view_zenith_p95_deg",
        "day_of_year",
    ]
    circular = ["solar_azimuth_sin", "solar_azimuth_cos"]
    x = frame[continuous + circular]
    y = frame["vpd_kpa"].to_numpy(dtype=float)
    transformer = ColumnTransformer(
        [
            (
                "continuous_splines",
                Pipeline(
                    [
                        (
                            "spline",
                            SplineTransformer(n_knots=4, degree=3, include_bias=False),
                        ),
                        ("scale", StandardScaler()),
                    ]
                ),
                continuous,
            ),
            ("circular", StandardScaler(), circular),
        ]
    )
    model = Pipeline([("basis", transformer), ("ridge", Ridge(alpha=1.0))])
    prediction = cross_val_predict(model, x, y, cv=LeaveOneOut(), n_jobs=1)
    return float(r2_score(y, prediction)), float(np.std(y - prediction, ddof=1))


def continuous_vpd_support(
    frame: pd.DataFrame,
    stratifiers: tuple[str, ...] = (
        "local_solar_time_hours",
        "solar_zenith_deg",
        "day_of_year",
    ),
) -> dict[str, Any]:
    intervals: list[dict[str, Any]] = []
    for stratifier in stratifiers:
        groups = pd.qcut(frame[stratifier], q=3, labels=False, duplicates="drop")
        for group in sorted(pd.Series(groups).dropna().unique()):
            values = frame.loc[groups == group, "vpd_kpa"].dropna().to_numpy(dtype=float)
            intervals.append(
                {
                    "stratifier": stratifier,
                    "tertile": int(group) + 1,
                    "n": int(values.size),
                    "vpd_p10_kpa": float(np.quantile(values, 0.10)),
                    "vpd_p90_kpa": float(np.quantile(values, 0.90)),
                }
            )
    lower = max(item["vpd_p10_kpa"] for item in intervals)
    upper = min(item["vpd_p90_kpa"] for item in intervals)
    has_overlap = bool(upper >= lower)
    return {
        "low_kpa": float(lower) if has_overlap else None,
        "high_kpa": float(upper) if has_overlap else None,
        "intersection_lower_bound_kpa": float(lower),
        "intersection_upper_bound_kpa": float(upper),
        "has_overlap": has_overlap,
        "width_kpa": float(max(0.0, upper - lower)),
        "intervals": intervals,
    }


def build_pairwise_rows(passes: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    columns = list(VARIABLE_LABELS)
    for city in GATE_CITIES:
        view_set = 25
        block = passes.loc[
            (passes["city"] == city) & (passes["view_set_max_deg"] == view_set)
        ]
        for left_index, left in enumerate(columns):
            for right in columns[left_index:]:
                pair_columns = [left] if left == right else [left, right]
                pair = block[pair_columns].dropna()
                n_pair = int(len(pair))
                pearson = None
                spearman = None
                if left == right and n_pair >= 1:
                    pearson = 1.0
                    spearman = 1.0
                elif n_pair >= 3 and pair[left].nunique() > 1 and pair[right].nunique() > 1:
                    pearson = float(pair[left].corr(pair[right], method="pearson"))
                    spearman = float(pair[left].corr(pair[right], method="spearman"))
                rows.append(
                    {
                        "city": city,
                        "view_set_max_deg": view_set,
                        "variable_1": VARIABLE_LABELS[left],
                        "variable_2": VARIABLE_LABELS[right],
                        "n_pair": n_pair,
                        "pearson_r": pearson,
                        "spearman_rho": spearman,
                        "role": "descriptive_nonbinding_binding_25deg_set",
                    }
                )
    return rows


PARSIMONIOUS_SPECS = {
    "primary_time_geometry": ["solar_zenith_deg", "view_zenith_p95_deg"],
    "plus_air_temperature_only": [
        "solar_zenith_deg",
        "view_zenith_p95_deg",
        "air_temperature_k",
    ],
    "plus_actual_vapour_pressure_only": [
        "solar_zenith_deg",
        "view_zenith_p95_deg",
        "actual_vapour_pressure_kpa",
    ],
}


def parsimonious_nonlinear_concurvity(
    frame: pd.DataFrame, continuous_columns: list[str]
) -> tuple[float, float]:
    basis: dict[str, np.ndarray] = {}
    for column in continuous_columns:
        values = frame[column].to_numpy(dtype=float)
        basis[column] = values
        basis[f"{column}_squared"] = values**2
    basis["day_of_year_sin"] = frame["day_of_year_sin"].to_numpy(dtype=float)
    basis["day_of_year_cos"] = frame["day_of_year_cos"].to_numpy(dtype=float)
    x = pd.DataFrame(basis, index=frame.index)
    y = frame["vpd_kpa"].to_numpy(dtype=float)
    model = Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=1.0))])
    prediction = cross_val_predict(model, x, y, cv=LeaveOneOut(), n_jobs=1)
    return float(r2_score(y, prediction)), float(np.std(y - prediction, ddof=1))


def build_parsimonious_sensitivity(passes: pd.DataFrame) -> dict[str, Any]:
    """Evaluate the user-requested, non-binding 15-degree sensitivity."""

    thresholds = {
        "minimum_complete_passes": 15,
        "maximum_vpd_vif": 5.0,
        "maximum_condition_index": 30.0,
        "maximum_nonlinear_concurvity_r2": 0.80,
        "minimum_residual_vpd_sd_kpa": 0.25,
        "minimum_continuous_support_width_kpa": 0.50,
    }
    rows: list[dict[str, Any]] = []
    primary_support: dict[str, dict[str, Any]] = {}
    for city in GATE_CITIES:
        city_block = passes.loc[
            (passes["city"] == city) & (passes["view_set_max_deg"] == 15)
        ].copy()
        support = continuous_vpd_support(
            city_block,
            stratifiers=("solar_zenith_deg", "day_of_year"),
        )
        primary_support[city] = support
        for specification, continuous_columns in PARSIMONIOUS_SPECS.items():
            linear_nuisance = continuous_columns + ["day_of_year_sin", "day_of_year_cos"]
            required = ["vpd_kpa", "day_of_year"] + linear_nuisance
            block = city_block.dropna(subset=required).copy()
            max_condition_index, rank = condition_index(
                block[["vpd_kpa"] + linear_nuisance]
            )
            linear_r2, vif = vpd_linear_diagnostics(block, linear_nuisance)
            nonlinear_r2, residual_sd = parsimonious_nonlinear_concurvity(
                block, continuous_columns
            )
            is_primary = specification == "primary_time_geometry"
            criteria = {
                "complete_passes": len(block) >= thresholds["minimum_complete_passes"],
                "vpd_vif": vif <= thresholds["maximum_vpd_vif"],
                "condition_index": max_condition_index
                <= thresholds["maximum_condition_index"],
                "nonlinear_concurvity": nonlinear_r2
                <= thresholds["maximum_nonlinear_concurvity_r2"],
                "residual_vpd_sd": residual_sd
                >= thresholds["minimum_residual_vpd_sd_kpa"],
                "continuous_support_width": support["width_kpa"]
                >= thresholds["minimum_continuous_support_width_kpa"],
            }
            rows.append(
                {
                    "city": city,
                    "specification": specification,
                    "role": "binding_for_sensitivity" if is_primary else "non_vetoing_interpretation",
                    "n_complete": int(len(block)),
                    "design_rank": rank,
                    "maximum_condition_index": max_condition_index,
                    "vpd_linear_concurvity_r2": linear_r2,
                    "vpd_vif": vif,
                    "vpd_nonlinear_cv_concurvity_r2": nonlinear_r2,
                    "residual_vpd_sd_kpa": residual_sd,
                    "continuous_support_low_kpa": support["low_kpa"],
                    "continuous_support_high_kpa": support["high_kpa"],
                    "continuous_support_intersection_lower_bound_kpa": support[
                        "intersection_lower_bound_kpa"
                    ],
                    "continuous_support_intersection_upper_bound_kpa": support[
                        "intersection_upper_bound_kpa"
                    ],
                    "continuous_support_width_kpa": support["width_kpa"],
                    "criteria_pass": criteria,
                    "all_primary_criteria_pass": all(criteria.values()) if is_primary else None,
                    "failed_primary_criteria": (
                        "|".join(name for name, passed in criteria.items() if not passed)
                        if is_primary
                        else ""
                    ),
                }
            )
    binding = [row for row in rows if row["role"] == "binding_for_sensitivity"]
    sensitivity_keep = len(binding) == len(GATE_CITIES) and all(
        row["all_primary_criteria_pass"] for row in binding
    )
    return {
        "decision_id": "V6.2-D004",
        "status": "NON_BINDING_SENSITIVITY",
        "controlling_D003_ruling_changed": False,
        "outcome_access": "none; historical nonthermal provenance only",
        "new_v6_2_coefficients_viewed": False,
        "sensitivity_ruling": "KEEP" if sensitivity_keep else "DROP",
        "thresholds": thresholds,
        "rows": rows,
        "binding_rows": binding,
        "support_details": primary_support,
        "interpretation": (
            "Parsimonious support criteria pass in both cities; a supervisor-approved "
            "pre-coefficient amendment would be required to replace D003."
            if sensitivity_keep
            else "Parsimonious support criteria still fail in at least one city; D003 remains unchanged."
        ),
    }


def _criterion(value: float | int | None, operator: str, threshold: float) -> bool:
    if value is None or not np.isfinite(float(value)):
        return False
    if operator == "ge":
        return float(value) >= threshold
    if operator == "le":
        return float(value) <= threshold
    raise ValueError(operator)


def build_condition_rows(passes: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    full_required = ["vpd_kpa"] + FULL_NUISANCE_COLUMNS
    reduced_required = ["vpd_kpa"] + REDUCED_NUISANCE_COLUMNS + ["day_of_year"]
    for city in GATE_CITIES:
        for view_set in VIEW_SETS:
            block = passes.loc[
                (passes["city"] == city) & (passes["view_set_max_deg"] == view_set)
            ].copy()
            full = block.dropna(subset=full_required)
            reduced = block.dropna(subset=reduced_required)
            support = continuous_vpd_support(reduced)
            reduced_ci, reduced_rank = condition_index(
                reduced[["vpd_kpa"] + REDUCED_NUISANCE_COLUMNS]
            )
            linear_r2, reduced_vif = vpd_linear_diagnostics(reduced, REDUCED_NUISANCE_COLUMNS)
            nonlinear_r2, residual_sd = vpd_nonlinear_concurvity(reduced)

            full_ci: float | None = None
            full_rank: int | None = None
            full_vif: float | None = None
            full_linear_r2: float | None = None
            full_nonlinear_r2: float | None = None
            full_residual_sd: float | None = None
            # The frozen full-design diagnostics are not reported from a pass
            # set below the predeclared minimum.  With fewer observations than
            # the design requires, VIF/condition-index values can be infinite
            # or deceptively finite depending only on rank deficiency.
            if len(full) >= THRESHOLDS.minimum_complete_passes:
                full_ci, full_rank = condition_index(full[["vpd_kpa"] + FULL_NUISANCE_COLUMNS])
                full_linear_r2, full_vif = vpd_linear_diagnostics(full, FULL_NUISANCE_COLUMNS)
                full_nonlinear_r2, full_residual_sd = vpd_nonlinear_concurvity(full)

            criteria = {
                "complete_passes": len(full) >= THRESHOLDS.minimum_complete_passes,
                "vpd_vif": _criterion(full_vif, "le", THRESHOLDS.maximum_vpd_vif),
                "condition_index": _criterion(
                    full_ci, "le", THRESHOLDS.maximum_condition_index
                ),
                "nonlinear_concurvity": _criterion(
                    full_nonlinear_r2,
                    "le",
                    THRESHOLDS.maximum_nonlinear_concurvity_r2,
                ),
                "residual_vpd_sd": _criterion(
                    full_residual_sd,
                    "ge",
                    THRESHOLDS.minimum_residual_vpd_sd_kpa,
                ),
                "continuous_support_width": _criterion(
                    support["width_kpa"],
                    "ge",
                    THRESHOLDS.minimum_continuous_support_width_kpa,
                ),
            }
            failed = [name for name, passed in criteria.items() if not passed]
            rows.append(
                {
                    "city": city,
                    "view_set_max_deg": view_set,
                    "binding_for_ruling": view_set == 25,
                    "n_quality_weather_passes": int(len(block)),
                    "n_full_design_complete": int(len(full)),
                    "full_design_complete_fraction": float(len(full) / len(block)) if len(block) else 0.0,
                    "n_reduced_design_complete": int(len(reduced)),
                    "missing_view_azimuth_passes": int(block["view_azimuth_deg"].isna().sum()),
                    "missing_relative_azimuth_passes": int(
                        block["relative_sun_sensor_azimuth_deg"].isna().sum()
                    ),
                    "full_design_rank": full_rank,
                    "full_max_condition_index": full_ci,
                    "full_vpd_linear_concurvity_r2": full_linear_r2,
                    "full_vpd_vif": full_vif,
                    "full_vpd_nonlinear_cv_concurvity_r2": full_nonlinear_r2,
                    "full_residual_vpd_sd_kpa": full_residual_sd,
                    "reduced_design_rank_nonbinding": reduced_rank,
                    "reduced_max_condition_index_nonbinding": reduced_ci,
                    "reduced_vpd_linear_concurvity_r2_nonbinding": linear_r2,
                    "reduced_vpd_vif_nonbinding": reduced_vif,
                    "reduced_vpd_nonlinear_cv_concurvity_r2_nonbinding": nonlinear_r2,
                    "reduced_residual_vpd_sd_kpa_nonbinding": residual_sd,
                    "continuous_support_low_kpa": support["low_kpa"],
                    "continuous_support_high_kpa": support["high_kpa"],
                    "continuous_support_intersection_lower_bound_kpa": support[
                        "intersection_lower_bound_kpa"
                    ],
                    "continuous_support_intersection_upper_bound_kpa": support[
                        "intersection_upper_bound_kpa"
                    ],
                    "continuous_support_has_overlap": support["has_overlap"],
                    "continuous_support_width_kpa": support["width_kpa"],
                    "minimum_complete_passes_threshold": THRESHOLDS.minimum_complete_passes,
                    "maximum_vpd_vif_threshold": THRESHOLDS.maximum_vpd_vif,
                    "maximum_condition_index_threshold": THRESHOLDS.maximum_condition_index,
                    "maximum_nonlinear_concurvity_r2_threshold": THRESHOLDS.maximum_nonlinear_concurvity_r2,
                    "minimum_residual_vpd_sd_kpa_threshold": THRESHOLDS.minimum_residual_vpd_sd_kpa,
                    "minimum_continuous_support_width_kpa_threshold": THRESHOLDS.minimum_continuous_support_width_kpa,
                    "complete_passes_criterion_pass": criteria["complete_passes"],
                    "vpd_vif_criterion_pass": criteria["vpd_vif"],
                    "condition_index_criterion_pass": criteria["condition_index"],
                    "nonlinear_concurvity_criterion_pass": criteria[
                        "nonlinear_concurvity"
                    ],
                    "residual_vpd_sd_criterion_pass": criteria["residual_vpd_sd"],
                    "continuous_support_width_criterion_pass": criteria[
                        "continuous_support_width"
                    ],
                    "all_binding_criteria_pass": all(criteria.values()),
                    "failed_criteria": "|".join(failed),
                    "city_view_set_ruling": "KEEP" if all(criteria.values()) else "DROP",
                    "diagnostic_note": (
                        "Full candidate design is binding; reduced design omits unavailable "
                        "view and relative azimuth and is reported only as an optimistic, nonbinding check."
                    ),
                }
            )
    return rows


def run_audit(repo_root: Path) -> dict[str, Any]:
    passes = load_analysis_passes(repo_root)
    pairwise_rows = build_pairwise_rows(passes)
    condition_rows = build_condition_rows(passes)
    binding = [row for row in condition_rows if row["binding_for_ruling"]]
    keep = len(binding) == len(GATE_CITIES) and all(
        row["all_binding_criteria_pass"] for row in binding
    )
    ruling = "KEEP" if keep else "DROP"
    input_evidence = []
    for name, relative in INPUT_PATHS.items():
        path = repo_root / relative
        input_evidence.append(
            {
                "name": name,
                "path": str(relative),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    pass_columns = [
        "city",
        "orbit",
        "acquisition_utc",
        "local_solar_date",
        "view_set_max_deg",
        "vpd_kpa",
        "air_temperature_k",
        "dewpoint_k",
        "actual_vapour_pressure_kpa",
        "local_solar_time_hours",
        "solar_zenith_deg",
        "solar_azimuth_deg",
        "view_zenith_p95_deg",
        "view_azimuth_deg",
        "relative_sun_sensor_azimuth_deg",
        "day_of_year",
    ]
    plot_frame = passes[pass_columns].copy()
    plot_frame["local_solar_date"] = plot_frame["local_solar_date"].astype(str)
    return {
        "audit": "v6.2 D1a demand--geometry support",
        "decision_id": "V6.2-D002",
        "outcome_access": "none; historical nonthermal provenance only",
        "new_v6_2_coefficients_viewed": False,
        "ruling": ruling,
        "branch_action": (
            "retain both W_tree x VPD and W_bg x VPD"
            if keep
            else "drop both VPD interactions, remove RQ2, and use average daytime effects"
        ),
        "thresholds": THRESHOLDS.__dict__,
        "binding_rows": binding,
        "pairwise_rows": pairwise_rows,
        "condition_rows": condition_rows,
        "plot_rows": plot_frame.replace({np.nan: None}).to_dict("records"),
        "input_evidence": input_evidence,
    }


def write_analysis_json(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
