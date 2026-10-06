# Step 7 dictionary

## Empirical precision

`comparison` identifies combined June/August, June, August, a supported date deletion, or its deletion-minus-full change. `group_km` is 1 or 8. `quantity` identifies temperature cooling difference, emitted-flux difference, arm-aggregated temperature-equivalent difference, or the paired departure between temperature and equivalent differences. Units are K/+10pp canopy or W/m²/+10pp canopy.

`independent_dates` is the number of distinct acquisition dates required by that comparison; it is not a pixel count or additional temporal replication. `requested`, `estimable` and `failed` count paired spatial draws required for the quantity. `SE` is the bootstrap sample SD and `width95` is the 97.5th-minus-2.5th percentile. Points, endpoints, signs and significance results are excluded from public serialization. `uncertainty_scope` is always `fixed_dates_spatial_only` and `effect_status` is always `SEALED_USER_REQUEST`.

## Resampling audit and covariance

The audit lists original orbit order, occupied physical-union groups, structural absence by pass, per-pass failed draw indices, complete-city draw counts, physical-group identity hashes and multiplicity hashes. A missing group contributes zero sufficient statistics; it is not filled with another location. All original controls remain fixed. A comparison need not discard a draw merely because an unrelated zero-weight date is non-estimable. Complete-city rows are required only to estimate the full covariance matrix.

Four public covariance JSON files in the scientific run directory record temperature estimation-error covariance in squared K/+10pp units. They describe spatial estimation precision, not population day-to-day variability. The synthetic generator uses the 8 km matrices as fixed plug-in inputs. City coordinate systems and draws are independent; there is no cross-city pooling.

## Synthetic production tables

Every row carries `label=SYNTHETIC_DATA`, city, phase, scenario ID, assumed linear amplitude, assumed day SD, spatial correlation fraction, profile and method. An amplitude is a generator parameter: curved or interacting mean terms may change `population_target` from that amplitude. The separate truth table records the exact known target, actual weighted time span, date count, nuisance-model residual degrees of freedom, and true spatial/day variance of that target.

`population_target_coverage` is the fraction of generated intervals covering the scenario's expected weighted scheduled-date contrast. `fixed_dates_target_coverage` evaluates those same intervals against the realized latent dates. `coverage_MCSE` is sqrt(p(1−p)/N) for the population coverage estimate, conditional on the fixed bootstrap bank. `mean_width`, `bias`, `bias_MCSE`, `estimable` and `failed` summarize the independent generated datasets. They are not estimates or tests of an observed canopy effect.

`zero_day_variance_fraction` records truncation of the candidate moment estimator at zero. Its residual degrees of freedom are six for Phoenix and two for Atlanta. `bootstrap_requested` and `bootstrap_estimable` describe the frozen date-resampling bank, reused across independent generated datasets within city/phase. Development and production use different banks and simulation streams. `target_outside_resampled_range_fraction` is a support diagnostic, not a retrospective filter.

The month/arm support audit replays the frozen production bank and counts estimable draws omitting a required month/arm. Rank failure and support loss are reported separately. The within-arm bootstrap preserves singleton dates and therefore cannot estimate their between-day variation.

## Sealed comparisons

The private comparison table adds point, q025, q975 and status fields to the public identifiers. Joint NPZ files retain paired pass effects/draws with orbit order, and Phoenix window NPZ files retain the seven matched comparison/influence arrays at each group size. These contain new empirical effects and are deliberately not linked in the public packet. The two private figures show conditional fixed-date intervals and are not visually reviewed while sealing remains active.
