#!/usr/bin/env python3
"""Section 16 (REASON #2 FIX) - PIXEL-LEVEL LOCAL PAIRING + spatial-cluster
re-aggregation, to ENLARGE and STRENGTHEN the thin Phoenix paired sample WITHOUT
fabricating signal.

Why this exists (the reason-#2 diagnosis)
-----------------------------------------
Section 14 found NO ROBUST THRESHOLD. The temporal-NDMI re-run (reason #1) tripled
the between-BG CSI spread yet the null PERSISTED, isolating the THIN, SPATIALLY-
CLUSTERED paired sample as the binding limitation: the BG-level master_table.parquet
has 264 rows (9 paired BGs x 54 overpasses), median n_good_obs = 2, and ONE block
group (040139412001) holds ~88 % of the tree pixels. Aggregating to the BG threw away
the x-axis support.

This module dissolves the BG-aggregation step (LEVER 1 + LEVER 2 + LEVER 4):
  * RE-DERIVE candidate tree + reference masks at the RELAXED pixel-design operating
    point (config.CANOPY_THR_PIXEL = 30, config.MIN_OBS_PIXEL = 15; all OTHER Section
    10 gates unchanged), NOT the saved section10_pixel_class_70m.tif (which already
    demoted references in tree-less BGs). This is exactly explore_pairing_units.py's
    honest re-derivation, reused.
  * LABEL queen (8-conn) / rook (4-conn) connected components of the tree class
    (scipy.ndimage.label) as the SPATIAL CLUSTERS -- the genuinely-independent unit.
  * For each tree pixel t and each overpass o with finite LST_t(o):
        cooling_advantage_px(t, o) = mean(LST_ref within radius R of t at o) - LST_t(o)
    with the references found by a KDTree on the reference-pixel coordinates (LEVER 1;
    primary R = 350 m, sweep {210, 350, 500}). The SAME-overpass differencing cancels
    weather + time-of-day exactly, per tree pixel.
  * Attach each tree pixel's mean_csi_tree (= csi at the pixel), vpd_z, ndmi_z, et, esi
    (from Section 11/12/9 stores) and its cluster_id + BG GEOID.
  * RE-AGGREGATE the pixel-overpass rows to a CLUSTER-overpass table (count-weighted
    cooling advantage) -- the PRIMARY modeling input for the clustering-aware threshold
    analysis (section16_threshold_pixel.py). The pixel-overpass count is reported but is
    NEVER the inference df (pseudo-replication guard).

NON-DESTRUCTIVE: reads only the analysis cube / CSI / z-score stores + the BG polygons;
writes ONLY the NEW deliverables:
  * data/processed/section16_pixel_class_pixel_70m.tif  -- relaxed candidate class raster
  * data/processed/section16_pixel_clusters.parquet     -- per-tree-pixel cluster table
  * data/processed/master_table_pixel.parquet           -- pixel-overpass paired table
  * data/processed/master_table_cluster.parquet         -- cluster-overpass modeling table
It does NOT touch master_table.parquet or section10_pixel_class_70m.tif.

Run (canopy env):
  conda run -n canopy python src/section16_pixel_pairing.py            # primary R + sweep
  conda run -n canopy python src/section16_pixel_pairing.py --no-sweep  # primary R only
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SRC = Path(__file__).resolve().parent
_ROOT = _SRC.parent
for _p in (str(_ROOT), str(_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import config  # noqa: E402

log = logging.getLogger("section16_pairing")

# Source stores (read-only).
ANALYSIS_ZARR = "analysis_cube_70m.zarr"
CSI_ZARR = "section12_csi_70m.zarr"
ZSCORE_ZARR = "section11_zscores_70m.zarr"
BG_PARQUET = "neighborhood_blockgroups_32612.parquet"

# NEW deliverables (data/processed/).
PIXEL_CLASS_TIF = "section16_pixel_class_pixel_70m.tif"
CLUSTERS_PARQUET = "section16_pixel_clusters.parquet"
MASTER_PIXEL_PARQUET = "master_table_pixel.parquet"
MASTER_CLUSTER_PARQUET = "master_table_cluster.parquet"

# Class codebook (same convention as Section 10).
CLASS_OTHER = 0
CLASS_TREE = 1
CLASS_REFERENCE = 2

# The dominant block group (Section 10/15): one BG carries ~88 % of tree px at canopy40
# and ~75 % at canopy30. Named for the mandatory leave-dominant-out falsification.
DOMINANT_BG_GEOID = "040139412001"


# =========================================================================== #
# Pure logic (numpy / scipy.ndimage only; unit-tested WITHOUT the geo IO stack)
# =========================================================================== #
def adjacency_structure(connectivity: str) -> np.ndarray:
    """The 3x3 ndimage structuring element for 'queen' (8-conn) or 'rook' (4-conn).

    'queen'/8-connectivity counts diagonal neighbours as connected (the PRIMARY unit
    -- a touching diagonal canopy cell is the same patch); 'rook'/4-connectivity counts
    only edge neighbours (the conservative sensitivity). Raises on any other value.
    """
    c = str(connectivity).lower()
    if c == "queen":
        return np.ones((3, 3), dtype=int)
    if c == "rook":
        return np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=int)
    raise ValueError(f"connectivity must be 'queen' or 'rook', got {connectivity!r}")


def label_clusters(tree_mask: np.ndarray, connectivity: str = "queen"
                   ) -> tuple[np.ndarray, int]:
    """Label connected components of the boolean tree mask -> (label_map, n_clusters).

    Labels are 1..n_clusters inside the tree mask, 0 elsewhere (scipy.ndimage.label
    convention). These connected components are the genuinely-independent SPATIAL UNITS:
    a contiguous riparian/peri-urban canopy patch is ONE cluster, not its pixel count.
    """
    from scipy import ndimage
    labels, n = ndimage.label(np.asarray(tree_mask, dtype=bool),
                              structure=adjacency_structure(connectivity))
    return labels.astype("int64"), int(n)


def local_reference_pairing(tree_rc: np.ndarray, ref_rc: np.ndarray, *,
                            radius_m: float, cell_size_m: float
                            ) -> tuple[list[np.ndarray], np.ndarray]:
    """For each tree pixel, the indices of reference pixels within ``radius_m`` (LEVER 1).

    Works in GRID-CELL space (row, col): the Euclidean radius in metres is converted to
    a cell radius (radius_m / cell_size_m) and a KDTree on the reference-pixel (row, col)
    coordinates is queried per tree pixel. Returns ``(neighbor_lists, n_ref_in_R)`` where
    ``neighbor_lists[i]`` is an int array of indices INTO ``ref_rc`` for tree pixel i, and
    ``n_ref_in_R[i]`` is its count. A tree pixel with no reference within R has an empty
    list and count 0 (it yields no paired observation). Pure: no IO, deterministic.

    ``tree_rc`` / ``ref_rc`` are (N, 2) int arrays of (row, col). The 70 m grid is a
    regular lattice, so cell-space Euclidean distance == metric distance / cell_size.
    """
    tree_rc = np.asarray(tree_rc, dtype="float64")
    ref_rc = np.asarray(ref_rc, dtype="float64")
    n_tree = tree_rc.shape[0]
    if n_tree == 0 or ref_rc.shape[0] == 0:
        return [np.array([], dtype="int64") for _ in range(n_tree)], np.zeros(n_tree, dtype="int64")
    from scipy.spatial import cKDTree
    radius_cells = float(radius_m) / float(cell_size_m)
    kdt = cKDTree(ref_rc)
    # query_ball_point returns, per tree pixel, the list of ref indices within the radius.
    neighbor_lists = kdt.query_ball_point(tree_rc, r=radius_cells)
    out = [np.asarray(sorted(nl), dtype="int64") for nl in neighbor_lists]
    n_ref_in_R = np.array([a.size for a in out], dtype="int64")
    return out, n_ref_in_R


def cooling_advantage_px(lst_tree: float, ref_lst_values: np.ndarray) -> tuple[float, int]:
    """cooling_advantage_px = mean(finite local reference LST) - tree-pixel LST (LEVER 1).

    ``ref_lst_values`` are the LST of the tree pixel's local reference pixels on THIS
    overpass; only FINITE references enter the mean (a reference with no LST that overpass
    is dropped). Returns ``(cooling_advantage, n_ref_finite)``; NaN/0 if the tree LST is
    non-finite or no local reference is finite. Positive => the tree pixel is COOLER than
    its local built surroundings. Same-overpass differencing cancels weather/time-of-day.
    """
    if not np.isfinite(lst_tree):
        return float("nan"), 0
    vals = np.asarray(ref_lst_values, dtype="float64")
    fin = np.isfinite(vals)
    n = int(fin.sum())
    if n == 0:
        return float("nan"), 0
    return float(vals[fin].mean()) - float(lst_tree), n


def count_weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    """Count-weighted mean over finite (value, weight) pairs; NaN if no finite weight.

    Used to collapse a cluster's member tree-pixel cooling advantages to ONE cluster-
    overpass value (weighting each pixel by the number of finite local references behind
    its difference, so a 1-reference pixel does not count the same as a 30-reference one).
    Pairs with a non-finite value or non-positive/NaN weight are dropped.
    """
    v = np.asarray(values, dtype="float64")
    w = np.asarray(weights, dtype="float64")
    ok = np.isfinite(v) & np.isfinite(w) & (w > 0)
    if not ok.any():
        return float("nan")
    return float(np.sum(v[ok] * w[ok]) / np.sum(w[ok]))


# =========================================================================== #
# Geo / IO layer
# =========================================================================== #
def _operating_params_pixel() -> dict:
    """Section 10 thresholds with canopy/min_obs at the RELAXED pixel-design floor.

    Reuses section10_classify_pixels.start_params() (so the reference rule, NDVI,
    impervious, water, built classes, tall-building buffer are IDENTICAL to Section 10),
    then overrides ONLY canopy_thr -> config.CANOPY_THR_PIXEL (30) and min_obs ->
    config.MIN_OBS_PIXEL (15). The BG-pipeline config.CANOPY_THR/MIN_OBS are not used.
    """
    import section10_classify_pixels as s10
    p = s10.start_params()
    p["canopy_thr"] = float(config.CANOPY_THR_PIXEL)
    p["min_obs"] = int(config.MIN_OBS_PIXEL)
    return p


def candidate_masks() -> dict:
    """Re-derive tree + reference CANDIDATE masks at the relaxed pixel-design thresholds.

    Mirrors explore_pairing_units.candidate_masks() but at canopy30 / min_obs15. Returns
    the 2-D boolean tree/ref candidate masks (BEFORE pairing), the building-buffer mask,
    the per-pixel BG index map + lookup, and the y/x coordinate vectors. The candidate
    masks are the un-demoted pool that local pairing operates over (NOT the saved raster).
    """
    import section10_classify_pixels as s10
    processed = config.PROCESSED_DIR
    interim = config.INTERIM_DIR
    inp = s10.load_inputs(processed)
    bg_index, lookup = s10.rasterize_blockgroups(interim)
    building_excluded, n_tall = s10.building_buffer_mask(
        interim, min_area_m2=config.TALL_BUILDING_MIN_AREA_M2, buffer_m=config.BUFFER_M)
    keep = ~building_excluded
    p = _operating_params_pixel()
    tree = s10.tree_mask(
        inp["ndvi"], inp["canopy"], inp["impervious"], inp["landcover"], inp["obs_count"],
        ndvi_thr=p["ndvi_thr"], canopy_thr=p["canopy_thr"], imperv_thr=p["imperv_thr"],
        min_obs=p["min_obs"], water_class=p["water_class"]) & keep
    ref = s10.reference_mask(
        inp["canopy"], inp["landcover"], inp["obs_count"],
        ref_canopy_max=p["ref_canopy_max"], built_classes=p["built_classes"],
        min_obs=p["min_obs"]) & keep
    log.info("Relaxed candidate masks (canopy>%.0f%%, NDVI>%.2f, imperv<%.0f%%, obs>=%d, "
             "ref canopy<%.0f%%, built only): tree=%d  ref=%d",
             p["canopy_thr"], p["ndvi_thr"], p["imperv_thr"], p["min_obs"],
             p["ref_canopy_max"], int(tree.sum()), int(ref.sum()))
    return {"tree": tree, "ref": ref, "bg_index": bg_index, "lookup": lookup,
            "building_excluded": building_excluded, "n_tall": n_tall,
            "y": inp["y"], "x": inp["x"]}


def load_overpass_layers() -> dict:
    """Load the per-overpass LST / CSI / vpd_z / ndmi_z / ET / ESI / PDSI stacks.

    Reads the Section 9 cube (lst/et/esi/pdsi + time/overpass_key), the Section 12 CSI
    store (csi), and the Section 11 z-score store (vpd_z/ndmi_z). The three stores share
    the 66-overpass axis + order (asserted, exactly as Section 13), so they are indexed
    positionally. Returns numpy stacks (overpass, y, x) + the overpass coords.
    """
    import rioxarray  # noqa: F401  (registers .rio)
    import xarray as xr
    processed = config.PROCESSED_DIR
    cube = xr.open_zarr(processed / ANALYSIS_ZARR, decode_coords="all")
    csi_ds = xr.open_zarr(processed / CSI_ZARR, decode_coords="all")
    z_ds = xr.open_zarr(processed / ZSCORE_ZARR, decode_coords="all")
    ck = np.array([str(k) for k in cube["overpass_key"].values])
    sk = np.array([str(k) for k in csi_ds["overpass_key"].values])
    zk = np.array([str(k) for k in z_ds["overpass_key"].values])
    assert np.array_equal(ck, sk), "CSI overpass_key order != cube"
    assert np.array_equal(ck, zk), "z-score overpass_key order != cube"
    out = {
        "lst": cube["lst"].values.astype("float32"),
        "et": cube["et"].values.astype("float32"),
        "esi": cube["esi"].values.astype("float32"),
        "pdsi": cube["pdsi"].values.astype("float32"),
        "csi": csi_ds["csi"].values.astype("float32"),
        "vpd_z": z_ds["vpd_z"].values.astype("float32"),
        "ndmi_z": z_ds["ndmi_z"].values.astype("float32"),
        "time": pd.to_datetime(cube["time"].values),
        "overpass_key": ck,
        "n_overpass": int(cube.sizes["overpass"]),
    }
    cube.close(); csi_ds.close(); z_ds.close()
    log.info("Loaded %d overpasses (lst/csi/vpd_z/ndmi_z + et/esi/pdsi)", out["n_overpass"])
    return out


def build_cluster_table(cm: dict, connectivity: str) -> pd.DataFrame:
    """Per-tree-pixel cluster table: (row, col, x, y, cluster_id, GEOID, obs unused here).

    Labels the tree-candidate mask into queen/rook clusters and assigns each tree pixel
    its cluster_id and its containing BG GEOID (via the same per-pixel BG index map used
    everywhere). Returns one row per tree-candidate pixel. obs_count is added by the
    caller (it needs the LST stack); kept out here so this stays cheap + testable.
    """
    tree = cm["tree"]
    labels, n_clusters = label_clusters(tree, connectivity)
    tr, tc = np.where(tree)
    cluster_id = labels[tr, tc]
    bg_idx = cm["bg_index"][tr, tc]
    geoid_of = dict(zip(cm["lookup"]["bg_index"].to_numpy(), cm["lookup"]["GEOID"].to_numpy()))
    geoid = np.array([str(geoid_of.get(int(b), "0")) for b in bg_idx])
    df = pd.DataFrame({
        "tree_row": tr.astype("int64"),
        "tree_col": tc.astype("int64"),
        "x": cm["x"][tc].astype("float64"),
        "y": cm["y"][tr].astype("float64"),
        "cluster_id": cluster_id.astype("int64"),
        "GEOID": geoid,
    })
    df.attrs["n_clusters"] = n_clusters
    df.attrs["connectivity"] = connectivity
    return df


def compute_pixel_pairs(cm: dict, layers: dict, clusters: pd.DataFrame, *,
                        radius_m: float) -> pd.DataFrame:
    """The pixel-overpass paired table for one radius R (Step 4).

    For each tree pixel and each overpass with finite tree LST, computes
    cooling_advantage_px = mean(finite local reference LST within R) - tree LST, and
    attaches the tree-pixel CSI / vpd_z / ndmi_z / ET / ESI / PDSI on that overpass, plus
    its cluster_id + GEOID + R. Vectorised across tree pixels per overpass via the
    precomputed KDTree neighbour lookup. Returns the long DataFrame (one row per emitted
    tree-pixel-overpass cell).
    """
    tr = clusters["tree_row"].to_numpy()
    tc = clusters["tree_col"].to_numpy()
    cid = clusters["cluster_id"].to_numpy()
    geoid = clusters["GEOID"].to_numpy()
    tree_rc = np.column_stack([tr, tc])

    rr, rc = np.where(cm["ref"])
    ref_rc = np.column_stack([rr, rc])
    neighbor_lists, n_ref_in_R = local_reference_pairing(
        tree_rc, ref_rc, radius_m=radius_m, cell_size_m=config.CELL_SIZE_M)

    lst = layers["lst"]; csi = layers["csi"]
    vpd_z = layers["vpd_z"]; ndmi_z = layers["ndmi_z"]
    et = layers["et"]; esi = layers["esi"]; pdsi = layers["pdsi"]
    times = layers["time"]; keys = layers["overpass_key"]
    n_op = layers["n_overpass"]
    n_tree = tree_rc.shape[0]

    rows: list[dict] = []
    for o in range(n_op):
        lst_o = lst[o]
        ref_lst_o = lst_o[rr, rc]               # length = n_ref candidates
        tree_lst_o = lst_o[tr, tc]              # length = n_tree
        csi_o = csi[o][tr, tc]
        vpd_o = vpd_z[o][tr, tc]
        ndmi_o = ndmi_z[o][tr, tc]
        et_o = et[o][tr, tc]
        esi_o = esi[o][tr, tc]
        pdsi_o = pdsi[o][tr, tc]
        for i in range(n_tree):
            lst_t = float(tree_lst_o[i])
            if not np.isfinite(lst_t):
                continue
            nl = neighbor_lists[i]
            if nl.size == 0:
                continue
            ca, n_ref_fin = cooling_advantage_px(lst_t, ref_lst_o[nl])
            if not np.isfinite(ca):
                continue
            rows.append({
                "tree_row": int(tr[i]), "tree_col": int(tc[i]),
                "cluster_id": int(cid[i]), "GEOID": str(geoid[i]),
                "overpass_index": int(o), "overpass_key": str(keys[o]),
                "overpass_timestamp": times[o],
                "lst_tree": lst_t,
                "ref_mean": lst_t + ca,         # = mean(finite local ref LST)
                "n_ref_in_R": int(n_ref_in_R[i]),
                "n_ref_finite": int(n_ref_fin),
                "cooling_advantage_px": ca,
                "mean_csi_tree": float(csi_o[i]) if np.isfinite(csi_o[i]) else np.nan,
                "vpd_z": float(vpd_o[i]) if np.isfinite(vpd_o[i]) else np.nan,
                "ndmi_z": float(ndmi_o[i]) if np.isfinite(ndmi_o[i]) else np.nan,
                "mean_et_tree": float(et_o[i]) if np.isfinite(et_o[i]) else np.nan,
                "mean_esi_tree": float(esi_o[i]) if np.isfinite(esi_o[i]) else np.nan,
                "pdsi": float(pdsi_o[i]) if np.isfinite(pdsi_o[i]) else np.nan,
                "R_m": float(radius_m),
            })
    df = pd.DataFrame(rows, columns=PIXEL_COLUMNS)
    log.info("R=%.0fm: %d tree-px-overpass paired rows from %d tree px x %d overpasses "
             "(reachable tree px: %d/%d have >=1 ref within R)",
             radius_m, len(df), n_tree, n_op, int((n_ref_in_R > 0).sum()), n_tree)
    return df


PIXEL_COLUMNS = [
    "tree_row", "tree_col", "cluster_id", "GEOID",
    "overpass_index", "overpass_key", "overpass_timestamp",
    "lst_tree", "ref_mean", "n_ref_in_R", "n_ref_finite", "cooling_advantage_px",
    "mean_csi_tree", "vpd_z", "ndmi_z", "mean_et_tree", "mean_esi_tree", "pdsi", "R_m",
]


def aggregate_to_clusters(pixel_df: pd.DataFrame) -> pd.DataFrame:
    """Collapse the pixel-overpass table to a CLUSTER-overpass table (Step 5; PRIMARY input).

    For each (cluster_id, overpass) group: the COUNT-WEIGHTED mean cooling advantage over
    member tree pixels (weight = n_ref_finite behind each pixel's difference), the mean
    tree-pixel CSI / vpd_z / ndmi_z / ET / ESI / PDSI, the number of valid tree pixels,
    and the summed local references. cluster_id maps 1:1 to a GEOID (a connected component
    lies in one BG, except the rare straddler -> the modal GEOID is used). R_m is carried.
    Returns the cluster-overpass DataFrame (the regression rows).
    """
    if pixel_df.empty:
        return pd.DataFrame(columns=CLUSTER_COLUMNS)
    out_rows: list[dict] = []
    for (cid, o), grp in pixel_df.groupby(["cluster_id", "overpass_index"], sort=True):
        ca = count_weighted_mean(grp["cooling_advantage_px"].to_numpy(),
                                 grp["n_ref_finite"].to_numpy())
        geoid_mode = grp["GEOID"].mode()
        out_rows.append({
            "cluster_id": int(cid),
            "GEOID": str(geoid_mode.iloc[0]) if len(geoid_mode) else str(grp["GEOID"].iloc[0]),
            "overpass_index": int(o),
            "overpass_key": str(grp["overpass_key"].iloc[0]),
            "overpass_timestamp": grp["overpass_timestamp"].iloc[0],
            "cooling_advantage": ca,
            "mean_csi_tree": float(np.nanmean(grp["mean_csi_tree"])) if grp["mean_csi_tree"].notna().any() else np.nan,
            "vpd_z": float(np.nanmean(grp["vpd_z"])) if grp["vpd_z"].notna().any() else np.nan,
            "ndmi_z": float(np.nanmean(grp["ndmi_z"])) if grp["ndmi_z"].notna().any() else np.nan,
            "mean_et_tree": float(np.nanmean(grp["mean_et_tree"])) if grp["mean_et_tree"].notna().any() else np.nan,
            "mean_esi_tree": float(np.nanmean(grp["mean_esi_tree"])) if grp["mean_esi_tree"].notna().any() else np.nan,
            "pdsi": float(np.nanmean(grp["pdsi"])) if grp["pdsi"].notna().any() else np.nan,
            "n_tree_px_valid": int(len(grp)),
            "n_ref_in_R": int(grp["n_ref_in_R"].sum()),
            "R_m": float(grp["R_m"].iloc[0]),
        })
    df = pd.DataFrame(out_rows, columns=CLUSTER_COLUMNS)
    log.info("Aggregated to %d cluster-overpass rows over %d clusters (R=%.0fm)",
             len(df), df["cluster_id"].nunique(), df["R_m"].iloc[0] if len(df) else -1)
    return df


CLUSTER_COLUMNS = [
    "cluster_id", "GEOID", "overpass_index", "overpass_key", "overpass_timestamp",
    "cooling_advantage", "mean_csi_tree", "vpd_z", "ndmi_z",
    "mean_et_tree", "mean_esi_tree", "pdsi",
    "n_tree_px_valid", "n_ref_in_R", "R_m",
]


def write_class_raster(cm: dict, out_path: Path) -> Path:
    """Write the relaxed candidate class raster (1=tree, 2=ref, 0=other) aligned to grid."""
    import rasterio
    from rasterio.transform import Affine
    raster = np.full(config.GRID_SHAPE, CLASS_OTHER, dtype="uint8")
    raster[cm["ref"]] = CLASS_REFERENCE
    raster[cm["tree"]] = CLASS_TREE      # tree wins over ref (disjoint by construction)
    transform = Affine(*config.GRID_TRANSFORM)
    nrows, ncols = config.GRID_SHAPE
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", driver="GTiff", height=nrows, width=ncols, count=1,
                       dtype="uint8", crs=config.CRS, transform=transform, nodata=255,
                       compress="deflate") as dst:
        dst.write(raster, 1)
        dst.set_band_description(1, "section16_pixel_class_pixel (relaxed candidates)")
        dst.update_tags(codebook="0=other; 1=tree-candidate; 2=reference-candidate",
                        canopy_thr=str(config.CANOPY_THR_PIXEL),
                        min_obs=str(config.MIN_OBS_PIXEL))
    log.info("Wrote relaxed candidate class raster -> %s", out_path.name)
    return out_path


# =========================================================================== #
# Reporting helpers (effective-N + dominant-cluster diagnostics)
# =========================================================================== #
def kish_neff(sizes: np.ndarray) -> float:
    """Kish effective N = (sum n_i)^2 / sum(n_i^2) over cluster sizes (worst-case rho~1)."""
    n = np.asarray(sizes, dtype="float64")
    s = n.sum()
    return float(s * s / np.sum(n * n)) if s > 0 else 0.0


def cluster_diagnostics(clusters: pd.DataFrame) -> dict:
    """Cluster-count / dominant-share / Kish-N_eff / BG-crosstab diagnostics (Step 3)."""
    n_clusters = int(clusters.attrs.get("n_clusters", clusters["cluster_id"].nunique()))
    sizes = clusters["cluster_id"].value_counts().to_numpy()
    bg_counts = clusters["GEOID"].value_counts()
    n_tree_px = int(len(clusters))
    dom_geoid = str(bg_counts.index[0]) if len(bg_counts) else "0"
    dom_share = float(bg_counts.iloc[0] / n_tree_px) if n_tree_px else float("nan")
    # clusters per BG, BGs per cluster (straddlers)
    cl_per_bg = clusters.groupby("GEOID")["cluster_id"].nunique()
    bg_per_cl = clusters.groupby("cluster_id")["GEOID"].nunique()
    return {
        "connectivity": clusters.attrs.get("connectivity", "?"),
        "n_tree_px": n_tree_px,
        "n_clusters": n_clusters,
        "largest_cluster_px": int(sizes.max()) if sizes.size else 0,
        "largest_cluster_share": round(float(sizes.max()) / n_tree_px, 4) if n_tree_px else float("nan"),
        "kish_neff_clusters": round(kish_neff(sizes), 2),
        "n_bg_with_tree": int((bg_counts.index != "0").sum()),
        "dominant_bg": dom_geoid,
        "dominant_bg_share": round(dom_share, 4),
        "kish_neff_bg": round(kish_neff(bg_counts.to_numpy()), 2),
        "n_clusters_straddle_bg": int((bg_per_cl > 1).sum()),
        "max_clusters_in_one_bg": int(cl_per_bg.max()) if len(cl_per_bg) else 0,
    }


# =========================================================================== #
# Orchestration / CLI
# =========================================================================== #
def run(do_sweep: bool = True, connectivity: str | None = None) -> dict:
    config.ensure_dirs()
    processed = config.PROCESSED_DIR
    connectivity = connectivity or config.CONNECTIVITY
    results: dict = {}

    cm = candidate_masks()
    layers = load_overpass_layers()

    # Step 2 deliverable: relaxed candidate class raster.
    write_class_raster(cm, processed / PIXEL_CLASS_TIF)

    # Step 3: spatial clusters (primary connectivity) + obs_count per tree px.
    clusters = build_cluster_table(cm, connectivity)
    obs_count = np.isfinite(layers["lst"]).sum(axis=0)
    clusters["obs_count"] = obs_count[clusters["tree_row"].to_numpy(),
                                      clusters["tree_col"].to_numpy()].astype("int64")
    clusters.to_parquet(processed / CLUSTERS_PARQUET, index=False)
    diag_primary = cluster_diagnostics(clusters)
    # rook sensitivity diagnostics (no separate parquet -- reported only).
    clusters_rook = build_cluster_table(cm, "rook")
    diag_rook = cluster_diagnostics(clusters_rook)
    results["cluster_diagnostics"] = {"primary": diag_primary, "rook": diag_rook}
    log.info("CLUSTERS (%s): %d clusters from %d tree px; largest=%d (%.1f%%); "
             "Kish N_eff(clusters)=%.1f  Kish N_eff(BG)=%.1f  dominant BG %s = %.1f%%",
             connectivity, diag_primary["n_clusters"], diag_primary["n_tree_px"],
             diag_primary["largest_cluster_px"], 100 * diag_primary["largest_cluster_share"],
             diag_primary["kish_neff_clusters"], diag_primary["kish_neff_bg"],
             diag_primary["dominant_bg"], 100 * diag_primary["dominant_bg_share"])

    # Steps 4-5: pixel pairing + cluster aggregation, primary R then sweep.
    radii = list(config.R_PAIR_SWEEP_M) if do_sweep else [float(config.R_PAIR_M)]
    primary_R = float(config.R_PAIR_M)
    pixel_frames: list[pd.DataFrame] = []
    cluster_frames: list[pd.DataFrame] = []
    sweep_summary: list[dict] = []
    for R in radii:
        px = compute_pixel_pairs(cm, layers, clusters, radius_m=R)
        cl = aggregate_to_clusters(px)
        pixel_frames.append(px)
        cluster_frames.append(cl)
        sweep_summary.append({
            "R_m": R,
            "pixel_overpass_rows": int(len(px)),
            "tree_px_with_obs": int(px["tree_row"].astype(str).add("_").add(px["tree_col"].astype(str)).nunique()) if len(px) else 0,
            "cluster_overpass_rows": int(len(cl)),
            "clusters_used": int(cl["cluster_id"].nunique()) if len(cl) else 0,
            "bg_used": int(cl["GEOID"].nunique()) if len(cl) else 0,
        })
    results["sweep_summary"] = sweep_summary

    # Persist the FULL sweep stacked (R_m column distinguishes radii); primary R first.
    pixel_all = pd.concat(pixel_frames, ignore_index=True) if pixel_frames else pd.DataFrame(columns=PIXEL_COLUMNS)
    cluster_all = pd.concat(cluster_frames, ignore_index=True) if cluster_frames else pd.DataFrame(columns=CLUSTER_COLUMNS)
    pixel_all.to_parquet(processed / MASTER_PIXEL_PARQUET, index=False)
    cluster_all.to_parquet(processed / MASTER_CLUSTER_PARQUET, index=False)
    results["master_table_pixel"] = processed / MASTER_PIXEL_PARQUET
    results["master_table_cluster"] = processed / MASTER_CLUSTER_PARQUET

    log.info("=" * 72)
    log.info("WROTE deliverables (data/processed/):")
    log.info("  %s  (%d rows; radii %s)", MASTER_PIXEL_PARQUET, len(pixel_all), radii)
    log.info("  %s  (%d rows)", MASTER_CLUSTER_PARQUET, len(cluster_all))
    log.info("  %s  (%d tree px)", CLUSTERS_PARQUET, len(clusters))
    log.info("  %s  (relaxed candidate class raster)", PIXEL_CLASS_TIF)
    log.info("SWEEP SUMMARY:")
    for s in sweep_summary:
        log.info("  R=%4.0fm: pixel-overpass=%d  cluster-overpass=%d  clusters=%d  BGs=%d  "
                 "%s", s["R_m"], s["pixel_overpass_rows"], s["cluster_overpass_rows"],
                 s["clusters_used"], s["bg_used"],
                 "<-- PRIMARY" if s["R_m"] == primary_R else "")
    # machine-readable summary line.
    log.info("SUMMARY_JSON: %s", json.dumps({
        "cluster_diagnostics": results["cluster_diagnostics"],
        "sweep_summary": sweep_summary, "primary_R_m": primary_R}, default=str))
    return results


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 16 - pixel-level local pairing + spatial-cluster "
                    "re-aggregation (reason-#2 fix; enlarged Phoenix paired sample).")
    p.add_argument("--no-sweep", action="store_true",
                   help="primary R only (skip the {210, 500} m sensitivity radii).")
    p.add_argument("--connectivity", choices=("queen", "rook"), default=None,
                   help="tree-cluster adjacency (default config.CONNECTIVITY = queen).")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging.")
    return p


def main(argv=None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    run(do_sweep=not args.no_sweep, connectivity=args.connectivity)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
