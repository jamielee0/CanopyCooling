#!/usr/bin/env python3
"""Deterministic tests for the Guide Step-1 feasibility screen.

Run from the repository root with:

    python src/test_v2_step01_conditions.py
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

import numpy as np
import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parent))
from urban_cooling_v2 import step01_conditions as step1  # noqa: E402


def synthetic_daily(cities: tuple[str, ...] = ("Phoenix", "Atlanta")) -> pd.DataFrame:
    """Three complete buffered summers with plausible canonical gridMET units."""

    rows: list[dict[str, object]] = []
    for city_index, city in enumerate(cities):
        for year in (2018, 2019, 2020):
            dates = pd.date_range(f"{year}-04-01", f"{year}-09-30", freq="D")
            phase = np.arange(len(dates), dtype=float)
            for index, date in enumerate(dates):
                # Phoenix gets a clear July water-balance rise; the second city is
                # wetter throughout.  Values remain in the documented units.
                if city == "Phoenix":
                    pr = (0.1 if date.month < 7 else (8.0 if date.month == 7 else 1.5))
                    pr += 0.0001 * index + 0.002 * (year - 2018)
                    eto = 6.0 if date.month <= 7 else 5.0
                    vpd = 4.0 + 1.1 * np.sin(phase[index] / 18.0) + (year - 2018) * 0.03
                    tmmx = 313.0 + 4.0 * np.sin(phase[index] / 25.0)
                else:
                    pr = 4.0 + 2.2 * np.sin(phase[index] / 11.0)
                    eto = 4.5 + 0.5 * np.sin(phase[index] / 19.0)
                    vpd = 1.6 + 0.6 * np.cos(phase[index] / 17.0) + city_index * 0.02
                    tmmx = 303.0 + 3.0 * np.sin(phase[index] / 24.0)
                rows.append(
                    {
                        "city": city,
                        "date": date,
                        "pr_mm": pr,
                        "eto_mm": eto,
                        "vpd_kpa": vpd,
                        "tmmx_k": tmmx,
                        "clear_sky": (index + year + city_index) % 3 != 0,
                    }
                )
    return pd.DataFrame(rows)


def balanced_axes(cities: tuple[str, ...] = ("A", "B", "C")) -> pd.DataFrame:
    """All nine tercile cells equally represented, with both corners supported."""

    levels = {"low": 1.0 / 6.0, "middle": 0.5, "high": 5.0 / 6.0}
    rows: list[dict[str, object]] = []
    date = pd.Timestamp("2018-06-01")
    for city in cities:
        for demand_level, demand in levels.items():
            for dryness_level, dryness in levels.items():
                for replicate in range(10):
                    rows.append(
                        {
                            "city": city,
                            "date": date + pd.Timedelta(days=len(rows)),
                            "summer_year": 2018 + replicate % 3,
                            "clear_sky": True,
                            "demand_pct": demand + (replicate - 4.5) * 0.0001,
                            "antecedent_dryness_30d_pct": dryness + (4.5 - replicate) * 0.00007,
                            "demand_tercile_30d": demand_level,
                            "dryness_tercile_30d": dryness_level,
                            "off_diagonal_corner_30d": (demand_level, dryness_level)
                            in step1.OFF_DIAGONAL_CORNERS,
                        }
                    )
    return pd.DataFrame(rows)


class Step1ConditionsTests(unittest.TestCase):
    def test_no_lookahead_and_calendar_day_windows(self) -> None:
        dates = pd.date_range("2020-04-01", "2020-09-30", freq="D")
        base = pd.DataFrame(
            {
                "city": "Phoenix",
                "date": dates,
                "pr_mm": 1.0,
                "eto_mm": 2.0,
                "vpd_kpa": 4.0,
                "tmmx_k": 312.0,
            }
        )
        changed = base.copy()
        target = pd.Timestamp("2020-07-15")
        changed.loc[changed["date"] == target, "pr_mm"] = 101.0
        original_result = step1.add_antecedent_balances(base)
        changed_result = step1.add_antecedent_balances(changed)
        original_today = original_result.loc[original_result["date"] == target, "balance_30d_mm"].item()
        changed_today = changed_result.loc[changed_result["date"] == target, "balance_30d_mm"].item()
        self.assertEqual(original_today, -30.0)
        self.assertEqual(changed_today, original_today, "today's rain leaked into today's antecedent value")
        tomorrow = target + pd.Timedelta(days=1)
        delta = (
            changed_result.loc[changed_result["date"] == tomorrow, "balance_30d_mm"].item()
            - original_result.loc[original_result["date"] == tomorrow, "balance_30d_mm"].item()
        )
        self.assertEqual(delta, 100.0)

        with_gap = base.loc[base["date"] != pd.Timestamp("2020-07-10")]
        gap_result = step1.add_antecedent_balances(with_gap)
        self.assertTrue(
            pd.isna(
                gap_result.loc[
                    gap_result["date"] == pd.Timestamp("2020-07-20"),
                    "balance_30d_mm",
                ].item()
            ),
            "a missing calendar day was silently treated as a complete 30-day window",
        )

    def test_summer_filter_and_within_city_percentiles(self) -> None:
        axes = step1.prepare_condition_axes(synthetic_daily())
        self.assertTrue(axes["date"].dt.month.between(6, 9).all())
        self.assertEqual(set(axes["summer_year"]), {2018, 2019, 2020})
        for _, group in axes.groupby("city"):
            # Exact repeats legitimately share a mid-rank; all percentiles still
            # remain on [0, 1] and are centred on one half within each city.
            self.assertGreaterEqual(group["demand_pct"].min(), 0.0)
            self.assertLessEqual(group["demand_pct"].max(), 1.0)
            self.assertAlmostEqual(group["demand_pct"].mean(), 0.5)
            finite = group.dropna(subset=["balance_30d_mm", "antecedent_dryness_30d_pct"])
            wettest = finite["balance_30d_mm"].idxmax()
            driest = finite["balance_30d_mm"].idxmin()
            self.assertLessEqual(
                finite.loc[wettest, "antecedent_dryness_30d_pct"],
                finite.loc[driest, "antecedent_dryness_30d_pct"],
            )
        diagnostic = step1.percentile_uniformity_diagnostic(axes)
        self.assertTrue(diagnostic["pass"].all())

    def test_validation_rejects_bad_keys_and_columns(self) -> None:
        daily = synthetic_daily(("Phoenix",)).head(100)
        with self.assertRaisesRegex(ValueError, "missing required"):
            step1.prepare_condition_axes(daily.drop(columns="vpd_kpa"))
        duplicated = pd.concat([daily, daily.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "unique"):
            step1.prepare_condition_axes(duplicated)

    def test_spearman_bootstrap_resamples_whole_summers(self) -> None:
        rng = np.random.default_rng(17)
        frame = pd.DataFrame(
            {
                "summer_year": np.repeat([2018, 2019, 2020, 2021], 40),
                "demand_pct": np.tile(np.linspace(0, 1, 40), 4),
            }
        )
        signs = np.repeat([1.0, 1.0, -1.0, 1.0], 40)
        frame["antecedent_dryness_30d_pct"] = (
            0.5 + signs * (frame["demand_pct"] - 0.5) + rng.normal(0, 0.02, len(frame))
        )
        first = step1.summer_block_spearman(frame, n_boot=250, seed=91)
        second = step1.summer_block_spearman(frame, n_boot=250, seed=91)
        self.assertEqual(first, second)
        self.assertEqual(first["bootstrap_unit"], "whole_summer")
        self.assertEqual(first["n_summers"], 4)
        self.assertEqual(first["status"], "ok")
        self.assertLessEqual(first["ci_low"], first["spearman"])
        self.assertGreaterEqual(first["ci_high"], first["spearman"])

        one_summer = frame.loc[frame["summer_year"] == 2018]
        insufficient = step1.summer_block_spearman(one_summer, n_boot=10)
        self.assertEqual(insufficient["status"], "insufficient_summers")
        self.assertTrue(np.isnan(insufficient["ci_low"]))

    def test_permutation_is_deterministic_and_reports_null_position(self) -> None:
        frame = balanced_axes(("A",))
        one = step1.permutation_corner_test(frame, n_permutations=300, seed=7)
        two = step1.permutation_corner_test(frame, n_permutations=300, seed=7)
        self.assertEqual(one, two)
        self.assertEqual(one["n"], 90)
        self.assertGreaterEqual(one["observed_percentile"], 0.0)
        self.assertLessEqual(one["observed_percentile"], 1.0)
        self.assertGreaterEqual(one["two_sided_p"], 0.0)
        self.assertLessEqual(one["two_sided_p"], 1.0)

    def test_cell_table_has_all_nine_cells_and_honest_ci_metadata(self) -> None:
        axes = balanced_axes(("A",))
        table = step1.cell_count_table(axes, n_boot=50, seed=3)
        self.assertEqual(len(table), 18)  # nine cells x all/clear
        self.assertEqual(set(table["cell"]), {
            f"{demand}|{dryness}"
            for demand in step1.TERCILES
            for dryness in step1.TERCILES
        })
        all_rows = table.loc[table["subset"] == "all_days"]
        self.assertTrue((all_rows["count"] == 10).all())
        self.assertTrue((table["bootstrap_unit"] == "whole_summer").all())
        corner = table.loc[table["is_off_diagonal_corner"]]
        self.assertTrue((corner["proportion_ci_low"] <= corner["proportion"]).all())
        self.assertTrue((corner["proportion_ci_high"] >= corner["proportion"]).all())

    def test_gate_has_all_three_outcomes(self) -> None:
        strong = step1.evaluate_gate(balanced_axes())
        self.assertEqual(strong["decision"], "within_city_separation_may_be_possible")
        self.assertEqual(strong["n_cities_with_within_city_support"], 3)

        rows: list[dict[str, object]] = []
        for city in ("A", "B"):
            for index, value in enumerate(np.linspace(0, 1, 90)):
                level = "low" if value < 1 / 3 else ("middle" if value < 2 / 3 else "high")
                rows.append(
                    {
                        "city": city,
                        "clear_sky": True,
                        "demand_pct": value,
                        "antecedent_dryness_30d_pct": value,
                        "demand_tercile_30d": level,
                        "dryness_tercile_30d": level,
                    }
                )
        impossible = step1.evaluate_gate(pd.DataFrame(rows))
        self.assertEqual(impossible["decision"], "interaction_not_estimable")

        no_clear = balanced_axes(("A",)).assign(clear_sky=False)
        unavailable = step1.evaluate_gate(no_clear)
        self.assertEqual(unavailable["decision"], "insufficient_data")

    def test_domain_units_physics_and_window_diagnostics(self) -> None:
        daily = synthetic_daily()
        axes = step1.prepare_condition_axes(daily)
        domains = pd.DataFrame(
            {
                "city": ["Phoenix", "Atlanta"],
                "domain_source": ["Census Urban Area", "Census Urban Area"],
                "area_km2": [3000.0, 2500.0],
            }
        )
        record = step1.domain_record_table(axes, domains)
        self.assertEqual(len(record), 2)
        self.assertTrue((record["n_summer_days"] == 3 * 122).all())
        units = step1.unit_diagnostics(daily)
        self.assertTrue(units["plausible_range_pass"].all())
        phoenix_vpd = units.loc[
            (units["city"] == "Phoenix") & (units["band"] == "vpd_kpa"),
            "phoenix_summer_2_to_6_kpa_reference_pass",
        ].item()
        self.assertTrue(bool(phoenix_vpd))
        physical = step1.phoenix_water_balance_diagnostic(axes)
        self.assertTrue(physical["june_negative"].all())
        self.assertTrue(physical["july_rises_from_june"].all())
        agreement = step1.window_agreement_table(axes)
        self.assertEqual(set(agreement["city"]), {"Phoenix", "Atlanta"})

    def test_writer_creates_named_deliverables_and_checks(self) -> None:
        daily = synthetic_daily()
        domains = pd.DataFrame(
            {
                "city": ["Phoenix", "Atlanta"],
                "domain_source": ["2020 Census Urban Area", "2020 Census Urban Area"],
                "area_km2": [3000.0, 2500.0],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = step1.write_step1_deliverables(
                daily,
                domains,
                tmp,
                n_boot=30,
                n_permutations=40,
                strict_five_cities=False,
            )
            for key in ("F1.1", "F1.2", "F1.3", "F1.4", "T1.1", "T1.2", "M1.1", "C1", "C4", "C5", "C6"):
                self.assertTrue(Path(result[key]).is_file(), key)
            memo = Path(result["M1.1"]).read_text(encoding="utf-8")
            self.assertIn("provisional", memo.casefold())
            self.assertIn("Decision", memo)

    def test_wilson_interval_contains_observed_proportion(self) -> None:
        low, high = step1.wilson_interval(5, 20)
        self.assertLessEqual(low, 0.25)
        self.assertGreaterEqual(high, 0.25)
        self.assertTrue(np.isnan(step1.wilson_interval(0, 0)[0]))
        with self.assertRaises(ValueError):
            step1.wilson_interval(3, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
