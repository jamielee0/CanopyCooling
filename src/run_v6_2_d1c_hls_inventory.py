#!/usr/bin/env python3
"""Build a public, outcome-blind HLS V2 metadata inventory for D1c.

This command contacts NASA CMR but never opens an HLS image, an optical index,
an ECOSTRESS LST value, or a v6.2 coefficient.  Protected-asset authentication
is intentionally reserved for the separate QA download step.
"""

from __future__ import annotations

import argparse
import csv
from datetime import timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from urban_cooling_v2.connectivity_audit import select_candidate_passes
from urban_cooling_v2.hls_cmr_inventory import (
    PRODUCTS,
    cmr_query,
    geometry_bbox,
    pair_candidate_passes,
    parse_cmr_item,
    selected_asset_plan,
    sha256,
    summarize_strata,
    utc,
)


REPO = Path(__file__).resolve().parents[1]
PASS_TABLE = REPO / "docs/v2/hitl/G3_SAMPLING_DESIGN/angle_threshold_pass_detail_existing_five.csv"
DOMAIN_FILE = REPO / "data/raw/v2/domains/census_urban_areas.geojson"
DEFAULT_OUTPUT = REPO / "deliverables/D1c_hls_inventory_v6_2_20260902"
WINDOWS = ("provisional_primary", "sensitivity")
CITIES = ("phoenix", "los_angeles")


def json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def csv_write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path}")
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            encoded = {
                key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
                for key, value in row.items()
            }
            writer.writerow(encoded)


def domains() -> dict[str, dict[str, Any]]:
    payload = json.loads(DOMAIN_FILE.read_text(encoding="utf-8"))
    result = {}
    for feature in payload["features"]:
        city = str(feature["properties"]["city"])
        if city in CITIES:
            result[city] = feature
    if set(result) != set(CITIES):
        raise ValueError(f"Missing required domains: {sorted(set(CITIES).difference(result))}")
    return result


def candidate_rows(features: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = pd.read_csv(PASS_TABLE, dtype={"orbit": "string"})
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for city in CITIES:
        longitude = float(features[city]["properties"]["CENTLON"])
        for window in WINDOWS:
            frame = select_candidate_passes(
                rows,
                city=city,
                longitude_degrees=longitude,
                season_window=window,
                view_zenith_maximum_degrees=15,
            )
            for row in frame.itertuples(index=False):
                timestamp = utc(row.acquisition_utc)
                key = (city, window, str(row.orbit), timestamp.isoformat())
                if key in seen:
                    continue
                seen.add(key)
                result.append(
                    {
                        "city": city,
                        "year": int(timestamp.year),
                        "season_window": window,
                        "thermal_pass_id": f"{city}:{row.orbit}:{timestamp.strftime('%Y%m%dT%H%M%S')}",
                        "thermal_orbit": str(row.orbit),
                        "thermal_acquisition_utc": timestamp.isoformat(),
                    }
                )
    return sorted(
        result,
        key=lambda row: (
            row["city"],
            row["year"],
            row["season_window"],
            row["thermal_acquisition_utc"],
        ),
    )


def write_checksums(output: Path) -> None:
    target = output / "checksums.txt"
    lines = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path != target:
            lines.append(f"{sha256(path)}  {path.relative_to(output).as_posix()}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(output: Path) -> dict[str, Any]:
    features = domains()
    candidates = candidate_rows(features)
    raw_dir = output / "data/cmr_raw"
    normalized: list[dict[str, Any]] = []
    queries: list[dict[str, Any]] = []

    for city in CITIES:
        city_candidates = [row for row in candidates if row["city"] == city]
        bbox = geometry_bbox(features[city]["geometry"])
        for year in range(2019, 2026):
            year_candidates = [row for row in city_candidates if row["year"] == year]
            if not year_candidates:
                continue
            times = [utc(row["thermal_acquisition_utc"]) for row in year_candidates]
            start = min(times) - timedelta(days=15)
            end = max(times) + timedelta(days=15)
            for sensor, definition in PRODUCTS.items():
                query, items = cmr_query(
                    collection_concept_id=str(definition["collection_concept_id"]),
                    bbox=bbox,
                    start=start,
                    end=end,
                )
                query.update({"city": city, "year": year, "sensor": sensor})
                raw_path = raw_dir / f"{city}_{year}_{sensor.replace('.', '_')}.json"
                json_write(raw_path, {"query": query, "items": items})
                query["raw_response_sha256"] = sha256(raw_path)
                query["raw_response_path"] = str(raw_path.relative_to(output))
                queries.append(query)
                for item in items:
                    record = parse_cmr_item(
                        item,
                        sensor=sensor,
                        city=city,
                        city_geometry=features[city]["geometry"],
                    )
                    if record["domain_geometry_intersects"]:
                        normalized.append(record)

    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in normalized:
        unique[(row["city"], row["sensor"], row["optical_acquisition_id"])] = row
    acquisitions = sorted(
        unique.values(),
        key=lambda row: (row["city"], row["sensor"], row["source_time"], row["optical_acquisition_id"]),
    )
    pairs = pair_candidate_passes(candidates, acquisitions)
    strata = summarize_strata(pairs)
    plan = selected_asset_plan(pairs, acquisitions)

    json_write(output / "analysis_manifest.json", {
        "status": "CATALOGUE_TIMING_INVENTORY_COMPLETE_REQUIRES_FMASK_QA",
        "outcome_access": False,
        "optical_asset_access": False,
        "new_v6_2_coefficients_viewed": False,
        "cities": list(CITIES),
        "years": list(range(2019, 2026)),
        "sensors": list(PRODUCTS),
        "candidate_pass_window_rows": len(candidates),
        "cmr_queries": len(queries),
        "domain_intersecting_granules": len(acquisitions),
        "pair_rows": len(pairs),
        "pair_rows_with_catalogue_match": sum(row["catalogue_pair_available"] for row in pairs),
        "download_plan_granules": len(plan),
        "all_download_plan_urls_present": all(row["all_required_urls_present"] for row in plan),
        "input_sha256": {
            str(PASS_TABLE.relative_to(REPO)): sha256(PASS_TABLE),
            str(DOMAIN_FILE.relative_to(REPO)): sha256(DOMAIN_FILE),
        },
        "interpretation": (
            "Catalogue pairs establish timing potential only. Fmask/QA must be opened before any "
            "pair is called usable, and final antecedent/future exposures require separate raw-HLS builds."
        ),
    })
    json_write(output / "data/cmr_queries.json", queries)
    json_write(output / "data/hls_acquisitions.json", acquisitions)
    json_write(output / "data/hls_pair_rows.json", pairs)
    json_write(output / "data/hls_download_plan.json", plan)
    csv_write(output / "tables/hls_acquisitions.csv", [
        {key: value for key, value in row.items() if key not in ("footprint", "assets")}
        | {"asset_names": sorted(row["assets"])}
        for row in acquisitions
    ])
    csv_write(output / "tables/hls_pair_rows.csv", pairs)
    csv_write(output / "tables/hls_strata.csv", strata)
    csv_write(output / "tables/hls_fmask_download_plan.csv", [
        {
            "city": row["city"],
            "sensor": row["sensor"],
            "optical_acquisition_id": row["optical_acquisition_id"],
            "source_time": row["source_time"],
            "mgrs_tile": row["mgrs_tile"],
            "cloud_coverage_percent": row["cloud_coverage_percent"],
            "fmask_url": row["fmask_url"],
            "all_required_urls_present": row["all_required_urls_present"],
        }
        for row in plan
    ])
    (output / "README.md").write_text(
        "# D1c HLS V2 catalogue inventory\n\n"
        "This package queries public NASA CMR metadata for `HLSL30.002` and `HLSS30.002` "
        "around the frozen 15-degree D1b candidate thermal passes. It opens no HLS raster, "
        "optical value, ECOSTRESS LST value, or v6.2 coefficient.\n\n"
        "Catalogue-level pairs are timing potential only. The next step is to retrieve Fmask "
        "for the deduplicated selected acquisitions in `tables/hls_fmask_download_plan.csv`, "
        "measure usable urban-block coverage, and then rerun the frozen D1c rule. The inherited "
        "centered Sentinel-2 object remains prohibited as the final exposure or placebo.\n",
        encoding="utf-8",
    )
    write_checksums(output)
    return json.loads((output / "analysis_manifest.json").read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = run(args.output.resolve())
    except Exception as exc:
        print(f"HLS inventory failed closed: {exc}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
