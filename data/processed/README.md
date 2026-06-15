# data/processed/

Final, analysis-ready datasets produced by the pipeline and consumed by
notebooks/figures. Reproducible from `raw/` + `interim/`. Contents are
git-ignored.

Current contents (regenerate from `src/`):
- `reference_grid.tif` — Section 1: the 70 m reference grid (EPSG:32612, 1155 × 1339,
  origin 355460/3754380). The geometric anchor every other layer is matched to.
- `analysis_cube_70m.zarr` — **Section 9 deliverable:** a single aligned,
  multi-variable cube with every layer harmonized onto the 70 m grid and time-matched
  to the ECOSTRESS overpasses (steps 47–51). Built by `src/section9_harmonize.py` from
  the Section 2–8 interim layers; reopen with `xr.open_zarr(..., decode_coords="all")`
  to recover the CRS.
  - **dims** `overpass = 66` (the ECOSTRESS LST overpasses — the master axis) `× y = 1155
    × x = 1339`; geometry identical to `reference_grid.tif` (asserted on write **and** on
    reload).
  - **time-varying vars** `(overpass, y, x)`: `lst` (K), `et` (W m⁻²), `esi` (—), `pet`
    (W m⁻²), `vpd` (kPa), `sm` (m³ m⁻³), `ppt_30d`/`ppt_60d`/`ppt_90d` (mm),
    `pdsi`/`spei30d`/`spei90d` (index), `tmean` (°C). **ET/ESI/PET are present only on
    their 45 paired overpasses** (NaN on the other 21; Section 3 caveat — supporting
    evidence only). **Drought is NaN on the 2 earliest pilot overpasses** (2023-06-02/-03,
    before the first 2023 pentad — no containing pentad).
  - **static vars** `(y, x)`, stored once: `ndvi`, `ndmi` (—), `impervious`, `canopy`
    (percent 0–100), `landcover_class` (**uint8 NLCD class codes — categorical**, never
    bilinear), `median_income` (USD), `pct_poc` (percent), `svi` (percentile 0–1).
  - **coords** `overpass_key` (`{orbit}_{scene}_{YYYYMMDDTHHMMSS}`), `time`, `orbit`,
    `scene`, `in_et`, `in_esi`, and the step-49 matches `era5_hour` / `precip_date` /
    `drought_pentad`, plus `y`/`x` and a CF `spatial_ref`.
  - **time matching (step 49):** ERA5 VPD/SM at the **nearest hour**; PRISM precip + tmean
    at the **exact date**; GRIDMET drought at the **pentad whose 5-day window contains the
    overpass date** (NaN if none). ERA5-Land is the only layer Section 9 resamples
    (bilinear, ~9 km → 70 m, a smooth regional background); everything else was already
    gridded with the correct method in its own section.
  - Compressed (Blosc/zstd), chunked one overpass per slice. ~1.8 GB.
- `analysis_overpass_table.parquet` — **Section 9** companion: a small **66-row**
  per-overpass table (`overpass_key`, `time`, `era5_hour`, `precip_date`,
  `drought_pentad`, `in_et`, `in_esi`, and regional area-mean driver values) for a quick
  sanity scan. A full pixel × overpass tidy table is deliberately **not** produced here —
  the analysis pixels are not defined until Section 10 (a per-pixel long table would be
  ~100 M rows and wasteful at this stage). See `src/README.md` (Section 9) for detail.
