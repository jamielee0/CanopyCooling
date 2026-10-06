#!/usr/bin/env python3
"""Outcome-blind HLS Fmask screening for the v6.2 D1c reassessment.

This module is limited to HLS source metadata and the Fmask quality band.  It
does not read reflectance, optical indices, ECOSTRESS LST, or coefficients.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from pyproj import Transformer
import rasterio
from rasterio.errors import WindowError
from rasterio.features import geometry_mask, geometry_window
from rasterio.warp import transform_geom
from shapely.geometry import box, mapping, shape

from urban_cooling_v2.connectivity_audit import (
    BLOCK_SIZE_M,
    CITY_LABEL,
    BlockGrid,
)
from urban_cooling_v2.lead_lag_feasibility import (
    MAX_ABSOLUTE_LAG_DAYS,
    MAX_LAG_IMBALANCE_DAYS,
    MIN_ABSOLUTE_LAG_DAYS,
    REQUIRED_CITIES,
    REQUIRED_SENSORS,
    REQUIRED_WINDOWS,
    REQUIRED_YEARS,
    _utc,
)
from urban_cooling_v2.step02_raster import (
    canonical_mgrs_core_bounds,
    partition_domain_for_mgrs_tile,
)


FMASK_REQUIRED_ZERO_BITS = (1, 2, 3, 4, 5)
MAX_AEROSOL_LEVEL = 2
MIN_CLEAR_HLS_CELLS_PER_BLOCK = 60
MIN_SHARED_USABLE_BLOCKS = 30


def clear_fmask_cells(
    values: np.ndarray,
    *,
    valid_source: np.ndarray | None = None,
    required_zero_bits: Sequence[int] = FMASK_REQUIRED_ZERO_BITS,
    maximum_aerosol_level: int = MAX_AEROSOL_LEVEL,
) -> np.ndarray:
    """Return cells passing the frozen HLS V2 bit and aerosol rule."""

    data = np.asarray(values)
    if not np.issubdtype(data.dtype, np.integer):
        raise ValueError("HLS Fmask values must have an integer dtype")
    if valid_source is None:
        valid = np.ones(data.shape, dtype=bool)
    else:
        valid = np.asarray(valid_source, dtype=bool)
        if valid.shape != data.shape:
            raise ValueError("valid_source must match the Fmask array shape")
    bit_mask = sum(1 << int(bit) for bit in required_zero_bits)
    aerosol = (data.astype(np.uint16) >> 6) & 0b11
    return valid & ((data.astype(np.uint16) & bit_mask) == 0) & (
        aerosol <= int(maximum_aerosol_level)
    )


def _domain_window(
    dataset: rasterio.io.DatasetReader,
    domain_geometry_wgs84: Mapping[str, Any],
) -> tuple[Any, np.ndarray] | None:
    projected = transform_geom(
        "EPSG:4326", dataset.crs, domain_geometry_wgs84, precision=-1
    )
    clipped = shape(projected).intersection(box(*canonical_mgrs_core_bounds(dataset.bounds)))
    if clipped.is_empty:
        return None
    try:
        window = geometry_window(dataset, [mapping(clipped)])
    except WindowError:
        return None
    domain = geometry_mask(
        [mapping(clipped)],
        out_shape=(int(window.height), int(window.width)),
        transform=dataset.window_transform(window),
        invert=True,
        all_touched=False,
    )
    return (window, domain) if domain.any() else None


def _pixel_block_keys(
    mask: np.ndarray,
    transform: Any,
    source_crs: Any,
    grid: BlockGrid,
) -> np.ndarray:
    rr, cc = np.nonzero(mask)
    if rr.size == 0:
        return np.empty(0, dtype=np.int64)
    xs = transform.c + (cc + 0.5) * transform.a + (rr + 0.5) * transform.b
    ys = transform.f + (cc + 0.5) * transform.d + (rr + 0.5) * transform.e
    source = rasterio.crs.CRS.from_user_input(source_crs)
    target = rasterio.crs.CRS.from_epsg(grid.epsg)
    if source != target:
        transformer = Transformer.from_crs(source, target, always_xy=True)
        xs, ys = transformer.transform(xs, ys)
        xs = np.asarray(xs)
        ys = np.asarray(ys)
    cols = np.floor((xs - grid.origin_x) / BLOCK_SIZE_M).astype(np.int64)
    rows = np.floor((ys - grid.origin_y) / BLOCK_SIZE_M).astype(np.int64)
    inside = (cols >= 0) & (cols < grid.ncols) & (rows >= 0) & (rows < grid.nrows)
    return rows[inside] * grid.ncols + cols[inside]


def fmask_block_counts(
    path: str | Path,
    *,
    mgrs_tile: str,
    domain_geometry_wgs84: Mapping[str, Any],
    grid: BlockGrid,
) -> tuple[dict[int, int], dict[str, Any]]:
    """Count clear HLS cells per retained study block for one granule."""

    tile_domain = partition_domain_for_mgrs_tile(domain_geometry_wgs84, mgrs_tile)
    valid_block_keys = set(grid.blocks["block_key"].astype(int))
    with rasterio.open(Path(path)) as dataset:
        if dataset.count != 1 or dataset.dtypes[0] != "uint8":
            raise ValueError(f"Unexpected HLS Fmask raster type: {path}")
        if abs(float(dataset.res[0])) != 30.0 or abs(float(dataset.res[1])) != 30.0:
            raise ValueError(f"Unexpected HLS Fmask resolution: {path}")
        clipped = _domain_window(dataset, tile_domain)
        if clipped is None:
            return {}, {
                "domain_cells": 0,
                "clear_cells": 0,
                "clear_fraction": None,
                "blocks_with_any_domain_cell": 0,
                "usable_blocks": 0,
                "source_crs": str(dataset.crs),
            }
        window, domain = clipped
        layer = dataset.read(1, window=window, masked=True)
        values = np.asarray(layer.filled(255), dtype=np.uint8)
        valid_source = domain & ~np.ma.getmaskarray(layer)
        clear = domain & clear_fmask_cells(values, valid_source=valid_source)
        transform = dataset.window_transform(window)
        domain_keys = _pixel_block_keys(domain, transform, dataset.crs, grid)
        clear_keys = _pixel_block_keys(clear, transform, dataset.crs, grid)

    domain_counts = Counter(int(key) for key in domain_keys if int(key) in valid_block_keys)
    clear_counts = Counter(int(key) for key in clear_keys if int(key) in valid_block_keys)
    counts = dict(sorted(clear_counts.items()))
    usable = sum(count >= MIN_CLEAR_HLS_CELLS_PER_BLOCK for count in counts.values())
    domain_total = int(sum(domain_counts.values()))
    clear_total = int(sum(clear_counts.values()))
    return counts, {
        "domain_cells": domain_total,
        "clear_cells": clear_total,
        "clear_fraction": clear_total / domain_total if domain_total else None,
        "blocks_with_any_domain_cell": len(domain_counts),
        "usable_blocks": int(usable),
        "source_crs": str(dataset.crs),
    }


def choose_quality_screened_pair(
    pass_time: Any,
    acquisitions: pd.DataFrame,
    usable_blocks: Mapping[str, Iterable[int]],
    *,
    sensor: str,
    minimum_shared_usable_blocks: int = MIN_SHARED_USABLE_BLOCKS,
    minimum_absolute_lag_days: float = MIN_ABSOLUTE_LAG_DAYS,
    maximum_absolute_lag_days: float = MAX_ABSOLUTE_LAG_DAYS,
    maximum_lag_imbalance_days: float = MAX_LAG_IMBALANCE_DAYS,
) -> dict[str, Any] | None:
    """Choose a timing-valid pair that also shares enough QA-usable blocks."""

    return evaluate_quality_screened_pair(
        pass_time,
        acquisitions,
        usable_blocks,
        sensor=sensor,
        minimum_shared_usable_blocks=minimum_shared_usable_blocks,
        minimum_absolute_lag_days=minimum_absolute_lag_days,
        maximum_absolute_lag_days=maximum_absolute_lag_days,
        maximum_lag_imbalance_days=maximum_lag_imbalance_days,
    )["pair"]


def evaluate_quality_screened_pair(
    pass_time: Any,
    acquisitions: pd.DataFrame,
    usable_blocks: Mapping[str, Iterable[int]],
    *,
    sensor: str,
    minimum_shared_usable_blocks: int = MIN_SHARED_USABLE_BLOCKS,
    minimum_absolute_lag_days: float = MIN_ABSOLUTE_LAG_DAYS,
    maximum_absolute_lag_days: float = MAX_ABSOLUTE_LAG_DAYS,
    maximum_lag_imbalance_days: float = MAX_LAG_IMBALANCE_DAYS,
) -> dict[str, Any]:
    """Return a selected pair plus transparent timing and QA diagnostics."""

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
    ]
    post = work.loc[
        work["signed_lag_days"].between(
            float(minimum_absolute_lag_days), float(maximum_absolute_lag_days)
        )
    ]
    candidates: list[tuple[float, float, str, str, Any, Any, int]] = []
    timing_valid_candidates = 0
    maximum_shared = 0
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
            timing_valid_candidates += 1
            shared = len(
                set(int(key) for key in usable_blocks.get(left_id, ())).intersection(
                    int(key) for key in usable_blocks.get(right_id, ())
                )
            )
            maximum_shared = max(maximum_shared, shared)
            if shared < int(minimum_shared_usable_blocks):
                continue
            candidates.append(
                (imbalance, pre_days + post_days, left_id, right_id, left, right, shared)
            )
    if not candidates:
        return {
            "pair": None,
            "quality_pair_available": False,
            "timing_valid_pair_candidates": timing_valid_candidates,
            "maximum_shared_usable_blocks_among_timing_pairs": maximum_shared,
            "failure_reason": (
                "NO_TIMING_VALID_PAIR_IN_DOWNLOADED_PLAN"
                if timing_valid_candidates == 0
                else "TIMING_PAIR_FOUND_BUT_SHARED_BLOCK_FLOOR_NOT_MET"
            ),
        }
    _, _, _, _, left, right, shared = min(candidates, key=lambda item: item[:4])
    pre_days = abs(float(left.signed_lag_days))
    post_days = abs(float(right.signed_lag_days))
    pair = {
        "pre_acquisition_id": str(left.optical_acquisition_id),
        "post_acquisition_id": str(right.optical_acquisition_id),
        "pre_lag_days": pre_days,
        "post_lag_days": post_days,
        "lag_imbalance_days": abs(pre_days - post_days),
        "shared_usable_blocks": int(shared),
    }
    return {
        "pair": pair,
        "quality_pair_available": True,
        "timing_valid_pair_candidates": timing_valid_candidates,
        "maximum_shared_usable_blocks_among_timing_pairs": maximum_shared,
        "failure_reason": None,
    }


def required_quality_grid_rows(
    pair_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Summarize the complete 56-row D1c grid after Fmask screening."""

    rows: list[dict[str, Any]] = []
    for city in REQUIRED_CITIES:
        for year in REQUIRED_YEARS:
            for window in REQUIRED_WINDOWS:
                for sensor in REQUIRED_SENSORS:
                    selected = [
                        row
                        for row in pair_rows
                        if row["city"] == city
                        and int(row["year"]) == year
                        and row["season_window"] == window
                        and row["sensor"] == sensor
                    ]
                    paired = [row for row in selected if row["quality_pair_available"]]
                    identifiers: list[str] = []
                    for row in paired:
                        identifiers.extend(
                            [str(row["pre_acquisition_id"]), str(row["post_acquisition_id"])]
                        )
                    reuse = Counter(identifiers)
                    candidate_count = len(selected)
                    pair_count = len(paired)
                    shared_counts = [int(row["shared_usable_blocks"]) for row in paired]
                    status = (
                        "QUALITY_SCREENED_PAIR_AVAILABLE"
                        if pair_count
                        else ("NO_QUALITY_SCREENED_PAIR" if candidate_count else "NO_CANDIDATE_PASSES")
                    )
                    rows.append(
                        {
                            "record_role": "required_hls_stratum",
                            "city": CITY_LABEL[city],
                            "year": year,
                            "season_window": window,
                            "sensor": sensor,
                            "candidate_passes": candidate_count,
                            "passes_with_feasible_matched_pre_post": pair_count,
                            "feasible_share": pair_count / candidate_count if candidate_count else None,
                            "unique_optical_acquisition_identifiers": len(reuse),
                            "max_thermal_passes_sharing_one_acquisition": max(reuse.values(), default=0),
                            "minimum_shared_usable_blocks_in_selected_pairs": min(shared_counts, default=None),
                            "median_shared_usable_blocks_in_selected_pairs": (
                                float(np.median(shared_counts)) if shared_counts else None
                            ),
                            "timing_status": status,
                            "interpretation_note": (
                                "Exact HLS V2 source IDs/times; Fmask-screened common-block support."
                                if pair_count
                                else (
                                    "Candidate pass exists, but no downloaded HLS pair meets both frozen timing and common-block QA rules."
                                    if candidate_count
                                    else "No candidate thermal pass in this stratum."
                                )
                            ),
                        }
                    )
    return rows


def acquisition_reuse_share(pair_rows: Iterable[Mapping[str, Any]]) -> float | None:
    """Return maximum selected-acquisition reuse divided by candidate passes."""

    rows = list(pair_rows)
    if not rows:
        return None
    identifiers: list[str] = []
    for row in rows:
        if row.get("quality_pair_available"):
            identifiers.extend(
                [str(row["pre_acquisition_id"]), str(row["post_acquisition_id"])]
            )
    return max(Counter(identifiers).values(), default=0) / len(rows)
