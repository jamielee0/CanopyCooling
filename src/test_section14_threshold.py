#!/usr/bin/env python3
"""Self-test for the Section 14 threshold logic (pure-logic, small synthetic data).

Mirrors the sibling test_section*_*: plain-`assert`-style `check()` calls in `test_*()`
functions run by a `main()` runner (pytest is NOT installed in the canopy env). Section 14's
analysis libraries (pwlf, ruptures, scipy) ARE in the canopy env and are exercised for real on
TINY SYNTHETIC series -- no master table, no IO, no network -- so the tests are fast and prove
the numerics, not the data.

What is proven (the algorithmically risky parts the protocol leans on):
  * the SEGMENTED fit RECOVERS a known breakpoint on a clearly-KINKED synthetic series
    (flat then steeply declining) -- step 76 works when a threshold really is present;
  * the SEGMENTED fit STILL RETURNS a breakpoint on a STRAIGHT LINE and on PURE NOISE -- the
    protocol's central PITFALL, and the reason a breakpoint alone is never sufficient;
  * the LINEAR-vs-SEGMENTED comparison: a kink is preferred by AIC on kinked data, NOT
    preferred on a straight line (the kink buys ~nothing);
  * the BINNING mechanics: per-bin mean / SEM / count, NaN-pairwise dropping, empty bins;
  * the MIN-COUNT filter mask (step 75);
  * the BOOTSTRAP mechanics: a TIGHT CI around the true break on kinked data; a WIDE CI
    (large spans_fraction) on a straight line (-> "not identified");
  * the CHANGE-POINT (ruptures) lands near the true break on a level-shift series;
  * the ET-decline check, the methods-agree test, and the full VERDICT GATE -- robust on a
    constructed kink-with-ET case, "no robust threshold detected" on a straight line.

Runs in the canopy env:  python src/test_section14_threshold.py
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sec14 = importlib.import_module("section14_threshold")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


# --------------------------------------------------------------------------- #
# Synthetic-data builders.
# --------------------------------------------------------------------------- #
def _kinked(n: int = 240, bp: float = 0.6, seed: int = 0,
            slope1: float = 0.0, slope2: float = -12.0, noise: float = 0.3,
            plateau: float = 0.0
            ) -> tuple[np.ndarray, np.ndarray]:
    """A clearly-kinked continuous piecewise-linear series: a ``plateau`` at level (intercept
    ``plateau``, slope ``slope1``) below ``bp``, then a steep ``slope2`` decline above, on x in
    [0, 1], plus small Gaussian noise. This is the "a threshold IS present" case the segmented
    fit must recover. With ``plateau`` raised and ``slope2`` steep it is also the case where the
    pwlf knee and the ruptures mean-shift land close enough to AGREE (within tolerance) -- a
    realistic 'cooling benefit holds, then collapses' shape."""
    rng = np.random.default_rng(seed)
    x = np.sort(rng.uniform(0.0, 1.0, size=n))
    y = np.where(x <= bp, plateau + slope1 * x, plateau + slope1 * bp + slope2 * (x - bp))
    y = y + rng.normal(0.0, noise, size=n)
    return x, y


def _straight(n: int = 240, slope: float = -1.0, seed: int = 1, noise: float = 1.0
              ) -> tuple[np.ndarray, np.ndarray]:
    """A STRAIGHT line plus noise (no kink) -- the pitfall case (pwlf still returns a break)."""
    rng = np.random.default_rng(seed)
    x = np.sort(rng.uniform(0.0, 1.0, size=n))
    y = slope * x + rng.normal(0.0, noise, size=n)
    return x, y


def _noise(n: int = 240, seed: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Pure noise: y independent of x (no relationship at all)."""
    rng = np.random.default_rng(seed)
    x = np.sort(rng.uniform(0.0, 1.0, size=n))
    y = rng.normal(0.0, 1.0, size=n)
    return x, y


# --------------------------------------------------------------------------- #
# 1. segmented fit recovers a known breakpoint on a kinked series (step 76).
# --------------------------------------------------------------------------- #
def test_segmented_recovers_known_breakpoint() -> None:
    print("\n[segmented_fit recovers a KNOWN breakpoint on a clearly-kinked series (step 76)]")
    x, y = _kinked(bp=0.6, slope1=0.0, slope2=-12.0, noise=0.2, seed=0)
    seg = sec14.segmented_fit(x, y)
    check(np.isfinite(seg["breakpoint"]), "a breakpoint is returned on kinked data")
    check(abs(seg["breakpoint"] - 0.6) < 0.08,
          f"recovered breakpoint {seg['breakpoint']:.3f} is within 0.08 of the true 0.60")
    check(seg["slope1"] > -2.0 and seg["slope2"] < -8.0,
          f"slope1 ~flat ({seg['slope1']:.2f}) and slope2 steeply negative ({seg['slope2']:.2f})")
    check(seg["slope_change"] < -8.0,
          f"slope_change is strongly negative ({seg['slope_change']:.2f}) -- a real bend")
    check(seg["r2"] > 0.9, f"segmented R^2 is high on clean kinked data ({seg['r2']:.3f})")


# --------------------------------------------------------------------------- #
# 2. THE PITFALL: a breakpoint is returned even on a straight line / pure noise.
# --------------------------------------------------------------------------- #
def test_segmented_returns_breakpoint_on_straight_line() -> None:
    print("\n[PITFALL: segmented_fit STILL returns a breakpoint on a straight line AND noise]")
    xs, ys = _straight(slope=-1.0, noise=0.05, seed=1)   # nearly perfect line
    seg_line = sec14.segmented_fit(xs, ys)
    check(np.isfinite(seg_line["breakpoint"]),
          "a breakpoint IS returned on a (near-perfect) straight line -- the pitfall")
    # On a straight line the two slopes are ~equal -> slope_change ~ 0 (no real bend).
    check(abs(seg_line["slope_change"]) < 1.0,
          f"but the straight-line slope_change is ~0 ({seg_line['slope_change']:+.3f}) -- no bend")
    xn, yn = _noise(seed=2)
    seg_noise = sec14.segmented_fit(xn, yn)
    check(np.isfinite(seg_noise["breakpoint"]),
          "a breakpoint IS returned on PURE NOISE too -- breakpoint alone proves nothing")


# --------------------------------------------------------------------------- #
# 3. linear vs segmented comparison (is the kink worth it?).
# --------------------------------------------------------------------------- #
def test_compare_linear_segmented() -> None:
    print("\n[compare_linear_segmented: kink preferred on kinked data, NOT on a line]")
    xk, yk = _kinked(bp=0.6, slope1=0.0, slope2=-12.0, noise=0.2, seed=3)
    ck = sec14.compare_linear_segmented(xk, yk)
    check(ck["delta_r2"] > 0.05,
          f"segmented R^2 beats linear by a clear margin on kinked data (dR2={ck['delta_r2']:.3f})")
    check(ck["segmented_preferred_by_aic"],
          f"segmented preferred by AIC on kinked data (dAIC={ck['delta_aic']:.1f} < -2)")
    xs, ys = _straight(slope=-1.0, noise=1.0, seed=4)
    cs = sec14.compare_linear_segmented(xs, ys)
    check(cs["delta_r2"] < 0.02,
          f"segmented barely improves R^2 on a straight line (dR2={cs['delta_r2']:.4f})")
    check(not cs["segmented_preferred_by_aic"],
          f"segmented NOT preferred by AIC on a straight line (dAIC={cs['delta_aic']:+.1f}) -- "
          "the kink is not worth it")


# --------------------------------------------------------------------------- #
# 4. binning mechanics (step 73).
# --------------------------------------------------------------------------- #
def test_bin_means() -> None:
    print("\n[bin_means: per-bin mean / SEM / count, NaN-pairwise drop, empty bins]")
    # x in [0,1], y = 2x exactly -> bin means increase; SEM tiny within a tight bin.
    x = np.linspace(0.0, 1.0, 100)
    y = 2.0 * x
    b = sec14.bin_means(x, y, n_bins=5)
    check(len(b["edges"]) == 6 and len(b["centers"]) == 5, "edges len = n_bins+1; centers len = n_bins")
    check(int(b["count"].sum()) == 100, "every finite pair is assigned to exactly one bin")
    check(np.all(np.diff(b["mean"]) > 0), "bin means increase monotonically for y = 2x")
    # NaN pairs dropped pairwise.
    xn = np.array([0.1, 0.2, np.nan, 0.8, 0.9])
    yn = np.array([1.0, np.nan, 5.0, 4.0, 4.5])
    bn = sec14.bin_means(xn, yn, n_bins=2)
    check(int(bn["count"].sum()) == 3, "rows with NaN x OR NaN y are dropped before binning")
    # an empty bin -> NaN mean, 0 count (gap in x).
    xg = np.array([0.05, 0.06, 0.95, 0.96])
    yg = np.array([1.0, 1.1, 9.0, 9.1])
    bg = sec14.bin_means(xg, yg, n_bins=4)
    check(np.isnan(bg["mean"]).any() and (bg["count"] == 0).any(),
          "a bin with no points has NaN mean and 0 count (drawn as a gap)")
    # SEM = std/sqrt(n): two points {0.0, 2.0} -> mean 1.0, std(ddof=1)=sqrt(2), sem=1.0.
    bs = sec14.bin_means(np.array([0.25, 0.25]), np.array([0.0, 2.0]), n_bins=1)
    check(abs(bs["mean"][0] - 1.0) < 1e-9 and abs(bs["sem"][0] - 1.0) < 1e-9,
          "per-bin SEM = std(ddof=1)/sqrt(n) (mean 1.0, sem 1.0 for {0,2})")


# --------------------------------------------------------------------------- #
# 5. min-count filter mask (step 75).
# --------------------------------------------------------------------------- #
def test_apply_min_count() -> None:
    print("\n[apply_min_count: keep rows with n_tree_valid >= min_count (step 75)]")
    counts = np.array([1, 2, 3, 10, 171, np.nan])
    m1 = sec14.apply_min_count(counts, 1)
    check(m1.tolist() == [True, True, True, True, True, False],
          "min_count=1 keeps all finite counts (drops NaN)")
    m3 = sec14.apply_min_count(counts, 3)
    check(m3.tolist() == [False, False, True, True, True, False],
          "min_count=3 keeps counts >= 3 only")
    m10 = sec14.apply_min_count(counts, 10)
    check(m10.tolist() == [False, False, False, True, True, False],
          "min_count=10 collapses toward the well-sampled rows (>=10) -- the robust subset")


# --------------------------------------------------------------------------- #
# 6. bootstrap: tight CI on a kink, wide CI on a straight line (step 77).
# --------------------------------------------------------------------------- #
def test_bootstrap_breakpoint() -> None:
    print("\n[bootstrap_breakpoint: tight CI on a kink, WIDE CI on a straight line (step 77)]")
    xk, yk = _kinked(bp=0.6, slope1=0.0, slope2=-12.0, noise=0.2, seed=5)
    bk = sec14.bootstrap_breakpoint(xk, yk, n_boot=200, seed=5)
    check(bk["n_valid"] > 150, f"most bootstrap resamples fit ({bk['n_valid']}/200)")
    check(bk["ci_low"] <= 0.6 <= bk["ci_high"], "the true break 0.60 lies inside the bootstrap CI")
    check(bk["spans_fraction"] < 0.5,
          f"the CI is TIGHT on a real kink (spans_fraction={bk['spans_fraction']:.2f} < 0.5 "
          "-> well identified)")
    # Reproducibility: same seed -> identical CI.
    bk2 = sec14.bootstrap_breakpoint(xk, yk, n_boot=200, seed=5)
    check(bk["ci_low"] == bk2["ci_low"] and bk["ci_high"] == bk2["ci_high"],
          "the bootstrap is deterministic for a fixed seed")
    # Straight line -> the breakpoint wanders -> WIDE CI (not identified).
    xs, ys = _straight(slope=-1.0, noise=1.0, seed=6)
    bs = sec14.bootstrap_breakpoint(xs, ys, n_boot=200, seed=6)
    check(bs["spans_fraction"] > 0.5,
          f"the CI is WIDE on a straight line (spans_fraction={bs['spans_fraction']:.2f} > 0.5 "
          "-> NOT identified)")


# --------------------------------------------------------------------------- #
# 7. change-point (ruptures) lands near a true level shift (step 78).
# --------------------------------------------------------------------------- #
def test_changepoint_csi() -> None:
    print("\n[changepoint_csi: ruptures finds a level shift near the true split (step 78)]")
    # A clean LEVEL shift at x=0.5: y ~ 0 below, y ~ -8 above.
    rng = np.random.default_rng(7)
    x = np.sort(rng.uniform(0.0, 1.0, size=200))
    y = np.where(x < 0.5, 0.0, -8.0) + rng.normal(0.0, 0.2, size=200)
    cp = sec14.changepoint_csi(x, y)
    check(np.isfinite(cp["changepoint_csi"]), "a change-point is returned")
    check(abs(cp["changepoint_csi"] - 0.5) < 0.06,
          f"change-point {cp['changepoint_csi']:.3f} is within 0.06 of the true 0.50")
    check(1 <= cp["split_index"] <= cp["n"] - 1, "split index is interior to the sequence")


# --------------------------------------------------------------------------- #
# 8. ET-decline check + methods-agree + the full VERDICT gate (steps 74, 78-79).
# --------------------------------------------------------------------------- #
def test_et_declines_beyond() -> None:
    print("\n[et_declines_beyond: mean ET below vs above the threshold (step 74)]")
    csi = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
    et = np.array([300.0, 290.0, 310.0, 120.0, 110.0, 100.0])   # high below, low above 0.5
    d = sec14.et_declines_beyond(csi, et, 0.5)
    check(d["et_declines"], "ET declines beyond the threshold (mean above < mean below)")
    check(d["mean_et_below"] > d["mean_et_above"], "mean ET below > mean ET above")
    check(d["n_below"] == 3 and d["n_above"] == 3, "below/above counts are correct")
    # ET that does NOT decline.
    d2 = sec14.et_declines_beyond(csi, et[::-1], 0.5)
    check(not d2["et_declines"], "reversed ET -> no decline beyond the threshold")
    # NaN ET rows dropped pairwise; NaN threshold -> no decline.
    d3 = sec14.et_declines_beyond(csi, np.array([np.nan]*6), 0.5)
    check(not d3["et_declines"] and d3["n_below"] == 0, "all-NaN ET -> no decline, 0 counts")
    check(not sec14.et_declines_beyond(csi, et, np.nan)["et_declines"],
          "NaN threshold -> et_declines False")


def test_methods_agree() -> None:
    print("\n[methods_agree: change-point inside the bootstrap CI (step 78)]")
    check(sec14.methods_agree(0.4, 0.7, 0.55), "change-point 0.55 inside CI (0.4, 0.7) -> agree")
    check(not sec14.methods_agree(0.4, 0.7, 0.9), "change-point 0.9 outside CI (0.4, 0.7) -> disagree")
    check(sec14.methods_agree(0.7, 0.4, 0.55), "CI bounds are order-insensitive (still agree)")
    check(not sec14.methods_agree(np.nan, 0.7, 0.55), "non-finite CI bound -> not agree")


def test_methods_agree_within_tolerance() -> None:
    print("\n[methods_agree: tolerance band absorbs the pwlf-knee vs ruptures-shift offset]")
    # Razor-thin CI that EXCLUDES the change-point, but the points are within tolerance.
    # x_range=1.0, tol=0.20 -> |0.72 - 0.56| = 0.16 < 0.20 -> agree via tolerance.
    check(sec14.methods_agree(0.55, 0.57, 0.72, breakpoint=0.56, x_range=1.0),
          "change-point outside a thin CI but within 0.20*range of the breakpoint -> agree")
    # A genuinely discordant pair: outside the CI AND beyond tolerance -> disagree.
    check(not sec14.methods_agree(0.55, 0.57, 0.95, breakpoint=0.56, x_range=1.0),
          "change-point far outside the CI and beyond tolerance -> disagree")
    # Without breakpoint/x_range it falls back to the strict CI-only test.
    check(sec14.methods_agree(0.4, 0.7, 0.55), "CI-only fallback still works (0.55 in [0.4,0.7])")


def test_threshold_verdict_robust_case() -> None:
    print("\n[threshold_verdict: ROBUST on a constructed plateau-then-decline + ET case (78-79)]")
    # Plateau (+6 K) below bp, steep decline above -> pwlf knee and ruptures shift agree within
    # tolerance, bend is steep, CI is tight; ET drops past bp. A realistic 'benefit collapses'.
    x, y = _kinked(bp=0.55, slope1=0.0, slope2=-16.0, noise=0.5, plateau=6.0, seed=8)
    et = np.where(x < 0.55, 300.0, 120.0)        # ET genuinely declines past the break
    res = sec14.analyze_sample(x, y, et=et, n_boot=200, seed=8, label="synthetic-kink")
    v = res["verdict"]
    check(v.methods_agree, "robust case: the two methods agree (within tolerance)")
    check(v.bend_visible, "robust case: a bend is visible (steep post-break slope)")
    check(v.et_corroborates, "robust case: ET declines beyond the breakpoint")
    check(v.well_identified, "robust case: the bootstrap CI is tight (well identified)")
    check(v.robust and v.label == "robust threshold",
          "ALL gates pass -> verdict.robust True, label 'robust threshold'")


def test_threshold_verdict_no_threshold_case() -> None:
    print("\n[threshold_verdict: NO ROBUST THRESHOLD on a straight line (the honest null)]")
    x, y = _straight(slope=-1.0, noise=1.0, seed=9)
    et = 200.0 - 50.0 * x      # ET trends but there is no kink in cooling advantage
    res = sec14.analyze_sample(x, y, et=et, n_boot=200, seed=9, label="synthetic-line")
    v = res["verdict"]
    check(not v.bend_visible, "straight line: no bend (slope_change ~ 0)")
    check(not v.well_identified, "straight line: the bootstrap CI is wide (not identified)")
    # The identification gate is what rejects the line: a CI spanning the whole range may
    # trivially 'contain' the change-point, but well_identified=False blocks the verdict.
    check(not v.robust and v.label == "no robust threshold detected",
          "a straight line yields 'no robust threshold detected' -- a VALID outcome")
    check(not res["comparison"]["segmented_preferred_by_aic"],
          "and the kink is not preferred over the line by AIC")


def test_verdict_gate_logic_controlled() -> None:
    print("\n[threshold_verdict: each gate is necessary (controlled dict inputs)]")
    # A passing baseline, then flip each gate off and confirm the verdict flips to not-robust.
    seg = {"breakpoint": 0.5, "slope_change": -5.0}
    boot = {"ci_low": 0.45, "ci_high": 0.55, "spans_fraction": 0.1, "x_range": 1.0}
    cp = {"changepoint_csi": 0.5}
    et = {"et_declines": True, "mean_et_below": 300.0, "mean_et_above": 120.0}
    comp = {"delta_r2": 0.2, "delta_aic": -50.0, "segmented_preferred_by_aic": True}
    base = sec14.threshold_verdict(segmented=seg, bootstrap=boot, changepoint=cp,
                                   et_check=et, comparison=comp)
    check(base.robust, "baseline with all gates satisfied -> robust")
    # flip ET off
    v_et = sec14.threshold_verdict(segmented=seg, bootstrap=boot, changepoint=cp,
                                   et_check={**et, "et_declines": False}, comparison=comp)
    check(not v_et.robust, "ET not declining -> not robust (mechanistic gate is necessary)")
    # flip bend off (shallow slope change)
    v_bend = sec14.threshold_verdict(segmented={**seg, "slope_change": -0.1}, bootstrap=boot,
                                     changepoint=cp, et_check=et, comparison=comp)
    check(not v_bend.robust, "no visible bend (slope_change ~ 0) -> not robust")
    # flip identification off (wide CI)
    v_id = sec14.threshold_verdict(segmented=seg,
                                   bootstrap={**boot, "spans_fraction": 0.8}, changepoint=cp,
                                   et_check=et, comparison=comp)
    check(not v_id.robust, "wide bootstrap CI (not identified) -> not robust")
    # flip agreement off (change-point far away, tight CI)
    v_ag = sec14.threshold_verdict(segmented=seg, bootstrap=boot,
                                   changepoint={"changepoint_csi": 0.95}, et_check=et,
                                   comparison=comp)
    check(not v_ag.robust, "methods disagree (change-point far outside CI & tolerance) -> not robust")


# --------------------------------------------------------------------------- #
# 9. describe_shape headline descriptors (step 72).
# --------------------------------------------------------------------------- #
def test_describe_shape() -> None:
    print("\n[describe_shape: Pearson/Spearman/OLS slope of the scatter (step 72)]")
    rng = np.random.default_rng(10)
    x = np.sort(rng.uniform(0.0, 1.0, size=200))
    y = -3.0 * x + rng.normal(0.0, 0.2, size=200)   # clear negative relationship
    s = sec14.describe_shape(x, y)
    check(s["pearson_r"] < -0.9, f"strong negative Pearson r recovered ({s['pearson_r']:.3f})")
    check(s["ols_slope"] < -2.5, f"OLS slope near -3 recovered ({s['ols_slope']:.2f})")
    # a flat cloud -> ~0 correlation.
    yf = rng.normal(0.0, 1.0, size=200)
    sf = sec14.describe_shape(x, yf)
    check(abs(sf["pearson_r"]) < 0.2, f"a flat cloud has ~0 Pearson r ({sf['pearson_r']:.3f})")


# --------------------------------------------------------------------------- #
# Direct runner (parity with the sibling test modules).
# --------------------------------------------------------------------------- #
def main() -> int:
    tests = [
        test_segmented_recovers_known_breakpoint,
        test_segmented_returns_breakpoint_on_straight_line,
        test_compare_linear_segmented,
        test_bin_means,
        test_apply_min_count,
        test_bootstrap_breakpoint,
        test_changepoint_csi,
        test_et_declines_beyond,
        test_methods_agree,
        test_methods_agree_within_tolerance,
        test_threshold_verdict_robust_case,
        test_threshold_verdict_no_threshold_case,
        test_verdict_gate_logic_controlled,
        test_describe_shape,
    ]
    print("=" * 64)
    print("Section 14 pure-logic self-test")
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
