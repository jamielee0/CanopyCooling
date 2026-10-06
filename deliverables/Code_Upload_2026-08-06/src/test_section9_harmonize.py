#!/usr/bin/env python3
"""Self-test for the Section 9 harmonization (pure-logic).

Stubs the geo stack (rioxarray/xarray/rasterio) so the module imports with only
numpy+pandas, then exercises the risky pure logic: overpass-key round-trip,
resampling-method routing (continuous->bilinear, categorical->nearest), and the
step-49 time matches (ERA5 nearest-hour, exact precip date, drought pentad
contains incl. early-season -> None). Reproject/Zarr/CRS/plotting are not retested.

    python -m pytest src/test_section9_harmonize.py -q
    python src/test_section9_harmonize.py
"""

from __future__ import annotations

import datetime as _dt
import importlib
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd


def _install_geo_stubs() -> None:
    """Stub heavy top-level imports so the module needs only numpy+pandas."""
    for name in ("rioxarray", "xarray"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["rioxarray"].open_rasterio = lambda *a, **k: None  # type: ignore[attr-defined]
    if not hasattr(sys.modules["xarray"], "Dataset"):
        sys.modules["xarray"].Dataset = object         # type: ignore[attr-defined]
        sys.modules["xarray"].DataArray = object         # type: ignore[attr-defined]
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
        sys.modules["rasterio"].enums = enums            # type: ignore[attr-defined]


_install_geo_stubs()

sys.path.insert(0, str(Path(__file__).resolve().parent))
sec9 = importlib.import_module("section9_harmonize")


def test_overpass_key_roundtrip() -> None:
    """Key composition matches Section 3 format and round-trips."""
    t = pd.Timestamp("2023-06-02 19:37:50")
    key = sec9.overpass_key("27821", "006", t)
    assert key == "27821_006_20230602T193750", key
    orbit, scene, ts = sec9.parse_overpass_key(key)
    assert orbit == "27821" and scene == "006", (orbit, scene)
    assert ts == t, ts
    for o, s, iso in [("27943", "004", "2023-06-10 16:20:58"),
                      ("28000", "012", "2023-09-29 20:09:50")]:
        k = sec9.overpass_key(o, s, pd.Timestamp(iso))
        ro, rs, rt = sec9.parse_overpass_key(k)
        assert (ro, rs, rt) == (o, s, pd.Timestamp(iso))


def test_resampling_routing() -> None:
    """Continuous->bilinear; categorical/aggregated->nearest."""
    from rasterio.enums import Resampling
    assert sec9.resampling_for("continuous") == Resampling.bilinear
    assert sec9.resampling_for("categorical") == Resampling.nearest
    assert sec9.resampling_for("aggregated") == Resampling.nearest
    assert sec9.resampling_for("categorical") != Resampling.bilinear  # never bilinear
    try:
        sec9.resampling_for("frobnicate")
        raise AssertionError("unknown kind should raise")
    except ValueError:
        pass


def test_round_to_hour() -> None:
    """ERA5 hour = round overpass UTC to nearest hour."""
    assert sec9.round_to_hour(pd.Timestamp("2023-06-02 19:37:50")) == pd.Timestamp("2023-06-02 20:00:00")
    assert sec9.round_to_hour(pd.Timestamp("2023-06-03 18:49:36")) == pd.Timestamp("2023-06-03 19:00:00")
    assert sec9.round_to_hour(pd.Timestamp("2023-06-10 16:20:58")) == pd.Timestamp("2023-06-10 16:00:00")  # <30min down
    assert sec9.round_to_hour(pd.Timestamp("2023-06-10 16:00:00")) == pd.Timestamp("2023-06-10 16:00:00")  # on hour


def test_overpass_date() -> None:
    """PRISM precip/tmean match = exact UTC calendar date."""
    assert sec9.overpass_date(pd.Timestamp("2023-06-02 19:37:50")) == _dt.date(2023, 6, 2)
    assert sec9.overpass_date(pd.Timestamp("2023-09-29 23:50:00")) == _dt.date(2023, 9, 29)  # no local shift


def test_select_by_time_exact_match_or_nan() -> None:
    """A missing PRISM day becomes NaN; it never borrows an adjacent day's value."""
    times = pd.to_datetime(["2023-06-01", "2023-06-03"])
    assert sec9.exact_time_index(times, "2023-06-01") == 0
    assert sec9.exact_time_index(times, "2023-06-02") is None

    class _Coord:
        values = times.to_numpy()

    class _Var:
        def __init__(self):
            self._values = np.array([[[1.0]], [[3.0]]], dtype="float32")

        def isel(self, *, time):
            return types.SimpleNamespace(values=self._values[time])

    class _Cube:
        def __init__(self):
            self._var = _Var()

        def __getitem__(self, key):
            return _Coord() if key == "time" else self._var

    reference = types.SimpleNamespace(sizes={"y": 1, "x": 1})
    old_assert = sec9._assert_on_grid
    sec9._assert_on_grid = lambda *args, **kwargs: None
    try:
        exact, found = sec9.select_by_time(
            _Cube(), "ppt_30d", "2023-06-01", reference, "synthetic")
        missing, missing_found = sec9.select_by_time(
            _Cube(), "ppt_30d", "2023-06-02", reference, "synthetic")
    finally:
        sec9._assert_on_grid = old_assert

    assert found is True and exact.item() == 1.0
    assert missing_found is False and np.isnan(missing).all()
    assert not np.isclose(missing.item(), 1.0) and not np.isclose(missing.item(), 3.0), \
        "missing date must not select either nearest neighbour"

    try:
        sec9.exact_time_index(pd.to_datetime(["2023-06-01", "2023-06-01"]),
                              "2023-06-01")
        raise AssertionError("duplicate exact dates should raise")
    except ValueError:
        pass


def test_match_pentad_contains() -> None:
    """Drought match = pentad whose 5-day window contains the date."""
    pentads = pd.to_datetime(["2023-06-04", "2023-06-09", "2023-06-14", "2023-06-19"])
    assert sec9.match_pentad("2023-06-10", pentads) == pd.Timestamp("2023-06-09")  # inside window
    assert sec9.match_pentad("2023-06-09", pentads) == pd.Timestamp("2023-06-09")  # start included
    assert sec9.match_pentad("2023-06-13", pentads) == pd.Timestamp("2023-06-09")  # P+4 still in
    assert sec9.match_pentad("2023-06-14", pentads) == pd.Timestamp("2023-06-14")  # next window


def test_match_pentad_early_season_none() -> None:
    """Date before season's first pentad -> None (no stale cross-season fallback)."""
    pentads = pd.to_datetime(["2022-09-27", "2023-06-04", "2023-06-09"])
    assert sec9.match_pentad("2023-06-02", pentads) is None
    assert sec9.match_pentad("2023-06-03", pentads) is None
    assert sec9.match_pentad("2022-09-28", pentads) == pd.Timestamp("2022-09-27")  # 2022 date matches 2022 pentad
    assert sec9.match_pentad("2023-06-05", pentads) == pd.Timestamp("2023-06-04")  # first valid 2023 pentad


def test_build_overpass_index() -> None:
    """Per-overpass index carries keys, matched hour and date, in order."""
    orbit = ["27821", "27836"]
    scene = ["006", "004"]
    time = pd.to_datetime(["2023-06-02 19:37:50", "2023-06-03 18:49:36"])
    idx = sec9.build_overpass_index(orbit, scene, time)
    assert list(idx["overpass_key"]) == ["27821_006_20230602T193750", "27836_004_20230603T184936"]
    assert list(idx["era5_hour"]) == [pd.Timestamp("2023-06-02 20:00"), pd.Timestamp("2023-06-03 19:00")]
    assert [pd.Timestamp(d).date() for d in idx["precip_date"]] == [_dt.date(2023, 6, 2), _dt.date(2023, 6, 3)]
    assert list(idx["orbit"]) == orbit and list(idx["scene"]) == scene


def test_layer_inventory_constants() -> None:
    """Layer inventory matches the protocol continuous/categorical split."""
    assert list(sec9.STATIC_CATEGORICAL) == ["landcover_class"]  # only categorical static
    for v in ("ndvi", "ndmi", "impervious", "canopy", "median_income", "pct_poc", "svi"):
        assert v in sec9.STATIC_CONTINUOUS
    assert sec9.ERA5_VARS == ("vpd", "sm")
    assert sec9.PRECIP_VARS == ("ppt_30d", "ppt_60d", "ppt_90d")
    assert sec9.DROUGHT_VARS == ("pdsi", "spei30d", "spei90d")
    assert sec9.PENTAD_WIDTH_DAYS == 5


def main() -> int:
    tests = [
        test_overpass_key_roundtrip,
        test_resampling_routing,
        test_round_to_hour,
        test_overpass_date,
        test_select_by_time_exact_match_or_nan,
        test_match_pentad_contains,
        test_match_pentad_early_season_none,
        test_build_overpass_index,
        test_layer_inventory_constants,
    ]
    print("=" * 64)
    print("Section 9 pure-logic self-test")
    print("=" * 64)
    failures: list[str] = []
    for t in tests:
        try:
            t()
            print(f"  ok:   {t.__name__}")
        except AssertionError as exc:
            failures.append(f"{t.__name__}: {exc}")
            print(f"  FAIL: {t.__name__}: {exc}")
    print("\n" + "=" * 64)
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
