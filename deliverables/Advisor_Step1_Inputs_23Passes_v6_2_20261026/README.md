# Advisor review: Section 7, Step 1

26 October 2026. This is the input-preparation step from Reza's latest review, not the earlier October results-review sequence. Step 1 is complete. Completion and verification are recorded in `completion.json` and `../../docs/v2/v6_2/execution/advisor_step1_20261026/independent_verification.json`.

## Main file

**`pass_inputs_23.csv`** contains one row per pass: eleven Phoenix and five Atlanta passes from 2023, plus seven existing Phoenix passes from 2019, 2024 and 2025. Use `sample_role` to distinguish them. Original fields in the sixteen 2023 rows are preserved exactly. Cooling fields in the other seven rows are blank; their estimates have not been opened.

The principal additions are:

- `geolocation_categories_by_scene`: each source scene's exact Best/Good/Suspect/Poor category, recovered from checksum-matched ECO_L1B_GEO.002 metadata. There are 40 source scenes: 38 Best and 2 Good. The census accepted Best and Good. No pass is removed, and these labels do not validate actual image alignment.
- `shortwave_W_m2`: HRRR downward shortwave radiation at acquisition time, averaged over the same frozen city domain used for weather.
- `sin_solar_elevation` and `solar_elevation_deg`: solar geometry at the recorded pass time and frozen city reference coordinates. These are city-reference values, not a pixel-by-pixel satellite geometry field.
- `air_temperature_K`, `dewpoint_K`, `VPD_kPa` and `wind_speed_m_s`: the existing weather descriptors for 2023 and the same calculations for the seven other-year passes. VPD remains descriptive.

Shortwave comes from the same HRRR CONUS `wrfsfcf00` analysis product as temperature. ecCodes identifies it as `sdswrf`, with units `W m**-2`. At each bracketing hour, divide domain-mean radiation by the cosine of solar zenith; interpolate that ratio to the acquisition time, then multiply by the acquisition cosine. If one hourly cosine is below 0.1, use only the other ratio. The interpolation fields remain in the CSV so the calculation can be checked.

## Two clarifications resolved with Jamie

The named census CSV often establishes only “Best/Good” jointly. Jamie approved recovering the exact original metadata flags. All required metadata was available locally; the pooled historical labels were not copied as exact “Good” values.

Four Phoenix passes (6281, 33623, 40111, 40376) have an older geolocation-audit pass timestamp about 52 seconds later than the model/selection-table timestamp. Jamie approved retaining the model-table times. The CSV records both times and their difference; `scene_geolocation_provenance.json` preserves each scene's timestamp and source identity. Both conventions use the same bracketing HRRR hours.

## What comes next

Step 2 is the requested pass-level radiation model and figures using the sixteen 2023 passes. Step 3 then predicts the seven other-year outcomes and records a dated, committed prediction note before those estimates are opened. Neither step is executed in this packet. No new cooling fits, synthetic calibration, temperature–energy agreement analysis or quadratic analysis were performed. Nothing was committed, pushed or sent externally.

See `DATA_DICTIONARY.md` for columns and `scene_geolocation_provenance.json` for scene-level sources. Detailed input/code hashes, hourly GRIB provenance, tests and numerical checks are in `../../docs/v2/v6_2/execution/advisor_step1_20261026/`. Cached nonthermal inputs are in `../../outputs/v6_2/scientific/advisor_step1_20261026/`.
