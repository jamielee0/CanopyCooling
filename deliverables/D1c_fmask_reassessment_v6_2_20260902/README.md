# D1c HLS-Fmask lead-lag reassessment

This package applies prospective rule `V6.2-D018` to the 149 acquired HLS V2
Fmask rasters. The temporal-specificity diagnostic is **demoted to exploratory** under the
frozen ruling `DEMOTE_TO_EXPLORATORY_CONFIRMATORY_SUPPORT_RULE_FAILED`.

## What was verified

- Every Fmask file matches its frozen byte count and SHA-256 manifest entry.
- Exact HLS V2 source times and unique acquisition identifiers were retained.
- A usable acquisition-block has at least 60 clear 30 m HLS cells.
- A feasible thermal-pass pair uses distinct, sensor-specific acquisitions 1-15
  days before and after the pass, has absolute-lag imbalance no greater than 3
  days, and shares at least 30 usable 1 km study blocks.
- The complete 56-row Phoenix/Los Angeles x 2019-2025 x two-window x two-sensor
  reporting grid is present.

## Interpretation boundary

This is a quality-screened timing feasibility count, not a final exposure build.
Only HLS Fmask and source metadata were opened. HLS reflectance, optical indices,
ECOSTRESS LST and new v6.2 coefficients remained unopened. The 149-file plan was
selected from the catalogue timing inventory; a failed row is conservative with
respect to un-downloaded alternative HLS pairs.

## Contents

- `memo.pdf`: superseding D1c decision memo.
- `tables/d1c_leadlag.csv`: 56 required quality-screened strata.
- `figures/d1c_timing.png` and `.svg`: verified pre/post lag histograms.
- `data/d1c_verified_pairs.json`: one record per candidate pass/window/sensor.
- `data/d1c_fmask_acquisitions.json`: per-acquisition QA coverage diagnostics.
- `analysis_manifest.json`: inputs, checks, numerical result and ruling.
- `checksums.txt`: SHA-256 for every other package file.
