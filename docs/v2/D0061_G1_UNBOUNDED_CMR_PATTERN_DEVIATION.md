# D0061 — Gate 1 unbounded CMR-pattern protocol deviation

## Status

`FROZEN / DISCLOSED SECOND PROTOCOL DEVIATION / QUERYING TERMINATED`

## What happened

While implementing the requested D0060 containment, the AI attempted to preserve a raw
CMR response for an orbit-`11645` Collection 3 metadata search. The query was not bounded
to 2018–2025. CMR treated the wildcard as a substring search and returned ten Collection 3
granule metadata records because `11645` occurred within their 2026 acquisition-time text,
not because their orbit was 11645.

The response was received at `2026-08-13T07:38:28.122Z`. This repeated the prohibited
2026 metadata exposure after D0060's intended containment and is a separate protocol
deviation. It also demonstrates that the response is invalid evidence for the missing
orbit.

## Exposure boundary

- Ten public CMR granule metadata records were returned and their producer IDs were printed
  locally to diagnose the false match.
- No science-data link was followed.
- No raster, array, pixel value, temperature/LST value, thermal outcome, city result,
  holdout result, or analysis result was opened.

## Quarantine

The raw response is retained only as deviation evidence at:

`docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/source_evidence/protocol_deviation_quarantine/DO_NOT_USE_unbounded_pattern_11645_returned_2026_metadata.json`

SHA-256:
`85b41f4e4f51912af544a6b21d1d2504d3dd60bb306399f18495a56c7c872a4c`

It is excluded from Gate-1 source bindings, Collection 3 evidence, scientific counts, and
all availability conclusions.

## Final containment

No further CMR collection or granule query is permitted during the Gate-1 revision. The
revised historical-availability claim may rely only on the already captured, explicitly
date-bounded 2020 and 2024 raw response bodies. G2 remains locked, and all other D0060
containment measures remain binding.
