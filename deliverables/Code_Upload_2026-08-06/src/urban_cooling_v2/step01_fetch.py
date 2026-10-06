"""Live adapters for Step 1 weather and early-afternoon clear-sky screening."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from .config import StudyConfig
from .domains import load_domain_features


GRIDMET_COLLECTION = "IDAHO_EPSCOR/GRIDMET"
GRIDMET_BANDS = ("pr", "eto", "vpd", "tmmx")
ERA5_COLLECTION = "ECMWF/ERA5/HOURLY"
ERA5_CLOUD_BAND = "total_cloud_cover"


def target_utc_hour_for_local_solar(longitude_deg: float, target_local_hour: float = 14.0) -> int:
    """Nearest UTC hour to a target mean local-solar clock hour.

    The equation-of-time correction is small relative to ERA5's hourly cadence and
    is deliberately not used to change the selected hour day by day.  The actual
    solar-time conversion is recorded downstream for satellite acquisitions.
    """
    return int(np.floor((target_local_hour - longitude_deg / 15.0) % 24 + 0.5)) % 24


def _feature_collection_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for feature in payload.get("features", []):
        props = dict(feature.get("properties", {}))
        if props:
            rows.append(props)
    return rows


def _reduce_collection(
    ee: Any,
    collection: Any,
    geometry: Any,
    *,
    city: str,
    bands: tuple[str, ...],
    scale: float,
) -> list[dict[str, Any]]:
    reducer = ee.Reducer.mean()

    def reduce_image(image: Any) -> Any:
        means = image.select(list(bands)).reduceRegion(
            reducer=reducer,
            geometry=geometry,
            scale=scale,
            maxPixels=1_000_000_000,
            bestEffort=True,
            tileScale=16,
        )
        return ee.Feature(None, means).set(
            {"city": city, "date": image.date().format("YYYY-MM-dd")}
        )

    result = ee.FeatureCollection(collection.map(reduce_image)).getInfo()
    return _feature_collection_rows(result)


def _write_provenance(path: Path, payload: dict[str, Any]) -> Path:
    payload = dict(payload)
    payload["retrieved_utc"] = datetime.now(timezone.utc).isoformat()
    payload["output_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    sidecar = path.with_suffix(path.suffix + ".provenance.json")
    sidecar.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return sidecar


def _domain_geometry_manifest(
    features: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Record the source and repaired geometry identities used by Earth Engine."""

    manifest: dict[str, dict[str, Any]] = {}
    for city, feature in sorted(features.items()):
        properties = feature.get("properties", {})
        source_hash = properties.get("source_geometry_sha256")
        analysis_hash = properties.get("analysis_geometry_sha256")
        if not source_hash or not analysis_hash:
            raise ValueError(f"{city}: domain geometry provenance is incomplete")
        manifest[str(city)] = {
            "source_geometry_sha256": str(source_hash),
            "analysis_geometry_sha256": str(analysis_hash),
            "topology_repair_applied": bool(
                properties.get("topology_repair_applied", False)
            ),
        }
    return manifest


def fetch_gee_conditions(
    config: StudyConfig,
    domains_geojson: str | Path,
    output_csv: str | Path,
    *,
    ee_module: Any | None = None,
    project: str | None = None,
    years: Iterable[int] | None = None,
    progress: Callable[[str], None] = print,
    resume: bool = True,
) -> pd.DataFrame:
    """Fetch spatial city means for gridMET plus ERA5 14:00-solar cloud cover.

    April--September is fetched so June observations have a complete 60-day
    antecedent window.  Percentile transforms still use June--September only.
    """
    if ee_module is None:
        import ee as ee_module

    if project:
        ee_module.Initialize(project=project)
    else:
        ee_module.Initialize()
    domain_path = Path(domains_geojson).resolve()
    features = load_domain_features(domain_path, config)
    geometry_manifest = _domain_geometry_manifest(features)
    selected_years = list(years if years is not None else range(
        int(config.study["weather_start_year"]), int(config.study["weather_end_year"]) + 1
    ))
    destination = Path(output_csv)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial_path = destination.with_suffix(destination.suffix + ".partial.csv")
    if resume and partial_path.exists():
        rows = pd.read_csv(partial_path).to_dict("records")
        progress(f"resuming from {partial_path} ({len(rows)} rows)")
    else:
        rows: list[dict[str, Any]] = []
    completed = {
        (str(row["city"]), int(str(row["date"])[:4]))
        for row in rows
        if row.get("city") is not None and row.get("date") is not None
    }
    for city in config.cities:
        geometry = ee_module.Geometry(features[city.slug]["geometry"])
        cloud_hour = target_utc_hour_for_local_solar(city.centroid_lon)
        for year in selected_years:
            if (city.slug, int(year)) in completed:
                progress(f"weather {city.slug} {year}: cached")
                continue
            start = f"{year:04d}-04-01"
            end = f"{year:04d}-10-01"
            progress(f"weather {city.slug} {year}: gridMET")
            weather = _reduce_collection(
                ee_module,
                ee_module.ImageCollection(GRIDMET_COLLECTION).filterDate(start, end),
                geometry,
                city=city.slug,
                bands=GRIDMET_BANDS,
                scale=4638.3,
            )
            progress(f"weather {city.slug} {year}: ERA5 cloud at {cloud_hour:02d}:00 UTC")
            cloud_collection = (
                ee_module.ImageCollection(ERA5_COLLECTION)
                .filterDate(start, end)
                .filter(ee_module.Filter.eq("hour", cloud_hour))
                .select([ERA5_CLOUD_BAND])
            )
            cloud = _reduce_collection(
                ee_module,
                cloud_collection,
                geometry,
                city=city.slug,
                bands=(ERA5_CLOUD_BAND,),
                scale=27830.0,
            )
            weather_frame = pd.DataFrame(weather)
            cloud_frame = pd.DataFrame(cloud)
            if weather_frame.empty or cloud_frame.empty:
                raise RuntimeError(f"{city.slug} {year}: Earth Engine returned an empty collection")
            merged = weather_frame.merge(
                cloud_frame[["city", "date", ERA5_CLOUD_BAND]],
                on=["city", "date"],
                how="left",
                validate="one_to_one",
            )
            merged["cloud_target_utc_hour"] = cloud_hour
            rows.extend(merged.to_dict("records"))
            pd.DataFrame(rows).to_csv(partial_path, index=False)
    frame = pd.DataFrame(rows).rename(
        columns={
            "pr": "pr_mm",
            "eto": "eto_mm",
            "vpd": "vpd_kpa",
            "tmmx": "tmmx_k",
            ERA5_CLOUD_BAND: "cloud_fraction",
        }
    )
    canonical = (
        "city",
        "date",
        "pr_mm",
        "eto_mm",
        "vpd_kpa",
        "tmmx_k",
        "cloud_fraction",
        "cloud_target_utc_hour",
    )
    missing = [name for name in canonical if name not in frame]
    if missing:
        raise RuntimeError(f"Earth Engine response missing columns: {missing}")
    frame = frame[list(canonical)].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    for column in ("pr_mm", "eto_mm", "vpd_kpa", "tmmx_k", "cloud_fraction"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    threshold = float(config.study["clear_sky_max_cloud_fraction"])
    frame["clear_sky"] = frame["cloud_fraction"].notna() & (frame["cloud_fraction"] <= threshold)
    frame = frame.sort_values(["city", "date"]).reset_index(drop=True)
    duplicate = frame.duplicated(["city", "date"])
    if duplicate.any():
        raise RuntimeError(f"Earth Engine returned {int(duplicate.sum())} duplicate city-days")
    frame.to_csv(destination, index=False)
    _write_provenance(
        destination,
        {
            "gridmet_collection": GRIDMET_COLLECTION,
            "gridmet_bands": list(GRIDMET_BANDS),
            "era5_collection": ERA5_COLLECTION,
            "era5_cloud_band": ERA5_CLOUD_BAND,
            "clear_sky_rule": f"city-mean total_cloud_cover <= {threshold} at nearest UTC hour to 14:00 mean local solar time",
            "years": selected_years,
            "domain_file": str(domain_path),
            "domain_file_sha256": hashlib.sha256(domain_path.read_bytes()).hexdigest(),
            "domain_geometry_rule": config.study["domain_analysis_topology_rule"],
            "domain_geometry_by_city": geometry_manifest,
            "row_count": len(frame),
        },
    )
    partial_path.unlink(missing_ok=True)
    return frame


__all__ = [
    "ERA5_CLOUD_BAND",
    "ERA5_COLLECTION",
    "GRIDMET_BANDS",
    "GRIDMET_COLLECTION",
    "fetch_gee_conditions",
    "target_utc_hour_for_local_solar",
]
