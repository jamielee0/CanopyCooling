# Urban Canopy Thermal Thresholds — Phoenix pilot

**Question.** Do urban trees show a *cooling-advantage threshold* — a level of compound
heat–drought stress beyond which their daytime cooling benefit collapses? This repo is the
**Phoenix pilot** that builds the full data pipeline and produces the first threshold estimate,
as a clean, reproducible base before scaling to multiple cities.

**Answer (pilot).** **No robust threshold detected** — and that is a *valid, honest* outcome,
not a failure. Phoenix supplies fewer than 10 independent paired block groups (9 total, one
dominant), so the threshold analysis is explicitly pilot-only. The primary two-dimensional
demand-by-supply surface and the secondary CSI analysis do not support a defensible threshold;
night and pooled-overpass results are sensitivity checks, not headline estimates. Full reasoning:
[`docs/section14_results_note.md`](docs/section14_results_note.md).

---

## How to review this repo (start here)
1. **[`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md)** — the *why* behind every
   methodological choice, in one place (the single authoritative rationale).
2. **[`docs/pipeline.md`](docs/pipeline.md)** — the step dependency DAG (0→16), each step's
   command and outputs, and how to re-run.
3. **[`src/`](src/README.md)** — the code: one module per pipeline section, each with a short
   header pointing back to the design doc. See [`src/README.md`](src/README.md) for the file index.
4. **Results notes** — [`docs/section11_anomaly_qc_note.md`](docs/section11_anomaly_qc_note.md)
   (anomaly QC) and [`docs/section14_results_note.md`](docs/section14_results_note.md) (the result).
5. **Tests** — each `src/test_section*.py` proves the risky numerics of its section on tiny
   synthetic arrays (no data, no network). Run one with
   `conda run -n canopy python src/test_section12_compound_stress.py`.

## Method in one paragraph
Every input layer is harmonized onto a **fixed 70 m grid** (EPSG:32612) and time-matched to the
**66 ECOSTRESS LST overpasses** of summer 2023 (Section 9). Pixels are classified into
**tree-dominated** and **non-tree built reference** sets, paired within block groups (Section 10).
Atmospheric demand is the VPD anomaly (`vpd_z`); the primary water-supply measure is the
ERA5-Land root-zone soil-moisture anomaly (`sm_z`); time-varying NDMI (`ndmi_z`) is retained as a
vegetation-condition check. The primary RQ1 detector is the Section 15 **two-dimensional
`vpd_z` × `sm_z` response surface**. CSI combines VPD and soil moisture as a secondary scalar
check. The headline sample is daytime only and requires the persisted `sample_label = "primary"`
(`n_tree_valid >= 3`); night and pooled-overpass fits are sensitivities. The pixel model uses
within-block-group terms that contain both spatial and temporal variation, with block-group
cluster inference. With fewer than 10 independent block groups, the project makes **no robust
threshold claim**.

## Layout
| Path | Contents |
|---|---|
| `config.py` | Project paths, the frozen Section-1 geometry, and the named §10–12 thresholds (no secrets). |
| `src/` | One module per pipeline section + the `run_all.py` driver, utilities, and tests. |
| `docs/` | Design rationale, the pipeline guide, and the result notes. |
| `notebooks/` | `14_exploratory_threshold.ipynb` — the executed Section-14 deliverable. |
| `data/` | `raw/`, `interim/`, `processed/` (all git-ignored) + the tracked `manifest.csv`. |
| `figures/` | Generated QC/result figures (git-ignored). |
| `environment.yml` | The conda environment `canopy` (Python 3.11). |

## Setup & run
```bash
conda env create -f environment.yml && conda activate canopy
python src/check_auth.py          # confirm Earthdata / Earth Engine / CDS / Census logins
python src/run_all.py --dry-run   # print the ordered 17-step plan (runs nothing)
```
The download steps (2–8) need configured credentials and pull hours/GB of raw data. The
**processing half (9–16) is network-free** and re-runs from saved interim:
```bash
python src/run_all.py --from 9 --skip-download
```
See [`docs/pipeline.md`](docs/pipeline.md) for the full driver usage, the manual touch-points, and
the deliverable audit (`run_all.py --check-deliverables`).
