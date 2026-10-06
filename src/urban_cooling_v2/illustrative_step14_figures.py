"""Synthetic-only paper figures for the quarantined illustrative package.

The writer consumes only the deterministic synthetic tables used by the
illustrative Guide Steps 4--13.  It performs no network access, has no
canonical-data fallback, and writes only six visibly watermarked PNG files.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np
import pandas as pd

from urban_cooling_v2.illustrative_steps02_08 import (
    DEFAULT_SEED,
    SIM_CITIES,
    generate_synthetic_data,
)


WATERMARK = "ILLUSTRATIVE — SYNTHETIC DATA — NOT A STUDY RESULT"
DAY_STRATA = ("10-12", "12-14", "14-16", "16-18")
EXPECTED_IDS = tuple(f"F14.{index}" for index in range(1, 7))
_SAVED_PASS_NAME = "ILLUSTRATIVE_synthetic_passes.csv"
_SAVED_MATCHED_NAME = "ILLUSTRATIVE_synthetic_matched_sets.csv"


def _false_series(values: pd.Series, *, label: str) -> None:
    normalized = values.astype(str).str.strip().str.casefold()
    if not normalized.isin({"false", "0"}).all():
        raise ValueError(f"{label} must be uniformly false")


def _validate_tables(
    pass_df: pd.DataFrame, matched_df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required_pass = {
        "data_origin",
        "canonical_eligible",
        "synthetic_pass_id",
        "city",
        "time_stratum",
        "synthetic_local_solar_time_hours",
        "synthetic_demand_pct",
        "synthetic_dryness_pct",
        "synthetic_solar_zenith_deg",
        "synthetic_incoming_radiation_w_m2",
    }
    required_matched = {
        "data_origin",
        "canonical_eligible",
        "synthetic_pass_id",
        "synthetic_matched_set_id",
        "city",
        "time_stratum",
        "synthetic_local_solar_time_hours",
        "synthetic_demand_pct",
        "synthetic_dryness_pct",
        "synthetic_canopy_fraction",
        "synthetic_reference_canopy_fraction",
        "synthetic_albedo",
        "synthetic_incoming_radiation_w_m2",
        "synthetic_et_member_1",
        "synthetic_et_member_2",
        "synthetic_et_member_3",
        "synthetic_et_member_4",
        "synthetic_et_potential",
        "synthetic_esi",
        "synthetic_ndvi_native",
        "synthetic_tree_lst_k",
        "synthetic_reference_lst_k",
        "synthetic_cooling_contrast_k",
        "synthetic_true_tree_class",
        "synthetic_predicted_tree_class",
    }
    missing_pass = sorted(required_pass.difference(pass_df.columns))
    missing_matched = sorted(required_matched.difference(matched_df.columns))
    if missing_pass or missing_matched:
        raise ValueError(
            "illustrative Step-14 source schema is incomplete; "
            f"pass_missing={missing_pass}, matched_missing={missing_matched}"
        )
    if pass_df.empty or matched_df.empty:
        raise ValueError("illustrative Step-14 source tables must be non-empty")
    for name, frame in (("pass", pass_df), ("matched", matched_df)):
        if not frame["data_origin"].astype(str).str.casefold().eq("synthetic").all():
            raise ValueError(f"{name} data_origin must be uniformly synthetic")
        _false_series(frame["canonical_eligible"], label=f"{name} canonical_eligible")
        cities = set(frame["city"].astype(str))
        if cities != set(SIM_CITIES):
            raise ValueError(
                f"{name} data must use exactly the five generic sim_city labels; "
                f"found {sorted(cities)}"
            )
    strata_by_city = pass_df.groupby("city")["time_stratum"].agg(set)
    for city, strata in strata_by_city.items():
        missing = set((*DAY_STRATA, "night")).difference(map(str, strata))
        if missing:
            raise ValueError(f"{city} lacks synthetic strata {sorted(missing)}")
    return pass_df.copy(), matched_df.copy()


def _load_existing_tables(
    output_root: Path, *, seed: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load exact quarantined tables when present, else use their shared API."""

    pass_path = output_root / _SAVED_PASS_NAME
    matched_path = output_root / _SAVED_MATCHED_NAME
    present = (pass_path.is_file(), matched_path.is_file())
    if any(present) and not all(present):
        raise FileNotFoundError(
            "illustrative Step-14 requires both saved synthetic source tables or neither"
        )
    if all(present):
        pass_df = pd.read_csv(pass_path)
        matched_df = pd.read_csv(matched_path)
    else:
        pass_df, matched_df = generate_synthetic_data(seed=int(seed))
    return _validate_tables(pass_df, matched_df)


def _pass_means(matched: pd.DataFrame) -> pd.DataFrame:
    numeric = [
        column
        for column in matched.columns
        if column.startswith("synthetic_")
        and pd.api.types.is_numeric_dtype(matched[column])
        and column not in {"synthetic_is_day"}
    ]
    first = ["city", "time_stratum"]
    return (
        matched.groupby("synthetic_pass_id", sort=True)
        .agg({**{column: "mean" for column in numeric}, **{column: "first" for column in first}})
        .reset_index()
    )


def _mean_interval(values: pd.Series) -> tuple[float, float]:
    clean = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if len(clean) == 0:
        return np.nan, np.nan
    mean = float(np.mean(clean))
    if len(clean) == 1:
        return mean, 0.0
    return mean, float(1.96 * np.std(clean, ddof=1) / np.sqrt(len(clean)))


def _stamp_and_save(fig: plt.Figure, path: Path) -> Path:
    fig.text(
        0.5,
        0.016,
        WATERMARK,
        ha="center",
        va="bottom",
        fontsize=10,
        fontweight="bold",
        color="#991b1b",
        bbox={
            "boxstyle": "round,pad=0.28",
            "facecolor": "white",
            "edgecolor": "#991b1b",
            "alpha": 0.95,
        },
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.subplots_adjust(bottom=0.18, top=0.88, wspace=0.34, hspace=0.36)
    fig.savefig(
        path,
        dpi=150,
        bbox_inches="tight",
        metadata={"Title": WATERMARK, "Description": WATERMARK},
    )
    plt.close(fig)
    return path


def _figure_1(
    pass_df: pd.DataFrame, matched: pd.DataFrame, path: Path
) -> Path:
    fig = plt.figure(figsize=(13.2, 4.5))
    grid = fig.add_gridspec(1, 3, width_ratios=(1.0, 1.05, 1.35))

    ax = fig.add_subplot(grid[0, 0])
    domain_xy = np.array(((0.18, 0.72), (0.72, 0.78), (0.83, 0.28), (0.43, 0.18), (0.12, 0.30)))
    sizes = pass_df.groupby("city")["synthetic_pass_id"].nunique().reindex(SIM_CITIES)
    ax.scatter(domain_xy[:, 0], domain_xy[:, 1], s=210 + 4 * sizes.to_numpy(), c=np.arange(5), cmap="viridis", edgecolor="black")
    for index, city in enumerate(SIM_CITIES):
        ax.text(domain_xy[index, 0], domain_xy[index, 1] - 0.105, city, ha="center", fontsize=8)
    ax.set(xlim=(0, 1), ylim=(0, 1), title="A  Generic synthetic study domains")
    ax.set_xticks([])
    ax.set_yticks([])

    ax = fig.add_subplot(grid[0, 1])
    canopy = matched["synthetic_canopy_fraction"]
    reference = matched["synthetic_reference_canopy_fraction"]
    ax.hist(reference, bins=np.linspace(0, 1, 22), alpha=0.65, color="#d95f02", label="synthetic reference")
    ax.hist(canopy, bins=np.linspace(0, 1, 22), alpha=0.58, color="#1b9e77", label="synthetic tree")
    ax.annotate(
        "within-pass\nsynthetic pairing",
        xy=(0.43, ax.get_ylim()[1] * 0.42),
        xytext=(0.60, ax.get_ylim()[1] * 0.54),
        arrowprops={"arrowstyle": "->"},
        fontsize=8,
        ha="center",
    )
    ax.set(title="B  Synthetic matched comparison", xlabel="synthetic canopy fraction", ylabel="matched-set count")
    ax.legend(frameon=False, fontsize=8)

    ax = fig.add_subplot(grid[0, 2])
    order = (*DAY_STRATA, "night")
    coverage = pass_df.groupby(["city", "time_stratum"])["synthetic_pass_id"].nunique().unstack(fill_value=0).reindex(index=SIM_CITIES, columns=order, fill_value=0)
    image = ax.imshow(coverage, cmap="Blues", aspect="auto")
    for row in range(len(coverage)):
        for column in range(len(order)):
            ax.text(column, row, str(int(coverage.iloc[row, column])), ha="center", va="center", fontsize=8)
    ax.set_xticks(range(len(order)), order, rotation=30, ha="right")
    ax.set_yticks(range(len(SIM_CITIES)), SIM_CITIES)
    ax.set_title("C  Synthetic pass coverage")
    fig.colorbar(image, ax=ax, label="synthetic passes", fraction=0.045)
    fig.suptitle("F14.1 / Paper Figure 1 — synthetic study design")
    return _stamp_and_save(fig, path)


def _figure_2(matched: pd.DataFrame, path: Path) -> Path:
    pass_level = _pass_means(matched)
    fig, axes = plt.subplots(1, 2, figsize=(12.6, 4.8), gridspec_kw={"width_ratios": (1.45, 1)})
    x = np.arange(len(DAY_STRATA))
    colors = plt.cm.viridis(np.linspace(0.08, 0.92, len(SIM_CITIES)))
    for color, city in zip(colors, SIM_CITIES):
        group = pass_level[pass_level["city"].eq(city)]
        means, errors = zip(*[
            _mean_interval(group.loc[group["time_stratum"].eq(stratum), "synthetic_cooling_contrast_k"])
            for stratum in DAY_STRATA
        ])
        axes[0].errorbar(x, means, yerr=errors, marker="o", capsize=2, linewidth=1.25, color=color, label=city)
    axes[0].set_xticks(x, DAY_STRATA)
    axes[0].set(title="A  Synthetic local-time pattern by city", xlabel="synthetic local-solar-time stratum", ylabel="synthetic cooling contrast (K)")
    axes[0].legend(frameon=False, fontsize=7, ncol=2)

    pooled_means, pooled_errors = zip(*[
        _mean_interval(pass_level.loc[pass_level["time_stratum"].eq(stratum), "synthetic_cooling_contrast_k"])
        for stratum in DAY_STRATA
    ])
    axes[1].errorbar(x, pooled_means, yerr=pooled_errors, marker="o", color="#2166ac", capsize=3, label="synthetic pooled")
    fixed_context = float(pass_level.loc[pass_level["time_stratum"].eq("12-14"), "synthetic_cooling_contrast_k"].mean())
    axes[1].axhline(fixed_context, color="#b2182b", linestyle="--", label="synthetic fixed-overpass context")
    axes[1].fill_between((-0.35, 3.35), fixed_context - 0.18, fixed_context + 0.18, color="#b2182b", alpha=0.10)
    axes[1].set_xticks(x, DAY_STRATA)
    axes[1].set(xlim=(-0.35, 3.35), title="B  Synthetic pooled estimate", xlabel="synthetic local-solar-time stratum", ylabel="synthetic cooling contrast (K)")
    axes[1].legend(frameon=False, fontsize=8)
    fig.suptitle("F14.2 / Paper Figure 2 — synthetic primary-result layout")
    return _stamp_and_save(fig, path)


def _surface(pass_level: pd.DataFrame, bins: int = 7) -> tuple[np.ma.MaskedArray, np.ndarray]:
    edges = np.linspace(0, 1, bins + 1)
    crown_area_bin = pd.cut(
        pass_level["synthetic_canopy_fraction"],
        edges,
        labels=False,
        include_lowest=True,
    )
    dryness_bin = pd.cut(pass_level["synthetic_dryness_pct"], edges, labels=False, include_lowest=True)
    work = pass_level.assign(
        _crown_area_bin=crown_area_bin, _dryness_bin=dryness_bin
    ).dropna(subset=["_crown_area_bin", "_dryness_bin"])
    values = np.full((bins, bins), np.nan)
    support = np.zeros((bins, bins), dtype=int)
    for (dryness, crown_area), group in work.groupby(
        ["_dryness_bin", "_crown_area_bin"], observed=True
    ):
        row, column = int(dryness), int(crown_area)
        support[row, column] = int(group["synthetic_pass_id"].nunique())
        values[row, column] = float(group["synthetic_cooling_contrast_k"].mean())
    mask = (support < 2) | ~np.isfinite(values)
    return np.ma.masked_where(mask, values), support


def _stratified_surfaces(
    pass_level: pd.DataFrame, *, bins: int = 4
) -> dict[str, tuple[np.ma.MaskedArray, np.ndarray]]:
    """Return one joint crown-area-by-moisture-deficit surface per stratum.

    A cell remains visible only when at least two distinct synthetic passes
    support it.  Keeping the four strata separate prevents a pooled surface
    from concealing changes over synthetic local solar time.
    """

    return {
        stratum: _surface(
            pass_level.loc[pass_level["time_stratum"].eq(stratum)], bins=bins
        )
        for stratum in DAY_STRATA
    }


def _figure_3(matched: pd.DataFrame, path: Path) -> Path:
    pass_level = _pass_means(matched)
    stratified = _stratified_surfaces(pass_level)
    fig, axes = plt.subplots(2, 2, figsize=(11.4, 8.0), sharex=True, sharey=True)
    cmap = plt.cm.coolwarm.with_extremes(bad="#d9d9d9")
    finite = np.concatenate(
        [surface.compressed() for surface, _ in stratified.values()]
    )
    centre = float(np.median(finite)) if len(finite) else 0.0
    spread = max(float(np.max(np.abs(finite - centre))) if len(finite) else 1.0, 0.2)
    norm = TwoSlopeNorm(
        vmin=centre - spread, vcenter=centre, vmax=centre + spread
    )
    image = None
    panel_labels = ("A", "B", "C", "D")
    for axis, panel_label, (stratum, (surface, support)) in zip(
        axes.flat, panel_labels, stratified.items()
    ):
        image = axis.imshow(
            surface,
            origin="lower",
            extent=(0, 1, 0, 1),
            aspect="auto",
            cmap=cmap,
            norm=norm,
        )
        axis.set_title(
            f"{panel_label}  Synthetic time stratum {stratum}"
        )
        axis.set_xlabel("synthetic crown-area fraction")
        axis.set_ylabel("synthetic moisture-deficit percentile")
        axis.text(
            0.02,
            0.97,
            f"supported cells: {int((support >= 2).sum())}\n"
            "grey = unsupported (<2 passes)",
            transform=axis.transAxes,
            ha="left",
            va="top",
            fontsize=7.4,
            bbox={"facecolor": "white", "alpha": 0.84, "edgecolor": "none"},
        )
    if image is not None:
        fig.colorbar(
            image,
            ax=axes.ravel().tolist(),
            label="synthetic cooling contrast (K)",
            fraction=0.025,
            pad=0.025,
        )
    fig.suptitle(
        "F14.3 / Paper Figure 3 — synthetic crown-area × moisture-deficit response by time stratum"
    )
    return _stamp_and_save(fig, path)


def _radiatively_standardize(matched: pd.DataFrame) -> pd.DataFrame:
    """Derive a transparent synthetic same-albedo cooling contrast.

    The generator has no paired-reference albedo field.  Therefore this
    illustrative-only calculation derives a reference-albedo proxy from the
    paired synthetic reference-canopy fraction using the same deterministic
    canopy/albedo relationship as the synthetic generator.  The albedo
    difference is explicitly reference minus tree.  Its modeled short-wave
    warming penalty is added back to the total contrast to represent a
    same-albedo (radiatively standardized) synthetic contrast.
    """

    work = matched.copy()
    work["_synthetic_reference_albedo_proxy"] = np.clip(
        0.27 - 0.10 * work["synthetic_reference_canopy_fraction"],
        0.08,
        0.36,
    )
    work["_synthetic_albedo_difference_reference_minus_tree"] = (
        work["_synthetic_reference_albedo_proxy"]
        - work["synthetic_albedo"]
    )
    work["_synthetic_radiative_penalty_k"] = (
        work["_synthetic_albedo_difference_reference_minus_tree"]
        * work["synthetic_incoming_radiation_w_m2"]
        / 100.0
    )
    work["_synthetic_radiatively_standardized_contrast_k"] = (
        work["synthetic_cooling_contrast_k"]
        + work["_synthetic_radiative_penalty_k"]
    )
    return work


def _figure_4(matched: pd.DataFrame, path: Path) -> Path:
    work = _radiatively_standardize(matched)

    fig, axes = plt.subplots(1, 2, figsize=(12.6, 4.8))
    sample = work.iloc[::3].copy()
    colors = plt.cm.viridis(np.linspace(0.08, 0.92, len(SIM_CITIES)))
    for color, city in zip(colors, SIM_CITIES):
        city_sample = sample.loc[sample["city"].eq(city)]
        axes[0].scatter(
            city_sample["synthetic_cooling_contrast_k"],
            city_sample["_synthetic_radiatively_standardized_contrast_k"],
            s=14,
            alpha=0.45,
            color=color,
            label=city,
        )
    comparison_limits = (
        float(
            min(
                sample["synthetic_cooling_contrast_k"].min(),
                sample["_synthetic_radiatively_standardized_contrast_k"].min(),
            )
        ),
        float(
            max(
                sample["synthetic_cooling_contrast_k"].max(),
                sample["_synthetic_radiatively_standardized_contrast_k"].max(),
            )
        ),
    )
    axes[0].plot(
        comparison_limits,
        comparison_limits,
        color="black",
        linestyle="--",
        linewidth=1.1,
        label="1:1",
    )
    axes[0].set(
        title="A  Total versus radiatively standardized",
        xlabel="total synthetic cooling contrast (K)",
        ylabel="radiatively standardized synthetic contrast (K)",
    )
    axes[0].legend(frameon=False, fontsize=7, ncol=2)

    modifier = "_synthetic_albedo_difference_reference_minus_tree"
    shift = "_synthetic_radiative_penalty_k"
    scatter = axes[1].scatter(
        sample[modifier],
        sample[shift],
        c=sample["synthetic_incoming_radiation_w_m2"],
        s=15,
        alpha=0.55,
        cmap="plasma",
    )
    coefficients = np.polyfit(sample[modifier], sample[shift], 1)
    xline = np.linspace(sample[modifier].min(), sample[modifier].max(), 80)
    axes[1].plot(
        xline, np.polyval(coefficients, xline), color="black", linewidth=1.5
    )
    axes[1].axhline(0, color="#666666", linestyle="--", linewidth=0.9)
    axes[1].set(
        title="B  Synthetic albedo-difference effect modification",
        xlabel="synthetic albedo difference (reference − tree)",
        ylabel="standardization shift (standardized − total, K)",
    )
    fig.colorbar(
        scatter,
        ax=axes[1],
        label="synthetic incoming radiation (W m⁻²)",
    )
    fig.suptitle(
        "F14.4 / Paper Figure 4 — synthetic radiative standardization and albedo modifier"
    )
    return _stamp_and_save(fig, path)


def _figure_5(matched: pd.DataFrame, path: Path) -> Path:
    et_columns = [f"synthetic_et_member_{index}" for index in range(1, 5)]
    et_mean = matched[et_columns].mean(axis=1)
    et_ratio = et_mean / matched["synthetic_et_potential"]
    sample = matched.iloc[::2]
    fig, axes = plt.subplots(2, 2, figsize=(11.2, 8.0))

    axes[0, 0].scatter(matched["synthetic_canopy_fraction"], et_mean, s=9, alpha=0.25, color="#1b9e77")
    coefficients = np.polyfit(matched["synthetic_canopy_fraction"], et_mean, 2)
    xline = np.linspace(0.05, 0.96, 100)
    axes[0, 0].plot(xline, np.polyval(coefficients, xline), color="black")
    axes[0, 0].set(title="A  Synthetic ET support", xlabel="synthetic canopy fraction", ylabel="synthetic mean ET")

    axes[0, 1].scatter(et_ratio, matched["synthetic_esi"], s=9, alpha=0.28, color="#7570b3")
    axes[0, 1].plot((0, 1.1), (0, 1.1), linestyle="--", color="black")
    axes[0, 1].set(title="B  Synthetic evaporative stress", xlabel="synthetic ET/PET", ylabel="synthetic ESI")

    axes[1, 0].scatter(sample["synthetic_canopy_fraction"], sample["synthetic_ndvi_native"], s=11, alpha=0.35, color="#66a61e")
    coefficients = np.polyfit(sample["synthetic_canopy_fraction"], sample["synthetic_ndvi_native"], 1)
    axes[1, 0].plot(xline, np.polyval(coefficients, xline), color="black")
    axes[1, 0].set(title="C  Synthetic optical-canopy support", xlabel="synthetic canopy fraction", ylabel="synthetic vegetation index")

    axes[1, 1].scatter(sample["synthetic_reference_lst_k"], sample["synthetic_tree_lst_k"], s=11, alpha=0.32, c=sample["synthetic_canopy_fraction"], cmap="YlGn")
    limits = (
        float(min(sample["synthetic_tree_lst_k"].min(), sample["synthetic_reference_lst_k"].min())),
        float(max(sample["synthetic_tree_lst_k"].max(), sample["synthetic_reference_lst_k"].max())),
    )
    axes[1, 1].plot(limits, limits, linestyle="--", color="black")
    axes[1, 1].set(title="D  Synthetic thermal contrast", xlabel="synthetic reference LST (K)", ylabel="synthetic tree LST (K)")
    fig.suptitle("F14.5 / Paper Figure 5 — synthetic supporting evidence")
    return _stamp_and_save(fig, path)


def _leave_one_city_out(pass_level: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for city in SIM_CITIES:
        subset = pass_level.loc[~pass_level["city"].eq(city)]
        mean, error = _mean_interval(subset["synthetic_cooling_contrast_k"])
        rows.append({"left_out": city, "mean": mean, "error": error})
    return pd.DataFrame(rows)


def _figure_6(matched: pd.DataFrame, path: Path, *, seed: int) -> Path:
    pass_level = _pass_means(matched)
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.0))

    placebo = matched[["city", "synthetic_reference_lst_k"]].copy()
    placebo["_placebo"] = placebo.groupby("city")["synthetic_reference_lst_k"].transform(lambda values: values - np.roll(values.to_numpy(), 1))
    placebo_summary = placebo.groupby("city")["_placebo"].agg(["mean", "sem"]).reindex(SIM_CITIES)
    axes[0, 0].errorbar(np.arange(5), placebo_summary["mean"], yerr=1.96 * placebo_summary["sem"], fmt="o", capsize=3, color="#762a83")
    axes[0, 0].axhline(0, color="black", linestyle="--")
    axes[0, 0].set_xticks(np.arange(5), SIM_CITIES, rotation=25)
    axes[0, 0].set(title="A  Synthetic placebo", ylabel="synthetic placebo contrast (K)")

    daynight_rows = []
    for label, subset in (
        ("day", pass_level[pass_level["time_stratum"].isin(DAY_STRATA)]),
        ("night", pass_level[pass_level["time_stratum"].eq("night")]),
    ):
        mean, error = _mean_interval(subset["synthetic_cooling_contrast_k"])
        daynight_rows.append((label, mean, error))
    axes[0, 1].errorbar([0, 1], [row[1] for row in daynight_rows], yerr=[row[2] for row in daynight_rows], fmt="o", capsize=4, color="#d95f0e")
    axes[0, 1].set_xticks((0, 1), ("synthetic day", "synthetic night"))
    axes[0, 1].set(title="B  Synthetic day/night comparison", ylabel="synthetic cooling contrast (K)")

    loo = _leave_one_city_out(pass_level)
    axes[1, 0].errorbar(loo["mean"], np.arange(len(loo)), xerr=loo["error"], fmt="o", capsize=3, color="#1b7837")
    full_mean = float(pass_level["synthetic_cooling_contrast_k"].mean())
    axes[1, 0].axvline(full_mean, color="black", linestyle="--", label="synthetic full panel")
    axes[1, 0].set_yticks(np.arange(len(loo)), [f"without {city}" for city in loo["left_out"]])
    axes[1, 0].set(title="C  Synthetic leave-one-city-out", xlabel="synthetic pooled contrast (K)")
    axes[1, 0].legend(frameon=False, fontsize=8)

    sampling = _mean_interval(pass_level["synthetic_cooling_contrast_k"])[1]
    classification = float(
        abs(
            matched.loc[matched["synthetic_true_tree_class"], "synthetic_cooling_contrast_k"].mean()
            - matched.loc[matched["synthetic_predicted_tree_class"], "synthetic_cooling_contrast_k"].mean()
        )
    )
    registration = float(
        matched.groupby(pd.qcut(matched["synthetic_canopy_fraction"], 4, duplicates="drop"), observed=True)["synthetic_cooling_contrast_k"].mean().diff().abs().median()
    )
    model_form = float(
        abs(
            matched["synthetic_cooling_contrast_k"].mean()
            - matched["synthetic_cooling_contrast_k"].median()
        )
    )
    uncertainty = pd.Series(
        (sampling, classification, registration, model_form),
        index=("pass sampling", "classification", "registration", "model form"),
    )
    axes[1, 1].barh(uncertainty.index, uncertainty.values, color=("#80cdc1", "#dfc27d", "#bf812d", "#35978f"))
    axes[1, 1].axvline(0.75, color="#b2182b", linestyle="--", label="synthetic detection limit")
    axes[1, 1].set(title="D  Synthetic uncertainty budget", xlabel="synthetic uncertainty contribution (K)")
    axes[1, 1].legend(frameon=False, fontsize=8)
    fig.suptitle("F14.6 / Paper Figure 6 — synthetic robustness summary")
    return _stamp_and_save(fig, path)


def write_step14_figures(
    output_root: str | Path,
    figure_root: str | Path,
    seed: int = DEFAULT_SEED,
) -> dict[str, Path]:
    """Write exactly the six quarantined illustrative paper figures.

    ``output_root`` is read only.  If the two exact shared synthetic CSVs are
    already present there they are consumed; otherwise the same deterministic
    shared generator used by Steps 4--13 is called.  No other input path is
    searched or opened.
    """

    output = Path(output_root)
    figures = Path(figure_root)
    pass_df, matched = _load_existing_tables(output, seed=int(seed))
    destinations = {
        "F14.1": figures / "ILLUSTRATIVE_F14.1_PAPER_FIGURE_1_study_design.png",
        "F14.2": figures / "ILLUSTRATIVE_F14.2_PAPER_FIGURE_2_primary_result.png",
        "F14.3": figures / "ILLUSTRATIVE_F14.3_PAPER_FIGURE_3_hydroclimatic_surface.png",
        "F14.4": figures / "ILLUSTRATIVE_F14.4_PAPER_FIGURE_4_radiative_pathway.png",
        "F14.5": figures / "ILLUSTRATIVE_F14.5_PAPER_FIGURE_5_supporting_evidence.png",
        "F14.6": figures / "ILLUSTRATIVE_F14.6_PAPER_FIGURE_6_robustness.png",
    }
    artifacts = {
        "F14.1": _figure_1(pass_df, matched, destinations["F14.1"]),
        "F14.2": _figure_2(matched, destinations["F14.2"]),
        "F14.3": _figure_3(matched, destinations["F14.3"]),
        "F14.4": _figure_4(matched, destinations["F14.4"]),
        "F14.5": _figure_5(matched, destinations["F14.5"]),
        "F14.6": _figure_6(matched, destinations["F14.6"], seed=int(seed)),
    }
    if tuple(artifacts) != EXPECTED_IDS:
        raise RuntimeError("illustrative Step-14 artifact registry is not exact")
    missing = [str(path) for path in artifacts.values() if not path.is_file() or path.stat().st_size <= 0]
    if missing:
        raise RuntimeError(f"illustrative Step-14 produced missing or empty figures: {missing}")
    return artifacts


__all__ = [
    "EXPECTED_IDS",
    "WATERMARK",
    "write_step14_figures",
]
