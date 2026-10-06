#!/usr/bin/env python3
"""Network-free tests for the v6.2 D1c lead-lag feasibility audit."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from urban_cooling_v2.lead_lag_feasibility import (
    centered_count_proxy,
    choose_matched_pair,
    confirmatory_ruling,
    required_grid_rows,
    validate_required_grid,
)


class LeadLagFeasibilityTests(unittest.TestCase):
    def test_pair_requires_distinct_pre_and_post_with_comparable_lags(self):
        ledger = pd.DataFrame(
            [
                ["pre", "HLSL30.002", "2023-06-07T12:00:00Z"],
                ["post", "HLSL30.002", "2023-06-13T12:00:00Z"],
                ["wrong_sensor", "HLSS30.002", "2023-06-10T12:00:00Z"],
            ],
            columns=["optical_acquisition_id", "sensor", "source_time"],
        )
        pair = choose_matched_pair("2023-06-10T12:00:00Z", ledger, sensor="HLSL30.002")
        self.assertIsNotNone(pair)
        self.assertEqual(pair["pre_acquisition_id"], "pre")
        self.assertEqual(pair["post_acquisition_id"], "post")
        self.assertEqual(pair["lag_imbalance_days"], 0)

    def test_pair_fails_when_lags_are_not_comparable(self):
        ledger = pd.DataFrame(
            [
                ["pre", "HLSL30.002", "2023-06-09T12:00:00Z"],
                ["post", "HLSL30.002", "2023-06-20T12:00:00Z"],
            ],
            columns=["optical_acquisition_id", "sensor", "source_time"],
        )
        self.assertIsNone(
            choose_matched_pair("2023-06-10T12:00:00Z", ledger, sensor="HLSL30.002")
        )

    def test_pair_fails_when_identifier_is_reused_on_both_sides(self):
        ledger = pd.DataFrame(
            [
                ["same", "HLSL30.002", "2023-06-08T12:00:00Z"],
                ["same", "HLSL30.002", "2023-06-12T12:00:00Z"],
            ],
            columns=["optical_acquisition_id", "sensor", "source_time"],
        )
        self.assertIsNone(
            choose_matched_pair("2023-06-10T12:00:00Z", ledger, sensor="HLSL30.002")
        )

    def test_centered_count_is_upper_bound_only(self):
        result = centered_count_proxy(np.array([[1, 2], [3, 4]], dtype="int16"))
        self.assertEqual(result["median_valid_scene_count"], 2.5)
        self.assertTrue(result["centered_count_ge2_upper_bound"])
        self.assertNotIn("matched_pre_post", result)

    def test_required_grid_has_56_unique_rows(self):
        rows = required_grid_rows({("phoenix", 2023, "sensitivity"): 3})
        validate_required_grid(rows)
        self.assertEqual(len(rows), 56)
        selected = [
            row
            for row in rows
            if row["city"] == "Phoenix"
            and row["year"] == 2023
            and row["season_window"] == "sensitivity"
        ]
        self.assertEqual({row["candidate_passes"] for row in selected}, {3})

    def test_missing_timing_provenance_demotes(self):
        rows = required_grid_rows({})
        self.assertEqual(
            confirmatory_ruling(
                rows,
                source_dates_available=False,
                acquisition_identifiers_available=False,
            ),
            "DEMOTE_TO_EXPLORATORY_MISSING_SOURCE_TIMING_PROVENANCE",
        )

    def test_share_threshold_can_be_varied_for_labeled_sensitivity(self):
        rows = required_grid_rows({})
        for city in ("Phoenix", "Los Angeles"):
            row = next(
                item
                for item in rows
                if item["city"] == city
                and item["year"] == 2019
                and item["season_window"] == "provisional_primary"
                and item["sensor"] == "HLSL30.002"
            )
            row.update(
                {
                    "candidate_passes": 5,
                    "passes_with_feasible_matched_pre_post": 1,
                    "feasible_share": 0.20,
                    "max_thermal_passes_sharing_one_acquisition": 1,
                }
            )
        self.assertEqual(
            confirmatory_ruling(
                rows,
                source_dates_available=True,
                acquisition_identifiers_available=True,
            ),
            "DEMOTE_TO_EXPLORATORY_CONFIRMATORY_SUPPORT_RULE_FAILED",
        )
        self.assertEqual(
            confirmatory_ruling(
                rows,
                source_dates_available=True,
                acquisition_identifiers_available=True,
                minimum_confirmatory_share=0.20,
            ),
            "KEEP_CONFIRMATORY",
        )

    def test_share_threshold_must_be_a_probability(self):
        with self.assertRaises(ValueError):
            confirmatory_ruling(
                required_grid_rows({}),
                source_dates_available=True,
                acquisition_identifiers_available=True,
                minimum_confirmatory_share=1.01,
            )

    def test_runner_has_no_optical_value_or_lst_array_access(self):
        source = Path(__file__).with_name("run_v6_2_d1c_leadlag.py").read_text(encoding="utf-8")
        self.assertNotIn('ds["observed"]', source)
        self.assertNotIn('ds["clim_mean"]', source)
        self.assertNotIn('ds["clim_std"]', source)
        self.assertNotIn("lst_cog", source.lower())


if __name__ == "__main__":
    unittest.main()
