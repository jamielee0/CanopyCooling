import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from v6_2_advance.advisor_step1_inputs import (
    OTHER_YEAR_ORBITS, check_holdout_blanks, exact_geo_flag,
    interpolate_shortwave, read_other_year_metadata, scene_summary, sun_at,
)


class AdvisorStep1Tests(unittest.TestCase):
    def test_known_ratio_interpolation_is_not_raw_flux_interpolation(self):
        r = interpolate_shortwave(300, 640, .5, .8, .7, .5)
        self.assertAlmostEqual(r["shortwave_W_m2"], 490)
        self.assertAlmostEqual(r["shortwave_floor_normalized"], 600)
        self.assertAlmostEqual(r["shortwave_ceiling_normalized"], 800)
        self.assertNotAlmostEqual(r["shortwave_W_m2"], (300+640)/2)

    def test_constant_transmission_recovers_hourly_and_subhourly_radiation(self):
        for w, c in [(0, .8), (.25, .73), (1, .4)]:
            r = interpolate_shortwave(800, 400, .8, .4, c, w)
            self.assertAlmostEqual(r["shortwave_W_m2"], 1000*c)

    def test_one_low_sun_bracket_uses_only_other_ratio(self):
        a = interpolate_shortwave(900, 400, .05, .5, .3, .4)
        b = interpolate_shortwave(400, 900, .5, .05, .3, .6)
        self.assertEqual(a["shortwave_W_m2"], 240)
        self.assertEqual(b["shortwave_W_m2"], 240)
        self.assertIsNone(a["shortwave_floor_normalized"])
        self.assertIsNone(b["shortwave_ceiling_normalized"])

    def test_low_sun_boundary_and_both_low_fail(self):
        self.assertEqual(interpolate_shortwave(100, 100, .1, .1, .1, .5)["shortwave_W_m2"], 100)
        with self.assertRaisesRegex(ValueError, "clarification"):
            interpolate_shortwave(1, 2, .09, .09, .1, .5)

    def test_no_missing_negative_or_below_horizon_filling(self):
        for args in [(np.nan, 10, .5, .5, .5, .5), (-1, 10, .5, .5, .5, .5),
                     (10, 10, .5, .5, -.1, .5), (10, 10, .5, .5, .5, 1.1)]:
            with self.assertRaises(ValueError):
                interpolate_shortwave(*args)

    def test_solar_clock_and_elevation_independent_equation(self):
        r = sun_at("2024-06-02T18:27:10.257Z", 33.45, -112.07)
        self.assertEqual(r["days_in_year"], 366)
        self.assertAlmostEqual(r["sin_solar_elevation"], np.sin(np.deg2rad(r["solar_elevation_deg"])), places=14)
        # The same absolute instant must survive timezone conversion.
        q = sun_at("2024-06-02T11:27:10.257-07:00", 33.45, -112.07)
        self.assertEqual(q, r)
        self.assertEqual(sun_at("2023-06-02T18:27:10Z", 33.45, -112.07)["days_in_year"], 365)

    def test_solar_time_orders_even_at_utc_midnight(self):
        a = sun_at("2019-08-15T00:00:00Z", 33.45, -112.07)
        b = sun_at("2019-08-15T01:00:00Z", 33.45, -112.07)
        self.assertTrue(16 < a["apparent_solar_hour"] < 17)
        self.assertTrue(17 < b["apparent_solar_hour"] < 18)
        self.assertGreater(a["sin_solar_elevation"], b["sin_solar_elevation"])

    def xml(self, raw="Best", name="GEO_001", group="L1GEOMetadata"):
        return (f'<Dataset xmlns="http://xml.opendap.org/ns/DAP/4.0#" xmlns:d="http://xml.opendap.org/dap/dmrpp/1.0.0#" name="{name}.h5">'
                f'<Group name="{group}"><String name="GeolocationAccuracyQA"><d:compact>{base64.b64encode(raw.encode()).decode()}</d:compact>'
                '</String></Group></Dataset>').encode()

    def test_exact_geo_categories_and_granule_binding(self):
        for name in ["Best", "Good", "Suspect", "Poor"]:
            self.assertEqual(exact_geo_flag(self.xml(name), "GEO_001"), (name, name.lower()))
        for data in [self.xml(name="wrong"), self.xml(group="wrong"), self.xml(raw="Best/Good")]:
            with self.assertRaises(ValueError):
                exact_geo_flag(data, "GEO_001")

    def test_scene_summary_retains_each_scene_and_exposes_mixed_quality(self):
        r = scene_summary([{"scene_key": "001_001", "category": "best"}, {"scene_key": "001_002", "category": "suspect"}])
        self.assertEqual(r["geolocation_worst_category"], "suspect")
        self.assertFalse(r["all_scene_categories_census_usable"])
        self.assertEqual(r["geo_best_scene_count"], 1)
        self.assertEqual(r["geo_suspect_scene_count"], 1)
        with self.assertRaises(ValueError):
            scene_summary([{"scene_key": "001_001", "category": "best"}]*2)

    def test_other_year_reader_blocks_effect_columns_before_io(self):
        with patch("v6_2_advance.advisor_step1_inputs.pd.read_csv") as reader:
            with self.assertRaises(ValueError):
                read_other_year_metadata("unused.csv", ["orbit", "cooling_K_per_10pp"])
            reader.assert_not_called()

    def test_holdout_effects_cannot_enter_output(self):
        rows = [{"city": "phoenix", "orbit": o, "cooling_K_per_10pp": ""} for o in OTHER_YEAR_ORBITS]
        self.assertTrue(check_holdout_blanks(rows))
        rows[0]["cooling_K_per_10pp"] = 0
        with self.assertRaises(ValueError):
            check_holdout_blanks(rows)


if __name__ == "__main__":
    unittest.main()
