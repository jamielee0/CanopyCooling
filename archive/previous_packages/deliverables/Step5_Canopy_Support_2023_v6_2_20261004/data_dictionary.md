# Step 5 predictor support dictionary

All tables are predictor-only. No outcome, coefficient, effect point, confidence endpoint or new inclusion decision is present. Empty fields denote unassessable/empty support; counts of zero remain zero. Candidate pairs, neighbourhoods and resampling configurations repeat observations and are not additional temporal samples.

## endpoint_support.csv

| Column | Meaning |
| --- | --- |
| `city` | Frozen city identifier |
| `orbit` | Acquisition orbit as identifier text |
| `date` | 2023 acquisition date |
| `month` | Calendar month |
| `apparent_solar_hour` | UTC/longitude/equation-of-time clock from the unchanged Step2 convention |
| `source_run_id` | Original paired native-cell run |
| `pair_id` | All15 prospectively recorded candidate contrasts, never selected by effects |
| `n_original_cells` | All unique original paired native cells |
| `n_original_blocks` | All occupied original 1km blocks |
| `f0` | Lower raw-canopy endpoint, fraction |
| `f1` | Upper raw-canopy endpoint, f0+0.10 |
| `halfwidth_fraction` | Descriptive endpoint halfwidth in canopy fraction; no inclusion threshold |
| `spanning_blocks` | Blocks with observed min canopy ≤f0 and max ≥f1 |
| `reference_cells` | All original cells in spanning blocks; models are not restricted here |
| `reference_whole_native_area_km2` | reference_cells×0.0049 km², whole native footprints in native UTM projection; not city-clipped area |
| `reference_cell_fraction` | Reference cells / original cells |
| `endpoint_status` | BLOCK_SPANNED or NO_BLOCK_SPANS_BOTH_ENDPOINTS; neighbourhood proximity alone is insufficient |
| `lower_band_lo` | Lower endpoint: clipped lower edge of closed endpoint neighbourhood |
| `lower_band_hi` | Lower endpoint: clipped upper edge of closed endpoint neighbourhood |
| `lower_cells` | Lower endpoint: all original cells in neighbourhood |
| `lower_blocks` | Lower endpoint: blocks represented by neighbourhood cells |
| `lower_cells_in_reference` | Lower endpoint: neighbourhood cells in exact-spanning reference blocks |
| `lower_fraction` | Lower endpoint: neighbourhood cells / original cells |
| `lower_density_per_fraction` | Lower endpoint: neighbourhood fraction divided by actual clipped band width |
| `upper_band_lo` | Upper endpoint: clipped lower edge of closed endpoint neighbourhood |
| `upper_band_hi` | Upper endpoint: clipped upper edge of closed endpoint neighbourhood |
| `upper_cells` | Upper endpoint: all original cells in neighbourhood |
| `upper_blocks` | Upper endpoint: blocks represented by neighbourhood cells |
| `upper_cells_in_reference` | Upper endpoint: neighbourhood cells in exact-spanning reference blocks |
| `upper_fraction` | Upper endpoint: neighbourhood cells / original cells |
| `upper_density_per_fraction` | Upper endpoint: neighbourhood fraction divided by actual clipped band width |
| `blocks_with_both_neighbourhoods` | Blocks containing at least one observation in each endpoint neighbourhood; may differ from exact spanning blocks |
| `cells_in_both_neighbourhoods` | Cells counted in both closed bands when they touch; explicitly reported to avoid treating counts as disjoint |

## endpoint_covariate_profiles.csv

| Column | Meaning |
| --- | --- |
| `city` | Frozen city identifier |
| `orbit` | Acquisition orbit as identifier text |
| `date` | 2023 acquisition date |
| `month` | Calendar month |
| `apparent_solar_hour` | UTC/longitude/equation-of-time clock from the unchanged Step2 convention |
| `source_run_id` | Original paired native-cell run |
| `halfwidth_fraction` | Descriptive endpoint halfwidth in canopy fraction; no inclusion threshold |
| `endpoint` | Lower or upper endpoint of historical contrast |
| `variable` | One of six unchanged context controls |
| `unit` | Fraction or m as appropriate to control |
| `n` | Number of cell values entering distribution; zero is preserved |
| `min` | min of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `p05` | p05 of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `p25` | p25 of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `median` | median of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `p75` | p75 of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `p95` | p95 of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `max` | max of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `mean` | mean of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `sd` | sd of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |

## design_diagnostics.csv

| Column | Meaning |
| --- | --- |
| `city` | Frozen city identifier |
| `orbit` | Acquisition orbit as identifier text |
| `date` | 2023 acquisition date |
| `month` | Calendar month |
| `apparent_solar_hour` | UTC/longitude/equation-of-time clock from the unchanged Step2 convention |
| `source_run_id` | Original paired native-cell run |
| `model` | Linear (f) or protected quadratic (f,f²) predictor design; no outcome fit |
| `status` | Design estimability or descriptive-distance availability, not an effect/overlap acceptance verdict |
| `n_cells` | All original paired native observations used by design |
| `n_blocks` | Original occupied 1km intercept blocks |
| `n_parameters` | Retained slope/context columns excluding block intercepts |
| `rank` | Rank of column-normalized block-centered design at frozen tolerance 1e-10 |
| `residual_dof` | n_cells − n_blocks − n_parameters |
| `protected_terms` | Mandatory canopy basis columns; one linear, two quadratic |
| `removed_context_terms` | JSON array of context dependencies removed before canopy rank check under inherited rule; no protected canopy term removed |
| `scaled_design_condition` | Largest / smallest singular value of column-normalized within-block design; descriptive numerical conditioning |
| `scaled_design_smallest_singular` | Smallest singular value of that normalized design |
| `partial_canopy_term` | raw_f for linear or raw_f_squared for quadratic |
| `partial_canopy_information` | Sum squared residual of designated canopy term after all other retained columns; fraction² for f or fraction⁴ for f²; no outcome information |
| `partial_canopy_effective_information_blocks` | Inverse sum squared block shares of partial canopy information; not independent days |
| `maximum_partial_canopy_information_share` | Largest block share of partial canopy information |
| `top_five_partial_canopy_information_share` | Sum of five largest such shares |

## design_resampling.csv

| Column | Meaning |
| --- | --- |
| `city` | Frozen city identifier |
| `orbit` | Acquisition orbit as identifier text |
| `date` | 2023 acquisition date |
| `month` | Calendar month |
| `apparent_solar_hour` | UTC/longitude/equation-of-time clock from the unchanged Step2 convention |
| `source_run_id` | Original paired native-cell run |
| `group_km` | 1km or8km whole physical resampling groups, retaining original 1km intercepts |
| `groups` | Number of occupied physical resampling groups |
| `requested` | 1000 design-only multinomial draws per pass/group configuration |
| `linear_estimable` | Draws whose frozen linear Gram matrix retains full rank at 1e-10 |
| `quadratic_estimable` | Draws whose frozen quadratic Gram matrix retains full rank at 1e-10 |
| `paired_estimable` | Draws estimable in both designs using identical physical multiplicities |
| `paired_failed` | Requested minus paired_estimable; no replacement |
| `draw_multiplicity_sha256` | Hash of exact ordered int64 multiplicity vectors for reproducibility |

## cross_city_context_distances.csv

| Column | Meaning |
| --- | --- |
| `city` | Frozen city identifier |
| `orbit` | Acquisition orbit as identifier text |
| `date` | 2023 acquisition date |
| `month` | Calendar month |
| `apparent_solar_hour` | UTC/longitude/equation-of-time clock from the unchanged Step2 convention |
| `source_run_id` | Original paired native-cell run |
| `endpoint` | Lower or upper endpoint of historical contrast |
| `halfwidth_fraction` | Descriptive endpoint halfwidth in canopy fraction; no inclusion threshold |
| `query_cells` | Up to2000 uniformly sampled cells per pass/endpoint/width, without replacement |
| `other_city_reference_cells` | Equal-size other-city reference pool, deduplicated by physical cell_id; max5000 |
| `status` | Design estimability or descriptive-distance availability, not an effect/overlap acceptance verdict |
| `min` | min of dimensionless standardized six-control Euclidean distance; SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `p05` | p05 of dimensionless standardized six-control Euclidean distance; SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `p25` | p25 of dimensionless standardized six-control Euclidean distance; SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `median` | median of dimensionless standardized six-control Euclidean distance; SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `p75` | p75 of dimensionless standardized six-control Euclidean distance; SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `p95` | p95 of dimensionless standardized six-control Euclidean distance; SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `max` | max of dimensionless standardized six-control Euclidean distance; SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `mean` | mean of dimensionless standardized six-control Euclidean distance; SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `sd` | sd of dimensionless standardized six-control Euclidean distance; SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |

## cross_city_reference_profiles.csv

| Column | Meaning |
| --- | --- |
| `city` | Frozen city identifier |
| `endpoint` | Lower or upper endpoint of historical contrast |
| `halfwidth_fraction` | Descriptive endpoint halfwidth in canopy fraction; no inclusion threshold |
| `variable` | One of six unchanged context controls |
| `n` | Number of cell values entering distribution; zero is preserved |
| `min` | min of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `p05` | p05 of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `p25` | p25 of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `median` | median of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `p75` | p75 of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `p95` | p95 of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `max` | max of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `mean` | mean of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |
| `sd` | sd of the named control's units (fraction; elevation/distance_to_water in m); SD uses ddof=1; quantiles use existing numeric convention; empty support is blank, not zero |

