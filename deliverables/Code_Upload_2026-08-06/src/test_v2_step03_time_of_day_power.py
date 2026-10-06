#!/usr/bin/env python3
"""Network-free tests for the isolated D0056 time-of-day Step-3 branch."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_v2_step03_time_of_day as runner  # noqa: E402
from urban_cooling_v2 import step03_time_of_day_power as tod  # noqa: E402


def synthetic_template(rows_per_cell: int = 6) -> pd.DataFrame:
    rng = np.random.default_rng(20260806)
    rows = []
    stratum_hours = {"10-12": 11.0, "12-14": 13.0, "14-16": 15.0, "16-18": 17.0}
    counter = 0
    for city in tod.EXPECTED_CITIES:
        for stratum, center in stratum_hours.items():
            for replicate in range(rows_per_cell):
                date = pd.Timestamp("2023-06-01") + pd.Timedelta(
                    days=int(rng.integers(0, 122))
                )
                rows.append(
                    {
                        "source_pass_id": f"synthetic_{counter:05d}",
                        "city": city,
                        "demand_percentile": float(rng.uniform()),
                        "antecedent_dryness_percentile": float(rng.uniform()),
                        "local_solar_time_hours": center + float(rng.uniform(-0.4, 0.4)),
                        "solar_zenith_deg": float(rng.uniform(18, 78)),
                        "solar_azimuth_deg": float(rng.uniform(0, 360)),
                        "local_solar_date": date.strftime("%Y-%m-%d"),
                        "acquisition_utc": date.tz_localize("UTC")
                        + pd.Timedelta(hours=float(rng.uniform(14, 23))),
                        "sampling_weight": float(rng.uniform(0.3, 1.0)),
                        "template_geometry_status": tod.OBSERVED_GEOMETRY_STATUS,
                    }
                )
                counter += 1
    return pd.DataFrame(rows)


class TimeOfDayPowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.template = synthetic_template()

    def test_live_nonthermal_inputs_and_exact_support_are_bound(self) -> None:
        inputs = runner.load_inputs()
        validation = inputs["validation"]
        self.assertEqual(validation["total_eligible_physical_passes"], 219)
        self.assertAlmostEqual(
            validation["total_expected_pass_equivalents"],
            159.08708404623306,
            places=10,
        )
        self.assertEqual(validation["full_panel_primary_contrast_planning_n"], 72)
        self.assertEqual(
            validation["minimum_leave_one_city_out_primary_contrast_planning_n"],
            54,
        )
        self.assertEqual(
            validation[
                "minneapolis_st_paul_excluded_primary_contrast_planning_n"
            ],
            56,
        )
        self.assertEqual(validation["interaction_status"], tod.INTERACTION_STATUS)
        self.assertFalse(validation["thermal_opened"])

    def test_primary_contrast_excludes_middle_strata(self) -> None:
        validated = tod.validate_time_template(self.template)
        primary = tod.primary_contrast_template(validated)
        self.assertEqual(set(primary["time_stratum"].astype(str)), {"10-12", "16-18"})
        self.assertEqual(len(primary), 2 * 5 * 6)
        census = tod.empirical_strata_census(validated)
        self.assertEqual(len(census), 20)
        self.assertTrue(census["physical_passes"].eq(6).all())

    def test_stratified_sampler_preserves_every_primary_city_cell(self) -> None:
        sampled = tod.sample_primary_passes(
            self.template, 50, np.random.default_rng(7)
        )
        cells = sampled.groupby(["city", "time_stratum"], observed=True).size()
        self.assertEqual(len(sampled), 50)
        self.assertEqual(len(cells), 10)
        self.assertTrue(cells.gt(0).all())
        self.assertEqual(sampled["pass_id"].nunique(), 50)

    def test_large_sample_recovers_known_time_contrast(self) -> None:
        spec = tod.TimeOfDaySimulationSpec(
            rows_per_pass=8,
            matched_sets_per_pass=2,
        )
        data = tod.simulate_clustered_time_of_day_data(
            self.template,
            1000,
            1.5,
            spec,
            np.random.default_rng(11),
        )
        fit = tod.fit_time_contrast(data)
        self.assertAlmostEqual(fit.estimate, 1.5, delta=0.20)
        self.assertLess(fit.p_value, 0.001)
        self.assertEqual(fit.n_passes, 1000)
        self.assertEqual(fit.covariance, "pass_cluster")

    def test_pass_cluster_uncertainty_exceeds_naive_row_uncertainty(self) -> None:
        spec = tod.TimeOfDaySimulationSpec(
            rows_per_pass=12,
            matched_sets_per_pass=3,
        )
        data = tod.simulate_clustered_time_of_day_data(
            self.template,
            80,
            1.5,
            spec,
            np.random.default_rng(17),
        )
        clustered = tod.fit_time_contrast(data, covariance="pass_cluster")
        naive = tod.fit_time_contrast(data, covariance="naive_row")
        self.assertGreater(clustered.std_error, naive.std_error)

    def test_small_study_and_writer_keep_interaction_stop(self) -> None:
        spec = tod.TimeOfDaySimulationSpec(
            rows_per_pass=6,
            matched_sets_per_pass=2,
        )
        results = tod.run_time_of_day_simulation_study(
            self.template,
            pass_counts=(40, 80),
            spec=spec,
            n_replicates=2,
            n_coverage_replicates=2,
            n_boot=10,
            input_eligible=True,
            interaction_stop_preserved=True,
        )
        support = tod.summarize_model_support(results)
        self.assertEqual(len(support), 3)
        self.assertIn("full_panel_primary_contrast_planning_n", support)
        self.assertEqual(
            set(results["leave_one_city_out"]["excluded_city"]),
            set(tod.PERMITTED_NON_PHOENIX_HOLDOUTS),
        )
        with tempfile.TemporaryDirectory() as temporary:
            paths = tod.write_time_of_day_deliverables(
                results,
                Path(temporary),
                output_relative_root="data/processed/v2/task1/test_D0056",
                input_bindings={"step2_gate_record_sha256": "0" * 64},
            )
            gate = json.loads(paths["gate"].read_text(encoding="utf-8"))
            self.assertEqual(gate["schema_version"], 1)
            self.assertEqual(gate["interaction_status"], tod.INTERACTION_STATUS)
            self.assertEqual(gate["analysis_profile"], "D0056_time_of_day_only")
            self.assertFalse(gate["thermal_opened"])
            self.assertEqual(
                gate["leave_one_city_out_support_path"],
                "data/processed/v2/task1/test_D0056/tables/"
                "T3T.2_leave_one_city_out_support.csv",
            )


if __name__ == "__main__":
    unittest.main()
