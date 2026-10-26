# Step 1 pass-table columns

One row is one city–orbit pass. The original 2023 columns and their values are inherited from `../../review/current/01_existing_results/pass_results_with_conditions.csv`; no outcome or interval was recomputed. Blank means unavailable or outside this step's access/scope, never zero. Seven other-year rows intentionally have blank cooling, uncertainty and paired energy-diagnostic fields. Their rainfall is also blank because this step did not request new antecedent rainfall extraction.

## Identity and scope

| Column | Meaning |
|---|---|
| `city`, `orbit`, `pass_id` | City and unique pass identity. |
| `local_date`, `date`, `month` | Local acquisition date/month retained from the source selection. |
| `acquisition_utc` | Existing model/selection-table timestamp, including fractional seconds. This drives interpolation. |
| `source_run_id`, `run_id` | Existing run owning the pass; not a new fitted model. |
| `sample_role` | `main_2023` or `other_year_prediction_inputs_only`. |
| `effect_access_status` | Previously released 2023 outcome or other-year outcome not opened pending committed Step 3 predictions. |
| `source_apparent_solar_hour` | Other-year selection-table solar time retained for provenance; use `apparent_solar_hour` for the common calculation. |
| `pass_time_source` | Documents the user-approved model-table convention. |
| `geo_binding_acquisition_utc` | Pass time recorded in the older geometry binding. |
| `geo_binding_minus_model_time_seconds` | Geometry-binding timestamp minus chosen acquisition timestamp; four approved differences near 52 seconds, otherwise zero. |

## Geolocation

| Column | Meaning |
|---|---|
| `geolocation_categories_by_scene` | JSON mapping from orbit_scene identity to exact category; multiple scenes are retained. |
| `geolocation_categories` | Distinct categories present, separated by semicolons. |
| `geolocation_worst_category` | Least favorable category among the source scenes; the per-scene map remains authoritative. |
| `n_source_scenes` | Number of distinct source scenes for this pass, not number of overlapping tiles. |
| `geo_best_scene_count`, `geo_good_scene_count`, `geo_suspect_scene_count`, `geo_poor_scene_count` | Counts of scenes in each exact category. |
| `all_scene_categories_census_usable` | Whether every source scene's category is Best or Good. Not a new inclusion rule or alignment validation. |
| `geolocation_product`, `census_usable_categories`, `geolocation_input_status` | Product, historical accepted categories and recovery status. |

`scene_geolocation_provenance.json` includes the original raw flag, exact GEO granule, metadata path/hash, geometry binding, individual scene time, source LST filenames (names only), and historical census category/raw flag/rule/warning. Exact categories describe every scene in the recorded source bundle; they do not establish coverage of every modeled cell.

## Radiation, sun and weather

| Column | Meaning / units |
|---|---|
| `shortwave_W_m2` | Domain-mean incoming shortwave at acquisition; W/m², cosine-normalized time interpolation. |
| `shortwave_floor_W_m2`, `shortwave_ceiling_W_m2` | Domain-mean radiation at bracketing hours; W/m². |
| `shortwave_floor_normalized`, `shortwave_ceiling_normalized` | Hourly radiation divided by hourly solar cosine; W/m². Blank if that cosine is below 0.1. |
| `shortwave_interpolation_method` | Two-hour ratio interpolation or the prescribed single-hour ratio rule. |
| `hrrr_floor_utc`, `hrrr_ceiling_utc` | Exact bracketing analysis hours. |
| `hrrr_interpolation_weight` | Fraction of elapsed time from lower to upper hour, including acquisition fractional seconds. |
| `solar_cosine_floor`, `solar_cosine_ceiling` | Cosine of solar zenith at the hourly reference times; dimensionless. |
| `sin_solar_elevation` | Sine of elevation, equal to cosine of zenith, at acquisition; dimensionless. |
| `solar_elevation_deg`, `solar_zenith_step1_deg` | Acquisition geometry in degrees, using inherited harmonic-declination code. |
| `solar_latitude_deg`, `solar_longitude_deg` | Frozen city reference coordinates used for solar calculations; degrees. |
| `solar_days_in_year` | 365 or 366, explicitly respecting the 2024 leap year. |
| `apparent_solar_hour` | Common apparent solar clock; hours. Preserved exactly for 2023. |
| `after_noon` | 1 if apparent solar hour >12, otherwise 0; an input only, with no model fitted here. |
| `hrrr_domain_cells` | Number of HRRR grid centers covered by the frozen Census urban-area polygon; each receives equal weight. |
| `hrrr_product`, `hrrr_shortwave_shortName`, `hrrr_shortwave_units` | Product and field identity. Unit text `W m-2` means ecCodes `W m**-2`. |
| `air_temperature_K`, `dewpoint_K` | Domain-mean 2 m air temperature and dewpoint, linearly interpolated in time; kelvin. |
| `wind_speed_m_s` | Mean of cellwise speed computed from 10 m U/V wind, then time-interpolated; m/s. |
| `VPD_kPa` | Mean of cellwise VPD from temperature/dewpoint, then time-interpolated; kPa, descriptive only. |
| `weather_input_status`, `rainfall_input_scope` | Completeness and explicit rainfall scope. |

The several older solar-time and geometry-coverage columns remain untouched as historical provenance. For subsequent Step 2, use the named common `apparent_solar_hour`, `after_noon`, `shortwave_W_m2` and `sin_solar_elevation` columns. Do not replace them with similarly named inherited metadata fields.
