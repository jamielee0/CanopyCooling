#!/usr/bin/env python3
"""Independent, network-free verification of the D0069 Gate-3 packet.

This module intentionally does not import the production Gate-3 sampling module
or the D0069 augmentation runner.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "docs/v2/hitl/G3_SAMPLING_DESIGN_SECOND_REVISION"
GEOMETRY = ROOT / "data/processed/v2/hitl/g3_sampling_design_revision2/geometry_azimuth_pass_summary.csv"
CLOUD = ROOT / "data/processed/v2/hitl/g3_sampling_design_revision2/cloud_pass_summary.csv"
WEATHER = ROOT / "data/processed/v2/hitl/g3_sampling_design_revision2/exact_weather_and_condition_pass_summary.csv"
ARCHIVE = ROOT / "docs/v2/hitl/G3_SAMPLING_DESIGN_REVISION/archive_pass_bounded_recheck_and_bounds.csv"
ARCHIVE_SCENES = ROOT / "docs/v2/hitl/G3_SAMPLING_DESIGN_REVISION/archive_scene_bounded_recheck.csv"
ARCHIVE_SUMMARY = ROOT / "docs/v2/hitl/G3_SAMPLING_DESIGN_REVISION/archive_bounded_recheck_summary.json"
NEW_ARCHIVE_STATUS = ROOT / "data/processed/v2/hitl/g3_sampling_design_revision2/new_pass_archive_status.csv"
NEW_PASSES_SOURCE = ROOT / "docs/v2/hitl/G3_SAMPLING_DESIGN/candidate_addition_physical_metadata_passes.csv"
NEW_METADATA_SOURCE = ROOT / "data/raw/v2/hitl/g3_sampling_design/candidate_additions_l2t_metadata_2018_2025.csv"
NEW_SCENE_MANIFEST = ROOT / "data/raw/v2/hitl/g3_sampling_design_revision2/new_l1b_geo/l1b_geo_scene_manifest.csv"
NEW_UNAVAILABLE_LABELS = ROOT / "data/processed/v2/hitl/g3_sampling_design_revision2/new_unavailable_condition_pass_summary.csv"
DAILY = ROOT / "data/raw/v2/hitl/g3_sampling_design/candidate_city_daily_gridmet_2018_2025.csv"
DOMAINS = ROOT / "data/raw/v2/hitl/g3_sampling_design/candidate_domains_7.geojson"
DOMAINS_PROVENANCE = ROOT / "data/raw/v2/hitl/g3_sampling_design/candidate_domains_7.geojson.provenance.json"
HRRR_MANIFEST = ROOT / "data/raw/v2/hitl/g3_sampling_design_revision2/hrrr_exact_acquisition_manifest.csv"
HRRR_SUMMARY = ROOT / "data/raw/v2/hitl/g3_sampling_design_revision2/hrrr_exact_acquisition/hrrr_hourly_domain_summary.csv"
HRRR_CHECKPOINT = ROOT / "data/raw/v2/hitl/g3_sampling_design_revision2/hrrr_exact_acquisition/hrrr_checkpoint_d0069.json"
HRRR_SHARDS = ROOT / "data/raw/v2/hitl/g3_sampling_design_revision2/hrrr_exact_acquisition/hourly_domain_cells"
HRRR_STORAGE_ESTIMATE = ROOT / "data/raw/v2/hitl/g3_sampling_design_revision2/hrrr_exact_acquisition/hrrr_storage_estimate.csv"
HRRR_STORAGE_PREFLIGHT = ROOT / "data/raw/v2/hitl/g3_sampling_design_revision2/hrrr_exact_acquisition/hrrr_storage_preflight.json"
AUGMENTATION_SUMMARY = ROOT / "data/processed/v2/hitl/g3_sampling_design_revision2/augmentation_summary.json"
GEOMETRY_CHECKPOINT = ROOT / "data/raw/v2/hitl/g3_sampling_design_revision2/geometry_azimuth_checkpoint.json"
GEOMETRY_RECONSTRUCTION_PREFLIGHT = ROOT / "data/raw/v2/hitl/g3_sampling_design_revision2/geometry_reconstruction_storage_preflight.json"
EXISTING_GEOMETRY_LINKS = ROOT / "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/retained_city_scene_links.csv"
EXISTING_GEOMETRY_SCENE_MANIFEST = ROOT / "data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available/l1b_geo_scene_manifest.csv"
THRESHOLDS = (10, 15, 20, 25)
PRIMARY = {
    ("atlanta", "jun_sep"),
    ("denver_aurora", "jun_sep"),
    ("minneapolis_st_paul", "jun_sep"),
    ("phoenix", "phoenix_apr_may"),
}
WEATHER_ALGORITHM_VERSION = "d0069-hrrr-exact-four-field-repaired-domains-v1"
ZERO_MAP_PROOF_SCHEMA_VERSION = "d0079-generated-zero-map-proof-v1"
RECONSTRUCTION_FLOAT32_ATOL = 1e-5
TEMPERATURE_SEARCH = r":(?:TMP|DPT):2 m"
WIND_SEARCH = r":(?:UGRD|VGRD):10 m above ground"
HRRR_SOURCE = (
    "NOAA HRRR public AWS archive; exact analysis f00 2-m TMP/DPT and "
    "10-m UGRD/VGRD; sfc with frozen prs fallback"
)
IMMUTABLE_ARCHIVE_HASHES = {
    ARCHIVE_SCENES: "54fba9c8e9d6f2c53f138f352e74615a9fa7f2a4ce4f144ab244edb34acae044",
    ARCHIVE: "f39e3673f901941bf89d27a5ff85fab7120db751f2cdcc948754c4e22ffee6db",
    ARCHIVE_SUMMARY: "aeb0a16048b92367fcef13619eceb19b7e811e3d9d12c77fb7bc735dbba36360",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _records_sha(frame: pd.DataFrame, columns: list[str]) -> str:
    return _canonical_sha(
        frame[columns].sort_values(columns, kind="stable").to_dict("records")
    )


def _independent_derive_new_archive_status(
    passes: pd.DataFrame,
    links: pd.DataFrame,
    manifest: pd.DataFrame,
) -> pd.DataFrame:
    """Clean-room pass-state derivation from exact scene links and outcomes."""

    required = (
        ({"city", "window_id", "orbit", "acquisition_utc"}, passes, "passes"),
        ({"city", "orbit", "scene"}, links, "links"),
        ({"orbit", "scene", "status", "cmr_query_error_type"}, manifest, "manifest"),
    )
    for columns, frame, label in required:
        missing = sorted(columns.difference(frame.columns))
        if missing:
            raise ValueError(f"Clean-room new archive {label} lacks columns: {missing}")
    rows = passes.copy()
    exact_links = links.copy()
    scenes = manifest.copy()
    for table in (rows, exact_links, scenes):
        table["orbit"] = pd.to_numeric(table["orbit"], errors="raise").astype(int)
    exact_links["scene"] = pd.to_numeric(exact_links["scene"], errors="raise").astype(int)
    scenes["scene"] = pd.to_numeric(scenes["scene"], errors="raise").astype(int)
    if (
        len(rows) != 300
        or rows.duplicated(["city", "orbit"]).any()
        or len(exact_links) != 488
        or exact_links.duplicated(["orbit", "scene"]).any()
        or len(scenes) != 488
        or scenes.duplicated(["orbit", "scene"]).any()
        or set(exact_links[["city", "orbit"]].itertuples(index=False, name=None))
        != set(rows[["city", "orbit"]].itertuples(index=False, name=None))
        or set(exact_links[["orbit", "scene"]].itertuples(index=False, name=None))
        != set(scenes[["orbit", "scene"]].itertuples(index=False, name=None))
    ):
        raise ValueError("Clean-room exact 300-pass/488-scene archive census changed")
    if not set(scenes["status"].astype(str)).issubset(
        {"available", "missing", "missing_required_endpoint"}
    ):
        raise ValueError("Clean-room scene manifest contains an unsealed status")
    lookup = scenes.set_index(["orbit", "scene"])
    states: list[str] = []
    for city, orbit in rows[["city", "orbit"]].itertuples(index=False, name=None):
        required_scenes = exact_links.loc[
            exact_links["city"].eq(city) & exact_links["orbit"].eq(orbit),
            ["orbit", "scene"],
        ]
        if required_scenes.empty:
            raise ValueError("Clean-room pass lacks an exact required scene link")
        keys = [tuple(map(int, value)) for value in required_scenes.to_records(index=False)]
        evidence = lookup.loc[keys]
        has_error = evidence["cmr_query_error_type"].fillna("").astype(str).str.strip().ne("").any()
        all_available = evidence["status"].astype(str).eq("available").all()
        states.append(
            "UNRESOLVED_ERROR" if has_error else ("ACCESSIBLE" if all_available else "RESOLVED_UNAVAILABLE")
        )
    rows["archive_status"] = states
    return rows


def _independent_new_archive_provenance() -> tuple[pd.DataFrame, dict[str, Any]]:
    """Reconstruct links from frozen candidate sources, then compare all statuses."""

    passes = pd.read_csv(NEW_PASSES_SOURCE)
    needed_pass = {"city", "window_id", "orbit", "acquisition_utc", "time_stratum"}
    if needed_pass.difference(passes.columns):
        raise ValueError("Clean-room frozen candidate-pass source is incomplete")
    passes = passes.loc[
        passes["time_stratum"].notna()
        & (
            (passes["city"].eq("denver_aurora") & passes["window_id"].eq("jun_sep"))
            | (passes["city"].eq("phoenix") & passes["window_id"].eq("phoenix_apr_may"))
        )
    ].copy()
    passes["orbit"] = pd.to_numeric(passes["orbit"], errors="raise").astype(int)
    metadata = pd.read_csv(NEW_METADATA_SOURCE)
    needed_metadata = {"city", "window_id", "orbit", "scene", "tile", "granule_id"}
    if needed_metadata.difference(metadata.columns):
        raise ValueError("Clean-room frozen L2T source is incomplete")
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
        raise ValueError("Clean-room L2T identity lacks build/revision fields")
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
    derived = _independent_derive_new_archive_status(
        passes, links, pd.read_csv(NEW_SCENE_MANIFEST)
    )
    observed = pd.read_csv(NEW_ARCHIVE_STATUS)
    required_status = {"city", "window_id", "orbit", "acquisition_utc", "archive_status"}
    if required_status.difference(observed.columns):
        raise ValueError("Clean-room archive-status artifact lacks governed fields")
    observed["orbit"] = pd.to_numeric(observed["orbit"], errors="raise").astype(int)
    comparison = derived[
        ["city", "window_id", "orbit", "acquisition_utc", "archive_status"]
    ].merge(
        observed[["city", "window_id", "orbit", "acquisition_utc", "archive_status"]],
        on=["city", "window_id", "orbit"],
        how="outer",
        suffixes=("_derived", "_observed"),
        indicator=True,
        validate="one_to_one",
    )
    if (
        len(observed) != 300
        or observed.duplicated(["city", "orbit"]).any()
        or not comparison["_merge"].eq("both").all()
        or not pd.to_datetime(
            comparison["acquisition_utc_derived"], utc=True, errors="coerce", format="mixed"
        ).eq(
            pd.to_datetime(
                comparison["acquisition_utc_observed"], utc=True, errors="coerce", format="mixed"
            )
        ).all()
        or not comparison["archive_status_derived"].astype(str).eq(
            comparison["archive_status_observed"].astype(str)
        ).all()
    ):
        raise ValueError("Clean-room archive statuses do not match exact scene provenance")
    if observed["archive_status"].astype(str).eq("UNRESOLVED_ERROR").any():
        raise ValueError("Clean-room exact archive provenance retains UNRESOLVED_ERROR")
    evidence = {
        "pass_count": int(len(derived)),
        "required_scene_link_count": int(len(links)),
        "required_scene_links_sha256": _records_sha(links, ["city", "orbit", "scene"]),
        "scene_manifest_sha256": _sha(NEW_SCENE_MANIFEST),
        "archive_status_sha256": _sha(NEW_ARCHIVE_STATUS),
        "status_counts": {
            str(key): int(value)
            for key, value in observed["archive_status"].astype(str).value_counts().sort_index().items()
        },
    }
    return derived, evidence


def _circular_summary(values: np.ndarray) -> tuple[float, float]:
    radians = np.deg2rad(np.mod(values.astype(float), 360.0))
    sine = float(np.mean(np.sin(radians)))
    cosine = float(np.mean(np.cos(radians)))
    return float(np.degrees(np.arctan2(sine, cosine)) % 360.0), float(np.hypot(sine, cosine))


def _replay_mapped_geometry_summary(
    view: np.ndarray,
    view_azimuth: np.ndarray,
    solar_azimuth: np.ndarray,
    n_domain_pixels: int,
) -> dict[str, Any]:
    view = np.asarray(view, dtype=float)
    view_azimuth = np.asarray(view_azimuth, dtype=float)
    solar_azimuth = np.asarray(solar_azimuth, dtype=float)
    if not (len(view) == len(view_azimuth) == len(solar_azimuth)) or not len(view):
        raise ValueError("Mapped geometry replay requires aligned nonempty view cells")
    valid_azimuth = np.isfinite(view_azimuth) & np.isfinite(solar_azimuth)
    azimuth_complete = bool(valid_azimuth.all())
    result: dict[str, Any] = {
        "l1b_geometry_coverage_fraction": len(view) / int(n_domain_pixels),
        "l1b_view_zenith_abs_min_deg": float(np.min(view)),
        "l1b_view_zenith_abs_median_deg": float(np.median(view)),
        "l1b_view_zenith_abs_mean_deg": float(np.mean(view)),
        "l1b_view_zenith_abs_p95_deg": float(np.quantile(view, 0.95)),
        "l1b_view_zenith_abs_max_deg": float(np.max(view)),
        "azimuth_valid_fraction_of_view_cells": float(valid_azimuth.sum() / len(view)),
        "geometry_azimuth_complete": azimuth_complete,
        "geometry_azimuth_status": "COMPLETE" if azimuth_complete else "AZIMUTH_INCOMPLETE",
    }
    if valid_azimuth.any():
        paired_view = view_azimuth[valid_azimuth]
        paired_solar = solar_azimuth[valid_azimuth]
        separation = np.mod(np.abs(paired_view - paired_solar), 360.0)
        relative = np.minimum(separation, 360.0 - separation)
        view_mean, view_concentration = _circular_summary(paired_view)
        solar_mean, solar_concentration = _circular_summary(paired_solar)
        result.update(
            {
                "view_azimuth_circular_mean_deg": view_mean,
                "view_azimuth_circular_concentration": view_concentration,
                "solar_azimuth_circular_mean_deg": solar_mean,
                "solar_azimuth_circular_concentration": solar_concentration,
                "relative_azimuth_q1_deg": float(np.quantile(relative, 0.25)),
                "relative_azimuth_median_deg": float(np.median(relative)),
                "relative_azimuth_q3_deg": float(np.quantile(relative, 0.75)),
                "relative_azimuth_iqr_deg": float(
                    np.quantile(relative, 0.75) - np.quantile(relative, 0.25)
                ),
            }
        )
    return result


def _cleanroom_accepts_zero_mapped_scene(scene: dict[str, Any]) -> bool:
    """Independent strict predicate for sealed D0047 zero-map scene proof."""

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


def _cleanroom_validate_zero_mapped_document(
    document: dict[str, Any], *, item_id: str
) -> None:
    summary = document.get("summary")
    scenes = document.get("scene_evidence")
    binding = document.get("binding")
    common_complete = bool(
        document.get("status") != "complete"
        or not isinstance(summary, dict)
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
        and isinstance(summary, dict)
        and summary.get("l1b_geometry_complete") is True
        and summary.get("geometry_definitive") is True
        and not bool(summary.get("quality_candidate_pre_cloud_geometry_only"))
    )
    generated_complete = bool(
        document.get("zero_map_proof_schema_version")
        == ZERO_MAP_PROOF_SCHEMA_VERSION
        and isinstance(binding, dict)
        and isinstance(summary, dict)
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
        raise ValueError(f"Clean-room zero-mapped evidence incomplete: {item_id}")
    rejected = []
    for scene in scenes:
        if isinstance(scene, dict) and _cleanroom_accepts_zero_mapped_scene(scene):
            continue
        evidence = scene if isinstance(scene, dict) else {}
        rejected.append(
            f"{evidence.get('granule_id', 'UNKNOWN_GRANULE')}: "
            f"status={evidence.get('proof_status')!r}, "
            f"mapped={evidence.get('mapped_target_cell_count')!r}, "
            f"full_boundary={evidence.get('full_resolution_boundary_verified')!r}"
        )
    if rejected:
        raise ValueError(
            f"Clean-room zero-mapped scene proof rejected: {item_id}; scenes={rejected}"
        )


def _cleanroom_resume_validation_digest(
    item_id: str, checkpoint: dict[str, Any]
) -> str:
    evidence_path = Path(str(checkpoint.get("evidence_path", "")))
    if (
        checkpoint.get("status") != "complete"
        or checkpoint.get("reuse_rule")
        or checkpoint.get("evidence_path") != str(evidence_path)
        or not evidence_path.is_file()
        or checkpoint.get("evidence_sha256") != _sha(evidence_path)
    ):
        raise ValueError(f"Clean-room resume checkpoint is not reusable: {item_id}")
    document = json.loads(evidence_path.read_text(encoding="utf-8"))
    binding = document.get("binding", {})
    reconstruction = document.get("reconstruction_artifact", {})
    reconstruction_path = Path(str(reconstruction.get("path", "")))
    if (
        document.get("status") != "complete"
        or binding.get("algorithm_version") != "d0069-g3-five-field-geometry-v2"
        or checkpoint.get("binding_sha256") != _canonical_sha(binding)
        or document.get("binding_sha256") != checkpoint.get("binding_sha256")
        or not reconstruction_path.is_file()
        or reconstruction.get("sha256") != _sha(reconstruction_path)
        or int(reconstruction.get("size_bytes", -1)) != reconstruction_path.stat().st_size
        or reconstruction.get("format_version") != "d0069-mapped-domain-cells-v1"
    ):
        raise ValueError(f"Clean-room resume evidence binding failed: {item_id}")
    city, orbit_text = item_id.split(":", 1)
    with np.load(reconstruction_path, allow_pickle=False) as mapped:
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
            raise ValueError(f"Clean-room resume NPZ identity failed: {item_id}")
    return _canonical_sha(
        {
            "item_id": item_id,
            "checkpoint_status": str(checkpoint.get("status")),
            "binding_sha256": str(checkpoint.get("binding_sha256")),
            "evidence_path": str(evidence_path),
            "evidence_sha256": _sha(evidence_path),
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
    )


def _cleanroom_compare_zero_scene_census(
    document: dict[str, Any],
    expected_rows: list[tuple[int, int, str]],
    *,
    item_id: str,
) -> None:
    """Require exact, unique binding/evidence equality to the frozen scene census."""

    bindings = document.get("binding", {}).get("scene_bindings", [])
    evidence = document.get("scene_evidence", [])
    observed = [
        (int(row.get("orbit", -1)), int(row.get("scene", -1)), str(row.get("granule_id", "")))
        for row in bindings
    ]
    observed_evidence = [
        (int(row.get("orbit", -1)), int(row.get("scene", -1)), str(row.get("granule_id", "")))
        for row in evidence
    ]
    if (
        not expected_rows
        or len(observed) != len(expected_rows)
        or len(set(observed)) != len(observed)
        or set(observed) != set(expected_rows)
        or len(observed_evidence) != len(observed)
        or len(set(observed_evidence)) != len(observed_evidence)
        or set(observed_evidence) != set(observed)
    ):
        raise ValueError(f"Reused geometry scene census differs from frozen identities: {item_id}")


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _strict_true(series: pd.Series) -> pd.Series:
    return series.astype("string").str.casefold().eq("true")


def _columns(frame: pd.DataFrame, required: Iterable[str], label: str) -> None:
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise ValueError(f"{label} missing columns {missing}")


def _window(city: str, month: int) -> str | None:
    if 6 <= month <= 9:
        return "jun_sep"
    if city == "phoenix" and month in (4, 5):
        return "phoenix_apr_may"
    if city in {"los_angeles", "sacramento"} and month == 10:
        return "california_october"
    return None


def _average_tie(reference: pd.Series, values: pd.Series) -> np.ndarray:
    ref = pd.to_numeric(reference, errors="coerce").dropna().to_numpy(float)
    target = pd.to_numeric(values, errors="coerce").to_numpy(float)
    if not len(ref):
        raise ValueError("Empty clean-room precipitation reference")
    result = np.full(target.shape, np.nan)
    finite = np.isfinite(target)
    if len(ref) == 1:
        result[finite] = 0.5
        return result
    ordered = np.sort(ref)
    unique = np.unique(ordered)
    ranks = np.asarray(
        [
            (
                (np.searchsorted(ordered, value, "left") + 1)
                + np.searchsorted(ordered, value, "right")
            )
            / 2.0
            for value in unique
        ],
        dtype=float,
    )
    ranks = (ranks - 1.0) / (len(ordered) - 1.0)
    result[finite] = np.interp(target[finite], unique, ranks, left=0.0, right=1.0)
    return result


def _daily_with_prior_precipitation(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="raise")
    work["year"] = work["date"].dt.year
    rows = []
    for (_, _), group in work.groupby(["city", "year"], sort=True):
        group = group.sort_values("date").copy()
        group["antecedent_precipitation_30d_mm"] = (
            pd.to_numeric(group["pr_mm"], errors="raise")
            .shift(1)
            .rolling(30, min_periods=30)
            .sum()
        )
        rows.append(group)
    return pd.concat(rows, ignore_index=True)


def _equation_of_time_minutes(times: pd.DatetimeIndex) -> np.ndarray:
    hour = times.hour + times.minute / 60 + times.second / 3600
    days = np.where(times.is_leap_year, 366.0, 365.0)
    gamma = 2 * np.pi / days * (times.dayofyear - 1 + (hour - 12) / 24)
    return 229.18 * (
        0.000075 + 0.001868 * np.cos(gamma) - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2 * gamma) - 0.040849 * np.sin(2 * gamma)
    )


def _local_solar_dates(acquisition: pd.Series, longitude: pd.Series) -> pd.Series:
    times = pd.DatetimeIndex(pd.to_datetime(acquisition, utc=True, errors="raise", format="mixed"))
    correction = pd.to_timedelta(
        4 * pd.to_numeric(longitude, errors="raise").to_numpy(float)
        + _equation_of_time_minutes(times),
        unit="m",
    )
    return pd.Series((times + correction).date, index=acquisition.index)


def _derive_new_unavailable_values(
    unavailable: pd.DataFrame,
    longitudes: dict[str, float],
    hourly: pd.DataFrame,
    daily_input: pd.DataFrame,
) -> pd.DataFrame:
    unavailable = unavailable.copy()
    unavailable["acquisition_utc"] = pd.to_datetime(
        unavailable["acquisition_utc"], utc=True, errors="raise", format="mixed"
    )
    unavailable["local_solar_date"] = _local_solar_dates(
        unavailable["acquisition_utc"], unavailable["city"].map(longitudes)
    )

    hourly = hourly.copy()
    hourly["timestamp_utc"] = pd.to_datetime(hourly["timestamp_utc"], utc=True, errors="raise", format="mixed")
    for target, source_column in (
        ("vpd_kpa_at_acquisition", "vpd_kpa"),
        ("air_temperature_k_at_acquisition", "t2m_k"),
        ("wind_speed_m_s_at_acquisition", "wind_speed_m_s"),
    ):
        unavailable[target] = np.nan
        for city, indices in unavailable.groupby("city").indices.items():
            source = hourly.loc[hourly["city"].eq(city)].sort_values("timestamp_utc")
            unavailable.iloc[indices, unavailable.columns.get_loc(target)] = np.interp(
                unavailable.iloc[indices]["acquisition_utc"].astype("int64").to_numpy(float),
                source["timestamp_utc"].astype("int64").to_numpy(float),
                pd.to_numeric(source[source_column], errors="raise").to_numpy(float),
                left=np.nan,
                right=np.nan,
            )

    daily = _daily_with_prior_precipitation(daily_input)
    daily["window_id"] = [
        _window(str(city), int(month))
        for city, month in zip(daily["city"], daily["date"].dt.month, strict=True)
    ]
    daily = daily.loc[daily["window_id"].notna()].copy()
    daily["local_solar_date"] = daily["date"].dt.date
    unavailable = unavailable.merge(
        daily[["city", "window_id", "local_solar_date", "antecedent_precipitation_30d_mm"]]
        .drop_duplicates(["city", "window_id", "local_solar_date"]),
        on=["city", "window_id", "local_solar_date"],
        how="left",
        validate="many_to_one",
    )
    unavailable["demand_percentile"] = np.nan
    unavailable["antecedent_precipitation_30d_wetness_percentile"] = np.nan
    for (city, window), indices in unavailable.groupby(["city", "window_id"]).indices.items():
        reference = daily.loc[daily["city"].eq(city) & daily["window_id"].eq(window)]
        unavailable.iloc[indices, unavailable.columns.get_loc("demand_percentile")] = _average_tie(
            reference["vpd_kpa"], unavailable.iloc[indices]["vpd_kpa_at_acquisition"]
        )
        unavailable.iloc[
            indices, unavailable.columns.get_loc("antecedent_precipitation_30d_wetness_percentile")
        ] = _average_tie(
            reference["antecedent_precipitation_30d_mm"],
            unavailable.iloc[indices]["antecedent_precipitation_30d_mm"],
        )
    demand = unavailable["demand_percentile"]
    wetness = unavailable["antecedent_precipitation_30d_wetness_percentile"]
    unavailable["demand_level"] = np.select(
        [demand.lt(1 / 3), demand.ge(2 / 3)], ["low", "high"], default="middle"
    )
    unavailable["wetness_level"] = np.select(
        [wetness.lt(1 / 3), wetness.ge(2 / 3)], ["dry", "wet"], default="middle"
    )
    unavailable["physical_pass_id"] = [
        f"{city}|orbit_{int(orbit):05d}"
        for city, orbit in unavailable[["city", "orbit"]].itertuples(index=False, name=None)
    ]
    unavailable["pass_recheck_classification"] = "RESOLVED_UNAVAILABLE"
    return unavailable


def _validate_hrrr_manifest_binding(
    record: dict[str, Any],
    checkpoint_record: dict[str, Any],
    shard_frame: pd.DataFrame,
    domains_binding: dict[str, str],
    *,
    shard_sha256: str,
    shard_size_bytes: int,
) -> None:
    item_id = str(record["item_id"])
    cities = sorted(filter(None, str(record["cities"]).split("|")))
    try:
        geometry_binding = json.loads(record["analysis_geometry_sha256_by_city"])
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError(f"HRRR manifest geometry binding is invalid: {item_id}") from None
    expected_geometry = {city: domains_binding[city] for city in cities}
    timestamp = pd.Timestamp(record["analysis_utc"])
    timestamp = timestamp.tz_convert("UTC") if timestamp.tzinfo else timestamp.tz_localize("UTC")
    expected_request = {
        "item_id": item_id,
        "analysis_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cities": "|".join(cities),
        "n_target_passes": int(record["n_target_passes"]),
        "model": str(record["model"]),
        "product": str(record["product"]),
        "forecast_hour": int(record["forecast_hour"]),
        "temperature_dewpoint_variable_search": TEMPERATURE_SEARCH,
        "wind_variable_search": WIND_SEARCH,
        "source": HRRR_SOURCE,
        "object_key": str(record["object_key"]),
        "product_resolution": str(record["product_resolution"]),
        "weather_algorithm_version": WEATHER_ALGORITHM_VERSION,
        "analysis_geometry_sha256_by_city": expected_geometry,
        "analysis_geometry_set_sha256": _canonical_sha(expected_geometry),
    }
    if (
        str(record.get("weather_algorithm_version")) != WEATHER_ALGORITHM_VERSION
        or geometry_binding != expected_geometry
        or str(record.get("analysis_geometry_set_sha256")) != _canonical_sha(expected_geometry)
        or checkpoint_record.get("status") != "complete"
        or checkpoint_record.get("request_binding") != expected_request
        or checkpoint_record.get("request_binding_sha256") != _canonical_sha(expected_request)
        or checkpoint_record.get("sha256") != shard_sha256
        or int(checkpoint_record.get("size_bytes", -1)) != int(shard_size_bytes)
        or checkpoint_record.get("weather_algorithm_version") != WEATHER_ALGORITHM_VERSION
        or checkpoint_record.get("analysis_geometry_sha256_by_city") != expected_geometry
        or checkpoint_record.get("analysis_geometry_set_sha256") != _canonical_sha(expected_geometry)
        or not shard_frame["weather_algorithm_version"].astype(str).eq(
            WEATHER_ALGORITHM_VERSION
        ).all()
        or any(
            not group["analysis_geometry_sha256"].astype(str).eq(
                expected_geometry[city]
            ).all()
            for city, group in shard_frame.groupby("city", sort=False)
        )
    ):
        raise ValueError(f"HRRR manifest/checkpoint/shard binding failed: {item_id}")


def _recompute_new_unavailable() -> tuple[pd.DataFrame, dict[str, Any]]:
    status = pd.read_csv(NEW_ARCHIVE_STATUS)
    if len(status) != 300 or status.duplicated(["city", "orbit"]).any():
        raise ValueError("Clean-room new archive status is not the sealed 300-pass census")
    if status["archive_status"].astype(str).eq("UNRESOLVED_ERROR").any():
        raise ValueError("Clean-room new archive status contains UNRESOLVED_ERROR")
    unavailable = status.loc[status["archive_status"].astype(str).eq("RESOLVED_UNAVAILABLE")].copy()
    if unavailable.empty or unavailable.duplicated(["city", "orbit"]).any():
        raise ValueError("Clean-room new unavailable census is empty or duplicated")
    domains = json.loads(DOMAINS.read_text(encoding="utf-8"))
    longitudes = {
        str(feature["properties"]["city"]): float(feature["properties"]["CENTLON"])
        for feature in domains["features"]
    }
    manifest = pd.read_csv(HRRR_MANIFEST)
    hourly = pd.read_csv(HRRR_SUMMARY)
    checkpoint_payload = json.loads(HRRR_CHECKPOINT.read_text(encoding="utf-8"))
    checkpoint = checkpoint_payload.get("items", checkpoint_payload)
    if not isinstance(checkpoint, dict) or not checkpoint:
        raise ValueError("Clean-room HRRR checkpoint envelope is empty or malformed")
    provenance = json.loads(DOMAINS_PROVENANCE.read_text(encoding="utf-8"))
    domains_binding = {
        str(record["city"]): str(record["analysis_geometry_sha256"])
        for record in provenance["records"]
    }
    source_cities = {str(feature["properties"]["city"]) for feature in domains["features"]}
    if (
        not source_cities.issubset(domains_binding)
        or not all(
            len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest)
            for digest in domains_binding.values()
        )
    ):
        raise ValueError("Domain provenance lacks sealed repaired-analysis hashes")
    source_hashes = {}
    shard_frames = []
    for record in manifest.to_dict("records"):
        item_id = str(record["item_id"])
        shard = HRRR_SHARDS / f"{item_id}.csv.gz"
        evidence = checkpoint.get(item_id, {})
        if (
            not shard.is_file()
            or evidence.get("status") != "complete"
            or evidence.get("sha256") != _sha(shard)
            or int(evidence.get("size_bytes", -1)) != shard.stat().st_size
        ):
            raise ValueError(f"Clean-room HRRR source evidence binding failed: {item_id}")
        source_hashes[str(shard.relative_to(ROOT))] = _sha(shard)
        shard_frame = pd.read_csv(shard)
        _validate_hrrr_manifest_binding(
            record,
            evidence,
            shard_frame,
            domains_binding,
            shard_sha256=_sha(shard),
            shard_size_bytes=shard.stat().st_size,
        )
        shard_frames.append(shard_frame)
    raw_cells = pd.concat(shard_frames, ignore_index=True)
    recomputed_hourly = (
        raw_cells.groupby(["city", "timestamp_utc"], sort=True, observed=True)
        .agg(
            t2m_k=("t2m_k", "mean"),
            d2m_k=("d2m_k", "mean"),
            vpd_kpa=("vpd_kpa", "mean"),
            wind_speed_m_s=("wind_speed_m_s", "mean"),
        )
        .reset_index()
    )
    hourly_compare = recomputed_hourly.merge(
        hourly[["city", "timestamp_utc", "t2m_k", "d2m_k", "vpd_kpa", "wind_speed_m_s"]],
        on=["city", "timestamp_utc"], suffixes=("_clean", "_summary"), validate="one_to_one",
    )
    if len(hourly_compare) != len(hourly) or any(
        not np.allclose(
            hourly_compare[f"{column}_clean"], hourly_compare[f"{column}_summary"],
            rtol=0, atol=1e-10,
        )
        for column in ("t2m_k", "d2m_k", "vpd_kpa", "wind_speed_m_s")
    ):
        raise ValueError("Clean-room HRRR hourly summary values do not reproduce from bound shards")
    hourly["timestamp_utc"] = pd.to_datetime(
        hourly["timestamp_utc"], utc=True, errors="raise", format="mixed"
    )
    expected_hour_city = {
        (
            city,
            pd.Timestamp(record["analysis_utc"]).tz_convert("UTC")
            if pd.Timestamp(record["analysis_utc"]).tzinfo
            else pd.Timestamp(record["analysis_utc"]).tz_localize("UTC"),
        )
        for record in manifest.to_dict("records")
        for city in str(record["cities"]).split("|")
    }
    observed_hour_city = set(hourly[["city", "timestamp_utc"]].itertuples(index=False, name=None))
    if observed_hour_city != expected_hour_city:
        raise ValueError("Clean-room HRRR hourly summary does not equal manifest hour-city census")
    result = _derive_new_unavailable_values(
        unavailable, longitudes, hourly, pd.read_csv(DAILY)
    )
    return result, {
        "hrrr_manifest_sha256": _sha(HRRR_MANIFEST),
        "hrrr_summary_sha256": _sha(HRRR_SUMMARY),
        "hrrr_checkpoint_sha256": _sha(HRRR_CHECKPOINT),
        "hrrr_shards": source_hashes,
    }


def _validate_geometry_pass_evidence(geometry: pd.DataFrame) -> dict[str, Any]:
    checkpoint_payload = json.loads(GEOMETRY_CHECKPOINT.read_text(encoding="utf-8"))
    checkpoint = checkpoint_payload.get("items", checkpoint_payload)
    augmentation = json.loads(AUGMENTATION_SUMMARY.read_text(encoding="utf-8"))
    inventory = augmentation.get("geometry_reconstruction_inventory", {})
    preflight = json.loads(GEOMETRY_RECONSTRUCTION_PREFLIGHT.read_text(encoding="utf-8"))
    inventory_rows = {
        (str(row.get("city")), int(row.get("orbit", -1))): row
        for row in inventory.get("passes", [])
    }
    old_links = pd.read_csv(EXISTING_GEOMETRY_LINKS)
    old_links = old_links.loc[
        old_links["city"].astype(str).isin({"atlanta", "minneapolis_st_paul"})
    ].copy()
    if old_links.duplicated(["city", "orbit", "scene"]).any():
        raise ValueError("Clean-room frozen D0047 scene links are duplicated")
    old_manifest = pd.read_csv(EXISTING_GEOMETRY_SCENE_MANIFEST)
    if old_manifest.duplicated(["orbit", "scene"]).any():
        raise ValueError("Clean-room frozen D0047 scene manifest is duplicated")
    if (
        inventory.get("format_version") != "d0069-mapped-domain-cells-v1"
        or inventory.get("storage_guard_pass") is not True
        or int(inventory.get("total_bytes", -1)) > int(inventory.get("maximum_bytes", -2))
        or inventory.get("raw_mapped_per_pixel_reconstruction_supported") is not True
        or int(inventory.get("pass_count", -1)) != len(inventory.get("passes", []))
    ):
        raise ValueError("Geometry reconstruction inventory is absent or unsafe")
    accessible = geometry.loc[~geometry["geometry_azimuth_status"].astype(str).eq("RESOLVED_UNAVAILABLE")]
    expected_raw = int(
        pd.to_numeric(accessible["n_domain_pixels"], errors="raise").sum() * 16
    )
    expected_overhead = len(accessible) * 1024**2
    credited = [str(value) for value in preflight.get("credited_completed_item_ids", [])]
    sealed_digests = preflight.get("credited_completed_validation_sha256_by_item_id", {})
    accessible_by_id = {
        f"{row.city}:{int(row.orbit):05d}": row
        for row in accessible.itertuples(index=False)
    }
    if (
        len(credited) != len(set(credited))
        or set(credited) != set(sealed_digests)
        or not set(credited).issubset(accessible_by_id)
    ):
        raise ValueError("Clean-room geometry resume credited census is invalid")
    completed_raw = int(
        sum(int(accessible_by_id[item_id].n_domain_pixels) * 16 for item_id in credited)
    )
    completed_overhead = len(credited) * 1024**2
    remaining_raw = expected_raw - completed_raw
    remaining_overhead = expected_overhead - completed_overhead
    if (
        preflight.get("status") != "PASS"
        or preflight.get("format_version") != "d0069-mapped-domain-cells-v1"
        or int(preflight.get("candidate_passes", -1)) != len(accessible)
        or int(preflight.get("raw_array_worst_case_bytes", -1)) != expected_raw
        or int(preflight.get("container_overhead_bytes", -1)) != expected_overhead
        or int(preflight.get("conservative_new_data_bytes", -1)) != expected_raw + expected_overhead
        or int(preflight.get("completed_passes", -1)) != len(credited)
        or int(preflight.get("completed_raw_array_worst_case_bytes", -1)) != completed_raw
        or int(preflight.get("completed_container_overhead_bytes", -1)) != completed_overhead
        or int(preflight.get("completed_conservative_bytes", -1))
        != completed_raw + completed_overhead
        or int(preflight.get("remaining_passes", -1)) != len(accessible) - len(credited)
        or int(preflight.get("remaining_raw_array_worst_case_bytes", -1)) != remaining_raw
        or int(preflight.get("remaining_container_overhead_bytes", -1)) != remaining_overhead
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
        raise ValueError("Geometry reconstruction storage preflight does not reproduce")
    for item_id in credited:
        if _cleanroom_resume_validation_digest(
            item_id, checkpoint.get(item_id, {})
        ) != sealed_digests[item_id]:
            raise ValueError(f"Clean-room geometry resume digest changed: {item_id}")
    governed = (
        "city", "window_id", "orbit", "year", "n_domain_pixels", "n_view_valid_pixels",
        "l1b_geometry_coverage_fraction", "l1b_view_zenith_abs_p95_deg",
        "view_azimuth_circular_mean_deg", "solar_azimuth_circular_mean_deg",
        "relative_azimuth_median_deg", "geometry_azimuth_complete", "geometry_azimuth_status",
        "source_geometry_evidence_sha256",
    )
    checked = 0
    reconstructable = True
    for row in accessible.to_dict("records"):
        item_id = f"{row['city']}:{int(row['orbit']):05d}"
        inventory_row = inventory_rows.get((str(row["city"]), int(row["orbit"])))
        if not isinstance(inventory_row, dict):
            raise ValueError(f"Missing geometry reconstruction inventory row: {item_id}")
        reconstruction_path = ROOT / str(inventory_row.get("path", ""))
        if (
            not reconstruction_path.is_file()
            or inventory_row.get("sha256") != _sha(reconstruction_path)
            or int(inventory_row.get("size_bytes", -1)) != reconstruction_path.stat().st_size
            or inventory_row.get("sha256") != row.get("geometry_reconstruction_artifact_sha256")
        ):
            raise ValueError(f"Geometry reconstruction artifact binding failed: {item_id}")
        source_assets = inventory_row.get("source_assets", [])
        if not source_assets:
            raise ValueError(f"Geometry source-asset inventory is empty: {item_id}")
        for source in source_assets:
            dmrpp = ROOT / str(source.get("dmrpp_path", ""))
            locator = ROOT / str(source.get("locator_path", ""))
            if (
                not dmrpp.is_file()
                or not locator.is_file()
                or source.get("dmrpp_sha256") != _sha(dmrpp)
                or source.get("locator_sha256") != _sha(locator)
            ):
                raise ValueError(f"Geometry local DMRPP/locator bytes failed binding: {item_id}")
        selected_chunks = inventory_row.get("selected_compressed_chunk_hash_inventory", [])
        if int(inventory_row.get("selected_compressed_chunk_count", -1)) != len(selected_chunks):
            raise ValueError(f"Geometry selected-chunk inventory count failed: {item_id}")
        if any(
            not item.get("chunk_key")
            or len(str(item.get("sha256", ""))) != 64
            or any(character not in "0123456789abcdef" for character in str(item.get("sha256", "")))
            for item in selected_chunks
        ):
            raise ValueError(f"Geometry selected-chunk inventory is malformed: {item_id}")
        with np.load(reconstruction_path, allow_pickle=False) as mapped:
            required_arrays = {
                "format_version", "city", "window_id", "orbit", "target_grid_sha256",
                "tile_names", "tile_offsets", "tile_sizes", "n_domain_pixels",
                "valid_target_index", "view_zenith_abs_deg", "view_azimuth_deg",
                "solar_azimuth_deg",
            }
            if required_arrays.difference(mapped.files):
                raise ValueError(f"Geometry reconstruction arrays incomplete: {item_id}")
            indices = mapped["valid_target_index"]
            view = mapped["view_zenith_abs_deg"]
            view_az = mapped["view_azimuth_deg"]
            solar_az = mapped["solar_azimuth_deg"]
            n_domain = int(mapped["n_domain_pixels"])
            mapped_grid_sha256 = str(mapped["target_grid_sha256"])
            if (
                str(mapped["format_version"]) != "d0069-mapped-domain-cells-v1"
                or str(mapped["city"]) != str(row["city"])
                or int(mapped["orbit"]) != int(row["orbit"])
                or n_domain != int(row["n_domain_pixels"])
                or not (len(indices) == len(view) == len(view_az) == len(solar_az))
                or len(indices) != int(row["n_view_valid_pixels"])
                or (len(indices) and (indices.min() < 0 or indices.max() >= n_domain))
                or len(np.unique(indices)) != len(indices)
            ):
                raise ValueError(f"Geometry reconstruction census failed: {item_id}")
            if len(view):
                reconstructed = _replay_mapped_geometry_summary(
                    view, view_az, solar_az, n_domain
                )
                if (
                    str(row["geometry_azimuth_status"])
                    != reconstructed["geometry_azimuth_status"]
                    or bool(str(row["geometry_azimuth_complete"]).casefold() == "true")
                    != reconstructed["geometry_azimuth_complete"]
                ):
                    raise ValueError(f"Geometry azimuth completeness/status differs: {item_id}")
                for column, value in reconstructed.items():
                    if column in {"geometry_azimuth_complete", "geometry_azimuth_status"}:
                        continue
                    if not np.isclose(
                        float(row[column]),
                        value,
                        rtol=0,
                        atol=RECONSTRUCTION_FLOAT32_ATOL,
                    ):
                        raise ValueError(f"Geometry reconstruction summary differs for {column}: {item_id}")
        record = checkpoint.get(item_id)
        if not isinstance(record, dict):
            raise ValueError(f"Missing geometry pass checkpoint: {item_id}")
        if record.get("reuse_rule") == "checksum-verified D0047 full-resolution zero-mapped scene proof":
            source_path = Path(str(record.get("source_path", "")))
            if (
                not source_path.is_file()
                or record.get("source_sha256") != _sha(source_path)
                or not isinstance(record.get("summary"), dict)
            ):
                raise ValueError(f"Reused geometry proof binding failed: {item_id}")
            summary = record["summary"]
            for column in governed:
                if column not in summary or column not in row:
                    raise ValueError(f"Reused geometry summary missing {column}: {item_id}")
                left, right = summary[column], row[column]
                if pd.isna(left) and pd.isna(right):
                    continue
                if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                    if not np.isclose(float(left), float(right), rtol=0, atol=1e-10):
                        raise ValueError(f"Reused geometry summary differs for {column}: {item_id}")
                elif str(left) != str(right):
                    raise ValueError(f"Reused geometry summary differs for {column}: {item_id}")
            source_document = json.loads(source_path.read_text(encoding="utf-8"))
            if str(source_document.get("binding", {}).get("target_grid_sha256")) != mapped_grid_sha256:
                raise ValueError(f"Reused mapped grid/pass binding differs: {item_id}")
            if str(row["geometry_azimuth_status"]) != "RESOLVED_VERIFIED_ZERO_MAPPED_CELLS":
                raise ValueError(f"Reused zero-mapped geometry status is not truthful: {item_id}")
            _cleanroom_validate_zero_mapped_document(source_document, item_id=item_id)
            expected_link_rows = old_links.loc[
                    old_links["city"].astype(str).eq(str(row["city"]))
                    & pd.to_numeric(old_links["orbit"], errors="raise").eq(int(row["orbit"])),
                    ["orbit", "scene"],
                ].copy()
            expected_join = expected_link_rows.merge(
                old_manifest[["orbit", "scene", "granule_id"]],
                on=["orbit", "scene"],
                how="left",
                validate="one_to_one",
            )
            expected_scenes = [
                (int(orbit), int(scene), str(granule))
                for orbit, scene, granule in expected_join[
                    ["orbit", "scene", "granule_id"]
                ].itertuples(index=False, name=None)
            ]
            _cleanroom_compare_zero_scene_census(
                source_document, expected_scenes, item_id=item_id
            )
            checked += 1
            continue
        path = Path(str(record.get("evidence_path", "")))
        if (
            record.get("status") != "complete"
            or not path.is_file()
            or record.get("evidence_sha256") != _sha(path)
        ):
            raise ValueError(f"Geometry pass evidence checksum failed: {item_id}")
        document = json.loads(path.read_text(encoding="utf-8"))
        binding = document.get("binding")
        summary = document.get("summary")
        scenes = document.get("scene_evidence")
        if not isinstance(summary, dict) or not isinstance(scenes, list) or not scenes:
            raise ValueError(f"Geometry pass evidence is structurally incomplete: {item_id}")
        if isinstance(binding, dict):
            canonical = hashlib.sha256(
                json.dumps(binding, sort_keys=True, separators=(",", ":"), default=str).encode()
            ).hexdigest()
            if document.get("binding_sha256") != canonical or record.get("binding_sha256") != canonical:
                raise ValueError(f"Geometry pass binding digest failed: {item_id}")
            if str(binding.get("target_grid_sha256")) != mapped_grid_sha256:
                raise ValueError(f"Geometry mapped grid/pass binding differs: {item_id}")
            for source in binding.get("scene_bindings", []):
                if not all(
                    isinstance(source.get(key), str) and len(source.get(key)) == 64
                    for key in ("cmr_record_sha256", "dmrpp_sha256", "locator_sha256")
                ):
                    raise ValueError(f"Geometry scene source hashes incomplete: {item_id}")
        else:
            # Reused D0047 zero-mapped documents use a nested reuse binding.
            if str(row["geometry_azimuth_status"]) != "RESOLVED_VERIFIED_ZERO_MAPPED_CELLS":
                raise ValueError(f"Geometry pass lacks canonical binding: {item_id}")
        for scene in scenes:
            chunk_digest = str(scene.get("selected_compressed_chunks_sha256", ""))
            if str(row["geometry_azimuth_status"]) != "RESOLVED_VERIFIED_ZERO_MAPPED_CELLS" and len(chunk_digest) != 64:
                raise ValueError(f"Geometry selected-chunk digest incomplete: {item_id}")
        for column in governed:
            if column not in summary or column not in row:
                raise ValueError(f"Geometry governed summary missing {column}: {item_id}")
            left, right = summary[column], row[column]
            if pd.isna(left) and pd.isna(right):
                continue
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                if not np.isclose(float(left), float(right), rtol=0, atol=1e-10):
                    raise ValueError(f"Geometry governed summary differs for {column}: {item_id}")
            elif str(left) != str(right):
                raise ValueError(f"Geometry governed summary differs for {column}: {item_id}")
        reconstructable &= bool(
            isinstance(binding, dict)
            and binding.get("scene_bindings")
            and all(
                len(str(scene.get("selected_compressed_chunks_sha256", ""))) == 64
                for scene in scenes
            )
        )
        checked += 1
    return {
        "pass_evidence_rows_verified": checked,
        "raw_per_pixel_reconstruction_deferred_to_gate6": True,
        "gate6_raw_evidence_sufficient": bool(
            reconstructable and len(inventory_rows) == len(accessible)
        ),
        "storage_preflight_sha256": _sha(GEOMETRY_RECONSTRUCTION_PREFLIGHT),
    }


def _relabel_archive() -> pd.DataFrame:
    archive = pd.read_csv(ARCHIVE, low_memory=False)
    daily = _daily_with_prior_precipitation(pd.read_csv(DAILY))
    if len(archive) != 31 or archive["observation_id"].duplicated().any():
        raise ValueError("Clean-room archive census is not exactly 31 unique passes")
    if not archive["pass_recheck_classification"].eq("RESOLVED_UNAVAILABLE").all():
        raise ValueError("Clean-room archive audit contains a non-resolved pass")
    daily["window_id"] = [
        _window(str(city), int(month))
        for city, month in zip(daily["city"], daily["date"].dt.month, strict=True)
    ]
    daily = daily.loc[daily["window_id"].notna()].copy()
    daily["local_solar_date"] = daily["date"].dt.date
    archive["window_id"] = [
        _window(str(city), int(month))
        for city, month in archive[["city", "month"]].itertuples(index=False, name=None)
    ]
    if archive["window_id"].isna().any():
        raise ValueError("Archive pass outside frozen window")
    archive["local_solar_date"] = pd.to_datetime(
        archive["proxy_local_solar_date"], errors="raise"
    ).dt.date
    lookup = daily[
        ["city", "window_id", "local_solar_date", "antecedent_precipitation_30d_mm"]
    ].drop_duplicates(["city", "window_id", "local_solar_date"])
    archive = archive.merge(
        lookup,
        on=["city", "window_id", "local_solar_date"],
        how="left",
        validate="many_to_one",
    )
    archive["wetness_percentile"] = np.nan
    for (city, window), indices in archive.groupby(["city", "window_id"]).indices.items():
        reference = daily.loc[
            daily["city"].eq(city) & daily["window_id"].eq(window),
            "antecedent_precipitation_30d_mm",
        ]
        archive.iloc[indices, archive.columns.get_loc("wetness_percentile")] = _average_tie(
            reference, archive.iloc[indices]["antecedent_precipitation_30d_mm"]
        )
    wetness = archive["wetness_percentile"]
    archive["wetness_level"] = np.select(
        [wetness.lt(1 / 3), wetness.ge(2 / 3)], ["dry", "wet"], default="middle"
    )
    demand = pd.to_numeric(archive["proxy_demand_percentile"], errors="coerce")
    archive["demand_level"] = np.select(
        [demand.ge(2 / 3), demand.lt(1 / 3)], ["high", "low"], default="middle"
    )
    archive["physical_pass_id"] = archive["observation_id"].astype(str)
    archive["bound_scope_included"] = [
        (str(city), str(window)) in PRIMARY
        for city, window in archive[["city", "window_id"]].itertuples(index=False, name=None)
    ]
    return archive


def _joined_detail() -> tuple[pd.DataFrame, dict[int, set[str]]]:
    geometry = pd.read_csv(GEOMETRY, low_memory=False)
    cloud = pd.read_csv(CLOUD, low_memory=False)
    weather = pd.read_csv(WEATHER, low_memory=False)
    if len(geometry) != 762 or geometry.duplicated(["city", "orbit"]).any():
        raise ValueError("Clean-room geometry ledger count/dedup failed")
    membership = set(
        geometry[["city", "window_id"]].drop_duplicates().itertuples(index=False, name=None)
    )
    if membership != PRIMARY:
        raise ValueError("Clean-room geometry membership differs from D0069")
    for frame, label in ((cloud, "cloud"), (weather, "weather")):
        if frame.duplicated(["city", "orbit"]).any():
            raise ValueError(f"Clean-room {label} physical-pass dedup failed")
    complete = _strict_true(geometry["geometry_azimuth_complete"])
    qualified = geometry.loc[
        complete
        & pd.to_numeric(geometry["l1b_geometry_coverage_fraction"], errors="coerce").ge(0.95)
        & pd.to_numeric(geometry["l1b_view_zenith_abs_p95_deg"], errors="coerce").le(25)
    ].copy()
    expected = set(qualified[["city", "orbit"]].itertuples(index=False, name=None))
    if set(cloud[["city", "orbit"]].itertuples(index=False, name=None)) != expected:
        raise ValueError("Clean-room cloud join census mismatch")
    if set(weather[["city", "orbit"]].itertuples(index=False, name=None)) != expected:
        raise ValueError("Clean-room weather join census mismatch")
    if not _strict_true(cloud["cloud_complete"]).all() or not _strict_true(
        weather["exact_weather_complete"]
    ).all():
        raise ValueError("Clean-room cloud/weather completeness failed")
    joined = qualified.merge(
        cloud[["city", "window_id", "orbit", "clear_domain_fraction"]],
        on=["city", "window_id", "orbit"],
        validate="one_to_one",
    ).merge(
        weather[
            [
                "city", "window_id", "orbit", "time_stratum", "demand_level",
                "wetness_level", "vpd_kpa_at_acquisition",
                "antecedent_precipitation_30d_mm", "air_temperature_k_at_acquisition",
                "wind_speed_m_s_at_acquisition", "day_of_window",
            ]
        ],
        on=["city", "window_id", "orbit"],
        validate="one_to_one",
    )
    joined["physical_pass_id"] = [
        f"{city}|orbit_{int(orbit):05d}"
        for city, orbit in joined[["city", "orbit"]].itertuples(index=False, name=None)
    ]
    daily = _daily_with_prior_precipitation(pd.read_csv(DAILY))
    daily["window_id"] = [
        _window(str(city), int(month))
        for city, month in zip(daily["city"], daily["date"].dt.month, strict=True)
    ]
    daily = daily.loc[daily["window_id"].notna()].copy()
    for (city, window), indices in joined.groupby(["city", "window_id"]).indices.items():
        reference = daily.loc[daily["city"].eq(city) & daily["window_id"].eq(window)]
        demand_percentile = _average_tie(
            reference["vpd_kpa"], joined.iloc[indices]["vpd_kpa_at_acquisition"]
        )
        wetness_percentile = _average_tie(
            reference["antecedent_precipitation_30d_mm"],
            joined.iloc[indices]["antecedent_precipitation_30d_mm"],
        )
        expected_demand = np.select(
            [demand_percentile >= 2 / 3, demand_percentile < 1 / 3],
            ["high", "low"],
            default="middle",
        )
        expected_wetness = np.select(
            [wetness_percentile >= 2 / 3, wetness_percentile < 1 / 3],
            ["wet", "dry"],
            default="middle",
        )
        if not np.array_equal(
            expected_demand, joined.iloc[indices]["demand_level"].astype(str)
        ):
            raise ValueError(f"Clean-room demand label mismatch for {city}/{window}")
        if not np.array_equal(
            expected_wetness, joined.iloc[indices]["wetness_level"].astype(str)
        ):
            raise ValueError(f"Clean-room wetness label mismatch for {city}/{window}")
    ids = {
        threshold: set(
            joined.loc[
                pd.to_numeric(joined["l1b_view_zenith_abs_p95_deg"], errors="coerce").le(
                    threshold
                ),
                "physical_pass_id",
            ]
        )
        for threshold in THRESHOLDS
    }
    prior: set[str] = set()
    for threshold in THRESHOLDS:
        if not prior.issubset(ids[threshold]):
            raise ValueError("Clean-room threshold nesting failed")
        prior = ids[threshold]
    return joined, ids


def _overlap(left: pd.Series, right: pd.Series) -> float:
    a = pd.to_numeric(left, errors="coerce").dropna()
    b = pd.to_numeric(right, errors="coerce").dropna()
    if a.empty or b.empty:
        return math.nan
    return float(min(a.max(), b.max()) - max(a.min(), b.min()))


def _histogram_overlap(left: pd.Series, right: pd.Series) -> float:
    a = pd.to_numeric(left, errors="coerce").dropna().to_numpy(float)
    b = pd.to_numeric(right, errors="coerce").dropna().to_numpy(float)
    if not len(a) or not len(b):
        return math.nan
    values = np.concatenate([a, b])
    low, high = float(values.min()), float(values.max())
    if low == high:
        edges = np.array([low - 0.5, high + 0.5])
    else:
        q1, q3 = np.quantile(values, [0.25, 0.75])
        width = 2.0 * float(q3 - q1) / np.cbrt(len(values))
        bins = int(math.ceil((high - low) / width)) if width > 0 else 10
        edges = np.linspace(low, high, min(20, max(5, bins)) + 1)
    ah = np.histogram(a, bins=edges)[0].astype(float)
    bh = np.histogram(b, bins=edges)[0].astype(float)
    return float(np.minimum(ah / ah.sum(), bh / bh.sum()).sum())


def _independent_pairwise(detail: pd.DataFrame) -> pd.DataFrame:
    variables = {
        "acquisition_vpd_histogram_overlap": "vpd_kpa_at_acquisition",
        "precipitation_30d_histogram_overlap": "antecedent_precipitation_30d_mm",
        "view_zenith_histogram_overlap": "l1b_view_zenith_abs_p95_deg",
        "relative_azimuth_histogram_overlap": "relative_azimuth_median_deg",
    }
    weather = {
        "acquisition_vpd_observed_range_overlap": "vpd_kpa_at_acquisition",
        "air_temperature_observed_range_overlap": "air_temperature_k_at_acquisition",
        "wind_speed_observed_range_overlap": "wind_speed_m_s_at_acquisition",
    }
    rows = []
    for threshold, threshold_group in detail.groupby("threshold_deg", sort=True):
        groups = list(threshold_group.groupby(["city", "window_id"], sort=True))
        for left_index, (left_key, left) in enumerate(groups):
            for right_key, right in groups[left_index + 1 :]:
                row = {
                    "threshold_deg": int(threshold),
                    "left_city_window": f"{left_key[0]}/{left_key[1]}",
                    "right_city_window": f"{right_key[0]}/{right_key[1]}",
                }
                row.update({name: _histogram_overlap(left[column], right[column]) for name, column in variables.items()})
                row.update({name: max(0.0, _overlap(left[column], right[column])) for name, column in weather.items()})
                rows.append(row)
    return pd.DataFrame(rows)


def _count_summary(frame: pd.DataFrame) -> dict[str, Any]:
    city_counts = frame.groupby("city").size()
    max_share = float(city_counts.max() / city_counts.sum()) if len(city_counts) else math.nan
    conclusions = {}
    for (city, window), group in frame.groupby(["city", "window_id"], sort=True):
        high = group.loc[group["demand_level"].eq("high")]
        conclusions[f"{city}/{window}"] = {
            "year": group["year"].nunique() >= 4,
            "am_pm": group["time_stratum"].eq("10-12").sum() >= 3
            and group["time_stratum"].eq("16-18").sum() >= 3,
            "wet_dry": high["wetness_level"].eq("wet").sum() >= 2
            and high["wetness_level"].eq("dry").sum() >= 2,
        }
    count_support = bool(conclusions and all(all(item.values()) for item in conclusions.values()))
    return {
        "four": frame["city"].nunique() >= 4,
        "share": bool(len(frame) and max_share <= 0.40),
        "support": count_support,
        "conclusions": conclusions,
    }


def _independent_archive_bounds(
    detail: pd.DataFrame, unavailable: pd.DataFrame
) -> dict[int, dict[str, Any]]:
    additions = unavailable.loc[_strict_true(unavailable["bound_scope_included"])].copy()
    rows: dict[int, dict[str, Any]] = {}
    for threshold in THRESHOLDS:
        lower = detail.loc[detail["threshold_deg"].eq(threshold)].copy()
        upper = pd.concat([lower, additions], ignore_index=True, sort=False)
        low = _count_summary(lower)
        high = _count_summary(upper)
        rows[threshold] = {
            "lower": low,
            "upper": high,
            "conclusions_invariant": bool(
                low["four"] == high["four"]
                and low["share"] == high["share"]
                and low["support"] == high["support"]
                and low["conclusions"] == high["conclusions"]
            ),
            "lower_eligible": low["four"] and low["share"] and low["support"],
            "upper_eligible": high["four"] and high["share"] and high["support"],
        }
    lower_first = next((t for t in THRESHOLDS if rows[t]["lower_eligible"]), None)
    upper_first = next((t for t in THRESHOLDS if rows[t]["upper_eligible"]), None)
    for threshold in THRESHOLDS:
        rows[threshold]["first_threshold_invariant"] = lower_first == upper_first
        rows[threshold]["archive_bounds_invariant"] = bool(
            rows[threshold]["conclusions_invariant"] and lower_first == upper_first
        )
    return rows


GOVERNANCE_RECORD_RELATIVE_PATHS = (
    "docs/v2/D0071_USER_DELEGATED_ITERATIVE_GATE_REVIEW.md",
    "docs/v2/D0072_G3_GEOMETRY_AND_RESUME_STORAGE_INCIDENT.md",
    "docs/v2/D0073_G4_G5_READINESS_2026_METADATA_EXPOSURE.md",
    "docs/v2/D0074_REPEAT_2026_METADATA_EXPOSURE.md",
    "docs/v2/D0075_G3_EXCLUSIVE_WRITER_CORRECTION.md",
    "docs/v2/D0076_FIRST_FOUR_ITEMS_SEQUENCE_CORRECTION.md",
    "docs/v2/D0077_G3_PAUSE_CHECKPOINT_COUNT_CORRECTION.md",
    "docs/v2/D0078_FIRST_FOUR_ITEMS_APPROVAL_AND_G3_RESUME.md",
    "docs/v2/D0079_G3_GENERATED_ZERO_MAP_PROOF_CORRECTION.md",
    "docs/v2/D0080_G3_VALIDATOR_INTEGRATION_CORRECTIONS.md",
    "docs/v2/D0081_G3_HRRR_CHECKPOINT_ENVELOPE_CORRECTION.md",
)


def _validate_governance_source_bindings(
    bindings: Mapping[str, Any],
    *,
    root: Path = ROOT,
    relative_paths: tuple[str, ...] = GOVERNANCE_RECORD_RELATIVE_PATHS,
) -> None:
    sources = bindings.get("sources", {})
    if not isinstance(sources, Mapping):
        raise ValueError("Packet source binding map is absent")
    missing = [name for name in relative_paths if name not in sources]
    mismatched = [
        name
        for name in relative_paths
        if name in sources
        and (
            not (root / name).is_file()
            or str(sources[name]) != _sha(root / name)
        )
    ]
    if missing or mismatched:
        raise ValueError(
            "Packet governance source bindings are incomplete or changed: "
            f"missing={missing}, mismatched={mismatched}"
        )


def verify() -> dict[str, Any]:
    governance_records = [ROOT / name for name in GOVERNANCE_RECORD_RELATIVE_PATHS]
    required = [
        GEOMETRY, CLOUD, WEATHER, ARCHIVE, ARCHIVE_SCENES, ARCHIVE_SUMMARY,
        NEW_ARCHIVE_STATUS, NEW_PASSES_SOURCE, NEW_METADATA_SOURCE, NEW_SCENE_MANIFEST,
        EXISTING_GEOMETRY_LINKS, EXISTING_GEOMETRY_SCENE_MANIFEST,
        NEW_UNAVAILABLE_LABELS, DAILY, DOMAINS, DOMAINS_PROVENANCE, HRRR_MANIFEST,
        HRRR_SUMMARY, HRRR_CHECKPOINT, HRRR_STORAGE_ESTIMATE, HRRR_STORAGE_PREFLIGHT,
        GEOMETRY_RECONSTRUCTION_PREFLIGHT, GEOMETRY_CHECKPOINT,
        AUGMENTATION_SUMMARY, PACKET / "source_bindings.json",
        PACKET / "threshold_pass_detail.csv", PACKET / "threshold_city_window_eligibility.csv",
        PACKET / "balance_diagnostics.csv", PACKET / "pairwise_balance_diagnostics.csv",
        PACKET / "archive_all_31_precipitation_relabel.csv",
        PACKET / "unified_unavailable_pass_ledger.csv",
        PACKET / "archive_bounds_four_primary_windows.csv", PACKET / "phenology_decisions.csv",
        PACKET / "selection.json", PACKET / "checks.json",
    ] + governance_records
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Clean-room verifier missing inputs: {missing}")

    immutable_mismatches = {
        str(path.relative_to(ROOT)): _sha(path)
        for path, expected in IMMUTABLE_ARCHIVE_HASHES.items()
        if _sha(path) != expected
    }
    if immutable_mismatches:
        raise ValueError(f"Immutable D0070 archive hash mismatch: {immutable_mismatches}")

    augmentation = json.loads(AUGMENTATION_SUMMARY.read_text(encoding="utf-8"))
    augmentation_mismatches = {
        name: _sha(ROOT / name) if (ROOT / name).is_file() else "MISSING"
        for name, expected in augmentation.get("artifacts", {}).items()
        if not (ROOT / name).is_file() or _sha(ROOT / name) != expected
    }
    if augmentation_mismatches:
        raise ValueError(f"Augmentation source/artifact binding mismatch: {augmentation_mismatches}")
    if (
        augmentation.get("temperature_or_lst_opened") is not False
        or augmentation.get("record_2026_opened") is not False
    ):
        raise ValueError("Augmentation summary violates historical nonthermal locks")
    new_status_name = str(NEW_ARCHIVE_STATUS.relative_to(ROOT))
    if augmentation.get("artifacts", {}).get(new_status_name) != _sha(NEW_ARCHIVE_STATUS):
        raise ValueError("Completed 300-row new archive-status artifact is not augmentation-bound")
    manifest_name = str(NEW_SCENE_MANIFEST.relative_to(ROOT))
    if augmentation.get("artifacts", {}).get(manifest_name) != _sha(NEW_SCENE_MANIFEST):
        raise ValueError("Completed 488-row scene manifest is not augmentation-bound")
    storage_estimate = pd.read_csv(HRRR_STORAGE_ESTIMATE)
    storage_preflight = json.loads(HRRR_STORAGE_PREFLIGHT.read_text(encoding="utf-8"))
    estimated_bytes = int(
        pd.to_numeric(storage_estimate["conservative_new_data_bytes"], errors="raise").sum()
    )
    if (
        storage_preflight.get("status") != "PASS"
        or storage_preflight.get("weather_algorithm_version") != WEATHER_ALGORITHM_VERSION
        or int(storage_preflight.get("conservative_new_data_bytes", -1)) != estimated_bytes
        or int(storage_preflight.get("required_free_bytes", -1))
        != estimated_bytes + int(storage_preflight.get("explicit_reserve_bytes", -2))
        or int(storage_preflight.get("observed_free_bytes", -1))
        < int(storage_preflight.get("required_free_bytes", 0))
        or storage_preflight.get("estimate_sha256") != _sha(HRRR_STORAGE_ESTIMATE)
    ):
        raise ValueError("HRRR storage estimate/preflight binding failed")

    bindings = json.loads((PACKET / "source_bindings.json").read_text(encoding="utf-8"))
    _validate_governance_source_bindings(bindings)
    mismatches = {
        name: {"expected": digest, "actual": _sha(ROOT / name) if (ROOT / name).is_file() else "MISSING"}
        for name, digest in bindings.get("sources", {}).items()
        if not (ROOT / name).is_file() or _sha(ROOT / name) != digest
    }
    if mismatches:
        raise ValueError(f"Source binding mismatch: {mismatches}")
    _, new_archive_provenance = _independent_new_archive_provenance()
    if bindings.get("new_archive_status_provenance") != new_archive_provenance:
        raise ValueError("Packet new archive provenance binding did not independently reproduce")

    joined, threshold_ids = _joined_detail()
    geometry_source = pd.read_csv(GEOMETRY)
    geometry_evidence = _validate_geometry_pass_evidence(geometry_source)
    unresolved_accessible = geometry_source.loc[
        geometry_source["geometry_azimuth_status"].astype(str).eq("AZIMUTH_INCOMPLETE")
    ]
    packet_detail = pd.read_csv(PACKET / "threshold_pass_detail.csv", low_memory=False)
    if packet_detail.duplicated(["threshold_deg", "physical_pass_id"]).any():
        raise ValueError("Packet threshold detail duplicates a physical pass")
    for threshold in THRESHOLDS:
        reported = set(
            packet_detail.loc[
                packet_detail["threshold_deg"].eq(threshold), "physical_pass_id"
            ].astype(str)
        )
        if reported != threshold_ids[threshold]:
            raise ValueError(f"Threshold {threshold} membership did not reproduce")
    source_detail = pd.concat(
        [
            joined.loc[
                pd.to_numeric(joined["l1b_view_zenith_abs_p95_deg"], errors="coerce").le(threshold)
            ].assign(threshold_deg=threshold)
            for threshold in THRESHOLDS
        ],
        ignore_index=True,
    )
    governed_numeric = (
        "l1b_geometry_coverage_fraction", "l1b_view_zenith_abs_p95_deg",
        "view_azimuth_circular_mean_deg", "solar_azimuth_circular_mean_deg",
        "relative_azimuth_median_deg", "clear_domain_fraction",
        "vpd_kpa_at_acquisition", "antecedent_precipitation_30d_mm",
        "air_temperature_k_at_acquisition", "wind_speed_m_s_at_acquisition", "day_of_window",
    )
    governed_text = ("city", "window_id", "time_stratum", "demand_level", "wetness_level")
    compare = source_detail[
        ["threshold_deg", "physical_pass_id", *governed_numeric, *governed_text]
    ].merge(
        packet_detail[["threshold_deg", "physical_pass_id", *governed_numeric, *governed_text]],
        on=["threshold_deg", "physical_pass_id"],
        suffixes=("_source", "_packet"),
        validate="one_to_one",
    )
    if len(compare) != len(source_detail):
        raise ValueError("Packet governed-value join is incomplete")
    for column in governed_numeric:
        if not np.allclose(compare[f"{column}_source"], compare[f"{column}_packet"], rtol=0, atol=1e-10):
            raise ValueError(f"Packet governed numeric values differ: {column}")
    for column in governed_text:
        if not compare[f"{column}_source"].astype(str).eq(compare[f"{column}_packet"].astype(str)).all():
            raise ValueError(f"Packet governed categorical values differ: {column}")

    raw_cells = []
    checkpoint_payload = json.loads(HRRR_CHECKPOINT.read_text(encoding="utf-8"))
    checkpoint = checkpoint_payload.get("items", checkpoint_payload)
    if not isinstance(checkpoint, dict) or not checkpoint:
        raise ValueError("Observed-pass HRRR checkpoint envelope is empty or malformed")
    for record in pd.read_csv(HRRR_MANIFEST).to_dict("records"):
        item_id = str(record["item_id"])
        shard = HRRR_SHARDS / f"{item_id}.csv.gz"
        evidence = checkpoint.get(item_id)
        if (
            not isinstance(evidence, dict)
            or not shard.is_file()
            or evidence.get("sha256") != _sha(shard)
        ):
            raise ValueError(f"Observed-pass HRRR shard checksum failed: {item_id}")
        raw_cells.append(pd.read_csv(shard))
    raw_hourly = (
        pd.concat(raw_cells, ignore_index=True)
        .groupby(["city", "timestamp_utc"], sort=True, observed=True)
        .agg(
            vpd_kpa=("vpd_kpa", "mean"), t2m_k=("t2m_k", "mean"),
            wind_speed_m_s=("wind_speed_m_s", "mean"),
        )
        .reset_index()
    )
    raw_hourly["timestamp_utc"] = pd.to_datetime(raw_hourly["timestamp_utc"], utc=True, errors="raise", format="mixed")
    observed_passes = joined[["city", "orbit", "acquisition_utc"]].copy()
    observed_passes["acquisition_utc"] = pd.to_datetime(observed_passes["acquisition_utc"], utc=True, errors="raise", format="mixed")
    for target, source in (
        ("vpd_kpa_at_acquisition", "vpd_kpa"),
        ("air_temperature_k_at_acquisition", "t2m_k"),
        ("wind_speed_m_s_at_acquisition", "wind_speed_m_s"),
    ):
        observed_passes[target] = np.nan
        for city, indices in observed_passes.groupby("city").indices.items():
            hourly_city = raw_hourly.loc[raw_hourly["city"].eq(city)].sort_values("timestamp_utc")
            observed_passes.iloc[indices, observed_passes.columns.get_loc(target)] = np.interp(
                observed_passes.iloc[indices]["acquisition_utc"].astype("int64").to_numpy(float),
                hourly_city["timestamp_utc"].astype("int64").to_numpy(float),
                hourly_city[source].to_numpy(float), left=np.nan, right=np.nan,
            )
    observed_compare = observed_passes.merge(
        joined[["city", "orbit", "vpd_kpa_at_acquisition", "air_temperature_k_at_acquisition", "wind_speed_m_s_at_acquisition"]],
        on=["city", "orbit"], suffixes=("_clean", "_packet"), validate="one_to_one",
    )
    for column in ("vpd_kpa_at_acquisition", "air_temperature_k_at_acquisition", "wind_speed_m_s_at_acquisition"):
        if not np.allclose(
            observed_compare[f"{column}_clean"], observed_compare[f"{column}_packet"], rtol=0, atol=1e-10
        ):
            raise ValueError(f"Observed-pass HRRR interpolation differs: {column}")

    relabelled = _relabel_archive()
    packet_relabel = pd.read_csv(PACKET / "archive_all_31_precipitation_relabel.csv")
    comparison = relabelled[
        ["observation_id", "antecedent_precipitation_30d_mm", "wetness_percentile", "wetness_level", "bound_scope_included"]
    ].merge(
        packet_relabel[
            ["observation_id", "antecedent_precipitation_30d_mm", "antecedent_precipitation_30d_wetness_percentile", "wetness_level", "bound_scope_included"]
        ],
        on="observation_id",
        suffixes=("_clean", "_packet"),
        validate="one_to_one",
    )
    if not np.allclose(
        comparison["antecedent_precipitation_30d_mm_clean"],
        comparison["antecedent_precipitation_30d_mm_packet"],
        rtol=0,
        atol=1e-10,
    ) or not np.allclose(
        comparison["wetness_percentile"],
        comparison["antecedent_precipitation_30d_wetness_percentile"],
        rtol=0,
        atol=1e-10,
    ):
        raise ValueError("Archive precipitation relabel values did not reproduce")
    if not comparison["wetness_level_clean"].eq(comparison["wetness_level_packet"]).all():
        raise ValueError("Archive wet/dry labels did not reproduce")
    if not _strict_true(comparison["bound_scope_included_clean"]).eq(
        _strict_true(comparison["bound_scope_included_packet"])
    ).all():
        raise ValueError("Archive bound scope did not reproduce")

    new_status = pd.read_csv(NEW_ARCHIVE_STATUS)
    if len(new_status) != 300 or new_status.duplicated(["city", "orbit"]).any():
        raise ValueError("New archive status is not the sealed 300-pass census")
    if new_status["archive_status"].astype(str).eq("UNRESOLVED_ERROR").any():
        raise ValueError("New archive status has UNRESOLVED_ERROR")
    new_missing = new_status.loc[new_status["archive_status"].astype(str).eq("RESOLVED_UNAVAILABLE")]
    new_labels = pd.read_csv(NEW_UNAVAILABLE_LABELS)
    recomputed_new, new_source_evidence = _recompute_new_unavailable()
    if set(new_missing[["city", "orbit"]].itertuples(index=False, name=None)) != set(
        new_labels[["city", "orbit"]].itertuples(index=False, name=None)
    ):
        raise ValueError("New unavailable label census does not reproduce")
    if not new_labels["archive_status"].astype(str).eq("RESOLVED_UNAVAILABLE").all():
        raise ValueError("New unavailable labels include a non-resolved pass")
    if (
        not _strict_true(new_labels["exact_weather_complete"]).all()
        or _strict_true(new_labels["temperature_or_lst_opened"]).any()
        or _strict_true(new_labels["record_2026_opened"]).any()
    ):
        raise ValueError("New unavailable labels are incomplete or violate a data lock")
    governed_new_numeric = (
        "vpd_kpa_at_acquisition", "air_temperature_k_at_acquisition",
        "wind_speed_m_s_at_acquisition", "antecedent_precipitation_30d_mm",
        "demand_percentile", "antecedent_precipitation_30d_wetness_percentile",
    )
    governed_new_text = ("local_solar_date", "time_stratum", "demand_level", "wetness_level")
    new_compare = recomputed_new[
        ["city", "orbit", "physical_pass_id", *governed_new_numeric, *governed_new_text]
    ].merge(
        new_labels[["city", "orbit", *governed_new_numeric, *governed_new_text]],
        on=["city", "orbit"], suffixes=("_clean", "_packet"), validate="one_to_one",
    )
    if len(new_compare) != len(new_missing):
        raise ValueError("New unavailable governed-value comparison changed the sealed census")
    for column in governed_new_numeric:
        if not np.allclose(
            new_compare[f"{column}_clean"], new_compare[f"{column}_packet"], rtol=0, atol=1e-10
        ):
            raise ValueError(f"New unavailable governed numeric value differs: {column}")
    for column in governed_new_text:
        if not new_compare[f"{column}_clean"].astype(str).eq(
            new_compare[f"{column}_packet"].astype(str)
        ).all():
            raise ValueError(f"New unavailable governed categorical value differs: {column}")
    new_labels = recomputed_new
    unified_packet = pd.read_csv(PACKET / "unified_unavailable_pass_ledger.csv")
    expected_unified_ids = set(relabelled["physical_pass_id"].astype(str)) | set(
        new_labels["physical_pass_id"].astype(str)
    )
    if unified_packet["physical_pass_id"].duplicated().any() or set(
        unified_packet["physical_pass_id"].astype(str)
    ) != expected_unified_ids:
        raise ValueError("Unified unavailable pass ledger did not reproduce")

    independent_unified = pd.concat([relabelled, new_labels], ignore_index=True, sort=False)
    independent_unified["bound_scope_included"] = [
        (str(city), str(window)) in PRIMARY
        for city, window in independent_unified[["city", "window_id"]].itertuples(
            index=False, name=None
        )
    ]
    independent_bounds = _independent_archive_bounds(packet_detail, independent_unified)
    packet_bounds = pd.read_csv(PACKET / "archive_bounds_four_primary_windows.csv")
    for row in packet_bounds.to_dict("records"):
        threshold = int(row["threshold_deg"])
        expected = independent_bounds[threshold]
        for key, packet_key in (
            ("lower_eligible", "lower_count_eligible"),
            ("upper_eligible", "upper_count_eligible"),
            ("first_threshold_invariant", "archive_threshold_choice_invariant"),
            ("archive_bounds_invariant", "archive_bounds_invariant"),
        ):
            if bool(expected[key]) != (str(row[packet_key]).casefold() == "true"):
                raise ValueError(f"Archive bound {packet_key} disagrees at {threshold}")

    clean_pairwise = _independent_pairwise(packet_detail)
    reported_pairwise = pd.read_csv(PACKET / "pairwise_balance_diagnostics.csv")
    pair_keys = ["threshold_deg", "left_city_window", "right_city_window"]
    if set(map(tuple, clean_pairwise[pair_keys].to_records(index=False))) != set(
        map(tuple, reported_pairwise[pair_keys].to_records(index=False))
    ):
        raise ValueError("Pairwise diagnostic membership did not reproduce")
    pair_compare = clean_pairwise.merge(
        reported_pairwise, on=pair_keys, suffixes=("_clean", "_packet"), validate="one_to_one"
    )
    for column in clean_pairwise.columns.difference(pair_keys):
        if not np.allclose(
            pair_compare[f"{column}_clean"], pair_compare[f"{column}_packet"], rtol=0, atol=1e-12,
            equal_nan=True,
        ):
            raise ValueError(f"Pairwise diagnostic differs: {column}")

    phenology = pd.read_csv(PACKET / "phenology_decisions.csv")
    pheno = {
        (str(row.city), str(row.window_id)): str(row.phenology_auto_eligible).casefold() == "true"
        for row in phenology.itertuples(index=False)
        if (str(row.city), str(row.window_id)) in PRIMARY
    }
    if set(pheno) != PRIMARY:
        raise ValueError("Clean-room phenology membership is not the exact four windows")
    eligibility = pd.read_csv(PACKET / "threshold_city_window_eligibility.csv")
    balance = pd.read_csv(PACKET / "balance_diagnostics.csv")
    independently_eligible: dict[int, bool] = {}
    for threshold in THRESHOLDS:
        group = packet_detail.loc[packet_detail["threshold_deg"].eq(threshold)]
        row_passes = []
        for city, window in sorted(PRIMARY):
            support = group.loc[group["city"].eq(city) & group["window_id"].eq(window)]
            high = support.loc[support["demand_level"].eq("high")]
            wet = high.loc[high["wetness_level"].eq("wet")]
            dry = high.loc[high["wetness_level"].eq("dry")]
            row_passes.append(
                pheno[(city, window)]
                and support["year"].nunique() >= 4
                and support["time_stratum"].eq("10-12").sum() >= 3
                and support["time_stratum"].eq("16-18").sum() >= 3
                and len(wet) >= 2
                and len(dry) >= 2
                and _overlap(wet["vpd_kpa_at_acquisition"], dry["vpd_kpa_at_acquisition"]) > 0
                and _overlap(wet["day_of_window"], dry["day_of_window"]) > 0
                and independent_bounds[threshold]["archive_bounds_invariant"]
                and not (
                    unresolved_accessible["city"].eq(city)
                    & unresolved_accessible["window_id"].eq(window)
                ).any()
            )
        counts = group.groupby("city").size()
        share = bool(len(group) and counts.max() / counts.sum() <= 0.40)
        reported_balance = balance.loc[balance["threshold_deg"].eq(threshold)]
        if len(reported_balance) != 1:
            raise ValueError("Balance row count did not reproduce")
        diagnostic_columns = (
            "vpd_kpa_at_acquisition", "antecedent_precipitation_30d_mm",
            "l1b_view_zenith_abs_p95_deg", "relative_azimuth_median_deg",
            "view_azimuth_circular_mean_deg", "solar_azimuth_circular_mean_deg",
            "air_temperature_k_at_acquisition",
            "wind_speed_m_s_at_acquisition",
        )
        groups = [part for _, part in group.groupby(["city", "window_id"], sort=True)]
        diagnostics = bool(
            len(groups) == len(PRIMARY)
            and all(
                len(part)
                and np.isfinite(
                    part[list(diagnostic_columns)]
                    .apply(pd.to_numeric, errors="coerce")
                    .to_numpy(float)
                ).all()
                for part in groups
            )
        )
        independently_eligible[threshold] = bool(all(row_passes) and share and diagnostics)

        reported_rows = eligibility.loc[eligibility["threshold_deg"].eq(threshold)]
        if set(reported_rows[["city", "window_id"]].itertuples(index=False, name=None)) != PRIMARY:
            raise ValueError(f"Eligibility membership differs at threshold {threshold}")
        reported_map = {
            (str(row.city), str(row.window_id)): str(row.eligible_city_window).casefold() == "true"
            for row in reported_rows.itertuples(index=False)
        }
        expected_map = dict(zip(sorted(PRIMARY), row_passes, strict=True))
        if reported_map != expected_map:
            raise ValueError(f"City-window eligibility differs at threshold {threshold}")

    independent_selected = next(
        (threshold for threshold in THRESHOLDS if independently_eligible[threshold]), None
    )
    selection = json.loads((PACKET / "selection.json").read_text(encoding="utf-8"))
    if selection.get("primary_view_zenith_threshold_deg") != independent_selected:
        raise ValueError(
            "Selected threshold did not reproduce: "
            f"{independent_selected} vs {selection.get('primary_view_zenith_threshold_deg')}"
        )
    return {
        "status": "PASS",
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "cleanroom_module_imports_production_gate3": False,
        "cleanroom_module_imports_augmentation_runner": False,
        "source_bindings_match": True,
        "new_archive_status_provenance_reproduced": new_archive_provenance,
        "physical_membership_and_dedup_reproduced": True,
        "geometry_cloud_weather_join_reproduced": True,
        "observed_pass_hrrr_interpolation_reproduced_from_shards": True,
        "geometry_evidence_verification": geometry_evidence,
        "governed_pass_values_reproduced": True,
        "threshold_membership_counts": {
            str(threshold): len(threshold_ids[threshold]) for threshold in THRESHOLDS
        },
        "archive_all_31_precipitation_labels_reproduced": True,
        "new_unavailable_recomputed_from_sealed_status": True,
        "new_unavailable_count": int(len(new_missing)),
        "new_unavailable_source_evidence": new_source_evidence,
        "archive_bound_scope_rows": int(relabelled["bound_scope_included"].sum()),
        "archive_bounds_reproduced": True,
        "pairwise_diagnostics_reproduced": True,
        "accessible_unresolved_geometry_passes": int(len(unresolved_accessible)),
        "city_window_support_reproduced": True,
        "selected_threshold_deg": independent_selected,
        "temperature_or_lst_opened": False,
        "holdout_data_opened": False,
        "record_2026_science_data_opened_or_queried": False,
        "record_2026_metadata_exposures_preserved": [
            "D0060", "D0061", "D0073", "D0074"
        ],
        "verification_boundary": (
            "Clean-room verifies source evidence hashes and pass-level geometry/cloud/weather "
            "bindings and governed summaries; independent raw per-pixel geometry reconstruction "
            "remains assigned to Gate 6."
        ),
    }


def main() -> int:
    output_path = PACKET / "cleanroom_verification.json"
    try:
        result = verify()
    except Exception as exc:
        result = {
            "status": "FAIL",
            "verified_utc": datetime.now(timezone.utc).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "temperature_or_lst_opened": False,
            "holdout_data_opened": False,
            "record_2026_science_data_opened_or_queried": False,
            "record_2026_metadata_exposures_preserved": [
                "D0060", "D0061", "D0073", "D0074"
            ],
        }
        _atomic_json(output_path, result)
        raise
    _atomic_json(output_path, result)
    print("PASS run_v2_hitl_gate3_cleanroom_check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
