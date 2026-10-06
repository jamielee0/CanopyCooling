"""Deterministic, synthetic-only illustrations for Guide Steps 4--8.

This module is intentionally isolated from the canonical v2 pipeline.  It has
no data-access adapter, accepts no source-data path, and never reads a thermal
or LST asset.  Its outputs are useful only for exercising presentation and
analysis shapes while the real scientific gate remains stopped.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_SEED = 20260805
WATERMARK = "ILLUSTRATIVE — SYNTHETIC DATA — NOT A STUDY RESULT"
SIM_CITIES = tuple(f"sim_city_{index}" for index in range(1, 6))


def _bounded(values: Any, low: float, high: float) -> np.ndarray:
    return np.clip(np.asarray(values, dtype=float), low, high)


def generate_synthetic_data(
    seed: int = DEFAULT_SEED,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return one reusable synthetic pass and matched-set dataset.

    The function is deliberately pure: it does not inspect the repository or
    perform network access.  All measurement-like fields are prefixed with
    ``synthetic_`` and the five city labels are generic.
    """

    rng = np.random.default_rng(int(seed))
    strata = ("10-12", "12-14", "14-16", "16-18")
    pass_rows: list[dict[str, Any]] = []
    for city_index, city in enumerate(SIM_CITIES):
        city_shift = (city_index - 2) * 0.12
        for pass_index in range(24):
            year = 2018 + pass_index % 8
            day_of_year = 155 + (pass_index * 11 + city_index * 7) % 120
            stratum_index = (pass_index + city_index) % len(strata)
            is_night = pass_index % 12 == 11
            local_time = (
                21.5 + rng.uniform(0.25, 1.75)
                if is_night
                else 10.35 + 2.0 * stratum_index + rng.uniform(0.15, 1.45)
            )
            solar_zenith = (
                float(rng.uniform(98.0, 119.0))
                if is_night
                else _bounded(
                    17.0 + abs(local_time - 13.25) * 11.5 + rng.normal(0, 2.2),
                    8.0,
                    78.0,
                ).item()
            )
            solar_azimuth = float(
                np.mod(180.0 + (local_time - 12.0) * 25.0 + rng.normal(0, 5), 360)
            )
            latent_demand = rng.normal(0.15 * city_index, 1.0)
            demand_pct = float(1.0 / (1.0 + np.exp(-latent_demand)))
            dryness_pct = float(
                _bounded(0.25 + 0.50 * demand_pct + rng.normal(0, 0.20), 0.01, 0.99)
            )
            hrrr_vpd = float(
                _bounded(0.7 + 4.0 * demand_pct + city_shift + rng.normal(0, 0.18), 0.2, 6.2)
            )
            t2m = float(294.0 + 8.5 * demand_pct + city_index * 0.65 + rng.normal(0, 0.8))
            d2m = float(t2m - (4.0 + 7.0 * demand_pct) + rng.normal(0, 0.45))
            incoming = float(
                _bounded(1040.0 * np.cos(np.deg2rad(solar_zenith)) + rng.normal(0, 25), 80, 1020)
            )
            net_radiation = float(_bounded(incoming * (0.70 + rng.normal(0, 0.025)), 40, 850))
            cloud_fraction = float(_bounded(rng.beta(1.5, 5.5) + 0.08 * city_index, 0, 0.92))
            quality_fraction = float(_bounded(0.97 - 0.34 * cloud_fraction + rng.normal(0, 0.02), 0.48, 0.995))
            water_fraction = float(_bounded(rng.beta(1.2, 18.0) + 0.015 * city_index, 0, 0.28))
            acquisition = (
                pd.Timestamp(year=year, month=1, day=1, tz="UTC")
                + pd.Timedelta(days=day_of_year - 1)
                + pd.Timedelta(hours=float(local_time + 4 + city_index * 0.3))
            )
            pass_id = f"synthetic_pass_{city_index + 1}_{pass_index + 1:03d}"
            station_t2m = t2m + rng.normal(0, 0.65)
            station_d2m = d2m + rng.normal(0, 0.55)
            pass_rows.append(
                {
                    "data_origin": "synthetic",
                    "canonical_eligible": False,
                    "synthetic_pass_id": pass_id,
                    "synthetic_scene_id": f"synthetic_scene_{city_index + 1}_{pass_index + 1:03d}",
                    "city": city,
                    "year": year,
                    "time_stratum": "night" if is_night else strata[stratum_index],
                    "synthetic_acquisition_utc": acquisition.isoformat(),
                    "synthetic_day_of_year": day_of_year,
                    "synthetic_is_day": not is_night,
                    "synthetic_local_solar_time_hours": local_time,
                    "synthetic_solar_zenith_deg": solar_zenith,
                    "synthetic_solar_azimuth_deg": solar_azimuth,
                    "synthetic_solar_elevation_deg": 90.0 - solar_zenith,
                    "synthetic_demand_pct": demand_pct,
                    "synthetic_dryness_pct": dryness_pct,
                    "synthetic_water_balance_30_mm": -8.0 - 150.0 * dryness_pct + rng.normal(0, 8),
                    "synthetic_water_balance_60_mm": -12.0 - 260.0 * dryness_pct + rng.normal(0, 14),
                    "synthetic_hrrr_vpd_kpa": hrrr_vpd,
                    "synthetic_station_vpd_kpa": hrrr_vpd + rng.normal(0, 0.16),
                    "synthetic_era5_vpd_kpa": hrrr_vpd * 0.95 + 0.08 + rng.normal(0, 0.14),
                    "synthetic_nearest_hour_vpd_kpa": hrrr_vpd + rng.normal(0, 0.11),
                    "synthetic_interpolated_vpd_kpa": hrrr_vpd + rng.normal(0, 0.045),
                    "synthetic_t2m_k": t2m,
                    "synthetic_d2m_k": d2m,
                    "synthetic_station_t2m_k": station_t2m,
                    "synthetic_station_d2m_k": station_d2m,
                    "synthetic_incoming_radiation_w_m2": incoming,
                    "synthetic_net_radiation_w_m2": net_radiation,
                    "synthetic_cloud_fraction": cloud_fraction,
                    "synthetic_water_fraction": water_fraction,
                    "synthetic_quality_fraction": quality_fraction,
                    "synthetic_view_zenith_deg": float(rng.uniform(1.0, 19.5)),
                    "synthetic_retrieval_mode": "five_band" if year >= 2020 else "three_band",
                    "synthetic_geometry_class": rng.choice(("best", "good"), p=(0.58, 0.42)),
                    "synthetic_obstructed": False,
                }
            )

    pass_df = pd.DataFrame(pass_rows)
    matched_rows: list[dict[str, Any]] = []
    land_uses = np.array(("residential", "park", "commercial", "institutional"))
    for pass_row in pass_df.to_dict("records"):
        city_index = SIM_CITIES.index(pass_row["city"])
        for set_index in range(8):
            canopy = float(_bounded(rng.beta(3.3, 2.7), 0.05, 0.96))
            reference_canopy = float(_bounded(rng.beta(1.4, 7.0), 0.0, 0.42))
            impervious = float(_bounded(0.82 - 0.58 * canopy + rng.normal(0, 0.09), 0.04, 0.97))
            buffer_impervious = float(_bounded(impervious + rng.normal(0, 0.08), 0.02, 0.98))
            optical_lag = int(rng.integers(1, 13))
            ndvi_native = float(_bounded(0.16 + 0.73 * canopy + rng.normal(0, 0.055), -0.05, 0.94))
            ndvi_fused = float(_bounded(ndvi_native + rng.normal(0, 0.012 + 0.006 * optical_lag), -0.05, 0.95))
            ndmi = float(_bounded(-0.22 + 0.72 * canopy + rng.normal(0, 0.08), -0.55, 0.72))
            albedo = float(_bounded(0.27 - 0.10 * canopy + rng.normal(0, 0.018), 0.08, 0.36))
            albedo_uncertainty = float(0.012 + 0.0022 * optical_lag + rng.uniform(0, 0.008))
            radiation_scale = pass_row["synthetic_net_radiation_w_m2"] / 600.0
            et_base = float(_bounded(1.0 + 3.7 * canopy * radiation_scale, 0.25, 6.5))
            et_members = _bounded(et_base + rng.normal(0, [0.18, 0.24, 0.30, 0.38]), 0.05, 7.0)
            et_potential = float(_bounded(et_base + 1.1 + rng.normal(0, 0.23), 0.5, 8.0))
            esi = float(_bounded(et_members.mean() / et_potential + rng.normal(0, 0.035), 0.05, 1.05))
            land_use = str(rng.choice(land_uses, p=(0.56, 0.19, 0.15, 0.10)))
            true_tree = bool(canopy >= 0.55 and impervious <= 0.62)
            classification_score = canopy - 0.25 * impervious + rng.normal(0, 0.09)
            predicted_tree = bool(classification_score >= 0.40)
            time_term = (pass_row["synthetic_local_solar_time_hours"] - 13.5) * 0.28
            reference_lst = float(
                304.0
                + 0.62 * (pass_row["synthetic_t2m_k"] - 294.0)
                + 2.3 * impervious
                + time_term
                + rng.normal(0, 0.55)
            )
            cooling = float(
                1.05
                + 3.0 * canopy
                + 0.75 * pass_row["synthetic_demand_pct"] * pass_row["synthetic_dryness_pct"]
                + 0.12 * (pass_row["synthetic_local_solar_time_hours"] - 12.0)
                + rng.normal(0, 0.32)
            )
            tree_lst = reference_lst - cooling
            matched_rows.append(
                {
                    **pass_row,
                    "synthetic_matched_set_id": (
                        f"{pass_row['synthetic_pass_id']}_set_{set_index + 1:02d}"
                    ),
                    "synthetic_canopy_fraction": canopy,
                    "synthetic_reference_canopy_fraction": reference_canopy,
                    "synthetic_impervious_fraction": impervious,
                    "synthetic_buffer_impervious_fraction": buffer_impervious,
                    "synthetic_ndvi_native": ndvi_native,
                    "synthetic_ndvi_fused": ndvi_fused,
                    "synthetic_ndmi_prepass": ndmi,
                    "synthetic_optical_lag_days": optical_lag,
                    "synthetic_albedo": albedo,
                    "synthetic_albedo_uncertainty": albedo_uncertainty,
                    "synthetic_et_member_1": float(et_members[0]),
                    "synthetic_et_member_2": float(et_members[1]),
                    "synthetic_et_member_3": float(et_members[2]),
                    "synthetic_et_member_4": float(et_members[3]),
                    "synthetic_et_potential": et_potential,
                    "synthetic_esi": esi,
                    "synthetic_land_use": land_use,
                    "synthetic_true_tree_class": true_tree,
                    "synthetic_predicted_tree_class": predicted_tree,
                    "synthetic_tree_lst_k": tree_lst,
                    "synthetic_reference_lst_k": reference_lst,
                    "synthetic_cooling_contrast_k": cooling,
                    "synthetic_valid_tree_pixels": int(rng.integers(18, 95)),
                    "synthetic_valid_reference_pixels": int(rng.integers(20, 110)),
                    "synthetic_canopy_change_fraction": float(rng.normal(0.01, 0.055)),
                }
            )
    matched_df = pd.DataFrame(matched_rows)
    return pass_df, matched_df


def _stamp(fig: plt.Figure) -> None:
    fig.text(
        0.5,
        0.018,
        WATERMARK,
        ha="center",
        va="bottom",
        color="#9b1c1c",
        fontsize=9.5,
        fontweight="bold",
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "alpha": 0.92},
    )


def _save_figure(fig: plt.Figure, path: Path) -> Path:
    _stamp(fig)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0.055, 1, 0.98))
    fig.savefig(
        path,
        dpi=135,
        bbox_inches="tight",
        metadata={"Title": WATERMARK, "Description": WATERMARK},
    )
    plt.close(fig)
    return path


def _write_table(frame: pd.DataFrame, path: Path) -> Path:
    output = frame.copy()
    if "data_origin" not in output:
        output.insert(0, "data_origin", "synthetic")
    if "canonical_eligible" not in output:
        output.insert(1, "canonical_eligible", False)
    output["data_origin"] = "synthetic"
    output["canonical_eligible"] = False
    path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(path, index=False, lineterminator="\n")
    return path


def _scene_arrays(seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(int(seed) + 404)
    y, x = np.mgrid[0:90, 0:110]
    canopy = _bounded(
        0.18
        + 0.58 * np.exp(-((x - 27) ** 2 + (y - 33) ** 2) / 420)
        + 0.48 * np.exp(-((x - 75) ** 2 + (y - 67) ** 2) / 520)
        + rng.normal(0, 0.045, x.shape),
        0,
        1,
    )
    impervious = _bounded(0.78 - 0.62 * canopy + rng.normal(0, 0.06, x.shape), 0, 1)
    water = ((x - 91) ** 2 / 120 + (y - 19) ** 2 / 60 < 1).astype(float)
    cloud = _bounded(0.08 + 0.60 * np.exp(-((x - 54) ** 2 + (y - 18) ** 2) / 250), 0, 1)
    quality = _bounded(1.0 - 0.45 * cloud - 0.25 * water + rng.normal(0, 0.025, x.shape), 0, 1)
    temperature = (
        315.0 + 4.0 * impervious - 6.0 * canopy - 8.0 * water + rng.normal(0, 0.45, x.shape)
    )
    valid_count = np.rint(_bounded(22 * quality * (1 - 0.65 * cloud), 0, 22))
    return {
        "synthetic_canopy_fraction": canopy,
        "synthetic_impervious_fraction": impervious,
        "synthetic_water_mask": water,
        "synthetic_cloud_fraction": cloud,
        "synthetic_quality_fraction": quality,
        "synthetic_lst_k": temperature,
        "synthetic_valid_observation_count": valid_count,
    }


def _pairwise_et_table(matched: pd.DataFrame) -> pd.DataFrame:
    names = [f"synthetic_et_member_{index}" for index in range(1, 5)]
    rows = []
    for left, right in combinations(names, 2):
        difference = matched[left] - matched[right]
        rows.append(
            {
                "synthetic_member_a": left,
                "synthetic_member_b": right,
                "synthetic_correlation": matched[left].corr(matched[right]),
                "synthetic_bias": difference.mean(),
                "synthetic_rmse": np.sqrt(np.mean(np.square(difference))),
            }
        )
    return pd.DataFrame(rows)


def _classification_metrics(matched: pd.DataFrame) -> pd.DataFrame:
    work = matched.copy()
    work["synthetic_purity_class"] = pd.cut(
        work["synthetic_canopy_fraction"],
        bins=(-np.inf, 0.45, 0.70, np.inf),
        labels=("low", "medium", "high"),
    ).astype(str)
    rows = []
    group_columns = ["city", "synthetic_purity_class", "synthetic_land_use"]
    for keys, group in work.groupby(group_columns, observed=True, sort=True):
        truth = group["synthetic_true_tree_class"].astype(bool)
        prediction = group["synthetic_predicted_tree_class"].astype(bool)
        tp = int((truth & prediction).sum())
        fp = int((~truth & prediction).sum())
        fn = int((truth & ~prediction).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        rows.append(
            {
                "city": keys[0],
                "synthetic_purity_class": keys[1],
                "synthetic_land_use": keys[2],
                "synthetic_true_positive": tp,
                "synthetic_false_positive": fp,
                "synthetic_false_negative": fn,
                "synthetic_precision": precision,
                "synthetic_recall": recall,
                "synthetic_f1": f1,
            }
        )
    return pd.DataFrame(rows)


def write_steps04_08(
    output_root: str | Path,
    figure_root: str | Path,
    seed: int = DEFAULT_SEED,
) -> dict[str, Path]:
    """Write all synthetic-only Guide Step 4--8 illustrative artifacts."""

    output = Path(output_root)
    figures = Path(figure_root)
    output.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    pass_df, matched = generate_synthetic_data(seed)
    scene = _scene_arrays(seed)
    artifacts: dict[str, Path] = {}
    artifacts["synthetic_pass_dataset"] = _write_table(
        pass_df, output / "ILLUSTRATIVE_synthetic_passes.csv"
    )
    artifacts["synthetic_matched_dataset"] = _write_table(
        matched, output / "ILLUSTRATIVE_synthetic_matched_sets.csv"
    )

    # Step 4: synthetic native-scene presentation and quality accounting.
    fig, ax = plt.subplots(figsize=(8.3, 5.6))
    image = ax.imshow(scene["synthetic_lst_k"], cmap="inferno")
    for label, xy in (
        ("synthetic park", (27, 33)),
        ("synthetic golf course", (75, 67)),
        ("synthetic freeway", (55, 45)),
        ("synthetic residential", (88, 55)),
    ):
        ax.annotate(label, xy=xy, xytext=(xy[0] - 12, xy[1] - 13), color="white",
                    arrowprops={"color": "white", "width": 0.7}, fontsize=8)
    ax.set(title="ILLUSTRATIVE F4.1: synthetic hot-afternoon scene", xlabel="synthetic native-grid x", ylabel="synthetic native-grid y")
    fig.colorbar(image, ax=ax, label="synthetic LST (K)")
    artifacts["F4.1"] = _save_figure(fig, figures / "ILLUSTRATIVE_F4.1_hot_scene.png")

    fig, axes = plt.subplots(2, 2, figsize=(9.0, 6.8))
    layer_specs = (
        ("synthetic_lst_k", "inferno", "Synthetic temperature (K)"),
        ("synthetic_cloud_fraction", "Blues", "Synthetic cloud fraction"),
        ("synthetic_water_mask", "winter", "Synthetic water mask"),
        ("synthetic_quality_fraction", "viridis", "Synthetic quality fraction"),
    )
    for ax, (name, cmap, title) in zip(axes.flat, layer_specs):
        im = ax.imshow(scene[name], cmap=cmap)
        ax.set_title(title)
        fig.colorbar(im, ax=ax, fraction=0.046)
    fig.suptitle("ILLUSTRATIVE F4.2: synthetic scene layers")
    artifacts["F4.2"] = _save_figure(fig, figures / "ILLUSTRATIVE_F4.2_scene_layers.png")

    fig, ax = plt.subplots(figsize=(7.7, 4.8))
    masks = {
        "high canopy": scene["synthetic_canopy_fraction"] >= 0.65,
        "impervious": scene["synthetic_impervious_fraction"] >= 0.70,
        "water": scene["synthetic_water_mask"] > 0,
    }
    for label, mask in masks.items():
        ax.hist(scene["synthetic_lst_k"][mask], bins=22, histtype="step", linewidth=1.8, label=label)
    ax.set(title="ILLUSTRATIVE F4.3: synthetic LST distributions", xlabel="synthetic LST (K)", ylabel="synthetic pixel count")
    ax.legend(frameon=False)
    artifacts["F4.3"] = _save_figure(fig, figures / "ILLUSTRATIVE_F4.3_lst_histograms.png")

    fig, ax = plt.subplots(figsize=(7.6, 5.2))
    im = ax.imshow(scene["synthetic_valid_observation_count"], cmap="cividis", vmin=0, vmax=22)
    ax.contour(np.ones_like(scene["synthetic_lst_k"]), levels=[0.5], colors="white")
    ax.set(title="ILLUSTRATIVE F4.4: synthetic valid-observation count", xlabel="synthetic native-grid x", ylabel="synthetic native-grid y")
    fig.colorbar(im, ax=ax, label="synthetic valid observations")
    artifacts["F4.4"] = _save_figure(fig, figures / "ILLUSTRATIVE_F4.4_valid_count_map.png")

    f45 = matched.assign(
        synthetic_zenith_bin=pd.cut(
            matched["synthetic_solar_zenith_deg"], bins=(0, 25, 40, 55, 90), labels=("0-25", "25-40", "40-55", "55-90")
        )
    ).groupby(["synthetic_retrieval_mode", "synthetic_zenith_bin"], observed=True)["synthetic_reference_lst_k"].mean().reset_index()
    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    for mode, group in f45.groupby("synthetic_retrieval_mode"):
        ax.plot(group["synthetic_zenith_bin"].astype(str), group["synthetic_reference_lst_k"], marker="o", label=mode)
    ax.set(title="ILLUSTRATIVE F4.5: synthetic retrieval period within zenith bins", xlabel="synthetic solar-zenith bin (degrees)", ylabel="synthetic scene-mean LST (K)")
    ax.legend(frameon=False)
    artifacts["F4.5"] = _save_figure(fig, figures / "ILLUSTRATIVE_F4.5_mode_by_zenith.png")

    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.4))
    for index, ax in enumerate(axes):
        shifted = np.roll(scene["synthetic_lst_k"], shift=index + 1, axis=1)
        ax.imshow(np.hypot(*np.gradient(shifted)), cmap="magma")
        for offset in (18, 45, 72):
            ax.plot([0, 109], [offset, offset + (index * 4 - 2)], color="cyan", linewidth=1.0)
        ax.set_title(f"synthetic scene {index + 1}: edges + roads")
    fig.suptitle("ILLUSTRATIVE F4.6: synthetic two-scene geolocation check")
    artifacts["F4.6"] = _save_figure(fig, figures / "ILLUSTRATIVE_F4.6_geolocation_edges.png")

    t41_columns = [
        "data_origin", "canonical_eligible", "synthetic_scene_id", "synthetic_pass_id", "city",
        "year", "time_stratum", "synthetic_acquisition_utc", "synthetic_retrieval_mode",
        "synthetic_geometry_class", "synthetic_view_zenith_deg", "synthetic_cloud_fraction",
    ]
    artifacts["T4.1"] = _write_table(pass_df[t41_columns], output / "ILLUSTRATIVE_T4.1_scene_metadata.csv")
    attrition = pass_df[["data_origin", "canonical_eligible", "synthetic_scene_id", "city"]].copy()
    attrition["synthetic_initial_pixels"] = 10000
    attrition["synthetic_after_water_mask"] = np.rint(10000 * (1 - pass_df["synthetic_water_fraction"])).astype(int)
    attrition["synthetic_after_cloud_mask"] = np.rint(attrition["synthetic_after_water_mask"] * (1 - pass_df["synthetic_cloud_fraction"])).astype(int)
    attrition["synthetic_after_quality_mask"] = np.rint(attrition["synthetic_after_cloud_mask"] * pass_df["synthetic_quality_fraction"]).astype(int)
    attrition["synthetic_after_plausibility_mask"] = np.rint(attrition["synthetic_after_quality_mask"] * 0.985).astype(int)
    attrition["synthetic_final_pixels"] = np.rint(attrition["synthetic_after_plausibility_mask"] * 0.94).astype(int)
    artifacts["T4.2"] = _write_table(attrition, output / "ILLUSTRATIVE_T4.2_pixel_attrition.csv")
    dictionary_rows = [
        ("synthetic_lst_k", "simulated native-grid surface temperature", "K"),
        ("synthetic_cloud_fraction", "simulated cloud fraction", "0-1"),
        ("synthetic_water_fraction", "simulated water fraction", "0-1"),
        ("synthetic_quality_fraction", "simulated retained-quality fraction", "0-1"),
        ("synthetic_view_zenith_deg", "simulated absolute view zenith", "degrees"),
        ("synthetic_retrieval_mode", "simulated retrieval-band period", "category"),
    ]
    artifacts["T4.3"] = _write_table(
        pd.DataFrame(dictionary_rows, columns=("synthetic_field", "synthetic_definition", "synthetic_unit"))
        .assign(synthetic_source="deterministic simulator; no product opened"),
        output / "ILLUSTRATIVE_T4.3_data_dictionary.csv",
    )

    # Step 5: synthetic supporting-product consistency and uncertainty.
    fig, ax = plt.subplots(figsize=(7.3, 4.7))
    good = matched[matched["synthetic_optical_lag_days"] <= 4]
    degraded = matched[matched["synthetic_optical_lag_days"] >= 9]
    ax.errorbar(good["synthetic_albedo"].mean(), 0, xerr=good["synthetic_albedo_uncertainty"].mean(), fmt="o", label="synthetic good")
    ax.errorbar(degraded["synthetic_albedo"].mean(), 1, xerr=degraded["synthetic_albedo_uncertainty"].mean(), fmt="o", label="synthetic degraded")
    ax.set_yticks((0, 1), ("good", "degraded"))
    ax.set(title="ILLUSTRATIVE F5.1: synthetic albedo uncertainty", xlabel="synthetic albedo")
    ax.legend(frameon=False)
    artifacts["F5.1"] = _save_figure(fig, figures / "ILLUSTRATIVE_F5.1_albedo_uncertainty.png")

    fig, ax = plt.subplots(figsize=(6.4, 5.1))
    scatter = ax.scatter(matched["synthetic_ndvi_native"], matched["synthetic_ndvi_fused"], c=matched["synthetic_optical_lag_days"], s=12, alpha=0.55, cmap="viridis")
    ax.plot((-0.1, 1), (-0.1, 1), color="black", linestyle="--")
    ax.set(title="ILLUSTRATIVE F5.2: synthetic fused versus native vegetation", xlabel="synthetic native vegetation index", ylabel="synthetic fused vegetation index")
    fig.colorbar(scatter, ax=ax, label="synthetic lag (days)")
    artifacts["F5.2"] = _save_figure(fig, figures / "ILLUSTRATIVE_F5.2_fused_vs_native.png")

    fusion = matched.assign(synthetic_absolute_fusion_error=(matched["synthetic_ndvi_fused"] - matched["synthetic_ndvi_native"]).abs())
    lag_summary = fusion.groupby("synthetic_optical_lag_days")["synthetic_absolute_fusion_error"].mean().reset_index()
    coefficients = np.polyfit(lag_summary["synthetic_optical_lag_days"], lag_summary["synthetic_absolute_fusion_error"], 1)
    fig, ax = plt.subplots(figsize=(7.2, 4.7))
    ax.scatter(fusion["synthetic_optical_lag_days"], fusion["synthetic_absolute_fusion_error"], s=9, alpha=0.2)
    xline = np.arange(1, 13)
    ax.plot(xline, np.polyval(coefficients, xline), color="#b2182b", linewidth=2)
    ax.set(title="ILLUSTRATIVE F5.3: synthetic fusion error by lag", xlabel="synthetic lag (days)", ylabel="synthetic absolute fusion error")
    artifacts["F5.3"] = _save_figure(fig, figures / "ILLUSTRATIVE_F5.3_fusion_error_lag.png")

    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.5), sharex=True)
    for city, group in pass_df.groupby("city"):
        ordered = group.sort_values("synthetic_solar_zenith_deg")
        axes[0].plot(ordered["synthetic_solar_zenith_deg"], ordered["synthetic_incoming_radiation_w_m2"], marker=".", label=city)
        axes[1].plot(ordered["synthetic_solar_zenith_deg"], ordered["synthetic_net_radiation_w_m2"], marker=".", label=city)
    axes[0].set(title="incoming", xlabel="synthetic solar zenith (degrees)", ylabel="synthetic radiation (W m-2)")
    axes[1].set(title="net", xlabel="synthetic solar zenith (degrees)")
    axes[1].legend(frameon=False, fontsize=7)
    fig.suptitle("ILLUSTRATIVE F5.4: synthetic radiation versus solar zenith")
    artifacts["F5.4"] = _save_figure(fig, figures / "ILLUSTRATIVE_F5.4_radiation_zenith.png")

    et_names = [f"synthetic_et_member_{index}" for index in range(1, 5)]
    fig, axes = plt.subplots(2, 3, figsize=(10.0, 6.2))
    for ax, (left, right) in zip(axes.flat, combinations(et_names, 2)):
        ax.scatter(matched[left], matched[right], s=8, alpha=0.30)
        ax.set(xlabel=left.replace("synthetic_et_", ""), ylabel=right.replace("synthetic_et_", ""))
    fig.suptitle("ILLUSTRATIVE F5.5: synthetic four-member ET pairs")
    artifacts["F5.5"] = _save_figure(fig, figures / "ILLUSTRATIVE_F5.5_et_pairs.png")

    fig, ax = plt.subplots(figsize=(6.6, 5.0))
    et_ratio = matched[et_names].mean(axis=1) / matched["synthetic_et_potential"]
    ax.scatter(et_ratio, matched["synthetic_esi"], s=10, alpha=0.35)
    ax.plot((0, 1.1), (0, 1.1), linestyle="--", color="black")
    ax.set(title="ILLUSTRATIVE F5.6: synthetic evaporative-stress consistency", xlabel="synthetic ET/PET", ylabel="synthetic ESI")
    artifacts["F5.6"] = _save_figure(fig, figures / "ILLUSTRATIVE_F5.6_esi_consistency.png")

    t51 = pd.DataFrame(
        {
            "synthetic_product": ("albedo", "vegetation_fusion", "radiation", "et_family_a", "et_family_b", "evaporative_stress"),
            "synthetic_version": ("sim-v1",) * 6,
            "synthetic_layer": ("albedo", "ndvi", "net_radiation", "et_members_1_4", "et_potential", "esi"),
            "synthetic_scene_match_fraction": (1.0, 0.94, 1.0, 0.92, 0.90, 0.89),
        }
    )
    artifacts["T5.1"] = _write_table(t51, output / "ILLUSTRATIVE_T5.1_product_inventory.csv")
    artifacts["T5.2"] = _write_table(_pairwise_et_table(matched), output / "ILLUSTRATIVE_T5.2_et_pair_statistics.csv")

    # Step 6: entirely synthetic weather validation and alignment diagnostics.
    fig, ax = plt.subplots(figsize=(6.4, 5.1))
    ax.scatter(pass_df["synthetic_station_vpd_kpa"], pass_df["synthetic_hrrr_vpd_kpa"], s=18, alpha=0.5)
    limits = (0, 6.2)
    ax.plot(limits, limits, linestyle="--", color="black")
    ax.set(xlim=limits, ylim=limits, title="ILLUSTRATIVE F6.1: synthetic gridded versus station VPD", xlabel="synthetic station VPD (kPa)", ylabel="synthetic gridded VPD (kPa)")
    artifacts["F6.1"] = _save_figure(fig, figures / "ILLUSTRATIVE_F6.1_vpd_station.png")

    daily_rng = np.random.default_rng(int(seed) + 602)
    days = np.arange(153, 275)
    seasonal_demand = 3.6 + 1.0 * np.sin((days - 153) / 122 * np.pi) + daily_rng.normal(0, 0.15, len(days))
    balance30 = -150 + 0.85 * (days - 153) + 55 / (1 + np.exp(-(days - 205) / 4)) + daily_rng.normal(0, 5, len(days))
    balance60 = -255 + 0.65 * (days - 153) + 70 / (1 + np.exp(-(days - 210) / 6)) + daily_rng.normal(0, 6, len(days))
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.plot(days, seasonal_demand, color="#b2182b", label="synthetic demand (kPa)")
    ax2 = ax.twinx()
    ax2.plot(days, balance30, color="#2166ac", label="synthetic 30-day balance")
    ax2.plot(days, balance60, color="#67a9cf", label="synthetic 60-day balance")
    example_passes = pass_df.loc[pass_df["city"].eq(SIM_CITIES[0]), "synthetic_day_of_year"]
    for value in example_passes:
        ax.axvline(value, color="0.5", alpha=0.12)
    ax.axvline(205, color="green", linestyle="--", label="synthetic monsoon onset")
    ax.set(title="ILLUSTRATIVE F6.2: synthetic seasonal demand and water balance", xlabel="synthetic day of year", ylabel="synthetic demand (kPa)")
    ax2.set_ylabel("synthetic climatic water balance (mm)")
    ax.legend(frameon=False, fontsize=7, loc="upper left")
    ax2.legend(frameon=False, fontsize=7, loc="lower right")
    artifacts["F6.2"] = _save_figure(fig, figures / "ILLUSTRATIVE_F6.2_seasonal_weather.png")

    corr_columns = [
        "synthetic_hrrr_vpd_kpa", "synthetic_dryness_pct", "synthetic_water_balance_30_mm",
        "synthetic_local_solar_time_hours", "synthetic_solar_zenith_deg", "synthetic_net_radiation_w_m2",
    ]
    correlation = pass_df[corr_columns].corr()
    fig, ax = plt.subplots(figsize=(7.5, 6.0))
    im = ax.imshow(correlation, cmap="coolwarm", vmin=-1, vmax=1)
    labels = [name.replace("synthetic_", "") for name in corr_columns]
    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(labels)), labels, fontsize=8)
    for row in range(len(labels)):
        for column in range(len(labels)):
            ax.text(column, row, f"{correlation.iloc[row, column]:.2f}", ha="center", va="center", fontsize=7)
    fig.colorbar(im, ax=ax, label="synthetic correlation")
    ax.set_title("ILLUSTRATIVE F6.3: synthetic pass-time correlation")
    artifacts["F6.3"] = _save_figure(fig, figures / "ILLUSTRATIVE_F6.3_weather_correlation.png")

    fig, ax = plt.subplots(figsize=(6.4, 5.1))
    ax.scatter(pass_df["synthetic_hrrr_vpd_kpa"], pass_df["synthetic_era5_vpd_kpa"], s=18, alpha=0.5)
    ax.plot((0, 6.2), (0, 6.2), linestyle="--", color="black")
    ax.set(title="ILLUSTRATIVE F6.4: synthetic HRRR versus ERA5", xlabel="synthetic HRRR VPD (kPa)", ylabel="synthetic ERA5 VPD (kPa)")
    artifacts["F6.4"] = _save_figure(fig, figures / "ILLUSTRATIVE_F6.4_hrrr_era5.png")

    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.5))
    axes[0].scatter(pass_df["synthetic_nearest_hour_vpd_kpa"], pass_df["synthetic_interpolated_vpd_kpa"], s=17, alpha=0.5)
    axes[0].plot((0, 6.2), (0, 6.2), linestyle="--", color="black")
    difference = pass_df["synthetic_nearest_hour_vpd_kpa"] - pass_df["synthetic_interpolated_vpd_kpa"]
    axes[1].hist(difference, bins=20, color="#4d9221", edgecolor="white")
    axes[0].set(xlabel="synthetic nearest hour", ylabel="synthetic interpolation")
    axes[1].set(xlabel="synthetic nearest - interpolated VPD (kPa)", ylabel="count")
    fig.suptitle("ILLUSTRATIVE F6.5: synthetic interpolation comparison")
    artifacts["F6.5"] = _save_figure(fig, figures / "ILLUSTRATIVE_F6.5_interpolation.png")

    t61_rows = []
    for city, group in pass_df.groupby("city"):
        for variable, grid, station in (
            ("temperature", "synthetic_t2m_k", "synthetic_station_t2m_k"),
            ("dewpoint", "synthetic_d2m_k", "synthetic_station_d2m_k"),
            ("vpd", "synthetic_hrrr_vpd_kpa", "synthetic_station_vpd_kpa"),
        ):
            delta = group[grid] - group[station]
            t61_rows.append({"city": city, "synthetic_variable": variable, "synthetic_bias": delta.mean(), "synthetic_rmse": np.sqrt(np.mean(delta**2)), "synthetic_n": len(group)})
    artifacts["T6.1"] = _write_table(pd.DataFrame(t61_rows), output / "ILLUSTRATIVE_T6.1_weather_validation.csv")

    bootstrap_rng = np.random.default_rng(int(seed) + 603)
    t62_rows = []
    for predictor in ("synthetic_dryness_pct", "synthetic_water_balance_30_mm", "synthetic_water_balance_60_mm"):
        xrank = pass_df["synthetic_hrrr_vpd_kpa"].rank().to_numpy()
        yrank = pass_df[predictor].rank().to_numpy()
        estimate = float(np.corrcoef(xrank, yrank)[0, 1])
        draws = []
        for _ in range(200):
            indices = bootstrap_rng.integers(0, len(pass_df), len(pass_df))
            draws.append(float(np.corrcoef(xrank[indices], yrank[indices])[0, 1]))
        t62_rows.append({"synthetic_variable_a": "synthetic_hrrr_vpd_kpa", "synthetic_variable_b": predictor, "synthetic_spearman": estimate, "synthetic_ci_low": np.quantile(draws, 0.025), "synthetic_ci_high": np.quantile(draws, 0.975), "synthetic_bootstrap_draws": 200})
    artifacts["T6.2"] = _write_table(pd.DataFrame(t62_rows), output / "ILLUSTRATIVE_T6.2_weather_correlations.csv")

    # Step 7: synthetic optical, canopy-change, and urban-form diagnostics.
    fig, axes = plt.subplots(1, 3, figsize=(11.0, 4.2))
    prepass = _bounded(scene["synthetic_canopy_fraction"] + np.random.default_rng(int(seed) + 701).normal(0, 0.07, scene["synthetic_canopy_fraction"].shape), 0, 1)
    moisture = _bounded(0.12 + 0.65 * scene["synthetic_canopy_fraction"] - 0.20 * scene["synthetic_impervious_fraction"], -0.2, 0.8)
    for ax, layer, title, cmap in (
        (axes[0], prepass, "synthetic pre-pass vegetation", "YlGn"),
        (axes[1], moisture, "synthetic pre-pass moisture", "BrBG"),
        (axes[2], scene["synthetic_canopy_fraction"], "synthetic seasonal vegetation", "YlGn"),
    ):
        im = ax.imshow(layer, cmap=cmap)
        ax.set_title(title, fontsize=9)
        fig.colorbar(im, ax=ax, fraction=0.046)
    fig.suptitle("ILLUSTRATIVE F7.1: synthetic optical composites")
    artifacts["F7.1"] = _save_figure(fig, figures / "ILLUSTRATIVE_F7.1_optical_composites.png")

    fig, ax = plt.subplots(figsize=(8.0, 4.6))
    grouped_lag = [matched.loc[matched["city"].eq(city), "synthetic_optical_lag_days"] for city in SIM_CITIES]
    ax.boxplot(grouped_lag, tick_labels=SIM_CITIES, showfliers=False)
    ax.axhline(10, color="#b2182b", linestyle="--", label="synthetic cutoff")
    ax.set(title="ILLUSTRATIVE F7.2: synthetic optical-image lag", ylabel="synthetic lag (days)")
    ax.tick_params(axis="x", rotation=25)
    ax.legend(frameon=False)
    artifacts["F7.2"] = _save_figure(fig, figures / "ILLUSTRATIVE_F7.2_optical_lag.png")

    fig, ax = plt.subplots(figsize=(7.2, 5.0))
    outlier = matched["synthetic_land_use"].isin(("park",)) & (matched["synthetic_ndvi_native"] > 0.55)
    ax.scatter(matched.loc[~outlier, "synthetic_canopy_fraction"], matched.loc[~outlier, "synthetic_ndvi_native"], s=10, alpha=0.3, label="synthetic other")
    ax.scatter(matched.loc[outlier, "synthetic_canopy_fraction"], matched.loc[outlier, "synthetic_ndvi_native"], s=14, alpha=0.55, label="synthetic turf/park outlier")
    ax.set(title="ILLUSTRATIVE F7.3: synthetic canopy versus vegetation index", xlabel="synthetic canopy fraction", ylabel="synthetic seasonal vegetation index")
    ax.legend(frameon=False)
    artifacts["F7.3"] = _save_figure(fig, figures / "ILLUSTRATIVE_F7.3_canopy_vegetation.png")

    city_one = matched[matched["city"].eq(SIM_CITIES[0])]
    annual_canopy = city_one.groupby("year")["synthetic_canopy_fraction"].mean()
    flagged_share = city_one["synthetic_canopy_change_fraction"].abs().gt(0.10).mean()
    fig, ax = plt.subplots(figsize=(7.3, 4.7))
    ax.bar(annual_canopy.index.astype(str), annual_canopy.values, color="#238b45")
    ax.text(0.02, 0.95, f"synthetic flagged share: {flagged_share:.1%}", transform=ax.transAxes, va="top")
    ax.set(title="ILLUSTRATIVE F7.4: synthetic first-to-last canopy", xlabel="synthetic year", ylabel="synthetic canopy fraction", ylim=(0, 1))
    artifacts["F7.4"] = _save_figure(fig, figures / "ILLUSTRATIVE_F7.4_canopy_change.png")

    fig, ax = plt.subplots(figsize=(6.7, 5.0))
    ax.scatter(matched["synthetic_impervious_fraction"], matched["synthetic_buffer_impervious_fraction"], s=10, alpha=0.35)
    ax.plot((0, 1), (0, 1), linestyle="--", color="black")
    ax.set(title="ILLUSTRATIVE F7.5: synthetic focal versus buffer imperviousness", xlabel="synthetic focal impervious fraction", ylabel="synthetic buffer impervious fraction")
    artifacts["F7.5"] = _save_figure(fig, figures / "ILLUSTRATIVE_F7.5_focal_buffer_impervious.png")

    t71 = pd.DataFrame(
        {
            "synthetic_product": ("optical vegetation", "optical moisture", "canopy", "impervious", "land cover"),
            "synthetic_release": ("sim-v1",) * 5,
            "synthetic_resolution_m": (30, 30, 10, 30, 30),
            "synthetic_year_assignment": ("pre-pass", "pre-pass", "nearest prior release", "nearest prior release", "nearest prior release"),
        }
    )
    artifacts["T7.1"] = _write_table(t71, output / "ILLUSTRATIVE_T7.1_landcover_inventory.csv")
    exclusions = matched.assign(synthetic_change_excluded=matched["synthetic_canopy_change_fraction"].abs().gt(0.10)).groupby(["city", "year"], as_index=False).agg(synthetic_rows=("synthetic_matched_set_id", "size"), synthetic_change_exclusions=("synthetic_change_excluded", "sum"))
    artifacts["T7.2"] = _write_table(exclusions, output / "ILLUSTRATIVE_T7.2_canopy_change_exclusions.csv")

    # Step 8: synthetic classification, balance, validation, and sensitivity.
    thresholds = (0.40, 0.55, 0.70)
    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    ax.hist(matched["synthetic_canopy_fraction"], bins=24, color="#74c476", edgecolor="white")
    for threshold in thresholds:
        ax.axvline(threshold, linestyle="--", label=f"synthetic threshold {threshold:.2f}")
    ax.set(title="ILLUSTRATIVE F8.1: synthetic canopy thresholds", xlabel="synthetic canopy fraction", ylabel="synthetic matched-set count")
    ax.legend(frameon=False, fontsize=8)
    artifacts["F8.1"] = _save_figure(fig, figures / "ILLUSTRATIVE_F8.1_canopy_thresholds.png")

    classification = np.full_like(scene["synthetic_canopy_fraction"], 0.0)
    tree_pixels = (scene["synthetic_canopy_fraction"] >= 0.55) & (scene["synthetic_impervious_fraction"] <= 0.62)
    reference_pixels = (scene["synthetic_canopy_fraction"] < 0.25) & (scene["synthetic_impervious_fraction"] >= 0.55)
    classification[reference_pixels] = 1
    classification[tree_pixels] = 2
    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.5))
    for ax, subset, title in ((axes[0], classification[:, :55], "synthetic residential"), (axes[1], classification[:, 55:], "synthetic park")):
        im = ax.imshow(subset, cmap="viridis", vmin=0, vmax=2)
        ax.set_title(title)
    fig.colorbar(im, ax=axes.ravel().tolist(), ticks=(0, 1, 2), label="excluded / reference / tree")
    fig.suptitle("ILLUSTRATIVE F8.2: synthetic tree/reference maps")
    artifacts["F8.2"] = _save_figure(fig, figures / "ILLUSTRATIVE_F8.2_class_maps.png")

    balance = pd.DataFrame(
        {
            "synthetic_covariate": ("impervious", "albedo", "solar_zenith", "demand", "dryness", "buffer_impervious"),
            "synthetic_smd_before": (0.42, -0.28, 0.21, 0.16, -0.31, 0.36),
            "synthetic_smd_after": (0.06, -0.04, 0.03, 0.05, -0.07, 0.08),
        }
    )
    fig, ax = plt.subplots(figsize=(7.5, 4.9))
    positions = np.arange(len(balance))
    ax.scatter(balance["synthetic_smd_before"], positions, label="synthetic before", marker="x", s=55)
    ax.scatter(balance["synthetic_smd_after"], positions, label="synthetic after", marker="o", s=42)
    ax.axvline(-0.1, color="0.4", linestyle="--")
    ax.axvline(0.1, color="0.4", linestyle="--")
    ax.set_yticks(positions, balance["synthetic_covariate"])
    ax.set(title="ILLUSTRATIVE F8.3: synthetic matching balance", xlabel="synthetic standardized mean difference")
    ax.legend(frameon=False)
    artifacts["F8.3"] = _save_figure(fig, figures / "ILLUSTRATIVE_F8.3_balance.png")

    shift_labels = ("unshifted", "north", "south", "east", "west")
    base_cooling = matched["synthetic_cooling_contrast_k"].mean()
    shift_estimates = base_cooling + np.array((0.0, -0.16, 0.12, -0.09, 0.18))
    fig, ax = plt.subplots(figsize=(7.2, 4.7))
    ax.errorbar(shift_labels, shift_estimates, yerr=(0.18, 0.24, 0.22, 0.20, 0.23), fmt="o", capsize=3)
    ax.axhline(base_cooling, color="black", linestyle="--")
    ax.set(title="ILLUSTRATIVE F8.4: synthetic registration sensitivity", ylabel="synthetic cooling contrast (K)")
    artifacts["F8.4"] = _save_figure(fig, figures / "ILLUSTRATIVE_F8.4_registration.png")

    fig, axes = plt.subplots(1, 4, figsize=(11.0, 3.5))
    for ax, land_use in zip(axes, ("residential", "park", "commercial", "institutional")):
        group = matched[matched["synthetic_land_use"].eq(land_use)]
        truth = group["synthetic_true_tree_class"].astype(int)
        predicted = group["synthetic_predicted_tree_class"].astype(int)
        matrix = np.array(
            [[((truth == 0) & (predicted == 0)).sum(), ((truth == 0) & (predicted == 1)).sum()],
             [((truth == 1) & (predicted == 0)).sum(), ((truth == 1) & (predicted == 1)).sum()]]
        )
        ax.imshow(matrix, cmap="Blues")
        for row in range(2):
            for column in range(2):
                ax.text(column, row, str(matrix[row, column]), ha="center", va="center")
        ax.set_title(land_use, fontsize=8)
        ax.set_xticks((0, 1), ("pred 0", "pred 1"), fontsize=7)
        ax.set_yticks((0, 1), ("true 0", "true 1"), fontsize=7)
    fig.suptitle("ILLUSTRATIVE F8.5: synthetic confusion matrices")
    artifacts["F8.5"] = _save_figure(fig, figures / "ILLUSTRATIVE_F8.5_confusion_matrices.png")

    composition = matched.loc[matched["synthetic_predicted_tree_class"]].groupby(["city", "synthetic_land_use"]).size().unstack(fill_value=0)
    composition = composition.div(composition.sum(axis=1), axis=0)
    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    composition.plot(kind="bar", stacked=True, ax=ax, colormap="Set2")
    ax.set(title="ILLUSTRATIVE F8.6: synthetic tree-sample land-use composition", xlabel="generic synthetic city", ylabel="synthetic proportion")
    ax.legend(frameon=False, fontsize=7)
    artifacts["F8.6"] = _save_figure(fig, figures / "ILLUSTRATIVE_F8.6_landuse_composition.png")

    fig, ax = plt.subplots(figsize=(7.0, 5.0))
    ax.scatter(matched["synthetic_canopy_fraction"], matched["synthetic_tree_lst_k"], s=9, alpha=0.23)
    coefficients = np.polyfit(matched["synthetic_canopy_fraction"], matched["synthetic_tree_lst_k"], 2)
    xline = np.linspace(0.05, 0.96, 120)
    ax.plot(xline, np.polyval(coefficients, xline), color="#b2182b", linewidth=2)
    ax.set(title="ILLUSTRATIVE F8.7: synthetic continuous canopy-temperature smooth", xlabel="synthetic canopy fraction", ylabel="synthetic tree LST (K)")
    artifacts["F8.7"] = _save_figure(fig, figures / "ILLUSTRATIVE_F8.7_continuous_canopy.png")

    artifacts["T8.1"] = _write_table(_classification_metrics(matched), output / "ILLUSTRATIVE_T8.1_validation_metrics.csv")
    artifacts["T8.2"] = _write_table(balance, output / "ILLUSTRATIVE_T8.2_covariate_balance.csv")
    count_rows = []
    for city, group in matched.groupby("city"):
        for threshold in thresholds:
            trees = int(group["synthetic_canopy_fraction"].ge(threshold).sum())
            references = int(group["synthetic_reference_canopy_fraction"].lt(0.25).sum())
            count_rows.append({"city": city, "synthetic_canopy_threshold": threshold, "synthetic_tree_count": trees, "synthetic_reference_count": references, "synthetic_matched_set_count": min(trees, references)})
    artifacts["T8.3"] = _write_table(pd.DataFrame(count_rows), output / "ILLUSTRATIVE_T8.3_threshold_counts.csv")

    return artifacts


__all__ = [
    "DEFAULT_SEED",
    "SIM_CITIES",
    "WATERMARK",
    "generate_synthetic_data",
    "write_steps04_08",
]
