# Spatial review public table dictionary

All four tables contain nonthermal support or precision diagnostics. New effect points, signs and interval endpoints are absent. The private comparison figures and arrays remain sealed. Counts across uncertainty variants or repeated common-cell distributions are not independent observations.

## spatial_precision_review.csv

| Column | Unit | Meaning | Missing rule |
| --- | --- | --- | --- |
| `city` | identifier or ISO date | Frozen pilot city | never missing |
| `orbit` | identifier or ISO date | Acquisition orbit, identifier text | never missing |
| `date` | identifier or ISO date | Acquisition date in 2023, YYYY-MM-DD | never missing |
| `kind` | category | Constituent original/common/registration precision, fresh joint common-minus-original difference, or validated archived fixed-support difference | never missing |
| `variant` | label | Explicit fit or uncertainty configuration; do not treat variants as independent acquisitions | never missing |
| `source_run_id` | identifier or ISO date | Original cached frame/model run identity | never missing |
| `group_km` | km | Whole spatial-group side length; mean models retain 1km block intercepts | never missing |
| `n_cells` | cells | Constituent fit sample; for joint difference, common sample size—original size is in support table | never missing |
| `n_blocks` | blocks | Constituent fit blocks; for joint difference, common 1km blocks | never missing |
| `groups` | groups | Resampling groups; joint differences use union of occupied original/common physical groups | never missing |
| `bootstrap_requested` | draws | Requested existing or fresh resampling draws | never missing |
| `bootstrap_estimable` | draws | Draws estimable jointly in both model spaces and, for joint difference, both populations | never missing |
| `bootstrap_failed` | draws | Requested minus estimable draws; no pass selection to rescue nonestimability | never missing |
| `T_SE_K_per_10pp` | K/+10pp | Sample SD of temperature cooling or specified paired cooling-difference draws | precision blank only if NOT_ESTIMABLE; never substitute zero |
| `T_width95_K_per_10pp` | K/+10pp | 95% percentile interval width; no point or endpoints disclosed | precision blank only if NOT_ESTIMABLE; never substitute zero |
| `M_SE_W_m2_per_10pp` | W/m²/+10pp | Sample SD of matched emitted-flux change/difference draws; precision only | precision blank only if NOT_ESTIMABLE; never substitute zero |
| `M_width95_W_m2_per_10pp` | W/m²/+10pp | Matched flux 95% interval width; point and endpoints remain sealed | precision blank only if NOT_ESTIMABLE; never substitute zero |
| `interval_method` | method | Existing constituent/matched or new joint whole-block percentile bootstrap; labelled explicitly | never missing |
| `pairing_status` | status | What is proven about physical sample and draw correspondence; constituent intervals do not establish difference intervals | never missing |
| `effect_status` | status | SEALED_USER_REQUEST on every precision row | never missing |

## canopy_context_distributions.csv

| Column | Unit | Meaning | Missing rule |
| --- | --- | --- | --- |
| `city` | identifier or ISO date | Frozen pilot city | never missing |
| `orbit` | identifier or ISO date | Acquisition orbit, identifier text | never missing |
| `date` | identifier or ISO date | Acquisition date in 2023, YYYY-MM-DD | never missing |
| `source_run_id` | identifier or ISO date | Original cached frame/model run identity | never missing |
| `population` | field name, unit, population or count | original / retained_all11 / excluded_from_all11; no support cutoff | never missing |
| `variable` | field name, unit, population or count | One of canopy_fraction and six frozen controls | never missing |
| `unit` | field name, unit, population or count | fraction or m | never missing |
| `n` | field name, unit, population or count | Number of unique native-cell observations contributing to the predictor distribution | never missing |
| `mean` | same unit as variable | Cell-weighted predictor mean | blank for empty population; SD also blank if fewer than two cells |
| `sd` | same unit as variable | Sample SD of predictor values, ddof=1 | blank for empty population; SD also blank if fewer than two cells |
| `q00` | same unit as variable | Cell-weighted quantile at probability 0; q00=min, q100=max | blank only for an empty population |
| `q01` | same unit as variable | Cell-weighted quantile at probability 0.01; q00=min, q100=max | blank only for an empty population |
| `q05` | same unit as variable | Cell-weighted quantile at probability 0.05; q00=min, q100=max | blank only for an empty population |
| `q10` | same unit as variable | Cell-weighted quantile at probability 0.1; q00=min, q100=max | blank only for an empty population |
| `q25` | same unit as variable | Cell-weighted quantile at probability 0.25; q00=min, q100=max | blank only for an empty population |
| `q50` | same unit as variable | Cell-weighted quantile at probability 0.5; q00=min, q100=max | blank only for an empty population |
| `q75` | same unit as variable | Cell-weighted quantile at probability 0.75; q00=min, q100=max | blank only for an empty population |
| `q90` | same unit as variable | Cell-weighted quantile at probability 0.9; q00=min, q100=max | blank only for an empty population |
| `q95` | same unit as variable | Cell-weighted quantile at probability 0.95; q00=min, q100=max | blank only for an empty population |
| `q99` | same unit as variable | Cell-weighted quantile at probability 0.99; q00=min, q100=max | blank only for an empty population |
| `q100` | same unit as variable | Cell-weighted quantile at probability 1; q00=min, q100=max | blank only for an empty population |

## footprint_and_reference_support.csv

| Column | Unit | Meaning | Missing rule |
| --- | --- | --- | --- |
| `city` | identifier or ISO date | Frozen pilot city | never missing |
| `orbit` | identifier or ISO date | Acquisition orbit, identifier text | never missing |
| `date` | identifier or ISO date | Acquisition date in 2023, YYYY-MM-DD | never missing |
| `source_run_id` | identifier or ISO date | Original cached frame/model run identity | never missing |
| `original_cells` | cells | Original retained paired native-cell population for the pass | never missing |
| `original_blocks` | blocks | Occupied original 1km intercept blocks | never missing |
| `reference_f0` | canopy fraction | Historical fixed lower endpoint; not reselected to optimize results | never missing |
| `reference_f1` | canopy fraction | Historical f0+0.10 endpoint | never missing |
| `reference_cells` | cells | All original cells in blocks whose observed canopy min/max cover both frozen endpoints | never missing |
| `reference_supporting_blocks` | blocks | Number of blocks whose observed raw canopy range covers both endpoints | never missing |
| `reference_status` | status | SUPPORTED or NOT_SUPPORTED_NO_REFERENCE_BLOCKS; no minimum replacement count | never missing |
| `common_all11_cells` | cells | Exact unique native-cell intersection over all11 Phoenix passes | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `common_all11_blocks` | blocks | Occupied original 1km block identities in the common sample | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `common_all11_area_km2` | km² | Sum of common unique whole 70m cells in Phoenix UTM12: cells×0.0049; not city-clipped area | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `common_all11_retained_fraction` | fraction | Common cells divided by this pass's original cells | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `excluded_cells` | cells | Original cells outside the all11 intersection; original minus common | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `common_scope` | status | Phoenix intersection only; Atlanta fields marked NOT_APPLICABLE_PHOENIX_INTERSECTION | never missing |
| `original_maximum_block_information_share` | fraction | original population: Largest residualized canopy-information share of a block | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `original_top_five_block_information_share` | fraction | original population: Sum of the five largest residualized block-information shares | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `original_effective_information_blocks` | effective blocks | original population: Inverse sum of squared residualized information shares; not actual independent blocks | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `original_maximum_slope_design_leverage` | fraction | original population: Published maximum single-cell slope-design leverage | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `original_within_block_canopy_variance` | fraction² | original population: Block-demeaned canopy Sxx divided by cell count | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `original_residualized_canopy_Sxx` | fraction² | original population: Canopy information after block intercepts and context adjustment | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `common_maximum_block_information_share` | fraction | common population: Largest residualized canopy-information share of a block | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `common_top_five_block_information_share` | fraction | common population: Sum of the five largest residualized block-information shares | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `common_effective_information_blocks` | effective blocks | common population: Inverse sum of squared residualized information shares; not actual independent blocks | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `common_maximum_slope_design_leverage` | fraction | common population: Published maximum single-cell slope-design leverage | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `common_within_block_canopy_variance` | fraction² | common population: Block-demeaned canopy Sxx divided by cell count | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |
| `common_residualized_canopy_Sxx` | fraction² | common population: Canopy information after block intercepts and context adjustment | common fields blank for Atlanta: NOT_APPLICABLE_PHOENIX_INTERSECTION |

## inherited_residual_spatial_diagnostics.csv

| Column | Unit | Meaning | Missing rule |
| --- | --- | --- | --- |
| `city` | identifier or ISO date | Frozen pilot city | never missing |
| `orbit` | identifier or ISO date | Acquisition orbit, identifier text | never missing |
| `boundary_km` | km | Historical 1km/2km group-boundary residual-neighbor diagnostic | never missing |
| `cross_boundary_neighbor_pairs` | pairs | Historical cardinal native-neighbor pairs crossing the specified group boundary | never missing |
| `interpretation` | text | Historical diagnostic warning: correlation is neither a p-value nor an effect sign | never missing |
| `LST_K_residual_cross_boundary_correlation` | correlation | Inherited temperature residual correlation across neighboring cells at group boundaries | never missing |
| `M_W_m2_residual_cross_boundary_correlation` | correlation | Inherited emitted-flux residual neighbor correlation | never missing |
| `source` | identifier or ISO date | Historical source table path | never missing |

