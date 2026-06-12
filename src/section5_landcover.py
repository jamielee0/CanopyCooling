#!/usr/bin/env python3
"""Section 5 - Acquire land-cover layers: imperviousness and tree canopy.

Implements steps 29-32 of the Data Acquisition & Analysis Protocol for the
Phoenix pilot. Like Sections 2-4 the whole section runs from this single module
so the result is reproducible end to end (protocol standing rule: "every figure
and every number must be reproducible from the saved code").

NO MANUAL DOWNLOAD. All three 30 m layers are pulled straight to local disk with
``geemap.download_ee_image`` (geedim under the hood), which tiles the request
under the Earth Engine size limit and stitches the tiles back into a single
GeoTIFF. There is NO ``Export.image.toDrive`` round-trip on the happy path; the
Drive export exists only as a last-resort fallback (see ``download_layer``).

Pipeline (steps 29-32)
----------------------
29. Load, for the study bbox, the most-recent NLCD impervious-surface-percentage
    layer, the NLCD land-cover CLASS layer (same NLCD image), and the most-recent
    USFS Tree Canopy Cover percentage layer. The exact collection ids + years are
    logged (and recorded in the manifest / filenames).
30. Download all three DIRECTLY to data/raw/landcover/ in EPSG:32612 at the native
    30 m scale with geemap.download_ee_image (geedim). Resampling on the EE side is
    NEAREST for all three so the native 30 m values (categorical classes AND the
    impervious / canopy percentages) are preserved unblended for the local
    aggregation below. Each file is recorded in data/manifest.csv with a checksum.
31. Resample impervious % and canopy % from 30 m to the 70 m reference grid by
    AREA-WEIGHTED AVERAGING -- each 70 m cell receives the area-weighted mean of
    the 30 m cells it covers. This averaged percentage is the "fraction" later
    sections use (protocol step 31; Section 10 thresholds are stated in percent).
32. Resample the land-cover CLASS layer to 70 m by NEAREST NEIGHBOUR (it is
    categorical) and keep it for the Section 10 water exclusion. It is NEVER
    bilinear/averaged -- that would invent meaningless fractional classes
    (Section 9 common pitfall).

Confirmed datasets (logged at run time; see also data/raw/README.md)
--------------------------------------------------------------------
Impervious % + land-cover class:
    USGS/NLCD_RELEASES/2021_REL/NLCD  image '2021'  -> year 2021
    bands: 'impervious' (0-100 %), 'landcover' (NLCD class codes 11-95)
    The most-recent OFFICIAL NLCD release in the Earth Engine catalog that
    carries BOTH the impervious-surface-percentage layer and the land-cover
    class layer in one CONUS asset. (The 2023 release folder holds only RCMAP +
    TCC, not the conventional NLCD land-cover / impervious image.)
Tree canopy %:
    projects/gtac-data-publish/assets/TCC/Product_Version/2025-6  CONUS, year 2025
    band: 'NLCD_Percent_Tree_Canopy_Cover' (0-100 %)
    The current (non-deprecated) USFS Tree Canopy Cover collection; it supersedes
    the deprecated USGS/NLCD_RELEASES/2023_REL/TCC/v2023-5. Most-recent CONUS year.

UNITS. The protocol calls these layers the impervious "fraction" and canopy
"fraction"; the source data and the Section-10 thresholds ("below 20 percent",
"above 70 percent") are in PERCENT, so the saved layers keep the native percent
units (0-100, float) and the GeoTIFF/manifest/READMEs say so explicitly.

A NOTE ON nodata=0 (important). geedim tags the downloaded uint8 rasters with
nodata=0. For the categorical land-cover layer 0 is genuinely "no class" (valid
NLCD classes start at 11), so 0=nodata is correct. But for impervious / canopy,
0 % is a VALID and very common value (most of the map). These two layers are
therefore read WITHOUT masking and every 0-100 value is treated as valid; only
sentinels > 100 (geedim ``unmask_value``) count as missing. Reading them masked
would silently drop every 0 % cell and bias the average upward.

Run (canopy env, Earth Engine authenticated):
    python src/section5_landcover.py                 # full run (all three layers)
    python src/section5_landcover.py --skip-download # reuse data/raw/landcover files
    python src/section5_landcover.py --layers impervious,landcover_class
    python src/section5_landcover.py --coarse-scale 300  # quick smoke test
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

# Heavy geospatial / EE libraries. The pure-numpy logic below (the area-weighted
# regrid, the categorical-subset check, product config) does not touch ee/geemap,
# so it stays unit-testable without the EE stack installed (see test_section5_*).
import ee  # noqa: E402
import geemap  # noqa: E402
import rioxarray  # noqa: F401,E402  (registers the .rio accessor)
import xarray as xr  # noqa: E402
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

log = logging.getLogger("section5")

# --------------------------------------------------------------------------- #
# Confirmed collection constants (the exact image + year are resolved and logged
# at run time -- "use the most recent year available", protocol Section 5).
# --------------------------------------------------------------------------- #
NLCD_COLLECTION = "USGS/NLCD_RELEASES/2021_REL/NLCD"
NLCD_IMPERVIOUS_BAND = "impervious"
NLCD_LANDCOVER_BAND = "landcover"

TCC_COLLECTION = "projects/gtac-data-publish/assets/TCC/Product_Version/2025-6"
TCC_STUDY_AREA = "CONUS"
TCC_CANOPY_BAND = "NLCD_Percent_Tree_Canopy_Cover"

NATIVE_SCALE_M = 30                       # NLCD + TCC native pixel size (metres)
PERCENT_VALID_MAX = 100                   # impervious / canopy valid range is 0-100
PERCENT_UNMASK_SENTINEL = 255             # geedim fills masked %-pixels with this
LANDCOVER_NODATA = 0                      # 0 = "no NLCD class" (valid classes >= 11)

# Buffer (m) added around the Section-1 grid bounds when defining the EE download
# region, so the 30 m source fully covers the 70 m grid and the area-weighted
# average at the grid EDGES is computed from complete source coverage.
DOWNLOAD_BUFFER_M = 150.0

# A 70 m cell is only written if at least this fraction of its area is covered by
# valid finer cells (else it is left nodata). With the buffered download this is
# ~1.0 everywhere inland; the guard only matters at a true data edge / mask hole.
COVERAGE_MIN = 0.5

# Per-tile size ladder (MB) for the resilient download. On a compute/size failure
# we retry with progressively smaller tiles before the Drive fallback (protocol
# step 30 / user instruction). These static 30 m layers are light (one band over
# the bbox is ~8 MB), so the default first rung rarely needs to step down.
MAX_TILE_SIZES_MB = (32, 16, 8, 4, 2)

# Cap concurrent Earth Engine tile requests (forwarded to geedim as max_requests)
# to keep the backend steady and avoid HTTP 429 storms. geedim 2.0 retired the
# old num_threads knob in favour of max_requests / max_cpus.
MAX_REQUESTS = 8

RAW_SUBDIR = "landcover"                   # data/raw/landcover/
DRIVE_FOLDER = "canopy_section5"           # only used by the fallback


# =========================================================================== #
# Product configuration  (pure data; no geo / EE deps)
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class LayerSpec:
    """Static description of one Section-5 layer (filenames, kind, units, dtype).

    The concrete ee.Image, resolved year and collection id are attached later in
    a LayerPlan (they need Earth Engine); everything here is pure data so it can
    be unit-tested without ee/geemap.
    """

    key: str                 # "impervious" / "canopy" / "landcover_class"
    long_name: str
    kind: str                # "continuous" (area-weighted avg) | "categorical" (nearest)
    band: str                # EE band id
    source_tag: str          # short provenance tag for the manifest ("nlcd"/"usfs_tcc")
    units: str
    out_dtype: str           # on-grid output dtype
    out_nodata: float        # on-grid output nodata

    @property
    def is_categorical(self) -> bool:
        return self.kind == "categorical"

    def raw_filename(self, year: int) -> str:
        """Native 30 m download name in data/raw/landcover/ (carries the year)."""
        return f"{self.source_tag}_{self.key}_{year}_{NATIVE_SCALE_M}m.tif"

    def grid_filename(self, year: int) -> str:
        """The layer resampled onto the 70 m reference grid (data/interim/)."""
        return f"{self.source_tag}_{self.key}_{year}_70m.tif"


IMPERVIOUS_SPEC = LayerSpec(
    key="impervious",
    long_name="NLCD impervious surface (area-weighted mean percent on the 70 m grid)",
    kind="continuous",
    band=NLCD_IMPERVIOUS_BAND,
    source_tag="nlcd",
    units="percent (0-100)",
    out_dtype="float32",
    out_nodata=float("nan"),
)
CANOPY_SPEC = LayerSpec(
    key="canopy",
    long_name="USFS tree canopy cover (area-weighted mean percent on the 70 m grid)",
    kind="continuous",
    band=TCC_CANOPY_BAND,
    source_tag="usfs_tcc",
    units="percent (0-100)",
    out_dtype="float32",
    out_nodata=float("nan"),
)
LANDCOVER_SPEC = LayerSpec(
    key="landcover_class",
    long_name="NLCD land-cover class (nearest-neighbour on the 70 m grid; categorical)",
    kind="categorical",
    band=NLCD_LANDCOVER_BAND,
    source_tag="nlcd",
    units="NLCD class code",
    out_dtype="uint8",
    out_nodata=float(LANDCOVER_NODATA),
)
SPECS = {s.key: s for s in (IMPERVIOUS_SPEC, CANOPY_SPEC, LANDCOVER_SPEC)}

# NLCD land-cover class codes -> short labels (for the QA figure legend + docs).
# Class 11 (open water) is what Section 10 uses to exclude water bodies.
NLCD_CLASS_LABELS = {
    11: "Open water", 12: "Perennial ice/snow",
    21: "Developed, open", 22: "Developed, low", 23: "Developed, medium",
    24: "Developed, high", 31: "Barren land",
    41: "Deciduous forest", 42: "Evergreen forest", 43: "Mixed forest",
    51: "Dwarf scrub", 52: "Shrub/scrub",
    71: "Grassland/herb.", 72: "Sedge/herb.", 73: "Lichens", 74: "Moss",
    81: "Pasture/hay", 82: "Cultivated crops",
    90: "Woody wetlands", 95: "Emergent herb. wetlands",
}


# =========================================================================== #
# Pure regrid logic  (numpy; unit-tested without the geo or EE stack)
# --------------------------------------------------------------------------- #
def _interval_overlap(dst_lo: np.ndarray, dst_hi: np.ndarray,
                      src_lo: np.ndarray, src_hi: np.ndarray) -> np.ndarray:
    """1-D overlap-length matrix between dest cells and source cells.

    Each cell is the closed interval [lo, hi] (in metres). Returns W with
    W[i, j] = length of the overlap between dest cell i and source cell j (>= 0).
    Order-independent: the lo/hi are true interval min/max, so it works for the
    x axis (lo=left, hi=right) and the y axis (lo=bottom, hi=top) alike, in
    whatever row/column storage order the rasters use.
    """
    lo = np.maximum(dst_lo[:, None], src_lo[None, :])
    hi = np.minimum(dst_hi[:, None], src_hi[None, :])
    return np.clip(hi - lo, 0.0, None)


def _cell_edges(transform6: Sequence[float], n: int, axis: str
                ) -> tuple[np.ndarray, np.ndarray]:
    """Return (lo, hi) per-cell interval bounds (metres) for an axis-aligned grid.

    transform6 is the rasterio Affine 6-tuple (a, b, c, d, e, f) with NO rotation
    (b == d == 0). axis="x": lo=left, hi=right (uses a, c). axis="y": lo=bottom,
    hi=top (uses e, f); e is negative for a north-up raster.
    """
    a, b, c, d, e, f = transform6
    if b != 0.0 or d != 0.0:
        raise ValueError("area-weighted regrid requires an unrotated grid (b==d==0)")
    if axis == "x":
        left = c + a * np.arange(n, dtype="float64")
        right = c + a * np.arange(1, n + 1, dtype="float64")
        return np.minimum(left, right), np.maximum(left, right)
    top = f + e * np.arange(n, dtype="float64")
    bottom = f + e * np.arange(1, n + 1, dtype="float64")
    return np.minimum(top, bottom), np.maximum(top, bottom)


def area_weighted_regrid(src_vals: np.ndarray, src_transform: Sequence[float],
                         dst_transform: Sequence[float], dst_shape: tuple[int, int],
                         coverage_min: float = COVERAGE_MIN) -> np.ndarray:
    """Exact AREA-WEIGHTED average of a finer raster onto a coarser grid.

    Both grids must be axis-aligned (no rotation) and in the SAME CRS -- true for
    Section 5 because the raw layers are downloaded already in EPSG:32612 and the
    reference grid is EPSG:32612. Each destination (70 m) cell value is the mean
    of the source (30 m) cells it covers, each source cell weighted by the AREA of
    its intersection with the destination cell; ``NaN`` source cells are excluded
    from both the weighted sum and its normaliser. A destination cell is returned
    ``NaN`` when less than ``coverage_min`` of its area is covered by valid source.

    Because the grids are rectilinear, the 2-D area weight factorises into the
    outer product of 1-D x- and y-overlaps, so the whole resample is two small
    matrix multiplications: num = Wy . (src) . Wx^T, den = Wy . (valid) . Wx^T.
    """
    src = np.asarray(src_vals, dtype="float64")
    nsr, nsc = src.shape
    ndr, ndc = dst_shape

    src_x_lo, src_x_hi = _cell_edges(src_transform, nsc, "x")
    src_y_lo, src_y_hi = _cell_edges(src_transform, nsr, "y")
    dst_x_lo, dst_x_hi = _cell_edges(dst_transform, ndc, "x")
    dst_y_lo, dst_y_hi = _cell_edges(dst_transform, ndr, "y")

    wx = _interval_overlap(dst_x_lo, dst_x_hi, src_x_lo, src_x_hi)  # (ndc, nsc)
    wy = _interval_overlap(dst_y_lo, dst_y_hi, src_y_lo, src_y_hi)  # (ndr, nsr)

    valid = np.isfinite(src)
    src0 = np.where(valid, src, 0.0)
    num = wy @ src0 @ wx.T                       # (ndr, ndc) area-weighted sum
    den = wy @ valid.astype("float64") @ wx.T    # (ndr, ndc) valid overlap area

    a, _b, _c, _d, e, _f = dst_transform
    cell_area = abs(a) * abs(e)
    out = np.full((ndr, ndc), np.nan, dtype="float64")
    ok = den >= coverage_min * cell_area
    out[ok] = num[ok] / den[ok]
    return out


def categorical_subset_ok(src_classes: np.ndarray, out_classes: np.ndarray) -> bool:
    """True if every resampled class already existed in the source (no invention).

    Nearest-neighbour resampling of a categorical layer must only ever copy
    existing class codes; a value that is not in the source means an averaging /
    interpolation bug crept in (Section 9 common pitfall). nodata is ignored by
    the caller before this check.
    """
    return set(np.unique(out_classes).tolist()).issubset(
        set(np.unique(src_classes).tolist()))


# =========================================================================== #
# Earth Engine setup + image resolution  (step 29; needs ee)
# --------------------------------------------------------------------------- #
def initialize_ee() -> str:
    """Initialise Earth Engine, returning the project id used (mirrors Section 4)."""
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


def download_region() -> "ee.Geometry":
    """Section-1 grid bounds (EPSG:32612), buffered outward by DOWNLOAD_BUFFER_M.

    Defined in metres in the project CRS so the 30 m source fully covers the 70 m
    grid (edge-correct area weighting). This is the study bbox of config.py,
    expressed precisely on the analysis grid rather than as a lon/lat rectangle.
    """
    left, bottom, right, top = config.GRID_BOUNDS
    d = DOWNLOAD_BUFFER_M
    return ee.Geometry.Rectangle(
        [left - d, bottom - d, right + d, top + d], proj=config.CRS, geodesic=False)


@dataclasses.dataclass
class LayerPlan:
    """A LayerSpec bound to a concrete, resolved ee.Image ready to download."""

    spec: LayerSpec
    image: "ee.Image"
    collection_id: str
    image_index: str
    year: int

    @property
    def raw_filename(self) -> str:
        return self.spec.raw_filename(self.year)

    @property
    def grid_filename(self) -> str:
        return self.spec.grid_filename(self.year)


def _resolve_year(image: "ee.Image", fallback_index: str) -> tuple[str, int]:
    """Return (system:index, year) for a resolved image, parsing the year out."""
    idx = image.get("system:index").getInfo() or fallback_index
    year = image.get("year").getInfo()
    if year is None:
        # NLCD images are keyed by the year itself (e.g. '2021'); fall back to that.
        import re
        m = re.search(r"(\d{4})", str(idx))
        year = int(m.group(1)) if m else -1
    return str(idx), int(year)


def resolve_layer_plans(keys: Sequence[str]) -> list[LayerPlan]:
    """Resolve the most-recent NLCD + TCC images and bind each requested layer.

    Logs the exact collection ids, image indices and years used (protocol step 29
    / user instruction "Log the exact collection IDs and years used").
    """
    plans: list[LayerPlan] = []

    need_nlcd = any(SPECS[k].source_tag == "nlcd" for k in keys)
    need_tcc = any(SPECS[k].source_tag == "usfs_tcc" for k in keys)

    if need_nlcd:
        nlcd_ic = ee.ImageCollection(NLCD_COLLECTION)
        nlcd_img = ee.Image(nlcd_ic.sort("system:time_start", False).first())
        nlcd_index, nlcd_year = _resolve_year(nlcd_img, "2021")
        log.info("NLCD: collection=%s  image=%s  year=%d  (bands: %s, %s)",
                 NLCD_COLLECTION, nlcd_index, nlcd_year,
                 NLCD_IMPERVIOUS_BAND, NLCD_LANDCOVER_BAND)

    if need_tcc:
        tcc_ic = (ee.ImageCollection(TCC_COLLECTION)
                  .filter(ee.Filter.eq("study_area", TCC_STUDY_AREA)))
        tcc_img = ee.Image(tcc_ic.sort("system:time_start", False).first())
        tcc_index, tcc_year = _resolve_year(tcc_img, "TCC_v2025-6_CONUS_2025")
        log.info("USFS TCC: collection=%s  image=%s  year=%d  study_area=%s  (band: %s)",
                 TCC_COLLECTION, tcc_index, tcc_year, TCC_STUDY_AREA, TCC_CANOPY_BAND)

    for key in keys:
        spec = SPECS[key]
        if spec.source_tag == "nlcd":
            image = nlcd_img.select(spec.band)
            plans.append(LayerPlan(spec, image, NLCD_COLLECTION, nlcd_index, nlcd_year))
        else:
            image = tcc_img.select(spec.band)
            plans.append(LayerPlan(spec, image, TCC_COLLECTION, tcc_index, tcc_year))
    return plans


# =========================================================================== #
# Resilient download  (step 30) -- geemap.download_ee_image, geedim under the hood
# --------------------------------------------------------------------------- #
@dataclasses.dataclass
class DownloadResult:
    """Outcome of acquiring one layer (local success or Drive fallback)."""

    plan: LayerPlan
    path: Path | None                  # local GeoTIFF if downloaded to disk
    method: str                        # "geemap.download_ee_image" / "Export.image.toDrive"
    max_tile_size_mb: float | None = None
    drive_task_id: str | None = None
    drive_folder: str | None = None
    drive_filename: str | None = None

    @property
    def is_local(self) -> bool:
        return self.path is not None


def _export_to_drive(plan: LayerPlan, region: "ee.Geometry") -> DownloadResult:
    """Last resort: start an Export.image.toDrive task and report it to the user.

    Only reached if every tiled local download attempt failed. The categorical
    land-cover layer is exported WITHOUT calling .resample(), so Earth Engine
    reprojects it with its default NEAREST neighbour (never bilinear).
    """
    drive_name = plan.raw_filename[:-4]    # strip ".tif"
    task = ee.batch.Export.image.toDrive(
        image=plan.image,
        description=drive_name,
        folder=DRIVE_FOLDER,
        fileNamePrefix=drive_name,
        region=region,
        crs=config.CRS,
        scale=NATIVE_SCALE_M,
        maxPixels=int(1e13),
        fileFormat="GeoTIFF",
    )
    task.start()
    log.error("Drive FALLBACK for %s: started Export.image.toDrive task id=%s "
              "(folder=%s, file=%s.tif)", plan.spec.key, task.id, DRIVE_FOLDER, drive_name)
    return DownloadResult(
        plan=plan, path=None, method="Export.image.toDrive",
        drive_task_id=task.id, drive_folder=DRIVE_FOLDER,
        drive_filename=f"{drive_name}.tif",
    )


def download_layer(plan: LayerPlan, region: "ee.Geometry", raw_dir: Path,
                   tile_sizes_mb: Sequence[float] = MAX_TILE_SIZES_MB,
                   scale_m: int | None = None) -> DownloadResult:
    """Download one layer to data/raw/landcover/ in EPSG:32612 at the native 30 m.

    Tiles + stitches via geemap.download_ee_image (geedim). Resampling is NEAREST
    for every layer so the native 30 m values are preserved unblended; the
    scientific 30 m -> 70 m resampling (area-weighted average vs nearest) is done
    locally and exactly afterwards. Continuous layers use ``unmask_value=255`` so
    any genuinely-masked pixel is a separable sentinel rather than masquerading as
    a real 0 %. On a compute/size failure we retry with a smaller per-tile size;
    only if every size fails do we fall back to Drive (step 30 / user instruction).
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / plan.raw_filename
    scale_m = scale_m or NATIVE_SCALE_M
    # Continuous %-layers: lift masked pixels to a >100 sentinel so a real 0 % is
    # never confused with nodata. Categorical: leave geedim's 0=nodata as-is.
    unmask = None if plan.spec.is_categorical else PERCENT_UNMASK_SENTINEL
    last_exc: Exception | None = None

    for mts in tile_sizes_mb:
        log.info("Downloading %s -> %s  crs=%s scale=%dm resampling=near max_tile=%sMB",
                 plan.spec.key, out_path.name, config.CRS, scale_m, mts)
        try:
            geemap.download_ee_image(
                plan.image, str(out_path),
                region=region,
                crs=config.CRS,
                scale=scale_m,
                resampling="near",       # preserve native 30 m values (req. for categorical)
                unmask_value=unmask,
                overwrite=True,
                max_requests=MAX_REQUESTS,   # geedim 2.0 concurrency cap (replaces num_threads)
                max_tile_size=mts,
            )
            log.info("Downloaded %s (%.1f MB on disk) at max_tile_size=%sMB",
                     plan.spec.key, out_path.stat().st_size / 1e6, mts)
            return DownloadResult(plan=plan, path=out_path,
                                  method="geemap.download_ee_image", max_tile_size_mb=mts)
        except Exception as exc:  # noqa: BLE001 - retry smaller, then Drive
            last_exc = exc
            log.warning("download %s failed at max_tile_size=%sMB: %s: %s -- "
                        "retrying with a smaller tile size",
                        plan.spec.key, mts, type(exc).__name__, exc)

    log.error("All tiled download attempts for %s failed (last: %s: %s).",
              plan.spec.key, type(last_exc).__name__, last_exc)
    return _export_to_drive(plan, region)


# =========================================================================== #
# Manifest + resample to the 70 m grid  (steps 30-32)
# --------------------------------------------------------------------------- #
def record_in_manifest(result: DownloadResult, project: str) -> None:
    """Append the downloaded layer to data/manifest.csv with a SHA-256 sum."""
    if not result.is_local:
        return
    plan = result.plan
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    src = (f"Google Earth Engine {plan.collection_id} "
           f"(project={project}; image={plan.image_index}; year={plan.year}; "
           f"band={plan.spec.band}; {plan.spec.kind}; {NATIVE_SCALE_M} m; "
           f"EPSG:32612; resampling=near; geemap.download_ee_image)")
    sec2.append_to_manifest([{
        "source": src,
        "dataset": plan.collection_id,
        "filename": result.path.name,
        "download_date": today,
        "checksum": f"sha256:{sec2.sha256_file(result.path)}",
    }])


def _read_reference():
    """Open the Section-1 reference grid as a 2-D DataArray (anchor for alignment)."""
    return rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)


def regrid_continuous(raw_path: Path, out_path: Path, reference, spec: LayerSpec) -> Path:
    """Step 31: resample a 30 m %-layer to the 70 m grid by AREA-WEIGHTED averaging.

    Reads the raw layer UNMASKED (so real 0 % cells count as valid), treats only
    values > 100 (the geedim unmask sentinel) as missing, then area-weights onto
    the reference grid with :func:`area_weighted_regrid`. The result is written as
    float32 percent aligned exactly to reference_grid.tif. A GDAL ``average``
    resample is computed alongside purely as a cross-check and the agreement is
    logged.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw = rioxarray.open_rasterio(raw_path, masked=False).squeeze("band", drop=True)
    vals = raw.values.astype("float64")
    valid = vals <= PERCENT_VALID_MAX                  # real 0-100 %, drop >100 sentinels
    src = np.where(valid, vals, np.nan)
    n_invalid = int((~valid).sum())
    if n_invalid:
        log.info("%s: %d/%d source cells masked (value>%d) before averaging",
                 spec.key, n_invalid, vals.size, PERCENT_VALID_MAX)

    src_transform = tuple(raw.rio.transform())[:6]
    dst_transform = tuple(reference.rio.transform())[:6]
    dst_shape = (int(reference.sizes["y"]), int(reference.sizes["x"]))
    averaged = area_weighted_regrid(src, src_transform, dst_transform, dst_shape)

    if averaged.shape != tuple(config.GRID_SHAPE):
        raise RuntimeError(f"{spec.key}: regrid shape {averaged.shape} != "
                           f"GRID_SHAPE {tuple(config.GRID_SHAPE)}")

    # Cross-check against GDAL's own area-weighted 'average' resampling. The raw
    # nodata=0 tag must be cleared first, else GDAL would drop every real 0 %.
    try:
        xcheck_src = raw.where(valid).rio.write_nodata(np.nan, encoded=False)
        gdal_avg = xcheck_src.rio.reproject_match(reference, resampling=Resampling.average)
        a = averaged
        b = gdal_avg.values.astype("float64")
        both = np.isfinite(a) & np.isfinite(b)
        if both.any():
            diff = np.abs(a[both] - b[both])
            log.info("%s: area-weighted vs GDAL-average cross-check  "
                     "mean|d|=%.4f max|d|=%.4f (percent)", spec.key,
                     float(diff.mean()), float(diff.max()))
    except Exception as exc:  # noqa: BLE001 - cross-check is advisory only
        log.debug("%s: GDAL-average cross-check skipped: %s", spec.key, exc)

    out = xr.DataArray(averaged.astype(spec.out_dtype), dims=("y", "x"),
                       coords={"y": reference["y"], "x": reference["x"]})
    out = out.rio.write_crs(config.CRS)
    out = out.rio.write_transform(reference.rio.transform())
    out = out.rio.write_nodata(np.nan, encoded=False)
    out.attrs.update(long_name=spec.long_name, units=spec.units,
                     dataset=spec.source_tag, resampling="area_weighted_average_30m_to_70m")
    out.rio.to_raster(out_path, compress="deflate")
    finite = np.isfinite(averaged)
    log.info("Resampled %s -> %s  shape=%s  valid=%.1f%%  range=[%.2f, %.2f] %%",
             spec.key, out_path.name, averaged.shape,
             100 * finite.mean(), float(np.nanmin(averaged)), float(np.nanmax(averaged)))
    return out_path


def regrid_categorical(raw_path: Path, out_path: Path, reference, spec: LayerSpec) -> Path:
    """Step 32: resample the 30 m land-cover CLASS layer to 70 m by NEAREST.

    Categorical data is NEVER averaged/bilinear-interpolated -- that invents
    fractional classes (Section 9 pitfall). Uses nearest-neighbour ``reproject_match``
    so output classes are a subset of the input classes (asserted), and writes the
    result as uint8 aligned exactly to reference_grid.tif.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw = rioxarray.open_rasterio(raw_path, masked=False).squeeze("band", drop=True)
    raw = raw.rio.write_nodata(LANDCOVER_NODATA)
    aligned = raw.rio.reproject_match(reference, resampling=Resampling.nearest)

    out_vals = np.rint(np.asarray(aligned.values)).astype("uint8")
    if out_vals.shape != tuple(config.GRID_SHAPE):
        raise RuntimeError(f"{spec.key}: regrid shape {out_vals.shape} != "
                           f"GRID_SHAPE {tuple(config.GRID_SHAPE)}")

    src_classes = np.unique(np.rint(raw.values).astype("int64"))
    data_classes = out_vals[out_vals != LANDCOVER_NODATA]
    if not categorical_subset_ok(src_classes, np.unique(data_classes)):
        raise RuntimeError(f"{spec.key}: nearest resample invented classes not in "
                           "the source -- categorical resampling is broken")

    out = xr.DataArray(out_vals, dims=("y", "x"),
                       coords={"y": reference["y"], "x": reference["x"]})
    out = out.rio.write_crs(config.CRS)
    out = out.rio.write_transform(reference.rio.transform())
    out = out.rio.write_nodata(LANDCOVER_NODATA)
    out.attrs.update(long_name=spec.long_name, units=spec.units,
                     dataset=spec.source_tag, resampling="nearest_30m_to_70m")
    out.rio.to_raster(out_path, compress="deflate", dtype="uint8")

    present = sorted(int(c) for c in np.unique(data_classes))
    n_water = int((out_vals == 11).sum())
    log.info("Resampled %s -> %s  shape=%s  classes=%s  water(11)=%d cells",
             spec.key, out_path.name, out_vals.shape, present, n_water)
    return out_path


def resample_to_grid(result: DownloadResult, reference) -> Path:
    """Dispatch a downloaded layer to the correct 70 m resampler (steps 31-32)."""
    spec = result.plan.spec
    out_path = config.INTERIM_DIR / result.plan.grid_filename
    if spec.is_categorical:
        return regrid_categorical(result.path, out_path, reference, spec)
    return regrid_continuous(result.path, out_path, reference, spec)


# =========================================================================== #
# Figure  (deliverable: the three 70 m layers, visually confirmed)
# --------------------------------------------------------------------------- #
def make_layers_figure(grid_paths: dict[str, Path], figures_dir: Path) -> Path | None:
    """Three-panel QA map: impervious %, canopy %, and the categorical class layer.

    The deliverable confirmation figure for Section 5. Impervious / canopy use a
    continuous ramp; the land-cover class uses a discrete colormap with an NLCD
    legend so a reviewer can see water (class 11) and the developed / vegetated
    classes land where expected.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap

    panels = [k for k in ("impervious", "canopy", "landcover_class") if k in grid_paths]
    if not panels:
        return None
    figures_dir.mkdir(parents=True, exist_ok=True)
    left, bottom, right, top = config.GRID_BOUNDS
    extent = (left, right, bottom, top)

    fig, axes = plt.subplots(1, len(panels), figsize=(6.2 * len(panels), 6.2),
                             constrained_layout=True)
    if len(panels) == 1:
        axes = [axes]

    for ax, key in zip(axes, panels):
        da = rioxarray.open_rasterio(grid_paths[key], masked=True).squeeze("band", drop=True)
        arr = da.values.astype("float64")
        if key in ("impervious", "canopy"):
            cmap = "cividis" if key == "impervious" else "YlGn"
            im = ax.imshow(arr, extent=extent, origin="upper", cmap=cmap, vmin=0, vmax=100)
            fig.colorbar(im, ax=ax, label="percent (0-100)", shrink=0.82)
            med = float(np.nanmedian(arr))
            ax.set_title(f"{key.capitalize()} % (70 m, area-weighted)\n"
                         f"median={med:.1f}%  -  NLCD/USFS")
        else:
            present = sorted(int(c) for c in np.unique(arr[np.isfinite(arr)]))
            present = [c for c in present if c != LANDCOVER_NODATA]
            base = plt.get_cmap("tab20", len(present))
            cmap = ListedColormap([base(i) for i in range(len(present))])
            norm = BoundaryNorm(np.array(present + [present[-1] + 1]) - 0.5, len(present))
            ax.imshow(arr, extent=extent, origin="upper", cmap=cmap, norm=norm)
            handles = [plt.Rectangle((0, 0), 1, 1, color=cmap(i))
                       for i in range(len(present))]
            labels = [f"{c} {NLCD_CLASS_LABELS.get(c, '?')}" for c in present]
            ax.legend(handles, labels, loc="upper left", fontsize=6.5, framealpha=0.9,
                      title="NLCD class (nearest)", title_fontsize=7)
            ax.set_title("Land-cover class (70 m, nearest)\n"
                         "categorical - water (11) used in Section 10")
        ax.set_xlabel("Easting (m, EPSG:32612)")
        ax.set_ylabel("Northing (m, EPSG:32612)")

    out = figures_dir / "section5_landcover_layers.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote QA figure -> %s", out.name)
    return out


# =========================================================================== #
# Orchestration / CLI
# --------------------------------------------------------------------------- #
def process_layer(plan: LayerPlan, region, reference, project: str,
                  skip_download: bool, coarse_scale: int | None) -> DownloadResult:
    """Acquire one layer: download -> manifest -> 70 m grid."""
    raw_dir = config.RAW_DIR / RAW_SUBDIR
    raw_path = raw_dir / plan.raw_filename

    if skip_download:
        if not raw_path.exists():
            raise SystemExit(f"--skip-download: {raw_path} not found; run a full "
                             "download first.")
        result = DownloadResult(plan=plan, path=raw_path, method="(reused local file)")
        log.info("--skip-download: reusing %s", raw_path.name)
    else:
        result = download_layer(plan, region, raw_dir,
                                scale_m=coarse_scale or NATIVE_SCALE_M)
        # A coarse-scale smoke raster is not the real native product, so it is
        # resampled/figured to exercise the wiring but kept out of the manifest.
        if result.is_local and not coarse_scale:
            record_in_manifest(result, project)

    if not result.is_local:
        return result  # Drive fallback: nothing local to resample yet

    resample_to_grid(result, reference)
    return result


def run(layers: Sequence[str] = ("impervious", "canopy", "landcover_class"),
        skip_download: bool = False, coarse_scale: int | None = None
        ) -> list[DownloadResult]:
    config.ensure_dirs()
    project = "default"
    region = None
    plans: list[LayerPlan]

    if skip_download:
        # Resolve the years from any already-downloaded raw file names so the
        # interim/manifest names match, without needing Earth Engine.
        plans = _plans_from_local(layers)
    else:
        project = initialize_ee()                       # step 29
        region = download_region()
        plans = resolve_layer_plans(layers)

    reference = _read_reference()
    log.info("Reference grid: shape=%s crs=%s transform=%s",
             tuple(config.GRID_SHAPE), config.CRS, tuple(reference.rio.transform())[:6])

    results = []
    for plan in plans:
        results.append(process_layer(plan, region, reference, project,
                                     skip_download, coarse_scale))

    # QA figure (deliverable) from whatever landed on the grid locally.
    grid_paths = {r.plan.spec.key: config.INTERIM_DIR / r.plan.grid_filename
                  for r in results if r.is_local}
    if grid_paths:
        make_layers_figure(grid_paths, config.FIGURES_DIR)

    _report(results)
    return results


def _plans_from_local(layers: Sequence[str]) -> list[LayerPlan]:
    """Build LayerPlans for --skip-download by discovering the year in raw names."""
    raw_dir = config.RAW_DIR / RAW_SUBDIR
    plans: list[LayerPlan] = []
    for key in layers:
        spec = SPECS[key]
        matches = sorted(raw_dir.glob(f"{spec.source_tag}_{spec.key}_*_{NATIVE_SCALE_M}m.tif"))
        if not matches:
            raise SystemExit(f"--skip-download: no raw file for '{key}' in {raw_dir}.")
        name = matches[-1].name
        year = int(name.split("_")[-2])     # ..._<year>_30m.tif
        coll = NLCD_COLLECTION if spec.source_tag == "nlcd" else TCC_COLLECTION
        plans.append(LayerPlan(spec, image=None, collection_id=coll,
                               image_index=str(year), year=year))
    return plans


def _report(results: Sequence[DownloadResult]) -> None:
    drive = [r for r in results if not r.is_local]
    log.info("Section 5 complete: %d/%d layers on the 70 m grid locally.",
             len(results) - len(drive), len(results))
    if drive:
        log.error("=" * 70)
        log.error("MANUAL STEP REQUIRED -- %d layer(s) fell back to Google Drive:",
                  len(drive))
        for r in drive:
            log.error("  * %s: grab '%s' from Drive folder '%s' (task id=%s), drop it "
                      "into data/raw/landcover/, then re-run with --skip-download.",
                      r.plan.spec.key, r.drive_filename, r.drive_folder, r.drive_task_id)
        log.error("=" * 70)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 5 - NLCD impervious/land-cover + USFS canopy on the 70 m grid "
                    "(no manual download).")
    p.add_argument("--layers", default="impervious,canopy,landcover_class",
                   help="comma list of layers to process (default all three).")
    p.add_argument("--skip-download", action="store_true",
                   help="reuse layers already in data/raw/landcover/.")
    p.add_argument("--coarse-scale", type=int, default=None,
                   help="(smoke test) override download scale in metres for speed.")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    run(
        layers=tuple(s.strip() for s in args.layers.split(",") if s.strip()),
        skip_download=args.skip_download,
        coarse_scale=args.coarse_scale,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
