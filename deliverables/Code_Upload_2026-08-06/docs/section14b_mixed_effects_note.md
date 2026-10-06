# Section 14b - Pixel-level mixed-effects model (B3.2) + BG cluster bootstrap (B3.3)

Unit of analysis: the tree PIXEL (`master_pixel_table.parquet`), one row per finite tree pixel carrying its BG x overpass reference-mean LST.

- Outcome: `cooling_advantage_px` (dT_cool = mean reference LST - tree-pixel LST).
- Primary sample: `is_day == True` (persisted by B4; READ, not re-derived) and `sample_label == "primary"` (`n_tree_valid >= 3`). Low-count rows are sensitivity-only.
- Design: Mundlak / correlated-within-between decomposition of `vpd_z`, `sm_z` into `_within` (within-BG) and `_bg_mean` (between-BG). Because the rows are repeated pixels, `_within` combines within-BG spatial and temporal variation; it is not labelled a purely temporal effect.
- Random effects: crossed random intercepts `(1|block_group) + (1|overpass)` via one constant top-level group and separate variance-component formulas for `C(neighborhood_id)` and `C(overpass_key)`.
- Uncertainty: BG-cluster bootstrap (whole block groups, <=9 clusters) of the CI for `vpd_z_within` and mean `cooling_advantage_px` (B3.3). It is reported only when the clean-fit gate passes; otherwise the CI is suppressed and the failure counts are reported alongside the naive model SE.

**Dominant-BG caveat.** BG `040139412001` contributes 2,969 of 3,300 fitted day-primary pixel-overpass rows (90.0%), so the fixed effect can still be dominated by that neighborhood. MixedLM does not apply the diagnostic inverse-cluster-size weights; dependence is assessed with a leave-dominant-BG-out sensitivity refit and whole-BG bootstrap.

**Crossed-RE fallback.** With ~9 BGs (one dominant) the crossed variance-component fit can hit boundary variance. Documented fallbacks: BG fixed effects + overpass random effect, or GEE with BG clusters. The wild-cluster (Rademacher) bootstrap is the small-cluster alternative to the percentile CI.

## Interpretation status: `exploratory_model_only_threshold_not_identifiable`

- 1 BG × overpass group(s) fell below the complete-case 3-pixel floor after predictor NaNs were removed.
- Only 4 block-group clusters are available; the pre-committed confirmatory minimum is 10.
- Cluster bootstrap status is not_identifiable_too_few_clean_bootstrap_fits (9.4% clean fits).

## Fixed effects (day-only primary) and BG-cluster diagnostics

Fit on 3300 tree pixels across 4 block group(s) and 28 overpass(es); converged=True; clean-fit=True.
After VPD/soil-moisture complete-case filtering, 1 BG × overpass group(s) (2 row(s)) fell below the 3-pixel floor and were excluded.

| term | estimate | model SE |
|------|----------|----------|
| `vpd_z_within` | -0.3905 | 0.6325 |
| `sm_z_within` | -1.4036 | 0.5586 |
| `vpd_z_bg_mean` | 4.8378 | 30.7721 |
| `sm_z_bg_mean` | 2.2424 | 30.4906 |
| `Intercept` | 4.9260 | 8.9594 |

BG-cluster bootstrap (500 resamples over 4 clusters, 95% CI):

- `vpd_z_within` = -0.3905; BG-bootstrap CI **not reported** because the clean-fit fraction failed the predeclared 80% minimum. The 47 surviving refits contained 20 unique coefficient value(s), so their raw percentiles must not be read as precise uncertainty.
- bootstrap status = `not_identifiable_too_few_clean_bootstrap_fits`; valid clean-fit fraction = 9.4%.
- rejected bootstrap fits: 279 for boundary/singular/non-finite fit quality and 174 for rank/level preflight failure or another fit error.
- mean `cooling_advantage_px` = 7.916 K; cluster interval not reported for the same fit-quality reason.

## Variance components

| component | variance (day-only primary) |
|-----------|------------------------------|
| block group `(1|neighborhood_id)` | 20.3572 |
| overpass `(1|overpass_key)` | 10.8258 |
| residual | 8.7655 |

## Dominant-BG in/out sensitivity

| sample | n pixels | n BGs | vpd_z_within | sm_z_within |
|--------|----------|-------|--------------|----------------|
| full (day-only) | 3300 | 4 | -0.3905 | -1.4036 |
| leave-040139412001-out | 331 | 3 | -0.4470 | 0.0691 |

The fixed effect effectively generalizes to the single dominant neighborhood; the leave-out row shows how much the coefficient depends on it.

## Day vs day+night

| sample | n pixels | mean dT_cool (K) | vpd_z_within |
|--------|----------|-------------------|--------------|
| day-only (primary) | 3300 | 7.916 | -0.3905 |
| day+night (pooled sensitivity) | 4385 | 6.322 | 0.3208 |

Day is the primary analysis; the pooled day+night row is a labelled sensitivity only.

