# Canonical v2 requirements

**Source authority:** `StepByStep_Guide_Urban_Tree_Cooling.docx`  
**Purpose:** turn the guide into an executable, one-entry-per-ID specification without
silently discarding its scientific cautions. If this file and the guide disagree on scientific
meaning, stop and resolve the discrepancy in `DECISION_LOG.md` before running affected work.

## Normalization rules

The source document contains repeated or malformed rows. This specification makes only the
following editorial repairs:

- repeated `F1.1`–`F1.4`, `T1.2`, `F4.4`, `F4.5`, `T4.1`, `T4.3`, `F12.4`, and paper
  `Figure 2` rows are represented once;
- the duplicated `T1.1` label is collapsed and attached to the description that immediately
  follows it;
- the paper's generic `Figure 1`–`Figure 6` labels are assigned canonical IDs
  `F14.1`–`F14.6`, and its unnumbered public package is `P14.1`;
- wording is compressed in the registry below, but no substantive requirement is relaxed.

No duplicate receives a new deliverable number. A deliverable is complete only when its file,
provenance, and required content exist; an empty placeholder does not count.

## Global scientific invariants

1. Keep one city and the entire 2026 season unopened until the method is frozen. The city is
   chosen after the data-quality audit and before any thermal result is inspected.
2. Use **pass** as the effective sample size for weather effects. Pixel rows within a pass are
   clustered observations, not independent weather observations.
3. Say **time-of-day dependence**, not a same-day diurnal course. Different local times are
   generally sampled on different dates.
4. Call the 30/60-day precipitation-minus-reference-ET quantity **antecedent climatic water
   balance** or **antecedent climatic dryness**. It is not soil water, root-zone water,
   irrigation, or plant-available water.
5. Freeze domains, thresholds, bin-merging rules, collection version, and model choices before
   viewing the result each could influence. Record every choice in `DECISION_LOG.md`.
6. Use one reproducible domain rule for all cities. Municipal boundaries, hand-drawn extents,
   and mixed domain types are prohibited.
7. Use the native ECOSTRESS tile geometry for the thermal chain. Never resample the temperature
   field; aggregate fractions by area and categorical values by a declared categorical rule.
8. Never mix collection versions in the primary chain. Layer names, scale factors, fill values,
   and quality definitions come from the frozen collection metadata, not memory.
9. Restrict claims to observed common support. Unsupported regions must be masked and must not
   drive thresholds or interaction claims.
10. Keep code, data provenance, decision history, tests, and generated artifacts reproducible
    without exposing credentials or secrets.

## Task boundary used for implementation

- **Task 0 — specification and guardrails:** preserve the legacy baseline, establish a separate
  v2 surface, normalize requirements, record decisions, and define gates.
- **Task 1 — feasibility gate:** implement and run Guide Steps 1–3. Task 1 is not complete from
  synthetic fixtures alone. It requires the real five-city weather audit, the real catalogue and
  cloud-survival audit, the definitive acquisition-time conditions figure, and simulations
  calibrated to those observed distributions.

## Step 1 — weather conditions screen

### Required inputs and transformations

- Resolve and freeze five Census Urban Areas (or one consistently applied equivalent) and their
  intersections with ECOSTRESS tiles. Store the source release, feature identifier, geometry,
  area, centroid, coordinate reference system, and checksum.
- Use Earth Engine dataset `IDAHO_EPSCOR/GRIDMET`, bands `pr` (mm), `eto` (mm), `vpd`
  (kPa), and `tmmx`, spatially averaged over each frozen domain for every 1 June–30 September
  day in 2018–2025. Retrieve at least the preceding 60 days for each summer so the first output
  day has a complete antecedent window; do not silently use a partial June window.
- Define demand from daily VPD and rank it within city across that city's summer days only.
- Compute `water_balance_30_mm` and `water_balance_60_mm` as the sum of `pr - eto` over the
  30 or 60 preceding days, ending the day before the focal day. Keep the physical balance and a
  clearly named percentile. If a high-valued **dryness** axis is used, derive it by reversing the
  ascending water-balance percentile; never change the sign implicitly.
- Define clear-sky likelihood from one declared early-afternoon reanalysis or MODIS cloud
  measure. Freeze the dataset, hour window, aggregation, and threshold before counting cells.
- For each city and both windows, assign demand and dryness to terciles and count all nine cells.
  The diagnostic corners are high-demand/wet-antecedent and low-demand/dry-antecedent.

### Required checks

| Check | Required evidence | Pass condition |
|---|---|---|
| Units | Per-city min/median/max for every gridMET band | `pr` and `eto` are mm; VPD is kPa; Phoenix summer VPD is plausibly about 2–6 kPa rather than hPa-scale values. |
| Physical balance | Full-summer Phoenix 30-day series | Strongly negative in June and rises at monsoon onset; opposite behaviour triggers a sign audit. |
| Percentiles | Histograms by city and variable | Approximately uniform on 0–1 within city; ties and the rank convention are documented. |
| Honest correlation | Spearman interval from whole-summer block bootstrap | Interval is reported; individual days are never the bootstrap unit. |
| Axis independence | Within-city permutation of the antecedent series and corner occupancy | Observed occupancy's position in the null distribution is reported. |
| Window sensitivity | 30-day versus 60-day corner counts | Same qualitative recommendation, or disagreement explicitly carried forward. |

### Step 1 decision rule

- **Proceed within cities:** reasonable clear-day corner support in at least three cities and
  demand–dryness correlation not extreme (guide heuristic: absolute value roughly below 0.8).
- **Adjust to cross-city comparison:** corners are thin within every city but cities occupy
  different parts of the plane; state the city-confounding limitation and consider a sixth city.
- **Stop the interaction:** corners are essentially empty everywhere and axes are nearly the
  same; retain the time-of-day study and report the sampling limitation.

This is a preliminary gate. It is superseded by Step 2's pass-date, acquisition-time result.

## Step 2 — satellite observation count

### Required inputs and transformations

- Search the frozen tiled ECOSTRESS surface-temperature collection with `earthaccess` for every
  domain and summer date in 2018–2025. A catalogue query must not download granules.
- Preserve granule identifier, acquisition UTC, orbit, tile, footprint, collection/concept ID,
  version, and source-query timestamp. Preserve tile records but deduplicate analytical passes
  so multiple covering tiles at one acquisition are counted once per city.
- At each domain centroid and acquisition UTC, use `pvlib` to calculate local solar time, solar
  zenith, solar azimuth, and solar elevation. Do not apply a civil-time-zone shift on top of the
  solar correction.
- Daytime is local solar time 10:00–18:00. Provisional daytime strata are 10–12, 12–14,
  14–16, and 16–18. Night is defined astronomically as solar elevation below civil twilight;
  record the numerical threshold. Any later stratum merge follows a preregistered minimum-count
  and common-support rule and is never chosen after viewing thermal results.
- Attach retrieval band mode, the published solar-array-obstruction flag, scene geolocation
  class (`best`, `good`, `suspect`, `poor`), and view geometry. Keep only best/good,
  unobstructed, near-nadir scenes for the usable-pass count; freeze the near-nadir threshold.
- Estimate cloud survival from one Phoenix month and one month in the most humid city, then
  compare each with an independently selected second month. Do not extrapolate an unstable
  fraction; expand the sample until the preregistered tolerance is met or report failure.
- Recompute Step 1 on usable pass dates with demand interpolated from the hourly primary weather
  product to exact acquisition time. This is the definitive feasibility result.

### Required checks

| Check | Required evidence | Pass condition |
|---|---|---|
| Solar time | Three known scenes plus a solar-elevation/time trace | Solar noon is within minutes of maximum elevation; no one-hour systematic shift. |
| Time coverage | Full-record pass histogram by local solar time | Broad, plausible precessing-orbit coverage rather than an unexplained spike. |
| Cloud representativeness | First versus independent second month per calibration city | Fractions agree within the frozen tolerance, or more months are sampled. |
| Band mode | Acquisition-date cross-tabulation | No pre-May-2019 reduced label; split/fix behaviour is consistent with 28 April 2023 and post-fix metadata. |
| Count identities | Daytime, year, stratum, and city totals | Exact agreement. |
| Pass deduplication | Unique acquisition audit by city | One city-pass is counted once regardless of tile count. |

### Step 2 gate

The Step 1 recommendation must be reissued using the definitive pass-date result. Observed
usable-pass totals, not catalogue granules or pixels, become the sample-size marker supplied to
Step 3. Failure to obtain stable cloud survival, trustworthy quality/obstruction metadata, or
hourly demand means Task 1 is incomplete rather than a pass.

## Step 3 — simulation and power

### Required design

- Sample from the actual Step 1/2 joint distributions of demand, antecedent dryness, local solar
  time, solar geometry, city, and their correlations.
- Reproduce pass clustering, multiple matched sets within pass, and many rows per matched set.
- Include at least: a known demand-by-dryness interaction at three or more effect sizes; a true
  zero interaction; and a smooth nonlinear response with no breakpoint.
- Fit the intended downstream models. Record interaction power and coefficient recovery,
  interaction Type I error, transition false-positive rate, spurious breakpoint locations, and
  interval coverage.
- Vary pass count; mark Step 2's usable count. Repeat with and without the time-of-day
  interaction to decide whether a three-way model is supportable.
- Compare pass-level block-bootstrap intervals with naive row-level intervals. The target effect
  is stated in kelvin and supported by literature: below reported tree-versus-built contrasts,
  but above instrument uncertainty.

### Required checks

| Check | Required evidence | Pass condition |
|---|---|---|
| Simulation correctness | Very-large-pass run with known interaction | Known coefficient is recovered within a declared small tolerance. |
| Nominal Type I error | Many zero-interaction replicates | False-positive rate is close to the declared alpha with Monte Carlo uncertainty reported. |
| Clustering | Coverage under pass-block versus row bootstrap | Pass-block coverage approaches nominal and the row bootstrap visibly under-covers; unexpected results are investigated, not forced. |
| Effect size | Citation and instrument comparison | Target is scientifically meaningful and resolvable. |

### Task 1 completion gate

Task 1 is complete only when every Step 1–3 deliverable below exists, every listed check passes
or its failure is explicitly documented, Step 2's definitive result has replaced the preliminary
Step 1 verdict, and `T3.1` states which models are supported by the real pass count. A quick or
synthetic profile validates code only; it cannot satisfy the scientific gate.

## Canonical deliverable registry

### Steps 1–3 (Task 1)

| ID | Required content |
|---|---|
| F1.1 | Five-city demand-percentile versus 30-day dryness-percentile scatter; daily points, tercile grid, diagnostic corners, nine cell counts, and Spearman correlation. |
| F1.2 | Same panels with all days grey and clear-sky days coloured; both corner counts annotated. |
| F1.3 | City-grouped diagnostic-corner counts/proportions for all versus clear-sky days, with binomial confidence intervals. |
| F1.4 | F1.1 repeated for the 60-day window. |
| T1.1 | City × nine-cell counts for all and clear days, diagnostic-corner proportions and confidence intervals, and Spearman correlation with summer-block-bootstrap interval. |
| T1.2 | City domain provenance, area, summer-day count, clear-day count, and clear percentage. |
| M1.1 | One-page per-city and overall separability verdict: within-city, cross-city only, or not estimable, with recommendation. |
| F2.1 | Five-city daytime local-solar-time histograms with provisional stratum boundaries and counts. |
| F2.2 | Usable-pass heatmaps for city × year and city × time stratum. |
| F2.3 | Per-city attrition from total granules through daytime, geolocation, obstruction, near-nadir, and cloud survival, with counts and percentages. |
| F2.4 | Pass-date strips by city/year coloured by retrieval band mode. |
| F2.5 | Definitive Step 1 joint distributions using usable pass dates and acquisition-time demand. |
| T2.1 | City × year × time-stratum usable-pass counts with row and column totals. |
| T2.2 | Attrition values behind F2.3, including cloud-survival estimate and method. |
| T2.3 | Scene metadata dictionary with field definition, units, and source. |
| F3.1 | Interaction power versus pass count for at least three effect sizes, with observed count marked. |
| F3.2 | Smooth-truth transition false-positive rate versus pass count with nominal alpha. |
| F3.3 | Estimated breakpoint distribution when no breakpoint exists. |
| F3.4 | Interaction-coefficient recovery versus pass count, intervals, and true value. |
| F3.5 | Confidence-interval coverage under pass-block and naive row bootstrap. |
| T3.1 | Minimum passes by planned model, detectable effect at observed count, and three-way-interaction verdict. |

### Steps 4–9

| ID | Required content |
|---|---|
| F4.1 | Annotated hot Phoenix afternoon LST scene covering a park, golf course, freeway interchange, and residential block. |
| F4.2 | Temperature, cloud, water, and quality layers for the same scene. |
| F4.3 | Scene and pooled LST histograms for high canopy, impervious, and water classes. |
| F4.4 | Per-pixel valid-observation count map with domain outline. |
| F4.5 | Scene-mean LST by retrieval-mode period within solar-zenith bins. |
| F4.6 | Two-scene temperature-edge/road-network geolocation check. |
| T4.1 | One usable scene per row with every required scene metadata field. |
| T4.2 | Per-scene pixel attrition through water, cloud, quality, plausibility, and final masks. |
| T4.3 | Frozen version-specific product/layer/unit/scale/fill data dictionary. |
| F5.1 | Albedo and uncertainty for a good and degraded scene. |
| F5.2 | Fused versus native 30 m vegetation index by fine-image lag. |
| F5.3 | Absolute fusion error versus fine-image lag with fitted trend. |
| F5.4 | Incoming and net radiation versus solar zenith by city. |
| F5.5 | Four-member evapotranspiration pairs plot over high-canopy pixels. |
| F5.6 | Evaporative stress versus ET/PET consistency plot. |
| T5.1 | Product/version/layer inventory and scene-match completeness. |
| T5.2 | Pairwise ET correlation, bias, and RMS difference over high-canopy pixels. |
| F6.1 | Gridded versus station VPD at acquisitions with 1:1 line, bias, and RMS difference. |
| F6.2 | Phoenix seasonal demand and 30/60-day balance with pass dates and monsoon onset. |
| F6.3 | Pass-time meteorological-predictor correlation heatmap. |
| F6.4 | HRRR versus ERA5-Land demand at pass times. |
| F6.5 | Nearest-hour versus linearly interpolated demand and difference distribution. |
| T6.1 | Per-city gridded/station temperature, dewpoint, and VPD validation. |
| T6.2 | Correlation matrix plus bootstrap intervals for demand versus antecedent variables. |
| F7.1 | Pre-pass vegetation/moisture composites beside seasonal composite. |
| F7.2 | Per-city optical-image lag distribution with cutoff. |
| F7.3 | Canopy fraction versus seasonal vegetation index with turf/golf outliers. |
| F7.4 | Phoenix first-to-last-year canopy change and flagged share. |
| F7.5 | Focal versus buffer imperviousness. |
| T7.1 | Land-cover product/release/resolution/year-assignment inventory. |
| T7.2 | Canopy-change exclusions by city/year. |
| F8.1 | Canopy-fraction distributions with three candidate thresholds and retained counts. |
| F8.2 | Tree/reference/excluded maps for residential and park areas over aerial imagery. |
| F8.3 | Pre/post-match standardized-mean-difference balance plot with 0.1 line. |
| F8.4 | Unshifted versus four one-pixel-shift cooling contrasts with intervals. |
| F8.5 | Validation confusion matrices by land-use stratum. |
| F8.6 | Tree-sample land-use composition by city. |
| F8.7 | Simple continuous LST-versus-canopy-fraction smooth. |
| T8.1 | Precision, recall, and F1 by city, canopy-purity class, and land-use stratum. |
| T8.2 | Tree/reference covariate balance before and after matching. |
| T8.3 | Tree, reference, and matched-set counts at three thresholds by city. |
| F9.1 | Analysis-table missingness matrix. |
| F9.2 | Outcome/key-predictor distributions with units. |
| F9.3 | Analysis-ready row counts by city, year, and time stratum. |
| F9.4 | Irrigation-evidence class counts and record-confirmed share by city. |
| T9.1 | Complete column definition/unit/source/version/transformation dictionary. |
| T9.2 | Row counts and core-variable completeness by city/year/stratum. |

### Steps 10–14

| ID | Required content |
|---|---|
| F10.1 | Raw cooling contrast versus local solar time by city; stratum boundaries; day/night separate. |
| F10.2 | Cooling contrast versus solar zenith and day of year in separate panels. |
| F10.3 | Pre/post-restriction common-support diagnostics with removals. |
| F10.4 | Fitted time-of-day effects by city and pooled for all three models. |
| F10.5 | Primary late-afternoon minus late-morning forest plot, per city and pooled under two weightings. |
| F10.6 | Primary contrast across all three outcomes. |
| F10.7 | Night result on the same axes as daytime. |
| F10.8 | Residual/fitted, residual/solar-zenith, and one-city spatial residual diagnostics. |
| T10.1 | Primary estimates, intervals, passes, and matched sets by city and both pooled weights. |
| T10.2 | Full model terms, bases, dimensions, random effects, fit statistics, and software version. |
| T10.3 | Concurvity among time, geometry, radiation, temperature, demand, and season. |
| F11.1 | Full and leave-one-city-out primary-endpoint forest plot. |
| F11.2 | Five-city data-quality panel. |
| F11.3 | Per-city continuous canopy model standardized to common canopy fractions. |
| F11.4 | Primary endpoint versus background climate as five labelled cases, not a fitted population gradient. |
| T11.1 | City inclusion criteria, achieved values, and pass/fail. |
| T11.2 | Held-out city, selection time/basis, and proof no thermal result preceded selection. |
| F12.1 | Demand × antecedent-balance tensor surface by time stratum with unsupported regions masked. |
| F12.2 | Pass-support map on the same axes. |
| F12.3 | Demand slices at low/medium/high antecedent dryness by stratum. |
| F12.4 | Held-out predictive and information-criterion comparison of linear, smooth, and transition models. |
| F12.5 | Supported transition locations and intervals by stratum/city with published values. |
| F12.6 | Radiatively standardized and total surfaces side by side. |
| T12.1 | Interaction estimate/smooth, uncertainty, held-out comparison, and effective pass count. |
| T12.2 | Transition estimate assessed against every preregistered criterion. |
| F13.1 | Placebo on the main-result axes. |
| F13.2 | Night versus day on identical axes and scale. |
| F13.3 | Tornado plot of every sensitivity result. |
| F13.4 | Uncertainty budget with combined interval and detection limit. |
| F13.5 | Radiatively standardized versus total primary contrast by city. |
| T13.1 | Every sensitivity estimate, interval, change, and conclusion. |
| T13.2 | Uncertainty source, magnitude, estimation method, and combined contribution. |
| F14.1 | Paper study-design figure: domains, matched comparison, and time-stratum coverage. |
| F14.2 | Paper primary-result figure: local-time strata by city and pooled with fixed-overpass context. |
| F14.3 | Paper demand × antecedent-dryness surface with unsupported regions masked. |
| F14.4 | Paper radiative pathway decomposition with albedo modifier. |
| F14.5 | Paper ET, evaporative-stress, optical-canopy, and thermal supporting evidence. |
| F14.6 | Paper placebo, night, leave-one-out, uncertainty-budget, and detection-limit robustness figure. |
| M14.1 | Go/adjust/stop memo and basis. |
| M14.2 | Confirmatory held-out-city and 2026 report, written before any later method change. |
| P14.1 | Public code, scene/version/download-date list, analysis table, decision log, and reproducible build. |

## Later-step completion gates

These gates preserve requirements that are not visible from the deliverable titles alone.

| Step | Completion gate |
|---:|---|
| 4 | F4.1–F4.6 and T4.1–T4.3 exist; all seven source checks pass; the hot-afternoon Phoenix map has physically sensible known-location ordering; masking, geolocation, band-mode, selective attrition, and checksum rerun checks are documented. |
| 5 | F5.1–F5.6 and T5.1–T5.2 exist; the vegetation-fusion artefact is quantified and a frozen filter is set; radiation and albedo are physical; ET members are distinct; internal consistency and scene-match completeness are reported. |
| 6 | F6.1–F6.5 and T6.1–T6.2 exist; the VPD formula check is exact; temporal/spatial alignment, stations, interpolation, HRRR/ERA5-Land comparison, and acquisition-time demand–antecedent correlation are recorded. |
| 7 | F7.1–F7.5 and T7.1–T7.2 exist; no future imagery leaks into a pass; image-lag and canopy-change rules are applied and quantified; year-specific releases and focal-versus-buffer form are auditable. |
| 8 | F8.1–F8.7 and T8.1–T8.3 exist; matching reaches the declared balance target; validation precision/recall is reported by stratum; registration sensitivity is smaller than the detectable effect; threshold sensitivity and continuous-canopy results are retained. |
| 9 | F9.1–F9.4 and T9.1–T9.2 exist; all six source checks pass; the table has one declared grain, no accidental duplicates or impossible values, and rebuilds byte-identically from code. |
| 10 | F10.1–F10.8 and T10.1–T10.3 exist; all seven source checks pass; common support is enforced; pass-block uncertainty is used; day/night and equal-city/observation weightings remain distinct; the primary endpoint can be stated with honest uncertainty. |
| 11 | F11.1–F11.4 and T11.1–T11.2 exist; one identical pipeline is used across cities; inclusion follows the written quality rule; held-out selection precedes thermal inspection; the primary result survives or honestly fails leave-one-city-out. |
| 12 | F12.1–F12.6 and T12.1–T12.2 exist; no unsupported region is interpreted; predictive comparison is blocked by whole years/passes/cities; any transition meets every preregistered criterion, otherwise the smooth/null result is reported. |
| 13 | F13.1–F13.5 and T13.1–T13.2 exist; placebo and night checks behave or are explained; sensitivities are complete; the effect exceeds the combined uncertainty/detection limit or is honestly reported as not doing so. |
| 14 | F14.1–F14.6, M14.1–M14.2, and P14.1 exist; logs prove the method froze before held-out data opened; every claim maps to an artifact; inference language stays within scope; an independent colleague can rebuild the package. |
