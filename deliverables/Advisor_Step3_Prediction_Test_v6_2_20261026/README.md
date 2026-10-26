# Advisor Step 3: the seven-pass prediction test

26 October 2026 · Completed and independently verified.

**All seven observed cooling estimates fell within their recorded 95% prediction intervals, including all three afternoon passes.** The eighteen-pass refit has a positive after-noon estimate, +0.202 K/+10pp (SE 0.104; 95% interval −0.020 to +0.424). The interval includes zero, so this is not evidence that afternoon cooling is definitively stronger.

This meets the two recorded directional expectations: the afternoon points are inside their intervals, and the after-noon estimate remains positive after the seven passes are added. It is consistent with Reza’s radiative explanation, rather than proof that radiation is the sole mechanism.

## Predictions were committed before opening outcomes

The unchanged [dated prediction note](pre_access/prediction_note_20261026.md), [prediction CSV](pre_access/predictions_7.csv), training/target inputs and supporting code were committed locally as **`d33734b1fdf88860f827d680ba57900c965b0519`**, on branch `advisor-step3-20261026`. The [commit receipt](prediction_commit_receipt.json) and recorded first-access time verify that sequence. The standalone [reproduction script](pre_access/reproduce_predictions.py) uses no held-out outcomes.

The predictor is the original-population Phoenix model from Step 2: cooling versus shortwave plus after_noon, trained on eleven 2023 dates. Individual prediction intervals include residual variance and use `obs_ci_lower/upper` from `get_prediction(...).summary_frame()`. They are not intervals for the fitted mean. The eighteen-pass refit did not replace these predictions.

## What the seven passes showed

Cooling and prediction intervals are K per +10 percentage points canopy.

| Orbit | Date | Arm | Predicted | Observed | 95% prediction interval | Inside? |
|---|---|---|---:|---:|---|---|
| 6281 | 2019-08-14 | Afternoon | 0.826 | 1.201 | [0.368, 1.285] | Yes |
| 6510 | 2019-08-29 | Morning | 1.219 | 1.024 | [0.777, 1.662] | Yes |
| 33496 | 2024-06-02 | Morning | 1.346 | 1.223 | [0.898, 1.793] | Yes |
| 33623 | 2024-06-10 | Afternoon | 1.119 | 1.261 | [0.710, 1.527] | Yes |
| 40111 | 2025-08-02 | Morning | 1.255 | 1.413 | [0.812, 1.698] | Yes |
| 40192 | 2025-08-07 | Afternoon | 0.994 | 0.988 | [0.572, 1.416] | Yes |
| 40376 | 2025-08-19 | Morning | 1.245 | 1.157 | [0.802, 1.688] | Yes |

Mean observed-minus-predicted error is +0.038 K/+10pp; prediction RMSE is 0.188. The largest miss is the 2019 afternoon pass (orbit 6281): observed cooling is 1.201 versus 0.826 predicted, a +0.375 difference. It remains within its wide prediction interval. That pass and the 2024 morning pass (33496) extend beyond their training arm’s radiation range, as labelled before outcome access.

![Observed versus predicted cooling](observed_vs_predicted.png)

[Download figure PDF](observed_vs_predicted.pdf). Horizontal bars are the committed individual prediction intervals; vertical bars are archived 8 km spatial intervals for observed pass cooling. The dashed line marks exact agreement. These are different sources of uncertainty.

## Same model, refitted on eighteen Phoenix passes

Unweighted OLS: `cooling ~ shortwave_W_m2 + after_noon`, using original pass populations, seven morning and eleven afternoon dates. There are fifteen residual degrees of freedom; residual SD is 0.165 K/+10pp.

| Term | Estimate | SE | 95% interval |
|---|---:|---:|---|
| Intercept | 0.457 | 0.218 | [-0.008, 0.922] |
| Shortwave, per 100 W/m² | 0.081 | 0.022 | [0.033, 0.128] |
| After-noon | 0.202 | 0.104 | [-0.020, 0.424] |

The after-noon point estimate changed from +0.183 in the eleven-pass training model to +0.202 in the eighteen-pass refit. The shortwave slope remains positive. These are conditional associations; no numerical “near-zero” margin was supplied or invented. The intercept is a model parameter, not a claim about nighttime cooling.

## What this does and does not settle

The added passes do not reveal the predicted model failing its recorded afternoon interval check. However, seven points with fairly wide intervals provide a limited test. Individual 95% intervals are not simultaneous coverage guarantees, and interval inclusion alone does not validate the mechanism or establish general summer behavior. Alignment and canopy-layer concerns remain. The multiyear comparison also retains the historical canopy/context-vintage limitations and does not introduce year/month controls. The original sixteen-pass 2023 pilot remains separate from this eighteen-Phoenix-pass extension.

## Deliverables and next action

- [Observed/predicted values and interval checks](observed_vs_predicted_7.csv).
- [Refit coefficients in original units](refit_coefficients.csv), [diagnostics](refit_diagnostics.json), [all eighteen input rows](refit_inputs_18.csv), and [fitted values/residuals](refit_fitted_values.csv).
- [Dated prediction note](pre_access/prediction_note_20261026.md) and [commit receipt](prediction_commit_receipt.json).

Four network-free tests passed, covering individual prediction variance, the actual Git commit gate, temperature sign/quantile extraction and interval boundaries. Independent matrix calculations reproduced both the saved predictions and the eighteen-pass refit; original source hashes and the first eleven rows are unchanged. No native thermal cells were read and no Stage 1 model was refitted. The archived seven-pass temperature points are now disclosed in this bounded Step 3 packet; their original files remain unchanged.

**Steps 1–3 are ready for Reza’s review before Step 4.** Nothing was pushed or sent, and Step 4 has not started. Synthetic calibration, temperature–energy agreement and further quadratic analysis remain stopped. The prediction commit is local in `../../outputs/v6_2/scientific/advisor_step3_20261026/git_checkout/`; the later comparison outputs are saved in this working export. Detailed execution records are in `../../docs/v2/v6_2/execution/advisor_step3_20261026/`.
