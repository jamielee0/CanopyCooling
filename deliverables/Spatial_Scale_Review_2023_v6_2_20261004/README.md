# Spatial and paired scale review for the 2023 pilot

Step 3 internal computations and the public support/precision packet are complete as of 4 October 2026. The user requested the next step, then explicitly answered **“Not yet—keep new effects sealed”** when asked about Reza's scale tolerance. This packet therefore presents nonthermal support, provenance, uncertainty methods and precision. The new effect comparisons and their figures are stored privately; their numerical interpretation and visual review remain deferred. No scale-agreement verdict, outcome switch or professor approval is implied.

The sample remains eleven Phoenix and five Atlanta acquisitions, all 2023. No pass was added, removed or replaced. The seven other-year Phoenix fits receive zero main-pilot weight. Temperature remains primary; emitted flux and its fixed-reference temperature equivalent remain paired diagnostics.

## What was completed

| Work | Result | Display scope |
| --- | --- | --- |
| All-eleven Phoenix footprint | Exact 196,090-cell intersection recovered; identities, predictors and coordinates reconcile | Public map, retention and distributions |
| Original/common point reconstruction | All eleven original and eleven common models recovered within the frozen numerical tolerance | Recovery checks public; new effects sealed |
| Joint common-minus-original uncertainty | 1 km and 8 km shared physical-group draws for every Phoenix pass: 22 configurations, 22,000 requested draws | SE/width/counts public; points/endpoints sealed |
| Fixed-support registration | All 24 existing differences for six additions validated against archived arrays, sample metadata and draw algorithm | Pairing checks/precision public; effects sealed |
| Available-support registration | 44 Phoenix shift-minus-original points assembled: 20 original-five and 24 added-six checks | Constituent precision public; point changes sealed; paired difference intervals unavailable |
| Paired temperature/flux diagnostic | All sixteen frozen endpoint-support audits; 32 1 km/8 km paired configurations computed | Support counts public; new diagnostics sealed |
| Reference dependence | Nine prescribed temperature/emissivity reference settings per pass, 144 configurations | New diagnostic values/figures sealed |

The joint bootstrap has **21,952 estimable draws and 48 non-estimable draws**. All 22 configurations have estimable interval summaries. Failed draws were not replaced, and no control, pass or rule was changed to make them estimable. The displayed precision table identifies every configuration's count. Intervals summarize the estimable paired resamples; this condition must accompany any later interpretation.

## What the footprint changes

The all-eleven intersection occupies **960.841 km² of whole native-cell footprints**, retaining **35.2%–57.3%** of each pass's original valid cells. The union of original footprints contains 556,686 unique cells. The shared footprint substantially changes represented geography; it is a labelled sensitivity rather than an automatically representative replacement population.

- Native footprint map: [PNG](common_footprint_predictor_map.png) / [PDF](common_footprint_predictor_map.pdf).
- Per-pass retention: [PNG](common_footprint_retention.png) / [PDF](common_footprint_retention.pdf).
- All seven predictor distributions: [PNG](retained_excluded_predictor_distributions.png) / [PDF](retained_excluded_predictor_distributions.pdf).

The map displays native cell centres in Phoenix's EPSG:32612 coordinate system. Areas sum unique retained whole 70 m cells, with no tile/scene double-counting or thermal interpolation. They are not city-clipped polygon areas or usable city-coverage percentages. The exact shared-cell identity hash agrees with the September 23 record.

| Median predictor | Shared cells, identical across passes | Excluded cells, range across passes |
| --- | ---: | ---: |
| Canopy fraction | 0.0279 | 0.0213–0.0323 |
| Impervious fraction | 0.4502 | 0.4751–0.5651 |
| Elevation, m | 419.9 | 361.6–399.0 |
| Distance to water, m | 3,542.7 | 2,562.8–2,888.9 |

Similar canopy medians alone would conceal these changes in elevation, water proximity and imperviousness. The map and distributions support interpreting the common-cell comparison as a population/composition sensitivity. They do not reveal the direction or magnitude of the sealed cooling change. Effective residualized canopy-information blocks decrease from an original range of about 1,390–2,237 to about 910 in the common sample; this is a concentration diagnostic, not a count of independent temporal observations.

The nonthermal rank audit explains the 48 failed resamples: **54 of 196,090 common cells have positive bare cover**, with within-block bare variation in **10 blocks and five 8 km groups**. Every failed draw exactly matches absence of that common-sample variation in the sampled groups. The frozen design retains the bare-cover control, so those draws lack an identifiable coefficient for the complete design. The audit read predictors and stored validity masks only, not outcomes or effect values. Zero denotes mathematical absence of variation, not a replacement inclusion threshold. See [the audit](sparse_control_rank_audit.json).

## How the uncertainty was checked

Original and common samples have different physical block sets. Equal archived seeds do not establish valid pairing. New draws therefore sample multiplicities once on the union of occupied physical blocks/groups and apply the same multiplicities to both populations and both outcomes. A block absent from the common sample contributes zero. Each population retains its own within-block centres and the archived canopy/context design. Repeated blocks are algebraically equivalent to fresh intercept IDs. Both archived point estimates are recovered before differences are summarized.

The 24 fixed-support registration comparisons have matching cell counts, physical block order, paired outcomes, predictor order, seeds and bootstrap-generation code. Recomputed summaries agree with their stored signed differences, SEs and sign-reversed percentile endpoints. Available-support shifts can also change which cells enter the fit. Their constituent intervals are retained separately; physical-group draw correspondence was not established for these archived available-support pairs, so their difference intervals remain unavailable here. A later validated joint-resampling construction could address that gap. Original-five and added-six checks remain explicitly distinguished.

The historical canopy pair `f0=0.028509538620710373`, `f1=f0+0.10`, temperature reference and emissivity reference were held fixed. All sixteen passes have blocks covering both raw endpoints; no reference was reselected. This establishes block endpoint support, not general joint covariate overlap or a causal city comparison. Predictions retain original training centres and controls, are averaged at each endpoint before inversion, and the exact fourth-root conversion is repeated in each matched T/M draw. The prescribed ±10 K and ±0.01 emissivity reference sensitivities are stored privately. Flux derives from the same retrievals and provides a diagnostic, not independent validation.

Larger groups are uncertainty sensitivities; an 8 km group does not prove independence. Existing residual-neighbor diagnostics for the ten original passes are preserved. They were not recomputed for the six additions. No empirical time model, day/window contrast, thermal raster rebuild, new data acquisition or additional-city work occurred. Step 2's weather/geometry/azimuth gaps remain unresolved by these spatial checks.

## Public tables and verification

- [Spatial precision review](spatial_precision_review.csv): 163 labelled constituent/difference rows, with SEs, interval widths and valid/failed draw counts; no new effect points or endpoints.
- [Canopy and context distributions](canopy_context_distributions.csv): 231 original/retained/excluded summaries across eleven passes and seven variables, with counts, mean/SD and min/max/P1–P99 quantiles.
- [Footprint and reference support](footprint_and_reference_support.csv): all sixteen identities, reference counts, Phoenix retention and original/common information concentration.
- [Inherited residual diagnostics](inherited_residual_spatial_diagnostics.csv): 20 historical boundary diagnostics for the ten original passes.
- [Dictionary](data_dictionary.md), [machine-readable definitions](data_dictionary.json), [remaining limits](remaining_limits.json) and [nonthermal summary](nonthermal_summary.json).
- [Execution freeze](../../docs/v2/v6_2/execution/spatial_scale_review_20261004/execution_freeze.json) and [verification](../../docs/v2/v6_2/execution/spatial_scale_review_20261004/verification.json).

Twenty network-free known-answer/boundary tests cover explicit fixed-effect pooling, repeated-block intercepts, shared physical draws/missing common blocks, rank failure, native identity, endpoint prediction/averaging, exact transformation, historical metadata and sealed-output protection. All 160 frozen source hashes were verified; initial code and recorded compatibility/performance repairs are preserved. CSV values roundtrip exactly through artifact-tool and final serialization. Public figures/table views were visually inspected. Sealed figures were checked only for file structure, nonblank rendering and permissions; their image pixels were not displayed or reviewed.

All new effects, draw arrays and five comparison-figure families remain under the guarded sealed output root with directory permissions 0700 and file permissions 0600. Original models/results and previous access records remain intact; no old empirical time-contrast file was opened. Reza's tolerance remains unset. **Effect-based review is still pending under the user's sealing instruction; this is not a final robustness or scale-agreement ruling.** Further study expansion remains paused. No commit, push or external message occurred.
