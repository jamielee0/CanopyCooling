#!/usr/bin/env python3

from __future__ import annotations

import unittest

import numpy as np

from urban_cooling_v2.science_tcc_screen import (
    canopy_span,
    cooling_effect_from_slope,
    merge_nonthermal_scene_masks,
    stable_median_fraction,
)


class ScienceTccScreenTests(unittest.TestCase):
    def test_stable_median_and_15pp_range(self) -> None:
        stack = np.array(
            [
                [[10, 10, 65535], [20, 50, 0]],
                [[11, 12, 65535], [21, 55, 1]],
                [[12, 14, 65535], [22, 60, 2]],
                [[13, 16, 65535], [23, 65, 3]],
                [[14, 18, 65535], [24, 70, 4]],
                [[15, 20, 65535], [25, 72, 5]],
                [[16, 25, 65535], [26, 75, 6]],
            ],
            dtype=float,
        )
        stack[stack == 65535] = np.nan
        median, stable = stable_median_fraction(stack)
        self.assertTrue(stable[0, 0])
        self.assertTrue(stable[0, 1])  # exactly 15 percentage points is retained
        self.assertFalse(stable[0, 2])
        self.assertFalse(stable[1, 1])
        self.assertAlmostEqual(float(median[0, 0]), 0.13)
        self.assertAlmostEqual(float(median[0, 1]), 0.16)

    def test_nonthermal_cloudy_wins(self) -> None:
        first = {
            "QC": np.ma.array([[0, 0], [0, 0]]),
            "cloud": np.ma.array([[0, 0], [0, 0]]),
            "water": np.ma.array([[0, 0], [0, 0]]),
            "height": np.ma.array([[1.0, 1.0], [1.0, 1.0]]),
        }
        second = {
            "QC": np.ma.array([[0, 2], [0, 0]]),
            "cloud": np.ma.array([[1, 0], [0, 0]]),
            "water": np.ma.array([[0, 0], [0, 1]]),
            "height": np.ma.array([[1.0, 1.0], [1.0, 1.0]]),
        }
        self.assertEqual(
            merge_nonthermal_scene_masks([first, second]).tolist(),
            [[False, True], [True, False]],
        )

    def test_canopy_span(self) -> None:
        p10, p90, span = canopy_span(np.linspace(0.0, 1.0, 101))
        self.assertAlmostEqual(p10, 0.10)
        self.assertAlmostEqual(p90, 0.90)
        self.assertAlmostEqual(span, 0.80)

    def test_known_case_ce_unit_conversion(self) -> None:
        # A -2 K/fraction slope means losing 0.10 canopy fraction warms by 0.20 K.
        self.assertAlmostEqual(cooling_effect_from_slope(-2.0), 0.20)
        self.assertAlmostEqual(cooling_effect_from_slope(1.5), -0.15)


if __name__ == "__main__":
    unittest.main()
