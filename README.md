# Urban canopy cooling with ECOSTRESS

## Latest review for Prof. Alizadeh — 26 October 2026

**[Start here: advisor Steps 1–3, summary and deliverables](review/current/advisor_steps_1_3_20261026/README.md)** · **[Figures](review/current/advisor_steps_1_3_20261026/FIGURES.md)**

The requested geolocation/radiation inputs, city-specific pass models and seven-pass prediction test are complete. After accounting for shortwave, a clear afternoon cooling deficit is no longer evident in the specified models. All seven previously unopened Phoenix estimates fall within their committed individual 95% prediction intervals. The eighteen-pass after-noon estimate is +0.202 K/+10pp (95% interval −0.020 to +0.424).

| Step | Completed output |
|---|---|
| 1. Inputs | [23-pass table](deliverables/Advisor_Step1_Inputs_23Passes_v6_2_20261026/pass_inputs_23.csv), exact scene geolocation flags, HRRR shortwave/weather and sun elevation |
| 2. Models | [2023 models and figures](deliverables/Advisor_Step2_Models_2023_v6_2_20261026/README.md), including sun-elevation and common-footprint repeats |
| 3. Prediction test | [Dated committed predictions, observed comparison and eighteen-pass refit](deliverables/Advisor_Step3_Prediction_Test_v6_2_20261026/README.md) |

The prediction record is preserved in commit [`d33734b`](https://github.com/jamielee0/CanopyCooling/commit/d33734b1fdf88860f827d680ba57900c965b0519), before outcome access. The original sixteen-pass 2023 pilot is unchanged; the additional Phoenix years are an extension check. Small samples, limited radiation overlap, image alignment and canopy/context-vintage limitations prevent a causal or general-summer conclusion.

**Steps 1–3 are ready for review before Step 4.** Step 4 has not started; further synthetic calibration, temperature–energy agreement and quadratic work remain stopped.

## History and reproducibility

- [Earlier six-task review](review/current/README.md#earlier-six-task-review), [checklist](review/current/DELIVERABLES_INDEX.md), and [archived packages](archive/README.md)
- [Preserved October 6 scientific release](deliverables/Pilot_Results_Review_2023_v6_2_20261006/README.md)
- [Active protocol](docs/v2/v6_2/protocol_v6_2.yml), [pilot plan](docs/v2/v6_2/pilot_plan_v6_2.md), [decision history](docs/v2/v6_2/decision_log_v6_2.md)
- [Source code](src/) and [tests](tests/)

Historical result packages, prediction bytes and prior commits are preserved. Their original status statements describe their execution dates. Raw downloads, model arrays, credentials and personal correspondence remain local; released scientific tables, figures, code and provenance are included here.
