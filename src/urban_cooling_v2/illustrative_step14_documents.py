"""Noncanonical Step-14 memos and package records.

This module is intentionally separate from the illustrative figure writers.  It
turns an already-built, quarantined package into a small set of review and
reproducibility documents without opening project rasters, selecting a holdout,
or making a confirmatory claim.  The only scene-level inputs it parses are the
synthetic scene and product metadata tables produced by the illustrative
Steps 4--5 writer.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


BANNER = "ILLUSTRATIVE — SYNTHETIC DATA — NOT A STUDY RESULT"
DATA_ORIGIN = "synthetic_and_nonthermal_metadata"
CANONICAL_ELIGIBLE = "false"
REQUIRED_STATUS = "STOP_USER_SKIPPED_D0047_GEOMETRY_710_OF_911"

OUTPUT_FILENAMES: dict[str, str] = {
    "M14.1": "ILLUSTRATIVE_M14.1_go_adjust_stop_memo.md",
    "M14.2": "ILLUSTRATIVE_M14.2_confirmatory_report_NOT_RUN.md",
    "LIMITATIONS": "ILLUSTRATIVE_step14_limitations.md",
    "FINAL_CHECKS": "ILLUSTRATIVE_step14_final_checks.csv",
    "SCENE_VERSION_INVENTORY": "ILLUSTRATIVE_step14_scene_version_inventory.csv",
    "P14.1": "ILLUSTRATIVE_P14.1_public_package_inventory.csv",
    "PACKAGE_CHECKSUMS": "ILLUSTRATIVE_public_package_checksums.json",
}

_REQUIRED_SEALED_STATUS: dict[str, Any] = {
    "scientific_gate_eligible": False,
    "task1_gate": "STOP",
    "task2_activated": False,
    "lst_opened": False,
    "thermal_opened": False,
    "holdout_status": "UNSELECTED",
    "record_2026_opened": False,
}

_SCENE_METADATA_FILENAME = "ILLUSTRATIVE_T4.1_scene_metadata.csv"
_PRODUCT_METADATA_FILENAME = "ILLUSTRATIVE_T5.1_product_inventory.csv"
_SNAPSHOT_FILENAME = "EMPIRICAL_PARTIAL_step02_snapshot_facts.json"
_UPSTREAM_MANIFEST_FILENAME = "run_manifest.json"
_SOURCE_INVENTORY_FILENAME = "ILLUSTRATIVE_public_package_source_inventory.csv"
_REBUILD_INSTRUCTIONS_FILENAME = "ILLUSTRATIVE_public_package_rebuild_instructions.md"
_STEP14_FIGURE_FILENAMES = frozenset(
    {
        "ILLUSTRATIVE_F14.1_PAPER_FIGURE_1_study_design.png",
        "ILLUSTRATIVE_F14.2_PAPER_FIGURE_2_primary_result.png",
        "ILLUSTRATIVE_F14.3_PAPER_FIGURE_3_hydroclimatic_surface.png",
        "ILLUSTRATIVE_F14.4_PAPER_FIGURE_4_radiative_pathway.png",
        "ILLUSTRATIVE_F14.5_PAPER_FIGURE_5_supporting_evidence.png",
        "ILLUSTRATIVE_F14.6_PAPER_FIGURE_6_robustness.png",
    }
)
_SELF_RECORD_FILENAMES = frozenset(
    {
        OUTPUT_FILENAMES["P14.1"],
        OUTPUT_FILENAMES["PACKAGE_CHECKSUMS"],
    }
)
_MUTABLE_ORCHESTRATOR_FILENAMES = frozenset(
    {
        "run_manifest.json",
        "canonical_gate_status.json",
        "data_origin_dictionary.csv",
        "README.md",
    }
)
_INVENTORY_EXCLUDED_FILENAMES = (
    _SELF_RECORD_FILENAMES | _MUTABLE_ORCHESTRATOR_FILENAMES
)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _validate_roots(output_root: Path, figure_root: Path) -> tuple[Path, Path]:
    output_root = Path(output_root).resolve()
    figure_root = Path(figure_root).resolve()
    if output_root == figure_root:
        raise ValueError("output_root and figure_root must be different")
    if _is_within(output_root, figure_root) or _is_within(figure_root, output_root):
        raise ValueError("output_root and figure_root must not contain one another")
    if not output_root.is_dir():
        raise FileNotFoundError(f"existing illustrative output root is required: {output_root}")
    if not figure_root.is_dir():
        raise FileNotFoundError(f"existing illustrative figure root is required: {figure_root}")
    return output_root, figure_root


def _normalized_status_contract(status_contract: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(status_contract, Mapping):
        raise TypeError("status_contract must be a mapping")

    status = str(status_contract.get("status", "")).strip()
    if status != REQUIRED_STATUS:
        raise ValueError(
            "Step 14 illustrative documents require the exact live D0047 STOP status"
        )
    if "\n" in status or "\r" in status:
        raise ValueError("status must be a single-line value")

    for key in (
        "canonical_status",
        "canonical_gate",
        "canonical_gate_status",
        "scientific_gate_status",
        "task2_gate",
    ):
        if str(status_contract.get(key, "")).strip().upper().startswith("PASS"):
            raise ValueError(f"unsafe canonical pass marker in status_contract field {key!r}")
    for key in ("confirmatory_run_performed", "holdout_opened"):
        if status_contract.get(key) is True:
            raise ValueError(f"unsafe opened-state marker in status_contract field {key!r}")

    normalized: dict[str, Any] = {"status": status}
    for key, expected in _REQUIRED_SEALED_STATUS.items():
        if key not in status_contract:
            raise ValueError(f"status_contract is missing sealed field {key!r}")
        actual = status_contract[key]
        if isinstance(expected, str):
            matches = str(actual).strip().upper() == expected
            normalized[key] = str(actual).strip().upper()
        else:
            matches = actual is expected
            normalized[key] = actual
        if not matches:
            raise ValueError(
                f"unsafe Step 14 status: {key} must be {expected!r}, got {actual!r}"
            )
    return normalized


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


def _write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[Mapping[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _find_unique_file(root: Path, filename: str) -> Path:
    matches = sorted(
        (path for path in root.rglob(filename) if path.is_file()),
        key=lambda path: str(path),
    )
    if len(matches) != 1:
        raise FileNotFoundError(
            f"expected exactly one existing {filename!r} under {root}; found {len(matches)}"
        )
    path = matches[0]
    if path.is_symlink() or not _is_within(path, root):
        raise ValueError(f"metadata source must be a regular in-package file: {path}")
    if path.stat().st_size <= 0:
        raise ValueError(f"metadata source is empty: {path}")
    return path


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    if not fieldnames or not rows:
        raise ValueError(f"metadata table must have a header and at least one row: {path}")
    return fieldnames, rows


def _is_false(value: Any) -> bool:
    return str(value).strip().casefold() in {"false", "0", "no"}


def _relative_label(path: Path, output_root: Path, figure_root: Path) -> str:
    if _is_within(path, output_root):
        return str(Path("data_root") / path.resolve().relative_to(output_root))
    if _is_within(path, figure_root):
        return str(Path("figures_root") / path.resolve().relative_to(figure_root))
    raise ValueError(f"file is outside the package roots: {path}")


def _sealed_csv_fields(status: Mapping[str, Any]) -> dict[str, str]:
    return {
        "workflow_status": str(status["status"]),
        "scientific_gate_eligible": "false",
        "task1_gate": "STOP",
        "task2_activated": "false",
        "lst_opened": "false",
        "thermal_opened": "false",
        "holdout_status": "UNSELECTED",
        "record_2026_opened": "false",
    }


def _sealed_markdown_fields(status: Mapping[str, Any]) -> str:
    fields = _sealed_csv_fields(status)
    return "  \n".join(f"{key}: {value}" for key, value in fields.items())


def _safe_snapshot(output_root: Path, status: Mapping[str, Any]) -> dict[str, Any]:
    matches = sorted(output_root.rglob(_SNAPSHOT_FILENAME), key=lambda path: str(path))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one nonthermal Step-2 snapshot under {output_root}; "
            f"found {len(matches)}"
        )
    path = matches[0]
    if path.is_symlink() or not path.is_file() or not _is_within(path, output_root):
        raise ValueError(f"unsafe nonthermal snapshot path: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"nonthermal snapshot must contain a JSON object: {path}")

    # The snapshot is supplemental metadata, never an authority that may open a
    # sealed branch or override the explicit function argument.
    sealed_snapshot_fields = (
        "status",
        "scientific_gate_eligible",
        "task1_gate",
        "task2_activated",
        "lst_opened",
        "thermal_opened",
        "holdout_status",
        "record_2026_opened",
    )
    missing_sealed = [key for key in sealed_snapshot_fields if key not in value]
    if missing_sealed:
        raise ValueError(
            f"nonthermal snapshot lacks sealed status fields: {missing_sealed}"
        )
    for key in sealed_snapshot_fields:
        expected = status[key]
        actual = value[key]
        if isinstance(expected, str):
            matches_status = str(actual).strip().upper() == str(expected).strip().upper()
        else:
            matches_status = actual is expected
        if not matches_status:
            raise ValueError(
                f"nonthermal snapshot conflicts with the sealed status contract: {key}={actual!r}"
            )

    required_checkpoint = {
        "cloud_complete",
        "d0047_geometry_candidates",
        "d0047_geometry_evaluated_at_user_skip",
        "d0047_geometry_unevaluated_at_user_skip",
        "usable_pass_count_available",
    }
    missing_checkpoint = sorted(required_checkpoint - set(value))
    if missing_checkpoint:
        raise ValueError(
            f"nonthermal snapshot lacks D0047 checkpoint fields: {missing_checkpoint}"
        )
    counts: dict[str, int] = {}
    for key in (
        "d0047_geometry_candidates",
        "d0047_geometry_evaluated_at_user_skip",
        "d0047_geometry_unevaluated_at_user_skip",
    ):
        raw = value[key]
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError(f"nonthermal snapshot field {key} must be a nonnegative integer")
        counts[key] = raw
    if counts != {
        "d0047_geometry_candidates": 911,
        "d0047_geometry_evaluated_at_user_skip": 710,
        "d0047_geometry_unevaluated_at_user_skip": 201,
    }:
        raise ValueError(f"nonthermal snapshot does not match the live D0047 checkpoint: {counts}")
    if (
        counts["d0047_geometry_evaluated_at_user_skip"]
        + counts["d0047_geometry_unevaluated_at_user_skip"]
        != counts["d0047_geometry_candidates"]
    ):
        raise ValueError("D0047 evaluated and unevaluated counts do not sum to candidates")
    if value["cloud_complete"] is not False:
        raise ValueError("nonthermal snapshot must record cloud_complete=false")
    if value["usable_pass_count_available"] is not False:
        raise ValueError(
            "nonthermal snapshot must record usable_pass_count_available=false"
        )

    allowed = {
        "catalogue_metadata_rows",
        "cloud_complete",
        "completeness",
        "d0047_geometry_candidates",
        "d0047_geometry_evaluated_at_user_skip",
        "d0047_geometry_unevaluated_at_user_skip",
        "daytime_catalogue_ceiling_passes",
        "usable_pass_count_available",
    }
    return {key: value[key] for key in sorted(allowed) if key in value}


def _write_scene_version_inventory(
    output_root: Path,
    figure_root: Path,
    *,
    seed: int,
    status: Mapping[str, Any],
) -> Path:
    scene_path = _find_unique_file(output_root, _SCENE_METADATA_FILENAME)
    product_path = _find_unique_file(output_root, _PRODUCT_METADATA_FILENAME)
    scene_columns, scene_rows = _read_csv(scene_path)
    product_columns, product_rows = _read_csv(product_path)

    required_scene = {
        "data_origin",
        "canonical_eligible",
        "synthetic_scene_id",
        "synthetic_pass_id",
        "city",
        "year",
        "synthetic_acquisition_utc",
        "synthetic_retrieval_mode",
        "synthetic_geometry_class",
    }
    required_product = {
        "data_origin",
        "canonical_eligible",
        "synthetic_product",
        "synthetic_version",
        "synthetic_layer",
        "synthetic_scene_match_fraction",
    }
    missing_scene = sorted(required_scene - set(scene_columns))
    missing_product = sorted(required_product - set(product_columns))
    if missing_scene:
        raise ValueError(f"synthetic scene metadata lacks fields: {missing_scene}")
    if missing_product:
        raise ValueError(f"synthetic product metadata lacks fields: {missing_product}")

    seen_scene_ids: set[str] = set()
    for row in scene_rows:
        scene_id = row["synthetic_scene_id"].strip()
        pass_id = row["synthetic_pass_id"].strip()
        city = row["city"].strip()
        if row["data_origin"].strip().casefold() != "synthetic":
            raise ValueError("scene/version inventory accepts only synthetic scene metadata")
        if not _is_false(row["canonical_eligible"]):
            raise ValueError("synthetic scene metadata is incorrectly marked canonical-eligible")
        if not scene_id.startswith("synthetic_scene_"):
            raise ValueError(f"non-synthetic scene identifier found: {scene_id!r}")
        if scene_id in seen_scene_ids:
            raise ValueError(f"duplicate synthetic scene identifier found: {scene_id!r}")
        seen_scene_ids.add(scene_id)
        if not pass_id.startswith("synthetic_pass_"):
            raise ValueError(f"non-synthetic pass identifier found: {pass_id!r}")
        if not re.fullmatch(r"sim_city_[A-Za-z0-9_]+", city):
            raise ValueError(f"non-generic city label found in synthetic metadata: {city!r}")

    seen_products: set[tuple[str, str, str]] = set()
    for row in product_rows:
        if row["data_origin"].strip().casefold() != "synthetic":
            raise ValueError("scene/version inventory accepts only synthetic product metadata")
        if not _is_false(row["canonical_eligible"]):
            raise ValueError("synthetic product metadata is incorrectly marked canonical-eligible")
        product_key = (
            row["synthetic_product"].strip(),
            row["synthetic_version"].strip(),
            row["synthetic_layer"].strip(),
        )
        if not all(product_key):
            raise ValueError("synthetic product, version, and layer must all be non-empty")
        if product_key in seen_products:
            raise ValueError(f"duplicate synthetic product metadata row: {product_key!r}")
        seen_products.add(product_key)

    scene_source = _relative_label(scene_path, output_root, figure_root)
    product_source = _relative_label(product_path, output_root, figure_root)
    inventory_rows: list[dict[str, Any]] = []
    for scene in sorted(scene_rows, key=lambda row: row["synthetic_scene_id"]):
        for product in sorted(
            product_rows,
            key=lambda row: (
                row["synthetic_product"],
                row["synthetic_version"],
                row["synthetic_layer"],
            ),
        ):
            inventory_rows.append(
                {
                    "data_origin": "synthetic_metadata",
                    "canonical_eligible": CANONICAL_ELIGIBLE,
                    **_sealed_csv_fields(status),
                    "inventory_scope": (
                        "illustrative_scene_product_crosswalk_not_match_confirmation"
                    ),
                    "synthetic_scene_id": scene["synthetic_scene_id"],
                    "synthetic_pass_id": scene["synthetic_pass_id"],
                    "city": scene["city"],
                    "year": scene["year"],
                    "synthetic_acquisition_utc": scene["synthetic_acquisition_utc"],
                    "synthetic_retrieval_mode": scene["synthetic_retrieval_mode"],
                    "synthetic_geometry_class": scene["synthetic_geometry_class"],
                    "synthetic_product": product["synthetic_product"],
                    "synthetic_version": product["synthetic_version"],
                    "synthetic_layer": product["synthetic_layer"],
                    "synthetic_scene_match_fraction_from_product_metadata": product[
                        "synthetic_scene_match_fraction"
                    ],
                    "record_relationship": (
                        "product_inventory_crosswalk_not_verified_scene_match"
                    ),
                    "download_date": "not_applicable_synthetic_no_download",
                    "download_status": "no_download_performed",
                    "illustrative_seed": int(seed),
                    "scene_metadata_source": scene_source,
                    "product_metadata_source": product_source,
                }
            )

    fields = (
        "data_origin",
        "canonical_eligible",
        "workflow_status",
        "scientific_gate_eligible",
        "task1_gate",
        "task2_activated",
        "lst_opened",
        "thermal_opened",
        "holdout_status",
        "record_2026_opened",
        "inventory_scope",
        "synthetic_scene_id",
        "synthetic_pass_id",
        "city",
        "year",
        "synthetic_acquisition_utc",
        "synthetic_retrieval_mode",
        "synthetic_geometry_class",
        "synthetic_product",
        "synthetic_version",
        "synthetic_layer",
        "synthetic_scene_match_fraction_from_product_metadata",
        "record_relationship",
        "download_date",
        "download_status",
        "illustrative_seed",
        "scene_metadata_source",
        "product_metadata_source",
    )
    return _write_csv(
        output_root / OUTPUT_FILENAMES["SCENE_VERSION_INVENTORY"],
        fields,
        inventory_rows,
    )


def _geometry_summary(snapshot: Mapping[str, Any]) -> str:
    evaluated = snapshot.get("d0047_geometry_evaluated_at_user_skip")
    candidates = snapshot.get("d0047_geometry_candidates")
    unevaluated = snapshot.get("d0047_geometry_unevaluated_at_user_skip")
    if evaluated is None or candidates is None:
        return "D0047 geometry completion counts were not present in the quarantined snapshot."
    suffix = f"; {unevaluated} remained unevaluated" if unevaluated is not None else ""
    return f"D0047 geometry was evaluated for {evaluated} of {candidates} candidates{suffix}."


def _write_memo(
    output_root: Path,
    *,
    seed: int,
    status: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> Path:
    text = f"""# ILLUSTRATIVE M14.1 — Go / adjust / stop memo

> {BANNER}

data_origin: {DATA_ORIGIN}  
canonical_eligible: false  
illustrative_seed: {int(seed)}  
{_sealed_markdown_fields(status)}

## Decision

**STOP for empirical, manuscript, and confirmatory claims.** The only permitted
continuation is the explicitly quarantined illustrative package. This memo does
not authorize Task 2, thermal/LST access, holdout selection, 2026 access, or a
scientific conclusion.

## Basis

- Task-1 gate remains **STOP** and scientific-gate eligibility remains false.
- {_geometry_summary(snapshot)}
- Cloud survival and the real usable-pass count are not complete.
- LST and thermal inputs remain unopened; therefore no empirical endpoint was estimated.
- The held-out city is **UNSELECTED**, and the 2026 record remains unopened.
- Steps 3–14 demonstrations use synthetic or nonthermal metadata and are not study results.

## Guide decision criteria

| Criterion | Current evidence | Disposition |
|---|---|---|
| Primary endpoint is stable | No empirical thermal endpoint exists | Not evaluated |
| Radiative standardization survives scrutiny | Synthetic demonstration only | Not evaluated |
| Placebo and night checks behave | Synthetic demonstration only | Not evaluated |
| Effect exceeds the combined detection limit | No empirical effect estimate exists | Not evaluated |

Because none of the scientific decision criteria has been evaluated on eligible
data, manuscript drafting and confirmatory opening remain out of scope. A later
run must complete the real Task-1 prerequisites and freeze its method before any
held-out thermal or 2026 record is opened. If a future eligible interaction
analysis fails, the guide's adjustment is to retain only a supportable
time-of-day paper and state the sampling limitation.
"""
    return _write_text(output_root / OUTPUT_FILENAMES["M14.1"], text)


def _write_confirmatory_not_run(
    output_root: Path,
    *,
    seed: int,
    status: Mapping[str, Any],
) -> Path:
    text = f"""# ILLUSTRATIVE M14.2 — Confirmatory report

> {BANNER}

**Status: NOT RUN**

data_origin: {DATA_ORIGIN}  
canonical_eligible: false  
illustrative_seed: {int(seed)}  
{_sealed_markdown_fields(status)}

No confirmatory estimate exists. No held-out city was selected, no held-out
thermal result was opened, and no 2026 record was opened. Synthetic held-out
labels or plots elsewhere in the illustrative package are demonstrations of
report structure only; they are not confirmatory analyses.

## Sealed-state record

| Control | Recorded state |
|---|---|
| Task 2 | Not activated |
| LST data | Unopened |
| Thermal data | Unopened |
| Held-out city | UNSELECTED |
| 2026 record | Unopened |

## Protocol if a future eligible run reaches this point

1. Complete and audit the real geometry, cloud-survival, hourly-demand, and power prerequisites.
2. Freeze domains, thresholds, versions, endpoints, models, and decision rules.
3. Record holdout selection using data-quality evidence before inspecting thermal results.
4. Open the held-out city and 2026 season once, run the frozen pipeline, and report whatever occurs.
5. Make no method change in response to the confirmatory result; any later change begins a new analysis.

This protocol is prospective only and does not alter the STOP decision in M14.1.
"""
    return _write_text(output_root / OUTPUT_FILENAMES["M14.2"], text)


def _write_limitations(output_root: Path, *, seed: int, status: Mapping[str, Any]) -> Path:
    text = f"""# ILLUSTRATIVE Step 14 — Limitations and claim boundaries

> {BANNER}

data_origin: {DATA_ORIGIN}  
canonical_eligible: false  
illustrative_seed: {int(seed)}  
{_sealed_markdown_fields(status)}

1. The current package contains synthetic downstream demonstrations and a partial nonthermal catalogue snapshot. It contains no eligible empirical cooling result.
2. Time-of-day dependence would compare observations from different dates; it must not be described as a same-day diurnal trajectory.
3. Clear-sky satellite sampling can differ systematically from all summer weather and limits generalization; the required empirical quantification is not available in this package.
4. Antecedent climatic dryness or water balance is a climatic exposure, not soil water, root-zone water, irrigation, or plant-available water.
5. Surface temperature is not leaf temperature, pedestrian comfort, mean radiant temperature, or a demonstrated reduction in near-surface air temperature.
6. Radiative adjustment is incomplete for shadow history, crown geometry, sky-view factor, roughness, thermal inertia, directional anisotropy, and other unresolved controls.
7. Five purposively selected cities are cases, not a probability sample of United States cities; no national population claim is supported.
8. D0047 geometry is incomplete, the real usable-pass total is unavailable, and cloud survival is incomplete; the Task-1 gate therefore remains STOP.
9. The held-out city and 2026 record remain sealed; there is no confirmatory result to interpret.
10. The scene/version inventory is a synthetic metadata crosswalk. Its download dates are explicitly not applicable and it is not a real source-data ledger.
11. P14.1 is a checksum inventory for the quarantined files, not a public scientific release; this document layer does not itself supply public code, a canonical decision log, or an independent rebuild.
"""
    return _write_text(output_root / OUTPUT_FILENAMES["LIMITATIONS"], text)


def _extended_package_source_check(output_root: Path) -> tuple[str, str]:
    expected = (
        output_root / _SOURCE_INVENTORY_FILENAME,
        output_root / _REBUILD_INSTRUCTIONS_FILENAME,
    )
    present = [
        path.name
        for path in expected
        if path.is_file() and not path.is_symlink() and path.stat().st_size > 0
    ]
    if len(present) == len(expected):
        return (
            "INCLUDED_IN_EXTENDED_PACKAGE",
            (
                f"{_SOURCE_INVENTORY_FILENAME} inventories source modules, runners, "
                f"tests, DECISION_LOG, and REQUIREMENTS; "
                f"{_REBUILD_INSTRUCTIONS_FILENAME} records the offline rebuild."
            ),
        )
    missing = sorted(path.name for path in expected if path.name not in present)
    return (
        "NOT_INCLUDED_BY_DOCUMENT_LAYER",
        "P14.1 inventories quarantined artifacts only; missing extended-package files: "
        + ", ".join(missing),
    )


def _write_final_checks(
    output_root: Path,
    *,
    status: Mapping[str, Any],
) -> Path:
    common = {
        "data_origin": DATA_ORIGIN,
        "canonical_eligible": CANONICAL_ELIGIBLE,
        **_sealed_csv_fields(status),
    }
    source_check_status, source_check_evidence = _extended_package_source_check(output_root)
    rows = [
        {
            **common,
            "check_id": "method_freeze_before_holdout",
            "guide_requirement": "Method freeze precedes held-out data access",
            "check_status": "NOT_RUN_HOLDOUT_UNSELECTED",
            "evidence": "Status contract records holdout_status=UNSELECTED and thermal_opened=false.",
        },
        {
            **common,
            "check_id": "confirmatory_report",
            "guide_requirement": "Held-out city and 2026 report uses the frozen method",
            "check_status": "NOT_RUN",
            "evidence": "M14.2 records that no confirmatory estimate exists.",
        },
        {
            **common,
            "check_id": "claim_traceability",
            "guide_requirement": "Every results claim traces to a figure or table",
            "check_status": "NONCANONICAL_SCOPE_ONLY",
            "evidence": "M14.1 and M14.2 make no empirical results claim; P14.1 indexes package files and hashes.",
        },
        {
            **common,
            "check_id": "inference_language",
            "guide_requirement": "Inference remains within time, water-balance, mechanism, and population limits",
            "check_status": "DOCUMENTED_NONCANONICAL",
            "evidence": "The Step-14 limitations memo records all required claim boundaries.",
        },
        {
            **common,
            "check_id": "independent_rebuild",
            "guide_requirement": "An independent colleague rebuilds the package",
            "check_status": "NOT_RUN",
            "evidence": "Checksums support later verification but do not constitute an independent rebuild.",
        },
        {
            **common,
            "check_id": "scene_version_download_inventory",
            "guide_requirement": "Scene, version, and download-date list exists",
            "check_status": "SYNTHETIC_METADATA_ONLY",
            "evidence": "Inventory uses the existing illustrative T4.1 and T5.1 metadata; no download occurred.",
        },
        {
            **common,
            "check_id": "public_code_and_decision_history",
            "guide_requirement": "Public code and decision history accompany the release",
            "check_status": source_check_status,
            "evidence": source_check_evidence,
        },
        {
            **common,
            "check_id": "canonical_step14_gate",
            "guide_requirement": "All Step-14 scientific prerequisites are satisfied",
            "check_status": "STOP_NOT_ELIGIBLE",
            "evidence": "Task-1 gate remains STOP; thermal, holdout, and 2026 branches remain sealed.",
        },
    ]
    fields = (
        "data_origin",
        "canonical_eligible",
        "workflow_status",
        "scientific_gate_eligible",
        "task1_gate",
        "task2_activated",
        "lst_opened",
        "thermal_opened",
        "holdout_status",
        "record_2026_opened",
        "check_id",
        "guide_requirement",
        "check_status",
        "evidence",
    )
    return _write_csv(output_root / OUTPUT_FILENAMES["FINAL_CHECKS"], fields, rows)


def _resolve_manifest_label(
    label: str,
    output_root: Path,
    figure_root: Path,
) -> Path | None:
    if "\\" in label:
        raise ValueError(f"manifest path must use forward slashes: {label!r}")
    if label.startswith("data_root/"):
        root = output_root
        raw_relative = label.removeprefix("data_root/")
    elif label.startswith("figures_root/"):
        root = figure_root
        raw_relative = label.removeprefix("figures_root/")
    else:
        raise ValueError(f"manifest path lacks a quarantined-root label: {label!r}")
    relative = Path(raw_relative)
    if not raw_relative or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe relative path in upstream manifest: {label!r}")
    path = root / relative
    if path.name in _INVENTORY_EXCLUDED_FILENAMES:
        return None
    if path.is_symlink() or not path.is_file() or not _is_within(path, root):
        raise ValueError(f"upstream manifest points outside the regular package files: {path}")
    if path.stat().st_size <= 0:
        raise ValueError(f"upstream manifest points to an empty file: {path}")
    safe_suffixes = {".csv", ".tsv", ".json", ".md", ".txt", ".png", ".jpg", ".jpeg", ".svg", ".pdf"}
    if path.suffix.casefold() not in safe_suffixes:
        raise ValueError(f"upstream manifest contains a disallowed file type: {path}")
    if not path.name.startswith(("ILLUSTRATIVE_", "EMPIRICAL_PARTIAL_", "PRELIMINARY_")):
        raise ValueError(f"upstream manifest contains an unlabelled artifact: {path}")
    return path.resolve()


def _manifest_allowlist(output_root: Path, figure_root: Path) -> set[Path]:
    manifest_path = output_root / _UPSTREAM_MANIFEST_FILENAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise FileNotFoundError(f"upstream illustrative manifest is required: {manifest_path}")
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("upstream illustrative manifest must be a JSON object")
    _normalized_status_contract(value)
    records = value.get("artifacts")
    if not isinstance(records, list) or not records:
        raise ValueError("upstream illustrative manifest must contain artifact records")

    allowed: set[Path] = set()
    labels: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("relative_path"), str):
            raise ValueError("each upstream manifest artifact needs a relative_path string")
        label = record["relative_path"].strip()
        if label in labels:
            raise ValueError(f"duplicate path in upstream illustrative manifest: {label!r}")
        labels.add(label)
        path = _resolve_manifest_label(label, output_root, figure_root)
        if path is not None:
            allowed.add(path)
    if not allowed:
        raise ValueError("upstream illustrative manifest contains no stable package artifacts")
    return allowed


def _exact_step14_allowlist(output_root: Path, figure_root: Path) -> set[Path]:
    paths = {
        output_root / filename
        for key, filename in OUTPUT_FILENAMES.items()
        if key not in {"P14.1", "PACKAGE_CHECKSUMS"}
    }
    paths.update(
        {
            output_root / _SOURCE_INVENTORY_FILENAME,
            output_root / _REBUILD_INSTRUCTIONS_FILENAME,
        }
    )
    paths.update(figure_root / filename for filename in _STEP14_FIGURE_FILENAMES)
    return {
        path.resolve()
        for path in paths
        if path.is_file() and not path.is_symlink() and path.stat().st_size > 0
    }


def _package_files(output_root: Path, figure_root: Path) -> list[Path]:
    allowed = _manifest_allowlist(output_root, figure_root)
    allowed.update(_exact_step14_allowlist(output_root, figure_root))

    # Inspect only directory entries and basic file metadata first.  Any file
    # outside the prior manifest or exact Step-14 allowlist is rejected before
    # its contents reach the checksum reader.
    discovered: set[Path] = set()
    for root in (output_root, figure_root):
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"public package inventory refuses symlinks: {path}")
            if not path.is_file() or path.name in _INVENTORY_EXCLUDED_FILENAMES:
                continue
            resolved = path.resolve()
            if not _is_within(resolved, root):
                raise ValueError(f"public package file escapes its root: {path}")
            if resolved not in allowed:
                raise ValueError(
                    "refusing to read or hash an unexpected package file outside the "
                    f"upstream manifest/Step-14 allowlist: {path}"
                )
            if path.stat().st_size <= 0:
                raise ValueError(f"public package contains an empty file: {path}")
            discovered.add(resolved)

    missing = sorted(
        allowed - discovered,
        key=lambda path: _relative_label(path, output_root, figure_root),
    )
    if missing:
        raise ValueError(f"allowlisted package files were not discovered: {missing}")
    return sorted(
        discovered,
        key=lambda path: _relative_label(path, output_root, figure_root),
    )


def _artifact_kind(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in {".png", ".jpg", ".jpeg", ".svg", ".pdf"}:
        return "figure"
    if suffix in {".csv", ".tsv"}:
        return "table_or_inventory"
    if suffix == ".json":
        return "machine_metadata"
    if suffix in {".md", ".txt"}:
        return "narrative_or_readme"
    if suffix == ".py":
        return "code"
    return "other"


def _origin_class(path: Path) -> str:
    if path.name.startswith("EMPIRICAL_PARTIAL_"):
        return "empirical_nonthermal_partial"
    if path.name.startswith("PRELIMINARY_"):
        return "preliminary_noncanonical"
    if path.name.startswith("ILLUSTRATIVE_"):
        return "illustrative_or_synthetic"
    return "noncanonical_package_metadata"


def _write_public_package_records(
    output_root: Path,
    figure_root: Path,
    *,
    seed: int,
    status: Mapping[str, Any],
) -> tuple[Path, Path]:
    files = _package_files(output_root, figure_root)
    if not files:
        raise ValueError("cannot inventory an empty illustrative package")

    rows: list[dict[str, Any]] = []
    for path in files:
        relative_path = _relative_label(path, output_root, figure_root)
        rows.append(
            {
                "data_origin": _origin_class(path),
                "canonical_eligible": CANONICAL_ELIGIBLE,
                **_sealed_csv_fields(status),
                "package_scope": "illustrative_only",
                "relative_path": relative_path,
                "file_name": path.name,
                "artifact_kind": _artifact_kind(path),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )

    fields = (
        "data_origin",
        "canonical_eligible",
        "workflow_status",
        "scientific_gate_eligible",
        "task1_gate",
        "task2_activated",
        "lst_opened",
        "thermal_opened",
        "holdout_status",
        "record_2026_opened",
        "package_scope",
        "relative_path",
        "file_name",
        "artifact_kind",
        "size_bytes",
        "sha256",
    )
    inventory_path = _write_csv(
        output_root / OUTPUT_FILENAMES["P14.1"],
        fields,
        rows,
    )
    content_digest_payload = "".join(
        f"{row['relative_path']}\t{row['size_bytes']}\t{row['sha256']}\n" for row in rows
    ).encode("utf-8")
    checksum_path = _write_json(
        output_root / OUTPUT_FILENAMES["PACKAGE_CHECKSUMS"],
        {
            "schema_version": 1,
            "data_origin": DATA_ORIGIN,
            "canonical_eligible": False,
            "scientific_gate_eligible": False,
            "task1_gate": "STOP",
            "task2_activated": False,
            "lst_opened": False,
            "thermal_opened": False,
            "holdout_status": "UNSELECTED",
            "record_2026_opened": False,
            "package_scope": "illustrative_only",
            "claim_limit": (
                "Checksum inventory for a quarantined synthetic/partial package; "
                "not a public scientific release or canonical reproducibility proof."
            ),
            "illustrative_seed": int(seed),
            "status_contract": dict(status),
            "listed_file_count": len(rows),
            "listed_content_sha256": hashlib.sha256(content_digest_payload).hexdigest(),
            "inventory_file": inventory_path.name,
            "inventory_size_bytes": inventory_path.stat().st_size,
            "inventory_sha256": _sha256_file(inventory_path),
            "excluded_mutable_orchestrator_files": sorted(
                _MUTABLE_ORCHESTRATOR_FILENAMES
            ),
            "excluded_self_record_files": sorted(_SELF_RECORD_FILENAMES),
            "self_record_policy": (
                "The P14.1 inventory CSV and this companion JSON are omitted from "
                "the row list to avoid circular self-checksums. Mutable orchestrator "
                "metadata is omitted because the extended runner rewrites and hashes "
                "it after this document layer completes."
            ),
        },
    )
    return inventory_path, checksum_path


def write_step14_documents(
    output_root: Path,
    figure_root: Path,
    seed: int,
    status_contract: Mapping[str, Any],
) -> dict[str, Path]:
    """Write the quarantined Step-14 memo and packaging layer.

    Parameters
    ----------
    output_root, figure_root:
        Existing roots of the already-built illustrative package.  This writer
        writes documents only under ``output_root`` and reads ``figure_root``
        only to compute the public-package file inventory and checksums.
    seed:
        The upstream illustrative seed, recorded for traceability.  This module
        performs no simulation.
    status_contract:
        Explicit sealed-state mapping.  The call fails unless Task 1 is STOP,
        Task 2 is inactive, and LST, thermal, holdout, and 2026 remain sealed.

    Returns
    -------
    dict[str, Path]
        Paths keyed by registry ID for M14.1, M14.2, and P14.1, plus named
        support-document keys.
    """

    output_root, figure_root = _validate_roots(output_root, figure_root)
    status = _normalized_status_contract(status_contract)
    snapshot = _safe_snapshot(output_root, status)

    artifacts: dict[str, Path] = {}
    artifacts["SCENE_VERSION_INVENTORY"] = _write_scene_version_inventory(
        output_root,
        figure_root,
        seed=int(seed),
        status=status,
    )
    artifacts["M14.1"] = _write_memo(
        output_root,
        seed=int(seed),
        status=status,
        snapshot=snapshot,
    )
    artifacts["M14.2"] = _write_confirmatory_not_run(
        output_root,
        seed=int(seed),
        status=status,
    )
    artifacts["LIMITATIONS"] = _write_limitations(
        output_root,
        seed=int(seed),
        status=status,
    )
    artifacts["FINAL_CHECKS"] = _write_final_checks(output_root, status=status)
    inventory_path, checksum_path = _write_public_package_records(
        output_root,
        figure_root,
        seed=int(seed),
        status=status,
    )
    artifacts["P14.1"] = inventory_path
    artifacts["PACKAGE_CHECKSUMS"] = checksum_path
    return artifacts


__all__ = [
    "BANNER",
    "CANONICAL_ELIGIBLE",
    "DATA_ORIGIN",
    "OUTPUT_FILENAMES",
    "write_step14_documents",
]
