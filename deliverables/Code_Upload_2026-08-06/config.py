"""Central configuration for the Canopy protocol — paths, frozen geometry, thresholds.

Defines project paths, the FIXED Section-1 analysis geometry, the time windows, and
the named thresholds for Sections 10-12. Section-1 geometry is written as LITERALS,
never recomputed at runtime, so every run is byte-for-byte identical. No secrets are
stored here — only pointers to the standard credential files each library reads.

See build_reference_grid.py (grid derivation), check_auth.py (auth smoke test) and
docs/DESIGN_DECISIONS.md for the rationale behind the constants below.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Project paths (absolute, derived from this file's directory = repo root) ---
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

# Local runtime directories (contents git-ignored).
_RUNTIME_DIRS = (RAW_DIR, INTERIM_DIR, PROCESSED_DIR, FIGURES_DIR)


def ensure_dirs() -> None:
    """Create the local runtime directories if they do not already exist."""
    for d in _RUNTIME_DIRS:
        d.mkdir(parents=True, exist_ok=True)


# The geometric anchor every later layer is matched to.
REFERENCE_GRID_TIF: Path = PROCESSED_DIR / "reference_grid.tif"


# === SECTION 1 — FIXED DOMAIN, PROJECTION, GRID, TIME WINDOWS ===
# Frozen literals, derived once by build_reference_grid.py (reproject BBOX_LONLAT to
# EPSG:32612 and snap the origin to the 70 m pixel). Do not edit by hand.
# Rationale: docs/DESIGN_DECISIONS.md (Section 1).

# domain (study area): (min_lon, max_lon, min_lat, max_lat) in WGS84 degrees.
BBOX_LONLAT: tuple = (-112.55, -111.55, 33.20, 33.92)

# projection / resolution
CRS: str = "EPSG:32612"          # UTM zone 12N, WGS84 - the project CRS
CELL_SIZE_M: int = 70            # ECOSTRESS native pixel size (metres)

# time windows
PILOT_WINDOW: tuple = ("2023-06-01", "2023-09-30")
CLIMATOLOGY_YEARS: tuple = (2018, 2024)   # inclusive (start, end)
SEASON: tuple = ("06-01", "09-30")        # MM-DD start/end of the season

# fixed analysis grid (EPSG:32612). ORIGIN is the TOP-LEFT corner (x_min, y_max);
# north-up, rows increasing southward.
GRID_ORIGIN_XY: tuple = (355460.0, 3754380.0)   # (x_min, y_max)
GRID_NROWS: int = 1155
GRID_NCOLS: int = 1339
GRID_SHAPE: tuple = (GRID_NROWS, GRID_NCOLS)     # (rows, cols)

# Bounds as (left, bottom, right, top) = (x_min, y_min, x_max, y_max), metres.
GRID_BOUNDS: tuple = (355460.0, 3673530.0, 449190.0, 3754380.0)

# Affine geotransform in rasterio/Affine order (a, b, c, d, e, f):
#   x = a*col + b*row + c ;  y = d*col + e*row + f  (a=+cell, e=-cell, (c,f)=top-left).
GRID_TRANSFORM: tuple = (70.0, 0.0, 355460.0, 0.0, -70.0, 3754380.0)

# Same transform in GDAL geotransform order (c, a, b, f, d, e).
GRID_GDAL_GEOTRANSFORM: tuple = (355460.0, 70.0, 0.0, 3754380.0, 0.0, -70.0)


# === SECTION 10 — PAIRED-DESIGN PIXEL CLASSIFICATION THRESHOLDS ===
# Named constants so the sensitivity sweep is just a change of numbers here. Canopy and
# impervious are stored as PERCENT (0-100). Rationale: docs/DESIGN_DECISIONS.md (Section 10).

# tree-dominated pixel = ALL of these (step 52)
NDVI_THR: float = 0.5        # warm-season median NDVI strictly above this
# CANOPY_THR is the OPERATING point, NOT the pre-registered 70% (which is unachievable
# at 70 m: the area-weighted canopy layer maxes at 69.53%). Its pre-outcome rule is
# max(CANOPY_PCTL of finite, building-excluded NDVI-qualifying pixels,
# CANOPY_THR_FLOOR). Phoenix's raw P90 is 8.143%, so the 40% physical-signal floor binds.
CANOPY_PCTL: float = 90.0
CANOPY_THR_FLOOR: float = 40.0
CANOPY_THR: float = 40.0     # derived OPERATING tree-canopy PERCENT; independent of BG yield
CANOPY_THR_PREREGISTERED: float = 70.0   # pre-registered bar; unachievable at 70 m (kept for honesty)
IMPERV_THR: float = 20.0     # impervious PERCENT strictly below this (low)
MIN_OBS: int = 20            # >= this many finite/good-quality ECOSTRESS LST obs
WATER_CLASS: int = 11        # NLCD "open water" -> excluded ("not water")

# non-tree urban reference pixel (step 53): low canopy on a materially impervious
# developed surface, in a block group that also holds a tree-dominated pixel. NLCD 21
# (developed open space) is deliberately excluded to avoid irrigated/vegetated references.
REF_BUILT_CLASSES: tuple = (22, 23, 24)   # NLCD developed: low/medium/high intensity
REF_CANOPY_MAX: float = 20.0              # reference canopy PERCENT strictly below this
REF_IMPERV_MIN: float = 20.0              # reference impervious PERCENT strictly above this

# tall-building exclusion buffer (step 54). Footprints carry GEOMETRY ONLY (no height),
# so "tall" is a documented footprint-AREA proxy. See docs/DESIGN_DECISIONS.md (Section 10).
BUFFER_M: float = 70.0                    # exclusion-buffer radius (metres)
TALL_BUILDING_MIN_AREA_M2: float = 1000.0  # footprint-area proxy for "tall/large"


# === SECTION 11 — ANOMALIES & DESEASONALIZATION (z-scores) ===
# Half-width (days) of the day-of-year moving window for the leave-one-year-out
# seasonal-normal climatology (built at the overpass hour). Clipped to the warm season,
# so the earliest/latest overpasses get a one-sided window. See docs (Section 11).
CLIMATOLOGY_WINDOW_DAYS: int = 15        # +/- days of the day-of-year moving window

# Per-variable climatological-std FLOORS for zscore() (BLOCKER B2). A per-pixel
# clim std at or below its floor is treated as degenerate (near-constant climatology)
# and the z-score is rejected to NaN rather than dividing by a tiny std (which yields
# |z| in the tens-to-hundreds that then inflate supply_stress -> CSI). Floors are in
# each variable's NATIVE, pre-regrid units and are applied at the native std, the only
# correct place (no re-standardization happens post-regrid). The NDMI value was calibrated
# against the Phoenix stored ``ndmi_clim_std`` distribution: 0.012 rejects ~0.7% of finite
# cells, while 0.020 rejected ~23.5% and was too aggressive for a degeneracy guard.
MIN_STD_NDMI: float = 0.012  # dimensionless NDMI (within the review's suggested 0.01-0.02 range)
MIN_STD_VPD: float = 0.05    # kPa, native ERA5 VPD std
MIN_STD_SM: float = 0.005    # m3 m-3, native root-zone soil-moisture std


# === SECTION 12 — COMPOUND STRESS INDEX (CSI) WEIGHTS ===
# Baseline EQUAL weights: CSI = WEIGHT_DEMAND*max(vpd_z,0) + WEIGHT_SUPPLY*max(supply_z,0).
# Named constants so the step-66 unequal/copula sensitivity tests are a change of numbers
# here. See docs/DESIGN_DECISIONS.md (Section 12).
WEIGHT_DEMAND: float = 0.5   # baseline weight on the demand (VPD z+) stress
WEIGHT_SUPPLY: float = 0.5   # baseline weight on the supply-deficit stress

# Water-supply axis (BLOCKER B1a). The CSI supply term is root-zone SOIL MOISTURE
# (sm_z), NOT ndmi_z: NDMI is vegetation greenness/moisture (a mediator/canopy-condition
# check), not a water-supply forcing. Section 12 supply = sm_z; Section 13 persists
# ndmi_z/mean_ndmi_z_tree as the VEGETATION CHECK only.
# SUPPLY_ROBUST_RESCALE divides sm_z by IQR/1.349 before supply_stress so its real
# single-year compressed variance (std ~0.45) does not silently de-weight the supply
# axis against the ~unit-std demand term. The compressed variance is a real property of
# a single pilot year; it is handled here by rescale, NOT "fixed" upstream.
SUPPLY_VAR: str = "sm_z"
SUPPLY_ROBUST_RESCALE: bool = True


# === SECTIONS 13-15 — PRIMARY ANALYSIS SAMPLE ===
# Rows based on fewer than three finite tree pixels are retained for transparent
# sensitivity analyses, but they are not allowed into the primary result. This directly
# addresses the Phoenix one-pixel extremes while preserving the full pilot data.
PRIMARY_MIN_TREE_PIXELS: int = 3


# --- Credential references (pointers only; populate via the normal login flow) ---
# NASA Earthdata (earthaccess): ~/.netrc for urs.earthdata.nasa.gov, or
#   EARTHDATA_USERNAME / EARTHDATA_PASSWORD.
EARTHDATA_NETRC = Path(os.environ.get("NETRC", Path.home() / ".netrc"))

# Google Earth Engine: `earthengine authenticate` cache + a cloud project id
#   (set via EARTHENGINE_PROJECT or GOOGLE_CLOUD_PROJECT).
EARTHENGINE_CREDENTIALS = Path.home() / ".config" / "earthengine" / "credentials"
EARTHENGINE_PROJECT = os.environ.get("EARTHENGINE_PROJECT") or os.environ.get(
    "GOOGLE_CLOUD_PROJECT"
)

# Copernicus Climate Data Store (cdsapi): ~/.cdsapirc, or CDSAPI_URL / CDSAPI_KEY.
CDSAPIRC = Path(os.environ.get("CDSAPI_RC", Path.home() / ".cdsapirc"))

# US Census Bureau API: CENSUS_API_KEY (recommended; limited volumes work without a key).
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
    print(f"NDVI_THR={NDVI_THR}  CANOPY_THR={CANOPY_THR} (max(P{CANOPY_PCTL:g}, "
          f"floor={CANOPY_THR_FLOOR}); pre-registered {CANOPY_THR_PREREGISTERED})  "
          f"IMPERV_THR={IMPERV_THR}  MIN_OBS={MIN_OBS}")
    print(f"REF_CANOPY_MAX={REF_CANOPY_MAX}  REF_IMPERV_MIN={REF_IMPERV_MIN}  "
          f"REF_BUILT_CLASSES={REF_BUILT_CLASSES}  WATER_CLASS={WATER_CLASS}")
    print(f"BUFFER_M={BUFFER_M}  TALL_BUILDING_MIN_AREA_M2={TALL_BUILDING_MIN_AREA_M2}")
    print("--- Section 11 anomalies ---")
    print(f"CLIMATOLOGY_WINDOW_DAYS={CLIMATOLOGY_WINDOW_DAYS} (+/- days, day-of-year window)")
    print("--- Section 12 compound stress index (baseline equal weights) ---")
    print(f"WEIGHT_DEMAND={WEIGHT_DEMAND}  WEIGHT_SUPPLY={WEIGHT_SUPPLY}")
    print(f"EARTHENGINE_PROJECT = {EARTHENGINE_PROJECT or '(unset)'}")
