#!/usr/bin/env python3
"""Network-free gate tests for the D0035 HRRR handoff runner."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_v2_step02_definitive as runner  # noqa: E402


class DefinitiveStep2RunnerTests(unittest.TestCase):
    def test_complete_catalogue_preserves_enriched_excluded_daytime_rows(self) -> None:
        base = pd.DataFrame(
            [
                {
                    "city": "atlanta",
                    "orbit": 1,
                    "acquisition_utc": "2024-07-01T02:00:00Z",
                    "retrieval_band_mode": "post_fix_unknown",
                    "source": "base-night",
                },
                {
                    "city": "atlanta",
                    "orbit": 2,
                    "acquisition_utc": "2024-07-01T16:00:00Z",
                    "retrieval_band_mode": "post_fix_unknown",
                    "source": "base-daytime",
                },
                {
                    "city": "atlanta",
                    "orbit": 3,
                    "acquisition_utc": "2024-07-02T16:00:00Z",
                    "retrieval_band_mode": "post_fix_unknown",
                    "source": "base-screened",
                },
            ]
        )
        enriched = base.loc[base["orbit"].isin([2, 3])].copy()
        enriched["retrieval_band_mode"] = "full"
        enriched["retrieval_band_count"] = 5
        enriched["source"] = "official-sidecar"
        screened = enriched.loc[enriched["orbit"].eq(3)].copy()
        screened["source"] = "d0047-final-screen"

        complete = runner._assemble_complete_catalogue(base, enriched, screened)

        self.assertEqual(len(complete), len(base))
        self.assertFalse(complete.duplicated(["city", "orbit"]).any())
        by_orbit = complete.set_index("orbit")
        self.assertEqual(by_orbit.loc[1, "source"], "base-night")
        self.assertEqual(by_orbit.loc[2, "source"], "official-sidecar")
        self.assertEqual(by_orbit.loc[2, "retrieval_band_mode"], "full")
        self.assertEqual(by_orbit.loc[2, "retrieval_band_count"], 5)
        self.assertEqual(by_orbit.loc[3, "source"], "d0047-final-screen")

    @staticmethod
    def _d0048_evidence_fixture() -> tuple[dict[str, object], dict[str, object]]:
        scene_binding: dict[str, object] = {
            "orbit": 344,
            "scene": 5,
            "granule_id": "ECOv002_L1B_GEO_00344_005",
            "cmr_record_sha256": "c" * 64,
            "dmrpp_sha256": "d" * 64,
            "locator_sha256": "e" * 64,
        }
        binding: dict[str, object] = {
            "implementation_decision_id": "D0048",
            "algorithm_version": runner.D0048_ALGORITHM_VERSION,
            "locator_stride": 32,
            "source_margin_pixels": 64,
            "radius_m": 210.0,
            "boundary_guard_m": 310.0,
            "max_selected_chunks": 512,
            "max_range_bytes_per_scene": 256 * 1024 * 1024,
            "verified_no_overlap_locator_shape": [176, 169],
            "verified_no_overlap_locator_expected_cells": 29_744,
            "verified_no_overlap_locator_stride": 32,
            "verified_no_overlap_locator_stride_minus_one_pixels": 31,
            "verified_no_overlap_locator_influence_m": 8_000.0,
            "verified_no_overlap_max_unsampled_path_pixels": 62,
            "verified_no_overlap_maximum_adjacent_source_displacement_m": 100.0,
            "verified_no_overlap_locator_uncertainty_m": 6_200.0,
            "verified_no_overlap_boundary_guard_m": 310.0,
            "verified_no_overlap_source_margin_pixels": 64,
            "verified_no_overlap_tie_break_rule": "row_major_lowest_flat_index",
            "scene_bindings": [scene_binding],
        }
        scene: dict[str, object] = {
            **scene_binding,
            "proof_mode": "verified_no_overlap",
            "proof_status": "verified_no_domain_overlap",
            "proof_acceptance_status": "verified_no_overlap_mapped_zero",
            "geometry_observation_status": "verified_no_domain_overlap",
            "locator_shape": [176, 169],
            "locator_stride": 32,
            "locator_stride_minus_one_pixels": 31,
            "locator_influence_m": 8_000.0,
            "locator_valid_count": 29_744,
            "locator_expected_count": 29_744,
            "locator_max_unsampled_path_pixels": 62,
            "maximum_adjacent_source_displacement_m": 100.0,
            "locator_minimum_domain_distance_m": 40_000.0,
            "locator_uncertainty_bound_m": 6_200.0,
            "locator_no_overlap_lower_bound_m": 33_800.0,
            "boundary_guard_distance_m": 310.0,
            "seed_source_margin_pixels": 64,
            "row_major_tie_breaking": True,
            "seeded_locator_points": [
                {
                    "target_grid": "16SGC",
                    "locator_flat_index": 171,
                    "locator_row": 1,
                    "locator_col": 2,
                    "source_row": 32,
                    "source_col": 64,
                    "latitude": 33.75,
                    "longitude": -84.4,
                    "minimum_domain_distance_m": 40_000.0,
                }
            ],
            "seeded_chunk_coords": [[0, 0], [0, 1], [1, 0], [1, 1]],
            "seeded_chunk_count": 4,
            "initial_chunk_count": 4,
            "final_chunk_count": 4,
            "boundary_expansion_iterations": 1,
            "boundary_edges_tested": 8,
            "boundary_minimum_domain_distance_m": 30_000.0,
            "boundary_verified": True,
            "full_resolution_boundary_verified": True,
            "mapped_target_cell_count": 0,
            "range_bytes_transferred": 1_000,
            "verified_no_overlap_mapped_zero": True,
            "verified_no_overlap_zero_imputed": False,
            "missing_scene_zero_coverage_assigned": False,
            "missing_scene_substitution_used": False,
        }
        return binding, scene

    def test_d0048_verified_no_overlap_evidence_is_fail_closed(self) -> None:
        binding, scene = self._d0048_evidence_fixture()
        with mock.patch.multiple(
            runner,
            D0047_ALGORITHM_VERSION=runner.D0048_ALGORITHM_VERSION,
            D0047_IMPLEMENTATION_DECISION_ID="D0048",
        ):
            runner._validate_d0048_geometry_evidence(
                binding, [scene], item_id="atlanta:00344"
            )

            mutations = {
                "selection mode": lambda value: value.__setitem__(
                    "proof_mode", "locator_near_domain_typo"
                ),
                "proof status": lambda value: value.__setitem__(
                    "proof_status", "verified_no_overlap"
                ),
                "acceptance status": lambda value: value.__setitem__(
                    "proof_acceptance_status", "pending"
                ),
                "observation status": lambda value: value.__setitem__(
                    "geometry_observation_status", "zero_assigned"
                ),
                "locator shape": lambda value: value.__setitem__(
                    "locator_shape", [175, 169]
                ),
                "locator stride": lambda value: value.__setitem__(
                    "locator_stride", 31
                ),
                "stride-minus-one": lambda value: value.__setitem__(
                    "locator_stride_minus_one_pixels", 30
                ),
                "locator influence": lambda value: value.__setitem__(
                    "locator_influence_m", 8_001.0
                ),
                "full-valid count": lambda value: value.__setitem__(
                    "locator_valid_count", 29_743
                ),
                "expected count": lambda value: value.__setitem__(
                    "locator_expected_count", 29_743
                ),
                "max path": lambda value: value.__setitem__(
                    "locator_max_unsampled_path_pixels", 61
                ),
                "adjacent displacement": lambda value: value.__setitem__(
                    "maximum_adjacent_source_displacement_m", 99.0
                ),
                "uncertainty bound": lambda value: value.__setitem__(
                    "locator_uncertainty_bound_m", 6_199.0
                ),
                "lower-bound arithmetic": lambda value: value.__setitem__(
                    "locator_no_overlap_lower_bound_m", 33_801.0
                ),
                "lower-bound guard": lambda value: (
                    value.__setitem__("locator_minimum_domain_distance_m", 6_510.0),
                    value.__setitem__("locator_no_overlap_lower_bound_m", 310.0),
                ),
                "source margin": lambda value: value.__setitem__(
                    "seed_source_margin_pixels", 63
                ),
                "tie-break declaration": lambda value: value.__setitem__(
                    "row_major_tie_breaking", False
                ),
                "row-major flat index": lambda value: value[
                    "seeded_locator_points"
                ][0].__setitem__("locator_flat_index", 172),
                "source-row binding": lambda value: value[
                    "seeded_locator_points"
                ][0].__setitem__("source_row", 31),
                "global-minimum binding": lambda value: value[
                    "seeded_locator_points"
                ][0].__setitem__("minimum_domain_distance_m", 40_001.0),
                "seed count": lambda value: value.__setitem__(
                    "seeded_chunk_count", 3
                ),
                "boundary guard": lambda value: value.__setitem__(
                    "boundary_guard_distance_m", 309.0
                ),
                "boundary verification": lambda value: value.__setitem__(
                    "full_resolution_boundary_verified", False
                ),
                "boundary distance": lambda value: value.__setitem__(
                    "boundary_minimum_domain_distance_m", 310.0
                ),
                "boundary edges": lambda value: value.__setitem__(
                    "boundary_edges_tested", 0
                ),
                "mapped count": lambda value: value.__setitem__(
                    "mapped_target_cell_count", 1
                ),
                "range cap": lambda value: value.__setitem__(
                    "range_bytes_transferred", 256 * 1024 * 1024 + 1
                ),
                "mapped-zero flag": lambda value: value.__setitem__(
                    "verified_no_overlap_mapped_zero", False
                ),
                "zero imputation": lambda value: value.__setitem__(
                    "verified_no_overlap_zero_imputed", True
                ),
                "missing-scene zero": lambda value: value.__setitem__(
                    "missing_scene_zero_coverage_assigned", True
                ),
                "scene substitution": lambda value: value.__setitem__(
                    "missing_scene_substitution_used", True
                ),
            }
            for label, mutate in mutations.items():
                with self.subTest(field=label):
                    damaged = copy.deepcopy(scene)
                    mutate(damaged)
                    with self.assertRaisesRegex(RuntimeError, "D0048"):
                        runner._validate_d0048_geometry_evidence(
                            binding, [damaged], item_id="atlanta:00344"
                        )

    def test_d0048_binding_and_ordinary_path_are_both_sealed(self) -> None:
        binding, scene = self._d0048_evidence_fixture()
        ordinary = copy.deepcopy(scene)
        ordinary.update(
            {
                "proof_mode": "locator_near_domain",
                "proof_status": "near_domain_full_resolution_verified",
                "proof_acceptance_status": "ordinary_near_domain_mapping",
                "geometry_observation_status": "mapped_near_domain_geometry",
                "verified_no_overlap_mapped_zero": False,
            }
        )
        with mock.patch.multiple(
            runner,
            D0047_ALGORITHM_VERSION=runner.D0048_ALGORITHM_VERSION,
            D0047_IMPLEMENTATION_DECISION_ID="D0048",
        ):
            runner._validate_d0048_geometry_evidence(
                binding, [ordinary], item_id="atlanta:00451"
            )
            for field in (
                "implementation_decision_id",
                "algorithm_version",
                "locator_stride",
                "source_margin_pixels",
                "radius_m",
                "boundary_guard_m",
                "max_selected_chunks",
                "max_range_bytes_per_scene",
                "verified_no_overlap_locator_shape",
                "verified_no_overlap_locator_expected_cells",
                "verified_no_overlap_locator_stride",
                "verified_no_overlap_locator_stride_minus_one_pixels",
                "verified_no_overlap_locator_influence_m",
                "verified_no_overlap_max_unsampled_path_pixels",
                "verified_no_overlap_maximum_adjacent_source_displacement_m",
                "verified_no_overlap_locator_uncertainty_m",
                "verified_no_overlap_boundary_guard_m",
                "verified_no_overlap_source_margin_pixels",
                "verified_no_overlap_tie_break_rule",
            ):
                with self.subTest(binding_field=field):
                    damaged = copy.deepcopy(binding)
                    damaged[field] = None
                    with self.assertRaisesRegex(RuntimeError, "D0048 binding"):
                        runner._validate_d0048_geometry_evidence(
                            damaged, [ordinary], item_id="atlanta:00451"
                        )

    def test_current_provenance_rejects_a_stale_geometry_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="step2-provenance-") as temporary:
            root = Path(temporary).resolve()
            quality = root / "data/processed/v2/task1/quality"
            raw = root / "data/raw/v2/ecostress/l1b_geo_geometry_D0035"
            evidence_dir = raw / "pass_evidence"
            evidence_path = evidence_dir / "phoenix/00001.json"
            evidence_path.parent.mkdir(parents=True)
            quality.mkdir(parents=True)
            scene_manifest = raw / "l1b_geo_scene_manifest.csv"
            asset_checkpoint = raw / "locator_dmrpp_checkpoint.json"
            geometry_checkpoint = raw / "geometry_scene_checkpoint.json"
            geometry_summary_path = quality / "geometry_pass_summary.csv"
            cloud_checkpoint = root / "data/raw/v2/ecostress/cloud_checkpoint.json"
            cloud_checkpoint.parent.mkdir(parents=True, exist_ok=True)
            cloud_summary = quality / "cloud_pass_summary.csv"
            combined_path = quality / "combined_validation.json"
            run_record_path = quality / "run_record.json"

            cmr_hash = "c" * 64
            pd.DataFrame(
                [
                    {
                        "orbit": 1,
                        "scene": 1,
                        "granule_id": "ECO_L1B_GEO_00001_001",
                        "cities": "phoenix",
                        "status": "available",
                        "decision_id": "D0035",
                        "collection_short_name": "ECO_L1B_GEO",
                        "collection_version": "002",
                        "collection_concept_id": runner.D0035_COLLECTION_CONCEPT_ID,
                        "cmr_record_sha256": cmr_hash,
                    }
                ]
            ).to_csv(scene_manifest, index=False)
            asset_checkpoint.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "items": {
                            "ECO_L1B_GEO_00001_001": {
                                "status": "complete",
                                "algorithm_version": runner.D0035_ALGORITHM_VERSION,
                                "collection_concept_id": runner.D0035_COLLECTION_CONCEPT_ID,
                                "cmr_record_sha256": cmr_hash,
                                "dmrpp_sha256": "d" * 64,
                                "locator_sha256": "e" * 64,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            summary = {
                "city": "phoenix",
                "orbit": 1,
                "acquisition_utc": "2023-07-01T19:30:00Z",
                "n_l1b_geo_scenes": 1,
                "decision_id": "D0035",
            }
            pd.DataFrame([summary]).to_csv(geometry_summary_path, index=False)
            scene_binding = {
                "orbit": 1,
                "scene": 1,
                "granule_id": "ECO_L1B_GEO_00001_001",
                "algorithm_version": runner.D0035_ALGORITHM_VERSION,
                "collection_concept_id": runner.D0035_COLLECTION_CONCEPT_ID,
                "dmrpp_sha256": "d" * 64,
                "locator_sha256": "e" * 64,
            }
            binding = {
                "algorithm_version": runner.D0035_ALGORITHM_VERSION,
                "decision_id": "D0035",
                "city": "phoenix",
                "orbit": 1,
                "acquisition_utc": "2023-07-01T19:30:00+00:00",
                "scene_bindings": [scene_binding],
            }
            binding_hash = runner._json_sha256(binding)
            evidence_path.write_text(
                json.dumps(
                    {
                        "status": "complete",
                        "decision_id": "D0035",
                        "algorithm_version": runner.D0035_ALGORITHM_VERSION,
                        "city": "phoenix",
                        "orbit": 1,
                        "boundary_verified": True,
                        "binding": binding,
                        "binding_sha256": binding_hash,
                        "scene_evidence": [{"boundary_verified": True}],
                        "summary": summary,
                        "lst_opened": False,
                        "thermal_opened": False,
                        "record_2026_opened": False,
                        "holdout_status": "UNSELECTED",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            geometry_checkpoint.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "items": {
                            "phoenix:00001": {
                                "status": "complete",
                                "boundary_verified": True,
                                "binding_sha256": binding_hash,
                                "evidence_path": str(evidence_path),
                                "evidence_sha256": runner._sha256(evidence_path),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            cloud_checkpoint.write_text(
                '{"schema_version": 1, "items": {}}\n', encoding="utf-8"
            )
            cloud_summary.write_text("city,orbit\nphoenix,1\n", encoding="utf-8")
            combined = {"decision_id": "D0035", "gate_status": runner.D0035_PASS_STATUS}
            combined_path.write_text(json.dumps(combined) + "\n", encoding="utf-8")
            counts = {
                "metadata_candidates": 1,
                "city_scene_links": 1,
                "unique_scenes": 1,
                "asset_checkpoint_items": 1,
                "geometry_checkpoint_items": 1,
                "pass_evidence_files": 1,
            }
            hashes = {
                "scene_manifest": runner._sha256(scene_manifest),
                "asset_checkpoint": runner._sha256(asset_checkpoint),
                "geometry_checkpoint": runner._sha256(geometry_checkpoint),
                "pass_evidence_set": runner._sha256_strings(
                    [f"phoenix/00001.json:{runner._sha256(evidence_path)}"]
                ),
                "geometry_summary": runner._sha256(geometry_summary_path),
                "cloud_checkpoint": runner._sha256(cloud_checkpoint),
                "cloud_summary": runner._sha256(cloud_summary),
                "combined_validation": runner._sha256(combined_path),
            }
            run_record_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "decision_id": "D0035",
                        "implementation_decision_id": "D0036",
                        "collection_concept_id": runner.D0035_COLLECTION_CONCEPT_ID,
                        "algorithm_version": runner.D0035_ALGORITHM_VERSION,
                        "provenance_counts": counts,
                        "provenance_sha256": hashes,
                        "artifact_sha256": {
                            str(geometry_summary_path.relative_to(root)): runner._sha256(
                                geometry_summary_path
                            )
                        },
                        "combined_validation": combined,
                        "lst_opened": False,
                        "thermal_opened": False,
                        "record_2026_opened": False,
                        "holdout_status": "UNSELECTED",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            patched = {
                "ROOT": root,
                "GEOMETRY_SUMMARY": geometry_summary_path,
                "CLOUD_SUMMARY": cloud_summary,
                "COMBINED_VALIDATION": combined_path,
                "D0035_SCENE_MANIFEST": scene_manifest,
                "D0035_ASSET_CHECKPOINT": asset_checkpoint,
                "D0035_GEOMETRY_CHECKPOINT": geometry_checkpoint,
                "D0035_PASS_EVIDENCE_DIR": evidence_dir,
                "D0035_CLOUD_CHECKPOINT": cloud_checkpoint,
                "D0035_RUN_RECORD": run_record_path,
                "EXPECTED_METADATA_CANDIDATES": 1,
                "EXPECTED_CITY_SCENE_LINKS": 1,
                "EXPECTED_UNIQUE_SCENES": 1,
            }
            with mock.patch.multiple(runner, **patched):
                current = pd.read_csv(geometry_summary_path)
                provenance = runner._validate_d0035_provenance(current, combined)
                self.assertEqual(provenance["provenance_counts"], counts)
                current.loc[0, "n_l1b_geo_scenes"] = 2
                current.to_csv(geometry_summary_path, index=False)
                with self.assertRaisesRegex(RuntimeError, "stale"):
                    runner._validate_d0035_provenance(
                        pd.read_csv(geometry_summary_path), combined
                    )

    def test_incomplete_combined_seal_blocks_before_hrrr_planning(self) -> None:
        with tempfile.TemporaryDirectory(prefix="step2-d0035-gate-") as temporary:
            root = Path(temporary).resolve()
            quality = root / "quality"
            quality.mkdir()
            screen = pd.DataFrame(
                {
                    "city": ["phoenix", "miami"],
                    "orbit": [1, 2],
                    "acquisition_utc": [
                        "2023-07-01T19:30:00.833Z",
                        "2023-07-02T18:30:00Z",
                    ],
                    "metadata_candidate": [True, True],
                    "l1b_geometry_covered_cells": [100, 100],
                    "l1b_geometry_domain_cells": [100, 100],
                    "l1b_geometry_coverage_fraction": [1.0, 1.0],
                    "l1b_view_zenith_abs_p95_deg": [10.0, 12.0],
                    "l1b_geometry_complete": [True, True],
                    "l1b_geometry_status": ["geometry_pass", "geometry_pass"],
                    "quality_candidate_pre_cloud": [True, True],
                    "quality_candidate_pre_cloud_l1b": [True, True],
                    "quality_candidate_pre_cloud_l2t_invalid": [True, False],
                }
            )
            legacy_path = quality / "legacy_screen.csv"
            pd.DataFrame(
                {
                    "city": ["phoenix", "miami"],
                    "orbit": [1, 2],
                    "acquisition_utc": [
                        "2023-07-01T19:30:00.833Z",
                        "2023-07-02T18:30:00Z",
                    ],
                    "metadata_candidate": [True, True],
                    "quality_candidate_pre_cloud": [True, False],
                }
            ).to_csv(legacy_path, index=False)
            pre_cloud_path = quality / "passes_quality_screened_pre_cloud_geometry_only.csv"
            final_screen_path = quality / "passes_quality_screened_l1b_geo.csv"
            screen.to_csv(pre_cloud_path, index=False)
            screen.to_csv(final_screen_path, index=False)
            geometry_summary_path = quality / "geometry_pass_summary.csv"
            geometry_summary = screen[
                [
                    "city",
                    "orbit",
                    "acquisition_utc",
                    "l1b_geometry_covered_cells",
                    "l1b_geometry_domain_cells",
                    "l1b_geometry_coverage_fraction",
                    "l1b_view_zenith_abs_p95_deg",
                    "l1b_geometry_complete",
                    "l1b_geometry_status",
                    "quality_candidate_pre_cloud",
                    "quality_candidate_pre_cloud_l1b",
                    "quality_candidate_pre_cloud_l2t_invalid",
                ]
            ].copy()
            geometry_summary.to_csv(geometry_summary_path, index=False)
            geometry_validation_path = quality / "geometry_validation.json"
            geometry_validation_path.write_text(
                json.dumps(
                    {
                        "decision_id": "D0035",
                        "expected_metadata_candidates": 2,
                        "resolved_geometry_candidate_count": 2,
                        "definitive_geometry_status_count": 2,
                        "unresolved_geometry_candidate_count": 0,
                        "geometry_source": "ECO_L1B_GEO.002",
                        "geometry_complete": True,
                        "candidate_seal_geometry_only": True,
                        "geometry_passing_candidate_count": 2,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            summary_path = quality / "cloud_pass_summary.csv"
            pd.DataFrame(
                {
                    "city": ["phoenix", "miami"],
                    "orbit": [1, 2],
                    "acquisition_utc": [
                        "2023-07-01T19:30:00.833Z",
                        "2023-07-02T18:30:00Z",
                    ],
                    "n_domain_pixels": [100, 100],
                    "n_domain_pixels_in_present_tiles": [100, 100],
                    "n_cloud_observed_pixels_independent_of_view": [100, 90],
                    "n_clear_pixels_independent_of_view": [0, 50],
                    "n_cloud_pixels_independent_of_view": [100, 40],
                    "n_cloud_invalid_or_fill_pixels_independent_of_view": [0, 10],
                    "cloud_survival_fraction_of_domain_independent_of_view": [
                        0.0,
                        0.5,
                    ],
                    "clear_domain_fraction": [0.0, 0.5],
                    "n_expected_scene_tiles": [1, 1],
                    "n_resolved_cloud_assets": [1, 1],
                    "n_verified_cloud_assets": [1, 1],
                    "cloud_asset_complete": [True, True],
                    "provenance_complete": [True, True],
                    "cloud_asset_bytes": [1000, 2000],
                    "cloud_asset_set_sha256": ["a" * 64, "b" * 64],
                    "cloud_resolution_status": [
                        "observed_exhaustive_complete_independent_of_view",
                        "observed_exhaustive_complete_independent_of_view",
                    ],
                    "decision_id": ["D0035", "D0035"],
                }
            ).to_csv(summary_path, index=False)
            validation_path = quality / "combined_validation.json"
            validation = {
                "decision_id": "D0035",
                "expected_metadata_candidates": 2,
                "resolved_geometry_candidate_count": 2,
                "definitive_geometry_status_count": 2,
                "unresolved_geometry_candidate_count": 0,
                "geometry_source": "ECO_L1B_GEO.002",
                "geometry_complete": True,
                "geometry_passing_candidate_count": 2,
                "expected_cloud_candidates": 2,
                "resolved_cloud_candidate_count": 2,
                "finite_cloud_fraction_count": 2,
                "cloud_complete": True,
                "combined_complete": True,
                "planning_pass_equivalent_sum": 0.5,
                "planning_pass_equivalent_floor": 0,
                "candidate_seal_geometry_only": False,
                "candidate_view_mask_cloud_independent": False,
                "view_gate_cloud_conditioned": True,
                "cloud_extrapolation_used": False,
                "scientific_gate_eligible": False,
                "canonical_status": "STOP_D0035_COMBINED_GATE",
                "gate_status": "STOP_D0035_COMBINED_GATE",
                "lst_opened": False,
                "thermal_opened": False,
                "record_2026_opened": False,
                "holdout_status": "UNSELECTED",
                "frozen_years": "2018-2025",
            }
            validation_path.write_text(
                json.dumps(validation) + "\n", encoding="utf-8"
            )
            manifest = root / "must_not_exist.csv"
            with mock.patch.multiple(
                runner,
                QUALITY=quality,
                GEOMETRY_SUMMARY=geometry_summary_path,
                GEOMETRY_VALIDATION=geometry_validation_path,
                SCREENED_PRE_CLOUD=pre_cloud_path,
                SCREENED_FINAL=final_screen_path,
                LEGACY_SCREENED=legacy_path,
                CLOUD_SUMMARY=summary_path,
                COMBINED_VALIDATION=validation_path,
                EXPECTED_METADATA_CANDIDATES=2,
                HRRR_MANIFEST=manifest,
                _validate_d0035_provenance=mock.Mock(
                    return_value={"algorithm_version": runner.D0035_ALGORITHM_VERSION}
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "STOP_D0035_COMBINED_GATE"
                ):
                    runner._load_quality()
                self.assertFalse(manifest.exists())

                validation.update(
                    {
                        "candidate_seal_geometry_only": True,
                        "candidate_view_mask_cloud_independent": True,
                        "view_gate_cloud_conditioned": False,
                        "scientific_gate_eligible": True,
                        "canonical_status": runner.D0035_PASS_STATUS,
                        "gate_status": runner.D0035_PASS_STATUS,
                    }
                )
                validation_path.write_text(
                    json.dumps(validation) + "\n", encoding="utf-8"
                )
                screened, cloud, loaded_validation = runner._load_quality()
                candidates = runner._candidate_passes(screened, cloud)
                self.assertEqual(len(candidates), 2)
                self.assertEqual(
                    candidates["cloud_survival_fraction_of_domain"].tolist(),
                    [0.5, 0.0],
                )
                self.assertTrue(loaded_validation["scientific_gate_eligible"])
                reference_index = root / "reference.idx"
                reference_index.write_text(
                    "\n".join(
                        [
                            "1:0:d=2023071819:VIS:surface:anl:",
                            "2:100:d=2023071819:TMP:2 m above ground:anl:",
                            "3:1300:d=2023071819:POT:2 m above ground:anl:",
                            "4:2500:d=2023071819:DPT:2 m above ground:anl:",
                            "5:3600:d=2023071819:RH:2 m above ground:anl:",
                        ]
                    ),
                    encoding="utf-8",
                )
                scope = runner.summarize_hrrr_request_scope(
                    candidates, reference_index_path=reference_index
                )
                self.assertEqual(scope["candidate_passes"], 2)
                self.assertEqual(scope["unique_analysis_hours"], 4)
                self.assertEqual(
                    scope["two_x_conservative_bytes_projection"], 4 * 2300 * 2
                )
                self.assertFalse(manifest.exists())
                expected_manifest = runner.build_hrrr_request_manifest(candidates)
                expected_manifest.to_csv(manifest, index=False)
                self.assertEqual(len(runner._load_manifest_for_current_gate()), 4)
                stale = expected_manifest.copy()
                stale.loc[0, "cities"] = "wrong-city"
                stale.to_csv(manifest, index=False)
                with self.assertRaisesRegex(RuntimeError, "manifest is stale"):
                    runner._load_manifest_for_current_gate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
