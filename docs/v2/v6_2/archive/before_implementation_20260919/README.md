# Urban tree cooling v6.2 active workspace

The current study asks how canopy-associated surface cooling varies with satellite observation time and whether a fixed 10:30 observation represents later-day cooling. The September meeting and subsequent radiance email amend v6.2 in place.

## Current documents

- `docs/v2/v6_2/protocol_v6_2.yml` is the machine-readable specification.
- `docs/v2/v6_2/pilot_plan_v6_2.md` documents the full pilot and exact transformation procedure.
- `docs/v2/v6_2/implementation_plan_v6_2.md` lists the code and verification work still to do.
- `docs/v2/v6_2/decision_log_v6_2.md` records current changes and preserves earlier history.
- `references/` contains the updated proposal, working guide, schedule and next steps, with original meeting/email sources under `references/sources/`.

## Current design and status

Fit one canopy slope per city-pass using native ECOSTRESS cells, block-specific intercepts and a shared within-block canopy term. Run matched temperature and emitted-energy models. Remove the per-block 0.20/0.10 canopy-span gates; freeze pass-level information and contributing-block thresholds from nonthermal distributions.

The pilot uses the five frozen Phoenix passes and five equivalent passes from Atlanta or Charlotte, selected for greater canopy heterogeneity before thermal download. Los Angeles belongs to the later expansion. VPD is descriptive only; the HLS/SWIR condition hypothesis is deferred. Keep both the total observation-time pattern and a secondary geometry/season-standardized pattern.

Point estimates remain sealed through the precision review. Scale agreement is evaluated only after a documented release. Full-city scaling is paused pending pilot review. The updated documents do not imply that the new code or pilot has run. Existing `src/run_v6_2_*` files are historical implementations until amended and verified.

## Preserved history and data

Earlier result packages under `deliverables/` are immutable historical evidence. Their thresholds and stop decisions apply to the old design. The pre-update active documents are preserved under `docs/v2/v6_2/archive/before_meeting_update_20260919/`.

The original data tree is now located at `/Users/jmlee/Documents/Documents - Jamie’s Mac mini/TreeProject/project/data`. The existing `data` symlink still names the earlier `/Users/jmlee/Documents/TreeProject/project/data` path; verify or repair it before future execution. This documentation update does not move data.
