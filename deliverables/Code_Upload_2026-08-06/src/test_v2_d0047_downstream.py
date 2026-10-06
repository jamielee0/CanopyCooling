#!/usr/bin/env python3
"""Network-free profile-contract tests for the D0047 downstream handoff."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v2_step02_definitive as step2  # noqa: E402
import run_v2_step03_definitive as step3  # noqa: E402


class D0047DownstreamTests(unittest.TestCase):
    def tearDown(self) -> None:
        step2.configure_profile(step2.D0035_PROFILE)
        step3.configure_profile("d0035_exhaustive")

    def test_profile_selection_uses_append_only_namespaces(self) -> None:
        root = Path("/tmp/d0047-profile-test-root")
        step2.configure_profile(step2.D0047_PROFILE, root=root)
        self.assertEqual(step2.ACTIVE_PROFILE, step2.D0047_PROFILE)
        self.assertIn("D0047_archive_available", str(step2.HRRR_ROOT))
        self.assertIn("D0047_archive_available", str(step2.OUTPUT))
        self.assertEqual(step2.EXPECTED_METADATA_CANDIDATES, 942)
        self.assertEqual(step2.RETAINED_METADATA_CANDIDATES, 911)
        self.assertEqual(step2.EXCLUDED_METADATA_CANDIDATES, 31)
        self.assertNotEqual(step2.OUTPUT, root / step2.D0035_PROFILE.output_relative)
        self.assertEqual(
            step2._active_profile_summary(),
            {
                "decision_id": "D0047",
                "analysis_profile": "D0047_archive_available",
                "scientific_gate_scope": "archive_available_only",
                "profile_scope_label": step2.D0047_SCOPE_LABEL,
                "original_metadata_candidate_count": 942,
                "excluded_pre_geometry_candidate_count": 31,
                "retained_geometry_candidate_count": 911,
            },
        )

        step3.configure_profile("d0047_archive_available", root=root)
        self.assertEqual(step3.COUNT_STATUS, step2.D0047_COUNT_STATUS)
        self.assertEqual(step3.HRRR_RUN_SEAL_STATUS, step2.D0047_HRRR_RUN_SEAL_STATUS)
        self.assertEqual(step3.SCIENTIFIC_GATE_SCOPE, "archive_available_only")
        self.assertEqual(
            step3._step3_decision_ids("D0047"),
            ["D0021", "D0027", "D0029", "D0047", "D0053"],
        )
        self.assertIn("D0047_archive_available", str(step3.OUTPUT))

    def test_full_942_row_profile_binding_rejects_status_corruption(self) -> None:
        with tempfile.TemporaryDirectory(prefix="d0047-downstream-ledger-") as temporary:
            root = Path(temporary).resolve()
            quality = root / step2.D0047_PROFILE.quality_relative
            quality.mkdir(parents=True)
            rows = []
            for index in range(942):
                included = index >= 31
                rows.append(
                    {
                        "city": f"city_{index % 5}",
                        "orbit": index + 1,
                        "acquisition_utc": "2023-07-01T12:00:00Z",
                        step2.ARCHIVE_AVAILABLE_STATUS_COLUMN: (
                            step2.ARCHIVE_AVAILABLE_RETAINED_STATUS
                            if included
                            else step2.ARCHIVE_AVAILABLE_EXCLUDED_STATUS
                        ),
                        step2.ARCHIVE_AVAILABLE_INCLUDED_COLUMN: included,
                    }
                )
            ledger = pd.DataFrame(rows)
            geometry = ledger.copy()
            ledger_path = quality / "candidate_availability_ledger.csv"
            validation_path = quality / "profile_validation.json"
            ledger.to_csv(ledger_path, index=False)
            validation = {
                "schema_version": 1,
                "decision_id": "D0047",
                "implementation_decision_id": step2.D0047_IMPLEMENTATION_DECISION_ID,
                "algorithm_version": step2.D0047_ALGORITHM_VERSION,
                "target_scope": step2.D0047_SCOPE_LABEL,
                "original_metadata_candidate_count": 942,
                "excluded_pre_geometry_candidate_count": 31,
                "retained_geometry_candidate_count": 911,
                "retained_city_scene_link_count": 1355,
                "retained_unique_scene_count": 1323,
                "candidate_ledger_complete": True,
                "retained_candidate_keys_exact": True,
                "whole_candidate_exclusion_rule": True,
                "missing_scene_imputation_used": False,
                "missing_scene_zero_coverage_assigned": False,
                "adjacent_scene_substitution_used": False,
                "profile_gate_status": "PASS_D0047_ARCHIVE_AVAILABLE_PROFILE_SEALED",
                "lst_opened": False,
                "thermal_opened": False,
                "record_2026_opened": False,
                "holdout_status": "UNSELECTED",
            }
            validation_path.write_text(json.dumps(validation) + "\n", encoding="utf-8")
            with mock.patch.object(step2, "ROOT", root):
                step2.configure_profile(step2.D0047_PROFILE, root=root)
                binding = step2._validate_archive_available_profile_artifacts(geometry)
                self.assertEqual(
                    binding["candidate_availability_ledger_sha256"],
                    step2._sha256(ledger_path),
                )
                damaged = geometry.copy()
                damaged.loc[0, step2.ARCHIVE_AVAILABLE_STATUS_COLUMN] = (
                    step2.ARCHIVE_AVAILABLE_RETAINED_STATUS
                )
                with self.assertRaisesRegex(RuntimeError, "availability status"):
                    step2._validate_archive_available_profile_artifacts(damaged)

    def test_d0047_attrition_separates_archive_loss_from_near_nadir(self) -> None:
        step2.configure_profile(step2.D0047_PROFILE)
        rows = []
        for city in ("phoenix", "atlanta"):
            for index in range(20):
                excluded = index < (3 if city == "phoenix" else 4)
                rows.append(
                    {
                        "city": city,
                        "daytime": True,
                        "geolocation_usable": True,
                        "obstruction_flag": False,
                        "near_nadir": pd.NA if excluded else index % 2 == 0,
                        step2.ARCHIVE_AVAILABLE_STATUS_COLUMN: (
                            step2.ARCHIVE_AVAILABLE_EXCLUDED_STATUS
                            if excluded
                            else step2.ARCHIVE_AVAILABLE_RETAINED_STATUS
                        ),
                        step2.ARCHIVE_AVAILABLE_INCLUDED_COLUMN: not excluded,
                        "cloud_survival_fraction_of_domain": (
                            pd.NA if excluded or index % 2 else 0.5
                        ),
                    }
                )
        # Patch the frozen census only for this compact synthetic fixture.
        with mock.patch.multiple(
            step2,
            ORIGINAL_METADATA_CANDIDATES=40,
            RETAINED_METADATA_CANDIDATES=33,
            EXCLUDED_METADATA_CANDIDATES=7,
        ):
            attrition = step2._d0047_attrition_table(pd.DataFrame(rows))
        stages = set(attrition["stage"])
        self.assertIn("archive_available_pre_geometry", stages)
        self.assertIn("near_nadir", stages)
        archive = attrition.loc[
            attrition["stage"].eq("archive_available_pre_geometry"),
            "count_or_expected_count",
        ].sum()
        prior = attrition.loc[
            attrition["stage"].eq("not_obstruction_flagged"),
            "count_or_expected_count",
        ].sum()
        self.assertEqual(prior - archive, 7)
        self.assertTrue(
            attrition["archive_unavailable_is_geometry_failure"].eq(False).all()
        )

    def test_step3_accepts_exact_mixed_hrrr_and_recomputes_profile_binding_hash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="d0047-step3-gate-") as temporary:
            root = Path(temporary).resolve()
            step3.configure_profile("d0047_archive_available", root=root)
            step2_root = root / (
                "data/processed/v2/task1/"
                "step2_definitive_l1b_geo_D0047_archive_available"
            )
            gate_path = step2_root / "step2_gate_record.json"
            checks_path = step2_root / "tables/T2.1_checks.csv"
            upstream_path = root / "evidence/d0047/run_record.json"
            combined_path = root / "evidence/d0047/combined_validation.json"
            ledger_path = root / "evidence/d0047/candidate_availability_ledger.csv"
            exclusion_path = root / (
                "evidence/d0047/archive_unavailable_pre_geometry_exclusions.csv"
            )
            hrrr_root = root / "data/raw/v2/weather/d0047_hrrr"
            checkpoint_path = hrrr_root / "hrrr_checkpoint.json"
            index_path = hrrr_root / "hrrr_hourly_shard_index.csv"
            summary_path = hrrr_root / "hrrr_hourly_domain_summary.csv"
            seal_path = hrrr_root / "hrrr_run_seal.json"
            manifest_path = hrrr_root / "hrrr_manifest.csv"
            hrrr_manifest = step3.hrrr_fetch.build_hrrr_request_manifest(
                pd.DataFrame(
                    {
                        "city": ["atlanta"],
                        "acquisition_utc": ["2018-07-28T22:30:00Z"],
                    }
                )
            )
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            hrrr_manifest.to_csv(manifest_path, index=False)
            manifest_canonical_sha256 = (
                step3.hrrr_fetch.canonical_hrrr_manifest_sha256(hrrr_manifest)
            )
            self.assertEqual(set(hrrr_manifest["product"]), {"sfc", "prs"})
            for path, content in (
                (checks_path, "check,pass,detail\nsealed,True,complete\n"),
                (upstream_path, '{"schema_version": 3}\n'),
                (combined_path, '{"gate_status": "PASS"}\n'),
                (ledger_path, "city,orbit\nphoenix,1\n"),
                (exclusion_path, "city,orbit\nphoenix,2\n"),
                (
                    checkpoint_path,
                    json.dumps(
                        {
                            "schema_version": (
                                step3.hrrr_fetch.HRRR_CHECKPOINT_SCHEMA_VERSION
                            ),
                            "manifest_sha256": manifest_canonical_sha256,
                        }
                    )
                    + "\n",
                ),
                (index_path, "item_id,sha256\ntest," + "a" * 64 + "\n"),
                (summary_path, "city,timestamp_utc\nphoenix,2023-07-01T12:00:00Z\n"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            def relative(path: Path) -> str:
                return path.relative_to(root).as_posix()

            profile_binding = {
                "decision_id": "D0047",
                "analysis_profile": "D0047_archive_available",
                "scientific_gate_scope": "archive_available_only",
                "profile_scope_label": step2.D0047_SCOPE_LABEL,
                "geometry_passing_candidate_count": 17,
                "combined_validation_path": relative(combined_path),
                "combined_validation_sha256": step3._sha256(combined_path),
                "upstream_run_record_path": relative(upstream_path),
                "upstream_run_record_sha256": step3._sha256(upstream_path),
                "candidate_availability_ledger_path": relative(ledger_path),
                "candidate_availability_ledger_sha256": step3._sha256(ledger_path),
                "exclusion_summary_path": relative(exclusion_path),
                "exclusion_summary_sha256": step3._sha256(exclusion_path),
            }
            hrrr_counts = {
                "manifest_items": 2,
                "checkpoint_items": 2,
                "shard_index_rows": 2,
                "summary_rows": 2,
                "shard_cell_rows": 2,
                "requested_city_hours": 2,
            }
            seal = {
                "schema_version": step3.hrrr_fetch.HRRR_RUN_SEAL_SCHEMA_VERSION,
                "status": step3.D0047_HRRR_RUN_SEAL_STATUS,
                "manifest_path": relative(manifest_path),
                "manifest_file_sha256": step3._sha256(manifest_path),
                "manifest_canonical_sha256": manifest_canonical_sha256,
                "manifest_fields": list(
                    step3.hrrr_fetch.HRRR_CHECKPOINT_REQUEST_FIELDS
                ),
                "frozen_domain_sha256": "c" * 64,
                "counts": hrrr_counts,
                "checkpoint_schema_version": (
                    step3.hrrr_fetch.HRRR_CHECKPOINT_SCHEMA_VERSION
                ),
                "shard_schema_version": step3.hrrr_fetch.HRRR_SHARD_SCHEMA_VERSION,
                "checkpoint_path": relative(checkpoint_path),
                "checkpoint_sha256": step3._sha256(checkpoint_path),
                "shard_index_path": relative(index_path),
                "shard_index_sha256": step3._sha256(index_path),
                "summary_path": relative(summary_path),
                "summary_sha256": step3._sha256(summary_path),
                "profile_binding": profile_binding,
                "profile_binding_sha256": step3._json_sha256(profile_binding),
                "lst_opened": False,
                "thermal_opened": False,
                "record_2026_opened": False,
                "holdout_status": "UNSELECTED",
            }
            seal_path.parent.mkdir(parents=True, exist_ok=True)
            seal_path.write_text(json.dumps(seal) + "\n", encoding="utf-8")
            upstream = {
                "decision_id": "D0047",
                "status": step3.D0047_PASS_STATUS,
                "scientific_gate_eligible": True,
                "analysis_profile": "D0047_archive_available",
                "scientific_gate_scope": "archive_available_only",
                "profile_scope_label": step2.D0047_SCOPE_LABEL,
                "algorithm_version": step3.D0047_ALGORITHM_VERSION,
                "run_record_path": relative(upstream_path),
                "run_record_sha256": step3._sha256(upstream_path),
                "candidate_availability_ledger_path": relative(ledger_path),
                "candidate_availability_ledger_sha256": step3._sha256(ledger_path),
                "exclusion_summary_path": relative(exclusion_path),
                "exclusion_summary_sha256": step3._sha256(exclusion_path),
                "original_exhaustive_gate_status": "STOP_D0035_INCOMPLETE_GEOMETRY",
                "restored_archive_sensitivity_required": True,
                "provenance_counts": {
                    "original_metadata_candidate_count": 942,
                    "excluded_pre_geometry_candidate_count": 31,
                    "retained_geometry_candidate_count": 911,
                    "retained_city_scene_link_count": 1355,
                    "retained_unique_scene_count": 1323,
                },
            }
            artifacts = [
                checks_path,
                upstream_path,
                combined_path,
                ledger_path,
                exclusion_path,
                manifest_path,
                checkpoint_path,
                index_path,
                summary_path,
                seal_path,
            ]
            gate = {
                "schema_version": 1,
                "decision_id": "D0047",
                "analysis_profile": "D0047_archive_available",
                "scientific_gate_scope": "archive_available_only",
                "profile_scope_label": step2.D0047_SCOPE_LABEL,
                "planning_count_status": step3.D0047_COUNT_STATUS,
                "status": "PASS",
                "scientific_gate_eligible": True,
                "all_checks_pass": True,
                "checks_path": relative(checks_path),
                "checks_sha256": step3._sha256(checks_path),
                "checks": [
                    {"check": "sealed", "pass": True, "detail": "complete"}
                ],
                "upstream_quality_profile": upstream,
                "hrrr_run_seal": {
                    "status": step3.D0047_HRRR_RUN_SEAL_STATUS,
                    "path": relative(seal_path),
                    "sha256": step3._sha256(seal_path),
                    "manifest_canonical_sha256": manifest_canonical_sha256,
                    "frozen_domain_sha256": "c" * 64,
                    "counts": hrrr_counts,
                    "profile_binding": profile_binding,
                    "profile_binding_sha256": step3._json_sha256(profile_binding),
                },
                "counts": {
                    "original_metadata_candidates": 942,
                    "excluded_pre_geometry_candidates": 31,
                    "retained_geometry_candidates": 911,
                    "near_nadir_physical_passes": 17,
                    "step2_checks": 1,
                    "step2_checks_passed": 1,
                },
                "artifact_sha256": {
                    relative(path): step3._sha256(path) for path in artifacts
                },
                "lst_opened": False,
                "thermal_opened": False,
                "record_2026_opened": False,
                "holdout_status": "UNSELECTED",
                "frozen_years": "2018-2025",
            }
            gate_path.parent.mkdir(parents=True, exist_ok=True)
            gate_path.write_text(json.dumps(gate) + "\n", encoding="utf-8")
            planning = {
                "step2_gate": "PASS",
                "step2_gate_record_path": relative(gate_path),
                "step2_gate_record_sha256": step3._sha256(gate_path),
                "upstream_run_record_path": relative(upstream_path),
                "upstream_run_record_sha256": step3._sha256(upstream_path),
                "upstream_algorithm_version": step3.D0047_ALGORITHM_VERSION,
                "hrrr_run_seal_path": relative(seal_path),
                "hrrr_run_seal_sha256": step3._sha256(seal_path),
            }
            with mock.patch.object(step3, "ROOT", root):
                loaded, loaded_path = step3._load_step2_gate_record(planning)
                self.assertEqual(loaded["analysis_profile"], "D0047_archive_available")
                self.assertEqual(loaded_path, gate_path)
                gate["hrrr_run_seal"]["profile_binding_sha256"] = "0" * 64
                gate_path.write_text(json.dumps(gate) + "\n", encoding="utf-8")
                planning["step2_gate_record_sha256"] = step3._sha256(gate_path)
                with self.assertRaisesRegex(RuntimeError, "profile binding"):
                    step3._load_step2_gate_record(planning)

    def test_step3_boolean_parser_rejects_unknown_inclusion_value(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "true/false"):
            step3._true_series(
                pd.Series(["true", "not_evaluated"]),
                label="D0047 test inclusion flag",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
