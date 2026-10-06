#!/usr/bin/env python3
"""Plan, fetch, and finalize a frozen cloud-independent Task-1 profile.

This driver never opens an ECOSTRESS temperature layer.  It starts only after
the active profile has definitive ECO_L1B_GEO.002 geometry for every eligible
candidate and every geometry passer has an exhaustive, view-independent cloud
fraction.  D0035 covers the original 942-candidate census; D0047 preserves that
ledger while evaluating its separately named 911-candidate archive-available
cohort.  The driver then fetches the narrow HRRR analysis-hour set bracketing
those passes and writes F2.1--F2.5/T2.1--T2.3 plus the empirical Step-3 template.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from urban_cooling_v2.config import load_config
from urban_cooling_v2.domains import load_domain_features
from urban_cooling_v2.step02_archive_available import (
    ALGORITHM_VERSION as ARCHIVE_AVAILABLE_ALGORITHM_VERSION,
    CANDIDATE_STATUS_COLUMN as ARCHIVE_AVAILABLE_STATUS_COLUMN,
    DECISION_ID as ARCHIVE_AVAILABLE_DECISION_ID,
    EXCLUDED_STATUS as ARCHIVE_AVAILABLE_EXCLUDED_STATUS,
    FROZEN_COUNTS as ARCHIVE_AVAILABLE_COUNTS,
    IMPLEMENTATION_DECISION_ID as ARCHIVE_AVAILABLE_IMPLEMENTATION_DECISION_ID,
    PROFILE_INCLUDED_COLUMN as ARCHIVE_AVAILABLE_INCLUDED_COLUMN,
    RETAINED_STATUS as ARCHIVE_AVAILABLE_RETAINED_STATUS,
    RUN_RECORD_SCHEMA_VERSION as ARCHIVE_AVAILABLE_RUN_RECORD_SCHEMA_VERSION,
    TARGET_SCOPE as ARCHIVE_AVAILABLE_SCOPE,
    VALIDATION_EXCLUDED_CANDIDATES_FIELD,
    VALIDATION_ORIGINAL_CANDIDATES_FIELD,
    VALIDATION_RETAINED_CANDIDATES_FIELD,
    VALIDATION_RETAINED_LINKS_FIELD,
    VALIDATION_RETAINED_SCENES_FIELD,
)
from urban_cooling_v2.step02_catalog import (
    build_step2_deliverables,
    join_acquisition_time_conditions,
    plot_attrition_waterfall,
)
from urban_cooling_v2.step02_l1b_geometry import (
    BOUNDARY_GUARD_DISTANCE_M,
    FULL_SWATH_SHAPE,
    LOCATOR_INFLUENCE_M,
    LOCATOR_MARGIN_PIXELS,
    LOCATOR_STRIDE,
    MAX_ADJACENT_SOURCE_DISPLACEMENT_M,
    NEAR_DOMAIN_PROOF_MODE,
    NO_OVERLAP_LOCATOR_EXPECTED_CELLS,
    NO_OVERLAP_LOCATOR_SHAPE,
    NO_OVERLAP_LOCATOR_UNCERTAINTY_M,
    NO_OVERLAP_PROOF_MODE,
    RADIUS_OF_INFLUENCE_M,
)
from urban_cooling_v2.step02_hrrr_fetch import (
    DEFAULT_MAX_NEW_DATA_BYTES,
    DEFAULT_MIN_FREE_BYTES_AFTER_PEAK,
    build_hrrr_request_manifest,
    estimate_hrrr_subset_downloads,
    fetch_hrrr_domain_weather,
    hrrr_subset_bytes_from_index,
    validate_hrrr_run_seal,
)
from urban_cooling_v2.step03_power import OBSERVED_GEOMETRY_STATUS


ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / "data/processed/v2/task1/step2_quality_screening_l1b_geo"
GEOMETRY_SUMMARY = QUALITY / "geometry_pass_summary.csv"
GEOMETRY_VALIDATION = QUALITY / "geometry_validation.json"
SCREENED_PRE_CLOUD = QUALITY / "passes_quality_screened_pre_cloud_geometry_only.csv"
SCREENED_FINAL = QUALITY / "passes_quality_screened_l1b_geo.csv"
CLOUD_SUMMARY = QUALITY / "cloud_pass_summary.csv"
COMBINED_VALIDATION = QUALITY / "combined_validation.json"
LEGACY_SCREENED = (
    ROOT
    / "data/processed/v2/task1/step2_quality_screening/"
    "passes_quality_screened_pre_cloud.csv"
)
STEP1_AXES = ROOT / "data/processed/v2/step1_condition_axes.csv"
BASE_CATALOGUE = (
    ROOT
    / "data/processed/v2/task1/step2_catalogue_audit/tables/"
    "step2_scene_catalogue_metadata_only.csv"
)
HRRR_ROOT = ROOT / "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo"
HRRR_MANIFEST = (
    ROOT / "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo_manifest.csv"
)
OUTPUT = ROOT / "data/processed/v2/task1/step2_definitive_l1b_geo"
HRRR_STORAGE_ESTIMATE = OUTPUT / "hrrr_storage_estimate.csv"
HRRR_STORAGE_REVIEW = OUTPUT / "hrrr_storage_review.json"
HRRR_SMOKE_INDEX = (
    ROOT
    / "data/raw/v2/weather/hrrr_smoke_grib/hrrr/20230702/"
    "hrrr.t08z.wrfsfcf00.grib2.idx"
)
HRRR_RUN_SEAL = HRRR_ROOT / "hrrr_run_seal.json"

D0035_RAW_ROOT = ROOT / "data/raw/v2/ecostress/l1b_geo_geometry_D0035"
D0035_SCENE_MANIFEST = D0035_RAW_ROOT / "l1b_geo_scene_manifest.csv"
D0035_ASSET_CHECKPOINT = D0035_RAW_ROOT / "locator_dmrpp_checkpoint.json"
D0035_GEOMETRY_CHECKPOINT = D0035_RAW_ROOT / "geometry_scene_checkpoint.json"
D0035_PASS_EVIDENCE_DIR = D0035_RAW_ROOT / "pass_evidence"
D0035_CLOUD_CHECKPOINT = (
    ROOT
    / "data/raw/v2/ecostress/enrichment_assets/"
    "cloud_l1b_geo_D0035_checkpoint.json"
)
D0035_RUN_RECORD = QUALITY / "run_record.json"
STEP2_GATE_RECORD = OUTPUT / "step2_gate_record.json"

D0035_DECISION_ID = "D0035"
D0035_IMPLEMENTATION_DECISION_ID = "D0036"
D0035_GEOMETRY_SOURCE = "ECO_L1B_GEO.002"
D0035_COLLECTION_CONCEPT_ID = "C2076087338-LPCLOUD"
D0035_ALGORITHM_VERSION = "d0035-l1b-dmrpp-pass-stream-v4"
EXPECTED_METADATA_CANDIDATES = 942
EXPECTED_CITY_SCENE_LINKS = 1404
EXPECTED_UNIQUE_SCENES = 1370
D0035_PASS_STATUS = "PASS_D0035_GEOMETRY_AND_EXHAUSTIVE_CLOUD"
STEP2_GATE_RECORD_SCHEMA_VERSION = 1

D0047_PROFILE_NAME = "d0047_archive_available"
D0047_DECISION_ID = ARCHIVE_AVAILABLE_DECISION_ID
D0047_IMPLEMENTATION_DECISION_ID = ARCHIVE_AVAILABLE_IMPLEMENTATION_DECISION_ID
D0047_ALGORITHM_VERSION = ARCHIVE_AVAILABLE_ALGORITHM_VERSION
D0047_PASS_STATUS = "PASS_D0047_ARCHIVE_AVAILABLE_GEOMETRY_AND_EXHAUSTIVE_CLOUD"
D0047_HRRR_RUN_SEAL_STATUS = (
    "PASS_EXACT_HRRR_RUN_SEAL_D0047_ARCHIVE_AVAILABLE"
)
D0047_SCOPE_LABEL = ARCHIVE_AVAILABLE_SCOPE
D0047_COUNT_STATUS = "certified_archive_available_expected_pass_equivalent_floor"
D0047_ORIGINAL_METADATA_CANDIDATES = ARCHIVE_AVAILABLE_COUNTS.original_candidates
D0047_RETAINED_METADATA_CANDIDATES = ARCHIVE_AVAILABLE_COUNTS.retained_candidates
D0047_EXCLUDED_METADATA_CANDIDATES = ARCHIVE_AVAILABLE_COUNTS.excluded_candidates
D0047_EXPECTED_CITY_SCENE_LINKS = ARCHIVE_AVAILABLE_COUNTS.retained_city_scene_links
D0047_EXPECTED_UNIQUE_SCENES = ARCHIVE_AVAILABLE_COUNTS.retained_unique_scenes
D0047_STATUS_COLUMN = ARCHIVE_AVAILABLE_STATUS_COLUMN
D0047_RETAINED_STATUS = ARCHIVE_AVAILABLE_RETAINED_STATUS
D0047_EXCLUDED_STATUS = ARCHIVE_AVAILABLE_EXCLUDED_STATUS
D0048_IMPLEMENTATION_DECISION_ID = "D0048"
D0054_BAND_MODE_DECISION_ID = "D0054"
D0048_ALGORITHM_VERSION = "d0047-archive-available-l1b-dmrpp-pass-stream-v2"
D0048_MAX_UNSAMPLED_PATH_PIXELS = 2 * (LOCATOR_STRIDE - 1)
D0048_NEAR_DOMAIN_PROOF_STATUS = "near_domain_full_resolution_verified"
D0048_NO_OVERLAP_PROOF_STATUS = "verified_no_domain_overlap"
D0048_NO_OVERLAP_ACCEPTANCE_STATUS = "verified_no_overlap_mapped_zero"
D0048_NO_OVERLAP_OBSERVATION_STATUS = "verified_no_domain_overlap"
D0048_TIE_BREAK_RULE = "row_major_lowest_flat_index"
D0048_MAX_SELECTED_CHUNKS = 512
D0048_MAX_RANGE_BYTES_PER_SCENE = 256 * 1024 * 1024
D0048_MAX_BOUNDARY_EXPANSION_ITERATIONS = 64


@dataclass(frozen=True)
class DownstreamProfile:
    """Immutable identity and namespace contract for a Step-2/3 handoff."""

    name: str
    decision_id: str
    implementation_decision_id: str
    algorithm_version: str
    pass_status: str
    scope_label: str
    count_status: str
    original_metadata_candidates: int
    retained_metadata_candidates: int
    excluded_metadata_candidates: int
    expected_city_scene_links: int
    expected_unique_scenes: int
    quality_relative: str
    raw_relative: str
    cloud_checkpoint_relative: str
    hrrr_relative: str
    hrrr_manifest_relative: str
    output_relative: str
    availability_status_column: str | None = None
    retained_status: str | None = None
    excluded_status: str | None = None


D0035_PROFILE = DownstreamProfile(
    name="d0035_exhaustive",
    decision_id="D0035",
    implementation_decision_id="D0036",
    algorithm_version="d0035-l1b-dmrpp-pass-stream-v4",
    pass_status="PASS_D0035_GEOMETRY_AND_EXHAUSTIVE_CLOUD",
    scope_label="exhaustive_942_candidate_D0035",
    count_status="certified_expected_pass_equivalent_floor",
    original_metadata_candidates=942,
    retained_metadata_candidates=942,
    excluded_metadata_candidates=0,
    expected_city_scene_links=1404,
    expected_unique_scenes=1370,
    quality_relative="data/processed/v2/task1/step2_quality_screening_l1b_geo",
    raw_relative="data/raw/v2/ecostress/l1b_geo_geometry_D0035",
    cloud_checkpoint_relative=(
        "data/raw/v2/ecostress/enrichment_assets/"
        "cloud_l1b_geo_D0035_checkpoint.json"
    ),
    hrrr_relative="data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo",
    hrrr_manifest_relative=(
        "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo_manifest.csv"
    ),
    output_relative="data/processed/v2/task1/step2_definitive_l1b_geo",
)

D0047_PROFILE = DownstreamProfile(
    name=D0047_PROFILE_NAME,
    decision_id=D0047_DECISION_ID,
    implementation_decision_id=D0047_IMPLEMENTATION_DECISION_ID,
    algorithm_version=D0047_ALGORITHM_VERSION,
    pass_status=D0047_PASS_STATUS,
    scope_label=D0047_SCOPE_LABEL,
    count_status=D0047_COUNT_STATUS,
    original_metadata_candidates=D0047_ORIGINAL_METADATA_CANDIDATES,
    retained_metadata_candidates=D0047_RETAINED_METADATA_CANDIDATES,
    excluded_metadata_candidates=D0047_EXCLUDED_METADATA_CANDIDATES,
    expected_city_scene_links=D0047_EXPECTED_CITY_SCENE_LINKS,
    expected_unique_scenes=D0047_EXPECTED_UNIQUE_SCENES,
    quality_relative=(
        "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047"
    ),
    raw_relative=(
        "data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available"
    ),
    cloud_checkpoint_relative=(
        "data/raw/v2/ecostress/enrichment_assets/"
        "cloud_l1b_geo_D0047_checkpoint.json"
    ),
    hrrr_relative=(
        "data/raw/v2/weather/"
        "hrrr_exact_acquisition_l1b_geo_D0047_archive_available"
    ),
    hrrr_manifest_relative=(
        "data/raw/v2/weather/"
        "hrrr_exact_acquisition_l1b_geo_D0047_archive_available_manifest.csv"
    ),
    output_relative=(
        "data/processed/v2/task1/"
        "step2_definitive_l1b_geo_D0047_archive_available"
    ),
    availability_status_column=D0047_STATUS_COLUMN,
    retained_status=D0047_RETAINED_STATUS,
    excluded_status=D0047_EXCLUDED_STATUS,
)

ACTIVE_PROFILE = D0035_PROFILE
ORIGINAL_METADATA_CANDIDATES = EXPECTED_METADATA_CANDIDATES
RETAINED_METADATA_CANDIDATES = EXPECTED_METADATA_CANDIDATES
EXCLUDED_METADATA_CANDIDATES = 0
PROFILE_SCOPE_LABEL = D0035_PROFILE.scope_label
PLANNING_COUNT_STATUS = D0035_PROFILE.count_status
AVAILABILITY_LEDGER: Path | None = None
PROFILE_VALIDATION: Path | None = None
D0047_EXCLUSION_SUMMARY: Path | None = None
D0047_ATTRITION_SUMMARY: Path | None = None
D0047_RETAINED_LINKS: Path | None = None


def configure_profile(profile: DownstreamProfile, *, root: Path | None = None) -> None:
    """Activate one frozen namespace before any result-bearing operation."""

    global ACTIVE_PROFILE, QUALITY, GEOMETRY_SUMMARY, GEOMETRY_VALIDATION
    global SCREENED_PRE_CLOUD, SCREENED_FINAL, CLOUD_SUMMARY, COMBINED_VALIDATION
    global HRRR_ROOT, HRRR_MANIFEST, OUTPUT, HRRR_STORAGE_ESTIMATE
    global HRRR_STORAGE_REVIEW, HRRR_RUN_SEAL, D0035_RAW_ROOT
    global D0035_SCENE_MANIFEST, D0035_ASSET_CHECKPOINT
    global D0035_GEOMETRY_CHECKPOINT, D0035_PASS_EVIDENCE_DIR
    global D0035_CLOUD_CHECKPOINT, D0035_RUN_RECORD, STEP2_GATE_RECORD
    global D0035_DECISION_ID, D0035_IMPLEMENTATION_DECISION_ID
    global D0035_ALGORITHM_VERSION, D0035_PASS_STATUS
    global EXPECTED_METADATA_CANDIDATES, EXPECTED_CITY_SCENE_LINKS
    global EXPECTED_UNIQUE_SCENES, ORIGINAL_METADATA_CANDIDATES
    global RETAINED_METADATA_CANDIDATES, EXCLUDED_METADATA_CANDIDATES
    global PROFILE_SCOPE_LABEL, PLANNING_COUNT_STATUS
    global AVAILABILITY_LEDGER, PROFILE_VALIDATION, D0047_EXCLUSION_SUMMARY
    global D0047_ATTRITION_SUMMARY, D0047_RETAINED_LINKS

    base = Path(ROOT if root is None else root).resolve()
    quality = base / profile.quality_relative
    raw = base / profile.raw_relative
    hrrr = base / profile.hrrr_relative
    output = base / profile.output_relative

    ACTIVE_PROFILE = profile
    QUALITY = quality
    GEOMETRY_SUMMARY = quality / "geometry_pass_summary.csv"
    GEOMETRY_VALIDATION = quality / "geometry_validation.json"
    SCREENED_PRE_CLOUD = quality / "passes_quality_screened_pre_cloud_geometry_only.csv"
    SCREENED_FINAL = quality / "passes_quality_screened_l1b_geo.csv"
    CLOUD_SUMMARY = quality / "cloud_pass_summary.csv"
    COMBINED_VALIDATION = quality / "combined_validation.json"
    HRRR_ROOT = hrrr
    HRRR_MANIFEST = base / profile.hrrr_manifest_relative
    OUTPUT = output
    HRRR_STORAGE_ESTIMATE = output / "hrrr_storage_estimate.csv"
    HRRR_STORAGE_REVIEW = output / "hrrr_storage_review.json"
    HRRR_RUN_SEAL = hrrr / "hrrr_run_seal.json"
    D0035_RAW_ROOT = raw
    D0035_SCENE_MANIFEST = raw / "l1b_geo_scene_manifest.csv"
    D0035_ASSET_CHECKPOINT = raw / "locator_dmrpp_checkpoint.json"
    D0035_GEOMETRY_CHECKPOINT = raw / "geometry_scene_checkpoint.json"
    D0035_PASS_EVIDENCE_DIR = raw / "pass_evidence"
    D0035_CLOUD_CHECKPOINT = base / profile.cloud_checkpoint_relative
    D0035_RUN_RECORD = quality / "run_record.json"
    STEP2_GATE_RECORD = output / "step2_gate_record.json"
    D0035_DECISION_ID = profile.decision_id
    D0035_IMPLEMENTATION_DECISION_ID = profile.implementation_decision_id
    D0035_ALGORITHM_VERSION = profile.algorithm_version
    D0035_PASS_STATUS = profile.pass_status
    EXPECTED_METADATA_CANDIDATES = profile.original_metadata_candidates
    EXPECTED_CITY_SCENE_LINKS = profile.expected_city_scene_links
    EXPECTED_UNIQUE_SCENES = profile.expected_unique_scenes
    ORIGINAL_METADATA_CANDIDATES = profile.original_metadata_candidates
    RETAINED_METADATA_CANDIDATES = profile.retained_metadata_candidates
    EXCLUDED_METADATA_CANDIDATES = profile.excluded_metadata_candidates
    PROFILE_SCOPE_LABEL = profile.scope_label
    PLANNING_COUNT_STATUS = profile.count_status
    if profile.excluded_metadata_candidates:
        AVAILABILITY_LEDGER = quality / "candidate_availability_ledger.csv"
        PROFILE_VALIDATION = quality / "profile_validation.json"
        D0047_EXCLUSION_SUMMARY = (
            quality / "archive_unavailable_pre_geometry_exclusions.csv"
        )
        D0047_ATTRITION_SUMMARY = quality / "archive_available_attrition_summary.csv"
        D0047_RETAINED_LINKS = quality / "retained_city_scene_links.csv"
    else:
        AVAILABILITY_LEDGER = None
        PROFILE_VALIDATION = None
        D0047_EXCLUSION_SUMMARY = None
        D0047_ATTRITION_SUMMARY = None
        D0047_RETAINED_LINKS = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_strings(values: Any) -> str:
    payload = "\n".join(sorted(str(value) for value in values)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = str(value).strip()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _load_checkpoint_document(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"D0035 {label} is absent")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        raise RuntimeError(f"D0035 {label} is unreadable") from None
    if document.get("schema_version") != 1 or not isinstance(
        document.get("items"), dict
    ):
        raise RuntimeError(f"D0035 {label} schema is invalid")
    return document


def _true_series(values: pd.Series, *, label: str) -> pd.Series:
    normalized = values.astype(str).str.strip().str.casefold()
    if not normalized.isin({"true", "false", "1", "0"}).all():
        raise ValueError(f"{label} contains values other than true/false")
    return normalized.isin({"true", "1"})


def _orbit_key(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="raise")
    if not np.equal(numeric, np.floor(numeric)).all():
        raise ValueError("orbit values must be integral")
    return numeric.astype("int64").astype(str)


def _utc_series(values: pd.Series, *, label: str) -> pd.Series:
    try:
        parsed = pd.to_datetime(
            values, utc=True, errors="coerce", format="mixed"
        )
    except TypeError:  # pragma: no cover - compatibility with older pandas
        parsed = pd.to_datetime(values, utc=True, errors="coerce")
    parsed = pd.Series(parsed, index=values.index)
    if parsed.isna().any():
        rows = parsed.index[parsed.isna()].tolist()
        raise ValueError(f"{label} contains invalid timestamps at rows {rows[:10]}")
    return parsed


def _candidate_mask(frame: pd.DataFrame) -> pd.Series:
    canonical_column = "quality_candidate_pre_cloud"
    l1b_column = "quality_candidate_pre_cloud_l1b"
    missing = {canonical_column, l1b_column} - set(frame.columns)
    if missing:
        raise ValueError(f"quality screen lacks {sorted(missing)}")
    if ACTIVE_PROFILE == D0047_PROFILE:
        included = _profile_included_mask(frame, label="D0047 candidate table")
        canonical_nullable = _nullable_true_series(
            frame[canonical_column], label=canonical_column
        )
        l1b_nullable = _nullable_true_series(frame[l1b_column], label=l1b_column)
        if (
            canonical_nullable.loc[~included].notna().any()
            or l1b_nullable.loc[~included].notna().any()
            or canonical_nullable.loc[included].isna().any()
            or l1b_nullable.loc[included].isna().any()
            or not canonical_nullable.equals(l1b_nullable)
        ):
            raise RuntimeError(
                "D0047 candidate flags must be null only for pre-geometry exclusions"
            )
        return l1b_nullable.fillna(False).astype(bool)
    canonical = _true_series(frame[canonical_column], label=canonical_column)
    l1b = _true_series(frame[l1b_column], label=l1b_column)
    if not canonical.equals(l1b):
        raise RuntimeError("canonical quality candidate flag differs from D0035 L1B")
    return l1b


def _metadata_mask(frame: pd.DataFrame) -> pd.Series:
    if "metadata_candidate" not in frame:
        return pd.Series(True, index=frame.index)
    return _true_series(frame["metadata_candidate"], label="metadata_candidate")


def _profile_included_mask(frame: pd.DataFrame, *, label: str) -> pd.Series:
    """Return the rows eligible for geometry under the active frozen profile."""

    if ACTIVE_PROFILE.excluded_metadata_candidates == 0:
        return pd.Series(True, index=frame.index, dtype=bool)
    required = {
        ARCHIVE_AVAILABLE_STATUS_COLUMN,
        ARCHIVE_AVAILABLE_INCLUDED_COLUMN,
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{label} lacks D0047 availability fields {sorted(missing)}")
    included = _true_series(
        frame[ARCHIVE_AVAILABLE_INCLUDED_COLUMN],
        label=f"{label} {ARCHIVE_AVAILABLE_INCLUDED_COLUMN}",
    )
    status = frame[ARCHIVE_AVAILABLE_STATUS_COLUMN].astype(str).str.strip()
    expected = included.map(
        {
            True: ARCHIVE_AVAILABLE_RETAINED_STATUS,
            False: ARCHIVE_AVAILABLE_EXCLUDED_STATUS,
        }
    )
    if not status.equals(expected):
        raise RuntimeError(f"{label} has an inconsistent D0047 availability status")
    if (
        len(frame) != ORIGINAL_METADATA_CANDIDATES
        or int(included.sum()) != RETAINED_METADATA_CANDIDATES
        or int((~included).sum()) != EXCLUDED_METADATA_CANDIDATES
    ):
        raise RuntimeError(f"{label} breaks the frozen D0047 candidate census")
    return included


def _nullable_true_series(values: pd.Series, *, label: str) -> pd.Series:
    """Normalize a nullable boolean column without interpreting NA as false."""

    normalized = values.astype("string").str.strip().str.casefold()
    invalid = normalized.notna() & ~normalized.isin({"true", "false", "1", "0"})
    if invalid.any():
        raise ValueError(f"{label} contains values other than true/false/NA")
    return normalized.map(
        {"true": True, "1": True, "false": False, "0": False}
    ).astype("boolean")


def _validate_archive_available_profile_artifacts(
    geometry: pd.DataFrame,
) -> dict[str, Any]:
    """Validate D0047's 942-row ledger and pre-geometry exclusion seal."""

    if ACTIVE_PROFILE != D0047_PROFILE:
        return {}
    if AVAILABILITY_LEDGER is None or PROFILE_VALIDATION is None:
        raise RuntimeError("D0047 profile paths were not configured")
    if not AVAILABILITY_LEDGER.is_file() or not PROFILE_VALIDATION.is_file():
        raise RuntimeError("D0047 availability ledger or profile validation is absent")
    ledger = pd.read_csv(AVAILABILITY_LEDGER)
    profile_validation = json.loads(PROFILE_VALIDATION.read_text(encoding="utf-8"))
    ledger_included = _profile_included_mask(
        ledger, label="D0047 candidate availability ledger"
    )
    geometry_included = _profile_included_mask(
        geometry, label="D0047 geometry summary"
    )
    _assert_same_keys_and_times(
        ledger,
        geometry,
        left_label="D0047 candidate availability ledger",
        right_label="D0047 geometry summary",
    )
    ledger_keyed = _keyed(ledger, label="D0047 candidate availability ledger")
    geometry_keyed = _keyed(geometry, label="D0047 geometry summary")
    availability_check = ledger_keyed[
        [
            "city",
            "orbit_key",
            ARCHIVE_AVAILABLE_STATUS_COLUMN,
            ARCHIVE_AVAILABLE_INCLUDED_COLUMN,
        ]
    ].merge(
        geometry_keyed[
            [
                "city",
                "orbit_key",
                ARCHIVE_AVAILABLE_STATUS_COLUMN,
                ARCHIVE_AVAILABLE_INCLUDED_COLUMN,
            ]
        ],
        on=["city", "orbit_key"],
        suffixes=("_ledger", "_geometry"),
        validate="one_to_one",
    )
    if not availability_check[
        f"{ARCHIVE_AVAILABLE_STATUS_COLUMN}_ledger"
    ].astype(str).equals(
        availability_check[f"{ARCHIVE_AVAILABLE_STATUS_COLUMN}_geometry"].astype(str)
    ):
        raise RuntimeError("D0047 geometry summary changed the availability ledger")
    if not _true_series(
        availability_check[f"{ARCHIVE_AVAILABLE_INCLUDED_COLUMN}_ledger"],
        label="D0047 ledger included flag",
    ).equals(
        _true_series(
            availability_check[f"{ARCHIVE_AVAILABLE_INCLUDED_COLUMN}_geometry"],
            label="D0047 geometry included flag",
        )
    ):
        raise RuntimeError("D0047 geometry summary changed the inclusion flag")

    exact_counts = {
        VALIDATION_ORIGINAL_CANDIDATES_FIELD: ORIGINAL_METADATA_CANDIDATES,
        VALIDATION_EXCLUDED_CANDIDATES_FIELD: EXCLUDED_METADATA_CANDIDATES,
        VALIDATION_RETAINED_CANDIDATES_FIELD: RETAINED_METADATA_CANDIDATES,
        VALIDATION_RETAINED_LINKS_FIELD: EXPECTED_CITY_SCENE_LINKS,
        VALIDATION_RETAINED_SCENES_FIELD: EXPECTED_UNIQUE_SCENES,
    }
    for field, expected in exact_counts.items():
        if int(profile_validation.get(field, -1)) != expected:
            raise RuntimeError(f"D0047 profile validation failed: {field}")
    if (
        profile_validation.get("schema_version") != 1
        or profile_validation.get("decision_id") != D0047_DECISION_ID
        or profile_validation.get("implementation_decision_id")
        != D0047_IMPLEMENTATION_DECISION_ID
        or profile_validation.get("algorithm_version") != D0047_ALGORITHM_VERSION
        or profile_validation.get("target_scope") != D0047_SCOPE_LABEL
        or profile_validation.get("candidate_ledger_complete") is not True
        or profile_validation.get("retained_candidate_keys_exact") is not True
        or profile_validation.get("whole_candidate_exclusion_rule") is not True
        or profile_validation.get("missing_scene_imputation_used") is not False
        or profile_validation.get("missing_scene_zero_coverage_assigned") is not False
        or profile_validation.get("adjacent_scene_substitution_used") is not False
        or profile_validation.get("profile_gate_status")
        != "PASS_D0047_ARCHIVE_AVAILABLE_PROFILE_SEALED"
        or profile_validation.get("lst_opened") is not False
        or profile_validation.get("thermal_opened") is not False
        or profile_validation.get("record_2026_opened") is not False
        or str(profile_validation.get("holdout_status", "")).upper() != "UNSELECTED"
    ):
        raise RuntimeError("D0047 archive-available profile seal is invalid")
    return {
        "candidate_availability_ledger_path": str(
            AVAILABILITY_LEDGER.relative_to(ROOT)
        ),
        "candidate_availability_ledger_sha256": _sha256(AVAILABILITY_LEDGER),
        "profile_validation_path": str(PROFILE_VALIDATION.relative_to(ROOT)),
        "profile_validation_sha256": _sha256(PROFILE_VALIDATION),
    }


def _keyed(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    required = {"city", "orbit", "acquisition_utc"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{label} lacks {sorted(missing)}")
    keyed = frame.copy()
    keyed["city"] = keyed["city"].astype(str)
    keyed["orbit_key"] = _orbit_key(keyed["orbit"])
    if keyed.duplicated(["city", "orbit_key"]).any():
        raise ValueError(f"{label} is not unique by city/orbit")
    return keyed


def _assert_same_keys_and_times(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    left_label: str,
    right_label: str,
) -> None:
    left_keyed = _keyed(left, label=left_label)
    right_keyed = _keyed(right, label=right_label)
    left_keys = set(
        left_keyed[["city", "orbit_key"]].itertuples(index=False, name=None)
    )
    right_keys = set(
        right_keyed[["city", "orbit_key"]].itertuples(index=False, name=None)
    )
    if left_keys != right_keys:
        raise RuntimeError(f"{left_label} and {right_label} keys differ")
    time_check = left_keyed[["city", "orbit_key", "acquisition_utc"]].merge(
        right_keyed[["city", "orbit_key", "acquisition_utc"]],
        on=["city", "orbit_key"],
        how="inner",
        suffixes=("_left", "_right"),
        validate="one_to_one",
    )
    left_time = _utc_series(
        time_check["acquisition_utc_left"], label=f"{left_label} acquisition_utc"
    )
    right_time = _utc_series(
        time_check["acquisition_utc_right"], label=f"{right_label} acquisition_utc"
    )
    if not left_time.equals(right_time):
        raise RuntimeError(
            f"{left_label} and {right_label} acquisition timestamps differ"
        )


def _canonicalize_l1b_screen(frame: pd.DataFrame) -> pd.DataFrame:
    """Make generic Step-2 columns explicitly use the D0035 L1B geometry."""

    screened = frame.copy()
    candidate = _candidate_mask(screened)
    if ACTIVE_PROFILE == D0047_PROFILE:
        included = _profile_included_mask(screened, label="D0047 canonical screen")
        near_nadir = pd.Series(pd.NA, index=screened.index, dtype="boolean")
        near_nadir.loc[included] = candidate.loc[included].to_numpy(bool)
        screened["near_nadir"] = near_nadir
    else:
        screened["near_nadir"] = candidate.to_numpy()
    screened["n_domain_pixels"] = pd.to_numeric(
        screened["l1b_geometry_domain_cells"], errors="raise"
    )
    screened["n_view_valid_pixels"] = pd.to_numeric(
        screened["l1b_geometry_covered_cells"], errors="raise"
    )
    screened["view_valid_fraction"] = pd.to_numeric(
        screened["l1b_geometry_coverage_fraction"], errors="raise"
    )
    screened["view_zenith_abs_p95_deg"] = pd.to_numeric(
        screened["l1b_view_zenith_abs_p95_deg"], errors="coerce"
    )
    screened["view_screen_status"] = screened["l1b_geometry_status"].astype(str)
    return screened


def _summary_value_matches(left: Any, right: Any, *, field: str) -> bool:
    if field == "acquisition_utc":
        try:
            return pd.Timestamp(left) == pd.Timestamp(right)
        except (TypeError, ValueError):
            return False
    if isinstance(left, (bool, np.bool_)) or isinstance(right, (bool, np.bool_)):
        try:
            return bool(left) == bool(right)
        except (TypeError, ValueError):
            return False
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float, np.integer, np.floating)) or isinstance(
        right, (int, float, np.integer, np.floating)
    ):
        try:
            return bool(
                np.isclose(
                    float(left),
                    float(right),
                    rtol=0,
                    atol=1e-12,
                    equal_nan=True,
                )
            )
        except (TypeError, ValueError):
            return False
    return str(left) == str(right)


def _validate_d0035_provenance(
    geometry: pd.DataFrame,
    combined_validation: dict[str, Any],
) -> dict[str, Any]:
    """Recompute the full current D0035 evidence chain before finalization."""

    required_files = {
        "scene_manifest": D0035_SCENE_MANIFEST,
        "asset_checkpoint": D0035_ASSET_CHECKPOINT,
        "geometry_checkpoint": D0035_GEOMETRY_CHECKPOINT,
        "geometry_summary": GEOMETRY_SUMMARY,
        "cloud_checkpoint": D0035_CLOUD_CHECKPOINT,
        "cloud_summary": CLOUD_SUMMARY,
        "combined_validation": COMBINED_VALIDATION,
        "run_record": D0035_RUN_RECORD,
    }
    absent = [name for name, path in required_files.items() if not path.is_file()]
    if absent:
        raise RuntimeError(f"D0035 provenance artifacts are absent: {sorted(absent)}")

    try:
        run_record = json.loads(D0035_RUN_RECORD.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        raise RuntimeError("D0035 run record is unreadable") from None
    if (
        run_record.get("schema_version") != 2
        or run_record.get("decision_id") != D0035_DECISION_ID
        or run_record.get("implementation_decision_id")
        != D0035_IMPLEMENTATION_DECISION_ID
        or run_record.get("collection_concept_id")
        != D0035_COLLECTION_CONCEPT_ID
        or run_record.get("algorithm_version") != D0035_ALGORITHM_VERSION
    ):
        raise RuntimeError("D0035 run record identity or algorithm is stale")
    if (
        run_record.get("lst_opened") is not False
        or run_record.get("thermal_opened") is not False
        or run_record.get("record_2026_opened") is not False
        or str(run_record.get("holdout_status", "")).upper() != "UNSELECTED"
    ):
        raise RuntimeError("D0035 run-record thermal/2026/holdout seals are broken")
    if run_record.get("combined_validation") != combined_validation:
        raise RuntimeError("D0035 run record embeds a stale combined validation")

    manifest = pd.read_csv(D0035_SCENE_MANIFEST)
    manifest_required = {
        "orbit",
        "scene",
        "granule_id",
        "cities",
        "status",
        "decision_id",
        "collection_short_name",
        "collection_version",
        "collection_concept_id",
        "cmr_record_sha256",
    }
    missing_manifest = manifest_required - set(manifest.columns)
    if missing_manifest:
        raise RuntimeError(
            f"D0035 scene manifest lacks {sorted(missing_manifest)}"
        )
    if (
        len(manifest) != EXPECTED_UNIQUE_SCENES
        or manifest.duplicated(["orbit", "scene"]).any()
        or manifest["granule_id"].astype(str).duplicated().any()
        or not manifest["status"].astype(str).eq("available").all()
        or not manifest["decision_id"].astype(str).eq(D0035_DECISION_ID).all()
        or not manifest["collection_short_name"].astype(str).eq("ECO_L1B_GEO").all()
        or not manifest["collection_version"].astype(str).str.zfill(3).eq("002").all()
        or not manifest["collection_concept_id"]
        .astype(str)
        .eq(D0035_COLLECTION_CONCEPT_ID)
        .all()
        or not manifest["cmr_record_sha256"]
        .astype(str)
        .str.fullmatch(r"[0-9a-f]{64}")
        .all()
    ):
        raise RuntimeError("D0035 scene-manifest identity census is stale")

    manifest_links: set[tuple[str, int, int, str]] = set()
    for row in manifest.to_dict("records"):
        cities = tuple(filter(None, str(row["cities"]).split(";")))
        if not cities or tuple(sorted(set(cities))) != cities:
            raise RuntimeError("D0035 scene manifest has a noncanonical city binding")
        for city in cities:
            manifest_links.add(
                (
                    city,
                    int(row["orbit"]),
                    int(row["scene"]),
                    str(row["granule_id"]),
                )
            )
    if len(manifest_links) != EXPECTED_CITY_SCENE_LINKS:
        raise RuntimeError("D0035 scene manifest city/scene link census is stale")

    asset_document = _load_checkpoint_document(
        D0035_ASSET_CHECKPOINT, label="metadata-asset checkpoint"
    )
    asset_items = asset_document["items"]
    manifest_by_granule = {
        str(row["granule_id"]): row for row in manifest.to_dict("records")
    }
    if set(asset_items) != set(manifest_by_granule):
        raise RuntimeError("D0035 metadata-asset checkpoint key census is stale")
    for granule, record in asset_items.items():
        manifest_row = manifest_by_granule[granule]
        if (
            record.get("status") != "complete"
            or record.get("algorithm_version") != D0035_ALGORITHM_VERSION
            or record.get("collection_concept_id")
            != D0035_COLLECTION_CONCEPT_ID
            or record.get("cmr_record_sha256")
            != str(manifest_row["cmr_record_sha256"])
            or not _is_sha256(record.get("dmrpp_sha256"))
            or not _is_sha256(record.get("locator_sha256"))
        ):
            raise RuntimeError(
                f"D0035 metadata-asset checkpoint is stale for {granule}"
            )

    geometry_document = _load_checkpoint_document(
        D0035_GEOMETRY_CHECKPOINT, label="geometry checkpoint"
    )
    geometry_items = geometry_document["items"]
    geometry_keyed = _keyed(geometry, label="D0035 geometry summary")
    expected_geometry_ids = {
        f"{row.city}:{int(row.orbit):05d}"
        for row in geometry[["city", "orbit"]].itertuples(index=False)
    }
    if (
        len(geometry) != EXPECTED_METADATA_CANDIDATES
        or len(geometry_items) != EXPECTED_METADATA_CANDIDATES
        or set(geometry_items) != expected_geometry_ids
    ):
        raise RuntimeError("D0035 geometry checkpoint census is stale")
    geometry_rows = {
        (str(row["city"]), str(row["orbit_key"])): row
        for row in geometry_keyed.to_dict("records")
    }

    checkpoint_files: set[Path] = set()
    evidence_links: set[tuple[str, int, int, str]] = set()
    evidence_set_inputs: list[str] = []
    for item_id, record in sorted(geometry_items.items()):
        if (
            record.get("status") != "complete"
            or record.get("boundary_verified") is not True
            or not _is_sha256(record.get("binding_sha256"))
            or not _is_sha256(record.get("evidence_sha256"))
            or not record.get("evidence_path")
        ):
            raise RuntimeError(f"D0035 geometry checkpoint is stale for {item_id}")
        path = Path(str(record["evidence_path"]))
        if not path.is_file():
            raise RuntimeError(f"D0035 pass evidence is absent for {item_id}")
        try:
            relative = path.resolve().relative_to(D0035_PASS_EVIDENCE_DIR.resolve())
        except ValueError:
            raise RuntimeError(
                f"D0035 pass evidence escaped its frozen root for {item_id}"
            ) from None
        evidence_sha = _sha256(path)
        if evidence_sha != record["evidence_sha256"]:
            raise RuntimeError(f"D0035 pass evidence hash is stale for {item_id}")
        checkpoint_files.add(path.resolve())
        evidence_set_inputs.append(f"{relative}:{evidence_sha}")
        try:
            evidence = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            raise RuntimeError(f"D0035 pass evidence is unreadable for {item_id}") from None
        binding = evidence.get("binding")
        scenes = evidence.get("scene_evidence")
        summary = evidence.get("summary")
        if not isinstance(binding, dict) or not isinstance(scenes, list) or not isinstance(
            summary, dict
        ):
            raise RuntimeError(f"D0035 pass evidence schema is stale for {item_id}")
        city = str(evidence.get("city"))
        orbit = int(evidence.get("orbit", -1))
        expected_path = D0035_PASS_EVIDENCE_DIR / city / f"{orbit:05d}.json"
        computed_binding_sha = _json_sha256(binding)
        if (
            expected_path.resolve() != path.resolve()
            or item_id != f"{city}:{orbit:05d}"
            or evidence.get("status") != "complete"
            or evidence.get("decision_id") != D0035_DECISION_ID
            or evidence.get("algorithm_version") != D0035_ALGORITHM_VERSION
            or evidence.get("boundary_verified") is not True
            or evidence.get("binding_sha256") != computed_binding_sha
            or record.get("binding_sha256") != computed_binding_sha
            or binding.get("algorithm_version") != D0035_ALGORITHM_VERSION
            or binding.get("decision_id") != D0035_DECISION_ID
            or str(binding.get("city")) != city
            or int(binding.get("orbit", -1)) != orbit
            or not scenes
            or not all(item.get("boundary_verified") is True for item in scenes)
            or evidence.get("lst_opened") is not False
            or evidence.get("thermal_opened") is not False
            or evidence.get("record_2026_opened") is not False
            or str(evidence.get("holdout_status", "")).upper() != "UNSELECTED"
        ):
            raise RuntimeError(f"D0035 pass evidence binding is stale for {item_id}")
        scene_bindings = binding.get("scene_bindings")
        if not isinstance(scene_bindings, list) or not scene_bindings:
            raise RuntimeError(f"D0035 pass evidence has no scene binding for {item_id}")
        for scene in scene_bindings:
            if (
                scene.get("algorithm_version") != D0035_ALGORITHM_VERSION
                or scene.get("collection_concept_id")
                != D0035_COLLECTION_CONCEPT_ID
                or not _is_sha256(scene.get("dmrpp_sha256"))
                or not _is_sha256(scene.get("locator_sha256"))
            ):
                raise RuntimeError(
                    f"D0035 scene binding is stale for {item_id}"
                )
            evidence_links.add(
                (
                    city,
                    int(scene["orbit"]),
                    int(scene["scene"]),
                    str(scene["granule_id"]),
                )
            )
        if int(summary.get("n_l1b_geo_scenes", -1)) != len(scene_bindings):
            raise RuntimeError(f"D0035 scene count is stale for {item_id}")
        geometry_row = geometry_rows.get((city, str(orbit)))
        if geometry_row is None or set(summary).difference(geometry_row):
            raise RuntimeError(f"D0035 geometry summary lacks evidence fields for {item_id}")
        for field, value in summary.items():
            if not _summary_value_matches(value, geometry_row[field], field=field):
                raise RuntimeError(
                    f"D0035 geometry summary is stale for {item_id}: {field}"
                )

    discovered_files = {
        path.resolve() for path in D0035_PASS_EVIDENCE_DIR.rglob("*.json")
    }
    if discovered_files != checkpoint_files or len(discovered_files) != EXPECTED_METADATA_CANDIDATES:
        raise RuntimeError("D0035 pass-evidence file census is stale")
    if evidence_links != manifest_links or len(evidence_links) != EXPECTED_CITY_SCENE_LINKS:
        raise RuntimeError("D0035 pass evidence and scene manifest bindings differ")
    scene_count = pd.to_numeric(geometry["n_l1b_geo_scenes"], errors="raise")
    if (
        not np.equal(scene_count, np.floor(scene_count)).all()
        or int(scene_count.sum()) != EXPECTED_CITY_SCENE_LINKS
    ):
        raise RuntimeError("D0035 geometry-summary scene count is stale")

    current_counts = {
        "metadata_candidates": EXPECTED_METADATA_CANDIDATES,
        "city_scene_links": EXPECTED_CITY_SCENE_LINKS,
        "unique_scenes": EXPECTED_UNIQUE_SCENES,
        "asset_checkpoint_items": len(asset_items),
        "geometry_checkpoint_items": len(geometry_items),
        "pass_evidence_files": len(discovered_files),
    }
    current_hashes = {
        "scene_manifest": _sha256(D0035_SCENE_MANIFEST),
        "asset_checkpoint": _sha256(D0035_ASSET_CHECKPOINT),
        "geometry_checkpoint": _sha256(D0035_GEOMETRY_CHECKPOINT),
        "pass_evidence_set": _sha256_strings(evidence_set_inputs),
        "geometry_summary": _sha256(GEOMETRY_SUMMARY),
        "cloud_checkpoint": _sha256(D0035_CLOUD_CHECKPOINT),
        "cloud_summary": _sha256(CLOUD_SUMMARY),
        "combined_validation": _sha256(COMBINED_VALIDATION),
    }
    if run_record.get("provenance_counts") != current_counts:
        raise RuntimeError("D0035 run-record provenance counts are stale")
    if run_record.get("provenance_sha256") != current_hashes:
        raise RuntimeError("D0035 run-record provenance hashes are stale")

    artifact_hashes = run_record.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict) or not artifact_hashes:
        raise RuntimeError("D0035 run record has no artifact hash ledger")
    for relative_path, expected_hash in artifact_hashes.items():
        path = (ROOT / str(relative_path)).resolve()
        try:
            path.relative_to(ROOT.resolve())
        except ValueError:
            raise RuntimeError("D0035 run-record artifact path escaped the repository") from None
        if not path.is_file() or _sha256(path) != expected_hash:
            raise RuntimeError(
                f"D0035 run-record artifact hash is stale: {relative_path}"
            )
    return {
        "run_record_path": str(D0035_RUN_RECORD.relative_to(ROOT)),
        "run_record_sha256": _sha256(D0035_RUN_RECORD),
        "algorithm_version": D0035_ALGORITHM_VERSION,
        "provenance_counts": current_counts,
        "provenance_sha256": current_hashes,
    }


def _d0048_int(value: Any, *, field: str, item_id: str) -> int:
    """Return an exact JSON integer for one fail-closed D0048 proof field."""

    if isinstance(value, (bool, np.bool_)):
        raise RuntimeError(f"D0048 proof is stale for {item_id}: {field}")
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise RuntimeError(f"D0048 proof is stale for {item_id}: {field}") from None
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise RuntimeError(f"D0048 proof is stale for {item_id}: {field}")
    return int(numeric)


def _d0048_float(value: Any, *, field: str, item_id: str) -> float:
    """Return one finite numeric D0048 proof field without boolean coercion."""

    if isinstance(value, (bool, np.bool_)):
        raise RuntimeError(f"D0048 proof is stale for {item_id}: {field}")
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise RuntimeError(f"D0048 proof is stale for {item_id}: {field}") from None
    if not math.isfinite(numeric):
        raise RuntimeError(f"D0048 proof is stale for {item_id}: {field}")
    return numeric


def _validate_d0048_geometry_evidence(
    binding: dict[str, Any],
    scenes: list[Any],
    *,
    item_id: str,
) -> None:
    """Validate every frozen D0048 selector and verified-no-overlap quantity.

    Ordinary near-domain scenes retain the original D0035 mapping path.  The
    extra proof quantities below are required only when ``proof_mode`` records
    D0048's global-locator fallback; no fallback field can silently weaken the
    normal path.
    """

    if (
        D0047_ALGORITHM_VERSION != D0048_ALGORITHM_VERSION
        or D0047_IMPLEMENTATION_DECISION_ID != D0048_IMPLEMENTATION_DECISION_ID
        or D0048_MAX_UNSAMPLED_PATH_PIXELS != 62
        or NO_OVERLAP_LOCATOR_UNCERTAINTY_M
        != D0048_MAX_UNSAMPLED_PATH_PIXELS
        * MAX_ADJACENT_SOURCE_DISPLACEMENT_M
    ):
        raise RuntimeError("D0048 algorithm or frozen mechanics constants are stale")

    exact_binding = {
        "implementation_decision_id": D0048_IMPLEMENTATION_DECISION_ID,
        "algorithm_version": D0048_ALGORITHM_VERSION,
        "locator_stride": LOCATOR_STRIDE,
        "source_margin_pixels": LOCATOR_MARGIN_PIXELS,
        "radius_m": RADIUS_OF_INFLUENCE_M,
        "boundary_guard_m": BOUNDARY_GUARD_DISTANCE_M,
        "max_selected_chunks": D0048_MAX_SELECTED_CHUNKS,
        "max_range_bytes_per_scene": D0048_MAX_RANGE_BYTES_PER_SCENE,
        "verified_no_overlap_locator_shape": list(NO_OVERLAP_LOCATOR_SHAPE),
        "verified_no_overlap_locator_expected_cells": (
            NO_OVERLAP_LOCATOR_EXPECTED_CELLS
        ),
        "verified_no_overlap_locator_stride": LOCATOR_STRIDE,
        "verified_no_overlap_locator_stride_minus_one_pixels": LOCATOR_STRIDE - 1,
        "verified_no_overlap_locator_influence_m": LOCATOR_INFLUENCE_M,
        "verified_no_overlap_max_unsampled_path_pixels": (
            D0048_MAX_UNSAMPLED_PATH_PIXELS
        ),
        "verified_no_overlap_maximum_adjacent_source_displacement_m": (
            MAX_ADJACENT_SOURCE_DISPLACEMENT_M
        ),
        "verified_no_overlap_locator_uncertainty_m": (
            NO_OVERLAP_LOCATOR_UNCERTAINTY_M
        ),
        "verified_no_overlap_boundary_guard_m": BOUNDARY_GUARD_DISTANCE_M,
        "verified_no_overlap_source_margin_pixels": LOCATOR_MARGIN_PIXELS,
        "verified_no_overlap_tie_break_rule": D0048_TIE_BREAK_RULE,
    }
    for field, expected in exact_binding.items():
        if binding.get(field) != expected:
            raise RuntimeError(f"D0048 binding is stale for {item_id}: {field}")

    scene_bindings = binding.get("scene_bindings")
    if not isinstance(scene_bindings, list) or len(scene_bindings) != len(scenes):
        raise RuntimeError(f"D0048 scene-evidence census is stale for {item_id}")
    bindings_by_granule = {
        str(scene.get("granule_id")): scene
        for scene in scene_bindings
        if isinstance(scene, dict) and scene.get("granule_id")
    }
    if len(bindings_by_granule) != len(scene_bindings):
        raise RuntimeError(f"D0048 scene bindings are not unique for {item_id}")

    for scene in scenes:
        if not isinstance(scene, dict):
            raise RuntimeError(f"D0048 scene evidence is stale for {item_id}")
        granule = str(scene.get("granule_id", ""))
        scene_binding = bindings_by_granule.get(granule)
        if scene_binding is None or any(
            scene.get(field) != scene_binding.get(field)
            for field in (
                "orbit",
                "scene",
                "granule_id",
                "cmr_record_sha256",
                "dmrpp_sha256",
                "locator_sha256",
            )
        ):
            raise RuntimeError(
                f"D0048 scene evidence is not checksum-bound for {item_id}: {granule}"
            )
        mode = scene.get("proof_mode")
        if mode not in {NEAR_DOMAIN_PROOF_MODE, NO_OVERLAP_PROOF_MODE}:
            raise RuntimeError(
                f"D0048 scene selection mode is stale for {item_id}: {granule}"
            )
        if (
            scene.get("full_resolution_boundary_verified") is not True
            or scene.get("boundary_verified") is not True
            or scene.get("verified_no_overlap_zero_imputed") is not False
            or scene.get("missing_scene_zero_coverage_assigned") is not False
            or scene.get("missing_scene_substitution_used") is not False
        ):
            raise RuntimeError(
                f"D0048 boundary or no-substitution proof is stale for {item_id}: "
                f"{granule}"
            )
        if mode == NEAR_DOMAIN_PROOF_MODE:
            if (
                scene.get("proof_status") != D0048_NEAR_DOMAIN_PROOF_STATUS
                or scene.get("proof_acceptance_status")
                != "ordinary_near_domain_mapping"
                or scene.get("geometry_observation_status")
                != "mapped_near_domain_geometry"
                or scene.get("verified_no_overlap_mapped_zero") is not False
            ):
                raise RuntimeError(
                    f"D0048 ordinary geometry-path proof is stale for {item_id}: "
                    f"{granule}"
                )
            continue

        exact_scene = {
            "proof_status": D0048_NO_OVERLAP_PROOF_STATUS,
            "proof_acceptance_status": D0048_NO_OVERLAP_ACCEPTANCE_STATUS,
            "geometry_observation_status": D0048_NO_OVERLAP_OBSERVATION_STATUS,
            "locator_shape": list(NO_OVERLAP_LOCATOR_SHAPE),
            "locator_stride": LOCATOR_STRIDE,
            "locator_stride_minus_one_pixels": LOCATOR_STRIDE - 1,
            "locator_influence_m": LOCATOR_INFLUENCE_M,
            "locator_expected_count": NO_OVERLAP_LOCATOR_EXPECTED_CELLS,
            "locator_max_unsampled_path_pixels": D0048_MAX_UNSAMPLED_PATH_PIXELS,
            "maximum_adjacent_source_displacement_m": (
                MAX_ADJACENT_SOURCE_DISPLACEMENT_M
            ),
            "locator_uncertainty_bound_m": NO_OVERLAP_LOCATOR_UNCERTAINTY_M,
            "boundary_guard_distance_m": BOUNDARY_GUARD_DISTANCE_M,
            "seed_source_margin_pixels": LOCATOR_MARGIN_PIXELS,
            "row_major_tie_breaking": True,
            "verified_no_overlap_mapped_zero": True,
            "verified_no_overlap_zero_imputed": False,
            "missing_scene_zero_coverage_assigned": False,
            "missing_scene_substitution_used": False,
        }
        for field, expected in exact_scene.items():
            if scene.get(field) != expected:
                raise RuntimeError(
                    f"D0048 no-overlap proof is stale for {item_id}: "
                    f"{granule}:{field}"
                )
        valid_count = _d0048_int(
            scene.get("locator_valid_count"),
            field="locator_valid_count",
            item_id=item_id,
        )
        if valid_count != NO_OVERLAP_LOCATOR_EXPECTED_CELLS:
            raise RuntimeError(
                f"D0048 no-overlap locator is not fully valid for {item_id}: {granule}"
            )
        minimum = _d0048_float(
            scene.get("locator_minimum_domain_distance_m"),
            field="locator_minimum_domain_distance_m",
            item_id=item_id,
        )
        lower_bound = _d0048_float(
            scene.get("locator_no_overlap_lower_bound_m"),
            field="locator_no_overlap_lower_bound_m",
            item_id=item_id,
        )
        if (
            not math.isclose(
                lower_bound,
                minimum - NO_OVERLAP_LOCATOR_UNCERTAINTY_M,
                rel_tol=0,
                abs_tol=1e-9,
            )
            or not lower_bound > BOUNDARY_GUARD_DISTANCE_M
        ):
            raise RuntimeError(
                f"D0048 no-overlap lower-bound inequality failed for {item_id}: "
                f"{granule}"
            )

        seeded_points = scene.get("seeded_locator_points")
        if not isinstance(seeded_points, list) or not seeded_points:
            raise RuntimeError(
                f"D0048 global locator seeds are absent for {item_id}: {granule}"
            )
        if not all(isinstance(point, dict) for point in seeded_points):
            raise RuntimeError(
                f"D0048 global locator seed is stale for {item_id}: {granule}"
            )
        target_names = [str(point.get("target_grid", "")) for point in seeded_points]
        if (
            any(not name for name in target_names)
            or len(set(target_names)) != len(target_names)
            or target_names != sorted(target_names)
        ):
            raise RuntimeError(
                f"D0048 global locator seed order is stale for {item_id}: {granule}"
            )
        seed_distances: list[float] = []
        for point in seeded_points:
            flat = _d0048_int(
                point.get("locator_flat_index"),
                field="locator_flat_index",
                item_id=item_id,
            )
            row = _d0048_int(
                point.get("locator_row"), field="locator_row", item_id=item_id
            )
            column = _d0048_int(
                point.get("locator_col"), field="locator_col", item_id=item_id
            )
            source_row = _d0048_int(
                point.get("source_row"), field="source_row", item_id=item_id
            )
            source_column = _d0048_int(
                point.get("source_col"), field="source_col", item_id=item_id
            )
            if (
                not 0 <= row < NO_OVERLAP_LOCATOR_SHAPE[0]
                or not 0 <= column < NO_OVERLAP_LOCATOR_SHAPE[1]
                or flat != row * NO_OVERLAP_LOCATOR_SHAPE[1] + column
                or source_row != row * LOCATOR_STRIDE
                or source_column != column * LOCATOR_STRIDE
                or not 0 <= source_row < FULL_SWATH_SHAPE[0]
                or not 0 <= source_column < FULL_SWATH_SHAPE[1]
            ):
                raise RuntimeError(
                    f"D0048 row-major locator binding failed for {item_id}: {granule}"
                )
            latitude = _d0048_float(
                point.get("latitude"), field="latitude", item_id=item_id
            )
            longitude = _d0048_float(
                point.get("longitude"), field="longitude", item_id=item_id
            )
            if (
                not -90 <= latitude <= 90
                or not -180 <= longitude <= 180
                or (latitude == 0 and longitude == 0)
            ):
                raise RuntimeError(
                    f"D0048 global locator coordinate is stale for {item_id}: {granule}"
                )
            seed_distance = _d0048_float(
                point.get("minimum_domain_distance_m"),
                field="minimum_domain_distance_m",
                item_id=item_id,
            )
            if seed_distance < 0:
                raise RuntimeError(
                    f"D0048 global locator distance is stale for {item_id}: {granule}"
                )
            seed_distances.append(seed_distance)
        if not math.isclose(
            min(seed_distances), minimum, rel_tol=0, abs_tol=1e-9
        ):
            raise RuntimeError(
                f"D0048 global-minimum locator binding failed for {item_id}: {granule}"
            )

        seeded_chunks = scene.get("seeded_chunk_coords")
        if not isinstance(seeded_chunks, list) or not seeded_chunks:
            raise RuntimeError(
                f"D0048 seeded chunk proof is absent for {item_id}: {granule}"
            )
        chunk_coords: list[tuple[int, int]] = []
        for coord in seeded_chunks:
            if not isinstance(coord, list) or len(coord) != 2:
                raise RuntimeError(
                    f"D0048 seeded chunk proof is stale for {item_id}: {granule}"
                )
            chunk_coord = (
                _d0048_int(coord[0], field="seeded_chunk_row", item_id=item_id),
                _d0048_int(coord[1], field="seeded_chunk_col", item_id=item_id),
            )
            if min(chunk_coord) < 0:
                raise RuntimeError(
                    f"D0048 seeded chunk proof is stale for {item_id}: {granule}"
                )
            chunk_coords.append(chunk_coord)
        seeded_count = _d0048_int(
            scene.get("seeded_chunk_count"),
            field="seeded_chunk_count",
            item_id=item_id,
        )
        initial_count = _d0048_int(
            scene.get("initial_chunk_count"),
            field="initial_chunk_count",
            item_id=item_id,
        )
        final_count = _d0048_int(
            scene.get("final_chunk_count"),
            field="final_chunk_count",
            item_id=item_id,
        )
        if (
            chunk_coords != sorted(set(chunk_coords))
            or seeded_count != len(chunk_coords)
            or initial_count != seeded_count
            or not 0 < initial_count <= final_count <= D0048_MAX_SELECTED_CHUNKS
        ):
            raise RuntimeError(
                f"D0048 64-pixel seed/chunk proof is stale for {item_id}: {granule}"
            )
        iterations = _d0048_int(
            scene.get("boundary_expansion_iterations"),
            field="boundary_expansion_iterations",
            item_id=item_id,
        )
        boundary_minimum = _d0048_float(
            scene.get("boundary_minimum_domain_distance_m"),
            field="boundary_minimum_domain_distance_m",
            item_id=item_id,
        )
        boundary_edges = _d0048_int(
            scene.get("boundary_edges_tested"),
            field="boundary_edges_tested",
            item_id=item_id,
        )
        range_bytes = _d0048_int(
            scene.get("range_bytes_transferred"),
            field="range_bytes_transferred",
            item_id=item_id,
        )
        if (
            not 1 <= iterations <= D0048_MAX_BOUNDARY_EXPANSION_ITERATIONS
            or boundary_edges <= 0
            or not boundary_minimum > BOUNDARY_GUARD_DISTANCE_M
            or _d0048_int(
                scene.get("mapped_target_cell_count"),
                field="mapped_target_cell_count",
                item_id=item_id,
            )
            != 0
            or not 0 < range_bytes <= D0048_MAX_RANGE_BYTES_PER_SCENE
        ):
            raise RuntimeError(
                f"D0048 full-resolution zero-map proof failed for {item_id}: {granule}"
            )


def _validate_d0047_provenance(
    geometry: pd.DataFrame,
    combined_validation: dict[str, Any],
) -> dict[str, Any]:
    """Recompute the D0047 archive-available evidence chain without weakening D0035."""

    if ACTIVE_PROFILE != D0047_PROFILE:
        raise RuntimeError("D0047 provenance validator requires the D0047 profile")
    profile_binding = _validate_archive_available_profile_artifacts(geometry)
    if any(
        path is None
        for path in (
            D0047_EXCLUSION_SUMMARY,
            D0047_ATTRITION_SUMMARY,
            D0047_RETAINED_LINKS,
        )
    ):
        raise RuntimeError("D0047 attrition paths were not configured")
    required_files = {
        "scene_manifest": D0035_SCENE_MANIFEST,
        "asset_checkpoint": D0035_ASSET_CHECKPOINT,
        "geometry_checkpoint": D0035_GEOMETRY_CHECKPOINT,
        "geometry_summary": GEOMETRY_SUMMARY,
        "cloud_checkpoint": D0035_CLOUD_CHECKPOINT,
        "cloud_summary": CLOUD_SUMMARY,
        "combined_validation": COMBINED_VALIDATION,
        "run_record": D0035_RUN_RECORD,
        "availability_ledger": AVAILABILITY_LEDGER,
        "profile_validation": PROFILE_VALIDATION,
        "exclusion_summary": D0047_EXCLUSION_SUMMARY,
        "attrition_summary": D0047_ATTRITION_SUMMARY,
        "retained_links": D0047_RETAINED_LINKS,
    }
    absent = [
        name for name, path in required_files.items() if path is None or not path.is_file()
    ]
    if absent:
        raise RuntimeError(f"D0047 provenance artifacts are absent: {sorted(absent)}")
    exclusion_ledger = pd.read_csv(D0047_EXCLUSION_SUMMARY)
    retained_links_table = pd.read_csv(D0047_RETAINED_LINKS)
    attrition_table = pd.read_csv(D0047_ATTRITION_SUMMARY)
    excluded_geometry_keys = set(
        map(
            tuple,
            geometry.loc[
                ~_profile_included_mask(geometry, label="D0047 geometry summary"),
                ["city", "orbit"],
            ].to_records(index=False),
        )
    )
    if (
        len(exclusion_ledger) != EXCLUDED_METADATA_CANDIDATES
        or exclusion_ledger.duplicated(["city", "orbit"]).any()
        or set(
            map(
                tuple,
                exclusion_ledger[["city", "orbit"]].to_records(index=False),
            )
        )
        != excluded_geometry_keys
        or len(retained_links_table) != EXPECTED_CITY_SCENE_LINKS
        or retained_links_table[["orbit", "scene"]].drop_duplicates().shape[0]
        != EXPECTED_UNIQUE_SCENES
        or retained_links_table.duplicated(["city", "orbit", "scene"]).any()
        or attrition_table.empty
        or int(
            pd.to_numeric(
                attrition_table["excluded_pre_geometry_candidate_count"],
                errors="raise",
            ).sum()
        )
        != EXCLUDED_METADATA_CANDIDATES
    ):
        raise RuntimeError("D0047 full/exclusion/link attrition ledger is stale")

    try:
        run_record = json.loads(D0035_RUN_RECORD.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        raise RuntimeError("D0047 run record is unreadable") from None
    if (
        run_record.get("schema_version") != ARCHIVE_AVAILABLE_RUN_RECORD_SCHEMA_VERSION
        or run_record.get("decision_id") != D0047_DECISION_ID
        or run_record.get("implementation_decision_id")
        != D0047_IMPLEMENTATION_DECISION_ID
        or run_record.get("collection_concept_id") != D0035_COLLECTION_CONCEPT_ID
        or run_record.get("algorithm_version") != D0047_ALGORITHM_VERSION
        or run_record.get("analysis_profile") != "D0047_archive_available"
        or run_record.get("scientific_gate_scope") != "archive_available_only"
        or run_record.get("combined_validation") != combined_validation
        or run_record.get("lst_opened") is not False
        or run_record.get("thermal_opened") is not False
        or run_record.get("record_2026_opened") is not False
        or str(run_record.get("holdout_status", "")).upper() != "UNSELECTED"
    ):
        raise RuntimeError("D0047 run-record identity, scope, or safety seal is stale")

    manifest = pd.read_csv(D0035_SCENE_MANIFEST)
    required_manifest = {
        "orbit",
        "scene",
        "granule_id",
        "cities",
        "status",
        "decision_id",
        "collection_short_name",
        "collection_version",
        "collection_concept_id",
        "cmr_record_sha256",
    }
    missing_manifest = required_manifest - set(manifest.columns)
    if missing_manifest:
        raise RuntimeError(f"D0047 scene manifest lacks {sorted(missing_manifest)}")
    if (
        len(manifest) != D0047_EXPECTED_UNIQUE_SCENES
        or manifest.duplicated(["orbit", "scene"]).any()
        or manifest["granule_id"].astype(str).duplicated().any()
        or not manifest["status"].astype(str).eq("available").all()
        or not manifest["decision_id"].astype(str).eq(D0047_DECISION_ID).all()
        or not manifest["collection_short_name"].astype(str).eq("ECO_L1B_GEO").all()
        or not manifest["collection_version"].astype(str).str.zfill(3).eq("002").all()
        or not manifest["collection_concept_id"]
        .astype(str)
        .eq(D0035_COLLECTION_CONCEPT_ID)
        .all()
        or not manifest["cmr_record_sha256"]
        .astype(str)
        .str.fullmatch(r"[0-9a-f]{64}")
        .all()
    ):
        raise RuntimeError("D0047 retained scene-manifest census is stale")
    manifest_links: set[tuple[str, int, int, str]] = set()
    for row in manifest.to_dict("records"):
        cities = tuple(filter(None, str(row["cities"]).split(";")))
        if not cities or tuple(sorted(set(cities))) != cities:
            raise RuntimeError("D0047 scene manifest has noncanonical city bindings")
        for city in cities:
            manifest_links.add(
                (city, int(row["orbit"]), int(row["scene"]), str(row["granule_id"]))
            )
    if len(manifest_links) != D0047_EXPECTED_CITY_SCENE_LINKS:
        raise RuntimeError("D0047 retained city/scene link census is stale")

    asset_document = _load_checkpoint_document(
        D0035_ASSET_CHECKPOINT, label="D0047 metadata-asset checkpoint"
    )
    asset_items = asset_document["items"]
    manifest_by_granule = {
        str(row["granule_id"]): row for row in manifest.to_dict("records")
    }
    if set(asset_items) != set(manifest_by_granule):
        raise RuntimeError("D0047 asset checkpoint differs from the retained manifest")
    for granule, record in asset_items.items():
        manifest_row = manifest_by_granule[granule]
        if (
            record.get("status") != "complete"
            or record.get("algorithm_version") != D0047_ALGORITHM_VERSION
            or record.get("collection_concept_id") != D0035_COLLECTION_CONCEPT_ID
            or record.get("cmr_record_sha256")
            != str(manifest_row["cmr_record_sha256"])
            or not _is_sha256(record.get("dmrpp_sha256"))
            or not _is_sha256(record.get("locator_sha256"))
        ):
            raise RuntimeError(f"D0047 asset checkpoint is stale for {granule}")

    included = _profile_included_mask(geometry, label="D0047 geometry summary")
    retained_geometry = geometry.loc[included].copy()
    excluded_geometry = geometry.loc[~included].copy()
    if len(retained_geometry) != D0047_RETAINED_METADATA_CANDIDATES:
        raise RuntimeError("D0047 retained geometry census is stale")
    geometry_document = _load_checkpoint_document(
        D0035_GEOMETRY_CHECKPOINT, label="D0047 geometry checkpoint"
    )
    geometry_items = geometry_document["items"]
    expected_geometry_ids = {
        f"{row.city}:{int(row.orbit):05d}"
        for row in retained_geometry[["city", "orbit"]].itertuples(index=False)
    }
    if set(geometry_items) != expected_geometry_ids:
        raise RuntimeError("D0047 geometry checkpoint includes the wrong candidate keys")
    if set(
        f"{row.city}:{int(row.orbit):05d}"
        for row in excluded_geometry[["city", "orbit"]].itertuples(index=False)
    ).intersection(geometry_items):
        raise RuntimeError("D0047 excluded candidates entered the geometry checkpoint")

    geometry_rows = {
        (str(row["city"]), str(row["orbit_key"])): row
        for row in _keyed(retained_geometry, label="D0047 retained geometry").to_dict(
            "records"
        )
    }
    checkpoint_files: set[Path] = set()
    evidence_links: set[tuple[str, int, int, str]] = set()
    evidence_set_inputs: list[str] = []
    for item_id, record in sorted(geometry_items.items()):
        if (
            record.get("status") != "complete"
            or record.get("boundary_verified") is not True
            or not _is_sha256(record.get("binding_sha256"))
            or not _is_sha256(record.get("evidence_sha256"))
            or not record.get("evidence_path")
        ):
            raise RuntimeError(f"D0047 geometry checkpoint is stale for {item_id}")
        path = Path(str(record["evidence_path"])).resolve()
        try:
            relative = path.relative_to(D0035_PASS_EVIDENCE_DIR.resolve())
        except ValueError:
            raise RuntimeError(
                f"D0047 pass evidence escaped its frozen root for {item_id}"
            ) from None
        if not path.is_file() or _sha256(path) != record["evidence_sha256"]:
            raise RuntimeError(f"D0047 pass evidence hash is stale for {item_id}")
        checkpoint_files.add(path)
        evidence_set_inputs.append(f"{relative}:{_sha256(path)}")
        try:
            evidence = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            raise RuntimeError(f"D0047 pass evidence is unreadable for {item_id}") from None
        binding = evidence.get("binding")
        scenes = evidence.get("scene_evidence")
        summary = evidence.get("summary")
        if not isinstance(binding, dict) or not isinstance(scenes, list) or not isinstance(
            summary, dict
        ):
            raise RuntimeError(f"D0047 pass evidence schema is stale for {item_id}")
        city = str(evidence.get("city"))
        orbit = int(evidence.get("orbit", -1))
        computed_binding_sha = _json_sha256(binding)
        if (
            item_id != f"{city}:{orbit:05d}"
            or path != (D0035_PASS_EVIDENCE_DIR / city / f"{orbit:05d}.json").resolve()
            or evidence.get("status") != "complete"
            or evidence.get("decision_id") != D0047_DECISION_ID
            or evidence.get("implementation_decision_id")
            != D0048_IMPLEMENTATION_DECISION_ID
            or evidence.get("algorithm_version") != D0047_ALGORITHM_VERSION
            or evidence.get("boundary_verified") is not True
            or evidence.get("binding_sha256") != computed_binding_sha
            or record.get("binding_sha256") != computed_binding_sha
            or binding.get("decision_id") != D0047_DECISION_ID
            or binding.get("algorithm_version") != D0047_ALGORITHM_VERSION
            or str(binding.get("city")) != city
            or int(binding.get("orbit", -1)) != orbit
            or not scenes
            or not all(item.get("boundary_verified") is True for item in scenes)
            or evidence.get("lst_opened") is not False
            or evidence.get("thermal_opened") is not False
            or evidence.get("record_2026_opened") is not False
            or str(evidence.get("holdout_status", "")).upper() != "UNSELECTED"
        ):
            raise RuntimeError(f"D0047 pass evidence binding is stale for {item_id}")
        scene_bindings = binding.get("scene_bindings")
        if not isinstance(scene_bindings, list) or not scene_bindings:
            raise RuntimeError(f"D0047 pass evidence has no scene binding for {item_id}")
        _validate_d0048_geometry_evidence(binding, scenes, item_id=item_id)
        for scene in scene_bindings:
            if (
                scene.get("algorithm_version") != D0047_ALGORITHM_VERSION
                or scene.get("collection_concept_id") != D0035_COLLECTION_CONCEPT_ID
                or not _is_sha256(scene.get("dmrpp_sha256"))
                or not _is_sha256(scene.get("locator_sha256"))
            ):
                raise RuntimeError(f"D0047 scene binding is stale for {item_id}")
            evidence_links.add(
                (
                    city,
                    int(scene["orbit"]),
                    int(scene["scene"]),
                    str(scene["granule_id"]),
                )
            )
        row = geometry_rows.get((city, str(orbit)))
        if row is None or set(summary).difference(row):
            raise RuntimeError(f"D0047 geometry summary lacks evidence for {item_id}")
        for field, value in summary.items():
            if not _summary_value_matches(value, row[field], field=field):
                raise RuntimeError(f"D0047 geometry summary is stale for {item_id}: {field}")

    discovered = {path.resolve() for path in D0035_PASS_EVIDENCE_DIR.rglob("*.json")}
    if discovered != checkpoint_files or len(discovered) != RETAINED_METADATA_CANDIDATES:
        raise RuntimeError("D0047 pass-evidence file census is stale")
    if evidence_links != manifest_links:
        raise RuntimeError("D0047 pass evidence and retained scene manifest differ")
    scene_count = pd.to_numeric(
        retained_geometry["n_l1b_geo_scenes"], errors="raise"
    )
    if (
        not np.equal(scene_count, np.floor(scene_count)).all()
        or int(scene_count.sum()) != EXPECTED_CITY_SCENE_LINKS
    ):
        raise RuntimeError("D0047 geometry-summary scene count is stale")

    current_counts = {
        VALIDATION_ORIGINAL_CANDIDATES_FIELD: ORIGINAL_METADATA_CANDIDATES,
        VALIDATION_EXCLUDED_CANDIDATES_FIELD: EXCLUDED_METADATA_CANDIDATES,
        VALIDATION_RETAINED_CANDIDATES_FIELD: RETAINED_METADATA_CANDIDATES,
        VALIDATION_RETAINED_LINKS_FIELD: EXPECTED_CITY_SCENE_LINKS,
        VALIDATION_RETAINED_SCENES_FIELD: EXPECTED_UNIQUE_SCENES,
        "asset_checkpoint_items": len(asset_items),
        "geometry_checkpoint_items": len(geometry_items),
        "pass_evidence_files": len(discovered),
    }
    current_hashes = {
        "scene_manifest": _sha256(D0035_SCENE_MANIFEST),
        "asset_checkpoint": _sha256(D0035_ASSET_CHECKPOINT),
        "geometry_checkpoint": _sha256(D0035_GEOMETRY_CHECKPOINT),
        "pass_evidence_set": _sha256_strings(evidence_set_inputs),
        "geometry_summary": _sha256(GEOMETRY_SUMMARY),
        "cloud_checkpoint": _sha256(D0035_CLOUD_CHECKPOINT),
        "cloud_summary": _sha256(CLOUD_SUMMARY),
        "combined_validation": _sha256(COMBINED_VALIDATION),
        "candidate_availability_ledger": _sha256(AVAILABILITY_LEDGER),
        "profile_validation": _sha256(PROFILE_VALIDATION),
        "archive_unavailable_pre_geometry_exclusions": _sha256(
            D0047_EXCLUSION_SUMMARY
        ),
        "archive_available_attrition_summary": _sha256(D0047_ATTRITION_SUMMARY),
        "retained_city_scene_links": _sha256(D0047_RETAINED_LINKS),
    }
    if run_record.get("provenance_counts") != current_counts:
        raise RuntimeError("D0047 run-record provenance counts are stale")
    if run_record.get("provenance_sha256") != current_hashes:
        raise RuntimeError("D0047 run-record provenance hashes are stale")
    artifact_hashes = run_record.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict) or not artifact_hashes:
        raise RuntimeError("D0047 run record has no artifact hash ledger")
    for relative_path, expected_hash in artifact_hashes.items():
        path = (ROOT / str(relative_path)).resolve()
        try:
            path.relative_to(ROOT.resolve())
        except ValueError:
            raise RuntimeError("D0047 artifact path escaped the repository") from None
        if not path.is_file() or _sha256(path) != expected_hash:
            raise RuntimeError(f"D0047 run-record artifact hash is stale: {relative_path}")
    return {
        "run_record_path": str(D0035_RUN_RECORD.relative_to(ROOT)),
        "run_record_sha256": _sha256(D0035_RUN_RECORD),
        "algorithm_version": D0047_ALGORITHM_VERSION,
        "analysis_profile": "D0047_archive_available",
        "scientific_gate_scope": "archive_available_only",
        "profile_scope_label": D0047_SCOPE_LABEL,
        "provenance_counts": current_counts,
        "provenance_sha256": current_hashes,
        **profile_binding,
        "exclusion_summary_path": str(D0047_EXCLUSION_SUMMARY.relative_to(ROOT)),
        "exclusion_summary_sha256": _sha256(D0047_EXCLUSION_SUMMARY),
        "attrition_summary_path": str(D0047_ATTRITION_SUMMARY.relative_to(ROOT)),
        "attrition_summary_sha256": _sha256(D0047_ATTRITION_SUMMARY),
        "retained_links_path": str(D0047_RETAINED_LINKS.relative_to(ROOT)),
        "retained_links_sha256": _sha256(D0047_RETAINED_LINKS),
    }


def _load_quality_d0047() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load only a complete D0047 archive-available geometry/cloud PASS."""

    geometry_only = pd.read_csv(SCREENED_PRE_CLOUD)
    screened = _canonicalize_l1b_screen(pd.read_csv(SCREENED_FINAL))
    legacy_screened = pd.read_csv(LEGACY_SCREENED)
    geometry = pd.read_csv(GEOMETRY_SUMMARY)
    cloud = pd.read_csv(CLOUD_SUMMARY)
    geometry_validation = json.loads(GEOMETRY_VALIDATION.read_text(encoding="utf-8"))
    validation = json.loads(COMBINED_VALIDATION.read_text(encoding="utf-8"))

    profile_binding = _validate_archive_available_profile_artifacts(geometry)
    geometry_included = _profile_included_mask(
        geometry, label="D0047 geometry summary"
    )
    geometry_only_metadata = geometry_only.loc[_metadata_mask(geometry_only)].copy()
    screened_metadata = screened.loc[_metadata_mask(screened)].copy()
    legacy_metadata = legacy_screened.loc[_metadata_mask(legacy_screened)].copy()
    geometry_only_included = _profile_included_mask(
        geometry_only_metadata, label="D0047 pre-cloud geometry screen"
    )
    screened_included = _profile_included_mask(
        screened_metadata, label="D0047 combined geometry/cloud screen"
    )
    if any(
        len(table) != ORIGINAL_METADATA_CANDIDATES
        for table in (
            geometry,
            geometry_only_metadata,
            screened_metadata,
            legacy_metadata,
        )
    ):
        raise RuntimeError("D0047 tables do not preserve the complete 942-row ledger")
    _assert_same_keys_and_times(
        geometry,
        geometry_only_metadata,
        left_label="D0047 geometry summary",
        right_label="D0047 pre-cloud geometry screen",
    )
    _assert_same_keys_and_times(
        geometry_only_metadata,
        screened_metadata,
        left_label="D0047 pre-cloud geometry screen",
        right_label="D0047 combined geometry/cloud screen",
    )
    _assert_same_keys_and_times(
        legacy_metadata,
        screened_metadata,
        left_label="legacy L2T screen",
        right_label="D0047 combined geometry/cloud screen",
    )

    def availability_by_key(table: pd.DataFrame, included: pd.Series, label: str) -> pd.DataFrame:
        keyed = _keyed(table, label=label)
        keyed["_included"] = included.to_numpy(bool)
        return keyed[["city", "orbit_key", "_included"]]

    included_check = availability_by_key(
        geometry, geometry_included, "D0047 geometry summary"
    ).merge(
        availability_by_key(
            geometry_only_metadata,
            geometry_only_included,
            "D0047 pre-cloud geometry screen",
        ),
        on=["city", "orbit_key"],
        suffixes=("_geometry", "_pre"),
        validate="one_to_one",
    ).merge(
        availability_by_key(
            screened_metadata,
            screened_included,
            "D0047 combined geometry/cloud screen",
        ),
        on=["city", "orbit_key"],
        validate="one_to_one",
    )
    if (
        not included_check["_included_geometry"].equals(
            included_check["_included_pre"]
        )
        or not included_check["_included_geometry"].equals(
            included_check["_included"]
        )
    ):
        raise RuntimeError("D0047 availability cohort changed between screened tables")

    required_geometry_columns = {
        "l1b_geometry_covered_cells",
        "l1b_geometry_domain_cells",
        "l1b_geometry_coverage_fraction",
        "l1b_view_zenith_abs_p95_deg",
        "l1b_geometry_complete",
        "l1b_geometry_status",
        "quality_candidate_pre_cloud",
        "quality_candidate_pre_cloud_l1b",
        "quality_candidate_pre_cloud_l2t_invalid",
        ARCHIVE_AVAILABLE_STATUS_COLUMN,
        ARCHIVE_AVAILABLE_INCLUDED_COLUMN,
    }
    missing_geometry = required_geometry_columns - set(geometry.columns)
    if missing_geometry:
        raise ValueError(f"D0047 geometry summary lacks {sorted(missing_geometry)}")

    excluded = geometry.loc[~geometry_included]
    retained = geometry.loc[geometry_included]
    metric_columns = [
        "l1b_geometry_covered_cells",
        "l1b_geometry_domain_cells",
        "l1b_geometry_coverage_fraction",
        "l1b_view_zenith_abs_p95_deg",
    ]
    if not excluded[metric_columns].isna().all(axis=None):
        raise RuntimeError("D0047 exclusions contain geometry measurements")
    excluded_complete = _nullable_true_series(
        excluded["l1b_geometry_complete"], label="excluded l1b_geometry_complete"
    )
    if excluded_complete.notna().any():
        raise RuntimeError("D0047 exclusions were assigned a geometry-complete flag")
    if not excluded["l1b_geometry_status"].astype(str).eq(
        ARCHIVE_AVAILABLE_EXCLUDED_STATUS
    ).all():
        raise RuntimeError("D0047 exclusions were assigned a geometry result status")
    for flag in (
        "quality_candidate_pre_cloud",
        "quality_candidate_pre_cloud_l1b",
        "quality_candidate_pre_cloud_l2t_invalid",
    ):
        if _nullable_true_series(
            excluded[flag], label=f"excluded {flag}"
        ).notna().any():
            raise RuntimeError("D0047 excluded candidate received a quality check flag")

    retained_complete = _true_series(
        retained["l1b_geometry_complete"], label="retained l1b_geometry_complete"
    )
    if not retained_complete.all():
        raise RuntimeError("not every retained D0047 row has definitive geometry")
    covered = pd.to_numeric(
        retained["l1b_geometry_covered_cells"], errors="coerce"
    )
    denominator = pd.to_numeric(
        retained["l1b_geometry_domain_cells"], errors="coerce"
    )
    coverage = pd.to_numeric(
        retained["l1b_geometry_coverage_fraction"], errors="coerce"
    )
    p95 = pd.to_numeric(
        retained["l1b_view_zenith_abs_p95_deg"], errors="coerce"
    )
    if (
        covered.isna().any()
        or denominator.isna().any()
        or coverage.isna().any()
        or (covered < 0).any()
        or (denominator <= 0).any()
        or (covered > denominator).any()
        or not np.equal(covered, np.floor(covered)).all()
        or not np.equal(denominator, np.floor(denominator)).all()
        or not bool(coverage.between(0.0, 1.0).all())
        or ((covered == 0) != p95.isna()).any()
        or (p95.dropna() < 0).any()
        or not np.allclose(
            coverage.to_numpy(float),
            (covered / denominator).to_numpy(float),
            rtol=0,
            atol=1e-12,
        )
    ):
        raise RuntimeError("D0047 retained L1B metrics are internally inconsistent")
    coverage_pass = coverage.ge(0.95)
    angle_pass = p95.notna() & p95.ge(0.0) & p95.le(20.0)
    expected_status = pd.Series(
        np.select(
            [
                coverage_pass & angle_pass,
                ~coverage_pass & angle_pass,
                coverage_pass & ~angle_pass,
            ],
            ["geometry_pass", "coverage_fail", "angle_fail"],
            default="coverage_and_angle_fail",
        ),
        index=retained.index,
    )
    retained_status = retained["l1b_geometry_status"].astype(str).str.strip()
    if not retained_status.equals(expected_status):
        raise RuntimeError("D0047 retained geometry status disagrees with its metrics")
    retained_candidates = _candidate_mask(geometry).loc[retained.index]
    if not retained_candidates.equals(retained_status.eq("geometry_pass")):
        raise RuntimeError("D0047 retained geometry status and candidate flag disagree")
    geometry_passing = int(retained_candidates.sum())
    if geometry_passing <= 0 or geometry_passing > RETAINED_METADATA_CANDIDATES:
        raise RuntimeError("D0047 produced no valid archive-available geometry cohort")

    geometry_count_fields = {
        VALIDATION_ORIGINAL_CANDIDATES_FIELD: ORIGINAL_METADATA_CANDIDATES,
        VALIDATION_EXCLUDED_CANDIDATES_FIELD: EXCLUDED_METADATA_CANDIDATES,
        VALIDATION_RETAINED_CANDIDATES_FIELD: RETAINED_METADATA_CANDIDATES,
        "resolved_geometry_candidate_count": RETAINED_METADATA_CANDIDATES,
        "definitive_geometry_status_count": RETAINED_METADATA_CANDIDATES,
        "unresolved_geometry_candidate_count": 0,
        "geometry_passing_candidate_count": geometry_passing,
    }
    for field, expected in geometry_count_fields.items():
        if int(geometry_validation.get(field, -1)) != expected:
            raise RuntimeError(f"D0047 geometry seal failed: {field}")
    if (
        geometry_validation.get("decision_id") != D0047_DECISION_ID
        or geometry_validation.get("analysis_profile") != "D0047_archive_available"
        or geometry_validation.get("scientific_gate_scope")
        != "archive_available_only"
        or geometry_validation.get("geometry_source") != D0035_GEOMETRY_SOURCE
        or geometry_validation.get("geometry_complete") is not True
        or geometry_validation.get("candidate_seal_geometry_only") is not True
        or int(geometry_validation.get("excluded_geometry_metric_null_row_count", -1))
        != EXCLUDED_METADATA_CANDIDATES
        or geometry_validation.get("excluded_geometry_nonnull_columns") != []
        or geometry_validation.get("missing_scene_imputation_used") is not False
        or geometry_validation.get("missing_scene_zero_coverage_assigned") is not False
        or geometry_validation.get("adjacent_scene_substitution_used") is not False
    ):
        raise RuntimeError("D0047 geometry seal is incomplete or incorrectly scoped")

    # The full 942-row screens must preserve all measured geometry values and flags.
    contract_columns = [
        *metric_columns,
        "l1b_geometry_complete",
        "l1b_geometry_status",
        "quality_candidate_pre_cloud",
        "quality_candidate_pre_cloud_l1b",
        "quality_candidate_pre_cloud_l2t_invalid",
        ARCHIVE_AVAILABLE_STATUS_COLUMN,
        ARCHIVE_AVAILABLE_INCLUDED_COLUMN,
    ]
    geometry_contract = _keyed(
        geometry[["city", "orbit", "acquisition_utc", *contract_columns]],
        label="D0047 geometry summary",
    )
    for table, table_label in (
        (geometry_only_metadata, "D0047 pre-cloud geometry screen"),
        (screened_metadata, "D0047 combined geometry/cloud screen"),
    ):
        missing_contract = set(contract_columns) - set(table.columns)
        if missing_contract:
            raise ValueError(f"{table_label} lacks {sorted(missing_contract)}")
        table_contract = _keyed(
            table[["city", "orbit", "acquisition_utc", *contract_columns]],
            label=table_label,
        )
        check = geometry_contract.merge(
            table_contract,
            on=["city", "orbit_key"],
            suffixes=("_geometry", "_table"),
            validate="one_to_one",
        )
        for column in metric_columns:
            if not np.allclose(
                pd.to_numeric(check[f"{column}_geometry"], errors="coerce"),
                pd.to_numeric(check[f"{column}_table"], errors="coerce"),
                rtol=0,
                atol=1e-12,
                equal_nan=True,
            ):
                raise RuntimeError(f"{table_label} differs in {column}")
        for column in (
            "quality_candidate_pre_cloud",
            "quality_candidate_pre_cloud_l1b",
            "quality_candidate_pre_cloud_l2t_invalid",
        ):
            if not _nullable_true_series(
                check[f"{column}_geometry"], label=f"geometry {column}"
            ).equals(
                _nullable_true_series(
                    check[f"{column}_table"], label=f"table {column}"
                )
            ):
                raise RuntimeError(f"{table_label} differs in {column}")
        if not _true_series(
            check[f"{ARCHIVE_AVAILABLE_INCLUDED_COLUMN}_geometry"],
            label=f"geometry {ARCHIVE_AVAILABLE_INCLUDED_COLUMN}",
        ).equals(
            _true_series(
                check[f"{ARCHIVE_AVAILABLE_INCLUDED_COLUMN}_table"],
                label=f"table {ARCHIVE_AVAILABLE_INCLUDED_COLUMN}",
            )
        ):
            raise RuntimeError(
                f"{table_label} differs in {ARCHIVE_AVAILABLE_INCLUDED_COLUMN}"
            )
        for column in (
            "l1b_geometry_complete",
            "l1b_geometry_status",
            ARCHIVE_AVAILABLE_STATUS_COLUMN,
        ):
            left = check[f"{column}_geometry"].astype("string")
            right = check[f"{column}_table"].astype("string")
            if not left.equals(right):
                raise RuntimeError(f"{table_label} differs in {column}")

    required_cloud = {
        "city",
        "orbit",
        "acquisition_utc",
        "n_domain_pixels",
        "n_domain_pixels_in_present_tiles",
        "n_cloud_observed_pixels_independent_of_view",
        "n_clear_pixels_independent_of_view",
        "n_cloud_pixels_independent_of_view",
        "n_cloud_invalid_or_fill_pixels_independent_of_view",
        "cloud_survival_fraction_of_domain_independent_of_view",
        "clear_domain_fraction",
        "n_expected_scene_tiles",
        "n_resolved_cloud_assets",
        "n_verified_cloud_assets",
        "cloud_asset_complete",
        "provenance_complete",
        "cloud_asset_bytes",
        "cloud_asset_set_sha256",
        "cloud_resolution_status",
        "decision_id",
    }
    missing_cloud = required_cloud - set(cloud.columns)
    if missing_cloud:
        raise ValueError(f"D0047 cloud summary lacks {sorted(missing_cloud)}")
    screened_candidates = screened_metadata.loc[
        screened_included & _candidate_mask(screened_metadata),
        ["city", "orbit", "acquisition_utc"],
    ].copy()
    if len(screened_candidates) != geometry_passing:
        raise RuntimeError("D0047 screened candidate count differs from geometry seal")
    cloud = cloud.copy()
    cloud["city"] = cloud["city"].astype(str)
    screened_candidates["city"] = screened_candidates["city"].astype(str)
    cloud["orbit_key"] = _orbit_key(cloud["orbit"])
    screened_candidates["orbit_key"] = _orbit_key(screened_candidates["orbit"])
    if cloud.duplicated(["city", "orbit_key"]).any():
        raise RuntimeError("D0047 cloud summary is not unique by city/orbit")
    candidate_keys = set(
        screened_candidates[["city", "orbit_key"]].itertuples(index=False, name=None)
    )
    cloud_keys = set(cloud[["city", "orbit_key"]].itertuples(index=False, name=None))
    if candidate_keys != cloud_keys or len(cloud) != geometry_passing:
        raise RuntimeError("D0047 cloud keys do not equal the geometry-pass cohort")
    acquisition_check = screened_candidates.merge(
        cloud[["city", "orbit_key", "acquisition_utc"]],
        on=["city", "orbit_key"],
        suffixes=("_screen", "_cloud"),
        validate="one_to_one",
    )
    if not _utc_series(
        acquisition_check["acquisition_utc_screen"], label="screen acquisition_utc"
    ).equals(
        _utc_series(
            acquisition_check["acquisition_utc_cloud"], label="cloud acquisition_utc"
        )
    ):
        raise RuntimeError("D0047 cloud acquisition times differ from the screen")

    fractions = pd.to_numeric(cloud["clear_domain_fraction"], errors="coerce")
    n_domain = pd.to_numeric(cloud["n_domain_pixels"], errors="raise")
    n_present = pd.to_numeric(
        cloud["n_domain_pixels_in_present_tiles"], errors="raise"
    )
    n_observed = pd.to_numeric(
        cloud["n_cloud_observed_pixels_independent_of_view"], errors="raise"
    )
    n_clear = pd.to_numeric(
        cloud["n_clear_pixels_independent_of_view"], errors="raise"
    )
    n_cloud = pd.to_numeric(
        cloud["n_cloud_pixels_independent_of_view"], errors="raise"
    )
    n_invalid = pd.to_numeric(
        cloud["n_cloud_invalid_or_fill_pixels_independent_of_view"], errors="raise"
    )
    pixel_counts = pd.concat(
        [n_domain, n_present, n_observed, n_clear, n_cloud, n_invalid], axis=1
    )
    if (
        fractions.isna().any()
        or not bool(fractions.between(0.0, 1.0).all())
        or (n_domain <= 0).any()
        or (pixel_counts < 0).any(axis=None)
        or not np.equal(pixel_counts, np.floor(pixel_counts)).all(axis=None)
        or (n_present > n_domain).any()
        or not (n_observed == n_clear + n_cloud).all()
        or not (n_domain == n_clear + n_cloud + n_invalid).all()
        or not np.allclose(fractions, n_clear / n_domain, rtol=0, atol=1e-12)
        or not np.allclose(
            fractions,
            pd.to_numeric(
                cloud["cloud_survival_fraction_of_domain_independent_of_view"],
                errors="coerce",
            ),
            rtol=0,
            atol=1e-12,
        )
    ):
        raise RuntimeError("D0047 cloud fractions or pixel counts are inconsistent")
    for column in ("cloud_asset_complete", "provenance_complete"):
        if not _true_series(cloud[column], label=column).all():
            raise RuntimeError(f"D0047 cloud completeness failed: {column}")
        cloud[column] = True
    expected_assets = pd.to_numeric(cloud["n_expected_scene_tiles"], errors="raise")
    resolved_assets = pd.to_numeric(cloud["n_resolved_cloud_assets"], errors="raise")
    verified_assets = pd.to_numeric(cloud["n_verified_cloud_assets"], errors="raise")
    if (
        (expected_assets <= 0).any()
        or not (expected_assets == resolved_assets).all()
        or not (expected_assets == verified_assets).all()
        or (pd.to_numeric(cloud["cloud_asset_bytes"], errors="raise") <= 0).any()
        or not cloud["cloud_asset_set_sha256"]
        .astype(str)
        .str.fullmatch(r"[0-9a-f]{64}")
        .all()
        or not cloud["cloud_resolution_status"]
        .astype(str)
        .eq("observed_exhaustive_complete_independent_of_view")
        .all()
        or not cloud["decision_id"].astype(str).eq(D0047_DECISION_ID).all()
    ):
        raise RuntimeError("D0047 cloud asset provenance is incomplete")

    validation_counts = {
        **geometry_count_fields,
        "expected_cloud_candidates": geometry_passing,
        "resolved_cloud_candidate_count": geometry_passing,
        "finite_cloud_fraction_count": geometry_passing,
    }
    for field, expected in validation_counts.items():
        if int(validation.get(field, -1)) != expected:
            raise RuntimeError(f"D0047 combined gate failed: {field}")
    fraction_sum = float(fractions.sum())
    planning_floor = math.floor(fraction_sum)
    if (
        validation.get("decision_id") != D0047_DECISION_ID
        or validation.get("analysis_profile") != "D0047_archive_available"
        or validation.get("scientific_gate_scope") != "archive_available_only"
        or validation.get("geometry_source") != D0035_GEOMETRY_SOURCE
        or validation.get("geometry_complete") is not True
        or validation.get("cloud_complete") is not True
        or validation.get("combined_complete") is not True
        or validation.get("candidate_seal_geometry_only") is not True
        or validation.get("candidate_view_mask_cloud_independent") is not True
        or validation.get("view_gate_cloud_conditioned") is not False
        or validation.get("cloud_extrapolation_used") is not False
        or validation.get("scientific_gate_eligible") is not True
        or validation.get("canonical_status") != D0047_PASS_STATUS
        or validation.get("gate_status") != D0047_PASS_STATUS
        or validation.get("lst_opened") is not False
        or validation.get("thermal_opened") is not False
        or validation.get("record_2026_opened") is not False
        or str(validation.get("holdout_status", "")).upper() != "UNSELECTED"
        or str(validation.get("frozen_years", "")) != "2018-2025"
        or not np.isclose(
            fraction_sum,
            float(validation.get("planning_pass_equivalent_sum", np.nan)),
            rtol=0,
            atol=1e-10,
        )
        or planning_floor != int(validation.get("planning_pass_equivalent_floor", -1))
    ):
        status = validation.get("gate_status", "not_gate_eligible")
        raise RuntimeError(f"D0047 combined geometry/cloud gate is not eligible: {status}")
    cloud["cloud_survival_fraction_of_domain"] = fractions
    provenance = _validate_d0047_provenance(geometry, validation)
    validation = dict(validation)
    validation["_upstream_provenance"] = provenance
    validation["_profile_binding"] = profile_binding
    return screened, cloud.drop(columns="orbit_key"), validation


def _load_quality() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Fail closed unless the complete D0035 geometry/cloud seal is certified."""

    if ACTIVE_PROFILE == D0047_PROFILE:
        return _load_quality_d0047()

    geometry_only = pd.read_csv(SCREENED_PRE_CLOUD)
    screened = _canonicalize_l1b_screen(pd.read_csv(SCREENED_FINAL))
    legacy_screened = pd.read_csv(LEGACY_SCREENED)
    geometry = pd.read_csv(GEOMETRY_SUMMARY)
    cloud = pd.read_csv(CLOUD_SUMMARY)
    geometry_validation = json.loads(GEOMETRY_VALIDATION.read_text(encoding="utf-8"))
    validation = json.loads(COMBINED_VALIDATION.read_text(encoding="utf-8"))

    required_geometry_validation = {
        "decision_id",
        "expected_metadata_candidates",
        "resolved_geometry_candidate_count",
        "definitive_geometry_status_count",
        "unresolved_geometry_candidate_count",
        "geometry_source",
        "geometry_complete",
        "candidate_seal_geometry_only",
        "geometry_passing_candidate_count",
    }
    missing_geometry_validation = required_geometry_validation - set(
        geometry_validation
    )
    if missing_geometry_validation:
        raise ValueError(
            "geometry validation lacks "
            f"{sorted(missing_geometry_validation)}"
        )
    if str(geometry_validation["decision_id"]).strip() != D0035_DECISION_ID:
        raise RuntimeError("geometry validation is not the frozen D0035 decision")
    exact_geometry_counts = {
        "expected_metadata_candidates": EXPECTED_METADATA_CANDIDATES,
        "resolved_geometry_candidate_count": EXPECTED_METADATA_CANDIDATES,
        "definitive_geometry_status_count": EXPECTED_METADATA_CANDIDATES,
        "unresolved_geometry_candidate_count": 0,
    }
    for field, expected in exact_geometry_counts.items():
        if int(geometry_validation[field]) != expected:
            raise RuntimeError(
                f"D0035 geometry seal failed: {field}={geometry_validation[field]}"
            )
    if (
        str(geometry_validation["geometry_source"]).strip()
        != D0035_GEOMETRY_SOURCE
        or geometry_validation["geometry_complete"] is not True
        or geometry_validation["candidate_seal_geometry_only"] is not True
    ):
        raise RuntimeError("D0035 geometry seal is incomplete or not cloud-independent")

    geometry_passing = int(
        geometry_validation["geometry_passing_candidate_count"]
    )
    if geometry_passing <= 0 or geometry_passing > EXPECTED_METADATA_CANDIDATES:
        raise RuntimeError(
            "D0035 geometry-passing count must be within the sealed 942 candidates"
        )
    if len(geometry) != EXPECTED_METADATA_CANDIDATES:
        raise RuntimeError(
            "geometry pass summary does not contain all 942 metadata candidates"
        )
    required_geometry_columns = {
        "l1b_geometry_covered_cells",
        "l1b_geometry_domain_cells",
        "l1b_geometry_coverage_fraction",
        "l1b_view_zenith_abs_p95_deg",
        "l1b_geometry_complete",
        "l1b_geometry_status",
        "quality_candidate_pre_cloud",
        "quality_candidate_pre_cloud_l1b",
        "quality_candidate_pre_cloud_l2t_invalid",
    }
    missing_geometry_columns = required_geometry_columns - set(geometry.columns)
    if missing_geometry_columns:
        raise ValueError(
            f"geometry pass summary lacks {sorted(missing_geometry_columns)}"
        )
    if not bool(
        _true_series(
            geometry["l1b_geometry_complete"], label="l1b_geometry_complete"
        ).all()
    ):
        raise RuntimeError("not every D0035 geometry row is definitive")
    allowed_geometry_statuses = {
        "geometry_pass",
        "coverage_fail",
        "angle_fail",
        "coverage_and_angle_fail",
    }
    geometry_status = geometry["l1b_geometry_status"].astype(str).str.strip()
    if not geometry_status.isin(allowed_geometry_statuses).all():
        raise RuntimeError("geometry pass summary contains an unresolved status")
    covered = pd.to_numeric(
        geometry["l1b_geometry_covered_cells"], errors="coerce"
    )
    denominator = pd.to_numeric(
        geometry["l1b_geometry_domain_cells"], errors="coerce"
    )
    coverage = pd.to_numeric(
        geometry["l1b_geometry_coverage_fraction"], errors="coerce"
    )
    p95 = pd.to_numeric(
        geometry["l1b_view_zenith_abs_p95_deg"], errors="coerce"
    )
    if (
        covered.isna().any()
        or denominator.isna().any()
        or coverage.isna().any()
        or (covered < 0).any()
        or (denominator <= 0).any()
        or (covered > denominator).any()
        or not np.equal(covered, np.floor(covered)).all()
        or not np.equal(denominator, np.floor(denominator)).all()
        or not bool(coverage.between(0.0, 1.0).all())
        or ((covered == 0) != p95.isna()).any()
        or (p95.dropna() < 0).any()
        or not np.allclose(
            coverage.to_numpy(float),
            (covered / denominator).to_numpy(float),
            rtol=0,
            atol=1e-12,
        )
    ):
        raise RuntimeError("D0035 L1B coverage metrics are internally inconsistent")
    coverage_pass = coverage.ge(0.95)
    angle_pass = p95.notna() & p95.ge(0.0) & p95.le(20.0)
    expected_status = pd.Series(
        np.select(
            [
                coverage_pass & angle_pass,
                ~coverage_pass & angle_pass,
                coverage_pass & ~angle_pass,
            ],
            [
                "geometry_pass",
                "coverage_fail",
                "angle_fail",
            ],
            default="coverage_and_angle_fail",
        ),
        index=geometry.index,
    )
    if not geometry_status.equals(expected_status):
        raise RuntimeError("D0035 L1B metrics disagree with geometry status")
    geometry_candidate_mask = _candidate_mask(geometry)
    if not geometry_candidate_mask.equals(geometry_status.eq("geometry_pass")):
        raise RuntimeError("geometry status and pre-cloud candidate flag disagree")

    geometry_only_metadata = geometry_only.loc[_metadata_mask(geometry_only)].copy()
    screened_metadata = screened.loc[_metadata_mask(screened)].copy()
    legacy_metadata = legacy_screened.loc[_metadata_mask(legacy_screened)].copy()
    if (
        len(geometry_only_metadata) != EXPECTED_METADATA_CANDIDATES
        or len(screened_metadata) != EXPECTED_METADATA_CANDIDATES
        or len(legacy_metadata) != EXPECTED_METADATA_CANDIDATES
    ):
        raise RuntimeError(
            "D0035 screened tables do not contain exactly 942 metadata candidates"
        )
    _assert_same_keys_and_times(
        geometry,
        geometry_only_metadata,
        left_label="geometry pass summary",
        right_label="pre-cloud geometry screen",
    )
    _assert_same_keys_and_times(
        geometry_only_metadata,
        screened_metadata,
        left_label="pre-cloud geometry screen",
        right_label="combined geometry/cloud screen",
    )
    _assert_same_keys_and_times(
        legacy_metadata,
        screened_metadata,
        left_label="legacy L2T screen",
        right_label="combined geometry/cloud screen",
    )
    numeric_contract_columns = (
        "l1b_geometry_covered_cells",
        "l1b_geometry_domain_cells",
        "l1b_geometry_coverage_fraction",
        "l1b_view_zenith_abs_p95_deg",
    )
    boolean_contract_columns = (
        "l1b_geometry_complete",
        "quality_candidate_pre_cloud",
        "quality_candidate_pre_cloud_l1b",
        "quality_candidate_pre_cloud_l2t_invalid",
    )
    for table, table_label in (
        (geometry_only_metadata, "pre-cloud geometry screen"),
        (screened_metadata, "combined geometry/cloud screen"),
    ):
        contract_columns = {
            *numeric_contract_columns,
            *boolean_contract_columns,
            "l1b_geometry_status",
        }
        missing_contract = contract_columns - set(table.columns)
        if missing_contract:
            raise ValueError(f"{table_label} lacks {sorted(missing_contract)}")
        geometry_contract = _keyed(
            geometry[
                [
                    "city",
                    "orbit",
                    "acquisition_utc",
                    *numeric_contract_columns,
                    *boolean_contract_columns,
                    "l1b_geometry_status",
                ]
            ],
            label="geometry pass summary",
        )
        table_contract = _keyed(
            table[
                [
                    "city",
                    "orbit",
                    "acquisition_utc",
                    *numeric_contract_columns,
                    *boolean_contract_columns,
                    "l1b_geometry_status",
                ]
            ],
            label=table_label,
        )
        contract_check = geometry_contract.merge(
            table_contract,
            on=["city", "orbit_key"],
            suffixes=("_geometry", "_table"),
            validate="one_to_one",
        )
        for column in numeric_contract_columns:
            if not np.allclose(
                pd.to_numeric(
                    contract_check[f"{column}_geometry"], errors="coerce"
                ).to_numpy(float),
                pd.to_numeric(
                    contract_check[f"{column}_table"], errors="coerce"
                ).to_numpy(float),
                rtol=0,
                atol=1e-12,
                equal_nan=True,
            ):
                raise RuntimeError(
                    f"{table_label} differs from geometry summary in {column}"
                )
        for column in boolean_contract_columns:
            if not _true_series(
                contract_check[f"{column}_geometry"], label=column
            ).equals(
                _true_series(
                    contract_check[f"{column}_table"], label=column
                )
            ):
                raise RuntimeError(
                    f"{table_label} differs from geometry summary in {column}"
                )
        if not contract_check["l1b_geometry_status_geometry"].astype(str).equals(
            contract_check["l1b_geometry_status_table"].astype(str)
        ):
            raise RuntimeError(
                f"{table_label} differs from geometry summary in l1b_geometry_status"
            )
    geometry_only_mask = _candidate_mask(geometry_only_metadata)
    final_candidate_mask = _candidate_mask(screened_metadata)
    if int(geometry_only_mask.sum()) != geometry_passing:
        raise RuntimeError(
            "pre-cloud table candidate count disagrees with geometry validation"
        )
    geometry_flags = _keyed(
        geometry.assign(_candidate=geometry_candidate_mask.to_numpy()),
        label="geometry pass summary",
    )[["city", "orbit_key", "_candidate"]]
    geometry_only_flags = _keyed(
        geometry_only_metadata.assign(_candidate=geometry_only_mask.to_numpy()),
        label="pre-cloud geometry screen",
    )[["city", "orbit_key", "_candidate"]]
    final_flags = _keyed(
        screened_metadata.assign(_candidate=final_candidate_mask.to_numpy()),
        label="combined geometry/cloud screen",
    )[["city", "orbit_key", "_candidate"]]
    geometry_flag_check = geometry_flags.merge(
        geometry_only_flags,
        on=["city", "orbit_key"],
        suffixes=("_summary", "_pre"),
        validate="one_to_one",
    )
    if not geometry_flag_check["_candidate_summary"].equals(
        geometry_flag_check["_candidate_pre"]
    ):
        raise RuntimeError("geometry summary and pre-cloud candidate flags disagree")
    if "quality_candidate_pre_cloud_l2t_invalid" not in screened_metadata:
        raise ValueError("combined quality screen lacks the preserved L2T-invalid flag")
    legacy_flags = _keyed(
        legacy_metadata.assign(
            _legacy_candidate=_true_series(
                legacy_metadata["quality_candidate_pre_cloud"],
                label="legacy quality_candidate_pre_cloud",
            ).to_numpy()
        ),
        label="legacy L2T screen",
    )[["city", "orbit_key", "_legacy_candidate"]]
    preserved_flags = _keyed(
        screened_metadata.assign(
            _legacy_candidate=_true_series(
                screened_metadata["quality_candidate_pre_cloud_l2t_invalid"],
                label="quality_candidate_pre_cloud_l2t_invalid",
            ).to_numpy()
        ),
        label="combined geometry/cloud screen",
    )[["city", "orbit_key", "_legacy_candidate"]]
    legacy_flag_check = legacy_flags.merge(
        preserved_flags,
        on=["city", "orbit_key"],
        suffixes=("_source", "_preserved"),
        validate="one_to_one",
    )
    if not legacy_flag_check["_legacy_candidate_source"].equals(
        legacy_flag_check["_legacy_candidate_preserved"]
    ):
        raise RuntimeError("preserved L2T-invalid flag differs from the original screen")
    flag_check = geometry_only_flags.merge(
        final_flags,
        on=["city", "orbit_key"],
        suffixes=("_pre", "_final"),
        validate="one_to_one",
    )
    if not flag_check["_candidate_pre"].equals(flag_check["_candidate_final"]):
        raise RuntimeError("the cloud census changed the pre-outcome geometry seal")

    required_cloud = {
        "city",
        "orbit",
        "acquisition_utc",
        "n_domain_pixels",
        "n_domain_pixels_in_present_tiles",
        "n_cloud_observed_pixels_independent_of_view",
        "n_clear_pixels_independent_of_view",
        "n_cloud_pixels_independent_of_view",
        "n_cloud_invalid_or_fill_pixels_independent_of_view",
        "cloud_survival_fraction_of_domain_independent_of_view",
        "clear_domain_fraction",
        "n_expected_scene_tiles",
        "n_resolved_cloud_assets",
        "n_verified_cloud_assets",
        "cloud_asset_complete",
        "provenance_complete",
        "cloud_asset_bytes",
        "cloud_asset_set_sha256",
        "cloud_resolution_status",
        "decision_id",
    }
    missing = required_cloud - set(cloud.columns)
    if missing:
        raise ValueError(f"cloud pass summary lacks {sorted(missing)}")
    required_validation = {
        "decision_id",
        "expected_metadata_candidates",
        "resolved_geometry_candidate_count",
        "definitive_geometry_status_count",
        "unresolved_geometry_candidate_count",
        "geometry_source",
        "geometry_complete",
        "candidate_seal_geometry_only",
        "geometry_passing_candidate_count",
        "expected_cloud_candidates",
        "resolved_cloud_candidate_count",
        "finite_cloud_fraction_count",
        "cloud_complete",
        "combined_complete",
        "scientific_gate_eligible",
        "planning_pass_equivalent_sum",
        "planning_pass_equivalent_floor",
        "candidate_view_mask_cloud_independent",
        "view_gate_cloud_conditioned",
        "cloud_extrapolation_used",
        "canonical_status",
        "gate_status",
        "lst_opened",
        "thermal_opened",
        "record_2026_opened",
        "holdout_status",
        "frozen_years",
    }
    missing_validation = required_validation - set(validation)
    if missing_validation:
        raise ValueError(
            f"cloud validation lacks {sorted(missing_validation)}"
        )
    if str(validation["decision_id"]).strip() != D0035_DECISION_ID:
        raise RuntimeError("combined validation is not the frozen D0035 decision")
    expected_counts = {
        "expected_metadata_candidates": EXPECTED_METADATA_CANDIDATES,
        "resolved_geometry_candidate_count": EXPECTED_METADATA_CANDIDATES,
        "definitive_geometry_status_count": EXPECTED_METADATA_CANDIDATES,
        "unresolved_geometry_candidate_count": 0,
        "geometry_passing_candidate_count": geometry_passing,
        "expected_cloud_candidates": geometry_passing,
        "resolved_cloud_candidate_count": geometry_passing,
        "finite_cloud_fraction_count": geometry_passing,
    }
    for field, expected in expected_counts.items():
        if int(validation[field]) != expected:
            raise RuntimeError(f"combined D0035 gate failed: {field}={validation[field]}")
    if (
        str(validation["geometry_source"]).strip() != D0035_GEOMETRY_SOURCE
        or validation["geometry_complete"] is not True
        or validation["cloud_complete"] is not True
        or validation["combined_complete"] is not True
        or validation["candidate_seal_geometry_only"] is not True
        or validation["scientific_gate_eligible"] is not True
        or validation["candidate_view_mask_cloud_independent"] is not True
        or validation["view_gate_cloud_conditioned"] is not False
        or validation["cloud_extrapolation_used"] is not False
        or str(validation["canonical_status"]) != D0035_PASS_STATUS
        or str(validation["gate_status"]) != D0035_PASS_STATUS
    ):
        status = validation.get("gate_status", "not_gate_eligible")
        raise RuntimeError(
            f"combined D0035 geometry/cloud gate is not eligible: {status}"
        )
    if (
        validation["lst_opened"] is not False
        or validation["thermal_opened"] is not False
        or validation["record_2026_opened"] is not False
        or str(validation["holdout_status"]).strip().upper() != "UNSELECTED"
        or str(validation["frozen_years"]).strip() != "2018-2025"
    ):
        raise RuntimeError("D0035 thermal/2026/holdout seals are not intact")

    screened_candidates = screened_metadata.loc[
        final_candidate_mask, ["city", "orbit", "acquisition_utc"]
    ].copy()
    if len(screened_candidates) != geometry_passing:
        raise ValueError(
            "quality screen does not contain the validation-declared candidates"
        )
    cloud = cloud.copy()
    cloud["city"] = cloud["city"].astype(str)
    screened_candidates["city"] = screened_candidates["city"].astype(str)
    cloud["orbit_key"] = _orbit_key(cloud["orbit"])
    screened_candidates["orbit_key"] = _orbit_key(screened_candidates["orbit"])
    if cloud.duplicated(["city", "orbit_key"]).any():
        raise ValueError("cloud summary is not unique by city/orbit")
    candidate_keys = set(
        screened_candidates[["city", "orbit_key"]].itertuples(index=False, name=None)
    )
    cloud_keys = set(cloud[["city", "orbit_key"]].itertuples(index=False, name=None))
    if candidate_keys != cloud_keys or len(cloud) != geometry_passing:
        raise RuntimeError(
            "cloud summary keys do not exactly equal the geometry-screened candidates"
        )
    acquisition_check = screened_candidates.merge(
        cloud[["city", "orbit_key", "acquisition_utc"]],
        on=["city", "orbit_key"],
        how="inner",
        suffixes=("_screen", "_cloud"),
        validate="one_to_one",
    )
    screen_time = _utc_series(
        acquisition_check["acquisition_utc_screen"], label="screen acquisition_utc"
    )
    cloud_time = _utc_series(
        acquisition_check["acquisition_utc_cloud"], label="cloud acquisition_utc"
    )
    if not screen_time.equals(cloud_time):
        raise RuntimeError("cloud acquisition timestamps do not match the screen")

    fractions = pd.to_numeric(cloud["clear_domain_fraction"], errors="coerce")
    if fractions.isna().any() or not bool(fractions.between(0.0, 1.0).all()):
        raise RuntimeError("cloud fractions must be finite in [0, 1]")
    for column in ("cloud_asset_complete", "provenance_complete"):
        if not bool(_true_series(cloud[column], label=column).all()):
            raise RuntimeError(f"cloud gate failed completeness field {column}")
        cloud[column] = True
    if not cloud["decision_id"].astype(str).eq(D0035_DECISION_ID).all():
        raise RuntimeError("cloud summary contains another decision ID")
    n_domain = pd.to_numeric(cloud["n_domain_pixels"], errors="raise")
    n_clear = pd.to_numeric(
        cloud["n_clear_pixels_independent_of_view"], errors="raise"
    )
    n_cloud = pd.to_numeric(
        cloud["n_cloud_pixels_independent_of_view"], errors="raise"
    )
    n_invalid = pd.to_numeric(
        cloud["n_cloud_invalid_or_fill_pixels_independent_of_view"],
        errors="raise",
    )
    n_observed = pd.to_numeric(
        cloud["n_cloud_observed_pixels_independent_of_view"], errors="raise"
    )
    n_present = pd.to_numeric(
        cloud["n_domain_pixels_in_present_tiles"], errors="raise"
    )
    pixel_counts = pd.concat(
        [n_domain, n_present, n_clear, n_cloud, n_invalid, n_observed], axis=1
    )
    if (
        (n_domain <= 0).any()
        or (pixel_counts < 0).any(axis=None)
        or not np.equal(pixel_counts, np.floor(pixel_counts)).all(axis=None)
        or (n_present > n_domain).any()
        or (n_clear < 0).any()
        or (n_clear > n_domain).any()
        or not (n_observed == n_clear + n_cloud).all()
        or not (n_domain == n_clear + n_cloud + n_invalid).all()
    ):
        raise RuntimeError("cloud pixel counts are internally inconsistent")
    if not np.allclose(
        fractions.to_numpy(float),
        (n_clear / n_domain).to_numpy(float),
        rtol=0,
        atol=1e-12,
    ):
        raise RuntimeError("cloud fractions disagree with clear/domain counts")
    independent_fraction = pd.to_numeric(
        cloud["cloud_survival_fraction_of_domain_independent_of_view"],
        errors="coerce",
    )
    if independent_fraction.isna().any() or not np.allclose(
        fractions.to_numpy(float),
        independent_fraction.to_numpy(float),
        rtol=0,
        atol=1e-12,
    ):
        raise RuntimeError("short and long independent-cloud fractions disagree")
    expected_assets = pd.to_numeric(
        cloud["n_expected_scene_tiles"], errors="raise"
    )
    resolved_assets = pd.to_numeric(
        cloud["n_resolved_cloud_assets"], errors="raise"
    )
    verified_assets = pd.to_numeric(
        cloud["n_verified_cloud_assets"], errors="raise"
    )
    asset_bytes = pd.to_numeric(cloud["cloud_asset_bytes"], errors="raise")
    if (
        (expected_assets <= 0).any()
        or not (expected_assets == resolved_assets).all()
        or not (expected_assets == verified_assets).all()
        or (asset_bytes <= 0).any()
        or not cloud["cloud_asset_set_sha256"]
        .astype(str)
        .str.fullmatch(r"[0-9a-f]{64}")
        .all()
        or not cloud["cloud_resolution_status"]
        .astype(str)
        .eq("observed_exhaustive_complete_independent_of_view")
        .all()
    ):
        raise RuntimeError("cloud asset provenance is incomplete or inconsistent")
    fraction_sum = float(fractions.sum())
    planning_floor = math.floor(fraction_sum)
    if not np.isclose(
        fraction_sum,
        float(validation["planning_pass_equivalent_sum"]),
        rtol=0,
        atol=1e-10,
    ) or planning_floor != int(validation["planning_pass_equivalent_floor"]):
        raise RuntimeError("cloud validation total/floor disagrees with pass summary")
    cloud["cloud_survival_fraction_of_domain"] = fractions
    provenance = _validate_d0035_provenance(geometry, validation)
    validation = dict(validation)
    validation["_d0035_provenance"] = provenance
    validation["_upstream_provenance"] = provenance
    return screened, cloud.drop(columns="orbit_key"), validation


def _candidate_passes(
    screened: pd.DataFrame, cloud_summary: pd.DataFrame
) -> pd.DataFrame:
    candidate_mask = _candidate_mask(screened)
    if ACTIVE_PROFILE == D0047_PROFILE:
        included = _profile_included_mask(
            screened, label="D0047 combined geometry/cloud screen"
        )
        candidate_mask = included & candidate_mask
    candidates = screened.loc[candidate_mask].copy()
    if candidates.empty:
        raise ValueError("no pass survived the frozen near-nadir quality gate")
    candidates["acquisition_utc"] = _utc_series(
        candidates["acquisition_utc"], label="candidate acquisition_utc"
    ).to_numpy()
    candidates["orbit_key"] = _orbit_key(candidates["orbit"])
    cloud = cloud_summary.copy()
    cloud["orbit_key"] = _orbit_key(cloud["orbit"])
    candidates = candidates.drop(
        columns=["cloud_survival_fraction_of_domain"], errors="ignore"
    )
    candidates = candidates.merge(
        cloud[["city", "orbit_key", "cloud_survival_fraction_of_domain"]],
        on=["city", "orbit_key"],
        how="left",
        validate="one_to_one",
    ).drop(columns="orbit_key")
    if candidates["cloud_survival_fraction_of_domain"].isna().any():
        raise AssertionError("candidate-specific cloud join is incomplete")
    return candidates.sort_values(["city", "acquisition_utc", "orbit"])


def _hrrr_seal_contract(
    validation: dict[str, Any],
    candidates: pd.DataFrame,
) -> tuple[str, dict[str, Any] | None]:
    """Return the exact seal label/profile binding required for this cohort."""

    if ACTIVE_PROFILE == D0035_PROFILE:
        return "PASS_EXACT_HRRR_RUN_SEAL", None
    provenance = validation.get("_upstream_provenance")
    if not isinstance(provenance, dict):
        raise RuntimeError("D0047 HRRR planning lacks current upstream provenance")
    binding = {
        "decision_id": D0047_DECISION_ID,
        "analysis_profile": "D0047_archive_available",
        "scientific_gate_scope": "archive_available_only",
        "profile_scope_label": D0047_SCOPE_LABEL,
        "geometry_passing_candidate_count": int(len(candidates)),
        "combined_validation_path": str(COMBINED_VALIDATION.relative_to(ROOT)),
        "combined_validation_sha256": _sha256(COMBINED_VALIDATION),
        "upstream_run_record_path": str(provenance["run_record_path"]),
        "upstream_run_record_sha256": str(provenance["run_record_sha256"]),
        "candidate_availability_ledger_path": str(
            provenance["candidate_availability_ledger_path"]
        ),
        "candidate_availability_ledger_sha256": str(
            provenance["candidate_availability_ledger_sha256"]
        ),
        "exclusion_summary_path": str(provenance["exclusion_summary_path"]),
        "exclusion_summary_sha256": str(provenance["exclusion_summary_sha256"]),
    }
    return D0047_HRRR_RUN_SEAL_STATUS, binding


def _active_profile_summary() -> dict[str, Any]:
    """Return the non-secret identity/count seal for profile-scoped HRRR planning."""

    return {
        "decision_id": ACTIVE_PROFILE.decision_id,
        "analysis_profile": (
            "D0047_archive_available"
            if ACTIVE_PROFILE == D0047_PROFILE
            else "D0035_exhaustive"
        ),
        "scientific_gate_scope": (
            "archive_available_only"
            if ACTIVE_PROFILE == D0047_PROFILE
            else "exhaustive_942_candidates"
        ),
        "profile_scope_label": ACTIVE_PROFILE.scope_label,
        "original_metadata_candidate_count": ORIGINAL_METADATA_CANDIDATES,
        "excluded_pre_geometry_candidate_count": EXCLUDED_METADATA_CANDIDATES,
        "retained_geometry_candidate_count": RETAINED_METADATA_CANDIDATES,
    }


def summarize_hrrr_request_scope(
    candidates: pd.DataFrame,
    *,
    reference_index_path: Path = HRRR_SMOKE_INDEX,
) -> dict[str, Any]:
    """Calculate a write-free request scope and local-index storage projection."""

    manifest = build_hrrr_request_manifest(candidates)
    reference_bytes = hrrr_subset_bytes_from_index(
        reference_index_path.read_text(encoding="utf-8")
    )
    conservative_bytes = int(len(manifest) * reference_bytes * 2)
    max_hours_at_reference_size = int(
        DEFAULT_MAX_NEW_DATA_BYTES // (reference_bytes * 2)
    )
    acquisition = _utc_series(
        candidates["acquisition_utc"], label="candidate acquisition_utc"
    )
    city_hours = {
        str(city): int(len(build_hrrr_request_manifest(group)))
        for city, group in candidates.groupby("city", sort=True)
    }
    return {
        **_active_profile_summary(),
        "candidate_passes": int(len(candidates)),
        "unique_analysis_hours": int(len(manifest)),
        "analysis_hours_by_city": city_hours,
        "earliest_acquisition_utc": acquisition.min().isoformat(),
        "latest_acquisition_utc": acquisition.max().isoformat(),
        "local_smoke_reference_exact_subset_bytes_per_hour": int(reference_bytes),
        "local_smoke_reference_exact_subset_bytes_projection": int(
            len(manifest) * reference_bytes
        ),
        "requested_hrrr_fields": [
            "TMP:2 m above ground:anl",
            "DPT:2 m above ground:anl",
        ],
        "storage_safety_factor": 2.0,
        "two_x_conservative_bytes_projection": conservative_bytes,
        "max_new_data_bytes": DEFAULT_MAX_NEW_DATA_BYTES,
        "minimum_free_bytes_after_peak": DEFAULT_MIN_FREE_BYTES_AFTER_PEAK,
        "max_hours_at_local_reference_size": max_hours_at_reference_size,
        "projected_budget_headroom_bytes": int(
            DEFAULT_MAX_NEW_DATA_BYTES - conservative_bytes
        ),
        "within_four_gib_projection": bool(
            conservative_bytes <= DEFAULT_MAX_NEW_DATA_BYTES
        ),
        "scope_status": "in_memory_only_no_manifest_written",
    }


def review_hrrr_scope() -> dict[str, Any]:
    """Review the certified scope without writing a manifest or using network."""

    screened, cloud_summary, _ = _load_quality()
    candidates = _candidate_passes(screened, cloud_summary)
    return summarize_hrrr_request_scope(candidates)


def _load_manifest_for_current_gate(
    candidates: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Reject a missing or stale manifest before any NOAA index/data request."""

    if candidates is None:
        screened, cloud_summary, _ = _load_quality()
        candidates = _candidate_passes(screened, cloud_summary)
    expected = build_hrrr_request_manifest(candidates)
    actual = pd.read_csv(HRRR_MANIFEST)
    missing = set(expected.columns) - set(actual.columns)
    if missing:
        raise RuntimeError(f"HRRR manifest lacks {sorted(missing)}")

    def canonical(frame: pd.DataFrame) -> pd.DataFrame:
        normalized = frame[expected.columns].copy()
        normalized["analysis_utc"] = _utc_series(
            normalized["analysis_utc"], label="manifest analysis_utc"
        ).dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        for column in ("n_target_passes", "forecast_hour"):
            normalized[column] = pd.to_numeric(
                normalized[column], errors="raise"
            ).astype("int64")
        for column in set(expected.columns) - {
            "analysis_utc",
            "n_target_passes",
            "forecast_hour",
        }:
            normalized[column] = normalized[column].astype(str)
        return normalized.sort_values("item_id").reset_index(drop=True)

    if not canonical(actual).equals(canonical(expected)):
        raise RuntimeError(
            "HRRR manifest is stale or does not exactly match the current D0035 gate"
        )
    return actual


def plan_hrrr() -> pd.DataFrame:
    screened, cloud_summary, validation = _load_quality()
    candidates = _candidate_passes(screened, cloud_summary)
    manifest = build_hrrr_request_manifest(candidates, output_csv=HRRR_MANIFEST)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    plan = {
        "schema_version": 1,
        "n_near_nadir_passes": int(len(candidates)),
        "n_unique_hrrr_analysis_hours": int(len(manifest)),
        "earliest_analysis_utc": str(manifest["analysis_utc"].min()),
        "latest_analysis_utc": str(manifest["analysis_utc"].max()),
        "decision_id": validation["decision_id"],
        "analysis_profile": (
            "D0047_archive_available"
            if ACTIVE_PROFILE == D0047_PROFILE
            else "D0035_exhaustive"
        ),
        "scientific_gate_scope": (
            "archive_available_only"
            if ACTIVE_PROFILE == D0047_PROFILE
            else "exhaustive_942_candidates"
        ),
        "profile_scope_label": PROFILE_SCOPE_LABEL,
        "planning_count_status": PLANNING_COUNT_STATUS,
        "original_metadata_candidate_count": ORIGINAL_METADATA_CANDIDATES,
        "excluded_pre_geometry_candidate_count": EXCLUDED_METADATA_CANDIDATES,
        "retained_geometry_candidate_count": RETAINED_METADATA_CANDIDATES,
        "cloud_expected_pass_equivalents_total": float(
            validation["planning_pass_equivalent_sum"]
        ),
        "cloud_planning_pass_count_floor": int(
            validation["planning_pass_equivalent_floor"]
        ),
        "geometry_source": validation["geometry_source"],
        "geometry_pass_summary_sha256": _sha256(GEOMETRY_SUMMARY),
        "geometry_validation_sha256": _sha256(GEOMETRY_VALIDATION),
        "cloud_pass_summary_sha256": _sha256(CLOUD_SUMMARY),
        "combined_validation_sha256": _sha256(COMBINED_VALIDATION),
        "pre_cloud_geometry_screen_sha256": _sha256(SCREENED_PRE_CLOUD),
        "combined_quality_screen_sha256": _sha256(SCREENED_FINAL),
        "legacy_l2t_screen_sha256": _sha256(LEGACY_SCREENED),
        "hrrr_manifest": str(HRRR_MANIFEST.relative_to(ROOT)),
        "hrrr_manifest_sha256": _sha256(HRRR_MANIFEST),
        "guard_review": (
            f"Manifest contains only {validation['decision_id']} ECO_L1B_GEO.002 "
            f"geometry passes in scope {PROFILE_SCOPE_LABEL} after the exhaustive "
            "view-independent cloud census"
        ),
    }
    (OUTPUT / "hrrr_request_plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def _domains() -> dict[str, dict[str, Any]]:
    config = load_config(ROOT / "configs/v2_cities.toml")
    features = load_domain_features(
        ROOT / "data/raw/v2/domains/census_urban_areas.geojson", config
    )
    return {city: feature["geometry"] for city, feature in features.items()}


def estimate_hrrr_storage(*, max_workers: int) -> pd.DataFrame:
    """Download only NOAA index text and freeze a conservative byte review."""

    manifest = _load_manifest_for_current_gate()
    estimates = estimate_hrrr_subset_downloads(
        manifest,
        safety_factor=2.0,
        max_workers=max_workers,
    )
    conservative_total = int(estimates["conservative_new_data_bytes"].sum())
    if conservative_total > DEFAULT_MAX_NEW_DATA_BYTES:
        raise RuntimeError(
            f"HRRR estimate {conservative_total} exceeds the 4-GiB new-data budget"
        )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    profile_summary = _active_profile_summary()
    for field in ("decision_id", "analysis_profile", "scientific_gate_scope"):
        estimates[field] = profile_summary[field]
    estimates.to_csv(HRRR_STORAGE_ESTIMATE, index=False)
    review = {
        "schema_version": 1,
        **profile_summary,
        "manifest_path": str(HRRR_MANIFEST.relative_to(ROOT)),
        "manifest_sha256": _sha256(HRRR_MANIFEST),
        "n_analysis_hours": int(len(estimates)),
        "exact_subset_bytes_total": int(estimates["exact_subset_bytes"].sum()),
        "safety_factor": 2.0,
        "conservative_new_data_bytes_total": conservative_total,
        "max_new_data_bytes": DEFAULT_MAX_NEW_DATA_BYTES,
        "free_disk_bytes_at_review": int(shutil.disk_usage(ROOT).free),
        "estimate_table": str(HRRR_STORAGE_ESTIMATE.relative_to(ROOT)),
        "estimate_table_sha256": _sha256(HRRR_STORAGE_ESTIMATE),
        "review_status": "within_4_gib_budget",
    }
    HRRR_STORAGE_REVIEW.write_text(
        json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return estimates


def fetch_hrrr(*, max_hours: int, max_workers: int) -> None:
    screened, cloud_summary, validation = _load_quality()
    candidates = _candidate_passes(screened, cloud_summary)
    manifest = _load_manifest_for_current_gate(candidates)
    review = json.loads(HRRR_STORAGE_REVIEW.read_text(encoding="utf-8"))
    estimates = pd.read_csv(HRRR_STORAGE_ESTIMATE)
    profile_summary = _active_profile_summary()
    if (
        review.get("review_status") != "within_4_gib_budget"
        or review.get("manifest_sha256") != _sha256(HRRR_MANIFEST)
        or review.get("estimate_table_sha256") != _sha256(HRRR_STORAGE_ESTIMATE)
        or int(review.get("max_new_data_bytes", -1)) != DEFAULT_MAX_NEW_DATA_BYTES
        or any(review.get(field) != expected for field, expected in profile_summary.items())
    ):
        raise RuntimeError("HRRR storage review is absent, stale, or not approved")
    for field in ("decision_id", "analysis_profile", "scientific_gate_scope"):
        if field not in estimates or not estimates[field].astype(str).eq(
            str(profile_summary[field])
        ).all():
            raise RuntimeError("HRRR storage estimate has a stale profile binding")
    if set(estimates["item_id"].astype(str)) != set(manifest["item_id"].astype(str)):
        raise RuntimeError("HRRR storage estimate does not match the request manifest")
    estimate_map = estimates.set_index("item_id")[
        "conservative_new_data_bytes"
    ].astype(int).to_dict()
    os.environ.setdefault(
        "HERBIE_CONFIG_PATH", str(ROOT / "data/raw/v2/weather/herbie")
    )
    run_seal_status, profile_binding = _hrrr_seal_contract(validation, candidates)
    fetch_hrrr_domain_weather(
        manifest,
        _domains(),
        HRRR_ROOT,
        manifest_path=HRRR_MANIFEST,
        grib_cache_dir=HRRR_ROOT / "grib_cache",
        max_analysis_hours=max_hours,
        max_workers=max_workers,
        conservative_download_bytes_by_item=estimate_map,
        max_new_data_bytes=DEFAULT_MAX_NEW_DATA_BYTES,
        run_seal_status=run_seal_status,
        profile_binding=profile_binding,
    )


def _join_conditions(candidates: pd.DataFrame) -> pd.DataFrame:
    hourly = pd.read_csv(HRRR_ROOT / "hrrr_hourly_domain_summary.csv")
    axes = pd.read_csv(STEP1_AXES)
    daily = axes.rename(
        columns={
            "antecedent_dryness_30d_pct": "antecedent_dryness_percentile"
        }
    )
    joined = join_acquisition_time_conditions(
        candidates,
        hourly,
        daily,
        axes,
        strict=True,
    )
    if len(joined) != len(candidates):
        raise AssertionError("exact-acquisition weather join changed the pass count")
    return joined


def _assemble_complete_catalogue(
    base: pd.DataFrame,
    enriched_daytime: pd.DataFrame,
    screened: pd.DataFrame,
) -> pd.DataFrame:
    """Overlay both enrichment stages without reverting excluded daytime rows."""

    key_columns = ["city", "orbit"]
    for label, frame in (
        ("base", base),
        ("enriched daytime", enriched_daytime),
        ("final screen", screened),
    ):
        missing = set(key_columns) - set(frame.columns)
        if missing:
            raise ValueError(f"{label} catalogue lacks keys {sorted(missing)}")
        if frame.duplicated(key_columns).any():
            raise ValueError(f"{label} catalogue keys must be unique by city/orbit")

    base_keys = pd.MultiIndex.from_frame(base[key_columns])
    enriched_keys = pd.MultiIndex.from_frame(enriched_daytime[key_columns])
    screened_keys = pd.MultiIndex.from_frame(screened[key_columns])
    if not bool(enriched_keys.isin(base_keys).all()):
        raise ValueError("enriched daytime rows do not map exactly to the base catalogue")
    if not bool(screened_keys.isin(enriched_keys).all()):
        raise ValueError("final screened rows do not map exactly to enriched daytime rows")

    base_only = base.loc[~base_keys.isin(enriched_keys)].copy()
    enriched_only = enriched_daytime.loc[~enriched_keys.isin(screened_keys)].copy()
    full = pd.concat([base_only, enriched_only, screened], ignore_index=True, sort=False)
    full_keys = pd.MultiIndex.from_frame(full[key_columns])
    if (
        len(full) != len(base)
        or full_keys.duplicated().any()
        or not bool(base_keys.isin(full_keys).all())
        or not bool(full_keys.isin(base_keys).all())
    ):
        raise AssertionError("full physical-pass catalogue identity changed")
    sort_columns = [
        column for column in ("city", "acquisition_utc", "orbit") if column in full
    ]
    return full.sort_values(sort_columns).reset_index(drop=True)


def _complete_catalogue(conditioned: pd.DataFrame) -> pd.DataFrame:
    base = pd.read_csv(BASE_CATALOGUE)
    keys = pd.MultiIndex.from_frame(conditioned[["city", "orbit"]])
    if keys.duplicated().any():
        raise ValueError("conditioned catalogue keys must be unique by city/orbit")
    enriched_daytime = pd.read_csv(LEGACY_SCREENED)
    screened = _canonicalize_l1b_screen(pd.read_csv(SCREENED_FINAL))
    conditioned_columns = [
        "city",
        "orbit",
        "local_solar_date",
        "vpd_kpa_at_acquisition",
        "demand_percentile",
        "antecedent_dryness_percentile",
        "cloud_survival_fraction_of_domain",
    ]
    screened = screened.merge(
        conditioned[conditioned_columns],
        on=["city", "orbit"],
        how="left",
        validate="one_to_one",
    )
    if "view_zenith_abs_p95_deg" in screened:
        screened["view_zenith_deg"] = screened["view_zenith_abs_p95_deg"]
    return _assemble_complete_catalogue(base, enriched_daytime, screened)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _artifact_hash_ledger(paths: list[Path]) -> dict[str, str]:
    ledger: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            raise RuntimeError(f"Step-2 gate artifact is absent: {path}")
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(ROOT.resolve())
        except ValueError:
            raise RuntimeError(
                f"Step-2 gate artifact escaped the repository: {path}"
            ) from None
        ledger[str(relative)] = _sha256(resolved)
    return dict(sorted(ledger.items()))


def _d0047_attrition_table(catalogue: pd.DataFrame) -> pd.DataFrame:
    """Keep archive gaps separate from measured D0047 geometry failures."""

    required = {
        "city",
        "daytime",
        "geolocation_usable",
        "obstruction_flag",
        "near_nadir",
        ARCHIVE_AVAILABLE_STATUS_COLUMN,
        ARCHIVE_AVAILABLE_INCLUDED_COLUMN,
        "cloud_survival_fraction_of_domain",
    }
    missing = required - set(catalogue.columns)
    if missing:
        raise ValueError(f"D0047 attrition catalogue lacks {sorted(missing)}")
    daytime_all = _true_series(catalogue["daytime"], label="D0047 daytime")
    geolocation_all = _true_series(
        catalogue["geolocation_usable"], label="D0047 geolocation_usable"
    )
    unobstructed_all = ~_true_series(
        catalogue["obstruction_flag"], label="D0047 obstruction_flag"
    )
    pre_archive = daytime_all & geolocation_all & unobstructed_all
    profile_included = _nullable_true_series(
        catalogue[ARCHIVE_AVAILABLE_INCLUDED_COLUMN],
        label="D0047 attrition profile-included flag",
    )
    profile_status = catalogue[ARCHIVE_AVAILABLE_STATUS_COLUMN].astype("string")
    expected_status = profile_included.loc[pre_archive].map(
        {
            True: ARCHIVE_AVAILABLE_RETAINED_STATUS,
            False: ARCHIVE_AVAILABLE_EXCLUDED_STATUS,
        }
    )
    if (
        int(pre_archive.sum()) != ORIGINAL_METADATA_CANDIDATES
        or profile_included.loc[pre_archive].isna().any()
        or profile_included.loc[~pre_archive].notna().any()
        or int(profile_included.loc[pre_archive].fillna(False).sum())
        != RETAINED_METADATA_CANDIDATES
        or int((profile_included.loc[pre_archive] == False).sum())  # noqa: E712
        != EXCLUDED_METADATA_CANDIDATES
        or not profile_status.loc[pre_archive].reset_index(drop=True).equals(
            expected_status.astype("string").reset_index(drop=True)
        )
        or profile_status.loc[~pre_archive].notna().any()
    ):
        raise RuntimeError("D0047 attrition catalogue breaks the frozen profile census")
    rows: list[dict[str, Any]] = []
    stages = (
        "total_granules",
        "daytime_10_18_lst",
        "geolocation_best_good",
        "not_obstruction_flagged",
        "archive_available_pre_geometry",
        "near_nadir",
        "surviving_cloud_screening",
    )
    for city, group in catalogue.groupby("city", sort=True):
        daytime = daytime_all.loc[group.index]
        geolocation = geolocation_all.loc[group.index]
        unobstructed = unobstructed_all.loc[group.index]
        archive_available = profile_included.loc[group.index].fillna(False).astype(bool)
        near_nadir = _nullable_true_series(
            group["near_nadir"], label=f"{city} D0047 near_nadir"
        ).fillna(False)
        masks = [
            pd.Series(True, index=group.index),
            daytime,
            daytime & geolocation,
            daytime & geolocation & unobstructed,
            daytime & geolocation & unobstructed & archive_available,
            daytime & geolocation & unobstructed & archive_available & near_nadir,
        ]
        counts = [float(mask.sum()) for mask in masks]
        selected_weights = pd.to_numeric(
            group.loc[masks[-1], "cloud_survival_fraction_of_domain"],
            errors="coerce",
        )
        if selected_weights.isna().any() or not selected_weights.between(0, 1).all():
            raise RuntimeError(f"{city}: D0047 final cohort has invalid cloud weights")
        counts.append(float(selected_weights.sum()))
        for order, (stage, value) in enumerate(zip(stages, counts, strict=True), start=1):
            previous = counts[order - 2] if order > 1 else counts[0]
            rows.append(
                {
                    "city": city,
                    "stage_order": order,
                    "stage": stage,
                    "count_or_expected_count": value,
                    "stage_retention_pct": 100 * value / previous if previous else np.nan,
                    "total_retention_pct": 100 * value / counts[0] if counts[0] else np.nan,
                    "count_kind": "expected" if stage == stages[-1] else "observed",
                    "analysis_profile": "D0047_archive_available",
                    "scientific_gate_scope": "archive_available_only",
                    "archive_unavailable_is_geometry_failure": False,
                }
            )
    attrition = pd.DataFrame(rows)
    archive_rows = attrition.loc[
        attrition["stage"].eq("archive_available_pre_geometry")
    ]
    prior_rows = attrition.loc[
        attrition["stage"].eq("not_obstruction_flagged")
    ]
    excluded = float(prior_rows["count_or_expected_count"].sum()) - float(
        archive_rows["count_or_expected_count"].sum()
    )
    if not np.isclose(excluded, EXCLUDED_METADATA_CANDIDATES, rtol=0, atol=0):
        raise RuntimeError("D0047 attrition does not expose exactly 31 archive gaps")
    return attrition


def finalize() -> dict[str, Path | str]:
    screened, cloud_summary, validation = _load_quality()
    candidates = _candidate_passes(screened, cloud_summary)
    manifest = _load_manifest_for_current_gate(candidates)
    run_seal_status, profile_binding = _hrrr_seal_contract(validation, candidates)
    hrrr_seal = validate_hrrr_run_seal(
        HRRR_RUN_SEAL,
        manifest,
        _domains(),
        HRRR_ROOT,
        manifest_path=HRRR_MANIFEST,
        minimum_domain_cells=2,
        expected_status=run_seal_status,
        expected_profile_binding=profile_binding,
    )
    conditioned = _join_conditions(candidates)
    catalogue = _complete_catalogue(conditioned)
    recommendation_path = (
        ROOT / "data/processed/v2/task1/step1/memos/M1.1_feasibility_gate.md"
    )
    recommendation = recommendation_path.read_text(encoding="utf-8")
    solar_cases = pd.DataFrame(
        [
            {"case": "phoenix", "date": "2023-07-15", "latitude": 33.5014810, "longitude": -111.9611870},
            {"case": "atlanta", "date": "2023-07-15", "latitude": 33.8362691, "longitude": -84.3365018},
            {"case": "miami", "date": "2023-07-15", "latitude": 26.1955769, "longitude": -80.2284942},
        ]
    )
    paths = build_step2_deliverables(
        catalogue,
        cloud_summary,
        {},
        solar_cases,
        OUTPUT,
        step1_recommendation=recommendation,
        solar_check_engine="pvlib",
        pass_cloud_weight_column="cloud_survival_fraction_of_domain",
    )
    if ACTIVE_PROFILE == D0047_PROFILE:
        # Replace the generic attrition/catalogue views with profile-aware versions.
        # The generic helper treats nullable geometry checks as false; D0047 must
        # retain those 31 rows as pre-geometry archive exclusions instead.
        attrition = _d0047_attrition_table(catalogue)
        attrition.to_csv(Path(paths["T2.2"]), index=False)
        plot_attrition_waterfall(attrition, Path(paths["F2.3"]))
        catalogue.to_csv(Path(paths["catalogue"]), index=False)
        catalogue_excluded = catalogue[
            ARCHIVE_AVAILABLE_STATUS_COLUMN
        ].astype("string").eq(ARCHIVE_AVAILABLE_EXCLUDED_STATUS).fillna(False)
        if (
            int(catalogue_excluded.sum()) != EXCLUDED_METADATA_CANDIDATES
            or catalogue.loc[catalogue_excluded, "near_nadir"].notna().any()
        ):
            raise RuntimeError(
                "D0047 deliverable catalogue converted archive gaps to geometry failures"
            )

    conditioned["sampling_weight"] = conditioned[
        "cloud_survival_fraction_of_domain"
    ]
    conditioned["source_pass_id"] = (
        conditioned["city"].astype(str)
        + "|orbit_"
        + conditioned["orbit"].astype(str)
    )
    conditioned["template_geometry_status"] = OBSERVED_GEOMETRY_STATUS
    template_columns = [
        "source_pass_id",
        "city",
        "demand_percentile",
        "antecedent_dryness_percentile",
        "local_solar_time_hours",
        "solar_zenith_deg",
        "solar_azimuth_deg",
        "local_solar_date",
        "acquisition_utc",
        "sampling_weight",
        "template_geometry_status",
    ]
    template = conditioned[template_columns].copy()
    template_path = OUTPUT / "tables/step3_empirical_template.csv"
    template.to_csv(template_path, index=False)
    expected_by_city = conditioned.groupby("city")["sampling_weight"].sum().sort_index()
    expected_total = float(expected_by_city.sum())
    planning_count = math.floor(expected_total)
    if not np.isclose(
        expected_total,
        float(validation["planning_pass_equivalent_sum"]),
        rtol=0,
        atol=1e-10,
    ) or planning_count != int(validation["planning_pass_equivalent_floor"]):
        raise AssertionError("Step-3 planning count differs from the cloud gate")

    checks_path = Path(paths["checks"])
    checks = pd.read_csv(checks_path)
    if {"check", "pass", "detail"} - set(checks.columns):
        raise RuntimeError("Step-2 checks table lacks its machine-readable contract")
    check_pass = _true_series(checks["pass"], label="step2 check pass")
    all_checks_pass = bool(check_pass.all())
    gate_status = str(paths["gate"])
    provenance = validation.get("_upstream_provenance")
    if not isinstance(provenance, dict):
        raise RuntimeError("current upstream provenance was not attached to finalization")
    hrrr_shard_index = pd.read_csv(HRRR_ROOT / "hrrr_hourly_shard_index.csv")
    if "local_path" not in hrrr_shard_index:
        raise RuntimeError("exact HRRR shard index lacks local paths")
    hrrr_shards = [Path(str(value)) for value in hrrr_shard_index["local_path"]]
    artifact_paths = [
        value for value in paths.values() if isinstance(value, Path)
    ] + hrrr_shards + [
        template_path,
        HRRR_MANIFEST,
        OUTPUT / "hrrr_request_plan.json",
        HRRR_STORAGE_ESTIMATE,
        HRRR_STORAGE_REVIEW,
        HRRR_ROOT / "hrrr_checkpoint.json",
        HRRR_ROOT / "hrrr_hourly_shard_index.csv",
        HRRR_ROOT / "hrrr_hourly_domain_summary.csv",
        HRRR_RUN_SEAL,
        D0035_RUN_RECORD,
        D0035_SCENE_MANIFEST,
        D0035_ASSET_CHECKPOINT,
        D0035_GEOMETRY_CHECKPOINT,
        D0035_CLOUD_CHECKPOINT,
        GEOMETRY_SUMMARY,
        GEOMETRY_VALIDATION,
        CLOUD_SUMMARY,
        COMBINED_VALIDATION,
        SCREENED_PRE_CLOUD,
        SCREENED_FINAL,
        LEGACY_SCREENED,
    ]
    if ACTIVE_PROFILE == D0047_PROFILE:
        artifact_paths.extend(
            [
                path
                for path in (
                    AVAILABILITY_LEDGER,
                    PROFILE_VALIDATION,
                    D0047_EXCLUSION_SUMMARY,
                    D0047_ATTRITION_SUMMARY,
                    D0047_RETAINED_LINKS,
                )
                if path is not None
            ]
        )
    artifact_ledger = _artifact_hash_ledger(list(dict.fromkeys(artifact_paths)))
    analysis_profile = (
        "D0047_archive_available"
        if ACTIVE_PROFILE == D0047_PROFILE
        else "D0035_exhaustive"
    )
    scientific_gate_scope = (
        "archive_available_only"
        if ACTIVE_PROFILE == D0047_PROFILE
        else "exhaustive_942_candidates"
    )
    upstream_key = (
        "upstream_quality_profile"
        if ACTIVE_PROFILE == D0047_PROFILE
        else "upstream_d0035"
    )
    upstream_record = {
        "decision_id": D0035_DECISION_ID,
        "status": str(validation["gate_status"]),
        "scientific_gate_eligible": bool(validation["scientific_gate_eligible"]),
        "analysis_profile": analysis_profile,
        "scientific_gate_scope": scientific_gate_scope,
        "profile_scope_label": PROFILE_SCOPE_LABEL,
        "algorithm_version": str(provenance["algorithm_version"]),
        "run_record_path": str(provenance["run_record_path"]),
        "run_record_sha256": str(provenance["run_record_sha256"]),
        "provenance_counts": provenance["provenance_counts"],
        "provenance_sha256": provenance["provenance_sha256"],
    }
    if ACTIVE_PROFILE == D0047_PROFILE:
        upstream_record.update(
            {
                "candidate_availability_ledger_path": provenance[
                    "candidate_availability_ledger_path"
                ],
                "candidate_availability_ledger_sha256": provenance[
                    "candidate_availability_ledger_sha256"
                ],
                "exclusion_summary_path": provenance["exclusion_summary_path"],
                "exclusion_summary_sha256": provenance[
                    "exclusion_summary_sha256"
                ],
                "attrition_summary_path": provenance["attrition_summary_path"],
                "attrition_summary_sha256": provenance[
                    "attrition_summary_sha256"
                ],
                "retained_links_path": provenance["retained_links_path"],
                "retained_links_sha256": provenance["retained_links_sha256"],
                "original_exhaustive_gate_status": (
                    "STOP_D0035_INCOMPLETE_GEOMETRY"
                ),
                "restored_archive_sensitivity_required": True,
            }
        )
    gate_record = {
        "schema_version": STEP2_GATE_RECORD_SCHEMA_VERSION,
        "decision_id": D0035_DECISION_ID,
        "implementation_decision_id": D0035_IMPLEMENTATION_DECISION_ID,
        "band_mode_metadata_decision_id": D0054_BAND_MODE_DECISION_ID,
        "analysis_profile": analysis_profile,
        "scientific_gate_scope": scientific_gate_scope,
        "profile_scope_label": PROFILE_SCOPE_LABEL,
        "planning_count_status": PLANNING_COUNT_STATUS,
        "status": gate_status,
        "scientific_gate_eligible": bool(gate_status == "PASS"),
        "all_checks_pass": all_checks_pass,
        "checks_pass": all_checks_pass,
        "count_support_pass": bool(gate_status in {"PASS", "CONDITIONAL"}),
        "failure_domains": [
            domain
            for domain, failed in (
                ("count_support", gate_status == "STOP"),
                ("step2_checks", not all_checks_pass),
            )
            if failed
        ],
        "checks_path": str(checks_path.relative_to(ROOT)),
        "checks_sha256": _sha256(checks_path),
        "checks": [
            {
                "check": str(row["check"]),
                "pass": bool(passed),
                "detail": str(row["detail"]),
            }
            for row, passed in zip(
                checks.to_dict("records"), check_pass.tolist(), strict=True
            )
        ],
        upstream_key: upstream_record,
        "hrrr_run_seal": {
            "status": str(hrrr_seal["status"]),
            "path": str(HRRR_RUN_SEAL.relative_to(ROOT)),
            "sha256": _sha256(HRRR_RUN_SEAL),
            "manifest_canonical_sha256": str(
                hrrr_seal["manifest_canonical_sha256"]
            ),
            "frozen_domain_sha256": str(hrrr_seal["frozen_domain_sha256"]),
            "counts": hrrr_seal["counts"],
            "profile_binding": hrrr_seal.get("profile_binding"),
            "profile_binding_sha256": hrrr_seal.get("profile_binding_sha256"),
        },
        "counts": {
            "original_metadata_candidates": ORIGINAL_METADATA_CANDIDATES,
            "excluded_pre_geometry_candidates": EXCLUDED_METADATA_CANDIDATES,
            "retained_geometry_candidates": RETAINED_METADATA_CANDIDATES,
            "near_nadir_physical_passes": int(len(conditioned)),
            "expected_pass_equivalents_total": expected_total,
            "planning_pass_count_floor": planning_count,
            "step2_checks": int(len(checks)),
            "step2_checks_passed": int(check_pass.sum()),
        },
        "artifact_sha256": artifact_ledger,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
    }
    if gate_status == "PASS" and not all_checks_pass:
        raise RuntimeError("Step-2 PASS status disagrees with its check table")
    _atomic_json(STEP2_GATE_RECORD, gate_record)
    planning = {
        "schema_version": 4,
        "decision_id": str(validation["decision_id"]),
        "analysis_profile": analysis_profile,
        "scientific_gate_scope": scientific_gate_scope,
        "profile_scope_label": PROFILE_SCOPE_LABEL,
        "count_status": PLANNING_COUNT_STATUS,
        "step2_gate": str(paths["gate"]),
        "step2_gate_record_path": str(STEP2_GATE_RECORD.relative_to(ROOT)),
        "step2_gate_record_sha256": _sha256(STEP2_GATE_RECORD),
        "near_nadir_physical_passes": int(len(conditioned)),
        "original_metadata_candidate_count": ORIGINAL_METADATA_CANDIDATES,
        "excluded_pre_geometry_candidate_count": EXCLUDED_METADATA_CANDIDATES,
        "retained_geometry_candidate_count": RETAINED_METADATA_CANDIDATES,
        "expected_pass_equivalents_by_city": expected_by_city.to_dict(),
        "expected_pass_equivalents_total": expected_total,
        "planning_pass_count_floor": planning_count,
        "rounding_rule": (
            "floor(sum candidate-specific observed clear-domain fractions); "
            f"{validation['decision_id']}/D0029"
        ),
        "template_sampling_rule": (
            "all cloud-independent geometry-screened real passes retained and sampled "
            "proportional to each candidate's observed clear-domain fraction; zero "
            "weights retained"
        ),
        "template_path": str(template_path.relative_to(ROOT)),
        "template_sha256": _sha256(template_path),
        "hrrr_summary_sha256": _sha256(
            HRRR_ROOT / "hrrr_hourly_domain_summary.csv"
        ),
        "hrrr_run_seal_path": str(HRRR_RUN_SEAL.relative_to(ROOT)),
        "hrrr_run_seal_sha256": _sha256(HRRR_RUN_SEAL),
        "upstream_run_record_path": str(provenance["run_record_path"]),
        "upstream_run_record_sha256": str(provenance["run_record_sha256"]),
        "upstream_algorithm_version": str(provenance["algorithm_version"]),
        "upstream_provenance_counts": provenance["provenance_counts"],
        "upstream_provenance_sha256": provenance["provenance_sha256"],
        "geometry_pass_summary_path": str(GEOMETRY_SUMMARY.relative_to(ROOT)),
        "geometry_pass_summary_sha256": _sha256(GEOMETRY_SUMMARY),
        "geometry_validation_path": str(GEOMETRY_VALIDATION.relative_to(ROOT)),
        "geometry_validation_sha256": _sha256(GEOMETRY_VALIDATION),
        "quality_screen_path": str(SCREENED_FINAL.relative_to(ROOT)),
        "quality_screen_sha256": _sha256(SCREENED_FINAL),
        "legacy_quality_screen_path": str(LEGACY_SCREENED.relative_to(ROOT)),
        "legacy_quality_screen_sha256": _sha256(LEGACY_SCREENED),
        "cloud_pass_summary_path": str(CLOUD_SUMMARY.relative_to(ROOT)),
        "cloud_pass_summary_sha256": _sha256(CLOUD_SUMMARY),
        "cloud_validation_path": str(COMBINED_VALIDATION.relative_to(ROOT)),
        "cloud_validation_sha256": _sha256(COMBINED_VALIDATION),
    }
    if ACTIVE_PROFILE == D0047_PROFILE:
        planning.update(
            {
                "candidate_availability_ledger_path": provenance[
                    "candidate_availability_ledger_path"
                ],
                "candidate_availability_ledger_sha256": provenance[
                    "candidate_availability_ledger_sha256"
                ],
                "exclusion_summary_path": provenance["exclusion_summary_path"],
                "exclusion_summary_sha256": provenance[
                    "exclusion_summary_sha256"
                ],
                "attrition_summary_path": provenance["attrition_summary_path"],
                "attrition_summary_sha256": provenance[
                    "attrition_summary_sha256"
                ],
                "retained_links_path": provenance["retained_links_path"],
                "retained_links_sha256": provenance["retained_links_sha256"],
                "original_exhaustive_gate_status": (
                    "STOP_D0035_INCOMPLETE_GEOMETRY"
                ),
                "restored_archive_sensitivity_required": True,
            }
        )
    planning_path = OUTPUT / "step3_planning_count.json"
    planning_path.write_text(
        json.dumps(planning, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    paths["step3_template"] = template_path
    paths["step2_gate_record"] = STEP2_GATE_RECORD
    paths["step3_planning_count"] = planning_path
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        choices=(D0035_PROFILE.name, D0047_PROFILE.name),
        default=D0035_PROFILE.name,
        help="Frozen upstream quality profile and append-only output namespace",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("review-hrrr-scope")
    subparsers.add_parser("plan-hrrr")
    estimate_parser = subparsers.add_parser("estimate-hrrr-storage")
    estimate_parser.add_argument("--max-workers", type=int, default=8)
    fetch_parser = subparsers.add_parser("fetch-hrrr")
    fetch_parser.add_argument("--max-hours", type=int, required=True)
    fetch_parser.add_argument("--max-workers", type=int, default=4)
    subparsers.add_parser("finalize")
    args = parser.parse_args()
    configure_profile(
        D0047_PROFILE if args.profile == D0047_PROFILE.name else D0035_PROFILE
    )
    if args.command == "review-hrrr-scope":
        print(json.dumps(review_hrrr_scope(), indent=2, sort_keys=True))
    elif args.command == "plan-hrrr":
        manifest = plan_hrrr()
        print(f"planned {len(manifest)} HRRR analysis hours")
    elif args.command == "estimate-hrrr-storage":
        estimates = estimate_hrrr_storage(max_workers=args.max_workers)
        exact = int(estimates["exact_subset_bytes"].sum())
        conservative = int(estimates["conservative_new_data_bytes"].sum())
        print(
            f"reviewed {len(estimates)} HRRR hours: exact subset {exact} bytes; "
            f"conservative new-data estimate {conservative} bytes"
        )
    elif args.command == "fetch-hrrr":
        fetch_hrrr(max_hours=args.max_hours, max_workers=args.max_workers)
        print(f"wrote {HRRR_ROOT}")
    else:
        paths = finalize()
        print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
