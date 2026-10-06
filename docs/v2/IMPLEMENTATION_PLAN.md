# V2 implementation plan

## Outcome

Build the guide as a new, gate-driven five-city pipeline while keeping the working Phoenix pilot
available for comparison. The first implementation milestone is **Task 0 + Task 1**: governance,
Guide Steps 1–3, and an evidence-backed go/adjust/stop decision before any new thermal archive is
built.

## Working model

Use one Codex task for one independently reviewable outcome. Give each task its allowed paths,
inputs, acceptance tests, and prohibited actions. Parallelize read-only research and isolated
modules; keep integration, scientific gate decisions, shared configuration, and any live-data
run under one coordinating task.

Recommended sequence:

1. Preserve and verify the Phoenix baseline.
2. Add Task 0 specification, repository guardrails, and append-only decisions.
3. Resolve and checksum five official urban domains. Do not run the weather audit first.
4. Implement Step 1 as pure transformations plus a replaceable data-access adapter.
5. Implement Step 2 as catalogue normalization, solar geometry, pass deduplication, attrition,
   and cloud-survival inputs. Catalogue search and granule download are separate operations.
6. Implement Step 3 against a common normalized Step 1/2 table.
7. Run offline unit tests and deterministic synthetic smoke data.
8. Run the real metadata/weather profiles, then the complete real Task 1 profile.
9. Review artifacts and issue one of the three feasibility decisions. Stop before Step 4 unless
   the gate permits continuation.

## Suggested repository surface

The coordinating implementation may choose exact names, but the surface should remain separate
and recognizable:

```text
AGENTS.md                         repository-wide safety and review rules
configs_v2/                      frozen non-secret city, period, and threshold configuration
docs/v2/                         requirements, decisions, baseline, and this plan
src/urban_cooling_v2/            v2 library code
src/test_v2_*.py                 offline deterministic tests
data/raw/v2/                     immutable source responses and downloaded calibration granules
data/interim/v2/                 normalized daily weather and catalogue/scene records
data/processed/v2/               Task 1 tables and machine-readable gate report
figures/v2/                      numbered Task 1 figures
```

Every generated artifact should carry, directly or in a sidecar manifest: configuration hash,
code revision or dirty-state fingerprint, source query time, source collection/release, row count,
date range, city list, and checksum.

## Legacy disposition map

| Legacy component | V2 disposition | Reason and intended action |
|---|---|---|
| Repository, manifest, account setup | **Reuse/adapt** | Keep project conventions and credential checks; add v2 dependencies and provenance without exposing secrets. |
| `config.py` Phoenix box/period | **Retain for legacy; create v2 config** | The box and 2023 period cannot define the five-city 2018–2025 audit. Do not silently change legacy constants. |
| `src/build_reference_grid.py` | **Retire from v2 primary chain** | The guide anchors analysis to native ECOSTRESS tiles; keep the script only for reproducibility of the pilot. |
| `src/section2_ecostress_lst.py` | **Adapt concepts; redo v2** | Reuse Earthdata familiarity and QA utilities where verified, but add collection freeze, scene geolocation, view angle, obstruction, retrieval mode, and native geometry. |
| `src/section3_ecostress_et_esi.py` | **Redo v2** | The guide replaces the old product assumption with a verified current multi-product chain in Step 5. Do not reuse product IDs by memory. |
| `src/section4_sentinel2_indices.py` | **Reuse seasonal vegetation half** | Seasonal vegetation supports classification. It cannot provide pass-varying moisture. |
| `src/section4b_ndmi_timeseries.py` | **Adapt** | Pre-pass optical logic is useful for Step 7 after temporal leakage and image-lag rules are enforced. |
| `src/section5_landcover.py` | **Adapt/extend** | Use year-specific releases, add albedo, distinguish focal and buffer urban form, and apply correct aggregation. |
| `src/section6_era5land_vpd_sm.py` | **Retain as sensitivity** | V2 primary acquisition-time weather is HRRR; ERA5-Land remains a comparison, and its soil moisture is not the main antecedent variable. |
| `src/section7_precip_drought.py` | **Adapt** | Reuse download/date handling where correct; primary antecedent quantity becomes 30/60-day `pr - eto`, and Step 1 uses gridMET. |
| `src/section8_neighborhood_tree.py` | **Adapt with correction** | Reuse Census/tree/building logic; CDC SVI is tract-level, not block-group-level, unless a new index is explicitly constructed. |
| `src/section9_harmonize.py` | **Redo for v2** | Inputs must be brought to the native tile grid; fractional layers use area-weighted aggregation and temperature is never resampled. |
| `src/section10_classify_pixels.py` | **Redo design** | V2 selects city-specific thresholds, matched references at the correct scale, continuous canopy co-primary model, validation, and registration sensitivity. |
| `src/section11_anomalies.py` | **Reuse verified math** | Anomaly/z-score utilities may be lifted with unit tests; variable roles and grouping change. |
| `src/section12_compound_stress.py` | **Retire from v2 primary analysis** | A scalar compound index discards the demand-by-antecedent comparison. Preserve only as a labelled legacy sensitivity if justified. |
| `src/section13_master_table.py` | **Rebuild schema** | Same table-building pattern, but new scene, geometry, matching, radiation, weather, support, and provenance fields are mandatory. |
| `src/section14_threshold.py` and notebook | **Retain as pilot; redesign later** | The v2 primary endpoint is time-of-day dependence and the hydroclimatic surface is conditional on support; no early threshold search. |
| `src/section14b_mixed_effects.py` | **Adapt clustering ideas** | Pass and matched-set dependence must be simulated in Step 3 and modelled later; do not assume the Phoenix specification generalizes. |
| `src/section15_response_surface.py` | **Adapt only after feasibility** | Useful conceptual starting point, but v2 distributions, common support, weighting, and `mgcv` model plan control. |
| `src/run_all.py` and `src/test_run_all.py` | **Keep legacy; create/adapt v2 runner** | Avoid destabilizing the passing 17-step pilot. Integrate only after the v2 interface and gates are stable. |

## Task 0 work package

### Inputs

- source guide and its 30-page rendered review;
- current branch, tests, deliverables, environment, and dirty worktree state;
- current Phoenix design and remediation documentation.

### Outputs

- repository guardrails (`AGENTS.md`);
- `docs/v2/BASELINE.md`;
- `docs/v2/REQUIREMENTS.md`;
- `docs/v2/IMPLEMENTATION_PLAN.md`;
- `docs/v2/DECISION_LOG.md`.

### Acceptance

- all source deliverables have one canonical entry;
- duplicate/malformed rows are disclosed rather than silently renumbered;
- legacy preservation, secrets, holdout, 2026, native geometry, effective sample size, and
  terminology rules are explicit;
- every unresolved scientific choice is open in the decision log and cannot be silently filled
  during a result run.

## Task 1 work packages

### 1A — domains and weather audit

Prompt boundary: implement Guide Step 1 only; write only the Step 1 module/tests and agreed v2
output paths; do not touch legacy modules or decide the holdout.

Required implementation layers:

- validated daily input schema and unit checks;
- rolling windows that end at day minus one;
- within-city summer percentiles and explicit wetness/dryness direction;
- tercile cells and diagnostic-corner summaries;
- whole-summer bootstrap, within-city permutation, and binomial intervals;
- deterministic figure/table/memo generation;
- a live adapter whose cached raw response can be replayed offline.

### 1B — catalogue and solar audit

Prompt boundary: implement Guide Step 2 only; catalogue search must never download a granule;
write only the Step 2 module/tests and agreed v2 output paths.

Required implementation layers:

- version-aware Earthdata query adapter and immutable raw metadata cache;
- metadata normalization with an explicit missing-field report;
- pass-versus-tile identity and deterministic deduplication;
- `pvlib` solar geometry and local-solar-time tests;
- band mode, obstruction, geolocation, near-nadir, time strata, and attrition states;
- cloud-survival calibration input and representativeness check;
- definitive join to exact-acquisition hourly demand.

### 1C — clustered power simulation

Prompt boundary: implement Guide Step 3 only; consume the normalized Step 1/2 schema and never
read a thermal outcome or choose the holdout.

Required implementation layers:

- configurable reproducible random seeds and Monte Carlo replicates;
- empirical covariate resampling by pass/city;
- row, matched-set, pass, and city dependence;
- interaction, no-interaction, and smooth-no-breakpoint generators;
- interaction and transition tests mirroring intended downstream models;
- pass-level and row-level bootstrap comparison;
- quick CI profile for code verification and full profile for the scientific gate.

### 1D — integration and gate review

The coordinating task owns shared configuration, CLI/runner, schemas, integration tests, live
runs, and the final decision. It verifies that separately written modules agree on city names,
time fields, percentile orientation, pass IDs, and output IDs.

## Run profiles

| Profile | Data/network | Purpose | May it satisfy Task 1? |
|---|---|---|---|
| Unit | Tiny in-memory fixtures; no network | Lock formulas, schemas, edge cases, count identities, and deduplication | No |
| Synthetic smoke | Deterministic five-city mock data | Prove all F1–F3/T1–T3 paths render and the runner resumes | No |
| Live tiny | One city/month or metadata-only query | Verify credentials, source schema, collection support, and solar calculations | No |
| Full feasibility | Five domains, 2018–2025 summers, cloud calibration, hourly pass-time join, full simulation | Produce the scientific gate | Yes |

The full run should be resumable, cache immutable raw responses, write to a staging directory,
validate outputs, then atomically promote the completed run. A failed or partial run must not
overwrite the last valid result.

## Review order

1. Review domain maps, identifiers, areas, and hashes before data counts.
2. Review Step 1 units, Phoenix monsoon shape, percentile direction, clear-sky definition, and
   corner support.
3. Review Step 2 query/version provenance, solar-time spot checks, duplicate passes, metadata
   completeness, attrition, and cloud-month stability.
4. Treat F2.5 as the conditions verdict that counts.
5. Review Step 3 recovery and Type I error before reading power. Reject a power result from a
   simulator that cannot recover known truth.
6. Issue a machine-readable and human-readable gate: `proceed_within_city`,
   `adjust_cross_city`, or `stop_interaction`. Include failed checks and uncertainty.

## Explicit stop conditions

- Official domains or checksums are missing or changed after the audit started.
- The primary ECOSTRESS collection/version cannot cover all five cities and the full period.
- Required geolocation, obstruction, or view metadata cannot be obtained reliably.
- Cloud-survival calibration is unstable at the preregistered tolerance.
- F2.5 has essentially no diagnostic-corner support.
- The simulation fails large-sample recovery or has materially inflated clustered Type I error.
- The real pass count is below the minimum for the proposed model.
- Someone requests opening 2026 or choosing the holdout from a thermal result before freeze.

In each case, preserve the evidence, record the decision, and stop the dependent work rather than
quietly weakening the check.
