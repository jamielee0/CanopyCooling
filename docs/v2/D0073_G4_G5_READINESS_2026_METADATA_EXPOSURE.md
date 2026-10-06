# D0073 — G4/G5 readiness-audit 2026 metadata exposure

## Status

`RECORDED DEVIATION / CONTAINED / NO REPEAT AUTHORIZED`

At `2026-08-13T23:19:39+09:00`, an independent subagent performing a read-only
readiness audit for future Gates 4 and 5 ran a recursive repository text search
for gate and matching terminology. The search unintentionally matched a
previously stored, embedded single-line CMR response under the searched project
trees and surfaced 2026 public collection/granule link metadata in tool output.

The surfaced category included product asset names, download/browse/documentation
links, and a timestamp encoded in metadata names. An LST asset name was visible,
but no raster, array, band value, temperature/LST value, city result, holdout
result, or other 2026 scientific observation was opened. No network request,
query, or download occurred during this incident. Nothing from the surfaced
metadata was used in the readiness audit or any scientific decision.

The retained tool output was truncated and did not preserve the exact matched
file prefix. The file will not be reopened merely to reconstruct that detail,
because doing so would repeat the prohibited inspection. This evidence
limitation is permanent and must remain explicit.

## Containment

- The recursive search was stopped and is not authorized to be repeated.
- All subsequent readiness reads are restricted to explicit named historical
  governance/code files rather than broad recursive searches.
- The surfaced metadata is excluded from every Gate-3 through Gate-8 source
  binding, result, and conclusion.
- Records must distinguish this incidental repository-metadata exposure from
  the still-unopened 2026 science record and thermal/LST values.
- Future lock claims may not say that no 2026 metadata was ever observed; they
  must preserve D0060, D0061, and this D0073 exposure while stating precisely
  that no 2026 science data or thermal value was opened.

Gate 3 remains governed by its historical 2018–2025 input allowlists. This
incident supplies no authority to query or inspect 2026 again and does not
authorize G3A or any later gate.
