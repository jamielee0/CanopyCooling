"""Matched linear/quadratic sensitivity; all empirical effects stay sealed."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

from urban_cooling_v2.pooled_city_pass import CONTEXT, SIGMA, _group_sum
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path
from .canopy_support import protected_design, group_statistics

OUTCOMES = ("LST_K", "M_W_m2")
PRECISION_FIELDS = {
    "city", "orbit", "date", "pair_id", "f0", "f1", "group_km", "model",
    "quantity", "units", "requested", "estimable", "failed", "SE", "width95",
    "effect_status", "support_status",
}


@dataclass
class Model:
    design: object
    coefficients: np.ndarray
    block_y_means: np.ndarray
    xy: np.ndarray


def fit_model(frame, *, quadratic, context=CONTEXT):
    design = protected_design(frame, quadratic=quadratic, context=context)
    y = frame[list(OUTCOMES)].to_numpy(float)
    if not np.isfinite(y).all():
        raise ValueError("Incomplete paired outcomes; no row deletion permitted")
    bi = design.row_blocks
    means = _group_sum(y, bi, len(design.block_labels)) / np.bincount(bi)[:, None]
    centered = y - means[bi]
    p = len(design.names)
    xy = np.empty((len(design.block_labels), p, 2))
    for j in range(p):
        for k in range(2):
            xy[:, j, k] = np.bincount(bi, weights=design.scaled[:, j] * centered[:, k],
                                      minlength=len(design.block_labels))
    coef = np.linalg.solve(design.xx.sum(axis=0), xy.sum(axis=0)) / design.norms[:, None]
    return Model(design, coef, means, xy)


def paired_bootstrap(linear, quadratic, *, group_km, replicates, seed):
    """Whole physical groups, identical draws for both bases and both outcomes."""
    matrices = []
    for model in (linear, quadratic):
        groups, inv, xx = group_statistics(model.design, group_km)
        matrices.append((groups, xx, _group_sum(model.xy, inv, len(groups))))
    if not np.array_equal(matrices[0][0], matrices[1][0]) or len(groups) < 2:
        raise ValueError("Different or insufficient physical resampling groups")
    draws = [np.full((replicates, len(m.design.names), 2), np.nan) for m in (linear, quadratic)]
    rng = np.random.default_rng(seed)
    h = hashlib.sha256()
    for r in range(replicates):
        w = rng.multinomial(len(groups), np.full(len(groups), 1 / len(groups)))
        h.update(w.astype("<i8").tobytes())
        for j, model in enumerate((linear, quadratic)):
            xx = np.einsum("g,gij->ij", w, matrices[j][1])
            xy = np.einsum("g,gik->ik", w, matrices[j][2])
            if np.linalg.matrix_rank(xx, tol=1e-10) != len(model.design.names):
                continue
            draws[j][r] = np.linalg.solve(xx, xy) / model.design.norms[:, None]
    valid = [np.isfinite(a).all(axis=(1, 2)) for a in draws]
    audit = dict(group_km=group_km, groups=len(groups), requested=replicates,
                 linear_estimable=int(valid[0].sum()), quadratic_estimable=int(valid[1].sum()),
                 paired_estimable=int((valid[0] & valid[1]).sum()),
                 paired_failed=int((~(valid[0] & valid[1])).sum()),
                 linear_failed_indices=np.flatnonzero(~valid[0]).tolist(),
                 quadratic_failed_indices=np.flatnonzero(~valid[1]).tolist(),
                 draw_multiplicity_sha256=h.hexdigest())
    return draws, audit


def basis_delta(names, f0, f1):
    if not (0 <= f0 <= 1 and 0 <= f1 <= 1):
        raise ValueError("Canopy endpoints outside fraction range")
    d = np.zeros(len(names))
    d[names.index("canopy_fraction")] = f1 - f0
    if "canopy_squared" in names:
        d[names.index("canopy_squared")] = f1 * f1 - f0 * f0
    return d


def contrast(model, draws, f0, f1):
    d = basis_delta(model.design.names, f0, f1)
    return d @ model.coefficients, np.einsum("p,bpo->bo", d, draws)


def endpoint_averages(model, reference_frame, f0, f1, weights=None):
    """Replace every canopy basis term; average predictions with training centers.

    Reference frames contain complete original blocks spanning both endpoints.
    This independent prediction route verifies the analytic finite contrast.
    """
    if not len(reference_frame):
        raise ValueError("No reference cells")
    bounds = reference_frame.groupby("block").canopy_fraction.agg(["min", "max"])
    if ((bounds["min"] > min(f0, f1)) | (bounds["max"] < max(f0, f1))).any():
        raise ValueError("Reference block lacks endpoint range support")
    ix = pd.Index(model.design.block_labels).get_indexer(reference_frame.block.astype(str))
    if (ix < 0).any():
        raise ValueError("Unknown reference block")
    columns = []
    for name in model.design.names:
        columns.append(reference_frame.canopy_fraction.to_numpy(float)**2 if name == "canopy_squared"
                       else reference_frame[name].to_numpy(float))
    x = np.column_stack(columns)
    w = np.ones(len(x)) if weights is None else np.asarray(weights, float)
    if w.shape != (len(x),) or not np.isfinite(w).all() or (w <= 0).any():
        raise ValueError("Invalid fixed reference weights")
    base = np.average(model.block_y_means[ix], weights=w, axis=0)
    center = np.average(model.design.means[ix], weights=w, axis=0)
    means = []
    for f in (f0, f1):
        target = np.average(x, weights=w, axis=0)
        target[model.design.names.index("canopy_fraction")] = f
        if "canopy_squared" in model.design.names:
            target[model.design.names.index("canopy_squared")] = f * f
        means.append(base + (target - center) @ model.coefficients)
    return np.asarray(means)


def cooling_quantities(changes, reference_K, reference_emissivity):
    """Positive T/flux cooling, exact fixed-reference equivalent, paired departure.

    Input is the difference of averaged endpoint predictions. Invalid fourth-root
    anchors remain missing and are counted; they never remove a T/flux result.
    """
    a = np.asarray(changes, float)
    if a.shape[-1] != 2 or reference_K <= 0 or not 0 < reference_emissivity <= 1:
        raise ValueError("Invalid paired changes or reference")
    anchor = reference_emissivity * SIGMA * reference_K**4
    upper = anchor + a[..., 1]
    valid = np.isfinite(a).all(axis=-1) & (upper > 0)
    equivalent = np.full(a.shape[:-1], np.nan)
    equivalent[valid] = reference_K - (upper[valid] / (reference_emissivity * SIGMA))**.25
    return np.stack((-a[..., 0], -a[..., 1], equivalent, -a[..., 0] - equivalent), axis=-1)


def summarize(point, draws):
    a = np.asarray(draws, float)
    a = a[np.isfinite(a)]
    if not np.isfinite(point) or len(a) < 2:
        return dict(status="NOT_ESTIMABLE", point=None, q025=None, q975=None, SE=None,
                    width95=None, estimable=len(a), failed=len(draws)-len(a))
    lo, hi = np.quantile(a, [.025, .975])
    return dict(status="ESTIMABLE", point=float(point), q025=float(lo), q975=float(hi),
                SE=float(np.std(a, ddof=1)), width95=float(hi-lo), estimable=len(a),
                failed=len(draws)-len(a))


def public_precision(row):
    if set(row) != PRECISION_FIELDS or row["effect_status"] != "SEALED_USER_REQUEST":
        raise ValueError("Unapproved public field or effect release")
    for key in ("SE", "width95"):
        if row[key] is not None and (not np.isfinite(row[key]) or row[key] < 0):
            raise ValueError("Invalid precision diagnostic")
    return dict(row)


def sealed_path(root, run, name):
    if "SEALED" not in name:
        raise ValueError("Explicit sealed label required")
    p = guarded_output_path(Path(root), "sealed", f"{run}/{name}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.parent.chmod(0o700)
    return p


def write_sealed_json(root, run, name, value):
    p = sealed_path(root, run, name)
    # Restrict the file at creation, before any sensitive bytes are written.
    with p.open("x") as stream:
        p.chmod(0o600)
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return p
