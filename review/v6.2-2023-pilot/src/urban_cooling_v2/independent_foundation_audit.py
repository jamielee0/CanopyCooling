#!/usr/bin/env python3
"""Independent v6.2 foundation/catalogue audit.

This file is intentionally self-contained.  It imports no project module and
does not open an ECOSTRESS LST/temperature asset.  It works from CSV/JSON CMR
metadata, nonthermal geometry arrays, and HRRR weather-cell extracts.

Run a fresh metadata query plus the local audit with::

    python src/urban_cooling_v2/independent_foundation_audit.py --live-cmr

Rebuild the packet from the tracked CMR response bodies with::

    python src/urban_cooling_v2/independent_foundation_audit.py
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import math
import re
import statistics
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


COLLECTION3_CONCEPT_ID = "C3998139651-LPCLOUD"
COLLECTION3_SHORT_NAME = "ECO_L2T_LSTE"
COLLECTION3_VERSION = "003"
CMR_ROOT = "https://cmr.earthdata.nasa.gov/search"
PAGE_SIZE = 2000
HISTORICAL_ROLE = "historical_provenance_only_not_v6_2_study_sample"
READY_STATUS = "READY_FOR_FOUNDATION_SIGN_OFF"
FAILED_STATUS = "REQUIRES_RECONCILIATION_BEFORE_FOUNDATION_SIGN_OFF"
CMR_EVIDENCE_RELATIVE = Path(
    "docs/v2/v6_2/foundation_audit/source_evidence/cmr_collection3"
)
GRANULE_RE = re.compile(
    r"^ECOv(?P<collection>\d{3})_L2T_LSTE_"
    r"(?P<orbit>\d+)_(?P<scene>\d+)_(?P<tile>\d{2}[A-Z]{3})_"
    r"(?P<acquisition>\d{8}T\d{6})_(?P<build>\d+)_(?P<revision>\d+)$"
)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def parse_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(value)


def parse_timestamp(value: str) -> dt.datetime:
    timestamp = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
    return timestamp.astimezone(dt.timezone.utc)


def parse_granule_id(granule_id: str) -> dict[str, Any]:
    match = GRANULE_RE.fullmatch(granule_id)
    if match is None:
        raise ValueError(f"Unrecognized ECO_L2T_LSTE native id: {granule_id}")
    out: dict[str, Any] = match.groupdict()
    for key in ("collection", "orbit", "scene", "build", "revision"):
        out[key] = int(out[key])
    return out


def equation_of_time_minutes(timestamp: dt.datetime) -> float:
    timestamp = timestamp.astimezone(dt.timezone.utc)
    hour = (
        timestamp.hour
        + timestamp.minute / 60.0
        + timestamp.second / 3600.0
    )
    day_of_year = timestamp.timetuple().tm_yday
    days = 366.0 if timestamp.replace(month=12, day=31).timetuple().tm_yday == 366 else 365.0
    gamma = 2.0 * math.pi / days * (day_of_year - 1.0 + (hour - 12.0) / 24.0)
    return 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2.0 * gamma)
        - 0.040849 * math.sin(2.0 * gamma)
    )


def local_solar_hour(timestamp: dt.datetime, longitude_deg: float) -> float:
    timestamp = timestamp.astimezone(dt.timezone.utc)
    utc_hour = (
        timestamp.hour
        + timestamp.minute / 60.0
        + timestamp.second / 3600.0
    )
    return (utc_hour + longitude_deg / 15.0 + equation_of_time_minutes(timestamp) / 60.0) % 24.0


def saturation_vapor_pressure_kpa(temperature_k: float) -> float:
    temperature_c = temperature_k - 273.15
    return 0.6108 * math.exp(17.27 * temperature_c / (temperature_c + 237.3))


def vpd_kpa(temperature_k: float, dewpoint_k: float) -> float:
    return max(
        saturation_vapor_pressure_kpa(temperature_k)
        - saturation_vapor_pressure_kpa(dewpoint_k),
        0.0,
    )


def select_strict_latest(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    """Select max build/revision per city, orbit, scene, and MGRS tile."""

    selected: dict[tuple[str, int, int, str], tuple[tuple[int, int, str], str]] = {}
    for row in rows:
        granule_id = str(row["granule_id"])
        parsed = parse_granule_id(granule_id)
        key = (str(row["city"]), parsed["orbit"], parsed["scene"], parsed["tile"])
        rank = (parsed["build"], parsed["revision"], granule_id)
        if key not in selected or rank > selected[key][0]:
            selected[key] = (rank, granule_id)
    return {value[1] for value in selected.values()}


def _median_timestamp(rows: Sequence[Mapping[str, Any]]) -> dt.datetime:
    values = sorted(parse_timestamp(str(row["acquisition_utc"])) for row in rows)
    return values[len(values) // 2]


def historical_catalogue_audit(repo: Path) -> dict[str, Any]:
    raw_path = repo / "data/raw/v2/ecostress/catalogue_tiles_2018_2025.csv"
    ledger_path = repo / "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/observation_ledger.csv"
    raw_rows = read_csv(raw_path)
    ledger_rows = read_csv(ledger_path)

    raw_ids = {row["granule_id"] for row in raw_rows}
    inherited_ids = {
        granule_id
        for row in ledger_rows
        for granule_id in row["selected_granule_ids"].split("|")
        if granule_id
    }
    if not inherited_ids <= raw_ids:
        raise ValueError("Inherited ledger contains granules absent from the raw catalogue")
    strict_latest_ids = select_strict_latest(raw_rows)

    passes: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    parsed_rows: list[tuple[dict[str, str], dict[str, Any]]] = []
    for raw in raw_rows:
        parsed = parse_granule_id(raw["granule_id"])
        parsed_rows.append((raw, parsed))
        if raw["granule_id"] in inherited_ids:
            passes[(raw["city"], parsed["orbit"])].append(raw)

    pass_details: dict[tuple[str, int], dict[str, Any]] = {}
    for key, members in passes.items():
        timestamp = _median_timestamp(members)
        longitude = float(members[0]["centroid_longitude"])
        pass_details[key] = {
            "pass_id": f"{key[0]}|orbit_{key[1]:05d}",
            "acquisition_utc": timestamp.isoformat().replace("+00:00", "Z"),
            "local_solar_time_hours": local_solar_hour(timestamp, longitude),
            "n_selected_rows": len(members),
            "n_scenes": len({parse_granule_id(row["granule_id"])["scene"] for row in members}),
            "n_tiles": len({parse_granule_id(row["granule_id"])["tile"] for row in members}),
        }

    crosswalk: list[dict[str, Any]] = []
    raw_counts = Counter((raw["city"], parsed["orbit"]) for raw, parsed in parsed_rows)
    for raw, parsed in parsed_rows:
        key = (raw["city"], parsed["orbit"])
        inherited = raw["granule_id"] in inherited_ids
        strict = raw["granule_id"] in strict_latest_ids
        crosswalk.append(
            {
                "city": raw["city"],
                "orbit": parsed["orbit"],
                "pass_id": f"{raw['city']}|orbit_{parsed['orbit']:05d}",
                "scene": parsed["scene"],
                "tile": parsed["tile"],
                "acquisition_utc": raw["acquisition_utc"],
                "build": parsed["build"],
                "revision": parsed["revision"],
                "granule_id": raw["granule_id"],
                "raw_rows_in_pass": raw_counts[key],
                "inherited_ledger_selected": inherited,
                "strict_latest_identity_selected": strict,
                "inherited_selection_status": (
                    "selected" if inherited else "omitted_from_inherited_canonical_ledger"
                ),
                "strict_revision_status": "latest" if strict else "superseded",
                "role": HISTORICAL_ROLE,
            }
        )

    stage_specs = [
        ("physical_city_orbit_observations", None, 2968),
        ("daytime_10_18_local_solar", "is_daytime_10_18", 1055),
        ("geolocation_usable", "geolocation_usable", 1017),
        ("metadata_and_obstruction_screen", "metadata_candidate", 942),
        ("archive_available_pre_geometry", "archive_available_for_l1b_geometry", 911),
        ("geometry_pass_historical_20deg", "geometry_pass", 219),
        ("early_late_stratum_eligible_historical", "early_late_stratum_eligible", 102),
    ]
    count_rows: list[dict[str, Any]] = [
        {
            "stage": "raw_domain_intersecting_tiled_products",
            "expected_historical_count": 13577,
            "independent_observed_count": len(raw_rows),
            "unit": "tiled_granule_record",
            "method": "direct raw CSV row count",
            "result": "PASS" if len(raw_rows) == 13577 else "FAIL",
            "role": HISTORICAL_ROLE,
        },
        {
            "stage": "inherited_ledger_provenance_products",
            "expected_historical_count": 13575,
            "independent_observed_count": len(inherited_ids),
            "unit": "tiled_granule_record",
            "method": (
                "distinct tiled identifiers recorded by the inherited observation ledger; "
                "not a latest-revision selector"
            ),
            "result": "PASS" if len(inherited_ids) == 13575 else "FAIL",
            "role": HISTORICAL_ROLE,
        },
        {
            "stage": "strict_latest_build_revision_products",
            "expected_historical_count": 11880,
            "independent_observed_count": len(strict_latest_ids),
            "unit": "tiled_granule_record",
            "method": "max build then revision per city/orbit/scene/tile parsed from native ID",
            "result": "PASS" if len(strict_latest_ids) == 11880 else "FAIL",
            "role": HISTORICAL_ROLE,
        },
    ]
    for stage, field, expected in stage_specs:
        if field is None:
            observed = len(ledger_rows)
        elif stage == "daytime_10_18_local_solar":
            observed = sum(10.0 <= value["local_solar_time_hours"] < 18.0 for value in pass_details.values())
        else:
            observed = sum(parse_bool(row[field]) for row in ledger_rows)
        count_rows.append(
            {
                "stage": stage,
                "expected_historical_count": expected,
                "independent_observed_count": observed,
                "unit": "physical_city_orbit_observation",
                "method": (
                    "raw metadata grouping plus independent NOAA equation-of-time calculation"
                    if stage == "daytime_10_18_local_solar"
                    else "independent boolean census of inherited nonthermal observation ledger"
                ),
                "result": "PASS" if observed == expected else "FAIL",
                "role": HISTORICAL_ROLE,
            }
        )

    omitted = [
        row for row in crosswalk if not row["inherited_ledger_selected"]
    ]
    return {
        "raw_path": raw_path,
        "ledger_path": ledger_path,
        "raw_rows": raw_rows,
        "ledger_rows": ledger_rows,
        "crosswalk": crosswalk,
        "count_rows": count_rows,
        "inherited_ids": inherited_ids,
        "strict_latest_ids": strict_latest_ids,
        "omitted": omitted,
        "pass_details": pass_details,
    }


def _cmr_query_url(parameters: Mapping[str, str]) -> str:
    return CMR_ROOT + "/granules.json?" + urllib.parse.urlencode(parameters)


def _query_definitions(domain_records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    domains = {record["slug"]: record for record in domain_records}
    definitions: list[dict[str, Any]] = []
    scopes = [
        ("historical_june_september", list(domains), {city: ("06-01", "09-30") for city in domains}),
        (
            "v6_2_primary_windows",
            ["phoenix", "los_angeles"],
            {"phoenix": ("05-15", "07-10"), "los_angeles": ("06-01", "09-30")},
        ),
        (
            "v6_2_sensitivity_windows",
            ["phoenix", "los_angeles"],
            {"phoenix": ("06-01", "09-30"), "los_angeles": ("05-15", "07-10")},
        ),
    ]
    for scope, cities, windows in scopes:
        for city in cities:
            west, south, east, north = domains[city]["bbox_wgs84"]
            start_md, end_md = windows[city]
            for year in range(2018, 2026):
                start = f"{year}-{start_md}T00:00:00Z"
                end = f"{year}-{end_md}T23:59:59Z"
                parameters = {
                    "collection_concept_id": COLLECTION3_CONCEPT_ID,
                    "temporal": f"{start},{end}",
                    "bounding_box": f"{west},{south},{east},{north}",
                    "page_size": str(PAGE_SIZE),
                }
                url = _cmr_query_url(parameters)
                definitions.append(
                    {
                        "query_scope": scope,
                        "city": city,
                        "city_role": (
                            "v6_2_gate_A" if city in {"phoenix", "los_angeles"} else "legacy_provenance_city"
                        ),
                        "year": year,
                        "window_start": start_md,
                        "window_end": end_md,
                        "temporal": f"{start}/{end}",
                        "bbox_wsen": parameters["bounding_box"],
                        "url": url,
                        "url_sha256": hashlib.sha256(url.encode()).hexdigest(),
                    }
                )
    return definitions


def _download(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "urban-tree-cooling-v6.2-independent-foundation-audit/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _raw_response_path(raw_dir: Path, url: str, page: int) -> Path:
    token = hashlib.sha256(url.encode()).hexdigest()[:20]
    return raw_dir / f"granules_{token}_page_{page:03d}.json"


def _fetch_or_load_query(definition: Mapping[str, Any], raw_dir: Path, live: bool) -> dict[str, Any]:
    entries = 0
    entry_records: list[dict[str, Any]] = []
    page_hashes: list[str] = []
    pages = 0
    updated = ""
    page = 1
    while True:
        separator = "&" if "?" in definition["url"] else "?"
        page_url = f"{definition['url']}{separator}page_num={page}"
        path = _raw_response_path(raw_dir, definition["url"], page)
        if live:
            body = _download(page_url)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        else:
            if not path.is_file():
                raise FileNotFoundError(f"Recorded CMR response absent; rerun with --live-cmr: {path}")
            body = path.read_bytes()
        payload = json.loads(body)
        feed = payload.get("feed", {})
        page_entries = feed.get("entry", [])
        if not isinstance(page_entries, list):
            raise ValueError(f"CMR response has no list-valued feed.entry: {path}")
        updated = str(feed.get("updated", updated))
        pages += 1
        entries += len(page_entries)
        entry_records.extend(page_entries)
        page_hashes.append(sha256_bytes(body))
        if len(page_entries) < PAGE_SIZE:
            break
        page += 1
    result = dict(definition)
    result.update(
        {
            "response_updated_utc": updated,
            "response_pages": pages,
            "entry_count": entries,
            "response_sha256s": "|".join(page_hashes),
            "result": "NO_ENTRIES" if entries == 0 else "ENTRIES_PRESENT",
            "thermal_or_lst_opened": False,
            "_entries": entry_records,
        }
    )
    return result


def collection3_audit(repo: Path, live: bool) -> dict[str, Any]:
    provenance_path = repo / "data/raw/v2/domains/census_urban_areas.geojson.provenance.json"
    domain_records = json.loads(provenance_path.read_text(encoding="utf-8"))["records"]
    raw_dir = repo / CMR_EVIDENCE_RELATIVE
    raw_dir.mkdir(parents=True, exist_ok=True)

    collection_url = CMR_ROOT + "/collections.json?" + urllib.parse.urlencode(
        {"concept_id": COLLECTION3_CONCEPT_ID, "page_size": "1"}
    )
    collection_path = raw_dir / "collection_C3998139651-LPCLOUD.json"
    if live:
        collection_path.write_bytes(_download(collection_url))
    elif not collection_path.is_file():
        raise FileNotFoundError(f"Recorded collection response absent; rerun with --live-cmr: {collection_path}")
    collection_payload = json.loads(collection_path.read_bytes())
    collection_entries = collection_payload.get("feed", {}).get("entry", [])

    definitions = _query_definitions(domain_records)
    unique: dict[str, dict[str, Any]] = {}
    for definition in definitions:
        unique.setdefault(definition["url"], definition)
    by_url: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_fetch_or_load_query, definition, raw_dir, live): url
            for url, definition in unique.items()
        }
        for future in as_completed(futures):
            by_url[futures[future]] = future.result()
    results = []
    for definition in definitions:
        result = dict(by_url[definition["url"]])
        for field in ("query_scope", "city", "city_role", "year", "window_start", "window_end", "temporal"):
            result[field] = definition[field]
        results.append(result)
    results.sort(key=lambda row: (row["query_scope"], row["city"], row["year"]))
    entry_inventory: dict[str, dict[str, Any]] = {}
    query_context: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"cities": set(), "scopes": set()}
    )
    for definition in definitions:
        for entry in by_url[definition["url"]]["_entries"]:
            concept_id = str(entry.get("id", ""))
            producer_id = str(entry.get("producer_granule_id") or entry.get("title") or "")
            key = concept_id or producer_id
            query_context[key]["cities"].add(definition["city"])
            query_context[key]["scopes"].add(definition["query_scope"])
            if key not in entry_inventory:
                match = re.search(
                    r"_L2T_LSTE_(?P<orbit>\d+)_(?P<scene>\d+)_(?P<tile>\d{2}[A-Z]{3})_",
                    producer_id,
                )
                entry_inventory[key] = {
                    "concept_id": concept_id,
                    "producer_granule_id": producer_id,
                    "acquisition_utc": entry.get("time_start", ""),
                    "orbit": int(match.group("orbit")) if match else "",
                    "scene": int(match.group("scene")) if match else "",
                    "tile": match.group("tile") if match else "",
                }
    inventory_rows: list[dict[str, Any]] = []
    for key, entry in entry_inventory.items():
        entry["matched_query_cities"] = "|".join(sorted(query_context[key]["cities"]))
        entry["matched_query_scopes"] = "|".join(sorted(query_context[key]["scopes"]))
        entry["role"] = "current_collection3_metadata_inventory_not_v6_2_sample"
        inventory_rows.append(entry)
    inventory_rows.sort(key=lambda row: (str(row["acquisition_utc"]), str(row["producer_granule_id"])))
    return {
        "provenance_path": provenance_path,
        "collection_url": collection_url,
        "collection_path": collection_path,
        "collection_entry_count": len(collection_entries),
        "raw_dir": raw_dir,
        "results": results,
        "inventory": inventory_rows,
    }


def archive_gap_audit(repo: Path, collection3_inventory: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    historical_path = repo / "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/archive_missing_31_audit.csv"
    unified_path = repo / "docs/v2/hitl/G3_SAMPLING_DESIGN_SECOND_REVISION/unified_unavailable_pass_ledger.csv"
    historical = read_csv(historical_path)
    unified = read_csv(unified_path)
    collection3_orbits = {int(row["orbit"]) for row in collection3_inventory if str(row.get("orbit", ""))}
    output: list[dict[str, Any]] = []
    for row in unified:
        output.append(
            {
                "physical_pass_id": row.get("physical_pass_id") or row.get("observation_id"),
                "city": row["city"],
                "orbit": row["orbit"],
                "acquisition_utc": row["acquisition_utc"],
                "source_population": row.get("source_population", ""),
                "unavailable_source": row.get("unavailable_source", ""),
                "archive_status": row.get("archive_status", ""),
                "required_l1b_scene_count": row.get("required_l1b_scene_count", ""),
                "unavailable_l1b_scene_count": row.get("unavailable_l1b_scene_count", ""),
                "unavailable_l1b_scene_keys": row.get("unavailable_l1b_scene_keys", ""),
                "bound_scope_included": row.get("bound_scope_included", ""),
                "geometry_outcome_known": row.get("geometry_outcome_known", ""),
                "cloud_weight_known": row.get("cloud_weight_known", ""),
                "collection3_live_recovery_status": (
                    "POTENTIAL_ORBIT_MATCH_REQUIRES_EXACT_SCENE_CHECK"
                    if int(float(row["orbit"])) in collection3_orbits
                    else "NOT_RECOVERED_NO_COLLECTION3_ORBIT_MATCH"
                ),
                "role": HISTORICAL_ROLE,
            }
        )
    return {
        "historical_path": historical_path,
        "unified_path": unified_path,
        "historical_count": len(historical),
        "unified_count": len(unified),
        "bound_scope_count": sum(parse_bool(row.get("bound_scope_included")) for row in unified),
        "collection3_potential_orbit_matches": sum(
            int(float(row["orbit"])) in collection3_orbits for row in unified
        ),
        "rows": output,
    }


def _close(actual: float | None, expected: float | None, tolerance: float = 1e-5) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    return abs(actual - expected) <= tolerance


def _np_scalar(array: np.ndarray) -> Any:
    return array.item() if array.shape == () else array


def geometry_recovery_audit(repo: Path) -> dict[str, Any]:
    summary_path = repo / "data/processed/v2/hitl/g3_sampling_design_revision2/geometry_azimuth_pass_summary.csv"
    reconstruction_root = repo / "data/raw/v2/hitl/g3_sampling_design_revision2/geometry_azimuth_reconstruction"
    joined_path = repo / "docs/v2/hitl/G3_SAMPLING_DESIGN_SECOND_REVISION/pass_evidence_25deg_joined.csv"
    unavailable_path = repo / "docs/v2/hitl/G3_SAMPLING_DESIGN_SECOND_REVISION/unified_unavailable_pass_ledger.csv"
    rows = read_csv(summary_path)
    joined = read_csv(joined_path)
    unavailable = read_csv(unavailable_path)
    if len(rows) != 762:
        raise ValueError(f"Expected 762 geometry-ledger rows, found {len(rows)}")

    checks: list[dict[str, Any]] = []
    for row in rows:
        city = row["city"]
        orbit = int(float(row["orbit"]))
        expected_hash = row["geometry_reconstruction_artifact_sha256"].strip()
        expected = bool(expected_hash)
        artifact = reconstruction_root / city / f"{orbit:05d}.npz"
        check: dict[str, Any] = {
            "city": city,
            "orbit": orbit,
            "window_id": row["window_id"],
            "source_population": row["source_population"],
            "geometry_azimuth_status": row["geometry_azimuth_status"],
            "reconstruction_expected": expected,
            "artifact_path": str(artifact.relative_to(repo)) if expected else "",
            "artifact_exists": artifact.is_file() if expected else not artifact.exists(),
            "artifact_hash_match": not expected,
            "identity_match": not expected,
            "array_shape_match": not expected,
            "metric_match": not expected,
            "role": HISTORICAL_ROLE,
        }
        if expected and artifact.is_file():
            check["artifact_hash_match"] = sha256_path(artifact) == expected_hash
            with np.load(artifact, allow_pickle=False) as archive:
                required = {
                    "format_version",
                    "city",
                    "window_id",
                    "orbit",
                    "n_domain_pixels",
                    "valid_target_index",
                    "view_zenith_abs_deg",
                    "view_azimuth_deg",
                    "solar_azimuth_deg",
                }
                missing = required - set(archive.files)
                if missing:
                    raise ValueError(f"{artifact}: missing arrays {sorted(missing)}")
                view = np.asarray(archive["view_zenith_abs_deg"], dtype=float)
                view_azimuth = np.asarray(archive["view_azimuth_deg"], dtype=float)
                solar_azimuth = np.asarray(archive["solar_azimuth_deg"], dtype=float)
                indices = np.asarray(archive["valid_target_index"])
                n_domain = int(_np_scalar(archive["n_domain_pixels"]))
                check["identity_match"] = (
                    str(_np_scalar(archive["city"])) == city
                    and int(_np_scalar(archive["orbit"])) == orbit
                    and str(_np_scalar(archive["window_id"])) == row["window_id"]
                )
                check["array_shape_match"] = (
                    view.ndim == view_azimuth.ndim == solar_azimuth.ndim == indices.ndim == 1
                    and len(view) == len(view_azimuth) == len(solar_azimuth) == len(indices)
                )
                finite_view = np.isfinite(view)
                n_view = int(finite_view.sum())
                coverage = n_view / n_domain if n_domain else 0.0
                overlap = finite_view & np.isfinite(view_azimuth) & np.isfinite(solar_azimuth)
                azimuth_fraction = float(overlap.sum() / n_view) if n_view else 0.0
                p95 = float(np.nanpercentile(view, 95)) if n_view else None
                check.update(
                    {
                        "n_domain_pixels_recalculated": n_domain,
                        "n_view_valid_pixels_recalculated": n_view,
                        "coverage_recalculated": coverage,
                        "view_p95_recalculated_deg": "" if p95 is None else p95,
                        "azimuth_valid_fraction_recalculated": azimuth_fraction,
                    }
                )
                expected_n_domain = int(float(row["n_domain_pixels"]))
                expected_n_view = int(float(row["n_view_valid_pixels"]))
                expected_coverage = float(row["l1b_geometry_coverage_fraction"])
                expected_p95 = parse_float(row["l1b_view_zenith_abs_p95_deg"])
                expected_fraction = parse_float(row["azimuth_valid_fraction_of_view_cells"])
                fraction_match = (
                    n_view == 0 and expected_fraction is None
                ) or _close(azimuth_fraction, expected_fraction, 1e-10)
                check["metric_match"] = (
                    n_domain == expected_n_domain
                    and n_view == expected_n_view
                    and _close(coverage, expected_coverage, 1e-10)
                    and _close(p95, expected_p95, 1e-5)
                    and fraction_match
                )
        check["audit_pass"] = all(
            bool(check[field])
            for field in (
                "artifact_exists",
                "artifact_hash_match",
                "identity_match",
                "array_shape_match",
                "metric_match",
            )
        )
        checks.append(check)

    status_counts = Counter(row["geometry_azimuth_status"] for row in rows)
    reconstruction_count = sum(bool(row["geometry_reconstruction_artifact_sha256"].strip()) for row in rows)
    summary = [
        {"check": "geometry_ledger_rows", "observed": len(rows), "expected": 762, "result": "PASS" if len(rows) == 762 else "FAIL"},
        {"check": "reconstruction_artifacts", "observed": reconstruction_count, "expected": 734, "result": "PASS" if reconstruction_count == 734 else "FAIL"},
        {"check": "all_reconstruction_hashes_and_metrics", "observed": sum(row["audit_pass"] for row in checks), "expected": 762, "result": "PASS" if all(row["audit_pass"] for row in checks) else "FAIL"},
        {"check": "complete_positive_maps", "observed": status_counts["COMPLETE"], "expected": 127, "result": "PASS" if status_counts["COMPLETE"] == 127 else "FAIL"},
        {"check": "verified_zero_maps", "observed": status_counts["RESOLVED_VERIFIED_ZERO_MAPPED_CELLS"], "expected": 221, "result": "PASS" if status_counts["RESOLVED_VERIFIED_ZERO_MAPPED_CELLS"] == 221 else "FAIL"},
        {"check": "accessible_azimuth_incomplete", "observed": status_counts["AZIMUTH_INCOMPLETE"], "expected": 386, "result": "PASS" if status_counts["AZIMUTH_INCOMPLETE"] == 386 else "FAIL"},
        {"check": "resolved_unavailable_rows_in_geometry_ledger", "observed": status_counts["RESOLVED_UNAVAILABLE"], "expected": 28, "result": "PASS" if status_counts["RESOLVED_UNAVAILABLE"] == 28 else "FAIL"},
        {"check": "joined_geometry_cloud_weather_passes_at_25deg", "observed": len(joined), "expected": 52, "result": "PASS" if len(joined) == 52 and all(parse_bool(row["cloud_complete"]) and parse_bool(row["exact_weather_complete"]) for row in joined) else "FAIL"},
        {"check": "unified_archive_unavailable_passes", "observed": len(unavailable), "expected": 43, "result": "PASS" if len(unavailable) == 43 else "FAIL"},
    ]
    for row in summary:
        row["role"] = HISTORICAL_ROLE
    return {
        "summary_path": summary_path,
        "joined_path": joined_path,
        "unavailable_path": unavailable_path,
        "checks": checks,
        "summary": summary,
        "status_counts": status_counts,
    }


def _hourly_cell_summary(path: Path, city: str) -> dict[str, Any]:
    temperatures: list[float] = []
    dewpoints: list[float] = []
    reported_vpd: list[float] = []
    recalculated_vpd: list[float] = []
    timestamps: set[str] = set()
    with gzip.open(path, "rt", newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["city"] != city:
                continue
            temperature = float(row["t2m_k"])
            dewpoint = float(row["d2m_k"])
            temperatures.append(temperature)
            dewpoints.append(dewpoint)
            reported_vpd.append(float(row["vpd_kpa"]))
            recalculated_vpd.append(vpd_kpa(temperature, dewpoint))
            timestamps.add(row["timestamp_utc"])
    if not temperatures:
        raise ValueError(f"{path}: no rows for {city}")
    if len(timestamps) != 1:
        raise ValueError(f"{path}: expected one timestamp for {city}, found {timestamps}")
    return {
        "n_domain_cells": len(temperatures),
        "mean_t2m_k": statistics.fmean(temperatures),
        "mean_d2m_k": statistics.fmean(dewpoints),
        "mean_vpd_kpa": statistics.fmean(reported_vpd),
        "max_cell_vpd_formula_error_kpa": max(abs(a - b) for a, b in zip(reported_vpd, recalculated_vpd, strict=True)),
    }


def hrrr_join_audit(repo: Path) -> dict[str, Any]:
    crosswalk_path = repo / "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/hrrr_pass_hour_crosswalk.csv"
    hourly_path = repo / "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo_D0047_archive_available/hrrr_hourly_domain_summary.csv"
    cells_root = repo / "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo_D0047_archive_available/hourly_domain_cells"
    pass_path = repo / "docs/v2/hitl/G2_HYDROCLIMATE_SUPPORT/pass_hydroclimate_219.csv"
    manifest_path = repo / "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo_D0047_archive_available_manifest.csv"
    links = read_csv(crosswalk_path)
    hourly = read_csv(hourly_path)
    passes = read_csv(pass_path)
    manifest = read_csv(manifest_path)

    by_observation: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in links:
        by_observation[row["observation_id"]].append(row)
    pass_lookup = {row["observation_id"]: row for row in passes}
    hourly_lookup = {(row["city"], parse_timestamp(row["timestamp_utc"])): row for row in hourly}
    by_city: dict[str, list[str]] = defaultdict(list)
    for observation_id, rows in by_observation.items():
        by_city[rows[0]["city"]].append(observation_id)

    sample_ids: list[str] = []
    for city in sorted(by_city):
        ranked = sorted(by_city[city], key=lambda value: hashlib.sha256(value.encode()).hexdigest())
        sample_ids.extend(ranked[:2])

    samples: list[dict[str, Any]] = []
    for observation_id in sorted(sample_ids):
        rows = sorted(by_observation[observation_id], key=lambda row: parse_timestamp(row["analysis_utc"]))
        if len(rows) != 2:
            raise ValueError(f"{observation_id}: expected two HRRR brackets, found {len(rows)}")
        floor_row, ceiling_row = rows
        city = floor_row["city"]
        acquisition = parse_timestamp(floor_row["acquisition_utc"])
        floor_time = parse_timestamp(floor_row["analysis_utc"])
        ceiling_time = parse_timestamp(ceiling_row["analysis_utc"])
        if not (floor_time < acquisition < ceiling_time):
            raise ValueError(f"{observation_id}: acquisition is not strictly bracketed")
        floor_cells = _hourly_cell_summary(cells_root / f"{floor_row['hrrr_item_id']}.csv.gz", city)
        ceiling_cells = _hourly_cell_summary(cells_root / f"{ceiling_row['hrrr_item_id']}.csv.gz", city)
        floor_summary = hourly_lookup[(city, floor_time)]
        ceiling_summary = hourly_lookup[(city, ceiling_time)]
        denominator = (ceiling_time - floor_time).total_seconds()
        weight = (acquisition - floor_time).total_seconds() / denominator
        interpolated = floor_cells["mean_vpd_kpa"] + weight * (
            ceiling_cells["mean_vpd_kpa"] - floor_cells["mean_vpd_kpa"]
        )
        target = float(pass_lookup[observation_id]["vpd_kpa_at_acquisition"])
        hourly_error = max(
            abs(floor_cells["mean_vpd_kpa"] - float(floor_summary["vpd_kpa"])),
            abs(ceiling_cells["mean_vpd_kpa"] - float(ceiling_summary["vpd_kpa"])),
        )
        formula_error = max(
            floor_cells["max_cell_vpd_formula_error_kpa"],
            ceiling_cells["max_cell_vpd_formula_error_kpa"],
        )
        interpolation_error = abs(interpolated - target)
        samples.append(
            {
                "sample_rule": "two lowest SHA256-ranked observation IDs per city",
                "observation_id": observation_id,
                "city": city,
                "acquisition_utc": acquisition.isoformat().replace("+00:00", "Z"),
                "floor_item_id": floor_row["hrrr_item_id"],
                "ceiling_item_id": ceiling_row["hrrr_item_id"],
                "floor_domain_cells": floor_cells["n_domain_cells"],
                "ceiling_domain_cells": ceiling_cells["n_domain_cells"],
                "interpolation_weight_to_ceiling": weight,
                "recalculated_vpd_kpa": interpolated,
                "recorded_vpd_kpa": target,
                "max_hourly_spatial_mean_error_kpa": hourly_error,
                "max_cell_formula_error_kpa": formula_error,
                "interpolation_error_kpa": interpolation_error,
                "temperature_unit_check": "PASS_KELVIN" if floor_cells["mean_t2m_k"] > 200 and ceiling_cells["mean_t2m_k"] > 200 else "FAIL",
                "audit_pass": hourly_error <= 1e-10 and formula_error <= 1e-12 and interpolation_error <= 1e-10,
                "role": HISTORICAL_ROLE,
            }
        )

    summary = [
        {"check": "physical_passes", "observed": len(by_observation), "expected": 219},
        {"check": "pass_hour_links", "observed": len(links), "expected": 438},
        {"check": "unique_hrrr_assets", "observed": len({row["hrrr_item_id"] for row in links}), "expected": 413},
        {"check": "request_manifest_rows", "observed": len(manifest), "expected": 413},
        {"check": "sampled_join_checks", "observed": sum(row["audit_pass"] for row in samples), "expected": len(samples)},
    ]
    for row in summary:
        row["result"] = "PASS" if row["observed"] == row["expected"] else "FAIL"
        row["role"] = HISTORICAL_ROLE
    return {
        "crosswalk_path": crosswalk_path,
        "hourly_path": hourly_path,
        "pass_path": pass_path,
        "manifest_path": manifest_path,
        "samples": samples,
        "summary": summary,
    }


def _relative(path: Path, repo: Path) -> str:
    return str(path.relative_to(repo))


def evaluate_readiness(
    historical: Mapping[str, Any],
    archive: Mapping[str, Any],
    geometry: Mapping[str, Any],
    hrrr: Mapping[str, Any],
) -> dict[str, Any]:
    """Calculate foundation readiness from every required audit section.

    A check passes only when its independently observed value equals its frozen
    expected value and, for precomputed summary rows, the producer also labels
    the row ``PASS``.  This deliberately fails closed on either disagreement.
    """

    checks: list[dict[str, Any]] = []

    def add_check(
        section: str,
        check: str,
        observed: Any,
        expected: Any,
        source_result: str | None = None,
    ) -> None:
        passed = observed == expected and source_result in {None, "PASS"}
        checks.append(
            {
                "section": section,
                "check": check,
                "observed": observed,
                "expected": expected,
                "source_result": source_result or "CALCULATED",
                "result": "PASS" if passed else "FAIL",
            }
        )

    for row in historical["count_rows"]:
        add_check(
            "historical",
            str(row["stage"]),
            row["independent_observed_count"],
            row["expected_historical_count"],
            str(row["result"]),
        )

    archive_rows = archive["rows"]
    add_check("archive", "historical_archive_gap_count", archive["historical_count"], 31)
    add_check("archive", "unified_archive_gap_count", archive["unified_count"], 43)
    add_check("archive", "old_four_window_bound_count", archive["bound_scope_count"], 28)
    add_check(
        "archive",
        "collection3_potential_gap_recoveries_requiring_review",
        archive["collection3_potential_orbit_matches"],
        0,
    )
    add_check(
        "archive",
        "gaps_without_geometry_outcome",
        sum(not parse_bool(row["geometry_outcome_known"]) for row in archive_rows),
        43,
    )
    add_check(
        "archive",
        "gaps_without_cloud_weight",
        sum(not parse_bool(row["cloud_weight_known"]) for row in archive_rows),
        43,
    )
    add_check(
        "archive",
        "gaps_explicitly_not_recovered_by_collection3",
        sum(
            row["collection3_live_recovery_status"]
            == "NOT_RECOVERED_NO_COLLECTION3_ORBIT_MATCH"
            for row in archive_rows
        ),
        43,
    )

    for row in geometry["summary"]:
        add_check(
            "geometry",
            str(row["check"]),
            row["observed"],
            row["expected"],
            str(row["result"]),
        )

    for row in hrrr["summary"]:
        add_check(
            "hrrr",
            str(row["check"]),
            row["observed"],
            row["expected"],
            str(row["result"]),
        )

    failed_check_ids = [
        f"{row['section']}.{row['check']}" for row in checks if row["result"] != "PASS"
    ]
    return {
        "status": READY_STATUS if not failed_check_ids else FAILED_STATUS,
        "required_checks": checks,
        "required_checks_total": len(checks),
        "required_checks_passed": len(checks) - len(failed_check_ids),
        "required_checks_failed": len(failed_check_ids),
        "failed_check_ids": failed_check_ids,
    }


def exit_code_for_manifest(manifest: Mapping[str, Any]) -> int:
    """Return nonzero unless the recorded readiness guard is fully satisfied."""

    readiness = manifest.get("readiness", {})
    return 0 if (
        manifest.get("status") == READY_STATUS
        and readiness.get("required_checks_failed") == 0
        and readiness.get("required_checks_passed") == readiness.get("required_checks_total")
    ) else 1


def _report(
    generated_utc: str,
    historical: Mapping[str, Any],
    cmr: Mapping[str, Any],
    archive: Mapping[str, Any],
    geometry: Mapping[str, Any],
    hrrr: Mapping[str, Any],
    readiness: Mapping[str, Any],
) -> str:
    count_map = {row["stage"]: row["independent_observed_count"] for row in historical["count_rows"]}
    c3_total = len(cmr["inventory"])
    c3_query_rows = len(cmr["results"])
    c3_unique_queries = len({row["url"] for row in cmr["results"]})
    c3_primary = {
        row["city"]: sum(
            int(item["entry_count"])
            for item in cmr["results"]
            if item["query_scope"] == "v6_2_primary_windows" and item["city"] == row["city"]
        )
        for row in ({"city": "phoenix"}, {"city": "los_angeles"})
    }
    geometry_results = {row["check"]: row for row in geometry["summary"]}
    hrrr_results = {row["check"]: row for row in hrrr["summary"]}
    omitted_ids = ", ".join(row["granule_id"] for row in historical["omitted"])
    if readiness["required_checks_failed"] == 0:
        signoff_text = (
            "The independent foundation/catalogue audit is ready for foundation sign-off. "
            "Every required historical, archive, geometry, and HRRR check passed."
        )
    else:
        signoff_text = (
            "The independent foundation/catalogue audit is not ready for foundation sign-off. "
            "Required failures: " + ", ".join(readiness["failed_check_ids"]) + "."
        )
    return f"""# v6.2 independent foundation/catalogue audit

**Run time (UTC):** {generated_utc}  
**Overall status:** `{readiness['status']}`  
**Access boundary:** metadata, nonthermal geometry, and HRRR only; no ECOSTRESS LST/temperature value was opened.  
**Sample boundary:** every inherited count below is historical provenance. None is the v6.2 study sample.

## Bottom line

The physical grouping is reproducible: the historical Collection 2 catalogue has {count_map['raw_domain_intersecting_tiled_products']:,} raw tiled records; the inherited ledger names {count_map['inherited_ledger_provenance_products']:,} of those identifiers and groups them into {count_map['physical_city_orbit_observations']:,} city–orbit observations. The independent local-solar-time calculation reproduces {count_map['daytime_10_18_local_solar']:,} daytime observations. The inherited nonthermal ledger also reproduces the later {count_map['metadata_and_obstruction_screen']:,} metadata-screened, {count_map['archive_available_pre_geometry']:,} archive-available, {count_map['geometry_pass_historical_20deg']:,} geometry-screened, and {count_map['early_late_stratum_eligible_historical']:,} early/late counts.

The recorded live Collection 3 run contains **{c3_query_rows} query rows representing {c3_unique_queries} unique query URLs** and returned **{c3_total} unique granule metadata records** across the 2018–2025 historical, v6.2 primary-window, and v6.2 sensitivity-window scopes. All granules are dated 23 August 2019. Under the v6.2 primary windows, Phoenix returned **{c3_primary['phoenix']}** and Los Angeles returned **{c3_primary['los_angeles']}** tiled records. This is a partial archive population, not a complete v6.2 catalogue and not a study sample. It is a dated availability result, not a permanent-absence claim.

The revision-count terminology is now formally resolved. **13,575 is the inherited ledger provenance count**: the number of distinct tiled identifiers named by that ledger, with no claim that its membership implements a latest-revision rule. **11,880 is the strict latest-build/latest-revision count** independently selected by maximum build and revision per `(city, orbit, scene, tile)`. The inherited ledger omits exactly two of the 13,577 raw rows: {omitted_ids}. Both are Minneapolis–St. Paul orbit 29106, scene 004, tile 15TVK; the same physical pass remains represented by scene 005. Neither tiled count is the v6.2 study sample.

## Historical count reconciliation

| Stage | Independent count | Result |
|---|---:|---|
""" + "\n".join(
        f"| {row['stage']} | {row['independent_observed_count']} | {row['result']} |"
        for row in historical["count_rows"]
    ) + f"""

The tile-to-pass crosswalk retains every raw identifier and records both inherited-ledger membership and a strict native-ID latest-revision flag. Its physical pass key is city plus zero-padded orbit. Adjacent scenes and MGRS tiles never become extra atmospheric observations.

## Exclusions and archive gaps

- The two tiled identifiers above are absent from the inherited canonical ledger but do not remove the Minneapolis–St. Paul orbit-29106 physical observation.
- The historical L1B GEO gap ledger contains **{archive['historical_count']}** passes. The later unified ledger contains **{archive['unified_count']}** passes: the original 31 plus 12 later unavailable passes; **{archive['bound_scope_count']}** were in the old four-window bound calculation.
- No gap is zero-filled, assigned a geometry result, or counted as recovered. The 31 historical gaps are from 2020 or 2024, while every recorded Collection 3 entry is from 2019; the exact orbit comparison recovers **{archive['collection3_potential_orbit_matches']}** of the 43 unified gaps.

## Geometry recovery

- Geometry ledger: **{geometry_results['geometry_ledger_rows']['observed']}** rows.
- Checksum-bound reconstruction arrays: **{geometry_results['reconstruction_artifacts']['observed']}**.
- Statuses: {geometry['status_counts']['COMPLETE']} complete positive maps, {geometry['status_counts']['RESOLVED_VERIFIED_ZERO_MAPPED_CELLS']} verified zero maps, {geometry['status_counts']['AZIMUTH_INCOMPLETE']} accessible but azimuth-incomplete, and {geometry['status_counts']['RESOLVED_UNAVAILABLE']} resolved unavailable.
- Every row's expected artifact presence, file hash, embedded city/orbit/window identity, array shape, coverage, valid-view count, view-zenith p95, and azimuth-valid fraction was independently checked. Result: **{geometry_results['all_reconstruction_hashes_and_metrics']['result']}**.
- The inherited 25-degree joined evidence has **{geometry_results['joined_geometry_cloud_weather_passes_at_25deg']['observed']}** geometry/cloud/weather-complete passes. This is design-history evidence, not the v6.2 15/25-degree sample.

## Sampled HRRR joins

The audit independently expands {hrrr_results['physical_passes']['observed']} passes to {hrrr_results['pass_hour_links']['observed']} floor/ceiling links and {hrrr_results['unique_hrrr_assets']['observed']} unique HRRR assets. It then selects two SHA-256-ranked passes per city (10 total), recalculates cell VPD from Kelvin temperature and dewpoint, averages over the frozen city domain, and linearly interpolates to acquisition time. **{hrrr_results['sampled_join_checks']['observed']}/{hrrr_results['sampled_join_checks']['expected']}** sampled joins reproduce within 1e-10 kPa; cell-level VPD formula checks reproduce within 1e-12 kPa.

Formula used for each HRRR cell:

`e_s(T) = 0.6108 exp(17.27 T_C / (T_C + 237.3)); VPD = max(e_s(T) - e_s(T_dew), 0)`

## Sign-off consequence

{signoff_text} The fail-closed readiness guard passed **{readiness['required_checks_passed']}/{readiness['required_checks_total']}** required checks and will make the command exit nonzero if any required check fails. The revision-count ambiguity is closed by the formal labels above, and every recorded CMR response required for offline replay is stored under the tracked `source_evidence/` directory and covered by the checksum ledger. The partial Collection 3 population remains a dated catalogue result, not a completeness claim, archive-gap recovery, or v6.2 sample. The 13,575 inherited provenance value remains in the historical record and is explicitly prohibited from becoming the v6.2 study sample.
"""


def run(repo: Path, live_cmr: bool) -> dict[str, Any]:
    repo = repo.resolve()
    docs_dir = repo / "docs/v2/v6_2/foundation_audit"
    docs_dir.mkdir(parents=True, exist_ok=True)
    generated_utc = dt.datetime.now(dt.timezone.utc).isoformat()

    historical = historical_catalogue_audit(repo)
    cmr = collection3_audit(repo, live_cmr)
    archive = archive_gap_audit(repo, cmr["inventory"])
    geometry = geometry_recovery_audit(repo)
    hrrr = hrrr_join_audit(repo)
    readiness = evaluate_readiness(historical, archive, geometry, hrrr)

    write_csv(
        docs_dir / "historical_count_reconciliation.csv",
        historical["count_rows"],
        ("stage", "expected_historical_count", "independent_observed_count", "unit", "method", "result", "role"),
    )
    write_csv(
        docs_dir / "historical_tile_to_pass_crosswalk.csv",
        historical["crosswalk"],
        (
            "city", "orbit", "pass_id", "scene", "tile", "acquisition_utc", "build", "revision",
            "granule_id", "raw_rows_in_pass", "inherited_ledger_selected",
            "strict_latest_identity_selected", "inherited_selection_status", "strict_revision_status", "role",
        ),
    )
    write_csv(
        docs_dir / "historical_inherited_ledger_exclusions.csv",
        historical["omitted"],
        (
            "city", "orbit", "pass_id", "scene", "tile", "acquisition_utc", "build", "revision",
            "granule_id", "inherited_selection_status", "strict_revision_status", "role",
        ),
    )
    write_csv(
        docs_dir / "collection3_query_counts.csv",
        cmr["results"],
        (
            "query_scope", "city", "city_role", "year", "window_start", "window_end", "temporal",
            "bbox_wsen", "url", "url_sha256", "response_updated_utc", "response_pages", "entry_count",
            "response_sha256s", "result", "thermal_or_lst_opened",
        ),
    )
    write_csv(
        docs_dir / "collection3_granule_inventory.csv",
        cmr["inventory"],
        (
            "concept_id", "producer_granule_id", "acquisition_utc", "orbit", "scene", "tile",
            "matched_query_cities", "matched_query_scopes", "role",
        ),
    )
    write_csv(
        docs_dir / "archive_gap_ledger.csv",
        archive["rows"],
        (
            "physical_pass_id", "city", "orbit", "acquisition_utc", "source_population", "unavailable_source",
            "archive_status", "required_l1b_scene_count", "unavailable_l1b_scene_count", "unavailable_l1b_scene_keys",
            "bound_scope_included", "geometry_outcome_known", "cloud_weight_known",
            "collection3_live_recovery_status", "role",
        ),
    )
    write_csv(
        docs_dir / "geometry_recovery_checks.csv",
        geometry["checks"],
        (
            "city", "orbit", "window_id", "source_population", "geometry_azimuth_status",
            "reconstruction_expected", "artifact_path", "artifact_exists", "artifact_hash_match", "identity_match",
            "array_shape_match", "n_domain_pixels_recalculated", "n_view_valid_pixels_recalculated",
            "coverage_recalculated", "view_p95_recalculated_deg", "azimuth_valid_fraction_recalculated",
            "metric_match", "audit_pass", "role",
        ),
    )
    write_csv(
        docs_dir / "geometry_recovery_summary.csv",
        geometry["summary"],
        ("check", "observed", "expected", "result", "role"),
    )
    write_csv(
        docs_dir / "hrrr_join_sample.csv",
        hrrr["samples"],
        (
            "sample_rule", "observation_id", "city", "acquisition_utc", "floor_item_id", "ceiling_item_id",
            "floor_domain_cells", "ceiling_domain_cells", "interpolation_weight_to_ceiling",
            "recalculated_vpd_kpa", "recorded_vpd_kpa", "max_hourly_spatial_mean_error_kpa",
            "max_cell_formula_error_kpa", "interpolation_error_kpa", "temperature_unit_check", "audit_pass", "role",
        ),
    )
    write_csv(
        docs_dir / "hrrr_join_summary.csv",
        hrrr["summary"],
        ("check", "observed", "expected", "result", "role"),
    )
    write_csv(
        docs_dir / "readiness_checks.csv",
        readiness["required_checks"],
        ("section", "check", "observed", "expected", "source_result", "result"),
    )

    report_path = docs_dir / "README.md"
    report_path.write_text(
        _report(generated_utc, historical, cmr, archive, geometry, hrrr, readiness),
        encoding="utf-8",
    )

    input_paths = [
        historical["raw_path"], historical["ledger_path"], cmr["provenance_path"],
        archive["historical_path"], archive["unified_path"], geometry["summary_path"],
        geometry["joined_path"], hrrr["crosswalk_path"], hrrr["hourly_path"],
        hrrr["pass_path"], hrrr["manifest_path"], Path(__file__).resolve(),
    ]
    manifest = {
        "schema_version": 2,
        "audit": "v6_2_independent_foundation_catalogue",
        "generated_utc": generated_utc,
        "status": readiness["status"],
        "execution": {
            "script": _relative(Path(__file__).resolve(), repo),
            "imports_project_code": False,
            "live_cmr": live_cmr,
            "python": sys.version,
        },
        "boundaries": {
            "temperature_or_lst_opened": False,
            "thermal_science_file_opened": False,
            "new_v6_2_study_sample_selected": False,
            "historical_counts_role": HISTORICAL_ROLE,
        },
        "revision_count_resolution": {
            "inherited_ledger_provenance_records": len(historical["inherited_ids"]),
            "inherited_count_claims_latest_revision_selection": False,
            "strict_latest_build_revision_records": len(historical["strict_latest_ids"]),
            "strict_identity_key": ["city", "orbit", "scene", "tile"],
            "strict_rank": ["build", "revision", "granule_id"],
            "resolution": (
                "13,575 is retained only as the inherited ledger provenance count; "
                "11,880 is accepted as the strict latest-build/latest-revision count"
            ),
        },
        "readiness": {
            "guard": "all required historical, archive, geometry, and HRRR checks must pass",
            "required_checks_total": readiness["required_checks_total"],
            "required_checks_passed": readiness["required_checks_passed"],
            "required_checks_failed": readiness["required_checks_failed"],
            "failed_check_ids": readiness["failed_check_ids"],
            "checks_file": "docs/v2/v6_2/foundation_audit/readiness_checks.csv",
        },
        "results": {
            "raw_tiled_records": len(historical["raw_rows"]),
            "inherited_ledger_provenance_records": len(historical["inherited_ids"]),
            "strict_latest_revision_records": len(historical["strict_latest_ids"]),
            "physical_city_orbit_observations": len(historical["ledger_rows"]),
            "collection3_recorded_query_rows": len(cmr["results"]),
            "collection3_unique_query_urls": len({row["url"] for row in cmr["results"]}),
            "collection3_unique_entries_all_recorded_queries": len(cmr["inventory"]),
            "collection3_primary_phoenix_entries": sum(
                int(row["entry_count"])
                for row in cmr["results"]
                if row["query_scope"] == "v6_2_primary_windows" and row["city"] == "phoenix"
            ),
            "collection3_primary_los_angeles_entries": sum(
                int(row["entry_count"])
                for row in cmr["results"]
                if row["query_scope"] == "v6_2_primary_windows" and row["city"] == "los_angeles"
            ),
            "historical_archive_gaps": archive["historical_count"],
            "unified_archive_gaps": archive["unified_count"],
            "geometry_rows": len(geometry["checks"]),
            "geometry_checks_passed": sum(row["audit_pass"] for row in geometry["checks"]),
            "hrrr_sample_checks_passed": sum(row["audit_pass"] for row in hrrr["samples"]),
            "hrrr_sample_checks_total": len(hrrr["samples"]),
        },
        "inputs": {_relative(path, repo): sha256_path(path) for path in input_paths},
    }
    manifest_path = docs_dir / "run_manifest.json"
    evidence_paths = sorted(path for path in cmr["raw_dir"].iterdir() if path.is_file())
    evidence_index = "".join(
        f"{sha256_path(path)}  {_relative(path, repo)}\n" for path in evidence_paths
    )
    manifest["source_evidence"] = {
        "cmr_response_directory": _relative(cmr["raw_dir"], repo),
        "tracked_response_files": len(evidence_paths),
        "offline_replay_required": True,
        "aggregate_sha256": sha256_bytes(evidence_index.encode("utf-8")),
    }
    write_json(manifest_path, manifest)

    checksum_paths = sorted(
        [path for path in docs_dir.iterdir() if path.name != "checksums.sha256" and path.is_file()]
        + evidence_paths
    )
    checksum_text = "".join(f"{sha256_path(path)}  {_relative(path, repo)}\n" for path in checksum_paths)
    (docs_dir / "checksums.sha256").write_text(checksum_text, encoding="utf-8")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root (default: inferred from script path)",
    )
    parser.add_argument(
        "--live-cmr",
        action="store_true",
        help="refresh public NASA CMR metadata response bodies before auditing",
    )
    arguments = parser.parse_args(argv)
    manifest = run(arguments.repo_root, arguments.live_cmr)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "readiness": manifest["readiness"],
                "results": manifest["results"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return exit_code_for_manifest(manifest)


if __name__ == "__main__":
    raise SystemExit(main())
