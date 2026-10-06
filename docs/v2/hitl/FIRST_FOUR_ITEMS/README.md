# First four items requested by the feedback

**Status:** delivered and independently verified before any further pipeline work  
**Evidence boundary:** historical nonthermal metadata and predictor evidence only  
**Current action:** D0069 augmentation paused; Gate 3 and all downstream gates remain unapproved

## 1. Attrition and raw pass counts

The complete table is `01_attrition_table.csv`. The key count chain is 13,577
raw tiled products → 13,575 latest revisions → 2,968 unique physical
city–orbit observations → 1,055 daytime observations → 942 after
metadata/obstruction screening → 911 archive-available before geometry → 219
under the historical 20° rule → 102 individual early/late-stratum-eligible
passes before empirical matching.

The 102 are individual passes, not 102 AM–PM pairs. The 413 HRRR timestamps are
weather assets: 219 passes require 438 bracketing pass-hour links, with 25
hours shared across cities, leaving 413 unique assets.

## 2. Pass-equivalent formula

The exact formula and interpretation are in `02_pass_equivalent_formula.md`.
Raw physical pass counts are primary. The 159.087 and 72.689 weighted sums are
secondary clear-domain exposure diagnostics; they are not independent sample
sizes. Tree/reference pixel yields remain explicitly unavailable rather than
being treated as zero.

## 3. View-angle threshold results

The complete comparison is `03_view_angle_threshold_results.csv`.

| Pass-level p95 limit | Raw physical passes | Role/status |
|---:|---:|---|
| 10° | 40 | confirmatory candidate; not selected |
| 15° | 127 | confirmatory candidate; not selected |
| 20° | 219 | historical applied comparator; not a final prospective selection |
| 25° | 326 | candidate; addition evidence incomplete |
| 30° | 413 | exploratory only |

Every row uses at least 95% domain geometry coverage and pass-level p95
absolute view zenith at or below the stated limit. Azimuth evidence is not
complete in this frozen comparison, so no prospective primary threshold is
claimed.

## 4. Within-city high-demand wet/dry support

The complete city breakdown is `04_within_city_high_demand_support.csv`.
Using the 30-day precipitation candidate, the inherited five-city panel has 40
high-demand/wet and 62 high-demand/dry physical passes. Every listed city has
both groups, but that alone does not establish pooled comparability.

For the original 30-day `P - ET0` sensitivity, the feedback's 34 wet + 53
middle + 68 dry = 155 high-demand physical passes is reproduced exactly.
`P - ET0` remains sensitivity-only because it partly contains atmospheric
demand. These counts do not establish a pooled effect; absolute-VPD,
day-of-year, city, azimuth, and weather overlap remain prospective gates.

Miami is retained here only because these are the inherited-panel counts being
audited. It is exploratory in the amended protocol. Denver is part of the
prospective sampling-design audit, not retroactively inserted into these
historical five-city totals.

## Independent verification

`independent_verification.json` recomputes all headline counts, sums, formulas,
within-city additivity, and source hashes directly from the sealed CSVs. The
verifier is network-free and imports no pipeline module.

The project does not claim that the 2026 metadata seal was perfect. D0060,
D0061, D0073, and D0074 remain disclosed. No 2026 science data, raster values,
thermal/LST values, city result, or holdout result was opened or used.
