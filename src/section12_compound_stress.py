#!/usr/bin/env python3
"""Section 12 - Compute the Compound Stress Index (CSI) (steps 62-66).

Implements the whole of Section 12 for the Phoenix pilot from this one module, so
it re-runs end to end from saved code (protocol standing rule: "every figure and
every number must be reproducible from the saved code; nothing produced by hand").

Objective (protocol Section 12, steps 62-66)
--------------------------------------------
Combine the standardized DEMAND and SUPPLY anomalies from Section 11 into a single
number -- the Compound Stress Index (CSI) -- that measures how severe the joint
heat-drought stress is for each pixel at each overpass:

  62. DEMAND stress = the POSITIVE PART of the VPD z-score:  demand = max(vpd_z, 0).
      Only ABOVE-normal VPD is stressful, so below-normal VPD contributes nothing.
  63. SUPPLY stress = the POSITIVE PART of the NEGATED water-supply z-score:
      supply = max(-ndmi_z, 0). LOW water is stressful, so a below-normal NDMI (a
      NEGATIVE z-score) becomes a POSITIVE stress contribution.
  64. Baseline CSI (EQUAL weights):  CSI = 0.5*demand + 0.5*supply
      (weights WEIGHT_DEMAND / WEIGHT_SUPPLY in config.py).
  65. Record the CSI for every pixel and overpass. CSI ~ 0 = near normal; a LARGE
      CSI = high atmospheric demand AND low water supply together -- a compound
      extreme. CSI >= 0 everywhere (both parts are non-negative).
  66. Plan two SENSITIVITY tests for LATER: unequal weights, and weights derived
      from the joint statistical dependence (a copula) of the two stressors. The
      baseline equal-weight version is sufficient to proceed now -- the hooks for
      both are present here but are NOT run (see "SENSITIVITY HOOKS" below).

COMMON PITFALL (guarded here): if the SUPPLY stress is built from RAW NDMI instead
of its z-score, it is NOT on the same scale as the demand stress, and the
equal-weight combination is dominated by whichever variable has the larger numeric
range. BOTH inputs MUST be z-scores from Section 11. This module reads ONLY the
`vpd_z` and `ndmi_z` z-score variables from `section11_zscores_70m.zarr` (never the
raw VPD/NDMI in the Section 9 cube); the build asserts the inputs are the z-scores,
and the unit tests prove the supply stress is built from the z-score, not raw NDMI.

================================================================================
KEY DESIGN DECISIONS (documented prominently; see also data/processed/README.md
and src/README.md Section 12)
================================================================================
(A) DEMAND is TIME-VARYING; SUPPLY is STATIC IN TIME.
    --------------------------------------------------------------------------
    `vpd_z` from Section 11 VARIES per (overpass, pixel) -- a true temporal
    day-of-year-at-overpass-hour leave-one-year-out climatology -- so the demand
    stress max(vpd_z, 0) varies in time. `ndmi_z`, however, is a SPATIAL
    standardized anomaly built from the SINGLE 2023 NDMI composite (Section 11
    decision B): there is no NDMI time series, so a temporal climatology is
    impossible and `ndmi_z` is CONSTANT across the 66 overpasses (it varies by
    pixel, not by overpass). Hence the supply stress max(-ndmi_z, 0) is ALSO
    constant across overpasses. This is carried forward honestly from Section 11.

(B) CONSEQUENCE for the temporal ranking (stated plainly):
    --------------------------------------------------------------------------
    Because the supply term is the SAME for every overpass, the TEMPORAL ordering
    of the SPATIAL-MEAN CSI across overpasses is driven ENTIRELY by the demand
    term: rank(spatial-mean CSI) == rank(spatial-mean demand) == rank of the VPD
    z+ demand. So "the highest-CSI dates == the highest VPD-demand dates". The
    deliverable confirms those highest-CSI dates coincide with the known compound
    extremes of summer 2023 (July 2023 was Phoenix's hottest month on record; a
    ~31-day >=110 F streak from ~2023-06-30 to ~2023-07-30). Because VPD-z is
    standardized PER HOUR-of-day (Section 11), a calm low-variance night can post a
    high z without being a heat extreme, so the ROBUST statistic is the heatwave-
    window ENRICHMENT among the top ranks (reused from Section 11), NOT a brittle
    top-1.

(C) CSI >= 0 EVERYWHERE (by construction).
    --------------------------------------------------------------------------
    demand = max(vpd_z, 0) >= 0 and supply = max(-ndmi_z, 0) >= 0, and the weights
    are non-negative, so CSI = w_d*demand + w_s*supply >= 0 at every finite pixel.
    A near-zero CSI means near-normal conditions; a large CSI is a compound extreme.

SENSITIVITY HOOKS (step 66) -- present but NOT RUN in the baseline deliverable.
------------------------------------------------------------------------------
* `compute_csi(demand, supply, w_demand, w_supply)` is a PARAMETERISED function, so
  the unequal-weight sensitivity test is a trivial re-call with other weights.
* `copula_weights(...)` is a clearly-labelled STUB (raises NotImplementedError with
  a `# TODO Section 12 step 66` note) -- a placeholder for the copula-derived
  weights, deliberately NOT executed. The baseline deliverable uses the equal
  weights `config.WEIGHT_DEMAND` / `config.WEIGHT_SUPPLY` (0.5 / 0.5) ONLY.

Deliverables (checkpoint, Section 12; data/processed/, git-ignored)
-------------------------------------------------------------------
* section12_csi_70m.zarr -- THE deliverable. Per-overpass Compound Stress Index on
  the 70 m grid, dims (overpass=66, y=1155, x=1339):
    csi            -- baseline equal-weight CSI = 0.5*demand + 0.5*supply (>= 0)
    demand_stress  -- max(vpd_z, 0)  (time-varying)
    supply_stress  -- max(-ndmi_z, 0) (constant in time -- decision A)
  coords overpass/overpass_key/time/era5_hour/y/x and a CF spatial_ref (reopen with
  decode_coords="all"). Aligned exactly to reference_grid.tif.
* section12_csi_overpass_summary.parquet -- a small 66-row per-overpass table
  (spatial-mean csi/demand/supply, season part, in-heatwave flag) for a quick scan.
* figures/section12_csi_distribution.png -- CSI distribution (+ the demand/supply
  components) and the spatial-mean CSI per overpass with the heatwave window marked.
* figures/section12_csi_extreme_date_map.png -- 70 m CSI map for the top-CSI overpass.

Run (canopy env; no network -- reads only data/processed):
    python src/section12_compound_stress.py                 # full Section 12
    python src/section12_compound_stress.py --no-figures     # skip the figures
    python src/section12_compound_stress.py --verify-only    # re-open + QC the saved store
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

# Heavy geospatial libs. The pure logic below (the positive-part demand/supply
# definitions, the parameterised CSI combination, the heatwave enrichment) does not
# touch them, so it stays unit-testable without the geo stack installed (see
# test_section12_compound_stress.py).
import rioxarray  # noqa: F401,E402  (registers the .rio accessor)
import xarray as xr  # noqa: E402

# Make config importable whether run from repo root or src/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
import config  # noqa: E402

# Reuse the Section 11 heatwave-window helpers verbatim so the CSI extreme-date
# check uses the SAME 2023 peak-heat window and the SAME robust enrichment statistic
# (no re-definition -> the two sections cannot drift). Imported lazily-safe: the
# import only needs numpy + pandas (Section 11's heavy imports are top-level but the
# functions used here are pure), and the unit test stubs the geo stack the same way.
import section11_anomalies as sec11  # noqa: E402

log = logging.getLogger("section12")


# =========================================================================== #
# Source layer + deliverable names.
# --------------------------------------------------------------------------- #
ZSCORE_ZARR = "section11_zscores_70m.zarr"   # Section 11 deliverable -> the z-scores

# The z-score variables we consume. DEMAND is the positive part of vpd_z; SUPPLY is
# the positive part of -ndmi_z. We NEVER read raw VPD/NDMI (the protocol pitfall).
DEMAND_Z_VAR = "vpd_z"        # VPD z-score (Section 11) -> demand driver, time-varying
SUPPLY_Z_VAR = "ndmi_z"       # water-supply z-score (Section 11) -> supply, static in time

# Deliverables (data/processed/).
CSI_ZARR = "section12_csi_70m.zarr"
CSI_SUMMARY_PARQUET = "section12_csi_overpass_summary.parquet"

# Figures.
FIG_DIST = "section12_csi_distribution.png"
FIG_EXTREME = "section12_csi_extreme_date_map.png"

# Known peak-heat window of summer 2023 -- reused from Section 11 (single source of
# truth) for the CSI extreme-date confirmation (step 65 deliverable).
HEATWAVE_2023 = sec11.HEATWAVE_2023


# =========================================================================== #
# Pure logic (numpy only; unit-tested without the geo stack)
# =========================================================================== #
def demand_stress(vpd_z):
    """DEMAND stress = positive part of the VPD z-score (step 62): max(vpd_z, 0).

    Only ABOVE-normal VPD (a positive z) is stressful; below-normal VPD contributes
    nothing. Elementwise over an array of any shape. NaN is preserved (np.maximum
    propagates NaN), so missing pixels stay missing rather than becoming 0.
    The input MUST be the VPD *z-score* (Section 11), not raw VPD.
    """
    z = np.asarray(vpd_z, dtype="float64")
    return np.maximum(z, 0.0)


def supply_stress(ndmi_z):
    """SUPPLY stress = positive part of the NEGATED water-supply z-score (step 63).

        supply = max(-ndmi_z, 0)

    LOW water is stressful, so a BELOW-normal NDMI (a NEGATIVE z-score) flips to a
    POSITIVE stress contribution, while above-normal NDMI (positive z) contributes
    nothing. Elementwise; NaN preserved. The input MUST be the water-supply
    *z-score* (Section 11), NOT raw NDMI -- building this from raw NDMI is the
    protocol's common pitfall (it would not be on the demand stress's scale, so the
    equal-weight CSI would be dominated by whichever has the larger numeric range).
    """
    z = np.asarray(ndmi_z, dtype="float64")
    return np.maximum(-z, 0.0)


def compute_csi(demand, supply,
                w_demand: float = config.WEIGHT_DEMAND,
                w_supply: float = config.WEIGHT_SUPPLY):
    """Compound Stress Index = w_demand*demand + w_supply*supply (step 64).

    The PARAMETERISED combination (SENSITIVITY HOOK, step 66): the baseline uses the
    equal weights `config.WEIGHT_DEMAND` / `config.WEIGHT_SUPPLY` (0.5 / 0.5), but a
    caller can pass any non-negative weights to run the unequal-weight sensitivity
    test later -- that is the only change needed. `demand` and `supply` are the
    already-computed positive-part stresses (each >= 0), so with non-negative weights
    the CSI is >= 0 everywhere (NaN preserved where either input is NaN). Elementwise
    over arrays of any (broadcastable) shape.
    """
    d = np.asarray(demand, dtype="float64")
    s = np.asarray(supply, dtype="float64")
    return float(w_demand) * d + float(w_supply) * s


def copula_weights(*args, **kwargs):
    """STUB (SENSITIVITY HOOK, step 66) -- copula-derived CSI weights. NOT RUN.

    Placeholder for the planned step-66 sensitivity test that derives the demand/
    supply weights from the JOINT STATISTICAL DEPENDENCE (a copula) of the two
    stressors, rather than fixing them at 0.5/0.5. It is deliberately NOT executed in
    the baseline deliverable (the equal-weight version is sufficient to proceed now);
    it raises so a later run cannot silently fall through to wrong numbers.

    # TODO Section 12 step 66: fit a copula (e.g. a Gaussian / t / Gumbel copula via
    # statsmodels/copulas) to the joint (demand_stress, supply_stress) distribution
    # over the analysis pixels, derive dependence-aware weights from it, and re-run
    # `compute_csi` with those weights as a sensitivity variant alongside the
    # unequal-weight variant. Until then this is a clearly-labelled placeholder.
    """
    raise NotImplementedError(
        "copula_weights is a Section 12 step-66 sensitivity-test STUB and is not "
        "implemented; the baseline deliverable uses the equal weights "
        f"WEIGHT_DEMAND={config.WEIGHT_DEMAND} / WEIGHT_SUPPLY={config.WEIGHT_SUPPLY}. "
        "See the function docstring (# TODO Section 12 step 66).")


def in_heatwave(ts, window: tuple = HEATWAVE_2023) -> bool:
    """Whether a date lies in the known 2023 Phoenix peak-heat window (delegates to
    Section 11's definition -- single source of truth for the window)."""
    return sec11.in_heatwave(ts, window)


def heatwave_enrichment(times, scores, top_k: int = 11,
                        window: tuple = HEATWAVE_2023) -> dict:
    """Heatwave-window ENRICHMENT among the highest scores (delegates to Section 11).

    The robust extreme-date statistic (Section 11): of the ``top_k`` overpasses with
    the largest score, what fraction fall in the 2023 peak-heat window, versus the
    window's share of ALL overpasses (>1 == over-represented at the top). Used here on
    the spatial-mean CSI (and demand) to confirm the highest-CSI dates coincide with
    the summer-2023 compound extremes -- robust to the per-hour VPD standardization
    that makes a brittle top-1 unreliable.
    """
    return sec11.heatwave_enrichment(times, scores, top_k=top_k, window=window)


# =========================================================================== #
# Loading + assembly (the geo stack)
# =========================================================================== #
def _reference():
    """The 70 m reference grid as a 2-D rioxarray DataArray (the match target/CRS)."""
    return rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)


def load_zscores(processed: Path) -> "xr.Dataset":
    """Open the Section 11 z-score store (the ONLY input -- z-scores, never raw values).

    Reopened with decode_coords="all" so the CF spatial_ref / CRS round-trips. We
    read ONLY the `vpd_z` and `ndmi_z` z-score variables for the CSI; the raw VPD/NDMI
    in the Section 9 cube are deliberately NOT touched (the protocol's common pitfall).
    """
    store = processed / ZSCORE_ZARR
    if not store.exists():
        raise FileNotFoundError(
            f"Section 11 z-score store not found: {store}. Run section11_anomalies.py first.")
    ds = xr.open_zarr(store, decode_coords="all")
    for v in (DEMAND_Z_VAR, SUPPLY_Z_VAR):
        if v not in ds.data_vars:
            raise AssertionError(f"{ZSCORE_ZARR} is missing the z-score variable {v!r}")
    return ds


def _assert_inputs_are_zscores(zds: "xr.Dataset") -> None:
    """Assert the CSI inputs are the Section-11 Z-SCORES, not raw VPD/NDMI (the pitfall).

    A z-score field has mean ~0 and std ~1 over its valid pixels and (for NDMI) ranges
    well into +/- several sigma; raw VPD (kPa, ~0..7, all positive) or raw NDMI
    (~-1..1, mean ~ -0.07) would NOT. We check, in-code:
      * the variables carry the z-score names (DEMAND_Z_VAR / SUPPLY_Z_VAR) and a
        dimensionless 'units' attr where present;
      * `ndmi_z` has whole-field mean ~0 and std ~1 (the spatial standardization is
        0/1 by construction -- a raw NDMI field would have mean ~ -0.07 and std ~0.09,
        which this would catch);
      * `vpd_z` takes BOTH signs (raw VPD in kPa is strictly >= 0, so a min < 0 proves
        it is the anomaly z-score, not raw VPD).
    Raises AssertionError if the inputs look like raw values. This is the programmatic
    guard behind the README/header claim that the CSI uses z-scores, not raw inputs.
    """
    nd = zds[SUPPLY_Z_VAR].values
    nd_mean = float(np.nanmean(nd)); nd_std = float(np.nanstd(nd))
    if not (abs(nd_mean) < 0.05 and abs(nd_std - 1.0) < 0.05):
        raise AssertionError(
            f"{SUPPLY_Z_VAR} does not look like a z-score (mean={nd_mean:+.4f}, "
            f"std={nd_std:.4f}; expected ~0 / ~1). Refusing to build the supply stress "
            "from a non-z-score input (protocol pitfall: raw NDMI would dominate the "
            "equal-weight CSI).")
    vd = zds[DEMAND_Z_VAR].values
    vd_min = float(np.nanmin(vd)); vd_max = float(np.nanmax(vd))
    if not (vd_min < 0.0 < vd_max):
        raise AssertionError(
            f"{DEMAND_Z_VAR} does not look like a z-score (min={vd_min:+.4f}, "
            f"max={vd_max:+.4f}; a z-score straddles 0, raw VPD in kPa is >= 0). "
            "Refusing to build the demand stress from raw VPD.")
    log.info("INPUT CHECK: CSI inputs are Section-11 Z-SCORES, not raw values "
             "-> %s mean=%+.4f std=%.4f (~0/~1); %s straddles 0 (min=%+.4f max=%+.4f). "
             "Raw VPD/NDMI are NOT used (protocol pitfall avoided).",
             SUPPLY_Z_VAR, nd_mean, nd_std, DEMAND_Z_VAR, vd_min, vd_max)


def _blosc():
    import numcodecs
    return numcodecs.Blosc(cname="zstd", clevel=5, shuffle=numcodecs.Blosc.SHUFFLE)


def build_csi_dataset(processed: Path, reference: "xr.DataArray"
                      ) -> tuple["xr.Dataset", dict]:
    """Build the (overpass, y, x) CSI + component cube from the Section 11 z-scores.

    demand = max(vpd_z, 0) (time-varying); supply = max(-ndmi_z, 0) (constant in time
    because ndmi_z is constant in time -- decision A); CSI = WEIGHT_DEMAND*demand +
    WEIGHT_SUPPLY*supply (baseline 0.5/0.5, decision/step 64). Returns (dataset, meta)
    where meta carries the weights, the static-supply flag and the CSI stats for the
    QC note / report.
    """
    zds = load_zscores(processed)
    _assert_inputs_are_zscores(zds)

    n = zds.sizes["overpass"]
    log.info("Building CSI from Section 11 z-scores: %d overpasses, grid (y=%d, x=%d)",
             n, zds.sizes["y"], zds.sizes["x"])
    log.info("  DEMAND = max(%s, 0)  [time-varying];  SUPPLY = max(-%s, 0)  "
             "[constant in time -- %s is a SPATIAL standardization, Section 11 decision B]",
             DEMAND_Z_VAR, SUPPLY_Z_VAR, SUPPLY_Z_VAR)
    log.info("  Baseline EQUAL weights: WEIGHT_DEMAND=%.3f  WEIGHT_SUPPLY=%.3f (step 64)",
             config.WEIGHT_DEMAND, config.WEIGHT_SUPPLY)

    vpd_z = zds[DEMAND_Z_VAR].values.astype("float64")        # (overpass, y, x), time-varying
    ndmi_z = zds[SUPPLY_Z_VAR].values.astype("float64")       # (overpass, y, x), constant in time

    demand = demand_stress(vpd_z).astype("float32")           # max(vpd_z, 0)
    supply = supply_stress(ndmi_z).astype("float32")          # max(-ndmi_z, 0)
    csi = compute_csi(demand, supply,
                      config.WEIGHT_DEMAND, config.WEIGHT_SUPPLY).astype("float32")

    # Confirm the supply term is genuinely constant across overpasses (it must be,
    # because ndmi_z is) -- a cheap invariant that documents decision A in the data.
    s0 = supply[0]; sL = supply[-1]
    both = np.isfinite(s0) & np.isfinite(sL)
    supply_static = bool(np.allclose(s0[both], sL[both], atol=1e-6)) if both.any() else True
    log.info("  supply_stress constant across overpasses: %s (decision A)", supply_static)

    data_vars = {
        "csi": (("overpass", "y", "x"), csi),
        "demand_stress": (("overpass", "y", "x"), demand),
        "supply_stress": (("overpass", "y", "x"), supply),
    }
    coords = {
        "overpass": zds["overpass"].values,
        "overpass_key": ("overpass", np.array([str(k) for k in zds["overpass_key"].values],
                                              dtype=object)),
        "time": ("overpass", zds["time"].values),
        "era5_hour": ("overpass", zds["era5_hour"].values),
        "y": reference.y.values,
        "x": reference.x.values,
    }
    ds = xr.Dataset(data_vars, coords=coords)
    ds = ds.rio.write_crs(reference.rio.crs)
    for v in ds.data_vars:
        if {"y", "x"} <= set(ds[v].dims):
            ds[v].attrs["grid_mapping"] = "spatial_ref"
    _annotate(ds, supply_static)
    zds.close()

    finite = np.isfinite(csi)
    n_finite = int(finite.sum())
    n_total = int(csi.size)
    meta = {
        "n_overpass": n,
        "w_demand": float(config.WEIGHT_DEMAND),
        "w_supply": float(config.WEIGHT_SUPPLY),
        "supply_static": supply_static,
        "csi_min": float(np.nanmin(csi)), "csi_mean": float(np.nanmean(csi)),
        "csi_max": float(np.nanmax(csi)),
        "n_finite": n_finite, "n_total": n_total,
        "frac_finite": n_finite / n_total if n_total else float("nan"),
        "csi_ge_zero": bool(np.all(csi[finite] >= 0.0)),
    }
    return ds, meta


def _annotate(ds: "xr.Dataset", supply_static: bool) -> None:
    """Attach units / methodology provenance to the CSI variables + dataset."""
    notes = {
        "csi": "Compound Stress Index (baseline, equal weights): "
               "CSI = WEIGHT_DEMAND*max(vpd_z,0) + WEIGHT_SUPPLY*max(-ndmi_z,0) "
               "(steps 62-64). >= 0 everywhere; near 0 = near normal, large = a "
               "compound heat-drought extreme. Built from Section 11 z-scores (NOT "
               "raw VPD/NDMI -- the protocol's common pitfall).",
        "demand_stress": "Demand stress = positive part of the VPD z-score, "
                         "max(vpd_z, 0) (step 62). Time-varying. Only above-normal "
                         "VPD is stressful.",
        "supply_stress": "Supply stress = positive part of the NEGATED water-supply "
                         "z-score, max(-ndmi_z, 0) (step 63). Low water -> positive "
                         "stress. CONSTANT IN TIME (ndmi_z is a single-composite "
                         "spatial standardization; Section 11 decision B).",
    }
    for v, note in notes.items():
        if v in ds:
            ds[v].attrs["long_name"] = note
            ds[v].attrs["units"] = "1"            # standardized / dimensionless
    ds.attrs["title"] = ("Section 12: Compound Stress Index (CSI) from the VPD & NDMI "
                         "z-scores, baseline equal weights (steps 62-66)")
    ds.attrs["crs"] = config.CRS
    ds.attrs["weight_demand"] = float(config.WEIGHT_DEMAND)
    ds.attrs["weight_supply"] = float(config.WEIGHT_SUPPLY)
    ds.attrs["method"] = ("demand=max(vpd_z,0) (step 62); supply=max(-ndmi_z,0) "
                          "(step 63); CSI=WEIGHT_DEMAND*demand+WEIGHT_SUPPLY*supply "
                          "(step 64, baseline equal weights 0.5/0.5). Inputs are the "
                          "Section 11 z-scores, never raw VPD/NDMI.")
    ds.attrs["supply_stress_constant_in_time"] = str(supply_static)
    ds.attrs["note_supply_static"] = (
        "supply_stress is CONSTANT across overpasses because ndmi_z is a SPATIAL "
        "standardization of the single 2023 NDMI composite (Section 11 decision B). "
        "Consequence: the temporal ranking of spatial-mean CSI == the ranking of the "
        "VPD demand, so the highest-CSI dates are the highest VPD-demand dates.")
    ds.attrs["sensitivity_hooks"] = (
        "compute_csi(demand, supply, w_demand, w_supply) is parameterised for the "
        "unequal-weight test; copula_weights() is a NotImplementedError stub for the "
        "copula-derived-weight test (step 66). Neither sensitivity variant is run in "
        "this baseline deliverable.")


def write_csi_zarr(ds: "xr.Dataset", store: Path) -> Path:
    """Write the CSI + component cube to a compressed, chunked Zarr.

    Each var chunks one overpass per slice (matching the Section 9/11 cubes). object /
    datetime coords are left uncompressed (Blosc cannot encode them). Overwrites.
    """
    if store.exists():
        import shutil
        shutil.rmtree(store)
    ny, nx = ds.sizes["y"], ds.sizes["x"]
    comp = _blosc()
    enc: dict[str, dict] = {}
    for v in ds.data_vars:
        if ds[v].dims == ("overpass", "y", "x"):
            enc[v] = {"compressor": comp, "chunks": (1, ny, nx)}
    store.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(store, mode="w", encoding=enc, consolidated=True)
    log.info("Wrote CSI cube -> %s", store)
    log.info("  dims=%s", dict(ds.sizes))
    log.info("  vars: %s", list(ds.data_vars))
    return store


# =========================================================================== #
# QC (step 65 + the deliverable confirmation)
# =========================================================================== #
def record_csi_stats(ds: "xr.Dataset") -> dict:
    """Record + PRINT the CSI min/mean/max, CSI >= 0 everywhere, and finite fraction."""
    csi = ds["csi"].values
    finite = np.isfinite(csi)
    cmin = float(np.nanmin(csi)); cmean = float(np.nanmean(csi)); cmax = float(np.nanmax(csi))
    ge0 = bool(np.all(csi[finite] >= 0.0))
    n_finite = int(finite.sum()); n_total = int(csi.size)
    frac = n_finite / n_total if n_total else float("nan")
    dmin = float(np.nanmin(ds["demand_stress"].values))
    dmax = float(np.nanmax(ds["demand_stress"].values))
    smin = float(np.nanmin(ds["supply_stress"].values))
    smax = float(np.nanmax(ds["supply_stress"].values))
    log.info("=" * 70)
    log.info("QC (step 65): Compound Stress Index distribution")
    log.info("  CSI       min=%+.4f  mean=%+.4f  max=%+.4f", cmin, cmean, cmax)
    log.info("  CSI >= 0 EVERYWHERE (finite cells): %s  (built from positive parts)", ge0)
    log.info("  finite cells: %d / %d  (fraction finite = %.4f)", n_finite, n_total, frac)
    log.info("  demand_stress  min=%.4f  max=%.4f  [max(vpd_z,0), time-varying]", dmin, dmax)
    log.info("  supply_stress  min=%.4f  max=%.4f  [max(-ndmi_z,0), constant in time]",
             smin, smax)
    return {"csi_min": cmin, "csi_mean": cmean, "csi_max": cmax, "csi_ge_zero": ge0,
            "n_finite": n_finite, "n_total": n_total, "frac_finite": frac,
            "demand_min": dmin, "demand_max": dmax, "supply_min": smin, "supply_max": smax}


def extreme_csi_dates(ds: "xr.Dataset", top_n: int = 10) -> tuple[pd.DataFrame, dict, dict]:
    """Overpasses with the largest SPATIAL-MEAN CSI (step 65 compound-extreme check).

    Ranks the 66 overpasses by spatial-mean CSI and confirms the highest-CSI dates
    coincide with the known summer-2023 compound extremes (July 2023 = Phoenix's
    hottest month on record). Because the SUPPLY term is constant in time (decision
    A), the CSI ranking == the VPD-demand ranking; this is verified in-code (the CSI
    and demand rankings are identical), and the ROBUST heatwave ENRICHMENT statistic
    (Section 11) is reported for BOTH the CSI and the demand, since the per-hour VPD
    standardization makes a brittle top-1 unreliable. Returns (ranked DataFrame,
    csi-enrichment dict, demand-enrichment dict) and PRINTS the top-N + enrichment.
    """
    times = pd.to_datetime(ds["time"].values)
    keys = [str(k) for k in ds["overpass_key"].values]
    csi_mean = ds["csi"].mean(dim=("y", "x"), skipna=True).values
    dem_mean = ds["demand_stress"].mean(dim=("y", "x"), skipna=True).values
    sup_mean = ds["supply_stress"].mean(dim=("y", "x"), skipna=True).values
    df = pd.DataFrame({"overpass_key": keys, "time": times,
                       "csi_mean": csi_mean, "demand_mean": dem_mean,
                       "supply_mean": sup_mean})
    df = df.sort_values("csi_mean", ascending=False).reset_index(drop=True)
    df["in_heatwave_2023"] = df["time"].apply(in_heatwave)
    df["rank"] = np.arange(1, len(df) + 1)

    # Verify the CSI ranking equals the demand ranking (decision B consequence).
    by_csi = df["overpass_key"].tolist()
    by_dem = (pd.DataFrame({"k": keys, "d": dem_mean})
              .sort_values("d", ascending=False)["k"].tolist())
    rank_match = (by_csi == by_dem)

    enr_csi = heatwave_enrichment(df["time"].to_numpy(), df["csi_mean"].to_numpy(), top_k=11)
    enr_dem = heatwave_enrichment(df["time"].to_numpy(), df["demand_mean"].to_numpy(), top_k=11)

    top = df.head(top_n).copy()
    log.info("=" * 70)
    log.info("QC (step 65): top-%d highest spatial-mean CSI overpasses "
             "(expect summer-2023 compound extremes; July 2023 = hottest month on record, "
             "~Jun 30..Jul 30 >=110F streak)", top_n)
    for _, r in top.iterrows():
        log.info("  %s  CSI=%.4f  (demand=%.4f  supply=%.4f)  %s",
                 pd.Timestamp(r["time"]), r["csi_mean"], r["demand_mean"], r["supply_mean"],
                 "<-- in 2023 heatwave window" if r["in_heatwave_2023"] else "")
    log.info("  CSI temporal ranking == VPD-demand ranking: %s "
             "(supply is constant in time -> decision A/B consequence)", rank_match)
    log.info("  HEATWAVE-WINDOW ENRICHMENT (robust to per-hour VPD standardization):")
    log.info("    CSI:    window is %.0f%% of all overpasses but %.0f%% of the top-%d "
             "-> %.2fx enriched", 100 * enr_csi["base_frac"], 100 * enr_csi["top_frac"],
             enr_csi["top_k"], enr_csi["enrichment"])
    log.info("    demand: window is %.0f%% of all overpasses but %.0f%% of the top-%d "
             "-> %.2fx enriched", 100 * enr_dem["base_frac"], 100 * enr_dem["top_frac"],
             enr_dem["top_k"], enr_dem["enrichment"])
    log.info("    ranks of the %d heatwave overpasses by CSI (1=highest): %s",
             enr_csi["n_hw"], enr_csi["hw_ranks"])
    enr_csi["rank_match_demand"] = rank_match
    return df, enr_csi, enr_dem


def overpass_summary_table(ds: "xr.Dataset") -> pd.DataFrame:
    """Small 66-row per-overpass summary: spatial-mean csi/demand/supply + flags."""
    times = pd.to_datetime(ds["time"].values)
    rec = {
        "overpass_key": [str(k) for k in ds["overpass_key"].values],
        "time": times,
        "era5_hour": pd.to_datetime(ds["era5_hour"].values),
        "season_part": [sec11.season_part_label(t) for t in times],
        "in_heatwave_2023": [in_heatwave(t) for t in times],
    }
    for v in ("csi", "demand_stress", "supply_stress"):
        rec[f"{v}_spatial_mean"] = ds[v].mean(dim=("y", "x"), skipna=True).values
    df = pd.DataFrame(rec)
    return df.sort_values("csi_spatial_mean", ascending=False).reset_index(drop=True)


# =========================================================================== #
# Figures (deliverable QC)
# =========================================================================== #
def make_distribution_figure(ds: "xr.Dataset", extreme_df: pd.DataFrame,
                             enr_csi: dict, figures_dir: Path) -> Path:
    """CSI distribution + components (L) and the spatial-mean CSI per overpass (R).

    Left: histogram of the CSI over all finite pixel-overpasses (the step-65
    distribution deliverable) with the demand/supply component histograms inset.
    Right: the spatial-mean CSI for each of the 66 overpasses in time order, with the
    2023 heatwave window shaded -- visually confirming the highest-CSI dates fall in
    the known compound-extreme window.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(15, 5.4), constrained_layout=True)

    # (L) CSI distribution + components.
    csi = ds["csi"].values
    csi_flat = csi[np.isfinite(csi)]
    # demand/supply: one representative overpass for supply (constant in time), all
    # overpasses for demand (so the demand histogram reflects the temporal spread).
    dem = ds["demand_stress"].values
    dem_flat = dem[np.isfinite(dem)]
    sup0 = ds["supply_stress"].isel(overpass=0).values
    sup_flat = sup0[np.isfinite(sup0)]
    cmean = float(np.mean(csi_flat)); cmax = float(np.max(csi_flat))
    axL.hist(csi_flat, bins=90, color="#6a51a3", alpha=0.85, label="CSI (all pixel-overpasses)")
    axL.hist(dem_flat, bins=90, color="#d7301f", alpha=0.40, label="demand = max(vpd_z,0)")
    axL.hist(sup_flat, bins=90, color="#238b45", alpha=0.40,
             label="supply = max(-ndmi_z,0)  (constant in time)")
    axL.axvline(0, color="k", lw=0.8, ls=":")
    axL.set_yscale("log")
    axL.set_xlabel("stress value (dimensionless; z-score units)")
    axL.set_ylabel("pixel-overpass count (log)")
    axL.set_title(f"Section 12: Compound Stress Index distribution\n"
                  f"CSI = {config.WEIGHT_DEMAND:g}*demand + {config.WEIGHT_SUPPLY:g}*supply  "
                  f"(>= 0; mean={cmean:.3f}, max={cmax:.2f})")
    axL.legend(loc="upper right", fontsize=8)

    # (R) spatial-mean CSI per overpass in time order, heatwave window shaded.
    times = pd.to_datetime(ds["time"].values)
    csi_op = ds["csi"].mean(dim=("y", "x"), skipna=True).values
    order = np.argsort(times.values)
    t_ord = times[order]
    csi_ord = csi_op[order]
    hw_lo, hw_hi = HEATWAVE_2023
    axR.axvspan(hw_lo, hw_hi, color="#fdae6b", alpha=0.35,
                label="2023 peak-heat window (Jun 30 - Jul 30)")
    axR.plot(t_ord, csi_ord, "o-", color="#6a51a3", ms=4, lw=1.0, label="spatial-mean CSI")
    # mark the single highest-CSI overpass
    top_t = pd.Timestamp(extreme_df.iloc[0]["time"])
    top_v = float(extreme_df.iloc[0]["csi_mean"])
    axR.plot([top_t], [top_v], "*", color="#54278f", ms=16, zorder=5,
             label=f"highest CSI ({top_t:%Y-%m-%d})")
    axR.set_xlabel("overpass date (2023)")
    axR.set_ylabel("spatial-mean CSI over the domain")
    axR.set_title("Spatial-mean CSI per overpass\n"
                  f"heatwave window {100*enr_csi['base_frac']:.0f}% of overpasses but "
                  f"{100*enr_csi['top_frac']:.0f}% of the top-{enr_csi['top_k']} "
                  f"({enr_csi['enrichment']:.2f}x enriched)")
    axR.legend(loc="best", fontsize=8)
    for lab in axR.get_xticklabels():
        lab.set_rotation(30); lab.set_horizontalalignment("right")

    out = figures_dir / FIG_DIST
    fig.savefig(out, dpi=150, bbox_inches="tight"); plt.close(fig)
    log.info("Wrote figure -> %s", out.name)
    return out


def make_extreme_date_map(ds: "xr.Dataset", extreme_df: pd.DataFrame,
                          figures_dir: Path) -> Path | None:
    """Map the 70 m CSI field for the TOP compound-extreme overpass (step 65 map)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    top_key = extreme_df.iloc[0]["overpass_key"]
    keys = [str(k) for k in ds["overpass_key"].values]
    i = keys.index(top_key)
    arr = ds["csi"].isel(overpass=i).values
    ts = pd.Timestamp(ds["time"].values[i])
    left, bottom, right, top = config.GRID_BOUNDS
    extent = (left, right, bottom, top)
    fig, ax = plt.subplots(figsize=(7.6, 6.6))
    vmax = float(np.nanmax(arr)) if np.isfinite(arr).any() else 1.0
    vmax = max(vmax, 0.5)
    im = ax.imshow(arr, extent=extent, origin="upper", cmap="magma", vmin=0.0, vmax=vmax)
    fig.colorbar(im, ax=ax, shrink=0.85, label="Compound Stress Index (>= 0)")
    ax.set_title(f"Section 12: Compound Stress Index, highest-CSI overpass\n{ts:%Y-%m-%d %H:%M} UTC "
                 f"(spatial-mean CSI = {extreme_df.iloc[0]['csi_mean']:.3f}; "
                 f"{'in' if in_heatwave(ts) else 'NOT in'} the 2023 heatwave window)")
    ax.set_xlabel("Easting (m, EPSG:32612)"); ax.set_ylabel("Northing (m)")
    out = figures_dir / FIG_EXTREME
    fig.savefig(out, dpi=150, bbox_inches="tight"); plt.close(fig)
    log.info("Wrote figure -> %s  (overpass %s, %s)", out.name, top_key, ts)
    return out


# =========================================================================== #
# Verification (re-open + assert geometry == reference_grid.tif)
# =========================================================================== #
def verify_grid(store: Path, reference: "xr.DataArray") -> "xr.Dataset":
    """Re-open the saved store and ASSERT its geometry matches reference_grid.tif."""
    ds = xr.open_zarr(store, decode_coords="all")
    log.info("=" * 70)
    log.info("VERIFY: reopened %s", store.name)
    log.info("  dims              %s", dict(ds.sizes))
    log.info("  vars              %s", list(ds.data_vars))
    crs = ds.rio.crs
    tx = ds.rio.transform()
    log.info("  CRS               %s", crs)
    log.info("  transform         %s", tuple(tx))
    log.info("  pixel size        (%.1f, %.1f) m", tx.a, tx.e)
    log.info("  shape (y, x)      (%d, %d)", ds.sizes["y"], ds.sizes["x"])
    log.info("  origin (x, y)     (%.1f, %.1f)", tx.c, tx.f)

    assert crs.to_epsg() == reference.rio.crs.to_epsg(), "CRS mismatch vs reference"
    assert ds.sizes["y"] == reference.sizes["y"] and ds.sizes["x"] == reference.sizes["x"], \
        "shape mismatch vs reference"
    rtx = reference.rio.transform()
    assert np.allclose([tx.a, tx.e, tx.c, tx.f], [rtx.a, rtx.e, rtx.c, rtx.f], atol=1e-6), \
        "transform (pixel size / origin) mismatch vs reference"
    assert np.allclose(ds.x.values, reference.x.values, atol=1e-6), "x mismatch"
    assert np.allclose(ds.y.values, reference.y.values, atol=1e-6), "y mismatch"
    assert ds.sizes["overpass"] == 66, f"expected 66 overpasses, got {ds.sizes['overpass']}"
    for v in ("csi", "demand_stress", "supply_stress"):
        assert v in ds.data_vars, f"missing variable {v}"
        assert np.issubdtype(ds[v].dtype, np.floating), f"{v} should be float"
    # CSI >= 0 everywhere (built from positive parts with non-negative weights).
    csi = ds["csi"].values
    finite = np.isfinite(csi)
    assert bool(np.all(csi[finite] >= 0.0)), "CSI must be >= 0 everywhere (positive parts)"
    # supply_stress is constant across overpasses (decision A: ndmi_z is constant).
    s0 = ds["supply_stress"].isel(overpass=0).values
    sL = ds["supply_stress"].isel(overpass=ds.sizes["overpass"] - 1).values
    both = np.isfinite(s0) & np.isfinite(sL)
    assert np.allclose(s0[both], sL[both], atol=1e-6), \
        "supply_stress must be constant across overpasses (ndmi_z is constant in time)"
    log.info("  ASSERTIONS PASSED: geometry == reference_grid.tif; 66 overpasses; "
             "csi/demand/supply present & float; CSI >= 0 everywhere; supply constant in time.")
    return ds


# =========================================================================== #
# Orchestration / CLI
# =========================================================================== #
def write_overpass_summary(ds: "xr.Dataset", out_path: Path) -> Path:
    df = overpass_summary_table(ds)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    log.info("Wrote per-overpass CSI summary -> %s (%d rows, %d cols)",
             out_path, len(df), df.shape[1])
    return out_path


def run(make_figures: bool = True, verify_only: bool = False) -> dict:
    config.ensure_dirs()
    processed = config.PROCESSED_DIR
    reference = _reference()
    store = processed / CSI_ZARR
    results: dict = {}

    meta: dict = {}
    if not verify_only:
        ds, meta = build_csi_dataset(processed, reference)
        write_csi_zarr(ds, store)
        results["csi_zarr"] = store
        ds.close()

    # Re-open from disk and run the QC (step 65 deliverable).
    ds = verify_grid(store, reference)
    results["dims"] = dict(ds.sizes)
    results["variables"] = list(ds.data_vars)

    stats = record_csi_stats(ds)
    extreme_df, enr_csi, enr_dem = extreme_csi_dates(ds, top_n=10)
    results["stats"] = stats
    results["extreme_df"] = extreme_df
    results["enrichment_csi"] = enr_csi
    results["enrichment_demand"] = enr_dem

    results["overpass_summary"] = write_overpass_summary(
        ds, processed / CSI_SUMMARY_PARQUET)

    if make_figures:
        results["fig_dist"] = make_distribution_figure(ds, extreme_df, enr_csi, config.FIGURES_DIR)
        results["fig_extreme"] = make_extreme_date_map(ds, extreme_df, config.FIGURES_DIR)

    _report_sensitivity_hooks()
    _report(results)
    ds.close()
    return results


def _report_sensitivity_hooks() -> None:
    """PRINT that the baseline weights are 0.5/0.5 and the step-66 hooks are NOT run."""
    log.info("=" * 70)
    log.info("SENSITIVITY HOOKS (step 66) -- present but NOT run in this baseline:")
    log.info("  baseline weights: WEIGHT_DEMAND=%.3f  WEIGHT_SUPPLY=%.3f (config.py)",
             config.WEIGHT_DEMAND, config.WEIGHT_SUPPLY)
    log.info("  (a) compute_csi(demand, supply, w_demand, w_supply) is parameterised "
             "-> unequal-weight test is a trivial re-call (NOT run now).")
    # Demonstrate the copula stub is a placeholder WITHOUT executing the variant: we
    # confirm it raises NotImplementedError rather than returning numbers.
    try:
        copula_weights()
        stub_ok = False
    except NotImplementedError:
        stub_ok = True
    log.info("  (b) copula_weights() is a NotImplementedError STUB (placeholder, not "
             "executed): raises as expected = %s.", stub_ok)


def _report(results: dict) -> None:
    log.info("=" * 70)
    log.info("Section 12 complete. Deliverables (data/processed/):")
    for key in ("csi_zarr", "overpass_summary"):
        if key in results:
            log.info("  %-16s -> %s", key, Path(results[key]).name)
    for key in ("fig_dist", "fig_extreme"):
        if results.get(key):
            log.info("  figure           -> %s", Path(results[key]).name)
    s = results.get("stats", {})
    if s:
        log.info("  CSI min/mean/max -> %+.4f / %+.4f / %+.4f  (>= 0 everywhere: %s)",
                 s["csi_min"], s["csi_mean"], s["csi_max"], s["csi_ge_zero"])
    log.info("=" * 70)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 12 - compute the Compound Stress Index (CSI) from the "
                    "Section 11 VPD & NDMI z-scores, baseline equal weights (steps 62-66).")
    p.add_argument("--no-figures", action="store_true", help="skip the QC figures.")
    p.add_argument("--verify-only", action="store_true",
                   help="skip the build; re-open the saved store and run verify + QC.")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    run(make_figures=not args.no_figures, verify_only=args.verify_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
