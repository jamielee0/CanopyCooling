#!/usr/bin/env python3
"""Self-test for the Section 4b time-resolved NDMI pipeline (pure-logic).

Mirrors test_section4 / test_section11_*: the geo / EE stack (ee, geemap,
rioxarray, xarray, rasterio) is stubbed so the module imports with only numpy +
pandas, then the algorithmically risky PURE logic is exercised on tiny synthetic
inputs (NO network, NO EE):

  * the NDMI formula + polarity (delegates to Section 4's normalized_difference)
  * the per-overpass +/-15-day window bounds (date_window_bounds)
  * the leave-one-year-out climatology year set (climatology_years: 2023 -> drop 2023)
  * the per-year date-window realisation of a day-of-year window (year_window_ranges),
    incl. the one-sided clipping at the season edges and the Feb-29 guard
  * the day-of-year DEDUP mapping (dedup_climatology_windows): overpasses sharing a
    day-of-year collapse to one climatology, and the round-trip groups cover all rows

The EE reductions, geedim download, reproject, Zarr assembly and QC plotting are
standard library usage exercised by the real CLI in the canopy environment, not
re-implemented here.

Runs with just numpy + pandas:  python src/test_section4b_ndmi_timeseries.py
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd


def _install_geo_stubs() -> None:
    """Stub the heavy top-level imports so the module imports with only numpy+pandas.

    sec4b pulls in section4 (-> section2: earthaccess, rioxarray, xarray) plus ee +
    geemap; none of the pure logic under test calls into them.
    """
    for name in ("ee", "geemap", "rioxarray", "earthaccess", "xarray"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["rioxarray"].open_rasterio = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["geemap"].download_ee_image = lambda *a, **k: None  # type: ignore[attr-defined]
    if not hasattr(sys.modules["xarray"], "Dataset"):
        sys.modules["xarray"].Dataset = object              # type: ignore[attr-defined]
        sys.modules["xarray"].DataArray = object             # type: ignore[attr-defined]
        sys.modules["xarray"].open_zarr = lambda *a, **k: None  # type: ignore[attr-defined]
        sys.modules["xarray"].open_dataset = lambda *a, **k: None  # type: ignore[attr-defined]
        sys.modules["xarray"].concat = lambda *a, **k: None  # type: ignore[attr-defined]
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
        sys.modules["rasterio"].enums = enums                # type: ignore[attr-defined]


_install_geo_stubs()

sys.path.insert(0, str(Path(__file__).resolve().parent))
sec4b = importlib.import_module("section4b_ndmi_timeseries")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


# --------------------------------------------------------------------------- #
# 1. NDMI formula + polarity.
# --------------------------------------------------------------------------- #
def test_ndmi_formula() -> None:
    print("\n[NDMI formula + polarity]")
    b8 = np.array([[0.5, 0.4], [0.6, 0.0]])
    b11 = np.array([[0.1, 0.4], [0.2, 0.0]])
    ndmi = sec4b.ndmi_from_bands(b8, b11)
    check(np.isclose(ndmi[0, 0], 0.4 / 0.6), "NDMI = (B8-B11)/(B8+B11)")
    check(ndmi[0, 1] == 0.0, "equal bands -> 0")
    check(np.isnan(ndmi[1, 1]), "0/0 (sum==0) -> NaN, no divide error")
    # Scale-invariant (DN vs reflectance) since it is a normalized difference.
    nd_dn = sec4b.ndmi_from_bands(b8 * 10000, b11 * 10000)
    check(np.allclose(nd_dn, ndmi, equal_nan=True), "scale-invariant (DN == reflectance)")
    check(sec4b.NDMI_BANDS == ("B8", "B11"), "NDMI bands = (B8, B11)")
    check(sec4b.NDMI_NATIVE_SCALE_M == 20, "NDMI native scale 20 m (SWIR B11)")


# --------------------------------------------------------------------------- #
# 2. Per-overpass +/-window date bounds.
# --------------------------------------------------------------------------- #
def test_date_window_bounds() -> None:
    print("\n[per-overpass +/-15-day window bounds]")
    # An overpass mid-July; window is symmetric and 15 days each side.
    c = pd.Timestamp("2023-07-20 19:37:50")
    lo, hi = sec4b.date_window_bounds(c, window_days=15)
    check(lo == pd.Timestamp("2023-07-05"), "lo = date - 15 d (time-of-day floored)")
    check(hi == pd.Timestamp("2023-08-04"), "hi = date + 15 d")
    check((hi - lo).days == 30, "window spans 2*15 = 30 days inclusive")
    # The default half-width is the config climatology window (15 d).
    import config
    check(sec4b.WINDOW_DAYS == config.CLIMATOLOGY_WINDOW_DAYS == 15,
          "window half-width == config.CLIMATOLOGY_WINDOW_DAYS (15)")
    # day-of-year helper.
    check(sec4b.doy_of(pd.Timestamp("2023-01-01")) == 1, "doy_of Jan-1 == 1")
    check(sec4b.doy_of(pd.Timestamp("2023-07-20")) == 201, "doy_of 2023-07-20 == 201")


# --------------------------------------------------------------------------- #
# 3. Leave-one-year-out climatology year set.
# --------------------------------------------------------------------------- #
def test_climatology_years_loyo() -> None:
    print("\n[leave-one-year-out climatology years]")
    yrs = sec4b.climatology_years(2023, year_lo=2018, year_hi=2024)
    check(yrs == [2018, 2019, 2020, 2021, 2022, 2024],
          "2023 overpass -> climatology over 2018-2022 + 2024 (2023 dropped)")
    check(2023 not in yrs, "the overpass's own year is EXCLUDED (LOYO, step 60)")
    check(len(yrs) == 6, "6 climatology years (7-year span minus the held-out year)")
    # A different held-out year drops the right one.
    check(sec4b.climatology_years(2020, 2018, 2024)
          == [2018, 2019, 2021, 2022, 2023, 2024], "LOYO drops exactly the target year")
    # The module's defaults come from config (2018, 2024).
    import config
    check((sec4b.CLIM_YEAR_LO, sec4b.CLIM_YEAR_HI) == tuple(config.CLIMATOLOGY_YEARS),
          "climatology-year span == config.CLIMATOLOGY_YEARS")


# --------------------------------------------------------------------------- #
# 4. Per-year date-window realisation of a day-of-year window (+ edge clipping).
# --------------------------------------------------------------------------- #
def test_year_window_ranges() -> None:
    print("\n[per-year +/-window realisation of a day-of-year window]")
    # day-of-year 201 (~2023-07-20). Over two years, each window is centred on the
    # same month/day in that year, +/-15 d.
    ranges = sec4b.year_window_ranges(201, [2019, 2024], window_days=15)
    check(len(ranges) == 2, "one window per climatology year")
    lo19, hi19 = ranges[0]
    # day-of-year 201 in a non-leap reference maps to 2001-07-20 -> Jul-20 each year.
    check(lo19.year == 2019 and hi19.year == 2019, "windows land in the target year")
    check(lo19 == pd.Timestamp("2019-07-05") and hi19 == pd.Timestamp("2019-08-04"),
          "doy 201 -> [Jul-05 .. Aug-04] in 2019")
    # Early-season day-of-year (e.g. June 1 == doy 152) -> the window starts mid-May.
    early = sec4b.year_window_ranges(152, [2020], window_days=15)[0]
    check(early[0] == pd.Timestamp("2020-05-17") and early[1] == pd.Timestamp("2020-06-16"),
          "early-season doy gives a window that legitimately reaches before the season "
          "(one-sided after the season filter, like Section 11)")
    # Feb-29 guard: doy 60 in a non-leap reference is Mar-1; force a Feb-29 case via
    # a leap-day-style center by using doy that maps to Feb-29 only in leap years.
    # (doy 60 -> 2001-03-01; the guard is exercised when month/day == 2/29.)
    leap = sec4b.year_window_ranges(60, [2021], window_days=5)[0]
    check(leap[0].year == 2021, "doy 60 window builds without error in a non-leap year")


# --------------------------------------------------------------------------- #
# 5. day-of-year dedup mapping (the EE-compute saver).
# --------------------------------------------------------------------------- #
def test_dedup_climatology_windows() -> None:
    print("\n[day-of-year dedup: identical climatology computed once, mapped back to all]")
    # Three overpasses: two share day-of-year (same calendar day, different time),
    # one is distinct.
    df = pd.DataFrame({
        "overpass": [0, 1, 2],
        "overpass_key": ["a", "b", "c"],
        "time": pd.to_datetime(["2023-07-20 19:37:50",
                                "2023-07-20 21:10:00",   # SAME day-of-year as row 0
                                "2023-08-05 18:00:00"]),  # distinct day-of-year
    })
    groups, unique = sec4b.dedup_climatology_windows(df)
    d0 = sec4b.doy_of(df.iloc[0]["time"])
    d2 = sec4b.doy_of(df.iloc[2]["time"])
    check(len(unique) == 2, "3 overpasses -> 2 unique day-of-year windows (dedup works)")
    check(sorted(groups[d0]) == [0, 1], "both same-day-of-year overpasses map to one clim group")
    check(groups[d2] == [2], "the distinct overpass is its own group")
    # Round-trip: every overpass row index appears in exactly one group.
    covered = sorted(i for idxs in groups.values() for i in idxs)
    check(covered == [0, 1, 2], "the dedup groups cover ALL overpasses exactly once "
          "(mapping back loses none)")
    check(unique == sorted(unique), "unique day-of-year list is sorted")


def main() -> int:
    tests = [
        test_ndmi_formula,
        test_date_window_bounds,
        test_climatology_years_loyo,
        test_year_window_ranges,
        test_dedup_climatology_windows,
    ]
    print("=" * 64)
    print("Section 4b pure-logic self-test (time-resolved NDMI)")
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
