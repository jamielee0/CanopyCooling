#!/usr/bin/env python3
"""Section 4 - Acquire Sentinel-2 vegetation (NDVI) and moisture (NDMI) indices.

Implements steps 23-28 of the Data Acquisition & Analysis Protocol for the
Phoenix pilot. Like Sections 2-3 the whole section runs from this single module
so the result is reproducible end to end (protocol standing rule: "every figure
and every number must be reproducible from the saved code").

NO MANUAL DOWNLOAD. The two warm-season median composites are pulled straight to
local disk with ``geemap.download_ee_image`` (geedim under the hood), which tiles
the request under the Earth Engine size limit and stitches the tiles back into a
single GeoTIFF. There is NO ``Export.image.toDrive`` round-trip on the happy path;
the Drive export exists only as a last-resort fallback (see ``download_composite``).

Pipeline (steps 23-28)
----------------------
23. Load COPERNICUS/S2_SR_HARMONIZED, filtered to the config bbox and the pilot
    window 2023-06-01..2023-09-30.
24. Drop high-cloud SCENES (CLOUDY_PIXEL_PERCENTAGE < MAX_SCENE_CLOUD_PCT), then
    mask cloud / cloud-shadow / snow PIXELS with the SCL scene-classification band.
25. Per scene NDVI = (B8 - B4) / (B8 + B4)   -- high for dense, healthy vegetation.
26. Per scene NDMI = (B8 - B11) / (B8 + B11) -- tracks canopy water content.
27. Reduce to a warm-season MEDIAN composite of NDVI and a SEPARATE median
    composite of NDMI (the median is robust to residual cloud and noise).
28. Download both composites to data/raw/sentinel2/ in EPSG:32612 at their native
    scale (NDVI 10 m; NDMI 20 m), record them in data/manifest.csv with checksums,
    then reproject + resample BOTH to the 70 m Section-1 reference grid (bilinear,
    per Section 9 step 48) into data/interim/.

RESOLUTION CAVEAT (protocol Section 4 common pitfall)
-----------------------------------------------------
The SWIR band B11 is NATIVE 20 m, coarser than the 10 m visible/NIR bands. NDMI
is therefore a 20 m product and is downloaded at 20 m -- it is NOT presented as a
true 10 m product. NDVI is a genuine 10 m product (B4 and B8 are both 10 m). Both
are then resampled CONSISTENTLY (bilinear) onto the common 70 m grid.

A note on COPERNICUS/S2_SR_HARMONIZED: the *harmonized* collection shifts the
post-2022 (processing-baseline 04.00) reflectance back onto the old offset so the
whole archive is on one scale. Because NDVI/NDMI are normalized differences, a
consistent additive offset cancels -- using HARMONIZED keeps the indices
comparable across the season without any manual offset handling.

Run (canopy env, Earth Engine authenticated):
    python src/section4_sentinel2_indices.py                # full run
    python src/section4_sentinel2_indices.py --indices ndvi # NDVI only
    python src/section4_sentinel2_indices.py --skip-download # reuse data/raw files
    python src/section4_sentinel2_indices.py --coarse-scale 100  # quick smoke test
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

# Heavy geospatial / EE libraries. The pure-numpy logic below (index formula, SCL
# mask, high-veg mask, product config) does not touch them, so it stays
# unit-testable without the geo / EE stack installed (see test_section4_*).
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

log = logging.getLogger("section4")

# --------------------------------------------------------------------------- #
# Confirmed collection constants (logged at run time).
# --------------------------------------------------------------------------- #
COLLECTION_ID = "COPERNICUS/S2_SR_HARMONIZED"
DATASET_ID = COLLECTION_ID                       # recorded in the manifest
PILOT_START, PILOT_END = config.PILOT_WINDOW     # ("2023-06-01", "2023-09-30")

# A SCENE is dropped before pixel masking if more than this % of it is cloudy
# (protocol step 24: "keep scenes with low cloud cover").
MAX_SCENE_CLOUD_PCT = 60.0

# Sentinel-2 Scene Classification Layer (SCL) class codes. Per step 24 we mask
# cloud, cloud-shadow and snow pixels; thin cirrus is grouped with cloud.
SCL_CLASS_NAMES = {
    0: "no_data", 1: "saturated_or_defective", 2: "dark_area_pixels",
    3: "cloud_shadow", 4: "vegetation", 5: "not_vegetated", 6: "water",
    7: "unclassified", 8: "cloud_medium_probability",
    9: "cloud_high_probability", 10: "thin_cirrus", 11: "snow_or_ice",
}
# Classes set to missing per step 24 (cloud / cloud-shadow / snow).
SCL_DROP_CLASSES = (3, 8, 9, 10, 11)

# Per-tile size ladder (MB) for the resilient download. On a compute/size
# failure we retry with progressively smaller tiles before the Drive fallback
# (protocol step 28 / user instruction). The ladder starts at 8 MB because a
# 10 m NDVI tile larger than that overflows Earth Engine's per-request memory
# when reducing a median over ~182 scenes ("User memory limit exceeded"); 8 MB
# tiles clear it. geedim's own default is ~4 MB.
MAX_TILE_SIZES_MB = (8, 4, 2, 1)

# Cap concurrent Earth Engine tile requests. geedim's default (32) stampedes the
# EE backend into HTTP 429 (rate-limit) storms for a heavy median-over-182-scenes
# composite, and exceeds the HTTP connection-pool size (10). Holding concurrency
# at <=10 keeps requests steady, avoids the 429 retry/backoff thrash, and silences
# the urllib3 pool warnings -- a few steady requests beat a throttled stampede.
MAX_REQUESTS = 8

# High-vegetation threshold for the visual-check overlay. Matches the
# pre-registered tree-dominated NDVI threshold (protocol step 52, start at 0.5).
HIGH_NDVI_THRESHOLD = 0.5

RAW_SUBDIR = "sentinel2"                          # data/raw/sentinel2/
DRIVE_FOLDER = "canopy_section4"                  # only used by the fallback


# =========================================================================== #
# Product configuration  (pure data; no geo / EE deps)
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class IndexProduct:
    """One normalized-difference index to acquire in Section 4.

    bands = (numerator_band, denominator_band) for the EE ``normalizedDifference``
    so the value is (num - den) / (num + den). native_scale_m is the coarsest
    input band's resolution -- the scale the composite is DOWNLOADED at, kept
    honest (NDMI is a 20 m product, never dressed up as 10 m).
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


# =========================================================================== #
# Pure index / mask logic  (numpy; unit-tested without the geo or EE stack)
# --------------------------------------------------------------------------- #
def normalized_difference(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """(num - den) / (num + den), NaN where the sum is zero (matches EE polarity).

    A reference implementation of the index EE computes server-side, so the
    formula itself is testable without Earth Engine.
    """
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


# =========================================================================== #
# Earth Engine setup + collection / composites  (steps 23-27; needs ee)
# --------------------------------------------------------------------------- #
def initialize_ee() -> str:
    """Initialise Earth Engine, returning the project id used.

    Loads the gitignored repo-root .env first (same helper as Section 2) so a
    fresh shell picks up EARTHENGINE_PROJECT without exporting it by hand. The
    user is expected to have already run ``earthengine authenticate``.
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


def load_collection(region: "ee.Geometry",
                    max_scene_cloud_pct: float = MAX_SCENE_CLOUD_PCT
                    ) -> "ee.ImageCollection":
    """Steps 23-24: load S2 SR (harmonized), drop high-cloud scenes, SCL-mask."""
    log.info("Loading %s  bbox=%s  temporal=%s  scene_cloud<%.0f%%",
             COLLECTION_ID, config.BBOX_LONLAT, (PILOT_START, PILOT_END),
             max_scene_cloud_pct)
    return (ee.ImageCollection(COLLECTION_ID)
            .filterBounds(region)
            .filterDate(PILOT_START, PILOT_END)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_scene_cloud_pct))
            .map(mask_scl_ee))


def index_composite(collection: "ee.ImageCollection",
                    product: IndexProduct) -> "ee.Image":
    """Steps 25-27: per-scene normalized difference, then a warm-season median."""
    num, den = product.bands

    def add_index(image: "ee.Image") -> "ee.Image":
        return image.normalizedDifference([num, den]).rename(product.key)

    return collection.map(add_index).select(product.key).median().rename(product.key)


# =========================================================================== #
# Resilient download  (step 28) -- geemap.download_ee_image, geedim under the hood
# --------------------------------------------------------------------------- #
@dataclasses.dataclass
class DownloadResult:
    """Outcome of acquiring one composite (local success or Drive fallback)."""

    product: IndexProduct
    path: Path | None                  # local GeoTIFF if downloaded to disk
    method: str                        # "geemap.download_ee_image" / "Export.image.toDrive"
    max_tile_size_mb: float | None = None
    drive_task_id: str | None = None
    drive_folder: str | None = None
    drive_filename: str | None = None

    @property
    def is_local(self) -> bool:
        return self.path is not None


def _export_to_drive(image: "ee.Image", product: IndexProduct,
                     region: "ee.Geometry") -> DownloadResult:
    """Last resort: start an Export.image.toDrive task and report it to the user.

    Only reached if every tiled local download attempt failed. Returns a
    DownloadResult flagged non-local so the orchestrator skips the local
    manifest/reproject steps and tells the user to fetch the files from Drive.
    """
    drive_name = f"s2_{product.key}_warmseason_median_2023_{product.native_scale_m}m"
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
        product=product, path=None, method="Export.image.toDrive",
        drive_task_id=task.id, drive_folder=DRIVE_FOLDER,
        drive_filename=f"{drive_name}.tif",
    )


def download_composite(image: "ee.Image", product: IndexProduct,
                       region: "ee.Geometry", raw_dir: Path,
                       tile_sizes_mb: Sequence[float] = MAX_TILE_SIZES_MB,
                       scale_m: int | None = None) -> DownloadResult:
    """Download one composite to data/raw/sentinel2/ in EPSG:32612 at native scale.

    Tiles+stitches via geemap.download_ee_image (geedim). On a compute/size
    failure, retries with a smaller per-tile size; only if every size fails does
    it fall back to Export.image.toDrive (step 28 / user instruction). ``scale_m``
    overrides the download scale (only used by the --coarse-scale smoke test).
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
                # Concurrency caps (forwarded to geedim) -- prevent the 429 storm.
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


# =========================================================================== #
# Manifest + reproject to the 70 m grid  (step 28)
# --------------------------------------------------------------------------- #
def record_in_manifest(result: DownloadResult, project: str) -> None:
    """Append the downloaded composite to data/manifest.csv with a SHA-256 sum."""
    if not result.is_local:
        return
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    src = (f"Google Earth Engine {COLLECTION_ID} "
           f"(project={project}; warm-season median; {result.product.native_scale_m} m; "
           f"EPSG:32612; geemap.download_ee_image)")
    sec2.append_to_manifest([{
        "source": src,
        "dataset": DATASET_ID,
        "filename": result.path.name,
        "download_date": today,
        "checksum": f"sha256:{sec2.sha256_file(result.path)}",
    }])


def reproject_to_grid(raw_path: Path, out_path: Path, reference) -> Path:
    """Reproject + resample a composite onto the 70 m reference grid (bilinear).

    Bilinear matches the protocol's rule for continuous quantities (Section 9
    step 48) and is applied identically to NDVI (10 m) and NDMI (20 m) so the two
    are resampled CONSISTENTLY onto the common grid.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    da = rioxarray.open_rasterio(raw_path, masked=True).squeeze("band", drop=True)
    aligned = da.rio.reproject_match(reference, resampling=Resampling.bilinear)
    aligned = aligned.rio.write_nodata(np.nan, encoded=False)
    aligned.astype("float32").rio.to_raster(out_path, compress="deflate")
    log.info("Resampled -> %s  shape=%s (70 m grid)", out_path.name, aligned.shape)
    return out_path


# =========================================================================== #
# Figures  (deliverable: high-NDVI overlay + index maps)
# --------------------------------------------------------------------------- #
# Well-known IRRIGATED / tree-lined Phoenix landmarks (lon, lat) -- golf courses,
# lush historic districts and a canal tree-corridor. Each was confirmed against
# the composite to sit well above the desert-urban background (see the per-marker
# NDVI shown in the figure legend). Deliberately excludes desert parks (e.g.
# Papago's rock/cactus) and open water (Tempe Town Lake), which are NOT green.
# NB (Section 10 pitfall): high NDVI alone is not proof of trees -- well-watered
# grass and cropland are green too -- so these are confirmation anchors, not a
# substitute for the canopy-fraction layer.
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
    """Visual check: high-NDVI overlay confirmed against known parks / tree lines.

    This is the Section-4 deliverable confirmation figure. Left: the whole study
    area for context. Right: a zoom on central Phoenix where high-NDVI pixels are
    overlaid in green and numbered markers locate well-known parks / tree-lined
    areas -- so the reviewer can see the green pixels land on them.

    NB (Section 10 pitfall): high NDVI alone is not proof of trees -- irrigated
    grass and cropland are green too -- so this confirms the index behaves
    sensibly, it does not yet isolate canopy (that needs Section 5's tree-cover).
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

    # Per-landmark neighbourhood-peak NDVI (3x3 ~ 210 m, allows for pixel slop and
    # the fact that a park is larger than one 70 m cell) -- shown in the legend so
    # the confirmation is quantitative, not just visual.
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
    im = ax.imshow(arr, extent=extent, origin="upper", cmap="RdYlGn",
                   vmin=-0.2, vmax=0.9)
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
    cmap = "RdYlGn" if product.key == "ndvi" else "BrBG"

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(arr, extent=extent, origin="upper", cmap=cmap,
                   vmin=-0.4, vmax=0.9)
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


# =========================================================================== #
# Orchestration / CLI
# --------------------------------------------------------------------------- #
def process_index(product: IndexProduct, collection: "ee.ImageCollection",
                  region: "ee.Geometry", reference, project: str,
                  skip_download: bool, coarse_scale: int | None) -> DownloadResult:
    """Acquire one index: composite -> download -> manifest -> 70 m grid."""
    raw_dir = config.RAW_DIR / RAW_SUBDIR
    raw_path = raw_dir / product.raw_filename

    if skip_download:
        if not raw_path.exists():
            raise SystemExit(f"--skip-download: {raw_path} not found; run a full "
                             "download first.")
        result = DownloadResult(product=product, path=raw_path,
                                method="(reused local file)")
        log.info("--skip-download: reusing %s", raw_path.name)
    else:
        image = index_composite(collection, product)
        result = download_composite(image, product, region, raw_dir,
                                    scale_m=coarse_scale or product.native_scale_m)
        # A coarse-scale smoke-test raster is not the real native product, so it
        # is reprojected/figured to exercise the wiring but kept out of the manifest.
        if result.is_local and not coarse_scale:
            record_in_manifest(result, project)

    if not result.is_local:
        return result  # Drive fallback: nothing local to reproject yet

    grid_path = config.INTERIM_DIR / product.grid_filename
    reproject_to_grid(result.path, grid_path, reference)
    return result


def run(indices: Sequence[str] = ("ndvi", "ndmi"), skip_download: bool = False,
        coarse_scale: int | None = None, max_scene_cloud_pct: float = MAX_SCENE_CLOUD_PCT
        ) -> list[DownloadResult]:
    config.ensure_dirs()
    project = "default"
    region = None
    collection = None
    if not skip_download:
        project = initialize_ee()
        region = study_region()
        collection = load_collection(region, max_scene_cloud_pct)
        n = collection.size().getInfo()
        log.info("Collection ready: %d scenes after scene-cloud filter + SCL mask", n)

    reference = rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)

    results = []
    for key in indices:
        results.append(process_index(PRODUCTS[key], collection, region, reference,
                                     project, skip_download, coarse_scale))

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

    _report(results)
    return results


def _report(results: Sequence[DownloadResult]) -> None:
    drive = [r for r in results if not r.is_local]
    log.info("Section 4 complete: %d/%d composites downloaded locally.",
             len(results) - len(drive), len(results))
    if drive:
        log.error("=" * 70)
        log.error("MANUAL STEP REQUIRED -- %d composite(s) fell back to Google Drive:",
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
                   help="reuse composites already in data/raw/sentinel2/.")
    p.add_argument("--coarse-scale", type=int, default=None,
                   help="(smoke test) override download scale in metres for speed.")
    p.add_argument("--max-scene-cloud-pct", type=float, default=MAX_SCENE_CLOUD_PCT,
                   help="drop scenes with CLOUDY_PIXEL_PERCENTAGE >= this (default %(default)s).")
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
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
