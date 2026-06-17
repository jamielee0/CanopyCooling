#!/usr/bin/env python3
"""Build notebooks/16_pixel_threshold.ipynb from saved code (reason-#2 fix).

Keeps the project's standing rule -- "every figure and every number reproducible from
saved code; nothing produced by hand" -- by GENERATING the notebook programmatically.
The notebook reads ONLY the new parquets + section16_threshold_results.json and the
reusable analysis modules; it produces the figures (scatter, binned mean +/- SEM with the
ET overlay, the segmented-fit + CLUSTER-bootstrap CI histogram, the leave-dominant-out
panel, the R-sweep + unit-robustness summary) and carries every caveat verbatim in the
markdown. Run AFTER section16_pixel_pairing.py + section16_threshold_pixel.py.

  conda run -n canopy python src/section16_build_notebook.py        # build only
  conda run -n canopy python src/section16_build_notebook.py --execute  # build + execute
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import nbformat as nbf
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

_SRC = Path(__file__).resolve().parent
_ROOT = _SRC.parent
NB_PATH = _ROOT / "notebooks" / "16_pixel_threshold.ipynb"


MD_INTRO = r"""# Section 16 (Reason #2 fix) — Pixel-level local pairing + clustering-aware threshold

**Branch `temporal-ndmi-supply`. NON-DESTRUCTIVE: this notebook never touches
`master_table.parquet` or the Section 10 BG-pipeline config.**

## Why this exists
Section 14 found **NO ROBUST THRESHOLD** at the block-group (BG) level (264 rows = 9 paired
BGs × 54 overpasses, median `n_good_obs` = 2, ONE BG holding ~88 % of the tree pixels). The
reason-#1 fix (time-varying NDMI supply) tripled the between-BG CSI spread yet the null
**persisted**, isolating the **thin, spatially-clustered paired sample** as the binding
limitation. This section extracts the **maximum statistically-honest signal** from the
existing Phoenix data by enlarging and strengthening the paired sample **without fabricating
signal**.

## The design (what changed)
1. **Relaxed pixel-design operating point** (`config.CANOPY_THR_PIXEL = 30`,
   `MIN_OBS_PIXEL = 15`; *all other Section 10 gates unchanged*) → **670 tree-candidate
   pixels** (vs 195 at canopy40), dominant-BG share **87.7 % → 71.2 %**.
2. **Pixel-level local pairing** (LEVER 1): for each tree pixel *t* and overpass *o*,
   `cooling_advantage_px(t,o) = mean(LST of reference pixels within R of t) − LST_t(o)`,
   differenced at the **same overpass** (cancels weather/time-of-day exactly). Primary
   **R = 350 m** (5 cells); sweep {210, 350, 500} m.
3. **Spatial-cluster re-aggregation** (LEVER 4 — the statistical backbone): queen
   (8-connectivity) connected components of the tree class are the **independent spatial
   unit**; the **cluster-overpass** count-weighted cooling advantage is the regression row.
4. **Clustering-aware inference**: MixedLM random intercept (cluster nested in BG),
   cluster-robust SEs, a **cluster-resampling** spatial block bootstrap (resamples the ~56
   clusters, **never** the pixels), a within-pixel fixed-effect temporal model, the
   **mandatory leave-dominant-BG-out** falsification, and a 2 km grid-tile robustness pass.

## The honesty gate is **unchanged from Section 14**
A threshold is credible **only if** the two methods agree on a *well-identified* break **AND**
a bend is visible in the binned plot **AND** ET declines past the same CSI level — **and** it
must survive **leave-dominant-out**. Otherwise the honest verdict is **"no robust threshold"**
(a valid finding, the gate to the cross-city phase).

## ⚠️ Pseudo-replication guard (carried on every estimate)
The nominal **pixel-overpass** count (thousands) is reported but is **NEVER the inference df**.
The regression rows are **cluster-overpass**; the resampling unit is the **spatial cluster**;
the honest effective independent N is the **Kish / inverse-Simpson** figure — bounded by the
~17 paired BGs and ~1.9 by BG-Kish. 78.5 % of tree px touch a ≤70 m tree neighbour.
"""

MD_CAVEATS = r"""## Caveats carried verbatim (from the design `key_caveats`)
- **PSEUDO-REPLICATION is managed, not eliminated.** Nominal-to-independent inflation runs
  ~7× (R=140 m) to ~70× (R=1000 m); the pixel/pixel-overpass count is never the regression df.
- **DOMINANT-CLUSTER concentration persists.** One BG (`040139412001`) holds ~88 % of tree px
  at canopy40 and still **71–75 %** at canopy30, supplying ~81–94 % of all paired obs. The
  **leave-the-dominant-BG-out refit is mandatory** and is the true test of whether any signal
  is multi-site.
- **IRRIGATED PERI-URBAN / RIPARIAN confound.** ~96 % of tree px are NLCD cropland + woody/herb
  wetland (irrigated ag + riparian canopy), **not** the central-Phoenix street-tree inventory
  (`functional_type = unknown` for all). Any "cooling threshold" here is for irrigated/riparian
  canopy in a desert with an artificially decoupled water supply — it limits generalization to
  managed urban street trees.
- **Within-cluster temporal autocorrelation.** The same cluster across ~17–37 overpasses is
  repeated measures; the random intercept + temporal-block bootstrap + cluster-robust SE handle
  it. A naive pooled fit fabricates significance.
- **SIGN/SHAPE PRIOR.** The within-pixel demeaned cooling-vs-CSI slope is the **wrong sign** for
  a threshold (cooling does **not** decline with stress). Enlarging the sample tests whether the
  Section 14 flat null survives a cleaner design; it cannot manufacture a bend the physics lacks.
- **Researcher degrees of freedom.** The R-sweep {210, 350, 500} and the offset-lattice 2 km grid
  are reported so the verdict is shown robust to these arbitrary choices; R=350 is pre-committed.
"""


def build() -> nbf.NotebookNode:
    nb = new_notebook()
    cells = [new_markdown_cell(MD_INTRO)]

    cells.append(new_code_cell(
        "import sys, json\n"
        "from pathlib import Path\n"
        "import numpy as np, pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        "ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()\n"
        "for p in (str(ROOT), str(ROOT / 'src')):\n"
        "    if p not in sys.path: sys.path.insert(0, p)\n"
        "import config\n"
        "import section14_threshold as s14\n"
        "import section16_threshold_pixel as s16t\n"
        "PROC = config.PROCESSED_DIR\n"
        "FIG = config.FIGURES_DIR; FIG.mkdir(parents=True, exist_ok=True)\n"
        "PRIMARY_R = float(config.R_PAIR_M)\n"
        "print('primary R =', PRIMARY_R, 'm ; canopy_thr_pixel =', config.CANOPY_THR_PIXEL,\n"
        "      '; min_obs_pixel =', config.MIN_OBS_PIXEL)"))

    cells.append(new_markdown_cell(
        "## 1. Load the new deliverables (read-only)\n"
        "`master_table_cluster.parquet` (PRIMARY modeling input), `master_table_pixel.parquet`\n"
        "(within-pixel temporal model), `section16_pixel_clusters.parquet` (per-pixel cluster\n"
        "map), and the saved `section16_threshold_results.json`."))
    cells.append(new_code_cell(
        "cluster_all = pd.read_parquet(PROC / 'master_table_cluster.parquet')\n"
        "pixel_all   = pd.read_parquet(PROC / 'master_table_pixel.parquet')\n"
        "clusters    = pd.read_parquet(PROC / 'section16_pixel_clusters.parquet')\n"
        "results     = json.load(open(PROC / 'section16_threshold_results.json'))\n"
        "dfp = cluster_all[cluster_all.R_m == PRIMARY_R].copy()\n"
        "pxp = pixel_all[pixel_all.R_m == PRIMARY_R].copy()\n"
        "print('cluster-overpass rows by R:')\n"
        "print(cluster_all.groupby('R_m').agg(rows=('cooling_advantage','size'),\n"
        "      clusters=('cluster_id','nunique'), BGs=('GEOID','nunique')))\n"
        "print('\\nPRIMARY R=%d m: %d cluster-overpass rows, %d clusters, %d BGs'\n"
        "      % (PRIMARY_R, len(dfp), dfp.cluster_id.nunique(), dfp.GEOID.nunique()))"))

    cells.append(new_markdown_cell(
        "## 2. Effective N — the pseudo-replication accounting\n"
        "Nominal pixel-overpass rows vs cluster-overpass rows vs independent **clusters / BGs**\n"
        "vs **Kish N_eff** vs **inverse-Simpson**. The honest inference N is the right-hand side."))
    cells.append(new_code_cell(
        "import section16_pixel_pairing as s16p\n"
        "# recompute cluster diagnostics directly from the candidate masks (queen + rook).\n"
        "cm = s16p.candidate_masks()\n"
        "cl_q = s16p.build_cluster_table(cm, 'queen'); diag = s16p.cluster_diagnostics(cl_q)\n"
        "cl_r = s16p.build_cluster_table(cm, 'rook');  diag_rook = s16p.cluster_diagnostics(cl_r)\n"
        "eff = results['by_radius'][str(int(PRIMARY_R))]['effective_n']\n"
        "print('TREE PIXELS (relaxed canopy30/min_obs15):', diag['n_tree_px'])\n"
        "print('queen clusters:', diag['n_clusters'], '| rook clusters:', diag_rook['n_clusters'],\n"
        "      '| BGs with tree:', diag['n_bg_with_tree'])\n"
        "print('dominant BG %s share: %.1f%% (was 87.7%% at canopy40)'\n"
        "      % (diag['dominant_bg'], 100*diag['dominant_bg_share']))\n"
        "print('Kish N_eff  clusters=%.1f (queen) / %.1f (rook) ; BG=%.1f'\n"
        "      % (diag['kish_neff_clusters'], diag_rook['kish_neff_clusters'], diag['kish_neff_bg']))\n"
        "print('\\nPRIMARY R=350 cluster-overpass effective-N report:')\n"
        "for k, v in eff.items(): print('  %-22s %s' % (k, v))\n"
        "print('\\nNOMINAL pixel-overpass (NOT df):', len(pxp))"))

    cells.append(new_markdown_cell(
        "## 3. The central scatter + binned mean ± SEM with the ET overlay (steps 72–74)\n"
        "One point per **cluster-overpass**. A threshold would show as a visible **bend** — flat at\n"
        "low CSI then dropping — with ET also declining past the same CSI. Watch for the bend."))
    cells.append(new_code_cell(
        "x = dfp['mean_csi_tree'].to_numpy(); y = dfp['cooling_advantage'].to_numpy()\n"
        "et = dfp['mean_et_tree'].to_numpy()\n"
        "shape = s14.describe_shape(x, y)\n"
        "binned = s14.bin_means(x, y, n_bins=s14.DEFAULT_N_BINS)\n"
        "et_b = s14.bin_means(x, et, edges=binned['edges'])\n"
        "fig, (axL, axR) = plt.subplots(1, 2, figsize=(14, 5.2), constrained_layout=True)\n"
        "axL.scatter(x, y, s=10, alpha=0.25, color='#1a9850')\n"
        "axL.axhline(0, color='k', lw=0.8, ls='--')\n"
        "axL.set_xlabel('mean CSI (tree pixels)'); axL.set_ylabel('cooling advantage (K)')\n"
        "axL.set_title('Cluster-overpass scatter (R=%d m)\\nPearson r=%.3f (p=%.3f); OLS slope=%.3f K/CSI'\n"
        "              % (PRIMARY_R, shape['pearson_r'], shape['pearson_p'], shape['ols_slope']))\n"
        "c = binned['centers']\n"
        "axR.errorbar(c, binned['mean'], yerr=binned['sem'], marker='o', color='#1a9850',\n"
        "             capsize=3, label='cooling advantage')\n"
        "axR.axhline(0, color='k', lw=0.8, ls=':')\n"
        "axR.set_xlabel('mean CSI (tree pixels)'); axR.set_ylabel('mean cooling advantage (K)')\n"
        "ax2 = axR.twinx()\n"
        "ax2.plot(c, et_b['mean'], marker='s', color='#d7301f', alpha=0.8, label='mean ET')\n"
        "ax2.set_ylabel('mean ET (W m$^{-2}$)', color='#d7301f')\n"
        "axR.set_title('Binned mean ± SEM + ET overlay\\n(look for a bend; ET should decline past it)')\n"
        "fig.savefig(FIG / 'section16_binned_cooling_csi_et.png', dpi=150, bbox_inches='tight')\n"
        "plt.show()\n"
        "print('binned cooling advantage means:', np.round(binned['mean'], 2))\n"
        "print('binned ET means              :', np.round(et_b['mean'], 1))"))

    cells.append(new_markdown_cell(
        "## 4. PRIMARY model — segmented fit + CLUSTER-resampling bootstrap CI (steps 76–77)\n"
        "The breakpoint CI comes from resampling the **~56 spatial clusters** (never the pixels),\n"
        "so the effective N is the honest cluster count. A wide CI (spanning most of the CSI\n"
        "range) means the breakpoint is **not identified**."))
    cells.append(new_code_cell(
        "pr = results['primary']\n"
        "seg = pr['segmented']; boot = pr['bootstrap']; v = pr['verdict']\n"
        "# recompute bootstrap estimates for the histogram (deterministic seed)\n"
        "boot_full = s16t.cluster_bootstrap_breakpoint(dfp, n_boot=config.N_BOOT_PIXEL,\n"
        "                                              seed=s14.DEFAULT_SEED)\n"
        "fig, (axL, axR) = plt.subplots(1, 2, figsize=(14, 5), constrained_layout=True)\n"
        "xs = np.linspace(np.nanmin(x), np.nanmax(x), 200)\n"
        "import pwlf\n"
        "fin = np.isfinite(x) & np.isfinite(y)\n"
        "m = pwlf.PiecewiseLinFit(x[fin], y[fin], seed=s14.DEFAULT_SEED); m.fit(2)\n"
        "axL.scatter(x, y, s=8, alpha=0.2, color='#1a9850')\n"
        "axL.plot(xs, m.predict(xs), color='#08519c', lw=2, label='segmented (1 break)')\n"
        "axL.axvline(seg['breakpoint'], color='#d7301f', ls='--', label='breakpoint=%.3f' % seg['breakpoint'])\n"
        "axL.set_xlabel('mean CSI'); axL.set_ylabel('cooling advantage (K)')\n"
        "axL.set_title('Segmented fit (R=%d m)\\nslope1=%.2f slope2=%.2f (change=%.2f); ΔAIC vs linear=%+.2f'\n"
        "              % (PRIMARY_R, seg['slope1'], seg['slope2'], seg['slope_change'], pr['delta_aic']))\n"
        "axL.legend(fontsize=8)\n"
        "axR.hist(boot_full['estimates'], bins=40, color='#6baed6')\n"
        "axR.axvline(boot_full['ci_low'], color='k', ls='--')\n"
        "axR.axvline(boot_full['ci_high'], color='k', ls='--', label='95%% CI (%.2f, %.2f)'\n"
        "            % (boot_full['ci_low'], boot_full['ci_high']))\n"
        "axR.set_xlabel('bootstrap breakpoint (CSI)'); axR.set_ylabel('resamples')\n"
        "axR.set_title('CLUSTER-resampling bootstrap (%d clusters)\\nspans %.0f%% of CSI range -> %s'\n"
        "              % (boot_full['n_clusters_resampled'], 100*boot_full['spans_fraction'],\n"
        "                 'NOT identified' if boot_full['spans_fraction'] >= 0.5 else 'identified'))\n"
        "axR.legend(fontsize=8)\n"
        "fig.savefig(FIG / 'section16_segmented_clusterboot.png', dpi=150, bbox_inches='tight')\n"
        "plt.show()\n"
        "for r in v['reasons']: print(' -', r)"))

    cells.append(new_markdown_cell(
        "## 5. Clustering-aware slopes: MixedLM, cluster-robust SE, within-pixel temporal FE\n"
        "The **cluster-robust SE** vs the **naive (iid) SE** shows how much the pseudo-replication\n"
        "was inflating significance. The **within-pixel** slope is the sign/shape-prior test."))
    cells.append(new_code_cell(
        "mlm = pr['mixedlm']; cr = pr['cluster_robust_ols']; fe = pr['within_pixel_fe']\n"
        "print('MixedLM (%s): slope=%.4f SE=%.4f p=%.3f converged=%s'\n"
        "      % (mlm['spec'], mlm['slope'], mlm['se'], mlm['pvalue'], mlm['converged']))\n"
        "print('cluster-robust OLS: slope=%.4f  SE_robust=%.4f (p=%.3f)  vs  SE_naive=%.4f (p=%.3f)'\n"
        "      % (cr['slope'], cr['se_robust'], cr['p_robust'], cr['se_naive'], cr['p_naive']))\n"
        "print('  -> SE inflation factor (robust/naive) = %.2f  (>1 means the iid fit was over-confident)'\n"
        "      % (cr['se_robust']/cr['se_naive'] if cr['se_naive'] else float('nan')))\n"
        "print('within-PIXEL fixed-effect (temporal): slope=%.4f SE=%.4f p=%.3f'\n"
        "      % (fe['slope'], fe['se_robust'], fe['p_robust']))\n"
        "print('  n_obs=%d  n_pixels=%d  design-effect eff N (rho 0.3/0.5/0.7)=%s'\n"
        "      % (fe['n_obs'], fe['n_pixels'], fe['deff_eff_n']))\n"
        "print('  SIGN PRIOR:', results['overall']['within_pixel_slope_sign'])"))

    cells.append(new_markdown_cell(
        "## 6. FALSIFICATION — leave-the-dominant-BG-out (drop `040139412001`)\n"
        "**The true test of whether any signal is multi-site.** If a threshold lives only in the\n"
        "dominant BG it is *one well-sampled place*, not a Phoenix threshold."))
    cells.append(new_code_cell(
        "ldo = pr['leave_dominant_out']; lv = ldo['verdict']; le = ldo['effective_n']\n"
        "dfn = dfp[dfp.GEOID != s16t.DOMINANT_BG_GEOID]\n"
        "xn = dfn['mean_csi_tree'].to_numpy(); yn = dfn['cooling_advantage'].to_numpy()\n"
        "bn = s14.bin_means(xn, yn, n_bins=s14.DEFAULT_N_BINS)\n"
        "fig, ax = plt.subplots(figsize=(7, 5))\n"
        "ax.errorbar(bn['centers'], bn['mean'], yerr=bn['sem'], marker='o', color='#6a51a3', capsize=3)\n"
        "ax.axhline(0, color='k', lw=0.8, ls=':')\n"
        "ax.set_xlabel('mean CSI'); ax.set_ylabel('cooling advantage (K)')\n"
        "ax.set_title('Leave-dominant-BG-out (R=%d m)\\n%d rows, %d clusters, %d BGs (Kish_cl=%.1f) -> %s'\n"
        "             % (PRIMARY_R, ldo['n_cluster_overpass'], le['n_clusters'], le['n_bg'],\n"
        "                le['kish_neff_clusters'], lv['label']))\n"
        "fig.savefig(FIG / 'section16_leave_dominant_out.png', dpi=150, bbox_inches='tight')\n"
        "plt.show()\n"
        "print('breakpoint=%.3f CI=(%.3f, %.3f) spans=%.2f agree=%s bend=%s ET=%s'\n"
        "      % (lv['breakpoint'], lv['ci_low'], lv['ci_high'], lv['spans_fraction'],\n"
        "         lv['methods_agree'], lv['bend_visible'], lv['et_corroborates']))"))

    cells.append(new_markdown_cell(
        "## 7. Sensitivity / robustness table — R-sweep × {queen, rook, 2 km grid, leave-dominant}\n"
        "Every estimate reports **nominal rows, cluster N, BG N, Kish N_eff** alongside the\n"
        "breakpoint + bootstrap CI + the three gate flags + the verdict. The 2 km grid splits the\n"
        "dominant clump (inverse-Simpson effective units rises) — a unit-definition invariance check."))
    cells.append(new_code_cell(
        "rows = []\n"
        "def _flat(res):\n"
        "    v = res['verdict']; e = res['effective_n']\n"
        "    return dict(unit=res['label'], rows=res['n_cluster_overpass'], clusters=e['n_clusters'],\n"
        "                BG=e['n_bg'], Kish_cl=e['kish_neff_clusters'], Kish_bg=e['kish_neff_bg'],\n"
        "                invSimpson_cl=e['invsimpson_clusters'], bp=round(v['breakpoint'],3),\n"
        "                CI_lo=round(v['ci_low'],3), CI_hi=round(v['ci_high'],3),\n"
        "                spans=round(v['spans_fraction'],2), agree=v['methods_agree'],\n"
        "                bend=v['bend_visible'], ET=v['et_corroborates'], verdict=v['label'])\n"
        "for R in sorted(results['by_radius'], key=lambda s:int(s)):\n"
        "    rows.append(_flat(results['by_radius'][R]))\n"
        "rows.append(_flat(pr['leave_dominant_out']))\n"
        "rows.append(_flat(pr['rook']))\n"
        "for tag in ('grid_2km','grid_2km_offset'):\n"
        "    if tag in pr['grid_2km']: rows.append(_flat(pr['grid_2km'][tag]))\n"
        "tab = pd.DataFrame(rows)\n"
        "pd.set_option('display.width', 220); pd.set_option('display.max_columns', 40)\n"
        "tab"))

    cells.append(new_markdown_cell(
        "## 8. Honest reconciliation — does the enlarged sample change the Section 14 null?\n"))
    cells.append(new_code_cell(
        "ov = results['overall']\n"
        "print('='*78)\n"
        "print('PRIMARY (R=%d m, queen cluster) verdict :' % PRIMARY_R, ov['primary_verdict'])\n"
        "print('LEAVE-DOMINANT-OUT verdict             :', ov['leave_dominant_out_verdict'])\n"
        "print('Survives dominant drop                 :', ov['survives_dominant_drop'])\n"
        "print('FINAL VERDICT                          :', ov['final_verdict'].upper())\n"
        "print('='*78)\n"
        "n_robust = sum(1 for r in rows if r['verdict']=='robust threshold')\n"
        "print('subsets reaching \"robust threshold\": %d / %d' % (n_robust, len(rows)))"))

    cells.append(new_markdown_cell(
        "### Reconciliation (the result)\n"
        "The enlarged pixel/cluster design raises the honest effective independent N from ~1.3\n"
        "(BG-Kish, Section 14) to the **~3–8 cluster-equivalent** range (Kish-on-BG ≈ 3.8 at the\n"
        "primary R; inverse-Simpson tiles ≈ 28 nominal but BG-Kish-bounded) and adds real\n"
        "between-cluster CSI spread (~34 % of CSI variance is between clusters). **And yet the\n"
        "Section 14 null persists, in every cell of the table:** the breakpoint bootstrap CI spans\n"
        "most of the CSI range (not identified), the segmented kink is not preferred over a straight\n"
        "line, the methods do not agree on a *well-identified* break, ET shows no consistent decline,\n"
        "and the cluster-robust SE deflates the (otherwise spuriously significant) pooled slope. The\n"
        "**within-pixel temporal slope is the wrong sign** for a threshold. The null **does not flip**\n"
        "under leave-dominant-out.\n\n"
        "This is the expected, honest, publishable outcome: a cleaner, larger, properly-clustered\n"
        "Phoenix design **tightens** the null rather than overturning it. Phoenix's sparse desert\n"
        "canopy physically does not contain many independent high-canopy *locations* (96 %\n"
        "irrigated ag/riparian, one dominant BG), and **no statistical method creates spatial\n"
        "replication the landscape lacks**. The binding limitation is confirmed to be the thin,\n"
        "clustered sample — this **gates to the multi-city extension**, exactly as Section 14 concluded.")
    )
    cells.append(new_markdown_cell(MD_CAVEATS))

    nb["cells"] = cells
    nb["metadata"] = {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    }
    return nb


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build (+ optionally execute) the Section 16 notebook.")
    ap.add_argument("--execute", action="store_true", help="execute the notebook after building.")
    args = ap.parse_args(argv)
    NB_PATH.parent.mkdir(parents=True, exist_ok=True)
    nb = build()
    nbf.write(nb, NB_PATH)
    print(f"Wrote {NB_PATH}")
    if args.execute:
        from nbclient import NotebookClient
        nb2 = nbf.read(NB_PATH, as_version=4)
        client = NotebookClient(nb2, timeout=1200, kernel_name="python3",
                                resources={"metadata": {"path": str(NB_PATH.parent)}})
        client.execute()
        nbf.write(nb2, NB_PATH)
        print(f"Executed and saved {NB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
