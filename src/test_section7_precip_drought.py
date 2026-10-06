#!/usr/bin/env python3
"""Self-test for the Section 7 precip/drought pipeline (pure-logic).

Geo/EE stack (rioxarray, xarray, rasterio, ee, geemap, earthaccess) is stubbed so
the module imports without it, then the risky pure logic is exercised on synthetic
data: antecedent rolling-sum semantics (exclusive/inclusive, incomplete->NaN,
NaN-in-window->NaN), 1-D vs 3-D agreement, date/URL/filename helpers, PRISM zip
member picker, GRIDMET DROUGHT band parser, and the download manifest row.
HTTP/EE/geedim/reproject/Zarr are exercised by the real CLI, not here.

Run: python src/test_section7_precip_drought.py
"""

from __future__ import annotations

import datetime as _dt
import importlib
import sys
import types
from pathlib import Path

import numpy as np


def _install_geo_stubs() -> None:
    """Stub heavy top-level imports so the module loads with only numpy+pandas."""
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
    """Exclusive: window is [t-N, t-1]."""
    print("\n[antecedent sum: preceding N days, EXCLUDING observation day]")
    daily = np.array([1, 2, 3, 4, 5, 6], dtype="float64")
    out = sec7.antecedent_sum(daily, window=2, inclusive=False)
    check(np.isnan(out[0]) and np.isnan(out[1]), "first window-1 days NaN (incomplete)")
    check(out.tolist()[2:] == [3.0, 5.0, 7.0, 9.0],
          "exclusive 2-day totals = [3,5,7,9]")
    check(sec7.ANTECEDENT_INCLUSIVE is False, "module default is exclusive")
    check(sec7.ANTECEDENT_WINDOWS == (30, 60, 90), "windows are 30/60/90 days")


def test_antecedent_inclusive() -> None:
    """Inclusive: window is [t-N+1, t]."""
    print("\n[antecedent sum: inclusive N-day total ending on the day]")
    daily = np.array([1, 2, 3, 4, 5, 6], dtype="float64")
    out = sec7.antecedent_sum(daily, window=2, inclusive=True)
    check(np.isnan(out[0]), "day 0 incomplete -> NaN")
    check(out.tolist()[1:] == [3.0, 5.0, 7.0, 9.0, 11.0],
          "inclusive 2-day totals = [3,5,7,9,11]")


def test_antecedent_nan_propagates() -> None:
    """A NaN in the window -> NaN, never a partial sum."""
    print("\n[antecedent sum: NaN inside window -> NaN]")
    daily = np.array([1, np.nan, 3, 4], dtype="float64")
    out = sec7.antecedent_sum(daily, window=2, inclusive=False)
    check(np.isnan(out[2]) and np.isnan(out[3]),
          "windows overlapping the NaN day are NaN, not a partial sum")


def test_antecedent_gridded_matches_1d() -> None:
    """3-D (time,y,x) result agrees with per-pixel 1-D."""
    print("\n[antecedent sum: 3-D agrees with per-pixel 1-D]")
    rng = np.arange(7 * 2 * 2, dtype="float64").reshape(7, 2, 2)
    grid = sec7.antecedent_sum(rng, window=3, inclusive=False)
    px = sec7.antecedent_sum(rng[:, 1, 0], window=3, inclusive=False)
    check(np.allclose(grid[:, 1, 0], px, equal_nan=True),
          "gridded matches 1-D series at pixel (1,0)")
    check(grid.shape == (7, 2, 2), "gridded keeps (time,y,x) shape")


def test_date_helpers() -> None:
    """season_dates / daily_dates / prism_url / prism_raw_filename."""
    print("\n[date / URL / filename helpers]")
    s = sec7.season_dates([2023], ("06-01", "09-30"))
    check(s[0] == _dt.date(2023, 6, 1) and s[-1] == _dt.date(2023, 9, 30) and len(s) == 122,
          "season_dates(2023) = Jun 1..Sep 30 = 122 days")
    multi = sec7.season_dates([2018, 2019])
    check(len(multi) == 122 + 122, "season_dates concatenates each year")
    d = sec7.daily_dates("2018-01-01", "2018-01-03")
    check(d == [_dt.date(2018, 1, 1), _dt.date(2018, 1, 2), _dt.date(2018, 1, 3)],
          "daily_dates inclusive of both endpoints")
    url = sec7.prism_url("ppt", _dt.date(2018, 6, 1))
    check(url.endswith("/get/us/4km/ppt/20180601"), "PRISM URL = get/us/4km + YYYYMMDD")
    check(sec7.prism_raw_filename("tmean", _dt.date(2023, 7, 4)) == "prism_tmean_20230704_bbox.tif",
          "PRISM raw filename = element + date + bbox tag")


def test_pick_raster_member() -> None:
    """PRISM zip member picker: .tif preferred, .bil fallback, else ValueError."""
    print("\n[PRISM zip raster-member picker]")
    names = ["prism_ppt_us_25m_20180601.info.txt", "prism_ppt_us_25m_20180601.prj",
             "prism_ppt_us_25m_20180601.tif", "prism_ppt_us_25m_20180601.xml"]
    check(sec7.pick_raster_member(names).endswith(".tif"), "prefers .tif")
    check(sec7.pick_raster_member(["a.hdr", "a.bil", "a.prj"]).endswith(".bil"),
          "falls back to .bil when no .tif")
    try:
        sec7.pick_raster_member(["a.prj", "a.xml"])
        check(False, "no raster -> ValueError")
    except ValueError:
        check(True, "no raster -> ValueError")


def test_parse_drought_band() -> None:
    """GRIDMET DROUGHT toBands band-name parser -> (yyyymmdd, var)."""
    print("\n[GRIDMET DROUGHT band-name parser]")
    check(sec7.parse_drought_band("20180601_pdsi") == ("20180601", "pdsi"),
          "'20180601_pdsi' -> ('20180601','pdsi')")
    check(sec7.parse_drought_band("20230705_spei90d") == ("20230705", "spei90d"),
          "'20230705_spei90d' -> ('20230705','spei90d')")
    check(sec7.parse_drought_band("0_pdsi") == (None, "pdsi"),
          "positional '0_pdsi' -> (None,'pdsi')")
    check(sec7.parse_drought_band("spei30d") == (None, "spei30d"),
          "bare variable name -> (None, var)")
    try:
        sec7.parse_drought_band("20230705_eddi30d")
        check(False, "unknown variable -> ValueError")
    except ValueError:
        check(True, "unknown variable -> ValueError")
    check(sec7.DROUGHT_VARS == ("pdsi", "spei30d", "spei90d"),
          "drought vars = pdsi + 30/90-day SPEI")


def test_resolve_drought_band_date() -> None:
    """Positional bands use system time; disagreement or missing metadata fails closed."""
    print("\n[GRIDMET DROUGHT band-date resolution]")
    check(sec7.resolve_band_date("0_pdsi", "20230705") == ("20230705", "pdsi"),
          "positional band resolves from system:time_start date")
    check(sec7.resolve_band_date("20230705_spei90d", "20230705")
          == ("20230705", "spei90d"),
          "matching name/system dates are accepted")
    check(sec7.resolve_band_date("20230705_spei30d", None)
          == ("20230705", "spei30d"),
          "dated band remains compatible when system metadata is unavailable")

    for name, fallback in (("0_pdsi", None),
                           ("20230705_pdsi", "20230710"),
                           ("20230230_pdsi", "20230230")):
        try:
            sec7.resolve_band_date(name, fallback)
            check(False, f"unresolvable/inconsistent {name!r} raises")
        except ValueError:
            check(True, f"unresolvable/inconsistent {name!r} raises")


def test_expand_drought_band_dates() -> None:
    """Earth Engine image dates expand in image-major, selected-variable order."""
    print("\n[GRIDMET DROUGHT system-time expansion]")
    dt1 = int(_dt.datetime(2023, 6, 5, tzinfo=_dt.timezone.utc).timestamp() * 1000)
    dt2 = int(_dt.datetime(2023, 6, 10, tzinfo=_dt.timezone.utc).timestamp() * 1000)
    expanded = sec7.expand_drought_band_dates([dt1, dt2], len(sec7.DROUGHT_VARS))
    check(expanded == ["20230605"] * 3 + ["20230610"] * 3,
          "each system date repeats once per selected drought variable")
    dl = sec7.DroughtDownload(2023, None, ["0_pdsi"], "test",
                              band_dates=["20230605"])
    check(dl.band_dates == ["20230605"], "DroughtDownload carries per-band dates")

    try:
        sec7.expand_drought_band_dates([dt1], 0)
        check(False, "zero variables raises")
    except ValueError:
        check(True, "zero variables raises")


def test_manifest_row() -> None:
    """Manifest row schema + sha256 checksum prefix."""
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
    """Drought per-year filter dates clamp to the project period."""
    print("\n[drought per-year filter dates]")
    check(sec7._year_filter_dates(2018) == ("2018-01-01", "2019-01-01"),
          "interior year = [Jan 1, next Jan 1)")
    check(sec7._year_filter_dates(2024) == ("2024-01-01", "2024-10-01"),
          "2024 clamped to protocol end (Oct 1 exclusive)")


def main() -> int:
    tests = [
        test_antecedent_exclusive,
        test_antecedent_inclusive,
        test_antecedent_nan_propagates,
        test_antecedent_gridded_matches_1d,
        test_date_helpers,
        test_pick_raster_member,
        test_parse_drought_band,
        test_resolve_drought_band_date,
        test_expand_drought_band_dates,
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
