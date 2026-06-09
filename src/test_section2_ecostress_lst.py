#!/usr/bin/env python3
"""Self-test for the Section 2 ECOSTRESS pipeline (pure-logic verification).

The geospatial / EO-access stack (earthaccess, rioxarray, xarray, rasterio) is
NOT required to run this test: it stubs those modules so the module imports, then
exercises the algorithmically risky, pure-numpy logic on synthetic data that
mimics ECOSTRESS layers:

  * filename parsing + overpass grouping
  * QC bit-0/1 decoding and the keep-mask polarity (QC best, cloud==0, water==0)
  * scale application + drop / range-flag decisions (step 16)
  * usable-observation count and mean-LST collapse (figures)
  * manifest append (schema + de-duplication)
  * earthaccess bbox ordering and needed-layer link filtering

The reproject / Zarr / matplotlib I/O glue is standard rioxarray/xarray usage
and is covered by running the real CLI in an authenticated environment; it is
not re-implemented here.

Runs with just numpy + pandas:  python src/test_section2_ecostress_lst.py
(also discoverable by pytest as test_* functions).
"""

from __future__ import annotations

import datetime as _dt
import importlib
import sys
import tempfile
import types
from pathlib import Path

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Install lightweight stubs for the heavy top-level imports so the module loads
# without the geo stack. The pure functions under test never call into them.
# --------------------------------------------------------------------------- #
def _install_geo_stubs() -> None:
    for name in ("earthaccess", "rioxarray", "xarray"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    # rioxarray.open_rasterio is referenced (not called) inside functions.
    sys.modules["rioxarray"].open_rasterio = lambda *a, **k: None  # type: ignore[attr-defined]

    if "rasterio" not in sys.modules:
        sys.modules["rasterio"] = types.ModuleType("rasterio")
    if "rasterio.enums" not in sys.modules:
        enums = types.ModuleType("rasterio.enums")

        class _Resampling:  # mimic rasterio.enums.Resampling.bilinear
            bilinear = "bilinear"
            nearest = "nearest"

        enums.Resampling = _Resampling
        sys.modules["rasterio.enums"] = enums
        sys.modules["rasterio"].enums = enums  # type: ignore[attr-defined]


_install_geo_stubs()

# Import the module under test (src/ is this file's directory).
sys.path.insert(0, str(Path(__file__).resolve().parent))
sec2 = importlib.import_module("section2_ecostress_lst")


# --------------------------------------------------------------------------- #
# Tiny assert harness so the file runs without pytest.
# --------------------------------------------------------------------------- #
_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


# --------------------------------------------------------------------------- #
def test_filename_parsing_and_overpass_key() -> None:
    print("\n[filename parsing]")
    fn = "ECOv002_L2T_LSTE_28527_009_12SWD_20230718T081442_0710_01_LST.tif"
    gf = sec2.parse_granule_filename(fn)
    check(gf.orbit == "28527", "orbit parsed")
    check(gf.scene == "009", "scene parsed")
    check(gf.tile == "12SWD", "MGRS tile parsed")
    check(gf.layer == "LST", "layer parsed")
    check(gf.datetime_utc == _dt.datetime(2023, 7, 18, 8, 14, 42, tzinfo=_dt.timezone.utc),
          "UTC overpass timestamp parsed")

    # Two tiles, same overpass -> same key; different scene -> different key.
    a = sec2.parse_granule_filename(fn)
    b = sec2.parse_granule_filename(
        "ECOv002_L2T_LSTE_28527_009_12SWC_20230718T081442_0710_01_LST.tif")
    c = sec2.parse_granule_filename(
        "ECOv002_L2T_LSTE_28600_010_12SWD_20230719T201500_0710_01_LST.tif")
    check(a.overpass_key == b.overpass_key, "same overpass, different tile -> same key")
    check(a.overpass_key != c.overpass_key, "different overpass -> different key")

    # Sibling-layer path rewrite.
    lst_p = Path("/data/raw/ecostress_lst") / fn
    check(sec2.layer_path_for(lst_p, "QC").name.endswith("_QC.tif"), "layer_path_for QC")
    check(sec2.layer_path_for(lst_p, "cloud").name.endswith("_cloud.tif"),
          "layer_path_for cloud")

    bad = "random_file.tif"
    try:
        sec2.parse_granule_filename(bad)
        check(False, "non-matching filename should raise")
    except ValueError:
        check(True, "non-matching filename raises ValueError")


def test_qc_bit_logic() -> None:
    print("\n[QC bit decoding]")
    # Low two bits: 00 best, 01 nominal, 10 cloud, 11 not produced.
    qc = np.array([[0b00, 0b01], [0b10, 0b11]], dtype="uint16")
    m = sec2.qc_best_quality_mask(qc)
    check(m.tolist() == [[True, False], [False, False]], "only 00 kept")
    # Higher bits set but mandatory bits 00 -> still best quality.
    qc2 = np.array([0b1111_1100, 0b0000_0001], dtype="uint16")
    check(sec2.qc_best_quality_mask(qc2).tolist() == [True, False],
          "high bits ignored, mandatory bits decide")


def test_keep_mask_polarity() -> None:
    print("\n[keep-mask polarity: QC best AND cloud==0 AND water==0]")
    lst = np.array([[300.0, 305.0], [310.0, np.nan]])
    qc = np.array([[0b00, 0b00], [0b00, 0b00]], dtype="uint16")   # all best
    cloud = np.array([[0, 1], [0, 0]], dtype="uint8")             # (0,1) cloudy
    water = np.array([[0, 0], [1, 0]], dtype="uint8")             # (1,0) water
    keep = sec2.build_keep_mask(lst, qc, cloud, water)
    # (0,0) land+clear+best+finite -> keep; (0,1) cloud -> drop;
    # (1,0) water -> drop; (1,1) lst NaN -> drop.
    check(keep.tolist() == [[True, False], [False, False]], "polarity correct")

    cleaned = sec2.apply_keep_mask(lst, keep)
    check(np.isnan(cleaned[0, 1]) and np.isnan(cleaned[1, 0]) and np.isnan(cleaned[1, 1]),
          "rejected pixels set to NaN")
    check(cleaned[0, 0] == 300.0, "kept pixel retains LST value")

    # A bad QC flag rejects even an otherwise-perfect pixel.
    qc_bad = np.array([[0b10, 0b00], [0b00, 0b00]], dtype="uint16")
    keep_bad = sec2.build_keep_mask(lst, qc_bad, np.zeros_like(cloud), np.zeros_like(water))
    check(keep_bad[0, 0] == False, "non-best QC rejects pixel")  # noqa: E712


def test_drop_and_flag_decisions() -> None:
    print("\n[step 16: drop near-empty, flag out-of-range]")
    # Mostly-missing granule -> dropped.
    near_empty = np.full((100, 100), np.nan)
    near_empty[0, 0] = 305.0  # 1 / 10000 = 0.0001 valid
    s_empty = sec2.summarize_granule(near_empty, "k", _dt.datetime(2023, 7, 1), "12SWD")
    check(sec2.decide_drop(s_empty, sec2.DEFAULT_MIN_VALID_FRACTION), "near-empty dropped")

    # Healthy granule, all in range -> kept, not flagged.
    good = np.random.default_rng(0).uniform(300, 330, size=(50, 50))
    s_good = sec2.summarize_granule(good, "k", _dt.datetime(2023, 7, 1), "12SWD")
    check(not sec2.decide_drop(s_good, sec2.DEFAULT_MIN_VALID_FRACTION), "healthy kept")
    check(not sec2.decide_range_flag(s_good), "in-range not flagged")

    # Has a few physically implausible pixels -> flagged but NOT dropped.
    odd = good.copy()
    odd[0, 0] = 355.0  # > 340 K
    odd[1, 1] = 270.0  # < 290 K
    s_odd = sec2.summarize_granule(odd, "k", _dt.datetime(2023, 7, 1), "12SWD")
    check(not sec2.decide_drop(s_odd, sec2.DEFAULT_MIN_VALID_FRACTION), "flagged granule kept")
    check(sec2.decide_range_flag(s_odd), "out-of-range flagged")
    check(s_odd.n_out_of_range == 2, "counts both out-of-range pixels")


def test_cube_statistics() -> None:
    print("\n[cube statistics: usable count + mean collapse]")
    nan = np.nan
    stack = np.array([
        [[300.0, nan], [310.0, 320.0]],
        [[302.0, 305.0], [nan, 322.0]],
        [[nan, nan], [312.0, 324.0]],
    ])  # (t=3, y=2, x=2)
    count = sec2.usable_observation_count(stack)
    check(count.tolist() == [[2, 1], [2, 3]], "per-pixel usable count")
    check(count.dtype == np.int32, "count dtype int32")
    mean = sec2.mean_lst_map(stack)
    check(abs(mean[0, 0] - 301.0) < 1e-9, "mean ignores NaN (pixel 0,0)")
    check(abs(mean[0, 1] - 305.0) < 1e-9, "mean of single obs (pixel 0,1)")
    # An all-NaN pixel stays NaN, no warning crash.
    allnan = np.full((2, 1, 1), np.nan)
    check(np.isnan(sec2.mean_lst_map(allnan)[0, 0]), "all-NaN pixel -> NaN mean")


def test_bbox_and_link_filtering() -> None:
    print("\n[earthaccess bbox ordering + link filtering]")
    # config bbox is (min_lon, max_lon, min_lat, max_lat).
    ll_lon, ll_lat, ur_lon, ur_lat = sec2.bbox_for_earthaccess()
    check((ll_lon, ll_lat, ur_lon, ur_lat) == (-112.55, 33.20, -111.55, 33.92),
          "bbox reordered to (LLlon, LLlat, URlon, URlat)")

    class _G:  # minimal stand-in for an earthaccess result granule
        def __init__(self, links):
            self._links = links

        def data_links(self):
            return self._links

    base = "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod/ECOv002_L2T_LSTE_28527_009_12SWD_20230718T081442_0710_01"
    g = _G([
        f"{base}_LST.tif", f"{base}_QC.tif", f"{base}_cloud.tif",
        f"{base}_water.tif", f"{base}_height.tif",
        f"{base}_EmisWB.tif", f"{base}_LST_err.tif", f"{base}_view_zenith.tif",
        f"{base}_LST.tif",  # duplicate
    ])
    links = sec2._needed_layer_links([g])
    check(len(links) == 5, "keeps exactly the 5 needed layers, de-dups")
    check(all(any(l.endswith(f"_{lyr}.tif") for lyr in sec2.NEEDED_LAYERS) for l in links),
          "every kept link is a needed layer")
    check(not any(l.endswith("_EmisWB.tif") for l in links), "drops unused layers")


def test_manifest_append() -> None:
    print("\n[manifest append: schema + de-dup]")
    with tempfile.TemporaryDirectory() as d:
        mpath = Path(d) / "manifest.csv"
        pd.DataFrame(columns=sec2._MANIFEST_COLUMNS).to_csv(mpath, index=False)
        rows = [
            {"source": "https://x/ECOv002_..._LST.tif", "dataset": sec2.DATASET_ID,
             "filename": "a_LST.tif", "download_date": "2026-06-10", "checksum": "sha256:aa"},
            {"source": "https://x/ECOv002_..._QC.tif", "dataset": sec2.DATASET_ID,
             "filename": "a_QC.tif", "download_date": "2026-06-10", "checksum": "sha256:bb"},
        ]
        sec2.append_to_manifest(rows, mpath)
        df = pd.read_csv(mpath)
        check(list(df.columns) == sec2._MANIFEST_COLUMNS, "manifest columns match schema")
        check(len(df) == 2, "two rows appended")
        # Re-appending one existing + one new -> only the new one is added.
        sec2.append_to_manifest(rows[:1] + [
            {"source": "https://x/ECOv002_..._cloud.tif", "dataset": sec2.DATASET_ID,
             "filename": "a_cloud.tif", "download_date": "2026-06-10", "checksum": "sha256:cc"},
        ], mpath)
        df2 = pd.read_csv(mpath)
        check(len(df2) == 3, "de-dup: only the genuinely new row added")


def test_sha256() -> None:
    print("\n[checksum]")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "blob.bin"
        p.write_bytes(b"ecostress")
        import hashlib
        check(sec2.sha256_file(p) == hashlib.sha256(b"ecostress").hexdigest(),
              "streaming sha256 matches hashlib")


def main() -> int:
    tests = [
        test_filename_parsing_and_overpass_key,
        test_qc_bit_logic,
        test_keep_mask_polarity,
        test_drop_and_flag_decisions,
        test_cube_statistics,
        test_bbox_and_link_filtering,
        test_manifest_append,
        test_sha256,
    ]
    print("=" * 64)
    print("Section 2 pure-logic self-test")
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
