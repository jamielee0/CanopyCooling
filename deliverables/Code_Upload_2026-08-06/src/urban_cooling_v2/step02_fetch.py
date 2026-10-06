"""Checkpointed live ECOSTRESS catalogue search for the five frozen domains."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import pandas as pd
from shapely.geometry import box, shape

from .config import StudyConfig
from .domains import geometry_bbox, load_domain_features
from .step02_catalog import CityDomain, normalize_granule_metadata


def footprint_intersects_domain(footprint_json: str | None, domain_geometry: dict[str, Any]) -> bool:
    """Test CMR bounding rectangles/polygons against the actual Census geometry."""
    if footprint_json is None or pd.isna(footprint_json):
        return False
    footprint = json.loads(str(footprint_json))
    domain = shape(domain_geometry)
    rectangles = footprint.get("BoundingRectangles", []) if isinstance(footprint, dict) else []
    for rectangle in rectangles:
        candidate = box(
            float(rectangle["WestBoundingCoordinate"]),
            float(rectangle["SouthBoundingCoordinate"]),
            float(rectangle["EastBoundingCoordinate"]),
            float(rectangle["NorthBoundingCoordinate"]),
        )
        if domain.intersects(candidate):
            return True
    polygons = footprint.get("GPolygons", []) if isinstance(footprint, dict) else []
    for polygon in polygons:
        points = polygon.get("Boundary", {}).get("Points", [])
        coords = [(float(point["Longitude"]), float(point["Latitude"])) for point in points]
        if len(coords) >= 3 and domain.intersects(shape({"type": "Polygon", "coordinates": [coords]})):
            return True
    return False


def _city_domain(city: Any, feature: dict[str, Any]) -> CityDomain:
    return CityDomain(
        city=city.slug,
        centroid_latitude=city.centroid_lat,
        centroid_longitude=city.centroid_lon,
        bbox_wsen=geometry_bbox(feature["geometry"]),
    )


def fetch_ecostress_catalogue(
    config: StudyConfig,
    domains_geojson: str | Path,
    output_csv: str | Path,
    *,
    search_data: Callable[..., Sequence[Any]] | None = None,
    years: Iterable[int] | None = None,
    progress: Callable[[str], None] = print,
    resume: bool = True,
) -> pd.DataFrame:
    """Query metadata only, filter tile footprints to domains, and checkpoint yearly."""
    if search_data is None:
        import earthaccess

        search_data = earthaccess.search_data
    features = load_domain_features(domains_geojson, config)
    selected_years = list(years if years is not None else range(
        int(config.study["weather_start_year"]), int(config.study["weather_end_year"]) + 1
    ))
    destination = Path(output_csv)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial.csv")
    if resume and partial.exists():
        rows = pd.read_csv(partial).to_dict("records")
        progress(f"resuming from {partial} ({len(rows)} rows)")
    else:
        rows: list[dict[str, Any]] = []
    completed = {
        (str(row["city"]), int(row["query_year"]))
        for row in rows
        if row.get("city") is not None and row.get("query_year") is not None
    }
    query_records: list[dict[str, Any]] = []
    for city in config.cities:
        feature = features[city.slug]
        domain = _city_domain(city, feature)
        for year in selected_years:
            if (city.slug, int(year)) in completed:
                progress(f"catalogue {city.slug} {year}: cached")
                continue
            start = f"{year:04d}-06-01T00:00:00Z"
            end = f"{year:04d}-09-30T23:59:59Z"
            progress(f"catalogue {city.slug} {year}")
            results = search_data(
                short_name=str(config.ecostress["short_name"]),
                version=str(config.ecostress["catalogue_version"]),
                provider="LPCLOUD",
                bounding_box=domain.bbox_wsen,
                temporal=(start, end),
                count=-1,
            )
            normalized = normalize_granule_metadata(results, domain)
            bbox_count = len(normalized)
            if not normalized.empty:
                normalized["domain_intersects"] = normalized["footprint_json"].map(
                    lambda value: footprint_intersects_domain(value, feature["geometry"])
                )
                normalized = normalized.loc[normalized["domain_intersects"]].copy()
                normalized["query_year"] = int(year)
                normalized["collection_short_name"] = str(config.ecostress["short_name"])
                normalized["collection_version"] = str(config.ecostress["catalogue_version"])
                normalized["collection_concept_id"] = str(config.ecostress["catalogue_concept_id"])
                normalized["domain_geoid"] = city.urban_area_geoid
                rows.extend(normalized.to_dict("records"))
            query_records.append(
                {
                    "city": city.slug,
                    "year": int(year),
                    "bbox_granules": bbox_count,
                    "domain_intersecting_granules": len(normalized),
                }
            )
            pd.DataFrame(rows).to_csv(partial, index=False)
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError("ECOSTRESS catalogue search returned no intersecting granules")
    frame["acquisition_utc"] = pd.to_datetime(frame["acquisition_utc"], utc=True)
    frame = (
        frame.drop_duplicates(["city", "granule_id"])
        .sort_values(["city", "acquisition_utc", "tile"])
        .reset_index(drop=True)
    )
    frame.to_csv(destination, index=False)
    partial.unlink(missing_ok=True)
    query_path = destination.with_suffix(destination.suffix + ".query_counts.csv")
    # When resuming, recompute the definitive domain counts from the finished table;
    # bbox counts from earlier sessions remain unavailable and are left explicit.
    definitive = frame.groupby(["city", "query_year"], as_index=False).size().rename(
        columns={"size": "domain_intersecting_granules"}
    )
    definitive["bbox_granules"] = pd.NA
    if query_records and len(completed) == 0:
        observed = pd.DataFrame(query_records)
        definitive = observed[["city", "year", "bbox_granules", "domain_intersecting_granules"]].rename(
            columns={"year": "query_year"}
        )
    definitive.to_csv(query_path, index=False)
    sidecar = destination.with_suffix(destination.suffix + ".provenance.json")
    sidecar.write_text(
        json.dumps(
            {
                "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                "query_type": "earthaccess/CMR metadata only; no imagery downloaded",
                "short_name": config.ecostress["short_name"],
                "version": config.ecostress["catalogue_version"],
                "collection_concept_id": config.ecostress["catalogue_concept_id"],
                "years": selected_years,
                "domain_rule": "CMR bbox query followed by exact intersection of tile footprint and frozen Census Urban Area geometry",
                "row_count": len(frame),
                "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return frame


__all__ = ["fetch_ecostress_catalogue", "footprint_intersects_domain"]

