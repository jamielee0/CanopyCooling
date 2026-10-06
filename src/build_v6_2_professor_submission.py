#!/usr/bin/env python3
"""Build the lean six-item v6.2 professor submission folder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from build_v6_2_professor_review_bundle import (
    copy_and_record,
    sha256,
    write_checksums,
    write_file_index,
)
from build_v6_2_tcc_span_figure import build as build_tcc_figure


SECTION_FILES: dict[str, list[tuple[str, str, str]]] = {
    "01_protocol_and_conformance": [
        ("docs/v2/v6_2/protocol_v6_2.yml", "protocol_v6_2.yml", "Controlling completed protocol."),
        ("docs/v2/v6_2/decision_log_v6_2.md", "decision_log_v6_2.md", "Prospective decisions and recorded results."),
        ("docs/v2/v6_2/conformance_memo.md", "conformance_memo.md", "Retained, revised, archived, retired, and quarantined components."),
        ("docs/v2/v6_2/prior_thermal_access.md", "prior_thermal_access.md", "Thermal-access boundary."),
        ("src/urban_cooling_v2/freeze_v6_2_manifest.py", "code/freeze_v6_2_manifest.py", "Control-boundary manifest logic."),
        ("src/urban_cooling_v2/v6_2_output_boundary.py", "code/v6_2_output_boundary.py", "Scientific, retired, and synthetic output boundary."),
        ("src/test_v6_2_output_boundary.py", "code/test_v6_2_output_boundary.py", "Network-free output-boundary test."),
    ],
    "03_corrected_stage1": [
        ("src/run_v6_2_d1d_stage1_precision.py", "code/run_v6_2_d1d_stage1_precision.py", "Five-pass native-grid Stage 1 runner."),
        ("src/urban_cooling_v2/stage1_precision_census.py", "code/stage1_precision_census.py", "Per-block-pass slope, spatial uncertainty, and stability logic."),
        ("src/test_v6_2_stage1_precision_census.py", "code/test_v6_2_stage1_precision_census.py", "Network-free Stage 1 implementation tests."),
        ("src/run_v6_2_d1d_tcc_span_screen.py", "code/run_v6_2_d1d_tcc_span_screen.py", "Official Science TCC eligibility screen."),
        ("src/urban_cooling_v2/science_tcc_screen.py", "code/science_tcc_screen.py", "Science TCC validity and span helpers."),
        ("src/test_v6_2_science_tcc_screen.py", "code/test_v6_2_science_tcc_screen.py", "Network-free official-TCC tests."),
        ("src/build_v6_2_d1d_figures.py", "code/build_v6_2_d1d_figures.py", "Implementation-only diagnostic figure builder."),
        ("src/build_v6_2_d1d_memo.py", "code/build_v6_2_d1d_memo.py", "Stage 1 memo builder."),
        ("src/build_v6_2_d1d_tables.mjs", "code/build_v6_2_d1d_tables.mjs", "Open-table builder."),
        ("src/finalize_v6_2_d1d_package.py", "code/finalize_v6_2_d1d_package.py", "Stage 1 package verifier."),
        ("src/build_v6_2_tcc_span_figure.py", "code/build_v6_2_tcc_span_figure.py", "Current official-TCC presentation figure builder."),
        ("src/test_v6_2_tcc_span_figure.py", "code/test_v6_2_tcc_span_figure.py", "Network-free presentation-figure validation tests."),
        ("deliverables/D1d_tcc_span_screen_v6_2_20260902/README.md", "current_result/README.md", "Current controlling Stage 1 eligibility result."),
        ("deliverables/D1d_tcc_span_screen_v6_2_20260902/analysis_manifest.json", "current_result/analysis_manifest.json", "Current official-TCC row-level evidence and input hashes."),
        ("deliverables/D1d_stage1_precision_v6_2_20260902/verification.json", "implementation_only/verification.json", "Verification that open outputs contain no point estimates."),
        ("deliverables/D1d_stage1_precision_v6_2_20260902/sealed_file_pointer.json", "implementation_only/sealed_file_pointer.json", "Hash-only pointer; no sealed coefficient file is included."),
        ("deliverables/D1d_stage1_precision_v6_2_20260902/analysis_manifest.json", "implementation_only/proxy_run_manifest.json", "Five-pass implementation run, explicitly noncontrolling because it used inherited proxies."),
        ("deliverables/D1d_stage1_precision_v6_2_20260902/tables/d1d_stage1_se.csv", "implementation_only/stage1_estimability_uncertainty_stability.csv", "Open diagnostic table without coefficient point estimates."),
        ("deliverables/D1d_stage1_precision_v6_2_20260902/tables/d1d_n_required.csv", "implementation_only/planning_counts.csv", "Open planning table; no coefficient point estimates."),
    ],
    "04_demand_geometry_ruling": [
        ("deliverables/D1a_demand_geometry_v6_2_20260830/memo.pdf", "demand_geometry_memo.pdf", "Binding strict demand-geometry memo."),
        ("deliverables/D1a_demand_geometry_v6_2_20260830/analysis_manifest.json", "evidence/strict_analysis_manifest.json", "Binding strict numerical result."),
        ("deliverables/D1a_demand_geometry_v6_2_20260830/tables/d1a_condition_index.csv", "evidence/strict_condition_index.csv", "Strict condition-index evidence."),
        ("deliverables/D1a_demand_geometry_v6_2_20260830/tables/d1a_pairwise.csv", "evidence/strict_pairwise.csv", "Strict pairwise evidence."),
        ("deliverables/D1a_demand_geometry_v6_2_20260830/figures/d1a_support.png", "figures/demand_geometry_support.png", "Current binding VPD support figure for slides."),
        ("deliverables/D1a_demand_geometry_v6_2_20260830/figures/d1a_support.svg", "figures/demand_geometry_support.svg", "Editable vector version of the current VPD figure."),
        ("deliverables/D1a_parsimonious_sensitivity_v6_2_20260830/analysis_manifest.json", "evidence/parsimonious_sensitivity_manifest.json", "Nonbinding realistic sensitivity that motivates supervisor review."),
        ("src/run_v6_2_d1a_demand_geometry.py", "code/run_v6_2_d1a_demand_geometry.py", "Binding strict demand-geometry runner."),
        ("src/run_v6_2_d1a_parsimonious_sensitivity.py", "code/run_v6_2_d1a_parsimonious_sensitivity.py", "Nonbinding parsimonious sensitivity runner."),
        ("src/urban_cooling_v2/demand_geometry_audit.py", "code/demand_geometry_audit.py", "Demand-support diagnostics and ruling logic."),
        ("src/test_v6_2_demand_geometry_audit.py", "code/test_v6_2_demand_geometry_audit.py", "Network-free demand-geometry tests."),
        ("src/build_v6_2_d1a_memo.py", "code/build_v6_2_d1a_memo.py", "Demand memo builder."),
        ("src/build_v6_2_d1a_tables.mjs", "code/build_v6_2_d1a_tables.mjs", "Demand evidence-table builder."),
    ],
    "05_block_pass_connectivity": [
        ("deliverables/D1b_connectivity_v6_2_20260830/memo.pdf", "connectivity_memo.pdf", "Current eight-combination connectivity report."),
        ("deliverables/D1b_connectivity_v6_2_20260830/analysis_manifest.json", "evidence/analysis_manifest.json", "Machine-readable connectivity results."),
        ("deliverables/D1b_connectivity_v6_2_20260830/tables/d1b_connectivity.csv", "evidence/connectivity_table.csv", "All required city-window-view combinations."),
        ("deliverables/D1b_connectivity_v6_2_20260830/figures/d1b_hist.png", "figures/passes_per_block.png", "Current passes-per-block distributions."),
        ("deliverables/D1b_connectivity_v6_2_20260830/figures/d1b_hist.svg", "figures/passes_per_block.svg", "Editable vector passes-per-block figure."),
        ("deliverables/D1b_connectivity_v6_2_20260830/figures/d1b_map.png", "figures/connectivity_map.png", "Current Phoenix and Los Angeles connectivity map."),
        ("deliverables/D1b_connectivity_v6_2_20260830/figures/d1b_map.svg", "figures/connectivity_map.svg", "Editable vector connectivity map."),
        ("src/run_v6_2_d1b_connectivity.py", "code/run_v6_2_d1b_connectivity.py", "Connectivity report runner."),
        ("src/urban_cooling_v2/connectivity_audit.py", "code/connectivity_audit.py", "Block-pass graph and support calculations."),
        ("src/test_v6_2_connectivity_audit.py", "code/test_v6_2_connectivity_audit.py", "Network-free connectivity tests."),
        ("src/build_v6_2_d1b_memo.py", "code/build_v6_2_d1b_memo.py", "Connectivity memo builder."),
        ("src/build_v6_2_d1b_table.mjs", "code/build_v6_2_d1b_table.mjs", "Connectivity table builder."),
    ],
    "06_raw_asset_inventory": [
        ("outputs/01a051dd-0bc4-76d1-bd67-65083c7f05fe/raw_asset_inventory_v6_2.xlsx", "raw_asset_inventory.xlsx", "Clean two-sheet inventory: product status/gaps plus per-file locations, byte counts, and hashes."),
    ],
}


ROOT_README = """# Professor submission: six requested v6.2 items

This folder contains only the six requested deliverables, their necessary
reproducibility code/tests, compact evidence, and current explanatory figures.
It contains no lead-lag package, no superseded figure, no raw raster, and no sealed
coefficient file.

## Version note

The request says v6.1 once. The attached Working Guide, proposal, schedule, protocol
names, branch, and folder conventions all say v6.2. This submission therefore uses
v6.2 and discloses the discrepancy instead of relabelling the work.

## Current status

1. Protocol/conformance: complete on branch `v6.2`; the inherited baseline is tagged
   `v2-inherited-pre-v6.2`.
2. Independent Collection 3 audit: passed and includes its recorded source evidence.
3. Corrected Stage 1: the per-block-pass implementation and sealing controls are
   included. The official Science TCC screen is controlling and found 0/13,509
   eligible block-passes, so the final thermal rerun did not proceed.
4. Demand-geometry: the frozen evidence-based ruling is DROP. At user direction the
   optional branch is retained only as inactive/on hold pending supervisor review;
   it is not permitted in a current model.
5. Connectivity: complete and supportable for planning, with the stated inherited
   historical-incidence limitation.
6. Raw assets: a plain have/partial/missing status table and a detailed per-file
   inventory. Acquisition scripts are not part of this deliverable.

PNG figures are ready for slides. Matching SVGs are included for editing. Every
copied or generated file is mapped in `FILE_INDEX.csv` and verified by
`checksums.sha256`.
"""


SECTION_READMES = {
    "01_protocol_and_conformance": """# 1. Protocol and conformance

The controlling work is v6.2, not relabelled v6.1. See `BRANCH_AND_TAG.txt` for the
current branch, HEAD, inherited tag, and tagged commit. The protocol, decision log,
conformance memo, and access boundary are included with the control-boundary code.
""",
    "02_collection3_catalogue_audit": """# 2. Independent Collection 3 catalogue audit

This is the complete tracked foundation-audit packet, including recorded CMR source
responses, query counts, tile-to-pass reconciliation, exclusions, gaps, geometry
checks, sampled HRRR joins, implementation, and independent tests. Historical counts
are provenance only and are not the new v6.2 sample.
""",
    "03_corrected_stage1": """# 3. Corrected Stage 1 implementation

The code estimates one canopy slope for each block within each pass and uses spatial
resampling for uncertainty. Point estimates remain sealed; the sealed file itself is
not included. `implementation_only/` documents the five-pass implementation run but
uses inherited nonconforming proxies and is not the controlling scientific result.
`current_result/` is the controlling official Science TCC screen: 0 of 13,509
candidate block-passes met the frozen 0.20 canopy-span floor, so no current thermal
Stage 1 rerun or standard error was estimable.
""",
    "04_demand_geometry_ruling": """# 4. Demand-geometry ruling

The prospectively frozen binding rule yields DROP for both VPD interactions. The
strict analysis fails both cities. The later parsimonious sensitivity is nonbinding:
Phoenix passes, while Los Angeles misses the common-support-width floor. At user
direction the branch is preserved only as inactive/on hold for supervisor review;
no VPD interaction may enter the current model.
""",
    "05_block_pass_connectivity": """# 5. Block-pass connectivity

The memo and table report Phoenix and Los Angeles under both proposed windows and
15/25 degree view sets. The maps and distributions are current planning figures.
The graph is supportable for planning, but it uses inherited historical incidence
and does not itself authorize Gate A or define the final Collection 3 sample.
""",
    "06_raw_asset_inventory": """# 6. Raw-asset inventory

This section answers only: **which required data are in hand, and which are not?**
It does not contain acquisition code, analysis code, credentials, or raw rasters.

| Product | Status | What is in hand | What is still missing |
|---|---|---|---|
| HLS V2 Fmask | HAVE | 149 verified files for Phoenix and Los Angeles; 2019–2025; individual SHA-256 hashes | Nothing else needed before Gate A for cloud screening |
| HLS V2 reflectance | NOT YET / DEFERRED | No reflectance values were opened | Required bands would be acquired only after Gate A authorization |
| Science TCC v2025-6 | HAVE | 14 verified files; both cities × 2019–2025; canopy cover and standard error | Nothing else needed for the current canopy-span screen |
| USGS 3DEP 10 m elevation | HAVE | 2 verified city-domain files; Earth Engine snapshot ends 2022-05-04 | A newer tile-state refresh only if the supervisor requires it |
| ECOSTRESS Collection 3 thermal | CATALOGUE ONLY | Reproducible catalogue metadata; no new thermal values opened | Approved thermal products have not been acquired |
| ECOSTRESS L1B viewing geometry | PARTIAL | 762 geometry rows checked; 734 recovered reconstruction artifacts verified | Final Collection 3 geometry completeness must be resolved for the study sample |
| HRRR / weather | PARTIAL / HISTORICAL | 219 passes, 438 links, and 413 inherited assets; 10/10 sampled joins passed | Final sample-specific weather must be reacquired and frozen |
| Precipitation | NOT YET | No frozen pre-Gate A precipitation payload | Exact product, release, years, and files remain to be selected and acquired |
| Contextual data | MIXED | Frozen city/block geometry is available; inherited land-use context exists | Final land-use and other contextual releases remain to be frozen where retained |

`raw_asset_inventory.xlsx` contains only two inventory sheets: a product-level
status/gap table and per-file evidence with locations, coverage, byte counts, and
checksums where available. It records 165 verified acquired files totaling
800,091,676 bytes. Missing data are valid inventory findings; they are not presented
as if downloaded.
""",
}


def record_generated(
    output: Path,
    relative: Path,
    category: str,
    status: str,
    description: str,
    records: list[dict[str, str | int]],
) -> None:
    path = output / relative
    records.append(
        {
            "category": category,
            "status": status,
            "bundle_path": relative.as_posix(),
            "source_path": "GENERATED_FOR_THIS_SUBMISSION",
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "description": description,
        }
    )


def write_branch_tag(repo: Path, target: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo, check=True, text=True, capture_output=True
        ).stdout.strip()

    target.write_text(
        "\n".join(
            [
                f"current_branch={git('branch', '--show-current')}",
                f"current_head={git('rev-parse', 'HEAD')}",
                "previous_version_tag=v2-inherited-pre-v6.2",
                f"tag_object={git('rev-parse', 'v2-inherited-pre-v6.2')}",
                f"tagged_commit={git('rev-parse', 'v2-inherited-pre-v6.2^{}')}",
                "tag_message=Last inherited commit before v6.2 control-boundary freeze",
                "",
            ]
        ),
        encoding="utf-8",
    )


def build(repo: Path, output: Path) -> dict[str, int | str]:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing submission: {output}")
    output.mkdir(parents=True)
    records: list[dict[str, str | int]] = []

    (output / "README_FIRST.md").write_text(ROOT_README, encoding="utf-8")
    record_generated(output, Path("README_FIRST.md"), "guide", "CURRENT", "Submission scope and status guide.", records)

    for section, files in SECTION_FILES.items():
        section_root = output / section
        section_root.mkdir(parents=True, exist_ok=True)
        (section_root / "README.md").write_text(SECTION_READMES[section], encoding="utf-8")
        record_generated(output, Path(section) / "README.md", "guide", "CURRENT", "Section interpretation guide.", records)
        for source, target, description in files:
            category = "figure" if Path(target).parts[0] == "figures" else "deliverable"
            copy_and_record(
                repo,
                output,
                source,
                Path(section) / target,
                category,
                "CURRENT_OR_EXPLICITLY_LABELLED_IMPLEMENTATION_ONLY",
                description,
                records,
            )

    audit_section = output / "02_collection3_catalogue_audit"
    audit_section.mkdir(parents=True, exist_ok=True)
    (audit_section / "README.md").write_text(
        SECTION_READMES["02_collection3_catalogue_audit"], encoding="utf-8"
    )
    record_generated(output, Path("02_collection3_catalogue_audit/README.md"), "guide", "CURRENT", "Section interpretation guide.", records)
    for source in sorted((repo / "docs/v2/v6_2/foundation_audit").rglob("*")):
        if source.is_file():
            relative = source.relative_to(repo / "docs/v2/v6_2/foundation_audit")
            copy_and_record(
                repo,
                output,
                source.relative_to(repo),
                Path("02_collection3_catalogue_audit/evidence") / relative,
                "deliverable",
                "FOUNDATION_PASS",
                "Independent foundation-audit evidence, including recorded source responses.",
                records,
            )
    for source, target, description in (
        ("src/urban_cooling_v2/independent_foundation_audit.py", "code/independent_foundation_audit.py", "Independent audit implementation."),
        ("src/test_v6_2_independent_foundation_audit.py", "code/test_v6_2_independent_foundation_audit.py", "Network-free independent audit tests."),
    ):
        copy_and_record(
            repo, output, source, Path("02_collection3_catalogue_audit") / target,
            "deliverable", "FOUNDATION_PASS", description, records
        )

    branch_file = output / "01_protocol_and_conformance/BRANCH_AND_TAG.txt"
    write_branch_tag(repo, branch_file)
    record_generated(output, branch_file.relative_to(output), "provenance", "CURRENT", "Branch and inherited-tag evidence.", records)

    tcc_manifest = repo / "deliverables/D1d_tcc_span_screen_v6_2_20260902/analysis_manifest.json"
    tcc_png = output / "03_corrected_stage1/figures/official_TCC_canopy_span.png"
    tcc_svg = output / "03_corrected_stage1/figures/official_TCC_canopy_span.svg"
    build_tcc_figure(tcc_manifest, tcc_png, tcc_svg)
    record_generated(output, tcc_png.relative_to(output), "figure", "CURRENT", "Official Science TCC canopy-span result for slides.", records)
    record_generated(output, tcc_svg.relative_to(output), "figure", "CURRENT", "Editable vector version of the official-TCC figure.", records)

    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.splitlines()
    (output / "SNAPSHOT_PROVENANCE.txt").write_text(
        "\n".join(
            [
                "snapshot_date=2026-09-03",
                f"git_commit={subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, check=True, text=True, capture_output=True).stdout.strip()}",
                f"worktree_dirty={str(bool(status)).lower()}",
                f"worktree_status_entry_count={len(status)}",
                "interpretation=FILE_INDEX.csv and checksums.sha256 identify the exact submission snapshot.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    record_generated(output, Path("SNAPSHOT_PROVENANCE.txt"), "provenance", "CURRENT", "Git snapshot disclosure.", records)

    write_file_index(output, records)
    checksum_count = write_checksums(output)
    return {
        "output": str(output),
        "indexed_items": len(records),
        "checksum_entries": checksum_count,
        "current_figure_files": sum(row["category"] == "figure" for row in records),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.repo.resolve(), args.output.resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
