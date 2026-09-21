# Reproducibility and publication boundary

## Network-free checks

From this review directory, with Python 3.11 and the dependencies in `requirements-review.txt`:

```sh
python -m unittest discover -s tests/v6_2_pooled -q
python -m unittest discover -s tests/v6_2_advance -q
python src/v6_2_rebalance/test_sampling_design.py
```

These cover 21 paired estimator/native-grid/scale tests, 3 temporal-resampling tests and 8 sampling-design tests. They use synthetic fixtures and do not require credentials or access to sealed coefficients. Passing them is software/scientific-logic verification, not proof of valid empirical time inference.

## Empirical reruns

Reviewable source code is included under `src/`, preserving the executed model and native-cell code. `run_v6_2_d1d_stage1_precision.py`, `stage1_precision_census.py` and `connectivity_audit.py` are included only because the active runner imports the historical Phoenix building-raster helper; their retired estimator/gates are not the current analysis. The legacy `config.py` is retained to satisfy package imports; its five-city validation does not define this pilot. Read the current pooled runner first.

The original scale runner and `pilot_scale.time_contrast` are preserved for audit. Do not use the old combined resampling/Stage-1 perturbation routine for a final empirical interval. `v6_2_advance/time_resampling.py` provides the tested simpler benchmark, whose broader validation remains pending. Simulation runner scripts retain their historical output/input paths and require the private input tree; use their provided completed synthetic outputs for review.

The portable execution manifests replace machine-specific root paths with `${PROJECT_ROOT}` / `${USER_HOME}` placeholders. They are documentation, not directly runnable frozen manifests. Reconstruct local paths, obtain the documented matching data inputs, use a new run identifier and create a new execution freeze before any authorized rerun. Do not overwrite earlier frozen outputs. No downloader will run merely by opening this package or running the listed tests.

## Provenance

`provenance/publication_sources.json` records source paths, original hashes and copy transformations. `SHA256SUMS` checks the published files. `provenance/local_execution_records/` preserves historical inventories of the larger local workspace, including intentionally unpublished raw/sealed files; those inventories are provenance, not manifests of this GitHub directory. Git commit history supplies the publication revision.

This review intentionally excludes raw LST/emissivity rasters, native outcome tables, sealed model arrays/time contrasts, credentials, local filesystem symlinks, personal correspondence, old Word snapshots and third-party article PDFs. Empirical point estimates previously viewed in conversation are not republished in this precision-review packet. All cited papers are linked to their primary sources.
