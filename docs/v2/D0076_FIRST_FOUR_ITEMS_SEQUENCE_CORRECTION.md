# D0076 — First-four-items reporting sequence correction

## Status

`FROZEN / REPORTING CORRECTION / PIPELINE PAUSED`

**Frozen:** `2026-08-14T00:38:00+09:00`

The feedback required four review items before further pipeline work: the
attrition table, pass-equivalent formula, applied view-angle threshold and
threshold results, and within-city wet/dry support. Gate 1 had computed the
underlying evidence, and D0069 later authorized bounded historical nonthermal
geometry/azimuth/cloud/weather augmentation, but the requested reviewer-facing
four-item package had not been delivered first.

The active D0069 geometry run was therefore paused with 500 validated pass
checkpoints preserved. No cloud, weather, final selector, G3A, Gate 4+, Task 2,
holdout, or thermal/LST work was started by this resumed run. The package at
`docs/v2/hitl/FIRST_FOUR_ITEMS/` now precedes any further augmentation. Its
headline numbers are independently recomputed by a standalone, network-free
verifier that imports no pipeline module.

This is a reporting-sequence correction. It does not revoke D0069, select a
design, promote Miami, choose a holdout, or authorize outcome access. The
augmentation remains paused after publication of the package. No 2026 science
data or thermal/LST value was opened; D0060, D0061, D0073, and D0074 remain
disclosed.
