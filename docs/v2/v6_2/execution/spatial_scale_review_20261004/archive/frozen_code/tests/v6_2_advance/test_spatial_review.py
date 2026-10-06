"""Independent known-answer checks; no network or empirical coefficient display."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from urban_cooling_v2.pooled_city_pass import SIGMA
from v6_2_advance.spatial_review import (
    PRECISION_FIELDS, block_stats, common_ids, identity_hash, joint_bootstrap,
    paired_scale, physical_groups, predictor_distribution, public_precision,
    reference_support, summary, validate_native_rows, write_sealed_json,
)
from v6_2_advance.run_spatial_review import Reader
from v6_2_advance.spatial_review import digest


def fixture():
    rows = []
    for block, slope, intercept in (("0_0", -3, 300), ("1_0", -6, 310), ("2_0", -10, 290)):
        for j, f in enumerate((.02, .08, .2, .5)):
            rows.append(dict(cell_id=f"{block}:{j}", block=block, canopy_fraction=f,
                             LST_K=intercept+slope*f, M_W_m2=2*intercept+4*slope*f))
    return pd.DataFrame(rows)


def explicit_fe(frame):
    labels = sorted(frame.block.unique())
    dummies = np.column_stack([frame.block.eq(b) for b in labels])
    design = np.column_stack([dummies, frame.canopy_fraction.to_numpy()])
    return np.linalg.lstsq(design, frame[["LST_K", "M_W_m2"]].to_numpy(), rcond=None)[0][-1]


class SpatialReviewTests(unittest.TestCase):
    def test_block_statistics_equal_independent_fixed_effect_ols(self):
        f = fixture()
        stat = block_stats(f, ["canopy_fraction"])
        np.testing.assert_allclose(stat.solve()[0], explicit_fe(f), atol=1e-10)
        self.assertAlmostEqual(stat.solve()[0, 0], -19/3)

    def test_repeated_blocks_use_fresh_intercepts(self):
        f = fixture()
        stat = block_stats(f, ["canopy_fraction"])
        draws = []
        for k, b in enumerate(("0_0", "0_0", "2_0")):
            q = f[f.block.eq(b)].copy()
            q["block"] = str(k)
            draws.append(q)
        np.testing.assert_allclose(stat.solve([2, 0, 1])[0], explicit_fe(pd.concat(draws)), atol=1e-10)

    def test_joint_multiplicities_match_explicit_union_draws(self):
        original = fixture()
        common = original[original.block.ne("2_0")].copy()
        a, b = [block_stats(f, ["canopy_fraction"]) for f in (original, common)]
        joint = joint_bootstrap(a, b, replicates=12, seed=17)
        rng = np.random.default_rng(17)
        for i in range(12):
            counts = rng.multinomial(3, np.full(3, 1/3))
            direct = []
            for f in (original, common):
                selected = []
                for block, n in zip(a.labels, counts):
                    for instance in range(n):
                        part = f[f.block.eq(block)].copy()
                        part["block"] = f"{block}:draw{instance}"
                        if len(part): selected.append(part)
                direct.append(-.1*explicit_fe(pd.concat(selected)) if selected else np.array([np.nan, np.nan]))
            if np.isfinite(direct).all(): np.testing.assert_allclose(joint["draws"][i], direct, atol=1e-10)
            else: self.assertFalse(joint["valid"][i])
        self.assertEqual(joint["groups"], 3)

    def test_identical_support_has_zero_joint_difference(self):
        s = block_stats(fixture(), ["canopy_fraction"])
        result = joint_bootstrap(s, s, replicates=15, seed=21)
        self.assertTrue(result["valid"].all())
        np.testing.assert_array_equal(result["difference_draws"], 0)

    def test_union_draw_identity_is_deterministic_and_seed_specific(self):
        s = block_stats(fixture(), ["canopy_fraction"])
        a = joint_bootstrap(s, s, replicates=10, seed=2)
        b = joint_bootstrap(s, s, replicates=10, seed=2)
        c = joint_bootstrap(s, s, replicates=10, seed=3)
        self.assertEqual(a["draw_multiplicity_sha256"], b["draw_multiplicity_sha256"])
        self.assertNotEqual(a["draw_multiplicity_sha256"], c["draw_multiplicity_sha256"])

    def test_groups_are_physical_not_row_order_or_pixel_counts(self):
        np.testing.assert_array_equal(physical_groups(["8_8", "15_8", "-1_0"], 8), ["1_1", "1_1", "-1_0"])
        self.assertEqual(identity_hash(["b", "a"]), identity_hash(["a", "b"]))
        with self.assertRaises(ValueError): physical_groups(["0_0"], 2)

    def test_rank_failure_is_reported_without_removing_controls(self):
        f = fixture()
        f["control"] = f.canopy_fraction*2
        with self.assertRaisesRegex(ValueError, "not estimable"): block_stats(f, ["canopy_fraction", "control"])

    def test_duplicate_ground_cells_and_wrong_blocks_are_rejected(self):
        f = pd.DataFrame(dict(cell_id=["a", "b"], native_crs=["EPSG:32612"]*2,
                             native_x=[70, 140], native_y=[70, 70], x=[70, 140], y=[70, 70], block=["0_0"]*2))
        validate_native_rows(f)
        f.loc[1, "native_x"] = 70
        with self.assertRaisesRegex(ValueError, "Duplicate ground"): validate_native_rows(f)
        f.loc[1, "native_x"] = 140
        f.loc[1, "block"] = "1_0"
        with self.assertRaisesRegex(ValueError, "Physical block"): validate_native_rows(f)

    def test_intersection_and_empty_support_remain_explicit(self):
        a = pd.DataFrame({"cell_id": ["c", "a", "b"]})
        b = pd.DataFrame({"cell_id": ["d", "a"]})
        self.assertEqual(common_ids([a, b]), ["a"])
        self.assertEqual(common_ids([a, pd.DataFrame({"cell_id": ["z"]})]), [])
        with self.assertRaises(ValueError): common_ids([a, pd.DataFrame({"cell_id": ["a", "a"]})])

    def test_exact_fourth_root_and_matched_draws_known_answer(self):
        ref, eps = 300, .95
        change = -2
        delta_flux = eps*SIGMA*((ref+change)**4-ref**4)
        temp_draws = np.array([-1, -2, -3.])
        flux_draws = eps*SIGMA*((ref+temp_draws)**4-ref**4)
        result, values = paired_scale(change, delta_flux, np.column_stack([temp_draws, flux_draws]), ref, eps)
        np.testing.assert_allclose(result["point"], [2, 2], atol=1e-12)
        np.testing.assert_allclose(values[:, 0], values[:, 1], atol=1e-12)
        self.assertAlmostEqual(result["paired_T_minus_equivalent"]["SE"], 0, places=11)
        linear_equivalent = -delta_flux/(4*eps*SIGMA*ref**3)
        self.assertGreater(abs(linear_equivalent-2), .01)

    def test_nonpositive_transform_anchor_is_not_rescued(self):
        ref, eps = 300, .95
        result, values = paired_scale(-1, -eps*SIGMA*ref**4-1, np.array([[-1, 0], [-2, 0]]), ref, eps)
        self.assertEqual(result["status"], "NOT_ESTIMABLE_AT_REFERENCE")
        self.assertIsNone(values)

    def test_reference_requires_actual_raw_endpoint_support(self):
        f = fixture()
        mask, r = reference_support(f, .1, .2)
        self.assertEqual(r["supporting_blocks"], 3)
        self.assertEqual(mask.sum(), 12)
        _, r = reference_support(f, .7, .8)
        self.assertEqual(r["status"], "NOT_SUPPORTED_NO_REFERENCE_BLOCKS")

    def test_distributions_preserve_zero_and_never_impose_canopy_floor(self):
        r = predictor_distribution([0, .001, .002, 1])
        self.assertEqual(r["n"], 4)
        self.assertEqual(r["q00"], 0)
        self.assertAlmostEqual(r["q50"], .0015)
        self.assertIsNone(predictor_distribution([])["q50"])

    def test_summaries_do_not_treat_incomplete_pairs_as_valid(self):
        result = summary([0, 0], [[1, np.nan], [2, 3]])
        self.assertEqual(result["status"], "NOT_ESTIMABLE")
        self.assertEqual(result["estimable"], 1)

    def test_public_precision_cannot_carry_effect_or_interval_endpoints(self):
        row = {k: None for k in PRECISION_FIELDS}
        row["effect_status"] = "SEALED_USER_REQUEST"
        self.assertEqual(public_precision(row), row)
        for key in ("point", "q025", "cooling_change"):
            with self.assertRaisesRegex(ValueError, "sensitive"): public_precision(dict(row, **{key: 1}))

    def test_sealed_writer_guards_root_label_and_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            p = write_sealed_json(root, "review", "comparison_SEALED.json", {"known_synthetic_effect": 1})
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertEqual(p.parent.stat().st_mode & 0o777, 0o700)
            with self.assertRaises(ValueError): write_sealed_json(root, "review", "comparison.json", {})
            with self.assertRaises(ValueError): write_sealed_json(root, "../scientific", "comparison_SEALED.json", {})

    def test_minimal_stress_archive_metadata_requires_identical_mean_model(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); (root/"data").mkdir()
            base_name = "outputs/v6_2/sealed_coefficients/r/7_paired_primary_SEALED.npz"
            stress_name = base_name.replace("paired_primary", "spatial_8km")
            base = root/base_name; base.parent.mkdir(parents=True)
            coef = np.array([[-3., -12.]])
            bootstrap = np.repeat(coef[None, :, :], 1000, axis=0)
            np.savez(base, coefficients=coef, bootstrap_coefficients=bootstrap,
                predictor_names=["canopy_fraction"], outcome_names=["LST_K", "M_W_m2"], block_labels=["0_0", "1_0"],
                block_x_means=[[.1], [.2]], block_y_means=[[300, 500], [310, 510]])
            np.savez(root/stress_name, coefficients=coef, bootstrap_coefficients=bootstrap)
            freeze = dict(data_link_target=str(root/"data"), inputs=[dict(path=p, sha256=digest(root/p)) for p in (base_name, stress_name)])
            with patch("v6_2_advance.run_spatial_review.ROOT", root):
                reader = Reader(freeze)
                recovered = reader.model(stress_name)
                np.testing.assert_array_equal(recovered["predictor_names"], ["canopy_fraction"])
                np.savez(root/stress_name, coefficients=coef+.1, bootstrap_coefficients=bootstrap)
                freeze["inputs"][1]["sha256"] = digest(root/stress_name)
                with self.assertRaisesRegex(ValueError, "differs"): Reader(freeze).model(stress_name)


if __name__ == "__main__": unittest.main()
