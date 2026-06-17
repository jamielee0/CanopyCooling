#!/usr/bin/env python3
"""Quantify the REAL yield of the repeated-measures lever + the remove-dominant falsification.

(A) Within-pixel temporal repeated measures: for the dominant BG's well-sampled tree pixels,
    regress per-pixel per-overpass cooling advantage on per-pixel per-overpass CSI with a
    PIXEL FIXED EFFECT (mixed-model spirit) -> the WITHIN-pixel CA-vs-CSI slope. This is the
    one design that uses real degrees of freedom (66 overpass dates) without inventing
    spatial independence. Report effective N = (independent clusters) x (overpass dates).

(B) Remove-dominant test: does the CA-vs-CSI relationship survive dropping the dominant BG?
    If the only signal lives in the one BG, any 'threshold' is that BG's idiosyncrasy.
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
from scipy import stats  # noqa: E402
import geopandas as gpd  # noqa: E402
from rasterio import features as rfeatures  # noqa: E402
from rasterio.transform import Affine  # noqa: E402

PROC = config.PROCESSED_DIR


def banner(t):
    print("\n" + "=" * 78); print(t); print("=" * 78)


def main():
    cls = rioxarray.open_rasterio(PROC / "section10_pixel_class_70m.tif").squeeze("band", drop=True).values
    cube = xr.open_zarr(PROC / "analysis_cube_70m.zarr", decode_coords="all")
    csi_ds = xr.open_zarr(PROC / "section12_csi_70m.zarr", decode_coords="all")
    lst = cube["lst"].values.astype("float32")
    csi = csi_ds["csi"].values.astype("float32")
    et = cube["et"].values.astype("float32")
    n_op = lst.shape[0]
    tree_mask = (cls == 1); ref_mask = (cls == 2)

    paired = pd.read_csv(PROC / "section10_paired_neighborhoods.csv", dtype={"GEOID": str})
    bg = gpd.read_parquet(config.INTERIM_DIR / "neighborhood_blockgroups_32612.parquet").reset_index(drop=True)
    if bg.crs is None or bg.crs.to_epsg() != 32612:
        bg = bg.to_crs(config.CRS)
    tr = Affine(*config.GRID_TRANSFORM)
    nrows, ncols = config.GRID_SHAPE
    bg_index = rfeatures.rasterize(((g, i + 1) for i, g in enumerate(bg.geometry)),
                                   out_shape=(nrows, ncols), transform=tr, fill=0,
                                   all_touched=False, dtype="int32")
    geoid_to_idx = {g: i + 1 for i, g in enumerate(bg["GEOID"].astype(str))}

    rows = []
    for _, p in paired.iterrows():
        g = p["GEOID"]; bidx = geoid_to_idx[g]
        in_bg = (bg_index == bidx)
        trr, trc = np.where(in_bg & tree_mask)
        rfr, rfc = np.where(in_bg & ref_mask)
        for t in range(n_op):
            rv = lst[t][rfr, rfc]; rf = np.isfinite(rv)
            if rf.sum() < 1:
                continue
            rmean = float(rv[rf].mean())
            tv = lst[t][trr, trc]; cv = csi[t][trr, trc]; ev = et[t][trr, trc]
            for k in range(len(trr)):
                if np.isfinite(tv[k]):
                    rows.append((g, f"{trr[k]}_{trc[k]}", t, rmean - float(tv[k]),
                                 float(cv[k]) if np.isfinite(cv[k]) else np.nan,
                                 float(ev[k]) if np.isfinite(ev[k]) else np.nan))
    df = pd.DataFrame(rows, columns=["geoid", "pix", "op", "ca", "csi", "et"])
    dom = "040139412001"

    banner("A. WITHIN-PIXEL temporal CA-vs-CSI slope (dominant BG, pixel fixed effect)")
    d = df[(df.geoid == dom) & df.csi.notna() & df.ca.notna()].copy()
    print(f"dominant-BG pixel-overpass obs with CSI: {len(d)}; unique pixels: {d.pix.nunique()}; "
          f"overpass dates: {d.op.nunique()}")
    # center ca and csi within each pixel (removes pixel fixed effect) -> within-pixel slope
    d["ca_w"] = d["ca"] - d.groupby("pix")["ca"].transform("mean")
    d["csi_w"] = d["csi"] - d.groupby("pix")["csi"].transform("mean")
    m = d["csi_w"].notna() & d["ca_w"].notna()
    sl, ic, r, pp, se = stats.linregress(d.loc[m, "csi_w"], d.loc[m, "ca_w"])
    print(f"WITHIN-pixel (demeaned) CA-vs-CSI slope = {sl:+.3f} K/CSI  (r={r:+.3f}, p={pp:.2g}, "
          f"se={se:.3f})")
    print("  -> this is the temporal cooling-vs-stress response holding the PLACE fixed;")
    print("     uses the 66 overpass dates as the real repeated-measures axis.")
    # naive pooled slope (the pseudo-replicated one)
    sl0, _, r0, pp0, _ = stats.linregress(d["csi"], d["ca"])
    print(f"NAIVE pooled slope (pseudo-replicated)  = {sl0:+.3f} K/CSI  (r={r0:+.3f}, p={pp0:.2g})")
    print(f"  pooled p-value treats {len(d)} obs as independent -> N inflated ~{len(d)/ (1):.0f}x; "
          f"honest N = ~1 cluster x {d.op.nunique()} dates.")

    banner("B. REMOVE-DOMINANT falsification: BG-mean CA-vs-CSI without the big BG")
    # collapse to BG x overpass means (like the master table), then correlate
    bgmean = df.groupby(["geoid", "op"]).agg(ca=("ca", "mean"), csi=("csi", "mean")).reset_index()
    full = bgmean.dropna(subset=["ca", "csi"])
    nod = full[full.geoid != dom]
    for name, sub in [("ALL 9 BGs", full), ("WITHOUT dominant BG (8 BGs)", nod),
                      ("DOMINANT BG only", full[full.geoid == dom])]:
        if len(sub) >= 3:
            rr, ppv = stats.pearsonr(sub["csi"], sub["ca"])
            sl, *_ = stats.linregress(sub["csi"], sub["ca"])
            print(f"  {name:<30}: n={len(sub):>4}  pearson r={rr:+.3f} (p={ppv:.2g})  slope={sl:+.3f} K/CSI")
    print("  If the relationship is near-zero/insignificant WITHOUT the dominant BG, then any")
    print("  enlarged-sample threshold is driven by that single irrigated-cropland cluster.")

    banner("C. EFFECTIVE SAMPLE SIZE accounting (what is honestly independent?)")
    print("Design                          | nominal N | honest independent units")
    print("-" * 78)
    print(f"BG-level master table           | 264 rows  | 9 BGs (1 = 88% of tree px) -> ~1-2 eff.")
    print(f"Pixel x overpass repeated meas. | 4436 obs  | ~1.3 eff. pixel-series x 66 dates")
    print(f"                                |           |   in dominant BG; +8 sparse BGs")
    print(f"Pure TEMPORAL (1 well-sampled   |  66 dates | 66 overpass dates (1 place) -> the")
    print(f"  cluster, within-pixel)        |           |   only axis with real replication")

    cube.close(); csi_ds.close()
    banner("DONE")


if __name__ == "__main__":
    main()
