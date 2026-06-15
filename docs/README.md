# docs/

Written documentation: protocol notes, method descriptions, data dictionaries,
and decisions. Tracked in git as text/markdown.

- `section11_anomaly_qc_note.md` — **Section 11** results/QC note (step 4): the
  standardized-anomaly (z-score) QC outcomes for VPD, NDMI (water supply) and soil
  moisture — whole-record mean/std, the day-of-year-vs-whole-season seasonal-cycle-removal
  proof, the 2023-heatwave-window enrichment of extreme VPD-z, and the documented NDMI
  spatial-standardization deviation (single 2023 composite → no temporal climatology
  possible). Written by `src/section11_anomalies.py`.
