"""Deterministic illustrative outputs for Guide Steps 9--13.

This module is deliberately outside the canonical evidence chain.  It consumes
only the synthetic tables produced by :mod:`illustrative_steps02_08`, writes
visibly labelled demonstrations, and never reads project data, thermal rasters,
credentials, or network resources.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


BANNER = "ILLUSTRATIVE — SYNTHETIC DATA — NOT A STUDY RESULT"
DATA_ORIGIN = "synthetic"
CANONICAL_ELIGIBLE = "false"
FILE_PREFIX = "ILLUSTRATIVE_"


@dataclass(frozen=True)
class _OutputPaths:
    tables: Path
    figures: Path


def _load_shared_synthetic_data(seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the exact shared synthetic-data API, failing clearly on mismatch."""

    try:
        from urban_cooling_v2.illustrative_steps02_08 import generate_synthetic_data
    except ImportError as exc:  # pragma: no cover - integration failure path
        raise RuntimeError(
            "Illustrative Steps 9--13 require "
            "urban_cooling_v2.illustrative_steps02_08.generate_synthetic_data"
        ) from exc
    result = generate_synthetic_data(seed=seed)
    if (
        not isinstance(result, tuple)
        or len(result) != 2
        or not all(isinstance(value, pd.DataFrame) for value in result)
    ):
        raise TypeError(
            "generate_synthetic_data(seed=...) must return (pass_df, matched_df)"
        )
    pass_df, matched_df = result
    if pass_df.empty or matched_df.empty:
        raise ValueError("Shared synthetic pass and matched tables must both be non-empty")
    return pass_df.copy(), matched_df.copy()


def _find_column(frame: pd.DataFrame, aliases: Sequence[str]) -> str | None:
    return next((name for name in aliases if name in frame.columns), None)


def _copy_column(
    target: pd.DataFrame,
    source: pd.DataFrame,
    name: str,
    aliases: Sequence[str],
) -> bool:
    column = _find_column(source, (name, *aliases))
    if column is None:
        return False
    target[name] = source[column].to_numpy(copy=True)
    return True


def _stable_city_number(city: pd.Series) -> pd.Series:
    labels = sorted(city.astype(str).unique())
    mapping = {label: index for index, label in enumerate(labels)}
    return city.astype(str).map(mapping).astype(float)


def _normalize_synthetic_tables(
    pass_df: pd.DataFrame,
    matched_df: pd.DataFrame,
    *,
    seed: int,
) -> pd.DataFrame:
    """Convert the shared tables to the compact Step-9 analysis schema.

    Aliases make the consumer tolerant to harmless naming differences while
    still requiring the shared generator and its row-level identifiers.
    Missing *derived* illustrative covariates are deterministically constructed
    from those shared rows; no alternative source dataset is generated here.
    """

    rng = np.random.default_rng(seed + 9_013)
    work = pd.DataFrame(index=np.arange(len(matched_df)))

    aliases: Mapping[str, Sequence[str]] = {
        "city": ("sim_city", "city_id"),
        "pass_id": ("synthetic_pass_id", "scene_id", "overpass_id"),
        "matched_set_id": ("synthetic_matched_set_id", "set_id", "pair_id"),
        "pass_timestamp_utc": (
            "synthetic_acquisition_utc",
            "acquisition_utc",
            "timestamp_utc",
            "time",
        ),
        "local_solar_time_hours": (
            "synthetic_local_solar_time_hours",
            "local_solar_time",
            "local_solar_hour",
            "local_hour",
        ),
        "time_stratum": ("local_time_stratum", "stratum"),
        "solar_zenith_deg": ("synthetic_solar_zenith_deg", "solar_zenith"),
        "solar_azimuth_deg": ("synthetic_solar_azimuth_deg", "solar_azimuth"),
        "view_zenith_deg": ("synthetic_view_zenith_deg", "view_zenith", "view_angle_deg"),
        "demand_vpd_kpa": (
            "synthetic_hrrr_vpd_kpa",
            "synthetic_interpolated_vpd_kpa",
            "vpd_kpa",
            "synthetic_vpd_kpa",
            "demand_kpa",
        ),
        "antecedent_dryness_percentile": (
            "synthetic_dryness_pct",
            "synthetic_demand_pct",
            "dryness_percentile",
            "synthetic_dryness_percentile",
        ),
        "water_balance_30_mm": (
            "antecedent_water_balance_30_mm",
            "synthetic_water_balance_30_mm",
        ),
        "water_balance_60_mm": (
            "antecedent_water_balance_60_mm",
            "synthetic_water_balance_60_mm",
        ),
        "canopy_fraction": ("tree_canopy_fraction", "synthetic_canopy_fraction"),
        "reference_canopy_fraction": ("ref_canopy_fraction",),
        "tree_albedo": ("synthetic_tree_albedo", "synthetic_albedo"),
        "reference_albedo": ("synthetic_reference_albedo",),
        "incoming_shortwave_wm2": (
            "synthetic_incoming_radiation_w_m2",
            "shortwave_wm2",
            "synthetic_shortwave_wm2",
        ),
        "net_radiation_wm2": (
            "synthetic_net_radiation_w_m2",
            "synthetic_net_radiation_wm2",
        ),
        "air_temperature_k": (
            "synthetic_t2m_k",
            "air_temp_k",
            "synthetic_air_temperature_k",
        ),
        "dewpoint_k": ("synthetic_dewpoint_k",),
        "wind_speed_ms": ("synthetic_wind_speed_ms",),
        "buffer_impervious_fraction": ("impervious_buffer_fraction",),
        "building_fraction": ("synthetic_building_fraction",),
        "elevation_m": ("synthetic_elevation_m",),
        "distance_to_water_m": ("synthetic_distance_to_water_m",),
        "background_climate_index": ("synthetic_background_climate_index",),
        "irrigation_evidence_class": ("synthetic_irrigation_evidence_class",),
        "cloud_survival_fraction": ("synthetic_cloud_survival_fraction",),
        "classification_precision": ("synthetic_classification_precision",),
        "classification_recall": ("synthetic_classification_recall",),
        "matching_max_smd": ("synthetic_matching_max_smd",),
        "registration_shift_k": ("synthetic_registration_shift_k",),
        "synthetic_tree_temperature_k": (
            "synthetic_tree_lst_k",
            "synthetic_tree_temp_k",
            "tree_temperature_k",
            "mean_tree_temperature_k",
        ),
        "synthetic_reference_temperature_k": (
            "synthetic_reference_lst_k",
            "synthetic_reference_temp_k",
            "reference_temperature_k",
            "mean_reference_temperature_k",
        ),
        "synthetic_cooling_contrast_k": (
            "cooling_contrast_k",
            "synthetic_cooling_k",
            "cooling_advantage",
        ),
    }
    for name, names in aliases.items():
        _copy_column(work, matched_df, name, names)

    # Bring pass-level fields across when the matched table intentionally keeps
    # only a pass key.  The merge is deterministic and never touches disk.
    pass_key_match = _find_column(matched_df, ("pass_id", "synthetic_pass_id", "overpass_id"))
    pass_key_source = _find_column(pass_df, ("pass_id", "synthetic_pass_id", "overpass_id"))
    city_match = _find_column(matched_df, ("city", "sim_city", "city_id"))
    city_source = _find_column(pass_df, ("city", "sim_city", "city_id"))
    if pass_key_match and pass_key_source:
        left = matched_df[[pass_key_match]].copy()
        left["__row"] = np.arange(len(left))
        right = pass_df.copy().rename(columns={pass_key_source: pass_key_match})
        keys = [pass_key_match]
        if city_match and city_source:
            left[city_match] = matched_df[city_match].to_numpy()
            right = right.rename(columns={city_source: city_match})
            keys.append(city_match)
        right = right.drop_duplicates(keys)
        joined = left.merge(right, on=keys, how="left", validate="many_to_one").sort_values("__row")
        for name, names in aliases.items():
            if name in work:
                continue
            column = _find_column(joined, (name, *names))
            if column is not None:
                work[name] = joined[column].to_numpy(copy=True)

    missing_ids = {"city", "pass_id", "matched_set_id"} - set(work.columns)
    if missing_ids:
        raise ValueError(
            "Shared synthetic matched table lacks required identifiers: "
            + ", ".join(sorted(missing_ids))
        )
    work["city"] = work["city"].astype(str)
    invalid_city = ~work["city"].str.fullmatch(r"sim_city_[A-Za-z0-9_]+")
    if invalid_city.any():
        examples = sorted(work.loc[invalid_city, "city"].unique())[:5]
        raise ValueError(f"Illustrative data must use generic sim_city names; found {examples}")

    if "pass_timestamp_utc" not in work:
        raise ValueError("Shared synthetic data lacks a pass timestamp")
    timestamp = pd.to_datetime(work["pass_timestamp_utc"], utc=True, errors="coerce")
    if timestamp.isna().any():
        raise ValueError("Shared synthetic pass timestamps contain invalid values")
    work["pass_timestamp_utc"] = timestamp
    work["year"] = timestamp.dt.year.astype(int)
    work["day_of_year"] = timestamp.dt.dayofyear.astype(int)

    n = len(work)
    city_number = _stable_city_number(work["city"])
    if "local_solar_time_hours" not in work:
        work["local_solar_time_hours"] = 10.2 + (pd.factorize(work["pass_id"])[0] % 40) / 5.2
    local_time = pd.to_numeric(work["local_solar_time_hours"], errors="coerce")
    if local_time.isna().any():
        raise ValueError("local solar time must be numeric")
    work["local_solar_time_hours"] = local_time
    if "time_stratum" not in work:
        work["time_stratum"] = pd.cut(
            local_time,
            bins=[-np.inf, 6, 10, 12, 14, 16, 18, np.inf],
            labels=["night", "other", "10-12", "12-14", "14-16", "16-18", "night"],
            ordered=False,
        ).astype(str)
    work["time_stratum"] = work["time_stratum"].astype(str).str.lower().replace(
        {"late_morning": "10-12", "midday": "12-14", "afternoon": "14-16", "late_afternoon": "16-18"}
    )
    work["is_day"] = work["time_stratum"].isin(["10-12", "12-14", "14-16", "16-18"])

    seasonal = np.sin(2 * np.pi * (work["day_of_year"] - 172) / 365.25)
    if "solar_zenith_deg" not in work:
        work["solar_zenith_deg"] = np.clip(
            27 + 6.2 * np.abs(local_time - 13.2) + 4 * (1 - seasonal), 12, 88
        )
    if "solar_azimuth_deg" not in work:
        work["solar_azimuth_deg"] = np.mod(180 + (local_time - 12) * 18, 360)
    if "view_zenith_deg" not in work:
        work["view_zenith_deg"] = np.clip(rng.normal(9, 4, n), 0.2, 19.8)

    if "background_climate_index" not in work:
        centre = (city_number - city_number.mean()) / max(city_number.std(), 1.0)
        work["background_climate_index"] = centre
    climate = pd.to_numeric(work["background_climate_index"], errors="coerce").fillna(0.0)
    if "demand_vpd_kpa" not in work:
        work["demand_vpd_kpa"] = np.clip(
            2.3 + 0.25 * (local_time - 12) + 0.38 * climate + 0.35 * seasonal + rng.normal(0, 0.3, n),
            0.4,
            6.4,
        )
    if "antecedent_dryness_percentile" not in work:
        latent = 0.32 * pd.to_numeric(work["demand_vpd_kpa"]) + 0.17 * climate + rng.normal(0, 0.75, n)
        work["antecedent_dryness_percentile"] = pd.Series(latent).groupby(work["city"]).rank(pct=True).to_numpy()
    dryness = pd.to_numeric(work["antecedent_dryness_percentile"], errors="coerce").clip(0, 1)
    if "water_balance_30_mm" not in work:
        work["water_balance_30_mm"] = 90 - 240 * dryness + rng.normal(0, 18, n)
    if "water_balance_60_mm" not in work:
        work["water_balance_60_mm"] = 1.7 * work["water_balance_30_mm"] + rng.normal(0, 25, n)

    if "canopy_fraction" not in work:
        work["canopy_fraction"] = np.clip(rng.beta(3.2, 3.5, n), 0.08, 0.93)
    if "reference_canopy_fraction" not in work:
        work["reference_canopy_fraction"] = np.clip(rng.beta(1.2, 9, n), 0, 0.32)
    if "tree_albedo" not in work:
        work["tree_albedo"] = np.clip(0.145 + rng.normal(0, 0.018, n), 0.08, 0.24)
    if "reference_albedo" not in work:
        work["reference_albedo"] = np.clip(0.24 + 0.025 * climate + rng.normal(0, 0.03, n), 0.13, 0.42)
    work["albedo_difference"] = work["reference_albedo"] - work["tree_albedo"]
    if "incoming_shortwave_wm2" not in work:
        elevation_factor = np.maximum(0, np.cos(np.deg2rad(work["solar_zenith_deg"])))
        work["incoming_shortwave_wm2"] = 930 * elevation_factor + rng.normal(0, 25, n)
    if "net_radiation_wm2" not in work:
        work["net_radiation_wm2"] = 0.67 * work["incoming_shortwave_wm2"] + rng.normal(0, 18, n)
    if "air_temperature_k" not in work:
        work["air_temperature_k"] = 300.5 + 1.25 * work["demand_vpd_kpa"] + 1.2 * climate + rng.normal(0, 0.7, n)
    if "dewpoint_k" not in work:
        work["dewpoint_k"] = work["air_temperature_k"] - (8 + 2.2 * work["demand_vpd_kpa"])
    if "wind_speed_ms" not in work:
        work["wind_speed_ms"] = np.clip(rng.gamma(2.2, 1.0, n), 0.1, 10)
    if "buffer_impervious_fraction" not in work:
        work["buffer_impervious_fraction"] = np.clip(rng.beta(4, 2.2, n), 0.08, 0.98)
    if "building_fraction" not in work:
        work["building_fraction"] = np.clip(0.36 * work["buffer_impervious_fraction"] + rng.normal(0, 0.07, n), 0, 0.72)
    if "elevation_m" not in work:
        work["elevation_m"] = 80 + 190 * city_number + rng.normal(0, 22, n)
    if "distance_to_water_m" not in work:
        work["distance_to_water_m"] = np.clip(rng.lognormal(7.0, 0.65, n), 40, 10_000)

    # Outcomes are either adopted from the shared generator or derived from its
    # tree/reference temperatures.  No unprefixed outcome is retained.
    if "synthetic_cooling_contrast_k" not in work:
        if {
            "synthetic_tree_temperature_k",
            "synthetic_reference_temperature_k",
        } <= set(work.columns):
            work["synthetic_cooling_contrast_k"] = (
                work["synthetic_reference_temperature_k"]
                - work["synthetic_tree_temperature_k"]
            )
        else:
            day_curve = 4.8 - 0.23 * (local_time - 11.0) - 0.12 * (local_time - 13.0) ** 2
            interaction = -0.32 * work["demand_vpd_kpa"] * dryness
            canopy = 2.1 * (work["canopy_fraction"] - 0.45)
            night = -0.7 + 0.15 * climate
            work["synthetic_cooling_contrast_k"] = np.where(
                work["is_day"], day_curve + interaction + canopy, night
            ) + rng.normal(0, 0.42, n)
    if "synthetic_tree_temperature_k" not in work:
        thermal_excess = np.where(work["is_day"], 7.0, 1.2) + 0.72 * work["demand_vpd_kpa"]
        work["synthetic_tree_temperature_k"] = work["air_temperature_k"] + thermal_excess + rng.normal(0, 0.35, n)
    if "synthetic_reference_temperature_k" not in work:
        work["synthetic_reference_temperature_k"] = (
            work["synthetic_tree_temperature_k"] + work["synthetic_cooling_contrast_k"]
        )
    # Enforce the central sign/identity exactly.
    work["synthetic_cooling_contrast_k"] = (
        work["synthetic_reference_temperature_k"]
        - work["synthetic_tree_temperature_k"]
    )
    # Give the shared synthetic night rows a deliberately different sign so
    # the day/night diagnostic exercises the guide's expected reversal.  This
    # is a labelled synthetic transformation, not a claim about observations.
    night_mask = ~work["is_day"]
    if night_mask.any():
        night_city = city_number.loc[night_mask]
        night_tree = (
            work.loc[night_mask, "air_temperature_k"]
            + 1.2
            + rng.normal(0, 0.20, int(night_mask.sum()))
        )
        night_contrast = (
            -0.72
            + 0.04 * (night_city - night_city.mean())
            + rng.normal(0, 0.12, int(night_mask.sum()))
        )
        work.loc[night_mask, "synthetic_tree_temperature_k"] = night_tree
        work.loc[night_mask, "synthetic_reference_temperature_k"] = (
            night_tree.to_numpy() + night_contrast.to_numpy()
        )
        work.loc[night_mask, "synthetic_cooling_contrast_k"] = night_contrast
    work["synthetic_thermal_excess_k"] = (
        work["synthetic_tree_temperature_k"] - work["air_temperature_k"]
    )
    work["synthetic_model_a_benefit_k"] = (
        work["synthetic_cooling_contrast_k"]
        + 0.10 * (work["canopy_fraction"] - work["canopy_fraction"].mean())
    )
    work["synthetic_model_b_benefit_k"] = (
        work["synthetic_cooling_contrast_k"]
        - 0.05 * (work["demand_vpd_kpa"] - work["demand_vpd_kpa"].mean())
    )
    work["synthetic_radiatively_standardized_contrast_k"] = (
        work["synthetic_cooling_contrast_k"]
        - 1.6 * (work["albedo_difference"] - work["albedo_difference"].mean())
        - 0.00035 * (work["net_radiation_wm2"] - work["net_radiation_wm2"].mean())
    )
    work["synthetic_placebo_contrast_k"] = (
        0.10 * (work["demand_vpd_kpa"] - work["demand_vpd_kpa"].mean())
        + rng.normal(0, 0.25, n)
    )

    irrigation_levels = np.array(
        [
            "record_confirmed",
            "land_use_supported",
            "spectrally_inferred",
            "no_identified_subsidy",
        ]
    )
    if "irrigation_evidence_class" not in work:
        irrigation_index = np.floor((1 - dryness) * 4).astype(int).clip(0, 3)
        work["irrigation_evidence_class"] = irrigation_levels[irrigation_index]
    if "cloud_survival_fraction" not in work:
        work["cloud_survival_fraction"] = np.clip(0.72 - 0.05 * city_number + rng.normal(0, 0.05, n), 0.3, 0.95)
    if "classification_precision" not in work:
        work["classification_precision"] = np.clip(0.91 + rng.normal(0, 0.018, n), 0.82, 0.98)
    if "classification_recall" not in work:
        work["classification_recall"] = np.clip(0.87 + rng.normal(0, 0.025, n), 0.75, 0.97)
    if "matching_max_smd" not in work:
        work["matching_max_smd"] = np.clip(0.055 + rng.normal(0, 0.012, n), 0.018, 0.095)
    if "registration_shift_k" not in work:
        work["registration_shift_k"] = np.clip(np.abs(rng.normal(0.16, 0.04, n)), 0.03, 0.35)

    work["retrieval_band_mode"] = np.where(work["year"].between(2019, 2022), "reduced", "full")
    work["data_origin"] = DATA_ORIGIN
    work["canonical_eligible"] = CANONICAL_ELIGIBLE
    work = work.sort_values(["city", "pass_timestamp_utc", "pass_id", "matched_set_id"]).reset_index(drop=True)
    if work.duplicated(["city", "matched_set_id", "pass_id"]).any():
        raise ValueError("Synthetic analysis key (city, matched_set_id, pass_id) is not unique")
    outcome_like = [
        name
        for name in work.columns
        if any(token in name.lower() for token in ("cooling", "contrast", "benefit", "excess", "placebo"))
        or name in {"tree_temperature_k", "reference_temperature_k"}
    ]
    invalid_outcomes = [name for name in outcome_like if not name.startswith("synthetic_")]
    if invalid_outcomes:
        raise AssertionError(f"Unprefixed outcome columns: {invalid_outcomes}")
    return work


def _table_meta(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["data_origin"] = DATA_ORIGIN
    result["canonical_eligible"] = CANONICAL_ELIGIBLE
    return result


def _figure(paths: _OutputPaths, artifact_id: str, slug: str, *, figsize=(9, 6)):
    path = paths.figures / f"{FILE_PREFIX}{artifact_id}_{slug}.png"
    fig = plt.figure(figsize=figsize, constrained_layout=True)
    return fig, path


def _finish_figure(fig: plt.Figure, path: Path, title: str) -> Path:
    fig.suptitle(f"{BANNER}\n{title}", fontsize=11, fontweight="bold")
    fig.text(
        0.5,
        -0.035,
        "All values, cities, intervals, and diagnostics are synthetic demonstrations.",
        ha="center",
        va="bottom",
        fontsize=7,
        color="#7a1f1f",
    )
    fig.savefig(path, dpi=135, bbox_inches="tight", metadata={"Title": BANNER})
    plt.close(fig)
    return path


def _write_table(
    paths: _OutputPaths,
    artifact_id: str,
    slug: str,
    frame: pd.DataFrame,
) -> Path:
    path = paths.tables / f"{FILE_PREFIX}{artifact_id}_{slug}.csv"
    _table_meta(frame).to_csv(path, index=False)
    return path


def _group_interval(values: pd.Series) -> tuple[float, float, float, int]:
    finite = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    if not len(finite):
        return np.nan, np.nan, np.nan, 0
    mean = float(np.mean(finite))
    se = float(np.std(finite, ddof=1) / np.sqrt(len(finite))) if len(finite) > 1 else 0.0
    return mean, mean - 1.96 * se, mean + 1.96 * se, len(finite)


def _endpoint_table(data: pd.DataFrame, outcome: str) -> pd.DataFrame:
    day = data.loc[data["time_stratum"].isin(["10-12", "16-18"])].copy()
    rows: list[dict[str, object]] = []
    for city, group in day.groupby("city", sort=True):
        pass_means = group.groupby(["pass_id", "time_stratum"], as_index=False)[outcome].mean()
        early = pass_means.loc[pass_means["time_stratum"].eq("10-12"), outcome]
        late = pass_means.loc[pass_means["time_stratum"].eq("16-18"), outcome]
        early_mean, _, _, n_early = _group_interval(early)
        late_mean, _, _, n_late = _group_interval(late)
        estimate = late_mean - early_mean
        early_se = early.std(ddof=1) / np.sqrt(max(n_early, 1)) if n_early > 1 else 0.0
        late_se = late.std(ddof=1) / np.sqrt(max(n_late, 1)) if n_late > 1 else 0.0
        se = float(np.sqrt(early_se**2 + late_se**2))
        rows.append(
            {
                "city": city,
                "outcome": outcome,
                "synthetic_late_minus_morning_k": estimate,
                "synthetic_ci_low_k": estimate - 1.96 * se,
                "synthetic_ci_high_k": estimate + 1.96 * se,
                "n_passes_morning": n_early,
                "n_passes_late": n_late,
                "n_matched_sets": int(group["matched_set_id"].nunique()),
                "pooling": "city_specific",
            }
        )
    result = pd.DataFrame(rows)
    values = result["synthetic_late_minus_morning_k"]
    mean, low, high, _ = _group_interval(values)
    pooled = {
        "city": "sim_city_equal_weighted_pool",
        "outcome": outcome,
        "synthetic_late_minus_morning_k": mean,
        "synthetic_ci_low_k": low,
        "synthetic_ci_high_k": high,
        "n_passes_morning": int(result["n_passes_morning"].sum()),
        "n_passes_late": int(result["n_passes_late"].sum()),
        "n_matched_sets": int(data["matched_set_id"].nunique()),
        "pooling": "equal_sim_city_weighted",
    }
    weighted = np.average(
        values,
        weights=result["n_passes_morning"] + result["n_passes_late"],
    )
    pooled_obs = dict(pooled)
    pooled_obs.update(
        {
            "city": "sim_city_observation_weighted_pool",
            "synthetic_late_minus_morning_k": float(weighted),
            "synthetic_ci_low_k": float(weighted - (mean - low)),
            "synthetic_ci_high_k": float(weighted + (high - mean)),
            "pooling": "observation_weighted",
        }
    )
    return pd.concat([result, pd.DataFrame([pooled, pooled_obs])], ignore_index=True)


def _common_support_mask(data: pd.DataFrame) -> pd.Series:
    relevant = data["time_stratum"].isin(["10-12", "16-18"])
    retained = pd.Series(False, index=data.index)
    predictors = [
        "demand_vpd_kpa",
        "antecedent_dryness_percentile",
        "day_of_year",
        "view_zenith_deg",
        "albedo_difference",
    ]
    for _, group in data.loc[relevant].groupby("city"):
        mask = pd.Series(True, index=group.index)
        for predictor in predictors:
            first = group.loc[group["time_stratum"].eq("10-12"), predictor]
            second = group.loc[group["time_stratum"].eq("16-18"), predictor]
            if first.empty or second.empty:
                mask[:] = False
                break
            lower = max(float(first.quantile(0.02)), float(second.quantile(0.02)))
            upper = min(float(first.quantile(0.98)), float(second.quantile(0.98)))
            if lower < upper:
                mask &= group[predictor].between(lower, upper)
        # The compact shared fixture has only a handful of passes per stratum.
        # If multidimensional trimming would erase a stratum, retain that
        # sim-city's declared comparison and expose the sparse support in the
        # diagnostic instead of emitting undefined illustrative estimates.
        retained_group = group.loc[mask]
        retained_counts = retained_group.groupby("time_stratum")["pass_id"].nunique()
        if any(int(retained_counts.get(stratum, 0)) < 2 for stratum in ("10-12", "16-18")):
            mask[:] = True
        retained.loc[group.index] = mask
    return retained


def _linear_fit(data: pd.DataFrame, outcome: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    city_dummies = pd.get_dummies(data["city"], drop_first=True, dtype=float)
    features = pd.DataFrame(
        {
            "intercept": 1.0,
            "local_solar_time_hours": data["local_solar_time_hours"],
            "demand_vpd_kpa": data["demand_vpd_kpa"],
            "antecedent_dryness_percentile": data["antecedent_dryness_percentile"],
            "demand_x_dryness": data["demand_vpd_kpa"] * data["antecedent_dryness_percentile"],
            "canopy_fraction": data["canopy_fraction"],
            "net_radiation_wm2_scaled": data["net_radiation_wm2"] / 500.0,
            "day_of_year_scaled": (data["day_of_year"] - data["day_of_year"].mean()) / 30.0,
        },
        index=data.index,
    )
    features = pd.concat([features, city_dummies.set_axis(data.index)], axis=1)
    valid = np.isfinite(features.to_numpy(float)).all(axis=1) & np.isfinite(data[outcome].to_numpy(float))
    x = features.loc[valid].to_numpy(float)
    y = data.loc[valid, outcome].to_numpy(float)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    fitted = np.full(len(data), np.nan)
    fitted[valid] = x @ beta
    return beta, fitted, features.columns.tolist()


def _write_step09(data: pd.DataFrame, paths: _OutputPaths) -> dict[str, Path]:
    output: dict[str, Path] = {}
    display = data.copy()
    optional = ["synthetic_thermal_excess_k", "net_radiation_wm2", "irrigation_evidence_class"]
    display.loc[display.index[::29], optional[0]] = np.nan
    display.loc[display.index[7::37], optional[1]] = np.nan

    fig, path = _figure(paths, "F9.1", "missingness_matrix", figsize=(10, 5))
    ax = fig.add_subplot(111)
    columns = [
        "synthetic_cooling_contrast_k",
        "synthetic_thermal_excess_k",
        "demand_vpd_kpa",
        "antecedent_dryness_percentile",
        "net_radiation_wm2",
        "canopy_fraction",
    ]
    sample = display[columns].iloc[: min(450, len(display))]
    ax.imshow(sample.isna().to_numpy().T, aspect="auto", cmap="Greys", interpolation="nearest")
    ax.set_yticks(range(len(columns)), [name.replace("synthetic_", "syn_") for name in columns])
    ax.set_xlabel("Illustrative analysis rows (ordered sample)")
    ax.set_title("Optional synthetic gaps are visible; the core contrast is complete")
    output["F9.1"] = _finish_figure(fig, path, "F9.1 · Illustrative missingness matrix")

    fig, path = _figure(paths, "F9.2", "outcome_predictor_distributions", figsize=(11, 7))
    variables = [
        ("synthetic_cooling_contrast_k", "Cooling contrast (K)"),
        ("synthetic_tree_temperature_k", "Tree temperature (K)"),
        ("demand_vpd_kpa", "Demand (kPa)"),
        ("antecedent_dryness_percentile", "Dryness percentile"),
        ("canopy_fraction", "Canopy fraction"),
        ("net_radiation_wm2", "Net radiation (W m⁻²)"),
    ]
    for index, (column, label) in enumerate(variables, 1):
        ax = fig.add_subplot(2, 3, index)
        ax.hist(data[column].dropna(), bins=24, color="#3b82a0", alpha=0.85)
        ax.set_xlabel(label)
        ax.set_ylabel("Rows")
    output["F9.2"] = _finish_figure(fig, path, "F9.2 · Illustrative outcome and predictor distributions")

    fig, path = _figure(paths, "F9.3", "row_count_heatmap", figsize=(11, 5))
    counts = data.loc[data["is_day"]].pivot_table(
        index="city", columns=["year", "time_stratum"], values="pass_id", aggfunc="size", fill_value=0
    )
    ax = fig.add_subplot(111)
    image = ax.imshow(counts.to_numpy(), aspect="auto", cmap="Blues")
    ax.set_yticks(range(len(counts.index)), counts.index)
    count_labels = [
        "\n".join(map(str, column)) if isinstance(column, tuple) else str(column)
        for column in counts.columns
    ]
    ax.set_xticks(range(len(counts.columns)), count_labels, rotation=90, fontsize=6)
    fig.colorbar(image, ax=ax, label="Synthetic rows")
    output["F9.3"] = _finish_figure(fig, path, "F9.3 · Illustrative city × year × time-stratum counts")

    fig, path = _figure(paths, "F9.4", "irrigation_evidence_counts", figsize=(10, 5))
    irrigation = data.groupby(["city", "irrigation_evidence_class"]).size().unstack(fill_value=0)
    ax = fig.add_subplot(111)
    irrigation.plot(kind="bar", stacked=True, ax=ax, colormap="viridis")
    ax.set_ylabel("Synthetic matched-set/pass rows")
    ax.legend(title="Illustrative evidence class", fontsize=7)
    output["F9.4"] = _finish_figure(fig, path, "F9.4 · Illustrative irrigation-evidence composition")

    dictionary_rows = []
    unit_lookup = {
        "synthetic_tree_temperature_k": "K",
        "synthetic_reference_temperature_k": "K",
        "synthetic_cooling_contrast_k": "K",
        "synthetic_thermal_excess_k": "K",
        "demand_vpd_kpa": "kPa",
        "water_balance_30_mm": "mm",
        "water_balance_60_mm": "mm",
        "net_radiation_wm2": "W m-2",
        "incoming_shortwave_wm2": "W m-2",
        "canopy_fraction": "fraction",
    }
    for column in data.columns:
        dictionary_rows.append(
            {
                "column": column,
                "definition": f"Synthetic illustrative field: {column.replace('_', ' ')}",
                "units": unit_lookup.get(column, "category_or_declared_unitless"),
                "source": "deterministic_shared_synthetic_generator",
                "version": "illustrative_v1",
                "transformation": "synthetic_or_deterministic_derived",
            }
        )
    output["T9.1"] = _write_table(paths, "T9.1", "data_dictionary", pd.DataFrame(dictionary_rows))

    core = [
        "synthetic_cooling_contrast_k",
        "demand_vpd_kpa",
        "antecedent_dryness_percentile",
        "canopy_fraction",
    ]
    grouped = data.groupby(["city", "year", "time_stratum"], as_index=False).agg(
        synthetic_row_count=("pass_id", "size"),
        synthetic_unique_passes=("pass_id", "nunique"),
    )
    for column in core:
        completeness = (
            data.assign(__complete=data[column].notna())
            .groupby(["city", "year", "time_stratum"])["__complete"]
            .mean()
            .reset_index(name=f"{column}_complete_fraction")
        )
        grouped = grouped.merge(completeness, on=["city", "year", "time_stratum"], how="left")
    output["T9.2"] = _write_table(paths, "T9.2", "row_counts_completeness", grouped)
    return output


def _write_step10(data: pd.DataFrame, paths: _OutputPaths) -> tuple[dict[str, Path], pd.DataFrame, pd.Series]:
    output: dict[str, Path] = {}
    support_mask = _common_support_mask(data)
    endpoint = _endpoint_table(data.loc[support_mask], "synthetic_cooling_contrast_k")

    fig, path = _figure(paths, "F10.1", "raw_contrast_local_solar_time", figsize=(11, 7))
    day_ax = fig.add_subplot(2, 1, 1)
    night_ax = fig.add_subplot(2, 1, 2)
    for city, group in data.groupby("city"):
        day = group.loc[group["is_day"]]
        day_ax.scatter(day["local_solar_time_hours"], day["synthetic_cooling_contrast_k"], s=5, alpha=0.12)
        binned = day.assign(bin=pd.cut(day["local_solar_time_hours"], np.arange(10, 18.01, 0.5))).groupby("bin", observed=True)["synthetic_cooling_contrast_k"].mean()
        centres = [interval.mid for interval in binned.index]
        day_ax.plot(centres, binned, label=city)
        night = group.loc[~group["is_day"]]
        if not night.empty:
            night_ax.scatter(night["local_solar_time_hours"], night["synthetic_cooling_contrast_k"], s=8, alpha=0.3, label=city)
    for boundary in [10, 12, 14, 16, 18]:
        day_ax.axvline(boundary, color="0.75", lw=0.8)
    day_ax.set_ylabel("Synthetic contrast (K)")
    day_ax.legend(ncol=3, fontsize=7)
    night_ax.axhline(0, color="black", lw=0.8)
    night_ax.set_xlabel("Local solar time (hours)")
    night_ax.set_ylabel("Synthetic night contrast (K)")
    output["F10.1"] = _finish_figure(fig, path, "F10.1 · Illustrative raw time-of-day dependence")

    fig, path = _figure(paths, "F10.2", "solar_geometry_and_season", figsize=(11, 5))
    for index, (column, label) in enumerate(
        [("solar_zenith_deg", "Solar zenith (degrees)"), ("day_of_year", "Day of year")], 1
    ):
        ax = fig.add_subplot(1, 2, index)
        ax.scatter(data[column], data["synthetic_cooling_contrast_k"], s=5, alpha=0.12, color="#256d85")
        bins = pd.qcut(data[column], 14, duplicates="drop")
        means = data.groupby(bins, observed=True).agg(x=(column, "mean"), y=("synthetic_cooling_contrast_k", "mean"))
        ax.plot(means["x"], means["y"], color="#a63d40", lw=2)
        ax.set_xlabel(label)
        ax.set_ylabel("Synthetic cooling contrast (K)")
    output["F10.2"] = _finish_figure(fig, path, "F10.2 · Illustrative geometry and season diagnostics")

    fig, path = _figure(paths, "F10.3", "common_support", figsize=(12, 7))
    support_vars = ["demand_vpd_kpa", "antecedent_dryness_percentile", "view_zenith_deg", "albedo_difference"]
    for index, column in enumerate(support_vars, 1):
        ax = fig.add_subplot(2, 2, index)
        for stratum, color in [("10-12", "#247ba0"), ("16-18", "#d95d39")]:
            before = data.loc[data["time_stratum"].eq(stratum), column]
            after = data.loc[support_mask & data["time_stratum"].eq(stratum), column]
            ax.hist(before, bins=18, density=True, histtype="step", color=color, alpha=0.45)
            ax.hist(after, bins=18, density=True, histtype="stepfilled", color=color, alpha=0.22, label=f"{stratum} retained")
        ax.set_xlabel(column.replace("_", " "))
        ax.set_ylabel("Density")
        ax.legend(fontsize=7)
    removed = int((data["time_stratum"].isin(["10-12", "16-18"]) & ~support_mask).sum())
    output["F10.3"] = _finish_figure(fig, path, f"F10.3 · Illustrative common support (rows removed: {removed})")

    fig, path = _figure(paths, "F10.4", "fitted_time_effect_three_models", figsize=(11, 6))
    ax = fig.add_subplot(111)
    model_outcomes = {
        "A · direct benefit": "synthetic_model_a_benefit_k",
        "B · thermal-excess benefit": "synthetic_model_b_benefit_k",
        "C · cooling contrast": "synthetic_cooling_contrast_k",
    }
    day = data.loc[data["is_day"]].copy()
    grid = np.linspace(10, 18, 81)
    for label, outcome in model_outcomes.items():
        x = day["local_solar_time_hours"].to_numpy(float)
        y = day[outcome].to_numpy(float)
        coefficient = np.polyfit(x, y, 3)
        ax.plot(grid, np.polyval(coefficient, grid), lw=2, label=label)
    ax.set_xlabel("Local solar time (hours)")
    ax.set_ylabel("Synthetic model-scale thermal benefit (K)")
    ax.legend()
    output["F10.4"] = _finish_figure(fig, path, "F10.4 · Illustrative fitted time effect")

    fig, path = _figure(paths, "F10.5", "primary_endpoint_forest", figsize=(9, 6))
    ax = fig.add_subplot(111)
    plot_table = endpoint.reset_index(drop=True)
    y = np.arange(len(plot_table))
    estimate = plot_table["synthetic_late_minus_morning_k"]
    ax.errorbar(
        estimate,
        y,
        xerr=[estimate - plot_table["synthetic_ci_low_k"], plot_table["synthetic_ci_high_k"] - estimate],
        fmt="o",
        color="#2d6a4f",
        capsize=3,
    )
    ax.set_yticks(y, plot_table["city"])
    ax.axvline(0, color="black", lw=0.9)
    ax.set_xlabel("Synthetic late-afternoon minus late-morning contrast (K)")
    output["F10.5"] = _finish_figure(fig, path, "F10.5 · Illustrative primary endpoint")

    fig, path = _figure(paths, "F10.6", "three_outcome_agreement", figsize=(9, 5))
    agreement = []
    for label, outcome in model_outcomes.items():
        table = _endpoint_table(data.loc[support_mask], outcome)
        pooled = table.loc[table["pooling"].eq("equal_sim_city_weighted")].iloc[0]
        agreement.append((label, pooled["synthetic_late_minus_morning_k"], pooled["synthetic_ci_low_k"], pooled["synthetic_ci_high_k"]))
    ax = fig.add_subplot(111)
    labels = [row[0] for row in agreement]
    values = np.array([row[1] for row in agreement], float)
    lows = np.array([row[2] for row in agreement], float)
    highs = np.array([row[3] for row in agreement], float)
    ax.errorbar(values, range(len(values)), xerr=[values - lows, highs - values], fmt="o", capsize=4)
    ax.set_yticks(range(len(values)), labels)
    ax.axvline(0, color="black", lw=0.8)
    ax.set_xlabel("Synthetic late-minus-morning estimate (K)")
    output["F10.6"] = _finish_figure(fig, path, "F10.6 · Illustrative agreement across outcomes")

    fig, path = _figure(paths, "F10.7", "night_reversal", figsize=(9, 5))
    ax = fig.add_subplot(111)
    by_city = data.groupby(["city", "is_day"])["synthetic_cooling_contrast_k"].mean().unstack()
    positions = np.arange(len(by_city))
    width = 0.38
    ax.bar(positions - width / 2, by_city.get(True, np.nan), width, label="day")
    ax.bar(positions + width / 2, by_city.get(False, np.nan), width, label="night")
    ax.set_xticks(positions, by_city.index, rotation=20)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("Synthetic cooling contrast (K)")
    ax.legend()
    output["F10.7"] = _finish_figure(fig, path, "F10.7 · Illustrative day/night sign comparison")

    _, fitted, _ = _linear_fit(data.loc[data["is_day"]].reset_index(drop=True), "synthetic_cooling_contrast_k")
    diagnostic = data.loc[data["is_day"]].reset_index(drop=True).copy()
    diagnostic["synthetic_fitted_contrast_k"] = fitted
    diagnostic["synthetic_residual_k"] = diagnostic["synthetic_cooling_contrast_k"] - fitted
    fig, path = _figure(paths, "F10.8", "residual_diagnostics", figsize=(12, 4))
    panels = [
        ("synthetic_fitted_contrast_k", "Fitted contrast (K)"),
        ("solar_zenith_deg", "Solar zenith (degrees)"),
        ("matched_set_id", "Synthetic matched-set ID"),
    ]
    for index, (column, label) in enumerate(panels, 1):
        ax = fig.add_subplot(1, 3, index)
        x = pd.factorize(diagnostic[column])[0] if column == "matched_set_id" else diagnostic[column]
        ax.scatter(x, diagnostic["synthetic_residual_k"], s=5, alpha=0.15)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_xlabel(label)
        ax.set_ylabel("Synthetic residual (K)")
    output["F10.8"] = _finish_figure(fig, path, "F10.8 · Illustrative residual diagnostics")

    output["T10.1"] = _write_table(paths, "T10.1", "primary_endpoint", endpoint)
    model_spec = pd.DataFrame(
        [
            {"model": "A_direct", "synthetic_outcome": "synthetic_tree_temperature_k", "terms": "time + air_temperature + radiation + wind + season + view + canopy + albedo + city", "clustering": "synthetic pass and matched-set demonstration", "software": "numpy_lstsq_illustrative"},
            {"model": "B_thermal_excess", "synthetic_outcome": "synthetic_thermal_excess_k", "terms": "time + radiation + wind + season + view + canopy + albedo + city", "clustering": "synthetic pass and matched-set demonstration", "software": "numpy_lstsq_illustrative"},
            {"model": "C_cooling_contrast", "synthetic_outcome": "synthetic_cooling_contrast_k", "terms": "time + demand + dryness + radiation + view + canopy + albedo + city", "clustering": "synthetic pass and matched-set demonstration", "software": "numpy_lstsq_illustrative"},
        ]
    )
    output["T10.2"] = _write_table(paths, "T10.2", "model_specification", model_spec)
    concurvity_vars = [
        "local_solar_time_hours",
        "solar_zenith_deg",
        "net_radiation_wm2",
        "air_temperature_k",
        "demand_vpd_kpa",
        "day_of_year",
    ]
    corr = data[concurvity_vars].corr()
    rows = []
    for left_index, left in enumerate(concurvity_vars):
        for right in concurvity_vars[left_index + 1 :]:
            rows.append(
                {
                    "term_a": left,
                    "term_b": right,
                    "synthetic_concurvity_proxy_abs_correlation": abs(float(corr.loc[left, right])),
                    "interpretation": "illustrative correlation proxy; not a fitted GAM concurvity diagnostic",
                }
            )
    output["T10.3"] = _write_table(paths, "T10.3", "concurvity_proxy", pd.DataFrame(rows))
    return output, endpoint, support_mask


def _write_step11(
    data: pd.DataFrame,
    paths: _OutputPaths,
    endpoint: pd.DataFrame,
    support_mask: pd.Series,
) -> dict[str, Path]:
    output: dict[str, Path] = {}
    cities = sorted(data["city"].unique())

    loo_rows = []
    full = endpoint.loc[endpoint["pooling"].eq("equal_sim_city_weighted")].iloc[0]
    loo_rows.append(
        {
            "omitted_city": "none_full_synthetic_panel",
            "synthetic_endpoint_k": float(full["synthetic_late_minus_morning_k"]),
            "synthetic_ci_low_k": float(full["synthetic_ci_low_k"]),
            "synthetic_ci_high_k": float(full["synthetic_ci_high_k"]),
        }
    )
    for city in cities:
        subset = data.loc[support_mask & data["city"].ne(city)]
        table = _endpoint_table(subset, "synthetic_cooling_contrast_k")
        pooled = table.loc[table["pooling"].eq("equal_sim_city_weighted")].iloc[0]
        loo_rows.append(
            {
                "omitted_city": city,
                "synthetic_endpoint_k": float(pooled["synthetic_late_minus_morning_k"]),
                "synthetic_ci_low_k": float(pooled["synthetic_ci_low_k"]),
                "synthetic_ci_high_k": float(pooled["synthetic_ci_high_k"]),
            }
        )
    loo = pd.DataFrame(loo_rows)
    fig, path = _figure(paths, "F11.1", "leave_one_sim_city_out", figsize=(9, 5))
    ax = fig.add_subplot(111)
    y = np.arange(len(loo))
    values = loo["synthetic_endpoint_k"]
    ax.errorbar(
        values,
        y,
        xerr=[values - loo["synthetic_ci_low_k"], loo["synthetic_ci_high_k"] - values],
        fmt="o",
        capsize=3,
        color="#5a3d7a",
    )
    ax.set_yticks(y, loo["omitted_city"])
    ax.axvline(0, color="black", lw=0.8)
    ax.set_xlabel("Synthetic late-minus-morning endpoint (K)")
    output["F11.1"] = _finish_figure(fig, path, "F11.1 · Illustrative leave-one-sim-city-out result")

    quality = data.groupby("city", as_index=False).agg(
        synthetic_usable_passes=("pass_id", "nunique"),
        synthetic_classification_precision=("classification_precision", "mean"),
        synthetic_classification_recall=("classification_recall", "mean"),
        synthetic_max_matching_smd=("matching_max_smd", "max"),
        synthetic_registration_shift_k=("registration_shift_k", "mean"),
        synthetic_cloud_survival_fraction=("cloud_survival_fraction", "mean"),
    )
    fig, path = _figure(paths, "F11.2", "sim_city_quality_panel", figsize=(11, 6))
    metrics = [
        "synthetic_usable_passes",
        "synthetic_classification_precision",
        "synthetic_classification_recall",
        "synthetic_max_matching_smd",
        "synthetic_registration_shift_k",
        "synthetic_cloud_survival_fraction",
    ]
    matrix = quality[metrics].to_numpy(float)
    minimum = matrix.min(axis=0)
    span = np.maximum(matrix.max(axis=0) - minimum, 1e-12)
    normalized = (matrix - minimum) / span
    ax = fig.add_subplot(111)
    image = ax.imshow(normalized, aspect="auto", cmap="viridis", vmin=0, vmax=1)
    ax.set_yticks(range(len(quality)), quality["city"])
    ax.set_xticks(range(len(metrics)), [name.replace("synthetic_", "syn_") for name in metrics], rotation=30, ha="right")
    for row in range(matrix.shape[0]):
        for column in range(matrix.shape[1]):
            ax.text(column, row, f"{matrix[row, column]:.2f}", ha="center", va="center", fontsize=7, color="white" if normalized[row, column] < 0.45 else "black")
    fig.colorbar(image, ax=ax, label="Within-metric normalized value")
    output["F11.2"] = _finish_figure(fig, path, "F11.2 · Illustrative per-sim-city quality panel")

    fig, path = _figure(paths, "F11.3", "continuous_canopy_model", figsize=(10, 6))
    ax = fig.add_subplot(111)
    common_grid = np.linspace(0.2, 0.8, 80)
    for city, group in data.loc[data["is_day"]].groupby("city"):
        coefficient = np.polyfit(group["canopy_fraction"], group["synthetic_tree_temperature_k"], 2)
        prediction = np.polyval(coefficient, common_grid)
        prediction -= prediction.mean()
        ax.plot(common_grid, prediction, label=city)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xlabel("Common synthetic canopy-fraction support")
    ax.set_ylabel("Centered synthetic tree temperature (K)")
    ax.legend(ncol=2, fontsize=8)
    output["F11.3"] = _finish_figure(fig, path, "F11.3 · Illustrative continuous canopy model")

    city_endpoint = endpoint.loc[endpoint["pooling"].eq("city_specific")].copy()
    climate = data.groupby("city", as_index=False)["background_climate_index"].mean()
    climate_endpoint = city_endpoint.merge(climate, on="city", validate="one_to_one")
    fig, path = _figure(paths, "F11.4", "endpoint_background_climate_cases", figsize=(8, 5))
    ax = fig.add_subplot(111)
    ax.scatter(
        climate_endpoint["background_climate_index"],
        climate_endpoint["synthetic_late_minus_morning_k"],
        s=55,
        color="#d17b0f",
    )
    for row in climate_endpoint.itertuples(index=False):
        ax.annotate(row.city, (row.background_climate_index, row.synthetic_late_minus_morning_k), xytext=(4, 4), textcoords="offset points", fontsize=8)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xlabel("Synthetic background-climate index")
    ax.set_ylabel("Synthetic endpoint (K)")
    output["F11.4"] = _finish_figure(fig, path, "F11.4 · Five illustrative cases (no population gradient)")

    inclusion_rows = []
    for row in quality.itertuples(index=False):
        criteria = {
            "usable_passes": row.synthetic_usable_passes >= 8,
            "precision_and_recall": min(row.synthetic_classification_precision, row.synthetic_classification_recall) >= 0.75,
            "matching_balance": row.synthetic_max_matching_smd < 0.10,
            "registration_stability": row.synthetic_registration_shift_k < 0.50,
        }
        for criterion, achieved in criteria.items():
            inclusion_rows.append(
                {
                    "city": row.city,
                    "criterion": criterion,
                    "synthetic_criterion_met": bool(achieved),
                    "illustrative_decision": "retain_for_demo" if achieved else "flag_for_demo_review",
                    "note": "Illustrative rule only; this is not a real inclusion decision.",
                }
            )
    output["T11.1"] = _write_table(paths, "T11.1", "sim_city_inclusion_demo", pd.DataFrame(inclusion_rows))

    illustrative_holdout = cities[-1]
    holdout = pd.DataFrame(
        [
            {
                "synthetic_holdout_example": illustrative_holdout,
                "selection_basis": "generic deterministic sim-city ordering after synthetic quality generation",
                "selection_sequence": "illustrative quality-first sequence",
                "thermal_inspection_before_selection": False,
                "real_holdout_selected": False,
                "status": "illustrative_only_not_a_real_holdout_selection",
            }
        ]
    )
    output["T11.2"] = _write_table(paths, "T11.2", "holdout_protocol_demo", holdout)
    return output


def _surface_table(data: pd.DataFrame, outcome: str, *, bins: int = 10) -> pd.DataFrame:
    frame = data.loc[data["is_day"]].copy()
    frame["vpd_bin"] = pd.cut(frame["demand_vpd_kpa"], bins=bins)
    frame["dryness_bin"] = pd.cut(
        frame["antecedent_dryness_percentile"],
        bins=np.linspace(0, 1, bins + 1),
        include_lowest=True,
    )
    return (
        frame.groupby(["time_stratum", "dryness_bin", "vpd_bin"], observed=True)
        .agg(
            synthetic_mean=(outcome, "mean"),
            synthetic_support_passes=("pass_id", "nunique"),
            synthetic_rows=("pass_id", "size"),
        )
        .reset_index()
    )


def _model_design(frame: pd.DataFrame, model: str) -> np.ndarray:
    vpd = frame["demand_vpd_kpa"].to_numpy(float)
    dry = frame["antecedent_dryness_percentile"].to_numpy(float)
    columns = [np.ones(len(frame)), vpd, dry]
    if model in {"smooth", "transition"}:
        columns.extend([vpd**2, dry**2, vpd * dry])
    if model == "transition":
        columns.append(np.maximum(vpd - 2.8, 0))
    return np.column_stack(columns)


def _crossvalidated_models(data: pd.DataFrame) -> pd.DataFrame:
    frame = data.loc[data["is_day"]].copy()
    rows = []
    for model in ("linear", "smooth", "transition"):
        squared_errors: list[np.ndarray] = []
        for year in sorted(frame["year"].unique()):
            train = frame.loc[frame["year"].ne(year)]
            test = frame.loc[frame["year"].eq(year)]
            if train.empty or test.empty:
                continue
            beta, *_ = np.linalg.lstsq(
                _model_design(train, model),
                train["synthetic_cooling_contrast_k"].to_numpy(float),
                rcond=None,
            )
            residual = test["synthetic_cooling_contrast_k"].to_numpy(float) - _model_design(test, model) @ beta
            squared_errors.append(residual**2)
        errors = np.concatenate(squared_errors)
        rmse = float(np.sqrt(np.mean(errors)))
        k = _model_design(frame.iloc[:1], model).shape[1]
        information = float(len(frame) * np.log(max(rmse**2, 1e-12)) + 2 * k)
        rows.append(
            {
                "model": model,
                "synthetic_heldout_year_rmse_k": rmse,
                "synthetic_information_criterion": information,
                "heldout_unit": "whole_synthetic_year",
            }
        )
    return pd.DataFrame(rows)


def _transition_demo(data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for stratum, group in data.loc[data["is_day"]].groupby("time_stratum"):
        candidates = np.linspace(
            float(group["demand_vpd_kpa"].quantile(0.15)),
            float(group["demand_vpd_kpa"].quantile(0.85)),
            25,
        )
        best = None
        y = group["synthetic_cooling_contrast_k"].to_numpy(float)
        vpd = group["demand_vpd_kpa"].to_numpy(float)
        dry = group["antecedent_dryness_percentile"].to_numpy(float)
        for breakpoint in candidates:
            x = np.column_stack([np.ones(len(group)), vpd, dry, vpd * dry, np.maximum(vpd - breakpoint, 0)])
            beta, *_ = np.linalg.lstsq(x, y, rcond=None)
            sse = float(np.sum((y - x @ beta) ** 2))
            if best is None or sse < best[0]:
                best = (sse, float(breakpoint))
        assert best is not None
        spread = max(0.18, float(np.std(vpd) / np.sqrt(max(group["pass_id"].nunique(), 1))))
        rows.append(
            {
                "time_stratum": stratum,
                "synthetic_breakpoint_kpa": best[1],
                "synthetic_ci_low_kpa": best[1] - 1.96 * spread,
                "synthetic_ci_high_kpa": best[1] + 1.96 * spread,
                "verdict": "illustrative_no_discrete_transition_claim",
            }
        )
    return pd.DataFrame(rows)


def _write_step12(data: pd.DataFrame, paths: _OutputPaths) -> tuple[dict[str, Path], pd.DataFrame]:
    output: dict[str, Path] = {}
    surface = _surface_table(data, "synthetic_cooling_contrast_k", bins=9)
    strata = [value for value in ["10-12", "12-14", "14-16", "16-18"] if value in surface["time_stratum"].unique()]

    fig, path = _figure(paths, "F12.1", "demand_dryness_surface", figsize=(11, 8))
    for index, stratum in enumerate(strata, 1):
        ax = fig.add_subplot(2, 2, index)
        subset = surface.loc[surface["time_stratum"].eq(stratum)].copy()
        pivot = subset.pivot(index="dryness_bin", columns="vpd_bin", values="synthetic_mean")
        support = subset.pivot(index="dryness_bin", columns="vpd_bin", values="synthetic_support_passes")
        masked = np.ma.masked_where(support.to_numpy() < 2, pivot.to_numpy())
        image = ax.imshow(masked, origin="lower", aspect="auto", cmap="coolwarm")
        ax.set_title(stratum)
        ax.set_xlabel("Synthetic demand bins")
        ax.set_ylabel("Synthetic dryness bins")
        fig.colorbar(image, ax=ax, label="Synthetic contrast (K)")
    output["F12.1"] = _finish_figure(fig, path, "F12.1 · Illustrative demand × antecedent-dryness surface")

    fig, path = _figure(paths, "F12.2", "surface_data_support", figsize=(11, 8))
    for index, stratum in enumerate(strata, 1):
        ax = fig.add_subplot(2, 2, index)
        subset = surface.loc[surface["time_stratum"].eq(stratum)]
        pivot = subset.pivot(index="dryness_bin", columns="vpd_bin", values="synthetic_support_passes")
        image = ax.imshow(pivot.to_numpy(), origin="lower", aspect="auto", cmap="magma")
        ax.set_title(stratum)
        ax.set_xlabel("Synthetic demand bins")
        ax.set_ylabel("Synthetic dryness bins")
        fig.colorbar(image, ax=ax, label="Unique synthetic passes")
    output["F12.2"] = _finish_figure(fig, path, "F12.2 · Illustrative pass-support map")

    fig, path = _figure(paths, "F12.3", "surface_slices", figsize=(11, 8))
    day = data.loc[data["is_day"]].copy()
    day["dryness_level"] = pd.cut(
        day["antecedent_dryness_percentile"],
        bins=[0, 1 / 3, 2 / 3, 1],
        labels=["low", "medium", "high"],
        include_lowest=True,
    )
    day["vpd_slice_bin"] = pd.cut(day["demand_vpd_kpa"], bins=12)
    for index, stratum in enumerate(strata, 1):
        ax = fig.add_subplot(2, 2, index)
        group = day.loc[day["time_stratum"].eq(stratum)]
        summary = group.groupby(["dryness_level", "vpd_slice_bin"], observed=True).agg(
            x=("demand_vpd_kpa", "mean"), y=("synthetic_cooling_contrast_k", "mean")
        ).reset_index()
        for level, slice_group in summary.groupby("dryness_level", observed=True):
            ax.plot(slice_group["x"], slice_group["y"], marker="o", ms=3, label=str(level))
        ax.set_title(stratum)
        ax.set_xlabel("Synthetic demand (kPa)")
        ax.set_ylabel("Synthetic contrast (K)")
        ax.legend(fontsize=7)
    output["F12.3"] = _finish_figure(fig, path, "F12.3 · Illustrative dryness-conditioned slices")

    comparison = _crossvalidated_models(data)
    fig, path = _figure(paths, "F12.4", "heldout_model_comparison", figsize=(9, 5))
    ax = fig.add_subplot(111)
    bars = ax.bar(comparison["model"], comparison["synthetic_heldout_year_rmse_k"], color=["#577590", "#43aa8b", "#f3722c"])
    for bar, value in zip(bars, comparison["synthetic_heldout_year_rmse_k"]):
        ax.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.3f}", ha="center", va="bottom")
    ax.set_ylabel("Whole-synthetic-year held-out RMSE (K)")
    output["F12.4"] = _finish_figure(fig, path, "F12.4 · Illustrative model comparison")

    transition = _transition_demo(data)
    fig, path = _figure(paths, "F12.5", "transition_location_demo", figsize=(9, 5))
    ax = fig.add_subplot(111)
    y = np.arange(len(transition))
    value = transition["synthetic_breakpoint_kpa"]
    ax.errorbar(
        value,
        y,
        xerr=[value - transition["synthetic_ci_low_kpa"], transition["synthetic_ci_high_kpa"] - value],
        fmt="o",
        capsize=4,
        color="#9b2226",
    )
    ax.set_yticks(y, transition["time_stratum"])
    ax.set_xlabel("Synthetic algorithm-returned breakpoint (kPa)")
    ax.text(0.5, 0.04, "Demonstration only: no discrete-transition claim", transform=ax.transAxes, ha="center", color="#9b2226")
    output["F12.5"] = _finish_figure(fig, path, "F12.5 · Illustrative transition diagnostic")

    standardized = _surface_table(data, "synthetic_radiatively_standardized_contrast_k", bins=9)
    fig, path = _figure(paths, "F12.6", "total_vs_radiative_surface", figsize=(11, 5))
    for index, (table, title) in enumerate([(surface, "total synthetic contrast"), (standardized, "radiatively standardized synthetic contrast")], 1):
        ax = fig.add_subplot(1, 2, index)
        combined = table.groupby(["dryness_bin", "vpd_bin"], observed=True).agg(
            value=("synthetic_mean", "mean"), support=("synthetic_support_passes", "sum")
        ).reset_index()
        pivot = combined.pivot(index="dryness_bin", columns="vpd_bin", values="value")
        support = combined.pivot(index="dryness_bin", columns="vpd_bin", values="support")
        image = ax.imshow(np.ma.masked_where(support.to_numpy() < 4, pivot.to_numpy()), origin="lower", aspect="auto", cmap="coolwarm")
        ax.set_title(title)
        ax.set_xlabel("Synthetic demand bins")
        ax.set_ylabel("Synthetic dryness bins")
        fig.colorbar(image, ax=ax, label="Synthetic contrast (K)")
    output["F12.6"] = _finish_figure(fig, path, "F12.6 · Illustrative total and radiatively standardized surfaces")

    frame = data.loc[data["is_day"]].copy()
    x = _model_design(frame, "smooth")
    y = frame["synthetic_cooling_contrast_k"].to_numpy(float)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    residual = y - x @ beta
    variance = np.sum(residual**2) / max(len(y) - x.shape[1], 1)
    covariance = variance * np.linalg.pinv(x.T @ x)
    interaction = float(beta[5])
    se = float(np.sqrt(max(covariance[5, 5], 0)))
    interaction_table = comparison.copy()
    interaction_table["synthetic_interaction_coefficient_k_per_kpa"] = interaction
    interaction_table["synthetic_interaction_ci_low"] = interaction - 1.96 * se
    interaction_table["synthetic_interaction_ci_high"] = interaction + 1.96 * se
    interaction_table["synthetic_effective_passes"] = int(frame["pass_id"].nunique())
    interaction_table["interpretation"] = "illustrative method exercise only"
    output["T12.1"] = _write_table(paths, "T12.1", "interaction_model_comparison", interaction_table)

    criterion_rows = []
    for row in transition.itertuples(index=False):
        checks = [
            ("beats_linear_and_smooth_on_heldout_data", False),
            ("observations_on_both_sides_across_three_years", True),
            ("stable_under_pass_year_city_resampling", False),
            ("exceeds_synthetic_detectability_limit", False),
            ("mechanism_moves_consistently", True),
            ("smooth_truth_false_positive_rate_acceptable", True),
        ]
        for criterion, met in checks:
            criterion_rows.append(
                {
                    "time_stratum": row.time_stratum,
                    "synthetic_breakpoint_kpa": row.synthetic_breakpoint_kpa,
                    "criterion": criterion,
                    "synthetic_criterion_met": met,
                    "verdict": "illustrative_smooth_response_no_transition_claim",
                }
            )
    output["T12.2"] = _write_table(paths, "T12.2", "transition_criteria", pd.DataFrame(criterion_rows))
    return output, transition


def _sensitivity_table(
    data: pd.DataFrame,
    endpoint: pd.DataFrame,
    support_mask: pd.Series,
) -> pd.DataFrame:
    base_row = endpoint.loc[endpoint["pooling"].eq("equal_sim_city_weighted")].iloc[0]
    base = float(base_row["synthetic_late_minus_morning_k"])
    half_width = max(0.08, float((base_row["synthetic_ci_high_k"] - base_row["synthetic_ci_low_k"]) / 2))

    def pooled(outcome: str, mask: pd.Series | None = None) -> float:
        active = support_mask if mask is None else support_mask & mask
        table = _endpoint_table(data.loc[active], outcome)
        row = table.loc[table["pooling"].eq("equal_sim_city_weighted")].iloc[0]
        return float(row["synthetic_late_minus_morning_k"])

    wet_mask = data["antecedent_dryness_percentile"].le(0.5)
    full_mode = data["retrieval_band_mode"].eq("full")
    loo_estimates = []
    for city in sorted(data["city"].unique()):
        subset = data.loc[support_mask & data["city"].ne(city)]
        table = _endpoint_table(subset, "synthetic_cooling_contrast_k")
        loo_estimates.append(float(table.loc[table["pooling"].eq("equal_sim_city_weighted"), "synthetic_late_minus_morning_k"].iloc[0]))

    variations = [
        ("radiative_standardisation", pooled("synthetic_radiatively_standardized_contrast_k"), "adjusted synthetic albedo and radiation"),
        ("pavement_placebo", pooled("synthetic_placebo_contrast_k"), "synthetic non-vegetated placebo"),
        ("night", float(data.loc[~data["is_day"], "synthetic_cooling_contrast_k"].mean()), "astronomically labelled synthetic night rows"),
        ("wet_restriction", pooled("synthetic_cooling_contrast_k", wet_mask), "synthetic lower-dryness half"),
        ("registration", base + float(data["registration_shift_k"].mean()) * 0.12, "deterministic one-pixel perturbation proxy"),
        ("retrieval_mode", pooled("synthetic_cooling_contrast_k", full_mode), "synthetic full-mode subset"),
        ("alternative_reference", base * 0.92, "deterministic alternative built-reference definition"),
        ("collection_version", base + 0.05, "deterministic alternative-chain perturbation"),
        ("alternative_meteorology", base * 1.03, "deterministic alternative-weather perturbation"),
        ("leave_one_out", float(np.mean(loo_estimates)), "mean of leave-one-sim-city-out estimates"),
    ]
    rows = []
    for index, (variation, estimate, method) in enumerate(variations):
        width = half_width * (1.0 + 0.025 * index)
        rows.append(
            {
                "variation": variation,
                "synthetic_estimate_k": estimate,
                "synthetic_ci_low_k": estimate - width,
                "synthetic_ci_high_k": estimate + width,
                "synthetic_change_from_main_k": estimate - base,
                "synthetic_sign_matches_main": bool(np.sign(estimate) == np.sign(base) or estimate == 0),
                "method": method,
                "conclusion": "illustrative_only_no_study_conclusion",
            }
        )
    return pd.DataFrame(rows)


def _write_step13(
    data: pd.DataFrame,
    paths: _OutputPaths,
    endpoint: pd.DataFrame,
    support_mask: pd.Series,
) -> dict[str, Path]:
    output: dict[str, Path] = {}
    sensitivity = _sensitivity_table(data, endpoint, support_mask)
    base = float(endpoint.loc[endpoint["pooling"].eq("equal_sim_city_weighted"), "synthetic_late_minus_morning_k"].iloc[0])

    fig, path = _figure(paths, "F13.1", "placebo_vs_main", figsize=(8, 5))
    placebo = sensitivity.loc[sensitivity["variation"].eq("pavement_placebo")].iloc[0]
    ax = fig.add_subplot(111)
    values = [base, float(placebo["synthetic_estimate_k"])]
    ax.bar(["main synthetic contrast", "synthetic pavement placebo"], values, color=["#277da1", "#f9844a"])
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("Synthetic late-minus-morning estimate (K)")
    output["F13.1"] = _finish_figure(fig, path, "F13.1 · Illustrative placebo comparison")

    fig, path = _figure(paths, "F13.2", "night_vs_day", figsize=(9, 5))
    by_city = data.groupby(["city", "is_day"])["synthetic_cooling_contrast_k"].mean().unstack()
    ax = fig.add_subplot(111)
    x = np.arange(len(by_city))
    ax.plot(x, by_city.get(True, np.nan), "o-", label="synthetic day")
    ax.plot(x, by_city.get(False, np.nan), "o-", label="synthetic night")
    ax.set_xticks(x, by_city.index)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("Mean synthetic cooling contrast (K)")
    ax.legend()
    output["F13.2"] = _finish_figure(fig, path, "F13.2 · Illustrative night-versus-day check")

    fig, path = _figure(paths, "F13.3", "sensitivity_tornado", figsize=(10, 6))
    tornado = sensitivity.sort_values("synthetic_change_from_main_k")
    ax = fig.add_subplot(111)
    colours = np.where(tornado["synthetic_sign_matches_main"], "#43aa8b", "#d00000")
    ax.barh(tornado["variation"], tornado["synthetic_change_from_main_k"], color=colours)
    ax.axvline(0, color="black", lw=0.8)
    ax.set_xlabel("Synthetic change from main estimate (K)")
    output["F13.3"] = _finish_figure(fig, path, "F13.3 · Illustrative sensitivity tornado")

    budget = pd.DataFrame(
        [
            ("temperature_retrieval", 0.34, "fixed synthetic validation magnitude"),
            ("geolocation", 0.16, "synthetic registration-shift exercise"),
            ("matching_imbalance", 0.13, "synthetic residual balance proxy"),
            ("view_angle", 0.11, "synthetic view-angle perturbation"),
            ("weather_product", 0.18, "synthetic source comparison"),
            ("albedo_fusion", 0.14, "synthetic uncertainty-layer exercise"),
        ],
        columns=["uncertainty_source", "synthetic_magnitude_k", "estimation_method"],
    )
    budget["synthetic_variance_contribution_k2"] = budget["synthetic_magnitude_k"] ** 2
    combined = float(np.sqrt(budget["synthetic_variance_contribution_k2"].sum()))
    budget["synthetic_combined_uncertainty_k"] = combined
    budget["synthetic_detectability_limit_k"] = 2 * combined
    fig, path = _figure(paths, "F13.4", "uncertainty_budget", figsize=(10, 5))
    ax = fig.add_subplot(111)
    left = 0.0
    for row in budget.itertuples(index=False):
        ax.barh([0], [row.synthetic_magnitude_k], left=left, label=row.uncertainty_source)
        left += row.synthetic_magnitude_k
    ax.axvline(combined, color="black", ls="--", label=f"quadrature combined {combined:.2f} K")
    ax.axvline(2 * combined, color="#d00000", ls=":", label="synthetic detectability limit")
    ax.set_yticks([0], ["illustrative components"])
    ax.set_xlabel("Synthetic uncertainty magnitude (K; components shown separately)")
    ax.legend(ncol=2, fontsize=7)
    output["F13.4"] = _finish_figure(fig, path, "F13.4 · Illustrative uncertainty budget")

    total = _endpoint_table(data.loc[support_mask], "synthetic_cooling_contrast_k")
    standardized = _endpoint_table(data.loc[support_mask], "synthetic_radiatively_standardized_contrast_k")
    total = total.loc[total["pooling"].eq("city_specific"), ["city", "synthetic_late_minus_morning_k"]].rename(columns={"synthetic_late_minus_morning_k": "synthetic_total_k"})
    standardized = standardized.loc[standardized["pooling"].eq("city_specific"), ["city", "synthetic_late_minus_morning_k"]].rename(columns={"synthetic_late_minus_morning_k": "synthetic_standardized_k"})
    attenuation = total.merge(standardized, on="city")
    fig, path = _figure(paths, "F13.5", "radiative_attenuation", figsize=(10, 5))
    ax = fig.add_subplot(111)
    x = np.arange(len(attenuation))
    width = 0.38
    ax.bar(x - width / 2, attenuation["synthetic_total_k"], width, label="total synthetic contrast")
    ax.bar(x + width / 2, attenuation["synthetic_standardized_k"], width, label="radiatively standardized")
    ax.set_xticks(x, attenuation["city"])
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("Synthetic endpoint (K)")
    ax.legend()
    output["F13.5"] = _finish_figure(fig, path, "F13.5 · Illustrative radiative attenuation")

    output["T13.1"] = _write_table(paths, "T13.1", "all_sensitivities", sensitivity)
    output["T13.2"] = _write_table(paths, "T13.2", "uncertainty_budget", budget)
    return output


EXPECTED_ARTIFACT_IDS = frozenset(
    [
        "F9.1", "F9.2", "F9.3", "F9.4", "T9.1", "T9.2",
        "F10.1", "F10.2", "F10.3", "F10.4", "F10.5", "F10.6", "F10.7", "F10.8", "T10.1", "T10.2", "T10.3",
        "F11.1", "F11.2", "F11.3", "F11.4", "T11.1", "T11.2",
        "F12.1", "F12.2", "F12.3", "F12.4", "F12.5", "F12.6", "T12.1", "T12.2",
        "F13.1", "F13.2", "F13.3", "F13.4", "F13.5", "T13.1", "T13.2",
    ]
)


def write_steps09_13(
    output_root: str | Path,
    figure_root: str | Path,
    seed: int = 20260805,
) -> dict[str, Path]:
    """Write all illustrative Guide Step 9--13 artifacts.

    Returns a mapping from every guide artifact ID to its created file, plus an
    ``ANALYSIS_TABLE`` entry for the synthetic Step-9 row-level table.  All
    filenames are prefixed ``ILLUSTRATIVE_`` and all tables carry the two
    machine-readable noncanonical markers.
    """

    paths = _OutputPaths(Path(output_root), Path(figure_root))
    paths.tables.mkdir(parents=True, exist_ok=True)
    paths.figures.mkdir(parents=True, exist_ok=True)
    pass_df, matched_df = _load_shared_synthetic_data(int(seed))
    data = _normalize_synthetic_tables(pass_df, matched_df, seed=int(seed))

    analysis_path = paths.tables / f"{FILE_PREFIX}STEP9_SYNTHETIC_ANALYSIS_TABLE.csv"
    data.to_csv(analysis_path, index=False)
    artifacts: dict[str, Path] = {"ANALYSIS_TABLE": analysis_path}
    artifacts.update(_write_step09(data, paths))
    step10, endpoint, support_mask = _write_step10(data, paths)
    artifacts.update(step10)
    artifacts.update(_write_step11(data, paths, endpoint, support_mask))
    step12, _ = _write_step12(data, paths)
    artifacts.update(step12)
    artifacts.update(_write_step13(data, paths, endpoint, support_mask))

    missing = EXPECTED_ARTIFACT_IDS - set(artifacts)
    extras = set(artifacts) - EXPECTED_ARTIFACT_IDS - {"ANALYSIS_TABLE"}
    if missing or extras:
        raise RuntimeError(
            f"Illustrative artifact registry mismatch; missing={sorted(missing)}, extras={sorted(extras)}"
        )
    empty = [str(path) for path in artifacts.values() if not path.is_file() or path.stat().st_size == 0]
    if empty:
        raise RuntimeError(f"Illustrative writer produced missing or empty artifacts: {empty}")
    return artifacts


__all__ = ["BANNER", "EXPECTED_ARTIFACT_IDS", "write_steps09_13"]
