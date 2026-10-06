#!/usr/bin/env python3
"""Section 12 / Compound Stress Index (CSI) — combine the VPD demand & SOIL-MOISTURE supply z-scores into a joint heat-drought stress scalar (steps 62-66).

Inputs : data/processed/section11_zscores_70m.zarr (vpd_z demand, sm_z supply, ndmi_z
         vegetation CHECK; z-scores only, never raw fields).
Outputs: data/processed/section12_csi_70m.zarr (csi, demand_stress, supply_stress; overpass=66, y=1155, x=1339),
         data/processed/section12_csi_overpass_summary.parquet (carries ndmi_z_check_spatial_mean),
         data/processed/section12_weight_sensitivity.parquet (five predeclared demand/supply
         weight scenarios, including the equal-weight baseline and both pure components),
         figures/section12_csi_distribution.png, figures/section12_csi_extreme_date_map.png
Key decisions (full rationale in docs/DESIGN_DECISIONS.md, Section 12):
  - demand = max(vpd_z, 0); supply = max(-sm_z, 0); CSI = WEIGHT_DEMAND*demand + WEIGHT_SUPPLY*supply (baseline 0.5/0.5).
  - SUPPLY AXIS = root-zone SOIL MOISTURE sm_z (config.SUPPLY_VAR), NOT ndmi_z (BLOCKER B1a). sm_z is robust-rescaled (IQR/1.349) to ~unit spread before supply_stress so its real single-year compressed variance (std ~0.45) does not silently de-weight supply against the ~unit-std demand term. ndmi_z (vegetation greenness/moisture) is carried as a CHECK only.
  - CROSS-MODULE NAMING INVARIANT: primary supply = sm_z (consumed by
    supply_stress/CSI); ndmi_z is the vegetation check only.
  - Both terms time-varying (sm_z is a temporal LOYO anomaly), so CSI varies in space AND time; CSI >= 0 everywhere.
  - Inputs must be z-scores (asserted in-code); building supply from a raw field is the protocol's common pitfall.
  - CSI is now a SECONDARY cross-city scalar. The PRIMARY RQ1 detector is the new Section 15 VPD_z x SM_z response surface (built by a separate module); CSI is retained for corroboration, not deleted.
  - Extreme-date check uses Section 11's heatwave-window enrichment (robust to per-hour VPD standardization), not a top-1.
  - Step-66 unequal-weight sensitivity is executed over five predeclared convex weight pairs.
    The copula idea remains an explicit NotImplementedError because no defensible estimator was
    pre-specified; it is not silently substituted for the requested deterministic sensitivity.
Run: python src/section12_compound_stress.py [--no-figures] [--verify-only] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

# Heavy geospatial libs. The pure logic below (demand/supply positive parts, the
# parameterised CSI combination, the heatwave enrichment) does not touch them, so it
# stays unit-testable without the geo stack installed.
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
import plot_style as ps  # noqa: E402  (shared figure color convention)

# Reuse the Section 11 heatwave-window helpers verbatim so the CSI extreme-date check
# uses the SAME 2023 window and enrichment statistic (no re-definition -> no drift).
import section11_anomalies as sec11  # noqa: E402

log = logging.getLogger("section12")


# --- Source layer + deliverable names ---------------------------------------
ZSCORE_ZARR = "section11_zscores_70m.zarr"   # Section 11 deliverable -> the z-scores

# DEMAND is the positive part of vpd_z; SUPPLY the positive part of the NEGATED
# soil-moisture z (max(-sm_z, 0)). We never read raw fields (the protocol pitfall).
DEMAND_Z_VAR = "vpd_z"        # VPD z-score (Section 11) -> demand driver, time-varying

# CROSS-MODULE SUPPLY/NAMING INVARIANT (BLOCKER B1a; see plan §2). Section 12 PRIMARY
# supply = sm_z (config.SUPPLY_VAR) -> root-zone SOIL MOISTURE, consumed by
# supply_stress/CSI. ndmi_z (vegetation greenness/moisture) is the VEGETATION CHECK only
# and is NOT in the CSI cube. Section 13 persists it as mean_ndmi_z_tree.
SUPPLY_Z_VAR = config.SUPPLY_VAR   # soil-moisture z-score (sm_z) -> supply, time-varying
CHECK_Z_VAR = "ndmi_z"             # NDMI z-score -> VEGETATION CHECK only (kept out of the cube)

CSI_ZARR = "section12_csi_70m.zarr"
CSI_SUMMARY_PARQUET = "section12_csi_overpass_summary.parquet"
WEIGHT_SENSITIVITY_PARQUET = "section12_weight_sensitivity.parquet"

# Predeclared step-66 sensitivity grid. Endpoints show the pure components; the interior
# scenarios show whether temporal rankings and heatwave enrichment depend on equal weighting.
DEFAULT_WEIGHT_GRID: tuple[tuple[float, float], ...] = (
    (0.0, 1.0),
    (0.3, 0.7),
    (0.5, 0.5),
    (0.7, 0.3),
    (1.0, 0.0),
)

FIG_DIST = "section12_csi_distribution.png"
FIG_EXTREME = "section12_csi_extreme_date_map.png"

# Known peak-heat window of summer 2023, reused from Section 11 (single source of truth).
HEATWAVE_2023 = sec11.HEATWAVE_2023


# --- Pure logic (numpy only; unit-tested without the geo stack) --------------
def demand_stress(vpd_z):
    """DEMAND stress = positive part of the VPD z-score (step 62): max(vpd_z, 0).

    Elementwise; NaN preserved (missing pixels stay missing). Input MUST be the VPD
    z-score, not raw VPD.
    """
    z = np.asarray(vpd_z, dtype="float64")
    return np.maximum(z, 0.0)


def supply_stress(supply_z):
    """SUPPLY stress = positive part of the NEGATED soil-moisture z-score (step 63): max(-sm_z, 0).

    Below-normal soil moisture (negative wetness z) flips to positive stress. Elementwise;
    NaN preserved. Sign-correct for ANY wetness z (positive z = wet = LOW stress), so the
    same formula works unchanged whether the supply axis is sm_z (BLOCKER B1a) or another
    wetness z. Input MUST be a z-score (robust-rescaled to ~unit spread), never a raw field:
    a tiny-variance raw field would silently de-weight the equal-weight CSI.
    """
    z = np.asarray(supply_z, dtype="float64")
    return np.maximum(-z, 0.0)


def robust_unit_scale(z):
    """Rescale a z array to ~unit spread by dividing by a ROBUST sigma = IQR / 1.349.

    IQR is the 75th - 25th percentile over the FINITE values; 1.349 is the IQR/std ratio
    of a standard normal, so IQR/1.349 is a robust standard-deviation estimate. Sign and
    NaNs are preserved (division by a positive scalar). If fewer than 2 finite values (or a
    degenerate IQR of 0), the input is returned UNCHANGED.

    Rationale (BLOCKER B1a): sm_z's real single-year compressed variance (std ~0.45) would
    otherwise make max(-sm_z, 0) small and silently de-weight the supply term against the
    ~unit-std demand term. This restores ~unit spread. The compressed variance is a real
    property of a single pilot year -- handled here by rescale, NEVER "fixed" upstream.
    """
    z = np.asarray(z, dtype="float64")
    finite = z[np.isfinite(z)]
    if finite.size < 2:
        return z
    q75, q25 = np.percentile(finite, [75, 25])
    iqr = q75 - q25
    if not (iqr > 0.0):
        return z
    return z / (iqr / 1.349)


def validate_csi_weights(w_demand: float, w_supply: float) -> tuple[float, float]:
    """Validate a convex demand/supply weight pair and return it as floats.

    The sensitivity is intentionally a convex reweighting of the same two component fields:
    weights must be finite, non-negative, and sum to one. This prevents accidental scale
    changes from masquerading as a weighting result.
    """
    wd = float(w_demand)
    ws = float(w_supply)
    if not (np.isfinite(wd) and np.isfinite(ws)):
        raise ValueError("CSI weights must be finite")
    if wd < 0.0 or ws < 0.0:
        raise ValueError("CSI weights must be non-negative")
    if not np.isclose(wd + ws, 1.0, atol=1e-12, rtol=0.0):
        raise ValueError(f"CSI weights must sum to 1; got {wd + ws:.12g}")
    return wd, ws


def compute_csi(demand, supply,
                w_demand: float = config.WEIGHT_DEMAND,
                w_supply: float = config.WEIGHT_SUPPLY):
    """Compound Stress Index = w_demand*demand + w_supply*supply (step 64), elementwise.

    Parameterised for the step-66 unequal-weight sensitivity test (baseline 0.5/0.5).
    With non-negative weights and positive-part inputs, CSI >= 0 (NaN preserved).
    """
    wd, ws = validate_csi_weights(w_demand, w_supply)
    d = np.asarray(demand, dtype="float64")
    s = np.asarray(supply, dtype="float64")
    return wd * d + ws * s


def copula_weights(*args, **kwargs):
    """STUB (sensitivity hook, step 66): copula-derived CSI weights. Raises NotImplementedError; NOT run."""
    # TODO Section 12 step 66: fit a copula to the joint (demand_stress, supply_stress)
    # distribution, derive dependence-aware weights, and re-run compute_csi with them.
    raise NotImplementedError(
        "copula_weights is a Section 12 step-66 sensitivity-test STUB and is not "
        "implemented; the baseline deliverable uses the equal weights "
        f"WEIGHT_DEMAND={config.WEIGHT_DEMAND} / WEIGHT_SUPPLY={config.WEIGHT_SUPPLY}. "
        "See the function docstring (# TODO Section 12 step 66).")


def in_heatwave(ts, window: tuple = HEATWAVE_2023) -> bool:
    """Whether a date lies in the known 2023 Phoenix peak-heat window (delegates to Section 11)."""
    return sec11.in_heatwave(ts, window)


def heatwave_enrichment(times, scores, top_k: int = 11,
                        window: tuple = HEATWAVE_2023) -> dict:
    """Heatwave-window enrichment among the highest scores (delegates to Section 11).

    Robust extreme-date statistic: of the top_k overpasses, the share in the 2023 window
    vs the window's share of all overpasses (>1 == over-represented at the top).
    """
    return sec11.heatwave_enrichment(times, scores, top_k=top_k, window=window)


# --- Loading + assembly (the geo stack) -------------------------------------
def _reference():
    """The 70 m reference grid as a 2-D rioxarray DataArray (the match target/CRS)."""
    return rioxarray.open_rasterio(config.REFERENCE_GRID_TIF).squeeze("band", drop=True)


def load_zscores(processed: Path) -> "xr.Dataset":
    """Open the Section 11 z-score store (the only input) with decode_coords='all'; read vpd_z (demand), sm_z (supply), ndmi_z (check)."""
    store = processed / ZSCORE_ZARR
    if not store.exists():
        raise FileNotFoundError(
            f"Section 11 z-score store not found: {store}. Run section11_anomalies.py first.")
    ds = xr.open_zarr(store, decode_coords="all")
    for v in (DEMAND_Z_VAR, SUPPLY_Z_VAR, CHECK_Z_VAR):
        if v not in ds.data_vars:
            raise AssertionError(f"{ZSCORE_ZARR} is missing the z-score variable {v!r}")
    return ds


def _assert_supply_is_z(arr, var: str, rescaled: bool) -> tuple:
    """Pure numeric core of the supply/check z-score guard (unit-testable, no xarray).

    Returns (mean, std, min, max) on success; raises AssertionError otherwise. Bands:
      - sm_z (config.SUPPLY_VAR), RAW stored field (rescaled=False): WIDER band
        0.3 < std < 1.3 and min < 0 < max. sm_z's real single-year compressed variance
        (std ~0.45) sits below the tight 0.7 band, so the wide band is REQUIRED -- this is
        the documented trap (the old tight band would reject valid sm_z).
      - any supply AFTER robust rescale (rescaled=True): TIGHT band 0.7 < std < 1.3 and
        straddling 0 -- the IQR/1.349 rescale should have restored ~unit spread.
      - the ndmi_z CHECK (rescaled=False, var != SUPPLY_VAR): TIGHT band 0.7 < std < 1.3
        AND a z-like span beyond +/-1 (raw NDMI is bounded in [-1, 1], std ~0.09).
    The mean is NOT checked: these are temporal LOYO anomalies -> one year need not mean 0.
    """
    a = np.asarray(arr, dtype="float64")
    mean = float(np.nanmean(a)); std = float(np.nanstd(a))
    amin = float(np.nanmin(a)); amax = float(np.nanmax(a))
    if rescaled:
        if not (0.7 < std < 1.3):
            raise AssertionError(
                f"{var} (robust-rescaled supply) does not have ~unit spread (std={std:.4f}; "
                "expected 0.7-1.3). The IQR/1.349 rescale should restore ~unit spread before "
                "supply_stress; a failure means the rescale did not take.")
        if not (amin < 0.0 < amax):
            raise AssertionError(
                f"{var} (rescaled) does not straddle 0 (min={amin:+.4f}, max={amax:+.4f}); "
                "a wetness z-score must carry both wet (>0) and dry (<0) values.")
    elif var == config.SUPPLY_VAR:
        # RAW sm_z: WIDE band -- its compressed single-year variance (std ~0.45) fails a
        # tight z band but is still far above any raw physical field. Must straddle 0.
        if not (0.3 < std < 1.3):
            raise AssertionError(
                f"{var} does not look like a soil-moisture z-score (std={std:.4f}; expected "
                f"0.3-1.3; mean={mean:+.4f}). sm_z's real single-year variance is COMPRESSED "
                "(std ~0.45) but far above a raw field; refusing to build supply from a "
                "non-z-score input.")
        if not (amin < 0.0 < amax):
            raise AssertionError(
                f"{var} does not straddle 0 (min={amin:+.4f}, max={amax:+.4f}); a "
                "soil-moisture z-score has both wet (>0) and dry (<0) pixels.")
    else:
        # ndmi_z CHECK: TIGHT z band spanning +/-1 (raw NDMI is bounded [-1,1], std ~0.09).
        if not (0.7 < std < 1.3):
            raise AssertionError(
                f"{var} does not look like a z-score (std={std:.4f}; expected ~1, tol "
                f"0.7-1.3; mean={mean:+.4f}). Raw NDMI (std ~0.09) would fail here.")
        if not (amin < -1.0 and amax > 1.0):
            raise AssertionError(
                f"{var} does not span a z-like range (min={amin:+.4f}, max={amax:+.4f}); a "
                "z-score reaches +/- several sigma, but RAW NDMI is bounded in [-1, 1].")
    return mean, std, amin, amax


def _assert_inputs_are_zscores(zds: "xr.Dataset") -> None:
    """Guard: assert the CSI inputs are Section-11 z-scores, not raw fields (the pitfall).

    Branches on SUPPLY_Z_VAR (config.SUPPLY_VAR) via the pure _assert_supply_is_z helper:
    for sm_z the RAW stored field is accepted with a WIDER band (0.3<std<1.3, straddling 0)
    because sm_z's real single-year variance is compressed (std ~0.45); the ndmi_z CHECK
    keeps the tight NDMI band (0.7<std<1.3, spanning +/-1). vpd_z must straddle 0. Mean is
    NOT checked (temporal LOYO anomalies). Raises AssertionError if inputs look like raw.
    """
    _sm_mean, sm_std, sm_min, sm_max = _assert_supply_is_z(
        zds[SUPPLY_Z_VAR].values, SUPPLY_Z_VAR, rescaled=False)
    _nd_mean, nd_std, nd_min, nd_max = _assert_supply_is_z(
        zds[CHECK_Z_VAR].values, CHECK_Z_VAR, rescaled=False)
    vd = zds[DEMAND_Z_VAR].values
    vd_min = float(np.nanmin(vd)); vd_max = float(np.nanmax(vd))
    if not (vd_min < 0.0 < vd_max):
        raise AssertionError(
            f"{DEMAND_Z_VAR} does not look like a z-score (min={vd_min:+.4f}, "
            f"max={vd_max:+.4f}; a z-score straddles 0, raw VPD in kPa is >= 0). "
            "Refusing to build the demand stress from raw VPD.")
    log.info("INPUT CHECK: CSI inputs are Section-11 Z-SCORES, not raw values -> "
             "SUPPLY %s std=%.4f (wide band 0.3-1.3: sm_z single-year variance is "
             "COMPRESSED) range [%+.2f, %+.2f] straddling 0; CHECK %s std=%.4f (~1) "
             "range [%+.2f, %+.2f] (z-like, NOT bounded in [-1,1]); %s straddles 0 "
             "(min=%+.4f max=%+.4f). Raw VPD/SM/NDMI are NOT used.",
             SUPPLY_Z_VAR, sm_std, sm_min, sm_max, CHECK_Z_VAR, nd_std, nd_min, nd_max,
             DEMAND_Z_VAR, vd_min, vd_max)


def _blosc():
    import numcodecs
    return numcodecs.Blosc(cname="zstd", clevel=5, shuffle=numcodecs.Blosc.SHUFFLE)


def build_csi_dataset(processed: Path, reference: "xr.DataArray"
                      ) -> tuple["xr.Dataset", dict]:
    """Build the (overpass, y, x) CSI + component cube from the Section 11 z-scores.

    Returns (dataset, meta) where meta carries the weights, the supply-varies-in-time
    flag and the CSI stats for the QC note / report.
    """
    zds = load_zscores(processed)
    _assert_inputs_are_zscores(zds)

    n = zds.sizes["overpass"]
    log.info("Building CSI from Section 11 z-scores: %d overpasses, grid (y=%d, x=%d)",
             n, zds.sizes["y"], zds.sizes["x"])
    log.info("  DEMAND = max(%s, 0)  [time-varying];  SUPPLY = max(-%s, 0)  "
             "[SOIL-MOISTURE supply; %s is a TEMPORAL day-of-year LOYO anomaly, Section 11; "
             "robust-rescaled to ~unit spread before supply_stress]  (BLOCKER B1a)",
             DEMAND_Z_VAR, SUPPLY_Z_VAR, SUPPLY_Z_VAR)
    log.info("  Baseline EQUAL weights: WEIGHT_DEMAND=%.3f  WEIGHT_SUPPLY=%.3f (step 64)",
             config.WEIGHT_DEMAND, config.WEIGHT_SUPPLY)

    vpd_z = zds[DEMAND_Z_VAR].values.astype("float64")        # (overpass, y, x), time-varying
    supply_z = zds[SUPPLY_Z_VAR].values.astype("float64")     # sm_z (overpass, y, x), time-varying
    ndmi_check = zds[CHECK_Z_VAR].values.astype("float64")    # VEGETATION CHECK only (kept out of the cube)

    # BLOCKER B1a: robust-rescale sm_z to ~unit spread (IQR/1.349) BEFORE supply_stress so its
    # real compressed single-year variance (std ~0.45) does not silently de-weight supply
    # against the ~unit-std demand term. supply_stress = max(-z, 0) is sign-correct for any
    # wetness z (positive sm_z = wet = low stress), so it works for sm_z unchanged.
    if config.SUPPLY_ROBUST_RESCALE:
        supply_z = robust_unit_scale(supply_z)
        _assert_supply_is_z(supply_z, SUPPLY_Z_VAR, rescaled=True)   # post-rescale ~unit spread
        log.info("  SUPPLY robust-rescaled: %s / (IQR/1.349) -> nanstd=%.4f (~1; raw sm_z ~0.45)",
                 SUPPLY_Z_VAR, float(np.nanstd(supply_z)))

    demand = demand_stress(vpd_z).astype("float32")           # max(vpd_z, 0)
    supply = supply_stress(supply_z).astype("float32")        # max(-sm_z, 0)  [rescaled sm_z]
    csi = compute_csi(demand, supply,
                      config.WEIGHT_DEMAND, config.WEIGHT_SUPPLY).astype("float32")

    # ndmi_z VEGETATION CHECK: keep per-overpass spatial mean only (carried in the summary
    # for corroboration). It is NOT in the csi/demand_stress/supply_stress cube -- the CSI
    # supply axis is sm_z (BLOCKER B1a), so verify_grid's cube assertions are unchanged.
    ndmi_check_op_mean = np.nanmean(ndmi_check.reshape(n, -1), axis=1).astype("float64")

    # Cheap invariant documenting decision A in the data: the std across overpasses of the
    # per-overpass spatial-mean supply must be > 0 (the OLD static supply gave exactly 0).
    sup_op_mean = np.nanmean(supply.reshape(n, -1), axis=1)   # spatial-mean per overpass
    supply_varies_std = float(np.nanstd(sup_op_mean))
    supply_time_varying = supply_varies_std > 1e-6
    log.info("  supply_stress VARIES across overpasses: %s "
             "(std of per-overpass spatial-mean supply = %.4f; OLD static supply = 0) "
             "-- decision A", supply_time_varying, supply_varies_std)

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
        # ndmi_z VEGETATION CHECK spatial mean per overpass (1-D; NOT part of the y,x cube).
        "ndmi_z_check_spatial_mean": ("overpass", ndmi_check_op_mean),
        "y": reference.y.values,
        "x": reference.x.values,
    }
    ds = xr.Dataset(data_vars, coords=coords)
    ds = ds.rio.write_crs(reference.rio.crs)
    for v in ds.data_vars:
        if {"y", "x"} <= set(ds[v].dims):
            ds[v].attrs["grid_mapping"] = "spatial_ref"
    _annotate(ds, supply_time_varying, supply_varies_std)
    zds.close()

    finite = np.isfinite(csi)
    n_finite = int(finite.sum())
    n_total = int(csi.size)
    meta = {
        "n_overpass": n,
        "w_demand": float(config.WEIGHT_DEMAND),
        "w_supply": float(config.WEIGHT_SUPPLY),
        "supply_time_varying": supply_time_varying,
        "supply_varies_std": supply_varies_std,
        "csi_min": float(np.nanmin(csi)), "csi_mean": float(np.nanmean(csi)),
        "csi_max": float(np.nanmax(csi)),
        "n_finite": n_finite, "n_total": n_total,
        "frac_finite": n_finite / n_total if n_total else float("nan"),
        "csi_ge_zero": bool(np.all(csi[finite] >= 0.0)),
    }
    return ds, meta


def _annotate(ds: "xr.Dataset", supply_time_varying: bool,
              supply_varies_std: float) -> None:
    """Attach units / methodology provenance to the CSI variables + dataset."""
    notes = {
        "csi": "Compound Stress Index (baseline, equal weights): "
               "CSI = WEIGHT_DEMAND*max(vpd_z,0) + WEIGHT_SUPPLY*max(-sm_z,0) "
               "(steps 62-64), where sm_z is robust-rescaled (IQR/1.349) to ~unit spread. "
               ">= 0 everywhere; near 0 = near normal, large = a compound heat-drought "
               "extreme. Varies in BOTH space and time from BOTH the demand and supply "
               "terms. Built from Section 11 z-scores: VPD demand + SOIL-MOISTURE supply "
               "(NOT raw fields, and NOT ndmi_z -- the supply axis is soil moisture, "
               "BLOCKER B1a; CSI is now a SECONDARY cross-city scalar, the Section 15 "
               "response surface being the primary RQ1 detector).",
        "demand_stress": "Demand stress = positive part of the VPD z-score, "
                         "max(vpd_z, 0) (step 62). Time-varying. Only above-normal "
                         "VPD is stressful.",
        "supply_stress": "Supply stress = positive part of the NEGATED SOIL-MOISTURE "
                         "z-score, max(-sm_z, 0) (step 63), with sm_z robust-rescaled "
                         "(IQR/1.349) to ~unit spread so its compressed single-year "
                         "variance does not de-weight the supply axis. Low soil moisture "
                         "-> positive stress. TIME-VARYING (and space-varying): sm_z is a "
                         "TEMPORAL day-of-year leave-one-year-out anomaly (Section 11). "
                         "NDMI is carried separately as a VEGETATION CHECK only "
                         "(ndmi_z_check_spatial_mean in the summary), not as supply.",
    }
    for v, note in notes.items():
        if v in ds:
            ds[v].attrs["long_name"] = note
            ds[v].attrs["units"] = "1"            # standardized / dimensionless
    ds.attrs["title"] = ("Section 12: Compound Stress Index (CSI) from the VPD demand & "
                         "SOIL-MOISTURE supply z-scores, baseline equal weights (steps 62-66)")
    ds.attrs["crs"] = config.CRS
    ds.attrs["weight_demand"] = float(config.WEIGHT_DEMAND)
    ds.attrs["weight_supply"] = float(config.WEIGHT_SUPPLY)
    ds.attrs["supply_var"] = str(config.SUPPLY_VAR)          # sm_z (BLOCKER B1a)
    ds.attrs["check_var"] = str(CHECK_Z_VAR)                 # ndmi_z vegetation check only
    ds.attrs["method"] = ("demand=max(vpd_z,0) (step 62); supply=max(-sm_z,0) with sm_z "
                          "robust-rescaled to ~unit spread (IQR/1.349) (step 63); "
                          "CSI=WEIGHT_DEMAND*demand+WEIGHT_SUPPLY*supply (step 64, baseline "
                          "equal weights 0.5/0.5). Supply axis is SOIL MOISTURE (sm_z), NOT "
                          "ndmi_z (a vegetation check); inputs are Section 11 z-scores, "
                          "never raw fields (BLOCKER B1a).")
    ds.attrs["supply_stress_time_varying"] = str(supply_time_varying)
    ds.attrs["supply_stress_overpass_mean_std"] = float(supply_varies_std)
    ds.attrs["note_supply_time_varying"] = (
        "supply_stress now VARIES across overpasses (std of the per-overpass "
        f"spatial-mean supply = {supply_varies_std:.4f}; was exactly 0 under the OLD "
        "static spatial standardization) because sm_z is a TEMPORAL day-of-year "
        "leave-one-year-out anomaly (Section 11). Consequence: the CSI varies in both "
        "space and time from BOTH the demand and supply terms, so the temporal ranking "
        "of spatial-mean CSI is no longer identical to the VPD-demand ranking.")
    ds.attrs["weight_sensitivity"] = (
        "EXECUTED in section12_weight_sensitivity.parquet for convex demand/supply pairs "
        "(0/1, 0.3/0.7, 0.5/0.5, 0.7/0.3, 1/0); all scenarios reuse these exact "
        "demand_stress and supply_stress arrays and a common finite mask.")
    ds.attrs["copula_sensitivity"] = (
        "NOT RUN: copula_weights() remains an explicit NotImplementedError because no "
        "defensible copula estimator was pre-specified. No data-driven weights are implied.")


def write_csi_zarr(ds: "xr.Dataset", store: Path) -> Path:
    """Write the CSI + component cube to a compressed, chunked Zarr (one overpass per chunk). Overwrites."""
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


# --- QC (step 65 + the deliverable confirmation) ----------------------------
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
    log.info("  supply_stress  min=%.4f  max=%.4f  [max(-sm_z,0), soil moisture, time-varying]",
             smin, smax)
    return {"csi_min": cmin, "csi_mean": cmean, "csi_max": cmax, "csi_ge_zero": ge0,
            "n_finite": n_finite, "n_total": n_total, "frac_finite": frac,
            "demand_min": dmin, "demand_max": dmax, "supply_min": smin, "supply_max": smax}


def extreme_csi_dates(ds: "xr.Dataset", top_n: int = 10) -> tuple[pd.DataFrame, dict, dict]:
    """Rank overpasses by spatial-mean CSI and confirm the top dates fall in summer-2023 (step 65).

    Whether the CSI ranking still equals the VPD-demand ranking is REPORTED, not assumed
    (the supply term now varies in time, decision A). Returns (ranked DataFrame,
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

    # Identical under the OLD static supply; with the supply now time-varying they may
    # diverge -- so this is an OBSERVATION, not an invariant.
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
             "(supply now varies in time -> the two orderings need NOT match)", rank_match)
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
    """Small 66-row per-overpass summary: spatial-mean csi/demand/supply + the ndmi_z
    VEGETATION CHECK spatial mean + flags. ndmi_z is corroboration only (BLOCKER B1a: the
    CSI supply axis is sm_z), so it is NOT in the csi/demand/supply cube."""
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
    # ndmi_z VEGETATION CHECK spatial mean (carried as a 1-D coord, NOT part of the cube).
    if "ndmi_z_check_spatial_mean" in ds.variables:
        rec["ndmi_z_check_spatial_mean"] = np.asarray(ds["ndmi_z_check_spatial_mean"].values)
    df = pd.DataFrame(rec)
    return df.sort_values("csi_spatial_mean", ascending=False).reset_index(drop=True)


def _weight_scenario_label(w_demand: float, w_supply: float) -> str:
    """Stable human-readable label for the five predeclared weight scenarios."""
    if np.isclose(w_demand, 0.0):
        return "pure_supply"
    if np.isclose(w_supply, 0.0):
        return "pure_demand"
    if np.isclose(w_demand, w_supply):
        return "equal_baseline"
    return "demand_heavy" if w_demand > w_supply else "supply_heavy"


def run_weight_sensitivity(
    ds: "xr.Dataset",
    weight_grid: Sequence[tuple[float, float]] | None = None,
) -> pd.DataFrame:
    """Execute the predeclared unequal-weight CSI sensitivity on the saved components.

    Every scenario uses the same demand/supply arrays and therefore the same common finite
    mask. One row records its whole-domain CSI distribution, per-overpass temporal ranking,
    top dates, and enrichment in the fixed 2023 heatwave window. The equal 0.5/0.5 scenario
    is checked against the saved baseline cube so a stale or differently computed baseline
    cannot pass silently.
    """
    pairs = tuple(DEFAULT_WEIGHT_GRID if weight_grid is None else weight_grid)
    if not pairs:
        raise ValueError("weight_grid must contain at least one scenario")
    checked = [validate_csi_weights(wd, ws) for wd, ws in pairs]
    if len(set(checked)) != len(checked):
        raise ValueError("weight_grid contains duplicate scenarios")
    if (float(config.WEIGHT_DEMAND), float(config.WEIGHT_SUPPLY)) not in checked:
        raise ValueError("weight_grid must include the configured equal-weight baseline")

    demand = np.asarray(ds["demand_stress"].values, dtype="float64")
    supply = np.asarray(ds["supply_stress"].values, dtype="float64")
    if demand.shape != supply.shape:
        raise ValueError("demand_stress and supply_stress shapes differ")
    times = pd.to_datetime(ds["time"].values)
    keys = np.asarray([str(k) for k in ds["overpass_key"].values], dtype=object)

    baseline = compute_csi(demand, supply, config.WEIGHT_DEMAND, config.WEIGHT_SUPPLY)
    baseline_scores = np.nanmean(baseline.reshape(baseline.shape[0], -1), axis=1)
    baseline_order = np.argsort(np.where(np.isfinite(baseline_scores), baseline_scores, -np.inf))[::-1]
    baseline_top10 = set(keys[baseline_order[:10]].tolist())
    saved = np.asarray(ds["csi"].values, dtype="float64")
    common = np.isfinite(saved) & np.isfinite(baseline)
    baseline_max_abs_diff = (float(np.max(np.abs(saved[common] - baseline[common])))
                             if common.any() else float("nan"))
    if not np.isfinite(baseline_max_abs_diff) or baseline_max_abs_diff > 1e-6:
        raise AssertionError(
            "recomputed 0.5/0.5 CSI does not reproduce the saved baseline cube "
            f"(max absolute difference={baseline_max_abs_diff})")

    rows: list[dict] = []
    for wd, ws in checked:
        csi = compute_csi(demand, supply, wd, ws)
        scores = np.nanmean(csi.reshape(csi.shape[0], -1), axis=1)
        order = np.argsort(np.where(np.isfinite(scores), scores, -np.inf))[::-1]
        top10_idx = order[:10]
        enrichment = heatwave_enrichment(times, scores, top_k=11)
        rank_corr = pd.Series(scores).corr(pd.Series(baseline_scores), method="spearman")
        finite = np.isfinite(csi)
        rows.append({
            "scenario": _weight_scenario_label(wd, ws),
            "w_demand": wd,
            "w_supply": ws,
            "n_overpasses": int(scores.size),
            "n_finite_cells": int(finite.sum()),
            "csi_spatial_mean_all": float(np.nanmean(csi)),
            "csi_spatial_std_all": float(np.nanstd(csi)),
            "csi_spatial_max": float(np.nanmax(csi)),
            "overpass_rank_spearman_vs_equal": float(rank_corr),
            "top10_overlap_with_equal": int(len(set(keys[top10_idx].tolist()) & baseline_top10)),
            "top_overpass_key": str(keys[order[0]]),
            "top_overpass_time": pd.Timestamp(times[order[0]]),
            "top_overpass_csi_mean": float(scores[order[0]]),
            "top10_overpass_keys": "|".join(str(keys[i]) for i in top10_idx),
            "heatwave_top_k": int(enrichment["top_k"]),
            "heatwave_top_fraction": float(enrichment["top_frac"]),
            "heatwave_enrichment": float(enrichment["enrichment"]),
            "baseline_max_abs_diff": baseline_max_abs_diff if np.isclose(wd, 0.5) else np.nan,
        })
    return pd.DataFrame(rows)


def write_weight_sensitivity(ds: "xr.Dataset", out_path: Path) -> Path:
    """Run and persist the executed step-66 unequal-weight sensitivity."""
    table = run_weight_sensitivity(ds)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out_path, index=False)
    log.info("Wrote unequal-weight sensitivity -> %s (%d scenarios)", out_path, len(table))
    for _, row in table.iterrows():
        log.info("  %-14s demand/supply=%.1f/%.1f  rank rho=%+.3f  top10 overlap=%d/10  "
                 "heatwave enrichment=%.2fx",
                 row["scenario"], row["w_demand"], row["w_supply"],
                 row["overpass_rank_spearman_vs_equal"], row["top10_overlap_with_equal"],
                 row["heatwave_enrichment"])
    return out_path


# --- Figures (deliverable QC) -----------------------------------------------
def make_distribution_figure(ds: "xr.Dataset", extreme_df: pd.DataFrame,
                             enr_csi: dict, figures_dir: Path) -> Path:
    """CSI distribution + components (L) and the spatial-mean CSI per overpass with the 2023 window shaded (R)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(15, 5.4), constrained_layout=True)

    # (L) CSI distribution + components.
    csi = ds["csi"].values
    csi_flat = csi[np.isfinite(csi)]
    dem = ds["demand_stress"].values
    dem_flat = dem[np.isfinite(dem)]
    sup = ds["supply_stress"].values
    sup_flat = sup[np.isfinite(sup)]
    cmean = float(np.mean(csi_flat)); cmax = float(np.max(csi_flat))
    # Step-OUTLINE histograms on a SHARED bin grid: filled bars blend into muddy colors
    # where the three distributions overlap near 0 (where almost all mass sits).
    hi = float(max(csi_flat.max(), dem_flat.max(), sup_flat.max()))
    bins = np.linspace(0.0, hi, 91)
    axL.hist(csi_flat, bins=bins, histtype="step", color=ps.ACCENT["csi"], lw=1.9,
             label="CSI (all pixel-overpasses)")
    axL.hist(dem_flat, bins=bins, histtype="step", color=ps.ACCENT["vpd"], lw=1.4,
             label="demand = max(vpd_z,0)")
    axL.hist(sup_flat, bins=bins, histtype="step", color=ps.ACCENT["ndmi"], lw=1.4,
             label="supply = max(-sm_z,0)  (soil moisture, time-varying)")
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
    # Robust display cap (99th pct) so one outlier pixel doesn't wash out the stress ramp.
    vmax = float(np.nanpercentile(arr, 99)) if np.isfinite(arr).any() else 1.0
    vmax = max(vmax, 0.5)
    # CSI is a non-negative stress field: sequential ramp that is WHITE at 0 (no stress).
    im = ax.imshow(arr, extent=extent, origin="upper", cmap=ps.CMAP["stress"], vmin=0.0, vmax=vmax)
    fig.colorbar(im, ax=ax, shrink=0.85, label="Compound Stress Index (>= 0)")
    ax.set_title(f"Section 12: Compound Stress Index, highest-CSI overpass\n{ts:%Y-%m-%d %H:%M} UTC "
                 f"(spatial-mean CSI = {extreme_df.iloc[0]['csi_mean']:.3f}; "
                 f"{'in' if in_heatwave(ts) else 'NOT in'} the 2023 heatwave window)")
    ax.set_xlabel("Easting (m, EPSG:32612)"); ax.set_ylabel("Northing (m)")
    out = figures_dir / FIG_EXTREME
    fig.savefig(out, dpi=150, bbox_inches="tight"); plt.close(fig)
    log.info("Wrote figure -> %s  (overpass %s, %s)", out.name, top_key, ts)
    return out


# --- Verification (re-open + assert geometry == reference_grid.tif) ----------
def verify_grid(store: Path, reference: "xr.DataArray") -> "xr.Dataset":
    """Re-open the saved store and ASSERT its geometry matches reference_grid.tif (+ CSI >= 0, supply varies in time)."""
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
    # supply_stress must VARY across overpasses (decision A: sm_z is a temporal
    # anomaly) -- the opposite of the OLD static-supply invariant.
    sup_op_mean = ds["supply_stress"].mean(dim=("y", "x"), skipna=True).values
    supply_varies_std = float(np.nanstd(sup_op_mean))
    assert supply_varies_std > 1e-6, (
        "supply_stress must VARY across overpasses now that sm_z is a temporal "
        f"anomaly (std of per-overpass spatial-mean supply = {supply_varies_std:.6f}, "
        "expected > 0; a flat supply would mean the temporal sm_z did not propagate)")
    log.info("  ASSERTIONS PASSED: geometry == reference_grid.tif; 66 overpasses; "
             "csi/demand/supply present & float; CSI >= 0 everywhere; supply VARIES in "
             "time (per-overpass spatial-mean supply std = %.4f).", supply_varies_std)
    return ds


# --- Orchestration / CLI ----------------------------------------------------
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
    results["weight_sensitivity"] = write_weight_sensitivity(
        ds, processed / WEIGHT_SENSITIVITY_PARQUET)

    if make_figures:
        results["fig_dist"] = make_distribution_figure(ds, extreme_df, enr_csi, config.FIGURES_DIR)
        results["fig_extreme"] = make_extreme_date_map(ds, extreme_df, config.FIGURES_DIR)

    _report_sensitivity_hooks()
    _report(results)
    ds.close()
    return results


def _report_sensitivity_hooks() -> None:
    """Report the executed deterministic sensitivity and explicit copula non-implementation."""
    log.info("=" * 70)
    log.info("SENSITIVITY (step 66):")
    log.info("  baseline weights: WEIGHT_DEMAND=%.3f  WEIGHT_SUPPLY=%.3f (config.py)",
             config.WEIGHT_DEMAND, config.WEIGHT_SUPPLY)
    log.info("  (a) deterministic unequal-weight sensitivity EXECUTED for %d convex pairs; "
             "see %s.", len(DEFAULT_WEIGHT_GRID), WEIGHT_SENSITIVITY_PARQUET)
    # Confirm the copula stub raises rather than returning invented numbers.
    try:
        copula_weights()
        stub_ok = False
    except NotImplementedError:
        stub_ok = True
    log.info("  (b) copula_weights() is intentionally NOT IMPLEMENTED or executed: no "
             "defensible estimator was pre-specified; raises as expected = %s.", stub_ok)


def _report(results: dict) -> None:
    log.info("=" * 70)
    log.info("Section 12 complete. Deliverables (data/processed/):")
    for key in ("csi_zarr", "overpass_summary", "weight_sensitivity"):
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
                    "Section 11 VPD demand & soil-moisture (sm_z) supply z-scores, "
                    "baseline equal weights (steps 62-66).")
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
