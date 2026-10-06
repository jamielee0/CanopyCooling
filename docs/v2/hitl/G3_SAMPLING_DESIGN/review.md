# Gate 3 review — prospective sampling design

## Decision

`REVISE_REQUIRED`

No primary city set, season window, or view-zenith threshold is selected. The frozen Gate-3
rules were applied without opening temperature/LST values or querying any 2026 record, but
the evidence chain is not yet complete enough to choose a prospective design.

## What this gate completed

- Bound official 2020 Census Urban Area domains for all seven candidates, including
  Denver–Aurora (`23527`) and Sacramento (`77068`), with source and analysis checksums.
- Retrieved and QA-screened historical `MOD13Q1.061` NDVI for April–October 2018–2025 and
  applied the pre-result stable-leaf-on rule. Passing city/window combinations: **atlanta/jun_sep, minneapolis_st_paul/jun_sep, denver_aurora/jun_sep, phoenix/phoenix_apr_may**.
- Rebuilt the candidate-day GridMET reference through the required preceding 60-day windows.
- Audited historical metadata ceilings for Denver, Sacramento, Phoenix April–May, and
  California October. Intersecting physical-overpass counts and their 10–18 local-solar
  daytime subsets are: **denver_aurora/jun_sep: 655 all / 229 daytime, los_angeles/california_october: 144 all / 60 daytime, phoenix/phoenix_apr_may: 225 all / 71 daytime, sacramento/california_october: 167 all / 73 daytime, sacramento/jun_sep: 685 all / 228 daytime**.
- Ran the existing five-city June–September geometry evidence through 10°, 15°, 20°, 25°,
  and exploratory 30° thresholds. Counts are **10°: 40, 15°: 127, 20°: 219, 25°: 326, 30°: 413** physical passes.

The daytime metadata ceilings are not usable-pass counts. They precede L1B coverage/angle,
view-azimuth, cloud, and exact-acquisition HRRR checks.

## Why Gate 3 cannot be approved as a selected design

1. Denver, Sacramento, and every shoulder-season addition still lack the frozen full-domain
   L1B geometry and cloud-quality audit.
2. Pass-level `view_azimuth` and relative sun–sensor azimuth have not been mapped for any
   candidate threshold. The official L1B arrays exist, but the prior pipeline read only
   latitude, longitude, and view zenith.
3. The 25° and 30° additions in the inherited panel lack complete cloud and exact-acquisition
   HRRR evidence, so their joint demand/wetness distributions are unresolved.
4. Gate 1's 31 archive-unavailable candidates remain unresolved. Under D0065 they remain in
   the denominator and prevent a claim of fully resolved observation accounting.

At the inherited 20° threshold: **atlanta: archive unresolved=8, azimuth=False, eligible=False; los_angeles: archive unresolved=8, azimuth=False, eligible=False; miami: archive unresolved=1, azimuth=False, eligible=False; minneapolis_st_paul: archive unresolved=8, azimuth=False, eligible=False; phoenix: archive unresolved=6, azimuth=False, eligible=False**.

## Efficient revision path

Keep D0065 unchanged and run one bounded nonthermal augmentation:

1. seal L1B identities and full-domain view geometry for the candidate additions;
2. map `view_azimuth` and `solar_azimuth` on the same target cells for every threshold
   candidate;
3. complete cloud and exact-acquisition HRRR only for newly geometry-qualified passes;
4. recheck the 31 historical archive exclusions without using an unbounded search; and
5. rerun the same eligibility rules once.

No threshold should be chosen from the current count chart. A 20° rule remains only the
inherited comparator, not a Gate-3 selection.

## Locks and next action

- Sampling design: `UNSELECTED`
- G3A tree/reference-yield checkpoint: `LOCKED`
- Gate 4 and later gates: `LOCKED`
- Holdout: `UNSELECTED`
- Temperature/LST and thermal outcomes: `UNOPENED`
- 2026 metadata/science query: `NOT PERFORMED AT G3`

Human options:

- `REVISE G3: run the bounded nonthermal augmentation` — complete the missing evidence
  under D0065 and return a revised Gate-3 packet.
- `STOP` — preserve this identifiability/data-completeness result and end the amended
  workflow.
