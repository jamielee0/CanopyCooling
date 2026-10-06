#!/usr/bin/env python3
"""Self-test for the Section 11 anomaly / deseasonalization pipeline (pure-logic).

Stubs the geo stack (rioxarray/xarray/rasterio) so the module imports with only
numpy + pandas, then exercises the risky pure logic on tiny synthetic arrays:
the +/-15-day day-of-year LOYO at-hour climatology window (steps 58-60), the
anomaly/z formulas + degenerate-std guard (steps 2-3), the NDMI temporal
day-of-year-at-overpass z (decision B, varies in time), the retained spatial
standardization, the half-month season-part binning, and the 2023-heatwave QC.

Run: python src/test_section11_anomalies.py
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd


def _install_geo_stubs() -> None:
    """Stub heavy top-level imports so the module loads with only numpy+pandas."""
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
sec11 = importlib.import_module("section11_anomalies")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


# 1. day-of-year +/-window moving-window selection at a fixed hour, LOYO.
def _synthetic_hourly():
    """Tiny hourly index over 3 years (2018-2020), Jun-Sep, for the window tests."""
    times = pd.date_range("2018-06-01", "2020-09-30 23:00", freq="h")
    times = times[(times.month >= 6) & (times.month <= 9)]
    return (times.dayofyear.to_numpy(), times.hour.to_numpy(), times.year.to_numpy(), times)


def test_doy_window_mask_basic() -> None:
    """day-of-year +/-15 window mask (step 58)."""
    print("\n[day-of-year +/-15 window mask (step 58)]")
    doys = np.array([180, 185, 190, 195, 200, 205, 210, 215, 220])
    m = sec11.doy_window_mask(doys, target_doy=200, window_days=15)
    check(doys[m].tolist() == [185, 190, 195, 200, 205, 210, 215],
          "window keeps doy in [target-15, target+15]")
    check(sec11.doy_window_mask(np.array([185, 215]), 200, 15).all(),
          "+/-15 boundary days included")
    check(not sec11.doy_window_mask(np.array([184, 216]), 200, 15).any(),
          "just outside +/-15 excluded")


def test_climatology_select_at_hour_loyo() -> None:
    """+/-15d, same hour, leave-one-year-out (steps 58-60)."""
    print("\n[climatology select: +/-15d, same hour, LOYO (58-60)]")
    doys, hours, years, _ = _synthetic_hourly()
    mask = sec11.climatology_select_mask(doys, hours, years, target_doy=200,
                                         target_hour=20, target_year=2019, window_days=15)
    check((hours[mask] == 20).all(), "all selected at matched hour (step 59)")
    check((np.abs(doys[mask] - 200) <= 15).all(), "all within +/-15 doy (step 58)")
    check((years[mask] != 2019).all(), "own year excluded (LOYO, step 60)")
    check(int(mask.sum()) == 62,
          f"2 LOYO years x 31 days @ 1 hour = 62 (got {int(mask.sum())})")
    full = sec11.climatology_select_mask(doys, hours, years, 200, 20, 9999, 15)  # drop none
    check(int(full.sum()) == 93 and int(full.sum()) - int(mask.sum()) == 31,
          "keeping the year adds exactly 31 (93 vs 62)")


def test_climatology_one_sided_early_season() -> None:
    """One-sided window at the season edge (early June)."""
    print("\n[one-sided window at season edge (early June)]")
    doys, hours, years, _ = _synthetic_hourly()
    # doy 153 ~ Jun 2; season starts Jun 1 (doy ~152) so window clips below -> one-sided.
    mask = sec11.climatology_select_mask(doys, hours, years, target_doy=153,
                                         target_hour=12, target_year=2019, window_days=15)
    sel_doys = doys[mask]
    check(sel_doys.min() >= 152, "clipped at season start (no wraparound)")
    check(sel_doys.max() <= 168, "extends only +15 days forward")
    check(int(mask.sum()) < 62 and int(mask.sum()) > 0,
          f"one-sided: fewer-but-nonzero samples (got {int(mask.sum())})")


# 2. anomaly / z-score formulas + degenerate-std guard.
def test_anomaly_and_zscore() -> None:
    """anomaly = obs - normal; z = anomaly / std (steps 2-3)."""
    print("\n[anomaly = obs - normal; z = anomaly / std (steps 2-3)]")
    obs = np.array([3.0, 5.0, 1.0])
    normal = np.array([2.0, 2.0, 2.0])
    std = np.array([1.0, 2.0, 0.5])
    a = sec11.anomaly(obs, normal)
    check(a.tolist() == [1.0, 3.0, -1.0], "anomaly = observed - normal")
    z = sec11.zscore(obs, normal, std)
    check(np.allclose(z, [1.0, 1.5, -2.0]), "z = anomaly / std")
    x = np.array([10.0, 12.0, 14.0, 16.0, 18.0])
    zz = sec11.zscore(x, np.mean(x), np.std(x))
    check(abs(float(np.mean(zz))) < 1e-12 and abs(float(np.std(zz)) - 1.0) < 1e-12,
          "standardizing by sample mean/std gives mean 0, std 1")


def test_zscore_degenerate_std() -> None:
    """Degenerate std (0 / non-finite) -> NaN, never +/-inf; min_std floor + count."""
    print("\n[degenerate std (0 / non-finite) -> NaN]")
    obs = np.array([3.0, 5.0, 7.0])
    normal = np.array([2.0, 2.0, 2.0])
    std = np.array([0.0, np.nan, 2.0])
    z = sec11.zscore(obs, normal, std)
    check(np.isnan(z[0]), "std == 0 -> z NaN")
    check(np.isnan(z[1]), "std non-finite -> z NaN")
    check(np.isclose(z[2], 2.5), "healthy std divides normally")
    check(np.isfinite(z[2]) and not np.isinf(z).any(), "no +/-inf produced")
    # B2 std floor: finite std <= min_std is rejected to NaN and COUNTED; non-finite
    # std is rejected but NOT counted as floored; above-floor divides normally.
    obs4 = np.array([3.0, 3.0, 3.0, 3.0])
    normal4 = np.array([2.0, 2.0, 2.0, 2.0])
    std4 = np.array([0.01, 0.02, np.nan, 0.5])
    z4, nf = sec11.zscore(obs4, normal4, std4, min_std=0.02, return_n_floored=True)
    check(np.isnan(z4[0]), "finite std BELOW floor (0.01 < 0.02) -> z NaN")
    check(np.isnan(z4[1]), "std EXACTLY at floor (== min_std) -> z NaN (<= comparison)")
    check(np.isnan(z4[2]), "non-finite std still -> z NaN under a floor")
    check(np.isclose(z4[3], 2.0), "std above floor divides normally (1.0/0.5 = 2.0)")
    check(nf == 2, f"n_floored counts ONLY finite stds <= min_std (got {nf}, want 2)")
    check(not np.isinf(z4).any(), "floor produces NaN, never +/-inf")
    # min_std=0.0 (the default) must reproduce the original exact-zero guard exactly.
    z0 = sec11.zscore(obs, normal, std, min_std=0.0)
    check(np.array_equal(z0, z, equal_nan=True),
          "min_std=0.0 is byte-for-byte the original behavior")


def test_zscore_min_std_floor_caps_extreme_z() -> None:
    """B2 lock: a tiny positive clim_std can no longer blow |z| into the hundreds."""
    print("\n[B2 std floor: tiny positive std no longer yields extreme |z|]")
    # A dense-canopy-like pixel: modest anomaly over a near-degenerate climatological
    # std. Unfloored, |z| = 0.15/0.001 = 150 -- the historical failure mode that
    # inflated the old NDMI-supply CSI. NDMI is now a vegetation check, but its z-score
    # still needs the same physical floor.
    obs = np.array([0.25, 0.25, 0.25])
    normal = np.array([0.10, 0.10, 0.10])
    std = np.array([0.001, 0.0005, 0.05])          # two tiny stds + one healthy one
    z_unfloored = sec11.zscore(obs, normal, std)   # old behavior (min_std=0.0)
    check(np.nanmax(np.abs(z_unfloored)) > 100.0,
          f"UNfloored tiny std blows up (max|z|={np.nanmax(np.abs(z_unfloored)):.0f} > 100)")
    z, nf = sec11.zscore(obs, normal, std, min_std=0.02, return_n_floored=True)
    check(np.isnan(z[0]) and np.isnan(z[1]), "both tiny stds floored -> NaN")
    check(nf == 2, f"floored count correct (got {nf}, want 2)")
    check(np.isclose(z[2], 3.0), "healthy std unaffected (0.15/0.05 = 3.0)")
    check(np.nanmax(np.abs(z)) < 100.0,
          f"NO surviving |z| in the hundreds (max|z|={np.nanmax(np.abs(z)):.1f})")


# 3. Legacy-helper coverage: NDMI spatial standardization is no longer the current path.
def test_spatial_standardize() -> None:
    """Legacy helper: spatial z = (x - mu)/sigma over a valid population."""
    print("\n[legacy spatial-standardization helper: z = (x - mu)/sigma]")
    rng = np.random.default_rng(0)
    field = rng.normal(loc=-0.07, scale=0.085, size=(50, 60)).astype("float64")
    field[0, 0] = np.nan
    field[10, 20] = np.nan
    z, mu, sigma = sec11.spatial_standardize(field)
    finite = np.isfinite(field)
    check(abs(float(np.mean(z[finite]))) < 1e-9, "z mean ~0 over reference population")
    check(abs(float(np.std(z[finite])) - 1.0) < 1e-9, "z std ~1 over reference population")
    check(np.isnan(z[0, 0]) and np.isnan(z[10, 20]), "invalid (NaN) pixels stay NaN")
    check(abs(mu - float(np.mean(field[finite]))) < 1e-12, "mu = mean of finite pixels")
    check(abs(sigma - float(np.std(field[finite]))) < 1e-12, "sigma = std of finite pixels")


def test_spatial_standardize_constant_field() -> None:
    """Constant field -> all NaN (sigma=0)."""
    print("\n[spatial standardization on constant field -> all NaN]")
    field = np.full((4, 4), 0.3)
    z, mu, sigma = sec11.spatial_standardize(field)
    check(sigma == 0.0, "constant field has sigma 0")
    check(np.isnan(z).all(), "constant field -> z all NaN (no div-by-zero)")


def test_spatial_standardize_refmask() -> None:
    """Spatial standardization with explicit reference mask."""
    print("\n[spatial standardization with explicit reference mask]")
    field = np.array([[0.0, 1.0], [2.0, 100.0]])  # 100 outlier excluded via mask
    ref = np.array([[True, True], [True, False]])
    z, mu, sigma = sec11.spatial_standardize(field, ref_mask=ref)
    check(abs(mu - 1.0) < 1e-12, "mu over ref-mask pixels only (0,1,2 -> 1.0)")
    check(np.isfinite(z[1, 1]), "out-of-population pixel still gets z (pop mu/sigma)")


# 3b. NDMI temporal day-of-year-at-overpass anomaly (new decision B): same
#     anomaly/z formula + std guard as VPD/SM, and it VARIES across overpasses.
def test_ndmi_temporal_zscore_varies_in_time() -> None:
    """NDMI temporal z per overpass; proof it varies in time."""
    # NOTE: uses clim_std=0.05 and assumes config.MIN_STD_NDMI < 0.05 (B2 floor).
    print("\n[NDMI temporal z = (observed - clim_mean)/clim_std per overpass]")
    observed = np.array([
        [[0.20, 0.10], [0.00, -0.10]],     # overpass 0
        [[0.10, 0.05], [0.00, -0.05]],     # overpass 1 (drier-ish)
        [[0.30, 0.20], [0.10, 0.00]],      # overpass 2 (wetter)
    ], dtype="float64")
    clim_mean = np.full((3, 2, 2), 0.10)
    clim_std = np.full((3, 2, 2), 0.05)
    z = sec11.zscore(observed, clim_mean, clim_std)        # exact production call
    check(np.isclose(z[0, 0, 0], 2.0), "z elementwise = (0.20-0.10)/0.05 = 2.0")
    per_op = np.nanmean(z.reshape(z.shape[0], -1), axis=1)
    check(float(np.nanstd(per_op)) > 1e-6,
          f"per-overpass mean z varies (std={np.nanstd(per_op):.4f} > 0)")
    check(not np.allclose(z[0], z[1]), "different overpasses give different z (not static)")


def test_ndmi_temporal_zscore_degenerate_std() -> None:
    """NDMI temporal z: clim_std 0 / non-finite -> NaN (same guard)."""
    # NOTE: uses clim_std=0.05 and assumes config.MIN_STD_NDMI < 0.05 (B2 floor).
    print("\n[NDMI temporal z: clim_std 0 / non-finite -> NaN]")
    observed = np.array([[[0.2, 0.2], [0.2, 0.2]]], dtype="float64")
    clim_mean = np.array([[[0.1, 0.1], [0.1, 0.1]]], dtype="float64")
    clim_std = np.array([[[0.05, 0.0], [np.nan, 0.05]]], dtype="float64")
    z = sec11.zscore(observed, clim_mean, clim_std)
    check(np.isclose(z[0, 0, 0], 2.0), "healthy clim_std divides normally")
    check(np.isnan(z[0, 0, 1]), "clim_std == 0 -> z NaN")
    check(np.isnan(z[0, 1, 0]), "clim_std non-finite -> z NaN")
    check(not np.isinf(z).any(), "no +/-inf produced for NDMI")


# 4. season-part binning + heatwave-window membership (QC checks).
def test_season_part_labels() -> None:
    """Half-month season-part binning."""
    print("\n[half-month season-part binning]")
    check(sec11.season_part_label("2023-06-02") == "Jun a", "early June -> 'Jun a'")
    check(sec11.season_part_label("2023-06-20") == "Jun b", "late June -> 'Jun b'")
    check(sec11.season_part_label("2023-07-15") == "Jul a", "Jul 15 -> 'Jul a' (boundary)")
    check(sec11.season_part_label("2023-07-16") == "Jul b", "Jul 16 -> 'Jul b'")
    check(sec11.season_part_label("2023-09-29") == "Sep b", "late Sep -> 'Sep b'")
    check(sec11.season_part_label("2023-05-15") is None, "outside warm season -> None")
    check(sec11.part_order()[0] == "Jun a" and sec11.part_order()[-1] == "Sep b",
          "part_order calendar-ordered Jun a .. Sep b")


def test_heatwave_window() -> None:
    """2023 peak-heat window membership."""
    print("\n[2023 peak-heat window membership]")
    check(sec11.in_heatwave("2023-07-20"), "mid/late July 2023 in window")
    check(sec11.in_heatwave("2023-06-30"), "2023-06-30 (start) included")
    check(sec11.in_heatwave("2023-07-30"), "2023-07-30 (end) included")
    check(not sec11.in_heatwave("2023-06-15"), "mid-June 2023 before window")
    check(not sec11.in_heatwave("2023-09-01"), "September 2023 after window")


def test_heatwave_enrichment() -> None:
    """Heatwave-window enrichment among highest scores."""
    print("\n[heatwave-window enrichment among highest scores]")
    times = pd.to_datetime([
        "2023-07-10", "2023-07-20", "2023-07-25",     # in-window (high scores)
        "2023-06-05", "2023-06-10", "2023-08-15",
        "2023-08-20", "2023-09-01", "2023-09-10", "2023-09-20"])
    scores = np.array([3.0, 2.9, 2.8, 0.1, 0.2, 0.3, 0.4, 0.0, -0.1, -0.2])
    enr = sec11.heatwave_enrichment(times, scores, top_k=3)
    check(abs(enr["base_frac"] - 0.3) < 1e-9, "base fraction = 3/10 in-window")
    check(abs(enr["top_frac"] - 1.0) < 1e-9, "all top-3 in-window (top_frac=1.0)")
    check(enr["enrichment"] > 3.0 - 1e-9, "enrichment = 1.0/0.3 ~ 3.33x")
    check(enr["hw_ranks"] == [1, 2, 3], "in-window overpasses rank 1,2,3")
    enr2 = sec11.heatwave_enrichment(times, -scores, top_k=3)
    check(enr2["top_frac"] == 0.0 and enr2["enrichment"] == 0.0,
          "in-window at bottom -> 0 enrichment (no false positive)")


def test_season_part_profile_and_spread() -> None:
    """Season-part profile + spread (flatness scalar)."""
    print("\n[season-part profile + spread]")
    times = pd.to_datetime(["2023-06-02", "2023-06-05",       # Jun a
                            "2023-07-20", "2023-07-25",       # Jul b
                            "2023-09-29"])                    # Sep b
    vals = np.array([-2.0, -1.0, 1.0, 1.0, 0.5])
    prof = sec11.season_part_profile(times, vals)
    by = dict(zip(prof["season_part"], prof["mean"]))
    check(abs(by["Jun a"] - (-1.5)) < 1e-9, "Jun a mean = mean(-2,-1) = -1.5")
    check(abs(by["Jul b"] - 1.0) < 1e-9, "Jul b mean = 1.0")
    check(abs(by["Sep b"] - 0.5) < 1e-9, "Sep b mean = 0.5")
    check(int(prof[prof["season_part"] == "Jun a"]["n"].iloc[0]) == 2, "Jun a has 2 samples")
    check(abs(sec11.profile_spread(prof) - 2.5) < 1e-9, "spread = max-min of part means = 2.5")
    check(prof["season_part"].tolist() == ["Jun a", "Jul b", "Sep b"],
          "rows in calendar order, empty parts dropped")


def test_module_constants() -> None:
    """Module constants match protocol / config."""
    print("\n[module constants match protocol / config]")
    import config
    check(config.CLIMATOLOGY_WINDOW_DAYS == 15, "config.CLIMATOLOGY_WINDOW_DAYS == 15 (decision C)")
    check(sec11.TEMPORAL_VARS == ("vpd", "sm"), "VPD + SM get temporal at-hour climatology")
    check(sec11.TEMPORAL_GRID_VAR == "ndmi", "NDMI is the temporal doy-at-overpass var")
    check(len(sec11.SEASON_PARTS) == 8, "8 half-month season parts (Jun a .. Sep b)")
    # B2 z-score std floors: must exist, be floats, and be strictly positive.
    for name in ("MIN_STD_NDMI", "MIN_STD_VPD", "MIN_STD_SM"):
        val = getattr(config, name, None)
        check(isinstance(val, float) and val > 0.0,
              f"config.{name} is a positive float (got {val!r})")


# Direct runner (parity with sibling test modules).
def main() -> int:
    tests = [
        test_doy_window_mask_basic,
        test_climatology_select_at_hour_loyo,
        test_climatology_one_sided_early_season,
        test_anomaly_and_zscore,
        test_zscore_degenerate_std,
        test_zscore_min_std_floor_caps_extreme_z,
        test_spatial_standardize,
        test_spatial_standardize_constant_field,
        test_spatial_standardize_refmask,
        test_ndmi_temporal_zscore_varies_in_time,
        test_ndmi_temporal_zscore_degenerate_std,
        test_season_part_labels,
        test_heatwave_window,
        test_heatwave_enrichment,
        test_season_part_profile_and_spread,
        test_module_constants,
    ]
    print("=" * 64)
    print("Section 11 pure-logic self-test")
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
