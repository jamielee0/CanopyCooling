# Design decisions & methodology

The single authoritative record of *why* the pipeline is built the way it is. Code
modules carry only a short header and a pointer here; the deep rationale lives once,
in this file. For the per-section QC numbers and the final result narrative see
[`section11_anomaly_qc_note.md`](section11_anomaly_qc_note.md) and
[`section14_results_note.md`](section14_results_note.md); for the step-by-step run
order see [`pipeline.md`](pipeline.md).

Standing rule for the whole project: **every figure and number must be reproducible
from the saved code — nothing produced by hand.** Each section module re-runs end to
end and re-opens its own output to assert geometry against `reference_grid.tif`.

---

## Section 1 — Fixed analysis geometry (`config.py`, `build_reference_grid.py`)
The domain (bbox `-112.55..-111.55 E`, `33.20..33.92 N`), projection (**EPSG:32612**,
UTM 12N), cell size (**70 m**, ECOSTRESS native), grid (1155×1339, origin
`(355460, 3754380)`), and time windows are **frozen literals** in `config.py`, derived
once by `build_reference_grid.py` and never recomputed at runtime — so every run is
byte-for-byte identical. `reference_grid.tif` is the geometric anchor every later layer
is matched and asserted against.

## Section 2 — ECOSTRESS LST
Land-surface temperature acquired + QC'd into a time-indexed Zarr cube. The **66 LST
overpasses are the master time axis** for the whole analysis (Section 9 reconstructs the
`overpass_key` `{orbit}_{scene}_{YYYYMMDDTHHMMSS}` since the LST cube lacks the coord).
- **Mandatory-QA coverage policy:** retain low-bit classes `00` and `01`; reject `10` and
  `11`. Class `01` is still disclosed as potentially degraded rather than relabelled as
  best quality. Its inclusion is a professor-approved coverage decision for this data-limited
  pilot. The independent finite-LST, clear-cloud, and land-only gates remain unchanged.
- **Auditable contribution of `01`:** the production granule report stores both the strict
  `00`-only count and the additional `01` count for every tile. The rebuild increased valid
  granule pixels from 107,114,822 to 112,237,722 (+5,122,900; +4.78% versus `00` only),
  recovered one tile at the 1% coverage cutoff, and recovered no new overpass (66 before and
  after). See [`section2_qc01_coverage_audit.md`](section2_qc01_coverage_audit.md).

## Section 3 — ECOSTRESS ET / ESI (supporting evidence ONLY)
- **ET/ESI are a mechanism check, never a primary measurement.** The PT-JPL ET product is
  built for *natural vegetation* and is **unreliable over built-up areas**; its use is
  **restricted to high-tree-fraction pixels** (Section 10) and it is allowed to corroborate
  or stay silent, never to drive a conclusion.
- **Product identity.** The protocol's example name `ECO_L3T_ET_PT-JPL` does not exist in
  ECOSTRESS Collection 2. PT-JPL ET is the **`PTJPLSMinst` layer of `ECO_L3T_JET` v002**;
  ESI is **`ECO_L4T_ESI` v002** (with its `PET` layer). Neither tiled product carries a
  QC-bits layer.

## Section 4 / 4b — Sentinel-2 NDVI & NDMI
- Source `COPERNICUS/S2_SR_HARMONIZED`; SCL cloud/shadow/snow mask drops classes
  {3,8,9,10,11}; NDMI = `(B8−B11)/(B8+B11)`. Pulled to disk with
  `geemap.download_ee_image` (geedim under the hood — no Drive round-trip).
- **NDMI is a 20 m product, not 10 m** (SWIR band B11 is native 20 m). NDVI (B4,B8) is
  genuine 10 m. Both are resampled **bilinear** onto the common 70 m grid.
- **Why Section 4b exists — a time-resolved vegetation check.** Section 4 produced a single
  2023 warm-season NDMI median, which cannot diagnose vegetation condition at individual
  overpasses. Section 4b supplies per-overpass `observed` NDMI (±15 d around each 2023
  overpass) plus a 2018–2024 **leave-one-year-out** day-of-year climatology (`clim_mean`,
  `clim_std`). This supersedes the static composite as the input to Section 11's `ndmi_z`
  vegetation-condition check. NDMI is **not** the primary water-supply axis and does not enter
  the current CSI; root-zone soil-moisture `sm_z` fills that role.

## Section 5 — Land cover, impervious %, canopy %
- **Datasets (most recent official):** impervious % + land-cover class from
  `USGS/NLCD_RELEASES/2021_REL/NLCD` (year 2021); tree canopy % from USFS TCC
  `…/Product_Version/2025-6` (year 2025). All native 30 m.
- **Resampling is the crux.** Impervious % and canopy % → 70 m by exact **area-weighted
  averaging** (unit-tested vs hand computation). The land-cover **class** layer is
  categorical → **nearest neighbour only**; averaging would invent fractional classes.
- **geedim `nodata=0` trap.** For impervious/canopy, 0 % is a *valid* value, so those two
  are read **unmasked** — masking would drop every 0 % cell and bias the mean upward. For
  the class layer 0 = "no class" (correctly masked). Layers stay in native **percent (0–100)**
  because the Section 10 thresholds are stated in percent.

## Section 6 — ERA5-Land VPD & soil moisture
Hourly 2018–2024 VPD + soil moisture (native ~9 km, EPSG:4326). The **only** layer Section 9
itself resamples (bilinear, continuous field). On the 70 m grid it is a smooth **regional**
background, not block-scale detail. The depth-weighted 0–28 cm root-zone soil moisture becomes
`sm_z`, the **primary water-supply axis**. NDMI remains a separate vegetation-condition check;
it is not substituted for soil moisture simply because it has finer spatial resolution.

## Section 7 — Precipitation & drought
- PRISM daily ppt → **antecedent precipitation** rolling totals over the preceding
  30/60/90 days; GRIDMET DROUGHT (`pdsi`, `spei30d`, `spei90d`); PRISM `tmean` as an
  independent cross-check on ERA5-Land air temperature. All **bilinear** to 70 m (continuous).
- **Robustness on a flaky host:** PRISM daily files are rate-limited (2×/IP/day); a
  rate-limited day **self-heals via the 800 m endpoint** averaged back to the 4 km clip grid;
  a corrupt SSL trust store transparently falls back to certifi's CA bundle. The coarse
  fields (~4 km / ~4.6 km) on 70 m are **regional context**.

## Section 8 — Neighborhood attributes, tree inventory, building footprints
- **ACS** 5-year vintage **2024**, block-group, Maricopa (state 04 / county 013):
  `B19013_001E` (median income) + `B03002`. **%-people-of-colour = 100·(total − non-Hispanic
  White alone)/total**. Census **jam values** (e.g. `-666666666`) → null, never averaged.
- **SVI is tract-level**, joined **down** to block groups by FIPS (a BG inherits its parent
  tract's `RPL_THEMES`; the first 11 digits of a 12-digit BG GEOID are the tract GEOID). So
  **SVI varies at tract scale**, not BG scale. `-999` sentinel → null.
- **Tree inventory:** the Phoenix open-data CKAN portal has **no** per-tree inventory; the
  real source is the ASU-hosted **`street_trees_gao_map_by_species` (GAO)** layer (~22.5k
  street/park trees). **Functional type is primary** (`water_use`, `leaf_habit` from a
  genus/species lookup); species detail is secondary. **No true planting year exists** in any
  accessible Phoenix inventory — the survey date is kept as `inventory_year` (do **not** use
  for tree age); `planting_year` is present but null for every record. Coverage is **central
  Phoenix** only.
- **Footprints:** Microsoft Planetary Computer STAC `ms-buildings` (anonymous, signed),
  Bing level-9 quadkey partitions over the bbox (~1.47 M polygons), clipped/reprojected to
  EPSG:32612; Azure-geojson fallback if the STAC read fails. They carry **geometry only — no
  height field** (see Section 10 tall-building proxy).
- **Rasterization:** BG income/%POC/SVI burned to 70 m by **nearest / value-per-cell** —
  already-aggregated quantities, never bilinear.

## Section 9 — Harmonization & time-matching (`analysis_cube_70m.zarr`)
- **Already-gridded vs resampled.** Sections 2–8 already wrote to the reference grid, so step
  47 is a **verification** (assert identical CRS/cell/origin/shape) — not a re-snap. Only
  ERA5-Land is resampled here. `landcover_class` is carried as **integer** classes (asserted
  no fractional classes on reload).
- **Time-matching rule per overpass:** ERA5 VPD+SM at the **nearest hour** (only the matching
  hourly slice is reprojected — 66 small reprojections, not all 20,496 hours); antecedent
  precip + `tmean` at the **exact date**; GRIDMET drought at the **pentad whose 5-day window
  contains the date**. The drought cube holds only warm-season pentads, so the **3 earliest
  pilot overpasses (2023-06-02/03) have no containing pentad and are left NaN** — an honest
  absence, not a stale prior-September value.
- A full pixel×overpass tidy table (~100 M rows) is **deliberately not** produced here (the
  analysis pixels are not defined until Section 10); only a 66-row per-overpass summary.

## Section 10 — Paired-design pixel classification
- **Tree-dominated = AND of five criteria:** NDVI > 0.5 **and** canopy % > `CANOPY_THR`
  **and** impervious % < 20 **and** not water (NLCD 11) **and** ≥ `MIN_OBS` finite LST obs.
  The conjunction encodes the pitfall guard: high NDVI *alone* (irrigated grass / golf turf)
  must **not** qualify — canopy must *also* be high.
- **Reference pixel (strict M1 rule):** canopy < 20 %, impervious cover > 20 %, and NLCD
  developed low/medium/high intensity (22/23/24), with ≥ `MIN_OBS` observations, in a BG that
  also holds a tree pixel. NLCD 21 (developed open space) is excluded because it can represent
  irrigated or otherwise vegetated open space rather than a hot urban comparison surface. The
  canopy and impervious inequalities are strict, and missing canopy/impervious values fail.
  Pixels remain **paired by block group**; tree/reference pixels in unpaired BGs are demoted.
  On the rebuilt Phoenix inputs this restriction reduces the final reference set from the broad
  comparator pool to 1,457 pixels while retaining 206 tree pixels and all 9 paired BGs.
- **Tall-building buffer = a documented proxy.** Footprints have **no height field**, so
  "tall/large" is proxied by footprint **area > 1000 m²** (just below the 99th pct ~1665 m² →
  the largest ~2 % of ~1.47 M footprints); buffering only those by 70 m excludes ~12 % of the
  grid. Buffering *all* footprints would over-exclude the built area.
- **OPERATING `CANOPY_THR = 40 %` from a pre-outcome canopy-layer rule (M2).** The committed
  rule is `max(P90 canopy among finite, building-excluded pixels with NDVI > 0.5, 40 %)`. It
  cannot inspect block-group geometry, reference yield, or the number of paired BGs. In Phoenix
  the eligible pool has 35,850 pixels and raw P90 = 8.143 %, so the hard 40 % physical-signal
  floor binds. The 70 m canopy layer (USFS TCC area-weighted to 70 m) maxes at 69.53 % (mean
  0.88 %), so the pre-registered 70 % bar remains unreachable and is preserved separately as
  `CANOPY_THR_PREREGISTERED`. The sensitivity CSV reports sample-yield dependence after the
  operating rule is fixed; it never selects the threshold.

  Stored-input recomputation under the strict reference rule gives:

  | CANOPY_THR | tree px | reference px | paired BGs |
  |---|---|---|---|
  | 35 % *(below floor, context only)* | 334 | 2,785 | 14 |
  | **40 % — adopted** | **206** | **1,457** | **9** |
  | 45 % | 116 | 1,342 | 7 |
  | 50 % | 58 | 770 | 4 |
  | 55/60/65/70 % | 29/7/2/**0** | 445/124/124/**0** | 2/1/1/**0** |

- **9 paired BGs is a thin design** — a genuine limitation the Section 14 estimate must be
  reported with. Visual validation samples ≤60 tree pixels over Esri imagery; the **human
  agreement rate is `PENDING USER REVIEW`** (never fabricated).

## Section 11 — Anomalies & deseasonalization (z-scores)
- All three stress variables become a **temporal day-of-year leave-one-year-out (LOYO)
  anomaly**. VPD/SM: for each overpass (day-of-year *D*, ERA5 hour *H*, year 2023) the normal
  = mean over hour == *H*, |doy − D| ≤ 15, 2018–2024 **excluding 2023**; `z = (obs − normal)/
  std`. Building the climatology *at the overpass hour* keeps the daily cycle out. Computed in
  native ERA5 space then bilinear-regridded to 70 m. The ±15-day window is **clipped** to the
  season (no wraparound), so the earliest-June/latest-September overpasses get a one-sided
  window (13 of 66; expected).
- **Supply construct:** `sm_z`, the root-zone-soil-moisture anomaly, is the primary water-supply
  variable. Its regional resolution is stated explicitly rather than relabelling a vegetation
  index as soil moisture.
- **Vegetation check:** `ndmi_z` is the same temporal LOYO anomaly (from Section 4b), computed
  per-overpass directly on the 70 m grid, replacing the former static spatial standardization.
  It varies in time and space but is not consumed as the primary supply variable.
- A single analysis year need not have anomaly mean 0; only the leave-one-year-out climatology
  is centred.
- See [`section11_anomaly_qc_note.md`](section11_anomaly_qc_note.md) for the QC numbers and the
  seasonal-cycle-removed proof.

## Section 12 — Compound Stress Index (CSI)
- **Demand = `max(vpd_z, 0)`** (only above-normal VPD is stressful); **supply = `max(−sm_z,
  0)`** after the documented robust scale adjustment (below-normal root-zone soil moisture →
  positive stress). **CSI = 0.5·demand + 0.5·supply** (equal weights
  `WEIGHT_DEMAND`/`WEIGHT_SUPPLY`). **CSI ≥ 0 everywhere** by construction.
- **Pitfall guarded both ways.** Inputs are the Section 11 **z-scores, never raw VPD/SM**.
  Assertions require z-like input ranges and confirm that supply is `config.SUPPLY_VAR ==
  "sm_z"`; `ndmi_z` is carried only as the vegetation-condition check.
- Both demand and supply are time-varying. CSI is retained as a **secondary scalar** useful for
  corroboration and cross-city summaries, while the primary RQ1 detector keeps VPD and soil
  moisture separate in the Section 15 two-dimensional response surface.
- **Unequal-weight sensitivity executed (step 66):** the same demand/supply component arrays
  are recombined at weights 0/1, 0.3/0.7, 0.5/0.5, 0.7/0.3, and 1/0. Section 12 persists
  temporal-rank and heatwave-enrichment diagnostics in
  `section12_weight_sensitivity.parquet`; Section 14 carries the five scenarios through the
  identical daytime-primary rows and block-group bootstrap in
  `section14_csi_weight_sensitivity.csv`. The equal row must reproduce baseline exactly.
  `copula_weights(...)` remains an explicit `NotImplementedError`: no defensible estimator was
  pre-specified, so no data-driven weights are invented.

## Section 13 — Cooling advantage & master table
- **One row per (paired BG, overpass)**, emitted only where computable (BG has ≥1 tree and ≥1
  reference pixel with finite LST that overpass) → **266 rows** (9 BGs × 54 represented
  overpasses; not every BG is computable on every overpass).
- **Primary outcome — `cooling_advantage = mean LST(reference) − mean LST(tree)`** (Kelvin =
  °C). Both terms from the **same overpass**, so shared weather/time-of-day cancel. **Never
  clipped** — can be negative. After the strict-reference correction, observed median is
  +2.881 K and 16.5% of rows are negative.
- Section 13 also persists `mean_demand_stress_tree` and `mean_supply_stress_tree` over one
  shared finite-pixel mask. Their configured weighted mean exactly reconstructs
  `mean_csi_tree`, making the Section 14 weight sensitivity row-comparable.
- `irrigation_proxy = mean( norm(turf_fraction), norm(income), norm(1 − impervious) )` across
  the 9 paired BGs (equal thirds, [0,1], higher = more likely irrigated) — a documented
  **heuristic ranking, not a measurement**.
- `functional_type` is **`unknown` for all 9 paired BGs**: the street-tree inventory covers
  only central Phoenix while the paired BGs sit on the metro periphery → a point-in-polygon
  join finds zero inventory trees in any paired BG (the anticipated coverage limitation, not a
  join bug).
- **Primary sample is persisted, not reconstructed downstream.** Section 13 writes `local_hour`,
  `is_day`, and `sample_label` to both BG and pixel tables. `sample_label == "primary"` requires
  `n_tree_valid >= 3`; downstream headline estimates additionally require `is_day == True`.
  Lower-count, night, and pooled-overpass rows are sensitivity-only.
- **Thin sample, carried not hidden:** `n_tree_px` 1–179 (one BG holds 179, the rest 1–8), and
  Phoenix contains only 9 paired block groups — below the 10-cluster minimum for confirmatory
  inference.

## Section 14 — Secondary CSI threshold & the honesty gate
- CSI threshold fitting is **secondary**, not the primary RQ1 analysis. Its headline run uses
  daytime rows with the persisted `sample_label == "primary"` (`n_tree_valid >= 3`); the full
  low-count daytime sample, night sample, and pooled-overpass sample are labelled sensitivities.
- **The honesty gate (encoded in code, non-negotiable).** A segmented regression *always*
  returns a breakpoint, even on a straight line or pure noise (proven in the tests). A candidate
  CSI threshold therefore must be well identified, agree with the independent **penalized
  PELT slope-change** diagnostic, show a meaningful bend, and receive mechanism corroboration.
  PELT can select zero breaks; zero or multiple breaks are reported as `none` rather than forced
  into a number. Method agreement uses a tightened 10% CSI-range tolerance. Failing any gate is
  reported as **"no robust threshold detected"**, not converted into a threshold claim.
- `section14_threshold.py` contains the reusable analysis logic; the executed
  `notebooks/14_exploratory_threshold.ipynb` performs IO, figures, and the result note.

## Section 15 — Primary two-dimensional RQ1 response surface
- The primary detector preserves the scientific construct directly: demand on the `vpd_z` axis,
  root-zone-soil-moisture supply on the `sm_z` axis, and mean cooling advantage in each 2-D cell.
  `mean_ndmi_z_tree` is available only as a vegetation-condition check.
- The headline surface is restricted to `is_day == True`, `sample_label == "primary"`, and
  `n_tree_valid >= 3`. The all-overpass surface is retained only as a sensitivity.

## Section 14b / pipeline step 16 — pixel mixed-effects sensitivity
- The per-tree-pixel model uses crossed random intercepts for block group and overpass plus a
  Mundlak within/between decomposition of `vpd_z` and `sm_z`. Because each row is a repeated
  pixel observation, the `_within` terms contain **within-BG spatial and temporal variation**;
  they are never labelled as purely temporal effects.
- Inference resamples whole block groups and independently relabels repeated cluster draws.
  Fewer than 10 independent block groups is pre-declared pilot-only. Phoenix has 9 before the
  primary count floor (and no more after filtering), so **no robust threshold claim is allowed**
  regardless of any point estimate. A denser cross-city sample is required for confirmatory work.
