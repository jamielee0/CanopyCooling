#!/usr/bin/env python3
"""Network-free tests for the synthetic-only Steps 4--8 illustrations."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from urban_cooling_v2.illustrative_steps02_08 import (
    DEFAULT_SEED,
    SIM_CITIES,
    WATERMARK,
    generate_synthetic_data,
    write_steps04_08,
)


class IllustrativeSteps0408Tests(unittest.TestCase):
    def test_generator_is_deterministic_generic_and_explicitly_synthetic(self) -> None:
        passes_a, matched_a = generate_synthetic_data(DEFAULT_SEED)
        passes_b, matched_b = generate_synthetic_data(DEFAULT_SEED)
        assert_frame_equal(passes_a, passes_b, check_exact=True)
        assert_frame_equal(matched_a, matched_b, check_exact=True)

        self.assertEqual(set(passes_a["city"]), set(SIM_CITIES))
        self.assertEqual(set(matched_a["city"]), set(SIM_CITIES))
        self.assertTrue(passes_a["data_origin"].eq("synthetic").all())
        self.assertTrue(matched_a["data_origin"].eq("synthetic").all())
        self.assertFalse(passes_a["canonical_eligible"].any())
        self.assertFalse(matched_a["canonical_eligible"].any())
        self.assertEqual(len(passes_a), 120)
        self.assertEqual(len(matched_a), 960)

        by_city = passes_a.groupby("city")["time_stratum"].agg(set)
        for strata in by_city:
            self.assertIn("night", strata)
            self.assertIn("10-12", strata)
            self.assertIn("16-18", strata)

        structural = {
            "data_origin",
            "canonical_eligible",
            "city",
            "year",
            "time_stratum",
        }
        for frame in (passes_a, matched_a):
            unprefixed = [
                column
                for column in frame.columns
                if column not in structural and not column.startswith("synthetic_")
            ]
            self.assertEqual(unprefixed, [])
        for required_outcome in (
            "synthetic_tree_lst_k",
            "synthetic_reference_lst_k",
            "synthetic_cooling_contrast_k",
        ):
            self.assertIn(required_outcome, matched_a)

    def test_writer_emits_every_prefixed_artifact_with_labels(self) -> None:
        expected = {
            *(f"F4.{index}" for index in range(1, 7)),
            *(f"T4.{index}" for index in range(1, 4)),
            *(f"F5.{index}" for index in range(1, 7)),
            *(f"T5.{index}" for index in range(1, 3)),
            *(f"F6.{index}" for index in range(1, 6)),
            *(f"T6.{index}" for index in range(1, 3)),
            *(f"F7.{index}" for index in range(1, 6)),
            *(f"T7.{index}" for index in range(1, 3)),
            *(f"F8.{index}" for index in range(1, 8)),
            *(f"T8.{index}" for index in range(1, 4)),
            "synthetic_pass_dataset",
            "synthetic_matched_dataset",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_root = root / "tables"
            figure_root = root / "figures"
            artifacts = write_steps04_08(
                output_root, figure_root, seed=DEFAULT_SEED
            )
            self.assertEqual(set(artifacts), expected)
            self.assertEqual(len(artifacts), 43)

            for artifact_id, path in artifacts.items():
                self.assertTrue(path.is_file(), artifact_id)
                self.assertGreater(path.stat().st_size, 100, artifact_id)
                self.assertTrue(path.name.startswith("ILLUSTRATIVE_"), path.name)
                if artifact_id.startswith("F"):
                    self.assertEqual(path.suffix, ".png")
                    self.assertIn(WATERMARK.encode("utf-8"), path.read_bytes())
                else:
                    table = pd.read_csv(path)
                    self.assertIn("data_origin", table)
                    self.assertIn("canonical_eligible", table)
                    self.assertTrue(table["data_origin"].eq("synthetic").all())
                    canonical = table["canonical_eligible"].astype(str).str.casefold()
                    self.assertTrue(canonical.eq("false").all())
                    if "city" in table:
                        self.assertTrue(set(table["city"]).issubset(SIM_CITIES))

            emitted = {
                path.resolve()
                for path in (*output_root.glob("*"), *figure_root.glob("*"))
                if path.is_file()
            }
            self.assertEqual(emitted, {path.resolve() for path in artifacts.values()})


if __name__ == "__main__":
    unittest.main()
