#!/usr/bin/env python3
"""Section 8 - Acquire neighborhood and tree attributes (protocol steps 42-46).

Implements the whole of Section 8 for the Phoenix pilot from this one module, so
it re-runs end to end from saved code (protocol standing rule: "every figure and
every number must be reproducible from the saved code; nothing produced by hand").

Deliverables (checkpoint, Section 8)
------------------------------------
* Gridded neighborhood income, %-people-of-colour, and social-vulnerability layers
  on the 70 m reference grid (data/interim/*_70m.tif).
* A cleaned tree inventory with functional-type and inventory-year fields
  (data/interim/phoenix_tree_inventory.parquet). NB: a true planting year is
  unavailable, so planting_year is present but null (see the tree note below).
* Building-footprint polygons for the study area, EPSG:32612, kept as vectors for
  the Section 10 exclusion buffer (data/interim/building_footprints_32612.parquet).
All raw downloads are recorded in data/manifest.csv with a SHA-256 checksum.

The five pieces (steps 42-46)
-----------------------------
42. ACS 5-year, block-group, Maricopa County AZ (state 04, county 013): median
    household income B19013_001E + the whole B03002 table (Hispanic-origin-by-race),
    from which %-people-of-colour = 100 * (B03002_001E - B03002_003E) / B03002_001E
    (people of colour := everyone who is NOT non-Hispanic White alone). Block-group
    polygons come from the matching TIGER/Line vintage and are joined by GEOID.
43. CDC/ATSDR Social Vulnerability Index. The user supplies the SVI CSV in
    data/raw/svi/ (it is TRACT level). It is JOINED DOWN to block groups by FIPS:
    every block group inherits its parent tract's SVI value, because the first 11
    digits of a 12-digit block-group GEOID ARE the tract GEOID. SVI therefore
    varies at TRACT scale, not block-group scale, in this analysis (stated here,
    in the code, and in the READMEs).
44. Phoenix municipal tree inventory. Species + functional types are the PRIMARY
    descriptor; detailed species are secondary (protocol pitfall: municipal
    inventories are uneven). See "Tree inventory source" below.
45. Building footprints, downloaded directly (no manual step) and kept as vector
    polygons in EPSG:32612 for the Section 10 tall-building exclusion buffer.
46. Rasterize block-group income, %-people-of-colour, and the joined SVI onto the
    70 m grid (NEAREST / value-per-cell) so every grid cell carries its
    neighborhood attributes (protocol step 48: neighborhood attributes are
    "already-aggregated" -> nearest, never bilinear).

Tree inventory source (an honest resolution, logged + documented)
-----------------------------------------------------------------
The protocol names "City of Phoenix open-data portal (phoenixopendata.com); ASU
Treelytics for species and functional attributes". The CKAN portal at
phoenixopendata.com does NOT host a per-tree inventory (its 160 datasets were
enumerated; only street-landscape-maintenance ZONES match "tree"). The real
Phoenix street-tree inventory with species is the ASU-hosted ArcGIS service the
protocol calls "ASU Treelytics":
    street_trees_gao_map_by_species__WFL1  (FeatureServer layer 1, 'top20_trees_gao_')
22,507 inventoried street/park trees with botanical + common species, condition,
DBH and a SURVEY date (~2011). It covers central Phoenix (the ASU "GAO" flight
area, roughly the core of the study bbox) and the top ~20 species. A TRUE PLANTING
YEAR IS UNAVAILABLE in any accessible Phoenix inventory: the survey date is kept as
``inventory_year`` (the year the tree was surveyed, NOT planted -- do not use it for
tree age), and ``planting_year`` is present but NULL for every record, since protocol
step 44 retains planting year only "where available". This matches the protocol's own
pitfall: inventories are uneven; use broad FUNCTIONAL TYPES (drought-tolerant vs
mesic; deciduous vs evergreen) as the primary descriptor and treat species as
secondary.

Building-footprints route (primary STAC, automatic fallback)
------------------------------------------------------------
PRIMARY (protocol / user instruction): query the Microsoft Planetary Computer STAC
`ms-buildings` collection for the config bbox with pystac-client, sign the assets
with planetary-computer (anonymous signing; no subscription key), read the signed
GeoParquet into geopandas, clip to the bbox. The data asset is `abfs://` on Azure
blob (account bingmlbuildings). FALLBACK (only if the STAC read fails): download
Arizona.geojson.zip from the Microsoft USBuildingFootprints release and clip to the
bbox. Both yield the same deliverable: building polygons in EPSG:32612.

NOTE on this machine: the adlfs/aiohttp read of the abfs:// asset fails here with a
TLS error (ASN1: NOT_ENOUGH_DATA) although sync HTTPS to the same host works; the
module therefore falls back automatically. In a normal environment the STAC path
runs and the fallback is never reached.

Run (canopy env; Census key in .env or CENSUS_API_KEY):
    python src/section8_neighborhood_tree.py                 # full Section 8
    python src/section8_neighborhood_tree.py --parts acs,svi,grid
    python src/section8_neighborhood_tree.py --parts trees
    python src/section8_neighborhood_tree.py --parts footprints --footprints-source fallback
    python src/section8_neighborhood_tree.py --skip-download   # reuse data/raw files
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

import numpy as np
import pandas as pd

# Heavy geospatial libs. The pure logic (%POC, jam-value cleaning, GEOID->tract,
# functional typing, manifest rows) does not touch these, so it stays unit-testable
# without the geo stack installed (see test_section8_neighborhood_tree.py).
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

log = logging.getLogger("section8")

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
# --- ACS / Census (step 42) ---
CENSUS_BASE = config.CENSUS_API_BASE                    # https://api.census.gov/data
ACS_DATASET = "acs/acs5"                                # 5-year estimates
ACS_YEAR = 2024                                         # latest acs5 vintage (verified live)
STATE_FIPS = "04"                                       # Arizona
COUNTY_FIPS = "013"                                     # Maricopa County
INCOME_VAR = "B19013_001E"                              # median household income (USD)
# %-people-of-colour from table B03002 (Hispanic or Latino Origin by Race):
#   total = B03002_001E ; non-Hispanic White alone = B03002_003E
#   people of colour := total - non-Hispanic White alone
POC_TOTAL_VAR = "B03002_001E"
POC_NHWHITE_VAR = "B03002_003E"
# Census "jam values": large negative sentinels meaning not-available / suppressed
# (e.g. -666666666 for median income in near-empty block groups). Treat as null.
CENSUS_JAM_THRESHOLD = -666666600                       # anything <= this is a jam value

# --- TIGER/Line block-group geometry (step 42) ---
TIGER_BG_URL = f"https://www2.census.gov/geo/tiger/TIGER{ACS_YEAR}/BG/tl_{ACS_YEAR}_{STATE_FIPS}_bg.zip"
TIGER_BG_ZIP = f"tl_{ACS_YEAR}_{STATE_FIPS}_bg.zip"

# --- CDC/ATSDR SVI (step 43) ---
SVI_DIR = config.RAW_DIR / "svi"
SVI_FIPS_COL = "FIPS"                                   # 11-digit TRACT GEOID
SVI_COUNTY_PREFIX = STATE_FIPS + COUNTY_FIPS            # "04013"
SVI_VALUE_COL = "RPL_THEMES"                            # overall SVI percentile ranking (0-1)
SVI_THEME_COLS = ["RPL_THEME1", "RPL_THEME2", "RPL_THEME3", "RPL_THEME4"]
SVI_MISSING = -999.0                                    # CDC SVI missing sentinel -> null

# --- Phoenix tree inventory (step 44) ---
TREE_SERVICE = ("https://services3.arcgis.com/0OPQIK59PJJqLK0A/arcgis/rest/services/"
                "street_trees_gao_map_by_species__WFL1/FeatureServer")
TREE_LAYER_ID = 1                                       # 'top20_trees_gao_' master point layer
TREE_OUT_FIELDS = ["SPP_BOT", "SPP_COM", "INV_DATE", "DBH1", "DBH2", "DBH3",
                   "HEIGHT", "COND", "LANDUSE"]
TREE_PAGE = 2000                                        # = layer maxRecordCount
TREE_RAW_NAME = "phoenix_street_trees_gao.geojson"

# --- Building footprints (step 45) ---
PC_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_COLLECTION = "ms-buildings"
# The US ms-buildings items are region-level partitions split into hive subdirs
# quadkey=<Bing-tile>/ at Bing Maps tile level 9. A small bbox only needs the few
# quadkey partitions covering it, so we read those directly (the parquet has no
# bbox-covering column, so geopandas' bbox= read is unavailable here).
BUILDINGS_QUADKEY_LEVEL = 9
FOOTPRINTS_RAW_STAC_NAME = "ms_buildings_phoenix_bbox_4326.parquet"
FOOTPRINTS_FALLBACK_URL = ("https://minedbuildings.z5.web.core.windows.net/"
                           "legacy/usbuildings-v2/Arizona.geojson.zip")
FOOTPRINTS_FALLBACK_ZIP = "USBuildingFootprints_Arizona.geojson.zip"

# --- output filenames (data/interim) ---
ACS_RAW_SUBDIR = "acs"
FOOTPRINTS_RAW_SUBDIR = "footprints"
TREE_RAW_SUBDIR = "trees"
BG_INTERIM_PARQUET = "neighborhood_blockgroups_32612.parquet"
TREE_INTERIM_PARQUET = "phoenix_tree_inventory.parquet"
FOOTPRINTS_INTERIM_PARQUET = "building_footprints_32612.parquet"
GRID_INCOME_TIF = "acs_median_income_70m.tif"
GRID_POC_TIF = "acs_pct_people_of_colour_70m.tif"
GRID_SVI_TIF = "cdc_svi_rpl_themes_70m.tif"

# HTTP retry policy (sync requests; the async/aiohttp path is unreliable here).
HTTP_RETRIES = 5
HTTP_BACKOFF_S = 1.5
HTTP_TIMEOUT_S = 90
USER_AGENT = "canopy-protocol-section8/1.0"


# =========================================================================== #
# Pure logic (numpy/pandas/str only; unit-tested without the geo or network stack)
# =========================================================================== #
def clean_census_value(raw) -> float | None:
    """Parse a Census API string to float, mapping jam values / blanks to None.

    The ACS API returns numbers as strings and uses large negative "jam values"
    (e.g. -666666666) for not-available / suppressed estimates. Those must become
    null, never fed into arithmetic.
    """
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
    """%-people-of-colour = 100 * (total - non-Hispanic White alone) / total.

    People of colour are defined as everyone who is NOT non-Hispanic White alone
    (B03002_001E total minus B03002_003E). Returns None if the total is missing or
    zero. Clipped to [0, 100] to absorb rounding at the extremes.
    """
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
    """The parent TRACT GEOID is the first 11 digits of a 12-digit block-group GEOID.

    Block groups nest exactly within tracts, so this truncation is the FIPS join key
    used to inherit a tract-level SVI value down to each of its block groups
    (protocol step 43 / user instruction). Stated explicitly because SVI varies at
    tract scale, not block-group scale, in this analysis.
    """
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


# --- Bing Maps tile system / quadkeys (pure; ms-buildings is quadkey-partitioned) -
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


# --- functional-type lookup (step 44): the PRIMARY descriptor -----------------
# Two axes the protocol names: water use (drought-tolerant vs mesic) and leaf habit
# (deciduous vs evergreen). Classified for the Phoenix / Sonoran context. The rule
# is GENUS-level (robust to species outside the inventoried top ~20) with a few
# SPECIES overrides where a species departs from its genus default. This mapping is
# a documented, defensible curation -- water-use class is the primary descriptor;
# species-level detail is secondary (protocol pitfall).
#   value: (water_use, leaf_habit)  with water_use in {drought_tolerant, mesic},
#          leaf_habit in {deciduous, evergreen}
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
# Species-level overrides (lowercased "genus species") where the species differs
# from the genus default above.
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
    """Map a botanical species to (water_use, leaf_habit).

    Species override first, then genus default, else ('unknown','unknown'). This is
    the broad FUNCTIONAL grouping that is the primary descriptor (protocol step 44).
    """
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


# =========================================================================== #
# HTTP helpers (sync requests + retries; NOT urllib/aiohttp, which are flaky here)
# =========================================================================== #
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


# =========================================================================== #
# Manifest
# =========================================================================== #
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


# =========================================================================== #
# Step 42 - ACS income + %-people-of-colour
# =========================================================================== #
def census_api_key() -> str | None:
    """Read CENSUS_API_KEY from the environment / repo .env (recommended, optional)."""
    import os
    sec2._load_project_dotenv()
    return os.environ.get("CENSUS_API_KEY") or config.CENSUS_API_KEY


def fetch_acs(year: int = ACS_YEAR, raw_dir: Path | None = None,
              skip_download: bool = False) -> Path:
    """Download ACS5 income (B19013_001E) + the B03002 table for Maricopa block groups.

    Two calls (income + group(B03002)); the raw JSON of each is saved to
    data/raw/acs/ and recorded in the manifest. Returns the income JSON path.
    """
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
    """Merge the two ACS JSONs into a per-block-group table with income + %POC.

    Columns: GEOID, TRACT_GEOID, NAME, median_income, total_pop, pct_poc. The
    computed table is also written to data/raw/acs/ (the ACS-derived product the
    user asked to save there).
    """
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
    """Download the TIGER/Line block-group shapefile for AZ, filter to Maricopa.

    Returns a GeoDataFrame in EPSG:32612 with a GEOID column, clipped (by county) to
    Maricopa. The zip is saved to data/raw/acs/ and recorded in the manifest.
    """
    raw_dir = raw_dir or (config.RAW_DIR / ACS_RAW_SUBDIR)
    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path = raw_dir / TIGER_BG_ZIP
    if not (skip_download and zip_path.exists()):
        log.info("TIGER: downloading %s", TIGER_BG_URL)
        r = http_get(TIGER_BG_URL, stream=True)
        zip_path.write_bytes(r.content)
        record_in_manifest(
            zip_path,
            f"US Census Bureau TIGER/Line {year} block groups, state {STATE_FIPS} "
            f"(www2.census.gov/geo/tiger)", f"TIGER{year}/BG")
    else:
        log.info("TIGER: reusing %s", zip_path.name)

    gdf = gpd.read_file(f"zip://{zip_path}")
    gdf = gdf[gdf["COUNTYFP"] == COUNTY_FIPS].copy()
    gdf = gdf.to_crs(config.CRS)
    gdf = gdf[["GEOID", "geometry"]].reset_index(drop=True)
    log.info("TIGER: %d Maricopa block-group polygons (EPSG:32612)", len(gdf))
    return gdf


# =========================================================================== #
# Step 43 - read tract-level SVI, join DOWN to block groups by FIPS
# =========================================================================== #
def read_svi(svi_dir: Path = SVI_DIR) -> pd.DataFrame:
    """Read the user-supplied CDC/ATSDR SVI CSV (TRACT level) for Maricopa County.

    Returns a frame keyed by TRACT_GEOID with the overall SVI ranking (RPL_THEMES)
    and the four theme rankings, missing sentinels (-999) mapped to NaN.
    """
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
    """Inherit each tract's SVI down to its block groups by FIPS (step 43).

    Block groups nest within tracts, so every block group takes its parent tract's
    SVI: join on TRACT_GEOID = first 11 digits of the block-group GEOID. SVI thus
    varies at TRACT scale, not block-group scale, in this analysis (stated openly
    per the user instruction).
    """
    if "TRACT_GEOID" not in bg.columns:
        bg = bg.assign(TRACT_GEOID=bg["GEOID"].map(tract_geoid_of))
    merged = bg.merge(svi, on="TRACT_GEOID", how="left", validate="many_to_one")
    n_bg = len(merged)
    n_with = int(merged["svi"].notna().sum())
    log.info("SVI join: %d/%d block groups inherited a tract SVI (tract-level value)",
             n_with, n_bg)
    return merged


# =========================================================================== #
# Step 44 - Phoenix tree inventory + functional types
# =========================================================================== #
def fetch_tree_inventory(raw_dir: Path | None = None,
                         skip_download: bool = False) -> Path:
    """Page the ASU GAO street-tree FeatureServer layer to a single GeoJSON file.

    ArcGIS f=geojson returns WGS84; paginate with resultOffset/resultRecordCount.
    Saved to data/raw/trees/ and recorded in the manifest. Returns the GeoJSON path.
    """
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
    """Build the cleaned tree inventory: species, functional types, inventory year.

    Reprojected to EPSG:32612. Adds water_use + leaf_habit (the PRIMARY functional
    descriptor) from the species.

    YEAR FIELDS -- read carefully. A TRUE PLANTING YEAR IS UNAVAILABLE: no accessible
    Phoenix tree inventory (including this ASU GAO source) exposes one. The source
    INV_DATE is the SURVEY date, kept as ``inventory_year``; it must NOT be read as a
    planting date or used to derive tree age. Protocol step 44 retains planting year
    only "where available", so ``planting_year`` is present but NULL for every record
    (honest absence), never aliased to the inventory year.
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
    # inventory_year = the SURVEY year (from INV_DATE). NOT a planting date.
    gdf["inventory_year"] = gdf.get("INV_DATE").map(inventory_year_from_epoch_ms)
    # True planting year is unavailable in any accessible Phoenix source -> all null.
    gdf["planting_year"] = np.nan

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


# =========================================================================== #
# Step 45 - building footprints (primary STAC, automatic fallback)
# =========================================================================== #
def bbox_lonlat() -> tuple[float, float, float, float]:
    """Study bbox as (minx, miny, maxx, maxy) in lon/lat (config.BBOX_LONLAT order)."""
    min_lon, max_lon, min_lat, max_lat = config.BBOX_LONLAT
    return (min_lon, min_lat, max_lon, max_lat)


def footprints_via_stac(raw_dir: Path | None = None) -> gpd.GeoDataFrame:
    """PRIMARY route: PC STAC ms-buildings -> signed GeoParquet -> clip to bbox.

    Discovers the ms-buildings item(s) for the bbox with pystac-client, signs the
    `data` asset with planetary-computer (anonymous signing), and reads ONLY the
    Bing level-9 quadkey partitions covering the bbox (the US partition has no
    bbox-covering column, so a bbox= read is unavailable; quadkey partitioning is
    the supported spatial subset). Concatenates, clips to the bbox keeping whole
    polygons, saves a raw EPSG:4326 copy to data/raw/footprints/ (recorded in the
    manifest), and returns the polygons reprojected to EPSG:32612. Raises on any
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
    # The item is a region-level partition split into quadkey=*/ subdirs; keep only
    # those covering the bbox. (A future quadkey-level item would have no subdirs.)
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
    """FALLBACK route: Microsoft USBuildingFootprints Arizona.geojson.zip -> clip.

    Downloads the AZ zip (sync HTTPS, Range-friendly) to data/raw/footprints/ and
    reads ONLY the bbox features straight out of the zip with a GDAL /vsizip/ +
    spatial filter (no 806 MB unzip). Reprojected to EPSG:32612.
    """
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
    """Get building footprints (EPSG:32612). source: auto|stac|fallback.

    'auto' tries the STAC route first and falls back to the AZ download on failure
    (the documented behaviour: fall back only if the STAC route fails). With
    --skip-download, a previously-saved raw STAC parquet is reused (no re-read).
    """
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


# =========================================================================== #
# Step 46 - rasterize the neighborhood attributes onto the 70 m grid (nearest)
# =========================================================================== #
def rasterize_attribute(bg: gpd.GeoDataFrame, column: str, out_path: Path,
                        dtype: str = "float32") -> Path:
    """Burn one block-group attribute onto the 70 m reference grid (value-per-cell).

    Neighborhood attributes are already-aggregated quantities, so the resampling is
    NEAREST / value-per-cell (protocol step 48): each 70 m cell takes the value of
    the block group that contains its centre. Block groups with a null attribute are
    not burned (their cells stay nodata=NaN). Output aligns exactly to
    processed/reference_grid.tif.
    """
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


# =========================================================================== #
# QA figure (deliverable confirmation)
# =========================================================================== #
def make_qa_figure(grid_paths: dict[str, Path], tree_gdf: gpd.GeoDataFrame | None,
                   foot_gdf: gpd.GeoDataFrame | None, figures_dir: Path) -> Path | None:
    """Multi-panel QA: the three gridded neighborhood layers + a tree functype bar."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import rioxarray  # noqa: F401

    panels = [("income", grid_paths.get("income"), "median household income (USD)", "viridis"),
              ("pct_poc", grid_paths.get("pct_poc"), "% people of colour", "magma"),
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


# =========================================================================== #
# Orchestration / CLI
# =========================================================================== #
def _quiet_third_party_logging() -> None:
    """Silence the very chatty Azure-SDK / fsspec HTTP request logging (footprints).

    adlfs + azure-storage-blob log every blob request/response at INFO, which buries
    the section's own progress. Lift them to WARNING (errors still surface).
    """
    for noisy in ("azure", "azure.core.pipeline.policies.http_logging_policy",
                  "adlfs", "aiohttp", "fsspec", "urllib3", "pyogrio", "fiona"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def run(parts: Sequence[str] = ("acs", "svi", "trees", "footprints", "grid"),
        skip_download: bool = False, footprints_source: str = "auto",
        year: int = ACS_YEAR) -> dict:
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
        fetch_acs(year=year, skip_download=skip_download)
        acs = build_acs_table(year=year)
        bg = fetch_block_group_geometries(year=year, skip_download=skip_download)
        bg = bg.merge(acs, on="GEOID", how="left")
        bg["TRACT_GEOID"] = bg["GEOID"].map(tract_geoid_of)
        results["n_block_groups"] = len(bg)

    if parts & {"svi", "grid"} and bg is not None:
        try:
            svi = read_svi()
            bg = join_svi_to_block_groups(bg, svi)
        except SystemExit as exc:
            log.warning("SVI: %s", exc)
            bg["svi"] = np.nan

    if bg is not None:
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
    for k in ("n_block_groups", "block_groups_parquet", "tree_parquet",
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
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
