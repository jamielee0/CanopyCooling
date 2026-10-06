#!/usr/bin/env python3
"""Network-free handoff tests for the definitive Step-3 runner."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from urban_cooling_v2 import step03_power as step3
import run_v2_step03_definitive as runner


class DefinitiveStep3RunnerTests(unittest.TestCase):
    def test_input_validation_locks_count_weights_hashes_and_profile(self) -> None:
        source_config = runner.CONFIG.read_bytes()
        with tempfile.TemporaryDirectory(prefix="step3-definitive-input-") as temporary:
            root = Path(temporary).resolve()
            config = root / "configs/v2_cities.toml"
            config.parent.mkdir(parents=True)
            config.write_bytes(source_config)
            step2_root = root / "data/processed/v2/task1/step2_definitive_l1b_geo"
            tables = step2_root / "tables"
            tables.mkdir(parents=True)
            template_path = tables / "step3_empirical_template.csv"
            template = step3.synthetic_pass_template(
                7, np.random.default_rng(20260801), rho=0.45
            )
            template["template_geometry_status"] = step3.OBSERVED_GEOMETRY_STATUS
            template["sampling_weight"] = 1.0
            template.loc[0, "sampling_weight"] = 0.0
            template.to_csv(template_path, index=False)

            cloud_path = root / "data/cloud_pass_summary.csv"
            cloud_path.parent.mkdir(parents=True, exist_ok=True)
            cloud_path.write_text("city,orbit\nphoenix,1\n", encoding="utf-8")
            geometry_path = root / "data/geometry_pass_summary.csv"
            pd.DataFrame(
                {
                    "record": range(8),
                    "l1b_geometry_covered_cells": [100] * 8,
                    "l1b_geometry_domain_cells": [100] * 8,
                    "l1b_geometry_coverage_fraction": [1.0] * 8,
                    "l1b_view_zenith_abs_p95_deg": [10.0] * 7 + [25.0],
                    "l1b_geometry_complete": [True] * 8,
                    "l1b_geometry_status": ["geometry_pass"] * 7
                    + ["angle_fail"],
                    "quality_candidate_pre_cloud": [True] * 7 + [False],
                    "quality_candidate_pre_cloud_l1b": [True] * 7 + [False],
                    "quality_candidate_pre_cloud_l2t_invalid": [True]
                    + [False] * 7,
                }
            ).to_csv(geometry_path, index=False)
            geometry_validation = root / "data/geometry_validation.json"
            geometry_validation.write_text(
                json.dumps(
                    {
                        "decision_id": "D0035",
                        "geometry_source": "ECO_L1B_GEO.002",
                        "expected_metadata_candidates": 8,
                        "resolved_geometry_candidate_count": 8,
                        "definitive_geometry_status_count": 8,
                        "unresolved_geometry_candidate_count": 0,
                        "geometry_complete": True,
                        "candidate_seal_geometry_only": True,
                        "geometry_passing_candidate_count": 7,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            quality_screen = root / "data/passes_quality_screened_l1b_geo.csv"
            pd.DataFrame(
                {
                    "quality_candidate_pre_cloud": [True] * 7 + [False],
                    "quality_candidate_pre_cloud_l1b": [True] * 7 + [False],
                    "quality_candidate_pre_cloud_l2t_invalid": [True]
                    + [False] * 7,
                }
            ).to_csv(quality_screen, index=False)
            legacy_quality_screen = root / "data/legacy_quality_screen.csv"
            legacy_quality_screen.write_text(
                "city,orbit,quality_candidate_pre_cloud\nphoenix,1,True\n",
                encoding="utf-8",
            )
            cloud_validation = root / "data/combined_validation.json"
            cloud_validation.write_text(
                json.dumps(
                    {
                        "decision_id": "D0035",
                        "geometry_source": "ECO_L1B_GEO.002",
                        "expected_metadata_candidates": 8,
                        "resolved_geometry_candidate_count": 8,
                        "definitive_geometry_status_count": 8,
                        "unresolved_geometry_candidate_count": 0,
                        "geometry_passing_candidate_count": 7,
                        "expected_cloud_candidates": 7,
                        "resolved_cloud_candidate_count": 7,
                        "finite_cloud_fraction_count": 7,
                        "geometry_complete": True,
                        "cloud_complete": True,
                        "combined_complete": True,
                        "candidate_seal_geometry_only": True,
                        "candidate_view_mask_cloud_independent": True,
                        "view_gate_cloud_conditioned": False,
                        "cloud_extrapolation_used": False,
                        "scientific_gate_eligible": True,
                        "planning_pass_equivalent_sum": 6.0,
                        "planning_pass_equivalent_floor": 6,
                        "canonical_status": runner.D0035_PASS_STATUS,
                        "gate_status": runner.D0035_PASS_STATUS,
                        "lst_opened": False,
                        "thermal_opened": False,
                        "record_2026_opened": False,
                        "holdout_status": "UNSELECTED",
                        "frozen_years": "2018-2025",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            hrrr = (
                root
                / "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo/"
                "hrrr_hourly_domain_summary.csv"
            )
            hrrr.parent.mkdir(parents=True)
            hrrr.write_text("city,timestamp_utc,vpd_kpa\n", encoding="utf-8")
            hrrr_manifest_path = (
                root
                / "data/raw/v2/weather/"
                "hrrr_exact_acquisition_l1b_geo_manifest.csv"
            )
            hrrr_manifest = runner.hrrr_fetch.build_hrrr_request_manifest(
                pd.DataFrame(
                    {
                        "city": ["phoenix"],
                        "acquisition_utc": ["2023-07-02T08:00:00Z"],
                    }
                )
            )
            hrrr_manifest.to_csv(hrrr_manifest_path, index=False)
            hrrr_manifest_sha256 = (
                runner.hrrr_fetch.canonical_hrrr_manifest_sha256(hrrr_manifest)
            )
            hrrr_checkpoint = hrrr.parent / "hrrr_checkpoint.json"
            hrrr_checkpoint.write_text(
                json.dumps(
                    {
                        "schema_version": (
                            runner.hrrr_fetch.HRRR_CHECKPOINT_SCHEMA_VERSION
                        ),
                        "manifest_sha256": hrrr_manifest_sha256,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            hrrr_index = hrrr.parent / "hrrr_hourly_shard_index.csv"
            hrrr_index.write_text("item_id,sha256\n", encoding="utf-8")
            hrrr_seal_path = hrrr.parent / "hrrr_run_seal.json"
            hrrr_counts = {
                "manifest_items": 1,
                "checkpoint_items": 1,
                "shard_index_rows": 1,
                "summary_rows": 1,
                "shard_cell_rows": 2,
                "requested_city_hours": 1,
            }
            hrrr_seal_path.write_text(
                json.dumps(
                    {
                        "schema_version": (
                            runner.hrrr_fetch.HRRR_RUN_SEAL_SCHEMA_VERSION
                        ),
                        "status": runner.HRRR_RUN_SEAL_STATUS,
                        "manifest_path": str(hrrr_manifest_path.relative_to(root)),
                        "manifest_file_sha256": runner._sha256(hrrr_manifest_path),
                        "manifest_canonical_sha256": hrrr_manifest_sha256,
                        "manifest_fields": list(
                            runner.hrrr_fetch.HRRR_CHECKPOINT_REQUEST_FIELDS
                        ),
                        "frozen_domain_sha256": "b" * 64,
                        "counts": hrrr_counts,
                        "checkpoint_schema_version": (
                            runner.hrrr_fetch.HRRR_CHECKPOINT_SCHEMA_VERSION
                        ),
                        "shard_schema_version": (
                            runner.hrrr_fetch.HRRR_SHARD_SCHEMA_VERSION
                        ),
                        "checkpoint_path": str(hrrr_checkpoint.relative_to(root)),
                        "checkpoint_sha256": runner._sha256(hrrr_checkpoint),
                        "shard_index_path": str(hrrr_index.relative_to(root)),
                        "shard_index_sha256": runner._sha256(hrrr_index),
                        "summary_path": str(hrrr.relative_to(root)),
                        "summary_sha256": runner._sha256(hrrr),
                        "lst_opened": False,
                        "thermal_opened": False,
                        "record_2026_opened": False,
                        "holdout_status": "UNSELECTED",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            upstream_run_record = root / "data/upstream_run_record.json"
            upstream_run_record.write_text(
                '{"schema_version": 2, "decision_id": "D0035"}\n',
                encoding="utf-8",
            )
            checks_path = tables / "step2_checks.csv"
            checks_path.write_text(
                "check,pass,detail\nall frozen checks,True,complete\n",
                encoding="utf-8",
            )
            gate_record_path = step2_root / "step2_gate_record.json"
            gate_artifacts = [
                template_path,
                checks_path,
                upstream_run_record,
                hrrr_seal_path,
                hrrr_manifest_path,
                hrrr_checkpoint,
                hrrr_index,
                hrrr,
            ]
            gate_record = {
                "schema_version": 1,
                "decision_id": "D0035",
                "status": "PASS",
                "scientific_gate_eligible": True,
                "all_checks_pass": True,
                "checks_path": str(checks_path.relative_to(root)),
                "checks_sha256": runner._sha256(checks_path),
                "checks": [
                    {"check": "all frozen checks", "pass": True, "detail": "complete"}
                ],
                "upstream_d0035": {
                    "status": runner.D0035_PASS_STATUS,
                    "scientific_gate_eligible": True,
                    "algorithm_version": runner.D0035_ALGORITHM_VERSION,
                    "run_record_path": str(upstream_run_record.relative_to(root)),
                    "run_record_sha256": runner._sha256(upstream_run_record),
                },
                "hrrr_run_seal": {
                    "status": runner.HRRR_RUN_SEAL_STATUS,
                    "path": str(hrrr_seal_path.relative_to(root)),
                    "sha256": runner._sha256(hrrr_seal_path),
                    "manifest_canonical_sha256": hrrr_manifest_sha256,
                    "frozen_domain_sha256": "b" * 64,
                    "counts": hrrr_counts,
                },
                "counts": {
                    "step2_checks": 1,
                    "step2_checks_passed": 1,
                },
                "artifact_sha256": {
                    str(path.relative_to(root)): runner._sha256(path)
                    for path in gate_artifacts
                },
                "lst_opened": False,
                "thermal_opened": False,
                "record_2026_opened": False,
                "holdout_status": "UNSELECTED",
                "frozen_years": "2018-2025",
            }
            gate_record_path.write_text(
                json.dumps(gate_record, indent=2) + "\n", encoding="utf-8"
            )

            planning_path = step2_root / "step3_planning_count.json"
            planning = {
                "schema_version": 4,
                "decision_id": "D0035",
                "count_status": "certified_expected_pass_equivalent_floor",
                "step2_gate": "PASS",
                "step2_gate_record_path": str(gate_record_path.relative_to(root)),
                "step2_gate_record_sha256": runner._sha256(gate_record_path),
                "near_nadir_physical_passes": 7,
                "expected_pass_equivalents_total": 6.0,
                "planning_pass_count_floor": 6,
                "template_path": str(template_path.relative_to(root)),
                "template_sha256": runner._sha256(template_path),
                "hrrr_summary_sha256": runner._sha256(hrrr),
                "hrrr_run_seal_path": str(hrrr_seal_path.relative_to(root)),
                "hrrr_run_seal_sha256": runner._sha256(hrrr_seal_path),
                "upstream_run_record_path": str(
                    upstream_run_record.relative_to(root)
                ),
                "upstream_run_record_sha256": runner._sha256(upstream_run_record),
                "upstream_algorithm_version": runner.D0035_ALGORITHM_VERSION,
                "geometry_pass_summary_path": str(geometry_path.relative_to(root)),
                "geometry_pass_summary_sha256": runner._sha256(geometry_path),
                "geometry_validation_path": str(
                    geometry_validation.relative_to(root)
                ),
                "geometry_validation_sha256": runner._sha256(geometry_validation),
                "quality_screen_path": str(quality_screen.relative_to(root)),
                "quality_screen_sha256": runner._sha256(quality_screen),
                "legacy_quality_screen_path": str(
                    legacy_quality_screen.relative_to(root)
                ),
                "legacy_quality_screen_sha256": runner._sha256(
                    legacy_quality_screen
                ),
                "cloud_pass_summary_path": str(cloud_path.relative_to(root)),
                "cloud_pass_summary_sha256": runner._sha256(cloud_path),
                "cloud_validation_path": str(cloud_validation.relative_to(root)),
                "cloud_validation_sha256": runner._sha256(cloud_validation),
            }
            planning_path.write_text(
                json.dumps(planning, indent=2) + "\n", encoding="utf-8"
            )
            output = root / "data/processed/v2/task1/step3_definitive_l1b_geo"
            with mock.patch.multiple(
                runner,
                ROOT=root,
                CONFIG=config,
                STEP2=step2_root,
                STEP2_GATE_RECORD=gate_record_path,
                PLANNING=planning_path,
                OUTPUT=output,
                EXPECTED_METADATA_CANDIDATES=8,
            ):
                inputs = runner.load_definitive_inputs()
                self.assertEqual(inputs["validation"]["actual_n_passes"], 6)
                self.assertEqual(inputs["validation"]["template_rows"], 7)
                self.assertEqual(inputs["validation"]["zero_weight_template_rows"], 1)
                self.assertEqual(
                    inputs["validation"]["decision_ids"],
                    ["D0021", "D0027", "D0029", "D0035"],
                )
                self.assertEqual(
                    inputs["validation"]["status"],
                    "ready_for_frozen_full_profile",
                )
                self.assertFalse(inputs["validation"]["lst_opened"])
                self.assertFalse(inputs["validation"]["thermal_opened"])
                self.assertFalse(inputs["validation"]["record_2026_opened"])
                self.assertEqual(inputs["validation"]["holdout_status"], "UNSELECTED")
                self.assertEqual(inputs["validation"]["frozen_years"], "2018-2025")
                planning["step2_gate"] = "CONDITIONAL"
                planning_path.write_text(
                    json.dumps(planning, indent=2) + "\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(RuntimeError, "disagrees with the PASS"):
                    runner.load_definitive_inputs()
                planning["step2_gate"] = "PASS"
                planning_path.write_text(
                    json.dumps(planning, indent=2) + "\n", encoding="utf-8"
                )
                original_gate = gate_record_path.read_text(encoding="utf-8")
                altered_gate = json.loads(original_gate)
                altered_gate["all_checks_pass"] = False
                gate_record_path.write_text(
                    json.dumps(altered_gate, indent=2) + "\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(RuntimeError, "planning checksum"):
                    runner.load_definitive_inputs()
                gate_record_path.write_text(original_gate, encoding="utf-8")
                template_path.write_text(
                    template_path.read_text(encoding="utf-8") + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(RuntimeError, "template"):
                    runner.load_definitive_inputs()


if __name__ == "__main__":
    unittest.main(verbosity=2)
