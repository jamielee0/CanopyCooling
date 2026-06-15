# src/

Python source for the protocol: data access, processing, modelling, and
utilities. Importable as a package alongside `config.py`.

- `check_auth.py` — minimal authenticated smoke test for the four services
  (Earthdata, Earth Engine, CDS, Census). Run: `python src/check_auth.py`.
- `build_reference_grid.py` — Section 1: derive/regenerate the 70 m reference grid.
- `section2_ecostress_lst.py` — Section 2: acquire + QC ECOSTRESS LST into a
  time-indexed Zarr cube. `test_section2_ecostress_lst.py` covers its pure logic.
- `section3_ecostress_et_esi.py` — Section 3: acquire + QC the ECOSTRESS
  evapotranspiration (PT-JPL) and evaporative-stress products, build ET/ESI Zarr
  cubes on the same grid, and write `data/interim/overpass_links.parquet` linking
  each ET/ESI overpass to its Section-2 LST overpass. Reuses the Section 2
  acquisition machinery (auth, manifest/checksum, clip, keep-mask, drop, cube
  stats, figures). `test_section3_ecostress_et_esi.py` covers its pure logic.
  Run: `python src/section3_ecostress_et_esi.py` (`--max-granules N` for a smoke
  test, `--skip-download` to reuse `data/raw`, `--links-only` to rebuild only the
  link table).

  **ET / ESI caveat (Section 3).** This evapotranspiration product is built for
  *natural vegetation* and is **unreliable over built-up areas**. It is
  **supporting evidence only** — a mechanism check, never a primary measurement —
  and its later use is **restricted to high-tree-fraction pixels (Section 10)**.

  **Product identity.** The protocol's example name `ECO_L3T_ET_PT-JPL` does not
  exist in ECOSTRESS Collection 2. As confirmed on Earthdata Search, the PT-JPL
  ET for the pilot window is the `PTJPLSMinst` layer of `ECO_L3T_JET` v002; ESI
  is `ECO_L4T_ESI` v002 (with its `PET` layer). See the module header for detail.
- `section4_sentinel2_indices.py` — Section 4: build warm-season median NDVI and
  NDMI composites from `COPERNICUS/S2_SR_HARMONIZED` in Earth Engine and pull them
  straight to disk with `geemap.download_ee_image` (no Drive round-trip), then
  resample onto the 70 m grid. `test_section4_sentinel2_indices.py` covers its
  pure logic.
- `section5_landcover.py` — Section 5: acquire the impervious-surface %, tree-canopy
  % and NLCD land-cover **class** layers and put all three on the 70 m grid, with
  **no manual download**. `test_section5_landcover.py` covers its pure logic.
  Run: `python src/section5_landcover.py` (`--coarse-scale 300` for a smoke test,
  `--skip-download` to reuse `data/raw/landcover/`, `--layers` to subset).

  **Datasets (most recent available; logged + recorded in the manifest).**
  Impervious % and land-cover class come from the most-recent OFFICIAL NLCD release
  carrying both layers in one CONUS image — `USGS/NLCD_RELEASES/2021_REL/NLCD`
  (year **2021**, bands `impervious`, `landcover`). Tree canopy % comes from the
  current (non-deprecated) USFS Tree Canopy Cover collection
  `projects/gtac-data-publish/assets/TCC/Product_Version/2025-6` (CONUS, year
  **2025**, band `NLCD_Percent_Tree_Canopy_Cover`). All native 30 m.

  **Resampling (the crux).** Impervious % and canopy % are resampled 30 m → 70 m
  by exact **AREA-WEIGHTED AVERAGING** (each 70 m cell = the area-weighted mean of
  the 30 m cells it covers); this is unit-tested against a hand computation and
  cross-checked against GDAL `average`. The land-cover **class** layer is
  categorical and is resampled by **NEAREST NEIGHBOUR** only — never averaged /
  bilinear, which would invent fractional classes (Section 9 pitfall).

  **Units / gotcha.** The saved %-layers keep native **percent (0–100)** units
  (the Section 10 thresholds are stated in percent). geedim tags the downloads
  `nodata=0`; for the categorical layer 0 = "no class" (correct), but for
  impervious/canopy 0 % is a **valid** value, so those two are read unmasked —
  masking them would silently drop every 0 % cell and bias the mean upward.
- `section7_precip_drought.py` — Section 7: precipitation history and drought
  state. PRISM daily **ppt** (2018–2024, web service `get/us/4km`, CONUS GeoTIFF
  clipped to the bbox) → **antecedent precipitation** rolling totals over the
  **preceding** 30/60/90 days; **GRIDMET DROUGHT** (`pdsi`, `spei30d`, `spei90d`)
  pulled from Earth Engine with `geemap.download_ee_image` at native scale (no
  Drive); PRISM mean air temperature **tmean** for the analysis seasons (an
  independent cross-check on ERA5-Land air temperature in Section 11). Every layer
  is reprojected to EPSG:32612 and resampled to the 70 m grid (**bilinear** — all
  are continuous) as Zarr cubes. `test_section7_precip_drought.py` covers its pure
  logic. Run: `python src/section7_precip_drought.py` (`--skip-drought` /
  `--skip-prism` to run one source, `--skip-download` to reuse `data/raw/prism/`,
  `--years 2023` to grid one season).

  **Robustness (download-heavy job on a flaky host).** Each PRISM daily file is
  rate-limited to twice per IP per day; the downloader is resumable and a
  rate-limited day **self-heals via the 800 m endpoint** (a different file)
  averaged back onto the 4 km clip grid. If the host's SSL trust store is corrupt
  (which breaks every HTTPS client), it transparently falls back to certifi's CA
  bundle for that run. The coarse fields (PRISM ~4 km, GRIDMET ~4.6 km) smoothed
  onto 70 m are **regional context**, not block-scale detail.
- `section8_neighborhood_tree.py` — Section 8: neighborhood attributes (ACS income
  & %-people-of-colour, CDC SVI), the Phoenix tree inventory with functional types,
  and Microsoft building footprints — all for the study area.
  `test_section8_neighborhood_tree.py` covers its pure logic. Run:
  `python src/section8_neighborhood_tree.py` (`--parts acs,svi,trees,footprints,grid`
  to subset, `--skip-download` to reuse `data/raw/`, `--footprints-source
  auto|stac|fallback`).

  **ACS (step 42).** ACS 5-year, vintage **2024**, block-group level, Maricopa
  County (state `04`, county `013`): `B19013_001E` (median household income) and the
  whole `B03002` table. **%-people-of-colour** = `100 × (B03002_001E − B03002_003E)
  / B03002_001E` — i.e. everyone who is *not* non-Hispanic White alone. Census **jam
  values** (e.g. `-666666666`) are mapped to null, never averaged. Block-group
  polygons come from TIGER/Line 2024 (`tl_2024_04_bg.zip`, filtered to county 013)
  and are joined by GEOID. Saved to `data/raw/acs/`.

  **SVI tract → block-group inheritance (step 43, important).** The CDC/ATSDR SVI is
  **tract level**; the user places the CSV in `data/raw/svi/`. It is **joined DOWN to
  block groups by FIPS: every block group inherits its parent tract's SVI value**,
  because the first 11 digits of a 12-digit block-group GEOID *are* the tract GEOID
  (block groups nest within tracts). **SVI therefore varies at TRACT scale, not
  block-group scale, in this analysis.** The overall ranking `RPL_THEMES` is used
  (themes 1–4 retained); the `-999` missing sentinel is nulled.

  **Tree inventory (step 44) — source resolution.** The protocol names "City of
  Phoenix open-data portal (phoenixopendata.com); ASU Treelytics". The phoenixopendata
  CKAN portal does **not** host a per-tree inventory (its 160 datasets were
  enumerated; only street-landscape-maintenance *zones* match "tree"). The real
  inventory is the ASU-hosted service the protocol calls "ASU Treelytics":
  `street_trees_gao_map_by_species__WFL1` (FeatureServer layer 1), **22,507**
  inventoried street/park trees with botanical + common species. **Functional type is
  the PRIMARY descriptor** — `water_use` (drought-tolerant vs mesic) and `leaf_habit`
  (deciduous vs evergreen) from a documented genus/species lookup; species detail is
  secondary (protocol pitfall: inventories are uneven). Coverage is central Phoenix
  (the ASU "GAO" flight area, ~the core of the bbox); top ~20 species. **A true
  planting year is unavailable** in any accessible Phoenix inventory: the source
  survey date is kept as `inventory_year` (the year the tree was *surveyed*, not
  planted — **do not use it for tree age**), and `planting_year` is present but
  **null for every record** (protocol step 44 retains planting year only "where
  available").

  **Building footprints (step 45) — primary STAC, automatic fallback.** Primary:
  the **Microsoft Planetary Computer STAC `ms-buildings`** collection — discovered
  with `pystac-client`, signed with `planetary-computer` (anonymous; no key), read
  from the signed `abfs://` GeoParquet with geopandas. The US item is partitioned by
  **Bing level-9 quadkey**; only the quadkey partitions covering the bbox are read
  (~1.47 M polygons), then clipped and reprojected to **EPSG:32612** (kept as vector
  polygons for the Section 10 tall-building buffer). **This primary STAC route
  produced the delivered layer** (item `United States_2022-07-06`). Fallback (only if
  the STAC read fails, which it did not): the Microsoft USBuildingFootprints
  `Arizona.geojson.zip`, clipped to the bbox. **Local cert-store caveat:** `adlfs`'s azure stack pulls `openssl 3.6.3`,
  whose stricter parsing trips a malformed cert in this machine's Windows store and
  breaks `import aiohttp`/earthaccess; `environment.yml` pins `openssl=3.6.2` to work
  around it (unnecessary on a clean machine).

  **Rasterization (step 46).** Block-group income, %-people-of-colour and the joined
  SVI are burned onto the 70 m reference grid by **NEAREST / value-per-cell** (each
  cell takes the value of the block group containing its centre) — these are
  already-aggregated quantities, never bilinear (Section 9 pitfall). All three align
  exactly to `../processed/reference_grid.tif`.
- `section9_harmonize.py` — Section 9: **harmonize every layer onto the common 70 m
  grid and time-match to the ECOSTRESS overpasses** (steps 47–51). Reads only
  `data/interim/` + `data/processed/reference_grid.tif` (no network). Produces the
  single aligned multi-variable analysis cube `../data/processed/analysis_cube_70m.zarr`.
  `test_section9_harmonize.py` covers its pure logic. Run:
  `python src/section9_harmonize.py` (`--no-figures` to skip the QA figure,
  `--verify-only` to re-open the saved cube and re-run the verification + spot check).

  **Already-gridded vs. resampled (steps 47–48).** Sections 2–8 wrote every gridded
  layer to the reference grid already, so step 47 is a **verification** (the module
  asserts identical CRS / cell size / origin / rows / cols for each layer, and refuses
  to proceed otherwise), not a re-snap. The **one** layer Section 9 itself resamples is
  **ERA5-Land** (Section 6; native ~9 km, EPSG:4326) — a continuous field, so
  **bilinear** (step 48 names VPD and soil moisture explicitly). Every other layer was
  resampled with the correct method in its own section: **bilinear** for the continuous
  layers (LST/ET/ESI/NDVI/NDMI/impervious/canopy/precip/drought/tmean), **nearest** for
  the categorical/already-aggregated ones (land-cover class, block-group income/%POC/
  SVI). The `landcover_class` layer is carried through as **integer** classes — never
  bilinear (the Section 9 pitfall; the module asserts no fractional classes on reload).

  **Master overpass axis.** The **66 ECOSTRESS LST overpasses** (Section 2 cube) are the
  master axis. The LST cube has no `overpass_key` coord, so it is reconstructed as
  `{orbit}_{scene}_{YYYYMMDDTHHMMSS}` (the Section 3 format) and used to place the 45
  paired **ET/ESI/PET** slices onto their overpasses (NaN on the other 21). ET/ESI
  remain *supporting evidence only* (Section 3 caveat) and are not resampled again.

  **Time-matching rule (step 49).** For each overpass: **ERA5 VPD + soil moisture** at
  the **nearest hour** (overpass UTC rounded to the hour — only the matching 8×10 hourly
  slice is bilinear-reprojected, 66 small reprojections, not all 20 496 hours);
  **antecedent precip (`ppt_30/60/90d`) + PRISM `tmean`** at the **exact calendar date**;
  **GRIDMET drought (`pdsi`/`spei30d`/`spei90d`)** at the **pentad whose 5-day window
  contains the date** (`pentad_start ≤ D < pentad_start+5`). The delivered drought cube
  holds only warm-season pentads, so the 3 earliest pilot overpasses (two on
  2023-06-02, one on 2023-06-03; before the first 2023 pentad on 06-04) have
  **no containing pentad and are left NaN**
  for drought — an honest absence, *not* the previous September's pentad (~8 months
  stale). ERA5-Land on the 70 m grid is a smooth **regional** background (the same
  coarse-field caveat as PRISM/GRIDMET), not a block-scale measurement.

  **Deliverable + the tidy-Parquet decision (step 50).** The primary deliverable is the
  gridded **`analysis_cube_70m.zarr`** (dims `overpass=66 × y=1155 × x=1339`; reopen with
  `decode_coords="all"`). A **full pixel × overpass tidy table (~100 M rows) is
  deliberately NOT produced** at this stage — the analysis pixels are not defined until
  Section 10, so a per-pixel long table would be wasteful. Instead a **small 66-row
  per-overpass table** `analysis_overpass_table.parquet` records the matched
  hour/date/pentad, `in_et`/`in_esi`, and the regional-mean drivers for a quick scan.

  **Alignment verified (step 51).** `figures/section9_alignment_spotcheck.png` and the
  run log print every layer's value at three known pixels (lon/lat **verified against the
  NDVI/impervious/canopy layers**, nudged off adjacent roads onto the feature): **Encanto
  Park** (NDVI 0.46, canopy 14 %, impervious 5 %, LST ≈ 310 K — coolest), the **I-10/I-17
  "Stack" interchange** (NDVI 0.02, impervious 91 %, canopy 0 %, LST ≈ 316 K — hottest,
  ET ≈ 4 W m⁻²), and **Papago Golf Course** (NDVI 0.56, impervious 1 %, canopy 0 % — very
  green turf but *no tree canopy*, distinct from the park, highest ET ≈ 209 W m⁻²).
- `section10_classify_pixels.py` — Section 10: **classify tree-dominated and non-tree
  urban reference pixels — the paired design** (steps 52–57). Reads the Section 9
  `data/processed/analysis_cube_70m.zarr` + the Section 8 block-group and building-
  footprint parquets (no network except the contextily aerial basemap for the
  validation overlay). **All thresholds are pre-registered named constants in
  `config.py`** so the sensitivity analysis is just a change of numbers there.
  `test_section10_classify_pixels.py` covers its pure logic. Run:
  `python src/section10_classify_pixels.py` (`--no-figures` to skip both figures,
  `--no-basemap` for a plain overlay without tile download, `--validation-n N`,
  `--seed N`).

  **Tree-dominated rule (step 52) — the AND of five criteria.** A pixel is
  tree-dominated iff warm-season median **NDVI > `NDVI_THR`** (0.5) **AND** tree-canopy
  **percent > `CANOPY_THR`** (**40 %**, the *operating* point — see "OPERATING
  CANOPY_THR" below; the **70 %** pre-registration is unachievable at 70 m) **AND**
  impervious **percent < `IMPERV_THR`** (20) **AND** it is **not water**
  (`landcover_class != WATER_CLASS`, NLCD 11) **AND** it has **≥ `MIN_OBS`** (20)
  finite/good-quality ECOSTRESS LST observations across the 66 overpasses (`obs_count` =
  per-pixel count of finite `lst` in the cube; each overpass's LST is already QC'd in
  Section 2). The protocol **pitfall is encoded by the conjunction**: high NDVI *alone*
  (well-watered grass / golf turf) does **not** qualify — canopy must *also* be high. It
  is the **combination** of high NDVI **with** high canopy that isolates trees.
  (Unit-tested, incl. the irrigated-grass case.)

  **Reference rule (step 53) + pairing (step 55).** A non-tree reference pixel has **low
  canopy** (`canopy < REF_CANOPY_MAX`, **20 %**), a **built** surface (`landcover_class`
  in `BUILT_CLASSES` = NLCD developed **21/22/23/24** — *not* water, *not* bare desert:
  barren 31 / shrub 52 / grassland 71 are excluded), and ≥ `MIN_OBS` observations. Then
  pixels are **paired by block group**: only block groups containing **both** a tree
  pixel and a reference pixel enter the analysis; tree/reference pixels in unpaired block
  groups are demoted to "other". The per-pixel **block-group index map** is produced here
  by rasterizing the block-group **GEOID** onto the 70 m grid by **centroid containment**
  (Section 8 rasterized only the block-group *attributes*, not the GEOID).

  **Tall-building buffer (step 54) — `TALL_BUILDING_MIN_AREA_M2 = 1000 m²` (a documented
  proxy).** The Microsoft footprints carry **geometry only — there is no height field** —
  so "tall/large" is proxied by footprint **area**: Phoenix is overwhelmingly low-rise,
  so large footprints are the commercial / multi-storey stock. 1000 m² sits just below
  the 99th percentile of footprint area (~1665 m²) → the largest ~2 % of the ~1.47 M
  footprints (**29,861** buildings); buffering *only* those by **`BUFFER_M` = 70 m**
  excludes **187,667 px (≈ 12 %** of the grid). Buffering *all* 1.47 M footprints would
  over-exclude the whole built area (the protocol's explicit warning), so only the proxy
  "tall" set is buffered. The area threshold is a config parameter and is in the
  sensitivity sweep.

  **OPERATING `CANOPY_THR = 40 %` — the pre-registered 70 % bar is unachievable at 70 m
  (a documented, protocol-gate-sanctioned operating point, NOT a silent change).** The
  70 m canopy layer (USFS TCC, 30 m, **area-weighted-averaged** to 70 m in Section 5)
  **maxes at 69.53 %** (mean 0.88 %): averaging 30 m canopy cells into 70 m cells dilutes
  the peaks, so **no 70 m cell reaches 70 %**. At the pre-registered `CANOPY_THR = 70 %`
  the tree count is **0** and the paired-neighborhood count is **0** — a **confirmed data
  ceiling** for a sparse-canopy desert city imaged at 70 m, **not a code bug**. The
  protocol's **Section 10 gate explicitly sanctions re-tuning** ("Few pairs or poor
  agreement means re-tune thresholds before continuing"), so `CANOPY_THR` is lowered to a
  **data-driven operating value** by a documented rule: the **HIGHEST canopy threshold in
  {40, 45, 50} that yields ≥ 10 paired neighborhoods** (all other thresholds at their
  pre-registered start values). The start-baseline canopy sweep is **35 → 70 %**:

  | `CANOPY_THR` | tree px | reference px | paired neighborhoods |
  |---|---|---|---|
  | 35 % *(context only, below floor)* | 314 | 9 391 | 14 |
  | **40 % — adopted operating point** | **195** | **6 019** | **9** |
  | 45 % | 112 | 4 235 | 7 |
  | 50 % | 56 | 2 561 | 4 |
  | 55 / 60 / 65 / 70 % | 29 / 7 / 2 / **0** | 1 329 / 819 / 819 / **0** | 2 / 1 / 1 / **0** |

  **None of {40, 45, 50} reaches 10 paired neighborhoods** (40 % → 9, 45 % → 7, 50 % → 4),
  so the rule falls back to the **40 % floor** — never lower (a 40 % canopy 70 m cell is
  already **~45× the Phoenix mean** of 0.88 %, a strong tree-dominated signal; lower would
  dilute the meaning). The adopted operating point is therefore **`CANOPY_THR = 40 %`**,
  giving **9 paired neighborhoods**. *(35 % clears 10, at 14 pairs, but it is **below the
  floor** and shown for context only, not adopted.)* The **70 % pre-registration is
  preserved** in `config.CANOPY_THR_PREREGISTERED`, and the **dependence is fully visible**
  in `section10_threshold_sensitivity.csv` (the full 35 → 70 % canopy sweep, the 70 % bar
  row at 0 px, and `is_operating_point` flagging the adopted 40 % row). **9 paired
  neighborhoods is a thin paired design — a genuine limitation that the Section 14
  threshold estimate MUST be reported WITH.** The sensitivity table (operating baseline)
  also shows which *other* thresholds bind at the 40 % operating point.

  **Visual validation (step 56) — imagery + a human eye; the human rate is PENDING USER
  REVIEW (never fabricated).** We cannot make the genuine-canopy call ourselves, so
  Section 10: (a) samples up to **60** classified tree pixels **spread across** their
  block groups (reproducible `seed`); (b) renders a **per-pixel aerial chip grid** over
  **Esri World Imagery** (1 m, via contextily — no auth) to
  `figures/section10_treepixel_validation_overlay.png` (each chip a ~160 m window with a
  box on the 70 m pixel — so a human can actually judge canopy *per pixel*, which a single
  full-extent overlay cannot); (c) writes `data/processed/section10_validation_sample.csv`
  with a **blank `genuine_canopy`** column for the user to mark yes/no; (d) prints an
  **automated provisional cross-check** (the share of sampled pixels also clearing a
  *stricter* NDVI+canopy bar — a proxy, **not** a human judgement) and a clearly-labelled
  **placeholder for the true human agreement rate (`PENDING USER REVIEW`)**. The sample is
  drawn at the **operating `CANOPY_THR = 40 %`** — exactly the tree pixels that enter the
  analysis.

  **Deliverables (`data/processed/`, git-ignored).** `section10_pixel_class_70m.tif`
  (per-pixel class raster aligned to `reference_grid.tif`; **codebook 0 = excluded/other,
  1 = tree-dominated, 2 = reference, 3 = excluded-by-building-buffer**, in the band tags),
  `section10_paired_neighborhoods.csv` (`GEOID, n_tree_px, n_ref_px`),
  `section10_threshold_sensitivity.csv` (tree/ref/paired counts as each threshold is
  varied, under two baselines — `operating_point` = canopy at the 40 % operating point,
  `preregistered` = canopy held at the 70 % bar [0 everywhere]; the adopted operating
  canopy row is flagged `is_operating_point`), and the validation sample CSV. Figures: the
  validation chip grid + `figures/section10_pixel_class_map.png`. The run **derives the
  operating `CANOPY_THR` from the ≥10-paired rule and asserts it equals `config.CANOPY_THR`**
  (so config and the derivation never drift), re-opens the saved raster, **asserts it
  aligns to `reference_grid.tif`** (CRS/shape/transform) and re-checks a random sample of
  tree pixels against the config thresholds.
- `section11_anomalies.py` — Section 11: **compute anomalies and deseasonalize the stress
  variables — standardized z-scores for VPD, NDMI (water supply) and soil moisture**
  (steps 58–61). Reads only `data/interim/era5land_vpd_sm_hourly_2018_2024.nc`, the
  Section 9 `data/processed/analysis_cube_70m.zarr` (for the 66-overpass axis + matched
  ERA5 hour) and the Section 4 NDMI composite (no network). Produces
  `../data/processed/section11_zscores_70m.zarr`. `test_section11_anomalies.py` covers its
  pure logic. Run: `python src/section11_anomalies.py` (`--no-figures` to skip the QC
  figures, `--verify-only` to re-open the saved store and re-run verify + QC). `config.py`
  gains `CLIMATOLOGY_WINDOW_DAYS = 15`.

  **Two methods, forced by what data exist (documented prominently in the header + the QC
  note + `data/processed/README.md`).** Each stress variable entering the Compound Stress
  Index is converted to a standardized anomaly, but the *method* differs by data
  availability:

  **VPD & soil moisture — rigorous temporal day-of-year-AT-OVERPASS-HOUR LOYO
  climatology.** The 2018–2024 *hourly* record exists only for ERA5-Land VPD + soil
  moisture. For each overpass (day-of-year *D*, matched ERA5 hour *H*, year *Y* = 2023) the
  **normal** at each native pixel = mean of values at **hour-of-day == *H*** over all days
  with **|doy − D| ≤ 15** across 2018–2024 **excluding year Y** (**leave-one-year-out**,
  step 60); the **std** is over the same set; `z = (observed − normal)/std`. Building the
  climatology *at the overpass hour* (step 59) keeps the daily cycle out of the anomaly.
  The work is done in **native ERA5 8×10 hourly space, then the per-overpass z (and the
  clim mean/std) are bilinear-regridded to 70 m** — so observed and climatology live in the
  same space (cleaner than mixing the cube's regridded observed with a native climatology).
  The ±15-day window is **clipped** to the warm season (no day-of-year wraparound — it is
  within-season), so the earliest-June / latest-September overpasses get a **one-sided
  window** (13 of 66; expected, documented). The observed value (the z numerator) is
  recomputed from the `.nc` at the matched hour, not reused from the cube.

  **NDMI — a SPATIAL standardized anomaly (a documented, data-forced deviation, analogous
  to Section 10's canopy operating-point decision).** Section 4 produced **only one**
  warm-season median NDMI composite (2023) — there is **no** multi-year or multi-date NDMI
  series — so a 2018–2024 day-of-year climatology **cannot** be built. The water-supply
  z-score is therefore a **spatial** standardized anomaly `z_NDMI(pixel) = (NDMI − μ)/σ`,
  with **μ and σ over all valid 70 m NDMI pixels** in the study domain (the documented
  reference population: **1 544 052** px; μ ≈ −0.0677, σ ≈ 0.0850). This z **varies by
  pixel, not by overpass**, and is **broadcast to all 66 overpasses** to give the
  per-pixel-per-overpass shape the protocol asks for. **Consequence (stated plainly):**
  unlike VPD/SM (true multi-year hourly → rigorous temporal LOYO climatology), NDMI has a
  single 2023 composite, so a temporal deseasonalization is impossible; a spatial
  standardization is used as the water-supply z that feeds Section 12's supply stress — so
  the **water-supply stress is a spatial field constant in time**, and the CSI's *temporal*
  variation comes from VPD. **Soil-moisture z is the protocol's temporal *check*** on the
  water-supply story and is kept.

  **QC (step 4 — the heart of the section; full account in
  `docs/section11_anomaly_qc_note.md`).** Whole-record mean/std: **`vpd_z` +0.12 / 0.95**
  (on target). **`sm_z` −0.09 / 0.45** — mean ≈ 0 but **std < 1**, which is a *real*
  single-pilot-year property (2023 overpass-hour soil moisture deviated *less* than the
  full 2018–2024 spread; **identical native & regridded**, so not a pipeline bug; SM is a
  slow root-zone state and the protocol's *check*, not a primary driver). **`ndmi_z`
  0.00 / 1.00** by construction. **Seasonal cycle removed as a function of day-of-year**
  (the protocol pitfall guard): the run proves it directly on the **dense** ERA5 record —
  the day-of-year VPD normal **tracks the within-season march** (3.74 → 2.83 kPa, Jun →
  Sep) while a single whole-season normal is **flat** (3.32 kPa), so the residual
  June-low/July-high z pattern is **real 2023 weather** (cool-humid early June, the record
  July heat), *not* the whole-season artifact (`figures/section11_seasonal_cycle_check.png`
  shows both panels). **Extreme positive VPD-z:** because z is standardized *per
  hour-of-day*, the strict top-5 is brittle, so the robust statistic is **enrichment** — the
  2023-06-30…07-30 heatwave window is **23 % of overpasses but 64 % of the top-11 VPD-z →
  2.80× enriched** (the #2 overpass overall is **2023-07-20**, a heatwave date). One extreme
  date is mapped (`figures/section11_vpd_z_extreme_date_map.png`) — a smooth city-wide
  positive VPD-z field (ERA5-Land ~9 km → varies gently, as a regional driver should),
  spatially sensible.

  **Deliverables (`data/processed/`, git-ignored).** `section11_zscores_70m.zarr` (dims
  `overpass=66 × y × x`; vars `vpd_z`, `sm_z`, `ndmi_z` + the **saved climatology**
  `vpd_clim_mean`/`vpd_clim_std`/`sm_clim_mean`/`sm_clim_std`; aligned to
  `reference_grid.tif`, asserted on reload) and `section11_zscores_overpass_summary.parquet`
  (66-row per-overpass regional-mean z + clim + season part). Figures: the z-distribution
  histograms, the seasonal-cycle check (two panels) and the extreme-date VPD-z map. The QC
  results note is `docs/section11_anomaly_qc_note.md`. The run re-opens the saved store and
  **asserts geometry == `reference_grid.tif`** (CRS/shape/transform), 66 overpasses, all z +
  climatology vars present and float, and that `ndmi_z` is constant across overpasses.
- `section12_compound_stress.py` — Section 12: **combine the standardized demand and supply
  anomalies into the Compound Stress Index (CSI)** (steps 62–66). Reads **only** the Section 11
  `data/processed/section11_zscores_70m.zarr` z-scores (no network). Produces
  `../data/processed/section12_csi_70m.zarr`. `test_section12_compound_stress.py` covers its
  pure logic. Run: `python src/section12_compound_stress.py` (`--no-figures` to skip the QC
  figures, `--verify-only` to re-open the saved store and re-run verify + QC). `config.py`
  gains the baseline weights `WEIGHT_DEMAND = 0.5`, `WEIGHT_SUPPLY = 0.5`.

  **Definitions (from the Section 11 z-scores — never raw values).** **Demand stress** =
  the positive part of the VPD z-score, **`demand = max(vpd_z, 0)`** (step 62; only
  above-normal VPD is stressful). **Supply stress** = the positive part of the **negated**
  water-supply z-score, **`supply = max(-ndmi_z, 0)`** (step 63; low water → positive stress,
  so a below-normal NDMI — a *negative* z — becomes a positive contribution). Baseline
  **`CSI = WEIGHT_DEMAND·demand + WEIGHT_SUPPLY·supply`** with **equal weights 0.5/0.5**
  (step 64). **CSI ≥ 0 everywhere** (built from non-negative parts with non-negative weights;
  near 0 = near-normal, large = a compound heat–drought extreme).

  **The COMMON PITFALL is guarded both ways.** If the supply stress were built from **raw
  NDMI** instead of its z-score, it would not be on the demand stress's scale and the
  equal-weight combination would be dominated by whichever variable has the larger numeric
  range. This module reads **only** `vpd_z` and `ndmi_z` from the Section 11 store (never the
  raw VPD/NDMI in the Section 9 cube); `_assert_inputs_are_zscores` **fails the build** unless
  `ndmi_z` is mean ≈ 0 / std ≈ 1 (a raw NDMI field is mean ≈ −0.07 / std ≈ 0.09) and `vpd_z`
  straddles 0 (raw VPD in kPa is ≥ 0); and the unit tests prove the supply stress built from
  the z-score carries a balanced ~half of the CSI while a raw-NDMI supply is swamped by demand.

  **Demand is TIME-VARYING; SUPPLY is STATIC IN TIME (carried forward from Section 11).**
  `vpd_z` varies per overpass (true temporal climatology), so the demand stress varies in
  time. `ndmi_z` is a **spatial** standardization of the single 2023 NDMI composite (Section 11
  decision B) — **constant across the 66 overpasses** — so the supply stress is **constant in
  time** (asserted on reload: `supply_stress` is identical across overpasses). **Consequence
  (stated plainly):** because the supply term is the same for every overpass, the **temporal
  ranking of the spatial-mean CSI equals the ranking of the VPD demand** (verified in-code: the
  CSI and demand orderings are identical) — i.e. *the highest-CSI dates are the highest
  VPD-demand dates*.

  **Confirming the compound extremes (step 65 deliverable).** CSI min/mean/max = **0.000 /
  0.421 / 5.453** (≥ 0 everywhere; **98.96 %** of pixel-overpass cells finite). Because VPD-z is
  standardized **per hour-of-day** (Section 11), a calm low-variance night can post a high z
  without being a heat extreme, so a brittle top-1 is unreliable; the **robust statistic is the
  heatwave-window ENRICHMENT** (reused verbatim from Section 11 — single source of truth). The
  known 2023 peak-heat window (≥110 °F streak ~Jun 30 – Jul 30, Phoenix's hottest month on
  record) is **23 % of all overpasses but 64 % of the top-11 highest-CSI overpasses → 2.80×
  enriched** (identical for CSI and demand, as expected from the static supply). 7 of the
  top-10 highest-CSI overpasses fall in July; the strict #1 is 2023-09-10 (a high-VPD-z calm
  pre-dawn overpass — exactly the per-hour-standardization subtlety, which is why enrichment,
  not top-1, is reported), and the #2 is **2023-07-20**, a core heatwave date.

  **Sensitivity HOOKS (step 66) — present but NOT run.** `compute_csi(demand, supply,
  w_demand, w_supply)` is a **parameterised** function so the unequal-weight test is a trivial
  re-call; `copula_weights(...)` is a **`NotImplementedError` STUB** (a clearly-labelled
  placeholder for the copula-derived weights, with a `# TODO Section 12 step 66` note) that is
  **deliberately not executed**. The baseline deliverable uses the equal 0.5/0.5 weights only.

  **Deliverables (`data/processed/`, git-ignored).** `section12_csi_70m.zarr` (dims
  `overpass = 66 × y = 1155 × x = 1339`; vars `csi`, `demand_stress`, `supply_stress`; aligned
  to `reference_grid.tif`, asserted on reload — CRS/shape/transform, 66 overpasses, all vars
  float, **CSI ≥ 0 everywhere**, and `supply_stress` constant in time) and
  `section12_csi_overpass_summary.parquet` (66-row per-overpass spatial-mean csi/demand/supply
  + season part + in-heatwave flag, sorted by CSI). Figures:
  `figures/section12_csi_distribution.png` (the CSI distribution with the demand/supply
  components, plus the spatial-mean CSI per overpass with the heatwave window shaded) and
  `figures/section12_csi_extreme_date_map.png` (the 70 m CSI field for the highest-CSI
  overpass).

- `section13_master_table.py` — Section 13: **compute the cooling advantage and assemble the
  master analysis table** (steps 67–71). Reads the Section 9 cube (`lst`/`et`/`esi`/`pdsi` +
  static `ndvi`/`canopy`/`impervious`), the Section 12 `csi`, the Section 11 `vpd_z`/`ndmi_z`,
  the Section 10 class raster (`section10_pixel_class_70m.tif`) and paired-BG list
  (`section10_paired_neighborhoods.csv`), the block-group attributes and the tree inventory
  (no network). Produces `../data/processed/master_table.parquet` — **the single input to every
  analysis from here on.** `test_section13_master_table.py` covers its pure logic. Run:
  `python src/section13_master_table.py` (`--no-figures` to skip the QA figure, `--verify-only`
  to re-open the saved table and re-run verify + QC).

  **Granularity: one row per (paired neighborhood, overpass).** Only the **9 paired block
  groups** (Section 10's paired design) enter, over the 66 overpasses → up to 594 candidate
  rows, but a row is **emitted only where the cooling advantage is computable** — the BG must
  have **≥ 1 tree pixel AND ≥ 1 reference pixel with finite LST on that overpass** (so both
  step-67 means exist). **264 rows** result (9 neighborhoods × 54 distinct overpasses; some
  small-tree BGs have no finite tree-LST on some overpasses, hence < 594).

  **Primary outcome — cooling advantage (step 67).** `cooling_advantage = mean LST(reference)
  − mean LST(tree)` over the BG's finite-LST pixels that overpass (Kelvin = °C, a temperature
  difference). Positive = trees cooler than the surrounding built surfaces; near zero = the
  benefit is gone. Because both terms come from the **same overpass**, shared weather and
  time-of-day cancel. **It can be negative and is never clipped.** Observed spread: **min
  −6.35, median +2.81, mean +3.66, max +23.06 K; 43/264 (16.3 %) negative** — mostly positive
  (trees cooler) with a tail to/below zero (the negatives are mostly small-magnitude pre-dawn
  overpasses; the +23 K max is a single-tree-pixel BG — noise the count columns expose).

  **Mechanism + stressor over the TREE pixels (step 68).** `mean_et_tree`, `mean_esi_tree`
  (ET/ESI mean over the BG's tree pixels — **NaN on the 21 overpasses without ET/ESI**, ~22.7 %
  of rows, Section 3 caveat), and `mean_csi_tree`, `mean_vpd_z_tree`, `mean_water_supply_z_tree`
  (CSI / VPD-z / NDMI-z means over the tree pixels; CSI/VPD-z are nearly spatially uniform —
  ERA5 ~9 km — while NDMI-z varies spatially and is static in time).

  **Modifiers.** `mean_impervious` / `mean_canopy` are **neighborhood-level** means over all
  valid BG pixels (a context modifier — the built-ness of the whole neighborhood, *not* just
  the tree pixels). `aridity` = the **BG-mean PDSI** that overpass (**negative = drier**; NaN on
  the 3 earliest pilot overpasses with no containing pentad — 9/264 rows). `irrigation_proxy` is
  the documented step-70 composite (below). `functional_type` = the **modal `water_use`**
  (drought_tolerant vs mesic) among inventory trees inside the BG (modal `leaf_habit` carried as
  `functional_leaf_habit`); **`unknown` for all 9 paired BGs here** because the street-tree
  inventory covers only a compact **central-Phoenix** box (UTM ~386–405 km E / 3694–3713 km N)
  while the paired BGs sit on the metro periphery — a direct point-in-polygon join finds **zero**
  inventory trees in any paired BG. This is the protocol's anticipated "central-Phoenix coverage
  → many BGs unknown" limitation, handled gracefully (not a join bug).

  **Irrigation-likelihood proxy (step 70) — DOCUMENTED FORMULA.**
  `irrigation_proxy = mean( norm(turf_fraction), norm(income), norm(1 − impervious_fraction) )`
  where `norm(c) = (c − min c)/(max c − min c)` **across the 9 paired neighborhoods** (equal
  1/3 weights; result in [0,1], higher = more likely irrigated). `turf_fraction` = share of BG
  pixels with **NDVI > `NDVI_THR` (0.50) AND canopy < `REF_CANOPY_MAX` (20 %)** — the irrigated
  *green-but-not-tree* lawn/turf signature (high NDVI without canopy); `income` = ACS median
  household income (**missing → paired-BG median before normalization**; one BG); `1 −
  impervious_fraction` = perviousness (`impervious %/100`). It is **static per BG** (no overpass
  dependence) and a **documented heuristic that ranks** neighborhoods by irrigation likelihood,
  **not a measurement** of water applied. Observed range over rows: **[0.009, 0.742]**.

  **Neighborhood + counts.** `median_income` / `pct_poc` / `svi` come from the block-group
  attributes (the parquet, for exactness). **All pixel-count columns are KEPT** for the Section
  14 minimum-count filter: `n_tree_px` / `n_ref_px` (static, from the class raster),
  `n_tree_valid` / `n_ref_valid` (finite-LST pixels that overpass — the actual sample sizes), and
  `n_good_obs = min(n_tree_valid, n_ref_valid)` (the binding paired sample size). **Thin paired
  sample (carried, not hidden):** ranges `n_tree_px` 1–171 (one BG, 040139412001, has 171; the
  others 1–6), `n_ref_px` 332–1122, `n_good_obs` 1–171 (median 2) — so **many rows rest on a
  single tree pixel**, which the Section 14 threshold estimate must be reported with.

  **Deliverable (`data/processed/`, git-ignored).** `master_table.parquet` (264 rows × 26
  columns; one row per paired neighborhood per overpass; columns grouped identifiers / outcome /
  mechanism / stressor / modifiers / neighborhood / counts), re-opened and **asserted on reload**
  (every column present, one row per (neighborhood, overpass), `cooling_advantage == reference −
  tree`, `n_good_obs == min(n_tree_valid, n_ref_valid)`, and every row has ≥ 1 finite tree &
  reference pixel). QA figure: `figures/section13_cooling_advantage_distribution.png` (the
  cooling-advantage distribution + the per-overpass spread).
- `section14_threshold.py` — **Section 14: exploratory analysis + the first threshold estimate**
  (steps 72–79) — the **final section** of the pilot and the **first scientific result**. This is
  the **reusable analysis logic** that the deliverable notebook
  (`notebooks/14_exploratory_threshold.ipynb`) imports and calls; it reads **nothing** and writes
  **nothing** (the notebook does the IO — reading only `data/processed/master_table.parquet` — and
  the figures). numpy / pandas / (pwlf, ruptures, statsmodels, scipy) only.
  `test_section14_threshold.py` exercises the risky numerics on tiny synthetic series in the canopy
  env (no IO). Run the notebook: `python -m`-free —
  `conda run -n canopy jupyter nbconvert --to notebook --execute --inplace
  notebooks/14_exploratory_threshold.ipynb`; run the tests:
  `conda run -n canopy python src/test_section14_threshold.py`.

  **What it computes.** `describe_shape` (Pearson/Spearman/OLS slope of the scatter, step 72);
  `bin_means` (per-bin mean / SEM / count of cooling advantage, NaN-pairwise-dropped, step 73 — and
  reused for the ET/ESI overlay, step 74); `apply_min_count` (the minimum-`n_tree_valid` filter,
  step 75); `linear_fit` and `segmented_fit` (the null straight-line model and the one-breakpoint
  continuous piecewise fit via `pwlf`, step 76) with `compare_linear_segmented` (ΔR² / ΔAIC — is the
  kink worth it?); `bootstrap_breakpoint` (row-resampled CI for the breakpoint + `spans_fraction` =
  CI width as a fraction of the CSI range, step 77); `changepoint_csi` (an **independent** single
  change-point on the CSI-ordered cooling-advantage sequence via `ruptures` l2 mean-shift, step 78);
  `et_declines_beyond` (mean ET below vs above the candidate threshold — the mechanistic check, step
  74); and `methods_agree` + `threshold_verdict` (the **honesty gate**, steps 78–79).

  **The honesty gate (the protocol's common pitfall, encoded in code — non-negotiable).** A
  segmented regression **always** returns a breakpoint, even on a straight line or pure noise (proven
  in the unit tests). `threshold_verdict` therefore reports a threshold as **credible only if ALL of**:
  (i) the two methods **agree** — the `ruptures` change-point lies inside the breakpoint's bootstrap
  CI *or* within a documented tolerance (`AGREE_TOLERANCE_FRACTION = 0.20` of the CSI range, which
  absorbs the known pwlf-knee-vs-ruptures-mean-shift location offset); (ii) the breakpoint is **well
  identified** — the bootstrap CI width is < `WIDE_CI_FRACTION = 0.5` of the CSI range; (iii) a
  **bend is visible** — the post-break slope is ≥ `BEND_SLOPE_DROP = 0.5` K/CSI-unit more negative
  than the pre-break slope; and (iv) **ET corroborates** — mean ET declines beyond the candidate
  threshold. Otherwise the verdict is **"no robust threshold detected"** — an explicitly valid
  outcome. (The wide-CI gate also rejects the degenerate case where a CI spanning the whole range
  trivially "contains" the change-point.) `analyze_sample` runs the whole pipeline on one
  (CSI, cooling-advantage[, ET]) sample and returns a `ThresholdVerdict`.

  **Phoenix pilot result — NO ROBUST THRESHOLD DETECTED** (`docs/section14_results_note.md`). Run on
  three samples — the **full** 9-BG sample (`n_tree_valid ≥ 1`, n = 264), a **modest** filter
  (`≥ 3`, n = 107), and the **robust** subset (`≥ 10`, n = 31, which collapses to the single
  well-sampled BG `040139412001` — the thin-sample sensitivity made explicit) — the verdict is the
  **same in all three**: the cooling-advantage vs CSI relationship is **flat** (|Pearson r| < 0.1,
  p > 0.3 everywhere; linear R² ≈ 0.001–0.009), the segmented kink is **not preferred** over a
  straight line (ΔAIC = +1.4 / +1.5 / +2.1, all > 0), the breakpoint is **not identified** (bootstrap
  CI spans **62 % / 88 % / 97 %** of the CSI range; the full-sample bootstrap distribution is
  multimodal), the two methods do **not** agree on a well-identified break, and **ET shows no
  decline** beyond the candidate breakpoint (no mechanistic signature). This is the **expected**
  outcome for the pilot, driven by (a) the **thin paired sample** (9 BGs, one dominant, median
  `n_good_obs` = 2; the most extreme cooling advantages rest on a single tree pixel — not clipped,
  but down-weighted by the min-count filter and reported via sensitivity) and (b) a **CSI axis that
  is ≈ a VPD-demand axis** (the NDMI supply z is static in time, so the between-BG CSI spread is ~10×
  smaller than the within-BG temporal spread). A defensible threshold needs the denser, multi-city
  sample of the **cross-city phase** that this section gates into. Figures (`figures/section14_*.png`):
  the scatter, the binned mean ± SEM, the ET/ESI overlay, the distribution/QC panel, and the
  segmented-fit + bootstrap-CI-histogram. **The executed notebook is the deliverable** (committed with
  outputs; it is code/output, not data).
