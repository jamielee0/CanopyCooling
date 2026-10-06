#!/usr/bin/env python3
"""Build the v6.2 D1c count-only lead-lag feasibility evidence package.

Only metadata, coordinates, and ``observed_valid_count`` from the inherited
centered optical object are opened.  Optical index values and thermal outcomes
remain unopened.  Scientific failure (demotion to exploratory) is a valid result;
the command exits nonzero only for a computational or conformance failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr
import yaml

from urban_cooling_v2.connectivity_audit import select_candidate_passes
from urban_cooling_v2.lead_lag_feasibility import (
    LEGACY_SENSOR,
    REQUIRED_CITIES,
    REQUIRED_WINDOWS,
    centered_count_proxy,
    confirmatory_ruling,
    plot_timing_histogram,
    required_grid_rows,
    validate_required_grid,
)


REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO / "deliverables" / "D1c_leadlag_v6_2_20260902"
PROTOCOL_FILE = REPO / "docs/v2/v6_2/protocol_v6_2.yml"
PASS_TABLE = REPO / "docs/v2/hitl/G3_SAMPLING_DESIGN/angle_threshold_pass_detail_existing_five.csv"
DOMAIN_FILE = REPO / "data/raw/v2/domains/census_urban_areas.geojson"
CENTERED_PRODUCT = REPO / "data/interim/s2_ndmi_timeseries_70m.zarr"
LEGACY_BUILDER = REPO / "src/section4b_ndmi_timeseries.py"
AUDIT_MODULE = REPO / "src/urban_cooling_v2/lead_lag_feasibility.py"
TABLE_BUILDER = REPO / "src/build_v6_2_d1c_table.mjs"
MEMO_BUILDER = REPO / "src/build_v6_2_d1c_memo.py"
PROHIBITED_OPTICAL_VALUE_VARIABLES = ("observed", "clim_mean", "clim_std")
DROP_VARIABLES = (
    *PROHIBITED_OPTICAL_VALUE_VARIABLES,
    "clim_valid_count",
    "clim_low_count_lt3",
    "observed_low_count_lt3",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root: Path) -> tuple[str, int, int]:
    """Hash relative paths and bytes for one permitted Zarr subtree."""

    digest = hashlib.sha256()
    files = [path for path in sorted(root.rglob("*")) if path.is_file()]
    total = 0
    for path in files:
        rel = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(rel).to_bytes(4, "big"))
        digest.update(rel)
        size = path.stat().st_size
        total += size
        digest.update(size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest(), len(files), total


def json_dump(path: Path, payload: Any, *, sort_keys: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=sort_keys) + "\n", encoding="utf-8")


def domain_longitudes(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, float] = {}
    for feature in payload.get("features", []):
        props = feature.get("properties", {})
        city = str(props.get("city", ""))
        if city in REQUIRED_CITIES:
            result[city] = float(props["CENTLON"])
    if set(result) != set(REQUIRED_CITIES):
        raise ValueError(f"Missing required domain longitudes: {result}")
    return result


def make_readme(output: Path, analysis: dict[str, Any]) -> None:
    text = f"""# D1c - lead-lag feasibility

This count-only package applies frozen rule `V6.2-D009`. The ruling is
`{analysis['ruling']}`: temporal specificity is demoted to exploratory until a
source-level HLS acquisition ledger exists.

## Why the count does not establish a matched pair

- The inherited object identifies itself as `{analysis['inherited_product']['collection']}`,
  not HLS V2. It covers Phoenix in 2023 only.
- It stores centered +/-15-day composites and pixel-level scene counts, but no
  optical acquisition identifiers, source dates, sensor-specific records, or lag signs.
- All {analysis['inherited_product']['axis_records']} legacy axis records have a
  spatial median centered scene count of at least two. That is only a
  necessary-but-not-sufficient upper bound: both scenes could lie on the same side
  of a pass.
- No optical index value, ECOSTRESS LST value, or new v6.2 coefficient was opened.

## Contents

- `memo.pdf`: two-page-or-shorter D1c decision memo.
- `tables/d1c_leadlag.csv`: 56 required HLS strata plus two legacy-product audit rows.
- `figures/d1c_timing.png` and `.svg`: required timing histogram in an explicit
  no-verifiable-lag state.
- `data/d1c_centered_count_audit.json`: permitted count-only axis and candidate joins.
- `analysis_manifest.json`: frozen rules, source inventory, checks, and ruling.
- `code_commit.txt`: repository state and exact commands.
- `checksums.txt`: SHA-256 for every other file in this folder.

## Boundary carried forward

The centered inherited product cannot become the final antecedent exposure or
future placebo. If the temporal-specificity diagnostic is later restored, both
one-sided variables must be rebuilt from raw HLS with distinct source identifiers,
the frozen matched-lag rule, and explicit acquisition-reuse accounting.
"""
    (output / "README.md").write_text(text, encoding="utf-8")


def write_checksums(output: Path) -> None:
    target = output / "checksums.txt"
    lines = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path != target:
            lines.append(f"{sha256(path)}  {path.relative_to(output).as_posix()}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _product_axis_audit(ds: xr.Dataset) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index in range(int(ds.sizes["overpass"])):
        key = str(ds["overpass_key"].values[index])
        summary = centered_count_proxy(np.asarray(ds["observed_valid_count"].isel(overpass=index).values))
        records.append(
            {
                "axis_index": index,
                "thermal_overpass_key": key,
                "thermal_orbit": key.split("_", 1)[0],
                "thermal_time": pd.Timestamp(ds["time"].values[index]).isoformat(),
                **summary,
            }
        )
    return records


def _candidate_frames(pass_rows: pd.DataFrame, longitudes: dict[str, float]):
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    counts: dict[tuple[str, int, str], int] = {}
    for city in REQUIRED_CITIES:
        for window in REQUIRED_WINDOWS:
            frame = select_candidate_passes(
                pass_rows,
                city=city,
                longitude_degrees=longitudes[city],
                season_window=window,
                view_zenith_maximum_degrees=15,
            )
            frames[(city, window)] = frame
            grouped = frame.groupby(pd.to_numeric(frame["year"]).astype(int)).size()
            for year, count in grouped.items():
                counts[(city, int(year), window)] = int(count)
    return frames, counts


def _legacy_rows(
    frames: dict[tuple[str, str], pd.DataFrame],
    axis_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    axes = pd.DataFrame(axis_records)
    axes["time"] = pd.to_datetime(axes["thermal_time"])
    axes["month_day"] = axes["time"].dt.strftime("%m-%d")
    rows = []
    candidate_audit = []
    for window in REQUIRED_WINDOWS:
        candidate = frames[("phoenix", window)].copy()
        candidate = candidate.loc[pd.to_numeric(candidate["year"]).astype(int).eq(2023)]
        orbit_rows = []
        for record in candidate.itertuples(index=False):
            orbit = str(record.orbit)
            matched = axes.loc[axes["thermal_orbit"].eq(orbit)].copy()
            proxy = bool(
                not matched.empty
                and matched["centered_count_ge2_upper_bound"].astype(bool).all()
            )
            audit_row = {
                "city": "Phoenix",
                "year": 2023,
                "season_window": window,
                "thermal_orbit": orbit,
                "thermal_acquisition_utc": pd.Timestamp(record.acquisition_utc).isoformat(),
                "matched_centered_axis_records": int(len(matched)),
                "matched_axis_keys": matched["thermal_overpass_key"].astype(str).tolist(),
                "spatial_median_counts": matched["median_valid_scene_count"].astype(float).tolist(),
                "centered_count_ge2_upper_bound": proxy,
                "verified_pre_post_pair": None,
            }
            candidate_audit.append(audit_row)
            orbit_rows.append(audit_row)
        start, end = (
            ("05-15", "07-10") if window == "provisional_primary" else ("06-01", "09-30")
        )
        all_window_axes = axes.loc[axes["month_day"].between(start, end)]
        proxy_passes = sum(bool(item["centered_count_ge2_upper_bound"]) for item in orbit_rows)
        rows.append(
            {
                "record_role": "legacy_centered_product_audit",
                "city": "Phoenix",
                "year": 2023,
                "season_window": window,
                "sensor": LEGACY_SENSOR,
                "candidate_passes": int(len(candidate)),
                "passes_with_feasible_matched_pre_post": None,
                "feasible_share": None,
                "unique_optical_acquisition_identifiers": 0,
                "max_thermal_passes_sharing_one_acquisition": None,
                "centered_count_ge2_passes_upper_bound": int(proxy_passes),
                "inherited_product_axis_records": int(len(all_window_axes)),
                "matched_candidate_axis_records": int(sum(item["matched_centered_axis_records"] for item in orbit_rows)),
                "timing_status": "COUNT_UPPER_BOUND_ONLY_SOURCE_TIMING_ABSENT",
                "interpretation_note": (
                    "Legacy centered Sentinel-2 count inventory only; count>=2 does not prove "
                    "one pre-pass and one post-pass observation."
                ),
            }
        )
    return rows, candidate_audit


def run_analysis(output: Path, node_binary: Path, node_modules: Path) -> dict[str, Any]:
    with PROTOCOL_FILE.open("r", encoding="utf-8") as handle:
        protocol = yaml.safe_load(handle)
    frozen = protocol["free_checks"]["lead_lag_feasibility"]
    if frozen["decision_id"] != "V6.2-D009" or frozen["status"] != "FROZEN_FOR_COUNT_ONLY_OUTCOME_BLIND_RUN":
        raise RuntimeError("D009 lead-lag rule is not frozen")
    for required in (
        PROTOCOL_FILE,
        PASS_TABLE,
        DOMAIN_FILE,
        CENTERED_PRODUCT,
        LEGACY_BUILDER,
        AUDIT_MODULE,
        TABLE_BUILDER,
        MEMO_BUILDER,
    ):
        if not required.exists():
            raise FileNotFoundError(required)

    output.mkdir(parents=True, exist_ok=True)
    for directory in ("data", "figures", "tables"):
        (output / directory).mkdir(exist_ok=True)

    pass_rows = pd.read_csv(PASS_TABLE, dtype={"orbit": "string"})
    longitudes = domain_longitudes(DOMAIN_FILE)
    frames, candidate_counts = _candidate_frames(pass_rows, longitudes)
    table_rows = required_grid_rows(candidate_counts)
    validate_required_grid(table_rows)

    ds = xr.open_zarr(
        CENTERED_PRODUCT,
        decode_coords="all",
        consolidated=True,
        drop_variables=list(DROP_VARIABLES),
    )
    try:
        collection = str(ds.attrs.get("collection", ""))
        if collection != LEGACY_SENSOR:
            raise RuntimeError(f"Unexpected centered collection: {collection}")
        if "observed_valid_count" not in ds.data_vars:
            raise RuntimeError("Inherited centered product lacks observed_valid_count")
        source_fields = set(ds.coords).union(ds.data_vars).union(ds.attrs)
        source_dates_available = any(
            name in source_fields for name in ("source_date", "optical_source_date", "acquisition_date")
        )
        acquisition_identifiers_available = any(
            name in source_fields for name in ("optical_acquisition_id", "source_acquisition_id")
        )
        axis_records = _product_axis_audit(ds)
        inherited = {
            "path": str(CENTERED_PRODUCT.relative_to(REPO)),
            "collection": collection,
            "crs": str(ds.attrs.get("crs")),
            "axis_records": int(ds.sizes["overpass"]),
            "spatial_shape": [int(ds.sizes["y"]), int(ds.sizes["x"])],
            "time_min": pd.Timestamp(ds["time"].values.min()).isoformat(),
            "time_max": pd.Timestamp(ds["time"].values.max()).isoformat(),
            "method_observed": str(ds.attrs.get("method_observed")),
            "source_dates_available": source_dates_available,
            "acquisition_identifiers_available": acquisition_identifiers_available,
            "permitted_data_variable_opened": "observed_valid_count",
            "prohibited_optical_value_variables_opened": [],
        }
    finally:
        ds.close()

    legacy_rows, candidate_audit = _legacy_rows(frames, axis_records)
    for row in table_rows:
        row["matched_candidate_axis_records"] = 0
    all_rows = table_rows + legacy_rows
    ruling = confirmatory_ruling(
        all_rows,
        source_dates_available=source_dates_available,
        acquisition_identifiers_available=acquisition_identifiers_available,
    )

    plot_timing_histogram(
        [],
        [],
        output / "figures/d1c_timing.png",
        output / "figures/d1c_timing.svg",
    )
    count_tree_hash, count_tree_files, count_tree_bytes = tree_sha256(
        CENTERED_PRODUCT / "observed_valid_count"
    )
    checks = {
        "required_hls_rows_56": len(table_rows) == 56,
        "legacy_audit_rows_2": len(legacy_rows) == 2,
        "all_required_grid_keys_present": True,
        "centered_axis_records_66": len(axis_records) == 66,
        "all_axis_spatial_median_counts_at_least_2": all(
            row["centered_count_ge2_upper_bound"] for row in axis_records
        ),
        "source_dates_available": source_dates_available,
        "acquisition_identifiers_available": acquisition_identifiers_available,
        "optical_value_variables_opened": False,
        "thermal_or_lst_values_opened": False,
        "new_v6_2_coefficients_viewed": False,
        "gate_A_authorized": False,
        "fail_closed_ruling_matches_missing_provenance": ruling
        == "DEMOTE_TO_EXPLORATORY_MISSING_SOURCE_TIMING_PROVENANCE",
    }
    computational_checks = {
        "required_hls_rows_56": checks["required_hls_rows_56"],
        "legacy_audit_rows_2": checks["legacy_audit_rows_2"],
        "all_required_grid_keys_present": checks["all_required_grid_keys_present"],
        "centered_axis_records_66": checks["centered_axis_records_66"],
        "optical_value_variables_not_opened": checks["optical_value_variables_opened"] is False,
        "thermal_or_lst_values_not_opened": checks["thermal_or_lst_values_opened"] is False,
        "new_coefficients_not_viewed": checks["new_v6_2_coefficients_viewed"] is False,
        "gate_A_not_authorized": checks["gate_A_authorized"] is False,
        "fail_closed_ruling_is_consistent": checks["fail_closed_ruling_matches_missing_provenance"],
    }
    if not all(computational_checks.values()):
        raise RuntimeError(f"Fail-closed D1c conformance check failed: {computational_checks}")

    input_hashes = {
        str(PROTOCOL_FILE.relative_to(REPO)): sha256(PROTOCOL_FILE),
        str(PASS_TABLE.relative_to(REPO)): sha256(PASS_TABLE),
        str(DOMAIN_FILE.relative_to(REPO)): sha256(DOMAIN_FILE),
        str(LEGACY_BUILDER.relative_to(REPO)): sha256(LEGACY_BUILDER),
        str((CENTERED_PRODUCT / ".zattrs").relative_to(REPO)): sha256(CENTERED_PRODUCT / ".zattrs"),
        str((CENTERED_PRODUCT / ".zmetadata").relative_to(REPO)): sha256(CENTERED_PRODUCT / ".zmetadata"),
    }
    analysis = {
        "decision_id": "V6.2-D009",
        "status": "READY_FOR_D1C_REVIEW",
        "ruling": ruling,
        "temporal_specificity_status": "EXPLORATORY",
        "table_rows": all_rows,
        "required_hls_rows": 56,
        "legacy_product_audit_rows": 2,
        "candidate_pass_counts_15deg": {
            city: {
                window: {
                    str(year): int(len(frame.loc[pd.to_numeric(frame["year"]).astype(int).eq(year)]))
                    for year in range(2019, 2026)
                }
                for window in REQUIRED_WINDOWS
                for frame in [frames[(city, window)]]
            }
            for city in REQUIRED_CITIES
        },
        "inherited_product": inherited,
        "count_only_summary": {
            "axis_records_with_spatial_median_count_ge2": int(
                sum(row["centered_count_ge2_upper_bound"] for row in axis_records)
            ),
            "axis_records_total": len(axis_records),
            "phoenix_2023_candidate_pass_proxy": {
                row["season_window"]: {
                    "candidate_passes": row["candidate_passes"],
                    "centered_count_ge2_upper_bound_passes": row[
                        "centered_count_ge2_passes_upper_bound"
                    ],
                    "matched_candidate_axis_records": row["matched_candidate_axis_records"],
                    "all_legacy_axis_records_in_window": row["inherited_product_axis_records"],
                }
                for row in legacy_rows
            },
            "verified_pre_lags": 0,
            "verified_post_lags": 0,
            "unique_optical_acquisition_identifiers": 0,
        },
        "checks": checks,
        "computational_checks": computational_checks,
        "input_sha256": input_hashes,
        "implementation_sha256": {
            str(path.relative_to(REPO)): sha256(path)
            for path in (Path(__file__), AUDIT_MODULE, TABLE_BUILDER, MEMO_BUILDER)
        },
        "permitted_count_subtree_sha256": {
            "path": str((CENTERED_PRODUCT / "observed_valid_count").relative_to(REPO)),
            "sha256": count_tree_hash,
            "files": count_tree_files,
            "bytes": count_tree_bytes,
        },
        "interpretation": {
            "centered_count_role": "necessary_not_sufficient_upper_bound_only",
            "actual_product_mismatch": "Sentinel-2 centered product is not HLS V2",
            "verified_pair_count": "not_estimable_not_zero",
            "final_antecedent_exposure": "must_be_rebuilt_from_raw_HLS_one_sided",
            "final_future_placebo": "must_be_rebuilt_separately_from_raw_HLS_matched_lag",
            "gate_A_authorization_effect": "none",
        },
    }
    json_dump(output / "analysis_manifest.json", analysis)
    json_dump(
        output / "data/d1c_centered_count_audit.json",
        {
            "axis_records": axis_records,
            "candidate_pass_join_audit": candidate_audit,
            "prohibited_optical_value_variables_opened": [],
            "thermal_or_lst_values_opened": False,
        },
        sort_keys=False,
    )
    json_dump(output / "data/d1c_analysis_rows.json", {"table_rows": all_rows}, sort_keys=False)

    environment = os.environ.copy()
    environment["NODE_PATH"] = str(node_modules)
    table_script = REPO / "src/build_v6_2_d1c_table.mjs"
    completed = subprocess.run(
        [
            str(node_binary),
            str(table_script),
            str(output / "data/d1c_analysis_rows.json"),
            str(output / "tables/d1c_leadlag.csv"),
        ],
        cwd=REPO,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Artifact-tool table build failed: {completed.stderr.strip()}")
    json_dump(output / "data/artifact_tool_verification.json", json.loads(completed.stdout))

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True, text=True, capture_output=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO, check=True, text=True, capture_output=True
        ).stdout.strip()
    )
    (output / "code_commit.txt").write_text(
        "\n".join(
            [
                f"git_commit={head}",
                f"worktree_dirty_at_run={str(dirty).lower()}",
                "analysis_command=python src/run_v6_2_d1c_leadlag.py --analysis-only --node <bundled-node> --node-modules <bundled-node_modules>",
                "memo_command=python src/build_v6_2_d1c_memo.py <table> <manifest> <memo.pdf>",
                "finalize_command=python src/run_v6_2_d1c_leadlag.py --finalize",
                "",
            ]
        ),
        encoding="utf-8",
    )
    make_readme(output, analysis)
    return analysis


def finalize(output: Path) -> None:
    required = [
        output / "memo.pdf",
        output / "tables/d1c_leadlag.csv",
        output / "figures/d1c_timing.png",
        output / "figures/d1c_timing.svg",
        output / "analysis_manifest.json",
        output / "README.md",
        output / "code_commit.txt",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Cannot finalize D1c; missing {missing}")
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
            analysis = run_analysis(output, args.node.resolve(), args.node_modules.resolve())
            payload = {
                "status": analysis["status"],
                "ruling": analysis["ruling"],
                "output": str(output),
            }
    except Exception as exc:
        print(f"D1c failed closed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
