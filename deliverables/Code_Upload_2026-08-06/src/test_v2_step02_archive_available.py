#!/usr/bin/env python3
"""Network-free tests for the D0047 archive-available Step-2 profile."""

from __future__ import annotations

import unittest

import pandas as pd

from urban_cooling_v2.step02_archive_available import (
    ArchiveAvailableCounts,
    CANDIDATE_STATUS_COLUMN,
    EXCLUDED_STATUS,
    EXCLUSION_REASON,
    EXCLUSION_REASON_COLUMN,
    PROFILE_INCLUDED_COLUMN,
    RETAINED_STATUS,
    build_archive_available_profile,
    candidate_availability_ledger,
    exclusion_summary,
)


COUNTS = ArchiveAvailableCounts(
    original_candidates=4,
    excluded_candidates=2,
    retained_candidates=2,
    original_city_scene_links=5,
    retained_city_scene_links=2,
    original_unique_scenes=5,
    missing_unique_scenes=2,
    retained_unique_scenes=2,
)


def _screened() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "city": "alpha",
                "orbit": 1,
                "acquisition_utc": "2020-06-10T10:00:00Z",
                "metadata_candidate": True,
                "time_stratum": "10-12",
                "quality_candidate_pre_cloud": False,
            },
            {
                "city": "beta",
                "orbit": 2,
                "acquisition_utc": "2020-07-11T12:00:00Z",
                "metadata_candidate": True,
                "time_stratum": "12-14",
                "quality_candidate_pre_cloud": True,
            },
            {
                "city": "gamma",
                "orbit": 3,
                "acquisition_utc": "2024-08-12T14:00:00Z",
                "metadata_candidate": True,
                "time_stratum": "14-16",
                "quality_candidate_pre_cloud": False,
            },
            {
                "city": "delta",
                "orbit": 4,
                "acquisition_utc": "2024-09-13T16:00:00Z",
                "metadata_candidate": True,
                "time_stratum": "16-18",
                "quality_candidate_pre_cloud": True,
            },
        ]
    )


def _view(city: str, orbit: int, scene: int, stamp: str) -> dict:
    product = (
        f"ECOv002_L2T_LSTE_{orbit:05d}_{scene:03d}_13TDE_"
        f"{stamp}_0712_01"
    )
    return {
        "city": city,
        "orbit": orbit,
        "scene": scene,
        "tile": "13TDE",
        "granule_id": product,
        "asset_type": "view_zenith_cog",
        "status": "available",
        "selected_build": 712,
        "selected_revision": 1,
        "acquisition_utc": pd.to_datetime(
            stamp, format="%Y%m%dT%H%M%S", utc=True
        ),
    }


def _views() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _view("alpha", 1, 1, "20200610T095900"),
            _view("alpha", 1, 2, "20200610T100000"),
            _view("beta", 2, 3, "20200711T120000"),
            _view("gamma", 3, 4, "20240812T140000"),
            _view("delta", 4, 5, "20240913T160000"),
        ]
    )


def _missing() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "orbit": 1,
                "scene": 2,
                "geo_granule_id": "ECOv002_L1B_GEO_00001_002_missing",
                "cmr_response_sha256": "a" * 64,
                "identity_resolution_status": "unresolved_missing",
                "geometry_values_opened": False,
            },
            {
                "orbit": 3,
                "scene": 4,
                "geo_granule_id": "ECOv002_L1B_GEO_00003_004_missing",
                "cmr_response_sha256": "b" * 64,
                "identity_resolution_status": "unresolved_missing",
                "geometry_values_opened": False,
            },
        ]
    )


class ArchiveAvailableProfileTests(unittest.TestCase):
    def test_whole_candidate_exclusion_preserves_complete_ledger(self) -> None:
        profile, retained_links, validation = build_archive_available_profile(
            _screened(), _views(), _missing(), counts=COUNTS
        )
        self.assertEqual(len(profile), 4)
        self.assertEqual(len(retained_links), 2)
        statuses = dict(zip(profile["city"], profile[CANDIDATE_STATUS_COLUMN]))
        self.assertEqual(statuses["alpha"], EXCLUDED_STATUS)
        self.assertEqual(statuses["gamma"], EXCLUDED_STATUS)
        self.assertEqual(statuses["beta"], RETAINED_STATUS)
        self.assertEqual(statuses["delta"], RETAINED_STATUS)
        self.assertEqual(set(retained_links["city"]), {"beta", "delta"})
        self.assertNotIn((1, 1), set(map(tuple, retained_links[["orbit", "scene"]].to_records(index=False))))
        self.assertTrue(
            profile.loc[
                profile[CANDIDATE_STATUS_COLUMN].eq(EXCLUDED_STATUS),
                EXCLUSION_REASON_COLUMN,
            ].eq(EXCLUSION_REASON).all()
        )
        self.assertTrue(validation["candidate_ledger_complete"])
        self.assertEqual(validation["original_metadata_candidate_count"], 4)
        self.assertEqual(validation["excluded_pre_geometry_candidate_count"], 2)
        self.assertEqual(validation["retained_geometry_candidate_count"], 2)
        self.assertFalse(validation["geometry_values_opened"])
        self.assertFalse(validation["lst_opened"])
        self.assertFalse(validation["record_2026_opened"])

    def test_compact_ledger_is_row_complete_and_summary_is_balanced(self) -> None:
        profile, _, _ = build_archive_available_profile(
            _screened(), _views(), _missing(), counts=COUNTS
        )
        ledger = candidate_availability_ledger(profile)
        summary = exclusion_summary(profile)
        self.assertEqual(len(ledger), 4)
        self.assertEqual(int(summary["original_candidate_count"].sum()), 4)
        self.assertEqual(
            int(summary["excluded_pre_geometry_candidate_count"].sum()), 2
        )
        self.assertEqual(int(summary["retained_geometry_candidate_count"].sum()), 2)
        self.assertEqual(
            int(profile[PROFILE_INCLUDED_COLUMN].sum()),
            int(summary["retained_geometry_candidate_count"].sum()),
        )

    def test_count_drift_fails_before_geometry(self) -> None:
        wrong = ArchiveAvailableCounts(
            original_candidates=4,
            excluded_candidates=1,
            retained_candidates=3,
            original_city_scene_links=5,
            retained_city_scene_links=3,
            original_unique_scenes=5,
            missing_unique_scenes=2,
            retained_unique_scenes=3,
        )
        with self.assertRaisesRegex(ValueError, "count seal mismatch"):
            build_archive_available_profile(
                _screened(), _views(), _missing(), counts=wrong
            )

    def test_opened_geometry_evidence_is_rejected(self) -> None:
        missing = _missing()
        missing.loc[0, "geometry_values_opened"] = True
        with self.assertRaisesRegex(ValueError, "geometry values were opened"):
            build_archive_available_profile(
                _screened(), _views(), missing, counts=COUNTS
            )

    def test_2026_candidate_is_rejected(self) -> None:
        screened = _screened()
        screened.loc[0, "acquisition_utc"] = "2026-06-10T10:00:00Z"
        with self.assertRaisesRegex(ValueError, "frozen 2018-2025"):
            build_archive_available_profile(
                screened, _views(), _missing(), counts=COUNTS
            )


if __name__ == "__main__":
    unittest.main()
