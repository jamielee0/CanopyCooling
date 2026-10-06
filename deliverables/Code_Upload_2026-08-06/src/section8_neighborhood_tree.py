#!/usr/bin/env python3
"""Section 8 / neighborhood + tree attributes (protocol steps 42-46).

Inputs : Census ACS5 / TIGER (api.census.gov, www2.census.gov), CDC SVI CSV in
         data/raw/svi/, ASU GAO tree FeatureServer, MS building footprints (PC STAC).
Outputs: data/interim/ -- block-group frame, tree inventory + footprints parquets,
         and income/%POC/SVI rasters on the 70 m grid; raw files in data/raw/ +
         data/manifest.csv (SHA-256); QA figure in figures/.
Key decisions (full rationale in docs/DESIGN_DECISIONS.md, Section 8):
  - ACS5 2024, Maricopa BG; %POC = 100*(total - non-Hispanic White)/total; jam values -> null.
  - SVI is TRACT level, inherited DOWN to block groups (first 11 GEOID digits = tract).
  - Tree inventory has no true planting year: planting_year is NULL; functional type is primary.
  - Footprints: PC STAC ms-buildings primary, USBuildingFootprints AZ download as fallback.
  - Neighborhood attributes rasterized NEAREST / value-per-cell (already-aggregated).
Run: python src/section8_neighborhood_tree.py [--parts ...] [--footprints-source auto|stac|fallback] [--skip-download] [--acs-year N] [--tiger-year N] [-v]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import math
import sys
import time
import zipfile
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlencode

import numpy as np
import pandas as pd

# Heavy geospatial libs; the pure logic below stays importable without them.
import geopandas as gpd  # noqa: E402
import requests  # noqa: E402
from rasterio import features as rfeatures  # noqa: E402
from rasterio.transform import Affine  # noqa: E402
from shapely.geometry import box  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
import config  # noqa: E402
import section2_ecostress_lst as sec2  # noqa: E402  (manifest/checksum/.env helpers)
import plot_style as ps  # noqa: E402  (shared figure color convention)

log = logging.getLogger("section8")

# --- Constants ------------------------------------------------------------- #
# ACS / Census (step 42)
CENSUS_BASE = config.CENSUS_API_BASE                    # https://api.census.gov/data
ACS_DATASET = "acs/acs5"                                # 5-year estimates
ACS5_VINTAGE = 2024                                     # Phoenix pilot analysis vintage
ACS5_PERIOD = "2020-2024"                               # five survey years represented
ACS5_RELEASE_DATE = "2026-01-29"                        # ACS API/detailed-table release
ACS5_RELEASE_SOURCE = ("https://www.census.gov/programs-surveys/acs/news/"
                       "data-releases/2024/release.html")
ACS5_RELEASE_SCHEDULE_SOURCE = ("https://www.census.gov/programs-surveys/acs/news/"
                                "data-releases/2024/release-schedule.html")
ACS_YEAR = ACS5_VINTAGE                                 # backward-compatible alias
STATE_FIPS = "04"                                       # Arizona
COUNTY_FIPS = "013"                                     # Maricopa County
INCOME_VAR = "B19013_001E"                              # median household income (USD)
# %POC from table B03002: total = B03002_001E; non-Hispanic White alone = B03002_003E.
POC_TOTAL_VAR = "B03002_001E"
POC_NHWHITE_VAR = "B03002_003E"
CENSUS_JAM_THRESHOLD = -666666600                       # anything <= this is a jam value -> null

# TIGER/Line block-group geometry (step 42)
TIGER_VINTAGE = 2024                                    # must match ACS5_VINTAGE
TIGER_RELEASE_DATE = "2024-09-25"
TIGER_BOUNDARIES_AS_OF = "2024-01-01"
TIGER_RELEASE_SOURCE = ("https://www.census.gov/geographies/mapping-files/2024/"
                        "geo/tiger-line-file.html")

# CDC/ATSDR SVI (step 43)
SVI_DIR = config.RAW_DIR / "svi"
SVI_FIPS_COL = "FIPS"                                   # 11-digit TRACT GEOID
SVI_COUNTY_PREFIX = STATE_FIPS + COUNTY_FIPS            # "04013"
SVI_VALUE_COL = "RPL_THEMES"                            # overall SVI percentile ranking (0-1)
SVI_THEME_COLS = ["RPL_THEME1", "RPL_THEME2", "RPL_THEME3", "RPL_THEME4"]
SVI_MISSING = -999.0                                    # CDC SVI missing sentinel -> null

# Phoenix tree inventory (step 44)
TREE_SERVICE = ("https://services3.arcgis.com/0OPQIK59PJJqLK0A/arcgis/rest/services/"
                "street_trees_gao_map_by_species__WFL1/FeatureServer")
TREE_LAYER_ID = 1                                       # 'top20_trees_gao_' master point layer
TREE_OUT_FIELDS = ["SPP_BOT", "SPP_COM", "INV_DATE", "DBH1", "DBH2", "DBH3",
                   "HEIGHT", "COND", "LANDUSE"]
TREE_PAGE = 2000                                        # = layer maxRecordCount
TREE_RAW_NAME = "phoenix_street_trees_gao.geojson"

# Building footprints (step 45)
PC_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_COLLECTION = "ms-buildings"
# ms-buildings US items are region partitions split into quadkey=<tile>/ hive subdirs
# at Bing tile level 9; read only the few quadkeys covering the bbox (no bbox= read).
BUILDINGS_QUADKEY_LEVEL = 9
FOOTPRINTS_RAW_STAC_NAME = "ms_buildings_phoenix_bbox_4326.parquet"
FOOTPRINTS_FALLBACK_URL = ("https://minedbuildings.z5.web.core.windows.net/"
                           "legacy/usbuildings-v2/Arizona.geojson.zip")
FOOTPRINTS_FALLBACK_ZIP = "USBuildingFootprints_Arizona.geojson.zip"

# Output filenames (data/interim)
ACS_RAW_SUBDIR = "acs"
FOOTPRINTS_RAW_SUBDIR = "footprints"
TREE_RAW_SUBDIR = "trees"
BG_INTERIM_PARQUET = "neighborhood_blockgroups_32612.parquet"
TREE_INTERIM_PARQUET = "phoenix_tree_inventory.parquet"
FOOTPRINTS_INTERIM_PARQUET = "building_footprints_32612.parquet"
GRID_INCOME_TIF = "acs_median_income_70m.tif"
GRID_POC_TIF = "acs_pct_people_of_colour_70m.tif"
GRID_SVI_TIF = "cdc_svi_rpl_themes_70m.tif"
VINTAGE_PROVENANCE_JSON = "section8_vintage_provenance.json"

# HTTP retry policy (sync requests; the async/aiohttp path is unreliable here).
HTTP_RETRIES = 5
HTTP_BACKOFF_S = 1.5
HTTP_TIMEOUT_S = 90
USER_AGENT = "canopy-protocol-section8/1.0"


# --- Pure logic (numpy/pandas/str only; unit-tested without geo/network) ---- #
def tiger_bg_filename(year: int, state_fips: str = STATE_FIPS) -> str:
    """Return the TIGER/Line block-group ZIP filename for a vintage and state."""
    return f"tl_{int(year)}_{str(state_fips).zfill(2)}_bg.zip"


def tiger_bg_url(year: int, state_fips: str = STATE_FIPS) -> str:
    """Return the exact Census TIGER/Line block-group download URL."""
    filename = tiger_bg_filename(year, state_fips)
    return f"https://www2.census.gov/geo/tiger/TIGER{int(year)}/BG/{filename}"


def acs_request_url(year: int, get_expression: str) -> str:
    """Return the credential-free ACS5 request URL used for Maricopa block groups."""
    query = urlencode([
        ("get", get_expression),
        ("for", "block group:*"),
        ("in", f"state:{STATE_FIPS} county:{COUNTY_FIPS}"),
    ])
    return f"{CENSUS_BASE}/{int(year)}/{ACS_DATASET}?{query}"


def validate_vintage_pair(acs_year: int, tiger_year: int, *,
                          require_pinned: bool = False) -> None:
    """Reject ACS/TIGER mismatches and, for production, non-pilot vintages."""
    acs_year = int(acs_year)
    tiger_year = int(tiger_year)
    if acs_year != tiger_year:
        raise ValueError(
            f"ACS5 vintage {acs_year} cannot be joined to TIGER/Line vintage "
            f"{tiger_year}; use the same year for both sources.")
    if require_pinned and (acs_year != ACS5_VINTAGE or tiger_year != TIGER_VINTAGE):
        raise ValueError(
            f"The Phoenix pilot is pinned to ACS5 {ACS5_VINTAGE} and TIGER/Line "
            f"{TIGER_VINTAGE}; received {acs_year}/{tiger_year}.")


def clean_census_value(raw) -> float | None:
    """Parse a Census API string to float; jam values / blanks -> None (never averaged)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "" or s.lower() in ("none", "null", "nan"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if v <= CENSUS_JAM_THRESHOLD:
        return None
    return v


def pct_people_of_colour(total, non_hisp_white) -> float | None:
    """%POC = 100*(total - non-Hispanic White)/total, clipped to [0,100]; None if total missing/0."""
    t = clean_census_value(total)
    w = clean_census_value(non_hisp_white)
    if t is None or t <= 0 or w is None:
        return None
    pct = 100.0 * (t - w) / t
    return float(min(100.0, max(0.0, pct)))


def block_group_geoid(state: str, county: str, tract: str, block_group: str) -> str:
    """Compose the 12-digit block-group GEOID = state(2)+county(3)+tract(6)+bg(1)."""
    return f"{state:0>2}{county:0>3}{tract:0>6}{block_group:0>1}"


def tract_geoid_of(bg_geoid: str) -> str:
    """Parent TRACT GEOID = first 11 digits of a 12-digit block-group GEOID (SVI join key)."""
    return str(bg_geoid)[:11]


def inventory_year_from_epoch_ms(ms) -> int | None:
    """ArcGIS dates are epoch milliseconds; return the calendar year (UTC) or None."""
    if ms is None or (isinstance(ms, float) and np.isnan(ms)):
        return None
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return None
    return _dt.datetime.fromtimestamp(ms / 1000.0, tz=_dt.timezone.utc).year


# Bing Maps tile system / quadkeys (pure; ms-buildings is quadkey-partitioned).
def latlon_to_tile_xy(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Bing Maps tile (x, y) containing a lat/lon at a zoom level (Web-Mercator)."""
    sin = math.sin(math.radians(lat))
    x = (lon + 180.0) / 360.0
    y = 0.5 - math.log((1 + sin) / (1 - sin)) / (4 * math.pi)
    n = 2 ** zoom
    return (min(n - 1, max(0, int(x * n))), min(n - 1, max(0, int(y * n))))


def tile_xy_to_quadkey(tx: int, ty: int, zoom: int) -> str:
    """Bing Maps quadkey string for a tile (x, y) at a zoom level."""
    out = []
    for i in range(zoom, 0, -1):
        digit = 0
        mask = 1 << (i - 1)
        if tx & mask:
            digit += 1
        if ty & mask:
            digit += 2
        out.append(str(digit))
    return "".join(out)


def bbox_quadkeys(bbox: tuple[float, float, float, float],
                  zoom: int = BUILDINGS_QUADKEY_LEVEL) -> list[str]:
    """Sorted Bing quadkeys at `zoom` whose tiles cover bbox=(minx,miny,maxx,maxy)."""
    minx, miny, maxx, maxy = bbox
    tx0, ty0 = latlon_to_tile_xy(maxy, minx, zoom)        # top-left
    tx1, ty1 = latlon_to_tile_xy(miny, maxx, zoom)        # bottom-right
    out = set()
    for tx in range(min(tx0, tx1), max(tx0, tx1) + 1):
        for ty in range(min(ty0, ty1), max(ty0, ty1) + 1):
            out.add(tile_xy_to_quadkey(tx, ty, zoom))
    return sorted(out)


# Functional-type lookup (step 44): the PRIMARY descriptor. GENUS-level (robust to
# species outside the inventoried top ~20) with a few SPECIES overrides below.
#   value: (water_use in {drought_tolerant, mesic}, leaf_habit in {deciduous, evergreen})
_GENUS_FUNCTYPE = {
    # xeric / desert-adapted
    "parkinsonia": ("drought_tolerant", "deciduous"),   # palo verde (drought-deciduous)
    "cercidium": ("drought_tolerant", "deciduous"),     # old palo verde genus
    "prosopis": ("drought_tolerant", "deciduous"),      # mesquite
    "acacia": ("drought_tolerant", "evergreen"),        # most landscape acacias
    "vachellia": ("drought_tolerant", "evergreen"),
    "senegalia": ("drought_tolerant", "evergreen"),
    "olneya": ("drought_tolerant", "evergreen"),        # ironwood
    "chilopsis": ("drought_tolerant", "deciduous"),     # desert willow
    "chitalpa": ("drought_tolerant", "deciduous"),
    "olea": ("drought_tolerant", "evergreen"),          # olive
    "eucalyptus": ("drought_tolerant", "evergreen"),
    "washingtonia": ("drought_tolerant", "evergreen"),  # fan palm (monocot)
    "phoenix": ("drought_tolerant", "evergreen"),       # date palm (monocot)
    "rhus": ("drought_tolerant", "evergreen"),
    "ebenopsis": ("drought_tolerant", "evergreen"),     # Texas ebony
    "caesalpinia": ("drought_tolerant", "evergreen"),
    "tipuana": ("drought_tolerant", "deciduous"),
    # mesic / higher-water amenity trees
    "fraxinus": ("mesic", "deciduous"),                 # ash
    "ulmus": ("mesic", "deciduous"),                    # elm
    "quercus": ("mesic", "evergreen"),                  # oak (live oak common here)
    "pinus": ("mesic", "evergreen"),                    # pine
    "brachychiton": ("mesic", "evergreen"),             # bottle tree
    "dalbergia": ("mesic", "deciduous"),                # Indian rosewood
    "morus": ("mesic", "deciduous"),                    # mulberry
    "pistacia": ("mesic", "deciduous"),
    "platanus": ("mesic", "deciduous"),                 # sycamore
    "populus": ("mesic", "deciduous"),                  # cottonwood
    "salix": ("mesic", "deciduous"),                    # willow
    "ficus": ("mesic", "evergreen"),
    "jacaranda": ("mesic", "deciduous"),
    "schinus": ("mesic", "evergreen"),                  # pepper tree
    "celtis": ("mesic", "deciduous"),                   # hackberry
}
# Species-level overrides where the species departs from its genus default.
_SPECIES_FUNCTYPE = {
    "acacia farnesiana": ("drought_tolerant", "deciduous"),   # sweet acacia (winter-deciduous)
    "acacia aneura": ("drought_tolerant", "evergreen"),       # mulga
    "acacia stenophylla": ("drought_tolerant", "evergreen"),  # shoestring acacia
    "quercus virginiana": ("mesic", "evergreen"),             # southern live oak
}


def _normalize_species(spp_bot) -> str:
    """Lowercase, collapse whitespace; return '' for blanks/NA."""
    if spp_bot is None:
        return ""
    s = str(spp_bot).strip().lower()
    if s in ("", "na", "n/a", "none", "unknown", "vacant", "stump"):
        return ""
    return " ".join(s.split())


def functional_type(spp_bot) -> tuple[str, str]:
    """Map a botanical species to (water_use, leaf_habit): species override, then genus, else unknown."""
    s = _normalize_species(spp_bot)
    if not s:
        return ("unknown", "unknown")
    if s in _SPECIES_FUNCTYPE:
        return _SPECIES_FUNCTYPE[s]
    genus = s.split()[0]
    if genus in _GENUS_FUNCTYPE:
        return _GENUS_FUNCTYPE[genus]
    return ("unknown", "unknown")


def acs_table_to_records(header: Sequence[str], rows: Iterable[Sequence]) -> list[dict]:
    """Turn a Census API [header, *rows] response into a list of dicts keyed by header."""
    h = list(header)
    return [dict(zip(h, r)) for r in rows]


# --- HTTP helpers (sync requests + retries; aiohttp is flaky here) ---------- #
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def http_get(url: str, *, params: dict | None = None, sess: requests.Session | None = None,
             stream: bool = False, headers: dict | None = None,
             retries: int = HTTP_RETRIES) -> requests.Response:
    """GET with exponential backoff. Raises RuntimeError after the final failure."""
    sess = sess or _session()
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = sess.get(url, params=params, timeout=HTTP_TIMEOUT_S, stream=stream,
                         headers=headers)
            r.raise_for_status()
            return r
        except Exception as exc:  # noqa: BLE001 - retry network/HTTP errors
            last = exc
            if attempt < retries - 1:
                time.sleep(HTTP_BACKOFF_S * (2 ** attempt))
    raise RuntimeError(f"GET failed after {retries} tries: {url}: {last}")


# --- Manifest -------------------------------------------------------------- #
def record_in_manifest(path: Path, source: str, dataset: str) -> None:
    """Append a downloaded raw file to data/manifest.csv with a SHA-256 sum."""
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    sec2.append_to_manifest([{
        "source": source,
        "dataset": dataset,
        "filename": path.name,
        "download_date": today,
        "checksum": f"sha256:{sec2.sha256_file(path)}",
    }])


def _manifest_download_record(filename: str,
                              manifest_csv: Path = config.MANIFEST_CSV) -> dict[str, str]:
    """Return the latest manifest record for a raw file; fail if provenance is absent."""
    if not manifest_csv.exists():
        raise RuntimeError(f"Section 8 provenance requires the missing manifest: {manifest_csv}")
    manifest = pd.read_csv(manifest_csv, dtype=str, keep_default_na=False)
    required = {"source", "dataset", "filename", "download_date", "checksum"}
    missing = required.difference(manifest.columns)
    if missing:
        raise RuntimeError(
            f"Section 8 provenance cannot read {manifest_csv}: missing columns {sorted(missing)}")
    matches = manifest.loc[manifest["filename"] == filename]
    if matches.empty:
        raise RuntimeError(
            f"Section 8 raw file {filename!r} has no access record in {manifest_csv}")
    row = matches.iloc[-1]
    return {key: str(row[key]) for key in
            ("source", "dataset", "download_date", "checksum")}


def _verified_manifest_download_record(path: Path,
                                       manifest_csv: Path = config.MANIFEST_CSV) -> dict[str, str]:
    """Return provenance only when the current raw bytes match their manifest hash."""
    record = _manifest_download_record(path.name, manifest_csv)
    actual = f"sha256:{sec2.sha256_file(path)}"
    if record["checksum"] != actual:
        raise RuntimeError(
            f"Section 8 raw input {path} does not match its manifest checksum: "
            f"expected {record['checksum']}, found {actual}")
    return record


def build_vintage_provenance(acs_year: int = ACS5_VINTAGE,
                             tiger_year: int = TIGER_VINTAGE,
                             raw_dir: Path | None = None,
                             manifest_csv: Path = config.MANIFEST_CSV) -> dict:
    """Build machine-readable provenance for the exact ACS5/TIGER inputs."""
    validate_vintage_pair(acs_year, tiger_year, require_pinned=True)
    raw_dir = raw_dir or (config.RAW_DIR / ACS_RAW_SUBDIR)
    income_name = f"acs5_{acs_year}_{INCOME_VAR}_maricopa_bg.json"
    poc_name = f"acs5_{acs_year}_B03002_maricopa_bg.json"
    tiger_name = tiger_bg_filename(tiger_year)
    for filename in (income_name, poc_name, tiger_name):
        if not (raw_dir / filename).exists():
            raise RuntimeError(
                f"Section 8 provenance cannot identify an absent raw input: {raw_dir / filename}")

    income_record = _verified_manifest_download_record(raw_dir / income_name, manifest_csv)
    poc_record = _verified_manifest_download_record(raw_dir / poc_name, manifest_csv)
    tiger_record = _verified_manifest_download_record(raw_dir / tiger_name, manifest_csv)
    return {
        "schema_version": 1,
        "analysis": "Phoenix urban-heat and canopy pilot, Section 8 neighborhood layers",
        "vintage_join_guard": {
            "acs5_vintage": int(acs_year),
            "tiger_line_vintage": int(tiger_year),
            "status": "matched",
            "production_contract": (
                "The pipeline raises before processing if ACS5 and TIGER/Line vintages differ."
            ),
        },
        "acs5": {
            "vintage": int(acs_year),
            "period": ACS5_PERIOD,
            "dataset": ACS_DATASET,
            "release_date": ACS5_RELEASE_DATE,
            "official_release_page": ACS5_RELEASE_SOURCE,
            "official_release_schedule": ACS5_RELEASE_SCHEDULE_SOURCE,
            "credential_note": (
                "CENSUS_API_KEY is intentionally omitted; each exact_request_url is the "
                "equivalent public request used to identify the extracted data."
            ),
            "resources": [
                {
                    "purpose": "median household income",
                    "raw_file": income_name,
                    "exact_request_url": acs_request_url(
                        acs_year, f"NAME,{INCOME_VAR}"),
                    "access_date": income_record["download_date"],
                    "sha256": income_record["checksum"],
                    "manifest_dataset": income_record["dataset"],
                    "manifest_source": income_record["source"],
                },
                {
                    "purpose": "B03002 race and Hispanic-origin table for percent POC",
                    "raw_file": poc_name,
                    "exact_request_url": acs_request_url(acs_year, "group(B03002)"),
                    "access_date": poc_record["download_date"],
                    "sha256": poc_record["checksum"],
                    "manifest_dataset": poc_record["dataset"],
                    "manifest_source": poc_record["source"],
                },
            ],
        },
        "tiger_line": {
            "vintage": int(tiger_year),
            "product": "TIGER/Line block-group shapefile",
            "release_date": TIGER_RELEASE_DATE,
            "boundaries_as_of": TIGER_BOUNDARIES_AS_OF,
            "official_release_page": TIGER_RELEASE_SOURCE,
            "raw_file": tiger_name,
            "exact_download_url": tiger_bg_url(tiger_year),
            "access_date": tiger_record["download_date"],
            "sha256": tiger_record["checksum"],
            "manifest_dataset": tiger_record["dataset"],
            "manifest_source": tiger_record["source"],
        },
    }


def write_vintage_provenance(acs_year: int = ACS5_VINTAGE,
                             tiger_year: int = TIGER_VINTAGE,
                             out_path: Path | None = None) -> Path:
    """Persist the Section 8 vintage/access contract as deterministic JSON."""
    out_path = out_path or (config.INTERIM_DIR / VINTAGE_PROVENANCE_JSON)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    provenance = build_vintage_provenance(acs_year=acs_year, tiger_year=tiger_year)
    out_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log.info("Saved ACS5/TIGER vintage provenance -> %s", out_path.name)
    return out_path


# --- Step 42: ACS income + %-people-of-colour ------------------------------ #
def census_api_key() -> str | None:
    """Read CENSUS_API_KEY from the environment / repo .env (recommended, optional)."""
    import os
    sec2._load_project_dotenv()
    return os.environ.get("CENSUS_API_KEY") or config.CENSUS_API_KEY


def fetch_acs(year: int = ACS_YEAR, raw_dir: Path | None = None,
              skip_download: bool = False) -> Path:
    """Download ACS5 income (B19013_001E) + B03002 table for Maricopa block groups; returns income JSON path."""
    raw_dir = raw_dir or (config.RAW_DIR / ACS_RAW_SUBDIR)
    raw_dir.mkdir(parents=True, exist_ok=True)
    inc_path = raw_dir / f"acs5_{year}_{INCOME_VAR}_maricopa_bg.json"
    b03_path = raw_dir / f"acs5_{year}_B03002_maricopa_bg.json"
    if skip_download and inc_path.exists() and b03_path.exists():
        log.info("ACS: reusing %s, %s", inc_path.name, b03_path.name)
        return inc_path

    key = census_api_key()
    base = f"{CENSUS_BASE}/{year}/{ACS_DATASET}"
    geo = {"for": "block group:*", "in": f"state:{STATE_FIPS} county:{COUNTY_FIPS}"}
    sess = _session()
    log.info("ACS: %s block groups in Maricopa (state %s county %s), vintage %d%s",
             ACS_DATASET, STATE_FIPS, COUNTY_FIPS, year, "" if key else " (no key)")

    inc_params = {"get": f"NAME,{INCOME_VAR}", **geo}
    if key:
        inc_params["key"] = key
    inc = http_get(base, params=inc_params, sess=sess).json()
    inc_path.write_text(json.dumps(inc), encoding="utf-8")
    log.info("ACS income: %d block groups -> %s", len(inc) - 1, inc_path.name)

    b03_params = {"get": "group(B03002)", **geo}
    if key:
        b03_params["key"] = key
    b03 = http_get(base, params=b03_params, sess=sess).json()
    b03_path.write_text(json.dumps(b03), encoding="utf-8")
    log.info("ACS B03002 table: %d block groups, %d variables -> %s",
             len(b03) - 1, len(b03[0]), b03_path.name)

    src = (f"US Census Bureau ACS 5-year {year} ({ACS_DATASET}; block group; "
           f"state {STATE_FIPS} county {COUNTY_FIPS}; api.census.gov)")
    record_in_manifest(inc_path, src + f"; get=NAME,{INCOME_VAR}", f"{ACS_DATASET}/{year}")
    record_in_manifest(b03_path, src + "; get=group(B03002)", f"{ACS_DATASET}/{year}")
    return inc_path


def build_acs_table(year: int = ACS_YEAR, raw_dir: Path | None = None) -> pd.DataFrame:
    """Merge the two ACS JSONs into a per-block-group table (GEOID, income, %POC); also writes a CSV."""
    raw_dir = raw_dir or (config.RAW_DIR / ACS_RAW_SUBDIR)
    inc = json.loads((raw_dir / f"acs5_{year}_{INCOME_VAR}_maricopa_bg.json").read_text())
    b03 = json.loads((raw_dir / f"acs5_{year}_B03002_maricopa_bg.json").read_text())

    inc_rows = acs_table_to_records(inc[0], inc[1:])
    b03_rows = acs_table_to_records(b03[0], b03[1:])

    recs = []
    inc_by_geoid = {block_group_geoid(r["state"], r["county"], r["tract"], r["block group"]): r
                    for r in inc_rows}
    for r in b03_rows:
        geoid = block_group_geoid(r["state"], r["county"], r["tract"], r["block group"])
        inc_r = inc_by_geoid.get(geoid, {})
        recs.append({
            "GEOID": geoid,
            "TRACT_GEOID": tract_geoid_of(geoid),
            "NAME": inc_r.get("NAME"),
            "median_income": clean_census_value(inc_r.get(INCOME_VAR)),
            "total_pop": clean_census_value(r.get(POC_TOTAL_VAR)),
            "pct_poc": pct_people_of_colour(r.get(POC_TOTAL_VAR), r.get(POC_NHWHITE_VAR)),
        })
    df = pd.DataFrame.from_records(recs).sort_values("GEOID").reset_index(drop=True)

    out_csv = raw_dir / f"acs5_{year}_income_poc_maricopa_bg.csv"
    df.to_csv(out_csv, index=False)
    log.info("ACS table: %d block groups; income non-null=%d, pct_poc non-null=%d -> %s",
             len(df), int(df["median_income"].notna().sum()),
             int(df["pct_poc"].notna().sum()), out_csv.name)
    log.info("ACS: median income median=%.0f USD; pct_poc median=%.1f%%",
             float(df["median_income"].median(skipna=True)),
             float(df["pct_poc"].median(skipna=True)))
    return df


def fetch_block_group_geometries(year: int = ACS_YEAR, raw_dir: Path | None = None,
                                 skip_download: bool = False) -> gpd.GeoDataFrame:
    """Download the TIGER/Line AZ block-group shapefile, filter to Maricopa; returns GEOID+geometry in EPSG:32612."""
    raw_dir = raw_dir or (config.RAW_DIR / ACS_RAW_SUBDIR)
    raw_dir.mkdir(parents=True, exist_ok=True)
    filename = tiger_bg_filename(year)
    url = tiger_bg_url(year)
    zip_path = raw_dir / filename
    if not (skip_download and zip_path.exists()):
        log.info("TIGER: downloading %s", url)
        r = http_get(url, stream=True)
        zip_path.write_bytes(r.content)
        record_in_manifest(
            zip_path,
            f"US Census Bureau TIGER/Line {year} block groups, state {STATE_FIPS} "
            f"({url})", f"TIGER{year}/BG")
    else:
        log.info("TIGER: reusing %s", zip_path.name)

    gdf = gpd.read_file(f"zip://{zip_path}")
    gdf = gdf[gdf["COUNTYFP"] == COUNTY_FIPS].copy()
    gdf = gdf.to_crs(config.CRS)
    gdf = gdf[["GEOID", "geometry"]].reset_index(drop=True)
    log.info("TIGER: %d Maricopa block-group polygons (EPSG:32612)", len(gdf))
    return gdf


# --- Step 43: read tract-level SVI, join DOWN to block groups by FIPS ------- #
def read_svi(svi_dir: Path = SVI_DIR) -> pd.DataFrame:
    """Read the user-supplied CDC/ATSDR SVI CSV (TRACT level) for Maricopa; -999 sentinels -> NaN."""
    csvs = sorted(p for p in svi_dir.glob("*.csv"))
    if not csvs:
        raise SystemExit(
            f"No SVI CSV found in {svi_dir}. Place the CDC/ATSDR SVI CSV there "
            "(tract level) and re-run (protocol step 43 / user instruction).")
    path = csvs[0]
    df = pd.read_csv(path, dtype={SVI_FIPS_COL: str})
    df = df[df[SVI_FIPS_COL].str.startswith(SVI_COUNTY_PREFIX)].copy()
    keep = [SVI_FIPS_COL, SVI_VALUE_COL] + [c for c in SVI_THEME_COLS if c in df.columns]
    df = df[keep].rename(columns={SVI_FIPS_COL: "TRACT_GEOID", SVI_VALUE_COL: "svi"})
    for c in ["svi"] + [c for c in SVI_THEME_COLS if c in df.columns]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
        df.loc[df[c] <= SVI_MISSING, c] = np.nan
    log.info("SVI: %s -> %d Maricopa TRACTS; svi non-null=%d (range [%.3f, %.3f])",
             path.name, len(df), int(df["svi"].notna().sum()),
             float(df["svi"].min(skipna=True)), float(df["svi"].max(skipna=True)))
    return df


def join_svi_to_block_groups(bg: pd.DataFrame, svi: pd.DataFrame) -> pd.DataFrame:
    """Inherit each tract's SVI down to its block groups by TRACT_GEOID; SVI thus varies at tract scale."""
    if "TRACT_GEOID" not in bg.columns:
        bg = bg.assign(TRACT_GEOID=bg["GEOID"].map(tract_geoid_of))
    merged = bg.merge(svi, on="TRACT_GEOID", how="left", validate="many_to_one")
    n_bg = len(merged)
    n_with = int(merged["svi"].notna().sum())
    log.info("SVI join: %d/%d block groups inherited a tract SVI (tract-level value)",
             n_with, n_bg)
    return merged


# --- Step 44: Phoenix tree inventory + functional types -------------------- #
def fetch_tree_inventory(raw_dir: Path | None = None,
                         skip_download: bool = False) -> Path:
    """Page the ASU GAO street-tree FeatureServer layer to a single WGS84 GeoJSON; returns its path."""
    raw_dir = raw_dir or (config.RAW_DIR / TREE_RAW_SUBDIR)
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / TREE_RAW_NAME
    if skip_download and out_path.exists():
        log.info("Trees: reusing %s", out_path.name)
        return out_path

    sess = _session()
    query = f"{TREE_SERVICE}/{TREE_LAYER_ID}/query"
    features: list[dict] = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": ",".join(TREE_OUT_FIELDS),
            "outSR": 4326,
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": TREE_PAGE,
            "returnGeometry": "true",
        }
        fc = http_get(query, params=params, sess=sess).json()
        batch = fc.get("features", [])
        features.extend(batch)
        log.info("Trees: fetched %d (offset %d), total %d", len(batch), offset, len(features))
        if len(batch) < TREE_PAGE or fc.get("exceededTransferLimit") is False and not batch:
            break
        if not batch:
            break
        offset += TREE_PAGE

    out = {"type": "FeatureCollection",
           "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
           "features": features}
    out_path.write_text(json.dumps(out), encoding="utf-8")
    log.info("Trees: %d features -> %s", len(features), out_path.name)
    record_in_manifest(
        out_path,
        f"ASU 'Treelytics' street-tree inventory (ArcGIS FeatureServer, layer "
        f"{TREE_LAYER_ID} 'top20_trees_gao_'); {TREE_SERVICE}", "street_trees_gao_map_by_species")
    return out_path


def clean_tree_inventory(geojson_path: Path) -> gpd.GeoDataFrame:
    """Build the cleaned tree inventory (EPSG:32612) with functional types + survey year.

    inventory_year is the SURVEY year (INV_DATE), NOT a planting date; planting_year is
    NULL for every record because no accessible Phoenix source exposes a true one.
    """
    gdf = gpd.read_file(geojson_path)
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
    gdf = gdf.to_crs(config.CRS)

    gdf["species_botanical"] = gdf.get("SPP_BOT")
    gdf["species_common"] = gdf.get("SPP_COM")
    ft = gdf["species_botanical"].map(functional_type)
    gdf["water_use"] = ft.map(lambda t: t[0])       # drought_tolerant | mesic | unknown
    gdf["leaf_habit"] = ft.map(lambda t: t[1])      # deciduous | evergreen | unknown
    gdf["inventory_year"] = gdf.get("INV_DATE").map(inventory_year_from_epoch_ms)
    gdf["planting_year"] = np.nan                    # true planting year unavailable -> all null

    keep = ["species_botanical", "species_common", "water_use", "leaf_habit",
            "inventory_year", "planting_year",
            "DBH1", "HEIGHT", "COND", "LANDUSE", "geometry"]
    keep = [c for c in keep if c in gdf.columns]
    gdf = gdf[keep].copy()

    wu = gdf["water_use"].value_counts(dropna=False).to_dict()
    lh = gdf["leaf_habit"].value_counts(dropna=False).to_dict()
    n_known = int((gdf["water_use"] != "unknown").sum())
    log.info("Trees cleaned: %d; water_use=%s leaf_habit=%s; species->functype known for %d/%d",
             len(gdf), wu, lh, n_known, len(gdf))
    return gdf


# --- Step 45: building footprints (primary STAC, automatic fallback) -------- #
def bbox_lonlat() -> tuple[float, float, float, float]:
    """Study bbox as (minx, miny, maxx, maxy) in lon/lat (config.BBOX_LONLAT order)."""
    min_lon, max_lon, min_lat, max_lat = config.BBOX_LONLAT
    return (min_lon, min_lat, max_lon, max_lat)


def footprints_via_stac(raw_dir: Path | None = None) -> gpd.GeoDataFrame:
    """PRIMARY route: PC STAC ms-buildings -> signed GeoParquet (quadkey subset) -> clip to bbox (EPSG:32612).

    Reads only the Bing level-9 quadkey partitions covering the bbox. Raises on any
    failure so the caller can fall back.
    """
    import planetary_computer
    import pystac_client
    from adlfs import AzureBlobFileSystem

    raw_dir = raw_dir or (config.RAW_DIR / FOOTPRINTS_RAW_SUBDIR)
    minx, miny, maxx, maxy = bbox_lonlat()
    cat = pystac_client.Client.open(PC_STAC_URL, modifier=planetary_computer.sign_inplace)
    items = list(cat.search(collections=[PC_COLLECTION], bbox=(minx, miny, maxx, maxy)).items())
    if not items:
        raise RuntimeError("PC STAC ms-buildings returned no items for the bbox")
    item = sorted(items, key=lambda it: str(it.properties.get("datetime") or ""), reverse=True)[0]
    asset = item.assets["data"]
    so = asset.extra_fields["table:storage_options"]
    log.info("Footprints/STAC: %d item(s); using newest %s (%s)",
             len(items), item.id, item.properties.get("datetime"))

    qks = bbox_quadkeys((minx, miny, maxx, maxy))
    # The item is a region partition split into quadkey=*/ subdirs; keep only those
    # covering the bbox. (A future quadkey-level item would have no subdirs.)
    fs = AzureBlobFileSystem(account_name=so["account_name"], credential=so["credential"])
    base = asset.href.replace("abfs://", "")
    listing = fs.ls(base, detail=False)
    have_subdirs = any("quadkey=" in e for e in listing)
    parts = []
    if have_subdirs:
        existing = {e.split("quadkey=")[-1] for e in listing if "quadkey=" in e}
        present = [q for q in qks if q in existing]
        if not present:
            raise RuntimeError(f"no ms-buildings quadkey partitions cover bbox (tried {qks})")
        log.info("Footprints/STAC: reading %d quadkey partition(s) at level %d: %s",
                 len(present), BUILDINGS_QUADKEY_LEVEL, present)
        for qk in present:
            g = gpd.read_parquet(f"{asset.href}/quadkey={qk}", storage_options=so)
            parts.append(g)
            log.info("Footprints/STAC: quadkey=%s -> %d polygons", qk, len(g))
    else:
        parts.append(gpd.read_parquet(asset.href, storage_options=so))

    gdf = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=parts[0].crs)
    gdf = gdf[gdf.intersects(box(minx, miny, maxx, maxy))].copy().reset_index(drop=True)
    log.info("Footprints/STAC: %d polygons within the bbox", len(gdf))

    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / FOOTPRINTS_RAW_STAC_NAME
    gdf.to_parquet(raw_path)
    record_in_manifest(
        raw_path,
        f"Microsoft Planetary Computer STAC '{PC_COLLECTION}' (item {item.id}; "
        f"signed with planetary-computer; Bing level-{BUILDINGS_QUADKEY_LEVEL} quadkey "
        f"partitions; {PC_STAC_URL})", PC_COLLECTION)
    return gdf.to_crs(config.CRS)


def footprints_via_fallback(raw_dir: Path | None = None,
                            skip_download: bool = False) -> gpd.GeoDataFrame:
    """FALLBACK route: download MS USBuildingFootprints Arizona.geojson.zip, read bbox features via /vsizip/ (EPSG:32612)."""
    raw_dir = raw_dir or (config.RAW_DIR / FOOTPRINTS_RAW_SUBDIR)
    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path = raw_dir / FOOTPRINTS_FALLBACK_ZIP
    if not (skip_download and zip_path.exists()):
        log.info("Footprints/fallback: downloading %s", FOOTPRINTS_FALLBACK_URL)
        r = http_get(FOOTPRINTS_FALLBACK_URL, stream=True)
        with open(zip_path, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
        log.info("Footprints/fallback: %.1f MB -> %s", zip_path.stat().st_size / 1e6, zip_path.name)
        record_in_manifest(
            zip_path,
            f"Microsoft USBuildingFootprints (Arizona, v2 GeoJSON); {FOOTPRINTS_FALLBACK_URL}",
            "USBuildingFootprints/Arizona")
    else:
        log.info("Footprints/fallback: reusing %s", zip_path.name)

    member = _geojson_member(zip_path)
    minx, miny, maxx, maxy = bbox_lonlat()
    vsi = f"/vsizip/{zip_path}/{member}"
    log.info("Footprints/fallback: reading bbox features from %s", member)
    gdf = gpd.read_file(vsi, bbox=(minx, miny, maxx, maxy))
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
    return gdf.to_crs(config.CRS)


def _geojson_member(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith((".geojson", ".json"))]
    if not names:
        raise RuntimeError(f"No GeoJSON member in {zip_path.name}")
    return names[0]


def acquire_footprints(source: str = "auto", skip_download: bool = False) -> gpd.GeoDataFrame:
    """Get building footprints (EPSG:32612). source auto|stac|fallback; auto tries STAC then falls back."""
    raw_stac = config.RAW_DIR / FOOTPRINTS_RAW_SUBDIR / FOOTPRINTS_RAW_STAC_NAME
    if skip_download and source in ("auto", "stac") and raw_stac.exists():
        gdf = gpd.read_parquet(raw_stac).to_crs(config.CRS)
        log.info("Footprints: reusing %s -> %d polygons (EPSG:32612)", raw_stac.name, len(gdf))
        return gdf
    if source in ("auto", "stac"):
        try:
            gdf = footprints_via_stac()
            log.info("Footprints: %d polygons via PC STAC ms-buildings", len(gdf))
            return gdf
        except Exception as exc:  # noqa: BLE001
            if source == "stac":
                raise
            log.warning("Footprints: STAC route failed (%s: %s) -- falling back to the "
                        "Microsoft USBuildingFootprints Arizona download",
                        type(exc).__name__, exc)
    gdf = footprints_via_fallback(skip_download=skip_download)
    log.info("Footprints: %d polygons via USBuildingFootprints fallback", len(gdf))
    return gdf


# --- Step 46: rasterize neighborhood attributes onto the 70 m grid (nearest)  #
def rasterize_attribute(bg: gpd.GeoDataFrame, column: str, out_path: Path,
                        dtype: str = "float32") -> Path:
    """Burn one block-group attribute onto the 70 m grid, value-per-cell; null attrs stay nodata=NaN."""
    import rasterio

    transform = Affine(*config.GRID_TRANSFORM)
    nrows, ncols = config.GRID_SHAPE
    sub = bg[bg[column].notna()]
    shapes = ((geom, float(val)) for geom, val in zip(sub.geometry, sub[column]))
    grid = rfeatures.rasterize(
        shapes=shapes, out_shape=(nrows, ncols), transform=transform,
        fill=np.nan, all_touched=False, dtype="float64")
    grid = grid.astype(dtype)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_path, "w", driver="GTiff", height=nrows, width=ncols, count=1,
        dtype=dtype, crs=config.CRS, transform=transform, nodata=float("nan"),
        compress="deflate",
    ) as dst:
        dst.write(grid, 1)
        dst.set_band_description(1, column)
    finite = np.isfinite(grid)
    log.info("Rasterized %s -> %s  valid=%.1f%% range=[%.3f, %.3f]",
             column, out_path.name, 100 * finite.mean(),
             float(np.nanmin(grid)) if finite.any() else float("nan"),
             float(np.nanmax(grid)) if finite.any() else float("nan"))
    return out_path


# --- QA figure (deliverable confirmation) ---------------------------------- #
def make_qa_figure(grid_paths: dict[str, Path], tree_gdf: gpd.GeoDataFrame | None,
                   foot_gdf: gpd.GeoDataFrame | None, figures_dir: Path) -> Path | None:
    """Multi-panel QA: the three gridded neighborhood layers + a tree functype bar."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import rioxarray  # noqa: F401

    # Demographic layers use NEUTRAL ramps, never a "heat" map (which reads as a value
    # judgement about the people in a neighborhood).
    panels = [("income", grid_paths.get("income"), "median household income (USD)", "viridis"),
              ("pct_poc", grid_paths.get("pct_poc"), "% people of colour", ps.CMAP["demographic"]),
              ("svi", grid_paths.get("svi"), "CDC SVI (RPL_THEMES)", "cividis")]
    panels = [p for p in panels if p[1] and Path(p[1]).exists()]
    n = len(panels) + (1 if tree_gdf is not None else 0)
    if n == 0:
        return None
    figures_dir.mkdir(parents=True, exist_ok=True)
    left, bottom, right, top = config.GRID_BOUNDS
    extent = (left, right, bottom, top)
    fig, axes = plt.subplots(1, n, figsize=(6.0 * n, 6.0), constrained_layout=True)
    if n == 1:
        axes = [axes]

    import rioxarray
    i = 0
    for key, path, label, cmap in panels:
        da = rioxarray.open_rasterio(path, masked=True).squeeze("band", drop=True)
        ax = axes[i]; i += 1
        im = ax.imshow(da.values, extent=extent, origin="upper", cmap=cmap)
        fig.colorbar(im, ax=ax, label=label, shrink=0.8)
        ax.set_title(f"{label}\n(70 m, nearest/value-per-cell)")
        ax.set_xlabel("Easting (m, EPSG:32612)"); ax.set_ylabel("Northing (m)")

    if tree_gdf is not None:
        ax = axes[i]
        ct = (tree_gdf.groupby(["water_use", "leaf_habit"]).size()
              .unstack(fill_value=0))
        ct.plot(kind="bar", stacked=True, ax=ax)
        ax.set_title(f"Tree inventory functional types\n(n={len(tree_gdf)}, central Phoenix)")
        ax.set_xlabel("water use"); ax.set_ylabel("tree count")
        ax.tick_params(axis="x", rotation=0)

    out = figures_dir / "section8_neighborhood_tree.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote QA figure -> %s", out.name)
    return out


# --- Orchestration / CLI --------------------------------------------------- #
def _quiet_third_party_logging() -> None:
    """Lift the chatty Azure-SDK / fsspec HTTP request loggers to WARNING (footprints)."""
    for noisy in ("azure", "azure.core.pipeline.policies.http_logging_policy",
                  "adlfs", "aiohttp", "fsspec", "urllib3", "pyogrio", "fiona"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def run(parts: Sequence[str] = ("acs", "svi", "trees", "footprints", "grid"),
        skip_download: bool = False, footprints_source: str = "auto",
        year: int = ACS_YEAR, tiger_year: int = TIGER_VINTAGE) -> dict:
    _quiet_third_party_logging()
    config.ensure_dirs()
    parts = set(parts)
    results: dict = {}
    bg: gpd.GeoDataFrame | None = None
    tree_gdf = None
    foot_gdf = None

    # ACS (needed by svi/grid too, since they attach to the block-group frame).
    need_bg = parts & {"acs", "svi", "grid"}
    if need_bg:
        validate_vintage_pair(year, tiger_year, require_pinned=True)
        fetch_acs(year=year, skip_download=skip_download)
        acs = build_acs_table(year=year)
        bg = fetch_block_group_geometries(year=tiger_year, skip_download=skip_download)
        bg = bg.merge(acs, on="GEOID", how="left")
        bg["TRACT_GEOID"] = bg["GEOID"].map(tract_geoid_of)
        bg["acs5_vintage"] = int(year)
        bg["acs5_period"] = ACS5_PERIOD
        bg["acs5_release_date"] = ACS5_RELEASE_DATE
        bg["tiger_line_vintage"] = int(tiger_year)
        bg["tiger_release_date"] = TIGER_RELEASE_DATE
        bg["tiger_boundaries_as_of"] = TIGER_BOUNDARIES_AS_OF
        results["n_block_groups"] = len(bg)

    if parts & {"svi", "grid"} and bg is not None:
        try:
            svi = read_svi()
            bg = join_svi_to_block_groups(bg, svi)
        except SystemExit as exc:
            log.warning("SVI: %s", exc)
            bg["svi"] = np.nan

    if bg is not None:
        provenance_path = write_vintage_provenance(
            acs_year=year, tiger_year=tiger_year)
        results["vintage_provenance"] = provenance_path
        bg_path = config.INTERIM_DIR / BG_INTERIM_PARQUET
        bg.to_parquet(bg_path)
        log.info("Saved block-group neighborhood frame -> %s", bg_path.name)
        results["block_groups_parquet"] = bg_path

    if "trees" in parts:
        tree_path = fetch_tree_inventory(skip_download=skip_download)
        tree_gdf = clean_tree_inventory(tree_path)
        out = config.INTERIM_DIR / TREE_INTERIM_PARQUET
        tree_gdf.to_parquet(out)
        log.info("Saved cleaned tree inventory -> %s", out.name)
        results["tree_parquet"] = out

    if "footprints" in parts:
        foot_gdf = acquire_footprints(source=footprints_source, skip_download=skip_download)
        out = config.INTERIM_DIR / FOOTPRINTS_INTERIM_PARQUET
        foot_gdf.to_parquet(out)
        log.info("Saved building footprints (EPSG:32612) -> %s", out.name)
        results["footprints_parquet"] = out

    grid_paths: dict[str, Path] = {}
    if "grid" in parts and bg is not None:
        grid_paths["income"] = rasterize_attribute(
            bg, "median_income", config.INTERIM_DIR / GRID_INCOME_TIF)
        grid_paths["pct_poc"] = rasterize_attribute(
            bg, "pct_poc", config.INTERIM_DIR / GRID_POC_TIF)
        grid_paths["svi"] = rasterize_attribute(
            bg, "svi", config.INTERIM_DIR / GRID_SVI_TIF)
        results["grid_paths"] = grid_paths

    if grid_paths or tree_gdf is not None:
        make_qa_figure(grid_paths, tree_gdf, foot_gdf, config.FIGURES_DIR)

    _report(results, parts)
    return results


def _report(results: dict, parts: set) -> None:
    log.info("=" * 70)
    log.info("Section 8 complete (parts: %s)", ",".join(sorted(parts)))
    for k in ("n_block_groups", "vintage_provenance", "block_groups_parquet", "tree_parquet",
              "footprints_parquet"):
        if k in results:
            log.info("  %-22s %s", k, results[k])
    if "grid_paths" in results:
        for key, p in results["grid_paths"].items():
            log.info("  grid:%-17s %s", key, Path(p).name)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 8 - neighborhood (ACS income/%POC, CDC SVI) + tree "
                    "inventory + building footprints, on the 70 m grid.")
    p.add_argument("--parts", default="acs,svi,trees,footprints,grid",
                   help="comma list of: acs, svi, trees, footprints, grid (default all).")
    p.add_argument("--skip-download", action="store_true",
                   help="reuse already-downloaded raw files where present.")
    p.add_argument("--footprints-source", default="auto",
                   choices=["auto", "stac", "fallback"],
                   help="footprints route (auto=STAC then fallback).")
    p.add_argument("--acs-year", type=int, default=ACS_YEAR, help="ACS 5-year vintage.")
    p.add_argument("--tiger-year", type=int, default=TIGER_VINTAGE,
                   help="TIGER/Line vintage; must match --acs-year (pilot pin: 2024).")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    run(
        parts=tuple(s.strip() for s in args.parts.split(",") if s.strip()),
        skip_download=args.skip_download,
        footprints_source=args.footprints_source,
        year=args.acs_year,
        tiger_year=args.tiger_year,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
