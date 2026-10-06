#!/usr/bin/env python3
"""Build the non-binding v6.2 D1a parsimonious demand sensitivity package."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from urban_cooling_v2.demand_geometry_audit import (
    INPUT_PATHS,
    build_parsimonious_sensitivity,
    load_analysis_passes,
    sha256_file,
)


DEFAULT_OUTPUT = Path("deliverables/D1a_parsimonious_sensitivity_v6_2_20260830")


def write_json(value: object, path: Path) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def format_markdown(result: dict) -> str:
    rows = [
        "# D1a parsimonious demand–geometry sensitivity",
        "",
        f"**Non-binding sensitivity ruling: {result['sensitivity_ruling']}**",
        "",
        "This user-requested sensitivity does not replace the controlling D003 DROP. It uses only the primary ≤15° near-nadir set; adjusts VPD for solar zenith, view zenith, and cyclic day of year; and does not require azimuth completeness. Temperature-only and vapour-pressure-only additions are interpretation checks, not vetoes.",
        "",
        "| City | Specification | n | VIF | Condition index | Nonlinear R² | Residual SD (kPa) | Common width (kPa) | Primary pass |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in result["rows"]:
        primary_pass = (
            "yes" if row["all_primary_criteria_pass"] else "no"
            if row["all_primary_criteria_pass"] is not None
            else "non-vetoing"
        )
        rows.append(
            "| {city} | {specification} | {n_complete} | {vpd_vif:.3f} | "
            "{maximum_condition_index:.3f} | {vpd_nonlinear_cv_concurvity_r2:.3f} | "
            "{residual_vpd_sd_kpa:.3f} | {continuous_support_width_kpa:.3f} | {primary_pass} |".format(
                primary_pass=primary_pass, **row
            )
        )
    rows.extend(
        [
            "",
            "## Interpretation",
            "",
            result["interpretation"],
            "",
            "Phoenix passes every binding parsimonious criterion. Los Angeles fails only the common-support-width floor: 0.300 kPa observed versus 0.500 kPa required. Therefore the cross-city sensitivity remains DROP, but the result is a near-pass rather than the structural non-estimability found under the controlling full design.",
            "",
            "No ECOSTRESS LST value or new v6.2 coefficient was opened. Historical pass evidence remains provenance-only and is not declared to be the v6.2 study sample.",
        ]
    )
    return "\n".join(rows) + "\n"


def write_checksums(output: Path) -> None:
    checksum_path = output / "checksums.txt"
    files = sorted(path for path in output.rglob("*") if path.is_file() and path != checksum_path)
    lines = []
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(output)}")
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else repo_root / args.output
    output.mkdir(parents=True, exist_ok=True)
    (output / "data").mkdir(exist_ok=True)

    result = build_parsimonious_sensitivity(load_analysis_passes(repo_root))
    evidence = []
    for name, relative in INPUT_PATHS.items():
        path = repo_root / relative
        evidence.append(
            {
                "name": name,
                "path": str(relative),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    result["input_evidence"] = evidence
    write_json(result, output / "analysis_manifest.json")
    (output / "README.md").write_text(format_markdown(result), encoding="utf-8")

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    command = (
        "PYTHONPATH=src /Users/jmlee/miniforge3/envs/urbanv2/bin/python "
        "src/run_v6_2_d1a_parsimonious_sensitivity.py"
    )
    (output / "code_commit.txt").write_text(
        f"base_commit={head}\n"
        "analysis_code_status=UNCOMMITTED_PENDING_REVIEW\n"
        f"exact_command={command}\n"
        "outcome_access=NONE\n"
        "new_v6_2_coefficients_viewed=false\n"
        "controlling_D003_ruling_changed=false\n",
        encoding="utf-8",
    )
    source_lines = [
        "D1a parsimonious-sensitivity input evidence",
        "Historical nonthermal provenance only; not the v6.2 study sample.",
        "",
    ]
    source_lines.extend(
        f"{item['name']}\t{item['path']}\tsha256={item['sha256']}\tbytes={item['bytes']}"
        for item in evidence
    )
    (output / "data" / "input_sources.txt").write_text(
        "\n".join(source_lines) + "\n", encoding="utf-8"
    )
    write_checksums(output)
    print(
        json.dumps(
            {"output": str(output), "sensitivity_ruling": result["sensitivity_ruling"]},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
