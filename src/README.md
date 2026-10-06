# src/

Python source for the pipeline — one module per protocol section, plus the driver,
utilities, and tests. Importable alongside `config.py`. Every module carries a short
header; the **full rationale for each design choice lives in
[`../docs/DESIGN_DECISIONS.md`](../docs/DESIGN_DECISIONS.md)**, and the step-by-step run
order is in [`../docs/pipeline.md`](../docs/pipeline.md).

Run any section in the `canopy` env, e.g. `python src/section9_harmonize.py`; most accept
`--help`, `--skip-download` (reuse saved raw), `--no-figures`, and `--verify-only`
(re-open the saved output and re-run its assertions, no recompute).

## Driver & utilities
| File | Role |
|---|---|
| `run_all.py` | End-to-end driver: an ordered registry of all 17 steps (0–16) with `--dry-run`, `--from/--to`, `--only`, `--check-deliverables`, `--skip-download`. |
| `check_auth.py` | Smoke-test the four service logins (Earthdata, Earth Engine, CDS, Census). |
| `build_reference_grid.py` | Section 1 — derive/regenerate the frozen 70 m `reference_grid.tif`. |
| `plot_style.py` | Shared figure colours/colormaps so all sections render consistently. |

## Pipeline sections
| File | Section — what it produces |
|---|---|
| `section2_ecostress_lst.py` | 2 — acquire + QC ECOSTRESS LST → LST cube (the 66-overpass master axis). |
| `section3_ecostress_et_esi.py` | 3 — ECOSTRESS ET (PT-JPL) + ESI cubes + overpass links (*supporting evidence only*). |
| `section4_sentinel2_indices.py` | 4 — Sentinel-2 warm-season median NDVI + NDMI on the 70 m grid. |
| `section4b_ndmi_timeseries.py` | 4b — *time-resolved* NDMI (per-overpass + day-of-year LOYO climatology), retained as a vegetation-condition check. |
| `section5_landcover.py` | 5 — NLCD impervious % + land-cover class + USFS canopy %, resampled to 70 m. |
| `section6_era5land_vpd_sm.py` | 6 — ERA5-Land hourly VPD + soil moisture (2018–2024). |
| `section7_precip_drought.py` | 7 — PRISM antecedent precip + tmean, GRIDMET drought, on 70 m. |
| `section8_neighborhood_tree.py` | 8 — ACS income/%POC, CDC SVI, ASU tree inventory, building footprints. |
| `section9_harmonize.py` | 9 — harmonize all layers + time-match to overpasses → `analysis_cube_70m.zarr`. |
| `section10_classify_pixels.py` | 10 — classify tree-dominated & reference pixels; the paired design. |
| `section11_anomalies.py` | 11 — deseasonalized z-scores for VPD, root-zone soil moisture (primary supply), and NDMI (vegetation check). |
| `section12_compound_stress.py` | 12 — the secondary Compound Stress Index (CSI) from VPD demand + root-zone-soil-moisture supply. |
| `section13_master_table.py` | 13 — cooling advantage + BG and pixel analysis tables, including the persisted daytime/count-floor `sample_label`. |
| `section14_threshold.py` | 14 — secondary CSI threshold logic + the honesty gate (driven by the notebook); night/pooled samples are sensitivities. |
| `section15_response_surface.py` | 15 — the primary RQ1 `vpd_z` × `sm_z` response surface, restricted to daytime `sample_label == "primary"` (`n_tree_valid >= 3`). |
| `section14b_mixed_effects.py` | 16 — pixel-level crossed mixed model + whole-block-group cluster bootstrap; within-BG terms combine spatial and temporal variation. |

## Tests
`test_<module>.py` mirrors each section: it stubs the geospatial stack so the module imports
with only numpy + pandas, then exercises that section's algorithmically risky **pure logic** on
tiny synthetic arrays — no network, no data files. Run one directly, e.g.
`conda run -n canopy python src/test_section14_threshold.py`. (pytest is not required.)
