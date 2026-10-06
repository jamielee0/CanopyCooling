#!/usr/bin/env python3
"""Network-free known-answer tests for the independent v6.2 foundation audit."""

from __future__ import annotations

import datetime as dt
import ast
import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from urban_cooling_v2.independent_foundation_audit import (
    CMR_EVIDENCE_RELATIVE,
    FAILED_STATUS,
    READY_STATUS,
    evaluate_readiness,
    exit_code_for_manifest,
    local_solar_hour,
    main,
    parse_granule_id,
    select_strict_latest,
    vpd_kpa,
)


class IndependentFoundationAuditTests(unittest.TestCase):
    def test_evidence_location_is_explicit(self) -> None:
        self.assertEqual(
            CMR_EVIDENCE_RELATIVE,
            Path("docs/v2/v6_2/foundation_audit/source_evidence/cmr_collection3"),
        )

    @staticmethod
    def _passing_sections() -> tuple[dict, dict, dict, dict]:
        historical = {
            "count_rows": [
                {
                    "stage": "known_count",
                    "independent_observed_count": 1,
                    "expected_historical_count": 1,
                    "result": "PASS",
                }
            ]
        }
        archive_rows = [
            {
                "geometry_outcome_known": False,
                "cloud_weight_known": False,
                "collection3_live_recovery_status": "NOT_RECOVERED_NO_COLLECTION3_ORBIT_MATCH",
            }
            for _ in range(43)
        ]
        archive = {
            "historical_count": 31,
            "unified_count": 43,
            "bound_scope_count": 28,
            "collection3_potential_orbit_matches": 0,
            "rows": archive_rows,
        }
        geometry = {
            "summary": [
                {"check": "geometry_check", "observed": 1, "expected": 1, "result": "PASS"}
            ]
        }
        hrrr = {
            "summary": [
                {"check": "hrrr_check", "observed": 1, "expected": 1, "result": "PASS"}
            ]
        }
        return historical, archive, geometry, hrrr

    def test_readiness_is_calculated_from_all_required_sections(self) -> None:
        readiness = evaluate_readiness(*self._passing_sections())
        self.assertEqual(readiness["status"], READY_STATUS)
        self.assertEqual(readiness["required_checks_failed"], 0)
        self.assertEqual(
            {row["section"] for row in readiness["required_checks"]},
            {"historical", "archive", "geometry", "hrrr"},
        )

    def test_any_required_section_failure_is_fail_closed(self) -> None:
        mutations = {
            "historical": lambda sections: sections[0]["count_rows"][0].update(
                independent_observed_count=0
            ),
            "archive": lambda sections: sections[1].update(historical_count=30),
            "geometry": lambda sections: sections[2]["summary"][0].update(observed=0),
            "hrrr": lambda sections: sections[3]["summary"][0].update(observed=0),
        }
        for section, mutate in mutations.items():
            with self.subTest(section=section):
                sections = self._passing_sections()
                mutate(sections)
                readiness = evaluate_readiness(*sections)
                manifest = {"status": readiness["status"], "readiness": readiness}
                self.assertEqual(readiness["status"], FAILED_STATUS)
                self.assertGreater(readiness["required_checks_failed"], 0)
                self.assertEqual(exit_code_for_manifest(manifest), 1)

    def test_main_returns_nonzero_for_failed_manifest(self) -> None:
        failed_manifest = {
            "status": FAILED_STATUS,
            "readiness": {
                "required_checks_total": 1,
                "required_checks_passed": 0,
                "required_checks_failed": 1,
                "failed_check_ids": ["geometry.injected_failure"],
            },
            "results": {},
        }
        with patch(
            "urban_cooling_v2.independent_foundation_audit.run",
            return_value=failed_manifest,
        ), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--repo-root", "."]), 1)

    def test_script_imports_no_project_module(self) -> None:
        path = Path(__file__).with_name("urban_cooling_v2") / "independent_foundation_audit.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertFalse(
            imported_roots & {"urban_cooling_v2", "config", "run_v2_hitl_gate1"}
        )

    def test_native_id_fields_are_explicit(self) -> None:
        parsed = parse_granule_id(
            "ECOv002_L2T_LSTE_29106_004_15TVK_20230824T161518_0712_02"
        )
        self.assertEqual(parsed["orbit"], 29106)
        self.assertEqual(parsed["scene"], 4)
        self.assertEqual(parsed["tile"], "15TVK")
        self.assertEqual(parsed["build"], 712)
        self.assertEqual(parsed["revision"], 2)

    def test_strict_latest_revision_is_per_physical_tile_identity(self) -> None:
        rows = [
            {"city": "x", "granule_id": "ECOv002_L2T_LSTE_00001_001_12SAA_20200101T000000_0710_01"},
            {"city": "x", "granule_id": "ECOv002_L2T_LSTE_00001_001_12SAA_20200101T000000_0712_02"},
            {"city": "x", "granule_id": "ECOv002_L2T_LSTE_00001_002_12SAA_20200101T000100_0710_01"},
        ]
        selected = select_strict_latest(rows)
        self.assertEqual(len(selected), 2)
        self.assertIn(rows[1]["granule_id"], selected)
        self.assertIn(rows[2]["granule_id"], selected)

    def test_local_solar_time_known_answer(self) -> None:
        timestamp = dt.datetime(2018, 7, 28, 22, 37, 48, 435000, tzinfo=dt.timezone.utc)
        self.assertAlmostEqual(local_solar_hour(timestamp, -84.3365018), 16.8977783104593, places=12)

    def test_vpd_known_answer(self) -> None:
        self.assertAlmostEqual(
            vpd_kpa(294.5308532714844, 291.4732360839844),
            0.43947115864110886,
            places=14,
        )


if __name__ == "__main__":
    unittest.main()
