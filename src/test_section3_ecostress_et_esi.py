#!/usr/bin/env python3
"""Self-test for the Section 3 ECOSTRESS ET/ESI pipeline (pure-logic verification).

Mirrors test_section2_*: the geo / EO-access stack is stubbed so the module
imports without it, then the algorithmically risky pure logic is exercised on
synthetic data:

  * generalised filename parsing of L3T_JET / L4T_ESI tiles (alphanumeric layer
    names like "PTJPLSMinst") and overpass-key sharing with Section 2 LSTE tiles
  * sibling-layer path rewriting across differently-suffixed granules
  * product configuration (download-layer union, primary layer/var)
  * the no-QC keep mask: reusing Section 2's build_keep_mask with zeros-QC so the
    gate degenerates to cloud==0 AND water==0 AND finite(value)
  * overpass-link table assembly (membership flags + LST pairing columns)

Reproject / Zarr / matplotlib glue is standard rioxarray/xarray usage exercised
by the real CLI in an authenticated environment, not re-implemented here.

Runs with just numpy + pandas:  python src/test_section3_ecostress_et_esi.py
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
    for name in ("earthaccess", "rioxarray", "xarray"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["rioxarray"].open_rasterio = lambda *a, **k: None  # type: ignore[attr-defined]
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
sec3 = importlib.import_module("section3_ecostress_et_esi")
sec2 = importlib.import_module("section2_ecostress_lst")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


def test_filename_parsing_jet_and_esi() -> None:
    print("\n[generalised filename parsing: JET + ESI]")
    jet = "ECOv002_L3T_JET_27821_006_12SUB_20230602T193750_0712_01_PTJPLSMinst.tif"
    g = sec3.parse_granule_filename(jet)
    check(g.orbit == "27821", "JET orbit parsed")
    check(g.scene == "006", "JET scene parsed")
    check(g.tile == "12SUB", "JET MGRS tile parsed")
    check(g.layer == "PTJPLSMinst", "alphanumeric layer name parsed (digits ok)")
    check(g.datetime_utc == _dt.datetime(2023, 6, 2, 19, 37, 50, tzinfo=_dt.timezone.utc),
          "JET UTC overpass timestamp parsed")

    esi = "ECOv002_L4T_ESI_27821_006_12SUB_20230602T193750_0712_01_ESI.tif"
    e = sec3.parse_granule_filename(esi)
    check(e.layer == "ESI", "ESI layer parsed (param==layer name disambiguated)")
    check(e.orbit == "27821" and e.scene == "006", "ESI orbit/scene parsed")

    bad = "random_file.tif"
    try:
        sec3.parse_granule_filename(bad)
        check(False, "non-matching filename should raise")
    except ValueError:
        check(True, "non-matching filename raises ValueError")


def test_overpass_key_shared_with_lst() -> None:
    print("\n[overpass key shared across products / same overpass]")
    jet = sec3.parse_granule_filename(
        "ECOv002_L3T_JET_27821_006_12SUB_20230602T193750_0712_01_PTJPLSMinst.tif")
    esi = sec3.parse_granule_filename(
        "ECOv002_L4T_ESI_27821_006_12SVB_20230602T193750_0712_01_ESI.tif")
    # Section-2 LSTE tile from the SAME overpass (orbit/scene/timestamp match).
    lst = sec2.parse_granule_filename(
        "ECOv002_L2T_LSTE_27821_006_12SUB_20230602T193750_0711_01_LST.tif")
    check(jet.overpass_key == lst.overpass_key,
          "JET tile shares overpass_key with the same-overpass LSTE tile")
    check(esi.overpass_key == lst.overpass_key,
          "ESI tile (diff MGRS tile) still shares the overpass_key")
    other = sec3.parse_granule_filename(
        "ECOv002_L3T_JET_27836_004_12SUB_20230603T184936_0712_01_PTJPLSMinst.tif")
    check(jet.overpass_key != other.overpass_key, "different overpass -> different key")


def test_sibling_layer_path() -> None:
    print("\n[sibling layer path rewriting]")
    jet = Path("/d/raw/ecostress_et/"
               "ECOv002_L3T_JET_27821_006_12SUB_20230602T193750_0712_01_PTJPLSMinst.tif")
    check(sec3.sibling_layer_path(jet, "cloud").name.endswith("_cloud.tif"),
          "JET -> cloud sibling")
    check(sec3.sibling_layer_path(jet, "water").name.endswith("_water.tif"),
          "JET -> water sibling")
    check("PTJPLSMinst" not in sec3.sibling_layer_path(jet, "cloud").name,
          "primary layer token fully replaced")
    esi = Path("/d/raw/ecostress_esi/"
               "ECOv002_L4T_ESI_27821_006_12SUB_20230602T193750_0712_01_ESI.tif")
    check(sec3.sibling_layer_path(esi, "PET").name.endswith("_PET.tif"), "ESI -> PET sibling")


def test_product_config() -> None:
    print("\n[product configuration]")
    et = sec3.ET_PRODUCT
    check(et.short_name == "ECO_L3T_JET" and et.version == "002", "ET = ECO_L3T_JET v002")
    check(et.primary_layer == "PTJPLSMinst", "ET primary layer is PTJPLSMinst")
    check(et.primary_var == "et", "ET primary var name is 'et'")
    check(set(et.download_layers) == {"PTJPLSMinst", "cloud", "water"},
          "ET downloads measure + gate layers only")

    esi = sec3.ESI_PRODUCT
    check(esi.short_name == "ECO_L4T_ESI", "ESI = ECO_L4T_ESI")
    check(set(esi.measure_layers) == {"ESI", "PET"}, "ESI keeps ESI + PET as variables")
    check(set(esi.download_layers) == {"ESI", "PET", "cloud", "water"},
          "ESI download-layer union correct")
    check(esi.var_names["ESI"] == "esi" and esi.var_names["PET"] == "pet",
          "ESI variable name mapping")


def test_no_qc_keep_mask_reuse() -> None:
    print("\n[no-QC keep mask: reuse build_keep_mask with zeros-QC]")
    val = np.array([[10.0, 20.0], [30.0, np.nan]])      # PTJPLSMinst-like
    cloud = np.array([[0, 1], [0, 0]], dtype="uint8")   # (0,1) cloudy
    water = np.array([[0, 0], [1, 0]], dtype="uint8")   # (1,0) water
    zeros_qc = np.zeros_like(cloud, dtype="uint16")     # no QC layer -> all best
    keep = sec2.build_keep_mask(val, zeros_qc, cloud, water)
    # (0,0) clear+land+finite keep; (0,1) cloud drop; (1,0) water drop; (1,1) NaN drop.
    check(keep.tolist() == [[True, False], [False, False]],
          "gate degenerates to cloud==0 AND water==0 AND finite")
    cleaned = sec2.apply_keep_mask(val, keep)
    check(cleaned[0, 0] == 10.0 and np.isnan(cleaned[0, 1]), "kept/dropped values correct")


def test_assemble_links() -> None:
    print("\n[overpass-link table assembly + LST pairing]")
    def meta(o, s, t):
        return {"datetime_utc": t, "orbit": o, "scene": s}
    # k1: in all three; k2: LST+ET only; k3: ESI only (no LST -> not paired).
    lst = {"27821_006_20230602T193750": meta("27821", "006", "2023-06-02T19:37:50"),
           "27836_004_20230603T184936": meta("27836", "004", "2023-06-03T18:49:36")}
    et = {"27821_006_20230602T193750": meta("27821", "006", "2023-06-02T19:37:50"),
          "27836_004_20230603T184936": meta("27836", "004", "2023-06-03T18:49:36")}
    esi = {"27821_006_20230602T193750": meta("27821", "006", "2023-06-02T19:37:50"),
           "27999_001_20230701T120000": meta("27999", "001", "2023-07-01T12:00:00")}
    df = sec3.assemble_links(lst, et, esi)
    check(len(df) == 3, "union of all overpass keys -> 3 rows")
    check(list(df.columns) == ["overpass_key", "datetime_utc", "orbit", "scene",
                               "in_lst", "in_et", "in_esi",
                               "et_paired_to_lst", "esi_paired_to_lst"],
          "link table schema")
    row1 = df[df.overpass_key == "27821_006_20230602T193750"].iloc[0]
    check(bool(row1.et_paired_to_lst) and bool(row1.esi_paired_to_lst),
          "overpass in LST+ET+ESI is paired to LST for both")
    row2 = df[df.overpass_key == "27836_004_20230603T184936"].iloc[0]
    check(bool(row2.et_paired_to_lst) and not bool(row2.esi_paired_to_lst),
          "LST+ET (no ESI) -> ET paired, ESI not")
    row3 = df[df.overpass_key == "27999_001_20230701T120000"].iloc[0]
    check(not bool(row3.et_paired_to_lst) and not bool(row3.esi_paired_to_lst),
          "ESI-only overpass (no LST) -> not paired to LST")
    check(sec3.assemble_links({}, {}, {}).shape[0] == 0, "empty inputs -> empty table")


def test_needed_layer_links_filtering() -> None:
    print("\n[needed-layer link filtering + de-dup]")
    class _G:
        def __init__(self, links): self._links = links
        def data_links(self): return self._links

    base = ("https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/"
            "ECO_L3T_JET.002/ECOv002_L3T_JET_27821_006_12SUB_20230602T193750_0712_01/"
            "ECOv002_L3T_JET_27821_006_12SUB_20230602T193750_0712_01")
    g = _G([f"{base}_PTJPLSMinst.tif", f"{base}_cloud.tif", f"{base}_water.tif",
            f"{base}_ETdaily.tif", f"{base}_MOD16inst.tif", f"{base}_STICinst.tif",
            f"{base}_PTJPLSMinst.tif"])  # duplicate
    links = sec3.needed_layer_links([g], sec3.ET_PRODUCT)
    check(len(links) == 3, "keeps exactly PTJPLSMinst+cloud+water, de-dups")
    check(not any(l.endswith("_ETdaily.tif") for l in links),
          "drops the unused ensemble/other-algorithm layers")


def main() -> int:
    tests = [
        test_filename_parsing_jet_and_esi,
        test_overpass_key_shared_with_lst,
        test_sibling_layer_path,
        test_product_config,
        test_no_qc_keep_mask_reuse,
        test_assemble_links,
        test_needed_layer_links_filtering,
    ]
    print("=" * 64)
    print("Section 3 pure-logic self-test")
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
