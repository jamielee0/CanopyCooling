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
  vegetation/moisture indices on the 70 m grid.
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
