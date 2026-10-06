# Implementation and execution of the amended v6.2 pilot

## Current extension — 21 September 2026

The user explicitly authorized continued work, additional passes, a methods review and U.S. city screening. The bounded exploratory extension is complete: Phoenix now has eleven paired Stage 1 passes, Atlanta retains five, and nineteen Census urban areas have canopy/2023 acquisition/cloud-mask screening. The six new Phoenix passes produced 24 paired fits across 1/2/4/8 km resampling groups. Read `deliverables/Methodology_and_Expansion_v6_2_20260921/README.md` for the current results, figures, method issues and next decisions.

The original ten LST gradients were disclosed at the user's request on 19 September. The extension includes an explicitly recorded LST pass-gradient table/plot. It is exploratory and cannot be called blinded. Raw model files stay in sealed storage; the original precision package remains a historical snapshot. Reza's numerical scale-agreement tolerance is still pending, and no final agreement ruling has been made.

A synthetic calibration identifies excess uncertainty in the inherited time bootstrap, which resamples noisy pass estimates and adds Stage 1 noise again. Earlier time-comparison uncertainty is provisional. A tested day-cluster benchmark without extra jitter is available; no new empirical time regression was fitted in this extension. Keep the total time pattern primary and geometry/season standardization secondary where supported.

The earlier blanket pause is superseded for this bounded extension. Full-archive processing and the additional-city thermal rollout have not been performed. LA input completion, expanded-pass registration/composition checks, canopy nonlinearity sensitivity and calibrated time inference remain next steps. Do not infer professor approval from the user's continuation request.

## Original pilot documentation (19 September snapshot; current status above controls)

The pooled city-pass estimator replaces the retired block-pass design. The limited five-Phoenix/five-Atlanta run is complete; its public precision evidence, simulation results and review decisions are in `deliverables/Pilot_Meeting_Package_v6_2_20260919/README.md`. Empirical coefficients and time contrasts remain sealed.

Completed work includes complete mission metadata reconciliation, native-footprint ownership, known-case canopy aggregation checks, matching Collection 2 wideband emissivity, nonthermal Atlanta selection before thermal download, paired LST/emitted-energy fitting, 1,000 whole-block bootstrap draws, four cardinal registration shifts, exact common-cell fits, 2/4/8 km spatial groups, residual correlation diagnostics, frozen reference predictions and the exact fourth-root transform. The synthetic test uses seven scenarios and four fixed component contrasts for all ten passes. Total-time and secondary geometry/season models report support separately.

The current runner commands, from the workspace root using the urbanv2 Python environment, are:

```sh
python src/run_v6_2_pooled_pilot.py --manifest docs/v2/v6_2/execution/phoenix_execution_manifest.json
python src/run_v6_2_pooled_pilot.py --manifest docs/v2/v6_2/execution/atlanta_execution_manifest.json
python src/run_v6_2_residual_audit.py docs/v2/v6_2/execution/phoenix_execution_manifest.json
python src/run_v6_2_residual_audit.py docs/v2/v6_2/execution/atlanta_execution_manifest.json
python src/run_v6_2_scale_diagnostics.py docs/v2/v6_2/execution/phoenix_execution_manifest.json docs/v2/v6_2/execution/atlanta_execution_manifest.json
python -m unittest discover -s tests/v6_2_pooled -q
```

These commands document the executed sequence, not permission to overwrite frozen artifacts. The precision runner validates code/config hashes, and the scale runner refuses to replace its existing design freeze. Phoenix’s original frozen runner is archived under `execution/phoenix_frozen_code`; subsequent output-boundary hardening is recorded without changing its numerical fit.

Review remains necessary for Reza’s numerical scale tolerance, release of the empirical comparison, incomplete Collection 3 historical coverage, the pilot’s 25-degree geometry exception, and independent-pass power before expansion. Precision alone does not establish cooling effects, time-pattern power or scale agreement. No four-of-five rule or replacement canopy-span threshold is used. Full-city scaling remains paused. The version remains 6.2.
