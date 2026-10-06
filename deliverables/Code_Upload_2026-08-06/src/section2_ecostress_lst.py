#!/usr/bin/env python3
"""Section 2 — Acquire and quality-filter ECOSTRESS land surface temperature.

Inputs : ECO_L2T_LSTE v002 granules from NASA Earthdata (LPCLOUD); the Section-1
         reference grid data/processed/reference_grid.tif.
Outputs: data/raw/ecostress_lst/ COGs + data/manifest.csv rows; the time-indexed
         cube data/interim/ecostress_lst_cube (Zarr) and granule QC report CSV;
         usable-obs count + mean-LST figures under figures/.
Key decisions (full rationale in docs/DESIGN_DECISIONS.md, Section 2):
  - Keep a pixel if QC bits 0-1 are 00 or 01, cloud == 0 (clear), and
    water == 0 (land). Including 01 is a professor-approved coverage decision;
    its contribution is reported separately for transparency.
  - v002 QC no longer carries cloud state; read clouds from the cloud layer.
  - Reproject to EPSG:32612 / 70 m with bilinear (continuous temperature field).
  - Raw LST is NEVER averaged across overpasses (precessing-orbit local times);
    the mean-LST map is a visual-QA artifact only.
Run: python src/section2_ecostress_lst.py
     python src/section2_ecostress_lst.py --max-granules 5    # smoke test
     python src/section2_ecostress_lst.py --skip-download     # reuse data/raw
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import hashlib
import logging
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

# The pure-numpy logic below (masks, drop/flag decisions, cube stats, filename
# parsing) does not touch these, so it is unit-testable without the geo stack.
import earthaccess  # noqa: E402
import rioxarray  # noqa: F401,E402  (registers the .rio accessor)
import xarray as xr  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402

# Make the sibling config module importable whether run from repo root or src/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config  # noqa: E402

log = logging.getLogger("section2")

# Confirmed collection constants (logged at run time).
SHORT_NAME = "ECO_L2T_LSTE"
VERSION = "002"
PROVIDER = "LPCLOUD"
DATASET_ID = f"{SHORT_NAME}.{VERSION}"          # recorded in the manifest
COLLECTION_DOI = "10.5067/ECOSTRESS/ECO_L2T_LSTE.002"

# Per-band layers we read. LST is the measurement; QC/cloud/water gate it.
# height is downloaded for provenance but not used in Section 2.
NEEDED_LAYERS = ("LST", "QC", "cloud", "water", "height")
QC_GATE_LAYERS = ("LST", "QC", "cloud", "water")

# Collection-2 quality-control conventions from the official ECOSTRESS v002
# User Guide, section 2.4 / Table 6. Mandatory flag 01 marks a produced
# retrieval with one or more potentially degrading conditions. For this
# data-limited pilot, the professor approved retaining both produced-retrieval
# classes (00 and 01). We preserve that caveat in metadata and separately audit
# the pixels contributed by 01. Cloud and water are still screened independently
# with their Collection-2 layers below; 10 and 11 remain excluded.
QC_MANDATORY_BITS = 0b11      # bits 0-1 are the mandatory QA flag
QC_BEST_QUALITY = 0b00        # 00 = produced without the v002 degradation flag
QC_DEGRADED_QUALITY = 0b01    # 01 = produced, but accuracy may be degraded
QC_MAX_INCLUDED_QUALITY = QC_DEGRADED_QUALITY  # professor-approved: keep 00 + 01
CLOUD_CLEAR_VALUE = 0         # cloud layer: 0 = clear, 1 = cloud
WATER_LAND_VALUE = 0          # water layer: 0 = land,  1 = water

# Physical-plausibility window for a Phoenix summer surface (Kelvin).
LST_PLAUSIBLE_K = (290.0, 340.0)

# A granule is "almost entirely missing" if < this fraction of the study-area
# pixels survive QC. Overridable on the command line.
DEFAULT_MIN_VALID_FRACTION = 0.01

# Output locations.
RAW_SUBDIR = "ecostress_lst"                                  # data/raw/ecostress_lst/
CUBE_DIRNAME = "ecostress_lst_cube"                           # data/interim/ecostress_lst_cube (zarr)
PILOT_START, PILOT_END = config.PILOT_WINDOW                  # ("2023-06-01","2023-09-30")


# --- Filename parsing (pure; no geo deps) ---
# ECOv002_L2T_LSTE_28527_009_13TDE_20230718T081442_0710_01_LST.tif
#   sensor_ver _L2T _LSTE _orbit _scene _tile _YYYYMMDDTHHMMSS _build _iter _LAYER
_GRANULE_RE = re.compile(
    r"^(?P<sensor>ECOv\d{3})_(?P<level>L2T)_(?P<param>LSTE)_"
    r"(?P<orbit>\d+)_(?P<scene>\d+)_(?P<tile>[0-9A-Z]+)_"
    r"(?P<dt>\d{8}T\d{6})_(?P<build>\d+)_(?P<iter>\d+)_(?P<layer>[A-Za-z_]+)\.tif$"
)


@dataclasses.dataclass(frozen=True)
class GranuleFile:
    """Parsed components of one ECOSTRESS tiled COG filename."""

    filename: str
    sensor: str
    orbit: str
    scene: str
    tile: str
    datetime_utc: _dt.datetime
    build: str
    iteration: str
    layer: str

    @property
    def overpass_key(self) -> str:
        """Key for one overpass (orbit+scene+instant). Tiles sharing it mosaic
        into a SINGLE time slice."""
        return f"{self.orbit}_{self.scene}_{self.datetime_utc:%Y%m%dT%H%M%S}"


def parse_granule_filename(filename: str) -> GranuleFile:
    """Parse an ECO_L2T_LSTE COG filename into its fields (raises on mismatch)."""
    name = Path(filename).name
    m = _GRANULE_RE.match(name)
    if not m:
        raise ValueError(f"Not an ECO_L2T_LSTE tiled COG filename: {name!r}")
    g = m.groupdict()
    dt = _dt.datetime.strptime(g["dt"], "%Y%m%dT%H%M%S").replace(
        tzinfo=_dt.timezone.utc
    )
    return GranuleFile(
        filename=name,
        sensor=g["sensor"],
        orbit=g["orbit"],
        scene=g["scene"],
        tile=g["tile"],
        datetime_utc=dt,
        build=g["build"],
        iteration=g["iter"],
        layer=g["layer"],
    )


def layer_path_for(lst_path: Path, layer: str) -> Path:
    """Given a ..._LST.tif path, return the sibling path for another layer."""
    return lst_path.with_name(re.sub(r"_LST\.tif$", f"_{layer}.tif", lst_path.name))


# --- Quality-control logic (pure numpy; unit-tested without the geo stack) ---
def qc_best_quality_mask(qc: np.ndarray) -> np.ndarray:
    """True only for v002 mandatory-QA ``00`` retrievals (audit baseline)."""
    qc_int = np.asarray(qc)
    return (qc_int & QC_MANDATORY_BITS) == QC_BEST_QUALITY


def qc_primary_quality_mask(qc: np.ndarray) -> np.ndarray:
    """True for mandatory-QA ``00`` or ``01`` retrievals used in the pilot.

    The inclusion of potentially degraded class ``01`` is an explicit,
    professor-approved coverage decision for this data-limited pilot. Higher QC
    bits do not alter the mandatory two-bit decision; classes ``10`` and ``11``
    remain excluded.
    """
    mandatory = np.asarray(qc) & QC_MANDATORY_BITS
    return mandatory <= QC_MAX_INCLUDED_QUALITY


def build_keep_mask(
    lst_k: np.ndarray,
    qc: np.ndarray,
    cloud: np.ndarray,
    water: np.ndarray,
) -> np.ndarray:
    """Keep finite, clear, land LST with mandatory QA ``00`` or ``01``."""
    finite_lst = np.isfinite(np.asarray(lst_k, dtype="float64"))
    qc_ok = qc_primary_quality_mask(qc)
    clear = np.asarray(cloud) == CLOUD_CLEAR_VALUE
    land = np.asarray(water) == WATER_LAND_VALUE
    return finite_lst & qc_ok & clear & land


def apply_keep_mask(lst_k: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """Return LST with all non-kept pixels set to NaN (missing)."""
    out = np.asarray(lst_k, dtype="float64").copy()
    out[~keep] = np.nan
    return out


@dataclasses.dataclass
class GranuleStats:
    """Per-granule QC summary used for the drop / flag decisions (step 16)."""

    overpass_key: str
    datetime_utc: _dt.datetime
    tile: str
    n_pixels: int
    n_valid: int
    valid_fraction: float
    lst_min: float
    lst_max: float
    lst_mean: float
    n_out_of_range: int
    n_valid_best_only: int = 0
    n_recovered_qc01: int = 0
    dropped: bool = False
    range_flagged: bool = False

    def as_row(self) -> dict:
        return {
            "overpass_key": self.overpass_key,
            "datetime_utc": self.datetime_utc.isoformat(),
            "tile": self.tile,
            "n_pixels": self.n_pixels,
            "n_valid": self.n_valid,
            "valid_fraction": round(self.valid_fraction, 6),
            "lst_min_k": None if np.isnan(self.lst_min) else round(self.lst_min, 3),
            "lst_max_k": None if np.isnan(self.lst_max) else round(self.lst_max, 3),
            "lst_mean_k": None if np.isnan(self.lst_mean) else round(self.lst_mean, 3),
            "n_out_of_range": self.n_out_of_range,
            "n_valid_best_only": self.n_valid_best_only,
            "n_recovered_qc01": self.n_recovered_qc01,
            "dropped": self.dropped,
            "range_flagged": self.range_flagged,
        }


def summarize_granule(
    lst_clean: np.ndarray,
    overpass_key: str,
    datetime_utc: _dt.datetime,
    tile: str,
    plausible_k: tuple[float, float] = LST_PLAUSIBLE_K,
) -> GranuleStats:
    """Compute valid coverage and range statistics for a cleaned granule."""
    arr = np.asarray(lst_clean, dtype="float64")
    n_pixels = int(arr.size)
    finite = np.isfinite(arr)
    n_valid = int(finite.sum())
    valid_fraction = (n_valid / n_pixels) if n_pixels else 0.0
    if n_valid:
        vals = arr[finite]
        lo, hi = plausible_k
        n_out = int(((vals < lo) | (vals > hi)).sum())
        return GranuleStats(
            overpass_key=overpass_key,
            datetime_utc=datetime_utc,
            tile=tile,
            n_pixels=n_pixels,
            n_valid=n_valid,
            valid_fraction=valid_fraction,
            lst_min=float(vals.min()),
            lst_max=float(vals.max()),
            lst_mean=float(vals.mean()),
            n_out_of_range=n_out,
        )
    return GranuleStats(
        overpass_key=overpass_key,
        datetime_utc=datetime_utc,
        tile=tile,
        n_pixels=n_pixels,
        n_valid=0,
        valid_fraction=0.0,
        lst_min=np.nan,
        lst_max=np.nan,
        lst_mean=np.nan,
        n_out_of_range=0,
    )


def decide_drop(stats: GranuleStats, min_valid_fraction: float) -> bool:
    """True if the granule is almost entirely missing after QC (step 16)."""
    return stats.valid_fraction < min_valid_fraction


def decide_range_flag(
    stats: GranuleStats, plausible_k: tuple[float, float] = LST_PLAUSIBLE_K
) -> bool:
    """True if any retained, valid LST falls outside the plausible window."""
    if stats.n_valid == 0:
        return False
    lo, hi = plausible_k
    return (stats.lst_min < lo) or (stats.lst_max > hi)


# --- Cube statistics (pure numpy) ---
def usable_observation_count(stack: np.ndarray) -> np.ndarray:
    """Per-pixel count of finite (usable) observations over the time axis 0."""
    return np.isfinite(np.asarray(stack, dtype="float64")).sum(axis=0).astype("int32")


def mean_lst_map(stack: np.ndarray) -> np.ndarray:
    """Per-pixel mean LST over time, ignoring NaNs (visual-QA artifact only)."""
    import warnings

    arr = np.asarray(stack, dtype="float64")
    all_nan = ~np.isfinite(arr).any(axis=0)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", r"Mean of empty slice", RuntimeWarning)
        out = np.nanmean(np.where(np.isfinite(arr), arr, np.nan), axis=0)
    out[all_nan] = np.nan
    return out


# --- Checksums + manifest (step 13) ---
def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Streaming SHA-256 of a file (large COGs are not loaded whole)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


_MANIFEST_COLUMNS = ["source", "dataset", "filename", "download_date", "checksum"]


def append_to_manifest(rows: Sequence[dict], manifest_csv: Path = None) -> None:
    """Append rows to data/manifest.csv, skipping filenames already recorded."""
    manifest_csv = Path(manifest_csv or config.MANIFEST_CSV)
    if manifest_csv.exists() and manifest_csv.stat().st_size > 0:
        existing = pd.read_csv(manifest_csv)
    else:
        existing = pd.DataFrame(columns=_MANIFEST_COLUMNS)
    known = set(existing.get("filename", pd.Series(dtype=str)).astype(str))
    new_rows = [r for r in rows if r["filename"] not in known]
    if not new_rows:
        log.info("manifest: nothing new to record (%d files already present)", len(known))
        return
    out = pd.concat([existing, pd.DataFrame(new_rows, columns=_MANIFEST_COLUMNS)],
                    ignore_index=True)
    out.to_csv(manifest_csv, index=False)
    log.info("manifest: appended %d row(s) -> %s", len(new_rows), manifest_csv)


# --- Earthdata search + download (steps 12-13) ---
def bbox_for_earthaccess() -> tuple[float, float, float, float]:
    """config.BBOX_LONLAT is (min_lon,max_lon,min_lat,max_lat); earthaccess wants
    (lower_left_lon, lower_left_lat, upper_right_lon, upper_right_lat)."""
    min_lon, max_lon, min_lat, max_lat = config.BBOX_LONLAT
    return (min_lon, min_lat, max_lon, max_lat)


def _load_project_dotenv() -> None:
    """Load the gitignored repo-root .env into the environment (no overwrite).

    Real environment variables and ~/.netrc always take precedence.
    """
    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = (part.strip() for part in line.split("=", 1))
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        os.environ.setdefault(key, val)


def authenticate() -> "earthaccess.Auth":
    """Log in to NASA Earthdata (reads ~/.netrc or EARTHDATA_USERNAME/PASSWORD)."""
    _load_project_dotenv()
    auth = earthaccess.login()
    if not getattr(auth, "authenticated", False):
        raise RuntimeError(
            "Earthdata authentication failed. Configure ~/.netrc or the "
            "EARTHDATA_USERNAME / EARTHDATA_PASSWORD environment variables."
        )
    log.info("Earthdata: authenticated")
    return auth


def search_granules(
    temporal: tuple[str, str] = (PILOT_START, PILOT_END),
    max_granules: int | None = None,
):
    """Search the ECO_L2T_LSTE collection over the study bbox and pilot window."""
    bbox = bbox_for_earthaccess()
    log.info(
        "Searching CMR: short_name=%s version=%s provider=%s bbox=%s temporal=%s",
        SHORT_NAME, VERSION, PROVIDER, bbox, temporal,
    )
    results = earthaccess.search_data(
        short_name=SHORT_NAME,
        version=VERSION,
        provider=PROVIDER,
        bounding_box=bbox,
        temporal=temporal,
        count=2000 if max_granules is None else max_granules,
    )
    log.info("CMR returned %d granule(s)", len(results))
    if max_granules is not None:
        results = results[:max_granules]
    return results


def _needed_layer_links(results) -> list[str]:
    """Collect download URLs for only the layers we use (keeps data/raw small)."""
    suffixes = tuple(f"_{lyr}.tif" for lyr in NEEDED_LAYERS)
    links: list[str] = []
    for granule in results:
        for url in granule.data_links():
            if url.endswith(suffixes):
                links.append(url)
    # De-duplicate while preserving order.
    seen, unique = set(), []
    for u in links:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def download_granules(results, raw_dir: Path) -> list[Path]:
    """Download the needed per-band COGs and record each in the manifest.

    Returns the list of local file paths.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    urls = _needed_layer_links(results)
    log.info("Downloading %d COG(s) into %s", len(urls), raw_dir)
    local = earthaccess.download(urls, str(raw_dir))
    paths = [Path(p) for p in local if str(p).endswith(".tif")]

    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    url_by_name = {u.rsplit("/", 1)[-1]: u for u in urls}
    rows = []
    for p in paths:
        rows.append({
            "source": url_by_name.get(p.name, "NASA LP DAAC (LPCLOUD)"),
            "dataset": DATASET_ID,
            "filename": p.name,
            "download_date": today,
            "checksum": f"sha256:{sha256_file(p)}",
        })
    append_to_manifest(rows)
    return paths


def discover_local_lst_files(raw_dir: Path) -> list[Path]:
    """All ..._LST.tif COGs already present locally (for --skip-download)."""
    return sorted(raw_dir.glob("ECOv*_L2T_LSTE_*_LST.tif"))


# --- Per-granule cleaning (steps 14-17) — needs the geo stack at run time ---
def _open_raw(path: Path, mask_and_scale: bool):
    """Open a single-band COG as a 2-D DataArray (band dim squeezed away)."""
    da = rioxarray.open_rasterio(path, masked=mask_and_scale,
                                 mask_and_scale=mask_and_scale)
    return da.squeeze("band", drop=True)


def _clip_to_bbox(da):
    """Clip a granule to the study-area extent (in the granule's own CRS)."""
    import geopandas as gpd
    from shapely.geometry import box

    # Study-area bounds (EPSG:32612) -> a polygon, projected into the tile CRS.
    left, bottom, right, top = config.GRID_BOUNDS
    gdf = gpd.GeoDataFrame(
        {"geometry": [box(left, bottom, right, top)]}, crs=config.CRS
    ).to_crs(da.rio.crs)
    return da.rio.clip(gdf.geometry.values, gdf.crs, drop=True, all_touched=True)


def clean_lst_tile(lst_path: Path, reference, min_valid_fraction: float):
    """Read + QC-mask + scale one granule tile and reproject it to the grid.

    Returns (aligned_lst_dataarray_or_None, GranuleStats); the DataArray is None
    when the granule is dropped as almost entirely missing.
    """
    gf = parse_granule_filename(lst_path.name)

    # Step 14 — read LST (scaled to Kelvin via metadata) + QC/cloud/water (raw).
    lst = _open_raw(lst_path, mask_and_scale=True)            # Kelvin floats, NaN fill
    qc = _open_raw(layer_path_for(lst_path, "QC"), mask_and_scale=False)
    cloud = _open_raw(layer_path_for(lst_path, "cloud"), mask_and_scale=False)
    water = _open_raw(layer_path_for(lst_path, "water"), mask_and_scale=False)

    # Restrict to the study area before stats so coverage is meaningful.
    lst = _clip_to_bbox(lst)
    qc = _clip_to_bbox(qc)
    cloud = _clip_to_bbox(cloud)
    water = _clip_to_bbox(water)

    # Step 15 — keep mandatory-QA 00+01, clear, land pixels; everything else
    # NaN. Retain a parallel 00-only count so the coverage choice is auditable.
    keep = build_keep_mask(lst.values, qc.values, cloud.values, water.values)
    best_only_keep = (
        np.isfinite(np.asarray(lst.values, dtype="float64"))
        & qc_best_quality_mask(qc.values)
        & (np.asarray(cloud.values) == CLOUD_CLEAR_VALUE)
        & (np.asarray(water.values) == WATER_LAND_VALUE)
    )
    clean_values = apply_keep_mask(lst.values, keep)
    lst_clean = lst.copy(data=clean_values)

    # Step 16 — drop / flag decisions on the cleaned, study-area data.
    stats = summarize_granule(clean_values, gf.overpass_key, gf.datetime_utc, gf.tile)
    stats.n_valid_best_only = int(best_only_keep.sum())
    stats.n_recovered_qc01 = stats.n_valid - stats.n_valid_best_only
    if decide_drop(stats, min_valid_fraction):
        stats.dropped = True
        log.warning("DROP  %s tile=%s — valid_fraction=%.4f < %.4f (near-empty)",
                    gf.overpass_key, gf.tile, stats.valid_fraction, min_valid_fraction)
        return None, stats
    stats.range_flagged = decide_range_flag(stats)
    if stats.range_flagged:
        log.warning(
            "FLAG  %s tile=%s — valid LST outside %.0f-%.0f K "
            "(min=%.2f max=%.2f, %d px out of range) — kept",
            gf.overpass_key, gf.tile, LST_PLAUSIBLE_K[0], LST_PLAUSIBLE_K[1],
            stats.lst_min, stats.lst_max, stats.n_out_of_range,
        )

    # Step 17 — reproject onto the 70 m grid (bilinear for the continuous field).
    aligned = lst_clean.rio.reproject_match(reference, resampling=Resampling.bilinear)
    aligned = aligned.rio.write_nodata(np.nan, encoded=False)
    return aligned, stats


# --- Build + save the cube (step 18) ---
def build_cube(
    lst_files: Iterable[Path],
    reference,
    min_valid_fraction: float,
) -> tuple["xr.DataArray", pd.DataFrame]:
    """Clean every granule, mosaic tiles within an overpass, and stack by time.

    Returns (cube, granule_report); cube dims are (time, y, x). Raw LST is never
    averaged across DIFFERENT overpasses.
    """
    per_overpass: dict[str, dict] = {}
    report_rows: list[dict] = []

    for lst_path in lst_files:
        aligned, stats = clean_lst_tile(lst_path, reference, min_valid_fraction)
        report_rows.append(stats.as_row())
        if aligned is None:
            continue
        slot = per_overpass.setdefault(
            stats.overpass_key, {"time": stats.datetime_utc, "tiles": []}
        )
        slot["tiles"].append(aligned)

    if not per_overpass:
        raise RuntimeError("No granules survived QC — nothing to stack.")

    # Mosaic tiles within each overpass, then order overpasses in time.
    times, slices, orbits, scenes = [], [], [], []
    for key in sorted(per_overpass, key=lambda k: per_overpass[k]["time"]):
        info = per_overpass[key]
        merged = info["tiles"][0]
        for extra in info["tiles"][1:]:
            merged = merged.where(np.isfinite(merged), extra)  # fill gaps from sibling tiles
        times.append(np.datetime64(info["time"].replace(tzinfo=None), "ns"))
        slices.append(merged)
        orbit, scene, _ = key.split("_")
        orbits.append(orbit)
        scenes.append(scene)

    cube = xr.concat(slices, dim="time")
    cube = cube.assign_coords(
        time=("time", np.array(times)),
        orbit=("time", np.array(orbits)),
        scene=("time", np.array(scenes)),
    ).sortby("time")
    cube.name = "lst"
    cube.attrs.update(
        long_name="ECOSTRESS land surface temperature (quality-controlled)",
        units="K",
        dataset=DATASET_ID,
        doi=COLLECTION_DOI,
        mandatory_qa_policy="keep 00 and 01; exclude 10 and 11",
        mandatory_qa_01_disclosure=(
            "01 may be degraded; included by professor-approved coverage decision"
        ),
        mandatory_qa_audit=(
            "See ecostress_lst_granule_report.csv columns n_valid_best_only "
            "and n_recovered_qc01"
        ),
        note=("Per-overpass LST on the Section-1 70 m grid. Time axis preserved; "
              "raw LST is NOT averaged across overpasses (overpass local times "
              "differ). Mandatory QA 00 and 01 are included; 01 is disclosed as "
              "potentially degraded. See Section 2 of the protocol."),
    )
    cube = cube.rio.write_crs(config.CRS)
    report = pd.DataFrame(report_rows)
    return cube, report


def save_cube_zarr(cube: "xr.DataArray", interim_dir: Path) -> Path:
    """Save the cube to data/interim/ecostress_lst_cube as Zarr."""
    interim_dir.mkdir(parents=True, exist_ok=True)
    out = interim_dir / CUBE_DIRNAME
    # Keep orbit/scene as data-less coordinate variables (string non-dim coords
    # do not ride along cleanly in zarr if they collide).
    ds = cube.to_dataset(name="lst")
    ds.to_zarr(out, mode="w", consolidated=True)
    log.info("Saved cube -> %s  dims=%s", out, dict(cube.sizes))
    return out


# --- Figures (deliverable: usable-obs count + mean-LST map) ---
def make_figures(cube: "xr.DataArray", figures_dir: Path) -> list[Path]:
    """Write the per-pixel usable-observation count and the mean-LST map."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    stack = cube.values  # (time, y, x)
    count = usable_observation_count(stack)
    mean = mean_lst_map(stack)

    left, bottom, right, top = config.GRID_BOUNDS
    extent = (left, right, bottom, top)
    outputs = []

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(count, extent=extent, origin="upper", cmap="viridis")
    ax.set_title("ECOSTRESS usable observations per pixel\n"
                 f"Phoenix {PILOT_START}..{PILOT_END}  (n_overpass={cube.sizes['time']})")
    ax.set_xlabel("Easting (m, EPSG:32612)")
    ax.set_ylabel("Northing (m, EPSG:32612)")
    fig.colorbar(im, ax=ax, label="count of usable overpasses")
    p1 = figures_dir / "ecostress_lst_usable_count.png"
    fig.savefig(p1, dpi=150, bbox_inches="tight")
    plt.close(fig)
    outputs.append(p1)

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(mean, extent=extent, origin="upper", cmap="inferno")
    ax.set_title("ECOSTRESS mean LST (visual QA only — not used in analysis)\n"
                 f"Phoenix {PILOT_START}..{PILOT_END}")
    ax.set_xlabel("Easting (m, EPSG:32612)")
    ax.set_ylabel("Northing (m, EPSG:32612)")
    fig.colorbar(im, ax=ax, label="mean LST (K)")
    p2 = figures_dir / "ecostress_lst_mean_map.png"
    fig.savefig(p2, dpi=150, bbox_inches="tight")
    plt.close(fig)
    outputs.append(p2)

    log.info("Wrote figures: %s", ", ".join(p.name for p in outputs))
    return outputs


# --- Orchestration / CLI ---
def run(
    max_granules: int | None = None,
    skip_download: bool = False,
    min_valid_fraction: float = DEFAULT_MIN_VALID_FRACTION,
) -> None:
    config.ensure_dirs()
    raw_dir = config.RAW_DIR / RAW_SUBDIR
    raw_dir.mkdir(parents=True, exist_ok=True)

    if skip_download:
        lst_files = discover_local_lst_files(raw_dir)
        log.info("--skip-download: found %d local LST COG(s)", len(lst_files))
        if not lst_files:
            raise SystemExit(f"No local granules in {raw_dir}; run without --skip-download.")
    else:
        authenticate()                                   # step 12
        results = search_granules(max_granules=max_granules)
        if not results:
            raise SystemExit("CMR search returned no granules for the bbox/window.")
        download_granules(results, raw_dir)              # step 13
        lst_files = discover_local_lst_files(raw_dir)

    reference = rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)

    cube, report = build_cube(lst_files, reference, min_valid_fraction)  # steps 14-18
    save_cube_zarr(cube, config.INTERIM_DIR)

    # Persist the granule-level QC report next to the cube for provenance.
    report_path = config.INTERIM_DIR / "ecostress_lst_granule_report.csv"
    report.to_csv(report_path, index=False)
    n_drop = int(report["dropped"].sum()) if len(report) else 0
    n_flag = int(report["range_flagged"].sum()) if len(report) else 0
    n_best = int(report["n_valid_best_only"].sum()) if len(report) else 0
    n_primary = int(report["n_valid"].sum()) if len(report) else 0
    n_recovered = int(report["n_recovered_qc01"].sum()) if len(report) else 0
    recovery_pct = (100.0 * n_recovered / n_best) if n_best else float("nan")
    log.info("Granule report -> %s  (%d dropped, %d range-flagged of %d tiles)",
             report_path, n_drop, n_flag, len(report))
    log.info(
        "Mandatory-QA coverage audit: 00-only=%s px; 00+01=%s px; "
        "QC=01 recovered=%s px (%+.2f%% vs 00-only)",
        f"{n_best:,}", f"{n_primary:,}", f"{n_recovered:,}", recovery_pct,
    )

    make_figures(cube, config.FIGURES_DIR)
    log.info("Section 2 complete: cube=%s  overpasses=%d",
             config.INTERIM_DIR / CUBE_DIRNAME, cube.sizes["time"])


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Section 2 — ECOSTRESS LST acquisition & QC.")
    p.add_argument("--max-granules", type=int, default=None,
                   help="cap the number of granules (quick smoke test).")
    p.add_argument("--skip-download", action="store_true",
                   help="reuse COGs already in data/raw/ecostress_lst/.")
    p.add_argument("--min-valid-fraction", type=float, default=DEFAULT_MIN_VALID_FRACTION,
                   help="drop a granule if fewer than this fraction of study-area "
                        "pixels survive QC (default %(default)s).")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    run(
        max_granules=args.max_granules,
        skip_download=args.skip_download,
        min_valid_fraction=args.min_valid_fraction,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
