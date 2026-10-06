# Provisional review of the 2023 cooling pilot

Prepared 4 October 2026 under the user's request to do Step 4. This review uses the previously released temperature results and public support/precision evidence. The user’s instruction to keep new effects sealed remains controlling. No new spatial-effect or paired-scale values were opened or displayed for this review.

**Provisional decision:** retain all eleven Phoenix and five Atlanta 2023 passes as the descriptive baseline, retain the frozen mean models and controls, and treat the common footprint as a population sensitivity. Prepare a predictor-only endpoint/covariate-support audit as the recommended next bounded preparation. Step 5 model fits, new time comparisons, simulation effect calibration and study expansion remain on hold while the quantitative spatial/paired-scale review is deferred. This completes the provisional Step 4 synthesis and decision record; the full effect-based Stage 1 decision remains unresolved.

## Released cooling estimates and dates

The released estimates describe canopy-associated mixed-pixel surface cooling under one slope per city-pass, native-cell observations, 1km block intercepts and the six existing context controls. Positive cooling is the negative temperature change associated with **+10 percentage points of canopy fraction**. Units are K per +10pp; K and °C differences have the same numerical magnitude. These are conditional spatial associations, not isolated tree temperatures or estimated causal planting effects.

Phoenix's eleven estimates span **0.893–1.705 K/+10pp**. The largest occurs on July 29 at 13.325 apparent solar hours; the smallest occurs on June 11 at 16.213 hours. Atlanta's five estimates span **0.097–0.338 K/+10pp**, with the largest on June 3 at 11.709 hours and the smallest on June 8 at 17.376 hours. These identify descriptive extremes among the released fits. They are not regression-influence scores, and no fitted time pattern or leave-date-out comparison was computed here.

All sixteen existing 8km percentile intervals lie above zero within their individual spatial models. The intervals characterize within-pass spatial uncertainty. They do not quantify an afternoon-minus-morning change, seasonal effect or causal city ranking. Phoenix and Atlanta also have markedly different canopy support: original pass medians are about **2.48%–3.01%** and **28.17%–33.61%** respectively. A common +10pp unit alone does not establish comparable populations or covariate overlap. [Released result packet](../../../deliverables/Results_Review_2023_v6_2_20261004/README.md)

### Phoenix

| Date in 2023 | Solar hour | Cooling K per 10pp | 95% interval 1km | 95% interval 8km | HRRR linked |
| --- | ---: | ---: | --- | --- | --- |
| 06-11 | 16.213 | 0.893 | [0.859, 0.927] | [0.829, 0.958] | yes |
| 06-15 | 14.545 | 1.289 | [1.225, 1.357] | [1.180, 1.407] | yes |
| 06-19 | 12.910 | 1.395 | [1.321, 1.468] | [1.270, 1.527] | missing |
| 06-26 | 10.425 | 1.232 | [1.172, 1.297] | [1.134, 1.329] | missing |
| 07-29 | 13.325 | 1.705 | [1.644, 1.768] | [1.585, 1.838] | yes |
| 08-06 | 10.102 | 1.441 | [1.383, 1.499] | [1.336, 1.547] | yes |
| 08-11 | 15.824 | 0.928 | [0.865, 0.992] | [0.823, 1.035] | yes |
| 08-15 | 14.278 | 1.256 | [1.139, 1.356] | [1.097, 1.413] | yes |
| 08-23 | 11.150 | 1.036 | [0.980, 1.091] | [0.943, 1.123] | missing |
| 09-21 | 16.001 | 0.900 | [0.857, 0.945] | [0.811, 0.982] | missing |
| 09-25 | 14.440 | 1.129 | [1.088, 1.172] | [1.054, 1.206] | missing |

### Atlanta

| Date in 2023 | Solar hour | Cooling K per 10pp | 95% interval 1km | 95% interval 8km | HRRR linked |
| --- | ---: | ---: | --- | --- | --- |
| 06-03 | 11.709 | 0.338 | [0.326, 0.350] | [0.313, 0.364] | yes |
| 06-07 | 10.055 | 0.228 | [0.220, 0.237] | [0.210, 0.245] | yes |
| 06-08 | 17.376 | 0.097 | [0.093, 0.102] | [0.088, 0.107] | yes |
| 06-23 | 11.562 | 0.222 | [0.204, 0.239] | [0.199, 0.243] | missing |
| 07-22 | 16.042 | 0.161 | [0.150, 0.172] | [0.145, 0.178] | yes |

Values are rounded to three decimals for reading; the [original results CSV](../../../deliverables/Results_Review_2023_v6_2_20261004/pass_results_long.csv) retains full precision and exact city/orbit/run identities. Both group sizes use the same mean model and cells. HRRR linked means cached acquisition-linked air temperature/VPD, not rainfall completeness. The [Phoenix](../../../deliverables/Results_Review_2023_v6_2_20261004/phoenix_cooling_vs_apparent_solar_time.png) and [Atlanta](../../../deliverables/Results_Review_2023_v6_2_20261004/atlanta_cooling_vs_apparent_solar_time.png) figures preserve all original dates without a new fitted curve.

## Geography and information concentration

The all-eleven Phoenix intersection contains **196,090 cells and 960.841 km² of whole native footprints**, retaining **35.2%–57.3%** of each original pass. The [footprint map](../../../deliverables/Spatial_Scale_Review_2023_v6_2_20261004/common_footprint_predictor_map.png) shows which geography persists across all dates; it displays cell centres rather than clipped city polygons. It contains no interpolated temperature layer.

The retained population differs from excluded cells. Its median elevation is **419.9 m**, compared with excluded-pass medians of **361.6–399.0 m**. Median distance to water is **3,542.7 m**, compared with **2,562.8–2,888.9 m**; median impervious fraction is **0.4502**, compared with **0.4751–0.5651**. Its canopy median, **0.0279**, lies within the excluded-pass range of **0.0213–0.0323**. Thus similar canopy medians would conceal substantive changes in the other controls. This is evidence of composition change, not evidence that cooling changed by a particular amount. [Seven-variable distributions](../../../deliverables/Spatial_Scale_Review_2023_v6_2_20261004/canopy_context_distributions.csv)

Effective residualized canopy-information blocks decrease from an original Phoenix range of roughly **1,390–2,237** to about **910** in the common sample. These are concentration summaries, not independent days. The available summaries do not identify which named neighbourhoods drive cooling coefficients, and this review performed no neighbourhood influence analysis. Geographic retention and coefficient influence remain distinct questions.

The common sample contains only **54 cells with positive bare cover**, with within-block variation in **10 blocks and five 8km groups**. All **48 failures among 22,000 joint draws** exactly coincide with omission of that variation from the resampled common population. There are **21,952 estimable draws**, and all 22 configurations have estimable summaries. No failed draw was replaced and no control was removed. Any later interval interpretation must acknowledge that it summarizes the estimable paired draws. The observed zero-variation condition is a mathematical identifiability finding, not a new ecological inclusion cutoff. [Outcome-blind rank audit](../../../deliverables/Spatial_Scale_Review_2023_v6_2_20261004/sparse_control_rank_audit.json)

## Alignment and paired scales remain unresolved numerically

Step 3 recovered the eleven original/common models and constructed joint 1km/8km intervals using the same physical-group multiplicities in both populations and outcome spaces. Missing common blocks contribute zero. The **24 fixed-support registration comparisons** have validated sample/draw correspondence. The **44 available-support shift points** combine alignment and possible population changes; their constituent intervals are preserved, but paired difference intervals were not established for these archived pairs.

Those numerical effects and comparison figures remain sealed. Consequently this review cannot determine whether registration or the common footprint changes cooling materially, which change is largest, or whether a spatial change is explained. Precision and successful computation cannot supply the missing effect magnitudes. The original sixteen-pass baseline therefore stays primary, and there is no present basis for replacing it with the shared footprint or declaring a robustness pass/fail. [Spatial review packet](../../../deliverables/Spatial_Scale_Review_2023_v6_2_20261004/README.md)

The **32 paired temperature/flux-reference configurations and 144 reference sensitivities** are also stored privately. All sixteen passes have blocks covering the frozen raw canopy endpoints; this does not establish joint covariate overlap between cities. The diagnostics use the same retrievals, cells and paired draws, with exact reference-anchored inversion. They provide no independent validation. Temperature remains primary, and the historical automatic promotion of flux remains excluded from review decisions. Reza's tolerance is unset, so numerical agreement and new effect display remain deferred under the current instructions.

## Time and weather limit interpretation

Phoenix contributes four June, one July, four August and two September observations; Atlanta contributes four June and one July. The complete cached Phoenix 2023 catalogue has **no July or September morning acquisition in 09:30–11:30 apparent solar time**, before cloud/geometry screening. A fully balanced June–September pattern is therefore unsupported by this archive. Adding other-year fits would change the pilot's year scope rather than repair those missing 2023 combinations. [Controlling sample description](phoenix_2023_sample_scope.md)

The proposed five-date June/August window sensitivity remains a separate possible analysis. Different dates supply its morning and afternoon observations, so it cannot by itself separate time from associated weather/date differences or answer an exact 10:30-versus-16:00 target. The primary question remains the total observation-time pattern, including associated solar geometry; a supported geometry/season-standardized pattern stays secondary. No window contrast, time regression or temporal uncertainty interval was computed for Step 4. Future time uncertainty must use independent pass/day clusters and actual-design calibration; dependent pixels and spatial bootstrap draws are not additional temporal observations.

Cached linked HRRR air temperature/VPD covers **10/16 acquisitions: 6/11 Phoenix and 4/5 Atlanta**. Missing brackets affect Phoenix June 19, June 26, August 23, September 21 and September 25, and Atlanta June 23. Acquisition-linked rainfall totals remain unacquired. Geometry coverage is not fully quantified in reused sources, and azimuth completeness retains the frozen pilot exception. Weather similarity, complete geometric control and a VPD adjustment are not established; VPD remains descriptive. [Missing-input ledger](../../../deliverables/Results_Review_2023_v6_2_20261004/missing_inputs.json)

## Provisional decisions and the next bounded preparation

| Topic | Decision now | Dependency for a stronger decision |
| --- | --- | --- |
| Main sample | Retain all 11 Phoenix and 5 Atlanta 2023 passes; other-year weight remains zero | A separate recorded sample-scope decision for any change |
| Shared footprint | Keep as a labelled sensitivity; preserve the original baseline | Review sealed changes and uncertainty before deciding whether any narrowing has scientific justification |
| Controls and failed draws | Retain the frozen controls and all draw accounting | Any prospective methodological change needs evidence and its own recorded rule; no retrospective rescue |
| Next preparation | Recommend a predictor-only canopy endpoint/covariate-support and design-rank audit | Separately request and freeze that bounded audit; this review does not execute it |
| Step 5 model fits | Hold the quadratic fitting component | Complete quantitative spatial/paired-scale review and supported endpoint/design assessment before a recorded go decision |
| Time and simulations | Hold new empirical time inference and numeric effect-range selection | Supported contrast definition, linked conditions and calibrated independent-day uncertainty |
| Expansion and scale ruling | Keep expansion paused and the ruling pending | Reza's recorded tolerance, applicable release scope and a separate post-review decision |

The next recommended preparation follows the first part of Step 5: examine the historical 2.85%–12.85% pair and nearby pairs separated by 10pp, within-block coverage, endpoint neighbourhood densities and overlap of the context controls. Include the sparse-control issue and identifiability of protected linear/quadratic canopy terms. Record diagnostic widths/settings before outcome comparisons and introduce no replacement inclusion gate. Existing spline work remains exploratory context and does not replace this specified support/finite-contrast check. This is a recommendation for separately bounded preparation, not authorization or execution of a new fit.

**No numerical temporal effect range has been adopted for simulation calibration.** The released city-pass cooling ranges describe spatial association levels under different dates/populations, not a distribution of afternoon-minus-morning effects. The 0.10 K standard-error benchmark supplies neither a temporal effect size nor Reza's agreement margin. Choosing a calibration range awaits a reviewed contrast relevant to the intended time question.

## Scope and completion record

The provisional synthesis and decision record are complete. Effect-based conclusions about alignment, common-footprint changes and paired scales remain explicitly unresolved under the user's sealing instruction. No practical-change cutoff, outcome switch, professor approval or full-study go decision is recorded.

This work opened public evidence only, reused already released temperature values/intervals, and performed no new fit, resampling, raw thermal access, sealed-file access or empirical time comparison. Input identities, source checksums, the current data link, cross-document/YAML consistency and offline visual QA are recorded in [the Step 4 execution record](execution/provisional_review_step4_20261004/README.md). Earlier scientific checks and original packages remain preserved; documentation-only work did not require rerunning a scientific pipeline.
