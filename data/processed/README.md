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
    `sm_clim_mean`/`sm_clim_std` (m³ m⁻³), and `ndmi_clim_mean`/`ndmi_clim_std`
    (dimensionless; the day-of-year LOYO NDMI climatology carried over from Section 4b).
  - **coords** `overpass`, `overpass_key`, `time`, `era5_hour` (the overpass axis is reused
    verbatim from the Section 9 cube), plus `y`/`x` and a CF `spatial_ref`.
  - **All three are a temporal day-of-year leave-one-year-out anomaly (documented in the
    module header + the QC note).** **`vpd_z` / `sm_z`:** for each overpass (day-of-year
    *D*, matched ERA5 hour *H*, year *Y* = 2023) the **normal** = mean of ERA5-Land values
    at hour == *H* over all days with |doy − D| ≤ `CLIMATOLOGY_WINDOW_DAYS` (**15**) across
    2018–2024 **excluding year Y** (leave-one-year-out); **std** over the same set;
    `z = (observed − normal)/std`. Computed in **native ERA5 8×10 hourly space, then
    bilinear-regridded to 70 m**. The ±15-day window is **clipped** to the warm season
    (one-sided at the June/September edges — expected). **`ndmi_z` — TEMPORAL day-of-year-
    at-overpass anomaly (the supply-axis fix):** Section 4b now supplies a time-resolved
    NDMI store (`data/interim/s2_ndmi_timeseries_70m.zarr`, same 66 overpass keys) with a
    per-overpass `observed` NDMI plus its 2018–2024 day-of-year (±15 d) LOYO climatology
    `clim_mean`/`clim_std`, so `ndmi_z = (observed − clim_mean)/clim_std` is the **same
    temporal anomaly formula** as VPD/SM, computed **per overpass per pixel directly on the
    70 m grid** (no regrid). This **replaces** the former static spatial standardization of
    a single 2023 composite. Consequence: `ndmi_z` now **varies in time and space**, so the
    CSI **supply axis is no longer frozen** — the CSI's temporal variation now comes from
    both the VPD (demand) and NDMI (supply) sides. (Asserted on reload: `ndmi_z` **varies**
    across overpasses — per-overpass spatial-mean std > 0.)
  - **QC (step 4; full account in `docs/section11_anomaly_qc_note.md`).** Whole-record
    mean/std: `vpd_z` **+0.12 / 0.95** (on target), `sm_z` **−0.09 / 0.45** (mean ≈ 0; std
    < 1 is a **real single-pilot-year** property — 2023 overpass-hour soil moisture varied
    less than the 2018–2024 spread; identical native & regridded, so not a pipeline bug;
    SM is the protocol's *check*), `ndmi_z` **+0.31 / 0.93** (near 0/1; standardized
    against an *independent* day-of-year LOYO climatology, like VPD/SM) with a
    per-overpass spatial-mean std **across** overpasses of **0.44 (> 0)** — the proof it
    now varies in time (the old static field was identical across all 66 overpasses). The
    seasonal
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
- `section12_csi_70m.zarr` — **Section 12 deliverable:** the **Compound Stress Index (CSI)**
  for every pixel and every overpass, built by `src/section12_compound_stress.py` from the
  Section 11 z-scores (steps 62–66). Reopen with `xr.open_zarr(..., decode_coords="all")`.
  - **dims** `overpass = 66 × y = 1155 × x = 1339`; geometry identical to `reference_grid.tif`
    (asserted on write **and** on reload).
  - **vars** `(overpass, y, x)`, all dimensionless: `csi` (the baseline equal-weight CSI),
    `demand_stress` (`max(vpd_z, 0)`, time-varying), `supply_stress` (`max(-ndmi_z, 0)`,
    **now time-varying** — `ndmi_z` is now a temporal anomaly).
  - **coords** `overpass`, `overpass_key`, `time`, `era5_hour` (the overpass axis is reused
    verbatim from the Section 11 store / Section 9 cube), plus `y`/`x` and a CF `spatial_ref`.
  - **Definitions (from the Section 11 z-scores — never raw values).** `demand_stress` = the
    positive part of the VPD z-score, **`max(vpd_z, 0)`** (step 62; only above-normal VPD is
    stressful). `supply_stress` = the positive part of the **negated** water-supply z-score,
    **`max(-ndmi_z, 0)`** (step 63; low water → positive stress, so a below-normal NDMI — a
    *negative* z — becomes a positive contribution). **`csi = WEIGHT_DEMAND·demand_stress +
    WEIGHT_SUPPLY·supply_stress`** with **baseline equal weights 0.5/0.5** (`config.WEIGHT_DEMAND`
    / `config.WEIGHT_SUPPLY`; step 64). **CSI ≥ 0 everywhere** (non-negative parts, non-negative
    weights). The build **refuses to run unless the inputs are z-scores** — `ndmi_z` has
    **std ≈ 1** and spans a **z-like range not bounded in [−1, 1]** (it now reaches ±many σ),
    and `vpd_z` straddles 0. The guard **no longer requires `ndmi_z` mean ≈ 0**: `ndmi_z` is now
    a **temporal day-of-year leave-one-year-out anomaly**, so a single analysis year can be
    offset from its multi-year normal (here the record-wide mean is **≈ +0.31**) — std ≈ 1 plus
    the unbounded range still firmly rejects RAW NDMI (bounded in [−1, 1], std ≈ 0.09). The
    protocol's common pitfall (raw NDMI would dominate the equal-weight sum) is guarded in code,
    not just in prose.
  - **`supply_stress` now VARIES IN TIME** (and space) because `ndmi_z` is now a **temporal**
    day-of-year leave-one-year-out anomaly (Section 11, updated), not the old single-composite
    spatial standardization. The std of the per-overpass spatial-mean supply is **> 0** (asserted
    on reload; was exactly 0 under the old static field). **Consequence:** the **CSI now varies
    in both space and time from BOTH the demand and supply terms**, so the temporal ranking of
    the spatial-mean CSI is **no longer identical** to the VPD-demand ranking (whether they still
    coincide is reported, not assumed).
  - **QC (step 65).** CSI min/mean/max = **0.000 / 0.334 / 22.486** (re-run with time-varying
    supply; old static-supply mean was 0.421 — the mean drops because the supply term is now
    near-normal on most overpasses rather than carrying the static spatial-anomaly floor);
    **CSI ≥ 0 everywhere**; **99.05 %** of pixel-overpass cells finite. The highest-CSI dates
    still coincide with the summer-2023 compound extremes via the **robust heatwave-window
    enrichment** (VPD-z is standardized per hour-of-day, so a brittle top-1 is unreliable): the
    2023-06-30…07-30 peak-heat window is **23 % of overpasses but 36 % of the top-11 highest-CSI
    → 1.60× enriched** (down from the static-supply 2.80×, which the demand-only ranking still
    shows — the supply now pulls some non-July wet/dry-anomaly dates up). The top-3 highest-CSI
    overpasses are **2023-09-10, 2023-08-30, 2023-07-20** (vs the old VPD-demand order). The CSI
    and VPD-demand rankings now **differ** (reported in-code). Compressed (Blosc/zstd), one
    overpass per chunk.
  - **Sensitivity hooks (step 66) — not run here.** The CSI computation is a parameterised
    `compute_csi(demand, supply, w_demand, w_supply)` (unequal-weight test = a trivial re-call)
    and `copula_weights()` is a `NotImplementedError` placeholder for the copula-derived weights.
    The baseline deliverable uses the equal 0.5/0.5 weights only.
- `section12_csi_overpass_summary.parquet` — **Section 12** companion: a **66-row**
  per-overpass table (`overpass_key`, `time`, `era5_hour`, `season_part`, `in_heatwave_2023`,
  and the spatial-mean `csi`/`demand_stress`/`supply_stress`), sorted by spatial-mean CSI, for
  a quick scan and the compound-extreme confirmation.
- `master_table.parquet` — **Section 13 deliverable:** the **master analysis table** — the
  study's primary outcome (the cooling advantage) plus every variable assembled into one
  analysis-ready table, **one row per paired neighborhood per overpass** (steps 67–71). Built by
  `src/section13_master_table.py`; **the single input to every analysis from here on.**
  - **shape** **264 rows × 26 columns**. Row = one (paired-neighborhood `GEOID`, overpass) pair.
    Only the **9 paired block groups** (Section 10) over the 66 overpasses enter (≤ 594
    candidates), and a row is **emitted only where the cooling advantage is computable** — the BG
    has **≥ 1 tree pixel AND ≥ 1 reference pixel with finite LST on that overpass**. Result: 264
    rows spanning **9 neighborhoods × 54 distinct overpasses**.
  - **columns by group.** *Identifiers:* `neighborhood_id` (12-digit GEOID), `overpass_timestamp`
    (UTC datetime), `overpass_key`, `city` (`"Phoenix"`). *Primary outcome:* `cooling_advantage`.
    *Mechanism (tree pixels):* `mean_et_tree`, `mean_esi_tree`. *Stressor (tree pixels):*
    `mean_csi_tree`, `mean_vpd_z_tree`, `mean_water_supply_z_tree`. *Modifiers:* `mean_impervious`,
    `mean_canopy`, `aridity`, `irrigation_proxy`, `functional_type` (+ detail
    `functional_leaf_habit`). *Neighborhood:* `median_income`, `pct_poc`, `svi`. *Counts:*
    `n_tree_px`, `n_ref_px`, `n_tree_valid`, `n_ref_valid`, `n_good_obs`. (Detail columns
    `mean_lst_tree`/`mean_lst_reference` are also kept so the cooling-advantage identity is
    auditable.)
  - **`cooling_advantage` (primary outcome, step 67)** = `mean LST(reference) − mean LST(tree)`
    over the BG's finite-LST pixels that overpass (**Kelvin = °C**, a temperature difference).
    Positive = trees cooler; near zero = benefit gone. Same-overpass differencing cancels weather
    and time-of-day. **Can be negative; NOT clipped.** Spread: **min −6.35 / median +2.81 / mean
    +3.66 / max +23.06 K; 43/264 (16.3 %) negative** — mostly positive (trees cooler) with a
    near-zero/negative tail (small pre-dawn overpasses; the +23 K max is a one-tree-pixel BG).
  - **mechanism/stressor (step 68)** are means over the BG's **tree-dominated pixels**.
    `mean_et_tree`/`mean_esi_tree` are **NaN on the 21 overpasses without ET/ESI** (~22.7 % of
    rows; Section 3 caveat). The stressor columns `mean_csi_tree` / `mean_water_supply_z_tree` now
    **vary per overpass** (Section 11/12 redo: `ndmi_z` is a temporal day-of-year LOYO anomaly, so
    `supply_stress` and CSI are time-varying — **supply is no longer static in time**); e.g. within
    the dominant BG `040139412001` `mean_csi_tree` spans **0.020–0.928** across its 34 overpasses
    (≈constant before). *Outlier note (checked):* the **domain-wide** `ndmi_z`/CSI have extreme
    outliers (up to ±50 / CSI ≈ 22) at the ~53 k stable bare/paved pixels (tiny NDMI clim-std), but
    the **195 tree pixels are well-behaved** (`ndmi_z` within ±3.6); because this table averages
    CSI/supply over **tree pixels only**, the tree-pixel stressor means stay sane over all 264 rows
    (`mean_csi_tree` ≤ 1.50, `mean_water_supply_z_tree` ∈ [−2.76, +1.07]; none |z| > 10). `aridity`
    = **BG-mean PDSI** that overpass (**negative = drier**; NaN on the 3 earliest overpasses with no
    containing pentad). `mean_impervious`/`mean_canopy` are **neighborhood-level** means over all
    valid BG pixels (context modifiers, not tree-pixel means).
  - **`irrigation_proxy` (step 70) — documented heuristic, static per BG.**
    `irrigation_proxy = mean( norm(turf_fraction), norm(income), norm(1 − impervious_fraction) )`,
    `norm(c) = (c − min c)/(max c − min c)` **across the 9 paired neighborhoods** (equal 1/3
    weights, [0,1], higher = more likely irrigated). `turf_fraction` = share of BG pixels with
    **NDVI > 0.50 AND canopy < 20 %** (irrigated green-but-not-tree = lawn/turf); `income` = ACS
    median income (**missing → paired-BG median before norm**); `1 − impervious_fraction` =
    perviousness. **Ranks** neighborhoods by irrigation likelihood; **not a measurement** of water
    applied. Range over rows **[0.009, 0.742]**.
  - **`functional_type` is `unknown` for all 9 paired BGs.** The modal `water_use` among inventory
    trees inside the BG — but the street-tree inventory covers only **central Phoenix** (UTM
    ~386–405 km E / 3694–3713 km N) and the paired BGs are on the periphery, so a point-in-polygon
    join finds **zero** inventory trees in any of them. The protocol's anticipated central-Phoenix
    limitation, handled gracefully.
  - **counts KEPT for the Section 14 minimum-count filter.** `n_tree_px`/`n_ref_px` (static, from
    the class raster), `n_tree_valid`/`n_ref_valid` (finite-LST that overpass — the actual sample
    sizes), `n_good_obs = min(n_tree_valid, n_ref_valid)`. **Thin paired sample (carried, not
    hidden):** `n_tree_px` **1–171** (one BG has 171; the rest 1–6), `n_ref_px` 332–1122,
    `n_good_obs` 1–171 (median **2**) → many rows rest on a single tree pixel; the Section 14
    threshold estimate must be reported with this caveat.
  - Re-opened and **asserted on reload**: every column present; one row per (neighborhood,
    overpass); `cooling_advantage == mean_lst_reference − mean_lst_tree`; `n_good_obs ==
    min(n_tree_valid, n_ref_valid)`; every row ≥ 1 finite tree & reference pixel. QA figure
    `figures/section13_cooling_advantage_distribution.png`.

### Section 16 (reason-#2 fix) — pixel-level local pairing + clustering-aware threshold

**NEW deliverables, fully NON-DESTRUCTIVE.** These ADD to (never replace) the BG-level
`master_table.parquet` above; they are built by `src/section16_pixel_pairing.py` +
`src/section16_threshold_pixel.py` at a **separate, relaxed operating point** (config block
`CANOPY_THR_PIXEL = 30`, `MIN_OBS_PIXEL = 15`; all other Section 10 gates unchanged) to enlarge and
strengthen the thin Phoenix paired sample without fabricating signal. The Section 10 BG-pipeline
constants (`CANOPY_THR = 40` / `MIN_OBS = 20` / `CANOPY_THR_PREREGISTERED = 70`) are untouched.

- `section16_pixel_class_pixel_70m.tif` — uint8 relaxed CANDIDATE class raster aligned to
  `reference_grid.tif` (codebook **0 = other, 1 = tree-candidate, 2 = reference-candidate**), at
  canopy > 30 % / obs ≥ 15. **670 tree-candidate pixels** (vs 195 in the BG-paired
  `section10_pixel_class_70m.tif`), 418 373 reference candidates. *Candidate* masks (un-demoted),
  re-derived from the cube — NOT the BG-paired subset.
- `section16_pixel_clusters.parquet` — one row per tree-candidate pixel:
  `tree_row, tree_col, x, y, cluster_id, GEOID, obs_count`. `cluster_id` = the **queen (8-conn)**
  connected-component label of the tree class (the independent spatial unit). **133 queen clusters /
  178 rook clusters** from 670 tree px; largest queen cluster **176 px (26.3 %)**; **dominant BG
  `040139412001` holds 71.2 %** of tree px (down from 87.7 % at canopy40); **Kish N_eff = 12.1
  (queen) / 16.6 (rook) clusters, but 1.9 by BG** (the honest independence ceiling — 44 clusters
  share the dominant BG's reference baseline + coarse ~9 km met).
- `master_table_pixel.parquet` — the **pixel-overpass** paired table (the finest granularity;
  **NOT the inference df**). One row per (tree px, overpass) with finite tree LST and ≥ 1 reachable
  reference within R, **stacked over the radius sweep** (`R_m` ∈ {210, 350, 500}; **18 713 rows**).
  Columns: `tree_row, tree_col, cluster_id, GEOID, overpass_index, overpass_key, overpass_timestamp,
  lst_tree, ref_mean, n_ref_in_R, n_ref_finite, cooling_advantage_px, mean_csi_tree, vpd_z, ndmi_z,
  mean_et_tree, mean_esi_tree, pdsi, R_m`. **`cooling_advantage_px = mean(finite LST of reference px
  within R metres of the tree px) − LST_tree`**, differenced at the **same overpass** (cancels
  weather/time-of-day exactly); references found by a KDTree on reference-px (row, col) coords,
  radius = R / 70 m cells. ET/ESI NaN on the non-ET overpasses (pairwise-dropped, never imputed).
- `master_table_cluster.parquet` — the **PRIMARY modeling input**: the pixel-overpass rows collapsed
  to **cluster-overpass** rows (stacked over the radius sweep; **4 178 rows**; **R = 350 m primary →
  1 344 rows over 56 clusters / 13 BGs, median 24 overpasses/cluster**). Columns: `cluster_id, GEOID,
  overpass_index, overpass_key, overpass_timestamp, cooling_advantage (count-weighted by
  n_ref_finite), mean_csi_tree, vpd_z, ndmi_z, mean_et_tree, mean_esi_tree, pdsi, n_tree_px_valid,
  n_ref_in_R, R_m`. CSI range 0–1.62 (R=350); cooling advantage median **+1.52 K**;
  **between-cluster CSI variance share ≈ 34 %** (real spatial signal on the x-axis). The cluster is
  the random-effect + resampling unit; the pixel-overpass count is reported but **never** the df.
- `section16_threshold_results.json` — the machine-readable clustering-aware results: per-radius
  cluster-level segmented fit + verdict, the cluster-resampling bootstrap CI, the MixedLM
  (random intercept, cluster nested in BG), cluster-robust SEs, the within-pixel temporal FE slope,
  the leave-dominant-BG-out refit, and the rook / 2 km-grid robustness passes, with nominal-N /
  cluster-N / BG-N / Kish-N_eff on every estimate. **Result: NO ROBUST THRESHOLD, in every cell** —
  breakpoint bootstrap CIs span 63–92 % of the CSI range (not identified), methods do not agree on a
  well-identified break, ET shows no consistent decline, cluster-robust SE deflates the otherwise
  spuriously-significant pooled slope (naive p ≈ 0.009 → robust p ≈ 0.12), the MixedLM slope is flat
  (≈ +0.03, p ≈ 0.88), and the within-pixel temporal slope is the **wrong sign** (≈ +0.16). The null
  does **not** flip under leave-dominant-out. The enlarged, properly-clustered design **tightens** the
  Section 14 null — it does not overturn it; the binding limit remains the thin, clustered sample,
  which gates to the cross-city phase. The deliverable narrative + figures are in
  `notebooks/16_pixel_threshold.ipynb` (figures `figures/section16_*.png`).
