#!/usr/bin/env python3
"""Step 2 feasibility audit: catalogue, solar time, attrition, and pass counts.

This module deliberately separates *catalogue search* from data download.  The
only network-facing function is :func:`search_earthaccess_summers`; everything
else operates on ordinary pandas tables and can be tested with synthetic data.

The canonical scene table contains one row per city and acquisition instant.
Tiles from the same pass are collapsed before counts are produced, so a city
covered by two ECOSTRESS tiles still contributes one observation.

Typical use
-----------
1. Search CMR with ``search_earthaccess_summers`` (no Earthdata password is
   embedded or requested by this module).
2. Add independently audited geolocation, obstruction, and view-angle fields,
   then call ``prepare_catalogue`` and ``filter_usable_passes``.
3. Derive cloud survival from pixel masks with ``summarize_cloud_masks`` and
   ``estimate_cloud_survival``.
4. Call ``build_step2_deliverables`` after acquisition-time weather
   percentiles have been joined to the scene table.

The local-solar-time calculation never applies a civil time-zone conversion.
It uses UTC, longitude, and the equation of time directly.  pvlib is used for
zenith/azimuth when available; a deterministic NOAA-style approximation is
included for offline tests and for a transparent cross-check.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


DAYTIME_START_HOUR = 10.0
DAYTIME_END_HOUR = 18.0
CIVIL_TWILIGHT_ELEVATION_DEG = -6.0
NEAR_NADIR_MAX_VIEW_ZENITH_DEG = 20.0
TIME_STRATA = ("10-12", "12-14", "14-16", "16-18")

# Official ECOSTRESS operating epochs.  JPL records three-band acquisition
# beginning 15 May 2019, a mixed three-/five-band transition beginning
# 28 April 2023, and five-band-only acquisition from 18 May 2023 onward.
REDUCED_MODE_START = pd.Timestamp("2019-05-15T00:00:00Z")
FIRMWARE_FIX = pd.Timestamp("2023-04-28T00:00:00Z")
FIVE_BAND_ONLY_START = pd.Timestamp("2023-05-18T00:00:00Z")

QUALITY_LEVELS = ("best", "good", "suspect", "poor")
QUALITY_RANK = {name: rank for rank, name in enumerate(QUALITY_LEVELS)}
USABLE_QUALITY = frozenset(("best", "good"))

ATTRITION_STAGES = (
    "total_granules",
    "daytime_10_18_lst",
    "geolocation_best_good",
    "not_obstruction_flagged",
    "near_nadir",
    "surviving_cloud_screening",
)


@dataclasses.dataclass(frozen=True)
class CityDomain:
    """Minimum frozen-domain information needed for a catalogue query."""

    city: str
    centroid_latitude: float
    centroid_longitude: float
    bbox_wsen: tuple[float, float, float, float]

    def validate(self) -> None:
        west, south, east, north = self.bbox_wsen
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError(
                f"{self.city}: bbox must be (west, south, east, north) in degrees"
            )
        if not (-90 <= self.centroid_latitude <= 90):
            raise ValueError(f"{self.city}: invalid centroid latitude")
        if not (-180 <= self.centroid_longitude <= 180):
            raise ValueError(f"{self.city}: invalid centroid longitude")


@dataclasses.dataclass(frozen=True)
class FeasibilityRules:
    """Predeclared descriptive thresholds for the Step-2 gate.

    These defaults are intentionally modest and apply to *expected* passes
    after cloud attrition.  Step 3, not this rule, determines statistical power.
    A project should freeze any changed values before looking at thermal data.
    """

    minimum_expected_total: float = 100.0
    minimum_expected_per_city: float = 10.0
    minimum_expected_per_pooled_stratum: float = 10.0
    minimum_off_diagonal_per_corner: int = 10


def _as_utc(values: Any) -> pd.DatetimeIndex:
    """Parse timestamps once and guarantee a UTC-aware DatetimeIndex."""

    # pandas 2 infers one format for an entire vector.  CMR legitimately mixes
    # whole-second and fractional-second ISO timestamps, so request mixed ISO
    # parsing explicitly instead of rejecting otherwise valid granules.
    try:
        parsed = pd.to_datetime(values, utc=True, errors="coerce", format="mixed")
    except TypeError:  # pragma: no cover - compatibility with older pandas
        parsed = pd.to_datetime(values, utc=True, errors="coerce")
    index = pd.DatetimeIndex(parsed)
    if index.isna().any():
        bad = np.flatnonzero(index.isna()).tolist()
        raise ValueError(f"Unparseable acquisition timestamp(s) at position(s) {bad}")
    return index


def _nested_get(record: Mapping[str, Any], path: Sequence[Any]) -> Any:
    value: Any = record
    for key in path:
        if isinstance(key, int):
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                return None
            if key >= len(value):
                return None
            value = value[key]
        else:
            if not isinstance(value, Mapping) or key not in value:
                return None
            value = value[key]
    return value


def _first_path(record: Mapping[str, Any], paths: Sequence[Sequence[Any]]) -> Any:
    for path in paths:
        value = _nested_get(record, path)
        if value not in (None, "", []):
            return value
    return None


def _record_mapping(granule: Any) -> Mapping[str, Any]:
    if isinstance(granule, Mapping):
        return granule
    data = getattr(granule, "data", None)
    if isinstance(data, Mapping):
        return data
    raise TypeError("Granule must be a mapping or expose a mapping-valued .data")


def _additional_attributes(record: Mapping[str, Any]) -> dict[str, Any]:
    attributes = _first_path(
        record,
        (("umm", "AdditionalAttributes"), ("AdditionalAttributes",)),
    )
    out: dict[str, Any] = {}
    if not isinstance(attributes, Sequence) or isinstance(attributes, (str, bytes)):
        return out
    for item in attributes:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("Name", item.get("name", ""))).strip().lower()
        values = item.get("Values", item.get("values", item.get("Value")))
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            values = values[0] if values else None
        if name:
            out[name] = values
    return out


_TILE_RE = re.compile(r"(?:^|_)(?P<tile>\d{2}[A-Z]{3})(?:_|$)")
_ORBIT_RE = re.compile(r"_L2T_[A-Z0-9]+_(?P<orbit>\d+)_")
_SCENE_RE = re.compile(
    r"_L2T_[A-Z0-9]+_(?P<orbit>\d+)_(?P<scene>\d+)_"
)


def normalize_geolocation_quality(value: Any) -> str:
    """Normalize scene-level geolocation labels to four ordered classes.

    Missing/unrecognized metadata is classified ``suspect`` and is therefore
    excluded until an explicit audit resolves it.
    """

    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "suspect"
    text = str(value).strip().lower().replace("_", " ").replace("-", " ")
    aliases = {
        "0": "best",
        "best": "best",
        "excellent": "best",
        "1": "good",
        "good": "good",
        "nominal": "good",
        "2": "suspect",
        "suspect": "suspect",
        "questionable": "suspect",
        "unknown": "suspect",
        "3": "poor",
        "poor": "poor",
        "bad": "poor",
    }
    return aliases.get(text, "suspect")


def normalize_band_mode(value: Any, band_count: Any = None) -> str | None:
    """Normalize reported mode/band count without guessing post-fix metadata."""

    if band_count is not None and not pd.isna(band_count):
        try:
            count = int(float(band_count))
        except (TypeError, ValueError):
            count = -1
        if count >= 5:
            return "full"
        if 0 < count <= 3:
            return "reduced"
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip().lower().replace("_", " ").replace("-", " ")
    if text in {"full", "full band", "full bands", "five band", "5 band", "5"}:
        return "full"
    if text in {
        "reduced",
        "reduced band",
        "reduced bands",
        "three band",
        "3 band",
        "3",
    }:
        return "reduced"
    return None


def assign_retrieval_band_mode(
    acquisition_utc: Any,
    observed_mode: Sequence[Any] | pd.Series | None = None,
    band_count: Sequence[Any] | pd.Series | None = None,
) -> pd.Series:
    """Assign documented operating epochs and retain transition/later reports.

    Before 15 May 2019 the instrument is labelled full.  From 15 May 2019
    through 27 April 2023 it is labelled reduced.  On/after the 28 April 2023
    transition start, mode must come from scene metadata; absent metadata is
    explicitly ``post_fix_unknown`` rather than silently assumed.  In
    particular, the five-band-only epoch is validated later rather than used
    to impute a missing scene report.
    """

    times = _as_utc(acquisition_utc)
    n = len(times)
    observed = list(observed_mode) if observed_mode is not None else [None] * n
    counts = list(band_count) if band_count is not None else [None] * n
    if len(observed) != n or len(counts) != n:
        raise ValueError("observed_mode and band_count must match timestamps")
    modes: list[str] = []
    for timestamp, raw_mode, raw_count in zip(times, observed, counts, strict=True):
        if timestamp < REDUCED_MODE_START:
            modes.append("full")
        elif timestamp < FIRMWARE_FIX:
            modes.append("reduced")
        else:
            modes.append(normalize_band_mode(raw_mode, raw_count) or "post_fix_unknown")
    return pd.Series(modes, index=getattr(acquisition_utc, "index", None), dtype="string")


def _footprint_json(record: Mapping[str, Any]) -> str | None:
    footprint = _first_path(
        record,
        (
            ("footprint",),
            ("geometry",),
            ("umm", "SpatialExtent", "HorizontalSpatialDomain", "Geometry"),
        ),
    )
    if footprint is None:
        return None
    return json.dumps(footprint, sort_keys=True, separators=(",", ":"), default=str)


def normalize_granule_metadata(
    granules: Iterable[Any],
    domain: CityDomain,
) -> pd.DataFrame:
    """Normalize earthaccess-style UMM metadata into the Step-2 scene schema."""

    domain.validate()
    rows: list[dict[str, Any]] = []
    for granule in granules:
        record = _record_mapping(granule)
        attrs = _additional_attributes(record)
        granule_id = _first_path(
            record,
            (
                ("granule_id",),
                ("producer_granule_id",),
                ("meta", "native-id"),
                ("umm", "GranuleUR"),
                ("id",),
                ("title",),
            ),
        )
        if granule_id is None:
            raise ValueError(f"{domain.city}: granule metadata has no stable identifier")
        granule_id = str(granule_id)
        acquisition = _first_path(
            record,
            (
                ("acquisition_utc",),
                ("time_start",),
                (
                    "umm",
                    "TemporalExtent",
                    "RangeDateTime",
                    "BeginningDateTime",
                ),
                ("TemporalExtent", "RangeDateTime", "BeginningDateTime"),
            ),
        )
        if acquisition is None:
            raise ValueError(f"{granule_id}: metadata has no acquisition start time")

        orbit = _first_path(
            record,
            (
                ("orbit",),
                ("umm", "OrbitCalculatedSpatialDomains", 0, "OrbitNumber"),
                ("OrbitCalculatedSpatialDomains", 0, "OrbitNumber"),
            ),
        )
        if orbit is None:
            match = _ORBIT_RE.search(granule_id)
            orbit = match.group("orbit") if match else "unknown"

        scene = _first_path(record, (("scene",), ("scene_id",)))
        if scene is None:
            match = _SCENE_RE.search(granule_id)
            scene = match.group("scene") if match else "unknown"

        tile = _first_path(record, (("tile",), ("tile_id",)))
        tile = tile or attrs.get("mgrs_tile_id") or attrs.get("tile_id")
        if tile is None:
            match = _TILE_RE.search(granule_id)
            tile = match.group("tile") if match else "unknown"

        quality = _first_path(
            record,
            (("geolocation_quality",), ("geolocation_quality_summary",)),
        )
        quality = quality or attrs.get("geolocation_quality_summary")
        view_zenith = _first_path(
            record,
            (("view_zenith_deg",), ("sensor_zenith_deg",)),
        )
        view_zenith = view_zenith or attrs.get("view_zenith")
        band_count = _first_path(record, (("retrieval_band_count",), ("band_count",)))
        band_count = band_count or attrs.get("retrieval_band_count")
        reported_mode = _first_path(record, (("reported_band_mode",), ("band_mode",)))
        reported_mode = reported_mode or attrs.get("retrieval_band_mode")

        rows.append(
            {
                "city": domain.city,
                "granule_id": granule_id,
                "acquisition_utc": acquisition,
                "orbit": str(orbit),
                "scene": str(scene),
                "tile": str(tile),
                "footprint_json": _footprint_json(record),
                "centroid_latitude": float(domain.centroid_latitude),
                "centroid_longitude": float(domain.centroid_longitude),
                "geolocation_quality": normalize_geolocation_quality(quality),
                "view_zenith_deg": pd.to_numeric(view_zenith, errors="coerce"),
                "reported_band_mode": normalize_band_mode(reported_mode, band_count),
                "retrieval_band_count": pd.to_numeric(band_count, errors="coerce"),
                "metadata_source": "NASA Earthdata CMR / UMM-G",
            }
        )

    columns = (
        "city",
        "granule_id",
        "acquisition_utc",
        "orbit",
        "scene",
        "tile",
        "footprint_json",
        "centroid_latitude",
        "centroid_longitude",
        "geolocation_quality",
        "view_zenith_deg",
        "reported_band_mode",
        "retrieval_band_count",
        "metadata_source",
    )
    table = pd.DataFrame(rows, columns=columns)
    if not table.empty:
        table["acquisition_utc"] = _as_utc(table["acquisition_utc"])
    return table


def search_earthaccess_summers(
    domains: Sequence[CityDomain],
    *,
    years: Iterable[int] = range(2018, 2026),
    short_name: str,
    version: str,
    provider: str = "LPCLOUD",
    search_data: Callable[..., Sequence[Any]] | None = None,
    count: int = -1,
) -> pd.DataFrame:
    """Search CMR for June--September scenes without downloading files.

    ``version`` is required on purpose: collection versions can coexist in CMR,
    and silently pooling them can double counts.  The caller must record the
    selected version in the decision log.  Authentication is neither read nor
    initiated here; public CMR catalogue search normally needs none.
    """

    if not short_name or not version:
        raise ValueError("short_name and an explicitly frozen version are required")
    if search_data is None:
        try:
            import earthaccess  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("earthaccess is required for live catalogue search") from exc
        search_data = earthaccess.search_data

    tables: list[pd.DataFrame] = []
    for domain in domains:
        domain.validate()
        for year in years:
            start = f"{int(year):04d}-06-01T00:00:00Z"
            end = f"{int(year):04d}-09-30T23:59:59Z"
            results = search_data(
                short_name=short_name,
                version=version,
                provider=provider,
                bounding_box=domain.bbox_wsen,
                temporal=(start, end),
                count=count,
            )
            normalized = normalize_granule_metadata(results, domain)
            normalized["query_year"] = int(year)
            normalized["collection_short_name"] = short_name
            normalized["collection_version"] = version
            normalized["collection_provider"] = provider
            tables.append(normalized)
    if not tables:
        return pd.DataFrame()
    out = pd.concat(tables, ignore_index=True)
    return out.drop_duplicates(subset=["city", "granule_id"], keep="first")


def equation_of_time_minutes(acquisition_utc: Any) -> np.ndarray:
    """Approximate equation of time in minutes (NOAA fractional-year form)."""

    times = _as_utc(acquisition_utc)
    hour = times.hour + times.minute / 60 + times.second / 3600
    days = np.where(times.is_leap_year, 366.0, 365.0)
    gamma = 2 * np.pi / days * (times.dayofyear - 1 + (hour - 12) / 24)
    return 229.18 * (
        0.000075
        + 0.001868 * np.cos(gamma)
        - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2 * gamma)
        - 0.040849 * np.sin(2 * gamma)
    )


def local_solar_time_hours(acquisition_utc: Any, longitude_deg: Any) -> np.ndarray:
    """Return local apparent solar time from UTC (east longitude positive)."""

    times = _as_utc(acquisition_utc)
    longitude = np.asarray(longitude_deg, dtype=float)
    if longitude.ndim == 0:
        longitude = np.full(len(times), float(longitude))
    if len(longitude) != len(times):
        raise ValueError("longitude must be scalar or match acquisition timestamps")
    utc_minutes = times.hour * 60 + times.minute + times.second / 60
    solar_minutes = (utc_minutes + 4 * longitude + equation_of_time_minutes(times)) % 1440
    return np.asarray(solar_minutes / 60, dtype=float)


def local_solar_dates(acquisition_utc: Any, longitude_deg: Any) -> pd.Series:
    """Return the local apparent-solar calendar date for daily-weather joins."""

    times = _as_utc(acquisition_utc)
    longitude = np.asarray(longitude_deg, dtype=float)
    if longitude.ndim == 0:
        longitude = np.full(len(times), float(longitude))
    if len(longitude) != len(times):
        raise ValueError("longitude must be scalar or match acquisition timestamps")
    correction = pd.to_timedelta(
        4 * longitude + equation_of_time_minutes(times), unit="m"
    )
    apparent_solar_datetime = times + correction
    return pd.Series(apparent_solar_datetime.date)


def _interpolate_one_series(
    source_time: pd.DatetimeIndex,
    source_values: np.ndarray,
    target_time: pd.DatetimeIndex,
    max_bracket_gap_hours: float,
) -> np.ndarray:
    finite = np.isfinite(source_values)
    source_time = source_time[finite]
    source_values = source_values[finite]
    if len(source_time) < 2:
        return np.full(len(target_time), np.nan)
    order = np.argsort(source_time.asi8)
    source_ns = source_time.asi8[order]
    source_values = source_values[order]
    target_ns = target_time.asi8
    right = np.searchsorted(source_ns, target_ns, side="left")
    exact = (right < len(source_ns)) & (source_ns[np.minimum(right, len(source_ns) - 1)] == target_ns)
    left = right - 1
    valid = exact | ((left >= 0) & (right < len(source_ns)))
    safe_left = np.clip(left, 0, len(source_ns) - 1)
    safe_right = np.clip(right, 0, len(source_ns) - 1)
    bracket_hours = (source_ns[safe_right] - source_ns[safe_left]) / 3.6e12
    valid &= exact | (bracket_hours <= max_bracket_gap_hours)
    interpolated = np.interp(target_ns.astype(float), source_ns.astype(float), source_values)
    interpolated[~valid] = np.nan
    return interpolated


def join_acquisition_time_conditions(
    passes: pd.DataFrame,
    hourly_weather: pd.DataFrame,
    daily_conditions: pd.DataFrame,
    demand_reference: pd.DataFrame,
    *,
    weather_time_column: str = "timestamp_utc",
    demand_value_column: str = "vpd_kpa",
    daily_date_column: str = "date",
    dryness_column: str = "antecedent_dryness_percentile",
    max_bracket_gap_hours: float = 3.0,
    strict: bool = True,
) -> pd.DataFrame:
    """Join exact-time demand and prior-day dryness to usable passes.

    Hourly VPD is linearly interpolated in UTC.  Its percentile is evaluated
    against the frozen within-city Step-1 demand reference distribution; the
    reference is never recomputed from the satellite-selected observations.
    Antecedent dryness is joined on the *local solar date*, which avoids putting
    a late-afternoon western-US pass on the following UTC calendar day.
    """

    pass_required = {"city", "acquisition_utc", "centroid_longitude"}
    hourly_required = {"city", weather_time_column, demand_value_column}
    daily_required = {"city", daily_date_column, dryness_column}
    reference_required = {"city", demand_value_column}
    for label, table, required in (
        ("passes", passes, pass_required),
        ("hourly_weather", hourly_weather, hourly_required),
        ("daily_conditions", daily_conditions, daily_required),
        ("demand_reference", demand_reference, reference_required),
    ):
        missing = required - set(table.columns)
        if missing:
            raise ValueError(f"{label} is missing {sorted(missing)}")

    out = passes.copy()
    out["acquisition_utc"] = _as_utc(out["acquisition_utc"])
    out["local_solar_date"] = local_solar_dates(
        out["acquisition_utc"], out["centroid_longitude"]
    ).to_numpy()
    out["vpd_kpa_at_acquisition"] = np.nan

    weather = hourly_weather.copy()
    weather[weather_time_column] = _as_utc(weather[weather_time_column])
    for city, positions in out.groupby("city", sort=False).indices.items():
        city_weather = weather.loc[weather["city"] == city].sort_values(weather_time_column)
        target = _as_utc(out.iloc[positions]["acquisition_utc"])
        values = _interpolate_one_series(
            _as_utc(city_weather[weather_time_column]),
            pd.to_numeric(city_weather[demand_value_column], errors="coerce").to_numpy(),
            target,
            max_bracket_gap_hours,
        )
        out.iloc[positions, out.columns.get_loc("vpd_kpa_at_acquisition")] = values

    out["demand_percentile"] = np.nan
    for city, positions in out.groupby("city", sort=False).indices.items():
        reference = pd.to_numeric(
            demand_reference.loc[
                demand_reference["city"] == city, demand_value_column
            ],
            errors="coerce",
        ).dropna()
        if reference.empty:
            continue
        ordered = np.sort(reference.to_numpy(dtype=float))
        values = out.iloc[positions]["vpd_kpa_at_acquisition"].to_numpy(dtype=float)
        percentiles = np.searchsorted(ordered, values, side="right") / len(ordered)
        percentiles[~np.isfinite(values)] = np.nan
        out.iloc[positions, out.columns.get_loc("demand_percentile")] = percentiles

    daily = daily_conditions.copy()
    daily[daily_date_column] = pd.to_datetime(daily[daily_date_column]).dt.date
    daily = daily[["city", daily_date_column, dryness_column]].drop_duplicates(
        ["city", daily_date_column]
    )
    out = out.merge(
        daily,
        how="left",
        left_on=["city", "local_solar_date"],
        right_on=["city", daily_date_column],
        validate="many_to_one",
    )
    if daily_date_column != "local_solar_date":
        out = out.drop(columns=[daily_date_column])
    if strict:
        missing_conditions = out[
            ["vpd_kpa_at_acquisition", "demand_percentile", dryness_column]
        ].isna()
        if missing_conditions.any().any():
            counts = missing_conditions.sum().to_dict()
            raise ValueError(f"Incomplete acquisition-time weather join: {counts}")
    return out


def _fallback_solar_position(
    acquisition_utc: Any,
    latitude_deg: Any,
    longitude_deg: Any,
) -> pd.DataFrame:
    """Vectorized solar geometry approximation, azimuth clockwise from north."""

    times = _as_utc(acquisition_utc)
    latitude = np.asarray(latitude_deg, dtype=float)
    longitude = np.asarray(longitude_deg, dtype=float)
    if latitude.ndim == 0:
        latitude = np.full(len(times), float(latitude))
    if longitude.ndim == 0:
        longitude = np.full(len(times), float(longitude))
    if len(latitude) != len(times) or len(longitude) != len(times):
        raise ValueError("latitude/longitude must be scalar or match timestamps")

    hour = times.hour + times.minute / 60 + times.second / 3600
    days = np.where(times.is_leap_year, 366.0, 365.0)
    gamma = 2 * np.pi / days * (times.dayofyear - 1 + (hour - 12) / 24)
    declination = (
        0.006918
        - 0.399912 * np.cos(gamma)
        + 0.070257 * np.sin(gamma)
        - 0.006758 * np.cos(2 * gamma)
        + 0.000907 * np.sin(2 * gamma)
        - 0.002697 * np.cos(3 * gamma)
        + 0.00148 * np.sin(3 * gamma)
    )
    local_hour = local_solar_time_hours(times, longitude)
    hour_angle = np.deg2rad(local_hour * 15 - 180)
    latitude_rad = np.deg2rad(latitude)
    cos_zenith = (
        np.sin(latitude_rad) * np.sin(declination)
        + np.cos(latitude_rad) * np.cos(declination) * np.cos(hour_angle)
    )
    zenith = np.rad2deg(np.arccos(np.clip(cos_zenith, -1, 1)))
    azimuth = (
        np.rad2deg(
            np.arctan2(
                np.sin(hour_angle),
                np.cos(hour_angle) * np.sin(latitude_rad)
                - np.tan(declination) * np.cos(latitude_rad),
            )
        )
        + 180
    ) % 360
    return pd.DataFrame(
        {
            "solar_zenith_deg": zenith,
            "solar_azimuth_deg": azimuth,
            "solar_elevation_deg": 90 - zenith,
        },
        index=times,
    )


def solar_position(
    acquisition_utc: Any,
    latitude_deg: Any,
    longitude_deg: Any,
    *,
    engine: str = "auto",
) -> pd.DataFrame:
    """Compute solar geometry using pvlib when requested/available.

    ``engine='auto'`` prefers pvlib and otherwise uses the deterministic
    approximation.  ``engine='pvlib'`` raises if pvlib is unavailable, making a
    production dependency failure visible rather than silently changing method.
    """

    if engine not in {"auto", "pvlib", "fallback"}:
        raise ValueError("engine must be 'auto', 'pvlib', or 'fallback'")
    times = _as_utc(acquisition_utc)
    latitude = np.asarray(latitude_deg, dtype=float)
    longitude = np.asarray(longitude_deg, dtype=float)
    if latitude.ndim == 0:
        latitude = np.full(len(times), float(latitude))
    if longitude.ndim == 0:
        longitude = np.full(len(times), float(longitude))

    if engine in {"auto", "pvlib"}:
        try:
            import pvlib  # type: ignore
        except ImportError:
            if engine == "pvlib":
                raise RuntimeError("pvlib is required for engine='pvlib'") from None
        else:
            # pvlib accepts one location per call, so preserve correctness for
            # multi-city vectors by evaluating each unique coordinate pair.
            result = pd.DataFrame(index=times)
            result["solar_zenith_deg"] = np.nan
            result["solar_azimuth_deg"] = np.nan
            coordinate_frame = pd.DataFrame(
                {"latitude": latitude, "longitude": longitude}, index=times
            )
            for (lat, lon), positions in coordinate_frame.groupby(
                ["latitude", "longitude"], sort=False
            ).indices.items():
                integer_positions = np.asarray(positions, dtype=int)
                subset_times = times[integer_positions]
                position = pvlib.solarposition.get_solarposition(
                    subset_times, latitude=float(lat), longitude=float(lon)
                )
                result.iloc[
                    integer_positions,
                    result.columns.get_loc("solar_zenith_deg"),
                ] = position["apparent_zenith"].to_numpy()
                result.iloc[
                    integer_positions,
                    result.columns.get_loc("solar_azimuth_deg"),
                ] = position["azimuth"].to_numpy()
            result["solar_elevation_deg"] = 90 - result["solar_zenith_deg"]
            result["solar_engine"] = "pvlib"
            return result

    result = _fallback_solar_position(times, latitude, longitude)
    result["solar_engine"] = "fallback"
    return result


def assign_time_stratum(local_solar_hour: Any) -> pd.Series:
    """Assign [10,12), [12,14), [14,16), and [16,18] solar-time bins."""

    values = np.asarray(local_solar_hour, dtype=float)
    labels = np.full(values.shape, None, dtype=object)
    labels[(values >= 10) & (values < 12)] = "10-12"
    labels[(values >= 12) & (values < 14)] = "12-14"
    labels[(values >= 14) & (values < 16)] = "14-16"
    labels[(values >= 16) & (values <= 18)] = "16-18"
    return pd.Series(pd.Categorical(labels, categories=TIME_STRATA, ordered=True))


def prepare_catalogue(
    catalogue: pd.DataFrame,
    *,
    obstruction_scene_ids: Iterable[str] = (),
    solar_engine: str = "auto",
    near_nadir_max_view_zenith_deg: float = NEAR_NADIR_MAX_VIEW_ZENITH_DEG,
) -> pd.DataFrame:
    """Add solar, time-bin, mode, obstruction, and screening columns."""

    required = {
        "city",
        "granule_id",
        "acquisition_utc",
        "orbit",
        "tile",
        "centroid_latitude",
        "centroid_longitude",
        "geolocation_quality",
    }
    missing = required - set(catalogue.columns)
    if missing:
        raise ValueError(f"Catalogue is missing required columns: {sorted(missing)}")
    out = catalogue.copy()
    out["acquisition_utc"] = _as_utc(out["acquisition_utc"])
    if "scene" not in out:
        out["scene"] = out["granule_id"].astype(str).str.extract(
            _SCENE_RE, expand=True
        )["scene"].fillna("unknown")
    out["geolocation_quality"] = out["geolocation_quality"].map(
        normalize_geolocation_quality
    )
    reported = out.get("reported_band_mode", pd.Series(None, index=out.index))
    band_count = out.get("retrieval_band_count", pd.Series(np.nan, index=out.index))
    out["retrieval_band_mode"] = assign_retrieval_band_mode(
        out["acquisition_utc"], reported, band_count
    ).to_numpy()

    position = solar_position(
        out["acquisition_utc"],
        out["centroid_latitude"],
        out["centroid_longitude"],
        engine=solar_engine,
    ).reset_index(drop=True)
    for column in position.columns:
        out[column] = position[column].to_numpy()
    out["local_solar_time_hours"] = local_solar_time_hours(
        out["acquisition_utc"], out["centroid_longitude"]
    )
    out["day_of_year"] = out["acquisition_utc"].dt.dayofyear.astype(int)
    out["year"] = out["acquisition_utc"].dt.year.astype(int)
    out["daytime"] = out["local_solar_time_hours"].between(
        DAYTIME_START_HOUR, DAYTIME_END_HOUR, inclusive="both"
    )
    out["night"] = out["solar_elevation_deg"] < CIVIL_TWILIGHT_ELEVATION_DEG
    out["night_zenith_threshold_deg"] = 90 - CIVIL_TWILIGHT_ELEVATION_DEG
    out["time_stratum"] = assign_time_stratum(out["local_solar_time_hours"]).to_numpy()

    obstruction_ids = {str(value) for value in obstruction_scene_ids}
    existing_obstruction = out.get(
        "obstruction_flag", pd.Series(False, index=out.index)
    ).fillna(False).astype(bool)
    out["obstruction_flag"] = existing_obstruction | out["granule_id"].astype(
        str
    ).isin(obstruction_ids)

    if "near_nadir" in out:
        existing_near_nadir = out["near_nadir"].fillna(False).astype(bool)
    else:
        existing_near_nadir = pd.Series(False, index=out.index)
    angles = pd.to_numeric(
        out.get("view_zenith_deg", pd.Series(np.nan, index=out.index)),
        errors="coerce",
    ).abs()
    out["near_nadir"] = np.where(
        angles.notna(), angles <= near_nadir_max_view_zenith_deg, existing_near_nadir
    )
    out["geolocation_usable"] = out["geolocation_quality"].isin(USABLE_QUALITY)
    return out


def _join_unique(values: pd.Series) -> str:
    return "|".join(sorted({str(value) for value in values if pd.notna(value)}))


def deduplicate_passes(catalogue: pd.DataFrame) -> pd.DataFrame:
    """Collapse all tiles/scenes from one city-orbit to one pass record.

    A large urban domain can intersect adjacent tiled-product scenes from the
    same ISS overpass.  Their acquisition starts differ by seconds, so exact
    timestamp de-duplication would incorrectly count one physical pass more
    than once.  ECOSTRESS orbit numbers are mission-unique; an explicit
    timestamp fallback is used only when an orbit is unavailable.
    """

    if catalogue.empty:
        return catalogue.copy()
    required = {"city", "acquisition_utc", "orbit", "granule_id", "tile"}
    missing = required - set(catalogue.columns)
    if missing:
        raise ValueError(f"Cannot de-duplicate; missing {sorted(missing)}")
    work = catalogue.copy()
    work["acquisition_utc"] = _as_utc(work["acquisition_utc"])
    known_orbit = work["orbit"].astype(str).str.lower().ne("unknown")
    work["scene_key"] = np.where(
        known_orbit,
        work["city"].astype(str) + "|orbit_" + work["orbit"].astype(str),
        work["city"].astype(str)
        + "|time_"
        + work["acquisition_utc"].dt.strftime("%Y%m%dT%H%M%S"),
    )

    rows: list[pd.Series] = []
    for _, group in work.sort_values("granule_id").groupby("scene_key", sort=True):
        time_ordered = group.sort_values(["acquisition_utc", "granule_id"]).reset_index(
            drop=True
        )
        row = time_ordered.iloc[len(time_ordered) // 2].copy()
        timestamps = time_ordered["acquisition_utc"]
        row["acquisition_utc_first"] = timestamps.iloc[0]
        row["acquisition_utc_last"] = timestamps.iloc[-1]
        row["acquisition_utc"] = timestamps.iloc[len(timestamps) // 2]
        row["granule_id"] = _join_unique(group["granule_id"])
        row["tile"] = _join_unique(group["tile"])
        row["n_intersecting_tiles"] = int(group["tile"].nunique())
        if "scene" in group:
            row["scene"] = _join_unique(group["scene"])
            row["n_intersecting_scenes"] = int(group["scene"].nunique())
        row["geolocation_quality"] = max(
            (normalize_geolocation_quality(value) for value in group["geolocation_quality"]),
            key=lambda value: QUALITY_RANK[value],
        )
        row["geolocation_usable"] = row["geolocation_quality"] in USABLE_QUALITY
        if "obstruction_flag" in group:
            row["obstruction_flag"] = bool(group["obstruction_flag"].fillna(False).any())
        if "near_nadir" in group:
            row["near_nadir"] = bool(group["near_nadir"].fillna(False).all())
        if "view_zenith_deg" in group:
            angle = pd.to_numeric(group["view_zenith_deg"], errors="coerce").abs()
            row["view_zenith_deg"] = angle.max() if angle.notna().any() else np.nan
        if "footprint_json" in group:
            row["footprint_json"] = json.dumps(
                [value for value in group["footprint_json"] if pd.notna(value)],
                separators=(",", ":"),
            )
        if "retrieval_band_mode" in group:
            modes = sorted(set(group["retrieval_band_mode"].dropna().astype(str)))
            row["retrieval_band_mode"] = modes[0] if len(modes) == 1 else "mixed"
        rows.append(row)
    out = pd.DataFrame(rows).reset_index(drop=True)
    return out.sort_values(["city", "acquisition_utc"]).reset_index(drop=True)


def filter_usable_passes(catalogue: pd.DataFrame) -> pd.DataFrame:
    """Apply all non-cloud scene filters; cloud survival is an expected fraction."""

    required = {
        "daytime",
        "geolocation_usable",
        "obstruction_flag",
        "near_nadir",
        "time_stratum",
    }
    missing = required - set(catalogue.columns)
    if missing:
        raise ValueError(f"Prepared catalogue is missing {sorted(missing)}")
    keep = (
        catalogue["daytime"].astype(bool)
        & catalogue["geolocation_usable"].astype(bool)
        & ~catalogue["obstruction_flag"].astype(bool)
        & catalogue["near_nadir"].astype(bool)
        & catalogue["time_stratum"].notna()
    )
    return catalogue.loc[keep].copy().reset_index(drop=True)


def summarize_cloud_masks(
    *,
    city: str,
    month: str,
    usable_masks: Sequence[np.ndarray],
    domain_mask: np.ndarray | None = None,
    is_primary: bool,
    scene_ids: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Count domain pixels surviving a proper QC/cloud mask for one month."""

    if not usable_masks:
        raise ValueError("At least one scene mask is required")
    arrays = [np.asarray(mask, dtype=bool) for mask in usable_masks]
    shape = arrays[0].shape
    if any(array.shape != shape for array in arrays):
        raise ValueError("Every usable mask must share one grid shape")
    domain = np.ones(shape, dtype=bool) if domain_mask is None else np.asarray(domain_mask, bool)
    if domain.shape != shape:
        raise ValueError("domain_mask must match scene masks")
    n_domain = int(domain.sum())
    if n_domain == 0:
        raise ValueError("domain_mask contains no pixels")
    ids = list(scene_ids) if scene_ids is not None else [f"scene_{i + 1}" for i in range(len(arrays))]
    if len(ids) != len(arrays):
        raise ValueError("scene_ids must match usable_masks")
    rows = []
    for scene_id, mask in zip(ids, arrays, strict=True):
        n_surviving = int((mask & domain).sum())
        rows.append(
            {
                "city": city,
                "month": str(month),
                "scene_id": str(scene_id),
                "is_primary": bool(is_primary),
                "n_domain_pixels": n_domain,
                "n_surviving_pixels": n_surviving,
                "surviving_fraction": n_surviving / n_domain,
            }
        )
    return pd.DataFrame(rows)


def estimate_cloud_survival(
    mask_samples: pd.DataFrame,
    *,
    tolerance: float = 0.10,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Estimate primary-month survival and compare an independent month.

    Returns ``(month_detail, city_summary)``.  Fractions are pooled pixel counts
    within each city-month rather than an unweighted mean of scene percentages.
    """

    required = {
        "city",
        "month",
        "is_primary",
        "n_domain_pixels",
        "n_surviving_pixels",
    }
    missing = required - set(mask_samples.columns)
    if missing:
        raise ValueError(f"Cloud samples are missing {sorted(missing)}")
    samples = mask_samples.copy()
    if (samples["n_domain_pixels"] <= 0).any():
        raise ValueError("n_domain_pixels must be positive")
    if (
        (samples["n_surviving_pixels"] < 0)
        | (samples["n_surviving_pixels"] > samples["n_domain_pixels"])
    ).any():
        raise ValueError("Surviving pixel count must lie within domain pixel count")

    month = (
        samples.groupby(["city", "month", "is_primary"], as_index=False)
        .agg(
            n_scenes=("scene_id", "nunique")
            if "scene_id" in samples
            else ("month", "size"),
            n_domain_pixels=("n_domain_pixels", "sum"),
            n_surviving_pixels=("n_surviving_pixels", "sum"),
        )
    )
    month["surviving_fraction"] = (
        month["n_surviving_pixels"] / month["n_domain_pixels"]
    )

    summaries = []
    for city, group in month.groupby("city", sort=True):
        primary = group.loc[group["is_primary"]]
        validation = group.loc[~group["is_primary"]]
        if len(primary) != 1:
            raise ValueError(f"{city}: exactly one primary month is required")
        primary_row = primary.iloc[0]
        validation_fraction = (
            float(
                np.average(
                    validation["surviving_fraction"],
                    weights=validation["n_domain_pixels"],
                )
            )
            if not validation.empty
            else np.nan
        )
        difference = (
            abs(float(primary_row["surviving_fraction"]) - validation_fraction)
            if np.isfinite(validation_fraction)
            else np.nan
        )
        summaries.append(
            {
                "measured_city": city,
                "primary_month": primary_row["month"],
                "validation_months": "|".join(validation["month"].astype(str)),
                "cloud_survival_fraction": float(primary_row["surviving_fraction"]),
                "validation_fraction": validation_fraction,
                "absolute_difference": difference,
                "tolerance": tolerance,
                "representative": bool(np.isfinite(difference) and difference <= tolerance),
                "n_primary_scenes": int(primary_row["n_scenes"]),
                "n_validation_scenes": int(validation["n_scenes"].sum()),
                "estimation_method": "pooled surviving domain pixels / pooled domain pixels",
            }
        )
    return month, pd.DataFrame(summaries)


def resolve_cloud_survival(
    cities: Iterable[str],
    cloud_summary: pd.DataFrame,
    reference_city_by_city: Mapping[str, str],
) -> pd.DataFrame:
    """Map measured dry/humid reference months to every city explicitly."""

    required = {"measured_city", "cloud_survival_fraction"}
    if required - set(cloud_summary.columns):
        raise ValueError("cloud_summary lacks measured city/fraction")
    lookup = cloud_summary.set_index("measured_city")
    rows = []
    for city in sorted(set(cities)):
        if city not in reference_city_by_city:
            raise ValueError(f"No cloud-survival reference mapping for {city}")
        reference = reference_city_by_city[city]
        if reference not in lookup.index:
            raise ValueError(f"Cloud-survival reference {reference!r} was not measured")
        source = lookup.loc[reference]
        rows.append(
            {
                "city": city,
                "cloud_reference_city": reference,
                "cloud_survival_fraction": float(source["cloud_survival_fraction"]),
                "cloud_validation_fraction": source.get("validation_fraction", np.nan),
                "cloud_representative": bool(source.get("representative", False)),
                "cloud_estimation_method": source.get("estimation_method", "not recorded"),
            }
        )
    return pd.DataFrame(rows)


def build_attrition_table(
    catalogue: pd.DataFrame,
    cloud_survival: pd.DataFrame,
    *,
    pass_cloud_weight_column: str | None = None,
) -> pd.DataFrame:
    """Create T2.2's sequential scene attrition and expected cloud-adjusted count."""

    required_cloud = {"city", "cloud_survival_fraction", "cloud_reference_city"}
    if required_cloud - set(cloud_survival.columns):
        raise ValueError("Resolved cloud survival table is incomplete")
    survival = cloud_survival.set_index("city")
    rows = []
    for city, group in catalogue.groupby("city", sort=True):
        if city not in survival.index:
            raise ValueError(f"No resolved cloud survival fraction for {city}")
        source = survival.loc[city]
        masks = [pd.Series(True, index=group.index)]
        masks.append(masks[-1] & group["daytime"].astype(bool))
        masks.append(masks[-1] & group["geolocation_usable"].astype(bool))
        masks.append(masks[-1] & ~group["obstruction_flag"].astype(bool))
        masks.append(masks[-1] & group["near_nadir"].astype(bool))
        counts = [float(mask.sum()) for mask in masks]
        if pass_cloud_weight_column is None:
            cloud_fraction = float(source["cloud_survival_fraction"])
            cloud_expected = counts[-1] * cloud_fraction
        else:
            if pass_cloud_weight_column not in group:
                raise ValueError(
                    f"catalogue lacks pass cloud weight {pass_cloud_weight_column!r}"
                )
            selected_weights = pd.to_numeric(
                group.loc[masks[-1], pass_cloud_weight_column], errors="coerce"
            )
            if (
                selected_weights.isna().any()
                or not bool(selected_weights.between(0.0, 1.0).all())
            ):
                raise ValueError(
                    f"{city}: usable pass cloud weights must be finite in [0, 1]"
                )
            cloud_expected = float(selected_weights.sum())
            cloud_fraction = cloud_expected / counts[-1] if counts[-1] else np.nan
        counts.append(cloud_expected)
        total = counts[0]
        for index, (stage, count_value) in enumerate(zip(ATTRITION_STAGES, counts, strict=True)):
            previous = counts[index - 1] if index else total
            rows.append(
                {
                    "city": city,
                    "stage_order": index + 1,
                    "stage": stage,
                    "count_or_expected_count": count_value,
                    "stage_retention_pct": 100 * count_value / previous if previous else np.nan,
                    "total_retention_pct": 100 * count_value / total if total else np.nan,
                    "count_kind": "expected" if stage == ATTRITION_STAGES[-1] else "observed",
                    "cloud_survival_fraction": cloud_fraction,
                    "cloud_reference_city": source["cloud_reference_city"],
                    "cloud_representative": bool(source.get("cloud_representative", False)),
                    "cloud_estimation_method": source.get(
                        "cloud_estimation_method", "not recorded"
                    ),
                }
            )
    return pd.DataFrame(rows)


def usable_pass_counts(
    usable: pd.DataFrame,
    *,
    cities: Sequence[str] | None = None,
    years: Sequence[int] | None = None,
) -> pd.DataFrame:
    """Build T2.1 as a complete city × year × time-stratum cube plus totals."""

    cities = list(cities) if cities is not None else sorted(usable["city"].unique())
    years = list(years) if years is not None else sorted(usable["year"].unique())
    index = pd.MultiIndex.from_product(
        [cities, years, TIME_STRATA], names=["city", "year", "time_stratum"]
    )
    detail = (
        usable.groupby(["city", "year", "time_stratum"], observed=True)
        .size()
        .reindex(index, fill_value=0)
        .rename("n_usable_passes")
        .reset_index()
    )
    if "expected_cloud_weight" in usable:
        weighted = (
            usable.groupby(["city", "year", "time_stratum"], observed=True)[
                "expected_cloud_weight"
            ]
            .sum()
            .reindex(index, fill_value=0.0)
            .rename("expected_usable_pass_equivalents")
            .reset_index()
        )
        detail = detail.merge(
            weighted,
            on=["city", "year", "time_stratum"],
            how="left",
            validate="one_to_one",
        )
    detail["count_scope"] = "detail"
    value_columns = ["n_usable_passes"]
    if "expected_usable_pass_equivalents" in detail:
        value_columns.append("expected_usable_pass_equivalents")
    city_year = detail.groupby(["city", "year"], as_index=False)[value_columns].sum()
    city_year["time_stratum"] = "ALL"
    city_year["count_scope"] = "city_year_total"
    city_stratum = detail.groupby(
        ["city", "time_stratum"], as_index=False, observed=True
    )[value_columns].sum()
    city_stratum["year"] = "ALL"
    city_stratum["count_scope"] = "city_stratum_total"
    city_total = detail.groupby("city", as_index=False)[value_columns].sum()
    city_total["year"] = "ALL"
    city_total["time_stratum"] = "ALL"
    city_total["count_scope"] = "city_total"
    overall = pd.DataFrame(
        [
            {
                "city": "ALL",
                "year": "ALL",
                "time_stratum": "ALL",
                "n_usable_passes": int(len(usable)),
                **(
                    {
                        "expected_usable_pass_equivalents": float(
                            usable["expected_cloud_weight"].sum()
                        )
                    }
                    if "expected_cloud_weight" in usable
                    else {}
                ),
                "count_scope": "grand_total",
            }
        ]
    )
    return pd.concat([detail, city_year, city_stratum, city_total, overall], ignore_index=True)


def scene_metadata_dictionary() -> pd.DataFrame:
    """Return T2.3: field names, units, meaning, and authoritative source."""

    rows = [
        ("city", "text", "Frozen analysis-domain label", "frozen city-domain record"),
        ("granule_id", "text", "All tile identifiers represented by the pass", "CMR UMM-G GranuleUR/native-id"),
        ("scene_key", "text", "city|orbit de-duplication key; UTC-second fallback only for unknown orbit", "derived"),
        ("acquisition_utc", "UTC ISO-8601", "Median intersecting tiled-scene acquisition start used for the pass", "CMR UMM-G temporal extent / derived"),
        ("acquisition_utc_first", "UTC ISO-8601", "Earliest intersecting tiled-scene acquisition start", "CMR UMM-G temporal extent / derived"),
        ("acquisition_utc_last", "UTC ISO-8601", "Latest intersecting tiled-scene acquisition start", "CMR UMM-G temporal extent / derived"),
        ("orbit", "identifier", "Instrument orbit number", "CMR UMM-G or granule name"),
        ("scene", "identifier(s)", "Tiled-product scene number(s) represented by the pass", "granule name"),
        ("tile", "MGRS identifier", "Intersecting tiled-product tile(s)", "CMR UMM-G/additional attributes or name"),
        ("footprint_json", "GeoJSON/UMM JSON", "Catalogue footprint geometry", "CMR UMM-G spatial extent"),
        ("n_intersecting_tiles", "count", "Tiles collapsed into this one pass", "derived"),
        ("n_intersecting_scenes", "count", "Adjacent tiled-product scenes collapsed into this one pass", "derived"),
        ("centroid_latitude", "degrees north", "Frozen domain centroid latitude", "city-domain record"),
        ("centroid_longitude", "degrees east", "Frozen domain centroid longitude", "city-domain record"),
        ("local_solar_time_hours", "decimal solar hour", "UTC corrected by longitude and equation of time; no time zone", "derived"),
        ("local_solar_date", "apparent-solar calendar date", "Calendar date used for the daily antecedent-weather join", "derived"),
        ("solar_zenith_deg", "degrees", "Apparent zenith at domain centroid", "pvlib or declared fallback"),
        ("solar_azimuth_deg", "degrees clockwise from north", "Solar azimuth at domain centroid", "pvlib or declared fallback"),
        ("solar_elevation_deg", "degrees", "90 minus solar zenith", "derived"),
        ("day_of_year", "integer 1-366", "Acquisition day of year; retained separately from solar angle", "derived"),
        ("daytime", "boolean", "Local solar time in closed interval 10:00-18:00", "preregistered Step-2 rule"),
        ("night", "boolean", "Solar elevation below -6 degrees (civil twilight)", "preregistered Step-2 rule"),
        ("time_stratum", "category", "10-12, 12-14, 14-16, or 16-18 local solar time", "preregistered Step-2 rule"),
        ("retrieval_band_mode", "category", "full, reduced, mixed, or post-fix unknown", "date rule plus scene metadata"),
        ("geolocation_quality", "ordered category", "best, good, suspect, or poor; worst tile retained", "published scene summary / audit"),
        ("obstruction_flag", "boolean", "Any tile/pass appears on published solar-array obstruction list", "published obstruction scene list"),
        ("view_zenith_deg", "degrees", "Pass-level p95 absolute sensor view zenith over valid frozen-domain pixels", "native ECOSTRESS tiled view_zenith COG / derived"),
        ("near_nadir", "boolean", f"At least 95% domain view coverage and p95 absolute view zenith <= {NEAR_NADIR_MAX_VIEW_ZENITH_DEG:g} degrees", "preregistered Step-2 rule / native quality raster"),
        ("vpd_kpa_at_acquisition", "kPa", "Hourly VPD linearly interpolated to acquisition UTC", "hourly weather product"),
        ("demand_percentile", "0-1 within city", "Hourly demand interpolated to acquisition UTC", "hourly weather product / Step 1"),
        ("antecedent_dryness_percentile", "0-1 within city", "Higher means drier antecedent climatic water balance", "Step 1"),
        ("year", "integer year", "Calendar year of the representative acquisition UTC", "derived"),
        ("query_year", "integer year", "Summer year used in the immutable catalogue query", "CMR query provenance"),
        ("domain_geoid", "Census GEOID", "Frozen 2020 Census Urban Area identifier", "TIGERweb frozen-domain record"),
        ("domain_intersects", "boolean", "Catalogue footprint intersects the frozen city domain", "CMR footprint / derived"),
        ("collection_short_name", "text", "ECOSTRESS collection short name", "CMR collection metadata"),
        ("collection_version", "text", "ECOSTRESS collection version", "CMR collection metadata"),
        ("collection_concept_id", "CMR identifier", "Pinned collection concept identifier", "CMR collection metadata"),
        ("metadata_source", "text", "Catalogue metadata adapter/source label", "derived provenance"),
        ("solar_engine", "category", "Solar-position implementation used for this row", "derived provenance"),
        ("night_zenith_threshold_deg", "degrees", "Zenith equivalent of the frozen civil-twilight night rule", "derived"),
        ("reported_band_mode", "category", "Band-mode label reported by official metadata when present", "L2T JSON sidecar"),
        ("retrieval_band_count", "count", "Minimum official retrieval band count represented by the pass", "L2T JSON NumberOfBands"),
        ("number_of_bands_min", "count", "Minimum NumberOfBands across the pass's tiled scenes", "L2T JSON sidecar / derived"),
        ("n_l2t_tiles", "count", "Number of official L2T tile records represented", "L2T JSON sidecars / derived"),
        ("official_orbit_scene_key", "identifier(s)", "Official orbit/scene join key(s)", "granule names / derived"),
        ("official_scene_granule_ids", "text", "Official tiled-scene granule identifiers joined to the pass", "CMR/L2T JSON sidecars"),
        ("product_quality", "category", "Official product-quality label retained as a diagnostic", "L2T JSON sidecar"),
        ("automatic_quality_flag", "category", "Official automatic quality flag retained as a diagnostic", "L2T JSON sidecar"),
        ("field_of_view_obstruction_any", "boolean/unknown", "Whether any official tiled scene reports field-of-view obstruction", "L2T JSON sidecar"),
        ("published_obstruction_flag", "boolean", "Whether any represented scene occurs in the published obstruction list", "LP DAAC obstruction list"),
        ("obstruction_status", "category", "Resolved obstruction evidence status", "official sidecar plus published list / derived"),
        ("qa_percent_cloud_cover_max", "percent", "Maximum metadata cloud-cover percentage across represented tiles", "L2T JSON sidecar; diagnostic only"),
        ("qa_percent_cloud_cover", "percent", "Pass-level metadata cloud-cover percentage", "L2T JSON sidecar; diagnostic only"),
        ("l2t_metadata_sources", "text", "Official L2T sidecars contributing to the pass", "derived provenance"),
        ("geo_metadata_sources", "text", "Official geolocation records contributing to the pass", "JPL flag table or L1B GEO DMR++"),
        ("official_metadata_complete", "boolean", "All frozen official metadata fields needed before raster screening are present", "derived validation"),
        ("metadata_warnings", "text", "Conservative metadata gaps or conflicts", "derived validation"),
        ("geolocation_source_rule", "text", "Rule/source used to resolve best/good/suspect/poor", "derived provenance"),
        ("geolocation_usable", "boolean", "Resolved geolocation quality is best or good", "preregistered rule / official metadata"),
        ("metadata_candidate", "boolean", "Pass survives daytime, geolocation, and obstruction metadata gates", "derived"),
        ("n_domain_pixels", "count", "Frozen-domain native-grid pixel-centre denominator across canonical MGRS cores", "native ECOSTRESS view grid / derived"),
        ("n_domain_pixels_in_present_tiles", "count", "Domain pixels in MGRS tiles present for this pass", "native ECOSTRESS view grid / derived"),
        ("n_view_valid_pixels", "count", "Frozen-domain pixels with a physical view angle", "native ECOSTRESS view_zenith COG / derived"),
        ("view_valid_fraction", "0-1", "n_view_valid_pixels divided by n_domain_pixels", "derived"),
        ("view_zenith_abs_min_deg", "degrees", "Minimum absolute view zenith over valid domain pixels", "native view_zenith COG / derived"),
        ("view_zenith_abs_median_deg", "degrees", "Median absolute view zenith over valid domain pixels", "native view_zenith COG / derived"),
        ("view_zenith_abs_mean_deg", "degrees", "Mean absolute view zenith over valid domain pixels", "native view_zenith COG / derived"),
        ("view_zenith_abs_p95_deg", "degrees", "95th percentile absolute view zenith over valid domain pixels", "native view_zenith COG / derived"),
        ("view_zenith_abs_max_deg", "degrees", "Maximum absolute view zenith over valid domain pixels", "native view_zenith COG / derived"),
        ("near_nadir_threshold_deg", "degrees", "Frozen p95 absolute view-zenith threshold", "decision D0018"),
        ("minimum_view_coverage", "0-1", "Frozen minimum valid-domain view coverage", "decision D0018"),
        ("n_unique_mgrs_tiles", "count", "Canonical MGRS cores contributing domain pixels", "derived"),
        ("n_selected_scene_tiles", "count", "Latest-revision scene/tile rasters combined for the pass", "quality-layer manifest / derived"),
        ("n_overlapping_valid_pixels", "count", "Valid pixels seen by more than one adjacent scene before tie-breaking", "native view_zenith COG / derived"),
        ("overlap_rule", "text", "Conservative rule used where adjacent scenes overlap", "decision D0028 / derived"),
        ("n_manifest_rows_before_revision_selection", "count", "Quality-layer manifest rows represented before revision de-duplication", "quality-layer manifest / derived"),
        ("view_screen_status", "category", "Metadata-excluded, view-excluded, or near-nadir pass", "derived"),
        ("quality_candidate_pre_cloud", "boolean", "Pass survives every frozen non-cloud Step-2 quality gate", "derived"),
    ]
    return pd.DataFrame(rows, columns=["field", "units_or_type", "definition", "source"])


def condition_cell(
    demand_percentile: Any,
    antecedent_dryness_percentile: Any,
) -> pd.Series:
    """Assign nine tercile cells (higher antecedent percentile means drier)."""

    demand = np.asarray(demand_percentile, dtype=float)
    dryness = np.asarray(antecedent_dryness_percentile, dtype=float)
    if not np.isfinite(demand).all() or not np.isfinite(dryness).all():
        raise ValueError("Percentiles must be finite before classifying condition cells")
    if np.any((demand < 0) | (demand > 1) | (dryness < 0) | (dryness > 1)):
        raise ValueError("Percentiles must lie in [0, 1]")
    demand_level = np.select(
        [demand < 1 / 3, demand < 2 / 3], ["low", "middle"], default="high"
    )
    dryness_level = np.select(
        [dryness < 1 / 3, dryness < 2 / 3], ["wet", "middle"], default="dry"
    )
    return pd.Series(
        [f"demand_{demand_value}__antecedent_{dryness_value}" for demand_value, dryness_value in zip(demand_level, dryness_level, strict=True)]
    )


def pass_condition_counts(usable: pd.DataFrame) -> pd.DataFrame:
    """Physical and, when available, cloud-weighted condition-cell support."""

    required = {"city", "demand_percentile", "antecedent_dryness_percentile"}
    missing = required - set(usable.columns)
    if missing:
        raise ValueError(
            "Acquisition-time conditions must be joined before F2.5: "
            + ", ".join(sorted(missing))
        )
    work = usable.copy()
    work["condition_cell"] = condition_cell(
        work["demand_percentile"], work["antecedent_dryness_percentile"]
    ).to_numpy()
    counts = (
        work.groupby(["city", "condition_cell"])
        .size()
        .rename("n_passes")
        .reset_index()
    )
    if "expected_cloud_weight" in work:
        weights = pd.to_numeric(work["expected_cloud_weight"], errors="coerce")
        if weights.isna().any() or not bool(weights.between(0.0, 1.0).all()):
            raise ValueError("expected_cloud_weight must be finite in [0, 1]")
        work["expected_cloud_weight"] = weights
        expected = (
            work.groupby(["city", "condition_cell"])["expected_cloud_weight"]
            .sum()
            .rename("expected_pass_equivalents")
            .reset_index()
        )
        counts = counts.merge(
            expected,
            on=["city", "condition_cell"],
            how="left",
            validate="one_to_one",
        )
    counts["off_diagonal_corner"] = counts["condition_cell"].isin(
        {
            "demand_high__antecedent_wet",
            "demand_low__antecedent_dry",
        }
    )
    return counts


def _circular_hour_distance(a: float, b: float) -> float:
    return abs((a - b + 12) % 24 - 12)


def validate_local_solar_noon(
    cases: pd.DataFrame,
    *,
    engine: str = "fallback",
    tolerance_minutes: float = 5.0,
) -> pd.DataFrame:
    """Verify maximum elevation occurs at local solar noon for known cases."""

    required = {"case", "date", "latitude", "longitude"}
    missing = required - set(cases.columns)
    if missing:
        raise ValueError(f"Solar-noon cases missing {sorted(missing)}")
    rows = []
    for case in cases.itertuples(index=False):
        date = pd.Timestamp(case.date).date()
        minutes = pd.date_range(
            pd.Timestamp(date, tz="UTC"), periods=24 * 60, freq="1min"
        )
        position = solar_position(
            minutes, float(case.latitude), float(case.longitude), engine=engine
        )
        maximum_position = int(np.nanargmax(position["solar_elevation_deg"].to_numpy()))
        peak_time = minutes[maximum_position]
        peak_lst = float(local_solar_time_hours([peak_time], float(case.longitude))[0])
        offset = 60 * _circular_hour_distance(peak_lst, 12.0)
        rows.append(
            {
                "case": case.case,
                "peak_acquisition_utc": peak_time.isoformat(),
                "peak_local_solar_time_hours": peak_lst,
                "offset_from_solar_noon_minutes": offset,
                "pass": bool(offset <= tolerance_minutes),
            }
        )
    return pd.DataFrame(rows)


def validate_band_mode_assignments(catalogue: pd.DataFrame) -> tuple[bool, str]:
    """Check official band-mode epochs without requiring an unsampled mix.

    Three- and five-band acquisitions may coexist only in the documented
    28 April--17 May 2023 transition.  From 18 May 2023 onward, official JPL
    mission history says acquisition is five-band only.  An empty transition
    sample is therefore valid (and expected for a June--September study).
    Post-transition modes still must come from scene metadata; this validator
    never fills an unknown value from the date.
    """

    times = _as_utc(catalogue["acquisition_utc"])
    modes = catalogue["retrieval_band_mode"].astype(str).to_numpy()
    before = times < REDUCED_MODE_START
    forced_reduced = (times >= REDUCED_MODE_START) & (times < FIRMWARE_FIX)
    transition = (times >= FIRMWARE_FIX) & (times < FIVE_BAND_ONLY_START)
    five_band_only = times >= FIVE_BAND_ONLY_START
    invalid_before = int(np.sum(before & (modes != "full")))
    invalid_reduced = int(np.sum(forced_reduced & (modes != "reduced")))
    unknown_values = {"post_fix_unknown", "None", "nan", "<NA>"}
    valid_transition_modes = {"full", "reduced", "mixed"}
    transition_modes = set(modes[transition]) - unknown_values
    transition_unknown = int(
        np.sum(transition & np.isin(modes, list(unknown_values)))
    )
    invalid_transition = int(
        np.sum(transition & ~np.isin(modes, list(valid_transition_modes)))
    )
    five_band_modes = set(modes[five_band_only]) - unknown_values
    five_band_unknown = int(
        np.sum(five_band_only & np.isin(modes, list(unknown_values)))
    )
    invalid_five_band = int(np.sum(five_band_only & (modes != "full")))
    passed = (
        invalid_before == 0
        and invalid_reduced == 0
        and transition_unknown == 0
        and invalid_transition == 0
        and five_band_unknown == 0
        and invalid_five_band == 0
    )
    transition_sample = "sampled" if int(transition.sum()) else "not sampled"
    detail = (
        f"pre-15-May-2019 invalid={invalid_before}; forced-three-band invalid={invalid_reduced}; "
        f"transition rows={int(transition.sum())}, unknown={transition_unknown}, "
        f"invalid={invalid_transition}, modes={sorted(transition_modes)}, "
        f"sample={transition_sample}; five-band-only rows={int(five_band_only.sum())}, "
        f"unknown={five_band_unknown}, invalid={invalid_five_band}, "
        f"modes={sorted(five_band_modes)}"
    )
    return passed, detail


def run_step2_checks(
    catalogue: pd.DataFrame,
    usable: pd.DataFrame,
    count_table: pd.DataFrame,
    cloud_summary: pd.DataFrame,
    solar_noon_cases: pd.DataFrame,
    *,
    solar_engine: str = "fallback",
    cloud_tolerance: float = 0.10,
    cloud_check_mode: str = "legacy_reference",
) -> pd.DataFrame:
    """Run the six explicit Step-2 checks and return an auditable table."""

    noon = validate_local_solar_noon(solar_noon_cases, engine=solar_engine)
    noon_pass = bool(noon["pass"].all())
    strata_by_city = usable.groupby("city", observed=True)["time_stratum"].nunique()
    lst_range = usable.groupby("city")["local_solar_time_hours"].agg(lambda x: x.max() - x.min())
    coverage_pass = bool((strata_by_city >= 3).all() and (lst_range >= 4).all())
    if cloud_check_mode == "legacy_reference":
        cloud_pass = bool(
            not cloud_summary.empty
            and cloud_summary["validation_fraction"].notna().all()
            and (cloud_summary["absolute_difference"] <= cloud_tolerance).all()
        )
        cloud_check_name = "cloud subsample is representative"
        cloud_detail = (
            "absolute differences="
            f"{cloud_summary.set_index('measured_city')['absolute_difference'].round(3).to_dict()}; "
            f"tolerance={cloud_tolerance}"
        )
    elif cloud_check_mode == "candidate_census":
        independent_of_view = (
            "n_clear_pixels_independent_of_view" in cloud_summary.columns
        )
        complete_columns = ["cloud_asset_complete", "provenance_complete"]
        if independent_of_view:
            required = {
                "cloud_survival_fraction_of_domain",
                "n_clear_pixels_independent_of_view",
                *complete_columns,
            }
            rule = "candidate-specific D0035 exhaustive cloud independent of view"
        else:
            required = {
                "cloud_survival_fraction_of_domain",
                "view_asset_complete",
                *complete_columns,
            }
            complete_columns.append("view_asset_complete")
            rule = "candidate-specific D0033"
        missing = required - set(cloud_summary.columns)
        if missing:
            raise ValueError(
                f"candidate cloud census lacks required fields {sorted(missing)}"
            )
        fractions = pd.to_numeric(
            cloud_summary["cloud_survival_fraction_of_domain"], errors="coerce"
        )
        complete = cloud_summary[complete_columns].astype(bool).all(axis=1)
        cloud_pass = bool(
            len(cloud_summary) > 0
            and fractions.notna().all()
            and fractions.between(0.0, 1.0).all()
            and complete.all()
        )
        cloud_check_name = "candidate cloud census is complete"
        cloud_detail = (
            f"resolved={len(cloud_summary)}; finite={int(fractions.notna().sum())}; "
            f"complete={int(complete.sum())}; rule={rule}"
        )
    else:
        raise ValueError(f"unknown cloud_check_mode: {cloud_check_mode!r}")
    band_pass, band_detail = validate_band_mode_assignments(
        catalogue.loc[catalogue["daytime"].astype(bool)]
    )

    detail_rows = count_table.loc[count_table["count_scope"] == "detail"]
    count_sum = int(detail_rows["n_usable_passes"].sum())
    total_row = count_table.loc[count_table["count_scope"] == "grand_total"]
    recorded_total = int(total_row["n_usable_passes"].iloc[0]) if len(total_row) == 1 else -1
    counts_pass = count_sum == len(usable) == recorded_total and usable["time_stratum"].notna().all()
    duplicate_count = int(
        catalogue.duplicated(subset=["city", "acquisition_utc"], keep=False).sum()
    )
    duplicate_pass = duplicate_count == 0 and (
        "scene_key" not in catalogue
        or not catalogue.duplicated(subset=["scene_key"], keep=False).any()
    )

    return pd.DataFrame(
        [
            {
                "check": "local solar time is computed correctly",
                "pass": noon_pass,
                "detail": f"{int(noon['pass'].sum())}/{len(noon)} cases within 5 minutes of local solar noon",
            },
            {
                "check": "time-of-day coverage is plausible",
                "pass": coverage_pass,
                "detail": f"strata/city={strata_by_city.to_dict()}; LST span/city={lst_range.round(2).to_dict()}",
            },
            {
                "check": cloud_check_name,
                "pass": cloud_pass,
                "detail": cloud_detail,
            },
            {
                "check": "band-mode split is correctly assigned",
                "pass": band_pass,
                "detail": band_detail,
            },
            {
                "check": "counts are internally consistent",
                "pass": bool(counts_pass),
                "detail": f"detail sum={count_sum}; usable rows={len(usable)}; grand total={recorded_total}",
            },
            {
                "check": "duplicate granules removed",
                "pass": bool(duplicate_pass),
                "detail": f"duplicate city/acquisition rows={duplicate_count}",
            },
        ]
    )


def _plot_imports():
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    return plt, mdates


def _panel_grid(n_panels: int) -> tuple[int, int]:
    columns = 2 if n_panels <= 4 else 3
    return math.ceil(n_panels / columns), columns


def plot_local_solar_histogram(catalogue: pd.DataFrame, path: Path) -> None:
    """Create F2.1."""

    plt, _ = _plot_imports()
    cities = sorted(catalogue["city"].unique())
    rows, columns = _panel_grid(len(cities))
    figure, axes = plt.subplots(rows, columns, figsize=(4.4 * columns, 3.3 * rows), squeeze=False)
    bins = np.arange(0, 24.25, 0.5)
    for axis, city in zip(axes.flat, cities, strict=False):
        group = catalogue.loc[catalogue["city"] == city]
        daytime = group.loc[group["daytime"].astype(bool)]
        axis.hist(daytime["local_solar_time_hours"], bins=bins, color="#3977a8", alpha=0.85)
        for boundary in (10, 12, 14, 16, 18):
            axis.axvline(boundary, color="#8f2d2d", linewidth=0.8, linestyle="--")
        counts = assign_time_stratum(daytime["local_solar_time_hours"]).value_counts(sort=False)
        annotation = "  ".join(f"{label}: {int(counts.get(label, 0))}" for label in TIME_STRATA)
        axis.text(0.02, 0.97, annotation, transform=axis.transAxes, va="top", fontsize=7)
        axis.set(title=city, xlabel="Local solar time (hours)", ylabel="Pass count", xlim=(0, 24))
    for axis in axes.flat[len(cities) :]:
        axis.set_visible(False)
    figure.suptitle("F2.1 — Daytime catalogue coverage by local solar time")
    figure.tight_layout()
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def _annotated_heatmap(
    axis: Any,
    values: pd.DataFrame,
    title: str,
    *,
    count_label: str = "Usable passes",
    value_format: str = ".0f",
) -> None:
    image = axis.imshow(values.to_numpy(), aspect="auto", cmap="Blues")
    axis.set_xticks(range(len(values.columns)), labels=[str(value) for value in values.columns])
    axis.set_yticks(range(len(values.index)), labels=[str(value) for value in values.index])
    for y in range(len(values.index)):
        for x in range(len(values.columns)):
            axis.text(
                x,
                y,
                format(float(values.iloc[y, x]), value_format),
                ha="center",
                va="center",
                fontsize=8,
            )
    axis.set_title(title)
    axis.figure.colorbar(image, ax=axis, shrink=0.75, label=count_label)


def plot_count_heatmaps(
    usable: pd.DataFrame,
    path: Path,
    *,
    figure_title: str = "F2.2 — Usable pass counts",
    count_label: str = "Usable passes",
    weight_column: str | None = None,
) -> None:
    """Create F2.2."""

    plt, _ = _plot_imports()
    value_column = weight_column or "granule_id"
    aggregate = "sum" if weight_column else "count"
    by_year = usable.pivot_table(
        index="city", columns="year", values=value_column, aggfunc=aggregate, fill_value=0
    )
    by_stratum = usable.pivot_table(
        index="city",
        columns="time_stratum",
        values=value_column,
        aggfunc=aggregate,
        fill_value=0,
        observed=False,
    )
    by_stratum = by_stratum.reindex(columns=TIME_STRATA, fill_value=0)
    figure, axes = plt.subplots(1, 2, figsize=(14, max(4, 0.7 * len(by_year))))
    value_format = ".1f" if weight_column else ".0f"
    _annotated_heatmap(
        axes[0],
        by_year,
        "City × year",
        count_label=count_label,
        value_format=value_format,
    )
    _annotated_heatmap(
        axes[1],
        by_stratum,
        "City × local-solar-time stratum",
        count_label=count_label,
        value_format=value_format,
    )
    figure.suptitle(figure_title)
    figure.tight_layout()
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def plot_attrition_waterfall(attrition: pd.DataFrame, path: Path) -> None:
    """Create F2.3."""

    plt, _ = _plot_imports()
    cities = sorted(attrition["city"].unique())
    rows, columns = _panel_grid(len(cities))
    figure, axes = plt.subplots(
        rows,
        columns,
        figsize=(6.3 * columns, 3.8 * rows),
        squeeze=False,
        sharex=False,
    )
    label_by_stage = {
        "total_granules": "total",
        "daytime_10_18_lst": "10–18\ndaytime",
        "geolocation_best_good": "geo\nbest/good",
        "not_obstruction_flagged": "no\nobstruction",
        "archive_available_pre_geometry": "archive\navailable",
        "near_nadir": "near-\nnadir",
        "surviving_cloud_screening": "cloud\nexpected",
    }
    for axis, city in zip(axes.flat, cities, strict=False):
        group = attrition.loc[attrition["city"].eq(city)]
        group = group.sort_values("stage_order")
        labels = [
            label_by_stage.get(str(stage), str(stage).replace("_", "\n"))
            for stage in group["stage"]
        ]
        axis.plot(
            group["stage_order"],
            group["count_or_expected_count"],
            marker="o",
            color="#2f6f9f",
            linewidth=1.8,
        )
        finite = group["count_or_expected_count"].dropna()
        reference_height = float(finite.max()) if len(finite) else 1.0
        for row in group.itertuples(index=False):
            if np.isfinite(row.count_or_expected_count):
                annotation = (
                    f"{row.count_or_expected_count:.0f}\n"
                    f"{row.total_retention_pct:.0f}%"
                )
                axis.annotate(
                    annotation,
                    (row.stage_order, row.count_or_expected_count),
                    xytext=(0, 6),
                    textcoords="offset points",
                    ha="center",
                    fontsize=8,
                )
            else:
                axis.annotate(
                    "withheld",
                    (row.stage_order, 0.05 * reference_height),
                    color="#9b2c2c",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                    fontweight="bold",
                )
        axis.set_title(city)
        axis.set_xticks(group["stage_order"], labels, fontsize=8)
        axis.grid(axis="y", alpha=0.25)
        axis.set_ylim(bottom=0)
    for axis in axes.flat[len(cities) :]:
        axis.set_visible(False)
    for axis in axes[:, 0]:
        axis.set_ylabel("Observed or expected pass count")
    figure.suptitle("F2.3 — Sequential catalogue attrition")
    figure.tight_layout()
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def plot_pass_date_strip(catalogue: pd.DataFrame, path: Path) -> None:
    """Create F2.4."""

    plt, mdates = _plot_imports()
    cities = sorted(catalogue["city"].unique())
    colors = {"full": "#2468a2", "reduced": "#e07a1f", "mixed": "#7b4fa3", "post_fix_unknown": "#777777"}
    figure, axis = plt.subplots(figsize=(15, max(4, 0.8 * len(cities))))
    y_lookup = {city: i for i, city in enumerate(cities)}
    for mode, group in catalogue.groupby("retrieval_band_mode", dropna=False):
        axis.scatter(group["acquisition_utc"], [y_lookup[city] for city in group["city"]], s=15, alpha=0.75, label=str(mode), color=colors.get(str(mode), "#333333"))
    axis.axvline(FIRMWARE_FIX, color="#8f2d2d", linestyle="--", linewidth=1, label="firmware fix")
    axis.set_yticks(range(len(cities)), cities)
    axis.xaxis.set_major_locator(mdates.YearLocator())
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axis.set(xlabel="Acquisition date (UTC)", ylabel="City", title="F2.4 — Pass dates and retrieval band mode")
    axis.legend(
        ncol=1,
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        frameon=True,
    )
    axis.grid(axis="x", alpha=0.2)
    figure.tight_layout()
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def plot_definitive_conditions(usable: pd.DataFrame, path: Path) -> None:
    """Create F2.5 from acquisition-time demand and usable-pass dates only."""

    required = {"demand_percentile", "antecedent_dryness_percentile"}
    if required - set(usable.columns):
        raise ValueError("F2.5 requires acquisition-time demand and antecedent dryness")
    plt, _ = _plot_imports()
    cities = sorted(usable["city"].unique())
    rows, columns = _panel_grid(len(cities))
    figure, axes = plt.subplots(rows, columns, figsize=(4.3 * columns, 4 * rows), squeeze=False)
    for axis, city in zip(axes.flat, cities, strict=False):
        group = usable.loc[usable["city"] == city]
        axis.axvspan(2 / 3, 1, ymin=0, ymax=1 / 3, color="#f2cf66", alpha=0.25)
        axis.axvspan(0, 1 / 3, ymin=2 / 3, ymax=1, color="#f2cf66", alpha=0.25)
        axis.scatter(group["demand_percentile"], group["antecedent_dryness_percentile"], s=16, alpha=0.75, color="#326a8b")
        for boundary in (1 / 3, 2 / 3):
            axis.axvline(boundary, color="#555555", linewidth=0.8, linestyle="--")
            axis.axhline(boundary, color="#555555", linewidth=0.8, linestyle="--")
        cells = condition_cell(group["demand_percentile"], group["antecedent_dryness_percentile"])
        high_mask = cells.eq("demand_high__antecedent_wet").to_numpy()
        low_mask = cells.eq("demand_low__antecedent_dry").to_numpy()
        high_wet = int(high_mask.sum())
        low_dry = int(low_mask.sum())
        if "expected_cloud_weight" in group:
            weights = pd.to_numeric(group["expected_cloud_weight"], errors="raise")
            high_label = f"{high_wet} physical / {weights[high_mask].sum():.1f} expected"
            low_label = f"{low_dry} physical / {weights[low_mask].sum():.1f} expected"
        else:
            high_label = str(high_wet)
            low_label = str(low_dry)
        axis.text(0.98, 0.02, f"high demand + wet: {high_label}", ha="right", va="bottom", transform=axis.transAxes, fontsize=8)
        axis.text(0.02, 0.98, f"low demand + dry: {low_label}", ha="left", va="top", transform=axis.transAxes, fontsize=8)
        axis.set(xlim=(0, 1), ylim=(0, 1), title=city, xlabel="Demand percentile at acquisition", ylabel="Antecedent dryness percentile")
    for axis in axes.flat[len(cities) :]:
        axis.set_visible(False)
    figure.suptitle("F2.5 — Definitive condition support on usable passes")
    figure.tight_layout()
    figure.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def assess_feasibility(
    attrition: pd.DataFrame,
    usable: pd.DataFrame,
    condition_counts: pd.DataFrame,
    checks: pd.DataFrame,
    rules: FeasibilityRules,
) -> tuple[str, list[str]]:
    """Apply frozen descriptive gates; return PASS, CONDITIONAL, or STOP."""

    final = attrition.loc[attrition["stage"] == "surviving_cloud_screening"]
    expected_by_city = final.set_index("city")["count_or_expected_count"]
    expected_total = float(expected_by_city.sum())
    if "expected_cloud_weight" in usable:
        weighted_usable = usable.copy()
        weights = pd.to_numeric(
            weighted_usable["expected_cloud_weight"], errors="coerce"
        )
        if weights.isna().any() or not bool(weights.between(0.0, 1.0).all()):
            raise ValueError("expected_cloud_weight must be finite in [0, 1]")
        weighted_usable["expected_cloud_weight"] = weights
    else:
        cloud_fraction_by_city = final.set_index("city")["cloud_survival_fraction"]
        weighted_usable = usable.assign(
            expected_cloud_weight=usable["city"].map(cloud_fraction_by_city)
        )
    stratum_counts = (
        weighted_usable.groupby("time_stratum", observed=True)["expected_cloud_weight"]
        .sum()
        .reindex(TIME_STRATA, fill_value=0.0)
    )
    corner_value = (
        "expected_pass_equivalents"
        if "expected_pass_equivalents" in condition_counts
        else "n_passes"
    )
    corner = (
        condition_counts.loc[condition_counts["off_diagonal_corner"]]
        .groupby("condition_cell")[corner_value]
        .sum()
    )
    reasons = [
        f"Expected cloud-screened total: {expected_total:.1f} (minimum {rules.minimum_expected_total:g}).",
        f"Expected cloud-screened passes by city: {expected_by_city.round(1).to_dict()}.",
        f"Expected cloud-screened counts by pooled time stratum: {stratum_counts.round(1).to_dict()}.",
        f"Off-diagonal {corner_value}: {corner.round(2).to_dict()} "
        f"(minimum {rules.minimum_off_diagonal_per_corner:g} per corner).",
        f"Step-2 checks passed: {int(checks['pass'].sum())}/{len(checks)}.",
    ]
    count_support = (
        expected_total >= rules.minimum_expected_total
        and (expected_by_city >= rules.minimum_expected_per_city).all()
        and (stratum_counts >= rules.minimum_expected_per_pooled_stratum).all()
        and len(corner) == 2
        and (corner >= rules.minimum_off_diagonal_per_corner).all()
    )
    if not count_support:
        return "STOP", reasons
    if not checks["pass"].all():
        return "CONDITIONAL", reasons
    return "PASS", reasons


def write_definitive_feasibility_memo(
    path: Path,
    *,
    gate: str,
    reasons: Sequence[str],
    step1_recommendation: str,
) -> None:
    """Write the required Step-2 comparison against the Step-1 recommendation."""

    body = [
        "# Step 2 definitive feasibility memo",
        "",
        f"**Gate: {gate}.**",
        "",
        "## Evidence",
        "",
        *[f"- {reason}" for reason in reasons],
        "",
        "## Comparison with Step 1",
        "",
        step1_recommendation.strip(),
        "",
        "This Step-2 result supersedes the daily-weather-only Step-1 screen because it uses "
        "actual usable pass dates and demand at acquisition time. It remains a feasibility "
        "screen; Step 3 determines power and minimum detectable effects.",
        "",
    ]
    path.write_text("\n".join(body), encoding="utf-8")


def build_step2_deliverables(
    catalogue: pd.DataFrame,
    cloud_summary: pd.DataFrame,
    reference_city_by_city: Mapping[str, str],
    solar_noon_cases: pd.DataFrame,
    output_dir: str | Path,
    *,
    step1_recommendation: str,
    rules: FeasibilityRules = FeasibilityRules(),
    solar_check_engine: str = "fallback",
    pass_cloud_weight_column: str | None = None,
) -> dict[str, Path | str]:
    """Write F2.1--F2.5, T2.1--T2.3, checks, catalogue, and gate memo."""

    output = Path(output_dir)
    figures = output / "figures"
    tables = output / "tables"
    figures.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)

    scenes = deduplicate_passes(catalogue)
    usable = filter_usable_passes(scenes)
    if pass_cloud_weight_column is None:
        resolved_cloud = resolve_cloud_survival(
            scenes["city"].unique(), cloud_summary, reference_city_by_city
        )
        cloud_lookup = resolved_cloud.set_index("city")["cloud_survival_fraction"]
        usable["expected_cloud_weight"] = usable["city"].map(cloud_lookup)
        cloud_check_mode = "legacy_reference"
    else:
        if pass_cloud_weight_column not in usable:
            raise ValueError(
                f"usable passes lack candidate cloud weight {pass_cloud_weight_column!r}"
            )
        weights = pd.to_numeric(
            usable[pass_cloud_weight_column], errors="coerce"
        )
        if weights.isna().any() or not bool(weights.between(0.0, 1.0).all()):
            raise ValueError("candidate cloud weights must be finite in [0, 1]")
        usable["expected_cloud_weight"] = weights.to_numpy()
        city_fraction = usable.groupby("city")["expected_cloud_weight"].mean()
        candidate_cloud_method = (
            "D0035 exhaustive candidate-specific observed clear-domain fraction "
            "independent of view"
            if "n_clear_pixels_independent_of_view" in cloud_summary.columns
            else "D0033 exhaustive candidate-specific observed clear-domain fraction"
        )
        resolved_cloud = pd.DataFrame(
            {
                "city": city_fraction.index,
                "cloud_reference_city": "candidate_specific_observed",
                "cloud_survival_fraction": city_fraction.to_numpy(),
                "cloud_validation_fraction": np.nan,
                "cloud_representative": True,
                "cloud_estimation_method": candidate_cloud_method,
            }
        )
        cloud_check_mode = "candidate_census"
    if usable["expected_cloud_weight"].isna().any():
        raise ValueError("usable passes lack a resolved cloud-survival weight")
    attrition = build_attrition_table(
        scenes,
        resolved_cloud,
        pass_cloud_weight_column=pass_cloud_weight_column,
    )
    counts = usable_pass_counts(usable)
    conditions = pass_condition_counts(usable)
    checks = run_step2_checks(
        scenes,
        usable,
        counts,
        cloud_summary,
        solar_noon_cases,
        solar_engine=solar_check_engine,
        cloud_check_mode=cloud_check_mode,
    )

    paths: dict[str, Path | str] = {
        "F2.1": figures / "F2.1_local_solar_time_histogram.png",
        "F2.2": figures / "F2.2_usable_pass_heatmaps.png",
        "F2.3": figures / "F2.3_attrition_waterfall.png",
        "F2.4": figures / "F2.4_pass_date_strip.png",
        "F2.5": figures / "F2.5_definitive_conditions.png",
        "T2.1": tables / "T2.1_usable_pass_counts.csv",
        "T2.2": tables / "T2.2_attrition.csv",
        "T2.3": tables / "T2.3_scene_metadata_dictionary.csv",
        "catalogue": tables / "step2_scene_catalogue.csv",
        "conditions": tables / "step2_definitive_condition_counts.csv",
        "checks": tables / "step2_checks.csv",
        "memo": output / "step2_definitive_feasibility.md",
    }

    plot_local_solar_histogram(scenes, paths["F2.1"])  # type: ignore[arg-type]
    plot_count_heatmaps(
        usable,
        paths["F2.2"],  # type: ignore[arg-type]
        figure_title="F2.2 — Expected cloud-adjusted usable pass-equivalents",
        count_label="Expected usable pass-equivalents",
        weight_column="expected_cloud_weight",
    )
    plot_attrition_waterfall(attrition, paths["F2.3"])  # type: ignore[arg-type]
    plot_pass_date_strip(scenes, paths["F2.4"])  # type: ignore[arg-type]
    plot_definitive_conditions(usable, paths["F2.5"])  # type: ignore[arg-type]
    counts.to_csv(paths["T2.1"], index=False)  # type: ignore[arg-type]
    attrition.to_csv(paths["T2.2"], index=False)  # type: ignore[arg-type]
    scene_metadata_dictionary().to_csv(paths["T2.3"], index=False)  # type: ignore[arg-type]
    scenes.to_csv(paths["catalogue"], index=False)  # type: ignore[arg-type]
    conditions.to_csv(paths["conditions"], index=False)  # type: ignore[arg-type]
    checks.to_csv(paths["checks"], index=False)  # type: ignore[arg-type]
    gate, reasons = assess_feasibility(attrition, usable, conditions, checks, rules)
    write_definitive_feasibility_memo(
        paths["memo"],  # type: ignore[arg-type]
        gate=gate,
        reasons=reasons,
        step1_recommendation=step1_recommendation,
    )
    paths["gate"] = gate
    return paths


def write_catalogue_ceiling_audit(
    catalogue: pd.DataFrame,
    output_dir: str | Path,
) -> dict[str, Path | str]:
    """Write the metadata-only subset of Step 2 and stop at its data gate.

    CMR establishes coverage and timing, but it does not expose every field
    needed to certify a usable thermal pass.  This writer therefore records
    unresolved stages as ``not_evaluated`` instead of turning missing metadata
    into either zero attrition or valid observations.
    """

    root = Path(output_dir)
    figures = root / "figures"
    tables = root / "tables"
    checks_dir = root / "checks"
    for directory in (figures, tables, checks_dir):
        directory.mkdir(parents=True, exist_ok=True)

    scenes = deduplicate_passes(catalogue)
    daytime = scenes.loc[
        scenes["daytime"].astype(bool) & scenes["time_stratum"].notna()
    ].copy()
    counts = usable_pass_counts(daytime).rename(
        columns={"n_usable_passes": "n_daytime_catalogue_ceiling_passes"}
    )

    attrition_rows: list[dict[str, Any]] = []
    unresolved_reasons = {
        "geolocation_best_good": (
            "GeolocationAccuracyQA is not present in CMR catalogue metadata"
        ),
        "not_obstruction_flagged": (
            "Published obstruction/field-of-view flags have not been joined"
        ),
        "near_nadir": "View zenith is not present in CMR catalogue metadata",
        "surviving_cloud_screening": (
            "Pixel cloud/QC calibration granules have not been screened"
        ),
    }
    for city, group in scenes.groupby("city", sort=True):
        observed = {
            "total_granules": int(len(group)),
            "daytime_10_18_lst": int(group["daytime"].sum()),
        }
        for stage_order, stage in enumerate(ATTRITION_STAGES, start=1):
            status = "observed" if stage in observed else "not_evaluated"
            attrition_rows.append(
                {
                    "city": city,
                    "stage_order": stage_order,
                    "stage": stage,
                    "count_or_expected_count": observed.get(stage, np.nan),
                    "status": status,
                    "reason_if_not_evaluated": unresolved_reasons.get(stage, ""),
                }
            )
    attrition = pd.DataFrame(attrition_rows)

    post_fix = scenes["acquisition_utc"] >= FIRMWARE_FIX
    post_fix_unknown = int(
        (scenes.loc[post_fix, "retrieval_band_mode"] == "post_fix_unknown").sum()
    )
    checks = pd.DataFrame(
        [
            {
                "item": "pass identity",
                "status": "PASS",
                "detail": (
                    f"{len(catalogue)} tile-granules collapse to {len(scenes)} "
                    "unique city-orbit passes"
                ),
            },
            {
                "item": "local solar geometry",
                "status": "PASS",
                "detail": (
                    f"engine={_join_unique(scenes['solar_engine'])}; {len(daytime)} "
                    "passes in 10:00-18:00 local solar time"
                ),
            },
            {
                "item": "geolocation certification",
                "status": "NOT_EVALUATED",
                "detail": (
                    f"best/good certifiable from current table for "
                    f"{int(scenes['geolocation_usable'].sum())}/{len(scenes)} passes"
                ),
            },
            {
                "item": "view-angle certification",
                "status": "NOT_EVALUATED",
                "detail": (
                    f"view zenith available for "
                    f"{int(pd.to_numeric(scenes['view_zenith_deg'], errors='coerce').notna().sum())}/"
                    f"{len(scenes)} passes"
                ),
            },
            {
                "item": "post-fix retrieval mode",
                "status": "NOT_EVALUATED" if post_fix_unknown else "PASS",
                "detail": (
                    f"post-fix unknown for {post_fix_unknown}/{int(post_fix.sum())} passes"
                ),
            },
            {
                "item": "obstruction certification",
                "status": "NOT_EVALUATED",
                "detail": "CMR does not supply the required obstruction audit flag",
            },
            {
                "item": "cloud survival calibration",
                "status": "NOT_EVALUATED",
                "detail": (
                    "requires the cloud and QC layers inside selected temperature granules"
                ),
            },
            {
                "item": "exact-acquisition hourly demand",
                "status": "NOT_EVALUATED",
                "detail": (
                    "HRRR acquisition-time interpolation begins only after usable passes "
                    "are certified"
                ),
            },
        ]
    )

    paths: dict[str, Path | str] = {
        "F2.1_partial": figures / "F2.1_local_solar_time_catalogue.png",
        "F2.2_partial": figures / "F2.2_daytime_catalogue_ceiling_heatmaps.png",
        "F2.4_partial": figures / "F2.4_pass_date_strip_catalogue.png",
        "T2.1_partial": tables / "T2.1_daytime_catalogue_ceiling_counts.csv",
        "T2.2_partial": tables / "T2.2_attrition_not_evaluated.csv",
        "T2.3": tables / "T2.3_scene_metadata_dictionary.csv",
        "catalogue": tables / "step2_scene_catalogue_metadata_only.csv",
        "checks": checks_dir / "step2_catalogue_gate.csv",
        "memo": root / "M2.0_catalogue_gate.md",
        "gate": "STOP_REQUIRED_METADATA_ENRICHMENT",
    }
    plot_local_solar_histogram(scenes, paths["F2.1_partial"])  # type: ignore[arg-type]
    plot_count_heatmaps(  # type: ignore[arg-type]
        daytime,
        paths["F2.2_partial"],
        figure_title="F2.2 partial — Daytime catalogue ceiling (not usable passes)",
        count_label="Catalogue ceiling passes",
    )
    plot_pass_date_strip(scenes, paths["F2.4_partial"])  # type: ignore[arg-type]
    counts.to_csv(paths["T2.1_partial"], index=False)  # type: ignore[arg-type]
    attrition.to_csv(paths["T2.2_partial"], index=False)  # type: ignore[arg-type]
    scene_metadata_dictionary().to_csv(paths["T2.3"], index=False)  # type: ignore[arg-type]
    scenes.to_csv(paths["catalogue"], index=False)  # type: ignore[arg-type]
    checks.to_csv(paths["checks"], index=False)  # type: ignore[arg-type]

    per_city = daytime.groupby("city").size().sort_index().to_dict()
    Path(paths["memo"]).write_text(  # type: ignore[arg-type]
        "# Step 2 catalogue gate\n\n"
        "**Gate: STOP_REQUIRED_METADATA_ENRICHMENT.** The public CMR catalogue is "
        "sufficient to establish coverage and pass timing, but not to certify usable "
        "thermal passes.\n\n"
        f"- Tile-granules returned: **{len(catalogue):,}**.\n"
        f"- Unique physical city-orbit passes: **{len(scenes):,}**.\n"
        f"- Daytime 10:00–18:00 local-solar catalogue ceiling: **{len(daytime):,}** "
        f"({per_city}).\n"
        "- The ceiling is not a usable-pass count: geolocation QA, view angle, "
        "obstruction, cloud survival, and exact-time HRRR demand remain unresolved.\n"
        "- F2.3 and F2.5 are intentionally not produced. Missing filters are recorded "
        "as `not_evaluated`, never as zero attrition or as valid observations.\n\n"
        "The definitive Step-2 gate and any claim of within-city feasibility remain "
        "blocked.\n",
        encoding="utf-8",
    )
    return paths
