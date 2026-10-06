#!/usr/bin/env python3
"""Section 6 — ERA5-Land atmospheric demand (VPD) and background soil moisture.

Inputs : Copernicus CDS reanalysis-era5-land hourly (t2m, d2m, swvl1, swvl2),
         warm season (Jun-Sep) 2018-2024, study-area bbox -> data/raw/era5land/
Outputs: hourly VPD [kPa] + root-zone SM [m3/m3] at native ~9 km ->
         data/interim/era5land_vpd_sm_hourly_2018_2024.nc; manifest rows
Key decisions (full rationale in docs/DESIGN_DECISIONS.md, Section 6):
  - Request chunked by calendar month (CDS per-request cost limit; restartable).
  - VPD via Tetens; SM depth-weighted over 0-7 and 7-28 cm layers.
  - Kept native hourly ~9 km: no time-aggregation, no 70 m regrid (done in Sec 9/11).
  - Root-zone SM is the primary water-supply axis, interpreted as a REGIONAL background;
    Section 4b NDMI is a separate vegetation-condition check.
Run: python src/section6_era5land_vpd_sm.py [--years Y...] [--skip-download]
                                            [--force] [--hour H] [-v]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import logging
import os
import sys
import zipfile
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

# Imported at module top, but the pure-numpy logic below does not touch them, so
# it can be unit-tested with these stubbed out (see test_section6_*).
import cdsapi  # noqa: E402
import xarray as xr  # noqa: E402

# Make the sibling config module importable whether run from repo root or src/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config  # noqa: E402

log = logging.getLogger("section6")

# --- Confirmed dataset constants --------------------------------------------
DATASET = "reanalysis-era5-land"                         # CDS collection name
DATASET_ID = DATASET                                     # recorded in the manifest
PROVIDER = "Copernicus Climate Data Store (ECMWF)"

# The four variables to request, paired with the short names in the NetCDF.
CDS_VARIABLES = (
    "2m_temperature",
    "2m_dewpoint_temperature",
    "volumetric_soil_water_layer_1",
    "volumetric_soil_water_layer_2",
)
SHORT_NAMES = ("t2m", "d2m", "swvl1", "swvl2")

# Soil-layer thicknesses for the root-zone depth weighting (cm): L1 0-7, L2 7-28.
SOIL_L1_CM = 7
SOIL_L2_CM = 21

# Tetens saturation-vapour-pressure constants (kPa, T in degrees Celsius).
TETENS_A = 0.6108
TETENS_B = 17.27
TETENS_C = 237.3
KELVIN_ZERO_C = 273.15

# Output locations.
RAW_SUBDIR = "era5land"                                  # data/raw/era5land/
INTERIM_NAME = "era5land_vpd_sm_hourly_2018_2024.nc"     # data/interim/<this>

# Spot-check defaults: dry July-2023 Phoenix heat-wave days vs a humid monsoon
# day, at ~mid-afternoon local. Phoenix is MST (UTC-7, no DST), so 22 UTC ~15:00.
DEFAULT_PEAK_HEAT_DATES = ("2023-07-16", "2023-07-20", "2023-07-25")
DEFAULT_CONTRAST_DATES = ("2023-08-18",)                 # monsoon: hot but humid
SPOT_CHECK_UTC_HOUR = 22                                 # ~15:00 local (MST)


# --- Request construction (pure; no cdsapi/xarray deps) ---------------------
def years() -> list[int]:
    """Inclusive climatology year span from config (2018..2024)."""
    lo, hi = config.CLIMATOLOGY_YEARS
    return list(range(lo, hi + 1))


def season_months() -> list[str]:
    """Two-digit month strings spanning config.SEASON, inclusive (whole Jun..Sep)."""
    (start_mm, _), (end_mm, _) = (s.split("-") for s in config.SEASON)
    return [f"{m:02d}" for m in range(int(start_mm), int(end_mm) + 1)]


def all_days() -> list[str]:
    """Day-of-month strings 01..31 (CDS silently drops non-existent dates)."""
    return [f"{d:02d}" for d in range(1, 32)]


def all_hours() -> list[str]:
    """Every hour of the day as CDS HH:00 strings (00:00..23:00)."""
    return [f"{h:02d}:00" for h in range(24)]


def area_for_cdsapi() -> list[float]:
    """Convert config.BBOX_LONLAT to the CDS sub-area order [N, W, S, E]."""
    min_lon, max_lon, min_lat, max_lat = config.BBOX_LONLAT
    return [max_lat, min_lon, min_lat, max_lon]


def build_cds_request(year: int, month: str) -> dict:
    """Build the CDS API request dict for one calendar month of one year."""
    return {
        "variable": list(CDS_VARIABLES),
        "year": str(year),
        "month": [month],
        "day": all_days(),
        "time": all_hours(),
        "area": area_for_cdsapi(),
        "data_format": "netcdf",
        "download_format": "unarchived",
    }


# --- VPD + soil-moisture maths (pure numpy; unit-tested without geo stack) ---
def kelvin_to_celsius(t_kelvin):
    """Convert a temperature (array or DataArray) from Kelvin to Celsius."""
    return t_kelvin - KELVIN_ZERO_C


def saturation_vapour_pressure_kpa(t_celsius):
    """Saturation vapour pressure e(T) in kPa via Tetens (T in degC); xarray-safe."""
    return TETENS_A * np.exp(TETENS_B * t_celsius / (t_celsius + TETENS_C))


def vpd_kpa(t2m_kelvin, d2m_kelvin):
    """Vapour pressure deficit [kPa] = e(T_air) - e(T_dewpoint) (step 34).

    Inputs are temperatures in Kelvin; VPD is >= 0 except for negligible noise.
    """
    e_air = saturation_vapour_pressure_kpa(kelvin_to_celsius(t2m_kelvin))
    e_dew = saturation_vapour_pressure_kpa(kelvin_to_celsius(d2m_kelvin))
    return e_air - e_dew


def rootzone_soil_moisture(swvl1, swvl2):
    """Depth-weighted root-zone soil moisture [m3/m3]: (7*swvl1+21*swvl2)/28 (step 35)."""
    total = SOIL_L1_CM + SOIL_L2_CM
    return (SOIL_L1_CM * swvl1 + SOIL_L2_CM * swvl2) / total


# --- Checksums + manifest (step 33) — same schema as Section 0 / Section 2 ---
def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Streaming SHA-256 of a file (raw NetCDFs are not loaded whole)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


_MANIFEST_COLUMNS = ["source", "dataset", "filename", "download_date", "checksum"]


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
        log.info("manifest: nothing new to record (%d file(s) already present)", len(known))
        return
    out = pd.concat([existing, pd.DataFrame(new_rows, columns=_MANIFEST_COLUMNS)],
                    ignore_index=True)
    out.to_csv(manifest_csv, index=False)
    log.info("manifest: appended %d row(s) -> %s", len(new_rows), manifest_csv)


def _manifest_row(path: Path, year: int, month: str) -> dict:
    """Build the manifest row for one downloaded raw (year, month) file."""
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    return {
        "source": f"{PROVIDER}: {DATASET} ({year}-{month})",
        "dataset": DATASET_ID,
        "filename": path.name,
        "download_date": today,
        "checksum": f"sha256:{sha256_file(path)}",
    }


# --- CDS download (step 33) — needs cdsapi at run time ----------------------
def _load_project_dotenv() -> None:
    """Load the gitignored repo-root .env into the environment (no overwrite).

    Real environment variables and ~/.cdsapirc take precedence.
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


def make_client() -> "cdsapi.Client":
    """Construct a cdsapi client (reads ~/.cdsapirc or CDSAPI_URL/CDSAPI_KEY).

    Kept non-quiet so the CDS queue status is surfaced through logging while waiting.
    """
    _load_project_dotenv()
    return cdsapi.Client()


def _looks_like_zip(path: Path) -> bool:
    """True if the file begins with the ZIP local-file magic (PK\\x03\\x04)."""
    with open(path, "rb") as fh:
        return fh.read(4) == b"PK\x03\x04"


def _ensure_unarchived_netcdf(path: Path) -> Path:
    """If CDS handed back a .zip (despite unarchived), extract its one NetCDF in place.

    Anything other than exactly one member is surfaced loudly.
    """
    if not _looks_like_zip(path):
        return path
    with zipfile.ZipFile(path) as zf:
        members = [m for m in zf.namelist() if m.endswith((".nc", ".nc4"))]
        if len(members) != 1:
            raise RuntimeError(
                f"CDS returned a ZIP with {len(members)} NetCDF member(s) "
                f"({members!r}); expected exactly one. Re-run with finer chunking."
            )
        data = zf.read(members[0])
    path.write_bytes(data)            # replace the .zip bytes with the .nc bytes
    log.info("Unarchived CDS zip -> %s (%s)", path.name, members[0])
    return path


def chunk_target(raw_dir: Path, year: int, month: str) -> Path:
    """Local path for one downloaded (year, month) file."""
    return raw_dir / f"era5land_{year}_{month}.nc"


def _is_valid_netcdf(path: Path) -> bool:
    """Cheap validity probe: the file opens as a dataset with our variables."""
    try:
        with xr.open_dataset(path) as ds:
            return any(v in ds.variables for v in SHORT_NAMES)
    except Exception:  # noqa: BLE001 - any failure means "re-download"
        return False


def download_chunk(client, year: int, month: str, raw_dir: Path,
                   force: bool = False) -> Path:
    """Submit one (year, month) CDS request, wait in the queue, save the NetCDF.

    Restartable: an already-present, openable chunk file is reused unless --force.
    """
    target = chunk_target(raw_dir, year, month)
    if target.exists() and not force and _is_valid_netcdf(target):
        log.info("%d-%s: reusing existing %s (%.1f MB)", year, month, target.name,
                 target.stat().st_size / 1e6)
        return target

    request = build_cds_request(year, month)
    log.info("%d-%s: submitting CDS request (queues at CDS — may take a while) "
             "vars=%d area=%s", year, month, len(CDS_VARIABLES), area_for_cdsapi())
    client.retrieve(DATASET, request, str(target))       # blocks: queue -> run -> download
    _ensure_unarchived_netcdf(target)
    log.info("%d-%s: downloaded %s (%.1f MB)", year, month, target.name,
             target.stat().st_size / 1e6)
    return target


def _keep_system_awake() -> None:
    """Best-effort: ask Windows not to idle-sleep while the long download runs.

    Blocks idle sleep only (not a lid-close); no-op off Windows or on failure.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        log.info("requested system stay-awake for the duration of the download")
    except Exception as exc:  # noqa: BLE001
        log.warning("could not request stay-awake (%s); keep the machine awake manually", exc)


def download_all(year_list: Sequence[int], raw_dir: Path, force: bool = False) -> list[Path]:
    """Download every (year, month) chunk, recording each in the manifest as it lands.

    One chunk failing is logged and skipped; a re-run fills only the gaps.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    _keep_system_awake()
    client = make_client()
    months = season_months()
    chunks = [(y, m) for y in year_list for m in months]
    got: list[Path] = []
    for i, (year, month) in enumerate(chunks, 1):
        log.info("=== %d-%s (%d/%d) ===", year, month, i, len(chunks))
        try:
            path = download_chunk(client, year, month, raw_dir, force=force)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            log.error("%d-%s FAILED: %s: %s", year, month, type(exc).__name__, exc)
            continue
        append_to_manifest([_manifest_row(path, year, month)])
        got.append(path)
    if len(got) != len(chunks):
        log.warning("downloaded %d of %d month-chunk(s); the record will be "
                    "incomplete until the rest are fetched (re-run to fill gaps).",
                    len(got), len(chunks))
    return got


def discover_local_chunks(raw_dir: Path) -> list[Path]:
    """All era5land_*.nc files already present locally (for --skip-download)."""
    return sorted(raw_dir.glob("era5land_*.nc"))


# --- Open + compute (steps 34-36) — needs xarray at run time ----------------
def _normalise(ds: "xr.Dataset") -> "xr.Dataset":
    """Put one raw ERA5-Land NetCDF into canonical (time, latitude, longitude).

    Renames `valid_time`->`time` and folds away singleton number/expver coords.
    """
    if "valid_time" in ds.variables and "time" not in ds.dims:
        ds = ds.rename({"valid_time": "time"})
    for extra in ("number", "expver"):
        if extra in ds.dims and ds.sizes[extra] == 1:
            ds = ds.squeeze(extra, drop=True)
        if extra in ds.coords and extra not in ds.dims:
            ds = ds.drop_vars(extra)
    return ds


def open_raw(paths: Sequence[Path]) -> "xr.Dataset":
    """Open and time-concatenate the per-year raw files into one hourly dataset."""
    if not paths:
        raise RuntimeError("No ERA5-Land raw files to open.")
    parts = [_normalise(xr.open_dataset(p)) for p in sorted(paths)]
    missing = [v for v in SHORT_NAMES if any(v not in p.variables for p in parts)]
    if missing:
        have = sorted(set().union(*[set(p.variables) for p in parts]))
        raise KeyError(f"Expected variables {missing} not found; file has {have}.")
    ds = xr.concat(parts, dim="time") if len(parts) > 1 else parts[0]
    ds = ds.sortby("time")
    # Guard against any duplicate hours if year files happen to overlap.
    _, keep = np.unique(ds["time"].values, return_index=True)
    if len(keep) != ds.sizes["time"]:
        ds = ds.isel(time=np.sort(keep))
    log.info("opened ERA5-Land: %d hourly steps %s..%s, grid %d lat x %d lon",
             ds.sizes["time"], str(ds["time"].values[0])[:13],
             str(ds["time"].values[-1])[:13],
             ds.sizes.get("latitude", -1), ds.sizes.get("longitude", -1))
    return ds


def compute_vpd_sm(ds: "xr.Dataset") -> "xr.Dataset":
    """Derive hourly VPD [kPa] and root-zone SM [m3/m3] (steps 34-35).

    Output stays on the native hourly ~9 km grid: no regrid, no time aggregation.
    """
    vpd = vpd_kpa(ds["t2m"], ds["d2m"])
    vpd.attrs = {
        "long_name": "vapour pressure deficit (Tetens, e(t2m) - e(d2m))",
        "units": "kPa",
        "formula": "e(T)=0.6108*exp(17.27*T/(T+237.3)); T in degC; VPD=e(t2m)-e(d2m)",
        "source_variables": "t2m, d2m (ERA5-Land 2m air & dewpoint temperature)",
    }
    sm = rootzone_soil_moisture(ds["swvl1"], ds["swvl2"])
    sm.attrs = {
        "long_name": "root-zone soil moisture, depth-weighted 0-28 cm",
        "units": "m3 m-3",
        "formula": "(7*swvl1 + 21*swvl2)/28  (layer1 0-7 cm, layer2 7-28 cm)",
        "source_variables": "swvl1, swvl2 (ERA5-Land volumetric soil water L1, L2)",
    }
    out = xr.Dataset({"vpd": vpd, "sm": sm})
    out.attrs = {
        "title": "ERA5-Land hourly VPD and root-zone soil moisture (Phoenix study area)",
        "summary": ("Section 6 of the Urban Canopy Thermal Thresholds protocol. "
                    "Atmospheric demand (VPD) and regional background soil moisture, "
                    "kept at native hourly ~9 km resolution for overpass-time "
                    "matching in Section 9 and anomalies in Section 11."),
        "dataset": DATASET_ID,
        "provider": PROVIDER,
        "resolution_note": ("ERA5-Land ~9 km is a REGIONAL background only and cannot "
                            "resolve block-to-block irrigation differences. Its root-zone "
                            "soil moisture is nevertheless the primary water-supply axis; "
                            "Sentinel-2 NDMI is retained separately as a vegetation-condition "
                            "check."),
        "warm_season": f"{config.SEASON[0]}..{config.SEASON[1]} each year",
        "years": f"{years()[0]}-{years()[-1]}",
        "crs": "EPSG:4326 (native lat/lon; NOT yet on the 70 m grid — see Section 9)",
    }
    return out


def save_interim(ds: "xr.Dataset", interim_dir: Path) -> Path:
    """Save the hourly VPD + SM dataset to data/interim/ as compressed NetCDF.

    The sys.modules sentinel sidesteps a Windows ssl.SSLError raised by dask's
    `from distributed import Client` probe; distributed is never used here.
    """
    sys.modules.setdefault("distributed", None)

    interim_dir.mkdir(parents=True, exist_ok=True)
    out = interim_dir / INTERIM_NAME
    encoding = {v: {"zlib": True, "complevel": 4} for v in ("vpd", "sm")}
    ds.to_netcdf(out, encoding=encoding)
    log.info("Saved hourly VPD + SM -> %s  dims=%s", out, dict(ds.sizes))
    return out


# --- Spot-check (deliverable: document + spot-check the VPD calculation) -----
def spot_check_vpd(
    ds: "xr.Dataset",
    dates: Sequence[str] = DEFAULT_PEAK_HEAT_DATES,
    contrast_dates: Sequence[str] = DEFAULT_CONTRAST_DATES,
    utc_hour: int = SPOT_CHECK_UTC_HOUR,
) -> pd.DataFrame:
    """Print area-mean VPD (and SM) at a mid-afternoon hour on chosen dates.

    Sanity check on Tetens: dry peak-heat days should give VPD >> humid monsoon day.
    """
    rows = []
    for label, date_list in (("peak-heat", dates), ("monsoon-contrast", contrast_dates)):
        for date in date_list:
            stamp = np.datetime64(f"{date}T{utc_hour:02d}:00:00")
            try:
                sl = ds.sel(time=stamp)
            except KeyError:
                log.warning("spot-check: %s %02d:00 UTC not in record — skipped",
                            date, utc_hour)
                continue
            rows.append({
                "date": date,
                "kind": label,
                "utc_hour": f"{utc_hour:02d}:00",
                "vpd_mean_kpa": round(float(sl["vpd"].mean()), 3),
                "vpd_max_kpa": round(float(sl["vpd"].max()), 3),
                "sm_mean_m3m3": round(float(sl["sm"].mean()), 4),
            })
    table = pd.DataFrame(rows)
    print("\nVPD spot-check (study-area mean at "
          f"{utc_hour:02d}:00 UTC ~ {(utc_hour - 7) % 24:02d}:00 MST):")
    if table.empty:
        print("  (no matching timestamps in the record — is 2023 downloaded?)")
    else:
        print(table.to_string(index=False))
        peak = table[table["kind"] == "peak-heat"]["vpd_mean_kpa"]
        cont = table[table["kind"] == "monsoon-contrast"]["vpd_mean_kpa"]
        if len(peak) and len(cont):
            print(f"\n  peak-heat mean VPD = {peak.mean():.2f} kPa  vs  "
                  f"monsoon-contrast = {cont.mean():.2f} kPa "
                  f"(expect peak >> contrast).")
    return table


# --- Orchestration / CLI ----------------------------------------------------
def run(
    year_list: Sequence[int] | None = None,
    skip_download: bool = False,
    force: bool = False,
    utc_hour: int = SPOT_CHECK_UTC_HOUR,
) -> None:
    config.ensure_dirs()
    raw_dir = config.RAW_DIR / RAW_SUBDIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    yrs = list(year_list) if year_list else years()

    if skip_download:
        paths = discover_local_chunks(raw_dir)
        log.info("--skip-download: found %d local chunk file(s) in %s",
                 len(paths), raw_dir)
        if not paths:
            raise SystemExit(f"No local ERA5-Land files in {raw_dir}; run without "
                             "--skip-download.")
    else:
        paths = download_all(yrs, raw_dir, force=force)    # step 33
        if not paths:
            raise SystemExit("No ERA5-Land years downloaded — cannot continue.")

    ds = open_raw(paths)
    out = compute_vpd_sm(ds)                                # steps 34-35
    save_interim(out, config.INTERIM_DIR)                   # step 36
    spot_check_vpd(out, utc_hour=utc_hour)                  # spot-check
    log.info("Section 6 complete: interim=%s  hourly_steps=%d",
             config.INTERIM_DIR / INTERIM_NAME, out.sizes["time"])


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Section 6 — ERA5-Land VPD & soil moisture.")
    p.add_argument("--years", type=int, nargs="+", default=None,
                   help="override the year list (default: config climatology span).")
    p.add_argument("--skip-download", action="store_true",
                   help="reuse NetCDFs already in data/raw/era5land/.")
    p.add_argument("--force", action="store_true",
                   help="re-download year files even if already present.")
    p.add_argument("--hour", type=int, default=SPOT_CHECK_UTC_HOUR,
                   help="UTC hour for the VPD spot-check (default %(default)s).")
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
        year_list=args.years,
        skip_download=args.skip_download,
        force=args.force,
        utc_hour=args.hour,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
