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
