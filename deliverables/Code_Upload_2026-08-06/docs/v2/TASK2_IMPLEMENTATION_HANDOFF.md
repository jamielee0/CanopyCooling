# Conditional Task 2 implementation handoff

## Current status

**Task 2 is not active.** D0047 is currently running a separately named
archive-available Task 1 profile after the user explicitly authorized
continuation without the 41 unavailable GEO objects. D0047 changes the estimand
to the 2018–2025 five-city archive-available candidate population; it does not
erase or convert the original D0035/D0046 exhaustive STOP.

The D0047 ledger retains all 942 candidates, marks 31 as
`archive_unavailable_pre_geometry` with null/not-evaluated geometry fields, and
passes 911 candidates into geometry. The excluded rows remain ineligible for
D0047 primary analysis even if their L2T temperature assets exist. A restored
GEO object enters only a separately versioned exhaustive sensitivity run.

Task 2 preflight must reject a generic PASS that lacks the D0047 profile,
scientific scope, count identities, and bound ledger/exclusion hashes. All Task
2 tables, figures, and prose must identify the archive-available profile.

This handoff prepares only a fail-closed implementation surface. The read-only
entry point is:

```text
python src/run_v2_task2.py --preflight
```

It must return nonzero until a canonical machine-readable Task 1 `PASS` exists,
all pre-thermal decisions are frozen, a quality-only holdout is recorded, and
the storage projection passes. No result-bearing Task 2 command exists yet.

## Boundary

Task 2 comprises the pre-thermal freeze and Guide Steps 4–9 for the four
development cities during 2018–2025. It ends with one analysis row per city,
matched set, and pass. It excludes:

- the held-out city's thermal archive until the method is frozen;
- all 2026 data;
- primary result modelling in Steps 10–14;
- any temperature resampling or mixed primary collection chain.

Native ECOSTRESS pixels are retained as source geometry. Tree and reference
pixel values are aggregated only when constructing the declared matched-set by
pass row.

## Activation contract

The future canonical `data/processed/v2/task1/TASK1_GATE.json` must contain at
least:

```json
{
  "task1_gate": "PASS",
  "profile_gate": "PASS_D0047_ARCHIVE_AVAILABLE_TASK1",
  "analysis_profile": "D0047_archive_available",
  "scientific_gate_eligible": true,
  "scientific_gate_scope": "archive_available_only",
  "estimand": "2018-2025 five-city archive-available candidate population",
  "candidate_ledger_count": 942,
  "archive_unavailable_pre_geometry_count": 31,
  "retained_geometry_candidate_count": 911,
  "original_exhaustive_gate_status": "STOP_D0035_INCOMPLETE_GEOMETRY",
  "latest_unavailability_confirmation": "STOP_D0046_DIRECT_DOWNLOADS_INCOMPLETE",
  "definitive_step2": "complete",
  "hrrr_exact_acquisition_fetch": "complete",
  "definitive_step3": "complete",
  "lst_or_thermal_layers_opened": 0,
  "holdout_status": "UNSELECTED",
  "season_2026": "UNOPENED",
  "t3_model_support_path": "data/processed/v2/task1/.../T3.1_model_support.csv"
}
```

The preflight additionally requires every status in `configs/v2_task2.toml` to
be `FROZEN`, the selected holdout to be named, a positive storage estimate with
headroom, and an explicit coordinator switch enabling result-bearing work.

## Decisions: user choice versus evidence

### Requires a new user or supervisor choice

1. **O0009 scientific scope.** Choose either a sixth-city redesign, which sends
   the study back through Steps 1–3, or retain the five-city panel and restrict
   demand-by-dryness inference to observed cross-city/common support. The latter
   is the shortest scientifically coherent route.
2. **Storage authority only if the evidence-backed staged projection does not
   fit.** Using an external volume, obtaining a new writable root, or deleting or
   moving existing user data requires user authorization.

D0035 supplies the unchanged numerical geometry rule; D0047 supplies the
user-approved archive-availability exclusion and scope-qualified estimand.
Neither decision alone activates Task 2.

### May be frozen from non-thermal evidence

- **Holdout eligibility and identity:** the guide predetermines Phoenix-specific
  thermal QA in F4.1, F6.2, and F7.4. Record Phoenix as the development/calibration
  city, then apply a frozen quality-only ranking to the other four cities. The
  ranking may use pass completeness, time-stratum support, cloud survival,
  geolocation, and product matchability, never LST. Record the identity and proof
  of no thermal inspection before opening any LST.
- **Primary collection chain:** audit official availability, full 2018–2025
  coverage, layer names, QA semantics, scales, fill values, and access support.
  Freeze the single complete chain; keep the alternative version for Step 13.
- **Time strata:** retain the four provisional two-hour strata only if definitive
  T3.1 and pass support allow them; otherwise apply a predeclared adjacent merge
  based only on counts/common support.
- **QA and scene usability:** freeze quality bits, water/cloud masks,
  obstruction/geolocation/view rules, physical plausibility flags, and minimum
  final valid-pixel/matched-set support before temperature distributions are
  viewed.
- **Supporting products:** select albedo/radiation/ET/evaporative-stress layers
  from collection metadata. A fusion uncertainty or fine-image-lag cutoff may be
  estimated from fused-versus-native optical error, not from thermal response.
- **Meteorology:** D0020 controls HRRR interpolation and ERA5-Land sensitivity.
  Freeze station sources, station QA, and spatial summaries from coverage tests.
- **Optical and land cover:** freeze the HLS pre-pass window inside the guide's
  5–10 day range, exact buffer radius inside 250–500 m, year assignment, canopy
  carry-forward/change exclusion, and height/LCZ sources from availability and
  source QA.
- **Classification and matching:** freeze three canopy percentiles, candidate
  reference radius, covariates, distance/caliper, reference ratio/replacement,
  exclusions, balance target, and validation sampling before F8.4/F8.7 expose a
  thermal relationship. Outcome-bearing registration and threshold results are
  pass/adjust/stop checks, not tuning inputs.
- **Step 9 schema:** freeze keys, units, sign conventions, source/version fields,
  and required completeness before assembly.

Every frozen choice receives a new append-only decision-log row. An ambiguous
evidence audit stops; it does not silently select the more favourable option.

## Work packages and allowed concurrency

### 2A — pre-thermal governance and storage

Coordinator-owned. Consume the Task 1 PASS/T3.1 only; inventory products and
asset sizes; resolve O0009; freeze collection, strata, QA, and storage; select
the holdout from quality evidence. Do not open LST. This stage gates all others.

### 2B — Step 4 temperature archive

Implement native-window fetch, immutable source manifest, version-aware masks,
scene table, pixel attrition, and F4.1–F4.6/T4.1–T4.3. The seven checks are:
scale, known-location ordering, water mask, zero-offset geolocation, band-mode
shift, selective attrition, and checksum-identical rebuild.

### 2C — Step 5 supporting ECOSTRESS chain

Implement same-pass joins for vegetation/albedo plus uncertainty, radiation,
four-member ET with canopy transpiration, second-family ET, and ESI/PET. Gate on
physical albedo/radiation, bounded fusion error, distinct ET members, ESI
consistency, and match completeness.

### 2D — Step 6 meteorology

Reuse the v2 HRRR adapter and Step 1 water-balance axes. Add multi-cell
acquisition interpolation, stations, ERA5-Land sensitivity, spatial spread, and
correlation/concurvity outputs. Gate on formula accuracy, alignment, no
look-ahead, source comparisons, and pass-time separability.

### 2E — Step 7 optical, land cover, and urban form

Implement HLS pre-pass/seasonal composites, year-specific canopy/impervious and
categorical land cover, change exclusions, focal/buffer variables, height or
sky-view, LCZ, elevation, and distance to water. Gate on zero future imagery,
mean-preserving fraction aggregation, integer categorical codes, and exact
buffer checks.

After 2A, 2B–2E may run in parallel on isolated paths. They may not independently
change shared decisions or configuration.

### 2F — Step 8 classification and matching

First build and freeze the outcome-blind classifier, continuous-canopy support,
matching, balance, and validation. Only then calculate the locked thermal
diagnostics. Gate on every matching SMD below 0.1, precision and recall by
stratum, non-park representation, registration spread below T3.1's detectable
effect, threshold sensitivity, adequate set size, and reference composition.

### 2G — Step 9 integration

Build the canonical matched-set-by-pass table and full dictionary. Require unique
keys, complete primary outcome/adjustment set or disclosed row removal, physical
units, exact outcome identities, positive Phoenix hot-afternoon sign convention,
and byte-identical rebuild.

Task 2 completes only when all F4.1–F9.4 and T4.1–T9.2 artifacts and source
checks exist, the development pipeline is frozen, and the held-out thermal
archive plus 2026 remain unopened.

## Storage-safe staging

Current evidence is a hard warning: free space was about 11 GiB during the
readiness audit and about 19 GiB at the later preflight, while `data/raw/v2`
already uses about 10 GiB. APFS free space is volatile; a full multi-product
archive must not be started from either observation without a sealed projection.

1. Use catalogue metadata or read-only object headers to inventory bytes for
   every frozen candidate and required layer before downloading.
2. Estimate peak local use by stage, including temporary mosaics and derived
   chunks. Require `projected_peak × 2 + 5 GiB reserve <= free bytes`.
3. Prefer stable granule identifiers plus checksums and native-grid COG window
   reads clipped to the frozen domain/MGRS core. Never persist signed URLs or
   credentials, and never interpolate temperature.
4. Process one development-city × year × product-family batch at a time into a
   compressed, chunked native-grid store. Seal each batch manifest and rerun its
   checks before the next batch.
5. Do not delete or move existing data to create space. If the projection fails,
   stop and request an approved external storage root or another recoverable
   storage arrangement.

The storage projection is a gate, not an optimization performed after downloads
begin.

## Existing code disposition

- Reuse directly: v2 domains/config provenance, pass identity, catalogue and
  metadata joins, solar geometry, MGRS-core clipping, cloud/view raster helpers,
  checksums, Step 1 water balance, HRRR adapter, and definitive T3.1 once it
  exists.
- Adapt pure helpers only: legacy Earthdata filename/QA utilities, VPD formula,
  optical-index math, area-weighted fraction aggregation, categorical handling,
  Census/building acquisition, validation/matching utilities, and table
  dictionaries.
- Redo for v2: every primary Step 4–9 module. Legacy products are Phoenix-2023 on
  a custom grid; the legacy optical window can include future imagery; legacy ET
  does not implement the required current product chain; and the old master
  table has the wrong grain.

No legacy output may substitute for a v2 acceptance check.
