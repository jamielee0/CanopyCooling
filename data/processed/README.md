# data/processed/

Final, analysis-ready datasets produced by the pipeline. Reproducible from `raw/` + `interim/`;
contents are git-ignored. The *why* behind each layer is in
[`../../docs/DESIGN_DECISIONS.md`](../../docs/DESIGN_DECISIONS.md); QC detail is in the
`docs/section*_note.md` files. All gridded outputs align exactly to `reference_grid.tif`
(asserted on write and on reload). Reopen the Zarr stores with
`xr.open_zarr(..., decode_coords="all")` to recover the CRS.

| File | Section | Contents |
|---|---|---|
| `reference_grid.tif` | 1 | The 70 m reference grid (EPSG:32612, 1155×1339, origin 355460/3754380) — the geometric anchor for every other layer. |
| `analysis_cube_70m.zarr` | 9 | The aligned multi-variable cube, all layers harmonized to 70 m and time-matched to the 66 overpasses. |
| `analysis_overpass_table.parquet` | 9 | 66-row per-overpass summary (matched hour/date/pentad, `in_et`/`in_esi`, regional-mean drivers). |
| `section10_pixel_class_70m.tif` | 10 | Per-pixel class (uint8, nodata 255): **0 = other, 1 = tree-dominated, 2 = reference, 3 = building-buffer**. |
| `section10_paired_neighborhoods.csv` | 10 | Paired block groups (`GEOID, n_tree_px, n_ref_px`). |
| `section10_threshold_sensitivity.csv` | 10 | Tree/ref/paired counts as each threshold is swept (operating vs pre-registered baselines). |
| `section10_validation_sample.csv` | 10 | Sampled tree pixels for visual validation (`genuine_canopy` left blank for the user). |
| `section11_zscores_70m.zarr` | 11 | Deseasonalized z-scores `vpd_z`, `sm_z`, `ndmi_z` + saved climatology means/stds. |
| `section11_zscores_overpass_summary.parquet` | 11 | 66-row per-overpass regional-mean z-scores + climatology. |
| `section12_csi_70m.zarr` | 12 | Compound Stress Index `csi`, `demand_stress`, `supply_stress`. |
| `section12_csi_overpass_summary.parquet` | 12 | 66-row per-overpass spatial-mean CSI/demand/supply, sorted by CSI. |
| `master_table.parquet` | 13 | **The master analysis table** — the single input to every analysis from here on. |
| `master_pixel_table.parquet` | 13 | One row per valid tree pixel × overpass, for the crossed mixed-effects and whole-BG cluster-bootstrap sensitivity. |

## `analysis_cube_70m.zarr` (Section 9)
- **dims** `overpass = 66` (the ECOSTRESS LST overpasses, the master axis) `× y = 1155 × x = 1339`.
- **time-varying vars** `(overpass, y, x)`: `lst` (K), `et` (W m⁻²), `esi` (—), `pet` (W m⁻²),
  `vpd` (kPa), `sm` (m³ m⁻³), `ppt_30d/60d/90d` (mm), `pdsi/spei30d/spei90d` (index), `tmean` (°C).
  **ET/ESI/PET exist only on their 45 paired overpasses** (NaN on the other 21); **drought is NaN
  on the 3 earliest overpasses** (before the first 2023 pentad).
- **static vars** `(y, x)`: `ndvi`, `ndmi` (—), `impervious`, `canopy` (percent 0–100),
  `landcover_class` (uint8 NLCD codes — categorical), `median_income` (USD), `pct_poc` (%),
  `svi` (0–1).
- **coords** `overpass_key`, `time`, `orbit`, `scene`, `in_et`, `in_esi`, `era5_hour`,
  `precip_date`, `drought_pentad`, `y`/`x`, CF `spatial_ref`. Time-matching: ERA5 at nearest hour,
  precip/tmean at exact date, drought at the containing pentad (see DESIGN_DECISIONS Section 9).

## `section11_zscores_70m.zarr` (Section 11)
- **dims** `overpass = 66 × y × x`. **z-score vars** (dimensionless): `vpd_z` (atmospheric
  demand), `sm_z` (the primary root-zone-soil-moisture supply axis), and `ndmi_z` (the
  vegetation-condition check). **Saved climatology**: `{vpd,sm,ndmi}_clim_mean`
  / `_clim_std`. All three are temporal day-of-year leave-one-year-out anomalies; `ndmi_z` varies
  across overpasses (asserted on reload). QC: [`../../docs/section11_anomaly_qc_note.md`](../../docs/section11_anomaly_qc_note.md).

## `section12_csi_70m.zarr` (Section 12)
- **vars** (dimensionless): `csi`, `demand_stress` = `max(vpd_z, 0)`, `supply_stress` =
  `max(-sm_z, 0)` after the documented robust rescale of `sm_z`.
  `csi = WEIGHT_DEMAND·demand + WEIGHT_SUPPLY·supply` (baseline 0.5/0.5); **CSI ≥ 0
  everywhere**. NDMI is carried into the companion summary as a vegetation check, not used as
  the supply term. CSI is a secondary scalar analysis; the primary RQ1 detector is the Section 15
  two-dimensional `vpd_z` × `sm_z` response surface.

## `master_table.parquet` (Section 13)
- **264 rows × 30 columns** — one row per (paired block group, overpass): the 9 paired BGs over the
  54 overpasses where the cooling advantage is computable (BG has ≥1 tree and ≥1 reference pixel
  with finite LST).
- **Primary outcome** `cooling_advantage = mean LST(reference) − mean LST(tree)` (K = °C),
  same-overpass differencing; never clipped (can be negative).
- **Column groups** — identifiers (`neighborhood_id`, `overpass_timestamp`, `overpass_key`,
  `city`), outcome (`cooling_advantage` + the auditable `mean_lst_tree`/`mean_lst_reference`),
  mechanism (`mean_et_tree`, `mean_esi_tree`), stressor over tree pixels (`mean_csi_tree`,
  `mean_vpd_z_tree`, `mean_sm_z_tree` [primary supply], `mean_ndmi_z_tree` [vegetation check]),
  modifiers (`mean_impervious`, `mean_canopy`,
  `aridity`, `irrigation_proxy`, `functional_type` + `functional_leaf_habit`), neighborhood
  (`median_income`, `pct_poc`, `svi`), counts (`n_tree_px`, `n_ref_px`, `n_tree_valid`,
  `n_ref_valid`, `n_good_obs`), and `local_hour`, `is_day`, `sample_label`.
- **Primary sample (persisted, not reconstructed downstream):** `is_day == True` and
  `sample_label == "primary"`, where the label requires `n_tree_valid >= 3`. Lower-count rows,
  night rows, and pooled-overpass results are sensitivity-only.
- **Thin-sample flag (carried, not hidden):** `n_tree_px` 1–171 (one BG holds 171, the rest 1–6).
  Phoenix has only 9 paired block groups, so it does not meet the 10-cluster minimum for a robust
  threshold claim. `functional_type` is `unknown` for all paired BGs (the inventory covers only
  central Phoenix). `irrigation_proxy` is a documented heuristic ranking, not a measurement.

## `master_pixel_table.parquet` (Section 13)
- Per-tree-pixel outcome `cooling_advantage_px = mean_lst_reference - tree_lst`, with per-pixel
  `vpd_z`, `sm_z`, `ndmi_z`, and `csi`, plus repeated BG/overpass counts and the persisted sample
  label. The mixed model decomposes VPD and SM into within-BG and between-BG terms; the within-BG
  terms contain both spatial and temporal variation, not a purely temporal effect.
