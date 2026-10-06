"""Step 3 sufficient statistics, paired draws and strictly sealed effect outputs."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import pickle
import zipfile

import numpy as np
import pandas as pd

from urban_cooling_v2.pooled_city_pass import SIGMA, _group_sum, temperature_equivalent
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path

OUTCOMES = ("LST_K", "M_W_m2")
QUANTILES = (0, .01, .05, .1, .25, .5, .75, .9, .95, .99, 1)
PRECISION_FIELDS = (
    "city", "orbit", "date", "kind", "variant", "source_run_id", "group_km",
    "n_cells", "n_blocks", "groups", "bootstrap_requested", "bootstrap_estimable", "bootstrap_failed",
    "T_SE_K_per_10pp", "T_width95_K_per_10pp", "M_SE_W_m2_per_10pp", "M_width95_W_m2_per_10pp",
    "interval_method", "pairing_status", "effect_status",
)


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def identity_hash(ids): return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


class LabelUnpickler(pickle.Unpickler):
    """Decode historical NumPy object-string arrays, never arbitrary globals."""
    def find_class(self, module, name):
        import numpy._core.multiarray as core
        allowed = {("numpy", "ndarray"): np.ndarray, ("numpy", "dtype"): np.dtype,
                   ("numpy._core.multiarray", "_reconstruct"): core._reconstruct,
                   ("numpy.core.multiarray", "_reconstruct"): core._reconstruct,
                   ("numpy._core.multiarray", "scalar"): core.scalar,
                   ("numpy.core.multiarray", "scalar"): core.scalar}
        if (module, name) not in allowed: raise pickle.UnpicklingError("Unsupported global in historical label array")
        return allowed[(module, name)]


def read_object_labels(path, key):
    if key not in ("block_labels", "predictor_names", "outcome_names"): raise ValueError("Object decoding is restricted to labels")
    with zipfile.ZipFile(path) as archive, archive.open(key+".npy") as handle:
        version = np.lib.format.read_magic(handle)
        shape, _, dtype = np.lib.format._read_array_header(handle, version)
        if len(shape)!=1 or not dtype.hasobject: raise ValueError("Expected one-dimensional historical object labels")
        labels = LabelUnpickler(handle).load()
    if not isinstance(labels, np.ndarray) or labels.shape!=shape or labels.ndim!=1 or not all(isinstance(x, (str, np.str_)) for x in labels):
        raise ValueError("Historical labels must be plain strings")
    return np.asarray(labels, dtype=str)


def common_ids(frames):
    result = None
    for frame in frames:
        ids = frame["cell_id"]
        if ids.isna().any() or ids.duplicated().any(): raise ValueError("Nonunique/missing native cell identity")
        result = set(ids) if result is None else result.intersection(ids)
    if result is None: raise ValueError("No input frames")
    return sorted(result)


def validate_native_rows(frame):
    if frame.cell_id.isna().any() or frame.cell_id.duplicated().any(): raise ValueError("Duplicate native identity")
    if frame[["native_crs", "native_x", "native_y"]].duplicated().any(): raise ValueError("Duplicate ground footprint")
    expected = np.array([f"{x}_{y}" for x, y in zip(np.floor(frame.x/1000).astype(int), np.floor(frame.y/1000).astype(int))])
    if not np.array_equal(expected, frame.block.astype(str).to_numpy()): raise ValueError("Physical block identity mismatch")


@dataclass
class BlockStats:
    labels: np.ndarray
    predictors: tuple
    norms: np.ndarray
    xx: np.ndarray
    xy: np.ndarray
    n_cells: int

    def solve(self, counts=None):
        counts = np.ones(len(self.labels)) if counts is None else np.asarray(counts, float)
        if counts.shape != (len(self.labels),) or not np.isfinite(counts).all() or (counts < 0).any():
            raise ValueError("Invalid physical-block multiplicities")
        xx = np.einsum("b,bij->ij", counts, self.xx)
        xy = np.einsum("b,bik->ik", counts, self.xy)
        if np.linalg.matrix_rank(xx, tol=1e-10) < len(self.predictors):
            raise ValueError("Resampled design not estimable")
        return np.linalg.solve(xx, xy) / self.norms[:, None]


def block_stats(frame, predictors, outcomes=OUTCOMES):
    """Original within-block centering and fixed archived predictor design.

    Normalization is numerical conditioning only, not a support restriction.
    Repeated blocks retain independent intercepts; their centered statistics add.
    """
    if not predictors or predictors[0] != "canopy_fraction": raise ValueError("Canopy must be first")
    x = frame[list(predictors)].to_numpy(float)
    y = frame[list(outcomes)].to_numpy(float)
    if len(x) < 3 or not np.isfinite(x).all() or not np.isfinite(y).all(): raise ValueError("Incomplete paired rows")
    if ((x[:, 0] < 0) | (x[:, 0] > 1)).any(): raise ValueError("Invalid canopy fraction")
    labels, inv = np.unique(frame.block.astype(str), return_inverse=True)
    counts = np.bincount(inv)
    xm = _group_sum(x, inv, len(labels)) / counts[:, None]
    ym = _group_sum(y, inv, len(labels)) / counts[:, None]
    xc, yc = x - xm[inv], y - ym[inv]
    norms = np.sqrt((xc**2).sum(axis=0))
    if (norms <= 1e-12).any(): raise ValueError("Frozen predictor has no within-block information")
    a = xc / norms
    if np.linalg.matrix_rank(a, tol=1e-10) < len(predictors) or len(x)-len(labels)-len(predictors) <= 0:
        raise ValueError("Frozen within-block design is not estimable")
    # Accumulate pairwise columns, avoiding an n_cells x 7 x 7 temporary array.
    xx = np.empty((len(labels), len(predictors), len(predictors)))
    xy = np.empty((len(labels), len(predictors), len(outcomes)))
    for i in range(len(predictors)):
        for j in range(i, len(predictors)):
            xx[:, i, j] = xx[:, j, i] = np.bincount(inv, weights=a[:, i]*a[:, j], minlength=len(labels))
        for k in range(len(outcomes)):
            xy[:, i, k] = np.bincount(inv, weights=a[:, i]*yc[:, k], minlength=len(labels))
    return BlockStats(labels, tuple(predictors), norms, xx, xy, len(frame))


def physical_groups(labels, size):
    if size not in (1, 8): raise ValueError("Only frozen 1km/8km joint sensitivities")
    return np.asarray([f"{int(label.split('_')[0])//size}_{int(label.split('_')[1])//size}" for label in labels])


def joint_bootstrap(original, common, *, replicates=1000, seed=20261004, group_km=1):
    """One multiplicity draw on the union of physical groups applied to both fits.

    Common support missing a block has zero contribution. Never pair unrelated
    archived bootstrap indices, and never sample pixels as independent blocks.
    """
    union = np.union1d(original.labels, common.labels)
    group_labels = physical_groups(union, group_km)
    groups, union_group = np.unique(group_labels, return_inverse=True)
    if len(groups) < 2: raise ValueError("Fewer than two resampling groups")
    indices = [union_group[np.searchsorted(union, s.labels)] for s in (original, common)]
    rng = np.random.default_rng(seed)
    draws = np.full((replicates, 2, 2), np.nan)
    count_hash = hashlib.sha256()
    for b in range(replicates):
        counts = rng.multinomial(len(groups), np.full(len(groups), 1/len(groups)))
        count_hash.update(counts.astype("<i8").tobytes())
        try:
            for k, stat in enumerate((original, common)):
                draws[b, k] = -.1 * stat.solve(counts[indices[k]])[0]
        except ValueError:
            draws[b] = np.nan
    valid = np.isfinite(draws).all(axis=(1, 2))
    return {"points": np.stack([-.1*s.solve()[0] for s in (original, common)]),
            "draws": draws, "difference_draws": draws[:, 1]-draws[:, 0], "valid": valid,
            "groups": len(groups), "physical_group_identity_sha256": identity_hash(groups),
            "draw_multiplicity_sha256": count_hash.hexdigest(), "requested": replicates,
            "estimable": int(valid.sum()), "failed": int((~valid).sum()), "group_km": group_km}


def summary(point, draws):
    a = np.asarray(draws, float)
    valid = np.isfinite(a).all(axis=-1) if a.ndim > 1 else np.isfinite(a)
    if valid.sum() < 2: return {"status": "NOT_ESTIMABLE", "estimable": int(valid.sum())}
    q = np.quantile(a[valid], [.025, .975], axis=0)
    return {"status": "ESTIMABLE", "point": np.asarray(point).tolist(), "SE": np.std(a[valid], axis=0, ddof=1).tolist(),
            "q025": q[0].tolist(), "q975": q[1].tolist(), "estimable": int(valid.sum())}


def paired_scale(temperature_change, flux_change, boot_changes, reference_K, emissivity):
    """Exact reference-anchored fourth-root transform in every matched draw."""
    anchor = emissivity * SIGMA * reference_K**4
    if not np.isfinite([temperature_change, flux_change, reference_K, emissivity]).all() or reference_K <= 0 or not 0 < emissivity <= 1 or anchor+flux_change <= 0:
        return {"status": "NOT_ESTIMABLE_AT_REFERENCE", "requested": len(boot_changes)}, None
    b = np.asarray(boot_changes, float)
    valid = np.isfinite(b).all(axis=1) & (anchor+b[:, 1] > 0)
    values = np.full_like(b, np.nan)
    values[valid, 0] = -b[valid, 0]
    values[valid, 1] = -temperature_equivalent(b[valid, 1], reference_K, emissivity)
    point = [-temperature_change, -float(temperature_equivalent(flux_change, reference_K, emissivity))]
    result = summary(point, values)
    if result["status"] == "ESTIMABLE":
        result["paired_T_minus_equivalent"] = summary(point[0]-point[1], values[:, 0]-values[:, 1])
    result.update(requested=len(b), failed=int((~valid).sum()), reference_K=reference_K, reference_emissivity=emissivity)
    return result, values


def reference_support(frame, f0, f1):
    if not np.isclose(f1-f0, .1) or not 0 <= f0 < f1 <= 1: raise ValueError("Invalid frozen reference endpoints")
    bounds = frame.groupby("block").canopy_fraction.agg(["min", "max"])
    labels = bounds.index[(bounds["min"] <= f0) & (bounds["max"] >= f1)]
    mask = frame.block.isin(labels).to_numpy()
    return mask, {"supporting_blocks": len(labels), "reference_cells": int(mask.sum()),
                  "status": "SUPPORTED" if len(labels) else "NOT_SUPPORTED_NO_REFERENCE_BLOCKS"}


def predictor_distribution(values):
    values = np.asarray(values, float)
    if not np.isfinite(values).all(): raise ValueError("Incomplete predictor distribution")
    if not len(values): return {"n": 0, "mean": None, "sd": None, **{f"q{int(q*100):02d}": None for q in QUANTILES}}
    return {"n": len(values), "mean": float(values.mean()), "sd": float(values.std(ddof=1)) if len(values)>1 else None,
            **{f"q{int(q*100):02d}": float(v) for q, v in zip(QUANTILES, np.quantile(values, QUANTILES))}}


def public_precision(row):
    if set(row) != set(PRECISION_FIELDS): raise ValueError("Public precision contains an undocumented or sensitive field")
    if row["effect_status"] != "SEALED_USER_REQUEST": raise ValueError("New effect display is not authorized")
    for k in ("T_SE_K_per_10pp", "T_width95_K_per_10pp", "M_SE_W_m2_per_10pp", "M_width95_W_m2_per_10pp"):
        if row[k] is not None and (not np.isfinite(row[k]) or row[k] < 0): raise ValueError("Invalid precision")
    return dict(row)


def write_sealed_json(root, run, filename, value):
    if "SEALED" not in filename: raise ValueError("Sealed effect file must have explicit label")
    path = guarded_output_path(Path(root), "sealed", f"{run}/{filename}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")
    path.chmod(0o600)
    return path
