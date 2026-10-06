#!/usr/bin/env python3
"""Section 14b / mixed-effects model of the pixel-level cooling advantage (BLOCKERS B3.2 + B3.3).

The unit of analysis is the tree PIXEL (remediation-plan principle 2): each row of
``master_pixel_table.parquet`` is one finite tree pixel carrying its BG x overpass
reference-mean LST, so within-BG and between-BG variation can be
separated. This module fits a crossed random-intercept mixed model on the DAY-ONLY
primary sample and reports the within-BG stress association (``vpd_z_within``,
``sm_z_within``) purged of between-BG confounding via a Mundlak / correlated-within-
between (CWC) decomposition, plus a BG-cluster bootstrap of its CI (principle 3:
clustered uncertainty, <=9 BG clusters).

INPUT CONTRACT -- reads ``data/processed/master_pixel_table.parquet`` (produced by
B3.1 / Section 13), one row per finite tree pixel. Columns relied on (exact names):
  neighborhood_id, overpass_key, cooling_advantage_px (outcome dT_cool),
  vpd_z, sm_z (per-pixel demand/water-supply predictors), ndmi_z (vegetation check),
  aridity, is_day (bool), local_hour (int),
  pixel_row, pixel_col, n_tree_valid, n_ref_valid.

CRITICAL DEPENDENCY NOTES
  * ``is_day`` / ``local_hour`` are PERSISTED columns (owned by B4). They are READ here,
    never re-derived from timestamps (single source of truth).
  * ``sample_label`` is persisted by Section 13 from the pre-committed tree-pixel floor.
    The primary model requires BOTH ``is_day == True`` and ``sample_label == "primary"``;
    low-count rows remain available only for labelled sensitivity analyses.
  * ``statsmodels`` is pinned in ``environment.yml``. Its import remains guarded so the
    pure helpers can be imported in lightweight environments, but the pipeline step fails
    clearly when it is unavailable; a blocker-resolution model must never become a silent
    no-op.

Crossed-RE caveat: with ~9 BGs (one empirically dominant, ``040139412001``) a crossed
variance-component fit can hit boundary variance; the exact dominant-group share is computed
from the fitted sample and written to the note. Documented fallbacks are BG fixed effects +
overpass RE, or GEE (see ``write_note``).

Run: python src/section14b_mixed_effects.py [--verify-only] [-v/--verbose]
"""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

# Make config importable whether run from the repo root or from src/ (same convention as
# the other section modules).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
import config  # noqa: E402

# statsmodels is pinned in the project environment. Guard the import so the pure helpers
# remain usable in lightweight environments; the CLI still fails clearly if it is absent.
try:  # pragma: no cover - exercised by whichever env has/lacks statsmodels
    import statsmodels.api as sm  # noqa: F401
    import statsmodels.formula.api as smf
    HAVE_STATSMODELS = True
except Exception:  # ImportError (and any transitive import failure)
    sm = None  # type: ignore[assignment]
    smf = None  # type: ignore[assignment]
    HAVE_STATSMODELS = False

log = logging.getLogger("section14b")


# --- Deliverable / input names --------------------------------------------- #
PIXEL_PARQUET = "master_pixel_table.parquet"                 # B3.1 pixel table (input)
NOTE_PATH = "docs/section14b_mixed_effects_note.md"          # emitted analysis note

# Column contract (exact names from the pixel table).
OUTCOME_COL = "cooling_advantage_px"     # dT_cool = mean_ref_lst(BG,overpass) - tree_lst_px
GROUP_COL = "neighborhood_id"            # block group -> (1|block_group) random intercept
OVERPASS_COL = "overpass_key"            # overpass  -> (1|overpass) variance component
DAY_COL = "is_day"                       # persisted by B4 (READ, never re-derived)
HOUR_COL = "local_hour"                  # persisted by B4
SAMPLE_LABEL_COL = "sample_label"        # persisted Section-13 primary/sensitivity label

# Per-pixel predictors decomposed into within-BG + between-BG mean parts.
# B1 invariant: the primary water-supply predictor is root-zone soil moisture ``sm_z``;
# ``ndmi_z`` is carried in the pixel table only as a vegetation-side sensitivity check.
MUNDLAK_COLS = ("vpd_z", "sm_z")
# Fixed-effect design after the Mundlak/CWC decomposition. The *_within coefficients are
# within-BG associations purged of between-BG confounding; because rows are repeated pixels,
# these terms may contain both within-BG spatial and temporal variation. The *_bg_mean
# coefficients absorb the spatial between-BG gradient.
FIXED_EFFECT_COLS = ["vpd_z_within", "sm_z_within", "vpd_z_bg_mean", "sm_z_bg_mean"]
KEY_COEF = "vpd_z_within"                # headline within-BG coefficient (B3.3 CI target)

# The dominant BG is preidentified, but its share depends on the exact complete-case fitted
# sample and is therefore calculated at run time. The crossed intercept absorbs its mean and
# the fixed effect can still be driven by this one neighborhood. MixedLM cannot consume the
# diagnostic inverse-cluster-size weights; dependence is assessed by a leave-dominant-BG-out
# sensitivity refit and whole-BG bootstrap.
DOMINANT_BG = "040139412001"

# Columns the module needs to exist in the pixel table (verify-only contract).
REQUIRED_COLUMNS = (
    GROUP_COL, OVERPASS_COL, OUTCOME_COL, "vpd_z", "sm_z", "ndmi_z", "aridity",
    DAY_COL, HOUR_COL, SAMPLE_LABEL_COL, "pixel_row", "pixel_col",
    "n_tree_valid", "n_ref_valid",
)

# Bootstrap defaults.
DEFAULT_N_BOOT = 500
DEFAULT_SEED = 20240615
MIN_CLUSTERS_FOR_CONFIRMATORY_INFERENCE = 10  # Phoenix has 9 -> pilot-only by design
MIN_BOOTSTRAP_VALID_FRACTION = 0.80


# --- Pure logic: Mundlak / within-between decomposition (numpy/pandas only) -- #
def group_mean_center(df: "pd.DataFrame", col: str, group: str
                      ) -> tuple["pd.Series", "pd.Series"]:
    """Mundlak / correlated-within-between (CWC) decomposition of one column.

    Returns two Series aligned to ``df.index``:
      * ``<col>_bg_mean`` -- the group (block-group) mean broadcast to every member row;
      * ``<col>_within``  -- the value minus its group mean (group-centered).
    By construction ``_within + _bg_mean == <col>`` on finite rows, and ``_within`` sums to
    ~0 within each group. NaNs propagate: the group mean skips NaN (pandas default), so a
    NaN value yields a NaN ``_within`` (dropped pairwise at fit time).
    """
    grouped = df.groupby(group)[col]
    bg_mean = grouped.transform("mean")
    within = df[col] - bg_mean
    return bg_mean.rename(f"{col}_bg_mean"), within.rename(f"{col}_within")


def add_mundlak_terms(df: "pd.DataFrame", cols: Sequence[str] = MUNDLAK_COLS,
                      group: str = GROUP_COL) -> "pd.DataFrame":
    """Return a copy of ``df`` with ``<col>_bg_mean`` and ``<col>_within`` added for each col.

    This is the design-matrix builder for the mixed model: fixed effects sit on the
    ``_within`` (within-BG spatial + temporal) and ``_bg_mean`` (between-BG) terms.
    """
    out = df.copy()
    for col in cols:
        bg_mean, within = group_mean_center(out, col, group)
        out[f"{col}_bg_mean"] = bg_mean
        out[f"{col}_within"] = within
    return out


# --- Pure logic: sample mask, weighting, dominant-BG handling --------------- #
def primary_mask(df: "pd.DataFrame") -> "pd.Series":
    """Boolean keep-mask for the DAY-ONLY primary sample.

    Requires ``is_day == True`` (persisted by B4; not re-derived), the persisted
    ``sample_label == "primary"``, and the underlying tree count at or above the same
    pre-committed floor. The redundant count check prevents a malformed label from leaking
    a one-pixel row into the headline fit.
    """
    missing = [c for c in (DAY_COL, SAMPLE_LABEL_COL, "n_tree_valid") if c not in df.columns]
    if missing:
        raise ValueError(f"primary sample requires persisted columns: {missing}")
    return (df[DAY_COL].astype(bool)
            & df[SAMPLE_LABEL_COL].eq("primary")
            & (df["n_tree_valid"] >= config.PRIMARY_MIN_TREE_PIXELS))


def inverse_cluster_size_weights(groups: Sequence) -> np.ndarray:
    """Per-row weight = 1 / (number of rows in that row's block group).

    Down-weights the dominant BG (~171 px) so it does not swamp the eight thin BGs (1-6 px
    each) in any weighted summary. Returns an array aligned to ``groups``. (MixedLM weighting
    is not first-class -- see ``write_note``; the weight is carried as a column and used in
    descriptive summaries / a WLS fallback.)
    """
    g = pd.Series(np.asarray(groups, dtype=object))
    sizes = g.map(g.value_counts()).to_numpy(dtype="float64")
    return 1.0 / sizes


def leave_dominant_out(df: "pd.DataFrame", group: str = GROUP_COL,
                       dominant: str = DOMINANT_BG) -> "pd.DataFrame":
    """Return ``df`` with every row of the dominant block group dropped (sensitivity refit)."""
    return df.loc[df[group].astype(str) != str(dominant)].copy()


def dominant_group_summary(df: "pd.DataFrame", group: str = GROUP_COL,
                           dominant: str = DOMINANT_BG) -> dict:
    """Count the preidentified dominant BG in the exact frame supplied.

    The share is intentionally based on fitted pixel-overpass rows rather than a static
    classification count, because day filtering and complete-case exclusions can change the
    model sample. An empty frame returns a NaN share.
    """
    if group not in df.columns:
        raise ValueError(f"dominant-group summary requires column {group!r}")
    n_obs = int(len(df))
    n_dominant = int(df[group].astype(str).eq(str(dominant)).sum())
    share = float(n_dominant / n_obs) if n_obs else float("nan")
    return {
        "dominant_group": str(dominant),
        "dominant_n_obs": n_dominant,
        "dominant_share": share,
    }


# --- Pure logic: B3.3 BG cluster resampling of row indices ------------------ #
def cluster_resample_indices(groups: Sequence, rng: "np.random.Generator") -> np.ndarray:
    """Resample WHOLE block groups (B3.3): return the concatenated member row indices.

    Draws ``n_unique`` groups WITH replacement (``rng.choice(unique_groups, size=n_unique,
    replace=True)``) and concatenates every member row index of each drawn group. A group
    can therefore appear 0, 1, or 2+ times; a partial group is NEVER returned. The resampled
    size equals the summed sizes of the drawn groups (it varies run to run). This is the
    clustered analogue of an i.i.d. row bootstrap. Its width is data-dependent and is reported
    explicitly rather than assumed to exceed the model-SE interval. numpy-only (no statsmodels needed).
    """
    groups = np.asarray(groups)
    uniq = np.unique(groups)
    if uniq.size == 0:
        return np.zeros(0, dtype=np.intp)
    idx_by_group = {g: np.where(groups == g)[0] for g in uniq}
    drawn = rng.choice(uniq, size=uniq.size, replace=True)
    parts = [idx_by_group[g] for g in drawn]
    return np.concatenate(parts).astype(np.intp)


def cluster_resample_frame(df: "pd.DataFrame", rng: "np.random.Generator",
                           group: str = GROUP_COL) -> "pd.DataFrame":
    """Resample whole clusters and give repeated draws independent bootstrap labels.

    A conventional cluster bootstrap treats two draws of the same original block group as
    two bootstrap clusters. Reusing the original label would collapse those copies into one
    random-effect level inside ``MixedLM``. This helper therefore concatenates every complete
    group draw and relabels it as ``<source>__boot_<draw>`` while retaining the source in the
    private ``_bootstrap_source_group`` column for diagnostics/tests.
    """
    uniq = np.asarray(pd.unique(df[group]))
    if uniq.size == 0:
        return df.iloc[0:0].copy()
    drawn = rng.choice(uniq, size=uniq.size, replace=True)
    parts: list[pd.DataFrame] = []
    for draw_id, source in enumerate(drawn):
        part = df.loc[df[group] == source].copy()
        part["_bootstrap_source_group"] = source
        part[group] = f"{source}__boot_{draw_id}"
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


# --- statsmodels-backed model fit (guarded) --------------------------------- #
def _require_statsmodels(what: str) -> None:
    if not HAVE_STATSMODELS:
        raise RuntimeError(
            f"{what} requires statsmodels, which is not installed in this environment. "
            "Install the pinned project environment before running B3.2/B3.3 "
            "to run the mixed model / cluster bootstrap. The pure helpers "
            "(group_mean_center, add_mundlak_terms, cluster_resample_indices, "
            "cluster_resample_frame, "
            "inverse_cluster_size_weights, leave_dominant_out) work without it.")


def _prepare_frame(df: "pd.DataFrame", *, drop_dominant: bool = False,
                   day_only: bool = True) -> "pd.DataFrame":
    """Filter -> add Mundlak terms -> drop dominant (optional) -> drop NaN design rows.

    Shared preprocessing for ``fit_mixed`` and ``bootstrap_mixed_ci`` so both fit exactly the
    same design. Adds the inverse-cluster-size weight column.
    """
    if day_only:
        d = df.loc[primary_mask(df)].copy()
    else:
        # Day+night pooled sensitivity: skip only the is_day filter; the primary
        # tree-pixel floor remains mandatory.
        mask = (df[SAMPLE_LABEL_COL].eq("primary")
                & (df["n_tree_valid"] >= config.PRIMARY_MIN_TREE_PIXELS))
        d = df.loc[mask].copy()
    d = add_mundlak_terms(d, cols=MUNDLAK_COLS, group=GROUP_COL)
    if drop_dominant:
        d = leave_dominant_out(d)
    d = d.dropna(subset=[OUTCOME_COL, *MUNDLAK_COLS])
    # Recheck the tree-pixel floor after predictor NaNs are removed. A BG x overpass can
    # satisfy n_tree_valid >= 3 upstream yet leave only 1-2 complete VPD+SM model rows.
    complete_count = d.groupby([GROUP_COL, OVERPASS_COL])[OUTCOME_COL].transform("size")
    d["n_predictor_complete"] = complete_count.astype("int64")
    below = complete_count < config.PRIMARY_MIN_TREE_PIXELS
    n_groups_excluded = int(
        d.loc[below, [GROUP_COL, OVERPASS_COL]].drop_duplicates().shape[0])
    n_rows_excluded = int(below.sum())
    d = d.loc[~below].drop(columns=FIXED_EFFECT_COLS, errors="ignore")
    # Recompute the CWC terms on the exact retained model sample so excluded low-complete-
    # count groups cannot influence a BG mean used by retained rows.
    d = add_mundlak_terms(d, cols=MUNDLAK_COLS, group=GROUP_COL).reset_index(drop=True)
    d["inv_cluster_weight"] = inverse_cluster_size_weights(d[GROUP_COL].to_numpy())
    d.attrs["n_complete_case_groups_excluded"] = n_groups_excluded
    d.attrs["n_complete_case_rows_excluded"] = n_rows_excluded
    return d


def _validate_prepared_frame(d: "pd.DataFrame") -> dict:
    """Fail before fitting when the mixed-model design is structurally unidentified."""
    n_obs = int(len(d))
    n_groups = int(d[GROUP_COL].nunique()) if n_obs else 0
    n_overpass = int(d[OVERPASS_COL].nunique()) if n_obs else 0
    n_terms = 1 + len(FIXED_EFFECT_COLS)
    if n_obs < n_terms + 1:
        raise RuntimeError(f"mixed model needs more than {n_terms} complete rows; found {n_obs}.")
    if n_groups < 2:
        raise RuntimeError(f"mixed model needs >=2 block groups; found {n_groups}.")
    if n_overpass < 2:
        raise RuntimeError(f"mixed model needs >=2 overpasses; found {n_overpass}.")
    design = np.column_stack([
        np.ones(n_obs, dtype="float64"),
        *[d[col].to_numpy(dtype="float64") for col in FIXED_EFFECT_COLS],
    ])
    if not np.isfinite(design).all():
        raise RuntimeError("mixed-model fixed-effect design contains non-finite values.")
    rank = int(np.linalg.matrix_rank(design))
    if rank < n_terms:
        raise RuntimeError(
            f"mixed-model fixed-effect design is rank deficient ({rank} < {n_terms}).")
    return {"design_rank": rank, "design_columns": n_terms,
            "n_groups": n_groups, "n_overpass": n_overpass}


def _fit_core(d: "pd.DataFrame", *, reml: bool = True):
    """Fit the crossed random-intercept MixedLM on an already-prepared frame.

    Uses the standard statsmodels crossed-effects construction: one constant top-level group
    plus independent variance components for ``C(neighborhood_id)`` and
    ``C(overpass_key)``. This represents ``(1|block_group) + (1|overpass)`` directly;
    putting overpass in ``vc_formula`` while grouping by block group would incorrectly nest
    overpasses inside block groups.
    """
    _validate_prepared_frame(d)
    d = d.copy()
    d["_all_rows"] = "all"
    vc_formula = {
        "block_group": f"0 + C({GROUP_COL})",
        "overpass": f"0 + C({OVERPASS_COL})",
    }
    formula = f"{OUTCOME_COL} ~ " + " + ".join(FIXED_EFFECT_COLS)
    model = smf.mixedlm(formula, d, groups=d["_all_rows"],
                        re_formula="0", vc_formula=vc_formula)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fitted = model.fit(reml=reml)
    fitted._phoenix_fit_warnings = [
        {"category": item.category.__name__, "message": str(item.message)} for item in caught]
    return fitted


_SEVERE_WARNING_MARKERS = (
    "singular", "boundary", "hessian", "not positive definite", "failed to converge",
    "gradient optimization failed", "invalid value encountered",
)


def _mixed_result_payload(mdf, key_coef: str = KEY_COEF) -> dict:
    """Extract estimates and reject convergence/boundary/singular/non-finite fits."""
    warning_records = list(getattr(mdf, "_phoenix_fit_warnings", []))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        params = {k: float(v) for k, v in mdf.params.items()}
        bse = {k: float(v) for k, v in mdf.bse.items()}
    warning_records.extend(
        {"category": item.category.__name__, "message": str(item.message)} for item in caught)
    severe = [
        item for item in warning_records
        if item["category"] == "ConvergenceWarning"
        or any(marker in item["message"].lower() for marker in _SEVERE_WARNING_MARKERS)
    ]
    estimate = float(params.get(key_coef, float("nan")))
    se = float(bse.get(key_coef, float("nan")))
    converged = bool(getattr(mdf, "converged", False))
    usable = bool(converged and np.isfinite(estimate) and np.isfinite(se) and se > 0
                  and not severe)
    return {"params": params, "bse": bse, "key_estimate": estimate, "key_se": se,
            "converged": converged, "fit_usable": usable,
            "fit_warnings": warning_records, "severe_fit_warnings": severe}


def _variance_components(mdf) -> tuple[float, float, float]:
    """Extract (var_block_group, var_overpass, var_residual) from a MixedLM result, robustly."""
    var_bg = float("nan")
    var_op = float("nan")
    var_resid = float("nan")
    try:
        vcomp = np.asarray(mdf.vcomp, dtype="float64")
        names = list(getattr(mdf.model.exog_vc, "names", []))
        mapping = {name: float(value) for name, value in zip(names, vcomp)}
        var_bg = mapping.get("block_group", float("nan"))
        var_op = mapping.get("overpass", float("nan"))
    except Exception:  # pragma: no cover - defensive
        pass
    try:
        var_resid = float(mdf.scale)
    except Exception:  # pragma: no cover - defensive
        pass
    return var_bg, var_op, var_resid


def fit_mixed(df: "pd.DataFrame", *, drop_dominant: bool = False, day_only: bool = True,
              reml: bool = True) -> dict:
    """Fit the B3.2 crossed random-intercept mixed model; return a small result dict.

    Filters to the primary mask (``is_day`` plus persisted ``sample_label == "primary"``),
    adds the Mundlak within/between terms, and fits crossed random intercepts for block group
    and overpass. Reports the fixed-effect coefficients (+ model SEs) and BOTH variance
    components plus the residual. Raises ``RuntimeError`` if statsmodels is absent.
    """
    _require_statsmodels("fit_mixed")
    d = _prepare_frame(df, drop_dominant=drop_dominant, day_only=day_only)
    n_obs = int(len(d))
    n_groups = int(d[GROUP_COL].nunique())
    dominance = dominant_group_summary(d)
    design_diag = _validate_prepared_frame(d)
    mdf = _fit_core(d, reml=reml)
    payload = _mixed_result_payload(mdf, KEY_COEF)
    params = payload["params"]
    bse = payload["bse"]
    var_bg, var_op, var_resid = _variance_components(mdf)
    try:
        summary_text = mdf.summary().as_text()
    except Exception:  # pragma: no cover - defensive
        summary_text = ""
    result = {
        "label": ("day+night(pooled)" if not day_only
                  else ("day-only,drop-dominant" if drop_dominant else "day-only(primary)")),
        "day_only": bool(day_only),
        "drop_dominant": bool(drop_dominant),
        "converged": payload["converged"],
        "fit_usable": payload["fit_usable"],
        "fit_warnings": payload["fit_warnings"],
        "severe_fit_warnings": payload["severe_fit_warnings"],
        "n_obs": n_obs,
        "n_groups": n_groups,
        "n_overpass": int(d[OVERPASS_COL].nunique()),
        **dominance,
        "params": params,
        "bse": bse,
        "key_coef": KEY_COEF,
        "key_estimate": payload["key_estimate"],
        "key_se": payload["key_se"],
        "var_block_group": var_bg,
        "var_overpass": var_op,
        "var_residual": var_resid,
        "mean_cooling": float(d[OUTCOME_COL].mean()),
        "design_rank": design_diag["design_rank"],
        "design_columns": design_diag["design_columns"],
        "n_complete_case_groups_excluded": int(
            d.attrs.get("n_complete_case_groups_excluded", 0)),
        "n_complete_case_rows_excluded": int(
            d.attrs.get("n_complete_case_rows_excluded", 0)),
        "summary": summary_text,
    }
    return result


def model_se_halfwidth(key_se: float, ci: float = 0.95) -> float:
    """Naive (model-SE) half-width of a coefficient CI: z_{1-a/2} * SE. Baseline for B3.3."""
    from scipy.stats import norm
    z = float(norm.ppf(1.0 - (1.0 - ci) / 2.0))
    return z * float(key_se)


# --- B3.3: BG-cluster bootstrap of the mixed-model CI ----------------------- #
def bootstrap_mixed_ci(df: "pd.DataFrame", *, n_boot: int = DEFAULT_N_BOOT,
                       seed: int = DEFAULT_SEED, ci: float = 0.95,
                       drop_dominant: bool = False, key_coef: str = KEY_COEF) -> dict:
    """BG-cluster bootstrap (B3.3) of the mixed-model CI for the key coefficient + mean dT_cool.

    Refits the model on each WHOLE-block-group resample (``cluster_resample_indices``) and
    returns percentile CIs for ``key_coef`` (default ``vpd_z_within``) and for mean
    ``cooling_advantage_px``. At <=9 clusters its width is reported alongside the naive model
    interval; no direction is assumed. Failed, non-converged, boundary, singular, and
    non-finite-SE refits are skipped and
    counted in ``n_valid``. Raises ``RuntimeError`` if statsmodels is absent (the
    ``cluster_resample_indices`` helper itself needs no statsmodels).
    """
    _require_statsmodels("bootstrap_mixed_ci")
    d = _prepare_frame(df, drop_dominant=drop_dominant, day_only=True)
    groups = d[GROUP_COL].to_numpy()
    n_clusters = int(np.unique(groups).size)
    rng = np.random.default_rng(seed)

    empty_ci = {"ci_low": float("nan"), "ci_high": float("nan"),
                "half_width": float("nan"), "median": float("nan"),
                "mean": float("nan"), "n_valid": 0, "n_unique": 0}
    if n_clusters < 2:
        return {
            "key_coef": key_coef, "n_boot": int(n_boot), "n_clusters": n_clusters,
            "ci_level": float(ci), "seed": int(seed),
            "drop_dominant": bool(drop_dominant), "coef": empty_ci.copy(),
            "mean_cooling": empty_ci.copy(), "valid_fraction": 0.0,
            "n_rejected_fit_quality": 0, "n_rejected_preflight_or_error": 0,
            "status": "not_identifiable_fewer_than_two_clusters",
        }

    coef_ests: list[float] = []
    mean_ests: list[float] = []
    n_rejected_fit_quality = 0
    n_rejected_preflight_or_error = 0
    for _ in range(int(n_boot)):
        dboot = cluster_resample_frame(d, rng, group=GROUP_COL)
        try:
            mdf = _fit_core(dboot)
            payload = _mixed_result_payload(mdf, key_coef)
            coef = payload["key_estimate"] if payload["fit_usable"] else float("nan")
            if not payload["fit_usable"]:
                n_rejected_fit_quality += 1
        except Exception:
            coef = float("nan")
            n_rejected_preflight_or_error += 1
        if np.isfinite(coef):
            coef_ests.append(coef)
            mean_ests.append(float(dboot[OUTCOME_COL].mean()))

    def _percentile_ci(vals: list[float]) -> dict:
        arr = np.asarray(vals, dtype="float64")
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return {"ci_low": float("nan"), "ci_high": float("nan"),
                    "half_width": float("nan"), "median": float("nan"),
                    "mean": float("nan"), "n_valid": 0, "n_unique": 0}
        alpha = (1.0 - ci) / 2.0
        lo = float(np.quantile(arr, alpha))
        hi = float(np.quantile(arr, 1.0 - alpha))
        return {"ci_low": lo, "ci_high": hi, "half_width": (hi - lo) / 2.0,
                "median": float(np.median(arr)), "mean": float(np.mean(arr)),
                "n_valid": int(arr.size), "n_unique": int(np.unique(arr).size)}

    diagnostic_coef_ci = _percentile_ci(coef_ests)
    diagnostic_mean_ci = _percentile_ci(mean_ests)
    valid_fraction = (diagnostic_coef_ci["n_valid"] / int(n_boot)
                      if int(n_boot) > 0 else 0.0)
    status = ("ok" if valid_fraction >= MIN_BOOTSTRAP_VALID_FRACTION
              else "not_identifiable_too_few_clean_bootstrap_fits")
    # A percentile interval built from a small, selected subset of clean refits can look
    # spuriously precise (even zero-width). Suppress it from the report unless the predeclared
    # clean-fit fraction passes; retain the raw diagnostic summary for auditing.
    if status == "ok":
        coef_ci = diagnostic_coef_ci
        mean_ci = diagnostic_mean_ci
    else:
        coef_ci = {**diagnostic_coef_ci, "ci_low": float("nan"),
                   "ci_high": float("nan"), "half_width": float("nan"),
                   "median": float("nan"), "mean": float("nan")}
        mean_ci = {**diagnostic_mean_ci, "ci_low": float("nan"),
                   "ci_high": float("nan"), "half_width": float("nan"),
                   "median": float("nan"), "mean": float("nan")}
    return {
        "key_coef": key_coef,
        "n_boot": int(n_boot),
        "n_clusters": n_clusters,
        "ci_level": float(ci),
        "seed": int(seed),
        "drop_dominant": bool(drop_dominant),
        "coef": coef_ci,
        "mean_cooling": mean_ci,
        "diagnostic_coef": diagnostic_coef_ci,
        "diagnostic_mean_cooling": diagnostic_mean_ci,
        "valid_fraction": float(valid_fraction),
        "status": status,
        "n_rejected_fit_quality": n_rejected_fit_quality,
        "n_rejected_preflight_or_error": n_rejected_preflight_or_error,
    }


# --- Deliverable note ------------------------------------------------------- #
def _fmt(x: float, nd: int = 4) -> str:
    try:
        if x is None or (isinstance(x, float) and not np.isfinite(x)):
            return "n/a"
        return f"{float(x):.{nd}f}"
    except Exception:
        return "n/a"


def _dominant_bg_caveat(primary: dict | None) -> str:
    """Format the caveat with the observed share of the exact fitted primary sample."""
    generic = (
        f"**Dominant-BG caveat.** BG `{DOMINANT_BG}` is the preidentified dominant "
        "block group. Its exact share of the fitted day-primary sample is calculated at "
        "run time. MixedLM does not apply the diagnostic inverse-cluster-size weights; "
        "dependence is assessed with a leave-dominant-BG-out sensitivity refit and whole-BG "
        "bootstrap."
    )
    if primary is None:
        return generic
    try:
        n_dominant = int(primary["dominant_n_obs"])
        n_obs = int(primary["n_obs"])
        share = float(primary["dominant_share"])
    except (KeyError, TypeError, ValueError):
        return generic
    if n_obs <= 0 or n_dominant < 0 or n_dominant > n_obs or not np.isfinite(share):
        return generic
    return (
        f"**Dominant-BG caveat.** BG `{DOMINANT_BG}` contributes "
        f"{n_dominant:,} of {n_obs:,} fitted day-primary pixel-overpass rows "
        f"({share:.1%}), so the fixed effect can still be dominated by that neighborhood. "
        "MixedLM does not apply the diagnostic inverse-cluster-size weights; dependence is "
        "assessed with a leave-dominant-BG-out sensitivity refit and whole-BG bootstrap."
    )


def write_note(result: dict | None, path: "Path | str", *,
               have_statsmodels: bool = HAVE_STATSMODELS) -> Path:
    """Emit ``docs/section14b_mixed_effects_note.md``.

    When a fitted ``result`` is supplied (statsmodels present), the note carries the fixed-
    effect coefficients +/- their BG-cluster CI, the variance components, the dominant-BG
    in/out sensitivity, and the day vs day+night contrast. When statsmodels is ABSENT (or
    ``result is None``) the note still writes -- stating the model could not be fit here and
    exactly what it WILL report once the dependency is restored. The CLI returns a non-zero
    status in that case so the blocker-resolution step cannot pass silently.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    primary = result.get("primary") if result is not None else None
    dropped = result.get("drop_dominant") if result is not None else None
    pooled = result.get("pooled") if result is not None else None
    boot = result.get("bootstrap") if result is not None else None
    lines: list[str] = []
    lines.append("# Section 14b - Pixel-level mixed-effects model (B3.2) + BG cluster bootstrap (B3.3)")
    lines.append("")
    lines.append("Unit of analysis: the tree PIXEL (`master_pixel_table.parquet`), one row per "
                 "finite tree pixel carrying its BG x overpass reference-mean LST.")
    lines.append("")
    lines.append("- Outcome: `cooling_advantage_px` (dT_cool = mean reference LST - tree-pixel LST).")
    lines.append("- Primary sample: `is_day == True` (persisted by B4; READ, not re-derived) "
                 f"and `sample_label == \"primary\"` (`n_tree_valid >= "
                 f"{config.PRIMARY_MIN_TREE_PIXELS}`). Low-count rows are sensitivity-only.")
    lines.append("- Design: Mundlak / correlated-within-between decomposition of `vpd_z`, `sm_z` "
                 "into `_within` (within-BG) and `_bg_mean` (between-BG). Because the rows are "
                 "repeated pixels, `_within` combines within-BG spatial and temporal variation; "
                 "it is not labelled a purely temporal effect.")
    lines.append("- Random effects: crossed random intercepts `(1|block_group) + (1|overpass)` "
                 "via one constant top-level group and separate variance-component formulas "
                 "for `C(neighborhood_id)` and `C(overpass_key)`.")
    lines.append("- Uncertainty: BG-cluster bootstrap (whole block groups, <=9 clusters) of the "
                 "CI for `vpd_z_within` and mean `cooling_advantage_px` (B3.3). It is "
                 "reported only when the clean-fit gate passes; otherwise the CI is suppressed "
                 "and the failure counts are reported alongside the naive model SE.")
    lines.append("")
    lines.append(_dominant_bg_caveat(primary))
    lines.append("")
    lines.append("**Crossed-RE fallback.** With ~9 BGs (one dominant) the crossed variance-"
                 "component fit can hit boundary variance. Documented fallbacks: BG fixed effects "
                 "+ overpass random effect, or GEE with BG clusters. The wild-cluster (Rademacher) "
                 "bootstrap is the small-cluster alternative to the percentile CI.")
    lines.append("")

    if (not have_statsmodels) or result is None:
        lines.append("## Status: NOT FIT HERE (dependency missing)")
        lines.append("")
        lines.append("`statsmodels` is unavailable even though it is pinned in the project "
                     "environment, so the mixed model and its cluster bootstrap were not run. "
                     "This is a hard pipeline failure, not a successful no-op. Restore the "
                     "project environment "
                     "and re-run `python src/section14b_mixed_effects.py`.")
        lines.append("")
        lines.append("### What this note WILL report once statsmodels is available")
        lines.append("")
        lines.append("- Fixed-effect coefficients for `vpd_z_within`, `sm_z_within`, "
                     "`vpd_z_bg_mean`, `sm_z_bg_mean` (estimate +/- BG-cluster CI).")
        lines.append("- Variance components: block-group intercept, overpass intercept, residual.")
        lines.append("- Dominant-BG in/out sensitivity (full sample vs leave-`040139412001`-out).")
        lines.append("- Day-only (primary) vs day+night (pooled sensitivity) contrast.")
        lines.append("- Note: the pure helpers (centering, within-between decomposition, cluster "
                     "resampling, inverse-cluster-size weighting) are unit-tested and pass without "
                     "statsmodels.")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log.info("Wrote deps-missing note -> %s", path)
        return path

    status = result.get("interpretation_status", "not_identifiable_pilot")
    reasons = result.get("status_reasons", [])
    lines.append(f"## Interpretation status: `{status}`")
    lines.append("")
    if reasons:
        for reason in reasons:
            lines.append(f"- {reason}")
    lines.append("")

    lines.append("## Fixed effects (day-only primary) and BG-cluster diagnostics")
    lines.append("")
    if primary is not None:
        lines.append(f"Fit on {primary['n_obs']} tree pixels across {primary['n_groups']} block "
                     f"group(s) and {primary['n_overpass']} overpass(es); "
                     f"converged={primary['converged']}; clean-fit={primary.get('fit_usable', False)}.")
        lines.append(
            f"After VPD/soil-moisture complete-case filtering, "
            f"{primary.get('n_complete_case_groups_excluded', 0)} BG × overpass group(s) "
            f"({primary.get('n_complete_case_rows_excluded', 0)} row(s)) fell below the "
            f"{config.PRIMARY_MIN_TREE_PIXELS}-pixel floor and were excluded.")
        if primary.get("severe_fit_warnings"):
            lines.append(
                f"The primary fit emitted {len(primary['severe_fit_warnings'])} severe "
                "boundary/singularity/convergence warning(s); estimates are diagnostic only.")
        lines.append("")
        lines.append("| term | estimate | model SE |")
        lines.append("|------|----------|----------|")
        for term in FIXED_EFFECT_COLS + ["Intercept"]:
            est = primary["params"].get(term)
            se = primary["bse"].get(term)
            if est is None:
                continue
            lines.append(f"| `{term}` | {_fmt(est)} | {_fmt(se)} |")
        lines.append("")
        if boot is not None:
            c = boot["coef"]
            m = boot["mean_cooling"]
            lines.append(f"BG-cluster bootstrap ({boot['n_boot']} resamples over "
                         f"{boot['n_clusters']} clusters, {int(boot['ci_level']*100)}% CI):")
            lines.append("")
            if boot.get("status") == "ok":
                lines.append(f"- `{boot['key_coef']}` = {_fmt(primary['key_estimate'])} "
                             f"[{_fmt(c['ci_low'])}, {_fmt(c['ci_high'])}] "
                             f"(cluster half-width {_fmt(c['half_width'])}; "
                             f"naive model-SE half-width "
                             f"{_fmt(model_se_halfwidth(primary['key_se']))}).")
            else:
                diag = boot.get("diagnostic_coef", {})
                lines.append(
                    f"- `{boot['key_coef']}` = {_fmt(primary['key_estimate'])}; BG-bootstrap "
                    "CI **not reported** because the clean-fit fraction failed the predeclared "
                    f"{MIN_BOOTSTRAP_VALID_FRACTION:.0%} minimum. The "
                    f"{diag.get('n_valid', 0)} surviving refits contained "
                    f"{diag.get('n_unique', 0)} unique coefficient value(s), so their raw "
                    "percentiles must not be read as precise uncertainty.")
            lines.append(f"- bootstrap status = `{boot.get('status', 'unknown')}`; "
                         f"valid clean-fit fraction = "
                         f"{boot.get('valid_fraction', float('nan')):.1%}.")
            lines.append(
                f"- rejected bootstrap fits: {boot.get('n_rejected_fit_quality', 0)} for "
                f"boundary/singular/non-finite fit quality and "
                f"{boot.get('n_rejected_preflight_or_error', 0)} for rank/level preflight "
                "failure or another fit error.")
            if boot.get("status") == "ok":
                lines.append(f"- mean `cooling_advantage_px` = "
                             f"{_fmt(primary['mean_cooling'], 3)} K "
                             f"[{_fmt(m['ci_low'], 3)}, {_fmt(m['ci_high'], 3)}] K "
                             f"(cluster half-width {_fmt(m['half_width'], 3)} K).")
            else:
                lines.append(f"- mean `cooling_advantage_px` = "
                             f"{_fmt(primary['mean_cooling'], 3)} K; cluster interval not "
                             "reported for the same fit-quality reason.")
            lines.append("")

    lines.append("## Variance components")
    lines.append("")
    if primary is not None:
        lines.append("| component | variance (day-only primary) |")
        lines.append("|-----------|------------------------------|")
        lines.append(f"| block group `(1|neighborhood_id)` | {_fmt(primary['var_block_group'])} |")
        lines.append(f"| overpass `(1|overpass_key)` | {_fmt(primary['var_overpass'])} |")
        lines.append(f"| residual | {_fmt(primary['var_residual'])} |")
        lines.append("")

    lines.append("## Dominant-BG in/out sensitivity")
    lines.append("")
    lines.append("| sample | n pixels | n BGs | vpd_z_within | sm_z_within |")
    lines.append("|--------|----------|-------|--------------|----------------|")
    for tag, r in (("full (day-only)", primary), ("leave-040139412001-out", dropped)):
        if r is None:
            continue
        lines.append(f"| {tag} | {r['n_obs']} | {r['n_groups']} | "
                     f"{_fmt(r['params'].get('vpd_z_within'))} | "
                     f"{_fmt(r['params'].get('sm_z_within'))} |")
    lines.append("")
    lines.append("The fixed effect effectively generalizes to the single dominant neighborhood; "
                 "the leave-out row shows how much the coefficient depends on it.")
    lines.append("")

    lines.append("## Day vs day+night")
    lines.append("")
    lines.append("| sample | n pixels | mean dT_cool (K) | vpd_z_within |")
    lines.append("|--------|----------|-------------------|--------------|")
    for tag, r in (("day-only (primary)", primary), ("day+night (pooled sensitivity)", pooled)):
        if r is None:
            continue
        lines.append(f"| {tag} | {r['n_obs']} | {_fmt(r['mean_cooling'], 3)} | "
                     f"{_fmt(r['params'].get('vpd_z_within'))} |")
    lines.append("")
    lines.append("Day is the primary analysis; the pooled day+night row is a labelled "
                 "sensitivity only.")
    lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("Wrote mixed-effects note -> %s", path)
    return path


# --- Verification ----------------------------------------------------------- #
def verify_pixel_table(path: "Path") -> bool:
    """Check the pixel parquet exists and carries every column the model relies on."""
    path = Path(path)
    if not path.exists():
        log.error("pixel table not found: %s", path)
        return False
    df = pd.read_parquet(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        log.error("pixel table %s missing required columns: %s", path.name, missing)
        return False
    log.info("VERIFY ok: %s has %d rows and all %d required columns; %d block group(s), "
             "%d day rows.", path.name, len(df), len(REQUIRED_COLUMNS),
             int(df[GROUP_COL].nunique()), int(df[DAY_COL].astype(bool).sum()))
    return True


# --- Orchestration / CLI ---------------------------------------------------- #
def run(*, n_boot: int = DEFAULT_N_BOOT, seed: int = DEFAULT_SEED) -> dict:
    """Fit the model (+ sensitivities + bootstrap) and write the note. Requires statsmodels."""
    _require_statsmodels("run")
    pixel_path = config.PROCESSED_DIR / PIXEL_PARQUET
    df = pd.read_parquet(pixel_path)
    log.info("Loaded pixel table: %d rows, %d block group(s), %d day rows.",
             len(df), int(df[GROUP_COL].nunique()), int(df[DAY_COL].astype(bool).sum()))

    primary = fit_mixed(df, day_only=True, drop_dominant=False)
    log.info("Primary (day-only) fit: %s = %s (+/- SE %s); n=%d, BGs=%d.",
             KEY_COEF, _fmt(primary["key_estimate"]), _fmt(primary["key_se"]),
             primary["n_obs"], primary["n_groups"])

    try:
        dropped = fit_mixed(df, day_only=True, drop_dominant=True)
    except Exception as exc:  # boundary variance / too-few groups after drop
        log.warning("leave-dominant-out refit failed: %s", exc)
        dropped = None

    try:
        pooled = fit_mixed(df, day_only=False, drop_dominant=False)
    except Exception as exc:
        log.warning("day+night pooled refit failed: %s", exc)
        pooled = None

    boot = bootstrap_mixed_ci(df, n_boot=n_boot, seed=seed, drop_dominant=False)
    log.info("BG-cluster bootstrap: %s CI [%s, %s] (half-width %s vs naive %s).",
             KEY_COEF, _fmt(boot["coef"]["ci_low"]), _fmt(boot["coef"]["ci_high"]),
             _fmt(boot["coef"]["half_width"]),
             _fmt(model_se_halfwidth(primary["key_se"])))

    status_reasons: list[str] = []
    if not primary.get("fit_usable", False):
        status_reasons.append(
            "The primary mixed model did not yield a clean converged fit with finite SEs and "
            "no boundary/singularity/Hessian warnings.")
    if primary.get("n_complete_case_groups_excluded", 0):
        status_reasons.append(
            f"{primary['n_complete_case_groups_excluded']} BG × overpass group(s) fell below "
            f"the complete-case {config.PRIMARY_MIN_TREE_PIXELS}-pixel floor after predictor "
            "NaNs were removed.")
    if primary["n_groups"] < MIN_CLUSTERS_FOR_CONFIRMATORY_INFERENCE:
        status_reasons.append(
            f"Only {primary['n_groups']} block-group clusters are available; the pre-committed "
            f"confirmatory minimum is {MIN_CLUSTERS_FOR_CONFIRMATORY_INFERENCE}.")
    if boot.get("status") != "ok":
        status_reasons.append(
            f"Cluster bootstrap status is {boot.get('status')} "
            f"({boot.get('valid_fraction', 0.0):.1%} clean fits).")
    interpretation_status = ("exploratory_model_only_threshold_not_identifiable"
                             if status_reasons else "confirmatory_inference_ready")
    result = {"primary": primary, "drop_dominant": dropped, "pooled": pooled,
              "bootstrap": boot, "interpretation_status": interpretation_status,
              "status_reasons": status_reasons}
    write_note(result, _REPO_ROOT / NOTE_PATH, have_statsmodels=True)
    return result


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 14b - pixel-level mixed-effects model (B3.2) + BG cluster "
                    "bootstrap of the model CI (B3.3). Reads master_pixel_table.parquet.")
    p.add_argument("--verify-only", action="store_true",
                   help="check the pixel parquet + required columns exist, then exit.")
    p.add_argument("--n-boot", type=int, default=DEFAULT_N_BOOT,
                   help=f"BG-cluster bootstrap resamples (default {DEFAULT_N_BOOT}).")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED,
                   help=f"bootstrap RNG seed (default {DEFAULT_SEED}).")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")

    config.ensure_dirs()
    pixel_path = config.PROCESSED_DIR / PIXEL_PARQUET

    if args.verify_only:
        ok = verify_pixel_table(pixel_path)
        return 0 if ok else 1

    # The pixel table is produced upstream (B3.1 / Section 13). Missing it is a hard error.
    if not pixel_path.exists():
        log.error("pixel table not found: %s -- run Section 13 (B3.1) first.", pixel_path)
        return 2

    if not HAVE_STATSMODELS:
        log.error("statsmodels is unavailable -> writing a diagnostic note and failing the "
                  "B3.2/B3.3 pipeline step. Install the pinned project environment.")
        write_note(None, _REPO_ROOT / NOTE_PATH, have_statsmodels=False)
        return 3

    run(n_boot=args.n_boot, seed=args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
