#!/usr/bin/env python3
"""Drill-down on the recommended setting vs baseline: per-BG tree-px composition,
cluster sizes, and the 20->15 MIN_OBS gain, to size pseudoreplication honestly."""
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
    classify, load_inputs, rasterize_blockgroups, building_buffer_mask, tree_mask)
from explore_relax_thresholds import connected_components_4  # noqa: E402


def cluster_sizes(mask):
    m = np.asarray(mask, bool); vis = np.zeros_like(m); ny, nx = m.shape; sizes = []
    for sy in range(ny):
        for sx in range(nx):
            if m[sy, sx] and not vis[sy, sx]:
                stack = [(sy, sx)]; vis[sy, sx] = True; sz = 0
                while stack:
                    y, x = stack.pop(); sz += 1
                    for dy, dx in ((1,0),(-1,0),(0,1),(0,-1)):
                        a, b = y+dy, x+dx
                        if 0 <= a < ny and 0 <= b < nx and m[a,b] and not vis[a,b]:
                            vis[a,b] = True; stack.append((a,b))
                sizes.append(sz)
    return sorted(sizes, reverse=True)


def run(mo, ct, inp, bg_index, lookup, buf):
    raster, paired, counts = classify(
        inp["ndvi"], inp["canopy"], inp["impervious"], inp["landcover"],
        inp["obs_count"], bg_index, buf,
        ndvi_thr=float(config.NDVI_THR), canopy_thr=ct,
        imperv_thr=float(config.IMPERV_THR), min_obs=mo,
        water_class=int(config.WATER_CLASS),
        ref_canopy_max=float(config.REF_CANOPY_MAX),
        built_classes=tuple(config.BUILT_CLASSES))
    tcand = tree_mask(inp["ndvi"], inp["canopy"], inp["impervious"], inp["landcover"],
                      inp["obs_count"], ndvi_thr=float(config.NDVI_THR), canopy_thr=ct,
                      imperv_thr=float(config.IMPERV_THR), min_obs=mo,
                      water_class=int(config.WATER_CLASS)) & (~buf)
    tree_final = (raster == 1)
    tb = bg_index[tree_final]
    vc = pd.Series(tb).value_counts()
    geoid_map = dict(zip(lookup.bg_index, lookup.GEOID))
    print(f"\n--- MIN_OBS={mo} CANOPY={ct:.0f}: tree_px={counts['n_tree_px']} "
          f"ref_px={counts['n_ref_px']} paired_BG={counts['n_paired_blockgroups']} ---")
    print("  tree px per paired BG (GEOID: n):",
          {geoid_map.get(int(k), int(k)): int(v) for k, v in vc.items()})
    cs = cluster_sizes(tcand)
    print(f"  candidate tree px={int(tcand.sum())} ; 4-conn clusters={len(cs)} ; "
          f"cluster sizes (top 12)={cs[:12]} ; singletons={sum(1 for s in cs if s==1)} ; "
          f"max_cluster={cs[0] if cs else 0} ({100*cs[0]/max(1,sum(cs)):.1f}% of cand px)")
    # ref px per BG too (paired only)
    rb = bg_index[raster == 2]
    rvc = pd.Series(rb).value_counts()
    print("  ref px per paired BG (GEOID: n):",
          {geoid_map.get(int(k), int(k)): int(v) for k, v in rvc.items()})
    return counts


def main():
    inp = load_inputs(config.PROCESSED_DIR)
    bg_index, lookup = rasterize_blockgroups(config.INTERIM_DIR)
    buf, _ = building_buffer_mask(config.INTERIM_DIR,
                                  min_area_m2=config.TALL_BUILDING_MIN_AREA_M2,
                                  buffer_m=config.BUFFER_M)
    print("BASELINE:")
    run(20, 40.0, inp, bg_index, lookup, buf)
    print("\nRECOMMENDED candidate:")
    run(15, 30.0, inp, bg_index, lookup, buf)
    print("\nALT (canopy 35):")
    run(15, 35.0, inp, bg_index, lookup, buf)

    # Where do the 20->15 MIN_OBS gained tree px live (obs in [15,20) )?
    obs = inp["obs_count"]
    for ct in (30.0, 35.0, 40.0):
        t20 = tree_mask(inp["ndvi"], inp["canopy"], inp["impervious"], inp["landcover"], obs,
                        ndvi_thr=0.5, canopy_thr=ct, imperv_thr=20.0, min_obs=20, water_class=11) & ~buf
        t15 = tree_mask(inp["ndvi"], inp["canopy"], inp["impervious"], inp["landcover"], obs,
                        ndvi_thr=0.5, canopy_thr=ct, imperv_thr=20.0, min_obs=15, water_class=11) & ~buf
        gained = t15 & ~t20
        og = obs[gained]
        print(f"\nCANOPY={ct:.0f}: MIN_OBS 20->15 adds {int(gained.sum())} cand tree px; "
              f"their obs_count: {sorted(og.tolist())[:30]}")


if __name__ == "__main__":
    main()
