#!/usr/bin/env python3
"""Section 9 - Harmonize all layers onto the common 70 m grid (steps 47-51).

Implements the whole of Section 9 for the Phoenix pilot from this one module, so
it re-runs end to end from saved code (protocol standing rule: "every figure and
every number must be reproducible from the saved code; nothing produced by hand").

Objective (protocol Section 9)
------------------------------
Bring every dataset acquired in Sections 2-8 onto the single 70 m reference grid
(Section 1: EPSG:32612, 1155 x 1339, origin 355460/3754380) so any pixel can be
looked up consistently across every variable, and matched in time to the
ECOSTRESS overpasses. After this section the data are geometrically uniform and
time-aligned: a single multi-variable cube indexed by (overpass, y, x).

The five steps (47-51)
----------------------
47. Confirm every raster is already EPSG:32612 and snapped to the reference grid
    (identical cell size, origin, rows, cols). Sections 2-8 wrote every gridded
    layer to the reference grid, so this is a VERIFICATION (assert), not a
    re-snap, for all but one layer.
48. Resample by data TYPE. The only layer not yet on the grid is ERA5-Land
    (native ~9 km, EPSG:4326); it is a CONTINUOUS field, so it is reprojected
    BILINEAR (step 48 lists VPD and soil moisture explicitly). Every other layer
    was already resampled with the correct method in its own section -- bilinear
    for the continuous layers (LST/ET/ESI/NDVI/NDMI/impervious/canopy/precip/
    drought/tmean), NEAREST for the categorical/already-aggregated layers
    (land-cover class, block-group income/%POC/SVI). Nothing categorical is ever
    bilinear-resampled here (the Section 9 pitfall).
49. Match the time-varying data to the ECOSTRESS overpasses. For each of the 66
    LST overpass timestamps:
      * ERA5-Land VPD + soil moisture at the matching HOUR (overpass UTC rounded
        to the nearest hour);
      * antecedent precipitation (ppt_30d/60d/90d) and PRISM tmean at the matching
        DATE (exact calendar date);
      * GRIDMET drought (pdsi/spei30d/spei90d) at the matching PENTAD -- the
        pentad whose 5-day window CONTAINS the overpass date (pentad_start <= D <
        pentad_start + 5 d). See the time-matching note below.
50. Assemble ONE analysis structure indexed by pixel and by overpass holding
    every variable -> a gridded Zarr cube (overpass, y, x), plus a small tidy
    per-overpass metadata/scalar Parquet (the matched hour/date/pentad and the
    regional-mean drivers). See the deliverable note below.
51. Verify alignment at several known locations (a large park, a highway
    interchange, an irrigated golf course): print every layer's value at those
    exact pixels and confirm each is sensible.

Master overpass axis
--------------------
The 66 ECOSTRESS LST overpasses (Section 2 cube; one row per overpass in
overpass_links.parquet, format ``{orbit}_{scene}_{YYYYMMDDTHHMMSS}``) are the
MASTER axis. ET and ESI exist on only 45 of those overpasses (Section 3 pairing);
they are placed on their paired overpasses by ``overpass_key`` and are NaN on the
other 21. The cube therefore has exactly 66 overpass steps.

Time-matching rule (step 49) -- documented precisely
-----------------------------------------------------
* ERA5 HOUR: round the overpass UTC time to the NEAREST hour (e.g. 19:37:50 ->
  20:00). ERA5-Land is hourly and tz-naive UTC; the overpass times are UTC.
* PRISM precip + tmean DATE: the EXACT calendar (UTC) date of the overpass. PRISM
  daily slices are keyed at midnight; we select on the normalized date.
* DROUGHT PENTAD: GRIDMET DROUGHT is pentad (one image every 5 days) and the
  delivered cube holds only WARM-SEASON pentads. The matched pentad is the one
  whose 5-day window CONTAINS the overpass date. The pentads within a season are
  spaced exactly 5 days, so this assigns a pentad at most 5 days old to every
  overpass that falls on/after the season's first pentad. The 2 earliest pilot
  overpasses (2023-06-02, -03) precede the first 2023 pentad (2023-06-04); they
  have NO containing pentad and are left NaN for drought, rather than being given
  the previous season's last pentad (2022-09-27, ~8 months stale and cross-season
  -- a meaningless "nearest preceding" match). Honest absence over a stale value.

ERA5-Land regridding -- efficiency + caveat
-------------------------------------------
ERA5-Land here is an 8 x 10 lat/lon tile (~9 km native) of hourly VPD + soil
moisture, 20496 hours. We do NOT regrid all 20496 hours; for each of the 66
overpasses we take the SINGLE matching-hour 8 x 10 slice and bilinear-reproject
THAT to the 70 m grid (66 small reprojections). ERA5-Land is a smooth REGIONAL
background -- on the 70 m grid VPD/SM vary gently across the city, which is
expected and correct for a ~9 km field (the same caveat as PRISM/GRIDMET in
Section 7); they are regional drivers, not block-scale measurements.

Deliverables (checkpoint, Section 9)
------------------------------------
* data/processed/analysis_cube_70m.zarr  -- THE deliverable. A single aligned
  multi-variable cube on the 70 m grid:
    dims (overpass=66, y=1155, x=1339); coords overpass_key, time, orbit, scene,
    in_et, in_esi, era5_hour, precip_date, drought_pentad (per-overpass), plus
    y/x and a CF spatial_ref (reopen with decode_coords="all" to recover the CRS).
    TIME-VARYING vars (overpass,y,x): lst, et, esi, pet, vpd, sm, ppt_30d,
    ppt_60d, ppt_90d, pdsi, spei30d, spei90d, tmean  (et/esi/pet present only on
    their 45 paired overpasses, NaN elsewhere).
    STATIC vars (y,x), stored once: ndvi, ndmi, impervious, canopy,
    landcover_class (uint8, categorical), median_income, pct_poc, svi.
* data/processed/analysis_overpass_table.parquet -- a SMALL tidy per-overpass
  table (66 rows): overpass_key, time, era5_hour, precip_date, drought_pentad,
  in_et, in_esi, and the regional (area-mean) driver values (vpd/sm/precip/
  drought) for a quick sanity scan. (We deliberately do NOT write a full
  pixel x overpass tidy table -- ~100 M rows -- at this stage: the analysis
  pixels are not defined until Section 10, so a per-pixel long table would be
  wasteful. The gridded Zarr is the primary structure; the tidy Parquet is the
  per-overpass scalar/metadata summary. See the README.)
* figures/section9_alignment_spotcheck.png -- the step-51 known-location check.

Run (canopy env; no network -- reads only data/interim + data/processed):
    python src/section9_harmonize.py                 # full Section 9
    python src/section9_harmonize.py --no-figures     # skip the QA figure
    python src/section9_harmonize.py --verify-only    # re-open + spot-check only
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

# Heavy geospatial libs. The pure logic below (overpass-key parsing, the time-
# matching rules, the resampling-method routing) does not touch them, so it stays
# unit-testable without the geo stack installed (see test_section9_harmonize.py).
import rioxarray  # noqa: F401,E402  (registers the .rio accessor)
import xarray as xr  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402

# Make config + the Section 2 helpers importable whether run from repo root or src/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
import config  # noqa: E402

log = logging.getLogger("section9")


# =========================================================================== #
# Source layers (all already on the 70 m grid except ERA5-Land).
# --------------------------------------------------------------------------- #
# ECOSTRESS cubes (Sections 2-3), each on the 70 m grid.
LST_CUBE = "ecostress_lst_cube"
ET_CUBE = "ecostress_et_cube"
ESI_CUBE = "ecostress_esi_cube"
OVERPASS_LINKS = "overpass_links.parquet"

# Section 7 coarse-but-gridded climate/drought cubes (70 m, time-indexed).
ANTECEDENT_ZARR = "prism_antecedent_precip_70m.zarr"
TMEAN_ZARR = "prism_tmean_70m.zarr"
DROUGHT_ZARR = "gridmet_drought_70m.zarr"

# Section 4/5/8 static single-band layers (70 m). Mapping: cube var -> filename.
# (impervious_fraction/canopy_fraction kept in PERCENT as Section 5 delivered them.)
STATIC_CONTINUOUS = {
    "ndvi": "s2_ndvi_warmseason_median_2023_70m.tif",
    "ndmi": "s2_ndmi_warmseason_median_2023_70m.tif",
    "impervious": "nlcd_impervious_2021_70m.tif",
    "canopy": "usfs_tcc_canopy_2025_70m.tif",
    "median_income": "acs_median_income_70m.tif",
    "pct_poc": "acs_pct_people_of_colour_70m.tif",
    "svi": "cdc_svi_rpl_themes_70m.tif",
}
# The one CATEGORICAL static layer -- NEVER bilinear (already nearest-resampled in
# Section 5; carried through as integer classes).
STATIC_CATEGORICAL = {
    "landcover_class": "nlcd_landcover_class_2021_70m.tif",
}

# ERA5-Land hourly tile (Section 6) -- the ONE layer Section 9 must resample.
ERA5_NC = "era5land_vpd_sm_hourly_2018_2024.nc"
ERA5_VARS = ("vpd", "sm")                         # continuous -> bilinear
ERA5_CRS = "EPSG:4326"                            # native (no CRS written in the .nc)

# Time-varying driver var groups pulled per overpass.
PRECIP_VARS = ("ppt_30d", "ppt_60d", "ppt_90d")   # PRISM antecedent, by DATE
TMEAN_VARS = ("tmean",)                           # PRISM tmean, by DATE
DROUGHT_VARS = ("pdsi", "spei30d", "spei90d")     # GRIDMET drought, by PENTAD

PENTAD_WIDTH_DAYS = 5                             # GRIDMET DROUGHT cadence

# Deliverables (data/processed/).
ANALYSIS_ZARR = "analysis_cube_70m.zarr"
OVERPASS_TABLE_PARQUET = "analysis_overpass_table.parquet"

# Spot-check locations (step 51): (name, lon, lat, expectation). Phoenix
# landmarks whose lon/lat were VERIFIED against the NDVI/impervious/canopy layers
# so each pixel sits on the described feature (the protocol's suggested approximate
# coords were nudged off adjacent roads/shrub onto the feature itself, as the task
# instructed). The exact pixel is the nearest grid-cell centre; values are printed
# so the character can be confirmed.
#   * Encanto Park  ~(-112.090, 33.475): a large irrigated municipal park with
#     mature trees -> high NDVI, real tree CANOPY, low impervious.
#   * I-10/I-17 "Stack" interchange ~(-112.108, 33.471): a multi-level freeway
#     interchange -> ~zero NDVI, ~100% impervious, no canopy.
#   * Papago Golf Course ~(-111.959, 33.461): irrigated turf fairways -> very high
#     NDVI, ~zero impervious, but ~zero tree CANOPY (grass, not trees) -- distinct
#     from the park, which has both green AND canopy.
SPOTCHECK_SITES = (
    ("Encanto Park (large urban park)", -112.090, 33.475,
     "high NDVI, real tree canopy, low impervious"),
    ("I-10/I-17 'Stack' interchange", -112.108, 33.471,
     "near-zero NDVI, ~100% impervious, no canopy"),
    ("Papago Golf Course (irrigated turf)", -111.959, 33.461,
     "very high NDVI, ~zero impervious, ~zero canopy (turf, not trees)"),
)


# =========================================================================== #
# Pure logic (numpy / pandas / str only; unit-tested without the geo stack)
# =========================================================================== #
def overpass_key(orbit: str, scene: str, time: pd.Timestamp) -> str:
    """Compose the canonical overpass key ``{orbit}_{scene}_{YYYYMMDDTHHMMSS}``.

    This is the Section 3 key format (verified against the ET/ESI cubes'
    ``overpass_key`` coord). The LST cube carries orbit/scene/time but NOT the key,
    so it is reconstructed with this exact rule to align LST against ET/ESI and the
    overpass_links table.
    """
    ts = pd.Timestamp(time)
    return f"{orbit}_{scene}_{ts.strftime('%Y%m%dT%H%M%S')}"


def parse_overpass_key(key: str) -> tuple[str, str, pd.Timestamp]:
    """Inverse of :func:`overpass_key`: ``key -> (orbit, scene, timestamp)``.

    The timestamp token is the LAST underscore-separated field (orbit and scene
    never contain a 'T...' time), so split from the right to be robust.
    """
    head, _, tstamp = key.rpartition("_")
    orbit, _, scene = head.partition("_")
    return orbit, scene, pd.Timestamp(_dt.datetime.strptime(tstamp, "%Y%m%dT%H%M%S"))


def resampling_for(layer_kind: str) -> "Resampling":
    """Route a layer KIND to its correct rasterio resampling method (step 48).

    'continuous' -> BILINEAR (temperature, ET, NDVI, NDMI, impervious/canopy
    fraction, VPD, soil moisture, precipitation, drought indices, tmean).
    'categorical' / 'aggregated' -> NEAREST (land-cover class; block-group income,
    %POC and other already-aggregated neighborhood attributes).

    The Section 9 pitfall: a categorical layer bilinear-resampled yields nonsense
    in-between classes (land-cover 4.3), so the method MUST follow the data type.
    """
    kind = layer_kind.lower()
    if kind == "continuous":
        return Resampling.bilinear
    if kind in ("categorical", "aggregated", "nearest"):
        return Resampling.nearest
    raise ValueError(f"unknown layer kind {layer_kind!r} (use continuous|categorical|aggregated)")


def round_to_hour(ts: pd.Timestamp) -> pd.Timestamp:
    """Round a timestamp to the NEAREST hour (the ERA5 hour-match rule, step 49)."""
    return pd.Timestamp(ts).round("h")


def overpass_date(ts: pd.Timestamp) -> _dt.date:
    """The calendar (UTC) date of an overpass (the PRISM date-match rule, step 49)."""
    return pd.Timestamp(ts).normalize().date()


def match_pentad(date, pentad_starts: Sequence, width_days: int = PENTAD_WIDTH_DAYS):
    """The pentad whose ``width_days`` window CONTAINS ``date`` (drought match, step 49).

    A pentad with start P covers ``[P, P + width_days)``. Returns the latest pentad
    start P with ``P <= date < P + width_days``, or None if no pentad's window
    contains the date (e.g. an overpass before the season's first pentad). Returning
    None -- not the nearest PRECEDING pentad -- avoids assigning a stale cross-season
    value (the delivered drought cube holds only warm-season pentads, so the nearest
    preceding pentad for an early-June overpass is the PREVIOUS September's, ~8
    months old). ``pentad_starts`` are normalized (midnight) timestamps/dates.
    """
    d = pd.Timestamp(date).normalize()
    w = pd.Timedelta(days=width_days)
    best = None
    for p in pentad_starts:
        p = pd.Timestamp(p).normalize()
        if p <= d < p + w:
            if best is None or p > best:
                best = p
    return best


def build_overpass_index(orbit, scene, time) -> pd.DataFrame:
    """Per-overpass index table from the LST cube's orbit/scene/time coordinates.

    Returns a DataFrame with overpass_key, time, orbit, scene, era5_hour and
    precip_date -- the master axis the analysis cube is indexed by, in input order.
    """
    rows = []
    for o, s, t in zip(orbit, scene, time):
        t = pd.Timestamp(t)
        rows.append({
            "overpass_key": overpass_key(str(o), str(s), t),
            "time": t,
            "orbit": str(o),
            "scene": str(s),
            "era5_hour": round_to_hour(t),
            "precip_date": pd.Timestamp(overpass_date(t)),
        })
    return pd.DataFrame(rows)


# =========================================================================== #
# Loading + alignment helpers (the geo stack)
# =========================================================================== #
def _reference():
    """The 70 m reference grid as a 2-D rioxarray DataArray (the match target/CRS)."""
    return rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)


def _assert_on_grid(da: "xr.DataArray", name: str, reference: "xr.DataArray") -> None:
    """Step 47: assert a layer is EPSG:32612 and snapped to the reference grid.

    Identical CRS, cell size, origin, rows and cols. Raises with a precise message
    if anything is off, so a mis-aligned layer is caught here, never silently
    carried into the cube.
    """
    crs = da.rio.crs
    if crs is None or crs.to_epsg() != reference.rio.crs.to_epsg():
        raise AssertionError(f"{name}: CRS {crs} != reference {reference.rio.crs}")
    if da.sizes.get("y") != reference.sizes["y"] or da.sizes.get("x") != reference.sizes["x"]:
        raise AssertionError(
            f"{name}: shape (y={da.sizes.get('y')}, x={da.sizes.get('x')}) != "
            f"reference (y={reference.sizes['y']}, x={reference.sizes['x']})")
    if not np.allclose(da.x.values, reference.x.values, atol=1e-6):
        raise AssertionError(f"{name}: x coordinates do not match the reference grid")
    if not np.allclose(da.y.values, reference.y.values, atol=1e-6):
        raise AssertionError(f"{name}: y coordinates do not match the reference grid")


def load_static_layers(reference: "xr.DataArray", interim: Path
                       ) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Load the static (y,x) layers, asserting each is already on the grid (step 47).

    Returns (continuous_arrays, categorical_arrays). Continuous layers are float32
    (NaN nodata); the categorical land-cover layer is kept as its integer class
    codes (nodata 0 -> retained as 0 "no class"; never turned into a float, so no
    fractional classes). No resampling happens here -- they were resampled with the
    correct method in their own sections; this only verifies alignment and reads.
    """
    cont: dict[str, np.ndarray] = {}
    for name, fn in STATIC_CONTINUOUS.items():
        da = rioxarray.open_rasterio(interim / fn, masked=True).squeeze("band", drop=True)
        _assert_on_grid(da, name, reference)
        cont[name] = da.values.astype("float32")
        log.info("  static  %-15s float32  on-grid OK", name)
    cat: dict[str, np.ndarray] = {}
    for name, fn in STATIC_CATEGORICAL.items():
        da = rioxarray.open_rasterio(interim / fn).squeeze("band", drop=True)  # NOT masked
        _assert_on_grid(da, name, reference)
        cat[name] = da.values.astype("uint8")
        uniq = np.unique(cat[name])
        log.info("  static  %-15s uint8 (categorical) on-grid OK; classes=%s",
                 name, uniq.tolist())
    return cont, cat


def reconstruct_lst_keys(lst: "xr.Dataset") -> list[str]:
    """Reconstruct each LST overpass's key from its orbit/scene/time (the LST cube
    has no ``overpass_key`` coord). Used to align ET/ESI by key onto the LST axis."""
    orbit = lst["orbit"].values
    scene = lst["scene"].values
    time = pd.to_datetime(lst["time"].values)
    return [overpass_key(str(o), str(s), t) for o, s, t in zip(orbit, scene, time)]


def align_paired_cube(cube: "xr.Dataset", var: str, master_keys: Sequence[str],
                      reference: "xr.DataArray") -> np.ndarray:
    """Place a 45-overpass ET/ESI variable onto the 66-overpass master axis.

    Selects each master overpass's slice by ``overpass_key`` (Section 3 pairing);
    overpasses absent from this cube get an all-NaN slice. Asserts the cube shares
    the reference grid (step 47). Returns a (66, y, x) float32 array.
    """
    _assert_on_grid(cube[var], f"{var} cube", reference)
    key_to_pos = {str(k): i for i, k in enumerate(cube["overpass_key"].values)}
    ny, nx = reference.sizes["y"], reference.sizes["x"]
    vals = cube[var].values.astype("float32")
    out = np.full((len(master_keys), ny, nx), np.nan, dtype="float32")
    n_present = 0
    for i, key in enumerate(master_keys):
        pos = key_to_pos.get(str(key))
        if pos is not None:
            out[i] = vals[pos]
            n_present += 1
    log.info("  paired  %-15s present on %d/%d overpasses (NaN elsewhere)",
             var, n_present, len(master_keys))
    return out


def reproject_era5_slice(slice2d: "xr.DataArray", reference: "xr.DataArray") -> np.ndarray:
    """Bilinear-reproject ONE ERA5-Land 8x10 lat/lon slice onto the 70 m grid.

    ERA5-Land carries no CRS in the .nc, so EPSG:4326 is written before the
    reproject_match. Continuous field -> BILINEAR (step 48). The result is the
    smooth regional VPD/SM background sampled at 70 m (expected for a ~9 km field).
    """
    src = slice2d.rio.write_crs(ERA5_CRS)
    matched = src.rio.reproject_match(reference, resampling=resampling_for("continuous"))
    return matched.values.astype("float32")


def select_by_time(cube: "xr.Dataset", var: str, when, reference: "xr.DataArray",
                   label: str) -> np.ndarray:
    """Nearest-time slice of a gridded driver cube for a given timestamp/date.

    Used for PRISM precip/tmean (exact date) where the requested ``when`` is one of
    the cube's daily steps. ``method='nearest'`` is a guard (the date is present);
    asserts the driver cube is on the reference grid (step 47).
    """
    _assert_on_grid(cube[var], f"{label} cube", reference)
    sel = cube[var].sel(time=pd.Timestamp(when), method="nearest")
    return sel.values.astype("float32")


# =========================================================================== #
# Assembly (step 50) -> the gridded analysis Zarr
# =========================================================================== #
def _blosc():
    import numcodecs
    return numcodecs.Blosc(cname="zstd", clevel=5, shuffle=numcodecs.Blosc.SHUFFLE)


def assemble_analysis_cube(interim: Path, reference: "xr.DataArray") -> xr.Dataset:
    """Build the (overpass, y, x) analysis cube holding every variable (step 50).

    Time-varying vars are matched to each of the 66 LST overpasses per the step-49
    rule; static vars are attached once as (y, x). The dataset carries the CRS via
    rio.write_crs + a per-var ``grid_mapping='spatial_ref'`` attr so it reloads with
    decode_coords="all" (matching the existing project cubes).
    """
    ny, nx = reference.sizes["y"], reference.sizes["x"]

    # ---- master overpass axis: the 66 LST overpasses ---------------------- #
    lst = xr.open_zarr(interim / LST_CUBE, decode_coords="all")
    _assert_on_grid(lst["lst"], "lst cube", reference)
    idx = build_overpass_index(lst["orbit"].values, lst["scene"].values,
                               pd.to_datetime(lst["time"].values))
    master_keys = idx["overpass_key"].tolist()
    n = len(master_keys)
    log.info("Master axis: %d ECOSTRESS LST overpasses", n)

    # Cross-check the reconstructed keys against overpass_links.parquet (if present).
    links_path = interim / OVERPASS_LINKS
    in_et = np.zeros(n, dtype=bool)
    in_esi = np.zeros(n, dtype=bool)
    if links_path.exists():
        links = pd.read_parquet(links_path).set_index("overpass_key")
        same = list(links.index) == master_keys
        log.info("overpass_links.parquet: %d rows; key order matches LST cube: %s",
                 len(links), same)
        in_et = np.array([bool(links.loc[k, "in_et"]) if k in links.index else False
                          for k in master_keys])
        in_esi = np.array([bool(links.loc[k, "in_esi"]) if k in links.index else False
                           for k in master_keys])

    data_vars: dict[str, tuple] = {}

    # ---- LST (master variable) -------------------------------------------- #
    data_vars["lst"] = (("overpass", "y", "x"), lst["lst"].values.astype("float32"))

    # ---- ET / ESI / PET on the master axis (paired; NaN where absent) ----- #
    et = xr.open_zarr(interim / ET_CUBE, decode_coords="all")
    esi = xr.open_zarr(interim / ESI_CUBE, decode_coords="all")
    data_vars["et"] = (("overpass", "y", "x"), align_paired_cube(et, "et", master_keys, reference))
    data_vars["esi"] = (("overpass", "y", "x"), align_paired_cube(esi, "esi", master_keys, reference))
    data_vars["pet"] = (("overpass", "y", "x"), align_paired_cube(esi, "pet", master_keys, reference))

    # ---- ERA5-Land VPD + SM at the matching HOUR (bilinear, per overpass) -- #
    era = xr.open_dataset(interim / ERA5_NC)
    era_times = pd.to_datetime(era["time"].values)
    era_set = set(era_times)
    vpd_out = np.full((n, ny, nx), np.nan, dtype="float32")
    sm_out = np.full((n, ny, nx), np.nan, dtype="float32")
    n_era = 0
    for i, hour in enumerate(idx["era5_hour"]):
        hour = pd.Timestamp(hour)
        if hour in era_set:
            vpd_out[i] = reproject_era5_slice(era["vpd"].sel(time=hour), reference)
            sm_out[i] = reproject_era5_slice(era["sm"].sel(time=hour), reference)
            n_era += 1
    data_vars["vpd"] = (("overpass", "y", "x"), vpd_out)
    data_vars["sm"] = (("overpass", "y", "x"), sm_out)
    log.info("  ERA5    vpd/sm  bilinear-reprojected for %d/%d overpasses "
             "(matched hour)", n_era, n)

    # ---- PRISM antecedent precip + tmean at the matching DATE -------------- #
    ant = xr.open_zarr(interim / ANTECEDENT_ZARR, decode_coords="all")
    tm = xr.open_zarr(interim / TMEAN_ZARR, decode_coords="all")
    for v in PRECIP_VARS:
        arr = np.full((n, ny, nx), np.nan, dtype="float32")
        for i, d in enumerate(idx["precip_date"]):
            arr[i] = select_by_time(ant, v, d, reference, "antecedent")
        data_vars[v] = (("overpass", "y", "x"), arr)
    tmean_arr = np.full((n, ny, nx), np.nan, dtype="float32")
    for i, d in enumerate(idx["precip_date"]):
        tmean_arr[i] = select_by_time(tm, "tmean", d, reference, "tmean")
    data_vars["tmean"] = (("overpass", "y", "x"), tmean_arr)
    log.info("  PRISM   %s + tmean attached by exact DATE", ", ".join(PRECIP_VARS))

    # ---- GRIDMET drought at the matching PENTAD (window-contains) ---------- #
    dro = xr.open_zarr(interim / DROUGHT_ZARR, decode_coords="all")
    _assert_on_grid(dro[DROUGHT_VARS[0]], "drought cube", reference)
    pentad_starts = pd.to_datetime(dro["time"].values).normalize()
    matched_pentads: list = []
    for d in idx["precip_date"]:
        matched_pentads.append(match_pentad(d, pentad_starts))
    n_pentad = sum(p is not None for p in matched_pentads)
    for v in DROUGHT_VARS:
        arr = np.full((n, ny, nx), np.nan, dtype="float32")
        for i, p in enumerate(matched_pentads):
            if p is not None:
                arr[i] = dro[v].sel(time=pd.Timestamp(p)).values.astype("float32")
        data_vars[v] = (("overpass", "y", "x"), arr)
    log.info("  GRIDMET drought %s matched to a containing pentad for %d/%d overpasses "
             "(%d early-season overpass(es) have no pentad -> NaN)",
             ", ".join(DROUGHT_VARS), n_pentad, n, n - n_pentad)
    idx["drought_pentad"] = [pd.Timestamp(p) if p is not None else pd.NaT
                             for p in matched_pentads]

    # ---- static (y, x) layers, attached once ------------------------------ #
    cont, cat = load_static_layers(reference, interim)
    for name, arr in cont.items():
        data_vars[name] = (("y", "x"), arr)
    for name, arr in cat.items():
        data_vars[name] = (("y", "x"), arr)

    # ---- coords + Dataset ------------------------------------------------- #
    coords = {
        "overpass": np.arange(n, dtype="int32"),
        "overpass_key": ("overpass", np.array(master_keys, dtype=object)),
        "time": ("overpass", idx["time"].to_numpy()),
        "orbit": ("overpass", idx["orbit"].to_numpy()),
        "scene": ("overpass", idx["scene"].to_numpy()),
        "in_et": ("overpass", in_et),
        "in_esi": ("overpass", in_esi),
        "era5_hour": ("overpass", idx["era5_hour"].to_numpy()),
        "precip_date": ("overpass", idx["precip_date"].to_numpy()),
        "drought_pentad": ("overpass", idx["drought_pentad"].to_numpy()),
        "y": reference.y.values,
        "x": reference.x.values,
    }
    ds = xr.Dataset(data_vars, coords=coords)
    ds = ds.rio.write_crs(reference.rio.crs)
    # Pin CF grid_mapping in each spatial var's attrs so it survives to_zarr and the
    # CRS reloads with decode_coords="all" (matches the Section 2/3/7 cubes).
    for v in ds.data_vars:
        if {"y", "x"} <= set(ds[v].dims):
            ds[v].attrs["grid_mapping"] = "spatial_ref"
    # Units / provenance attrs.
    _annotate(ds)
    return ds


def _annotate(ds: "xr.Dataset") -> None:
    """Attach short units/notes to the variables (provenance for later sections)."""
    units = {
        "lst": "K", "et": "W m-2", "esi": "1", "pet": "W m-2",
        "vpd": "kPa", "sm": "m3 m-3",
        "ppt_30d": "mm", "ppt_60d": "mm", "ppt_90d": "mm",
        "pdsi": "index", "spei30d": "index", "spei90d": "index", "tmean": "degC",
        "ndvi": "1", "ndmi": "1", "impervious": "percent", "canopy": "percent",
        "landcover_class": "NLCD class code", "median_income": "USD",
        "pct_poc": "percent", "svi": "percentile 0-1",
    }
    for v, u in units.items():
        if v in ds:
            ds[v].attrs.setdefault("units", u)
    ds.attrs["title"] = ("Section 9 analysis cube: all layers harmonized onto the 70 m "
                         "reference grid, time-matched to the ECOSTRESS overpasses")
    ds.attrs["crs"] = config.CRS
    ds.attrs["grid_origin_xy"] = list(config.GRID_ORIGIN_XY)
    ds.attrs["cell_size_m"] = config.CELL_SIZE_M
    ds.attrs["time_matching"] = ("ERA5 VPD/SM: nearest hour; PRISM precip+tmean: exact "
                                 "date; GRIDMET drought: pentad whose 5-day window "
                                 "contains the overpass date (NaN if none).")


def write_analysis_zarr(ds: "xr.Dataset", store: Path) -> Path:
    """Write the analysis cube to a compressed, sensibly-chunked Zarr (step 50).

    Time-varying vars chunk as (1 overpass, full y, full x); static (y,x) vars as
    one full tile. object/datetime coords are left uncompressed (Blosc cannot encode
    them). Overwrites any existing store.
    """
    if store.exists():
        import shutil
        shutil.rmtree(store)
    ny, nx = ds.sizes["y"], ds.sizes["x"]
    comp = _blosc()
    enc: dict[str, dict] = {}
    for v in ds.data_vars:
        dims = ds[v].dims
        if dims == ("overpass", "y", "x"):
            enc[v] = {"compressor": comp, "chunks": (1, ny, nx)}
        elif dims == ("y", "x"):
            enc[v] = {"compressor": comp, "chunks": (ny, nx)}
    store.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(store, mode="w", encoding=enc, consolidated=True)
    log.info("Wrote analysis cube -> %s", store)
    log.info("  dims=%s", dict(ds.sizes))
    log.info("  time-varying vars: %s",
             [v for v in ds.data_vars if ds[v].dims == ("overpass", "y", "x")])
    log.info("  static vars:       %s",
             [v for v in ds.data_vars if ds[v].dims == ("y", "x")])
    return store


def write_overpass_table(ds: "xr.Dataset", out_path: Path) -> Path:
    """Write the small tidy per-overpass metadata/scalar table (step 50, optional).

    66 rows: overpass_key, time, era5_hour, precip_date, drought_pentad, in_et,
    in_esi, and the regional (area-mean) driver values for a quick sanity scan. NOT
    a per-pixel long table (that is deferred to Section 10, once analysis pixels are
    defined -- a full pixel x overpass table would be ~100 M rows and wasteful now).
    """
    n = ds.sizes["overpass"]
    rec = {
        "overpass_key": ds["overpass_key"].values,
        "time": pd.to_datetime(ds["time"].values),
        "era5_hour": pd.to_datetime(ds["era5_hour"].values),
        "precip_date": pd.to_datetime(ds["precip_date"].values),
        "drought_pentad": pd.to_datetime(ds["drought_pentad"].values),
        "in_et": ds["in_et"].values,
        "in_esi": ds["in_esi"].values,
    }
    # Regional (area-mean) driver values per overpass for a quick scan.
    for v in ("lst", "vpd", "sm", "ppt_30d", "pdsi", "spei90d", "tmean"):
        if v in ds:
            rec[f"{v}_regional_mean"] = ds[v].mean(dim=("y", "x"), skipna=True).values
    df = pd.DataFrame(rec)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    log.info("Wrote per-overpass table -> %s (%d rows, %d cols)",
             out_path, len(df), df.shape[1])
    return out_path


# =========================================================================== #
# Verification (step 47 re-open assertions + step 51 known-location spot check)
# =========================================================================== #
def verify_grid(store: Path, reference: "xr.DataArray") -> "xr.Dataset":
    """Re-open the saved cube and PRINT/ASSERT its geometry matches the reference.

    Confirms dims, CRS, pixel size, shape, origin equal reference_grid.tif EXACTLY;
    that landcover_class is integer (no fractional classes) and the continuous
    layers are float. Returns the reopened dataset for the spot check.
    """
    ds = xr.open_zarr(store, decode_coords="all")
    log.info("=" * 70)
    log.info("VERIFY (step 47): reopened %s", store.name)
    log.info("  dims              %s", dict(ds.sizes))
    tv = [v for v in ds.data_vars if ds[v].dims == ("overpass", "y", "x")]
    st = [v for v in ds.data_vars if ds[v].dims == ("y", "x")]
    log.info("  time-varying vars (%d) %s", len(tv), tv)
    log.info("  static vars       (%d) %s", len(st), st)
    crs = ds.rio.crs
    tx = ds.rio.transform()
    log.info("  CRS               %s", crs)
    log.info("  transform         %s", tuple(tx))
    log.info("  pixel size        (%.1f, %.1f) m", tx.a, tx.e)
    log.info("  shape (y, x)      (%d, %d)", ds.sizes["y"], ds.sizes["x"])
    log.info("  origin (x, y)     (%.1f, %.1f)", tx.c, tx.f)

    assert crs.to_epsg() == reference.rio.crs.to_epsg(), "CRS mismatch vs reference"
    assert ds.sizes["y"] == reference.sizes["y"] and ds.sizes["x"] == reference.sizes["x"], \
        "shape mismatch vs reference"
    rtx = reference.rio.transform()
    assert np.allclose([tx.a, tx.e, tx.c, tx.f], [rtx.a, rtx.e, rtx.c, rtx.f], atol=1e-6), \
        "transform (pixel size / origin) mismatch vs reference"
    assert np.allclose(ds.x.values, reference.x.values, atol=1e-6), "x mismatch"
    assert np.allclose(ds.y.values, reference.y.values, atol=1e-6), "y mismatch"
    assert np.issubdtype(ds["landcover_class"].dtype, np.integer), \
        "landcover_class must be integer (categorical), not float"
    lc = ds["landcover_class"].values
    assert np.all(lc == lc.astype("int64")), "landcover_class has fractional classes!"
    for v in ("lst", "vpd", "sm", "ndvi", "impervious", "canopy"):
        assert np.issubdtype(ds[v].dtype, np.floating), f"{v} should be float (continuous)"
    log.info("  ASSERTIONS PASSED: geometry == reference_grid.tif; landcover_class is "
             "integer/categorical; continuous layers are float.")
    return ds


def sample_overpass_time_match(ds: "xr.Dataset", i: int = 0) -> None:
    """Step-49 evidence: PRINT the matched hour/date/pentad for one overpass."""
    log.info("=" * 70)
    log.info("TIME MATCH (step 49) for overpass %d:", i)
    log.info("  overpass_key   %s", str(ds["overpass_key"].values[i]))
    log.info("  overpass time  %s (UTC)", pd.Timestamp(ds["time"].values[i]))
    log.info("  -> ERA5 hour   %s  (nearest hour)", pd.Timestamp(ds["era5_hour"].values[i]))
    log.info("  -> precip date %s  (exact calendar date)",
             pd.Timestamp(ds["precip_date"].values[i]).date())
    dp = ds["drought_pentad"].values[i]
    log.info("  -> drought pentad %s  (pentad window containing the date)",
             pd.Timestamp(dp).date() if not pd.isnull(dp) else "NONE (early-season -> NaN)")


def lonlat_to_rowcol(lon: float, lat: float, reference: "xr.DataArray") -> tuple[int, int]:
    """Nearest grid (row, col) for a lon/lat point (reproject the point to EPSG:32612).

    Uses the reference grid's coordinate vectors so the pixel is the same cell every
    other layer is on.
    """
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", config.CRS, always_xy=True)
    x, y = tr.transform(lon, lat)
    col = int(np.argmin(np.abs(reference.x.values - x)))
    row = int(np.argmin(np.abs(reference.y.values - y)))
    return row, col


def spot_check(ds: "xr.Dataset", reference: "xr.DataArray", overpass_i: int = 0
               ) -> list[dict]:
    """Step 51: PRINT every layer's value at known locations and return the rows.

    For each landmark (a large park, a highway interchange, an irrigated golf
    course) prints the static layers (NDVI/NDMI/impervious/canopy/land-cover/
    neighborhood) and one representative overpass's time-varying layers (LST/ET/
    ESI/VPD/SM/precip/drought/tmean) at that exact pixel, with the expectation, so
    the character can be confirmed.
    """
    log.info("=" * 70)
    log.info("SPOT CHECK (step 51): known-location values at exact pixels")
    log.info("  representative overpass = %d (%s, %s UTC)", overpass_i,
             str(ds["overpass_key"].values[overpass_i]),
             pd.Timestamp(ds["time"].values[overpass_i]))
    static_vars = [v for v in ds.data_vars if ds[v].dims == ("y", "x")]
    tvar = [v for v in ds.data_vars if ds[v].dims == ("overpass", "y", "x")]
    rows: list[dict] = []
    for name, lon, lat, expect in SPOTCHECK_SITES:
        row, col = lonlat_to_rowcol(lon, lat, reference)
        log.info("-" * 70)
        log.info("%s", name)
        log.info("  lon/lat (%.4f, %.4f) -> grid (row=%d, col=%d); expect: %s",
                 lon, lat, row, col, expect)
        rec = {"site": name, "lon": lon, "lat": lat, "row": row, "col": col}
        # static layers (the character markers)
        smsg = []
        for v in static_vars:
            val = ds[v].isel(y=row, x=col).values
            val = val.item() if np.ndim(val) == 0 else val
            rec[v] = val
            smsg.append(f"{v}={_fmt(val)}")
        log.info("  static : %s", "  ".join(smsg))
        # time-varying layers at the representative overpass
        tmsg = []
        for v in tvar:
            val = ds[v].isel(overpass=overpass_i, y=row, x=col).values
            val = float(val) if np.ndim(val) == 0 else val
            rec[f"{v}@op{overpass_i}"] = val
            tmsg.append(f"{v}={_fmt(val)}")
        log.info("  op%-4d : %s", overpass_i, "  ".join(tmsg))
        rows.append(rec)
    return rows


def _fmt(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if np.isnan(f):
        return "NaN"
    if abs(f) >= 1000 or (abs(f) < 0.01 and f != 0):
        return f"{f:.3g}"
    return f"{f:.3f}"


def make_spotcheck_figure(ds: "xr.Dataset", reference: "xr.DataArray",
                          rows: list[dict], figures_dir: Path,
                          overpass_i: int = 0) -> Path | None:
    """QA figure: NDVI + impervious + a representative LST map with the 3 sites marked.

    Visual confirmation that the spot-check pixels sit where expected (park =
    green/cool, interchange = bare/hot) and that the layers co-register.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    left, bottom, right, top = config.GRID_BOUNDS
    extent = (left, right, bottom, top)
    panels = [("ndvi", "NDVI (warm-season median)", "YlGn", None, None),
              ("impervious", "Impervious surface (%)", "magma", 0, 100),
              ("lst", f"LST (K), overpass {overpass_i}", "inferno", None, None)]
    fig, axes = plt.subplots(1, 3, figsize=(18, 6), constrained_layout=True)
    for ax, (v, title, cmap, vmin, vmax) in zip(axes, panels):
        if ds[v].dims == ("overpass", "y", "x"):
            arr = ds[v].isel(overpass=overpass_i).values
        else:
            arr = ds[v].values
        im = ax.imshow(arr, extent=extent, origin="upper", cmap=cmap, vmin=vmin, vmax=vmax)
        fig.colorbar(im, ax=ax, shrink=0.8)
        ax.set_title(title)
        ax.set_xlabel("Easting (m, EPSG:32612)"); ax.set_ylabel("Northing (m)")
        # mark the sites
        for r in rows:
            xx = reference.x.values[r["col"]]
            yy = reference.y.values[r["row"]]
            ax.plot(xx, yy, "o", ms=9, mfc="none", mec="cyan", mew=2)
            ax.annotate(r["site"].split(" (")[0], (xx, yy), color="cyan",
                        fontsize=8, xytext=(6, 6), textcoords="offset points")
    fig.suptitle("Section 9 alignment spot-check: layers co-register on the 70 m grid\n"
                 "(park = high NDVI / cooler; interchange = high impervious / hotter)",
                 fontsize=12)
    out = figures_dir / "section9_alignment_spotcheck.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote spot-check figure -> %s", out.name)
    return out


# =========================================================================== #
# Orchestration / CLI
# =========================================================================== #
def run(make_figures: bool = True, verify_only: bool = False) -> dict:
    config.ensure_dirs()
    interim = config.INTERIM_DIR
    reference = _reference()
    store = config.PROCESSED_DIR / ANALYSIS_ZARR
    results: dict = {}

    if not verify_only:
        ds = assemble_analysis_cube(interim, reference)
        write_analysis_zarr(ds, store)
        results["analysis_zarr"] = store
        results["overpass_table"] = write_overpass_table(ds, config.PROCESSED_DIR / OVERPASS_TABLE_PARQUET)

    # Re-open from disk and verify (step 47), show a time match (step 49),
    # and spot-check known locations (step 51).
    ds = verify_grid(store, reference)
    results["dims"] = dict(ds.sizes)
    results["variables"] = list(ds.data_vars)
    sample_overpass_time_match(ds, i=0)
    # Use a mid-season overpass for the spot check so ET/ESI are likely present.
    rep = _pick_paired_overpass(ds)
    rows = spot_check(ds, reference, overpass_i=rep)
    results["spotcheck"] = rows
    if make_figures:
        results["figure"] = make_spotcheck_figure(ds, reference, rows, config.FIGURES_DIR, rep)

    _report(results)
    return results


def _pick_paired_overpass(ds: "xr.Dataset") -> int:
    """A representative overpass for the spot check: best LST spatial COVERAGE.

    Each ECOSTRESS scene covers only a sliver of the bbox, so most overpasses are
    NaN at any given pixel; we pick the overpass whose LST is finite over the
    largest fraction of the grid (preferring one that also has ET present) so the
    spot-check pixels actually carry LST/ET/ESI values. Falls back to overpass 0.
    """
    lst = ds["lst"]
    cov = np.isfinite(lst.values).reshape(lst.sizes["overpass"], -1).mean(axis=1)
    in_et = ds["in_et"].values if "in_et" in ds.coords else np.zeros(len(cov), bool)
    # Prefer high-coverage overpasses that also have ET; else just highest coverage.
    score = cov + 0.001 * in_et.astype(float)
    if np.nanmax(cov) <= 0:
        return 0
    return int(np.argmax(score))


def _report(results: dict) -> None:
    log.info("=" * 70)
    log.info("Section 9 complete. Deliverables (data/processed/):")
    for key in ("analysis_zarr", "overpass_table"):
        if key in results:
            log.info("  %-16s -> %s", key, Path(results[key]).name)
    if "figure" in results and results["figure"]:
        log.info("  figure           -> %s", Path(results["figure"]).name)
    log.info("=" * 70)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 9 - harmonize all layers onto the 70 m grid and "
                    "time-match to the ECOSTRESS overpasses (steps 47-51).")
    p.add_argument("--no-figures", action="store_true", help="skip the QA spot-check figure.")
    p.add_argument("--verify-only", action="store_true",
                   help="skip the build; re-open the saved cube and run verify + spot check.")
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
