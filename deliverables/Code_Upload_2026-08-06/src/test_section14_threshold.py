#!/usr/bin/env python3
"""Self-test for Section 14 threshold logic (pure-logic, tiny synthetic data).

`check()`-style asserts in `test_*()` functions run by `main()` (pytest absent in canopy).
pwlf/ruptures/scipy ARE exercised for real on tiny synthetic series -- no IO/network.
Proves: segmented fit recovers a known breakpoint on a kink but also returns one on a
line/noise (the pitfall); linear-vs-segmented AIC; binning; min-count mask; bootstrap CI
(tight on kink, wide on line); ruptures change-point; ET-decline; methods-agree; verdict gate.

Run:  python src/test_section14_threshold.py
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sec14 = importlib.import_module("section14_threshold")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


# Synthetic-data builders.
def _kinked(n: int = 240, bp: float = 0.6, seed: int = 0,
            slope1: float = 0.0, slope2: float = -12.0, noise: float = 0.3,
            plateau: float = 0.0
            ) -> tuple[np.ndarray, np.ndarray]:
    """Continuous piecewise-linear kink: plateau below bp, steep slope2 above, plus noise."""
    rng = np.random.default_rng(seed)
    x = np.sort(rng.uniform(0.0, 1.0, size=n))
    y = np.where(x <= bp, plateau + slope1 * x, plateau + slope1 * bp + slope2 * (x - bp))
    y = y + rng.normal(0.0, noise, size=n)
    return x, y


def _straight(n: int = 240, slope: float = -1.0, seed: int = 1, noise: float = 1.0
              ) -> tuple[np.ndarray, np.ndarray]:
    """Straight line plus noise (no kink) -- the pitfall case."""
    rng = np.random.default_rng(seed)
    x = np.sort(rng.uniform(0.0, 1.0, size=n))
    y = slope * x + rng.normal(0.0, noise, size=n)
    return x, y


def _noise(n: int = 240, seed: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Pure noise: y independent of x."""
    rng = np.random.default_rng(seed)
    x = np.sort(rng.uniform(0.0, 1.0, size=n))
    y = rng.normal(0.0, 1.0, size=n)
    return x, y


def test_segmented_recovers_known_breakpoint() -> None:
    """Segmented fit recovers a known breakpoint on a kinked series (step 76)."""
    print("\n[segmented_fit recovers a KNOWN breakpoint on a kinked series (step 76)]")
    x, y = _kinked(bp=0.6, slope1=0.0, slope2=-12.0, noise=0.2, seed=0)
    seg = sec14.segmented_fit(x, y)
    check(np.isfinite(seg["breakpoint"]), "breakpoint returned on kinked data")
    check(abs(seg["breakpoint"] - 0.6) < 0.08,
          f"breakpoint {seg['breakpoint']:.3f} within 0.08 of true 0.60")
    check(seg["slope1"] > -2.0 and seg["slope2"] < -8.0,
          f"slope1 ~flat ({seg['slope1']:.2f}), slope2 steeply neg ({seg['slope2']:.2f})")
    check(seg["slope_change"] < -8.0,
          f"slope_change strongly negative ({seg['slope_change']:.2f}) -- a real bend")
    check(seg["r2"] > 0.9, f"segmented R^2 high on clean kink ({seg['r2']:.3f})")


def test_segmented_returns_breakpoint_on_straight_line() -> None:
    """PITFALL: breakpoint returned even on a straight line / pure noise."""
    print("\n[PITFALL: segmented_fit STILL returns a breakpoint on a line AND noise]")
    xs, ys = _straight(slope=-1.0, noise=0.05, seed=1)   # nearly perfect line
    seg_line = sec14.segmented_fit(xs, ys)
    check(np.isfinite(seg_line["breakpoint"]),
          "breakpoint IS returned on a near-perfect line -- the pitfall")
    check(abs(seg_line["slope_change"]) < 1.0,
          f"but line slope_change ~0 ({seg_line['slope_change']:+.3f}) -- no bend")
    xn, yn = _noise(seed=2)
    seg_noise = sec14.segmented_fit(xn, yn)
    check(np.isfinite(seg_noise["breakpoint"]),
          "breakpoint IS returned on PURE NOISE too -- breakpoint alone proves nothing")


def test_compare_linear_segmented() -> None:
    """Linear vs segmented: kink preferred on kinked data, not on a line."""
    print("\n[compare_linear_segmented: kink preferred on kink, NOT on a line]")
    xk, yk = _kinked(bp=0.6, slope1=0.0, slope2=-12.0, noise=0.2, seed=3)
    ck = sec14.compare_linear_segmented(xk, yk)
    check(ck["delta_r2"] > 0.05,
          f"segmented R^2 beats linear on kink (dR2={ck['delta_r2']:.3f})")
    check(ck["segmented_preferred_by_aic"],
          f"segmented preferred by AIC on kink (dAIC={ck['delta_aic']:.1f} < -2)")
    xs, ys = _straight(slope=-1.0, noise=1.0, seed=4)
    cs = sec14.compare_linear_segmented(xs, ys)
    check(cs["delta_r2"] < 0.02,
          f"segmented barely improves R^2 on a line (dR2={cs['delta_r2']:.4f})")
    check(not cs["segmented_preferred_by_aic"],
          f"segmented NOT preferred by AIC on a line (dAIC={cs['delta_aic']:+.1f})")


def test_bin_means() -> None:
    """Binning: per-bin mean / SEM / count, NaN-pairwise drop, empty bins (step 73)."""
    print("\n[bin_means: per-bin mean / SEM / count, NaN drop, empty bins]")
    x = np.linspace(0.0, 1.0, 100)
    y = 2.0 * x
    b = sec14.bin_means(x, y, n_bins=5)
    check(len(b["edges"]) == 6 and len(b["centers"]) == 5, "edges=n_bins+1, centers=n_bins")
    check(int(b["count"].sum()) == 100, "every finite pair assigned to one bin")
    check(np.all(np.diff(b["mean"]) > 0), "bin means increase monotonically for y=2x")
    xn = np.array([0.1, 0.2, np.nan, 0.8, 0.9])
    yn = np.array([1.0, np.nan, 5.0, 4.0, 4.5])
    bn = sec14.bin_means(xn, yn, n_bins=2)
    check(int(bn["count"].sum()) == 3, "rows with NaN x OR y dropped before binning")
    xg = np.array([0.05, 0.06, 0.95, 0.96])
    yg = np.array([1.0, 1.1, 9.0, 9.1])
    bg = sec14.bin_means(xg, yg, n_bins=4)
    check(np.isnan(bg["mean"]).any() and (bg["count"] == 0).any(),
          "empty bin has NaN mean and 0 count")
    bs = sec14.bin_means(np.array([0.25, 0.25]), np.array([0.0, 2.0]), n_bins=1)
    check(abs(bs["mean"][0] - 1.0) < 1e-9 and abs(bs["sem"][0] - 1.0) < 1e-9,
          "per-bin SEM = std(ddof=1)/sqrt(n) (mean 1.0, sem 1.0 for {0,2})")


def test_apply_min_count() -> None:
    """Min-count filter mask: keep rows with n_tree_valid >= min_count (step 75)."""
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
          "min_count=10 keeps >=10 -- the robust subset")


def test_bootstrap_breakpoint() -> None:
    """Bootstrap: tight CI on a kink, wide CI on a straight line (step 77)."""
    print("\n[bootstrap_breakpoint: tight CI on kink, WIDE CI on a line (step 77)]")
    xk, yk = _kinked(bp=0.6, slope1=0.0, slope2=-12.0, noise=0.2, seed=5)
    bk = sec14.bootstrap_breakpoint(xk, yk, n_boot=200, seed=5)
    check(bk["n_valid"] > 150, f"most resamples fit ({bk['n_valid']}/200)")
    check(bk["ci_low"] <= 0.6 <= bk["ci_high"], "true break 0.60 inside bootstrap CI")
    check(bk["spans_fraction"] < 0.5,
          f"CI TIGHT on a real kink (spans_fraction={bk['spans_fraction']:.2f} < 0.5)")
    bk2 = sec14.bootstrap_breakpoint(xk, yk, n_boot=200, seed=5)
    check(bk["ci_low"] == bk2["ci_low"] and bk["ci_high"] == bk2["ci_high"],
          "bootstrap deterministic for a fixed seed")
    xs, ys = _straight(slope=-1.0, noise=1.0, seed=6)
    bs = sec14.bootstrap_breakpoint(xs, ys, n_boot=200, seed=6)
    check(bs["spans_fraction"] > 0.5,
          f"CI WIDE on a line (spans_fraction={bs['spans_fraction']:.2f} > 0.5 -> not identified)")


def test_cluster_bootstrap_draws_whole_bgs() -> None:
    """B3.3: cluster resample draws WHOLE block groups; groups=None is unchanged."""
    print("\n[cluster bootstrap: whole-BG resampling, i.i.d. path preserved (B3.3)]")
    # 4 clusters of 3 rows each; the resampler must return only whole-cluster unions.
    groups = np.array([0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3])
    members = {g: set(np.nonzero(groups == g)[0]) for g in np.unique(groups)}
    rng = np.random.default_rng(0)
    for _ in range(200):
        idx = sec14._cluster_resample_indices(groups, rng)
        drawn = [g for g in np.unique(groups) if members[g] <= set(idx)]
        # every index belongs to a cluster that is present in FULL (no partial clusters)
        present = {int(groups[i]) for i in idx}
        for g in present:
            check(members[g] <= set(idx), f"cluster {g} present -> all its rows present")
        check(idx.size % 3 == 0, "resample size is a whole number of 3-row clusters")
    # groups=None must be byte-for-byte identical to the historical i.i.d. row bootstrap.
    xk, yk = _kinked(bp=0.6, slope1=0.0, slope2=-12.0, noise=0.2, seed=5)
    b_none = sec14.bootstrap_breakpoint(xk, yk, n_boot=150, seed=5)
    b_default = sec14.bootstrap_breakpoint(xk, yk, n_boot=150, seed=5, groups=None)
    check(b_none["ci_low"] == b_default["ci_low"] and b_none["ci_high"] == b_default["ci_high"],
          "groups=None reproduces the i.i.d. row bootstrap exactly")
    check(b_none["clustered"] is False and b_none["n_clusters"] == 0,
          "groups=None reports clustered=False")
    # A single-BG sample cannot support a cluster bootstrap -> NaN CI, not a zero-width one.
    one_bg = sec14.bootstrap_breakpoint(xk, yk, n_boot=100, seed=5,
                                        groups=np.zeros(xk.size, dtype=int))
    check(one_bg["n_clusters"] == 1 and not np.isfinite(one_bg["spans_fraction"]),
          "single-cluster groups -> NaN CI (uncomputable), not spurious zero width")


def test_cluster_bootstrap_wider_than_iid() -> None:
    """B3.3: with between-BG breakpoint heterogeneity, the BG-cluster CI is WIDER than the row CI.

    This is the whole point of the fix: an i.i.d. row bootstrap treats pseudo-replicated rows
    as independent and pins the pooled breakpoint too tightly. When each block group carries its
    OWN breakpoint (as thin, per-BG paired samples do), resampling whole BGs moves the pooled
    kink across the per-BG values and reports the honest, wider interval.
    """
    print("\n[cluster bootstrap: whole-BG CI wider than i.i.d. rows on clustered data (B3.3)]")
    rng = np.random.default_rng(1)
    xs, ys, gs = [], [], []
    for bg, bp in enumerate((0.30, 0.42, 0.54, 0.66, 0.78)):   # a distinct kink per block group
        m = 60
        xb = np.sort(rng.uniform(0.0, 1.0, size=m))
        yb = np.where(xb < bp, 0.0, -10.0) + rng.normal(0.0, 0.25, size=m)
        xs.append(xb); ys.append(yb); gs.append(np.full(m, bg))
    x = np.concatenate(xs); y = np.concatenate(ys); g = np.concatenate(gs)
    b_iid = sec14.bootstrap_breakpoint(x, y, n_boot=300, seed=1)
    b_clu = sec14.bootstrap_breakpoint(x, y, n_boot=300, seed=1, groups=g)
    check(b_clu["clustered"] is True and b_clu["n_clusters"] == 5,
          f"clustered CI reports 5 BGs (got {b_clu['n_clusters']})")
    check(b_clu["spans_fraction"] > b_iid["spans_fraction"],
          f"BG-cluster CI WIDER than i.i.d. rows "
          f"(cluster spans={b_clu['spans_fraction']:.3f} > iid {b_iid['spans_fraction']:.3f})")


def test_changepoint_csi() -> None:
    """Penalized slope-change method finds a known kink and may return zero breaks."""
    print("\n[changepoint_csi: penalized PELT finds a slope change but can return zero]")
    # Use a regular design here so this unit test isolates the change-point logic from
    # random gaps in x near the known kink. Irregular-x behaviour is exercised by the
    # end-to-end synthetic verdict test below.
    rng = np.random.default_rng(7)
    x = np.linspace(0.0, 1.0, 240)
    y = np.where(x < 0.5, 6.0, 6.0 - 12.0 * (x - 0.5))
    y = y + rng.normal(0.0, 0.2, size=x.size)
    cp = sec14.changepoint_csi(x, y)
    check(np.isfinite(cp["changepoint_csi"]), "change-point returned")
    check(cp["n_breaks"] == 1, "exactly one penalized slope break selected")
    check(abs(cp["changepoint_csi"] - 0.5) < 0.10,
          f"change-point {cp['changepoint_csi']:.3f} within 0.10 of true 0.50")
    check(cp["split_index"] > 0, "split index interior to the slope sequence")
    xf, yf = _straight(slope=-1.0, noise=0.05, seed=16)
    none = sec14.changepoint_csi(xf, yf)
    check(none["n_breaks"] == 0 and none["split_index"] == -1
          and not np.isfinite(none["changepoint_csi"]),
          "straight response -> zero breaks and NaN change-point (not forced)")
    flat = sec14.changepoint_csi(xf, np.ones_like(xf))
    check(flat["n_breaks"] == 0 and not np.isfinite(flat["changepoint_csi"]),
          "flat response -> zero breaks and NaN change-point")
    check(sec14.optional_threshold_label(flat["changepoint_csi"]) == "none",
          "zero-break result is displayed as 'none', never as a fabricated number")


def test_csi_weight_sensitivity_uses_identical_primary_rows() -> None:
    """m3: all five weights use the same primary rows and equal reproduces baseline."""
    print("\n[m3: five CSI weights use identical daytime-primary rows and BG clusters]")
    rng = np.random.default_rng(31)
    n = 80
    demand = np.linspace(0.0, 2.0, n)
    supply = 0.2 + 0.35 * demand ** 2 + rng.normal(0.0, 0.03, n)
    equal = 0.5 * demand + 0.5 * supply
    cooling = 5.0 - 1.5 * demand + rng.normal(0.0, 0.4, n)
    frame = pd.DataFrame({
        sec14.OUTCOME_COL: cooling,
        sec14.CSI_COL: equal,
        sec14.ET_COL: 250.0 - 20.0 * demand,
        sec14.COUNT_COL: np.full(n, 3),
        "is_day": np.ones(n, dtype=bool),
        "sample_label": np.repeat("primary", n),
        "neighborhood_id": np.repeat(["A", "B", "C", "D"], n // 4),
        sec14.DEMAND_COMPONENT_COL: demand,
        sec14.SUPPLY_COMPONENT_COL: supply,
    })
    table = sec14.csi_weight_sensitivity_table(frame, n_boot=10, seed=31)
    check(len(table) == 5, "all five predeclared weight scenarios executed")
    check(table["n_rows"].nunique() == 1 and int(table["n_rows"].iloc[0]) == n,
          "every scenario uses the identical 80 primary rows")
    check(table["n_bgs"].nunique() == 1 and int(table["n_bgs"].iloc[0]) == 4,
          "every scenario uses the identical four BG clusters")
    equal_row = table.loc[table["scenario"] == "equal_baseline"].iloc[0]
    check(equal_row["baseline_max_abs_diff"] <= 2e-6,
          "equal scenario exactly reproduces saved mean_csi_tree")
    check((table["verdict"] == "no robust threshold detected").all(),
          "four-BG cluster gate prevents a robust claim under every weight")
    bad = False
    try:
        sec14.csi_weight_sensitivity_table(
            frame, scenarios=(("equal", 0.5, 0.5), ("bad", 0.8, 0.8)), n_boot=2)
    except ValueError:
        bad = True
    check(bad, "non-convex scenario weights are rejected")


def test_et_declines_beyond() -> None:
    """ET-decline check: mean ET below vs above the threshold (step 74)."""
    print("\n[et_declines_beyond: mean ET below vs above threshold (step 74)]")
    csi = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
    et = np.array([300.0, 290.0, 310.0, 120.0, 110.0, 100.0])
    d = sec14.et_declines_beyond(csi, et, 0.5)
    check(d["et_declines"], "ET declines beyond threshold (above < below)")
    check(d["mean_et_below"] > d["mean_et_above"], "mean ET below > above")
    check(d["n_below"] == 3 and d["n_above"] == 3, "below/above counts correct")
    d2 = sec14.et_declines_beyond(csi, et[::-1], 0.5)
    check(not d2["et_declines"], "reversed ET -> no decline")
    d3 = sec14.et_declines_beyond(csi, np.array([np.nan]*6), 0.5)
    check(not d3["et_declines"] and d3["n_below"] == 0, "all-NaN ET -> no decline, 0 counts")
    check(not sec14.et_declines_beyond(csi, et, np.nan)["et_declines"],
          "NaN threshold -> et_declines False")


def test_methods_agree() -> None:
    """Methods-agree: change-point inside the bootstrap CI (step 78)."""
    print("\n[methods_agree: change-point inside the bootstrap CI (step 78)]")
    check(sec14.methods_agree(0.4, 0.7, 0.55), "0.55 inside CI (0.4,0.7) -> agree")
    check(not sec14.methods_agree(0.4, 0.7, 0.9), "0.9 outside CI (0.4,0.7) -> disagree")
    check(sec14.methods_agree(0.7, 0.4, 0.55), "CI bounds order-insensitive (still agree)")
    check(not sec14.methods_agree(np.nan, 0.7, 0.55), "non-finite CI bound -> not agree")


def test_methods_agree_within_tolerance() -> None:
    """Methods-agree tolerance band absorbs the pwlf-knee vs ruptures-shift offset."""
    print("\n[methods_agree: tolerance band absorbs knee-vs-shift offset]")
    check(sec14.methods_agree(0.55, 0.57, 0.62, breakpoint=0.56, x_range=1.0),
          "outside a thin CI but within 0.10*range of breakpoint -> agree")
    check(not sec14.methods_agree(0.55, 0.57, 0.72, breakpoint=0.56, x_range=1.0),
          "0.16-range offset is beyond the tightened 0.10 tolerance -> disagree")
    check(sec14.methods_agree(0.4, 0.7, 0.55), "CI-only fallback works (0.55 in [0.4,0.7])")


def test_threshold_verdict_robust_case() -> None:
    """Verdict ROBUST on a constructed plateau-then-decline + ET case (78-79)."""
    print("\n[threshold_verdict: ROBUST on plateau-then-decline + ET case (78-79)]")
    x, y = _kinked(bp=0.55, slope1=0.0, slope2=-16.0, noise=0.5, plateau=6.0, seed=8)
    et = np.where(x < 0.55, 300.0, 120.0)
    groups = np.arange(x.size) % sec14.MIN_CLUSTERS_FOR_CONFIRMATORY_INFERENCE
    res = sec14.analyze_sample(x, y, et=et, n_boot=200, seed=8,
                               label="synthetic-kink", groups=groups)
    v = res["verdict"]
    check(v.methods_agree, "robust: methods agree (within tolerance)")
    check(v.bend_visible, "robust: bend visible (steep post-break slope)")
    check(v.et_corroborates, "robust: ET declines beyond breakpoint")
    check(v.well_identified, "robust: bootstrap CI tight (well identified)")
    check(v.robust and v.label == "robust threshold",
          "ALL gates pass -> robust True, label 'robust threshold'")


def test_threshold_verdict_no_threshold_case() -> None:
    """Verdict NO ROBUST THRESHOLD on a straight line (the honest null)."""
    print("\n[threshold_verdict: NO ROBUST THRESHOLD on a line (the honest null)]")
    x, y = _straight(slope=-1.0, noise=1.0, seed=9)
    et = 200.0 - 50.0 * x
    res = sec14.analyze_sample(x, y, et=et, n_boot=200, seed=9, label="synthetic-line")
    v = res["verdict"]
    check(not v.bend_visible, "line: no bend (slope_change ~ 0)")
    check(not v.well_identified, "line: bootstrap CI wide (not identified)")
    check(not v.robust and v.label == "no robust threshold detected",
          "line yields 'no robust threshold detected' -- a VALID outcome")
    check(not res["comparison"]["segmented_preferred_by_aic"],
          "kink not preferred over the line by AIC")


def test_verdict_gate_logic_controlled() -> None:
    """Each verdict gate is necessary (controlled dict inputs)."""
    print("\n[threshold_verdict: each gate is necessary (controlled inputs)]")
    seg = {"breakpoint": 0.5, "slope_change": -5.0}
    boot = {"ci_low": 0.45, "ci_high": 0.55, "spans_fraction": 0.1, "x_range": 1.0,
            "clustered": True, "n_clusters": 10}
    cp = {"changepoint_csi": 0.5}
    et = {"et_declines": True, "mean_et_below": 300.0, "mean_et_above": 120.0}
    comp = {"delta_r2": 0.2, "delta_aic": -50.0, "segmented_preferred_by_aic": True}
    base = sec14.threshold_verdict(segmented=seg, bootstrap=boot, changepoint=cp,
                                   et_check=et, comparison=comp)
    check(base.robust, "baseline with all gates satisfied -> robust")
    v_unclustered = sec14.threshold_verdict(
        segmented=seg,
        bootstrap={**boot, "clustered": False, "n_clusters": 0},
        changepoint=cp, et_check=et, comparison=comp)
    check(not v_unclustered.cluster_adequate and not v_unclustered.robust,
          "unclustered row bootstrap cannot support a confirmatory threshold claim")
    v_et = sec14.threshold_verdict(segmented=seg, bootstrap=boot, changepoint=cp,
                                   et_check={**et, "et_declines": False}, comparison=comp)
    check(not v_et.robust, "ET not declining -> not robust")
    v_bend = sec14.threshold_verdict(segmented={**seg, "slope_change": -0.1}, bootstrap=boot,
                                     changepoint=cp, et_check=et, comparison=comp)
    check(not v_bend.robust, "no visible bend (slope_change ~ 0) -> not robust")
    v_id = sec14.threshold_verdict(segmented=seg,
                                   bootstrap={**boot, "spans_fraction": 0.8}, changepoint=cp,
                                   et_check=et, comparison=comp)
    check(not v_id.robust, "wide bootstrap CI (not identified) -> not robust")
    v_ag = sec14.threshold_verdict(segmented=seg, bootstrap=boot,
                                   changepoint={"changepoint_csi": 0.95}, et_check=et,
                                   comparison=comp)
    check(not v_ag.robust, "methods disagree (change-point far outside CI & tol) -> not robust")
    v_clusters = sec14.threshold_verdict(
        segmented=seg,
        bootstrap={**boot, "clustered": True, "n_clusters": 9},
        changepoint=cp, et_check=et, comparison=comp)
    check(not v_clusters.cluster_adequate and not v_clusters.robust,
          "nine clustered BGs cannot support a confirmatory threshold claim")
    v_clusters_ok = sec14.threshold_verdict(
        segmented=seg,
        bootstrap={**boot, "clustered": True, "n_clusters": 10},
        changepoint=cp, et_check=et, comparison=comp)
    check(v_clusters_ok.cluster_adequate and v_clusters_ok.robust,
          "cluster-count gate clears at the predeclared 10-BG minimum")


def test_describe_shape() -> None:
    """describe_shape: Pearson/Spearman/OLS slope of the scatter (step 72)."""
    print("\n[describe_shape: Pearson/Spearman/OLS slope of scatter (step 72)]")
    rng = np.random.default_rng(10)
    x = np.sort(rng.uniform(0.0, 1.0, size=200))
    y = -3.0 * x + rng.normal(0.0, 0.2, size=200)
    s = sec14.describe_shape(x, y)
    check(s["pearson_r"] < -0.9, f"strong negative Pearson r ({s['pearson_r']:.3f})")
    check(s["ols_slope"] < -2.5, f"OLS slope near -3 ({s['ols_slope']:.2f})")
    yf = rng.normal(0.0, 1.0, size=200)
    sf = sec14.describe_shape(x, yf)
    check(abs(sf["pearson_r"]) < 0.2, f"flat cloud has ~0 Pearson r ({sf['pearson_r']:.3f})")


def test_split_day_night() -> None:
    """split_day_night partitions on is_day and intersects an optional keep_mask (B4)."""
    print("\n[split_day_night: partition on is_day; intersect keep_mask (B4)]")
    is_day = np.array([True, True, False, True, False, False])
    day, night = sec14.split_day_night(is_day)
    check(day.tolist() == [True, True, False, True, False, False],
          "day mask selects exactly the is_day=True rows")
    check(night.tolist() == [False, False, True, False, True, True],
          "night mask selects exactly the is_day=False rows")
    check(bool(np.all(day ^ night)) and not bool(np.any(day & night)),
          "day and night are complementary and disjoint (tile all rows, no keep_mask)")
    keep = np.array([True, False, True, True, True, False])
    day_k, night_k = sec14.split_day_night(is_day, keep_mask=keep)
    check(day_k.tolist() == [True, False, False, True, False, False],
          "day&keep drops the filtered-out day row (index 1)")
    check(night_k.tolist() == [False, False, True, False, True, False],
          "night&keep drops the filtered-out night row (index 5)")
    check(not bool(np.any((day_k | night_k) & ~keep)),
          "no kept-partition row falls outside keep_mask")
    primary = sec14.primary_sample_mask(
        is_day, np.array([3, 2, 5, 10, 1, 4]), min_count=3)
    check(primary.tolist() == [True, False, False, True, False, False],
          "primary mask requires BOTH daytime and the tree-pixel floor")


def test_daynight_contrast() -> None:
    """daynight_contrast recovers day/night intercepts and slopes via a pure-numpy OLS (B4)."""
    print("\n[daynight_contrast: recover +4.8 day vs +0.4 night intercepts + slope (B4)]")
    rng = np.random.default_rng(20240615)
    n = 300
    slope = -2.0
    xd = rng.uniform(0.0, 1.0, size=n)
    xn = rng.uniform(0.0, 1.0, size=n)
    yd = 4.8 + slope * xd + rng.normal(0.0, 0.05, size=n)   # DAY: intercept ~ +4.8
    yn = 0.4 + slope * xn + rng.normal(0.0, 0.05, size=n)   # NIGHT: intercept ~ +0.4
    x = np.concatenate([xd, xn])
    y = np.concatenate([yd, yn])
    is_day = np.concatenate([np.ones(n, bool), np.zeros(n, bool)])
    r = sec14.daynight_contrast(x, y, is_day)
    check(r["n_day"] == n and r["n_night"] == n, "day/night row counts split correctly")
    check(abs(r["day_intercept"] - 4.8) < 0.1,
          f"day intercept ~ +4.8 (got {r['day_intercept']:.3f})")
    check(abs(r["night_intercept"] - 0.4) < 0.1,
          f"night intercept ~ +0.4 (got {r['night_intercept']:.3f})")
    check(abs(r["delta_intercept"] - 4.4) < 0.15,
          f"delta_intercept = day - night ~ +4.4 (got {r['delta_intercept']:.3f})")
    check(r["delta_intercept"] > 3.0, "delta_intercept strongly POSITIVE (day >> night)")
    check(abs(r["day_slope"] - slope) < 0.15 and abs(r["night_slope"] - slope) < 0.15,
          f"both slopes ~ {slope} (day {r['day_slope']:.2f}, night {r['night_slope']:.2f})")
    check(abs(r["delta_slope"]) < 0.2,
          f"delta_slope ~ 0 (parallel slopes) (got {r['delta_slope']:.3f})")
    # Degenerate guards: all-day and too-few rows return NaN delta (interaction unidentified).
    rg = sec14.daynight_contrast(xd, yd, np.ones(n, bool))
    check(not np.isfinite(rg["delta_intercept"]),
          "all-day input -> delta_intercept NaN (night side empty, unidentified)")


def test_night_does_not_flatten_day_signal() -> None:
    """Pooling day+night dilutes the day intercept; day-only delta_intercept stays strong (B4)."""
    print("\n[night_does_not_flatten_day_signal: pooling dilutes, day-only recovers (B4)]")
    # DAY: a genuine plateau-then-decline signal (the cooling advantage), high level ~ +4.8 K.
    xd, yd = _kinked(n=240, bp=0.6, slope1=0.0, slope2=-12.0, noise=0.2, plateau=4.8, seed=11)
    # NIGHT: flat, near zero (~ +0.4 K), no signal.
    rng = np.random.default_rng(12)
    xn = np.sort(rng.uniform(0.0, 1.0, size=240))
    yn = 0.4 + rng.normal(0.0, 0.2, size=240)
    x = np.concatenate([xd, xn])
    y = np.concatenate([yd, yn])
    is_day = np.concatenate([np.ones(xd.size, bool), np.zeros(xn.size, bool)])

    # (1) Day/night contrast on the POOLED data: day intercept >> night, delta strongly positive.
    r = sec14.daynight_contrast(x, y, is_day)
    check(r["delta_intercept"] > 3.0,
          f"day-vs-night delta_intercept strongly POSITIVE ({r['delta_intercept']:.2f})")
    check(r["day_intercept"] > r["night_intercept"] + 3.0,
          f"day intercept ({r['day_intercept']:.2f}) >> night intercept ({r['night_intercept']:.2f})")

    # (2) A single pooled OLS line DILUTES the day intercept toward the night level: the pooled
    #     intercept sits between the night and day intercepts, understating the daytime signal.
    lin_pooled = sec14.linear_fit(x, y)
    check(r["night_intercept"] < lin_pooled["intercept"] < r["day_intercept"],
          f"pooled intercept ({lin_pooled['intercept']:.2f}) diluted between night "
          f"({r['night_intercept']:.2f}) and day ({r['day_intercept']:.2f})")
    lin_day = sec14.linear_fit(xd, yd)
    check(lin_pooled["intercept"] < lin_day["intercept"] - 1.5,
          f"pooling drags the intercept well below the day-only fit "
          f"({lin_pooled['intercept']:.2f} vs day-only {lin_day['intercept']:.2f})")

    # (3) OPTIONAL: the segmented/change-point path needs pwlf/ruptures. Exercise it only if the
    #     libs import; skip-with-a-note otherwise so the suite passes in the bare test env.
    try:
        seg_day = sec14.segmented_fit(xd, yd)
        seg_pool = sec14.segmented_fit(x, y)
        check(seg_day["slope_change"] < -6.0,
              f"day-only segmented recovers the bend (slope_change {seg_day['slope_change']:.2f})")
        check(seg_pool["slope_change"] > seg_day["slope_change"],
              "pooling with flat night weakens the recovered bend (less negative slope_change)")
    except ImportError:
        print("  skip: pwlf not installed -> segmented cross-check skipped "
              "(day-only delta_intercept already proven via daynight_contrast)")


def main() -> int:
    tests = [
        test_segmented_recovers_known_breakpoint,
        test_segmented_returns_breakpoint_on_straight_line,
        test_compare_linear_segmented,
        test_bin_means,
        test_apply_min_count,
        test_split_day_night,
        test_daynight_contrast,
        test_night_does_not_flatten_day_signal,
        test_bootstrap_breakpoint,
        test_cluster_bootstrap_draws_whole_bgs,
        test_cluster_bootstrap_wider_than_iid,
        test_changepoint_csi,
        test_csi_weight_sensitivity_uses_identical_primary_rows,
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
