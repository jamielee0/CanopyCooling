# D0072 — Gate 3 geometry zero-coverage and resume-storage incident

## Status

`FROZEN / NONTHERMAL IMPLEMENTATION SAFETY CORRECTION`

**Frozen:** `2026-08-13T23:16:30+09:00`

This record was frozen after the D0069 geometry stage had begun, while all
temperature/LST values, thermal outcomes, holdout data, and 2026 science data
remained sealed. The earlier D0060/D0061 metadata-query deviations remained
disclosed. This record documents two implementation incidents and their outcome-blind
corrections. It does not change the city, season, angle, phenology, support, or
selection rules.

## Full-resolution zero mapped cells

The first geometry invocation stopped after preserving 79 checksum-bound pass
checkpoints. Atlanta orbit 17605 had an accessible, exact `ECO_L1B_GEO.002`
source and complete inherited D0047 full-resolution evidence, but zero mapped
domain cells. The initial D0069 reuse validator accepted only the older
`verified_no_domain_overlap` label and rejected the equally definitive
`near_domain_full_resolution_verified` zero-cell proof.

The correction treats a pass as a resolved observed zero-coverage result only
when every required scene has exact city/orbit/scene/granule identity and a
complete full-resolution, boundary-verified, checksum-bound zero-mapped proof.
Both accepted proof categories require their category-specific proof mode and
acceptance status, a boundary distance beyond the frozen guard, positive and
hashed chunk/range evidence, and explicit absence of missing-scene
substitution or zero imputation. The output receives a distinct resolved
zero-mapped status. Its angle summaries remain undefined, and it cannot enter
an angle threshold, cloud/weather target, eligible observation set, or
unavailable-pass upper bound.

The rule is categorical for every inherited zero-cell pass; it does not
special-case orbit 17605. Production, packet, and clean-room validators each
enforce the exact frozen scene census and independently reject duplicate,
missing, relabelled, substituted, imputed, boundary-incomplete, nonzero, or
tampered evidence.

## Resume storage accounting

The original preflight conservatively reserved the full 734-pass worst case
even after valid checkpoints existed. Its full-population raw-array ceiling and
five-GiB reserve remain unchanged. Resume credit is now allowed only for an
ordinary pass whose current checkpoint, binding, source identities, evidence,
and reconstruction artifact satisfy the exact same validator used by the
worker's no-write return path. Credit is the predeclared deterministic
city-domain worst case, never the compressed size, mapped-cell count,
coverage, angle, or any scientific result.

Every credited identity and validation digest is sealed in the preflight. At
worker use, a credited pass is handled before every zero-map or reconstruction
write branch: the current source binding and reconstruction bytes are reopened,
hashed, sized, structurally validated, and compared with the sealed digest. It
must return without writing or fail with an instruction to rerun the preflight.
It can never fall through to recomputation under stale storage credit.

Legacy zero-map passes receive no resume credit because their current worker
path writes a fresh empty reconstruction artifact. Invalid or stale artifacts
also receive no credit. The live requirement is therefore:

`remaining deterministic raw worst case + remaining fixed container overhead + 5 GiB reserve`.

The full-population raw ceiling, final actual-artifact cap, no-deletion rule,
and packet/clean-room independent reconciliation remain binding.

## Fail-closed storage stops

Before this record was frozen, two approved resume attempts stopped before
geometry writes because APFS free space was below the live requirement. The
latest failed preflight snapshot at freeze reported 734
candidate passes, 55 credited ordinary passes, 679 remaining passes,
7,848,037,904 bytes of remaining conservative new data, a 5,368,709,120-byte
reserve, and 13,216,747,024 required free bytes. It observed 12,327,686,144
free bytes and returned `FAIL_INSUFFICIENT_FREE_SPACE`. At freeze, the 79
existing checkpoints included 24 uncredited zero-map checkpoints and remained
preserved. These are historical at-freeze counts; a later successful resume
preflight and subsequent checkpoints supersede the live operational snapshot
without changing this incident record.

No project or user data may be deleted or moved to defeat this gate. Execution
may resume only after the unchanged live preflight passes or the user supplies
an approved writable storage root.

## Review evidence

Independent science and code reviewers approved the zero-coverage semantics,
strict scene predicates, resume-credit formula, and final time-of-check/time-of-use
control after iterative revisions. The final Gate-3 packet must bind this
record, the augmentation runner and tests, the successful preflight, all
checkpoint/evidence/reconstruction inventories, and the exact independent
review record. Gate 3 remains unapproved until the real nonthermal run, packet,
clean-room verification, complete tests, and final review all pass.
