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
