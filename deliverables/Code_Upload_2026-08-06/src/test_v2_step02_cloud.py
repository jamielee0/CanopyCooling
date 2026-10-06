#!/usr/bin/env python3
"""Tests for the frozen Step-2 cloud expansion rule."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from urban_cooling_v2.step02_cloud import evaluate_cloud_stability  # noqa: E402


def _rows(values: dict[str, dict[int, float]]) -> pd.DataFrame:
    rows = []
    for city, years in values.items():
        for year, fraction in years.items():
            rows.append(
                {
                    "city": city,
                    "month_key": f"{year:04d}-07",
                    "n_near_nadir_passes": 2,
                    "n_domain_pixels": 1000,
                    "n_clear_pixels": int(1000 * fraction),
                }
            )
    return pd.DataFrame(rows)


class CloudStabilityTests(unittest.TestCase):
    def test_primary_month_is_retained_when_independent_month_passes(self) -> None:
        data = _rows(
            {
                "phoenix": {2022: 0.70, 2023: 0.76},
                "miami": {2022: 0.42, 2023: 0.50},
            }
        )
        summary, _ = evaluate_cloud_stability(data)
        self.assertTrue(summary["representative"].all())
        self.assertEqual(set(summary["calibration_stage"]), {"primary_2023_validation_2022"})
        self.assertAlmostEqual(
            summary.set_index("reference_city").loc["phoenix", "cloud_survival_fraction"],
            0.76,
        )

    def test_failed_primary_uses_first_complete_passing_expansion(self) -> None:
        values = {
            "phoenix": {2021: 0.70, 2022: 0.60, 2023: 0.75, 2024: 0.70},
            "miami": {2021: 0.40, 2022: 0.30, 2023: 0.45, 2024: 0.40},
        }
        summary, audit = evaluate_cloud_stability(_rows(values), tolerance=0.12)
        self.assertTrue(summary["representative"].all())
        self.assertEqual(set(summary["calibration_stage"]), {"expanded_2021_through_2024"})
        self.assertTrue(
            audit.loc[
                audit["calibration_stage"].eq("expanded_2021_through_2024"),
                "city_pass",
            ].all()
        )
        self.assertAlmostEqual(
            summary.set_index("reference_city").loc["phoenix", "cloud_survival_fraction"],
            0.6875,
        )

    def test_failure_requests_only_the_next_frozen_pair(self) -> None:
        data = _rows(
            {
                "phoenix": {2022: 0.20, 2023: 0.80},
                "miami": {2022: 0.20, 2023: 0.80},
            }
        )
        summary, _ = evaluate_cloud_stability(data)
        self.assertFalse(summary["representative"].any())
        self.assertTrue(summary["cloud_survival_fraction"].isna().all())
        self.assertEqual(
            set(summary["next_action"]),
            {"add_frozen_2021_and_2024_july_pair_for_both_cities"},
        )

    def test_attempted_zero_pass_expansion_advances_to_next_pair(self) -> None:
        data = _rows(
            {
                "phoenix": {2022: 0.90, 2023: 0.95, 2024: 0.94},
                "miami": {2022: 0.80},
            }
        )
        summary, audit = evaluate_cloud_stability(
            data, attempted_years=(2021, 2022, 2023, 2024)
        )
        self.assertEqual(
            set(summary["calibration_stage"]),
            {"expanded_2021_through_2024"},
        )
        self.assertEqual(
            set(summary["next_action"]),
            {"add_frozen_2020_and_2025_july_pair_for_both_cities"},
        )
        self.assertTrue(
            audit.loc[
                audit["calibration_stage"].eq("expanded_2021_through_2024"),
                "stage_attempted",
            ].all()
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
