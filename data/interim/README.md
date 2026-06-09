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
