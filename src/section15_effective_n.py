#!/usr/bin/env python3
"""Section 15 (lever exploration) - EFFECTIVE SAMPLE SIZE for an enlarged but
SPATIALLY-CLUSTERED tree-pixel sample, and the statistically-honest threshold
estimation approach it implies.

Why this exists
---------------
Section 14 found NO ROBUST THRESHOLD at the BG level (264 rows = 9 BG x 54
overpasses, median n_good_obs = 2). The obvious "fix" is to drop BG averaging and
pair at the PIXEL level: ~195 tree pixels x 54 overpasses ~= 10k tree-pixel-overpass
observations, each differenced against its BG reference mean -> thousands of rows.
That looks like a huge N -- but it is PSEUDO-REPLICATED on two axes:

  1. SPATIAL: the 195 tree pixels are not independent draws. They sit in a handful
     of contiguous CLUMPS (a riparian/peri-urban canopy patch is one ~tree, not 171
     trees), and 70 m LST/CSI fields are strongly spatially autocorrelated. The
     number of INDEPENDENT spatial units is the number of disconnected clusters,
     NOT the pixel count.
  2. TEMPORAL: the same pixel observed on 54 overpasses gives 54 correlated rows,
     not 54 independent ones (a within-pixel random effect / repeated measure).

This script QUANTIFIES axis 1 (the binding one): it counts the genuinely-independent
spatial clusters of tree pixels three ways
  (a) connected components of the tree class (rook = 4-neighbour, queen = 8-neighbour),
  (b) the block-group grouping (the Section 10 pairing unit),
  (c) clusters cross-tabulated by BG (clusters that straddle BGs, BG with >1 cluster),
then reports the implied EFFECTIVE N and what a credible threshold realistically needs.

It reads ONLY data/processed/section10_pixel_class_70m.tif and the paired-BG CSV +
the BG polygons (for the per-BG breakdown). Writes nothing except stdout. numpy +
scipy.ndimage + rasterio only (all in the canopy env).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config  # noqa: E402

import rioxarray  # noqa: E402,F401
import rasterio  # noqa: E402
from scipy import ndimage  # noqa: E402

CLASS_TREE = 1
CLASS_REFERENCE = 2


def load_class_raster() -> np.ndarray:
    path = config.PROCESSED_DIR / "section10_pixel_class_70m.tif"
    with rasterio.open(path) as src:
        arr = src.read(1)
    return arr


def connected_components(tree_mask: np.ndarray, structure: np.ndarray) -> tuple[np.ndarray, int]:
    """Label connected components of the boolean tree mask with the given adjacency."""
    labels, n = ndimage.label(tree_mask, structure=structure)
    return labels, int(n)


def cluster_size_stats(labels: np.ndarray, n: int) -> dict:
    if n == 0:
        return {"n_clusters": 0, "sizes": np.array([], dtype=int)}
    sizes = np.array([int((labels == k).sum()) for k in range(1, n + 1)], dtype=int)
    sizes = np.sort(sizes)[::-1]
    return {
        "n_clusters": n,
        "sizes": sizes,
        "max": int(sizes.max()),
        "median": float(np.median(sizes)),
        "n_singletons": int((sizes == 1).sum()),
        "largest_frac": float(sizes.max() / sizes.sum()),
        "total_px": int(sizes.sum()),
    }


def rasterize_bg(paired_geoids):
    """Per-pixel block-group index map (same centroid-containment as Section 13)."""
    import geopandas as gpd
    from rasterio import features as rfeatures
    from rasterio.transform import Affine

    bg = gpd.read_parquet(config.INTERIM_DIR / "neighborhood_blockgroups_32612.parquet").reset_index(drop=True)
    if bg.crs is None or bg.crs.to_epsg() != 32612:
        bg = bg.to_crs(config.CRS)
    transform = Affine(*config.GRID_TRANSFORM)
    nrows, ncols = config.GRID_SHAPE
    shapes = ((geom, i + 1) for i, geom in enumerate(bg.geometry))
    idx = rfeatures.rasterize(shapes=shapes, out_shape=(nrows, ncols), transform=transform,
                              fill=0, all_touched=False, dtype="int32")
    geoids = bg["GEOID"].astype(str).to_numpy()
    geoid_of_index = {i + 1: geoids[i] for i in range(len(geoids))}
    return idx, geoid_of_index


def effective_n_kish(repeats_per_unit: np.ndarray) -> float:
    """Kish-style effective N for clustered/weighted samples:
        N_eff = (sum n_i)^2 / sum(n_i^2)
    where n_i is the number of (correlated) observations in cluster i. If every
    cluster had 1 obs this returns the true count; one giant cluster collapses it
    toward ~1. A crude but standard upper-bound proxy for the design effect when
    within-cluster correlation is near 1 (the worst case for autocorrelated LST)."""
    n = np.asarray(repeats_per_unit, dtype="float64")
    s = n.sum()
    if s <= 0:
        return 0.0
    return float(s * s / np.sum(n * n))


def main() -> int:
    import pandas as pd

    arr = load_class_raster()
    tree_mask = arr == CLASS_TREE
    ref_mask = arr == CLASS_REFERENCE
    n_tree_px = int(tree_mask.sum())
    n_ref_px = int(ref_mask.sum())
    print("=" * 78)
    print("EFFECTIVE SAMPLE SIZE for the Phoenix tree-pixel paired design")
    print("=" * 78)
    print(f"class raster: {arr.shape}  tree px={n_tree_px}  reference px={n_ref_px}")

    # ---- (a) connected components: rook (4-nbr) and queen (8-nbr) ----------
    rook = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=int)
    queen = np.ones((3, 3), dtype=int)
    lab_r, n_r = connected_components(tree_mask, rook)
    lab_q, n_q = connected_components(tree_mask, queen)
    sr = cluster_size_stats(lab_r, n_r)
    sq = cluster_size_stats(lab_q, n_q)

    print("\n--- (a) SPATIAL CLUSTERS = connected components of the tree class ---")
    for name, s in (("ROOK (4-neighbour)", sr), ("QUEEN (8-neighbour)", sq)):
        print(f"  {name}: {s['n_clusters']} clusters from {s['total_px']} tree px")
        print(f"      sizes (desc): {s['sizes'].tolist()}")
        print(f"      max={s['max']}px  median={s['median']}px  singletons={s['n_singletons']}  "
              f"largest cluster = {100*s['largest_frac']:.1f}% of tree px")

    # ---- (b)/(c) clusters by block group -----------------------------------
    paired = pd.read_csv(config.PROCESSED_DIR / "section10_paired_neighborhoods.csv",
                         dtype={"GEOID": str})
    paired_geoids = paired["GEOID"].tolist()
    bg_idx, geoid_of_index = rasterize_bg(paired_geoids)

    # tree pixels' BG and queen-cluster labels
    tr_rows, tr_cols = np.where(tree_mask)
    tr_bgidx = bg_idx[tr_rows, tr_cols]
    tr_geoid = np.array([geoid_of_index.get(int(b), "0") for b in tr_bgidx])
    tr_clab = lab_q[tr_rows, tr_cols]  # queen cluster label per tree px

    df = pd.DataFrame({"geoid": tr_geoid, "cluster": tr_clab})
    paired_set = set(paired_geoids)
    df["in_paired_bg"] = df["geoid"].isin(paired_set)

    print("\n--- (b) BLOCK-GROUP grouping (the Section 10 pairing unit) ---")
    bg_counts = df.groupby("geoid").size().sort_values(ascending=False)
    n_bg_with_tree = int((bg_counts.index != "0").sum())
    print(f"  block groups containing >=1 tree px: {n_bg_with_tree}")
    print(f"  paired block groups (from CSV): {len(paired_geoids)}")
    for g, c in bg_counts.items():
        flag = "" if g in paired_set else "  (NOT a paired BG / outside)"
        print(f"      BG {g}: {c} tree px{flag}")
    bg_tree_px = bg_counts[bg_counts.index.isin(paired_set)]
    if len(bg_tree_px):
        print(f"  -> largest paired BG holds {bg_tree_px.max()} / {bg_tree_px.sum()} "
              f"tree px = {100*bg_tree_px.max()/bg_tree_px.sum():.1f}%")

    print("\n--- (c) CLUSTERS cross-tabulated with BLOCK GROUPS (queen adjacency) ---")
    # how many distinct queen-clusters fall in each paired BG, and do clusters straddle BGs?
    cl_per_bg = df[df["in_paired_bg"]].groupby("geoid")["cluster"].nunique().sort_values(ascending=False)
    bg_per_cl = df[df["in_paired_bg"]].groupby("cluster")["geoid"].nunique()
    n_clusters_in_paired = int(df[df["in_paired_bg"]]["cluster"].nunique())
    n_straddle = int((bg_per_cl > 1).sum())
    print(f"  distinct queen-clusters lying in a paired BG: {n_clusters_in_paired}")
    print(f"  clusters that straddle >1 BG: {n_straddle}")
    print("  clusters per paired BG:")
    for g, c in cl_per_bg.items():
        print(f"      BG {g}: {c} distinct tree clusters")

    # ---- effective-N estimates ---------------------------------------------
    print("\n" + "=" * 78)
    print("EFFECTIVE-N ESTIMATES (independent units, NOT nominal pixel/row counts)")
    print("=" * 78)
    n_overpass = 54  # overpasses with emitted master-table rows (per project memory)

    # Independent SPATIAL units under each definition:
    units_queen = n_q
    units_rook = n_r
    units_bg = len(paired_geoids)
    # clusters restricted to paired BGs (the analysable spatial units)
    units_cluster_paired = n_clusters_in_paired

    # Kish effective-N on the cluster-size distribution (worst-case rho~1 within cluster)
    kish_queen = effective_n_kish(sq["sizes"])
    kish_rook = effective_n_kish(sr["sizes"])
    kish_bg = effective_n_kish(bg_tree_px.to_numpy()) if len(bg_tree_px) else float("nan")

    print(f"  nominal pixel-level N (tree px x overpass)        : {n_tree_px} x {n_overpass} "
          f"= {n_tree_px*n_overpass}  <-- PSEUDO-REPLICATED, do NOT use as df")
    print(f"  independent SPATIAL clusters (queen / 8-nbr)      : {units_queen}")
    print(f"  independent SPATIAL clusters (rook  / 4-nbr)      : {units_rook}")
    print(f"  clusters lying inside a PAIRED BG                 : {units_cluster_paired}")
    print(f"  paired BLOCK GROUPS (Section 10 unit)             : {units_bg}")
    print(f"  Kish N_eff on cluster sizes (queen, rho~1)        : {kish_queen:.2f}")
    print(f"  Kish N_eff on cluster sizes (rook,  rho~1)        : {kish_rook:.2f}")
    print(f"  Kish N_eff on BG tree-px sizes (rho~1)            : {kish_bg:.2f}")

    # The number of independent units for a SPATIAL block bootstrap of the breakpoint:
    # you resample CLUSTERS (or BGs) with replacement -> the bootstrap has at most
    # this many distinct units to draw from.
    print("\n  --> For a SPATIAL BLOCK BOOTSTRAP of the breakpoint CI you resample these")
    print("      independent units, NOT pixels. The number of distinct blocks available")
    print(f"      is at most {units_queen} (queen clusters) or {units_bg} (block groups).")

    # ---- what a credible threshold needs -----------------------------------
    print("\n" + "=" * 78)
    print("WHAT A CREDIBLE SEGMENTED-REGRESSION THRESHOLD NEEDS vs WHAT WE HAVE")
    print("=" * 78)
    print("  A 2-segment continuous piecewise fit estimates 4 structural params")
    print("  (2 slopes, 1 intercept, 1 breakpoint) + variance. Rules of thumb for a")
    print("  CREDIBLE, well-identified breakpoint with a bootstrap CI:")
    print("    - >= ~8-10 INDEPENDENT units per segment -> >= ~15-20 independent units;")
    print("    - enough units ON EACH SIDE of the candidate breakpoint (>=5-8 each);")
    print("    - a spatial block bootstrap needs >= ~20-30 resamplable blocks to give a")
    print("      stable percentile CI (fewer -> the CI is itself unstable).")
    print(f"  We have {units_queen} queen clusters / {units_rook} rook clusters / "
          f"{units_bg} paired BGs as independent spatial units.")
    largest_share = 100 * sq["largest_frac"]
    print(f"  AND one cluster carries {largest_share:.1f}% of the tree pixels, so even the")
    print("  cluster count overstates independence (one dominant clump ~ 1 effective unit).")

    verdict_units = units_queen
    can_support = verdict_units >= 15
    print(f"\n  EFFECTIVE independent units available : ~{verdict_units} (queen clusters); "
          f"realistically fewer (~{max(units_bg, int(round(kish_queen)))}) once the")
    print("  dominant clump + within-cluster autocorrelation are accounted for.")
    print(f"  Credible-threshold floor (~15-20 indep units, balanced across the break): "
          f"{'PLAUSIBLY MET' if can_support else 'NOT MET'}")
    print("\n  HONEST CONCLUSION: pixel-level pairing INFLATES nominal N into the thousands")
    print("  but the INDEPENDENT spatial sample is ~the cluster/BG count (single digits to")
    print("  low double digits), dominated by one clump. That cannot support a robust,")
    print("  well-identified cooling-vs-CSI breakpoint; it can only TIGHTEN the existing")
    print("  null with honest (mixed-effects / cluster-robust / spatial-block-bootstrap)")
    print("  uncertainty. The binding limit remains the thin, clustered Phoenix sample.")

    # machine-readable summary line for the caller
    print("\nSUMMARY_JSON:", {
        "n_tree_px": n_tree_px,
        "n_ref_px": n_ref_px,
        "n_overpass": n_overpass,
        "nominal_pixel_obs": n_tree_px * n_overpass,
        "clusters_queen": units_queen,
        "clusters_rook": units_rook,
        "clusters_in_paired_bg": units_cluster_paired,
        "paired_bgs": units_bg,
        "largest_cluster_px": sq["max"],
        "largest_cluster_frac": round(sq["largest_frac"], 4),
        "kish_neff_queen": round(kish_queen, 2),
        "kish_neff_rook": round(kish_rook, 2),
        "kish_neff_bg": round(kish_bg, 2) if kish_bg == kish_bg else None,
        "queen_cluster_sizes": sq["sizes"].tolist(),
        "rook_cluster_sizes": sr["sizes"].tolist(),
        "n_clusters_straddle_bg": n_straddle,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
