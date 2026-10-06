#!/usr/bin/env python3
"""Regenerate the nonthermal Gate-2 hydroclimatic-support package."""

from __future__ import annotations

import json
from pathlib import Path

from urban_cooling_v2.hitl_gate2_hydroclimate import write_gate2_package


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(write_gate2_package(root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
