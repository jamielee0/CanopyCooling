#!/usr/bin/env python3
"""Network-free tests for the outcome-blind v6.2 D1b audit."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

import pandas as pd

from urban_cooling_v2.connectivity_audit import (
    largest_component_edge_share,
    local_solar_date,
    select_candidate_passes,
    spatial_sector,
    summarize_combination,
    validate_summary_rows,
)


class ConnectivityAuditTests(unittest.TestCase):
    def test_local_solar_date_crosses_previous_day(self):
        self.assertEqual(local_solar_date("2025-06-02T01:00:00Z", -120), date(2025, 6, 1))

    def test_spatial_quadrants(self):
        self.assertEqual(spatial_sector(-1, 1, 0, 0), "NW")
        self.assertEqual(spatial_sector(1, 1, 0, 0), "NE")
        self.assertEqual(spatial_sector(-1, -1, 0, 0), "SW")
        self.assertEqual(spatial_sector(1, -1, 0, 0), "SE")

    def test_largest_component_uses_edge_share(self):
        edges = [("b1", "p1"), ("b2", "p1"), ("b2", "p2"), ("b3", "p3")]
        self.assertAlmostEqual(largest_component_edge_share(edges), 0.75)

    def test_candidate_filter_is_year_window_quality_and_view_bounded(self):
        rows = pd.DataFrame(
            [
                ["phoenix", "1", "2020-06-02T01:00:00Z", 2020, True, 14.0],
                ["phoenix", "2", "2020-07-12T20:00:00Z", 2020, True, 14.0],
                ["phoenix", "3", "2020-06-20T20:00:00Z", 2020, False, 10.0],
                ["phoenix", "4", "2020-06-20T20:00:00Z", 2020, True, 16.0],
                ["phoenix", "1", "2020-06-02T01:00:00Z", 2020, True, 14.0],
            ],
            columns=[
                "city",
                "orbit",
                "acquisition_utc",
                "year",
                "quality_and_exact_weather_complete",
                "l1b_view_zenith_abs_p95_deg",
            ],
        )
        selected = select_candidate_passes(
            rows,
            city="phoenix",
            longitude_degrees=-112,
            season_window="provisional_primary",
            view_zenith_maximum_degrees=15,
        )
        self.assertEqual(selected["orbit"].tolist(), ["1"])
        self.assertEqual(selected.iloc[0]["local_solar_date"], date(2020, 6, 1))

    def test_summary_metrics_and_thresholds(self):
        blocks = pd.DataFrame(
            {
                "block_id": [f"b{i}" for i in range(30)],
                "sector": ["NW", "NE", "SW", "SE"] * 7 + ["NW", "NE"],
                "land_use_class": ["Developed, Open Space"] * 20 + ["Shrub/Scrub"] * 10,
            }
        )
        edges = pd.DataFrame(
            [(f"b{i}", f"p{j}") for i in range(30) for j in range(8)],
            columns=["block_id", "pass_id"],
        )
        row = summarize_combination(
            city="phoenix", season_window="sensitivity", view_set=15, edges=edges, blocks=blocks
        )
        self.assertEqual(row["eligible_blocks"], 30)
        self.assertEqual(row["median_passes_per_block"], 8)
        self.assertEqual(row["blocks_below_floor"], 0)
        self.assertEqual(row["largest_connected_component_share"], 1)
        self.assertTrue(row["combination_pass"])

    def test_eight_row_validation_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "exactly eight"):
            validate_summary_rows([])

    def test_source_contains_no_lst_asset_open(self):
        source = Path(__file__).with_name("urban_cooling_v2").joinpath("connectivity_audit.py").read_text()
        self.assertNotIn('"lst" /', source.lower())
        self.assertNotIn("lst_cog", source.lower())


if __name__ == "__main__":
    unittest.main()
