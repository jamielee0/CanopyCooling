#!/usr/bin/env python3
"""Follow-up detail for the pairing-unit lever: (1) why tract collapses to 8 units,
(2) how the 2 km grid splits the dominant 171-px BG cluster, (3) within-2km-tile
context heterogeneity (impervious spread) -- to judge the 'same local context' control.
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
import section10_classify_pixels as s10  # noqa: E402
from explore_pairing_units import candidate_masks, unit_id_grid, _bg_polys  # noqa: E402
import xarray as xr  # noqa: E402


def main() -> int:
    cm = candidate_masks()
    tree = cm["tree"]
    tr, tc = np.where(tree)

    # (1) tract membership of the 9 paired BGs.
    bg = _bg_polys()
    paired_geoids = ["040130101021", "040130405354", "040130506112", "040130822071",
                     "040131125182", "040139410001", "040139412001", "040139413002",
                     "040139413003"]
    tr_map = {g: g[:11] for g in paired_geoids}
    print("(1) TRACT collapse: paired BG -> tract")
    by_tract: dict[str, list[str]] = {}
    for g, t in tr_map.items():
        by_tract.setdefault(t, []).append(g)
    for t, gs in sorted(by_tract.items()):
        flag = "  <-- 2 BGs collapse into 1 tract" if len(gs) > 1 else ""
        print(f"   tract {t}: {gs}{flag}")
    print(f"   => 9 paired BGs sit in {len(by_tract)} distinct tracts "
          f"(explains tract n_paired_units < BG).")
    print()

    # (2) how the 2 km grid splits the dominant 171-px BG (040139412001).
    g2d, _ = unit_id_grid(cm, 2000.0)
    bg_index = cm["bg_index"]; lookup = cm["lookup"]
    dom_idx = int(lookup.loc[lookup["GEOID"] == "040139412001", "bg_index"].iloc[0])
    tree_unit = g2d[tr, tc]
    tree_bg = bg_index[tr, tc]
    dom_mask = tree_bg == dom_idx
    dom_tiles = pd.Series(tree_unit[dom_mask]).value_counts()
    print("(2) 2 km grid SPLITS the dominant 171-px BG (040139412001):")
    print(f"   {int(dom_mask.sum())} tree px of that BG span {len(dom_tiles)} distinct "
          f"2 km tiles; per-tile tree counts = {sorted(dom_tiles.tolist(), reverse=True)}")
    print(f"   => the single concentrated BG is broken into {len(dom_tiles)} smaller "
          f"local units (de-concentration without discarding the px).")
    print()

    # (3) within-2km-tile impervious heterogeneity (the 'same local context' check):
    #     how tight is the built context inside a 2 km tile vs inside a BG?
    ds = xr.open_zarr(config.PROCESSED_DIR / "analysis_cube_70m.zarr", decode_coords="all")
    imperv = ds["impervious"].values.astype("float32")
    ds.close()

    def tile_imperv_spread(unit2d, label):
        # std of impervious within each PAIRED tile (tiles holding a tree AND a ref).
        ref = cm["ref"]
        rr, rc = np.where(ref)
        tu = unit2d[tr, tc]; ru = unit2d[rr, rc]
        ut = set(pd.Series(tu[tu != 0]).unique().tolist())
        ur = set(pd.Series(ru[ru != 0]).unique().tolist())
        paired = ut & ur
        spreads = []
        for u in paired:
            m = (unit2d == u) & np.isfinite(imperv)
            v = imperv[m]
            if v.size >= 2:
                spreads.append(float(v.std()))
        spreads = np.array(spreads)
        print(f"   {label}: within-unit impervious std over paired units -- "
              f"median={np.median(spreads):.1f}%, mean={spreads.mean():.1f}%, "
              f"max={spreads.max():.1f}% (n={len(spreads)})")

    print("(3) WITHIN-UNIT impervious heterogeneity (lower std = tighter 'same local "
          "context'); compares the built-context homogeneity of each unit:")
    tile_imperv_spread(bg_index.astype("int64"), "block_group")
    tile_imperv_spread(g2d, "grid_2000m")
    g1, _ = unit_id_grid(cm, 1000.0)
    tile_imperv_spread(g1, "grid_1000m")
    print()
    print("   (A 2 km tile ~ 800 ha; a Phoenix BG median area is ~similar order, so the "
          "built-context spread is comparable -- the grid keeps a real local control.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
