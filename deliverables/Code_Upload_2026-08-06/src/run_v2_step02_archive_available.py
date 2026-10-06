#!/usr/bin/env python3
"""Run the decision-scoped D0047 archive-available geometry/cloud profile.

This is an append-only adapter around the frozen D0035/D0036 geometry engine.
It changes only the candidate population and output namespaces authorized by
D0047.  The geometry thresholds, source variables, mapping rule, boundary
proof, overlap rule, and exhaustive-cloud rule remain unchanged.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Iterator, Mapping

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import run_v2_step02_l1b_geometry as base

from urban_cooling_v2.config import load_config
from urban_cooling_v2.step02_archive_available import (
    ALGORITHM_VERSION,
    AVAILABLE_SCENE_COUNT_COLUMN,
    CANDIDATE_STATUS_COLUMN,
    DECISION_ID,
    EXCLUDED_STATUS,
    EXCLUSION_REASON,
    EXCLUSION_REASON_COLUMN,
    FROZEN_COUNTS,
    IMPLEMENTATION_DECISION_ID,
    MISSING_SCENE_COUNT_COLUMN,
    MISSING_SCENE_KEYS_COLUMN,
    PROFILE_INCLUDED_COLUMN,
    REQUIRED_SCENE_COUNT_COLUMN,
    RETAINED_STATUS,
    RUN_ID,
    RUN_RECORD_SCHEMA_VERSION,
    TARGET_SCOPE,
    VALIDATION_EXCLUDED_CANDIDATES_FIELD,
    VALIDATION_ORIGINAL_CANDIDATES_FIELD,
    VALIDATION_RETAINED_CANDIDATES_FIELD,
    VALIDATION_RETAINED_LINKS_FIELD,
    VALIDATION_RETAINED_SCENES_FIELD,
    archive_unavailable_exclusions,
    build_archive_available_profile,
    candidate_availability_ledger,
    exclusion_summary,
)


ANALYSIS_PROFILE = "D0047_archive_available"
SCIENTIFIC_GATE_SCOPE = "archive_available_only"
COLLECTION_CONCEPT_ID = "C2076087338-LPCLOUD"

PRE_CLOUD = base.PRE_CLOUD
VIEW_MANIFEST = base.VIEW_MANIFEST
MISSING_SCENE_EVIDENCE = (
    ROOT
    / "data/processed/v2/task1/step2_l1b_identity_refresh_D0042/scene_identity_resolution.csv"
)
SOURCE_D0035_CMR_CACHE = (
    ROOT / "data/raw/v2/ecostress/l1b_geo_geometry_D0035/cmr/by_scene"
)

RAW_ROOT = ROOT / "data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available"
CMR_CACHE = RAW_ROOT / "cmr"
DMRPP_DIR = RAW_ROOT / "dmrpp"
LOCATOR_DIR = RAW_ROOT / "locator_stride32"
PASS_EVIDENCE_DIR = RAW_ROOT / "pass_evidence"
SCENE_MANIFEST = RAW_ROOT / "l1b_geo_scene_manifest.csv"
ASSET_CHECKPOINT = RAW_ROOT / "locator_dmrpp_checkpoint.json"
GEOMETRY_CHECKPOINT = RAW_ROOT / "geometry_scene_checkpoint.json"

CLOUD_MANIFEST = (
    ROOT / "data/raw/v2/ecostress/enrichment_manifest_cloud_l1b_geo_D0047.csv"
)
CLOUD_CHECKPOINT = (
    ROOT
    / "data/raw/v2/ecostress/enrichment_assets/cloud_l1b_geo_D0047_checkpoint.json"
)

OUTPUT_DIR = (
    ROOT / "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047"
)
CANDIDATE_LEDGER = OUTPUT_DIR / "candidate_availability_ledger.csv"
EXCLUSION_LEDGER = OUTPUT_DIR / "archive_unavailable_pre_geometry_exclusions.csv"
ATTRITION_SUMMARY = OUTPUT_DIR / "archive_available_attrition_summary.csv"
RETAINED_LINKS = OUTPUT_DIR / "retained_city_scene_links.csv"
PROFILE_VALIDATION = OUTPUT_DIR / "profile_validation.json"
GEOMETRY_SUMMARY = OUTPUT_DIR / "geometry_pass_summary.csv"
PRE_CLOUD_D0047 = OUTPUT_DIR / "passes_quality_screened_pre_cloud_geometry_only.csv"
GEOMETRY_VALIDATION_JSON = OUTPUT_DIR / "geometry_validation.json"
GEOMETRY_VALIDATION_CSV = OUTPUT_DIR / "geometry_validation.csv"
CLOUD_SUMMARY = OUTPUT_DIR / "cloud_pass_summary.csv"
FINAL_TABLE = OUTPUT_DIR / "passes_quality_screened_l1b_geo.csv"
COMBINED_VALIDATION_JSON = OUTPUT_DIR / "combined_validation.json"
COMBINED_VALIDATION_CSV = OUTPUT_DIR / "combined_validation.csv"
RUN_RECORD = OUTPUT_DIR / "run_record.json"

PROFILE_ARTIFACTS = (
    CANDIDATE_LEDGER,
    EXCLUSION_LEDGER,
    ATTRITION_SUMMARY,
    RETAINED_LINKS,
    PROFILE_VALIDATION,
)

_ORIGINAL_DECORATE_SCENE_MANIFEST = base._decorate_scene_manifest
_ORIGINAL_PREPARE_SCENE_MANIFEST = base._prepare_scene_manifest
_ORIGINAL_RUN_GEOMETRY = base._run_geometry_passes
_ORIGINAL_RUN_CLOUD = base._run_cloud
_ORIGINAL_RESOLVE_LATEST_GEO_SCENES = base.resolve_latest_geo_scenes


def _strict_bool(series: pd.Series, *, name: str) -> pd.Series:
    if pd.api.types.is_bool_dtype(series.dtype):
        if series.isna().any():
            raise ValueError(f"{name} contains null retained values")
        return series.astype(bool)
    lowered = series.astype("string").str.strip().str.casefold()
    if lowered.isna().any() or (~lowered.isin(["true", "false"])).any():
        raise ValueError(f"{name} contains non-boolean retained values")
    return lowered.eq("true")


def _profile_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        pd.read_csv(PRE_CLOUD),
        pd.read_csv(VIEW_MANIFEST),
        pd.read_csv(MISSING_SCENE_EVIDENCE),
    )


def _write_profile_artifacts(
    screened: pd.DataFrame,
    views: pd.DataFrame,
    missing: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    candidates, links, validation = build_archive_available_profile(
        screened, views, missing
    )
    validation = {
        **validation,
        "analysis_profile": ANALYSIS_PROFILE,
        "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
        "candidate_ledger_relative_path": str(CANDIDATE_LEDGER.relative_to(ROOT)),
        "exclusion_ledger_relative_path": str(EXCLUSION_LEDGER.relative_to(ROOT)),
        "retained_links_relative_path": str(RETAINED_LINKS.relative_to(ROOT)),
    }
    base._atomic_csv(candidate_availability_ledger(candidates), CANDIDATE_LEDGER)
    base._atomic_csv(archive_unavailable_exclusions(candidates), EXCLUSION_LEDGER)
    base._atomic_csv(exclusion_summary(candidates), ATTRITION_SUMMARY)
    base._atomic_csv(links, RETAINED_LINKS)
    base._atomic_json(validation, PROFILE_VALIDATION)
    return candidates, links, validation


def _profile_targets(
    screened_passes: pd.DataFrame,
    latest_view_manifest: pd.DataFrame,
    **_: Any,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = pd.read_csv(MISSING_SCENE_EVIDENCE)
    candidates, links, _ = _write_profile_artifacts(
        screened_passes, latest_view_manifest, missing
    )
    return candidates, links


def _validate_config_seal(config: Any) -> None:
    """Confirm that D0047 inherits the unchanged frozen D0035 mechanics."""

    expected = {
        "geometry_remediation_decision_id": "D0035",
        "geometry_remediation_collection_concept_id": COLLECTION_CONCEPT_ID,
        "geometry_remediation_expected_metadata_candidates": 942,
        "geometry_remediation_expected_city_scene_references": 1_404,
        "geometry_remediation_expected_unique_l1b_scene_assets": 1_370,
        "geometry_remediation_locator_stride": base.LOCATOR_STRIDE,
        "geometry_remediation_locator_margin_pixels": base.LOCATOR_MARGIN_PIXELS,
        "geometry_remediation_minimum_view_coverage_fraction": base.MINIMUM_VIEW_COVERAGE,
        "geometry_remediation_max_view_zenith_p95_deg": base.NEAR_NADIR_MAX_DEG,
    }
    mismatches = [
        key for key, value in expected.items() if config.ecostress.get(key) != value
    ]
    if mismatches:
        raise ValueError(
            "D0047 inherited D0035 execution/config seal mismatch: "
            + ", ".join(sorted(mismatches))
        )


def _copy_exact_cache(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Missing immutable D0035 exact cache: {source}")
    source_digest = base.sha256_file(source)
    if destination.is_file():
        if base.sha256_file(destination) != source_digest:
            raise ValueError(f"Existing D0047 exact cache differs: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    shutil.copyfile(source, temporary)
    if base.sha256_file(temporary) != source_digest:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"D0047 exact-cache copy failed checksum: {source.name}")
    temporary.replace(destination)


def _seed_exact_cmr_caches(links: pd.DataFrame) -> None:
    keys = sorted(
        set(map(tuple, links[["orbit", "scene"]].to_records(index=False)))
    )
    if len(keys) != FROZEN_COUNTS.retained_unique_scenes:
        raise ValueError("D0047 exact-cache seed does not contain 1,323 scenes")
    for raw_orbit, raw_scene in keys:
        orbit, scene = int(raw_orbit), int(raw_scene)
        name = f"{orbit:05d}_{scene:03d}.json"
        source = SOURCE_D0035_CMR_CACHE / name
        document = json.loads(source.read_text(encoding="utf-8"))
        if document.get("query") != base._exact_scene_query(orbit, scene):
            raise ValueError(f"D0035 exact cache query mismatch: {name}")
        _copy_exact_cache(source, CMR_CACHE / "by_scene" / name)


def _prepare_scene_manifest(
    candidates: pd.DataFrame,
    links: pd.DataFrame,
    **kwargs: Any,
) -> pd.DataFrame:
    _seed_exact_cmr_caches(links)
    return _ORIGINAL_PREPARE_SCENE_MANIFEST(candidates, links, **kwargs)


def _decorate_scene_manifest(
    links: pd.DataFrame,
    results: list[dict[str, Any]],
    **kwargs: Any,
) -> pd.DataFrame:
    manifest = _ORIGINAL_DECORATE_SCENE_MANIFEST(
        links, results, **kwargs
    )
    manifest["decision_id"] = DECISION_ID
    manifest["target_scope"] = TARGET_SCOPE
    manifest["analysis_profile"] = ANALYSIS_PROFILE
    manifest["scientific_gate_scope"] = SCIENTIFIC_GATE_SCOPE
    if len(manifest) != FROZEN_COUNTS.retained_unique_scenes:
        raise ValueError("D0047 scene manifest is not exactly 1,323 rows")
    if not manifest["status"].astype(str).eq("available").all():
        raise ValueError("D0047 retained scene manifest contains an unavailable identity")
    base._atomic_csv(manifest, SCENE_MANIFEST)
    return manifest


def _resolve_latest_geo_scenes(
    scene_links: pd.DataFrame,
    geo_records: pd.DataFrame,
    **kwargs: Any,
) -> pd.DataFrame:
    """Override D0035's definition-time 1,370 default for D0047 only."""

    if "expected_unique_scenes" in kwargs and int(
        kwargs["expected_unique_scenes"]
    ) != FROZEN_COUNTS.retained_unique_scenes:
        raise ValueError("D0047 GEO resolver received a non-1,323 scene seal")
    return _ORIGINAL_RESOLVE_LATEST_GEO_SCENES(
        scene_links,
        geo_records,
        expected_unique_scenes=FROZEN_COUNTS.retained_unique_scenes,
    )


def _excluded_geometry_rows(candidates: pd.DataFrame) -> pd.DataFrame:
    excluded = candidates.loc[
        candidates[CANDIDATE_STATUS_COLUMN].eq(EXCLUDED_STATUS)
    ].copy()
    rows: list[dict[str, Any]] = []
    for candidate in excluded.to_dict("records"):
        acquisition = pd.Timestamp(candidate["acquisition_utc"])
        evidence_hash = str(candidate["d0047_missing_scene_evidence_sha256"])
        rows.append(
            {
                "city": str(candidate["city"]),
                "orbit": int(candidate["orbit"]),
                "acquisition_utc": acquisition.isoformat(),
                "year": int(acquisition.year),
                "metadata_candidate": True,
                "n_l1b_geo_scenes": np.nan,
                "n_domain_pixels": np.nan,
                "n_view_valid_pixels": np.nan,
                "view_valid_fraction": np.nan,
                "view_zenith_abs_min_deg": np.nan,
                "view_zenith_abs_median_deg": np.nan,
                "view_zenith_abs_mean_deg": np.nan,
                "view_zenith_abs_p95_deg": np.nan,
                "view_zenith_abs_max_deg": np.nan,
                "near_nadir_threshold_deg": base.NEAR_NADIR_MAX_DEG,
                "minimum_view_coverage": base.MINIMUM_VIEW_COVERAGE,
                "near_nadir": pd.NA,
                "n_overlapping_valid_pixels": np.nan,
                "overlap_rule": "not evaluated; archive unavailable before geometry",
                "geometry_source": "ECO_L1B_GEO.002",
                "l1b_geometry_covered_cells": np.nan,
                "l1b_geometry_domain_cells": np.nan,
                "l1b_geometry_coverage_fraction": np.nan,
                "l1b_view_zenith_abs_p95_deg": np.nan,
                "l1b_geometry_complete": pd.NA,
                "l1b_geometry_status": EXCLUDED_STATUS,
                "quality_candidate_pre_cloud_l1b": pd.NA,
                "quality_candidate_pre_cloud": pd.NA,
                "quality_candidate_pre_cloud_l2t_invalid": pd.NA,
                "geometry_resolution_status": EXCLUDED_STATUS,
                "geometry_definitive": pd.NA,
                "quality_candidate_pre_cloud_geometry_only": pd.NA,
                "geometry_error_type": pd.NA,
                "scene_source_evidence_sha256": evidence_hash,
                "scene_map_set_sha256": evidence_hash,
                "decision_id": DECISION_ID,
                CANDIDATE_STATUS_COLUMN: EXCLUDED_STATUS,
                PROFILE_INCLUDED_COLUMN: False,
                EXCLUSION_REASON_COLUMN: EXCLUSION_REASON,
                REQUIRED_SCENE_COUNT_COLUMN: int(
                    candidate[REQUIRED_SCENE_COUNT_COLUMN]
                ),
                AVAILABLE_SCENE_COUNT_COLUMN: int(
                    candidate[AVAILABLE_SCENE_COUNT_COLUMN]
                ),
                MISSING_SCENE_COUNT_COLUMN: int(
                    candidate[MISSING_SCENE_COUNT_COLUMN]
                ),
                MISSING_SCENE_KEYS_COLUMN: str(
                    candidate[MISSING_SCENE_KEYS_COLUMN]
                ),
                "d0047_profile_scope": TARGET_SCOPE,
            }
        )
    return pd.DataFrame(rows)


def _run_geometry_passes(
    candidates: pd.DataFrame,
    manifest: pd.DataFrame,
    links: pd.DataFrame,
    target_grids: Mapping[str, Mapping[str, Any]],
    asset_bindings: Mapping[str, Mapping[str, Any]],
    **kwargs: Any,
) -> pd.DataFrame:
    retained = candidates.loc[
        candidates[CANDIDATE_STATUS_COLUMN].eq(RETAINED_STATUS)
    ].copy()
    if len(retained) != FROZEN_COUNTS.retained_candidates:
        raise ValueError("D0047 geometry target count is not exactly 911")
    previous_expected = base.EXPECTED_METADATA_CANDIDATES
    base.EXPECTED_METADATA_CANDIDATES = FROZEN_COUNTS.retained_candidates
    try:
        resolved = _ORIGINAL_RUN_GEOMETRY(
            retained,
            manifest,
            links,
            target_grids,
            asset_bindings,
            **kwargs,
        )
    finally:
        base.EXPECTED_METADATA_CANDIDATES = previous_expected
    provenance = retained[
        [
            "city",
            "orbit",
            CANDIDATE_STATUS_COLUMN,
            PROFILE_INCLUDED_COLUMN,
            EXCLUSION_REASON_COLUMN,
            REQUIRED_SCENE_COUNT_COLUMN,
            AVAILABLE_SCENE_COUNT_COLUMN,
            MISSING_SCENE_COUNT_COLUMN,
            MISSING_SCENE_KEYS_COLUMN,
            "d0047_profile_scope",
        ]
    ]
    resolved = resolved.merge(
        provenance, on=["city", "orbit"], how="left", validate="one_to_one"
    )
    summary = pd.concat(
        [resolved, _excluded_geometry_rows(candidates)],
        ignore_index=True,
        sort=False,
    ).sort_values(["city", "acquisition_utc", "orbit"], kind="stable")
    summary = summary.reset_index(drop=True)
    if len(summary) != FROZEN_COUNTS.original_candidates:
        raise RuntimeError("D0047 geometry summary is not row-complete over 942 candidates")
    return summary


def _identity_set(table: pd.DataFrame) -> set[tuple[str, int, str]]:
    stamps = pd.to_datetime(
        table["acquisition_utc"], errors="raise", utc=True, format="mixed"
    ).map(lambda value: value.isoformat())
    return set(
        zip(
            table["city"].astype(str),
            pd.to_numeric(table["orbit"], errors="raise").astype(int),
            stamps,
            strict=True,
        )
    )


def _validate_geometry_identity(
    summary: pd.DataFrame, candidates: pd.DataFrame
) -> None:
    if (
        len(summary) != FROZEN_COUNTS.original_candidates
        or summary.duplicated(["city", "orbit"]).any()
        or _identity_set(summary) != _identity_set(candidates)
    ):
        raise ValueError("D0047 geometry summary does not equal the 942-row ledger")
    if int(summary[CANDIDATE_STATUS_COLUMN].eq(EXCLUDED_STATUS).sum()) != (
        FROZEN_COUNTS.excluded_candidates
    ):
        raise ValueError("D0047 geometry summary lost the 31 exclusions")


_NULL_EXCLUDED_GEOMETRY_COLUMNS = (
    "n_l1b_geo_scenes",
    "n_domain_pixels",
    "n_view_valid_pixels",
    "view_valid_fraction",
    "view_zenith_abs_min_deg",
    "view_zenith_abs_median_deg",
    "view_zenith_abs_mean_deg",
    "view_zenith_abs_p95_deg",
    "view_zenith_abs_max_deg",
    "near_nadir",
    "n_overlapping_valid_pixels",
    "l1b_geometry_covered_cells",
    "l1b_geometry_domain_cells",
    "l1b_geometry_coverage_fraction",
    "l1b_view_zenith_abs_p95_deg",
    "l1b_geometry_complete",
    "quality_candidate_pre_cloud_l1b",
    "quality_candidate_pre_cloud",
    "quality_candidate_pre_cloud_l2t_invalid",
    "geometry_definitive",
    "quality_candidate_pre_cloud_geometry_only",
    "geometry_error_type",
)


def _build_geometry_validation(summary: pd.DataFrame) -> dict[str, Any]:
    _validate_geometry_identity(summary, summary)
    retained = summary.loc[
        summary[CANDIDATE_STATUS_COLUMN].eq(RETAINED_STATUS)
    ].copy()
    excluded = summary.loc[
        summary[CANDIDATE_STATUS_COLUMN].eq(EXCLUDED_STATUS)
    ].copy()
    if len(retained) != FROZEN_COUNTS.retained_candidates or len(excluded) != (
        FROZEN_COUNTS.excluded_candidates
    ):
        raise ValueError("D0047 geometry status census changed")
    null_columns = [
        column
        for column in _NULL_EXCLUDED_GEOMETRY_COLUMNS
        if column not in excluded or not excluded[column].isna().all()
    ]
    definitive = _strict_bool(
        retained["l1b_geometry_complete"], name="l1b_geometry_complete"
    )
    geometry_definitive = _strict_bool(
        retained["geometry_definitive"], name="geometry_definitive"
    )
    passing_flags = _strict_bool(
        retained["quality_candidate_pre_cloud_l1b"],
        name="quality_candidate_pre_cloud_l1b",
    )
    domain = pd.to_numeric(retained["n_domain_pixels"], errors="coerce")
    valid = pd.to_numeric(retained["n_view_valid_pixels"], errors="coerce")
    fraction = pd.to_numeric(retained["view_valid_fraction"], errors="coerce")
    ratios_equal = np.isclose(fraction, valid / domain, rtol=0, atol=1e-15)
    hashes_valid = retained["scene_map_set_sha256"].astype(str).str.fullmatch(
        r"[0-9a-f]{64}"
    )
    retained_complete = bool(
        definitive.all()
        and geometry_definitive.all()
        and retained["l1b_geometry_status"].astype(str).str.len().gt(0).all()
        and hashes_valid.all()
        and domain.gt(0).all()
        and valid.ge(0).all()
        and valid.le(domain).all()
        and ratios_equal.all()
    )
    complete = bool(retained_complete and not null_columns)
    passing = int(passing_flags.sum())
    status = (
        "GEOMETRY_SEALED_AWAITING_EXHAUSTIVE_CLOUD_D0047"
        if complete
        else "STOP_D0047_INCOMPLETE_ARCHIVE_AVAILABLE_GEOMETRY"
    )
    return {
        "decision_id": DECISION_ID,
        "implementation_decision_id": IMPLEMENTATION_DECISION_ID,
        "analysis_profile": ANALYSIS_PROFILE,
        "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
        VALIDATION_ORIGINAL_CANDIDATES_FIELD: FROZEN_COUNTS.original_candidates,
        VALIDATION_EXCLUDED_CANDIDATES_FIELD: FROZEN_COUNTS.excluded_candidates,
        VALIDATION_RETAINED_CANDIDATES_FIELD: FROZEN_COUNTS.retained_candidates,
        "expected_metadata_candidates": FROZEN_COUNTS.retained_candidates,
        "resolved_geometry_candidate_count": int(definitive.sum()),
        "definitive_geometry_status_count": int(geometry_definitive.sum()),
        "unresolved_geometry_candidate_count": int((~definitive).sum()),
        "excluded_geometry_metric_null_row_count": int(
            excluded[list(_NULL_EXCLUDED_GEOMETRY_COLUMNS)].isna().all(axis=1).sum()
        ),
        "excluded_geometry_nonnull_columns": null_columns,
        "geometry_source": "ECO_L1B_GEO.002",
        "geometry_complete": complete,
        "candidate_seal_geometry_only": complete,
        "candidate_view_mask_cloud_independent": complete,
        "view_gate_cloud_conditioned": False,
        "geometry_passing_candidate_count": passing,
        "scientific_gate_eligible": False,
        "missing_scene_imputation_used": False,
        "missing_scene_zero_coverage_assigned": False,
        "adjacent_scene_substitution_used": False,
        "gate_status": status,
        "canonical_status": status,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
    }


def _canonical_pre_cloud_table(
    candidates: pd.DataFrame, geometry_summary: pd.DataFrame
) -> pd.DataFrame:
    table = candidates.copy()
    if "quality_candidate_pre_cloud" in table.columns:
        table = table.rename(
            columns={
                "quality_candidate_pre_cloud": "quality_candidate_pre_cloud_l2t_invalid"
            }
        )
    else:
        table["quality_candidate_pre_cloud_l2t_invalid"] = False
    generic_geometry = [
        "n_domain_pixels",
        "n_view_valid_pixels",
        "view_valid_fraction",
        "view_zenith_abs_min_deg",
        "view_zenith_abs_median_deg",
        "view_zenith_abs_mean_deg",
        "view_zenith_abs_p95_deg",
        "view_zenith_abs_max_deg",
        "near_nadir_threshold_deg",
        "minimum_view_coverage",
        "near_nadir",
        "n_overlapping_valid_pixels",
        "overlap_rule",
    ]
    table = table.rename(
        columns={
            column: f"{column}_l2t_invalid"
            for column in generic_geometry
            if column in table.columns
        }
    )
    metrics = geometry_summary.drop(
        columns=[
            column
            for column in ("metadata_candidate", "year")
            if column in geometry_summary
        ],
        errors="ignore",
    ).copy()
    for frame in (table, metrics):
        frame["acquisition_utc"] = pd.to_datetime(
            frame["acquisition_utc"], utc=True, format="mixed"
        ).map(lambda value: value.isoformat())
    duplicate = [
        column
        for column in metrics.columns
        if column in table.columns and column not in {"city", "orbit", "acquisition_utc"}
    ]
    metrics = metrics.drop(columns=duplicate)
    table = table.merge(
        metrics,
        on=["city", "orbit", "acquisition_utc"],
        how="left",
        validate="one_to_one",
    )
    retained = table[CANDIDATE_STATUS_COLUMN].eq(RETAINED_STATUS)
    excluded = table[CANDIDATE_STATUS_COLUMN].eq(EXCLUDED_STATUS)
    if table.loc[retained, "quality_candidate_pre_cloud_l1b"].isna().any():
        raise ValueError("D0047 retained table lost a geometry result")
    if not table.loc[
        excluded, "quality_candidate_pre_cloud_l1b"
    ].isna().all():
        raise ValueError("D0047 exclusion rows contain a geometry check flag")
    excluded_metric_columns = [
        column
        for column in table.columns
        if column.endswith("_l2t_invalid")
        or column in _NULL_EXCLUDED_GEOMETRY_COLUMNS
    ]
    for column in excluded_metric_columns:
        table[column] = table[column].astype(object)
        table.loc[excluded, column] = pd.NA
    if not table.loc[excluded, excluded_metric_columns].isna().all().all():
        raise ValueError(
            "D0047 exclusion rows retain a candidate-facing geometry/check value"
        )
    generic = pd.Series(pd.NA, index=table.index, dtype="boolean")
    generic.loc[retained] = table.loc[
        retained, "quality_candidate_pre_cloud_l1b"
    ].astype(bool)
    table["quality_candidate_pre_cloud"] = generic
    return table.sort_values(
        ["city", "acquisition_utc", "orbit"], kind="stable"
    ).reset_index(drop=True)


def _run_cloud(
    pre_cloud_l1b: pd.DataFrame,
    latest_views: pd.DataFrame,
    domain_geometries: Mapping[str, Mapping[str, Any]],
    **kwargs: Any,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    transient = pre_cloud_l1b.copy()
    excluded = transient[CANDIDATE_STATUS_COLUMN].eq(EXCLUDED_STATUS)
    transient.loc[excluded, "quality_candidate_pre_cloud_l1b"] = False
    transient.loc[excluded, "quality_candidate_pre_cloud"] = False
    summary, validation = _ORIGINAL_RUN_CLOUD(
        transient, latest_views, domain_geometries, **kwargs
    )
    if CLOUD_MANIFEST.is_file():
        manifest = pd.read_csv(CLOUD_MANIFEST)
        manifest["decision_id"] = DECISION_ID
        manifest["target_scope"] = (
            "all_D0047_archive_available_L1B_geometry_passing_candidates"
        )
        manifest["analysis_profile"] = ANALYSIS_PROFILE
        manifest["scientific_gate_scope"] = SCIENTIFIC_GATE_SCOPE
        base._atomic_csv(manifest, CLOUD_MANIFEST)
    validation = {
        **validation,
        "decision_id": DECISION_ID,
        "analysis_profile": ANALYSIS_PROFILE,
        "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
        "cloud_scope_excludes_pre_geometry_archive_gaps": True,
    }
    return summary, validation


def _combined_validation(
    geometry: Mapping[str, Any], cloud: Mapping[str, Any]
) -> dict[str, Any]:
    combined_complete = bool(geometry["geometry_complete"] and cloud["cloud_complete"])
    no_geometry_passers = bool(
        geometry["geometry_complete"]
        and int(geometry.get("geometry_passing_candidate_count", 0)) == 0
    )
    scientific_gate_eligible = bool(combined_complete and not no_geometry_passers)
    if not geometry["geometry_complete"]:
        status = "STOP_D0047_INCOMPLETE_ARCHIVE_AVAILABLE_GEOMETRY"
    elif not cloud["cloud_complete"]:
        status = "STOP_D0047_INCOMPLETE_EXHAUSTIVE_CLOUD"
    elif no_geometry_passers:
        status = "STOP_D0047_NO_GEOMETRY_PASSERS"
    else:
        status = "PASS_D0047_ARCHIVE_AVAILABLE_GEOMETRY_AND_EXHAUSTIVE_CLOUD"
    return {
        **geometry,
        **cloud,
        "decision_id": DECISION_ID,
        "implementation_decision_id": IMPLEMENTATION_DECISION_ID,
        "analysis_profile": ANALYSIS_PROFILE,
        "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
        VALIDATION_ORIGINAL_CANDIDATES_FIELD: FROZEN_COUNTS.original_candidates,
        VALIDATION_EXCLUDED_CANDIDATES_FIELD: FROZEN_COUNTS.excluded_candidates,
        VALIDATION_RETAINED_CANDIDATES_FIELD: FROZEN_COUNTS.retained_candidates,
        VALIDATION_RETAINED_LINKS_FIELD: FROZEN_COUNTS.retained_city_scene_links,
        VALIDATION_RETAINED_SCENES_FIELD: FROZEN_COUNTS.retained_unique_scenes,
        "combined_complete": combined_complete,
        "scientific_gate_eligible": scientific_gate_eligible,
        "candidate_view_mask_cloud_independent": bool(geometry["geometry_complete"]),
        "view_gate_cloud_conditioned": False,
        "cloud_extrapolation_used": False,
        "missing_scene_imputation_used": False,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
        "gate_status": status,
        "canonical_status": status,
    }


def _unavailable_geometry_validation(
    *, stage: str, error_type: str
) -> dict[str, Any]:
    return {
        "decision_id": DECISION_ID,
        "implementation_decision_id": IMPLEMENTATION_DECISION_ID,
        "analysis_profile": ANALYSIS_PROFILE,
        "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
        VALIDATION_ORIGINAL_CANDIDATES_FIELD: FROZEN_COUNTS.original_candidates,
        VALIDATION_EXCLUDED_CANDIDATES_FIELD: FROZEN_COUNTS.excluded_candidates,
        VALIDATION_RETAINED_CANDIDATES_FIELD: FROZEN_COUNTS.retained_candidates,
        "expected_metadata_candidates": FROZEN_COUNTS.retained_candidates,
        "resolved_geometry_candidate_count": 0,
        "definitive_geometry_status_count": 0,
        "unresolved_geometry_candidate_count": FROZEN_COUNTS.retained_candidates,
        "geometry_source": "ECO_L1B_GEO.002",
        "geometry_complete": False,
        "candidate_seal_geometry_only": False,
        "candidate_view_mask_cloud_independent": False,
        "view_gate_cloud_conditioned": False,
        "geometry_passing_candidate_count": 0,
        "scientific_gate_eligible": False,
        "geometry_failure_stage": str(stage),
        "geometry_error_type": str(error_type),
        "missing_scene_imputation_used": False,
        "gate_status": "STOP_D0047_INCOMPLETE_ARCHIVE_AVAILABLE_GEOMETRY",
        "canonical_status": "STOP_D0047_INCOMPLETE_ARCHIVE_AVAILABLE_GEOMETRY",
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
    }


def _write_run_record(
    combined: Mapping[str, Any],
    artifacts: list[Path],
    *,
    profile: str,
) -> None:
    geometry_items = (
        base.load_checkpoint(GEOMETRY_CHECKPOINT)
        if GEOMETRY_CHECKPOINT.is_file()
        else {}
    )
    asset_items = (
        base.load_checkpoint(ASSET_CHECKPOINT) if ASSET_CHECKPOINT.is_file() else {}
    )
    pass_files = sorted(
        {
            Path(str(record["evidence_path"]))
            for record in geometry_items.values()
            if record.get("status") == "complete"
            and record.get("evidence_path")
            and Path(str(record["evidence_path"])).is_file()
            and Path(str(record["evidence_path"])).resolve().is_relative_to(
                PASS_EVIDENCE_DIR.resolve()
            )
        }
    )

    def digest(path: Path) -> str:
        return base.sha256_file(path) if path.is_file() else ""

    pass_evidence_set = base.sha256_strings(
        f"{path.relative_to(PASS_EVIDENCE_DIR)}:{base.sha256_file(path)}"
        for path in pass_files
    )
    all_artifacts = list(dict.fromkeys([*PROFILE_ARTIFACTS, *artifacts]))
    run_record = {
        "schema_version": RUN_RECORD_SCHEMA_VERSION,
        "run_id": RUN_ID,
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "decision_id": DECISION_ID,
        "implementation_decision_id": IMPLEMENTATION_DECISION_ID,
        "collection_concept_id": COLLECTION_CONCEPT_ID,
        "algorithm_version": ALGORITHM_VERSION,
        "analysis_profile": ANALYSIS_PROFILE,
        "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
        "profile": profile,
        "provenance_counts": {
            VALIDATION_ORIGINAL_CANDIDATES_FIELD: FROZEN_COUNTS.original_candidates,
            VALIDATION_EXCLUDED_CANDIDATES_FIELD: FROZEN_COUNTS.excluded_candidates,
            VALIDATION_RETAINED_CANDIDATES_FIELD: FROZEN_COUNTS.retained_candidates,
            VALIDATION_RETAINED_LINKS_FIELD: FROZEN_COUNTS.retained_city_scene_links,
            VALIDATION_RETAINED_SCENES_FIELD: FROZEN_COUNTS.retained_unique_scenes,
            "asset_checkpoint_items": len(asset_items),
            "geometry_checkpoint_items": len(geometry_items),
            "pass_evidence_files": len(pass_files),
        },
        "provenance_sha256": {
            "candidate_availability_ledger": digest(CANDIDATE_LEDGER),
            "archive_unavailable_pre_geometry_exclusions": digest(EXCLUSION_LEDGER),
            "archive_available_attrition_summary": digest(ATTRITION_SUMMARY),
            "retained_city_scene_links": digest(RETAINED_LINKS),
            "profile_validation": digest(PROFILE_VALIDATION),
            "scene_manifest": digest(SCENE_MANIFEST),
            "asset_checkpoint": digest(ASSET_CHECKPOINT),
            "geometry_checkpoint": digest(GEOMETRY_CHECKPOINT),
            "pass_evidence_set": pass_evidence_set,
            "geometry_summary": digest(GEOMETRY_SUMMARY),
            "cloud_checkpoint": digest(CLOUD_CHECKPOINT),
            "cloud_summary": digest(CLOUD_SUMMARY),
            "combined_validation": digest(COMBINED_VALIDATION_JSON),
        },
        "artifact_sha256": {
            str(path.relative_to(ROOT)): base.sha256_file(path)
            for path in all_artifacts
            if path.is_file()
        },
        "combined_validation": dict(combined),
        "missing_scene_imputation_used": False,
        "missing_scene_zero_coverage_assigned": False,
        "adjacent_scene_substitution_used": False,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
    }
    base._atomic_json(run_record, RUN_RECORD)


_BASE_PATCH_FIELDS = (
    "DECISION_ID",
    "IMPLEMENTATION_DECISION_ID",
    "D0035_ALGORITHM_VERSION",
    "EXPECTED_METADATA_CANDIDATES",
    "EXPECTED_CITY_SCENE_LINKS",
    "EXPECTED_UNIQUE_SCENES",
    "RAW_ROOT",
    "CMR_CACHE",
    "DMRPP_DIR",
    "LOCATOR_DIR",
    "PASS_EVIDENCE_DIR",
    "SCENE_MANIFEST",
    "ASSET_CHECKPOINT",
    "GEOMETRY_CHECKPOINT",
    "CLOUD_MANIFEST",
    "CLOUD_CHECKPOINT",
    "OUTPUT_DIR",
    "GEOMETRY_SUMMARY",
    "PRE_CLOUD_L1B",
    "GEOMETRY_VALIDATION_JSON",
    "GEOMETRY_VALIDATION_CSV",
    "CLOUD_SUMMARY",
    "FINAL_TABLE",
    "COMBINED_VALIDATION_JSON",
    "COMBINED_VALIDATION_CSV",
    "RUN_RECORD",
    "frozen_geometry_targets",
    "_validate_config_seal",
    "_prepare_scene_manifest",
    "_decorate_scene_manifest",
    "resolve_latest_geo_scenes",
    "_run_geometry_passes",
    "_validate_geometry_identity",
    "build_geometry_validation",
    "_canonical_pre_cloud_table",
    "_run_cloud",
    "_combined_validation",
    "_unavailable_geometry_validation",
    "_write_run_record",
)


def _configure_base() -> None:
    """Bind the unchanged engine to D0047 constants and append-only paths."""

    base.DECISION_ID = DECISION_ID
    base.IMPLEMENTATION_DECISION_ID = IMPLEMENTATION_DECISION_ID
    base.D0035_ALGORITHM_VERSION = ALGORITHM_VERSION
    base.EXPECTED_METADATA_CANDIDATES = FROZEN_COUNTS.original_candidates
    base.EXPECTED_CITY_SCENE_LINKS = FROZEN_COUNTS.retained_city_scene_links
    base.EXPECTED_UNIQUE_SCENES = FROZEN_COUNTS.retained_unique_scenes
    base.RAW_ROOT = RAW_ROOT
    base.CMR_CACHE = CMR_CACHE
    base.DMRPP_DIR = DMRPP_DIR
    base.LOCATOR_DIR = LOCATOR_DIR
    base.PASS_EVIDENCE_DIR = PASS_EVIDENCE_DIR
    base.SCENE_MANIFEST = SCENE_MANIFEST
    base.ASSET_CHECKPOINT = ASSET_CHECKPOINT
    base.GEOMETRY_CHECKPOINT = GEOMETRY_CHECKPOINT
    base.CLOUD_MANIFEST = CLOUD_MANIFEST
    base.CLOUD_CHECKPOINT = CLOUD_CHECKPOINT
    base.OUTPUT_DIR = OUTPUT_DIR
    base.GEOMETRY_SUMMARY = GEOMETRY_SUMMARY
    base.PRE_CLOUD_L1B = PRE_CLOUD_D0047
    base.GEOMETRY_VALIDATION_JSON = GEOMETRY_VALIDATION_JSON
    base.GEOMETRY_VALIDATION_CSV = GEOMETRY_VALIDATION_CSV
    base.CLOUD_SUMMARY = CLOUD_SUMMARY
    base.FINAL_TABLE = FINAL_TABLE
    base.COMBINED_VALIDATION_JSON = COMBINED_VALIDATION_JSON
    base.COMBINED_VALIDATION_CSV = COMBINED_VALIDATION_CSV
    base.RUN_RECORD = RUN_RECORD
    base.frozen_geometry_targets = _profile_targets
    base._validate_config_seal = _validate_config_seal
    base._prepare_scene_manifest = _prepare_scene_manifest
    base._decorate_scene_manifest = _decorate_scene_manifest
    base.resolve_latest_geo_scenes = _resolve_latest_geo_scenes
    base._run_geometry_passes = _run_geometry_passes
    base._validate_geometry_identity = _validate_geometry_identity
    base.build_geometry_validation = _build_geometry_validation
    base._canonical_pre_cloud_table = _canonical_pre_cloud_table
    base._run_cloud = _run_cloud
    base._combined_validation = _combined_validation
    base._unavailable_geometry_validation = _unavailable_geometry_validation
    base._write_run_record = _write_run_record


@contextmanager
def _configured_base() -> Iterator[None]:
    """Apply D0047 overrides only for the duration of one adapter operation."""

    previous = {name: getattr(base, name) for name in _BASE_PATCH_FIELDS}
    _configure_base()
    try:
        yield
    finally:
        for name, value in previous.items():
            setattr(base, name, value)


def run_profile_only() -> int:
    """Write only metadata-ledger artifacts; never authenticate or open arrays."""

    with _configured_base():
        config = load_config(ROOT / "configs/v2_cities.toml")
        _validate_config_seal(config)
        if config.study.get("holdout_status") != "UNSELECTED":
            raise ValueError("D0047 requires the holdout to remain UNSELECTED")
        screened, views, missing = _profile_inputs()
        candidates, links, validation = _write_profile_artifacts(
            screened, views, missing
        )
        print(
            "D0047 archive-available profile sealed: "
            f"{len(candidates)} ledger rows; "
            f"{validation[VALIDATION_EXCLUDED_CANDIDATES_FIELD]} excluded; "
            f"{validation[VALIDATION_RETAINED_CANDIDATES_FIELD]} retained; "
            f"{len(links)} retained city-scene links",
            flush=True,
        )
        return 0


def main() -> int:
    if "--profile-only" in sys.argv[1:]:
        if len(sys.argv[1:]) != 1:
            raise ValueError("--profile-only cannot be combined with live-run arguments")
        return run_profile_only()
    if "--stage" in sys.argv[1:]:
        index = sys.argv[1:].index("--stage")
        values = sys.argv[1:]
        if index + 1 < len(values) and values[index + 1] == "profile":
            if len(values) != 2:
                raise ValueError("--stage profile cannot be combined with live-run arguments")
            return run_profile_only()
    with _configured_base():
        print(
            "D0047 archive-available geometry/cloud runner: 942-row ledger, "
            "31 pre-geometry exclusions, 911 retained candidates",
            flush=True,
        )
        return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
