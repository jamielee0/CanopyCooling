# Results table dictionary

One row is one city-pass and spatial uncertainty variant. Exactly 16 `original` rows precede 48 uncertainty sensitivities. Sensitivity rows reuse the same estimate and cells; they are not additional observations. Canopy fraction ranges from 0 to 1; +10pp means +0.10. Positive cooling is minus the signed temperature change. Units of temperature differences are K, numerically equal to °C differences.

Blank fields are missing or withheld, never zero. Machine-readable definitions are in `data_dictionary.json`. The execution freeze documents clock, area, input identities and SHA256 checksums. No new model or flux conversion was computed.

| Variable | Type / unit | Definition | Missing-value rule |
| --- | --- | --- | --- |
| `city` | string / identifier or ISO8601 | Frozen city identifier | never missing |
| `orbit` | string / identifier or ISO8601 | ECOSTRESS acquisition orbit, retained as identifier text | never missing |
| `variant` | string / identifier or ISO8601 | original (1km intervals) or spatial_uncertainty_2/4/8km; same point model and cells | never missing |
| `source_run_id` | string / identifier or ISO8601 | Original scientific run identity | never missing |
| `source_model_variant` | string / identifier or ISO8601 | paired_primary original point model | never missing |
| `source_resampling_variant` | string / identifier or ISO8601 | paired_primary or spatial_2/4/8km interval source | never missing |
| `acquisition_utc` | string / identifier or ISO8601 | Exact acquisition instant as timezone-aware ISO8601 UTC | never missing |
| `civil_datetime` | string / identifier or ISO8601 | Acquisition in city's IANA civil timezone, explicit UTC offset | never missing |
| `civil_timezone` | string / identifier or ISO8601 | IANA timezone identifier | never missing |
| `local_date` | string / identifier or ISO8601 | Civil acquisition date, YYYY-MM-DD | never missing |
| `collection` | string / identifier or ISO8601 | ECOSTRESS collection identifier as text; retain leading zeros | never missing |
| `source_collection_label` | string / identifier or ISO8601 | Unmodified collection label in released CSV; previous numeric export wrote 2 for 002 | never missing |
| `sample_status` | string / identifier or ISO8601 | 2023 observational pilot; exploratory after prior release | never missing |
| `analysis_crs` | string / identifier or ISO8601 | Original projected city coordinate reference system | never missing |
| `month` | integer / calendar month | Month of local civil acquisition date | never missing |
| `solar_longitude_deg` | number / degree | East-positive frozen geographic-domain centroid longitude | never missing |
| `equation_of_time_min` | number / minute | Harmonic equation-of-time correction, documented in execution freeze | never missing |
| `mean_solar_hour` | number / hour | Computed UTC fractional hour + longitude/15, modulo 24 | never missing |
| `apparent_solar_hour` | number / hour | Computed mean solar hour + equation-of-time/60, modulo 24; plotted x | never missing |
| `source_plot_solar_hour` | number / hour | Unmodified solar_hour in released pass table | never missing |
| `apparent_minus_source_solar_seconds` | number / second | Signed wrapped clock difference in seconds relative to released plot time | never missing |
| `source_mean_solar_hour` | number / hour | Unmodified local_mean_solar_hour from released pass table | blank where that inherited field was absent; use computed apparent_solar_hour |
| `source_apparent_solar_hour` | number / hour | Unmodified apparent_local_solar_hour from released pass table | blank where that inherited field was absent; use computed apparent_solar_hour |
| `source_inherited_solar_hour` | number / hour | Unmodified local_solar_hour_inherited_metadata from released pass table | blank where that inherited field was absent; use computed apparent_solar_hour |
| `signed_slope_T_K_per_canopy_fraction` | number / K / unit canopy fraction | 10 × released signed temperature change per +10pp | never missing |
| `signed_change_T_K_per_10pp` | number / K / +10pp canopy | Released conditional linear temperature change, 0.10 × canopy slope | never missing |
| `cooling_K_per_10pp` | number / K / +10pp canopy | Negative signed temperature change; positive means lower mixed-pixel LST | never missing |
| `spatial_SE_K_per_10pp` | number / K / +10pp canopy | Sample SD (ddof=1) of existing whole-group bootstrap temperature changes | never missing |
| `cooling_q025_K_per_10pp` | number / K / +10pp canopy | Existing 2.5th percentile of sign-reversed bootstrap temperature changes | never missing |
| `cooling_q975_K_per_10pp` | number / K / +10pp canopy | Existing 97.5th percentile of sign-reversed bootstrap temperature changes | never missing |
| `interval_width_K_per_10pp` | number / K / +10pp canopy | 97.5th minus 2.5th percentile, checked against independent public precision | never missing |
| `cluster_sandwich_SE_K_per_10pp` | number / K / +10pp canopy | Previously published cluster-sandwich SE for the same spatial grouping | never missing |
| `interval_method` | string / method | Existing 95% percentile bootstrap; whole physical spatial groups, original 1km block intercepts | never missing |
| `resampling_group_km` | integer / km | Side length of resampling group; does not change the fitted mean model | never missing |
| `resampling_groups` | integer / count | Existing precision record: resampling_groups | never missing |
| `bootstrap_requested` | integer / count | Existing precision record: bootstrap_requested | never missing |
| `bootstrap_estimable` | integer / count | Existing precision record: bootstrap_estimable | never missing |
| `bootstrap_failed` | integer / count | Existing precision record: bootstrap_failed | never missing |
| `bootstrap_seed` | integer / seed | Existing precision record: bootstrap_seed | never missing |
| `signed_flux_change_W_m2_per_10pp` | number / W/m² / +10pp canopy | Reserved paired diagnostic effect field; no coefficient read or conversion in this step | always blank: SEALED_NOT_RELEASED |
| `flux_reduction_W_m2_per_10pp` | number / W/m² / +10pp canopy | Reserved paired diagnostic effect field; no coefficient read or conversion in this step | always blank: SEALED_NOT_RELEASED |
| `signed_equivalent_change_K_per_10pp` | number / K / +10pp canopy | Reserved paired diagnostic effect field; no coefficient read or conversion in this step | always blank: SEALED_NOT_RELEASED |
| `equivalent_cooling_K_per_10pp` | number / K / +10pp canopy | Reserved paired diagnostic effect field; no coefficient read or conversion in this step | always blank: SEALED_NOT_RELEASED |
| `paired_effect_status` | string / status | SEALED_NOT_RELEASED; prior LST reuse does not authorize flux or equivalent display | never missing |
| `flux_spatial_SE_W_m2_per_10pp` | number / W/m² / +10pp canopy | Permitted existing public flux precision for matched spatial grouping, no effect | never missing |
| `flux_interval_width_W_m2_per_10pp` | number / W/m² / +10pp canopy | Permitted existing public flux percentile width; endpoints withheld | never missing |
| `reference_temperature_K` | number / K | Existing September19 fixed reference; metadata only, no new transformation | never missing |
| `reference_emissivity` | number / fraction | Existing September19 fixed reference emissivity | never missing |
| `reference_status` | string / status | Historical original-ten-pass reference metadata; applicability to six additions not established here | never missing |
| `reference_source` | string / relative repository path | Exact numeric reference manifest, hashed in freeze | never missing |
| `n_cells` | integer / count | Unique paired complete native cells in original fit (cell-pass observations) | never missing |
| `n_blocks` | integer / count | Original occupied 1km intercept blocks | never missing |
| `contributing_blocks` | integer / count | Blocks contributing within-block canopy information | never missing |
| `design_rank` | integer / count | Rank of original within-block slope/context design | never missing |
| `residual_degrees_of_freedom` | integer / count | Original fit residual degrees of freedom | never missing |
| `footprint_area_km2` | number / km² | Sum of unique retained whole native-cell footprints: n × 4900 m² / 1e6; reconcile canonical tile audit; not city-clipped area | never missing |
| `footprint_area_status` | string / status | VERIFIED_CANONICAL_WHOLE_CELLS; selected cell centres fall in domain; edge cells are not clipped | never missing |
| `within_block_canopy_Sxx` | number / fraction² | Sum of squared block-demeaned canopy fractions | never missing |
| `within_block_canopy_variance` | number / fraction² | Published within_block_variance; Sxx divided by n_cells | never missing |
| `residualized_canopy_Sxx` | number / fraction² | Canopy information remaining after block intercepts and context controls | never missing |
| `maximum_block_information_share` | number / fraction | Largest block share of residualized canopy information | never missing |
| `top_five_block_information_share` | number / fraction | Sum of five largest residualized information shares | never missing |
| `effective_information_blocks` | number / effective blocks | Inverse sum of squared residualized block information shares | never missing |
| `maximum_slope_design_leverage` | number / fraction | Published maximum single-cell canopy-slope leverage | never missing |
| `removed_context_terms` | string / JSON array | Context terms removed from the original design; no redesign at assembly | never missing |
| `canopy_q0` | number / fraction | Cell-weighted canopy fraction quantile at probability 0, reused from predictor-only support snapshot; no cutoff | never missing |
| `canopy_q0p01` | number / fraction | Cell-weighted canopy fraction quantile at probability 0.01, reused from predictor-only support snapshot; no cutoff | never missing |
| `canopy_q0p05` | number / fraction | Cell-weighted canopy fraction quantile at probability 0.05, reused from predictor-only support snapshot; no cutoff | never missing |
| `canopy_q0p1` | number / fraction | Cell-weighted canopy fraction quantile at probability 0.1, reused from predictor-only support snapshot; no cutoff | never missing |
| `canopy_q0p25` | number / fraction | Cell-weighted canopy fraction quantile at probability 0.25, reused from predictor-only support snapshot; no cutoff | never missing |
| `canopy_q0p35` | number / fraction | Cell-weighted canopy fraction quantile at probability 0.35, reused from predictor-only support snapshot; no cutoff | never missing |
| `canopy_q0p5` | number / fraction | Cell-weighted canopy fraction quantile at probability 0.5, reused from predictor-only support snapshot; no cutoff | never missing |
| `canopy_q0p65` | number / fraction | Cell-weighted canopy fraction quantile at probability 0.65, reused from predictor-only support snapshot; no cutoff | never missing |
| `canopy_q0p75` | number / fraction | Cell-weighted canopy fraction quantile at probability 0.75, reused from predictor-only support snapshot; no cutoff | never missing |
| `canopy_q0p9` | number / fraction | Cell-weighted canopy fraction quantile at probability 0.9, reused from predictor-only support snapshot; no cutoff | never missing |
| `canopy_q0p95` | number / fraction | Cell-weighted canopy fraction quantile at probability 0.95, reused from predictor-only support snapshot; no cutoff | never missing |
| `canopy_q0p99` | number / fraction | Cell-weighted canopy fraction quantile at probability 0.99, reused from predictor-only support snapshot; no cutoff | never missing |
| `canopy_q1` | number / fraction | Cell-weighted canopy fraction quantile at probability 1, reused from predictor-only support snapshot; no cutoff | never missing |
| `view_zenith_p95_deg` | number / degree | Inherited pass p95 sensor view zenith, not mean or solar zenith | never missing |
| `geometry_coverage_status` | string / status | NOT_QUANTIFIED_IN_REUSED_SOURCES; p95 alone does not establish complete cell-level geometry | never missing |
| `view_azimuth_status` | string / status | UNRESOLVED_FROZEN_PILOT_EXCEPTION; do not claim completed azimuth recovery | never missing |
| `geometry_exception_status` | string / status | Frozen 25-degree pilot precision exception retained as inherited metadata | never missing |
| `weather_status` | string / status | Cached linked HRRR interpolation status or missing bracketing hourly records | never missing |
| `air_temperature_K` | number / K | Cached HRRR 2m domain-mean air temperature interpolated at exact acquisition, independently reconciled | blank: MISSING_BRACKETING_HOURLY_RECORDS |
| `VPD_kPa` | number / kPa | Cached HRRR domain-mean VPD interpolated at exact acquisition; descriptive only | blank: MISSING_BRACKETING_HOURLY_RECORDS |
| `source_inherited_VPD_kPa` | number / kPa | Unmodified inherited VPD metadata from released table, kept distinct from linked HRRR fields | blank: inherited metadata absent |
| `weather_bracket_start_utc` | string / ISO8601 UTC | Exact existing hourly bracket used for HRRR interpolation | blank: MISSING_BRACKETING_HOURLY_RECORDS |
| `weather_bracket_end_utc` | string / ISO8601 UTC | Exact existing hourly bracket used for HRRR interpolation | blank: MISSING_BRACKETING_HOURLY_RECORDS |
| `rainfall_prior_1d_mm` | number / mm | Reserved antecedent rainfall total over 1 days before acquisition | always blank: NOT_ACQUIRED |
| `rainfall_prior_3d_mm` | number / mm | Reserved antecedent rainfall total over 3 days before acquisition | always blank: NOT_ACQUIRED |
| `rainfall_prior_7d_mm` | number / mm | Reserved antecedent rainfall total over 7 days before acquisition | always blank: NOT_ACQUIRED |
| `rainfall_status` | string / status | NOT_ACQUIRED; no cached acquisition-linked totals located or retrieved in this step | never missing |
| `source_precision` | string / path or SHA256 | Public source of group/draw accounting and paired precision | never missing |
| `source_ownership_audit` | string / path or SHA256 | Canonical tile ownership/count/area audit used for this pass | never missing |
| `source_predictor_snapshot` | string / path or SHA256 | Predictor-only support freeze reused without opening cached thermal frame | never missing |
| `native_frame_sha256_recorded` | string / path or SHA256 | Historical input-frame checksum from predictor freeze, not a new checksum/read of sealed frame | never missing |
| `source_weather` | string / path or SHA256 | Cached exact-acquisition weather table; raw hourly source in execution manifest | never missing |
