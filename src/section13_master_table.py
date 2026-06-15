#!/usr/bin/env python3
"""Section 13 - Cooling advantage + the master analysis table (steps 67-71).

Implements the whole of Section 13 for the Phoenix pilot from this one module, so
it re-runs end to end from saved code (protocol standing rule: "every figure and
every number must be reproducible from the saved code; nothing produced by hand").

Objective (protocol Section 13, steps 67-71)
--------------------------------------------
Compute the study's PRIMARY OUTCOME -- the cooling advantage of trees -- and
assemble every variable into one analysis-ready master table (one row per paired
neighborhood per overpass). This is the INTEGRATION section: the single file every
later analysis (Section 14 onward) reads.

  67. COOLING ADVANTAGE. For each (paired) neighborhood and each overpass, take the
      MEAN LST over its TREE-DOMINATED pixels and the MEAN LST over its REFERENCE
      pixels, and
          cooling_advantage = mean_LST(reference) - mean_LST(tree).
      Positive = trees cooler than the surrounding built surfaces; near zero = the
      benefit is gone. Because BOTH terms come from the SAME overpass, the shared
      weather and time-of-day cancel out (the whole point of the paired design).
      It CAN be negative on some overpasses -- that is NOT an error (report the
      spread; do not clip).
  68. MECHANISM + STRESSOR over the TREE pixels. For the same neighborhood/overpass,
      the MEAN Compound Stress Index, and the MEAN evapotranspiration (ET) and
      evaporative-stress index (ESI) over the TREE-DOMINATED pixels.
  69. ASSEMBLE the master table -- one row per neighborhood per overpass -- with the
      identifier / outcome / mechanism / stressor / modifier / neighborhood / count
      column groups (see COLUMN GROUPS below).
  70. IRRIGATION-LIKELIHOOD PROXY: a DOCUMENTED composite of impervious fraction,
      landscaped/turf fraction, and neighborhood income (formula written out below),
      added as a column.
  71. SAVE the master table in Parquet -- the single input to every analysis from
      here on.

Common pitfall (carried, not hidden): neighborhoods with very FEW tree or reference
pixels give noisy averages. We KEEP the pixel-count columns so a minimum-count
requirement can be imposed before modelling (Section 14). The Phoenix paired sample
is THIN: only 9 paired block groups, and only ONE of them (GEOID 040139412001) has a
large tree set (~171 tree px); the others have 1-6 tree px. That thin sample
propagates into this table -- many rows have a very small n_tree_valid -- and MUST be
reported with the Section 14 threshold estimate.

================================================================================
GRANULARITY & EXACTLY HOW EACH COLUMN IS COMPUTED (documented choices; see also
data/processed/README.md and src/README.md Section 13)
================================================================================
ROW = one (paired-neighborhood GEOID, overpass) pair. There are 9 paired BGs and 66
overpasses -> up to 594 candidate rows, but a row is EMITTED ONLY where the cooling
advantage is COMPUTABLE: the BG must have >= 1 tree pixel AND >= 1 reference pixel
with FINITE LST on that overpass (the row-emission rule, :func:`row_emittable`).

* IDENTIFIERS
    - neighborhood_id     = the block-group GEOID (string, 12-digit).
    - overpass_timestamp  = the overpass `time` (UTC datetime).
    - overpass_key        = `{orbit}_{scene}_{YYYYMMDDTHHMMSS}` (kept for joins).
    - city                = "Phoenix".
* PRIMARY OUTCOME
    - cooling_advantage   = mean LST(reference) - mean LST(tree) over THIS overpass's
                            FINITE-LST pixels in the BG (Kelvin == degrees C
                            difference; a temperature DIFFERENCE so K and degC are the
                            same number). Can be negative -- not clipped.
* MECHANISM (over the TREE-dominated pixels; step 68)
    - mean_et_tree        = mean ET over the BG's tree pixels that overpass (W m-2;
                            NaN on the 21 overpasses with no ET -- expected).
    - mean_esi_tree       = mean ESI over the BG's tree pixels that overpass (-; NaN
                            on the 21 non-ET/ESI overpasses).
* STRESSOR (over the TREE-dominated pixels; step 68 "over the tree-dominated pixels")
    - mean_csi_tree            = mean CSI over the BG's tree pixels (Section 12).
    - mean_vpd_z_tree          = mean VPD z-score over the BG's tree pixels (Section 11;
                                 nearly spatially uniform -- ERA5 ~9 km).
    - mean_water_supply_z_tree = mean water-supply z-score (ndmi_z, Section 11) over the
                                 BG's tree pixels (STATIC in time -- Section 11 decision B;
                                 varies spatially).
* MODIFIERS
    - mean_impervious     = NEIGHBORHOOD-level mean impervious percent over ALL valid
                            pixels in the BG (a CONTEXT modifier -- the built-ness of the
                            whole neighborhood, NOT just the tree pixels; documented choice).
    - mean_canopy         = NEIGHBORHOOD-level mean canopy percent over all valid BG pixels.
    - aridity             = the BG-mean drought index (PDSI) for that overpass
                            (NEGATIVE = drier; a background-dryness modifier). PDSI is NaN
                            on the 3 earliest pilot overpasses (no containing pentad,
                            Section 9) -> aridity NaN there (expected).
    - irrigation_proxy    = the documented composite of step 70 (see IRRIGATION PROXY).
    - functional_type     = the dominant tree FUNCTIONAL type in the BG from the tree
                            inventory: the MODAL `water_use` (drought_tolerant vs mesic)
                            among inventory trees whose point falls in the BG. `unknown`
                            where the BG has NO inventory trees (the inventory covers
                            central Phoenix only, so several BGs are unknown -- expected,
                            handled gracefully). The modal `leaf_habit`
                            (deciduous/evergreen) is also carried as `functional_leaf_habit`.
* NEIGHBORHOOD (from the block-group attributes -- the parquet, for exactness)
    - median_income       = ACS median household income (USD; top-coded at 250001).
    - pct_poc             = percent people of colour.
    - svi                 = CDC/ATSDR overall social-vulnerability index (percentile 0-1).
* COUNTS (KEEP ALL for the Section 14 minimum-count filter)
    - n_tree_px           = tree-dominated pixels in the BG (static; from the class raster).
    - n_ref_px            = reference pixels in the BG (static).
    - n_tree_valid        = tree pixels with FINITE LST on this overpass (the actual tree
                            sample size behind mean_LST(tree)).
    - n_ref_valid         = reference pixels with FINITE LST on this overpass.
    - n_good_obs          = min(n_tree_valid, n_ref_valid) -- the binding sample size for
                            the paired cooling_advantage difference (defined so a row is
                            only as trustworthy as its SMALLER group).

UNITS / SIGN: cooling_advantage is a TEMPERATURE DIFFERENCE in Kelvin, numerically equal
to degrees Celsius (the cube's `lst` is in Kelvin). Positive => tree pixels are COOLER
than reference pixels (the expected urban-tree effect).

================================================================================
IRRIGATION PROXY (step 70) -- DOCUMENTED FORMULA (a heuristic, NOT a measurement)
================================================================================
Construct an irrigation-LIKELIHOOD proxy in [0, 1] (higher = more likely irrigated) as
an EQUAL-WEIGHT mean of three components, each MIN-MAX normalized to [0, 1] ACROSS the
paired neighborhoods:

  (a) turf_fraction  = fraction of the BG that is IRRIGATED GREEN-BUT-NOT-TREE, defined
      per pixel as (NDVI > NDVI_THR) AND (canopy < REF_CANOPY_MAX). High NDVI WITHOUT
      tree canopy is the protocol's "lawn/turf" signature (well-watered grass scores
      high NDVI but is not canopy) -- the documented turf/landscaped-fraction proxy.
      Higher turf fraction -> more likely irrigated. (NDVI_THR / REF_CANOPY_MAX are the
      same pre-registered cuts Section 10 uses, so the proxy reuses calibrated bars.)
  (b) income         = the BG ACS median household income. Higher income -> more able to
      irrigate landscaping -> more likely irrigated.
  (c) low_impervious = (1 - impervious_fraction), where impervious_fraction = mean
      impervious PERCENT / 100. More pervious (less paved) surface -> more landscapable
      ground that could be irrigated.

  Each component c is normalized across the N paired neighborhoods:
      c_norm = (c - min(c)) / (max(c) - min(c))            (0 if max == min)
  and combined with EQUAL weights:
      irrigation_proxy = mean(turf_fraction_norm, income_norm, low_impervious_norm)
                       = (turf_fraction_norm + income_norm + low_impervious_norm) / 3.

  Missing income (BG with NaN ACS income) is imputed to the MEDIAN income of the paired
  BGs BEFORE normalization (so the proxy is defined for every paired BG; documented).
  irrigation_proxy is STATIC per BG (it has no overpass dependence), so every overpass
  row for a given BG carries the same value. It is a DOCUMENTED HEURISTIC composite, not
  a measurement of irrigation; it is meant to RANK neighborhoods by irrigation
  likelihood, not to quantify water applied.

Deliverables (checkpoint, Section 13; data/processed/, git-ignored)
-------------------------------------------------------------------
* master_table.parquet -- THE deliverable. One row per (paired neighborhood, overpass)
  with the column groups above. The single input to every analysis from here on
  (step 71). KEEPS the pixel-count columns for the Section 14 minimum-count filter.
* figures/section13_cooling_advantage_distribution.png -- (optional QA) the
  cooling_advantage distribution + per-overpass spread.

Run (canopy env; no network -- reads only data/processed + data/interim):
    python src/section13_master_table.py                 # full Section 13
    python src/section13_master_table.py --no-figures     # skip the QA figure
    python src/section13_master_table.py --verify-only    # re-open + QC the saved table
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

# Heavy geospatial libs. The pure logic below (the cooling-advantage difference, the
# zonal mean over a class mask, the row-emission rule, the irrigation-proxy formula +
# normalization, and the modal functional-type aggregation) is numpy/pandas-only, so
# it stays unit-testable WITHOUT the geo stack installed (see
# test_section13_master_table.py).
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


# =========================================================================== #
# Source layer + deliverable names.
# --------------------------------------------------------------------------- #
ANALYSIS_ZARR = "analysis_cube_70m.zarr"               # Section 9 cube
CSI_ZARR = "section12_csi_70m.zarr"                    # Section 12 CSI
ZSCORE_ZARR = "section11_zscores_70m.zarr"             # Section 11 z-scores
PIXEL_CLASS_TIF = "section10_pixel_class_70m.tif"      # Section 10 classification
PAIRED_CSV = "section10_paired_neighborhoods.csv"      # Section 10 paired BGs
BG_PARQUET = "neighborhood_blockgroups_32612.parquet"  # Section 8 block groups
TREE_INVENTORY_PARQUET = "phoenix_tree_inventory.parquet"  # Section 8 tree inventory

# Deliverables.
MASTER_PARQUET = "master_table.parquet"
FIG_COOLING = "section13_cooling_advantage_distribution.png"

# Section 10 class codebook (must match section10_classify_pixels.py).
CLASS_TREE = 1
CLASS_REFERENCE = 2

CITY = "Phoenix"

# The z-score variable used as the "water-supply z" (Section 11 / step 69 stressor).
WATER_SUPPLY_Z_VAR = "ndmi_z"
VPD_Z_VAR = "vpd_z"

# Tree-inventory functional-type fields (Section 8).
WATER_USE_FIELD = "water_use"     # drought_tolerant | mesic
LEAF_HABIT_FIELD = "leaf_habit"   # deciduous | evergreen
FUNCTIONAL_UNKNOWN = "unknown"    # BG with no inventory trees


# =========================================================================== #
# Pure logic (numpy / pandas only; unit-tested WITHOUT the geo stack)
# =========================================================================== #
def zonal_mean(values: np.ndarray, mask: np.ndarray) -> tuple[float, int]:
    """Mean of ``values`` over the cells where ``mask`` is True AND the value is finite.

    Returns ``(mean, n_valid)`` where ``n_valid`` is the number of finite cells inside
    the mask (the actual sample size behind the mean). If no cell is both masked and
    finite, returns ``(nan, 0)``. NaNs inside the mask are ignored (not counted), so the
    mean reflects only real observations -- exactly the per-overpass tree/reference LST
    averaging of steps 67-68 (a pixel with no LST that overpass does not enter the mean).
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

    Positive => the tree-dominated pixels are COOLER than the reference (built) pixels
    -- the urban-tree cooling effect. Near zero => the benefit is gone. CAN be NEGATIVE
    (trees warmer than reference on that overpass) -- that is a real outcome, NOT an
    error, and is never clipped. Because both means come from the SAME overpass, the
    shared weather and time-of-day cancel out. NaN if either mean is NaN.
    """
    return float(mean_lst_reference) - float(mean_lst_tree)


def row_emittable(n_tree_valid: int, n_ref_valid: int) -> bool:
    """Whether a (neighborhood, overpass) row is emitted (the row-emission rule).

    A row is emitted ONLY if the cooling advantage is computable: the BG must have at
    least ONE tree pixel AND at least one reference pixel with FINITE LST on that
    overpass (so BOTH means in step 67 exist). Rows where either group has no finite-LST
    pixel that overpass are dropped (the difference would be NaN / undefined).
    """
    return int(n_tree_valid) >= 1 and int(n_ref_valid) >= 1


def normalize_unit(x: np.ndarray) -> np.ndarray:
    """MIN-MAX normalize a 1-D array to [0, 1] across its elements (the irrigation proxy).

        x_norm = (x - min(x)) / (max(x) - min(x))

    If all elements are equal (max == min) every element maps to 0.0 (no spread to
    rank). NaNs are ignored when computing min/max but PROPAGATE in the output (a NaN
    stays NaN). Used to put each irrigation-proxy component on a common [0, 1] scale
    BEFORE the equal-weight combination (step 70).
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
    """Irrigation-likelihood proxy in [0, 1] (step 70) -- the DOCUMENTED composite.

    EQUAL-weight mean of three MIN-MAX-normalized components ACROSS the neighborhoods:
      (a) turf_fraction        -- irrigated green-but-not-tree fraction (high NDVI, low
                                  canopy); higher -> more likely irrigated;
      (b) income               -- ACS median household income; higher -> more able to
                                  irrigate landscaping;
      (c) low_impervious = 1 - impervious_fraction -- more pervious ground -> more
                                  landscapable surface that could be irrigated.
    Each is normalized to [0, 1] with :func:`normalize_unit`, then combined:
        irrigation_proxy = (turf_norm + income_norm + low_impervious_norm) / 3.
    Higher = more likely irrigated. ``impervious_fraction`` is a FRACTION in [0, 1] (NOT
    percent). Inputs are per-neighborhood arrays of equal length; the result is the
    per-neighborhood proxy. Missing income should be imputed BEFORE calling (so no NaN
    leaks into the normalization). A DOCUMENTED HEURISTIC, not a measurement of water
    applied -- it RANKS neighborhoods by irrigation likelihood.
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
    """The MODAL (most frequent) functional-type label among a BG's inventory trees.

    ``labels`` is the sequence of e.g. `water_use` values for the inventory trees whose
    point falls inside the block group. Returns the single most frequent NON-NULL label
    (ties broken by the alphabetically-first label, deterministically). If the sequence
    is EMPTY or all-null (the BG has no inventory trees -- the inventory is central-
    Phoenix only), returns ``unknown``. This is the dominant tree functional type of the
    neighborhood (drought_tolerant vs mesic / deciduous vs evergreen), a MODIFIER.
    """
    s = pd.Series(list(labels), dtype="object").dropna()
    s = s[s.astype(str).str.len() > 0]
    if s.empty:
        return unknown
    counts = s.value_counts()
    top = counts[counts == counts.max()].index.tolist()
    return str(sorted(map(str, top))[0])


# =========================================================================== #
# Geo / IO layer (loads the cube + class raster + vectors; rasterizes GEOID)
# =========================================================================== #
def _reference() -> "xr.DataArray":
    """The 70 m reference grid as a 2-D rioxarray DataArray (the match target/CRS)."""
    return rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)


def rasterize_blockgroup_geoid(interim: Path, paired_geoids: Sequence[str]
                               ) -> tuple[np.ndarray, "pd.DataFrame"]:
    """Rasterize block-group GEOID onto the 70 m grid by centroid containment.

    Re-derives the per-pixel block-group INDEX map exactly as Section 10 does (each cell
    takes the 1-based index of the block group that CONTAINS its centre; all_touched=
    False -> value-per-cell, no double counting at polygon edges; 0 = no block group),
    so each pixel maps to its block group for the zonal means. Returns
    ``(index_map int32, lookup DataFrame[bg_index, GEOID, is_paired])`` where is_paired
    flags the 9 paired block groups (the only ones that enter the master table).
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

    Spatially joins each inventory tree to its block group via the SAME per-pixel
    bg_index map used for the zonal means (sample the index map at the tree's pixel --
    consistent with the centroid-containment rasterization, and robust to the inventory
    being a point layer), then takes the MODAL label per BG (:func:`modal_functional_type`).
    Returns a DataFrame[GEOID, functional_type, functional_leaf_habit, n_inventory_trees].
    Block groups with NO inventory trees simply do not appear here (they are filled with
    `unknown` later) -- the inventory covers central Phoenix only, so this is expected.
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
    """Load every gridded layer Section 13 needs, as numpy arrays on the 70 m grid.

    From the Section 9 cube: time-varying ``lst``/``et``/``esi``/``pdsi`` (overpass,y,x)
    and the static ``ndvi``/``canopy``/``impervious`` (y,x). From the Section 12 store:
    ``csi`` (overpass,y,x). From the Section 11 store: ``vpd_z`` and ``ndmi_z``
    (overpass,y,x). The three stores SHARE the same 66-overpass axis and overpass_key
    ORDER (asserted), so they are indexed positionally. Returns a dict of arrays plus the
    overpass coords (time / overpass_key) and the per-pixel class raster.
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
        "vpd_z": z_ds[VPD_Z_VAR].values.astype("float32"),
        "ndmi_z": z_ds[WATER_SUPPLY_Z_VAR].values.astype("float32"),
        "ndvi": cube["ndvi"].values.astype("float32"),        # static (y, x)
        "canopy": cube["canopy"].values.astype("float32"),
        "impervious": cube["impervious"].values.astype("float32"),
        "class_raster": class_da.values,                      # uint8 (y, x)
        "time": pd.to_datetime(cube["time"].values),
        "overpass_key": ck,
        "n_overpass": int(cube.sizes["overpass"]),
    }
    log.info("Loaded grids: %d overpasses; LST/ET/ESI/PDSI + CSI + vpd_z/ndmi_z "
             "(overpass,y,x); ndvi/canopy/impervious + class raster (y,x)",
             grids["n_overpass"])
    cube.close(); csi_ds.close(); z_ds.close()
    return grids


def neighborhood_static(bg_index: np.ndarray, grids: dict, paired: "pd.DataFrame",
                        bg_attrs: "pd.DataFrame", func_types: "pd.DataFrame") -> "pd.DataFrame":
    """Per-paired-BG STATIC table (everything that does NOT vary by overpass).

    For each paired block group computes: the tree/reference pixel masks (from the class
    raster restricted to the BG), the neighborhood-level mean impervious/canopy over all
    valid BG pixels, the turf fraction (NDVI>NDVI_THR AND canopy<REF_CANOPY_MAX, over the
    BG's pixels), the static counts n_tree_px/n_ref_px, the ACS attributes
    (median_income/pct_poc/svi) and the modal functional type. The irrigation proxy is
    then computed ACROSS these BGs (step 70). Returns one row per paired BG, plus stashes
    the per-BG tree/reference pixel index lists in attrs for the per-overpass pass.

    ``paired`` must already carry the ``bg_index`` column (merged from the rasterization
    lookup) so each paired GEOID maps to its per-pixel block-group index.
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

    # ---- irrigation proxy across the paired BGs (step 70) ----------------- #
    # Impute missing income to the paired-BG median BEFORE normalization so the proxy is
    # defined for every paired BG (documented choice).
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
    """Assemble the master table -- one row per (paired BG, overpass) -- steps 67-69.

    For every paired BG and every overpass: take the tree/reference LST means (over the
    BG's tree/reference pixels with finite LST that overpass), form the cooling advantage
    (step 67), the tree-pixel mechanism (mean ET/ESI) and stressor (mean CSI/vpd_z/ndmi_z)
    means (step 68), attach the static modifiers/neighborhood attributes + the overpass
    aridity (BG-mean PDSI), the counts, and the identifiers. A row is EMITTED ONLY where
    :func:`row_emittable` (>=1 finite-LST tree px AND >=1 finite-LST reference px). Returns
    the master DataFrame (one row per emitted (neighborhood, overpass) pair).
    """
    tree_px = static.attrs["tree_px_by_geoid"]
    ref_px = static.attrs["ref_px_by_geoid"]
    times = grids["time"]; keys = grids["overpass_key"]
    n_op = grids["n_overpass"]

    lst = grids["lst"]; et = grids["et"]; esi = grids["esi"]
    pdsi = grids["pdsi"]; csi = grids["csi"]
    vpd_z = grids["vpd_z"]; ndmi_z = grids["ndmi_z"]

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
            mean_csi, _ = _zonal_at(csi[t], trr, trc)
            mean_vpd_z, _ = _zonal_at(vpd_z[t], trr, trc)
            mean_ndmi_z, _ = _zonal_at(ndmi_z[t], trr, trc)
            # Aridity = BG-mean PDSI that overpass (negative = drier) over tree+ref pixels.
            arid_r = np.concatenate([trr, rfr]); arid_c = np.concatenate([trc, rfc])
            aridity, _ = _zonal_at(pdsi[t], arid_r, arid_c)

            rows.append({
                # identifiers
                "neighborhood_id": geoid,
                "overpass_timestamp": times[t],
                "overpass_key": keys[t],
                "city": CITY,
                # primary outcome
                "cooling_advantage": cool,
                "mean_lst_tree": mean_tree_lst,
                "mean_lst_reference": mean_ref_lst,
                # mechanism (tree pixels)
                "mean_et_tree": mean_et,
                "mean_esi_tree": mean_esi,
                # stressor (tree pixels)
                "mean_csi_tree": mean_csi,
                "mean_vpd_z_tree": mean_vpd_z,
                "mean_water_supply_z_tree": mean_ndmi_z,
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


# Canonical master-table column order (grouped: identifiers / outcome / mechanism /
# stressor / modifiers / neighborhood / counts). Kept as a module constant so the saved
# file and the tests agree on the schema.
MASTER_COLUMNS = [
    # identifiers
    "neighborhood_id", "overpass_timestamp", "overpass_key", "city",
    # primary outcome
    "cooling_advantage", "mean_lst_tree", "mean_lst_reference",
    # mechanism (tree pixels)
    "mean_et_tree", "mean_esi_tree",
    # stressor (tree pixels)
    "mean_csi_tree", "mean_vpd_z_tree", "mean_water_supply_z_tree",
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
    "identifiers": ["neighborhood_id", "overpass_timestamp", "overpass_key", "city"],
    "primary_outcome": ["cooling_advantage"],
    "mechanism": ["mean_et_tree", "mean_esi_tree"],
    "stressor": ["mean_csi_tree", "mean_vpd_z_tree", "mean_water_supply_z_tree"],
    "modifiers": ["mean_impervious", "mean_canopy", "aridity", "irrigation_proxy",
                  "functional_type"],
    "neighborhood": ["median_income", "pct_poc", "svi"],
    "counts": ["n_tree_px", "n_ref_px", "n_good_obs"],
}


# =========================================================================== #
# IO + QC
# =========================================================================== #
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
    """PRINT the deliverable QC (step 2-5 of the definition of done) and return a summary.

    Confirms one row per (neighborhood, overpass) (no duplicate keys), lists the columns
    by protocol group, prints the cooling_advantage distribution (incl. # negative), the
    irrigation_proxy formula, and the pixel-count ranges (so the thin paired sample is
    visible). Returns a dict of the headline numbers.
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
    for c in ("mean_et_tree", "mean_esi_tree", "mean_csi_tree", "mean_vpd_z_tree",
              "mean_water_supply_z_tree", "aridity"):
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


# =========================================================================== #
# Figure (optional QA)
# =========================================================================== #
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


# =========================================================================== #
# Verification (re-open the saved table + re-check the invariants)
# =========================================================================== #
def verify_master_table(out_path: Path) -> "pd.DataFrame":
    """Re-open the saved Parquet and ASSERT the master-table invariants.

    Confirms: every canonical column present; one row per (neighborhood, overpass) (no
    duplicate keys); <= 9 neighborhoods and <= 66 overpasses; city == 'Phoenix';
    cooling_advantage == mean_lst_reference - mean_lst_tree (the step-67 identity) on the
    finite rows; n_good_obs == min(n_tree_valid, n_ref_valid); and every emitted row has
    n_tree_valid >= 1 AND n_ref_valid >= 1 (the row-emission rule). Returns the table.
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
    # n_good_obs == min(tree_valid, ref_valid); row-emission rule.
    assert (master["n_good_obs"]
            == np.minimum(master["n_tree_valid"], master["n_ref_valid"])).all(), \
        "n_good_obs != min(n_tree_valid, n_ref_valid)"
    assert (master["n_tree_valid"] >= 1).all() and (master["n_ref_valid"] >= 1).all(), \
        "an emitted row violates the >=1 tree AND >=1 reference finite-LST rule"
    log.info("  ASSERTIONS PASSED: all columns present; one row per (neighborhood, "
             "overpass); cooling_advantage == ref - tree; n_good_obs == min(...); "
             "every row has >=1 finite tree & reference pixel.")
    return master


# =========================================================================== #
# Orchestration / CLI
# =========================================================================== #
def run(make_figures: bool = True, verify_only: bool = False) -> dict:
    config.ensure_dirs()
    interim = config.INTERIM_DIR
    processed = config.PROCESSED_DIR
    out_path = processed / MASTER_PARQUET
    results: dict = {}

    if not verify_only:
        # ---- inputs ------------------------------------------------------- #
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

        # ---- per-BG static table + irrigation proxy (step 70) ------------- #
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

        # ---- assemble + save (steps 67-69, 71) ---------------------------- #
        master = build_master_table(grids, static)
        write_master_table(master, out_path)
        results["master_parquet"] = out_path

    # ---- re-open + QC (steps 2-5 of the definition of done) --------------- #
    master = verify_master_table(out_path)
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
