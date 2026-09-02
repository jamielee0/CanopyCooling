#!/usr/bin/env python3
"""Write and verify the v6.2 initial-package index and checksum manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(root: Path, output_name: str = "checksums.sha256") -> None:
    output = root / output_name
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file()
        and path != output
        and "_workbook_previews" not in path.parts
    )
    output.write_text(
        "".join(f"{sha256(path)}  {path.relative_to(root)}\n" for path in files),
        encoding="utf-8",
    )
    for line in output.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        actual = sha256(root / relative)
        if actual != expected:
            raise RuntimeError(f"checksum mismatch: {relative}")


def write_screen_checksums(repo: Path) -> None:
    screen = repo / "deliverables/D1d_tcc_span_screen_v6_2_20260902"
    write_checksums(screen, "checksums.txt")


def write_referenced_checksums(repo: Path, package: Path) -> None:
    index = json.loads((package / "package_index.json").read_text(encoding="utf-8"))
    output = package / "referenced_artifacts.sha256"
    files: set[Path] = set()
    for item in index["items"]:
        target = repo / item["path"]
        if target.is_dir():
            files.update(path for path in target.rglob("*") if path.is_file())
        elif target.is_file():
            files.add(target)
        else:
            raise FileNotFoundError(target)
    files.discard(output)
    files.discard(package / "checksums.sha256")
    output.write_text(
        "".join(f"{sha256(path)}  {path.relative_to(repo)}\n" for path in sorted(files)),
        encoding="utf-8",
    )
    for line in output.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        if sha256(repo / relative) != expected:
            raise RuntimeError(f"referenced checksum mismatch: {relative}")


def write_package_index(repo: Path, package: Path, allow_pending_outputs: bool = False) -> Path:
    items = [
        ("One-page decision summary", "COMPLETE", package / "one_page_summary.pdf", "Supervisor-facing status and Gate A recommendation"),
        ("Consolidated inventory workbook", "COMPLETE", package / "asset_inventory_and_package_index.xlsx", "Per-file hashes, asset gaps, and package index"),
        ("Controlling protocol", "CURRENT", repo / "docs/v2/v6_2/protocol_v6_2.yml", "Frozen v6.2 rules and current branch statuses"),
        ("Decision log", "CURRENT", repo / "docs/v2/v6_2/decision_log_v6_2.md", "Prospective decisions and results"),
        ("Conformance memo", "CURRENT", repo / "docs/v2/v6_2/conformance_memo.md", "Retained, revised, rebuilt, archived, and retired components"),
        ("Prior thermal-access record", "CURRENT", repo / "docs/v2/v6_2/prior_thermal_access.md", "Thermal access boundary"),
        ("Foundation audit", "PASS", repo / "docs/v2/v6_2/foundation_audit", "Independent catalogue and historical reconciliation"),
        ("D1a strict demand–geometry", "FAIL / BINDING", repo / "deliverables/D1a_demand_geometry_v6_2_20260830", "Full-nuisance VPD diagnostic"),
        ("D1a parsimonious sensitivity", "MIXED / NONBINDING", repo / "deliverables/D1a_parsimonious_sensitivity_v6_2_20260830", "Realistic VPD sensitivity"),
        ("D1a geometry reassessment", "FAIL / SUPPORTING", repo / "deliverables/D1a_geometry_recovery_reassessment_v6_2_20260901", "Recovered-geometry reassessment"),
        ("D1b connectivity", "PASS FOR PLANNING", repo / "deliverables/D1b_connectivity_v6_2_20260830", "Eight required connectivity combinations"),
        ("D1c lead–lag", "EXPLORATORY / DEMOTED", repo / "deliverables/D1c_leadlag_v6_2_20260902", "Inherited centred-HLS feasibility count"),
        ("D1c HLS inventory", "COMPLETE", repo / "deliverables/D1c_hls_inventory_v6_2_20260902", "Fmask catalogue and selection evidence"),
        ("D1d preliminary proxy screen", "SUPERSEDED DIAGNOSTIC", repo / "deliverables/D1d_stage1_precision_v6_2_20260902", "NLCD proxy stop; not controlling"),
        ("D1d official TCC screen", "STOP / CONTROLLING", repo / "deliverables/D1d_tcc_span_screen_v6_2_20260902", "Official canopy-span eligibility result"),
        ("Acquisition write-up", "COMPLETE", repo / "docs/v2/v6_2/data_acquisition_20260902.md", "HLS, TCC, and 3DEP acquisition record"),
    ]
    records = []
    for item, status, path, purpose in items:
        if not path.exists() and not (allow_pending_outputs and path.parent == package):
            raise FileNotFoundError(path)
        records.append({
            "item": item,
            "status": status,
            "path": str(path.relative_to(repo)),
            "purpose": purpose,
        })
    out = package / "package_index.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"schema_version": "1.0", "items": records}, indent=2) + "\n", encoding="utf-8")
    return out


def write_readme(package: Path) -> None:
    (package / "README.md").write_text(
        """# Urban Tree Cooling v6.2 initial package — 2026-09-02

This package closes the pre–Gate A checks requested for the first delivery. Start
with `one_page_summary.pdf`; use `asset_inventory_and_package_index.xlsx` for the
per-file inventory and detailed package map.

## Current ruling

Do **not** begin Gate A under the current frozen design. The official Science TCC
screen found zero of 13,509 candidate block-passes meeting the frozen `p10–p90 >=
0.20` canopy-span requirement; the observed maximum was 0.18410. Because this was
an optimistic nonthermal screen, a thermal-complete mask cannot create an eligible
block-pass. No conditional thermal Stage 1 rerun was performed.

The VPD branch is **inactive on hold**, not dropped. The binding full-nuisance check
fails both cities; the nonbinding parsimonious sensitivity passes Phoenix while Los
Angeles misses only the common-support-width floor (0.300 versus 0.500 kPa). A
supervisor keep/drop/amend ruling is still required before the branch can activate.

## Data boundary

The verified inventory contains 149 HLS Fmask files, 14 Science TCC files, and two
3DEP files (165 files; 800,091,676 bytes). Every file has a local SHA-256. The 16
Drive-hosted TCC/3DEP files also match Google MD5 metadata. No new thermal or HLS
reflectance values were opened for acquisition or the TCC screen.

`checksums.sha256` covers the package files; `referenced_artifacts.sha256` covers the
files named by the package index, including files inside indexed evidence directories.
Workbook preview PNGs are temporary visual-QA artifacts and are intentionally excluded.
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--index-only", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    package = repo / "deliverables/Initial_Package_v6_2_20260902"
    package.mkdir(parents=True, exist_ok=True)
    index = write_package_index(repo, package, allow_pending_outputs=args.index_only)
    if args.index_only:
        print(json.dumps({"package_index": str(index)}))
        return
    for required in (package / "one_page_summary.pdf", package / "asset_inventory_and_package_index.xlsx"):
        if not required.exists():
            raise FileNotFoundError(required)
    write_readme(package)
    write_screen_checksums(repo)
    write_referenced_checksums(repo, package)
    write_checksums(package)
    print(json.dumps({"package": str(package), "status": "verified"}))


if __name__ == "__main__":
    main()
