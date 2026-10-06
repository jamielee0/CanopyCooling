# Gate 1 review — Revised complete observation reconciliation

**Gate status:** `REVISED_AWAITING_HUMAN_APPROVAL_WITH_RECORDED_PROTOCOL_DEVIATIONS`  
**Authorized by:** `D0059`; deviations recorded by `D0060` and `D0061`  
**Next gate remains locked:** `G2`

## Important protocol disclosure

Gate 1 does **not** claim clean compliance with the approved 2026 freeze. Two public CMR
metadata exposures occurred: the original 2026 positive-control query and a later unbounded
wildcard query that matched text inside 2026 timestamps. No science-data link or
temperature/LST value was opened, and neither response contributes to any count or
conclusion. The events and containment are preserved in D0060 and D0061.

## Bottom line

The complete nonthermal chain now reconciles without changing the frozen data rules:

`13,577 tiled records → 13,575 selected revisions → 2,968 physical city–orbit observations
→ 1,055 daytime → 1,017 geolocation-usable → 942 metadata candidates → 911 archive-available
→ 219 geometry/cloud-complete physical passes → 102 early/late-stratum-eligible individual
physical passes prior to empirical matching`.

The 219 retained physical passes carry **159.087084 pass-equivalents**, and the 102
early/late-stratum-eligible passes carry **72.689029**. Those weighted values are secondary
clear-domain exposure diagnostics, not outcome-reliability weights or independent sample
sizes. The
102 are not 102 matched morning–afternoon pairs.

## Four requested review items

1. **Attrition:** every one of the 2,968 observations has a mutually exclusive final status;
   the long breakdown covers city, year, month, and time stratum.
2. **Formula:** `w_i = clear domain pixels / domain pixels`; physical counts are reported
   next to every weighted sum.
3. **Applied view rule:** L1B-GEO valid-domain coverage ≥ 0.95 and pass-level p95 absolute
   view zenith ≤ 20°.
4. **Within-city wet/dry support:** all nine demand × dryness cells are present as explicit
   rows for each city and overall, including zeros and both full-retained and early/late
   eligibility counts prior to matching.

## What the reconciliation changes in our understanding

- The **413** HRRR number is fully explained: 438 floor/ceiling pass–hour links for 219
  fractional-hour acquisitions collapse to 413 unique assets because 25 hours are shared
  across two cities. It is not a pass count.
- The retained low-demand/dry corner has **8 physical passes** but only
  **0.552699 pass-equivalents**. Cloud weighting therefore describes
  poor usable exposure; it must not erase the distinction between eight atmospheric events
  and roughly half a clear-domain equivalent.
- Of the 31 archive-unavailable candidates, **2** fall in that same corner
  under a clearly labelled daily Step-1 proxy. The item remains
  **`OPEN_WITH_PROXY_EVIDENCE`**: definitive acquisition-time membership, geometry, and
  cloud outcomes are unknown. If both eventually passed geometry, the physical candidate
  ceiling would rise from 8 to 10, but recovery is not demonstrated to
  restore support.
- Collection 3 has the correct tiled view/cloud variables and fill semantics in principle,
  but current CMR results contain no historical 2020 or 2024 granules for these candidates.
  Reprocessing should be checked again at G3. Current recovered count: **0**.

## Explicit limitations

- `usable_tree_pixels` and `usable_reference_pixels` are not available yet. They remain
  blank with an explicit status, never zero-filled. The mandatory named
  `G3A_NONTHERMAL_TREE_REFERENCE_YIELD` checkpoint will compute pre-outcome eligible counts
  without opening a temperature/LST value after G3 freezes the design and before G4/G5/G7.
- The missing-31 condition classification uses a daily proxy, not exact-acquisition HRRR.
- The Collection 3 finding is a timestamped current-availability audit, not a permanent
  archive claim.

## Data-access state

No ECOSTRESS temperature/LST value, thermal outcome, holdout result, or 2026 science value
was opened. However, 2026 **metadata were queried**, as disclosed above; the packet does not
label the 2026 record wholly unopened. R0015 and R0016 remain STOP, Task 2 remains disabled,
and the holdout remains `UNSELECTED`.

## Files to review

1. `attrition_summary.csv` — compact complete chain and count units.
2. `observation_ledger.csv` — all 2,968 physical observations and final statuses.
3. `within_city_wet_dry_support.csv` — raw and weighted support for every city/cell.
4. `pass_quality_219.csv` — per-pass geometry, cloud counts, weights, and support cells.
5. `hrrr_pass_hour_crosswalk.csv` — the 438-to-413 weather reconciliation.
6. `archive_missing_31_audit.csv` — candidate-level proxy audit and unknown-outcome flags.
7. `G3A_nonthermal_tree_reference_yield_checkpoint.md` — mandatory later count checkpoint.
8. `source_evidence/cmr_collection3_historical_summer_2020.json` and the corresponding 2024
   file — preserved raw historical CMR response bodies.
9. `revision_response.md`, `method_notes.md`, and `checks.json` — revisions, definitions,
   limitations, hashes, and assertions.

## Your decision

- `APPROVE G1` — bind this reconciliation and authorize G2 nonthermal hydroclimatic support only.
- `REVISE G1: <change>` — revise this package; do not begin G2.
- `STOP` — preserve all current locks and do not continue.
