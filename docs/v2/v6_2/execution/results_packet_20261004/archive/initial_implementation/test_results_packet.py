"""Network-free known-answer and boundary checks for released-result assembly."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from v6_2_advance.results_packet import (
    FrozenReader, SEALED_FIELDS, check_output_scope, footprint_area_km2, keyed,
    number, reconcile_estimate, sha256, solar_times, support_quantiles, timestamp,
    validate_weather,
)


class ResultsPacketTests(unittest.TestCase):
    def test_temperature_sign_units_and_existing_interval(self):
        r = dict(gradient_K_per_10pp="-2", cooling_K_per_10pp="2", SE_8km_K_per_10pp="0.3",
                 cooling_q025_8km="1.4", cooling_q975_8km="2.6", n_cells="7", n_blocks="2")
        p = dict(LST_K_SE_per_10pp="0.3", LST_K_bootstrap_width_95_per_10pp="1.2",
                 bootstrap_requested="100", bootstrap_estimable="97", bootstrap_failed="3", n_cells="7", n_blocks="2")
        self.assertEqual(reconcile_estimate(r, p, 8), (-2, 2, .3, 1.4, 2.6))
        r["cooling_K_per_10pp"] = "-2"
        with self.assertRaisesRegex(ValueError, "Signed"): reconcile_estimate(r, p, 8)

    def test_bootstrap_accounting_and_interval_mismatch_rejected(self):
        r = dict(gradient_K_per_10pp="-1", cooling_K_per_10pp="1", SE_2km_K_per_10pp="0.2",
                 cooling_q025_2km="0.5", cooling_q975_2km="1.5", n_cells="7", n_blocks="2")
        p = dict(LST_K_SE_per_10pp="0.2", LST_K_bootstrap_width_95_per_10pp="1",
                 bootstrap_requested="100", bootstrap_estimable="97", bootstrap_failed="2", n_cells="7", n_blocks="2")
        with self.assertRaisesRegex(ValueError, "accounting"): reconcile_estimate(r, p, 2)
        p["bootstrap_failed"] = "3"
        r["cooling_q975_2km"] = "1.6"
        with self.assertRaisesRegex(ValueError, "width"): reconcile_estimate(r, p, 2)

    def test_composite_identity_not_orbit_only(self):
        rows = [dict(city=c, orbit="7", run="r", variant="v") for c in ("phoenix", "atlanta")]
        self.assertEqual(len(keyed(rows, ("city", "orbit", "run", "variant"))), 2)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            keyed(rows + [dict(rows[0])], ("city", "orbit", "run", "variant"))

    def test_solar_clock_known_jan1_noon_and_longitude_shift(self):
        # On Jan 1 at noon gamma=0: EOT=229.18*(.000075+.001868-.014615).
        t = datetime(2023, 1, 1, 12, tzinfo=timezone.utc)
        mean, apparent, eot = solar_times(t, 0)
        self.assertEqual(mean, 12)
        self.assertAlmostEqual(eot, -2.90416896, places=10)
        self.assertAlmostEqual(apparent, 11.951597184, places=10)
        self.assertAlmostEqual(solar_times(t, 15)[1] - apparent, 1, places=12)

    def test_solar_rollover_subseconds_and_utc_conversion(self):
        t = timestamp("2023-01-01T19:00:00.500-05:00")
        mean, apparent, _ = solar_times(t, -15)
        self.assertAlmostEqual(mean, 23 + .5 / 3600)
        self.assertTrue(0 <= apparent < 24)
        with self.assertRaises(ValueError): solar_times(datetime(2023, 1, 1), 0)
        with self.assertRaises(ValueError): timestamp("2023-01-01T12:00:00")

    def test_native_area_uses_unique_cells_not_scene_count(self):
        base = dict(city="phoenix", scenes="20", unique_QA_valid_before_context="9",
                    native_area_m2="4900", ownership="whole_footprint_inside_canonical_core_and_UTM_band")
        audit = [dict(base, tile="A", paired_complete_primary="3"), dict(base, tile="B", paired_complete_primary="4")]
        self.assertEqual(footprint_area_km2(audit, 7), .0343)
        with self.assertRaisesRegex(ValueError, "Duplicate"): footprint_area_km2(audit + [audit[0]], 10)
        with self.assertRaisesRegex(ValueError, "count"): footprint_area_km2(audit, 8)

    def test_ownership_and_product_area_must_be_verified(self):
        r = dict(city="phoenix", tile="A", unique_QA_valid_before_context="9", paired_complete_primary="3",
                 native_area_m2="4900", ownership="bbox_only")
        with self.assertRaisesRegex(ValueError, "ownership"): footprint_area_km2([r], 3)
        r["ownership"] = "whole_footprint_inside_canonical_core_and_UTM_band"
        r["native_area_m2"] = "10000"
        with self.assertRaisesRegex(ValueError, "70 m"): footprint_area_km2([r], 3)

    def test_support_is_distribution_not_cutoff(self):
        s = dict(n_cells=7, n_blocks=2, quantiles={"0": 0, "0.5": .001, "1": 1})
        self.assertEqual(support_quantiles(s, dict(n_cells="7", n_blocks="2"))["0.5"], .001)
        s["quantiles"]["1"] = -1
        with self.assertRaisesRegex(ValueError, "invalid"): support_quantiles(s, dict(n_cells="7", n_blocks="2"))

    def test_weather_known_half_hour_interpolation(self):
        r = dict(city="phoenix", acquisition_utc="2023-06-01T12:30:00+00:00")
        hourly = {("phoenix", f"2023-06-01T{h}:00:00+00:00"): dict(t2m_k=t, vpd_kpa=v)
                  for h, t, v in (("12", 300, 2), ("13", 304, 4))}
        w = dict(acquisition_utc=r["acquisition_utc"], hrrr_t2m_K=302, hrrr_vpd_kPa=3,
                 weather_status="LINEAR_INTERPOLATION_OF_EXISTING_HOURLY_DOMAIN_MEANS")
        self.assertEqual(validate_weather(r, w, hourly), (302, 3, "2023-06-01T12:00:00+00:00", "2023-06-01T13:00:00+00:00"))

    def test_missing_weather_not_zero_or_inherited_fallback(self):
        r = dict(city="phoenix", acquisition_utc="2023-06-01T12:30:00+00:00")
        w = dict(acquisition_utc=r["acquisition_utc"], hrrr_t2m_K="", hrrr_vpd_kPa="",
                 weather_status="MISSING_BRACKETING_HOURLY_RECORDS")
        self.assertEqual(validate_weather(r, w, {}), (None, None, None, None))
        w["hrrr_t2m_K"] = 0
        with self.assertRaisesRegex(ValueError, "silently filled"): validate_weather(r, w, {})
        self.assertIsNone(number("", required=False))
        self.assertEqual(number("0", required=False), 0)
        with self.assertRaises(ValueError): number("inf", required=False)

    def scope_rows(self):
        rows, identities = [], set()
        for size in (1, 2, 4, 8):
            for i in range(16):
                city = "phoenix" if i < 11 else "atlanta"
                identities.add((city, str(i), "r", "paired_primary"))
                rows.append(dict(city=city, orbit=str(i), source_run_id="r", source_model_variant="paired_primary",
                    variant="original" if size == 1 else f"spatial_uncertainty_{size}km", resampling_group_km=size,
                    acquisition_utc="2023-06-01T12:00:00+00:00", paired_effect_status="SEALED_NOT_RELEASED",
                    **{k: None for k in SEALED_FIELDS}, cooling_K_per_10pp=1, n_cells=7,
                    footprint_area_km2=.0343, apparent_solar_hour=12))
        return rows, identities

    def test_16_originals_and_48_sensitivities_are_not_new_observations(self):
        rows, identities = self.scope_rows()
        check_output_scope(rows, identities)
        rows[16]["n_cells"] = 8
        with self.assertRaisesRegex(ValueError, "changed estimate/support"): check_output_scope(rows, identities)

    def test_sealed_effect_and_other_year_cannot_escape(self):
        rows, identities = self.scope_rows()
        rows[0][SEALED_FIELDS[0]] = -.2
        with self.assertRaisesRegex(ValueError, "Unreleased"): check_output_scope(rows, identities)
        rows[0][SEALED_FIELDS[0]] = None
        rows[0]["acquisition_utc"] = "2024-06-01T12:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "outside-scope"): check_output_scope(rows, identities)

    def test_public_reader_enforces_hash_and_sealed_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root/"data").mkdir()
            source = root/"public.json"
            source.write_text('{"known":7}')
            freeze = dict(data_link_target=str(root/"data"), inputs=[dict(path="public.json", sha256=sha256(source))])
            reader = FrozenReader(root, freeze)
            self.assertEqual(reader.read("public.json", "json"), {"known": 7})
            with self.assertRaisesRegex(ValueError, "allowlist"): reader.read("outputs/sealed_coefficients/a.npz", "json")
            source.write_text('{"known":8}')
            with self.assertRaisesRegex(ValueError, "changed"): reader.read("public.json", "json")


if __name__ == "__main__": unittest.main()
