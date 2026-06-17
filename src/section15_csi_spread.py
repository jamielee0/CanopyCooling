#!/usr/bin/env python3
"""Does the enlarged (cluster-level) sample actually give INDEPENDENT VARIATION
along the CSI axis? A breakpoint needs spread in x (CSI), not just many units.

For each queen-cluster of tree pixels, compute its per-overpass mean CSI and mean
cooling proxy, and ask: how much of the CSI variance is BETWEEN clusters (spatial,
which pixel-pairing newly exposes) vs WITHIN cluster over time (temporal, already
present at BG level)? If between-cluster CSI spread is tiny, 57 clusters add units
but almost no new x-axis leverage for a threshold -> the null cannot move.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config  # noqa: E402

import rasterio  # noqa: E402
import xarray as xr  # noqa: E402
from scipy import ndimage  # noqa: E402

CLASS_TREE = 1


def main() -> int:
    with rasterio.open(config.PROCESSED_DIR / "section10_pixel_class_70m.tif") as src:
        cls = src.read(1)
    tree_mask = cls == CLASS_TREE
    queen = np.ones((3, 3), dtype=int)
    lab, n = ndimage.label(tree_mask, structure=queen)
    n = int(n)

    csi_ds = xr.open_zarr(config.PROCESSED_DIR / "section12_csi_70m.zarr", decode_coords="all")
    csi = csi_ds["csi"].values  # (overpass, y, x)
    n_op = csi.shape[0]

    # per-cluster, per-overpass mean CSI
    rows, cols = np.where(tree_mask)
    clab = lab[rows, cols]
    cluster_ids = np.arange(1, n + 1)

    # cluster x overpass mean CSI
    cmean = np.full((n, n_op), np.nan)
    for t in range(n_op):
        vals = csi[t][rows, cols]
        for ci, cid in enumerate(cluster_ids):
            sel = (clab == cid) & np.isfinite(vals)
            if sel.any():
                cmean[ci, t] = float(vals[sel].mean())

    # time-mean CSI per cluster (its spatial position on the CSI axis)
    cluster_time_mean = np.nanmean(cmean, axis=1)
    finite = np.isfinite(cluster_time_mean)
    ctm = cluster_time_mean[finite]

    # overpass-mean CSI across clusters (the temporal axis everyone shares)
    op_mean = np.nanmean(cmean, axis=0)
    opm = op_mean[np.isfinite(op_mean)]

    print("=" * 72)
    print("CSI VARIATION: between-cluster (spatial) vs within/over-time (temporal)")
    print("=" * 72)
    print(f"clusters with finite CSI: {finite.sum()}/{n}; overpasses: {n_op}")
    print(f"\nBETWEEN-CLUSTER spread of time-mean CSI (the NEW spatial leverage):")
    print(f"   min={ctm.min():.3f} median={np.median(ctm):.3f} max={ctm.max():.3f} "
          f"range={ctm.max()-ctm.min():.3f} std={ctm.std():.4f}")
    print(f"\nTEMPORAL spread of overpass-mean CSI (shared by ALL clusters):")
    print(f"   min={opm.min():.3f} median={np.median(opm):.3f} max={opm.max():.3f} "
          f"range={opm.max()-opm.min():.3f} std={opm.std():.4f}")

    # variance decomposition on the full cluster x overpass panel
    flat = cmean[np.isfinite(cmean)]
    grand = flat.mean()
    # between-cluster: var of cluster means; within: residual
    cl_means = np.nanmean(cmean, axis=1)
    op_means = np.nanmean(cmean, axis=0)
    var_total = np.nanvar(cmean)
    var_between_cluster = np.nanvar(cl_means[np.isfinite(cl_means)])
    var_between_overpass = np.nanvar(op_means[np.isfinite(op_means)])
    print(f"\nVARIANCE of the cluster x overpass CSI panel:")
    print(f"   total var                : {var_total:.5f}")
    print(f"   between-CLUSTER var (spatial): {var_between_cluster:.5f} "
          f"({100*var_between_cluster/var_total:.1f}% of total)")
    print(f"   between-OVERPASS var (temporal): {var_between_overpass:.5f} "
          f"({100*var_between_overpass/var_total:.1f}% of total)")
    print("\nINTERPRETATION: the breakpoint lives on the CSI (x) axis. If the temporal")
    print("term dominates and the between-cluster (spatial) spread is small, then adding")
    print("57 spatial clusters multiplies UNITS but barely widens the x-axis support that")
    print("a threshold needs -> consistent with the persistent Section 14 null.")
    print("\nSUMMARY_JSON:", {
        "between_cluster_csi_range": round(float(ctm.max() - ctm.min()), 4),
        "between_cluster_csi_std": round(float(ctm.std()), 4),
        "temporal_csi_range": round(float(opm.max() - opm.min()), 4),
        "temporal_csi_std": round(float(opm.std()), 4),
        "pct_var_between_cluster": round(100 * var_between_cluster / var_total, 1),
        "pct_var_between_overpass": round(100 * var_between_overpass / var_total, 1),
    })
    csi_ds.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
