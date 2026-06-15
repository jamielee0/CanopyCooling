# notebooks/

Exploratory and analysis Jupyter notebooks. Keep heavy/reusable logic in
`src/`; notebooks should import from there.

- `14_exploratory_threshold.ipynb` — **Section 14 deliverable** (steps 72–79): the
  exploratory analysis of the project's central relationship — tree **cooling advantage** vs
  the **Compound Stress Index (CSI)** — and the **first threshold estimate** for Phoenix. Reads
  **only** `../data/processed/master_table.parquet` and imports the reusable analysis logic from
  `../src/section14_threshold.py`. Contains: the scatter (step 72), the binned mean cooling
  advantage ± SEM (step 73), the ET/ESI overlay on the binned axis (step 74), the distribution /
  QC inspection of too-few-pixel neighborhoods, outliers and the day/night artifact (step 75),
  the segmented (piecewise) regression with a bootstrap CI (steps 76–77), the independent
  `ruptures` change-point (step 78), the linear-vs-segmented comparison, the multi-criteria
  agreement gate, and the written conclusion (step 79). **This notebook is committed WITH its
  executed outputs** (it is the deliverable; figures saved to `../figures/section14_*.png`). Its
  honest verdict — **no robust threshold detected** for the Phoenix pilot (flat relationship; the
  segmented kink is not preferred by AIC; the breakpoint is not identified by the bootstrap; the
  two methods do not agree on a well-identified break; no ET corroboration) — and the thin-sample
  caveats are summarised in `../docs/section14_results_note.md`. Re-execute with
  `conda run -n canopy jupyter nbconvert --to notebook --execute --inplace
  notebooks/14_exploratory_threshold.ipynb`.
