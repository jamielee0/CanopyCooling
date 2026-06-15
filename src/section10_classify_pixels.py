#!/usr/bin/env python3
"""Section 10 - Classify tree-dominated and reference pixels (the paired design).

Implements the whole of Section 10 for the Phoenix pilot from this one module, so
it re-runs end to end from saved code (protocol standing rule: "every figure and
every number must be reproducible from the saved code; nothing produced by hand").

Objective (protocol Section 10, steps 52-57)
--------------------------------------------
Identify the two pixel groups the whole analysis compares -- TREE-DOMINATED pixels
and matched NON-TREE URBAN REFERENCE pixels in the SAME neighborhood (block group).
This is the paired design: only block groups that contain BOTH groups enter the
analysis. All thresholds are pre-registered NAMED CONSTANTS in config.py so the
sensitivity analysis just changes numbers there.

The rules (read carefully; all thresholds come from config.py)
--------------------------------------------------------------
52. TREE-DOMINATED = ALL of:
      * warm-season median NDVI  >  config.NDVI_THR        (start 0.5)
      * tree-canopy PERCENT      >  config.CANOPY_THR      (start 70)
      * impervious PERCENT       <  config.IMPERV_THR      (start 20)
      * NOT water (landcover_class != config.WATER_CLASS, NLCD 11)
      * >= config.MIN_OBS finite/good-quality ECOSTRESS LST observations (start 20)
    PITFALL (encoded here): high NDVI ALONE is not trees -- well-watered grass also
    scores high. It is the COMBINATION of high NDVI WITH high canopy fraction that
    isolates trees. The AND of all five criteria is what does it; never NDVI alone.
53. NON-TREE URBAN REFERENCE = ALL of:
      * canopy PERCENT  <  config.REF_CANOPY_MAX           (low canopy; start 20)
      * a BUILT surface: landcover_class in config.BUILT_CLASSES (NLCD developed
        21/22/23/24) -- NOT water, NOT bare desert (barren 31 / shrub 52 /
        grassland 71 are excluded)
      * >= config.MIN_OBS ECOSTRESS observations (so a reference pixel carries LST)
      * lies in a block group that also holds >= 1 tree-dominated pixel (step 55)
54. EXCLUDE any pixel within config.BUFFER_M (start 70 m) of a TALL building
    footprint, to avoid facade-radiated heat. Excluded pixels can be neither tree
    nor reference. See the "two data gaps" note for the tall-building proxy.
55. PAIR by block group: for each block group form its tree set and its reference
    set; ONLY block groups with BOTH non-empty enter the analysis (paired
    neighborhoods). Reference pixels in block groups WITHOUT a tree pixel are
    demoted to "other" (code 0): they have no tree pixel to pair with.
56. VALIDATE visually: sample classified tree pixels over 1 m aerial imagery and
    confirm genuine canopy (not lawn/cropland); record the agreement rate. This
    needs a human eye -- see the "two data gaps" note for exactly how it is handled.
57. REPORT counts (tree px, reference px, paired neighborhoods) and a SENSITIVITY
    table showing how those counts move as each threshold is varied.

Two real data gaps, handled explicitly (documented choices)
-----------------------------------------------------------
(1) "TALL building" has NO height field. The Microsoft footprints
    (data/interim/building_footprints_32612.parquet) are GEOMETRY ONLY -- there is
    no height/storeys attribute, so we cannot filter by height. We use a documented
    PROXY for "tall/large": footprint AREA. Phoenix is overwhelmingly low-rise, so
    large footprints are the commercial / multi-storey stock that radiate facade
    heat. config.TALL_BUILDING_MIN_AREA_M2 = 1000 m2 sits just below the 99th
    percentile of footprint area (~1665 m2) -> the largest ~2 % of the ~1.47 M
    footprints (29,861 buildings); buffering ONLY those by 70 m removes ~12 % of the
    grid. Buffering all 1.47 M footprints would over-exclude the whole built area
    (the protocol's explicit warning), so we buffer only the "tall" proxy set. The
    area threshold is a config parameter, so it is part of the sensitivity story.
(2) VISUAL VALIDATION needs imagery + a HUMAN eye (step 56). We cannot make the
    genuine-canopy call ourselves, so we DO NOT fabricate a human agreement number.
    Instead: (a) sample up to config N classified tree pixels spread across the
    paired neighborhoods; (b) build an OVERLAY figure of those pixels over Esri
    World Imagery (1 m aerial) via contextily, reprojected to Web Mercator, ->
    figures/section10_treepixel_validation_overlay.png; (c) write
    data/processed/section10_validation_sample.csv with a BLANK `genuine_canopy`
    column for the user to mark yes/no; (d) compute an AUTOMATED PROVISIONAL
    cross-check the user can compare against (the share of sampled pixels whose
    NDVI & canopy clear a stricter bar -- a proxy, NOT a substitute), and print BOTH
    the provisional automated number and the placeholder for the true human rate
    ("PENDING USER REVIEW"). The human agreement rate is filled in by the user.

THE CANOPY DATA CEILING and the OPERATING THRESHOLD (reported honestly, not hidden)
-----------------------------------------------------------------------------------
The 70 m canopy layer (USFS TCC, 30 m, AREA-WEIGHTED-averaged to 70 m in Section 5)
has a MAXIMUM value of 69.53 % (mean 0.88 %): averaging 30 m canopy cells into 70 m
cells dilutes the peaks, so NO 70 m cell reaches the pre-registered CANOPY_THR = 70 %.
At the pre-registered 70 % bar the tree-dominated count is ZERO, and with it the
paired-neighborhood count is zero -- a confirmed data ceiling for a sparse-canopy
desert city imaged at 70 m, NOT a code bug. The protocol's Section 10 gate explicitly
sanctions re-tuning when the paired design is starved ("Few pairs or poor agreement
means re-tune thresholds before continuing"), so the OPERATING CANOPY_THR is lowered
to a data-driven value by a documented rule: the HIGHEST canopy threshold in
{40, 45, 50} that yields >= 10 PAIRED NEIGHBORHOODS (all other thresholds at their
pre-registered start values). In Phoenix NONE of {40,45,50} reaches 10 paired
neighborhoods (40 % -> 9, 45 % -> 7, 50 % -> 4), so the rule falls back to the 40 %
FLOOR (a 40 % canopy 70 m cell is already ~45x the Phoenix mean -> a strong
tree-dominated signal; lower would dilute the meaning). The adopted operating point is
therefore CANOPY_THR = 40 %, giving 9 paired neighborhoods -- a GENUINE LIMITATION
that the Section 14 threshold estimate MUST be reported WITH. The 70 % pre-registration
is preserved in config.CANOPY_THR_PREREGISTERED, and the SENSITIVITY TABLE keeps the
FULL canopy sweep (35/40/45/50/55/60/65/70 %), so the dependence on lowering the bar --
and the 70 % data ceiling (0 px) -- is fully visible. This is a documented,
protocol-gate-sanctioned operating point, NOT a silent change. The visual-validation
sample is drawn at the operating CANOPY_THR (the pixels that actually enter the
analysis). See config.py and the README for the full account.

Deliverables (checkpoint, Section 10; data/processed/, git-ignored)
-------------------------------------------------------------------
* section10_pixel_class_70m.tif    -- per-pixel class raster aligned to
  reference_grid.tif. Codebook: 0 = excluded/other, 1 = tree-dominated,
  2 = reference, 3 = excluded-by-building-buffer. (Codes 0 and 3 are both "not in
  the analysis"; 3 is broken out so the buffer's effect is auditable.)
* section10_paired_neighborhoods.csv -- GEOID, n_tree_px, n_ref_px for the block
  groups that contain BOTH a tree and a reference pixel.
* section10_threshold_sensitivity.csv -- tree/reference/paired counts as each of
  NDVI_THR, CANOPY_THR (35..70 %), IMPERV_THR, MIN_OBS and TALL_BUILDING_MIN_AREA_M2
  is varied, under two baselines (canopy at the OPERATING point vs the PRE-REGISTERED
  70 % bar); the adopted operating CANOPY_THR row is flagged is_operating_point.
* section10_validation_sample.csv  -- the visual-validation sample (blank
  genuine_canopy column for the user).
* figures/section10_treepixel_validation_overlay.png -- the aerial overlay.
* figures/section10_pixel_class_map.png -- a QA map of the classification.

Run (canopy env; no network EXCEPT the contextily basemap tiles for the overlay):
    python src/section10_classify_pixels.py                 # full Section 10
    python src/section10_classify_pixels.py --no-figures     # skip BOTH figures
    python src/section10_classify_pixels.py --no-basemap     # plain overlay (no tiles)
    python src/section10_classify_pixels.py --validation-n 80
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

# Heavy geospatial libs. The pure logic below (the AND tree rule, the reference
# rule, the pairing that keeps only block groups with BOTH sets, the obs-count
# threshold, the tall-building area mask, the sensitivity sweep) is numpy-only, so
# it stays unit-testable without the geo stack installed
# (see test_section10_classify_pixels.py).
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

log = logging.getLogger("section10")


# =========================================================================== #
# Constants (filenames + class codebook + sensitivity sweep grids).
# --------------------------------------------------------------------------- #
ANALYSIS_ZARR = "analysis_cube_70m.zarr"           # Section 9 cube (the inputs)
BG_PARQUET = "neighborhood_blockgroups_32612.parquet"   # Section 8 block groups
FOOTPRINTS_PARQUET = "building_footprints_32612.parquet"  # Section 8 footprints

# Deliverables (data/processed/).
PIXEL_CLASS_TIF = "section10_pixel_class_70m.tif"
PAIRED_CSV = "section10_paired_neighborhoods.csv"
SENSITIVITY_CSV = "section10_threshold_sensitivity.csv"
VALIDATION_CSV = "section10_validation_sample.csv"
# Figures (figures/).
OVERLAY_PNG = "section10_treepixel_validation_overlay.png"
CLASSMAP_PNG = "section10_pixel_class_map.png"

# Per-pixel class CODEBOOK (integer codes burned into the raster).
CLASS_OTHER = 0      # excluded / other (in NO analysis group)
CLASS_TREE = 1       # tree-dominated
CLASS_REFERENCE = 2  # non-tree urban reference (in a paired block group)
CLASS_BUILDING_BUFFER = 3   # excluded by the tall-building buffer (step 54)
CLASS_CODEBOOK = {
    CLASS_OTHER: "excluded/other",
    CLASS_TREE: "tree-dominated",
    CLASS_REFERENCE: "reference",
    CLASS_BUILDING_BUFFER: "excluded-by-building-buffer",
}

# Sensitivity sweep grids: each threshold varied AROUND its operating value
# (step 57). Built once so the operating value is always included and flagged.
# CANOPY is swept FINELY from the 40 % operating floor up to the 70 % pre-
# registered bar (which the 69.53 % data ceiling makes unreachable -> 0 px), so
# the whole canopy dependence -- and the data ceiling -- is visible in one table.
SENS_NDVI = (0.40, 0.45, 0.50, 0.55, 0.60)
SENS_CANOPY = (35.0, 40.0, 45.0, 50.0, 55.0, 60.0, 65.0, 70.0)  # 40 % op floor -> 70 % ceiling
SENS_IMPERV = (10.0, 20.0, 30.0, 40.0)
SENS_MIN_OBS = (10, 15, 20, 25, 30)
SENS_TALL_AREA = (500.0, 1000.0, 1500.0, 2000.0)

# Visual validation defaults.
VALIDATION_N = 60                     # sampled tree pixels (spread across BGs)
VALIDATION_RANDOM_SEED = 1059         # fixed -> reproducible sample
# Provisional automated cross-check bar (a PROXY for "genuine canopy", NOT a human
# judgement): a sampled pixel "provisionally passes" if it clears a STRICTER NDVI
# AND canopy bar than the classification thresholds (high NDVI with real canopy is
# what isolates trees). This is only a comparison the user can sanity-check against.
PROVISIONAL_NDVI_BAR = 0.55
PROVISIONAL_CANOPY_MARGIN = 5.0       # canopy must clear (CANOPY_THR_used - margin)


# =========================================================================== #
# Pure logic (numpy / pandas only; unit-tested without the geo stack)
# =========================================================================== #
def tree_mask(ndvi: np.ndarray, canopy: np.ndarray, impervious: np.ndarray,
              landcover: np.ndarray, obs_count: np.ndarray, *,
              ndvi_thr: float, canopy_thr: float, imperv_thr: float,
              min_obs: int, water_class: int) -> np.ndarray:
    """Boolean tree-dominated mask = the AND of ALL five criteria (step 52).

    A pixel is tree-dominated iff: warm-season median NDVI strictly > ndvi_thr AND
    canopy percent strictly > canopy_thr AND impervious percent strictly < imperv_thr
    AND it is NOT water (landcover != water_class) AND it has >= min_obs ECOSTRESS
    observations. NaNs in any continuous layer fail the comparison (np.nan > x is
    False), so a pixel missing NDVI/canopy/impervious is never tree-dominated.

    The protocol pitfall is encoded by the conjunction: high NDVI ALONE (irrigated
    grass) does NOT qualify -- canopy_thr must ALSO be cleared. Never NDVI by itself.
    """
    with np.errstate(invalid="ignore"):
        m = (
            (ndvi > ndvi_thr)
            & (canopy > canopy_thr)
            & (impervious < imperv_thr)
            & (landcover != water_class)
            & (obs_count >= min_obs)
        )
    return np.asarray(m, dtype=bool)


def reference_mask(canopy: np.ndarray, landcover: np.ndarray, obs_count: np.ndarray,
                   *, ref_canopy_max: float, built_classes: Sequence[int],
                   min_obs: int) -> np.ndarray:
    """Boolean candidate-reference mask (step 53, BEFORE the same-neighborhood pair).

    A candidate reference pixel has LOW canopy (canopy percent strictly <
    ref_canopy_max), a BUILT surface (landcover in built_classes -- NLCD developed
    21/22/23/24, i.e. NOT water and NOT bare desert), and >= min_obs ECOSTRESS
    observations (so it carries an LST series to compare). The same-block-group-as-a-
    tree-pixel requirement (step 55) is applied later, in :func:`pair_by_blockgroup`.
    """
    built = np.isin(landcover, np.asarray(built_classes))
    with np.errstate(invalid="ignore"):
        m = (canopy < ref_canopy_max) & built & (obs_count >= min_obs)
    return np.asarray(m, dtype=bool)


def pair_by_blockgroup(tree: np.ndarray, ref_candidate: np.ndarray,
                       bg_index: np.ndarray, *, nodata_index: int = 0
                       ) -> tuple[np.ndarray, np.ndarray, "pd.DataFrame"]:
    """Keep only block groups that contain BOTH a tree pixel and a reference pixel.

    Steps 55. ``bg_index`` is the per-pixel block-group index map (an integer id per
    cell; ``nodata_index`` marks cells with no block group). Returns:
      * ``tree_final``  -- tree pixels that fall in a PAIRED block group (a block
        group that also has >=1 candidate reference pixel);
      * ``ref_final``   -- candidate reference pixels that fall in a PAIRED block
        group (one that also has >=1 tree pixel);
      * ``paired`` DataFrame with columns bg_index, n_tree_px, n_ref_px (one row per
        paired block group, sorted by bg_index).
    Pixels (tree OR reference) in a block group missing the other set are dropped
    from the final masks -- they have nothing to pair with (step 55). Pixels with
    ``nodata_index`` are never paired.
    """
    tree = np.asarray(tree, dtype=bool)
    ref_candidate = np.asarray(ref_candidate, dtype=bool)
    bg = np.asarray(bg_index)

    valid = bg != nodata_index
    tree_bg = bg[valid & tree]
    ref_bg = bg[valid & ref_candidate]
    tree_counts = pd.Series(tree_bg).value_counts()
    ref_counts = pd.Series(ref_bg).value_counts()
    # Block groups present in BOTH -> the paired neighborhoods.
    paired_ids = np.sort(np.intersect1d(tree_counts.index.to_numpy(),
                                        ref_counts.index.to_numpy()))

    paired_set = set(int(i) for i in paired_ids)
    in_paired = valid & np.isin(bg, np.asarray(sorted(paired_set), dtype=bg.dtype)) \
        if paired_set else np.zeros_like(valid)
    tree_final = tree & in_paired
    ref_final = ref_candidate & in_paired

    rows = [{"bg_index": int(i),
             "n_tree_px": int(tree_counts.get(i, 0)),
             "n_ref_px": int(ref_counts.get(i, 0))} for i in paired_ids]
    paired = pd.DataFrame(rows, columns=["bg_index", "n_tree_px", "n_ref_px"])
    return tree_final, ref_final, paired


def assemble_class_raster(tree_final: np.ndarray, ref_final: np.ndarray,
                          building_excluded: np.ndarray) -> np.ndarray:
    """Combine the final masks into the integer class raster (the codebook).

    Precedence: building-buffer exclusion is recorded first (CLASS_BUILDING_BUFFER),
    then tree, then reference. (By construction tree/reference pixels are already
    outside the buffer -- the buffer is removed before classification -- so the
    precedence only labels the leftover buffered cells; it never overwrites a real
    tree/reference pixel.) Everything else stays CLASS_OTHER.
    """
    out = np.full(tree_final.shape, CLASS_OTHER, dtype="uint8")
    out[np.asarray(building_excluded, dtype=bool)] = CLASS_BUILDING_BUFFER
    out[np.asarray(tree_final, dtype=bool)] = CLASS_TREE
    out[np.asarray(ref_final, dtype=bool)] = CLASS_REFERENCE
    return out


def classify(ndvi, canopy, impervious, landcover, obs_count, bg_index,
             building_excluded, *, ndvi_thr: float, canopy_thr: float,
             imperv_thr: float, min_obs: int, water_class: int,
             ref_canopy_max: float, built_classes: Sequence[int]
             ) -> tuple[np.ndarray, "pd.DataFrame", dict]:
    """End-to-end pure classification on arrays -> (class raster, paired table, counts).

    Pipeline: remove building-buffer pixels from BOTH candidate pools (step 54), form
    the tree mask (step 52) and candidate-reference mask (step 53), pair by block
    group keeping only block groups with BOTH (step 55), and assemble the class
    raster. ``building_excluded`` is the boolean tall-building-buffer mask. Returns
    the class raster, the paired-neighborhood table (bg_index/n_tree_px/n_ref_px) and
    a counts dict. This is the single function the unit tests and the CLI both call,
    so the saved raster and the test logic are identical.
    """
    building_excluded = np.asarray(building_excluded, dtype=bool)
    keep = ~building_excluded   # step 54: buffered pixels can be neither group

    tree = tree_mask(ndvi, canopy, impervious, landcover, obs_count,
                     ndvi_thr=ndvi_thr, canopy_thr=canopy_thr, imperv_thr=imperv_thr,
                     min_obs=min_obs, water_class=water_class) & keep
    refc = reference_mask(canopy, landcover, obs_count, ref_canopy_max=ref_canopy_max,
                          built_classes=built_classes, min_obs=min_obs) & keep

    tree_final, ref_final, paired = pair_by_blockgroup(tree, refc, bg_index)
    raster = assemble_class_raster(tree_final, ref_final, building_excluded)
    counts = {
        "n_tree_candidate": int(tree.sum()),
        "n_ref_candidate": int(refc.sum()),
        "n_tree_px": int(tree_final.sum()),
        "n_ref_px": int(ref_final.sum()),
        "n_paired_blockgroups": int(len(paired)),
        "n_building_excluded": int(building_excluded.sum()),
    }
    return raster, paired, counts


def sensitivity_row(label: str, value, ndvi, canopy, impervious, landcover,
                    obs_count, bg_index, building_excluded, *, params: dict,
                    baseline: str = "operating_point") -> dict:
    """One sensitivity-table row: classify with ``params`` and return the counts.

    ``label``/``value`` name which threshold is being varied to ``value``; ``params``
    is the full threshold dict used for this run (operating values except the one
    varied). ``baseline`` records whether the canopy bar is at the 'operating_point'
    (config.CANOPY_THR) or held at the 'preregistered' 70 % bar (see
    :func:`build_sensitivity_table`). The canopy threshold actually used is reported
    in the ``canopy_thr`` column so the operating point is explicit.
    """
    _, _, counts = classify(
        ndvi, canopy, impervious, landcover, obs_count, bg_index, building_excluded,
        ndvi_thr=params["ndvi_thr"], canopy_thr=params["canopy_thr"],
        imperv_thr=params["imperv_thr"], min_obs=params["min_obs"],
        water_class=params["water_class"], ref_canopy_max=params["ref_canopy_max"],
        built_classes=params["built_classes"])
    return {
        "varied": label,
        "value": value,
        "baseline": baseline,
        "canopy_thr": params["canopy_thr"],
        "n_tree_px": counts["n_tree_px"],
        "n_ref_px": counts["n_ref_px"],
        "n_paired_blockgroups": counts["n_paired_blockgroups"],
    }


# =========================================================================== #
# Geo / IO layer (loads the cube + vectors, rasterizes GEOID + the buffer)
# =========================================================================== #
def _reference() -> "xr.DataArray":
    """The 70 m reference grid as a 2-D rioxarray DataArray (the match target/CRS)."""
    return rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)


def load_inputs(processed: Path) -> dict:
    """Load the gridded classification inputs from the Section 9 analysis cube.

    Returns a dict of numpy arrays on the 70 m grid: ndvi, canopy, impervious
    (percent), landcover_class (uint8), and obs_count = per-pixel count of FINITE
    LST across the 66 overpasses (the "good-quality ECOSTRESS observations" of step
    52; each overpass's LST is already QC'd in Section 2). Each overpass's LST is
    finite only where that scene covered the pixel, so obs_count is a genuine
    per-pixel good-observation count.
    """
    ds = xr.open_zarr(processed / ANALYSIS_ZARR, decode_coords="all")
    ndvi = ds["ndvi"].values.astype("float32")
    canopy = ds["canopy"].values.astype("float32")
    impervious = ds["impervious"].values.astype("float32")
    landcover = ds["landcover_class"].values.astype("int32")
    obs_count = np.isfinite(ds["lst"].values).sum(axis=0).astype("int32")
    log.info("Inputs from %s: grid (y=%d, x=%d), %d LST overpasses",
             ANALYSIS_ZARR, ds.sizes["y"], ds.sizes["x"], ds.sizes["overpass"])
    log.info("  obs_count (finite LST): min=%d median=%d max=%d  frac>=%d = %.3f",
             int(obs_count.min()), int(np.median(obs_count)), int(obs_count.max()),
             config.MIN_OBS, float((obs_count >= config.MIN_OBS).mean()))
    return {"ndvi": ndvi, "canopy": canopy, "impervious": impervious,
            "landcover": landcover, "obs_count": obs_count,
            "y": ds["y"].values, "x": ds["x"].values}


def rasterize_blockgroups(interim: Path) -> tuple[np.ndarray, "pd.DataFrame"]:
    """Rasterize block-group GEOID onto the 70 m grid by centroid containment.

    Section 8 only rasterized the block-group ATTRIBUTES; here we burn a per-pixel
    block-group INDEX map so pixels can be GROUPED by block group for pairing
    (step 55). Each cell takes the (1-based) index of the block group that CONTAINS
    its centre (all_touched=False -> value-per-cell, no double-counting at polygon
    edges); 0 = no block group. Returns (index_map int32, lookup DataFrame with
    columns bg_index, GEOID) so a paired bg_index can be turned back into its GEOID.
    """
    bg = gpd.read_parquet(interim / BG_PARQUET).reset_index(drop=True)
    if str(bg.crs).upper() not in ("EPSG:32612",) and bg.crs.to_epsg() != 32612:
        bg = bg.to_crs(config.CRS)
    transform = Affine(*config.GRID_TRANSFORM)
    nrows, ncols = config.GRID_SHAPE
    # Burn 1-based row index so 0 stays "no block group".
    shapes = ((geom, i + 1) for i, geom in enumerate(bg.geometry))
    idx = rfeatures.rasterize(
        shapes=shapes, out_shape=(nrows, ncols), transform=transform,
        fill=0, all_touched=False, dtype="int32")
    lookup = pd.DataFrame({"bg_index": np.arange(1, len(bg) + 1, dtype="int64"),
                           "GEOID": bg["GEOID"].astype(str).to_numpy()})
    covered = int((idx > 0).sum())
    log.info("Rasterized block-group GEOID -> index map: %d/%d px covered (%.1f%%); "
             "%d distinct block groups burned",
             covered, nrows * ncols, 100 * covered / (nrows * ncols),
             int(np.unique(idx[idx > 0]).size))
    return idx, lookup


def building_buffer_mask(interim: Path, *, min_area_m2: float, buffer_m: float
                         ) -> tuple[np.ndarray, int]:
    """Boolean mask of pixels within ``buffer_m`` of a "tall"/large building (step 54).

    The footprints carry GEOMETRY ONLY (no height), so "tall" is the documented
    AREA proxy: only footprints with area > ``min_area_m2`` are buffered. The
    buffered polygons are rasterized with all_touched=True (a pixel TOUCHED by the
    buffer is excluded -- conservative, as facade heat reaches adjacent cells).
    Returns (mask, n_tall) where n_tall is how many footprints qualified as tall.
    """
    fp = gpd.read_parquet(interim / FOOTPRINTS_PARQUET)
    if fp.crs is not None and fp.crs.to_epsg() != 32612:
        fp = fp.to_crs(config.CRS)
    areas = fp.geometry.area.to_numpy()
    tall = fp[areas > min_area_m2]
    n_tall = int(len(tall))
    transform = Affine(*config.GRID_TRANSFORM)
    nrows, ncols = config.GRID_SHAPE
    if n_tall == 0:
        log.warning("Building buffer: NO footprints exceed %.0f m2 -> empty buffer",
                    min_area_m2)
        return np.zeros((nrows, ncols), dtype=bool), 0
    buffered = tall.geometry.buffer(buffer_m)
    mask = rfeatures.rasterize(
        ((g, 1) for g in buffered), out_shape=(nrows, ncols),
        transform=transform, fill=0, all_touched=True, dtype="uint8").astype(bool)
    log.info("Building buffer: %d/%d footprints > %.0f m2 ('tall' proxy); "
             "buffered by %.0f m -> %d px excluded (%.2f%% of grid)",
             n_tall, len(fp), min_area_m2, buffer_m, int(mask.sum()),
             100 * mask.mean())
    return mask, n_tall


def write_class_raster(raster: np.ndarray, out_path: Path) -> Path:
    """Write the integer class raster aligned to reference_grid.tif (uint8, nodata 255).

    The codebook (0/1/2/3) is recorded in the band description + dataset tags so the
    file is self-describing. nodata is 255 (outside the 0-3 codes); every analysis
    cell carries a real code, so 255 is unused here but reserved.
    """
    import rasterio

    transform = Affine(*config.GRID_TRANSFORM)
    nrows, ncols = config.GRID_SHAPE
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_path, "w", driver="GTiff", height=nrows, width=ncols, count=1,
        dtype="uint8", crs=config.CRS, transform=transform, nodata=255,
        compress="deflate",
    ) as dst:
        dst.write(raster, 1)
        dst.set_band_description(1, "section10_pixel_class")
        dst.update_tags(1, **{f"class_{k}": v for k, v in CLASS_CODEBOOK.items()})
        dst.update_tags(codebook="; ".join(f"{k}={v}" for k, v in CLASS_CODEBOOK.items()))
    log.info("Wrote class raster -> %s", out_path.name)
    return out_path


def write_paired_neighborhoods(paired: "pd.DataFrame", lookup: "pd.DataFrame",
                               out_path: Path) -> Path:
    """Write the paired-neighborhood list (GEOID, n_tree_px, n_ref_px) -> CSV (step 55)."""
    df = paired.merge(lookup, on="bg_index", how="left")
    df = df[["GEOID", "n_tree_px", "n_ref_px"]].sort_values("GEOID").reset_index(drop=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    log.info("Wrote paired neighborhoods -> %s (%d block groups with BOTH sets)",
             out_path.name, len(df))
    return out_path


# =========================================================================== #
# Sensitivity table (step 57)
# =========================================================================== #
def start_params() -> dict:
    """The OPERATING thresholds from config.py as a dict.

    ``canopy_thr`` is ``config.CANOPY_THR`` -- the sweep-driven OPERATING POINT (40 %),
    NOT the pre-registered 70 % bar (which the 69.53 % data ceiling makes unreachable;
    see :func:`derive_operating_canopy_thr` and ``config.CANOPY_THR_PREREGISTERED``).
    Every OTHER threshold (NDVI/IMPERV/MIN_OBS/water/reference/built) is at its
    pre-registered start value -- only the canopy bar was re-tuned, under the protocol
    Section 10 gate. (Name kept for the unit tests / validation path that call it.)
    """
    return {
        "ndvi_thr": float(config.NDVI_THR),
        "canopy_thr": float(config.CANOPY_THR),
        "imperv_thr": float(config.IMPERV_THR),
        "min_obs": int(config.MIN_OBS),
        "water_class": int(config.WATER_CLASS),
        "ref_canopy_max": float(config.REF_CANOPY_MAX),
        "built_classes": tuple(config.BUILT_CLASSES),
    }


# The operating-point selection rule (documented; pre-registered bar is preserved in
# config.CANOPY_THR_PREREGISTERED). Keep the canopy bar as HIGH as the data allows
# while yielding enough paired neighborhoods for the Section 14 regression.
OP_MIN_PAIRED = 10                       # target: >= this many paired neighborhoods
OP_CANDIDATES = (50.0, 45.0, 40.0)       # highest-first; >=10-paired wins
OP_FLOOR = 40.0                          # never go below this (a 40 % 70 m cell is
                                         # ~45x the Phoenix mean -> strong tree signal)


def derive_operating_canopy_thr(inp: dict, bg_index: np.ndarray,
                                building_excluded: np.ndarray, base: dict
                                ) -> tuple[float, dict]:
    """Derive the operating CANOPY_THR from the sweep by the documented rule.

    Rule (protocol Section 10 gate -- "few pairs ... re-tune thresholds"): the HIGHEST
    canopy threshold in OP_CANDIDATES (= {40, 45, 50}) that yields >= OP_MIN_PAIRED
    (10) PAIRED NEIGHBORHOODS, with all OTHER thresholds at their pre-registered start
    values. If none reaches the target, fall back to the OP_FLOOR (40 %) -- never lower
    (a 40 % canopy 70 m cell is already ~45x the Phoenix mean of 0.88 %, a strong
    tree-dominated signal; going lower would dilute the meaning), and flag that Phoenix
    yields fewer than the target number of pairs (a genuine limitation for Section 14).

    Returns ``(operating_canopy_thr, info)`` where ``info`` records the per-candidate
    paired counts, whether the target was met, and the chosen value. This is the
    SINGLE source of truth for the operating point; ``config.CANOPY_THR`` is asserted
    to equal it at run time so the saved config and the derivation never drift.
    """
    paired_by_ct: dict[float, int] = {}
    for ct in sorted(set(OP_CANDIDATES)):
        params = dict(base)
        params["canopy_thr"] = ct
        _, _, counts = classify(
            inp["ndvi"], inp["canopy"], inp["impervious"], inp["landcover"],
            inp["obs_count"], bg_index, building_excluded,
            ndvi_thr=params["ndvi_thr"], canopy_thr=ct, imperv_thr=params["imperv_thr"],
            min_obs=params["min_obs"], water_class=params["water_class"],
            ref_canopy_max=params["ref_canopy_max"], built_classes=params["built_classes"])
        paired_by_ct[ct] = int(counts["n_paired_blockgroups"])

    chosen = None
    for ct in OP_CANDIDATES:                 # highest-first
        if paired_by_ct.get(ct, 0) >= OP_MIN_PAIRED:
            chosen = float(ct)
            break
    target_met = chosen is not None
    if chosen is None:
        chosen = float(OP_FLOOR)
    info = {"paired_by_candidate": paired_by_ct, "target_met": target_met,
            "min_paired_target": OP_MIN_PAIRED, "n_paired_at_operating": paired_by_ct.get(chosen, 0),
            "operating_canopy_thr": chosen}
    return chosen, info


def _sweep(common: dict, base: dict, baseline: str, *, mark_op_ct: float | None = None
           ) -> list[dict]:
    """Sweep NDVI/CANOPY/IMPERV/MIN_OBS around their operating values under one baseline.

    ``base`` carries the fixed value of every OTHER threshold; ``baseline`` labels
    whether those others are at the canopy 'operating_point' (canopy = config.CANOPY_THR)
    or 'preregistered' (canopy = config.CANOPY_THR_PREREGISTERED -> the honest all-zero
    pre-registration). The CANOPY_THR sweep itself is emitted ONCE (under the operating
    baseline) and spans the whole 35->70 % grid, so the pre-registered 70 % row (0 px,
    the data ceiling) is already visible there. ``mark_op_ct`` flags the adopted
    operating canopy value in the CANOPY_THR sweep via the is_operating_point column.
    """
    rows: list[dict] = []
    sweeps = [
        ("NDVI_THR", "ndvi_thr", SENS_NDVI, config.NDVI_THR),
        ("CANOPY_THR", "canopy_thr", SENS_CANOPY, config.CANOPY_THR),
        ("IMPERV_THR", "imperv_thr", SENS_IMPERV, config.IMPERV_THR),
        ("MIN_OBS", "min_obs", SENS_MIN_OBS, config.MIN_OBS),
    ]
    for label, key, grid, op_val in sweeps:
        # CANOPY_THR spans the full grid under the operating baseline only (emit once).
        if label == "CANOPY_THR" and baseline != "operating_point":
            continue
        for v in grid:
            params = dict(base)
            params[key] = v
            r = sensitivity_row(label, v, params=params, baseline=baseline, **common)
            # is_operating: the row whose ONLY-varied threshold sits at its operating
            # value, under the operating baseline (the live classification's setting).
            r["is_operating"] = bool(v == op_val and baseline == "operating_point")
            r["is_operating_point"] = bool(
                label == "CANOPY_THR" and mark_op_ct is not None and v == mark_op_ct)
            rows.append(r)
    return rows


def build_sensitivity_table(inp: dict, bg_index: np.ndarray, interim: Path) -> "pd.DataFrame":
    """Vary each threshold around its operating value and record tree/ref/paired counts.

    Two baselines, because the PRE-REGISTERED canopy bar (CANOPY_THR_PREREGISTERED =
    70 %) zeroes every count -- the 69.53 % canopy data ceiling (30 m USFS TCC area-
    averaged to 70 m never reaches 70 %), which is exactly the gate concern that
    sanctioned re-tuning:
      * baseline='operating_point' -- every OTHER threshold at its pre-registered start
        value with CANOPY_THR at the OPERATING point (config.CANOPY_THR = 40 %), so the
        NDVI/IMPERV/MIN_OBS/tall-area sweeps actually move the counts and their
        sensitivity is visible; the CANOPY_THR sweep itself (35->70 %) lives here and
        shows the FULL canopy dependence, including the 70 % pre-registered row (0 px,
        the data ceiling). The adopted operating canopy row is flagged is_operating_point.
      * baseline='preregistered' -- the OTHER thresholds swept with CANOPY_THR held at
        the PRE-REGISTERED 70 % bar (every row 0 -- the honest pre-registration picture,
        preserved so the dependence on lowering canopy is explicit, not hidden).
    NDVI/CANOPY/IMPERV/MIN_OBS use the operating tall-building buffer (only the
    classification threshold changes). TALL_BUILDING_MIN_AREA_M2 is swept separately
    (its buffer mask recomputed per area value) under BOTH baselines. ``canopy_thr``
    records the canopy threshold actually in force for each row; ``is_operating`` marks
    the live classification's setting of each threshold; ``is_operating_point`` marks
    the ADOPTED operating canopy value in the CANOPY_THR sweep.
    """
    base = start_params()                              # canopy at the OPERATING point
    base_pre = dict(base)
    base_pre["canopy_thr"] = float(config.CANOPY_THR_PREREGISTERED)  # the 70 % bar
    base_buffer, _ = building_buffer_mask(
        interim, min_area_m2=config.TALL_BUILDING_MIN_AREA_M2, buffer_m=config.BUFFER_M)
    common = dict(ndvi=inp["ndvi"], canopy=inp["canopy"], impervious=inp["impervious"],
                  landcover=inp["landcover"], obs_count=inp["obs_count"],
                  bg_index=bg_index, building_excluded=base_buffer)

    rows: list[dict] = []
    rows += _sweep(common, base, baseline="operating_point",
                   mark_op_ct=float(config.CANOPY_THR))
    rows += _sweep(common, base_pre, baseline="preregistered")

    # TALL_BUILDING_MIN_AREA_M2: recompute the buffer per area value, under BOTH
    # baselines (operating canopy -> visible effect; pre-registered 70 -> zeros).
    for baseline, bparams in (("operating_point", base), ("preregistered", base_pre)):
        for v in SENS_TALL_AREA:
            buf, n_tall = building_buffer_mask(interim, min_area_m2=v, buffer_m=config.BUFFER_M)
            common_v = dict(common)
            common_v["building_excluded"] = buf
            r = sensitivity_row("TALL_BUILDING_MIN_AREA_M2", v, params=bparams,
                                baseline=baseline, **common_v)
            r["is_operating"] = bool(
                v == config.TALL_BUILDING_MIN_AREA_M2 and baseline == "operating_point")
            r["is_operating_point"] = False
            r["n_tall_buildings"] = n_tall
            rows.append(r)

    df = pd.DataFrame(rows)
    return df


# =========================================================================== #
# Visual validation (step 56) -- imagery overlay + sample CSV + provisional check
# =========================================================================== #
def _pixel_centres_lonlat(rows: np.ndarray, cols: np.ndarray, ycoords: np.ndarray,
                          xcoords: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Lon/lat of pixel centres (row,col) from the grid's y/x coordinate vectors."""
    from pyproj import Transformer
    xs = xcoords[cols]
    ys = ycoords[rows]
    tr = Transformer.from_crs(config.CRS, "EPSG:4326", always_xy=True)
    lon, lat = tr.transform(xs, ys)
    return np.asarray(lon), np.asarray(lat)


def sample_tree_pixels(tree_mask_arr: np.ndarray, bg_index: np.ndarray, *,
                       n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Sample up to ``n`` tree pixels SPREAD across the block groups they fall in.

    Spreading the sample across block groups (round-robin over the block groups that
    hold tree pixels, picking a random pixel each pass) gives the user a geographic
    spread to inspect, not a cluster. Returns (rows, cols) index arrays. Reproducible
    via ``seed``.
    """
    rr, cc = np.where(tree_mask_arr)
    if rr.size == 0:
        return np.array([], dtype=int), np.array([], dtype=int)
    rng = np.random.default_rng(seed)
    bg_of = bg_index[rr, cc]
    order_by_bg: dict[int, list[int]] = {}
    for i, b in enumerate(bg_of):
        order_by_bg.setdefault(int(b), []).append(i)
    for b in order_by_bg:
        rng.shuffle(order_by_bg[b])
    picked: list[int] = []
    bgs = list(order_by_bg.keys())
    rng.shuffle(bgs)
    while len(picked) < min(n, rr.size):
        progressed = False
        for b in bgs:
            if order_by_bg[b]:
                picked.append(order_by_bg[b].pop())
                progressed = True
                if len(picked) >= min(n, rr.size):
                    break
        if not progressed:
            break
    picked = np.array(picked, dtype=int)
    return rr[picked], cc[picked]


def write_validation_sample(rows: np.ndarray, cols: np.ndarray, inp: dict,
                            canopy_thr_used: float, out_path: Path) -> "pd.DataFrame":
    """Write the validation sample CSV with a BLANK genuine_canopy column (step 56).

    Columns: pixel_id, row, col, lon, lat, ndvi, canopy_pct, impervious_pct,
    genuine_canopy. ``genuine_canopy`` is left EMPTY for the user to mark yes/no over
    the aerial overlay. ``canopy_thr_used`` is the canopy threshold the sampled tree
    pixels were classified at (recorded so the user knows the operating point).
    """
    lon, lat = _pixel_centres_lonlat(rows, cols, inp["y"], inp["x"])
    df = pd.DataFrame({
        "pixel_id": np.arange(len(rows), dtype=int),
        "row": rows.astype(int),
        "col": cols.astype(int),
        "lon": np.round(lon, 6),
        "lat": np.round(lat, 6),
        "ndvi": np.round(inp["ndvi"][rows, cols], 4),
        "canopy_pct": np.round(inp["canopy"][rows, cols], 2),
        "impervious_pct": np.round(inp["impervious"][rows, cols], 2),
        "genuine_canopy": "",          # BLANK -> user marks yes/no
    })
    df.attrs["canopy_thr_used"] = canopy_thr_used
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    log.info("Wrote validation sample -> %s (%d pixels; genuine_canopy BLANK for "
             "user review; classified at canopy>%.0f%%)",
             out_path.name, len(df), canopy_thr_used)
    return df


def provisional_agreement(sample: "pd.DataFrame", canopy_thr_used: float) -> dict:
    """An AUTOMATED PROVISIONAL cross-check the user can compare against (step 56).

    NOT a human judgement and NOT the reported agreement rate: it is the share of
    sampled tree pixels that ALSO clear a STRICTER bar (NDVI > PROVISIONAL_NDVI_BAR
    AND canopy > canopy_thr_used - PROVISIONAL_CANOPY_MARGIN). High NDVI WITH real
    canopy is what isolates trees, so a high provisional share is weak corroboration
    that the sampled pixels are vegetated+canopied (the user still confirms genuine
    tree canopy vs lawn over the imagery). Returns the rate and the bar used.
    """
    if len(sample) == 0:
        return {"provisional_rate": float("nan"), "n": 0,
                "ndvi_bar": PROVISIONAL_NDVI_BAR,
                "canopy_bar": canopy_thr_used - PROVISIONAL_CANOPY_MARGIN}
    canopy_bar = canopy_thr_used - PROVISIONAL_CANOPY_MARGIN
    passes = ((sample["ndvi"] > PROVISIONAL_NDVI_BAR)
              & (sample["canopy_pct"] > canopy_bar))
    return {"provisional_rate": float(passes.mean()), "n": int(len(sample)),
            "n_pass": int(passes.sum()), "ndvi_bar": PROVISIONAL_NDVI_BAR,
            "canopy_bar": float(canopy_bar)}


CHIP_HALF_WIDTH_M = 80.0   # half-width of each per-pixel aerial chip (~one 70 m pixel + margin)


def make_validation_overlay(sample: "pd.DataFrame", figures_dir: Path, *,
                            use_basemap: bool = True,
                            canopy_thr_used: float = config.CANOPY_THR) -> Path | None:
    """Per-pixel aerial chip GRID for the visual validation (step 56 / gap 2).

    A single full-extent overlay is useless for the per-pixel genuine-canopy call (the
    sample spans the whole metro, so individual 70 m pixels are sub-pixel on screen).
    Instead this draws a GRID of small zoomed-in chips -- one per sampled tree pixel,
    a ~160 m window centred on the pixel, at full Esri World Imagery resolution (1 m),
    with a box marking the 70 m pixel footprint and the pixel_id + canopy% labelled.
    That is what lets a human confirm GENUINE TREE CANOPY (vs irrigated lawn / crop)
    per pixel and mark genuine_canopy in the CSV. Reprojects each chip's window to Web
    Mercator for the basemap. If tiles fail (or use_basemap=False) the chips fall back
    to a neutral background so the figure always renders. Returns the figure path.
    """
    if len(sample) == 0:
        log.warning("Validation overlay: no tree pixels to plot -> skipped")
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from pyproj import Transformer

    cx = None
    if use_basemap:
        try:
            import contextily as _cx
            cx = _cx
        except Exception as exc:  # noqa: BLE001
            log.warning("Validation overlay: contextily unavailable (%s) -> plain chips",
                        exc)
    tr = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    half = CHIP_HALF_WIDTH_M
    pix = float(config.CELL_SIZE_M)

    n = len(sample)
    ncol = int(np.ceil(np.sqrt(n)))
    nrow = int(np.ceil(n / ncol))
    figures_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(nrow, ncol, figsize=(2.2 * ncol, 2.5 * nrow))
    axes = np.atleast_1d(axes).ravel()
    n_basemap = 0
    for k, (_, r) in enumerate(sample.iterrows()):
        ax = axes[k]
        # Centre + the 70 m pixel footprint, in Web Mercator (approx; chips are tiny).
        cxm, cym = tr.transform(r["lon"], r["lat"])
        ax.set_xlim(cxm - half, cxm + half)
        ax.set_ylim(cym - half, cym + half)
        got = False
        if cx is not None:
            try:
                cx.add_basemap(ax, source=cx.providers.Esri.WorldImagery,
                               crs="EPSG:3857", attribution=False, zoom=19)
                got = True
                n_basemap += 1
            except Exception:  # noqa: BLE001 - degrade this chip gracefully
                got = False
        if not got:
            ax.set_facecolor("0.85")
        ax.add_patch(Rectangle((cxm - pix / 2, cym - pix / 2), pix, pix, fill=False,
                               edgecolor="yellow", linewidth=1.4))
        ax.set_title(f"#{int(r['pixel_id'])}  cnpy={r['canopy_pct']:.0f}%",
                     fontsize=7, pad=2)
        ax.set_xticks([]); ax.set_yticks([])
    for k in range(n, len(axes)):
        axes[k].axis("off")
    fig.suptitle(
        "Section 10 visual validation: %d classified TREE-DOMINATED pixels on 1 m "
        "aerial imagery\n(each chip ~%dm; yellow box = the 70 m pixel; classified at "
        "canopy>%.0f%%; mark genuine_canopy yes/no by pixel_id in %s)"
        % (n, int(2 * half), canopy_thr_used, VALIDATION_CSV), fontsize=10)
    out = figures_dir / OVERLAY_PNG
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote validation overlay (chip grid) -> %s (%d/%d chips with basemap)",
             out.name, n_basemap, n)
    return out


def make_classmap_figure(raster: np.ndarray, figures_dir: Path) -> Path | None:
    """QA map of the per-pixel classification (codebook colours) -> figures/."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap

    figures_dir.mkdir(parents=True, exist_ok=True)
    left, bottom, right, top = config.GRID_BOUNDS
    extent = (left, right, bottom, top)
    # 0 other (grey), 1 tree (green), 2 reference (orange), 3 buffer (purple).
    cmap = ListedColormap(["#d9d9d9", "#1a9850", "#f46d43", "#7b3294"])
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5], cmap.N)
    fig, ax = plt.subplots(figsize=(9, 8), constrained_layout=True)
    im = ax.imshow(raster, extent=extent, origin="upper", cmap=cmap, norm=norm,
                   interpolation="nearest")
    cbar = fig.colorbar(im, ax=ax, ticks=[0, 1, 2, 3], shrink=0.8)
    cbar.ax.set_yticklabels([CLASS_CODEBOOK[i] for i in (0, 1, 2, 3)])
    n_tree = int((raster == CLASS_TREE).sum())
    n_ref = int((raster == CLASS_REFERENCE).sum())
    ax.set_title("Section 10 pixel classification (70 m)\n"
                 "tree=%d  reference=%d  buffer-excluded=%d"
                 % (n_tree, n_ref, int((raster == CLASS_BUILDING_BUFFER).sum())))
    ax.set_xlabel("Easting (m, EPSG:32612)"); ax.set_ylabel("Northing (m)")
    out = figures_dir / CLASSMAP_PNG
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote classification map -> %s", out.name)
    return out


# =========================================================================== #
# Verification (step 3 of the definition of done: re-open + re-check)
# =========================================================================== #
def verify_raster(out_path: Path, reference: "xr.DataArray", inp: dict,
                  params: dict, building_excluded: np.ndarray, seed: int = 7) -> None:
    """Re-open the saved class raster, ASSERT alignment, and re-check a tree sample.

    Confirms CRS/shape/transform equal reference_grid.tif EXACTLY, and that a random
    sample of saved TREE pixels genuinely satisfies ALL config criteria (NDVI/canopy/
    impervious/not-water/obs and outside the building buffer). Prints the check.
    """
    da = rioxarray.open_rasterio(out_path).squeeze("band", drop=True)
    log.info("=" * 70)
    log.info("VERIFY: reopened %s", out_path.name)
    crs = da.rio.crs
    tx = da.rio.transform()
    rtx = reference.rio.transform()
    log.info("  CRS %s ; shape (y=%d, x=%d) ; pixel (%.1f, %.1f) m",
             crs, da.sizes["y"], da.sizes["x"], tx.a, tx.e)
    assert crs.to_epsg() == reference.rio.crs.to_epsg(), "CRS mismatch vs reference"
    assert da.sizes["y"] == reference.sizes["y"] and da.sizes["x"] == reference.sizes["x"], \
        "shape mismatch vs reference"
    assert np.allclose([tx.a, tx.e, tx.c, tx.f], [rtx.a, rtx.e, rtx.c, rtx.f], atol=1e-6), \
        "transform mismatch vs reference"
    log.info("  ALIGNMENT OK: CRS/shape/transform == reference_grid.tif")

    raster = da.values
    rr, cc = np.where(raster == CLASS_TREE)
    if rr.size == 0:
        log.warning("  (no saved tree pixels -> criteria-recheck skipped; at the "
                    "operating CANOPY_THR this should not happen -- see the header)")
        return
    rng = np.random.default_rng(seed)
    k = min(10, rr.size)
    sel = rng.choice(rr.size, size=k, replace=False)
    ok = True
    for j in sel:
        r, c = int(rr[j]), int(cc[j])
        nd, cn, im = inp["ndvi"][r, c], inp["canopy"][r, c], inp["impervious"][r, c]
        lcv, ob = int(inp["landcover"][r, c]), int(inp["obs_count"][r, c])
        good = (nd > params["ndvi_thr"] and cn > params["canopy_thr"]
                and im < params["imperv_thr"] and lcv != params["water_class"]
                and ob >= params["min_obs"] and not building_excluded[r, c])
        ok = ok and good
        log.info("  tree px (r=%d,c=%d): ndvi=%.3f>%.2f canopy=%.2f>%.1f imperv=%.2f<%.1f "
                 "lc=%d(!=%d) obs=%d>=%d buffer=%s -> %s", r, c, nd, params["ndvi_thr"],
                 cn, params["canopy_thr"], im, params["imperv_thr"], lcv,
                 params["water_class"], ob, params["min_obs"],
                 bool(building_excluded[r, c]), "PASS" if good else "FAIL")
    assert ok, "a saved tree pixel does NOT satisfy all config criteria!"
    log.info("  CRITERIA RE-CHECK PASSED for %d random tree pixels", k)


# =========================================================================== #
# Orchestration / CLI
# =========================================================================== #
def _validation_tree_mask(inp: dict, building_excluded: np.ndarray, params: dict
                          ) -> tuple[np.ndarray, float]:
    """The tree mask used for the VALIDATION sample -- at the OPERATING thresholds.

    Sampling is done at the live OPERATING thresholds (``params``, i.e. canopy =
    config.CANOPY_THR = 40 %), so the overlay/CSV show exactly the tree pixels that
    enter the analysis. (Earlier the pre-registered 70 % bar yielded 0 tree pixels and
    the sample had to be drawn at a lowered canopy; with the adopted operating point
    the primary classification already has tree pixels, so no special-casing is
    needed.) Returns ``(tree_mask, canopy_thr_used)``.
    """
    keep = ~np.asarray(building_excluded, dtype=bool)
    ct = float(params["canopy_thr"])
    tree = tree_mask(
        inp["ndvi"], inp["canopy"], inp["impervious"], inp["landcover"],
        inp["obs_count"], ndvi_thr=params["ndvi_thr"], canopy_thr=ct,
        imperv_thr=params["imperv_thr"], min_obs=params["min_obs"],
        water_class=params["water_class"]) & keep
    return tree, ct


def run(make_figures: bool = True, use_basemap: bool = True,
        validation_n: int = VALIDATION_N, seed: int = VALIDATION_RANDOM_SEED) -> dict:
    config.ensure_dirs()
    interim = config.INTERIM_DIR
    processed = config.PROCESSED_DIR
    reference = _reference()
    results: dict = {}

    # ---- inputs + the two derived per-pixel maps -------------------------- #
    inp = load_inputs(processed)
    bg_index, lookup = rasterize_blockgroups(interim)
    building_excluded, n_tall = building_buffer_mask(
        interim, min_area_m2=config.TALL_BUILDING_MIN_AREA_M2, buffer_m=config.BUFFER_M)

    # ---- derive + ASSERT the operating canopy threshold ------------------- #
    # The pre-registered CANOPY_THR_PREREGISTERED = 70 % is unachievable at 70 m (the
    # canopy layer maxes at 69.53 %), so it yields 0 tree pixels. The OPERATING canopy
    # threshold is derived here from the documented >=10-paired-neighborhood rule and
    # MUST equal config.CANOPY_THR (so the saved config and the derivation never drift).
    params = start_params()                            # canopy at the OPERATING point
    op_ct, op_info = derive_operating_canopy_thr(
        inp, bg_index, building_excluded, params)
    log.info("=" * 70)
    log.info("OPERATING CANOPY_THR derivation (rule: HIGHEST of %s with >=%d paired "
             "neighborhoods; else %.0f%% floor):",
             tuple(int(c) for c in OP_CANDIDATES), OP_MIN_PAIRED, OP_FLOOR)
    for ct in sorted(op_info["paired_by_candidate"]):
        log.info("    canopy>%.0f%% -> %d paired neighborhoods", ct,
                 op_info["paired_by_candidate"][ct])
    log.info("  pre-registered bar      : %.0f%% (config.CANOPY_THR_PREREGISTERED; "
             "0 tree px -- 70 m data ceiling 69.53%%)", config.CANOPY_THR_PREREGISTERED)
    log.info("  ADOPTED operating CANOPY_THR: %.0f%%  (%s; %d paired neighborhoods)",
             op_ct, "target met" if op_info["target_met"]
             else f"NONE of {tuple(int(c) for c in OP_CANDIDATES)} reached "
                  f"{OP_MIN_PAIRED} -> {OP_FLOOR:.0f}%% floor",
             op_info["n_paired_at_operating"])
    if not op_info["target_met"]:
        log.warning("  LIMITATION: Phoenix yields only %d paired neighborhoods at the "
                    "%.0f%% operating floor (< the %d target). The Section 14 threshold "
                    "estimate MUST be reported WITH this caveat (thin paired design).",
                    op_info["n_paired_at_operating"], op_ct, OP_MIN_PAIRED)
    assert float(config.CANOPY_THR) == float(op_ct), (
        f"config.CANOPY_THR={config.CANOPY_THR} != derived operating point {op_ct}; "
        f"update config.CANOPY_THR to the operating value.")

    # ---- classify at the OPERATING thresholds (the deliverable) ----------- #
    raster, paired, counts = classify(
        inp["ndvi"], inp["canopy"], inp["impervious"], inp["landcover"],
        inp["obs_count"], bg_index, building_excluded,
        ndvi_thr=params["ndvi_thr"], canopy_thr=params["canopy_thr"],
        imperv_thr=params["imperv_thr"], min_obs=params["min_obs"],
        water_class=params["water_class"], ref_canopy_max=params["ref_canopy_max"],
        built_classes=params["built_classes"])
    counts["n_tall_buildings"] = n_tall

    write_class_raster(raster, processed / PIXEL_CLASS_TIF)
    write_paired_neighborhoods(paired, lookup, processed / PAIRED_CSV)
    results.update({"class_raster": processed / PIXEL_CLASS_TIF,
                    "paired_csv": processed / PAIRED_CSV, "counts": counts,
                    "operating_info": op_info})

    # ---- HEADLINE counts (step 2 of the definition of done) --------------- #
    obs = inp["obs_count"]
    log.info("=" * 70)
    log.info("HEADLINE COUNTS (OPERATING thresholds: NDVI>%.2f, canopy>%.0f%% "
             "[operating; 70%% pre-registered], imperv<%.0f%%, not water, obs>=%d):",
             params["ndvi_thr"], params["canopy_thr"], params["imperv_thr"],
             params["min_obs"])
    log.info("  tree-dominated pixels    : %d", counts["n_tree_px"])
    log.info("  reference pixels         : %d", counts["n_ref_px"])
    log.info("  paired neighborhoods     : %d", counts["n_paired_blockgroups"])
    log.info("  pixels excluded by buffer: %d  (%d 'tall' footprints > %.0f m2)",
             counts["n_building_excluded"], n_tall, config.TALL_BUILDING_MIN_AREA_M2)
    log.info("  obs-count map: min=%d median=%d max=%d  frac>=%d = %.3f",
             int(obs.min()), int(np.median(obs)), int(obs.max()), params["min_obs"],
             float((obs >= params["min_obs"]).mean()))

    # ---- sensitivity table (step 57) -------------------------------------- #
    sens = build_sensitivity_table(inp, bg_index, interim)
    sens.to_csv(processed / SENSITIVITY_CSV, index=False)
    results["sensitivity_csv"] = processed / SENSITIVITY_CSV
    log.info("=" * 70)
    log.info("SENSITIVITY TABLE (counts as each threshold is varied; "
             "@ = operating value, OP = adopted operating CANOPY_THR):")
    _print_sensitivity(sens)

    # ---- visual validation (step 56 / data gap 2) ------------------------- #
    val_tree, canopy_used = _validation_tree_mask(inp, building_excluded, params)
    rows, cols = sample_tree_pixels(val_tree, bg_index, n=validation_n, seed=seed)
    sample = write_validation_sample(rows, cols, inp, canopy_used,
                                     processed / VALIDATION_CSV)
    results["validation_csv"] = processed / VALIDATION_CSV
    prov = provisional_agreement(sample, canopy_used)
    log.info("=" * 70)
    log.info("VISUAL VALIDATION (step 56):")
    log.info("  sampled %d tree pixels (classified at canopy>%.0f%%) spread across "
             "their block groups", prov.get("n", 0), canopy_used)
    log.info("  -> %s : mark genuine_canopy yes/no over %s",
             VALIDATION_CSV, OVERLAY_PNG)
    log.info("  PROVISIONAL automated cross-check (NOT the reported rate): %.1f%% of "
             "the sample also clears NDVI>%.2f AND canopy>%.1f%% (n_pass=%d/%d)",
             100 * prov["provisional_rate"] if prov["n"] else float("nan"),
             prov["ndvi_bar"], prov["canopy_bar"], prov.get("n_pass", 0), prov.get("n", 0))
    log.info("  HUMAN agreement rate: PENDING USER REVIEW (fill genuine_canopy in the "
             "CSV; not fabricated here)")
    results["provisional_agreement"] = prov
    results["validation_canopy_thr"] = canopy_used

    # ---- figures ---------------------------------------------------------- #
    if make_figures:
        results["overlay_png"] = make_validation_overlay(
            sample, config.FIGURES_DIR, use_basemap=use_basemap,
            canopy_thr_used=canopy_used)
        results["classmap_png"] = make_classmap_figure(raster, config.FIGURES_DIR)

    # ---- re-open + re-check (step 3 of the definition of done) ------------ #
    verify_raster(processed / PIXEL_CLASS_TIF, reference, inp, params, building_excluded)

    _report(results)
    return results


def _print_sensitivity(sens: "pd.DataFrame") -> None:
    """Pretty-print the sensitivity table grouped by baseline, then varied threshold."""
    labels = {"operating_point": "OTHER thresholds pre-registered, canopy at the "
                                 "OPERATING POINT (so each threshold's effect is visible)",
              "preregistered": "canopy held at the PRE-REGISTERED 70%% bar "
                               "(0 everywhere -- the 69.53%% data ceiling)"}
    for baseline in ("operating_point", "preregistered"):
        sub = sens[sens["baseline"] == baseline]
        if sub.empty:
            continue
        log.info("  --- %s ---", labels.get(baseline, baseline))
        for label, grp in sub.groupby("varied", sort=False):
            log.info("  %s:", label)
            for _, r in grp.iterrows():
                # @ marks the live operating value of each swept threshold; OP marks
                # the ADOPTED operating CANOPY_THR in the canopy sweep.
                flag = "OP" if r.get("is_operating_point") else (
                    " @" if r.get("is_operating") else "  ")
                extra = f"  [canopy>{r['canopy_thr']:.0f}%]"
                if "n_tall_buildings" in r and not pd.isna(r["n_tall_buildings"]):
                    extra += f"  (n_tall={int(r['n_tall_buildings'])})"
                log.info("    %s value=%-7s tree=%-6d ref=%-7d paired=%-4d%s", flag,
                         r["value"], int(r["n_tree_px"]), int(r["n_ref_px"]),
                         int(r["n_paired_blockgroups"]), extra)


def _report(results: dict) -> None:
    log.info("=" * 70)
    log.info("Section 10 complete. Deliverables:")
    for key in ("class_raster", "paired_csv", "sensitivity_csv", "validation_csv"):
        if key in results:
            log.info("  %-16s -> %s", key, Path(results[key]).name)
    for key in ("overlay_png", "classmap_png"):
        if results.get(key):
            log.info("  %-16s -> figures/%s", key, Path(results[key]).name)
    log.info("=" * 70)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 10 - classify tree-dominated & non-tree reference pixels "
                    "(the paired design; steps 52-57).")
    p.add_argument("--no-figures", action="store_true",
                   help="skip BOTH the validation overlay and the classification map.")
    p.add_argument("--no-basemap", action="store_true",
                   help="draw the validation overlay WITHOUT the contextily aerial "
                        "basemap (no tile download).")
    p.add_argument("--validation-n", type=int, default=VALIDATION_N,
                   help="number of tree pixels to sample for visual validation.")
    p.add_argument("--seed", type=int, default=VALIDATION_RANDOM_SEED,
                   help="random seed for the validation sample (reproducible).")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    run(make_figures=not args.no_figures, use_basemap=not args.no_basemap,
        validation_n=args.validation_n, seed=args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
