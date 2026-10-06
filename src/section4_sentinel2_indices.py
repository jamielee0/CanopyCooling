#!/usr/bin/env python3
"""Section 4 / Sentinel-2 indices — acquire warm-season NDVI and NDMI composites.

Inputs : COPERNICUS/S2_SR_HARMONIZED (Earth Engine), config bbox + PILOT_WINDOW;
         data/processed reference grid (config.REFERENCE_GRID_TIF).
Outputs: native-scale composites in data/raw/sentinel2/ (NDVI 10 m, NDMI 20 m),
         70 m-grid composites in data/interim/, QA figures in figures/,
         manifest rows in data/manifest.csv.
Key decisions (full rationale in docs/DESIGN_DECISIONS.md, Section 4):
  - No manual download: geemap.download_ee_image (geedim) tiles+stitches locally;
    Export.image.toDrive is a last-resort fallback only.
  - HARMONIZED collection so the whole archive shares one reflectance scale.
  - NDMI kept honest at 20 m (SWIR B11 is native 20 m); NDVI is true 10 m.
  - Both resampled bilinear onto the 70 m grid (continuous quantities).
  - Broad scene prefilter keeps CLOUDY_PIXEL_PERCENTAGE <60%; per-pixel SCL masking is primary.
  - Post-SCL valid-scene counts are retained as QC; pixels with <3 are flagged, not masked.
Run: python src/section4_sentinel2_indices.py
       [--indices ndvi,ndmi] [--skip-download] [--coarse-scale M]
       [--max-scene-cloud-pct P] [--counts-only] [-v]
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

# Heavy geospatial / EE libraries. The pure-numpy logic below does not touch
# them, so it stays unit-testable without the geo / EE stack installed.
import ee  # noqa: E402
import geemap  # noqa: E402
import rioxarray  # noqa: F401,E402  (registers the .rio accessor)
from rasterio.enums import Resampling  # noqa: E402

# Make config + the Section 2 module importable whether run from repo root or src/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
import config  # noqa: E402
import section2_ecostress_lst as sec2  # noqa: E402  (reuse manifest/checksum helpers)
import plot_style as ps  # noqa: E402  (shared figure color convention)

log = logging.getLogger("section4")

COLLECTION_ID = "COPERNICUS/S2_SR_HARMONIZED"
DATASET_ID = COLLECTION_ID                       # recorded in the manifest
PILOT_START, PILOT_END = config.PILOT_WINDOW     # ("2023-06-01", "2023-09-30")

# A deliberately broad scene-level guard. It removes only globally poor scenes; the
# PRIMARY cloud decision is the per-pixel SCL mask below. Keeping 60% preserves usable
# clear pixels in partly cloudy desert scenes, while the new post-mask count rasters make
# thin local support visible instead of silently tightening the scene gate.
MAX_SCENE_CLOUD_PCT = 60.0
SCENE_PREFILTER_RATIONALE = (
    "Keep scenes with CLOUDY_PIXEL_PERCENTAGE < 60%; this is a broad request-size guard. "
    "Per-pixel SCL masking is the primary cloud/shadow/snow filter, and post-mask valid-"
    "scene counts expose local support."
)
LOW_VALID_SCENE_COUNT = 3                 # flag count <3; never mask the index composite
COVERAGE_NOTE = config.DOCS_DIR / "section4_scene_coverage_note.md"

# Sentinel-2 Scene Classification Layer (SCL) class codes.
SCL_CLASS_NAMES = {
    0: "no_data", 1: "saturated_or_defective", 2: "dark_area_pixels",
    3: "cloud_shadow", 4: "vegetation", 5: "not_vegetated", 6: "water",
    7: "unclassified", 8: "cloud_medium_probability",
    9: "cloud_high_probability", 10: "thin_cirrus", 11: "snow_or_ice",
}
# Classes set to missing: cloud / cloud-shadow / snow (thin cirrus grouped here).
SCL_DROP_CLASSES = (3, 8, 9, 10, 11)

# Per-tile size ladder (MB) for the resilient download: retry smaller before the
# Drive fallback. Starts at 8 MB because a 10 m NDVI tile larger than that
# overflows EE's per-request memory when reducing a median over ~182 scenes.
MAX_TILE_SIZES_MB = (8, 4, 2, 1)

# Cap concurrent EE tile requests; geedim's default (32) triggers HTTP 429 storms
# and exceeds the connection-pool size (10) on this heavy median composite.
MAX_REQUESTS = 8

# High-vegetation threshold for the visual-check overlay (pre-registered, 0.5).
HIGH_NDVI_THRESHOLD = 0.5

RAW_SUBDIR = "sentinel2"                          # data/raw/sentinel2/
DRIVE_FOLDER = "canopy_section4"                  # only used by the fallback


# --- Product configuration (pure data; no geo / EE deps) ------------------- #
@dataclasses.dataclass(frozen=True)
class IndexProduct:
    """One normalized-difference index to acquire: (num - den) / (num + den).

    native_scale_m is the coarsest input band's resolution -- the scale the
    composite is downloaded at, kept honest (NDMI is a 20 m product).
    """

    key: str                 # short id used in paths/figures ("ndvi"/"ndmi")
    long_name: str
    bands: tuple             # (num, den), e.g. ("B8", "B4")
    native_scale_m: int      # 10 (NDVI) or 20 (NDMI)
    units: str = "1"

    @property
    def raw_filename(self) -> str:
        """Native-resolution composite, as downloaded into data/raw/sentinel2/."""
        return f"s2_{self.key}_warmseason_median_2023_{self.native_scale_m}m.tif"

    @property
    def grid_filename(self) -> str:
        """The composite resampled onto the 70 m reference grid (data/interim/)."""
        return f"s2_{self.key}_warmseason_median_2023_70m.tif"

    @property
    def count_band_name(self) -> str:
        """Earth Engine band name for the post-SCL valid-scene count."""
        return f"{self.key}_valid_scene_count"

    @property
    def count_raw_filename(self) -> str:
        """Exact integer count raster downloaded at the index's native scale."""
        return f"s2_{self.key}_valid_scene_count_2023_{self.native_scale_m}m.tif"

    @property
    def count_grid_filename(self) -> str:
        """Nearest-neighbour sample of the count on the 70 m analysis grid."""
        return f"s2_{self.key}_valid_scene_count_nearest_2023_70m.tif"

    @property
    def low_count_flag_grid_filename(self) -> str:
        """70 m uint8 flag (1=count<3); the index itself is never masked by this flag."""
        return f"s2_{self.key}_low_valid_scene_count_lt3_2023_70m.tif"


NDVI_PRODUCT = IndexProduct(
    key="ndvi",
    long_name="Sentinel-2 warm-season median NDVI (B8,B4); 10 m",
    bands=("B8", "B4"),
    native_scale_m=10,
)
# NDMI uses the 20 m SWIR band B11 -> a 20 m product, downloaded at 20 m.
NDMI_PRODUCT = IndexProduct(
    key="ndmi",
    long_name="Sentinel-2 warm-season median NDMI (B8,B11); 20 m (SWIR-limited)",
    bands=("B8", "B11"),
    native_scale_m=20,
)
PRODUCTS = {NDVI_PRODUCT.key: NDVI_PRODUCT, NDMI_PRODUCT.key: NDMI_PRODUCT}


# --- Pure index / mask logic (numpy; unit-tested without geo or EE) -------- #
def normalized_difference(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """(num - den) / (num + den), NaN where the sum is zero (matches EE polarity)."""
    num = np.asarray(num, dtype="float64")
    den = np.asarray(den, dtype="float64")
    total = num + den
    out = np.full(num.shape, np.nan, dtype="float64")
    nz = total != 0
    out[nz] = (num[nz] - den[nz]) / total[nz]
    return out


def scl_keep_mask(scl: np.ndarray,
                  drop_classes: Sequence[int] = SCL_DROP_CLASSES) -> np.ndarray:
    """True where the SCL pixel should be KEPT (not cloud / cloud-shadow / snow)."""
    scl = np.asarray(scl)
    keep = np.ones(scl.shape, dtype=bool)
    for cls in drop_classes:
        keep &= scl != cls
    return keep


def high_veg_mask(ndvi: np.ndarray,
                  threshold: float = HIGH_NDVI_THRESHOLD) -> np.ndarray:
    """True where NDVI marks dense vegetation (>= threshold), ignoring NaN."""
    arr = np.asarray(ndvi, dtype="float64")
    return np.isfinite(arr) & (arr >= threshold)


def valid_scene_count(stack: np.ndarray, axis: int = 0) -> np.ndarray:
    """Count finite post-mask observations along ``axis`` as an exact integer array."""
    return np.isfinite(np.asarray(stack)).sum(axis=axis, dtype="int32")


def valid_count_stats(counts: np.ndarray, low_threshold: int = LOW_VALID_SCENE_COUNT,
                      missing_value: int | None = None) -> dict:
    """Summarise integer valid-scene counts; low counts are flagged, never dropped.

    ``missing_value`` is reserved for an unavailable count tile (Section 4b uses -1).
    All other values must be finite, integer-valued and nonnegative.
    """
    arr = np.asarray(counts)
    valid = np.isfinite(arr)
    if missing_value is not None:
        valid &= arr != missing_value
    vals = np.asarray(arr[valid], dtype="float64")
    if vals.size == 0:
        return {"n_valid": 0, "min": None, "median": None, "max": None,
                "n_lt_threshold": 0, "frac_lt_threshold": None,
                "low_threshold": int(low_threshold)}
    if np.any(vals < 0) or not np.all(vals == np.floor(vals)):
        raise ValueError("valid-scene counts must be integer-valued and nonnegative")
    low = vals < int(low_threshold)
    return {
        "n_valid": int(vals.size),
        "min": int(vals.min()),
        "median": float(np.median(vals)),
        "max": int(vals.max()),
        "n_lt_threshold": int(low.sum()),
        "frac_lt_threshold": float(low.mean()),
        "low_threshold": int(low_threshold),
    }


# --- Earth Engine setup + collection / composites (steps 23-27) ------------ #
def initialize_ee() -> str:
    """Initialise Earth Engine and return the project id used.

    Loads the gitignored repo-root .env so EARTHENGINE_PROJECT is picked up; the
    user must have already run ``earthengine authenticate``.
    """
    sec2._load_project_dotenv()
    import os
    project = (os.environ.get("EARTHENGINE_PROJECT")
               or os.environ.get("GOOGLE_CLOUD_PROJECT")
               or config.EARTHENGINE_PROJECT)
    if project:
        ee.Initialize(project=project)
    else:
        ee.Initialize()
    log.info("Earth Engine: initialised (project=%s)", project or "default")
    return project or "default"


def study_region() -> "ee.Geometry":
    """The config bbox as a non-geodesic WGS84 rectangle for filtering/clipping."""
    min_lon, max_lon, min_lat, max_lat = config.BBOX_LONLAT
    return ee.Geometry.Rectangle(
        [min_lon, min_lat, max_lon, max_lat], proj="EPSG:4326", geodesic=False)


def mask_scl_ee(image: "ee.Image") -> "ee.Image":
    """Mask cloud / cloud-shadow / snow pixels using the SCL band (step 24)."""
    scl = image.select("SCL")
    keep = scl.neq(SCL_DROP_CLASSES[0])
    for cls in SCL_DROP_CLASSES[1:]:
        keep = keep.And(scl.neq(cls))
    return image.updateMask(keep)


def base_collection(region: "ee.Geometry") -> "ee.ImageCollection":
    """Unmasked warm-season S2 collection after spatial and temporal filtering only."""
    return (ee.ImageCollection(COLLECTION_ID)
            .filterBounds(region)
            .filterDate(PILOT_START, PILOT_END))


def scene_prefilter(collection: "ee.ImageCollection",
                    max_scene_cloud_pct: float = MAX_SCENE_CLOUD_PCT
                    ) -> "ee.ImageCollection":
    """Keep scenes with CLOUDY_PIXEL_PERCENTAGE strictly below the broad guard."""
    return collection.filter(
        ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", float(max_scene_cloud_pct)))


def scene_filter_totals(region: "ee.Geometry",
                        max_scene_cloud_pct: float = MAX_SCENE_CLOUD_PCT) -> dict:
    """Retrieve before/after scene totals for the documented scene-level prefilter."""
    base = base_collection(region)
    kept = scene_prefilter(base, max_scene_cloud_pct)
    return {
        "before_scene_prefilter": int(base.size().getInfo()),
        "after_scene_prefilter": int(kept.size().getInfo()),
        "max_scene_cloud_pct": float(max_scene_cloud_pct),
    }


def load_collection(region: "ee.Geometry",
                    max_scene_cloud_pct: float = MAX_SCENE_CLOUD_PCT
                    ) -> "ee.ImageCollection":
    """Load S2, keep scene cloud < threshold, then apply the PRIMARY SCL pixel mask."""
    log.info("Loading %s  bbox=%s  temporal=%s  scene_cloud<%.0f%%",
             COLLECTION_ID, config.BBOX_LONLAT, (PILOT_START, PILOT_END),
             max_scene_cloud_pct)
    log.info("  rationale: %s", SCENE_PREFILTER_RATIONALE)
    return scene_prefilter(base_collection(region), max_scene_cloud_pct).map(mask_scl_ee)


def index_collection(collection: "ee.ImageCollection",
                     product: IndexProduct) -> "ee.ImageCollection":
    """Post-SCL per-scene normalized-difference collection for one product."""
    num, den = product.bands

    def add_index(image: "ee.Image") -> "ee.Image":
        return image.normalizedDifference([num, den]).rename(product.key)

    return collection.map(add_index).select(product.key)


def index_composite(collection: "ee.ImageCollection",
                    product: IndexProduct) -> "ee.Image":
    """Steps 25-27: per-scene normalized difference, then a warm-season median."""
    return index_collection(collection, product).median().rename(product.key)


def valid_scene_count_image(collection: "ee.ImageCollection",
                            product: IndexProduct) -> "ee.Image":
    """Post-SCL per-pixel valid-scene count as an exact nonnegative uint16 image."""
    return (index_collection(collection, product)
            .count()
            .rename(product.count_band_name)
            .unmask(0)
            .toUint16())


# --- Resilient download (step 28); geemap.download_ee_image / geedim -------- #
@dataclasses.dataclass
class DownloadResult:
    """Outcome of acquiring one composite or valid-count raster."""

    product: IndexProduct
    path: Path | None                  # local GeoTIFF if downloaded to disk
    method: str                        # "geemap.download_ee_image" / "Export.image.toDrive"
    artifact: str = "composite"        # "composite" or "valid_scene_count"
    max_tile_size_mb: float | None = None
    drive_task_id: str | None = None
    drive_folder: str | None = None
    drive_filename: str | None = None

    @property
    def is_local(self) -> bool:
        return self.path is not None


def _export_to_drive(image: "ee.Image", product: IndexProduct,
                     region: "ee.Geometry", artifact: str = "composite") -> DownloadResult:
    """Last resort: start an Export.image.toDrive task and report it to the user.

    Returns a DownloadResult flagged non-local so the orchestrator skips the
    local manifest/reproject steps.
    """
    filename = (product.raw_filename if artifact == "composite"
                else product.count_raw_filename)
    drive_name = Path(filename).stem
    task = ee.batch.Export.image.toDrive(
        image=image,
        description=drive_name,
        folder=DRIVE_FOLDER,
        fileNamePrefix=drive_name,
        region=region,
        crs=config.CRS,
        scale=product.native_scale_m,
        maxPixels=int(1e13),
        fileFormat="GeoTIFF",
    )
    task.start()
    log.error("Drive FALLBACK for %s: started Export.image.toDrive task id=%s "
              "(folder=%s, file=%s.tif)", product.key, task.id, DRIVE_FOLDER, drive_name)
    return DownloadResult(
        product=product, path=None, method="Export.image.toDrive", artifact=artifact,
        drive_task_id=task.id, drive_folder=DRIVE_FOLDER,
        drive_filename=f"{drive_name}.tif",
    )


def download_composite(image: "ee.Image", product: IndexProduct,
                       region: "ee.Geometry", raw_dir: Path,
                       tile_sizes_mb: Sequence[float] = MAX_TILE_SIZES_MB,
                       scale_m: int | None = None) -> DownloadResult:
    """Download one composite to data/raw/sentinel2/ in EPSG:32612 at native scale.

    Retries with a smaller per-tile size on compute/size failure; only if every
    size fails does it fall back to Drive. ``scale_m`` overrides the download
    scale (used by the --coarse-scale smoke test).
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / product.raw_filename
    scale_m = scale_m or product.native_scale_m
    last_exc: Exception | None = None

    for mts in tile_sizes_mb:
        log.info("Downloading %s -> %s  crs=%s scale=%dm max_tile_size=%sMB",
                 product.key, out_path.name, config.CRS, scale_m, mts)
        try:
            geemap.download_ee_image(
                image, str(out_path),
                region=region,
                crs=config.CRS,
                scale=scale_m,
                resampling="bilinear",   # continuous index; bilinear on EE reproject
                overwrite=True,
                max_tile_size=mts,
                num_threads=MAX_REQUESTS,
                max_requests=MAX_REQUESTS,
            )
            log.info("Downloaded %s (%.1f MB on disk) at max_tile_size=%sMB",
                     product.key, out_path.stat().st_size / 1e6, mts)
            return DownloadResult(
                product=product, path=out_path,
                method="geemap.download_ee_image", max_tile_size_mb=mts)
        except Exception as exc:  # noqa: BLE001 - retry smaller, then Drive
            last_exc = exc
            log.warning("download %s failed at max_tile_size=%sMB: %s: %s -- "
                        "retrying with a smaller tile size",
                        product.key, mts, type(exc).__name__, exc)

    log.error("All tiled download attempts for %s failed (last: %s: %s).",
              product.key, type(last_exc).__name__, last_exc)
    return _export_to_drive(image, product, region)


def download_valid_scene_count(image: "ee.Image", product: IndexProduct,
                               region: "ee.Geometry", raw_dir: Path,
                               tile_sizes_mb: Sequence[float] = MAX_TILE_SIZES_MB,
                               overwrite: bool = False) -> DownloadResult:
    """Download an exact native-scale uint16 count raster using nearest neighbour.

    Existing valid files are reused, making ``--counts-only`` interruption-safe.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / product.count_raw_filename
    if not overwrite and _valid_cached_count_tif(out_path):
        log.info("Reusing valid-scene count %s (%.1f MB)",
                 out_path.name, out_path.stat().st_size / 1e6)
        return DownloadResult(product=product, path=out_path,
                              method="(reused local file)", artifact="valid_scene_count")

    last_exc: Exception | None = None
    for mts in tile_sizes_mb:
        log.info("Downloading %s valid-scene count -> %s  scale=%dm nearest",
                 product.key, out_path.name, product.native_scale_m)
        try:
            geemap.download_ee_image(
                image, str(out_path), region=region, crs=config.CRS,
                scale=product.native_scale_m, resampling="near", overwrite=True,
                max_tile_size=mts, num_threads=MAX_REQUESTS, max_requests=MAX_REQUESTS)
            return DownloadResult(
                product=product, path=out_path, method="geemap.download_ee_image",
                artifact="valid_scene_count", max_tile_size_mb=mts)
        except Exception as exc:  # noqa: BLE001 - retry smaller, then Drive
            last_exc = exc
            log.warning("count download %s failed at %sMB: %s: %s -- retrying smaller",
                        product.key, mts, type(exc).__name__, exc)
    log.error("All count download attempts for %s failed (last: %s: %s).",
              product.key, type(last_exc).__name__, last_exc)
    return _export_to_drive(image, product, region, artifact="valid_scene_count")


def _valid_cached_count_tif(path: Path) -> bool:
    """True when ``path`` is a readable, single-band integer GeoTIFF.

    Count rasters can compress below an arbitrary byte-size threshold, so resume
    validation checks the file structure and dtype instead of rejecting small files.
    """
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        import rasterio
        with rasterio.open(path) as src:
            return (src.count == 1 and src.width > 0 and src.height > 0
                    and np.issubdtype(np.dtype(src.dtypes[0]), np.integer))
    except Exception:  # noqa: BLE001 - an unreadable/truncated cache entry is refetched
        return False


# --- Manifest + reproject to the 70 m grid (step 28) ----------------------- #
def record_in_manifest(result: DownloadResult, project: str) -> None:
    """Append a downloaded composite/count raster with a SHA-256 sum."""
    if not result.is_local:
        return
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    method = ("warm-season median index"
              if result.artifact == "composite"
              else "post-SCL per-pixel valid-scene count; uint16; nearest")
    src = (f"Google Earth Engine {COLLECTION_ID} "
           f"(project={project}; {method}; {result.product.native_scale_m} m; EPSG:32612; "
           f"scene_cloud<{MAX_SCENE_CLOUD_PCT:g}; geemap.download_ee_image)")
    sec2.append_to_manifest([{
        "source": src,
        "dataset": DATASET_ID,
        "filename": result.path.name,
        "download_date": today,
        "checksum": f"sha256:{sec2.sha256_file(result.path)}",
    }])


def reproject_to_grid(raw_path: Path, out_path: Path, reference) -> Path:
    """Reproject + resample a composite onto the 70 m reference grid (bilinear).

    Bilinear is applied identically to NDVI (10 m) and NDMI (20 m) so the two are
    resampled consistently onto the common grid.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    da = rioxarray.open_rasterio(raw_path, masked=True).squeeze("band", drop=True)
    aligned = da.rio.reproject_match(reference, resampling=Resampling.bilinear)
    aligned = aligned.rio.write_nodata(np.nan, encoded=False)
    aligned.astype("float32").rio.to_raster(out_path, compress="deflate")
    log.info("Resampled -> %s  shape=%s (70 m grid)", out_path.name, aligned.shape)
    return out_path


def count_raster_stats(path: Path,
                       low_threshold: int = LOW_VALID_SCENE_COUNT) -> dict:
    """Validate/summarise an integer nonnegative count raster block-by-block."""
    import rasterio

    hist = np.zeros(1, dtype="int64")
    with rasterio.open(path) as src:
        if not np.issubdtype(np.dtype(src.dtypes[0]), np.integer):
            raise AssertionError(f"{path.name}: count dtype {src.dtypes[0]} is not integer")
        nodata = src.nodata
        dtype_max = np.iinfo(np.dtype(src.dtypes[0])).max
        for _, window in src.block_windows(1):
            vals = np.asarray(src.read(1, window=window), dtype="int64").ravel()
            # Zero is a valid count and must never be discarded even if a downloader
            # labels 0 as nodata. Only impossible negative/max sentinels are removed.
            if nodata is not None and (nodata < 0 or nodata == dtype_max):
                vals = vals[vals != int(nodata)]
            if vals.size == 0:
                continue
            if np.any(vals < 0):
                raise AssertionError(f"{path.name}: valid-scene count contains negatives")
            bincount = np.bincount(vals)
            if bincount.size > hist.size:
                hist = np.pad(hist, (0, bincount.size - hist.size))
            hist[:bincount.size] += bincount

    n = int(hist.sum())
    if n == 0:
        return valid_count_stats(np.array([], dtype="int32"), low_threshold)
    present = np.flatnonzero(hist)
    cumulative = np.cumsum(hist)
    # Exact conventional median from the two central order statistics.
    left_rank = (n - 1) // 2 + 1
    right_rank = n // 2 + 1
    left = int(np.searchsorted(cumulative, left_rank, side="left"))
    right = int(np.searchsorted(cumulative, right_rank, side="left"))
    n_low = int(hist[:int(low_threshold)].sum())
    return {
        "n_valid": n,
        "min": int(present[0]),
        "median": (left + right) / 2.0,
        "max": int(present[-1]),
        "n_lt_threshold": n_low,
        "frac_lt_threshold": n_low / n,
        "low_threshold": int(low_threshold),
    }


def reproject_count_to_grid(raw_path: Path, out_path: Path, flag_path: Path,
                            reference, product: IndexProduct,
                            scene_totals: dict | None = None) -> tuple[Path, Path]:
    """Nearest-sample an integer count onto 70 m and write a separate <3 flag.

    The median index raster is deliberately untouched; the flag is diagnostic only.
    """
    import rasterio

    out_path.parent.mkdir(parents=True, exist_ok=True)
    da = rioxarray.open_rasterio(raw_path, masked=False).squeeze("band", drop=True)
    aligned = da.rio.reproject_match(reference, resampling=Resampling.nearest)
    values = np.asarray(aligned.values)
    if np.any(~np.isfinite(values)) or np.any(values < 0) \
            or not np.all(values == np.floor(values)):
        raise AssertionError(f"{raw_path.name}: reprojected count is not finite/nonnegative integer")
    if np.max(values, initial=0) > np.iinfo("uint16").max:
        raise AssertionError(f"{raw_path.name}: count exceeds uint16")

    count_da = aligned.copy(data=values.astype("uint16"))
    count_da = count_da.rio.write_nodata(None, encoded=False)
    count_da.rio.to_raster(out_path, compress="deflate")
    flag = (values < LOW_VALID_SCENE_COUNT).astype("uint8")
    flag_da = aligned.copy(data=flag).rio.write_nodata(None, encoded=False)
    flag_da.rio.to_raster(flag_path, compress="deflate")

    tags = {
        "source_band": product.count_band_name,
        "resampling": "nearest",
        "count_semantics": "post-SCL valid index observations",
        "low_count_rule": f"count < {LOW_VALID_SCENE_COUNT}; diagnostic only; index not masked",
        "scene_cloud_keep_rule": (
            f"CLOUDY_PIXEL_PERCENTAGE < "
            f"{(scene_totals or {}).get('max_scene_cloud_pct', MAX_SCENE_CLOUD_PCT):g}"),
    }
    if scene_totals:
        tags.update({
            "scenes_before_prefilter": str(scene_totals["before_scene_prefilter"]),
            "scenes_after_prefilter": str(scene_totals["after_scene_prefilter"]),
        })
    for path in (out_path, flag_path):
        with rasterio.open(path, "r+") as dst:
            dst.update_tags(**tags)
    log.info("Count QC -> %s; low-count flag -> %s (nearest; index unchanged)",
             out_path.name, flag_path.name)
    return out_path, flag_path


# --- Figures (deliverable: high-NDVI overlay + index maps) ----------------- #
# Well-known IRRIGATED / tree-lined Phoenix landmarks (lon, lat), used only as
# confirmation anchors for the NDVI overlay. Deliberately excludes desert parks
# and open water (not green). High NDVI alone is not proof of trees (Section 10
# pitfall) -- the canopy-fraction layer does the actual isolation.
KNOWN_GREEN_LANDMARKS = [
    ("Encanto Park & Golf", -112.0889, 33.4726),
    ("Encanto-Palmcroft (historic, tree-lined)", -112.0850, 33.4790),
    ("Papago Golf Course", -111.9405, 33.4585),
    ("Arizona Country Club", -111.9610, 33.5010),
    ("Arcadia / Grand Canal (tree-lined)", -111.9850, 33.4900),
]


def _landmarks_in_grid_xy():
    """Project the known green landmarks into EPSG:32612 metres for overlaying."""
    from pyproj import Transformer
    tf = Transformer.from_crs("EPSG:4326", config.CRS, always_xy=True)
    left, bottom, right, top = config.GRID_BOUNDS
    out = []
    for name, lon, lat in KNOWN_GREEN_LANDMARKS:
        x, y = tf.transform(lon, lat)
        if left <= x <= right and bottom <= y <= top:   # only those inside the grid
            out.append((name, x, y))
    return out


def _zoom_window(landmarks, pad_m: float = 3500.0):
    """Bounding box (in grid metres) around the landmarks, padded and clamped."""
    left, bottom, right, top = config.GRID_BOUNDS
    if not landmarks:
        return left, bottom, right, top
    xs = [x for _, x, y in landmarks]
    ys = [y for _, x, y in landmarks]
    return (max(left, min(xs) - pad_m), max(bottom, min(ys) - pad_m),
            min(right, max(xs) + pad_m), min(top, max(ys) + pad_m))


def make_ndvi_overlay_figure(ndvi_grid_path: Path, figures_dir: Path) -> Path:
    """Visual-check deliverable: high-NDVI overlay vs known parks / tree lines.

    Confirms the index behaves sensibly; it does not isolate canopy (Section 10
    pitfall: irrigated grass and cropland are green too).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    figures_dir.mkdir(parents=True, exist_ok=True)
    ndvi = rioxarray.open_rasterio(ndvi_grid_path, masked=True).squeeze("band", drop=True)
    arr = ndvi.values.astype("float64")
    high = high_veg_mask(arr, HIGH_NDVI_THRESHOLD)
    overlay = np.where(high, 1.0, np.nan)
    frac = float(high.sum()) / float(np.isfinite(arr).sum() or 1)
    area_median = float(np.nanmedian(arr))

    left, bottom, right, top = config.GRID_BOUNDS
    extent = (left, right, bottom, top)
    green = ListedColormap(["#1a9641"])
    landmarks = _landmarks_in_grid_xy()

    # Per-landmark neighbourhood-peak NDVI over a 3x3 window (~210 m) -- a park is
    # larger than one 70 m cell and allows for pixel slop; shown in the legend.
    xs, ys = ndvi.x.values, ndvi.y.values

    def _nb_peak(x, y):
        xi = int(np.argmin(np.abs(xs - x)))
        yi = int(np.argmin(np.abs(ys - y)))
        nb = arr[max(0, yi - 1):yi + 2, max(0, xi - 1):xi + 2]
        return float(np.nanmax(nb)) if np.isfinite(nb).any() else float("nan")

    peaks = [_nb_peak(x, y) for _, x, y in landmarks]

    fig, axes = plt.subplots(1, 2, figsize=(15, 6.8), constrained_layout=True)

    # (a) Full study area: continuous NDVI for context.
    ax = axes[0]
    im = ax.imshow(arr, extent=extent, origin="upper", cmap=ps.CMAP["vegetation"],
                   vmin=0.0, vmax=0.9)
    zx0, zy0, zx1, zy1 = _zoom_window(landmarks)
    ax.add_patch(plt.Rectangle((zx0, zy0), zx1 - zx0, zy1 - zy0, fill=False,
                               edgecolor="black", linewidth=1.3, linestyle="--"))
    ax.set_title("Sentinel-2 warm-season median NDVI (70 m), full study area\n"
                 f"Phoenix {PILOT_START}..{PILOT_END}  (dashed box = zoom at right)")
    ax.set_xlabel("Easting (m, EPSG:32612)"); ax.set_ylabel("Northing (m, EPSG:32612)")
    fig.colorbar(im, ax=ax, label="NDVI", shrink=0.85)

    # (b) Zoom on central Phoenix: high-NDVI overlay + numbered park markers.
    ax = axes[1]
    ax.imshow(arr, extent=extent, origin="upper", cmap="Greys_r", vmin=-0.2, vmax=0.9)
    ax.imshow(overlay, extent=extent, origin="upper", cmap=green,
              vmin=0, vmax=1, alpha=0.9)
    for i, (name, x, y) in enumerate(landmarks, start=1):
        ax.plot(x, y, marker="o", markersize=10, markerfacecolor="none",
                markeredgecolor="#cc0000", markeredgewidth=2.2)
        ax.annotate(str(i), (x, y), color="#cc0000", fontsize=9, fontweight="bold",
                    ha="center", va="center")
    handles = [plt.Line2D([], [], marker="o", linestyle="none", markerfacecolor="none",
                          markeredgecolor="#cc0000", markersize=8,
                          label=f"{i}. {name}  (NDVI {peak:.2f})")
               for i, ((name, x, y), peak) in enumerate(zip(landmarks, peaks), start=1)]
    handles.append(plt.Line2D([], [], marker="s", linestyle="none", color="#1a9641",
                              markersize=8, label=f"NDVI >= {HIGH_NDVI_THRESHOLD:g} (high veg)"))
    ax.legend(handles=handles, loc="upper left", fontsize=7.5, framealpha=0.92,
              title=f"area-median NDVI = {area_median:.2f}", title_fontsize=8)
    ax.set_xlim(zx0, zx1); ax.set_ylim(zy0, zy1)
    ax.set_title(f"High-NDVI pixels over central Phoenix "
                 f"({100 * frac:.1f}% of valid pixels area-wide)\n"
                 "green = high NDVI; numbered rings = known parks / golf / tree-lined "
                 "areas (legend gives each one's peak NDVI)")
    ax.set_xlabel("Easting (m, EPSG:32612)"); ax.set_ylabel("Northing (m, EPSG:32612)")

    out = figures_dir / "sentinel2_ndvi_highveg_overlay.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote visual check -> %s  (high-NDVI on %.1f%% of valid pixels)",
             out.name, 100 * frac)
    return out


def make_index_map_figure(grid_path: Path, product: IndexProduct,
                          figures_dir: Path) -> Path:
    """Simple QA map of one index composite on the 70 m grid."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    da = rioxarray.open_rasterio(grid_path, masked=True).squeeze("band", drop=True)
    arr = da.values.astype("float64")
    left, bottom, right, top = config.GRID_BOUNDS
    extent = (left, right, bottom, top)
    fig, ax = plt.subplots(figsize=(7, 6))
    if product.key == "ndvi":
        # vegetation greenness: sequential greens (white/pale at 0 = no vegetation)
        im = ax.imshow(arr, extent=extent, origin="upper",
                       cmap=ps.CMAP["vegetation"], vmin=0.0, vmax=0.9)
    else:
        # NDMI signed moisture index: diverging brown<->green with WHITE exactly at 0
        im = ax.imshow(arr, extent=extent, origin="upper",
                       cmap=ps.CMAP["ndmi"], norm=ps.diverging_norm(arr, symmetric=False))
    ax.set_title(f"Sentinel-2 warm-season median {product.key.upper()} (70 m)\n"
                 f"native {product.native_scale_m} m  -  Phoenix "
                 f"{PILOT_START}..{PILOT_END}")
    ax.set_xlabel("Easting (m, EPSG:32612)"); ax.set_ylabel("Northing (m, EPSG:32612)")
    fig.colorbar(im, ax=ax, label=product.key.upper())
    out = figures_dir / f"sentinel2_{product.key}_median_map.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote %s map -> %s", product.key, out.name)
    return out


_COVERAGE_NOTE_TEMPLATE = """# Sentinel-2 scene-coverage diagnostics

The 60% scene filter is a broad prefilter. Per-pixel SCL masking is the primary
cloud/shadow/snow decision. Counts below three are flagged for review and never used to
mask NDVI or NDMI.

<!-- SECTION4_STATIC_START -->
Section 4 static-composite counts have not been retrieved yet.
<!-- SECTION4_STATIC_END -->

<!-- SECTION4B_TIMESERIES_START -->
Section 4b time-series counts have not been retrieved yet.
<!-- SECTION4B_TIMESERIES_END -->
"""


def replace_coverage_note_section(text: str, section: str, body: str) -> str:
    """Replace one marker-delimited coverage-note section without touching the other."""
    start = f"<!-- {section}_START -->"
    end = f"<!-- {section}_END -->"
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError(f"coverage note must contain exactly one {start} and {end}")
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    return f"{before}{start}\n{body.strip()}\n{end}{after}"


def update_coverage_note(section: str, body: str,
                         path: Path = COVERAGE_NOTE) -> Path:
    """Update one generated section of the shared Section 4/4b coverage note."""
    text = path.read_text(encoding="utf-8") if path.exists() else _COVERAGE_NOTE_TEMPLATE
    updated = replace_coverage_note_section(text, section, body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return path


def _stats_markdown(stats: dict | None) -> tuple[str, str, str, str]:
    if not stats or not stats.get("n_valid"):
        return "pending", "pending", "pending", "pending"
    return (str(stats["min"]), f"{stats['median']:.1f}", str(stats["max"]),
            f"{stats['n_lt_threshold']:,} ({100 * stats['frac_lt_threshold']:.3f}%)")


def render_static_coverage_note(scene_totals: dict | None,
                                count_details: dict[str, dict]) -> str:
    """Markdown body for the static-composite section of the coverage note."""
    if scene_totals:
        before_after = (
            f"The warm-season collection contained **{scene_totals['before_scene_prefilter']:,}** "
            f"scenes before the scene prefilter and **{scene_totals['after_scene_prefilter']:,}** "
            f"after keeping `CLOUDY_PIXEL_PERCENTAGE < {scene_totals['max_scene_cloud_pct']:g}`.")
    else:
        before_after = ("Before/after scene totals are pending an Earth Engine metadata query; "
                        "they cannot be reconstructed from median-composite GeoTIFFs.")
    rows = []
    for key in ("ndvi", "ndmi"):
        d = count_details.get(key, {})
        mn, med, mx, low = _stats_markdown(d.get("grid_stats"))
        rows.append(
            f"| {key.upper()} | {d.get('status', 'pending')} | {mn} | {med} | {mx} | {low} |")
    return "\n".join([
        "## Section 4 warm-season composites",
        "",
        SCENE_PREFILTER_RATIONALE,
        "",
        before_after,
        "",
        "| Index | count artifact | min | median | max | 70 m pixels with count <3 |",
        "|---|---|---:|---:|---:|---:|",
        *rows,
        "",
        "Native count GeoTIFFs are exact nonnegative integers. The clearly named 70 m count "
        "rasters use nearest-neighbour sampling, with separate uint8 `<3` flags. NDVI/NDMI "
        "values are retained regardless of the flag.",
    ])


# --- Orchestration / CLI --------------------------------------------------- #
def process_index(product: IndexProduct, collection: "ee.ImageCollection",
                  region: "ee.Geometry", reference, project: str,
                  skip_download: bool, coarse_scale: int | None,
                  counts_only: bool = False, scene_totals: dict | None = None
                  ) -> tuple[DownloadResult | None, DownloadResult | None, dict]:
    """Acquire one index plus its post-mask valid-count diagnostics."""
    raw_dir = config.RAW_DIR / RAW_SUBDIR
    raw_path = raw_dir / product.raw_filename
    composite_result: DownloadResult | None = None
    if not counts_only:
        if skip_download:
            if not raw_path.exists():
                raise SystemExit(f"--skip-download: {raw_path} not found; run a full "
                                 "download first.")
            composite_result = DownloadResult(
                product=product, path=raw_path, method="(reused local file)")
            log.info("--skip-download: reusing %s", raw_path.name)
        else:
            image = index_composite(collection, product)
            composite_result = download_composite(
                image, product, region, raw_dir,
                scale_m=coarse_scale or product.native_scale_m)
            if composite_result.is_local and not coarse_scale:
                record_in_manifest(composite_result, project)
        if composite_result.is_local:
            reproject_to_grid(
                composite_result.path, config.INTERIM_DIR / product.grid_filename, reference)

    count_result: DownloadResult | None = None
    details: dict = {"status": "pending Earth Engine valid-count retrieval"}
    count_raw = raw_dir / product.count_raw_filename
    if coarse_scale is not None:
        details["status"] = "skipped for coarse-scale smoke test"
        log.info("Count QC for %s skipped in --coarse-scale smoke test; native filename must "
                 "remain an exact native-scale product.", product.key)
    elif skip_download:
        if count_raw.exists():
            count_result = DownloadResult(
                product=product, path=count_raw, method="(reused local file)",
                artifact="valid_scene_count")
        else:
            log.warning("No cached %s count raster; the median composite cannot reconstruct "
                        "per-pixel N. Run --counts-only with Earth Engine.", product.key)
    else:
        count_image = valid_scene_count_image(collection, product)
        count_result = download_valid_scene_count(
            count_image, product, region, raw_dir, overwrite=False)
        if count_result.is_local and count_result.method != "(reused local file)":
            record_in_manifest(count_result, project)

    if count_result is not None:
        if count_result.is_local:
            count_grid = config.INTERIM_DIR / product.count_grid_filename
            low_flag = config.INTERIM_DIR / product.low_count_flag_grid_filename
            reproject_count_to_grid(
                count_result.path, count_grid, low_flag, reference, product, scene_totals)
            details.update({
                "status": f"available: `{count_grid.name}` + `{low_flag.name}`",
                "native_path": count_result.path,
                "grid_path": count_grid,
                "flag_path": low_flag,
                "native_stats": count_raster_stats(count_result.path),
                "grid_stats": count_raster_stats(count_grid),
            })
        else:
            details["status"] = f"Drive fallback pending: `{count_result.drive_filename}`"
    return composite_result, count_result, details


def run(indices: Sequence[str] = ("ndvi", "ndmi"), skip_download: bool = False,
        coarse_scale: int | None = None, max_scene_cloud_pct: float = MAX_SCENE_CLOUD_PCT,
        counts_only: bool = False
        ) -> list[DownloadResult]:
    if skip_download and counts_only:
        raise SystemExit("--skip-download and --counts-only are mutually exclusive")
    config.ensure_dirs()
    project = "default"
    region = None
    collection = None
    totals = None
    if not skip_download:
        project = initialize_ee()
        region = study_region()
        totals = scene_filter_totals(region, max_scene_cloud_pct)
        collection = load_collection(region, max_scene_cloud_pct)
        log.info("Scene totals: before prefilter=%d; after keep CLOUDY_PIXEL_PERCENTAGE<%.0f=%d",
                 totals["before_scene_prefilter"], max_scene_cloud_pct,
                 totals["after_scene_prefilter"])

    reference = rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)

    results: list[DownloadResult] = []
    count_results: list[DownloadResult] = []
    count_details: dict[str, dict] = {}
    for key in indices:
        composite, count, details = process_index(
            PRODUCTS[key], collection, region, reference, project, skip_download,
            coarse_scale, counts_only=counts_only, scene_totals=totals)
        if composite is not None:
            results.append(composite)
        if count is not None:
            count_results.append(count)
        count_details[key] = details

    # Visual check (deliverable). Needs the NDVI composite on the 70 m grid.
    ndvi_res = next((r for r in results if r.product.key == "ndvi" and r.is_local), None)
    if ndvi_res is not None:
        ndvi_grid = config.INTERIM_DIR / NDVI_PRODUCT.grid_filename
        make_ndvi_overlay_figure(ndvi_grid, config.FIGURES_DIR)
        make_index_map_figure(ndvi_grid, NDVI_PRODUCT, config.FIGURES_DIR)
    ndmi_res = next((r for r in results if r.product.key == "ndmi" and r.is_local), None)
    if ndmi_res is not None:
        make_index_map_figure(config.INTERIM_DIR / NDMI_PRODUCT.grid_filename,
                              NDMI_PRODUCT, config.FIGURES_DIR)

    note_body = render_static_coverage_note(totals, count_details)
    update_coverage_note("SECTION4_STATIC", note_body)
    _report(results, count_results, counts_only)
    return results


def _report(results: Sequence[DownloadResult], count_results: Sequence[DownloadResult],
            counts_only: bool = False) -> None:
    all_results = [*results, *count_results]
    drive = [r for r in all_results if not r.is_local]
    log.info("Section 4 complete: %d composite(s), %d valid-count artifact(s); mode=%s.",
             len(results), len(count_results), "counts-only" if counts_only else "full")
    if drive:
        log.error("=" * 70)
        log.error("MANUAL STEP REQUIRED -- %d artifact(s) fell back to Google Drive:",
                  len(drive))
        for r in drive:
            log.error("  * %s: grab '%s' from Drive folder '%s' (task id=%s), drop it "
                      "into data/raw/sentinel2/, then re-run with --skip-download.",
                      r.product.key, r.drive_filename, r.drive_folder, r.drive_task_id)
        log.error("=" * 70)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 4 - Sentinel-2 NDVI/NDMI warm-season composites (no manual download).")
    p.add_argument("--indices", default="ndvi,ndmi",
                   help="comma list of indices to process (default ndvi,ndmi).")
    p.add_argument("--skip-download", action="store_true",
                   help="reuse composites and any count rasters already in data/raw/sentinel2/.")
    p.add_argument("--counts-only", action="store_true",
                   help="retrieve/reuse only post-SCL valid-scene counts (resumable); do not "
                        "redownload median composites.")
    p.add_argument("--coarse-scale", type=int, default=None,
                   help="(smoke test) override download scale in metres for speed.")
    p.add_argument("--max-scene-cloud-pct", type=float, default=MAX_SCENE_CLOUD_PCT,
                   help="broad prefilter: keep scenes with CLOUDY_PIXEL_PERCENTAGE < this; "
                        "drop >= this (default %(default)s). Per-pixel SCL masking is primary.")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    run(
        indices=tuple(s.strip() for s in args.indices.split(",") if s.strip()),
        skip_download=args.skip_download,
        coarse_scale=args.coarse_scale,
        max_scene_cloud_pct=args.max_scene_cloud_pct,
        counts_only=args.counts_only,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
