# Step 3 prediction note — 26 October 2026

Generated UTC: 2026-10-26T20:40:57.055848+00:00

**Written before opening the seven other-year cooling estimates. This note and its input/output bundle must be committed before outcome access.**

Use the original-population Phoenix shortwave model from Step 2, fitted to all eleven 2023 passes with equal pass weights. Cooling is K per +10 percentage points canopy; after_noon is 1 when apparent solar hour >12. The fitted equation is:

`predicted cooling = 0.294975043439 + 0.001014637388 × shortwave_W_m2 + 0.182706854503 × after_noon`

The intervals below are individual 95% prediction intervals (`obs_ci_lower`, `obs_ci_upper`), including residual variance, with eight residual degrees of freedom. They are not confidence intervals for the mean and are not simultaneous seven-pass coverage intervals. Full precision is in `predictions_7.csv`.

| Orbit | Local date | Arm | Shortwave W/m² | Predicted cooling | 95% prediction interval | Outside training arm’s SW range? |
|---|---|---|---:|---:|---|---|
| 6281 | 2019-08-14 | Afternoon | 343.55 | 0.8263 | [0.3680, 1.2845] | Yes |
| 6510 | 2019-08-29 | Morning | 911.12 | 1.2194 | [0.7767, 1.6621] | No |
| 33496 | 2024-06-02 | Morning | 1035.38 | 1.3455 | [0.8983, 1.7927] | Yes |
| 33623 | 2024-06-10 | Afternoon | 631.92 | 1.1189 | [0.7103, 1.5274] | No |
| 40111 | 2025-08-02 | Morning | 946.29 | 1.2551 | [0.8124, 1.6979] | No |
| 40192 | 2025-08-07 | Afternoon | 508.60 | 0.9937 | [0.5717, 1.4158] | No |
| 40376 | 2025-08-19 | Morning | 936.26 | 1.2449 | [0.8023, 1.6876] | No |

## Expectation recorded before access

If the afternoon decline is radiative, the three afternoon held-out estimates should fall inside their intervals, and the after-noon coefficient should stay near zero or positive when all seven are added. Report all seven point errors and interval checks, including failures. No numerical practical margin for “near zero” has been supplied; report the refit estimate, standard error and 95% interval without inventing a pass/fail margin. Interval inclusion alone will not prove the mechanism.

Two inputs extend beyond their training arm’s shortwave range (orbits 6281 and 33496). Retain both as requested and label extrapolation; do not change the prediction model or intervals after seeing outcomes. The existing models also retain alignment and canopy-vintage limitations.

After verifying the commit, read the seven checksum-bound existing temperature estimates, compare observed against these unchanged predictions, and refit the same unweighted model on all eighteen Phoenix original-population passes. No year/month controls, interactions, model search, new Stage 1 fits, new acquisitions or Step 4 work are added. Preserve the sixteen-pass 2023 main pilot as its original scope; the eighteen-pass refit is the advisor’s multiyear extension check.

The companion files contain the eleven training rows, seven nonthermal target rows, frozen model parameters and a standalone reproduction script. No seven-pass observed cooling values are present in this bundle.
