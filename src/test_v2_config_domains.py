#!/usr/bin/env python3
"""Network-free tests for frozen v2 configuration and Census domains."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from urban_cooling_v2.config import load_config  # noqa: E402
from urban_cooling_v2.domains import (  # noqa: E402
    domain_records,
    fetch_census_domains,
    geometry_bbox,
    load_domain_features,
    valid_analysis_geometry,
)


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class ConfigDomainTests(unittest.TestCase):
    def test_config_has_five_unselected_holdout_and_frozen_ids(self) -> None:
        cfg = load_config()
        self.assertEqual(len(cfg.cities), 5)
        self.assertEqual(cfg.study["holdout_status"], "UNSELECTED")
        self.assertEqual(cfg.study["holdout_city"], "")
        self.assertEqual(cfg.city("phoenix").urban_area_geoid, "69184")
        self.assertEqual(cfg.ecostress["catalogue_version"], "002")
        self.assertEqual(cfg.weather["step2_hourly_primary"], "HRRR")

    def test_geometry_bbox(self) -> None:
        geometry = {
            "type": "MultiPolygon",
            "coordinates": [[[[-3, 2], [4, 2], [4, 8], [-3, 2]]]],
        }
        self.assertEqual(geometry_bbox(geometry), (-3.0, 2.0, 4.0, 8.0))

    def test_analysis_geometry_repairs_self_intersection(self) -> None:
        bowtie = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [2, 2], [0, 2], [2, 0], [0, 0]]],
        }
        repaired = valid_analysis_geometry(bowtie)
        self.assertEqual(repaired["type"], "MultiPolygon")

    def test_fetch_and_checksum_validation(self) -> None:
        cfg = load_config()
        by_id = {city.urban_area_geoid: city for city in cfg.cities}

        def fake_get(_url: str, *, params: dict, timeout: int) -> _Response:
            self.assertEqual(timeout, 120)
            geoid = params["where"].split("'")[1]
            city = by_id[geoid]
            payload = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "GEOID": geoid,
                            "UA": geoid,
                            "NAME": city.urban_area_name,
                            "AREALAND": str(round(city.area_land_km2 * 1_000_000)),
                            "AREAWATER": "0",
                            "CENTLAT": str(city.centroid_lat),
                            "CENTLON": str(city.centroid_lon),
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[
                                [city.centroid_lon - 0.1, city.centroid_lat - 0.1],
                                [city.centroid_lon + 0.1, city.centroid_lat - 0.1],
                                [city.centroid_lon + 0.1, city.centroid_lat + 0.1],
                                [city.centroid_lon - 0.1, city.centroid_lat - 0.1],
                            ]],
                        },
                    }
                ],
            }
            return _Response(payload)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "domains.geojson"
            provenance = fetch_census_domains(cfg, path, request_get=fake_get)
            self.assertEqual(len(provenance["records"]), 5)
            features = load_domain_features(path, cfg)
            self.assertEqual(set(features), set(cfg.city_slugs))
            self.assertEqual(len(domain_records(path, cfg)), 5)

            payload = json.loads(path.read_text())
            payload["features"][0]["geometry"]["coordinates"][0][0][0] += 1
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_domain_features(path, cfg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
