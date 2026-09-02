from __future__ import annotations

import math
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from urban_cooling_v2.demand_geometry_audit import (
    THRESHOLDS,
    build_parsimonious_sensitivity,
    condition_index,
    continuous_vpd_support,
    saturation_vapour_pressure_kpa,
    solar_position_from_local_solar_time,
    run_audit,
    vpd_linear_diagnostics,
)


class DemandGeometryAuditTests(unittest.TestCase):
    def test_saturation_vapour_pressure_at_zero_c(self) -> None:
        value = float(saturation_vapour_pressure_kpa(np.array([0.0]))[0])
        self.assertAlmostEqual(value, 0.6108, places=4)

    def test_solar_position_is_near_overhead_at_equator_equinox_noon(self) -> None:
        zenith, azimuth = solar_position_from_local_solar_time(0.0, 80.0, 12.0)
        self.assertLess(float(zenith), 2.0)
        self.assertGreaterEqual(float(azimuth), 0.0)
        self.assertLess(float(azimuth), 360.0)

    def test_condition_index_detects_collinearity(self) -> None:
        x = np.linspace(-1.0, 1.0, 40)
        matrix = pd.DataFrame({"a": x, "b": 2.0 * x + 1e-8 * np.sin(x)})
        index, rank = condition_index(matrix)
        self.assertGreater(index, THRESHOLDS.maximum_condition_index)
        self.assertEqual(rank, 2)

    def test_vif_detects_redundant_vpd(self) -> None:
        x = np.linspace(-1.0, 1.0, 50)
        frame = pd.DataFrame({"vpd_kpa": 1.0 + 3.0 * x, "temperature": x})
        _, vif = vpd_linear_diagnostics(frame, ["temperature"])
        self.assertTrue(math.isinf(vif))

    def test_continuous_support_intersects_tertile_ranges(self) -> None:
        frame = pd.DataFrame(
            {
                "vpd_kpa": np.tile(np.linspace(1.0, 2.0, 12), 3),
                "local_solar_time_hours": np.repeat([10.0, 12.0, 14.0], 12),
                "solar_zenith_deg": np.repeat([20.0, 30.0, 40.0], 12),
                "day_of_year": np.repeat([150.0, 180.0, 210.0], 12),
            }
        )
        support = continuous_vpd_support(frame)
        self.assertGreater(support["width_kpa"], 0.5)
        self.assertLess(support["low_kpa"], support["high_kpa"])

    def test_repository_audit_uses_only_fully_recovered_azimuth(self) -> None:
        result = run_audit(Path.cwd())
        self.assertEqual(result["ruling"], "DROP")
        binding = {row["city"]: row for row in result["binding_rows"]}
        self.assertEqual(binding["phoenix"]["n_full_design_complete"], 4)
        self.assertEqual(binding["los_angeles"]["n_full_design_complete"], 1)
        self.assertFalse(any(row["all_binding_criteria_pass"] for row in binding.values()))
        self.assertFalse(result["new_v6_2_coefficients_viewed"])

    def test_parsimonious_sensitivity_preserves_near_pass_honestly(self) -> None:
        from urban_cooling_v2.demand_geometry_audit import load_analysis_passes

        result = build_parsimonious_sensitivity(load_analysis_passes(Path.cwd()))
        self.assertEqual(result["sensitivity_ruling"], "DROP")
        binding = {row["city"]: row for row in result["binding_rows"]}
        self.assertTrue(binding["phoenix"]["all_primary_criteria_pass"])
        self.assertFalse(binding["los_angeles"]["all_primary_criteria_pass"])
        self.assertEqual(
            binding["los_angeles"]["failed_primary_criteria"],
            "continuous_support_width",
        )
        self.assertFalse(result["controlling_D003_ruling_changed"])


if __name__ == "__main__":
    unittest.main()
