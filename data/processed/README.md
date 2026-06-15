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
    evidence only). **Drought is NaN on the 3 earliest pilot overpasses** (two on
    2023-06-02, one on 2023-06-03; before the first 2023 pentad — no containing pentad).
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
- `section10_pixel_class_70m.tif` — **Section 10 deliverable:** the per-pixel
  classification of the paired design (steps 52–57), built by
  `src/section10_classify_pixels.py`. uint8, aligned exactly to `reference_grid.tif`
  (CRS/shape/transform asserted on reload), nodata 255. **Codebook** (in the band tags):
  **0 = excluded/other, 1 = tree-dominated, 2 = reference, 3 = excluded-by-building-
  buffer**. **At the pre-registered start thresholds (`config.NDVI_THR` 0.5,
  `CANOPY_THR` 70 %, `IMPERV_THR` 20 %, not water, `MIN_OBS` 20) the tree and reference
  counts are 0** — the 70 m canopy layer maxes at ≈ 69.5 % (30 m USFS TCC area-averaged to
  70 m never reaches 70 %), so only codes 0 and 3 appear. This is the honest pre-
  registered result; see `section10_threshold_sensitivity.csv` for where pixels appear as
  `CANOPY_THR` is lowered, and `src/README.md` (Section 10, "GATE CONCERN") for the full
  explanation.
- `section10_paired_neighborhoods.csv` — **Section 10:** the paired-neighborhood list
  (`GEOID`, `n_tree_px`, `n_ref_px`) — block groups that contain **both** a tree-dominated
  pixel and a reference pixel (step 55). **Empty at the start thresholds** (0 tree pixels →
  no pairs); 4 paired block groups appear at the canopy = 50 % operating point.
- `section10_threshold_sensitivity.csv` — **Section 10** (step 57): tree/reference/paired
  counts as each threshold (`NDVI_THR`, `CANOPY_THR`, `IMPERV_THR`, `MIN_OBS`,
  `TALL_BUILDING_MIN_AREA_M2`) is varied around its start value, under two baselines
  (`start` = all other thresholds pre-registered; `operating_point` = others swept with
  `CANOPY_THR` at the documented 50 % operating point, so each threshold's effect is
  visible despite the canopy-ceiling). Columns: `varied`, `value`, `baseline`,
  `canopy_thr`, `n_tree_px`, `n_ref_px`, `n_paired_blockgroups`, `is_start`,
  `n_tall_buildings`.
- `section10_validation_sample.csv` — **Section 10** (step 56): a sample of classified
  tree-dominated pixels for visual validation — `pixel_id, row, col, lon, lat, ndvi,
  canopy_pct, impervious_pct, genuine_canopy`. **`genuine_canopy` is left BLANK for the
  user** to mark yes/no over `figures/section10_treepixel_validation_overlay.png` (a
  per-pixel 1 m aerial chip grid). The human agreement rate is **pending user review** —
  an automated *provisional* cross-check is printed by the run but is **not** the reported
  rate. Because the start thresholds yield 0 tree pixels, the sample is drawn at the
  canopy = 50 % operating point (logged; the saved class raster is unaffected).
