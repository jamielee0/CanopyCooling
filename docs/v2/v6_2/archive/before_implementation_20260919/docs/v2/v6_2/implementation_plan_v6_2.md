# Implementation sequence for the amended v6.2 pilot

This is an implementation plan, not a report of completed scientific work. The current specification is `protocol_v6_2.yml`; the detailed procedure is `pilot_plan_v6_2.md`. Existing runners still implement the historical block-pass design.

1. Audit full catalogue metadata, tile/ground-cell overlap and area-weighted raster aggregation. Reconcile pass identities and counts. Verify the relocated data path before reading assets.
2. Keep the five frozen Phoenix passes. Screen Atlanta and Charlotte on canopy heterogeneity and afternoon metadata; select one and an equivalent five-pass set before thermal download. Verify collections and matching wideband emissivity.
3. Calculate pass-level within-block canopy information and contributing-block distributions. Freeze their thresholds and all pending precision, common-support, reference, time and scale-decision settings in a short decision-log entry.
4. Replace separate block slopes with block intercepts plus one shared canopy term per city-pass. Fit matched-cell LST and M models. Keep raw signed coefficients and the positive-cooling convention distinct. Build the exact prediction/anchoring/fourth-root procedure.
5. Implement whole-block paired bootstrap, common-cell/reweighting and ±1-cell registration checks. Verify pooling with a known synthetic example, unit conversions, overlap ownership, emissivity scaling, nonpositive anchor handling, fixed prediction centers, and leakage-free sealed outputs. Existing tests of the retired block-span gates must be replaced for the new runner, not treated as current acceptance tests.
6. Run the two-city precision pilot with all points sealed and publish only permitted precision/support diagnostics. Run clearly labeled constant-contrast mixing simulations in the synthetic output root. Record absolute-temperature access when preparing their inputs.
7. Review precision and record release of the prespecified coefficient/contrast subset. Inspect the pass plot, fit only the frozen time models, and compare total and secondary standardized patterns across model spaces.
8. Review the pilot and choose the headline scale. If both cities lack precision, report and stop. Expand to Phoenix/Los Angeles archives and eight to twelve further cities only after a recorded review decision.

No analysis, download, unsealing, commit, push, email, or meeting scheduling is performed by this documentation update.
