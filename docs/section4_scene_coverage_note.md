# Sentinel-2 scene-coverage diagnostics

The 60% scene filter is intentionally retained as a broad prefilter. It keeps scenes with
`CLOUDY_PIXEL_PERCENTAGE < 60` and rejects scenes at or above 60%. Per-pixel SCL masking is
the primary cloud, shadow, cirrus, and snow decision. Counts below three are flagged for
review and never used to mask NDVI or NDMI.

<!-- SECTION4_STATIC_START -->
## Section 4 warm-season composites

Keep scenes with CLOUDY_PIXEL_PERCENTAGE < 60%; this is a broad request-size guard. Per-pixel SCL masking is the primary cloud/shadow/snow filter, and post-mask valid-scene counts expose local support.

The warm-season collection contained **201** scenes before the scene prefilter and **182** after keeping `CLOUDY_PIXEL_PERCENTAGE < 60`.

| Index | count artifact | min | median | max | 70 m pixels with count <3 |
|---|---|---:|---:|---:|---:|
| NDVI | available: `s2_ndvi_valid_scene_count_nearest_2023_70m.tif` + `s2_ndvi_low_valid_scene_count_lt3_2023_70m.tif` | 0 | 41.0 | 169 | 2,493 (0.161%) |
| NDMI | available: `s2_ndmi_valid_scene_count_nearest_2023_70m.tif` + `s2_ndmi_low_valid_scene_count_lt3_2023_70m.tif` | 0 | 41.0 | 169 | 2,493 (0.161%) |

Native count GeoTIFFs are exact nonnegative integers. The clearly named 70 m count rasters use nearest-neighbour sampling, with separate uint8 `<3` flags. NDVI/NDMI values are retained regardless of the flag.
<!-- SECTION4_STATIC_END -->

<!-- SECTION4B_TIMESERIES_START -->
## Section 4b time-resolved NDMI

The resumable count cache expects **118** files (one observed count per overpass plus one climatology count per unique day-of-year): **118 present**, **0 missing**.

The same broad scene guard keeps `CLOUDY_PIXEL_PERCENTAGE < 60`; per-pixel SCL masking remains primary. A single before/after scene total is not collapsed across the overlapping time windows, because that would double-count scenes. The non-overlapping warm-season totals are recorded in the Section 4 table above.

| Count variable | min | median | max | 70 m cells with count <3 | count unavailable (-1) |
|---|---:|---:|---:|---:|---:|
| Observed +/-15-day window | 1 | 9.0 | 52 | 9,240 (0.009%) | 0 (0.000%) |
| LOYO climatology window | 0 | 55.0 | 288 | 3,093,090 (3.030%) | 0 (0.000%) |

Count GeoTIFFs and cube variables use nearest-neighbour resampling and exact integer storage. A genuine zero is a valid count. Only `-1` means the count tile has not been retrieved. The separate `<3` flags are diagnostic and never mask NDMI.

Existing median/mean/std tiles cannot reconstruct these counts. Missing files require an authenticated Earth Engine run with `python src/section4b_ndmi_timeseries.py --counts-only`; the command is interruption-safe and reuses completed count tiles.
<!-- SECTION4B_TIMESERIES_END -->
