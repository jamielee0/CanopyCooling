#!/usr/bin/env python3
"""Network-free adversarial tests for the D0056 scoped Task-1 gate."""

from __future__ import annotations

from copy import deepcopy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from urban_cooling_v2.task1_time_of_day_gate import (  # noqa: E402
    ANALYSIS_PROFILE,
    DEFAULT_ARTIFACT_PATHS,
    DEFAULT_GATE_PATH,
    EXPECTED_INPUT_BINDING_PATHS,
    EXPECTED_LOCO_SUPPORT,
    EXPECTED_STRATA_CENSUS,
    INTERACTION_STATUS,
    PRIMARY_ESTIMAND,
    SCIENTIFIC_GATE_SCOPE,
    STEP3_PASS_STATUS,
    TASK1_GATE_STATUS,
    TimeOfDayTask1GateError,
    sha256_file,
    validate_time_of_day_task1_pass,
    write_time_of_day_task1_pass,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError("test CSV requires rows")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class TimeOfDayFixture:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.paths = {
            name: self.root / relative
            for name, relative in DEFAULT_ARTIFACT_PATHS.items()
        }
        self.gate_path = self.root / DEFAULT_GATE_PATH
        self._build_original_step2()
        self._build_step3()

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def _build_original_step2(self) -> None:
        gate_path = self.paths["original_interaction_step2_gate"]
        checks_path = gate_path.parent / "tables/step2_checks.csv"
        checks = [
            {"check": f"check_{index}", "detail": "ok", "pass": True}
            for index in range(6)
        ]
        _write_csv(checks_path, checks)
        checks_sha = sha256_file(checks_path)
        step2 = {
            "schema_version": 1,
            "decision_id": "D0047",
            "implementation_decision_id": "D0048",
            "band_mode_metadata_decision_id": "D0054",
            "analysis_profile": "D0047_archive_available",
            "scientific_gate_scope": "archive_available_only",
            "profile_scope_label": (
                "archive_available_after_pre_geometry_exclusion_D0047"
            ),
            "status": "STOP",
            "scientific_gate_eligible": False,
            "all_checks_pass": True,
            "checks_pass": True,
            "count_support_pass": False,
            "failure_domains": ["count_support"],
            "planning_count_status": (
                "certified_archive_available_expected_pass_equivalent_floor"
            ),
            "counts": {
                "original_metadata_candidates": 942,
                "excluded_pre_geometry_candidates": 31,
                "retained_geometry_candidates": 911,
                "near_nadir_physical_passes": 219,
                "expected_pass_equivalents_total": 159.0870840462331,
                "planning_pass_count_floor": 159,
                "step2_checks": 6,
                "step2_checks_passed": 6,
            },
            "checks": checks,
            "checks_path": self.relative(checks_path),
            "checks_sha256": checks_sha,
            "artifact_sha256": {self.relative(checks_path): checks_sha},
            "upstream_quality_profile": {
                "decision_id": "D0047",
                "analysis_profile": "D0047_archive_available",
                "scientific_gate_scope": "archive_available_only",
                "status": (
                    "PASS_D0047_ARCHIVE_AVAILABLE_GEOMETRY_AND_EXHAUSTIVE_CLOUD"
                ),
                "scientific_gate_eligible": True,
                "original_exhaustive_gate_status": (
                    "STOP_D0035_INCOMPLETE_GEOMETRY"
                ),
                "restored_archive_sensitivity_required": True,
            },
            "hrrr_run_seal": {
                "status": (
                    "PASS_EXACT_HRRR_RUN_SEAL_D0047_ARCHIVE_AVAILABLE"
                ),
                "counts": {"manifest_items": 413},
            },
            "frozen_years": "2018-2025",
            "holdout_status": "UNSELECTED",
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
        }
        _write_json(gate_path, step2)

    def _build_step3(self) -> None:
        step2_sha = sha256_file(self.paths["original_interaction_step2_gate"])
        input_bindings: dict[str, str] = {}
        for path_field, relative in EXPECTED_INPUT_BINDING_PATHS.items():
            path = self.root / relative
            if path_field == "template_path":
                _write_csv(path, [{"source_pass_id": "fixture"}])
            elif path_field == "planning_path":
                _write_json(path, {"fixture": "planning"})
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_text("fixture\n", encoding="utf-8")
            input_bindings[path_field] = relative
            hash_field = f"{path_field.removesuffix('_path')}_sha256"
            input_bindings[hash_field] = sha256_file(path)
        input_bindings["step2_gate_record_sha256"] = step2_sha

        loco_rows = []
        for city, (physical, expected, planning_n) in EXPECTED_LOCO_SUPPORT.items():
            power = 0.84
            loco_rows.append(
                {
                    "excluded_city": city,
                    "physical_passes": physical,
                    "expected_pass_equivalents": expected,
                    "planning_n": planning_n,
                    "effect_size_k": 1.5,
                    "n_replicates": 200,
                    "mean_estimate_k": 1.49,
                    "power_at_primary_effect": power,
                    "power_mc_ci_low": power - 0.04,
                    "power_mc_ci_high": power + 0.04,
                    "target_power": 0.8,
                    "statistically_supportable": True,
                    "scientific_gate_eligible": True,
                }
            )
        loco_path = self.paths["t3t2_leave_one_city_out_support"]
        _write_csv(loco_path, loco_rows)
        loco_sha = sha256_file(loco_path)
        model_rows = []
        for effect, power, minimum in (
            (0.75, 0.60, 150),
            (1.50, 0.85, 65),
            (2.25, 0.97, 40),
        ):
            model_rows.append(
                {
                    "model": "pass_clustered_late_afternoon_minus_late_morning",
                    "primary_estimand": PRIMARY_ESTIMAND,
                    "effect_size_k": effect,
                    "minimum_passes_for_target_power": minimum,
                    "full_panel_primary_contrast_planning_n": 72,
                    "power_at_planning_n": power,
                    "power_mc_ci_low": max(0.0, power - 0.05),
                    "power_mc_ci_high": min(1.0, power + 0.05),
                    "target_power": 0.80,
                    "statistically_supportable_at_planning_n": effect >= 1.5,
                    "scientific_gate_eligible": True,
                    "interaction_status": INTERACTION_STATUS,
                    "smallest_detectable_effect_at_planning_n_k": 1.5,
                }
            )
        model_path = self.paths["t3t1_time_of_day_model_support"]
        _write_csv(model_path, model_rows)
        model_sha = sha256_file(model_path)
        census_path = self.root / (
            "data/processed/v2/task1/step3_time_of_day_only_D0056/"
            "tables/T3T.3_empirical_strata_census.csv"
        )
        census_rows = [
            {
                "city": city,
                "time_stratum": stratum,
                "physical_passes": physical,
                "expected_pass_equivalents": expected,
                "is_primary_contrast_stratum": stratum in {"10-12", "16-18"},
            }
            for (city, stratum), (physical, expected) in EXPECTED_STRATA_CENSUS.items()
        ]
        _write_csv(census_path, census_rows)
        census_sha = sha256_file(census_path)
        checks_path = self.root / (
            "data/processed/v2/task1/step3_time_of_day_only_D0056/"
            "tables/step3_time_of_day_checks.csv"
        )
        check_rows = [
            {
                "check_id": "fixture_check",
                "category": "power",
                "criterion": "fixture pass",
                "observed_value": 1.0,
                "n_monte_carlo": 200,
                "mc_ci_low": 0.8,
                "mc_ci_high": 1.0,
                "passed": True,
                "required_for_gate": True,
                "detail": "fixture",
            }
        ]
        _write_csv(checks_path, check_rows)
        checks_sha = sha256_file(checks_path)
        artifact_ledger = {
            self.relative(model_path): model_sha,
            self.relative(loco_path): loco_sha,
            self.relative(census_path): census_sha,
            self.relative(checks_path): checks_sha,
        }
        gate = {
            "schema_version": 1,
            "decision_id": "D0056",
            "analysis_profile": ANALYSIS_PROFILE,
            "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
            "primary_estimand": PRIMARY_ESTIMAND,
            "status": STEP3_PASS_STATUS,
            "scientific_gate_eligible": True,
            "interaction_status": INTERACTION_STATUS,
            "all_required_checks_pass": True,
            "passed_required_checks": 1,
            "total_required_checks": 1,
            "failed_check_ids": [],
            "checks": check_rows,
            "total_eligible_physical_passes": 219,
            "total_expected_pass_equivalents": 159.0870840462331,
            "total_planning_n": 159,
            "full_panel_primary_contrast_physical_passes": 102,
            "full_panel_primary_contrast_expected_pass_equivalents": 72.68902899522442,
            "full_panel_primary_contrast_planning_n": 72,
            "minneapolis_st_paul_excluded_primary_contrast_planning_n": 56,
            "minimum_leave_one_city_out_primary_contrast_planning_n": 54,
            "all_permitted_non_phoenix_holdouts_supported": True,
            "model_support_path": self.relative(model_path),
            "model_support_sha256": model_sha,
            "leave_one_city_out_support_path": self.relative(loco_path),
            "leave_one_city_out_support_sha256": loco_sha,
            "strata_census_path": self.relative(census_path),
            "strata_census_sha256": census_sha,
            "checks_path": self.relative(checks_path),
            "checks_sha256": checks_sha,
            "interaction_step2_gate_status": "STOP",
            "input_bindings": input_bindings,
            "artifact_sha256": artifact_ledger,
            "holdout_status": "UNSELECTED",
            "frozen_years": "2018-2025",
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
        }
        _write_json(self.paths["step3_time_of_day_gate"], gate)
        module_path = self.root / "src/urban_cooling_v2/step03_time_of_day_power.py"
        runner_path = self.root / "src/run_v2_step03_time_of_day.py"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("# fixture module\n", encoding="utf-8")
        runner_path.write_text("# fixture runner\n", encoding="utf-8")
        run = {
            "schema_version": 1,
            "decision_id": "D0056",
            "decision_ids": ["D0027", "D0047", "D0056"],
            "analysis_profile": ANALYSIS_PROFILE,
            "scientific_gate_scope": SCIENTIFIC_GATE_SCOPE,
            "primary_estimand": PRIMARY_ESTIMAND,
            "interaction_status": INTERACTION_STATUS,
            "interaction_step2_gate_status": "STOP",
            "status": STEP3_PASS_STATUS,
            "scientific_gate_eligible": True,
            "all_required_checks_pass": True,
            "failed_check_ids": [],
            "total_eligible_physical_passes": 219,
            "total_expected_pass_equivalents": 159.0870840462331,
            "total_planning_n": 159,
            "full_panel_primary_contrast_physical_passes": 102,
            "full_panel_primary_contrast_expected_pass_equivalents": 72.68902899522442,
            "full_panel_primary_contrast_planning_n": 72,
            "minneapolis_st_paul_excluded_primary_contrast_planning_n": 56,
            "minimum_leave_one_city_out_primary_contrast_planning_n": 54,
            "template_rows": 219,
            "input_bindings": input_bindings,
            "planning_sha256": input_bindings["planning_sha256"],
            "template_sha256": input_bindings["template_sha256"],
            "step2_gate_record_sha256": step2_sha,
            "config_sha256": input_bindings["config_sha256"],
            "step3_time_of_day_gate_path": self.relative(
                self.paths["step3_time_of_day_gate"]
            ),
            "step3_time_of_day_gate_sha256": sha256_file(
                self.paths["step3_time_of_day_gate"]
            ),
            "step3_module_sha256": sha256_file(module_path),
            "runner_sha256": sha256_file(runner_path),
            "holdout_status": "UNSELECTED",
            "frozen_years": "2018-2025",
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
        }
        _write_json(self.paths["step3_time_of_day_run_record"], run)

    def artifact_paths(self) -> dict[str, Path]:
        return dict(self.paths)

    def write_gate(self) -> dict:
        output = write_time_of_day_task1_pass(
            self.paths, gate_path=self.gate_path, repo_root=self.root
        )
        return json.loads(output.read_text(encoding="utf-8"))

    def rewrite_step2(self, mutation) -> None:
        path = self.paths["original_interaction_step2_gate"]
        value = json.loads(path.read_text(encoding="utf-8"))
        mutation(value)
        _write_json(path, value)
        self._build_step3()

    def rewrite_step3_gate(self, mutation) -> None:
        path = self.paths["step3_time_of_day_gate"]
        value = json.loads(path.read_text(encoding="utf-8"))
        mutation(value)
        for prefix in (
            "model_support",
            "leave_one_city_out_support",
            "strata_census",
            "checks",
        ):
            relative = value.get(f"{prefix}_path")
            digest = value.get(f"{prefix}_sha256")
            if relative and digest:
                value["artifact_sha256"][relative] = digest
        _write_json(path, value)
        run_path = self.paths["step3_time_of_day_run_record"]
        run = json.loads(run_path.read_text(encoding="utf-8"))
        run["input_bindings"] = value["input_bindings"]
        run["step2_gate_record_sha256"] = value["input_bindings"][
            "step2_gate_record_sha256"
        ]
        run["step3_time_of_day_gate_sha256"] = sha256_file(path)
        _write_json(run_path, run)


class TimeOfDayTask1GateTests(unittest.TestCase):
    def test_writer_emits_only_scoped_pass_and_preserves_generic_namespace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tod-task1-") as temporary:
            fixture = TimeOfDayFixture(Path(temporary))
            generic = fixture.root / "data/processed/v2/task1/TASK1_GATE.json"
            _write_json(generic, {"task1_gate": "SENTINEL_GENERIC_GATE"})

            gate = fixture.write_gate()

            self.assertEqual(gate["task1_gate"], TASK1_GATE_STATUS)
            self.assertEqual(gate["original_interaction_step2_gate_status"], "STOP")
            self.assertFalse(gate["original_interaction_count_support_pass"])
            self.assertEqual(
                json.loads(generic.read_text(encoding="utf-8"))["task1_gate"],
                "SENTINEL_GENERIC_GATE",
            )
            validate_time_of_day_task1_pass(
                gate, gate_path=fixture.gate_path, repo_root=fixture.root
            )

    def test_writer_refuses_to_overwrite_scoped_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tod-task1-") as temporary:
            fixture = TimeOfDayFixture(Path(temporary))
            fixture.write_gate()
            with self.assertRaisesRegex(
                TimeOfDayTask1GateError, "refusing to overwrite"
            ):
                fixture.write_gate()

    def test_original_interaction_stop_cannot_be_converted_to_pass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tod-task1-") as temporary:
            fixture = TimeOfDayFixture(Path(temporary))
            fixture.rewrite_step2(lambda value: value.__setitem__("status", "PASS"))
            with self.assertRaisesRegex(
                TimeOfDayTask1GateError, "original interaction Step-2 gate has stale status"
            ):
                fixture.write_gate()

    def test_original_count_support_failure_must_remain_visible(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tod-task1-") as temporary:
            fixture = TimeOfDayFixture(Path(temporary))
            fixture.rewrite_step2(
                lambda value: value.__setitem__("count_support_pass", True)
            )
            with self.assertRaisesRegex(
                TimeOfDayTask1GateError, "original count_support_pass must be false"
            ):
                fixture.write_gate()

    def test_step3_stop_cannot_activate_task1(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tod-task1-") as temporary:
            fixture = TimeOfDayFixture(Path(temporary))
            fixture.rewrite_step3_gate(
                lambda value: value.__setitem__(
                    "status", "STOP_TIME_OF_DAY_ONLY_STEP3"
                )
            )
            with self.assertRaisesRegex(
                TimeOfDayTask1GateError, "Step-3 gate has stale status"
            ):
                fixture.write_gate()

    def test_step3_must_bind_r0015(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tod-task1-") as temporary:
            fixture = TimeOfDayFixture(Path(temporary))
            fixture.rewrite_step3_gate(
                lambda value: value["input_bindings"].__setitem__(
                    "step2_gate_record_sha256", "f" * 64
                )
            )
            with self.assertRaisesRegex(
                TimeOfDayTask1GateError,
                "input changed|does not bind the immutable R0015 gate",
            ):
                fixture.write_gate()

    def test_thermal_or_holdout_seal_breaks_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tod-task1-") as temporary:
            fixture = TimeOfDayFixture(Path(temporary))
            fixture.rewrite_step3_gate(
                lambda value: value.__setitem__("thermal_opened", True)
            )
            with self.assertRaisesRegex(
                TimeOfDayTask1GateError, "Step-3 thermal_opened must be false"
            ):
                fixture.write_gate()

    def test_leave_one_city_out_support_is_required(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tod-task1-") as temporary:
            fixture = TimeOfDayFixture(Path(temporary))
            fixture.rewrite_step3_gate(
                lambda value: value.__setitem__(
                    "all_permitted_non_phoenix_holdouts_supported", False
                )
            )
            with self.assertRaisesRegex(
                TimeOfDayTask1GateError, "leave-one-city-out support verdict"
            ):
                fixture.write_gate()

    def test_msp_development_count_is_bound(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tod-task1-") as temporary:
            fixture = TimeOfDayFixture(Path(temporary))
            path = fixture.paths["t3t2_leave_one_city_out_support"]
            with path.open(encoding="utf-8", newline="") as source:
                rows = list(csv.DictReader(source))
            for row in rows:
                if row["excluded_city"] == "minneapolis_st_paul":
                    row["planning_n"] = "55"
            _write_csv(path, rows)
            fixture.rewrite_step3_gate(
                lambda value: value.__setitem__(
                    "leave_one_city_out_support_sha256", sha256_file(path)
                )
            )
            with self.assertRaisesRegex(
                TimeOfDayTask1GateError,
                "frozen support changed for minneapolis_st_paul",
            ):
                fixture.write_gate()

    def test_t3t1_requires_all_three_frozen_effect_sizes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tod-task1-") as temporary:
            fixture = TimeOfDayFixture(Path(temporary))
            path = fixture.paths["t3t1_time_of_day_model_support"]
            with path.open(encoding="utf-8", newline="") as source:
                fields, *rows = list(csv.reader(source))
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(fields)
                writer.writerows(rows[:2])
            fixture.rewrite_step3_gate(
                lambda value: value.__setitem__(
                    "model_support_sha256", sha256_file(path)
                )
            )
            with self.assertRaisesRegex(
                TimeOfDayTask1GateError, "exactly three effect-size rows"
            ):
                fixture.write_gate()

    def test_tampered_bound_artifact_invalidates_existing_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tod-task1-") as temporary:
            fixture = TimeOfDayFixture(Path(temporary))
            gate = fixture.write_gate()
            path = fixture.paths["t3t1_time_of_day_model_support"]
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(
                TimeOfDayTask1GateError, "artifact changed"
            ):
                validate_time_of_day_task1_pass(
                    gate, gate_path=fixture.gate_path, repo_root=fixture.root
                )

    def test_payload_cannot_remove_hydroclimatic_prohibitions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tod-task1-") as temporary:
            fixture = TimeOfDayFixture(Path(temporary))
            gate = fixture.write_gate()
            altered = deepcopy(gate)
            altered["prohibited_inference"].remove("hydroclimatic_transition_threshold")
            with self.assertRaisesRegex(
                TimeOfDayTask1GateError, "inference limits"
            ):
                validate_time_of_day_task1_pass(
                    altered, gate_path=fixture.gate_path, repo_root=fixture.root
                )


if __name__ == "__main__":
    unittest.main()
