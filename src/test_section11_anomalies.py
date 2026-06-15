#!/usr/bin/env python3
"""Self-test for the Section 11 anomaly / deseasonalization pipeline (pure-logic).

Mirrors test_section2-10_*: the geo stack (rioxarray, xarray, rasterio) is stubbed
so the module imports with only numpy + pandas, then the algorithmically risky PURE
logic is exercised on tiny SYNTHETIC arrays (NO network, NO full .nc):

  * the +/-15-day day-of-year MOVING-WINDOW selection at a FIXED hour with
    LEAVE-ONE-YEAR-OUT (steps 58-60) -- incl. the one-sided early/late-season window
  * the anomaly = observed - normal and z = anomaly / std formulas (steps 2-3), and
    the degenerate-std (zero / non-finite) -> NaN guard
  * the NDMI SPATIAL standardization z = (x - mu)/sigma (decision B): mean ~0 / std
    ~1 over the reference population, NaN preserved, constant-field -> NaN
  * the half-month SEASON-PART binning used for the seasonal-cycle flatness check
  * the 2023-heatwave-window membership test (the extreme-date QC expectation)

The ERA5 climatology reduction, native->70 m reproject, Zarr assembly/write, CRS
round-trip and matplotlib glue are standard library usage exercised by the real CLI
in the canopy environment (and by the end-to-end run), not re-implemented here.

Runs with just numpy + pandas:  python src/test_section11_anomalies.py
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd


def _install_geo_stubs() -> None:
    """Stub the heavy top-level imports so the module imports with only numpy+pandas."""
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


# --------------------------------------------------------------------------- #
# 1. day-of-year +/-window moving-window selection at a fixed hour, LOYO.
# --------------------------------------------------------------------------- #
def _synthetic_hourly():
    """A tiny hourly index over 3 years (2018-2020), Jun-Sep, used by the window tests."""
    times = pd.date_range("2018-06-01", "2020-09-30 23:00", freq="h")
    times = times[(times.month >= 6) & (times.month <= 9)]
    return (times.dayofyear.to_numpy(), times.hour.to_numpy(), times.year.to_numpy(), times)


def test_doy_window_mask_basic() -> None:
    print("\n[day-of-year +/-15 window mask (step 58)]")
    doys = np.array([180, 185, 190, 195, 200, 205, 210, 215, 220])
    m = sec11.doy_window_mask(doys, target_doy=200, window_days=15)
    # within +/-15 of 200 -> [185..215] inclusive
    check(doys[m].tolist() == [185, 190, 195, 200, 205, 210, 215],
          "window keeps day-of-year in [target-15, target+15]")
    # boundary is inclusive
    check(sec11.doy_window_mask(np.array([185, 215]), 200, 15).all(),
          "the +/-15 boundary days are included")
    check(not sec11.doy_window_mask(np.array([184, 216]), 200, 15).any(),
          "just outside +/-15 is excluded")


def test_climatology_select_at_hour_loyo() -> None:
    print("\n[climatology sample selection: +/-15d, SAME hour, leave-one-year-out (58-60)]")
    doys, hours, years, _ = _synthetic_hourly()
    # target: doy 200, hour 20, year 2019 (the LOYO year to drop)
    mask = sec11.climatology_select_mask(doys, hours, years, target_doy=200,
                                         target_hour=20, target_year=2019, window_days=15)
    # every selected sample must be hour 20, within +/-15 of doy 200, and NOT 2019
    check((hours[mask] == 20).all(), "all selected samples are at the matched hour (step 59)")
    check((np.abs(doys[mask] - 200) <= 15).all(), "all within +/-15 day-of-year (step 58)")
    check((years[mask] != 2019).all(), "the observation's own year is excluded (LOYO, step 60)")
    # with 2 remaining years (2018, 2020) and a full 31-day window -> 2*31 = 62 samples
    check(int(mask.sum()) == 62,
          f"2 LOYO years x 31 window-days @ 1 hour = 62 samples (got {int(mask.sum())})")
    # if we DIDN'T drop the year it would be 3*31 = 93 -> proves LOYO removed exactly one year
    full = sec11.climatology_select_mask(doys, hours, years, 200, 20, 9999, 15)  # drop none
    check(int(full.sum()) == 93 and int(full.sum()) - int(mask.sum()) == 31,
          "leaving the year in would add exactly one year's 31 samples (93 vs 62)")


def test_climatology_one_sided_early_season() -> None:
    print("\n[one-sided window at the season edge (early June) -- expected, documented]")
    doys, hours, years, _ = _synthetic_hourly()
    # doy 153 = ~Jun 2; the season starts Jun 1 (doy ~152), so the window is clipped
    # below -> one-sided. Across 2 LOYO years, days available are doy 152..168 (17 days).
    mask = sec11.climatology_select_mask(doys, hours, years, target_doy=153,
                                         target_hour=12, target_year=2019, window_days=15)
    sel_doys = doys[mask]
    check(sel_doys.min() >= 152, "early-season window is clipped at the season start (no wraparound)")
    check(sel_doys.max() <= 168, "early-season window extends only +15 days forward")
    # one-sided: fewer than the full 2*31 samples
    check(int(mask.sum()) < 62 and int(mask.sum()) > 0,
          f"one-sided window has fewer-but-nonzero samples (got {int(mask.sum())})")


# --------------------------------------------------------------------------- #
# 2. anomaly / z-score formulas + degenerate-std guard.
# --------------------------------------------------------------------------- #
def test_anomaly_and_zscore() -> None:
    print("\n[anomaly = obs - normal; z = anomaly / std (steps 2-3)]")
    obs = np.array([3.0, 5.0, 1.0])
    normal = np.array([2.0, 2.0, 2.0])
    std = np.array([1.0, 2.0, 0.5])
    a = sec11.anomaly(obs, normal)
    check(a.tolist() == [1.0, 3.0, -1.0], "anomaly = observed - normal")
    z = sec11.zscore(obs, normal, std)
    check(np.allclose(z, [1.0, 1.5, -2.0]), "z = anomaly / std")
    # a known mean-0/std-1 sanity: standardizing a sample by its own mean/std
    x = np.array([10.0, 12.0, 14.0, 16.0, 18.0])
    zz = sec11.zscore(x, np.mean(x), np.std(x))
    check(abs(float(np.mean(zz))) < 1e-12 and abs(float(np.std(zz)) - 1.0) < 1e-12,
          "standardizing by the sample mean/std gives mean 0, std 1")


def test_zscore_degenerate_std() -> None:
    print("\n[degenerate std (0 / non-finite) -> NaN, never +/-inf]")
    obs = np.array([3.0, 5.0, 7.0])
    normal = np.array([2.0, 2.0, 2.0])
    std = np.array([0.0, np.nan, 2.0])
    z = sec11.zscore(obs, normal, std)
    check(np.isnan(z[0]), "std == 0 -> z is NaN (degenerate climatology, e.g. 1-sample window)")
    check(np.isnan(z[1]), "std non-finite -> z is NaN")
    check(np.isclose(z[2], 2.5), "a healthy std still divides normally")
    check(np.isfinite(z[2]) and not np.isinf(z).any(), "no +/-inf is ever produced")


# --------------------------------------------------------------------------- #
# 3. NDMI spatial standardization (decision B).
# --------------------------------------------------------------------------- #
def test_spatial_standardize() -> None:
    print("\n[NDMI spatial standardization z = (x - mu)/sigma over the valid population]")
    rng = np.random.default_rng(0)
    field = rng.normal(loc=-0.07, scale=0.085, size=(50, 60)).astype("float64")
    # punch some NaNs (invalid pixels) that must be excluded from mu/sigma and stay NaN
    field[0, 0] = np.nan
    field[10, 20] = np.nan
    z, mu, sigma = sec11.spatial_standardize(field)
    finite = np.isfinite(field)
    check(abs(float(np.mean(z[finite]))) < 1e-9,
          "z mean ~0 over the reference population (by construction)")
    check(abs(float(np.std(z[finite])) - 1.0) < 1e-9,
          "z std ~1 over the reference population (by construction)")
    check(np.isnan(z[0, 0]) and np.isnan(z[10, 20]), "invalid (NaN) pixels stay NaN")
    check(abs(mu - float(np.mean(field[finite]))) < 1e-12, "mu = mean of the finite pixels")
    check(abs(sigma - float(np.std(field[finite]))) < 1e-12, "sigma = std of the finite pixels")


def test_spatial_standardize_constant_field() -> None:
    print("\n[NDMI spatial standardization on a constant field -> all NaN (sigma=0)]")
    field = np.full((4, 4), 0.3)
    z, mu, sigma = sec11.spatial_standardize(field)
    check(sigma == 0.0, "constant field has sigma 0")
    check(np.isnan(z).all(), "constant field -> z all NaN (no divide-by-zero)")


def test_spatial_standardize_refmask() -> None:
    print("\n[NDMI spatial standardization with an explicit reference mask]")
    field = np.array([[0.0, 1.0], [2.0, 100.0]])  # 100 is an outlier we exclude via mask
    ref = np.array([[True, True], [True, False]])
    z, mu, sigma = sec11.spatial_standardize(field, ref_mask=ref)
    check(abs(mu - 1.0) < 1e-12, "mu computed only over the reference-mask pixels (0,1,2 -> 1.0)")
    check(np.isfinite(z[1, 1]), "an out-of-population pixel still gets a z (using pop mu/sigma)")


# --------------------------------------------------------------------------- #
# 4. season-part binning + heatwave-window membership (the QC checks).
# --------------------------------------------------------------------------- #
def test_season_part_labels() -> None:
    print("\n[half-month season-part binning (the seasonal-cycle flatness check)]")
    check(sec11.season_part_label("2023-06-02") == "Jun a", "early June -> 'Jun a'")
    check(sec11.season_part_label("2023-06-20") == "Jun b", "late June -> 'Jun b'")
    check(sec11.season_part_label("2023-07-15") == "Jul a", "Jul 15 -> 'Jul a' (boundary)")
    check(sec11.season_part_label("2023-07-16") == "Jul b", "Jul 16 -> 'Jul b'")
    check(sec11.season_part_label("2023-09-29") == "Sep b", "late Sep -> 'Sep b'")
    check(sec11.season_part_label("2023-05-15") is None, "outside the warm season -> None")
    check(sec11.part_order()[0] == "Jun a" and sec11.part_order()[-1] == "Sep b",
          "part_order is calendar-ordered Jun a .. Sep b")


def test_heatwave_window() -> None:
    print("\n[2023 peak-heat window membership (the extreme-date QC expectation)]")
    check(sec11.in_heatwave("2023-07-20"), "mid/late July 2023 is in the heatwave window")
    check(sec11.in_heatwave("2023-06-30"), "2023-06-30 (window start) is included")
    check(sec11.in_heatwave("2023-07-30"), "2023-07-30 (window end) is included")
    check(not sec11.in_heatwave("2023-06-15"), "mid-June 2023 is before the window")
    check(not sec11.in_heatwave("2023-09-01"), "September 2023 is after the window")


def test_heatwave_enrichment() -> None:
    print("\n[heatwave-window enrichment among the highest scores (robust extreme check)]")
    # 10 overpasses: 3 in the July window. Give the in-window ones high scores so the
    # window is over-represented at the top.
    times = pd.to_datetime([
        "2023-07-10", "2023-07-20", "2023-07-25",     # in-window (high scores)
        "2023-06-05", "2023-06-10", "2023-08-15",
        "2023-08-20", "2023-09-01", "2023-09-10", "2023-09-20"])
    scores = np.array([3.0, 2.9, 2.8, 0.1, 0.2, 0.3, 0.4, 0.0, -0.1, -0.2])
    enr = sec11.heatwave_enrichment(times, scores, top_k=3)
    check(abs(enr["base_frac"] - 0.3) < 1e-9, "base fraction = 3/10 in-window")
    check(abs(enr["top_frac"] - 1.0) < 1e-9, "all top-3 are in-window (top_frac=1.0)")
    check(enr["enrichment"] > 3.0 - 1e-9, "enrichment = top_frac/base = 1.0/0.3 ~ 3.33x")
    check(enr["hw_ranks"] == [1, 2, 3], "the 3 in-window overpasses rank 1,2,3 (highest scores)")
    # the reverse: in-window overpasses with the LOWEST scores -> no enrichment
    enr2 = sec11.heatwave_enrichment(times, -scores, top_k=3)
    check(enr2["top_frac"] == 0.0 and enr2["enrichment"] == 0.0,
          "in-window overpasses at the BOTTOM -> 0 enrichment (no false positive)")


def test_season_part_profile_and_spread() -> None:
    print("\n[season-part profile + spread (the flatness scalar)]")
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
    # spread = max(1.0) - min(-1.5) = 2.5
    check(abs(sec11.profile_spread(prof) - 2.5) < 1e-9, "profile spread = max-min of part means = 2.5")
    check(prof["season_part"].tolist() == ["Jun a", "Jul b", "Sep b"],
          "profile rows are in calendar order, empty parts dropped")


def test_module_constants() -> None:
    print("\n[module constants match the protocol / config]")
    import config
    check(config.CLIMATOLOGY_WINDOW_DAYS == 15, "config.CLIMATOLOGY_WINDOW_DAYS == 15 (decision C)")
    check(sec11.TEMPORAL_VARS == ("vpd", "sm"),
          "VPD + soil moisture get the temporal at-hour climatology")
    check(sec11.SPATIAL_VAR == "ndmi", "NDMI is the spatial-standardization (water-supply) var")
    check(len(sec11.SEASON_PARTS) == 8, "8 half-month season parts (Jun a .. Sep b)")


# --------------------------------------------------------------------------- #
# Direct runner (parity with the sibling test modules).
# --------------------------------------------------------------------------- #
def main() -> int:
    tests = [
        test_doy_window_mask_basic,
        test_climatology_select_at_hour_loyo,
        test_climatology_one_sided_early_season,
        test_anomaly_and_zscore,
        test_zscore_degenerate_std,
        test_spatial_standardize,
        test_spatial_standardize_constant_field,
        test_spatial_standardize_refmask,
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
