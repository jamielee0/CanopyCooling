import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from urban_cooling_v2.pooled_city_pass import CONTEXT, emitted_energy, temperature_equivalent
from v6_2_advance.canopy_support import resampled_design_rank
from v6_2_advance.spatial_review import validate_native_rows
from v6_2_advance.quadratic_sensitivity import (
    fit_model, paired_bootstrap, basis_delta, contrast, endpoint_averages,
    cooling_quantities, summarize, public_precision, write_sealed_json,
)


def fixture(controls=False):
    rng = np.random.default_rng(712)
    rows = []
    for block in range(6):
        for j, f in enumerate(np.linspace(.01, .45, 20) + block*.025):
            row = dict(block=f"{block*8}_0", canopy_fraction=f,
                       LST_K=305+block*3-5*f+2*f*f, M_W_m2=440+block*7-30*f+9*f*f)
            for k, name in enumerate(CONTEXT):
                row[name] = rng.normal()
                if controls:
                    row["LST_K"] += row[name]*(k+1)*.1
                    row["M_W_m2"] += row[name]*(k+1)*.5
            rows.append(row)
    return pd.DataFrame(rows)


class QuadraticSensitivityTests(unittest.TestCase):
    def test_known_curve_with_six_controls_and_block_intercepts(self):
        frame = fixture(True)
        fit = fit_model(frame, quadratic=True)
        np.testing.assert_allclose(fit.coefficients[:2], [[-5, -30], [2, 9]], atol=1e-10)
        point, _ = contrast(fit, fit.coefficients[None], .1, .2)
        np.testing.assert_allclose(-point, [.44, 2.73], atol=1e-11)
        self.assertEqual(fit.design.diagnostics["removed_context_terms"], [])

    def test_independent_dummy_variable_regression(self):
        f = fixture(True)
        fit = fit_model(f, quadratic=True)
        x = np.column_stack((f.canopy_fraction, f.canopy_fraction**2, f[list(CONTEXT)],
                             pd.get_dummies(f.block).astype(float)))
        b = np.linalg.lstsq(x, f[["LST_K", "M_W_m2"]], rcond=None)[0]
        np.testing.assert_allclose(fit.coefficients, b[:8], atol=1e-10)

    def test_linear_nesting(self):
        f = fixture()
        f.LST_K = 305 + np.repeat(np.arange(6)*3, 20) - 5*f.canopy_fraction
        fit = fit_model(f, quadratic=True, context=())
        np.testing.assert_allclose(fit.coefficients[:, 0], [-5, 0], atol=1e-10)

    def test_endpoint_predictions_update_square_and_fixed_weights(self):
        f = fixture(True)
        fit = fit_model(f, quadratic=True)
        means = endpoint_averages(fit, f, .15, .25, np.arange(1, len(f)+1))
        point, _ = contrast(fit, fit.coefficients[None], .15, .25)
        np.testing.assert_allclose(means[1]-means[0], point, atol=1e-11)
        self.assertAlmostEqual(-point[0], .42)
        with self.assertRaises(ValueError): endpoint_averages(fit, f, .8, .9)
        bad = f.copy(); bad.block = "unknown"
        with self.assertRaises(ValueError): endpoint_averages(fit, bad, .15, .25)

    def test_square_centering_order(self):
        f = fixture(); fit = fit_model(f, quadratic=True, context=())
        raw = f.canopy_fraction.to_numpy()
        centered = raw-f.groupby("block").canopy_fraction.transform("mean").to_numpy()
        wrong = centered**2
        wrong -= pd.Series(wrong).groupby(f.block).transform("mean").to_numpy()
        y = f.LST_K-f.groupby("block").LST_K.transform("mean")
        x = np.column_stack((centered, wrong))
        self.assertGreater(np.linalg.norm(y-x@np.linalg.lstsq(x, y, rcond=None)[0]), .05)
        self.assertEqual(fit.design.names, ("canopy_fraction", "canopy_squared"))

    def test_whole_group_bootstrap_matches_explicit_resampled_blocks(self):
        f = fixture(True)
        linear, quad = [fit_model(f, quadratic=q) for q in (False, True)]
        draws, audit = paired_bootstrap(linear, quad, group_km=8, replicates=6, seed=47)
        expected = resampled_design_rank(linear.design, quad.design, size=8, replicates=6, seed=47)
        self.assertEqual(audit, expected)
        groups = np.unique([f"{int(x.split('_')[0])//8}_0" for x in quad.design.block_labels])
        rng = np.random.default_rng(47)
        for r in range(6):
            counts = rng.multinomial(6, np.full(6, 1/6))
            parts = []
            for g, count in zip(groups, counts):
                block = f"{int(g.split('_')[0])*8}_0"
                for copy in range(count):
                    part = f[f.block.eq(block)].copy(); part.block = f"{block}_{copy}"; parts.append(part)
            repeated = pd.concat(parts, ignore_index=True)
            for j, q in enumerate((False, True)):
                refit = fit_model(repeated, quadratic=q)
                np.testing.assert_allclose(draws[j][r], refit.coefficients, atol=1e-9)

    def test_failed_draws_are_retained_without_rescue(self):
        f = fixture(); f["sparse"] = 0.
        f.loc[:19, "sparse"] = np.sin(np.arange(20))
        linear, quad = [fit_model(f, quadratic=q, context=("sparse",)) for q in (False, True)]
        draws, audit = paired_bootstrap(linear, quad, group_km=8, replicates=100, seed=17)
        self.assertGreater(audit["paired_failed"], 0)
        self.assertEqual(audit["paired_estimable"]+audit["paired_failed"], 100)
        self.assertTrue(np.isnan(draws[1][audit["quadratic_failed_indices"]]).all())

    def test_protected_quadratic_and_missing_outcome_fail(self):
        f = fixture(); f["confounder"] = f.canopy_fraction**2
        with self.assertRaises(ValueError): fit_model(f, quadratic=True, context=("confounder",))
        f.loc[0, "LST_K"] = np.nan
        with self.assertRaisesRegex(ValueError, "paired outcomes"): fit_model(f, quadratic=True, context=())

    def test_exact_reference_transform_and_invalid_draw_accounting(self):
        tref, e = 300., .95
        change = emitted_energy(299., e)-emitted_energy(tref, e)
        values = cooling_quantities(np.array([[-1., change], [-1., -1000.]]), tref, e)
        np.testing.assert_allclose(values[0, [0, 2, 3]], [1, 1, 0], atol=1e-10)
        self.assertTrue(np.isnan(values[1, 2])); self.assertEqual(values[1, 0], 1)
        delta = np.array([-50., 30.])
        self.assertNotAlmostEqual(float(temperature_equivalent(delta.mean(), tref, e)),
                                 float(temperature_equivalent(delta, tref, e).mean()), places=5)

    def test_paired_difference_uses_covariance(self):
        a = np.arange(10.)
        result = summarize(2., a+2-a)
        self.assertEqual(result["SE"], 0.)
        self.assertEqual(result["q025"], 2.)
        self.assertEqual(summarize(0., [np.nan, 1.])["status"], "NOT_ESTIMABLE")

    def test_native_identity_and_physical_block_validation(self):
        f = pd.DataFrame(dict(cell_id=["a", "b"], native_crs=[1, 1], native_x=[0, 70],
                              native_y=[0, 0], x=[100., 170.], y=[100., 100.], block=["0_0", "0_0"]))
        validate_native_rows(f)
        with self.assertRaises(ValueError): validate_native_rows(pd.concat([f, f]))
        f.loc[0, "block"] = "1_0"
        with self.assertRaises(ValueError): validate_native_rows(f)

    def test_output_allowlist_and_private_file_permissions(self):
        row = dict(city="a", orbit=1, date="2023-01-01", pair_id="historical", f0=.1, f1=.2,
                   group_km=8, model="quadratic", quantity="temperature", units="K", requested=10,
                   estimable=10, failed=0, SE=.1, width95=.4, effect_status="SEALED_USER_REQUEST",
                   support_status="BLOCK_RANGE_ONLY")
        self.assertEqual(public_precision(row), row)
        for sensitive in ("point", "q025", "coefficients", "p_value", "significant"):
            with self.assertRaises(ValueError): public_precision({**row, sensitive: 1})
        with tempfile.TemporaryDirectory() as folder:
            p = write_sealed_json(folder, "run", "result_SEALED.json", {"point": 9})
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertEqual(p.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(json.loads(p.read_text())["point"], 9)
            with self.assertRaises(ValueError): write_sealed_json(folder, "run", "public.json", {})
            with self.assertRaises(FileExistsError): write_sealed_json(folder, "run", "result_SEALED.json", {})


if __name__ == "__main__": unittest.main()
