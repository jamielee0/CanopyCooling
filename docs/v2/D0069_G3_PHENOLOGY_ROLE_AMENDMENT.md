# D0069 — Gate 3 phenology-role amendment and second revision authorization

## Status and evidentiary timing

`FROZEN / USER-APPROVED REVISE RESULT / PRE-SECOND-AUGMENTATION RULE`

At `2026-08-13T19:57:15+09:00`, the user approved the *revision result* in
R0020 and selected the option `APPROVE REVISE RESULT AND AMEND PHENOLOGY
ROLE`. This does **not** approve Gate 3 or any sampling design. The instruction
was issued after inspecting only the historical nonthermal phenology and
archive evidence in R0020 and before the geometry, azimuth, cloud, exact-
weather, bounded-balance, or selector results authorized below were computed.

The instruction is bound to the immutable R0020 evidence that the human
reviewed:

- revised checks SHA-256: `3cd10249ef78a7e0f401dca81eaea7789f657ee2ba14c68253db0e04fb1f127f`
- revised review SHA-256: `9f1460ab817bb9ca8af133494f1d34c05468a615ff8e8134d434f5eeb36207ed`
- revised source bindings SHA-256: `aadb72f491debd7b4486f77c4d8c848d7517ceada75385895463b7ba39aa8828`
- Gate-3 module SHA-256: `f6177c997000f837eba5a6f91a188434590016b6e2a7d3a1612351215a9fdb25`
- archive runner SHA-256: `38216eadd8d62ee67d786ad750a485117a46d469cd6d883c0f66438a5a540135`
- revision runner SHA-256: `a780379366afa170405b0e218a6445dabc6f2e62226e63bfdb2ca3224e0aa22a`

No temperature/LST value, thermal outcome, holdout datum, or 2026 record had
been opened when this amendment was frozen.

## Amended phenology role

D0065's whole-city MOD13Q1.061 ranks-0-and-1 analysis remains the primary
phenology screen. The annual USFS-tree-canopy-masked ranks-0-and-1 analysis is
the required tree-relevant confirmation. A city-window is phenology-eligible
only when both analyses have complete coverage under their frozen rules and
both pass.

The whole-city QA-rank-0-only analysis remains mandatory and must always be
reported with its absolute NDVI values and year coverage, but it is a
sensitivity and is not an automatic veto. Its result must be classified as:

- `QA0_CONFIRMS` when every month has at least seven usable years and passes;
- `QA0_THRESHOLD_REVERSAL` when coverage is complete but a month fails the
  frozen NDVI threshold; or
- `QA0_INCOMPLETE_YEAR_COVERAGE` when any month has fewer than seven usable
  years.

The last two states return prominently in the review but do not by themselves
make the city-window ineligible. In the already inspected R0020 evidence,
Atlanta June–September is `QA0_INCOMPLETE_YEAR_COVERAGE` because June and July
have only six and three usable years, respectively. Phoenix April–May is the
genuine `QA0_THRESHOLD_REVERSAL`. The primary and canopy-confirmation screens
phenology-qualify exactly four nonexploratory windows for the next audit:

1. Atlanta, June–September;
2. Denver–Aurora, June–September;
3. Minneapolis–St. Paul, June–September; and
4. Phoenix, April–May.

Adding cities, promoting Miami, or changing a season is not authorized merely
to rescue support. June–September Phoenix and every other D0065 window remain
reported as sensitivities where required.

## Operational selector requirements

The selector must fail closed unless every candidate threshold supplies and
passes all of the following independent conditions; a true archive-completion
flag or a finite entropy/histogram value cannot substitute for any one of
them:

1. all D0065 city-window eligibility rules, including complete real geometry,
   view azimuth, relative sun–sensor azimuth, cloud, and exact-acquisition
   weather evidence;
2. at least four nonexploratory cities including Denver–Aurora;
3. no city above 40% of physical passes;
4. at least three 10–12 passes and three 16–18 passes in every primary
   city-window;
5. at least two high-demand/wet and two high-demand/dry passes in every
   primary city-window;
6. strictly positive within-city observed-range overlap in acquisition VPD
   between the high-demand/wet and high-demand/dry observations;
7. strictly positive within-city observed day-of-window range overlap between
   the high-demand/wet and high-demand/dry observations, so a pre-/post-season
   split cannot masquerade as wet/dry support;
8. complete pairwise range-overlap reporting for acquisition VPD, air
   temperature, and wind speed when supplied by the exact HRRR record; and
9. a calculated, not asserted, inaccessible-pass bound-invariance result.

Normalized Shannon entropy and all D0067 histogram-overlap coefficients must be
finite and reported, but remain diagnostics without invented cutoffs. The
selector iterates 10, 15, 20, and 25 degrees and chooses only the first
threshold whose complete boolean evidence passes. Missing or false AM/PM,
wet/dry, VPD-overlap, seasonal-overlap, weather-overlap, geometry, or bound
flags must prevent selection.

## Calculated inaccessible-pass bounds

For each primary threshold, the lower bound excludes every
`RESOLVED_UNAVAILABLE` pass. The upper bound adds each such pass once at its
known city, season, year, and local-solar time, assumes that it would qualify
the angle and cloud rules, and uses only its already sealed nonthermal demand
and wetness labels. Unknown azimuth or exact weather is never invented and the
upper construction is not labelled observed evidence.

Compute lower and upper city shares, city-year counts, AM/PM counts, and
high-demand wet/dry counts. Apply the same count and 40% rules at both ends.
The selected threshold is bound-invariant only when the smallest eligible
threshold is identical under both computed count-bound tables and the
four-city, city-share, AM/PM, and wet/dry conclusions agree. VPD/weather overlap
and geometry completeness remain gating on the observed accessible design;
they cannot be repaired by an unavailable pass.

## Authorized work and locks

The AI is authorized to correct and test the selector, phenology labelling,
bounded diagnostics, and test-suite recording; complete historical nonthermal
geometry, azimuth, cloud, and exact-weather augmentation for the four
phenology-eligible city-windows; rerun Gate 3; and issue a new checksum-bound
packet for human review.

Gate 3 itself remains unapproved. G3A, Gate 4+, Task 2, holdout selection/data,
temperature/LST, thermal outcomes, and every 2026 query or record remain
locked. The new run must stop for human review even if a design is selected.
