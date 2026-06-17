#!/usr/bin/env python3
"""Unit tests for the PURE logic of section16_pixel_pairing (reason-#2 fix).

Tests the numerics that carry the result WITHOUT the geo IO stack: the adjacency
structures, connected-component cluster labelling, the KDTree local-reference pairing
(radius -> cell conversion, reachability), the cooling_advantage_px difference (finite
handling, sign), the count-weighted cluster collapse, and the Kish effective-N.

pytest is NOT installed in the canopy env -> run this file DIRECTLY:
  conda run -n canopy python src/test_section16_pixel_pairing.py
Exits non-zero on the first failed assertion (prints which test failed).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parent
_ROOT = _SRC.parent
for _p in (str(_ROOT), str(_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import section16_pixel_pairing as s16  # noqa: E402


def test_adjacency_structure():
    q = s16.adjacency_structure("queen")
    r = s16.adjacency_structure("rook")
    assert q.sum() == 9, "queen must be the full 3x3 (8 neighbours + centre)"
    assert r.sum() == 5, "rook must be the plus-shape (4 neighbours + centre)"
    assert r[0, 0] == 0 and r[1, 1] == 1, "rook excludes diagonals, includes centre"
    try:
        s16.adjacency_structure("bishop")
        raise AssertionError("bad connectivity should raise")
    except ValueError:
        pass
    print("ok  test_adjacency_structure")


def test_label_clusters_queen_vs_rook():
    # Two cells touching only diagonally: ONE queen cluster, TWO rook clusters.
    m = np.zeros((4, 4), dtype=bool)
    m[1, 1] = True
    m[2, 2] = True
    _, nq = s16.label_clusters(m, "queen")
    _, nr = s16.label_clusters(m, "rook")
    assert nq == 1, f"queen should merge the diagonal pair into 1 cluster, got {nq}"
    assert nr == 2, f"rook should keep the diagonal pair as 2 clusters, got {nr}"
    # A solid 2x2 block is one cluster either way.
    m2 = np.zeros((4, 4), dtype=bool)
    m2[1:3, 1:3] = True
    _, nq2 = s16.label_clusters(m2, "queen")
    _, nr2 = s16.label_clusters(m2, "rook")
    assert nq2 == 1 and nr2 == 1, "a solid block is one cluster under both adjacencies"
    print("ok  test_label_clusters_queen_vs_rook")


def test_local_reference_pairing_radius():
    # tree at (5,5); refs at increasing chebyshev/euclid distances.
    tree_rc = np.array([[5, 5]])
    ref_rc = np.array([[5, 6],    # 1 cell  = 70 m
                       [5, 8],    # 3 cells = 210 m
                       [5, 10],   # 5 cells = 350 m
                       [5, 13]])  # 8 cells = 560 m
    # R = 350 m on a 70 m grid -> radius 5 cells -> first three refs (<=5), not the 8-cell one.
    nlists, ncount = s16.local_reference_pairing(
        tree_rc, ref_rc, radius_m=350.0, cell_size_m=70.0)
    assert ncount[0] == 3, f"R=350m should reach the 1/3/5-cell refs (3), got {ncount[0]}"
    assert set(nlists[0].tolist()) == {0, 1, 2}
    # R = 210 m -> radius 3 cells -> first two refs.
    _, ncount210 = s16.local_reference_pairing(
        tree_rc, ref_rc, radius_m=210.0, cell_size_m=70.0)
    assert ncount210[0] == 2, f"R=210m should reach the 1/3-cell refs (2), got {ncount210[0]}"
    # no references -> empty, count 0.
    nl0, nc0 = s16.local_reference_pairing(tree_rc, np.empty((0, 2)),
                                           radius_m=350.0, cell_size_m=70.0)
    assert nc0[0] == 0 and nl0[0].size == 0
    print("ok  test_local_reference_pairing_radius")


def test_cooling_advantage_px():
    # tree LST 300; local refs 305, 307 (one NaN dropped) -> mean(306) - 300 = +6.
    ca, n = s16.cooling_advantage_px(300.0, np.array([305.0, 307.0, np.nan]))
    assert n == 2, f"NaN reference must be dropped, n={n}"
    assert abs(ca - 6.0) < 1e-9, f"cooling advantage should be +6, got {ca}"
    # tree warmer than refs -> negative cooling advantage (allowed, not clipped).
    ca2, _ = s16.cooling_advantage_px(310.0, np.array([305.0, 307.0]))
    assert ca2 < 0, "tree warmer than local refs -> negative cooling advantage (kept)"
    # non-finite tree LST -> NaN, n=0.
    ca3, n3 = s16.cooling_advantage_px(np.nan, np.array([305.0]))
    assert not np.isfinite(ca3) and n3 == 0
    # all-NaN references -> NaN, n=0.
    ca4, n4 = s16.cooling_advantage_px(300.0, np.array([np.nan, np.nan]))
    assert not np.isfinite(ca4) and n4 == 0
    print("ok  test_cooling_advantage_px")


def test_count_weighted_mean():
    # values 2, 4 with weights 1, 3 -> (2*1 + 4*3)/(1+3) = 14/4 = 3.5.
    m = s16.count_weighted_mean(np.array([2.0, 4.0]), np.array([1.0, 3.0]))
    assert abs(m - 3.5) < 1e-9, f"weighted mean should be 3.5, got {m}"
    # a 0-weight / NaN pair is dropped.
    m2 = s16.count_weighted_mean(np.array([2.0, 4.0, 99.0]),
                                 np.array([1.0, 3.0, 0.0]))
    assert abs(m2 - 3.5) < 1e-9, "zero-weight pair must be dropped"
    m3 = s16.count_weighted_mean(np.array([np.nan, 4.0]), np.array([1.0, 3.0]))
    assert abs(m3 - 4.0) < 1e-9, "NaN-value pair must be dropped"
    # no usable weight -> NaN.
    assert not np.isfinite(s16.count_weighted_mean(np.array([1.0]), np.array([0.0])))
    print("ok  test_count_weighted_mean")


def test_kish_neff():
    # equal sizes -> N_eff == count.
    assert abs(s16.kish_neff(np.array([1, 1, 1, 1])) - 4.0) < 1e-9
    # one dominant cluster collapses N_eff toward ~1.
    neff = s16.kish_neff(np.array([100, 1, 1]))
    assert neff < 1.1, f"a dominant cluster should give N_eff ~1, got {neff}"
    # the design's headline: 477 + a spread of small clusters -> low N_eff.
    neff2 = s16.kish_neff(np.array([477] + [3] * 100))
    assert neff2 < 5, f"a 477-px dominant cluster keeps N_eff low, got {neff2}"
    assert s16.kish_neff(np.array([])) == 0.0
    print("ok  test_kish_neff")


def test_aggregate_to_clusters_smoke():
    import pandas as pd
    # two clusters, one overpass; cluster 1 has two pixels (weighted), cluster 2 one.
    px = pd.DataFrame({
        "tree_row": [0, 1, 2], "tree_col": [0, 0, 0],
        "cluster_id": [1, 1, 2], "GEOID": ["A", "A", "B"],
        "overpass_index": [0, 0, 0], "overpass_key": ["k0", "k0", "k0"],
        "overpass_timestamp": pd.to_datetime(["2023-06-01"] * 3),
        "lst_tree": [300.0, 301.0, 302.0], "ref_mean": [305.0, 304.0, 306.0],
        "n_ref_in_R": [10, 5, 8], "n_ref_finite": [1, 3, 2],
        "cooling_advantage_px": [5.0, 3.0, 4.0],
        "mean_csi_tree": [0.5, 0.7, 0.6], "vpd_z": [0.1, 0.2, 0.3],
        "ndmi_z": [0.0, 0.0, 0.0], "mean_et_tree": [np.nan, np.nan, 100.0],
        "mean_esi_tree": [np.nan, np.nan, 0.9], "pdsi": [-1.0, -1.0, -1.0],
        "R_m": [350.0, 350.0, 350.0],
    })
    cl = s16.aggregate_to_clusters(px)
    assert len(cl) == 2, f"expected 2 cluster-overpass rows, got {len(cl)}"
    c1 = cl[cl["cluster_id"] == 1].iloc[0]
    # count-weighted CA: (5*1 + 3*3)/(1+3) = 14/4 = 3.5.
    assert abs(c1["cooling_advantage"] - 3.5) < 1e-9, c1["cooling_advantage"]
    assert c1["n_tree_px_valid"] == 2 and c1["GEOID"] == "A"
    # ET present only on cluster 2 -> cluster 1 ET is NaN (pairwise drop, never imputed).
    assert not np.isfinite(c1["mean_et_tree"])
    print("ok  test_aggregate_to_clusters_smoke")


def main() -> int:
    tests = [
        test_adjacency_structure,
        test_label_clusters_queen_vs_rook,
        test_local_reference_pairing_radius,
        test_cooling_advantage_px,
        test_count_weighted_mean,
        test_kish_neff,
        test_aggregate_to_clusters_smoke,
    ]
    for t in tests:
        t()
    print(f"\nALL {len(tests)} section16_pixel_pairing tests PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
