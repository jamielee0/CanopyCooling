#!/usr/bin/env python3
"""Self-test for the Section 7 precip/drought pipeline (pure-logic).

Mirrors test_section2/3/4_*: the geo / EE stack (rioxarray, xarray, rasterio, ee,
geemap, earthaccess) is stubbed so the module imports without it, then the
algorithmically risky pure logic is exercised on synthetic data:

  * the antecedent rolling-sum semantics: "preceding N days" excluding the
    observation day (and the inclusive variant), incomplete windows -> NaN, and
    NaN-in-window -> NaN (an incomplete record never reads as complete)
  * the 1-D and 3-D (gridded) antecedent results agree pixel-by-pixel
  * the date / URL / filename helpers (season + daily date ranges, PRISM URL)
  * the PRISM zip raster-member picker (.tif preferred, .bil fallback)
  * the GRIDMET DROUGHT toBands band-name parser -> (yyyymmdd, variable)
  * the manifest row built for a download (schema + checksum prefix)

The HTTP download, EE compute, geedim download, reproject and Zarr writing are
standard library usage exercised by the real CLI in an authenticated environment,
not re-implemented here.

Runs with just numpy + pandas:  python src/test_section7_precip_drought.py
"""

from __future__ import annotations

import datetime as _dt
import importlib
import sys
import types
from pathlib import Path

import numpy as np


def _install_geo_stubs() -> None:
    """Stub the heavy top-level imports so the module imports with only numpy+pandas."""
    for name in ("ee", "geemap", "rioxarray", "earthaccess", "xarray"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["rioxarray"].open_rasterio = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["geemap"].download_ee_image = lambda *a, **k: None  # type: ignore[attr-defined]
    if not hasattr(sys.modules["xarray"], "Dataset"):
        sys.modules["xarray"].Dataset = object       # type: ignore[attr-defined]
        sys.modules["xarray"].DataArray = object      # type: ignore[attr-defined]
        sys.modules["xarray"].concat = lambda *a, **k: None  # type: ignore[attr-defined]
        sys.modules["xarray"].open_zarr = lambda *a, **k: None  # type: ignore[attr-defined]
    if "rasterio" not in sys.modules:
        sys.modules["rasterio"] = types.ModuleType("rasterio")
    if "rasterio.enums" not in sys.modules:
        enums = types.ModuleType("rasterio.enums")

        class _Resampling:
            bilinear = "bilinear"
            nearest = "nearest"

        enums.Resampling = _Resampling
        sys.modules["rasterio.enums"] = enums
        sys.modules["rasterio"].enums = enums         # type: ignore[attr-defined]


_install_geo_stubs()

sys.path.insert(0, str(Path(__file__).resolve().parent))
sec7 = importlib.import_module("section7_precip_drought")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


def test_antecedent_exclusive() -> None:
    print("\n[antecedent sum: preceding N days, EXCLUDING the observation day]")
    daily = np.array([1, 2, 3, 4, 5, 6], dtype="float64")
    out = sec7.antecedent_sum(daily, window=2, inclusive=False)
    # t<2 incomplete -> NaN; t=2: days[0,1]=3; t=3: 5; t=4: 7; t=5: 9
    check(np.isnan(out[0]) and np.isnan(out[1]), "first window-1 days are NaN (incomplete)")
    check(out.tolist()[2:] == [3.0, 5.0, 7.0, 9.0],
          "exclusive 2-day totals = [3,5,7,9] (window is [t-2, t-1])")
    check(sec7.ANTECEDENT_INCLUSIVE is False, "module default is exclusive ('preceding')")
    check(sec7.ANTECEDENT_WINDOWS == (30, 60, 90), "windows are 30/60/90 days (step 38)")


def test_antecedent_inclusive() -> None:
    print("\n[antecedent sum: inclusive N-day total ending on the day]")
    daily = np.array([1, 2, 3, 4, 5, 6], dtype="float64")
    out = sec7.antecedent_sum(daily, window=2, inclusive=True)
    # t=0 incomplete; t=1: days[0,1]=3; t=2: 5; ... t=5: days[4,5]=11
    check(np.isnan(out[0]), "day 0 incomplete -> NaN")
    check(out.tolist()[1:] == [3.0, 5.0, 7.0, 9.0, 11.0],
          "inclusive 2-day totals = [3,5,7,9,11] (window is [t-1, t])")


def test_antecedent_nan_propagates() -> None:
    print("\n[antecedent sum: a NaN inside the window -> NaN (never undercount)]")
    daily = np.array([1, np.nan, 3, 4], dtype="float64")
    out = sec7.antecedent_sum(daily, window=2, inclusive=False)
    # t=2 window=[0,1] contains NaN -> NaN; t=3 window=[1,2] contains NaN -> NaN
    check(np.isnan(out[2]) and np.isnan(out[3]),
          "windows overlapping the NaN day are NaN, not a smaller partial sum")


def test_antecedent_gridded_matches_1d() -> None:
    print("\n[antecedent sum: 3-D (time,y,x) agrees with per-pixel 1-D]")
    rng = np.arange(7 * 2 * 2, dtype="float64").reshape(7, 2, 2)
    grid = sec7.antecedent_sum(rng, window=3, inclusive=False)
    px = sec7.antecedent_sum(rng[:, 1, 0], window=3, inclusive=False)
    check(np.allclose(grid[:, 1, 0], px, equal_nan=True),
          "gridded antecedent matches the 1-D series at pixel (1,0)")
    check(grid.shape == (7, 2, 2), "gridded antecedent keeps (time,y,x) shape")


def test_date_helpers() -> None:
    print("\n[date / URL / filename helpers]")
    s = sec7.season_dates([2023], ("06-01", "09-30"))
    check(s[0] == _dt.date(2023, 6, 1) and s[-1] == _dt.date(2023, 9, 30) and len(s) == 122,
          "season_dates(2023) spans Jun 1..Sep 30 = 122 days")
    multi = sec7.season_dates([2018, 2019])
    check(len(multi) == 122 + 122, "season_dates concatenates each year's warm season")
    d = sec7.daily_dates("2018-01-01", "2018-01-03")
    check(d == [_dt.date(2018, 1, 1), _dt.date(2018, 1, 2), _dt.date(2018, 1, 3)],
          "daily_dates is inclusive of both endpoints")
    url = sec7.prism_url("ppt", _dt.date(2018, 6, 1))
    check(url.endswith("/get/us/4km/ppt/20180601"), "PRISM URL uses get/us/4km + YYYYMMDD")
    check(sec7.prism_raw_filename("tmean", _dt.date(2023, 7, 4)) == "prism_tmean_20230704_bbox.tif",
          "PRISM raw filename encodes element + date + bbox tag")


def test_pick_raster_member() -> None:
    print("\n[PRISM zip raster-member picker]")
    names = ["prism_ppt_us_25m_20180601.info.txt", "prism_ppt_us_25m_20180601.prj",
             "prism_ppt_us_25m_20180601.tif", "prism_ppt_us_25m_20180601.xml"]
    check(sec7.pick_raster_member(names).endswith(".tif"), "prefers the .tif member")
    check(sec7.pick_raster_member(["a.hdr", "a.bil", "a.prj"]).endswith(".bil"),
          "falls back to .bil when there is no .tif")
    try:
        sec7.pick_raster_member(["a.prj", "a.xml"])
        check(False, "no raster -> ValueError")
    except ValueError:
        check(True, "no raster -> ValueError")


def test_parse_drought_band() -> None:
    print("\n[GRIDMET DROUGHT toBands band-name parser]")
    check(sec7.parse_drought_band("20180601_pdsi") == ("20180601", "pdsi"),
          "'20180601_pdsi' -> ('20180601','pdsi')")
    check(sec7.parse_drought_band("20230705_spei90d") == ("20230705", "spei90d"),
          "'20230705_spei90d' -> ('20230705','spei90d')")
    check(sec7.parse_drought_band("0_pdsi") == (None, "pdsi"),
          "positional '0_pdsi' -> (None,'pdsi') (date supplied from the time list)")
    check(sec7.parse_drought_band("spei30d") == (None, "spei30d"),
          "bare variable name -> (None, var)")
    try:
        sec7.parse_drought_band("20230705_eddi30d")
        check(False, "unknown variable -> ValueError")
    except ValueError:
        check(True, "unknown variable -> ValueError")
    check(sec7.DROUGHT_VARS == ("pdsi", "spei30d", "spei90d"),
          "drought vars = pdsi + 30/90-day SPEI (match antecedent windows)")


def test_manifest_row() -> None:
    print("\n[manifest row for a download]")
    import tempfile
    import pandas as pd

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        raw = d / "prism_ppt_20180601_bbox.tif"
        raw.write_bytes(b"fake-geotiff-bytes")
        manifest = d / "manifest.csv"
        row = {
            "source": f"{sec7.prism_url('ppt', _dt.date(2018, 6, 1))} (PRISM daily ppt; bbox subset)",
            "dataset": sec7.PRISM_DATASET_ID,
            "filename": raw.name,
            "download_date": "2026-06-12",
            "checksum": f"sha256:{sec7.sha256_file(raw)}",
        }
        sec7.append_to_manifest([row], manifest_csv=manifest)
        df = pd.read_csv(manifest)
        check(list(df.columns) == ["source", "dataset", "filename", "download_date", "checksum"],
              "manifest schema matches Section 0")
        check(df.iloc[0]["dataset"] == "PRISM_daily_4km", "PRISM dataset id recorded")
        check(str(df.iloc[0]["checksum"]).startswith("sha256:"), "sha256 checksum prefix")


def test_year_filter_dates() -> None:
    print("\n[drought per-year filter dates clamp to the project period]")
    check(sec7._year_filter_dates(2018) == ("2018-01-01", "2019-01-01"),
          "a full interior year is [Jan 1, next Jan 1)")
    check(sec7._year_filter_dates(2024) == ("2024-01-01", "2024-10-01"),
          "2024 is clamped to the protocol end (Sep 30 -> exclusive Oct 1)")


def main() -> int:
    tests = [
        test_antecedent_exclusive,
        test_antecedent_inclusive,
        test_antecedent_nan_propagates,
        test_antecedent_gridded_matches_1d,
        test_date_helpers,
        test_pick_raster_member,
        test_parse_drought_band,
        test_manifest_row,
        test_year_filter_dates,
    ]
    print("=" * 64)
    print("Section 7 pure-logic self-test")
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
