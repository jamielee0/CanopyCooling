#!/usr/bin/env python3
"""Section 4b — time-resolved Sentinel-2 NDMI (per-overpass observed + LOYO day-of-year climatology).

Inputs : data/processed/analysis_cube_70m.zarr (the 66-overpass master axis),
         COPERNICUS/S2_SR_HARMONIZED (Earth Engine), config.REFERENCE_GRID_TIF.
Outputs: data/interim/s2_ndmi_timeseries_70m.zarr (overpass=66, y=1155, x=1339;
         vars observed/clim_mean/clim_std plus observed/climatology valid counts and
         separate count<3 flags), per-tile GeoTIFFs in
         data/raw/sentinel2_ndmi_ts/, manifest rows with SHA-256 checksums.
Key decisions (full rationale in docs/DESIGN_DECISIONS.md, Section 4b):
  - Gives the Section 11 NDMI vegetation-condition check a real time dimension; NDMI is not
    the primary water-supply axis (root-zone soil moisture is).
  - observed = per-overpass cloud-masked S2 median within +/-15 d (2023).
  - clim_mean/std = day-of-year leave-one-year-out climatology over 2018-2024 (drops 2023).
  - Scene cloud <60% is a broad prefilter; per-pixel SCL masking is primary.
  - Post-SCL counts use nearest-neighbour resampling; count<3 is flagged, never masked.
  - Climatology deduped by unique day-of-year (computed once, mapped to all overpasses).
  - Supersedes the single static s2_ndmi_warmseason_median_2023_70m.tif.
Run:
    python src/section4b_ndmi_timeseries.py                 # full run (EE download)
    python src/section4b_ndmi_timeseries.py --overpass 10    # download only overpass 10 (test)
    python src/section4b_ndmi_timeseries.py --skip-download   # reuse data/raw/sentinel2_ndmi_ts/
    python src/section4b_ndmi_timeseries.py --coarse-scale 210 # quick smoke test (coarser grid)
    python src/section4b_ndmi_timeseries.py --counts-only       # resumable count-only pull
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

# Heavy geospatial / EE libs; the pure logic below stays importable without them.
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


# --- Constants (most inherited from Section 4 to keep the two consistent) ---
COLLECTION_ID = sec4.COLLECTION_ID                # COPERNICUS/S2_SR_HARMONIZED
DATASET_ID = COLLECTION_ID
SCL_DROP_CLASSES = sec4.SCL_DROP_CLASSES          # (3, 8, 9, 10, 11)
MAX_SCENE_CLOUD_PCT = sec4.MAX_SCENE_CLOUD_PCT    # 60.0 broad prefilter; SCL is primary
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
LOW_VALID_SCENE_COUNT = sec4.LOW_VALID_SCENE_COUNT  # <3 is flagged, never masked
COUNT_MISSING = -1                                # count tile unavailable on disk
OBS_COUNT_NAME = "observed_valid_count"
CLIM_COUNT_NAME = "clim_valid_count"
OBS_LOW_FLAG_NAME = "observed_low_count_lt3"
CLIM_LOW_FLAG_NAME = "clim_low_count_lt3"
COUNT_RESAMPLING = "nearest"                    # semantic name in metadata / notes
COUNT_DOWNLOAD_RESAMPLING = "near"              # geemap/geedim spelling


# --- Pure logic (numpy / pandas only; unit-tested without the geo or EE stack) ---
def ndmi_from_bands(b8: np.ndarray, b11: np.ndarray) -> np.ndarray:
    """NDMI = (B8 - B11) / (B8 + B11), NaN where the sum is zero (Section 4 formula).

    Reference for the index EE computes server-side; reuses Section 4 so the two cannot drift.
    """
    return sec4.normalized_difference(b8, b11)


def date_window_bounds(center_date: pd.Timestamp,
                       window_days: int = WINDOW_DAYS) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Inclusive [start, end] calendar dates of the +/- ``window_days`` window.

    Returns midnight-floored Timestamps; the caller adds one day to make the EE
    (exclusive) filterDate end inclusive of the whole last day.
    """
    c = pd.Timestamp(center_date).normalize()
    return c - pd.Timedelta(days=int(window_days)), c + pd.Timedelta(days=int(window_days))


def doy_of(ts) -> int:
    """Day-of-year (1-366) of a timestamp."""
    return int(pd.Timestamp(ts).dayofyear)


def climatology_years(target_year: int,
                      year_lo: int = CLIM_YEAR_LO, year_hi: int = CLIM_YEAR_HI) -> list[int]:
    """Years in one overpass's day-of-year climatology: [lo..hi] minus ``target_year`` (LOYO).

    For the all-2023 pilot this is [2018, 2019, 2020, 2021, 2022, 2024].
    """
    return [y for y in range(int(year_lo), int(year_hi) + 1) if y != int(target_year)]


def year_window_ranges(doy: int, years: Sequence[int],
                       window_days: int = WINDOW_DAYS,
                       ref_year: int = 2001) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """For a target day-of-year, the [start, end] calendar window in EACH given year.

    The day-of-year climatology is realised as a union of per-year +/-window windows.
    ``ref_year`` (non-leap) maps day-of-year to a month/day reused in each target year.
    Returns inclusive pairs (the caller makes the EE end exclusive by +1 day).
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
    """Group overpasses by exact day-of-year so identical climatologies compute ONCE.

    Returns ``(groups, unique_doys)``: ``groups[doy]`` is the list of overpass row-indices
    sharing that day-of-year; the caller computes once per unique day-of-year and broadcasts.
    """
    groups: dict[int, list[int]] = {}
    for i, (_, row) in enumerate(overpasses.iterrows()):
        d = doy_of(row["time"])
        groups.setdefault(d, []).append(i)
    return groups, sorted(groups)


def expected_count_tile_names(overpasses: pd.DataFrame,
                              only_overpass: int | None = None) -> list[str]:
    """Deterministic resumable count-tile inventory (observed + deduped climatology)."""
    if only_overpass is None:
        obs_indices = range(len(overpasses))
        doys = dedup_climatology_windows(overpasses)[1]
    else:
        if not 0 <= int(only_overpass) < len(overpasses):
            raise IndexError(f"overpass {only_overpass} outside 0..{len(overpasses)-1}")
        obs_indices = [int(only_overpass)]
        doys = [doy_of(overpasses.iloc[int(only_overpass)]["time"])]
    return ([f"obs_count_op{i:02d}.tif" for i in obs_indices]
            + [f"clim_count_doy{d:03d}.tif" for d in doys])


def count_cache_inventory(overpasses: pd.DataFrame, raw_dir: Path,
                          only_overpass: int | None = None) -> dict:
    """Report how many expected count tiles are cached; no EE/network calls."""
    expected = expected_count_tile_names(overpasses, only_overpass)
    present = [name for name in expected if (raw_dir / name).exists()]
    present_set = set(present)
    missing = [name for name in expected if name not in present_set]
    return {"expected": len(expected), "present": len(present),
            "missing": len(missing), "missing_names": missing}


def low_count_flag(counts: np.ndarray,
                   threshold: int = LOW_VALID_SCENE_COUNT,
                   missing_value: int = COUNT_MISSING) -> np.ndarray:
    """Return a uint8 diagnostic flag for valid counts below ``threshold``.

    Missing count tiles use ``missing_value`` and are not called low coverage. The
    flag is diagnostic only: it never changes the associated NDMI values.
    """
    arr = np.asarray(counts)
    return ((arr != missing_value) & (arr >= 0) & (arr < int(threshold))).astype("uint8")


def count_cube_stats(counts: np.ndarray,
                     threshold: int = LOW_VALID_SCENE_COUNT,
                     missing_value: int = COUNT_MISSING) -> dict:
    """Exact, memory-conscious stats for an integer count cube.

    A histogram is accumulated one leading-axis slab at a time, avoiding a large
    float copy of the full 66-by-y-by-x cube. Genuine zeros remain valid; only -1
    denotes a count tile that is not available on disk.
    """
    arr = np.asarray(counts)
    slabs = arr if arr.ndim > 2 else arr[np.newaxis, ...]
    hist = np.zeros(0, dtype="int64")
    n_missing = 0
    for slab in slabs:
        flat = np.asarray(slab).reshape(-1)
        if np.any(~np.isfinite(flat)):
            raise ValueError("valid-scene counts must be finite integers or the missing sentinel")
        missing = flat == missing_value
        n_missing += int(missing.sum())
        vals = flat[~missing]
        if np.any(vals < 0) or not np.all(vals == np.floor(vals)):
            raise ValueError("valid-scene counts must be integer-valued and nonnegative")
        if vals.size:
            binc = np.bincount(vals.astype("int64"))
            if binc.size > hist.size:
                hist = np.pad(hist, (0, binc.size - hist.size))
            hist[:binc.size] += binc

    n_valid = int(hist.sum())
    total = int(arr.size)
    if not n_valid:
        return {
            "n_valid": 0, "n_missing": n_missing,
            "frac_missing": n_missing / total if total else None,
            "min": None, "median": None, "max": None, "n_lt_threshold": 0,
            "frac_lt_threshold": None, "low_threshold": int(threshold),
        }
    occupied = np.flatnonzero(hist)
    cumulative = np.cumsum(hist)

    def _order_stat(k: int) -> int:
        return int(np.searchsorted(cumulative, k + 1, side="left"))

    lo_mid = _order_stat((n_valid - 1) // 2)
    hi_mid = _order_stat(n_valid // 2)
    n_low = int(hist[:int(threshold)].sum())
    return {
        "n_valid": n_valid,
        "n_missing": n_missing,
        "frac_missing": n_missing / total if total else None,
        "min": int(occupied[0]),
        "median": (lo_mid + hi_mid) / 2.0,
        "max": int(occupied[-1]),
        "n_lt_threshold": n_low,
        "frac_lt_threshold": n_low / n_valid,
        "low_threshold": int(threshold),
    }


# --- Earth Engine: per-overpass reductions (needs ee) ---
def _ndmi_image(image: "ee.Image") -> "ee.Image":
    """Per-scene NDMI = normalizedDifference(B8, B11), renamed to the index name."""
    return image.normalizedDifference(list(NDMI_BANDS)).rename(NDMI_NAME)


def _masked_ndmi_collection(region: "ee.Geometry", start: str, end: str,
                            max_scene_cloud_pct: float = MAX_SCENE_CLOUD_PCT
                            ) -> "ee.ImageCollection":
    """S2 SR (harmonized) over [start, end): scene-cloud filter, SCL-mask, per-scene NDMI.

    ``end`` is EXCLUSIVE (EE filterDate convention).
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
    """Per-overpass OBSERVED NDMI: median composite within +/-window of the overpass date (2023)."""
    lo, hi = date_window_bounds(center_date, window_days)
    end_excl = hi + pd.Timedelta(days=1)          # make the last day inclusive
    coll = _masked_ndmi_collection(region, _date_str(lo), _date_str(end_excl))
    return coll.median().rename(NDMI_NAME)


def observed_count_image(region: "ee.Geometry", center_date: pd.Timestamp,
                         window_days: int = WINDOW_DAYS) -> "ee.Image":
    """Post-SCL valid NDMI count in one observed +/-window as uint16 (zero unmasked)."""
    lo, hi = date_window_bounds(center_date, window_days)
    coll = _masked_ndmi_collection(
        region, _date_str(lo), _date_str(hi + pd.Timedelta(days=1)))
    return coll.count().rename(OBS_COUNT_NAME).unmask(0).toUint16()


def _climatology_collection(region: "ee.Geometry", doy: int,
                            years: Sequence[int], window_days: int = WINDOW_DAYS
                            ) -> "ee.ImageCollection":
    """Merged post-SCL NDMI collection for one LOYO day-of-year window."""
    coll = None
    for lo, hi in year_window_ranges(doy, years, window_days):
        c = _masked_ndmi_collection(
            region, _date_str(lo), _date_str(hi + pd.Timedelta(days=1)))
        coll = c if coll is None else coll.merge(c)
    return coll


def climatology_images(region: "ee.Geometry", doy: int, years: Sequence[int],
                       window_days: int = WINDOW_DAYS) -> tuple["ee.Image", "ee.Image"]:
    """Day-of-year LOYO climatology mean and (population) std images for one day-of-year."""
    coll = _climatology_collection(region, doy, years, window_days)
    mean_img = coll.mean().rename("clim_mean")
    std_img = coll.reduce(ee.Reducer.stdDev()).rename("clim_std")
    return mean_img, std_img


def climatology_count_image(region: "ee.Geometry", doy: int, years: Sequence[int],
                            window_days: int = WINDOW_DAYS) -> "ee.Image":
    """Post-SCL valid NDMI count in one merged LOYO climatology window."""
    return (_climatology_collection(region, doy, years, window_days)
            .count().rename(CLIM_COUNT_NAME).unmask(0).toUint16())


# --- Resilient download (reuses Section 4's tiled geemap.download_ee_image ladder) ---
@dataclasses.dataclass
class TileResult:
    """Outcome of downloading one reduced 70 m image to a GeoTIFF (or Drive fallback)."""

    name: str                          # short id (e.g. "obs_op05" / "clim_mean_doy180")
    path: Path | None                  # local GeoTIFF, or None if it fell back to Drive
    method: str
    max_tile_size_mb: float | None = None
    drive_task_id: str | None = None
    scale_m: int | None = None
    resampling: str | None = None

    @property
    def is_local(self) -> bool:
        return self.path is not None


def _export_to_drive(image: "ee.Image", name: str, region: "ee.Geometry",
                     scale_m: int, resampling: str = "bilinear") -> TileResult:
    """Last resort: start an Export.image.toDrive task and flag it for the user."""
    task = ee.batch.Export.image.toDrive(
        image=image, description=name, folder=DRIVE_FOLDER, fileNamePrefix=name,
        region=region, crs=config.CRS, scale=scale_m, maxPixels=int(1e13),
        fileFormat="GeoTIFF")
    task.start()
    log.error("Drive FALLBACK for %s: started Export.image.toDrive task id=%s "
              "(folder=%s, file=%s.tif)", name, task.id, DRIVE_FOLDER, name)
    return TileResult(name=name, path=None, method="Export.image.toDrive",
                      drive_task_id=task.id, scale_m=scale_m, resampling=resampling)


def download_image(image: "ee.Image", name: str, region: "ee.Geometry", raw_dir: Path,
                   scale_m: int, tile_sizes_mb: Sequence[float] = MAX_TILE_SIZES_MB,
                   overwrite: bool = True, resampling: str = "bilinear") -> TileResult:
    """Download one reduced image to ``raw_dir/<name>.tif`` (EPSG:32612, ``scale_m``).

    Retries with smaller tiles on failure, then falls back to Export.image.toDrive.
    With ``overwrite=False`` reuses a valid on-disk file (the --skip-download / resume path).
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / f"{name}.tif"
    # Tiny continuous files are usually interrupted stubs. Count files may compress very
    # small, so validate their GeoTIFF structure/dtype instead of applying a byte threshold.
    _MIN_VALID_BYTES = 100_000
    if not overwrite and out_path.exists():
        is_count = "count" in name
        valid_cache = (sec4._valid_cached_count_tif(out_path) if is_count
                       else out_path.stat().st_size >= _MIN_VALID_BYTES)
        if valid_cache:
            log.info("  reuse %s (%.2f MB on disk)", out_path.name,
                     out_path.stat().st_size / 1e6)
            return TileResult(name=name, path=out_path, method="(reused local file)",
                              scale_m=scale_m, resampling=resampling)
        log.warning("  refetch %s (cached file failed %s validation)", out_path.name,
                    "integer GeoTIFF" if is_count else f">={_MIN_VALID_BYTES}-byte")

    last_exc: Exception | None = None
    for mts in tile_sizes_mb:
        try:
            geemap.download_ee_image(
                image, str(out_path), region=region, crs=config.CRS, scale=scale_m,
                resampling=resampling,
                overwrite=True, max_tile_size=mts,
                num_threads=MAX_REQUESTS, max_requests=MAX_REQUESTS)
            log.info("  downloaded %s (%.2f MB) at max_tile_size=%sMB",
                     out_path.name, out_path.stat().st_size / 1e6, mts)
            return TileResult(name=name, path=out_path,
                              method="geemap.download_ee_image", max_tile_size_mb=mts,
                              scale_m=scale_m, resampling=resampling)
        except Exception as exc:  # noqa: BLE001 - retry smaller, then Drive
            last_exc = exc
            log.warning("  download %s failed at max_tile_size=%sMB: %s: %s -- "
                        "retrying smaller", name, mts, type(exc).__name__, exc)
    log.error("  all tiled attempts for %s failed (last: %s: %s).",
              name, type(last_exc).__name__, last_exc)
    return _export_to_drive(image, name, region, scale_m, resampling=resampling)


# --- Loading helpers (the geo stack) ---
def _reference() -> "xr.DataArray":
    """The 70 m reference grid as a 2-D rioxarray DataArray (the match target / CRS)."""
    return rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)


def load_overpass_axis(processed: Path) -> pd.DataFrame:
    """The 66-overpass master axis (overpass, key, time) from the Section 9 cube, in its order."""
    cube = xr.open_zarr(processed / ANALYSIS_CUBE, decode_coords="all")
    df = pd.DataFrame({
        "overpass": np.asarray(cube["overpass"].values, dtype="int32"),
        "overpass_key": np.array([str(k) for k in cube["overpass_key"].values], dtype=object),
        "time": pd.to_datetime(cube["time"].values),
    })
    cube.close()
    return df


def _read_grid_array(path: Path, reference: "xr.DataArray") -> np.ndarray:
    """Open a downloaded GeoTIFF, reproject_match (bilinear) to the reference grid, return float32.

    Snaps any sub-pixel origin/extent mismatch exactly onto reference_grid.tif. NaN where masked.
    """
    from rasterio.enums import Resampling
    da = rioxarray.open_rasterio(path, masked=True).squeeze("band", drop=True)
    matched = da.rio.reproject_match(reference, resampling=Resampling.bilinear)
    return matched.values.astype("float32")


def _read_grid_count(path: Path, reference: "xr.DataArray") -> np.ndarray:
    """Open a count GeoTIFF, nearest-match to 70 m, assert exact nonnegative integers."""
    from rasterio.enums import Resampling
    da = rioxarray.open_rasterio(path, masked=False).squeeze("band", drop=True)
    matched = da.rio.reproject_match(reference, resampling=Resampling.nearest)
    values = np.asarray(matched.values)
    if np.any(~np.isfinite(values)) or np.any(values < 0) \
            or not np.all(values == np.floor(values)):
        raise AssertionError(f"{path.name}: count is not finite/nonnegative integer")
    if np.max(values, initial=0) > np.iinfo("int16").max:
        raise AssertionError(f"{path.name}: count exceeds int16 storage")
    return values.astype("int16")


# --- Assembly -> the NDMI time-series Zarr ---
def _blosc():
    import numcodecs
    return numcodecs.Blosc(cname="zstd", clevel=5, shuffle=numcodecs.Blosc.SHUFFLE)


def assemble_dataset(observed: np.ndarray, clim_mean: np.ndarray, clim_std: np.ndarray,
                     observed_count: np.ndarray, clim_count: np.ndarray,
                     overpasses: pd.DataFrame, reference: "xr.DataArray") -> "xr.Dataset":
    """Build NDMI values, nearest count diagnostics, and non-destructive <3 flags."""
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
            OBS_COUNT_NAME: (("overpass", "y", "x"), observed_count.astype("int16")),
            CLIM_COUNT_NAME: (("overpass", "y", "x"), clim_count.astype("int16")),
            OBS_LOW_FLAG_NAME: (("overpass", "y", "x"),
                                low_count_flag(observed_count)),
            CLIM_LOW_FLAG_NAME: (("overpass", "y", "x"),
                                 low_count_flag(clim_count)),
        },
        coords=coords,
    )
    ds = ds.rio.write_crs(reference.rio.crs)
    for v in ("observed", "clim_mean", "clim_std"):
        ds[v].attrs["grid_mapping"] = "spatial_ref"
        ds[v].attrs["units"] = "1"                # NDMI is dimensionless
    for v in (OBS_COUNT_NAME, CLIM_COUNT_NAME):
        ds[v].attrs.update({
            "grid_mapping": "spatial_ref", "units": "valid scenes",
            "resampling": COUNT_RESAMPLING, "missing_value": COUNT_MISSING,
            "valid_min": 0,
            "low_count_rule": (f"count < {LOW_VALID_SCENE_COUNT} is flagged only; "
                               "NDMI is not masked"),
        })
    for v in (OBS_LOW_FLAG_NAME, CLIM_LOW_FLAG_NAME):
        ds[v].attrs.update({
            "grid_mapping": "spatial_ref", "units": "1",
            "flag_values": [0, 1],
            "flag_meanings": "adequate_or_missing low_valid_scene_count",
            "diagnostic_only": "does not mask observed/climatological NDMI",
        })
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
    ds[OBS_COUNT_NAME].attrs["long_name"] = (
        "Post-SCL valid Sentinel-2 NDMI observations in each +/-15-day observed window")
    ds[CLIM_COUNT_NAME].attrs["long_name"] = (
        "Post-SCL valid Sentinel-2 NDMI observations in each merged LOYO climatology window")
    ds.attrs["title"] = ("Section 4b: time-resolved Sentinel-2 NDMI (per-overpass observed "
                         "+ 2018-2024 leave-one-year-out day-of-year climatology) on the 70 m grid")
    ds.attrs["crs"] = config.CRS
    ds.attrs["collection"] = COLLECTION_ID
    ds.attrs["climatology_years"] = list(config.CLIMATOLOGY_YEARS)
    ds.attrs["climatology_window_days"] = WINDOW_DAYS
    ds.attrs["scene_cloud_pct_max"] = MAX_SCENE_CLOUD_PCT
    ds.attrs["scene_prefilter_keep_rule"] = (
        f"CLOUDY_PIXEL_PERCENTAGE < {MAX_SCENE_CLOUD_PCT:g}")
    ds.attrs["scene_prefilter_role"] = (
        "broad scene guard; per-pixel SCL masking is primary")
    ds.attrs["scene_prefilter_totals_scope"] = (
        "not collapsed across overlapping observed/climatology windows; use the per-window "
        "post-SCL count variables and the Section 4 warm-season before/after totals")
    ds.attrs["valid_count_resampling"] = COUNT_RESAMPLING
    ds.attrs["low_valid_scene_count_threshold"] = LOW_VALID_SCENE_COUNT
    ds.attrs["low_count_action"] = "flag only; do not mask NDMI"
    ds.attrs["scl_drop_classes"] = list(SCL_DROP_CLASSES)
    ds.attrs["ndmi_bands"] = list(NDMI_BANDS)
    ds.attrs["native_scale_m"] = NDMI_NATIVE_SCALE_M
    ds.attrs["supersedes"] = (
        f"data/interim/{OLD_STATIC_NDMI_TIF} (the single static 2023 warm-season median) "
        "as the input to Section 11's NDMI vegetation-condition check; this product gives "
        "that check a real time dimension but does not define the primary water-supply axis.")
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


# --- Manifest ---
def record_in_manifest(tiles: Sequence[TileResult], project: str) -> None:
    """Append each downloaded per-overpass / per-day-of-year GeoTIFF to the manifest."""
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    rows = []
    for t in tiles:
        if not t.is_local or t.method == "(reused local file)":
            continue
        is_count = "count" in t.name
        artifact = ("post-SCL valid-scene count; integer; nearest-neighbour"
                    if is_count else "time-resolved NDMI reduction; continuous")
        rows.append({
            "source": (f"Google Earth Engine {COLLECTION_ID} (project={project}; "
                       f"Section 4b {artifact}; output scale={t.scale_m or 'unknown'} m; "
                       f"EPSG:32612; geemap.download_ee_image; {t.name})"),
            "dataset": DATASET_ID,
            "filename": t.path.name,
            "download_date": today,
            "checksum": f"sha256:{sec2.sha256_file(t.path)}",
        })
    if rows:
        sec2.append_to_manifest(rows)
        log.info("Recorded %d Section 4b GeoTIFFs in the manifest.", len(rows))


# --- Download orchestration (EE) ---
def download_all(overpasses: pd.DataFrame, region: "ee.Geometry", raw_dir: Path,
                 scale_m: int, overwrite: bool,
                 only_overpass: int | None = None,
                 counts_only: bool = False,
                 include_counts: bool = True) -> list[TileResult]:
    """Download values plus counts, or resume only missing count diagnostics.

    Count files are named separately and always use nearest resampling. ``counts_only``
    skips observed/climatology value reductions, reuses existing count files, and is the
    safe recovery path after the original continuous tiles have already been cached.
    """
    n = len(overpasses)
    groups, unique_doys = dedup_climatology_windows(overpasses)
    log.info("Climatology dedup: %d overpasses -> %d UNIQUE day-of-year windows "
             "(%.1fx fewer climatology reductions)", n, len(unique_doys),
             n / max(1, len(unique_doys)))

    tiles: list[TileResult] = []

    # Per-overpass OBSERVED median composites (in 2023).
    op_iter = range(n) if only_overpass is None else [only_overpass]
    for i in op_iter:
        row = overpasses.iloc[i]
        lo, hi = date_window_bounds(row["time"])
        log.info("[observed %2d/%d] op=%d key=%s date=%s window=[%s..%s]",
                 i + 1 if only_overpass is None else i, n, int(row["overpass"]),
                 row["overpass_key"], _date_str(row["time"]), _date_str(lo), _date_str(hi))
        if not counts_only:
            img = observed_image(region, row["time"])
            tiles.append(download_image(img, f"obs_op{i:02d}", region, raw_dir, scale_m,
                                        overwrite=overwrite))
        if include_counts:
            count_img = observed_count_image(region, row["time"])
            tiles.append(download_image(
                count_img, f"obs_count_op{i:02d}", region, raw_dir, scale_m,
                overwrite=False, resampling=COUNT_DOWNLOAD_RESAMPLING))

    # Deduped day-of-year CLIMATOLOGY mean/std (LOYO).
    doys_to_do = unique_doys
    if only_overpass is not None:
        doys_to_do = [doy_of(overpasses.iloc[only_overpass]["time"])]
    for k, d in enumerate(doys_to_do):
        yrs = climatology_years(2023)             # all pilot overpasses are 2023 -> LOYO drops 2023
        log.info("[clim %2d/%d] doy=%d  LOYO years=%s  (serves %d overpass(es))",
                 k + 1, len(doys_to_do), d, yrs, len(groups.get(d, [])))
        if not counts_only:
            mean_img, std_img = climatology_images(region, d, yrs)
            tiles.append(download_image(mean_img, f"clim_mean_doy{d:03d}", region, raw_dir,
                                        scale_m, overwrite=overwrite))
            tiles.append(download_image(std_img, f"clim_std_doy{d:03d}", region, raw_dir,
                                        scale_m, overwrite=overwrite))
        if include_counts:
            count_img = climatology_count_image(region, d, yrs)
            tiles.append(download_image(
                count_img, f"clim_count_doy{d:03d}", region, raw_dir, scale_m,
                overwrite=False, resampling=COUNT_DOWNLOAD_RESAMPLING))
    return tiles


def assemble_from_disk(overpasses: pd.DataFrame, raw_dir: Path,
                       reference: "xr.DataArray") -> "xr.Dataset":
    """Read the downloaded per-overpass / per-day-of-year GeoTIFFs into the (66,y,x) cube.

    Maps each deduped day-of-year clim tile back to every overpass sharing it; missing tiles
    (e.g. a Drive fallback not yet retrieved) leave that slice NaN and are reported.
    """
    n = len(overpasses)
    ny, nx = reference.sizes["y"], reference.sizes["x"]
    observed = np.full((n, ny, nx), np.nan, dtype="float32")
    clim_mean = np.full((n, ny, nx), np.nan, dtype="float32")
    clim_std = np.full((n, ny, nx), np.nan, dtype="float32")
    observed_count = np.full((n, ny, nx), COUNT_MISSING, dtype="int16")
    clim_count = np.full((n, ny, nx), COUNT_MISSING, dtype="int16")

    # Cache per-day-of-year clim arrays so each unique tile is read from disk once.
    cm_cache: dict[int, np.ndarray] = {}
    cs_cache: dict[int, np.ndarray] = {}
    cc_cache: dict[int, np.ndarray] = {}
    missing_values: list[str] = []
    missing_counts: list[str] = []

    for i in range(n):
        d = doy_of(overpasses.iloc[i]["time"])
        obs_p = raw_dir / f"obs_op{i:02d}.tif"
        if obs_p.exists():
            observed[i] = _read_grid_array(obs_p, reference)
        else:
            missing_values.append(obs_p.name)
        obs_count_p = raw_dir / f"obs_count_op{i:02d}.tif"
        if obs_count_p.exists():
            observed_count[i] = _read_grid_count(obs_count_p, reference)
        else:
            missing_counts.append(obs_count_p.name)

        if d not in cm_cache:
            cm_p = raw_dir / f"clim_mean_doy{d:03d}.tif"
            cs_p = raw_dir / f"clim_std_doy{d:03d}.tif"
            cm_cache[d] = _read_grid_array(cm_p, reference) if cm_p.exists() else None
            cs_cache[d] = _read_grid_array(cs_p, reference) if cs_p.exists() else None
            if cm_cache[d] is None:
                missing_values.append(cm_p.name)
            if cs_cache[d] is None:
                missing_values.append(cs_p.name)
            cc_p = raw_dir / f"clim_count_doy{d:03d}.tif"
            cc_cache[d] = _read_grid_count(cc_p, reference) if cc_p.exists() else None
            if cc_cache[d] is None:
                missing_counts.append(cc_p.name)
        if cm_cache[d] is not None:
            clim_mean[i] = cm_cache[d]
        if cs_cache[d] is not None:
            clim_std[i] = cs_cache[d]
        if cc_cache[d] is not None:
            clim_count[i] = cc_cache[d]

    if missing_values:
        unique = sorted(set(missing_values))
        log.warning("assemble_from_disk: %d value GeoTIFF(s) missing -> those slices "
                    "stay NaN: %s", len(unique), unique[:8])
    if missing_counts:
        unique = sorted(set(missing_counts))
        log.warning("assemble_from_disk: %d count GeoTIFF(s) missing -> count=-1 and low "
                    "flag=0; NDMI remains unchanged: %s", len(unique), unique[:8])
    return assemble_dataset(observed, clim_mean, clim_std, observed_count, clim_count,
                            overpasses, reference)


# --- QC (Section 2 of the brief) ---
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

    # (g) Post-SCL valid-scene counts and diagnostic-only low-count flags.
    log.info("-" * 72)
    log.info("QC(g): post-SCL valid-scene counts (nearest; count<%d is FLAGGED, not masked)",
             LOW_VALID_SCENE_COUNT)
    count_pairs = ((OBS_COUNT_NAME, OBS_LOW_FLAG_NAME, "observed"),
                   (CLIM_COUNT_NAME, CLIM_LOW_FLAG_NAME, "climatology"))
    missing_vars = [name for pair in count_pairs for name in pair[:2] if name not in ds]
    if missing_vars:
        out["valid_count_status"] = "pending count-only retrieval/rebuild"
        out["valid_count_missing_variables"] = missing_vars
        log.warning("  count diagnostics not present in this saved store: %s", missing_vars)
        log.warning("  existing continuous NDMI values remain valid; run --counts-only to "
                    "retrieve counts, then rebuild the store.")
    else:
        out["valid_count_status"] = "available"
        count_stats: dict[str, dict] = {}
        for count_name, flag_name, label in count_pairs:
            arr = np.asarray(ds[count_name].values)
            stats = count_cube_stats(arr)
            expected_flag = low_count_flag(arr)
            actual_flag = np.asarray(ds[flag_name].values, dtype="uint8")
            if not np.array_equal(actual_flag, expected_flag):
                raise AssertionError(f"{flag_name} does not exactly match count<"
                                     f"{LOW_VALID_SCENE_COUNT}")
            per_slice_low = []
            per_slice_missing = []
            for slab in arr:
                valid = slab != COUNT_MISSING
                per_slice_low.append(
                    float(low_count_flag(slab).sum() / valid.sum()) if valid.any() else np.nan)
                per_slice_missing.append(float((~valid).mean()))
            per_op[f"{label}_count_lt{LOW_VALID_SCENE_COUNT}_frac"] = per_slice_low
            per_op[f"{label}_count_missing_frac"] = per_slice_missing
            count_stats[count_name] = stats
            log.info("  %-13s min=%s median=%s max=%s; low=%d/%d (%.3f%%); "
                     "missing=%d (%.3f%%)", label, stats["min"], stats["median"],
                     stats["max"], stats["n_lt_threshold"], stats["n_valid"],
                     100 * (stats["frac_lt_threshold"] or 0.0), stats["n_missing"],
                     100 * (stats["frac_missing"] or 0.0))
        out["valid_count_stats"] = count_stats
        log.info("  ASSERTIONS PASSED: count rasters are finite nonnegative integers (or -1 "
                 "when unavailable); flags match exactly; NDMI arrays are not changed.")

    out["per_overpass"] = per_op

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
    """Spatially correlate the NEW observed season-median against the OLD static composite.

    High correlation = the new product resolves the time the old one collapsed, consistently.
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


def render_timeseries_coverage_note(inventory: dict, qc: dict | None = None) -> str:
    """Markdown body for the Section 4b marker in the shared coverage note."""
    stats_by_var = (qc or {}).get("valid_count_stats", {})
    rows = []
    for variable, label in ((OBS_COUNT_NAME, "Observed +/-15-day window"),
                            (CLIM_COUNT_NAME, "LOYO climatology window")):
        stats = stats_by_var.get(variable)
        if stats and stats.get("n_valid"):
            low = (f"{stats['n_lt_threshold']:,} "
                   f"({100 * stats['frac_lt_threshold']:.3f}%)")
            missing = (f"{stats['n_missing']:,} "
                       f"({100 * stats['frac_missing']:.3f}%)")
            fields = (str(stats["min"]), f"{stats['median']:.1f}", str(stats["max"]),
                      low, missing)
        else:
            fields = ("pending",) * 5
        rows.append(f"| {label} | {' | '.join(fields)} |")

    missing_names = inventory.get("missing_names", [])
    sample = ", ".join(f"`{name}`" for name in missing_names[:6])
    missing_detail = (f" First missing files: {sample}." if sample else "")
    return "\n".join([
        "## Section 4b time-resolved NDMI",
        "",
        (f"The resumable count cache expects **{inventory['expected']:,}** files "
         f"(one observed count per overpass plus one climatology count per unique day-of-year): "
         f"**{inventory['present']:,} present**, **{inventory['missing']:,} missing**."
         f"{missing_detail}"),
        "",
        (f"The same broad scene guard keeps `CLOUDY_PIXEL_PERCENTAGE < "
         f"{MAX_SCENE_CLOUD_PCT:g}`; per-pixel SCL masking remains primary. A single "
         "before/after scene total is not collapsed across the overlapping time windows, "
         "because that would double-count scenes. The non-overlapping warm-season totals "
         "are recorded in the Section 4 table above."),
        "",
        "| Count variable | min | median | max | 70 m cells with count <3 | count unavailable (-1) |",
        "|---|---:|---:|---:|---:|---:|",
        *rows,
        "",
        ("Count GeoTIFFs and cube variables use nearest-neighbour resampling and exact integer "
         "storage. A genuine zero is a valid count. Only `-1` means the count tile has not "
         "been retrieved. The separate `<3` flags are diagnostic and never mask NDMI."),
        "",
        ("Existing median/mean/std tiles cannot reconstruct these counts. Missing files require "
         "an authenticated Earth Engine run with `python src/section4b_ndmi_timeseries.py "
         "--counts-only`; the command is interruption-safe and reuses completed count tiles."),
    ])


def update_timeseries_coverage_note(inventory: dict, qc: dict | None = None) -> Path:
    """Persist Section 4b count-cache state and any available count statistics."""
    return sec4.update_coverage_note(
        "SECTION4B_TIMESERIES", render_timeseries_coverage_note(inventory, qc))


# --- Orchestration / CLI ---
def run(skip_download: bool = False, coarse_scale: int | None = None,
        only_overpass: int | None = None, verify_only: bool = False,
        counts_only: bool = False) -> dict:
    if skip_download and counts_only:
        raise SystemExit("--skip-download and --counts-only are mutually exclusive")
    if coarse_scale is not None and counts_only:
        raise SystemExit("--counts-only must run at the exact 70 m analysis scale; remove "
                         "--coarse-scale")
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

    inventory = count_cache_inventory(overpasses, raw_dir)
    results: dict = {"store": store, "count_inventory_before": inventory}
    scale_m = coarse_scale or config.CELL_SIZE_M

    if verify_only:
        results["qc"] = run_qc(store, reference, interim)
        results["count_inventory_after"] = count_cache_inventory(overpasses, raw_dir)
        update_timeseries_coverage_note(results["count_inventory_after"], results["qc"])
        _report(results, only_overpass, coarse_scale)
        return results

    project = "default"
    if not skip_download:
        project = sec4.initialize_ee()
        region = sec4.study_region()
        # overwrite=False -> RESUME: reuse valid on-disk tiles, refetch only missing/corrupt
        # ones, so both value and count pulls are interruption-safe. Delete a tile (or the
        # raw subdir) to force a fresh fetch; --skip-download skips downloads entirely.
        tiles = download_all(overpasses, region, raw_dir, scale_m,
                             overwrite=False, only_overpass=only_overpass,
                             counts_only=counts_only,
                             include_counts=coarse_scale is None)
        # A coarse-scale or single-overpass run is not the native product -> keep it OUT of
        # the manifest.
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
            results["count_inventory_after"] = count_cache_inventory(overpasses, raw_dir)
            update_timeseries_coverage_note(results["count_inventory_after"])
            _report(results, only_overpass, coarse_scale)
            return results

    if only_overpass is not None:
        log.info("--overpass %d: downloaded that overpass's tiles only; skipping the "
                 "full-cube assembly (use a full run to build the Zarr).", only_overpass)
        results["single_overpass"] = only_overpass
        results["count_inventory_after"] = count_cache_inventory(overpasses, raw_dir)
        update_timeseries_coverage_note(results["count_inventory_after"])
        _report(results, only_overpass, coarse_scale)
        return results

    ds = assemble_from_disk(overpasses, raw_dir, reference)
    write_zarr(ds, store)
    ds.close()
    results["qc"] = run_qc(store, reference, interim)
    results["count_inventory_after"] = count_cache_inventory(overpasses, raw_dir)
    update_timeseries_coverage_note(results["count_inventory_after"], results["qc"])
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
            log.info("  OBSERVED spatial-mean spread across overpasses = %.4f (the NDMI "
                     "vegetation-condition check is TIME-VARYING).",
                     qc["observed_spatialmean_spread"])
        if qc.get("agreement"):
            log.info("  agreement with old static composite: Pearson r=%.4f",
                     qc["agreement"].get("pearson_r", float("nan")))
    inventory = results.get("count_inventory_after", results.get("count_inventory_before"))
    if inventory:
        log.info("  count cache: %d/%d present; %d still require Earth Engine",
                 inventory["present"], inventory["expected"], inventory["missing"])
    log.info("=" * 72)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 4b - time-resolved Sentinel-2 NDMI (per-overpass observed + "
                    "2018-2024 leave-one-year-out day-of-year climatology) for the "
                    "vegetation-condition check.")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--skip-download", action="store_true",
                      help="reuse the per-overpass / per-day-of-year GeoTIFFs already in "
                           "data/raw/sentinel2_ndmi_ts/ (assemble + QC only).")
    mode.add_argument("--counts-only", action="store_true",
                      help="retrieve/reuse only the missing post-SCL observed and climatology "
                           "count tiles at 70 m with nearest-neighbour resampling; do not "
                           "redownload continuous NDMI tiles.")
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
        only_overpass=args.overpass, verify_only=args.verify_only,
        counts_only=args.counts_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
