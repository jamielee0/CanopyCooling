#!/usr/bin/env python3
"""Self-test for the Section 13 master-table pipeline (pure-logic).

Mirrors test_section2-12_*: the geo stack (rioxarray, xarray, rasterio, geopandas)
is stubbed so the module imports with only numpy + pandas, then the algorithmically
risky PURE logic is exercised on tiny SYNTHETIC arrays (NO network, NO full Zarr,
NO grid IO):

  * the COOLING ADVANTAGE identity = mean_LST(reference) - mean_LST(tree), including a
    NEGATIVE case (trees warmer than reference -> a negative cooling advantage, which
    is a real outcome, NOT clipped)                                          (step 67)
  * the ZONAL MEAN over a class mask: mean over the masked-AND-finite cells only, with
    the correct n_valid sample size, and NaN/0 when nothing is both masked and finite
  * the ROW-EMISSION rule: a row is emitted ONLY if there is >=1 finite-LST tree pixel
    AND >=1 finite-LST reference pixel (so both step-67 means exist)
  * the IRRIGATION-PROXY formula + normalization: min-max normalize each of
    {turf_fraction, income, 1 - impervious_fraction} across neighborhoods, equal-weight
    mean -> [0,1]; the monotonic directions (more turf / higher income / less impervious
    -> higher proxy); the all-equal-component edge case                       (step 70)
  * the FUNCTIONAL-TYPE modal aggregation: the most frequent non-null label, deterministic
    tie-break, and 'unknown' when a BG has no inventory trees                 (step 68/69)

The Zarr/raster/vector load, the GEOID rasterization, the spatial join and the parquet
write are standard library usage exercised by the real CLI in the canopy environment
(and by the end-to-end run), not re-implemented here.

Runs with just numpy + pandas:  python src/test_section13_master_table.py
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd


def _install_geo_stubs() -> None:
    """Stub the heavy top-level imports so the module imports with only numpy + pandas."""
    for name in ("rioxarray", "xarray", "geopandas"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["rioxarray"].open_rasterio = lambda *a, **k: None  # type: ignore[attr-defined]
    if not hasattr(sys.modules["xarray"], "Dataset"):
        sys.modules["xarray"].Dataset = object             # type: ignore[attr-defined]
        sys.modules["xarray"].DataArray = object            # type: ignore[attr-defined]
        sys.modules["xarray"].open_zarr = lambda *a, **k: None  # type: ignore[attr-defined]
    if not hasattr(sys.modules["geopandas"], "read_parquet"):
        sys.modules["geopandas"].read_parquet = lambda *a, **k: None  # type: ignore[attr-defined]
        sys.modules["geopandas"].GeoDataFrame = object      # type: ignore[attr-defined]
    # rasterio.features + rasterio.transform.Affine are imported at module top level.
    if "rasterio" not in sys.modules:
        sys.modules["rasterio"] = types.ModuleType("rasterio")
    if "rasterio.features" not in sys.modules:
        feats = types.ModuleType("rasterio.features")
        feats.rasterize = lambda *a, **k: None             # type: ignore[attr-defined]
        sys.modules["rasterio.features"] = feats
        sys.modules["rasterio"].features = feats           # type: ignore[attr-defined]
    if "rasterio.transform" not in sys.modules:
        tr = types.ModuleType("rasterio.transform")

        class _Affine(tuple):
            def __new__(cls, *args):
                return super().__new__(cls, args)

        tr.Affine = _Affine                                # type: ignore[attr-defined]
        sys.modules["rasterio.transform"] = tr
        sys.modules["rasterio"].transform = tr             # type: ignore[attr-defined]


_install_geo_stubs()

sys.path.insert(0, str(Path(__file__).resolve().parent))
sec13 = importlib.import_module("section13_master_table")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


# --------------------------------------------------------------------------- #
# 1. cooling advantage = ref mean - tree mean, incl. a NEGATIVE case (step 67).
# --------------------------------------------------------------------------- #
def test_cooling_advantage_identity_and_negative() -> None:
    print("\n[cooling_advantage = mean_LST(reference) - mean_LST(tree) (step 67)]")
    # Trees cooler than reference -> positive cooling advantage (the expected effect).
    ca = sec13.cooling_advantage(315.0, 308.0)
    check(abs(ca - 7.0) < 1e-9, "ref 315 K, tree 308 K -> cooling_advantage = +7.0 K (trees cooler)")
    # Equal -> the benefit is gone (near zero).
    check(abs(sec13.cooling_advantage(310.0, 310.0)) < 1e-9,
          "equal tree/reference -> cooling_advantage = 0 (benefit gone)")
    # NEGATIVE case: trees WARMER than reference -> negative (a real outcome, NOT clipped).
    can = sec13.cooling_advantage(305.0, 309.0)
    check(abs(can + 4.0) < 1e-9, "ref 305 K, tree 309 K -> cooling_advantage = -4.0 K (NOT clipped)")
    check(can < 0.0, "a negative cooling advantage is returned as-is (negatives allowed)")
    # NaN if either mean is NaN.
    check(np.isnan(sec13.cooling_advantage(np.nan, 300.0)),
          "NaN reference mean -> NaN cooling advantage")


# --------------------------------------------------------------------------- #
# 2. zonal mean over a class mask (the per-overpass tree/reference averaging).
# --------------------------------------------------------------------------- #
def test_zonal_mean_over_mask() -> None:
    print("\n[zonal_mean: mean over masked-AND-finite cells, with the n_valid sample size]")
    vals = np.array([[300.0, 310.0, np.nan],
                     [320.0, np.nan, 330.0]])
    mask = np.array([[True, True, True],
                     [False, True, True]])
    m, n = sec13.zonal_mean(vals, mask)
    # masked & finite cells: 300, 310, 330 (the [1,1] NaN and the unmasked 320 excluded).
    check(abs(m - (300.0 + 310.0 + 330.0) / 3.0) < 1e-9,
          "mean is over masked cells with FINITE values only (NaNs in-mask ignored)")
    check(n == 3, "n_valid counts the masked-and-finite cells (=3), not all masked (=4)")
    # nothing masked-and-finite -> (NaN, 0).
    allnan = np.array([np.nan, np.nan])
    m0, n0 = sec13.zonal_mean(allnan, np.array([True, True]))
    check(np.isnan(m0) and n0 == 0, "all-NaN inside the mask -> (NaN, 0)")
    m1, n1 = sec13.zonal_mean(np.array([1.0, 2.0]), np.array([False, False]))
    check(np.isnan(m1) and n1 == 0, "empty mask -> (NaN, 0)")


# --------------------------------------------------------------------------- #
# 3. the row-emission rule (need BOTH groups finite that overpass).
# --------------------------------------------------------------------------- #
def test_row_emission_rule() -> None:
    print("\n[row_emittable: >=1 finite-LST tree px AND >=1 finite-LST reference px]")
    check(sec13.row_emittable(1, 1), "1 tree + 1 reference -> emit")
    check(sec13.row_emittable(171, 800), "many tree + many reference -> emit")
    check(not sec13.row_emittable(0, 500), "0 tree (but reference present) -> DROP (no tree mean)")
    check(not sec13.row_emittable(5, 0), "0 reference (but tree present) -> DROP (no reference mean)")
    check(not sec13.row_emittable(0, 0), "neither group finite -> DROP")


# --------------------------------------------------------------------------- #
# 4. irrigation-proxy formula + normalization (step 70).
# --------------------------------------------------------------------------- #
def test_normalize_unit() -> None:
    print("\n[normalize_unit: min-max to [0,1] across neighborhoods]")
    out = sec13.normalize_unit(np.array([10.0, 20.0, 30.0]))
    check(np.allclose(out, [0.0, 0.5, 1.0]), "min->0, max->1, midpoint->0.5")
    # all-equal -> all 0.0 (no spread to rank on).
    eq = sec13.normalize_unit(np.array([5.0, 5.0, 5.0]))
    check(np.allclose(eq, [0.0, 0.0, 0.0]), "all-equal components normalize to 0 (no spread)")
    check(np.all((out >= 0) & (out <= 1)), "normalized values lie in [0,1]")


def test_irrigation_proxy_formula() -> None:
    print("\n[irrigation_proxy = mean(norm(turf), norm(income), norm(1-impervious)) (step 70)]")
    # 3 neighborhoods. Construct so each component's ranking is clear.
    turf = np.array([0.0, 0.1, 0.2])         # increasing turf
    income = np.array([30000.0, 60000.0, 90000.0])  # increasing income
    imperv_frac = np.array([0.8, 0.5, 0.2])  # decreasing impervious -> increasing (1-imperv)
    proxy = sec13.irrigation_proxy(turf, income, imperv_frac)
    # Every component increases monotonically with the neighborhood index, so the proxy
    # must be monotonically increasing too, and span [0,1] (all three are aligned).
    check(np.all(np.diff(proxy) > 0), "proxy increases when turf, income & perviousness all increase")
    check(abs(proxy[0] - 0.0) < 1e-9 and abs(proxy[2] - 1.0) < 1e-9,
          "with all components aligned, the proxy spans 0..1 (equal-weight mean of three 0..1 norms)")
    # Direction checks via one-hot perturbations against a flat baseline.
    flat_turf = np.array([0.1, 0.1]); flat_inc = np.array([5e4, 5e4])
    base_imp = np.array([0.5, 0.5])
    # higher turf alone -> higher proxy
    p_turf = sec13.irrigation_proxy(np.array([0.0, 0.3]), flat_inc, base_imp)
    check(p_turf[1] > p_turf[0], "more turf alone -> higher irrigation proxy")
    # higher income alone -> higher proxy
    p_inc = sec13.irrigation_proxy(flat_turf, np.array([3e4, 9e4]), base_imp)
    check(p_inc[1] > p_inc[0], "higher income alone -> higher irrigation proxy")
    # LESS impervious alone -> higher proxy (1 - impervious_fraction)
    p_imp = sec13.irrigation_proxy(flat_turf, flat_inc, np.array([0.9, 0.1]))
    check(p_imp[1] > p_imp[0], "less impervious (more pervious) alone -> higher irrigation proxy")
    # result bounded in [0,1]
    check(np.all((proxy >= -1e-9) & (proxy <= 1 + 1e-9)), "irrigation_proxy lies in [0,1]")


def test_irrigation_proxy_equal_weight_value() -> None:
    print("\n[irrigation_proxy is the EQUAL-weight (1/3 each) mean of the three norms]")
    # Two neighborhoods so each norm is exactly {0,1}; the proxy is then the mean of the
    # three 0/1 norms -> a multiple of 1/3, which pins the equal weighting precisely.
    turf = np.array([1.0, 0.0])              # norm -> [1, 0]
    income = np.array([0.0, 1.0])            # norm -> [0, 1]
    imperv_frac = np.array([0.0, 1.0])       # 1-imp = [1,0] -> norm -> [1, 0]
    proxy = sec13.irrigation_proxy(turf, income, imperv_frac)
    # neigh0: (1 + 0 + 1)/3 = 2/3 ; neigh1: (0 + 1 + 0)/3 = 1/3
    check(np.allclose(proxy, [2.0 / 3.0, 1.0 / 3.0]),
          "proxy = (turf_norm + income_norm + low_imperv_norm)/3 (equal 1/3 weights)")


# --------------------------------------------------------------------------- #
# 5. functional-type modal aggregation (step 68/69 modifier).
# --------------------------------------------------------------------------- #
def test_modal_functional_type() -> None:
    print("\n[modal_functional_type: dominant label; 'unknown' when no trees]")
    check(sec13.modal_functional_type(
        ["mesic", "mesic", "drought_tolerant"]) == "mesic",
        "the most frequent label (mesic 2 vs drought_tolerant 1) wins")
    # empty / all-null -> unknown (a BG with no inventory trees).
    check(sec13.modal_functional_type([]) == sec13.FUNCTIONAL_UNKNOWN,
          "no inventory trees -> 'unknown'")
    check(sec13.modal_functional_type([None, np.nan]) == sec13.FUNCTIONAL_UNKNOWN,
          "all-null labels -> 'unknown'")
    # null values are dropped before the mode.
    check(sec13.modal_functional_type(
        ["drought_tolerant", None, "drought_tolerant", np.nan]) == "drought_tolerant",
        "nulls are ignored; the modal non-null label wins")
    # deterministic tie-break: 50/50 -> alphabetically-first label.
    tie = sec13.modal_functional_type(["mesic", "drought_tolerant"])
    check(tie == "drought_tolerant",
          "a tie is broken deterministically by the alphabetically-first label")


# --------------------------------------------------------------------------- #
# 6. module constants / schema sanity (cheap guards on the deliverable contract).
# --------------------------------------------------------------------------- #
def test_module_constants_and_schema() -> None:
    print("\n[module constants + master-table schema contract]")
    check(sec13.MASTER_PARQUET == "master_table.parquet",
          "the deliverable is data/processed/master_table.parquet (step 71)")
    check(sec13.CLASS_TREE == 1 and sec13.CLASS_REFERENCE == 2,
          "the Section 10 class codes match (1=tree, 2=reference)")
    check(sec13.WATER_SUPPLY_Z_VAR == "ndmi_z" and sec13.VPD_Z_VAR == "vpd_z",
          "the water-supply z is ndmi_z and the demand z is vpd_z (Section 11 names)")
    check(sec13.CITY == "Phoenix", "city identifier is 'Phoenix'")
    # every protocol column GROUP maps only to columns that exist in MASTER_COLUMNS.
    for grp, cols in sec13.COLUMN_GROUPS.items():
        for c in cols:
            check(c in sec13.MASTER_COLUMNS, f"column-group {grp!r} member {c!r} is in MASTER_COLUMNS")
    # the canonical column list has no duplicates and leads with the identifiers.
    check(len(sec13.MASTER_COLUMNS) == len(set(sec13.MASTER_COLUMNS)),
          "MASTER_COLUMNS has no duplicate column names")
    check(sec13.MASTER_COLUMNS[:4] == ["neighborhood_id", "overpass_timestamp",
                                       "overpass_key", "city"],
          "MASTER_COLUMNS leads with the identifier group")
    check("n_good_obs" in sec13.MASTER_COLUMNS and "n_tree_px" in sec13.MASTER_COLUMNS
          and "n_ref_px" in sec13.MASTER_COLUMNS,
          "the pixel-count columns are retained (for the Section 14 minimum-count filter)")


# --------------------------------------------------------------------------- #
# Direct runner (parity with the sibling test modules).
# --------------------------------------------------------------------------- #
def main() -> int:
    tests = [
        test_cooling_advantage_identity_and_negative,
        test_zonal_mean_over_mask,
        test_row_emission_rule,
        test_normalize_unit,
        test_irrigation_proxy_formula,
        test_irrigation_proxy_equal_weight_value,
        test_modal_functional_type,
        test_module_constants_and_schema,
    ]
    print("=" * 64)
    print("Section 13 pure-logic self-test")
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
