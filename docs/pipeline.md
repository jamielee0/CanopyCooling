# Pipeline — end-to-end reproduction (raw download → threshold)

The whole Phoenix pilot reproduces from saved code via the driver
**`src/run_all.py`** (the project's "`make all`" equivalent). This is the
cleanup the protocol requires before scaling to four cities:

> "Verify the entire pipeline runs end to end from saved code with no manual
> intervention … A pipeline that can't be re-run cleanly for Phoenix won't
> survive being extended to four cities."

`run_all.py` holds a declarative registry of the **17 steps (0–16)** in
dependency order; each step records its command, its key output files, whether
it needs network/auth, and whether it has a manual prerequisite. Everything is
run through the project's launcher:

```powershell
& "$env:USERPROFILE\anaconda3\Scripts\conda.exe" run -n canopy python src\run_all.py [flags]
```

## Driver usage

| Command | What it does |
|---|---|
| `run_all.py` | print the ordered plan + a usage hint (does **not** auto-run the multi-hour download pipeline) |
| `run_all.py --dry-run` | print the full ordered plan + the manual/network legend; execute nothing |
| `run_all.py --check-deliverables` | read-only audit: PASS/MISSING table of every step's output files |
| `run_all.py --from N [--to M]` | run a contiguous range of steps (inclusive) |
| `run_all.py --only N[,M,…]` | run just those step ids (overrides `--from/--to`) |
| `run_all.py --skip-download` | forward the download-skip flag to every step that supports it (reuse saved raw/interim) |
| `-v` | debug logging + forward `-v` to each section module |

**Re-run the network-free processing half from saved interim:**

```powershell
& "$env:USERPROFILE\anaconda3\Scripts\conda.exe" run -n canopy python src\run_all.py --from 9 --skip-download
```

## Dependency DAG (0 → 16)

```
 0  check_auth ......... auth smoke test (Earthdata/EE/CDS/Census)
       |  (gates every networked step; not a data dependency of 1)
 1  reference_grid ..... data/processed/reference_grid.tif  (the geometric anchor)
       |__ 2  ECOSTRESS LST cube ............ (Earthdata)   ─┐
       |__ 3  ECOSTRESS ET/ESI + links ...... (Earthdata)    │  steps 2–8 each
       |__ 4  Sentinel-2 NDVI/NDMI .......... (Earth Engine) │  depend ONLY on
       |      4b time-resolved NDMI check ... (Earth Engine) │  run when rebuilding NDMI
       |__ 5  land cover (imperv/canopy/cls)  (Earth Engine) │  the grid (1) and
       |__ 6  ERA5-Land VPD/SM (hourly) ..... (CDS; long Q)   │  are independent
       |__ 7  precip + drought + tmean ...... (PRISM + EE)    │  of one another
       |__ 8  ACS/SVI/tree/footprints ....... (Census/ASU/PC)─┘
 9  harmonize -> analysis_cube_70m.zarr     (reads interim of 2–8; NO network)
       |
10  classify pixels (paired design)         (reads 9 + 8)
       |
11  anomalies / z-scores                    (reads 6 .nc + 9 + saved 4b)
       VPD demand + root-zone-SM supply; NDMI vegetation check; std-floor audit
       |
12  secondary compound stress index (CSI)   (VPD demand + soil-moisture supply)
       |
13  BG master + pixel-level table           (reads 9,10,11,12,8)
       |
14  secondary CSI threshold notebook        (day + persisted count-floor primary)
       |
15  primary VPD_z x SM_z response surface   (reads 13)
       |
16  crossed pixel mixed model + BG bootstrap (reads 13 pixel table)
```

**Sections 9–16 are the network-free, cleanly re-runnable PROCESSING/ANALYSIS half** —
they read only `data/interim/` + `data/processed/` and need no auth. Sections
2–8 require configured credentials and download hours/GB of raw data.

## Step table — command + key outputs

| ID | Step | Command (run via the conda launcher) | Net | Key outputs |
|---:|------|--------------------------------------|:---:|-------------|
| 0 | check_auth | `python src/check_auth.py` | ✔ | *(smoke test — no file)* |
| 1 | reference_grid | `python src/build_reference_grid.py` | – | `data/processed/reference_grid.tif` |
| 2 | ecostress_lst | `python src/section2_ecostress_lst.py` | ✔ | `data/interim/ecostress_lst_cube/`, `…_granule_report.csv` |
| 3 | ecostress_et_esi | `python src/section3_ecostress_et_esi.py` | ✔ | `data/interim/ecostress_{et,esi}_cube/`, `overpass_links.parquet` |
| 4 | sentinel2_indices | `python src/section4_sentinel2_indices.py` | ✔ | `data/interim/s2_{ndvi,ndmi}_warmseason_median_2023_70m.tif` |
| 5 | landcover | `python src/section5_landcover.py` | ✔ | `nlcd_impervious_2021_70m.tif`, `usfs_tcc_canopy_2025_70m.tif`, `nlcd_landcover_class_2021_70m.tif` |
| 6 | era5land_vpd_sm | `python src/section6_era5land_vpd_sm.py` | ✔ | `data/interim/era5land_vpd_sm_hourly_2018_2024.nc` |
| 7 | precip_drought | `python src/section7_precip_drought.py` | ✔ | `prism_antecedent_precip_70m.zarr`, `prism_tmean_70m.zarr`, `gridmet_drought_70m.zarr` |
| 8 | neighborhood_tree | `python src/section8_neighborhood_tree.py` | ✔ | block-group + tree + footprint parquets; `acs_*`, `cdc_svi_*` 70 m tifs |
| 9 | harmonize | `python src/section9_harmonize.py` | – | `data/processed/analysis_cube_70m.zarr`, `analysis_overpass_table.parquet` |
| 10 | classify_pixels | `python src/section10_classify_pixels.py` | – | `section10_pixel_class_70m.tif`, `…_paired_neighborhoods.csv`, `…_threshold_sensitivity.csv`, `…_validation_sample.csv` |
| 11 | anomalies | `python src/section11_anomalies.py` | – | `section11_zscores_70m.zarr`, `…_overpass_summary.parquet`, floor-audit QC note/figures |
| 12 | compound_stress | `python src/section12_compound_stress.py` | – | soil-moisture-supply `section12_csi_70m.zarr`, `…_overpass_summary.parquet` |
| 13 | master_table | `python src/section13_master_table.py` | – | `master_table.parquet`, `master_pixel_table.parquet` with persisted `local_hour`/`is_day`/`sample_label` |
| 14 | exploratory_threshold | `jupyter nbconvert --to notebook --execute --inplace notebooks/14_exploratory_threshold.ipynb` | – | executed secondary-CSI notebook, `docs/section14_results_note.md`, `figures/section14_*.png` |
| 15 | response_surface | `python src/section15_response_surface.py` | – | primary `figures/section15_response_surface_vpdz_smz{,_day}.png` |
| 16 | mixed_effects | `python src/section14b_mixed_effects.py` | – | `docs/section14b_mixed_effects_note.md` (hard failure if the pinned model dependency is absent) |

(The download steps 2–8 accept `--skip-download` to reuse saved raw/interim; the
processing steps accept their documented `--no-figures` / `--verify-only` options; see each
section's `--help`.)

## Manual / not-fully-automatable touch-points (the honest caveats)

Five touch-points are **not** fully scriptable. The driver flags the registered ones in
`--dry-run` / `--check-deliverables`:

1. **(S0) Account logins — one-time, interactive.** `earthaccess`/`~/.netrc`,
   `earthengine authenticate` (+ a Google Cloud project id), `~/.cdsapirc`, and
   (recommended) `CENSUS_API_KEY`. These cannot be created from code;
   `check_auth.py` only **verifies** they are present. Once configured, every
   networked step runs unattended.
2. **(S7) PRISM rate-limit fallback.** PRISM daily files are limited to 2×/IP/day.
   The Section 7 downloader is resumable and **self-heals via the 800 m endpoint**,
   but a hard rate-limit wall may require waiting and re-running S7 the next day —
   the one networked step whose success is not guaranteed in a single unattended
   pass.
3. **(S8) CDC/ATSDR SVI CSV — user-placed.** The SVI is tract-level and the CSV
   is dropped into `data/raw/svi/` by hand (it is not fetched from code). S8 reads
   whatever CSV is there.
4. **Configured credentials for the networked steps (2–8).** Earth Engine, CDS,
   and Census all need a logged-in account / key (a consequence of S0). Everything
   in 9–16 needs no network at all.
5. **(S4b) Rebuilding the NDMI vegetation check.** If Section 4 inputs are rebuilt rather than
   reused, run `python src/section4b_ndmi_timeseries.py` before Section 11. This creates the
   time-resolved NDMI check consumed by the anomaly step; NDMI is not the primary water-supply
   variable and does not enter the primary response surface.

## Verifying reproducibility

- **Audit the deliverables on disk:** `run_all.py --check-deliverables` prints a
  PASS/MISSING table for all 17 registered steps' outputs.
- **Prove the processing half re-runs:** `run_all.py --from 9 --skip-download`
  (no auth, no network) regenerates `analysis_cube_70m.zarr` →
  `section10/11/12` stores → `master_table.parquet` → the Section 14 figures from
  saved interim → the Section 15 primary surface → the Section 16 mixed-model note. Individual
  steps re-run with `--only N`.
- **Logic tests for the driver:** `conda run -n canopy python src/test_run_all.py`
  (pure logic: registry well-formedness, selection logic, manual/network flags,
  command construction — runs nothing, touches no data).
