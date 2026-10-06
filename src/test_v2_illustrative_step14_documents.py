"""Offline contract tests for the noncanonical Step-14 document layer."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from urban_cooling_v2.illustrative_step14_documents import (
    BANNER,
    OUTPUT_FILENAMES,
    write_step14_documents,
)


SAFE_STATUS = {
    "status": "STOP_USER_SKIPPED_D0047_GEOMETRY_710_OF_911",
    "scientific_gate_eligible": False,
    "task1_gate": "STOP",
    "task2_activated": False,
    "lst_opened": False,
    "thermal_opened": False,
    "holdout_status": "UNSELECTED",
    "record_2026_opened": False,
}


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class IllustrativeStep14DocumentsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="illustrative-step14-")
        self.root = Path(self.temporary.name)
        self.output_root = self.root / "data"
        self.figure_root = self.root / "figures"
        self.output_root.mkdir()
        self.figure_root.mkdir()

        _write_csv(
            self.output_root / "ILLUSTRATIVE_T4.1_scene_metadata.csv",
            [
                "data_origin",
                "canonical_eligible",
                "synthetic_scene_id",
                "synthetic_pass_id",
                "city",
                "year",
                "time_stratum",
                "synthetic_acquisition_utc",
                "synthetic_retrieval_mode",
                "synthetic_geometry_class",
                "synthetic_view_zenith_deg",
                "synthetic_cloud_fraction",
            ],
            [
                {
                    "data_origin": "synthetic",
                    "canonical_eligible": False,
                    "synthetic_scene_id": "synthetic_scene_1_001",
                    "synthetic_pass_id": "synthetic_pass_1_001",
                    "city": "sim_city_1",
                    "year": 2019,
                    "time_stratum": "10-12",
                    "synthetic_acquisition_utc": "2019-06-01T17:00:00+00:00",
                    "synthetic_retrieval_mode": "three_band",
                    "synthetic_geometry_class": "good",
                    "synthetic_view_zenith_deg": 8.0,
                    "synthetic_cloud_fraction": 0.1,
                },
                {
                    "data_origin": "synthetic",
                    "canonical_eligible": False,
                    "synthetic_scene_id": "synthetic_scene_2_001",
                    "synthetic_pass_id": "synthetic_pass_2_001",
                    "city": "sim_city_2",
                    "year": 2020,
                    "time_stratum": "16-18",
                    "synthetic_acquisition_utc": "2020-07-01T23:00:00+00:00",
                    "synthetic_retrieval_mode": "five_band",
                    "synthetic_geometry_class": "best",
                    "synthetic_view_zenith_deg": 4.0,
                    "synthetic_cloud_fraction": 0.05,
                },
            ],
        )
        _write_csv(
            self.output_root / "ILLUSTRATIVE_T5.1_product_inventory.csv",
            [
                "data_origin",
                "canonical_eligible",
                "synthetic_product",
                "synthetic_version",
                "synthetic_layer",
                "synthetic_scene_match_fraction",
            ],
            [
                {
                    "data_origin": "synthetic",
                    "canonical_eligible": False,
                    "synthetic_product": "albedo",
                    "synthetic_version": "sim-v1",
                    "synthetic_layer": "albedo",
                    "synthetic_scene_match_fraction": 1.0,
                },
                {
                    "data_origin": "synthetic",
                    "canonical_eligible": False,
                    "synthetic_product": "radiation",
                    "synthetic_version": "sim-v1",
                    "synthetic_layer": "net_radiation",
                    "synthetic_scene_match_fraction": 1.0,
                },
            ],
        )
        snapshot = {
            **SAFE_STATUS,
            "catalogue_metadata_rows": 2968,
            "d0047_geometry_candidates": 911,
            "d0047_geometry_evaluated_at_user_skip": 710,
            "d0047_geometry_unevaluated_at_user_skip": 201,
            "daytime_catalogue_ceiling_passes": 1055,
            "cloud_complete": False,
            "usable_pass_count_available": False,
        }
        snapshot_path = (
            self.output_root
            / "empirical_nonthermal/step02/EMPIRICAL_PARTIAL_step02_snapshot_facts.json"
        )
        snapshot_path.parent.mkdir(parents=True)
        snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")

        _write_csv(
            self.output_root / "ILLUSTRATIVE_STEP9_SYNTHETIC_ANALYSIS_TABLE.csv",
            ["data_origin", "canonical_eligible", "city", "synthetic_outcome"],
            [
                {
                    "data_origin": "synthetic",
                    "canonical_eligible": False,
                    "city": "sim_city_1",
                    "synthetic_outcome": 1.0,
                }
            ],
        )
        _write_csv(
            self.output_root / "data_origin_dictionary.csv",
            ["artifact_id", "status"],
            [{"artifact_id": "F2.1", "status": SAFE_STATUS["status"]}],
        )
        (self.output_root / "canonical_gate_status.json").write_text(
            json.dumps(SAFE_STATUS) + "\n", encoding="utf-8"
        )
        (self.output_root / "README.md").write_text(
            "Illustrative package.\n", encoding="utf-8"
        )
        (self.output_root / "ILLUSTRATIVE_public_package_source_inventory.csv").write_text(
            "relative_path,sha256\nsrc/example.py,fixture\n", encoding="utf-8"
        )
        (self.output_root / "ILLUSTRATIVE_public_package_rebuild_instructions.md").write_text(
            "# Offline illustrative rebuild\n\nThis is a test fixture.\n", encoding="utf-8"
        )
        (self.figure_root / "ILLUSTRATIVE_F14.1_PAPER_FIGURE_1_study_design.png").write_bytes(
            b"synthetic figure fixture"
        )

        upstream_files = [
            self.output_root / "ILLUSTRATIVE_T4.1_scene_metadata.csv",
            self.output_root / "ILLUSTRATIVE_T5.1_product_inventory.csv",
            snapshot_path,
            self.output_root / "ILLUSTRATIVE_STEP9_SYNTHETIC_ANALYSIS_TABLE.csv",
            self.figure_root / "ILLUSTRATIVE_F14.1_PAPER_FIGURE_1_study_design.png",
        ]
        manifest_records = []
        for path in upstream_files:
            if path.is_relative_to(self.output_root):
                relative = str(Path("data_root") / path.relative_to(self.output_root))
            else:
                relative = str(Path("figures_root") / path.relative_to(self.figure_root))
            manifest_records.append(
                {
                    "relative_path": relative,
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
        manifest = {**SAFE_STATUS, "artifacts": manifest_records}
        (self.output_root / "run_manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

        self.artifacts = write_step14_documents(
            self.output_root,
            self.figure_root,
            seed=20260805,
            status_contract=SAFE_STATUS,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_registry_names_and_all_outputs_are_nonempty(self) -> None:
        expected = {
            "M14.1": "ILLUSTRATIVE_M14.1_go_adjust_stop_memo.md",
            "M14.2": "ILLUSTRATIVE_M14.2_confirmatory_report_NOT_RUN.md",
            "LIMITATIONS": "ILLUSTRATIVE_step14_limitations.md",
            "FINAL_CHECKS": "ILLUSTRATIVE_step14_final_checks.csv",
            "SCENE_VERSION_INVENTORY": "ILLUSTRATIVE_step14_scene_version_inventory.csv",
            "P14.1": "ILLUSTRATIVE_P14.1_public_package_inventory.csv",
            "PACKAGE_CHECKSUMS": "ILLUSTRATIVE_public_package_checksums.json",
        }
        self.assertEqual(OUTPUT_FILENAMES, expected)
        self.assertEqual(set(self.artifacts), set(expected))
        self.assertEqual(
            {key: path.name for key, path in self.artifacts.items()},
            expected,
        )
        for key, path in self.artifacts.items():
            with self.subTest(key=key):
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 100)
                self.assertTrue(path.name.startswith("ILLUSTRATIVE_"))
        id_bearing = [
            path.name
            for path in self.artifacts.values()
            if any(token in path.name for token in ("M14.1", "M14.2", "P14.1"))
        ]
        self.assertEqual(
            sorted(id_bearing),
            sorted(
                [
                    "ILLUSTRATIVE_M14.1_go_adjust_stop_memo.md",
                    "ILLUSTRATIVE_M14.2_confirmatory_report_NOT_RUN.md",
                    "ILLUSTRATIVE_P14.1_public_package_inventory.csv",
                ]
            ),
        )

    def test_memos_preserve_stop_and_make_no_confirmatory_claim(self) -> None:
        memo = self.artifacts["M14.1"].read_text(encoding="utf-8")
        report = self.artifacts["M14.2"].read_text(encoding="utf-8")
        self.assertIn(BANNER, memo)
        self.assertIn("STOP for empirical, manuscript, and confirmatory claims", memo)
        self.assertIn("710 of 911", memo)
        self.assertIn("201 remained unevaluated", memo)
        self.assertIn("**Status: NOT RUN**", report)
        self.assertIn("No confirmatory estimate exists", report)
        self.assertIn("Held-out city | UNSELECTED", report)
        self.assertIn("2026 record | Unopened", report)
        for text in (memo, report):
            self.assertIn("canonical_eligible: false", text)
            self.assertIn(SAFE_STATUS["status"], text)
            self.assertIn("scientific_gate_eligible: false", text)
            self.assertIn("task1_gate: STOP", text)
            self.assertIn("task2_activated: false", text)
            self.assertIn("lst_opened: false", text)
            self.assertIn("thermal_opened: false", text)
            self.assertIn("holdout_status: UNSELECTED", text)
            self.assertIn("record_2026_opened: false", text)

    def test_scene_version_inventory_uses_only_upstream_synthetic_metadata(self) -> None:
        with self.artifacts["SCENE_VERSION_INVENTORY"].open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 4)  # two scenes crossed with two products
        self.assertEqual({row["canonical_eligible"] for row in rows}, {"false"})
        self.assertEqual({row["data_origin"] for row in rows}, {"synthetic_metadata"})
        self.assertEqual({row["city"] for row in rows}, {"sim_city_1", "sim_city_2"})
        self.assertTrue(
            all(row["synthetic_scene_id"].startswith("synthetic_scene_") for row in rows)
        )
        self.assertEqual(
            {row["download_date"] for row in rows},
            {"not_applicable_synthetic_no_download"},
        )
        self.assertEqual(
            {row["scene_metadata_source"] for row in rows},
            {"data_root/ILLUSTRATIVE_T4.1_scene_metadata.csv"},
        )
        self.assertEqual(
            {row["product_metadata_source"] for row in rows},
            {"data_root/ILLUSTRATIVE_T5.1_product_inventory.csv"},
        )
        for row in rows:
            self.assertEqual(row["scientific_gate_eligible"], "false")
            self.assertEqual(row["task1_gate"], "STOP")
            self.assertEqual(row["task2_activated"], "false")
            self.assertEqual(row["lst_opened"], "false")
            self.assertEqual(row["thermal_opened"], "false")
            self.assertEqual(row["holdout_status"], "UNSELECTED")
            self.assertEqual(row["record_2026_opened"], "false")

    def test_public_inventory_hashes_every_stable_nonself_file(self) -> None:
        inventory_path = self.artifacts["P14.1"]
        with inventory_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        by_relative = {row["relative_path"]: row for row in rows}
        excluded = {
            "data_root/run_manifest.json",
            "data_root/canonical_gate_status.json",
            "data_root/data_origin_dictionary.csv",
            "data_root/README.md",
            f"data_root/{OUTPUT_FILENAMES['P14.1']}",
            f"data_root/{OUTPUT_FILENAMES['PACKAGE_CHECKSUMS']}",
        }
        actual_files: dict[str, Path] = {}
        for root, label in (
            (self.output_root, "data_root"),
            (self.figure_root, "figures_root"),
        ):
            for path in root.rglob("*"):
                if path.is_file():
                    relative = str(Path(label) / path.relative_to(root))
                    if relative not in excluded:
                        actual_files[relative] = path
        self.assertEqual(set(by_relative), set(actual_files))
        for relative, path in actual_files.items():
            with self.subTest(relative=relative):
                row = by_relative[relative]
                self.assertEqual(row["canonical_eligible"], "false")
                self.assertEqual(row["scientific_gate_eligible"], "false")
                self.assertEqual(row["task1_gate"], "STOP")
                self.assertEqual(row["task2_activated"], "false")
                self.assertEqual(row["lst_opened"], "false")
                self.assertEqual(row["thermal_opened"], "false")
                self.assertEqual(row["holdout_status"], "UNSELECTED")
                self.assertEqual(row["record_2026_opened"], "false")
                self.assertEqual(int(row["size_bytes"]), path.stat().st_size)
                self.assertEqual(row["sha256"], _sha256(path))

        checksums = json.loads(
            self.artifacts["PACKAGE_CHECKSUMS"].read_text(encoding="utf-8")
        )
        self.assertFalse(checksums["canonical_eligible"])
        self.assertEqual(checksums["listed_file_count"], len(rows))
        self.assertEqual(checksums["inventory_sha256"], _sha256(inventory_path))
        self.assertEqual(
            set(checksums["excluded_mutable_orchestrator_files"]),
            {"README.md", "canonical_gate_status.json", "data_origin_dictionary.csv", "run_manifest.json"},
        )
        self.assertEqual(
            set(checksums["excluded_self_record_files"]),
            {OUTPUT_FILENAMES["P14.1"], OUTPUT_FILENAMES["PACKAGE_CHECKSUMS"]},
        )

    def test_extended_source_inventory_and_rebuild_are_acknowledged(self) -> None:
        with self.artifacts["FINAL_CHECKS"].open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            rows = {row["check_id"]: row for row in csv.DictReader(handle)}
        source_check = rows["public_code_and_decision_history"]
        self.assertEqual(source_check["check_status"], "INCLUDED_IN_EXTENDED_PACKAGE")
        self.assertIn("ILLUSTRATIVE_public_package_source_inventory.csv", source_check["evidence"])
        self.assertIn(
            "ILLUSTRATIVE_public_package_rebuild_instructions.md",
            source_check["evidence"],
        )
        with self.artifacts["P14.1"].open("r", encoding="utf-8", newline="") as handle:
            names = {row["file_name"] for row in csv.DictReader(handle)}
        self.assertIn("ILLUSTRATIVE_public_package_source_inventory.csv", names)
        self.assertIn("ILLUSTRATIVE_public_package_rebuild_instructions.md", names)

    def test_missing_extended_source_files_retains_not_included_status(self) -> None:
        (self.output_root / "ILLUSTRATIVE_public_package_source_inventory.csv").unlink()
        (self.output_root / "ILLUSTRATIVE_public_package_rebuild_instructions.md").unlink()
        artifacts = write_step14_documents(
            self.output_root,
            self.figure_root,
            seed=20260805,
            status_contract=SAFE_STATUS,
        )
        with artifacts["FINAL_CHECKS"].open("r", encoding="utf-8", newline="") as handle:
            rows = {row["check_id"]: row for row in csv.DictReader(handle)}
        self.assertEqual(
            rows["public_code_and_decision_history"]["check_status"],
            "NOT_INCLUDED_BY_DOCUMENT_LAYER",
        )

    def test_outputs_are_deterministic_on_safe_rerun(self) -> None:
        before = {key: path.read_bytes() for key, path in self.artifacts.items()}
        rerun = write_step14_documents(
            self.output_root,
            self.figure_root,
            seed=20260805,
            status_contract=dict(SAFE_STATUS),
        )
        self.assertEqual(before, {key: path.read_bytes() for key, path in rerun.items()})

    def test_unexpected_sealed_data_file_is_rejected_before_hashing(self) -> None:
        unexpected = self.output_root / "real_LST_2026_holdout.tif"
        unexpected.write_bytes(b"must never reach checksum reader")
        with mock.patch(
            "urban_cooling_v2.illustrative_step14_documents._sha256_file"
        ) as checksum_reader:
            with self.assertRaisesRegex(ValueError, "refusing to read or hash"):
                write_step14_documents(
                    self.output_root,
                    self.figure_root,
                    seed=20260805,
                    status_contract=SAFE_STATUS,
                )
        checksum_reader.assert_not_called()

    def test_snapshot_checkpoint_invariants_fail_closed(self) -> None:
        snapshot_path = (
            self.output_root
            / "empirical_nonthermal/step02/EMPIRICAL_PARTIAL_step02_snapshot_facts.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["d0047_geometry_evaluated_at_user_skip"] = 709
        snapshot_path.write_text(json.dumps(snapshot) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not match the live D0047 checkpoint"):
            write_step14_documents(
                self.output_root,
                self.figure_root,
                seed=20260805,
                status_contract=SAFE_STATUS,
            )

    def test_unsafe_or_incomplete_status_contract_fails_closed(self) -> None:
        unsafe_values = {
            "scientific_gate_eligible": True,
            "task1_gate": "GO",
            "task2_activated": True,
            "lst_opened": True,
            "thermal_opened": True,
            "holdout_status": "sim_city_5",
            "record_2026_opened": True,
            "status": "COMPLETE_NONCANONICAL",
            "canonical_gate_status": "PASS",
            "confirmatory_run_performed": True,
            "holdout_opened": True,
        }
        for key, value in unsafe_values.items():
            with self.subTest(key=key):
                status = dict(SAFE_STATUS)
                status[key] = value
                with self.assertRaises(ValueError):
                    write_step14_documents(
                        self.output_root,
                        self.figure_root,
                        seed=20260805,
                        status_contract=status,
                    )

        for missing in SAFE_STATUS:
            with self.subTest(missing=missing):
                status = dict(SAFE_STATUS)
                status.pop(missing)
                with self.assertRaises(ValueError):
                    write_step14_documents(
                        self.output_root,
                        self.figure_root,
                        seed=20260805,
                        status_contract=status,
                    )


if __name__ == "__main__":
    unittest.main()
