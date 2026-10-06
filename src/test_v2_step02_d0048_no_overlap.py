#!/usr/bin/env python3
"""Network-free tests for D0048 verified-no-domain-overlap geometry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd
from pyproj import CRS, Transformer
from scipy.spatial import cKDTree
from shapely.geometry import Point

import run_v2_step02_l1b_geometry as runner
from urban_cooling_v2 import step02_archive_available as archive
from urban_cooling_v2.step02_l1b_geometry import (
    BOUNDARY_GUARD_DISTANCE_M,
    FULL_SWATH_SHAPE,
    LOCATOR_INFLUENCE_M,
    LOCATOR_MARGIN_PIXELS,
    LOCATOR_STRIDE,
    MAX_ADJACENT_SOURCE_DISPLACEMENT_M,
    NO_OVERLAP_LOCATOR_EXPECTED_CELLS,
    NO_OVERLAP_LOCATOR_SHAPE,
    NO_OVERLAP_LOCATOR_UNCERTAINTY_M,
    NO_OVERLAP_MAX_UNSAMPLED_PATH_PIXELS,
    TargetGrid,
    finalize_initial_selection_proof,
    initial_chunk_selection,
    initial_chunk_selection_with_proof,
    sha256_file,
    summarize_geometry_passes,
    write_scene_map_npz,
)


def _grid(
    *,
    tile: str = "12SVC",
    domain_radius_m: float = 0.0,
) -> TargetGrid:
    crs = CRS.from_epsg(32612)
    x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(
        -112.0, 33.0
    )
    x_values = np.array([x], dtype=float)
    y_values = np.array([y], dtype=float)
    domain = Point(float(x), float(y))
    if domain_radius_m:
        domain = domain.buffer(domain_radius_m)
    return TargetGrid(
        city="phoenix",
        tile=tile,
        crs=crs,
        x=x_values,
        y=y_values,
        tree=cKDTree(np.column_stack((x_values, y_values))),
        domain_geometry_projected=domain,
    )


def _locator_at_offset(grid: TargetGrid, offset_m: float) -> tuple[np.ndarray, np.ndarray]:
    inverse = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    longitude, latitude = inverse.transform(grid.x[0] + offset_m, grid.y[0])
    lat = np.full(NO_OVERLAP_LOCATOR_SHAPE, latitude, dtype=float)
    lon = np.full(NO_OVERLAP_LOCATOR_SHAPE, longitude, dtype=float)
    return lat, lon


class InitialSelectionTests(unittest.TestCase):
    def test_ordinary_near_scene_selection_is_unchanged(self) -> None:
        grid = _grid()
        lat, lon = _locator_at_offset(grid, 20_000.0)
        inverse = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
        lon[3, 4], lat[3, 4] = inverse.transform(grid.x[0], grid.y[0])
        expected = initial_chunk_selection(
            lat, lon, {grid.tile: grid}, chunk_shape=(128, 128)
        )
        observed, proof = initial_chunk_selection_with_proof(
            lat, lon, {grid.tile: grid}, chunk_shape=(128, 128)
        )
        self.assertEqual(observed, expected)
        self.assertEqual(proof["proof_mode"], "locator_near_domain")

    def test_far_fully_valid_locator_seeds_verified_no_overlap(self) -> None:
        grid = _grid(domain_radius_m=100.0)
        lat, lon = _locator_at_offset(grid, 20_000.0)
        selected, proof = initial_chunk_selection_with_proof(
            lat, lon, {grid.tile: grid}, chunk_shape=(128, 128)
        )
        self.assertEqual(selected, {(0, 0)})
        self.assertEqual(proof["proof_mode"], "verified_no_overlap")
        self.assertEqual(proof["locator_valid_count"], 29_744)
        self.assertEqual(proof["locator_expected_count"], 29_744)
        self.assertGreater(
            proof["locator_no_overlap_lower_bound_m"],
            BOUNDARY_GUARD_DISTANCE_M,
        )
        self.assertEqual(proof["seeded_locator_points"][0]["locator_flat_index"], 0)
        self.assertEqual(proof["seeded_chunk_coords"], [[0, 0]])

    def test_fallback_rejects_any_invalid_or_fill_locator_cell(self) -> None:
        grid = _grid()
        for label, value in (("nan", np.nan), ("fill", 0.0)):
            with self.subTest(label=label):
                lat, lon = _locator_at_offset(grid, 20_000.0)
                if label == "nan":
                    lat[10, 10] = value
                else:
                    lat[10, 10] = 0.0
                    lon[10, 10] = 0.0
                with self.assertRaisesRegex(ValueError, "all 29,744"):
                    initial_chunk_selection_with_proof(
                        lat, lon, {grid.tile: grid}, chunk_shape=(128, 128)
                    )

    def test_fallback_rejects_any_nonproduction_locator_shape(self) -> None:
        grid = _grid()
        lat = np.full((175, 169), 20.0, dtype=float)
        lon = np.full((175, 169), -100.0, dtype=float)
        with self.assertRaisesRegex(ValueError, "Unexpected stride locator shape"):
            initial_chunk_selection_with_proof(
                lat, lon, {grid.tile: grid}, chunk_shape=(128, 128)
            )

    def test_fallback_rejects_insufficient_literal_domain_lower_bound(self) -> None:
        # Target centres remain >8 km away, so ordinary initialization is
        # empty, while the literal domain extends to within about 6.5 km.
        grid = _grid(domain_radius_m=1_700.0)
        lat, lon = _locator_at_offset(grid, 8_200.0)
        with self.assertRaisesRegex(ValueError, "310 m guard"):
            initial_chunk_selection_with_proof(
                lat, lon, {grid.tile: grid}, chunk_shape=(128, 128)
            )

    def test_row_major_seed_tie_breaking_is_deterministic_per_grid(self) -> None:
        a = _grid(tile="A")
        z = _grid(tile="Z")
        lat, lon = _locator_at_offset(a, 20_000.0)
        first_selected, first = initial_chunk_selection_with_proof(
            lat, lon, {"Z": z, "A": a}, chunk_shape=(128, 128)
        )
        second_selected, second = initial_chunk_selection_with_proof(
            lat.copy(), lon.copy(), {"A": a, "Z": z}, chunk_shape=(128, 128)
        )
        self.assertEqual(first_selected, second_selected)
        self.assertEqual(first["seeded_locator_points"], second["seeded_locator_points"])
        self.assertEqual(
            [item["target_grid"] for item in first["seeded_locator_points"]],
            ["A", "Z"],
        )
        self.assertTrue(
            all(
                item["locator_flat_index"] == 0
                for item in first["seeded_locator_points"]
            )
        )


class ProofFinalizationTests(unittest.TestCase):
    def _pending_proof(self) -> dict[str, object]:
        grid = _grid()
        lat, lon = _locator_at_offset(grid, 20_000.0)
        _, proof = initial_chunk_selection_with_proof(
            lat, lon, {grid.tile: grid}, chunk_shape=(128, 128)
        )
        return proof

    def test_zero_mapping_is_observed_and_not_imputed(self) -> None:
        proof = finalize_initial_selection_proof(
            self._pending_proof(),
            full_resolution_boundary_verified=True,
            mapped_target_cell_count=0,
        )
        self.assertEqual(proof["proof_status"], "verified_no_domain_overlap")
        self.assertEqual(
            proof["proof_acceptance_status"], "verified_no_overlap_mapped_zero"
        )
        self.assertTrue(proof["verified_no_overlap_mapped_zero"])
        self.assertFalse(proof["verified_no_overlap_zero_imputed"])
        self.assertFalse(proof["missing_scene_zero_coverage_assigned"])

    def test_any_mapped_cell_is_a_fail_closed_contradiction(self) -> None:
        with self.assertRaisesRegex(ValueError, "contradiction"):
            finalize_initial_selection_proof(
                self._pending_proof(),
                full_resolution_boundary_verified=True,
                mapped_target_cell_count=1,
            )

    def test_final_evidence_validator_binds_every_frozen_constant(self) -> None:
        proof = finalize_initial_selection_proof(
            self._pending_proof(),
            full_resolution_boundary_verified=True,
            mapped_target_cell_count=0,
        )
        evidence = {**proof, "boundary_verified": True}
        with mock.patch.object(runner, "IMPLEMENTATION_DECISION_ID", "D0048"):
            self.assertTrue(runner._scene_boundary_evidence_valid(evidence))
            corrupted = {**evidence, "locator_uncertainty_bound_m": 6_199.0}
            self.assertFalse(runner._scene_boundary_evidence_valid(corrupted))


class PassOutcomeTests(unittest.TestCase):
    def test_empty_scene_combines_with_companion_and_single_empty_is_definitive(self) -> None:
        grid = _grid()
        empty = {
            grid.tile: {
                "target_index": np.array([], dtype=np.int32),
                "view_zenith_abs_deg": np.array([], dtype=np.float32),
                "source_distance_m": np.array([], dtype=np.float32),
            }
        }
        companion = {
            grid.tile: {
                "target_index": np.array([0], dtype=np.int32),
                "view_zenith_abs_deg": np.array([10.0], dtype=np.float32),
                "source_distance_m": np.array([0.0], dtype=np.float32),
            }
        }
        candidates = pd.DataFrame(
            {
                "city": [grid.city],
                "orbit": [1],
                "acquisition_utc": ["2020-07-01T00:00:00Z"],
            }
        )
        with tempfile.TemporaryDirectory(prefix="d0048-empty-pass-") as temporary:
            empty_path = Path(temporary) / "empty.npz"
            companion_path = Path(temporary) / "companion.npz"
            write_scene_map_npz(empty_path, empty)
            write_scene_map_npz(companion_path, companion)
            multi_links = pd.DataFrame(
                {
                    "city": [grid.city, grid.city],
                    "orbit": [1, 1],
                    "scene": [1, 2],
                }
            )
            multi = summarize_geometry_passes(
                candidates,
                multi_links,
                {
                    (grid.city, 1, 1): empty_path,
                    (grid.city, 1, 2): companion_path,
                },
                {grid.city: {grid.tile: grid}},
                expected_candidates=1,
            ).iloc[0]
            single = summarize_geometry_passes(
                candidates,
                multi_links.iloc[[0]].copy(),
                {(grid.city, 1, 1): empty_path},
                {grid.city: {grid.tile: grid}},
                expected_candidates=1,
            ).iloc[0]
        self.assertEqual(multi["n_view_valid_pixels"], 1)
        self.assertEqual(multi["l1b_geometry_status"], "geometry_pass")
        self.assertEqual(single["n_view_valid_pixels"], 0)
        self.assertEqual(single["view_valid_fraction"], 0.0)
        self.assertEqual(single["l1b_geometry_status"], "coverage_and_angle_fail")
        self.assertTrue(bool(single["l1b_geometry_complete"]))


class VersionAndBindingTests(unittest.TestCase):
    def test_d0048_bumps_algorithm_and_binds_mechanics(self) -> None:
        self.assertEqual(archive.IMPLEMENTATION_DECISION_ID, "D0048")
        self.assertEqual(
            archive.ALGORITHM_VERSION,
            "d0047-archive-available-l1b-dmrpp-pass-stream-v2",
        )
        fields = runner._d0048_geometry_binding_fields()
        self.assertEqual(fields["verified_no_overlap_locator_shape"], [176, 169])
        self.assertEqual(fields["verified_no_overlap_locator_expected_cells"], 29_744)
        self.assertEqual(fields["verified_no_overlap_locator_stride"], 32)
        self.assertEqual(
            fields["verified_no_overlap_locator_stride_minus_one_pixels"], 31
        )
        self.assertEqual(fields["verified_no_overlap_max_unsampled_path_pixels"], 62)
        self.assertEqual(
            fields["verified_no_overlap_maximum_adjacent_source_displacement_m"],
            100.0,
        )
        self.assertEqual(fields["verified_no_overlap_locator_uncertainty_m"], 6_200.0)
        self.assertEqual(fields["verified_no_overlap_locator_influence_m"], 8_000.0)
        self.assertEqual(fields["verified_no_overlap_boundary_guard_m"], 310.0)
        self.assertEqual(fields["verified_no_overlap_source_margin_pixels"], 64)

    def test_v1_pass_evidence_is_not_reused_under_v2(self) -> None:
        with tempfile.TemporaryDirectory(prefix="d0048-stale-evidence-") as temporary:
            evidence_root = Path(temporary)
            city, orbit = "phoenix", 1
            path = evidence_root / city / f"{orbit:05d}.json"
            path.parent.mkdir(parents=True)
            binding = {"algorithm_version": archive.ALGORITHM_VERSION}
            binding_hash = hashlib.sha256(
                json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            document = {
                "status": "complete",
                "decision_id": "D0047",
                "implementation_decision_id": "D0047",
                "algorithm_version": (
                    "d0047-archive-available-l1b-dmrpp-pass-stream-v1"
                ),
                "binding_sha256": binding_hash,
                "binding": binding,
                "boundary_verified": True,
                "city": city,
                "orbit": orbit,
                "scene_evidence": [{"boundary_verified": True}],
                "summary": {
                    "city": city,
                    "orbit": orbit,
                    "acquisition_utc": "2020-07-01T00:00:00+00:00",
                    "l1b_geometry_complete": True,
                    "decision_id": "D0047",
                },
            }
            path.write_text(json.dumps(document), encoding="utf-8")
            record = {
                "status": "complete",
                "boundary_verified": True,
                "evidence_path": str(path),
                "evidence_sha256": sha256_file(path),
                "binding_sha256": binding_hash,
            }
            with mock.patch.multiple(
                runner,
                PASS_EVIDENCE_DIR=evidence_root,
                DECISION_ID="D0047",
                IMPLEMENTATION_DECISION_ID="D0048",
                D0035_ALGORITHM_VERSION=archive.ALGORITHM_VERSION,
            ):
                self.assertFalse(
                    runner._pass_evidence_valid(
                        record,
                        binding_hash,
                        binding_payload={
                            **binding,
                            "city": city,
                            "orbit": orbit,
                            "acquisition_utc": "2020-07-01T00:00:00+00:00",
                        },
                    )
                )


if __name__ == "__main__":
    unittest.main()
