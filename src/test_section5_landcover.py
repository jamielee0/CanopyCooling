#!/usr/bin/env python3
"""Self-test for the Section 5 land-cover pipeline (pure-logic).

Mirrors test_section2/3/4_*: the geo / EE stack (ee, geemap, rioxarray, rasterio,
xarray) is stubbed so the module imports without it, then the algorithmically
risky pure logic is exercised on synthetic data:

  * the EXACT area-weighted regrid, checked against a hand-computed 30 m -> 70 m
    overlap (the non-integer 70/30 ratio is the whole point of area weighting),
    plus uniform-source, NaN-exclusion and coverage-threshold behaviour
  * the 1-D interval-overlap helper and the unrotated-grid guard
  * the categorical subset check (nearest must never invent a class)
  * product configuration (native 30 m, 70 m filenames carry the year, units are
    percent, the class layer is categorical/uint8)
  * the manifest row built for an EE download (schema + checksum prefix)

The EE compute, geedim download, reproject and matplotlib glue are standard
library usage exercised by the real CLI in an authenticated environment.

Runs with just numpy + pandas:  python src/test_section5_landcover.py
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import numpy as np


def _install_geo_stubs() -> None:
    """Stub heavy top-level imports so the module imports with only numpy+pandas."""
    for name in ("ee", "geemap", "rioxarray", "earthaccess", "xarray"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["rioxarray"].open_rasterio = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["geemap"].download_ee_image = lambda *a, **k: None  # type: ignore[attr-defined]
    if not hasattr(sys.modules["xarray"], "DataArray"):
        sys.modules["xarray"].Dataset = object  # type: ignore[attr-defined]
        sys.modules["xarray"].DataArray = object  # type: ignore[attr-defined]
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
        sys.modules["rasterio"].enums = enums  # type: ignore[attr-defined]


_install_geo_stubs()

sys.path.insert(0, str(Path(__file__).resolve().parent))
sec5 = importlib.import_module("section5_landcover")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


# 30 m source: 4x4 grid covering x[0,120], y[0,120]; top-left origin (0, 120).
_SRC_T = (30.0, 0.0, 0.0, 0.0, -30.0, 120.0)
_SRC = np.array([[10.0, 20.0, 30.0, 40.0],
                 [50.0, 60.0, 70.0, 80.0],
                 [90.0, 100.0, 110.0, 120.0],
                 [130.0, 140.0, 150.0, 160.0]])
# One 70 m dest cell at the same origin: covers x[0,70], y[50,120].
_DST_T = (70.0, 0.0, 0.0, 0.0, -70.0, 120.0)


def test_area_weighted_hand_calc() -> None:
    print("\n[area-weighted regrid: hand-computed 30 m -> 70 m overlap]")
    out = sec5.area_weighted_regrid(_SRC, _SRC_T, _DST_T, (1, 1))
    # wx = [30,30,10,0]; wy = [30,30,10,0]; den = 70*70 = 4900 (full coverage);
    # num = 224000 -> mean = 2240/49 = 45.714285...
    check(np.isclose(out[0, 0], 2240.0 / 49.0),
          f"weighted mean = 2240/49 ({2240/49:.6f}); got {out[0,0]:.6f}")


def test_area_weighted_uniform() -> None:
    print("\n[area-weighted regrid: uniform source -> same value]")
    src = np.full((4, 4), 50.0)
    out = sec5.area_weighted_regrid(src, _SRC_T, _DST_T, (1, 1))
    check(np.isclose(out[0, 0], 50.0), "uniform 50 % -> 50 %")


def test_area_weighted_nan_excluded() -> None:
    print("\n[area-weighted regrid: NaN source cells excluded from num + den]")
    src = _SRC.copy()
    src[0, 0] = np.nan                       # removes weight 30*30=900, value 10
    out = sec5.area_weighted_regrid(src, _SRC_T, _DST_T, (1, 1))
    # den = 4900-900 = 4000; num = 224000 - 900*10 = 215000 -> 53.75
    check(np.isclose(out[0, 0], 53.75), f"NaN-excluded mean = 53.75; got {out[0,0]:.4f}")


def test_area_weighted_coverage_threshold() -> None:
    print("\n[area-weighted regrid: sparse coverage -> NaN unless threshold lowered]")
    src = np.array([[50.0]])
    src_t = (30.0, 0.0, 0.0, 0.0, -30.0, 30.0)   # one 30 m cell at x[0,30], y[0,30]
    dst_t = (70.0, 0.0, 0.0, 0.0, -70.0, 70.0)   # one 70 m cell x[0,70], y[0,70]
    # overlap area 900 / 4900 = 0.18 coverage
    out_default = sec5.area_weighted_regrid(src, src_t, dst_t, (1, 1))  # coverage_min=0.5
    out_low = sec5.area_weighted_regrid(src, src_t, dst_t, (1, 1), coverage_min=0.1)
    check(np.isnan(out_default[0, 0]), "coverage 0.18 < 0.5 -> NaN")
    check(np.isclose(out_low[0, 0], 50.0), "coverage 0.18 >= 0.1 -> 50 %")


def test_interval_overlap_and_rotation_guard() -> None:
    print("\n[1-D interval overlap + unrotated-grid guard]")
    w = sec5._interval_overlap(np.array([0.0]), np.array([70.0]),
                               np.array([0.0, 30.0, 60.0, 90.0]),
                               np.array([30.0, 60.0, 90.0, 120.0]))
    check(w.shape == (1, 4) and np.allclose(w[0], [30, 30, 10, 0]),
          "overlap of [0,70] with 30 m cells = [30,30,10,0]")
    try:
        sec5._cell_edges((30.0, 1.0, 0.0, 0.0, -30.0, 0.0), 3, "x")  # b != 0
        check(False, "rotated transform should raise ValueError")
    except ValueError:
        check(True, "rotated transform (b!=0) raises ValueError")


def test_categorical_subset() -> None:
    print("\n[categorical subset check: nearest never invents a class]")
    src = np.array([11, 21, 41, 82])
    check(sec5.categorical_subset_ok(src, np.array([11, 41])), "subset -> ok")
    check(not sec5.categorical_subset_ok(src, np.array([11, 99])),
          "class 99 not in source -> rejected (averaging bug)")


def test_layer_specs() -> None:
    print("\n[product configuration: honest scales, percent units, categorical class]")
    imp, can, lc = sec5.IMPERVIOUS_SPEC, sec5.CANOPY_SPEC, sec5.LANDCOVER_SPEC
    check(imp.raw_filename(2021) == "nlcd_impervious_2021_30m.tif", "impervious raw name")
    check(imp.grid_filename(2021) == "nlcd_impervious_2021_70m.tif", "impervious 70 m name")
    check(can.raw_filename(2025) == "usfs_tcc_canopy_2025_30m.tif", "canopy raw name")
    check(lc.raw_filename(2021) == "nlcd_landcover_class_2021_30m.tif", "land-cover raw name")
    check(imp.kind == "continuous" and can.kind == "continuous", "impervious/canopy continuous")
    check(lc.is_categorical and lc.out_dtype == "uint8", "land-cover categorical/uint8")
    check(lc.out_nodata == 0, "land-cover nodata = 0 (no NLCD class is 0)")
    check("percent" in imp.units and "percent" in can.units, "impervious/canopy units percent")
    check(sec5.NLCD_COLLECTION == "USGS/NLCD_RELEASES/2021_REL/NLCD", "NLCD collection id")
    check(sec5.TCC_COLLECTION ==
          "projects/gtac-data-publish/assets/TCC/Product_Version/2025-6", "current TCC id")
    check(sec5.NLCD_CLASS_LABELS.get(11) == "Open water", "class 11 = open water (Section 10)")


def test_manifest_row() -> None:
    print("\n[manifest row for an EE download]")
    import tempfile
    import pandas as pd
    import section2_ecostress_lst as sec2

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        raw = d / "nlcd_impervious_2021_30m.tif"
        raw.write_bytes(b"fake-geotiff-bytes")
        manifest = d / "manifest.csv"
        row = {
            "source": f"Google Earth Engine {sec5.NLCD_COLLECTION} (project=test)",
            "dataset": sec5.NLCD_COLLECTION,
            "filename": raw.name,
            "download_date": "2026-06-12",
            "checksum": f"sha256:{sec2.sha256_file(raw)}",
        }
        sec2.append_to_manifest([row], manifest_csv=manifest)
        df = pd.read_csv(manifest)
        check(list(df.columns) == ["source", "dataset", "filename", "download_date", "checksum"],
              "manifest schema matches Section 0")
        check(df.iloc[0]["dataset"] == "USGS/NLCD_RELEASES/2021_REL/NLCD", "dataset id recorded")
        check(str(df.iloc[0]["checksum"]).startswith("sha256:"), "sha256 checksum prefix")


def test_download_result_shapes() -> None:
    print("\n[download-result is_local flag drives orchestration]")
    plan = sec5.LayerPlan(sec5.IMPERVIOUS_SPEC, image=None,
                          collection_id=sec5.NLCD_COLLECTION, image_index="2021", year=2021)
    local = sec5.DownloadResult(plan=plan, path=Path("x.tif"),
                                method="geemap.download_ee_image")
    drive = sec5.DownloadResult(plan=plan, path=None, method="Export.image.toDrive",
                                drive_task_id="ABC", drive_folder="canopy_section5",
                                drive_filename="nlcd_impervious_2021_30m.tif")
    check(local.is_local and not drive.is_local, "local has path; Drive fallback does not")
    check(plan.raw_filename == "nlcd_impervious_2021_30m.tif", "plan resolves raw filename")
    check(plan.grid_filename == "nlcd_impervious_2021_70m.tif", "plan resolves 70 m filename")


def main() -> int:
    tests = [
        test_area_weighted_hand_calc,
        test_area_weighted_uniform,
        test_area_weighted_nan_excluded,
        test_area_weighted_coverage_threshold,
        test_interval_overlap_and_rotation_guard,
        test_categorical_subset,
        test_layer_specs,
        test_manifest_row,
        test_download_result_shapes,
    ]
    print("=" * 64)
    print("Section 5 pure-logic self-test")
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
