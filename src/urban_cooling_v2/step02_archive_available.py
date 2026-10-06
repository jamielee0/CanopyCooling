#!/usr/bin/env python3
"""Decision-scoped D0047 archive-available Step-2 profile.

D0047 preserves the original 942-row metadata-candidate census while excluding
an entire city/orbit candidate before geometry whenever any required exact
``ECO_L1B_GEO.002`` scene is one of the 41 sealed archive gaps.  The exclusion
is not a geometry failure, zero-coverage observation, or imputation.  It changes
the estimand to the explicitly labelled 2018--2025 archive-available candidate
population.

Only metadata identities are handled here.  No geometry array, cloud array,
LST/thermal layer, 2026 record, or holdout result is opened by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

import pandas as pd

from .step02_l1b_geometry import frozen_geometry_targets


DECISION_ID = "D0047"
IMPLEMENTATION_DECISION_ID = "D0048"
RUN_ID = "R0011_D0047"
RUN_RECORD_SCHEMA_VERSION = 3
ALGORITHM_VERSION = "d0047-archive-available-l1b-dmrpp-pass-stream-v2"
TARGET_SCOPE = "archive_available_after_pre_geometry_exclusion_D0047"

CANDIDATE_STATUS_COLUMN = "d0047_candidate_status"
RETAINED_STATUS = "retained_archive_available"
EXCLUDED_STATUS = "archive_unavailable_pre_geometry"
EXCLUSION_REASON_COLUMN = "d0047_exclusion_reason"
EXCLUSION_REASON = "required_exact_ECO_L1B_GEO.002_scene_unavailable"
PROFILE_INCLUDED_COLUMN = "d0047_profile_included"
MISSING_SCENE_COUNT_COLUMN = "d0047_unavailable_scene_count"
MISSING_SCENE_KEYS_COLUMN = "d0047_unavailable_scene_keys"
REQUIRED_SCENE_COUNT_COLUMN = "d0047_required_scene_count"
AVAILABLE_SCENE_COUNT_COLUMN = "d0047_available_scene_count"

VALIDATION_ORIGINAL_CANDIDATES_FIELD = "original_metadata_candidate_count"
VALIDATION_EXCLUDED_CANDIDATES_FIELD = "excluded_pre_geometry_candidate_count"
VALIDATION_RETAINED_CANDIDATES_FIELD = "retained_geometry_candidate_count"
VALIDATION_ORIGINAL_LINKS_FIELD = "original_city_scene_link_count"
VALIDATION_RETAINED_LINKS_FIELD = "retained_city_scene_link_count"
VALIDATION_ORIGINAL_SCENES_FIELD = "original_unique_scene_count"
VALIDATION_MISSING_SCENES_FIELD = "sealed_unavailable_unique_scene_count"
VALIDATION_RETAINED_SCENES_FIELD = "retained_unique_scene_count"


@dataclass(frozen=True)
class ArchiveAvailableCounts:
    """Exact count identities frozen before D0047 geometry execution."""

    original_candidates: int
    excluded_candidates: int
    retained_candidates: int
    original_city_scene_links: int
    retained_city_scene_links: int
    original_unique_scenes: int
    missing_unique_scenes: int
    retained_unique_scenes: int


FROZEN_COUNTS = ArchiveAvailableCounts(
    original_candidates=942,
    excluded_candidates=31,
    retained_candidates=911,
    original_city_scene_links=1_404,
    retained_city_scene_links=1_355,
    original_unique_scenes=1_370,
    missing_unique_scenes=41,
    retained_unique_scenes=1_323,
)

FROZEN_EXCLUDED_BY_CITY = {
    "atlanta": 8,
    "los_angeles": 8,
    "miami": 1,
    "minneapolis_st_paul": 8,
    "phoenix": 6,
}
FROZEN_ORIGINAL_BY_CITY = {
    "atlanta": 196,
    "los_angeles": 196,
    "miami": 91,
    "minneapolis_st_paul": 266,
    "phoenix": 193,
}
FROZEN_RETAINED_BY_CITY = {
    "atlanta": 188,
    "los_angeles": 188,
    "miami": 90,
    "minneapolis_st_paul": 258,
    "phoenix": 187,
}
FROZEN_EXCLUDED_BY_YEAR = {2020: 24, 2024: 7}
FROZEN_EXCLUDED_BY_UTC_MONTH = {6: 8, 7: 4, 8: 13, 9: 6}
FROZEN_EXCLUDED_BY_TIME_STRATUM = {
    "10-12": 9,
    "12-14": 9,
    "14-16": 8,
    "16-18": 5,
}

LEDGER_ID_COLUMNS = (
    "city",
    "orbit",
    "acquisition_utc",
    "year",
    "month",
    "time_stratum",
    CANDIDATE_STATUS_COLUMN,
    PROFILE_INCLUDED_COLUMN,
    EXCLUSION_REASON_COLUMN,
    REQUIRED_SCENE_COUNT_COLUMN,
    AVAILABLE_SCENE_COUNT_COLUMN,
    MISSING_SCENE_COUNT_COLUMN,
    MISSING_SCENE_KEYS_COLUMN,
    "d0047_required_scene_keys",
    "d0047_profile_scope",
    "d0047_missing_scene_evidence_sha256",
    "decision_id",
    "lst_opened",
    "thermal_opened",
    "record_2026_opened",
    "holdout_status",
)


def _scene_key(orbit: Any, scene: Any) -> str:
    return f"{int(orbit):05d}_{int(scene):03d}"


def _sha256_records(records: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        records,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_missing_scene_census(
    missing_scenes: pd.DataFrame,
    *,
    counts: ArchiveAvailableCounts,
) -> tuple[pd.DataFrame, set[tuple[int, int]], str]:
    required = {"orbit", "scene"}
    absent = sorted(required.difference(missing_scenes.columns))
    if absent:
        raise ValueError(f"D0047 missing-scene evidence lacks columns: {absent}")
    sealed = missing_scenes.copy()
    sealed["orbit"] = pd.to_numeric(sealed["orbit"], errors="raise").astype(int)
    sealed["scene"] = pd.to_numeric(sealed["scene"], errors="raise").astype(int)
    if sealed.duplicated(["orbit", "scene"]).any():
        raise ValueError("D0047 missing-scene evidence contains duplicate identities")
    if len(sealed) != counts.missing_unique_scenes:
        raise ValueError(
            "D0047 missing-scene count changed: "
            f"expected {counts.missing_unique_scenes}, found {len(sealed)}"
        )
    if "geometry_values_opened" in sealed.columns:
        values = sealed["geometry_values_opened"].astype("string").str.casefold()
        if (~values.isin(["false", "0"])).any():
            raise ValueError("D0047 source evidence indicates geometry values were opened")
    if "identity_resolution_status" in sealed.columns:
        if (~sealed["identity_resolution_status"].astype(str).eq("unresolved_missing")).any():
            raise ValueError("D0047 source evidence contains a resolved scene identity")
    keys = set(
        map(
            tuple,
            sealed[["orbit", "scene"]].to_records(index=False),
        )
    )
    evidence_columns = [
        column
        for column in (
            "orbit",
            "scene",
            "geo_granule_id",
            "cmr_response_sha256",
            "identity_resolution_status",
        )
        if column in sealed.columns
    ]
    records = (
        sealed[evidence_columns]
        .sort_values(["orbit", "scene"], kind="stable")
        .to_dict("records")
    )
    return sealed, keys, _sha256_records(records)


def build_archive_available_profile(
    screened_passes: pd.DataFrame,
    latest_view_manifest: pd.DataFrame,
    missing_scenes: pd.DataFrame,
    *,
    counts: ArchiveAvailableCounts = FROZEN_COUNTS,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Return the 942-row D0047 ledger, retained links, and validation.

    The D0035 census is reconstructed first and validated against its original
    count identities.  Exclusion is then a deterministic anti-join on the
    sealed exact orbit/scene gaps.  Every candidate touching at least one such
    scene is excluded in full, including any otherwise available companion
    scene belonging to the same city/orbit pass.
    """

    candidates, original_links = frozen_geometry_targets(
        screened_passes,
        latest_view_manifest,
        expected_candidates=counts.original_candidates,
        expected_city_scene_links=counts.original_city_scene_links,
        expected_unique_scenes=None,
    )
    sealed_missing, missing_keys, evidence_sha256 = _validate_missing_scene_census(
        missing_scenes,
        counts=counts,
    )
    original_unique_scenes = original_links[["orbit", "scene"]].drop_duplicates()
    if len(original_unique_scenes) != counts.original_unique_scenes:
        raise ValueError(
            "D0047 original unique-scene count changed: "
            f"expected {counts.original_unique_scenes}, "
            f"found {len(original_unique_scenes)}"
        )
    observed_link_keys = set(map(tuple, original_unique_scenes.to_records(index=False)))
    if not missing_keys.issubset(observed_link_keys):
        raise ValueError("D0047 missing-scene evidence is outside the D0035 scene map")

    links = original_links.copy()
    links["d0047_scene_key"] = [
        _scene_key(orbit, scene)
        for orbit, scene in links[["orbit", "scene"]].itertuples(index=False)
    ]
    links["d0047_scene_archive_available"] = [
        (int(orbit), int(scene)) not in missing_keys
        for orbit, scene in links[["orbit", "scene"]].itertuples(index=False)
    ]

    grouped = links.groupby(["city", "orbit"], sort=True)
    candidate_scene_rows: list[dict[str, Any]] = []
    for (city, orbit), group in grouped:
        required_keys = sorted(group["d0047_scene_key"].astype(str))
        missing = sorted(
            group.loc[
                ~group["d0047_scene_archive_available"], "d0047_scene_key"
            ].astype(str)
        )
        candidate_scene_rows.append(
            {
                "city": str(city),
                "orbit": int(orbit),
                REQUIRED_SCENE_COUNT_COLUMN: int(len(group)),
                AVAILABLE_SCENE_COUNT_COLUMN: int(len(group) - len(missing)),
                MISSING_SCENE_COUNT_COLUMN: int(len(missing)),
                MISSING_SCENE_KEYS_COLUMN: ";".join(missing),
                "d0047_required_scene_keys": ";".join(required_keys),
            }
        )
    candidate_scenes = pd.DataFrame(candidate_scene_rows)
    ledger = candidates.merge(
        candidate_scenes,
        on=["city", "orbit"],
        how="left",
        validate="one_to_one",
    )
    if ledger[REQUIRED_SCENE_COUNT_COLUMN].isna().any():
        raise ValueError("D0047 ledger lost a D0035 candidate-to-scene mapping")
    excluded = ledger[MISSING_SCENE_COUNT_COLUMN].gt(0)
    ledger[CANDIDATE_STATUS_COLUMN] = excluded.map(
        {True: EXCLUDED_STATUS, False: RETAINED_STATUS}
    )
    ledger[PROFILE_INCLUDED_COLUMN] = ~excluded
    ledger[EXCLUSION_REASON_COLUMN] = ""
    ledger.loc[excluded, EXCLUSION_REASON_COLUMN] = EXCLUSION_REASON
    ledger["d0047_profile_scope"] = TARGET_SCOPE
    ledger["d0047_missing_scene_evidence_sha256"] = evidence_sha256
    ledger["decision_id"] = DECISION_ID
    ledger["lst_opened"] = False
    ledger["thermal_opened"] = False
    ledger["record_2026_opened"] = False
    ledger["holdout_status"] = "UNSELECTED"
    ledger["acquisition_utc"] = pd.to_datetime(
        ledger["acquisition_utc"], errors="raise", utc=True, format="mixed"
    )
    years = ledger["acquisition_utc"].dt.year
    if not years.between(2018, 2025).all():
        raise ValueError("D0047 candidate ledger must stay inside frozen 2018-2025")
    ledger["year"] = years.astype(int)
    ledger["month"] = ledger["acquisition_utc"].dt.month.astype(int)
    ledger["acquisition_utc"] = ledger["acquisition_utc"].map(
        lambda value: value.isoformat()
    )

    retained_keys = set(
        map(
            tuple,
            ledger.loc[
                ledger[PROFILE_INCLUDED_COLUMN], ["city", "orbit"]
            ].to_records(index=False),
        )
    )
    retained_links = links.loc[
        [
            (str(city), int(orbit)) in retained_keys
            for city, orbit in links[["city", "orbit"]].itertuples(index=False)
        ]
    ].copy()
    if (~retained_links["d0047_scene_archive_available"]).any():
        raise ValueError("D0047 retained links contain a sealed unavailable scene")
    retained_links["decision_id"] = DECISION_ID
    retained_links["d0047_profile_scope"] = TARGET_SCOPE
    retained_links = retained_links.sort_values(
        ["city", "orbit", "scene"], kind="stable"
    ).reset_index(drop=True)

    observed = {
        VALIDATION_ORIGINAL_CANDIDATES_FIELD: int(len(ledger)),
        VALIDATION_EXCLUDED_CANDIDATES_FIELD: int(excluded.sum()),
        VALIDATION_RETAINED_CANDIDATES_FIELD: int((~excluded).sum()),
        VALIDATION_ORIGINAL_LINKS_FIELD: int(len(original_links)),
        VALIDATION_RETAINED_LINKS_FIELD: int(len(retained_links)),
        VALIDATION_ORIGINAL_SCENES_FIELD: int(len(original_unique_scenes)),
        VALIDATION_MISSING_SCENES_FIELD: int(len(sealed_missing)),
        VALIDATION_RETAINED_SCENES_FIELD: int(
            retained_links[["orbit", "scene"]].drop_duplicates().shape[0]
        ),
    }
    expected = {
        VALIDATION_ORIGINAL_CANDIDATES_FIELD: counts.original_candidates,
        VALIDATION_EXCLUDED_CANDIDATES_FIELD: counts.excluded_candidates,
        VALIDATION_RETAINED_CANDIDATES_FIELD: counts.retained_candidates,
        VALIDATION_ORIGINAL_LINKS_FIELD: counts.original_city_scene_links,
        VALIDATION_RETAINED_LINKS_FIELD: counts.retained_city_scene_links,
        VALIDATION_ORIGINAL_SCENES_FIELD: counts.original_unique_scenes,
        VALIDATION_MISSING_SCENES_FIELD: counts.missing_unique_scenes,
        VALIDATION_RETAINED_SCENES_FIELD: counts.retained_unique_scenes,
    }
    mismatches = {
        key: {"expected": expected[key], "observed": value}
        for key, value in observed.items()
        if int(value) != int(expected[key])
    }
    if mismatches:
        raise ValueError(
            "D0047 archive-available count seal mismatch: "
            + json.dumps(mismatches, sort_keys=True)
        )
    excluded_table = ledger.loc[excluded].copy()
    if counts == FROZEN_COUNTS:
        frozen_distributions = {
            "excluded_by_city": (
                excluded_table.groupby("city", sort=True).size().astype(int).to_dict(),
                FROZEN_EXCLUDED_BY_CITY,
            ),
            "original_by_city": (
                ledger.groupby("city", sort=True).size().astype(int).to_dict(),
                FROZEN_ORIGINAL_BY_CITY,
            ),
            "retained_by_city": (
                ledger.loc[~excluded]
                .groupby("city", sort=True)
                .size()
                .astype(int)
                .to_dict(),
                FROZEN_RETAINED_BY_CITY,
            ),
            "excluded_by_year": (
                excluded_table.groupby("year", sort=True).size().astype(int).to_dict(),
                FROZEN_EXCLUDED_BY_YEAR,
            ),
            "excluded_by_utc_month": (
                excluded_table.groupby("month", sort=True).size().astype(int).to_dict(),
                FROZEN_EXCLUDED_BY_UTC_MONTH,
            ),
            "excluded_by_time_stratum": (
                excluded_table.groupby("time_stratum", sort=True)
                .size()
                .astype(int)
                .to_dict(),
                FROZEN_EXCLUDED_BY_TIME_STRATUM,
            ),
        }
        distribution_mismatches = {
            label: {"expected": expected_values, "observed": observed_values}
            for label, (observed_values, expected_values) in frozen_distributions.items()
            if observed_values != expected_values
        }
        if distribution_mismatches:
            raise ValueError(
                "D0047 structured attrition seal mismatch: "
                + json.dumps(distribution_mismatches, sort_keys=True)
            )
    candidate_keys = ledger[["city", "orbit"]]
    retained_candidate_keys = ledger.loc[
        ledger[PROFILE_INCLUDED_COLUMN], ["city", "orbit"]
    ]
    exact_retained_keys = set(map(tuple, retained_candidate_keys.to_records(index=False)))
    observed_retained_keys = set(
        map(
            tuple,
            retained_links[["city", "orbit"]].drop_duplicates().to_records(index=False),
        )
    )
    ledger_complete = bool(
        not candidate_keys.duplicated().any()
        and exact_retained_keys == observed_retained_keys
        and ledger.loc[excluded, EXCLUSION_REASON_COLUMN].eq(EXCLUSION_REASON).all()
        and ledger.loc[~excluded, EXCLUSION_REASON_COLUMN].eq("").all()
        and ledger.loc[excluded, MISSING_SCENE_COUNT_COLUMN].gt(0).all()
        and ledger.loc[~excluded, MISSING_SCENE_COUNT_COLUMN].eq(0).all()
    )
    validation: dict[str, Any] = {
        "schema_version": 1,
        "decision_id": DECISION_ID,
        "implementation_decision_id": IMPLEMENTATION_DECISION_ID,
        "algorithm_version": ALGORITHM_VERSION,
        "target_scope": TARGET_SCOPE,
        **observed,
        "candidate_ledger_complete": ledger_complete,
        "retained_candidate_keys_exact": exact_retained_keys == observed_retained_keys,
        "whole_candidate_exclusion_rule": True,
        "missing_scene_imputation_used": False,
        "missing_scene_zero_coverage_assigned": False,
        "adjacent_scene_substitution_used": False,
        "geometry_values_opened": False,
        "cloud_values_opened": False,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
        "missing_scene_evidence_sha256": evidence_sha256,
        "excluded_by_city": (
            excluded_table.groupby("city", sort=True).size().astype(int).to_dict()
        ),
        "original_by_city": (
            ledger.groupby("city", sort=True).size().astype(int).to_dict()
        ),
        "retained_by_city": (
            ledger.loc[~excluded]
            .groupby("city", sort=True)
            .size()
            .astype(int)
            .to_dict()
        ),
        "excluded_by_year": (
            excluded_table.groupby("year", sort=True).size().astype(int).to_dict()
        ),
        "excluded_by_utc_month": (
            excluded_table.groupby("month", sort=True).size().astype(int).to_dict()
        ),
        "excluded_by_time_stratum": (
            excluded_table.groupby("time_stratum", sort=True)
            .size()
            .astype(int)
            .to_dict()
        ),
        "profile_gate_status": (
            "PASS_D0047_ARCHIVE_AVAILABLE_PROFILE_SEALED"
            if ledger_complete
            else "STOP_D0047_ARCHIVE_AVAILABLE_PROFILE_INVALID"
        ),
    }
    if not ledger_complete:
        raise ValueError("D0047 archive-available ledger integrity check failed")
    return (
        ledger.sort_values(["city", "acquisition_utc", "orbit"], kind="stable")
        .reset_index(drop=True),
        retained_links,
        validation,
    )


def candidate_availability_ledger(profile_candidates: pd.DataFrame) -> pd.DataFrame:
    """Return the compact, row-complete D0047 exclusion ledger artifact."""

    missing = sorted(set(LEDGER_ID_COLUMNS).difference(profile_candidates.columns))
    if missing:
        raise ValueError(f"D0047 profile candidates lack ledger columns: {missing}")
    return profile_candidates[list(LEDGER_ID_COLUMNS)].copy()


def exclusion_summary(profile_candidates: pd.DataFrame) -> pd.DataFrame:
    """Report structured exclusions by city/year/month/time stratum."""

    required = {
        "city",
        "year",
        "month",
        "time_stratum",
        CANDIDATE_STATUS_COLUMN,
    }
    missing = sorted(required.difference(profile_candidates.columns))
    if missing:
        raise ValueError(f"D0047 profile candidates lack summary columns: {missing}")
    dimensions = ["city", "year", "month", "time_stratum"]
    output = (
        profile_candidates.assign(
            excluded_pre_geometry=profile_candidates[CANDIDATE_STATUS_COLUMN].eq(
                EXCLUDED_STATUS
            ),
            retained_archive_available=profile_candidates[CANDIDATE_STATUS_COLUMN].eq(
                RETAINED_STATUS
            ),
        )
        .groupby(dimensions, dropna=False, sort=True)
        .agg(
            original_candidate_count=("orbit", "size"),
            excluded_pre_geometry_candidate_count=(
                "excluded_pre_geometry",
                "sum",
            ),
            retained_geometry_candidate_count=(
                "retained_archive_available",
                "sum",
            ),
        )
        .reset_index()
    )
    output["decision_id"] = DECISION_ID
    output["target_scope"] = TARGET_SCOPE
    return output


def archive_unavailable_exclusions(
    profile_candidates: pd.DataFrame,
) -> pd.DataFrame:
    """Return the supplementary row set for the 31 excluded candidates."""

    ledger = candidate_availability_ledger(profile_candidates)
    output = ledger.loc[
        ledger[CANDIDATE_STATUS_COLUMN].eq(EXCLUDED_STATUS)
    ].copy()
    if len(profile_candidates) == FROZEN_COUNTS.original_candidates and len(output) != (
        FROZEN_COUNTS.excluded_candidates
    ):
        raise ValueError("D0047 supplementary exclusion row count is not exactly 31")
    return output.reset_index(drop=True)


__all__ = [
    "ALGORITHM_VERSION",
    "ArchiveAvailableCounts",
    "AVAILABLE_SCENE_COUNT_COLUMN",
    "CANDIDATE_STATUS_COLUMN",
    "DECISION_ID",
    "EXCLUDED_STATUS",
    "EXCLUSION_REASON",
    "EXCLUSION_REASON_COLUMN",
    "FROZEN_EXCLUDED_BY_CITY",
    "FROZEN_EXCLUDED_BY_TIME_STRATUM",
    "FROZEN_EXCLUDED_BY_UTC_MONTH",
    "FROZEN_EXCLUDED_BY_YEAR",
    "FROZEN_COUNTS",
    "FROZEN_ORIGINAL_BY_CITY",
    "FROZEN_RETAINED_BY_CITY",
    "IMPLEMENTATION_DECISION_ID",
    "LEDGER_ID_COLUMNS",
    "MISSING_SCENE_COUNT_COLUMN",
    "MISSING_SCENE_KEYS_COLUMN",
    "PROFILE_INCLUDED_COLUMN",
    "REQUIRED_SCENE_COUNT_COLUMN",
    "RETAINED_STATUS",
    "RUN_ID",
    "RUN_RECORD_SCHEMA_VERSION",
    "TARGET_SCOPE",
    "VALIDATION_EXCLUDED_CANDIDATES_FIELD",
    "VALIDATION_MISSING_SCENES_FIELD",
    "VALIDATION_ORIGINAL_CANDIDATES_FIELD",
    "VALIDATION_ORIGINAL_LINKS_FIELD",
    "VALIDATION_ORIGINAL_SCENES_FIELD",
    "VALIDATION_RETAINED_CANDIDATES_FIELD",
    "VALIDATION_RETAINED_LINKS_FIELD",
    "VALIDATION_RETAINED_SCENES_FIELD",
    "archive_unavailable_exclusions",
    "build_archive_available_profile",
    "candidate_availability_ledger",
    "exclusion_summary",
]
