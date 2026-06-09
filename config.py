"""Central configuration for the Canopy protocol.

Defines canonical project paths and the locations/environment variables that
the external services read their credentials from. NO SECRETS ARE STORED HERE
— this module only references the standard credential files / env vars that
each library already expects. See src/check_auth.py for the auth smoke test.
"""

from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Project paths
# --------------------------------------------------------------------------- #
# Resolve relative to this file so paths work regardless of the current dir.
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


# --------------------------------------------------------------------------- #
# Credential references (read from the standard locations each library uses).
# These are pointers only — populate them yourself via the normal login flow.
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
    print(f"EARTHENGINE_PROJECT = {EARTHENGINE_PROJECT or '(unset)'}")
