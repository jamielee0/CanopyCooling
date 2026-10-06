#!/usr/bin/env python3
"""Deterministic tests for the Guide Step 3 simulation and power gate."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from urban_cooling_v2 import step03_power as step3  # noqa: E402


class Step3PowerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = step3.SimulationSpec(
            seed=20260801,
            rows_per_pass=12,
            matched_sets_per_pass=3,
            effect_sizes_k=(0.75, 1.5, 2.25),
        )
        self.template = step3.synthetic_pass_template(800, np.random.default_rng(9), rho=0.45)

    def test_large_sample_recovers_known_interaction(self) -> None:
        large_template = step3.synthetic_pass_template(5000, np.random.default_rng(9), rho=0.45)
        data = step3.simulate_clustered_data(
            large_template, 4000, 1.5, self.spec, np.random.default_rng(11)
        )
        fit = step3.fit_interaction(data)
        self.assertAlmostEqual(fit.estimate, 1.5, delta=0.20)
        self.assertLess(fit.p_value, 0.001)
        self.assertEqual(fit.n_passes, 4000)
        self.assertEqual(fit.covariance, "pass_cluster")

    def test_cluster_standard_error_exceeds_naive_row_error(self) -> None:
        data = step3.simulate_clustered_data(
            self.template, 80, 1.5, self.spec, np.random.default_rng(17)
        )
        clustered = step3.fit_interaction(data, covariance="pass_cluster")
        naive = step3.fit_interaction(data, covariance="naive_row")
        self.assertGreater(clustered.std_error, naive.std_error)

    def test_synthetic_geometry_is_plausible_correlated_and_cyclic(self) -> None:
        template = step3.synthetic_pass_template(5000, np.random.default_rng(77), rho=0.45)
        self.assertTrue(template["solar_zenith_deg"].between(0, 180).all())
        self.assertTrue(template["solar_azimuth_deg"].between(0, 360, inclusive="left").all())
        distance_from_noon = (template["local_solar_time"] - 12.0).abs()
        self.assertGreater(
            distance_from_noon.corr(template["solar_zenith_deg"], method="spearman"),
            0.70,
        )
        morning = template.loc[template["local_solar_time"] < 12]
        afternoon = template.loc[template["local_solar_time"] > 12]
        self.assertGreater((morning["solar_azimuth_deg"] < 180).mean(), 0.98)
        self.assertGreater((afternoon["solar_azimuth_deg"] > 180).mean(), 0.98)
        self.assertTrue(template["acquisition_utc"].notna().all())
        self.assertTrue(template["source_date"].str.match(r"\d{4}-\d{2}-\d{2}").all())

        data = step3.simulate_clustered_data(
            template, 70, 1.5, self.spec, np.random.default_rng(78)
        )
        np.testing.assert_allclose(
            data["solar_azimuth_sin"] ** 2 + data["solar_azimuth_cos"] ** 2,
            1.0,
            rtol=0,
            atol=1e-14,
        )
        self.assertIn("source_date", data)
        self.assertIn("acquisition_utc", data)
        self.assertTrue(data.groupby("pass_id")["source_date"].nunique().eq(1).all())
        _, design_names = step3._design_matrix(data, include_three_way=True)
        for nuisance in (
            "solar_zenith_c",
            "solar_azimuth_sin",
            "solar_azimuth_cos",
        ):
            self.assertIn(nuisance, design_names)
        boundary = np.deg2rad([359.0, 1.0])
        cyclic_distance = np.linalg.norm(
            np.array([np.sin(boundary[0]), np.cos(boundary[0])])
            - np.array([np.sin(boundary[1]), np.cos(boundary[1])])
        )
        self.assertLess(cyclic_distance, 0.04)

    def test_empirical_geometry_is_required_and_legacy_path_is_explicit(self) -> None:
        observed = self.template.head(20).drop(columns="template_geometry_status")
        validated = step3.validate_template(observed)
        self.assertEqual(
            set(validated["template_geometry_status"]),
            {step3.OBSERVED_GEOMETRY_STATUS},
        )
        self.assertIn("source_date", validated)
        self.assertIn("acquisition_utc", validated)
        step2_named = observed.rename(
            columns={
                "demand_pct": "demand_percentile",
                "dryness_pct": "antecedent_dryness_percentile",
                "local_solar_time": "local_solar_time_hours",
                "source_pass_id": "scene_key",
                "source_date": "local_solar_date",
            }
        )
        self.assertEqual(len(step3.validate_template(step2_named)), len(step2_named))
        mixed_timestamp = observed.copy()
        mixed_timestamp["acquisition_utc"] = [
            "2024-08-03T23:15:32.833Z"
            if index == 0
            else f"2024-08-{(index % 20) + 1:02d}T23:16:58Z"
            for index in range(len(mixed_timestamp))
        ]
        self.assertEqual(
            len(step3.validate_template(mixed_timestamp)), len(mixed_timestamp)
        )

        missing = observed.drop(columns=["solar_zenith_deg", "solar_azimuth_deg"])
        with self.assertRaisesRegex(ValueError, "required observed solar geometry"):
            step3.validate_template(missing)

        legacy = missing.assign(
            template_geometry_status=step3.LEGACY_PRELIMINARY_GEOMETRY_STATUS
        )
        reconstructed = step3.validate_template(
            legacy, allow_legacy_preliminary_geometry=True
        )
        self.assertEqual(
            set(reconstructed["template_geometry_status"]),
            {step3.LEGACY_RECONSTRUCTED_GEOMETRY_STATUS},
        )
        self.assertTrue(reconstructed["solar_zenith_deg"].notna().all())
        with self.assertRaisesRegex(ValueError, "requires observed solar geometry"):
            step3.run_simulation_study(
                actual_n_passes=20,
                pass_counts=(20,),
                spec=self.spec,
                template=legacy,
                n_replicates=1,
                n_coverage_replicates=1,
                n_boot=10,
                count_status="certified_usable_passes",
                allow_legacy_preliminary_geometry=True,
            )

    def test_cloud_survival_sampling_weights_are_preserved_and_used(self) -> None:
        template = self.template.head(5).copy()
        template["sampling_weight"] = [100.0, 1.0, 1.0, 1.0, 1.0]
        validated = step3.validate_template(template)
        self.assertIn("sampling_weight", validated)
        sampled = step3._sample_passes(
            validated, 1000, np.random.default_rng(20260801)
        )
        self.assertGreater(
            sampled["source_pass_id"].eq(template.iloc[0]["source_pass_id"]).mean(),
            0.90,
        )
        zero_weight = template.copy()
        zero_weight["sampling_weight"] = [0.0, 1.0, 1.0, 1.0, 1.0]
        validated_zero = step3.validate_template(zero_weight)
        self.assertEqual(len(validated_zero), len(zero_weight))
        sampled_zero = step3._sample_passes(
            validated_zero, 20, np.random.default_rng(20260802)
        )
        self.assertFalse(
            sampled_zero["source_pass_id"].eq(zero_weight.iloc[0]["source_pass_id"]).any()
        )
        with self.assertRaisesRegex(ValueError, "finite nonnegative"):
            step3.validate_template(template.assign(sampling_weight=-1.0))
        with self.assertRaisesRegex(ValueError, "positive total"):
            step3.validate_template(template.assign(sampling_weight=0.0))

    def test_expected_pass_equivalent_floor_is_a_certified_count_status(self) -> None:
        observed = self.template.head(20).assign(
            template_geometry_status=step3.OBSERVED_GEOMETRY_STATUS,
            sampling_weight=0.5,
        )
        results = step3.run_simulation_study(
            actual_n_passes=10,
            pass_counts=(10,),
            spec=self.spec,
            template=observed,
            n_replicates=1,
            n_coverage_replicates=1,
            n_boot=5,
            count_status="certified_expected_pass_equivalent_floor",
        )
        self.assertTrue(step3.summarize_support(results)["scientific_gate_eligible"].all())
        self.assertEqual(
            results["run_settings"]["sampling_weight_status"],
            "cloud_survival_weighted",
        )

    def test_archive_available_floor_is_a_certified_count_status(self) -> None:
        self.assertIn(
            "certified_archive_available_expected_pass_equivalent_floor",
            step3.CERTIFIED_COUNT_STATUSES,
        )

    def test_vectorized_simulator_preserves_frozen_noise_sequence_with_controls(self) -> None:
        spec = step3.SimulationSpec(rows_per_pass=6, matched_sets_per_pass=2)
        template = step3.synthetic_pass_template(20, np.random.default_rng(9), rho=0.45)
        data = step3.simulate_clustered_data(
            template,
            5,
            1.5,
            spec,
            np.random.default_rng(11),
            three_way_effect_k=0.5,
        )
        self.assertEqual(len(data), 30)
        self.assertEqual(data.iloc[0]["source_pass_id"], "template_00016")
        self.assertEqual(data.iloc[-1]["matched_set_id"], "pass_00004_set_1")
        np.testing.assert_allclose(
            data["cooling_advantage_k"].iloc[[0, 1, -1]],
            [4.038887830227392, 0.14757220738141186, 1.4371071672765572],
            rtol=0,
            atol=1e-14,
        )
        for nuisance in (
            "solar_zenith_c",
            "solar_azimuth_sin",
            "solar_azimuth_cos",
        ):
            self.assertIn(nuisance, data)

    def test_sufficient_statistic_bootstrap_matches_reference_refit(self) -> None:
        data = step3.simulate_clustered_data(
            self.template, 70, 1.5, self.spec, np.random.default_rng(101)
        )

        def reference(method: str, seed: int) -> tuple[float, float]:
            rng = np.random.default_rng(seed)
            estimates = []
            if method == "pass":
                pass_ids = pd.unique(data["pass_id"])
                for _ in range(16):
                    selected = rng.choice(pass_ids, size=len(pass_ids), replace=True)
                    chunks = []
                    for draw_index, pass_id in enumerate(selected):
                        chunk = data.loc[data["pass_id"] == pass_id].copy()
                        chunk["pass_id"] = f"boot_{draw_index:05d}"
                        chunks.append(chunk)
                    sample = pd.concat(chunks, ignore_index=True)
                    estimates.append(
                        step3.fit_interaction(
                            sample, term="interaction", covariance="naive_row"
                        ).estimate
                    )
            else:
                for _ in range(16):
                    selected = rng.integers(0, len(data), len(data))
                    estimates.append(
                        step3.fit_interaction(
                            data.iloc[selected].reset_index(drop=True),
                            term="interaction",
                            covariance="naive_row",
                        ).estimate
                    )
            return tuple(np.quantile(estimates, [0.025, 0.975]))

        for method, seed in (("pass", 102), ("row", 103)):
            expected = reference(method, seed)
            observed = step3.bootstrap_interval(
                data,
                term="interaction",
                method=method,
                n_boot=16,
                rng=np.random.default_rng(seed),
            )
            np.testing.assert_allclose(observed, expected, rtol=0, atol=1e-10)

    def test_no_interaction_type_one_error_is_near_nominal(self) -> None:
        rng = np.random.default_rng(23)
        detected = []
        for _ in range(160):
            data = step3.simulate_clustered_data(self.template, 120, 0.0, self.spec, rng)
            detected.append(step3.fit_interaction(data).p_value < self.spec.alpha)
        rate = np.mean(detected)
        self.assertGreaterEqual(rate, 0.01)
        self.assertLessEqual(rate, 0.10)

    def test_smooth_transition_test_tracks_spurious_break_without_forcing_claim(self) -> None:
        smooth = step3.simulate_smooth_no_breakpoint(
            self.template, 150, self.spec, np.random.default_rng(31)
        )
        result = step3.transition_test(smooth)
        self.assertGreaterEqual(result["best_breakpoint"], 0.0)
        self.assertLessEqual(result["best_breakpoint"], 1.0)
        self.assertGreaterEqual(result["adjusted_p_value"], result["raw_p_value"])

    def test_whole_pass_bootstrap_is_wider_than_naive_row_bootstrap(self) -> None:
        data = step3.simulate_clustered_data(
            self.template, 70, 1.5, self.spec, np.random.default_rng(41)
        )
        block = step3.bootstrap_interval(
            data, term="interaction", method="pass", n_boot=80, rng=np.random.default_rng(42)
        )
        row = step3.bootstrap_interval(
            data, term="interaction", method="row", n_boot=80, rng=np.random.default_rng(43)
        )
        self.assertGreater(block[1] - block[0], row[1] - row[0])

    def test_tiny_study_writes_all_deliverables(self) -> None:
        results = step3.run_simulation_study(
            actual_n_passes=30,
            pass_counts=(20, 40),
            spec=self.spec,
            template=self.template,
            n_replicates=5,
            n_coverage_replicates=3,
            n_boot=20,
            count_status="synthetic_code_validation",
            template_status="synthetic_astronomical_geometry_code_validation",
        )
        support = step3.summarize_support(results)
        self.assertEqual(set(support["model"]), {"demand_by_dryness", "demand_by_dryness_by_time"})
        for column in (
            "power_mc_ci_low",
            "power_mc_ci_high",
            "type_i_error_at_planning_n",
            "type_i_error_mc_ci_low",
            "type_i_error_mc_ci_high",
        ):
            self.assertIn(column, support)
        self.assertEqual(len(results["interaction_null"]), 3 * 5)
        self.assertEqual(len(results["three_way_null"]), 3 * 5)
        self.assertFalse(results["geometry_gate_eligible"])
        with tempfile.TemporaryDirectory() as tmp:
            paths = step3.write_step3_deliverables(results, tmp)
            for deliverable in (
                "F3.1",
                "F3.2",
                "F3.3",
                "F3.4",
                "F3.5",
                "T3.1",
                "M3.1",
                "diagnostic_checks",
                "diagnostic_gate",
            ):
                self.assertTrue(paths[deliverable].exists(), deliverable)
                self.assertGreater(paths[deliverable].stat().st_size, 0)
            self.assertTrue(paths["provenance"].exists())
            self.assertTrue(paths["model_error_summary"].exists())
            error_summary = pd.read_csv(paths["model_error_summary"])
            self.assertEqual(
                set(error_summary["test"]),
                {
                    "demand_by_dryness_null",
                    "demand_by_dryness_by_time_null",
                    "smooth_truth_transition_test",
                },
            )
            self.assertTrue(
                error_summary["false_positive_rate"].between(0, 1).all()
            )
            self.assertTrue(
                error_summary["false_positive_rate_mc_ci_low"]
                .le(error_summary["false_positive_rate"])
                .all()
            )
            self.assertTrue(
                error_summary["false_positive_rate_mc_ci_high"]
                .ge(error_summary["false_positive_rate"])
                .all()
            )
            provenance = paths["provenance"].read_text(encoding="utf-8")
            self.assertIn('"n_replicates": 5', provenance)
            self.assertIn('"n_coverage_replicates": 3', provenance)
            self.assertIn('"n_boot": 20', provenance)
            self.assertIn('"normalized_template_sha256"', provenance)
            self.assertIn(step3.SYNTHETIC_GEOMETRY_STATUS, provenance)
            memo = paths["M3.1"].read_text(encoding="utf-8")
            self.assertIn("Monte Carlo profile", memo)

    def test_simulation_rejects_zero_replicate_profiles(self) -> None:
        with self.assertRaisesRegex(ValueError, "n_replicates"):
            step3.run_simulation_study(
                actual_n_passes=30,
                pass_counts=(20, 40),
                spec=self.spec,
                template=self.template,
                n_replicates=0,
                n_coverage_replicates=3,
                n_boot=20,
            )

    def test_frozen_diagnostic_gate_reports_compound_d0027_checks(self) -> None:
        spec = step3.SimulationSpec()

        def binary_rows(total: int, successes: int, **columns) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    **{name: [value] * total for name, value in columns.items()},
                    "detected": [True] * successes + [False] * (total - successes),
                }
            )

        power_parts = []
        for n_passes in (50, 800):
            for effect in spec.effect_sizes_k:
                detected = 90 if (n_passes == 50 and effect == spec.primary_effect_size_k) else 80
                estimates = np.full(100, effect + 0.05)
                power_parts.append(
                    pd.DataFrame(
                        {
                            "n_passes": n_passes,
                            "effect_size_k": effect,
                            "estimate_k": estimates,
                            "detected": [True] * detected + [False] * (100 - detected),
                        }
                    )
                )
        coverage = pd.concat(
            [
                binary_rows(
                    60,
                    57,
                    n_passes=50,
                    method="pass-level block bootstrap",
                ).rename(columns={"detected": "covered"}),
                binary_rows(
                    60,
                    42,
                    n_passes=50,
                    method="naive row bootstrap",
                ).rename(columns={"detected": "covered"}),
            ],
            ignore_index=True,
        )
        results = {
            "spec": spec,
            "actual_n_passes": 50,
            "count_status": "certified_expected_pass_equivalent_floor",
            "geometry_gate_eligible": True,
            "power": pd.concat(power_parts, ignore_index=True),
            "interaction_null": binary_rows(100, 5, n_passes=50),
            "three_way_null": binary_rows(100, 5, n_passes=50),
            "transition": binary_rows(100, 5, n_passes=50),
            "coverage": coverage,
        }
        gate = step3.evaluate_diagnostic_gate(results)
        self.assertEqual(gate["summary"]["decision_id"], "D0027")
        self.assertEqual(gate["summary"]["status"], "PASS")
        self.assertFalse(gate["summary"]["failed_check_ids"])
        self.assertTrue(gate["checks"]["passed"].all())
        null_checks = gate["checks"].loc[
            gate["checks"]["category"].eq("false_positive_control")
        ]
        self.assertEqual(len(null_checks), 3)
        self.assertTrue(
            null_checks["mc_ci_low"].le(spec.alpha).all()
            and null_checks["mc_ci_high"].ge(spec.alpha).all()
        )

        failed = dict(results)
        failed_power = results["power"].copy()
        primary_actual = failed_power["n_passes"].eq(50) & np.isclose(
            failed_power["effect_size_k"], spec.primary_effect_size_k
        )
        failed_power.loc[primary_actual, "detected"] = False
        failed["power"] = failed_power
        failed_gate = step3.evaluate_diagnostic_gate(failed)
        self.assertEqual(failed_gate["summary"]["status"], "FAIL")
        self.assertIn(
            "primary_effect_power", failed_gate["summary"]["failed_check_ids"]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
