# Proposed outcome-blind protocol amendment

**Study:** Urban Tree Cooling v2  
**Prepared:** 2026-08-12 (Asia/Seoul)  
**Gate:** G0 — Freeze and amendment  
**Status:** `PROPOSED_AWAITING_USER_APPROVAL`  
**Feedback source:** `/Users/jmlee/Downloads/Urban_Tree_Cooling_feedbackdocx.docx`  
**Feedback source SHA-256:** `4d369a5337a20b2969d4c1ccabb528c56fae9eb19061c72513d301658dc79333`

This amendment is prospective and outcome-blind. It does not activate a new analysis,
supersede an existing STOP, select a holdout, or authorize access to an ECOSTRESS LST or
other thermal outcome. It becomes the working protocol only after the user explicitly
approves Gate 0.

## 1. Evidence and decisions that remain immutable

1. **R0015 remains the canonical demand-by-antecedent-wetness support result.** Its
   `STOP` is preserved. The low-demand/dry corner has 0.553 expected pass-equivalents
   against the earlier minimum of 10; the high-demand/wet corner has 26.168. No later
   analysis may relabel that profile as a PASS.
2. **R0016 remains the canonical D0056 time-of-day simulation result.** Its
   `STOP_TIME_OF_DAY_ONLY_STEP3` is preserved. Full-panel power for the frozen 1.50 K
   contrast was 0.110, every permitted leave-one-city-out branch failed the 0.80 power
   target, and the pooled null-rejection check failed.
3. **D0057 remains a prepared contract that was never activated.** It did not authorize
   Task 2, a holdout choice, thermal access, or 2026 access.
4. **No new result is retroactively inserted into R0015 or R0016.** Any approved work
   receives a new decision ID, run ID, configuration hash, output namespace, and audit
   trail.
5. **The archive-available estimand remains explicit.** The original 942-candidate
   exhaustive census and the D0047 archive-available profile are not silently merged.
   Restored or newly recoverable observations are reported as a named sensitivity or a
   new prospective profile.

## 2. Freeze in force during Gates G0–G7

Until a later gate explicitly authorizes otherwise:

- do not open, download, inspect, summarize, or model an ECOSTRESS LST/temperature
  layer or any derived empirical cooling outcome;
- do not open or query the 2026 record;
- keep the confirmatory holdout `UNSELECTED` and do not compute a holdout thermal result;
- do not develop downstream empirical Steps 4–14; only governance, nonthermal support,
  clean-room verification, and preregistered simulation work are allowed;
- do not tune cities, seasons, wetness definitions, view-angle filters, matching rules,
  effects, thresholds, or simulation diagnostics after seeing a thermal result;
- do not weaken R0015 or R0016 acceptance criteria to make an earlier stopped profile pass;
- do not present pass-equivalents as the number of independent atmospheric situations;
- do not describe the time comparison as a diurnal course, hysteresis, or physiological
  response.

The repository's active time-of-day Task-2 configuration is fail-closed under D0058:
`result_bearing_actions_enabled=false`, `holdout_status=UNSELECTED`, and both the held-out
thermal record and 2026 are `UNOPENED`.

## 3. Synthetic-output quarantine

All synthetic, simulated, or illustrative material must satisfy all of these rules:

1. Write only below an `illustrative_only/`, `synthetic/`, or `fixtures/` directory.
2. Begin every user-facing synthetic filename with `SYNTHETIC_` or `ILLUSTRATIVE_`.
3. Put a visible **SYNTHETIC — NOT EMPIRICAL EVIDENCE** watermark on every synthetic
   figure and slide-ready image.
4. Include `data_origin=synthetic`, `scientific_gate_eligible=false`, and the deterministic
   seed in every synthetic table or sidecar.
5. Exclude synthetic artifacts from normal empirical deliverable and presentation
   inventories by a machine-checked manifest rule.
6. Never use a real city label in a synthetic outcome plot unless the label is visibly
   qualified as a simulation scenario.

Existing `illustrative_only` packages are preserved as historical demonstrations and do
not become evidence for the amended study.

## 4. Prospective work authorized after Gate 0 approval

Approval authorizes only the following staged, nonthermal work. Every stage stops for
human review before the next begins.

### G1 — Complete observation reconciliation

Build one row per unique orbit–scene–city observation and reconcile the complete chain
from 2,968 catalogue records to the final 102 AM–PM analysis passes. The deliverable must:

- define whether every intermediate number counts granules, tiled products, physical
  overpasses, city observations, timestamps, or weighted pass-equivalents;
- explain why 413 weather timestamps map to 219 near-nadir physical passes;
- record every inclusion, exclusion, and tile-to-pass deduplication transition;
- give the exact pass-equivalent formula while reporting raw physical pass counts beside it;
- report clear-domain fraction plus usable tree and reference pixels per pass where those
  nonthermal quality counts are available;
- break attrition down by city, year, month, and time stratum;
- audit whether the 31 archive-unavailable candidates concentrate in the sparse support
  region; and
- test, without opening temperature, whether Collection 3 tiled `view_zenith` and cloud
  layers and correct fill-value semantics can recover avoidable losses.

### G2 — Rebuild antecedent hydroclimatic support

Evaluate three predictor definitions using 30- and 60-day windows ending on the day before
the observation:

1. accumulated precipitation;
2. days since a physically justified, prospectively frozen meaningful-rain threshold; and
3. accumulated `P − ET0` as a labelled sensitivity.

`P − ET0` is **antecedent climatic water balance**, not irrigation, root-zone water,
soil-moisture availability, or a direct plant-water measurement. Report continuous
distributions, correlations, overlap, seasonal variance, and high-demand wet/dry support;
the 3×3 grid is descriptive only. Retain the June Phoenix sign check and require the
expected strongly negative balance to be reproduced independently.

### G3 — Select a prospective sampling design

Make all choices using predictor support and data quality only:

- restore a semi-arid continental candidate, with Denver as the default candidate to audit;
- document why Miami entered v2 and treat it as exploratory unless later approved for a
  different role;
- evaluate the existing June–September window plus Los Angeles/Sacramento October and
  Phoenix April–May candidate shoulder seasons;
- require city-specific optical evidence of stable leaf-on conditions, and retain
  June–September as a sensitivity analysis;
- run view-angle thresholds of 10°, 15°, 20°, and 25°, with 30° exploratory; and
- for each threshold report physical pass counts and joint distributions of city,
  time of day, demand, wetness, view zenith, view azimuth, and relative sun–sensor azimuth.

Choose the city set, season windows, and angle rule by information and comparability, not
by sample size alone. Freeze them before thermal access.

### G4 — Audit the focused high-demand wet–dry contrast

Before simulation, require:

- wet and dry high-demand observations within the same cities;
- genuine within-city overlap in at least four cities for a pooled analysis;
- overlap in absolute demand, not only membership in a broad demand tercile;
- overlap in season and day of year;
- explicit separation of Phoenix monsoon and pre-monsoon support; and
- leave-one-city and leave-one-season support checks.

If fewer than four cities have genuine overlap, the pooled claim is not authorized;
comparative city case studies may be proposed instead.

### G5 — Redesign the time comparison

Treat morning versus afternoon as an empirical matching problem:

- show morning/afternoon availability and solar-elevation overlap for every city;
- match or stratify on comparable solar elevation rather than treating solar zenith as an
  ordinary adjustment when it defines the comparison;
- report view azimuth and relative sun–sensor azimuth and control the latter prospectively;
- retain a near-nadir view-zenith rule selected at G3;
- demonstrate weather, demand, wetness, season, and day-of-year overlap; and
- report the matched analysis count before simulation.

The estimand is **time-of-day asymmetry at comparable solar elevation**. Interpretation
must acknowledge heat storage, air temperature, wind, illumination, and shadow geometry.
It is not same-day hysteresis or direct physiological evidence.

### G6 — Independent clean-room verification

A script that imports none of the existing v2 pipeline modules must independently reproduce:

- starting and final record counts;
- orbit/scene/city identity and tile-to-pass deduplication;
- solar geometry;
- weather timestamps and joins;
- view-angle filtering; and
- the support tables.

Known-answer tests cover VPD and units, a published solar-position value, exclusion of the
observation day from rolling windows with zero violations, cloud-mask/fill semantics,
tile-to-pass identity, signs and units of precipitation/ET0/water balance, and the June
Phoenix balance. Independent verification should preferably be run or inspected by a
person other than the primary implementer.

### G7 — Freeze and run simulations

Preregister separate simulations for:

1. the full demand-by-wetness surface;
2. the focused high-demand wet–dry contrast; and
3. the empirically matched time-of-day asymmetry.

Before running, freeze effect sizes in kelvin, residual variance, city/pass/matched-set
clustering, pass-level measurement error, replicate counts, random seeds, alpha, target
power, minimum detectable effect, bias checks, Type-I-error checks, interval-coverage
checks, and leave-one-city/season analyses. A simulation must reproduce the empirical
clustering and support structure. Adding draws from the same collinear predictor
distribution is not evidence that new cities or seasons help; such scenarios must use
justified, meaningfully different predictor distributions.

### G8 — Decision

Apply the frozen results once:

- **Combined study:** both the high-demand and time-of-day analyses pass.
- **Focused hydroclimatic study:** only the high-demand comparison passes.
- **Time-of-day study:** only the empirically matched time comparison passes.
- **Comparative case studies:** pooled support fails but defensible city-specific support exists.
- **Identifiability paper:** neither contrast passes, but the support/identifiability result is valid.
- **Simplify pipeline:** independent verification cannot reproduce the core counts.

No thermal access follows automatically from a simulation PASS. A separate prethermal
activation gate must still freeze the data chain, holdout rule, storage plan, and exact
analysis specification.

## 5. Gate mechanics

Each gate emits only:

- `review.md` with the decision and material evidence;
- `checks.json` with machine-readable statuses;
- supporting CSVs; and
- at most two essential figures.

The AI then stops. Advancement requires an explicit `APPROVE G#`. `REVISE G#: ...`
returns the same gate for another review; `STOP` ends the amended workflow without
changing preserved results.

## 6. Approval effect

Approving G0 will:

- accept this document as the prospective, outcome-blind working protocol;
- authorize G1 nonthermal reconciliation only;
- preserve all existing STOP results and sealed outcomes; and
- require a new append-only decision-log entry binding the approved amendment and its
  checksum before G1 begins.

Approving G0 will **not** approve a final city set, season window, wetness metric,
view-angle threshold, matching method, simulation parameter, holdout, or thermal run.
Those decisions remain assigned to later gates.
