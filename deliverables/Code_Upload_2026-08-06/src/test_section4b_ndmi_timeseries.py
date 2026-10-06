#!/usr/bin/env python3
"""Self-test for the Section 4b time-resolved NDMI pipeline (pure-logic).

Stubs the geo/EE stack (ee, geemap, rioxarray, xarray, rasterio) so the module
imports with only numpy + pandas, then exercises the risky pure logic on tiny
synthetic inputs (no network, no EE):
  * NDMI formula + polarity
  * per-overpass +/-15-day window bounds
  * leave-one-year-out climatology year set
  * per-year realisation of a day-of-year window (edge clipping, Feb-29 guard)
  * day-of-year dedup mapping (round-trip covers all rows)
  * deterministic observed/climatology count-tile inventory
  * exact integer count statistics, missing sentinel, and diagnostic-only <3 flags
  * retained 60% broad prefilter plus nearest-neighbour count contract

Run: python src/test_section4b_ndmi_timeseries.py
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


def test_ndmi_formula() -> None:
    """NDMI formula + polarity."""
    print("\n[NDMI formula + polarity]")
    b8 = np.array([[0.5, 0.4], [0.6, 0.0]])
    b11 = np.array([[0.1, 0.4], [0.2, 0.0]])
    ndmi = sec4b.ndmi_from_bands(b8, b11)
    check(np.isclose(ndmi[0, 0], 0.4 / 0.6), "NDMI = (B8-B11)/(B8+B11)")
    check(ndmi[0, 1] == 0.0, "equal bands -> 0")
    check(np.isnan(ndmi[1, 1]), "0/0 (sum==0) -> NaN, no divide error")
    nd_dn = sec4b.ndmi_from_bands(b8 * 10000, b11 * 10000)
    check(np.allclose(nd_dn, ndmi, equal_nan=True), "scale-invariant (DN == reflectance)")
    check(sec4b.NDMI_BANDS == ("B8", "B11"), "NDMI bands = (B8, B11)")
    check(sec4b.NDMI_NATIVE_SCALE_M == 20, "NDMI native scale 20 m (SWIR B11)")


def test_date_window_bounds() -> None:
    """Per-overpass +/-15-day window bounds."""
    print("\n[per-overpass +/-15-day window bounds]")
    c = pd.Timestamp("2023-07-20 19:37:50")
    lo, hi = sec4b.date_window_bounds(c, window_days=15)
    check(lo == pd.Timestamp("2023-07-05"), "lo = date - 15 d (time floored)")
    check(hi == pd.Timestamp("2023-08-04"), "hi = date + 15 d")
    check((hi - lo).days == 30, "window spans 2*15 = 30 days")
    import config
    check(sec4b.WINDOW_DAYS == config.CLIMATOLOGY_WINDOW_DAYS == 15,
          "window half-width == config.CLIMATOLOGY_WINDOW_DAYS (15)")
    check(sec4b.doy_of(pd.Timestamp("2023-01-01")) == 1, "doy_of Jan-1 == 1")
    check(sec4b.doy_of(pd.Timestamp("2023-07-20")) == 201, "doy_of 2023-07-20 == 201")


def test_climatology_years_loyo() -> None:
    """Leave-one-year-out climatology year set."""
    print("\n[leave-one-year-out climatology years]")
    yrs = sec4b.climatology_years(2023, year_lo=2018, year_hi=2024)
    check(yrs == [2018, 2019, 2020, 2021, 2022, 2024],
          "2023 overpass -> 2018-2022 + 2024 (2023 dropped)")
    check(2023 not in yrs, "overpass's own year EXCLUDED (LOYO)")
    check(len(yrs) == 6, "6 climatology years (7-span minus held-out)")
    check(sec4b.climatology_years(2020, 2018, 2024)
          == [2018, 2019, 2021, 2022, 2023, 2024], "LOYO drops exactly the target year")
    import config
    check((sec4b.CLIM_YEAR_LO, sec4b.CLIM_YEAR_HI) == tuple(config.CLIMATOLOGY_YEARS),
          "clim-year span == config.CLIMATOLOGY_YEARS")


def test_year_window_ranges() -> None:
    """Per-year realisation of a day-of-year window (+ edge clipping, Feb-29 guard)."""
    print("\n[per-year +/-window realisation of a day-of-year window]")
    ranges = sec4b.year_window_ranges(201, [2019, 2024], window_days=15)
    check(len(ranges) == 2, "one window per climatology year")
    lo19, hi19 = ranges[0]
    check(lo19.year == 2019 and hi19.year == 2019, "windows land in the target year")
    check(lo19 == pd.Timestamp("2019-07-05") and hi19 == pd.Timestamp("2019-08-04"),
          "doy 201 -> [Jul-05 .. Aug-04] in 2019")
    early = sec4b.year_window_ranges(152, [2020], window_days=15)[0]
    check(early[0] == pd.Timestamp("2020-05-17") and early[1] == pd.Timestamp("2020-06-16"),
          "early-season doy reaches before season (one-sided post-filter)")
    leap = sec4b.year_window_ranges(60, [2021], window_days=5)[0]
    check(leap[0].year == 2021, "doy 60 window builds in a non-leap year")


def test_dedup_climatology_windows() -> None:
    """Day-of-year dedup: identical climatology computed once, mapped back to all."""
    print("\n[day-of-year dedup]")
    df = pd.DataFrame({
        "overpass": [0, 1, 2],
        "overpass_key": ["a", "b", "c"],
        "time": pd.to_datetime(["2023-07-20 19:37:50",
                                "2023-07-20 21:10:00",   # SAME doy as row 0
                                "2023-08-05 18:00:00"]),  # distinct doy
    })
    groups, unique = sec4b.dedup_climatology_windows(df)
    d0 = sec4b.doy_of(df.iloc[0]["time"])
    d2 = sec4b.doy_of(df.iloc[2]["time"])
    check(len(unique) == 2, "3 overpasses -> 2 unique doy windows")
    check(sorted(groups[d0]) == [0, 1], "both same-doy overpasses map to one group")
    check(groups[d2] == [2], "distinct overpass is its own group")
    covered = sorted(i for idxs in groups.values() for i in idxs)
    check(covered == [0, 1, 2], "dedup groups cover ALL overpasses exactly once")
    check(unique == sorted(unique), "unique doy list is sorted")


def _tiny_overpasses() -> pd.DataFrame:
    return pd.DataFrame({
        "overpass": [0, 1, 2],
        "overpass_key": ["a", "b", "c"],
        "time": pd.to_datetime(["2023-07-20 19:37:50",
                                "2023-07-20 21:10:00",
                                "2023-08-05 18:00:00"]),
    })


def test_count_tile_inventory() -> None:
    """Observed counts are per-overpass; climatology counts are deduped by DOY."""
    print("\n[resumable count-tile inventory]")
    import tempfile
    df = _tiny_overpasses()
    expected = sec4b.expected_count_tile_names(df)
    check(expected[:3] == ["obs_count_op00.tif", "obs_count_op01.tif",
                           "obs_count_op02.tif"], "one observed count tile per overpass")
    check(len(expected) == 5, "3 observed + 2 unique-DOY climatology counts = 5 files")
    check(len(sec4b.expected_count_tile_names(df, only_overpass=1)) == 2,
          "single-overpass recovery expects one observed + one climatology count")
    with tempfile.TemporaryDirectory() as d:
        raw = Path(d)
        (raw / expected[0]).write_bytes(b"present")
        (raw / expected[-1]).write_bytes(b"present")
        inventory = sec4b.count_cache_inventory(df, raw)
        check(inventory["expected"] == 5 and inventory["present"] == 2
              and inventory["missing"] == 3, "inventory reports exact present/missing totals")
        check(expected[0] not in inventory["missing_names"],
              "present count file is not reported missing")


def test_count_stats_and_flags() -> None:
    """Genuine zero is valid, -1 is unavailable, and count<3 never masks NDMI."""
    print("\n[exact count stats + diagnostic-only low-count flags]")
    counts = np.array([[-1, 0, 1, 2], [3, 4, 5, -1]], dtype="int16")
    stats = sec4b.count_cube_stats(counts)
    check(stats["n_valid"] == 6 and stats["n_missing"] == 2,
          "-1 is missing while genuine zero remains a valid count")
    check(stats["min"] == 0 and stats["median"] == 2.5 and stats["max"] == 5,
          "histogram stats preserve exact min/median/max")
    check(stats["n_lt_threshold"] == 3 and np.isclose(stats["frac_lt_threshold"], 0.5),
          "count<3 identifies exactly 0, 1, and 2")
    flags = sec4b.low_count_flag(counts)
    check(flags.dtype == np.uint8, "low-count flag is uint8")
    check(flags.tolist() == [[0, 1, 1, 1], [0, 0, 0, 0]],
          "missing is not low; counts 0/1/2 are flagged")
    ndmi = np.array([[0.2, np.nan, -0.1, 0.4], [0.0, 0.3, 0.5, -0.2]])
    original = ndmi.copy()
    sec4b.low_count_flag(counts)
    check(np.allclose(ndmi, original, equal_nan=True), "flag calculation does not mask NDMI")


def test_scene_filter_and_resampling_contract() -> None:
    """The broad 60% gate and nearest 70 m count rules stay explicit."""
    print("\n[scene gate + count resampling contract]")
    check(sec4b.MAX_SCENE_CLOUD_PCT == 60.0,
          "scene prefilter remains 60% by explicit decision")
    check("per-pixel scl" in sec4b.sec4.SCENE_PREFILTER_RATIONALE.lower()
          and "primary" in sec4b.sec4.SCENE_PREFILTER_RATIONALE.lower(),
          "per-pixel SCL masking is documented as primary")
    check(sec4b.COUNT_RESAMPLING == "nearest"
          and sec4b.COUNT_DOWNLOAD_RESAMPLING == "near",
          "count metadata and downloader both specify nearest-neighbour")
    help_text = sec4b._build_arg_parser().format_help().lower()
    check("--counts-only" in help_text and "70 m" in help_text and "nearest" in help_text,
          "CLI exposes resumable 70 m nearest count-only retrieval")
    note = sec4b.render_timeseries_coverage_note(
        {"expected": 118, "present": 0, "missing": 118,
         "missing_names": ["obs_count_op00.tif"]})
    check("118" in note and "earth engine" in note.lower() and "never mask ndmi" in note.lower(),
          "coverage note records pending cache totals, retrieval source, and no-mask rule")


def main() -> int:
    tests = [
        test_ndmi_formula,
        test_date_window_bounds,
        test_climatology_years_loyo,
        test_year_window_ranges,
        test_dedup_climatology_windows,
        test_count_tile_inventory,
        test_count_stats_and_flags,
        test_scene_filter_and_resampling_contract,
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
