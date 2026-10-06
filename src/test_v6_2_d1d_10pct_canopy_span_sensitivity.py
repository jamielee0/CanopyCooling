#!/usr/bin/env python3
"""Tests for the nonbinding D021 0.10 canopy-span sensitivity."""

from __future__ import annotations

import unittest

from run_v6_2_d1d_10pct_canopy_span_sensitivity import evaluate_rows


class CanopySpanSensitivityTests(unittest.TestCase):
    def test_threshold_is_inclusive_and_counts_blocks_and_passes(self) -> None:
        rows = [
            {"pass_id": "p1", "block_id": "a", "canopy_span_fraction": 0.09},
            {"pass_id": "p2", "block_id": "a", "canopy_span_fraction": 0.10},
            {"pass_id": "p1", "block_id": "b", "canopy_span_fraction": 0.11},
            {"pass_id": "p2", "block_id": "b", "canopy_span_fraction": 0.12},
        ]
        result = evaluate_rows(rows, threshold=0.10)
        self.assertEqual(result["eligible_block_passes"], 3)
        self.assertEqual(result["unique_eligible_blocks"], 2)
        self.assertEqual(result["eligible_passes_per_eligible_block_median"], 1.5)
        self.assertEqual(result["eligible_passes_per_block_distribution"], {"1": 1, "2": 1})

    def test_threshold_must_be_probability(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_rows([], threshold=-0.01)


if __name__ == "__main__":
    unittest.main()
