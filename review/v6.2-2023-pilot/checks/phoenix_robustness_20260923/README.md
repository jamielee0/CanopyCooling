# Phoenix v6.2: completed registration and shared-footprint checks

Completed 23 September 2026 for the existing 2023 pilot. No passes were added, removed or replaced; Phoenix remains eleven passes and Atlanta five. This completes the previously pending computations for the six added Phoenix passes, with new common-cell refits for all eleven Phoenix passes.

## What was run

- **24 registration refits:** move the canopy and all context maps by one native 70 m cell north, south, east and west for each of the six additions. Temperature/emissivity remain at the observed location.
- **30 fixed-support registration refits:** fit the unshifted and four shifted versions on the exact same set of cells within each pass. This separates alignment changes from changes in the available footprint.
- **11 common-cell refits:** use the exact intersection of valid native cells across all eleven current Phoenix passes, including the original five.
- Every fit uses the unchanged pooled estimator and paired LST/emitted-energy outcomes, identical rows/controls/draws across outcome spaces, and 1,000 whole-block bootstrap replicates.

All **65 paired fits** were estimable. **65,000/65,000 bootstrap draws** were estimable. The six rebuilt unshifted input tables exactly matched the original cached inputs, including all model variables and physical cell identities. All 177 source thermal-input checksums were verified before registration rebuilding. The common-cell coordinates, coordinate systems and block identities also matched exactly across passes. Twenty-four shifted-versus-unshifted fixed-support comparisons used matching spatial bootstrap draws; their changes and interval endpoints remain sealed.

## Public precision and support

The all-eleven intersection contains **196,090 native cells**, retaining **35.2%–57.3%** of each pass's original valid cells. This changes the represented footprint substantially and should be treated as a sensitivity rather than as an automatically representative replacement sample.

| Check | Paired fits | LST slope SE range, K per +10 pp canopy |
|---|---:|---:|
| Common cells across all eleven passes | 11 | 0.0212–0.0732 |
| Four shifts, available support | 24 | 0.0216–0.0583 |
| Unshifted/four shifts, fixed within-pass support | 30 | 0.0222–0.0603 |

[All precision results](precision.csv), [common-cell precision and retention](common_cell_precision_and_retention.csv), and [registration support](registration_support.csv).

These are standard errors, not cooling gradients. Coefficients, their differences from the original unshifted fits, and signs were calculated programmatically and stored in sealed files. They were not displayed or included in this package. No numerical threshold for an acceptable change was invented, and numerical completion does not establish that the effect estimates are insensitive to alignment or composition. That interpretation remains for authorized coefficient review.

## Limits and next decisions

The shared footprint does not remove differences in dates, weather or season. Moving all context layers together is a sensitivity to alignment with ECOSTRESS; it does not separately estimate each input layer's registration error. These checks do not settle the viewing-angle exception, context-vintage sensitivities, nonlinear canopy sensitivity, temporal-bootstrap correction, scale-agreement tolerance or final study expansion. No empirical time model was fitted.

Original outputs and the earlier pending-status completion record are preserved as historical execution records. The new scientific output run is `phoenix_robustness_20260923`; its execution freeze records the exact inputs, source-code hashes and diagnostic definitions before refitting.
