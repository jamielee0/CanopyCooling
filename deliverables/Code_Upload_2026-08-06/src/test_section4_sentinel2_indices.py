#!/usr/bin/env python3
"""Self-test for the Section 4 Sentinel-2 NDVI/NDMI pipeline (pure-logic).

Stubs the geo/EE stack (ee, geemap, rioxarray, rasterio) and exercises the risky
pure logic on synthetic data: normalized-difference + NDVI/NDMI polarity, the SCL
keep-mask, valid-scene counts/flags, the NaN-safe high-NDVI threshold, product config
(honest native scales), scene-gate wording, and the EE-download manifest row.

Runs with just numpy + pandas:  python src/test_section4_sentinel2_indices.py
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
    check(np.isclose(ndvi[0, 0], 0.4 / 0.6), "NDVI = (B8-B4)/(B8+B4)")
    check(ndvi[0, 1] == 0.0, "equal bands -> 0")
    check(np.isnan(ndvi[1, 1]), "0/0 (sum==0) -> NaN, no divide error")
    nd_dn = sec4.normalized_difference(b8 * 10000, b4 * 10000)
    check(np.allclose(nd_dn, ndvi, equal_nan=True), "scale-invariant (DN == reflectance)")


def test_scl_keep_mask() -> None:
    print("\n[SCL keep-mask: drop cloud / cloud-shadow / snow]")
    scl = np.array([[4, 3], [8, 5], [11, 6], [9, 10]])
    keep = sec4.scl_keep_mask(scl)
    expected = np.array([[True, False],
                         [False, True],
                         [False, True],
                         [False, False]])
    check(keep.tolist() == expected.tolist(), "drops {3,8,9,10,11}, keeps the rest")
    check(set(sec4.SCL_DROP_CLASSES) == {3, 8, 9, 10, 11},
          "SCL_DROP_CLASSES = cloud-shadow + cloud(med/high) + cirrus + snow")
    check(bool(keep[2, 1]) and bool(keep[1, 1]), "water + bare soil are kept")


def test_high_veg_mask() -> None:
    print("\n[high-NDVI overlay threshold]")
    ndvi = np.array([[0.55, 0.49], [np.nan, 0.5]])
    high = sec4.high_veg_mask(ndvi, 0.5)
    check(high.tolist() == [[True, False], [False, True]],
          ">= threshold and finite; NaN never high")
    check(sec4.HIGH_NDVI_THRESHOLD == 0.5, "default high-NDVI threshold is 0.5 (step 52)")


def test_valid_scene_count_helper() -> None:
    print("\n[post-mask valid-scene count + low-count flag semantics]")
    stack = np.array([
        [[0.1, np.nan, 0.2], [0.1, np.nan, np.nan]],
        [[0.2, 0.3, np.nan], [np.nan, np.nan, np.nan]],
        [[0.3, np.nan, 0.4], [0.2, np.nan, np.nan]],
    ])
    got = sec4.valid_scene_count(stack)
    check(got.dtype == np.int32, "valid-scene count is exact int32")
    check(got.tolist() == [[3, 1, 2], [2, 0, 0]], "finite observations counted per pixel")
    stats = sec4.valid_count_stats(got)
    check(stats["min"] == 0 and stats["max"] == 3, "count stats retain zero and maximum")
    check(stats["n_lt_threshold"] == 5 and stats["low_threshold"] == 3,
          "count<3 is flagged (five pixels), not masked")
    check(np.isfinite(stack).sum() == 8, "source index values remain unchanged by QC helper")


def test_scene_gate_threshold_and_wording() -> None:
    print("\n[60% scene prefilter is broad; per-pixel SCL masking is primary]")
    check(sec4.MAX_SCENE_CLOUD_PCT == 60.0, "scene prefilter remains 60% by explicit decision")
    rationale = sec4.SCENE_PREFILTER_RATIONALE.lower()
    check("< 60" in rationale and "per-pixel scl" in rationale and "primary" in rationale,
          "rationale states keep <60 and primary per-pixel SCL masking")
    help_text = " ".join(sec4._build_arg_parser().format_help().split())
    check("keep scenes with CLOUDY_PIXEL_PERCENTAGE < this" in help_text,
          "CLI help matches ee.Filter.lt keep semantics")
    check("drop >= this" in help_text, "CLI help states the rejected boundary")


def test_product_config() -> None:
    print("\n[product configuration: honest native scales]")
    ndvi = sec4.NDVI_PRODUCT
    ndmi = sec4.NDMI_PRODUCT
    check(ndvi.bands == ("B8", "B4"), "NDVI = normalizedDifference(B8,B4)")
    check(ndmi.bands == ("B8", "B11"), "NDMI = normalizedDifference(B8,B11)")
    check(ndvi.native_scale_m == 10, "NDVI native scale 10 m")
    check(ndmi.native_scale_m == 20, "NDMI native scale 20 m (SWIR B11 is 20 m)")
    check(ndvi.raw_filename.endswith("_10m.tif"), "NDVI raw filename marked 10 m")
    check(ndmi.raw_filename.endswith("_20m.tif"), "NDMI raw filename marked 20 m")
    check(ndvi.grid_filename.endswith("_70m.tif") and ndmi.grid_filename.endswith("_70m.tif"),
          "both grid filenames marked 70 m")
    check(ndvi.count_raw_filename == "s2_ndvi_valid_scene_count_2023_10m.tif",
          "NDVI native count filename is explicit and 10 m")
    check(ndmi.count_raw_filename == "s2_ndmi_valid_scene_count_2023_20m.tif",
          "NDMI native count filename is explicit and 20 m")
    check(ndvi.count_grid_filename.endswith("_count_nearest_2023_70m.tif")
          and ndmi.count_grid_filename.endswith("_count_nearest_2023_70m.tif"),
          "70 m count summaries explicitly say nearest")
    check("lt3" in ndvi.low_count_flag_grid_filename,
          "separate low-count flag filename records the <3 rule")
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
        res = sec4.DownloadResult(product=sec4.NDVI_PRODUCT, path=raw,
                                  method="geemap.download_ee_image", max_tile_size_mb=16)
        # Call the manifest pieces directly against a temp manifest.
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
    check(not res.is_local, "no local path -> is_local False (skips reproject)")
    check(res.drive_filename.endswith("_20m.tif"), "Drive filename keeps honest 20 m tag")


def main() -> int:
    tests = [
        test_normalized_difference,
        test_scl_keep_mask,
        test_high_veg_mask,
        test_valid_scene_count_helper,
        test_scene_gate_threshold_and_wording,
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
