"""Network-free known-answer tests for the exploratory curve visualization."""
from pathlib import Path
import sys
import unittest
import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from v6_2_advance.nonlinear_association import (
    CONTEXT, spline_basis, fit_curve, curve_difference, partial_cooling,
    spatial_groups, linear_check, summarize_bins,
)

KNOTS = [.05, .25, .55, .9]


def fixture(curved=True, noise=False):
    rng = np.random.default_rng(55)
    block = np.repeat(np.arange(32), 50)
    f = rng.uniform(.01, .99, len(block))
    x = rng.normal(size=(len(f), 6)) + .5*f[:, None]
    coef = np.array([-3., 1.7, -1.2]) if curved else np.array([-3., 0., 0.])
    y = 300 + .5*block + x @ np.array([.3, .2, -.4, 1.1, .7, -.9]) + spline_basis(f, KNOTS) @ coef
    if noise:
        y += rng.normal(0, .2, len(y))
    d = pd.DataFrame(x, columns=CONTEXT)
    d["canopy_fraction"] = f
    d["block"] = block.astype(str)
    d["cell_id"] = [f"cell_{i}" for i in range(len(f))]
    d["x"] = block*8000 + rng.uniform(0, 900, len(f))
    d["y"] = 100.0
    d["LST_K"] = y
    d["M_W_m2"] = 2*y + 30
    return d, coef


class NonlinearTests(unittest.TestCase):
    def test_basis_agrees_with_independent_natural_cubic_interpolator(self):
        x = np.linspace(KNOTS[0], KNOTS[-1], 101)
        natural = CubicSpline(KNOTS, spline_basis(KNOTS, KNOTS), bc_type="natural")
        np.testing.assert_allclose(spline_basis(x, KNOTS), natural(x), atol=1e-12)

    def test_linear_tails_and_invalid_knots(self):
        for x in [np.array([-.3, -.2, -.1]), np.array([1.1, 1.2, 1.3])]:
            np.testing.assert_allclose(np.diff(spline_basis(x, KNOTS), n=2, axis=0), 0, atol=1e-12)
        with self.assertRaises(ValueError):
            spline_basis([.1], [.1, .1, .3, .8])

    def test_curved_signal_recovery_with_block_and_context_confounding(self):
        d, coef = fixture()
        transformed, fit = fit_curve(d, KNOTS, replicates=40)
        x = np.linspace(.05, .9, 40)
        expected = -(spline_basis(x, KNOTS)-spline_basis([.2], KNOTS)) @ coef
        point, draws = curve_difference(fit, KNOTS, x, .2)
        np.testing.assert_allclose(point[:, 0], expected, atol=1e-10)
        np.testing.assert_allclose(draws[:, :, 0], np.broadcast_to(expected, draws[:, :, 0].shape), atol=1e-9)
        expected_partial = -(spline_basis(d.canopy_fraction, KNOTS)-spline_basis([.2], KNOTS)) @ coef
        np.testing.assert_allclose(partial_cooling(transformed, fit, KNOTS, .2), expected_partial, atol=1e-10)

    def test_true_linear_association_stays_linear_and_units(self):
        d, _ = fixture(curved=False)
        transformed, fit = fit_curve(d, KNOTS, replicates=30)
        point, _ = curve_difference(fit, KNOTS, [.2, .21, .3], .2)
        np.testing.assert_allclose(point[:, 0], [0, .03, .3], atol=1e-10)
        np.testing.assert_allclose(linear_check(transformed, fit)[0], [-3, -6], atol=1e-10)

    def test_paired_resampling_and_reference_zero(self):
        d, _ = fixture(noise=True)
        _, fit = fit_curve(d, KNOTS, replicates=40)
        point, draws = curve_difference(fit, KNOTS, [.2, .6], .2)
        np.testing.assert_allclose(point[0], 0)
        np.testing.assert_allclose(draws[:, 0], 0)
        np.testing.assert_allclose(draws[:, :, 1], 2*draws[:, :, 0], atol=1e-9)
        self.assertGreater(np.std(draws[:, 1, 0]), 0)
        self.assertEqual(fit.diagnostics["resampling_groups"], 32)

    def test_duplicate_cells_and_split_block_rejected(self):
        d, _ = fixture()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            spatial_groups(pd.concat([d, d.iloc[:1]], ignore_index=True))
        d.loc[0, "x"] = 16000
        with self.assertRaisesRegex(ValueError, "crosses"):
            spatial_groups(d)

    def test_bin_endpoints_and_empty_bins_preserved(self):
        d = pd.DataFrame({"canopy_fraction": [.1, .2, .4], "LST_K": [300, 301, 303], "block": ["a", "a", "b"]})
        rows = summarize_bins(d, np.array([0, 1, 3]), [.1, .2, .3, .4, .5])
        self.assertEqual([r["n_cells"] for r in rows], [1, 1, 0, 1])
        self.assertTrue(np.isnan(rows[2]["mean_canopy"]))


if __name__ == "__main__":
    unittest.main()
