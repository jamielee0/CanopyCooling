#!/usr/bin/env python3
"""Run the outcome-blind v6.2 D018 HLS Fmask lead-lag reassessment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import make_valid
from shapely.geometry import mapping
import yaml

from urban_cooling_v2.connectivity_audit import build_block_grid
from urban_cooling_v2.hls_fmask_lead_lag import (
    MIN_CLEAR_HLS_CELLS_PER_BLOCK,
    MIN_SHARED_USABLE_BLOCKS,
    evaluate_quality_screened_pair,
    fmask_block_counts,
    required_quality_grid_rows,
)
from urban_cooling_v2.lead_lag_feasibility import (
    confirmatory_ruling,
    plot_timing_histogram,
    validate_required_grid,
)


REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO / "deliverables/D1c_fmask_reassessment_v6_2_20260902"
PROTOCOL_FILE = REPO / "docs/v2/v6_2/protocol_v6_2.yml"
DECISION_LOG = REPO / "docs/v2/v6_2/decision_log_v6_2.md"
DOMAIN_FILE = REPO / "data/raw/v2/domains/census_urban_areas.geojson"
FMASK_MANIFEST = REPO / "data/raw/v2/hls_v2/download_manifest_fmask.json"
ACQUISITION_LEDGER = (
    REPO
    / "deliverables/D1c_hls_inventory_v6_2_20260902/data/hls_acquisitions.json"
)
CANDIDATE_PAIR_ROWS = (
    REPO / "deliverables/D1c_hls_inventory_v6_2_20260902/data/hls_pair_rows.json"
)
AUDIT_MODULE = REPO / "src/urban_cooling_v2/hls_fmask_lead_lag.py"
LEAD_LAG_MODULE = REPO / "src/urban_cooling_v2/lead_lag_feasibility.py"
TABLE_BUILDER = REPO / "src/build_v6_2_d1c_fmask_table.mjs"
MEMO_BUILDER = REPO / "src/build_v6_2_d1c_fmask_memo.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_dump(path: Path, payload: Any, *, sort_keys: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=sort_keys) + "\n", encoding="utf-8"
    )


def write_checksums(output: Path) -> None:
    target = output / "checksums.txt"
    lines = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path != target:
            lines.append(f"{sha256(path)}  {path.relative_to(output).as_posix()}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_readme(output: Path, analysis: dict[str, Any]) -> None:
    wording = (
        "kept as confirmatory"
        if analysis["ruling"] == "KEEP_CONFIRMATORY"
        else "demoted to exploratory"
    )
    text = f"""# D1c HLS-Fmask lead-lag reassessment

This package applies prospective rule `V6.2-D018` to the 149 acquired HLS V2
Fmask rasters. The temporal-specificity diagnostic is **{wording}** under the
frozen ruling `{analysis['ruling']}`.

## What was verified

- Every Fmask file matches its frozen byte count and SHA-256 manifest entry.
- Exact HLS V2 source times and unique acquisition identifiers were retained.
- A usable acquisition-block has at least 60 clear 30 m HLS cells.
- A feasible thermal-pass pair uses distinct, sensor-specific acquisitions 1-15
  days before and after the pass, has absolute-lag imbalance no greater than 3
  days, and shares at least 30 usable 1 km study blocks.
- The complete 56-row Phoenix/Los Angeles x 2019-2025 x two-window x two-sensor
  reporting grid is present.

## Interpretation boundary

This is a quality-screened timing feasibility count, not a final exposure build.
Only HLS Fmask and source metadata were opened. HLS reflectance, optical indices,
ECOSTRESS LST and new v6.2 coefficients remained unopened. The 149-file plan was
selected from the catalogue timing inventory; a failed row is conservative with
respect to un-downloaded alternative HLS pairs.

## Contents

- `memo.pdf`: superseding D1c decision memo.
- `tables/d1c_leadlag.csv`: 56 required quality-screened strata.
- `figures/d1c_timing.png` and `.svg`: verified pre/post lag histograms.
- `data/d1c_verified_pairs.json`: one record per candidate pass/window/sensor.
- `data/d1c_fmask_acquisitions.json`: per-acquisition QA coverage diagnostics.
- `analysis_manifest.json`: inputs, checks, numerical result and ruling.
- `checksums.txt`: SHA-256 for every other package file.
"""
    (output / "README.md").write_text(text, encoding="utf-8")


def _validate_and_load_manifest(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    manifest_hash = sha256(FMASK_MANIFEST)
    inventory = protocol["products"]["hls"]["pre_gate_A_local_inventory"]
    if manifest_hash != inventory["fmask_manifest_sha256"]:
        raise RuntimeError(
            f"Fmask manifest checksum mismatch: {manifest_hash}"
        )
    payload = json.loads(FMASK_MANIFEST.read_text(encoding="utf-8"))
    files = list(payload.get("files", []))
    if payload.get("asset_set") != "fmask" or len(files) != 149:
        raise RuntimeError("Frozen Fmask manifest must contain exactly 149 files")
    identities = [(row["city"], row["optical_acquisition_id"]) for row in files]
    if len(set(identities)) != 149:
        raise RuntimeError("Fmask manifest acquisition identities are not unique")
    if any(str(row.get("asset")) != "Fmask" for row in files):
        raise RuntimeError("Fmask manifest contains a non-Fmask asset")
    return files


def _validate_file(path: Path, row: dict[str, Any]) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size != int(row["bytes"]):
        raise RuntimeError(f"Fmask byte-count mismatch: {path}")
    observed = sha256(path)
    if observed != str(row["sha256"]):
        raise RuntimeError(f"Fmask SHA-256 mismatch: {path}")


def _pair_candidates(
    candidates: list[dict[str, Any]],
    acquisitions: pd.DataFrame,
    usable_blocks: dict[str, set[int]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        city = str(candidate["city"])
        sensor = str(candidate["sensor"])
        ledger = acquisitions.loc[
            acquisitions["city"].eq(city) & acquisitions["sensor"].eq(sensor)
        ].copy()
        evaluation = evaluate_quality_screened_pair(
            candidate["thermal_acquisition_utc"],
            ledger,
            usable_blocks,
            sensor=sensor,
        )
        pair = evaluation["pair"]
        result = {
            key: candidate[key]
            for key in (
                "city",
                "year",
                "season_window",
                "sensor",
                "thermal_pass_id",
                "thermal_orbit",
                "thermal_acquisition_utc",
            )
        }
        result["quality_pair_available"] = pair is not None
        result.update(
            pair
            if pair is not None
            else {
                "pre_acquisition_id": None,
                "post_acquisition_id": None,
                "pre_lag_days": None,
                "post_lag_days": None,
                "lag_imbalance_days": None,
                "shared_usable_blocks": None,
            }
        )
        result["timing_valid_pair_candidates"] = int(
            evaluation["timing_valid_pair_candidates"]
        )
        result["maximum_shared_usable_blocks_among_timing_pairs"] = int(
            evaluation["maximum_shared_usable_blocks_among_timing_pairs"]
        )
        result["failure_reason"] = evaluation["failure_reason"]
        rows.append(result)
    return rows


def run_analysis(output: Path, node_binary: Path, node_modules: Path) -> dict[str, Any]:
    with PROTOCOL_FILE.open("r", encoding="utf-8") as handle:
        protocol = yaml.safe_load(handle)
    frozen = protocol["free_checks"]["lead_lag_feasibility"]["fmask_reassessment"]
    if (
        frozen.get("decision_id") != "V6.2-D018"
        or frozen.get("status") != "FROZEN_BEFORE_HLS_FMASK_VALUE_ACCESS"
    ):
        raise RuntimeError("D018 Fmask reassessment rule is not prospectively frozen")
    for required in (
        PROTOCOL_FILE,
        DECISION_LOG,
        DOMAIN_FILE,
        FMASK_MANIFEST,
        ACQUISITION_LEDGER,
        CANDIDATE_PAIR_ROWS,
        AUDIT_MODULE,
        LEAD_LAG_MODULE,
        TABLE_BUILDER,
        MEMO_BUILDER,
    ):
        if not required.is_file():
            raise FileNotFoundError(required)

    output.mkdir(parents=True, exist_ok=True)
    for directory in ("data", "figures", "tables"):
        (output / directory).mkdir(exist_ok=True)

    manifest_rows = _validate_and_load_manifest(protocol)
    ledger_rows = json.loads(ACQUISITION_LEDGER.read_text(encoding="utf-8"))
    ledger_lookup = {
        (str(row["city"]), str(row["optical_acquisition_id"])): row
        for row in ledger_rows
    }
    domains = gpd.read_file(DOMAIN_FILE).set_index("city")
    grids = {}
    domain_geometries = {}
    for city in ("phoenix", "los_angeles"):
        if city not in domains.index:
            raise RuntimeError(f"Census domain is missing {city}")
        row = domains.loc[city].copy()
        if not row.geometry.is_valid:
            row.geometry = make_valid(row.geometry)
        if row.geometry.is_empty or not row.geometry.is_valid:
            raise RuntimeError(f"Census topology repair failed for {city}")
        grids[city] = build_block_grid(row, city)
        domain_geometries[city] = mapping(row.geometry)

    acquisition_rows: list[dict[str, Any]] = []
    usable_blocks: dict[str, set[int]] = {}
    verified_files = 0
    for manifest_row in manifest_rows:
        path = REPO / str(manifest_row["local_path"])
        _validate_file(path, manifest_row)
        verified_files += 1
        city = str(manifest_row["city"])
        identity = (city, str(manifest_row["optical_acquisition_id"]))
        source = ledger_lookup.get(identity)
        if source is None:
            raise RuntimeError(f"Acquisition is absent from source ledger: {identity}")
        for field in ("sensor", "source_time", "mgrs_tile"):
            if str(manifest_row[field]) != str(source[field]):
                raise RuntimeError(f"Manifest/source-ledger {field} mismatch: {identity}")
        counts, diagnostics = fmask_block_counts(
            path,
            mgrs_tile=str(manifest_row["mgrs_tile"]),
            domain_geometry_wgs84=domain_geometries[city],
            grid=grids[city],
        )
        selected_blocks = {
            int(key)
            for key, count in counts.items()
            if int(count) >= MIN_CLEAR_HLS_CELLS_PER_BLOCK
        }
        usable_blocks[str(manifest_row["optical_acquisition_id"])] = selected_blocks
        acquisition_rows.append(
            {
                "city": city,
                "sensor": str(manifest_row["sensor"]),
                "optical_acquisition_id": str(manifest_row["optical_acquisition_id"]),
                "source_time": str(manifest_row["source_time"]),
                "mgrs_tile": str(manifest_row["mgrs_tile"]),
                "manifest_bytes": int(manifest_row["bytes"]),
                "manifest_sha256": str(manifest_row["sha256"]),
                **diagnostics,
                "minimum_clear_cells_per_usable_block": MIN_CLEAR_HLS_CELLS_PER_BLOCK,
            }
        )

    acquisitions = pd.DataFrame(manifest_rows)[
        ["city", "sensor", "optical_acquisition_id", "source_time", "mgrs_tile"]
    ].copy()
    candidate_rows = json.loads(CANDIDATE_PAIR_ROWS.read_text(encoding="utf-8"))
    candidate_keys = [
        (
            row["city"],
            row["year"],
            row["season_window"],
            row["sensor"],
            row["thermal_pass_id"],
        )
        for row in candidate_rows
    ]
    if len(candidate_rows) != 110 or len(set(candidate_keys)) != 110:
        raise RuntimeError("D1c candidate pair rows must contain 110 unique records")
    verified_pairs = _pair_candidates(candidate_rows, acquisitions, usable_blocks)
    table_rows = required_quality_grid_rows(verified_pairs)
    validate_required_grid(table_rows)
    ruling = confirmatory_ruling(
        table_rows,
        source_dates_available=True,
        acquisition_identifiers_available=True,
    )

    selected_pairs = [row for row in verified_pairs if row["quality_pair_available"]]
    pre_lags = [float(row["pre_lag_days"]) for row in selected_pairs]
    post_lags = [float(row["post_lag_days"]) for row in selected_pairs]
    plot_timing_histogram(
        pre_lags,
        post_lags,
        output / "figures/d1c_timing.png",
        output / "figures/d1c_timing.svg",
        footer_note=(
            "Exact HLS V2 source times; pairs require >=30 common QA-usable blocks. "
            "No reflectance, optical index, thermal outcome, or coefficient was opened."
        ),
    )

    checks = {
        "fmask_manifest_hash_matches_protocol": True,
        "all_149_fmask_files_match_manifest": verified_files == 149,
        "every_selected_acquisition_has_exact_source_time_and_identifier": all(
            row["source_time"] and row["optical_acquisition_id"] for row in acquisition_rows
        ),
        "candidate_pass_window_sensor_rows_110": len(verified_pairs) == 110,
        "required_hls_rows_56": len(table_rows) == 56,
        "all_required_grid_keys_present": True,
        "every_feasible_pair_meets_shared_block_floor": all(
            int(row["shared_usable_blocks"]) >= MIN_SHARED_USABLE_BLOCKS
            for row in selected_pairs
        ),
        "every_feasible_pair_meets_lag_imbalance": all(
            float(row["lag_imbalance_days"]) <= 3.0 for row in selected_pairs
        ),
        "reflectance_or_optical_index_opened": False,
        "thermal_or_lst_values_opened": False,
        "new_v6_2_coefficients_viewed": False,
        "gate_A_authorized": False,
    }
    positive = {
        key: value
        for key, value in checks.items()
        if key
        not in {
            "reflectance_or_optical_index_opened",
            "thermal_or_lst_values_opened",
            "new_v6_2_coefficients_viewed",
            "gate_A_authorized",
        }
    }
    prohibited_false = all(
        checks[key] is False
        for key in (
            "reflectance_or_optical_index_opened",
            "thermal_or_lst_values_opened",
            "new_v6_2_coefficients_viewed",
            "gate_A_authorized",
        )
    )
    if not all(positive.values()) or not prohibited_false:
        raise RuntimeError(f"D018 fail-closed conformance check failed: {checks}")

    by_city = {}
    for city in ("phoenix", "los_angeles"):
        city_rows = [row for row in verified_pairs if row["city"] == city]
        city_pairs = [row for row in city_rows if row["quality_pair_available"]]
        by_city[city] = {
            "candidate_pass_window_sensor_rows": len(city_rows),
            "quality_screened_pairs": len(city_pairs),
            "quality_screened_pair_share": len(city_pairs) / len(city_rows),
        }
    analysis = {
        "decision_id": "V6.2-D018",
        "status": "READY_FOR_D1C_FMASK_REASSESSMENT_REVIEW",
        "ruling": ruling,
        "temporal_specificity_status": (
            "CONFIRMATORY" if ruling == "KEEP_CONFIRMATORY" else "EXPLORATORY"
        ),
        "prior_ruling_superseded": "V6.2-D010",
        "frozen_thresholds": {
            "fmask_bits_required_zero": [1, 2, 3, 4, 5],
            "maximum_aerosol_level_bits_6_7": 2,
            "minimum_clear_hls_30m_cells_per_block": MIN_CLEAR_HLS_CELLS_PER_BLOCK,
            "minimum_shared_usable_blocks_per_pair": MIN_SHARED_USABLE_BLOCKS,
            "minimum_absolute_lag_days": 1,
            "maximum_absolute_lag_days": 15,
            "maximum_pre_post_absolute_lag_difference_days": 3,
            "minimum_confirmatory_share": 0.70,
            "maximum_acquisition_reuse_share": 0.25,
        },
        "counts": {
            "fmask_files": verified_files,
            "fmask_total_bytes": sum(int(row["manifest_bytes"]) for row in acquisition_rows),
            "acquisitions_with_at_least_30_usable_blocks": sum(
                int(row["usable_blocks"]) >= MIN_SHARED_USABLE_BLOCKS
                for row in acquisition_rows
            ),
            "candidate_pass_window_sensor_rows": len(verified_pairs),
            "quality_screened_pairs": len(selected_pairs),
            "quality_screened_pair_share": len(selected_pairs) / len(verified_pairs),
            "unique_selected_acquisition_ids": len(
                {
                    row[key]
                    for row in selected_pairs
                    for key in ("pre_acquisition_id", "post_acquisition_id")
                }
            ),
            "verified_pre_lags": len(pre_lags),
            "verified_post_lags": len(post_lags),
        },
        "by_city": by_city,
        "lag_summary_days": {
            "pre_median": float(np.median(pre_lags)) if pre_lags else None,
            "pre_p90": float(np.percentile(pre_lags, 90)) if pre_lags else None,
            "post_median": float(np.median(post_lags)) if post_lags else None,
            "post_p90": float(np.percentile(post_lags, 90)) if post_lags else None,
        },
        "table_rows": table_rows,
        "checks": checks,
        "input_sha256": {
            str(path.relative_to(REPO)): sha256(path)
            for path in (
                PROTOCOL_FILE,
                DECISION_LOG,
                DOMAIN_FILE,
                FMASK_MANIFEST,
                ACQUISITION_LEDGER,
                CANDIDATE_PAIR_ROWS,
            )
        },
        "implementation_sha256": {
            str(path.relative_to(REPO)): sha256(path)
            for path in (
                Path(__file__),
                AUDIT_MODULE,
                LEAD_LAG_MODULE,
                TABLE_BUILDER,
                MEMO_BUILDER,
            )
        },
        "interpretation": {
            "evidence_role": "quality_screened_timing_feasibility_only",
            "download_plan_scope": "149_acquisitions_selected_from_catalogue_pair_inventory",
            "failed_pair_interpretation": "conservative_with_respect_to_un_downloaded_alternatives",
            "final_antecedent_exposure": "still_requires_raw_HLS_reflectance_one_sided_build",
            "final_future_placebo": "still_requires_separate_raw_HLS_reflectance_matched_lag_build",
            "gate_A_authorization_effect": "none",
        },
    }
    json_dump(output / "analysis_manifest.json", analysis)
    json_dump(
        output / "data/d1c_fmask_acquisitions.json", acquisition_rows, sort_keys=False
    )
    json_dump(output / "data/d1c_verified_pairs.json", verified_pairs, sort_keys=False)
    json_dump(output / "data/d1c_analysis_rows.json", {"table_rows": table_rows}, sort_keys=False)

    environment = os.environ.copy()
    environment["NODE_PATH"] = str(node_modules)
    table_run = subprocess.run(
        [
            str(node_binary),
            str(TABLE_BUILDER),
            str(output / "data/d1c_analysis_rows.json"),
            str(output / "tables/d1c_leadlag.csv"),
        ],
        cwd=REPO,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    if table_run.returncode != 0:
        raise RuntimeError(f"Artifact-tool table build failed: {table_run.stderr.strip()}")
    json_dump(output / "data/artifact_tool_verification.json", json.loads(table_run.stdout))

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True, text=True, capture_output=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
    )
    (output / "code_commit.txt").write_text(
        "\n".join(
            [
                f"git_commit={head}",
                f"worktree_dirty_at_run={str(dirty).lower()}",
                "analysis_command=python src/run_v6_2_d1c_fmask_reassessment.py --analysis-only --node <bundled-node> --node-modules <bundled-node_modules>",
                "memo_command=python src/build_v6_2_d1c_fmask_memo.py <manifest> <memo.pdf>",
                "finalize_command=python src/run_v6_2_d1c_fmask_reassessment.py --finalize",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _make_readme(output, analysis)
    return analysis


def finalize(output: Path) -> None:
    required = [
        output / "memo.pdf",
        output / "tables/d1c_leadlag.csv",
        output / "figures/d1c_timing.png",
        output / "figures/d1c_timing.svg",
        output / "data/d1c_fmask_acquisitions.json",
        output / "data/d1c_verified_pairs.json",
        output / "analysis_manifest.json",
        output / "README.md",
        output / "code_commit.txt",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Cannot finalize D1c Fmask reassessment; missing {missing}")
    write_checksums(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--node-modules", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--analysis-only", action="store_true")
    mode.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    try:
        if args.finalize:
            finalize(output)
            payload = {"status": "FINALIZED", "output": str(output)}
        else:
            if args.node is None or args.node_modules is None:
                raise ValueError("--analysis-only requires --node and --node-modules")
            analysis = run_analysis(
                output, args.node.resolve(), args.node_modules.resolve()
            )
            payload = {
                "status": analysis["status"],
                "ruling": analysis["ruling"],
                "quality_screened_pairs": analysis["counts"]["quality_screened_pairs"],
                "output": str(output),
            }
    except Exception as exc:
        print(f"D1c Fmask reassessment failed closed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
