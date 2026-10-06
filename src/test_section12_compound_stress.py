#!/usr/bin/env python3
"""Self-test for the Section 12 Compound Stress Index pipeline (pure-logic).

Geo stack (rioxarray/xarray/rasterio) is stubbed so the module imports with only
numpy + pandas; the risky pure logic is then exercised on tiny synthetic arrays:
  demand = max(vpd_z, 0); supply = max(-sm_z, 0) (SOIL MOISTURE, BLOCKER B1a) with
  sm_z robust-rescaled (IQR/1.349) to ~unit spread; CSI = 0.5*d + 0.5*s plus the
  parameterised compute_csi weight hook; CSI >= 0 and NaN preserved; supply VARIES
  across overpasses (temporal sm_z); the z-score-not-raw pitfall guard (the pure
  _assert_supply_is_z helper: wide band for sm_z, tight band for the ndmi_z check);
  copula_weights() stub raises; config baseline weights are 0.5/0.5.
Run:  python src/test_section12_compound_stress.py
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd


def _install_geo_stubs() -> None:
    """Stub the heavy top-level imports so the module (and section11) import with
    only numpy + pandas (section12 imports section11_anomalies at top level)."""
    for name in ("rioxarray", "xarray"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["rioxarray"].open_rasterio = lambda *a, **k: None  # type: ignore[attr-defined]
    if not hasattr(sys.modules["xarray"], "Dataset"):
        sys.modules["xarray"].Dataset = object            # type: ignore[attr-defined]
        sys.modules["xarray"].DataArray = object           # type: ignore[attr-defined]
        sys.modules["xarray"].open_zarr = lambda *a, **k: None  # type: ignore[attr-defined]
        sys.modules["xarray"].open_dataset = lambda *a, **k: None  # type: ignore[attr-defined]
    if "rasterio" not in sys.modules:
        sys.modules["rasterio"] = types.ModuleType("rasterio")
    if "rasterio.enums" not in sys.modules:
        enums = types.ModuleType("rasterio.enums")

        class _Resampling:
            bilinear = "bilinear"
            nearest = "nearest"
            average = "average"

        enums.Resampling = _Resampling
        sys.modules["rasterio.enums"] = enums
        sys.modules["rasterio"].enums = enums              # type: ignore[attr-defined]


_install_geo_stubs()

sys.path.insert(0, str(Path(__file__).resolve().parent))
sec12 = importlib.import_module("section12_compound_stress")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


def test_demand_stress_positive_part() -> None:
    """demand stress = max(vpd_z, 0) (step 62)."""
    print("\n[demand stress = max(vpd_z, 0) (step 62)]")
    vpd_z = np.array([-2.0, -0.5, 0.0, 0.5, 3.0])
    d = sec12.demand_stress(vpd_z)
    check(d.tolist() == [0.0, 0.0, 0.0, 0.5, 3.0],
          "demand keeps positive z, zeroes negative/zero z")
    check(np.all(d >= 0.0), "demand stress >= 0 everywhere")
    dn = sec12.demand_stress(np.array([np.nan, 1.0]))
    check(np.isnan(dn[0]) and dn[1] == 1.0, "NaN VPD z preserved (not turned to 0)")


def test_supply_stress_negated_positive_part() -> None:
    """supply stress = max(-sm_z, 0) (step 63)."""
    print("\n[supply stress = max(-sm_z, 0): low water -> positive stress (step 63)]")
    sm_z = np.array([-2.0, -0.5, 0.0, 0.5, 3.0])
    s = sec12.supply_stress(sm_z)
    check(s.tolist() == [2.0, 0.5, 0.0, 0.0, 0.0],
          "below-normal soil moisture (negative z) -> positive supply stress; above-normal -> 0")
    check(np.all(s >= 0.0), "supply stress >= 0 everywhere")
    dn = sec12.supply_stress(np.array([np.nan, -1.0]))
    check(np.isnan(dn[0]) and dn[1] == 1.0, "NaN soil-moisture z preserved")
    check(s[0] == np.max(s), "lowest soil-moisture z (-2) yields largest supply stress")


def test_compute_csi_equal_weights() -> None:
    """baseline CSI = 0.5*demand + 0.5*supply (step 64)."""
    print("\n[baseline CSI = 0.5*demand + 0.5*supply (step 64)]")
    demand = np.array([0.0, 1.0, 2.0, 4.0])
    supply = np.array([1.0, 0.0, 2.0, 0.0])
    csi = sec12.compute_csi(demand, supply, 0.5, 0.5)
    check(np.allclose(csi, [0.5, 0.5, 2.0, 2.0]), "CSI = 0.5*demand + 0.5*supply elementwise")
    csi_def = sec12.compute_csi(demand, supply)
    check(np.allclose(csi_def, csi), "compute_csi defaults to config equal weights")
    check(np.all(csi >= 0.0), "equal-weight CSI >= 0 when both parts >= 0")


def test_compute_csi_parameterised_weights() -> None:
    """parameterised compute_csi -- step-66 unequal-weight hook."""
    print("\n[parameterised compute_csi -- step-66 unequal-weight HOOK]")
    demand = np.array([2.0, 0.0])
    supply = np.array([0.0, 2.0])
    csi_d = sec12.compute_csi(demand, supply, 1.0, 0.0)
    check(np.allclose(csi_d, [2.0, 0.0]), "w_demand=1, w_supply=0 -> CSI == demand")
    csi_s = sec12.compute_csi(demand, supply, 0.0, 1.0)
    check(np.allclose(csi_s, [0.0, 2.0]), "w_demand=0, w_supply=1 -> CSI == supply")
    csi_u = sec12.compute_csi(demand, supply, 0.7, 0.3)
    check(np.allclose(csi_u, [1.4, 0.6]), "unequal weights (0.7/0.3) are a trivial re-call")


def test_weight_validation_and_executed_sensitivity() -> None:
    """m3: five convex scenarios execute, reproduce baseline, and reject invalid weights."""
    print("\n[m3: executed unequal-weight sensitivity uses five validated convex pairs]")
    for pair in ((-0.1, 1.1), (0.2, 0.2), (np.nan, 1.0)):
        raised = False
        try:
            sec12.validate_csi_weights(*pair)
        except ValueError:
            raised = True
        check(raised, f"invalid pair {pair} rejected")

    class _Array:
        def __init__(self, values):
            self.values = np.asarray(values)

    # Six overpasses with deliberately different demand/supply temporal rankings.
    demand = np.arange(24, dtype=float).reshape(6, 2, 2) / 10.0
    supply = demand[::-1].copy() * 0.8
    demand[0, 0, 0] = np.nan
    supply[0, 0, 0] = np.nan
    baseline = sec12.compute_csi(demand, supply, 0.5, 0.5).astype("float32")
    ds = {
        "demand_stress": _Array(demand),
        "supply_stress": _Array(supply),
        "csi": _Array(baseline),
        "time": _Array(pd.to_datetime([
            "2023-06-05", "2023-06-30", "2023-07-10",
            "2023-07-20", "2023-08-15", "2023-09-10",
        ]).to_numpy()),
        "overpass_key": _Array(np.array([f"op{i}" for i in range(6)], dtype=object)),
    }
    table = sec12.run_weight_sensitivity(ds)
    check(len(table) == 5, "one output row per predeclared scenario")
    check(set(table["scenario"]) == {
        "pure_supply", "supply_heavy", "equal_baseline", "demand_heavy", "pure_demand"
    }, "endpoint, unequal, and equal-baseline scenarios all persisted")
    equal = table.loc[table["scenario"] == "equal_baseline"].iloc[0]
    check(equal["baseline_max_abs_diff"] <= 1e-6,
          "equal scenario exactly reproduces the saved baseline cube")
    check((table["n_finite_cells"] == table["n_finite_cells"].iloc[0]).all(),
          "all weights use the same common finite-cell count")
    pure_d = table.loc[table["scenario"] == "pure_demand", "csi_spatial_mean_all"].iloc[0]
    pure_s = table.loc[table["scenario"] == "pure_supply", "csi_spatial_mean_all"].iloc[0]
    equal_mean = equal["csi_spatial_mean_all"]
    check(np.isclose(equal_mean, 0.5 * pure_d + 0.5 * pure_s),
          "equal scenario is the exact convex midpoint of pure demand and supply means")


def test_csi_nonnegative_and_nan_preserved() -> None:
    """CSI >= 0 everywhere; NaN preserved (step 65)."""
    print("\n[CSI >= 0 everywhere; NaN preserved (step 65)]")
    rng = np.random.default_rng(1)
    vpd_z = rng.normal(0, 1, size=2000)
    sm_z = rng.normal(0, 1, size=2000)
    vpd_z[5] = np.nan
    d = sec12.demand_stress(vpd_z)
    s = sec12.supply_stress(sm_z)
    csi = sec12.compute_csi(d, s, 0.5, 0.5)
    fin = np.isfinite(csi)
    check(bool(np.all(csi[fin] >= 0.0)), "CSI >= 0 over all finite cells")
    check(np.isnan(csi[5]), "NaN VPD z propagates to NaN CSI")


def test_supply_varies_across_overpasses_when_sm_z_is_temporal() -> None:
    """Supply varies in time when sm_z is a temporal anomaly."""
    print("\n[supply stress VARIES across overpasses when sm_z is temporal]")
    rng = np.random.default_rng(7)
    n_op, n_px = 8, 500
    sm_z_temporal = rng.normal(0.0, 1.0, size=(n_op, n_px))   # different z-field per overpass
    supply = sec12.supply_stress(sm_z_temporal)               # (overpass, px)
    per_op_mean = np.nanmean(supply, axis=1)
    varies_std = float(np.nanstd(per_op_mean))
    check(supply.shape == (n_op, n_px), "supply keeps (overpass, pixel) shape")
    check(varies_std > 1e-6,
          f"temporal sm_z -> supply varies across overpasses (std={varies_std:.4f} > 0)")
    # Contrast: an identical-every-overpass z field -> flat supply.
    sm_z_static = np.broadcast_to(rng.normal(0, 1, size=n_px), (n_op, n_px))
    supply_static = sec12.supply_stress(sm_z_static)
    static_std = float(np.nanstd(np.nanmean(supply_static, axis=1)))
    check(static_std < 1e-12,
          f"static sm_z gives flat supply (std={static_std:.2e} ~ 0)")
    demand_zero = np.zeros_like(supply)
    csi = sec12.compute_csi(demand_zero, supply, 0.5, 0.5)
    check(float(np.nanstd(np.nanmean(csi, axis=1))) > 1e-6,
          "temporal supply -> CSI varies across overpasses from supply side alone (demand=0)")


def test_supply_uses_zscore_not_raw_soil_moisture() -> None:
    """PITFALL guard: supply uses the soil-moisture z-score, not its raw values."""
    print("\n[PITFALL guard: supply stress uses the SOIL-MOISTURE Z-SCORE, not raw values]")
    rng = np.random.default_rng(2)
    raw_sm = rng.normal(loc=0.21, scale=0.04, size=5000)
    mu, sigma = float(np.mean(raw_sm)), float(np.std(raw_sm))
    sm_z = (raw_sm - mu) / sigma

    supply_from_z = sec12.supply_stress(sm_z)
    supply_from_raw = sec12.supply_stress(raw_sm)   # WRONG input (the pitfall)
    check(not np.allclose(supply_from_z, supply_from_raw, atol=1e-3),
          "supply from z-score differs from supply from raw soil moisture")
    check(np.max(supply_from_z) > 1.0, "z-score supply reaches order-1 magnitudes")
    check(np.max(supply_from_raw) == 0.0,
          "positive raw volumetric moisture is not a standardized stress signal")

    vpd_z = rng.normal(0, 1, size=5000)
    demand = sec12.demand_stress(vpd_z)
    csi_correct = sec12.compute_csi(demand, supply_from_z, 0.5, 0.5)
    csi_pitfall = sec12.compute_csi(demand, supply_from_raw, 0.5, 0.5)
    supply_share_correct = np.mean(0.5 * supply_from_z) / np.mean(csi_correct)
    supply_share_pitfall = np.mean(0.5 * supply_from_raw) / np.mean(csi_pitfall)
    check(supply_share_correct > 0.40,
          "z-scores -> supply term carries a balanced ~half of equal-weight CSI")
    check(supply_share_pitfall < 0.25,
          "raw soil moisture -> supply term vanishes -> CSI demand-dominated (pitfall)")
    check(supply_share_correct > 2.0 * supply_share_pitfall,
          "z-score supply carries materially more of CSI than raw-soil-moisture supply")
    check(sec12.SUPPLY_Z_VAR == "sm_z" and sec12.DEMAND_Z_VAR == "vpd_z",
          "module reads the z-score variables (vpd_z demand / sm_z supply), not raw fields")


def test_supply_source_is_soil_moisture() -> None:
    """B1a: the CSI supply axis is root-zone SOIL MOISTURE (sm_z); ndmi_z is a check only."""
    print("\n[B1a: supply source is SOIL MOISTURE (sm_z); ndmi_z is a vegetation check]")
    import config
    check(sec12.SUPPLY_Z_VAR == "sm_z", "SUPPLY_Z_VAR is sm_z")
    check(sec12.SUPPLY_Z_VAR == config.SUPPLY_VAR,
          "SUPPLY_Z_VAR is wired to config.SUPPLY_VAR (single source of truth)")
    check(sec12.CHECK_Z_VAR == "ndmi_z", "CHECK_Z_VAR is ndmi_z (vegetation check, not supply)")
    check(sec12.SUPPLY_Z_VAR != sec12.CHECK_Z_VAR,
          "supply and check are two DIFFERENT variables, by design (naming invariant)")
    # supply_stress is sign-correct for any wetness z: dry sm_z (<0) -> stress; wet (>0) -> 0.
    s = sec12.supply_stress(np.array([-2.0, 0.0, 2.0]))
    check(s.tolist() == [2.0, 0.0, 0.0],
          "supply_stress([-2,0,2]) == [2,0,0] (dry soil moisture -> stress; wet -> 0)")


def test_robust_unit_scale_restores_unit_spread() -> None:
    """robust_unit_scale (IQR/1.349) restores ~unit spread for compressed-variance sm_z."""
    print("\n[robust_unit_scale: IQR/1.349 restores ~unit spread; sign/NaN preserved]")
    rng = np.random.default_rng(20240606)
    z = rng.normal(0.0, 0.45, size=5000)   # sm_z's real single-year compressed variance
    check(np.std(z) < 0.6, f"input has compressed std ~0.45 (std={np.std(z):.3f})")
    r = sec12.robust_unit_scale(z)
    check(0.7 < np.std(r) < 1.3,
          f"rescaled std restored to ~1 (std={np.std(r):.3f} in 0.7-1.3)")
    # Sign preserved elementwise (division by a positive robust sigma).
    check(np.array_equal(np.sign(r), np.sign(z)), "sign preserved elementwise")
    # NaN preserved; finite values stay finite.
    zn = np.array([np.nan, -0.9, 0.0, 0.9])
    rn = sec12.robust_unit_scale(zn)
    check(np.isnan(rn[0]) and not np.any(np.isnan(rn[1:])),
          "NaN preserved; finite entries stay finite")
    # Fewer than 2 finite values -> returned unchanged.
    one = np.array([np.nan, 3.0])
    check(np.array_equal(sec12.robust_unit_scale(one), one, equal_nan=True),
          "fewer than 2 finite values -> returned unchanged")
    allnan = np.array([np.nan, np.nan])
    check(np.array_equal(sec12.robust_unit_scale(allnan), allnan, equal_nan=True),
          "all-NaN input -> returned unchanged")


def test_input_guard_accepts_sm_z_rejects_raw() -> None:
    """Pure guard _assert_supply_is_z: accepts sm_z-like z (wide band), rejects raw fields."""
    print("\n[input guard _assert_supply_is_z: accepts sm_z (std~0.45, spans 0), rejects raw]")
    rng = np.random.default_rng(11)
    # sm_z-like: compressed std ~0.45, straddles 0 -> the WIDE supply band accepts it.
    sm_like = rng.normal(0.0, 0.45, size=5000)
    try:
        _m, std, lo, hi = sec12._assert_supply_is_z(sm_like, "sm_z", rescaled=False)
        ok = (0.3 < std < 1.3) and (lo < 0 < hi)
    except AssertionError:
        ok = False
    check(ok, "sm_z-like field (std~0.45, spans 0) PASSES the wide supply guard")
    # A raw physical field: tiny std, does not straddle 0 -> rejected.
    raw_sm = rng.normal(loc=0.18, scale=0.03, size=5000)   # e.g. raw soil moisture (all > 0)
    raised = False
    try:
        sec12._assert_supply_is_z(raw_sm, "sm_z", rescaled=False)
    except AssertionError:
        raised = True
    check(raised, "raw field (tiny std, does not straddle 0) is REJECTED by the supply guard")
    # The ndmi_z CHECK keeps the TIGHT band: raw NDMI (bounded [-1,1], std~0.09) rejected.
    raw_ndmi = rng.normal(loc=-0.07, scale=0.09, size=5000)
    raised_nd = False
    try:
        sec12._assert_supply_is_z(raw_ndmi, "ndmi_z", rescaled=False)
    except AssertionError:
        raised_nd = True
    check(raised_nd, "ndmi_z CHECK keeps the tight z band -> raw NDMI rejected")
    # A proper ndmi_z z-score (std~1, spans +/-1) passes the tight check band.
    ndmi_z = rng.normal(0.0, 1.0, size=5000)
    try:
        sec12._assert_supply_is_z(ndmi_z, "ndmi_z", rescaled=False)
        ok_nd = True
    except AssertionError:
        ok_nd = False
    check(ok_nd, "a true ndmi_z z-score (std~1, spans +/-1) passes the tight check band")
    # Post-rescale guard: robust-rescaled sm_z has ~unit spread and passes rescaled=True.
    rescaled = sec12.robust_unit_scale(sm_like)
    try:
        sec12._assert_supply_is_z(rescaled, "sm_z", rescaled=True)
        ok_r = True
    except AssertionError:
        ok_r = False
    check(ok_r, "robust-rescaled sm_z (~unit spread, spans 0) passes the post-rescale guard")


def test_copula_weights_is_unrun_stub() -> None:
    """step-66 copula stub raises NotImplementedError, never run."""
    print("\n[copula_weights() is a step-66 STUB -- raises NotImplementedError]")
    raised = False
    try:
        sec12.copula_weights()
    except NotImplementedError:
        raised = True
    check(raised, "copula_weights() raises NotImplementedError (placeholder)")
    raised2 = False
    try:
        sec12.copula_weights(np.array([1.0]), np.array([1.0]))
    except NotImplementedError:
        raised2 = True
    check(raised2, "copula_weights(*args) still raises (stub ignores args)")


def test_heatwave_helpers_delegate_to_section11() -> None:
    """heatwave window + enrichment reuse Section 11 (single source of truth)."""
    print("\n[heatwave window + enrichment reuse Section 11]")
    check(sec12.in_heatwave("2023-07-20"), "mid-July 2023 is in the heatwave window")
    check(not sec12.in_heatwave("2023-09-01"), "September 2023 is after the window")
    check(sec12.HEATWAVE_2023[0] == pd.Timestamp("2023-06-30")
          and sec12.HEATWAVE_2023[1] == pd.Timestamp("2023-07-30"),
          "2023 peak-heat window matches Section 11 (Jun 30 .. Jul 30)")
    times = pd.to_datetime(["2023-07-10", "2023-07-20", "2023-07-25",
                            "2023-06-05", "2023-08-15", "2023-09-10"])
    scores = np.array([3.0, 2.9, 2.8, 0.1, 0.2, 0.0])
    enr = sec12.heatwave_enrichment(times, scores, top_k=3)
    check(abs(enr["top_frac"] - 1.0) < 1e-9 and enr["enrichment"] > 1.0,
          "2023-window overpasses dominate top scores -> enrichment > 1")


def test_module_constants_and_weights() -> None:
    """config baseline weights + module source constants."""
    print("\n[config baseline weights + module source constants]")
    import config
    check(abs(config.WEIGHT_DEMAND - 0.5) < 1e-12, "config.WEIGHT_DEMAND == 0.5")
    check(abs(config.WEIGHT_SUPPLY - 0.5) < 1e-12, "config.WEIGHT_SUPPLY == 0.5")
    check(abs((config.WEIGHT_DEMAND + config.WEIGHT_SUPPLY) - 1.0) < 1e-12,
          "baseline weights sum to 1")
    check(sec12.DEMAND_Z_VAR == "vpd_z", "demand built from VPD z-score variable")
    check(sec12.SUPPLY_Z_VAR == "sm_z", "supply built from SOIL-MOISTURE z-score variable (sm_z)")
    check(sec12.CHECK_Z_VAR == "ndmi_z", "ndmi_z carried as the VEGETATION CHECK only")
    check(sec12.ZSCORE_ZARR == "section11_zscores_70m.zarr",
          "only input is the Section 11 z-score store")


def main() -> int:
    tests = [
        test_demand_stress_positive_part,
        test_supply_stress_negated_positive_part,
        test_compute_csi_equal_weights,
        test_compute_csi_parameterised_weights,
        test_weight_validation_and_executed_sensitivity,
        test_csi_nonnegative_and_nan_preserved,
        test_supply_varies_across_overpasses_when_sm_z_is_temporal,
        test_supply_uses_zscore_not_raw_soil_moisture,
        test_supply_source_is_soil_moisture,
        test_robust_unit_scale_restores_unit_spread,
        test_input_guard_accepts_sm_z_rejects_raw,
        test_copula_weights_is_unrun_stub,
        test_heatwave_helpers_delegate_to_section11,
        test_module_constants_and_weights,
    ]
    print("=" * 64)
    print("Section 12 pure-logic self-test")
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
