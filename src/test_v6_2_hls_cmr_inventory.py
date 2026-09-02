#!/usr/bin/env python3
"""Network-free tests for the v6.2 HLS CMR inventory helpers."""

from __future__ import annotations

import unittest

from urban_cooling_v2.hls_cmr_inventory import (
    exact_reuse_share,
    parse_cmr_item,
    selected_asset_plan,
)


class HlsCmrInventoryTests(unittest.TestCase):
    def item(self):
        granule = "HLS.S30.T12SVC.2023152T180919.v2.0"
        base = "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLSS30.020"
        return {
            "meta": {
                "concept-id": "G1-LPCLOUD",
                "collection-concept-id": "C2021957295-LPCLOUD",
                "native-id": granule,
            },
            "umm": {
                "GranuleUR": granule,
                "TemporalExtent": {
                    "RangeDateTime": {
                        "BeginningDateTime": "2023-06-01T18:24:50Z",
                        "EndingDateTime": "2023-06-01T18:24:57Z",
                    }
                },
                "SpatialExtent": {
                    "HorizontalSpatialDomain": {
                        "Geometry": {
                            "GPolygons": [
                                {
                                    "Boundary": {
                                        "Points": [
                                            {"Longitude": -112.2, "Latitude": 33.1},
                                            {"Longitude": -111.4, "Latitude": 33.1},
                                            {"Longitude": -111.4, "Latitude": 34.0},
                                            {"Longitude": -112.2, "Latitude": 34.0},
                                            {"Longitude": -112.2, "Latitude": 33.1},
                                        ]
                                    }
                                }
                            ]
                        }
                    }
                },
                "AdditionalAttributes": [
                    {"Name": "MGRS_TILE_ID", "Values": ["12SVC"]},
                    {"Name": "CLOUD_COVERAGE", "Values": ["5"]},
                ],
                "RelatedUrls": [
                    {
                        "URL": f"{base}/{granule}/{granule}.Fmask.tif",
                        "Type": "GET DATA",
                    },
                    {"URL": f"{base}/{granule}/{granule}.B04.tif", "Type": "GET DATA"},
                    {"URL": f"{base}/{granule}/{granule}.B8A.tif", "Type": "GET DATA"},
                    {"URL": f"{base}/{granule}/{granule}.B11.tif", "Type": "GET DATA"},
                ],
            },
        }

    def test_parse_cmr_item_preserves_source_identity_and_assets(self):
        city = {
            "type": "Polygon",
            "coordinates": [[[-112, 33.2], [-111.5, 33.2], [-111.5, 33.8], [-112, 33.8], [-112, 33.2]]],
        }
        row = parse_cmr_item(self.item(), sensor="HLSS30.002", city="phoenix", city_geometry=city)
        self.assertTrue(row["domain_geometry_intersects"])
        self.assertEqual(row["mgrs_tile"], "12SVC")
        self.assertEqual(row["cloud_coverage_percent"], 5.0)
        self.assertEqual(set(row["assets"]), {"B04", "B8A", "B11", "Fmask"})

    def test_download_plan_requires_fmask_and_sensor_specific_bands(self):
        city = {
            "type": "Polygon",
            "coordinates": [[[-112, 33.2], [-111.5, 33.2], [-111.5, 33.8], [-112, 33.8], [-112, 33.2]]],
        }
        acquisition = parse_cmr_item(
            self.item(), sensor="HLSS30.002", city="phoenix", city_geometry=city
        )
        pair = {
            "catalogue_pair_available": True,
            "pre_acquisition_id": acquisition["optical_acquisition_id"],
            "post_acquisition_id": acquisition["optical_acquisition_id"],
        }
        plan = selected_asset_plan([pair], [acquisition])
        self.assertEqual(len(plan), 1)
        self.assertTrue(plan[0]["all_required_urls_present"])
        self.assertEqual(set(plan[0]["reflectance_urls"]), {"B04", "B8A", "B11"})

    def test_reuse_share_has_no_small_n_exception(self):
        rows = [
            {
                "catalogue_pair_available": True,
                "pre_acquisition_id": "pre",
                "post_acquisition_id": "post",
            }
            for _ in range(3)
        ]
        self.assertEqual(exact_reuse_share(rows), 1.0)


if __name__ == "__main__":
    unittest.main()
