#!/usr/bin/env python3
"""Pure, outcome-blind logic for the v6.2 D1c lead-lag feasibility check.

The inherited centered optical product is allowed to contribute counts only.
Its pixel values are neither needed nor permitted here.  A centered count of two
or more is only an upper-bound proxy: without source dates and acquisition IDs it
cannot establish that one observation is before and one is after a thermal pass.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REQUIRED_CITIES = ("phoenix", "los_angeles")
REQUIRED_YEARS = tuple(range(2019, 2026))
REQUIRED_WINDOWS = ("provisional_primary", "sensitivity")
REQUIRED_SENSORS = ("HLSL30.002", "HLSS30.002")
LEGACY_SENSOR = "COPERNICUS/S2_SR_HARMONIZED"
CITY_LABEL = {"phoenix": "Phoenix", "los_angeles": "Los Angeles"}
MIN_ABSOLUTE_LAG_DAYS = 1.0
MAX_ABSOLUTE_LAG_DAYS = 15.0
MAX_LAG_IMBALANCE_DAYS = 3.0
MIN_CONFIRMATORY_SHARE = 0.70
MAX_ACQUISITION_REUSE_SHARE = 0.25


def _utc(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def choose_matched_pair(
    pass_time: Any,
    acquisitions: pd.DataFrame,
    *,
    sensor: str,
    minimum_absolute_lag_days: float = MIN_ABSOLUTE_LAG_DAYS,
    maximum_absolute_lag_days: float = MAX_ABSOLUTE_LAG_DAYS,
    maximum_lag_imbalance_days: float = MAX_LAG_IMBALANCE_DAYS,
) -> dict[str, Any] | None:
    """Choose one distinct, sensor-specific pre/post pair under the frozen D009 rule."""

    required = {"optical_acquisition_id", "sensor", "source_time"}
    missing = sorted(required.difference(acquisitions.columns))
    if missing:
        raise ValueError(f"Acquisition ledger lacks columns: {missing}")
    thermal = _utc(pass_time)
    work = acquisitions.loc[acquisitions["sensor"].astype(str).eq(str(sensor))].copy()
    work["source_time"] = work["source_time"].map(_utc)
    work["signed_lag_days"] = (
        work["source_time"] - thermal
    ).dt.total_seconds() / 86400.0
    pre = work.loc[
        work["signed_lag_days"].between(
            -float(maximum_absolute_lag_days), -float(minimum_absolute_lag_days)
        )
    ].copy()
    post = work.loc[
        work["signed_lag_days"].between(
            float(minimum_absolute_lag_days), float(maximum_absolute_lag_days)
        )
    ].copy()
    candidates: list[tuple[float, float, str, str, Any, Any]] = []
    for left in pre.itertuples(index=False):
        for right in post.itertuples(index=False):
            left_id = str(left.optical_acquisition_id)
            right_id = str(right.optical_acquisition_id)
            if left_id == right_id:
                continue
            pre_days = abs(float(left.signed_lag_days))
            post_days = abs(float(right.signed_lag_days))
            imbalance = abs(pre_days - post_days)
            if imbalance > float(maximum_lag_imbalance_days):
                continue
            candidates.append(
                (
                    imbalance,
                    pre_days + post_days,
                    left_id,
                    right_id,
                    left,
                    right,
                )
            )
    if not candidates:
        return None
    _, _, _, _, left, right = min(candidates, key=lambda item: item[:4])
    return {
        "pre_acquisition_id": str(left.optical_acquisition_id),
        "post_acquisition_id": str(right.optical_acquisition_id),
        "pre_lag_days": abs(float(left.signed_lag_days)),
        "post_lag_days": abs(float(right.signed_lag_days)),
        "lag_imbalance_days": abs(
            abs(float(left.signed_lag_days)) - abs(float(right.signed_lag_days))
        ),
    }


def centered_count_proxy(count_array: np.ndarray) -> dict[str, Any]:
    """Summarize one centered count grid without inspecting any optical index value."""

    values = np.asarray(count_array)
    if values.size == 0:
        raise ValueError("Centered count grid is empty")
    if np.any(~np.isfinite(values)) or np.any(values < 0):
        raise ValueError("Centered count grid must be finite and nonnegative")
    flat = values.reshape(-1)
    return {
        "minimum_valid_scene_count": int(np.min(flat)),
        "median_valid_scene_count": float(np.median(flat)),
        "maximum_valid_scene_count": int(np.max(flat)),
        "fraction_cells_count_ge_1": float(np.mean(flat >= 1)),
        "fraction_cells_count_ge_2": float(np.mean(flat >= 2)),
        "centered_count_ge2_upper_bound": bool(np.median(flat) >= 2),
    }


def required_grid_rows(candidate_counts: Mapping[tuple[str, int, str], int]) -> list[dict[str, Any]]:
    """Create the complete 2-city x 7-year x 2-window x 2-sensor D1c grid."""

    rows: list[dict[str, Any]] = []
    for city in REQUIRED_CITIES:
        for year in REQUIRED_YEARS:
            for window in REQUIRED_WINDOWS:
                candidate_passes = int(candidate_counts.get((city, year, window), 0))
                for sensor in REQUIRED_SENSORS:
                    rows.append(
                        {
                            "record_role": "required_hls_stratum",
                            "city": CITY_LABEL[city],
                            "year": year,
                            "season_window": window,
                            "sensor": sensor,
                            "candidate_passes": candidate_passes,
                            "passes_with_feasible_matched_pre_post": None,
                            "feasible_share": None,
                            "unique_optical_acquisition_identifiers": 0,
                            "max_thermal_passes_sharing_one_acquisition": None,
                            "centered_count_ge2_passes_upper_bound": None,
                            "inherited_product_axis_records": 0,
                            "timing_status": "NOT_ESTIMABLE_MISSING_HLS_ACQUISITION_LEDGER",
                            "interpretation_note": (
                                "Required HLS row; inherited centered object is Sentinel-2 SR, "
                                "not HLS V2, and stores no source dates or acquisition IDs."
                            ),
                        }
                    )
    return rows


def validate_required_grid(rows: Sequence[Mapping[str, Any]]) -> None:
    required = [row for row in rows if row.get("record_role") == "required_hls_stratum"]
    if len(required) != 56:
        raise ValueError(f"D1c requires 56 HLS rows; found {len(required)}")
    keys = {
        (row["city"], int(row["year"]), row["season_window"], row["sensor"])
        for row in required
    }
    expected = {
        (CITY_LABEL[city], year, window, sensor)
        for city in REQUIRED_CITIES
        for year in REQUIRED_YEARS
        for window in REQUIRED_WINDOWS
        for sensor in REQUIRED_SENSORS
    }
    if keys != expected:
        missing = sorted(expected.difference(keys))
        extra = sorted(keys.difference(expected))
        raise ValueError(f"D1c required-grid mismatch; missing={missing}, extra={extra}")


def confirmatory_ruling(
    rows: Sequence[Mapping[str, Any]],
    *,
    source_dates_available: bool,
    acquisition_identifiers_available: bool,
    minimum_confirmatory_share: float = MIN_CONFIRMATORY_SHARE,
) -> str:
    """Apply the fail-closed D009 confirmatory/exploratory ruling."""

    validate_required_grid(rows)
    if not 0.0 <= float(minimum_confirmatory_share) <= 1.0:
        raise ValueError("minimum_confirmatory_share must be between 0 and 1")
    if not source_dates_available or not acquisition_identifiers_available:
        return "DEMOTE_TO_EXPLORATORY_MISSING_SOURCE_TIMING_PROVENANCE"

    required = [row for row in rows if row.get("record_role") == "required_hls_stratum"]
    for city in (CITY_LABEL[name] for name in REQUIRED_CITIES):
        city_window_pass = False
        for window in REQUIRED_WINDOWS:
            strata = [
                row
                for row in required
                if row["city"] == city and row["season_window"] == window
            ]
            nonzero = [row for row in strata if int(row["candidate_passes"]) > 0]
            if not nonzero:
                continue
            shares_ok = all(
                row["feasible_share"] is not None
                and float(row["feasible_share"]) >= float(minimum_confirmatory_share)
                for row in nonzero
            )
            reuse_ok = all(
                row["max_thermal_passes_sharing_one_acquisition"] is not None
                and int(row["max_thermal_passes_sharing_one_acquisition"])
                <= max(1, int(np.floor(MAX_ACQUISITION_REUSE_SHARE * int(row["candidate_passes"]))))
                for row in nonzero
            )
            city_window_pass = city_window_pass or (shares_ok and reuse_ok)
        if not city_window_pass:
            return "DEMOTE_TO_EXPLORATORY_CONFIRMATORY_SUPPORT_RULE_FAILED"
    return "KEEP_CONFIRMATORY"


def acquisition_reuse(pair_rows: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
    identifiers: list[str] = []
    for row in pair_rows:
        identifiers.extend([str(row["pre_acquisition_id"]), str(row["post_acquisition_id"])])
    counts = Counter(identifiers)
    return len(counts), max(counts.values(), default=0)


def plot_timing_histogram(
    pre_lags: Sequence[float],
    post_lags: Sequence[float],
    png_path: Path,
    svg_path: Path,
    *,
    footer_note: str = (
        "Centered scene counts cannot reveal side-of-pass timing; no optical value or thermal outcome was opened."
    ),
) -> None:
    """Plot the required timing histogram, including an explicit no-data state."""

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.8), sharey=True)
    bins = np.arange(0.5, 16.5, 1.0)
    for axis, values, label, color in zip(
        axes,
        (pre_lags, post_lags),
        ("Pre-pass lag", "Post-pass lag"),
        ("#277DA1", "#E07A5F"),
    ):
        axis.hist(values, bins=bins, color=color, edgecolor="white", linewidth=0.6)
        axis.set_xlim(0.5, 15.5)
        axis.set_xticks([1, 3, 6, 9, 12, 15])
        axis.set_xlabel("Absolute lag (days)")
        axis.set_title(f"{label} (verified n={len(values)})", loc="left", fontweight="bold")
        axis.grid(axis="y", color="#D9E2E7", linewidth=0.6)
        axis.set_axisbelow(True)
        if not values:
            axis.set_ylim(0, 1)
            axis.text(
                8,
                0.54,
                "No verified source-date records\nare stored in the inherited product",
                ha="center",
                va="center",
                color="#58727D",
                fontsize=9,
                bbox={"boxstyle": "round,pad=0.45", "facecolor": "#F3F6F7", "edgecolor": "#CBD8DD"},
            )
    axes[0].set_ylabel("Matched optical observations")
    fig.suptitle(
        "D1c lead-lag timing: verified matched observations",
        x=0.07,
        y=0.99,
        ha="left",
        fontsize=14,
        fontweight="bold",
        color="#183642",
    )
    fig.text(
        0.07,
        0.015,
        footer_note,
        fontsize=8,
        color="#58727D",
    )
    fig.tight_layout(rect=[0.04, 0.07, 0.99, 0.92])
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=320, facecolor="white")
    fig.savefig(svg_path, facecolor="white")
    plt.close(fig)
