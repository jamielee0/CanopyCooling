#!/usr/bin/env python3
"""Self-test for the Section 3 ECOSTRESS ET/ESI pipeline (pure-logic).

Stubs the geo/EO-access stack so the module imports, then exercises risky pure
logic on synthetic data: filename parsing of L3T_JET/L4T_ESI tiles, overpass-key
sharing with Section 2 LSTE, sibling-layer path rewriting, product config, the
exact cloud/water/finite screening mask, advisory-only range handling, persisted
disclosure metadata, and link-table assembly.
Reproject/Zarr/matplotlib glue is standard rioxarray/xarray, not re-tested here.

Runs with just numpy + pandas: python src/test_section3_ecostress_et_esi.py
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
    """JET/ESI filename parsing incl. alphanumeric layer names."""
    print("\n[filename parsing: JET + ESI]")
    jet = "ECOv002_L3T_JET_27821_006_12SUB_20230602T193750_0712_01_PTJPLSMinst.tif"
    g = sec3.parse_granule_filename(jet)
    check(g.orbit == "27821", "JET orbit")
    check(g.scene == "006", "JET scene")
    check(g.tile == "12SUB", "JET MGRS tile")
    check(g.layer == "PTJPLSMinst", "alphanumeric layer name (digits ok)")
    check(g.datetime_utc == _dt.datetime(2023, 6, 2, 19, 37, 50, tzinfo=_dt.timezone.utc),
          "JET UTC timestamp")

    esi = "ECOv002_L4T_ESI_27821_006_12SUB_20230602T193750_0712_01_ESI.tif"
    e = sec3.parse_granule_filename(esi)
    check(e.layer == "ESI", "ESI layer (param==layer name)")
    check(e.orbit == "27821" and e.scene == "006", "ESI orbit/scene")

    bad = "random_file.tif"
    try:
        sec3.parse_granule_filename(bad)
        check(False, "non-matching filename should raise")
    except ValueError:
        check(True, "non-matching filename raises ValueError")


def test_overpass_key_shared_with_lst() -> None:
    """overpass_key is shared across products from the same overpass."""
    print("\n[overpass key shared across products]")
    jet = sec3.parse_granule_filename(
        "ECOv002_L3T_JET_27821_006_12SUB_20230602T193750_0712_01_PTJPLSMinst.tif")
    esi = sec3.parse_granule_filename(
        "ECOv002_L4T_ESI_27821_006_12SVB_20230602T193750_0712_01_ESI.tif")
    lst = sec2.parse_granule_filename(
        "ECOv002_L2T_LSTE_27821_006_12SUB_20230602T193750_0711_01_LST.tif")
    check(jet.overpass_key == lst.overpass_key, "JET shares overpass_key with LSTE")
    check(esi.overpass_key == lst.overpass_key, "ESI (diff MGRS) shares overpass_key")
    other = sec3.parse_granule_filename(
        "ECOv002_L3T_JET_27836_004_12SUB_20230603T184936_0712_01_PTJPLSMinst.tif")
    check(jet.overpass_key != other.overpass_key, "different overpass -> different key")


def test_sibling_layer_path() -> None:
    """Sibling-layer path rewriting replaces the layer token."""
    print("\n[sibling layer path rewriting]")
    jet = Path("/d/raw/ecostress_et/"
               "ECOv002_L3T_JET_27821_006_12SUB_20230602T193750_0712_01_PTJPLSMinst.tif")
    check(sec3.sibling_layer_path(jet, "cloud").name.endswith("_cloud.tif"), "JET -> cloud")
    check(sec3.sibling_layer_path(jet, "water").name.endswith("_water.tif"), "JET -> water")
    check("PTJPLSMinst" not in sec3.sibling_layer_path(jet, "cloud").name,
          "primary layer token fully replaced")
    esi = Path("/d/raw/ecostress_esi/"
               "ECOv002_L4T_ESI_27821_006_12SUB_20230602T193750_0712_01_ESI.tif")
    check(sec3.sibling_layer_path(esi, "PET").name.endswith("_PET.tif"), "ESI -> PET")


def test_product_config() -> None:
    """ET/ESI product configuration values."""
    print("\n[product configuration]")
    et = sec3.ET_PRODUCT
    check(et.short_name == "ECO_L3T_JET" and et.version == "002", "ET = ECO_L3T_JET v002")
    check(et.primary_layer == "PTJPLSMinst", "ET primary layer PTJPLSMinst")
    check(et.primary_var == "et", "ET primary var 'et'")
    check(set(et.download_layers) == {"PTJPLSMinst", "cloud", "water"},
          "ET downloads measure + gate layers")

    esi = sec3.ESI_PRODUCT
    check(esi.short_name == "ECO_L4T_ESI", "ESI = ECO_L4T_ESI")
    check(set(esi.measure_layers) == {"ESI", "PET"}, "ESI vars ESI + PET")
    check(set(esi.download_layers) == {"ESI", "PET", "cloud", "water"},
          "ESI download-layer union")
    check(esi.var_names["ESI"] == "esi" and esi.var_names["PET"] == "pet",
          "ESI var name mapping")
    check(esi.plausible == {"esi": (0.0, 1.0)},
          "ESI advisory range is 0-1 and PET has no configured range")
    all_long_names = list(et.var_long_names.values()) + list(esi.var_long_names.values())
    check(all("quality-controlled" not in text.lower() for text in all_long_names),
          "variable names do not claim retrieval quality control")
    check(all("cloud == 0" in text and "water == 0" in text
              and "isfinite(value)" in text for text in all_long_names),
          "variable names disclose exact finite/cloud/water screening")


def test_supporting_keep_mask() -> None:
    """Section 3's product-specific mask is exactly finite, clear, and land."""
    print("\n[explicit finite/cloud/water screening mask]")
    val = np.array([[10.0, 20.0], [30.0, np.nan]])
    cloud = np.array([[0, 1], [0, 0]], dtype="uint8")
    water = np.array([[0, 0], [1, 0]], dtype="uint8")
    keep = sec3.supporting_keep_mask(val, cloud, water)
    check(keep.tolist() == [[True, False], [False, False]],
          "gate = cloud==0 AND water==0 AND finite")
    cleaned = sec2.apply_keep_mask(val, keep)
    check(cleaned[0, 0] == 10.0 and np.isnan(cleaned[0, 1]), "kept/dropped values")


def test_advisory_ranges_do_not_clip() -> None:
    """Values outside the ESI advisory range are counted/flagged, not clipped."""
    print("\n[advisory range is flag-only; no clipping]")
    values = np.array([[-0.25, 0.5, 1.25]], dtype="float64")
    clear = np.zeros_like(values, dtype="uint8")
    land = np.zeros_like(values, dtype="uint8")
    keep = sec3.supporting_keep_mask(values, clear, land)
    retained = sec2.apply_keep_mask(values, keep)
    check(np.array_equal(retained, values),
          "finite clear-land values outside 0-1 remain numerically unchanged")
    stats = sec2.summarize_granule(
        retained,
        "test_overpass",
        _dt.datetime(2023, 6, 1, tzinfo=_dt.timezone.utc),
        "12SUB",
        plausible_k=sec3.ESI_PRODUCT.plausible["esi"],
    )
    check(stats.n_out_of_range == 2, "two outside-range ESI values are counted")
    check(sec2.decide_range_flag(stats, sec3.ESI_PRODUCT.plausible["esi"]),
          "outside-range ESI values trigger a diagnostic flag")


def test_disclosure_metadata() -> None:
    """Cube attrs state the actual mask, absent retrieval QA, role, and policy."""
    print("\n[persisted screening and interpretation disclosure]")
    ds_attrs = sec3.dataset_disclosure_attrs(sec3.ESI_PRODUCT)
    check(ds_attrs["analysis_role"] == "corroboration-only",
          "dataset role is corroboration-only")
    check(ds_attrs["screening_mask"] ==
          "isfinite(value) AND cloud == 0 AND water == 0",
          "dataset stores the exact screening expression")
    check(ds_attrs["retrieval_quality_qa_filter_applied"] is False,
          "dataset explicitly records no retrieval-quality QA filter")
    check("retained" in ds_attrs["advisory_range_policy"]
          and "never clipped" in ds_attrs["advisory_range_policy"],
          "dataset records advisory-only, no-clipping range policy")
    uncertainty = ds_attrs["etinst_uncertainty_disclosure"]
    check(ds_attrs["etinst_uncertainty_used"] is False
          and "ensemble spread" in uncertainty
          and "not a retrieval-quality QA bit" in uncertainty,
          "ETinstUncertainty is disclosed as unused ensemble spread, not a QA bit")

    esi_attrs = sec3.variable_disclosure_attrs(sec3.ESI_PRODUCT, "esi")
    check(esi_attrs["advisory_range_defined"] is True
          and esi_attrs["advisory_range_min"] == 0.0
          and esi_attrs["advisory_range_max"] == 1.0,
          "ESI variable persists the 0-1 advisory range")
    pet_attrs = sec3.variable_disclosure_attrs(sec3.ESI_PRODUCT, "pet")
    check(pet_attrs["advisory_range_defined"] is False
          and pet_attrs["advisory_range"] == "none configured",
          "PET variable states that no advisory range is configured")


def test_assemble_links() -> None:
    """Link-table assembly: membership flags + LST pairing columns."""
    print("\n[overpass-link table + LST pairing]")
    def meta(o, s, t):
        return {"datetime_utc": t, "orbit": o, "scene": s}
    # k1: all three; k2: LST+ET only; k3: ESI only (no LST -> not paired).
    lst = {"27821_006_20230602T193750": meta("27821", "006", "2023-06-02T19:37:50"),
           "27836_004_20230603T184936": meta("27836", "004", "2023-06-03T18:49:36")}
    et = {"27821_006_20230602T193750": meta("27821", "006", "2023-06-02T19:37:50"),
          "27836_004_20230603T184936": meta("27836", "004", "2023-06-03T18:49:36")}
    esi = {"27821_006_20230602T193750": meta("27821", "006", "2023-06-02T19:37:50"),
           "27999_001_20230701T120000": meta("27999", "001", "2023-07-01T12:00:00")}
    df = sec3.assemble_links(lst, et, esi)
    check(len(df) == 3, "union of overpass keys -> 3 rows")
    check(list(df.columns) == ["overpass_key", "datetime_utc", "orbit", "scene",
                               "in_lst", "in_et", "in_esi",
                               "et_paired_to_lst", "esi_paired_to_lst"],
          "link table schema")
    row1 = df[df.overpass_key == "27821_006_20230602T193750"].iloc[0]
    check(bool(row1.et_paired_to_lst) and bool(row1.esi_paired_to_lst),
          "in LST+ET+ESI -> both paired to LST")
    row2 = df[df.overpass_key == "27836_004_20230603T184936"].iloc[0]
    check(bool(row2.et_paired_to_lst) and not bool(row2.esi_paired_to_lst),
          "LST+ET (no ESI) -> ET paired, ESI not")
    row3 = df[df.overpass_key == "27999_001_20230701T120000"].iloc[0]
    check(not bool(row3.et_paired_to_lst) and not bool(row3.esi_paired_to_lst),
          "ESI-only (no LST) -> not paired")
    check(sec3.assemble_links({}, {}, {}).shape[0] == 0, "empty inputs -> empty table")


def test_needed_layer_links_filtering() -> None:
    """needed_layer_links keeps only configured layers and de-dups."""
    print("\n[needed-layer link filtering + de-dup]")
    class _G:
        def __init__(self, links): self._links = links
        def data_links(self): return self._links

    base = ("https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/"
            "ECO_L3T_JET.002/ECOv002_L3T_JET_27821_006_12SUB_20230602T193750_0712_01/"
            "ECOv002_L3T_JET_27821_006_12SUB_20230602T193750_0712_01")
    g = _G([f"{base}_PTJPLSMinst.tif", f"{base}_cloud.tif", f"{base}_water.tif",
            f"{base}_ETdaily.tif", f"{base}_MOD16inst.tif", f"{base}_STICinst.tif",
            f"{base}_ETinstUncertainty.tif",
            f"{base}_PTJPLSMinst.tif"])  # duplicate
    links = sec3.needed_layer_links([g], sec3.ET_PRODUCT)
    check(len(links) == 3, "keeps PTJPLSMinst+cloud+water, de-dups")
    check(not any(l.endswith("_ETdaily.tif") for l in links),
          "drops unused ensemble/other-algorithm layers")
    check(not any(l.endswith("_ETinstUncertainty.tif") for l in links),
          "does not download ETinstUncertainty ensemble spread as a QA band")


def main() -> int:
    tests = [
        test_filename_parsing_jet_and_esi,
        test_overpass_key_shared_with_lst,
        test_sibling_layer_path,
        test_product_config,
        test_supporting_keep_mask,
        test_advisory_ranges_do_not_clip,
        test_disclosure_metadata,
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
