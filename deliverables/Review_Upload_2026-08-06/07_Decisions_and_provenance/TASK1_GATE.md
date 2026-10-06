# Task 1 feasibility result

**Active profile: STOP / `STOP_USER_SKIPPED_D0047_GEOMETRY_710_OF_911`.**

**Preserved exhaustive result: STOP.** D0035 remains
`STOP_D0035_INCOMPLETE_GEOMETRY`, most recently confirmed by
`STOP_D0046_DIRECT_DOWNLOADS_INCOMPLETE`.

D0047 authorizes a separately named archive-available analysis profile. It does
not convert the original 942-candidate exhaustive census into a PASS.

- Step 1 remains complete and canonical: `cross_city_separation_only`.
- Original candidate ledger: 942 city-orbit rows.
- Explicit pre-geometry exclusions: 31 rows labelled
  `archive_unavailable_pre_geometry`.
- Retained for geometry: 911 candidates.
- Original/retained city-scene links: 1,404 / 1,355.
- Original/retained unique GEO scenes: 1,370 / 1,323.
- Missing exact GEO objects: 41.
- No missing object is imputed, assigned zero coverage, or replaced.
- The LP DAAC restoration/re-indexing request was sent under explicit user
  authorization.

The active estimand is the **2018–2025 five-city archive-available candidate
population**. Exclusions are structured and must be reported by city, year,
acquisition-UTC month, and local-solar-time stratum.

The continuation gates are:

1. All 911 retained candidates receive definitive D0035 geometry.
2. Every retained geometry passer receives a finite official cloud fraction.
3. Exact-acquisition HRRR is complete for every required retained pass.
4. Definitive Step 2 and F2.5 pass all checks.
5. Definitive Step 3 passes D0027 and produces T3.1.
6. Only then may a scope-qualified canonical Task 1 PASS be written.

D0048 repairs only the fail-closed handling of an available scene whose complete
stride-32 locator proves it is far outside the frozen domain. It does not change
any geometry threshold or remove a candidate. The proof requires the frozen
6,200 m unsampled-displacement bound, 310 m boundary guard, a deterministic
full-resolution nearest-locator seed, the unchanged expansion algorithm, and
exactly zero mapped target cells. The active implementation is decision `D0048`
and algorithm `d0047-archive-available-l1b-dmrpp-pass-stream-v2`; v1 checkpoint
evidence is preserved for audit but cannot be reused.

D0049 is a transport-only repair for isolated stale authenticated sessions. On
an HTTP 401 or 403, the runner may create one fresh authenticated session for
that scene and retry the identical byte range once. A second 401/403 fails
closed, HTTP 404 is never retried under this rule, and every existing range,
object-validator, byte-cap, checksum, and geometry check remains unchanged.
The refresh count is recorded as zero or one in newly written scene evidence;
pre-D0049 completed evidence remains valid because no scientific binding or
algorithm version changed.

On 2026-08-05 the user directed the live D0047 geometry computation to stop and
continue the guide through a separately labelled noncanonical demonstration.
The last durable checkpoint contains 710 of 911 retained candidates, with zero
unresolved among those evaluated and 201 retained candidates not evaluated.
Those 201 candidates are not imputed, classified, assigned zero, or silently
dropped. This user-directed shortcut does not produce a Task 1 PASS and does not
activate canonical Task 2. Any continuation is isolated under the
`illustrative_only` namespace, opens no thermal/LST or 2026 data, selects no
real holdout, and labels all outcome-bearing content as synthetic.

Run R0012 completed that demonstration under
`data/processed/v2/illustrative_only/steps02_13/` and
`figures/v2/illustrative_only/steps02_13/`. Its manifest SHA-256 is
`ef576a91fcecba51e076c1ecc995a16d1b2ed8f8ddd617e0e589dd88379c10f7`;
completion of this illustrative package does not alter this STOP gate.

Decision D0052 and run R0013 extend the same quarantined demonstration through
the source guide's final Step 14 under
`data/processed/v2/illustrative_only/steps02_14/` and
`figures/v2/illustrative_only/steps02_14/`. The package contains 102/102 unique
guide IDs, 72 visibly labelled figures, 40 origin-labelled and gate-ineligible
CSV tables, a canonical-STOP M14.1 memo, and a confirmatory-NOT-RUN M14.2
report. Its authoritative manifest is stored inside that package, and the
release archive includes the hashed code, tests, requirements, decision log,
and gate record needed for an offline illustrative rebuild. This is an
illustrative package completion only; it does not complete canonical Step 14,
activate Task 2, select a real holdout, or open thermal/LST or 2026 data.

Until every gate passes, Task 2 remains inactive. Holdout selection,
ECOSTRESS thermal/LST access, and 2026 access remain prohibited. If LP DAAC
restores the 41 objects, the original exhaustive census must be rerun as a
separate sensitivity analysis; D0047 artifacts are never mutated in place.

See `step2_l1b_repeat_retry_D0046/direct_download_validation.json`,
`docs/v2/D0047_ARCHIVE_AVAILABLE_PROFILE.md`, and
`docs/v2/DECISION_LOG.md` for the controlling evidence and scope.
