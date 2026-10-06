#!/usr/bin/env python3
"""Focused tests for the six quarantined synthetic Step-14 figures."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from urban_cooling_v2.illustrative_step14_figures import (
    DAY_STRATA,
    EXPECTED_IDS,
    WATERMARK,
    _pass_means,
    _radiatively_standardize,
    _stratified_surfaces,
    _surface,
    write_step14_figures,
)
from urban_cooling_v2.illustrative_steps02_08 import generate_synthetic_data


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class IllustrativeStep14FigureTests(unittest.TestCase):
    def test_f14_3_surfaces_are_time_stratified_and_mask_unsupported_cells(
        self,
    ) -> None:
        _, matched = generate_synthetic_data(seed=20260805)
        pass_level = _pass_means(matched)
        stratified = _stratified_surfaces(pass_level, bins=4)

        self.assertEqual(tuple(stratified), DAY_STRATA)
        for stratum, (surface, support) in stratified.items():
            self.assertEqual(surface.shape, (4, 4), stratum)
            self.assertEqual(support.shape, (4, 4), stratum)
            np.testing.assert_array_equal(
                np.ma.getmaskarray(surface), support < 2
            )
            self.assertGreater(int((support >= 2).sum()), 0, stratum)

        # Atmospheric-demand values are not a hidden substitute for the
        # requested synthetic crown-area axis.
        first_stratum = pass_level.loc[
            pass_level["time_stratum"].eq(DAY_STRATA[0])
        ].copy()
        baseline_surface, baseline_support = _surface(first_stratum, bins=4)
        first_stratum["synthetic_demand_pct"] = (
            1.0 - first_stratum["synthetic_demand_pct"]
        )
        changed_surface, changed_support = _surface(first_stratum, bins=4)
        np.testing.assert_array_equal(baseline_support, changed_support)
        np.testing.assert_allclose(
            baseline_surface.filled(np.nan),
            changed_surface.filled(np.nan),
            equal_nan=True,
        )

    def test_f14_4_uses_explicit_synthetic_radiative_standardization(self) -> None:
        _, matched = generate_synthetic_data(seed=20260805)
        work = _radiatively_standardize(matched)

        reference_proxy = np.clip(
            0.27 - 0.10 * matched["synthetic_reference_canopy_fraction"],
            0.08,
            0.36,
        )
        albedo_difference = reference_proxy - matched["synthetic_albedo"]
        penalty = (
            albedo_difference
            * matched["synthetic_incoming_radiation_w_m2"]
            / 100.0
        )
        np.testing.assert_allclose(
            work["_synthetic_reference_albedo_proxy"], reference_proxy
        )
        np.testing.assert_allclose(
            work["_synthetic_albedo_difference_reference_minus_tree"],
            albedo_difference,
        )
        np.testing.assert_allclose(
            work["_synthetic_radiative_penalty_k"], penalty
        )
        np.testing.assert_allclose(
            work["_synthetic_radiatively_standardized_contrast_k"],
            matched["synthetic_cooling_contrast_k"] + penalty,
        )
        self.assertGreater(float(np.abs(penalty).max()), 0.0)

    def test_writes_exactly_six_deterministic_watermarked_figures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = write_step14_figures(
                root / "data_a", root / "figures_a", seed=20260805
            )
            second = write_step14_figures(
                root / "data_b", root / "figures_b", seed=20260805
            )
            self.assertEqual(tuple(first), EXPECTED_IDS)
            self.assertEqual(tuple(second), EXPECTED_IDS)
            self.assertEqual(len(first), 6)
            self.assertFalse((root / "data_a").exists())
            self.assertFalse((root / "data_b").exists())

            first_ids: list[str] = []
            for index, artifact_id in enumerate(EXPECTED_IDS, start=1):
                path = first[artifact_id]
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 10_000)
                self.assertEqual(path.suffix, ".png")
                expected_prefix = (
                    f"ILLUSTRATIVE_F14.{index}_PAPER_FIGURE_{index}_"
                )
                self.assertTrue(path.name.startswith(expected_prefix), path.name)
                self.assertIn(WATERMARK.encode("utf-8"), path.read_bytes())
                self.assertEqual(_sha256(path), _sha256(second[artifact_id]))
                first_ids.extend(
                    candidate for candidate in EXPECTED_IDS if candidate in path.name
                )
            self.assertEqual(first_ids, list(EXPECTED_IDS))
            self.assertEqual(
                len(list((root / "figures_a").glob("*.png"))), 6
            )

    def test_reuses_exact_saved_synthetic_tables_and_rejects_real_city(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_root = root / "illustrative_data"
            data_root.mkdir()
            pass_df, matched_df = generate_synthetic_data(seed=20260805)
            pass_path = data_root / "ILLUSTRATIVE_synthetic_passes.csv"
            matched_path = data_root / "ILLUSTRATIVE_synthetic_matched_sets.csv"
            pass_df.to_csv(pass_path, index=False)
            matched_df.to_csv(matched_path, index=False)

            with patch(
                "urban_cooling_v2.illustrative_step14_figures.generate_synthetic_data",
                side_effect=AssertionError("saved tables should be reused"),
            ):
                artifacts = write_step14_figures(
                    data_root, root / "figures", seed=20260805
                )
            self.assertEqual(tuple(artifacts), EXPECTED_IDS)

            hostile = matched_df.copy()
            hostile.loc[hostile.index[0], "city"] = "phoenix"
            hostile.to_csv(matched_path, index=False)
            with self.assertRaisesRegex(ValueError, "generic sim_city"):
                write_step14_figures(
                    data_root, root / "rejected_figures", seed=20260805
                )
            self.assertFalse((root / "rejected_figures").exists())

    def test_refuses_a_partial_saved_source_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.mkdir(exist_ok=True)
            pass_df, _ = generate_synthetic_data(seed=20260805)
            pass_df.to_csv(
                root / "ILLUSTRATIVE_synthetic_passes.csv", index=False
            )
            with self.assertRaisesRegex(FileNotFoundError, "both saved"):
                write_step14_figures(root, root / "figures", seed=20260805)
            self.assertFalse((root / "figures").exists())


if __name__ == "__main__":
    unittest.main()
