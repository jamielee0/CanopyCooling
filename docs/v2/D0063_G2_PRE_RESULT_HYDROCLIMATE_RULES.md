# D0063 — Gate 2 pre-result hydroclimate rules

## Status

`FROZEN / PRE-RESULT G2 RULE`

These rules were fixed before computing Gate-2 support results and without opening a
temperature/LST value or other cooling outcome.

## Observation and reference populations

- Primary support population: the 219 retained physical passes approved at Gate 1.
- Reference population: all 4,880 June–September city-days in the checksum-bound 2018–2025
  Step-1 weather record.
- Pass dates use apparent local-solar calendar date.
- Every antecedent window ends on the day before the focal date.

## Frozen predictor definitions

For each 30- and 60-day preceding window:

1. `antecedent_precipitation_*d_mm` is the sum of daily GridMET precipitation in millimetres.
2. A meaningful-rain event is prospectively defined as daily precipitation **at least
   5.0 mm**. `days_since_meaningful_rain_*d` is 1 when the event occurred yesterday and
   ranges through the window length. If no qualifying event occurs in the window, the value
   is right-censored at `window + 1`, with a separate censoring flag.
3. `antecedent_climatic_water_balance_*d_mm` is the sum of daily `P - ET0` in millimetres
   and is a labelled sensitivity only.

The 5 mm rule is an operational surface-rainfall threshold, not a measurement of effective
rainfall for a particular tree, irrigation, infiltration, root-zone water, or soil-moisture
availability. FAO effective-rainfall guidance documents practical methods that disregard
daily rainfall below 5 mm, while also emphasizing that effectiveness depends on local soil,
runoff, storage, and crop conditions. That supports a non-trace-event threshold but not a
plant-water claim. Gate 2 will not tune or compare alternative thresholds after viewing its
support table.

Sources:

- https://www.fao.org/4/x5560e/x5560e03.htm
- https://www.fao.org/4/s2022e/s2022e03.htm

## Support summaries

- Raw continuous values remain primary. Within-city wetness percentiles and the 3×3 grid are
  descriptive only and use the full summer-day reference distribution, not the selected
  satellite passes.
- Higher precipitation and higher balance mean wetter; fewer days since meaningful rain
  means wetter. Direction is stored explicitly.
- Every weighted exposure summary must be accompanied by its physical-pass count.
- Correlation uncertainty resamples whole city-summers, never individual passes.

## Independent Phoenix sign check

A Gate-2 implementation that does not call the existing Step-1 balance function must
recompute Phoenix 30-day balance directly from raw daily `P - ET0`. The check passes only if
all eight June summer medians are negative, the pooled June median is at most -100 mm, the
observation day is excluded with zero violations, and the independent values agree with the
canonical Step-1 series to numerical tolerance.

## Locks

No CMR query, 2026 query or record, temperature/LST value, thermal outcome, holdout result,
or downstream empirical analysis is authorized. Gate 3 remains locked until explicit human
approval of Gate 2.
