# Step 6 data dictionary

All tables concern the original 2023 sample. Blank numeric fields indicate unavailable or inapplicable values, never zero. No file in this packet contains an empirical canopy-cooling effect.

## Combined conditions and acquisition conditions

`city`, `orbit`, `date` and timezone-aware `acquisition_utc` identify the frozen pass. `apparent_solar_hour` retains Step 2's solar clock. `time_arm` is morning (9.5–11.5), afternoon (15–18) or outside those windows. `window_weight` is the signed frozen Phoenix contrast weight; Atlanta and unused Phoenix dates have zero weight only for this sensitivity.

`hrrr_floor_utc`, `hrrr_ceiling_utc` and `hrrr_interpolation_weight` record exact weather matching. `air_temperature_K` and `dewpoint_K` are Kelvin. `VPD_kPa` is the interpolated hourly mean of cellwise vapour-pressure deficits; it is descriptive. `wind_speed_m_s` interpolates hourly means of cellwise sqrt(u²+v²), rather than converting a mean vector to speed. All are frozen city-domain descriptors, not modeled-cell or station measurements. `weather_status` reports completeness.

`solar_zenith_centroid_deg` and `solar_azimuth_centroid_deg` are calculated from harmonic declination, the domain centroid and apparent solar time. Azimuth is clockwise from north. They are not recovered sensor azimuths. `view_zenith_p95_inherited_deg` remains the archived pass-level statistic.

For each of 1, 3 and 7 days, `rainfall_*d_hour_ended_mm`, `rainfall_*d_status` and `rainfall_*d_product` identify the reported descriptor and its source. Window timing, lag and primary/fallback details must be read from the rainfall table.

## Antecedent rainfall

`window_start_utc` and `window_end_utc` define (start, end], ending at floor(acquisition UTC). `acquisition_minus_window_end_seconds` is the unobserved subhour interval after that endpoint. `days` determines 24, 72 or 168 required hourly accumulation intervals.

`total_mm` is the complete domain total from the explicitly selected product. `MRMS_total_mm` and `MRMS_status` preserve the primary result, including its one missing window. `Stage_IV_total_mm` and `Stage_IV_status` separately describe the protocol fallback. `exact_acquisition_ended_total_mm` is always blank: the hourly product does not identify the exact subhourly target. `exact_window_status` states that limit.

`required_hours`, `available_hours`, `n_domain_cells` and `complete_cell_fraction` describe the selected product's support. A complete MRMS total requires every expected hour and a valid nonnegative value at every fixed domain cell. The full-window Stage IV fallback uses its own fixed grid. There is no single-hour cross-product substitution, gap interpolation or complete-cell subset chosen after missingness.

`hourly_rainfall.csv` contains the primary MRMS hourly domain summaries only. `n_domain_cells`, `valid_cells`, `missing_cells`, `complete_domain` and `mean_mm` expose quality and the fixed spatial denominator. Stage IV hourly cell arrays and their independent full-window result are retained in the scientific run directory; provenance points to each source file.

## Hourly weather and reconciliation

`t2m_mean`, `d2m_mean`, `vpd_mean` and `wind_speed_mean` use K, K, kPa and m/s. `u10_mean` and `v10_mean` are native grid-relative component summaries, not earth-relative wind-direction estimates. `n_domain_cells` records the fixed center-in-domain count. `product` identifies HRRR sfc or the predeclared prs fallback; forecast hour is always zero.

The reconciliation table reports new-minus-old differences and VPD after reproducing the inherited float32 Kelvin decoding. This separates a documented representation difference from a changed atmospheric field or domain.

## Geometry support

`source` and `source_sha256` link the cached evidence. `geometry_acquisition_utc` and its offset from the frozen acquisition verify identity. `evidence_level` distinguishes directly inspected cached arrays from view-only evidence summaries. `n_domain_cells`, `n_view_valid`, `view_coverage_fraction` and p95 values refer to the archived canonical city-domain target grid, not the modeled-cell population.

`joint_view_solar_azimuth_cells` and `azimuth_fraction_of_view_cells` count simultaneous valid view and solar azimuth among valid-view cells. Blanks in view-only records are unknown, not measured zero. `modeled_cell_coverage_status` explicitly records that this separate crosswalk was not established. Old eligibility flags have no current exclusion authority.

## Schedule and coverage

`comparison_schedule.csv` preserves acquisition identity, frozen source run, original cell counts, inherited viewing angle and signed weights. Month/time counts enumerate independent acquisition dates; they are not effective sample sizes. The leave-one-date schedule contains only prospective weights and support statuses. It renormalizes within an existing month/arm while preserving half-month weights; an empty month/arm is marked unsupported. No leave-one-date cooling estimates were computed.
