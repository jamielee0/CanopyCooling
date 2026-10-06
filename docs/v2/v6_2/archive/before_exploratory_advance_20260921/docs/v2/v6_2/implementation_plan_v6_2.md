# Implementation and execution of the amended v6.2 pilot

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
