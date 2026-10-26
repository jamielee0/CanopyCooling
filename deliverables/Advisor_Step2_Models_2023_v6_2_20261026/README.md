# Advisor Step 2: radiation and afternoon cooling

26 October 2026 · Completed and verified.

**The fitted afternoon deficit is no longer evident after accounting for radiation.** The shortwave-adjusted after-noon term is +0.183 K/+10pp for Phoenix and −0.005 for Atlanta; both 95% intervals include zero. Phoenix’s common footprint gives +0.180. The sun-elevation models give the same broad pattern. This is consistent with Reza’s explanation, but does not establish that radiation is the sole cause or that afternoon cooling is stronger.

## Requested models

For each city/population: `cooling = intercept + b × exposure + c × after_noon + error`. Cooling is the existing positive cooling estimate per +10 percentage points of canopy. Exposure is either incoming shortwave (W/m²) or sine of sun elevation; `after_noon = 1` when apparent solar hour is above 12. All passes receive equal weight. Each reported coefficient uses ordinary OLS standard errors, exactly as requested. No pixel-level cooling model was refitted.

| City / population | Exposure | Intercept ± SE | Exposure slope ± SE | After-noon ± SE | Residual SD |
|---|---|---:|---:|---:|---:|
| Phoenix / original | Shortwave, per 100 W/m² | 0.295 ± 0.258 | 0.101 ± 0.026 | +0.183 ± 0.127 | 0.166 |
| Phoenix / common | Shortwave, per 100 W/m² | 0.301 ± 0.192 | 0.068 ± 0.019 | +0.180 ± 0.095 | 0.124 |
| Atlanta / original | Shortwave, per 100 W/m² | 0.052 ± 0.124 | 0.026 ± 0.015 | -0.005 ± 0.085 | 0.046 |
| Phoenix / original | Sine elevation, per unit | 0.059 ± 0.307 | 1.312 ± 0.325 | +0.186 ± 0.125 | 0.163 |
| Phoenix / common | Sine elevation, per unit | 0.097 ± 0.205 | 0.927 ± 0.218 | +0.192 ± 0.084 | 0.109 |
| Atlanta / original | Sine elevation, per unit | -0.036 ± 0.311 | 0.316 ± 0.326 | +0.021 ± 0.169 | 0.060 |

Intercepts, after-noon terms and residual SD are in K/+10pp. Shortwave slopes above are rescaled per 100 W/m² for readability; the [full coefficient CSV](coefficients.csv) reports the requested raw per-W/m² coefficients and all 95% intervals. Intercepts at zero exposure are model parameters, not a nighttime estimate.

The shortwave-model 95% intervals for the after-noon term are Phoenix original [−0.110, +0.476], Phoenix common [−0.038, +0.398], and Atlanta [−0.371, +0.362] K/+10pp. All six models’ after-noon intervals include zero. Phoenix’s exposure slopes are positive with model-based intervals excluding zero; Atlanta’s exposure slopes are much less precise.

## Cooling divided by shortwave

These are the requested means of individual pass ratios, not ratios of group means. Values below are multiplied by 1,000; original units are (K/+10pp)/(W/m²).

| City / population | Morning | Afternoon | Passes, morning / afternoon |
|---|---:|---:|---:|
| Phoenix / original | 1.338 | 1.789 | 3 / 8 |
| Phoenix / common | 1.005 | 1.456 | 3 / 8 |
| Atlanta / original | 0.323 | 0.395 | 3 / 2 |

These ratio summaries are descriptive and do not replace the regression; a ratio implicitly treats the intercept differently.

## Figures and limits

- [Phoenix shortwave](phoenix_shortwave.png) ([PDF](phoenix_shortwave.pdf)): original and common populations side by side.
- [Atlanta shortwave](atlanta_shortwave.png) ([PDF](atlanta_shortwave.pdf)).
- Sun-elevation repeats: [Phoenix](phoenix_sun_elevation.png) ([PDF](phoenix_sun_elevation.pdf)) and [Atlanta](atlanta_sun_elevation.png) ([PDF](atlanta_sun_elevation.pdf)).

Points show existing pass estimates; vertical bars show existing 95% spatial intervals using 8 km groups. Lines show the two fitted OLS arms over each arm’s observed exposure range. These bars are not regression uncertainty or weighting. The common-footprint intervals retain the archived non-estimable-draw handling; no draw or interval was replaced.

Phoenix uses all eleven 2023 dates (three morning, eight afternoon), rather than the earlier selected five-date time contrast. Its morning radiation range is narrow, about 887–975 W/m². Atlanta has just five dates (three morning, two afternoon), two residual degrees of freedom, and no morning/afternoon exposure-range overlap. Its after-noon comparison relies heavily on the assumed linear relationship and remains descriptive. The ordinary OLS intervals are conditional on that model and do not propagate the full covariance/measurement uncertainty of the estimated pass cooling values.

The common footprint changes the represented population. It uses the same Step 1 city-domain weather and reference solar geometry for each pass; no common-domain weather product was newly extracted. Alignment and canopy-layer concerns remain unresolved.

## Files and next step

Exact inputs: [model_inputs_2023.csv](model_inputs_2023.csv), 27 rows representing 16 distinct passes plus 11 common-population repeats. Additional outputs: [model diagnostics](model_diagnostics.csv), [arm ratios](morning_afternoon_ratios.csv), and [fitted values/residuals](fitted_values_and_residuals.csv). Eight network-free tests passed; independent QR calculations reproduced all coefficients, standard errors, intervals, residuals and ratio summaries. All four figure layouts were inspected.

**Next is Step 3:** use the Phoenix shortwave model to predict the seven other-year passes and save a dated prediction note, committing it before opening those outcomes. No Step 3 predictions or other-year outcome access occurred here. Synthetic calibration, temperature–energy agreement and further quadratic analysis remain stopped. Nothing was committed, pushed or sent.

Execution and provenance: `../../docs/v2/v6_2/execution/advisor_step2_20261026/`. The Step 1 package and historical results remain unchanged.
