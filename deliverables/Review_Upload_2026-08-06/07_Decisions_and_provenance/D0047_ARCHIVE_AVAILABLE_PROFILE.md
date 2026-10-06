# D0047 archive-available Step 2 profile

## Scope

D0047 is the user-approved continuation profile after the exact 41-scene
`ECO_L1B_GEO.002` restoration route was exhausted locally. The original D0035
exhaustive result remains a valid STOP. D0047 instead estimates the
**2018–2025 five-city archive-available candidate population**.

The canonical D0047 candidate-facing tables retain all 942 rows. Thirty-one
rows are explicitly labelled `archive_unavailable_pre_geometry` with null
geometry/cloud metrics and not-evaluated checks. They are never encoded as zero
coverage, geometry failures, clear scenes, or imputed observations. The
remaining 911 rows receive the unchanged D0035 geometry rule and, for every
geometry passer, the unchanged D0033 exhaustive-cloud rule.

## Frozen pre-geometry attrition

| City | Original | Excluded | Retained |
|---|---:|---:|---:|
| Atlanta | 196 | 8 | 188 |
| Los Angeles | 196 | 8 | 188 |
| Miami | 91 | 1 | 90 |
| Minneapolis–St. Paul | 266 | 8 | 258 |
| Phoenix | 193 | 6 | 187 |
| **Total** | **942** | **31** | **911** |

Additional exclusion distributions fixed before geometry values were opened:

- Year: 2020 = 24; 2024 = 7.
- Acquisition-UTC month: June = 8; July = 4; August = 13; September = 6.
- Local-solar-time stratum: 10–12 = 9; 12–14 = 9; 14–16 = 8; 16–18 = 5.
- Original/retained city-scene links: 1,404 / 1,355.
- Original/retained unique GEO scenes: 1,370 / 1,323.

This imbalance is reported, not hidden or corrected through imputation. Any
resulting lack of common support must fail or constrain the later support gate;
it cannot trigger post-result threshold changes.

## Gate contract

The geometry/cloud PASS name is
`PASS_D0047_ARCHIVE_AVAILABLE_GEOMETRY_AND_EXHAUSTIVE_CLOUD`. It requires:

1. a hash-bound 942-row ledger and 31-row exclusion table;
2. exactly 31 null/not-evaluated exclusions and 911 definitive retained rows;
3. unchanged D0035 95% coverage, 20-degree p95, 210 m mapping, overlap, and
   provenance rules for all retained candidates; and
4. a finite directly observed official cloud fraction for every retained
   geometry passer.

Subsequent scope-qualified labels are:

- HRRR: `PASS_EXACT_HRRR_RUN_SEAL_D0047_ARCHIVE_AVAILABLE`;
- Step 3 count: `certified_archive_available_expected_pass_equivalent_floor`;
- final Task 1 profile: `PASS_D0047_ARCHIVE_AVAILABLE_TASK1`;
- scientific scope: `archive_available_only`.

Task 2 must reject a generic PASS without the D0047 scope, counts, and bound
artifact hashes. The 31 excluded passes remain ineligible for D0047 primary
analysis even if their L2T temperature products exist. Restored GEO objects
enter only a separately versioned exhaustive sensitivity run.

## D0048 available-scene no-overlap proof

D0048 fixes a technical fail-closed case discovered before any affected
full-resolution `view_zenith` value was opened. An exact available scene whose
complete 176×169 locator has no point within the unchanged 8 km influence is
eligible for a deterministic full-resolution no-overlap confirmation only
when every locator cell is valid and
`minimum_literal_domain_distance − 6,200 m > 310 m`. The runner then seeds the
globally nearest locator point for each frozen target grid, applies the
unchanged ±64-pixel subset and iterative boundary proof, and accepts
`verified_no_domain_overlap` only when zero target cells map within 210 m.

This does not impute or drop a scene. The scene contributes no mapped cells; a
single-scene pass receives definitive zero coverage, while a companion scene
may still supply pass coverage. All D0035 scientific thresholds remain frozen.

The implementation is bound to decision `D0048` and algorithm
`d0047-archive-available-l1b-dmrpp-pass-stream-v2`. Evidence from the initial
v1 attempt is invalid for reuse and is preserved with an independent hash
ledger under
`data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available/pre_D0048_v1/`.
Final scene evidence distinguishes the selector mode `verified_no_overlap`
from the accepted observation status `verified_no_domain_overlap`, and records
that zero coverage was observed rather than imputed or assigned for a missing
scene.

## D0049 authenticated-session refresh

Two isolated HTTP 403 responses interrupted the long D0048 range-read run.
After each stop, a fresh authenticated session read both the exact failed
object and a known-good control as valid eight-byte HDF5 ranges with immutable
object validators. D0049 therefore permits one fresh-session retry per scene
after HTTP 401/403 only. The exact byte request and every content, size,
validator, hash, resource-cap, and scientific check remain unchanged; a second
401/403 fails closed, and 404 is never refreshed or reclassified. This is a
transport-continuity rule, so the D0048 v2 algorithm and already completed
evidence remain valid.

## External restoration

The exact 41-scene restoration/re-indexing request was sent to LP DAAC under
the user's explicit authorization. A later archive change does not mutate this
profile; it triggers a new exhaustive sensitivity run.
