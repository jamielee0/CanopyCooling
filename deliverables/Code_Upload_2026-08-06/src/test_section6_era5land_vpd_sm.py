#!/usr/bin/env python3
"""Self-test for the Section 6 ERA5-Land VPD / soil-moisture pure logic.

cdsapi/xarray are stubbed so the module imports, then the risky numpy logic is
exercised on synthetic inputs: CDS request builder, Kelvin->Celsius, Tetens
e(T), VPD, depth-weighted root-zone soil moisture, manifest append/de-dup, and
streaming checksum. NetCDF I/O glue is covered by the real CLI, not here.

Run: python src/test_section6_era5land_vpd_sm.py  (also pytest-discoverable).
"""

from __future__ import annotations

import importlib
import math
import sys
import tempfile
import types
from pathlib import Path

import numpy as np
import pandas as pd


def _install_stubs() -> None:
    cdsapi = sys.modules.setdefault("cdsapi", types.ModuleType("cdsapi"))
    cdsapi.Client = lambda *a, **k: None  # type: ignore[attr-defined]
    if "xarray" not in sys.modules:
        sys.modules["xarray"] = types.ModuleType("xarray")


_install_stubs()

sys.path.insert(0, str(Path(__file__).resolve().parent))
sec6 = importlib.import_module("section6_era5land_vpd_sm")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


def test_request_builder() -> None:
    print("\n[CDS request builder]")
    check(list(sec6.years()) == [2018, 2019, 2020, 2021, 2022, 2023, 2024],
          "years() spans climatology inclusive")
    check(sec6.season_months() == ["06", "07", "08", "09"], "season months Jun-Sep")
    check(len(sec6.all_days()) == 31 and sec6.all_days()[0] == "01"
          and sec6.all_days()[-1] == "31", "days 01..31")
    hours = sec6.all_hours()
    check(len(hours) == 24 and hours[0] == "00:00" and hours[-1] == "23:00",
          "all 24 hours 00:00..23:00")

    # BBOX_LONLAT (min_lon,max_lon,min_lat,max_lat) -> CDS [N,W,S,E].
    check(sec6.area_for_cdsapi() == [33.92, -112.55, 33.20, -111.55],
          "area reordered to [N,W,S,E]")

    req = sec6.build_cds_request(2023, "07")
    check(req["variable"] == [
        "2m_temperature", "2m_dewpoint_temperature",
        "volumetric_soil_water_layer_1", "volumetric_soil_water_layer_2"],
        "four ERA5-Land variables in order")
    check(req["year"] == "2023", "year stringified")
    check(req["month"] == ["07"], "one calendar month per request")
    check(len(req["day"]) == 31, "all days of month")
    check(len(req["time"]) == 24, "all hours")
    check(req["data_format"] == "netcdf", "data_format netcdf")
    check(req["download_format"] == "unarchived", "download_format unarchived")
    check(req["area"] == [33.92, -112.55, 33.20, -111.55], "request area correct")


def test_kelvin_to_celsius() -> None:
    print("\n[Kelvin -> Celsius]")
    check(abs(sec6.kelvin_to_celsius(273.15) - 0.0) < 1e-9, "273.15 K -> 0 C")
    check(abs(sec6.kelvin_to_celsius(300.0) - 26.85) < 1e-9, "300 K -> 26.85 C")
    arr = sec6.kelvin_to_celsius(np.array([273.15, 313.15]))
    check(np.allclose(arr, [0.0, 40.0]), "vectorised over array")


def test_tetens_saturation_vapour_pressure() -> None:
    print("\n[Tetens e(T), kPa]")
    check(abs(sec6.saturation_vapour_pressure_kpa(0.0) - 0.6108) < 1e-12,
          "e(0 C) = 0.6108 kPa")
    check(abs(sec6.saturation_vapour_pressure_kpa(20.0) - 2.338) < 5e-3,
          "e(20 C) ~ 2.338 kPa")
    check(abs(sec6.saturation_vapour_pressure_kpa(30.0) - 4.243) < 5e-3,
          "e(30 C) ~ 4.243 kPa")
    # Closed-form cross-check at arbitrary T.
    t = 37.5
    expected = 0.6108 * math.exp(17.27 * t / (t + 237.3))
    check(abs(sec6.saturation_vapour_pressure_kpa(t) - expected) < 1e-12,
          "matches closed-form Tetens at T=37.5 C")
    ts = np.array([0.0, 10.0, 20.0, 30.0, 40.0])
    es = sec6.saturation_vapour_pressure_kpa(ts)
    check(np.all(np.diff(es) > 0), "e(T) increases with T")


def test_vpd() -> None:
    print("\n[VPD = e(t2m) - e(d2m), kPa]")
    check(abs(sec6.vpd_kpa(310.0, 310.0)) < 1e-12, "t2m == d2m -> VPD = 0")
    # Hot dry Phoenix afternoon: 40 C air, 10 C dewpoint.
    expect = (0.6108 * math.exp(17.27 * 40 / (40 + 237.3))
              - 0.6108 * math.exp(17.27 * 10 / (10 + 237.3)))
    check(abs(sec6.vpd_kpa(313.15, 283.15) - expect) < 1e-9, "40C/10C closed-form")
    check(abs(sec6.vpd_kpa(313.15, 283.15) - 6.148) < 1e-2, "40C/10C VPD ~6.148")
    moist = sec6.vpd_kpa(313.15, 303.15)   # dewpoint 30 C
    dry = sec6.vpd_kpa(313.15, 283.15)     # dewpoint 10 C
    check(dry > moist > 0, "lower dewpoint -> larger VPD")
    v = sec6.vpd_kpa(np.array([310.0, 313.15]), np.array([310.0, 283.15]))
    check(v.shape == (2,) and abs(v[0]) < 1e-12 and v[1] > 6.0, "vectorised VPD")


def test_rootzone_soil_moisture() -> None:
    print("\n[root-zone SM (7*swvl1 + 21*swvl2)/28]")
    check(abs(sec6.rootzone_soil_moisture(0.2, 0.2) - 0.2) < 1e-12, "equal layers -> 0.2")
    check(abs(sec6.rootzone_soil_moisture(0.1, 0.3) - 0.25) < 1e-12, "(0.1,0.3) -> 0.25")
    check(abs(sec6.rootzone_soil_moisture(1.0, 0.0) - 0.25) < 1e-12, "top weight 7/28")
    check(abs(sec6.rootzone_soil_moisture(0.0, 1.0) - 0.75) < 1e-12, "deep weight 21/28")
    sm = sec6.rootzone_soil_moisture(np.array([0.1, 0.2]), np.array([0.3, 0.2]))
    check(np.allclose(sm, [0.25, 0.2]), "vectorised over arrays")


def test_manifest_append() -> None:
    print("\n[manifest append: schema + de-dup]")
    with tempfile.TemporaryDirectory() as d:
        mpath = Path(d) / "manifest.csv"
        pd.DataFrame(columns=sec6._MANIFEST_COLUMNS).to_csv(mpath, index=False)
        rows = [
            {"source": "CDS: reanalysis-era5-land (warm season 2018)",
             "dataset": sec6.DATASET_ID, "filename": "era5land_2018.nc",
             "download_date": "2026-06-12", "checksum": "sha256:aa"},
            {"source": "CDS: reanalysis-era5-land (warm season 2019)",
             "dataset": sec6.DATASET_ID, "filename": "era5land_2019.nc",
             "download_date": "2026-06-12", "checksum": "sha256:bb"},
        ]
        sec6.append_to_manifest(rows, mpath)
        df = pd.read_csv(mpath)
        check(list(df.columns) == sec6._MANIFEST_COLUMNS, "columns match schema")
        check(len(df) == 2, "two rows appended")
        # Re-append one existing + one new -> only the new one lands.
        sec6.append_to_manifest(rows[:1] + [
            {"source": "CDS: reanalysis-era5-land (warm season 2020)",
             "dataset": sec6.DATASET_ID, "filename": "era5land_2020.nc",
             "download_date": "2026-06-12", "checksum": "sha256:cc"}], mpath)
        df2 = pd.read_csv(mpath)
        check(len(df2) == 3, "de-dup: only new row added")


def test_manifest_row_and_checksum() -> None:
    print("\n[manifest row + streaming checksum]")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "era5land_2023_07.nc"
        p.write_bytes(b"not-really-netcdf-but-fine-for-a-checksum")
        import hashlib
        check(sec6.sha256_file(p) == hashlib.sha256(p.read_bytes()).hexdigest(),
              "streaming sha256 matches hashlib")
        row = sec6._manifest_row(p, 2023, "07")
        check(set(row) == set(sec6._MANIFEST_COLUMNS), "row has exactly schema keys")
        check(row["dataset"] == sec6.DATASET_ID and row["filename"] == "era5land_2023_07.nc",
              "row dataset + filename correct")
        check(row["checksum"].startswith("sha256:"), "checksum tagged sha256:")


def main() -> int:
    tests = [
        test_request_builder,
        test_kelvin_to_celsius,
        test_tetens_saturation_vapour_pressure,
        test_vpd,
        test_rootzone_soil_moisture,
        test_manifest_append,
        test_manifest_row_and_checksum,
    ]
    print("=" * 64)
    print("Section 6 pure-logic self-test")
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
