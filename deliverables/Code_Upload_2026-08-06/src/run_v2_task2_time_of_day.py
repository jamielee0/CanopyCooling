#!/usr/bin/env python3
"""Prethermal-only D0056/D0057 Task-2A entry point.

The commands in this runner read only frozen CSV/JSON/TOML metadata.  No command
downloads or opens an LST/thermal raster.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from urban_cooling_v2.task2_time_of_day_guardrails import (
    DEFAULT_CONFIG,
    build_prethermal_evidence,
    run_imported_public_cmr_census,
    run_public_cmr_census,
    run_preflight,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze or validate the D0056 time-of-day-only Task-2A metadata contract."
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument(
        "--freeze-evidence",
        action="store_true",
        help="Build quality-only holdout/product/storage evidence; opens no thermal layer.",
    )
    actions.add_argument(
        "--census-public-cmr",
        action="store_true",
        help="Census public NASA CMR metadata only; downloads/opens no science asset.",
    )
    actions.add_argument(
        "--import-public-cmr-metadata",
        type=Path,
        metavar="PATH",
        help="Run the same census from official CMR JSON/CSV saved in the repository.",
    )
    actions.add_argument(
        "--preflight",
        action="store_true",
        help="Validate the exact branch gate and Task-2A freeze; opens no raster.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()

    if args.census_public_cmr:
        try:
            record = run_public_cmr_census(args.config)
        except (OSError, RuntimeError, ValueError) as exc:
            record = {
                "status": "MISSING_LIVE_CMR_CENSUS",
                "ready": False,
                "blocker": str(exc),
                "thermal_or_science_values_opened": 0,
                "data_object_urls_followed": 0,
            }
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0 if record["status"] == "PASS_CORE_PRODUCT_AVAILABILITY" else 2

    if args.import_public_cmr_metadata is not None:
        try:
            record = run_imported_public_cmr_census(
                args.import_public_cmr_metadata, args.config
            )
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            record = {
                "status": "INVALID_IMPORTED_CMR_CENSUS",
                "ready": False,
                "blocker": str(exc),
                "thermal_or_science_values_opened": 0,
                "data_object_urls_followed": 0,
            }
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0 if record["status"] == "PASS_CORE_PRODUCT_AVAILABILITY" else 2

    if args.freeze_evidence:
        try:
            record = build_prethermal_evidence(args.config)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            record = {
                "status": "STOP_TASK2A_PREREQUISITE",
                "ready": False,
                "blocker": str(exc),
                "thermal_or_science_values_opened": 0,
                "data_object_urls_followed": 0,
            }
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0 if record["status"] == "FROZEN_PRETHERMAL_READY" else 2

    report = run_preflight(args.config)
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
