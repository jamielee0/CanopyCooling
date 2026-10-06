# Urban tree cooling v6.2 active workspace

The current study asks how canopy-associated surface cooling varies with satellite observation time and whether a fixed 10:30 observation represents later-day cooling. The September meeting and subsequent radiance email amend v6.2 in place.

## Current documents

- `docs/v2/v6_2/protocol_v6_2.yml` is the machine-readable specification.
- `docs/v2/v6_2/pilot_plan_v6_2.md` documents the full pilot and exact transformation procedure.
- `docs/v2/v6_2/implementation_plan_v6_2.md` records completed implementation, run commands and remaining review decisions.
- `docs/v2/v6_2/decision_log_v6_2.md` records current changes and preserves earlier history.
- `references/` contains the updated proposal, working guide, schedule and next steps, with original meeting/email sources under `references/sources/`.

## Current design and status

Fit one canopy slope per city-pass using native ECOSTRESS cells, block-specific intercepts and a shared within-block canopy term. Run matched temperature and emitted-energy models. Remove the per-block 0.20/0.10 canopy-span gates; report pass-level information, contributing-block distributions and information concentration without an arbitrary replacement gate.

The pilot retains Phoenix orbits 27963, 28024, 28706, 28828 and 28909 and selects Atlanta orbits 27835, 27896, 27916, 28145 and 28598. A seeded 300-block nonthermal Science TCC screen found within-block variance of 0.00159 in Phoenix, 0.08301 in Atlanta and 0.07189 in Charlotte. Atlanta also has verified afternoon acquisitions. Its five passes were frozen before thermal download from the existing geometry-verified 2023 June–September inventory.

The pooled estimator, paired emitted-energy model, spatial checks and scale-diagnostic workflow are implemented. The limited Phoenix–Atlanta pilot is authorized and its empirical outputs remain sealed. The meeting package records completed run status and precision. Full-city scaling remains paused until review. Coefficient sealing remains in force for precision review. Reza’s numerical scale-agreement tolerance remains pending. Compute and store paired contrasts without displaying them; do not issue an agreement ruling until the tolerance is prospectively recorded and coefficient release is authorized. Treat an exactly zero contrast as direction unresolved. The full-study power design and Collection 3 historical coverage decision remain for the post-pilot review.

## Preserved history and data

Earlier result packages under `deliverables/` are immutable historical evidence. Their thresholds and stop decisions apply to the old design. The pre-update active documents are preserved under `docs/v2/v6_2/archive/before_meeting_update_20260919/`.

The data symlink has been repaired and verified against the relocated original data tree. Raw files and historical result packages remain preserved. New pilot inputs are under data/raw/v2/pilot_v6_2_20260919/.
