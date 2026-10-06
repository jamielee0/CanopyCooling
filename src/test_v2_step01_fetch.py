#!/usr/bin/env python3
"""Small network-free checks for the live Step 1 adapter."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from urban_cooling_v2.step01_fetch import (  # noqa: E402
    _domain_geometry_manifest,
    _feature_collection_rows,
    target_utc_hour_for_local_solar,
)


class Step1FetchTests(unittest.TestCase):
    def test_target_utc_hour_has_correct_longitude_sign(self) -> None:
        self.assertEqual(target_utc_hour_for_local_solar(-112.0), 21)
        self.assertEqual(target_utc_hour_for_local_solar(-80.0), 19)
        self.assertEqual(target_utc_hour_for_local_solar(0.0), 14)
        self.assertEqual(target_utc_hour_for_local_solar(150.0), 4)

    def test_feature_rows_ignore_empty_features(self) -> None:
        payload = {
            "features": [
                {"properties": {"city": "phoenix", "date": "2020-06-01", "pr": 0.0}},
                {"properties": {}},
            ]
        }
        rows = _feature_collection_rows(payload)
        self.assertEqual(rows, [{"city": "phoenix", "date": "2020-06-01", "pr": 0.0}])

    def test_domain_geometry_manifest_requires_both_geometry_hashes(self) -> None:
        features = {
            "phoenix": {
                "properties": {
                    "source_geometry_sha256": "source-hash",
                    "analysis_geometry_sha256": "analysis-hash",
                    "topology_repair_applied": True,
                }
            }
        }
        self.assertEqual(
            _domain_geometry_manifest(features),
            {
                "phoenix": {
                    "source_geometry_sha256": "source-hash",
                    "analysis_geometry_sha256": "analysis-hash",
                    "topology_repair_applied": True,
                }
            },
        )
        del features["phoenix"]["properties"]["analysis_geometry_sha256"]
        with self.assertRaisesRegex(ValueError, "provenance is incomplete"):
            _domain_geometry_manifest(features)


if __name__ == "__main__":
    unittest.main(verbosity=2)
