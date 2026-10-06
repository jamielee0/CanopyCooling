#!/usr/bin/env python3
"""Generate the Gate-1 nonthermal observation reconciliation checkpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from urban_cooling_v2.hitl_gate1_reconciliation import write_gate1_package


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root",
    )
    args = parser.parse_args()
    print(json.dumps(write_gate1_package(args.root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
