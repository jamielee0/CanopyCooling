#!/usr/bin/env python3
"""Quick confirmation of the panel dimensions a cluster-level mixed model would have:
- emitted overpasses in the master table (the temporal axis actually usable),
- the cluster x overpass panel size with finite CSI AND finite tree LST,
- the implied design-effect / effective-N for the FULL panel under a plausible
  intra-cluster + temporal correlation (so the recommendation's projected paired
  observations are grounded, not asserted)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config  # noqa: E402

import rasterio  # noqa: E402
import xarray as xr  # noqa: E402
from scipy import ndimage  # noqa: E402

CLASS_TREE = 1


def main() -> int:
    mt = pd.read_parquet(config.PROCESSED_DIR / "master_table.parquet")
    n_emitted_overpass = int(mt["overpass_key"].nunique())
    print(f"master_table: {len(mt)} rows, {mt['neighborhood_id'].nunique()} BGs, "
          f"{n_emitted_overpass} distinct overpasses emitted")

    with rasterio.open(config.PROCESSED_DIR / "section10_pixel_class_70m.tif") as src:
        cls = src.read(1)
    tree_mask = cls == CLASS_TREE
    queen = np.ones((3, 3), dtype=int)
    lab, n = ndimage.label(tree_mask, structure=queen)
    n = int(n)

    cube = xr.open_zarr(config.PROCESSED_DIR / "analysis_cube_70m.zarr", decode_coords="all")
    lst = cube["lst"].values  # (overpass, y, x)
    n_op = lst.shape[0]
    rows, cols = np.where(tree_mask)
    clab = lab[rows, cols]

    # cluster x overpass cells with >=1 finite-LST tree pixel (a paired obs is possible)
    paired_cells = 0
    per_cluster_obs = np.zeros(n, dtype=int)
    for t in range(n_op):
        v = lst[t][rows, cols]
        fin = np.isfinite(v)
        for ci in range(1, n + 1):
            if (fin & (clab == ci)).any():
                paired_cells += 1
                per_cluster_obs[ci - 1] += 1
    print(f"\nCLUSTER-LEVEL panel (queen): {n} clusters x {n_op} overpasses")
    print(f"  cluster x overpass cells with >=1 finite-LST tree px (a paired obs): {paired_cells}")
    print(f"  per-cluster temporal obs: min={per_cluster_obs.min()} "
          f"median={int(np.median(per_cluster_obs))} max={per_cluster_obs.max()}")

    # Design effect for repeated measures within a cluster:
    # Deff = 1 + (m_bar - 1)*rho ; N_eff = paired_cells / Deff.
    m_bar = paired_cells / n  # avg obs per cluster
    for rho in (0.3, 0.5, 0.7):
        deff = 1 + (m_bar - 1) * rho
        neff = paired_cells / deff
        print(f"  temporal rho={rho}: m_bar={m_bar:.1f} Deff={deff:.2f} -> "
              f"N_eff(panel)={neff:.0f} obs  (~{neff/m_bar:.0f} indep cluster-equivalents)")
    cube.close()

    print("\nSUMMARY_JSON:", {
        "n_emitted_overpass": n_emitted_overpass,
        "clusters_queen": n,
        "panel_paired_cells": paired_cells,
        "median_obs_per_cluster": int(np.median(per_cluster_obs)),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
