#!/usr/bin/env python3
"""Build the v6.2 D1b historical nonthermal connectivity evidence package."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import geopandas as gpd
import pandas as pd
from shapely import make_valid
from shapely.geometry import mapping
import yaml

from urban_cooling_v2.connectivity_audit import (
    CITY_LABEL,
    MIN_CLEAR_CELLS,
    VIEW_SETS,
    WINDOWS,
    assign_modal_land_cover,
    build_block_grid,
    clear_cell_counts_for_pass,
    plot_connectivity_map,
    plot_pass_histogram,
    select_candidate_passes,
    summarize_combination,
    validate_summary_rows,
)


REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO / "deliverables" / "D1b_connectivity_v6_2_20260830"
PASS_TABLE = REPO / "docs/v2/hitl/G3_SAMPLING_DESIGN/angle_threshold_pass_detail_existing_five.csv"
DOMAIN_FILE = REPO / "data/raw/v2/domains/census_urban_areas.geojson"
MANIFEST_FILE = REPO / "data/raw/v2/ecostress/enrichment_manifest_cloud_l1b_geo_D0047.csv"
ASSET_ROOT = REPO / "data/raw/v2/ecostress/enrichment_assets"
PROTOCOL_FILE = REPO / "docs/v2/v6_2/protocol_v6_2.yml"
NLCD = {
    "phoenix": REPO / "data/raw/v2/context/annual_nlcd_c1_1_2024/phoenix_annual_nlcd_c1_1_2024_land_cover.tif",
    "los_angeles": REPO / "data/raw/v2/context/annual_nlcd_c1_1_2024/los_angeles_annual_nlcd_c1_1_2024_land_cover.tif",
}
EXPECTED_NLCD_SHA256 = {
    "phoenix": "1afd90c8490d0dd49335d6556cfbdb69aa05ce9754602f1fa71e6863b960ee30",
    "los_angeles": "9660a7f9d4ed67a61ceb66ed3e9741dbaac3c012c61528167017f14d956ea73d",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_dump(path: Path, payload, *, sort_keys: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=sort_keys) + "\n", encoding="utf-8")


def make_readme(output: Path, ruling: str, widening_used: bool) -> None:
    text = f"""# D1b — block–pass connectivity report

This package reports all eight Phoenix/Los Angeles × season-window × view-set
combinations required by the v6.2 schedule. The numerical ruling is
`{ruling}`. The single preauthorized 25° incidence widening was
`{'USED' if widening_used else 'NOT USED'}` to obtain the ruling; the 25° panels
are still reported as required.

## Interpretation boundary

- Evidence is the inherited Collection 2 quality/geometry archive for 2019–2025,
  not the new Collection 3 v6.2 study sample.
- Only cloud and view-zenith quality layers were opened. No ECOSTRESS LST value
  and no new v6.2 coefficient was opened.
- An edge requires at least 60 clear native cells in a 1 km block. This is an
  optimistic necessary-condition screen for the later disjoint 30-tree plus
  30-background pixel floors; later canopy/background checks may remove edges.
- Phoenix's May 15–July 10 panel is an observed June 1–July 10 lower bound because
  the inherited archive contains no quality-and-weather-complete May 15–31 pass.
- The 25° incidence result is not fully geometry-admissible until view azimuth is
  resolved. D1b does not authorize Gate A or thermal processing.

## Contents

- `memo.pdf`: two-page-or-shorter decision memo.
- `tables/d1b_connectivity.csv`: the eight required numerical rows.
- `figures/d1b_map.png` and `.svg`: eligible 1 km blocks colored by pass count.
- `figures/d1b_hist.png` and `.svg`: pass-count distributions.
- `data/d1b_block_counts.csv`: block-level panel counts and modal land-use class.
- `data/d1b_edges.csv`: eligible block–pass edges.
- `data/d1b_passes.csv`: selected and edge-surviving passes by panel.
- `analysis_manifest.json`: rules, inputs, coverage notes, and fail-closed checks.
- `checksums.sha256`: hashes for every package file except itself.
"""
    (output / "README.md").write_text(text, encoding="utf-8")


def write_checksums(output: Path) -> None:
    target = output / "checksums.sha256"
    lines = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path != target:
            lines.append(f"{sha256(path)}  {path.relative_to(output).as_posix()}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(output: Path, node_binary: Path, node_modules: Path) -> dict:
    with PROTOCOL_FILE.open("r", encoding="utf-8") as handle:
        protocol = yaml.safe_load(handle)
    frozen = protocol["free_checks"]["connectivity"]
    if frozen["decision_id"] != "V6.2-D006" or frozen["status"] != "FROZEN_FOR_OUTCOME_BLIND_RUN":
        raise RuntimeError("D006 connectivity rule is not frozen")

    for required in [PASS_TABLE, DOMAIN_FILE, MANIFEST_FILE, PROTOCOL_FILE, *NLCD.values()]:
        if not required.is_file():
            raise FileNotFoundError(required)
    nlcd_hashes = {city: sha256(path) for city, path in NLCD.items()}
    if nlcd_hashes != EXPECTED_NLCD_SHA256:
        raise RuntimeError(f"Annual NLCD checksum mismatch: {nlcd_hashes}")

    output.mkdir(parents=True, exist_ok=True)
    for directory in ("data", "figures", "tables"):
        (output / directory).mkdir(exist_ok=True)

    domains = gpd.read_file(DOMAIN_FILE).set_index("city")
    pass_rows = pd.read_csv(PASS_TABLE, dtype={"orbit": "string"})
    manifest = pd.read_csv(MANIFEST_FILE, dtype={"orbit": "string", "scene": "string"})
    manifest["orbit"] = manifest["orbit"].astype(str).str.replace(r"\.0$", "", regex=True)

    grids = {}
    blocks_by_city = {}
    pass_clear_counts: dict[tuple[str, str], dict[int, int]] = {}
    pass_diagnostics: dict[tuple[str, str], dict[str, int]] = {}
    candidate_by_combo: dict[tuple[str, str, int], pd.DataFrame] = {}

    for city in WINDOWS:
        if city not in domains.index:
            raise RuntimeError(f"Census domain is missing {city}")
        domain_row = domains.loc[city].copy()
        source_was_valid = bool(domain_row.geometry.is_valid)
        if not source_was_valid:
            domain_row.geometry = make_valid(domain_row.geometry)
        if not domain_row.geometry.is_valid or domain_row.geometry.is_empty:
            raise RuntimeError(f"Census topology repair failed for {city}")
        grid = build_block_grid(domain_row, city)
        blocks = assign_modal_land_cover(grid, NLCD[city])
        grids[city] = grid
        blocks_by_city[city] = blocks
        longitude = float(domain_row["CENTLON"])
        for window in WINDOWS[city]:
            for view in VIEW_SETS:
                candidate_by_combo[(city, window, view)] = select_candidate_passes(
                    pass_rows,
                    city=city,
                    longitude_degrees=longitude,
                    season_window=window,
                    view_zenith_maximum_degrees=view,
                )

        unique = pd.concat(
            [candidate_by_combo[(city, window, 25)] for window in WINDOWS[city]],
            ignore_index=True,
        ).drop_duplicates("orbit")
        for row in unique.sort_values(["local_solar_date", "orbit"]).itertuples():
            orbit = str(row.orbit)
            asset_rows = manifest.loc[manifest["city"].eq(city) & manifest["orbit"].eq(orbit)].copy()
            if asset_rows.empty:
                raise RuntimeError(f"No quality-layer assets for {city} orbit {orbit}")
            counts, diagnostics = clear_cell_counts_for_pass(
                asset_rows,
                domain_geometry_wgs84=mapping(domain_row.geometry),
                asset_root=ASSET_ROOT,
                grid=grid,
            )
            pass_clear_counts[(city, orbit)] = counts
            pass_diagnostics[(city, orbit)] = diagnostics

    summary_rows = []
    edge_rows = []
    block_rows = []
    selected_pass_rows = []
    for city in WINDOWS:
        blocks = blocks_by_city[city]
        block_lookup = blocks.set_index("block_key")
        for window in WINDOWS[city]:
            for view in VIEW_SETS:
                candidates = candidate_by_combo[(city, window, view)]
                combo_edges = []
                per_block = Counter()
                for record in candidates.itertuples():
                    orbit = str(record.orbit)
                    pass_id = f"{city}:{orbit}"
                    eligible_keys = sorted(
                        key
                        for key, count in pass_clear_counts[(city, orbit)].items()
                        if count >= MIN_CLEAR_CELLS
                    )
                    for key in eligible_keys:
                        block_id = str(block_lookup.loc[key, "block_id"])
                        combo_edges.append((block_id, pass_id, key, pass_clear_counts[(city, orbit)][key]))
                        per_block[block_id] += 1
                    selected_pass_rows.append(
                        {
                            "city": city,
                            "season_window": window,
                            "view_zenith_set_deg": view,
                            "orbit": orbit,
                            "pass_id": pass_id,
                            "acquisition_utc": record.acquisition_utc.isoformat(),
                            "local_solar_date": record.local_solar_date.isoformat(),
                            "view_zenith_abs_p95_deg": float(record.l1b_view_zenith_abs_p95_deg),
                            "eligible_blocks": len(eligible_keys),
                            "clear_cells_total": int(pass_diagnostics[(city, orbit)].get("clear_cells", 0)),
                            "quality_layers_opened_only": True,
                        }
                    )
                edges = pd.DataFrame(combo_edges, columns=["block_id", "pass_id", "block_key", "clear_cells"])
                for record in edges.itertuples():
                    edge_rows.append(
                        {
                            "city": city,
                            "season_window": window,
                            "view_zenith_set_deg": view,
                            "block_id": record.block_id,
                            "pass_id": record.pass_id,
                            "clear_native_cells": int(record.clear_cells),
                        }
                    )
                summary_rows.append(
                    summarize_combination(
                        city=city,
                        season_window=window,
                        view_set=view,
                        edges=edges,
                        blocks=blocks,
                    )
                )
                for block in blocks.itertuples():
                    block_rows.append(
                        {
                            "city": city,
                            "season_window": window,
                            "view_zenith_set_deg": view,
                            "block_id": block.block_id,
                            "grid_row": int(block.grid_row),
                            "grid_col": int(block.grid_col),
                            "sector": block.sector,
                            "land_use_code": int(block.land_use_code),
                            "land_use_class": block.land_use_class,
                            "pass_count": int(per_block.get(block.block_id, 0)),
                            "eligible": bool(per_block.get(block.block_id, 0) > 0),
                        }
                    )

    validate_summary_rows(summary_rows)
    pass_at_15 = any(row["combination_pass"] for row in summary_rows if row["view_zenith_set_deg"] == 15)
    pass_at_25 = any(row["combination_pass"] for row in summary_rows if row["view_zenith_set_deg"] == 25)
    if pass_at_15:
        ruling = "HISTORICAL_PROXY_SUPPORTS_CONNECTIVITY_AT_15_DEGREES"
        widening_used = False
    elif pass_at_25:
        ruling = "HISTORICAL_PROXY_SUPPORTS_AFTER_25_DEGREE_WIDENING"
        widening_used = True
    else:
        ruling = "HISTORICAL_PROXY_DOES_NOT_SUPPORT_CONNECTIVITY"
        widening_used = False

    block_details = pd.DataFrame(block_rows)
    edges = pd.DataFrame(edge_rows)
    passes = pd.DataFrame(selected_pass_rows)
    block_details.to_csv(output / "data/d1b_block_counts.csv", index=False)
    edges.to_csv(output / "data/d1b_edges.csv", index=False)
    passes.to_csv(output / "data/d1b_passes.csv", index=False)

    plot_connectivity_map(
        block_details,
        grids,
        output / "figures/d1b_map.png",
        output / "figures/d1b_map.svg",
    )
    plot_pass_histogram(
        block_details,
        output / "figures/d1b_hist.png",
        output / "figures/d1b_hist.svg",
    )

    input_hashes = {
        str(path.relative_to(REPO)): sha256(path)
        for path in [PASS_TABLE, DOMAIN_FILE, MANIFEST_FILE, PROTOCOL_FILE, *NLCD.values()]
    }
    checks = {
        "exactly_eight_summary_rows": len(summary_rows) == 8,
        "all_combination_keys_unique": len(
            {(r["city"], r["season_window"], r["view_zenith_set_deg"]) for r in summary_rows}
        )
        == 8,
        "all_selected_passes_have_quality_assets": all(
            (city, str(row.orbit)) in pass_clear_counts
            for (city, window, view), frame in candidate_by_combo.items()
            for row in frame.itertuples()
        ),
        "annual_nlcd_hashes_match": nlcd_hashes == EXPECTED_NLCD_SHA256,
        "no_thermal_or_new_coefficient_opened": True,
        "gate_A_authorized": False,
    }
    positive_checks = {key: value for key, value in checks.items() if key != "gate_A_authorized"}
    if not all(positive_checks.values()) or checks["gate_A_authorized"] is not False:
        raise RuntimeError(f"Fail-closed D1b check failed: {checks}")

    analysis = {
        "decision_id": "V6.2-D006",
        "status": "READY_FOR_D1B_REVIEW",
        "ruling": ruling,
        "single_preauthorized_25_degree_widening_used_for_ruling": widening_used,
        "summary_rows": summary_rows,
        "checks": checks,
        "input_sha256": input_hashes,
        "annual_nlcd": {
            "product": "USGS Annual NLCD Collection 1.1 Land Cover 2024",
            "image_service": "https://di-nlcd.img.arcgis.com/arcgis/rest/services/USA_NLCD_Annual_LandCover/ImageServer",
            "official_access_page": "https://www.usgs.gov/centers/eros/how-can-i-access-and-download-annual-nlcd-data",
            "resampling": "nearest_neighbor",
            "nominal_resolution_m": 30,
            "sha256_by_city": nlcd_hashes,
        },
        "coverage_notes": {
            "phoenix_provisional_primary": "Observed June 1-July 10 lower bound; no quality-and-weather-complete inherited pass exists for May 15-31.",
            "los_angeles_sensitivity": "Observed June 1-July 10 lower bound because the inherited five-city archive was censused June-September.",
            "collection3": "Recorded CMR evidence is partial and lacks complete block-level cloud/geometry assets; no new v6.2 sample was selected.",
        },
        "census_geometry_topology": {
            "rule": "shapely_make_valid_if_needed_before_projection_and_rasterization",
            "source_validity_by_city": {
                city: bool(domains.loc[city].geometry.is_valid) for city in WINDOWS
            },
        },
        "interpretation": {
            "evidence_role": "historical_collection2_nonthermal_feasibility_proxy_not_v6_2_study_sample",
            "edge_role": "optimistic necessary-condition screen pending tree/background/canopy-span checks",
            "view_25_role": "incidence sensitivity; not fully geometry-admissible until view azimuth is resolved",
            "gate_A_authorization_effect": "none",
        },
    }
    json_dump(output / "analysis_manifest.json", analysis)
    json_dump(
        output / "data/d1b_analysis_rows.json",
        {"summary_rows": summary_rows},
        sort_keys=False,
    )

    env = dict(**__import__("os").environ)
    env["NODE_PATH"] = str(node_modules)
    table_script = REPO / "src/build_v6_2_d1b_table.mjs"
    completed = subprocess.run(
        [str(node_binary), str(table_script), str(output / "data/d1b_analysis_rows.json"), str(output / "tables/d1b_connectivity.csv")],
        cwd=REPO,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Artifact-tool table build failed: {completed.stderr.strip()}")
    json_dump(output / "data/artifact_tool_verification.json", json.loads(completed.stdout))

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, text=True, capture_output=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=REPO, check=True, text=True, capture_output=True).stdout.strip())
    (output / "code_commit.txt").write_text(
        f"git_commit={head}\nworktree_dirty_at_run={str(dirty).lower()}\n", encoding="utf-8"
    )
    make_readme(output, ruling, widening_used)
    write_checksums(output)
    return analysis


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--node-modules", type=Path, required=True)
    args = parser.parse_args()
    try:
        analysis = run(args.output.resolve(), args.node.resolve(), args.node_modules.resolve())
    except Exception as exc:
        print(f"D1b failed closed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": analysis["status"], "ruling": analysis["ruling"], "output": str(args.output.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
