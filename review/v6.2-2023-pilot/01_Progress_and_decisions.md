# Progress and decisions for review

## Completed

- Corrected paired Stage 1 estimator: one canopy slope per city/pass, block intercepts, six within-block context covariates; no arbitrary canopy-span or pass-count gate.
- Original five Phoenix/five Atlanta pilot, plus six additional 2023 Phoenix passes. Atlanta was selected using canopy heterogeneity and verified acquisition metadata before its thermal download.
- Shared LST/emitted-energy cells and bootstrap draws; 1,000 replicates and 1/2/4/8 km spatial grouping sensitivity. Standard errors and support are in the main sixteen-pass table.
- Original ten-pass registration and common-cell checks; native ownership/overlap audit; initial synthetic mixing scenarios and exact standardized inversion on the original ten passes.
- Complete catalogue metadata audit, Phoenix month/time audit and nonthermal screening of nineteen US urban areas.
- A month-balanced June/August 2023 window sensitivity has been specified. No new empirical window/time contrast was fitted. All eleven existing Phoenix results are retained.

The original ten LST gradients and subsequent six-pass Phoenix LST plot were previously viewed under user-authorized exploratory disclosure. The work cannot be represented as globally blinded. No previously sealed empirical time contrast is published here. The seven other-year fit coefficients remain sealed and those passes receive zero weight in the main pilot.

## Changes proposed for discussion

1. Retain 2023 as the main pilot. Report its actual time/season support; use June/August month balance as a sensitivity. Additional years require a separate scope decision and do not fill missing 2023 cells.
2. Keep the linear canopy model as baseline; add a low-complexity nonlinear sensitivity with predictions at the same supported canopy endpoints. Phoenix/Atlanta slope differences may partly reflect their different predictor distributions.
3. Correct and calibrate temporal uncertainty. An internal controlled simulation found excess uncertainty when noisy pass estimates were resampled and then perturbed again with Stage 1 draws. The implemented day-cluster benchmark avoids that extra perturbation, but does not yet validate a final hierarchical or dependent-day model.
4. Finish added-pass registration and common-cell fits. Retain spatial residual/range checks and 1/2/4/8 km sensitivity; 8 km is not a demonstrated independence distance. Changing clouds changes the contributing geography.
5. Review the 25-degree pilot geometry exception versus the intended 15-degree design and incomplete azimuth data. Only three of the current eleven Phoenix passes meet the 15-degree condition. Do not infer joint geometry/season support from time coverage alone.
6. Decide on a defensible full-study Collection 2/3 plan after the historical-catalogue audit. Both pilot cities use matching Collection 2. Canopy/context date sensitivities remain needed: stable 2019–2025 median canopy, 2021 imperviousness and 2024 land cover are used with 2023 thermal observations.
7. Define the scale-agreement tolerance, distinct from the approximately 0.10 K SE feasibility reference. Earlier effect access must remain acknowledged; no retrospective claim of fully blinded tolerance selection.

The total observation-time interpretation includes associated solar geometry. A secondary geometry/season-standardized result is reported only when its actual prediction targets are supported. VPD remains descriptive because of this study's support/collinearity limitations; the global paper's VPD association does not establish a causal effect. No eight-class subpixel unmixing is proposed.

## What has not been established

A causal planting effect, air-temperature cooling, a complete summer diurnal curve, a final scale-agreement ruling, corrected multi-city time inference, a final national city sample, or readiness for full-city scaling. The fixed-contrast mixing test does not imply constant emitted-energy contrasts across different background temperatures.
