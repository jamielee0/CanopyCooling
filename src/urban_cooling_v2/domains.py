"""Fetch, validate, freeze, and load the five official Census Urban Areas."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable

from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union

from .config import StudyConfig


EXPECTED_FIELDS = (
    "GEOID",
    "UA",
    "NAME",
    "AREALAND",
    "AREAWATER",
    "CENTLAT",
    "CENTLON",
)


def canonical_json_bytes(value: Any) -> bytes:
    """Return stable UTF-8 JSON bytes suitable for provenance hashes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def valid_analysis_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    """Return a polygonal, topology-valid representation of a source geometry.

    TIGERweb's GeoJSON response can become self-intersecting after the declared
    sub-grid simplification.  The source bytes and source hash remain frozen;
    this deterministic GEOS repair is the geometry used by analysis code.
    """

    source = shape(geometry)
    repaired = source if source.is_valid else make_valid(source)
    if isinstance(repaired, GeometryCollection):
        polygons = [
            part
            for part in repaired.geoms
            if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty
        ]
        repaired = unary_union(polygons)
    if not isinstance(repaired, (Polygon, MultiPolygon)) or repaired.is_empty:
        raise ValueError("domain topology repair did not yield a polygonal geometry")
    if not repaired.is_valid:
        raise ValueError("domain geometry remains invalid after topology repair")
    return mapping(repaired)


def _coordinates(geometry: dict[str, Any]) -> Iterable[tuple[float, float]]:
    def visit(value: Any) -> Iterable[tuple[float, float]]:
        if (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            yield float(value[0]), float(value[1])
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from visit(child)

    yield from visit(geometry.get("coordinates", []))


def geometry_bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    points = list(_coordinates(geometry))
    if not points:
        raise ValueError("domain geometry has no coordinates")
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def _request_feature(
    service_url: str,
    geoid: str,
    request_get: Callable[..., Any],
) -> dict[str, Any]:
    query_url = service_url.rstrip("/") + "/query"
    params = {
        "where": f"GEOID='{geoid}'",
        "outFields": ",".join(EXPECTED_FIELDS),
        "returnGeometry": "true",
        "outSR": "4326",
        "geometryPrecision": "5",
        # The source feature remains identified by GEOID.  This tolerance only
        # simplifies the computational representation below the 4-km weather grid.
        "maxAllowableOffset": "0.0005",
        "f": "geojson",
    }
    response = request_get(query_url, params=params, timeout=120)
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features", [])
    if len(features) != 1:
        raise RuntimeError(f"Census query for GEOID {geoid} returned {len(features)} features")
    return features[0]


def fetch_census_domains(
    config: StudyConfig,
    output_path: str | Path,
    *,
    request_get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Fetch all frozen features and write a GeoJSON plus provenance sidecar.

    The exact source feature is fixed by its 2020 Urban Area GEOID.  Geometry is
    returned in WGS84 with a sub-grid simplification tolerance documented in the
    sidecar, keeping Earth Engine requests tractable without changing the domain rule.
    """
    if request_get is None:
        import requests

        request_get = requests.get
    features: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for city in config.cities:
        feature = _request_feature(config.study["domain_service"], city.urban_area_geoid, request_get)
        props = feature.get("properties", {})
        actual_geoid = str(props.get("GEOID", "")).zfill(5)
        if actual_geoid != city.urban_area_geoid:
            raise ValueError(f"{city.slug}: expected GEOID {city.urban_area_geoid}, got {actual_geoid}")
        if props.get("NAME") != city.urban_area_name:
            raise ValueError(
                f"{city.slug}: expected {city.urban_area_name!r}, got {props.get('NAME')!r}"
            )
        area_km2 = float(props["AREALAND"]) / 1_000_000.0
        if abs(area_km2 - city.area_land_km2) > 0.001:
            raise ValueError(
                f"{city.slug}: configured/source area mismatch {city.area_land_km2} vs {area_km2} km2"
            )
        geometry_hash = sha256_json(feature["geometry"])
        bbox = geometry_bbox(feature["geometry"])
        feature["id"] = city.slug
        feature["properties"] = {
            **props,
            "city": city.slug,
            "label": city.label,
            "climate_role": city.climate_role,
            "geometry_sha256": geometry_hash,
        }
        features.append(feature)
        records.append(
            {
                **asdict(city),
                "source_area_land_km2": area_km2,
                "bbox_wgs84": list(bbox),
                "geometry_sha256": geometry_hash,
            }
        )
    collection = {
        "type": "FeatureCollection",
        "name": "urban_tree_cooling_v2_frozen_2020_urban_areas",
        "features": features,
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(collection, indent=2) + "\n", encoding="utf-8")
    provenance = {
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "source_service": config.study["domain_service"],
        "source_vintage": config.study["domain_vintage"],
        "query_rule": "one exact GEOID per city; WGS84; geometryPrecision=5; maxAllowableOffset=0.0005 degrees",
        "feature_collection_sha256": sha256_json(collection),
        "records": records,
    }
    sidecar = destination.with_suffix(destination.suffix + ".provenance.json")
    sidecar.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return provenance


def load_domain_features(path: str | Path, config: StudyConfig) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError("domain file must be a GeoJSON FeatureCollection")
    by_city = {feature.get("properties", {}).get("city"): feature for feature in payload["features"]}
    if set(by_city) != set(config.city_slugs):
        raise ValueError(f"domain cities {sorted(by_city)} do not match config {sorted(config.city_slugs)}")
    for city in config.cities:
        props = by_city[city.slug]["properties"]
        if str(props.get("GEOID", "")).zfill(5) != city.urban_area_geoid:
            raise ValueError(f"{city.slug}: cached domain GEOID does not match frozen config")
        expected = props.get("geometry_sha256")
        actual = sha256_json(by_city[city.slug]["geometry"])
        if expected != actual:
            raise ValueError(f"{city.slug}: cached domain geometry checksum failed")
        analysis_geometry = valid_analysis_geometry(by_city[city.slug]["geometry"])
        analysis_hash = sha256_json(analysis_geometry)
        by_city[city.slug] = {
            **by_city[city.slug],
            "geometry": analysis_geometry,
            "properties": {
                **props,
                "source_geometry_sha256": expected,
                "analysis_geometry_sha256": analysis_hash,
                "topology_repair_applied": analysis_hash != expected,
                "topology_rule": "GEOS make_valid; retain polygonal components",
            },
        }
    return by_city


def domain_records(path: str | Path, config: StudyConfig) -> list[dict[str, Any]]:
    """Return compact records for Step 1 table T1.2."""
    features = load_domain_features(path, config)
    rows = []
    for city in config.cities:
        props = features[city.slug]["properties"]
        rows.append(
            {
                "city": city.slug,
                "domain_source": f"{config.study['domain_vintage']} GEOID {city.urban_area_geoid}",
                "area_km2": float(props["AREALAND"]) / 1_000_000.0,
                "geometry_sha256": props["geometry_sha256"],
                "analysis_geometry_sha256": props["analysis_geometry_sha256"],
                "topology_repair_applied": props["topology_repair_applied"],
            }
        )
    return rows


__all__ = [
    "domain_records",
    "fetch_census_domains",
    "geometry_bbox",
    "load_domain_features",
    "sha256_json",
    "valid_analysis_geometry",
]
