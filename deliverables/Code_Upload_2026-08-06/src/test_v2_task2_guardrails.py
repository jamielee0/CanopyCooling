#!/usr/bin/env python3
"""Network-free adversarial tests for the Task 1 -> Task 2 gate."""

from __future__ import annotations

from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from urban_cooling_v2.task1_pass_gate import (  # noqa: E402
    Task1GateError,
    sha256_file,
    validate_canonical_task1_pass,
    write_canonical_task1_pass,
)
from urban_cooling_v2.task2_guardrails import (  # noqa: E402
    evaluate_preflight,
    run_preflight,
)


HRRR_SOURCE = "NOAA HRRR public AWS archive; surface analysis f00"
HRRR_SEARCH = r":(?:TMP|DPT):2 m"
CERTIFIED_COUNT = "certified_expected_pass_equivalent_floor"
D0035_PASS = "PASS_D0035_GEOMETRY_AND_EXHAUSTIVE_CLOUD"


def _json_hash(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError("test CSV rows may not be empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _ready_config() -> dict:
    decisions = {
        "cross_city_scope_status": "FROZEN",
        "cross_city_scope_choice": "cross_city_common_support",
        "holdout_eligibility_rule_status": "FROZEN",
        "holdout_eligibility_rule": "quality-only rule frozen before LST",
        "holdout_selection_status": "FROZEN",
        "collection_chain_status": "FROZEN",
        "collection_chain_decision_id": "D_TEST",
        "time_strata_status": "FROZEN",
        "scene_pixel_qa_status": "FROZEN",
        "supporting_product_chain_status": "FROZEN",
        "optical_landcover_status": "FROZEN",
        "classification_matching_status": "FROZEN",
        "analysis_schema_status": "FROZEN",
    }
    return {
        "task2": {
            # Deliberately hostile: the implementation must ignore this list.
            "accepted_task1_gate_values": ["FAKE_PASS"],
            "result_bearing_actions_enabled": True,
            "development_end_year": 2025,
            "season_2026_status": "UNOPENED",
            "holdout_status": "SELECTED",
            "holdout_city": "atlanta",
            "heldout_thermal_status": "UNOPENED",
        },
        "decisions": decisions,
        "storage": {
            "status": "FROZEN",
            "projected_peak_bytes": 1_000,
            "headroom_multiplier": 2.0,
            "minimum_reserve_bytes": 1_000,
            "delete_existing_data": False,
            "persist_signed_urls": False,
            "preserve_native_temperature_grid": True,
        },
        "safety": {
            "open_2026": False,
            "mix_primary_collection_versions": False,
            "resample_temperature": False,
            "use_future_optical_imagery": False,
            "use_thermal_outcome_to_tune_thresholds": False,
        },
    }


class BoundFixture:
    """Small but fully hash- and semantics-bound Task 1 PASS evidence chain."""

    def __init__(self, root: Path, *, diagnostic_status: str = "PASS") -> None:
        self.root = root.resolve()
        self.paths: dict[str, Path] = {}
        self._build_d0035()
        self._build_hrrr()
        self._build_step2_gate()
        self._build_step3(diagnostic_status=diagnostic_status)

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def _build_d0035(self) -> None:
        combined_path = self.root / "evidence/d0035/combined_validation.json"
        run_path = self.root / "evidence/d0035/run_record.json"
        combined = {
            "decision_id": "D0035",
            "geometry_source": "ECO_L1B_GEO.002",
            "expected_metadata_candidates": 942,
            "resolved_geometry_candidate_count": 942,
            "definitive_geometry_status_count": 942,
            "unresolved_geometry_candidate_count": 0,
            "geometry_passing_candidate_count": 2,
            "expected_cloud_candidates": 2,
            "resolved_cloud_candidate_count": 2,
            "finite_cloud_fraction_count": 2,
            "planning_pass_equivalent_sum": 1.75,
            "planning_pass_equivalent_floor": 1,
            "geometry_complete": True,
            "cloud_complete": True,
            "combined_complete": True,
            "scientific_gate_eligible": True,
            "candidate_seal_geometry_only": True,
            "candidate_view_mask_cloud_independent": True,
            "view_gate_cloud_conditioned": False,
            "cloud_extrapolation_used": False,
            "canonical_status": D0035_PASS,
            "gate_status": D0035_PASS,
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
            "frozen_years": "2018-2025",
        }
        _write_json(combined_path, combined)
        provenance_sha = {
            "scene_manifest": "1" * 64,
            "asset_checkpoint": "2" * 64,
            "geometry_checkpoint": "3" * 64,
            "pass_evidence_set": "4" * 64,
            "geometry_summary": "5" * 64,
            "cloud_checkpoint": "6" * 64,
            "cloud_summary": "7" * 64,
            "combined_validation": sha256_file(combined_path),
        }
        provenance_counts = {
            "metadata_candidates": 942,
            "city_scene_links": 1404,
            "unique_scenes": 1370,
            "asset_checkpoint_items": 1370,
            "geometry_checkpoint_items": 942,
            "pass_evidence_files": 2,
        }
        run = {
            "schema_version": 2,
            "run_id": "R0004_D0035",
            "decision_id": "D0035",
            "implementation_decision_id": "D0036",
            "algorithm_version": "d0035-l1b-dmrpp-pass-stream-v4",
            "provenance_counts": provenance_counts,
            "provenance_sha256": provenance_sha,
            "artifact_sha256": {
                self.relative(combined_path): sha256_file(combined_path)
            },
            "combined_validation": combined,
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
        }
        _write_json(run_path, run)
        self.combined = combined
        self.d0035_run = run
        self.paths["d0035_combined_validation"] = combined_path
        self.paths["d0035_run_record"] = run_path

    def _build_hrrr(self) -> None:
        root = self.root / "weather/exact_hrrr"
        manifest_path = self.root / "weather/hrrr_manifest.csv"
        index_path = root / "hrrr_hourly_shard_index.csv"
        summary_path = root / "hrrr_hourly_domain_summary.csv"
        checkpoint_path = root / "hrrr_checkpoint.json"
        seal_path = root / "hrrr_run_seal.json"
        item_id = "hrrr-sfc-f00-20230702T08Z"
        object_key = "hrrr.20230702/conus/hrrr.t08z.wrfsfcf00.grib2"
        grib_url = (
            "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/" + object_key
        )
        manifest_row = {
            "item_id": item_id,
            "analysis_utc": "2023-07-02 08:00:00+00:00",
            "cities": "phoenix",
            "n_target_passes": 1,
            "model": "hrrr",
            "product": "sfc",
            "forecast_hour": 0,
            "variable_search": HRRR_SEARCH,
            "source": HRRR_SOURCE,
            "object_key": object_key,
            "grib_url": grib_url,
            "index_url": grib_url + ".idx",
        }
        _write_csv(manifest_path, [manifest_row])
        binding = {
            "item_id": item_id,
            "analysis_utc": "2023-07-02T08:00:00Z",
            "cities": "phoenix",
            "n_target_passes": 1,
            "model": "hrrr",
            "product": "sfc",
            "forecast_hour": 0,
            "variable_search": HRRR_SEARCH,
            "source": HRRR_SOURCE,
            "object_key": object_key,
        }
        request_sha = _json_hash(binding)
        domain_sha = "8" * 64
        shard_path = root / "hourly_domain_cells" / f"{item_id}.csv.gz"
        shard_path.parent.mkdir(parents=True, exist_ok=True)
        shard_path.write_bytes(b"sealed test shard\n")
        shard_sha = sha256_file(shard_path)
        city_counts = {"phoenix": 2}
        checkpoint_item = {
            "schema_version": 2,
            "shard_schema_version": 1,
            "status": "complete",
            "frozen_domain_sha256": domain_sha,
            "request_binding": binding,
            "request_sha256": request_sha,
            "shard_columns": ["city", "timestamp_utc"],
            "local_path": str(shard_path),
            "size_bytes": shard_path.stat().st_size,
            "sha256": shard_sha,
            "n_rows": 2,
            "city_row_counts": city_counts,
        }
        checkpoint = {
            "schema_version": 2,
            "checkpoint_kind": "hrrr_exact_acquisition_domain_shards",
            "manifest_sha256": _json_hash([binding]),
            "frozen_domain_sha256": domain_sha,
            "shard_schema_version": 1,
            "minimum_domain_cells": 2,
            "items": {item_id: checkpoint_item},
        }
        _write_json(checkpoint_path, checkpoint)
        index_row = {
            "schema_version": 2,
            "shard_schema_version": 1,
            "item_id": item_id,
            "analysis_utc": "2023-07-02 08:00:00+00:00",
            "cities": "phoenix",
            "n_target_passes": 1,
            "model": "hrrr",
            "product": "sfc",
            "forecast_hour": 0,
            "variable_search": HRRR_SEARCH,
            "object_key": object_key,
            "request_sha256": request_sha,
            "frozen_domain_sha256": domain_sha,
            "local_path": str(shard_path),
            "size_bytes": shard_path.stat().st_size,
            "sha256": shard_sha,
            "n_rows": 2,
            "city_row_counts": json.dumps(city_counts, separators=(",", ":")),
            "source": HRRR_SOURCE,
        }
        _write_csv(index_path, [index_row])
        summary_row = {
            "city": "phoenix",
            "timestamp_utc": "2023-07-02 08:00:00+00:00",
            "vpd_kpa": 1.5,
            "vpd_kpa_median": 1.5,
            "vpd_kpa_std": 0.1,
            "vpd_kpa_p10": 1.4,
            "vpd_kpa_p90": 1.6,
            "vpd_kpa_min": 1.4,
            "vpd_kpa_max": 1.6,
            "t2m_k": 305.0,
            "d2m_k": 290.0,
            "n_domain_cells": 2,
            "source": HRRR_SOURCE,
            "domain_cell_rule": (
                "HRRR grid-cell center covered by frozen Census Urban Area"
            ),
        }
        _write_csv(summary_path, [summary_row])
        shard_set = [
            {
                "item_id": item_id,
                "request_sha256": request_sha,
                "sha256": shard_sha,
                "n_rows": 2,
                "city_row_counts": city_counts,
            }
        ]
        seal = {
            "schema_version": 1,
            "status": "PASS_EXACT_HRRR_RUN_SEAL",
            "manifest_path": str(manifest_path),
            "manifest_file_sha256": sha256_file(manifest_path),
            "manifest_canonical_sha256": _json_hash([binding]),
            "manifest_fields": [
                "item_id",
                "analysis_utc",
                "cities",
                "n_target_passes",
                "model",
                "product",
                "forecast_hour",
                "variable_search",
                "source",
                "object_key",
            ],
            "frozen_domain_sha256": domain_sha,
            "domain_names": ["phoenix"],
            "minimum_domain_cells": 2,
            "checkpoint_path": str(checkpoint_path),
            "checkpoint_sha256": sha256_file(checkpoint_path),
            "shard_index_path": str(index_path),
            "shard_index_sha256": sha256_file(index_path),
            "summary_path": str(summary_path),
            "summary_sha256": sha256_file(summary_path),
            "shard_set_sha256": _json_hash(shard_set),
            "counts": {
                "manifest_items": 1,
                "checkpoint_items": 1,
                "shard_index_rows": 1,
                "summary_rows": 1,
                "shard_cell_rows": 2,
                "requested_city_hours": 1,
            },
            "checkpoint_schema_version": 2,
            "shard_schema_version": 1,
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
        }
        _write_json(seal_path, seal)
        self.hrrr_seal = seal
        self.paths.update(
            {
                "hrrr_run_seal": seal_path,
                "hrrr_manifest": manifest_path,
                "hrrr_shard_index": index_path,
                "hrrr_summary": summary_path,
            }
        )

    def _build_step2_gate(self) -> None:
        checks_path = self.root / "evidence/step2/T2.1_checks.csv"
        _write_csv(
            checks_path,
            [{"check": "sealed_fixture", "pass": True, "detail": "complete"}],
        )
        path = self.root / "evidence/step2/step2_gate_record.json"
        ledger_paths = [
            checks_path,
            self.paths["d0035_combined_validation"],
            self.paths["d0035_run_record"],
            self.paths["hrrr_run_seal"],
            self.paths["hrrr_manifest"],
            self.paths["hrrr_shard_index"],
            self.paths["hrrr_summary"],
        ]
        gate = {
            "schema_version": 1,
            "decision_id": "D0035",
            "implementation_decision_id": "D0036",
            "status": "PASS",
            "scientific_gate_eligible": True,
            "all_checks_pass": True,
            "checks_path": self.relative(checks_path),
            "checks_sha256": sha256_file(checks_path),
            "checks": [
                {"check": "sealed_fixture", "pass": True, "detail": "complete"}
            ],
            "upstream_d0035": {
                "status": D0035_PASS,
                "scientific_gate_eligible": True,
                "algorithm_version": "d0035-l1b-dmrpp-pass-stream-v4",
                "run_record_path": self.relative(self.paths["d0035_run_record"]),
                "run_record_sha256": sha256_file(
                    self.paths["d0035_run_record"]
                ),
                "provenance_counts": self.d0035_run["provenance_counts"],
                "provenance_sha256": self.d0035_run["provenance_sha256"],
            },
            "hrrr_run_seal": {
                "status": "PASS_EXACT_HRRR_RUN_SEAL",
                "path": self.relative(self.paths["hrrr_run_seal"]),
                "sha256": sha256_file(self.paths["hrrr_run_seal"]),
                "manifest_canonical_sha256": self.hrrr_seal[
                    "manifest_canonical_sha256"
                ],
                "frozen_domain_sha256": self.hrrr_seal["frozen_domain_sha256"],
                "counts": self.hrrr_seal["counts"],
            },
            "counts": {
                "near_nadir_physical_passes": 2,
                "expected_pass_equivalents_total": 1.75,
                "planning_pass_count_floor": 1,
                "step2_checks": 1,
                "step2_checks_passed": 1,
            },
            "artifact_sha256": {
                self.relative(item): sha256_file(item) for item in ledger_paths
            },
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
            "frozen_years": "2018-2025",
        }
        _write_json(path, gate)
        self.paths["step2_gate"] = path

    def _build_step3(self, *, diagnostic_status: str) -> None:
        diagnostic_path = self.root / "evidence/step3/step3_diagnostic_gate.json"
        support_path = self.root / "evidence/step3/tables/T3.1_model_support.csv"
        run_path = self.root / "evidence/step3/run_record.json"
        diagnostic = {
            "decision_id": "D0027",
            "status": diagnostic_status,
            "scientific_gate_eligible": True,
            "actual_n_passes": 1,
            "large_count_n_passes": 800,
            "passed_required_checks": 2 if diagnostic_status == "PASS" else 1,
            "total_required_checks": 2,
            "failed_check_ids": [] if diagnostic_status == "PASS" else ["power"],
            "thresholds": {"target": 0.8},
        }
        _write_json(diagnostic_path, diagnostic)
        support_rows = []
        for model in ("demand_by_dryness", "demand_by_dryness_by_time"):
            support_rows.append(
                {
                    "model": model,
                    "effect_size_k": 1.5,
                    "minimum_passes_for_target_power": 100,
                    "planning_n_passes": 1,
                    "power_at_planning_n": 0.5,
                    "target_power": 0.8,
                    "statistically_supportable_at_planning_n": False,
                    "count_status": CERTIFIED_COUNT,
                    "scientific_gate_eligible": True,
                    "smallest_detectable_effect_at_planning_n_k": 2.0,
                }
            )
        _write_csv(support_path, support_rows)
        run = {
            "decision_ids": ["D0021", "D0027", "D0029", "D0035"],
            "actual_n_passes": 1,
            "count_status": CERTIFIED_COUNT,
            "step2_gate": "PASS",
            "status": "ready_for_frozen_full_profile",
            "hrrr_summary_sha256": sha256_file(self.paths["hrrr_summary"]),
            "planning_sha256": "9" * 64,
            "config_sha256": "a" * 64,
            "template_sha256": "b" * 64,
            "diagnostic_gate": diagnostic,
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
            "frozen_years": "2018-2025",
        }
        _write_json(run_path, run)
        self.paths.update(
            {
                "step3_run_record": run_path,
                "step3_diagnostic_gate": diagnostic_path,
                "t3_model_support": support_path,
            }
        )

    def write_gate(self) -> Path:
        gate_path = self.root / "data/processed/v2/task1/TASK1_GATE.json"
        return write_canonical_task1_pass(
            self.paths, gate_path=gate_path, repo_root=self.root
        )


class Task2GuardrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _preflight(self, gate_path: Path, gate: dict | None = None):
        if gate is None:
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
        return evaluate_preflight(
            _ready_config(),
            gate,
            task1_gate_path=str(gate_path),
            free_bytes=10_000,
            repo_root=self.root,
        )

    def test_repository_current_stop_remains_closed(self) -> None:
        report = run_preflight()
        self.assertFalse(report.ready)
        self.assertIn(
            "TASK1_CANONICAL_GATE_MISSING", {item.code for item in report.blockers}
        )

    def test_minimal_fake_pass_fails(self) -> None:
        gate_path = self.root / "TASK1_GATE.json"
        report = self._preflight(gate_path, {"task1_gate": "PASS"})
        self.assertFalse(report.ready)
        self.assertIn(
            "TASK1_CANONICAL_GATE_INVALID", {item.code for item in report.blockers}
        )

    def test_step3_fail_blocks_canonical_writer(self) -> None:
        fixture = BoundFixture(self.root, diagnostic_status="FAIL")
        with self.assertRaisesRegex(Task1GateError, "status is not PASS"):
            fixture.write_gate()

    def test_bound_artifact_mutation_blocks_preflight(self) -> None:
        fixture = BoundFixture(self.root)
        gate_path = fixture.write_gate()
        fixture.paths["hrrr_summary"].write_text("mutated\n", encoding="utf-8")
        report = self._preflight(gate_path)
        self.assertFalse(report.ready)
        self.assertIn(
            "TASK1_CANONICAL_GATE_INVALID", {item.code for item in report.blockers}
        )

    def test_path_escape_blocks_preflight(self) -> None:
        fixture = BoundFixture(self.root)
        gate_path = fixture.write_gate()
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["artifacts"]["d0035_combined_validation"]["path"] = "../escape.json"
        report = self._preflight(gate_path, gate)
        self.assertFalse(report.ready)
        self.assertIn(
            "TASK1_CANONICAL_GATE_INVALID", {item.code for item in report.blockers}
        )
        detail = " ".join(item.detail for item in report.blockers)
        self.assertIn("escapes the repository", detail)

    def test_d0035_writer_and_validator_behavior_is_preserved(self) -> None:
        fixture = BoundFixture(self.root)
        gate_path = fixture.write_gate()
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        validate_canonical_task1_pass(
            gate, gate_path=gate_path, repo_root=self.root
        )
        report = self._preflight(gate_path)
        self.assertFalse(report.ready)
        self.assertIn(
            "TASK1_D0047_PROFILE_REQUIRED", {item.code for item in report.blockers}
        )
        self.assertEqual(report.task1_gate_value, "PASS")

    def test_config_cannot_redefine_pass_status(self) -> None:
        fixture = BoundFixture(self.root)
        gate_path = fixture.write_gate()
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["task1_gate"] = "FAKE_PASS"
        report = self._preflight(gate_path, gate)
        codes = {item.code for item in report.blockers}
        self.assertIn("TASK1_NOT_PASS", codes)
        self.assertIn("TASK1_CANONICAL_GATE_INVALID", codes)

    def test_storage_and_safety_still_fail_closed(self) -> None:
        fixture = BoundFixture(self.root)
        gate_path = fixture.write_gate()
        config = deepcopy(_ready_config())
        config["storage"]["projected_peak_bytes"] = 6_000
        config["safety"]["resample_temperature"] = True
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        report = evaluate_preflight(
            config,
            gate,
            task1_gate_path=str(gate_path),
            free_bytes=10_000,
            repo_root=self.root,
        )
        codes = {item.code for item in report.blockers}
        self.assertIn("INSUFFICIENT_STORAGE_HEADROOM", codes)
        self.assertIn("SAFETY_RESAMPLE_TEMPERATURE", codes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
