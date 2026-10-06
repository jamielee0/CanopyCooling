#!/usr/bin/env python3
"""Build the fully offline, explicitly noncanonical Steps 2–13 package.

The command succeeds when the illustrative package is internally complete.  Its
scientific gate remains STOP by construction; success must never be interpreted
as Task-1 PASS or Task-2 activation.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
import json
from pathlib import Path
import re
import socket
from typing import Any, Callable, Iterator
import urllib.request

from urban_cooling_v2.illustrative_steps02_03 import (
    DEFAULT_SEED,
    IllustrativeRoots,
    STATUS,
    sha256_file,
    status_contract,
    write_steps02_03,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOTS = IllustrativeRoots.defaults(ROOT)
DEFAULT_OUTPUT_ROOT = DEFAULT_ROOTS.output_root
DEFAULT_FIGURES_ROOT = DEFAULT_ROOTS.figures_root
ALLOWED_PREFIXES = ("EMPIRICAL_PARTIAL_", "PRELIMINARY_", "ILLUSTRATIVE_")
FIGURE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".svg", ".pdf"})

REQUIRED_IDS_BY_STEP: dict[int, tuple[str, ...]] = {
    2: ("F2.1", "F2.2", "F2.3", "F2.4", "F2.5", "T2.1", "T2.2", "T2.3"),
    3: ("F3.1", "F3.2", "F3.3", "F3.4", "F3.5", "T3.1"),
    4: ("F4.1", "F4.2", "F4.3", "F4.4", "F4.5", "F4.6", "T4.1", "T4.2", "T4.3"),
    5: ("F5.1", "F5.2", "F5.3", "F5.4", "F5.5", "F5.6", "T5.1", "T5.2"),
    6: ("F6.1", "F6.2", "F6.3", "F6.4", "F6.5", "T6.1", "T6.2"),
    7: ("F7.1", "F7.2", "F7.3", "F7.4", "F7.5", "T7.1", "T7.2"),
    8: ("F8.1", "F8.2", "F8.3", "F8.4", "F8.5", "F8.6", "F8.7", "T8.1", "T8.2", "T8.3"),
    9: ("F9.1", "F9.2", "F9.3", "F9.4", "T9.1", "T9.2"),
    10: (
        "F10.1",
        "F10.2",
        "F10.3",
        "F10.4",
        "F10.5",
        "F10.6",
        "F10.7",
        "F10.8",
        "T10.1",
        "T10.2",
        "T10.3",
    ),
    11: ("F11.1", "F11.2", "F11.3", "F11.4", "T11.1", "T11.2"),
    12: ("F12.1", "F12.2", "F12.3", "F12.4", "F12.5", "F12.6", "T12.1", "T12.2"),
    13: ("F13.1", "F13.2", "F13.3", "F13.4", "F13.5", "T13.1", "T13.2"),
}
REQUIRED_IDS = tuple(
    artifact_id
    for step in sorted(REQUIRED_IDS_BY_STEP)
    for artifact_id in REQUIRED_IDS_BY_STEP[step]
)


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _validate_roots(output_root: Path, figures_root: Path, repo_root: Path) -> None:
    output_root = output_root.resolve()
    figures_root = figures_root.resolve()
    repo_root = repo_root.resolve()
    if output_root == figures_root:
        raise ValueError("data and figure roots must be different")
    if output_root in {repo_root, repo_root / "data", repo_root / "data/processed/v2"}:
        raise ValueError("refusing to write illustrative artifacts to a broad/canonical root")
    if figures_root in {repo_root, repo_root / "figures", repo_root / "figures/v2"}:
        raise ValueError("refusing to write illustrative figures to a broad/canonical root")
    for path in (output_root, figures_root):
        if _within(path, repo_root) and "illustrative_only" not in path.parts:
            raise ValueError(
                f"repository output must remain under an illustrative_only namespace: {path}"
            )


@contextmanager
def offline_network_guard() -> Iterator[None]:
    """Fail closed if any writer attempts an internet connection."""

    original_socket = socket.socket
    original_create_connection = socket.create_connection
    original_urlopen = urllib.request.urlopen

    class OfflineSocket(original_socket):
        def connect(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - defensive
            raise RuntimeError("network access is forbidden in illustrative offline mode")

        def connect_ex(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
            raise RuntimeError("network access is forbidden in illustrative offline mode")

    def deny_network(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("network access is forbidden in illustrative offline mode")

    socket.socket = OfflineSocket
    socket.create_connection = deny_network
    urllib.request.urlopen = deny_network
    try:
        yield
    finally:
        socket.socket = original_socket
        socket.create_connection = original_create_connection
        urllib.request.urlopen = original_urlopen


def _all_artifacts(output_root: Path, figures_root: Path) -> list[Path]:
    paths: set[Path] = set()
    for root in (output_root, figures_root):
        if root.exists():
            paths.update(
                path.resolve()
                for path in root.rglob("*")
                if path.is_file() and path.stat().st_size > 0
            )
    return sorted(paths, key=lambda path: str(path))


def _id_pattern(artifact_id: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(artifact_id)}(?![0-9])",
        flags=re.IGNORECASE,
    )


def index_required_ids(
    output_root: Path,
    figures_root: Path,
) -> dict[str, list[Path]]:
    """Find every required ID in non-empty artifact filenames."""

    files = _all_artifacts(output_root, figures_root)
    index = {
        artifact_id: [
            path for path in files if _id_pattern(artifact_id).search(path.name)
        ]
        for artifact_id in REQUIRED_IDS
    }
    missing = [artifact_id for artifact_id, matches in index.items() if not matches]
    if missing:
        raise RuntimeError(f"illustrative package lacks required IDs: {missing}")
    return index


def validate_figure_names(figures_root: Path) -> list[Path]:
    figures = sorted(
        path.resolve()
        for path in figures_root.rglob("*")
        if path.is_file() and path.suffix.lower() in FIGURE_SUFFIXES
    )
    if not figures:
        raise RuntimeError("illustrative package contains no figures")
    bad = [path for path in figures if not path.name.startswith(ALLOWED_PREFIXES)]
    if bad:
        raise RuntimeError(
            "illustrative figures must use an empirical/preliminary/illustrative prefix: "
            + ", ".join(str(path) for path in bad)
        )
    if any(path.stat().st_size <= 0 for path in figures):
        raise RuntimeError("illustrative package contains an empty figure")
    return figures


def _walk_json(value: Any, *, source: Path) -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key).strip().casefold()
            if key == "scientific_gate_eligible" and child is not False:
                raise RuntimeError(f"scientific_gate_eligible is not false in {source}")
            if key == "task1_gate" and str(child).strip().upper() != "STOP":
                raise RuntimeError(f"Task-1 gate is not STOP in {source}")
            if key in {"task2_activated", "lst_opened", "thermal_opened", "record_2026_opened"} and child is not False:
                raise RuntimeError(f"sealed field {raw_key} is not false in {source}")
            if key == "holdout_status" and str(child).strip().upper() != "UNSELECTED":
                raise RuntimeError(f"holdout is not UNSELECTED in {source}")
            if key in {
                "canonical_status",
                "canonical_gate",
                "canonical_gate_status",
                "scientific_gate_status",
                "task2_gate",
            } and str(child).strip().upper().startswith("PASS"):
                raise RuntimeError(f"canonical PASS claim in {source}: {raw_key}={child}")
            _walk_json(child, source=source)
    elif isinstance(value, list):
        for child in value:
            _walk_json(child, source=source)


def reject_canonical_pass_claims(output_root: Path, figures_root: Path) -> None:
    """Reject exact gate violations while allowing synthetic diagnostic columns."""

    for path in _all_artifacts(output_root, figures_root):
        suffix = path.suffix.lower()
        if suffix == ".json":
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"cannot validate JSON artifact {path}") from exc
            _walk_json(value, source=path)
        elif suffix in {".md", ".txt", ".csv", ".tsv"}:
            text = path.read_text(encoding="utf-8", errors="strict")
            forbidden = (
                r"(?i)canonical[_ -]?(?:status|gate)(?:_status)?\s*[,=:|]\s*PASS\b",
                r"(?i)task1[_ -]?gate\s*[,=:|]\s*PASS\b",
                r"(?i)scientific[_ -]?gate[_ -]?eligible\s*[,=:|]\s*(?:true|1)\b",
            )
            if any(re.search(pattern, text) for pattern in forbidden):
                raise RuntimeError(f"canonical PASS claim in text artifact {path}")


def _relative_label(path: Path, output_root: Path, figures_root: Path) -> str:
    if _within(path, output_root):
        return str(Path("data_root") / path.relative_to(output_root))
    if _within(path, figures_root):
        return str(Path("figures_root") / path.relative_to(figures_root))
    raise ValueError(f"artifact is outside both quarantine roots: {path}")


def _origin_from_path(path: Path) -> tuple[str, bool, str]:
    if path.name.startswith("EMPIRICAL_PARTIAL_"):
        return "empirical_nonthermal_partial", False, "partial"
    if path.name.startswith("PRELIMINARY_"):
        return "preliminary_noncanonical", False, "preliminary"
    if path.name.startswith("ILLUSTRATIVE_"):
        return "synthetic_downstream", True, "illustrative_only"
    if "synthetic_downstream" in path.parts:
        return "synthetic_downstream", True, "illustrative_only"
    return "package_metadata", False, "noncanonical"


def write_data_origin_dictionary(
    output_root: Path,
    figures_root: Path,
    id_index: dict[str, list[Path]],
) -> Path:
    rows: list[dict[str, Any]] = []
    for artifact_id in REQUIRED_IDS:
        for path in id_index[artifact_id]:
            origin, synthetic, completeness = _origin_from_path(path)
            rows.append(
                {
                    "artifact_id": artifact_id,
                    "relative_path": _relative_label(path, output_root, figures_root),
                    "file_name": path.name,
                    "artifact_kind": (
                        "figure" if path.suffix.lower() in FIGURE_SUFFIXES else "table_or_record"
                    ),
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


def write_readme(output_root: Path, figures_root: Path) -> Path:
    content = f"""# Illustrative-only Guide Steps 2–13

**Status:** `{STATUS}`

This directory is a quarantined, offline demonstration produced after the user
directed the D0047 geometry run to stop at 710 of 911 candidates. It is not a
canonical Task-1 result, is not scientifically gate-eligible, and does not
activate Task 2.

## Real nonthermal facts retained

- 2,968 catalogue metadata rows.
- 1,055 daytime catalogue-ceiling passes; this is not a usable-pass count.
- 911 D0047 archive-available geometry candidates.
- 710 candidates evaluated at the stop snapshot.
- 201 candidates unevaluated.

## Interpretation boundary

`empirical_nonthermal/` contains only real catalogue metadata and the incomplete
geometry checkpoint facts. `synthetic_downstream/` contains illustrative outputs
that demonstrate file shapes and analytical workflows. Every figure is visibly
labelled as illustrative/synthetic and every filename is prefixed accordingly.

No ECOSTRESS LST or thermal value was opened. The holdout remains `UNSELECTED`,
the 2026 record remains unopened, and the canonical Task-1 gate remains `STOP`.

Figures are stored separately at `{figures_root}`. `data_origin_dictionary.csv`
maps every required deliverable ID to its origin. `run_manifest.json` contains
SHA-256 hashes for the package artifacts.
"""
    path = output_root / "README.md"
    path.write_text(content, encoding="utf-8")
    return path


def write_gate_status(
    output_root: Path,
    *,
    id_index: dict[str, list[Path]],
    figure_count: int,
) -> Path:
    value = {
        **status_contract(),
        "schema_version": 1,
        "package_scope": "illustrative_only_steps02_13",
        "illustrative_package_validation": "COMPLETE_NONCANONICAL",
        "required_artifact_ids_present": True,
        "required_artifact_id_count": len(id_index),
        "figure_count": int(figure_count),
        "network_accessed": False,
        "geometry_snapshot": {
            "catalogue_metadata_rows": 2968,
            "daytime_catalogue_ceiling_passes": 1055,
            "geometry_candidates": 911,
            "geometry_evaluated": 710,
            "geometry_unevaluated": 201,
            "geometry_complete": False,
        },
        "claim_limit": "Synthetic/partial workflow artifacts only; not study results.",
    }
    return _write_json(output_root / "canonical_gate_status.json", value)


def write_manifest(
    output_root: Path,
    figures_root: Path,
    *,
    seed: int,
    writer_results: dict[str, Any],
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
        "package_scope": "illustrative_only_steps02_13",
        "seed": int(seed),
        "offline": True,
        "network_accessed": False,
        "writers_called": sorted(writer_results),
        "artifact_count_excluding_manifest": len(records),
        "artifacts": records,
        "manifest_self_hash": None,
        "manifest_self_hash_note": (
            "The manifest cannot contain its own SHA-256 without a circular value; "
            "every other package artifact is hashed above."
        ),
    }
    return _write_json(manifest_path, value)


def _normalize_writer_result(name: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {"writer": name, "return_type": "None"}
    if isinstance(value, dict):
        return {"writer": name, "return_type": "dict", "keys": sorted(map(str, value))}
    if isinstance(value, (list, tuple, set)):
        return {"writer": name, "return_type": type(value).__name__, "items": len(value)}
    return {"writer": name, "return_type": type(value).__name__}


def run_package(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    figures_root: Path = DEFAULT_FIGURES_ROOT,
    repo_root: Path = ROOT,
    seed: int = DEFAULT_SEED,
    steps04_08_writer: Callable[[Path, Path, int], Any] | None = None,
    steps09_13_writer: Callable[[Path, Path, int], Any] | None = None,
) -> dict[str, Any]:
    """Run all illustrative writers, validate required IDs, and seal the package."""

    output_root = Path(output_root).resolve()
    figures_root = Path(figures_root).resolve()
    repo_root = Path(repo_root).resolve()
    _validate_roots(output_root, figures_root, repo_root)
    for root in (output_root, figures_root):
        (root / "empirical_nonthermal").mkdir(parents=True, exist_ok=True)
        (root / "synthetic_downstream").mkdir(parents=True, exist_ok=True)

    if steps04_08_writer is None:
        from urban_cooling_v2.illustrative_steps02_08 import write_steps04_08

        steps04_08_writer = write_steps04_08
    if steps09_13_writer is None:
        from urban_cooling_v2.illustrative_steps09_13 import write_steps09_13

        steps09_13_writer = write_steps09_13

    with offline_network_guard():
        result02_03 = write_steps02_03(
            output_root=output_root,
            figures_root=figures_root,
            repo_root=repo_root,
            seed=seed,
            status=status_contract(),
        )
        result04_08 = steps04_08_writer(output_root, figures_root, seed)
        result09_13 = steps09_13_writer(output_root, figures_root, seed)

    writer_results = {
        "write_steps02_03": _normalize_writer_result("write_steps02_03", result02_03),
        "write_steps04_08": _normalize_writer_result("write_steps04_08", result04_08),
        "write_steps09_13": _normalize_writer_result("write_steps09_13", result09_13),
    }
    id_index = index_required_ids(output_root, figures_root)
    figures = validate_figure_names(figures_root)
    write_data_origin_dictionary(output_root, figures_root, id_index)
    write_readme(output_root, figures_root)
    write_gate_status(output_root, id_index=id_index, figure_count=len(figures))
    reject_canonical_pass_claims(output_root, figures_root)
    manifest = write_manifest(
        output_root,
        figures_root,
        seed=seed,
        writer_results=writer_results,
    )
    reject_canonical_pass_claims(output_root, figures_root)
    return {
        **status_contract(),
        "output_root": str(output_root),
        "figures_root": str(figures_root),
        "required_artifact_id_count": len(id_index),
        "figure_count": len(figures),
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
