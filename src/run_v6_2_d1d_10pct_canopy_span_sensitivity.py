#!/usr/bin/env python3
"""Evaluate a nonbinding 0.10 canopy-span sensitivity from the sealed D016 table.

The controlling 0.20 D015/D016 rule is preserved. This script opens no LST and
does not run Stage 1; it only reclassifies already recorded nonthermal spans.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Sequence


REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "deliverables/D1d_tcc_span_screen_v6_2_20260902/analysis_manifest.json"
OUTPUT = REPO / "deliverables/D1d_10pct_canopy_span_sensitivity_v6_2_20260903"
BLOCK_PASS_TABLE = OUTPUT / "tables/d1d_10pct_block_passes.csv"
BLOCK_TABLE = OUTPUT / "tables/d1d_10pct_blocks.csv"
THRESHOLD = 0.10
ORIGINAL_THRESHOLD = 0.20


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evaluate_rows(
    rows: Sequence[dict[str, Any]], threshold: float = THRESHOLD
) -> dict[str, Any]:
    if not 0.0 <= float(threshold) <= 1.0:
        raise ValueError("threshold must be between 0 and 1")
    eligible = [
        row for row in rows if float(row["canopy_span_fraction"]) >= float(threshold)
    ]
    by_pass: dict[str, dict[str, int | float]] = {}
    pass_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        pass_rows[str(row["pass_id"])].append(row)
    for pass_id, current in sorted(pass_rows.items()):
        eligible_count = sum(
            float(row["canopy_span_fraction"]) >= float(threshold) for row in current
        )
        by_pass[pass_id] = {
            "candidate_block_passes": len(current),
            "eligible_block_passes": eligible_count,
            "eligible_share": eligible_count / len(current),
        }

    eligible_passes_by_block = Counter(str(row["block_id"]) for row in eligible)
    count_distribution = Counter(eligible_passes_by_block.values())
    return {
        "candidate_block_passes": len(rows),
        "eligible_block_passes": len(eligible),
        "eligible_share": len(eligible) / len(rows) if rows else 0.0,
        "unique_eligible_blocks": len(eligible_passes_by_block),
        "eligible_passes_per_eligible_block_median": (
            float(median(eligible_passes_by_block.values()))
            if eligible_passes_by_block
            else None
        ),
        "eligible_passes_per_block_distribution": {
            str(key): count_distribution[key] for key in sorted(count_distribution)
        },
        "eligible_passes_by_block": dict(sorted(eligible_passes_by_block.items())),
        "by_pass": by_pass,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = source["rows"]
    if source["candidate_block_passes"] != len(rows):
        raise ValueError("D016 source row count does not reconcile")
    if source["eligible_block_passes"] != 0:
        raise ValueError("D016 controlling result is no longer zero")
    if float(source["canopy_span_fraction"]["frozen_floor"]) != ORIGINAL_THRESHOLD:
        raise ValueError("D016 controlling 0.20 floor changed")

    result = evaluate_rows(rows)
    expected = {
        "eligible_block_passes": 1368,
        "unique_eligible_blocks": 331,
        "eligible_passes_per_eligible_block_median": 4.0,
    }
    for key, value in expected.items():
        if result[key] != value:
            raise RuntimeError(f"Unexpected 0.10 result for {key}: {result[key]}")

    block_pass_rows = [
        {
            "city": row["city"],
            "pass_id": row["pass_id"],
            "block_id": row["block_id"],
            "nonthermal_native_cells": row["nonthermal_native_cells"],
            "canopy_p10_fraction": row["canopy_p10_fraction"],
            "canopy_p90_fraction": row["canopy_p90_fraction"],
            "canopy_span_fraction": row["canopy_span_fraction"],
            "meets_controlling_0_20_span": row["meets_frozen_0_20_span"],
            "meets_nonbinding_0_10_span": float(row["canopy_span_fraction"])
            >= THRESHOLD,
        }
        for row in rows
    ]
    write_csv(BLOCK_PASS_TABLE, block_pass_rows)
    write_csv(
        BLOCK_TABLE,
        [
            {"block_id": block_id, "eligible_passes_at_0_10": count}
            for block_id, count in result["eligible_passes_by_block"].items()
        ],
    )

    result_for_manifest = dict(result)
    result_for_manifest.pop("eligible_passes_by_block")
    manifest = {
        "decision_id": "V6.2-D021",
        "status": "NONBINDING_POST_SUPPORT_SENSITIVITY_COMPLETE",
        "controlling_decision_preserved": "V6.2-D016",
        "controlling_canopy_span_floor": ORIGINAL_THRESHOLD,
        "sensitivity_canopy_span_floor": THRESHOLD,
        "canopy_span_interpretation": "p90_minus_p10_canopy_fraction_within_block_pass",
        "result": result_for_manifest,
        "sensitivity_ruling": "WOULD_CLEAR_NONTHERMAL_ZERO_ELIGIBILITY_STOP",
        "authorized_action": "NONE_PENDING_SUPERVISOR_APPROVAL",
        "interpretation": (
            "A prospectively approved 0.10 rule would permit consideration of the "
            "same five-pass sealed Stage-1 pilot because the nonthermal screen is "
            "no longer empty. It does not establish final thermal estimability, "
            "precision, power, Los Angeles support, or Gate-A eligibility."
        ),
        "checks": {
            "source_candidate_rows_reconcile": len(rows) == 13509,
            "source_controlling_0_20_eligibility_zero": source[
                "eligible_block_passes"
            ]
            == 0,
            "sensitivity_threshold_exactly_0_10": THRESHOLD == 0.10,
            "controlling_D016_not_replaced": True,
            "thermal_or_lst_values_opened": False,
            "new_v6_2_coefficients_viewed": False,
            "conditional_stage1_rerun_executed": False,
            "gate_A_authorized": False,
        },
        "input_sha256": {str(SOURCE.relative_to(REPO)): sha256(SOURCE)},
        "implementation_sha256": {
            str(Path(__file__).resolve().relative_to(REPO)): sha256(
                Path(__file__).resolve()
            )
        },
    }
    (OUTPUT / "analysis_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    pass_lines = []
    for pass_id, values in result["by_pass"].items():
        pass_lines.append(
            f"| {pass_id} | {values['eligible_block_passes']:,} | "
            f"{values['candidate_block_passes']:,} | {values['eligible_share']:.1%} |"
        )
    distribution_text = ", ".join(
        f"{block_count} blocks on {pass_count} pass{'es' if pass_count != '1' else ''}"
        for pass_count, block_count in result[
            "eligible_passes_per_block_distribution"
        ].items()
    )
    readme = f"""# D1d 0.10 canopy-span sensitivity

This is a **nonbinding post-support sensitivity**. It preserves the controlling
0.20 D015/D016 rule and opens no ECOSTRESS LST or new coefficient.

## What the threshold means

The rule is not "10% of observations." A block-pass passes when its within-block
Science TCC p90 minus p10 is at least **0.10 canopy fraction**, or ten percentage
points. The purpose is to avoid estimating a canopy-temperature slope from a block
whose canopy values are nearly uniform.

## Result

- Candidate nonthermal block-passes: **{result['candidate_block_passes']:,}**
- Eligible at 0.10: **{result['eligible_block_passes']:,} ({result['eligible_share']:.1%})**
- Unique eligible Phoenix blocks: **{result['unique_eligible_blocks']:,}**
- Median eligible passes per eligible block: **{result['eligible_passes_per_eligible_block_median']:.0f} of 5**
- Eligible-pass distribution across blocks: {distribution_text}

| Pass | Eligible | Candidate | Share |
|---|---:|---:|---:|
{chr(10).join(pass_lines)}

At 0.10, the nonthermal screen is no longer empty. If a supervisor prospectively
approved this threshold, it would be reasonable to consider the same five-pass
sealed thermal Stage-1 pilot. That pilot would still need to demonstrate actual
tree/background cell support, estimable slopes, acceptable uncertainty and
stability. This sensitivity does **not** authorize Gate A.

## Contents

- `tables/d1d_10pct_block_passes.csv`: all 13,509 rows under both thresholds.
- `tables/d1d_10pct_blocks.csv`: eligible-pass counts for the 331 qualifying blocks.
- `analysis_manifest.json`: exact result, checks, and source hash.
- `checksums.txt`: SHA-256 for every other file in this package.
"""
    (OUTPUT / "README.md").write_text(readme, encoding="utf-8")

    checksums = []
    for path in sorted(item for item in OUTPUT.rglob("*") if item.is_file()):
        if path.name == "checksums.txt":
            continue
        checksums.append(f"{sha256(path)}  {path.relative_to(OUTPUT)}")
    (OUTPUT / "checksums.txt").write_text(
        "\n".join(checksums) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "eligible_block_passes": result["eligible_block_passes"],
                "unique_eligible_blocks": result["unique_eligible_blocks"],
                "gate_A_authorized": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
