"""Central configuration for the Canopy protocol.

Defines canonical project paths, the FIXED analysis geometry (Section 1), the
project time windows, and the locations/environment variables that the external
services read their credentials from. NO SECRETS ARE STORED HERE — this module
only references the standard credential files / env vars that each library
already expects. See src/check_auth.py for the auth smoke test and
src/build_reference_grid.py for the reference-grid derivation.

Section 1 geometry is written as LITERALS, never recomputed at runtime, so every
run is byte-for-byte identical.
"""

from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Project paths (absolute, derived from the repo root = this file's directory).
# --------------------------------------------------------------------------- #
BASE_DIR: Path = Path(__file__).resolve().parent

DATA_DIR: Path = BASE_DIR / "data"
RAW_DIR: Path = DATA_DIR / "raw"
INTERIM_DIR: Path = DATA_DIR / "interim"
PROCESSED_DIR: Path = DATA_DIR / "processed"
MANIFEST_CSV: Path = DATA_DIR / "manifest.csv"

SRC_DIR: Path = BASE_DIR / "src"
NOTEBOOKS_DIR: Path = BASE_DIR / "notebooks"
FIGURES_DIR: Path = BASE_DIR / "figures"
DOCS_DIR: Path = BASE_DIR / "docs"

# Directories that should always exist locally (their contents are git-ignored).
_RUNTIME_DIRS = (RAW_DIR, INTERIM_DIR, PROCESSED_DIR, FIGURES_DIR)


def ensure_dirs() -> None:
    """Create the local runtime directories if they do not already exist."""
    for d in _RUNTIME_DIRS:
        d.mkdir(parents=True, exist_ok=True)


# Canonical output: the geometric anchor every later layer is matched to.
REFERENCE_GRID_TIF: Path = PROCESSED_DIR / "reference_grid.tif"


# ===========================================================================
# SECTION 1 - FIXED ANALYSIS DOMAIN, PROJECTION, GRID, TIME WINDOWS
# ---------------------------------------------------------------------------
# These constants FIX the geometry of the entire project. They are literals,
# never recomputed at runtime, so every run is byte-for-byte identical. The
# grid numbers below were derived ONCE by reprojecting BBOX_LONLAT into
# EPSG:32612 (Transverse Mercator) and snapping the origin to the 70 m
# ECOSTRESS pixel size; see src/build_reference_grid.py for the derivation and
# the regeneration of reference_grid.tif. Do not edit by hand.
# ===========================================================================

# --- domain (study area) ---------------------------------------------------
# (min_lon, max_lon, min_lat, max_lat) in WGS84 degrees.
BBOX_LONLAT: tuple = (-112.55, -111.55, 33.20, 33.92)

# --- projection / resolution ----------------------------------------------
CRS: str = "EPSG:32612"          # UTM zone 12N, WGS84 - the project CRS
CELL_SIZE_M: int = 70            # ECOSTRESS native pixel size (metres)

# --- time windows ----------------------------------------------------------
PILOT_WINDOW: tuple = ("2023-06-01", "2023-09-30")
CLIMATOLOGY_YEARS: tuple = (2018, 2024)   # inclusive (start, end)
SEASON: tuple = ("06-01", "09-30")        # MM-DD start/end of the season

# --- fixed analysis grid (EPSG:32612) -------------------------------------
# Frozen results of reprojecting BBOX_LONLAT -> EPSG:32612 and snapping the
# origin outward to whole multiples of CELL_SIZE_M. ORIGIN is the TOP-LEFT
# corner (x_min, y_max); the grid is north-up with rows increasing southward.
GRID_ORIGIN_XY: tuple = (355460.0, 3754380.0)   # (x_min, y_max)
GRID_NROWS: int = 1155
GRID_NCOLS: int = 1339
GRID_SHAPE: tuple = (GRID_NROWS, GRID_NCOLS)     # (rows, cols)

# Bounds as (left, bottom, right, top) = (x_min, y_min, x_max, y_max), metres.
GRID_BOUNDS: tuple = (355460.0, 3673530.0, 449190.0, 3754380.0)

# North-up affine geotransform in rasterio/Affine order:
#   (a, b, c, d, e, f) -> x = a*col + b*row + c ;  y = d*col + e*row + f
# a = +CELL_SIZE_M, e = -CELL_SIZE_M, (c, f) = top-left corner.
GRID_TRANSFORM: tuple = (70.0, 0.0, 355460.0, 0.0, -70.0, 3754380.0)

# Same transform in GDAL geotransform order, if a tool wants it:
#   (c, a, b, f, d, e) = (left, x_res, 0, top, 0, -y_res)
GRID_GDAL_GEOTRANSFORM: tuple = (355460.0, 70.0, 0.0, 3754380.0, 0.0, -70.0)


# ===========================================================================
# SECTION 10 - PAIRED-DESIGN PIXEL CLASSIFICATION THRESHOLDS
# ---------------------------------------------------------------------------
# The pre-registered ("start") thresholds for classifying tree-dominated and
# non-tree urban reference pixels (protocol steps 52-57). They are NAMED
# CONSTANTS so the sensitivity analysis just changes numbers here. Section 10
# sweeps each of these around its start value and reports how the tree/
# reference/paired-neighborhood counts respond.
#
# Units note: canopy and impervious are stored as PERCENT (0-100) in Section 5,
# so CANOPY_THR / IMPERV_THR / REF_CANOPY_MAX are in PERCENT, not fractions.
# ===========================================================================

# --- tree-dominated pixel = ALL of these (step 52) ------------------------
NDVI_THR: float = 0.5        # warm-season median NDVI strictly above this
# CANOPY_THR is the SENSITIVITY-DRIVEN OPERATING POINT, not the pre-registered
# 70 %. The pre-registered 70 % bar is UNACHIEVABLE at 70 m: the tree-canopy
# layer (USFS TCC, 30 m, AREA-WEIGHTED-averaged to 70 m in Section 5) MAXES at
# 69.53 % (mean 0.88 %), because averaging 30 m canopy cells into 70 m cells
# dilutes the peaks -> ZERO 70 m cells reach 70 %, so the pre-registered bar
# yields 0 tree-dominated pixels and 0 paired neighborhoods (a confirmed data
# ceiling for a sparse-canopy desert city imaged at 70 m, NOT a bug). The
# protocol's Section 10 gate explicitly sanctions re-tuning the threshold when
# the paired design is starved ("Few pairs or poor agreement means re-tune
# thresholds before continuing"). The operating value below was chosen by a
# documented sweep rule: the HIGHEST canopy threshold in {40, 45, 50} that
# yields >= 10 paired neighborhoods; none of {40,45,50} reaches 10 in Phoenix
# (40 % -> 9, 45 % -> 7, 50 % -> 4), so the rule falls back to the 40 % FLOOR
# (a 40 % canopy 70 m cell is already ~45x the Phoenix mean of 0.88 % -> a
# strong tree-dominated signal; going lower would dilute the meaning). At 40 %
# Phoenix yields only 9 paired neighborhoods -- a GENUINE LIMITATION to carry
# into the Section 14 threshold estimate, which MUST be reported WITH this
# caveat. The full dependence is visible in section10_threshold_sensitivity.csv.
# This is a documented, protocol-gate-sanctioned operating point, NOT a silent
# change: CANOPY_THR_PREREGISTERED preserves the 70 % pre-registration.
CANOPY_THR: float = 40.0     # OPERATING tree-canopy PERCENT (sweep-driven; see above)
CANOPY_THR_PREREGISTERED: float = 70.0   # pre-registered bar; unachievable at 70 m
                                         # (layer max 69.53 %) -> preserved for honesty
IMPERV_THR: float = 20.0     # impervious PERCENT strictly below this (low)
MIN_OBS: int = 20            # >= this many finite/good-quality ECOSTRESS LST obs
WATER_CLASS: int = 11        # NLCD "open water" -> excluded ("not water")

# --- non-tree urban reference pixel (step 53) -----------------------------
# "Low canopy fraction" + a BUILT (not water, not bare desert) surface, in a
# block group that also holds >=1 tree-dominated pixel. NLCD developed classes
# are the "built" set; bare-desert classes (barren 31 / shrub 52 / grassland 71)
# are NOT eligible. REF_CANOPY_MAX is the "low canopy" ceiling: set to 20 % to
# mirror IMPERV_THR's "low" cut and to sit well above the 99th percentile of the
# 70 m canopy layer (~12 %), so it admits genuinely low-canopy built pixels
# without being so loose it is meaningless (raising it 20->30 % changes the
# reference count by <0.1 %, so 20 % already captures the built low-canopy set).
BUILT_CLASSES: tuple = (21, 22, 23, 24)   # NLCD developed: open/low/med/high
REF_CANOPY_MAX: float = 20.0              # reference canopy PERCENT strictly below this

# --- tall-building exclusion buffer (step 54) -----------------------------
# Exclude any pixel within BUFFER_M of a "tall"/large building footprint to
# avoid facade-radiated heat. The Microsoft footprints carry GEOMETRY ONLY (no
# height/storeys field), so "tall" is a documented PROXY by footprint AREA:
# Phoenix is overwhelmingly low-rise, and large footprints are the commercial /
# multi-storey stock. TALL_BUILDING_MIN_AREA_M2 = 1000 m2 sits just below the
# 99th percentile of footprint area (~1665 m2) -> ~the largest ~2 % of the
# ~1.47 M footprints (29,861 buildings); buffering ONLY those by 70 m removes
# ~12 % of the grid (buffering all 1.47 M would over-exclude the whole built
# area, which the protocol warns against). It is a parameter so it is part of
# the sensitivity story.
BUFFER_M: float = 70.0                    # exclusion-buffer radius (metres)
TALL_BUILDING_MIN_AREA_M2: float = 1000.0  # footprint-area proxy for "tall/large"


# ===========================================================================
# SECTION 11 - ANOMALIES & DESEASONALIZATION (z-scores)
# ---------------------------------------------------------------------------
# Half-width (in days) of the DAY-OF-YEAR moving window used to build the
# seasonal-normal climatology (protocol step 58): the normal for a calendar day
# D is the mean of all observations within +/- CLIMATOLOGY_WINDOW_DAYS of D
# (same hour-of-day, for the sub-daily VPD/SM fields) across all years in
# CLIMATOLOGY_YEARS, with the observation's own year left out (leave-one-year-out,
# step 60). The window is CLIPPED to the available warm-season data, so the
# earliest/latest overpasses get a one-sided window (documented, expected).
# Always normalising as a function of day-of-year (NOT one whole-season mean) is
# the protocol's explicit pitfall guard.
# ===========================================================================
CLIMATOLOGY_WINDOW_DAYS: int = 15        # +/- days of the day-of-year moving window


# ===========================================================================
# SECTION 12 - COMPOUND STRESS INDEX (CSI) WEIGHTS
# ---------------------------------------------------------------------------
# The BASELINE equal weights for combining the two standardized stress
# components into the Compound Stress Index (protocol step 64):
#   CSI = WEIGHT_DEMAND * demand_stress + WEIGHT_SUPPLY * supply_stress
# where demand_stress = max(vpd_z, 0) (the positive part of the VPD z-score,
# step 62) and supply_stress = max(-ndmi_z, 0) (the positive part of the NEGATED
# water-supply z-score, step 63) -- BOTH z-scores from Section 11, never raw
# values (the protocol's common pitfall: raw NDMI is on a different scale and
# would dominate the equal-weight sum). The weights are NAMED CONSTANTS so the
# step-66 sensitivity tests (unequal weights, copula-derived weights) are just a
# change of numbers here; only the equal-weight baseline is run now.
# ===========================================================================
WEIGHT_DEMAND: float = 0.5   # baseline weight on the demand (VPD z+) stress
WEIGHT_SUPPLY: float = 0.5   # baseline weight on the supply (-NDMI z)+ stress


# ===========================================================================
# SECTION 16 (REASON #2 FIX) - PIXEL-LEVEL PAIRING DESIGN OPERATING POINTS
# ---------------------------------------------------------------------------
# A SEPARATE, ADDED config block for the pixel-level local-pairing + clustering-
# aware threshold analysis (src/section16_*.py). These are NEW constants -- they
# are NEVER substituted for the Section 10 BG-pipeline constants above. The BG
# pipeline keeps using CANOPY_THR = 40 / MIN_OBS = 20 / CANOPY_THR_PREREGISTERED
# = 70 UNTOUCHED; master_table.parquet (BG-level, 264 rows) is NOT regenerated.
#
# WHY a relaxed pixel-design operating point (Section 15 lever assessment):
#  * Section 14 found NO ROBUST THRESHOLD at the BG level (9 paired BGs, ONE
#    holding 87.7% of tree px, median n_good_obs = 2). The binding limitation is
#    the THIN, SPATIALLY-CLUSTERED paired sample, not the CSI signal.
#  * The pixel design dissolves the BG-aggregation step by differencing each
#    tree pixel against its LOCAL reference pixels (within R metres) at the SAME
#    overpass, then re-aggregating to spatial CLUSTERS for honest inference.
#  * Relaxing canopy 40 -> 30 is the binding gain (paired BG 9 -> 17, tree px
#    195 -> 639, dominant-BG share 87.7% -> 74.6%, queen clusters ~75 -> ~178);
#    relaxing MIN_OBS 20 -> 15 is a near-free reliability relaxation (+137 px,
#    all with obs in [15, 19]). 30 % is the FLOOR (still ~34x the 0.88% Phoenix
#    mean canopy -> "tree-dominated" stays defensible); never go below it.
#  * ALL OTHER Section 10 gates are UNCHANGED: NDVI > 0.5, impervious < 20 %,
#    not-water (NLCD 11), the reference rule, and the tall-building buffer.
# ===========================================================================
CANOPY_THR_PIXEL: float = 30.0   # pixel-design operating canopy PERCENT floor (NOT
                                 # the BG pipeline's CANOPY_THR=40; never go below 30)
MIN_OBS_PIXEL: int = 15          # pixel-design min finite ECOSTRESS LST obs (the elbow;
                                 # NOT the BG pipeline's MIN_OBS=20)
R_PAIR_M: float = 350.0          # PRIMARY local-pairing radius (Euclidean, 70 m grid =
                                 # 5 cells); references within R of a tree px are its
                                 # local controls (same micro-climate context)
R_PAIR_SWEEP_M: tuple = (210.0, 350.0, 500.0)   # radius sensitivity sweep (3 / 5 / ~7 cells)
CONNECTIVITY: str = "queen"      # PRIMARY tree-cluster adjacency (8-connectivity); 'rook'
                                 # (4-connectivity) reported as a sensitivity
N_BOOT_PIXEL: int = 2000         # CLUSTER-resampling spatial block bootstrap resamples
GRID_TILE_M: float = 2000.0      # de-concentration ROBUSTNESS sensitivity tile size (splits
                                 # the dominant BG into ~8 tiles); NOT the primary unit


# --------------------------------------------------------------------------- #
# Credential references (read from the standard locations each library uses).
# These are pointers only - populate them yourself via the normal login flow.
# --------------------------------------------------------------------------- #
# NASA Earthdata (earthaccess): ~/.netrc entry for urs.earthdata.nasa.gov,
#   or EARTHDATA_USERNAME / EARTHDATA_PASSWORD environment variables.
EARTHDATA_NETRC = Path(os.environ.get("NETRC", Path.home() / ".netrc"))

# Google Earth Engine: credentials cached by `earthengine authenticate`
#   (~/.config/earthengine/credentials) plus a cloud project id. Set the
#   project via EARTHENGINE_PROJECT (or GOOGLE_CLOUD_PROJECT).
EARTHENGINE_CREDENTIALS = Path.home() / ".config" / "earthengine" / "credentials"
EARTHENGINE_PROJECT = os.environ.get("EARTHENGINE_PROJECT") or os.environ.get(
    "GOOGLE_CLOUD_PROJECT"
)

# Copernicus Climate Data Store (cdsapi): ~/.cdsapirc, or CDSAPI_URL / CDSAPI_KEY.
CDSAPIRC = Path(os.environ.get("CDSAPI_RC", Path.home() / ".cdsapirc"))

# US Census Bureau API: a key from CENSUS_API_KEY (the API also serves limited
#   volumes without a key, but a key is recommended).
CENSUS_API_KEY = os.environ.get("CENSUS_API_KEY")
CENSUS_API_BASE = "https://api.census.gov/data"


if __name__ == "__main__":
    ensure_dirs()
    print(f"BASE_DIR        = {BASE_DIR}")
    print(f"DATA_DIR        = {DATA_DIR}")
    print(f"MANIFEST_CSV    = {MANIFEST_CSV}")
    print(f"REFERENCE_GRID  = {REFERENCE_GRID_TIF}")
    print(f"CRS             = {CRS}")
    print(f"CELL_SIZE_M     = {CELL_SIZE_M}")
    print(f"GRID_SHAPE      = {GRID_SHAPE} (rows, cols)")
    print(f"GRID_ORIGIN_XY  = {GRID_ORIGIN_XY}")
    print(f"GRID_BOUNDS     = {GRID_BOUNDS} (left, bottom, right, top)")
    print("--- Section 10 thresholds (others pre-registered; canopy at the operating point) ---")
    print(f"NDVI_THR={NDVI_THR}  CANOPY_THR={CANOPY_THR} (operating; "
          f"pre-registered {CANOPY_THR_PREREGISTERED})  IMPERV_THR={IMPERV_THR}  "
          f"MIN_OBS={MIN_OBS}")
    print(f"REF_CANOPY_MAX={REF_CANOPY_MAX}  BUILT_CLASSES={BUILT_CLASSES}  "
          f"WATER_CLASS={WATER_CLASS}")
    print(f"BUFFER_M={BUFFER_M}  TALL_BUILDING_MIN_AREA_M2={TALL_BUILDING_MIN_AREA_M2}")
    print("--- Section 11 anomalies ---")
    print(f"CLIMATOLOGY_WINDOW_DAYS={CLIMATOLOGY_WINDOW_DAYS} (+/- days, day-of-year window)")
    print("--- Section 12 compound stress index (baseline equal weights) ---")
    print(f"WEIGHT_DEMAND={WEIGHT_DEMAND}  WEIGHT_SUPPLY={WEIGHT_SUPPLY}")
    print(f"EARTHENGINE_PROJECT = {EARTHENGINE_PROJECT or '(unset)'}")
