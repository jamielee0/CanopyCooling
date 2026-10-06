#!/usr/bin/env python3
"""Section 14 / threshold — exploratory analysis + first cooling-advantage threshold estimate.

Inputs : data/processed/master_table.parquet (read by the notebook; this module is pure math).
Outputs: returns dicts/verdict objects consumed by notebooks/14_exploratory_threshold.ipynb,
         which writes figures, docs/section14_results_note.md, and
         data/processed/section14_csi_weight_sensitivity.csv.
Key decisions (full rationale in docs/DESIGN_DECISIONS.md, Section 14):
  - Honesty gate: a threshold is "robust" only if methods agree AND a bend is visible AND
    ET corroborates AND the breakpoint is well identified; else "no robust threshold detected".
  - Segmented (pwlf) always returns a breakpoint, so it is never sufficient evidence on its own;
    cross-checked against an independent change-point (ruptures) and a plain linear fit (dAIC/dR2).
  - Thin paired sample (9 BGs, one dominant); the primary sample is daytime with
    n_tree_valid >= 3, while full/strict/night/pooled samples are labelled sensitivities.
  - CSI supply is root-zone soil moisture; NDMI is retained only as a vegetation-condition
    check. ET NaN on off-ET overpasses is dropped pairwise, never imputed.
  - Unequal CSI weights (0/1, 0.3/0.7, 0.5/0.5, 0.7/0.3, 1/0) are run on the
    identical daytime-primary rows and BG clusters; the equal row must reproduce baseline.
Run: imported by the notebook; numerics unit-tested in test_section14_threshold.py (no I/O).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

log = logging.getLogger("section14")

# The two analysis columns at the heart of Section 14 (names from the Section 13 table).
OUTCOME_COL = "cooling_advantage"        # K = degC; reference LST - tree LST (step 67)
CSI_COL = "mean_csi_tree"                # the Compound Stress Index over the tree pixels
ET_COL = "mean_et_tree"                  # ET over the tree pixels (W m-2); NaN off-ET overpasses
ESI_COL = "mean_esi_tree"                # ESI over the tree pixels (-)
COUNT_COL = "n_tree_valid"               # the filterable sample size (finite-LST tree px)
DEMAND_COMPONENT_COL = "mean_demand_stress_tree"
SUPPLY_COMPONENT_COL = "mean_supply_stress_tree"

# Minor m3: the same five convex pairs executed in Section 12 are carried through the
# daytime-primary threshold analysis. Equal remains the baseline; endpoints bound the result.
CSI_WEIGHT_SCENARIOS: tuple[tuple[str, float, float], ...] = (
    ("pure_supply", 0.0, 1.0),
    ("supply_heavy", 0.3, 0.7),
    ("equal_baseline", 0.5, 0.5),
    ("demand_heavy", 0.7, 0.3),
    ("pure_demand", 1.0, 0.0),
)

# Defaults (documented; the notebook can override).
DEFAULT_MIN_COUNT = 3                    # minimum n_tree_valid for the "modest filter"
ROBUST_MIN_COUNT = 10                    # the strict filter -> collapses to the one well-sampled BG
DEFAULT_N_BINS = 8                       # CSI bins for the binned-mean plot
DEFAULT_N_BOOTSTRAP = 1000               # bootstrap resamples for the breakpoint CI
DEFAULT_SEED = 20240615                  # deterministic bootstrap / any RNG use
MIN_CLUSTERS_FOR_CONFIRMATORY_INFERENCE = 10
WEIGHT_SENSITIVITY_N_BOOTSTRAP = DEFAULT_N_BOOTSTRAP


# --- Pure logic: filtering + binning ---------------------------------------- #
def apply_min_count(values_count: np.ndarray, min_count: int) -> np.ndarray:
    """Boolean keep-mask for rows whose sample-size column is >= ``min_count``.

    ``min_count <= 1`` keeps everything; NaN counts are dropped (treated as 0). This is the
    sensitivity lever: a strict bar collapses the sample onto the one well-sampled BG.
    """
    c = np.asarray(values_count, dtype="float64")
    keep = np.isfinite(c) & (c >= float(min_count))
    return keep


def primary_sample_mask(is_day: np.ndarray, values_count: np.ndarray,
                        min_count: int = DEFAULT_MIN_COUNT) -> np.ndarray:
    """Pre-committed primary sample: daytime rows with enough finite tree pixels.

    This combines B4 (day-only) with the B3 safeguard against one-pixel extremes. The
    full day, night, and pooled samples remain sensitivity analyses; none is allowed to
    replace this mask implicitly.
    """
    keep = apply_min_count(values_count, min_count)
    day, _night = split_day_night(is_day, keep_mask=keep)
    return day


# --- Pure logic: day/night pooling (BLOCKER B4) ----------------------------- #
def split_day_night(is_day: np.ndarray, keep_mask: np.ndarray | None = None
                    ) -> tuple[np.ndarray, np.ndarray]:
    """Partition rows into day vs night boolean masks from the persisted ``is_day`` column.

    ``is_day`` is the Section-13 column (``local_hour = (utc_hour - 7) % 24``, MST=UTC-7 no DST;
    ``is_day = 7 <= local_hour < 19``) — the single source of truth for time-of-day. Returns
    ``(day_mask, night_mask)`` as boolean arrays over the SAME rows: ``day_mask`` selects daytime
    overpasses, ``night_mask`` the rest. When ``keep_mask`` is given (e.g. an ``apply_min_count``
    result), both returned masks are intersected with it, so the two partitions plus the dropped
    rows tile the input exactly. Pure numpy — no pwlf/ruptures/statsmodels.
    """
    d = np.asarray(is_day).astype(bool)
    if keep_mask is None:
        keep = np.ones(d.shape, dtype=bool)
    else:
        keep = np.asarray(keep_mask).astype(bool)
    day_mask = d & keep
    night_mask = (~d) & keep
    return day_mask, night_mask


def daynight_contrast(x: np.ndarray, y: np.ndarray, is_day: np.ndarray) -> dict:
    """Pure-OLS day/night interaction fit ``y ~ 1 + is_day + x + is_day*x`` via ``lstsq``.

    Tests whether pooling day and night overpasses dilutes the day signal. The design matrix
    columns are ``[1, is_day, x, is_day*x]``, so the fitted coefficients are the NIGHT baseline
    plus day offsets:
      - ``night_intercept = beta[0]``,   ``day_intercept = beta[0] + beta[1]``
      - ``delta_intercept = beta[1]`` = day intercept - night intercept (the headline: expected
        strongly positive, day +4.8 K vs night +0.4 K)
      - ``night_slope = beta[2]``,       ``day_slope = beta[2] + beta[3]``,
        ``delta_slope = beta[3]``
    Non-finite (x, y, is_day) rows are dropped pairwise. Returns NaNs if fewer than 4 finite rows
    or if either the day or night side is empty (the interaction is then unidentified). Pure numpy
    — never imports pwlf/ruptures/statsmodels.
    """
    x = np.asarray(x, dtype="float64")
    y = np.asarray(y, dtype="float64")
    d = np.asarray(is_day).astype(bool).astype("float64")
    fin = np.isfinite(x) & np.isfinite(y) & np.isfinite(d)
    x = x[fin]
    y = y[fin]
    d = d[fin]
    n = int(x.size)
    n_day = int(d.sum())
    n_night = int((d == 0.0).sum())
    out = {"night_intercept": np.nan, "day_intercept": np.nan, "delta_intercept": np.nan,
           "night_slope": np.nan, "day_slope": np.nan, "delta_slope": np.nan,
           "n": n, "n_day": n_day, "n_night": n_night}
    if n < 4 or n_day == 0 or n_night == 0:
        return out
    design = np.column_stack([np.ones(n), d, x, d * x])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    b0, b1, b2, b3 = (float(beta[0]), float(beta[1]), float(beta[2]), float(beta[3]))
    out.update({
        "night_intercept": b0,
        "day_intercept": b0 + b1,
        "delta_intercept": b1,
        "night_slope": b2,
        "day_slope": b2 + b3,
        "delta_slope": b3,
    })
    return out


def bin_means(x: np.ndarray, y: np.ndarray, n_bins: int = DEFAULT_N_BINS,
              edges: np.ndarray | None = None
              ) -> dict[str, np.ndarray]:
    """Bin ``x`` into equal-width intervals; return per-bin count/mean/std/sem of ``y``.

    Non-finite (x, y) pairs are dropped pairwise first; empty bins come back as NaN mean / 0
    count. A threshold shows here as a bend in the binned-mean curve.
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


# --- Pure logic: linear & segmented (piecewise) regression ------------------ #
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
    """Gaussian-likelihood AIC = n*ln(RSS/n) + 2*k (k counts variance); relative-only, const dropped."""
    n = int(n)
    rss = max(float(rss), 1e-300)        # guard ln(0)
    return n * np.log(rss / n) + 2 * k_params


def linear_fit(x: np.ndarray, y: np.ndarray) -> dict:
    """OLS straight-line fit y = a + b*x — the null model the segmented fit must beat.

    Returns ``{slope, intercept, r2, rss, aic, n}``; NaN pairs dropped; AIC uses k=3.
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
    """Continuous 2-segment piecewise-linear fit (one interior breakpoint) via ``pwlf``.

    Returns the breakpoint (first threshold estimate), both segment slopes, R^2, RSS, AIC (k=5,
    comparable to linear_fit). Caveat: pwlf always returns a breakpoint, so it must clear the
    full gate (see :func:`threshold_verdict`); breakpoint is NaN if the fit cannot be formed.
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
    """Fit both models on the same data — "is the kink worth it?".

    Returns both fits plus ``delta_r2`` and ``delta_aic`` (negative favours segmented, only
    meaningfully beyond ~|2|); a tiny delta_r2 / non-negative delta_aic is evidence against a
    threshold.
    """
    lin = linear_fit(x, y)
    seg = segmented_fit(x, y, seed=seed)
    d_r2 = (seg["r2"] - lin["r2"]) if np.isfinite(seg["r2"]) and np.isfinite(lin["r2"]) else np.nan
    d_aic = (seg["aic"] - lin["aic"]) if np.isfinite(seg["aic"]) and np.isfinite(lin["aic"]) else np.nan
    return {"linear": lin, "segmented": seg, "delta_r2": d_r2, "delta_aic": d_aic,
            "segmented_preferred_by_aic": bool(np.isfinite(d_aic) and d_aic < -2.0)}


# --- Pure logic: bootstrap CI for the breakpoint ---------------------------- #
def _cluster_resample_indices(groups: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """One whole-cluster resample (B3.3): draw ``len(unique(groups))`` clusters with
    replacement and return the concatenated row indices of every drawn cluster.

    The returned index set is always a union of WHOLE clusters — a cluster is either fully
    in or fully out — so a resample never splits a block group. Consumes exactly one
    ``rng.choice`` draw, matching the single ``rng.integers`` draw of the i.i.d. path.
    """
    g = np.asarray(groups)
    uniq = np.unique(g)
    members = [np.nonzero(g == gg)[0] for gg in uniq]
    drawn = rng.choice(uniq.size, size=uniq.size, replace=True)
    return np.concatenate([members[k] for k in drawn])


def bootstrap_breakpoint(x: np.ndarray, y: np.ndarray, *,
                         n_boot: int = DEFAULT_N_BOOTSTRAP,
                         seed: int = DEFAULT_SEED,
                         ci: float = 0.95,
                         groups: np.ndarray | None = None) -> dict:
    """Percentile bootstrap CI for the breakpoint by resampling with replacement.

    ``point`` is the breakpoint on the full sample; ``spans_fraction`` (CI width / CSI range) is
    the honesty flag — a large value means the breakpoint is not identified. Failed-fit
    resamples are skipped (counted in ``n_valid``).

    ``groups`` (B3.3): when given (a per-row cluster label, e.g. block-group id aligned to
    ``x``/``y``), the resample draws WHOLE clusters with replacement — ``rng.choice`` over the
    unique groups, then all member rows of each drawn group — instead of i.i.d. rows. This is
    the honest CI at ≤9 block groups (one dominant BG): an i.i.d. row bootstrap treats
    pseudo-replicated pixels/overpasses as independent and reports a spuriously tight interval.
    With ``groups=None`` the i.i.d. row bootstrap is preserved byte-for-byte.
    """
    x = np.asarray(x, dtype="float64")
    y = np.asarray(y, dtype="float64")
    fin = np.isfinite(x) & np.isfinite(y)
    x = x[fin]
    y = y[fin]
    g = np.asarray(groups)[fin] if groups is not None else None
    n = int(x.size)
    x_range = float(np.ptp(x)) if n else np.nan
    point = segmented_fit(x, y, seed=seed)["breakpoint"]
    n_clusters = int(np.unique(g).size) if g is not None else 0
    out = {"point": point, "ci_low": np.nan, "ci_high": np.nan, "median": np.nan,
           "mean": np.nan, "std": np.nan, "estimates": np.array([]), "n_valid": 0,
           "n_boot": int(n_boot), "spans_fraction": np.nan, "x_range": x_range,
           "ci_level": float(ci), "clustered": bool(groups is not None),
           "n_clusters": n_clusters}
    if n < 4 or not np.isfinite(x_range) or x_range <= 0:
        return out
    if g is not None and n_clusters < 2:
        # A block-group cluster bootstrap needs >= 2 clusters: with a single BG every
        # whole-cluster resample is identical, so the between-BG uncertainty is uncomputable.
        # Return NaN (honest "not identifiable by clustering") rather than a spurious
        # zero-width CI that would read as a well-identified breakpoint.
        return out
    rng = np.random.default_rng(seed)
    ests: list[float] = []
    for _ in range(int(n_boot)):
        idx = (rng.integers(0, n, size=n) if g is None
               else _cluster_resample_indices(g, rng))
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


# --- Pure logic: independent, zero-break-capable change-point check -------- #
def changepoint_csi(x: np.ndarray, y: np.ndarray, *,
                    n_bins: int = DEFAULT_N_BINS, pen: float | None = None,
                    min_size: int = 2) -> dict:
    """Penalized change-point in the binned cooling-response slope via ``ruptures.Pelt``.

    A thermal threshold is a *change in slope*, not merely a change in the mean level. We bin
    cooling advantage along CSI, compute adjacent-bin slopes, and apply a PELT mean-shift
    detector to that slope sequence. The default BIC-style penalty is
    ``2*log(n_slopes)*var(slopes)``. PELT may return no interior break; multiple or edge breaks
    are treated as "no single identified change-point" rather than being forced into an answer.
    When exactly one admissible break is found, it is mapped to the shared CSI-bin centre
    between the last pre-break and first post-break slope intervals. This is independent
    machinery from the raw-row segmented fit.
    """
    import ruptures as rpt

    x = np.asarray(x, dtype="float64")
    y = np.asarray(y, dtype="float64")
    fin = np.isfinite(x) & np.isfinite(y)
    x = x[fin]
    y = y[fin]
    n = int(x.size)
    out = {"changepoint_csi": np.nan, "split_index": -1, "n": n,
           "n_breaks": 0, "penalty": np.nan,
           "break_indices": np.array([], dtype=int),
           "bin_centers": np.array([]), "binned_mean": np.array([]),
           "slope_signal": np.array([]),
           "x_sorted": np.array([]), "y_sorted": np.array([])}
    if n < 4 or float(np.ptp(x)) <= 0:
        return out
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    ys = y[order]
    binned = bin_means(xs, ys, n_bins=n_bins)
    good = (binned["count"] > 0) & np.isfinite(binned["mean"])
    centers = binned["centers"][good].astype("float64")
    means = binned["mean"][good].astype("float64")
    out.update({"bin_centers": centers, "binned_mean": means,
                "x_sorted": xs, "y_sorted": ys})
    if centers.size < 5:
        return out
    dx = np.diff(centers)
    if np.any(~np.isfinite(dx)) or np.any(dx <= 0):
        return out
    slopes = np.diff(means) / dx
    out["slope_signal"] = slopes
    if slopes.size < 2 * int(min_size):
        return out
    penalty = (float(pen) if pen is not None else
               float(2.0 * np.log(slopes.size) * max(float(np.var(slopes)), 1e-12)))
    out["penalty"] = penalty
    signal = slopes.reshape(-1, 1).astype("float64")
    algo = rpt.Pelt(model="l2", min_size=int(min_size), jump=1).fit(signal)
    bkps = [int(v) for v in algo.predict(pen=penalty)]
    interior = np.asarray([v for v in bkps if 0 < v < slopes.size], dtype=int)
    out.update({"n_breaks": int(interior.size), "break_indices": interior})
    if interior.size != 1:
        return out
    split = int(interior[0])
    if split < int(min_size) or slopes.size - split < int(min_size):
        return out
    # ``ruptures`` returns the first index of the post-break slope segment. Adjacent slopes
    # live between neighbouring bin centres, so their physical boundary is centers[split].
    cp = float(centers[split])
    out.update({"changepoint_csi": cp, "split_index": split})
    return out


# --- Pure logic: ET corroboration + the agreement gate / verdict ------------ #
def et_declines_beyond(csi: np.ndarray, et: np.ndarray, threshold_csi: float
                       ) -> dict:
    """Mechanistic check: does mean ET below ``threshold_csi`` exceed mean ET at-or-above it?

    Drops NaN ET pairwise (off-ET overpasses). ``et_declines`` is True iff mean ET above the
    threshold is lower than below; False (and means NaN) if the threshold is NaN or a side empty.
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
AGREE_TOLERANCE_FRACTION = 0.10  # change-point within this fraction of the CSI range of the breakpoint = agree
                                 # (acknowledges the pwlf-knee vs ruptures-mean-shift location offset;
                                 #  the well_identified gate still rejects an unidentified-CI "agreement")


def methods_agree(breakpoint_ci_low: float, breakpoint_ci_high: float,
                  changepoint: float, *, breakpoint: float = np.nan,
                  x_range: float = np.nan,
                  tol_fraction: float = AGREE_TOLERANCE_FRACTION) -> bool:
    """Do the segmented breakpoint and independent change-point agree within uncertainty?

    True if EITHER the change-point falls inside the breakpoint's bootstrap CI OR it is within
    ``tol_fraction`` of the CSI range of the breakpoint point estimate (a documented tolerance
    for the pwlf-knee vs ruptures-mean-shift offset). False if any required input is non-finite.
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
    """Structured Section 14 honesty-gate result.

    ``robust`` is True only if methods_agree AND bend_visible AND et_corroborates AND
    well_identified; ``label`` is human-readable; ``reasons`` lists which criteria passed/failed.
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
    cluster_adequate: bool
    n_clusters: int
    spans_fraction: float
    slope_change: float
    delta_r2: float
    delta_aic: float
    reasons: list[str] = field(default_factory=list)


def threshold_verdict(*, segmented: dict, bootstrap: dict, changepoint: dict,
                      et_check: dict, comparison: dict,
                      bend_slope_drop: float = BEND_SLOPE_DROP,
                      wide_ci_fraction: float = WIDE_CI_FRACTION) -> ThresholdVerdict:
    """Combine all evidence into the credible/not verdict — THE gate.

    Robust only if all hold: methods agree; breakpoint well identified (CI width <
    ``wide_ci_fraction`` of CSI range); bend visible (slope_change <= -``bend_slope_drop``); ET
    corroborates; and a clustered analysis contains at least
    ``MIN_CLUSTERS_FOR_CONFIRMATORY_INFERENCE`` independent block groups. Else "no robust
    threshold detected". The linear-vs-segmented comparison is carried for the note but is not a
    hard gate.
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
    clustered = bool(bootstrap.get("clustered", False))
    n_clusters = int(bootstrap.get("n_clusters", 0))
    # Confirmatory inference requires uncertainty that was actually clustered by
    # whole block group.  An i.i.d. row bootstrap cannot satisfy this gate even
    # when every other diagnostic happens to look favourable.
    cluster_adequate = bool(
        clustered and n_clusters >= MIN_CLUSTERS_FOR_CONFIRMATORY_INFERENCE)

    reasons: list[str] = []
    cp_label = optional_threshold_label(cp)
    reasons.append(
        f"methods agree (change-point in bootstrap CI or within 10% range tolerance): "
        f"{agree} [bp={bp:.3f}, penalized PELT={cp_label}, "
        f"n_breaks={int(changepoint.get('n_breaks', 0))}, CI=({lo:.3f}, {hi:.3f})]")
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
    reasons.append(
        f"independent block groups adequate for confirmatory inference "
        f"(>={MIN_CLUSTERS_FOR_CONFIRMATORY_INFERENCE}): {cluster_adequate} "
        f"[n_clusters={n_clusters if clustered else 'not clustered'}]")

    robust = bool(agree and well_identified and bend_visible and et_corroborates
                  and cluster_adequate)
    label = "robust threshold" if robust else "no robust threshold detected"
    return ThresholdVerdict(
        robust=robust, label=label, breakpoint=bp, ci_low=lo, ci_high=hi, changepoint=cp,
        methods_agree=agree, bend_visible=bend_visible, et_corroborates=et_corroborates,
        well_identified=well_identified, cluster_adequate=cluster_adequate,
        n_clusters=n_clusters, spans_fraction=spans, slope_change=slope_change,
        delta_r2=d_r2, delta_aic=d_aic, reasons=reasons)


# --- Convenience: run the whole pipeline on one (x, y[, et]) sample --------- #
def analyze_sample(x: np.ndarray, y: np.ndarray, et: np.ndarray | None = None, *,
                   n_bins: int = DEFAULT_N_BINS, n_boot: int = DEFAULT_N_BOOTSTRAP,
                   seed: int = DEFAULT_SEED, label: str = "",
                   groups: np.ndarray | None = None) -> dict:
    """Run the full threshold pipeline on one CSI/cooling-advantage sample.

    Bundles binned means, linear-vs-segmented comparison, bootstrap CI, change-point, ET-decline
    check (at the breakpoint), and the combined verdict. Called once per sample; reads/writes nothing.

    ``groups`` (B3.3): a per-row cluster label (block-group id) aligned to ``x``/``y``; forwarded
    to ``bootstrap_breakpoint`` so the breakpoint CI resamples whole block groups, not i.i.d. rows.
    """
    x = np.asarray(x, dtype="float64")
    y = np.asarray(y, dtype="float64")
    comparison = compare_linear_segmented(x, y, seed=seed)
    seg = comparison["segmented"]
    boot = bootstrap_breakpoint(x, y, n_boot=n_boot, seed=seed, groups=groups)
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


def optional_threshold_label(value: object, digits: int = 3) -> str:
    """Format an optional threshold, using ``none`` for a genuine zero/no-single-break result."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "none"
    return f"{number:.{digits}f}" if np.isfinite(number) else "none"


def csi_weight_sensitivity_table(
    frame: "pd.DataFrame",
    *,
    scenarios: Sequence[tuple[str, float, float]] = CSI_WEIGHT_SCENARIOS,
    n_boot: int = WEIGHT_SENSITIVITY_N_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
) -> "pd.DataFrame":
    """Run all CSI weight scenarios on one identical daytime-primary row set (minor m3).

    Section 13 persists demand/supply component means on a shared finite tree-pixel mask.
    This routine selects the pre-committed daytime, ``sample_label == 'primary'`` rows, drops
    missing outcome/components once, and then applies every convex weight pair to those exact
    rows. Each scenario receives the same BG-cluster bootstrap and honesty gate. The equal
    scenario must reproduce ``mean_csi_tree`` within floating-point tolerance.
    """
    required = {
        OUTCOME_COL, CSI_COL, ET_COL, COUNT_COL, "is_day", "sample_label",
        "neighborhood_id", DEMAND_COMPONENT_COL, SUPPLY_COMPONENT_COL,
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"weight sensitivity is missing columns: {missing}")
    if not scenarios:
        raise ValueError("at least one CSI weight scenario is required")

    checked: list[tuple[str, float, float]] = []
    seen: set[tuple[float, float]] = set()
    for name, wd0, ws0 in scenarios:
        wd = float(wd0); ws = float(ws0)
        if not (np.isfinite(wd) and np.isfinite(ws) and wd >= 0 and ws >= 0
                and np.isclose(wd + ws, 1.0, atol=1e-12, rtol=0.0)):
            raise ValueError(f"invalid convex CSI weights for {name!r}: {wd0}, {ws0}")
        if (wd, ws) in seen:
            raise ValueError(f"duplicate CSI weight pair: {(wd, ws)}")
        seen.add((wd, ws))
        checked.append((str(name), wd, ws))
    if (0.5, 0.5) not in seen:
        raise ValueError("CSI weight scenarios must include the equal 0.5/0.5 baseline")

    base_mask = (frame["is_day"].astype(bool)
                 & frame["sample_label"].eq("primary")
                 & frame[[OUTCOME_COL, DEMAND_COMPONENT_COL,
                           SUPPLY_COMPONENT_COL]].notna().all(axis=1))
    sample = frame.loc[base_mask].copy()
    if sample.empty:
        raise ValueError("no finite daytime-primary rows for CSI weight sensitivity")
    demand = sample[DEMAND_COMPONENT_COL].to_numpy(dtype="float64")
    supply = sample[SUPPLY_COMPONENT_COL].to_numpy(dtype="float64")
    recomputed_equal = 0.5 * demand + 0.5 * supply
    saved_equal = sample[CSI_COL].to_numpy(dtype="float64")
    baseline_diff = float(np.nanmax(np.abs(recomputed_equal - saved_equal)))
    if not np.allclose(recomputed_equal, saved_equal, atol=2e-6, rtol=1e-6, equal_nan=True):
        raise AssertionError(
            "equal-weight CSI does not reproduce the saved common-mask component identity "
            f"(max absolute difference={baseline_diff:.8g})")
    # Use the saved equal-weight values for that scenario so every downstream diagnostic,
    # including the deterministic bootstrap, reproduces the notebook's baseline exactly.
    equal = saved_equal.copy()

    rows: list[dict] = []
    for name, wd, ws in checked:
        x = equal.copy() if (wd, ws) == (0.5, 0.5) else wd * demand + ws * supply
        res = analyze_sample(
            x,
            sample[OUTCOME_COL].to_numpy(dtype="float64"),
            et=sample[ET_COL].to_numpy(dtype="float64"),
            n_bins=DEFAULT_N_BINS,
            n_boot=int(n_boot),
            seed=int(seed),
            label=name,
            groups=sample["neighborhood_id"].to_numpy(),
        )
        seg = res["segmented"]
        boot = res["bootstrap"]
        cp = res["changepoint"]
        verdict = res["verdict"]
        rank_corr = pd.Series(x).corr(pd.Series(equal), method="spearman")
        rows.append({
            "scenario": name,
            "w_demand": wd,
            "w_supply": ws,
            "n_rows": int(len(sample)),
            "n_bgs": int(sample["neighborhood_id"].nunique()),
            "mean_csi": float(np.mean(x)),
            "rank_spearman_vs_equal": float(rank_corr),
            "baseline_max_abs_diff": baseline_diff if (wd, ws) == (0.5, 0.5) else np.nan,
            "candidate_breakpoint": float(seg.get("breakpoint", np.nan)),
            "pelt_changepoint": float(cp.get("changepoint_csi", np.nan)),
            "pelt_n_breaks": int(cp.get("n_breaks", 0)),
            "pelt_penalty": float(cp.get("penalty", np.nan)),
            "cluster_ci_low": float(boot.get("ci_low", np.nan)),
            "cluster_ci_high": float(boot.get("ci_high", np.nan)),
            "cluster_ci_spans_fraction": float(boot.get("spans_fraction", np.nan)),
            "delta_aic": float(res["comparison"].get("delta_aic", np.nan)),
            "methods_agree": bool(verdict.methods_agree),
            "bend_visible": bool(verdict.bend_visible),
            "et_corroborates": bool(verdict.et_corroborates),
            "cluster_adequate": bool(verdict.cluster_adequate),
            "verdict": verdict.label,
        })
    return pd.DataFrame(rows)


def describe_shape(x: np.ndarray, y: np.ndarray) -> dict:
    """Headline scatter descriptors: Pearson/Spearman correlations and OLS slope.

    A near-zero correlation/slope says the cloud is essentially flat (no monotonic decline),
    itself a key piece of the verdict.
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


def write_results_note(path: str | Path, results: dict[str, dict], daynight: dict, *,
                       primary_key: str = "A_day_primary",
                       primary_min_count: int = DEFAULT_MIN_COUNT,
                       weight_sensitivity: "pd.DataFrame | None" = None) -> Path:
    """Write the executed Section-14 result note from the current in-memory results.

    Keeping this report generation beside the analysis avoids hand-maintained numbers and stale
    construct labels. The output deliberately distinguishes the primary sample from every
    sensitivity and never promotes a candidate breakpoint when the honesty gate fails.
    """
    if primary_key not in results:
        raise KeyError(f"primary sample {primary_key!r} is absent from results")

    def fmt(value: object, digits: int = 3) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "NA"
        return f"{number:.{digits}f}" if np.isfinite(number) else "NA"

    primary = results[primary_key]
    lines = [
        "# Section 14 — Phoenix exploratory threshold results",
        "",
        "## Blocker-aligned analysis contract",
        "",
        "- **B1 — construct alignment:** the primary water-supply variable is root-zone soil "
        "moisture (`sm_z`). CSI is a secondary composite of standardized VPD demand and soil-"
        "moisture supply; NDMI remains a vegetation-condition check. The primary threshold "
        "detector is the Section 15 two-dimensional `VPD_z × sm_z` response surface.",
        f"- **B2/B3 — sample safeguards:** the primary Section 14 sample requires daytime "
        f"observations and `n_tree_valid >= {primary_min_count}`. Count-floor exclusions are "
        "persisted in `sample_label`; full and stricter samples are sensitivities. Breakpoint "
        "uncertainty resamples whole block groups.",
        "- **B4 — temporal scope:** daytime is primary. Night-only and pooled estimates are "
        "reported only as labelled contrasts.",
        "",
        "## Result",
        "",
        f"**{primary['verdict'].label.capitalize()}.** The primary sample contains "
        f"{primary.get('n', 0)} rows from {primary.get('n_bgs', 0)} block groups. This Phoenix "
        "pilot is exploratory: fewer than 10 independent block groups cannot support "
        "confirmatory threshold inference.",
        "",
        "| sample | role | rows | BGs | candidate breakpoint | penalized PELT | 95% BG-bootstrap CI | CI/range | ΔAIC | verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name, res in results.items():
        boot = res["bootstrap"]
        verdict = res["verdict"]
        role = ("primary" if name == primary_key else
                "night contrast" if name.startswith("N_") else
                "pooled sensitivity" if name.startswith("P_") else
                "count-floor sensitivity")
        ci = f"{fmt(boot.get('ci_low'))} to {fmt(boot.get('ci_high'))}"
        cp = res["changepoint"]
        cp_value = optional_threshold_label(cp.get("changepoint_csi"))
        cp_text = (cp_value if cp_value != "none" else
                   f"none ({int(cp.get('n_breaks', 0))} breaks)")
        lines.append(
            f"| `{name}` | {role} | {res.get('n', 0)} | {res.get('n_bgs', 0)} | "
            f"{fmt(res['segmented'].get('breakpoint'))} | {cp_text} | {ci} | "
            f"{fmt(boot.get('spans_fraction'), 2)} | "
            f"{fmt(res['comparison'].get('delta_aic'), 2)} | {verdict.label} |")

    lines.extend([
        "",
        "## Day/night contrast",
        "",
        f"The fitted day intercept is {fmt(daynight.get('day_intercept'), 2)} K versus "
        f"{fmt(daynight.get('night_intercept'), 2)} K at night (day − night: "
        f"{fmt(daynight.get('delta_intercept'), 2)} K). Pooling therefore dilutes the daytime "
        "cooling signal and is not used for the headline result.",
    ])

    if weight_sensitivity is not None:
        required = {"scenario", "w_demand", "w_supply", "n_rows", "n_bgs",
                    "rank_spearman_vs_equal", "candidate_breakpoint", "pelt_changepoint",
                    "pelt_n_breaks", "cluster_ci_low", "cluster_ci_high", "delta_aic",
                    "verdict"}
        missing = sorted(required - set(weight_sensitivity.columns))
        if missing:
            raise KeyError(f"weight-sensitivity table is missing columns: {missing}")
        lines.extend([
            "",
            "## CSI weight sensitivity (minor m3)",
            "",
            "All five convex demand/supply weights use the identical daytime-primary rows, "
            "component finite mask, block-group clusters, and honesty gate. The 0.5/0.5 row "
            "exactly reproduces the saved baseline CSI.",
            "",
            "| scenario | demand / supply | rows | BGs | rank ρ vs equal | candidate breakpoint | penalized PELT | BG-bootstrap CI | ΔAIC | verdict |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ])
        for _, row in weight_sensitivity.iterrows():
            cp_value = optional_threshold_label(row["pelt_changepoint"])
            cp_text = (cp_value if cp_value != "none" else
                       f"none ({int(row['pelt_n_breaks'])} breaks)")
            ci = f"{fmt(row['cluster_ci_low'])} to {fmt(row['cluster_ci_high'])}"
            lines.append(
                f"| `{row['scenario']}` | {row['w_demand']:.1f} / {row['w_supply']:.1f} | "
                f"{int(row['n_rows'])} | {int(row['n_bgs'])} | "
                f"{fmt(row['rank_spearman_vs_equal'], 3)} | "
                f"{fmt(row['candidate_breakpoint'])} | {cp_text} | {ci} | "
                f"{fmt(row['delta_aic'], 2)} | {row['verdict']} |")
        verdicts = sorted(set(weight_sensitivity["verdict"].astype(str)))
        lines.extend([
            "",
            "Weighting conclusion: " + (
                "every scenario returns **no robust threshold detected**; the headline "
                "conclusion is insensitive to the demand/supply weights."
                if verdicts == ["no robust threshold detected"] else
                "scenario verdicts differ and must be interpreted individually: "
                + ", ".join(verdicts)),
        ])

    lines.extend([
        "",
        "## Interpretation",
        "",
        "The segmented fit may produce a candidate breakpoint, but it is never sufficient on "
        "its own. The independent penalized PELT method is allowed to return zero breaks; "
        "zero or multiple breaks are reported as **none**, not converted into a fabricated "
        "number. Method agreement uses the tightened 10% CSI-range tolerance and the "
        "whole-block-group bootstrap. In this pilot, the cluster-count safeguard alone "
        "prevents a confirmatory claim; breakpoint stability, response shape, and ET provide "
        "additional diagnostics. The defensible conclusion is: **no robust threshold detected "
        "in the Phoenix pilot**. This means the available data do not identify one; it does "
        "not prove that no physiological threshold exists.",
        "",
        "Generated by `src/section14_threshold.py`; rerunning the notebook refreshes all values "
        "and `data/processed/section14_csi_weight_sensitivity.csv`.",
        "",
    ])
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return output
