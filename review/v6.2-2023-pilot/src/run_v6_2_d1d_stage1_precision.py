#!/usr/bin/env python3
"""Run the frozen v6.2 D1d five-pass native-grid precision census.

The command intentionally emits no coefficient value or sign. Point estimates
are streamed into the guarded sealed root; all public products are diagnostics.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Mapping

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from rasterio.windows import Window, from_bounds
from scipy.ndimage import distance_transform_edt
import yaml


REPOSITORY = Path(__file__).resolve().parent.parent
if str(REPOSITORY / "src") not in sys.path:
    sys.path.insert(0, str(REPOSITORY / "src"))

from urban_cooling_v2.connectivity_audit import build_block_grid
from urban_cooling_v2.stage1_precision_census import (
    REQUIRED_LAYERS,
    build_power_rows,
    discover_latest_complete_bundles,
    fit_block_pass,
    free_check_ruling,
    merge_scene_arrays,
)
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path


PROTOCOL = REPOSITORY / "docs/v2/v6_2/protocol_v6_2.yml"
DOMAINS = REPOSITORY / "data/raw/v2/domains/census_urban_areas.geojson"
D1B_PASSES = REPOSITORY / "deliverables/D1b_connectivity_v6_2_20260830/data/d1b_passes.csv"
D1B_TABLE = REPOSITORY / "deliverables/D1b_connectivity_v6_2_20260830/tables/d1b_connectivity.csv"
RAW_LSTE = REPOSITORY / "data/raw/ecostress_lst"
CANOPY = REPOSITORY / "data/raw/landcover/usfs_tcc_canopy_2025_30m.tif"
IMPERVIOUS = REPOSITORY / "data/raw/landcover/nlcd_impervious_2021_30m.tif"
LANDCOVER = REPOSITORY / "data/raw/v2/context/annual_nlcd_c1_1_2024/phoenix_annual_nlcd_c1_1_2024_land_cover.tif"
BUILDINGS = REPOSITORY / "data/interim/building_footprints_32612.parquet"
PACKAGE = REPOSITORY / "deliverables/D1d_stage1_precision_v6_2_20260902"
SEALED_NAME = "d1d_coefficients_SEALED_20260902.csv"


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value: Any):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def selected_orbits_from_frozen_rule(protocol: Mapping[str, Any]) -> list[int]:
    frozen = [
        int(value)
        for value in protocol["free_checks"]["stage_1_precision_census"]["pass_selection"]["selected_orbits"]
    ]
    passes = pd.read_csv(D1B_PASSES)
    candidates = passes.loc[
        passes["city"].eq("phoenix")
        & passes["season_window"].eq("sensitivity")
        & passes["view_zenith_set_deg"].eq(25)
        & passes["acquisition_utc"].astype(str).str.startswith("2023")
    ].copy()
    candidates["orbit"] = pd.to_numeric(candidates["orbit"], errors="raise").astype(int)
    candidates["acquisition_utc"] = pd.to_datetime(candidates["acquisition_utc"], utc=True)
    candidates = candidates.sort_values(["acquisition_utc", "orbit"], kind="stable")
    available = []
    for orbit in candidates["orbit"].tolist():
        try:
            discover_latest_complete_bundles(RAW_LSTE, [orbit])
        except ValueError:
            continue
        available.append(orbit)
    selected = available[:5]
    if selected != frozen:
        raise ValueError(f"Frozen pass selection mismatch: protocol={frozen}, recomputed={selected}")
    return frozen


def phoenix_grid():
    domains = gpd.read_file(DOMAINS)
    city_column = "city" if "city" in domains.columns else "id"
    selected = domains.loc[domains[city_column].astype(str).str.casefold().eq("phoenix")]
    if len(selected) != 1:
        raise ValueError(f"Expected one Phoenix urban area, found {len(selected)}")
    return build_block_grid(selected.iloc[0], "phoenix")


def _aligned_window(dataset: rasterio.io.DatasetReader, bounds: tuple[float, float, float, float]) -> Window | None:
    left = max(dataset.bounds.left, bounds[0])
    bottom = max(dataset.bounds.bottom, bounds[1])
    right = min(dataset.bounds.right, bounds[2])
    top = min(dataset.bounds.top, bounds[3])
    if left >= right or bottom >= top:
        return None
    raw = from_bounds(left, bottom, right, top, dataset.transform)
    row0 = max(0, int(math.floor(raw.row_off)))
    col0 = max(0, int(math.floor(raw.col_off)))
    row1 = min(dataset.height, int(math.ceil(raw.row_off + raw.height)))
    col1 = min(dataset.width, int(math.ceil(raw.col_off + raw.width)))
    if row1 <= row0 or col1 <= col0:
        return None
    return Window(col0, row0, col1 - col0, row1 - row0)


def _reproject_array(
    source: np.ndarray,
    *,
    source_transform,
    source_crs,
    target_shape: tuple[int, int],
    target_transform,
    target_crs,
    resampling: Resampling,
    source_nodata: float | None,
) -> np.ndarray:
    destination = np.full(target_shape, np.nan, dtype=np.float32)
    reproject(
        source=np.asarray(source, dtype=np.float32),
        destination=destination,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=source_nodata,
        dst_transform=target_transform,
        dst_crs=target_crs,
        dst_nodata=np.nan,
        resampling=resampling,
        init_dest_nodata=True,
        num_threads=2,
    )
    return destination


def _building_presence_10m(bounds: tuple[float, float, float, float]):
    left = math.floor(bounds[0] / 10.0) * 10.0
    bottom = math.floor(bounds[1] / 10.0) * 10.0
    right = math.ceil(bounds[2] / 10.0) * 10.0
    top = math.ceil(bounds[3] / 10.0) * 10.0
    width = int(round((right - left) / 10.0))
    height = int(round((top - bottom) / 10.0))
    try:
        buildings = gpd.read_parquet(BUILDINGS, bbox=(left, bottom, right, top))
    except (TypeError, ValueError):
        buildings = gpd.read_parquet(BUILDINGS)
        buildings = buildings.cx[left:right, bottom:top]
    if buildings.crs is None:
        raise ValueError("Building footprints have no CRS")
    buildings = buildings.to_crs(epsg=32612)
    buildings = buildings.loc[buildings.geometry.notna() & ~buildings.geometry.is_empty]
    transform = from_origin(left, top, 10.0, 10.0)
    array = rasterize(
        ((geometry, 1) for geometry in buildings.geometry),
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=False,
        dtype=np.uint8,
    )
    return array, transform, rasterio.crs.CRS.from_epsg(32612), int(len(buildings))


class StaticContext:
    def __init__(self, bounds: tuple[float, float, float, float]):
        self.canopy_ds = rasterio.open(CANOPY)
        self.impervious_ds = rasterio.open(IMPERVIOUS)
        self.landcover_ds = rasterio.open(LANDCOVER)
        self.canopy = self.canopy_ds.read(1).astype(np.float32) / 100.0
        self.impervious = self.impervious_ds.read(1).astype(np.float32) / 100.0
        landcover = self.landcover_ds.read(1)
        valid = landcover != 0
        self.low_vegetation = np.where(
            valid, np.isin(landcover, [52, 71, 81, 82]).astype(np.float32), np.nan
        )
        self.bare = np.where(valid, (landcover == 31).astype(np.float32), np.nan)
        water = landcover == 11
        if not water.any():
            raise ValueError("Annual NLCD context contains no open-water cell")
        distance = distance_transform_edt(~water, sampling=(30.0, 30.0)).astype(np.float32)
        distance[~valid] = np.nan
        self.distance_to_water = distance
        (
            self.building,
            self.building_transform,
            self.building_crs,
            self.building_feature_count,
        ) = _building_presence_10m(bounds)
        self.cache: dict[tuple[Any, ...], dict[str, np.ndarray]] = {}

    def close(self) -> None:
        self.canopy_ds.close()
        self.impervious_ds.close()
        self.landcover_ds.close()

    def for_grid(self, shape, transform, crs) -> dict[str, np.ndarray]:
        key = (shape, tuple(transform), crs.to_string())
        if key in self.cache:
            return self.cache[key]
        kwargs = dict(target_shape=shape, target_transform=transform, target_crs=crs)
        result = {
            "canopy_fraction": _reproject_array(
                self.canopy,
                source_transform=self.canopy_ds.transform,
                source_crs=self.canopy_ds.crs,
                resampling=Resampling.average,
                source_nodata=None,
                **kwargs,
            ),
            "impervious_fraction": _reproject_array(
                self.impervious,
                source_transform=self.impervious_ds.transform,
                source_crs=self.impervious_ds.crs,
                resampling=Resampling.average,
                source_nodata=None,
                **kwargs,
            ),
            "low_vegetation_fraction": _reproject_array(
                self.low_vegetation,
                source_transform=self.landcover_ds.transform,
                source_crs=self.landcover_ds.crs,
                resampling=Resampling.average,
                source_nodata=np.nan,
                **kwargs,
            ),
            "bare_fraction": _reproject_array(
                self.bare,
                source_transform=self.landcover_ds.transform,
                source_crs=self.landcover_ds.crs,
                resampling=Resampling.average,
                source_nodata=np.nan,
                **kwargs,
            ),
            "building_fraction": _reproject_array(
                self.building,
                source_transform=self.building_transform,
                source_crs=self.building_crs,
                resampling=Resampling.average,
                source_nodata=None,
                **kwargs,
            ),
            "distance_to_water": _reproject_array(
                self.distance_to_water,
                source_transform=self.landcover_ds.transform,
                source_crs=self.landcover_ds.crs,
                resampling=Resampling.average,
                source_nodata=np.nan,
                **kwargs,
            ),
        }
        self.cache[key] = result
        return result


def _read_bundle_window(bundle, window: Window) -> tuple[dict[str, np.ndarray], Any, Any]:
    arrays: dict[str, np.ndarray] = {}
    transform = None
    crs = None
    shape = (int(window.height), int(window.width))
    for layer in REQUIRED_LAYERS:
        with rasterio.open(bundle.layers[layer]) as dataset:
            current_transform = dataset.window_transform(window)
            if transform is None:
                transform = current_transform
                crs = dataset.crs
            elif current_transform != transform or dataset.crs != crs:
                raise ValueError(f"Native layer grid mismatch in {bundle.layers[layer].name}")
            arrays[layer] = dataset.read(1, window=window)
            if arrays[layer].shape != shape:
                raise ValueError("Windowed native layer has an unexpected shape")
    return arrays, transform, crs


def _tile_frame(
    bundles,
    *,
    bounds,
    grid,
    allowed_keys: set[int],
    static: StaticContext,
) -> pd.DataFrame:
    with rasterio.open(bundles[0].layers["LST"]) as first:
        window = _aligned_window(first, bounds)
    if window is None:
        return pd.DataFrame()
    scenes = []
    transform = None
    crs = None
    for bundle in sorted(bundles, key=lambda value: (value.instant, value.scene)):
        arrays, current_transform, current_crs = _read_bundle_window(bundle, window)
        if transform is None:
            transform, crs = current_transform, current_crs
        elif current_transform != transform or current_crs != crs:
            raise ValueError("Selected scenes do not share one MGRS tile grid")
        scenes.append(arrays)
    lst, height, valid_thermal = merge_scene_arrays(scenes)
    assert transform is not None and crs is not None
    static_values = static.for_grid(lst.shape, transform, crs)

    row_indices, col_indices = np.indices(lst.shape, dtype=np.int32)
    xs = transform.c + (col_indices + 0.5) * transform.a
    ys = transform.f + (row_indices + 0.5) * transform.e
    grid_cols = np.floor((xs - grid.origin_x) / 1000.0).astype(np.int64)
    grid_rows = np.floor((ys - grid.origin_y) / 1000.0).astype(np.int64)
    block_keys = grid_rows * int(grid.ncols) + grid_cols
    in_urban_block = np.isin(block_keys, np.fromiter(allowed_keys, dtype=np.int64))
    complete = valid_thermal & in_urban_block
    complete &= np.isfinite(static_values["canopy_fraction"])
    for value in static_values.values():
        complete &= np.isfinite(value)
    if not complete.any():
        return pd.DataFrame()
    return pd.DataFrame(
        {
            "block_key": block_keys[complete],
            "x": xs[complete],
            "y": ys[complete],
            "lst_k": lst[complete],
            "canopy_fraction": static_values["canopy_fraction"][complete],
            "impervious_fraction": static_values["impervious_fraction"][complete],
            "low_vegetation_fraction": static_values["low_vegetation_fraction"][complete],
            "bare_fraction": static_values["bare_fraction"][complete],
            "building_fraction": static_values["building_fraction"][complete],
            "elevation": height[complete],
            "distance_to_water": static_values["distance_to_water"][complete],
        }
    )


def run() -> dict[str, Any]:
    protocol = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    frozen = protocol["free_checks"]["stage_1_precision_census"]
    if frozen["decision_id"] != "V6.2-D011" or frozen["new_v6_2_coefficients_viewed_at_freeze"] is not False:
        raise ValueError("D011 is not a valid prospective frozen rule")
    selected_orbits = selected_orbits_from_frozen_rule(protocol)
    bundles = discover_latest_complete_bundles(RAW_LSTE, selected_orbits)
    bundle_by_orbit_tile: dict[tuple[int, str], list[Any]] = defaultdict(list)
    for bundle in bundles:
        bundle_by_orbit_tile[(bundle.orbit, bundle.tile)].append(bundle)

    grid = phoenix_grid()
    block_lookup = dict(zip(grid.blocks["block_key"].astype(int), grid.blocks["block_id"]))
    allowed_keys = set(block_lookup)
    bounds = (
        float(grid.blocks["center_x"].min() - 500.0),
        float(grid.blocks["center_y"].min() - 500.0),
        float(grid.blocks["center_x"].max() + 500.0),
        float(grid.blocks["center_y"].max() + 500.0),
    )

    static = StaticContext(bounds)
    open_rows: list[dict[str, object]] = []
    sealed_rows: list[dict[str, object]] = []
    pass_counts: list[dict[str, object]] = []
    try:
        for orbit in selected_orbits:
            tile_frames = []
            for (_, tile), tile_bundles in sorted(bundle_by_orbit_tile.items()):
                if _ != orbit:
                    continue
                frame = _tile_frame(
                    tile_bundles,
                    bounds=bounds,
                    grid=grid,
                    allowed_keys=allowed_keys,
                    static=static,
                )
                if not frame.empty:
                    frame["source_tile"] = tile
                    tile_frames.append(frame)
            if not tile_frames:
                raise ValueError(f"Selected orbit {orbit} produced no complete native cells")
            cells = pd.concat(tile_frames, ignore_index=True)
            cells = cells.sort_values(["x", "y", "source_tile"], kind="stable")
            cells = cells.drop_duplicates(["x", "y"], keep="last")
            pass_candidate_rows = 0
            pass_converged_rows = 0
            for block_key, block in cells.groupby("block_key", sort=True):
                if len(block) < 60:
                    continue
                pass_candidate_rows += 1
                block_key = int(block_key)
                block_id = block_lookup[block_key]
                grid_row = block_key // int(grid.ncols)
                grid_col = block_key % int(grid.ncols)
                block_x0 = grid.origin_x + grid_col * 1000.0
                block_y0 = grid.origin_y + grid_row * 1000.0
                diagnostics, slope = fit_block_pass(
                    city="Phoenix",
                    block_id=block_id,
                    pass_id=f"phoenix:{orbit}",
                    lst_k=block["lst_k"].to_numpy(),
                    canopy_fraction=block["canopy_fraction"].to_numpy(),
                    context={
                        "impervious_fraction": block["impervious_fraction"].to_numpy(),
                        "low_vegetation_fraction": block["low_vegetation_fraction"].to_numpy(),
                        "bare_fraction": block["bare_fraction"].to_numpy(),
                        "building_fraction": block["building_fraction"].to_numpy(),
                        "elevation": block["elevation"].to_numpy(),
                        "distance_to_water": block["distance_to_water"].to_numpy(),
                    },
                    x_coord=block["x"].to_numpy(),
                    y_coord=block["y"].to_numpy(),
                    block_origin_x=block_x0,
                    block_origin_y=block_y0,
                )
                open_rows.append(diagnostics)
                if slope is not None:
                    pass_converged_rows += 1
                    sealed_rows.append(
                        {
                            "city": "Phoenix",
                            "block_id": block_id,
                            "pass_id": f"phoenix:{orbit}",
                            "slope_K_per_unit_canopy_fraction": slope,
                            "CE_K_per_10pp": -0.10 * slope,
                        }
                    )
            pass_counts.append(
                {
                    "pass_id": f"phoenix:{orbit}",
                    "complete_native_cells": int(len(cells)),
                    "candidate_block_passes": pass_candidate_rows,
                    "converged_block_passes": pass_converged_rows,
                }
            )
    finally:
        static.close()

    if not open_rows:
        raise RuntimeError(
            "D1d failed closed: no block-pass has at least 60 complete cells; "
            f"pass counts={pass_counts}"
        )
    open_rows.sort(key=lambda row: (str(row["pass_id"]), str(row["block_id"])))
    sealed_rows.sort(key=lambda row: (str(row["pass_id"]), str(row["block_id"])))
    if len(sealed_rows) != sum(bool(row["convergence_flag"]) for row in open_rows):
        raise ValueError("Sealed/open converged-row identity failed")

    standard_errors = [
        float(row["spatially_robust_se_K_per_10pp"])
        for row in open_rows
        if row["convergence_flag"] and row["spatially_robust_se_K_per_10pp"] is not None
    ]
    d1b_rows = pd.read_csv(D1B_TABLE).to_dict(orient="records")
    if standard_errors:
        power_rows, se_summaries = build_power_rows(standard_errors, d1b_rows)
        ruling = free_check_ruling(power_rows)
        run_status = "RULING_CALCULATED_SEALED_FILE_NOT_OPENED"
    else:
        se_summaries = {"p25": None, "median": None, "p75": None}
        power_rows = []
        for item in d1b_rows:
            available = int(
                math.floor(
                    float(item["block_passes"])
                    * float(item["largest_connected_component_share"])
                )
            )
            for reliability in (0.30, 0.50, 0.70):
                for criterion, latent_target in (("detection", 0.10), ("equivalence", 0.05)):
                    power_rows.append(
                        {
                            "city": item["city"],
                            "season_window": item["season_window"],
                            "view_zenith_set_deg": int(item["view_zenith_set_deg"]),
                            "se_summary": "not_estimable",
                            "observed_stage1_se_K_per_10pp": None,
                            "reliability": reliability,
                            "criterion": criterion,
                            "attenuated_target_K_per_10pp": latent_target * math.sqrt(reliability),
                            "required_connected_block_passes": None,
                            "available_connected_block_passes_D1b": available,
                            "status": "NOT_ESTIMABLE_NO_BLOCK_PASS_MEETS_FROZEN_CANOPY_SPAN",
                        }
                    )
        ruling = {
            "optimistic_required_connected_block_passes": None,
            "available_connected_block_passes_max_by_city": {
                city: max(
                    int(row["available_connected_block_passes_D1b"])
                    for row in power_rows
                    if row["city"] == city
                )
                for city in sorted({str(row["city"]) for row in power_rows})
            },
            "stop_before_gate_A": True,
            "ruling": "STOP_BEFORE_GATE_A_NO_ESTIMABLE_BLOCK_PASS_UNDER_FROZEN_CANOPY_SPAN",
            "gate_A_authorized": False,
            "reason": "All candidate five-pass block-passes fail the frozen 0.20 canopy p10-p90 span floor",
        }
        run_status = "D1D_STOP_NO_ESTIMABLE_BLOCK_PASS"

    sealed_path = guarded_output_path(REPOSITORY, "sealed", SEALED_NAME)
    sealed_path.parent.mkdir(parents=True, exist_ok=True)
    if sealed_path.exists():
        raise FileExistsError(f"Refusing to overwrite sealed output: {sealed_path}")
    temporary = sealed_path.with_name(f".{sealed_path.name}.tmp")
    try:
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "city",
                    "block_id",
                    "pass_id",
                    "slope_K_per_unit_canopy_fraction",
                    "CE_K_per_10pp",
                ],
            )
            writer.writeheader()
            writer.writerows(sealed_rows)
        os.replace(temporary, sealed_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    sealed_sha256 = sha256_file(sealed_path)

    PACKAGE.mkdir(parents=True, exist_ok=True)
    data_dir = PACKAGE / "data"
    data_dir.mkdir(exist_ok=True)
    write_json(
        data_dir / "d1d_analysis_rows.json",
        {
            "stage1_rows": open_rows,
            "power_rows": power_rows,
        },
    )
    sealed_link = PACKAGE / "sealed/d1d_coefficients_SEALED.csv"
    sealed_link.parent.mkdir(exist_ok=True)
    if sealed_link.exists() or sealed_link.is_symlink():
        raise FileExistsError(f"Refusing to replace package sealed link: {sealed_link}")
    sealed_link.symlink_to(os.path.relpath(sealed_path, sealed_link.parent))
    write_json(
        PACKAGE / "sealed_file_pointer.json",
        {
            "canonical_path": str(sealed_path.relative_to(REPOSITORY)),
            "package_link": str(sealed_link.relative_to(REPOSITORY)),
            "sha256": sealed_sha256,
            "opened_after_creation": False,
            "coefficient_values_in_open_outputs": False,
        },
    )

    failures = Counter(str(row["failure_reason"]) for row in open_rows if not row["convergence_flag"])
    stable_count = sum(bool(row["design_stability_flag"]) for row in open_rows)
    source_paths = [PROTOCOL, DOMAINS, D1B_PASSES, D1B_TABLE, CANOPY, IMPERVIOUS, LANDCOVER, BUILDINGS]
    source_paths.extend(
        bundle.layers[layer]
        for bundle in bundles
        for layer in REQUIRED_LAYERS
    )
    input_hashes = {str(path.relative_to(REPOSITORY)): sha256_file(path) for path in source_paths}
    manifest = {
        "decision_id": "V6.2-D011",
        "status": run_status,
        "selected_orbits": selected_orbits,
        "native_complete_bundles": len(bundles),
        "native_input_files": len(bundles) * len(REQUIRED_LAYERS),
        "building_features_in_bounds": static.building_feature_count,
        "candidate_block_passes": len(open_rows),
        "converged_block_passes": len(sealed_rows),
        "design_stable_block_passes": stable_count,
        "failure_counts": dict(failures),
        "pass_counts": pass_counts,
        "standard_error_summary_K_per_10pp": se_summaries,
        "power_grid_rows": len(power_rows),
        "ruling": ruling,
        "sealed_output": {
            "canonical_path": str(sealed_path.relative_to(REPOSITORY)),
            "package_link": str(sealed_link.relative_to(REPOSITORY)),
            "sha256": sealed_sha256,
            "row_count": len(sealed_rows),
            "opened_after_creation": False,
        },
        "checks": {
            "exactly_five_passes": len(selected_orbits) == 5,
            "one_open_row_per_candidate_block_pass": len(open_rows) == sum(item["candidate_block_passes"] for item in pass_counts),
            "sealed_rows_equal_converged_rows": len(sealed_rows) == sum(bool(row["convergence_flag"]) for row in open_rows),
            "open_rows_have_no_point_estimate_field": all(
                not any(token in key.casefold() for token in ("slope_k_per_unit", "ce_k_per_10pp"))
                for row in open_rows
                for key in row
            ),
            "power_grid_has_expected_rows": len(power_rows) == (144 if standard_errors else 48),
            "gate_A_authorized": False,
        },
        "input_sha256": dict(sorted(input_hashes.items())),
        "deviations": frozen["known_deviations"],
    }
    if not all(value is True for key, value in manifest["checks"].items() if key != "gate_A_authorized"):
        raise RuntimeError("D1d failed closed: manifest checks did not all pass")
    write_json(PACKAGE / "analysis_manifest.json", manifest)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "candidate_block_passes": len(open_rows),
                "converged_block_passes": len(sealed_rows),
                "design_stable_block_passes": stable_count,
                "sealed_sha256": sealed_sha256,
                "ruling": ruling["ruling"],
            },
            sort_keys=True,
        )
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
