#!/usr/bin/env python3
"""Network-free tests for the v6.2 D018 HLS Fmask reassessment."""

from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from urban_cooling_v2.hls_fmask_lead_lag import (
    choose_quality_screened_pair,
    clear_fmask_cells,
    evaluate_quality_screened_pair,
    required_quality_grid_rows,
)
from urban_cooling_v2.lead_lag_feasibility import validate_required_grid


class HlsFmaskLeadLagTests(unittest.TestCase):
    def test_clear_mask_implements_frozen_bits_and_aerosol(self):
        values = np.array(
            [[0, 1, 2, 4, 8, 16, 32, 128, 192, 255]], dtype=np.uint8
        )
        valid = np.ones(values.shape, dtype=bool)
        result = clear_fmask_cells(values, valid_source=valid)
        self.assertEqual(
            result.tolist(),
            [[True, True, False, False, False, False, False, True, False, False]],
        )

    def test_source_nodata_mask_is_respected(self):
        values = np.array([[0, 0]], dtype=np.uint8)
        result = clear_fmask_cells(
            values, valid_source=np.array([[True, False]], dtype=bool)
        )
        self.assertEqual(result.tolist(), [[True, False]])

    def test_pair_requires_thirty_common_usable_blocks(self):
        ledger = pd.DataFrame(
            [
                ["pre", "HLSL30.002", "2023-06-07T12:00:00Z"],
                ["post", "HLSL30.002", "2023-06-13T12:00:00Z"],
            ],
            columns=["optical_acquisition_id", "sensor", "source_time"],
        )
        blocks = {"pre": range(40), "post": range(10, 40)}
        pair = choose_quality_screened_pair(
            "2023-06-10T12:00:00Z", ledger, blocks, sensor="HLSL30.002"
        )
        self.assertIsNotNone(pair)
        self.assertEqual(pair["shared_usable_blocks"], 30)

    def test_pair_fails_with_twenty_nine_common_blocks(self):
        ledger = pd.DataFrame(
            [
                ["pre", "HLSL30.002", "2023-06-07T12:00:00Z"],
                ["post", "HLSL30.002", "2023-06-13T12:00:00Z"],
            ],
            columns=["optical_acquisition_id", "sensor", "source_time"],
        )
        blocks = {"pre": range(40), "post": range(11, 40)}
        self.assertIsNone(
            choose_quality_screened_pair(
                "2023-06-10T12:00:00Z", ledger, blocks, sensor="HLSL30.002"
            )
        )
        evaluation = evaluate_quality_screened_pair(
            "2023-06-10T12:00:00Z", ledger, blocks, sensor="HLSL30.002"
        )
        self.assertEqual(evaluation["timing_valid_pair_candidates"], 1)
        self.assertEqual(
            evaluation["failure_reason"],
            "TIMING_PAIR_FOUND_BUT_SHARED_BLOCK_FLOOR_NOT_MET",
        )

    def test_tie_breaker_applies_after_block_screen(self):
        ledger = pd.DataFrame(
            [
                ["pre_bad", "HLSL30.002", "2023-06-08T12:00:00Z"],
                ["post_bad", "HLSL30.002", "2023-06-12T12:00:00Z"],
                ["pre_good", "HLSL30.002", "2023-06-07T12:00:00Z"],
                ["post_good", "HLSL30.002", "2023-06-13T12:00:00Z"],
            ],
            columns=["optical_acquisition_id", "sensor", "source_time"],
        )
        blocks = {
            "pre_bad": range(29),
            "post_bad": range(29),
            "pre_good": range(40),
            "post_good": range(10, 40),
        }
        pair = choose_quality_screened_pair(
            "2023-06-10T12:00:00Z", ledger, blocks, sensor="HLSL30.002"
        )
        self.assertEqual(pair["pre_acquisition_id"], "pre_good")
        self.assertEqual(pair["post_acquisition_id"], "post_good")

    def test_summary_preserves_complete_56_row_grid(self):
        pair_rows = [
            {
                "city": "phoenix",
                "year": 2023,
                "season_window": "sensitivity",
                "sensor": "HLSL30.002",
                "quality_pair_available": True,
                "pre_acquisition_id": "pre",
                "post_acquisition_id": "post",
                "shared_usable_blocks": 31,
            }
        ]
        rows = required_quality_grid_rows(pair_rows)
        validate_required_grid(rows)
        self.assertEqual(len(rows), 56)
        selected = [
            row
            for row in rows
            if row["city"] == "Phoenix"
            and row["year"] == 2023
            and row["season_window"] == "sensitivity"
            and row["sensor"] == "HLSL30.002"
        ][0]
        self.assertEqual(selected["passes_with_feasible_matched_pre_post"], 1)
        self.assertEqual(selected["feasible_share"], 1.0)
        self.assertEqual(selected["minimum_shared_usable_blocks_in_selected_pairs"], 31)

    def test_runner_does_not_name_reflectance_or_lst_asset_paths(self):
        source = Path(__file__).with_name(
            "run_v6_2_d1c_fmask_reassessment.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("reflectance_urls", source)
        self.assertNotIn("lst_cog", source.lower())
        self.assertNotIn('ds["observed"]', source)


if __name__ == "__main__":
    unittest.main()
