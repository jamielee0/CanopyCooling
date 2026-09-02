# D1c - lead-lag feasibility

This count-only package applies frozen rule `V6.2-D009`. The ruling is
`DEMOTE_TO_EXPLORATORY_MISSING_SOURCE_TIMING_PROVENANCE`: temporal specificity is demoted to exploratory until a
source-level HLS acquisition ledger exists.

## Why the count does not establish a matched pair

- The inherited object identifies itself as `COPERNICUS/S2_SR_HARMONIZED`,
  not HLS V2. It covers Phoenix in 2023 only.
- It stores centered +/-15-day composites and pixel-level scene counts, but no
  optical acquisition identifiers, source dates, sensor-specific records, or lag signs.
- All 66 legacy axis records have a
  spatial median centered scene count of at least two. That is only a
  necessary-but-not-sufficient upper bound: both scenes could lie on the same side
  of a pass.
- No optical index value, ECOSTRESS LST value, or new v6.2 coefficient was opened.

## Contents

- `memo.pdf`: two-page-or-shorter D1c decision memo.
- `tables/d1c_leadlag.csv`: 56 required HLS strata plus two legacy-product audit rows.
- `figures/d1c_timing.png` and `.svg`: required timing histogram in an explicit
  no-verifiable-lag state.
- `data/d1c_centered_count_audit.json`: permitted count-only axis and candidate joins.
- `analysis_manifest.json`: frozen rules, source inventory, checks, and ruling.
- `code_commit.txt`: repository state and exact commands.
- `checksums.txt`: SHA-256 for every other file in this folder.

## Boundary carried forward

The centered inherited product cannot become the final antecedent exposure or
future placebo. If the temporal-specificity diagnostic is later restored, both
one-sided variables must be rebuilt from raw HLS with distinct source identifiers,
the frozen matched-lag rule, and explicit acquisition-reuse accounting.
