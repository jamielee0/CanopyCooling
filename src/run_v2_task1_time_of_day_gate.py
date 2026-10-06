#!/usr/bin/env python3
"""Finalize the separately scoped D0056 time-of-day-only Task-1 gate."""

from __future__ import annotations

import argparse
from pathlib import Path

from urban_cooling_v2.task1_time_of_day_gate import (
    DEFAULT_GATE_PATH,
    REPO_ROOT,
    write_default_time_of_day_task1_pass,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed D0056 Task-1 finalizer; performs no network, raster, "
            "thermal, holdout, or 2026 access."
        )
    )
    parser.add_argument(
        "--gate-path",
        type=Path,
        default=Path(DEFAULT_GATE_PATH),
        help="Repository-relative scoped gate output (never overwritten).",
    )
    args = parser.parse_args()
    output = write_default_time_of_day_task1_pass(
        repo_root=REPO_ROOT,
        gate_path=args.gate_path,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
