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
  buffer**. Built at the **operating thresholds** (`config.NDVI_THR` 0.5, `CANOPY_THR`
  **40 %** [operating; 70 % pre-registered is unachievable at 70 m — the canopy layer maxes
  at **69.53 %**, so 30 m USFS TCC area-averaged to 70 m never reaches 70 %], `IMPERV_THR`
  20 %, not water, `MIN_OBS` 20): **195 tree pixels, 6 019 reference pixels, 187 667 px
  excluded by the building buffer**. The 40 % operating `CANOPY_THR` is the sweep-driven
  point chosen via the ≥10-paired-neighborhood rule (40 % floor); see
  `section10_threshold_sensitivity.csv` for the full canopy dependence and `src/README.md`
  (Section 10, "OPERATING `CANOPY_THR`") for the full explanation.
- `section10_paired_neighborhoods.csv` — **Section 10:** the paired-neighborhood list
  (`GEOID`, `n_tree_px`, `n_ref_px`) — block groups that contain **both** a tree-dominated
  pixel and a reference pixel (step 55). At the operating `CANOPY_THR = 40 %` there are
  **9 paired block groups** (a thin paired design — a genuine limitation for the Section 14
  threshold estimate, which must be reported with this caveat). At the pre-registered 70 %
  bar it would be empty (0 tree pixels → no pairs).
- `section10_threshold_sensitivity.csv` — **Section 10** (step 57): tree/reference/paired
  counts as each threshold (`NDVI_THR`, `CANOPY_THR` [swept **35 → 70 %**], `IMPERV_THR`,
  `MIN_OBS`, `TALL_BUILDING_MIN_AREA_M2`) is varied, under two baselines:
  `operating_point` (other thresholds pre-registered, `CANOPY_THR` at the **40 %**
  operating point — so each threshold's effect is visible) and `preregistered`
  (`CANOPY_THR` held at the **70 %** pre-registered bar — every row **0**, the 69.53 % data
  ceiling). The full canopy sweep makes the dependence on lowering the bar explicit (70 %
  → 0 px; 50/45/40 % → 4/7/9 paired). Columns: `varied`, `value`, `baseline`,
  `canopy_thr`, `n_tree_px`, `n_ref_px`, `n_paired_blockgroups`, `is_operating` (the live
  operating value of each swept threshold), `is_operating_point` (the **adopted** operating
  `CANOPY_THR` row), `n_tall_buildings`.
- `section10_validation_sample.csv` — **Section 10** (step 56): a sample of classified
  tree-dominated pixels for visual validation — `pixel_id, row, col, lon, lat, ndvi,
  canopy_pct, impervious_pct, genuine_canopy`. **`genuine_canopy` is left BLANK for the
  user** to mark yes/no over `figures/section10_treepixel_validation_overlay.png` (a
  per-pixel 1 m aerial chip grid). The human agreement rate is **pending user review** —
  an automated *provisional* cross-check is printed by the run but is **not** the reported
  rate. The sample is drawn at the operating `CANOPY_THR = 40 %` — exactly the tree pixels
  that enter the analysis.
- `section11_zscores_70m.zarr` — **Section 11 deliverable:** standardized-anomaly
  (z-score) fields for the Compound-Stress-Index stress variables, built by
  `src/section11_anomalies.py` (steps 58–61). Reopen with
  `xr.open_zarr(..., decode_coords="all")`.
  - **dims** `overpass = 66 × y = 1155 × x = 1339`; geometry identical to
    `reference_grid.tif` (asserted on write **and** on reload).
  - **z-score vars** `(overpass, y, x)`, all dimensionless: `vpd_z`, `sm_z` (the soil-
    moisture **check**), `ndmi_z` (the **water-supply** z). **Saved climatology** (kept to
    interpret results later — step 4 deliverable): `vpd_clim_mean`/`vpd_clim_std` (kPa),
    `sm_clim_mean`/`sm_clim_std` (m³ m⁻³).
  - **coords** `overpass`, `overpass_key`, `time`, `era5_hour` (the overpass axis is reused
    verbatim from the Section 9 cube), plus `y`/`x` and a CF `spatial_ref`.
  - **Two methods, by what data exist (documented in the module header + the QC note).**
    **`vpd_z` / `sm_z` — rigorous temporal climatology:** for each overpass (day-of-year
    *D*, matched ERA5 hour *H*, year *Y* = 2023) the **normal** = mean of ERA5-Land values
    at hour == *H* over all days with |doy − D| ≤ `CLIMATOLOGY_WINDOW_DAYS` (**15**) across
    2018–2024 **excluding year Y** (leave-one-year-out); **std** over the same set;
    `z = (observed − normal)/std`. Computed in **native ERA5 8×10 hourly space, then
    bilinear-regridded to 70 m**. The ±15-day window is **clipped** to the warm season
    (one-sided at the June/September edges — expected). **`ndmi_z` — spatial
    standardization (a documented, data-forced deviation):** Section 4 produced **only one**
    2023 NDMI composite, so a temporal day-of-year climatology is **impossible**; instead
    `z_NDMI = (NDMI − μ)/σ` over **all valid 70 m NDMI pixels** (μ ≈ −0.0677, σ ≈ 0.0850,
    n = **1 544 052** px), **broadcast across all 66 overpasses** (it varies by pixel, not
    by overpass — **constant in time**). Consequence: the water-supply stress feeding
    Section 12 is a spatial field constant in time; the CSI's *temporal* variation comes
    from VPD. (Asserted on reload: `ndmi_z` is identical across overpasses.)
  - **QC (step 4; full account in `docs/section11_anomaly_qc_note.md`).** Whole-record
    mean/std: `vpd_z` **+0.12 / 0.95** (on target), `sm_z` **−0.09 / 0.45** (mean ≈ 0; std
    < 1 is a **real single-pilot-year** property — 2023 overpass-hour soil moisture varied
    less than the 2018–2024 spread; identical native & regridded, so not a pipeline bug;
    SM is the protocol's *check*), `ndmi_z` **0.00 / 1.00** (by construction). The seasonal
    cycle is **demonstrably removed as a function of day-of-year**: the day-of-year VPD
    normal tracks the within-season march (3.74 → 2.83 kPa, Jun → Sep) while a whole-season
    normal is flat (3.32 kPa) — so the residual June-low/July-high z pattern is **real 2023
    weather** (cool-humid early June, the record July heat), not the whole-season pitfall.
    Extreme positive VPD-z: the 2023-06-30…07-30 heatwave window is **23 % of overpasses
    but 64 % of the top-11 VPD-z → 2.80× enriched** (#2 overall is 2023-07-20). Compressed
    (Blosc/zstd), one overpass per chunk.
- `section11_zscores_overpass_summary.parquet` — **Section 11** companion: a **66-row**
  per-overpass table (`overpass_key`, `time`, `era5_hour`, `season_part`,
  `in_heatwave_2023`, and regional area-mean `vpd_z`/`sm_z`/`ndmi_z` + the VPD/SM
  climatology means/stds) for a quick scan and the QC tables.
