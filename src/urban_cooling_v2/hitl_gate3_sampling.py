"""Outcome-blind Gate-3 sampling-design audit.

This module reads or retrieves only nonthermal 2018--2025 information.  It is
deliberately fail-closed: missing candidate-city geometry, weather, cloud, or
azimuth evidence is reported as unresolved and cannot become an eligible pass.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from shapely.geometry import shape

from .domains import geometry_bbox, sha256_json, valid_analysis_geometry
from .step01_fetch import GRIDMET_BANDS, GRIDMET_COLLECTION, _reduce_collection
from .step02_catalog import (
    CityDomain,
    assign_time_stratum,
    local_solar_dates,
    local_solar_time_hours,
    normalize_granule_metadata,
)
from .step02_fetch import footprint_intersects_domain


DECISION_ID = "D0067"
YEARS = tuple(range(2018, 2026))
ANGLE_THRESHOLDS = (10, 15, 20, 25, 30)
PRIMARY_ANGLE_THRESHOLDS = (10, 15, 20, 25)
PRIMARY_CITY_WINDOWS = frozenset(
    {
        ("atlanta", "jun_sep"),
        ("denver_aurora", "jun_sep"),
        ("minneapolis_st_paul", "jun_sep"),
        ("phoenix", "phoenix_apr_may"),
    }
)
MODIS_COLLECTION = "MODIS/061/MOD13Q1"
MODIS_START = "2018-04-01"
MODIS_END = "2025-11-01"
MODIS_SCALE_M = 250
CANOPY_COLLECTION = "projects/gtac-data-publish/assets/TCC/Product_Version/2025-6"
CANOPY_BAND = "NLCD_Percent_Tree_Canopy_Cover"
CANOPY_MINIMUM_PERCENT = 10.0
MIN_VALID_FRACTION = 0.50
MIN_YEARS = 7
MEDIAN_PEAK_FRACTION = 0.90
Q1_PEAK_FRACTION = 0.80

CANDIDATE_CITY_META: dict[str, dict[str, Any]] = {
    "phoenix": {"label": "Phoenix", "geoid": "69184", "role": "primary inherited"},
    "los_angeles": {"label": "Los Angeles", "geoid": "51445", "role": "primary inherited"},
    "atlanta": {"label": "Atlanta", "geoid": "03817", "role": "primary inherited"},
    "minneapolis_st_paul": {
        "label": "Minneapolis-Saint Paul",
        "geoid": "57628",
        "role": "primary inherited",
    },
    "miami": {"label": "Miami", "geoid": "56602", "role": "exploratory humid"},
    "denver_aurora": {
        "label": "Denver-Aurora",
        "geoid": "23527",
        "role": "default semi-arid continental candidate",
    },
    "sacramento": {
        "label": "Sacramento",
        "geoid": "77068",
        "role": "seasonal comparator",
    },
}

WINDOWS: tuple[dict[str, str], ...] = (
    {"window_id": "jun_sep", "start": "06-01", "end": "09-30"},
    {"window_id": "phoenix_apr_may", "start": "04-01", "end": "05-31"},
    {"window_id": "california_october", "start": "10-01", "end": "10-31"},
)


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _analysis_feature(feature: Mapping[str, Any]) -> dict[str, Any]:
    source_geometry = dict(feature["geometry"])
    analysis_geometry = valid_analysis_geometry(source_geometry)
    props = dict(feature.get("properties", {}))
    return {
        "type": "Feature",
        "id": feature.get("id"),
        "properties": {
            **props,
            "source_geometry_sha256": sha256_json(source_geometry),
            "analysis_geometry_sha256": sha256_json(analysis_geometry),
            "topology_repair_applied": sha256_json(source_geometry) != sha256_json(analysis_geometry),
        },
        "geometry": analysis_geometry,
    }


def fetch_candidate_domains(
    existing_geojson: str | Path,
    output_geojson: str | Path,
    *,
    request_get: Callable[..., Any],
    service_url: str,
) -> dict[str, dict[str, Any]]:
    """Bind all seven candidate domains without altering the frozen five-city file."""

    existing_payload = json.loads(Path(existing_geojson).read_text(encoding="utf-8"))
    existing = {
        str(feature["properties"]["city"]): feature
        for feature in existing_payload.get("features", [])
    }
    features: list[dict[str, Any]] = []
    retrievals: list[dict[str, Any]] = []
    for slug, meta in CANDIDATE_CITY_META.items():
        if slug in existing:
            feature = dict(existing[slug])
            source = "existing checksum-bound frozen five-city domain"
        else:
            params = {
                "where": f"GEOID='{meta['geoid']}'",
                "outFields": "GEOID,UA,NAME,AREALAND,AREAWATER,CENTLAT,CENTLON",
                "returnGeometry": "true",
                "outSR": "4326",
                "geometryPrecision": "5",
                "maxAllowableOffset": "0.0005",
                "f": "geojson",
            }
            response = request_get(service_url.rstrip("/") + "/query", params=params, timeout=120)
            response.raise_for_status()
            candidates = response.json().get("features", [])
            if len(candidates) != 1:
                raise RuntimeError(f"{slug}: Census returned {len(candidates)} features")
            feature = candidates[0]
            source = "live official Census TIGERweb query"
        props = dict(feature.get("properties", {}))
        if str(props.get("GEOID", "")).zfill(5) != meta["geoid"]:
            raise ValueError(f"{slug}: wrong Census GEOID")
        feature["id"] = slug
        source_geometry_hash = sha256_json(feature["geometry"])
        feature["properties"] = {
            **props,
            "city": slug,
            "label": meta["label"],
            "g3_role": meta["role"],
            "geometry_sha256": source_geometry_hash,
        }
        analysed = _analysis_feature(feature)
        features.append(feature)
        retrievals.append(
            {
                "city": slug,
                "geoid": meta["geoid"],
                "name": props.get("NAME"),
                "area_land_km2": float(props["AREALAND"]) / 1_000_000,
                "centroid_lat": float(props["CENTLAT"]),
                "centroid_lon": float(props["CENTLON"]),
                "source": source,
                "source_geometry_sha256": source_geometry_hash,
                "analysis_geometry_sha256": analysed["properties"]["analysis_geometry_sha256"],
            }
        )
    collection = {
        "type": "FeatureCollection",
        "name": "g3_candidate_2020_census_urban_areas",
        "features": features,
    }
    destination = Path(output_geojson)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(collection, indent=2) + "\n", encoding="utf-8")
    _write_json(
        destination.with_suffix(destination.suffix + ".provenance.json"),
        {
            "retrieved_utc": datetime.now(timezone.utc).isoformat(),
            "decision_id": DECISION_ID,
            "service": service_url,
            "query_rule": "exact 2020 Census Urban Area GEOID; WGS84; precision 5; maximum offset 0.0005 degrees",
            "feature_collection_sha256": sha256_file(destination),
            "records": retrievals,
            "record_2026_queried": False,
            "temperature_or_lst_opened": False,
        },
    )
    return {feature["properties"]["city"]: _analysis_feature(feature) for feature in features}


def load_candidate_domains(path: str | Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    result = {
        str(feature["properties"]["city"]): _analysis_feature(feature)
        for feature in payload.get("features", [])
    }
    if set(result) != set(CANDIDATE_CITY_META):
        raise ValueError("Gate-3 candidate-domain set is incomplete")
    return result


def _feature_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(item.get("properties", {})) for item in payload.get("features", [])]


def fetch_modis_phenology(
    domains: Mapping[str, Mapping[str, Any]],
    raw_output: str | Path,
    *,
    ee: Any,
    project: str,
    progress: Callable[[str], None] = print,
) -> pd.DataFrame:
    """Retrieve QA-screened composite medians for the frozen 2018--2025 interval."""

    ee.Initialize(project=project)
    collection = (
        ee.ImageCollection(MODIS_COLLECTION)
        .filterDate(MODIS_START, MODIS_END)
        .filter(ee.Filter.calendarRange(2018, 2025, "year"))
        .filter(ee.Filter.calendarRange(4, 10, "month"))
    )
    canopy_collection = (
        ee.ImageCollection(CANOPY_COLLECTION)
        .filter(ee.Filter.calendarRange(2018, 2025, "year"))
        .filter(ee.Filter.eq("study_area", "CONUS"))
    )
    rows: list[dict[str, Any]] = []
    for city, feature in sorted(domains.items()):
        progress(f"phenology {city}")
        geometry = ee.Geometry(feature["geometry"])

        def reduce_image(image: Any) -> Any:
            raw = image.select("NDVI").multiply(0.0001)
            qa = image.select("SummaryQA")
            year = image.date().get("year")
            annual_canopy_collection = canopy_collection.filter(
                ee.Filter.eq("year", year)
            )
            canopy_projection = annual_canopy_collection.first().select(
                CANOPY_BAND
            ).projection()
            annual_canopy = annual_canopy_collection.mosaic().setDefaultProjection(
                canopy_projection
            )
            canopy_mean = (
                annual_canopy.select(CANOPY_BAND)
                .updateMask(annual_canopy.select("data_mask").eq(1))
                .reduceResolution(reducer=ee.Reducer.mean(), maxPixels=1024)
                .reproject(raw.projection())
                .rename("canopy_mean")
            )
            canopy_eligible = canopy_mean.gte(CANOPY_MINIMUM_PERCENT)
            primary = raw.updateMask(qa.lte(1)).rename("primary")
            good = raw.updateMask(qa.eq(0)).rename("good")
            canopy_primary = (
                raw.updateMask(qa.lte(1))
                .updateMask(canopy_eligible)
                .rename("canopy_primary")
            )
            canopy_cells = canopy_eligible.selfMask().rename("canopy_eligible")
            primary_valid = qa.lte(1).unmask(0).rename("primary_fraction")
            good_valid = qa.eq(0).unmask(0).rename("good_fraction")
            reducer = ee.Reducer.median().combine(ee.Reducer.count(), sharedInputs=True)
            stats = ee.Image.cat(primary, good, canopy_primary).reduceRegion(
                reducer=reducer,
                geometry=geometry,
                scale=MODIS_SCALE_M,
                maxPixels=1_000_000_000,
                tileScale=8,
            )
            fractions = (
                ee.Image.cat(primary_valid, good_valid)
                .reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=geometry,
                    scale=MODIS_SCALE_M,
                    maxPixels=1_000_000_000,
                    tileScale=8,
                )
            )
            canopy_stats = (
                ee.Image.cat(canopy_cells, canopy_mean.updateMask(canopy_eligible))
                .reduceRegion(
                    reducer=reducer,
                    geometry=geometry,
                    scale=MODIS_SCALE_M,
                    maxPixels=1_000_000_000,
                    tileScale=8,
                )
            )
            return ee.Feature(None, stats.combine(fractions).combine(canopy_stats)).set(
                {
                    "city": city,
                    "date": image.date().format("YYYY-MM-dd"),
                    "system_index": image.get("system:index"),
                }
            )

        payload = ee.FeatureCollection(collection.map(reduce_image)).getInfo()
        rows.extend(_feature_rows(payload))
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    if frame["date"].dt.year.min() != 2018 or frame["date"].dt.year.max() != 2025:
        raise ValueError("MODIS response escaped the frozen 2018--2025 interval")
    numeric = [
        "primary_median",
        "primary_count",
        "good_median",
        "good_count",
        "canopy_primary_median",
        "canopy_primary_count",
        "canopy_eligible_count",
        "canopy_mean_median",
        "canopy_mean_count",
        "primary_fraction",
        "good_fraction",
    ]
    for column in numeric:
        frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
    frame["primary_valid_fraction"] = frame["primary_fraction"]
    frame["good_valid_fraction"] = frame["good_fraction"]
    frame["estimated_in_domain_pixels"] = np.rint(
        frame["primary_count"] / frame["primary_valid_fraction"].replace(0, np.nan)
    )
    frame["canopy_masked_cell_fraction"] = (
        frame["canopy_eligible_count"] / frame["estimated_in_domain_pixels"]
    )
    frame["canopy_primary_valid_fraction"] = (
        frame["canopy_primary_count"] / frame["canopy_eligible_count"].replace(0, np.nan)
    )
    frame["primary_composite_usable"] = frame["primary_valid_fraction"] >= MIN_VALID_FRACTION
    frame["good_composite_usable"] = frame["good_valid_fraction"] >= MIN_VALID_FRACTION
    frame["canopy_primary_composite_usable"] = (
        frame["canopy_primary_valid_fraction"] >= MIN_VALID_FRACTION
    )
    frame["year"] = frame["date"].dt.year
    frame["month"] = frame["date"].dt.month
    frame = frame.sort_values(["city", "date"]).reset_index(drop=True)
    destination = Path(raw_output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index=False)
    _write_json(
        destination.with_suffix(destination.suffix + ".provenance.json"),
        {
            "retrieved_utc": datetime.now(timezone.utc).isoformat(),
            "decision_id": DECISION_ID,
            "collection": MODIS_COLLECTION,
            "date_filter": [MODIS_START, MODIS_END],
            "calendar_year_filter": [2018, 2025],
            "months": [4, 10],
            "ndvi_scale": 0.0001,
            "primary_summary_qa": [0, 1],
            "sensitivity_summary_qa": [0],
            "canopy_collection": CANOPY_COLLECTION,
            "canopy_band": CANOPY_BAND,
            "canopy_year_filter": [2018, 2025],
            "canopy_minimum_percent_after_modis_grid_mean": CANOPY_MINIMUM_PERCENT,
            "canopy_mask_rule": "annual same-year TCC; data_mask=1; mean to MODIS grid; retain >=10%",
            "minimum_valid_fraction": MIN_VALID_FRACTION,
            "output_sha256": sha256_file(destination),
            "record_2026_queried": False,
            "temperature_or_lst_opened": False,
        },
    )
    return frame


def summarize_leaf_on(composites: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    return summarize_leaf_on_metric(
        composites,
        median_column="primary_median",
        valid_fraction_column="primary_valid_fraction",
        usable_column="primary_composite_usable",
        analysis_id="whole_domain_qa_0_1_primary",
    )


def summarize_leaf_on_metric(
    composites: pd.DataFrame,
    *,
    median_column: str,
    valid_fraction_column: str,
    usable_column: str,
    analysis_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the same frozen leaf-on rule to one declared NDVI sensitivity."""

    required = {median_column, valid_fraction_column, usable_column, "city", "year", "month"}
    missing = required.difference(composites.columns)
    if missing:
        raise ValueError(f"{analysis_id}: missing phenology columns {sorted(missing)}")
    usable = composites.loc[composites[usable_column]].copy()
    city_year_month = (
        usable.groupby(["city", "year", "month"], as_index=False)
        .agg(
            monthly_ndvi=(median_column, "median"),
            usable_composites=(median_column, "size"),
            median_valid_fraction=(valid_fraction_column, "median"),
        )
    )
    rows: list[dict[str, Any]] = []
    for city, group in city_year_month.groupby("city", sort=True):
        month_stats = (
            group.groupby("month", as_index=False)
            .agg(
                years_available=("year", "nunique"),
                median_ndvi=("monthly_ndvi", "median"),
                q1_ndvi=("monthly_ndvi", lambda x: float(np.quantile(x, 0.25))),
                q3_ndvi=("monthly_ndvi", lambda x: float(np.quantile(x, 0.75))),
                median_valid_fraction=("median_valid_fraction", "median"),
            )
        )
        peak = float(month_stats["median_ndvi"].max())
        for record in month_stats.to_dict("records"):
            stable = bool(
                int(record["years_available"]) >= MIN_YEARS
                and float(record["median_ndvi"]) >= MEDIAN_PEAK_FRACTION * peak
                and float(record["q1_ndvi"]) >= Q1_PEAK_FRACTION * peak
            )
            rows.append(
                {
                    **record,
                    "city": city,
                    "city_peak_median_ndvi": peak,
                    "median_fraction_of_peak": float(record["median_ndvi"]) / peak if peak else math.nan,
                    "q1_fraction_of_peak": float(record["q1_ndvi"]) / peak if peak else math.nan,
                    "stable_leaf_on": stable,
                    "analysis_id": analysis_id,
                }
            )
    monthly = pd.DataFrame(rows).sort_values(["city", "month"]).reset_index(drop=True)
    window_months = {
        "jun_sep": [6, 7, 8, 9],
        "phoenix_apr_may": [4, 5],
        "california_october": [10],
    }
    candidates = [
        *( (city, "jun_sep") for city in CANDIDATE_CITY_META ),
        ("phoenix", "phoenix_apr_may"),
        ("los_angeles", "california_october"),
        ("sacramento", "california_october"),
    ]
    window_rows: list[dict[str, Any]] = []
    for city, window_id in candidates:
        months = window_months[window_id]
        selected = monthly.loc[monthly["city"].eq(city) & monthly["month"].isin(months)]
        complete = set(selected["month"].astype(int)) == set(months)
        window_rows.append(
            {
                "city": city,
                "window_id": window_id,
                "months": ",".join(str(value) for value in months),
                "months_complete": complete,
                "year_coverage_complete": bool(
                    complete and len(selected) and selected["years_available"].ge(MIN_YEARS).all()
                ),
                "all_months_stable_leaf_on": bool(complete and selected["stable_leaf_on"].all()),
                "minimum_years_available": int(selected["years_available"].min()) if len(selected) else 0,
                "minimum_median_fraction_of_peak": float(selected["median_fraction_of_peak"].min()) if len(selected) else math.nan,
                "minimum_q1_fraction_of_peak": float(selected["q1_fraction_of_peak"].min()) if len(selected) else math.nan,
                "jun_sep_retained_as_sensitivity": window_id == "jun_sep",
                "analysis_id": analysis_id,
            }
        )
    return monthly, pd.DataFrame(window_rows)


def summarize_phenology_sensitivities(
    composites: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return primary, QA-0-only, and canopy-masked frozen-rule summaries."""

    specifications = (
        (
            "whole_domain_qa_0_1_primary",
            "primary_median",
            "primary_valid_fraction",
            "primary_composite_usable",
        ),
        (
            "whole_domain_qa_0_sensitivity",
            "good_median",
            "good_valid_fraction",
            "good_composite_usable",
        ),
        (
            "canopy_masked_qa_0_1_sensitivity",
            "canopy_primary_median",
            "canopy_primary_valid_fraction",
            "canopy_primary_composite_usable",
        ),
    )
    monthly_parts: list[pd.DataFrame] = []
    window_parts: list[pd.DataFrame] = []
    for analysis_id, median, fraction, usable in specifications:
        month, window = summarize_leaf_on_metric(
            composites,
            median_column=median,
            valid_fraction_column=fraction,
            usable_column=usable,
            analysis_id=analysis_id,
        )
        monthly_parts.append(month)
        window_parts.append(window)
    monthly = pd.concat(monthly_parts, ignore_index=True)
    windows = pd.concat(window_parts, ignore_index=True)
    stable_wide = windows.pivot(
        index=["city", "window_id"],
        columns="analysis_id",
        values="all_months_stable_leaf_on",
    ).reset_index()
    coverage_wide = windows.pivot(
        index=["city", "window_id"],
        columns="analysis_id",
        values="year_coverage_complete",
    ).reset_index()
    expected = [item[0] for item in specifications]
    for column in expected:
        if column not in stable_wide:
            stable_wide[column] = False
        if column not in coverage_wide:
            coverage_wide[column] = False
    wide = stable_wide.merge(
        coverage_wide.rename(columns={column: f"{column}_coverage_complete" for column in expected}),
        on=["city", "window_id"],
        how="outer",
        validate="one_to_one",
    )
    wide["primary_phenology_pass"] = wide[expected[0]].fillna(False).astype(bool)
    wide["qa0_sensitivity_pass"] = wide[expected[1]].fillna(False).astype(bool)
    wide["canopy_sensitivity_pass"] = wide[expected[2]].fillna(False).astype(bool)
    primary_coverage = f"{expected[0]}_coverage_complete"
    qa0_coverage = f"{expected[1]}_coverage_complete"
    canopy_coverage = f"{expected[2]}_coverage_complete"
    wide["primary_phenology_coverage_complete"] = wide[primary_coverage].fillna(False).astype(bool)
    wide["qa0_sensitivity_coverage_complete"] = wide[qa0_coverage].fillna(False).astype(bool)
    wide["canopy_sensitivity_coverage_complete"] = wide[canopy_coverage].fillna(False).astype(bool)
    wide["phenology_required_eligibility_complete"] = (
        wide["primary_phenology_coverage_complete"]
        & wide["canopy_sensitivity_coverage_complete"]
    )
    wide["phenology_sensitivity_complete"] = (
        wide["phenology_required_eligibility_complete"]
        & wide["qa0_sensitivity_coverage_complete"]
    )
    wide["phenology_auto_eligible"] = (
        wide["phenology_required_eligibility_complete"]
        & wide["primary_phenology_pass"]
        & wide["canopy_sensitivity_pass"]
    )
    wide["qa0_sensitivity_status"] = np.select(
        [
            ~wide["qa0_sensitivity_coverage_complete"],
            wide["qa0_sensitivity_pass"],
        ],
        [
            "QA0_INCOMPLETE_YEAR_COVERAGE",
            "QA0_CONFIRMS",
        ],
        default="QA0_THRESHOLD_REVERSAL",
    )
    wide["phenology_status"] = np.select(
        [
            ~wide["primary_phenology_coverage_complete"],
            ~wide["primary_phenology_pass"],
            ~wide["canopy_sensitivity_coverage_complete"],
            wide["primary_phenology_pass"] & ~wide["canopy_sensitivity_pass"],
        ],
        [
            "PRIMARY_SCREEN_INCOMPLETE",
            "PRIMARY_SCREEN_FAIL",
            "CANOPY_CONFIRMATION_INCOMPLETE",
            "CANOPY_CONFIRMATION_FAIL",
        ],
        default="PRIMARY_AND_CANOPY_CONFIRMED",
    )
    return monthly, windows, wide


def _weather_bounds(city: str, year: int) -> tuple[str, str]:
    if city == "phoenix":
        return f"{year}-01-31", f"{year}-10-01"
    if city in {"los_angeles", "sacramento"}:
        return f"{year}-04-01", f"{year}-11-01"
    return f"{year}-04-01", f"{year}-10-01"


def fetch_candidate_weather(
    domains: Mapping[str, Mapping[str, Any]],
    output_csv: str | Path,
    *,
    ee: Any,
    project: str,
    progress: Callable[[str], None] = print,
    resume: bool = True,
) -> pd.DataFrame:
    ee.Initialize(project=project)
    destination = Path(output_csv)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial.csv")
    rows = pd.read_csv(partial).to_dict("records") if resume and partial.exists() else []
    completed = {(str(row["city"]), int(str(row["date"])[:4])) for row in rows}
    for city, feature in sorted(domains.items()):
        geometry = ee.Geometry(feature["geometry"])
        for year in YEARS:
            if (city, year) in completed:
                continue
            start, end = _weather_bounds(city, year)
            progress(f"weather {city} {year}")
            collection = (
                ee.ImageCollection(GRIDMET_COLLECTION)
                .filterDate(start, end)
                .filter(ee.Filter.calendarRange(year, year, "year"))
            )
            fetched = _reduce_collection(
                ee,
                collection,
                geometry,
                city=city,
                bands=GRIDMET_BANDS,
                scale=4638.3,
            )
            rows.extend(fetched)
            pd.DataFrame(rows).to_csv(partial, index=False)
    frame = pd.DataFrame(rows).rename(
        columns={"pr": "pr_mm", "eto": "eto_mm", "vpd": "vpd_kpa", "tmmx": "tmmx_k"}
    )
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    if frame["date"].dt.year.min() != 2018 or frame["date"].dt.year.max() != 2025:
        raise ValueError("GridMET response escaped the frozen 2018--2025 interval")
    for column in ("pr_mm", "eto_mm", "vpd_kpa", "tmmx_k"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.sort_values(["city", "date"]).drop_duplicates(["city", "date"])
    frame.to_csv(destination, index=False)
    partial.unlink(missing_ok=True)
    _write_json(
        destination.with_suffix(destination.suffix + ".provenance.json"),
        {
            "retrieved_utc": datetime.now(timezone.utc).isoformat(),
            "decision_id": DECISION_ID,
            "collection": GRIDMET_COLLECTION,
            "bands": list(GRIDMET_BANDS),
            "years": list(YEARS),
            "city_specific_bounds": {city: _weather_bounds(city, 2018)[0][5:] + " through " + _weather_bounds(city, 2018)[1][5:] for city in domains},
            "row_count": len(frame),
            "output_sha256": sha256_file(destination),
            "record_2026_queried": False,
            "temperature_or_lst_opened": False,
        },
    )
    return frame.reset_index(drop=True)


def add_antecedent_predictors(weather: pd.DataFrame) -> pd.DataFrame:
    out: list[pd.DataFrame] = []
    work = weather.copy()
    work["year"] = pd.to_datetime(work["date"]).dt.year
    for (city, year), group in work.groupby(["city", "year"], sort=True):
        group = group.sort_values("date").copy()
        for window in (30, 60):
            prior_pr = group["pr_mm"].shift(1)
            prior_balance = (group["pr_mm"] - group["eto_mm"]).shift(1)
            group[f"antecedent_precipitation_{window}d_mm"] = prior_pr.rolling(window, min_periods=window).sum()
            group[f"antecedent_balance_{window}d_mm"] = prior_balance.rolling(window, min_periods=window).sum()
        out.append(group)
    return pd.concat(out, ignore_index=True)


def _window_for_city_date(city: str, timestamp: pd.Timestamp) -> str | None:
    month = timestamp.month
    if 6 <= month <= 9:
        return "jun_sep"
    if city == "phoenix" and month in {4, 5}:
        return "phoenix_apr_may"
    if city in {"los_angeles", "sacramento"} and month == 10:
        return "california_october"
    return None


def candidate_day_support(weather_with_predictors: pd.DataFrame) -> pd.DataFrame:
    work = weather_with_predictors.copy()
    work["window_id"] = [
        _window_for_city_date(city, date)
        for city, date in zip(work["city"], pd.to_datetime(work["date"]))
    ]
    work = work.loc[work["window_id"].notna()].copy()
    rows: list[dict[str, Any]] = []
    for (city, window_id), group in work.groupby(["city", "window_id"], sort=True):
        required = ["vpd_kpa", "antecedent_precipitation_30d_mm", "antecedent_precipitation_60d_mm"]
        rows.append(
            {
                "city": city,
                "window_id": window_id,
                "physical_city_days": len(group),
                "complete_30d_days": int(group[["vpd_kpa", "antecedent_precipitation_30d_mm"]].notna().all(axis=1).sum()),
                "complete_60d_days": int(group[required].notna().all(axis=1).sum()),
                "vpd_min_kpa": float(group["vpd_kpa"].min()),
                "vpd_median_kpa": float(group["vpd_kpa"].median()),
                "vpd_max_kpa": float(group["vpd_kpa"].max()),
                "precip30_min_mm": float(group["antecedent_precipitation_30d_mm"].min()),
                "precip30_median_mm": float(group["antecedent_precipitation_30d_mm"].median()),
                "precip30_max_mm": float(group["antecedent_precipitation_30d_mm"].max()),
            }
        )
    return pd.DataFrame(rows)


def fetch_candidate_metadata(
    domains: Mapping[str, Mapping[str, Any]],
    output_csv: str | Path,
    *,
    search_data: Callable[..., Sequence[Any]],
    progress: Callable[[str], None] = print,
    resume: bool = True,
) -> pd.DataFrame:
    """Fetch only metadata for candidate-city/shoulder additions."""

    specs = (
        ("phoenix", "phoenix_apr_may", "04-01", "05-31"),
        ("los_angeles", "california_october", "10-01", "10-31"),
        ("denver_aurora", "jun_sep", "06-01", "09-30"),
        ("sacramento", "jun_sep", "06-01", "09-30"),
        ("sacramento", "california_october", "10-01", "10-31"),
    )
    destination = Path(output_csv)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial.csv")
    rows = pd.read_csv(partial).to_dict("records") if resume and partial.exists() else []
    completed = {(str(row["city"]), str(row["window_id"]), int(row["query_year"])) for row in rows}
    for city, window_id, start_md, end_md in specs:
        feature = domains[city]
        props = feature["properties"]
        domain = CityDomain(
            city=city,
            centroid_latitude=float(props["CENTLAT"]),
            centroid_longitude=float(props["CENTLON"]),
            bbox_wsen=geometry_bbox(feature["geometry"]),
        )
        for year in YEARS:
            if (city, window_id, year) in completed:
                continue
            start = f"{year}-{start_md}T00:00:00Z"
            end = f"{year}-{end_md}T23:59:59Z"
            progress(f"metadata {city} {window_id} {year}")
            result = search_data(
                short_name="ECO_L2T_LSTE",
                version="002",
                provider="LPCLOUD",
                bounding_box=domain.bbox_wsen,
                temporal=(start, end),
                count=-1,
            )
            normalized = normalize_granule_metadata(result, domain)
            if not normalized.empty:
                normalized["domain_intersects"] = normalized["footprint_json"].map(
                    lambda value: footprint_intersects_domain(value, feature["geometry"])
                )
                normalized = normalized.loc[normalized["domain_intersects"]].copy()
                normalized["window_id"] = window_id
                normalized["query_year"] = year
                normalized["domain_geoid"] = props["GEOID"]
                rows.extend(normalized.to_dict("records"))
            else:
                rows.append(
                    {
                        "city": city,
                        "window_id": window_id,
                        "query_year": year,
                        "query_empty_marker": True,
                        "domain_geoid": props["GEOID"],
                    }
                )
            pd.DataFrame(rows).to_csv(partial, index=False)
    frame = pd.DataFrame(rows)
    frame = frame.loc[frame.get("granule_id").notna()].copy()
    frame["acquisition_utc"] = pd.to_datetime(frame["acquisition_utc"], utc=True, format="mixed")
    if frame["acquisition_utc"].dt.year.min() != 2018 or frame["acquisition_utc"].dt.year.max() != 2025:
        raise ValueError("CMR response escaped the frozen 2018--2025 interval")
    frame = frame.drop_duplicates(["city", "window_id", "granule_id"]).sort_values(
        ["city", "window_id", "acquisition_utc", "granule_id"]
    )
    frame.to_csv(destination, index=False)
    partial.unlink(missing_ok=True)
    _write_json(
        destination.with_suffix(destination.suffix + ".provenance.json"),
        {
            "retrieved_utc": datetime.now(timezone.utc).isoformat(),
            "decision_id": DECISION_ID,
            "query_type": "public CMR metadata only",
            "short_name": "ECO_L2T_LSTE",
            "version": "002",
            "provider": "LPCLOUD",
            "years": list(YEARS),
            "specifications": [list(item) for item in specs],
            "row_count": len(frame),
            "output_sha256": sha256_file(destination),
            "record_2026_queried": False,
            "temperature_or_lst_opened": False,
        },
    )
    return frame.reset_index(drop=True)


def summarize_candidate_metadata(metadata: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = metadata.copy()
    work["orbit"] = pd.to_numeric(work["orbit"], errors="raise").astype(int)
    work["local_solar_time_hours"] = local_solar_time_hours(
        work["acquisition_utc"], work["centroid_longitude"]
    )
    work["local_solar_date"] = local_solar_dates(
        work["acquisition_utc"], work["centroid_longitude"]
    ).to_numpy()
    work["time_stratum"] = assign_time_stratum(work["local_solar_time_hours"])
    work["daytime_10_18"] = work["time_stratum"].notna()
    passes = (
        work.groupby(["city", "window_id", "orbit"], as_index=False)
        .agg(
            acquisition_utc=("acquisition_utc", "max"),
            local_solar_date=("local_solar_date", "max"),
            local_solar_time_hours=("local_solar_time_hours", "max"),
            time_stratum=("time_stratum", "last"),
            n_tiles=("granule_id", "nunique"),
            n_scenes=("scene", "nunique"),
        )
    )
    passes["year"] = pd.to_datetime(passes["acquisition_utc"], utc=True).dt.year
    counts = (
        passes.groupby(
            ["city", "window_id", "year", "time_stratum"],
            dropna=False,
            observed=True,
            as_index=False,
        )
        .size()
        .rename(columns={"size": "physical_metadata_ceiling_passes"})
    )
    return passes, counts


def audit_existing_angle_thresholds(
    geometry_csv: str | Path,
    catalogue_csv: str | Path,
    g2_pass_csv: str | Path,
    missing_csv: str | Path,
    phenology_windows: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    geometry = pd.read_csv(geometry_csv)
    catalogue = pd.read_csv(catalogue_csv, low_memory=False)
    g2 = pd.read_csv(g2_pass_csv)
    missing = pd.read_csv(missing_csv)
    keys = ["city", "orbit"]
    catalogue["orbit"] = pd.to_numeric(catalogue["orbit"], errors="raise").astype(int)
    geometry["orbit"] = pd.to_numeric(geometry["orbit"], errors="raise").astype(int)
    g2["orbit"] = pd.to_numeric(g2["orbit"], errors="raise").astype(int)
    meta = catalogue.drop_duplicates(keys)[keys + ["time_stratum", "local_solar_time_hours", "month"]]
    geometry = geometry.merge(meta, on=keys, how="left", validate="one_to_one")
    coverage = geometry["l1b_geometry_coverage_fraction"].ge(0.95)
    base_cols = keys + [
        "vpd_kpa_at_acquisition",
        "antecedent_precipitation_30d_mm",
        "antecedent_precipitation_30d_wetness_percentile",
        "demand_percentile",
        "clear_domain_fraction",
    ]
    g2_small = g2[base_cols].drop_duplicates(keys)
    missing_by_city = missing.groupby("city").size().to_dict()
    phenology = phenology_windows.loc[phenology_windows["window_id"].eq("jun_sep")].set_index("city")
    detail_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    eligibility_rows: list[dict[str, Any]] = []
    for threshold in ANGLE_THRESHOLDS:
        selected = geometry.loc[
            coverage & geometry["l1b_view_zenith_abs_p95_deg"].le(threshold)
        ].copy()
        selected = selected.merge(g2_small, on=keys, how="left", validate="one_to_one")
        selected["threshold_deg"] = threshold
        selected["quality_and_exact_weather_complete"] = selected["vpd_kpa_at_acquisition"].notna()
        selected["view_azimuth_complete"] = False
        selected["relative_azimuth_complete"] = False
        selected["high_demand"] = selected["demand_percentile"].ge(2 / 3)
        selected["wet"] = selected["antecedent_precipitation_30d_wetness_percentile"].ge(2 / 3)
        selected["dry"] = selected["antecedent_precipitation_30d_wetness_percentile"].le(1 / 3)
        detail_rows.extend(selected.to_dict("records"))
        for city in sorted(geometry["city"].unique()):
            group = selected.loc[selected["city"].eq(city)].copy()
            resolved = group.loc[group["quality_and_exact_weather_complete"]]
            morning = int(group["time_stratum"].eq("10-12").sum())
            afternoon = int(group["time_stratum"].eq("16-18").sum())
            hd_wet = resolved.loc[resolved["high_demand"] & resolved["wet"]]
            hd_dry = resolved.loc[resolved["high_demand"] & resolved["dry"]]
            if len(hd_wet) and len(hd_dry):
                overlap = max(
                    0.0,
                    min(float(hd_wet["vpd_kpa_at_acquisition"].max()), float(hd_dry["vpd_kpa_at_acquisition"].max()))
                    - max(float(hd_wet["vpd_kpa_at_acquisition"].min()), float(hd_dry["vpd_kpa_at_acquisition"].min())),
                )
            else:
                overlap = 0.0
            phenology_pass = bool(phenology.loc[city, "all_months_stable_leaf_on"]) if city in phenology.index else False
            unresolved_archive = int(missing_by_city.get(city, 0))
            eligibility = {
                "phenology_pass": phenology_pass,
                "fully_resolved_observation_accounting": unresolved_archive == 0,
                "four_year_minimum": int(group["year"].nunique()) >= 4 if len(group) else False,
                "morning_minimum": morning >= 3,
                "afternoon_minimum": afternoon >= 3,
                "high_demand_wet_minimum": len(hd_wet) >= 2,
                "high_demand_dry_minimum": len(hd_dry) >= 2,
                "absolute_vpd_overlap_positive": overlap > 0,
                "azimuth_complete": False,
                "quality_weather_complete_for_all_selected": bool(len(group) and group["quality_and_exact_weather_complete"].all()),
            }
            eligible = all(eligibility.values())
            eligibility_rows.append(
                {
                    "threshold_deg": threshold,
                    "city": city,
                    "window_id": "jun_sep",
                    "physical_passes": len(group),
                    "clear_domain_pass_equivalents": float(resolved["clear_domain_fraction"].sum()),
                    "years_with_passes": int(group["year"].nunique()),
                    "morning_10_12_passes": morning,
                    "late_afternoon_16_18_passes": afternoon,
                    "high_demand_wet_passes": len(hd_wet),
                    "high_demand_dry_passes": len(hd_dry),
                    "absolute_vpd_overlap_kpa": overlap,
                    "archive_unresolved_candidates": unresolved_archive,
                    **eligibility,
                    "eligible_city_window": eligible,
                }
            )
            for stratum, stratum_group in group.groupby("time_stratum", dropna=False):
                resolved_stratum = stratum_group.loc[stratum_group["quality_and_exact_weather_complete"]]
                summary_rows.append(
                    {
                        "threshold_deg": threshold,
                        "city": city,
                        "window_id": "jun_sep",
                        "time_stratum": str(stratum) if pd.notna(stratum) else "outside_10_18",
                        "physical_passes": len(stratum_group),
                        "quality_and_exact_weather_complete_passes": len(resolved_stratum),
                        "unresolved_quality_or_weather_passes": len(stratum_group) - len(resolved_stratum),
                        "clear_domain_pass_equivalents": float(resolved_stratum["clear_domain_fraction"].sum()),
                        "view_zenith_p95_median_deg": float(stratum_group["l1b_view_zenith_abs_p95_deg"].median()),
                        "acquisition_vpd_median_kpa": float(resolved_stratum["vpd_kpa_at_acquisition"].median()) if len(resolved_stratum) else math.nan,
                        "precip30_median_mm": float(resolved_stratum["antecedent_precipitation_30d_mm"].median()) if len(resolved_stratum) else math.nan,
                        "view_azimuth_status": "UNRESOLVED_NOT_MAPPED",
                        "relative_azimuth_status": "UNRESOLVED_NOT_MAPPED",
                    }
                )
    return pd.DataFrame(detail_rows), pd.DataFrame(summary_rows), pd.DataFrame(eligibility_rows)


def circular_mean_concentration(values_deg: Iterable[float]) -> tuple[float, float]:
    """Return circular mean in [0, 360) and mean-resultant concentration."""

    values = np.asarray(list(values_deg), dtype=float)
    values = values[np.isfinite(values)]
    if not len(values):
        return math.nan, math.nan
    radians = np.deg2rad(np.mod(values, 360.0))
    sine = float(np.mean(np.sin(radians)))
    cosine = float(np.mean(np.cos(radians)))
    mean = float(np.mod(np.rad2deg(math.atan2(sine, cosine)), 360.0))
    return mean, float(math.hypot(sine, cosine))


def relative_azimuth_deg(view_azimuth: Iterable[float], solar_azimuth: Iterable[float]) -> np.ndarray:
    """Smallest absolute circular sun-sensor difference in [0, 180]."""

    view = np.asarray(list(view_azimuth), dtype=float)
    solar = np.asarray(list(solar_azimuth), dtype=float)
    if view.shape != solar.shape:
        raise ValueError("View and solar azimuth arrays must align")
    difference = np.abs((view - solar + 180.0) % 360.0 - 180.0)
    difference[~(np.isfinite(view) & np.isfinite(solar))] = np.nan
    return difference


def normalized_shannon_entropy(counts: Iterable[float]) -> float:
    values = np.asarray(list(counts), dtype=float)
    values = values[np.isfinite(values) & (values > 0)]
    if not len(values):
        return math.nan
    if len(values) == 1:
        return 0.0
    probabilities = values / values.sum()
    return float(-(probabilities * np.log(probabilities)).sum() / np.log(len(values)))


def _shared_histogram_edges(values: np.ndarray) -> np.ndarray:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return np.array([], dtype=float)
    low, high = float(np.min(finite)), float(np.max(finite))
    if low == high:
        return np.array([low - 0.5, high + 0.5], dtype=float)
    q1, q3 = np.quantile(finite, [0.25, 0.75])
    width = 2.0 * float(q3 - q1) / np.cbrt(len(finite))
    bins = int(math.ceil((high - low) / width)) if width > 0 else 10
    bins = min(20, max(5, bins))
    return np.linspace(low, high, bins + 1)


def histogram_overlap_coefficient(left: Iterable[float], right: Iterable[float]) -> float:
    a = np.asarray(list(left), dtype=float)
    b = np.asarray(list(right), dtype=float)
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]
    if not len(a) or not len(b):
        return math.nan
    edges = _shared_histogram_edges(np.concatenate([a, b]))
    left_hist = np.histogram(a, bins=edges)[0].astype(float)
    right_hist = np.histogram(b, bins=edges)[0].astype(float)
    left_hist /= left_hist.sum()
    right_hist /= right_hist.sum()
    return float(np.minimum(left_hist, right_hist).sum())


def _positive_range_overlap(left: pd.Series, right: pd.Series) -> float:
    a = pd.to_numeric(left, errors="coerce").dropna()
    b = pd.to_numeric(right, errors="coerce").dropna()
    if a.empty or b.empty:
        return math.nan
    return float(max(0.0, min(a.max(), b.max()) - max(a.min(), b.min())))


def _strict_true(value: Any) -> bool:
    """Accept only actual boolean true values for fail-closed gate evidence."""

    return isinstance(value, (bool, np.bool_)) and bool(value)


def _all_strict_true(values: Iterable[Any]) -> bool:
    items = list(values)
    return bool(items) and all(_strict_true(value) for value in items)


def _city_window_set(frame: pd.DataFrame) -> frozenset[tuple[str, str]]:
    return frozenset(
        (str(city), str(window_id))
        for city, window_id in frame[["city", "window_id"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )


def _validate_physical_pass_ids(
    frame: pd.DataFrame,
    *,
    label: str,
    threshold_scoped: bool,
) -> None:
    if "physical_pass_id" not in frame:
        raise ValueError(f"{label} missing required physical_pass_id")
    identifiers = frame["physical_pass_id"]
    if identifiers.isna().any() or identifiers.astype(str).str.strip().eq("").any():
        raise ValueError(f"{label} contains a missing physical_pass_id")
    keys = ["threshold_deg", "physical_pass_id"] if threshold_scoped else ["physical_pass_id"]
    if frame.duplicated(keys).any():
        raise ValueError(f"{label} contains duplicate physical pass identities")
    if threshold_scoped:
        identity_membership = frame.groupby("physical_pass_id")[["city", "window_id"]].nunique()
        if identity_membership.gt(1).any().any():
            raise ValueError(f"{label} reassigns a physical pass identity across city-windows")


def _validate_threshold_nesting(frame: pd.DataFrame) -> None:
    thresholds = set(pd.to_numeric(frame["threshold_deg"], errors="raise").astype(int))
    unexpected = thresholds.difference(PRIMARY_ANGLE_THRESHOLDS)
    if unexpected:
        raise ValueError(
            f"Physical-pass evidence contains non-primary thresholds {sorted(unexpected)}"
        )
    prior_ids: set[str] = set()
    for threshold in PRIMARY_ANGLE_THRESHOLDS:
        current_ids = set(
            frame.loc[frame["threshold_deg"].eq(threshold), "physical_pass_id"].astype(str)
        )
        if not prior_ids.issubset(current_ids):
            raise ValueError("Archive observed-pass thresholds are not nested")
        prior_ids = current_ids


def _physical_pass_set_sha256(values: Iterable[Any]) -> str:
    identifiers = sorted(str(value) for value in values)
    payload = json.dumps(identifiers, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_balance_diagnostics(
    pass_detail: pd.DataFrame,
    *,
    thresholds: Sequence[int] = PRIMARY_ANGLE_THRESHOLDS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute D0067 diagnostics, including explicit rows for empty thresholds.

    ``thresholds`` is the caller's explicit threshold ledger.  It defaults to
    every primary threshold so a zero-pass threshold is recorded as incomplete
    rather than silently omitted.
    """

    required = {
        "threshold_deg",
        "physical_pass_id",
        "city",
        "window_id",
        "time_stratum",
        "demand_level",
        "wetness_level",
        "vpd_kpa_at_acquisition",
        "antecedent_precipitation_30d_mm",
        "l1b_geometry_coverage_fraction",
        "l1b_view_zenith_abs_p95_deg",
        "view_azimuth_circular_mean_deg",
        "solar_azimuth_circular_mean_deg",
        "relative_azimuth_median_deg",
        "geometry_azimuth_complete",
        "cloud_complete",
        "exact_weather_complete",
        "day_of_window",
    }
    missing = required.difference(pass_detail.columns)
    if missing:
        raise ValueError(f"Balance diagnostics missing columns {sorted(missing)}")
    threshold_ledger = tuple(int(value) for value in thresholds)
    if threshold_ledger != tuple(PRIMARY_ANGLE_THRESHOLDS):
        raise ValueError("Balance diagnostics threshold ledger must be 10, 15, 20, 25")
    _validate_physical_pass_ids(
        pass_detail,
        label="Balance diagnostics",
        threshold_scoped=True,
    )
    if not _city_window_set(pass_detail).issubset(PRIMARY_CITY_WINDOWS):
        raise ValueError("Balance diagnostics include an out-of-scope city-window")
    _validate_threshold_nesting(pass_detail)
    threshold_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    variables = {
        "acquisition_vpd": "vpd_kpa_at_acquisition",
        "precipitation_30d": "antecedent_precipitation_30d_mm",
        "view_zenith": "l1b_view_zenith_abs_p95_deg",
        "relative_azimuth": "relative_azimuth_median_deg",
    }
    required_weather_ranges = {
        "acquisition_vpd": "vpd_kpa_at_acquisition",
        "air_temperature": "air_temperature_k_at_acquisition",
        "wind_speed": "wind_speed_m_s_at_acquisition",
    }
    missing_weather = set(required_weather_ranges.values()).difference(pass_detail.columns)
    if missing_weather:
        raise ValueError(
            f"Balance diagnostics missing frozen exact-weather columns {sorted(missing_weather)}"
        )
    weather_ranges = required_weather_ranges
    finite_columns = (
        "l1b_geometry_coverage_fraction",
        "l1b_view_zenith_abs_p95_deg",
        "view_azimuth_circular_mean_deg",
        "solar_azimuth_circular_mean_deg",
        "relative_azimuth_median_deg",
        *required_weather_ranges.values(),
    )
    finite_evidence = np.ones(len(pass_detail), dtype=bool)
    for column in finite_columns:
        finite_evidence &= np.isfinite(
            pd.to_numeric(pass_detail[column], errors="coerce").to_numpy(dtype=float)
        )
    strict_flags = np.ones(len(pass_detail), dtype=bool)
    for column in ("geometry_azimuth_complete", "cloud_complete", "exact_weather_complete"):
        strict_flags &= pass_detail[column].map(_strict_true).to_numpy(dtype=bool)
    coverage = pd.to_numeric(
        pass_detail["l1b_geometry_coverage_fraction"], errors="coerce"
    ).to_numpy(dtype=float)
    zenith = pd.to_numeric(
        pass_detail["l1b_view_zenith_abs_p95_deg"], errors="coerce"
    ).to_numpy(dtype=float)
    row_threshold = pd.to_numeric(pass_detail["threshold_deg"], errors="raise").to_numpy(
        dtype=float
    )
    qualifying = finite_evidence & strict_flags & (coverage >= 0.95) & (zenith <= row_threshold)
    if not qualifying.all():
        failed_ids = sorted(
            pass_detail.loc[~qualifying, "physical_pass_id"].astype(str).unique().tolist()
        )
        raise ValueError(
            "Balance diagnostics contain nonqualifying physical passes: "
            + ", ".join(failed_ids[:10])
        )
    for threshold in threshold_ledger:
        group = pass_detail.loc[pass_detail["threshold_deg"].eq(threshold)].copy()
        city_window_membership = sorted(
            f"{city}/{window_id}"
            for city, window_id in group[["city", "window_id"]]
            .drop_duplicates()
            .itertuples(index=False, name=None)
        )
        exact_primary_membership = _city_window_set(group) == PRIMARY_CITY_WINDOWS
        counts = group.groupby("city").size()
        maximum_share = float(counts.max() / counts.sum()) if len(counts) else math.nan
        cells = group.groupby(
            ["city", "time_stratum", "demand_level", "wetness_level"],
            dropna=False,
        ).size()
        pair_group = list(group.groupby(["city", "window_id"], sort=True))
        for left_index, (left_key, left) in enumerate(pair_group):
            for right_key, right in pair_group[left_index + 1 :]:
                row: dict[str, Any] = {
                    "threshold_deg": int(threshold),
                    "left_city_window": f"{left_key[0]}/{left_key[1]}",
                    "right_city_window": f"{right_key[0]}/{right_key[1]}",
                }
                for label, column in variables.items():
                    row[f"{label}_histogram_overlap"] = histogram_overlap_coefficient(
                        left[column], right[column]
                    )
                for label, column in weather_ranges.items():
                    row[f"{label}_observed_range_overlap"] = (
                        _positive_range_overlap(left[column], right[column])
                        if column in group.columns
                        else math.nan
                    )
                pair_rows.append(row)
        threshold_pairs = [row for row in pair_rows if row["threshold_deg"] == int(threshold)]
        overlap_values = [
            row[f"{label}_histogram_overlap"]
            for row in threshold_pairs
            for label in variables
        ]
        weather_values = [
            row[f"{label}_observed_range_overlap"]
            for row in threshold_pairs
            for label in weather_ranges
        ]
        city_window_support = []
        for (city, window_id), support in group.groupby(["city", "window_id"], sort=True):
            am_count = int(support["time_stratum"].eq("10-12").sum())
            pm_count = int(support["time_stratum"].eq("16-18").sum())
            high = support.loc[support["demand_level"].eq("high")]
            wet = high.loc[high["wetness_level"].eq("wet")]
            dry = high.loc[high["wetness_level"].eq("dry")]
            vpd_overlap = _positive_range_overlap(
                wet["vpd_kpa_at_acquisition"], dry["vpd_kpa_at_acquisition"]
            )
            season_overlap = _positive_range_overlap(
                wet["day_of_window"], dry["day_of_window"]
            )
            city_window_support.append(
                {
                    "city": city,
                    "window_id": window_id,
                    "am_count": am_count,
                    "pm_count": pm_count,
                    "high_demand_wet_count": int(len(wet)),
                    "high_demand_dry_count": int(len(dry)),
                    "high_demand_wet_dry_vpd_range_overlap": vpd_overlap,
                    "high_demand_wet_dry_day_of_window_range_overlap": season_overlap,
                    "am_pm_support_pass": am_count >= 3 and pm_count >= 3,
                    "wet_dry_support_pass": len(wet) >= 2 and len(dry) >= 2,
                    "within_city_vpd_overlap_pass": bool(np.isfinite(vpd_overlap) and vpd_overlap > 0),
                    "within_city_season_overlap_pass": bool(
                        np.isfinite(season_overlap) and season_overlap > 0
                    ),
                }
            )
        entropy = normalized_shannon_entropy(cells)
        geometry_columns = (
            "l1b_view_zenith_abs_p95_deg",
            "view_azimuth_circular_mean_deg",
            "relative_azimuth_median_deg",
        )
        geometry_complete = bool(
            len(group)
            and all(
                np.isfinite(pd.to_numeric(group[column], errors="coerce").to_numpy(float)).all()
                for column in geometry_columns
            )
        )
        threshold_rows.append(
            {
                "threshold_deg": int(threshold),
                "physical_passes": int(len(group)),
                "qualifying_pass_count": int(group["physical_pass_id"].nunique()),
                "qualifying_pass_set_sha256": _physical_pass_set_sha256(
                    group["physical_pass_id"]
                ),
                "unique_cities": int(group["city"].nunique()),
                "city_window_membership": json.dumps(city_window_membership),
                "exact_primary_city_window_membership": exact_primary_membership,
                "maximum_city_share": maximum_share,
                "city_share_cap_pass": bool(len(group) and maximum_share <= 0.40),
                "normalized_shannon_entropy": entropy,
                "entropy_diagnostic_complete": bool(np.isfinite(entropy)),
                "pairwise_city_window_comparisons": len(threshold_pairs),
                "histogram_diagnostics_complete": bool(
                    exact_primary_membership
                    and threshold_pairs
                    and np.isfinite(np.asarray(overlap_values, dtype=float)).all()
                ),
                "geometry_diagnostics_complete": geometry_complete,
                "am_pm_support_diagnostics_complete": bool(
                    exact_primary_membership
                    and city_window_support
                    and all(item["am_pm_support_pass"] for item in city_window_support)
                ),
                "wet_dry_support_diagnostics_complete": bool(
                    exact_primary_membership
                    and city_window_support
                    and all(item["wet_dry_support_pass"] for item in city_window_support)
                ),
                "within_city_vpd_overlap_complete_and_positive": bool(
                    exact_primary_membership
                    and city_window_support
                    and all(item["within_city_vpd_overlap_pass"] for item in city_window_support)
                ),
                "weather_overlap_diagnostics_complete": bool(
                    exact_primary_membership
                    and threshold_pairs
                    and np.isfinite(np.asarray(weather_values, dtype=float)).all()
                ),
                "weather_overlap_fields_reported": ",".join(weather_ranges),
                "wind_speed_overlap_status": "REPORTED",
                "season_overlap_diagnostics_complete": bool(
                    exact_primary_membership
                    and city_window_support
                    and all(
                        item["within_city_season_overlap_pass"]
                        for item in city_window_support
                    )
                ),
                "city_window_support": city_window_support,
            }
        )
    return pd.DataFrame(threshold_rows), pd.DataFrame(pair_rows)


def build_archive_bound_diagnostics(
    observed_passes: pd.DataFrame,
    resolved_unavailable_passes: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate D0069 lower/upper count support without inventing geometry or weather."""

    required_observed = {
        "threshold_deg",
        "physical_pass_id",
        "city",
        "window_id",
        "year",
        "time_stratum",
        "demand_level",
        "wetness_level",
    }
    required_missing = {
        "physical_pass_id",
        "city",
        "window_id",
        "year",
        "time_stratum",
        "demand_level",
        "wetness_level",
        "pass_recheck_classification",
    }
    missing_observed = required_observed.difference(observed_passes.columns)
    missing_unavailable = required_missing.difference(resolved_unavailable_passes.columns)
    if missing_observed:
        raise ValueError(f"Archive bounds missing observed columns {sorted(missing_observed)}")
    if missing_unavailable:
        raise ValueError(f"Archive bounds missing unavailable columns {sorted(missing_unavailable)}")
    if not resolved_unavailable_passes["pass_recheck_classification"].eq(
        "RESOLVED_UNAVAILABLE"
    ).all():
        raise ValueError("Archive bounds include a pass not classified RESOLVED_UNAVAILABLE")
    _validate_physical_pass_ids(
        observed_passes,
        label="Archive observed passes",
        threshold_scoped=True,
    )
    _validate_physical_pass_ids(
        resolved_unavailable_passes,
        label="Archive unavailable passes",
        threshold_scoped=False,
    )
    if not _city_window_set(observed_passes).issubset(PRIMARY_CITY_WINDOWS):
        raise ValueError("Archive observed passes include a non-primary city-window")
    if not _city_window_set(resolved_unavailable_passes).issubset(PRIMARY_CITY_WINDOWS):
        raise ValueError("Archive unavailable passes include a non-primary city-window")
    observed_ids = set(observed_passes["physical_pass_id"].astype(str))
    unavailable_ids = set(resolved_unavailable_passes["physical_pass_id"].astype(str))
    if observed_ids.intersection(unavailable_ids):
        raise ValueError("A physical pass cannot be both observed and RESOLVED_UNAVAILABLE")
    _validate_threshold_nesting(observed_passes)

    def summarize(frame: pd.DataFrame) -> dict[str, Any]:
        city_counts = frame.groupby("city").size()
        max_share = float(city_counts.max() / city_counts.sum()) if len(city_counts) else math.nan
        support_rows = []
        city_year_counts = [
            {
                "city": str(city),
                "window_id": str(window_id),
                "year": int(year),
                "qualifying_passes": int(len(group)),
            }
            for (city, window_id, year), group in frame.groupby(
                ["city", "window_id", "year"], sort=True
            )
        ]
        for (city, window_id), group in frame.groupby(["city", "window_id"], sort=True):
            am = int(group["time_stratum"].eq("10-12").sum())
            pm = int(group["time_stratum"].eq("16-18").sum())
            high = group.loc[group["demand_level"].eq("high")]
            wet = int(high["wetness_level"].eq("wet").sum())
            dry = int(high["wetness_level"].eq("dry").sum())
            support_rows.append(
                {
                    "city": city,
                    "window_id": window_id,
                    "qualifying_passes": int(len(group)),
                    "qualifying_years": int(group["year"].nunique()),
                    "am_count": am,
                    "pm_count": pm,
                    "high_demand_wet_count": wet,
                    "high_demand_dry_count": dry,
                    "year_support_pass": group["year"].nunique() >= 4,
                    "am_pm_support_pass": am >= 3 and pm >= 3,
                    "wet_dry_support_pass": wet >= 2 and dry >= 2,
                }
            )
        required_support_pass = bool(
            support_rows
            and all(
                item["year_support_pass"]
                and item["am_pm_support_pass"]
                and item["wet_dry_support_pass"]
                for item in support_rows
            )
        )
        return {
            "physical_passes": int(len(frame)),
            "unique_cities": int(frame["city"].nunique()),
            "four_city_minimum_pass": int(frame["city"].nunique()) >= 4,
            "maximum_city_share": max_share,
            "city_share_cap_pass": bool(len(frame) and max_share <= 0.40),
            "required_count_support_pass": required_support_pass,
            "city_window_support": support_rows,
            "city_window_conclusions": {
                f"{item['city']}/{item['window_id']}": {
                    "year_support_pass": item["year_support_pass"],
                    "am_pm_support_pass": item["am_pm_support_pass"],
                    "wet_dry_support_pass": item["wet_dry_support_pass"],
                }
                for item in support_rows
            },
            "city_year_counts": city_year_counts,
        }

    upper_additions = resolved_unavailable_passes[list(required_missing - {"pass_recheck_classification"})].copy()
    rows: list[dict[str, Any]] = []
    for threshold in PRIMARY_ANGLE_THRESHOLDS:
        lower_frame = observed_passes.loc[observed_passes["threshold_deg"].eq(threshold)].copy()
        upper_frame = pd.concat([lower_frame, upper_additions], ignore_index=True, sort=False)
        lower = summarize(lower_frame)
        upper = summarize(upper_frame)
        aggregate_conclusions = (
            "four_city_minimum_pass",
            "city_share_cap_pass",
            "required_count_support_pass",
        )
        conclusion_invariant = bool(
            all(lower[key] == upper[key] for key in aggregate_conclusions)
            and lower["city_window_conclusions"] == upper["city_window_conclusions"]
        )
        rows.append(
            {
                "threshold_deg": int(threshold),
                **{f"lower_{key}": value for key, value in lower.items()},
                **{f"upper_{key}": value for key, value in upper.items()},
                "archive_count_conclusions_invariant": conclusion_invariant,
            }
        )
    result = pd.DataFrame(rows)
    for bound in ("lower", "upper"):
        result[f"{bound}_count_eligible"] = (
            result[f"{bound}_four_city_minimum_pass"].fillna(False)
            & result[f"{bound}_city_share_cap_pass"].fillna(False)
            & result[f"{bound}_required_count_support_pass"].fillna(False)
        )
    def first_eligible(column: str) -> int | None:
        passing = result.loc[result[column], "threshold_deg"]
        return int(passing.min()) if len(passing) else None

    lower_first = first_eligible("lower_count_eligible")
    upper_first = first_eligible("upper_count_eligible")
    threshold_invariant = lower_first == upper_first
    result["lower_first_count_eligible_threshold_deg"] = lower_first
    result["upper_first_count_eligible_threshold_deg"] = upper_first
    result["archive_threshold_choice_invariant"] = threshold_invariant
    result["archive_bounds_invariant"] = (
        result["archive_count_conclusions_invariant"]
        & result["archive_threshold_choice_invariant"]
    )
    return result


def selection_result(
    eligibility: pd.DataFrame,
    balance: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Select the smallest fully eligible D0067 primary threshold, fail closed."""

    threshold_status: dict[str, Any] = {}
    selected_threshold: int | None = None
    selected_rows = pd.DataFrame()
    for threshold in PRIMARY_ANGLE_THRESHOLDS:
        group = eligibility.loc[eligibility["threshold_deg"].eq(threshold)]
        group_membership = (
            _city_window_set(group)
            if {"city", "window_id"}.issubset(group.columns)
            else frozenset()
        )
        exact_group_membership = bool(
            group_membership == PRIMARY_CITY_WINDOWS
            and not group.duplicated(["city", "window_id"]).any()
        )
        if "phenology_auto_eligible" not in group or not exact_group_membership:
            candidates = group.iloc[0:0].copy()
        else:
            phenology_mask = group["phenology_auto_eligible"].map(_strict_true)
            candidates = group.loc[phenology_mask].copy()
        unique_cities = int(candidates["city"].nunique()) if "city" in candidates else 0
        includes_denver = bool(
            "city" in candidates and candidates["city"].eq("denver_aurora").any()
        )
        all_eligible = bool(
            len(candidates)
            and "eligible_city_window" in candidates
            and _all_strict_true(candidates["eligible_city_window"])
        )
        bound_invariant = bool(
            len(candidates)
            and "archive_bounds_invariant" in candidates
            and _all_strict_true(candidates["archive_bounds_invariant"])
        )
        candidate_pass_set_bound = False
        candidate_pass_count: int | None = None
        candidate_pass_hash: str | None = None
        if {
            "qualifying_pass_count",
            "qualifying_pass_set_sha256",
        }.issubset(candidates.columns) and len(candidates):
            counts = pd.to_numeric(
                candidates["qualifying_pass_count"], errors="coerce"
            ).dropna().unique()
            hashes = candidates["qualifying_pass_set_sha256"].dropna().astype(str).unique()
            if len(counts) == 1 and len(hashes) == 1:
                candidate_pass_count = int(counts[0])
                candidate_pass_hash = str(hashes[0])
        balance_row = pd.DataFrame()
        if balance is not None and "threshold_deg" in balance:
            balance_row = balance.loc[balance["threshold_deg"].eq(threshold)]
        candidate_membership = sorted(
            f"{city}/{window_id}"
            for city, window_id in candidates[["city", "window_id"]]
            .drop_duplicates()
            .itertuples(index=False, name=None)
        ) if {"city", "window_id"}.issubset(candidates.columns) else []
        balance_membership_matches = False
        if len(balance_row) == 1:
            try:
                reported_membership = json.loads(
                    str(balance_row.iloc[0].get("city_window_membership", ""))
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                reported_membership = []
            balance_membership_matches = bool(
                sorted(map(str, reported_membership)) == candidate_membership
                and int(balance_row.iloc[0].get("unique_cities", -1)) == unique_cities
            )
            try:
                balance_pass_count = int(balance_row.iloc[0]["qualifying_pass_count"])
                balance_pass_hash = str(
                    balance_row.iloc[0]["qualifying_pass_set_sha256"]
                )
            except (KeyError, TypeError, ValueError, OverflowError):
                balance_pass_count = -1
                balance_pass_hash = ""
            candidate_pass_set_bound = bool(
                candidate_pass_count is not None
                and candidate_pass_hash is not None
                and candidate_pass_count == balance_pass_count
                and candidate_pass_hash == balance_pass_hash
            )
        balance_complete = bool(
            len(balance_row) == 1
            and balance_membership_matches
            and candidate_pass_set_bound
            and _strict_true(balance_row.iloc[0].get("histogram_diagnostics_complete", False))
            and _strict_true(balance_row.iloc[0].get("entropy_diagnostic_complete", False))
            and _strict_true(balance_row.iloc[0].get("geometry_diagnostics_complete", False))
            and _strict_true(balance_row.iloc[0].get("city_share_cap_pass", False))
            and _strict_true(balance_row.iloc[0].get("am_pm_support_diagnostics_complete", False))
            and _strict_true(balance_row.iloc[0].get("wet_dry_support_diagnostics_complete", False))
            and _strict_true(balance_row.iloc[0].get("within_city_vpd_overlap_complete_and_positive", False))
            and _strict_true(balance_row.iloc[0].get("season_overlap_diagnostics_complete", False))
            and _strict_true(balance_row.iloc[0].get("weather_overlap_diagnostics_complete", False))
            and _strict_true(balance_row.iloc[0].get("archive_bounds_invariant", False))
        )
        passes = bool(
            exact_group_membership
            and _city_window_set(candidates) == PRIMARY_CITY_WINDOWS
            and unique_cities == 4
            and includes_denver
            and all_eligible
            and bound_invariant
            and balance_complete
        )
        threshold_status[str(threshold)] = {
            "eligible_city_windows": int(
                group.get("eligible_city_window", pd.Series(dtype=bool))
                .map(_strict_true)
                .sum()
            ),
            "audited_city_windows": len(group),
            "candidate_primary_city_windows": len(candidates),
            "candidate_primary_unique_cities": unique_cities,
            "exact_d0069_city_window_membership": exact_group_membership,
            "four_city_minimum_pass": unique_cities == 4,
            "denver_included": includes_denver,
            "all_candidate_city_windows_eligible": all_eligible,
            "archive_bounds_invariant": bound_invariant,
            "balance_diagnostics_complete_and_pass": balance_complete,
            "balance_membership_matches_candidates": balance_membership_matches,
            "eligibility_pass_set_matches_balance": candidate_pass_set_bound,
            "threshold_eligible": passes,
        }
        if selected_threshold is None and passes:
            selected_threshold = threshold
            selected_rows = candidates.copy()
    selected = selected_threshold is not None
    if selected:
        city_set: str | list[str] = sorted(selected_rows["city"].unique().tolist())
        window_set: str | list[dict[str, str]] = sorted(
            selected_rows[["city", "window_id"]].drop_duplicates().to_dict("records"),
            key=lambda item: (item["city"], item["window_id"]),
        )
        reason = "Smallest threshold satisfying every frozen eligibility and bound rule."
    else:
        city_set = "UNSELECTED"
        window_set = "UNSELECTED"
        reason = (
            "No primary threshold has at least four nonexploratory cities including Denver "
            "with complete eligibility, invariant inaccessible-pass bounds, and passing balance diagnostics."
        )
    return {
        "gate_status": "SELECTED_AWAITING_HUMAN_APPROVAL" if selected else "REVISE_REQUIRED",
        "sampling_design_selected": selected,
        "primary_city_set": city_set,
        "primary_season_windows": window_set,
        "primary_view_zenith_threshold_deg": selected_threshold,
        "reason": reason,
        "threshold_status": threshold_status,
        "g3a_authorized": False,
        "gate4_authorized": False,
        "temperature_or_lst_opened": False,
        "record_2026_queried": False,
    }


__all__ = [
    "ANGLE_THRESHOLDS",
    "CANDIDATE_CITY_META",
    "DECISION_ID",
    "add_antecedent_predictors",
    "audit_existing_angle_thresholds",
    "candidate_day_support",
    "build_balance_diagnostics",
    "build_archive_bound_diagnostics",
    "circular_mean_concentration",
    "fetch_candidate_domains",
    "fetch_candidate_metadata",
    "fetch_candidate_weather",
    "fetch_modis_phenology",
    "histogram_overlap_coefficient",
    "load_candidate_domains",
    "selection_result",
    "sha256_file",
    "summarize_candidate_metadata",
    "summarize_leaf_on",
    "summarize_leaf_on_metric",
    "summarize_phenology_sensitivities",
    "normalized_shannon_entropy",
    "relative_azimuth_deg",
]
