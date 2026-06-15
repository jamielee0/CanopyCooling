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
