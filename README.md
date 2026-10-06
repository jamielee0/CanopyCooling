# Urban tree cooling v6.2 active workspace

## Latest released review — 6 October 2026

**[Read the integrated 2023 pilot report](deliverables/Pilot_Results_Review_2023_v6_2_20261006/README.md)**

The current pilot contains **eleven Phoenix and five Atlanta passes, all from 2023**. The results are now released for exploratory review. The selected Phoenix dates show weaker afternoon canopy-associated cooling, with a magnitude that depends on footprint and model choice. The report presents the spatial sensitivities, quadratic results, paired temperature–energy diagnostics, completed weather inputs and uncertainty limitations. A general summer or causal time-of-day effect and a formal scale-agreement ruling are not established.

- [Released pass summary](deliverables/Pilot_Results_Review_2023_v6_2_20261006/pilot_pass_summary.csv)
- [Fixed-date comparison and sensitivity intervals](deliverables/Pilot_Results_Review_2023_v6_2_20261006/joint_window_sensitivities.csv)
- [Methods and captions](deliverables/Pilot_Results_Review_2023_v6_2_20261006/methods_and_captions.md)
- [Remaining scientific decisions](deliverables/Pilot_Results_Review_2023_v6_2_20261006/next_decisions.md)
- [Active protocol](docs/v2/v6_2/protocol_v6_2.yml) and [decision history](docs/v2/v6_2/decision_log_v6_2.md)
- [Earlier published September review](https://github.com/jamielee0/CanopyCooling/tree/main/review/v6.2-2023-pilot)

Code, tests, research documentation, released result packages and publication-safe provenance are versioned. Large raw data, model arrays, local caches, credentials and original personal correspondence remain local. Historical packages and Git history are retained; their original status statements describe their creation dates. The active protocol and the released report above control the current interpretation.

## Historical scope record — 21 September 2026

The user clarified that the pilot under discussion is **2023**. The assistant's previous rebalancing step expanded the year range without making that scope change explicit. That expansion is not the main pilot. **The current pilot remains eleven Phoenix passes and five Atlanta passes, all in 2023.** The seven processed Phoenix passes from 2019, 2024 and 2025 are preserved as a separate exploratory extension and receive no weight in the main 2023 pilot. Eighteen Phoenix passes exist on disk, but only eleven belong to the current pilot.

Read `docs/v2/v6_2/phoenix_2023_sample_scope.md` for the controlling sample description. Retain all eleven 2023 Phoenix passes for descriptive coverage. The optional balanced morning/afternoon sampling sensitivity uses five of them in June and August: each month gets half of each arm's weight, divided among that month's available passes. Three other June/August passes describe middle times; the July and September passes remain descriptive because they have no 2023 morning counterparts in 09:30–11:30 solar time. No file or result was deleted. This weighting is not a newly computed time contrast.

The complete 2023 catalogue has no July or September acquisition in that morning window, before quality screening. More observations from 2019/2024/2025 do not repair the missing 2023 combinations. A fully balanced June–September 2023 pattern therefore remains unsupported. Keep the exact 10:30-versus-late-afternoon research target distinct from a window-mean comparison; preserve the total time interpretation including associated solar geometry, with secondary geometry/season standardization only where supported.

The prior eighteen-pass/twelve-endpoint rebalancing package is a preserved exploratory multiyear result, not the controlling pilot specification. Its seven additional paired fits completed, but their point estimates remain sealed. Earlier authorized disclosures remain recorded. No new empirical time regression, scale-agreement ruling or professor approval is implied. Reza's tolerance, calibrated time inference, registration/common-cell checks and full-study season/product choices remain unresolved. The nineteen-city nonthermal screen and previous eleven-pass 2023 package remain available. Version stays 6.2.

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
