#!/usr/bin/env python3
"""Section 4b - Time-resolved Sentinel-2 NDMI (per-overpass + LOYO day-of-year climatology).

WHY THIS SECTION EXISTS (the supply-axis fix)
---------------------------------------------
Section 4 originally produced only ONE NDMI image: a 2023 warm-season MEDIAN
composite (data/interim/s2_ndmi_warmseason_median_2023_70m.tif). Because that is
a single static field, Section 11's water-supply z-score could only be a SPATIAL
standardization -- a deviation that varies BY PIXEL but is CONSTANT across all 66
ECOSTRESS overpasses (decision (B) in section11_anomalies.py). With the supply
half of the Compound Stress Index frozen in time, the CSI collapses to (almost)
a pure temporal VPD-demand axis with little between-neighborhood variation -- the
deepest reason the Phoenix pilot found "no robust threshold" (Section 14).

The fix implemented here gives NDMI a REAL time dimension, exactly mirroring how
Section 11 already treats VPD and soil moisture:
  * ``observed``  -- for EACH 2023 overpass, a cloud-masked S2 NDMI MEDIAN composite
                     within +/- CLIMATOLOGY_WINDOW_DAYS (15) days of the overpass
                     date (in 2023). This VARIES overpass-to-overpass through the
                     season (greener around the monsoon), and across space.
  * ``clim_mean`` / ``clim_std`` -- the DAY-OF-YEAR climatology: for each overpass's
                     day-of-year, the mean and std of cloud-masked S2 NDMI over years
                     2018-2024 EXCLUDING the overpass's own year (LEAVE-ONE-YEAR-OUT;
                     every pilot overpass is 2023, so the climatology is over
                     2018-2022 + 2024), within +/- 15 days of that day-of-year.

Section 11 can then compute a proper TEMPORAL NDMI z-score
``z = (observed - clim_mean) / clim_std`` that varies overpass-to-overpass AND
across space, unfreezing the CSI supply axis. This product SUPERSEDES the single
static composite as the input to Section 11's NDMI z-score.

METHOD (mirrors Section 4 + Section 11)
---------------------------------------
* Source: COPERNICUS/S2_SR_HARMONIZED (same as Section 4). The harmonized
  collection puts the whole archive on one reflectance offset; since NDMI is a
  normalized difference, a consistent additive offset cancels -- so the 2018-2024
  archive is directly comparable without manual offset handling.
* Per scene: drop high-cloud SCENES (CLOUDY_PIXEL_PERCENTAGE < MAX_SCENE_CLOUD_PCT),
  mask cloud / cloud-shadow / snow PIXELS via the SCL band (drop classes {3,8,9,10,11}),
  then NDMI = (B8 - B11) / (B8 + B11). B11 (SWIR) is NATIVE 20 m, so NDMI is a 20 m
  product, reprojected to 70 m on the EE side (bilinear) like Section 4.
* observed: server-side ``median()`` over the per-overpass +/-15 d window in 2023.
* clim_mean / clim_std: server-side ``mean()`` / ``stdDev()`` over the union of the
  +/-15 d windows in each climatology year (2018-2022, 2024). EE compute is reduced
  by DEDUPING the climatology by UNIQUE day-of-year window: many overpasses fall on
  the same calendar day-of-year window, so the climatology is identical and computed
  once per unique window, then mapped back to all 66 overpasses.
* Each reduced 70 m image is downloaded with ``geemap.download_ee_image``
  (geedim under the hood; crs=EPSG:32612, scale=70, region=bbox), tiled+stitched
  under the EE size limit, with a smaller-tile retry ladder then an Export-to-Drive
  fallback -- identical machinery to Section 4. We download PER overpass (small 70 m
  images) rather than one giant cube to stay within EE compute limits.

DELIVERABLE (data/interim/; git-ignored)
-----------------------------------------
* ``s2_ndmi_timeseries_70m.zarr`` -- dims (overpass=66, y=1155, x=1339), vars
  ``observed`` / ``clim_mean`` / ``clim_std`` (NDMI, dimensionless), coords
  overpass / overpass_key / time / doy / y / x and a CF spatial_ref (reopen with
  ``decode_coords="all"``). Indexed by the SAME 66 overpass_keys, in the SAME order,
  as data/processed/analysis_cube_70m.zarr -- so Section 11 can drop it in.
  Recorded in data/manifest.csv with SHA-256 checksums (per per-overpass GeoTIFF).

Run (canopy env, Earth Engine authenticated):
    python src/section4b_ndmi_timeseries.py                 # full run (EE download)
    python src/section4b_ndmi_timeseries.py --overpass 10    # download only overpass 10 (test)
    python src/section4b_ndmi_timeseries.py --skip-download   # reuse data/raw/sentinel2_ndmi_ts/
    python src/section4b_ndmi_timeseries.py --coarse-scale 210 # quick smoke test (coarser grid)
    python src/section4b_ndmi_timeseries.py --verify-only      # re-open + QC the saved store
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import logging
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

# Heavy geospatial / EE libraries. The pure logic below (NDMI formula, SCL mask,
# the +/-15-day window selection, the LOYO year exclusion, the day-of-year dedup)
# does not touch them, so it stays unit-testable without the geo / EE stack
# installed (see test_section4b_ndmi_timeseries.py).
import ee  # noqa: E402
import geemap  # noqa: E402
import rioxarray  # noqa: F401,E402  (registers the .rio accessor)
import xarray as xr  # noqa: E402

# Make config + the Section 2/4 modules importable whether run from repo root or src/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
import config  # noqa: E402
import section2_ecostress_lst as sec2  # noqa: E402  (manifest/checksum helpers)
import section4_sentinel2_indices as sec4  # noqa: E402  (collection, SCL mask, download)

log = logging.getLogger("section4b")


# =========================================================================== #
# Constants (most inherited from Section 4 to keep the two consistent).
# --------------------------------------------------------------------------- #
COLLECTION_ID = sec4.COLLECTION_ID                # COPERNICUS/S2_SR_HARMONIZED
DATASET_ID = COLLECTION_ID
SCL_DROP_CLASSES = sec4.SCL_DROP_CLASSES          # (3, 8, 9, 10, 11)
MAX_SCENE_CLOUD_PCT = sec4.MAX_SCENE_CLOUD_PCT    # 60.0
MAX_TILE_SIZES_MB = sec4.MAX_TILE_SIZES_MB        # (8, 4, 2, 1) retry ladder
MAX_REQUESTS = sec4.MAX_REQUESTS                  # 8 (concurrency cap)

# NDMI band polarity (SWIR B11 is native 20 m -> NDMI is a 20 m product).
NDMI_BANDS = ("B8", "B11")
NDMI_NATIVE_SCALE_M = 20
NDMI_NAME = "ndmi"

WINDOW_DAYS = config.CLIMATOLOGY_WINDOW_DAYS      # 15 (the +/- day-of-year half-width)
CLIM_YEAR_LO, CLIM_YEAR_HI = config.CLIMATOLOGY_YEARS   # (2018, 2024) inclusive

ANALYSIS_CUBE = "analysis_cube_70m.zarr"          # Section 9 cube -> the 66-overpass axis
OLD_STATIC_NDMI_TIF = "s2_ndmi_warmseason_median_2023_70m.tif"  # the field this supersedes

RAW_SUBDIR = "sentinel2_ndmi_ts"                  # data/raw/sentinel2_ndmi_ts/
OUT_ZARR = "s2_ndmi_timeseries_70m.zarr"          # THE deliverable (data/interim/)
DRIVE_FOLDER = "canopy_section4b"                  # only used by the Export fallback

# How a per-overpass window with too few clear S2 pixels is flagged in the QC.
THIN_COVERAGE_FINITE_FRAC = 0.80                  # < this fraction finite -> "thin"


# =========================================================================== #
# Pure logic (numpy / pandas only; unit-tested without the geo or EE stack)
# =========================================================================== #
def ndmi_from_bands(b8: np.ndarray, b11: np.ndarray) -> np.ndarray:
    """NDMI = (B8 - B11) / (B8 + B11), NaN where the sum is zero (Section 4 formula).

    A reference implementation of the index EE computes server-side, so the polarity
    and the divide-by-zero guard are testable without Earth Engine. Reuses Section 4's
    ``normalized_difference`` so the two sections cannot drift apart.
    """
    return sec4.normalized_difference(b8, b11)


def date_window_bounds(center_date: pd.Timestamp,
                       window_days: int = WINDOW_DAYS) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Inclusive [start, end] calendar dates of the +/- ``window_days`` window.

    The OBSERVED composite for one overpass is the S2 NDMI median over the scenes
    whose acquisition date falls in [center - window, center + window] (the same
    +/-15 d half-width Section 11 uses for the VPD/SM day-of-year window, here as an
    ABSOLUTE calendar window within the overpass's own year). Returns midnight-floored
    Timestamps; the EE ``filterDate`` end is treated as EXCLUSIVE by the caller, so it
    adds one day to make ``end`` inclusive of the whole last day.
    """
    c = pd.Timestamp(center_date).normalize()
    return c - pd.Timedelta(days=int(window_days)), c + pd.Timedelta(days=int(window_days))


def doy_of(ts) -> int:
    """Day-of-year (1-366) of a timestamp."""
    return int(pd.Timestamp(ts).dayofyear)


def climatology_years(target_year: int,
                      year_lo: int = CLIM_YEAR_LO, year_hi: int = CLIM_YEAR_HI) -> list[int]:
    """Years entering one overpass's day-of-year climatology: [lo..hi] EXCLUDING
    ``target_year`` (LEAVE-ONE-YEAR-OUT, step 60).

    Every pilot overpass is 2023, so this returns [2018, 2019, 2020, 2021, 2022, 2024]
    -- the 2018-2024 inclusive span with 2023 (the observation's own year) dropped.
    Pure list logic so the LOYO exclusion is unit-tested without EE.
    """
    return [y for y in range(int(year_lo), int(year_hi) + 1) if y != int(target_year)]


def year_window_ranges(doy: int, years: Sequence[int],
                       window_days: int = WINDOW_DAYS,
                       ref_year: int = 2001) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """For a target day-of-year, the [start, end] calendar window in EACH given year.

    The day-of-year climatology samples S2 over |doy - D| <= window in every
    climatology year. We realise that as a UNION of per-year date windows: in each
    year Y, the window is centred on the calendar date that has day-of-year ``doy`` in
    Y, +/- ``window_days``. ``ref_year`` (any non-leap year) maps the day-of-year to a
    month/day; using the SAME month/day in each target year keeps the window on the
    right calendar position (and naturally clips at the season edges, exactly like
    Section 11's one-sided early-June / late-September windows). Returns inclusive
    [start, end] pairs (the caller makes the EE end exclusive by +1 day).
    """
    # Map day-of-year -> (month, day) via a fixed reference (non-leap) year.
    anchor = (pd.Timestamp(f"{int(ref_year)}-01-01") + pd.Timedelta(days=int(doy) - 1))
    month, day = anchor.month, anchor.day
    out: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for y in years:
        # Guard against day-of-year 366 / Feb-29 landing in a non-leap target year.
        try:
            center = pd.Timestamp(year=int(y), month=month, day=day)
        except ValueError:
            center = pd.Timestamp(year=int(y), month=month, day=day - 1)
        out.append((center - pd.Timedelta(days=int(window_days)),
                    center + pd.Timedelta(days=int(window_days))))
    return out


def dedup_climatology_windows(overpasses: pd.DataFrame,
                              window_days: int = WINDOW_DAYS
                              ) -> tuple[dict[int, list[int]], list[int]]:
    """Group overpasses by their day-of-year so identical climatologies compute ONCE.

    Many of the 66 overpasses share a calendar day-of-year (or are close enough that
    their +/-window day-of-year climatology is identical). The climatology depends ONLY
    on the day-of-year (and the fixed LOYO year set), so it is identical for all
    overpasses with the same day-of-year. We therefore key by day-of-year: returns
    ``(groups, unique_doys)`` where ``groups[doy]`` is the list of overpass row-indices
    sharing that day-of-year, and ``unique_doys`` is the sorted unique day-of-year list.
    The caller computes the climatology once per unique day-of-year and broadcasts it
    back to every overpass in the group -- cutting EE compute from 66 to len(unique).

    NB we dedup by EXACT day-of-year (not overlapping windows) so each overpass gets a
    climatology centred precisely on ITS day-of-year; this is exact, not approximate.
    """
    groups: dict[int, list[int]] = {}
    for i, (_, row) in enumerate(overpasses.iterrows()):
        d = doy_of(row["time"])
        groups.setdefault(d, []).append(i)
    return groups, sorted(groups)


# =========================================================================== #
# Earth Engine -- per-overpass reductions  (needs ee)
# =========================================================================== #
def _ndmi_image(image: "ee.Image") -> "ee.Image":
    """Per-scene NDMI = normalizedDifference(B8, B11), renamed to the index name."""
    return image.normalizedDifference(list(NDMI_BANDS)).rename(NDMI_NAME)


def _masked_ndmi_collection(region: "ee.Geometry", start: str, end: str,
                            max_scene_cloud_pct: float = MAX_SCENE_CLOUD_PCT
                            ) -> "ee.ImageCollection":
    """S2 SR (harmonized) over [start, end): scene-cloud filter, SCL-mask, per-scene NDMI.

    Mirrors Section 4's load_collection + index step but for an ARBITRARY date window
    (used both for the per-overpass observed window and for each climatology-year
    window). ``end`` is EXCLUSIVE (EE filterDate convention).
    """
    return (ee.ImageCollection(COLLECTION_ID)
            .filterBounds(region)
            .filterDate(start, end)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", float(max_scene_cloud_pct)))
            .map(sec4.mask_scl_ee)        # drop SCL {3,8,9,10,11} per Section 4
            .map(_ndmi_image)
            .select(NDMI_NAME))


def _date_str(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def observed_image(region: "ee.Geometry", center_date: pd.Timestamp,
                   window_days: int = WINDOW_DAYS) -> "ee.Image":
    """Per-overpass OBSERVED NDMI: median composite within +/-window of the overpass date.

    The window is in the overpass's OWN year (2023). ``median()`` is robust to residual
    cloud (matches Section 4's warm-season median). Returns a single-band EE image.
    """
    lo, hi = date_window_bounds(center_date, window_days)
    end_excl = hi + pd.Timedelta(days=1)          # make the last day inclusive
    coll = _masked_ndmi_collection(region, _date_str(lo), _date_str(end_excl))
    return coll.median().rename(NDMI_NAME)


def climatology_images(region: "ee.Geometry", doy: int, years: Sequence[int],
                       window_days: int = WINDOW_DAYS) -> tuple["ee.Image", "ee.Image"]:
    """Day-of-year LOYO climatology MEAN and STD images for one day-of-year.

    Unions the +/-window date windows across every climatology ``years`` entry, builds
    one masked-NDMI collection over that union, then reduces to ``mean()`` and
    ``stdDev()`` (population std, matching Section 11's np.nanstd). Returns
    ``(clim_mean_img, clim_std_img)`` as single-band EE images.
    """
    ranges = year_window_ranges(doy, years, window_days)
    coll = None
    for lo, hi in ranges:
        end_excl = hi + pd.Timedelta(days=1)
        c = _masked_ndmi_collection(region, _date_str(lo), _date_str(end_excl))
        coll = c if coll is None else coll.merge(c)
    mean_img = coll.mean().rename("clim_mean")
    std_img = coll.reduce(ee.Reducer.stdDev()).rename("clim_std")
    return mean_img, std_img


# =========================================================================== #
# Resilient download  (reuses Section 4's tiled geemap.download_ee_image ladder)
# =========================================================================== #
@dataclasses.dataclass
class TileResult:
    """Outcome of downloading one reduced 70 m image to a GeoTIFF (or Drive fallback)."""

    name: str                          # short id (e.g. "obs_op05" / "clim_mean_doy180")
    path: Path | None                  # local GeoTIFF, or None if it fell back to Drive
    method: str
    max_tile_size_mb: float | None = None
    drive_task_id: str | None = None

    @property
    def is_local(self) -> bool:
        return self.path is not None


def _export_to_drive(image: "ee.Image", name: str, region: "ee.Geometry",
                     scale_m: int) -> TileResult:
    """Last resort: start an Export.image.toDrive task and flag it for the user."""
    task = ee.batch.Export.image.toDrive(
        image=image, description=name, folder=DRIVE_FOLDER, fileNamePrefix=name,
        region=region, crs=config.CRS, scale=scale_m, maxPixels=int(1e13),
        fileFormat="GeoTIFF")
    task.start()
    log.error("Drive FALLBACK for %s: started Export.image.toDrive task id=%s "
              "(folder=%s, file=%s.tif)", name, task.id, DRIVE_FOLDER, name)
    return TileResult(name=name, path=None, method="Export.image.toDrive",
                      drive_task_id=task.id)


def download_image(image: "ee.Image", name: str, region: "ee.Geometry", raw_dir: Path,
                   scale_m: int, tile_sizes_mb: Sequence[float] = MAX_TILE_SIZES_MB,
                   overwrite: bool = True) -> TileResult:
    """Download one reduced image to ``raw_dir/<name>.tif`` in EPSG:32612 at ``scale_m``.

    Tiles+stitches via geemap.download_ee_image (geedim); on a compute/size failure
    retries with a smaller per-tile size, then falls back to Export.image.toDrive --
    the exact resilient pattern Section 4 uses. If the file already exists and
    ``overwrite`` is False, reuses it (the --skip-download path).
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / f"{name}.tif"
    # Real 70 m composites are ~7 MB; anything tiny is a truncated/corrupt stub left by
    # an interrupted run (e.g. a power-off mid-download) -- treat it as missing and refetch.
    _MIN_VALID_BYTES = 100_000
    if not overwrite and out_path.exists():
        if out_path.stat().st_size >= _MIN_VALID_BYTES:
            log.info("  reuse %s (%.2f MB on disk)", out_path.name,
                     out_path.stat().st_size / 1e6)
            return TileResult(name=name, path=out_path, method="(reused local file)")
        log.warning("  refetch %s (on-disk %d bytes < %d -> corrupt/truncated)",
                    out_path.name, out_path.stat().st_size, _MIN_VALID_BYTES)

    last_exc: Exception | None = None
    for mts in tile_sizes_mb:
        try:
            geemap.download_ee_image(
                image, str(out_path), region=region, crs=config.CRS, scale=scale_m,
                resampling="bilinear",        # continuous index; bilinear on EE reproject
                overwrite=True, max_tile_size=mts,
                num_threads=MAX_REQUESTS, max_requests=MAX_REQUESTS)
            log.info("  downloaded %s (%.2f MB) at max_tile_size=%sMB",
                     out_path.name, out_path.stat().st_size / 1e6, mts)
            return TileResult(name=name, path=out_path,
                              method="geemap.download_ee_image", max_tile_size_mb=mts)
        except Exception as exc:  # noqa: BLE001 - retry smaller, then Drive
            last_exc = exc
            log.warning("  download %s failed at max_tile_size=%sMB: %s: %s -- "
                        "retrying smaller", name, mts, type(exc).__name__, exc)
    log.error("  all tiled attempts for %s failed (last: %s: %s).",
              name, type(last_exc).__name__, last_exc)
    return _export_to_drive(image, name, region, scale_m)


# =========================================================================== #
# Loading helpers (the geo stack)
# =========================================================================== #
def _reference() -> "xr.DataArray":
    """The 70 m reference grid as a 2-D rioxarray DataArray (the match target / CRS)."""
    return rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)


def load_overpass_axis(processed: Path) -> pd.DataFrame:
    """The 66-overpass master axis (overpass, key, time) from the Section 9 cube.

    The Section 9 analysis cube is the authoritative overpass axis used everywhere
    downstream, so we reuse its order verbatim -- the time series shares the exact
    overpass index Section 11 expects. Returns columns overpass / overpass_key / time.
    """
    cube = xr.open_zarr(processed / ANALYSIS_CUBE, decode_coords="all")
    df = pd.DataFrame({
        "overpass": np.asarray(cube["overpass"].values, dtype="int32"),
        "overpass_key": np.array([str(k) for k in cube["overpass_key"].values], dtype=object),
        "time": pd.to_datetime(cube["time"].values),
    })
    cube.close()
    return df


def _read_grid_array(path: Path, reference: "xr.DataArray") -> np.ndarray:
    """Open a downloaded GeoTIFF, reproject_match to the reference grid, return float32.

    geemap already wrote EPSG:32612 at the requested scale, but a tiny origin/extent
    mismatch (sub-pixel) can occur; reproject_match snaps it EXACTLY onto
    reference_grid.tif (bilinear, the continuous-field rule) so every band lands on the
    identical 66 x 1155 x 1339 grid as the other cubes. NaN where masked/no-data.
    """
    from rasterio.enums import Resampling
    da = rioxarray.open_rasterio(path, masked=True).squeeze("band", drop=True)
    matched = da.rio.reproject_match(reference, resampling=Resampling.bilinear)
    return matched.values.astype("float32")


# =========================================================================== #
# Assembly -> the NDMI time-series Zarr
# =========================================================================== #
def _blosc():
    import numcodecs
    return numcodecs.Blosc(cname="zstd", clevel=5, shuffle=numcodecs.Blosc.SHUFFLE)


def assemble_dataset(observed: np.ndarray, clim_mean: np.ndarray, clim_std: np.ndarray,
                     overpasses: pd.DataFrame, reference: "xr.DataArray") -> "xr.Dataset":
    """Build the (overpass, y, x) NDMI time-series dataset with CF coords + provenance."""
    coords = {
        "overpass": overpasses["overpass"].to_numpy(),
        "overpass_key": ("overpass", overpasses["overpass_key"].to_numpy()),
        "time": ("overpass", overpasses["time"].to_numpy()),
        "doy": ("overpass", np.array([doy_of(t) for t in overpasses["time"]], dtype="int32")),
        "y": reference.y.values,
        "x": reference.x.values,
    }
    ds = xr.Dataset(
        {
            "observed": (("overpass", "y", "x"), observed),
            "clim_mean": (("overpass", "y", "x"), clim_mean),
            "clim_std": (("overpass", "y", "x"), clim_std),
        },
        coords=coords,
    )
    ds = ds.rio.write_crs(reference.rio.crs)
    for v in ds.data_vars:
        ds[v].attrs["grid_mapping"] = "spatial_ref"
        ds[v].attrs["units"] = "1"                # NDMI is dimensionless
    ds["observed"].attrs["long_name"] = (
        "Per-overpass observed Sentinel-2 NDMI: cloud-masked S2 median composite within "
        f"+/-{WINDOW_DAYS} d of the overpass date (2023). Time-varying (vs the old single "
        "static warm-season median).")
    ds["clim_mean"].attrs["long_name"] = (
        f"Day-of-year NDMI climatological mean: cloud-masked S2 NDMI over years "
        f"{CLIM_YEAR_LO}-{CLIM_YEAR_HI} EXCLUDING the overpass year (leave-one-year-out), "
        f"within +/-{WINDOW_DAYS} d of the overpass day-of-year.")
    ds["clim_std"].attrs["long_name"] = (
        "Day-of-year NDMI climatological standard deviation over the same LOYO window.")
    ds.attrs["title"] = ("Section 4b: time-resolved Sentinel-2 NDMI (per-overpass observed "
                         "+ 2018-2024 leave-one-year-out day-of-year climatology) on the 70 m grid")
    ds.attrs["crs"] = config.CRS
    ds.attrs["collection"] = COLLECTION_ID
    ds.attrs["climatology_years"] = list(config.CLIMATOLOGY_YEARS)
    ds.attrs["climatology_window_days"] = WINDOW_DAYS
    ds.attrs["scene_cloud_pct_max"] = MAX_SCENE_CLOUD_PCT
    ds.attrs["scl_drop_classes"] = list(SCL_DROP_CLASSES)
    ds.attrs["ndmi_bands"] = list(NDMI_BANDS)
    ds.attrs["native_scale_m"] = NDMI_NATIVE_SCALE_M
    ds.attrs["supersedes"] = (
        f"data/interim/{OLD_STATIC_NDMI_TIF} (the single static 2023 warm-season median) "
        "as the input to Section 11's NDMI water-supply z-score: this product unfreezes the "
        "CSI supply axis by giving NDMI a real time dimension.")
    ds.attrs["method_observed"] = (
        f"per-overpass S2 NDMI median over [date+/-{WINDOW_DAYS} d] in the overpass year (2023)")
    ds.attrs["method_climatology"] = (
        f"day-of-year LOYO climatology: mean/stdDev of S2 NDMI over the union of +/-{WINDOW_DAYS} d "
        f"windows in years {CLIM_YEAR_LO}-{CLIM_YEAR_HI} excluding the overpass year; "
        "deduped by unique day-of-year (identical climatology computed once per day-of-year)")
    return ds


def write_zarr(ds: "xr.Dataset", store: Path) -> Path:
    """Write the cube to a compressed, chunked Zarr (one overpass per chunk). Overwrites."""
    if store.exists():
        import shutil
        shutil.rmtree(store)
    ny, nx = ds.sizes["y"], ds.sizes["x"]
    comp = _blosc()
    enc = {v: {"compressor": comp, "chunks": (1, ny, nx)} for v in ds.data_vars}
    store.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(store, mode="w", encoding=enc, consolidated=True)
    log.info("Wrote NDMI time-series cube -> %s", store)
    log.info("  dims=%s  vars=%s", dict(ds.sizes), list(ds.data_vars))
    return store


# =========================================================================== #
# Manifest
# =========================================================================== #
def record_in_manifest(tiles: Sequence[TileResult], project: str) -> None:
    """Append each downloaded per-overpass / per-day-of-year GeoTIFF to the manifest."""
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    rows = []
    for t in tiles:
        if not t.is_local or t.method == "(reused local file)":
            continue
        rows.append({
            "source": (f"Google Earth Engine {COLLECTION_ID} (project={project}; "
                       f"time-resolved NDMI Section 4b; {NDMI_NATIVE_SCALE_M} m native; "
                       f"EPSG:32612; geemap.download_ee_image; {t.name})"),
            "dataset": DATASET_ID,
            "filename": t.path.name,
            "download_date": today,
            "checksum": f"sha256:{sec2.sha256_file(t.path)}",
        })
    if rows:
        sec2.append_to_manifest(rows)
        log.info("Recorded %d Section 4b GeoTIFFs in the manifest.", len(rows))


# =========================================================================== #
# Download orchestration (EE)
# =========================================================================== #
def download_all(overpasses: pd.DataFrame, region: "ee.Geometry", raw_dir: Path,
                 scale_m: int, overwrite: bool,
                 only_overpass: int | None = None) -> list[TileResult]:
    """Download per-overpass observed + (deduped) day-of-year climatology mean/std.

    Returns ALL TileResults (observed + the unique-day-of-year clim mean/std), so the
    manifest records every downloaded GeoTIFF. The per-day-of-year clim tiles are named
    by day-of-year so the dedup is visible on disk and reusable across overpasses.
    """
    n = len(overpasses)
    groups, unique_doys = dedup_climatology_windows(overpasses)
    log.info("Climatology dedup: %d overpasses -> %d UNIQUE day-of-year windows "
             "(%.1fx fewer climatology reductions)", n, len(unique_doys),
             n / max(1, len(unique_doys)))

    tiles: list[TileResult] = []

    # --- per-overpass OBSERVED median composites (in 2023) -------------------- #
    op_iter = range(n) if only_overpass is None else [only_overpass]
    for i in op_iter:
        row = overpasses.iloc[i]
        lo, hi = date_window_bounds(row["time"])
        log.info("[observed %2d/%d] op=%d key=%s date=%s window=[%s..%s]",
                 i + 1 if only_overpass is None else i, n, int(row["overpass"]),
                 row["overpass_key"], _date_str(row["time"]), _date_str(lo), _date_str(hi))
        img = observed_image(region, row["time"])
        tiles.append(download_image(img, f"obs_op{i:02d}", region, raw_dir, scale_m,
                                    overwrite=overwrite))

    # --- deduped day-of-year CLIMATOLOGY mean/std (LOYO) ---------------------- #
    # When testing a single overpass, only fetch that overpass's day-of-year climatology.
    doys_to_do = unique_doys
    if only_overpass is not None:
        doys_to_do = [doy_of(overpasses.iloc[only_overpass]["time"])]
    for k, d in enumerate(doys_to_do):
        yrs = climatology_years(2023)             # all pilot overpasses are 2023 -> LOYO drops 2023
        log.info("[clim %2d/%d] doy=%d  LOYO years=%s  (serves %d overpass(es))",
                 k + 1, len(doys_to_do), d, yrs, len(groups.get(d, [])))
        mean_img, std_img = climatology_images(region, d, yrs)
        tiles.append(download_image(mean_img, f"clim_mean_doy{d:03d}", region, raw_dir,
                                    scale_m, overwrite=overwrite))
        tiles.append(download_image(std_img, f"clim_std_doy{d:03d}", region, raw_dir,
                                    scale_m, overwrite=overwrite))
    return tiles


def assemble_from_disk(overpasses: pd.DataFrame, raw_dir: Path,
                       reference: "xr.DataArray") -> "xr.Dataset":
    """Read the downloaded per-overpass / per-day-of-year GeoTIFFs into the (66,y,x) cube.

    The climatology was deduped by day-of-year on download, so here we MAP each
    day-of-year tile back to EVERY overpass sharing that day-of-year -- the documented
    dedup round-trip. Missing tiles (e.g. a Drive fallback not yet retrieved) leave that
    overpass's slice NaN and are reported by the caller.
    """
    n = len(overpasses)
    ny, nx = reference.sizes["y"], reference.sizes["x"]
    observed = np.full((n, ny, nx), np.nan, dtype="float32")
    clim_mean = np.full((n, ny, nx), np.nan, dtype="float32")
    clim_std = np.full((n, ny, nx), np.nan, dtype="float32")

    # Cache per-day-of-year clim arrays so each unique tile is read from disk once.
    cm_cache: dict[int, np.ndarray] = {}
    cs_cache: dict[int, np.ndarray] = {}
    missing: list[str] = []

    for i in range(n):
        d = doy_of(overpasses.iloc[i]["time"])
        obs_p = raw_dir / f"obs_op{i:02d}.tif"
        if obs_p.exists():
            observed[i] = _read_grid_array(obs_p, reference)
        else:
            missing.append(obs_p.name)

        if d not in cm_cache:
            cm_p = raw_dir / f"clim_mean_doy{d:03d}.tif"
            cs_p = raw_dir / f"clim_std_doy{d:03d}.tif"
            cm_cache[d] = _read_grid_array(cm_p, reference) if cm_p.exists() else None
            cs_cache[d] = _read_grid_array(cs_p, reference) if cs_p.exists() else None
            if cm_cache[d] is None:
                missing.append(cm_p.name)
            if cs_cache[d] is None:
                missing.append(cs_p.name)
        if cm_cache[d] is not None:
            clim_mean[i] = cm_cache[d]
        if cs_cache[d] is not None:
            clim_std[i] = cs_cache[d]

    if missing:
        log.warning("assemble_from_disk: %d expected GeoTIFF(s) missing -> those slices "
                    "stay NaN: %s", len(missing), sorted(set(missing))[:8])
    return assemble_dataset(observed, clim_mean, clim_std, overpasses, reference)


# =========================================================================== #
# QC (Section 2 of the brief)
# =========================================================================== #
def _assert_on_grid(ds: "xr.Dataset", reference: "xr.DataArray") -> None:
    """Assert the saved cube is EPSG:32612 and snapped EXACTLY to reference_grid.tif."""
    crs = ds.rio.crs
    assert crs is not None and crs.to_epsg() == reference.rio.crs.to_epsg(), \
        f"CRS {crs} != reference {reference.rio.crs}"
    assert ds.sizes["y"] == reference.sizes["y"] and ds.sizes["x"] == reference.sizes["x"], \
        "shape mismatch vs reference"
    assert ds.sizes["overpass"] == 66, f"expected 66 overpasses, got {ds.sizes['overpass']}"
    rtx = reference.rio.transform(); tx = ds.rio.transform()
    assert np.allclose([tx.a, tx.e, tx.c, tx.f], [rtx.a, rtx.e, rtx.c, rtx.f], atol=1e-6), \
        "transform (pixel size / origin) mismatch vs reference"
    assert np.allclose(ds.x.values, reference.x.values, atol=1e-6), "x mismatch"
    assert np.allclose(ds.y.values, reference.y.values, atol=1e-6), "y mismatch"


def run_qc(store: Path, reference: "xr.DataArray", interim: Path) -> dict:
    """Re-open the saved store and run + PRINT every QC check from the brief (Section 2)."""
    ds = xr.open_zarr(store, decode_coords="all")
    log.info("=" * 72)
    log.info("VERIFY + QC: %s", store.name)
    log.info("  dims=%s  vars=%s", dict(ds.sizes), list(ds.data_vars))
    log.info("  CRS=%s  transform=%s", ds.rio.crs, tuple(ds.rio.transform()))
    _assert_on_grid(ds, reference)
    log.info("  ASSERTIONS PASSED: geometry == reference_grid.tif; 66 overpasses.")

    out: dict = {}

    # (a) finite fractions per var.
    log.info("-" * 72)
    log.info("QC(a): finite fraction per variable")
    for v in ("observed", "clim_mean", "clim_std"):
        arr = ds[v].values
        frac = float(np.isfinite(arr).mean())
        out.setdefault("finite_frac", {})[v] = frac
        log.info("  %-10s finite=%.4f", v, frac)

    # (b) observed VARIES across overpasses (the whole point).
    log.info("-" * 72)
    log.info("QC(b): per-overpass spatial-mean NDMI for OBSERVED (must VARY through the "
             "season -- vs the old single static composite)")
    times = pd.to_datetime(ds["time"].values)
    keys = [str(k) for k in ds["overpass_key"].values]
    obs_means = ds["observed"].mean(dim=("y", "x"), skipna=True).values
    cm_means = ds["clim_mean"].mean(dim=("y", "x"), skipna=True).values
    per_op = pd.DataFrame({"overpass_key": keys, "date": [t.date() for t in times],
                           "doy": [doy_of(t) for t in times],
                           "observed_mean": obs_means, "clim_mean_mean": cm_means})
    out["per_overpass"] = per_op
    # show a spread of dates through the season
    show_idx = np.linspace(0, len(per_op) - 1, min(12, len(per_op))).astype(int)
    for j in show_idx:
        r = per_op.iloc[j]
        log.info("  %s (doy %3d)  observed_mean=%+.4f  clim_mean_mean=%+.4f",
                 r["date"], int(r["doy"]), r["observed_mean"], r["clim_mean_mean"])
    obs_spread = float(np.nanmax(obs_means) - np.nanmin(obs_means))
    obs_std_across = float(np.nanstd(obs_means))
    out["observed_spatialmean_spread"] = obs_spread
    out["observed_spatialmean_std_across_overpasses"] = obs_std_across
    log.info("  OBSERVED spatial-mean across overpasses: min=%+.4f max=%+.4f spread=%.4f "
             "std=%.4f", float(np.nanmin(obs_means)), float(np.nanmax(obs_means)),
             obs_spread, obs_std_across)
    log.info("  -> observed %s vary across overpasses (spread %.4f; the old static "
             "composite had ZERO temporal variation).",
             "DOES" if obs_spread > 1e-3 else "DOES NOT", obs_spread)

    # (c) NDMI range in [-1, 1]; min/median/max for observed + clim_mean.
    log.info("-" * 72)
    log.info("QC(c): NDMI range (must be within [-1, 1])")
    for v in ("observed", "clim_mean", "clim_std"):
        arr = ds[v].values
        mn, md, mx = (float(np.nanmin(arr)), float(np.nanmedian(arr)), float(np.nanmax(arr)))
        out.setdefault("range", {})[v] = (mn, md, mx)
        log.info("  %-10s min=%+.4f  median=%+.4f  max=%+.4f", v, mn, md, mx)
    obs = ds["observed"].values; cm = ds["clim_mean"].values
    in_range = (np.nanmin(obs) >= -1.0 - 1e-6 and np.nanmax(obs) <= 1.0 + 1e-6
                and np.nanmin(cm) >= -1.0 - 1e-6 and np.nanmax(cm) <= 1.0 + 1e-6)
    out["in_range"] = bool(in_range)
    log.info("  observed & clim_mean within [-1, 1]: %s", in_range)

    # (d) spot-check: green (golf/park) vs built/bare pixel.
    log.info("-" * 72)
    log.info("QC(d): spot-check observed NDMI at known green vs built/bare locations "
             "(season-median per pixel; green should be HIGHER / wetter)")
    out["spot"] = _spot_check(ds)

    # (e) agreement with the OLD static composite (season-aggregate of new observed).
    log.info("-" * 72)
    log.info("QC(e): agreement of the NEW observed season-aggregate vs the OLD static "
             "warm-season median composite")
    out["agreement"] = _agreement_with_old(ds, interim, reference)

    # (f) coverage / thin-window report.
    log.info("-" * 72)
    log.info("QC(f): per-overpass observed coverage (windows with thin clear-S2 coverage)")
    cov = ds["observed"].notnull().mean(dim=("y", "x")).values
    per_op["observed_finite_frac"] = cov
    thin = per_op[per_op["observed_finite_frac"] < THIN_COVERAGE_FINITE_FRAC]
    out["n_thin"] = int(len(thin))
    log.info("  overpasses with observed finite-fraction < %.2f: %d",
             THIN_COVERAGE_FINITE_FRAC, len(thin))
    for _, r in thin.iterrows():
        log.info("    %s (doy %3d) finite=%.3f", r["date"], int(r["doy"]),
                 r["observed_finite_frac"])
    log.info("  min observed finite-fraction over all overpasses = %.3f", float(np.nanmin(cov)))

    ds.close()
    return out


def _spot_check(ds: "xr.Dataset") -> pd.DataFrame:
    """Per-pixel season-median observed NDMI at known green vs built/bare points."""
    from pyproj import Transformer
    # Green / irrigated anchors (reuse Section 4's confirmed landmarks) + built/bare.
    green = sec4.KNOWN_GREEN_LANDMARKS[:3]
    built_bare = [
        ("Sky Harbor runways (built/paved)", -112.0117, 33.4342),
        ("Downtown Phoenix core (built)", -112.0740, 33.4500),
        ("North desert preserve (bare desert)", -112.0700, 33.7400),
    ]
    tf = Transformer.from_crs("EPSG:4326", config.CRS, always_xy=True)
    season_med = ds["observed"].median(dim="overpass", skipna=True)
    xs = ds.x.values; ys = ds.y.values
    rows = []
    for label, lon, lat in [("GREEN " + n, lo, la) for n, lo, la in green] + \
                           [("BUILT/BARE " + n, lo, la) for n, lo, la in built_bare]:
        x, y = tf.transform(lon, lat)
        if not (xs.min() <= x <= xs.max() and ys.min() <= y <= ys.max()):
            continue
        xi = int(np.argmin(np.abs(xs - x))); yi = int(np.argmin(np.abs(ys - y)))
        val = float(season_med.isel(y=yi, x=xi).values)
        rows.append({"location": label, "season_median_ndmi": val})
        log.info("  %-44s NDMI=%+.4f", label, val)
    df = pd.DataFrame(rows)
    if not df.empty:
        g = df[df["location"].str.startswith("GREEN")]["season_median_ndmi"].mean()
        b = df[df["location"].str.startswith("BUILT")]["season_median_ndmi"].mean()
        log.info("  mean GREEN NDMI=%+.4f  vs mean BUILT/BARE NDMI=%+.4f  -> green %s "
                 "wetter", g, b, "IS" if g > b else "is NOT")
    return df


def _agreement_with_old(ds: "xr.Dataset", interim: Path, reference: "xr.DataArray") -> dict:
    """Correlate the NEW observed SEASON-MEDIAN against the OLD static composite.

    The new per-overpass observed, aggregated over time (per-pixel season median),
    should reproduce the OLD single warm-season median's spatial pattern (the new one
    just RESOLVES the time the old one collapsed). High spatial correlation = consistent.
    """
    old_p = interim / OLD_STATIC_NDMI_TIF
    if not old_p.exists():
        log.warning("  old static composite %s not found -> skipping agreement check", old_p)
        return {}
    old = _read_grid_array(old_p, reference)
    new_season = ds["observed"].median(dim="overpass", skipna=True).values.astype("float64")
    both = np.isfinite(old) & np.isfinite(new_season)
    n = int(both.sum())
    a = old[both].astype("float64"); b = new_season[both]
    r = float(np.corrcoef(a, b)[0, 1]) if n > 2 else float("nan")
    bias = float(np.mean(b - a))
    mae = float(np.mean(np.abs(b - a)))
    log.info("  n_common=%d  Pearson r=%.4f  mean(new-old)=%+.4f  MAE=%.4f",
             n, r, bias, mae)
    log.info("  -> the new observed season-aggregate %s the old static composite's "
             "spatial pattern.", "MATCHES" if r > 0.8 else "is broadly consistent with")
    return {"n_common": n, "pearson_r": r, "bias_new_minus_old": bias, "mae": mae}


# =========================================================================== #
# Orchestration / CLI
# =========================================================================== #
def run(skip_download: bool = False, coarse_scale: int | None = None,
        only_overpass: int | None = None, verify_only: bool = False) -> dict:
    config.ensure_dirs()
    interim = config.INTERIM_DIR
    processed = config.PROCESSED_DIR
    raw_dir = config.RAW_DIR / RAW_SUBDIR
    store = interim / OUT_ZARR
    reference = _reference()
    overpasses = load_overpass_axis(processed)
    log.info("Overpass axis: %d ECOSTRESS overpasses (years %s); window=+/-%dd; "
             "climatology years %s LOYO (drops the overpass year)", len(overpasses),
             sorted({t.year for t in overpasses["time"]}), WINDOW_DAYS,
             list(config.CLIMATOLOGY_YEARS))

    results: dict = {"store": store}
    scale_m = coarse_scale or config.CELL_SIZE_M

    if verify_only:
        results["qc"] = run_qc(store, reference, interim)
        _report(results, only_overpass, coarse_scale)
        return results

    project = "default"
    if not skip_download:
        project = sec4.initialize_ee()
        region = sec4.study_region()
        # overwrite=False -> RESUME: reuse valid on-disk tiles, refetch only missing or
        # corrupt ones. This expensive ~170-tile EE pull is interruption-safe (a power-off
        # or killed run just continues). Delete a tile (or data/raw/sentinel2_ndmi_ts/) to
        # force a fresh fetch; --skip-download skips the download phase entirely.
        tiles = download_all(overpasses, region, raw_dir, scale_m,
                             overwrite=False, only_overpass=only_overpass)
        # A coarse-scale smoke test or a single --overpass run is not the full native
        # product, so it exercises the wiring but is kept OUT of the manifest.
        if coarse_scale is None and only_overpass is None:
            record_in_manifest(tiles, project)
        results["tiles"] = tiles
        drive = [t for t in tiles if not t.is_local]
        if drive:
            log.error("=" * 72)
            log.error("MANUAL STEP: %d tile(s) fell back to Google Drive (folder '%s'). "
                      "Grab them, drop into %s, then re-run with --skip-download:",
                      len(drive), DRIVE_FOLDER, raw_dir)
            for t in drive:
                log.error("  * %s.tif (task id=%s)", t.name, t.drive_task_id)
            results["drive_fallback"] = drive
            _report(results, only_overpass, coarse_scale)
            return results

    if only_overpass is not None:
        log.info("--overpass %d: downloaded that overpass's tiles only; skipping the "
                 "full-cube assembly (use a full run to build the Zarr).", only_overpass)
        results["single_overpass"] = only_overpass
        _report(results, only_overpass, coarse_scale)
        return results

    ds = assemble_from_disk(overpasses, raw_dir, reference)
    write_zarr(ds, store)
    ds.close()
    results["qc"] = run_qc(store, reference, interim)
    _report(results, only_overpass, coarse_scale)
    return results


def _report(results: dict, only_overpass: int | None, coarse_scale: int | None) -> None:
    log.info("=" * 72)
    if only_overpass is not None:
        log.info("Section 4b single-overpass test complete (overpass %d).", only_overpass)
    elif coarse_scale is not None:
        log.info("Section 4b smoke test complete (coarse scale %d m; not the native "
                 "product, not in the manifest).", coarse_scale)
    else:
        log.info("Section 4b complete. Deliverable: data/interim/%s", OUT_ZARR)
    if "qc" in results and results["qc"]:
        qc = results["qc"]
        if "observed_spatialmean_spread" in qc:
            log.info("  OBSERVED spatial-mean spread across overpasses = %.4f (the supply "
                     "axis is now TIME-VARYING).", qc["observed_spatialmean_spread"])
        if qc.get("agreement"):
            log.info("  agreement with old static composite: Pearson r=%.4f",
                     qc["agreement"].get("pearson_r", float("nan")))
    log.info("=" * 72)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 4b - time-resolved Sentinel-2 NDMI (per-overpass observed + "
                    "2018-2024 leave-one-year-out day-of-year climatology) to unfreeze "
                    "the CSI water-supply axis.")
    p.add_argument("--skip-download", action="store_true",
                   help="reuse the per-overpass / per-day-of-year GeoTIFFs already in "
                        "data/raw/sentinel2_ndmi_ts/ (assemble + QC only).")
    p.add_argument("--overpass", type=int, default=None,
                   help="(test) download ONLY this overpass index (0-based) + its day-of-year "
                        "climatology; skip the full-cube assembly.")
    p.add_argument("--coarse-scale", type=int, default=None,
                   help="(smoke test) override download scale in metres for speed.")
    p.add_argument("--verify-only", action="store_true",
                   help="skip the download/build; re-open the saved Zarr and run QC.")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    run(skip_download=args.skip_download, coarse_scale=args.coarse_scale,
        only_overpass=args.overpass, verify_only=args.verify_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
