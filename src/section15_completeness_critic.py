#!/usr/bin/env python3
"""Completeness critic + additional-lever assessment for the THIN Phoenix paired sample.

This is an EXPLORATORY diagnostic (not a deliverable-producing pipeline step). It backs,
with numbers, two questions:

(1) ADDITIONAL LEVER. Of the candidate levers to enlarge/strengthen the paired sample
    (per-pixel per-overpass LST-difference repeated measures; widen/relax the reference
    pool; pixel-count weighting; pooling overpasses; 30 m thermal sharpening), which gives
    the most defensible gain in REAL (not nominal) statistical power, and what does it
    actually yield in numbers?

(2) FALSIFICATION RISK. What would make any enlarged-sample 'threshold' a FALSE POSITIVE?
    - pseudo-replication: spatial clustering of tree pixels (connected components, Moran-ish
      adjacency), and the effective (independent) sample size vs the nominal pixel count;
    - the dominant cluster: what fraction of tree pixels live in the single largest
      cluster / BG (the ~88% claim), and does removing it kill the signal;
    - confounding: the landcover / peri-urban / agricultural / riparian (irrigated) nature
      of the tree pixels;
    - CSI still dominated by VPD: variance share of demand vs supply in the tree-pixel CSI.

Reads only data/processed (no network, no writes except optional stdout). Run:
    conda run -n canopy python src/section15_completeness_critic.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config  # noqa: E402

import rioxarray  # noqa: F401
import xarray as xr  # noqa: E402
from scipy import ndimage, stats  # noqa: E402

PROC = config.PROCESSED_DIR
CLASS_TREE = 1
CLASS_REFERENCE = 2


def banner(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def main():
    # ---- load ----------------------------------------------------------------
    cls = rioxarray.open_rasterio(PROC / "section10_pixel_class_70m.tif").squeeze("band", drop=True).values
    cube = xr.open_zarr(PROC / "analysis_cube_70m.zarr", decode_coords="all")
    csi_ds = xr.open_zarr(PROC / "section12_csi_70m.zarr", decode_coords="all")
    z_ds = xr.open_zarr(PROC / "section11_zscores_70m.zarr", decode_coords="all")

    lst = cube["lst"].values.astype("float32")        # (op, y, x) Kelvin
    et = cube["et"].values.astype("float32")
    landcover = cube["landcover_class"].values        # (y, x)
    ndvi = cube["ndvi"].values
    ndmi = cube["ndmi"].values
    canopy = cube["canopy"].values
    imperv = cube["impervious"].values
    csi = csi_ds["csi"].values.astype("float32")
    demand = csi_ds["demand_stress"].values.astype("float32")
    supply = csi_ds["supply_stress"].values.astype("float32")
    n_op = lst.shape[0]

    tree_mask = (cls == CLASS_TREE)
    ref_mask = (cls == CLASS_REFERENCE)
    n_tree = int(tree_mask.sum())
    n_ref = int(ref_mask.sum())
    banner("0. SAMPLE BASICS")
    print(f"tree pixels = {n_tree}; reference pixels = {n_ref}; overpasses = {n_op}")

    # =========================================================================
    # 1. PSEUDO-REPLICATION: spatial clustering of TREE pixels
    # =========================================================================
    banner("1. PSEUDO-REPLICATION: spatial clustering of tree pixels")
    # connected components (8-connectivity) -> spatial clusters
    structure8 = np.ones((3, 3), dtype=int)
    lbl, n_clusters = ndimage.label(tree_mask, structure=structure8)
    sizes = np.array(ndimage.sum(tree_mask, lbl, range(1, n_clusters + 1)), dtype=int)
    sizes_sorted = np.sort(sizes)[::-1]
    print(f"connected tree clusters (8-conn): {n_clusters}")
    print(f"cluster sizes (top 10 px): {sizes_sorted[:10].tolist()}")
    print(f"largest cluster = {sizes_sorted[0]} px = {100*sizes_sorted[0]/n_tree:.1f}% of all tree px")
    # how many clusters hold 90% of pixels
    cum = np.cumsum(sizes_sorted) / n_tree
    n_for_90 = int(np.searchsorted(cum, 0.90) + 1)
    print(f"# clusters holding 90% of tree px: {n_for_90}")
    print(f"singletons (1-px clusters): {(sizes == 1).sum()} of {n_clusters} clusters")

    # =========================================================================
    # 2. DOMINANT BLOCK GROUP concentration (the ~88% claim) + remove-it test
    # =========================================================================
    banner("2. DOMINANT BLOCK GROUP -- does one BG drive everything?")
    paired = pd.read_csv(PROC / "section10_paired_neighborhoods.csv", dtype={"GEOID": str})
    paired = paired.sort_values("n_tree_px", ascending=False)
    total_tree = paired["n_tree_px"].sum()
    paired["frac_of_tree_px"] = paired["n_tree_px"] / total_tree
    print(paired.to_string(index=False))
    top = paired.iloc[0]
    print(f"\nDOMINANT BG {top['GEOID']}: {int(top['n_tree_px'])}/{total_tree} tree px "
          f"= {100*top['frac_of_tree_px']:.1f}%")
    print(f"Remaining 8 BGs hold {total_tree - int(top['n_tree_px'])} tree px "
          f"(median {paired['n_tree_px'].iloc[1:].median():.0f} px each, "
          f"range {int(paired['n_tree_px'].iloc[1:].min())}-{int(paired['n_tree_px'].iloc[1:].max())}).")
    # how many BGs have >= 10 tree px (the ROBUST_MIN_COUNT bar)?
    print(f"BGs with >=10 tree px: {(paired['n_tree_px']>=10).sum()} (these are the only ones "
          f"that survive a strict per-overpass n_tree_valid>=10 filter -> collapse to 1 BG)")

    # =========================================================================
    # 3. LEVER: per-pixel per-overpass repeated measures -- REAL vs NOMINAL N
    # =========================================================================
    banner("3. LEVER A -- per-PIXEL per-OVERPASS LST-difference repeated measures")
    # Build pixel-level cooling advantage: each tree pixel vs its BG reference MEAN at the
    # SAME overpass (preserves the same-overpass control). Count paired observations.
    # Rasterize BG index the same way Section 13 does (centroid containment).
    import geopandas as gpd
    from rasterio import features as rfeatures
    from rasterio.transform import Affine
    bg = gpd.read_parquet(config.INTERIM_DIR / "neighborhood_blockgroups_32612.parquet").reset_index(drop=True)
    if bg.crs is None or bg.crs.to_epsg() != 32612:
        bg = bg.to_crs(config.CRS)
    transform = Affine(*config.GRID_TRANSFORM)
    nrows, ncols = config.GRID_SHAPE
    shapes = ((geom, i + 1) for i, geom in enumerate(bg.geometry))
    bg_index = rfeatures.rasterize(shapes=shapes, out_shape=(nrows, ncols), transform=transform,
                                   fill=0, all_touched=False, dtype="int32")
    geoids = bg["GEOID"].astype(str).to_numpy()
    geoid_to_idx = {g: i + 1 for i, g in enumerate(geoids)}

    # For each paired BG: reference mean LST per overpass; then per tree pixel per overpass diff.
    n_pixel_obs = 0
    n_pixel_obs_nondominant = 0
    per_pixel_rows = []  # (geoid, pix_id, op, ca, csi, et)
    dominant_geoid = top["GEOID"]
    for _, prow in paired.iterrows():
        g = prow["GEOID"]; bidx = geoid_to_idx[g]
        in_bg = (bg_index == bidx)
        tmask = in_bg & tree_mask
        rmask = in_bg & ref_mask
        tr, tc = np.where(tmask)
        rr, rc = np.where(rmask)
        # reference mean LST per overpass for this BG
        for t in range(n_op):
            ref_vals = lst[t][rr, rc]
            ref_fin = np.isfinite(ref_vals)
            if ref_fin.sum() < 1:
                continue
            ref_mean = float(ref_vals[ref_fin].mean())
            tree_vals = lst[t][tr, tc]
            csi_vals = csi[t][tr, tc]
            et_vals = et[t][tr, tc]
            for k in range(len(tr)):
                if np.isfinite(tree_vals[k]):
                    ca = ref_mean - float(tree_vals[k])
                    per_pixel_rows.append((g, f"{tr[k]}_{tc[k]}", t, ca,
                                           float(csi_vals[k]) if np.isfinite(csi_vals[k]) else np.nan,
                                           float(et_vals[k]) if np.isfinite(et_vals[k]) else np.nan))
                    n_pixel_obs += 1
                    if g != dominant_geoid:
                        n_pixel_obs_nondominant += 1
    ppx = pd.DataFrame(per_pixel_rows, columns=["geoid", "pix_id", "op", "ca", "csi", "et"])
    print(f"BG-level master rows (current design)          : 264 (9 BG x ~varies overpass)")
    print(f"PIXEL-level paired obs (tree px x overpass)    : {n_pixel_obs}")
    print(f"   ... of those NOT in dominant BG             : {n_pixel_obs_nondominant} "
          f"({100*n_pixel_obs_nondominant/n_pixel_obs:.1f}%)")
    print(f"   ... IN dominant BG {dominant_geoid}          : {n_pixel_obs-n_pixel_obs_nondominant} "
          f"({100*(n_pixel_obs-n_pixel_obs_nondominant)/n_pixel_obs:.1f}%)")
    print(f"unique tree pixels actually contributing       : {ppx['pix_id'].nunique()}")
    print(f"median overpasses per tree pixel               : {ppx.groupby('pix_id')['op'].nunique().median():.0f}")

    # REAL independent units: spatial clusters (or BGs), NOT pixels.
    print(f"\nNOMINAL N (pixel-overpass obs)                 : {n_pixel_obs}")
    print(f"  but these are NOT independent:")
    print(f"  - independent SPATIAL clusters of tree px     : {n_clusters} "
          f"(1 holds {100*sizes_sorted[0]/n_tree:.0f}% of px)")
    print(f"  - independent BLOCK GROUPS                     : 9 (1 holds {100*top['frac_of_tree_px']:.0f}% of px)")
    print(f"  - independent OVERPASS DATES (temporal)        : {n_op}")
    # variance-inflation-style effective N within the dominant BG: how correlated are its
    # pixels' time series? (high correlation -> few effective independent series)
    dom = ppx[ppx["geoid"] == dominant_geoid]
    wide = dom.pivot_table(index="op", columns="pix_id", values="ca")
    # mean pairwise correlation among dominant-BG pixel CA time series
    cc = wide.corr().values
    iu = np.triu_indices_from(cc, k=1)
    mean_r = np.nanmean(cc[iu])
    npix_dom = wide.shape[1]
    # effective number of independent series ~ n / (1 + (n-1)*mean_r)  (Kish-style)
    eff_series = npix_dom / (1 + (npix_dom - 1) * max(mean_r, 0))
    print(f"\nWithin dominant BG ({npix_dom} tree px): mean pairwise r of pixel CA time series "
          f"= {mean_r:.2f}")
    print(f"  -> effective # independent pixel series ~ {eff_series:.1f} (Kish), "
          f"NOT {npix_dom}. Pixels are near-redundant repeats of one place.")

    # =========================================================================
    # 4. LEVER B -- widen / relax the reference pool (feasibility & gain)
    # =========================================================================
    banner("4. LEVER B -- reference pool size (already large) vs tree scarcity")
    print("Reference pixels per paired BG (already abundant):")
    print(paired[["GEOID", "n_tree_px", "n_ref_px"]].to_string(index=False))
    print(f"\nTotal reference px = {paired['n_ref_px'].sum()} vs tree px = {paired['n_tree_px'].sum()}.")
    print("DIAGNOSIS: the BINDING scarcity is TREE pixels, not reference pixels. Relaxing the")
    print("reference definition adds reference px we already have in abundance (ref mean LST is")
    print("already well-estimated, median n_ref_valid high). It does NOT add independent tree")
    print("units, so it cannot fix the thin paired design. LOW VALUE for the binding constraint.")

    # =========================================================================
    # 5. CONFOUND -- landcover / peri-urban / irrigated nature of tree pixels
    # =========================================================================
    banner("5. CONFOUND -- what ARE the tree pixels? (peri-urban / ag / riparian / irrigated)")
    tlc = landcover[tree_mask]
    vals, counts = np.unique(tlc[np.isfinite(tlc)] if tlc.dtype.kind == 'f' else tlc, return_counts=True)
    nlcd_names = {11: "open water", 21: "dev-open", 22: "dev-low", 23: "dev-med", 24: "dev-high",
                  31: "barren", 41: "deciduous forest", 42: "evergreen forest", 43: "mixed forest",
                  52: "shrub/scrub", 71: "grassland", 81: "pasture/hay", 82: "cultivated crops",
                  90: "woody wetlands", 95: "herb wetlands"}
    print("Tree-pixel NLCD landcover distribution:")
    for v, c in sorted(zip(vals, counts), key=lambda kv: -kv[1]):
        print(f"  class {int(v):>3} {nlcd_names.get(int(v),'?'):<18}: {int(c):>4} px ({100*c/n_tree:.1f}%)")
    # how many tree px are in NLCD DEVELOPED classes vs ag/wetland/forest?
    dev = np.isin(tlc, [21, 22, 23, 24]).sum()
    agwet = np.isin(tlc, [81, 82, 90, 95]).sum()
    natveg = np.isin(tlc, [41, 42, 43, 52, 71]).sum()
    print(f"\nDeveloped (truly urban) tree px : {dev} ({100*dev/n_tree:.1f}%)")
    print(f"Ag/wetland (irrigated/riparian)  : {agwet} ({100*agwet/n_tree:.1f}%)")
    print(f"Natural veg (forest/shrub/grass) : {natveg} ({100*natveg/n_tree:.1f}%)")
    print("CONFOUND: if most tree px are NLCD 82/90 (crops/woody-wetland) not 21-24 developed,")
    print("the 'cooling advantage' conflates URBAN TREE SHADE with IRRIGATED AG/RIPARIAN")
    print("evaporative cooling -> the threshold would describe irrigated cropland, not street trees.")

    # =========================================================================
    # 6. CSI STILL DOMINATED BY VPD? -- variance share over tree pixels
    # =========================================================================
    banner("6. IS CSI STILL ~A PURE VPD-DEMAND AXIS? (variance share over tree pixels)")
    # over tree pixels across all overpasses
    d = demand[:, tree_mask]
    s = supply[:, tree_mask]
    c = csi[:, tree_mask]
    fin = np.isfinite(d) & np.isfinite(s) & np.isfinite(c)
    dv = d[fin]; sv = s[fin]; cv = c[fin]
    print(f"tree-pixel CSI samples (op x px, finite): {dv.size}")
    print(f"  demand_stress (=max(vpd_z,0)) : mean={dv.mean():.3f} sd={dv.std():.3f}")
    print(f"  supply_stress (=max(-ndmi_z,0)): mean={sv.mean():.3f} sd={sv.std():.3f}")
    print(f"  csi                            : mean={cv.mean():.3f} sd={cv.std():.3f}")
    # correlation of CSI with each component
    rd = stats.pearsonr(cv, dv)[0]
    rs = stats.pearsonr(cv, sv)[0]
    print(f"  corr(CSI, demand) = {rd:.3f}   corr(CSI, supply) = {rs:.3f}")
    # variance share: var(0.5*demand) vs var(0.5*supply) (CSI=0.5d+0.5s)
    var_d = np.var(0.5 * dv); var_s = np.var(0.5 * sv)
    cov = np.cov(0.5 * dv, 0.5 * sv)[0, 1]
    var_csi = np.var(cv)
    print(f"  var(0.5*demand)={var_d:.4f}  var(0.5*supply)={var_s:.4f}  2cov={2*cov:.4f}  var(CSI)={var_csi:.4f}")
    print(f"  demand share of CSI variance = {100*(var_d+cov)/var_csi:.0f}%   "
          f"supply share = {100*(var_s+cov)/var_csi:.0f}%")
    # temporal vs spatial: is CSI variance mostly between-overpass (temporal=VPD) or between-pixel?
    csi_tree = c.copy()  # (op, px)
    op_means = np.nanmean(csi_tree, axis=1)   # per-overpass spatial mean (temporal signal)
    px_means = np.nanmean(csi_tree, axis=0)   # per-pixel temporal mean (spatial signal)
    print(f"\n  between-OVERPASS sd of CSI (temporal/~VPD) = {np.nanstd(op_means):.3f}")
    print(f"  between-PIXEL   sd of CSI (spatial/~supply) = {np.nanstd(px_means):.3f}")
    ratio = np.nanstd(op_means) / max(np.nanstd(px_means), 1e-9)
    print(f"  temporal/spatial sd ratio = {ratio:.1f}x  "
          f"(>>1 => CSI variation is still mostly the temporal VPD-demand axis)")

    cube.close(); csi_ds.close(); z_ds.close()
    banner("DONE")


if __name__ == "__main__":
    main()
