#!/usr/bin/env python3
"""Domain-exact ECOSTRESS view-angle and cloud summaries for Step 2.

The functions in this module deliberately open only the small quality-layer
COGs selected by the catalogue audit.  They never open or download LST.  A
physical pass is represented by every intersecting MGRS tile in one city/orbit
group; duplicate product revisions are resolved before pixels are combined.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd
import rasterio
from rasterio.errors import WindowError
from rasterio.features import geometry_mask, geometry_window
from rasterio.warp import transform_geom
from shapely.geometry import box, mapping, shape



VIEW_ASSET_TYPE = "view_zenith_cog"
CLOUD_ASSET_TYPE = "cloud_cog"
_MGRS_ZONE = re.compile(r"^(?P<zone>[1-9]|[1-5][0-9]|60)[A-Z].*$")


def canonical_mgrs_core_bounds(bounds: Any) -> tuple[float, float, float, float]:
    """Return the non-overlapping 100 km core inside a buffered MGRS COG."""

    left = round(float(bounds.left) / 100_000.0) * 100_000.0
    bottom = round(float(bounds.bottom) / 100_000.0) * 100_000.0
    return left, bottom, left + 100_000.0, bottom + 100_000.0


def select_latest_tile_revisions(rows: pd.DataFrame) -> pd.DataFrame:
    """Keep the latest build/revision for each city/orbit/scene/MGRS tile."""

    required = {
        "city",
        "orbit",
        "scene",
        "tile",
        "granule_id",
        "selected_build",
        "selected_revision",
    }
    missing = sorted(required.difference(rows.columns))
    if missing:
        raise ValueError(f"Layer manifest lacks columns: {missing}")
    out = rows.copy()
    out["selected_build"] = pd.to_numeric(out["selected_build"], errors="coerce")
    out["selected_revision"] = pd.to_numeric(
        out["selected_revision"], errors="coerce"
    )
    if out[["selected_build", "selected_revision"]].isna().any().any():
        raise ValueError("Every available quality layer needs a build and revision")
    out = out.sort_values(
        [
            "city",
            "orbit",
            "scene",
            "tile",
            "selected_build",
            "selected_revision",
            "granule_id",
        ],
        kind="stable",
    )
    return out.drop_duplicates(
        ["city", "orbit", "scene", "tile"], keep="last"
    ).reset_index(drop=True)


def _local_asset_path(row: Mapping[str, Any], asset_root: Path) -> Path:
    asset_type = str(row["asset_type"])
    if asset_type not in {VIEW_ASSET_TYPE, CLOUD_ASSET_TYPE}:
        raise ValueError(f"Unsupported quality layer: {asset_type}")
    file_name = Path(str(row["file_name"])).name
    path = asset_root / asset_type / file_name
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _domain_window(
    dataset: rasterio.io.DatasetReader,
    domain_geometry_wgs84: Mapping[str, Any],
) -> tuple[Any, np.ndarray] | None:
    if shape(domain_geometry_wgs84).is_empty:
        return None
    projected = transform_geom(
        "EPSG:4326", dataset.crs, domain_geometry_wgs84, precision=-1
    )
    # ECOSTRESS MGRS COGs are approximately 109.8 km square: a 100 km
    # canonical MGRS core plus an east/south overlap.  Clip to the core so
    # adjacent tile grids do not count the same Census-domain area twice.
    core = box(*canonical_mgrs_core_bounds(dataset.bounds))
    projected_shape = shape(projected).intersection(core)
    if projected_shape.is_empty:
        return None
    projected = mapping(projected_shape)
    try:
        window = geometry_window(dataset, [projected])
    except WindowError:
        return None
    transform = dataset.window_transform(window)
    domain = geometry_mask(
        [projected],
        out_shape=(int(window.height), int(window.width)),
        transform=transform,
        invert=True,
        all_touched=False,
    )
    if not domain.any():
        return None
    return window, domain


def partition_domain_for_mgrs_tile(
    domain_geometry_wgs84: Mapping[str, Any], tile: str
) -> dict[str, Any]:
    """Clip a domain to the canonical longitude band of an MGRS UTM zone.

    Full 100 km COG squares from adjacent UTM zones overlap geographically near
    a zone boundary.  Assigning pixels by the MGRS zone's six-degree longitude
    band prevents double-counting while leaving native grids unchanged.
    """

    match = _MGRS_ZONE.fullmatch(str(tile).strip().upper())
    if match is None:
        raise ValueError(f"Cannot parse MGRS UTM zone from tile {tile!r}")
    zone = int(match.group("zone"))
    west = -180.0 + 6.0 * (zone - 1)
    east = west + 6.0
    # Treat the eastern edge as open so an exact-boundary pixel center has one
    # deterministic owner.  The epsilon is far below native-pixel precision.
    if zone < 60:
        east -= 1e-10
    domain = shape(domain_geometry_wgs84)
    if not domain.is_valid:
        raise ValueError("domain geometry must be topology-valid before raster screening")
    clipped = domain.intersection(box(west, -90.0, east, 90.0))
    return mapping(clipped)


def _check_same_grid(
    reference: rasterio.io.DatasetReader,
    candidate: rasterio.io.DatasetReader,
) -> None:
    if (
        candidate.crs != reference.crs
        or candidate.transform != reference.transform
        or candidate.width != reference.width
        or candidate.height != reference.height
    ):
        raise ValueError("Quality layers for one MGRS tile do not share a grid")


def domain_pixel_counts_by_tile(
    rows: pd.DataFrame,
    *,
    domain_geometry_wgs84: Mapping[str, Any],
    asset_root: str | Path,
    tile_domain_geometries_wgs84: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, int]:
    """Rasterize a frozen domain once on every MGRS grid it intersects.

    A pass can omit a tile because its swath misses that part of the city.  The
    resulting tile-independent sum is therefore the correct denominator for
    the pass-level 95% domain-coverage rule.
    """

    if rows.empty:
        raise ValueError("Domain denominator needs at least one reference layer")
    selected = select_latest_tile_revisions(rows)
    root = Path(asset_root)
    counts: dict[str, int] = {}
    for tile, tile_rows in selected.groupby("tile", sort=True):
        record = tile_rows.sort_values(
            ["scene", "selected_build", "selected_revision", "granule_id"],
            kind="stable",
        ).iloc[0].to_dict()
        path = _local_asset_path(record, root)
        tile_domain = (
            tile_domain_geometries_wgs84[str(tile)]
            if tile_domain_geometries_wgs84 is not None
            else partition_domain_for_mgrs_tile(domain_geometry_wgs84, str(tile))
        )
        with rasterio.open(path) as dataset:
            clipped = _domain_window(dataset, tile_domain)
        counts[str(tile)] = int(clipped[1].sum()) if clipped is not None else 0
    if sum(counts.values()) == 0:
        raise ValueError("No reference MGRS grid contains a frozen-domain pixel")
    return counts


def summarize_view_pass(
    rows: pd.DataFrame,
    *,
    domain_geometry_wgs84: Mapping[str, Any],
    asset_root: str | Path,
    near_nadir_threshold_deg: float = 20.0,
    minimum_view_coverage: float = 0.95,
    domain_pixel_denominator: int | None = None,
    tile_domain_geometries_wgs84: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize one city/orbit pass across its unique MGRS tiles.

    Adjacent along-track scenes can overlap within one tile.  Their valid
    pixels are unioned; where two observations overlap, the larger absolute
    view angle is retained as a conservative tie-breaker.
    """

    if rows.empty:
        raise ValueError("A pass needs at least one view-angle row")
    selected = select_latest_tile_revisions(rows)
    if set(selected["asset_type"].astype(str)) != {VIEW_ASSET_TYPE}:
        raise ValueError("summarize_view_pass accepts only view-angle rows")
    root = Path(asset_root)
    values: list[np.ndarray] = []
    n_domain = 0
    n_valid = 0
    n_overlap = 0
    n_tiles = 0
    n_scene_tiles = 0

    for _, tile_rows in selected.groupby("tile", sort=True):
        records = tile_rows.sort_values(
            ["scene", "selected_build", "selected_revision", "granule_id"],
            kind="stable",
        ).to_dict("records")
        first_path = _local_asset_path(records[0], root)
        tile = str(tile_rows.iloc[0]["tile"])
        tile_domain = (
            tile_domain_geometries_wgs84[tile]
            if tile_domain_geometries_wgs84 is not None
            else partition_domain_for_mgrs_tile(domain_geometry_wgs84, tile)
        )
        with rasterio.open(first_path) as reference:
            clipped = _domain_window(reference, tile_domain)
            if clipped is None:
                continue
            window, domain = clipped
            combined = np.full(domain.shape, np.nan, dtype=np.float32)
            for record in records:
                path = _local_asset_path(record, root)
                with rasterio.open(path) as dataset:
                    _check_same_grid(reference, dataset)
                    layer = dataset.read(1, window=window, masked=True)
                data = np.asarray(layer.filled(np.nan), dtype=np.float32)
                valid = (
                    domain
                    & ~np.ma.getmaskarray(layer)
                    & np.isfinite(data)
                    & (np.abs(data) <= 90.0)
                )
                already = valid & np.isfinite(combined)
                n_overlap += int(already.sum())
                fill = valid & ~np.isfinite(combined)
                combined[fill] = np.abs(data[fill])
                combined[already] = np.maximum(
                    combined[already], np.abs(data[already])
                )
                n_scene_tiles += 1
            tile_valid = domain & np.isfinite(combined)
            tile_values = combined[tile_valid]
            values.append(tile_values)
            n_domain += int(domain.sum())
            n_valid += int(tile_valid.sum())
            n_tiles += 1

    if n_domain == 0 and domain_pixel_denominator is None:
        raise ValueError("No rasterized Census-domain pixels intersect the pass")
    n_domain_present_tiles = n_domain
    if domain_pixel_denominator is not None:
        if domain_pixel_denominator < n_domain_present_tiles:
            raise ValueError("Global domain denominator is smaller than present-tile pixels")
        n_domain = int(domain_pixel_denominator)
    all_values = np.concatenate(values) if values else np.array([], dtype=float)
    coverage = n_valid / n_domain
    p95 = float(np.quantile(all_values, 0.95)) if n_valid else np.nan
    return {
        "n_domain_pixels": n_domain,
        "n_domain_pixels_in_present_tiles": n_domain_present_tiles,
        "n_view_valid_pixels": n_valid,
        "view_valid_fraction": coverage,
        "view_zenith_abs_min_deg": float(np.min(all_values))
        if n_valid
        else np.nan,
        "view_zenith_abs_median_deg": float(np.median(all_values))
        if n_valid
        else np.nan,
        "view_zenith_abs_mean_deg": float(np.mean(all_values))
        if n_valid
        else np.nan,
        "view_zenith_abs_p95_deg": p95,
        "view_zenith_abs_max_deg": float(np.max(all_values))
        if n_valid
        else np.nan,
        "near_nadir_threshold_deg": float(near_nadir_threshold_deg),
        "minimum_view_coverage": float(minimum_view_coverage),
        "near_nadir": bool(
            n_valid
            and coverage >= minimum_view_coverage
            and p95 <= near_nadir_threshold_deg
        ),
        "n_unique_mgrs_tiles": n_tiles,
        "n_selected_scene_tiles": n_scene_tiles,
        "n_overlapping_valid_pixels": n_overlap,
        "overlap_rule": "retain larger absolute view angle",
    }


def summarize_cloud_pass(
    cloud_rows: pd.DataFrame,
    view_rows: pd.DataFrame,
    *,
    domain_geometry_wgs84: Mapping[str, Any],
    asset_root: str | Path,
    domain_pixel_denominator: int | None = None,
    tile_domain_geometries_wgs84: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Measure clear-pixel survival for one pass, intersected with valid view data.

    Only cloud layers with a matching selected view-angle granule are used.
    ECOSTRESS cloud codes are 0=clear and 1=cloud.  Fill/masked/unexpected
    values do not survive.  In the small overlap between adjacent scenes,
    cloudy wins over clear as the conservative tie-breaker.
    """

    if cloud_rows.empty or view_rows.empty:
        raise ValueError("Cloud calibration needs cloud and view rows")
    clouds = select_latest_tile_revisions(cloud_rows)
    views = select_latest_tile_revisions(view_rows)
    clouds = clouds.loc[clouds["asset_type"].eq(CLOUD_ASSET_TYPE)]
    views = views.loc[views["asset_type"].eq(VIEW_ASSET_TYPE)]
    pairs = clouds.merge(
        views,
        on=["city", "orbit", "scene", "tile", "granule_id"],
        how="inner",
        suffixes=("_cloud", "_view"),
        validate="one_to_one",
    )
    if pairs.empty:
        raise ValueError("No cloud granule has a matching view-angle granule")
    root = Path(asset_root)
    n_domain = 0
    n_view_valid = 0
    n_clear = 0
    n_cloud = 0
    n_invalid = 0
    n_overlap = 0
    n_tiles = 0

    for _, tile_pairs in pairs.groupby("tile", sort=True):
        records = tile_pairs.sort_values(
            ["scene", "selected_build_cloud", "selected_revision_cloud", "granule_id"],
            kind="stable",
        ).to_dict("records")
        first_view = root / VIEW_ASSET_TYPE / Path(
            str(records[0]["file_name_view"])
        ).name
        tile = str(tile_pairs.iloc[0]["tile"])
        tile_domain = (
            tile_domain_geometries_wgs84[tile]
            if tile_domain_geometries_wgs84 is not None
            else partition_domain_for_mgrs_tile(domain_geometry_wgs84, tile)
        )
        with rasterio.open(first_view) as reference:
            clipped = _domain_window(reference, tile_domain)
            if clipped is None:
                continue
            window, domain = clipped
            view_valid_any = np.zeros(domain.shape, dtype=bool)
            cloud_observed = np.zeros(domain.shape, dtype=bool)
            clear_any = np.zeros(domain.shape, dtype=bool)
            cloudy_any = np.zeros(domain.shape, dtype=bool)
            unexpected_any = np.zeros(domain.shape, dtype=bool)
            for record in records:
                view_path = root / VIEW_ASSET_TYPE / Path(
                    str(record["file_name_view"])
                ).name
                cloud_path = root / CLOUD_ASSET_TYPE / Path(
                    str(record["file_name_cloud"])
                ).name
                if not view_path.is_file():
                    raise FileNotFoundError(view_path)
                if not cloud_path.is_file():
                    raise FileNotFoundError(cloud_path)
                with rasterio.open(view_path) as view_ds, rasterio.open(
                    cloud_path
                ) as cloud_ds:
                    _check_same_grid(reference, view_ds)
                    _check_same_grid(reference, cloud_ds)
                    view = view_ds.read(1, window=window, masked=True)
                    cloud = cloud_ds.read(1, window=window, masked=True)
                view_data = np.asarray(view.filled(np.nan), dtype=float)
                valid_view = (
                    domain
                    & ~np.ma.getmaskarray(view)
                    & np.isfinite(view_data)
                    & (np.abs(view_data) <= 90.0)
                )
                cloud_data = np.asarray(cloud.filled(255))
                cloud_unmasked = domain & ~np.ma.getmaskarray(cloud)
                observed = cloud_unmasked & np.isin(cloud_data, (0, 1))
                n_overlap += int((valid_view & view_valid_any).sum())
                view_valid_any |= valid_view
                cloud_observed |= observed
                clear_any |= observed & (cloud_data == 0)
                cloudy_any |= observed & (cloud_data == 1)
                unexpected_any |= cloud_unmasked & ~np.isin(cloud_data, (0, 1, 255))

            usable_base = domain & view_valid_any
            clear = usable_base & clear_any & ~cloudy_any
            cloudy = usable_base & cloudy_any
            invalid = usable_base & (~cloud_observed | unexpected_any)
            n_domain += int(domain.sum())
            n_view_valid += int(usable_base.sum())
            n_clear += int(clear.sum())
            n_cloud += int(cloudy.sum())
            n_invalid += int(invalid.sum())
            n_tiles += 1

    if n_domain == 0 and domain_pixel_denominator is None:
        raise ValueError("No rasterized Census-domain pixels intersect the pass")
    n_domain_present_tiles = n_domain
    if domain_pixel_denominator is not None:
        if domain_pixel_denominator < n_domain_present_tiles:
            raise ValueError("Global domain denominator is smaller than present-tile pixels")
        n_domain = int(domain_pixel_denominator)
    return {
        "n_domain_pixels": n_domain,
        "n_domain_pixels_in_present_tiles": n_domain_present_tiles,
        "n_view_valid_pixels": n_view_valid,
        "view_valid_fraction": n_view_valid / n_domain,
        "n_clear_pixels": n_clear,
        "n_cloud_pixels": n_cloud,
        "n_cloud_invalid_or_fill_pixels": n_invalid,
        "cloud_survival_fraction_of_domain": n_clear / n_domain,
        "clear_fraction_of_valid_view_pixels": n_clear / n_view_valid
        if n_view_valid
        else np.nan,
        "n_unique_mgrs_tiles": n_tiles,
        "n_overlapping_valid_pixels": n_overlap,
        "cloud_code_rule": (
            "0=clear; 1=cloud; 255/masked/unexpected=non-surviving; "
            "cloudy wins in scene overlap"
        ),
    }


__all__ = [
    "CLOUD_ASSET_TYPE",
    "VIEW_ASSET_TYPE",
    "canonical_mgrs_core_bounds",
    "domain_pixel_counts_by_tile",
    "partition_domain_for_mgrs_tile",
    "select_latest_tile_revisions",
    "summarize_cloud_pass",
    "summarize_view_pass",
]
