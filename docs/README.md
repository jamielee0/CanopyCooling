# docs/

Written documentation: protocol notes, method descriptions, data dictionaries,
and decisions. Tracked in git as text/markdown.

- `pipeline.md` — **end-to-end reproduction guide**: the full dependency DAG
  (0 → 14), each step's command + key outputs, the driver (`src/run_all.py`)
  usage, the 3–4 manual touch-points, and how to re-run the network-free
  processing half (9–14) from saved interim (`run_all.py --from 9
  --skip-download`).
- `section11_anomaly_qc_note.md` — **Section 11** results/QC note (step 4): the
  standardized-anomaly (z-score) QC outcomes for VPD, NDMI (water supply) and soil
  moisture — whole-record mean/std, the day-of-year-vs-whole-season seasonal-cycle-removal
  proof, the 2023-heatwave-window enrichment of extreme VPD-z, and the documented NDMI
  spatial-standardization deviation (single 2023 composite → no temporal climatology
  possible). Written by `src/section11_anomalies.py`.
- `section14_results_note.md` — **Section 14** results note (step 79): the **first scientific
  result** — the pilot threshold estimate for cooling advantage vs the Compound Stress Index,
  its uncertainty from **two independent methods** (segmented-regression breakpoint + bootstrap
  CI, and an independent `ruptures` change-point), the ET corroboration, and the data-adequacy
  caveats. **Verdict: no robust threshold detected** (a valid outcome under the protocol's
  common-pitfall gate, not a failure): the relationship is flat (|Pearson r| < 0.1, p > 0.3 in
  every sample), the segmented kink is **not** preferred over a straight line (ΔAIC > 0
  everywhere), the breakpoint is **not** identified (bootstrap CI spans 62–97 % of the CSI
  range), the two methods do not agree on a well-identified break, and ET shows no mechanistic
  decline. Driven by the **thin paired sample** (9 BGs, one dominant; median `n_good_obs` = 2)
  and a CSI axis that is ~entirely **temporal VPD-demand** (the NDMI supply z is static in time).
  Produced by `notebooks/14_exploratory_threshold.ipynb` (logic in `src/section14_threshold.py`).
