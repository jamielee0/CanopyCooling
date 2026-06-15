#!/usr/bin/env python3
"""Self-test for the Section 9 harmonization pipeline (pure-logic).

Mirrors test_section2-8_*: the geo stack (rioxarray, xarray, rasterio) is stubbed
so the module imports with only numpy + pandas, then the algorithmically risky
PURE logic is exercised on synthetic data:

  * overpass-key composition ``{orbit}_{scene}_{YYYYMMDDTHHMMSS}`` and its inverse
    parse -- the key that aligns the LST cube (no key coord) to ET/ESI/links
  * the resampling-method ROUTING (continuous -> bilinear; categorical/aggregated
    -> nearest) -- the Section 9 pitfall guard
  * the step-49 TIME-MATCHING rules: ERA5 nearest-hour rounding, the exact precip
    DATE, and the drought PENTAD "window-contains" match (incl. the early-season
    no-pentad -> None case that must NOT fall back to a stale cross-season pentad)
  * the per-overpass index builder (keys, matched hour, matched date) in order

The reproject, Zarr assembly/write, CRS round-trip and matplotlib glue are
standard library usage exercised by the real CLI in the canopy environment (and by
the end-to-end run), not re-implemented here.

Runs with just numpy + pandas (pytest-discoverable):
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
    """Stub the heavy top-level imports so the module imports with only numpy+pandas."""
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


# --------------------------------------------------------------------------- #
# Tests (plain asserts -> pytest-discoverable; also run from main()).
# --------------------------------------------------------------------------- #
def test_overpass_key_roundtrip() -> None:
    """Key composition matches the Section 3 format and round-trips."""
    t = pd.Timestamp("2023-06-02 19:37:50")
    key = sec9.overpass_key("27821", "006", t)
    assert key == "27821_006_20230602T193750", key
    orbit, scene, ts = sec9.parse_overpass_key(key)
    assert orbit == "27821" and scene == "006", (orbit, scene)
    assert ts == t, ts
    # round-trip a few more
    for o, s, iso in [("27943", "004", "2023-06-10 16:20:58"),
                      ("28000", "012", "2023-09-29 20:09:50")]:
        k = sec9.overpass_key(o, s, pd.Timestamp(iso))
        ro, rs, rt = sec9.parse_overpass_key(k)
        assert (ro, rs, rt) == (o, s, pd.Timestamp(iso))


def test_resampling_routing() -> None:
    """Continuous -> bilinear; categorical/aggregated -> nearest (step 48 / pitfall)."""
    from rasterio.enums import Resampling
    assert sec9.resampling_for("continuous") == Resampling.bilinear
    assert sec9.resampling_for("categorical") == Resampling.nearest
    assert sec9.resampling_for("aggregated") == Resampling.nearest
    # the categorical land-cover layer must never route to bilinear
    assert sec9.resampling_for("categorical") != Resampling.bilinear
    try:
        sec9.resampling_for("frobnicate")
        raise AssertionError("unknown kind should raise")
    except ValueError:
        pass


def test_round_to_hour() -> None:
    """ERA5 hour match = round overpass UTC to the NEAREST hour (step 49)."""
    assert sec9.round_to_hour(pd.Timestamp("2023-06-02 19:37:50")) == pd.Timestamp("2023-06-02 20:00:00")
    assert sec9.round_to_hour(pd.Timestamp("2023-06-03 18:49:36")) == pd.Timestamp("2023-06-03 19:00:00")
    # down-rounds when < 30 min past the hour
    assert sec9.round_to_hour(pd.Timestamp("2023-06-10 16:20:58")) == pd.Timestamp("2023-06-10 16:00:00")
    # exactly on the hour stays put
    assert sec9.round_to_hour(pd.Timestamp("2023-06-10 16:00:00")) == pd.Timestamp("2023-06-10 16:00:00")


def test_overpass_date() -> None:
    """PRISM precip/tmean match = the exact calendar (UTC) date (step 49)."""
    assert sec9.overpass_date(pd.Timestamp("2023-06-02 19:37:50")) == _dt.date(2023, 6, 2)
    # late-evening UTC overpass keeps its own UTC date (no local-time shift)
    assert sec9.overpass_date(pd.Timestamp("2023-09-29 23:50:00")) == _dt.date(2023, 9, 29)


def test_match_pentad_contains() -> None:
    """Drought match = the pentad whose 5-day window CONTAINS the date (step 49)."""
    # warm-season pentads spaced 5 days (as in the delivered GRIDMET cube)
    pentads = pd.to_datetime(["2023-06-04", "2023-06-09", "2023-06-14", "2023-06-19"])
    # a date inside [2023-06-09, 2023-06-14) -> 2023-06-09
    assert sec9.match_pentad("2023-06-10", pentads) == pd.Timestamp("2023-06-09")
    # the pentad start itself is included (P <= D)
    assert sec9.match_pentad("2023-06-09", pentads) == pd.Timestamp("2023-06-09")
    # the last day of a window (P+4) is still inside [P, P+5)
    assert sec9.match_pentad("2023-06-13", pentads) == pd.Timestamp("2023-06-09")
    # the next pentad start flips to the next window
    assert sec9.match_pentad("2023-06-14", pentads) == pd.Timestamp("2023-06-14")


def test_match_pentad_early_season_none() -> None:
    """An overpass before the season's first pentad has NO containing pentad -> None.

    It must NOT fall back to the previous season's last pentad (stale, cross-season).
    This is the real 2023-06-02/-03 case: first 2023 pentad is 2023-06-04, and the
    only earlier pentads are from 2022.
    """
    pentads = pd.to_datetime(["2022-09-27", "2023-06-04", "2023-06-09"])
    assert sec9.match_pentad("2023-06-02", pentads) is None
    assert sec9.match_pentad("2023-06-03", pentads) is None
    # 2022-09-27 covers [2022-09-27, 2022-10-02); a date in there matches it,
    # but a June-2023 date does not (so it is never wrongly assigned).
    assert sec9.match_pentad("2022-09-28", pentads) == pd.Timestamp("2022-09-27")
    # and the first valid 2023 pentad still matches normally
    assert sec9.match_pentad("2023-06-05", pentads) == pd.Timestamp("2023-06-04")


def test_build_overpass_index() -> None:
    """The per-overpass index carries keys, matched hour and matched date, in order."""
    orbit = ["27821", "27836"]
    scene = ["006", "004"]
    time = pd.to_datetime(["2023-06-02 19:37:50", "2023-06-03 18:49:36"])
    idx = sec9.build_overpass_index(orbit, scene, time)
    assert list(idx["overpass_key"]) == ["27821_006_20230602T193750", "27836_004_20230603T184936"]
    assert list(idx["era5_hour"]) == [pd.Timestamp("2023-06-02 20:00"), pd.Timestamp("2023-06-03 19:00")]
    assert [pd.Timestamp(d).date() for d in idx["precip_date"]] == [_dt.date(2023, 6, 2), _dt.date(2023, 6, 3)]
    assert list(idx["orbit"]) == orbit and list(idx["scene"]) == scene


def test_layer_inventory_constants() -> None:
    """The layer inventory matches the protocol's continuous/categorical split."""
    # land-cover class is the ONLY categorical static layer (never bilinear)
    assert list(sec9.STATIC_CATEGORICAL) == ["landcover_class"]
    # neighborhood attributes + indices live among the continuous/aggregated statics
    for v in ("ndvi", "ndmi", "impervious", "canopy", "median_income", "pct_poc", "svi"):
        assert v in sec9.STATIC_CONTINUOUS
    # time-varying driver groups
    assert sec9.ERA5_VARS == ("vpd", "sm")
    assert sec9.PRECIP_VARS == ("ppt_30d", "ppt_60d", "ppt_90d")
    assert sec9.DROUGHT_VARS == ("pdsi", "spei30d", "spei90d")
    assert sec9.PENTAD_WIDTH_DAYS == 5


# --------------------------------------------------------------------------- #
# Direct runner (parity with the sibling test modules).
# --------------------------------------------------------------------------- #
def main() -> int:
    tests = [
        test_overpass_key_roundtrip,
        test_resampling_routing,
        test_round_to_hour,
        test_overpass_date,
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
