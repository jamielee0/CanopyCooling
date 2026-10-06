#!/usr/bin/env python3
"""Self-test for the Section 15 response-surface module (pure-logic).

Exercises the risky pure logic on tiny hand-built arrays (no parquet, no
matplotlib render): cell assignment + cell means, pairwise-NaN dropping,
out-of-range exclusion (NOT clamped), the day-only filter, and the module
constants. matplotlib is NOT imported (the plot is exercised by the real CLI).

Run: python src/test_section15_response_surface.py
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sec15 = importlib.import_module("section15_response_surface")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


def test_binned_surface_assignment() -> None:
    """Hand-built points land in the expected cells; cell mean = arithmetic mean."""
    print("\n[binned_surface: cell assignment + cell means]")
    # Default edges: VPD_BINS=[-1,0,1,3] -> x bins {[-1,0),[0,1),[1,3)};
    #                SM_BINS =[-3,-1,0,1] -> y bins {[-3,-1),[-1,0),[0,1)}.
    # Two points in cell (i_sm=0, j_vpd=0): x in [-1,0), y in [-3,-1).
    #   (-0.5, -2.0, cool=10), (-0.8, -1.5, cool=20)  -> mean 15, n 2
    # One point in cell (i_sm=2, j_vpd=2): x in [1,3), y in [0,1).
    #   (2.0, 0.5, cool=4) -> mean 4, n 1
    vpd = np.array([-0.5, -0.8, 2.0])
    sm = np.array([-2.0, -1.5, 0.5])
    cool = np.array([10.0, 20.0, 4.0])
    s = sec15.binned_surface(vpd, sm, cool)

    check(s.mean_cooling.shape == (3, 3), "mean_cooling is (n_sm=3, n_vpd=3)")
    check(s.n.shape == (3, 3), "n is (n_sm=3, n_vpd=3)")
    check(s.n[0, 0] == 2, "two points land in cell (i_sm=0, j_vpd=0)")
    check(abs(s.mean_cooling[0, 0] - 15.0) < 1e-9,
          "cell (0,0) mean = arithmetic mean of its points (=(10+20)/2=15)")
    check(s.n[2, 2] == 1, "one point lands in cell (i_sm=2, j_vpd=2)")
    check(abs(s.mean_cooling[2, 2] - 4.0) < 1e-9, "cell (2,2) mean = 4.0")
    # every other cell empty: n 0, mean NaN.
    empty = np.ones((3, 3), dtype=bool)
    empty[0, 0] = False
    empty[2, 2] = False
    check(int(s.n[empty].sum()) == 0, "all other cells have n == 0")
    check(np.all(np.isnan(s.mean_cooling[empty])), "all empty cells have mean NaN")
    check(np.array_equal(s.vpd_edges, np.array([-1, 0, 1, 3], dtype="float64")),
          "vpd_edges returned as given")
    check(np.array_equal(s.sm_edges, np.array([-3, -1, 0, 1], dtype="float64")),
          "sm_edges returned as given")


def test_binned_surface_nan_pairwise_drop() -> None:
    """A point with NaN in vpd OR supply OR cooling is dropped, affecting no cell."""
    print("\n[binned_surface: pairwise NaN drop]")
    # Baseline: one good point in cell (0,0).
    base = sec15.binned_surface(np.array([-0.5]), np.array([-2.0]), np.array([10.0]))
    check(base.n[0, 0] == 1 and abs(base.mean_cooling[0, 0] - 10.0) < 1e-9,
          "baseline single good point -> n=1, mean=10")

    # Add three points, each NaN in exactly one of the three arrays (all else in-cell).
    vpd = np.array([-0.5, np.nan, -0.5, -0.5])
    sm = np.array([-2.0, -2.0, np.nan, -2.0])
    cool = np.array([10.0, 20.0, 20.0, np.nan])
    s = sec15.binned_surface(vpd, sm, cool)
    check(s.n[0, 0] == 1, "NaN-in-any-of-3 points dropped -> only the 1 good point counts")
    check(abs(s.mean_cooling[0, 0] - 10.0) < 1e-9,
          "dropped NaN points do not perturb the cell mean")
    check(int(s.n.sum()) == 1, "exactly one pair survives across the whole surface")


def test_binned_surface_out_of_range_excluded() -> None:
    """A point beyond the outer edges is EXCLUDED, not clamped into the edge cell."""
    print("\n[binned_surface: out-of-range excluded, never clamped]")
    # In-range anchor in the top-right cell (i_sm=2, j_vpd=2): x in [1,3), y in [0,1).
    # Out-of-range points that WOULD clamp into an edge cell if clamped:
    #   x=5.0 (beyond top vpd edge 3) ; x=-2.0 (below bottom vpd edge -1)
    #   y=2.0 (beyond top sm edge 1)  ; y=-5.0 (below bottom sm edge -3)
    vpd = np.array([2.0, 5.0, -2.0, 2.0, 2.0])
    sm = np.array([0.5, 0.5, 0.5, 2.0, -5.0])
    cool = np.array([4.0, 99.0, 99.0, 99.0, 99.0])
    s = sec15.binned_surface(vpd, sm, cool)
    check(s.n[2, 2] == 1, "top-right edge cell counts ONLY the in-range point (not x=5)")
    check(abs(s.mean_cooling[2, 2] - 4.0) < 1e-9,
          "edge-cell mean unaffected by the excluded out-of-range points")
    check(int(s.n.sum()) == 1, "all 4 out-of-range points excluded -> total n == 1")
    # explicit: the below-range vpd point (x=-2) did NOT clamp into left column.
    check(int(s.n[:, 0].sum()) == 0, "x=-2 not clamped into the left (j_vpd=0) column")
    check(int(s.n[0, :].sum()) == 0, "y=-5 not clamped into the bottom (i_sm=0) row")


def test_day_filter_matches_is_day() -> None:
    """The day-only subset used for the surface equals df[df.is_day]."""
    print("\n[day_subset: matches df[df.is_day]]")
    df = pd.DataFrame({
        sec15.X_VAR: [0.1, 0.2, 0.3, 0.4],
        sec15.Y_VAR: [-0.5, -0.5, 0.2, 0.2],
        sec15.COLOR_VAR: [1.0, 2.0, 3.0, 4.0],
        sec15.COUNT_VAR: [5, 6, 7, 8],
        sec15.IS_DAY_VAR: [True, False, True, False],
        sec15.LOCAL_HOUR_VAR: [12, 2, 15, 23],
        sec15.SAMPLE_LABEL_VAR: ["primary", "primary", "sensitivity_lt3_tree_pixels", "primary"],
    })
    sub = sec15.day_subset(df)
    expected = df[df["is_day"]]
    check(sub.equals(expected), "day_subset(df) == df[df.is_day] (rows + index)")
    check(len(sub) == 2, "two day rows selected")
    check(bool(sub[sec15.IS_DAY_VAR].all()), "every selected row has is_day True")
    check(list(sub[sec15.LOCAL_HOUR_VAR]) == [12, 15], "correct day rows retained (hours 12,15)")

    primary = sec15.primary_subset(df)
    check(primary.index.tolist() == [0],
          "primary surface keeps only day rows with the persisted count-floor label")


def test_module_constants() -> None:
    """Module constants: monotone bins, .png figure names, contract axis vars."""
    print("\n[module constants + contract]")
    check(all(b < a for b, a in zip(sec15.VPD_BINS, sec15.VPD_BINS[1:])),
          "VPD_BINS strictly increasing")
    check(all(b < a for b, a in zip(sec15.SM_BINS, sec15.SM_BINS[1:])),
          "SM_BINS strictly increasing")
    check(isinstance(sec15.VPD_BINS, list) and isinstance(sec15.SM_BINS, list),
          "bins are lists")
    check(sec15.FIG_SURFACE.endswith(".png") and sec15.FIG_SURFACE_DAY.endswith(".png"),
          "figure-name constants end in .png")
    check(sec15.FIG_SURFACE != sec15.FIG_SURFACE_DAY,
          "all-overpass and day-only figures are distinct files")
    check(sec15.MASTER_PARQUET == "master_table.parquet",
          "reads master_table.parquet (BG-mean grain)")
    check(sec15.X_VAR == "mean_vpd_z_tree", "x axis = mean_vpd_z_tree (demand)")
    check(sec15.Y_VAR == "mean_sm_z_tree", "y axis = mean_sm_z_tree (supply, soil moisture)")
    check(sec15.COLOR_VAR == "cooling_advantage", "colour = cooling_advantage")
    check(sec15.COUNT_VAR == "n_tree_valid", "count var = n_tree_valid")
    check(sec15.IS_DAY_VAR == "is_day", "day flag column = is_day")
    check(sec15.SAMPLE_LABEL_VAR == "sample_label", "primary-sample label is persisted")


def main() -> int:
    tests = [
        test_binned_surface_assignment,
        test_binned_surface_nan_pairwise_drop,
        test_binned_surface_out_of_range_excluded,
        test_day_filter_matches_is_day,
        test_module_constants,
    ]
    print("=" * 64)
    print("Section 15 response-surface pure-logic self-test")
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
