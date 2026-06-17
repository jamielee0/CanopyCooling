#!/usr/bin/env python3
"""LEVER EXPLORATION: ALTERNATIVE PAIRING UNITS for the thin Phoenix paired sample.

The block-group (BG) pairing unit yields only 9 paired BGs (one holding 171/195 tree
px). This script evaluates alternative "same local context" pairing units that could
use MORE of the data WITHOUT fabricating signal:

  (a) census TRACT-level pairing  (GEOID[:11] of the BG polygons)
  (b) fixed grid tiles            (500 m, 1 km, 2 km super-cells over the domain)
  (c) for reference: the current BG unit (re-derived) + a "whole-city" single-pool unit

CRITICAL METHOD NOTE
--------------------
The saved class raster (section10_pixel_class_70m.tif) already DEMOTED reference pixels
in BGs that had no tree pixel (and tree pixels in BGs that had no reference) to "other".
So it CANNOT be used to test alternative units (it is pre-filtered to the 9 BGs' result).
We therefore RE-DERIVE the *candidate* tree and reference masks from the analysis cube
using the EXACT operating thresholds + the same tall-building buffer (identical to
section10_classify_pixels.classify), then re-pair under each candidate unit. This is the
honest comparison: a tree px demoted under the BG unit may legitimately pair with a
reference px in the same tract or grid tile.

For EACH unit we compute:
  * n paired units (units containing >=1 tree AND >=1 reference candidate pixel)
  * tree-pixel coverage = (# tree candidates in a paired unit) / (total tree candidates)
  * reference-bottleneck check: how many tree candidates sit in a unit with a tree but
    NO reference (i.e. references are the limiting side), vs tree px simply isolated
  * concentration: max tree px in one unit / total (the pseudo-replication red flag)
  * # genuinely-independent spatial clusters of tree px (single-linkage at ~1 unit size)

Run (canopy env):
  conda run -n canopy python src/explore_pairing_units.py
Writes nothing; PRINTS a full report to stdout (the orchestrator reads stdout).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import rioxarray  # noqa: F401  (registers .rio)
import xarray as xr
from rasterio import features as rfeatures
from rasterio.transform import Affine

_SRC = Path(__file__).resolve().parent
_ROOT = _SRC.parent
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)
import config  # noqa: E402
import section10_classify_pixels as s10  # noqa: E402

ANALYSIS_ZARR = "analysis_cube_70m.zarr"
BG_PARQUET = "neighborhood_blockgroups_32612.parquet"


def _operating_params() -> dict:
    return s10.start_params()  # canopy at operating 40 %, all else pre-registered


def candidate_masks() -> dict:
    """Re-derive the tree & reference CANDIDATE masks exactly as Section 10 does.

    Returns a dict with the 2-D boolean tree/ref candidate masks (BEFORE any pairing),
    the building-buffer mask, the per-pixel BG index map, the BG lookup, and the y/x
    coordinate vectors. These candidate masks are what every unit re-pairs over -- they
    are NOT the demoted, BG-paired raster.
    """
    processed = config.PROCESSED_DIR
    interim = config.INTERIM_DIR
    inp = s10.load_inputs(processed)
    bg_index, lookup = s10.rasterize_blockgroups(interim)
    building_excluded, n_tall = s10.building_buffer_mask(
        interim, min_area_m2=config.TALL_BUILDING_MIN_AREA_M2, buffer_m=config.BUFFER_M)
    keep = ~building_excluded
    p = _operating_params()
    tree = s10.tree_mask(
        inp["ndvi"], inp["canopy"], inp["impervious"], inp["landcover"], inp["obs_count"],
        ndvi_thr=p["ndvi_thr"], canopy_thr=p["canopy_thr"], imperv_thr=p["imperv_thr"],
        min_obs=p["min_obs"], water_class=p["water_class"]) & keep
    ref = s10.reference_mask(
        inp["canopy"], inp["landcover"], inp["obs_count"],
        ref_canopy_max=p["ref_canopy_max"], built_classes=p["built_classes"],
        min_obs=p["min_obs"]) & keep
    return {
        "tree": tree, "ref": ref, "bg_index": bg_index, "lookup": lookup,
        "building_excluded": building_excluded, "n_tall": n_tall,
        "y": inp["y"], "x": inp["x"],
    }


def _bg_polys() -> "gpd.GeoDataFrame":
    bg = gpd.read_parquet(config.INTERIM_DIR / BG_PARQUET).reset_index(drop=True)
    if bg.crs is None or bg.crs.to_epsg() != 32612:
        bg = bg.to_crs(config.CRS)
    bg["GEOID"] = bg["GEOID"].astype(str)
    return bg


def unit_id_blockgroup(cm: dict) -> tuple[np.ndarray, dict]:
    """Per-pixel BG-GEOID unit id (the CURRENT unit; 0 = none). Returns (id_map, meta)."""
    bg_index = cm["bg_index"]
    lookup = cm["lookup"]
    # map bg_index (1-based) -> a small integer unit id; 0 stays 0.
    geoid_of = dict(zip(lookup["bg_index"].to_numpy(), lookup["GEOID"].to_numpy()))
    return bg_index.astype("int64"), {"name": "block_group",
                                       "id_to_label": {int(k): str(v) for k, v in geoid_of.items()}}


def unit_id_tract(cm: dict) -> tuple[np.ndarray, dict]:
    """Per-pixel census-TRACT unit id by rasterizing TRACT polygons (GEOID[:11]).

    Dissolve the BG polygons to tracts (first 11 GEOID digits), then rasterize by
    centroid containment exactly like the BG map (all_touched=False, 0 = none). A tract
    is ~4 BGs, so it is a strictly COARSER 'same local context' unit -- still a real
    census neighborhood, just larger.
    """
    bg = _bg_polys()
    bg["TRACT"] = bg["GEOID"].str[:11]
    tracts = bg.dissolve(by="TRACT", as_index=False)[["TRACT", "geometry"]]
    tracts = tracts.reset_index(drop=True)
    transform = Affine(*config.GRID_TRANSFORM)
    nrows, ncols = config.GRID_SHAPE
    shapes = ((geom, i + 1) for i, geom in enumerate(tracts.geometry))
    idx = rfeatures.rasterize(shapes=shapes, out_shape=(nrows, ncols),
                              transform=transform, fill=0, all_touched=False, dtype="int32")
    id_to_label = {i + 1: str(t) for i, t in enumerate(tracts["TRACT"].to_numpy())}
    return idx.astype("int64"), {"name": "tract", "id_to_label": id_to_label,
                                 "n_total_units": len(tracts)}


def unit_id_grid(cm: dict, tile_m: float) -> tuple[np.ndarray, dict]:
    """Per-pixel fixed-grid-tile unit id (tile_m x tile_m super-cells over the domain).

    Each 70 m pixel is assigned to the tile (i, j) = (floor((x-x0)/tile), floor((y0-y)/
    tile)) using the grid's own y/x centres -> a regular lattice of square super-cells.
    Tiles are LOCAL spatial context (a fixed-radius neighborhood) but, unlike census
    units, are NOT aligned to any socio-administrative boundary. Only tiles that actually
    contain >=1 candidate pixel get a nonzero id (so n_total_units counts occupied tiles).
    """
    y = cm["y"]; x = cm["x"]
    ny, nx = len(y), len(x)
    # tile index per axis from the pixel-centre coordinates.
    x0 = float(config.GRID_BOUNDS[0]); ytop = float(config.GRID_BOUNDS[3])
    col_tile = np.floor((x - x0) / tile_m).astype("int64")            # length nx
    row_tile = np.floor((ytop - y) / tile_m).astype("int64")          # length ny
    nct = int(col_tile.max()) + 1
    # composite tile id per pixel = row_tile * nct + col_tile  (+1 so 0 reserved=none)
    tile2d = (row_tile[:, None] * nct + col_tile[None, :]) + 1        # (ny, nx)
    return tile2d.astype("int64"), {"name": f"grid_{int(tile_m)}m", "tile_m": tile_m}


def unit_id_city(cm: dict) -> tuple[np.ndarray, dict]:
    """Single whole-domain unit (id 1 everywhere). The 'no local control' extreme.

    This is the maximal-data, minimal-confounding-control option: every tree px pairs
    against every reference px city-wide. Included as a reference bound, NOT recommended
    (it discards the same-overpass-SAME-PLACE control that the paired design exists for).
    """
    nrows, ncols = config.GRID_SHAPE
    return np.ones((nrows, ncols), dtype="int64"), {"name": "whole_city"}


def evaluate_unit(unit2d: np.ndarray, cm: dict, meta: dict) -> dict:
    """Compute the paired-unit / coverage / bottleneck / concentration metrics.

    A unit is PAIRED iff it holds >=1 tree candidate AND >=1 reference candidate. Tree
    coverage = tree candidates in a paired unit / total tree candidates. Reference is the
    BOTTLENECK for the tree px that are in a unit holding tree(s) but NO reference. We
    also separate units with id==0 (no unit -> never pairable) so the failure mode is
    explicit. Concentration = the single most tree-px-heavy paired unit's share.
    """
    tree = cm["tree"]; ref = cm["ref"]
    tr, tc = np.where(tree)
    rr, rc = np.where(ref)
    n_tree = tr.size
    n_ref = rr.size

    tree_unit = unit2d[tr, tc]
    ref_unit = unit2d[rr, rc]

    # units (excluding id 0 = no unit) with each kind of px.
    tree_units = pd.Series(tree_unit[tree_unit != 0]).value_counts()
    ref_units = pd.Series(ref_unit[ref_unit != 0]).value_counts()
    units_with_tree = set(tree_units.index.tolist())
    units_with_ref = set(ref_units.index.tolist())
    paired_units = sorted(units_with_tree & units_with_ref)
    n_paired_units = len(paired_units)

    # tree px coverage: tree px whose unit is a paired unit.
    paired_set = set(paired_units)
    tree_in_paired = np.array([u in paired_set for u in tree_unit])
    n_tree_in_paired = int(tree_in_paired.sum())
    tree_coverage = n_tree_in_paired / n_tree if n_tree else float("nan")

    # WHY are the rest excluded?  (a) tree px with unit id 0 (no unit) ; (b) tree px in a
    # unit that has tree(s) but NO reference (REFERENCE is the bottleneck) ; (c) (cannot
    # happen) tree px with no tree in unit.
    tree_no_unit = int((tree_unit == 0).sum())
    # tree px in a tree-bearing unit that lacks a reference:
    units_tree_no_ref = units_with_tree - units_with_ref
    tree_ref_bottleneck = int(sum(int(tree_units.get(u, 0)) for u in units_tree_no_ref))
    # sanity: coverage + no_unit + bottleneck == n_tree
    assert n_tree_in_paired + tree_no_unit + tree_ref_bottleneck == n_tree, (
        n_tree_in_paired, tree_no_unit, tree_ref_bottleneck, n_tree)

    # reference coverage (is reference ever globally scarce?) -- ref px in a paired unit.
    ref_in_paired = np.array([u in paired_set for u in ref_unit])
    n_ref_in_paired = int(ref_in_paired.sum())

    # concentration / pseudo-replication: per-paired-unit tree counts.
    per_unit_tree = np.array([int(tree_units.get(u, 0)) for u in paired_units], dtype=int)
    per_unit_ref = np.array([int(ref_units.get(u, 0)) for u in paired_units], dtype=int)
    if per_unit_tree.size:
        max_share = float(per_unit_tree.max()) / n_tree
        # units needed to cover 80% of tree px (more units => less concentrated).
        s = np.sort(per_unit_tree)[::-1]
        csum = np.cumsum(s)
        units_for_80 = int(np.searchsorted(csum, 0.8 * n_tree) + 1)
        # paired units with >=2 tree px AND >=2 ref px (the rows that carry a real
        # within-unit difference, not a 1-vs-1 noisy pair).
        n_units_ge2 = int(((per_unit_tree >= 2) & (per_unit_ref >= 2)).sum())
        # effective number of units by tree px (inverse Simpson on the tree-px shares):
        p_share = per_unit_tree / per_unit_tree.sum()
        eff_units = float(1.0 / np.sum(p_share ** 2))
    else:
        max_share = float("nan"); units_for_80 = 0; n_units_ge2 = 0; eff_units = 0.0

    return {
        "unit": meta["name"],
        "n_total_occupied_units": int(len(set(unit2d[unit2d != 0].ravel().tolist()))
                                      if unit2d.size < 5_000_000 else
                                      len(np.unique(unit2d[unit2d != 0]))),
        "n_tree_candidates": n_tree,
        "n_ref_candidates": n_ref,
        "n_paired_units": n_paired_units,
        "tree_px_in_paired_units": n_tree_in_paired,
        "tree_coverage_frac": round(tree_coverage, 4),
        "ref_px_in_paired_units": n_ref_in_paired,
        "tree_px_no_unit": tree_no_unit,
        "tree_px_ref_bottleneck": tree_ref_bottleneck,
        "max_unit_tree_share": round(max_share, 4),
        "paired_units_for_80pct_tree": units_for_80,
        "n_paired_units_ge2tree_ge2ref": n_units_ge2,
        "effective_units_invsimpson": round(eff_units, 2),
        "per_unit_tree_counts": per_unit_tree.tolist(),
        "per_unit_ref_counts": per_unit_ref.tolist(),
    }


def spatial_clusters(cm: dict, link_dist_m: float) -> dict:
    """Count genuinely-independent spatial clusters of TREE candidate pixels.

    Single-linkage (connected components) on tree px whose pairwise distance <=
    link_dist_m groups physically-adjacent tree px into one cluster. This is the
    pseudo-replication denominator: many tree px that are all neighbours are ~1
    independent unit, not N. We report it at a few linkage distances (140 m = 2 px,
    500 m, 1 km) so the true independent-unit count is visible regardless of unit choice.
    """
    tr, tc = np.where(cm["tree"])
    if tr.size == 0:
        return {}
    xs = cm["x"][tc]; ys = cm["y"][tr]
    pts = np.column_stack([xs, ys])
    try:
        from scipy.sparse.csgraph import connected_components
        from scipy.spatial import cKDTree
        tree = cKDTree(pts)
        pairs = tree.query_pairs(r=link_dist_m, output_type="ndarray")
        n = pts.shape[0]
        from scipy.sparse import coo_matrix
        if pairs.size:
            data = np.ones(pairs.shape[0])
            adj = coo_matrix((data, (pairs[:, 0], pairs[:, 1])), shape=(n, n))
            ncomp, labels = connected_components(adj, directed=False)
        else:
            ncomp = n; labels = np.arange(n)
        sizes = pd.Series(labels).value_counts().to_numpy()
        return {"link_dist_m": link_dist_m, "n_tree_px": int(n),
                "n_clusters": int(ncomp), "largest_cluster_px": int(sizes.max()),
                "largest_cluster_share": round(float(sizes.max()) / n, 4)}
    except Exception as exc:  # noqa: BLE001
        return {"link_dist_m": link_dist_m, "error": str(exc)}


def main() -> int:
    print("=" * 78)
    print("ALTERNATIVE PAIRING-UNIT EXPLORATION (Phoenix; candidate masks re-derived)")
    print("=" * 78)
    cm = candidate_masks()
    n_tree = int(cm["tree"].sum()); n_ref = int(cm["ref"].sum())
    print(f"Re-derived CANDIDATE masks at operating thresholds "
          f"(NDVI>{config.NDVI_THR}, canopy>{config.CANOPY_THR}%, imperv<{config.IMPERV_THR}%, "
          f"obs>={config.MIN_OBS}, ref canopy<{config.REF_CANOPY_MAX}%, built only):")
    print(f"  tree candidates      = {n_tree}")
    print(f"  reference candidates = {n_ref}")
    print(f"  (NB: the saved class raster's 195 tree / 6019 ref are the BG-PAIRED SUBSET; "
          f"candidates are the un-demoted pool.)")
    print()

    results = []
    # (a) block group (current) ; (b) tract ; (c) grid tiles ; + whole-city bound.
    bg2d, bg_meta = unit_id_blockgroup(cm)
    results.append(evaluate_unit(bg2d, cm, bg_meta))

    tr2d, tr_meta = unit_id_tract(cm)
    res_tract = evaluate_unit(tr2d, cm, tr_meta)
    res_tract["n_total_units_in_domain"] = tr_meta.get("n_total_units")
    results.append(res_tract)

    for tile_m in (500.0, 1000.0, 2000.0):
        g2d, g_meta = unit_id_grid(cm, tile_m)
        results.append(evaluate_unit(g2d, cm, g_meta))

    city2d, city_meta = unit_id_city(cm)
    results.append(evaluate_unit(city2d, cm, city_meta))

    df = pd.DataFrame(results)
    show_cols = ["unit", "n_paired_units", "tree_px_in_paired_units", "tree_coverage_frac",
                 "ref_px_in_paired_units", "tree_px_no_unit", "tree_px_ref_bottleneck",
                 "max_unit_tree_share", "n_paired_units_ge2tree_ge2ref",
                 "effective_units_invsimpson", "paired_units_for_80pct_tree"]
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 40)
    print("PER-UNIT METRICS")
    print(df[show_cols].to_string(index=False))
    print()
    print("PER-UNIT tree-px counts (the concentration detail):")
    for r in results:
        print(f"  {r['unit']:<12}: tree per paired unit = {r['per_unit_tree_counts']}")
    print()

    print("PSEUDO-REPLICATION: independent spatial clusters of TREE candidate px")
    clus = []
    for d in (140.0, 500.0, 1000.0):
        c = spatial_clusters(cm, d)
        clus.append(c)
        if c:
            print(f"  link<= {int(c['link_dist_m']):>4} m : {c['n_clusters']:>3} clusters "
                  f"of {c['n_tree_px']} tree px ; largest = {c['largest_cluster_px']} px "
                  f"({100*c['largest_cluster_share']:.1f}%)")
    print()

    # machine-readable block for the orchestrator.
    print("JSON_RESULTS_BEGIN")
    print(json.dumps({"candidates": {"n_tree": n_tree, "n_ref": n_ref},
                      "units": results, "clusters": clus}, default=str))
    print("JSON_RESULTS_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
