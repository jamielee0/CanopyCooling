# Precision and support for all ten city-passes

| City | Pass | Cells | Blocks with variation | SE K per 10pp | Bootstrap width K per 10pp | Within-block Sxx |
| --- | --- | --- | --- | --- | --- | --- |
| phoenix | phoenix:27963 | 516781 | 3220 | 0.0173 | 0.0677 | 372.57 |
| phoenix | phoenix:28024 | 519066 | 3084 | 0.0330 | 0.1313 | 391.73 |
| phoenix | phoenix:28706 | 556672 | 3235 | 0.0321 | 0.1245 | 427.22 |
| phoenix | phoenix:28828 | 556673 | 3235 | 0.0292 | 0.1156 | 427.22 |
| phoenix | phoenix:28909 | 409964 | 2737 | 0.0322 | 0.1269 | 319.57 |
| atlanta | atlanta:27835 | 485177 | 7266 | 0.0061 | 0.0245 | 27657.22 |
| atlanta | atlanta:27896 | 510119 | 7501 | 0.0043 | 0.0168 | 29378.59 |
| atlanta | atlanta:27916 | 481257 | 7178 | 0.0023 | 0.0089 | 27277.93 |
| atlanta | atlanta:28145 | 253835 | 4894 | 0.0089 | 0.0350 | 13999.49 |
| atlanta | atlanta:28598 | 237294 | 4742 | 0.0059 | 0.0225 | 13009.91 |

The standard errors are the SD of 1,000 paired whole-1km-block bootstrap slope draws, scaled by 0.10. The interval column is q97.5 minus q2.5; endpoints and signs are sealed. Sxx is the sum of squared within-block canopy deviations in fraction-squared units. No 0.20/0.10 canopy-span filter or arbitrary pass-information minimum is used. All finite, estimable blocks can contribute. The full CSV additionally reports residualized canopy information, information concentration, effective information blocks, rank, leverage, resample failures and emitted-energy precision in W/m² per 10 percentage points.

| City | Five-pass SE range | Median SE | 8km-group SE range |
| --- | --- | --- | --- |
| Phoenix | 0.0173–0.0330 | 0.0321 | 0.0332–0.0631 |
| Atlanta | 0.0023–0.0089 | 0.0059 | 0.0048–0.0135 |

Four cardinal ±1-cell shifts, an exact common-cell subset across five passes, and 2km groups are in 02_precision_sensitivities.csv. The separately frozen 4km and 8km group checks are in 02_larger_spatial_groups.csv. Neighbor residual correlations are diagnostic evidence of spatial dependence; larger-group uncertainty does not change the mean model or select passes. No expected cooling sign is used. Changes in effect magnitude under registration/composition remain sealed for review; precision stability alone does not certify effect stability.

Canopy information is distributed as follows (shares are fractions):

| city | pass_id | contributing_blocks | effective_information_blocks | maximum_block_information_share | top_five_block_information_share |
| --- | --- | --- | --- | --- | --- |
| phoenix | phoenix:27963 | 3220 | 2193.1 | 0.00149 | 0.00654 |
| phoenix | phoenix:28024 | 3084 | 2099.1 | 0.00153 | 0.00673 |
| phoenix | phoenix:28706 | 3235 | 2237.5 | 0.00140 | 0.00619 |
| phoenix | phoenix:28828 | 3235 | 2237.5 | 0.00140 | 0.00619 |
| phoenix | phoenix:28909 | 2737 | 1749.6 | 0.00172 | 0.00796 |
| atlanta | atlanta:27835 | 7266 | 4565.5 | 0.00115 | 0.00526 |
| atlanta | atlanta:27896 | 7501 | 4800.2 | 0.00108 | 0.00488 |
| atlanta | atlanta:27916 | 7178 | 4521.7 | 0.00115 | 0.00519 |
| atlanta | atlanta:28145 | 4894 | 2667.6 | 0.00219 | 0.00801 |
| atlanta | atlanta:28598 | 4742 | 2457.6 | 0.00229 | 0.00939 |

Residual cross-boundary neighbor correlations are provided in `02_residual_spatial_dependence.csv`; they motivate examining the larger-group standard errors.

Eleven of 90,000 requested spatial resamples were rank-deficient, all in Phoenix sensitivity fits. The estimator reports and omits those draws; every primary fit had 1,000 estimable draws. No pass was removed.

| city | pass_id | variant | bootstrap_requested | bootstrap_estimable | bootstrap_failed |
| --- | --- | --- | --- | --- | --- |
| phoenix | phoenix:28024 | registration_dx0_dy1 | 1000 | 999 | 1 |
| phoenix | phoenix:27963 | common_cells | 1000 | 999 | 1 |
| phoenix | phoenix:28024 | common_cells | 1000 | 999 | 1 |
| phoenix | phoenix:28706 | common_cells | 1000 | 999 | 1 |
| phoenix | phoenix:28828 | common_cells | 1000 | 999 | 1 |
| phoenix | phoenix:28909 | common_cells | 1000 | 999 | 1 |
| phoenix | phoenix:28024 | spatial_8km | 1000 | 997 | 3 |
| phoenix | phoenix:28909 | spatial_8km | 1000 | 998 | 2 |
