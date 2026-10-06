"""Network-free contract tests for illustrative Guide Steps 9--13."""

from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

import pandas as pd

from urban_cooling_v2.illustrative_steps09_13 import (
    BANNER,
    EXPECTED_ARTIFACT_IDS,
    write_steps09_13,
)


class IllustrativeSteps0913Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="illustrative-steps09-13-")
        cls.root = Path(cls.temporary.name)
        cls.artifacts = write_steps09_13(
            cls.root / "tables",
            cls.root / "figures",
            seed=20260805,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_complete_prefixed_nonempty_artifact_registry(self) -> None:
        self.assertEqual(
            set(self.artifacts),
            set(EXPECTED_ARTIFACT_IDS) | {"ANALYSIS_TABLE"},
        )
        for artifact_id, path in self.artifacts.items():
            with self.subTest(artifact_id=artifact_id):
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 100)
                self.assertTrue(path.name.startswith("ILLUSTRATIVE_"))
        self.assertEqual(
            sum(path.suffix == ".png" for path in self.artifacts.values()),
            27,
        )
        self.assertEqual(
            sum(path.suffix == ".csv" for path in self.artifacts.values()),
            12,
        )

    def test_tables_are_machine_labelled_and_use_only_generic_cities(self) -> None:
        forbidden = re.compile(
            r"phoenix|atlanta|miami|minneapolis|los[_ ]angeles",
            flags=re.IGNORECASE,
        )
        for artifact_id, path in self.artifacts.items():
            if path.suffix != ".csv":
                continue
            with self.subTest(artifact_id=artifact_id):
                frame = pd.read_csv(path)
                self.assertFalse(frame.empty)
                self.assertIn("data_origin", frame)
                self.assertIn("canonical_eligible", frame)
                self.assertEqual(set(frame["data_origin"].astype(str)), {"synthetic"})
                normalized = frame["canonical_eligible"].astype(str).str.casefold()
                self.assertEqual(set(normalized), {"false"})
                self.assertIsNone(forbidden.search(path.read_text(encoding="utf-8")))

        analysis = pd.read_csv(self.artifacts["ANALYSIS_TABLE"])
        self.assertTrue(analysis["city"].str.fullmatch(r"sim_city_[A-Za-z0-9_]+").all())
        self.assertEqual(analysis["city"].nunique(), 5)
        self.assertTrue({"night", "10-12", "16-18"}.issubset(set(analysis["time_stratum"])))
        outcome_like = [
            column
            for column in analysis
            if any(
                token in column.casefold()
                for token in ("cooling", "contrast", "benefit", "excess", "placebo")
            )
        ]
        self.assertTrue(outcome_like)
        self.assertTrue(all(column.startswith("synthetic_") for column in outcome_like))

    def test_figures_embed_the_visible_synthetic_warning(self) -> None:
        marker = BANNER.encode("utf-8")
        for artifact_id, path in self.artifacts.items():
            if path.suffix != ".png":
                continue
            with self.subTest(artifact_id=artifact_id):
                # The same string is both visibly drawn and stored as PNG Title
                # metadata, giving the test a stable machine-readable check.
                self.assertIn(marker, path.read_bytes())

    def test_numeric_outputs_are_defined_and_night_reverses(self) -> None:
        endpoint = pd.read_csv(self.artifacts["T10.1"])
        numeric = [
            "synthetic_late_minus_morning_k",
            "synthetic_ci_low_k",
            "synthetic_ci_high_k",
        ]
        self.assertFalse(endpoint[numeric].isna().any().any())
        analysis = pd.read_csv(self.artifacts["ANALYSIS_TABLE"])
        day_mean = analysis.loc[
            analysis["time_stratum"].ne("night"), "synthetic_cooling_contrast_k"
        ].mean()
        night_mean = analysis.loc[
            analysis["time_stratum"].eq("night"), "synthetic_cooling_contrast_k"
        ].mean()
        self.assertGreater(day_mean, 0)
        self.assertLess(night_mean, 0)


if __name__ == "__main__":
    unittest.main()
