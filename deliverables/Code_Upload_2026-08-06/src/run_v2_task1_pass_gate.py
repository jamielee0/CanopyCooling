#!/usr/bin/env python3
"""Write the canonical Task-1 PASS only after a complete local revalidation."""

from __future__ import annotations

import argparse
from pathlib import Path

from urban_cooling_v2.task1_pass_gate import (
    REPO_ROOT,
    write_default_canonical_task1_pass,
    write_default_d0047_canonical_task1_pass,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed Task-1 PASS finalizer; performs no network or raster access."
        )
    )
    parser.add_argument(
        "--profile",
        choices=("d0035_exhaustive", "d0047_archive_available"),
        required=True,
        help="Frozen evidence chain to validate before writing PASS.",
    )
    parser.add_argument(
        "--gate-path",
        type=Path,
        default=Path("data/processed/v2/task1/TASK1_GATE.json"),
        help="Repository-relative canonical gate output (never overwritten).",
    )
    args = parser.parse_args()
    writer = (
        write_default_d0047_canonical_task1_pass
        if args.profile == "d0047_archive_available"
        else write_default_canonical_task1_pass
    )
    output = writer(repo_root=REPO_ROOT, gate_path=args.gate_path)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
