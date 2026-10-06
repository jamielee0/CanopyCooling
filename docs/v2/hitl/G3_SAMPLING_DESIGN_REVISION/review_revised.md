# Gate 3 revised review — prospective sampling design

## Decision

`REVISE_REQUIRED — NO PRIMARY DESIGN IDENTIFIABLE UNDER D0067`

The requested revision was run without opening temperature/LST, thermal outcomes,
holdout data, or any 2026 record. The amended pre-result rule now fails before a
view-zenith threshold can be selected: only **2** nonexploratory
cities remain stable across the primary, QA-rank-0-only, and canopy-masked
phenology analyses, versus the frozen minimum of four including Denver.

## Phenology reconciliation

- Whole-city QA ranks 0+1 pass: **atlanta/jun_sep, denver_aurora/jun_sep, minneapolis_st_paul/jun_sep, phoenix/phoenix_apr_may**.
- Whole-city QA rank 0 only pass: **denver_aurora/jun_sep, minneapolis_st_paul/jun_sep**.
- Canopy-masked QA ranks 0+1 pass: **atlanta/jun_sep, denver_aurora/jun_sep, minneapolis_st_paul/jun_sep, phoenix/jun_sep, phoenix/phoenix_apr_may**.
- Stable in all three analyses: **denver_aurora/jun_sep, minneapolis_st_paul/jun_sep**.
- Usable composite counts are **662/742**
  for the primary analysis, **493/742**
  for QA rank 0 only, and **680/742**
  for the canopy-masked sensitivity.

Atlanta June–September and Phoenix April–May pass the primary city-level screen
but reverse under QA rank 0 only. Their canopy-masked results remain stable. Under
the frozen D0067 fail-closed rule they are `PHENOLOGY_SENSITIVE` and cannot be
auto-selected.

Phoenix's canopy-mask coverage is reported explicitly: its median retained
MODIS-cell fraction is **0.011**.
The canopy result is therefore informative but spatially sparse and is not being
presented as a whole-city tree-health estimate.

## Inaccessible-pass resolution

The finite one-query/one-access-attempt recheck completed for all 31 historical
passes. Pass classifications: **{"RESOLVED_UNAVAILABLE": 31}**.
There were **0** unresolved query
errors; version-003 L1B was not queried because the official collection does not
exist. Lower/upper contributions are retained in
`archive_pass_bounded_recheck_and_bounds.csv` rather than silently dropping these
passes.

## Selector and balance diagnostics

The selector is no longer hard-coded to fail. Its successful known-answer test
selects 15° after rejecting 10°, and fail-closed tests cover phenotype reversal,
archive-bound failure, city share, missing balance evidence, and azimuth helpers.
Test status: **PASS**.
The complete regression run also passed: **37 v2 test programs and 17 legacy
test programs**.

The revised real-data selector still returns `REVISE_REQUIRED`. City-share,
entropy, AM/PM, wet/dry, and continuous-overlap diagnostics are implemented but
correctly marked not computable: with only two sensitivity-stable cities, no
threshold can meet the four-city rule. Completing thousands of new geometry,
cloud, and HRRR reads cannot change that upstream result. Those reads were
therefore not launched, and the packet does not mislabel metadata ceilings as
usable observations.

## What remains unresolved

The requested azimuth/cloud/exact-weather augmentation is not complete. This is
now a downstream evidence gap rather than the reason no design was selected. It
should be run only after the human chooses one of the following pre-result design
amendments:

1. keep QA-rank-0 and canopy results as reported sensitivities but remove automatic
   disqualification on a QA-0 reversal; or
2. retain D0067's strict confirmation rule and add enough predeclared candidate
   cities to restore at least four sensitivity-stable cities.

No larger angle threshold, Miami promotion, or favourable count can override the
current frozen four-city phenology failure.

## Locks

- Sampling design: `UNSELECTED`
- G3A: `LOCKED`
- Gate 4+: `LOCKED`
- Holdout: `UNSELECTED / UNOPENED`
- Temperature/LST and thermal outcomes: `UNOPENED`
- 2026 query or record: `NOT PERFORMED`

Human options: `APPROVE REVISE RESULT AND AMEND PHENOLOGY ROLE`, `ADD CANDIDATE
CITIES UNDER A NEW PRE-RESULT RULE`, or `STOP`.
