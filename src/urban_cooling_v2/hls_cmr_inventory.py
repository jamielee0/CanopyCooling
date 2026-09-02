#!/usr/bin/env python3
"""Pure helpers for the v6.2 HLS CMR inventory and lead-lag pairing.

NASA CMR discovery is public.  Authentication is deliberately kept out of this
module so metadata can be inventoried before any protected HLS asset is opened.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import pandas as pd
from shapely.geometry import Polygon, shape

from urban_cooling_v2.lead_lag_feasibility import choose_matched_pair


CMR_GRANULE_SEARCH = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
CMR_PAGE_SIZE = 2000
PRODUCTS = {
    "HLSL30.002": {
        "collection_concept_id": "C2021957657-LPCLOUD",
        "granule_prefix": "HLS.L30.",
        "required_reflectance_assets": ("B04", "B05", "B06"),
    },
    "HLSS30.002": {
        "collection_concept_id": "C2021957295-LPCLOUD",
        "granule_prefix": "HLS.S30.",
        "required_reflectance_assets": ("B04", "B8A", "B11"),
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def geometry_bbox(geometry: Mapping[str, Any]) -> tuple[float, float, float, float]:
    return tuple(float(value) for value in shape(geometry).bounds)


def _attributes(umm: Mapping[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in umm.get("AdditionalAttributes", []):
        name = str(item.get("Name", ""))
        result[name] = [str(value) for value in item.get("Values", [])]
    return result


def _attribute_first(attributes: Mapping[str, Sequence[str]], name: str) -> str | None:
    values = attributes.get(name, ())
    return str(values[0]) if values else None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_time(umm: Mapping[str, Any]) -> str:
    temporal = umm.get("TemporalExtent", {})
    if "RangeDateTime" in temporal:
        return str(temporal["RangeDateTime"]["BeginningDateTime"])
    if "SingleDateTime" in temporal:
        return str(temporal["SingleDateTime"])
    raise ValueError(f"CMR granule lacks source time: {umm.get('GranuleUR')}")


def _footprint(umm: Mapping[str, Any]) -> dict[str, Any] | None:
    geometry = (
        umm.get("SpatialExtent", {})
        .get("HorizontalSpatialDomain", {})
        .get("Geometry", {})
    )
    polygons = geometry.get("GPolygons", [])
    rings = []
    for item in polygons:
        points = item.get("Boundary", {}).get("Points", [])
        ring = [[float(point["Longitude"]), float(point["Latitude"])] for point in points]
        if len(ring) >= 4:
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            rings.append(ring)
    if not rings:
        return None
    if len(rings) == 1:
        return {"type": "Polygon", "coordinates": [rings[0]]}
    return {"type": "MultiPolygon", "coordinates": [[[point for point in ring]] for ring in rings]}


def _asset_name(url: str) -> str | None:
    name = Path(urlparse(url).path).name
    if not name.lower().endswith(".tif"):
        return None
    parts = name.split(".")
    return parts[-2] if len(parts) >= 2 else None


def parse_cmr_item(
    item: Mapping[str, Any],
    *,
    sensor: str,
    city: str,
    city_geometry: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize one CMR UMM granule without opening any HLS asset."""

    meta = item.get("meta", {})
    umm = item.get("umm", {})
    granule = str(umm.get("GranuleUR") or meta.get("native-id") or "")
    expected = str(PRODUCTS[sensor]["granule_prefix"])
    if not granule.startswith(expected):
        raise ValueError(f"Unexpected granule for {sensor}: {granule}")
    attributes = _attributes(umm)
    footprint = _footprint(umm)
    overlaps = bool(footprint and shape(city_geometry).intersects(shape(footprint)))
    assets: dict[str, str] = {}
    for related in umm.get("RelatedUrls", []):
        if related.get("Type") != "GET DATA":
            continue
        url = str(related.get("URL", ""))
        asset = _asset_name(url)
        if asset and url.startswith("https://"):
            assets[asset] = url
    return {
        "city": city,
        "sensor": sensor,
        "collection_concept_id": str(meta.get("collection-concept-id", "")),
        "granule_concept_id": str(meta.get("concept-id", "")),
        "optical_acquisition_id": granule,
        "source_time": utc(_source_time(umm)).isoformat(),
        "mgrs_tile": _attribute_first(attributes, "MGRS_TILE_ID"),
        "cloud_coverage_percent": _float_or_none(
            _attribute_first(attributes, "CLOUD_COVERAGE")
        ),
        "spatial_coverage_percent": _float_or_none(
            _attribute_first(attributes, "SPATIAL_COVERAGE")
        ),
        "product_uri": _attribute_first(attributes, "PRODUCT_URI"),
        "domain_geometry_intersects": overlaps,
        "footprint": footprint,
        "assets": dict(sorted(assets.items())),
    }


def cmr_query(
    *,
    collection_concept_id: str,
    bbox: Sequence[float],
    start: Any,
    end: Any,
    timeout_seconds: int = 120,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch every public CMR UMM result for one product/city/time query."""

    base = {
        "collection_concept_id": collection_concept_id,
        "bounding_box": ",".join(f"{float(value):.8f}" for value in bbox),
        "temporal": f"{utc(start).strftime('%Y-%m-%dT%H:%M:%SZ')},"
        f"{utc(end).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "page_size": str(CMR_PAGE_SIZE),
    }
    items: list[dict[str, Any]] = []
    page = 1
    hits: int | None = None
    while True:
        params = dict(base)
        params["page_num"] = str(page)
        url = f"{CMR_GRANULE_SEARCH}?{urlencode(params)}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "urban-tree-cooling-v6.2-hls-inventory/1.0",
            },
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.load(response)
        if hits is None:
            hits = int(payload.get("hits", 0))
        page_items = list(payload.get("items", []))
        items.extend(page_items)
        if not page_items or len(items) >= hits or len(page_items) < CMR_PAGE_SIZE:
            break
        page += 1
    if hits is None or len(items) != hits:
        raise RuntimeError(f"Incomplete CMR paging: expected {hits}, retrieved {len(items)}")
    query = {
        "endpoint": CMR_GRANULE_SEARCH,
        "parameters": base,
        "hits": hits,
        "retrieved": len(items),
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
    }
    return query, items


def pair_candidate_passes(
    candidate_rows: Sequence[Mapping[str, Any]],
    acquisitions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Apply the frozen timing rule to every pass-window-sensor row."""

    frames: dict[tuple[str, str], pd.DataFrame] = {}
    for city in sorted({str(row["city"]) for row in candidate_rows}):
        for sensor in PRODUCTS:
            selected = [
                row
                for row in acquisitions
                if row["city"] == city
                and row["sensor"] == sensor
                and row["domain_geometry_intersects"]
            ]
            frames[(city, sensor)] = pd.DataFrame(selected)
    results: list[dict[str, Any]] = []
    for candidate in candidate_rows:
        for sensor in PRODUCTS:
            frame = frames[(str(candidate["city"]), sensor)]
            if frame.empty:
                frame = pd.DataFrame(
                    columns=["optical_acquisition_id", "sensor", "source_time"]
                )
            pair = choose_matched_pair(candidate["thermal_acquisition_utc"], frame, sensor=sensor)
            result = {**candidate, "sensor": sensor, "catalogue_pair_available": pair is not None}
            result.update(
                pair
                if pair is not None
                else {
                    "pre_acquisition_id": None,
                    "post_acquisition_id": None,
                    "pre_lag_days": None,
                    "post_lag_days": None,
                    "lag_imbalance_days": None,
                }
            )
            results.append(result)
    return results


def summarize_strata(pair_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Summarize the complete city/year/window/sensor catalogue feasibility grid."""

    cities = ("phoenix", "los_angeles")
    windows = ("provisional_primary", "sensitivity")
    rows: list[dict[str, Any]] = []
    for city in cities:
        for year in range(2019, 2026):
            for window in windows:
                for sensor in PRODUCTS:
                    selected = [
                        row
                        for row in pair_rows
                        if row["city"] == city
                        and int(row["year"]) == year
                        and row["season_window"] == window
                        and row["sensor"] == sensor
                    ]
                    paired = [row for row in selected if row["catalogue_pair_available"]]
                    identifiers: list[str] = []
                    for row in paired:
                        identifiers.extend(
                            [str(row["pre_acquisition_id"]), str(row["post_acquisition_id"])]
                        )
                    counts = Counter(identifiers)
                    candidate_count = len(selected)
                    paired_count = len(paired)
                    rows.append(
                        {
                            "city": city,
                            "year": year,
                            "season_window": window,
                            "sensor": sensor,
                            "candidate_passes": candidate_count,
                            "catalogue_matched_pair_passes": paired_count,
                            "catalogue_matched_pair_share": (
                                paired_count / candidate_count if candidate_count else None
                            ),
                            "unique_selected_acquisition_ids": len(counts),
                            "max_candidate_passes_sharing_one_selected_acquisition": max(
                                counts.values(), default=0
                            ),
                            "status": (
                                "CATALOGUE_PAIR_AVAILABLE_REQUIRES_FMASK_QA"
                                if paired_count
                                else (
                                    "NO_CATALOGUE_PAIR"
                                    if candidate_count
                                    else "NO_CANDIDATE_PASSES"
                                )
                            ),
                        }
                    )
    return rows


def selected_asset_plan(
    pair_rows: Sequence[Mapping[str, Any]],
    acquisitions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Create a deduplicated, credential-gated plan for selected HLS assets."""

    selected_ids = {
        str(row[key])
        for row in pair_rows
        if row["catalogue_pair_available"]
        for key in ("pre_acquisition_id", "post_acquisition_id")
    }
    lookup = {str(row["optical_acquisition_id"]): row for row in acquisitions}
    plan = []
    for acquisition_id in sorted(selected_ids):
        row = lookup[acquisition_id]
        assets = row["assets"]
        required = PRODUCTS[str(row["sensor"])]["required_reflectance_assets"]
        plan.append(
            {
                "city": row["city"],
                "sensor": row["sensor"],
                "optical_acquisition_id": acquisition_id,
                "source_time": row["source_time"],
                "mgrs_tile": row["mgrs_tile"],
                "cloud_coverage_percent": row["cloud_coverage_percent"],
                "fmask_url": assets.get("Fmask"),
                "reflectance_asset_names": list(required),
                "reflectance_urls": {name: assets.get(name) for name in required},
                "all_required_urls_present": bool(
                    assets.get("Fmask") and all(assets.get(name) for name in required)
                ),
            }
        )
    return plan


def exact_reuse_share(pair_rows: Iterable[Mapping[str, Any]]) -> float | None:
    """Return the frozen acquisition-reuse share without a small-n exception."""

    rows = list(pair_rows)
    if not rows:
        return None
    identifiers: list[str] = []
    for row in rows:
        if row.get("catalogue_pair_available"):
            identifiers.extend([str(row["pre_acquisition_id"]), str(row["post_acquisition_id"])])
    maximum = max(Counter(identifiers).values(), default=0)
    return maximum / len(rows)
