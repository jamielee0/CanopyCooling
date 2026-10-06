# Urban tree canopy cooling pilot plan v6.2

Updated 19 September 2026. Current meeting and follow-up amendment.

## Purpose and current status

We will test whether a pooled city-pass estimator can measure canopy-associated surface cooling and whether its observation-time pattern survives a change from temperature to emitted-energy space. This amendment stays within v6.2. It replaces the earlier block-pass optical-condition design. No pilot result is created by this documentation update, and full-city scaling remains paused until the pilot is reviewed.

The later follow-up email controls the paired-space tests, two time interpretations and scaling pause. The written Next Steps document controls the exact Stage 1 formula and the two-city pilot. The transcript supplies the catalogue, overlap, power and research-focus clarifications. Where the transcript briefly says one slope per block-pass, the explicit written formula and repeated city-pass explanation control.

## The pooled estimator

Fit a separate model for each city and overpass, using native ECOSTRESS cells pooled across its eligible 1 km blocks. Block effects are intercepts. Each city-pass has one shared canopy slope; do not fit a block-by-canopy interaction and do not average all cell temperatures into one observation per block.

LST_K ~ 0 + C(block) + canopy_c + context_covariates_c

M_W_m2 ~ 0 + C(block) + canopy_c + context_covariates_c

Center canopy and context variables within block and pass. Retain impervious, low-vegetation, bare, building, elevation and water-distance context terms and the existing quality controls. Handle constant or rank-deficient terms using a rule frozen before fitting. Albedo and incoming/net radiation remain secondary radiative sensitivities.

Use the same cells, covariates, weights and resampling draws in both models. Compute M = epsilon_WB × sigma × T_K^4, with sigma = 5.670374419 × 10^-8 W m^-2 K^-4 and the matching ECOSTRESS wideband emissivity layer. Verify product, layer, scale, fill values and QA; do not substitute a spectral emissivity band. M is broadband emitted flux in W/m², termed emitted-radiance space in the advisor email.

Report signed changes delta_T = 0.10 beta_T and delta_M = 0.10 beta_M per 10 percentage points of canopy. If using a positive-cooling convention, CE_T = -delta_T and CE_M = -delta_M. Keep the convention explicit in every table. These are mixed-pixel conditional associations, not temperatures of trees.

## Canopy support and pilot selection

Remove the 0.20 per-block canopy-span floor. The later 0.10 per-block sensitivity is historical evidence, not a replacement inclusion rule. A narrow-span block may contribute to a pooled slope. Between-block differences in mean canopy cannot supply the missing within-block identifying variation.

For each city-pass calculate Sxx = sum_b sum_i w_i (f_i - mean_b(f))², its normalized variance Sxx/sum(w), and Bvar, the number of blocks with positive within-block variation above a documented numerical tolerance. Also report canopy information remaining after adjustment for the context variables and each block’s share of that information.

Set minimum Sxx and Bvar from their observed nonthermal distributions after deduplication and quality screening. Record values and reasoning before the model run. The thresholds remain pending until that nonthermal audit is complete. Remove the old minimum of eight passes per block; use a simulation of the actual independent passes, time coverage and pilot precision to justify sample size.

Retain the five frozen Phoenix orbits 27963, 28024, 28706, 28828 and 28909. Select five equivalent passes in one higher-canopy city, Atlanta or Charlotte, using canopy heterogeneity first and clear-sky afternoon coverage second. Confirm a clearly wider within-block canopy distribution before downloading its thermal data. Record selection without using cooling outcomes. Los Angeles is a post-review expansion city, not the required high-canopy pilot.

Keep the frozen 2019–2025 main study period, annual Science TCC product, stable-cell multi-year median canopy amount and year-matched sensitivity. Freeze the selected city’s season and supported time windows before fitting. Check actual time coverage; five passes do not guarantee an estimable 10:30-to-afternoon comparison.

## Spatial and archive checks

Build one unique ground-cell dataset per city-pass. Deduplicate repeated scenes and tile revisions using acquisition identity, grid transform and cell location. At MGRS or projection boundaries compare ground footprints and use a deterministic QA/metadata priority or exclude ambiguous overlap. Do not count the same ground area twice. Record raw and unique cell counts, overlap area, rejected duplicates and unusually dense blocks.

Keep LST on native ECOSTRESS cells. Aggregate canopy and continuous context by area-weighted overlap and categorical land cover by area fractions. Verify the actual Rasterio operations with known cases; the library name alone does not establish correct resampling.

Check complete ECOSTRESS mission catalogue metadata, all pagination and collection identities, then apply the declared study years and filters. Reconcile granule, tile, orbit and city-pass counts. Catalogue completeness is not permission to process the full thermal archive.

The frozen Phoenix precision inputs may be Collection 2; the final-study product remains Collection 3. Preserve this distinction and verify matching wideband emissivity. Do not silently replace frozen passes or interpret a collection difference as a city effect. Missing emissivity or incompatible products leave the paired comparison incomplete.

## Precision review and sealed results

Resample whole spatial blocks and refit both models together. Keep all cells within each sampled block and assign fresh block labels to repeat draws. Check larger spatial groups when residual dependence crosses 1 km boundaries. Planning defaults are 1,000 replicates and seed 20260919; these are analyst operational defaults to record before execution.

The open pilot table reports each city-pass, the pooled-slope standard error in K per 10 percentage points, Bvar, Sxx, normalized variance, convergence, leverage and the bootstrap width q97.5 - q2.5. Report the width alone, not its endpoints. Keep signed coefficients, CE values, raw bootstrap draws, prediction levels and coefficient plots sealed. Report corresponding M precision in W/m² as well.

Retain common-cell or frozen reweighting checks and ±1 native-cell registration shifts. Judge estimability and precision without any expected-sign requirement. The advisor’s approximate 0.1 K per 10 percentage points standard-error benchmark is recorded as a 0.10 operational target to freeze. Define how the five pass-specific standard errors determine city-level success before the run; report all passes and city summaries so the best pass cannot be chosen afterward.

If either city meets the frozen precision criterion, prepare the pilot for review. Phoenix failure with success in the higher-canopy city is a useful scope result. If both fail, report the numbers and stop dependent analysis. Precision success alone does not establish power for a time contrast or an equivalence claim.

The sequence is design freeze, paired model fitting with estimates sealed, precision ruling, recorded review release of the necessary coefficients, then the prespecified scale/time comparison. Full-city scaling still requires pilot review. The follow-up scale comparison cannot be completed while all point estimates remain sealed; these are successive stages, not contradictory reporting requirements.

## Standardized temperature equivalent

Freeze two raw canopy fractions f0 and f1 = f0 + 0.10 inside the observed common support of the compared cities and times. Freeze reference covariate rows, valid block labels and weights without selecting them on outcomes. Use equal city weights and equal pass weights within city for combined references; within each fitted city-pass retain valid block labels. If the pair or reference lacks support, report the contrast as not estimable.

For prediction, set raw canopy to f0 or f1 and subtract the original training block mean; keep training centers, other covariates and reference weights fixed. Average the two sets of emitted-energy predictions to obtain muM0 and muM1. Define dM = muM1 - muM0.

Before effect access, specify a reference temperature Tref, reference emissivity epsilon_ref and a sensitivity grid. This plan deliberately does not invent values absent from the advisor’s instructions. If choosing them from absolute observed temperatures, disclose that access and freeze the reference without viewing fitted slopes.

Define Mref = epsilon_ref × sigma × Tref^4. Reanchor the two predictions as A0 = Mref and A1 = Mref + dM. The standardized contrast is delta_T_equiv = [A1/(epsilon_ref × sigma)]^(1/4) - [A0/(epsilon_ref × sigma)]^(1/4), and CE_M_equiv = -delta_T_equiv. Both anchored predictions must be positive.

This is an explicitly reference-anchored transformation of a predicted energy difference. Average predictions first, then reanchor and back-transform; do not silently average individual fourth-root predictions. Repeat the procedure in every paired bootstrap draw with the reference fixed. Never divide beta_M by a universal temperature-to-radiance constant.

## Synthetic mixing check

Use the observed joint canopy, absolute temperature and emissivity distributions and the actual block/city/time structure from both pilot cities. Record access to absolute temperature distributions separately from access to sealed coefficients. The component temperatures and emissivities are simulation assumptions; mixed-pixel data do not identify them directly.

Within each scenario hold Delta = Tbackground - Ttree constant across cities and observation times. Use plausible background-temperature distributions anchored to observed LST, an equal-component-emissivity scenario matched to observed pixel emissivity, and sensitivity scenarios for component emissivity differences. Freeze a grid of contrasts, including a zero-contrast control, before simulation.

Mmix = (1 - f) epsilon_background sigma Tbackground^4 + f epsilon_tree sigma (Tbackground - Delta)^4. Define epsilon_mix = (1 - f) epsilon_background + f epsilon_tree and Tmix = [Mmix/(sigma epsilon_mix)]^(1/4).

Fit the same pooled models and standardized contrasts. Separate a transformation-only, no-noise scenario from spatial-error and emissivity sensitivities. Report artificial between-city and observation-time variation, bias against each scenario’s known benchmark, T-versus-M-equivalent discrepancies, uncertainty and reversal frequencies. A constant temperature contrast does not imply a constant radiative contrast.

Label every simulation SYNTHETIC_DATA and keep it under tests/fixtures/synthetic_demo, separate from empirical scientific outputs. Do not implement the eight-class subpixel unmixing method.

## Time patterns and the scale decision

The primary pattern is the total association with local solar observation time, including the associated change in solar geometry. Retain quality screening, but do not add solar-geometry or radiation controls to the only primary time model. Fit a separate secondary pattern standardized for geometry and season only where joint support permits it. Report a secondary pattern as not identifiable when geometry and time cannot be separated.

After reviewed unsealing, plot the pass-level cooling coefficient and uncertainty against local solar time before fitting any curve. Freeze the curve basis, covariates and weighting before release; the plot must not be used to select a more favorable model. A pass fixed effect is inappropriate with one outcome per city-pass because it would absorb the time pattern.

For each model space compare CE at 10:30 with CE at a prospectively selected, supported late-afternoon time or window; 17:00 in the meeting was an example, not an automatically accepted target. Define D_T = CE_T(late) - CE_T(10:30) and D_M = CE_M_equiv(late) - CE_M_equiv(10:30). Propagate paired uncertainty and report city-specific results before any pooled summary.

Freeze a numerical tolerance tau in K per 10 percentage points before effect access. It is separate from the 0.10 K precision benchmark. Agreement in direction with |D_T - D_M| < tau allows LST to remain the headline metric. Material discrepancy or reversal makes emitted energy the primary physical analysis and requires describing LST as scale-dependent. Report uncertainty and near-zero cases; inadequate support or precision is not evidence of agreement.

Different observation times often come from different days. Describe the result as an observational time pattern, not a same-day trajectory or a causal effect of changing the clock. Positive D means more cooling later and a morning measurement that understates later cooling; negative D means less cooling later. A near-zero estimate supports similarity only with adequate equivalence precision.

## VPD canopy validation and deferred work

VPD is descriptive only and excluded from primary and confirmatory claims and interactions. Keep the global study in the literature review as an observational climatic association. Our own collinearity and support diagnostics justify the exclusion. Cite the actual weather source and audit when reporting Phoenix’s roughly 0.95 temperature correlation and Los Angeles’s roughly 0.30 kPa common-support width; the latter is not the entire observed VPD range. The transcript recalls ERA5, while the inherited protocol uses HRRR with ERA5-Land sensitivity; verify the manifest before labeling data.

Make a brief check for canopy products of 1 m or finer in Phoenix and the selected pilot city, documenting date, coverage, licensing and methods. If suitable, aggregate to native ECOSTRESS cells and compare with date-matched annual 30 m canopy fractions. Keep the primary multi-city Science TCC product and move on if a suitable validation product is unavailable.

The prior HLS/SWIR tree-versus-background joint-sign hypothesis is deferred. Its measurement and timing records remain historical resources and do not gate the current time-pattern pilot. An HLS drought-focused pivot requires a future explicit decision. Maintain a short literature note explaining relevant products, resolutions, cities, estimators, confounding and the project’s specific gap; do not claim novelty solely from the meeting discussion.

## After review and remaining freeze items

Only after pilot review and a recorded expansion decision, process the available Phoenix and Los Angeles passes, build the pass-level coefficient/standard-error table and inspect the time plot. Then consider eight to twelve further cities selected on within-block canopy heterogeneity and clear-sky afternoon coverage before thermal downloads. The transcript’s twenty-to-twenty-five-city discussion is a possible screening pool, not current authorization.

The remaining pre-run entries are the second city and its pass manifest/season, Sxx and contributing-block minima, the city-level precision aggregation rule, supported canopy pair and reference weights, Tref and epsilon_ref, late-afternoon target, scale tolerance and zero-direction convention, simulation contrast scenarios, and the time-model/power specification. Complete these from nonthermal evidence or declared physical choices before effect access. No value is presented as already frozen when it was not supplied.

Keep short decision-log entries, source/output checksums, output isolation, prior-access disclosure and sealed estimates. New conformance memoranda, formal decision identifiers and per-deliverable packages are set aside. Original source files and earlier signed/checksummed result packages remain preserved as historical records. Existing analysis code still needs implementation and verification against this amended plan.
