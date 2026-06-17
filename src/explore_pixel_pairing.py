#!/usr/bin/env python3
"""EXPLORATION (read-only): pixel-level local spatial pairing as a fix for the thin
paired sample. Computes REAL numbers; writes NOTHING to processed data.

Lever: instead of pairing tree vs reference by block group (9 paired BGs, one
dominant), pair EACH tree pixel with nearby REFERENCE pixel(s) within radius R at the
SAME overpass -> cooling_advantage_px = mean_LST(local refs within R) - LST(tree px).

We compute, with no fabrication:
  (A) tree/reference/building/other pixel counts from section10_pixel_class_70m.tif
  (B) for R in {140,210,350,500,1000} m (grid=70m): how many of the tree pixels have
      >=1 reference pixel within R (geometric reachability, ignoring LST)
  (C) using analysis_cube_70m.zarr lst: number of paired (tree-pixel, overpass)
      observations = tree px finite LST AND >=1 local ref finite LST that overpass,
      summed over 66 overpasses, per R
  (D) number of distinct SPATIAL CLUSTERS of tree pixels (connected components, both
      4- and 8-connectivity) -> the genuinely-independent units
  (E) dominant-BG dissolution check: do tree pixels still concentrate in one BG once
      we work at pixel level? (load BG polygons, assign each tree px to a BG)
  (F) spatial-autocorrelation / pseudo-replication diagnostics
"""
import numpy as np
import xarray as xr
import rasterio
from scipy import ndimage
from collections import Counter

CLASS_TIF = r"C:\Users\pingp\Documents\TreeProject\project\data\processed\section10_pixel_class_70m.tif"
CUBE = r"C:\Users\pingp\Documents\TreeProject\project\data\processed\analysis_cube_70m.zarr"
BG_PARQUET = r"C:\Users\pingp\Documents\TreeProject\project\data\interim\neighborhood_blockgroups_32612.parquet"

CELL_M = 70.0
RADII_M = [140, 210, 350, 500, 1000]

# ---------------------------------------------------------------------------
# (A) load class raster
# ---------------------------------------------------------------------------
with rasterio.open(CLASS_TIF) as src:
    cls = src.read(1)
    transform = src.transform
    crs = src.crs
print("=== (A) class raster ===")
print("shape", cls.shape, "crs", crs)
vals, counts = np.unique(cls, return_counts=True)
for v, c in zip(vals, counts):
    name = {0: "other", 1: "tree", 2: "reference", 3: "building-buffer"}.get(int(v), "?")
    print(f"  class {int(v)} ({name}): {int(c)}")

tree_mask = cls == 1
ref_mask = cls == 2
n_tree = int(tree_mask.sum())
n_ref = int(ref_mask.sum())
print(f"  N tree pixels = {n_tree}; N reference pixels = {n_ref}")

tree_rc = np.argwhere(tree_mask)          # (row, col)
ref_rc = np.argwhere(ref_mask)
# pixel-center coords in metres (for distance)
tree_xy = np.column_stack([tree_rc[:, 1] * CELL_M, tree_rc[:, 0] * CELL_M])
ref_xy = np.column_stack([ref_rc[:, 1] * CELL_M, ref_rc[:, 0] * CELL_M])

# ---------------------------------------------------------------------------
# (B) geometric reachability per R: how many tree px have >=1 ref within R
#     Also record, per tree px, the LIST of local-ref (row,col) within R for (C).
# ---------------------------------------------------------------------------
print("\n=== (B) geometric reachability (tree px with >=1 reference within R) ===")
from scipy.spatial import cKDTree
ref_tree_kd = cKDTree(ref_xy)
reach = {}           # R -> boolean array over tree px (has >=1 ref within R)
local_ref_idx = {}   # R -> list (len n_tree) of arrays of ref-index into ref_rc
nref_within = {}     # R -> array: count of ref px within R per tree px
for R in RADII_M:
    # query_ball_point returns, for each tree, indices of refs within R
    neighbors = ref_tree_kd.query_ball_point(tree_xy, r=R + 1e-6)
    counts_w = np.array([len(n) for n in neighbors])
    has = counts_w >= 1
    reach[R] = has
    local_ref_idx[R] = neighbors
    nref_within[R] = counts_w
    print(f"  R={R:4d} m ({R/CELL_M:.1f} cells): {int(has.sum()):3d}/{n_tree} tree px reachable "
          f"({100*has.sum()/n_tree:.1f}%); median #ref within R = {int(np.median(counts_w))}, "
          f"max = {int(counts_w.max())}")

# ---------------------------------------------------------------------------
# (C) paired (tree-pixel, overpass) observations using LST finiteness
# ---------------------------------------------------------------------------
print("\n=== (C) paired (tree-pixel, overpass) observations from LST ===")
ds = xr.open_zarr(CUBE, decode_coords="all")
lst = ds["lst"]  # (overpass, y, x) Kelvin
n_overpass = lst.sizes["overpass"]
print("  lst dims", dict(lst.sizes))

# Pull LST for tree pixels and reference pixels across all overpasses.
lst_vals = lst.values  # (overpass, y, x) -- 66 x 1155 x 1339 floats; load once
tree_lst = lst_vals[:, tree_rc[:, 0], tree_rc[:, 1]]   # (overpass, n_tree)
ref_lst = lst_vals[:, ref_rc[:, 0], ref_rc[:, 1]]      # (overpass, n_ref)
tree_finite = np.isfinite(tree_lst)                    # (overpass, n_tree)
ref_finite = np.isfinite(ref_lst)                      # (overpass, n_ref)

# Baseline (BG-level current design proxy): how many (tree-px, overpass) have finite tree LST at all
total_treepx_obs = int(tree_finite.sum())
print(f"  total (tree-px, overpass) cells with finite tree LST = {total_treepx_obs} "
      f"(of {n_tree}x{n_overpass} = {n_tree*n_overpass})")

paired_obs = {}        # R -> number of paired (tree-px, overpass) obs
n_treepx_used = {}     # R -> distinct tree px contributing >=1 paired obs
for R in RADII_M:
    neighbors = local_ref_idx[R]
    paired_count = 0
    treepx_used = np.zeros(n_tree, dtype=bool)
    for ti in range(n_tree):
        ridx = neighbors[ti]
        if len(ridx) == 0:
            continue
        ridx = np.asarray(ridx)
        # overpasses where tree px finite AND >=1 local ref finite
        ref_any = ref_finite[:, ridx].any(axis=1)   # (overpass,)
        good = tree_finite[:, ti] & ref_any
        ng = int(good.sum())
        paired_count += ng
        if ng > 0:
            treepx_used[ti] = True
    paired_obs[R] = paired_count
    n_treepx_used[R] = int(treepx_used.sum())
    print(f"  R={R:4d} m: paired (tree-px, overpass) obs = {paired_count:5d}; "
          f"distinct tree px contributing = {int(treepx_used.sum()):3d}/{n_tree}; "
          f"mean obs/tree-px = {paired_count/max(1,treepx_used.sum()):.1f}")

# ---------------------------------------------------------------------------
# (D) spatial clusters of tree pixels (connected components) = independent units
# ---------------------------------------------------------------------------
print("\n=== (D) spatial clusters of tree pixels (independent units) ===")
struct4 = ndimage.generate_binary_structure(2, 1)  # 4-connectivity
struct8 = ndimage.generate_binary_structure(2, 2)  # 8-connectivity
lbl4, n4 = ndimage.label(tree_mask, structure=struct4)
lbl8, n8 = ndimage.label(tree_mask, structure=struct8)
print(f"  4-connectivity components: {n4}")
print(f"  8-connectivity components: {n8}")
# size distribution (8-conn)
sizes8 = np.bincount(lbl8.ravel())[1:]
print(f"  8-conn component sizes: min={sizes8.min()}, median={int(np.median(sizes8))}, "
      f"max={sizes8.max()}, mean={sizes8.mean():.1f}")
order = np.argsort(sizes8)[::-1]
print("  top-5 8-conn component sizes:", sizes8[order[:5]].tolist())
print(f"  singletons (size==1): {int((sizes8==1).sum())} of {n8} components")

# Distance-based clustering (DBSCAN-like) at a few link distances:
# group tree px whose centers are within link distance -> connected components on a graph.
print("  -- distance-linked clusters of tree px (single-linkage at link distance) --")
tree_kd = cKDTree(tree_xy)
for link in [70, 100, 150, 210, 350]:
    pairs = tree_kd.query_pairs(r=link + 1e-6)
    # union-find
    parent = list(range(n_tree))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    roots = set(find(i) for i in range(n_tree))
    print(f"     link={link:4d} m: {len(roots)} clusters")

# ---------------------------------------------------------------------------
# (E) dominant-BG dissolution check: assign tree px to block groups
# ---------------------------------------------------------------------------
print("\n=== (E) dominant-BG check at pixel level ===")
try:
    import geopandas as gpd
    from shapely.geometry import Point
    bg = gpd.read_parquet(BG_PARQUET)
    print("  BG parquet rows", len(bg), "crs", bg.crs)
    # tree px center coords in MAP units (use raster transform)
    tx = transform.c + (tree_rc[:, 1] + 0.5) * transform.a + (tree_rc[:, 0] + 0.5) * transform.b
    ty = transform.f + (tree_rc[:, 1] + 0.5) * transform.d + (tree_rc[:, 0] + 0.5) * transform.e
    pts = gpd.GeoDataFrame(geometry=[Point(xx, yy) for xx, yy in zip(tx, ty)], crs=bg.crs)
    joined = gpd.sjoin(pts, bg, how="left", predicate="within")
    geoid_col = None
    for cand in ["GEOID", "geoid", "GEOID20", "GEOID10"]:
        if cand in joined.columns:
            geoid_col = cand
            break
    if geoid_col is None:
        # take first object-ish column from bg
        for c in bg.columns:
            if c != bg.geometry.name and bg[c].dtype == object:
                geoid_col = c
                break
    assigned = joined[geoid_col].fillna("UNASSIGNED").astype(str).values
    cnt = Counter(assigned)
    print(f"  tree px assigned to {len([k for k in cnt if k!='UNASSIGNED'])} distinct BGs "
          f"(col={geoid_col}); UNASSIGNED={cnt.get('UNASSIGNED',0)}")
    top = cnt.most_common(6)
    for g, c in top:
        print(f"    BG {g}: {c} tree px ({100*c/n_tree:.1f}%)")
    dom_share = top[0][1] / n_tree
    print(f"  dominant-BG share of tree px = {100*dom_share:.1f}%")
except Exception as e:
    print("  BG check skipped:", repr(e))

# ---------------------------------------------------------------------------
# (F) pseudo-replication / spatial-autocorrelation diagnostics
# ---------------------------------------------------------------------------
print("\n=== (F) pseudo-replication / autocorrelation diagnostics ===")
# nearest-tree-neighbor distance distribution (how clustered are tree px?)
dd, _ = tree_kd.query(tree_xy, k=2)  # k=2: self + nearest other
nn = dd[:, 1]
print(f"  nearest tree-px neighbor distance: min={nn.min():.0f} m, median={np.median(nn):.0f} m, "
      f"mean={nn.mean():.0f} m, max={nn.max():.0f} m")
print(f"  tree px with a tree neighbor <=70 m (adjacent): {int((nn<=70+1e-6).sum())} "
      f"({100*(nn<=70+1e-6).mean():.1f}%)")
print(f"  tree px with a tree neighbor <=210 m: {int((nn<=210+1e-6).sum())} "
      f"({100*(nn<=210+1e-6).mean():.1f}%)")

# Ratio nominal-N vs independent-N at each R (effective replication factor)
print("  nominal paired obs vs independent clusters (8-conn) per R:")
for R in RADII_M:
    print(f"    R={R:4d} m: nominal obs={paired_obs[R]}, independent spatial clusters(8-conn)={n8}, "
          f"tree px used={n_treepx_used[R]} -> inflation factor "
          f"~{paired_obs[R]/max(1,n8):.0f}x obs per independent unit")

ds.close()
print("\nDONE")
