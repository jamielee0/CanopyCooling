# v6.2 — expanded pilot, methodology review and U.S. city screen

**Updated 21 September 2026. Phoenix is now expanded from five to eleven passes; Atlanta remains at five.** The six additional Phoenix passes produced paired temperature/emitted-energy fits and larger-block uncertainty checks. This package records the user's authorized exploratory continuation. It does not claim completion of the full project or professor approval of a full rollout.

## Start here

- [What should change, what the literature supports, and the issues found](01_Methodology_review.md)
- [Which U.S. cities to investigate next, with measured canopy/cloud support](02_Candidate_cities.md)
- [What is ready and missing for Los Angeles](03_Los_Angeles_readiness.md)
- [Expanded gradient plot](pass_gradients_vs_solar_time.png) and [the complete pass table](pass_gradients_exploratory.csv)
- [Observation time versus season](time_season_coverage.png)
- [Candidate-city figure](candidate_city_screen.png) and [numeric screen](candidate_city_screen.csv)

## Did the extension go well?

**Stage 1 estimation remains feasible.** All six added passes produced paired fits, for 24 new fits across 1/2/4/8 km resampling groups. Phoenix now has eleven primary slope estimates. Its primary SE range is 0.0173–0.0542 K per +10 percentage points of canopy; with 8 km resampling groups it is 0.0332–0.0815. All eleven remain below the advisor's approximate 0.10 K precision benchmark. This benchmark is not a scale-agreement tolerance or proof of time-pattern power.

Of 24,000 new bootstrap draws, one failed numerical rank in the 21 September 2023 pass's 8 km variant; that interval uses 999 draws. No primary draw failed and no selected pass was dropped. The new passes still need the full registration/composition checks completed for the original five.

The plot shows that Phoenix's observed late-afternoon gradients are lower than several earlier observations, with variation across dates. Atlanta's five gradients remain substantially smaller. These are cross-date conditional associations, not an identified daily trajectory or a causal explanation of the city difference. The new scatterplot was inspected before any new empirical time model; none was fitted. The initial pilot's earlier plot-order deviation remains documented.

## The most important changes recommended

1. **Fix time uncertainty before reporting a final time contrast.** The inherited routine combines resampling already-noisy pass estimates with an extra Stage 1 noise draw. A controlled calibration found excessive uncertainty: 0.0728 estimated SE versus 0.0442 actual sampling spread in the measurement-noise-only case. A tested day-cluster benchmark without extra jitter is available, but a final model must also address unequal measurement uncertainty and dependence across days/geography. Earlier time-comparison uncertainty is provisional; Stage 1 point gradients are unaffected by this defect.
2. **Check nonlinear canopy response at common canopy levels.** In a clearly labelled synthetic demonstration using the observed canopy/context distributions, the same monotone curved response produces linear gradients of −0.476 in Phoenix and −0.302 in Atlanta K per +10 pp. Correctly specified common-endpoint contrasts recover −0.469 in both. This demonstrates a mechanism; it does not estimate how much of the real city difference is explained by nonlinearity.
3. **Expand time/season support, not only the pass count.** The eleven Phoenix passes remain drawn from an inherited 2023 geometry-screened frame. Only three meet the intended stricter 15° criterion. All eligible study-year opportunities should eventually be audited consistently, without choosing passes based on gradients. Season, clouds, partial footprints and view geometry require explicit diagnostics.
4. **Keep larger-block uncertainty and check changing pixel composition.** Do not select the smallest SE or shrink to the exact-cell intersection of every future pass. Annual canopy/context sensitivity and joint support for standardized predictions remain necessary.

## City-screen outcome

Nineteen urban areas were screened with canopy summaries, full-pagination acquisition metadata and 535 cloud-mask files covering 155 afternoon city-pass opportunities. No new-city temperature imagery was downloaded. Raleigh, Charlotte, Baltimore and Washington–Arlington are strong first candidates; Seattle, Portland, Minneapolis–St Paul and Chicago merit follow-up for broader coverage. Philadelphia, New York, Boston, Houston and Dallas remain useful alternatives with distinct limitations. These are proposed candidates, not a frozen final selection. See the city note for all nineteen and the exact sample design.

## VPD, physical interpretation and disclosure

VPD remains descriptive. The available existing HRRR hourly data yield paired VPD/air-temperature observations for six of eleven Phoenix passes and four of five Atlanta passes; Phoenix's subset correlation is 0.988. Missing weather records are reported, not silently replaced with daily values. The advisor's approximately 0.95 arid-city correlation and 0.3 kPa LA common support remain labelled historical diagnostics. [Descriptive table](descriptive_vpd_temperature.csv) · [Methods and sample counts](descriptive_vpd_summary.json).

Continue calling the estimate **canopy-associated surface cooling**. The emitted-energy comparison uses the same temperature/emissivity retrievals and is not an independent radiance validation. No eight-class unmixing or causal VPD model was added.

The original gradients were disclosed at the user's request before Reza supplied a scale tolerance. This extension is exploratory. The LST pass table/plot has an explicit disclosure record; raw model artifacts and previous time comparisons remain in sealed storage. No final scale-agreement ruling is issued, and a later tolerance cannot be described as blinded to all effect information. A held-out future-data evaluation is an option for confirmatory work.

## Reproducibility

Execution records: `docs/v2/v6_2/execution/advance_20260921/`. New code: `src/v6_2_advance/`. New paired fits: `outputs/v6_2/scientific/pooled_extension_20260921_phoenix/`, with raw model files in the corresponding sealed directory. The original 19 September pilot and meeting package are preserved.

The two mechanism/calibration demonstrations are isolated under `tests/fixtures/synthetic_demo/advance_20260921/` with `SYNTHETIC_DATA` names. They are not empirical cooling results. The 21 existing scientific checks and three new resampling checks pass. See `verification.json` and `SHA256SUMS` for this package's validation and inventory.
