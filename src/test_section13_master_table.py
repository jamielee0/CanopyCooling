#!/usr/bin/env python3
"""Self-test for the Section 13 master-table pipeline (pure-logic).

Geo stack (rioxarray/xarray/rasterio/geopandas) is stubbed so the module imports
with only numpy + pandas; the risky pure logic is exercised on tiny synthetic
arrays (no network, no Zarr, no grid IO): cooling advantage (incl. negative case),
zonal mean over a class mask, the row-emission rule, the irrigation proxy + its
normalization, and the functional-type modal aggregation. Zarr/raster/vector load,
rasterization, spatial join and parquet write are exercised by the real CLI.

Run: python src/test_section13_master_table.py
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd


def _install_geo_stubs() -> None:
    """Stub heavy top-level imports so the module imports with only numpy + pandas."""
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


def test_cooling_advantage_identity_and_negative() -> None:
    """cooling_advantage = ref mean - tree mean, incl. negative case (step 67)."""
    print("\n[cooling_advantage = mean_LST(reference) - mean_LST(tree) (step 67)]")
    ca = sec13.cooling_advantage(315.0, 308.0)
    check(abs(ca - 7.0) < 1e-9, "ref 315, tree 308 -> +7.0 K (trees cooler)")
    check(abs(sec13.cooling_advantage(310.0, 310.0)) < 1e-9,
          "equal tree/reference -> 0")
    can = sec13.cooling_advantage(305.0, 309.0)
    check(abs(can + 4.0) < 1e-9, "ref 305, tree 309 -> -4.0 K (NOT clipped)")
    check(can < 0.0, "negative cooling advantage returned as-is")
    check(np.isnan(sec13.cooling_advantage(np.nan, 300.0)),
          "NaN reference mean -> NaN")


def test_zonal_mean_over_mask() -> None:
    """zonal_mean: mean over masked-AND-finite cells, with n_valid sample size."""
    print("\n[zonal_mean: mean over masked-AND-finite cells, with n_valid]")
    vals = np.array([[300.0, 310.0, np.nan],
                     [320.0, np.nan, 330.0]])
    mask = np.array([[True, True, True],
                     [False, True, True]])
    m, n = sec13.zonal_mean(vals, mask)
    check(abs(m - (300.0 + 310.0 + 330.0) / 3.0) < 1e-9,
          "mean over masked finite cells only (in-mask NaNs ignored)")
    check(n == 3, "n_valid counts masked-and-finite (=3), not all masked (=4)")
    m0, n0 = sec13.zonal_mean(np.array([np.nan, np.nan]), np.array([True, True]))
    check(np.isnan(m0) and n0 == 0, "all-NaN inside mask -> (NaN, 0)")
    m1, n1 = sec13.zonal_mean(np.array([1.0, 2.0]), np.array([False, False]))
    check(np.isnan(m1) and n1 == 0, "empty mask -> (NaN, 0)")


def test_csi_component_means_use_common_mask() -> None:
    """m3: component means share one finite mask and exactly reconstruct baseline CSI."""
    print("\n[m3: CSI/demand/supply means use one common finite tree-pixel mask]")
    demand = np.array([[1.0, 3.0, 9.0, np.nan]])
    supply = np.array([[5.0, 7.0, np.nan, 11.0]])
    csi = 0.5 * demand + 0.5 * supply
    rr = np.array([0, 0, 0, 0])
    cc = np.array([0, 1, 2, 3])
    mc, md, ms = sec13.common_component_means(csi, demand, supply, rr, cc)
    check(np.isclose(md, 2.0) and np.isclose(ms, 6.0),
          "only the two pixels finite in both components enter either mean")
    check(np.isclose(mc, 4.0) and np.isclose(mc, 0.5 * md + 0.5 * ms),
          "mean baseline CSI equals weighted component means exactly")
    empty = sec13.common_component_means(
        np.full((1, 2), np.nan), np.full((1, 2), np.nan),
        np.full((1, 2), np.nan), np.array([0, 0]), np.array([0, 1]))
    check(all(np.isnan(v) for v in empty), "empty common mask returns three NaNs")


def test_row_emission_rule() -> None:
    """row_emittable: need >=1 finite-LST tree px AND >=1 finite-LST reference px."""
    print("\n[row_emittable: >=1 finite tree px AND >=1 finite reference px]")
    check(sec13.row_emittable(1, 1), "1 tree + 1 reference -> emit")
    check(sec13.row_emittable(171, 800), "many tree + many reference -> emit")
    check(not sec13.row_emittable(0, 500), "0 tree -> DROP")
    check(not sec13.row_emittable(5, 0), "0 reference -> DROP")
    check(not sec13.row_emittable(0, 0), "neither group -> DROP")


def test_primary_sample_label() -> None:
    """Low-count rows are retained but explicitly excluded from the primary sample."""
    print("\n[analysis_sample_label: primary tree-pixel floor is explicit and non-destructive]")
    floor = sec13.config.PRIMARY_MIN_TREE_PIXELS
    check(sec13.analysis_sample_label(floor) == sec13.PRIMARY_SAMPLE_LABEL,
          "row at the pre-committed tree-pixel floor is primary")
    check(sec13.analysis_sample_label(floor - 1) == sec13.LOW_COUNT_SAMPLE_LABEL,
          "row below the floor is retained as a labelled sensitivity observation")


def test_normalize_unit() -> None:
    """normalize_unit: min-max to [0,1] across neighborhoods (step 70)."""
    print("\n[normalize_unit: min-max to [0,1]]")
    out = sec13.normalize_unit(np.array([10.0, 20.0, 30.0]))
    check(np.allclose(out, [0.0, 0.5, 1.0]), "min->0, max->1, mid->0.5")
    eq = sec13.normalize_unit(np.array([5.0, 5.0, 5.0]))
    check(np.allclose(eq, [0.0, 0.0, 0.0]), "all-equal -> 0 (no spread)")
    check(np.all((out >= 0) & (out <= 1)), "values in [0,1]")


def test_irrigation_proxy_formula() -> None:
    """irrigation_proxy = mean(norm(turf), norm(income), norm(1-imperv)) (step 70)."""
    print("\n[irrigation_proxy formula + monotonic directions (step 70)]")
    turf = np.array([0.0, 0.1, 0.2])
    income = np.array([30000.0, 60000.0, 90000.0])
    imperv_frac = np.array([0.8, 0.5, 0.2])
    proxy = sec13.irrigation_proxy(turf, income, imperv_frac)
    check(np.all(np.diff(proxy) > 0), "proxy increases when all components increase")
    check(abs(proxy[0] - 0.0) < 1e-9 and abs(proxy[2] - 1.0) < 1e-9,
          "all components aligned -> proxy spans 0..1")
    flat_turf = np.array([0.1, 0.1]); flat_inc = np.array([5e4, 5e4])
    base_imp = np.array([0.5, 0.5])
    p_turf = sec13.irrigation_proxy(np.array([0.0, 0.3]), flat_inc, base_imp)
    check(p_turf[1] > p_turf[0], "more turf alone -> higher proxy")
    p_inc = sec13.irrigation_proxy(flat_turf, np.array([3e4, 9e4]), base_imp)
    check(p_inc[1] > p_inc[0], "higher income alone -> higher proxy")
    p_imp = sec13.irrigation_proxy(flat_turf, flat_inc, np.array([0.9, 0.1]))
    check(p_imp[1] > p_imp[0], "less impervious alone -> higher proxy")
    check(np.all((proxy >= -1e-9) & (proxy <= 1 + 1e-9)), "proxy in [0,1]")


def test_irrigation_proxy_equal_weight_value() -> None:
    """irrigation_proxy is the equal-weight (1/3 each) mean of the three norms."""
    print("\n[irrigation_proxy = equal 1/3 weights]")
    turf = np.array([1.0, 0.0])              # norm -> [1, 0]
    income = np.array([0.0, 1.0])            # norm -> [0, 1]
    imperv_frac = np.array([0.0, 1.0])       # 1-imp=[1,0] -> norm -> [1, 0]
    proxy = sec13.irrigation_proxy(turf, income, imperv_frac)
    check(np.allclose(proxy, [2.0 / 3.0, 1.0 / 3.0]),
          "proxy = (turf_norm + income_norm + low_imperv_norm)/3")


def test_modal_functional_type() -> None:
    """modal_functional_type: dominant label; 'unknown' when no trees (step 68/69)."""
    print("\n[modal_functional_type: dominant label; 'unknown' when no trees]")
    check(sec13.modal_functional_type(
        ["mesic", "mesic", "drought_tolerant"]) == "mesic",
        "most frequent label wins (mesic 2 vs 1)")
    check(sec13.modal_functional_type([]) == sec13.FUNCTIONAL_UNKNOWN,
          "no trees -> 'unknown'")
    check(sec13.modal_functional_type([None, np.nan]) == sec13.FUNCTIONAL_UNKNOWN,
          "all-null -> 'unknown'")
    check(sec13.modal_functional_type(
        ["drought_tolerant", None, "drought_tolerant", np.nan]) == "drought_tolerant",
        "nulls ignored; modal non-null wins")
    tie = sec13.modal_functional_type(["mesic", "drought_tolerant"])
    check(tie == "drought_tolerant",
          "tie broken by alphabetically-first label")


def test_module_constants_and_schema() -> None:
    """Module constants + master-table schema contract."""
    print("\n[module constants + master-table schema contract]")
    check(sec13.MASTER_PARQUET == "master_table.parquet",
          "deliverable is master_table.parquet (step 71)")
    check(sec13.CLASS_TREE == 1 and sec13.CLASS_REFERENCE == 2,
          "Section 10 class codes (1=tree, 2=reference)")
    # Cross-module naming invariant: NDMI is the vegetation check; supply = sm_z.
    check(sec13.VEGETATION_CHECK_Z_VAR == "ndmi_z" and sec13.VPD_Z_VAR == "vpd_z",
          "veg-check z=ndmi_z, demand z=vpd_z (Section 11)")
    check(sec13.SM_Z_VAR == "sm_z", "supply proper z=sm_z (B1b)")
    check(sec13.CITY == "Phoenix", "city is 'Phoenix'")
    for grp, cols in sec13.COLUMN_GROUPS.items():
        for c in cols:
            check(c in sec13.MASTER_COLUMNS, f"column-group {grp!r} member {c!r} in MASTER_COLUMNS")
    check(len(sec13.MASTER_COLUMNS) == len(set(sec13.MASTER_COLUMNS)),
          "MASTER_COLUMNS has no duplicates")
    check(sec13.MASTER_COLUMNS[:4] == ["neighborhood_id", "overpass_timestamp",
                                       "overpass_key", "city"],
          "MASTER_COLUMNS leads with identifier group")
    check("n_good_obs" in sec13.MASTER_COLUMNS and "n_tree_px" in sec13.MASTER_COLUMNS
          and "n_ref_px" in sec13.MASTER_COLUMNS,
          "pixel-count columns retained (Section 14 filter)")
    # B1b supply rename + add: primary sm_z present, veg-check renamed, old name gone.
    check("mean_sm_z_tree" in sec13.MASTER_COLUMNS,
          "mean_sm_z_tree (primary supply) in MASTER_COLUMNS")
    check("mean_ndmi_z_tree" in sec13.MASTER_COLUMNS,
          "mean_ndmi_z_tree (vegetation check) in MASTER_COLUMNS")
    check("mean_demand_stress_tree" in sec13.MASTER_COLUMNS
          and "mean_supply_stress_tree" in sec13.MASTER_COLUMNS,
          "m3 demand/supply component means are persisted for weight sensitivity")
    check("mean_water_supply_z_tree" not in sec13.MASTER_COLUMNS,
          "old mean_water_supply_z_tree removed from MASTER_COLUMNS")
    # B4 persisted time-of-day columns (appended after 'city').
    check(all(c in sec13.MASTER_COLUMNS for c in ("local_hour", "is_day", "sample_label")),
          "local_hour + is_day + sample_label persisted in MASTER_COLUMNS")
    # B3.1 pixel-table schema contract.
    check(sec13.PIXEL_PARQUET == "master_pixel_table.parquet",
          "pixel deliverable is master_pixel_table.parquet (B3.1)")
    for c in ("neighborhood_id", "overpass_timestamp", "overpass_key", "city",
              "local_hour", "is_day", "sample_label", "pixel_row", "pixel_col", "tree_lst",
              "mean_lst_reference", "cooling_advantage_px", "vpd_z", "sm_z", "ndmi_z", "csi",
              "aridity", "n_ref_valid", "n_tree_valid", "n_good_obs"):
        check(c in sec13.PIXEL_COLUMNS, f"PIXEL_COLUMNS contains {c!r}")
    check(len(sec13.PIXEL_COLUMNS) == len(set(sec13.PIXEL_COLUMNS)),
          "PIXEL_COLUMNS has no duplicates")


def test_local_hour_and_is_day_derivation() -> None:
    """local_time_fields: tz-naive UTC -> (local_hour, is_day) with Arizona UTC-7 offset."""
    print("\n[local_hour + is_day derivation (Arizona MST = UTC-7, no DST; day [7,19))]")
    cases = [
        # (utc_hour, expected_local_hour, expected_is_day, note)
        (20, 13, True, "20:00 UTC -> local 13, day"),
        (6, 23, False, "06:00 UTC -> local 23, night"),
        (2, 19, False, "02:00 UTC -> local 19, night (upper boundary excluded)"),
        (14, 7, True, "14:00 UTC -> local 7, day (lower boundary included)"),
    ]
    for utc_h, exp_hour, exp_day, note in cases:
        ts = pd.Timestamp(f"2023-06-15 {utc_h:02d}:00:00")  # tz-naive UTC
        lh, isd = sec13.local_time_fields(ts)
        check(lh == exp_hour and isinstance(lh, int), f"{note}: local_hour == {exp_hour}")
        check(isd is exp_day and isinstance(isd, bool), f"{note}: is_day is {exp_day}")


def _stub_grids(times, lst, vpd_z, sm_z, ndmi_z, csi, pdsi):
    """Assemble a minimal grids dict for build_pixel_table (numpy arrays, no xarray)."""
    n = len(times)
    return {
        "time": pd.to_datetime(times),
        "overpass_key": np.array([f"op{t}" for t in range(n)]),
        "n_overpass": n,
        "lst": lst, "vpd_z": vpd_z, "sm_z": sm_z, "ndmi_z": ndmi_z,
        "csi": csi, "pdsi": pdsi,
    }


def test_pixel_table_shape_and_identity() -> None:
    """build_pixel_table: one row per finite tree px; identity + emit gate (B3.1)."""
    print("\n[build_pixel_table: row count, cooling_advantage_px identity, emit gate]")
    # 3x3 grid, single overpass. BG 'A': two tree px (one NaN LST) + one ref px.
    #                             BG 'B': one tree px but ZERO finite reference px.
    nan = np.nan
    lst = np.array([[[300.0, 305.0, 310.0],
                     [nan,   320.0, 330.0],
                     [340.0, 350.0, 360.0]]], dtype="float64")  # (1, 3, 3)
    vpd_z = np.full((1, 3, 3), 1.5, dtype="float64")
    sm_z = np.full((1, 3, 3), -1.25, dtype="float64")
    ndmi_z = np.full((1, 3, 3), -0.5, dtype="float64")
    csi = np.full((1, 3, 3), 0.25, dtype="float64")
    pdsi = np.full((1, 3, 3), -2.0, dtype="float64")
    grids = _stub_grids(["2023-06-15 20:00:00"], lst, vpd_z, sm_z, ndmi_z, csi, pdsi)

    static = pd.DataFrame([{"neighborhood_id": "A"}, {"neighborhood_id": "B"}])
    # BG A: tree px at (0,0) finite and (1,0) NaN-LST; reference px at (0,1),(0,2).
    # BG B: tree px at (2,2) finite; NO reference px -> must emit nothing.
    static.attrs["tree_px_by_geoid"] = {
        "A": (np.array([0, 1]), np.array([0, 0])),
        "B": (np.array([2]), np.array([2])),
    }
    static.attrs["ref_px_by_geoid"] = {
        "A": (np.array([0, 0]), np.array([1, 2])),
        "B": (np.array([], dtype=int), np.array([], dtype=int)),
    }

    pixel = sec13.build_pixel_table(grids, static)
    check(list(pixel.columns) == list(sec13.PIXEL_COLUMNS),
          "pixel table columns == PIXEL_COLUMNS in order")
    # Only BG A emits, and only its ONE finite tree pixel (0,0); (1,0) is NaN LST.
    check(len(pixel) == 1, "row count == sum of finite tree px over emittable BG x overpass")
    check((pixel["neighborhood_id"] == "A").all(),
          "BG B (0 finite reference px) emits nothing")
    check(bool((pixel["pixel_row"] == 0).all() and (pixel["pixel_col"] == 0).all()),
          "NaN-LST tree pixel (1,0) absent")
    row = pixel.iloc[0]
    mean_ref = (305.0 + 310.0) / 2.0  # ref px (0,1),(0,2)
    check(abs(row["mean_lst_reference"] - mean_ref) < 1e-9,
          "mean_lst_reference is the BG x overpass reference MEAN")
    check(abs(row["tree_lst"] - 300.0) < 1e-9, "tree_lst is the per-pixel value")
    check(abs(row["cooling_advantage_px"] - (mean_ref - 300.0)) < 1e-5,
          "cooling_advantage_px == mean_lst_reference - tree_lst")
    check(int(row["local_hour"]) == 13 and bool(row["is_day"]) is True,
          "identifiers carry local_hour/is_day (20:00 UTC -> 13, day)")
    check(row["sample_label"] == sec13.LOW_COUNT_SAMPLE_LABEL,
          "one-tree-pixel row is retained but labelled sensitivity-only")
    check(abs(row["vpd_z"] - 1.5) < 1e-9 and abs(row["sm_z"] + 1.25) < 1e-9
          and abs(row["ndmi_z"] + 0.5) < 1e-9
          and abs(row["csi"] - 0.25) < 1e-9,
          "per-pixel predictors carried (vpd_z, sm_z supply, ndmi_z check, csi)")

    # Multi-tree BG -> multiple rows: give BG A two finite tree px.
    static2 = pd.DataFrame([{"neighborhood_id": "A"}])
    static2.attrs["tree_px_by_geoid"] = {"A": (np.array([0, 2]), np.array([0, 2]))}
    static2.attrs["ref_px_by_geoid"] = {"A": (np.array([0]), np.array([1]))}
    pixel2 = sec13.build_pixel_table(grids, static2)
    check(len(pixel2) == 2, "a multi-tree BG yields multiple rows (one per finite tree px)")


def main() -> int:
    tests = [
        test_cooling_advantage_identity_and_negative,
        test_zonal_mean_over_mask,
        test_csi_component_means_use_common_mask,
        test_row_emission_rule,
        test_primary_sample_label,
        test_normalize_unit,
        test_irrigation_proxy_formula,
        test_irrigation_proxy_equal_weight_value,
        test_modal_functional_type,
        test_module_constants_and_schema,
        test_local_hour_and_is_day_derivation,
        test_pixel_table_shape_and_identity,
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
