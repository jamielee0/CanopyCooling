#!/usr/bin/env python3
"""Follow-up diagnostics for pixel-level pairing: which INDEPENDENT clusters / BGs
actually contribute paired observations at each R, and the effective independent N."""
import numpy as np
import xarray as xr
import rasterio
from scipy import ndimage
from scipy.spatial import cKDTree
from collections import Counter
import geopandas as gpd
from shapely.geometry import Point

CLASS_TIF = r"C:\Users\pingp\Documents\TreeProject\project\data\processed\section10_pixel_class_70m.tif"
CUBE = r"C:\Users\pingp\Documents\TreeProject\project\data\processed\analysis_cube_70m.zarr"
BG_PARQUET = r"C:\Users\pingp\Documents\TreeProject\project\data\interim\neighborhood_blockgroups_32612.parquet"
CELL_M = 70.0
RADII_M = [140, 210, 350, 500, 1000]

with rasterio.open(CLASS_TIF) as src:
    cls = src.read(1); transform = src.transform
tree_mask = cls == 1; ref_mask = cls == 2
tree_rc = np.argwhere(tree_mask); ref_rc = np.argwhere(ref_mask)
n_tree = len(tree_rc)
tree_xy = np.column_stack([tree_rc[:, 1]*CELL_M, tree_rc[:, 0]*CELL_M])
ref_xy = np.column_stack([ref_rc[:, 1]*CELL_M, ref_rc[:, 0]*CELL_M])

# 8-conn cluster label per tree px
struct8 = ndimage.generate_binary_structure(2, 2)
lbl8, n8 = ndimage.label(tree_mask, structure=struct8)
tree_cluster = lbl8[tree_rc[:, 0], tree_rc[:, 1]]  # cluster id per tree px

# BG per tree px
bg = gpd.read_parquet(BG_PARQUET)
tx = transform.c + (tree_rc[:, 1]+0.5)*transform.a + (tree_rc[:, 0]+0.5)*transform.b
ty = transform.f + (tree_rc[:, 1]+0.5)*transform.d + (tree_rc[:, 0]+0.5)*transform.e
pts = gpd.GeoDataFrame(geometry=[Point(a, b) for a, b in zip(tx, ty)], crs=bg.crs)
joined = gpd.sjoin(pts, bg, how="left", predicate="within")
tree_bg = joined["GEOID"].astype(str).values

# ref reachability and LST
ref_kd = cKDTree(ref_xy)
ds = xr.open_zarr(CUBE, decode_coords="all")
lst_vals = ds["lst"].values
n_overpass = lst_vals.shape[0]
tree_finite = np.isfinite(lst_vals[:, tree_rc[:, 0], tree_rc[:, 1]])
ref_finite = np.isfinite(lst_vals[:, ref_rc[:, 0], ref_rc[:, 1]])

print("=== independent units that actually CONTRIBUTE paired obs, per R ===")
for R in RADII_M:
    nbrs = ref_kd.query_ball_point(tree_xy, r=R+1e-6)
    used = np.zeros(n_tree, dtype=bool)
    obs_by_cluster = Counter(); obs_by_bg = Counter()
    for ti in range(n_tree):
        ridx = np.asarray(nbrs[ti])
        if ridx.size == 0:
            continue
        good = (tree_finite[:, ti] & ref_finite[:, ridx].any(axis=1)).sum()
        if good > 0:
            used[ti] = True
            obs_by_cluster[int(tree_cluster[ti])] += int(good)
            obs_by_bg[tree_bg[ti]] += int(good)
    clusters_contributing = len(obs_by_cluster)
    bgs_contributing = len(obs_by_bg)
    total_obs = sum(obs_by_cluster.values())
    # dominant cluster / BG share of paired obs
    dom_cl = max(obs_by_cluster.values())/total_obs if total_obs else 0
    dom_bg = max(obs_by_bg.values())/total_obs if total_obs else 0
    print(f"\n R={R} m: paired obs={total_obs}; tree px used={int(used.sum())}; "
          f"independent clusters contributing={clusters_contributing}; BGs contributing={bgs_contributing}")
    print(f"   dominant-cluster share of paired obs = {100*dom_cl:.1f}%; dominant-BG share = {100*dom_bg:.1f}%")
    # show top contributing BGs
    for g, c in obs_by_bg.most_common(4):
        print(f"     BG {g}: {c} obs ({100*c/total_obs:.1f}%)")

ds.close()
print("\nDONE2")
