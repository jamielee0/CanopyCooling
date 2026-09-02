#!/usr/bin/env python3
"""Export the frozen v6.2 Science TCC inputs directly to Google Drive.

This is a nonthermal, pre-Gate-A-safe acquisition step.  It exports the two
required Science bands for Phoenix and Los Angeles for 2019--2025, clipped to
the frozen Census urban-area geometries and kept on the product's native 30 m
Albers grid.
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
    REPO
    / "data/raw/v2/science_tcc_v2025_6"
    / "google_drive_export_manifest.json"
)

EE_PROJECT = "tree-497018"
COLLECTION = "projects/gtac-data-publish/assets/TCC/Product_Version/2025-6"
DRIVE_FOLDER_NAME = "Urban_Tree_Cooling_v6_2_raw_inputs_20260902"
DRIVE_FOLDER_ID = "1BWuKX2np0_cTVPvVpiFCQXq5Ip6whU1R"
CITIES = ("phoenix", "los_angeles")
YEARS = tuple(range(2019, 2026))
BANDS = (
    "Science_Percent_Tree_Canopy_Cover",
    "Science_Percent_Tree_Canopy_Cover_Standard_Error",
)

# Frozen native source grid, verified from the v2025-6 CONUS images.
SOURCE_CRS_WKT = (
    'PROJCS["Albers_Conical_Equal_Area", '
    'GEOGCS["WGS 84", DATUM["WGS_1984", '
    'SPHEROID["WGS 84", 6378137.0, 298.257223563, '
    'AUTHORITY["EPSG","7030"]], TOWGS84[0.0, 0.0, 0.0, 0.0, 0.0, '
    '0.0, 0.0], AUTHORITY["EPSG","6326"]], PRIMEM["Greenwich", '
    '0.0, AUTHORITY["EPSG","8901"]], UNIT["degree", '
    '0.017453292519943295], AXIS["Longitude", EAST], '
    'AXIS["Latitude", NORTH], AUTHORITY["EPSG","4326"]], '
    'PROJECTION["Albers_Conic_Equal_Area"], '
    'PARAMETER["central_meridian", -96.0], '
    'PARAMETER["latitude_of_origin", 23.0], '
    'PARAMETER["standard_parallel_1", 29.5], '
    'PARAMETER["false_easting", 0.0], '
    'PARAMETER["false_northing", 0.0], '
    'PARAMETER["standard_parallel_2", 45.5], UNIT["m", 1.0], '
    'AXIS["Easting", EAST], AXIS["Northing", NORTH]]'
)
SOURCE_TRANSFORM = [30, 0, -2361705, 0, -30, 3177525]


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


def description(city: str, year: int) -> str:
    return f"utc_v6_2_science_tcc_{city}_{year}"


def asset_id(year: int) -> str:
    return f"{COLLECTION}/TCC_v2025-6_CONUS_{year}"


def existing_tasks() -> dict[str, dict[str, Any]]:
    # Descriptions can recur after a corrected retry.  Prefer any successful
    # or active task over an older failed attempt so reruns stay idempotent.
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
        for year in YEARS:
            task_description = description(city, year)
            file_prefix = f"science_tcc_v2025-6_{city}_{year}_native30m"
            record: dict[str, Any] = {
                "city": city,
                "year": year,
                "asset_id": asset_id(year),
                "bands": list(BANDS),
                "description": task_description,
                "drive_folder_name": DRIVE_FOLDER_NAME,
                "drive_folder_id": DRIVE_FOLDER_ID,
                "file_name_prefix": file_prefix,
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

            # GeoTIFF requires one compatible sample type across bands.  The
            # source stores Science TCC as Byte and its SE as UInt16, so promote
            # both losslessly to UInt16.  The scientific values are unchanged.
            image = (
                ee.Image(asset_id(year))
                .select(list(BANDS))
                .toUint16()
                .clip(region)
            )
            task = ee.batch.Export.image.toDrive(
                image=image,
                description=task_description,
                folder=DRIVE_FOLDER_NAME,
                fileNamePrefix=file_prefix,
                region=region,
                crs=SOURCE_CRS_WKT,
                crsTransform=SOURCE_TRANSFORM,
                maxPixels=1_000_000_000,
                fileFormat="GeoTIFF",
                formatOptions={"cloudOptimized": True, "noData": 65535},
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
        "collection": COLLECTION,
        "collection_release": "v2025-6",
        "study_areas": list(CITIES),
        "years": list(YEARS),
        "required_bands": list(BANDS),
        "prohibited_band_not_exported": "NLCD_Percent_Tree_Canopy_Cover",
        "domain_path": str(DOMAIN_PATH.relative_to(REPO)),
        "domain_sha256": sha256(DOMAIN_PATH),
        "native_grid": {
            "crs_wkt": SOURCE_CRS_WKT,
            "transform": SOURCE_TRANSFORM,
            "nominal_pixel_size_m": 30,
        },
        "export_sample_type": "UInt16",
        "export_nodata": 65535,
        "type_harmonization": (
            "Source Byte cover and UInt16 standard-error bands are both exported "
            "as UInt16; this is a lossless promotion and does not alter values."
        ),
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
