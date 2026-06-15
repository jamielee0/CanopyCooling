#!/usr/bin/env python3
"""Self-test for the Section 10 pixel classification (pure-logic).

Mirrors test_section2-9_*: the heavy geo stack (geopandas, rioxarray, xarray,
rasterio, shapely) is stubbed so the module imports with only numpy + pandas, then
the algorithmically risky PURE logic is exercised on small SYNTHETIC arrays (no
network, no full grid, no Zarr):

  * the AND-combination TREE rule (step 52) -- every one of the five criteria must
    hold, AND the protocol pitfall: high NDVI ALONE (well-watered grass) does NOT
    qualify; canopy must also be high
  * NaN-safety: a pixel missing NDVI/canopy/impervious is never tree-dominated
  * the candidate-REFERENCE rule (step 53): low canopy + a BUILT class (not water,
    not bare desert) + enough observations
  * the PAIRING logic (step 55): only block groups containing BOTH a tree pixel and
    a reference pixel survive; tree/reference pixels in unpaired block groups are
    dropped; nodata-index pixels never pair
  * the obs-count threshold (MIN_OBS) gating BOTH groups
  * the class-raster assembly + codebook precedence
  * one end-to-end classify() on a hand-built grid (counts + paired table)
  * a sensitivity_row sanity check (lowering CANOPY_THR can only add tree pixels)

The rasterization (GEOID + buffer), Zarr read, GeoTIFF write, contextily overlay
and matplotlib glue are standard library usage exercised by the real CLI in the
canopy environment (and by the end-to-end run), not re-implemented here.

Runs with just numpy + pandas:  python src/test_section10_classify_pixels.py
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import numpy as np


def _install_stubs() -> None:
    """Stub the heavy top-level imports so the module imports with only numpy+pandas."""
    for name in ("geopandas", "rioxarray", "xarray"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["geopandas"].GeoDataFrame = object        # type: ignore[attr-defined]
    sys.modules["geopandas"].read_parquet = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["rioxarray"].open_rasterio = lambda *a, **k: None  # type: ignore[attr-defined]
    if not hasattr(sys.modules["xarray"], "Dataset"):
        sys.modules["xarray"].Dataset = object             # type: ignore[attr-defined]
        sys.modules["xarray"].DataArray = object            # type: ignore[attr-defined]
        sys.modules["xarray"].open_zarr = lambda *a, **k: None  # type: ignore[attr-defined]

    # rasterio.features.rasterize + rasterio.transform.Affine used at import time.
    if "rasterio" not in sys.modules:
        sys.modules["rasterio"] = types.ModuleType("rasterio")
    feats = types.ModuleType("rasterio.features")
    feats.rasterize = lambda *a, **k: None
    sys.modules["rasterio.features"] = feats
    sys.modules["rasterio"].features = feats               # type: ignore[attr-defined]
    trans = types.ModuleType("rasterio.transform")
    trans.Affine = lambda *a, **k: a
    sys.modules["rasterio.transform"] = trans
    sys.modules["rasterio"].transform = trans              # type: ignore[attr-defined]


_install_stubs()

sys.path.insert(0, str(Path(__file__).resolve().parent))
sec10 = importlib.import_module("section10_classify_pixels")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


# Start-threshold kwargs reused by several tests (the pre-registered values).
_TREE_KW = dict(ndvi_thr=0.5, canopy_thr=70.0, imperv_thr=20.0, min_obs=20, water_class=11)
_REF_KW = dict(ref_canopy_max=20.0, built_classes=(21, 22, 23, 24), min_obs=20)


def test_tree_rule_is_an_AND() -> None:
    print("\n[tree rule = AND of all five criteria (step 52)]")
    # one clearly tree-dominated pixel: high NDVI, high canopy, low imperv, built-ish
    # non-water class, plenty of obs.
    ndvi = np.array([0.7])
    canopy = np.array([85.0])
    imperv = np.array([5.0])
    lc = np.array([21])
    obs = np.array([30])
    check(sec10.tree_mask(ndvi, canopy, imperv, lc, obs, **_TREE_KW)[0],
          "all five criteria met -> tree-dominated")
    # break each criterion in turn -> must flip to False
    check(not sec10.tree_mask(np.array([0.4]), canopy, imperv, lc, obs, **_TREE_KW)[0],
          "NDVI below threshold -> NOT tree")
    check(not sec10.tree_mask(ndvi, np.array([60.0]), imperv, lc, obs, **_TREE_KW)[0],
          "canopy below threshold -> NOT tree")
    check(not sec10.tree_mask(ndvi, canopy, np.array([40.0]), lc, obs, **_TREE_KW)[0],
          "impervious above threshold -> NOT tree")
    check(not sec10.tree_mask(ndvi, canopy, imperv, np.array([11]), obs, **_TREE_KW)[0],
          "water class (11) -> NOT tree")
    check(not sec10.tree_mask(ndvi, canopy, imperv, lc, np.array([10]), **_TREE_KW)[0],
          "too few observations (<MIN_OBS) -> NOT tree")
    # strict inequalities: exactly AT the threshold does NOT pass (> / <)
    check(not sec10.tree_mask(np.array([0.5]), canopy, imperv, lc, obs, **_TREE_KW)[0],
          "NDVI exactly at threshold -> NOT tree (strict >)")
    check(not sec10.tree_mask(ndvi, np.array([70.0]), imperv, lc, obs, **_TREE_KW)[0],
          "canopy exactly at threshold -> NOT tree (strict >)")
    check(not sec10.tree_mask(ndvi, canopy, np.array([20.0]), lc, obs, **_TREE_KW)[0],
          "impervious exactly at threshold -> NOT tree (strict <)")
    check(sec10.tree_mask(ndvi, canopy, imperv, lc, np.array([20]), **_TREE_KW)[0],
          "obs exactly at MIN_OBS -> tree (>=)")


def test_tree_pitfall_high_ndvi_alone() -> None:
    print("\n[pitfall: high NDVI ALONE is not trees -- irrigated grass]")
    # irrigated lawn / golf turf: very high NDVI, low impervious, plenty obs, BUT
    # essentially no tree canopy -> must NOT be tree-dominated.
    grass = sec10.tree_mask(np.array([0.85]), np.array([2.0]), np.array([1.0]),
                            np.array([71]), np.array([35]), **_TREE_KW)
    check(not grass[0], "NDVI 0.85 but canopy 2% (turf) -> NOT tree-dominated")
    # the SAME high NDVI WITH high canopy -> tree-dominated (the combination)
    treed = sec10.tree_mask(np.array([0.85]), np.array([80.0]), np.array([1.0]),
                            np.array([21]), np.array([35]), **_TREE_KW)
    check(treed[0], "NDVI 0.85 WITH canopy 80% -> tree-dominated (combination)")


def test_tree_rule_nan_safe() -> None:
    print("\n[NaN-safety: missing layer -> never tree-dominated]")
    nan = np.array([np.nan])
    ok_other = (np.array([85.0]), np.array([5.0]), np.array([21]), np.array([30]))
    check(not sec10.tree_mask(nan, *ok_other, **_TREE_KW)[0], "NaN NDVI -> NOT tree")
    check(not sec10.tree_mask(np.array([0.7]), nan, np.array([5.0]), np.array([21]),
                              np.array([30]), **_TREE_KW)[0], "NaN canopy -> NOT tree")
    check(not sec10.tree_mask(np.array([0.7]), np.array([85.0]), nan, np.array([21]),
                              np.array([30]), **_TREE_KW)[0], "NaN impervious -> NOT tree")


def test_reference_rule() -> None:
    print("\n[candidate-reference rule (step 53): low canopy + built + obs]")
    # built (developed) + low canopy + enough obs -> candidate reference
    check(sec10.reference_mask(np.array([3.0]), np.array([23]), np.array([30]),
                               **_REF_KW)[0], "low canopy + developed(23) -> reference")
    # bare desert is NOT eligible even with low canopy
    for desert in (31, 52, 71):
        check(not sec10.reference_mask(np.array([1.0]), np.array([desert]),
                                       np.array([30]), **_REF_KW)[0],
              f"bare-desert class {desert} -> NOT reference")
    # water is NOT eligible
    check(not sec10.reference_mask(np.array([0.0]), np.array([11]), np.array([30]),
                                   **_REF_KW)[0], "water (11) -> NOT reference")
    # high canopy is NOT a reference (it might be a tree pixel)
    check(not sec10.reference_mask(np.array([55.0]), np.array([23]), np.array([30]),
                                   **_REF_KW)[0], "high canopy -> NOT reference")
    # too few observations -> NOT reference (a reference must carry an LST series)
    check(not sec10.reference_mask(np.array([3.0]), np.array([23]), np.array([5]),
                                   **_REF_KW)[0], "developed but obs<MIN_OBS -> NOT reference")


def test_pairing_keeps_only_blockgroups_with_both() -> None:
    print("\n[pairing (step 55): keep only block groups with BOTH sets]")
    # 1-D 'grid' of 6 pixels in 3 block groups (index 1,2,3); 0 = nodata.
    #   pos 0 (BG1): tree        pos 1 (BG1): reference   -> BG1 has BOTH -> PAIRED
    #   pos 2 (BG2): tree        pos 5 (BG2): (neither)    -> BG2 tree-only -> dropped
    #   pos 3 (BG3): reference                              -> BG3 ref-only  -> dropped
    #   pos 4 (nodata BG=0): tree                           -> never pairs
    bg = np.array([1, 1, 2, 3, 0, 2])
    tree = np.array([True, False, True, False, True, False])   # pos 4 is in nodata BG
    ref = np.array([False, True, False, True, False, False])
    tfin, rfin, paired = sec10.pair_by_blockgroup(tree, ref, bg)
    check(list(paired["bg_index"]) == [1], "only BG1 is paired (has both)")
    check(int(paired.iloc[0]["n_tree_px"]) == 1 and int(paired.iloc[0]["n_ref_px"]) == 1,
          "paired BG1 counts: 1 tree, 1 ref")
    check(tfin.tolist() == [True, False, False, False, False, False],
          "only the BG1 tree pixel survives in tree_final")
    check(rfin.tolist() == [False, True, False, False, False, False],
          "only the BG1 reference pixel survives in ref_final")
    # nodata-index tree pixel (position 4) is never paired
    check(not tfin[4], "tree pixel in nodata block group is dropped")


def test_pairing_none_when_disjoint() -> None:
    print("\n[pairing: disjoint sets -> no paired neighborhoods]")
    bg = np.array([1, 2])
    tree = np.array([True, False])
    ref = np.array([False, True])
    tfin, rfin, paired = sec10.pair_by_blockgroup(tree, ref, bg)
    check(len(paired) == 0, "tree in BG1, ref in BG2 -> 0 paired block groups")
    check(tfin.sum() == 0 and rfin.sum() == 0, "no pixels survive when nothing pairs")


def test_assemble_class_raster_precedence() -> None:
    print("\n[class raster assembly + codebook precedence]")
    tree = np.array([True, False, False, False])
    ref = np.array([False, True, False, False])
    buff = np.array([False, False, True, False])
    r = sec10.assemble_class_raster(tree, ref, buff)
    check(r.tolist() == [sec10.CLASS_TREE, sec10.CLASS_REFERENCE,
                         sec10.CLASS_BUILDING_BUFFER, sec10.CLASS_OTHER],
          "codes: tree=1, reference=2, buffer=3, other=0")
    check(r.dtype == np.uint8, "class raster is uint8")
    # a tree pixel that also happens to be flagged buffered keeps TREE (tree wins,
    # though in the pipeline tree pixels are already outside the buffer)
    r2 = sec10.assemble_class_raster(np.array([True]), np.array([False]), np.array([True]))
    check(r2[0] == sec10.CLASS_TREE, "tree precedence over buffer label")


def test_classify_end_to_end_small_grid() -> None:
    print("\n[classify() end-to-end on a small hand-built grid]")
    # 2x3 grid. Block-group index map: left column BG1, middle BG1, right BG2.
    bg = np.array([[1, 1, 2],
                   [1, 1, 2]])
    # Design:
    #   (0,0) tree (high ndvi+canopy)         in BG1
    #   (0,1) reference (low canopy, built)    in BG1  -> BG1 PAIRED
    #   (0,2) tree                             in BG2
    #   (1,2) reference                        in BG2  -> BG2 PAIRED
    #   (1,0) irrigated grass (high ndvi, no canopy) -> neither
    #   (1,1) inside building buffer            -> excluded
    ndvi = np.array([[0.8, 0.1, 0.75],
                     [0.9, 0.2, 0.1]])
    canopy = np.array([[80.0, 2.0, 78.0],
                       [1.0, 1.0, 1.0]])
    imperv = np.array([[3.0, 60.0, 4.0],
                       [1.0, 80.0, 70.0]])
    lc = np.array([[21, 22, 21],
                   [71, 23, 23]])
    obs = np.full((2, 3), 30)
    buff = np.array([[False, False, False],
                     [False, True, False]])
    raster, paired, counts = sec10.classify(
        ndvi, canopy, imperv, lc, obs, bg, buff,
        ndvi_thr=0.5, canopy_thr=70.0, imperv_thr=20.0, min_obs=20, water_class=11,
        ref_canopy_max=20.0, built_classes=(21, 22, 23, 24))
    check(counts["n_tree_px"] == 2, f"2 tree pixels (got {counts['n_tree_px']})")
    check(counts["n_ref_px"] == 2, f"2 reference pixels (got {counts['n_ref_px']})")
    check(counts["n_paired_blockgroups"] == 2,
          f"2 paired block groups (got {counts['n_paired_blockgroups']})")
    check(raster[0, 0] == sec10.CLASS_TREE and raster[0, 2] == sec10.CLASS_TREE,
          "the two tree pixels are coded 1")
    check(raster[0, 1] == sec10.CLASS_REFERENCE and raster[1, 2] == sec10.CLASS_REFERENCE,
          "the two reference pixels are coded 2")
    check(raster[1, 1] == sec10.CLASS_BUILDING_BUFFER, "buffered pixel coded 3")
    check(raster[1, 0] == sec10.CLASS_OTHER, "irrigated-grass pixel coded 0 (not a tree)")


def test_classify_buffer_removes_from_both_pools() -> None:
    print("\n[classify(): a buffered pixel can be neither tree nor reference]")
    bg = np.array([[1, 1]])
    # both pixels would be tree+reference candidates respectively, but pixel (0,0)
    # is inside the building buffer -> it must be excluded, leaving BG1 unpaired.
    ndvi = np.array([[0.8, 0.1]])
    canopy = np.array([[80.0, 2.0]])
    imperv = np.array([[3.0, 50.0]])
    lc = np.array([[21, 23]])
    obs = np.array([[30, 30]])
    buff = np.array([[True, False]])
    raster, paired, counts = sec10.classify(
        ndvi, canopy, imperv, lc, obs, bg, buff,
        ndvi_thr=0.5, canopy_thr=70.0, imperv_thr=20.0, min_obs=20, water_class=11,
        ref_canopy_max=20.0, built_classes=(21, 22, 23, 24))
    check(counts["n_tree_px"] == 0, "the only tree candidate was inside the buffer -> 0 tree")
    check(counts["n_paired_blockgroups"] == 0, "no tree pixel -> BG1 not paired")
    check(raster[0, 0] == sec10.CLASS_BUILDING_BUFFER, "buffered pixel coded 3")
    check(raster[0, 1] == sec10.CLASS_OTHER,
          "reference candidate demoted to other (its BG has no tree pixel)")


def test_sensitivity_row_monotone_in_canopy() -> None:
    print("\n[sensitivity: lowering CANOPY_THR can only ADD tree pixels]")
    # a column of pixels with a spread of canopy values, all else tree-qualifying,
    # all in one block group that also has a reference pixel.
    canopy = np.array([72.0, 66.0, 58.0, 2.0])
    ndvi = np.array([0.7, 0.7, 0.7, 0.1])
    imperv = np.array([5.0, 5.0, 5.0, 50.0])
    lc = np.array([21, 21, 21, 23])      # last is the built reference
    obs = np.full(4, 30)
    bg = np.array([1, 1, 1, 1])
    buff = np.zeros(4, dtype=bool)
    base = sec10.start_params()
    common = dict(ndvi=ndvi, canopy=canopy, impervious=imperv, landcover=lc,
                  obs_count=obs, bg_index=bg, building_excluded=buff)
    p70 = dict(base); p70["canopy_thr"] = 70.0
    p60 = dict(base); p60["canopy_thr"] = 60.0
    p50 = dict(base); p50["canopy_thr"] = 50.0
    r70 = sec10.sensitivity_row("CANOPY_THR", 70.0, params=p70, **common)
    r60 = sec10.sensitivity_row("CANOPY_THR", 60.0, params=p60, **common)
    r50 = sec10.sensitivity_row("CANOPY_THR", 50.0, params=p50, **common)
    check(r70["n_tree_px"] == 1, "canopy>70 -> 1 tree (only the 72% pixel)")
    check(r60["n_tree_px"] == 2, "canopy>60 -> 2 tree (72,66)")
    check(r50["n_tree_px"] == 3, "canopy>50 -> 3 tree (72,66,58)")
    check(r70["n_tree_px"] <= r60["n_tree_px"] <= r50["n_tree_px"],
          "tree count is monotone non-decreasing as CANOPY_THR falls")


def test_config_constants_present() -> None:
    print("\n[Section 10 config constants: pre-registered start values + canopy operating point]")
    import config
    check(config.NDVI_THR == 0.5, "NDVI_THR start = 0.5")
    # CANOPY_THR is the sweep-driven OPERATING point (40 %); the 70 % pre-registration
    # is preserved in CANOPY_THR_PREREGISTERED. The 70 % bar is unachievable at 70 m
    # (the canopy layer maxes at 69.53 %), so it is NOT the operating value -- see the
    # config.py comment and the section10 header. The operating point was chosen by the
    # >=10-paired-neighborhood rule (40 % floor; Phoenix yields only 9 pairs).
    check(config.CANOPY_THR == 40.0, "CANOPY_THR operating = 40.0 (sweep-driven floor)")
    check(config.CANOPY_THR_PREREGISTERED == 70.0,
          "CANOPY_THR_PREREGISTERED = 70.0 (pre-registered bar, unachievable at 70 m)")
    check(config.CANOPY_THR < config.CANOPY_THR_PREREGISTERED,
          "operating CANOPY_THR is below the pre-registered bar (re-tuned, not raised)")
    check(config.IMPERV_THR == 20.0, "IMPERV_THR start = 20.0")
    check(config.MIN_OBS == 20, "MIN_OBS start = 20")
    check(config.BUFFER_M == 70.0, "BUFFER_M start = 70.0")
    check(config.WATER_CLASS == 11, "WATER_CLASS = 11 (NLCD open water)")
    check(tuple(config.BUILT_CLASSES) == (21, 22, 23, 24), "BUILT_CLASSES = developed 21-24")
    check(config.REF_CANOPY_MAX == 20.0, "REF_CANOPY_MAX = 20.0 (documented choice)")
    check(config.TALL_BUILDING_MIN_AREA_M2 == 1000.0,
          "TALL_BUILDING_MIN_AREA_M2 = 1000 (documented area proxy)")
    check(sec10.CLASS_CODEBOOK[1] == "tree-dominated" and sec10.CLASS_CODEBOOK[2] == "reference",
          "codebook: 1=tree, 2=reference")


def main() -> int:
    tests = [
        test_tree_rule_is_an_AND,
        test_tree_pitfall_high_ndvi_alone,
        test_tree_rule_nan_safe,
        test_reference_rule,
        test_pairing_keeps_only_blockgroups_with_both,
        test_pairing_none_when_disjoint,
        test_assemble_class_raster_precedence,
        test_classify_end_to_end_small_grid,
        test_classify_buffer_removes_from_both_pools,
        test_sensitivity_row_monotone_in_canopy,
        test_config_constants_present,
    ]
    print("=" * 64)
    print("Section 10 pure-logic self-test")
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
