#!/usr/bin/env python3
"""Run the frozen D015 official-Science-TCC screen without opening LST."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import Resampling
import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from run_v6_2_d1d_stage1_precision import (
    PROTOCOL,
    RAW_LSTE,
    _aligned_window,
    _reproject_array,
    phoenix_grid,
    selected_orbits_from_frozen_rule,
)
from urban_cooling_v2.science_tcc_screen import (
    canopy_span,
    merge_nonthermal_scene_masks,
    stable_median_fraction,
)
from urban_cooling_v2.stage1_precision_census import discover_latest_complete_bundles


TCC_DIR = ROOT / "data/raw/v2/science_tcc_v2025_6/drive_exports"
SOURCE_MANIFEST = ROOT / "data/raw/v2/science_tcc_v2025_6/drive_output_verification.json"
PACKAGE = ROOT / "deliverables/D1d_tcc_span_screen_v6_2_20260902"


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_phoenix_stable_tcc() -> tuple[np.ndarray, Any, Any, list[Path], int]:
    files = sorted(TCC_DIR.glob("science_tcc_v2025-6_phoenix_*_native30m.tif"))
    if len(files) != 7:
        raise ValueError(f"Expected seven Phoenix annual TCC files, found {len(files)}")
    annual = []
    transform = crs = shape = None
    source_valid_cells = 0
    for path in files:
        with rasterio.open(path) as dataset:
            if dataset.count != 2 or dataset.nodata != 65535:
                raise ValueError(f"Unexpected Science TCC structure: {path.name}")
            if transform is None:
                transform, crs, shape = dataset.transform, dataset.crs, dataset.shape
            elif (dataset.transform, dataset.crs, dataset.shape) != (transform, crs, shape):
                raise ValueError("Annual Phoenix Science TCC files do not share one native grid")
            values = dataset.read(1, masked=True).astype(np.float32).filled(np.nan)
            source_valid_cells += int(np.isfinite(values).sum())
            annual.append(values)
    median, stable = stable_median_fraction(np.stack(annual))
    return median, transform, crs, files, int(stable.sum())


def read_nonthermal_scene(bundle, window):
    arrays = {}
    transform = crs = None
    for layer in ("QC", "cloud", "water", "height"):
        with rasterio.open(bundle.layers[layer]) as dataset:
            current_transform = dataset.window_transform(window)
            if transform is None:
                transform, crs = current_transform, dataset.crs
            elif current_transform != transform or dataset.crs != crs:
                raise ValueError("Native nonthermal layer grid mismatch")
            arrays[layer] = dataset.read(1, window=window, masked=True)
    return arrays, transform, crs


def run() -> dict[str, Any]:
    protocol = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    rule = protocol["free_checks"]["science_tcc_canopy_span_screen"]
    if rule["decision_id"] != "V6.2-D015" or rule["new_v6_2_coefficient_viewed_at_freeze"] is not False:
        raise ValueError("D015 prospective rule is not frozen")
    expected_manifest_sha = rule["source_verification_manifest_sha256"]
    if sha256_file(SOURCE_MANIFEST) != expected_manifest_sha:
        raise ValueError("Science TCC verification manifest changed after D015 freeze")

    selected_orbits = selected_orbits_from_frozen_rule(protocol)
    bundles = discover_latest_complete_bundles(RAW_LSTE, selected_orbits)
    grouped = defaultdict(list)
    for bundle in bundles:
        grouped[(bundle.orbit, bundle.tile)].append(bundle)

    stable_tcc, tcc_transform, tcc_crs, tcc_files, stable_source_cells = load_phoenix_stable_tcc()
    grid = phoenix_grid()
    allowed_keys = set(grid.blocks["block_key"].astype(int))
    block_lookup = dict(zip(grid.blocks["block_key"].astype(int), grid.blocks["block_id"]))
    bounds = (
        float(grid.blocks["center_x"].min() - 500.0),
        float(grid.blocks["center_y"].min() - 500.0),
        float(grid.blocks["center_x"].max() + 500.0),
        float(grid.blocks["center_y"].max() + 500.0),
    )
    target_cache = {}
    rows = []
    pass_counts = []
    for orbit in selected_orbits:
        tile_frames = []
        for (candidate_orbit, tile), tile_bundles in sorted(grouped.items()):
            if candidate_orbit != orbit:
                continue
            with rasterio.open(tile_bundles[0].layers["QC"]) as first:
                window = _aligned_window(first, bounds)
            if window is None:
                continue
            scenes = []
            target_transform = target_crs = None
            for bundle in sorted(tile_bundles, key=lambda item: (item.instant, item.scene)):
                scene, current_transform, current_crs = read_nonthermal_scene(bundle, window)
                if target_transform is None:
                    target_transform, target_crs = current_transform, current_crs
                elif current_transform != target_transform or current_crs != target_crs:
                    raise ValueError("Selected scenes do not share a native tile grid")
                scenes.append(scene)
            valid = merge_nonthermal_scene_masks(scenes)
            cache_key = (valid.shape, tuple(target_transform), target_crs.to_string())
            if cache_key not in target_cache:
                target_cache[cache_key] = _reproject_array(
                    stable_tcc,
                    source_transform=tcc_transform,
                    source_crs=tcc_crs,
                    target_shape=valid.shape,
                    target_transform=target_transform,
                    target_crs=target_crs,
                    resampling=Resampling.average,
                    source_nodata=np.nan,
                )
            canopy = target_cache[cache_key]
            rr, cc = np.indices(valid.shape, dtype=np.int32)
            xs = target_transform.c + (cc + 0.5) * target_transform.a
            ys = target_transform.f + (rr + 0.5) * target_transform.e
            grid_cols = np.floor((xs - grid.origin_x) / 1000.0).astype(np.int64)
            grid_rows = np.floor((ys - grid.origin_y) / 1000.0).astype(np.int64)
            block_keys = grid_rows * int(grid.ncols) + grid_cols
            keep = valid & np.isfinite(canopy)
            keep &= np.isin(block_keys, np.fromiter(allowed_keys, dtype=np.int64))
            if keep.any():
                tile_frames.append(
                    pd.DataFrame(
                        {"block_key": block_keys[keep], "x": xs[keep], "y": ys[keep], "canopy": canopy[keep], "tile": tile}
                    )
                )
        if not tile_frames:
            raise RuntimeError(f"Orbit {orbit} produced no nonthermal TCC cells")
        cells = pd.concat(tile_frames, ignore_index=True)
        cells = cells.sort_values(["x", "y", "tile"], kind="stable").drop_duplicates(["x", "y"], keep="last")
        candidates = eligible = 0
        for block_key, block in cells.groupby("block_key", sort=True):
            if len(block) < 60:
                continue
            candidates += 1
            p10, p90, span = canopy_span(block["canopy"].to_numpy())
            is_eligible = bool(span >= 0.20)
            eligible += int(is_eligible)
            rows.append(
                {
                    "city": "Phoenix",
                    "pass_id": f"phoenix:{orbit}",
                    "block_id": block_lookup[int(block_key)],
                    "nonthermal_native_cells": int(len(block)),
                    "canopy_p10_fraction": p10,
                    "canopy_p90_fraction": p90,
                    "canopy_span_fraction": span,
                    "meets_frozen_0_20_span": is_eligible,
                }
            )
        pass_counts.append(
            {"pass_id": f"phoenix:{orbit}", "native_cells": int(len(cells)), "candidate_block_passes": candidates, "eligible_block_passes": eligible}
        )

    rows.sort(key=lambda row: (row["pass_id"], row["block_id"]))
    spans = np.array([row["canopy_span_fraction"] for row in rows], dtype=float)
    eligible_count = sum(row["meets_frozen_0_20_span"] for row in rows)
    ruling = "PERMIT_CONDITIONAL_FIVE_PASS_THERMAL_RERUN" if eligible_count else "RETAIN_STAGE1_STOP_NO_OFFICIAL_TCC_ELIGIBILITY"
    result = {
        "decision_id": "V6.2-D015",
        "status": "COMPLETE_NO_THERMAL_ACCESS",
        "ruling": ruling,
        "selected_orbits": selected_orbits,
        "candidate_block_passes": len(rows),
        "eligible_block_passes": int(eligible_count),
        "pass_counts": pass_counts,
        "canopy_span_fraction": {
            "minimum": float(np.min(spans)),
            "p25": float(np.quantile(spans, 0.25)),
            "median": float(np.median(spans)),
            "p75": float(np.quantile(spans, 0.75)),
            "maximum": float(np.max(spans)),
            "frozen_floor": 0.20,
        },
        "stable_source_cells": stable_source_cells,
        "thermal_values_opened": False,
        "tcc_source_values_opened_after_D015_freeze": True,
        "threshold_relaxed": False,
        "source_sha256": {str(path.relative_to(ROOT)): sha256_file(path) for path in tcc_files + [SOURCE_MANIFEST, PROTOCOL]},
        "rows": rows,
    }
    write_json(PACKAGE / "analysis_manifest.json", result)
    print(json.dumps({key: result[key] for key in ("status", "ruling", "candidate_block_passes", "eligible_block_passes", "canopy_span_fraction")}, sort_keys=True))
    return result


if __name__ == "__main__":
    run()
