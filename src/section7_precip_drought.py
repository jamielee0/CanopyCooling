#!/usr/bin/env python3
"""Section 7 / precip_drought - acquire precipitation history and drought state, gridded to 70 m.

Inputs : PRISM web service (daily ppt + tmean, ~4 km); GRIDMET DROUGHT via Earth Engine (~4638 m);
         Section 1 reference grid (config.REFERENCE_GRID_TIF). Raw clips cached in data/raw/{prism,drought}/.
Outputs: data/interim/ Zarr cubes on the 70 m grid (EPSG:32612), plus QA figures:
         prism_antecedent_precip_70m.zarr (ppt_30d/60d/90d), prism_tmean_70m.zarr (tmean),
         gridmet_drought_70m.zarr (pdsi/spei30d/spei90d).
Key decisions (full rationale in docs/DESIGN_DECISIONS.md, Section 7):
  - PRISM ppt runs from 2018-01-01 (lead-in) so the 90-day antecedent window is complete from season start.
  - Coarse regional fields resampled to 70 m: bilinear throughout (continuous quantities), regional context only.
  - PRISM via the get/us/<res> endpoint; 800 m product averaged onto the 4 km clip self-heals rate-limited days.
  - GRIDMET DROUGHT pulled direct with geemap.download_ee_image at native scale (never Export.image.toDrive).
  - Antecedent series needs a complete daily record; any gap skips the cube rather than faking it.
Run: python src/section7_precip_drought.py [--skip-prism] [--skip-drought] [--skip-download]
                                           [--years 2023] [--no-figures] [-v]
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as _dt
import hashlib
import io
import logging
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable, Sequence

import numpy as np
import pandas as pd

# Heavy geospatial / EE libraries are imported lazily inside the functions that
# need them, so the pure-numpy/pandas logic stays unit-testable without the geo /
# EE stack installed (see test_section7_*).
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

log = logging.getLogger("section7")


# --- Manifest / checksum / dotenv helpers (inlined so Section 7 stays self-
# --- contained; it has no NASA Earthdata dependency, so it must not import
# --- section2 just to append a manifest row). Same five-column schema as Section 0.
_MANIFEST_COLUMNS = ["source", "dataset", "filename", "download_date", "checksum"]


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Streaming SHA-256 of a file (large rasters are not loaded whole)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def append_to_manifest(rows: Sequence[dict], manifest_csv: Path | None = None) -> None:
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


def _load_project_dotenv() -> None:
    """Load the gitignored repo-root .env into the environment without overwriting real vars."""
    import os
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


def harden_ssl_if_needed() -> bool:
    """Route https through certifi's CA bundle iff the host's default SSL context is broken.

    A no-op on a healthy host. On Windows a malformed cert in the system store can make
    ssl.create_default_context() raise, breaking every https client in the process; this
    skips the system store only when it cannot be built. Returns True if the fallback was installed.
    """
    import ssl
    try:
        ssl.create_default_context()
        return False                              # healthy host: nothing to do
    except Exception as exc:                       # noqa: BLE001
        try:
            import certifi
        except Exception:                          # noqa: BLE001
            log.error("Default SSL context failed (%s) and certifi is unavailable; "
                      "https downloads will fail.", exc)
            return False
        import os
        ca = certifi.where()
        for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
            os.environ.setdefault(var, ca)         # requests / GDAL /vsicurl
        _orig = ssl.create_default_context

        def _patched(purpose=ssl.Purpose.SERVER_AUTH, *, cafile=None,
                     capath=None, cadata=None):
            if cafile is None and capath is None and cadata is None:
                cafile = ca                        # certifi instead of the broken store
            return _orig(purpose, cafile=cafile, capath=capath, cadata=cadata)

        ssl.create_default_context = _patched
        ssl._create_default_https_context = lambda *a, **k: _patched()
        log.warning("Default SSL context unavailable (%s: %s) - the host trust store "
                    "looks corrupt. Routing all https through certifi (%s) for this run.",
                    type(exc).__name__, exc, ca)
        return True


# --- Confirmed source constants (logged at run time).
# PRISM "get/us/<res>" endpoint serves one CONUS daily GeoTIFF per element/day,
# EPSG:4269, nodata -9999. 4 km is the protocol product; 800 m is a separate file
# with its own per-file rate-limit counter, used only as a self-healing fallback.
PRISM_WS_BASE = "https://services.nacse.org/prism/data/get/us"
PRISM_RES = "4km"
PRISM_RES_FALLBACK = "800m"
PRISM_DATASET_ID = "PRISM_daily_4km"             # recorded in the manifest
PRISM_USER_AGENT = "canopy-protocol/1.0 (urban-canopy thermal-threshold study)"

# ppt needs the full record (lead-in for the antecedent windows); tmean only the
# analysis seasons. PERIOD_END is the protocol's "September 2024".
PPT_START = "2018-01-01"
PERIOD_END = "2024-09-30"

ANTECEDENT_WINDOWS = (30, 60, 90)
# "Preceding N days" excludes the observation day itself; flip to True for the
# inclusive N-day total ending on D.
ANTECEDENT_INCLUSIVE = False

# GRIDMET DROUGHT (Earth Engine): pdsi + 30/90-day SPEI, matching the 30/90-day
# antecedent-precip windows. Native scale ~4638 m; the collection is pentad.
DROUGHT_COLLECTION = "GRIDMET/DROUGHT"
DROUGHT_VARS = ("pdsi", "spei30d", "spei90d")
DROUGHT_NATIVE_SCALE_M = 4638.312116386398       # confirmed from EE projection

# Per-tile size ladder (MB) for the resilient EE download, mirroring Section 4.
MAX_TILE_SIZES_MB = (32, 16, 8, 4, 2)
MAX_REQUESTS = 8                                 # cap concurrent EE tile requests

# Buffer the clip / EE region so the 70 m grid edges have surrounding coarse cells
# for bilinear resampling (no edge NaNs).
CLIP_BUFFER_DEG = 0.15

# Polite concurrency + retry for the PRISM web service.
PRISM_MAX_WORKERS = 5
PRISM_RETRIES = 4
PRISM_BACKOFF_S = 2.0
PRISM_TIMEOUT_S = 120

RAW_PRISM_SUBDIR = "prism"                       # data/raw/prism/
RAW_DROUGHT_SUBDIR = "drought"                   # data/raw/drought/

# Gridded (interim) Zarr stores on the 70 m reference grid.
ANTECEDENT_ZARR = "prism_antecedent_precip_70m.zarr"
TMEAN_ZARR = "prism_tmean_70m.zarr"
DROUGHT_ZARR = "gridmet_drought_70m.zarr"

# Time-block size (days) for the streaming reproject->Zarr append; 15 keeps peak
# memory well under 1 GB regardless of how many seasons are gridded.
GRID_CHUNK_DAYS = 15

# Plausible physical ranges for the QC sanity log (Phoenix warm season).
PPT_VALID_RANGE = (0.0, 400.0)                   # daily mm
TMEAN_VALID_RANGE = (-20.0, 55.0)                # degC


# --- Pure date / URL / parsing logic (no geo or EE deps; unit-tested) ---
def season_dates(years: Sequence[int], season: tuple[str, str] = config.SEASON
                 ) -> list[_dt.date]:
    """Every calendar date inside the warm season (MM-DD..MM-DD) for each year."""
    start_mmdd, end_mmdd = season
    out: list[_dt.date] = []
    for yr in years:
        start = _dt.date.fromisoformat(f"{yr}-{start_mmdd}")
        end = _dt.date.fromisoformat(f"{yr}-{end_mmdd}")
        d = start
        while d <= end:
            out.append(d)
            d += _dt.timedelta(days=1)
    return out


def daily_dates(start: str, end: str) -> list[_dt.date]:
    """Every calendar date in [start, end] inclusive (ISO yyyy-mm-dd strings)."""
    d0 = _dt.date.fromisoformat(start)
    d1 = _dt.date.fromisoformat(end)
    out: list[_dt.date] = []
    d = d0
    while d <= d1:
        out.append(d)
        d += _dt.timedelta(days=1)
    return out


def prism_url(element: str, date: _dt.date, res: str = PRISM_RES) -> str:
    """PRISM web-service URL for one element/day, e.g. .../get/us/4km/ppt/20180601."""
    return f"{PRISM_WS_BASE}/{res}/{element}/{date:%Y%m%d}"


def prism_raw_filename(element: str, date: _dt.date) -> str:
    """Local name for the bbox-clipped native-resolution PRISM day."""
    return f"prism_{element}_{date:%Y%m%d}_bbox.tif"


def pick_raster_member(names: Sequence[str]) -> str:
    """Pick the raster file inside a PRISM zip (.tif now; .bil on older archives)."""
    for ext in (".tif", ".bil"):
        for n in names:
            if n.lower().endswith(ext):
                return n
    raise ValueError(f"no .tif/.bil raster member in PRISM zip: {list(names)}")


def parse_drought_band(name: str, vars_: Sequence[str] = DROUGHT_VARS
                       ) -> tuple[str | None, str]:
    """Parse an EE ``toBands`` band name ``<system:index>_<var>`` into (yyyymmdd, variable).

    Date is None when the leading token is not an 8-digit date (some EE builds emit
    positional ``0_pdsi``); the caller then supplies it from the image's time list.
    """
    var = next((v for v in sorted(vars_, key=len, reverse=True)
                if name.endswith("_" + v) or name == v), None)
    if var is None:
        raise ValueError(f"band {name!r} matches none of {tuple(vars_)}")
    prefix = name[: -(len(var) + 1)] if name != var else ""
    token = prefix.split("_")[0] if prefix else ""
    date = token if (len(token) == 8 and token.isdigit()) else None
    return date, var


def system_time_to_date_token(value) -> str:
    """Convert an Earth Engine ``system:time_start`` value to ``YYYYMMDD``.

    Earth Engine returns milliseconds since the Unix epoch, but accepting an ISO-like
    timestamp as well keeps the resolver testable and defensive. Invalid or missing
    metadata raises instead of manufacturing a date.
    """
    if value is None:
        raise ValueError("missing system:time_start")
    if isinstance(value, (int, float, np.integer, np.floating)):
        if not np.isfinite(value):
            raise ValueError(f"invalid system:time_start {value!r}")
        ts = pd.to_datetime(value, unit="ms", utc=True)
    else:
        ts = pd.Timestamp(value)
    if pd.isna(ts):
        raise ValueError(f"invalid system:time_start {value!r}")
    return ts.strftime("%Y%m%d")


def expand_drought_band_dates(system_times: Sequence, n_vars: int) -> list[str]:
    """Expand image dates to Earth Engine ``toBands`` image-major band order."""
    if int(n_vars) <= 0:
        raise ValueError("n_vars must be positive")
    dates = [system_time_to_date_token(value) for value in system_times]
    return [date for date in dates for _ in range(int(n_vars))]


def _validated_date_token(value: str, *, context: str) -> str:
    """Validate and normalize a compact drought date token."""
    token = str(value)
    try:
        parsed = _dt.datetime.strptime(token, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"{context}: invalid YYYYMMDD date {token!r}") from exc
    return parsed.strftime("%Y%m%d")


def resolve_band_date(name: str, system_date: str | None,
                      vars_: Sequence[str] = DROUGHT_VARS) -> tuple[str, str]:
    """Resolve one drought band to ``(YYYYMMDD, variable)`` or fail closed.

    A date encoded in the band name is checked against the date derived from the
    image's ``system:time_start``. Positional names use that system date. If neither
    source resolves the date, or the two sources disagree, the band is rejected with
    an error rather than silently disappearing from the drought cube.
    """
    parsed_date, var = parse_drought_band(name, vars_)
    parsed = (_validated_date_token(parsed_date, context=f"band {name!r}")
              if parsed_date is not None else None)
    fallback = (_validated_date_token(system_date, context=f"band {name!r} system time")
                if system_date is not None else None)
    if parsed is None and fallback is None:
        raise ValueError(f"band {name!r}: no date in name and no system:time_start fallback")
    if parsed is not None and fallback is not None and parsed != fallback:
        raise ValueError(
            f"band {name!r}: name date {parsed} disagrees with system date {fallback}")
    return (parsed or fallback), var


# --- Pure antecedent-precipitation logic (numpy; unit-tested) ---
def antecedent_sum(daily: np.ndarray, window: int,
                   inclusive: bool = ANTECEDENT_INCLUSIVE) -> np.ndarray:
    """Rolling total over the preceding ``window`` days, along axis 0 (time).

    O(time) via cumulative sums; identical for the 1-D and gridded 3-D cases. NaNs are
    treated as 0 for the running total but propagate into any window that contains them,
    so an incomplete record never reads as a (smaller) complete one. Positions without a
    complete window are NaN.
    """
    arr = np.asarray(daily, dtype="float64")
    n = arr.shape[0]
    finite = np.isfinite(arr)
    filled = np.where(finite, arr, 0.0)

    # Prefix sums with a leading zero row: P[k] = sum(filled[0:k]).
    zero = np.zeros((1,) + arr.shape[1:], dtype="float64")
    P = np.concatenate([zero, np.cumsum(filled, axis=0)], axis=0)        # (n+1, ...)
    C = np.concatenate([np.zeros((1,) + arr.shape[1:], dtype="int64"),
                        np.cumsum(finite, axis=0)], axis=0)              # finite count

    out = np.full(arr.shape, np.nan, dtype="float64")
    for t in range(n):
        hi = t + 1 if inclusive else t          # window is [lo, hi) in prefix terms
        lo = hi - window
        if lo < 0:
            continue                            # incomplete window -> stays NaN
        total = P[hi] - P[lo]
        ok = (C[hi] - C[lo]) == window          # every day in the window was finite
        out[t] = np.where(ok, total, np.nan)
    return out


# --- PRISM web-service download (steps 37, 40) ---
@dataclasses.dataclass
class ClipWindow:
    """A fixed pixel window into the (constant) PRISM CONUS grid + its transform."""
    col_off: int
    row_off: int
    width: int
    height: int
    transform: object                            # rasterio Affine for the window
    crs: object


def _http_get(url: str, retries: int = PRISM_RETRIES) -> bytes:
    """GET with small exponential backoff; raises on final failure."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": PRISM_USER_AGENT})
            with urllib.request.urlopen(req, timeout=PRISM_TIMEOUT_S) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(PRISM_BACKOFF_S * (2 ** attempt))
    raise RuntimeError(f"GET failed after {retries} tries: {url}: {last}")


@contextlib.contextmanager
def _open_prism_raster(zip_bytes: bytes):
    """Yield an open rasterio dataset for the raster member of a PRISM zip.

    A context manager so the MemoryFile / temp-dir backing store stays alive for the
    ``with`` block (a bare dataset would be freed underneath GDAL and segfault on read).
    Raises if the payload is not a zip (e.g. an HTML notice) or has no raster member.
    """
    import rasterio
    from rasterio.io import MemoryFile

    if zip_bytes[:2] != b"PK":                    # zip local-file-header magic
        head = zip_bytes[:200].decode("utf-8", "replace")
        raise ValueError(f"PRISM payload is not a zip (got {len(zip_bytes)} B): {head!r}")
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    member = pick_raster_member(zf.namelist())
    if member.lower().endswith(".tif"):
        with MemoryFile(zf.read(member)) as mem, mem.open() as ds:
            yield ds
    else:                                         # .bil: needs its sibling files
        import shutil
        import tempfile
        td = tempfile.mkdtemp(prefix="prism_")
        try:
            zf.extractall(td)
            with rasterio.open(Path(td) / member) as ds:
                yield ds
        finally:
            shutil.rmtree(td, ignore_errors=True)


def _compute_clip_window(ds, bbox_lonlat=config.BBOX_LONLAT,
                         buffer_deg: float = CLIP_BUFFER_DEG) -> ClipWindow:
    """Integer pixel window covering bbox+buffer in the PRISM grid (constant daily)."""
    from rasterio.windows import Window, from_bounds, transform as win_transform

    min_lon, max_lon, min_lat, max_lat = bbox_lonlat
    w = from_bounds(min_lon - buffer_deg, min_lat - buffer_deg,
                    max_lon + buffer_deg, max_lat + buffer_deg, ds.transform)
    col_off = int(np.floor(w.col_off))
    row_off = int(np.floor(w.row_off))
    width = int(np.ceil(w.col_off + w.width)) - col_off
    height = int(np.ceil(w.row_off + w.height)) - row_off
    # Clamp to the grid.
    col_off = max(0, col_off)
    row_off = max(0, row_off)
    width = min(width, ds.width - col_off)
    height = min(height, ds.height - row_off)
    win = Window(col_off, row_off, width, height)
    return ClipWindow(col_off, row_off, width, height,
                      win_transform(win, ds.transform), ds.crs)


_NODATA = -9999.0


def _read_window(ds, win: ClipWindow) -> np.ndarray:
    """Read the bbox window from an open PRISM dataset as a float32 array."""
    from rasterio.windows import Window
    return ds.read(1, window=Window(win.col_off, win.row_off, win.width, win.height)
                   ).astype("float32")


def _yx_coords(win: ClipWindow) -> dict:
    """Cell-centre y/x coordinate vectors for a clip window's Affine transform."""
    a = win.transform                            # (a=xres, b, c=left, d, e=-yres, f=top)
    xs = a.c + (np.arange(win.width) + 0.5) * a.a
    ys = a.f + (np.arange(win.height) + 0.5) * a.e
    return {"y": ys, "x": xs}


def _win_template(win: ClipWindow) -> "xr.DataArray":
    """An empty rioxarray DataArray on the 4 km clip grid (a resample target)."""
    t = xr.DataArray(np.zeros((win.height, win.width), "float32"),
                     dims=("y", "x"), coords=_yx_coords(win))
    t.rio.write_crs(win.crs, inplace=True)
    t.rio.write_transform(win.transform, inplace=True)
    return t


def _write_clip(arr: np.ndarray, win: ClipWindow, out_path: Path) -> Path:
    """Write a clipped float32 array as a small GeoTIFF on the clip-window grid."""
    import rasterio
    out = np.where(np.isfinite(arr), arr, _NODATA).astype("float32")
    profile = dict(driver="GTiff", height=win.height, width=win.width, count=1,
                   dtype="float32", crs=win.crs, transform=win.transform,
                   nodata=_NODATA, compress="deflate")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(out, 1)
    return out_path


def _fetch_prism_800m_on_grid(element: str, date: _dt.date,
                              win: ClipWindow) -> np.ndarray:
    """Fetch the 800 m product and average it DOWN onto the 4 km clip grid.

    Used only when the 4 km day is rate-limited. PRISM's 4 km grid is itself an upscale
    of the 800 m grid, so this is a faithful stand-in that keeps the daily stack aligned.
    """
    with _open_prism_raster(_http_get(prism_url(element, date, PRISM_RES_FALLBACK))) as ds:
        w800 = _compute_clip_window(ds)
        a = _read_window(ds, w800)
        nod = ds.nodata if ds.nodata is not None else _NODATA
        src = xr.DataArray(np.where(a == nod, np.nan, a), dims=("y", "x"),
                           coords=_yx_coords(w800))
        src.rio.write_crs(ds.crs, inplace=True)
        src.rio.write_transform(w800.transform, inplace=True)
    matched = src.rio.reproject_match(_win_template(win), resampling=Resampling.average)
    return matched.values.astype("float32")


def _fetch_prism_clip(element: str, date: _dt.date,
                      win: ClipWindow | None) -> tuple[np.ndarray, ClipWindow, str]:
    """Fetch one PRISM day clipped to the bbox window. Returns (array, win, source).

    Tries 4 km first; a rate-limited day (non-zip notice -> ValueError) self-heals via
    the 800 m product averaged onto the same clip grid. The first day must come from
    4 km (it establishes the shared clip window).
    """
    try:
        with _open_prism_raster(_http_get(prism_url(element, date, PRISM_RES))) as ds:
            if win is None:
                win = _compute_clip_window(ds)
            arr = _read_window(ds, win)
            nod = ds.nodata if ds.nodata is not None else _NODATA
        return np.where(arr == nod, np.nan, arr), win, PRISM_RES
    except ValueError as exc:                    # non-zip payload => per-file rate limit
        if win is None:
            raise
        log.warning("PRISM %s %s: 4 km unavailable (%s); falling back to 800 m",
                    element, date, exc)
        return _fetch_prism_800m_on_grid(element, date, win), win, "800m->4km"


def prism_service_ok(element: str = "ppt", date: _dt.date | None = None) -> bool:
    """Smoke-test the PRISM web service with a single day (step 37 pre-flight).

    True if the service responds sensibly - a real zip+raster, or the per-file
    rate-limit notice (which still proves it is up). Only a genuine non-response or an
    unrecognised payload returns False, so the orchestrator can ask for a manual download.
    """
    date = date or _dt.date.fromisoformat(PPT_START)
    url = prism_url(element, date)
    log.info("PRISM smoke test: GET %s", url)
    try:
        raw = _http_get(url)
    except Exception as exc:  # noqa: BLE001 - no response => service unavailable
        log.error("PRISM smoke test FAILED (no response): %s: %s", type(exc).__name__, exc)
        return False
    if raw[:2] == b"PK":                          # got a zip: open it to be sure
        try:
            with _open_prism_raster(raw) as ds:
                log.info("PRISM smoke test OK: CONUS %dx%d, crs=%s, nodata=%s",
                         ds.height, ds.width, ds.crs, ds.nodata)
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("PRISM smoke test FAILED (bad zip): %s: %s", type(exc).__name__, exc)
            return False
    text = raw[:300].decode("utf-8", "replace")
    if "more than twice" in text or "blocked" in text.lower():
        log.info("PRISM smoke test: service UP (probe file is rate-limited today, "
                 "which is expected on a same-day re-run): %s", text.strip())
        return True
    log.error("PRISM smoke test FAILED (unexpected payload): %s", text.strip())
    return False


def download_prism_day(element: str, date: _dt.date, raw_dir: Path,
                       win: ClipWindow | None) -> tuple[Path, ClipWindow, bool, str]:
    """Download one PRISM day, clip to the bbox window, write a small GeoTIFF.

    Resumable: an existing clip is reused (no HTTP). Returns (path, clip_window,
    downloaded?, source), where source is "4km" / "800m->4km" / "cached".
    """
    out_path = raw_dir / prism_raw_filename(element, date)
    if out_path.exists() and out_path.stat().st_size > 0:
        # Pass ``win`` THROUGH unchanged - never rebuild it from the cached clip. The
        # clip's own window is (0, 0, clip_w, clip_h); using that to read a fresh CONUS
        # grid would read its offshore top-left corner instead of the Phoenix bbox.
        return out_path, win, False, "cached"
    arr, win, source = _fetch_prism_clip(element, date, win)
    _write_clip(arr, win, out_path)
    return out_path, win, True, source


def download_prism_series(element: str, dates: Sequence[_dt.date], raw_dir: Path,
                          max_workers: int = PRISM_MAX_WORKERS
                          ) -> tuple[dict[_dt.date, Path], ClipWindow, list[_dt.date]]:
    """Download a whole element series (resumable, polite thread pool, resilient).

    The first day is fetched alone to establish the shared clip window; the rest run
    concurrently, with errored days retried once sequentially. New files are recorded in
    the manifest. Returns (date->path map, clip_window, still_failed_dates) - the caller
    decides whether a gap is tolerable (it is not, for the antecedent series).
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    dates = list(dates)
    log.info("PRISM %s: %d day(s) %s..%s -> %s", element, len(dates),
             dates[0], dates[-1], raw_dir)

    first_path, win, first_dl, first_src = download_prism_day(element, dates[0], raw_dir, None)
    results: dict[_dt.date, Path] = {dates[0]: first_path}
    sources: dict[_dt.date, str] = {dates[0]: first_src}
    n_downloaded = int(first_dl)
    failed: list[_dt.date] = []

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(download_prism_day, element, d, raw_dir, win): d for d in dates[1:]}
        done = 0
        for fut in as_completed(futs):
            d = futs[fut]
            try:
                path, _win, dl, src = fut.result()
                results[d] = path
                sources[d] = src
                n_downloaded += int(dl)
            except Exception as exc:  # noqa: BLE001 - collect, retry below
                failed.append(d)
                if len(failed) <= 10:
                    log.warning("  PRISM %s %s failed: %s: %s", element, d,
                                type(exc).__name__, exc)
            done += 1
            if done % 200 == 0:
                log.info("  PRISM %s: %d/%d done (%d new, %d failed so far)",
                         element, done, len(dates) - 1, n_downloaded, len(failed))

    # Patient sequential retry of the stragglers.
    still_failed: list[_dt.date] = []
    for d in failed:
        try:
            path, _win, dl, src = download_prism_day(element, d, raw_dir, win)
            results[d] = path
            sources[d] = src
            n_downloaded += int(dl)
        except Exception as exc:  # noqa: BLE001
            still_failed.append(d)
            log.error("  PRISM %s %s still failing after retry: %s: %s", element, d,
                      type(exc).__name__, exc)

    newly = [(d, results[d], sources[d]) for d in dates
             if d in results and sources.get(d) != "cached"]
    _record_prism_manifest(element, newly)
    log.info("PRISM %s: %d/%d files present (%d new, %d unresolved)", element,
             len(results), len(dates), n_downloaded, len(still_failed))
    return results, win, still_failed


def _record_prism_manifest(element: str,
                           day_paths: Sequence[tuple[_dt.date, Path, str]]) -> None:
    """Append one manifest row per NEW PRISM day (source URL + checksum of the clip)."""
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    rows = []
    for date, path, source in day_paths:
        res = PRISM_RES_FALLBACK if source.startswith("800m") else PRISM_RES
        note = " [800m fallback, averaged to 4km]" if source.startswith("800m") else ""
        rows.append({
            "source": f"{prism_url(element, date, res)} "
                      f"(PRISM daily {element}; bbox subset{note})",
            "dataset": PRISM_DATASET_ID,
            "filename": path.name,
            "download_date": today,
            "checksum": f"sha256:{sha256_file(path)}",
        })
    append_to_manifest(rows)


# --- GRIDMET DROUGHT via Earth Engine (step 39) - geemap.download_ee_image (geedim) ---
def initialize_ee() -> str:
    """Initialise Earth Engine, returning the project id (mirrors Section 4)."""
    import os

    import ee
    _load_project_dotenv()
    project = (os.environ.get("EARTHENGINE_PROJECT")
               or os.environ.get("GOOGLE_CLOUD_PROJECT")
               or config.EARTHENGINE_PROJECT)
    if project:
        ee.Initialize(project=project)
    else:
        ee.Initialize()
    log.info("Earth Engine: initialised (project=%s)", project or "default")
    return project or "default"


def drought_region(buffer_deg: float = CLIP_BUFFER_DEG):
    """Buffered bbox as a non-geodesic WGS84 rectangle for the EE region pull."""
    import ee
    min_lon, max_lon, min_lat, max_lat = config.BBOX_LONLAT
    return ee.Geometry.Rectangle(
        [min_lon - buffer_deg, min_lat - buffer_deg,
         max_lon + buffer_deg, max_lat + buffer_deg],
        proj="EPSG:4326", geodesic=False)


def drought_raw_filename(year: int) -> str:
    return f"gridmet_drought_{year}.tif"


def _year_filter_dates(year: int) -> tuple[str, str]:
    """[start, end) for one calendar year, clamped to the project period."""
    start = max(f"{year}-01-01", PPT_START)
    end = min(f"{year + 1}-01-01", _next_day(PERIOD_END))
    return start, end


def _next_day(iso: str) -> str:
    return (_dt.date.fromisoformat(iso) + _dt.timedelta(days=1)).isoformat()


@dataclasses.dataclass
class DroughtDownload:
    """Outcome of acquiring one year of GRIDMET DROUGHT."""
    year: int
    path: Path | None
    band_names: list[str]
    method: str
    max_tile_size_mb: float | None = None
    # One YYYYMMDD token per raster band, derived from system:time_start. Kept as
    # a defaulted final field so existing dated-name callers remain compatible.
    band_dates: list[str] = dataclasses.field(default_factory=list)

    @property
    def is_local(self) -> bool:
        return self.path is not None


def download_drought_year(year: int, region, raw_dir: Path,
                          vars_: Sequence[str] = DROUGHT_VARS,
                          tile_sizes_mb: Sequence[float] = MAX_TILE_SIZES_MB,
                          scale_m: float = DROUGHT_NATIVE_SCALE_M) -> DroughtDownload:
    """Download one year of GRIDMET DROUGHT to a native-scale multi-band GeoTIFF.

    Pentad images are stacked with ``toBands`` (bands ``<yyyymmdd>_<var>``) and pulled in
    EPSG:32612 at native scale (a few pixels across). On a compute/size failure the
    per-tile size is reduced; if all sizes fail the caller triggers the SPEI-file
    fallback. Resumable: an existing file is reused.
    """
    import ee
    import geemap

    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / drought_raw_filename(year)
    start, end = _year_filter_dates(year)
    col = (ee.ImageCollection(DROUGHT_COLLECTION)
           .filterBounds(region).filterDate(start, end).select(list(vars_))
           .sort("system:time_start"))
    system_times = col.aggregate_array("system:time_start").getInfo()
    image = col.toBands()
    band_names = image.bandNames().getInfo()
    band_dates = expand_drought_band_dates(system_times, len(vars_))
    if len(band_names) != len(band_dates):
        raise RuntimeError(
            f"Drought {year}: {len(band_names)} toBands names but "
            f"{len(band_dates)} dates from system:time_start")
    log.info("Drought %d: %s..%s, %d bands (%d pentads x %d vars)",
             year, start, end, len(band_names), len(band_names) // len(vars_), len(vars_))

    if out_path.exists() and out_path.stat().st_size > 0:
        log.info("Drought %d: reusing %s", year, out_path.name)
        return DroughtDownload(year, out_path, band_names, "(reused local file)",
                               band_dates=band_dates)

    last_exc: Exception | None = None
    for mts in tile_sizes_mb:
        try:
            geemap.download_ee_image(
                image, str(out_path), region=region, crs=config.CRS, scale=scale_m,
                resampling="bilinear", overwrite=True, max_tile_size=mts,
                num_threads=MAX_REQUESTS, max_requests=MAX_REQUESTS)
            log.info("Drought %d downloaded (%.2f MB, max_tile_size=%sMB)",
                     year, out_path.stat().st_size / 1e6, mts)
            return DroughtDownload(year, out_path, band_names,
                                   "geemap.download_ee_image", mts,
                                   band_dates=band_dates)
        except Exception as exc:  # noqa: BLE001 - retry smaller, then SPEI fallback
            last_exc = exc
            log.warning("Drought %d download failed at max_tile_size=%sMB: %s: %s",
                        year, mts, type(exc).__name__, exc)
    log.error("Drought %d: all tile sizes failed (last: %s: %s)",
              year, type(last_exc).__name__, last_exc)
    return DroughtDownload(year, None, band_names, "FAILED", band_dates=band_dates)


# --- Reproject + assemble onto the 70 m grid (step 41) -> Zarr cubes ---
def _open_reference():
    """The 70 m reference grid as a 2-D rioxarray DataArray (the match target)."""
    return rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)


def _native_stack_dataarray(paths: Sequence[Path], dates: Sequence[_dt.date],
                            name: str) -> "xr.DataArray":
    """Stack aligned single-band native PRISM GeoTIFFs into a (time, y, x) cube.

    Every file shares the same clip window; nodata is masked to NaN. An entirely-nodata
    clip is treated as a bug (a resumed-run wrong-window read) and refused.
    """
    first = rioxarray.open_rasterio(paths[0], masked=True).squeeze("band", drop=True)
    data = np.empty((len(paths), first.sizes["y"], first.sizes["x"]), dtype="float32")
    empty: list[str] = []
    for i, p in enumerate(paths):
        da = rioxarray.open_rasterio(p, masked=True).squeeze("band", drop=True)
        data[i] = da.values
        if not np.isfinite(data[i]).any():       # an entirely-nodata clip is a bug
            empty.append(p.name)
    if empty:
        log.error("%s: %d/%d native clips are ENTIRELY nodata (e.g. %s) - these "
                  "would grid to all-NaN; delete them from data/raw/prism/ and "
                  "re-download.", name, len(empty), len(paths), empty[:5])
        raise RuntimeError(f"{name}: {len(empty)} all-nodata clip(s); refusing to "
                           f"build a cube with empty seasons (first: {empty[0]})")
    cube = xr.DataArray(
        data, dims=("time", "y", "x"),
        coords={"time": pd.to_datetime(list(dates)), "y": first.y.values, "x": first.x.values},
        name=name)
    cube.rio.write_crs(first.rio.crs, inplace=True)
    cube.rio.write_transform(first.rio.transform(), inplace=True)
    return cube


def _resample_native_2d(arr2d: np.ndarray, crs, transform, yv: np.ndarray,
                        xv: np.ndarray, reference,
                        resampling=Resampling.bilinear) -> np.ndarray:
    """Reproject ONE small native 2-D layer onto the 70 m reference grid."""
    da = xr.DataArray(np.asarray(arr2d, dtype="float32"), dims=("y", "x"),
                      coords={"y": yv, "x": xv})
    da.rio.write_crs(crs, inplace=True)
    da.rio.write_transform(transform, inplace=True)
    return da.rio.reproject_match(reference, resampling=resampling).values.astype("float32")


def _resample_native_block(slices: np.ndarray, crs, transform, yv: np.ndarray,
                           xv: np.ndarray, reference,
                           resampling=Resampling.bilinear) -> np.ndarray:
    """Reproject a small (k, y, x) native block onto the 70 m grid, slice by slice.

    On-demand (per Zarr block) so peak memory is one block of 70 m slices, never the
    whole multi-year cube.
    """
    ny, nx = reference.sizes["y"], reference.sizes["x"]
    out = np.empty((len(slices), ny, nx), dtype="float32")
    for i, layer in enumerate(slices):
        out[i] = _resample_native_2d(layer, crs, transform, yv, xv, reference, resampling)
    return out


def _zarr_encoding(var_names: Sequence[str], ny: int, nx: int) -> dict:
    """Compressed, time-chunked Zarr encoding (one 70 m slice per chunk)."""
    import numcodecs
    comp = numcodecs.Blosc(cname="zstd", clevel=5, shuffle=numcodecs.Blosc.SHUFFLE)
    return {v: {"compressor": comp, "chunks": (1, ny, nx)} for v in var_names}


def write_grid_cube_zarr(store: Path, dates: Sequence[_dt.date],
                         layer_provider: Callable[[Sequence[int]], dict],
                         var_names: Sequence[str], reference,
                         chunk_days: int = GRID_CHUNK_DAYS) -> Path:
    """Stream a gridded cube to a Zarr store, appending GRID_CHUNK_DAYS at a time.

    ``layer_provider(indices)`` returns {var_name: (k, y, x) float32 array} already on
    the 70 m grid. Bounded peak memory = one block per variable.
    """
    if store.exists():
        import shutil
        shutil.rmtree(store)
    ny, nx = reference.sizes["y"], reference.sizes["x"]
    times = pd.to_datetime(list(dates))
    n = len(times)
    first = True
    for lo in range(0, n, chunk_days):
        hi = min(lo + chunk_days, n)
        block = layer_provider(list(range(lo, hi)))
        ds = xr.Dataset(
            {v: (("time", "y", "x"), block[v]) for v in var_names},
            coords={"time": times[lo:hi], "y": reference.y.values, "x": reference.x.values})
        ds = ds.rio.write_crs(reference.rio.crs)
        # Pin the CF grid_mapping in each var's ATTRS so it survives to_zarr (the explicit
        # per-var `encoding` below otherwise drops rioxarray's grid_mapping). Reopen with
        # decode_coords="all" to recover the CRS, like the Section 2/3 cubes.
        for v in var_names:
            ds[v].attrs["grid_mapping"] = "spatial_ref"
        if first:
            ds.to_zarr(store, mode="w", encoding=_zarr_encoding(var_names, ny, nx),
                       consolidated=True)
            first = False
        else:
            ds.to_zarr(store, append_dim="time", consolidated=True)
        log.info("  %s: wrote days %d..%d/%d", store.name, lo, hi, n)
    log.info("Wrote gridded cube -> %s  (%d days, vars=%s)", store.name, n, list(var_names))
    return store


# --- High-level builders for each gridded product ---
def build_antecedent_cube(ppt_paths: Sequence[Path], ppt_dates: Sequence[_dt.date],
                          grid_years: Sequence[int], reference) -> Path:
    """Steps 38 + 41: antecedent ppt (30/60/90 d) on the 70 m grid for warm seasons.

    Antecedent totals are computed once at NATIVE 4 km resolution over the whole daily
    series (cheap); each Zarr block then resamples only its days to 70 m.
    """
    native = _native_stack_dataarray(ppt_paths, ppt_dates, "ppt")     # (time,y,x) mm
    ant_native = {f"ppt_{w}d": antecedent_sum(native.values, w) for w in ANTECEDENT_WINDOWS}
    crs, transform = native.rio.crs, native.rio.transform()
    yv, xv = native.y.values, native.x.values

    # Restrict the gridded output to warm-season dates (the analysis period).
    season = set(season_dates(grid_years))
    idx = np.asarray([i for i, d in enumerate(ppt_dates) if d in season])
    season_dts = [ppt_dates[i] for i in idx]
    var_names = [f"ppt_{w}d" for w in ANTECEDENT_WINDOWS]
    log.info("Antecedent: %d native days -> %d warm-season days on 70 m grid",
             len(ppt_dates), len(season_dts))

    def provider(block: Sequence[int]) -> dict:
        sel = idx[np.asarray(block)]             # native indices for this block
        return {v: _resample_native_block(ant_native[v][sel], crs, transform, yv, xv, reference)
                for v in var_names}

    return write_grid_cube_zarr(config.INTERIM_DIR / ANTECEDENT_ZARR, season_dts,
                                provider, var_names, reference)


def build_tmean_cube(tmean_paths: Sequence[Path], tmean_dates: Sequence[_dt.date],
                     reference) -> Path:
    """Steps 40 + 41: PRISM mean air temperature on the 70 m grid (warm seasons)."""
    native = _native_stack_dataarray(tmean_paths, tmean_dates, "tmean")   # (time,y,x) degC
    vals = native.values
    crs, transform = native.rio.crs, native.rio.transform()
    yv, xv = native.y.values, native.x.values

    def provider(block: Sequence[int]) -> dict:
        return {"tmean": _resample_native_block(vals[np.asarray(block)], crs, transform,
                                                yv, xv, reference)}

    return write_grid_cube_zarr(config.INTERIM_DIR / TMEAN_ZARR, tmean_dates,
                                provider, ["tmean"], reference)


def build_drought_cube(downloads: Sequence[DroughtDownload], grid_years: Sequence[int],
                       reference, vars_: Sequence[str] = DROUGHT_VARS) -> Path:
    """Step 41: GRIDMET DROUGHT (pdsi/spei30d/spei90d) on the 70 m grid (warm seasons).

    Each year file is a native multi-band GeoTIFF (bands ``yyyymmdd_var``). The tiny
    native slices are held in memory and warm-season pentads resampled to 70 m on
    demand, one Zarr block at a time.
    """
    season_months = set(range(6, 10))            # Jun-Sep
    # per_var[var][ts] = (native_2d, geo_id); geos[geo_id] = (crs, transform, y, x).
    per_var: dict[str, dict[pd.Timestamp, tuple]] = {v: {} for v in vars_}
    geos: dict[int, tuple] = {}
    wanted_years = set(grid_years)

    for dl in downloads:
        if not dl.is_local:
            continue
        da = rioxarray.open_rasterio(dl.path, masked=True)   # (band, y, x), native
        geos[dl.year] = (da.rio.crs, da.rio.transform(), da.y.values, da.x.values)
        n_bands = int(da.sizes["band"])
        if len(dl.band_names) != n_bands:
            raise RuntimeError(
                f"drought {dl.year}: raster has {n_bands} bands but acquisition metadata "
                f"has {len(dl.band_names)} names")
        if dl.band_dates and len(dl.band_dates) != n_bands:
            raise RuntimeError(
                f"drought {dl.year}: raster has {n_bands} bands but system-time metadata "
                f"has {len(dl.band_dates)} dates")
        names = dl.band_names
        vals = da.values                          # native, tiny (band, y, x)
        n_system_date_fallback = 0
        for b, name in enumerate(names):
            parsed_date, _ = parse_drought_band(name, vars_)
            fallback_date = dl.band_dates[b] if dl.band_dates else None
            date, var = resolve_band_date(name, fallback_date, vars_)
            if parsed_date is None:
                n_system_date_fallback += 1
            expected_var = vars_[b % len(vars_)]
            if var != expected_var:
                raise RuntimeError(
                    f"drought {dl.year} band {b} {name!r}: variable {var!r} does not "
                    f"match image-major toBands order {expected_var!r}")
            ts = pd.Timestamp(date)
            if ts.month not in season_months or ts.year not in wanted_years:
                continue
            if ts in per_var[var]:
                raise RuntimeError(
                    f"drought: duplicate {var} band for {ts.date()} (year {dl.year})")
            per_var[var][ts] = (vals[b], dl.year)
        if n_system_date_fallback:
            log.info("Drought %d: resolved %d positional band date(s) from "
                     "system:time_start", dl.year, n_system_date_fallback)

    # Common, sorted pentad date axis across variables.
    all_dates = sorted(set().union(*[set(d.keys()) for d in per_var.values()]))
    if not all_dates:
        raise RuntimeError("drought: no warm-season pentads parsed from the downloads")
    ny, nx = reference.sizes["y"], reference.sizes["x"]

    def provider(block: Sequence[int]) -> dict:
        out = {}
        for v in vars_:
            arr = np.full((len(block), ny, nx), np.nan, dtype="float32")
            for k, i in enumerate(block):
                slot = per_var[v].get(all_dates[i])
                if slot is not None:
                    native_2d, geo_id = slot
                    crs, transform, yv, xv = geos[geo_id]
                    arr[k] = _resample_native_2d(native_2d, crs, transform, yv, xv, reference)
            out[v] = arr
        return out

    season_dates_ = [d.date() for d in all_dates]
    log.info("Drought: %d warm-season pentads on the 70 m grid (vars=%s)",
             len(season_dates_), list(vars_))
    return write_grid_cube_zarr(config.INTERIM_DIR / DROUGHT_ZARR, season_dates_,
                                provider, list(vars_), reference)


# --- Figures (deliverable QA) ---
def make_qa_figures(figures_dir: Path) -> list[Path]:
    """QA: a representative 70 m map per product + an area-mean time series.

    Confirms the gridded layers carry a physically sensible signal (monsoon rise in
    antecedent precip, PDSI tracking drought state) by reading the saved Zarr only.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    left, bottom, right, top = config.GRID_BOUNDS
    extent = (left, right, bottom, top)
    out_paths: list[Path] = []

    ant_store = config.INTERIM_DIR / ANTECEDENT_ZARR
    drought_store = config.INTERIM_DIR / DROUGHT_ZARR
    tmean_store = config.INTERIM_DIR / TMEAN_ZARR

    # (a) Representative maps on a late-monsoon pilot date.
    if ant_store.exists():
        ant = xr.open_zarr(ant_store)
        # pick a date near the end of the 2023 monsoon if present, else the last.
        tsel = _pick_date(ant.time.values, "2023-09-15")
        fig, axes = plt.subplots(1, 3, figsize=(16, 5.2), constrained_layout=True)
        arrs = {w: ant[f"ppt_{w}d"].sel(time=tsel).values for w in ANTECEDENT_WINDOWS}
        # SHARED color scale across the 3 windows so the panels are directly comparable
        # (90 d total >= 60 d >= 30 d at every pixel; per-panel scaling would hide that).
        shared_vmax = max(1.0, max(float(np.nanmax(a)) for a in arrs.values()))
        for ax, w in zip(axes, ANTECEDENT_WINDOWS):
            arr = arrs[w]
            im = ax.imshow(arr, extent=extent, origin="upper", cmap="YlGnBu",
                           vmin=0, vmax=shared_vmax)
            ax.set_title(f"Antecedent ppt {w} d\n{pd.Timestamp(tsel):%Y-%m-%d}")
            ax.set_xlabel("Easting (m)"); ax.set_ylabel("Northing (m)")
            fig.colorbar(im, ax=ax, shrink=0.8, label="mm")
        p = figures_dir / "section7_antecedent_precip_maps.png"
        fig.savefig(p, dpi=150, bbox_inches="tight"); plt.close(fig)
        out_paths.append(p)
        ant.close()

    # (b) Area-mean time series: antecedent precip + PDSI over the whole record.
    if ant_store.exists() and drought_store.exists():
        ant = xr.open_zarr(ant_store); dro = xr.open_zarr(drought_store)
        fig, ax1 = plt.subplots(figsize=(12, 5))
        for w, c in zip(ANTECEDENT_WINDOWS, ("#9ecae1", "#4292c6", "#08519c")):
            s = _break_offseason(ant[f"ppt_{w}d"].mean(dim=("y", "x")).to_series())
            ax1.plot(s.index, s.values, color=c, lw=1.2, label=f"antecedent ppt {w} d")
        ax1.set_ylabel("area-mean antecedent precip (mm)"); ax1.set_xlabel("date")
        ax2 = ax1.twinx()
        pdsi = _break_offseason(dro["pdsi"].mean(dim=("y", "x")).to_series())
        ax2.plot(pdsi.index, pdsi.values, color="#d95f0e", lw=1.6, label="PDSI (drought)")
        ax2.set_ylabel("PDSI  (negative = drier)")
        ax2.axhline(0, color="#d95f0e", lw=0.6, ls=":")
        lines = ax1.get_lines() + ax2.get_lines()
        ax1.legend(lines, [l.get_label() for l in lines], loc="upper left", fontsize=8)
        ax1.set_title("Section 7 sanity check: warm-season antecedent precipitation "
                      "and drought state (area mean)\nPhoenix bbox, 2018-2024 -- gaps = "
                      "off-season (data is Jun-Sep only); monsoon = mid/late-summer rise")
        p = figures_dir / "section7_precip_drought_timeseries.png"
        fig.savefig(p, dpi=150, bbox_inches="tight"); plt.close(fig)
        out_paths.append(p)
        ant.close(); dro.close()

    # (c) PRISM tmean map (cross-check layer) on the same pilot date.
    if tmean_store.exists():
        tm = xr.open_zarr(tmean_store)
        tsel = _pick_date(tm.time.values, "2023-07-15")
        arr = tm["tmean"].sel(time=tsel).values
        fig, ax = plt.subplots(figsize=(7, 6))
        im = ax.imshow(arr, extent=extent, origin="upper", cmap="inferno")
        ax.set_title(f"PRISM mean air temperature (70 m)\n{pd.Timestamp(tsel):%Y-%m-%d}")
        ax.set_xlabel("Easting (m)"); ax.set_ylabel("Northing (m)")
        fig.colorbar(im, ax=ax, label="degC")
        p = figures_dir / "section7_prism_tmean_map.png"
        fig.savefig(p, dpi=150, bbox_inches="tight"); plt.close(fig)
        out_paths.append(p)
        tm.close()

    for p in out_paths:
        log.info("Wrote figure -> %s", p.name)
    return out_paths


def _pick_date(times: np.ndarray, target_iso: str):
    """Nearest available time to target_iso (figures degrade gracefully by year)."""
    t = pd.to_datetime(times)
    target = pd.Timestamp(target_iso)
    return times[int(np.argmin(np.abs(t - target)))]


def _break_offseason(s, max_gap_days: int = 20):
    """Insert a NaN breakpoint after any gap > max_gap_days so a line plot does not connect across it.

    The layers are gridded for warm seasons only (Jun-Sep), so saved dates jump ~8 months
    at each year boundary; without the break matplotlib would draw a fictional off-season
    segment. Returns a new date-sorted series.
    """
    s = s.sort_index()
    if len(s) < 2:
        return s
    idx = pd.DatetimeIndex(s.index)
    gap_days = idx.to_series().diff().dt.days.to_numpy()
    breaks = [idx[i - 1] + pd.Timedelta(days=1) for i in range(1, len(idx))
              if gap_days[i] > max_gap_days]
    if breaks:
        s = pd.concat([s, pd.Series(np.nan, index=pd.DatetimeIndex(breaks))]).sort_index()
    return s


# --- Orchestration / CLI ---
def _grid_years(years_arg: str | None) -> list[int]:
    lo, hi = config.CLIMATOLOGY_YEARS
    allyears = list(range(lo, hi + 1))
    if not years_arg:
        return allyears
    want = {int(y) for y in years_arg.split(",")}
    return [y for y in allyears if y in want]


def run(skip_prism: bool = False, skip_drought: bool = False,
        skip_download: bool = False, years_arg: str | None = None,
        make_figures: bool = True) -> dict:
    config.ensure_dirs()
    harden_ssl_if_needed()                        # certifi fallback iff host store is broken
    grid_years = _grid_years(years_arg)
    reference = _open_reference()
    raw_prism = config.RAW_DIR / RAW_PRISM_SUBDIR
    raw_drought = config.RAW_DIR / RAW_DROUGHT_SUBDIR
    results: dict = {"grid_years": grid_years}

    # ---- PRISM precipitation + temperature (+ antecedent) ------------------ #
    if not skip_prism:
        if not skip_download and not prism_service_ok():
            raise SystemExit(
                "\n" + "=" * 72 + "\nPRISM WEB SERVICE UNAVAILABLE.\n"
                "Download the daily 4 km grids manually from prism.oregonstate.edu\n"
                "into data/raw/prism/ (ppt 2018-01-01..2024-09-30; tmean warm seasons),\n"
                "named like 'prism_ppt_YYYYMMDD_bbox.tif', then re-run with\n"
                "  python src/section7_precip_drought.py --skip-download\n" + "=" * 72)

        ppt_dates = daily_dates(PPT_START, PERIOD_END)
        # tmean has no antecedent window, so only the gridded years are needed
        # (grid_years is the EXPANDED year range; config.CLIMATOLOGY_YEARS is just
        # the (first, last) endpoints, not an enumerated list).
        tmean_dates = season_dates(grid_years)
        if skip_download:
            ppt_map = dict(zip(ppt_dates, _existing_paths(raw_prism, "ppt", ppt_dates)))
            tmean_map = dict(zip(tmean_dates, _existing_paths(raw_prism, "tmean", tmean_dates)))
            ppt_failed: list = []
            tmean_failed: list = []
        else:
            ppt_map, _, ppt_failed = download_prism_series("ppt", ppt_dates, raw_prism)
            tmean_map, _, tmean_failed = download_prism_series("tmean", tmean_dates, raw_prism)

        _sanity_log_prism([ppt_map[ppt_dates[0]]], "ppt", PPT_VALID_RANGE)
        _sanity_log_prism([tmean_map[tmean_dates[0]]], "tmean", TMEAN_VALID_RANGE)

        # Antecedent needs a COMPLETE daily series; a gap would silently NaN every
        # dependent window, so it is skipped (not faked) if any ppt day is unresolved.
        if ppt_failed:
            log.error("PRISM ppt incomplete: %d unresolved day(s), e.g. %s. ANTECEDENT "
                      "CUBE SKIPPED - re-run after the PRISM per-file quota resets "
                      "(it backfills only the missing days).", len(ppt_failed),
                      [str(d) for d in ppt_failed[:5]])
        else:
            ppt_paths = [ppt_map[d] for d in ppt_dates]
            results["antecedent_zarr"] = build_antecedent_cube(
                ppt_paths, ppt_dates, grid_years, reference)

        # tmean (cross-check) is restricted to the requested grid years (default: all).
        ty_dates = [d for d in tmean_dates if d.year in set(grid_years) and d in tmean_map]
        if ty_dates:
            results["tmean_zarr"] = build_tmean_cube(
                [tmean_map[d] for d in ty_dates], ty_dates, reference)
        if tmean_failed:
            log.warning("PRISM tmean: %d unresolved day(s), e.g. %s (tmean cube built "
                        "from the days present).", len(tmean_failed),
                        [str(d) for d in tmean_failed[:5]])

    # ---- GRIDMET DROUGHT (Earth Engine) ------------------------------------ #
    if not skip_drought:
        initialize_ee()
        region = drought_region()
        downloads = [download_drought_year(y, region, raw_drought)
                     for y in range(config.CLIMATOLOGY_YEARS[0], config.CLIMATOLOGY_YEARS[1] + 1)]
        local = [d for d in downloads if d.is_local]
        if not local:
            raise SystemExit(_spei_fallback_message())
        _record_drought_manifest(local)
        results["drought_zarr"] = build_drought_cube(downloads, grid_years, reference)

    if make_figures:
        results["figures"] = make_qa_figures(config.FIGURES_DIR)

    _report(results)
    return results


def _existing_paths(raw_dir: Path, element: str, dates: Sequence[_dt.date]) -> list[Path]:
    """--skip-download: collect manually-placed PRISM files, erroring on any gap."""
    paths, missing = [], []
    for d in dates:
        p = raw_dir / prism_raw_filename(element, d)
        (paths if p.exists() else missing).append(p)
    if missing:
        raise SystemExit(
            f"--skip-download: {len(missing)} {element} file(s) missing from {raw_dir} "
            f"(first: {missing[0].name}). Place all daily files there and re-run.")
    log.info("--skip-download: reusing %d %s file(s) from %s", len(paths), element, raw_dir)
    return paths


def _sanity_log_prism(paths: Sequence[Path], element: str, valid: tuple[float, float]) -> None:
    if not paths:
        return
    da = rioxarray.open_rasterio(paths[0], masked=True).squeeze("band", drop=True)
    v = da.values[np.isfinite(da.values)]
    if v.size:
        log.info("PRISM %s sanity (%s): min/mean/max = %.2f/%.2f/%.2f (expect within %s)",
                 element, Path(paths[0]).name, float(v.min()), float(v.mean()),
                 float(v.max()), valid)


def _record_drought_manifest(downloads: Sequence[DroughtDownload]) -> None:
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    rows = []
    for dl in downloads:
        rows.append({
            "source": (f"Google Earth Engine {DROUGHT_COLLECTION} (year={dl.year}; "
                       f"vars={','.join(DROUGHT_VARS)}; native {DROUGHT_NATIVE_SCALE_M:.0f} m; "
                       f"EPSG:32612; geemap.download_ee_image)"),
            "dataset": DROUGHT_COLLECTION,
            "filename": dl.path.name,
            "download_date": today,
            "checksum": f"sha256:{sha256_file(dl.path)}",
        })
    append_to_manifest(rows)


def _spei_fallback_message() -> str:
    return ("\n" + "=" * 72 + "\nGRIDMET DROUGHT via Earth Engine FAILED for every year "
            "and every tile size.\nLast-resort fallback: download a SPEI global database "
            "file from spei.csic.es\n(e.g. speiXX.nc) into data/raw/drought/ and re-run; "
            "or fix Earth Engine\naccess (earthengine authenticate; EARTHENGINE_PROJECT).\n"
            + "=" * 72)


def _report(results: dict) -> None:
    log.info("=" * 70)
    log.info("Section 7 complete. Gridded 70 m cubes (data/interim/):")
    for key in ("antecedent_zarr", "tmean_zarr", "drought_zarr"):
        if key in results:
            log.info("  %-16s -> %s", key, Path(results[key]).name)
    if results.get("figures"):
        log.info("  figures          -> %d QA figure(s) in %s",
                 len(results["figures"]), config.FIGURES_DIR)
    log.info("=" * 70)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 7 - PRISM precip/temperature + GRIDMET drought on the 70 m grid.")
    p.add_argument("--skip-prism", action="store_true", help="skip PRISM ppt/tmean/antecedent.")
    p.add_argument("--skip-drought", action="store_true", help="skip GRIDMET drought (no EE).")
    p.add_argument("--skip-download", action="store_true",
                   help="reuse PRISM files already in data/raw/prism/ (manual download).")
    p.add_argument("--years", default=None,
                   help="comma list of warm-season years to GRID (default: all 2018-2024).")
    p.add_argument("--no-figures", action="store_true", help="skip QA figures.")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    run(skip_prism=args.skip_prism, skip_drought=args.skip_drought,
        skip_download=args.skip_download, years_arg=args.years,
        make_figures=not args.no_figures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
