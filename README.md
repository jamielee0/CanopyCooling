# Canopy protocol

Project scaffolding for Section 0 of the protocol.

## Layout
- `config.py` — canonical project paths + references to credential locations (no secrets).
- `environment.yml` — conda environment `canopy` (Python 3.11). See header notes on version pins.
- `data/` — `raw/`, `interim/`, `processed/` (all git-ignored) plus `manifest.csv` (tracked).
- `src/` — analysis & utility code, including `check_auth.py`.
- `notebooks/` — exploratory Jupyter notebooks.
- `figures/` — generated figures (git-ignored).
- `docs/` — written documentation and protocol notes.

## Getting started
1. `conda env create -f environment.yml && conda activate canopy`
2. Complete each service login yourself (Earthdata, Earth Engine, CDS, Census).
3. `python src/check_auth.py` — confirm all four services read **PASS** before continuing.

## Pipeline progress
- **Section 1** — fixed domain/CRS/grid/time windows in `config.py` + `reference_grid.tif`.
- **Section 2** — `src/section2_ecostress_lst.py`: ECOSTRESS LST acquisition + QC → `data/interim/ecostress_lst_cube`.
- **Section 3** — `src/section3_ecostress_et_esi.py`: ECOSTRESS evapotranspiration (PT-JPL) and evaporative-stress (ESI) acquisition + QC → `data/interim/ecostress_et_cube`, `ecostress_esi_cube`, and the LST overpass link table `data/interim/overpass_links.parquet`.

  > **ET / ESI are supporting evidence only.** This evapotranspiration product is
  > built for *natural vegetation* and is **unreliable over built-up areas**. It is
  > a mechanism check, never a primary measurement, and its later use is
  > **restricted to high-tree-fraction pixels (Section 10)**. Product identity was
  > confirmed on Earthdata Search: the protocol's example name `ECO_L3T_ET_PT-JPL`
  > does not exist in Collection 2 — PT-JPL ET is the `PTJPLSMinst` layer of
  > `ECO_L3T_JET` v002, and ESI is `ECO_L4T_ESI` v002.
