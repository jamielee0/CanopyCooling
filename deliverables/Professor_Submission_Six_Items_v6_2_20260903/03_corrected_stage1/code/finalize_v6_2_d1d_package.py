#!/usr/bin/env python3
"""Verify and checksum the open D1d package without parsing sealed estimates."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

from pypdf import PdfReader


EXPECTED_SEALED_SHA256 = "146b16f85aa89c486d174121d1e3e781ded685d8940f0dc6037e238b090d6004"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_shape(path: Path) -> tuple[int, list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        return sum(1 for _ in reader), header


def main(package_arg: str) -> int:
    package = Path(package_arg).resolve()
    stage_path = package / "tables" / "d1d_stage1_se.csv"
    power_path = package / "tables" / "d1d_n_required.csv"
    sealed_link = package / "sealed" / "d1d_coefficients_SEALED.csv"

    stage_rows, stage_header = csv_shape(stage_path)
    power_rows, power_header = csv_shape(power_path)
    forbidden = {"slope_K_per_unit_canopy_fraction", "CE_K_per_10pp"}
    checks = {
        "memo_pdf_present": (package / "memo.pdf").is_file(),
        "memo_pdf_page_count_expected": len(PdfReader(package / "memo.pdf").pages) == 2,
        "two_open_tables_present": stage_path.is_file() and power_path.is_file(),
        "two_figure_pngs_present": all(
            (package / "figures" / name).is_file()
            for name in ("d1d_se_distribution.png", "d1d_n_required.png")
        ),
        "stage_open_rows_13210": stage_rows == 13210,
        "power_open_rows_48": power_rows == 48,
        "open_tables_have_no_point_estimate_fields": forbidden.isdisjoint(stage_header)
        and forbidden.isdisjoint(power_header),
        "sealed_pointer_is_symlink": sealed_link.is_symlink(),
        "sealed_sha256_matches_manifest": sha256_file(sealed_link) == EXPECTED_SEALED_SHA256,
    }
    if not all(checks.values()):
        raise SystemExit(json.dumps(checks, sort_keys=True))

    verification = {
        "status": "VERIFIED_D1D_STOP_NO_ESTIMABLE_BLOCK_PASS",
        "checks": checks,
        "stage_open_rows": stage_rows,
        "power_open_rows": power_rows,
        "sealed_sha256": EXPECTED_SEALED_SHA256,
        "sealed_content_policy": "hashed_only_not_parsed",
    }
    (package / "verification.json").write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    checksum_path = package / "checksums.txt"
    entries = []
    for path in sorted(package.rglob("*")):
        if path.is_dir() or path == checksum_path:
            continue
        entries.append(f"{sha256_file(path)}  {path.relative_to(package)}")
    checksum_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
    print(json.dumps(verification, sort_keys=True))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: finalize_v6_2_d1d_package.py PACKAGE_DIR")
    raise SystemExit(main(sys.argv[1]))
