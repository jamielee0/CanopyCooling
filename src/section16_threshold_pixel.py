#!/usr/bin/env python3
"""Section 16 (REASON #2 FIX) - CLUSTERING-AWARE threshold analysis on the enlarged,
pixel-level, spatially-clustered Phoenix paired sample.

This is the inference half of the reason-#2 fix. It reads ONLY the NEW parquets built by
src/section16_pixel_pairing.py (master_table_cluster.parquet = the PRIMARY modeling input;
master_table_pixel.parquet for the within-pixel temporal model) and REUSES the existing
Section 14 honesty gate verbatim (src/section14_threshold.py: segmented + ruptures +
methods_agree + ET-corroboration + threshold_verdict). It ADDS the clustering-aware layer
the thin BG sample could not support:

  PRIMARY  -- cluster-level segmented fit on the CLUSTER-overpass cooling advantage vs
              mean_csi_tree, with:
                (a) a MixedLM random intercept per spatial cluster (nested in BG),
                (b) CLUSTER-ROBUST (cluster on spatial cluster) SE on the slope,
                (c) a CLUSTER-RESAMPLING spatial block bootstrap for the breakpoint CI
                    (resamples the ~56 clusters, NEVER the pixels nor the pixel-overpass
                    rows) -- this prices the spatial autocorrelation back out and returns
                    the effective N to the honest cluster count.
  SECONDARY -- within-cluster FIXED-EFFECT (demeaning) temporal model + temporal-block
              bootstrap (block on overpass) + cluster-robust SE, harvesting the overpass
              dates as new df with the design-effect deflation reported.
  FALSIFICATION -- leave-the-dominant-BG-out refit (drop 040139412001) + cluster-EQUAL
              weighting + the Kish-N_eff / inverse-Simpson report side by side.
  ROBUSTNESS -- the R-sweep {210, 350, 500}, queen vs rook, and a 2 km grid-tile pass
              (reuse src/explore_pairing_units.py's grid logic on the cluster centroids).

THE GATE IS UNCHANGED FROM SECTION 14 (the whole point): a threshold is reported ONLY if
methods AGREE on a well-identified break AND a bend is visible in the binned plot AND ET
declines beyond the same CSI level -- AND it must SURVIVE leave-dominant-out. Otherwise the
honest verdict is "no robust threshold" (a valid finding, the gate to the cross-city phase).

PSEUDO-REPLICATION GUARD (carried on every estimate): the nominal pixel-overpass count is
reported but is NEVER the inference df. The regression rows are CLUSTER-overpass; the
resampling unit is the spatial CLUSTER; the honest effective independent N is the
Kish/inverse-Simpson figure, bounded by the ~17 paired BGs and ~1.9 by BG-Kish.

Writes notebooks/16_pixel_threshold figures are produced by the notebook; this module
writes data/processed/section16_threshold_results.json (the machine-readable results) and
PRINTS the full sensitivity table to stdout.

Run (canopy env):
  conda run -n canopy python src/section16_threshold_pixel.py
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

_SRC = Path(__file__).resolve().parent
_ROOT = _SRC.parent
for _p in (str(_ROOT), str(_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import config  # noqa: E402
import section14_threshold as s14  # noqa: E402  (REUSE the honesty gate)

log = logging.getLogger("section16_threshold")

MASTER_CLUSTER_PARQUET = "master_table_cluster.parquet"
MASTER_PIXEL_PARQUET = "master_table_pixel.parquet"
RESULTS_JSON = "section16_threshold_results.json"
DOMINANT_BG_GEOID = "040139412001"

CSI_COL = "mean_csi_tree"
CA_COL = "cooling_advantage"
ET_COL = "mean_et_tree"


# =========================================================================== #
# Effective-N helpers
# =========================================================================== #
def inverse_simpson(sizes: np.ndarray) -> float:
    """Inverse-Simpson effective number of units from a size distribution (1/sum p_i^2)."""
    n = np.asarray(sizes, dtype="float64")
    s = n.sum()
    if s <= 0:
        return 0.0
    p = n / s
    return float(1.0 / np.sum(p * p))


def effective_n_report(df: pd.DataFrame) -> dict:
    """Nominal-N / cluster-N / BG-N / Kish-N_eff / inverse-Simpson, side by side.

    Reported on EVERY estimate so the pixel/pixel-overpass count is never mistaken for the
    inference df. ``df`` is a cluster-overpass frame for one radius/unit subset.
    """
    n_rows = int(len(df))
    n_clusters = int(df["cluster_id"].nunique())
    n_bg = int(df["GEOID"].nunique())
    csizes = df.groupby("cluster_id").size().to_numpy()
    bgsizes = df.groupby("GEOID").size().to_numpy()
    return {
        "cluster_overpass_rows": n_rows,
        "n_clusters": n_clusters,
        "n_bg": n_bg,
        "kish_neff_clusters": round(s16_kish(csizes), 2),
        "kish_neff_bg": round(s16_kish(bgsizes), 2),
        "invsimpson_clusters": round(inverse_simpson(csizes), 2),
        "invsimpson_bg": round(inverse_simpson(bgsizes), 2),
    }


def s16_kish(sizes: np.ndarray) -> float:
    n = np.asarray(sizes, dtype="float64")
    s = n.sum()
    return float(s * s / np.sum(n * n)) if s > 0 else 0.0


# =========================================================================== #
# Cluster-resampling spatial block bootstrap (resamples CLUSTERS, never rows)
# =========================================================================== #
def cluster_bootstrap_breakpoint(df: pd.DataFrame, *, n_boot: int, seed: int,
                                 ci: float = 0.95) -> dict:
    """Breakpoint bootstrap CI by resampling SPATIAL CLUSTERS with replacement (LEVER 4).

    The honest spatial block bootstrap: draw ``k`` clusters (k = the number of distinct
    clusters) WITH REPLACEMENT, pool ALL the cluster-overpass rows of the drawn clusters,
    refit the 2-segment model, collect the breakpoint. This NEVER resamples individual
    pixels or pixel-overpass rows, so it prices the within-cluster spatial autocorrelation
    back out -- the bootstrap has at most ``n_clusters`` distinct units to draw from, which
    is the honest effective N. Returns the same shape as s14.bootstrap_breakpoint plus the
    cluster count, so it slots straight into the Section 14 verdict gate.
    """
    x_full = df[CSI_COL].to_numpy(dtype="float64")
    y_full = df[CA_COL].to_numpy(dtype="float64")
    fin = np.isfinite(x_full) & np.isfinite(y_full)
    x_range = float(np.ptp(x_full[fin])) if fin.any() else np.nan
    point = s14.segmented_fit(x_full[fin], y_full[fin])["breakpoint"]
    clusters = df["cluster_id"].to_numpy()
    uniq = np.unique(clusters[fin])
    k = uniq.size
    out = {"point": point, "ci_low": np.nan, "ci_high": np.nan, "median": np.nan,
           "mean": np.nan, "std": np.nan, "estimates": np.array([]), "n_valid": 0,
           "n_boot": int(n_boot), "spans_fraction": np.nan, "x_range": x_range,
           "ci_level": float(ci), "n_clusters_resampled": int(k)}
    if k < 4 or not np.isfinite(x_range) or x_range <= 0:
        return out
    # precompute per-cluster row indices for fast pooling
    rows_by_cluster = {int(c): np.where((clusters == c) & fin)[0] for c in uniq}
    rng = np.random.default_rng(seed)
    ests: list[float] = []
    for _ in range(int(n_boot)):
        draw = rng.choice(uniq, size=k, replace=True)
        idx = np.concatenate([rows_by_cluster[int(c)] for c in draw])
        xb = x_full[idx]; yb = y_full[idx]
        if float(np.ptp(xb)) <= 0:
            continue
        bp = s14.segmented_fit(xb, yb)["breakpoint"]
        if np.isfinite(bp):
            ests.append(float(bp))
    ests_arr = np.asarray(ests, dtype="float64")
    if ests_arr.size == 0:
        return out
    alpha = (1.0 - ci) / 2.0
    lo = float(np.quantile(ests_arr, alpha)); hi = float(np.quantile(ests_arr, 1.0 - alpha))
    out.update({"ci_low": lo, "ci_high": hi, "median": float(np.median(ests_arr)),
                "mean": float(np.mean(ests_arr)),
                "std": float(np.std(ests_arr, ddof=1)) if ests_arr.size > 1 else np.nan,
                "estimates": ests_arr, "n_valid": int(ests_arr.size),
                "spans_fraction": (hi - lo) / x_range if x_range > 0 else np.nan})
    return out


def temporal_block_bootstrap_breakpoint(df: pd.DataFrame, *, n_boot: int, seed: int,
                                        ci: float = 0.95) -> dict:
    """Breakpoint CI resampling OVERPASS dates (the temporal block, for the secondary model).

    Resamples the distinct overpass_index values with replacement and pools all rows of the
    drawn overpasses -> prices the within-overpass (cross-cluster, same-day) correlation. A
    companion to the cluster bootstrap for the repeated-measures temporal axis.
    """
    x_full = df[CSI_COL].to_numpy(dtype="float64")
    y_full = df[CA_COL].to_numpy(dtype="float64")
    fin = np.isfinite(x_full) & np.isfinite(y_full)
    x_range = float(np.ptp(x_full[fin])) if fin.any() else np.nan
    ops = df["overpass_index"].to_numpy()
    uniq = np.unique(ops[fin]); k = uniq.size
    out = {"ci_low": np.nan, "ci_high": np.nan, "spans_fraction": np.nan,
           "x_range": x_range, "n_valid": 0, "n_overpasses_resampled": int(k)}
    if k < 4 or not np.isfinite(x_range) or x_range <= 0:
        return out
    rows_by_op = {int(o): np.where((ops == o) & fin)[0] for o in uniq}
    rng = np.random.default_rng(seed)
    ests: list[float] = []
    for _ in range(int(n_boot)):
        draw = rng.choice(uniq, size=k, replace=True)
        idx = np.concatenate([rows_by_op[int(o)] for o in draw])
        xb = x_full[idx]; yb = y_full[idx]
        if float(np.ptp(xb)) <= 0:
            continue
        bp = s14.segmented_fit(xb, yb)["breakpoint"]
        if np.isfinite(bp):
            ests.append(float(bp))
    ests_arr = np.asarray(ests, dtype="float64")
    if ests_arr.size == 0:
        return out
    alpha = (1.0 - ci) / 2.0
    lo = float(np.quantile(ests_arr, alpha)); hi = float(np.quantile(ests_arr, 1.0 - alpha))
    out.update({"ci_low": lo, "ci_high": hi,
                "spans_fraction": (hi - lo) / x_range if x_range > 0 else np.nan,
                "n_valid": int(ests_arr.size)})
    return out


# =========================================================================== #
# MixedLM random-intercept (cluster nested in BG) + cluster-robust OLS
# =========================================================================== #
def mixedlm_random_intercept(df: pd.DataFrame) -> dict:
    """Linear MixedLM: cooling_advantage ~ CSI, random intercept per spatial CLUSTER.

    Tests whether the LINEAR cooling-vs-CSI slope is non-zero once between-cluster level
    differences are absorbed by a random intercept -- the honest spatial model that returns
    the effective N to the cluster count. The PRIMARY grouping is the spatial cluster (the
    finest independent unit). Because a connected component lies in essentially one BG (only
    ~3 straddlers), a cluster random intercept already captures the BG level; we additionally
    try the BG-nested variance-component form and FALL BACK to the cluster-only random
    intercept if the nested design is singular (it is, when one BG holds ~44 clusters). The
    fallback is documented, not hidden. Returns slope, SE/p, variance components, and which
    specification converged. NaN-safe.
    """
    sub = df[[CA_COL, CSI_COL, "cluster_id", "GEOID"]].dropna()
    out = {"slope": np.nan, "se": np.nan, "pvalue": np.nan, "n": int(len(sub)),
           "n_clusters": int(sub["cluster_id"].nunique()),
           "n_bg": int(sub["GEOID"].nunique()), "converged": False,
           "cluster_var": np.nan, "resid_var": np.nan, "spec": "none"}
    if len(sub) < 10 or sub["cluster_id"].nunique() < 2:
        return out
    import statsmodels.formula.api as smf
    d = sub.rename(columns={CA_COL: "y", CSI_COL: "x"}).copy()

    # (1) try BG-nested variance-component (cluster within BG); (2) fall back to a plain
    #     cluster random intercept if the nested design is singular.
    specs = [
        ("bg_nested_cluster", dict(groups="GEOID",
                                   vc_formula={"cl": "0 + C(cluster_id)"})),
        ("cluster_random_intercept", dict(groups="cluster_id", vc_formula=None)),
    ]
    for spec_name, kw in specs:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                if kw["vc_formula"] is not None:
                    md = smf.mixedlm("y ~ x", d, groups=d[kw["groups"]],
                                     vc_formula=kw["vc_formula"])
                else:
                    md = smf.mixedlm("y ~ x", d, groups=d[kw["groups"]])
                mf = md.fit(reml=True, method="lbfgs", maxiter=300)
            slope = float(mf.params.get("x", np.nan))
            if not np.isfinite(slope):
                continue
            out.update({
                "slope": slope,
                "se": float(mf.bse.get("x", np.nan)),
                "pvalue": float(mf.pvalues.get("x", np.nan)),
                "converged": bool(mf.converged),
                "cluster_var": float(mf.cov_re.iloc[0, 0]) if mf.cov_re.size else np.nan,
                "resid_var": float(mf.scale),
                "spec": spec_name,
            })
            if out["converged"]:
                return out
        except Exception as exc:  # noqa: BLE001
            log.warning("MixedLM spec %s failed (%s)", spec_name, exc)
            continue
    if out["spec"] == "none":
        log.warning("MixedLM: all specs failed -> NaN slope")
    return out


def cluster_robust_ols(df: pd.DataFrame) -> dict:
    """OLS cooling_advantage ~ CSI with CLUSTER-ROBUST (cluster on spatial cluster) SE.

    The sandwich SE clustered on the spatial cluster is the honest standard error for the
    linear slope: it accounts for arbitrary within-cluster correlation (spatial + temporal)
    without modelling it. Returns slope, cluster-robust SE/p, and the cluster count (the
    effective df for the robust SE). Compared against the naive (iid) SE to show inflation.
    """
    sub = df[[CA_COL, CSI_COL, "cluster_id"]].dropna()
    out = {"slope": np.nan, "se_robust": np.nan, "p_robust": np.nan,
           "se_naive": np.nan, "p_naive": np.nan, "n": int(len(sub)),
           "n_clusters": int(sub["cluster_id"].nunique())}
    if len(sub) < 5 or sub["cluster_id"].nunique() < 2:
        return out
    import statsmodels.api as sm
    X = sm.add_constant(sub[CSI_COL].to_numpy(dtype="float64"))
    y = sub[CA_COL].to_numpy(dtype="float64")
    groups = sub["cluster_id"].to_numpy()
    try:
        ols = sm.OLS(y, X).fit()
        out["se_naive"] = float(ols.bse[1]); out["p_naive"] = float(ols.pvalues[1])
        rob = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": groups})
        out.update({"slope": float(rob.params[1]), "se_robust": float(rob.bse[1]),
                    "p_robust": float(rob.pvalues[1])})
    except Exception as exc:  # noqa: BLE001
        log.warning("cluster-robust OLS failed (%s)", exc)
    return out


def within_cluster_fixed_effect(pixel_df: pd.DataFrame) -> dict:
    """Within-PIXEL demeaned cooling-vs-CSI slope (the repeated-measures temporal model).

    Demeans cooling_advantage_px and mean_csi_tree WITHIN each tree pixel (subtract the
    pixel's own mean over its overpasses), then regresses the demeaned outcome on the
    demeaned CSI -> the slope is identified purely from TEMPORAL within-pixel variation
    (genuinely-new df after the spatial cross-section is swept out). The SIGN/SHAPE PRIOR
    test from the design: a POSITIVE slope here is the WRONG sign for a cooling threshold
    (cooling does NOT decline with stress). Cluster-robust SE on the spatial cluster.
    Reports the design-effect-deflated effective N at rho in {0.3, 0.5, 0.7}.
    """
    cols = ["cooling_advantage_px", "mean_csi_tree", "tree_row", "tree_col", "cluster_id"]
    sub = pixel_df[cols].dropna().copy()
    sub["pix"] = sub["tree_row"].astype(str) + "_" + sub["tree_col"].astype(str)
    out = {"slope": np.nan, "se_robust": np.nan, "p_robust": np.nan,
           "n_obs": int(len(sub)), "n_pixels": int(sub["pix"].nunique()),
           "deff_eff_n": {}}
    if len(sub) < 10:
        return out
    g = sub.groupby("pix")
    sub["y_dm"] = sub["cooling_advantage_px"] - g["cooling_advantage_px"].transform("mean")
    sub["x_dm"] = sub["mean_csi_tree"] - g["mean_csi_tree"].transform("mean")
    keep = sub["x_dm"].abs() > 1e-12  # pixels with >1 distinct CSI contribute
    s2 = sub[keep]
    if len(s2) < 10 or s2["cluster_id"].nunique() < 2:
        return out
    import statsmodels.api as sm
    X = sm.add_constant(s2["x_dm"].to_numpy(dtype="float64"))
    y = s2["y_dm"].to_numpy(dtype="float64")
    try:
        rob = sm.OLS(y, X).fit(cov_type="cluster",
                               cov_kwds={"groups": s2["cluster_id"].to_numpy()})
        out.update({"slope": float(rob.params[1]), "se_robust": float(rob.bse[1]),
                    "p_robust": float(rob.pvalues[1])})
    except Exception as exc:  # noqa: BLE001
        log.warning("within-pixel FE failed (%s)", exc)
    # design-effect deflation: Deff = 1 + (m_bar - 1) * rho ; eff N = n / Deff
    n = len(s2)
    m_bar = n / max(s2["pix"].nunique(), 1)
    for rho in (0.3, 0.5, 0.7):
        deff = 1.0 + (m_bar - 1.0) * rho
        out["deff_eff_n"][str(rho)] = round(n / deff, 1) if deff > 0 else float(n)
    return out


# =========================================================================== #
# 2 km grid-tile robustness (de-concentration) on the cluster centroids
# =========================================================================== #
def grid_tile_id(df: pd.DataFrame, tile_m: float, *, offset_m: float = 0.0) -> pd.Series:
    """Assign each cluster-overpass row a 2 km grid-tile id from the cluster CENTROID x/y.

    Reuses the explore_pairing_units grid lattice idea on the (per-cluster) centroid
    coordinates, so the dominant BG's single 171-px clump is split across ~8 tiles. The
    cluster centroid x/y are recovered from the cluster table by joining the clusters
    parquet; here we accept x/y already present (added by the caller). ``offset_m`` shifts
    the lattice origin for the offset-lattice sensitivity (researcher-DoF check).
    """
    x = df["cx"].to_numpy(dtype="float64"); y = df["cy"].to_numpy(dtype="float64")
    x0 = float(config.GRID_BOUNDS[0]) + offset_m
    ytop = float(config.GRID_BOUNDS[3]) + offset_m
    col_tile = np.floor((x - x0) / tile_m).astype("int64")
    row_tile = np.floor((ytop - y) / tile_m).astype("int64")
    nct = int(col_tile.max()) + 1 if col_tile.size else 1
    return pd.Series((row_tile * nct + col_tile) + 1, index=df.index)


# =========================================================================== #
# The full analysis on one cluster-overpass subset (reuses the s14 gate)
# =========================================================================== #
def analyze_subset(df: pd.DataFrame, *, label: str, n_boot: int, seed: int) -> dict:
    """Run the Section 14 honesty gate on a cluster-overpass subset, using the CLUSTER
    bootstrap for the breakpoint CI (so the effective N is the cluster count, not the rows).
    Returns a dict with the verdict + all supporting numbers + the effective-N report.
    """
    x = df[CSI_COL].to_numpy(dtype="float64")
    y = df[CA_COL].to_numpy(dtype="float64")
    et = df[ET_COL].to_numpy(dtype="float64")

    shape = s14.describe_shape(x, y)
    comparison = s14.compare_linear_segmented(x, y, seed=seed)
    seg = comparison["segmented"]
    boot = cluster_bootstrap_breakpoint(df, n_boot=n_boot, seed=seed)   # CLUSTER resample
    cp = s14.changepoint_csi(x, y)
    et_check = s14.et_declines_beyond(x, et, seg["breakpoint"])
    verdict = s14.threshold_verdict(segmented=seg, bootstrap=boot, changepoint=cp,
                                    et_check=et_check, comparison=comparison)
    binned = s14.bin_means(x, y, n_bins=s14.DEFAULT_N_BINS)
    eff = effective_n_report(df)
    return {
        "label": label,
        "n_cluster_overpass": int(np.isfinite(x).sum()),
        "effective_n": eff,
        "shape": shape,
        "linear": comparison["linear"],
        "segmented": {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                      for k, v in seg.items()},
        "delta_aic": comparison["delta_aic"],
        "delta_r2": comparison["delta_r2"],
        "bootstrap": {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                      for k, v in boot.items() if k != "estimates"},
        "changepoint_csi": cp["changepoint_csi"],
        "et_check": et_check,
        "verdict": {"robust": verdict.robust, "label": verdict.label,
                    "breakpoint": verdict.breakpoint, "ci_low": verdict.ci_low,
                    "ci_high": verdict.ci_high, "changepoint": verdict.changepoint,
                    "methods_agree": verdict.methods_agree,
                    "bend_visible": verdict.bend_visible,
                    "et_corroborates": verdict.et_corroborates,
                    "well_identified": verdict.well_identified,
                    "spans_fraction": verdict.spans_fraction,
                    "slope_change": verdict.slope_change,
                    "reasons": verdict.reasons},
        "binned": {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                   for k, v in binned.items()},
    }


# =========================================================================== #
# Orchestration
# =========================================================================== #
def run(n_boot: int | None = None, seed: int = s14.DEFAULT_SEED) -> dict:
    config.ensure_dirs()
    processed = config.PROCESSED_DIR
    n_boot = int(n_boot if n_boot is not None else config.N_BOOT_PIXEL)
    cluster_all = pd.read_parquet(processed / MASTER_CLUSTER_PARQUET)
    pixel_all = pd.read_parquet(processed / MASTER_PIXEL_PARQUET)

    # cluster centroids (for the 2 km grid pass) from the clusters parquet.
    clu = pd.read_parquet(processed / "section16_pixel_clusters.parquet")
    centroids = clu.groupby("cluster_id").agg(cx=("x", "mean"), cy=("y", "mean")).reset_index()

    primary_R = float(config.R_PAIR_M)
    results: dict = {"primary_R_m": primary_R, "n_boot": n_boot, "seed": seed,
                     "by_radius": {}, "primary": {}}

    # ---- R-sweep: primary verdict per radius (cluster-overpass) -------------- #
    for R in sorted(cluster_all["R_m"].unique()):
        df_R = cluster_all[cluster_all["R_m"] == R].copy()
        res = analyze_subset(df_R, label=f"cluster-queen R={int(R)}m", n_boot=n_boot, seed=seed)
        results["by_radius"][str(int(R))] = res
        log.info("R=%4.0fm [%s]: bp=%.3f CI=(%.3f,%.3f) spans=%.2f agree=%s bend=%s ET=%s "
                 "-> %s  (clusters=%d, BG=%d, Kish_cl=%.1f, Kish_bg=%.1f)",
                 R, res["label"], res["verdict"]["breakpoint"], res["verdict"]["ci_low"],
                 res["verdict"]["ci_high"], res["verdict"]["spans_fraction"],
                 res["verdict"]["methods_agree"], res["verdict"]["bend_visible"],
                 res["verdict"]["et_corroborates"], res["verdict"]["label"],
                 res["effective_n"]["n_clusters"], res["effective_n"]["n_bg"],
                 res["effective_n"]["kish_neff_clusters"], res["effective_n"]["kish_neff_bg"])

    # ---- PRIMARY radius: the full clustering-aware stack --------------------- #
    dfp = cluster_all[cluster_all["R_m"] == primary_R].copy()
    pxp = pixel_all[pixel_all["R_m"] == primary_R].copy()
    primary = dict(results["by_radius"][str(int(primary_R))])

    # (a) MixedLM random intercept (cluster nested in BG)
    primary["mixedlm"] = mixedlm_random_intercept(dfp)
    # (b) cluster-robust OLS slope
    primary["cluster_robust_ols"] = cluster_robust_ols(dfp)
    # (c) temporal-block bootstrap of the breakpoint
    primary["temporal_block_bootstrap"] = {
        k: (v.tolist() if isinstance(v, np.ndarray) else v)
        for k, v in temporal_block_bootstrap_breakpoint(dfp, n_boot=n_boot, seed=seed).items()}
    # (d) within-pixel fixed-effect temporal slope (sign/shape prior)
    primary["within_pixel_fe"] = within_cluster_fixed_effect(pxp)

    # (e) FALSIFICATION: leave-the-dominant-BG-out refit
    df_nodom = dfp[dfp["GEOID"] != DOMINANT_BG_GEOID].copy()
    primary["leave_dominant_out"] = analyze_subset(
        df_nodom, label=f"cluster-queen R={int(primary_R)}m LEAVE-DOMINANT-OUT",
        n_boot=n_boot, seed=seed)
    log.info("LEAVE-DOMINANT-OUT (drop %s): n_cluster-overpass=%d clusters=%d BG=%d -> %s",
             DOMINANT_BG_GEOID, primary["leave_dominant_out"]["n_cluster_overpass"],
             primary["leave_dominant_out"]["effective_n"]["n_clusters"],
             primary["leave_dominant_out"]["effective_n"]["n_bg"],
             primary["leave_dominant_out"]["verdict"]["label"])

    # (f) ROBUSTNESS: rook clusters at primary R (re-aggregate from pixel rows)
    primary["rook"] = _rook_subset_analysis(pxp, n_boot=n_boot, seed=seed, primary_R=primary_R)

    # (g) ROBUSTNESS: 2 km grid-tile unit (+ offset lattice)
    primary["grid_2km"] = _grid_subset_analysis(dfp, centroids, n_boot=n_boot, seed=seed)

    results["primary"] = primary

    # ---- HONEST RECONCILIATION verdict --------------------------------------- #
    pv = primary["verdict"]
    ldo = primary["leave_dominant_out"]["verdict"]
    overall_robust = bool(pv["robust"] and ldo["robust"])
    survives_dominant = bool(ldo["robust"]) if pv["robust"] else None
    results["overall"] = {
        "primary_verdict": pv["label"],
        "primary_robust": pv["robust"],
        "leave_dominant_out_verdict": ldo["label"],
        "survives_dominant_drop": survives_dominant,
        "final_verdict": "robust_threshold" if overall_robust else "no_robust_threshold",
        "within_pixel_slope_sign": ("positive (WRONG sign for a threshold)"
                                    if np.isfinite(primary["within_pixel_fe"]["slope"])
                                    and primary["within_pixel_fe"]["slope"] > 0
                                    else "negative/na"),
    }

    out_json = processed / RESULTS_JSON
    with open(out_json, "w") as fh:
        json.dump(_jsonable(results), fh, indent=2)
    log.info("Wrote %s", out_json.name)
    _print_sensitivity_table(results)
    return results


def _rook_subset_analysis(pixel_df_R: pd.DataFrame, *, n_boot, seed, primary_R) -> dict:
    """Re-label tree px into ROOK clusters and re-aggregate at the primary R, then analyze.

    The pixel rows already carry the QUEEN cluster_id; for the rook sensitivity we re-derive
    rook cluster ids from the tree (row, col) coordinates and re-aggregate. Reuses the
    pairing module's rook labelling + count-weighted collapse so the unit definition is the
    only thing that changes.
    """
    import section16_pixel_pairing as s16p
    if pixel_df_R.empty:
        return {"label": "rook (empty)", "verdict": {"label": "inconclusive", "robust": False}}
    # rebuild rook labels over the full grid tree mask, map to these pixels.
    cm = s16p.candidate_masks()
    rook_labels, _ = s16p.label_clusters(cm["tree"], "rook")
    df = pixel_df_R.copy()
    df["cluster_id"] = rook_labels[df["tree_row"].to_numpy(), df["tree_col"].to_numpy()]
    cl = s16p.aggregate_to_clusters(df)
    return analyze_subset(cl, label=f"cluster-ROOK R={int(primary_R)}m",
                          n_boot=n_boot, seed=seed)


def _grid_subset_analysis(dfp: pd.DataFrame, centroids: pd.DataFrame, *, n_boot, seed) -> dict:
    """Re-aggregate the cluster-overpass rows into 2 km GRID TILES and analyze (+offset).

    Each cluster's centroid is assigned a 2 km tile; cluster-overpass rows are re-grouped by
    (tile, overpass) with a count-weighted cooling advantage (weight = n_tree_px_valid) and
    mean CSI/ET. The dominant BG's single clump splits across tiles, so this checks the
    threshold result is invariant to the spatial-unit definition. Reports the offset-lattice
    sensitivity (origin shifted by tile/2) so the grid phase is not a hidden DoF.
    """
    base = dfp.merge(centroids, on="cluster_id", how="left")
    res = {}
    for tag, off in (("grid_2km", 0.0), ("grid_2km_offset", config.GRID_TILE_M / 2.0)):
        d = base.copy()
        d["tile"] = grid_tile_id(d, config.GRID_TILE_M, offset_m=off)
        # re-aggregate to (tile, overpass) with count-weighted CA.
        rows = []
        for (tile, o), g in d.groupby(["tile", "overpass_index"]):
            ca = float(np.sum(g[CA_COL] * g["n_tree_px_valid"]) / g["n_tree_px_valid"].sum()) \
                if g["n_tree_px_valid"].sum() > 0 else np.nan
            rows.append({"cluster_id": int(tile), "GEOID": str(g["GEOID"].mode().iloc[0]),
                         "overpass_index": int(o), CA_COL: ca,
                         CSI_COL: float(g[CSI_COL].mean()),
                         ET_COL: float(np.nanmean(g[ET_COL])) if g[ET_COL].notna().any() else np.nan,
                         "n_tree_px_valid": int(g["n_tree_px_valid"].sum())})
        gd = pd.DataFrame(rows)
        sizes = gd.groupby("cluster_id").size().to_numpy()
        analysis = analyze_subset(gd, label=tag, n_boot=n_boot, seed=seed)
        analysis["invsimpson_tiles"] = round(inverse_simpson(sizes), 2)
        analysis["n_tiles"] = int(gd["cluster_id"].nunique())
        res[tag] = analysis
    return res


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def _print_sensitivity_table(results: dict) -> None:
    log.info("=" * 100)
    log.info("SECTION 16 SENSITIVITY TABLE (clustering-aware; effective N, not nominal rows)")
    log.info("=" * 100)
    hdr = (f"{'unit/subset':<34} {'rows':>5} {'clu':>4} {'BG':>3} {'Kish_cl':>7} "
           f"{'Kish_bg':>7} {'bp':>6} {'CI_lo':>6} {'CI_hi':>6} {'spans':>6} "
           f"{'agree':>5} {'bend':>5} {'ET':>4} {'verdict':>20}")
    log.info(hdr)
    log.info("-" * 100)

    def _row(res):
        v = res["verdict"]; e = res["effective_n"]
        return (f"{res['label']:<34} {res['n_cluster_overpass']:>5} {e['n_clusters']:>4} "
                f"{e['n_bg']:>3} {e['kish_neff_clusters']:>7.1f} {e['kish_neff_bg']:>7.1f} "
                f"{v['breakpoint']:>6.3f} {v['ci_low']:>6.3f} {v['ci_high']:>6.3f} "
                f"{v['spans_fraction']:>6.2f} {str(v['methods_agree']):>5} "
                f"{str(v['bend_visible']):>5} {str(v['et_corroborates']):>4} "
                f"{v['label']:>20}")

    for R in sorted(results["by_radius"], key=lambda s: int(s)):
        log.info(_row(results["by_radius"][R]))
    p = results["primary"]
    log.info(_row(p["leave_dominant_out"]))
    log.info(_row(p["rook"]))
    for tag in ("grid_2km", "grid_2km_offset"):
        if tag in p["grid_2km"]:
            r = p["grid_2km"][tag]
            log.info(_row(r) + f"  [invSimpson tiles={r.get('invsimpson_tiles')}, "
                     f"n_tiles={r.get('n_tiles')}]")
    log.info("-" * 100)
    log.info("MixedLM (cluster nested in BG): slope=%.4f SE=%.4f p=%.3f converged=%s",
             p["mixedlm"]["slope"], p["mixedlm"]["se"], p["mixedlm"]["pvalue"],
             p["mixedlm"]["converged"])
    cr = p["cluster_robust_ols"]
    log.info("Cluster-robust OLS slope=%.4f  SE_robust=%.4f (p=%.3f)  vs SE_naive=%.4f "
             "(p=%.3f)  [SE inflation x%.1f]",
             cr["slope"], cr["se_robust"], cr["p_robust"], cr["se_naive"], cr["p_naive"],
             cr["se_robust"] / cr["se_naive"] if cr["se_naive"] else float("nan"))
    fe = p["within_pixel_fe"]
    log.info("Within-PIXEL FE (temporal) slope=%.4f SE=%.4f p=%.3f  (n_obs=%d n_px=%d; "
             "design-effect eff N rho0.3/0.5/0.7=%s)  SIGN PRIOR: %s",
             fe["slope"], fe["se_robust"], fe["p_robust"], fe["n_obs"], fe["n_pixels"],
             fe["deff_eff_n"], results["overall"]["within_pixel_slope_sign"])
    log.info("=" * 100)
    ov = results["overall"]
    log.info("PRIMARY verdict           : %s", ov["primary_verdict"])
    log.info("LEAVE-DOMINANT-OUT verdict: %s", ov["leave_dominant_out_verdict"])
    log.info("SURVIVES dominant drop?   : %s", ov["survives_dominant_drop"])
    log.info("FINAL VERDICT             : %s", ov["final_verdict"].upper())
    log.info("=" * 100)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 16 - clustering-aware threshold analysis on the enlarged "
                    "pixel/cluster paired sample (reuses the Section 14 honesty gate).")
    p.add_argument("--n-boot", type=int, default=None,
                   help="cluster-bootstrap resamples (default config.N_BOOT_PIXEL=2000).")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv=None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    run(n_boot=args.n_boot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
