# notebooks/

Analysis notebooks. Reusable logic lives in `src/`; notebooks only do IO and plotting.

- `14_exploratory_threshold.ipynb` — **the secondary Section 14 CSI deliverable** (steps 72–79):
  cooling advantage vs the Compound Stress Index and the Phoenix pilot threshold diagnostic.
  The primary RQ1 detector is the separate Section 15 `vpd_z` × `sm_z` response surface. Reads only
  `../data/processed/master_table.parquet` and imports `../src/section14_threshold.py`. Walks
  through the scatter, the binned mean ± SEM, the ET/ESI overlay, the QC inspection, the segmented
  fit + bootstrap CI, the independent `ruptures` change-point, and the honesty-gate verdict.
  The headline sample is daytime `sample_label == "primary"` (`n_tree_valid >= 3`); night and
  pooled-overpass runs are sensitivities. **Committed with its executed outputs** (figures →
  `../figures/section14_*.png`). Verdict: **no robust threshold detected**; Phoenix has only 9
  paired block groups, below the 10-cluster confirmatory minimum. See
  [`../docs/section14_results_note.md`](../docs/section14_results_note.md).
  Re-execute: `conda run -n canopy jupyter nbconvert --to notebook --execute --inplace notebooks/14_exploratory_threshold.ipynb`.
