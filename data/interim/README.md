# data/interim/

Intermediate, partially-processed data — reprojected, clipped, merged, or
otherwise transformed but not yet final. Safe to delete and regenerate from
`raw/` via the pipeline. Contents are git-ignored.

Current contents (regenerate from `src/`):
- `ecostress_lst_cube/` — Section 2 quality-controlled LST cube (time, y, x).
- `ecostress_et_cube/` — Section 3 ECOSTRESS PT-JPL evapotranspiration cube
  (`et`, W m⁻²), on the 70 m grid. Supporting evidence only — unreliable over
  built-up areas; restrict to high-tree-fraction pixels (Section 10).
- `ecostress_esi_cube/` — Section 3 evaporative-stress cube (`esi`, dimensionless;
  `pet`, W m⁻²), same grid and caveat.
- `ecostress_{lst,et,esi}_granule_report.csv` — per-tile QC report (coverage,
  drop/flag decisions).
- `overpass_links.parquet` — Section 3 step 22: one row per overpass across the
  LST/ET/ESI cubes, with `in_lst/in_et/in_esi` membership and
  `et_paired_to_lst`/`esi_paired_to_lst` pairing flags keyed to the LST overpasses.
- `s2_{ndvi,ndmi}_warmseason_median_2023_70m.tif` — Section 4 warm-season median
  vegetation/moisture indices on the 70 m grid. **Note:** the single static
  `s2_ndmi_warmseason_median_2023_70m.tif` is **superseded by the Section 4b
  time-resolved NDMI cube below** as the input to Section 11's NDMI water-supply
  z-score (it is retained for the Section 4 NDVI overlay and as the old-vs-new
  agreement baseline).
- `s2_ndmi_timeseries_70m.zarr` — **Section 4b time-resolved Sentinel-2 NDMI** on the
  70 m grid, dims `(overpass=66, y=1155, x=1339)`, vars `observed` / `clim_mean` /
  `clim_std` (NDMI, dimensionless), indexed by the **same 66 `overpass_key`s in the
  same order** as `../processed/analysis_cube_70m.zarr` (coords `overpass_key` / `time`
  / `doy`; CF `spatial_ref`, reopen with `decode_coords="all"`). `observed` = a
  cloud-masked S2 NDMI **median composite within ±15 d of each overpass date** (2023),
  so it **varies overpass-to-overpass** (vs the static composite above); `clim_mean` /
  `clim_std` = the **day-of-year climatology** mean/std of cloud-masked S2 NDMI over
  **2018–2024 EXCLUDING the overpass year** (leave-one-year-out → 2018–2022 + 2024),
  within ±15 d of the day-of-year. Built server-side in Earth Engine from
  `COPERNICUS/S2_SR_HARMONIZED` (SCL-masked, `(B8−B11)/(B8+B11)`, B11 native 20 m →
  70 m bilinear), downloaded per-overpass with the climatology **deduped by unique
  day-of-year** (52 unique windows for 66 overpasses). **This unfreezes the CSI
  water-supply axis**: it supersedes the single static composite as Section 11's NDMI
  z-score input, letting Section 11 compute a proper *temporal* NDMI z-score
  `(observed − clim_mean)/clim_std` (varying in time AND space). Regenerate with
  `python src/section4b_ndmi_timeseries.py`; raw per-overpass GeoTIFFs live in
  `../raw/sentinel2_ndmi_ts/` and are recorded in `../manifest.csv`.
- `nlcd_impervious_2021_70m.tif` — Section 5 NLCD impervious surface, **percent
  (0–100)**, float32, **area-weighted** mean of the 30 m cells per 70 m cell.
- `usfs_tcc_canopy_2025_70m.tif` — Section 5 USFS tree-canopy cover, **percent
  (0–100)**, float32, **area-weighted** mean (USFS TCC v2025-6, CONUS, 2025).
- `nlcd_landcover_class_2021_70m.tif` — Section 5 NLCD land-cover **class**
  (categorical NLCD codes, uint8, nodata 0), **nearest-neighbour** resample —
  never averaged. Class 11 (open water) is used for the Section 10 water exclusion.

  The Section 5 percent-layers are the impervious/canopy "fraction" the protocol
  refers to (kept in percent because the Section 10 thresholds — "below 20
  percent", "above 70 percent" — are in percent). All three align exactly to
  `../processed/reference_grid.tif`. Raw 30 m downloads live in
  `../raw/landcover/` and are recorded in `../manifest.csv`.

Section 7 (precipitation history + drought state):
- `prism_antecedent_precip_70m.zarr` — antecedent precipitation, vars `ppt_30d` /
  `ppt_60d` / `ppt_90d` (**mm**, float32), one slice per warm-season day 2018–2024
  (854). Rolling totals over the **preceding** 30/60/90 days, computed from the full
  PRISM daily series (the Jan-2018 lead-in makes the 90-day window complete from
  each season's start). `ppt_90d` ≥ `ppt_60d` ≥ `ppt_30d` by construction.
- `prism_tmean_70m.zarr` — PRISM mean air temperature (`tmean`, **°C**), warm-season
  days 2018–2024 (854); an independent cross-check on the ERA5-Land air temperature
  (Section 11).
- `gridmet_drought_70m.zarr` — GRIDMET DROUGHT (`pdsi`, `spei30d`, `spei90d`), one
  slice per warm-season pentad 2018–2024 (168).

  All three are **bilinear** resamples of coarse regional fields (PRISM ~4 km,
  GRIDMET ~4.6 km) onto the 70 m grid — regional context, not block-scale detail —
  in EPSG:32612, aligned to `../processed/reference_grid.tif` (reopen with
  `decode_coords="all"` to recover the CRS). Raw daily/pentad clips live in
  `../raw/prism/` and `../raw/drought/`, recorded in `../manifest.csv`.

Section 8 (neighborhood + tree attributes):
- `neighborhood_blockgroups_32612.parquet` — Maricopa block-group polygons
  (EPSG:32612) with `median_income` (ACS B19013_001E), `pct_poc` (%-people-of-colour
  from B03002), `total_pop`, the joined `svi` (`RPL_THEMES`) + themes 1–4, `GEOID`
  and `TRACT_GEOID`. **SVI is inherited from the parent TRACT** (first 11 digits of
  the block-group GEOID): it varies at tract scale, not block-group scale.
- `acs_median_income_70m.tif`, `acs_pct_people_of_colour_70m.tif`,
  `cdc_svi_rpl_themes_70m.tif` — those three block-group attributes rasterized onto
  the 70 m grid by **nearest / value-per-cell** (float32, nodata NaN). Each cell
  carries its neighborhood's value; aligned exactly to `../processed/reference_grid.tif`.
- `phoenix_tree_inventory.parquet` — cleaned ASU "Treelytics" street-tree inventory
  (22,507 trees, EPSG:32612) with `species_botanical`/`species_common`, the PRIMARY
  functional descriptors `water_use` (drought_tolerant/mesic) + `leaf_habit`
  (deciduous/evergreen), and `inventory_year`. **A true planting year is unavailable**
  — no accessible Phoenix inventory exposes one — so `inventory_year` is the **survey
  year** (when the tree was inventoried, ~2010–2021) and **must NOT be read as a
  planting date or used to derive tree age**; the `planting_year` column is present
  but **null for every record** (protocol step 44 retains planting year only "where
  available"). Central-Phoenix coverage, top ~20 species (see `src/README.md`).
- `building_footprints_32612.parquet` — ~1.47 M Microsoft building-footprint polygons
  for the bbox (EPSG:32612), kept as vectors for the Section 10 tall-building
  exclusion buffer. **Fetched programmatically from the Microsoft Planetary Computer
  STAC `ms-buildings` collection** (item `United States_2022-07-06`, signed with
  planetary-computer, Bing level-9 quadkey partitions covering the bbox) — the
  intended primary source, recorded in `../manifest.csv`. (The USBuildingFootprints
  Arizona release is an automatic fallback only if the STAC read fails; it was not
  used.) Large + git-ignored.

  Section 8 raw inputs live in `../raw/acs/`, `../raw/svi/` (user-supplied SVI CSV),
  `../raw/trees/`, `../raw/footprints/` and are recorded in `../manifest.csv`.
