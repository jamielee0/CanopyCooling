#!/usr/bin/env python3
"""Section 6 — Atmospheric demand (VPD) and background water supply (soil moisture).

Implements steps 33-36 of the Data Acquisition & Analysis Protocol for the
Phoenix pilot. The whole section runs from this single module so the result is
reproducible end to end (protocol standing rule: "every figure and every number
must be reproducible from the saved code").

Pipeline
--------
33. Using the Copernicus Climate Data Store API (cdsapi), request four ERA5-Land
    hourly variables over the config bounding box, for ALL hours, for the warm
    season 1 June - 30 September of every year 2018-2024 (the long record is
    needed for the Section 11 climatology). The request is CHUNKED BY YEAR — one
    CDS job per year — because CDS requests queue and a per-year granularity is
    restartable and keeps each job comfortably inside the request-size limits.
    Each raw NetCDF is saved to data/raw/era5land/ and recorded in the manifest.
        2m_temperature                (t2m)   - air temperature        [K]
        2m_dewpoint_temperature       (d2m)   - dewpoint temperature   [K]
        volumetric_soil_water_layer_1 (swvl1) - soil moisture 0-7 cm   [m3/m3]
        volumetric_soil_water_layer_2 (swvl2) - soil moisture 7-28 cm  [m3/m3]
34. Compute vapour pressure deficit. Convert t2m and d2m from Kelvin to Celsius,
    take the saturation vapour pressure of each via the Tetens formula
        e(T) = 0.6108 * exp(17.27 * T / (T + 237.3))   [kPa, T in degC]
    and form  VPD = e(t2m) - e(d2m)  [kPa].
35. Compute a root-zone soil-moisture value by depth-weighting the two ERA5-Land
    layers (layer 1 = 0-7 cm, layer 2 = 7-28 cm):
        SM = (7 * swvl1 + 21 * swvl2) / 28   [m3/m3].
36. Keep BOTH VPD and SM at their NATIVE hourly, ~9 km resolution. They are NOT
    aggregated in time nor regridded to the 70 m grid here — that matching to the
    ECOSTRESS overpass hour happens in Section 9, and the anomalies in Section 11.
    The hourly VPD and SM series are saved together to data/interim/ as NetCDF.

Then (deliverable extra): VPD is spot-checked against a few known Phoenix
peak-heat dates of summer 2023 and the values are printed.

IMPORTANT (protocol common pitfall): ERA5-Land at ~9 km cannot resolve
block-to-block differences within a city. VPD and SM from this section are a
REGIONAL BACKGROUND only. The intra-urban water-supply signal is the
high-resolution Sentinel-2 NDMI of Section 4 — never this layer.

Dataset confirmed on the Copernicus CDS:
    name = reanalysis-era5-land   provider = Copernicus Climate Data Store / ECMWF
    hourly, native grid 0.1 deg (~9 km), variables are instantaneous (no
    de-accumulation needed). The new CDS returns a single NetCDF per request when
    data_format=netcdf and download_format=unarchived; file short names are
    t2m / d2m / swvl1 / swvl2 and the time coordinate is `valid_time`.

Run (in the `canopy` env with a working ~/.cdsapirc or CDSAPI_URL/CDSAPI_KEY):
    python src/section6_era5land_vpd_sm.py                 # full 2018-2024 run
    python src/section6_era5land_vpd_sm.py --years 2023     # one year (smoke test)
    python src/section6_era5land_vpd_sm.py --skip-download  # reuse data/raw files
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

# Heavy access / array libraries. Imported at module top as in Section 2; the
# pure-numpy logic below (the Tetens VPD, the depth-weighted soil moisture, the
# request builder, the manifest helpers) does NOT touch them, so it can be
# unit-tested with these stubbed out (see test_section6_*).
import cdsapi  # noqa: E402
import xarray as xr  # noqa: E402

# Make the sibling config module importable whether run from repo root or src/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config  # noqa: E402

log = logging.getLogger("section6")

# --------------------------------------------------------------------------- #
# Confirmed dataset constants (see module docstring; logged at run time).
# --------------------------------------------------------------------------- #
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

# Soil-layer thicknesses for the root-zone depth weighting (centimetres).
#   ERA5-Land layer 1 spans 0-7 cm  -> 7 cm thick
#   ERA5-Land layer 2 spans 7-28 cm -> 21 cm thick
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

# Spot-check defaults (step "5"): the late-July 2023 Phoenix heat wave produced a
# record 31-day streak of daily highs >= 110 F (30 Jun - 30 Jul 2023). We sample
# the dry peak-heat days and contrast with a humid monsoon day, at a mid-afternoon
# hour. Phoenix is MST (UTC-7, no DST), so 22:00 UTC ~ 15:00 local.
DEFAULT_PEAK_HEAT_DATES = ("2023-07-16", "2023-07-20", "2023-07-25")
DEFAULT_CONTRAST_DATES = ("2023-08-18",)                 # monsoon: hot but humid
SPOT_CHECK_UTC_HOUR = 22                                 # ~15:00 local (MST)


# =========================================================================== #
# Request construction  (pure; no cdsapi/xarray deps)
# --------------------------------------------------------------------------- #
def years() -> list[int]:
    """The inclusive climatology year span from config (2018..2024)."""
    lo, hi = config.CLIMATOLOGY_YEARS
    return list(range(lo, hi + 1))


def season_months() -> list[str]:
    """Two-digit month strings spanning config.SEASON, inclusive.

    config.SEASON is ("06-01", "09-30"); the season boundaries are month-aligned
    (whole June..September), so requesting every day 01-31 of these months and
    letting CDS ignore non-existent dates returns exactly the warm season.
    """
    (start_mm, _), (end_mm, _) = (s.split("-") for s in config.SEASON)
    return [f"{m:02d}" for m in range(int(start_mm), int(end_mm) + 1)]


def all_days() -> list[str]:
    """Day-of-month strings 01..31 (CDS silently drops non-existent dates)."""
    return [f"{d:02d}" for d in range(1, 32)]


def all_hours() -> list[str]:
    """Every hour of the day as CDS HH:00 strings (00:00..23:00)."""
    return [f"{h:02d}:00" for h in range(24)]


def area_for_cdsapi() -> list[float]:
    """config.BBOX_LONLAT is (min_lon,max_lon,min_lat,max_lat); CDS wants the
    sub-area as [North, West, South, East]."""
    min_lon, max_lon, min_lat, max_lat = config.BBOX_LONLAT
    return [max_lat, min_lon, min_lat, max_lon]


def build_cds_request(year: int) -> dict:
    """Build the CDS API request dict for one warm season of one year.

    All four variables, every day of June-September, every hour, clipped to the
    study area; NetCDF, unarchived so a single .nc comes back.
    """
    return {
        "variable": list(CDS_VARIABLES),
        "year": str(year),
        "month": season_months(),
        "day": all_days(),
        "time": all_hours(),
        "area": area_for_cdsapi(),
        "data_format": "netcdf",
        "download_format": "unarchived",
    }


# =========================================================================== #
# VPD + soil-moisture maths  (pure numpy; unit-tested without the geo stack)
# --------------------------------------------------------------------------- #
def kelvin_to_celsius(t_kelvin):
    """Convert a temperature (array or DataArray) from Kelvin to Celsius."""
    return t_kelvin - KELVIN_ZERO_C


def saturation_vapour_pressure_kpa(t_celsius):
    """Saturation vapour pressure e(T) in kPa via the Tetens formula (T in degC).

        e(T) = 0.6108 * exp(17.27 * T / (T + 237.3))

    Works on plain numpy arrays and on xarray DataArrays (np.exp dispatches).
    """
    return TETENS_A * np.exp(TETENS_B * t_celsius / (t_celsius + TETENS_C))


def vpd_kpa(t2m_kelvin, d2m_kelvin):
    """Vapour pressure deficit [kPa] = e(T_air) - e(T_dewpoint) (protocol step 34).

    Inputs are temperatures in Kelvin (ERA5-Land t2m and d2m). Because the
    dewpoint cannot exceed the air temperature, VPD is >= 0 except for
    negligible numerical noise where the reanalysis reports T_dew ~ T_air.
    """
    e_air = saturation_vapour_pressure_kpa(kelvin_to_celsius(t2m_kelvin))
    e_dew = saturation_vapour_pressure_kpa(kelvin_to_celsius(d2m_kelvin))
    return e_air - e_dew


def rootzone_soil_moisture(swvl1, swvl2):
    """Depth-weighted root-zone soil moisture [m3/m3] (protocol step 35).

        SM = (7 * swvl1 + 21 * swvl2) / 28

    i.e. the 0-28 cm mean weighted by each layer's thickness (0-7 and 7-28 cm).
    """
    total = SOIL_L1_CM + SOIL_L2_CM
    return (SOIL_L1_CM * swvl1 + SOIL_L2_CM * swvl2) / total


# =========================================================================== #
# Checksums + manifest  (step 33) — same schema as Section 0 / Section 2
# --------------------------------------------------------------------------- #
def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Streaming SHA-256 of a file (raw NetCDFs are not loaded whole)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


_MANIFEST_COLUMNS = ["source", "dataset", "filename", "download_date", "checksum"]


def append_to_manifest(rows: Sequence[dict], manifest_csv: Path | None = None) -> None:
    """Append rows to data/manifest.csv, skipping filenames already recorded.

    Each row carries: source, dataset, filename, download_date, checksum — the
    schema established in Section 0.
    """
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


def _manifest_row(path: Path, year: int) -> dict:
    """Build the manifest row for one downloaded raw year file."""
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    return {
        "source": f"{PROVIDER}: {DATASET} (warm season {year})",
        "dataset": DATASET_ID,
        "filename": path.name,
        "download_date": today,
        "checksum": f"sha256:{sha256_file(path)}",
    }


# =========================================================================== #
# CDS download  (step 33) — needs cdsapi at run time
# --------------------------------------------------------------------------- #
def _load_project_dotenv() -> None:
    """Load the gitignored repo-root .env into the environment (no overwrite).

    Mirrors src/check_auth.py and src/section2 so a run can pick up local CDS
    credentials (CDSAPI_URL / CDSAPI_KEY) from the project .env without exporting
    them by hand. Real environment variables and ~/.cdsapirc take precedence.
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

    The project .env is loaded first (no overwrite) so CDS creds can live there
    alongside the other services' creds. Kept non-quiet so the queue status
    (queued / running / completed) cdsapi emits is surfaced through logging
    while a request waits in the CDS queue.
    """
    _load_project_dotenv()
    return cdsapi.Client()


def _looks_like_zip(path: Path) -> bool:
    """True if the file begins with the ZIP local-file magic (PK\\x03\\x04)."""
    with open(path, "rb") as fh:
        return fh.read(4) == b"PK\x03\x04"


def _ensure_unarchived_netcdf(path: Path) -> Path:
    """If CDS handed back a .zip (despite download_format=unarchived), extract.

    For an all-instantaneous request like ours the archive contains exactly one
    NetCDF; extract it in place. Anything else is surfaced loudly rather than
    silently mishandled.
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


def year_target(raw_dir: Path, year: int) -> Path:
    """Local path for one downloaded year file."""
    return raw_dir / f"era5land_{year}.nc"


def _is_valid_netcdf(path: Path) -> bool:
    """Cheap validity probe: the file opens as a dataset with our variables."""
    try:
        with xr.open_dataset(path) as ds:
            return any(v in ds.variables for v in SHORT_NAMES)
    except Exception:  # noqa: BLE001 - any failure means "re-download"
        return False


def download_year(client, year: int, raw_dir: Path, force: bool = False) -> Path:
    """Submit one per-year CDS request, wait in the queue, and save the NetCDF.

    Restartable: an already-present, openable year file is reused unless --force.
    """
    target = year_target(raw_dir, year)
    if target.exists() and not force and _is_valid_netcdf(target):
        log.info("year %d: reusing existing %s (%.1f MB)", year, target.name,
                 target.stat().st_size / 1e6)
        return target

    request = build_cds_request(year)
    log.info("year %d: submitting CDS request (queues at CDS — may take a while) "
             "vars=%d months=%s area=%s", year, len(CDS_VARIABLES),
             ",".join(season_months()), area_for_cdsapi())
    client.retrieve(DATASET, request, str(target))       # blocks: queue -> run -> download
    _ensure_unarchived_netcdf(target)
    log.info("year %d: downloaded %s (%.1f MB)", year, target.name,
             target.stat().st_size / 1e6)
    return target


def download_all(year_list: Sequence[int], raw_dir: Path, force: bool = False) -> list[Path]:
    """Download every requested year, recording each in the manifest as it lands.

    One year failing (queue error, transient CDS outage) does not abort the rest;
    failures are logged and the run continues, so a re-run fills only the gaps.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    client = make_client()
    got: list[Path] = []
    for i, year in enumerate(year_list, 1):
        log.info("=== year %d (%d/%d) ===", year, i, len(year_list))
        try:
            path = download_year(client, year, raw_dir, force=force)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            log.error("year %d FAILED: %s: %s", year, type(exc).__name__, exc)
            continue
        append_to_manifest([_manifest_row(path, year)])
        got.append(path)
    if len(got) != len(year_list):
        log.warning("downloaded %d of %d year(s); the climatology will be "
                    "incomplete until the rest are fetched (re-run to fill gaps).",
                    len(got), len(year_list))
    return got


def discover_local_years(raw_dir: Path) -> list[Path]:
    """All era5land_<year>.nc files already present locally (for --skip-download)."""
    return sorted(raw_dir.glob("era5land_*.nc"))


# =========================================================================== #
# Open + compute  (steps 34-36) — needs xarray at run time
# --------------------------------------------------------------------------- #
def _normalise(ds: "xr.Dataset") -> "xr.Dataset":
    """Put one raw ERA5-Land NetCDF into a canonical (time, latitude, longitude).

    The new CDS names the time axis `valid_time` and may carry singleton
    `number` / `expver` coordinates; fold those away so every year stacks cleanly.
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
    """Derive hourly VPD and root-zone soil moisture (steps 34-35).

    Returns a new dataset with two variables, `vpd` [kPa] and `sm` [m3/m3], on
    the SAME native hourly ~9 km grid as the inputs (no regrid, no time
    aggregation — step 36).
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
                            "resolve block-to-block differences; the intra-urban "
                            "water-supply signal is the Sentinel-2 NDMI of Section 4."),
        "warm_season": f"{config.SEASON[0]}..{config.SEASON[1]} each year",
        "years": f"{years()[0]}-{years()[-1]}",
        "crs": "EPSG:4326 (native lat/lon; NOT yet on the 70 m grid — see Section 9)",
    }
    return out


def save_interim(ds: "xr.Dataset", interim_dir: Path) -> Path:
    """Save the hourly VPD + SM dataset to data/interim/ as NetCDF."""
    interim_dir.mkdir(parents=True, exist_ok=True)
    out = interim_dir / INTERIM_NAME
    encoding = {v: {"zlib": True, "complevel": 4} for v in ("vpd", "sm")}
    ds.to_netcdf(out, encoding=encoding)
    log.info("Saved hourly VPD + SM -> %s  dims=%s", out, dict(ds.sizes))
    return out


# =========================================================================== #
# Spot-check  (deliverable: document + spot-check the VPD calculation)
# --------------------------------------------------------------------------- #
def spot_check_vpd(
    ds: "xr.Dataset",
    dates: Sequence[str] = DEFAULT_PEAK_HEAT_DATES,
    contrast_dates: Sequence[str] = DEFAULT_CONTRAST_DATES,
    utc_hour: int = SPOT_CHECK_UTC_HOUR,
) -> pd.DataFrame:
    """Print area-mean VPD (and SM) at a mid-afternoon hour on chosen dates.

    On the dry peak-heat days of July 2023 the study-area VPD should be very high
    (well above typical), and markedly higher than on a humid monsoon afternoon —
    a quick physical sanity check on the Tetens calculation.
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


# =========================================================================== #
# Orchestration / CLI
# --------------------------------------------------------------------------- #
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
        paths = discover_local_years(raw_dir)
        log.info("--skip-download: found %d local year file(s) in %s",
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
