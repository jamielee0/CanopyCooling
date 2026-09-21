> Review snapshot: the opening 2023-only scope controls historical sections. See [current progress and limitations](../01_Progress_and_decisions.md) for the provisional temporal bootstrap and outstanding checks. Original workspace paths below are provenance, not commands to run from this export.

# Implementation and execution of the amended v6.2 pilot

## Current pilot scope — 2023 only

The user clarified that the pilot under discussion is **2023**. The assistant's previous rebalancing step expanded the year range without making that scope change explicit. That expansion is not the main pilot. **The current pilot remains eleven Phoenix passes and five Atlanta passes, all in 2023.** The seven processed Phoenix passes from 2019, 2024 and 2025 are preserved as a separate exploratory extension and receive no weight in the main 2023 pilot. Eighteen Phoenix passes exist on disk, but only eleven belong to the current pilot.

Read `docs/v2/v6_2/phoenix_2023_sample_scope.md` for the controlling sample description. Retain all eleven 2023 Phoenix passes for descriptive coverage. The optional balanced morning/afternoon sampling sensitivity uses five of them in June and August: each month gets half of each arm's weight, divided among that month's available passes. Three other June/August passes describe middle times; the July and September passes remain descriptive because they have no 2023 morning counterparts in 09:30–11:30 solar time. No file or result was deleted. This weighting is not a newly computed time contrast.

The complete 2023 catalogue has no July or September acquisition in that morning window, before quality screening. More observations from 2019/2024/2025 do not repair the missing 2023 combinations. A fully balanced June–September 2023 pattern therefore remains unsupported. Keep the exact 10:30-versus-late-afternoon research target distinct from a window-mean comparison; preserve the total time interpretation including associated solar geometry, with secondary geometry/season standardization only where supported.

The prior eighteen-pass/twelve-endpoint rebalancing package is a preserved exploratory multiyear result, not the controlling pilot specification. Its seven additional paired fits completed, but their point estimates remain sealed. Earlier authorized disclosures remain recorded. No new empirical time regression, scale-agreement ruling or professor approval is implied. Reza's tolerance, calibrated time inference, registration/common-cell checks and full-study season/product choices remain unresolved. The nineteen-city nonthermal screen and previous eleven-pass 2023 package remain available. Version stays 6.2.

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
