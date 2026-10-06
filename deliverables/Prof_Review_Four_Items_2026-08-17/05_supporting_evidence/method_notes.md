# Gate 1 methods and count definitions

## Unit of observation and deduplication

The independent census unit in this checkpoint is one **physical city–orbit
observation**. A pass can intersect multiple adjacent ECOSTRESS scenes and MGRS tiles.
Those tiled products remain listed in the ledger for provenance, but they do not become
additional atmospheric situations. The raw metadata census contains 13,577 tiled product
records. Latest-revision selection removes two superseded records, leaving 13,575 selected
products grouped into 2,968 unique city–orbit observations.

The `observation_id` explicitly encodes city, zero-padded orbit, and the full adjacent-scene
group. The ledger also carries the upstream `scene_key`, official orbit–scene key where
enriched metadata exists, source-granule list, and counts before and after revision
selection.

## Attrition and applied view rule

All stage counts through 219 are physical observations. The definitive geometry rule was
applied on `ECO_L1B_GEO.002`: at least 0.95 valid domain coverage and pass-level p95 absolute
view zenith no greater than 20 degrees. The 31 candidates whose required L1B scene evidence
was unavailable were excluded before geometry; they were not assigned zero coverage and no
adjacent scene was substituted.

The 102 final records are **individual early/late-stratum-eligible physical passes** in the
10–12 or 16–18 local-solar-time strata. They are not 102 matched morning–afternoon pairs,
and Gate 1 establishes no empirical morning–afternoon comparability. The other 117 retained
passes are in the 12–14 or 14–16 midday strata.

## Pass-equivalent formula

For retained physical pass *i*:

`w_i = n_clear_pixels_independent_of_view_i / n_domain_pixels_cloud_i`

and the reported pass-equivalent exposure is `PE = sum_i(w_i)`. This produces 159.087084
for all 219 retained physical passes and 72.689029 for the 102 early/late-stratum-eligible
passes. It is a **secondary clear-domain exposure diagnostic**. Without usable
tree/reference counts and matching yields, it cannot quantify the reliability of a
within-pass cooling contrast. It is also not an independent observation count, an effective
sample size, or proof of 159 distinct atmospheric situations.

The per-pass table reports the clear-domain numerator, denominator, cloud/fill partition,
and fraction. Usable tree and reference pixel counts are explicitly unavailable at this
checkpoint; blank values are paired with a machine-readable status rather than treated as
zeros. They are assigned to the mandatory named `G3A_NONTHERMAL_TREE_REFERENCE_YIELD`
checkpoint. G3A will compute pre-outcome eligible tree/reference pixels and nonthermal
matching yields without reading a temperature/LST value, after G3 freezes the design and
before G4, G5, or G7 may proceed.

## Why 413 weather timestamps correspond to 219 passes

All 219 acquisition times fall between integer UTC hours. Linear interpolation therefore
uses a floor-hour and a ceiling-hour input for each pass: 438 pass–hour links. Twenty-five
analysis hours are shared by two cities, so deduplication yields 413 unique HRRR assets.
There are no same-city duplicate pass-hour links. HRRR timestamps count weather assets,
not satellite observations.

## Missing-31 audit

The missing-candidate table joins each candidate to the already frozen Step-1 daily
condition axes on local-solar date. The demand value is therefore a **daily proxy**, not
the acquisition-time HRRR value that would have been computed only after geometry passed.
The proxy can identify possible concentration but cannot reveal the definitive
acquisition-time condition cell, whether a missing candidate would pass geometry, its cloud
weight, or its eventual tree/reference support. The audit item therefore remains
`OPEN_WITH_PROXY_EVIDENCE`.

## Collection 3 semantics and current availability

The official Collection 3 tiled product documents separate `view_zenith.tif` and
`cloud.tif` assets. View-zenith NaN and cloud value 255 are fill/missing support and must
not be converted to a physical angle or cloud class. Two date-bounded CMR probes returned
no Collection 3 granules for the 2020 or 2024 study summers. Both raw response bodies and
their SHA-256 hashes are preserved. Thus Collection 3 is a technically valid future
recovery route, but it does not recover the 31 candidates now. Recheck at G3; do not
interpret the current zero as permanent absence.

## Protocol deviations

The first Gate-1 draft queried 2026 public granule metadata as a positive control, violating
the approved no-query boundary. During revision, an unbounded wildcard query separately
matched text inside ten 2026 acquisition timestamps. D0060 and D0061 record both events.
The responses are excluded from all counts and conclusions; one retained raw response is
quarantined solely as deviation evidence. No science-data link, temperature/LST value,
thermal outcome, holdout result, or 2026 science value was opened. Gate 1 therefore does
not claim clean protocol compliance.
