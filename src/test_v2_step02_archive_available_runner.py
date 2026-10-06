#!/usr/bin/env python3
"""Offline integration tests for the D0047 geometry/cloud runner adapter."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

import run_v2_step02_archive_available as runner
from urban_cooling_v2.step02_archive_available import (
    CANDIDATE_STATUS_COLUMN,
    EXCLUDED_STATUS,
    FROZEN_COUNTS,
    RETAINED_STATUS,
    build_archive_available_profile,
)


def _profile_and_links() -> tuple[pd.DataFrame, pd.DataFrame]:
    screened, views, missing = runner._profile_inputs()
    candidates, links, _ = build_archive_available_profile(screened, views, missing)
    return candidates, links


def _resolved_row(candidate: dict) -> dict:
    acquisition = pd.Timestamp(candidate["acquisition_utc"])
    return {
        "city": str(candidate["city"]),
        "orbit": int(candidate["orbit"]),
        "acquisition_utc": acquisition.isoformat(),
        "year": int(acquisition.year),
        "metadata_candidate": True,
        "n_l1b_geo_scenes": int(candidate["d0047_required_scene_count"]),
        "n_domain_pixels": 100,
        "n_view_valid_pixels": 95,
        "view_valid_fraction": 0.95,
        "view_zenith_abs_min_deg": 1.0,
        "view_zenith_abs_median_deg": 5.0,
        "view_zenith_abs_mean_deg": 5.0,
        "view_zenith_abs_p95_deg": 10.0,
        "view_zenith_abs_max_deg": 12.0,
        "near_nadir_threshold_deg": 20.0,
        "minimum_view_coverage": 0.95,
        "near_nadir": True,
        "n_overlapping_valid_pixels": 0,
        "overlap_rule": "retain largest absolute finite L1B view zenith across scenes",
        "geometry_source": "ECO_L1B_GEO.002",
        "l1b_geometry_covered_cells": 95,
        "l1b_geometry_domain_cells": 100,
        "l1b_geometry_coverage_fraction": 0.95,
        "l1b_view_zenith_abs_p95_deg": 10.0,
        "l1b_geometry_complete": True,
        "l1b_geometry_status": "geometry_pass",
        "quality_candidate_pre_cloud_l1b": True,
        "quality_candidate_pre_cloud": True,
        "quality_candidate_pre_cloud_l2t_invalid": bool(
            candidate["quality_candidate_pre_cloud"]
        ),
        "geometry_resolution_status": "geometry_pass",
        "geometry_definitive": True,
        "quality_candidate_pre_cloud_geometry_only": True,
        "geometry_error_type": np.nan,
        "scene_source_evidence_sha256": "a" * 64,
        "scene_map_set_sha256": "b" * 64,
        "decision_id": "D0047",
        CANDIDATE_STATUS_COLUMN: RETAINED_STATUS,
        "d0047_profile_included": True,
        "d0047_exclusion_reason": "",
        "d0047_required_scene_count": int(candidate["d0047_required_scene_count"]),
        "d0047_available_scene_count": int(candidate["d0047_available_scene_count"]),
        "d0047_unavailable_scene_count": 0,
        "d0047_unavailable_scene_keys": "",
        "d0047_profile_scope": runner.TARGET_SCOPE,
    }


def _complete_summary(profile: pd.DataFrame) -> pd.DataFrame:
    retained = profile.loc[
        profile[CANDIDATE_STATUS_COLUMN].eq(RETAINED_STATUS)
    ]
    resolved = pd.DataFrame(
        [_resolved_row(row) for row in retained.to_dict("records")]
    )
    excluded = runner._excluded_geometry_rows(profile)
    return pd.concat([resolved, excluded], ignore_index=True, sort=False).sort_values(
        ["city", "acquisition_utc", "orbit"], kind="stable"
    ).reset_index(drop=True)


class ArchiveAvailableRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base_patch = runner._configured_base()
        cls.base_patch.__enter__()
        cls.addClassCleanup(cls.base_patch.__exit__, None, None, None)
        cls.profile, cls.links = _profile_and_links()
        cls.summary = _complete_summary(cls.profile)

    def test_manifest_decorator_uses_d0047_1323_scene_seal(self) -> None:
        results: list[dict] = []
        for orbit, scene in (
            self.links[["orbit", "scene"]]
            .drop_duplicates()
            .sort_values(["orbit", "scene"])
            .itertuples(index=False)
        ):
            path = (
                runner.SOURCE_D0035_CMR_CACHE
                / f"{int(orbit):05d}_{int(scene):03d}.json"
            )
            document = json.loads(path.read_text(encoding="utf-8"))
            results.extend(document["results"])
        with tempfile.TemporaryDirectory(prefix="d0047-manifest-test-") as temporary:
            destination = Path(temporary) / "l1b_geo_scene_manifest.csv"
            previous_runner = runner.SCENE_MANIFEST
            previous_base = runner.base.SCENE_MANIFEST
            runner.SCENE_MANIFEST = destination
            runner.base.SCENE_MANIFEST = destination
            try:
                manifest = runner._decorate_scene_manifest(self.links, results)
            finally:
                runner.SCENE_MANIFEST = previous_runner
                runner.base.SCENE_MANIFEST = previous_base
        self.assertEqual(len(manifest), FROZEN_COUNTS.retained_unique_scenes)
        self.assertTrue(manifest["status"].eq("available").all())
        self.assertEqual(set(manifest["decision_id"]), {"D0047"})
        self.assertEqual(set(manifest["target_scope"]), {runner.TARGET_SCOPE})

    def test_separate_validator_accepts_911_and_null_31(self) -> None:
        validation = runner._build_geometry_validation(self.summary)
        self.assertTrue(validation["geometry_complete"])
        self.assertEqual(validation["original_metadata_candidate_count"], 942)
        self.assertEqual(validation["excluded_pre_geometry_candidate_count"], 31)
        self.assertEqual(validation["retained_geometry_candidate_count"], 911)
        self.assertEqual(validation["resolved_geometry_candidate_count"], 911)
        self.assertEqual(validation["excluded_geometry_metric_null_row_count"], 31)
        self.assertEqual(validation["geometry_passing_candidate_count"], 911)
        self.assertEqual(
            validation["canonical_status"],
            "GEOMETRY_SEALED_AWAITING_EXHAUSTIVE_CLOUD_D0047",
        )

    def test_exclusion_zero_is_not_accepted_as_null(self) -> None:
        corrupted = self.summary.copy()
        index = corrupted.index[
            corrupted[CANDIDATE_STATUS_COLUMN].eq(EXCLUDED_STATUS)
        ][0]
        corrupted.loc[index, "n_view_valid_pixels"] = 0
        validation = runner._build_geometry_validation(corrupted)
        self.assertFalse(validation["geometry_complete"])
        self.assertIn(
            "n_view_valid_pixels", validation["excluded_geometry_nonnull_columns"]
        )

    def test_canonical_table_keeps_942_and_null_exclusion_checks(self) -> None:
        canonical = runner._canonical_pre_cloud_table(self.profile, self.summary)
        self.assertEqual(len(canonical), FROZEN_COUNTS.original_candidates)
        excluded = canonical[CANDIDATE_STATUS_COLUMN].eq(EXCLUDED_STATUS)
        retained = canonical[CANDIDATE_STATUS_COLUMN].eq(RETAINED_STATUS)
        excluded_null_columns = sorted(
            set(runner._NULL_EXCLUDED_GEOMETRY_COLUMNS).union(
                column
                for column in canonical.columns
                if column.endswith("_l2t_invalid")
            )
        )
        self.assertFalse(set(excluded_null_columns).difference(canonical.columns))
        self.assertTrue(
            canonical.loc[excluded, excluded_null_columns].isna().all().all()
        )
        self.assertTrue(
            canonical.loc[
                excluded, "quality_candidate_pre_cloud_l2t_invalid"
            ].isna().all()
        )
        self.assertTrue(
            self.summary.loc[
                self.summary[CANDIDATE_STATUS_COLUMN].eq(EXCLUDED_STATUS),
                runner._NULL_EXCLUDED_GEOMETRY_COLUMNS,
            ].isna().all().all()
        )
        self.assertFalse(
            canonical.loc[retained, "quality_candidate_pre_cloud_l1b"].isna().any()
        )
        retained_keys = ["city", "orbit"]
        canonical_retained = canonical.loc[
            retained, retained_keys + ["quality_candidate_pre_cloud_l2t_invalid"]
        ].sort_values(retained_keys).reset_index(drop=True)
        summary_retained = self.summary.loc[
            self.summary[CANDIDATE_STATUS_COLUMN].eq(RETAINED_STATUS),
            retained_keys + ["quality_candidate_pre_cloud_l2t_invalid"],
        ].sort_values(retained_keys).reset_index(drop=True)
        pd.testing.assert_frame_equal(canonical_retained, summary_retained)

    def test_combined_pass_is_explicitly_archive_available_only(self) -> None:
        geometry = runner._build_geometry_validation(self.summary)
        combined = runner._combined_validation(
            geometry,
            {
                "cloud_complete": True,
                "expected_cloud_candidates": 911,
                "resolved_cloud_candidate_count": 911,
                "planning_pass_equivalent_sum": 500.5,
                "planning_pass_equivalent_floor": 500,
            },
        )
        self.assertTrue(combined["scientific_gate_eligible"])
        self.assertEqual(combined["analysis_profile"], "D0047_archive_available")
        self.assertEqual(combined["scientific_gate_scope"], "archive_available_only")
        self.assertEqual(
            combined["canonical_status"],
            "PASS_D0047_ARCHIVE_AVAILABLE_GEOMETRY_AND_EXHAUSTIVE_CLOUD",
        )
        self.assertNotIn("PASS_D0035", combined["canonical_status"])

    def test_run_record_exact_provenance_schema_fixture(self) -> None:
        count_keys = {
            "original_metadata_candidate_count",
            "excluded_pre_geometry_candidate_count",
            "retained_geometry_candidate_count",
            "retained_city_scene_link_count",
            "retained_unique_scene_count",
            "asset_checkpoint_items",
            "geometry_checkpoint_items",
            "pass_evidence_files",
        }
        hash_keys = {
            "candidate_availability_ledger",
            "archive_unavailable_pre_geometry_exclusions",
            "archive_available_attrition_summary",
            "retained_city_scene_links",
            "profile_validation",
            "scene_manifest",
            "asset_checkpoint",
            "geometry_checkpoint",
            "pass_evidence_set",
            "geometry_summary",
            "cloud_checkpoint",
            "cloud_summary",
            "combined_validation",
        }
        names = [
            "CANDIDATE_LEDGER",
            "EXCLUSION_LEDGER",
            "ATTRITION_SUMMARY",
            "RETAINED_LINKS",
            "PROFILE_VALIDATION",
            "SCENE_MANIFEST",
            "ASSET_CHECKPOINT",
            "GEOMETRY_CHECKPOINT",
            "PASS_EVIDENCE_DIR",
            "GEOMETRY_SUMMARY",
            "CLOUD_CHECKPOINT",
            "CLOUD_SUMMARY",
            "COMBINED_VALIDATION_JSON",
            "RUN_RECORD",
            "PROFILE_ARTIFACTS",
        ]
        previous = {name: getattr(runner, name) for name in names}
        parent = runner.ROOT / "data/processed/v2/task1"
        with tempfile.TemporaryDirectory(
            prefix=".d0047-record-test-", dir=parent
        ) as temporary:
            root = Path(temporary)
            try:
                runner.CANDIDATE_LEDGER = root / "candidate_availability_ledger.csv"
                runner.EXCLUSION_LEDGER = (
                    root / "archive_unavailable_pre_geometry_exclusions.csv"
                )
                runner.ATTRITION_SUMMARY = root / "archive_available_attrition_summary.csv"
                runner.RETAINED_LINKS = root / "retained_city_scene_links.csv"
                runner.PROFILE_VALIDATION = root / "profile_validation.json"
                runner.SCENE_MANIFEST = root / "l1b_geo_scene_manifest.csv"
                runner.ASSET_CHECKPOINT = root / "locator_dmrpp_checkpoint.json"
                runner.GEOMETRY_CHECKPOINT = root / "geometry_scene_checkpoint.json"
                runner.PASS_EVIDENCE_DIR = root / "pass_evidence"
                runner.GEOMETRY_SUMMARY = root / "geometry_pass_summary.csv"
                runner.CLOUD_CHECKPOINT = root / "cloud_checkpoint.json"
                runner.CLOUD_SUMMARY = root / "cloud_pass_summary.csv"
                runner.COMBINED_VALIDATION_JSON = root / "combined_validation.json"
                runner.RUN_RECORD = root / "run_record.json"
                runner.PROFILE_ARTIFACTS = (
                    runner.CANDIDATE_LEDGER,
                    runner.EXCLUSION_LEDGER,
                    runner.ATTRITION_SUMMARY,
                    runner.RETAINED_LINKS,
                    runner.PROFILE_VALIDATION,
                )
                for path in runner.PROFILE_ARTIFACTS:
                    path.write_text("fixture\n", encoding="utf-8")
                combined = {
                    "decision_id": "D0047",
                    "canonical_status": (
                        "PASS_D0047_ARCHIVE_AVAILABLE_GEOMETRY_AND_EXHAUSTIVE_CLOUD"
                    ),
                }
                runner._write_run_record(
                    combined,
                    list(runner.PROFILE_ARTIFACTS),
                    profile="offline schema fixture",
                )
                record = json.loads(runner.RUN_RECORD.read_text(encoding="utf-8"))
            finally:
                for name, value in previous.items():
                    setattr(runner, name, value)
        self.assertEqual(set(record["provenance_counts"]), count_keys)
        self.assertEqual(set(record["provenance_sha256"]), hash_keys)
        self.assertEqual(record["schema_version"], 3)
        self.assertEqual(record["analysis_profile"], "D0047_archive_available")
        self.assertEqual(record["scientific_gate_scope"], "archive_available_only")
        artifact_labels = set(record["artifact_sha256"])
        self.assertTrue(
            any(label.endswith("candidate_availability_ledger.csv") for label in artifact_labels)
        )
        self.assertTrue(
            any(
                label.endswith("archive_unavailable_pre_geometry_exclusions.csv")
                for label in artifact_labels
            )
        )


class ZBasePatchIsolationTests(unittest.TestCase):
    def test_d0047_adapter_context_restores_d0035_engine(self) -> None:
        previous = {
            name: getattr(runner.base, name) for name in runner._BASE_PATCH_FIELDS
        }
        with runner._configured_base():
            self.assertIs(
                runner.base._run_geometry_passes, runner._run_geometry_passes
            )
            self.assertIs(runner.base._write_run_record, runner._write_run_record)
            self.assertEqual(runner.base.DECISION_ID, "D0047")
        for name, value in previous.items():
            self.assertIs(getattr(runner.base, name), value, name)


if __name__ == "__main__":
    unittest.main()
