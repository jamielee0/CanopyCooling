#!/usr/bin/env python3
"""Network-free scope tests for the lean six-item professor submission."""

from __future__ import annotations

import unittest

from build_v6_2_professor_submission import SECTION_FILES, SECTION_READMES


class ProfessorSubmissionScopeTests(unittest.TestCase):
    def test_exact_six_requested_sections_are_defined(self):
        expected = {
            "01_protocol_and_conformance",
            "02_collection3_catalogue_audit",
            "03_corrected_stage1",
            "04_demand_geometry_ruling",
            "05_block_pass_connectivity",
            "06_raw_asset_inventory",
        }
        self.assertEqual(set(SECTION_READMES), expected)
        self.assertEqual(set(SECTION_FILES) | {"02_collection3_catalogue_audit"}, expected)

    def test_no_superseded_or_lead_lag_figure_is_selected(self):
        selected = [item for files in SECTION_FILES.values() for item in files]
        figure_sources = [source for source, target, _ in selected if "/figures/" in source]
        self.assertTrue(figure_sources)
        self.assertFalse(any("D1c_" in source or "stage1_precision" in source for source in figure_sources))
        self.assertFalse(any("SUPERSEDED" in target.upper() for _, target, _ in selected))

    def test_raw_asset_inventory_is_status_only(self):
        selected = SECTION_FILES["06_raw_asset_inventory"]
        self.assertEqual(
            [target for _, target, _ in selected],
            ["raw_asset_inventory.xlsx"],
        )
        self.assertFalse(any(target.startswith("code/") for _, target, _ in selected))
        readme = SECTION_READMES["06_raw_asset_inventory"]
        self.assertIn("which required data are in hand", readme)
        self.assertIn("NOT YET", readme)
        self.assertIn("PARTIAL", readme)
        self.assertIn("HAVE", readme)


if __name__ == "__main__":
    unittest.main()
