#!/usr/bin/env python3
"""Re-evaluate D1c at a user-requested 20% share cutoff.

This is deliberately a post-support, nonbinding sensitivity.  It reads only the
already produced D1c stratum table and does not replace the frozen 70% D009/D019
ruling or open reflectance, optical-index, LST, or coefficient values.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from urban_cooling_v2.lead_lag_feasibility import (
    MAX_ACQUISITION_REUSE_SHARE,
    confirmatory_ruling,
    validate_required_grid,
)


REPO = Path(__file__).resolve().parents[1]
SOURCE_TABLE = (
    REPO
    / "deliverables/D1c_fmask_reassessment_v6_2_20260902/tables/d1c_leadlag.csv"
)
OUTPUT = REPO / "deliverables/D1c_20pct_sensitivity_v6_2_20260903"
TABLE_PATH = OUTPUT / "tables/d1c_20pct_strata.csv"
THRESHOLD = 0.20
ORIGINAL_THRESHOLD = 0.70
EXPECTED_RULING = "DEMOTE_TO_EXPLORATORY_CONFIRMATORY_SUPPORT_RULE_FAILED"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_rows() -> list[dict[str, Any]]:
    with SOURCE_TABLE.open(newline="", encoding="utf-8") as handle:
        raw_rows = list(csv.DictReader(handle))
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        row = dict(raw)
        row["year"] = int(row["year"])
        row["candidate_passes"] = int(row["candidate_passes"])
        row["passes_with_feasible_matched_pre_post"] = int(
            row["passes_with_feasible_matched_pre_post"]
        )
        row["feasible_share"] = (
            None if row["feasible_share"] == "" else float(row["feasible_share"])
        )
        row["max_thermal_passes_sharing_one_acquisition"] = (
            None
            if row["max_thermal_passes_sharing_one_acquisition"] == ""
            else int(row["max_thermal_passes_sharing_one_acquisition"])
        )
        rows.append(row)
    validate_required_grid(rows)
    return rows


def evaluate(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    evaluated: list[dict[str, Any]] = []
    for row in rows:
        candidate = int(row["candidate_passes"])
        reuse_limit = max(1, math.floor(MAX_ACQUISITION_REUSE_SHARE * candidate))
        share = row["feasible_share"]
        reuse = row["max_thermal_passes_sharing_one_acquisition"]
        applicable = candidate > 0
        share_pass = bool(applicable and share is not None and float(share) >= THRESHOLD)
        reuse_pass = bool(applicable and reuse is not None and int(reuse) <= reuse_limit)
        evaluated.append(
            {
                "city": row["city"],
                "year": row["year"],
                "season_window": row["season_window"],
                "sensor": row["sensor"],
                "candidate_passes": candidate,
                "quality_screened_pairs": row[
                    "passes_with_feasible_matched_pre_post"
                ],
                "feasible_share": share,
                "minimum_share_sensitivity": THRESHOLD,
                "share_rule": "NOT_APPLICABLE"
                if not applicable
                else ("PASS" if share_pass else "FAIL"),
                "maximum_acquisition_reuse": reuse,
                "reuse_limit": reuse_limit if applicable else None,
                "reuse_rule": "NOT_APPLICABLE"
                if not applicable
                else ("PASS" if reuse_pass else "FAIL"),
                "stratum_rule": "NOT_APPLICABLE"
                if not applicable
                else ("PASS" if share_pass and reuse_pass else "FAIL"),
            }
        )

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in evaluated:
        if row["candidate_passes"] > 0:
            grouped[(row["city"], row["season_window"])].append(row)

    panels: dict[str, dict[str, Any]] = {}
    for (city, window), strata in sorted(grouped.items()):
        panel_key = f"{city.lower().replace(' ', '_')}__{window}"
        share_failures = [row for row in strata if row["share_rule"] == "FAIL"]
        reuse_failures = [row for row in strata if row["reuse_rule"] == "FAIL"]
        panels[panel_key] = {
            "city": city,
            "season_window": window,
            "nonzero_strata": len(strata),
            "share_failure_count": len(share_failures),
            "reuse_failure_count": len(reuse_failures),
            "all_nonzero_strata_pass": all(
                row["stratum_rule"] == "PASS" for row in strata
            ),
            "share_failure_strata": [
                f"{row['year']} {row['sensor']} ({row['quality_screened_pairs']}/"
                f"{row['candidate_passes']}={float(row['feasible_share']):.1%})"
                for row in share_failures
            ],
            "reuse_failure_strata": [
                f"{row['year']} {row['sensor']} ({row['maximum_acquisition_reuse']} shared; "
                f"limit {row['reuse_limit']})"
                for row in reuse_failures
            ],
        }

    ruling = confirmatory_ruling(
        rows,
        source_dates_available=True,
        acquisition_identifiers_available=True,
        minimum_confirmatory_share=THRESHOLD,
    )
    return evaluated, {"panels": panels, "ruling": ruling}


def write_table(rows: list[dict[str, Any]]) -> None:
    TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TABLE_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows = read_rows()
    evaluated, result = evaluate(rows)
    if result["ruling"] != EXPECTED_RULING:
        raise RuntimeError(
            f"Unexpected 20% sensitivity ruling: {result['ruling']}"
        )
    write_table(evaluated)

    manifest = {
        "decision_id": "V6.2-D020",
        "status": "NONBINDING_POST_SUPPORT_SENSITIVITY_COMPLETE",
        "requested_minimum_matched_pair_share": THRESHOLD,
        "controlling_minimum_matched_pair_share": ORIGINAL_THRESHOLD,
        "controlling_decision_preserved": "V6.2-D019",
        "ruling": result["ruling"],
        "interpretation": (
            "Lowering the share cutoff to 20% does not change the result because "
            "each city-window must pass every nonzero year-sensor stratum, and all "
            "four panels retain zero-share strata; Los Angeles also retains frozen "
            "25% acquisition-reuse failures."
        ),
        "panels": result["panels"],
        "checks": {
            "source_required_grid_rows_56": len(rows) == 56,
            "minimum_share_exactly_0_20": THRESHOLD == 0.20,
            "original_0_70_ruling_not_replaced": True,
            "same_stratum_and_reuse_rules_retained": True,
            "thermal_or_lst_values_opened": False,
            "reflectance_or_optical_index_opened": False,
            "new_v6_2_coefficients_viewed": False,
            "gate_A_authorized": False,
        },
        "input_sha256": {
            str(SOURCE_TABLE.relative_to(REPO)): sha256(SOURCE_TABLE),
        },
        "implementation_sha256": {
            str(Path(__file__).resolve().relative_to(REPO)): sha256(Path(__file__).resolve()),
            "src/urban_cooling_v2/lead_lag_feasibility.py": sha256(
                REPO / "src/urban_cooling_v2/lead_lag_feasibility.py"
            ),
        },
    }
    manifest_path = OUTPUT / "analysis_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    panel_lines = []
    for panel in result["panels"].values():
        status = "PASS" if panel["all_nonzero_strata_pass"] else "FAIL"
        panel_lines.append(
            f"| {panel['city']} | {panel['season_window']} | "
            f"{panel['nonzero_strata']} | {panel['share_failure_count']} | "
            f"{panel['reuse_failure_count']} | **{status}** |"
        )
    readme = f"""# D1c 20% matched-pair-share sensitivity

This is a **nonbinding post-support sensitivity** requested after the frozen 70%
result was known. It does not replace D009/D019 or authorize Gate A.

## Result

The ruling is still **{result['ruling']}**. Although the pooled city shares are
45.5% in Phoenix and 31.8% in Los Angeles, the frozen decision structure is not a
pooled-city test: one season window must pass every nonzero year x sensor stratum.

| City | Season window | Nonzero strata | Share failures | Reuse failures | Panel |
|---|---|---:|---:|---:|---|
{chr(10).join(panel_lines)}

Every panel still contains at least one zero-share stratum, which fails even a
20% minimum. Los Angeles also retains three failures of the separate 25%
acquisition-reuse rule. Therefore neither city has a qualifying season window.

## Interpretation boundary

The 20% cutoff is not stated in the professor's documents and was introduced only
as a user-requested sensitivity. This package reads the existing 56-row Fmask
feasibility table only; it opens no HLS reflectance, optical index, ECOSTRESS LST,
or new coefficient. It is D1c lead-lag evidence, not the D1b block-pass
connectivity report.

## Contents

- `tables/d1c_20pct_strata.csv`: all 56 required strata with 20% share and
  unchanged 25% acquisition-reuse evaluations.
- `analysis_manifest.json`: exact input hash, panel summaries, checks, and ruling.
- `checksums.txt`: SHA-256 for every other file in this package.
"""
    (OUTPUT / "README.md").write_text(readme, encoding="utf-8")

    checksum_lines = []
    for path in sorted(item for item in OUTPUT.rglob("*") if item.is_file()):
        if path.name == "checksums.txt":
            continue
        checksum_lines.append(f"{sha256(path)}  {path.relative_to(OUTPUT)}")
    (OUTPUT / "checksums.txt").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(OUTPUT), "ruling": result["ruling"]}, indent=2))


if __name__ == "__main__":
    main()
