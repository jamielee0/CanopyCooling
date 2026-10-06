#!/usr/bin/env python3
"""Section 9 / harmonize — bring all layers onto the common 70 m grid, time-matched to the ECOSTRESS overpasses (steps 47-51).

Inputs : data/interim/ ECOSTRESS cubes (LST/ET/ESI), ERA5-Land hourly tile,
         PRISM antecedent-precip/tmean + GRIDMET drought Zarrs, static 70 m
         tifs (NDVI/NDMI/impervious/canopy/income/%POC/SVI/landcover), and
         overpass_links.parquet.
Outputs: data/processed/analysis_cube_70m.zarr (overpass=66, y=1155, x=1339),
         data/processed/analysis_overpass_table.parquet (66 rows),
         figures/section9_alignment_spotcheck.png.
Key decisions (full rationale in docs/DESIGN_DECISIONS.md, Section 9):
  - 66 LST overpasses are the MASTER axis; ET/ESI/PET present on 45, NaN elsewhere.
  - All layers already on-grid except ERA5-Land; only it is resampled (bilinear).
  - Resampling follows data TYPE: continuous->bilinear, categorical->nearest.
  - Time match: ERA5=nearest hour, PRISM precip/tmean=exact date, drought=pentad
    whose 5-day window contains the date (NaN if none, e.g. earliest overpasses).
  - Gridded Zarr is the primary structure; the Parquet is a per-overpass scalar
    summary (no ~100 M-row per-pixel table until Section 10).
Run: python src/section9_harmonize.py [--no-figures] [--verify-only] [-v]
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
import plot_style as ps  # noqa: E402  (shared figure color convention)

log = logging.getLogger("section9")


# --- Source layers (all already on the 70 m grid except ERA5-Land) ---------- #
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

# Spot-check locations (step 51): (name, lon, lat, expectation). Phoenix landmarks
# whose lon/lat were verified to sit on the described feature (nudged off adjacent
# roads/shrub). Park = green AND canopy; interchange = bare/impervious; golf course
# = green turf but no tree canopy -- a deliberate three-way contrast.
SPOTCHECK_SITES = (
    ("Encanto Park (large urban park)", -112.090, 33.475,
     "high NDVI, real tree canopy, low impervious"),
    ("I-10/I-17 'Stack' interchange", -112.108, 33.471,
     "near-zero NDVI, ~100% impervious, no canopy"),
    ("Papago Golf Course (irrigated turf)", -111.959, 33.461,
     "very high NDVI, ~zero impervious, ~zero canopy (turf, not trees)"),
)


# --- Pure logic (numpy / pandas / str only; unit-tested without the geo stack) #
def overpass_key(orbit: str, scene: str, time: pd.Timestamp) -> str:
    """Compose the canonical overpass key ``{orbit}_{scene}_{YYYYMMDDTHHMMSS}``
    (the LST cube has no key coord, so it is reconstructed to align with ET/ESI)."""
    ts = pd.Timestamp(time)
    return f"{orbit}_{scene}_{ts.strftime('%Y%m%dT%H%M%S')}"


def parse_overpass_key(key: str) -> tuple[str, str, pd.Timestamp]:
    """Inverse of :func:`overpass_key`: ``key -> (orbit, scene, timestamp)``
    (split from the right; the timestamp is always the last underscore field)."""
    head, _, tstamp = key.rpartition("_")
    orbit, _, scene = head.partition("_")
    return orbit, scene, pd.Timestamp(_dt.datetime.strptime(tstamp, "%Y%m%dT%H%M%S"))


def resampling_for(layer_kind: str) -> "Resampling":
    """Route a layer KIND to its rasterio resampling method (step 48):
    continuous->bilinear, categorical/aggregated->nearest. Categorical MUST be
    nearest -- bilinear yields nonsense in-between classes (the Section 9 pitfall)."""
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
    """Latest pentad start P with ``P <= date < P + width_days`` (drought match, step 49),
    or None if no window contains the date -- None over a stale cross-season match."""
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
    """Per-overpass index (overpass_key, time, orbit, scene, era5_hour, precip_date)
    from the LST cube's orbit/scene/time coords -- the master axis, in input order."""
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


# --- Loading + alignment helpers (the geo stack) ---------------------------- #
def _reference():
    """The 70 m reference grid as a 2-D rioxarray DataArray (the match target/CRS)."""
    return rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)


def _assert_on_grid(da: "xr.DataArray", name: str, reference: "xr.DataArray") -> None:
    """Step 47: assert a layer is EPSG:32612 and snapped to the reference grid
    (CRS, cell size, origin, rows, cols), raising a precise message if anything is off."""
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
    """Load the static (y,x) layers, asserting each is already on-grid (step 47).

    Returns (continuous float32 arrays, categorical uint8 arrays). The land-cover
    layer keeps integer class codes (never floated -> no fractional classes).
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
    """Reconstruct each LST overpass's key from orbit/scene/time (the LST cube has
    no key coord); used to align ET/ESI by key onto the LST axis."""
    orbit = lst["orbit"].values
    scene = lst["scene"].values
    time = pd.to_datetime(lst["time"].values)
    return [overpass_key(str(o), str(s), t) for o, s, t in zip(orbit, scene, time)]


def align_paired_cube(cube: "xr.Dataset", var: str, master_keys: Sequence[str],
                      reference: "xr.DataArray") -> np.ndarray:
    """Place a 45-overpass ET/ESI variable onto the 66-overpass master axis by
    ``overpass_key`` (NaN where absent). Asserts on-grid; returns (66, y, x) float32."""
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
    """Bilinear-reproject ONE ERA5-Land 8x10 lat/lon slice onto the 70 m grid
    (CRS written first, since the .nc carries none). Continuous field -> bilinear."""
    src = slice2d.rio.write_crs(ERA5_CRS)
    matched = src.rio.reproject_match(reference, resampling=resampling_for("continuous"))
    return matched.values.astype("float32")


def exact_time_index(times: Sequence, when) -> int | None:
    """Return the unique position matching ``when``'s calendar date, else ``None``.

    PRISM is a daily product, so time-of-day components are normalized away.  Duplicate
    entries for the requested date are refused because silently choosing one would be as
    ambiguous as a nearest-date substitution.
    """
    available = pd.DatetimeIndex(pd.to_datetime(times)).normalize()
    target = pd.Timestamp(when).normalize()
    matches = np.flatnonzero(available == target)
    if matches.size > 1:
        raise ValueError(f"duplicate time entries for exact date {target.date()}")
    return None if matches.size == 0 else int(matches[0])


def select_by_time(cube: "xr.Dataset", var: str, when, reference: "xr.DataArray",
                   label: str) -> tuple[np.ndarray, bool]:
    """Select an exact PRISM date or return an all-NaN grid.

    Returns ``(values, found)``.  A missing date is never replaced by its nearest
    neighbour; the caller aggregates ``found`` into a visible missing-overpass count.
    Asserts that the source is already on the reference grid (step 47).
    """
    _assert_on_grid(cube[var], f"{label} cube", reference)
    pos = exact_time_index(cube["time"].values, when)
    if pos is None:
        shape = (int(reference.sizes["y"]), int(reference.sizes["x"]))
        return np.full(shape, np.nan, dtype="float32"), False
    sel = cube[var].isel(time=pos)
    return sel.values.astype("float32"), True


# --- Assembly (step 50) -> the gridded analysis Zarr ------------------------ #
def _blosc():
    import numcodecs
    return numcodecs.Blosc(cname="zstd", clevel=5, shuffle=numcodecs.Blosc.SHUFFLE)


def assemble_analysis_cube(interim: Path, reference: "xr.DataArray") -> xr.Dataset:
    """Build the (overpass, y, x) analysis cube holding every variable (step 50):
    time-varying vars time-matched to the 66 LST overpasses, static vars attached
    once. Carries the CRS via rio.write_crs + per-var grid_mapping for decode_coords."""
    ny, nx = reference.sizes["y"], reference.sizes["x"]

    # Master overpass axis: the 66 LST overpasses.
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

    # LST (master variable).
    data_vars["lst"] = (("overpass", "y", "x"), lst["lst"].values.astype("float32"))

    # ET / ESI / PET on the master axis (paired; NaN where absent).
    et = xr.open_zarr(interim / ET_CUBE, decode_coords="all")
    esi = xr.open_zarr(interim / ESI_CUBE, decode_coords="all")
    data_vars["et"] = (("overpass", "y", "x"), align_paired_cube(et, "et", master_keys, reference))
    data_vars["esi"] = (("overpass", "y", "x"), align_paired_cube(esi, "esi", master_keys, reference))
    data_vars["pet"] = (("overpass", "y", "x"), align_paired_cube(esi, "pet", master_keys, reference))

    # ERA5-Land VPD + SM at the matching HOUR (per-overpass single-slice bilinear).
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

    # PRISM antecedent precip + tmean at the matching DATE.
    ant = xr.open_zarr(interim / ANTECEDENT_ZARR, decode_coords="all")
    tm = xr.open_zarr(interim / TMEAN_ZARR, decode_coords="all")
    missing_ant: set[int] = set()
    for v in PRECIP_VARS:
        arr = np.full((n, ny, nx), np.nan, dtype="float32")
        for i, d in enumerate(idx["precip_date"]):
            selected, found = select_by_time(ant, v, d, reference, "antecedent")
            arr[i] = selected
            if not found:
                missing_ant.add(i)
        data_vars[v] = (("overpass", "y", "x"), arr)
    tmean_arr = np.full((n, ny, nx), np.nan, dtype="float32")
    missing_tmean: set[int] = set()
    for i, d in enumerate(idx["precip_date"]):
        selected, found = select_by_time(tm, "tmean", d, reference, "tmean")
        tmean_arr[i] = selected
        if not found:
            missing_tmean.add(i)
    data_vars["tmean"] = (("overpass", "y", "x"), tmean_arr)
    log.info("  PRISM   %s + tmean attached by exact DATE", ", ".join(PRECIP_VARS))
    missing_log = log.warning if (missing_ant or missing_tmean) else log.info
    missing_log("  PRISM   antecedent: %d/%d overpasses missing exact date -> NaN; "
                "tmean: %d/%d missing exact date -> NaN",
                len(missing_ant), n, len(missing_tmean), n)

    # GRIDMET drought at the matching PENTAD (window-contains; None -> NaN).
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

    # Static (y, x) layers, attached once.
    cont, cat = load_static_layers(reference, interim)
    for name, arr in cont.items():
        data_vars[name] = (("y", "x"), arr)
    for name, arr in cat.items():
        data_vars[name] = (("y", "x"), arr)

    # Coords + Dataset.
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
    # Pin CF grid_mapping in each spatial var's attrs so the CRS survives to_zarr
    # and reloads with decode_coords="all" (matches the Section 2/3/7 cubes).
    for v in ds.data_vars:
        if {"y", "x"} <= set(ds[v].dims):
            ds[v].attrs["grid_mapping"] = "spatial_ref"
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
    """Write the analysis cube to a compressed, chunked Zarr (step 50): time-varying
    vars as (1, y, x), static as one tile; object/datetime coords uncompressed.
    Overwrites any existing store."""
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
    """Write the small per-overpass metadata/scalar table (66 rows): keys, matched
    hour/date/pentad, in_et/in_esi, and regional (area-mean) driver values. NOT a
    per-pixel long table (deferred to Section 10, once analysis pixels are defined)."""
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


# --- Verification (step 47 re-open assertions + step 51 spot check) ---------- #
def verify_grid(store: Path, reference: "xr.DataArray") -> "xr.Dataset":
    """Re-open the saved cube and PRINT/ASSERT its geometry == reference_grid.tif
    (dims/CRS/pixel size/shape/origin), landcover_class is integer, continuous
    layers are float. Returns the reopened dataset for the spot check."""
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
    """Nearest grid (row, col) for a lon/lat point (reprojected to EPSG:32612), using
    the reference coord vectors so the pixel is the same cell every layer is on."""
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", config.CRS, always_xy=True)
    x, y = tr.transform(lon, lat)
    col = int(np.argmin(np.abs(reference.x.values - x)))
    row = int(np.argmin(np.abs(reference.y.values - y)))
    return row, col


def spot_check(ds: "xr.Dataset", reference: "xr.DataArray", overpass_i: int = 0
               ) -> list[dict]:
    """Step 51: PRINT every layer's value at each known landmark pixel (static layers
    + one representative overpass's time-varying layers) with the expectation, and
    return the rows."""
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
        smsg = []
        for v in static_vars:
            val = ds[v].isel(y=row, x=col).values
            val = val.item() if np.ndim(val) == 0 else val
            rec[v] = val
            smsg.append(f"{v}={_fmt(val)}")
        log.info("  static : %s", "  ".join(smsg))
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
    """QA figure: NDVI + impervious + a representative LST map with the 3 sites marked,
    confirming the spot-check pixels sit where expected and the layers co-register."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    left, bottom, right, top = config.GRID_BOUNDS
    extent = (left, right, bottom, top)
    panels = [("ndvi", "NDVI (warm-season median)", "YlGn", None, None),
              ("impervious", "Impervious surface (%)", ps.CMAP["impervious"], 0, 100),
              ("lst", f"LST (K), overpass {overpass_i}", ps.CMAP["temperature"], None, None)]
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


# --- Orchestration / CLI ---------------------------------------------------- #
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

    # Re-open from disk: verify (step 47), show a time match (step 49), spot-check (step 51).
    ds = verify_grid(store, reference)
    results["dims"] = dict(ds.sizes)
    results["variables"] = list(ds.data_vars)
    sample_overpass_time_match(ds, i=0)
    # Mid-season overpass for the spot check so ET/ESI are likely present.
    rep = _pick_paired_overpass(ds)
    rows = spot_check(ds, reference, overpass_i=rep)
    results["spotcheck"] = rows
    if make_figures:
        results["figure"] = make_spotcheck_figure(ds, reference, rows, config.FIGURES_DIR, rep)

    _report(results)
    return results


def _pick_paired_overpass(ds: "xr.Dataset") -> int:
    """A representative overpass for the spot check: the one with the best finite-LST
    spatial coverage (each ECOSTRESS scene covers only a sliver), preferring one that
    also has ET. Falls back to overpass 0."""
    lst = ds["lst"]
    cov = np.isfinite(lst.values).reshape(lst.sizes["overpass"], -1).mean(axis=1)
    in_et = ds["in_et"].values if "in_et" in ds.coords else np.zeros(len(cov), bool)
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
