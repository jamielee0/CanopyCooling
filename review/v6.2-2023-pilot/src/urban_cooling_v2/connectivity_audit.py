#!/usr/bin/env python3
"""Outcome-blind block--pass connectivity audit for v6.2 D1b.

This module opens ECOSTRESS cloud and view-zenith quality layers only.  It does
not open, download, or inspect an LST/temperature response layer.  The graph is
an intentionally optimistic historical feasibility screen: a block--pass edge
requires 60 clear native cells, before the later canopy/background eligibility
checks can remove edges.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.colors import Normalize
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd
from pyproj import Transformer
import rasterio
from rasterio.features import geometry_mask, geometry_window
from rasterio.warp import transform_geom
from shapely import contains_xy
from shapely.geometry import box, mapping, shape

from urban_cooling_v2.step02_raster import (
    canonical_mgrs_core_bounds,
    partition_domain_for_mgrs_tile,
    select_latest_tile_revisions,
)


CITY_EPSG = {"phoenix": 32612, "los_angeles": 32611}
CITY_LABEL = {"phoenix": "Phoenix", "los_angeles": "Los Angeles"}
WINDOWS = {
    "phoenix": {
        "provisional_primary": ("05-15", "07-10"),
        "sensitivity": ("06-01", "09-30"),
    },
    "los_angeles": {
        "provisional_primary": ("06-01", "09-30"),
        "sensitivity": ("05-15", "07-10"),
    },
}
VIEW_SETS = (15, 25)
BLOCK_SIZE_M = 1000
MIN_CLEAR_CELLS = 60
PASSES_PER_BLOCK_FLOOR = 8
MIN_BLOCKS = 30
MIN_SECTORS = 3
MIN_LCC_SHARE = 0.80
MIN_MEDIAN_PASSES = 8.0

NLCD_LABELS = {
    11: "Open Water",
    12: "Perennial Ice/Snow",
    21: "Developed, Open Space",
    22: "Developed, Low Intensity",
    23: "Developed, Medium Intensity",
    24: "Developed, High Intensity",
    31: "Barren Land",
    41: "Deciduous Forest",
    42: "Evergreen Forest",
    43: "Mixed Forest",
    52: "Shrub/Scrub",
    71: "Grassland/Herbaceous",
    81: "Pasture/Hay",
    82: "Cultivated Crops",
    90: "Woody Wetlands",
    95: "Emergent Herbaceous Wetlands",
}


@dataclass(frozen=True)
class BlockGrid:
    city: str
    epsg: int
    origin_x: float
    origin_y: float
    ncols: int
    nrows: int
    urban_geometry: Any
    centroid_x: float
    centroid_y: float
    blocks: pd.DataFrame


def local_solar_date(acquisition_utc: Any, longitude_degrees: float) -> date:
    """Approximate local-solar date using longitude / 15 hours."""

    stamp = pd.Timestamp(acquisition_utc)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return (stamp + pd.to_timedelta(longitude_degrees / 15.0, unit="h")).date()


def month_day(value: date) -> str:
    return value.strftime("%m-%d")


def spatial_sector(x: float, y: float, center_x: float, center_y: float) -> str:
    north = y >= center_y
    east = x >= center_x
    return ("N" if north else "S") + ("E" if east else "W")


def select_candidate_passes(
    pass_rows: pd.DataFrame,
    *,
    city: str,
    longitude_degrees: float,
    season_window: str,
    view_zenith_maximum_degrees: float,
) -> pd.DataFrame:
    """Select distinct historical passes under the frozen D006 metadata rule."""

    required = {
        "city",
        "orbit",
        "acquisition_utc",
        "year",
        "quality_and_exact_weather_complete",
        "l1b_view_zenith_abs_p95_deg",
    }
    missing = sorted(required.difference(pass_rows.columns))
    if missing:
        raise ValueError(f"Pass table lacks columns: {missing}")
    if city not in WINDOWS or season_window not in WINDOWS[city]:
        raise ValueError(f"Unknown city/window combination: {city}/{season_window}")

    work = pass_rows.loc[pass_rows["city"].astype(str).eq(city)].copy()
    work["year"] = pd.to_numeric(work["year"], errors="coerce")
    work["l1b_view_zenith_abs_p95_deg"] = pd.to_numeric(
        work["l1b_view_zenith_abs_p95_deg"], errors="coerce"
    )
    quality = work["quality_and_exact_weather_complete"].astype(str).str.lower()
    work = work.loc[
        work["year"].between(2019, 2025)
        & quality.isin({"true", "1"})
        & work["l1b_view_zenith_abs_p95_deg"].le(
            float(view_zenith_maximum_degrees)
        )
    ].copy()
    work["orbit"] = work["orbit"].astype(str).str.replace(r"\.0$", "", regex=True)
    work["acquisition_utc"] = pd.to_datetime(work["acquisition_utc"], utc=True)
    # Rows repeat across the inherited threshold ladder.  The pass-level values
    # are identical; stable sorting makes the physical-pass de-duplication explicit.
    work = work.sort_values(
        ["orbit", "acquisition_utc", "l1b_view_zenith_abs_p95_deg"], kind="stable"
    ).drop_duplicates(["orbit"], keep="first")
    work["local_solar_date"] = [
        local_solar_date(ts, longitude_degrees) for ts in work["acquisition_utc"]
    ]
    work["month_day"] = work["local_solar_date"].map(month_day)
    start, end = WINDOWS[city][season_window]
    work = work.loc[work["month_day"].between(start, end)].copy()
    return work.sort_values(["local_solar_date", "orbit"], kind="stable").reset_index(
        drop=True
    )


def build_block_grid(domain_row: pd.Series, city: str) -> BlockGrid:
    epsg = CITY_EPSG[city]
    source = gpd.GeoSeries([domain_row.geometry], crs="EPSG:4326")
    urban = source.to_crs(epsg=epsg).iloc[0]
    minx, miny, maxx, maxy = urban.bounds
    origin_x = np.floor(minx / BLOCK_SIZE_M) * BLOCK_SIZE_M
    origin_y = np.floor(miny / BLOCK_SIZE_M) * BLOCK_SIZE_M
    ncols = int(np.ceil((maxx - origin_x) / BLOCK_SIZE_M))
    nrows = int(np.ceil((maxy - origin_y) / BLOCK_SIZE_M))
    cols = np.arange(ncols, dtype=int)
    rows = np.arange(nrows, dtype=int)
    cc, rr = np.meshgrid(cols, rows)
    xs = origin_x + (cc.ravel() + 0.5) * BLOCK_SIZE_M
    ys = origin_y + (rr.ravel() + 0.5) * BLOCK_SIZE_M
    keep = contains_xy(urban, xs, ys)
    cc = cc.ravel()[keep]
    rr = rr.ravel()[keep]
    xs = xs[keep]
    ys = ys[keep]
    keys = rr * ncols + cc
    center = urban.centroid
    blocks = pd.DataFrame(
        {
            "block_key": keys.astype(np.int64),
            "block_id": [f"{city}_r{r:04d}_c{c:04d}" for r, c in zip(rr, cc)],
            "grid_row": rr,
            "grid_col": cc,
            "center_x": xs,
            "center_y": ys,
            "sector": [spatial_sector(x, y, center.x, center.y) for x, y in zip(xs, ys)],
        }
    ).sort_values("block_key", kind="stable")
    return BlockGrid(
        city=city,
        epsg=epsg,
        origin_x=float(origin_x),
        origin_y=float(origin_y),
        ncols=ncols,
        nrows=nrows,
        urban_geometry=urban,
        centroid_x=float(center.x),
        centroid_y=float(center.y),
        blocks=blocks.reset_index(drop=True),
    )


def _domain_window(dataset: rasterio.io.DatasetReader, geometry_wgs84: Mapping[str, Any]):
    projected = transform_geom("EPSG:4326", dataset.crs, geometry_wgs84, precision=-1)
    clipped_geometry = shape(projected).intersection(box(*canonical_mgrs_core_bounds(dataset.bounds)))
    if clipped_geometry.is_empty:
        return None
    try:
        window = geometry_window(dataset, [mapping(clipped_geometry)])
    except Exception:
        return None
    domain = geometry_mask(
        [mapping(clipped_geometry)],
        out_shape=(int(window.height), int(window.width)),
        transform=dataset.window_transform(window),
        invert=True,
        all_touched=False,
    )
    return (window, domain) if domain.any() else None


def _coords_to_block_keys(
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
    if rasterio.crs.CRS.from_user_input(source_crs) != rasterio.crs.CRS.from_epsg(grid.epsg):
        transformer = Transformer.from_crs(source_crs, grid.epsg, always_xy=True)
        xs, ys = transformer.transform(xs, ys)
        xs = np.asarray(xs)
        ys = np.asarray(ys)
    cols = np.floor((xs - grid.origin_x) / BLOCK_SIZE_M).astype(np.int64)
    rows = np.floor((ys - grid.origin_y) / BLOCK_SIZE_M).astype(np.int64)
    inside = (cols >= 0) & (cols < grid.ncols) & (rows >= 0) & (rows < grid.nrows)
    return rows[inside] * grid.ncols + cols[inside]


def clear_cell_counts_for_pass(
    manifest_rows: pd.DataFrame,
    *,
    domain_geometry_wgs84: Mapping[str, Any],
    asset_root: str | Path,
    grid: BlockGrid,
) -> tuple[dict[int, int], dict[str, int]]:
    """Count clear, valid-view native cells in each retained 1 km block."""

    if manifest_rows.empty:
        raise ValueError("Selected pass has no cloud manifest rows")
    rows = select_latest_tile_revisions(manifest_rows.copy())
    rows = rows.loc[rows["asset_type"].astype(str).eq("cloud_cog")]
    root = Path(asset_root)
    valid_block_keys = set(grid.blocks["block_key"].astype(int))
    counts: Counter[int] = Counter()
    diagnostics = Counter()

    for tile, tile_rows in rows.groupby("tile", sort=True):
        tile_domain = partition_domain_for_mgrs_tile(domain_geometry_wgs84, str(tile))
        records = tile_rows.sort_values(
            ["scene", "selected_build", "selected_revision", "granule_id"], kind="stable"
        ).to_dict("records")
        first_view = root / "view_zenith_cog" / Path(str(records[0]["view_file_name"])).name
        if not first_view.is_file():
            raise FileNotFoundError(first_view)
        with rasterio.open(first_view) as reference:
            clipped = _domain_window(reference, tile_domain)
            if clipped is None:
                continue
            window, domain = clipped
            valid_view_any = np.zeros(domain.shape, dtype=bool)
            clear_any = np.zeros(domain.shape, dtype=bool)
            cloudy_any = np.zeros(domain.shape, dtype=bool)
            unexpected_any = np.zeros(domain.shape, dtype=bool)
            for record in records:
                view_path = root / "view_zenith_cog" / Path(str(record["view_file_name"])).name
                cloud_path = root / "cloud_cog" / Path(str(record["file_name"])).name
                if not view_path.is_file() or not cloud_path.is_file():
                    raise FileNotFoundError(view_path if not view_path.is_file() else cloud_path)
                with rasterio.open(view_path) as view_ds, rasterio.open(cloud_path) as cloud_ds:
                    for candidate in (view_ds, cloud_ds):
                        if (
                            candidate.crs != reference.crs
                            or candidate.transform != reference.transform
                            or candidate.width != reference.width
                            or candidate.height != reference.height
                        ):
                            raise ValueError("Cloud/view layers in one tile do not share a grid")
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
                valid_view_any |= valid_view
                clear_any |= observed & (cloud_data == 0)
                cloudy_any |= observed & (cloud_data == 1)
                unexpected_any |= cloud_unmasked & ~np.isin(cloud_data, (0, 1, 255))

            clear = domain & valid_view_any & clear_any & ~cloudy_any & ~unexpected_any
            keys = _coords_to_block_keys(
                clear, reference.window_transform(window), reference.crs, grid
            )
            if keys.size:
                unique, n = np.unique(keys, return_counts=True)
                for key, count in zip(unique, n):
                    if int(key) in valid_block_keys:
                        counts[int(key)] += int(count)
            diagnostics["tiles"] += 1
            diagnostics["domain_cells"] += int(domain.sum())
            diagnostics["clear_cells"] += int(clear.sum())
    return dict(counts), dict(diagnostics)


def assign_modal_land_cover(
    grid: BlockGrid, land_cover_path: str | Path
) -> pd.DataFrame:
    """Assign the modal Annual NLCD class inside the Census domain per block."""

    path = Path(land_cover_path)
    with rasterio.open(path) as ds:
        urban = transform_geom(
            f"EPSG:{grid.epsg}", ds.crs, mapping(grid.urban_geometry), precision=-1
        )
        window = geometry_window(ds, [urban])
        layer = ds.read(1, window=window, masked=True)
        transform = ds.window_transform(window)
        domain = geometry_mask(
            [urban],
            out_shape=(int(window.height), int(window.width)),
            transform=transform,
            invert=True,
            all_touched=False,
        )
        values = np.asarray(layer.filled(0), dtype=np.int16)
        valid = domain & ~np.ma.getmaskarray(layer) & (values > 0)
        keys = _coords_to_block_keys(valid, transform, ds.crs, grid)
        codes = values[valid]
        if keys.shape[0] != codes.shape[0]:
            raise ValueError("Land-cover coordinate and value arrays differ")

    allowed = set(grid.blocks["block_key"].astype(int))
    keep = np.fromiter((int(k) in allowed for k in keys), dtype=bool, count=len(keys))
    keys = keys[keep]
    codes = codes[keep]
    pair = keys.astype(np.int64) * 256 + codes.astype(np.int64)
    unique, counts = np.unique(pair, return_counts=True)
    modal: dict[int, tuple[int, int]] = {}
    for encoded, count in zip(unique, counts):
        key, code = divmod(int(encoded), 256)
        previous = modal.get(key)
        if previous is None or count > previous[1] or (count == previous[1] and code < previous[0]):
            modal[key] = (code, int(count))
    out = grid.blocks.copy()
    out["land_use_code"] = out["block_key"].map(lambda k: modal.get(int(k), (0, 0))[0])
    out["land_use_class"] = out["land_use_code"].map(NLCD_LABELS).fillna("Other/NoData")
    return out


def largest_component_edge_share(edges: Iterable[tuple[str, str]]) -> float:
    """Return the edge share of the largest bipartite connected component."""

    edge_list = list(edges)
    if not edge_list:
        return 0.0
    adjacency: dict[str, set[str]] = defaultdict(set)
    for block, pass_id in edge_list:
        bnode = f"b:{block}"
        pnode = f"p:{pass_id}"
        adjacency[bnode].add(pnode)
        adjacency[pnode].add(bnode)
    seen: set[str] = set()
    largest_edges = 0
    for start in sorted(adjacency):
        if start in seen:
            continue
        queue = deque([start])
        seen.add(start)
        degree_sum = 0
        while queue:
            node = queue.popleft()
            degree_sum += len(adjacency[node])
            for neighbor in adjacency[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        largest_edges = max(largest_edges, degree_sum // 2)
    return largest_edges / len(edge_list)


def summarize_combination(
    *,
    city: str,
    season_window: str,
    view_set: int,
    edges: pd.DataFrame,
    blocks: pd.DataFrame,
) -> dict[str, Any]:
    if edges.empty:
        counts = pd.Series(dtype=float)
        sectors: list[str] = []
        dominant_class = "NONE"
        dominant_share = 0.0
        lcc = 0.0
        eligible_passes = 0
    else:
        counts = edges.groupby("block_id").size().astype(float)
        eligible = blocks.loc[blocks["block_id"].isin(counts.index)].copy()
        sectors = sorted(eligible["sector"].astype(str).unique())
        edge_land = edges.merge(
            blocks[["block_id", "land_use_class"]], on="block_id", how="left", validate="many_to_one"
        )
        land_counts = edge_land["land_use_class"].fillna("Other/NoData").value_counts()
        dominant_class = str(land_counts.index[0])
        dominant_share = float(land_counts.iloc[0] / len(edge_land))
        lcc = largest_component_edge_share(zip(edges["block_id"], edges["pass_id"]))
        eligible_passes = int(edges["pass_id"].nunique())

    n_blocks = int(len(counts))
    median = float(counts.median()) if n_blocks else 0.0
    p10 = float(np.quantile(counts.to_numpy(), 0.10, method="linear")) if n_blocks else 0.0
    below = int((counts < PASSES_PER_BLOCK_FLOOR).sum()) if n_blocks else 0
    passed = bool(
        n_blocks >= MIN_BLOCKS
        and len(sectors) >= MIN_SECTORS
        and lcc >= MIN_LCC_SHARE
        and median >= MIN_MEDIAN_PASSES
    )
    return {
        "city": CITY_LABEL[city],
        "season_window": season_window,
        "view_zenith_set_deg": int(view_set),
        "eligible_blocks": n_blocks,
        "eligible_passes": eligible_passes,
        "block_passes": int(len(edges)),
        "median_passes_per_block": round(median, 3),
        "p10_passes_per_block": round(p10, 3),
        "blocks_below_floor": below,
        "largest_connected_component_share": round(lcc, 6),
        "spatial_sectors": len(sectors),
        "sectors_represented": ";".join(sectors),
        "dominant_land_use_class": dominant_class,
        "largest_share_one_land_use_class": round(dominant_share, 6),
        "combination_pass": passed,
    }


def validate_summary_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    if len(rows) != 8:
        raise ValueError(f"D1b must contain exactly eight combinations, found {len(rows)}")
    keys = {
        (row["city"], row["season_window"], int(row["view_zenith_set_deg"]))
        for row in rows
    }
    expected = {
        (CITY_LABEL[city], window, view)
        for city in WINDOWS
        for window in WINDOWS[city]
        for view in VIEW_SETS
    }
    if keys != expected:
        raise ValueError(f"D1b combination set mismatch: expected {expected}, found {keys}")
    for row in rows:
        if not 0 <= float(row["largest_connected_component_share"]) <= 1:
            raise ValueError("Largest-component share is outside [0, 1]")
        if not 0 <= int(row["spatial_sectors"]) <= 4:
            raise ValueError("Spatial-sector count is outside [0, 4]")
        if int(row["block_passes"]) < int(row["eligible_blocks"]):
            raise ValueError("Every eligible block must have at least one block-pass")
        if int(row["block_passes"]) < int(row["eligible_passes"]):
            raise ValueError("Every eligible pass must have at least one block-pass")


def plot_connectivity_map(
    block_details: pd.DataFrame,
    grids: Mapping[str, BlockGrid],
    output_png: str | Path,
    output_svg: str | Path,
) -> None:
    fig, axes = plt.subplots(2, 4, figsize=(14.5, 7.6), constrained_layout=True)
    columns = [("provisional_primary", 15), ("provisional_primary", 25), ("sensitivity", 15), ("sensitivity", 25)]
    vmax = max(1.0, float(block_details["pass_count"].max())) if not block_details.empty else 1.0
    norm = Normalize(vmin=1, vmax=vmax)
    cmap = plt.get_cmap("viridis")
    for i, city in enumerate(("phoenix", "los_angeles")):
        grid = grids[city]
        for j, (window, view) in enumerate(columns):
            ax = axes[i, j]
            panel = block_details.loc[
                block_details["city"].eq(city)
                & block_details["season_window"].eq(window)
                & block_details["view_zenith_set_deg"].eq(view)
                & block_details["pass_count"].gt(0)
            ]
            patches = [
                Rectangle(
                    (grid.origin_x + row.grid_col * BLOCK_SIZE_M, grid.origin_y + row.grid_row * BLOCK_SIZE_M),
                    BLOCK_SIZE_M,
                    BLOCK_SIZE_M,
                )
                for row in panel.itertuples()
            ]
            if patches:
                collection = PatchCollection(patches, cmap=cmap, norm=norm, linewidth=0)
                collection.set_array(panel["pass_count"].to_numpy(dtype=float))
                ax.add_collection(collection)
            boundary = grid.urban_geometry.boundary
            if boundary.geom_type == "MultiLineString":
                geoms = boundary.geoms
            else:
                geoms = [boundary]
            for geom in geoms:
                xy = np.asarray(geom.coords)
                ax.plot(xy[:, 0], xy[:, 1], color="#202020", linewidth=0.35)
            ax.set_aspect("equal")
            ax.autoscale_view()
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_title(f"{window.replace('_', ' ').title()} · ≤{view}°", fontsize=9)
            if j == 0:
                ax.set_ylabel(CITY_LABEL[city], fontsize=10, weight="bold")
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    fig.colorbar(sm, ax=axes, shrink=0.72, pad=0.01, label="Eligible passes per block")
    fig.suptitle("Historical nonthermal block–pass connectivity (1 km blocks)", fontsize=13, weight="bold")
    for path in (Path(output_png), Path(output_svg)):
        path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=300, bbox_inches="tight")
    fig.savefig(output_svg, bbox_inches="tight")
    plt.close(fig)


def plot_pass_histogram(
    block_details: pd.DataFrame, output_png: str | Path, output_svg: str | Path
) -> None:
    fig, axes = plt.subplots(2, 4, figsize=(14.5, 7.0), constrained_layout=True, sharey="row")
    columns = [("provisional_primary", 15), ("provisional_primary", 25), ("sensitivity", 15), ("sensitivity", 25)]
    for i, city in enumerate(("phoenix", "los_angeles")):
        for j, (window, view) in enumerate(columns):
            ax = axes[i, j]
            panel = block_details.loc[
                block_details["city"].eq(city)
                & block_details["season_window"].eq(window)
                & block_details["view_zenith_set_deg"].eq(view)
                & block_details["pass_count"].gt(0),
                "pass_count",
            ]
            upper = max(PASSES_PER_BLOCK_FLOOR + 1, int(panel.max()) + 1) if len(panel) else PASSES_PER_BLOCK_FLOOR + 1
            bins = np.arange(0.5, upper + 0.5, 1)
            ax.hist(panel, bins=bins, color="#277da1", edgecolor="white", linewidth=0.25)
            ax.axvline(PASSES_PER_BLOCK_FLOOR, color="#d1495b", linestyle="--", linewidth=1.1)
            ax.set_title(f"{window.replace('_', ' ').title()} · ≤{view}°", fontsize=9)
            ax.set_xlabel("Passes per eligible block", fontsize=8)
            if j == 0:
                ax.set_ylabel(f"{CITY_LABEL[city]}\nBlocks", fontsize=9, weight="bold")
            ax.tick_params(labelsize=7)
    fig.suptitle("Eligible pass-count distributions; red line = floor of 8", fontsize=13, weight="bold")
    for path in (Path(output_png), Path(output_svg)):
        path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=300, bbox_inches="tight")
    fig.savefig(output_svg, bbox_inches="tight")
    plt.close(fig)


__all__ = [
    "BlockGrid",
    "CITY_EPSG",
    "CITY_LABEL",
    "MIN_CLEAR_CELLS",
    "PASSES_PER_BLOCK_FLOOR",
    "VIEW_SETS",
    "WINDOWS",
    "assign_modal_land_cover",
    "build_block_grid",
    "clear_cell_counts_for_pass",
    "largest_component_edge_share",
    "local_solar_date",
    "plot_connectivity_map",
    "plot_pass_histogram",
    "select_candidate_passes",
    "spatial_sector",
    "summarize_combination",
    "validate_summary_rows",
]
