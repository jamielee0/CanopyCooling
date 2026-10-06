# D0067 — Gate 3 revision pre-result rules

## Status and relationship to D0065

`FROZEN / PRE-AUGMENTATION G3 RULE`

D0065 remains binding. This outcome-blind amendment was written after the
initial nonthermal Gate-3 support audit, in direct response to the human's
revision verdict, and before opening any newly augmented geometry, azimuth,
cloud, exact-weather, archive-recheck, QA-rank-0, or canopy-masked result. It
cannot loosen a D0065 eligibility rule.

## Phenology sensitivities

Retain D0065's whole-domain MOD13Q1.061 ranks-0-and-1 screen as the primary
phenology screen. Produce two required sensitivities using the same dates,
scale factor, 50% usable-composite rule, seven-of-eight-year coverage rule, and
90% median/80% first-quartile peak rules:

1. whole-domain MOD13Q1.061 with `SummaryQA == 0` only; and
2. MOD13Q1.061 ranks 0+1 restricted to MODIS cells whose annual mean tree-canopy
   cover is at least 10%, using the official annual 30 m USFS Tree Canopy Cover
   `NLCD_Percent_Tree_Canopy_Cover` band aggregated by mean to the MODIS grid.

The canopy year must match the MODIS composite year and may not exceed 2025.
Report the retained MODIS-cell fraction and the absolute NDVI values. A
city-window that passes the primary screen but lacks complete sensitivity
coverage, or whose stable-leaf-on status is reversed by either sensitivity, is
`PHENOLOGY_SENSITIVE` and cannot be auto-selected; it returns for human review.

Official source definitions:

- https://lpdaac.usgs.gov/documents/621/MOD13_User_Guide_V61.pdf
- https://developers.google.com/earth-engine/datasets/catalog/projects_gtac-data-publish_assets_TCC_Product_Version_2025-6
- https://data.fs.usda.gov/geodata/rastergateway/treecanopycover/

## Bounded inaccessible-pass resolution

Recheck each of the 31 exact historical candidates once, using only its sealed
city, acquisition date, orbit, scene, and the version-002 and version-003 L1B
GEO identities. The finite budget is one date-bounded CMR identity query per
collection version and, when an exact asset is returned, one range-read access
attempt after a passing control request. No expanding date, orbit, scene, city,
or collection search is permitted.

Classify each candidate as exactly one of:

- `RECOVERED`: exact identity and required nonthermal geometry arrays were read;
- `RESOLVED_UNAVAILABLE`: no exact identity is present, or the exact asset remains
  inaccessible after the bounded attempt; or
- `UNRESOLVED_ERROR`: the bounded query itself failed or identity matching is
  ambiguous.

`RESOLVED_UNAVAILABLE` closes observation accounting but contributes no observed
pass. `UNRESOLVED_ERROR` fails the gate. For every threshold, report partial-
identification bounds: the lower bound treats resolved-unavailable passes as
nonqualifying; the upper bound treats every such pass as angle-qualified with
unit clear weight, while preserving its known city, year, and time stratum.
Unknown azimuth is never imputed into the observed design. Auto-selection is
allowed only when the chosen threshold, four-city minimum, city-share cap, and
required AM/PM and wet/dry support conclusions are unchanged across the two
bounds.

## Geometry, cloud, and exact-weather completion

For every accessible candidate in every declared city-window, use the same
frozen-domain cells for L1B coverage, absolute view zenith, view azimuth, solar
azimuth, and relative sun–sensor azimuth. Circular means and concentrations and
relative-azimuth median/IQR follow D0065. An accessible candidate with any
missing required geometry field is unresolved and fails auto-selection.

Cloud and exact-acquisition HRRR processing is required for every accessible
pass that qualifies at any primary threshold. Reuse is permitted only when the
stored artifact's source identity, target-domain hash, algorithm hash, and
output checksum match. A threshold may not borrow a cloud or weather proxy from
another pass.

## Automatic city-window and threshold selection

Candidate primary city-windows are all non-Miami windows declared in D0065.
Miami remains exploratory and cannot supply the four-city minimum or repair a
failed balance rule. A city-window is auto-eligible only when it passes every
D0065 rule and is stable under both phenology sensitivities above. The
prospective primary design contains every auto-eligible city-window; it must
cover at least four unique cities and include Denver–Aurora. If more than one
window for a city is auto-eligible, keep both in the diagnostics but count the
city only once toward the four-city minimum.

For each threshold, compute the following before selection:

- physical-pass count and clear-domain pass-equivalents by city-window;
- maximum city share, which must be at most 40% using physical passes;
- observed and bounded AM (10–12) and PM (16–18) support;
- observed and bounded high-demand/wet and high-demand/dry support;
- normalized Shannon entropy over occupied
  city × time-stratum × demand × wetness cells;
- pairwise histogram-overlap coefficients for acquisition VPD, 30-day
  precipitation, absolute view zenith, and relative azimuth; and
- pairwise observed-range overlap for acquisition VPD, air temperature, and
  wind speed wherever exact HRRR provides those quantities.

Entropy and histogram overlap are diagnostics, not compensating scores. They
must be finite and fully reported but have no invented post-result cutoff.
D0065's positive within-city VPD overlap and all count/support rules remain
gating.

The selector must iterate 10°, 15°, 20°, then 25° and choose the first threshold
at which all rules pass and the same choice is identified at both inaccessible-
pass bounds. A successful-selection known-answer test and fail-closed tests for
missing azimuth, unresolved archive errors, phenotype reversal, city share, and
support are required. If no threshold passes, return `REVISE_REQUIRED` with
rule-level reasons. The exploratory 30° result can be reported but never chosen.

## Locks and stopping rule

The revised run may open only nonthermal historical data through 2025. It must
emit a new, checksum-bound Gate-3 revision packet and stop for human review.
G3A, Gate 4+, holdout selection/data, temperature/LST, thermal outcomes, and all
2026 queries/records remain locked.
