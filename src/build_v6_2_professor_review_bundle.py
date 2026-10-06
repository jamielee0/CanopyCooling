#!/usr/bin/env python3
"""Assemble a safe, checksummed v6.2 professor-review code and figure bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Iterable


PROHIBITED_PARTS = {"__pycache__", "raw", "sealed", "sealed_coefficients"}


CURRENT_FIGURES = [
    (
        "deliverables/D1a_demand_geometry_v6_2_20260830/figures/d1a_support.png",
        "02_figures/current_and_supporting/D1a_strict_VPD_support.png",
        "Binding full-nuisance atmospheric-demand support diagnostic.",
    ),
    (
        "deliverables/D1a_demand_geometry_v6_2_20260830/figures/d1a_support.svg",
        "02_figures/current_and_supporting/D1a_strict_VPD_support.svg",
        "Vector version of the binding atmospheric-demand figure.",
    ),
    (
        "deliverables/D1a_geometry_recovery_reassessment_v6_2_20260901/figures/d1a_support.png",
        "02_figures/current_and_supporting/D1a_geometry_reassessment.png",
        "Supporting recovered-geometry atmospheric-demand reassessment.",
    ),
    (
        "deliverables/D1a_geometry_recovery_reassessment_v6_2_20260901/figures/d1a_support.svg",
        "02_figures/current_and_supporting/D1a_geometry_reassessment.svg",
        "Vector version of the recovered-geometry reassessment.",
    ),
    (
        "deliverables/D1b_connectivity_v6_2_20260830/figures/d1b_hist.png",
        "02_figures/current_and_supporting/D1b_connectivity_pass_distribution.png",
        "Passes-per-block distributions for the eight connectivity combinations.",
    ),
    (
        "deliverables/D1b_connectivity_v6_2_20260830/figures/d1b_hist.svg",
        "02_figures/current_and_supporting/D1b_connectivity_pass_distribution.svg",
        "Vector version of the connectivity distribution figure.",
    ),
    (
        "deliverables/D1b_connectivity_v6_2_20260830/figures/d1b_map.png",
        "02_figures/current_and_supporting/D1b_connectivity_map.png",
        "Spatial connectivity and component structure for Phoenix and Los Angeles.",
    ),
    (
        "deliverables/D1b_connectivity_v6_2_20260830/figures/d1b_map.svg",
        "02_figures/current_and_supporting/D1b_connectivity_map.svg",
        "Vector version of the connectivity map.",
    ),
    (
        "deliverables/D1c_fmask_reassessment_v6_2_20260902/figures/d1c_timing.png",
        "02_figures/current_and_supporting/D1c_verified_lead_lag_timing.png",
        "Current Fmask-screened pre/post lag distribution; confirmatory support failed.",
    ),
    (
        "deliverables/D1c_fmask_reassessment_v6_2_20260902/figures/d1c_timing.svg",
        "02_figures/current_and_supporting/D1c_verified_lead_lag_timing.svg",
        "Vector version of the current lead-lag timing figure.",
    ),
]


SUPERSEDED_FIGURES = [
    (
        "deliverables/D1c_leadlag_v6_2_20260902/figures/d1c_timing.png",
        "02_figures/superseded_diagnostics/D1c_inherited_centered_product_timing_SUPERSEDED.png",
        "Superseded inherited centered-product timing diagnostic.",
    ),
    (
        "deliverables/D1c_leadlag_v6_2_20260902/figures/d1c_timing.svg",
        "02_figures/superseded_diagnostics/D1c_inherited_centered_product_timing_SUPERSEDED.svg",
        "Vector version of the superseded centered-product diagnostic.",
    ),
    (
        "deliverables/D1d_stage1_precision_v6_2_20260902/figures/d1d_n_required.png",
        "02_figures/superseded_diagnostics/D1d_proxy_sample_size_SUPERSEDED.png",
        "Superseded Stage 1 planning figure based on inherited proxy inputs.",
    ),
    (
        "deliverables/D1d_stage1_precision_v6_2_20260902/figures/d1d_n_required.svg",
        "02_figures/superseded_diagnostics/D1d_proxy_sample_size_SUPERSEDED.svg",
        "Vector version of the superseded sample-size figure.",
    ),
    (
        "deliverables/D1d_stage1_precision_v6_2_20260902/figures/d1d_se_distribution.png",
        "02_figures/superseded_diagnostics/D1d_proxy_SE_distribution_SUPERSEDED.png",
        "Superseded Stage 1 standard-error diagnostic based on inherited proxy inputs.",
    ),
    (
        "deliverables/D1d_stage1_precision_v6_2_20260902/figures/d1d_se_distribution.svg",
        "02_figures/superseded_diagnostics/D1d_proxy_SE_distribution_SUPERSEDED.svg",
        "Vector version of the superseded standard-error diagnostic.",
    ),
]


REPORTS = [
    (
        "deliverables/Initial_Package_v6_2_20260902/one_page_summary.pdf",
        "01_start_here/one_page_decision_summary.pdf",
        "CURRENT",
        "Expanded six-section supervisor decision page.",
    ),
    (
        "deliverables/Initial_Package_v6_2_20260902/asset_inventory_and_package_index.xlsx",
        "01_start_here/asset_inventory_and_package_index.xlsx",
        "CURRENT",
        "Verified raw-asset inventory and original package map.",
    ),
    (
        "deliverables/D1a_demand_geometry_v6_2_20260830/memo.pdf",
        "03_reports/current_and_supporting/D1a_strict_demand_geometry_memo.pdf",
        "BINDING_FAIL",
        "Strict atmospheric-demand support memo.",
    ),
    (
        "deliverables/D1a_geometry_recovery_reassessment_v6_2_20260901/memo.pdf",
        "03_reports/current_and_supporting/D1a_geometry_reassessment_memo.pdf",
        "SUPPORTING_FAIL",
        "Recovered-geometry sensitivity memo.",
    ),
    (
        "deliverables/D1b_connectivity_v6_2_20260830/memo.pdf",
        "03_reports/current_and_supporting/D1b_connectivity_memo.pdf",
        "PASS_FOR_PLANNING",
        "Eight-combination connectivity report.",
    ),
    (
        "deliverables/D1c_fmask_reassessment_v6_2_20260902/memo.pdf",
        "03_reports/current_and_supporting/D1c_Fmask_lead_lag_memo.pdf",
        "EXPLORATORY_DEMOTED",
        "Current quality-screened lead-lag feasibility memo.",
    ),
    (
        "deliverables/D1c_leadlag_v6_2_20260902/memo.pdf",
        "03_reports/superseded_diagnostics/D1c_centered_product_memo_SUPERSEDED.pdf",
        "SUPERSEDED",
        "Original inherited centered-product diagnostic.",
    ),
    (
        "deliverables/D1d_stage1_precision_v6_2_20260902/memo.pdf",
        "03_reports/superseded_diagnostics/D1d_proxy_stage1_memo_SUPERSEDED.pdf",
        "SUPERSEDED",
        "Inherited-proxy Stage 1 diagnostic; not the controlling stop.",
    ),
]


GOVERNANCE_FILES = [
    "docs/v2/v6_2/README.md",
    "docs/v2/v6_2/protocol_v6_2.yml",
    "docs/v2/v6_2/decision_log_v6_2.md",
    "docs/v2/v6_2/conformance_memo.md",
    "docs/v2/v6_2/prior_thermal_access.md",
    "docs/v2/v6_2/data_acquisition_20260902.md",
    "docs/v2/v6_2/output_isolation_manifest.csv",
    "docs/v2/v6_2/source_document_checksums.txt",
]


EVIDENCE_FILES = [
    "deliverables/D1a_demand_geometry_v6_2_20260830/analysis_manifest.json",
    "deliverables/D1a_demand_geometry_v6_2_20260830/tables/d1a_condition_index.csv",
    "deliverables/D1a_demand_geometry_v6_2_20260830/tables/d1a_pairwise.csv",
    "deliverables/D1a_parsimonious_sensitivity_v6_2_20260830/analysis_manifest.json",
    "deliverables/D1a_geometry_recovery_reassessment_v6_2_20260901/analysis_manifest.json",
    "deliverables/D1a_geometry_recovery_reassessment_v6_2_20260901/tables/d1a_condition_index.csv",
    "deliverables/D1a_geometry_recovery_reassessment_v6_2_20260901/tables/d1a_pairwise.csv",
    "deliverables/D1b_connectivity_v6_2_20260830/analysis_manifest.json",
    "deliverables/D1b_connectivity_v6_2_20260830/tables/d1b_connectivity.csv",
    "deliverables/D1c_fmask_reassessment_v6_2_20260902/analysis_manifest.json",
    "deliverables/D1c_fmask_reassessment_v6_2_20260902/tables/d1c_leadlag.csv",
    "deliverables/D1c_hls_inventory_v6_2_20260902/analysis_manifest.json",
    "deliverables/D1c_hls_inventory_v6_2_20260902/tables/hls_acquisitions.csv",
    "deliverables/D1c_hls_inventory_v6_2_20260902/tables/hls_fmask_download_plan.csv",
    "deliverables/D1c_hls_inventory_v6_2_20260902/tables/hls_pair_rows.csv",
    "deliverables/D1c_hls_inventory_v6_2_20260902/tables/hls_strata.csv",
    "deliverables/D1d_tcc_span_screen_v6_2_20260902/README.md",
    "deliverables/D1d_tcc_span_screen_v6_2_20260902/analysis_manifest.json",
    "deliverables/D1d_stage1_precision_v6_2_20260902/analysis_manifest.json",
    "deliverables/D1d_stage1_precision_v6_2_20260902/tables/d1d_n_required.csv",
    "deliverables/D1d_stage1_precision_v6_2_20260902/tables/d1d_stage1_se.csv",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_safe_source(relative: Path) -> None:
    lowered = {part.lower() for part in relative.parts}
    if lowered & PROHIBITED_PARTS or relative.suffix.lower() == ".pyc":
        raise ValueError(f"Prohibited bundle source: {relative}")


def copy_and_record(
    repo: Path,
    output: Path,
    source_relative: str | Path,
    bundle_relative: str | Path,
    category: str,
    status: str,
    description: str,
    records: list[dict[str, str | int]],
) -> None:
    source_relative = Path(source_relative)
    bundle_relative = Path(bundle_relative)
    assert_safe_source(source_relative)
    source = repo / source_relative
    if not source.is_file():
        raise FileNotFoundError(source)
    target = output / bundle_relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    records.append(
        {
            "category": category,
            "status": status,
            "bundle_path": bundle_relative.as_posix(),
            "source_path": source_relative.as_posix(),
            "bytes": target.stat().st_size,
            "sha256": sha256(target),
            "description": description,
        }
    )


def code_sources(repo: Path) -> list[Path]:
    paths: set[Path] = set()
    for pattern in (
        "run_v6_2_*.py",
        "build_v6_2_*.py",
        "build_v6_2_*.mjs",
        "finalize_v6_2_*.py",
        "wait_v6_2_*.py",
        "test_v6_2_*.py",
    ):
        paths.update(path.relative_to(repo) for path in (repo / "src").glob(pattern))
    paths.update(
        path.relative_to(repo)
        for path in (repo / "src/urban_cooling_v2").glob("*.py")
    )
    for relative in (
        "src/README.md",
        "src/run_v2_hitl_gate3_second_augmentation.py",
        "src/run_v2_step02_l1b_geometry.py",
        "src/store_earthdata_token.py",
        "configs/v2_cities.toml",
        "environment.yml",
        "AGENTS.md",
    ):
        paths.add(Path(relative))
    return sorted(paths)


def foundation_files(repo: Path) -> Iterable[Path]:
    root = repo / "docs/v2/v6_2/foundation_audit"
    for path in sorted(root.iterdir()):
        if path.is_file():
            yield path.relative_to(repo)


def write_readme(output: Path, records: list[dict[str, str | int]]) -> None:
    current_figures = sum(
        row["category"] == "figure" and row["status"] != "SUPERSEDED"
        for row in records
    )
    superseded_figures = sum(
        row["category"] == "figure" and row["status"] == "SUPERSEDED"
        for row in records
    )
    code_files = sum(row["category"] == "code" for row in records)
    text = f"""# Urban Tree Cooling v6.2 professor review bundle

Start with `01_start_here/one_page_decision_summary.pdf`.

This folder is a snapshot of the current v6.2 pre-Gate A work. It contains
{code_files} source/configuration files, {current_figures} current or supporting
figure files, {superseded_figures} explicitly separated superseded figure files,
the principal memos, governance records, and compact evidence tables. PNG files
are convenient for slides; matching SVG files are editable vector versions.

## Scientific status in one paragraph

The independent foundation audit passed, and the eight-combination connectivity
report is usable for planning. The official Science TCC canopy-span screen found
zero eligible block-passes under the frozen 0.20 requirement, so Gate A should not
begin under the current design. Exact HLS lead-lag timing is now verified, but only
41 of 110 candidate records formed quality-screened pairs and confirmatory support
failed. The optional atmospheric-demand branch remains inactive and on hold pending
a supervisor keep/drop/amend ruling.

## Folder map

- `01_start_here/`: the expanded one-page decision summary and asset inventory.
- `02_figures/current_and_supporting/`: figures that may be shown with their stated
  status and limitations.
- `02_figures/superseded_diagnostics/`: historical diagnostics. These must be
  labelled superseded and must not be presented as controlling results.
- `03_reports/`: current/supporting memos and a separate superseded subfolder.
- `04_evidence/`: compact manifests and tables; no raw rasters or thermal layers.
- `05_code/`: the current working-tree source snapshot, tests, configuration, and
  environment file. The complete `urban_cooling_v2` Python package is included to
  avoid hiding imports behind a curated script list.
- `06_governance/`: protocol, decision log, conformance, acquisition, and access
  records.
- `FILE_INDEX.csv`: source-to-bundle mapping, status, size, and SHA-256 for every
  copied item.
- `checksums.sha256`: hashes for every file in this bundle except itself.
- `SNAPSHOT_PROVENANCE.txt`: Git commit and dirty-worktree disclosure.

## Figure talking guide

1. `D1a_strict_VPD_support`: binding result; both cities fail the strict support rule.
2. `D1a_geometry_reassessment`: supporting sensitivity; it does not reverse D1a.
3. `D1b_connectivity_*`: planning evidence across both cities, two windows, and two
   view-angle sets; the underlying incidence is inherited historical evidence.
4. `D1c_verified_lead_lag_timing`: 41 verified pairs; show as exploratory timing
   feasibility, not a confirmatory effect result.
5. Files containing `SUPERSEDED` are included only for transparent design history.

## Deliberate exclusions

Raw data, credentials, Earthdata tokens, HLS reflectance, ECOSTRESS thermal values,
and sealed coefficient files are not copied. No coefficient values are exposed by
this bundle. The bundle does not replace the controlling repository or authorize
Gate A.
"""
    (output / "README_FIRST.md").write_text(text, encoding="utf-8")


def write_file_index(output: Path, records: list[dict[str, str | int]]) -> None:
    fields = [
        "category",
        "status",
        "bundle_path",
        "source_path",
        "bytes",
        "sha256",
        "description",
    ]
    with (output / "FILE_INDEX.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(records, key=lambda row: str(row["bundle_path"])))


def write_provenance(repo: Path, output: Path) -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    (output / "SNAPSHOT_PROVENANCE.txt").write_text(
        "\n".join(
            [
                "snapshot_date=2026-09-03",
                f"git_commit={commit}",
                f"worktree_dirty={str(bool(status)).lower()}",
                f"worktree_status_entry_count={len(status)}",
                "interpretation=FILE_INDEX.csv and checksums.sha256 identify the exact copied working-tree snapshot.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_checksums(output: Path) -> int:
    checksum_file = output / "checksums.sha256"
    files = sorted(
        path for path in output.rglob("*")
        if path.is_file() and path != checksum_file
    )
    checksum_file.write_text(
        "".join(f"{sha256(path)}  {path.relative_to(output).as_posix()}\n" for path in files),
        encoding="utf-8",
    )
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        if sha256(output / relative) != expected:
            raise RuntimeError(f"Checksum verification failed: {relative}")
    return len(files)


def build(repo: Path, output: Path) -> dict[str, int | str]:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing bundle: {output}")
    output.mkdir(parents=True)
    records: list[dict[str, str | int]] = []

    for source in code_sources(repo):
        copy_and_record(
            repo,
            output,
            source,
            Path("05_code") / source,
            "code",
            "CURRENT_WORKTREE_SNAPSHOT",
            "v6.2 code, test, configuration, or direct local dependency.",
            records,
        )

    for source, target, description in CURRENT_FIGURES:
        copy_and_record(
            repo, output, source, target, "figure", "CURRENT_OR_SUPPORTING", description, records
        )
    for source, target, description in SUPERSEDED_FIGURES:
        copy_and_record(
            repo, output, source, target, "figure", "SUPERSEDED", description, records
        )
    for source, target, status, description in REPORTS:
        copy_and_record(repo, output, source, target, "report", status, description, records)

    for source in GOVERNANCE_FILES:
        copy_and_record(
            repo,
            output,
            source,
            Path("06_governance") / Path(source).name,
            "governance",
            "CURRENT",
            "Controlling or explanatory v6.2 governance record.",
            records,
        )

    for source in EVIDENCE_FILES:
        relative = Path(source)
        target = Path("04_evidence/workstreams") / relative.relative_to("deliverables")
        copy_and_record(
            repo,
            output,
            source,
            target,
            "evidence",
            "CURRENT_OR_DISCLOSED_DIAGNOSTIC",
            "Compact workstream evidence; see source package status.",
            records,
        )

    for source in foundation_files(repo):
        target = Path("04_evidence/foundation_audit") / source.name
        copy_and_record(
            repo,
            output,
            source,
            target,
            "evidence",
            "FOUNDATION_PASS",
            "Independent foundation-audit top-level evidence.",
            records,
        )

    write_readme(output, records)
    write_file_index(output, records)
    write_provenance(repo, output)
    checksum_count = write_checksums(output)
    return {
        "output": str(output),
        "copied_items": len(records),
        "checksum_entries": checksum_count,
        "code_files": sum(row["category"] == "code" for row in records),
        "figure_files": sum(row["category"] == "figure" for row in records),
        "report_files": sum(row["category"] == "report" for row in records),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.repo.resolve(), args.output.resolve())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
