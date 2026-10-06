# Current v6.2 specification

## Current sampling rebalance — 21 September 2026

The user asked to rebalance the pass sample, including additions/removals. The bounded correction is complete: **Phoenix has 18 paired Stage 1 passes; 12 form a balanced morning/afternoon comparison subset across five year-months. Atlanta retains five.** Seven new Phoenix passes were frozen using orbital, geometry and cloud information before thermal download: 06281, 06510, 33496, 33623, 40111, 40192 and 40376. The new runs produced 28 paired fits at 1/2/4/8 km resampling sizes, with all 28,000 bootstrap draws estimable. No existing result was deleted.

Read `deliverables/Sampling_Rebalance_v6_2_20260921/README.md` for the dates/times, selection rationale, figure, precision and remaining limitations. The complete catalogue audit contains 547 June–September Phoenix orbit acquisitions in 2019–2025. The 2023 catalogue has no July or September morning acquisition in the 09:30–11:30 solar window, even before quality filters. The supported comparison covers June and August; it does not establish a complete June–September time pattern.

The twelve endpoint passes cover August 2019, June/August 2023, June 2024 and August 2025. Give each year-month 20% of each arm's weight, divided among available passes in that arm. This equalizes the year/month distributions without discarding the extra morning passes. Three middle-time June/August 2023 passes remain for shape/context; the July and September 2023 passes remain descriptive because their year-months have no morning counterpart. This is a sampling sensitivity, not a replacement of the exact 10:30-versus-16:00 research contrast or the unresolved full-study season ruling.

Seven new additions were prioritized from the clear-support upper group: matched year-month common clear sample-point counts had a gap from 3 to 214 of 300. Record this distribution-based acquisition priority, not a universal cloud cutoff or an invented pass-count target. The cloudy 2021/2022 candidates stay in the review queue, and unresolved archive geometry is not classified as failed. Freeze: `docs/v2/v6_2/execution/rebalance_20260921/thermal_batch_selection_freeze.json`.

New gradients remain sealed; only precision/support and sampling metadata were published for these seven passes. Earlier disclosed gradients remain exploratory. No new empirical time regression or scale-agreement ruling was computed. Reza's tolerance is pending. The inherited temporal bootstrap needs correction before final inference. Preserve the total observation-time interpretation including solar geometry; geometry/season standardization remains a separate supported analysis.

Month/year balance does not match exact dates, weather or native-cell composition. Common native-cell retention within the selected strata is 73.2%–100%; added-pass common-cell refits and registration stress tests remain outstanding. Older acquisitions also increase mismatch with the frozen context-layer dates. The original 25-degree geometry exception remains; only the August 2019 pair supports the 15-degree sensitivity in both arms. The full-archive/multi-city thermal rollout remains outside this bounded correction; no professor approval is implied. The previous eleven-pass methods/city-screening package remains a historical result, including its nineteen-city nonthermal screen.

## Original pilot documentation (19 September snapshot; current status above controls)

The active protocol and pilot plan incorporate the September meeting, written Next Steps and later follow-up email. Version 6.2 is retained. The later email controls paired measurement spaces, time interpretation and the scaling pause; the written Next Steps controls the exact pooled formula and pilot structure. The transcript provides context and audit tasks.

Read `protocol_v6_2.yml`, `pilot_plan_v6_2.md`, `implementation_plan_v6_2.md`, then the latest entry in `decision_log_v6_2.md`. Updated Word documents are in `../../../references/`.

The old block-pass condition model, canopy-span gates, optical gate sequence and eight-pass minimum are no longer active. Historical data inventories, foundation audits, prior-access records and result counts remain evidence of what was done; they are not rewritten as pooled-pilot results. `conformance_memo.md` now records only that the old memo is superseded; new conformance packages are not required.

The old files are preserved in `archive/before_meeting_update_20260919/`. The pooled pilot is implemented and executed for five Phoenix and five Atlanta passes. Its meeting package is `deliverables/Pilot_Meeting_Package_v6_2_20260919/README.md`. Reference and time settings are frozen in execution/output manifests; Reza’s numerical agreement tolerance remains pending. Full-city scaling remains paused and all point estimates remain sealed until the documented review/release sequence permits access.
