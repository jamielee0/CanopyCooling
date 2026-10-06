# D0080 — Gate-3 validator-integration corrections

## Status

`FROZEN / NONTHERMAL VALIDATOR-INTEGRATION CORRECTIONS`

**Frozen:** `2026-08-16T21:44:49+09:00`

After the D0079 regeneration, all 79 generated new-pass zero-map records carried
the corrected proof and all were classified
`RESOLVED_VERIFIED_ZERO_MAPPED_CELLS`. Packet construction then failed closed
because its zero-map validator accepted only the legacy D0047 document layout,
whose top-level and summary field names differ from the generated D0069 layout.
The clean-room validator had the same legacy-only assumption.

Both validators now use two explicit branches. The legacy branch retains every
D0047 requirement. The generated branch requires the
`d0079-generated-zero-map-proof-v1` schema, D0069 binding and summary identities,
matching city/orbit, `new_d0069` source population, truthful zero-map completion
and status, zero overlaps, closed thermal and 2026 locks, and the same strict
per-scene full-resolution boundary, range-hash, no-imputation, and no-substitution
proof. A stale or missing schema fails closed.

Clean-room replay subsequently found a numeric representation mismatch, not a
scientific disagreement. The source summaries were computed before the mapped
arrays were stored as float32. An exhaustive replay of all 513 nonempty geometry
reconstructions found the largest absolute discrepancies were:

- view-zenith mean: `8.581237047167178e-06` degrees;
- view-zenith 95th percentile: `7.343292232064869e-06` degrees;
- view-zenith median: `9.536743199589637e-07` degrees;
- all other reconstructed numeric summaries: at most
  `2.842170943040401e-14`, apart from ordinary coverage roundoff at
  `1.1102230246251565e-16`.

The clean-room absolute replay tolerance is therefore sealed at `1e-5` with
zero relative tolerance. This is only a float32 serialization allowance and is
orders of magnitude below the frozen view-angle thresholds. Geometry status and
completeness remain exact comparisons.

This record also corrects the abbreviated D0079 decision-log statement. The
global geometry algorithm version remains
`d0069-g3-five-field-geometry-v2`; invalidation is narrowly controlled by the
new zero-map proof schema. Sealed metadata and validated nonzero geometry caches
were not globally invalidated.

No threshold, source value, geometry classification, support rule, design
choice, or access authorization changes. Temperature/LST, holdout outcomes, and
2026 science records remain unopened, and Gate 3 remains unapproved until the
regenerated packet and clean-room verification complete.
