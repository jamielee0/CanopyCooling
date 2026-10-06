# D0065 — Gate 3 pre-result sampling-design rules

## Status

`FROZEN / PRE-RESULT G3 RULE`

These rules were fixed after the user's Gate-2 approval and before computing any new
Gate-3 support, phenology, or angle-threshold result. No temperature/LST value, cooling
outcome, holdout result, or 2026 record may be opened.

## Candidate cities and roles

- The inherited candidates are Phoenix, Los Angeles, Atlanta, Minneapolis–St. Paul, and
  Miami, using their already frozen 2020 Census Urban Area domains.
- Denver–Aurora, Colorado (2020 Urban Area GEOID `23527`) is the default semi-arid
  continental candidate required by the Gate-0 amendment.
- Sacramento, California (2020 Urban Area GEOID `77068`) is a seasonal comparator used to
  test whether a California October extension adds a meaningfully different, comparable
  support region.
- Miami entered v2 under D0003 as a deliberately strongly humid case beyond the legacy
  four-city direction. It is exploratory in Gate 3: it cannot displace Denver merely by
  increasing the pooled count. Promotion to a different role requires an explicit Gate-3
  human approval.

Denver and Sacramento domains must be obtained from the corrected/current 2020 Census
Urban Area source, simplified and rasterized using the same rules as the five frozen
domains, and assigned source and analysis-geometry checksums before they contribute any
result.

Official domain sources:

- https://www.census.gov/programs-surveys/geography/guidance/geo-areas/urban-rural.html
- https://tigerweb.geo.census.gov/tigerwebmain/Files/bas26/tigerweb_bas26_ua_2020_tab20_us.html

## Candidate seasons and antecedent inputs

- Every candidate city is audited for the existing June 1–September 30 window in each of
  2018–2025.
- Phoenix additionally receives an April 1–May 31 shoulder candidate.
- Los Angeles and Sacramento additionally receive an October 1–31 shoulder candidate.
- April calculations must have daily inputs from at least January 31; October calculations
  must have daily inputs from at least August 2. Every 30- or 60-day window ends on the day
  before the focal local-solar date.
- Thirty-day accumulated precipitation is the candidate primary wetness variable. Sixty-day
  accumulated precipitation is a window sensitivity; days since at least 5 mm rain is a
  right-censored diagnostic; `P - ET0` is sensitivity-only. Gate-2 definitions and
  interpretive limits remain binding.
- June–September is always retained and reported as a sensitivity, even when a city's
  optical leaf-on rule fails.

## Frozen optical leaf-on rule

The primary optical evidence is Terra MODIS `MOD13Q1.061`, a 16-day 250 m vegetation-index
product. NDVI uses scale factor `0.0001`. Primary summaries retain pixel-reliability ranks
0 (good) and 1 (marginal); rank 0 alone is a sensitivity. Fill, snow/ice, and cloudy pixels
are excluded.

For each city, composite, and frozen analysis domain, compute the median QA-valid NDVI and
the valid-pixel fraction. A composite is usable only when at least 50% of in-domain MODIS
pixels are valid. For each city-year-month, take the median of usable composite medians.
Define the city-specific peak as the maximum, over April–October, of the 2018–2025 median
monthly NDVI. A calendar month is `STABLE_LEAF_ON` only when:

1. at least seven of eight years have a usable monthly value;
2. its eight-year median NDVI is at least 90% of that city-specific peak; and
3. its across-year first quartile is at least 80% of that peak.

A primary candidate window passes phenology only if every calendar month in the window is
`STABLE_LEAF_ON`. The absolute NDVI values and year coverage must be reported so this
relative rule cannot disguise sparse or nonvegetated support. NDVI is phenological evidence,
not a tree-health or irrigation outcome.

Official product definitions:

- https://lpdaac.usgs.gov/documents/621/MOD13_User_Guide_V61.pdf
- https://lpdaac.usgs.gov/documents/103/MOD13_User_Guide_V6.pdf

## Frozen observation and geometry rules

- Candidate observations are unique city–orbit physical overpasses from `ECO_L1B_GEO.002`
  during the frozen windows and years. Tiled products never count as separate physical
  passes.
- Daytime strata remain 10–12, 12–14, 14–16, and 16–18 apparent local-solar hours; the
  later time-design audit focuses on 10–12 versus 16–18.
- A pass must have at least 95% frozen-domain coverage by cloud-independent L1B geometry.
- Run pass-level 95th-percentile absolute view-zenith thresholds 10°, 15°, 20°, and 25°.
  Report 30° separately as exploratory; it is not eligible to become primary at this gate.
- Use the L1B GEO `view_azimuth` and `solar_azimuth` arrays in degrees over the same mapped
  domain cells used for view zenith. Summarize each with a circular mean and circular
  concentration. Define relative sun–sensor azimuth as the smallest absolute circular
  difference, in `[0°, 180°]`, for each mapped cell and report its pass-level median and
  interquartile range.
- Missing azimuth, weather, cloud, archive, or provenance information is an explicit
  unresolved observation and is never silently dropped from a denominator.

Official geometry definitions:

- https://ecostress.jpl.nasa.gov/downloads/psd/ECOSTRESS_SDS_PSD_L1.pdf
- https://lpdaac.usgs.gov/documents/1491/ECO1B_User_Guide_V2.pdf

## Frozen support and selection rules

For every threshold, report raw physical counts and clear-domain pass-equivalents beside
joint city, season, year, time-stratum, acquisition-VPD, 30-day precipitation, view-zenith,
view-azimuth, and relative-azimuth summaries. Demand is high when acquisition-time VPD is in
the upper city-season tercile of the full candidate-day reference distribution; wet and dry
are the upper and lower city-season terciles of 30-day precipitation. Terciles are descriptive
support labels; raw continuous variables govern overlap checks.

A city-window is eligible for a proposed pooled primary design only if it:

1. passes the frozen phenology rule;
2. has fully resolved observation accounting and at least one qualifying physical pass in
   at least four of the eight years;
3. has at least three qualifying physical passes in each of the 10–12 and 16–18 strata;
4. has at least two high-demand/wet and two high-demand/dry qualifying physical passes;
5. has a strictly positive observed range overlap in absolute acquisition-time VPD between
   its high-demand wet and dry observations; and
6. has complete pass-level view azimuth and relative-azimuth summaries.

For the prospective primary city set at a candidate threshold, no single city may supply
more than 40% of physical passes. Report normalized Shannon entropy across city × time
stratum × demand × wetness cells and histogram-overlap coefficients for continuous demand,
wetness, view zenith, and relative azimuth. These are comparability diagnostics, not a
weighted score that can trade away a failed eligibility rule.

Select the smallest threshold among 10°, 15°, 20°, and 25° that satisfies every eligibility
rule for all proposed primary city-windows. If none qualifies, Gate 3 returns
`REVISE_REQUIRED` and does not invent a threshold. A larger count, Miami's inclusion, a
shoulder extension, or Sacramento's inclusion cannot override a failed phenology,
within-city-support, completeness, or geometry-comparability rule.

## Mandatory G3A checkpoint and locks

After a design is selected but before Gate 4, G5, or G7, run the separately named
`G3A_NONTHERMAL_TREE_REFERENCE_YIELD` checkpoint already assigned at Gate 1. For every
selected pass it must report pre-outcome eligible tree pixels, eligible reference pixels,
and nonthermal matching yield. G3A is not authorized until the Gate-3 design packet has
been approved by the human.

Gate 3 must stop for review. Gate 4+, Task 2, G3A execution, holdout selection,
temperature/LST access, thermal outcomes, and every 2026 query or record remain locked.
