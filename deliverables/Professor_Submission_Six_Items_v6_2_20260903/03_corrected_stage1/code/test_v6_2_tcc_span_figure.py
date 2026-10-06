#!/usr/bin/env python3
"""Network-free tests for the official-TCC presentation figure inputs."""

from __future__ import annotations

import unittest

from build_v6_2_tcc_span_figure import validate_manifest


class TccSpanFigureTests(unittest.TestCase):
    def test_manifest_count_threshold_and_maximum_reproduce(self):
        manifest = {
            "candidate_block_passes": 3,
            "eligible_block_passes": 1,
            "canopy_span_fraction": {"frozen_floor": 0.2, "maximum": 0.21},
            "rows": [
                {"pass_id": "phoenix:1", "canopy_span_fraction": 0.05},
                {"pass_id": "phoenix:1", "canopy_span_fraction": 0.10},
                {"pass_id": "phoenix:2", "canopy_span_fraction": 0.21},
            ],
        }
        spans, passes, threshold = validate_manifest(manifest)
        self.assertEqual(len(spans), 3)
        self.assertEqual(passes[-1], "phoenix:2")
        self.assertEqual(threshold, 0.2)

    def test_inconsistent_eligible_count_fails_closed(self):
        manifest = {
            "candidate_block_passes": 1,
            "eligible_block_passes": 0,
            "canopy_span_fraction": {"frozen_floor": 0.2, "maximum": 0.21},
            "rows": [{"pass_id": "phoenix:1", "canopy_span_fraction": 0.21}],
        }
        with self.assertRaises(ValueError):
            validate_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
