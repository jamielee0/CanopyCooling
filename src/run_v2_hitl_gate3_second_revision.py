#!/usr/bin/env python3
"""Build the D0069 Gate-3 second-revision packet from historical nonthermal evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from urban_cooling_v2.hitl_gate3_sampling import (
    PRIMARY_ANGLE_THRESHOLDS,
    add_antecedent_predictors,
    build_archive_bound_diagnostics,
    build_balance_diagnostics,
    selection_result,
    summarize_phenology_sensitivities,
)


OUTPUT = ROOT / "docs/v2/hitl/G3_SAMPLING_DESIGN_SECOND_REVISION"
PHENOLOGY_RAW = (
    ROOT
    / "data/raw/v2/hitl/g3_sampling_design_revision/mod13q1_tcc_2018_2025_composite_ndvi.csv"
)
GEOMETRY = (
    ROOT
    / "data/processed/v2/hitl/g3_sampling_design_revision2/geometry_azimuth_pass_summary.csv"
)
CLOUD = ROOT / "data/processed/v2/hitl/g3_sampling_design_revision2/cloud_pass_summary.csv"
WEATHER = (
    ROOT
    / "data/processed/v2/hitl/g3_sampling_design_revision2/exact_weather_and_condition_pass_summary.csv"
)
AUGMENTATION_SUMMARY = (
    ROOT / "data/processed/v2/hitl/g3_sampling_design_revision2/augmentation_summary.json"
)
HRRR_STORAGE_ESTIMATE = (
    ROOT
    / "data/raw/v2/hitl/g3_sampling_design_revision2/hrrr_exact_acquisition/hrrr_storage_estimate.csv"
)
HRRR_STORAGE_PREFLIGHT = (
    ROOT
    / "data/raw/v2/hitl/g3_sampling_design_revision2/hrrr_exact_acquisition/hrrr_storage_preflight.json"
)
GEOMETRY_RECONSTRUCTION_PREFLIGHT = (
    ROOT
    / "data/raw/v2/hitl/g3_sampling_design_revision2/geometry_reconstruction_storage_preflight.json"
)
GEOMETRY_CHECKPOINT = (
    ROOT / "data/raw/v2/hitl/g3_sampling_design_revision2/geometry_azimuth_checkpoint.json"
)
NEW_ARCHIVE_STATUS = (
    ROOT / "data/processed/v2/hitl/g3_sampling_design_revision2/new_pass_archive_status.csv"
)
NEW_PASSES_SOURCE = (
    ROOT
    / "docs/v2/hitl/G3_SAMPLING_DESIGN/candidate_addition_physical_metadata_passes.csv"
)
NEW_METADATA_SOURCE = (
    ROOT
    / "data/raw/v2/hitl/g3_sampling_design/candidate_additions_l2t_metadata_2018_2025.csv"
)
NEW_SCENE_MANIFEST = (
    ROOT
    / "data/raw/v2/hitl/g3_sampling_design_revision2/new_l1b_geo/l1b_geo_scene_manifest.csv"
)
EXISTING_GEOMETRY_LINKS = (
    ROOT
    / "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/retained_city_scene_links.csv"
)
EXISTING_GEOMETRY_SCENE_MANIFEST = (
    ROOT
    / "data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available/l1b_geo_scene_manifest.csv"
)
NEW_UNAVAILABLE_LABELS = (
    ROOT
    / "data/processed/v2/hitl/g3_sampling_design_revision2/new_unavailable_condition_pass_summary.csv"
)
ARCHIVE_PASSES = (
    ROOT
    / "docs/v2/hitl/G3_SAMPLING_DESIGN_REVISION/archive_pass_bounded_recheck_and_bounds.csv"
)
ARCHIVE_SUMMARY = (
    ROOT / "docs/v2/hitl/G3_SAMPLING_DESIGN_REVISION/archive_bounded_recheck_summary.json"
)
DAILY_GRIDMET = (
    ROOT / "data/raw/v2/hitl/g3_sampling_design/candidate_city_daily_gridmet_2018_2025.csv"
)
D0069 = ROOT / "docs/v2/D0069_G3_PHENOLOGY_ROLE_AMENDMENT.md"
D0067 = ROOT / "docs/v2/D0067_G3_REVISION_PRE_RESULT_RULES.md"
D0070 = ROOT / "docs/v2/D0070_G3_ARCHIVE_RECHECK_PROTOCOL_DEVIATION.md"
D0071 = ROOT / "docs/v2/D0071_USER_DELEGATED_ITERATIVE_GATE_REVIEW.md"
D0072 = ROOT / "docs/v2/D0072_G3_GEOMETRY_AND_RESUME_STORAGE_INCIDENT.md"
D0073 = ROOT / "docs/v2/D0073_G4_G5_READINESS_2026_METADATA_EXPOSURE.md"
D0074 = ROOT / "docs/v2/D0074_REPEAT_2026_METADATA_EXPOSURE.md"
D0075 = ROOT / "docs/v2/D0075_G3_EXCLUSIVE_WRITER_CORRECTION.md"
D0076 = ROOT / "docs/v2/D0076_FIRST_FOUR_ITEMS_SEQUENCE_CORRECTION.md"
D0077 = ROOT / "docs/v2/D0077_G3_PAUSE_CHECKPOINT_COUNT_CORRECTION.md"
D0078 = ROOT / "docs/v2/D0078_FIRST_FOUR_ITEMS_APPROVAL_AND_G3_RESUME.md"
D0079 = ROOT / "docs/v2/D0079_G3_GENERATED_ZERO_MAP_PROOF_CORRECTION.md"
D0080 = ROOT / "docs/v2/D0080_G3_VALIDATOR_INTEGRATION_CORRECTIONS.md"
D0081 = ROOT / "docs/v2/D0081_G3_HRRR_CHECKPOINT_ENVELOPE_CORRECTION.md"
ARCHIVE_SCENES = (
    ROOT / "docs/v2/hitl/G3_SAMPLING_DESIGN_REVISION/archive_scene_bounded_recheck.csv"
)
SAMPLING_MODULE = ROOT / "src/urban_cooling_v2/hitl_gate3_sampling.py"
AUGMENTATION_RUNNER = ROOT / "src/run_v2_hitl_gate3_second_augmentation.py"

PRIMARY_CITY_WINDOWS = {
    ("atlanta", "jun_sep"),
    ("denver_aurora", "jun_sep"),
    ("minneapolis_st_paul", "jun_sep"),
    ("phoenix", "phoenix_apr_may"),
}
EXPECTED_LEDGER_ROWS = 762
EXPECTED_ARCHIVE_ROWS = 31
GENERATOR_VERSION = "d0069-g3-second-revision-v1"
WEATHER_ALGORITHM_VERSION = "d0069-hrrr-exact-four-field-repaired-domains-v1"
ZERO_MAP_PROOF_SCHEMA_VERSION = "d0079-generated-zero-map-proof-v1"
IMMUTABLE_D0070_HASHES = {
    ARCHIVE_SCENES: "54fba9c8e9d6f2c53f138f352e74615a9fa7f2a4ce4f144ab244edb34acae044",
    ARCHIVE_PASSES: "f39e3673f901941bf89d27a5ff85fab7120db751f2cdcc948754c4e22ffee6db",
    ARCHIVE_SUMMARY: "aeb0a16048b92367fcef13619eceb19b7e811e3d9d12c77fb7bc735dbba36360",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def strict_true(values: pd.Series) -> pd.Series:
    return values.astype("string").str.casefold().eq("true")


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError(f"{label} lacks required columns: {missing}")


def _canonical_records_sha256(frame: pd.DataFrame, columns: list[str]) -> str:
    records = (
        frame[columns]
        .sort_values(columns, kind="stable")
        .to_dict("records")
    )
    return hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _derive_new_archive_status_from_frames(
    passes: pd.DataFrame,
    links: pd.DataFrame,
    manifest: pd.DataFrame,
) -> pd.DataFrame:
    """Derive all 300 pass states solely from their sealed required scenes."""

    _require_columns(passes, {"city", "window_id", "orbit", "acquisition_utc"}, "new passes")
    _require_columns(links, {"city", "orbit", "scene"}, "new scene links")
    _require_columns(
        manifest,
        {"orbit", "scene", "status", "cmr_query_error_type"},
        "new scene manifest",
    )
    rows = passes.copy()
    exact_links = links.copy()
    scenes = manifest.copy()
    for table in (rows, exact_links, scenes):
        table["orbit"] = pd.to_numeric(table["orbit"], errors="raise").astype(int)
    exact_links["scene"] = pd.to_numeric(exact_links["scene"], errors="raise").astype(int)
    scenes["scene"] = pd.to_numeric(scenes["scene"], errors="raise").astype(int)
    pass_keys = set(rows[["city", "orbit"]].itertuples(index=False, name=None))
    link_pass_keys = set(exact_links[["city", "orbit"]].itertuples(index=False, name=None))
    link_scene_keys = set(exact_links[["orbit", "scene"]].itertuples(index=False, name=None))
    scene_keys = set(scenes[["orbit", "scene"]].itertuples(index=False, name=None))
    if (
        len(rows) != 300
        or rows.duplicated(["city", "orbit"]).any()
        or len(exact_links) != 488
        or exact_links.duplicated(["orbit", "scene"]).any()
        or len(scenes) != 488
        or scenes.duplicated(["orbit", "scene"]).any()
        or link_pass_keys != pass_keys
        or scene_keys != link_scene_keys
    ):
        raise ValueError("New archive provenance does not equal the sealed 300-pass/488-scene census")
    if not set(scenes["status"].astype(str)).issubset(
        {"available", "missing", "missing_required_endpoint"}
    ):
        raise ValueError("New scene manifest contains an unsealed archive status")
    lookup = scenes.set_index(["orbit", "scene"])
    derived: list[str] = []
    for city, orbit in rows[["city", "orbit"]].itertuples(index=False, name=None):
        required = exact_links.loc[
            exact_links["city"].eq(city) & exact_links["orbit"].eq(orbit),
            ["orbit", "scene"],
        ]
        if required.empty:
            raise ValueError("A new pass has no exact required orbit/scene link")
        keys = [tuple(map(int, row)) for row in required.to_records(index=False)]
        evidence = lookup.loc[keys]
        error = evidence["cmr_query_error_type"].fillna("").astype(str).str.strip().ne("").any()
        available = evidence["status"].astype(str).eq("available").all()
        derived.append(
            "UNRESOLVED_ERROR" if error else ("ACCESSIBLE" if available else "RESOLVED_UNAVAILABLE")
        )
    rows["archive_status"] = derived
    return rows


def _new_archive_provenance() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Rebuild required scene links and pass states from checksum-bound sources."""

    passes = pd.read_csv(NEW_PASSES_SOURCE)
    _require_columns(
        passes,
        {"city", "window_id", "orbit", "acquisition_utc", "time_stratum"},
        "new pass source",
    )
    passes = passes.loc[
        passes["time_stratum"].notna()
        & (
            (passes["city"].eq("denver_aurora") & passes["window_id"].eq("jun_sep"))
            | (
                passes["city"].eq("phoenix")
                & passes["window_id"].eq("phoenix_apr_may")
            )
        )
    ].copy()
    passes["orbit"] = pd.to_numeric(passes["orbit"], errors="raise").astype(int)
    if len(passes) != 300 or passes.duplicated(["city", "orbit"]).any():
        raise ValueError("New pass source does not reproduce the sealed 300 passes")
    metadata = pd.read_csv(NEW_METADATA_SOURCE)
    _require_columns(
        metadata,
        {"city", "window_id", "orbit", "scene", "tile", "granule_id"},
        "new L2T metadata source",
    )
    metadata["orbit"] = pd.to_numeric(metadata["orbit"], errors="raise").astype(int)
    metadata["scene"] = pd.to_numeric(metadata["scene"], errors="raise").astype(int)
    targets = metadata.merge(
        passes[["city", "window_id", "orbit"]],
        on=["city", "window_id", "orbit"],
        how="inner",
        validate="many_to_one",
    )
    revisions = targets["granule_id"].astype(str).str.extract(
        r"_(?P<build>[0-9]+)_(?P<revision>[0-9]+)$"
    )
    if revisions.isna().any().any():
        raise ValueError("A required L2T identity lacks build/revision fields")
    targets["_build"] = revisions["build"].astype(int)
    targets["_revision"] = revisions["revision"].astype(int)
    targets = (
        targets.sort_values(
            ["city", "orbit", "scene", "tile", "_build", "_revision", "granule_id"],
            kind="stable",
        )
        .drop_duplicates(["city", "orbit", "scene", "tile"], keep="last")
    )
    links = targets[["city", "orbit", "scene"]].drop_duplicates().reset_index(drop=True)
    manifest = pd.read_csv(NEW_SCENE_MANIFEST)
    expected = _derive_new_archive_status_from_frames(passes, links, manifest)
    evidence = {
        "pass_count": int(len(expected)),
        "required_scene_link_count": int(len(links)),
        "required_scene_links_sha256": _canonical_records_sha256(
            links, ["city", "orbit", "scene"]
        ),
        "scene_manifest_sha256": sha256_file(NEW_SCENE_MANIFEST),
        "archive_status_sha256": sha256_file(NEW_ARCHIVE_STATUS),
    }
    return expected, links, evidence


def _validate_new_archive_status_provenance(observed: pd.DataFrame) -> dict[str, Any]:
    expected, _, evidence = _new_archive_provenance()
    _require_columns(
        observed,
        {"city", "window_id", "orbit", "acquisition_utc", "archive_status"},
        "new archive status",
    )
    actual = observed.copy()
    actual["orbit"] = pd.to_numeric(actual["orbit"], errors="raise").astype(int)
    if len(actual) != 300 or actual.duplicated(["city", "orbit"]).any():
        raise ValueError("New archive status is not the sealed 300-pass census")
    comparison = expected[
        ["city", "window_id", "orbit", "acquisition_utc", "archive_status"]
    ].merge(
        actual[["city", "window_id", "orbit", "acquisition_utc", "archive_status"]],
        on=["city", "window_id", "orbit"],
        how="outer",
        suffixes=("_derived", "_observed"),
        indicator=True,
        validate="one_to_one",
    )
    derived_time = pd.to_datetime(
        comparison["acquisition_utc_derived"], utc=True, errors="coerce", format="mixed"
    )
    observed_time = pd.to_datetime(
        comparison["acquisition_utc_observed"], utc=True, errors="coerce", format="mixed"
    )
    if (
        not comparison["_merge"].eq("both").all()
        or not derived_time.eq(observed_time).all()
        or not comparison["archive_status_derived"].astype(str).eq(
            comparison["archive_status_observed"].astype(str)
        ).all()
    ):
        raise ValueError("New archive status rows do not match exact scene provenance")
    if actual["archive_status"].astype(str).eq("UNRESOLVED_ERROR").any():
        raise ValueError("New archive status retains UNRESOLVED_ERROR")
    evidence["status_counts"] = {
        str(key): int(value)
        for key, value in actual["archive_status"].astype(str).value_counts().sort_index().items()
    }
    return evidence


def _assert_historical_nonthermal(frame: pd.DataFrame, label: str) -> None:
    for column in ("temperature_or_lst_opened", "record_2026_opened"):
        if column not in frame:
            raise ValueError(f"{label} lacks the {column} safety seal")
        if strict_true(frame[column]).any():
            raise ValueError(f"{label} reports a forbidden opened-data state")
    if "acquisition_utc" in frame:
        years = pd.to_datetime(
            frame["acquisition_utc"], utc=True, errors="raise", format="mixed"
        ).dt.year
        if len(years) and (int(years.min()) < 2018 or int(years.max()) > 2025):
            raise ValueError(f"{label} escaped the historical 2018-2025 window")


def _packet_accepts_zero_mapped_scene(scene: Mapping[str, Any]) -> bool:
    """Independently recognize the two sealed D0047 zero-map proof forms."""

    try:
        mapped_count = int(scene.get("mapped_target_cell_count", -1))
    except (TypeError, ValueError):
        return False
    status = str(scene.get("proof_status", ""))
    if mapped_count != 0:
        return False
    if status not in {
        "verified_no_domain_overlap",
        "near_domain_full_resolution_verified",
    }:
        return False
    try:
        boundary_distance = float(scene.get("boundary_minimum_domain_distance_m"))
        selected_chunks = int(scene.get("final_chunk_count", 0))
        range_requests = int(scene.get("range_request_count", 0))
    except (TypeError, ValueError):
        return False
    chunk_hash = str(scene.get("selected_compressed_chunks_sha256", ""))
    range_hash = str(scene.get("range_evidence_sha256", ""))
    common = bool(
        scene.get("full_resolution_boundary_verified") is True
        and scene.get("boundary_verified") is True
        and math.isfinite(boundary_distance)
        and boundary_distance > 310.0
        and selected_chunks > 0
        and range_requests > 0
        and len(chunk_hash) == 64
        and all(character in "0123456789abcdef" for character in chunk_hash)
        and len(range_hash) == 64
        and all(character in "0123456789abcdef" for character in range_hash)
        and scene.get("missing_scene_substitution_used") is False
        and scene.get("missing_scene_zero_coverage_assigned") is False
        and scene.get("verified_no_overlap_zero_imputed") is False
    )
    if status == "verified_no_domain_overlap":
        return bool(
            common
            and scene.get("proof_mode") == "verified_no_overlap"
            and scene.get("proof_acceptance_status") == "verified_no_overlap_mapped_zero"
            and scene.get("verified_no_overlap_mapped_zero") is True
        )
    return bool(
        common
        and scene.get("proof_mode") == "locator_near_domain"
        and scene.get("proof_acceptance_status") == "ordinary_near_domain_mapping"
        and math.isfinite(boundary_distance)
        and boundary_distance > 310.0
    )


def _packet_validate_zero_mapped_evidence(
    document: Mapping[str, Any], *, item_id: str
) -> None:
    summary = document.get("summary")
    scenes = document.get("scene_evidence")
    binding = document.get("binding")
    common_complete = bool(
        document.get("status") != "complete"
        or not isinstance(summary, Mapping)
        or int(summary.get("n_view_valid_pixels", -1)) != 0
        or float(summary.get("l1b_geometry_coverage_fraction", math.nan)) != 0.0
        or not isinstance(scenes, list)
        or not scenes
        or int(summary.get("n_l1b_geo_scenes", -1)) != len(scenes)
    ) is False
    legacy_complete = bool(
        document.get("decision_id") == "D0047"
        and document.get("full_resolution") is True
        and document.get("boundary_verified") is True
        and isinstance(summary, Mapping)
        and summary.get("l1b_geometry_complete") is True
        and summary.get("geometry_definitive") is True
        and not bool(summary.get("quality_candidate_pre_cloud_geometry_only"))
    )
    generated_complete = bool(
        document.get("zero_map_proof_schema_version")
        == ZERO_MAP_PROOF_SCHEMA_VERSION
        and isinstance(binding, Mapping)
        and isinstance(summary, Mapping)
        and binding.get("decision_id") == "D0069"
        and summary.get("decision_id") == "D0069"
        and summary.get("source_population") == "new_d0069"
        and str(binding.get("city")) == str(summary.get("city"))
        and int(binding.get("orbit", -1)) == int(summary.get("orbit", -2))
        and summary.get("geometry_azimuth_complete") is True
        and summary.get("geometry_azimuth_status")
        == "RESOLVED_VERIFIED_ZERO_MAPPED_CELLS"
        and int(summary.get("n_overlapping_valid_pixels", -1)) == 0
        and document.get("temperature_or_lst_opened") is False
        and document.get("record_2026_opened") is False
    )
    if not common_complete or not (legacy_complete or generated_complete):
        raise ValueError(f"Zero-mapped geometry pass evidence is incomplete: {item_id}")
    rejected = []
    for scene in scenes:
        if _packet_accepts_zero_mapped_scene(scene):
            continue
        granule = str(scene.get("granule_id", "UNKNOWN_GRANULE"))
        rejected.append(
            f"{granule}: status={scene.get('proof_status')!r}, "
            f"mapped={scene.get('mapped_target_cell_count')!r}, "
            f"full_boundary={scene.get('full_resolution_boundary_verified')!r}"
        )
    if rejected:
        raise ValueError(
            f"Zero-mapped geometry scene proof rejected: {item_id}; scenes={rejected}"
        )


def _packet_resume_validation_digest(
    item_id: str, checkpoint: Mapping[str, Any], evidence_path: Path
) -> str:
    if (
        checkpoint.get("status") != "complete"
        or checkpoint.get("reuse_rule")
        or checkpoint.get("evidence_path") != str(evidence_path)
        or not evidence_path.is_file()
        or checkpoint.get("evidence_sha256") != sha256_file(evidence_path)
    ):
        raise ValueError(f"Geometry resume checkpoint/evidence is not reusable: {item_id}")
    document = json.loads(evidence_path.read_text(encoding="utf-8"))
    binding = document.get("binding", {})
    reconstruction = document.get("reconstruction_artifact", {})
    path = Path(str(reconstruction.get("path", "")))
    if (
        document.get("status") != "complete"
        or binding.get("algorithm_version") != "d0069-g3-five-field-geometry-v2"
        or checkpoint.get("binding_sha256") != hashlib.sha256(
            json.dumps(binding, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        or document.get("binding_sha256") != checkpoint.get("binding_sha256")
        or not path.is_file()
        or reconstruction.get("sha256") != sha256_file(path)
        or int(reconstruction.get("size_bytes", -1)) != path.stat().st_size
        or reconstruction.get("format_version") != "d0069-mapped-domain-cells-v1"
    ):
        raise ValueError(f"Geometry resume evidence/reconstruction binding failed: {item_id}")
    city, orbit_text = item_id.split(":", 1)
    with np.load(path, allow_pickle=False) as mapped:
        indices = mapped["valid_target_index"]
        if (
            str(mapped["format_version"]) != "d0069-mapped-domain-cells-v1"
            or str(mapped["city"]) != city
            or int(mapped["orbit"]) != int(orbit_text)
            or str(mapped["window_id"]) != str(document["summary"]["window_id"])
            or str(mapped["target_grid_sha256"])
            != str(reconstruction["target_grid_sha256"])
            or int(mapped["n_domain_pixels"]) != int(reconstruction["n_domain_pixels"])
            or len(indices) != int(reconstruction["n_valid_target_cells"])
            or not (
                len(mapped["view_zenith_abs_deg"])
                == len(mapped["view_azimuth_deg"])
                == len(mapped["solar_azimuth_deg"])
                == len(indices)
            )
        ):
            raise ValueError(f"Geometry resume NPZ identity/census failed: {item_id}")
    payload = {
        "item_id": item_id,
        "checkpoint_status": str(checkpoint.get("status")),
        "binding_sha256": str(checkpoint.get("binding_sha256")),
        "evidence_path": str(evidence_path),
        "evidence_sha256": sha256_file(evidence_path),
        "reconstruction_path": str(reconstruction["path"]),
        "reconstruction_sha256": str(reconstruction["sha256"]),
        "reconstruction_size_bytes": int(reconstruction["size_bytes"]),
        "format_version": str(reconstruction["format_version"]),
        "city": str(binding["city"]),
        "window_id": str(document["summary"]["window_id"]),
        "orbit": int(binding["orbit"]),
        "target_grid_sha256": str(reconstruction["target_grid_sha256"]),
        "n_domain_pixels": int(reconstruction["n_domain_pixels"]),
        "n_valid_target_cells": int(reconstruction["n_valid_target_cells"]),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def validate_geometry_reconstruction_inventory(
    augmentation: dict[str, Any], geometry: pd.DataFrame
) -> dict[str, Any]:
    inventory = augmentation.get("geometry_reconstruction_inventory", {})
    rows = inventory.get("passes", [])
    expected = set(
        geometry.loc[
            geometry["geometry_azimuth_status"].astype(str).ne("RESOLVED_UNAVAILABLE"),
            ["city", "orbit"],
        ].itertuples(index=False, name=None)
    )
    preflight = json.loads(GEOMETRY_RECONSTRUCTION_PREFLIGHT.read_text(encoding="utf-8"))
    resolved = geometry.loc[
        geometry["geometry_azimuth_status"].astype(str).ne("RESOLVED_UNAVAILABLE")
    ]
    expected_raw = int(pd.to_numeric(resolved["n_domain_pixels"], errors="raise").sum() * 16)
    expected_overhead = len(resolved) * 1024**2
    credited = [str(value) for value in preflight.get("credited_completed_item_ids", [])]
    sealed_digests = preflight.get("credited_completed_validation_sha256_by_item_id", {})
    resolved_by_id = {
        f"{row.city}:{int(row.orbit):05d}": row
        for row in resolved.itertuples(index=False)
    }
    if (
        len(credited) != len(set(credited))
        or set(credited) != set(sealed_digests)
        or not set(credited).issubset(resolved_by_id)
    ):
        raise ValueError("Geometry resume preflight credited census is invalid")
    completed_raw = int(
        sum(int(resolved_by_id[item_id].n_domain_pixels) * 16 for item_id in credited)
    )
    completed_overhead = len(credited) * 1024**2
    remaining_raw = expected_raw - completed_raw
    remaining_overhead = expected_overhead - completed_overhead
    preflight_name = str(GEOMETRY_RECONSTRUCTION_PREFLIGHT.relative_to(ROOT))
    if (
        augmentation.get("artifacts", {}).get(preflight_name)
        != sha256_file(GEOMETRY_RECONSTRUCTION_PREFLIGHT)
        or preflight.get("status") != "PASS"
        or preflight.get("format_version") != "d0069-mapped-domain-cells-v1"
        or int(preflight.get("candidate_passes", -1)) != len(resolved)
        or int(preflight.get("raw_array_worst_case_bytes", -1)) != expected_raw
        or int(preflight.get("container_overhead_bytes", -1)) != expected_overhead
        or int(preflight.get("conservative_new_data_bytes", -1))
        != expected_raw + expected_overhead
        or int(preflight.get("completed_passes", -1)) != len(credited)
        or int(preflight.get("completed_raw_array_worst_case_bytes", -1)) != completed_raw
        or int(preflight.get("completed_container_overhead_bytes", -1))
        != completed_overhead
        or int(preflight.get("completed_conservative_bytes", -1))
        != completed_raw + completed_overhead
        or int(preflight.get("remaining_passes", -1)) != len(resolved) - len(credited)
        or int(preflight.get("remaining_raw_array_worst_case_bytes", -1)) != remaining_raw
        or int(preflight.get("remaining_container_overhead_bytes", -1))
        != remaining_overhead
        or int(preflight.get("remaining_conservative_new_data_bytes", -1))
        != remaining_raw + remaining_overhead
        or int(preflight.get("raw_array_worst_case_bytes", -1))
        > int(preflight.get("absolute_maximum_bytes", -2))
        or int(preflight.get("required_free_bytes", -1))
        != int(preflight.get("remaining_conservative_new_data_bytes", -2))
        + int(preflight.get("explicit_reserve_bytes", -3))
        or int(preflight.get("observed_free_bytes", -1))
        < int(preflight.get("required_free_bytes", 0))
    ):
        raise ValueError("Geometry reconstruction storage preflight binding failed")
    observed = {(str(row.get("city")), int(row.get("orbit", -1))) for row in rows}
    if (
        inventory.get("format_version") != "d0069-mapped-domain-cells-v1"
        or inventory.get("storage_guard_pass") is not True
        or inventory.get("raw_mapped_per_pixel_reconstruction_supported") is not True
        or int(inventory.get("pass_count", -1)) != len(rows)
        or int(inventory.get("total_bytes", -1)) > int(inventory.get("maximum_bytes", -2))
        or observed != expected
    ):
        raise ValueError("Geometry reconstruction inventory is incomplete or unsafe")
    if credited:
        checkpoint_payload = json.loads(GEOMETRY_CHECKPOINT.read_text(encoding="utf-8"))
        checkpoint = checkpoint_payload.get("items", checkpoint_payload)
        for item_id in credited:
            record = checkpoint.get(item_id, {})
            evidence_path = Path(str(record.get("evidence_path", "")))
            if _packet_resume_validation_digest(item_id, record, evidence_path) != sealed_digests[item_id]:
                raise ValueError(f"Geometry resume validation digest changed: {item_id}")
    total = 0
    for record in rows:
        item_id = f"{record['city']}:{int(record['orbit']):05d}"
        path = ROOT / str(record.get("path", ""))
        evidence = ROOT / str(record.get("pass_evidence_path", ""))
        if (
            not path.is_file()
            or not evidence.is_file()
            or record.get("sha256") != sha256_file(path)
            or int(record.get("size_bytes", -1)) != path.stat().st_size
            or record.get("pass_evidence_sha256") != sha256_file(evidence)
        ):
            raise ValueError(f"Geometry reconstruction/pass evidence binding failed: {item_id}")
        if int(record.get("n_valid_target_cells", -1)) == 0:
            if str(
                geometry.loc[
                    geometry["city"].astype(str).eq(str(record["city"]))
                    & pd.to_numeric(geometry["orbit"], errors="coerce").eq(int(record["orbit"])),
                    "geometry_azimuth_status",
                ].iloc[0]
            ) != "RESOLVED_VERIFIED_ZERO_MAPPED_CELLS":
                raise ValueError(f"Zero-mapped geometry status is not truthful: {item_id}")
            _packet_validate_zero_mapped_evidence(
                json.loads(evidence.read_text(encoding="utf-8")), item_id=item_id
            )
        source_assets = record.get("source_assets", [])
        if not source_assets:
            raise ValueError(f"Geometry source-asset inventory is empty: {item_id}")
        for source in source_assets:
            dmrpp = ROOT / str(source.get("dmrpp_path", ""))
            locator = ROOT / str(source.get("locator_path", ""))
            if (
                not dmrpp.is_file()
                or not locator.is_file()
                or source.get("dmrpp_sha256") != sha256_file(dmrpp)
                or source.get("locator_sha256") != sha256_file(locator)
            ):
                raise ValueError(f"Geometry local metadata asset binding failed: {item_id}")
        selected_chunks = record.get("selected_compressed_chunk_hash_inventory", [])
        if int(record.get("selected_compressed_chunk_count", -1)) != len(selected_chunks):
            raise ValueError(f"Geometry selected-chunk inventory count failed: {item_id}")
        if any(
            not item.get("chunk_key") or len(str(item.get("sha256", ""))) != 64
            for item in selected_chunks
        ):
            raise ValueError(f"Geometry selected-chunk inventory malformed: {item_id}")
        total += path.stat().st_size
    if total != int(inventory.get("total_bytes", -1)):
        raise ValueError("Geometry reconstruction inventory byte total does not reconcile")
    return {
        "format_version": inventory["format_version"],
        "pass_count": len(rows),
        "total_bytes": total,
        "local_source_asset_hashes_verified": True,
        "storage_preflight_sha256": sha256_file(GEOMETRY_RECONSTRUCTION_PREFLIGHT),
    }


def validate_hrrr_storage_binding(augmentation: dict[str, Any]) -> dict[str, Any]:
    estimate = pd.read_csv(HRRR_STORAGE_ESTIMATE)
    preflight = json.loads(HRRR_STORAGE_PREFLIGHT.read_text(encoding="utf-8"))
    expected_bytes = int(
        pd.to_numeric(estimate["conservative_new_data_bytes"], errors="raise").sum()
    )
    artifacts = augmentation.get("artifacts", {})
    estimate_name = str(HRRR_STORAGE_ESTIMATE.relative_to(ROOT))
    preflight_name = str(HRRR_STORAGE_PREFLIGHT.relative_to(ROOT))
    if (
        artifacts.get(estimate_name) != sha256_file(HRRR_STORAGE_ESTIMATE)
        or artifacts.get(preflight_name) != sha256_file(HRRR_STORAGE_PREFLIGHT)
        or preflight.get("status") != "PASS"
        or preflight.get("weather_algorithm_version") != WEATHER_ALGORITHM_VERSION
        or int(preflight.get("conservative_new_data_bytes", -1)) != expected_bytes
        or int(preflight.get("required_free_bytes", -1))
        != expected_bytes + int(preflight.get("explicit_reserve_bytes", -2))
        or int(preflight.get("observed_free_bytes", -1))
        < int(preflight.get("required_free_bytes", 0))
        or preflight.get("estimate_sha256") != sha256_file(HRRR_STORAGE_ESTIMATE)
    ):
        raise ValueError("HRRR storage estimate/preflight binding failed")
    return {
        "weather_algorithm_version": WEATHER_ALGORITHM_VERSION,
        "estimate_sha256": sha256_file(HRRR_STORAGE_ESTIMATE),
        "preflight_sha256": sha256_file(HRRR_STORAGE_PREFLIGHT),
        "conservative_new_data_bytes": expected_bytes,
        "required_free_bytes": int(preflight["required_free_bytes"]),
        "observed_free_bytes": int(preflight["observed_free_bytes"]),
    }


def average_tie_percentile(reference: Iterable[Any], values: Iterable[Any]) -> np.ndarray:
    """Gate-2 average-tie empirical percentile on [0, 1]."""

    ref = pd.to_numeric(pd.Series(list(reference)), errors="coerce").dropna().to_numpy(float)
    if not len(ref):
        raise ValueError("Average-tie reference is empty")
    targets = pd.to_numeric(pd.Series(list(values)), errors="coerce").to_numpy(float)
    result = np.full(targets.shape, np.nan, dtype=float)
    finite = np.isfinite(targets)
    if len(ref) == 1:
        result[finite] = 0.5
        return result
    ordered = np.sort(ref)
    unique = np.unique(ordered)
    ranks = []
    for value in unique:
        left = int(np.searchsorted(ordered, value, side="left"))
        right = int(np.searchsorted(ordered, value, side="right"))
        average_rank = (left + 1 + right) / 2.0
        ranks.append((average_rank - 1.0) / (len(ordered) - 1.0))
    result[finite] = np.interp(targets[finite], unique, ranks, left=0.0, right=1.0)
    return result


def _window_id(city: str, month: int) -> str | None:
    if 6 <= month <= 9:
        return "jun_sep"
    if city == "phoenix" and month in (4, 5):
        return "phoenix_apr_may"
    if city in {"los_angeles", "sacramento"} and month == 10:
        return "california_october"
    return None


def relabel_archive_wetness(
    archive: pd.DataFrame,
    daily_gridmet: pd.DataFrame,
) -> pd.DataFrame:
    """Relabel all 31 inaccessible passes with the precipitation reference, never P-ET0."""

    required = {
        "observation_id",
        "city",
        "acquisition_utc",
        "year",
        "month",
        "time_stratum",
        "proxy_local_solar_date",
        "proxy_demand_percentile",
        "pass_recheck_classification",
    }
    _require_columns(archive, required, "archive pass audit")
    if len(archive) != EXPECTED_ARCHIVE_ROWS or archive["observation_id"].duplicated().any():
        raise ValueError("The frozen 31-pass archive census changed or is duplicated")
    if not archive["pass_recheck_classification"].eq("RESOLVED_UNAVAILABLE").all():
        raise ValueError("Every frozen archive pass must be RESOLVED_UNAVAILABLE")

    daily = add_antecedent_predictors(daily_gridmet.copy())
    _require_columns(
        daily,
        {"city", "date", "antecedent_precipitation_30d_mm"},
        "daily GridMET reference",
    )
    daily["date"] = pd.to_datetime(daily["date"], errors="raise")
    if daily["date"].dt.year.min() < 2018 or daily["date"].dt.year.max() > 2025:
        raise ValueError("Daily reference escaped 2018-2025")
    daily["window_id"] = [
        _window_id(str(city), int(month))
        for city, month in zip(daily["city"], daily["date"].dt.month, strict=True)
    ]
    daily = daily.loc[daily["window_id"].notna()].copy()
    daily["local_solar_date"] = daily["date"].dt.date

    output = archive.copy()
    output["window_id"] = [
        _window_id(str(city), int(month))
        for city, month in output[["city", "month"]].itertuples(index=False, name=None)
    ]
    if output["window_id"].isna().any():
        raise ValueError("An archive pass lies outside every frozen candidate window")
    output["local_solar_date"] = pd.to_datetime(
        output["proxy_local_solar_date"], errors="raise"
    ).dt.date
    lookup = daily[
        ["city", "window_id", "local_solar_date", "antecedent_precipitation_30d_mm"]
    ].drop_duplicates(["city", "window_id", "local_solar_date"])
    output = output.merge(
        lookup,
        on=["city", "window_id", "local_solar_date"],
        how="left",
        validate="many_to_one",
    )
    output["antecedent_precipitation_30d_wetness_percentile"] = np.nan
    for (city, window), indices in output.groupby(["city", "window_id"]).indices.items():
        reference = daily.loc[
            daily["city"].eq(city) & daily["window_id"].eq(window),
            "antecedent_precipitation_30d_mm",
        ]
        output.iloc[
            indices,
            output.columns.get_loc("antecedent_precipitation_30d_wetness_percentile"),
        ] = average_tie_percentile(
            reference,
            output.iloc[indices]["antecedent_precipitation_30d_mm"],
        )
    percentile = output["antecedent_precipitation_30d_wetness_percentile"]
    output["wetness_level"] = np.select(
        [percentile.lt(1 / 3), percentile.ge(2 / 3)],
        ["dry", "wet"],
        default="middle",
    )
    demand = pd.to_numeric(output["proxy_demand_percentile"], errors="coerce")
    output["demand_level"] = np.select(
        [demand.ge(2 / 3), demand.lt(1 / 3)],
        ["high", "low"],
        default="middle",
    )
    output["physical_pass_id"] = output["observation_id"].astype(str)
    output["bound_scope_included"] = [
        (str(city), str(window)) in PRIMARY_CITY_WINDOWS
        for city, window in output[["city", "window_id"]].itertuples(index=False, name=None)
    ]
    output["wetness_label_source"] = (
        "D0065 daily 30-day precipitation; city-window 2018-2025 average-tie percentile"
    )
    output["old_proxy_p_minus_et0_used_for_bounds"] = False
    required_values = [
        "antecedent_precipitation_30d_mm",
        "antecedent_precipitation_30d_wetness_percentile",
        "demand_level",
        "wetness_level",
    ]
    if output[required_values].isna().any().any():
        raise ValueError("Archive precipitation relabel is incomplete")
    return output


def unify_unavailable_ledger(
    historical_31: pd.DataFrame,
    new_status: pd.DataFrame,
    new_labels: pd.DataFrame,
) -> pd.DataFrame:
    """Combine the all-31 audit with every new unavailable D0069 primary pass."""

    _require_columns(new_status, {"city", "window_id", "orbit", "archive_status"}, "new archive status")
    if new_status.duplicated(["city", "orbit"]).any():
        raise ValueError("New archive status duplicates a physical city-orbit pass")
    if len(new_status) != 300:
        raise ValueError("New archive status does not contain the sealed 300-pass census")
    status_values = set(new_status["archive_status"].astype(str))
    if not status_values.issubset({"ACCESSIBLE", "RESOLVED_UNAVAILABLE", "UNRESOLVED_ERROR"}):
        raise ValueError(f"New archive status contains an unknown state: {sorted(status_values)}")
    if new_status["archive_status"].eq("UNRESOLVED_ERROR").any():
        raise ValueError("New D0069 archive status contains UNRESOLVED_ERROR")
    missing = new_status.loc[new_status["archive_status"].eq("RESOLVED_UNAVAILABLE")].copy()
    _require_columns(
        new_labels,
        {
            "city", "window_id", "orbit", "year", "time_stratum",
            "demand_level", "wetness_level", "archive_status",
            "exact_weather_complete", "temperature_or_lst_opened", "record_2026_opened",
        },
        "new unavailable condition labels",
    )
    _assert_historical_nonthermal(new_labels, "new unavailable condition labels")
    new_labels = new_labels.copy()
    new_labels["physical_pass_id"] = [
        f"{city}|orbit_{int(orbit):05d}"
        for city, orbit in new_labels[["city", "orbit"]].itertuples(index=False, name=None)
    ]
    new_labels["pass_recheck_classification"] = new_labels["archive_status"].astype(str)
    if new_labels.duplicated(["city", "orbit"]).any() or new_labels["physical_pass_id"].duplicated().any():
        raise ValueError("New unavailable labels duplicate a physical pass")
    expected = set(missing[["city", "orbit"]].itertuples(index=False, name=None))
    observed = set(new_labels[["city", "orbit"]].itertuples(index=False, name=None))
    if observed != expected:
        raise ValueError("New unavailable label census does not equal RESOLVED_UNAVAILABLE status rows")
    if (
        not new_labels["pass_recheck_classification"].eq("RESOLVED_UNAVAILABLE").all()
        or not strict_true(new_labels["exact_weather_complete"]).all()
    ):
        raise ValueError("A new unavailable pass lacks a frozen nonthermal label")
    if not set(new_labels[["city", "window_id"]].itertuples(index=False, name=None)).issubset(
        PRIMARY_CITY_WINDOWS
    ):
        raise ValueError("New unavailable labels escape the exact four D0069 windows")
    new = new_labels.copy()
    new["unavailable_source"] = "d0069_new_pass_archive_status"
    old = historical_31.copy()
    old["unavailable_source"] = "d0070_historical_31"
    unified = pd.concat([old, new], ignore_index=True, sort=False)
    if unified["physical_pass_id"].duplicated().any():
        raise ValueError("Unified unavailable ledger duplicates a physical pass")
    unified["bound_scope_included"] = [
        (str(city), str(window)) in PRIMARY_CITY_WINDOWS
        for city, window in unified[["city", "window_id"]].itertuples(index=False, name=None)
    ]
    return unified


def assemble_pass_evidence(
    geometry: pd.DataFrame,
    cloud: pd.DataFrame,
    weather: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate the ledger and join exact nonthermal pass evidence one-to-one."""

    _require_columns(
        geometry,
        {
            "city", "window_id", "orbit", "acquisition_utc", "year",
            "l1b_geometry_coverage_fraction", "l1b_view_zenith_abs_p95_deg",
            "view_azimuth_circular_mean_deg", "solar_azimuth_circular_mean_deg",
            "relative_azimuth_median_deg",
            "geometry_azimuth_complete", "geometry_azimuth_status",
        },
        "geometry ledger",
    )
    _require_columns(
        cloud,
        {"city", "window_id", "orbit", "clear_domain_fraction", "cloud_complete"},
        "cloud summary",
    )
    _require_columns(
        weather,
        {
            "city", "window_id", "orbit", "time_stratum", "demand_level",
            "wetness_level", "vpd_kpa_at_acquisition",
            "antecedent_precipitation_30d_mm", "air_temperature_k_at_acquisition",
            "wind_speed_m_s_at_acquisition", "day_of_window", "exact_weather_complete",
        },
        "weather summary",
    )
    for frame, label in ((geometry, "geometry"), (cloud, "cloud"), (weather, "weather")):
        _assert_historical_nonthermal(frame, label)
        if frame.duplicated(["city", "orbit"]).any():
            raise ValueError(f"{label} has duplicate city-orbit physical passes")
    if len(geometry) != EXPECTED_LEDGER_ROWS:
        raise ValueError(f"Geometry ledger has {len(geometry)} rows, expected {EXPECTED_LEDGER_ROWS}")
    memberships = set(
        geometry[["city", "window_id"]].drop_duplicates().itertuples(index=False, name=None)
    )
    if memberships != PRIMARY_CITY_WINDOWS:
        raise ValueError(f"Geometry ledger membership changed: {sorted(memberships)}")

    complete = strict_true(geometry["geometry_azimuth_complete"])
    expected_25 = geometry.loc[
        complete
        & pd.to_numeric(geometry["l1b_geometry_coverage_fraction"], errors="coerce").ge(0.95)
        & pd.to_numeric(geometry["l1b_view_zenith_abs_p95_deg"], errors="coerce").le(25.0)
    ].copy()
    expected_keys = set(expected_25[["city", "orbit"]].itertuples(index=False, name=None))
    cloud_keys = set(cloud[["city", "orbit"]].itertuples(index=False, name=None))
    weather_keys = set(weather[["city", "orbit"]].itertuples(index=False, name=None))
    if cloud_keys != expected_keys or weather_keys != expected_keys:
        raise ValueError("Cloud/weather census does not equal the <=25-degree geometry census")
    if not strict_true(cloud["cloud_complete"]).all() or not strict_true(
        weather["exact_weather_complete"]
    ).all():
        raise ValueError("Cloud or exact-weather evidence is not complete")

    cloud_columns = [
        "city", "window_id", "orbit", "clear_domain_fraction", "cloud_complete"
    ]
    evidence = expected_25.merge(
        cloud[cloud_columns],
        on=["city", "window_id", "orbit"],
        how="inner",
        validate="one_to_one",
    )
    weather_columns = [
        "city", "window_id", "orbit", "time_stratum", "demand_level",
        "wetness_level", "vpd_kpa_at_acquisition", "antecedent_precipitation_30d_mm",
        "air_temperature_k_at_acquisition", "wind_speed_m_s_at_acquisition",
        "day_of_window", "exact_weather_complete",
    ]
    evidence = evidence.merge(
        weather[weather_columns],
        on=["city", "window_id", "orbit"],
        how="inner",
        validate="one_to_one",
    )
    evidence["physical_pass_id"] = [
        f"{city}|orbit_{int(orbit):05d}"
        for city, orbit in evidence[["city", "orbit"]].itertuples(index=False, name=None)
    ]
    numeric_required = [
        "clear_domain_fraction", "l1b_geometry_coverage_fraction",
        "l1b_view_zenith_abs_p95_deg", "view_azimuth_circular_mean_deg",
        "solar_azimuth_circular_mean_deg", "relative_azimuth_median_deg",
        "vpd_kpa_at_acquisition",
        "antecedent_precipitation_30d_mm", "air_temperature_k_at_acquisition",
        "wind_speed_m_s_at_acquisition", "day_of_window",
    ]
    if not np.isfinite(
        evidence[numeric_required].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    ).all():
        raise ValueError("A <=25-degree pass has incomplete joined nonthermal evidence")

    detail = pd.concat(
        [
            evidence.loc[
                pd.to_numeric(evidence["l1b_view_zenith_abs_p95_deg"], errors="coerce").le(
                    threshold
                )
            ].assign(threshold_deg=threshold)
            for threshold in PRIMARY_ANGLE_THRESHOLDS
        ],
        ignore_index=True,
    )
    detail = detail.sort_values(
        ["threshold_deg", "city", "acquisition_utc", "orbit"], kind="stable"
    ).reset_index(drop=True)
    return evidence, detail


def validate_observed_condition_labels(detail: pd.DataFrame, daily_gridmet: pd.DataFrame) -> None:
    """Fail unless pass labels reproduce from the full candidate-day references."""

    daily = add_antecedent_predictors(daily_gridmet.copy())
    daily["date"] = pd.to_datetime(daily["date"], errors="raise")
    daily["window_id"] = [
        _window_id(str(city), int(month))
        for city, month in zip(daily["city"], daily["date"].dt.month, strict=True)
    ]
    daily = daily.loc[daily["window_id"].notna()].copy()
    for (city, window), indices in detail.groupby(["city", "window_id"]).indices.items():
        reference = daily.loc[daily["city"].eq(city) & daily["window_id"].eq(window)]
        demand_percentile = average_tie_percentile(
            reference["vpd_kpa"], detail.iloc[indices]["vpd_kpa_at_acquisition"]
        )
        wetness_percentile = average_tie_percentile(
            reference["antecedent_precipitation_30d_mm"],
            detail.iloc[indices]["antecedent_precipitation_30d_mm"],
        )
        demand = np.select(
            [demand_percentile >= 2 / 3, demand_percentile < 1 / 3],
            ["high", "low"],
            default="middle",
        )
        wetness = np.select(
            [wetness_percentile >= 2 / 3, wetness_percentile < 1 / 3],
            ["wet", "dry"],
            default="middle",
        )
        if not np.array_equal(demand, detail.iloc[indices]["demand_level"].astype(str)):
            raise ValueError(f"Observed demand labels do not reproduce for {city}/{window}")
        if not np.array_equal(wetness, detail.iloc[indices]["wetness_level"].astype(str)):
            raise ValueError(f"Observed precipitation wetness labels do not reproduce for {city}/{window}")


def _positive_range_overlap(left: pd.Series, right: pd.Series) -> float:
    a = pd.to_numeric(left, errors="coerce").dropna()
    b = pd.to_numeric(right, errors="coerce").dropna()
    if a.empty or b.empty:
        return math.nan
    return float(min(a.max(), b.max()) - max(a.min(), b.min()))


def build_eligibility(
    detail: pd.DataFrame,
    phenology: pd.DataFrame,
    archive_bounds: pd.DataFrame,
    unresolved_accessible: pd.DataFrame,
) -> pd.DataFrame:
    _require_columns(
        phenology,
        {
            "city", "window_id", "primary_phenology_pass", "canopy_sensitivity_pass",
            "phenology_auto_eligible", "phenology_status", "qa0_sensitivity_status",
        },
        "phenology decisions",
    )
    primary = phenology.loc[
        [
            (str(city), str(window)) in PRIMARY_CITY_WINDOWS
            for city, window in phenology[["city", "window_id"]].itertuples(
                index=False, name=None
            )
        ]
    ].copy()
    if (
        set(primary[["city", "window_id"]].itertuples(index=False, name=None))
        != PRIMARY_CITY_WINDOWS
        or primary.duplicated(["city", "window_id"]).any()
    ):
        raise ValueError("Phenology decisions lack the exact four D0069 windows")
    bound_lookup = archive_bounds.set_index("threshold_deg")
    rows: list[dict[str, Any]] = []
    for threshold in PRIMARY_ANGLE_THRESHOLDS:
        group = detail.loc[detail["threshold_deg"].eq(threshold)]
        pass_ids = sorted(group["physical_pass_id"].astype(str))
        pass_set_sha256 = hashlib.sha256(
            json.dumps(pass_ids, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for pheno in primary.to_dict("records"):
            support = group.loc[
                group["city"].eq(pheno["city"])
                & group["window_id"].eq(pheno["window_id"])
            ]
            high = support.loc[support["demand_level"].eq("high")]
            wet = high.loc[high["wetness_level"].eq("wet")]
            dry = high.loc[high["wetness_level"].eq("dry")]
            years = int(support["year"].nunique())
            am = int(support["time_stratum"].eq("10-12").sum())
            pm = int(support["time_stratum"].eq("16-18").sum())
            vpd_overlap = _positive_range_overlap(
                wet["vpd_kpa_at_acquisition"], dry["vpd_kpa_at_acquisition"]
            )
            day_overlap = _positive_range_overlap(wet["day_of_window"], dry["day_of_window"])
            archive_invariant = bool(bound_lookup.loc[threshold, "archive_bounds_invariant"])
            unresolved_count = int(
                len(
                    unresolved_accessible.loc[
                        unresolved_accessible["city"].eq(pheno["city"])
                        & unresolved_accessible["window_id"].eq(pheno["window_id"])
                    ]
                )
            )
            conditions = {
                "phenology_auto_eligible": bool(pheno["phenology_auto_eligible"]),
                "four_year_support_pass": years >= 4,
                "am_pm_support_pass": am >= 3 and pm >= 3,
                "wet_dry_support_pass": len(wet) >= 2 and len(dry) >= 2,
                "within_city_vpd_overlap_pass": bool(
                    np.isfinite(vpd_overlap) and vpd_overlap > 0
                ),
                "within_city_season_overlap_pass": bool(
                    np.isfinite(day_overlap) and day_overlap > 0
                ),
                "geometry_azimuth_cloud_exact_weather_complete": bool(len(support)),
                "archive_bounds_invariant": archive_invariant,
                "accessible_observation_accounting_complete": unresolved_count == 0,
            }
            reasons = [name for name, passed in conditions.items() if not passed]
            rows.append(
                {
                    **pheno,
                    "threshold_deg": threshold,
                    "qualifying_pass_count": int(group["physical_pass_id"].nunique()),
                    "qualifying_pass_set_sha256": pass_set_sha256,
                    "physical_passes": int(len(support)),
                    "clear_domain_pass_equivalents": float(
                        pd.to_numeric(support["clear_domain_fraction"], errors="coerce").sum()
                    ),
                    "qualifying_years": years,
                    "am_count": am,
                    "pm_count": pm,
                    "high_demand_wet_count": int(len(wet)),
                    "high_demand_dry_count": int(len(dry)),
                    "high_demand_wet_dry_vpd_range_overlap": vpd_overlap,
                    "high_demand_wet_dry_day_of_window_range_overlap": day_overlap,
                    "accessible_unresolved_pass_count": unresolved_count,
                    **conditions,
                    "eligible_city_window": not reasons,
                    "ineligibility_reasons": "|".join(reasons),
                }
            )
    return pd.DataFrame(rows)


def run_full_regression_suite() -> dict[str, Any]:
    v2 = sorted((ROOT / "src").glob("test_v2_*.py"))
    legacy = sorted(
        path for path in (ROOT / "src").glob("test_*.py") if not path.name.startswith("test_v2_")
    )
    rows = []
    with tempfile.TemporaryDirectory(prefix="g3-second-revision-tests-") as temp_dir:
        environment = os.environ.copy()
        environment.update(
            {
                "MPLCONFIGDIR": str(Path(temp_dir) / "matplotlib"),
                "XDG_CACHE_HOME": str(Path(temp_dir) / "xdg"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        for suite, paths in (("v2", v2), ("legacy", legacy)):
            for path in paths:
                started = time.monotonic()
                result = subprocess.run(
                    [sys.executable, str(path)],
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                rows.append(
                    {
                        "suite": suite,
                        "program": str(path.relative_to(ROOT)),
                        "program_sha256": sha256_file(path),
                        "returncode": int(result.returncode),
                        "passed": result.returncode == 0,
                        "duration_seconds": round(time.monotonic() - started, 3),
                        "stdout_last_line": result.stdout.strip().splitlines()[-1]
                        if result.stdout.strip()
                        else "",
                        "stderr_last_line": result.stderr.strip().splitlines()[-1]
                        if result.stderr.strip()
                        else "",
                    }
                )
    counts = {
        suite: {
            "discovered": sum(row["suite"] == suite for row in rows),
            "passed": sum(row["suite"] == suite and row["passed"] for row in rows),
            "failed": sum(row["suite"] == suite and not row["passed"] for row in rows),
        }
        for suite in ("v2", "legacy")
    }
    return {"counts": counts, "all_passed": bool(rows and all(row["passed"] for row in rows)), "programs": rows}


def run(*, run_tests: bool = True) -> dict[str, Any]:
    required_paths = [
        PHENOLOGY_RAW, GEOMETRY, CLOUD, WEATHER, AUGMENTATION_SUMMARY,
        HRRR_STORAGE_ESTIMATE, HRRR_STORAGE_PREFLIGHT, GEOMETRY_RECONSTRUCTION_PREFLIGHT,
        GEOMETRY_CHECKPOINT,
        NEW_ARCHIVE_STATUS, NEW_PASSES_SOURCE, NEW_METADATA_SOURCE, NEW_SCENE_MANIFEST,
        EXISTING_GEOMETRY_LINKS, EXISTING_GEOMETRY_SCENE_MANIFEST,
        NEW_UNAVAILABLE_LABELS, ARCHIVE_PASSES, ARCHIVE_SCENES,
        ARCHIVE_SUMMARY, DAILY_GRIDMET, D0069, D0067, D0070, D0071, D0072, D0073,
        D0074, D0075, D0076, D0077, D0078, D0079, D0080, D0081,
        SAMPLING_MODULE, AUGMENTATION_RUNNER,
    ]
    missing = [str(path.relative_to(ROOT)) for path in required_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Gate-3 second revision is fail-closed; missing inputs: {missing}")

    augmentation = json.loads(AUGMENTATION_SUMMARY.read_text(encoding="utf-8"))
    archive_summary = json.loads(ARCHIVE_SUMMARY.read_text(encoding="utf-8"))
    immutable_mismatches = {
        str(path.relative_to(ROOT)): sha256_file(path)
        for path, expected in IMMUTABLE_D0070_HASHES.items()
        if sha256_file(path) != expected
    }
    if immutable_mismatches:
        raise ValueError(f"Immutable D0070 archive evidence hash mismatch: {immutable_mismatches}")
    if augmentation.get("temperature_or_lst_opened") or augmentation.get("record_2026_opened"):
        raise ValueError("Augmentation summary violates the nonthermal historical lock")
    new_status_name = str(NEW_ARCHIVE_STATUS.relative_to(ROOT))
    if augmentation.get("artifacts", {}).get(new_status_name) != sha256_file(NEW_ARCHIVE_STATUS):
        raise ValueError("Completed 300-row new archive-status artifact is not augmentation-bound")
    manifest_name = str(NEW_SCENE_MANIFEST.relative_to(ROOT))
    if augmentation.get("artifacts", {}).get(manifest_name) != sha256_file(NEW_SCENE_MANIFEST):
        raise ValueError("Completed 488-row scene manifest is not augmentation-bound")
    new_archive_provenance = _validate_new_archive_status_provenance(
        pd.read_csv(NEW_ARCHIVE_STATUS, low_memory=False)
    )
    if (
        int(archive_summary.get("pass_count", -1)) != EXPECTED_ARCHIVE_ROWS
        or int(archive_summary.get("unresolved_error_count", -1)) != 0
        or archive_summary.get("record_2026_queried") is not False
    ):
        raise ValueError("Archive summary is incomplete, unresolved, or outside the lock")

    composites = pd.read_csv(PHENOLOGY_RAW, parse_dates=["date"])
    if composites["year"].min() != 2018 or composites["year"].max() != 2025:
        raise ValueError("Phenology evidence escaped 2018-2025")
    monthly, windows, phenology = summarize_phenology_sensitivities(composites)
    expected_pheno = phenology.loc[
        [
            (str(city), str(window)) in PRIMARY_CITY_WINDOWS
            for city, window in phenology[["city", "window_id"]].itertuples(index=False, name=None)
        ]
    ]
    if not expected_pheno["phenology_auto_eligible"].astype(bool).all():
        raise ValueError("The D0069 four-window primary/canopy phenology result did not reproduce")

    geometry = pd.read_csv(GEOMETRY, low_memory=False)
    cloud = pd.read_csv(CLOUD, low_memory=False)
    weather = pd.read_csv(WEATHER, low_memory=False)
    geometry_reconstruction = validate_geometry_reconstruction_inventory(
        augmentation, geometry
    )
    hrrr_storage_binding = validate_hrrr_storage_binding(augmentation)
    pass_evidence, detail = assemble_pass_evidence(geometry, cloud, weather)
    unresolved_accessible = geometry.loc[
        geometry["geometry_azimuth_status"].astype(str).eq("AZIMUTH_INCOMPLETE")
    ].copy()

    archive = pd.read_csv(ARCHIVE_PASSES, low_memory=False)
    daily = pd.read_csv(DAILY_GRIDMET, parse_dates=["date"])
    validate_observed_condition_labels(detail, daily)
    relabelled = relabel_archive_wetness(archive, daily)
    unified_unavailable = unify_unavailable_ledger(
        relabelled,
        pd.read_csv(NEW_ARCHIVE_STATUS, low_memory=False),
        pd.read_csv(NEW_UNAVAILABLE_LABELS, low_memory=False),
    )
    bound_scope = unified_unavailable.loc[
        strict_true(unified_unavailable["bound_scope_included"])
    ].copy()
    archive_bounds = build_archive_bound_diagnostics(
        detail,
        bound_scope[
            [
                "physical_pass_id", "city", "window_id", "year", "time_stratum",
                "demand_level", "wetness_level", "pass_recheck_classification",
            ]
        ],
    )
    balance, pairwise = build_balance_diagnostics(detail)
    balance = balance.merge(
        archive_bounds[["threshold_deg", "archive_bounds_invariant"]],
        on="threshold_deg",
        how="left",
        validate="one_to_one",
    )
    eligibility = build_eligibility(detail, phenology, archive_bounds, unresolved_accessible)
    selection = selection_result(eligibility, balance)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    tables = {
        "phenology_monthly.csv": monthly,
        "phenology_windows_long.csv": windows,
        "phenology_decisions.csv": phenology,
        "archive_all_31_precipitation_relabel.csv": relabelled,
        "unified_unavailable_pass_ledger.csv": unified_unavailable,
        "accessible_unresolved_geometry_ledger.csv": unresolved_accessible,
        "archive_bounds_four_primary_windows.csv": archive_bounds,
        "pass_evidence_25deg_joined.csv": pass_evidence,
        "threshold_pass_detail.csv": detail,
        "threshold_city_window_eligibility.csv": eligibility,
        "balance_diagnostics.csv": balance,
        "pairwise_balance_diagnostics.csv": pairwise,
    }
    for name, frame in tables.items():
        atomic_csv(OUTPUT / name, frame)
    atomic_json(OUTPUT / "selection.json", selection)

    regression = run_full_regression_suite() if run_tests else {
        "counts": {"v2": {"discovered": 0, "passed": 0, "failed": 0}, "legacy": {"discovered": 0, "passed": 0, "failed": 0}},
        "all_passed": False,
        "programs": [],
        "status": "NOT_RUN",
    }
    atomic_json(OUTPUT / "full_regression_suite.json", regression)

    source_paths = required_paths + [Path(__file__), ROOT / "src/run_v2_hitl_gate3_cleanroom_check.py"]
    source_bindings = {
        "generator_version": GENERATOR_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "sources": {
            str(path.relative_to(ROOT)): sha256_file(path)
            for path in source_paths
            if path.is_file()
        },
        "new_archive_status_provenance": new_archive_provenance,
        "locks": {
            "temperature_or_lst_opened": False,
            "holdout_data_opened": False,
            "record_2026_science_data_opened_or_queried": False,
            "record_2026_metadata_exposures_preserved": [
                "D0060", "D0061", "D0073", "D0074"
            ],
        },
    }
    atomic_json(OUTPUT / "source_bindings.json", source_bindings)

    checks = {
        "decision_id": "D0069",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "four_primary_phenology_windows_reproduced": bool(expected_pheno["phenology_auto_eligible"].all()),
        "geometry_ledger_rows": int(len(geometry)),
        "geometry_ledger_complete": len(geometry) == EXPECTED_LEDGER_ROWS,
        "geometry_solar_azimuth_required": True,
        "geometry_reconstruction_inventory": geometry_reconstruction,
        "hrrr_storage_binding": hrrr_storage_binding,
        "joined_25deg_passes": int(len(pass_evidence)),
        "archive_all_31_relabelled": len(relabelled) == EXPECTED_ARCHIVE_ROWS,
        "unified_unavailable_passes": int(len(unified_unavailable)),
        "new_resolved_unavailable_passes": int(len(unified_unavailable) - len(relabelled)),
        "new_archive_status_provenance": new_archive_provenance,
        "accessible_unresolved_geometry_passes": int(len(unresolved_accessible)),
        "immutable_d0070_hashes_match": True,
        "archive_bound_scope_rows": int(len(bound_scope)),
        "old_p_minus_et0_proxy_used_for_bounds": False,
        "selection": selection,
        "full_regression_suite_all_passed": bool(regression["all_passed"]),
        "temperature_or_lst_opened": False,
        "holdout_data_opened": False,
        "record_2026_science_data_opened_or_queried": False,
        "record_2026_metadata_exposures_preserved": [
            "D0060", "D0061", "D0073", "D0074"
        ],
    }
    atomic_json(OUTPUT / "checks.json", checks)

    selected = selection.get("primary_view_zenith_threshold_deg")
    decision = "APPROVE_FOR_INDEPENDENT_REVIEW" if selected is not None else "REVISE_REQUIRED"
    review = f"""# Gate 3 second-revision review — prospective sampling design

## Decision

`{decision}`

The D0069 historical nonthermal augmentation was joined one physical city-orbit
pass at a time. The production selector returned **{selection.get('gate_status')}**
with selected primary view-zenith threshold **{selected if selected is not None else 'none'}**.
This packet does not itself approve Gate 3; independent clean-room and agent
review must agree before the delegated workflow can advance.

## Frozen membership and phenology

The prospective design is limited to Atlanta June-September, Denver-Aurora
June-September, Minneapolis-St. Paul June-September, and Phoenix April-May.
Eligibility uses the primary QA-0+1 screen plus canopy-masked confirmation.
QA-0-only remains a prominently reported sensitivity and is not an automatic veto.

## Observation accounting and balance

- Geometry ledger: **{len(geometry)}** unique city-orbit rows.
- Joined complete passes qualifying at 25 degrees: **{len(pass_evidence)}**.
- Archive audit: all **{len(relabelled)}** historical D0070 passes plus
  **{len(unified_unavailable) - len(relabelled)}** new D0069 unavailable passes retained;
  **{len(bound_scope)}**
  belong to the exact four primary windows used in selection bounds.
- Wet/dry archive labels were recomputed from the D0065 30-day precipitation
  reference with Gate-2 average-tie percentiles. The old P-ET0 proxy was not used.
- Archive lower/upper threshold invariance: **{bool(archive_bounds['archive_bounds_invariant'].all())}**.
- Full discovered tests passed: **{bool(regression['all_passed'])}**.

## Locks

No temperature/LST value, thermal outcome, holdout datum, or 2026 science record
was opened. The prior D0060/D0061 metadata-query deviations and D0073/D0074
incidental repository-metadata exposures remain disclosed and excluded from this evidence.
G3A and Gate 4+ remain locked pending the independent review record.
"""
    (OUTPUT / "review.md").write_text(review, encoding="utf-8")
    reviewer_record = {
        "gate": "G3_SAMPLING_DESIGN_SECOND_REVISION",
        "status": "PENDING_INDEPENDENT_AGENT_REVIEW",
        "packet_checks_sha256": sha256_file(OUTPUT / "checks.json"),
        "packet_review_sha256": sha256_file(OUTPUT / "review.md"),
        "cleanroom_verification": "PENDING",
        "blocking_findings": [],
        "reviewer": None,
        "reviewed_utc": None,
    }
    atomic_json(OUTPUT / "reviewer_record.json", reviewer_record)
    return checks


def main() -> int:
    run(run_tests=True)
    print("PASS run_v2_hitl_gate3_second_revision")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
