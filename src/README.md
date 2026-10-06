# v6.2 implementation status

## Current extension — 21 September 2026

The user explicitly authorized continued work, additional passes, a methods review and U.S. city screening. The bounded exploratory extension is complete: Phoenix now has eleven paired Stage 1 passes, Atlanta retains five, and nineteen Census urban areas have canopy/2023 acquisition/cloud-mask screening. The six new Phoenix passes produced 24 paired fits across 1/2/4/8 km resampling groups. Read `deliverables/Methodology_and_Expansion_v6_2_20260921/README.md` for the current results, figures, method issues and next decisions.

The original ten LST gradients were disclosed at the user's request on 19 September. The extension includes an explicitly recorded LST pass-gradient table/plot. It is exploratory and cannot be called blinded. Raw model files stay in sealed storage; the original precision package remains a historical snapshot. Reza's numerical scale-agreement tolerance is still pending, and no final agreement ruling has been made.

A synthetic calibration identifies excess uncertainty in the inherited time bootstrap, which resamples noisy pass estimates and adds Stage 1 noise again. Earlier time-comparison uncertainty is provisional. A tested day-cluster benchmark without extra jitter is available; no new empirical time regression was fitted in this extension. Keep the total time pattern primary and geometry/season standardization secondary where supported.

The earlier blanket pause is superseded for this bounded extension. Full-archive processing and the additional-city thermal rollout have not been performed. LA input completion, expanded-pass registration/composition checks, canopy nonlinearity sensitivity and calibrated time inference remain next steps. Do not infer professor approval from the user's continuation request.

## Original pilot documentation (19 September snapshot; current status above controls)

The analysis code in this directory predates the 19 September documentation amendment. It is preserved for reproducibility and has not yet been changed to implement the pooled city-pass estimator, paired emitted-energy analysis or new pass-level support rules.

Before running the amended pilot, follow `../docs/v2/v6_2/implementation_plan_v6_2.md` and the controlling protocol. Do not treat a successful old block-pass test suite as acceptance of the new estimator. Preserve old result packages, but update the new runner and meaningful tests against the amended design.

The `data` symlink currently names the earlier location of the data directory. Verify the relocated path documented in the root README before future execution. No data or code was changed by this documentation update.
