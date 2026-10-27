# Response to Prof. Alizadeh: Steps 1–3

**26 October 2026 — all three requested steps are complete.** This follows Section 7 of the latest pilot review. It is separate from the earlier six-task review.

The new analyses are consistent with the proposed radiative explanation: **a clear afternoon cooling deficit is no longer evident after accounting for incoming shortwave.** All seven previously unopened Phoenix estimates also fall inside their pre-recorded prediction intervals. Alignment and canopy-layer concerns remain unresolved, so these results do not establish radiation as the sole mechanism.

**[Reza’s original Figure 1](FIGURES.md)** is included alongside the new figures ([direct PNG](reference/reza_review_figure_1.png)).

## What was done

| Requested step | Completed work | Open the deliverable |
|---|---|---|
| **1. Add inputs; no new cooling fits** | One row for all 23 passes; exact scene geolocation flags, HRRR shortwave/weather and sun elevation. Shortwave uses the requested cosine-normalized interpolation. | [23-pass CSV](../../../deliverables/Advisor_Step1_Inputs_23Passes_v6_2_20261026/pass_inputs_23.csv) · [column guide](../../../deliverables/Advisor_Step1_Inputs_23Passes_v6_2_20261026/DATA_DICTIONARY.md) |
| **2. Test the 2023 pass-level relationship** | Separate city OLS fits with shortwave + after_noon; repeats using sine of sun elevation and Phoenix’s common footprint. Coefficients, SEs, residual SD and morning/afternoon cooling-to-shortwave ratios. | [Figures](FIGURES.md) · [coefficients](../../../deliverables/Advisor_Step2_Models_2023_v6_2_20261026/coefficients.csv) · [ratios](../../../deliverables/Advisor_Step2_Models_2023_v6_2_20261026/morning_afternoon_ratios.csv) · [full Step 2 report](../../../deliverables/Advisor_Step2_Models_2023_v6_2_20261026/README.md) |
| **3. Predict first, then open seven estimates** | Seven individual 95% prediction intervals committed before outcome access; observed/predicted comparison and the same model refitted on all 18 Phoenix passes. | [Dated prediction note](../../../deliverables/Advisor_Step3_Prediction_Test_v6_2_20261026/pre_access/prediction_note_20261026.md) · [comparison table](../../../deliverables/Advisor_Step3_Prediction_Test_v6_2_20261026/observed_vs_predicted_7.csv) · [refit table](../../../deliverables/Advisor_Step3_Prediction_Test_v6_2_20261026/refit_coefficients.csv) |

## Main results

After-noon coefficients below compare afternoon with morning at the same shortwave within the specified linear model. Units are K per +10 percentage points of canopy; positive means greater fitted cooling in the afternoon.

| Sample | Passes | After-noon estimate | 95% interval |
|---|---:|---:|---:|
| Phoenix 2023, original populations | 11 | +0.183 | [−0.110, +0.476] |
| Phoenix 2023, common footprint | 11 | +0.180 | [−0.038, +0.398] |
| Atlanta 2023 | 5 | −0.005 | [−0.371, +0.362] |
| Phoenix, after adding the seven other-year passes | 18 | +0.202 | [−0.020, +0.424] |

All four intervals include zero. The sine-of-sun-elevation repeats give the same broad picture. Phoenix’s original and common-footprint estimates above use all eleven 2023 dates; they are not a direct re-estimate of the earlier selected five-date contrast.

For the prediction check, **7/7 points were inside their individual intervals, including 3/3 afternoon passes**. Prediction RMSE was **0.188 K/+10pp**. The largest error was the 2019 afternoon pass (orbit 6281): observed **1.201**, predicted **0.826**, difference **+0.375**. It was inside a fairly wide interval. This is an encouraging but limited check, not proof that the model captures every mechanism.

## Details and limitations worth discussing

- Exact source metadata gives **38 Best and 2 Good scenes**. The census accepted both. These flags do not verify actual image alignment. Pooled “Best/Good” entries were resolved from cached original metadata with Jamie’s approval.
- Four other-year passes had approximately 52-second differences between model-table and older geometry-audit timestamps. Jamie approved retaining model-table times; both timestamps and individual scene times are documented. The bracketing HRRR hours are unchanged.
- Atlanta has only five dates and **no overlap between morning and afternoon radiation ranges**. Its adjusted comparison is descriptive and depends strongly on the assumed line. Phoenix has only three 2023 morning dates and a narrow morning radiation range.
- Orbits **6281 and 33496** extend beyond their training arm’s radiation range. This was labelled before their outcomes were opened. Individual prediction intervals are fairly wide and are not simultaneous seven-pass coverage intervals.
- All regressions use equal pass weights and ordinary OLS SEs as requested. The figures separately show existing 8 km spatial intervals; the pass-level OLS does not propagate the full uncertainty/covariance of those estimated cooling values.

## Prediction record and next action

The prediction note, exact inputs and predictions were committed as [`d33734b`](https://github.com/jamielee0/CanopyCooling/commit/d33734b1fdf88860f827d680ba57900c965b0519) **before the seven outcomes were opened**. [Commit receipt](../../../deliverables/Advisor_Step3_Prediction_Test_v6_2_20261026/prediction_commit_receipt.json) · [first-access record](../../../docs/v2/v6_2/execution/advisor_step3_20261026/outcome_access_started.json) · [full Step 3 report](../../../deliverables/Advisor_Step3_Prediction_Test_v6_2_20261026/README.md).

**Steps 1–3 are ready for review before Step 4.** Step 4 has not started. Further synthetic calibration, temperature–energy agreement work and quadratic analysis remain stopped. No new pixel-level cooling model or raw thermal acquisition was needed for these three steps. The sixteen-pass 2023 pilot remains the main sample; the eighteen-Phoenix-pass refit is a labelled multiyear extension check.

The code and checks are included: [Step 1](../../../src/v6_2_advance/run_advisor_step1.py), [Step 2](../../../src/v6_2_advance/run_advisor_step2.py), [Step 3](../../../src/v6_2_advance/run_advisor_step3.py). There were 21, 8 and 4 relevant tests respectively, plus independent numerical/source checks and figure review. [Publication provenance](../../../docs/v2/v6_2/execution/advisor_publication_20261026/pre_push_record.json).

[Earlier six-task review](../README.md#earlier-six-task-review). Historical packages retain their original completion/disclosure statements; “not pushed” in those execution snapshots describes their status before this publication.
