#!/usr/bin/env python3
"""Self-test for Section 14b (pixel-level mixed-effects model + BG cluster bootstrap).

Mirrors the hand-rolled ``check(cond, msg)`` harness of the other section tests (NOT
pytest). The module imports with numpy + pandas only; ``statsmodels`` is pinned but its import
is GUARDED, so the PURE-helper tests (centering, within-between decomposition, cluster
resampling, dominant-BG down-weighting) ALWAYS run, while the model tests (fit + cluster-CI)
SKIP cleanly (recorded green) when statsmodels is absent.

Run: python src/test_section14b_mixed_effects.py
"""

from __future__ import annotations

import importlib
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
m = importlib.import_module("section14b_mixed_effects")

HAVE_STATSMODELS = m.HAVE_STATSMODELS

_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


# --- Pure helpers (always run) ---------------------------------------------- #
def test_group_mean_centering() -> None:
    """_within sums to ~0 per group; _bg_mean is the group mean; _within + _bg_mean == x."""
    print("\n[group_mean_center: Mundlak/CWC within-between decomposition]")
    df = pd.DataFrame({
        "neighborhood_id": ["a", "a", "a", "b", "b"],
        "x": [1.0, 3.0, 5.0, 10.0, 20.0],
    })
    bg_mean, within = m.group_mean_center(df, "x", "neighborhood_id")
    check(bg_mean.name == "x_bg_mean" and within.name == "x_within",
          "returns Series named x_bg_mean and x_within")
    # group a mean = 3.0, group b mean = 15.0
    check(np.allclose(bg_mean.to_numpy(), [3.0, 3.0, 3.0, 15.0, 15.0]),
          "_bg_mean equals the group mean broadcast to members")
    for g in ("a", "b"):
        sel = df["neighborhood_id"] == g
        check(abs(float(within[sel].sum())) < 1e-12,
              f"_within sums to ~0 within group {g!r}")
    check(np.allclose((within + bg_mean).to_numpy(), df["x"].to_numpy()),
          "_within + _bg_mean == original column")
    # single-row group -> within is exactly 0, bg_mean is the value
    df1 = pd.DataFrame({"neighborhood_id": ["a", "b", "b"], "x": [7.0, 2.0, 4.0]})
    bg1, wi1 = m.group_mean_center(df1, "x", "neighborhood_id")
    check(abs(float(wi1.iloc[0])) < 1e-12 and abs(float(bg1.iloc[0]) - 7.0) < 1e-12,
          "singleton group -> _within 0, _bg_mean = the value")


def test_within_between_decomposition() -> None:
    """Recover a KNOWN within-group slope (distinct from the between slope) via numpy OLS."""
    print("\n[add_mundlak_terms: recover a known within-group slope (no statsmodels)]")
    groups = ["a", "a", "a", "b", "b", "b", "c", "c", "c"]
    x_group_mean = {"a": 0.0, "b": 5.0, "c": 10.0}   # between-group spread of x
    dx = [-1.0, 0.0, 1.0]                             # within-group offsets (mean 0 per group)
    beta_within, beta_between, alpha = 2.0, 10.0, 3.0
    offs = dx * 3
    x = [x_group_mean[g] + d for g, d in zip(groups, offs)]
    # y = alpha + between-slope * group_mean + within-slope * within-offset  (noise-free)
    y = np.array([alpha + beta_between * x_group_mean[g] + beta_within * d
                  for g, d in zip(groups, offs)], dtype="float64")
    df = pd.DataFrame({"neighborhood_id": groups, "vpd_z": x,
                       "sm_z": np.zeros(9), "y": y})
    out = m.add_mundlak_terms(df, cols=("vpd_z", "sm_z"), group="neighborhood_id")
    check(np.allclose(out["vpd_z_within"].to_numpy(), offs),
          "vpd_z_within reproduces the known within offsets")
    check(np.allclose(out["vpd_z_bg_mean"].to_numpy(),
                      [x_group_mean[g] for g in groups]),
          "vpd_z_bg_mean reproduces the group means")
    # Plain numpy OLS of y on [1, vpd_z_within] recovers the WITHIN slope (=2), because the
    # between term is constant within group and vpd_z_within is zero-mean within each group.
    A = np.column_stack([np.ones(9), out["vpd_z_within"].to_numpy()])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    check(abs(float(coef[1]) - beta_within) < 1e-9,
          f"OLS on _within recovers the within slope ({beta_within})")
    # A naive pooled OLS of y on RAW x is dominated by the between slope -> clearly != 2.
    Ap = np.column_stack([np.ones(9), np.asarray(x)])
    coef_p, *_ = np.linalg.lstsq(Ap, y, rcond=None)
    check(float(coef_p[1]) > 5.0,
          "naive pooled slope on raw x is inflated by the between structure (!= within)")


def test_cluster_resample_draws_whole_bgs() -> None:
    """cluster_resample_indices returns only whole groups; a group can appear 0/1/2+ times."""
    print("\n[cluster_resample_indices: whole-block-group resampling (B3.3)]")
    groups = np.array(["a", "a", "a", "b", "c", "c"])   # a:{0,1,2}, b:{3}, c:{4,5}
    members = {"a": [0, 1, 2], "b": [3], "c": [4, 5]}
    n_unique = 3
    rng = np.random.default_rng(20240615)
    appearance_seen = {"a": set(), "b": set(), "c": set()}
    for _ in range(400):
        idx = m.cluster_resample_indices(groups, rng)
        cnt = Counter(int(i) for i in idx.tolist())
        total_draws = 0
        for g, mem in members.items():
            per_member = [cnt.get(i, 0) for i in mem]
            # every member of a drawn group appears the SAME number of times (whole group)
            check_ok = len(set(per_member)) == 1
            if not check_ok:
                _FAILURES.append(f"partial group {g!r} drawn: {per_member}")
            appear = per_member[0]
            appearance_seen[g].add(appear)
            total_draws += appear
        # exactly n_unique whole groups were drawn (with replacement)
        if total_draws != n_unique:
            _FAILURES.append(f"drew {total_draws} groups, expected {n_unique}")
        # resampled size == sum of drawn group sizes
        expected_size = sum(cnt.get(i, 0) for mem in members.values() for i in mem)
        if int(idx.size) != expected_size:
            _FAILURES.append(f"resample size {idx.size} != {expected_size}")
    print("  ok:   400 draws are all whole-group unions of exactly 3 groups")
    check(0 in appearance_seen["a"], "some draw omits group 'a' entirely (0 times)")
    check(any(c >= 2 for c in appearance_seen["a"]),
          "some draw includes group 'a' 2+ times")
    # empty input -> empty index array
    empt = m.cluster_resample_indices(np.array([]), np.random.default_rng(0))
    check(empt.size == 0, "empty groups -> empty index array")

    # MixedLM-specific path: repeated source draws must receive distinct bootstrap
    # labels, otherwise statsmodels collapses them back into one random-effect level.
    frame = pd.DataFrame({"neighborhood_id": groups, "value": np.arange(groups.size)})
    boot = m.cluster_resample_frame(frame, np.random.default_rng(20240615))
    check(boot["neighborhood_id"].nunique() == n_unique,
          "bootstrap frame has one distinct random-effect label per cluster draw")
    complete = True
    for _, part in boot.groupby("neighborhood_id"):
        src = part["_bootstrap_source_group"].iloc[0]
        complete &= set(part["value"].tolist()) == set(frame.loc[frame["neighborhood_id"] == src,
                                                           "value"].tolist())
    check(complete, "every relabelled bootstrap cluster contains its complete source group")


def test_dominant_bg_downweight() -> None:
    """Inverse-cluster-size weights favor small BGs; leave-dominant-out drops that BG only."""
    print("\n[dominant-BG handling: inverse-size weights + leave-dominant-out]")
    groups = np.array(["dom"] * 10 + ["s1", "s2"])
    w = m.inverse_cluster_size_weights(groups)
    check(np.allclose(w[:10], 0.1), "dominant BG (size 10) rows -> weight 1/10")
    check(np.allclose(w[10:], 1.0), "singleton BGs -> weight 1.0")
    check(float(w[10:].min()) > float(w[:10].max()),
          "every small-BG weight exceeds every dominant-BG weight")
    df = pd.DataFrame({"neighborhood_id": groups, "v": np.arange(12.0)})
    out = m.leave_dominant_out(df, group="neighborhood_id", dominant="dom")
    check(len(out) == 2 and set(out["neighborhood_id"]) == {"s1", "s2"},
          "leave-dominant-out drops exactly the dominant BG's rows")
    check((out["neighborhood_id"] != "dom").all(), "no dominant rows remain")
    summary = m.dominant_group_summary(df, group="neighborhood_id", dominant="dom")
    check(summary["dominant_n_obs"] == 10
          and np.isclose(summary["dominant_share"], 10 / 12),
          "dominant share is computed from the exact supplied sample")
    caveat = m._dominant_bg_caveat({"n_obs": 12, **summary})
    stale_estimate = "~" + "95%"
    check("10 of 12" in caveat and "83.3%" in caveat and stale_estimate not in caveat,
          "note caveat reports the computed count/share rather than a hard-coded estimate")
    check(m.DOMINANT_BG == "040139412001", "DOMINANT_BG constant identifies the target BG")


def test_module_constants_and_contract() -> None:
    """Module constants + input-column contract."""
    print("\n[module constants + input-column contract]")
    check(m.PIXEL_PARQUET == "master_pixel_table.parquet", "reads master_pixel_table.parquet")
    check(m.NOTE_PATH == "docs/section14b_mixed_effects_note.md", "note path is the B3.2 note")
    check(m.OUTCOME_COL == "cooling_advantage_px", "outcome is cooling_advantage_px")
    check(m.KEY_COEF == "vpd_z_within", "key coefficient is vpd_z_within")
    check(m.MUNDLAK_COLS == ("vpd_z", "sm_z"), "Mundlak decomposition on vpd_z + sm_z")
    check(set(m.FIXED_EFFECT_COLS) == {"vpd_z_within", "sm_z_within",
                                       "vpd_z_bg_mean", "sm_z_bg_mean"},
          "fixed effects on the _within and _bg_mean terms")
    for c in ("neighborhood_id", "overpass_key", "cooling_advantage_px", "vpd_z", "sm_z", "ndmi_z",
              "aridity", "is_day", "local_hour", "sample_label",
              "n_tree_valid", "n_ref_valid"):
        check(c in m.REQUIRED_COLUMNS, f"required input column {c!r} declared")
    check(isinstance(m.HAVE_STATSMODELS, bool), "HAVE_STATSMODELS is a bool flag")


def test_primary_mask_enforces_label_and_floor() -> None:
    """primary_mask requires day + persisted primary label + the underlying count floor."""
    print("\n[primary_mask: day-only plus explicit tree-pixel floor]")
    floor = m.config.PRIMARY_MIN_TREE_PIXELS
    df = pd.DataFrame({"is_day": [True, True, False, True],
                       "sample_label": ["primary", "sensitivity_lt3_tree_pixels",
                                        "primary", "primary"],
                       "n_tree_valid": [floor, floor - 1, floor, floor - 1]})
    mask = m.primary_mask(df)
    check(mask.tolist() == [True, False, False, False],
          "only day + primary label + count-at-floor row enters the headline model")
    try:
        m.primary_mask(df.drop(columns="sample_label"))
        raised = False
    except ValueError:
        raised = True
    check(raised, "stale pixel table without sample_label fails clearly")


def test_complete_case_floor_and_design_preflight() -> None:
    """Predictor NaNs cannot leave a 1-2-pixel BG x overpass in the fitted sample."""
    print("\n[complete-case floor + mixed-design preflight]")
    df = _synthetic_pixel_df()
    target = (df["neighborhood_id"].eq("g2") & df["overpass_key"].eq("op1")
              & df["is_day"])
    target_idx = df.index[target].tolist()
    df.loc[target_idx[:4], "sm_z"] = np.nan  # 2 complete rows remain, below floor=3
    prepared = m._prepare_frame(df, day_only=True)
    still_present = (prepared["neighborhood_id"].eq("g2")
                     & prepared["overpass_key"].eq("op1")).any()
    check(not still_present,
          "BG x overpass with only 2 VPD+SM-complete pixels is excluded entirely")
    check(prepared.attrs.get("n_complete_case_groups_excluded") == 1,
          "complete-case exclusion count records the affected BG x overpass")
    check(prepared.attrs.get("n_complete_case_rows_excluded") == 2,
          "complete-case exclusion count records the two otherwise-complete rows")
    diag = m._validate_prepared_frame(prepared)
    check(diag["design_rank"] == diag["design_columns"],
          "retained fixed-effect design has full column rank")

    rank_bad = prepared.copy()
    rank_bad["sm_z_within"] = rank_bad["vpd_z_within"]
    rank_bad["sm_z_bg_mean"] = rank_bad["vpd_z_bg_mean"]
    try:
        m._validate_prepared_frame(rank_bad)
        raised = False
    except RuntimeError:
        raised = True
    check(raised, "rank-deficient fixed-effect design fails before MixedLM fitting")


def test_severe_warning_invalidates_fit() -> None:
    """A nominally converged finite fit is unusable when statsmodels flags a boundary."""
    print("\n[fit-quality gate: severe warnings + finite SE]")

    class FakeResult:
        converged = True
        params = pd.Series({m.KEY_COEF: -1.0})
        bse = pd.Series({m.KEY_COEF: 0.2})
        _phoenix_fit_warnings = [{
            "category": "ConvergenceWarning",
            "message": "The MLE may be on the boundary of the parameter space.",
        }]

    payload = m._mixed_result_payload(FakeResult())
    check(not payload["fit_usable"] and len(payload["severe_fit_warnings"]) == 1,
          "boundary/convergence warning rejects an otherwise finite converged fit")

    clean = FakeResult()
    clean._phoenix_fit_warnings = []
    payload_clean = m._mixed_result_payload(clean)
    check(payload_clean["fit_usable"], "clean converged fit with finite positive SE is usable")


# --- Model tests (guarded on statsmodels) ----------------------------------- #
def _synthetic_pixel_df(seed: int = 7) -> "pd.DataFrame":
    """Small pixel table with several BGs x overpasses and a real within-BG vpd effect."""
    rng = np.random.default_rng(seed)
    rows = []
    bg_levels = {"g1": 2.0, "g2": -1.0, "g3": 0.5, "g4": 1.0}   # between-BG intercepts
    overpasses = ["op1", "op2", "op3", "op4"]
    op_effect = {"op1": 0.3, "op2": -0.2, "op3": 0.1, "op4": -0.1}
    for gi, (bg, level) in enumerate(bg_levels.items()):
        n_px = 20 if bg == "g1" else 6                          # g1 is the "dominant" BG
        vpd_bg = float(rng.normal(0, 1))                        # BG-mean vpd (between)
        sm_bg = float(rng.normal(0, 1))
        for op in overpasses:
            for p in range(n_px):
                vpd_within = float(rng.normal(0, 1))
                sm_within = float(rng.normal(0, 1))
                vpd = vpd_bg + vpd_within
                sm_z = sm_bg + sm_within
                # within vpd cools less (-1.5 per unit), between vpd is a spatial confound (+3)
                y = (4.0 + level + op_effect[op]
                     - 1.5 * vpd_within + 3.0 * vpd_bg
                     + 0.4 * sm_within + float(rng.normal(0, 0.3)))
                rows.append({
                    "neighborhood_id": bg, "overpass_key": op,
                    "cooling_advantage_px": y, "vpd_z": vpd, "sm_z": sm_z,
                    "ndmi_z": float(rng.normal(0, 1)),
                    "aridity": -1.0, "is_day": True, "local_hour": 13,
                    "sample_label": "primary",
                    "pixel_row": gi * 100 + p, "pixel_col": p,
                    "n_tree_valid": n_px, "n_ref_valid": 30,
                })
    # a few night rows that must be excluded by the primary mask
    for op in overpasses:
        rows.append({"neighborhood_id": "g1", "overpass_key": op,
                     "cooling_advantage_px": 0.2, "vpd_z": 0.0, "sm_z": 0.0, "ndmi_z": 0.0,
                     "aridity": -1.0, "is_day": False, "local_hour": 2,
                     "sample_label": "primary",
                     "pixel_row": 999, "pixel_col": 0, "n_tree_valid": 20, "n_ref_valid": 30})
    return pd.DataFrame(rows)


def test_fit_mixed_runs() -> None:
    """fit_mixed returns coefficients + variance components on the day-only primary sample."""
    print("\n[fit_mixed: crossed random-intercept model (B3.2)]")
    if not HAVE_STATSMODELS:
        check(True, "fit_mixed (skipped: statsmodels absent)")
        return
    df = _synthetic_pixel_df()
    res = m.fit_mixed(df, day_only=True)
    check("vpd_z_within" in res["params"], "fixed effect vpd_z_within estimated")
    check(res["n_obs"] == int(df["is_day"].sum()),
          "fit uses only the day-only primary rows (night excluded)")
    check(np.isfinite(res["var_residual"]), "residual variance reported")
    check(np.isfinite(res["var_block_group"]) or np.isfinite(res["var_overpass"]),
          "at least one crossed variance component reported")
    check(res["key_estimate"] < 0.0,
          "recovered vpd_z_within is negative (within-BG cooling weakens with demand)")
    prepared = m._prepare_frame(df, day_only=True)
    expected_dominance = m.dominant_group_summary(prepared)
    check(res["dominant_n_obs"] == expected_dominance["dominant_n_obs"]
          and np.isclose(res["dominant_share"], expected_dominance["dominant_share"]),
          "fit result carries dominance statistics from the exact fitted frame")


def test_bootstrap_ci_reports_convergence_status() -> None:
    """B3.3 reports the cluster interval and refuses to hide failed/non-converged refits."""
    print("\n[bootstrap_mixed_ci: report width + convergence/identifiability status (B3.3)]")
    if not HAVE_STATSMODELS:
        check(True, "bootstrap_ci_wider_than_naive (skipped: statsmodels absent)")
        return
    df = _synthetic_pixel_df()
    fit = m.fit_mixed(df, day_only=True)
    naive_hw = m.model_se_halfwidth(fit["key_se"])
    boot = m.bootstrap_mixed_ci(df, n_boot=80, seed=20240615)
    cluster_hw = boot["coef"]["half_width"]
    if boot["status"] == "ok":
        check(np.isfinite(cluster_hw) and cluster_hw > 0,
              "passing bootstrap reports a finite/positive cluster CI half-width")
        check(np.isfinite(boot["mean_cooling"]["half_width"]),
              "passing bootstrap reports the mean cooling interval")
    else:
        check(np.isnan(cluster_hw) and np.isnan(boot["mean_cooling"]["half_width"]),
              "failed clean-fit gate suppresses misleading coefficient/mean intervals")
        check(boot["diagnostic_coef"]["n_valid"] > 0,
              "suppressed interval retains the surviving-refit count for audit")
    check(np.isfinite(naive_hw) and naive_hw > 0,
          "naive model-SE half-width is available for an explicit comparison")
    expected_status = ("ok" if boot["valid_fraction"] >= m.MIN_BOOTSTRAP_VALID_FRACTION
                       else "not_identifiable_too_few_clean_bootstrap_fits")
    check(boot["status"] == expected_status and 0.0 <= boot["valid_fraction"] <= 1.0,
          "bootstrap status matches the observed converged-fit fraction")

    one_bg = df[df["neighborhood_id"] == "g1"].copy()
    one = m.bootstrap_mixed_ci(one_bg, n_boot=10, seed=1)
    check(one["status"] == "not_identifiable_fewer_than_two_clusters"
          and one["coef"]["n_valid"] == 0,
          "single-BG sample returns an explicit not-identifiable status, not a zero-width CI")


def main() -> int:
    tests = [
        test_group_mean_centering,
        test_within_between_decomposition,
        test_cluster_resample_draws_whole_bgs,
        test_dominant_bg_downweight,
        test_module_constants_and_contract,
        test_primary_mask_enforces_label_and_floor,
        test_complete_case_floor_and_design_preflight,
        test_severe_warning_invalidates_fit,
        test_fit_mixed_runs,
        test_bootstrap_ci_reports_convergence_status,
    ]
    print("=" * 64)
    print("Section 14b mixed-effects self-test "
          f"(HAVE_STATSMODELS={HAVE_STATSMODELS})")
    print("=" * 64)
    for t in tests:
        t()
    print("\n" + "=" * 64)
    if _FAILURES:
        print(f"{len(_FAILURES)} CHECK(S) FAILED:")
        for f in _FAILURES:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
