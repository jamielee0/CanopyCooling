#!/usr/bin/env python3
"""Self-test for Section 10 pixel classification (pure logic, geo stack stubbed).

Exercises on tiny synthetic arrays: the AND tree rule (incl. high-NDVI-alone
pitfall), strict candidate-reference rule, pre-outcome canopy threshold,
block-group pairing, class-raster precedence, end-to-end classification, and
sensitivity monotonicity. Runs on numpy + pandas only:
    python src/test_section10_classify_pixels.py
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


# Pre-registered start-threshold kwargs reused by several tests.
_TREE_KW = dict(ndvi_thr=0.5, canopy_thr=70.0, imperv_thr=20.0, min_obs=20, water_class=11)
_REF_KW = dict(ref_canopy_max=20.0, ref_imperv_min=20.0,
               ref_built_classes=(22, 23, 24), min_obs=20)


def test_tree_rule_is_an_AND() -> None:
    print("\n[tree rule = AND of all five criteria (step 52)]")
    ndvi = np.array([0.7])
    canopy = np.array([85.0])
    imperv = np.array([5.0])
    lc = np.array([21])
    obs = np.array([30])
    check(sec10.tree_mask(ndvi, canopy, imperv, lc, obs, **_TREE_KW)[0],
          "all five criteria met -> tree")
    check(not sec10.tree_mask(np.array([0.4]), canopy, imperv, lc, obs, **_TREE_KW)[0],
          "NDVI below thr -> NOT tree")
    check(not sec10.tree_mask(ndvi, np.array([60.0]), imperv, lc, obs, **_TREE_KW)[0],
          "canopy below thr -> NOT tree")
    check(not sec10.tree_mask(ndvi, canopy, np.array([40.0]), lc, obs, **_TREE_KW)[0],
          "imperv above thr -> NOT tree")
    check(not sec10.tree_mask(ndvi, canopy, imperv, np.array([11]), obs, **_TREE_KW)[0],
          "water class (11) -> NOT tree")
    check(not sec10.tree_mask(ndvi, canopy, imperv, lc, np.array([10]), **_TREE_KW)[0],
          "obs<MIN_OBS -> NOT tree")
    # strict inequalities: exactly AT the threshold does NOT pass (> / <)
    check(not sec10.tree_mask(np.array([0.5]), canopy, imperv, lc, obs, **_TREE_KW)[0],
          "NDVI at thr -> NOT tree (strict >)")
    check(not sec10.tree_mask(ndvi, np.array([70.0]), imperv, lc, obs, **_TREE_KW)[0],
          "canopy at thr -> NOT tree (strict >)")
    check(not sec10.tree_mask(ndvi, canopy, np.array([20.0]), lc, obs, **_TREE_KW)[0],
          "imperv at thr -> NOT tree (strict <)")
    check(sec10.tree_mask(ndvi, canopy, imperv, lc, np.array([20]), **_TREE_KW)[0],
          "obs at MIN_OBS -> tree (>=)")


def test_tree_pitfall_high_ndvi_alone() -> None:
    print("\n[pitfall: high NDVI ALONE is not trees -- irrigated grass]")
    grass = sec10.tree_mask(np.array([0.85]), np.array([2.0]), np.array([1.0]),
                            np.array([71]), np.array([35]), **_TREE_KW)
    check(not grass[0], "NDVI 0.85 but canopy 2% (turf) -> NOT tree")
    treed = sec10.tree_mask(np.array([0.85]), np.array([80.0]), np.array([1.0]),
                            np.array([21]), np.array([35]), **_TREE_KW)
    check(treed[0], "NDVI 0.85 WITH canopy 80% -> tree (combination)")


def test_tree_rule_nan_safe() -> None:
    print("\n[NaN-safety: missing layer -> never tree]")
    nan = np.array([np.nan])
    ok_other = (np.array([85.0]), np.array([5.0]), np.array([21]), np.array([30]))
    check(not sec10.tree_mask(nan, *ok_other, **_TREE_KW)[0], "NaN NDVI -> NOT tree")
    check(not sec10.tree_mask(np.array([0.7]), nan, np.array([5.0]), np.array([21]),
                              np.array([30]), **_TREE_KW)[0], "NaN canopy -> NOT tree")
    check(not sec10.tree_mask(np.array([0.7]), np.array([85.0]), nan, np.array([21]),
                              np.array([30]), **_TREE_KW)[0], "NaN imperv -> NOT tree")


def test_reference_rule() -> None:
    print("\n[candidate-reference rule: low canopy + high impervious + NLCD22-24 + obs]")
    check(sec10.reference_mask(np.array([3.0]), np.array([60.0]), np.array([23]),
                               np.array([30]), **_REF_KW)[0],
          "low canopy + impervious + developed(23) -> reference")
    for desert in (31, 52, 71):
        check(not sec10.reference_mask(np.array([1.0]), np.array([60.0]),
                                       np.array([desert]), np.array([30]), **_REF_KW)[0],
              f"bare-desert class {desert} -> NOT reference")
    check(not sec10.reference_mask(np.array([0.0]), np.array([60.0]), np.array([11]),
                                   np.array([30]), **_REF_KW)[0],
          "water (11) -> NOT reference")
    check(not sec10.reference_mask(np.array([55.0]), np.array([60.0]), np.array([23]),
                                   np.array([30]), **_REF_KW)[0],
          "high canopy -> NOT reference")
    check(not sec10.reference_mask(np.array([3.0]), np.array([60.0]), np.array([23]),
                                   np.array([5]), **_REF_KW)[0],
          "developed but obs<MIN_OBS -> NOT reference")


def test_reference_requires_impervious_floor() -> None:
    print("\n[reference impervious rule is strict and NaN-safe]")
    canopy = np.array([3.0, 3.0, 3.0])
    impervious = np.array([20.0, 20.01, np.nan])
    landcover = np.array([23, 23, 23])
    obs = np.array([30, 30, 30])
    got = sec10.reference_mask(canopy, impervious, landcover, obs, **_REF_KW)
    check(got.tolist() == [False, True, False],
          "impervious==20 fails, >20 passes, NaN fails")


def test_reference_excludes_nlcd21() -> None:
    print("\n[reference rule excludes developed open space (NLCD 21)]")
    canopy = np.array([3.0, 3.0, 3.0, 3.0])
    impervious = np.full(4, 60.0)
    landcover = np.array([21, 22, 23, 24])
    obs = np.full(4, 30)
    got = sec10.reference_mask(canopy, impervious, landcover, obs, **_REF_KW)
    check(got.tolist() == [False, True, True, True],
          "NLCD 21 fails; developed intensity classes 22-24 pass")


def test_pairing_keeps_only_blockgroups_with_both() -> None:
    print("\n[pairing (step 55): keep only block groups with BOTH sets]")
    # 6 px, BGs 1/2/3 (0=nodata): BG1 has both (paired); BG2 tree-only, BG3 ref-only;
    # pos 4 tree is in nodata BG -> never pairs.
    bg = np.array([1, 1, 2, 3, 0, 2])
    tree = np.array([True, False, True, False, True, False])   # pos 4 is in nodata BG
    ref = np.array([False, True, False, True, False, False])
    tfin, rfin, paired = sec10.pair_by_blockgroup(tree, ref, bg)
    check(list(paired["bg_index"]) == [1], "only BG1 is paired (has both)")
    check(int(paired.iloc[0]["n_tree_px"]) == 1 and int(paired.iloc[0]["n_ref_px"]) == 1,
          "paired BG1 counts: 1 tree, 1 ref")
    check(tfin.tolist() == [True, False, False, False, False, False],
          "only BG1 tree px survives in tree_final")
    check(rfin.tolist() == [False, True, False, False, False, False],
          "only BG1 ref px survives in ref_final")
    check(not tfin[4], "tree px in nodata BG is dropped")


def test_pairing_none_when_disjoint() -> None:
    print("\n[pairing: disjoint sets -> no paired neighborhoods]")
    bg = np.array([1, 2])
    tree = np.array([True, False])
    ref = np.array([False, True])
    tfin, rfin, paired = sec10.pair_by_blockgroup(tree, ref, bg)
    check(len(paired) == 0, "tree BG1, ref BG2 -> 0 paired BGs")
    check(tfin.sum() == 0 and rfin.sum() == 0, "nothing pairs -> no px survive")


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
    r2 = sec10.assemble_class_raster(np.array([True]), np.array([False]), np.array([True]))
    check(r2[0] == sec10.CLASS_TREE, "tree precedence over buffer label")


def test_classify_end_to_end_small_grid() -> None:
    print("\n[classify() end-to-end on a small hand-built grid]")
    # 2x3 grid; BG map left/middle=BG1, right=BG2. Both BGs end up paired.
    bg = np.array([[1, 1, 2],
                   [1, 1, 2]])
    # (0,0) tree BG1; (0,1) ref BG1; (0,2) tree BG2; (1,2) ref BG2;
    # (1,0) irrigated grass -> neither; (1,1) inside buffer -> excluded.
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
        ref_canopy_max=20.0, ref_imperv_min=20.0,
        ref_built_classes=(22, 23, 24))
    check(counts["n_tree_px"] == 2, f"2 tree px (got {counts['n_tree_px']})")
    check(counts["n_ref_px"] == 2, f"2 ref px (got {counts['n_ref_px']})")
    check(counts["n_paired_blockgroups"] == 2,
          f"2 paired BGs (got {counts['n_paired_blockgroups']})")
    check(raster[0, 0] == sec10.CLASS_TREE and raster[0, 2] == sec10.CLASS_TREE,
          "the two tree px coded 1")
    check(raster[0, 1] == sec10.CLASS_REFERENCE and raster[1, 2] == sec10.CLASS_REFERENCE,
          "the two ref px coded 2")
    check(raster[1, 1] == sec10.CLASS_BUILDING_BUFFER, "buffered px coded 3")
    check(raster[1, 0] == sec10.CLASS_OTHER, "irrigated-grass px coded 0 (not tree)")


def test_classify_buffer_removes_from_both_pools() -> None:
    print("\n[classify(): a buffered pixel can be neither tree nor reference]")
    # (0,0) would be tree but is in the buffer -> excluded -> BG1 unpaired.
    bg = np.array([[1, 1]])
    ndvi = np.array([[0.8, 0.1]])
    canopy = np.array([[80.0, 2.0]])
    imperv = np.array([[3.0, 50.0]])
    lc = np.array([[21, 23]])
    obs = np.array([[30, 30]])
    buff = np.array([[True, False]])
    raster, paired, counts = sec10.classify(
        ndvi, canopy, imperv, lc, obs, bg, buff,
        ndvi_thr=0.5, canopy_thr=70.0, imperv_thr=20.0, min_obs=20, water_class=11,
        ref_canopy_max=20.0, ref_imperv_min=20.0,
        ref_built_classes=(22, 23, 24))
    check(counts["n_tree_px"] == 0, "only tree candidate was buffered -> 0 tree")
    check(counts["n_paired_blockgroups"] == 0, "no tree px -> BG1 not paired")
    check(raster[0, 0] == sec10.CLASS_BUILDING_BUFFER, "buffered px coded 3")
    check(raster[0, 1] == sec10.CLASS_OTHER,
          "ref candidate demoted to other (BG has no tree px)")


def test_validation_sample_uses_final_paired_tree_class() -> None:
    print("\n[validation sample: only finalized paired class-1 pixels are eligible]")
    # The class-0 cells represent raw threshold-qualified candidates that pairing demoted.
    # They must never re-enter the validation sample after the final raster is assembled.
    raster = np.array([
        [sec10.CLASS_TREE, sec10.CLASS_OTHER, sec10.CLASS_REFERENCE],
        [sec10.CLASS_BUILDING_BUFFER, sec10.CLASS_TREE, sec10.CLASS_OTHER],
    ], dtype="uint8")
    params = {"canopy_thr": 40.0}
    eligible, canopy_used = sec10._validation_tree_mask(raster, params)
    expected = raster == sec10.CLASS_TREE
    check(np.array_equal(eligible, expected),
          "validation mask is exactly class_raster == CLASS_TREE")
    check(not eligible[0, 1] and not eligible[1, 2],
          "class-0 threshold-like candidates remain excluded")
    bg_index = np.array([[1, 99, 1], [1, 2, 99]], dtype="int32")
    rows, cols = sec10.sample_tree_pixels(eligible, bg_index, n=10, seed=7)
    check(len(rows) == 2 and bool(np.all(raster[rows, cols] == sec10.CLASS_TREE)),
          "every sampled coordinate is a finalized paired class-1 pixel")
    check(canopy_used == 40.0, "validation metadata retains the operating canopy threshold")


def test_sensitivity_row_monotone_in_canopy() -> None:
    print("\n[sensitivity: lowering CANOPY_THR can only ADD tree pixels]")
    # spread of canopy values, all else tree-qualifying, one BG with a reference px.
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
    check(r70["n_tree_px"] == 1, "canopy>70 -> 1 tree (72%)")
    check(r60["n_tree_px"] == 2, "canopy>60 -> 2 tree (72,66)")
    check(r50["n_tree_px"] == 3, "canopy>50 -> 3 tree (72,66,58)")
    check(r70["n_tree_px"] <= r60["n_tree_px"] <= r50["n_tree_px"],
          "tree count monotone non-decreasing as CANOPY_THR falls")


def test_operating_canopy_threshold_is_precommitted() -> None:
    print("\n[operating canopy threshold: NDVI-pool P90 or signal floor, never BG yield]")
    canopy = np.array([10., 20., 30., 40., 50., 60., 70., 80., 90., 100., np.nan])
    ndvi = np.array([0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.4, 0.8, 0.8])
    # Exclude canopy=100 through the building buffer; canopy=90 fails NDVI; NaN fails.
    building_excluded = np.array(
        [False, False, False, False, False, False, False, False, False, True, False])
    eligible = (~building_excluded) & np.isfinite(canopy) & np.isfinite(ndvi) & (ndvi > 0.5)
    expected_raw = float(np.percentile(canopy[eligible], 90.0, method="linear"))
    expected = max(expected_raw, 40.0)
    base = sec10.start_params()

    # Extra BG maps deliberately disagree. The derivation API has no BG argument and
    # only consumes canopy/NDVI, so paired-neighborhood yield cannot affect the result.
    inp_one_bg = {"canopy": canopy, "ndvi": ndvi, "bg_index": np.ones(canopy.size)}
    inp_many_bg = {"canopy": canopy, "ndvi": ndvi,
                   "bg_index": np.arange(1, canopy.size + 1)}
    chosen_one, info_one = sec10.derive_operating_canopy_thr(
        inp_one_bg, building_excluded, base)
    chosen_many, info_many = sec10.derive_operating_canopy_thr(
        inp_many_bg, building_excluded, base)

    check(np.isclose(chosen_one, expected),
          f"chosen threshold equals max(P90={expected_raw:.3f}, 40) = {expected:.3f}")
    check(np.isclose(chosen_one, chosen_many),
          "threshold invariant to one-BG versus one-BG-per-pixel maps")
    check(info_one["n_eligible"] == int(eligible.sum()), "eligible pool count persisted")
    check(np.isclose(info_one["raw_percentile_value"], expected_raw),
          "raw canopy percentile persisted")
    check(info_one["independent_of_bg_yield"] and info_many["independent_of_bg_yield"],
          "provenance explicitly records BG-yield independence")


def test_operating_canopy_threshold_floor_and_empty_pool() -> None:
    print("\n[operating canopy threshold: hard floor + empty-pool failure]")
    base = sec10.start_params()
    low = {"canopy": np.array([1., 5., 10.]), "ndvi": np.array([0.6, 0.7, 0.8])}
    chosen, info = sec10.derive_operating_canopy_thr(
        low, np.zeros(3, dtype=bool), base)
    check(chosen == 40.0 and info["floor_applied"],
          "P90 below 40 -> hard 40% signal floor binds")

    empty = {"canopy": np.array([10., np.nan]), "ndvi": np.array([0.5, 0.9])}
    raised = False
    try:
        sec10.derive_operating_canopy_thr(empty, np.array([False, True]), base)
    except ValueError as exc:
        raised = "no finite, building-excluded pixels" in str(exc)
    check(raised, "empty NDVI-qualifying pool raises an informative ValueError")


def test_config_constants_present() -> None:
    print("\n[config constants: pre-registered starts + canopy operating point]")
    import config
    check(config.NDVI_THR == 0.5, "NDVI_THR start = 0.5")
    # Phoenix's NDVI-qualified P90 is below the precommitted signal floor, so the
    # operating value is 40; 70 remains the honest but unreachable preregistered bar.
    check(config.CANOPY_PCTL == 90.0, "CANOPY_PCTL = 90")
    check(config.CANOPY_THR_FLOOR == 40.0, "CANOPY_THR_FLOOR = 40")
    check(config.CANOPY_THR == 40.0, "CANOPY_THR operating = 40.0 (P90-or-floor rule)")
    check(config.CANOPY_THR_PREREGISTERED == 70.0,
          "CANOPY_THR_PREREGISTERED = 70.0 (pre-registered bar)")
    check(config.CANOPY_THR < config.CANOPY_THR_PREREGISTERED,
          "operating CANOPY_THR below pre-registered bar")
    check(config.IMPERV_THR == 20.0, "IMPERV_THR start = 20.0")
    check(config.MIN_OBS == 20, "MIN_OBS start = 20")
    check(config.BUFFER_M == 70.0, "BUFFER_M start = 70.0")
    check(config.WATER_CLASS == 11, "WATER_CLASS = 11 (NLCD open water)")
    check(tuple(config.REF_BUILT_CLASSES) == (22, 23, 24),
          "REF_BUILT_CLASSES = developed intensity 22-24 (NLCD 21 excluded)")
    check(config.REF_CANOPY_MAX == 20.0, "REF_CANOPY_MAX = 20.0")
    check(config.REF_IMPERV_MIN == 20.0, "REF_IMPERV_MIN = 20.0")
    check(config.TALL_BUILDING_MIN_AREA_M2 == 1000.0,
          "TALL_BUILDING_MIN_AREA_M2 = 1000 (area proxy)")
    check(sec10.CLASS_CODEBOOK[1] == "tree-dominated" and sec10.CLASS_CODEBOOK[2] == "reference",
          "codebook: 1=tree, 2=reference")


def main() -> int:
    tests = [
        test_tree_rule_is_an_AND,
        test_tree_pitfall_high_ndvi_alone,
        test_tree_rule_nan_safe,
        test_reference_rule,
        test_reference_requires_impervious_floor,
        test_reference_excludes_nlcd21,
        test_pairing_keeps_only_blockgroups_with_both,
        test_pairing_none_when_disjoint,
        test_assemble_class_raster_precedence,
        test_classify_end_to_end_small_grid,
        test_classify_buffer_removes_from_both_pools,
        test_validation_sample_uses_final_paired_tree_class,
        test_sensitivity_row_monotone_in_canopy,
        test_operating_canopy_threshold_is_precommitted,
        test_operating_canopy_threshold_floor_and_empty_pool,
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
