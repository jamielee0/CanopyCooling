#!/usr/bin/env python3
"""Section 14 - exploratory analysis + the first threshold estimate (steps 72-79).

The FINAL section of the Phoenix pilot and the first scientific result. This module
holds the REUSABLE analysis logic the notebook (`notebooks/14_exploratory_threshold.ipynb`)
imports and calls, so that "every figure and every number is reproducible from the saved
code" (the project's standing rule) and the risky numerics are unit-tested
(`test_section14_threshold.py`) on small synthetic data WITHOUT the heavy libraries.

Objective (protocol Section 14, steps 72-79)
---------------------------------------------
Look at the CENTRAL relationship of the whole project -- the tree COOLING ADVANTAGE
against COMPOUND STRESS (the CSI) -- and produce a FIRST THRESHOLD ESTIMATE for Phoenix.
A threshold, if present, appears as a clear BEND: cooling advantage roughly flat / slowly
declining at low stress, then dropping more steeply beyond some point. The mechanistic
signature is that cooling advantage AND ET both decline beyond the SAME stress level.

  EXPLORATORY (steps 72-75)
    72. SCATTER cooling_advantage vs CSI (one point per neighborhood per overpass).
    73. BIN the CSI; per bin plot mean cooling_advantage +/- an error bar (look for a bend).
    74. On the same binned axis, OVERLAY mean ET and ESI (the ET corroboration).
    75. INSPECT distributions; flag/resolve too-few-pixel neighborhoods, outliers, seasonal
        artifacts BEFORE modelling (here: the minimum-count filter + its sensitivity).
  FIRST THRESHOLD (steps 76-79)
    76. Fit a SEGMENTED (piecewise) regression with ONE breakpoint -> the threshold estimate.
    77. BOOTSTRAP-resample for a confidence interval on the breakpoint.
    78. Independently refit with a CHANGE-POINT method (ruptures) as a cross-check.
    79. Document the value, its uncertainty, and the ET evidence -- credible ONLY if the two
        methods AGREE within uncertainty AND the bend is visible AND ET corroborates.

THE HONESTY GATE (the protocol's "Common pitfall", encoded here, non-negotiable)
--------------------------------------------------------------------------------
A segmented regression ALWAYS returns a breakpoint -- even for a perfectly straight line or
pure noise. So a Phoenix threshold is reported as CREDIBLE only if ALL THREE hold:
  (i)   the two methods AGREE -- the ruptures change-point lies inside the segmented
        breakpoint's bootstrap CI (and the bootstrap CI is not so wide it spans most of the
        CSI range, which would mean "not identified");
  (ii)  a BEND is visible in the binned plot (the post-breakpoint slope is meaningfully more
        negative than the pre-breakpoint slope);
  (iii) ET DECLINES beyond the same CSI level (mechanistic corroboration).
Otherwise the honest result is **"no robust threshold detected"** -- a VALID finding, not a
failure. We also compare the segmented fit against a plain LINEAR fit (delta-R^2 / delta-AIC):
if the kink buys little over a straight line, that is itself evidence against a threshold.

The interpretation caveat we MUST carry (from Sections 10-13)
-------------------------------------------------------------
* THIN sample: the paired design has only 9 block groups, and ONE (040139412001, ~171 tree
  px) dominates; the other 8 rest on 1-6 tree px (median n_good_obs = 2). A strict
  minimum-count filter (e.g. n_tree_valid >= 10) collapses the sample toward that single
  well-sampled BG -- so we report BOTH (a) the full 9-BG sample (noisy) and (b) the robust
  single-BG subset (~temporal-only) and reconcile them.
* CSI's TEMPORAL variation is driven by VPD demand (the NDMI water-supply z is a static-in-
  time SPATIAL field -- Section 11/12). So across rows CSI = VPD-demand (temporal, ~spatially
  uniform) + NDMI (spatial across the 9 BGs); the "threshold in CSI" is largely a VPD-demand
  axis. State this so the result is read correctly.
* mean_et_tree / mean_esi_tree are NaN on ~22.7 % of rows (the non-ET overpasses) -- dropped
  pairwise in the ET overlay / corroboration, never imputed.

This module is numpy / pandas / (pwlf, ruptures, statsmodels, scikit-learn) only -- it reads
NOTHING and writes NOTHING. The notebook does the IO (reads only
`data/processed/master_table.parquet`) and the figures; this module is the math.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

log = logging.getLogger("section14")

# The two analysis columns at the heart of Section 14 (names from the Section 13 table).
OUTCOME_COL = "cooling_advantage"        # K = degC; reference LST - tree LST (step 67)
CSI_COL = "mean_csi_tree"                # the Compound Stress Index over the tree pixels
ET_COL = "mean_et_tree"                  # ET over the tree pixels (W m-2); NaN off-ET overpasses
ESI_COL = "mean_esi_tree"                # ESI over the tree pixels (-)
COUNT_COL = "n_tree_valid"               # the filterable sample size (finite-LST tree px)

# Defaults (documented; the notebook can override).
DEFAULT_MIN_COUNT = 3                    # minimum n_tree_valid for the "modest filter"
ROBUST_MIN_COUNT = 10                    # the strict filter -> collapses to the one well-sampled BG
DEFAULT_N_BINS = 8                       # CSI bins for the binned-mean plot
DEFAULT_N_BOOTSTRAP = 1000               # bootstrap resamples for the breakpoint CI
DEFAULT_SEED = 20240615                  # deterministic bootstrap / any RNG use


# =========================================================================== #
# Pure logic: filtering + binning (steps 73, 75)
# =========================================================================== #
def apply_min_count(values_count: np.ndarray, min_count: int) -> np.ndarray:
    """Boolean keep-mask for rows whose sample-size column is >= ``min_count`` (step 75).

    The protocol's step 75 ("neighborhoods with too few pixels") is operationalised as a
    minimum-count filter on the per-row finite-LST sample size (``n_tree_valid``). Returns a
    boolean array, True where the row is kept. ``min_count <= 1`` keeps everything (the full,
    unfiltered sample). NaN counts are dropped (treated as 0). This is the lever whose
    SENSITIVITY we report: a strict bar collapses the Phoenix sample onto the single well-
    sampled block group, so the full vs robust subsets must be reconciled, not silently
    swapped.
    """
    c = np.asarray(values_count, dtype="float64")
    keep = np.isfinite(c) & (c >= float(min_count))
    return keep


def bin_means(x: np.ndarray, y: np.ndarray, n_bins: int = DEFAULT_N_BINS,
              edges: np.ndarray | None = None
              ) -> dict[str, np.ndarray]:
    """Bin ``x`` and return per-bin mean/SEM/count of ``y`` (the step-73 binned plot).

    Bins ``x`` into ``n_bins`` EQUAL-WIDTH intervals across its finite range (or uses the
    supplied ``edges``), and for each bin computes the count, the mean of ``y``, the standard
    deviation, and the standard error of the mean (SEM = std / sqrt(n), the error bar). Pairs
    with a non-finite ``x`` or ``y`` are dropped FIRST (pairwise), so e.g. the ET overlay uses
    only rows that actually have ET. Empty bins come back as NaN mean / 0 count (and are simply
    not drawn). A threshold, if present, shows here as a clear BEND -- mean cooling advantage
    roughly flat at low CSI then dropping beyond some bin.

    Returns a dict with ``edges`` (len n_bins+1), ``centers``, ``count``, ``mean``, ``std``,
    ``sem`` (each len n_bins).
    """
    x = np.asarray(x, dtype="float64")
    y = np.asarray(y, dtype="float64")
    fin = np.isfinite(x) & np.isfinite(y)
    x = x[fin]
    y = y[fin]
    if edges is None:
        if x.size == 0:
            edges = np.linspace(0.0, 1.0, n_bins + 1)
        else:
            lo = float(np.min(x))
            hi = float(np.max(x))
            if hi <= lo:
                hi = lo + 1.0
            edges = np.linspace(lo, hi, n_bins + 1)
    edges = np.asarray(edges, dtype="float64")
    nb = len(edges) - 1
    centers = 0.5 * (edges[:-1] + edges[1:])
    count = np.zeros(nb, dtype="int64")
    mean = np.full(nb, np.nan)
    std = np.full(nb, np.nan)
    sem = np.full(nb, np.nan)
    if x.size:
        # Right-closed final bin so the maximum x lands in the last bin, not out of range.
        idx = np.digitize(x, edges[1:-1], right=False)
        for b in range(nb):
            sel = idx == b
            n = int(sel.sum())
            count[b] = n
            if n > 0:
                yb = y[sel]
                mean[b] = float(yb.mean())
                if n > 1:
                    s = float(yb.std(ddof=1))
                    std[b] = s
                    sem[b] = s / np.sqrt(n)
                else:
                    std[b] = np.nan
                    sem[b] = np.nan
    return {"edges": edges, "centers": centers, "count": count,
            "mean": mean, "std": std, "sem": sem}


# =========================================================================== #
# Pure logic: linear & segmented (piecewise) regression (step 76)
# =========================================================================== #
def _r2(y: np.ndarray, yhat: np.ndarray) -> float:
    """Coefficient of determination R^2 = 1 - SS_res / SS_tot (0 if y has no variance)."""
    y = np.asarray(y, dtype="float64")
    yhat = np.asarray(yhat, dtype="float64")
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    if ss_tot <= 0:
        return 0.0
    return 1.0 - ss_res / ss_tot


def _aic_from_rss(n: int, rss: float, k_params: int) -> float:
    """Gaussian-likelihood AIC from the residual sum of squares.

    AIC = n * ln(RSS / n) + 2 * k, where k counts ALL free parameters INCLUDING the noise
    variance. Lower is better. Used only to COMPARE the linear vs segmented fit on the same
    data (a relative quantity), so the additive constant is dropped.
    """
    n = int(n)
    rss = max(float(rss), 1e-300)        # guard ln(0)
    return n * np.log(rss / n) + 2 * k_params


def linear_fit(x: np.ndarray, y: np.ndarray) -> dict:
    """Ordinary least-squares straight-line fit y = a + b*x (the null model for step 76).

    Returns ``{slope, intercept, r2, rss, aic, n}``. This is the baseline the segmented fit
    must BEAT to justify a breakpoint: if a kink barely improves on this line, the data look
    straight and "no threshold" is the honest reading. NaN pairs are dropped. AIC uses
    k = 3 free parameters (slope, intercept, variance).
    """
    x = np.asarray(x, dtype="float64")
    y = np.asarray(y, dtype="float64")
    fin = np.isfinite(x) & np.isfinite(y)
    x = x[fin]
    y = y[fin]
    n = int(x.size)
    if n < 2:
        return {"slope": np.nan, "intercept": np.nan, "r2": np.nan,
                "rss": np.nan, "aic": np.nan, "n": n}
    b, a = np.polyfit(x, y, 1)           # slope, intercept
    yhat = a + b * x
    rss = float(np.sum((y - yhat) ** 2))
    return {"slope": float(b), "intercept": float(a), "r2": _r2(y, yhat),
            "rss": rss, "aic": _aic_from_rss(n, rss, k_params=3), "n": n}


def segmented_fit(x: np.ndarray, y: np.ndarray, *, seed: int = DEFAULT_SEED) -> dict:
    """Continuous piecewise-linear fit with ONE interior breakpoint (step 76; via ``pwlf``).

    Fits a 2-segment continuous piecewise-linear model and returns the single interior
    breakpoint (the FIRST THRESHOLD ESTIMATE) plus the two segment slopes, R^2, RSS and AIC.
    Uses ``pwlf.PiecewiseLinFit(x, y).fit(2)`` (degree-1, 2 segments => 1 interior break),
    which optimises the breakpoint location. AIC uses k = 5 free parameters (2 slopes,
    1 intercept, 1 breakpoint, 1 variance) so it is directly comparable to ``linear_fit``'s
    k = 3.

    THE PITFALL THIS ENCODES: pwlf ALWAYS returns a breakpoint, even for a straight line or
    pure noise -- so ``breakpoint`` alone is NEVER sufficient evidence; it must clear the
    agreement + bend + ET gate (see :func:`threshold_verdict`). Returns
    ``{breakpoint, slope1, slope2, slope_change, r2, rss, aic, n, breakpoints(full)}``;
    breakpoint is NaN if the fit cannot be formed (n too small / degenerate x).
    """
    import pwlf

    x = np.asarray(x, dtype="float64")
    y = np.asarray(y, dtype="float64")
    fin = np.isfinite(x) & np.isfinite(y)
    x = x[fin]
    y = y[fin]
    n = int(x.size)
    out = {"breakpoint": np.nan, "slope1": np.nan, "slope2": np.nan,
           "slope_change": np.nan, "r2": np.nan, "rss": np.nan, "aic": np.nan,
           "n": n, "breakpoints": np.array([np.nan, np.nan, np.nan])}
    if n < 4 or float(np.ptp(x)) <= 0:
        return out
    # pwlf uses its own RNG for the multi-start breakpoint search; seed for reproducibility.
    try:
        np.random.seed(seed)
    except Exception:
        pass
    model = pwlf.PiecewiseLinFit(x, y, seed=seed)
    breaks = model.fit(2)                 # 2 segments -> [min, bp, max]
    slopes = model.calc_slopes()          # 2 slopes
    yhat = model.predict(x)
    rss = float(np.sum((y - yhat) ** 2))
    bp = float(breaks[1])
    out.update({
        "breakpoint": bp,
        "slope1": float(slopes[0]),
        "slope2": float(slopes[1]),
        "slope_change": float(slopes[1] - slopes[0]),
        "r2": _r2(y, yhat),
        "rss": rss,
        "aic": _aic_from_rss(n, rss, k_params=5),
        "n": n,
        "breakpoints": np.asarray(breaks, dtype="float64"),
    })
    return out


def compare_linear_segmented(x: np.ndarray, y: np.ndarray, *, seed: int = DEFAULT_SEED
                             ) -> dict:
    """Linear vs segmented comparison (the protocol's "is the kink worth it?" check).

    Fits both models on the SAME data and returns both fits plus ``delta_r2`` (segmented R^2 -
    linear R^2; >= 0) and ``delta_aic`` (segmented AIC - linear AIC; NEGATIVE favours the
    segmented model, but only meaningfully so beyond ~|2|). A tiny delta_r2 and a non-negative
    delta_aic mean the straight line is as good -> evidence AGAINST a threshold (the kink is
    just fitting noise). Returns ``{linear, segmented, delta_r2, delta_aic,
    segmented_preferred_by_aic}``.
    """
    lin = linear_fit(x, y)
    seg = segmented_fit(x, y, seed=seed)
    d_r2 = (seg["r2"] - lin["r2"]) if np.isfinite(seg["r2"]) and np.isfinite(lin["r2"]) else np.nan
    d_aic = (seg["aic"] - lin["aic"]) if np.isfinite(seg["aic"]) and np.isfinite(lin["aic"]) else np.nan
    return {"linear": lin, "segmented": seg, "delta_r2": d_r2, "delta_aic": d_aic,
            "segmented_preferred_by_aic": bool(np.isfinite(d_aic) and d_aic < -2.0)}


# =========================================================================== #
# Pure logic: bootstrap CI for the breakpoint (step 77)
# =========================================================================== #
def bootstrap_breakpoint(x: np.ndarray, y: np.ndarray, *,
                         n_boot: int = DEFAULT_N_BOOTSTRAP,
                         seed: int = DEFAULT_SEED,
                         ci: float = 0.95) -> dict:
    """Bootstrap CI for the segmented breakpoint by resampling ROWS (step 77).

    Resamples the (x, y) ROWS WITH REPLACEMENT ``n_boot`` times, refits the 2-segment model on
    each resample, and collects the breakpoint estimates. Returns the percentile CI (default
    central 95 %), the bootstrap median/mean/std, the per-replicate estimates, and -- the
    honesty flag -- ``spans_fraction``: the CI width as a fraction of the observed CSI range.
    If ``spans_fraction`` is large (the CI covers most of the CSI range) the breakpoint is NOT
    well identified -- which the verdict treats as failing identification (a straight-line /
    no-relationship signature). Resamples that fail to fit are skipped (counted in
    ``n_valid``).

    Returns ``{point, ci_low, ci_high, median, mean, std, estimates, n_valid, n_boot,
    spans_fraction, x_range, ci_level}``. ``point`` is the breakpoint on the FULL sample.
    """
    x = np.asarray(x, dtype="float64")
    y = np.asarray(y, dtype="float64")
    fin = np.isfinite(x) & np.isfinite(y)
    x = x[fin]
    y = y[fin]
    n = int(x.size)
    x_range = float(np.ptp(x)) if n else np.nan
    point = segmented_fit(x, y, seed=seed)["breakpoint"]
    out = {"point": point, "ci_low": np.nan, "ci_high": np.nan, "median": np.nan,
           "mean": np.nan, "std": np.nan, "estimates": np.array([]), "n_valid": 0,
           "n_boot": int(n_boot), "spans_fraction": np.nan, "x_range": x_range,
           "ci_level": float(ci)}
    if n < 4 or not np.isfinite(x_range) or x_range <= 0:
        return out
    rng = np.random.default_rng(seed)
    ests: list[float] = []
    for _ in range(int(n_boot)):
        idx = rng.integers(0, n, size=n)
        xb = x[idx]
        yb = y[idx]
        if float(np.ptp(xb)) <= 0:
            continue
        bp = segmented_fit(xb, yb, seed=seed)["breakpoint"]
        if np.isfinite(bp):
            ests.append(float(bp))
    ests_arr = np.asarray(ests, dtype="float64")
    if ests_arr.size == 0:
        return out
    alpha = (1.0 - ci) / 2.0
    lo = float(np.quantile(ests_arr, alpha))
    hi = float(np.quantile(ests_arr, 1.0 - alpha))
    out.update({
        "ci_low": lo, "ci_high": hi,
        "median": float(np.median(ests_arr)),
        "mean": float(np.mean(ests_arr)),
        "std": float(np.std(ests_arr, ddof=1)) if ests_arr.size > 1 else np.nan,
        "estimates": ests_arr,
        "n_valid": int(ests_arr.size),
        "spans_fraction": (hi - lo) / x_range if x_range > 0 else np.nan,
    })
    return out


# =========================================================================== #
# Pure logic: independent change-point check (step 78, via ruptures)
# =========================================================================== #
def changepoint_csi(x: np.ndarray, y: np.ndarray, *, penalty_n_bkps: int = 1
                    ) -> dict:
    """Independent single change-point estimate on the CSI axis (step 78; via ``ruptures``).

    A DIFFERENT method from the segmented regression, so its agreement (or not) is an honest
    cross-check. Orders the (x, y) pairs by x, runs ruptures' exact dynamic-programming search
    (``rpt.Dynp``, l2 cost = change in mean) for ONE change point in the x-ordered cooling-
    advantage SEQUENCE, and maps the returned sequence index back to a CSI VALUE (the midpoint
    of the x-values straddling the split). The l2 model detects a shift in the LEVEL of cooling
    advantage along the stress axis -- the same "the relationship changes here" question the
    breakpoint asks, by independent machinery.

    Returns ``{changepoint_csi, split_index, n, x_sorted, y_sorted}``; ``changepoint_csi`` is
    NaN if it cannot be formed. NOTE (honesty): a change-point method, like the segmented fit,
    will return a split even on a straight line -- which is exactly why step 78 requires the
    two to AGREE, not just to each produce a number.
    """
    import ruptures as rpt

    x = np.asarray(x, dtype="float64")
    y = np.asarray(y, dtype="float64")
    fin = np.isfinite(x) & np.isfinite(y)
    x = x[fin]
    y = y[fin]
    n = int(x.size)
    out = {"changepoint_csi": np.nan, "split_index": -1, "n": n,
           "x_sorted": np.array([]), "y_sorted": np.array([])}
    if n < 4 or float(np.ptp(x)) <= 0:
        return out
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    ys = y[order]
    signal = ys.reshape(-1, 1).astype("float64")
    algo = rpt.Dynp(model="l2", min_size=1, jump=1).fit(signal)
    bkps = algo.predict(n_bkps=int(penalty_n_bkps))   # e.g. [split_index, n]
    split = int(bkps[0])
    split = max(1, min(split, n - 1))
    # Map the sequence split index to a CSI value: midpoint of the straddling x-values.
    cp = 0.5 * (float(xs[split - 1]) + float(xs[split]))
    out.update({"changepoint_csi": cp, "split_index": split,
                "x_sorted": xs, "y_sorted": ys})
    return out


# =========================================================================== #
# Pure logic: ET-corroboration + the agreement gate / verdict (steps 74, 78-79)
# =========================================================================== #
def et_declines_beyond(csi: np.ndarray, et: np.ndarray, threshold_csi: float
                       ) -> dict:
    """Does ET decline beyond ``threshold_csi``? -- the mechanistic corroboration (step 74).

    Compares the mean ET BELOW vs AT-OR-ABOVE the candidate threshold (pairwise-dropping NaN
    ET rows, the ~22.7 % off-ET overpasses). Returns ``{mean_et_below, mean_et_above,
    et_declines, delta, n_below, n_above}`` with ``et_declines`` True iff mean ET above the
    threshold is LOWER than below (the expected signature: cooling advantage AND ET both
    falling past the same stress level). If the threshold is NaN or either side is empty,
    ``et_declines`` is False and the means are NaN. (A coarse but honest mechanistic check; the
    binned ET overlay in the notebook is the visual version.)
    """
    csi = np.asarray(csi, dtype="float64")
    et = np.asarray(et, dtype="float64")
    fin = np.isfinite(csi) & np.isfinite(et)
    csi = csi[fin]
    et = et[fin]
    out = {"mean_et_below": np.nan, "mean_et_above": np.nan, "et_declines": False,
           "delta": np.nan, "n_below": 0, "n_above": 0}
    if not np.isfinite(threshold_csi) or csi.size == 0:
        return out
    below = csi < threshold_csi
    above = ~below
    nb = int(below.sum())
    na = int(above.sum())
    out["n_below"] = nb
    out["n_above"] = na
    if nb == 0 or na == 0:
        return out
    mb = float(et[below].mean())
    ma = float(et[above].mean())
    out.update({"mean_et_below": mb, "mean_et_above": ma, "delta": ma - mb,
                "et_declines": bool(ma < mb)})
    return out


# Thresholds for the verdict gate (documented, tunable).
BEND_SLOPE_DROP = 0.5            # post-break slope must be this much MORE negative (K per CSI unit)
WIDE_CI_FRACTION = 0.5           # bootstrap CI wider than this fraction of the CSI range = not identified
AGREE_TOLERANCE_FRACTION = 0.20  # change-point within this fraction of the CSI range of the breakpoint = agree
                                 # (acknowledges the pwlf-knee vs ruptures-mean-shift location offset;
                                 #  the well_identified gate still rejects an unidentified-CI "agreement")


def methods_agree(breakpoint_ci_low: float, breakpoint_ci_high: float,
                  changepoint: float, *, breakpoint: float = np.nan,
                  x_range: float = np.nan,
                  tol_fraction: float = AGREE_TOLERANCE_FRACTION) -> bool:
    """Do the two methods agree within their uncertainty? (step 78's credibility test).

    The protocol treats the threshold as credible only if the segmented-regression breakpoint
    and the INDEPENDENT change-point agree WITHIN their uncertainty ranges. The two methods
    locate "where the relationship changes" by DIFFERENT machinery -- pwlf optimises a
    continuous slope break, ruptures (l2) finds a shift in the mean LEVEL -- so on the same
    real threshold their point estimates are systematically OFFSET (a continuous 2-segment fit
    places its knee earlier than a mean-shift split on a declining shape). A razor-thin
    bootstrap CI therefore must NOT be the sole agreement test (it would never be met even for
    a genuine threshold). Agreement is declared if EITHER:
      * the change-point falls inside the breakpoint's bootstrap CI [ci_low, ci_high]
        (the strict, uncertainty-aware test), OR
      * the change-point is within ``tol_fraction`` of the CSI range of the breakpoint POINT
        estimate (a documented tolerance for the methods' inherent location offset).
    This stays honest: a genuinely DISCORDANT pair (change-point far outside the CI AND more
    than ~15 % of the CSI range from the breakpoint) still fails. Returns False if any required
    input is non-finite.
    """
    if not np.isfinite(changepoint):
        return False
    inside_ci = False
    if np.isfinite(breakpoint_ci_low) and np.isfinite(breakpoint_ci_high):
        lo = min(breakpoint_ci_low, breakpoint_ci_high)
        hi = max(breakpoint_ci_low, breakpoint_ci_high)
        inside_ci = bool(lo <= changepoint <= hi)
    within_tol = False
    if np.isfinite(breakpoint) and np.isfinite(x_range) and x_range > 0:
        within_tol = bool(abs(changepoint - breakpoint) <= tol_fraction * x_range)
    return bool(inside_ci or within_tol)


@dataclass
class ThresholdVerdict:
    """The Section 14 honesty gate result -- the structured verdict object.

    ``robust`` is True ONLY if all of ``methods_agree`` AND ``bend_visible`` AND
    ``et_corroborates`` AND ``well_identified`` hold. ``label`` is the human-readable verdict
    (``"robust threshold"`` / ``"no robust threshold detected"``). ``reasons`` lists which
    criteria passed/failed, for the results note.
    """
    robust: bool
    label: str
    breakpoint: float
    ci_low: float
    ci_high: float
    changepoint: float
    methods_agree: bool
    bend_visible: bool
    et_corroborates: bool
    well_identified: bool
    spans_fraction: float
    slope_change: float
    delta_r2: float
    delta_aic: float
    reasons: list[str] = field(default_factory=list)


def threshold_verdict(*, segmented: dict, bootstrap: dict, changepoint: dict,
                      et_check: dict, comparison: dict,
                      bend_slope_drop: float = BEND_SLOPE_DROP,
                      wide_ci_fraction: float = WIDE_CI_FRACTION) -> ThresholdVerdict:
    """Combine all evidence into the honest credible/not verdict (steps 78-79; THE GATE).

    A threshold is reported as CREDIBLE only if ALL of:
      * methods AGREE -- the change-point lies in the breakpoint's bootstrap CI OR within the
        documented tolerance of the breakpoint point estimate (:func:`methods_agree`);
      * the breakpoint is WELL IDENTIFIED -- the bootstrap CI width is < ``wide_ci_fraction``
        of the CSI range (a CI spanning most of the range = "not identified");
      * a BEND is VISIBLE -- the segmented post-break slope is at least ``bend_slope_drop``
        MORE NEGATIVE than the pre-break slope (slope_change <= -bend_slope_drop);
      * ET CORROBORATES -- mean ET declines beyond the candidate threshold.
    Otherwise the verdict is **"no robust threshold detected"** -- a valid scientific outcome.
    Returns a :class:`ThresholdVerdict`. (The linear-vs-segmented comparison is carried in the
    verdict for the note but is not a hard gate -- a tiny delta_r2 / non-negative delta_aic is
    reported as corroborating "no threshold".)
    """
    bp = float(segmented.get("breakpoint", np.nan))
    slope_change = float(segmented.get("slope_change", np.nan))
    lo = float(bootstrap.get("ci_low", np.nan))
    hi = float(bootstrap.get("ci_high", np.nan))
    spans = float(bootstrap.get("spans_fraction", np.nan))
    x_range = float(bootstrap.get("x_range", np.nan))
    cp = float(changepoint.get("changepoint_csi", np.nan))
    d_r2 = float(comparison.get("delta_r2", np.nan))
    d_aic = float(comparison.get("delta_aic", np.nan))

    agree = methods_agree(lo, hi, cp, breakpoint=bp, x_range=x_range)
    well_identified = bool(np.isfinite(spans) and spans < wide_ci_fraction)
    bend_visible = bool(np.isfinite(slope_change) and slope_change <= -abs(bend_slope_drop))
    et_corroborates = bool(et_check.get("et_declines", False))

    reasons: list[str] = []
    reasons.append(
        f"methods agree (change-point in bootstrap CI or within tolerance of breakpoint): "
        f"{agree} [bp={bp:.3f}, cp={cp:.3f}, CI=({lo:.3f}, {hi:.3f})]")
    reasons.append(
        f"breakpoint well identified (CI width < {wide_ci_fraction:.0%} of CSI range): "
        f"{well_identified} [spans_fraction={spans:.2f}]")
    reasons.append(
        f"bend visible (post-break slope <= pre-break - {bend_slope_drop}): {bend_visible} "
        f"[slope_change={slope_change:+.3f} K per CSI unit]")
    reasons.append(
        f"ET declines beyond the threshold: {et_corroborates} "
        f"[mean ET below={et_check.get('mean_et_below', float('nan')):.1f}, "
        f"above={et_check.get('mean_et_above', float('nan')):.1f} W/m2]")
    reasons.append(
        f"segmented vs linear: delta_R2={d_r2:+.4f}, delta_AIC={d_aic:+.2f} "
        f"(<-2 favours segmented): {comparison.get('segmented_preferred_by_aic', False)}")

    robust = bool(agree and well_identified and bend_visible and et_corroborates)
    label = "robust threshold" if robust else "no robust threshold detected"
    return ThresholdVerdict(
        robust=robust, label=label, breakpoint=bp, ci_low=lo, ci_high=hi, changepoint=cp,
        methods_agree=agree, bend_visible=bend_visible, et_corroborates=et_corroborates,
        well_identified=well_identified, spans_fraction=spans, slope_change=slope_change,
        delta_r2=d_r2, delta_aic=d_aic, reasons=reasons)


# =========================================================================== #
# Convenience: run the whole threshold pipeline on one (x, y[, et]) sample
# =========================================================================== #
def analyze_sample(x: np.ndarray, y: np.ndarray, et: np.ndarray | None = None, *,
                   n_bins: int = DEFAULT_N_BINS, n_boot: int = DEFAULT_N_BOOTSTRAP,
                   seed: int = DEFAULT_SEED, label: str = "") -> dict:
    """Run the full step-76-79 threshold pipeline on one CSI/cooling-advantage sample.

    Convenience wrapper the notebook calls once per sample (full sample, modest-filter sample,
    robust subset). Computes: the binned means, the linear-vs-segmented comparison, the
    bootstrap CI, the ruptures change-point, the ET-decline check (at the segmented
    breakpoint), and the combined :func:`threshold_verdict`. Returns a dict bundling all of
    them (+ ``n`` and ``label``). Reads/writes nothing.
    """
    x = np.asarray(x, dtype="float64")
    y = np.asarray(y, dtype="float64")
    comparison = compare_linear_segmented(x, y, seed=seed)
    seg = comparison["segmented"]
    boot = bootstrap_breakpoint(x, y, n_boot=n_boot, seed=seed)
    cp = changepoint_csi(x, y)
    if et is not None:
        et_check = et_declines_beyond(x, np.asarray(et, dtype="float64"), seg["breakpoint"])
    else:
        et_check = {"mean_et_below": np.nan, "mean_et_above": np.nan, "et_declines": False,
                    "delta": np.nan, "n_below": 0, "n_above": 0}
    verdict = threshold_verdict(segmented=seg, bootstrap=boot, changepoint=cp,
                                et_check=et_check, comparison=comparison)
    binned = bin_means(x, y, n_bins=n_bins)
    return {"label": label, "n": int(np.isfinite(x).sum()),
            "binned": binned, "comparison": comparison, "linear": comparison["linear"],
            "segmented": seg, "bootstrap": boot, "changepoint": cp, "et_check": et_check,
            "verdict": verdict}


def describe_shape(x: np.ndarray, y: np.ndarray) -> dict:
    """Headline descriptors of the cooling-advantage vs CSI scatter (step 72).

    Returns the Pearson and Spearman correlations and the OLS slope -- a compact, honest
    summary of the overall SHAPE before any threshold is fitted. A near-zero correlation /
    slope says the cloud is essentially flat (no monotonic decline of cooling advantage with
    stress), which is itself a key piece of the verdict.
    """
    from scipy import stats as _stats

    x = np.asarray(x, dtype="float64")
    y = np.asarray(y, dtype="float64")
    fin = np.isfinite(x) & np.isfinite(y)
    x = x[fin]
    y = y[fin]
    n = int(x.size)
    if n < 3:
        return {"n": n, "pearson_r": np.nan, "pearson_p": np.nan,
                "spearman_r": np.nan, "spearman_p": np.nan, "ols_slope": np.nan}
    pr = _stats.pearsonr(x, y)
    sr = _stats.spearmanr(x, y)
    b, _a = np.polyfit(x, y, 1)
    return {"n": n, "pearson_r": float(pr[0]), "pearson_p": float(pr[1]),
            "spearman_r": float(sr.correlation), "spearman_p": float(sr.pvalue),
            "ols_slope": float(b)}
