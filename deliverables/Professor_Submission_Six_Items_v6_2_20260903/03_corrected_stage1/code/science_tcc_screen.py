#!/usr/bin/env python3
"""Pure helpers for the v6.2 official-Science-TCC canopy-span screen."""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np


def stable_median_fraction(
    annual_percent: np.ndarray,
    *,
    stability_tolerance_fraction: float = 0.15,
) -> tuple[np.ndarray, np.ndarray]:
    """Return stable-cell 2019-2025 median canopy fraction and stability mask."""

    values = np.asarray(annual_percent, dtype=np.float32)
    if values.ndim != 3 or values.shape[0] != 7:
        raise ValueError("Science TCC stack must contain exactly seven annual layers")
    valid = np.isfinite(values) & (values >= 0.0) & (values <= 100.0)
    all_valid = valid.all(axis=0)
    safe = np.where(valid, values, 0.0)
    annual_range_fraction = (np.max(safe, axis=0) - np.min(safe, axis=0)) / 100.0
    stable = all_valid & (annual_range_fraction <= stability_tolerance_fraction + 1e-12)
    median = np.median(safe, axis=0) / 100.0
    median[~stable] = np.nan
    return median.astype(np.float32), stable


def merge_nonthermal_scene_masks(
    scenes: Sequence[Mapping[str, np.ndarray]],
) -> np.ndarray:
    """Merge native QA/cloud/water/height arrays without reading LST.

    A cloud or water flag in any present scene wins. At least one scene must have
    mandatory QA class 00/01, clear land and finite height.
    """

    if not scenes:
        raise ValueError("At least one scene is required")
    shape = np.ma.asarray(scenes[0]["QC"]).shape
    any_bad = np.zeros(shape, dtype=bool)
    any_valid = np.zeros(shape, dtype=bool)
    for scene in scenes:
        arrays = {name: np.ma.asarray(scene[name]) for name in ("QC", "cloud", "water", "height")}
        if any(array.shape != shape for array in arrays.values()):
            raise ValueError("Nonthermal native layers do not share one grid")
        present = np.ones(shape, dtype=bool)
        for array in arrays.values():
            present &= ~np.ma.getmaskarray(array)
        qc = np.asarray(arrays["QC"].filled(65535), dtype=np.uint16)
        cloud = np.asarray(arrays["cloud"].filled(255))
        water = np.asarray(arrays["water"].filled(255))
        height = np.asarray(arrays["height"].filled(np.nan), dtype=float)
        present &= np.isfinite(height)
        any_bad |= present & ((cloud != 0) | (water != 0))
        mandatory = qc & np.uint16(0b11)
        any_valid |= present & (mandatory <= 1) & (cloud == 0) & (water == 0)
    return any_valid & ~any_bad


def canopy_span(canopy_fraction: np.ndarray) -> tuple[float, float, float]:
    values = np.asarray(canopy_fraction, dtype=float)
    values = values[np.isfinite(values)]
    if not len(values):
        return float("nan"), float("nan"), float("nan")
    p10, p90 = np.quantile(values, [0.10, 0.90])
    return float(p10), float(p90), float(p90 - p10)


def cooling_effect_from_slope(
    slope_k_per_unit_canopy_fraction: float,
    *,
    canopy_loss_fraction: float = 0.10,
) -> float:
    """Convert a canopy-LST slope to warming after a canopy-fraction loss."""

    return -float(canopy_loss_fraction) * float(slope_k_per_unit_canopy_fraction)
