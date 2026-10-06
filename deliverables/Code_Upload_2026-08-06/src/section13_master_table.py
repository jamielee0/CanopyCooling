#!/usr/bin/env python3
"""Section 13 / master table — cooling advantage + the analysis-ready master table (steps 67-71).

Inputs : data/processed/ — analysis_cube_70m.zarr (Sec 9), section12_csi_70m.zarr,
         section11_zscores_70m.zarr, section10_pixel_class_70m.tif,
         section10_paired_neighborhoods.csv; data/interim/ —
         neighborhood_blockgroups_32612.parquet, phoenix_tree_inventory.parquet.
Outputs: data/processed/master_table.parquet (one row per paired BG per overpass);
         data/processed/master_pixel_table.parquet (one row per finite tree pixel per
         emittable BG x overpass; B3.1 paired-difference table);
         figures/section13_cooling_advantage_distribution.png (optional QA).
Key decisions (full rationale in docs/DESIGN_DECISIONS.md, Section 13):
  - cooling_advantage = mean LST(reference) - mean LST(tree); paired so weather cancels; negatives kept, never clipped.
  - Row emitted only where >=1 finite-LST tree px AND >=1 finite-LST reference px.
  - irrigation_proxy = equal-weight mean of min-max-normalized turf_fraction, income, (1 - impervious); documented heuristic.
  - functional_type = modal inventory water_use per BG; 'unknown' where no inventory trees (central-Phoenix-only inventory).
  - Pixel-count columns kept for the Section 14 minimum-count filter; the Phoenix paired sample is thin (9 BGs, 1 dominant).
Run: python src/section13_master_table.py [--no-figures] [--verify-only] [-v/--verbose]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

# Pure logic below is numpy/pandas-only so it stays unit-testable without the geo stack.
import geopandas as gpd  # noqa: E402
import rioxarray  # noqa: F401,E402  (registers the .rio accessor)
import xarray as xr  # noqa: E402
from rasterio import features as rfeatures  # noqa: E402
from rasterio.transform import Affine  # noqa: E402

# Make config importable whether run from the repo root or from src/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
import config  # noqa: E402

log = logging.getLogger("section13")


# --- Source layer + deliverable names --------------------------------------- #
ANALYSIS_ZARR = "analysis_cube_70m.zarr"               # Section 9 cube
CSI_ZARR = "section12_csi_70m.zarr"                    # Section 12 CSI
ZSCORE_ZARR = "section11_zscores_70m.zarr"             # Section 11 z-scores
PIXEL_CLASS_TIF = "section10_pixel_class_70m.tif"      # Section 10 classification
PAIRED_CSV = "section10_paired_neighborhoods.csv"      # Section 10 paired BGs
BG_PARQUET = "neighborhood_blockgroups_32612.parquet"  # Section 8 block groups
TREE_INVENTORY_PARQUET = "phoenix_tree_inventory.parquet"  # Section 8 tree inventory

# Deliverables.
MASTER_PARQUET = "master_table.parquet"
PIXEL_PARQUET = "master_pixel_table.parquet"  # B3.1 pixel-level paired-difference table
FIG_COOLING = "section13_cooling_advantage_distribution.png"

# Section 10 class codebook (must match section10_classify_pixels.py).
CLASS_TREE = 1
CLASS_REFERENCE = 2

CITY = "Phoenix"
PRIMARY_SAMPLE_LABEL = "primary"
LOW_COUNT_SAMPLE_LABEL = "sensitivity_lt3_tree_pixels"

# Section 11 z-score variables. Supply = sm_z (soil moisture; config.SUPPLY_VAR ==
# "sm_z"; master column mean_sm_z_tree). NDMI is explicitly named as the vegetation
# check (master column mean_ndmi_z_tree, carried for corroboration).
VEGETATION_CHECK_Z_VAR = "ndmi_z"
SM_Z_VAR = "sm_z"
VPD_Z_VAR = "vpd_z"

# Tree-inventory functional-type fields (Section 8).
WATER_USE_FIELD = "water_use"     # drought_tolerant | mesic
LEAF_HABIT_FIELD = "leaf_habit"   # deciduous | evergreen
FUNCTIONAL_UNKNOWN = "unknown"    # BG with no inventory trees


# --- Pure logic (numpy / pandas only; unit-tested without the geo stack) ----- #
def zonal_mean(values: np.ndarray, mask: np.ndarray) -> tuple[float, int]:
    """Mean of ``values`` over cells that are both masked and finite.

    Returns ``(mean, n_valid)``; ``(nan, 0)`` if no cell qualifies. NaNs inside the
    mask are ignored, so the mean reflects only real observations (steps 67-68).
    """
    mask = np.asarray(mask, dtype=bool)
    vals = np.asarray(values, dtype="float64")
    sel = mask & np.isfinite(vals)
    n = int(sel.sum())
    if n == 0:
        return float("nan"), 0
    return float(vals[sel].mean()), n


def cooling_advantage(mean_lst_reference: float, mean_lst_tree: float) -> float:
    """Cooling advantage = mean LST(reference) - mean LST(tree) (step 67).

    Positive => trees cooler than reference. CAN be negative (a real outcome, never
    clipped). NaN if either mean is NaN.
    """
    return float(mean_lst_reference) - float(mean_lst_tree)


def row_emittable(n_tree_valid: int, n_ref_valid: int) -> bool:
    """Row-emission rule: emit only if >=1 finite-LST tree px AND >=1 finite-LST ref px.

    Ensures both means in step 67 exist; otherwise the difference is undefined.
    """
    return int(n_tree_valid) >= 1 and int(n_ref_valid) >= 1


def analysis_sample_label(n_tree_valid: int) -> str:
    """Label the pre-committed primary sample without discarding low-count rows.

    The primary analysis requires at least ``config.PRIMARY_MIN_TREE_PIXELS`` finite
    tree pixels in the BG x overpass row. Lower-count observations remain available as
    a clearly named sensitivity pool instead of entering the headline model at full weight.
    """
    return (PRIMARY_SAMPLE_LABEL if int(n_tree_valid) >= config.PRIMARY_MIN_TREE_PIXELS
            else LOW_COUNT_SAMPLE_LABEL)


def local_time_fields(ts) -> tuple[int, bool]:
    """``(local_hour, is_day)`` for a tz-naive-UTC overpass timestamp (B4).

    Arizona is MST = UTC-7 year-round (no DST) and ``ts`` is tz-naive UTC (Section 2/9
    provenance), so local hour = (UTC hour - 7) % 24 exactly; any DST-state extension
    must move to ``zoneinfo``, not stretch the fixed -7 offset. Day = [7, 19) local
    (heuristic cut, DECISION 4). Matches notebook cell 4 / line 282. These persisted
    columns are the SINGLE SOURCE OF TRUTH for time-of-day: downstream consumers
    (response surface, mixed model, threshold analysis) READ ``local_hour``/``is_day``
    from the master/pixel tables and do NOT re-derive them.
    """
    local_hour = int((pd.Timestamp(ts).hour - 7) % 24)
    return local_hour, bool(7 <= local_hour < 19)


def normalize_unit(x: np.ndarray) -> np.ndarray:
    """Min-max normalize a 1-D array to [0, 1] across its elements (irrigation proxy).

    If all elements are equal, every element maps to 0.0. NaNs are ignored for min/max
    but propagate in the output.
    """
    x = np.asarray(x, dtype="float64")
    finite = np.isfinite(x)
    if not finite.any():
        return np.full_like(x, np.nan)
    lo = float(np.nanmin(x))
    hi = float(np.nanmax(x))
    rng = hi - lo
    if rng <= 0.0:
        out = np.where(finite, 0.0, np.nan)
        return out
    return (x - lo) / rng


def irrigation_proxy(turf_fraction: np.ndarray, income: np.ndarray,
                     impervious_fraction: np.ndarray) -> np.ndarray:
    """Irrigation-likelihood proxy in [0, 1] (step 70): equal-weight mean of min-max-
    normalized turf_fraction, income, and (1 - impervious_fraction).

    ``impervious_fraction`` is a FRACTION in [0, 1] (not percent). Impute missing income
    before calling so no NaN leaks into the normalization. A documented heuristic, not a
    measurement; it ranks neighborhoods by irrigation likelihood.
    """
    turf = np.asarray(turf_fraction, dtype="float64")
    inc = np.asarray(income, dtype="float64")
    imp = np.asarray(impervious_fraction, dtype="float64")
    low_imperv = 1.0 - imp
    turf_n = normalize_unit(turf)
    inc_n = normalize_unit(inc)
    low_imperv_n = normalize_unit(low_imperv)
    return (turf_n + inc_n + low_imperv_n) / 3.0


def modal_functional_type(labels: Sequence, *, unknown: str = FUNCTIONAL_UNKNOWN) -> str:
    """Modal (most frequent) non-null functional-type label among a BG's inventory trees.

    Ties broken by the alphabetically-first label (deterministic). Returns ``unknown``
    if the sequence is empty or all-null (BG has no inventory trees).
    """
    s = pd.Series(list(labels), dtype="object").dropna()
    s = s[s.astype(str).str.len() > 0]
    if s.empty:
        return unknown
    counts = s.value_counts()
    top = counts[counts == counts.max()].index.tolist()
    return str(sorted(map(str, top))[0])


# --- Geo / IO layer (loads cube + class raster + vectors; rasterizes GEOID) -- #
def _reference() -> "xr.DataArray":
    """The 70 m reference grid as a 2-D rioxarray DataArray (the match target/CRS)."""
    return rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)


def rasterize_blockgroup_geoid(interim: Path, paired_geoids: Sequence[str]
                               ) -> tuple[np.ndarray, "pd.DataFrame"]:
    """Rasterize block-group GEOID onto the 70 m grid by centroid containment (as Section 10).

    Returns ``(index_map int32, lookup DataFrame[bg_index, GEOID, is_paired])``; each cell
    holds the 1-based index of the BG containing its centre (0 = none), is_paired flags the
    9 paired BGs (the only ones that enter the master table).
    """
    bg = gpd.read_parquet(interim / BG_PARQUET).reset_index(drop=True)
    if bg.crs is None or bg.crs.to_epsg() != 32612:
        bg = bg.to_crs(config.CRS)
    transform = Affine(*config.GRID_TRANSFORM)
    nrows, ncols = config.GRID_SHAPE
    shapes = ((geom, i + 1) for i, geom in enumerate(bg.geometry))
    idx = rfeatures.rasterize(
        shapes=shapes, out_shape=(nrows, ncols), transform=transform,
        fill=0, all_touched=False, dtype="int32")
    paired_set = set(str(g) for g in paired_geoids)
    geoids = bg["GEOID"].astype(str).to_numpy()
    lookup = pd.DataFrame({
        "bg_index": np.arange(1, len(bg) + 1, dtype="int64"),
        "GEOID": geoids,
        "is_paired": np.isin(geoids, np.array(sorted(paired_set), dtype=object)),
    })
    covered = int((idx > 0).sum())
    log.info("Rasterized block-group GEOID -> index map: %d/%d px covered (%.1f%%); "
             "%d paired block groups flagged",
             covered, nrows * ncols, 100 * covered / (nrows * ncols),
             int(lookup["is_paired"].sum()))
    return idx, lookup


def tree_functional_types_by_bg(interim: Path, bg_index: np.ndarray,
                                lookup: "pd.DataFrame") -> "pd.DataFrame":
    """Modal `water_use` and `leaf_habit` per block group from the tree inventory.

    Joins each inventory tree to its BG by sampling the bg_index map at the tree's pixel,
    then takes the modal label per BG. Returns DataFrame[GEOID, functional_type,
    functional_leaf_habit, n_inventory_trees]; BGs with no inventory trees are absent
    (filled with `unknown` later) — the inventory covers central Phoenix only.
    """
    inv_path = interim / TREE_INVENTORY_PARQUET
    if not inv_path.exists():
        log.warning("Tree inventory not found (%s) -> all functional types 'unknown'",
                    inv_path.name)
        return pd.DataFrame(columns=["GEOID", "functional_type",
                                     "functional_leaf_habit", "n_inventory_trees"])
    trees = gpd.read_parquet(inv_path)
    if trees.crs is None or trees.crs.to_epsg() != 32612:
        trees = trees.to_crs(config.CRS)

    # Map each tree point to a grid (row, col), then read its bg_index.
    transform = Affine(*config.GRID_TRANSFORM)
    inv = ~transform                                   # world -> (col, row)
    xs = trees.geometry.x.to_numpy()
    ys = trees.geometry.y.to_numpy()
    cols, rows = inv * (xs, ys)
    cols = np.floor(cols).astype(int)
    rows = np.floor(rows).astype(int)
    nrows, ncols = config.GRID_SHAPE
    inside = (rows >= 0) & (rows < nrows) & (cols >= 0) & (cols < ncols)
    bg_of = np.zeros(len(trees), dtype="int64")
    bg_of[inside] = bg_index[rows[inside], cols[inside]]

    geoid_of_index = dict(zip(lookup["bg_index"].to_numpy(), lookup["GEOID"].to_numpy()))
    df = pd.DataFrame({
        "bg_index": bg_of,
        WATER_USE_FIELD: trees[WATER_USE_FIELD].to_numpy() if WATER_USE_FIELD in trees else None,
        LEAF_HABIT_FIELD: trees[LEAF_HABIT_FIELD].to_numpy() if LEAF_HABIT_FIELD in trees else None,
    })
    df = df[df["bg_index"] > 0].copy()
    df["GEOID"] = df["bg_index"].map(geoid_of_index)

    rows_out = []
    for geoid, grp in df.groupby("GEOID"):
        rows_out.append({
            "GEOID": str(geoid),
            "functional_type": modal_functional_type(grp[WATER_USE_FIELD]),
            "functional_leaf_habit": modal_functional_type(grp[LEAF_HABIT_FIELD]),
            "n_inventory_trees": int(len(grp)),
        })
    out = pd.DataFrame(rows_out, columns=["GEOID", "functional_type",
                                          "functional_leaf_habit", "n_inventory_trees"])
    log.info("Tree-inventory functional types: %d trees joined to %d block groups",
             int(df.shape[0]), int(out.shape[0]))
    return out


def load_grids(processed: Path) -> dict:
    """Load every gridded layer Section 13 needs as numpy arrays on the 70 m grid.

    Cube (Sec 9): time-varying lst/et/esi/pdsi + static ndvi/canopy/impervious; Sec 12:
    csi plus its demand/supply component fields; Sec 11: vpd_z + sm_z (supply proper)
    + ndmi_z (vegetation check). The three
    stores share the same 66-overpass axis and key order (asserted) so they are indexed
    positionally.
    """
    cube = xr.open_zarr(processed / ANALYSIS_ZARR, decode_coords="all")
    csi_ds = xr.open_zarr(processed / CSI_ZARR, decode_coords="all")
    z_ds = xr.open_zarr(processed / ZSCORE_ZARR, decode_coords="all")

    # The overpass axes MUST line up (same keys, same order) -> positional indexing.
    ck = np.array([str(k) for k in cube["overpass_key"].values])
    sk = np.array([str(k) for k in csi_ds["overpass_key"].values])
    zk = np.array([str(k) for k in z_ds["overpass_key"].values])
    assert np.array_equal(ck, sk), "CSI overpass_key order != cube (cannot index positionally)"
    assert np.array_equal(ck, zk), "z-score overpass_key order != cube (cannot index positionally)"

    class_da = rioxarray.open_rasterio(processed / PIXEL_CLASS_TIF).squeeze("band", drop=True)

    grids = {
        "lst": cube["lst"].values.astype("float32"),         # (overpass, y, x) Kelvin
        "et": cube["et"].values.astype("float32"),
        "esi": cube["esi"].values.astype("float32"),
        "pdsi": cube["pdsi"].values.astype("float32"),
        "csi": csi_ds["csi"].values.astype("float32"),
        "demand_stress": csi_ds["demand_stress"].values.astype("float32"),
        "supply_stress": csi_ds["supply_stress"].values.astype("float32"),
        "vpd_z": z_ds[VPD_Z_VAR].values.astype("float32"),
        "sm_z": z_ds[SM_Z_VAR].values.astype("float32"),      # supply proper (B1b)
        "ndmi_z": z_ds[VEGETATION_CHECK_Z_VAR].values.astype("float32"),
        "ndvi": cube["ndvi"].values.astype("float32"),        # static (y, x)
        "canopy": cube["canopy"].values.astype("float32"),
        "impervious": cube["impervious"].values.astype("float32"),
        "class_raster": class_da.values,                      # uint8 (y, x)
        "time": pd.to_datetime(cube["time"].values),
        "overpass_key": ck,
        "n_overpass": int(cube.sizes["overpass"]),
    }
    log.info("Loaded grids: %d overpasses; LST/ET/ESI/PDSI + CSI/demand/supply + "
             "vpd_z/sm_z/ndmi_z "
             "(overpass,y,x); ndvi/canopy/impervious + class raster (y,x)",
             grids["n_overpass"])
    cube.close(); csi_ds.close(); z_ds.close()
    return grids


def neighborhood_static(bg_index: np.ndarray, grids: dict, paired: "pd.DataFrame",
                        bg_attrs: "pd.DataFrame", func_types: "pd.DataFrame") -> "pd.DataFrame":
    """Per-paired-BG static table (everything that does NOT vary by overpass), incl. step 70.

    Computes per BG the tree/reference pixel masks, mean impervious/canopy, turf fraction,
    static counts, ACS attributes and modal functional type; then the irrigation proxy
    across these BGs. ``paired`` must already carry the ``bg_index`` column. Stashes the
    per-BG tree/reference pixel index lists in ``.attrs`` for the per-overpass pass.
    """
    rows = []
    tree_px_by_geoid: dict[str, tuple] = {}
    ref_px_by_geoid: dict[str, tuple] = {}

    class_raster = grids["class_raster"]
    ndvi = grids["ndvi"]; canopy = grids["canopy"]; impervious = grids["impervious"]
    ndvi_thr = float(config.NDVI_THR)
    ref_canopy_max = float(config.REF_CANOPY_MAX)

    # paired has columns GEOID, n_tree_px, n_ref_px, bg_index (merged before call).
    for _, prow in paired.iterrows():
        geoid = str(prow["GEOID"]); bidx = int(prow["bg_index"])
        in_bg = (bg_index == bidx)
        tree_mask = in_bg & (class_raster == CLASS_TREE)
        ref_mask = in_bg & (class_raster == CLASS_REFERENCE)
        tree_px_by_geoid[geoid] = np.where(tree_mask)
        ref_px_by_geoid[geoid] = np.where(ref_mask)

        mean_imperv, _ = zonal_mean(impervious, in_bg)
        mean_canopy, _ = zonal_mean(canopy, in_bg)
        # turf fraction over the BG's valid pixels: high NDVI AND low canopy.
        valid = in_bg & np.isfinite(ndvi) & np.isfinite(canopy)
        n_valid_bg = int(valid.sum())
        with np.errstate(invalid="ignore"):
            turf = valid & (ndvi > ndvi_thr) & (canopy < ref_canopy_max)
        turf_fraction = float(turf.sum()) / n_valid_bg if n_valid_bg else float("nan")

        attrs = bg_attrs.loc[bg_attrs["GEOID"] == geoid]
        median_income = float(attrs["median_income"].iloc[0]) if len(attrs) else float("nan")
        pct_poc = float(attrs["pct_poc"].iloc[0]) if len(attrs) else float("nan")
        svi = float(attrs["svi"].iloc[0]) if len(attrs) else float("nan")

        ft = func_types.loc[func_types["GEOID"] == geoid]
        functional_type = str(ft["functional_type"].iloc[0]) if len(ft) else FUNCTIONAL_UNKNOWN
        functional_leaf = str(ft["functional_leaf_habit"].iloc[0]) if len(ft) else FUNCTIONAL_UNKNOWN
        n_inv = int(ft["n_inventory_trees"].iloc[0]) if len(ft) else 0

        rows.append({
            "neighborhood_id": geoid,
            "bg_index": bidx,
            "n_tree_px": int(prow["n_tree_px"]),
            "n_ref_px": int(prow["n_ref_px"]),
            "mean_impervious": mean_imperv,
            "mean_canopy": mean_canopy,
            "turf_fraction": turf_fraction,
            "median_income": median_income,
            "pct_poc": pct_poc,
            "svi": svi,
            "functional_type": functional_type,
            "functional_leaf_habit": functional_leaf,
            "n_inventory_trees": n_inv,
        })

    static = pd.DataFrame(rows)

    # Impute missing income to the paired-BG median BEFORE normalization (step 70).
    income = static["median_income"].to_numpy(dtype="float64")
    if np.isnan(income).any():
        med = float(np.nanmedian(income))
        n_imp = int(np.isnan(income).sum())
        income = np.where(np.isnan(income), med, income)
        log.info("Irrigation proxy: imputed %d missing median_income to the paired-BG "
                 "median (%.0f) before normalization", n_imp, med)
    imperv_fraction = static["mean_impervious"].to_numpy(dtype="float64") / 100.0
    static["irrigation_proxy"] = irrigation_proxy(
        static["turf_fraction"].to_numpy(dtype="float64"), income, imperv_fraction)

    static.attrs["tree_px_by_geoid"] = tree_px_by_geoid
    static.attrs["ref_px_by_geoid"] = ref_px_by_geoid
    return static


def build_master_table(grids: dict, static: "pd.DataFrame") -> "pd.DataFrame":
    """Assemble the master table — one row per (paired BG, overpass) — steps 67-69.

    Per BG and overpass: tree/reference LST means and cooling advantage (step 67), the
    tree-pixel mechanism (ET/ESI) and stressor means (step 68: CSI/vpd_z + sm_z supply
    proper + ndmi_z vegetation check), the static modifiers/attributes + overpass
    aridity (BG-mean PDSI), counts and identifiers incl. the persisted B4 time-of-day
    columns (local_hour/is_day -- single source of truth, see :func:`local_time_fields`).
    A row is emitted only where :func:`row_emittable`.
    """
    tree_px = static.attrs["tree_px_by_geoid"]
    ref_px = static.attrs["ref_px_by_geoid"]
    times = grids["time"]; keys = grids["overpass_key"]
    n_op = grids["n_overpass"]

    lst = grids["lst"]; et = grids["et"]; esi = grids["esi"]
    pdsi = grids["pdsi"]; csi = grids["csi"]
    demand_stress = grids["demand_stress"]; supply_stress = grids["supply_stress"]
    vpd_z = grids["vpd_z"]; sm_z = grids["sm_z"]; ndmi_z = grids["ndmi_z"]

    rows: list[dict] = []
    n_candidate = 0
    for _, srow in static.iterrows():
        geoid = srow["neighborhood_id"]
        trr, trc = tree_px[geoid]      # tree pixel (row, col) arrays for this BG
        rfr, rfc = ref_px[geoid]       # reference pixel (row, col) arrays
        for t in range(n_op):
            n_candidate += 1
            # Per-overpass tree/reference LST means over the BG's pixels.
            tree_lst = lst[t][trr, trc]
            ref_lst = lst[t][rfr, rfc]
            tree_finite = np.isfinite(tree_lst)
            ref_finite = np.isfinite(ref_lst)
            n_tree_valid = int(tree_finite.sum())
            n_ref_valid = int(ref_finite.sum())
            if not row_emittable(n_tree_valid, n_ref_valid):
                continue
            mean_tree_lst = float(tree_lst[tree_finite].mean())
            mean_ref_lst = float(ref_lst[ref_finite].mean())
            cool = cooling_advantage(mean_ref_lst, mean_tree_lst)

            # Mechanism + stressor over the TREE pixels (step 68).
            mean_et, _ = _zonal_at(et[t], trr, trc)
            mean_esi, _ = _zonal_at(esi[t], trr, trc)
            # m3: aggregate baseline CSI and both components over the SAME finite tree-pixel
            # mask. This makes every alternative convex reweighting auditable and preserves
            # mean_csi == 0.5*mean_demand + 0.5*mean_supply (within float tolerance).
            mean_csi, mean_demand_stress, mean_supply_stress = common_component_means(
                csi[t], demand_stress[t], supply_stress[t], trr, trc)
            mean_vpd_z, _ = _zonal_at(vpd_z[t], trr, trc)
            mean_sm_z, _ = _zonal_at(sm_z[t], trr, trc)       # supply proper (B1b)
            mean_ndmi_z, _ = _zonal_at(ndmi_z[t], trr, trc)   # vegetation check
            # Aridity = BG-mean PDSI that overpass over tree+ref pixels (negative = drier).
            arid_r = np.concatenate([trr, rfr]); arid_c = np.concatenate([trc, rfc])
            aridity, _ = _zonal_at(pdsi[t], arid_r, arid_c)

            # Time-of-day (B4, SINGLE SOURCE OF TRUTH): Arizona MST = UTC-7, no DST;
            # times[t] is tz-naive UTC; any DST-state extension must move to zoneinfo.
            # Matches notebook cell 4 / line 282. Downstream (response surface, mixed
            # model) READ these columns; they do not re-derive time-of-day.
            local_hour, is_day = local_time_fields(times[t])

            rows.append({
                # identifiers
                "neighborhood_id": geoid,
                "overpass_timestamp": times[t],
                "overpass_key": keys[t],
                "city": CITY,
                "local_hour": local_hour,
                "is_day": is_day,
                "sample_label": analysis_sample_label(n_tree_valid),
                # primary outcome
                "cooling_advantage": cool,
                "mean_lst_tree": mean_tree_lst,
                "mean_lst_reference": mean_ref_lst,
                # mechanism (tree pixels)
                "mean_et_tree": mean_et,
                "mean_esi_tree": mean_esi,
                # stressor (tree pixels): sm_z = supply proper; ndmi_z = vegetation check
                "mean_csi_tree": mean_csi,
                "mean_demand_stress_tree": mean_demand_stress,
                "mean_supply_stress_tree": mean_supply_stress,
                "mean_vpd_z_tree": mean_vpd_z,
                "mean_sm_z_tree": mean_sm_z,
                "mean_ndmi_z_tree": mean_ndmi_z,
                # modifiers
                "mean_impervious": srow["mean_impervious"],
                "mean_canopy": srow["mean_canopy"],
                "aridity": aridity,
                "irrigation_proxy": srow["irrigation_proxy"],
                "functional_type": srow["functional_type"],
                "functional_leaf_habit": srow["functional_leaf_habit"],
                # neighborhood
                "median_income": srow["median_income"],
                "pct_poc": srow["pct_poc"],
                "svi": srow["svi"],
                # counts
                "n_tree_px": int(srow["n_tree_px"]),
                "n_ref_px": int(srow["n_ref_px"]),
                "n_tree_valid": n_tree_valid,
                "n_ref_valid": n_ref_valid,
                "n_good_obs": int(min(n_tree_valid, n_ref_valid)),
            })

    master = pd.DataFrame(rows, columns=MASTER_COLUMNS)
    log.info("Assembled master table: %d rows emitted of %d candidate (BG x overpass) "
             "pairs (%d paired BGs x %d overpasses)", len(master), n_candidate,
             len(static), n_op)
    return master


def _zonal_at(layer2d: np.ndarray, rr: np.ndarray, cc: np.ndarray) -> tuple[float, int]:
    """Mean of a 2-D layer at the (rr, cc) pixel indices, finite only. (Thin helper.)"""
    if rr.size == 0:
        return float("nan"), 0
    vals = np.asarray(layer2d[rr, cc], dtype="float64")
    fin = np.isfinite(vals)
    n = int(fin.sum())
    if n == 0:
        return float("nan"), 0
    return float(vals[fin].mean()), n


def common_component_means(
    csi2d: np.ndarray,
    demand2d: np.ndarray,
    supply2d: np.ndarray,
    rr: np.ndarray,
    cc: np.ndarray,
) -> tuple[float, float, float]:
    """Mean baseline CSI/demand/supply over one shared finite pixel mask (m3).

    A shared mask is essential: separately averaging each component over different pixels can
    break the convex-weight identity and make the sensitivity incomparable. Empty masks return
    three NaNs. The baseline identity is asserted against the configured weights.
    """
    if rr.size == 0:
        return float("nan"), float("nan"), float("nan")
    c = np.asarray(csi2d[rr, cc], dtype="float64")
    d = np.asarray(demand2d[rr, cc], dtype="float64")
    s = np.asarray(supply2d[rr, cc], dtype="float64")
    common = np.isfinite(c) & np.isfinite(d) & np.isfinite(s)
    if not common.any():
        return float("nan"), float("nan"), float("nan")
    mc = float(c[common].mean())
    md = float(d[common].mean())
    ms = float(s[common].mean())
    expected = float(config.WEIGHT_DEMAND) * md + float(config.WEIGHT_SUPPLY) * ms
    if not np.isclose(mc, expected, atol=2e-6, rtol=1e-6):
        raise AssertionError(
            "mean CSI/component identity failed on the common finite mask: "
            f"mean_csi={mc:.8g}, weighted_components={expected:.8g}")
    return mc, md, ms


def build_pixel_table(grids: dict, static: "pd.DataFrame") -> "pd.DataFrame":
    """Pixel-level paired-difference table (B3.1) -- one row per FINITE-LST tree pixel
    per emittable (paired BG, overpass).

    Each tree pixel is paired against that BG x overpass reference MEAN LST:
    ``cooling_advantage_px = mean_lst_reference - tree_lst``. Same emit gate as the
    master table (:func:`row_emittable`: >=1 finite tree AND >=1 finite reference LST
    pixel); only tree pixels with finite LST emit a row. Predictors vpd_z/sm_z/ndmi_z/csi
    are PER-PIXEL here (the point of the pixel table -- the mixed model separates
    within-BG from between-BG variation); ``aridity`` stays BG-level (same value for
    every pixel in the BG x overpass). Non-finite predictors are KEPT as NaN (the
    model drops them pairwise). ``local_hour``/``is_day`` are the same persisted B4
    columns as the master table (single source of truth). ``sm_z`` is the physical
    water-supply predictor used by the primary model; ``ndmi_z`` is retained only as a
    vegetation-side check. Both are the B2-floored z-scores from the Section 11 store.
    """
    tree_px = static.attrs["tree_px_by_geoid"]
    ref_px = static.attrs["ref_px_by_geoid"]
    times = grids["time"]; keys = grids["overpass_key"]
    n_op = grids["n_overpass"]

    lst = grids["lst"]; pdsi = grids["pdsi"]; csi = grids["csi"]
    vpd_z = grids["vpd_z"]; sm_z = grids["sm_z"]; ndmi_z = grids["ndmi_z"]

    rows: list[dict] = []
    n_emittable = 0
    for _, srow in static.iterrows():
        geoid = srow["neighborhood_id"]
        trr, trc = tree_px[geoid]      # tree pixel (row, col) arrays for this BG
        rfr, rfc = ref_px[geoid]       # reference pixel (row, col) arrays
        arid_r = np.concatenate([trr, rfr]); arid_c = np.concatenate([trc, rfc])
        for t in range(n_op):
            tree_lst = lst[t][trr, trc]
            ref_lst = lst[t][rfr, rfc]
            tree_finite = np.isfinite(tree_lst)
            n_tree_valid = int(tree_finite.sum())
            n_ref_valid = int(np.isfinite(ref_lst).sum())
            if not row_emittable(n_tree_valid, n_ref_valid):
                continue
            n_emittable += 1
            mean_ref_lst, _ = _zonal_at(lst[t], rfr, rfc)
            aridity, _ = _zonal_at(pdsi[t], arid_r, arid_c)
            local_hour, is_day = local_time_fields(times[t])
            n_good = int(min(n_tree_valid, n_ref_valid))
            for r, c, px_lst in zip(trr[tree_finite], trc[tree_finite],
                                    tree_lst[tree_finite]):
                rows.append({
                    # identifiers (same B4 local_hour/is_day as the master table)
                    "neighborhood_id": geoid,
                    "overpass_timestamp": times[t],
                    "overpass_key": keys[t],
                    "city": CITY,
                    "local_hour": local_hour,
                    "is_day": is_day,
                    "sample_label": analysis_sample_label(n_tree_valid),
                    "pixel_row": int(r),
                    "pixel_col": int(c),
                    # outcome (pixel vs BG-reference-mean pairing)
                    "tree_lst": float(px_lst),
                    "mean_lst_reference": mean_ref_lst,
                    "cooling_advantage_px": cooling_advantage(mean_ref_lst, float(px_lst)),
                    # predictors (PER-PIXEL; NaN kept -- model drops pairwise)
                    "vpd_z": float(vpd_z[t][r, c]),
                    "sm_z": float(sm_z[t][r, c]),       # primary water-supply predictor
                    "ndmi_z": float(ndmi_z[t][r, c]),   # vegetation-side check only
                    "csi": float(csi[t][r, c]),
                    "aridity": aridity,                      # BG-level, as in the master
                    # counts (BG x overpass level, repeated per pixel)
                    "n_ref_valid": n_ref_valid,
                    "n_tree_valid": n_tree_valid,
                    "n_good_obs": n_good,
                })
    pixel = pd.DataFrame(rows, columns=PIXEL_COLUMNS)
    log.info("Assembled pixel table (B3.1): %d rows (finite tree px) over %d emittable "
             "(BG x overpass) pairs from %d paired BGs x %d overpasses",
             len(pixel), n_emittable, len(static), n_op)
    return pixel


# Canonical master-table column order (grouped). Module constant so the saved file and
# the tests agree on the schema.
MASTER_COLUMNS = [
    # identifiers (local_hour/is_day APPENDED after city -- keeps MASTER_COLUMNS[:4]
    # stable, the invariant the schema test asserts)
    "neighborhood_id", "overpass_timestamp", "overpass_key", "city",
    "local_hour", "is_day", "sample_label",
    # primary outcome
    "cooling_advantage", "mean_lst_tree", "mean_lst_reference",
    # mechanism (tree pixels)
    "mean_et_tree", "mean_esi_tree",
    # stressor (tree pixels): mean_sm_z_tree = supply proper; mean_ndmi_z_tree =
    # vegetation check (renamed from mean_water_supply_z_tree; invariant in section 2
    # of the remediation plan)
    "mean_csi_tree", "mean_demand_stress_tree", "mean_supply_stress_tree",
    "mean_vpd_z_tree", "mean_sm_z_tree", "mean_ndmi_z_tree",
    # modifiers
    "mean_impervious", "mean_canopy", "aridity", "irrigation_proxy",
    "functional_type", "functional_leaf_habit",
    # neighborhood
    "median_income", "pct_poc", "svi",
    # counts
    "n_tree_px", "n_ref_px", "n_tree_valid", "n_ref_valid", "n_good_obs",
]

# The protocol's column GROUPS -> the master columns that satisfy each (for the report).
COLUMN_GROUPS = {
    "identifiers": ["neighborhood_id", "overpass_timestamp", "overpass_key", "city",
                    "local_hour", "is_day", "sample_label"],
    "primary_outcome": ["cooling_advantage"],
    "mechanism": ["mean_et_tree", "mean_esi_tree"],
    "stressor": ["mean_csi_tree", "mean_demand_stress_tree", "mean_supply_stress_tree",
                 "mean_vpd_z_tree", "mean_sm_z_tree", "mean_ndmi_z_tree"],
    "modifiers": ["mean_impervious", "mean_canopy", "aridity", "irrigation_proxy",
                  "functional_type"],
    "neighborhood": ["median_income", "pct_poc", "svi"],
    "counts": ["n_tree_px", "n_ref_px", "n_good_obs"],
}

# Canonical pixel-table column order (B3.1). One row per finite-LST tree pixel per
# emittable BG x overpass; predictors vpd_z/sm_z/ndmi_z/csi are PER-PIXEL (csi is
# per-pixel from the Section 12 CSI store), aridity stays BG-level. ``sm_z`` is the
# primary supply predictor and ``ndmi_z`` is a vegetation check. The tests + saved file agree
# on this schema.
PIXEL_COLUMNS = [
    # identifiers
    "neighborhood_id", "overpass_timestamp", "overpass_key", "city",
    "local_hour", "is_day", "sample_label", "pixel_row", "pixel_col",
    # outcome
    "tree_lst", "mean_lst_reference", "cooling_advantage_px",
    # predictors (per-pixel, except aridity which is BG-level)
    "vpd_z", "sm_z", "ndmi_z", "csi", "aridity",
    # counts
    "n_ref_valid", "n_tree_valid", "n_good_obs",
]


# --- IO + QC ---------------------------------------------------------------- #
def load_block_group_attrs(interim: Path) -> "pd.DataFrame":
    """Block-group GEOID + ACS attributes (median_income, pct_poc, svi) from the parquet."""
    bg = gpd.read_parquet(interim / BG_PARQUET)
    df = pd.DataFrame({
        "GEOID": bg["GEOID"].astype(str).to_numpy(),
        "median_income": bg["median_income"].to_numpy(),
        "pct_poc": bg["pct_poc"].to_numpy(),
        "svi": bg["svi"].to_numpy(),
    })
    return df


def write_master_table(master: "pd.DataFrame", out_path: Path) -> Path:
    """Write the master table to Parquet (step 71). Overwrites."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    master.to_parquet(out_path, index=False)
    log.info("Wrote master table -> %s (%d rows, %d cols)",
             out_path.name, len(master), master.shape[1])
    return out_path


def report_master_table(master: "pd.DataFrame", irrigation_formula: str) -> dict:
    """Print the deliverable QC (definition-of-done steps 2-5) and return a summary dict.

    Confirms one row per (neighborhood, overpass), lists columns by protocol group, prints
    the cooling_advantage distribution (incl. # negative), the proxy formula, and the
    pixel-count ranges (so the thin paired sample is visible).
    """
    log.info("=" * 70)
    log.info("MASTER TABLE QC (Section 13 deliverable)")
    n_rows = len(master)
    n_neigh = master["neighborhood_id"].nunique()
    n_op = master["overpass_key"].nunique()
    dup = int(master.duplicated(subset=["neighborhood_id", "overpass_key"]).sum())
    log.info("  rows                         : %d", n_rows)
    log.info("  unique neighborhoods (<=9)   : %d", n_neigh)
    log.info("  overpasses represented (<=66): %d", n_op)
    log.info("  duplicate (neighborhood, overpass) keys: %d  (must be 0 -> one row per pair)",
             dup)
    assert dup == 0, "duplicate (neighborhood, overpass) keys -> not one row per pair"

    # Columns by protocol group (confirm every group present).
    log.info("  COLUMNS by protocol group (all %d columns):", master.shape[1])
    for grp, cols in COLUMN_GROUPS.items():
        present = [c for c in cols if c in master.columns]
        missing = [c for c in cols if c not in master.columns]
        log.info("    %-15s : %s%s", grp, present,
                 f"  MISSING={missing}" if missing else "")
        assert not missing, f"column group {grp} missing {missing}"
    extra = [c for c in master.columns
             if c not in {c2 for cols in COLUMN_GROUPS.values() for c2 in cols}]
    log.info("    %-15s : %s", "(extra/detail)", extra)

    # cooling_advantage distribution (step 3) -- report honestly, do NOT clip.
    ca = master["cooling_advantage"].to_numpy(dtype="float64")
    ca = ca[np.isfinite(ca)]
    n_neg = int((ca < 0).sum())
    ca_stats = {
        "min": float(np.min(ca)), "median": float(np.median(ca)),
        "mean": float(np.mean(ca)), "max": float(np.max(ca)),
        "n_negative": n_neg, "n_finite": int(ca.size),
        "frac_negative": n_neg / ca.size if ca.size else float("nan"),
    }
    log.info("  COOLING_ADVANTAGE (K = degC; reference - tree; positive = trees cooler):")
    log.info("    min=%+.3f  median=%+.3f  mean=%+.3f  max=%+.3f",
             ca_stats["min"], ca_stats["median"], ca_stats["mean"], ca_stats["max"])
    log.info("    # negative = %d / %d (%.1f%%)  [negatives ALLOWED -- benefit gone/reversed; "
             "NOT clipped]", n_neg, int(ca.size), 100 * ca_stats["frac_negative"])

    # irrigation_proxy formula (step 4) + value range.
    ip = master["irrigation_proxy"].to_numpy(dtype="float64")
    ip = ip[np.isfinite(ip)]
    log.info("  IRRIGATION_PROXY (step 70) formula:")
    for line in irrigation_formula.splitlines():
        log.info("    %s", line)
    if ip.size:
        log.info("    irrigation_proxy range over rows: [%.3f, %.3f]",
                 float(ip.min()), float(ip.max()))

    # pixel-count ranges (step 5) -- KEPT for the Section 14 minimum-count filter.
    log.info("  PIXEL-COUNT columns (KEPT for the Section 14 minimum-count filter):")
    for c in ("n_tree_px", "n_ref_px", "n_tree_valid", "n_ref_valid", "n_good_obs"):
        col = master[c].to_numpy()
        log.info("    %-13s : min=%d  median=%.1f  max=%d",
                 c, int(col.min()), float(np.median(col)), int(col.max()))
    log.info("    NOTE: the THIN paired sample propagates here -- one BG (040139412001) "
             "has ~171 tree px; the others 1-6, so many rows have small n_tree_valid.")

    # mechanism / stressor NaN coverage (ET/ESI absent on 21 overpasses).
    log.info("  COLUMN NaN coverage (mechanism/stressor/modifier):")
    for c in ("mean_et_tree", "mean_esi_tree", "mean_csi_tree",
              "mean_demand_stress_tree", "mean_supply_stress_tree", "mean_vpd_z_tree",
              "mean_sm_z_tree", "mean_ndmi_z_tree", "aridity"):
        col = master[c]
        n_nan = int(col.isna().sum())
        log.info("    %-26s : %d / %d NaN (%.1f%%)", c, n_nan, n_rows,
                 100 * n_nan / n_rows if n_rows else float("nan"))
    log.info("  functional_type coverage:")
    for label, cnt in master.drop_duplicates("neighborhood_id")["functional_type"].value_counts(
            dropna=False).items():
        log.info("    %-16s : %d block group(s)", label, int(cnt))

    return {"n_rows": n_rows, "n_neighborhoods": n_neigh, "n_overpasses": n_op,
            "duplicates": dup, "cooling_advantage": ca_stats}


IRRIGATION_FORMULA = (
    "irrigation_proxy = mean( norm(turf_fraction), norm(income), norm(1 - impervious_fraction) )\n"
    "  where norm(c) = (c - min(c)) / (max(c) - min(c)) across the 9 paired neighborhoods,\n"
    "  turf_fraction = share of BG pixels with NDVI > NDVI_THR (%.2f) AND canopy < REF_CANOPY_MAX (%.0f%%)\n"
    "                  (irrigated green-but-not-tree: high NDVI, low canopy = the lawn/turf signature),\n"
    "  income = ACS median household income (missing -> paired-BG median before norm),\n"
    "  impervious_fraction = mean impervious percent / 100.\n"
    "  Equal weights (1/3 each); result in [0,1], higher = more likely irrigated. "
    "A DOCUMENTED HEURISTIC, not a measurement."
) % (float(config.NDVI_THR), float(config.REF_CANOPY_MAX))


# --- Figure (optional QA) --------------------------------------------------- #
def make_cooling_figure(master: "pd.DataFrame", figures_dir: Path) -> Path | None:
    """QA figure: cooling_advantage distribution (L) + per-overpass spread (R)."""
    if master.empty:
        log.warning("Cooling figure: empty master table -> skipped")
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(14, 5.2), constrained_layout=True)

    ca = master["cooling_advantage"].to_numpy(dtype="float64")
    ca = ca[np.isfinite(ca)]
    n_neg = int((ca < 0).sum())
    axL.hist(ca, bins=40, color="#1a9850", alpha=0.85)
    axL.axvline(0, color="k", lw=1.0, ls="--", label="0 (benefit gone)")
    axL.axvline(float(np.median(ca)), color="#d7301f", lw=1.2,
                label=f"median = {np.median(ca):+.2f} K")
    axL.set_xlabel("cooling advantage (K = degC; reference LST - tree LST)")
    axL.set_ylabel("rows (neighborhood x overpass)")
    axL.set_title("Section 13: cooling-advantage distribution\n"
                  f"n={ca.size} rows; mean={np.mean(ca):+.2f} K; "
                  f"{n_neg} negative ({100*n_neg/ca.size:.0f}%) -- not clipped")
    axL.legend(loc="upper right", fontsize=8)

    # Per-overpass spread (boxplot of cooling_advantage by date order).
    times = pd.to_datetime(master["overpass_timestamp"])
    df = master.assign(_t=times).sort_values("_t")
    order = sorted(df["_t"].unique())
    data = [df.loc[df["_t"] == t, "cooling_advantage"].dropna().to_numpy() for t in order]
    axR.axhline(0, color="k", lw=0.8, ls=":")
    axR.boxplot(data, showfliers=False, widths=0.6)
    axR.set_xticks([])
    axR.set_xlabel("overpass (time order)")
    axR.set_ylabel("cooling advantage (K) across the paired neighborhoods")
    axR.set_title("Per-overpass cooling-advantage spread\n(each box = the paired "
                  "neighborhoods on one overpass)")

    out = figures_dir / FIG_COOLING
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote figure -> %s", out.name)
    return out


# --- Verification (re-open the saved table + re-check the invariants) -------- #
def verify_master_table(out_path: Path) -> "pd.DataFrame":
    """Re-open the saved Parquet and assert the master-table invariants.

    Checks: every canonical column present; one row per (neighborhood, overpass); <=9
    neighborhoods and <=66 overpasses; city == 'Phoenix'; the step-67 identity on finite
    rows; n_good_obs == min(n_tree_valid, n_ref_valid); and the row-emission rule.
    """
    master = pd.read_parquet(out_path)
    log.info("=" * 70)
    log.info("VERIFY: reopened %s (%d rows, %d cols)", out_path.name, len(master),
             master.shape[1])
    for c in MASTER_COLUMNS:
        assert c in master.columns, f"missing column {c!r} in saved table"
    dup = int(master.duplicated(subset=["neighborhood_id", "overpass_key"]).sum())
    assert dup == 0, "duplicate (neighborhood, overpass) keys in saved table"
    assert master["neighborhood_id"].nunique() <= 9, "more than 9 paired neighborhoods"
    assert master["overpass_key"].nunique() <= 66, "more than 66 overpasses"
    assert (master["city"] == CITY).all(), "city column not all 'Phoenix'"
    # step-67 identity on the finite rows.
    fin = (master["cooling_advantage"].notna() & master["mean_lst_reference"].notna()
           & master["mean_lst_tree"].notna())
    lhs = master.loc[fin, "cooling_advantage"].to_numpy()
    rhs = (master.loc[fin, "mean_lst_reference"] - master.loc[fin, "mean_lst_tree"]).to_numpy()
    assert np.allclose(lhs, rhs, atol=1e-5), \
        "cooling_advantage != mean_lst_reference - mean_lst_tree (step-67 identity broken)"
    # m3 common-mask identity: the saved equal-weight CSI mean must be exactly
    # reconstructable from the two saved component means.
    comp_fin = master[["mean_csi_tree", "mean_demand_stress_tree",
                       "mean_supply_stress_tree"]].notna().all(axis=1)
    comp_lhs = master.loc[comp_fin, "mean_csi_tree"].to_numpy(dtype="float64")
    comp_rhs = (float(config.WEIGHT_DEMAND)
                * master.loc[comp_fin, "mean_demand_stress_tree"].to_numpy(dtype="float64")
                + float(config.WEIGHT_SUPPLY)
                * master.loc[comp_fin, "mean_supply_stress_tree"].to_numpy(dtype="float64"))
    assert np.allclose(comp_lhs, comp_rhs, atol=2e-6, rtol=1e-6), \
        "mean CSI != weighted component means on the common finite mask"
    # n_good_obs == min(tree_valid, ref_valid); row-emission rule.
    assert (master["n_good_obs"]
            == np.minimum(master["n_tree_valid"], master["n_ref_valid"])).all(), \
        "n_good_obs != min(n_tree_valid, n_ref_valid)"
    assert (master["n_tree_valid"] >= 1).all() and (master["n_ref_valid"] >= 1).all(), \
        "an emitted row violates the >=1 tree AND >=1 reference finite-LST rule"
    expected_label = np.where(master["n_tree_valid"] >= config.PRIMARY_MIN_TREE_PIXELS,
                              PRIMARY_SAMPLE_LABEL, LOW_COUNT_SAMPLE_LABEL)
    assert np.array_equal(master["sample_label"].to_numpy(), expected_label), \
        "sample_label does not match the pre-committed tree-pixel floor"
    log.info("  ASSERTIONS PASSED: all columns present; one row per (neighborhood, "
             "overpass); cooling_advantage == ref - tree; CSI == weighted component "
             "means on a common mask; n_good_obs == min(...); every row has >=1 finite "
             "tree & reference pixel.")
    return master


def verify_pixel_table(out_path: Path) -> "pd.DataFrame":
    """Re-open the saved pixel Parquet (B3.1) and assert its invariants.

    Mirrors :func:`verify_master_table`: every :data:`PIXEL_COLUMNS` column present;
    unique on (neighborhood_id, overpass_key, pixel_row, pixel_col); the pixel step-67
    identity cooling_advantage_px == mean_lst_reference - tree_lst on finite rows
    (atol 1e-5); <=9 neighborhoods; every row has >=1 finite tree AND reference pixel.
    """
    pixel = pd.read_parquet(out_path)
    log.info("=" * 70)
    log.info("VERIFY: reopened %s (%d rows, %d cols)", out_path.name, len(pixel),
             pixel.shape[1])
    for c in PIXEL_COLUMNS:
        assert c in pixel.columns, f"missing column {c!r} in saved pixel table"
    dup = int(pixel.duplicated(
        subset=["neighborhood_id", "overpass_key", "pixel_row", "pixel_col"]).sum())
    assert dup == 0, "duplicate (neighborhood, overpass, pixel_row, pixel_col) keys"
    assert pixel["neighborhood_id"].nunique() <= 9, "more than 9 paired neighborhoods"
    # pixel step-67 identity on the finite rows.
    fin = (pixel["cooling_advantage_px"].notna() & pixel["mean_lst_reference"].notna()
           & pixel["tree_lst"].notna())
    lhs = pixel.loc[fin, "cooling_advantage_px"].to_numpy()
    rhs = (pixel.loc[fin, "mean_lst_reference"] - pixel.loc[fin, "tree_lst"]).to_numpy()
    assert np.allclose(lhs, rhs, atol=1e-5), \
        "cooling_advantage_px != mean_lst_reference - tree_lst (pixel identity broken)"
    assert (pixel["n_ref_valid"] >= 1).all() and (pixel["n_tree_valid"] >= 1).all(), \
        "an emitted pixel row violates the >=1 tree AND >=1 reference finite-LST rule"
    expected_label = np.where(pixel["n_tree_valid"] >= config.PRIMARY_MIN_TREE_PIXELS,
                              PRIMARY_SAMPLE_LABEL, LOW_COUNT_SAMPLE_LABEL)
    assert np.array_equal(pixel["sample_label"].to_numpy(), expected_label), \
        "pixel sample_label does not match the pre-committed tree-pixel floor"
    log.info("  ASSERTIONS PASSED: all columns present; unique per "
             "(neighborhood, overpass, pixel_row, pixel_col); cooling_advantage_px == "
             "ref_mean - tree_lst; every row has >=1 finite tree & reference pixel.")
    return pixel


# --- Orchestration / CLI ---------------------------------------------------- #
def run(make_figures: bool = True, verify_only: bool = False) -> dict:
    config.ensure_dirs()
    interim = config.INTERIM_DIR
    processed = config.PROCESSED_DIR
    out_path = processed / MASTER_PARQUET
    pixel_path = processed / PIXEL_PARQUET
    results: dict = {}

    if not verify_only:
        paired = pd.read_csv(processed / PAIRED_CSV, dtype={"GEOID": str})
        bg_index, lookup = rasterize_blockgroup_geoid(interim, paired["GEOID"].tolist())
        # attach bg_index to the paired table (GEOID -> bg_index via the lookup).
        paired = paired.merge(lookup[["GEOID", "bg_index"]], on="GEOID", how="left")
        assert paired["bg_index"].notna().all(), \
            "a paired GEOID did not rasterize to a bg_index (geometry/CRS mismatch?)"
        paired["bg_index"] = paired["bg_index"].astype(int)

        grids = load_grids(processed)
        bg_attrs = load_block_group_attrs(interim)
        func_types = tree_functional_types_by_bg(interim, bg_index, lookup)

        static = neighborhood_static(bg_index, grids, paired, bg_attrs, func_types)
        log.info("=" * 70)
        log.info("PER-PAIRED-BG STATIC TABLE (%d BGs):", len(static))
        for _, r in static.iterrows():
            log.info("  %s: n_tree=%d n_ref=%d imperv=%.1f%% canopy=%.1f%% turf=%.3f "
                     "income=%s svi=%.3f ftype=%s irr=%.3f",
                     r["neighborhood_id"], r["n_tree_px"], r["n_ref_px"],
                     r["mean_impervious"], r["mean_canopy"], r["turf_fraction"],
                     "NaN" if pd.isna(r["median_income"]) else f"{r['median_income']:.0f}",
                     r["svi"], r["functional_type"], r["irrigation_proxy"])

        master = build_master_table(grids, static)
        write_master_table(master, out_path)
        results["master_parquet"] = out_path

        # B3.1 pixel-level paired-difference table (additive; master_table.parquet
        # unchanged). One row per finite tree pixel per emittable BG x overpass.
        pixel = build_pixel_table(grids, static)
        pixel.to_parquet(pixel_path, index=False)
        log.info("Wrote pixel table -> %s (%d rows, %d cols)",
                 pixel_path.name, len(pixel), pixel.shape[1])
        results["pixel_parquet"] = pixel_path

    master = verify_master_table(out_path)
    verify_pixel_table(pixel_path)
    results["summary"] = report_master_table(master, IRRIGATION_FORMULA)

    if make_figures:
        results["fig_cooling"] = make_cooling_figure(master, config.FIGURES_DIR)

    _report(results)
    return results


def _report(results: dict) -> None:
    log.info("=" * 70)
    log.info("Section 13 complete. Deliverable (data/processed/):")
    if "master_parquet" in results:
        log.info("  master_table     -> %s", Path(results["master_parquet"]).name)
    if "pixel_parquet" in results:
        log.info("  pixel_table      -> %s", Path(results["pixel_parquet"]).name)
    if results.get("fig_cooling"):
        log.info("  figure           -> %s", Path(results["fig_cooling"]).name)
    s = results.get("summary", {})
    if s:
        ca = s["cooling_advantage"]
        log.info("  rows=%d  neighborhoods=%d  overpasses=%d", s["n_rows"],
                 s["n_neighborhoods"], s["n_overpasses"])
        log.info("  cooling_advantage: min=%+.3f median=%+.3f mean=%+.3f max=%+.3f "
                 "(# negative=%d/%d)", ca["min"], ca["median"], ca["mean"], ca["max"],
                 ca["n_negative"], ca["n_finite"])
    log.info("=" * 70)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 13 - cooling advantage + the master analysis table "
                    "(one row per paired neighborhood per overpass; steps 67-71).")
    p.add_argument("--no-figures", action="store_true", help="skip the QA figure.")
    p.add_argument("--verify-only", action="store_true",
                   help="skip the build; re-open the saved master table and run verify + QC.")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    run(make_figures=not args.no_figures, verify_only=args.verify_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
