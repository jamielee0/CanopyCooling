# Urban tree cooling v6.2 active workspace

## Current sampling rebalance — 21 September 2026

The user asked to rebalance the pass sample, including additions/removals. The bounded correction is complete: **Phoenix has 18 paired Stage 1 passes; 12 form a balanced morning/afternoon comparison subset across five year-months. Atlanta retains five.** Seven new Phoenix passes were frozen using orbital, geometry and cloud information before thermal download: 06281, 06510, 33496, 33623, 40111, 40192 and 40376. The new runs produced 28 paired fits at 1/2/4/8 km resampling sizes, with all 28,000 bootstrap draws estimable. No existing result was deleted.

Read `deliverables/Sampling_Rebalance_v6_2_20260921/README.md` for the dates/times, selection rationale, figure, precision and remaining limitations. The complete catalogue audit contains 547 June–September Phoenix orbit acquisitions in 2019–2025. The 2023 catalogue has no July or September morning acquisition in the 09:30–11:30 solar window, even before quality filters. The supported comparison covers June and August; it does not establish a complete June–September time pattern.

The twelve endpoint passes cover August 2019, June/August 2023, June 2024 and August 2025. Give each year-month 20% of each arm's weight, divided among available passes in that arm. This equalizes the year/month distributions without discarding the extra morning passes. Three middle-time June/August 2023 passes remain for shape/context; the July and September 2023 passes remain descriptive because their year-months have no morning counterpart. This is a sampling sensitivity, not a replacement of the exact 10:30-versus-16:00 research contrast or the unresolved full-study season ruling.

Seven new additions were prioritized from the clear-support upper group: matched year-month common clear sample-point counts had a gap from 3 to 214 of 300. Record this distribution-based acquisition priority, not a universal cloud cutoff or an invented pass-count target. The cloudy 2021/2022 candidates stay in the review queue, and unresolved archive geometry is not classified as failed. Freeze: `docs/v2/v6_2/execution/rebalance_20260921/thermal_batch_selection_freeze.json`.

New gradients remain sealed; only precision/support and sampling metadata were published for these seven passes. Earlier disclosed gradients remain exploratory. No new empirical time regression or scale-agreement ruling was computed. Reza's tolerance is pending. The inherited temporal bootstrap needs correction before final inference. Preserve the total observation-time interpretation including solar geometry; geometry/season standardization remains a separate supported analysis.

Month/year balance does not match exact dates, weather or native-cell composition. Common native-cell retention within the selected strata is 73.2%–100%; added-pass common-cell refits and registration stress tests remain outstanding. Older acquisitions also increase mismatch with the frozen context-layer dates. The original 25-degree geometry exception remains; only the August 2019 pair supports the 15-degree sensitivity in both arms. The full-archive/multi-city thermal rollout remains outside this bounded correction; no professor approval is implied. The previous eleven-pass methods/city-screening package remains a historical result, including its nineteen-city nonthermal screen.

## Original pilot documentation (19 September snapshot; current status above controls)

The current study asks how canopy-associated surface cooling varies with satellite observation time and whether a fixed 10:30 observation represents later-day cooling. The September meeting and subsequent radiance email amend v6.2 in place.

## Current documents

- `docs/v2/v6_2/protocol_v6_2.yml` is the machine-readable specification.
- `docs/v2/v6_2/pilot_plan_v6_2.md` documents the full pilot and exact transformation procedure.
- `docs/v2/v6_2/implementation_plan_v6_2.md` records completed implementation, run commands and remaining review decisions.
- `docs/v2/v6_2/decision_log_v6_2.md` records current changes and preserves earlier history.
- `references/` contains the updated proposal, working guide, schedule and next steps, with original meeting/email sources under `references/sources/`.

## Original pilot design and status (historical snapshot)

Fit one canopy slope per city-pass using native ECOSTRESS cells, block-specific intercepts and a shared within-block canopy term. Run matched temperature and emitted-energy models. Remove the per-block 0.20/0.10 canopy-span gates; report pass-level information, contributing-block distributions and information concentration without an arbitrary replacement gate.

The pilot retains Phoenix orbits 27963, 28024, 28706, 28828 and 28909 and selects Atlanta orbits 27835, 27896, 27916, 28145 and 28598. A seeded 300-block nonthermal Science TCC screen found within-block variance of 0.00159 in Phoenix, 0.08301 in Atlanta and 0.07189 in Charlotte. Atlanta also has verified afternoon acquisitions. Its five passes were frozen before thermal download from the existing geometry-verified 2023 June–September inventory.

The pooled estimator, paired emitted-energy model, spatial checks and scale-diagnostic workflow are implemented. The limited Phoenix–Atlanta pilot is authorized and its empirical outputs remain sealed. The meeting package records completed run status and precision. Full-city scaling remains paused until review. Coefficient sealing remains in force for precision review. Reza’s numerical scale-agreement tolerance remains pending. Compute and store paired contrasts without displaying them; do not issue an agreement ruling until the tolerance is prospectively recorded and coefficient release is authorized. Treat an exactly zero contrast as direction unresolved. The full-study power design and Collection 3 historical coverage decision remain for the post-pilot review.

## Preserved history and data

Earlier result packages under `deliverables/` are immutable historical evidence. Their thresholds and stop decisions apply to the old design. The pre-update active documents are preserved under `docs/v2/v6_2/archive/before_meeting_update_20260919/`.

The data symlink has been repaired and verified against the relocated original data tree. Raw files and historical result packages remain preserved. New pilot inputs are under data/raw/v2/pilot_v6_2_20260919/.
