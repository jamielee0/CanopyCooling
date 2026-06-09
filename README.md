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
