# D0081 — Gate-3 HRRR checkpoint-envelope correction

## Status

`FROZEN / NONTHERMAL CLEAN-ROOM CHECKPOINT CORRECTION`

**Frozen:** `2026-08-16T21:49:06+09:00`

Clean-room verification reached exact-weather replay after the D0080 geometry
checks passed. The 117-row HRRR manifest and the HRRR checkpoint contained the
same 117 item identifiers, but the checkpoint is a versioned envelope with the
records under `items`. Two verifier paths incorrectly treated the envelope
itself as the item map, producing a missing-key failure before any weather value
comparison.

Both paths now unwrap `items`, while retaining compatibility with the historical
flat-map representation. They fail closed if the resulting item map is empty or
malformed, if a manifest item is missing, if its shard is absent, or if the
recorded checksum differs from the shard bytes. The existing algorithm-version,
geometry-binding, size, and cell-value reproduction checks remain unchanged.

This is a verifier integration correction only. It changes no HRRR value,
geometry value, threshold, support rule, classification, sampling design, or
data-access authorization. Temperature/LST, holdout outcomes, and 2026 science
records remain unopened, and Gate 3 remains unapproved until the regenerated
packet and clean-room verification complete.
