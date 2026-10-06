#!/usr/bin/env python3
"""Export frozen-domain USGS 3DEP 1/3 arc-second DEMs to Google Drive.

The Earth Engine source is the official USGS 3DEP 10 m seamless collection.
Only the nonthermal elevation band is accessed.  The export remains on each
city's source-aligned NAD83 1/3 arc-second grid.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ee


REPO = Path(__file__).resolve().parents[1]
DOMAIN_PATH = REPO / "data/raw/v2/domains/census_urban_areas.geojson"
MANIFEST_PATH = (
    REPO / "data/raw/v2/usgs_3dep_10m" / "google_drive_export_manifest.json"
)
EE_PROJECT = "tree-497018"
COLLECTION = "USGS/3DEP/10m_collection"
BAND = "elevation"
DRIVE_FOLDER_NAME = "Urban_Tree_Cooling_v6_2_raw_inputs_20260902"
DRIVE_FOLDER_ID = "1BWuKX2np0_cTVPvVpiFCQXq5Ip6whU1R"
CITIES = ("phoenix", "los_angeles")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_domains(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text())
    result: dict[str, dict[str, Any]] = {}
    for feature in payload.get("features", []):
        city = feature.get("properties", {}).get("city")
        if city in CITIES:
            result[city] = feature["geometry"]
    missing = sorted(set(CITIES).difference(result))
    if missing:
        raise RuntimeError(f"Missing frozen domain geometries: {missing}")
    return result


def description(city: str) -> str:
    return f"utc_v6_2_usgs_3dep_10m_{city}"


def existing_tasks() -> dict[str, dict[str, Any]]:
    rank = {
        "COMPLETED": 5,
        "RUNNING": 4,
        "READY": 3,
        "CANCEL_REQUESTED": 2,
        "FAILED": 1,
        "CANCELLED": 0,
    }
    result: dict[str, dict[str, Any]] = {}
    for item in ee.data.getTaskList():
        key = item.get("description", "")
        if not key:
            continue
        if key not in result or rank.get(item.get("state", ""), -1) > rank.get(
            result[key].get("state", ""), -1
        ):
            result[key] = item
    return result


def export_all(*, dry_run: bool) -> dict[str, Any]:
    domains = load_domains(DOMAIN_PATH)
    prior = existing_tasks() if not dry_run else {}
    records: list[dict[str, Any]] = []

    for city in CITIES:
        region = ee.Geometry(domains[city], proj="EPSG:4326", geodesic=False)
        collection = ee.ImageCollection(COLLECTION).filterBounds(region).sort("system:index")
        source_ids = collection.aggregate_array("system:index").getInfo()
        if not source_ids:
            raise RuntimeError(f"No 3DEP source tiles intersect {city}")
        projection = collection.first().select(BAND).projection().getInfo()
        if projection.get("crs") != "EPSG:4269":
            raise RuntimeError(f"Unexpected 3DEP source CRS for {city}: {projection}")

        task_description = description(city)
        file_prefix = f"usgs_3dep_10m_{city}_frozen_census_domain"
        record: dict[str, Any] = {
            "city": city,
            "source_collection": COLLECTION,
            "source_tile_ids": source_ids,
            "band": BAND,
            "description": task_description,
            "drive_folder_name": DRIVE_FOLDER_NAME,
            "drive_folder_id": DRIVE_FOLDER_ID,
            "file_name_prefix": file_prefix,
            "native_projection": projection,
        }

        old = prior.get(task_description)
        if old and old.get("state") in {"READY", "RUNNING", "COMPLETED"}:
            record.update(
                {
                    "action": "reused_existing_task",
                    "task_id": old.get("id"),
                    "state_at_manifest": old.get("state"),
                }
            )
            records.append(record)
            continue

        if dry_run:
            record.update({"action": "dry_run", "state_at_manifest": "NOT_STARTED"})
            records.append(record)
            continue

        image = collection.select(BAND).mosaic().toFloat().clip(region)
        task = ee.batch.Export.image.toDrive(
            image=image,
            description=task_description,
            folder=DRIVE_FOLDER_NAME,
            fileNamePrefix=file_prefix,
            region=region,
            crs=projection["crs"],
            crsTransform=projection["transform"],
            maxPixels=1_000_000_000,
            fileFormat="GeoTIFF",
            formatOptions={"cloudOptimized": True, "noData": -9999},
        )
        task.start()
        status = task.status()
        record.update(
            {
                "action": "started_new_task",
                "task_id": status.get("id"),
                "state_at_manifest": status.get("state"),
            }
        )
        records.append(record)

    manifest = {
        "schema_version": "1.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "pre_gate_a_nonthermal": True,
        "earth_engine_project": EE_PROJECT,
        "source_collection": COLLECTION,
        "source_catalog_snapshot_availability_end": "2022-05-04",
        "band": BAND,
        "units": "metres",
        "nominal_resolution": "1/3 arc-second (approximately 10 m)",
        "domain_path": str(DOMAIN_PATH.relative_to(REPO)),
        "domain_sha256": sha256(DOMAIN_PATH),
        "drive_folder_name": DRIVE_FOLDER_NAME,
        "drive_folder_id": DRIVE_FOLDER_ID,
        "dry_run": dry_run,
        "exports": records,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    ee.Initialize(project=EE_PROJECT)
    manifest = export_all(dry_run=args.dry_run)
    states: dict[str, int] = {}
    for item in manifest["exports"]:
        state = item["state_at_manifest"]
        states[state] = states.get(state, 0) + 1
    print(
        json.dumps(
            {
                "manifest": str(MANIFEST_PATH),
                "exports": len(manifest["exports"]),
                "states": states,
                "drive_folder_id": DRIVE_FOLDER_ID,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
