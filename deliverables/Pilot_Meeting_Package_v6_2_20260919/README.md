# v6.2 two-city pilot for precision review

The revised pooled estimator has been run for all five frozen Phoenix passes and five Atlanta passes selected before thermal download. LST and emitted-energy models use the same native cells, controls and whole-block resampling. Empirical coefficients, predictions, bootstrap endpoints and time-contrast values remain sealed. This package contains permitted precision diagnostics and clearly labeled simulations.

| City | Five-pass SE range | Median SE | 8km-group SE range |
| --- | --- | --- | --- |
| Phoenix | 0.0173–0.0330 | 0.0321 | 0.0332–0.0631 |
| Atlanta | 0.0023–0.0089 | 0.0059 | 0.0048–0.0135 |

SE units are kelvin per 10 percentage points of canopy. The approximate 0.10 benchmark is a feasibility reference, not a scale-agreement tolerance or a four-of-five gate. Larger spatial groups test uncertainty sensitivity; passing that benchmark does not establish a time pattern or equivalence.

The four meeting items are:

1. [Audit and sample selection](01_audit_and_sample_selection.md).
2. [All ten precision results](02_precision_and_support.md), with the accompanying CSV and sensitivity tables.
3. [Mixing test and exact conversion](03_mixing_and_standardization.md).
4. [Decisions for Reza](04_decisions_for_Reza.md).

All 280 synthetic city-pass/scenario/contrast combinations are complete. Both total-time comparisons are computed and sealed; neither city has common support for the secondary geometry/season comparison. Twenty-one targeted tests and the output-boundary check pass.

The main unresolved decisions are Reza’s numerical scale tolerance and recorded release of the empirical comparisons after precision review. Full-city expansion remains paused. The protocol stays at v6.2.
