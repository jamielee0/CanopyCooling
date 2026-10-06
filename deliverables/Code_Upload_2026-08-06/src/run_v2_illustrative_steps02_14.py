#!/usr/bin/env python3
"""Build the offline, explicitly noncanonical Guide Steps 2--14 package.

This runner extends the quarantined Steps 2--13 demonstration with the six
Step-14 paper-layout figures, a canonical-STOP decision memo, an explicit
confirmatory-NOT-RUN report, and an illustrative package inventory.  Successful
execution validates only the demonstration package; it never opens or activates
the canonical Task-2, thermal/LST, holdout, or 2026 branches.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from run_v2_illustrative_steps02_13 import (
    FIGURE_SUFFIXES,
    REQUIRED_IDS_BY_STEP as BASE_REQUIRED_IDS_BY_STEP,
    _all_artifacts,
    _relative_label,
    _validate_roots,
    offline_network_guard,
    reject_canonical_pass_claims,
    run_package as run_steps02_13,
    validate_figure_names,
)
from urban_cooling_v2.illustrative_steps02_03 import (
    DEFAULT_SEED,
    STATUS,
    sha256_file,
    status_contract,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "data/processed/v2/illustrative_only/steps02_14"
DEFAULT_FIGURES_ROOT = ROOT / "figures/v2/illustrative_only/steps02_14"

REQUIRED_IDS_BY_STEP: dict[int, tuple[str, ...]] = {
    **BASE_REQUIRED_IDS_BY_STEP,
    14: (
        "F14.1",
        "F14.2",
        "F14.3",
        "F14.4",
        "F14.5",
        "F14.6",
        "M14.1",
        "M14.2",
        "P14.1",
    ),
}
REQUIRED_IDS = tuple(
    artifact_id
    for step in sorted(REQUIRED_IDS_BY_STEP)
    for artifact_id in REQUIRED_IDS_BY_STEP[step]
)

PUBLIC_SOURCE_FILES: tuple[tuple[str, str], ...] = (
    ("operating_rules", "AGENTS.md"),
    ("environment", "environment.yml"),
    ("configuration", "configs/v2_cities.toml"),
    ("configuration", "configs/v2_task2.toml"),
    ("requirements", "docs/v2/REQUIREMENTS.md"),
    ("decision_history", "docs/v2/DECISION_LOG.md"),
    ("gate_record", "data/processed/v2/task1/TASK1_GATE.md"),
    ("runner", "src/run_v2_illustrative_steps02_13.py"),
    ("runner", "src/run_v2_illustrative_steps02_14.py"),
    ("implementation", "src/urban_cooling_v2/illustrative_steps02_03.py"),
    ("implementation", "src/urban_cooling_v2/illustrative_steps02_08.py"),
    ("implementation", "src/urban_cooling_v2/illustrative_steps09_13.py"),
    ("implementation", "src/urban_cooling_v2/illustrative_step14_figures.py"),
    ("implementation", "src/urban_cooling_v2/illustrative_step14_documents.py"),
    ("test", "src/test_v2_illustrative_steps02_08.py"),
    ("test", "src/test_v2_illustrative_steps02_13.py"),
    ("test", "src/test_v2_illustrative_steps09_13.py"),
    ("test", "src/test_v2_illustrative_step14_figures.py"),
    ("test", "src/test_v2_illustrative_step14_documents.py"),
    ("test", "src/test_v2_illustrative_steps02_14.py"),
)


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _id_pattern(artifact_id: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(artifact_id)}(?![0-9])",
        flags=re.IGNORECASE,
    )


def index_required_ids(
    output_root: Path,
    figures_root: Path,
) -> dict[str, list[Path]]:
    """Require every canonical registry ID exactly once by artifact filename."""

    files = _all_artifacts(output_root, figures_root)
    index = {
        artifact_id: [
            path for path in files if _id_pattern(artifact_id).search(path.name)
        ]
        for artifact_id in REQUIRED_IDS
    }
    missing = [artifact_id for artifact_id, matches in index.items() if not matches]
    duplicated = {
        artifact_id: [str(path) for path in matches]
        for artifact_id, matches in index.items()
        if len(matches) > 1
    }
    if missing:
        raise RuntimeError(f"illustrative package lacks required IDs: {missing}")
    if duplicated:
        raise RuntimeError(
            "illustrative package has non-unique required IDs: "
            + json.dumps(duplicated, sort_keys=True)
        )
    return index


def _origin_for_artifact(artifact_id: str, path: Path) -> tuple[str, bool, str]:
    if artifact_id.startswith("F14."):
        return "synthetic_step14_paper_layout", True, "illustrative_only"
    if artifact_id == "M14.1":
        return "governance_record", False, "canonical_stop"
    if artifact_id == "M14.2":
        return "governance_record", False, "confirmatory_not_run"
    if artifact_id == "P14.1":
        return "illustrative_package_inventory", False, "illustrative_package"
    if path.name.startswith("EMPIRICAL_PARTIAL_"):
        return "empirical_nonthermal_partial", False, "partial"
    if path.name.startswith("PRELIMINARY_"):
        return "preliminary_noncanonical", False, "preliminary"
    if path.name.startswith("ILLUSTRATIVE_") or "synthetic_downstream" in path.parts:
        return "synthetic_downstream", True, "illustrative_only"
    return "package_metadata", False, "noncanonical"


def _artifact_kind(artifact_id: str, path: Path) -> str:
    if path.suffix.lower() in FIGURE_SUFFIXES:
        return "figure"
    if artifact_id.startswith("M14."):
        return "memo"
    if artifact_id == "P14.1":
        return "package_inventory"
    return "table_or_record"


def write_data_origin_dictionary(
    output_root: Path,
    figures_root: Path,
    id_index: Mapping[str, list[Path]],
) -> Path:
    rows: list[dict[str, Any]] = []
    for artifact_id in REQUIRED_IDS:
        path = id_index[artifact_id][0]
        origin, synthetic, completeness = _origin_for_artifact(artifact_id, path)
        rows.append(
            {
                "artifact_id": artifact_id,
                "relative_path": _relative_label(path, output_root, figures_root),
                "file_name": path.name,
                "artifact_kind": _artifact_kind(artifact_id, path),
                "origin_class": origin,
                "synthetic": str(synthetic).lower(),
                "completeness": completeness,
                "scientific_gate_eligible": "false",
                "status": STATUS,
            }
        )
    destination = output_root / "data_origin_dictionary.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "artifact_id",
        "relative_path",
        "file_name",
        "artifact_kind",
        "origin_class",
        "synthetic",
        "completeness",
        "scientific_gate_eligible",
        "status",
    ]
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return destination


def validate_csv_contract(output_root: Path) -> list[Path]:
    tables = sorted(output_root.rglob("*.csv"))
    if not tables:
        raise RuntimeError("illustrative package contains no CSV tables")
    for path in tables:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            fields = set(reader.fieldnames or [])
        if not rows:
            raise RuntimeError(f"illustrative CSV is empty: {path}")
        if not fields.intersection({"data_origin", "origin_class"}):
            raise RuntimeError(f"illustrative CSV lacks an origin column: {path}")
        eligibility = fields.intersection(
            {"scientific_gate_eligible", "canonical_eligible"}
        )
        if not eligibility:
            raise RuntimeError(f"illustrative CSV lacks an eligibility column: {path}")
        for field in eligibility:
            values = {str(row[field]).strip().casefold() for row in rows}
            if values != {"false"}:
                raise RuntimeError(
                    f"illustrative CSV eligibility is not uniformly false: {path}"
                )
    return tables


def write_public_source_bundle(output_root: Path, repo_root: Path) -> dict[str, Path]:
    """Inventory the exact code and governance files shipped in the final archive."""

    rows: list[dict[str, Any]] = []
    for role, relative in PUBLIC_SOURCE_FILES:
        path = (repo_root / relative).resolve()
        try:
            path.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise ValueError(f"public source file escapes the repository: {path}") from exc
        if not path.is_file() or path.stat().st_size <= 0:
            raise FileNotFoundError(f"required public source file is missing: {path}")
        rows.append(
            {
                "data_origin": "source_code_or_governance",
                "canonical_eligible": "false",
                "package_role": role,
                "repo_relative_path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    inventory = output_root / "ILLUSTRATIVE_public_package_source_inventory.csv"
    fieldnames = [
        "data_origin",
        "canonical_eligible",
        "package_role",
        "repo_relative_path",
        "size_bytes",
        "sha256",
    ]
    with inventory.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    instructions = output_root / "ILLUSTRATIVE_public_package_rebuild_instructions.md"
    instructions.write_text(
        f"""# Illustrative package rebuild instructions

**Status:** `{STATUS}`  
**Scientific gate eligible:** `false`  
**Data origin:** source code, governance records, empirical nonthermal partial
metadata, and deterministic synthetic demonstrations

From the repository root, activate the environment described by
`environment.yml`, then run:

```text
PYTHONPATH=src python src/run_v2_illustrative_steps02_14.py
```

The runner blocks network access during every illustrative writer, refuses
repository outputs outside `illustrative_only`, requires all 102 registry IDs
exactly once, verifies origin and false-eligibility columns on every CSV, and
hashes every non-manifest output. The authoritative verification ledger is
`data/processed/v2/illustrative_only/steps02_14/run_manifest.json`.

This rebuild reproduces an illustrative workflow package only. It does not open
or reproduce a canonical thermal result, select the holdout, open the real 2026
record, activate Task 2, or satisfy the guide's canonical Step-14 gate.
""",
        encoding="utf-8",
    )
    return {"SOURCE_INVENTORY": inventory, "REBUILD_INSTRUCTIONS": instructions}


def write_readme(output_root: Path, figures_root: Path) -> Path:
    content = f"""# Illustrative-only Guide Steps 2–14

**Canonical status:** `{STATUS}`  
**Illustrative package:** complete through the end of the source guide  
**Scientific gate eligible:** `false`

This quarantined, offline package continues the guide after the user directed
the D0047 geometry run to stop at 710 of 911 retained candidates. It is not a
canonical Task-1 result and does not activate Task 2.

## What is real and what is illustrative

- Step 2 retains real, nonthermal catalogue metadata and the incomplete D0047
  checkpoint facts: 2,968 catalogue rows, a 1,055-pass daytime catalogue
  ceiling, 911 retained geometry candidates, 710 evaluated, and 201 unevaluated.
- Steps 3–13 are deterministic synthetic workflow demonstrations.
- Step 14 contains six synthetic paper-layout figures, a real canonical-STOP
  decision memo, an explicit confirmatory-NOT-RUN report, and an illustrative
  package inventory.

No ECOSTRESS LST or thermal value was opened. The real held-out city remains
`UNSELECTED`, the real 2026 record remains unopened, and no empirical manuscript
or confirmatory claim is authorized. F14.1 is a synthetic design schematic and
does not satisfy the guide's canonical real-imagery requirement.

Figures are stored separately at `{figures_root}`. `data_origin_dictionary.csv`
maps all 102 unique deliverable IDs to origin and eligibility. `run_manifest.json`
contains SHA-256 hashes for every non-manifest package artifact. P14.1 is an
illustrative local/Drive package inventory, not a public scientific release.
"""
    destination = output_root / "README.md"
    destination.write_text(content, encoding="utf-8")
    return destination


def write_gate_status(
    output_root: Path,
    *,
    id_index: Mapping[str, list[Path]],
    figure_count: int,
    csv_count: int,
) -> Path:
    value = {
        **status_contract(),
        "schema_version": 1,
        "package_scope": "illustrative_only_steps02_14",
        "illustrative_package_validation": "COMPLETE_NONCANONICAL",
        "canonical_step14_status": "INCOMPLETE_CONFIRMATORY_NOT_RUN",
        "confirmatory_run_status": "NOT_RUN",
        "canonical_completion_claimed": False,
        "required_artifact_ids_present": True,
        "required_artifact_ids_unique": True,
        "required_artifact_id_count": len(id_index),
        "figure_count": int(figure_count),
        "step14_paper_figure_count": 6,
        "csv_table_count": int(csv_count),
        "network_accessed": False,
        "geometry_snapshot": {
            "catalogue_metadata_rows": 2968,
            "daytime_catalogue_ceiling_passes": 1055,
            "geometry_candidates": 911,
            "geometry_evaluated": 710,
            "geometry_unevaluated": 201,
            "geometry_complete": False,
        },
        "claim_limit": (
            "Synthetic/partial workflow artifacts and governance records only; "
            "not study or confirmatory results."
        ),
    }
    return _write_json(output_root / "canonical_gate_status.json", value)


def _normalize_writer_result(name: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {"writer": name, "return_type": "None"}
    if isinstance(value, dict):
        return {
            "writer": name,
            "return_type": "dict",
            "keys": sorted(map(str, value)),
        }
    if isinstance(value, (list, tuple, set)):
        return {
            "writer": name,
            "return_type": type(value).__name__,
            "items": len(value),
        }
    return {"writer": name, "return_type": type(value).__name__}


def write_manifest(
    output_root: Path,
    figures_root: Path,
    *,
    seed: int,
    writer_results: Mapping[str, Any],
) -> Path:
    manifest_path = (output_root / "run_manifest.json").resolve()
    records = []
    for path in _all_artifacts(output_root, figures_root):
        if path == manifest_path:
            continue
        records.append(
            {
                "relative_path": _relative_label(path, output_root, figures_root),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    value = {
        **status_contract(),
        "schema_version": 1,
        "package_scope": "illustrative_only_steps02_14",
        "seed": int(seed),
        "offline": True,
        "network_accessed": False,
        "canonical_step14_status": "INCOMPLETE_CONFIRMATORY_NOT_RUN",
        "confirmatory_run_status": "NOT_RUN",
        "writers": {
            name: _normalize_writer_result(name, result)
            for name, result in sorted(writer_results.items())
        },
        "artifact_count_excluding_manifest": len(records),
        "artifacts": records,
        "manifest_self_hash": None,
        "manifest_self_hash_note": (
            "The manifest cannot contain its own SHA-256 without a circular value; "
            "every other package artifact is hashed above."
        ),
    }
    return _write_json(manifest_path, value)


def run_package(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    figures_root: Path = DEFAULT_FIGURES_ROOT,
    repo_root: Path = ROOT,
    seed: int = DEFAULT_SEED,
    steps04_08_writer: Callable[[Path, Path, int], Any] | None = None,
    steps09_13_writer: Callable[[Path, Path, int], Any] | None = None,
    step14_figure_writer: Callable[[Path, Path, int], Any] | None = None,
    step14_document_writer: Callable[[Path, Path, int, Mapping[str, Any]], Any]
    | None = None,
) -> dict[str, Any]:
    """Build, validate, and seal the complete illustrative Steps 2--14 package."""

    output_root = Path(output_root).resolve()
    figures_root = Path(figures_root).resolve()
    repo_root = Path(repo_root).resolve()
    _validate_roots(output_root, figures_root, repo_root)

    base_result = run_steps02_13(
        output_root=output_root,
        figures_root=figures_root,
        repo_root=repo_root,
        seed=int(seed),
        steps04_08_writer=steps04_08_writer,
        steps09_13_writer=steps09_13_writer,
    )

    if step14_figure_writer is None:
        from urban_cooling_v2.illustrative_step14_figures import (
            write_step14_figures,
        )

        step14_figure_writer = write_step14_figures
    if step14_document_writer is None:
        from urban_cooling_v2.illustrative_step14_documents import (
            write_step14_documents,
        )

        step14_document_writer = write_step14_documents

    sealed_status = status_contract()
    with offline_network_guard():
        figure_result = step14_figure_writer(output_root, figures_root, int(seed))
        source_bundle_result = write_public_source_bundle(output_root, repo_root)
        document_result = step14_document_writer(
            output_root,
            figures_root,
            int(seed),
            sealed_status,
        )

    id_index = index_required_ids(output_root, figures_root)
    figures = validate_figure_names(figures_root)
    if len([artifact_id for artifact_id in id_index if artifact_id.startswith("F14.")]) != 6:
        raise RuntimeError("illustrative Step 14 must contain exactly six paper figures")
    tables = validate_csv_contract(output_root)
    write_data_origin_dictionary(output_root, figures_root, id_index)
    write_readme(output_root, figures_root)
    write_gate_status(
        output_root,
        id_index=id_index,
        figure_count=len(figures),
        csv_count=len(tables),
    )
    reject_canonical_pass_claims(output_root, figures_root)
    manifest = write_manifest(
        output_root,
        figures_root,
        seed=int(seed),
        writer_results={
            "run_steps02_13": base_result,
            "write_public_source_bundle": source_bundle_result,
            "write_step14_figures": figure_result,
            "write_step14_documents": document_result,
        },
    )
    reject_canonical_pass_claims(output_root, figures_root)
    return {
        **sealed_status,
        "output_root": str(output_root),
        "figures_root": str(figures_root),
        "required_artifact_id_count": len(id_index),
        "figure_count": len(figures),
        "csv_table_count": len(tables),
        "confirmatory_run_status": "NOT_RUN",
        "canonical_step14_status": "INCOMPLETE_CONFIRMATORY_NOT_RUN",
        "manifest": str(manifest),
        "manifest_sha256": sha256_file(manifest),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--figures-root", type=Path, default=DEFAULT_FIGURES_ROOT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_package(
        output_root=args.output_root,
        figures_root=args.figures_root,
        repo_root=ROOT,
        seed=args.seed,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
