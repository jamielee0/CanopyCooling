# Urban canopy cooling results review and targeted analysis plan

Prepared 30 September 2026 for the user and Prof. Alizadeh; implementation initiated 4 October 2026. Current status: Steps 1–2 are complete; Step 3 internal computations and public support/precision are complete, with effect-based review deferred at the user's explicit sealing request.

Execution update 4 October 2026: the user requested starting with the first step and then the next part. Step 1 scope/access and outcome-hierarchy records are in `execution/results_review_20261004/`. Step 2 existing-result assembly is in `execution/results_packet_20261004/`, with the sixteen-original-row CSV, 48 spatial uncertainty sensitivities, dictionary, two city time figures and missing-input ledger in `deliverables/Results_Review_2023_v6_2_20261004/`. Released estimates/SEs/intervals reconcile exactly; fourteen known-answer/boundary tests and visual checks passed. No new coefficient display, model fit or empirical time comparison occurred. Steps 3–7 remain subsequent work. The original plan, first-step documents, historical packages and source checksums are preserved.

Subsequent Step 3 update: the user requested the next step and explicitly replied “Not yet—keep new effects sealed.” The internal spatial/paired-scale review and public nonthermal/precision packet are in `execution/spatial_scale_review_20261004/` and `deliverables/Spatial_Scale_Review_2023_v6_2_20261004/`. Eleven original/common point reconstructions, 22 joint group-size configurations, 24 fixed-support pair validations, 44 available-support points, 32 paired-scale diagnostics and 144 reference sensitivities are recorded. Of 22,000 new joint draws, 21,952 are estimable; an outcome-blind audit attributes all 48 failures to omitted common-sample bare-cover variation. Twenty tests passed. No effect display, sample/model-specification change or time comparison occurred. The numerical/visual effect-review component of Step 3 and the effect-based Step 4 decision remain pending; Steps 5–7 remain proposed.

Start with the existing 2023 results and spatial comparisons. Then try two bounded additions: a simple quadratic canopy sensitivity and the supported Phoenix June/August window comparison. Their purpose is to establish what the current data can say about cooling and how sampling changes that interpretation before selecting additional observations.

## Scope and current evidence

The main pilot contains eleven Phoenix and five Atlanta passes, all from 2023. Keep all sixteen in the descriptive results. The seven Phoenix passes from other years have zero weight in this pilot. Phoenix's five June/August endpoint passes support a separate window sensitivity; the complete 2023 catalogue has no July or September morning acquisition in the defined 09:30–11:30 solar window.

The baseline remains one canopy slope per city-pass, native ECOSTRESS cells, 1 km block intercepts and the six existing context controls. Paired temperature and flux calculations use the same cells, weights, covariates and spatial draws. Report canopy-associated mixed-pixel surface cooling, with positive cooling in K per +10 percentage points of canopy. Interpret the results as conditional spatial associations observed on different dates.

| Existing evidence | Current status | Use in this plan |
| --- | --- | --- |
| Sixteen released linear temperature results | Estimates and 1, 2, 4 and 8 km interval fields exist | Reuse for the initial table and time plots |
| Phoenix registration and common-cell computations | 65 paired fits and 65,000 estimable draws completed on 23 September | Reuse archived estimates; validate each difference's uncertainty |
| All-eleven Phoenix common footprint | 196,090 cells; 35.2–57.3% of each original pass retained | Show the represented geography and distribution changes |
| Fixed-support registration comparisons | 24 paired differences already computed for the six additions | Reuse after confirming draw correspondence and review-access scope |
| Common-cell versus original comparisons | Archived code records point differences | Obtain valid joint uncertainty only where it can be justified |
| September 30 nonlinear analysis | Sixteen paired restricted cubic spline fits completed | Preserve as exploratory context; implement the separate simple quadratic check |
| Replacement day-resampling benchmark | Code and known-answer tests exist | Calibrate on the actual design before empirical temporal use |
| Weather descriptors | Some records exist; completeness is unresolved | Inventory acquisition-linked coverage before interpreting weather similarity |

The outcome hierarchy follows the new guidance: temperature is primary; emitted longwave flux and its reference-temperature equivalent are diagnostics. The user-authorized first-step amendment on 4 October resolves the old automatic promotion of flux in the active protocol, preserving the prior specification. The new source document alone does not amend repository authority.

## Stage 1 Assemble and interpret the existing results

### Step 1 Record the implementation and access boundary

Create a bounded execution record before new scientific work. It should specify the sixteen-pass sample, original run identities, temperature-primary interpretation, flux diagnostic role, spatial comparison definitions and the order of review before extension. Archive and checksum the affected active documents before amending the protocol, pilot plan and decision log in place at v6.2.

Distinguish the temperature estimates and intervals already released from unreleased flux estimates, spatial differences, bootstrap arrays and time contrasts. Record the scope of user-authorized review access before displaying new sealed values. Internal computations must follow the existing sealing rules. Preserve original model arrays and access records; a private review packet is still an effect disclosure when it is shown to someone.

Keep the original sealed empirical time-contrast files outside the initial packet. Derive any later exploratory comparison under its own freeze. Reza's numerical scale tolerance remains pending; the 0.10 K standard-error benchmark supplies neither a practical time-effect threshold nor an agreement margin.

**Completion evidence:** a source/input/code manifest, the scope and disclosure record, a cross-document consistency check and a verified data-link target. The data link resolved successfully during planning; verify it again before execution.

### Step 2 Build a single labelled results table

**Completed 4 October 2026.** See the packet and execution record above. Flux/equivalent effect fields retain `SEALED_NOT_RELEASED`; cached linked air-temperature/VPD covers 10/16 passes, rainfall is not acquired, and geometry/azimuth completeness gaps remain explicit. The table does not silently substitute values for these gaps or turn resampling sensitivities into additional observations.

Start from the released sixteen-row gradient table. Join by city, orbit, source run and variant, and validate uniqueness rather than assuming orbit alone is sufficient. Use a long-format CSV: exactly sixteen rows labelled `original`, with clearly labelled sensitivity rows added beneath them. A data dictionary defines every field and missing-value reason.

Include these field groups:

- Identity: city, orbit, acquisition UTC, local date, month, apparent local solar hour, collection, source run and variant. Document the longitude and equation-of-time convention; retain civil and mean solar times as separate fields.
- Result: signed temperature slope per unit canopy fraction, signed change per +10 percentage points, positive cooling, spatial SE, 95% interval endpoints, interval method, resampling-group size and estimable draw count. Retain the original numerical precision internally.
- Paired diagnostics: signed flux change in W/m², positive flux reduction and supported reference-temperature equivalent, with matched uncertainty and reference identity. Mark unavailable or unsupported conversions explicitly.
- Sample and support: unique valid cells, valid footprint area, block counts, canopy quantiles, within-block and residualized canopy information, maximum/top-five information shares and effective information blocks.
- Conditions: p95 sensor view angle, geometry coverage, azimuth completeness, available acquisition-linked air temperature, VPD and recent rainfall. VPD remains descriptive. Mark missing, inherited and newly retrieved records separately.

Calculate footprint area from retained native ground footprints in the analysis coordinate system, reconciling tile ownership and boundary exclusions. Do not infer usable city coverage from a scene bounding box. Reuse existing spatial uncertainty results at 1, 2, 4 and 8 km with an explicit method column.

Make separate Phoenix and Atlanta plots of cooling against apparent solar time, with date labels and intervals. Show all original passes. Use 1 km intervals as the inherited baseline and a separate panel or clear overlay for 8 km; include the other scales in the table or appendix. Start with descriptive points, avoiding a new fitted time curve at this step.

**Completion evidence:** eleven Phoenix and five Atlanta original rows; no other-year rows; every plotted point resolves to a frozen run; unit/sign reconciliation; exact agreement with released fields; missing-input ledger; visual inspection of both plots.

### Step 3 Review spatial comparisons and paired scales

**Internal computations/support review completed 4 October 2026; effect-based review deferred.** The original/common paired intervals that were previously missing now exist under new shared physical-group draws at 1km and 8km. New values/figures remain sealed per the user's reply. Public footprint, seven-variable distributions, reference support, sparse-control rank audit and precision are available in the packet above. All 48 failed resamples remain reported; no replacement threshold, control removal or draw rescue was introduced. Sealed effect-figure visual review remains unperformed, and no robustness or agreement verdict follows from computation.

For every Phoenix pass, show original and all-eleven common-cell cooling and the absolute change. Include retained-cell fraction. Map the shared footprint and compare retained versus excluded cells' canopy, context distributions and spatial coverage. Treat this as a change in represented population, even when estimates are similar.

For the six added Phoenix passes, show four shifted-minus-unshifted changes on identical within-pass support. Existing paired difference intervals can be reused after validating labels, order, draw counts and the draw-generation procedure. Keep shifts on available support in another panel because they combine registration and composition changes. Check the original five-pass registration outputs separately; record any difference in their existing comparison methods rather than silently treating them as identical to the September 23 paired checks.

Common-cell point changes exist, but the archived comparison code does not establish paired intervals for them. First inspect available draw metadata without asserting covariance from equal seeds. If needed, reconstruct block sufficient statistics from the cached original native-cell frames. Draw multiplicities once on a shared universe of physical blocks and apply the same multiplicities to original and common-cell statistics, with zero contribution where a common sample lacks a block. Recover both archived point estimates before computing difference intervals. This is targeted joint resampling for eleven comparisons; it preserves the completed 65 fits and does not require rebuilding thermal rasters. If that construction cannot be validated, show the point change and separate estimate intervals, marking the difference interval unavailable.

Make a paired diagnostic plot of temperature cooling and temperature-equivalent flux cooling where supported. Preserve paired draws and the exact fourth-root conversion with the documented fixed temperature/emissivity reference. Report reference dependence, and investigate differences through background temperature, emissivity and sampling. Flux is derived from the same temperature retrievals and supplies a diagnostic rather than independent validation.

Retain existing residual diagnostics and information-concentration summaries. Larger resampling groups are uncertainty sensitivities; an 8 km grouping does not prove independence. Report absolute changes with uncertainty, avoiding relative percentages for estimates near zero.

**Completion evidence:** spatial-comparison figures, common-footprint map and distribution table, paired-scale figure, explicit uncertainty limitations and a short finding for each sensitivity. Do not issue a robustness pass/fail or agreement verdict without a justified criterion.

### Step 4 Review the packet before choosing the next analysis

Prepare a concise interpretation answering: what are the actual cooling estimates; which dates or neighbourhoods drive them; how do alignment and footprint changes alter the comparison; and which statements remain limited by canopy, weather or time support?

Record a review decision about the next bounded analysis. A substantial unexplained spatial change warrants diagnosing its mechanism or narrowing the represented population before interpreting time differences. Report any provisional effect range used for simulation calibration as an exploratory input informed by reviewed results, rather than a retrospective significance threshold.

**Stage 1 deliverable:** one results CSV and dictionary, two city time plots, spatial-comparison figures, a footprint map, a paired-scale diagnostic, missing-input ledger and short interpretation. Store newly disclosed content in a private local review directory under the sealed output root, with a separate disclosure manifest. Existing public result packages remain preserved.

## Stage 2 Try the targeted analyses

### Step 5 Audit canopy support and fit one quadratic sensitivity

This is the preferred first new model after Stage 1. The existing spline is useful context but does not answer the requested quadratic sensitivity with supported common endpoints.

Audit predictors before fitting: the original 2.85%–12.85% pair, nearby candidate pairs separated by ten percentage points, endpoint neighbourhood counts and densities, within-block coverage, and overlap in imperviousness, buildings, other controls and relevant month/time settings. Show counts at several documented endpoint neighbourhood widths rather than turning one arbitrary width into a new eligibility threshold. If support requires an inclusion rule, justify and freeze it prospectively before fitting that comparison. Report retained cells, blocks, area and information. Predictor support may change the reference population; keep that explicit.

When usable city overlap is absent, report supported city-specific finite contrasts and curves. Do not force a city ranking or choose endpoints using the observed cooling results. The all-cell baseline stays identifiable as the baseline; any restricted-support fit is a labelled sensitivity.

Fit the same paired native cells, unit weights, block intercepts and controls with raw canopy `f` and raw canopy squared `f²`. Compute `f²` before centring, then centre both terms within block. Protect both canopy basis terms in rank checks: the current fitter treats additional predictors as context candidates, so silently dropping the quadratic term would defeat this sensitivity. Preserve the existing defensible control/rank rule and report non-estimability instead of deleting a confounder to rescue the curve.

For each supported pair, calculate positive cooling as:

`CE_T(f0,f1) = -[beta1 * (f1-f0) + beta2 * (f1²-f0²)]`, with `f1=f0+0.10`.

Update every canopy basis term at both prediction endpoints, retain original training centres and reference weights, and repeat the complete contrast in each paired bootstrap draw. The existing generic endpoint predictor changes only the raw canopy column and must not be reused unchanged for this model. Compute the paired flux difference, average predictions before inversion, and use the exact fixed-reference conversion in each draw.

Proposed execution settings: sixteen paired quadratic fits; 1,000 whole-1km-block draws per pass with a recorded seed; 8 km grouping as a spatial sensitivity using the same point-estimation design. Freeze these settings before execution. Keep full arrays sealed and release only the authorized finite-contrast and curve artifacts. Do not select among curves by significance.

**Completion evidence:** linear versus quadratic finite-contrast table, curves with observed canopy support, retained-support table, point/interval changes and known-answer tests. For `T=305-5f+2f²`, the 10%–20% change must be -0.44 K and positive cooling +0.44 K. An additional fixture must demonstrate why squaring centred canopy gives a different model when block means differ.

### Step 6 Complete the inputs for the Phoenix window sensitivity

Keep all eleven Phoenix dates in the descriptive display. Use the following frozen five-date sensitivity; other pilot dates receive zero weight only for this comparison.

| Month | Morning date and arm weight | Afternoon date and arm weight |
| --- | --- | --- |
| June | 26 June: 0.50 | 11 June: 0.50 |
| August | 6 August: 0.25; 23 August: 0.25 | 11 August: 0.50 |

Each arm sums to one. Define:

`D_window = 0.50*C_Jun11 + 0.50*C_Aug11 - 0.50*C_Jun26 - 0.25*C_Aug06 - 0.25*C_Aug23`.

Report June's `C_Jun11-C_Jun26` and August's `C_Aug11-(C_Aug06+C_Aug23)/2` separately. Positive values mean stronger cooling on the sampled afternoon dates. These compare 09:30–11:30 with 15:00–18:00 apparent solar time. Keep the exact 10:30-versus-16:00 target as a distinct question requiring its own supported model.

Inventory cached acquisition-linked weather first. Complete missing air-temperature and available antecedent rainfall descriptors through the documented products with exact acquisition matching, QA and provenance. Preserve missing records if acquisition fails. Do not claim comparable weather from unlinked city averages or inherited VPD alone. Sensor view angle is a retrieval condition; solar geometry belongs to the primary total observation-time interpretation. Report support for both explicitly.

Check Atlanta's actual month/time coverage independently. Its five-pass count does not automatically justify importing Phoenix's matched-month weights or pooling the cities. Any supported Atlanta comparison needs its own frozen definition.

### Step 7 Calibrate uncertainty before reporting a general time interval

Separate two questions: uncertainty in the weighted comparison of these observed dates, and uncertainty about differences on other summer dates.

For the fixed-date comparison, resample recurring geography by stable physical block/group identity across passes and retain temperature/flux covariance. Use one draw plan across the participating dates, accounting for structural absence of blocks in some footprints. Validate that alignment of physical groups survives ordering and missing-group changes. This propagates spatial estimation uncertainty while holding dates and arm weights fixed.

For broader temporal inference, simulate the actual eleven-Phoenix/five-Atlanta design, actual times/months, unequal spatial SEs and missing windows. Include a zero-effect case, a clearly labelled provisional effect grid, plausible between-day variation and cross-pass spatial covariance sensitivities. Compare the existing day-cluster benchmark with a justified construction that separates pass-estimation error and between-day variation. A noisy pass estimate must not receive a second independent copy of its Stage 1 error without a justified model.

Proposed calibration: a small development run followed by 2,000 simulated datasets per frozen scenario, recording Monte Carlo error. At nominal 95% coverage, 2,000 independent simulations imply about 0.5 percentage points of Monte Carlo SE. Report empirical coverage, interval width, bias, failed fits, loss of arm/support and independent date counts. Use independent simulation streams for method development and final assessment; do not tune a method to the observed contrast sign. Freeze exact seeds and resampling counts before the production calibration.

June has one date per arm and August has one afternoon date. Within-month date variability therefore cannot be estimated reliably from these five endpoints. If the calibrated method cannot support a general summer interval, report the window point estimate and fixed-date spatial interval with that limitation. Pixel counts do not supply additional temporal replication.

Make leave-one-date-out displays. Freeze a rule that renormalizes weights only within an existing month/arm and preserves half-month arm weights. If deletion empties a month/arm, label that comparison unsupported rather than redefining the target. Do not describe unsupported deletions as successful validation folds.

**Completion evidence:** monthly and combined exploratory window results, weather/geometry table, influence plot, fixed-date spatial uncertainty and calibration report. A broader between-day interval appears only if the assessment justifies its interpretation. No equivalence or scale-agreement claim follows from overlapping intervals.

## Order of work and completion criteria

| Work package | Depends on | Main work type | Ready for review when |
| --- | --- | --- | --- |
| Scope and packet | Source reconciliation and bounded execution/access record | Reuse and table/figure assembly | Sixteen baseline rows, provenance, interval labels and missing inputs validated |
| Spatial interpretation | Packet and authorized comparison access | Existing comparisons; targeted joint resampling if needed | Population changes and uncertainty of differences are explicit |
| Quadratic sensitivity | Spatial review and predictor-only support freeze | Sixteen new paired fits and spatial draws | Correct basis/predictions, supported finite contrasts and QA complete |
| Phoenix window sensitivity | Reviewed results, linked weather and frozen weights | Five-date contrast and calibrated uncertainty | Monthly results, influence and date-versus-space limits are explicit |
| Acquisition proposal | Findings from the preceding packages | Metadata/quality design audit | Each proposed observation addresses a documented gap |

Recommended first attempt: complete Stage 1, then the supported quadratic sensitivity. Prepare the weather and simulation inputs alongside that sensitivity where dependencies permit. Defer broader temporal claims until calibration is complete. This order gives an interpretable review packet before the more uncertain day-inference work.

Runtime estimates should follow inventory of cached frames and one measured fit; avoid a completion-date promise before benchmarking. Most Stage 1 estimates and intervals are already available. Additional compute is concentrated in joint difference resampling, quadratic draws and time-calibration simulations.

## Tests and artifact handling

All new analytical logic needs network-free known-answer fixtures before empirical execution. Required checks cover sample/variant joins, signs and units, physical ownership, exact endpoint regeneration, block centring, rank failure, predictor support, matched outcome rows, fixed-reference transformation, paired spatial covariance, temporal double-counting, weight sums, loss of support and sealed serialization. A reordered or partially missing block list must not break physical draw alignment. Public serialization must exclude unapproved coefficients, intervals, predictions and draws.

Reuse relevant pooled, nonlinear and robustness tests; extend them only for the new logic. Run required checks after changes. Documentation checks cover source facts, cross-document consistency, YAML parsing if amended, checksums and rendered readability. Inspect all scientific figure exports, axes, interval labels, dates and legend meanings visually. Synthetic calibration output belongs in a clearly labelled synthetic location, separate from empirical review outputs.

Proposed new code lives in `src/v6_2_advance/` with focused tests in `tests/v6_2_advance/`. Keep calculation functions separate from output/release code. New empirical model arrays stay under the sealed output root with restricted file permissions; newly authorized review artifacts get a separate manifest and release scope. Never overwrite original frozen packages. Every new row and figure links to an input/run identity and checksum manifest.

## Decisions after the targeted review

Before selecting more observations, specify the represented population, comparison windows, practically meaningful difference and acceptable uncertainty. A later margin must disclose prior effect access. A numerical scale-equivalence ruling still needs Reza's tolerance and recorded review; descriptive paired differences can be reported within the authorized scope without such a verdict.

Audit further 2023 opportunities in both cities first, prioritizing repeated dates in the same month and arm with comparable sensor geometry, clear footprints and canopy/context support. The Phoenix July/September morning gap is already established and cannot be filled by relaxed screening. If 2023 cannot support the intended question, present a separate proposal for other complete years, with city-year-month comparisons and context/product consistency. Additional years do not repair missing 2023 combinations.

Consider one additional city only if it supplies specific replication unavailable in Phoenix/Atlanta. Los Angeles currently has no completed paired model. New years, thermal downloads or city rollout need a separately recorded scope decision. The acquisition plan should name the gap each date fills and reserve an untouched supported confirmation subset where feasible.

The review can lead to a focused observational time result, a reproducible sampling-sensitivity result, or a conclusion that the comparison remains unsupported. Draft methods and captions as the work proceeds; decide the headline after seeing the validated results. Sending the packet to Prof. Alizadeh remains a separate user-authorized action.

## Sources

- [User pasted implementation proposal](</Users/jmlee/.codex/attachments/5296db61-0af3-4c11-8faa-c4eb1e76228a/Pasted text.txt>).
- [New Urban Tree Cooling Next Steps document](/Users/jmlee/.codex/attachments/04ca87e3-4e40-4e71-8b50-d8dc90f128b2/Urban_Tree_Cooling_Next_Steps.docx), treated as source guidance.
- [Repository operating rules](/Users/jmlee/Documents/TreeProject/AGENTS.md), [active protocol](/Users/jmlee/Documents/TreeProject/docs/v2/v6_2/protocol_v6_2.yml), [pilot plan](/Users/jmlee/Documents/TreeProject/docs/v2/v6_2/pilot_plan_v6_2.md), [decision log](/Users/jmlee/Documents/TreeProject/docs/v2/v6_2/decision_log_v6_2.md) and [2023 sample scope](/Users/jmlee/Documents/TreeProject/docs/v2/v6_2/phoenix_2023_sample_scope.md).
- [Released sixteen-pass table](/Users/jmlee/Documents/TreeProject/outputs/v6_2/scientific/exploratory_review_20260921/pass_gradients_exploratory.csv), [robustness report](/Users/jmlee/Documents/TreeProject/deliverables/Phoenix_Robustness_v6_2_20260923/README.md) and [nonlinear report](/Users/jmlee/Documents/TreeProject/deliverables/Nonlinear_Canopy_Association_v6_2_20260930/README.md).
- Inspected implementation: [pooled estimator](/Users/jmlee/Documents/TreeProject/src/urban_cooling_v2/pooled_city_pass.py), [robustness runner](/Users/jmlee/Documents/TreeProject/src/v6_2_advance/run_robustness_completion.py), [registration difference calculation](/Users/jmlee/Documents/TreeProject/src/v6_2_advance/finish_robustness_comparisons.py), [day-resampling benchmark](/Users/jmlee/Documents/TreeProject/src/v6_2_advance/time_resampling.py) and [benchmark tests](/Users/jmlee/Documents/TreeProject/tests/v6_2_advance/test_time_resampling.py).

The companion checksum manifest records the plan and source snapshots used at preparation. This plan is proposed work and does not report new scientific findings, coefficient access or advisor approval.
