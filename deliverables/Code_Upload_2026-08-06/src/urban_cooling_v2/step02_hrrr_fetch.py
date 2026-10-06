#!/usr/bin/env python3
"""Exact-acquisition HRRR demand data for the Step-2 feasibility audit.

This module plans and executes the narrow weather acquisition needed after
ECOSTRESS passes have been certified usable.  For each pass it requests the
HRRR surface analyses bracketing acquisition UTC, selects only 2-m temperature
and 2-m dewpoint, computes VPD, and preserves both individual frozen-domain
grid cells and domain-level spatial summaries.

The default live loader uses Herbie only as a byte-range/GRIB adapter and pins
its source priority to NOAA's public AWS archive.  Imports are lazy, so all
planning, formula, geometry, and checkpoint tests run without Herbie, cfgrib,
ecCodes, credentials, or a network connection.  Fetches resume at the hourly
shard level; checkpoints contain only local file evidence and SHA-256 hashes.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from shapely.geometry import Point, shape
from shapely.prepared import prep

HRRR_MODEL = "hrrr"
HRRR_PRODUCT = "sfc"
HRRR_FALLBACK_PRODUCT = "prs"
HRRR_FORECAST_HOUR = 0
HRRR_SEARCH_STRING = r":(?:TMP|DPT):2 m"
HRRR_BUCKET = "noaa-hrrr-bdp-pds"
HRRR_HTTPS_ROOT = f"https://{HRRR_BUCKET}.s3.amazonaws.com"
HRRR_SOURCE_LABEL = (
    "NOAA HRRR public AWS archive; exact analysis f00 2-m fields; "
    "sfc with frozen prs fallback"
)
HRRR_FALLBACK_ANALYSIS_HOURS = frozenset(
    {
        "20180728T23Z",
        "20180802T23Z",
        "20180807T19Z",
        "20180815T23Z",
    }
)
HRRR_PRIMARY_PRODUCT_RESOLUTION = "primary_sfc"
HRRR_FALLBACK_PRODUCT_RESOLUTION = (
    "frozen_prs_fallback_for_missing_official_sfc_object"
)
DEFAULT_MAX_ANALYSIS_HOURS = 500
DEFAULT_MAX_NEW_DATA_BYTES = 4 * 1024**3
DEFAULT_MIN_FREE_BYTES_AFTER_PEAK = 2 * 1024**3
DEFAULT_STORAGE_SAFETY_FACTOR = 2.0
HRRR_CHECKPOINT_SCHEMA_VERSION = 3
HRRR_SHARD_SCHEMA_VERSION = 1
HRRR_RUN_SEAL_SCHEMA_VERSION = 2
HRRR_RUN_SEAL_STATUS = "PASS_EXACT_HRRR_RUN_SEAL"
HRRR_SHARD_COLUMNS = (
    "city",
    "timestamp_utc",
    "grid_y_index",
    "grid_x_index",
    "latitude",
    "longitude",
    "t2m_k",
    "d2m_k",
    "vpd_kpa",
)
HRRR_CHECKPOINT_REQUEST_FIELDS = (
    "item_id",
    "analysis_utc",
    "cities",
    "n_target_passes",
    "model",
    "product",
    "forecast_hour",
    "variable_search",
    "source",
    "object_key",
    "product_resolution",
)


class HrrrDependencyError(RuntimeError):
    """Raised when the optional live GRIB stack is unavailable."""


class HrrrFetchError(RuntimeError):
    """Raised for a safely described, hour-scoped HRRR fetch failure."""


@dataclasses.dataclass(frozen=True)
class HrrrRunResult:
    summary: pd.DataFrame
    shard_index: pd.DataFrame
    summary_path: Path
    shard_index_path: Path
    checkpoint_path: Path
    run_seal_path: Path


def dependency_status() -> dict[str, bool]:
    """Report whether the optional live HRRR decoding stack is importable."""

    status = {
        "herbie": importlib.util.find_spec("herbie") is not None,
        "cfgrib": importlib.util.find_spec("cfgrib") is not None,
        "eccodes": importlib.util.find_spec("eccodes") is not None,
        "xarray": importlib.util.find_spec("xarray") is not None,
    }
    status["live_ready"] = all(status.values())
    return status


def _analysis_hour(analysis_utc: Any) -> pd.Timestamp:
    """Normalize and validate one exact UTC HRRR analysis hour."""

    timestamp = pd.Timestamp(analysis_utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    if timestamp != timestamp.floor("h"):
        raise ValueError("HRRR analysis time must fall on an exact UTC hour")
    return timestamp


def official_hrrr_product(analysis_utc: Any) -> str:
    """Return the frozen official object product for one analysis hour.

    Four exact 2018 ``wrfsfc`` objects in the D0047 request census are absent
    from NOAA's public AWS archive.  Their same-cycle, same-valid-time ``wrfprs``
    objects contain the identical 2-m TMP/DPT fields on the identical HRRR
    grid.  D0053 freezes those four pressure-file fallbacks explicitly; no
    temporal substitution or forecast lead is introduced.
    """

    timestamp = _analysis_hour(analysis_utc)
    if timestamp.strftime("%Y%m%dT%HZ") in HRRR_FALLBACK_ANALYSIS_HOURS:
        return HRRR_FALLBACK_PRODUCT
    return HRRR_PRODUCT


def official_hrrr_object(analysis_utc: Any) -> dict[str, str]:
    """Return the immutable NOAA/AWS object identity for one HRRR analysis."""

    timestamp = _analysis_hour(analysis_utc)
    product = official_hrrr_product(timestamp)
    object_stem = {"sfc": "wrfsfc", "prs": "wrfprs"}[product]
    key = (
        f"hrrr.{timestamp:%Y%m%d}/conus/"
        f"hrrr.t{timestamp:%H}z.{object_stem}f{HRRR_FORECAST_HOUR:02d}.grib2"
    )
    url = f"{HRRR_HTTPS_ROOT}/{key}"
    return {
        "object_key": key,
        "grib_url": url,
        "index_url": f"{url}.idx",
        "product_resolution": (
            HRRR_FALLBACK_PRODUCT_RESOLUTION
            if product == HRRR_FALLBACK_PRODUCT
            else HRRR_PRIMARY_PRODUCT_RESOLUTION
        ),
    }


def _utc_series(values: Any, *, label: str) -> pd.Series:
    try:
        converted = pd.to_datetime(
            values, utc=True, errors="coerce", format="mixed"
        )
    except TypeError:  # pragma: no cover - compatibility with older pandas
        converted = pd.to_datetime(values, utc=True, errors="coerce")
    series = pd.Series(converted)
    if series.isna().any():
        bad = series.index[series.isna()].tolist()
        raise ValueError(f"{label} contains invalid timestamps at rows {bad[:10]}")
    return series


def build_hrrr_request_manifest(
    passes: pd.DataFrame,
    *,
    acquisition_column: str = "acquisition_utc",
    city_column: str = "city",
    output_csv: str | os.PathLike[str] | None = None,
) -> pd.DataFrame:
    """Plan unique hourly analyses bracketing every supplied pass acquisition.

    The caller is responsible for supplying only the passes whose upstream
    usability checks have passed.  Exact-hour acquisitions need one analysis;
    fractional acquisitions need the floor and ceiling UTC analyses.
    """

    required = {acquisition_column, city_column}
    missing = sorted(required.difference(passes.columns))
    if missing:
        raise ValueError(f"passes lacks columns: {missing}")
    if passes.empty:
        raise ValueError("at least one certified pass is required")

    work = passes[[city_column, acquisition_column]].copy()
    work[city_column] = work[city_column].astype(str).str.strip()
    if work[city_column].eq("").any():
        raise ValueError("pass city values must be non-empty")
    work[acquisition_column] = _utc_series(
        work[acquisition_column], label=acquisition_column
    ).to_numpy()
    work["pass_row"] = np.arange(len(work), dtype=int)

    floor = work.assign(analysis_utc=work[acquisition_column].dt.floor("h"))
    ceiling = work.assign(analysis_utc=work[acquisition_column].dt.ceil("h"))
    expanded = pd.concat([floor, ceiling], ignore_index=True).drop_duplicates(
        ["pass_row", "analysis_utc"]
    )

    rows: list[dict[str, Any]] = []
    for analysis, group in expanded.groupby("analysis_utc", sort=True):
        timestamp = pd.Timestamp(analysis)
        product = official_hrrr_product(timestamp)
        source = official_hrrr_object(timestamp)
        cities = sorted(group[city_column].unique())
        rows.append(
            {
                "item_id": f"hrrr-{product}-f00-{timestamp:%Y%m%dT%H}Z",
                "analysis_utc": timestamp,
                "cities": "|".join(cities),
                "n_target_passes": int(group["pass_row"].nunique()),
                "model": HRRR_MODEL,
                "product": product,
                "forecast_hour": HRRR_FORECAST_HOUR,
                "variable_search": HRRR_SEARCH_STRING,
                "source": HRRR_SOURCE_LABEL,
                **source,
            }
        )
    manifest = pd.DataFrame(rows).sort_values("analysis_utc").reset_index(drop=True)
    if manifest["item_id"].duplicated().any():
        raise AssertionError("HRRR manifest item IDs must be unique")
    if output_csv is not None:
        destination = Path(output_csv)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        manifest.to_csv(temporary, index=False)
        temporary.replace(destination)
    return manifest


def saturation_vapour_pressure_kpa(temperature_c: Any) -> np.ndarray:
    """Tetens saturation vapour pressure with temperature in degrees C."""

    temperature = np.asarray(temperature_c, dtype=float)
    return 0.6108 * np.exp(17.27 * temperature / (temperature + 237.3))


def vpd_kpa(temperature_k: Any, dewpoint_k: Any) -> np.ndarray:
    """Compute nonnegative VPD from Kelvin air/dewpoint temperatures."""

    temperature = np.asarray(temperature_k, dtype=float)
    dewpoint = np.asarray(dewpoint_k, dtype=float)
    if temperature.shape != dewpoint.shape:
        raise ValueError("temperature and dewpoint arrays must have the same shape")
    raw = saturation_vapour_pressure_kpa(temperature - 273.15) - saturation_vapour_pressure_kpa(
        dewpoint - 273.15
    )
    return np.maximum(raw, 0.0)


def _dataset_variable(dataset: Any, preferred: str, grib_short_name: str) -> Any:
    if preferred in dataset.data_vars:
        return dataset[preferred]
    target = grib_short_name.casefold()
    candidates = []
    for name, variable in dataset.data_vars.items():
        short_name = str(variable.attrs.get("GRIB_shortName", "")).casefold()
        if short_name == target:
            candidates.append(name)
    if len(candidates) != 1:
        raise ValueError(
            f"HRRR dataset requires exactly one {grib_short_name!r} field; found {candidates}"
        )
    return dataset[candidates[0]]


def _two_dimensional(value: Any, label: str) -> np.ndarray:
    squeezed = value.squeeze(drop=True) if hasattr(value, "squeeze") else np.squeeze(value)
    array = np.asarray(getattr(squeezed, "values", squeezed), dtype=float)
    if array.ndim != 2:
        raise ValueError(f"{label} must reduce to a two-dimensional HRRR grid")
    return array


def _grid_coordinates(dataset: Any) -> tuple[np.ndarray, np.ndarray]:
    latitude = None
    longitude = None
    for name in ("latitude", "lat"):
        if name in dataset.coords:
            latitude = np.asarray(dataset.coords[name].values, dtype=float)
            break
    for name in ("longitude", "lon"):
        if name in dataset.coords:
            longitude = np.asarray(dataset.coords[name].values, dtype=float)
            break
    if latitude is None or longitude is None:
        raise ValueError("HRRR dataset requires latitude and longitude coordinates")
    if latitude.ndim == longitude.ndim == 1:
        longitude, latitude = np.meshgrid(longitude, latitude)
    if latitude.ndim != 2 or longitude.ndim != 2 or latitude.shape != longitude.shape:
        raise ValueError("HRRR latitude/longitude coordinates must form one 2-D grid")
    longitude = np.where(longitude > 180, longitude - 360, longitude)
    return latitude, longitude


def _geometry(value: Any) -> Any:
    if hasattr(value, "geom_type"):
        return value
    if isinstance(value, Mapping) and value.get("type") == "Feature":
        return shape(value["geometry"])
    if isinstance(value, Mapping):
        return shape(value)
    raise TypeError("domain must be a shapely geometry, GeoJSON geometry, or Feature")


def extract_domain_cells(
    dataset: Any,
    domains: Mapping[str, Any],
    *,
    analysis_utc: Any,
    minimum_domain_cells: int = 2,
) -> pd.DataFrame:
    """Extract every HRRR grid-cell center covered by each frozen domain."""

    if minimum_domain_cells < 1:
        raise ValueError("minimum_domain_cells must be positive")
    timestamp = pd.Timestamp(analysis_utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    if timestamp != timestamp.floor("h"):
        raise ValueError("analysis_utc must be an exact hour")

    latitude, longitude = _grid_coordinates(dataset)
    temperature = _two_dimensional(_dataset_variable(dataset, "t2m", "2t"), "t2m")
    dewpoint = _two_dimensional(_dataset_variable(dataset, "d2m", "2d"), "d2m")
    if temperature.shape != latitude.shape or dewpoint.shape != latitude.shape:
        raise ValueError("HRRR data fields and coordinate grids must share one shape")

    finite_weather = np.isfinite(temperature) & np.isfinite(dewpoint)
    if finite_weather.any():
        plausible = (
            np.nanmin(temperature[finite_weather]) >= 180
            and np.nanmax(temperature[finite_weather]) <= 350
            and np.nanmin(dewpoint[finite_weather]) >= 170
            and np.nanmax(dewpoint[finite_weather]) <= 340
        )
        if not plausible:
            raise ValueError("HRRR 2-m temperature/dewpoint values are not plausible Kelvin")

    rows: list[pd.DataFrame] = []
    for city in sorted(domains):
        geometry = _geometry(domains[city])
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError(f"{city}: domain geometry is empty or invalid")
        min_lon, min_lat, max_lon, max_lat = geometry.bounds
        candidates = (
            finite_weather
            & np.isfinite(latitude)
            & np.isfinite(longitude)
            & (longitude >= min_lon)
            & (longitude <= max_lon)
            & (latitude >= min_lat)
            & (latitude <= max_lat)
        )
        ys, xs = np.where(candidates)
        prepared = prep(geometry)
        inside = np.fromiter(
            (
                prepared.covers(Point(float(longitude[y, x]), float(latitude[y, x])))
                for y, x in zip(ys, xs, strict=True)
            ),
            dtype=bool,
            count=len(ys),
        )
        ys = ys[inside]
        xs = xs[inside]
        if len(ys) < minimum_domain_cells:
            raise ValueError(
                f"{city}: only {len(ys)} valid HRRR cell centers fall in the domain; "
                f"minimum is {minimum_domain_cells}"
            )
        city_temperature = temperature[ys, xs]
        city_dewpoint = dewpoint[ys, xs]
        rows.append(
            pd.DataFrame(
                {
                    "city": city,
                    "timestamp_utc": timestamp,
                    "grid_y_index": ys.astype(int),
                    "grid_x_index": xs.astype(int),
                    "latitude": latitude[ys, xs],
                    "longitude": longitude[ys, xs],
                    "t2m_k": city_temperature,
                    "d2m_k": city_dewpoint,
                    "vpd_kpa": vpd_kpa(city_temperature, city_dewpoint),
                }
            )
        )
    if not rows:
        raise ValueError("at least one frozen domain is required")
    return pd.concat(rows, ignore_index=True)


def summarize_domain_cells(cells: pd.DataFrame) -> pd.DataFrame:
    """Produce the hourly mean used for joining plus retained spatial spread."""

    required = {"city", "timestamp_utc", "t2m_k", "d2m_k", "vpd_kpa"}
    missing = sorted(required.difference(cells.columns))
    if missing:
        raise ValueError(f"domain cells lack columns: {missing}")
    if cells.empty:
        return pd.DataFrame(
            columns=[
                "city",
                "timestamp_utc",
                "vpd_kpa",
                "vpd_kpa_median",
                "vpd_kpa_std",
                "vpd_kpa_p10",
                "vpd_kpa_p90",
                "vpd_kpa_min",
                "vpd_kpa_max",
                "t2m_k",
                "d2m_k",
                "n_domain_cells",
                "source",
                "domain_cell_rule",
            ]
        )
    work = cells.copy()
    work["timestamp_utc"] = _utc_series(work["timestamp_utc"], label="timestamp_utc").to_numpy()
    group_keys = ["city", "timestamp_utc"]
    grouped = work.groupby(group_keys, sort=True, observed=True)
    summary = grouped.agg(
        vpd_kpa=("vpd_kpa", "mean"),
        vpd_kpa_median=("vpd_kpa", "median"),
        vpd_kpa_std=("vpd_kpa", "std"),
        vpd_kpa_min=("vpd_kpa", "min"),
        vpd_kpa_max=("vpd_kpa", "max"),
        t2m_k=("t2m_k", "mean"),
        d2m_k=("d2m_k", "mean"),
        n_domain_cells=("vpd_kpa", "size"),
    ).reset_index()
    quantiles = (
        grouped["vpd_kpa"]
        .quantile([0.1, 0.9])
        .unstack(-1)
        .rename(columns={0.1: "vpd_kpa_p10", 0.9: "vpd_kpa_p90"})
        .reset_index()
    )
    summary = summary.merge(quantiles, on=group_keys, how="left", validate="one_to_one")
    ordered = [
        "city",
        "timestamp_utc",
        "vpd_kpa",
        "vpd_kpa_median",
        "vpd_kpa_std",
        "vpd_kpa_p10",
        "vpd_kpa_p90",
        "vpd_kpa_min",
        "vpd_kpa_max",
        "t2m_k",
        "d2m_k",
        "n_domain_cells",
    ]
    summary = summary[ordered]
    summary["source"] = HRRR_SOURCE_LABEL
    summary["domain_cell_rule"] = "HRRR grid-cell center covered by frozen Census Urban Area"
    return summary


class HerbieHrrrLoader:
    """Lazy, AWS-only Herbie loader for two HRRR surface analysis fields."""

    def __init__(
        self,
        cache_dir: str | os.PathLike[str],
        *,
        herbie_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.herbie_factory = herbie_factory

    def __call__(self, analysis_utc: Any) -> Any:
        factory = self.herbie_factory
        if factory is None:
            status = dependency_status()
            if not status["live_ready"]:
                missing = [name for name in ("herbie", "cfgrib", "eccodes", "xarray") if not status[name]]
                raise HrrrDependencyError(
                    "Live HRRR decoding requires conda-forge herbie-data, cfgrib, and eccodes; "
                    f"missing: {', '.join(missing)}"
                )
            from herbie import Herbie

            factory = Herbie
        timestamp = pd.Timestamp(analysis_utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            request = factory(
                timestamp.tz_localize(None).to_pydatetime(),
                model=HRRR_MODEL,
                product=official_hrrr_product(timestamp),
                fxx=HRRR_FORECAST_HOUR,
                priority=["aws"],
                save_dir=self.cache_dir,
                overwrite=False,
                verbose=False,
            )
            dataset = request.xarray(
                HRRR_SEARCH_STRING,
                remove_grib=True,
                verbose=False,
            )
            if isinstance(dataset, (list, tuple)):
                import xarray as xr

                dataset = xr.merge(list(dataset), compat="override", join="exact")
            return dataset
        except HrrrDependencyError:
            raise
        except Exception:
            # Herbie/request exceptions may include a remote URL.  Keep the
            # surfaced error hour-scoped and credential-safe.
            raise HrrrFetchError(f"HRRR load failed for {timestamp.isoformat()}") from None


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def frozen_domain_sha256(domains: Mapping[str, Any]) -> str:
    """Hash the exact named frozen-domain geometries deterministically."""

    if not domains:
        raise ValueError("at least one frozen domain is required")
    payload: list[dict[str, Any]] = []
    for city in sorted(domains):
        geometry = _geometry(domains[city])
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError(f"{city}: domain geometry is empty or invalid")
        payload.append(
            {
                "city": str(city),
                "geometry": geometry.__geo_interface__,
            }
        )
    return _json_sha256(payload)


def _canonical_request_binding(row: Mapping[str, Any]) -> dict[str, Any]:
    timestamp = pd.Timestamp(row["analysis_utc"])
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    binding = {
        "item_id": str(row["item_id"]),
        "analysis_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cities": str(row["cities"]),
        "n_target_passes": int(row["n_target_passes"]),
        "model": str(row["model"]),
        "product": str(row["product"]),
        "forecast_hour": int(row["forecast_hour"]),
        "variable_search": str(row["variable_search"]),
        "source": str(row["source"]),
        "object_key": str(row["object_key"]),
        "product_resolution": str(row["product_resolution"]),
    }
    return binding


def canonical_hrrr_manifest_sha256(manifest: pd.DataFrame) -> str:
    """Hash validated canonical request fields in analysis-time order."""

    planned = _validate_live_manifest(manifest)
    bindings = [
        _canonical_request_binding(row) for row in planned.to_dict("records")
    ]
    return _json_sha256(bindings)


def _load_hrrr_checkpoint(
    path: Path,
    *,
    manifest_sha256: str,
    domain_sha256: str,
    minimum_domain_cells: int,
) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        document.get("schema_version") != HRRR_CHECKPOINT_SCHEMA_VERSION
        or document.get("checkpoint_kind")
        != "hrrr_exact_acquisition_domain_shards"
        or document.get("manifest_sha256") != manifest_sha256
        or document.get("frozen_domain_sha256") != domain_sha256
        or int(document.get("shard_schema_version", -1))
        != HRRR_SHARD_SCHEMA_VERSION
        or int(document.get("minimum_domain_cells", -1))
        != int(minimum_domain_cells)
        or not isinstance(document.get("items"), dict)
    ):
        raise HrrrFetchError(
            "HRRR checkpoint schema or manifest/domain binding is stale"
        )
    return document["items"]


def _write_hrrr_checkpoint(
    path: Path,
    items: Mapping[str, Mapping[str, Any]],
    *,
    manifest_sha256: str,
    domain_sha256: str,
    minimum_domain_cells: int,
) -> None:
    payload = {
        "schema_version": HRRR_CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_kind": "hrrr_exact_acquisition_domain_shards",
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": manifest_sha256,
        "frozen_domain_sha256": domain_sha256,
        "shard_schema_version": HRRR_SHARD_SCHEMA_VERSION,
        "minimum_domain_cells": int(minimum_domain_cells),
        "items": {str(key): dict(value) for key, value in items.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _validate_shard_contents(
    cells: pd.DataFrame,
    row: Mapping[str, Any],
    domains: Mapping[str, Any],
    *,
    minimum_domain_cells: int,
) -> dict[str, int]:
    if tuple(cells.columns) != HRRR_SHARD_COLUMNS:
        raise ValueError("HRRR shard schema columns differ from the frozen schema")
    if cells.empty:
        raise ValueError("HRRR shard is empty")
    analysis = pd.Timestamp(row["analysis_utc"])
    if analysis.tzinfo is None:
        analysis = analysis.tz_localize("UTC")
    else:
        analysis = analysis.tz_convert("UTC")
    timestamps = _utc_series(cells["timestamp_utc"], label="shard timestamp_utc")
    if not timestamps.eq(analysis).all():
        raise ValueError("HRRR shard timestamp differs from its canonical request")
    requested_cities = tuple(filter(None, str(row["cities"]).split("|")))
    if set(cells["city"].astype(str)) != set(requested_cities):
        raise ValueError("HRRR shard city set differs from its canonical request")
    numeric_columns = (
        "grid_y_index",
        "grid_x_index",
        "latitude",
        "longitude",
        "t2m_k",
        "d2m_k",
        "vpd_kpa",
    )
    numeric = cells.loc[:, numeric_columns].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(float)).all():
        raise ValueError("HRRR shard contains non-finite numeric values")
    for column in ("grid_y_index", "grid_x_index"):
        values = numeric[column].to_numpy(float)
        if (values < 0).any() or not np.equal(values, np.floor(values)).all():
            raise ValueError("HRRR shard grid indices must be nonnegative integers")
    if cells.duplicated(["city", "grid_y_index", "grid_x_index"]).any():
        raise ValueError("HRRR shard repeats a frozen-domain grid cell")
    if (
        not numeric["latitude"].between(-90.0, 90.0).all()
        or not numeric["longitude"].between(-180.0, 180.0).all()
        or not numeric["t2m_k"].between(180.0, 350.0).all()
        or not numeric["d2m_k"].between(170.0, 340.0).all()
        or (numeric["vpd_kpa"] < 0).any()
    ):
        raise ValueError("HRRR shard values fall outside frozen physical bounds")
    expected_vpd = vpd_kpa(
        numeric["t2m_k"].to_numpy(float),
        numeric["d2m_k"].to_numpy(float),
    )
    if not np.allclose(
        numeric["vpd_kpa"].to_numpy(float), expected_vpd, rtol=0, atol=1e-12
    ):
        raise ValueError("HRRR shard VPD disagrees with its frozen formula")
    city_counts: dict[str, int] = {}
    for city in requested_cities:
        group = cells.loc[cells["city"].astype(str).eq(city)]
        if len(group) < minimum_domain_cells:
            raise ValueError(f"{city}: HRRR shard has too few frozen-domain cells")
        geometry = _geometry(domains[city])
        prepared = prep(geometry)
        inside = [
            prepared.covers(Point(float(lon), float(lat)))
            for lon, lat in zip(group["longitude"], group["latitude"], strict=True)
        ]
        if not all(inside):
            raise ValueError(f"{city}: HRRR shard contains a cell outside the frozen domain")
        city_counts[city] = int(len(group))
    return city_counts


def _valid_shard(
    row: Mapping[str, Any],
    record: Mapping[str, Any] | None,
    domains: Mapping[str, Any],
    *,
    domain_sha256: str,
    minimum_domain_cells: int,
) -> Path | None:
    if not record or record.get("status") != "complete":
        return None
    binding = _canonical_request_binding(row)
    if (
        int(record.get("schema_version", -1)) != HRRR_CHECKPOINT_SCHEMA_VERSION
        or int(record.get("shard_schema_version", -1))
        != HRRR_SHARD_SCHEMA_VERSION
        or record.get("frozen_domain_sha256") != domain_sha256
        or record.get("request_binding") != binding
        or record.get("request_sha256") != _json_sha256(binding)
        or tuple(record.get("shard_columns", ())) != HRRR_SHARD_COLUMNS
        or not record.get("local_path")
    ):
        return None
    path = Path(str(record["local_path"]))
    if (
        not path.is_file()
        or path.stat().st_size != int(record.get("size_bytes", -1))
        or _sha256(path) != record.get("sha256")
    ):
        return None
    try:
        cells = pd.read_csv(path)
        counts = _validate_shard_contents(
            cells,
            row,
            domains,
            minimum_domain_cells=minimum_domain_cells,
        )
    except Exception:
        return None
    if (
        int(record.get("n_rows", -1)) != len(cells)
        or record.get("city_row_counts") != counts
    ):
        return None
    return path


def _validate_live_manifest(manifest: pd.DataFrame) -> pd.DataFrame:
    required = {
        "item_id",
        "analysis_utc",
        "cities",
        "n_target_passes",
        "model",
        "product",
        "forecast_hour",
        "variable_search",
        "object_key",
        "grib_url",
        "index_url",
        "source",
        "product_resolution",
    }
    missing = sorted(required.difference(manifest.columns))
    if missing:
        raise ValueError(f"HRRR manifest lacks columns: {missing}")
    work = manifest.copy()
    if work.empty:
        raise ValueError("HRRR manifest must contain at least one request")
    work["analysis_utc"] = _utc_series(work["analysis_utc"], label="analysis_utc").to_numpy()
    if work["item_id"].duplicated().any():
        raise ValueError("HRRR manifest item IDs must be unique")
    for row in work.to_dict("records"):
        timestamp = pd.Timestamp(row["analysis_utc"])
        product = official_hrrr_product(timestamp)
        official = official_hrrr_object(row["analysis_utc"])
        cities = tuple(filter(None, str(row["cities"]).split("|")))
        if (
            timestamp != timestamp.floor("h")
            or str(row["item_id"])
            != f"hrrr-{product}-f00-{timestamp:%Y%m%dT%H}Z"
            or not cities
            or tuple(sorted(set(cities))) != cities
            or int(row["n_target_passes"]) <= 0
            or row["model"] != HRRR_MODEL
            or row["product"] != product
            or int(row["forecast_hour"]) != HRRR_FORECAST_HOUR
            or row["variable_search"] != HRRR_SEARCH_STRING
            or row["source"] != HRRR_SOURCE_LABEL
            or any(str(row[key]) != value for key, value in official.items())
        ):
            raise ValueError(f"{row['item_id']}: manifest is not the frozen NOAA/AWS HRRR request")
    return work.sort_values("analysis_utc").reset_index(drop=True)


def hrrr_subset_bytes_from_index(index_text: str) -> int:
    """Return exact GRIB message bytes for the frozen TMP/DPT subset.

    NOAA's wgrib-style index records the starting byte of every message.  The
    next message therefore gives the exclusive end of a selected field.  The
    frozen 2-m temperature and dewpoint fields are not terminal messages; fail
    closed if an unexpected index layout prevents an exact calculation.
    """

    records: list[tuple[int, str]] = []
    for line in str(index_text).splitlines():
        if not line.strip():
            continue
        fields = line.split(":", 2)
        if len(fields) < 3:
            raise ValueError("HRRR index contains a malformed record")
        try:
            offset = int(fields[1])
        except ValueError as exc:
            raise ValueError("HRRR index contains a non-integer byte offset") from exc
        records.append((offset, line))
    if len(records) < 2:
        raise ValueError("HRRR index contains too few records")
    offsets = np.asarray([value[0] for value in records], dtype=np.int64)
    if np.any(np.diff(offsets) <= 0):
        raise ValueError("HRRR index byte offsets are not strictly increasing")
    pattern = re.compile(HRRR_SEARCH_STRING)
    selected = [index for index, (_, line) in enumerate(records) if pattern.search(line)]
    if len(selected) != 2:
        raise ValueError(
            "HRRR index must contain exactly one 2-m TMP and one 2-m DPT message"
        )
    if selected[-1] == len(records) - 1:
        raise ValueError("selected HRRR field is terminal; exact byte size is unavailable")
    return int(sum(offsets[index + 1] - offsets[index] for index in selected))


def estimate_hrrr_subset_downloads(
    manifest: pd.DataFrame,
    *,
    index_reader: Callable[[str], str] | None = None,
    safety_factor: float = DEFAULT_STORAGE_SAFETY_FACTOR,
    max_workers: int = 8,
) -> pd.DataFrame:
    """Read only NOAA index files and estimate every selective GRIB download.

    This does not fetch a GRIB field.  The conservative estimate doubles the
    exact indexed message bytes by default to cover indexes, temporary decode
    products, retained shards, and archive variability.
    """

    planned = _validate_live_manifest(manifest)
    if safety_factor < 1:
        raise ValueError("storage safety_factor must be at least one")
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    if index_reader is None:
        from urllib.request import urlopen

        def index_reader(url: str) -> str:
            with urlopen(url, timeout=30) as response:  # noqa: S310 - frozen NOAA URL
                return response.read().decode("utf-8")

    def estimate(row: Mapping[str, Any]) -> dict[str, Any]:
        try:
            text = index_reader(str(row["index_url"]))
            exact = hrrr_subset_bytes_from_index(text)
        except Exception:
            raise HrrrFetchError(
                f"HRRR storage estimate failed for {pd.Timestamp(row['analysis_utc']).isoformat()}"
            ) from None
        return {
            "item_id": str(row["item_id"]),
            "analysis_utc": row["analysis_utc"],
            "product": str(row["product"]),
            "product_resolution": str(row["product_resolution"]),
            "object_key": str(row["object_key"]),
            "exact_subset_bytes": exact,
            "safety_factor": float(safety_factor),
            "conservative_new_data_bytes": int(np.ceil(exact * safety_factor)),
        }

    rows = planned.to_dict("records")
    if max_workers == 1:
        estimates = [estimate(row) for row in rows]
    else:
        estimates_by_item: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(estimate, row): row for row in rows}
            for future in as_completed(futures):
                item = future.result()
                estimates_by_item[item["item_id"]] = item
        estimates = [estimates_by_item[str(row["item_id"])] for row in rows]
    return pd.DataFrame(estimates)


def fetch_hrrr_domain_weather(
    manifest: pd.DataFrame,
    domains: Mapping[str, Any],
    output_dir: str | os.PathLike[str],
    *,
    loader: Callable[[pd.Timestamp], Any] | None = None,
    manifest_path: str | os.PathLike[str] | None = None,
    checkpoint_path: str | os.PathLike[str] | None = None,
    grib_cache_dir: str | os.PathLike[str] | None = None,
    minimum_domain_cells: int = 2,
    max_analysis_hours: int = DEFAULT_MAX_ANALYSIS_HOURS,
    max_workers: int = 1,
    conservative_download_bytes_by_item: Mapping[str, int] | None = None,
    max_new_data_bytes: int = DEFAULT_MAX_NEW_DATA_BYTES,
    min_free_bytes_after_peak: int = DEFAULT_MIN_FREE_BYTES_AFTER_PEAK,
    run_seal_status: str = HRRR_RUN_SEAL_STATUS,
    profile_binding: Mapping[str, Any] | None = None,
) -> HrrrRunResult:
    """Fetch/extract requested hours with per-hour checksum checkpoints.

    ``max_analysis_hours`` is a deliberate side-effect guard.  Raise it only
    after reviewing a certified usable-pass manifest; the unfiltered catalogue
    ceiling is not an appropriate input for this fetch.
    """

    planned = _validate_live_manifest(manifest)
    manifest_sha256 = canonical_hrrr_manifest_sha256(planned)
    domain_sha256 = frozen_domain_sha256(domains)
    if len(planned) > max_analysis_hours:
        raise HrrrFetchError(
            f"Refusing {len(planned)} HRRR hours; reviewed limit is {max_analysis_hours}"
        )
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    if max_new_data_bytes <= 0 or min_free_bytes_after_peak < 0:
        raise ValueError("storage guard byte limits are invalid")
    live_loader = loader is None
    root = Path(output_dir)
    shards_dir = root / "hourly_domain_cells"
    shards_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = Path(checkpoint_path) if checkpoint_path else root / "hrrr_checkpoint.json"
    manifest_file = Path(manifest_path) if manifest_path is not None else None
    manifest_file_sha256: str | None = None
    if manifest_file is not None:
        if not manifest_file.is_file():
            raise HrrrFetchError("HRRR manifest path does not exist")
        file_manifest = pd.read_csv(manifest_file)
        if canonical_hrrr_manifest_sha256(file_manifest) != manifest_sha256:
            raise HrrrFetchError(
                "HRRR manifest file differs from the canonical in-memory request"
            )
        manifest_file_sha256 = _sha256(manifest_file)
    if loader is None:
        cache = Path(grib_cache_dir) if grib_cache_dir else root / "grib_cache"
        loader = HerbieHrrrLoader(cache)
    items = _load_hrrr_checkpoint(
        checkpoint,
        manifest_sha256=manifest_sha256,
        domain_sha256=domain_sha256,
        minimum_domain_cells=minimum_domain_cells,
    )
    records = planned.to_dict("records")
    shard_by_item: dict[str, Path] = {}
    pending: list[dict[str, Any]] = []
    for row in records:
        item_id = str(row["item_id"])
        cached = _valid_shard(
            row,
            items.get(item_id),
            domains,
            domain_sha256=domain_sha256,
            minimum_domain_cells=minimum_domain_cells,
        )
        if cached is not None:
            shard_by_item[item_id] = cached
            continue
        pending.append(row)

    if live_loader:
        if conservative_download_bytes_by_item is None:
            raise HrrrFetchError(
                "Live HRRR fetch requires a reviewed per-item storage estimate"
            )
        estimates = {
            str(item): int(value)
            for item, value in conservative_download_bytes_by_item.items()
        }
        missing_estimates = sorted(
            set(planned["item_id"].astype(str)).difference(estimates)
        )
        if missing_estimates:
            raise HrrrFetchError(
                "Storage estimate lacks planned HRRR items: "
                + ", ".join(missing_estimates[:5])
            )
        estimated_total = sum(estimates[str(item)] for item in planned["item_id"])
        if estimated_total > max_new_data_bytes:
            raise HrrrFetchError(
                f"Refusing estimated {estimated_total} bytes of HRRR new data; "
                f"budget is {max_new_data_bytes} bytes"
            )
        pending_sizes = sorted(
            (estimates[str(row["item_id"])] for row in pending), reverse=True
        )
        conservative_peak = sum(pending_sizes[:max_workers])
        disk_anchor = root if root.exists() else root.parent
        free_bytes = shutil.disk_usage(disk_anchor).free
        if free_bytes - conservative_peak < min_free_bytes_after_peak:
            raise HrrrFetchError(
                f"Insufficient free space for conservative HRRR peak {conservative_peak} bytes; "
                f"free={free_bytes}, required reserve={min_free_bytes_after_peak}"
            )

    def load_and_extract(row: Mapping[str, Any]) -> pd.DataFrame:
        item_id = str(row["item_id"])
        requested_cities = tuple(filter(None, str(row["cities"]).split("|")))
        unknown = sorted(set(requested_cities).difference(domains))
        if unknown:
            raise ValueError(f"{item_id}: no frozen domain supplied for {unknown}")
        selected_domains = {city: domains[city] for city in requested_cities}
        timestamp = pd.Timestamp(row["analysis_utc"])
        dataset = None
        try:
            dataset = loader(timestamp)
            cells = extract_domain_cells(
                dataset,
                selected_domains,
                analysis_utc=timestamp,
                minimum_domain_cells=minimum_domain_cells,
            )
        except (HrrrDependencyError, ValueError):
            raise
        except Exception:
            raise HrrrFetchError(f"HRRR extraction failed for {timestamp.isoformat()}") from None
        finally:
            close = getattr(dataset, "close", None)
            if callable(close):
                close()
        return cells

    def persist(row: Mapping[str, Any], cells: pd.DataFrame) -> None:
        item_id = str(row["item_id"])
        city_counts = _validate_shard_contents(
            cells,
            row,
            domains,
            minimum_domain_cells=minimum_domain_cells,
        )
        shard = shards_dir / f"{item_id}.csv.gz"
        temporary = shard.with_name(f".{shard.name}.tmp")
        cells.to_csv(temporary, index=False, compression="gzip")
        temporary.replace(shard)
        items[item_id] = {
            "schema_version": HRRR_CHECKPOINT_SCHEMA_VERSION,
            "shard_schema_version": HRRR_SHARD_SCHEMA_VERSION,
            "status": "complete",
            "frozen_domain_sha256": domain_sha256,
            "request_binding": _canonical_request_binding(row),
            "request_sha256": _json_sha256(_canonical_request_binding(row)),
            "shard_columns": list(HRRR_SHARD_COLUMNS),
            "local_path": str(shard),
            "size_bytes": shard.stat().st_size,
            "sha256": _sha256(shard),
            "n_rows": int(len(cells)),
            "city_row_counts": city_counts,
        }
        _write_hrrr_checkpoint(
            checkpoint,
            items,
            manifest_sha256=manifest_sha256,
            domain_sha256=domain_sha256,
            minimum_domain_cells=minimum_domain_cells,
        )
        shard_by_item[item_id] = shard

    if max_workers == 1:
        for row in pending:
            persist(row, load_and_extract(row))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_rows = {
                executor.submit(load_and_extract, row): row for row in pending
            }
            for future in as_completed(future_rows):
                row = future_rows[future]
                persist(row, future.result())

    expected_item_ids = {str(row["item_id"]) for row in records}
    if set(items) != expected_item_ids:
        raise HrrrFetchError(
            "HRRR checkpoint item set differs from the canonical manifest"
        )
    shards = [shard_by_item[str(row["item_id"])] for row in records]
    validated_cells: list[pd.DataFrame] = []
    for row, path in zip(records, shards, strict=True):
        validated = _valid_shard(
            row,
            items.get(str(row["item_id"])),
            domains,
            domain_sha256=domain_sha256,
            minimum_domain_cells=minimum_domain_cells,
        )
        if validated is None or validated.resolve() != path.resolve():
            raise HrrrFetchError(
                f"{row['item_id']}: persisted HRRR shard failed final validation"
            )
        validated_cells.append(pd.read_csv(path, parse_dates=["timestamp_utc"]))

    all_cells = pd.concat(validated_cells, ignore_index=True)
    summary = summarize_domain_cells(all_cells)
    summary_path = root / "hrrr_hourly_domain_summary.csv"
    summary_tmp = summary_path.with_name(f".{summary_path.name}.tmp")
    summary.to_csv(summary_tmp, index=False)
    summary_tmp.replace(summary_path)

    shard_rows = []
    for row, path in zip(planned.to_dict("records"), shards, strict=True):
        item = items[str(row["item_id"])]
        binding = _canonical_request_binding(row)
        shard_rows.append(
            {
                "schema_version": HRRR_CHECKPOINT_SCHEMA_VERSION,
                "shard_schema_version": HRRR_SHARD_SCHEMA_VERSION,
                "item_id": row["item_id"],
                "analysis_utc": row["analysis_utc"],
                "cities": row["cities"],
                "n_target_passes": int(row["n_target_passes"]),
                "model": row["model"],
                "product": row["product"],
                "product_resolution": row["product_resolution"],
                "forecast_hour": int(row["forecast_hour"]),
                "variable_search": row["variable_search"],
                "object_key": row["object_key"],
                "request_sha256": _json_sha256(binding),
                "frozen_domain_sha256": domain_sha256,
                "local_path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "n_rows": int(item["n_rows"]),
                "city_row_counts": json.dumps(
                    item["city_row_counts"], sort_keys=True, separators=(",", ":")
                ),
                "source": HRRR_SOURCE_LABEL,
            }
        )
    shard_index = pd.DataFrame(shard_rows)
    shard_index_path = root / "hrrr_hourly_shard_index.csv"
    shard_tmp = shard_index_path.with_name(f".{shard_index_path.name}.tmp")
    shard_index.to_csv(shard_tmp, index=False)
    shard_tmp.replace(shard_index_path)
    shard_set = [
        {
            "item_id": str(row["item_id"]),
            "request_sha256": str(items[str(row["item_id"])]["request_sha256"]),
            "sha256": str(items[str(row["item_id"])]["sha256"]),
            "n_rows": int(items[str(row["item_id"])]["n_rows"]),
            "city_row_counts": items[str(row["item_id"])]["city_row_counts"],
        }
        for row in records
    ]
    run_seal_path = root / "hrrr_run_seal.json"
    if not str(run_seal_status).startswith("PASS_EXACT_HRRR_RUN_SEAL"):
        raise ValueError("HRRR run-seal status is not an approved exact-HRRR PASS label")
    normalized_profile_binding = (
        json.loads(json.dumps(profile_binding, sort_keys=True, default=str))
        if profile_binding is not None
        else None
    )
    run_seal = {
        "schema_version": HRRR_RUN_SEAL_SCHEMA_VERSION,
        "status": str(run_seal_status),
        "manifest_path": str(manifest_file) if manifest_file is not None else None,
        "manifest_file_sha256": manifest_file_sha256,
        "manifest_canonical_sha256": manifest_sha256,
        "manifest_fields": list(HRRR_CHECKPOINT_REQUEST_FIELDS),
        "frozen_domain_sha256": domain_sha256,
        "domain_names": sorted(str(city) for city in domains),
        "minimum_domain_cells": int(minimum_domain_cells),
        "checkpoint_path": str(checkpoint),
        "checkpoint_sha256": _sha256(checkpoint),
        "shard_index_path": str(shard_index_path),
        "shard_index_sha256": _sha256(shard_index_path),
        "summary_path": str(summary_path),
        "summary_sha256": _sha256(summary_path),
        "shard_set_sha256": _json_sha256(shard_set),
        "counts": {
            "manifest_items": int(len(planned)),
            "checkpoint_items": int(len(items)),
            "shard_index_rows": int(len(shard_index)),
            "summary_rows": int(len(summary)),
            "shard_cell_rows": int(len(all_cells)),
            "requested_city_hours": int(
                sum(len(str(value).split("|")) for value in planned["cities"])
            ),
        },
        "checkpoint_schema_version": HRRR_CHECKPOINT_SCHEMA_VERSION,
        "shard_schema_version": HRRR_SHARD_SCHEMA_VERSION,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
    }
    if normalized_profile_binding is not None:
        run_seal["profile_binding"] = normalized_profile_binding
        run_seal["profile_binding_sha256"] = _json_sha256(
            normalized_profile_binding
        )
    _atomic_json(run_seal_path, run_seal)
    validate_hrrr_run_seal(
        run_seal_path,
        planned,
        domains,
        root,
        manifest_path=manifest_file,
        checkpoint_path=checkpoint,
        minimum_domain_cells=minimum_domain_cells,
        expected_status=run_seal_status,
        expected_profile_binding=normalized_profile_binding,
    )
    return HrrrRunResult(
        summary,
        shard_index,
        summary_path,
        shard_index_path,
        checkpoint,
        run_seal_path,
    )


def _assert_frame_values_equal(
    actual: pd.DataFrame,
    expected: pd.DataFrame,
    *,
    label: str,
    timestamp_columns: Iterable[str] = (),
) -> None:
    if tuple(actual.columns) != tuple(expected.columns):
        raise HrrrFetchError(f"{label} columns differ from the frozen schema")
    if len(actual) != len(expected):
        raise HrrrFetchError(f"{label} row count differs from recomputation")
    timestamp_names = set(timestamp_columns)
    for column in expected.columns:
        if column in timestamp_names:
            actual_values = _utc_series(actual[column], label=f"{label} {column}")
            expected_values = _utc_series(
                expected[column], label=f"recomputed {label} {column}"
            )
            if not actual_values.reset_index(drop=True).equals(
                expected_values.reset_index(drop=True)
            ):
                raise HrrrFetchError(
                    f"{label} {column} differs from recomputation"
                )
            continue
        if pd.api.types.is_numeric_dtype(expected[column]):
            actual_values = pd.to_numeric(actual[column], errors="coerce").to_numpy(float)
            expected_values = pd.to_numeric(expected[column], errors="coerce").to_numpy(float)
            if not np.allclose(
                actual_values,
                expected_values,
                rtol=1e-12,
                atol=1e-12,
                equal_nan=True,
            ):
                raise HrrrFetchError(
                    f"{label} {column} differs from recomputation"
                )
            continue
        actual_values = actual[column].fillna("<NA>").astype(str).tolist()
        expected_values = expected[column].fillna("<NA>").astype(str).tolist()
        if actual_values != expected_values:
            raise HrrrFetchError(f"{label} {column} differs from recomputation")


def validate_hrrr_run_seal(
    run_seal_path: str | os.PathLike[str],
    manifest: pd.DataFrame,
    domains: Mapping[str, Any],
    output_dir: str | os.PathLike[str],
    *,
    manifest_path: str | os.PathLike[str] | None = None,
    checkpoint_path: str | os.PathLike[str] | None = None,
    minimum_domain_cells: int = 2,
    expected_status: str = HRRR_RUN_SEAL_STATUS,
    expected_profile_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute and validate the exact HRRR run represented by one seal."""

    seal_path = Path(run_seal_path)
    if not seal_path.is_file():
        raise HrrrFetchError("exact HRRR run seal is absent")
    try:
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        raise HrrrFetchError("exact HRRR run seal is unreadable") from None
    planned = _validate_live_manifest(manifest)
    root = Path(output_dir)
    checkpoint = (
        Path(checkpoint_path)
        if checkpoint_path is not None
        else root / "hrrr_checkpoint.json"
    )
    shard_index_path = root / "hrrr_hourly_shard_index.csv"
    summary_path = root / "hrrr_hourly_domain_summary.csv"
    current_manifest_sha256 = canonical_hrrr_manifest_sha256(planned)
    current_domain_sha256 = frozen_domain_sha256(domains)

    exact_fields = {
        "schema_version": HRRR_RUN_SEAL_SCHEMA_VERSION,
        "status": str(expected_status),
        "manifest_canonical_sha256": current_manifest_sha256,
        "manifest_fields": list(HRRR_CHECKPOINT_REQUEST_FIELDS),
        "frozen_domain_sha256": current_domain_sha256,
        "domain_names": sorted(str(city) for city in domains),
        "minimum_domain_cells": int(minimum_domain_cells),
        "checkpoint_schema_version": HRRR_CHECKPOINT_SCHEMA_VERSION,
        "shard_schema_version": HRRR_SHARD_SCHEMA_VERSION,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
    }
    for field, expected in exact_fields.items():
        if seal.get(field) != expected:
            raise HrrrFetchError(f"exact HRRR run seal has stale {field}")
    normalized_profile_binding = (
        json.loads(json.dumps(expected_profile_binding, sort_keys=True, default=str))
        if expected_profile_binding is not None
        else None
    )
    if normalized_profile_binding is None:
        if "profile_binding" in seal or "profile_binding_sha256" in seal:
            raise HrrrFetchError("exact HRRR run seal has an unexpected profile binding")
    elif (
        seal.get("profile_binding") != normalized_profile_binding
        or seal.get("profile_binding_sha256")
        != _json_sha256(normalized_profile_binding)
    ):
        raise HrrrFetchError("exact HRRR run seal has a stale profile binding")

    artifact_paths = {
        "checkpoint": checkpoint,
        "shard_index": shard_index_path,
        "summary": summary_path,
    }
    for name, path in artifact_paths.items():
        if not path.is_file():
            raise HrrrFetchError(f"exact HRRR {name} artifact is absent")
        stored_path = seal.get(f"{name}_path")
        if not stored_path or Path(str(stored_path)).resolve() != path.resolve():
            raise HrrrFetchError(f"exact HRRR run seal points to a stale {name}")
        if seal.get(f"{name}_sha256") != _sha256(path):
            raise HrrrFetchError(f"exact HRRR {name} artifact hash is stale")

    manifest_file = Path(manifest_path) if manifest_path is not None else None
    if manifest_file is None:
        if seal.get("manifest_path") is not None or seal.get("manifest_file_sha256") is not None:
            raise HrrrFetchError("exact HRRR run seal has an unexpected manifest file")
    else:
        if not manifest_file.is_file():
            raise HrrrFetchError("current HRRR manifest file is absent")
        if (
            not seal.get("manifest_path")
            or Path(str(seal["manifest_path"])).resolve() != manifest_file.resolve()
            or seal.get("manifest_file_sha256") != _sha256(manifest_file)
            or canonical_hrrr_manifest_sha256(pd.read_csv(manifest_file))
            != current_manifest_sha256
        ):
            raise HrrrFetchError("exact HRRR manifest file binding is stale")

    items = _load_hrrr_checkpoint(
        checkpoint,
        manifest_sha256=current_manifest_sha256,
        domain_sha256=current_domain_sha256,
        minimum_domain_cells=minimum_domain_cells,
    )
    records = planned.to_dict("records")
    expected_ids = [str(row["item_id"]) for row in records]
    if set(items) != set(expected_ids):
        raise HrrrFetchError(
            "exact HRRR checkpoint item set differs from the current manifest"
        )

    all_cells: list[pd.DataFrame] = []
    expected_index_rows: list[dict[str, Any]] = []
    shard_set: list[dict[str, Any]] = []
    for row in records:
        item_id = str(row["item_id"])
        path = _valid_shard(
            row,
            items.get(item_id),
            domains,
            domain_sha256=current_domain_sha256,
            minimum_domain_cells=minimum_domain_cells,
        )
        expected_path = root / "hourly_domain_cells" / f"{item_id}.csv.gz"
        if path is None or path.resolve() != expected_path.resolve():
            raise HrrrFetchError(f"{item_id}: exact HRRR shard validation failed")
        item = items[item_id]
        binding = _canonical_request_binding(row)
        all_cells.append(pd.read_csv(path, parse_dates=["timestamp_utc"]))
        expected_index_rows.append(
            {
                "schema_version": HRRR_CHECKPOINT_SCHEMA_VERSION,
                "shard_schema_version": HRRR_SHARD_SCHEMA_VERSION,
                "item_id": item_id,
                "analysis_utc": row["analysis_utc"],
                "cities": row["cities"],
                "n_target_passes": int(row["n_target_passes"]),
                "model": row["model"],
                "product": row["product"],
                "product_resolution": row["product_resolution"],
                "forecast_hour": int(row["forecast_hour"]),
                "variable_search": row["variable_search"],
                "object_key": row["object_key"],
                "request_sha256": _json_sha256(binding),
                "frozen_domain_sha256": current_domain_sha256,
                "local_path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "n_rows": int(item["n_rows"]),
                "city_row_counts": json.dumps(
                    item["city_row_counts"], sort_keys=True, separators=(",", ":")
                ),
                "source": HRRR_SOURCE_LABEL,
            }
        )
        shard_set.append(
            {
                "item_id": item_id,
                "request_sha256": str(item["request_sha256"]),
                "sha256": str(item["sha256"]),
                "n_rows": int(item["n_rows"]),
                "city_row_counts": item["city_row_counts"],
            }
        )

    recomputed_cells = pd.concat(all_cells, ignore_index=True)
    recomputed_summary = summarize_domain_cells(recomputed_cells)
    stored_summary = pd.read_csv(summary_path)
    _assert_frame_values_equal(
        stored_summary,
        recomputed_summary,
        label="HRRR summary",
        timestamp_columns=("timestamp_utc",),
    )
    expected_index = pd.DataFrame(expected_index_rows)
    stored_index = pd.read_csv(shard_index_path)
    _assert_frame_values_equal(
        stored_index,
        expected_index,
        label="HRRR shard index",
        timestamp_columns=("analysis_utc",),
    )

    expected_counts = {
        "manifest_items": int(len(planned)),
        "checkpoint_items": int(len(items)),
        "shard_index_rows": int(len(stored_index)),
        "summary_rows": int(len(stored_summary)),
        "shard_cell_rows": int(len(recomputed_cells)),
        "requested_city_hours": int(
            sum(len(str(value).split("|")) for value in planned["cities"])
        ),
    }
    if seal.get("counts") != expected_counts:
        raise HrrrFetchError("exact HRRR run seal counts differ from recomputation")
    if seal.get("shard_set_sha256") != _json_sha256(shard_set):
        raise HrrrFetchError("exact HRRR shard-set hash differs from recomputation")
    return seal


__all__ = [
    "DEFAULT_MAX_ANALYSIS_HOURS",
    "DEFAULT_MAX_NEW_DATA_BYTES",
    "DEFAULT_MIN_FREE_BYTES_AFTER_PEAK",
    "DEFAULT_STORAGE_SAFETY_FACTOR",
    "HRRR_BUCKET",
    "HRRR_FORECAST_HOUR",
    "HRRR_FALLBACK_ANALYSIS_HOURS",
    "HRRR_FALLBACK_PRODUCT",
    "HRRR_FALLBACK_PRODUCT_RESOLUTION",
    "HRRR_HTTPS_ROOT",
    "HRRR_MODEL",
    "HRRR_PRODUCT",
    "HRRR_PRIMARY_PRODUCT_RESOLUTION",
    "HRRR_SEARCH_STRING",
    "HRRR_RUN_SEAL_STATUS",
    "HRRR_SOURCE_LABEL",
    "HerbieHrrrLoader",
    "HrrrDependencyError",
    "HrrrFetchError",
    "HrrrRunResult",
    "build_hrrr_request_manifest",
    "canonical_hrrr_manifest_sha256",
    "dependency_status",
    "estimate_hrrr_subset_downloads",
    "extract_domain_cells",
    "fetch_hrrr_domain_weather",
    "frozen_domain_sha256",
    "hrrr_subset_bytes_from_index",
    "official_hrrr_object",
    "official_hrrr_product",
    "saturation_vapour_pressure_kpa",
    "summarize_domain_cells",
    "validate_hrrr_run_seal",
    "vpd_kpa",
]
