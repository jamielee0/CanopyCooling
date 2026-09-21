> Review snapshot: the opening 2023-only scope controls historical sections. See [current progress and limitations](../01_Progress_and_decisions.md) for the provisional temporal bootstrap and outstanding checks. Original workspace paths below are provenance, not commands to run from this export.

# Urban tree canopy cooling pilot plan v6.2

## Current pilot scope — 2023 only

The user clarified that the pilot under discussion is **2023**. The assistant's previous rebalancing step expanded the year range without making that scope change explicit. That expansion is not the main pilot. **The current pilot remains eleven Phoenix passes and five Atlanta passes, all in 2023.** The seven processed Phoenix passes from 2019, 2024 and 2025 are preserved as a separate exploratory extension and receive no weight in the main 2023 pilot. Eighteen Phoenix passes exist on disk, but only eleven belong to the current pilot.

Read `docs/v2/v6_2/phoenix_2023_sample_scope.md` for the controlling sample description. Retain all eleven 2023 Phoenix passes for descriptive coverage. The optional balanced morning/afternoon sampling sensitivity uses five of them in June and August: each month gets half of each arm's weight, divided among that month's available passes. Three other June/August passes describe middle times; the July and September passes remain descriptive because they have no 2023 morning counterparts in 09:30–11:30 solar time. No file or result was deleted. This weighting is not a newly computed time contrast.

The complete 2023 catalogue has no July or September acquisition in that morning window, before quality screening. More observations from 2019/2024/2025 do not repair the missing 2023 combinations. A fully balanced June–September 2023 pattern therefore remains unsupported. Keep the exact 10:30-versus-late-afternoon research target distinct from a window-mean comparison; preserve the total time interpretation including associated solar geometry, with secondary geometry/season standardization only where supported.

The prior eighteen-pass/twelve-endpoint rebalancing package is a preserved exploratory multiyear result, not the controlling pilot specification. Its seven additional paired fits completed, but their point estimates remain sealed. Earlier authorized disclosures remain recorded. No new empirical time regression, scale-agreement ruling or professor approval is implied. Prof. Alizadeh's tolerance, calibrated time inference, registration/common-cell checks and full-study season/product choices remain unresolved. The nineteen-city nonthermal screen and previous eleven-pass 2023 package remain available. Version stays 6.2.

## Original pilot design and execution record

Original pilot amendment: 19 September 2026. Current bounded extension: 21 September 2026.

## Original pilot purpose and status (historical snapshot)

The pooled estimator, paired emitted-energy model, spatial checks and scale-diagnostic workflow are implemented. The limited Phoenix–Atlanta pilot is authorized and its empirical outputs remain sealed. The meeting package records completed run status and precision. Full-city scaling remains paused until review.

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

Report each pass’s total within-block canopy information, contributing blocks and concentration of information. No arbitrary replacement canopy-span, Sxx, block-count or four-of-five exclusion gate is imposed. Numerical rank and nonzero information determine whether a model can be estimated. The support distributions inform review and any later prospectively justified rule.

The pilot retains Phoenix orbits 27963, 28024, 28706, 28828 and 28909 and selects Atlanta orbits 27835, 27896, 27916, 28145 and 28598. A seeded 300-block nonthermal Science TCC screen found within-block variance of 0.00159 in Phoenix, 0.08301 in Atlanta and 0.07189 in Charlotte. Atlanta also has verified afternoon acquisitions. Its five passes were frozen before thermal download from the existing geometry-verified 2023 June–September inventory.

Keep the frozen 2019–2025 main study period, annual Science TCC product, stable-cell multi-year median canopy amount and year-matched sensitivity. Freeze the selected city’s season and supported time windows before fitting. Check actual time coverage; five passes do not guarantee an estimable 10:30-to-afternoon comparison.

## Spatial and archive checks

Build one unique ground-cell dataset per city-pass. Deduplicate repeated scenes and tile revisions using acquisition identity, grid transform and cell location. At MGRS or projection boundaries compare ground footprints and use a deterministic QA/metadata priority or exclude ambiguous overlap. Do not count the same ground area twice. Record raw and unique cell counts, overlap area, rejected duplicates and unusually dense blocks.

Keep LST on native ECOSTRESS cells. Aggregate canopy and continuous context by area-weighted overlap and categorical land cover by area fractions. Verify the actual Rasterio operations with known cases; the library name alone does not establish correct resampling.

Check complete ECOSTRESS mission catalogue metadata, all pagination and collection identities, then apply the declared study years and filters. Reconcile granule, tile, orbit and city-pass counts. Catalogue completeness is not permission to process the full thermal archive.

Both pilot cities use matching Collection 2 products. Collection 3 historical coverage is incomplete and requires review before expansion. Preserve this distinction and verify matching wideband emissivity. Do not silently replace frozen passes or interpret a collection difference as a city effect. Missing emissivity or incompatible products leave the paired comparison incomplete.

## Precision review and sealed results

Resample whole spatial blocks and refit both models together. Keep all cells within each sampled block and assign fresh block labels to repeat draws. Check larger spatial groups when residual dependence crosses 1 km boundaries. Planning defaults are 1,000 replicates and seed 20260919; these are analyst operational defaults to record before execution.

The open pilot table reports each city-pass, the pooled-slope standard error in K per 10 percentage points, Bvar, Sxx, normalized variance, convergence, leverage and the bootstrap width q97.5 - q2.5. Report the width alone, not its endpoints. Keep signed coefficients, CE values, raw bootstrap draws, prediction levels and coefficient plots sealed. Report corresponding M precision in W/m² as well.

Report all five passes and each city’s median, range and number at or below the approximate 0.10 K per 10 percentage points SE benchmark. This is a descriptive feasibility comparison; no additional four-of-five city gate is imposed. Use 1,000 paired whole-block bootstrap draws, seed 20260919, four cardinal one-cell registration shifts, 2 km spatial groups and the exact common-cell subset.

Review feasibility using all reported standard errors and support diagnostics. Adequate precision in either city is useful. If neither city has usable precision, report the numbers and stop dependent interpretation. Precision alone does not establish time-contrast power or equivalence.

Coefficient sealing remains in force for precision review. Prof. Alizadeh’s numerical scale-agreement tolerance remains pending. Compute and store paired contrasts without displaying them; do not issue an agreement ruling until the tolerance is prospectively recorded and coefficient release is authorized. Treat an exactly zero contrast as direction unresolved. The full-study power design and Collection 3 historical coverage decision remain for the post-pilot review.

## Standardized temperature equivalent

Freeze two raw canopy fractions f0 and f1 = f0 + 0.10 inside the observed common support of the compared cities and times. Freeze reference covariate rows, valid block labels and weights without selecting them on outcomes. Use equal city weights and equal pass weights within city for combined references; within each fitted city-pass retain valid block labels. If the pair or reference lacks support, report the contrast as not estimable.

For prediction, set raw canopy to f0 or f1 and subtract the original training block mean; keep training centers, other covariates and reference weights fixed. Average the two sets of emitted-energy predictions to obtain muM0 and muM1. Define dM = muM1 - muM0.

Select the shared canopy pair 0.10 apart by maximizing the minimum number of supporting reference blocks across passes, breaking ties toward the smaller lower endpoint. Keep every eligible block in slope fitting; only prediction reference rows require both endpoints. Freeze Tref and epsilon_ref as the equal-city average of equal-pass medians, with sensitivity offsets of ±10 K and ±0.01 emissivity. Record numerical values and reference row identities before computing sealed predictions.

Define Mref = epsilon_ref × sigma × Tref^4. Reanchor the two predictions as A0 = Mref and A1 = Mref + dM. The standardized contrast is delta_T_equiv = [A1/(epsilon_ref × sigma)]^(1/4) - [A0/(epsilon_ref × sigma)]^(1/4), and CE_M_equiv = -delta_T_equiv. Both anchored predictions must be positive.

This is an explicitly reference-anchored transformation of a predicted energy difference. Average predictions first, then reanchor and back-transform; do not silently average individual fourth-root predictions. Repeat the procedure in every paired bootstrap draw with the reference fixed. Never divide beta_M by a universal temperature-to-radiance constant.

## Synthetic mixing check

Use the observed joint canopy, absolute temperature and emissivity distributions and the actual block/city/time structure from both pilot cities. Record access to absolute temperature distributions separately from access to sealed coefficients. The component temperatures and emissivities are simulation assumptions; mixed-pixel data do not identify them directly.

Run SYNTHETIC_DATA scenarios with constant component contrasts of 0, 2, 5 and 10 K on 200 reproducibly sampled whole blocks per pass. Use observed block temperature and emissivity medians for the transformation-only baseline. Add spatial error, unequal emissivity, narrower canopy support, ±10 K background shifts and within-block permutations of observed temperatures. Subtract the matched zero-contrast control when isolating transformation artifacts. These assumed component temperatures are not recovered tree temperatures.

Mmix = (1 - f) epsilon_background sigma Tbackground^4 + f epsilon_tree sigma (Tbackground - Delta)^4. Define epsilon_mix = (1 - f) epsilon_background + f epsilon_tree and Tmix = [Mmix/(sigma epsilon_mix)]^(1/4).

Fit the same pooled models and standardized contrasts. Separate a transformation-only, no-noise scenario from spatial-error and emissivity sensitivities. Report artificial between-city and observation-time variation, bias against each scenario’s known benchmark, T-versus-M-equivalent discrepancies, uncertainty and reversal frequencies. A constant temperature contrast does not imply a constant radiative contrast.

Label every simulation SYNTHETIC_DATA and keep it under tests/fixtures/synthetic_demo, separate from empirical scientific outputs. Do not implement the eight-class subpixel unmixing method.

## Time patterns and the scale decision

The primary pattern is the total association with local solar observation time, including the associated change in solar geometry. Retain quality screening, but do not add solar-geometry or radiation controls to the only primary time model. Fit a separate secondary pattern standardized for geometry and season only where joint support permits it. Report a secondary pattern as not identifiable when geometry and time cannot be separated.

Use a city-specific linear total-time model and compare 10:30 with 16:00 apparent local solar time, including the equation-of-time correction. Average the two city contrasts equally only when both are supported. A separate model adds solar elevation and day of year only where their joint support overlaps. Carry paired Stage 1 uncertainty through independent-day resampling. Five passes per city provide an exploratory feasibility comparison, not a population-wide or same-day diurnal claim. After reviewed unsealing, inspect the pass-level plot with its uncertainty. Do not select the time model from the resulting signs.

For each model space compare CE at 10:30 with CE at a prospectively selected, supported late-afternoon time or window; 17:00 in the meeting was an example, not an automatically accepted target. Define D_T = CE_T(late) - CE_T(10:30) and D_M = CE_M_equiv(late) - CE_M_equiv(10:30). Propagate paired uncertainty and report city-specific results before any pooled summary.

Coefficient sealing remains in force for precision review. Prof. Alizadeh’s numerical scale-agreement tolerance remains pending. Compute and store paired contrasts without displaying them; do not issue an agreement ruling until the tolerance is prospectively recorded and coefficient release is authorized. Treat an exactly zero contrast as direction unresolved. The full-study power design and Collection 3 historical coverage decision remain for the post-pilot review. Agreement requires the same nonzero direction and a discrepancy strictly below the frozen tolerance. Material disagreement makes emitted energy the primary physical analysis and LST scale-dependent.

Different observation times often come from different days. Describe the result as an observational time pattern, not a same-day trajectory or a causal effect of changing the clock. Positive D means more cooling later and a morning measurement that understates later cooling; negative D means less cooling later. A near-zero estimate supports similarity only with adequate equivalence precision.

## VPD canopy validation and deferred work

VPD is descriptive only and excluded from primary and confirmatory claims and interactions. Keep the global study in the literature review as an observational climatic association. Our own collinearity and support diagnostics justify the exclusion. Cite the actual weather source and audit when reporting Phoenix’s roughly 0.95 temperature correlation and Los Angeles’s roughly 0.30 kPa common-support width; the latter is not the entire observed VPD range. The transcript recalls ERA5, while the inherited protocol uses HRRR with ERA5-Land sensitivity; verify the manifest before labeling data.

Make a brief check for canopy products of 1 m or finer in Phoenix and the selected pilot city, documenting date, coverage, licensing and methods. If suitable, aggregate to native ECOSTRESS cells and compare with date-matched annual 30 m canopy fractions. Keep the primary multi-city Science TCC product and move on if a suitable validation product is unavailable.

The prior HLS/SWIR tree-versus-background joint-sign hypothesis is deferred. Its measurement and timing records remain historical resources and do not gate the current time-pattern pilot. An HLS drought-focused pivot requires a future explicit decision. Maintain a short literature note explaining relevant products, resolutions, cities, estimators, confounding and the project’s specific gap; do not claim novelty solely from the meeting discussion.

## After review and remaining decisions

Only after pilot review and a recorded expansion decision, process the available Phoenix and Los Angeles passes, build the pass-level coefficient/standard-error table and inspect the time plot. Then consider eight to twelve further cities selected on within-block canopy heterogeneity and clear-sky afternoon coverage before thermal downloads. The transcript’s twenty-to-twenty-five-city discussion is a possible screening pool, not current authorization.

Coefficient sealing remains in force for precision review. Prof. Alizadeh’s numerical scale-agreement tolerance remains pending. Compute and store paired contrasts without displaying them; do not issue an agreement ruling until the tolerance is prospectively recorded and coefficient release is authorized. Treat an exactly zero contrast as direction unresolved. The full-study power design and Collection 3 historical coverage decision remain for the post-pilot review.

Keep short decision-log entries, provenance checksums, isolated synthetic outputs and prior-access disclosures. The active implementation is run_v6_2_pooled_pilot.py with pooled_city_pass.py, pilot_native.py and pilot_scale.py. Historical runners and original source documents remain preserved.
## Executed pilot and review package

The pooled estimator, paired emitted-energy model, spatial checks and scale-diagnostic workflow are implemented. The limited Phoenix–Atlanta pilot is authorized and its empirical outputs remain sealed. The meeting package records completed run status and precision. Full-city scaling remains paused until review. Report all five passes and each city’s median, range and number at or below the approximate 0.10 K per 10 percentage points SE benchmark. This is a descriptive feasibility comparison; no additional four-of-five city gate is imposed. Use 1,000 paired whole-block bootstrap draws, seed 20260919, four cardinal one-cell registration shifts, 2 km spatial groups and the exact common-cell subset.

Use a city-specific linear total-time model and compare 10:30 with 16:00 apparent local solar time, including the equation-of-time correction. Average the two city contrasts equally only when both are supported. A separate model adds solar elevation and day of year only where their joint support overlaps. Carry paired Stage 1 uncertainty through independent-day resampling. Five passes per city provide an exploratory feasibility comparison, not a population-wide or same-day diurnal claim.

Select the shared canopy pair 0.10 apart by maximizing the minimum number of supporting reference blocks across passes, breaking ties toward the smaller lower endpoint. Keep every eligible block in slope fitting; only prediction reference rows require both endpoints. Freeze Tref and epsilon_ref as the equal-city average of equal-pass medians, with sensitivity offsets of ±10 K and ±0.01 emissivity. Record numerical values and reference row identities before computing sealed predictions.

Run SYNTHETIC_DATA scenarios with constant component contrasts of 0, 2, 5 and 10 K on 200 reproducibly sampled whole blocks per pass. Use observed block temperature and emissivity medians for the transformation-only baseline. Add spatial error, unequal emissivity, narrower canopy support, ±10 K background shifts and within-block permutations of observed temperatures. Subtract the matched zero-contrast control when isolating transformation artifacts. These assumed component temperatures are not recovered tree temperatures.

See deliverables/Pilot_Meeting_Package_v6_2_20260919/README.md for run status, precision tables, audits and the remaining decisions. The active protocol stays at version 6.2.
