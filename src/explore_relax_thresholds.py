#!/usr/bin/env python3
"""Lever exploration: RECOVER MORE TREE PIXELS by relaxing MIN_OBS and CANOPY_THR.

Recomputes the Section-10 paired-design counts over a grid of
MIN_OBS in {8,10,12,15,20} x CANOPY_THR in {30,35,40}, holding NDVI>0.5,
impervious<20, not-water, reference rule and the tall-building buffer fixed at
their config values. Uses the SAME pure logic functions as the live
classification (imported from section10_classify_pixels) so the numbers match.

Adds the reliability + pseudoreplication diagnostics the lever turns on:
  * obs_count distribution (how noisy a MIN_OBS floor is);
  * for each (min_obs, canopy_thr): tree px, ref px, PAIRED BG count, the
    dominant-BG share of tree px, and a SPATIAL-CLUSTER count (4-connectivity
    connected components of tree px) = the REAL number of independent units.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SRC = Path(__file__).resolve().parent
_ROOT = _SRC.parent
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

import config  # noqa: E402
from section10_classify_pixels import (  # noqa: E402
    classify, load_inputs, rasterize_blockgroups, building_buffer_mask, tree_mask,
)

MIN_OBS_GRID = (8, 10, 12, 15, 20)
CANOPY_GRID = (30.0, 35.0, 40.0)


def connected_components_4(mask: np.ndarray) -> int:
    """Count 4-connected components of a boolean mask (the # of spatial clusters).

    A pure-numpy flood fill (no scipy dependency). Each component is a contiguous
    blob of tree pixels; the component count is the number of genuinely-separate
    spatial units (a far better 'independent N' than the raw pixel count, which is
    inflated by within-blob autocorrelation = pseudoreplication).
    """
    m = np.asarray(mask, dtype=bool)
    visited = np.zeros_like(m)
    ny, nx = m.shape
    ncomp = 0
    for sy in range(ny):
        for sx in range(nx):
            if m[sy, sx] and not visited[sy, sx]:
                ncomp += 1
                stack = [(sy, sx)]
                visited[sy, sx] = True
                while stack:
                    y, x = stack.pop()
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny2, nx2 = y + dy, x + dx
                        if 0 <= ny2 < ny and 0 <= nx2 < nx and m[ny2, nx2] and not visited[ny2, nx2]:
                            visited[ny2, nx2] = True
                            stack.append((ny2, nx2))
    return ncomp


def main() -> None:
    inp = load_inputs(config.PROCESSED_DIR)
    bg_index, lookup = rasterize_blockgroups(config.INTERIM_DIR)
    buffer_mask, _ = building_buffer_mask(
        config.INTERIM_DIR, min_area_m2=config.TALL_BUILDING_MIN_AREA_M2,
        buffer_m=config.BUFFER_M)

    obs = inp["obs_count"]
    print("=== obs_count (finite-LST per-pixel count over 66 overpasses) ===")
    finite = obs[obs > 0]
    pct = {q: int(np.percentile(finite, q)) for q in (5, 10, 25, 50, 75, 90, 95)}
    print(f"  over cells with >=1 obs (n={finite.size}): min={int(finite.min())} "
          f"p5={pct[5]} p10={pct[10]} p25={pct[25]} median={pct[50]} "
          f"p75={pct[75]} p90={pct[90]} p95={pct[95]} max={int(finite.max())}")
    for thr in MIN_OBS_GRID + (25,):
        print(f"  cells with obs_count >= {thr:2d}: {int((obs >= thr).sum()):,} "
              f"({100*(obs>=thr).mean():.2f}% of grid)")

    rows = []
    print("\n=== count grid: MIN_OBS x CANOPY_THR (NDVI>0.5, imperv<20, not water) ===")
    print(f"{'MIN_OBS':>7} {'CANOPY':>6} | {'tree_px':>7} {'ref_px':>7} "
          f"{'paired_BG':>9} {'distinct_BG_tree':>16} {'domBG_share':>11} "
          f"{'spatial_clusters':>16} {'px_in_paired_pct':>16}")
    for mo in MIN_OBS_GRID:
        for ct in CANOPY_GRID:
            raster, paired, counts = classify(
                inp["ndvi"], inp["canopy"], inp["impervious"], inp["landcover"],
                obs, bg_index, buffer_mask,
                ndvi_thr=float(config.NDVI_THR), canopy_thr=ct,
                imperv_thr=float(config.IMPERV_THR), min_obs=mo,
                water_class=int(config.WATER_CLASS),
                ref_canopy_max=float(config.REF_CANOPY_MAX),
                built_classes=tuple(config.BUILT_CLASSES))

            # tree CANDIDATE mask (before pairing) for clustering on all tree px
            tcand = tree_mask(
                inp["ndvi"], inp["canopy"], inp["impervious"], inp["landcover"], obs,
                ndvi_thr=float(config.NDVI_THR), canopy_thr=ct,
                imperv_thr=float(config.IMPERV_THR), min_obs=mo,
                water_class=int(config.WATER_CLASS)) & (~buffer_mask)

            tree_final = (raster == 1)  # CLASS_TREE: tree px in PAIRED BGs
            # distinct BGs holding any tree CANDIDATE px (pre-pair)
            cand_bgs = np.unique(bg_index[tcand & (bg_index > 0)])
            n_distinct_bg = int(cand_bgs.size)
            # dominant-BG share among FINAL (paired) tree px
            if counts["n_tree_px"] > 0:
                tb = bg_index[tree_final]
                vc = pd.Series(tb).value_counts()
                dom_share = float(vc.iloc[0]) / float(counts["n_tree_px"])
            else:
                dom_share = float("nan")
            # spatial clusters = 4-connected components of the CANDIDATE tree mask
            n_clusters = connected_components_4(tcand)
            n_tcand = int(tcand.sum())
            px_in_paired = (counts["n_tree_px"] / n_tcand) if n_tcand else float("nan")

            print(f"{mo:>7} {ct:>6.0f} | {counts['n_tree_px']:>7} "
                  f"{counts['n_ref_px']:>7} {counts['n_paired_blockgroups']:>9} "
                  f"{n_distinct_bg:>16} {dom_share:>11.3f} {n_clusters:>16} "
                  f"{px_in_paired:>16.3f}")
            rows.append({
                "min_obs": mo, "canopy_thr": ct,
                "tree_px": counts["n_tree_px"], "ref_px": counts["n_ref_px"],
                "paired_bg": counts["n_paired_blockgroups"],
                "tree_candidate_px": n_tcand,
                "distinct_bg_tree_candidate": n_distinct_bg,
                "dominant_bg_share": round(dom_share, 4) if dom_share == dom_share else None,
                "spatial_clusters_4conn": n_clusters,
                "frac_tree_cand_in_paired": round(px_in_paired, 4) if px_in_paired == px_in_paired else None,
            })

    df = pd.DataFrame(rows)
    out = config.PROCESSED_DIR / "explore_relax_thresholds_grid.csv"
    df.to_csv(out, index=False)
    print(f"\nWrote grid -> {out}")

    # Baseline (config operating point) for reference
    base = df[(df.min_obs == 20) & (df.canopy_thr == 40.0)].iloc[0]
    print(f"\nBASELINE (config: MIN_OBS=20, CANOPY=40): tree={base.tree_px} "
          f"ref={base.ref_px} paired_BG={base.paired_bg} "
          f"clusters={base.spatial_clusters_4conn} domBG_share={base.dominant_bg_share}")


if __name__ == "__main__":
    main()
