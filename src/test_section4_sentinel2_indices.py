#!/usr/bin/env python3
"""Self-test for the Section 4 Sentinel-2 NDVI/NDMI pipeline (pure-logic).

Mirrors test_section2/3_*: the geo / EE stack (ee, geemap, rioxarray, rasterio)
is stubbed so the module imports without it, then the algorithmically risky pure
logic is exercised on synthetic data:

  * the normalized-difference formula and its NDVI / NDMI band polarity
  * the SCL keep-mask (cloud / cloud-shadow / snow classes dropped, the rest kept)
  * the high-NDVI overlay threshold (NaN-safe)
  * product configuration, including the honest native scales (NDVI 10 m,
    NDMI 20 m) and the resolution baked into the filenames
  * the manifest row built for an EE download (schema + checksum prefix)

The EE compute, geedim download, reproject and matplotlib glue are standard
library usage exercised by the real CLI in an authenticated environment, not
re-implemented here.

Runs with just numpy + pandas:  python src/test_section4_sentinel2_indices.py
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import numpy as np


def _install_geo_stubs() -> None:
    """Stub the heavy top-level imports so the module imports with only numpy+pandas.

    sec4 pulls in section2 (earthaccess, rioxarray, xarray) plus ee + geemap; none
    of the pure logic under test calls into them.
    """
    for name in ("ee", "geemap", "rioxarray", "earthaccess", "xarray"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["rioxarray"].open_rasterio = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["geemap"].download_ee_image = lambda *a, **k: None  # type: ignore[attr-defined]
    if not hasattr(sys.modules["xarray"], "Dataset"):
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

        enums.Resampling = _Resampling
        sys.modules["rasterio.enums"] = enums
        sys.modules["rasterio"].enums = enums  # type: ignore[attr-defined]


_install_geo_stubs()

sys.path.insert(0, str(Path(__file__).resolve().parent))
sec4 = importlib.import_module("section4_sentinel2_indices")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


def test_normalized_difference() -> None:
    print("\n[normalized-difference formula + polarity]")
    b8 = np.array([[0.5, 0.4], [0.6, 0.0]])
    b4 = np.array([[0.1, 0.4], [0.2, 0.0]])
    ndvi = sec4.normalized_difference(b8, b4)
    # (0.5-0.1)/(0.5+0.1) = 0.4/0.6
    check(np.isclose(ndvi[0, 0], 0.4 / 0.6), "NDVI = (B8-B4)/(B8+B4)")
    check(ndvi[0, 1] == 0.0, "equal bands -> 0")
    check(np.isnan(ndvi[1, 1]), "0/0 (sum==0) -> NaN, no divide error")
    # Reflectance scaling cancels in a normalized difference (DN vs reflectance).
    nd_dn = sec4.normalized_difference(b8 * 10000, b4 * 10000)
    check(np.allclose(nd_dn, ndvi, equal_nan=True), "scale-invariant (DN == reflectance)")


def test_scl_keep_mask() -> None:
    print("\n[SCL keep-mask: drop cloud / cloud-shadow / snow]")
    scl = np.array([[4, 3], [8, 5], [11, 6], [9, 10]])
    keep = sec4.scl_keep_mask(scl)
    expected = np.array([[True, False],   # 4 veg keep, 3 cloud-shadow drop
                         [False, True],   # 8 cloud drop, 5 bare keep
                         [False, True],   # 11 snow drop, 6 water keep
                         [False, False]]) # 9 cloud-high drop, 10 cirrus drop
    check(keep.tolist() == expected.tolist(), "drops {3,8,9,10,11}, keeps the rest")
    check(set(sec4.SCL_DROP_CLASSES) == {3, 8, 9, 10, 11},
          "SCL_DROP_CLASSES = cloud-shadow + cloud(med/high) + cirrus + snow")
    # water (6) and bare (5) are intentionally kept -- they are not cloud/snow.
    check(bool(keep[2, 1]) and bool(keep[1, 1]), "water + bare soil are kept")


def test_high_veg_mask() -> None:
    print("\n[high-NDVI overlay threshold]")
    ndvi = np.array([[0.55, 0.49], [np.nan, 0.5]])
    high = sec4.high_veg_mask(ndvi, 0.5)
    check(high.tolist() == [[True, False], [False, True]],
          ">= threshold and finite; NaN never counts as high")
    check(sec4.HIGH_NDVI_THRESHOLD == 0.5, "default high-NDVI threshold is 0.5 (step 52)")


def test_product_config() -> None:
    print("\n[product configuration: honest native scales]")
    ndvi = sec4.NDVI_PRODUCT
    ndmi = sec4.NDMI_PRODUCT
    check(ndvi.bands == ("B8", "B4"), "NDVI = normalizedDifference(B8,B4)")
    check(ndmi.bands == ("B8", "B11"), "NDMI = normalizedDifference(B8,B11)")
    check(ndvi.native_scale_m == 10, "NDVI native scale 10 m")
    check(ndmi.native_scale_m == 20, "NDMI native scale 20 m (SWIR B11 is 20 m)")
    # The resolution is baked into the filenames so NDMI is never dressed up as 10 m.
    check(ndvi.raw_filename.endswith("_10m.tif"), "NDVI raw filename marked 10 m")
    check(ndmi.raw_filename.endswith("_20m.tif"), "NDMI raw filename marked 20 m")
    check(ndvi.grid_filename.endswith("_70m.tif") and ndmi.grid_filename.endswith("_70m.tif"),
          "both grid filenames marked 70 m")
    check(sec4.COLLECTION_ID == "COPERNICUS/S2_SR_HARMONIZED", "harmonized SR collection")


def test_manifest_row(tmp=None) -> None:
    print("\n[manifest row for an EE download]")
    import tempfile
    import pandas as pd
    import section2_ecostress_lst as sec2

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        raw = d / "s2_ndvi_warmseason_median_2023_10m.tif"
        raw.write_bytes(b"fake-geotiff-bytes")
        manifest = d / "manifest.csv"
        # Point the shared helper + checksum at the temp file/manifest.
        res = sec4.DownloadResult(product=sec4.NDVI_PRODUCT, path=raw,
                                  method="geemap.download_ee_image", max_tile_size_mb=16)
        # record_in_manifest writes to config.MANIFEST_CSV; call the underlying
        # pieces directly against a temp manifest instead.
        row = {
            "source": f"Google Earth Engine {sec4.COLLECTION_ID} (project=test)",
            "dataset": sec4.DATASET_ID,
            "filename": raw.name,
            "download_date": "2026-06-12",
            "checksum": f"sha256:{sec2.sha256_file(raw)}",
        }
        sec2.append_to_manifest([row], manifest_csv=manifest)
        df = pd.read_csv(manifest)
        check(list(df.columns) == ["source", "dataset", "filename", "download_date", "checksum"],
              "manifest schema matches Section 0")
        check(df.iloc[0]["dataset"] == "COPERNICUS/S2_SR_HARMONIZED", "dataset id recorded")
        check(str(df.iloc[0]["checksum"]).startswith("sha256:"), "sha256 checksum prefix")
        check(res.is_local, "local download result flagged is_local")


def test_drive_fallback_shape() -> None:
    print("\n[Drive-fallback result is flagged non-local]")
    res = sec4.DownloadResult(product=sec4.NDMI_PRODUCT, path=None,
                              method="Export.image.toDrive",
                              drive_task_id="ABC123", drive_folder="canopy_section4",
                              drive_filename="s2_ndmi_warmseason_median_2023_20m.tif")
    check(not res.is_local, "no local path -> is_local is False (orchestrator skips reproject)")
    check(res.drive_filename.endswith("_20m.tif"), "Drive filename keeps the honest 20 m tag")


def main() -> int:
    tests = [
        test_normalized_difference,
        test_scl_keep_mask,
        test_high_veg_mask,
        test_product_config,
        test_manifest_row,
        test_drive_fallback_shape,
    ]
    print("=" * 64)
    print("Section 4 pure-logic self-test")
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
