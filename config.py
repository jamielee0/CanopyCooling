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
    print(f"EARTHENGINE_PROJECT = {EARTHENGINE_PROJECT or '(unset)'}")
