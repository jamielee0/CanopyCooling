"""Network-free tests for the distinct D0056/D0057 Task-2A guardrail."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pandas as pd

from urban_cooling_v2.task2_time_of_day_guardrails import (
    DEFAULT_CONFIG,
    EXPECTED_DEVELOPMENT_CITIES,
    EXPECTED_GATE,
    EXPECTED_HOLDOUT,
    EXPECTED_PROFILE,
    EXPECTED_PROFILE_GATE,
    EXPECTED_SCOPE,
    _holdout_ranking,
    _product_and_storage_tables,
    imported_cmr_requester,
    load_config,
    run_public_cmr_census,
    run_preflight,
    sha256_file,
)


class TimeOfDayTask2AGuardrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(DEFAULT_CONFIG)

    def test_quality_only_rule_selects_minneapolis_without_outcomes(self) -> None:
        rows = []
        city_values = {
            "atlanta": (6, 4.0, 25),
            "los_angeles": (8, 6.0, 27),
            "miami": (2, 1.0, 15),
            "minneapolis_st_paul": (12, 8.0, 32),
        }
        for city, (minimum_n, minimum_expected, positive_cells) in city_values.items():
            cell = 0
            for year in range(2018, 2026):
                for stratum in ("10-12", "12-14", "14-16", "16-18"):
                    cell += 1
                    positive = cell <= positive_cells
                    rows.append(
                        {
                            "city": city,
                            "year": year,
                            "time_stratum": stratum,
                            "n_usable_passes": minimum_n if positive else 0,
                            "expected_usable_pass_equivalents": (
                                minimum_expected if positive else 0.0
                            ),
                            "count_scope": "detail",
                        }
                    )
        ranking = _holdout_ranking(self.config, pd.DataFrame(rows))
        self.assertEqual(ranking.iloc[0]["city"], EXPECTED_HOLDOUT)
        self.assertTrue(bool(ranking.iloc[0]["eligible"]))
        self.assertFalse(bool(ranking["thermal_outcome_used"].any()))
        self.assertFalse(bool(ranking.loc[ranking.city.eq("miami"), "eligible"].iloc[0]))

    def test_storage_bound_covers_largest_metadata_only_family(self) -> None:
        facts = {
            "development_pass_tile_associations": 719,
            "maximum_city_year_pass_tile_associations": 57,
        }
        products, storage, summary = _product_and_storage_tables(self.config, facts)
        self.assertEqual(set(products["collection_version"]), {"002"})
        self.assertFalse(bool(products["thermal_value_opened"].any()))
        self.assertEqual(summary["largest_batch_family"], "HLS_PREPASS")
        self.assertGreaterEqual(
            summary["configured_projected_peak_bytes"], summary["calculated_peak_floor_bytes"]
        )
        self.assertTrue((storage["source_values_opened"] == False).all())  # noqa: E712

    def _temporary_preflight_repo(self, gate_overrides: dict | None = None) -> tuple[Path, Path]:
        temp_root = Path(tempfile.mkdtemp(prefix="v2-tod-preflight-"))
        self.addCleanup(shutil.rmtree, temp_root)
        config_path = temp_root / "configs" / "v2_task2_time_of_day.toml"
        config_path.parent.mkdir(parents=True)
        shutil.copyfile(DEFAULT_CONFIG, config_path)
        # The repository default is fail-closed after D0058. This fixture
        # deliberately models the counterfactual state in which an exact
        # branch-specific Task-1 PASS had authorized the prepared D0057
        # contract, so the rest of the preflight can still be tested.
        config_text = config_path.read_text(encoding="utf-8")
        config_text = config_text.replace(
            'activation_status = "BLOCKED_D0058_STEP3_STOP"',
            'activation_status = "FROZEN_TIME_OF_DAY_ONLY"',
            1,
        )
        config_text = config_text.replace(
            "result_bearing_actions_enabled = false",
            "result_bearing_actions_enabled = true",
            1,
        )
        config_text = config_text.replace(
            'holdout_status = "UNSELECTED"',
            'holdout_status = "SELECTED_QUALITY_ONLY"',
            1,
        )
        config_text = config_text.replace(
            'holdout_city = ""',
            'holdout_city = "minneapolis_st_paul"',
            1,
        )
        config_path.write_text(config_text, encoding="utf-8")
        config = load_config(config_path)

        gate_path = temp_root / config["task2"]["canonical_task1_gate"]
        gate_path.parent.mkdir(parents=True)
        gate = {
            "task1_gate": EXPECTED_GATE,
            "profile_gate": EXPECTED_PROFILE_GATE,
            "analysis_profile": EXPECTED_PROFILE,
            "scientific_gate_scope": EXPECTED_SCOPE,
            "full_panel_primary_contrast_planning_n": 72,
            "minneapolis_st_paul_excluded_primary_contrast_planning_n": 56,
            "minimum_leave_one_city_out_primary_contrast_planning_n": 54,
            "all_permitted_non_phoenix_holdouts_supported": True,
        }
        gate.update(gate_overrides or {})
        gate_path.write_text(json.dumps(gate), encoding="utf-8")

        catalogue_path = temp_root / config["evidence"]["scene_catalogue"]
        catalogue_path.parent.mkdir(parents=True)
        catalogue_path.write_text("metadata_only_fixture\n", encoding="utf-8")

        cmr_settings = config["public_cmr_census"]
        cmr_artifacts = {}
        for key in (
            "match_census_output",
            "match_summary_output",
            "collection_inventory_output",
        ):
            path = temp_root / cmr_settings[key]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{key}\n", encoding="utf-8")
            cmr_artifacts[str(path.relative_to(temp_root))] = sha256_file(path)
        cmr_summaries = []
        for product in config["public_cmr_census"]["products"]:
            cmr_summaries.append(
                {
                    "family": product["family"],
                    "core_product": product["core"],
                    "expected_associations": 719,
                    "match_fraction": 1.0 if product["core"] else 0.0,
                }
            )
        cmr_record_path = temp_root / cmr_settings["census_record_output"]
        cmr_record_path.parent.mkdir(parents=True, exist_ok=True)
        cmr_record = {
            "decision_id": "D0057",
            "status": "PASS_CORE_PRODUCT_AVAILABILITY",
            "configuration_sha256": sha256_file(config_path),
            "source_scene_catalogue_sha256": sha256_file(catalogue_path),
            "minimum_core_match_fraction": cmr_settings["minimum_core_match_fraction"],
            "metadata_acquisition_mode": "LIVE_PUBLIC_CMR",
            "expected_development_pass_tile_associations": 719,
            "product_summaries": cmr_summaries,
            "et_alexi_role": "DEMOTED_AVAILABILITY_LIMITED_OPTIONAL_STEP5_NOT_CORE",
            "credentials_used": False,
            "data_object_urls_followed": 0,
            "thermal_or_science_values_opened": 0,
            "holdout_included": False,
            "record_2026_included": False,
            "artifact_hashes": cmr_artifacts,
        }
        cmr_record_path.write_text(json.dumps(cmr_record), encoding="utf-8")

        freeze_path = temp_root / config["evidence"]["freeze_record"]
        freeze_path.parent.mkdir(parents=True, exist_ok=True)
        freeze = {
            "decision_id": "D0057",
            "holdout_city": EXPECTED_HOLDOUT,
            "interaction_stop_preserved": True,
            "lst_or_thermal_layers_opened": 0,
            "holdout_thermal_opened": False,
            "record_2026_opened": False,
            "public_cmr_core_product_status": "PASS_CORE_PRODUCT_AVAILABILITY",
            "et_alexi_role": "DEMOTED_AVAILABILITY_LIMITED_OPTIONAL_STEP5_NOT_CORE",
            "configuration_sha256": sha256_file(config_path),
            "source_hashes": {},
            "artifact_hashes": {},
        }
        freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
        decision_log = temp_root / "docs" / "v2" / "DECISION_LOG.md"
        decision_log.parent.mkdir(parents=True)
        decision_log.write_text("| D0057 | frozen |\n", encoding="utf-8")
        return temp_root, config_path

    def test_public_cmr_census_matches_exact_metadata_and_demotes_missing_alexi(self) -> None:
        temp_root = Path(tempfile.mkdtemp(prefix="v2-tod-cmr-"))
        self.addCleanup(shutil.rmtree, temp_root)
        config_path = temp_root / "configs" / "v2_task2_time_of_day.toml"
        config_path.parent.mkdir(parents=True)
        shutil.copyfile(DEFAULT_CONFIG, config_path)
        config = load_config(config_path)
        catalogue_path = temp_root / config["evidence"]["scene_catalogue"]
        catalogue_path.parent.mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "city": "atlanta",
                    "year": 2018,
                    "scene_key": "atlanta|orbit_344",
                    "time_stratum": "16-18",
                    "official_scene_granule_ids": (
                        "ECOv002_L2T_LSTE_00344_006_16SFB_"
                        "20180728T223748_0712_01.zip"
                    ),
                    "quality_candidate_pre_cloud_geometry_only": True,
                }
            ]
        ).to_csv(catalogue_path, index=False)
        products = {item["short_name"]: item for item in config["public_cmr_census"]["products"]}
        by_concept = {item["concept_id"]: item for item in products.values()}

        def requester(url: str) -> dict:
            query = parse_qs(urlparse(url).query)
            if urlparse(url).path.endswith("collections.json"):
                product = products[query["short_name"][0]]
                return {
                    "feed": {
                        "entry": [
                            {
                                "short_name": product["short_name"],
                                "version_id": "002",
                                "id": product["concept_id"],
                                "title": product["short_name"],
                                "time_start": "2018-07-10T00:00:00Z",
                                "data_center": "LPCLOUD",
                                "cloud_hosted": True,
                                "online_access_flag": True,
                            }
                        ]
                    }
                }
            product = by_concept[query["collection_concept_id"][0]]
            family = product["family"]
            if family == "ET_ALEXI":
                entries = []
            elif family == "STARS":
                entries = [
                    {
                        "producer_granule_id": "ECOv002_L2T_STARS_16SFB_20180728_0712_01",
                        "time_start": "2018-07-28T22:37:48.435Z",
                        "orbit_calculated_spatial_domains": [
                            {"start_orbit_number": "344", "stop_orbit_number": "344"}
                        ],
                        "granule_size": "14.42",
                    }
                ]
            else:
                token = product["short_name"].removeprefix("ECO_")
                entries = [
                    {
                        "producer_granule_id": (
                            f"ECOv002_{token}_00344_006_16SFB_"
                            "20180728T223748_0712_01"
                        ),
                        "granule_size": "10.0",
                    }
                ]
            return {"feed": {"entry": entries}}

        record = run_public_cmr_census(
            config_path, repo_root=temp_root, requester=requester
        )
        self.assertEqual(record["status"], "PASS_CORE_PRODUCT_AVAILABILITY")
        self.assertEqual(
            record["et_alexi_role"],
            "DEMOTED_AVAILABILITY_LIMITED_OPTIONAL_STEP5_NOT_CORE",
        )
        self.assertEqual(record["expected_development_pass_tile_associations"], 1)
        self.assertEqual(record["thermal_or_science_values_opened"], 0)
        self.assertFalse(record["credentials_used"])

    def test_official_cmr_json_import_is_network_free_and_pattern_filtered(self) -> None:
        temp_root = Path(tempfile.mkdtemp(prefix="v2-tod-cmr-import-"))
        self.addCleanup(shutil.rmtree, temp_root)
        source = temp_root / "official.json"
        source.write_text(
            json.dumps(
                {
                    "collections": [
                        {
                            "short_name": "ECO_L3T_SEB",
                            "version_id": "002",
                            "id": "C2074852168-LPCLOUD",
                        }
                    ],
                    "granules": [
                        {
                            "collection_concept_id": "C2074852168-LPCLOUD",
                            "producer_granule_id": (
                                "ECOv002_L3T_SEB_00344_006_16SFB_"
                                "20180728T223748_0712_01"
                            ),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        requester = imported_cmr_requester(source)
        payload = requester(
            "https://cmr.earthdata.nasa.gov/search/granules.json?"
            "collection_concept_id=C2074852168-LPCLOUD&"
            "producer_granule_id%5B%5D=ECOv002_L3T_SEB_00344_006_16SFB_*"
        )
        self.assertEqual(len(payload["feed"]["entry"]), 1)

    def test_exact_branch_contract_can_pass_without_raster_access(self) -> None:
        root, config_path = self._temporary_preflight_repo()
        with patch(
            "urban_cooling_v2.task2_time_of_day_guardrails._validate_gate_with_branch_validator"
        ), patch(
            "urban_cooling_v2.task2_time_of_day_guardrails.shutil.disk_usage",
            return_value=SimpleNamespace(free=40 * 1024**3),
        ):
            report = run_preflight(config_path, repo_root=root)
        self.assertTrue(report.ready, report.blockers)
        self.assertEqual(report.holdout_city, EXPECTED_HOLDOUT)
        self.assertEqual(report.development_cities, EXPECTED_DEVELOPMENT_CITIES)
        self.assertEqual(report.thermal_files_opened, 0)

    def test_generic_pass_cannot_activate_time_of_day_task2(self) -> None:
        root, config_path = self._temporary_preflight_repo(
            {"task1_gate": "PASS", "analysis_profile": "D0047_archive_available"}
        )
        with patch(
            "urban_cooling_v2.task2_time_of_day_guardrails._validate_gate_with_branch_validator"
        ), patch(
            "urban_cooling_v2.task2_time_of_day_guardrails.shutil.disk_usage",
            return_value=SimpleNamespace(free=40 * 1024**3),
        ):
            report = run_preflight(config_path, repo_root=root)
        self.assertFalse(report.ready)
        codes = {item.code for item in report.blockers}
        self.assertIn("TASK1_TASK1_GATE_MISMATCH", codes)
        self.assertIn("TASK1_ANALYSIS_PROFILE_MISMATCH", codes)

    def test_repository_default_remains_blocked_after_d0058(self) -> None:
        config = load_config(DEFAULT_CONFIG)
        task2 = config["task2"]
        self.assertEqual(task2["activation_status"], "BLOCKED_D0058_STEP3_STOP")
        self.assertFalse(task2["result_bearing_actions_enabled"])
        self.assertEqual(task2["holdout_status"], "UNSELECTED")
        self.assertEqual(task2["holdout_city"], "")
        self.assertEqual(task2["heldout_thermal_status"], "UNOPENED")
        self.assertEqual(task2["season_2026_status"], "UNOPENED")


if __name__ == "__main__":
    unittest.main()
