"""Exploratory nonlinear canopy association; preserve the primary estimator."""
import numpy as np
import pandas as pd
from urban_cooling_v2.pooled_city_pass import CONTEXT, fit_city_pass

SPLINE_COLUMNS = ("canopy_fraction", "canopy_rcs_1", "canopy_rcs_2")


def spline_basis(values, knots):
    """Four-knot restricted cubic basis, normalized by outer-knot span squared.

    Formula follows Hmisc::rcspline.eval(norm=2, inclx=TRUE). Transform raw
    canopy first; block centering occurs later inside the FE estimator.
    """
    x = np.atleast_1d(np.asarray(values, float))
    k = np.asarray(knots, float)
    if k.shape != (4,) or not np.isfinite(k).all() or not (np.diff(k) > 0).all():
        raise ValueError("Four distinct ordered finite knots required")
    if not np.isfinite(x).all():
        raise ValueError("Finite canopy values required")
    result = [x]
    for first in k[:-2]:
        h = (np.maximum(x-first, 0)**3
             - np.maximum(x-k[-2], 0)**3 * (k[-1]-first)/(k[-1]-k[-2])
             + np.maximum(x-k[-1], 0)**3 * (k[-2]-first)/(k[-1]-k[-2]))
        result.append(h / (k[-1]-k[0])**2)
    return np.column_stack(result)


def spatial_groups(frame):
    if not frame.cell_id.is_unique:
        raise ValueError("Duplicate native cell IDs")
    groups = (np.floor(frame.x/8000).astype(int).astype(str) + "_"
              + np.floor(frame.y/8000).astype(int).astype(str))
    check = pd.DataFrame({"block": frame.block, "group": groups})
    if check.groupby("block").group.nunique().max() != 1:
        raise ValueError("Original block crosses an 8km resampling group")
    return groups


def fit_curve(frame, knots, *, replicates=1000, seed=20260930):
    d = frame.copy()
    d["spatial_group"] = spatial_groups(d)
    basis = spline_basis(d.canopy_fraction, knots)
    for j, name in enumerate(SPLINE_COLUMNS[1:], 1):
        d[name] = basis[:, j]
    fit = fit_city_pass(d, context=(*CONTEXT, *SPLINE_COLUMNS[1:]),
                        bootstrap_replicates=replicates, seed=seed,
                        cluster_column="spatial_group")
    if set(fit.predictor_names) != set((*CONTEXT, *SPLINE_COLUMNS)):
        raise ValueError("Full prespecified nonlinear design is not identifiable")
    return d, fit


def curve_difference(fit, knots, canopy, reference):
    """Positive reductions relative to reference, paired LST/energy and draws."""
    ix = [fit.predictor_names.index(n) for n in SPLINE_COLUMNS]
    delta = spline_basis(canopy, knots) - spline_basis([reference], knots)
    point = -delta @ fit.coefficients[ix]
    draws = -np.einsum("xk,bko->bxo", delta, fit.bootstrap_coefficients[:, ix, :])
    return point, draws


def partial_cooling(frame, fit, knots, reference):
    """Adjusted observations: reference canopy component minus partial response."""
    block_index = pd.Index(fit.block_labels).get_indexer(frame.block.astype(str))
    if (block_index < 0).any():
        raise ValueError("Unknown original block")
    x = frame[fit.predictor_names].to_numpy(float)
    fitted = fit.block_y_means[block_index] + (x-fit.block_x_means[block_index]) @ fit.coefficients
    residual = frame.LST_K.to_numpy() - fitted[:, 0]
    ix = [fit.predictor_names.index(n) for n in SPLINE_COLUMNS]
    delta = spline_basis(frame.canopy_fraction, knots) - spline_basis([reference], knots)
    return -delta @ fit.coefficients[ix, 0] - residual


def linear_check(frame, fit):
    """Recover the original linear coefficient from exactly these paired cells."""
    cols = ["canopy_fraction", *CONTEXT]
    ix = [fit.predictor_names.index(n) for n in cols]
    bi = pd.Index(fit.block_labels).get_indexer(frame.block.astype(str))
    xc = frame[cols].to_numpy(float) - fit.block_x_means[bi][:, ix]
    yc = frame[["LST_K", "M_W_m2"]].to_numpy(float) - fit.block_y_means[bi]
    norm = np.linalg.norm(xc, axis=0)
    return np.linalg.lstsq(xc/norm, yc, rcond=1e-10)[0] / norm[:, None]


def summarize_bins(frame, adjusted, edges):
    f = frame.canopy_fraction.to_numpy()
    ids = np.searchsorted(edges, f, side="right") - 1
    ids[f == edges[-1]] = len(edges)-2
    raw = frame.LST_K.to_numpy() - frame.LST_K.mean()
    rows = []
    for j in range(len(edges)-1):
        sel = ids == j
        rows.append({"bin": j, "canopy_lower": edges[j], "canopy_upper": edges[j+1],
                     "n_cells": int(sel.sum()), "n_blocks": int(frame.loc[sel, "block"].nunique()),
                     "mean_canopy": float(np.mean(f[sel])) if sel.any() else np.nan,
                     "adjusted_cooling_C": float(np.mean(adjusted[sel])) if sel.any() else np.nan,
                     "observed_LST_minus_pass_mean_C": float(np.mean(raw[sel])) if sel.any() else np.nan})
    return rows
