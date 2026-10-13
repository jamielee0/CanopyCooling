# Methods and figure captions — review draft

## Empirical methods

We retained eleven Phoenix and five Atlanta ECOSTRESS acquisitions from 2023 and the original paired native-cell samples. Each city-pass temperature and emitted-energy model included a common linear canopy term, 1 km block intercepts and the six frozen contextual covariates. Original temperature estimates were reconstructed before uncertainty calculations. No cells, dates, controls or canopy endpoints were selected according to new effect values.

The exploratory Phoenix comparison contrasted the specified morning (09:30–11:30 apparent solar time) and afternoon (15:00–18:00) windows. June11 and August11 each received afternoon weight 0.50; June26 received morning weight 0.50, and August6 and August23 each received morning weight 0.25. Monthly contrasts were retained separately. Positive differences denote greater canopy-associated mixed-pixel surface cooling on the sampled afternoon dates. These are conditional associations from different dates, not causal planting responses or same-day diurnal trajectories.

We sampled whole spatial groups from each city's union of physical locations. A common multiplicity vector was applied to every date and both outcomes in each draw. Structurally absent groups contributed zero statistics, while repeated groups were represented by repeated within-block sufficient statistics. Models retained their original intercept scale and controls. One thousand draws were generated for both 1 km and 8 km group sizes. For each supported comparison, standard errors and percentile intervals were calculated from matched draws. These characterize spatial estimation uncertainty while holding dates and weights fixed.

Emitted-energy predictions were averaged within each comparison arm before fixed-reference anchoring and fourth-root transformation. The two arm equivalents were then differenced. Temperature remained primary; energy and reference-equivalent temperature were paired diagnostics. No scale-equivalence verdict was issued. Deleting a date was allowed only when all required month/arms remained represented; remaining weights were renormalized within the existing month/arm without changing its half-month weight.

## Calibration methods

Separate synthetic experiments used the actual city-specific schedules and estimated spatial covariance, with explicit hypothetical time/season means and between-day covariance structures. The target population contrast and realized-date contrast were tracked separately. We compared the existing independent-day slope bootstrap, within-arm date resampling, a moment-based spatial/day variance separation candidate, a spatial-only interval, a known-variance oracle and a duplicated-spatial-noise negative control. The candidate maintained the frozen window point estimator and did not add a second independent copy of pass-estimation error.

Development and production used independent random streams. Production comprised 2,000 generated datasets for each of 216 scenarios. Coverage, Monte Carlo error, interval width, bias, failures and resampled support loss were retained without tuning to an empirical contrast. Covariance matrices were treated as known generator inputs; the assessment does not validate the empirical spatial bootstrap or random sampling of dates. No general-season empirical interval was adopted.

## Captions

**Public fixed-date precision figure.** Bootstrap standard errors for the combined and monthly Phoenix comparisons, two supported deletion comparisons, and deletion-minus-full changes. Light and dark bars use whole 1 km and 8 km physical groups, respectively. Shared multiplicities preserve cross-date spatial dependence. The figure displays precision only; empirical points and confidence endpoints remain sealed. It does not measure uncertainty over additional summer days.

**Private comparison figure — pending authorized effect review.** Phoenix afternoon-minus-morning canopy-cooling differences with pointwise percentile intervals from matched spatial resampling. Influence rows show deletion-minus-full differences. Deleting June11, June26 or August11 empties a required month/arm and is unsupported. All intervals condition on the selected dates; no general-season or causal interpretation is implied. Numerical interpretation will be added only after authorized review.

**Synthetic coverage figure.** Minimum population-target coverage across the declared amplitude, day-variability and spatial-correlation grid within each mean/day profile. Each scenario uses 2,000 generated datasets and a nominal 95% interval. Cells summarize hypothetical processes at the observed schedules, not empirical cooling estimates. Scenario minima are exploratory summaries; they are not practical-significance margins or scale-agreement thresholds.
