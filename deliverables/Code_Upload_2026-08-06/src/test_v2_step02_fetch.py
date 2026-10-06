#!/usr/bin/env python3
"""Network-free tests for exact-domain catalogue filtering."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from urban_cooling_v2.step02_fetch import footprint_intersects_domain  # noqa: E402


class Step2FetchTests(unittest.TestCase):
    def test_rectangle_intersection_uses_domain_not_only_bbox(self) -> None:
        domain = {
            "type": "Polygon",
            "coordinates": [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
        }
        intersects = {
            "BoundingRectangles": [
                {
                    "WestBoundingCoordinate": 0.5,
                    "SouthBoundingCoordinate": 0.5,
                    "EastBoundingCoordinate": 2.0,
                    "NorthBoundingCoordinate": 2.0,
                }
            ]
        }
        outside = {
            "BoundingRectangles": [
                {
                    "WestBoundingCoordinate": 2.0,
                    "SouthBoundingCoordinate": 2.0,
                    "EastBoundingCoordinate": 3.0,
                    "NorthBoundingCoordinate": 3.0,
                }
            ]
        }
        self.assertTrue(footprint_intersects_domain(json.dumps(intersects), domain))
        self.assertFalse(footprint_intersects_domain(json.dumps(outside), domain))
        self.assertFalse(footprint_intersects_domain(None, domain))


if __name__ == "__main__":
    unittest.main(verbosity=2)

