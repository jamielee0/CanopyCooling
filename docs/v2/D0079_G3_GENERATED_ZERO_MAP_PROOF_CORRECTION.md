# D0079 — Gate-3 generated zero-map proof correction

## Status

`FROZEN / PRE-RERUN NONTHERMAL INTEGRITY CORRECTION`

**Frozen:** `2026-08-16T21:24:26+09:00`

After D0078 authorized resumption, the D0069 geometry, cloud, and exact-weather
stages completed without opening temperature/LST outcomes, holdout data, or any
2026 science record. Gate-3 packet generation then failed closed on
`denver_aurora:00345`: its reconstruction contained zero mapped target cells,
but its generated evidence was labelled `AZIMUTH_INCOMPLETE` instead of
`RESOLVED_VERIFIED_ZERO_MAPPED_CELLS`.

The source proof already contained the exact no-overlap identity, positive and
hashed range evidence, full-resolution boundary verification, a boundary
distance beyond the frozen guard, zero mapped cells, and explicit no-imputation
flags. The producer failed to copy that completed verification into the
additional generic `boundary_verified` field required by the downstream sealed
predicate. This affected generated new-pass zero maps; it does not relax the
predicate or change any geometry value, city, season, threshold, or support
rule.

## Correction

1. `finalize_initial_selection_proof` now emits both
   `full_resolution_boundary_verified=true` and `boundary_verified=true` from
   the same successful final full-resolution boundary check.
2. A narrow generated-zero-map evidence schema advances to
   `d0079-generated-zero-map-proof-v1`. The validator invalidates only
   generated new-pass zero-map caches that lack the corrected schema and
   strict accepted proof. Nonzero geometry caches and sealed metadata assets
   remain eligible only after their existing full binding and hash checks.
3. A known-answer test requires a newly finalized exact zero-map proof to pass
   the unchanged strict downstream predicate, while existing tamper tests keep
   rejecting missing, unverified, imputed, unhashed, or inside-guard evidence.
4. The affected zero-map geometry records, dependent cloud/weather bindings,
   augmentation summary, Gate-3 packet, and clean-room verification must be
   regenerated.

All D0069/D0072/D0075 scientific, storage, exclusive-writer, and sealed-data
guards remain unchanged. Gate 3 and every downstream gate remain unapproved
until the corrected packet and independent verification pass.
