#!/usr/bin/env python3
"""Conditional Task 2 entry point.

Only the read-only preflight exists.  Result-bearing stages are intentionally
absent until the canonical Task 1 gate is PASS and the Task 2 decisions freeze.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from urban_cooling_v2.task2_guardrails import DEFAULT_CONFIG, run_preflight


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the fail-closed, no-data-access Task 2 readiness preflight."
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Evaluate gates and frozen decisions; performs no network or raster access.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Conditional Task 2 TOML configuration.",
    )
    args = parser.parse_args()
    if not args.preflight:
        parser.error(
            "Only --preflight is implemented. Result-bearing Task 2 stages remain disabled."
        )

    report = run_preflight(args.config)
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
