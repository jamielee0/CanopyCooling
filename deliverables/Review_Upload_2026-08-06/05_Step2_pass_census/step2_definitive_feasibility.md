# Step 2 definitive feasibility memo

**Gate: STOP.**

## Evidence

- Expected cloud-screened total: 159.1 (minimum 100).
- Expected cloud-screened passes by city: {'atlanta': 24.4, 'los_angeles': 42.4, 'miami': 12.4, 'minneapolis_st_paul': 41.7, 'phoenix': 38.1}.
- Expected cloud-screened counts by pooled time stratum: {'10-12': 40.0, '12-14': 43.1, '14-16': 43.3, '16-18': 32.7}.
- Off-diagonal expected_pass_equivalents: {'demand_high__antecedent_wet': 26.17, 'demand_low__antecedent_dry': 0.55} (minimum 10 per corner).
- Step-2 checks passed: 6/6.

## Comparison with Step 1

# M1.1 — Weather-condition feasibility gate

**Status:** Provisional feasibility screen; this is not a final identifiability decision.

**Decision:** `cross_city_separation_only`

Proceed only as a cross-city comparison, state the city-confounding limitation, and consider adding a sixth city.

## City evidence

| City | Clear valid days | High-demand / wet | Low-demand / dry | Combined share | Spearman ρ | Within-city support |
|---|---:|---:|---:|---:|---:|:---:|
| atlanta | 133 | 11 | 2 | 9.8% | 0.53 | no |
| los_angeles | 659 | 53 | 29 | 12.4% | 0.32 | yes |
| miami | 68 | 2 | 2 | 5.9% | 0.33 | no |
| minneapolis_st_paul | 263 | 31 | 5 | 13.7% | 0.54 | yes |
| phoenix | 697 | 29 | 14 | 6.2% | 0.52 | no |

## Window sensitivity

The qualitative support threshold changes between 30 and 60 days for: atlanta, miami, minneapolis_st_paul. Both windows must be retained in later steps.

## Documented diagnostic failures

Phoenix's 30-day balance is negative in June in 8/8 summers, but the July median rises above the June median in only 3/8. The sign check passes; the strict annual July-rise check does not. Monsoon timing varies, so the plotted trajectory and both antecedent windows remain required rather than treating this diagnostic as uniform support.

## Predeclared screening rule

A city passes this screen when combined clear-sky corner share is at least 10%, each corner has at least 5 days, and |Spearman ρ| is below 0.80. The strong case requires at least 3 cities.

## Limit

This is a feasibility screen, not proof of identifiability. Step 2 overpass-time support, Step 3 simulation, common-support diagnostics, and model concurvity remain binding.

This Step-2 result supersedes the daily-weather-only Step-1 screen because it uses actual usable pass dates and demand at acquisition time. It remains a feasibility screen; Step 3 determines power and minimum detectable effects.
