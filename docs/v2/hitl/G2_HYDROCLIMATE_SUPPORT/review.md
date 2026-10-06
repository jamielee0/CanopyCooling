# Gate 2 review — Antecedent hydroclimatic support

**Gate status:** `COMPLETE_AWAITING_HUMAN_APPROVAL`  
**Authorized by:** `D0062`; pre-result rules frozen by `D0063`  
**Next gate remains locked:** `G3`

## Bottom line

Gate 2 rebuilt all three nonthermal predictor definitions for both 30- and 60-day
prior-day windows across the approved 219 physical passes and the 4,880-day summer reference.
The continuous values are primary; every 3×3 count is explicitly descriptive. No predictor
has been adopted as the final study definition, and formal high-demand overlap remains assigned
to Gate 4.

## High-demand support

| Window (days) | Predictor | Wet passes | Dry passes | Wet pass-equivalents | Dry pass-equivalents |
|---:|---|---:|---:|---:|---:|
| 30 | precipitation | 40 | 62 | 32.494 | 53.638 |
| 30 | days since meaningful rain | 32 | 59 | 25.371 | 47.901 |
| 30 | climatic water balance | 34 | 68 | 26.168 | 58.154 |
| 60 | precipitation | 37 | 66 | 30.345 | 58.392 |
| 60 | days since meaningful rain | 35 | 59 | 27.973 | 47.901 |
| 60 | climatic water balance | 44 | 56 | 34.553 | 49.455 |

These pooled totals do not establish a pooled comparison. The within-city absolute-demand
range check is still descriptive:

- 30d precipitation: 5/5 cities have both high-demand wet/dry passes with positive raw-VPD range overlap.
- 30d days since meaningful rain: 4/5 cities have both high-demand wet/dry passes with positive raw-VPD range overlap.
- 30d climatic water balance: 5/5 cities have both high-demand wet/dry passes with positive raw-VPD range overlap.
- 60d precipitation: 5/5 cities have both high-demand wet/dry passes with positive raw-VPD range overlap.
- 60d days since meaningful rain: 4/5 cities have both high-demand wet/dry passes with positive raw-VPD range overlap.
- 60d climatic water balance: 5/5 cities have both high-demand wet/dry passes with positive raw-VPD range overlap.

## Demand–predictor correlations

- 30d precipitation: raw Spearman -0.388 (whole-city-summer 95% interval -0.533 to -0.230).
- 30d days since meaningful rain: raw Spearman 0.396 (whole-city-summer 95% interval 0.226 to 0.556).
- 30d climatic water balance: raw Spearman -0.574 (whole-city-summer 95% interval -0.714 to -0.377).
- 60d precipitation: raw Spearman -0.442 (whole-city-summer 95% interval -0.583 to -0.289).
- 60d days since meaningful rain: raw Spearman 0.432 (whole-city-summer 95% interval 0.287 to 0.579).
- 60d climatic water balance: raw Spearman -0.585 (whole-city-summer 95% interval -0.731 to -0.391).

The pooled rows are descriptive because city climate differences remain a confounding source;
the CSV also reports every city separately. `P - ET0` is retained only as antecedent climatic
water-balance sensitivity because ET0 partly contains atmospheric demand.

## Material support limitations and carry-forward assessment

The days-since metric is heavily right-censored where no ≥5 mm event occurred in the window:

| Window (days) | Atlanta | Los Angeles | Miami | Minneapolis–St. Paul | Phoenix |
|---:|---:|---:|---:|---:|---:|
| 30 | 0/40 | 44/48 | 0/16 | 1/71 | 23/44 |
| 60 | 0/40 | 34/48 | 0/16 | 0/71 | 22/44 |

This is especially material for Los Angeles: 44/48 passes are censored at 31 days in the
30-day definition, producing no high-demand wet or dry tertile observations; the 60-day
definition still has 34/48 censored and no high-demand dry observations. Phoenix is also
substantially censored. The metric remains reported as requested, but it is not a broadly
discriminating five-city primary definition at the frozen 5 mm threshold.

Accumulated precipitation has high-demand wet and dry passes with positive raw-VPD range
overlap in all five cities for both windows, so it is the cleaner primary candidate to carry
into Gate 3. This is a support recommendation, not final adoption. Climatic water balance
remains sensitivity-only: its pooled raw correlation with precipitation is
**0.910** at 30 days and
**0.908** at 60 days, while its demand correlation is
stronger than precipitation's.

## Independent Phoenix sign check

The raw-input implementation reproduced all eight negative June medians. The pooled June
30-day balance median was **-251.648 mm**, satisfying
the prospectively frozen strongly-negative threshold of -100 mm. Maximum disagreement with
the canonical Step-1 series was
**2.84e-14 mm**, with zero
observation-day leakage violations.

## Interpretation boundary

- Precipitation and days since ≥5 mm rain are candidate wetness definitions.
- `P - ET0` is a sensitivity; it is not irrigation, soil moisture, root-zone water, or plant
  water availability.
- A day with ≥5 mm rain is an operational event flag, not proof that the rain reached a tree's
  root zone.
- Clear-domain pass-equivalents remain secondary exposure diagnostics beside physical counts.
- Existing D0060/D0061 deviations remain in the study history; Gate 2 introduced no new
  query or data-access deviation.

## Files to review

1. `pass_hydroclimate_219.csv` — continuous predictors for every approved physical pass.
2. `continuous_distributions.csv` — all quantiles for passes and summer-day references.
3. `demand_predictor_correlations.csv` and `predictor_pair_correlations.csv` — correlations
   and whole-city-summer uncertainty.
4. `high_demand_wet_dry_support.csv` and `high_demand_absolute_vpd_overlap.csv` — physical and
   weighted support with descriptive overlap.
5. `descriptive_3x3_support.csv` — explicitly non-gating grid counts.
6. `city_year_predictor_support.csv` and `seasonal_variance.csv` — interannual support.
7. `phoenix_june_sign_check.csv`, `window_exclusion_audit.csv`, and `checks.json` — known-answer,
   leakage, binding, and sealed-state checks.
8. `figures/continuous_predictor_distributions.png` and
   `figures/high_demand_wet_dry_support.png` — the two essential Gate-2 figures.

## Your decision

- `APPROVE G2` — bind this support audit and authorize G3 nonthermal sampling-design work only.
- `REVISE G2: <change>` — revise this package; do not begin G3.
- `STOP` — preserve all locks and do not continue.
