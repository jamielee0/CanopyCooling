# Advisory review implementation log

Date: 2026-07-17  
Scope: Phoenix pilot remediation, exactly 15 advisory findings (`B1`–`B4`,
`M1`–`M6`, `m1`–`m5`).

## Overall before/after result

Before remediation, the analysis treated vegetation NDMI as water supply, made a
scalar composite the primary detector, pooled day and night, used block-group
means as the inferential unit, admitted weak reference pixels, and left several
QA/date/count assumptions implicit. After remediation, root-zone soil moisture
is the supply construct, a daytime `VPD_z × sm_z` surface is the primary
descriptive detector, pixel-level mixed modeling and whole-block-group
uncertainty are explicit, reference/sample rules are pre-committed, and source
screening/date semantics are fail-closed and auditable.

The resulting scientific conclusion is more conservative: **no robust threshold
was detected in the Phoenix pilot**. The daytime primary CSI sample has 79 rows
from 4 block groups; its candidate breakpoint is 0.324, penalized PELT selects
zero breaks, and the whole-BG interval is 0.002–1.178. The day intercept is
7.13 K versus 1.11 K at night, confirming that pooling diluted the daytime
signal. The pixel model uses 3,300 tree-pixel observations across 4 block groups and 28
overpasses, but its cluster interval is intentionally suppressed because only
9.4% of bootstrap refits passed the clean-fit gate. This is exploratory evidence,
not a confirmatory threshold claim.

Current completion state: all 15 code findings have complete implementation,
production-artifact, and reviewer-log evidence. Minor `m2` includes the finished
static and time-series count products, with a complete 118/118 authenticated
Earth Engine cache and no unavailable count slices. The separate human imagery
validation remains a manual publication gate: its regenerated 60-row sample is
ready, but `genuine_canopy` is blank and no human agreement rate is claimed.

## Execution sequence

1. Corrected the analytical blockers: physical anomaly floors, supply construct
   and primary detector, pixel-level unit of analysis, and daytime-primary scope.
2. Hardened major sampling and input rules: strict references, pre-outcome canopy
   threshold, explicit ECOSTRESS QA, exact PRISM dates, labelled sample floors,
   and drought-band date resolution.
3. Closed minor disclosure/sensitivity/provenance issues; added exact Sentinel-2
   count machinery and completed its resumable production retrieval.
4. Rebuilt the network-free analysis chain and the product-specific cached-data
   outputs where safe; regenerated notes, figures, Parquet/Zarr metadata, and QC
   reports.
5. Ran focused tests throughout, then independently ran every `src/test_*.py`;
   all 17 test files passed.

## Finding log

### B1 — Water-supply construct and primary RQ1 detector

- **Status:** Implemented and verified.
- **Implementation:** Section 12 now defines supply stress as
  `max(-sm_z, 0)` from root-zone soil-moisture anomalies, with documented
  IQR/1.349 robust rescaling; `ndmi_z` is retained only as a vegetation-condition
  check. Section 15 makes the binned daytime `VPD_z × sm_z` response surface the
  primary descriptive RQ1 detector; scalar CSI is secondary.
- **Verification evidence/artifacts:** `src/section12_compound_stress.py`,
  `src/section15_response_surface.py`, their focused tests,
  `data/processed/section12_csi_70m.zarr`, and
  `figures/section15_response_surface_vpdz_smz_day.png`. The saved Section 14
  note states the same construct contract.
- **Residual limitation:** ERA5-Land soil moisture is regional-scale and the
  response surface is descriptive, not an inferential threshold estimate. The
  Phoenix sample remains too sparse for confirmation.

### B2 — Near-zero climatological-standard-deviation floor

- **Status:** Implemented, rebuilt, and audited.
- **Implementation:** Variable-specific physical floors reject finite
  climatological standard deviations at or below 0.05 kPa for VPD, 0.005 m3 m-3
  for soil moisture, and 0.012 for NDMI before division; rejected cells become
  NaN and are counted.
- **Verification evidence/artifacts:** `src/section11_anomalies.py`,
  `src/test_section11_anomalies.py`, `data/processed/section11_zscores_70m.zarr`,
  and `docs/section11_anomaly_qc_note.md`. The audit records 0/5,280 VPD cells,
  214/5,280 SM cells (4.0530%), and 732,049/102,071,970 NDMI cells (0.7172%)
  floored.
- **Residual limitation:** Flooring intentionally reduces complete cases. The
  surviving 2023 `sm_z` standard deviation of about 0.457 is a real single-year
  property, not forced to one upstream.

### B3 — Unit of analysis, pseudoreplication, and clustered uncertainty

- **Status:** Implemented; inference correctly reported as non-identifiable.
- **Implementation:** Section 13 persists one paired row per finite tree pixel,
  carrying its block-group-by-overpass reference mean. Section 14b fits a
  crossed block-group/overpass random-intercept model with a Mundlak
  within/between decomposition and resamples whole block groups for uncertainty.
  Low-count rows remain available but are not primary.
- **Verification evidence/artifacts:** `data/processed/master_pixel_table.parquet`,
  `src/section13_master_table.py`, `src/section14b_mixed_effects.py`, both focused
  tests, and `docs/section14b_mixed_effects_note.md`. The primary fit contains
  3,300 pixel observations, 4 BGs, and 28 overpasses; the clean bootstrap fraction is 9.4%,
  so the CI is suppressed rather than over-interpreted.
- **Residual limitation:** The dominant BG contributes 2,969/3,300 fitted
  day-primary pixel-overpass rows (90.0%), and only four primary clusters survive.
  The mixed model is exploratory; the leave-dominant-BG-out sensitivity changes
  coefficients materially.

### B4 — Day/night pooling

- **Status:** Implemented, propagated, and reported.
- **Implementation:** Section 13 is the single source of truth for Phoenix local
  time (`UTC-7`, no DST) and persists `local_hour` plus `is_day` to both master
  tables. Sections 14, 15, and 14b read those fields; daytime is primary while
  night and pooled estimates are labelled sensitivities.
- **Verification evidence/artifacts:** `src/section13_master_table.py`,
  `src/section14_threshold.py`, `src/section15_response_surface.py`,
  `src/section14b_mixed_effects.py`, focused day/night tests, and
  `docs/section14_results_note.md`. The fitted intercept is 7.13 K by day and
  1.11 K at night, a 6.02 K contrast.
- **Residual limitation:** The 07:00–19:00 rule is a predeclared Phoenix heuristic.
  Scaling to DST-observing cities requires timezone-aware logic and may justify
  a solar-time sensitivity.

### M1 — Reference-set restriction

- **Status:** Implemented, rebuilt, and verified.
- **Implementation:** References must have canopy below 20%, impervious cover
  above 20%, NLCD class 22/23/24, sufficient LST observations, and a paired tree
  pixel in the same BG. NLCD 21 and missing canopy/impervious values fail.
- **Verification evidence/artifacts:** `src/section10_classify_pixels.py`,
  `src/test_section10_classify_pixels.py`,
  `data/processed/section10_pixel_class_70m.tif`, and
  `data/processed/section10_paired_neighborhoods.csv`. The stored-input rebuild
  yields 1,457 strict reference pixels while retaining 206 tree pixels and all
  9 paired BGs. A final audit also found and corrected a validation-only sampling
  mismatch: the regenerated 60-row review CSV now draws exclusively from saved
  class-1 pixels (60/60 verified), rather than admitting seven pre-pairing
  candidates.
- **Residual limitation:** Nine paired BGs remain a thin design, and the stricter
  comparator definition materially reduces reference support.

### M2 — Pre-committed canopy threshold

- **Status:** Implemented, rebuilt, and verified.
- **Implementation:** The operating threshold is chosen without outcomes or BG
  yield as `max(P90 canopy among finite, building-excluded NDVI>0.5 pixels,
  40%)`. The preregistered 70% value is retained separately, and sensitivity
  rows no longer select the operating point.
- **Verification evidence/artifacts:** `config.py`,
  `src/section10_classify_pixels.py`, its invariance tests,
  `data/processed/section10_threshold_sensitivity.csv`, and
  `docs/DESIGN_DECISIONS.md`. The eligible pool is 35,850 pixels; raw P90 is
  8.143%, so the physical 40% floor binds, yielding 206 tree pixels and 9 paired
  BGs.
- **Residual limitation:** The binding 40% floor is a scientific policy choice,
  not a Phoenix outcome optimum; alternate percentiles/floors remain labelled
  sensitivity analyses.

### M3 — ECOSTRESS LST mandatory-QA interpretation

- **Status:** Implemented, rebuilt, and audited under the professor-approved coverage policy.
- **Implementation:** Bits 0–1 are decoded explicitly. Mandatory-QA `00` and `01`
  enter the primary cube; `10` and `11` remain excluded. Class `01` is not
  relabelled as best quality: its potentially degraded status and the professor's
  data-coverage decision are stored in cube metadata. Finite-LST, clear-cloud,
  and land-only gates still apply. A parallel `00`-only mask records the exact
  contribution of `01` per tile.
- **Verification evidence/artifacts:** `src/section2_ecostress_lst.py` and
  `src/test_section2_ecostress_lst.py`, including synthetic `00/01/10/11` and
  clear-land polarity checks; `data/interim/ecostress_lst_granule_report.csv`;
  and `docs/section2_qc01_coverage_audit.md`. The rebuild added 5,122,900 valid
  pixels (+4.78% versus `00` only), recovered one tile, and left the time axis at
  66 overpasses. Downstream counts increased from 195 to 206 tree pixels and
  from 1,453 to 1,457 reference pixels, with all 9 paired BGs retained.
- **Residual limitation:** Class `01` may be degraded, and this pipeline still
  does not ingest the associated error-estimate band. Results therefore represent
  the professor-approved coverage tradeoff, not a claim that `01` equals `00` quality.

### M4 — Exact PRISM date matching

- **Status:** Implemented and verified.
- **Implementation:** PRISM precipitation and temperature now require a unique
  exact calendar-date match. A missing date returns an all-NaN aligned grid and
  is counted/logged; duplicate dates raise. Nearest-date borrowing is removed.
- **Verification evidence/artifacts:** `src/section9_harmonize.py`,
  `src/test_section9_harmonize.py`, and
  `data/processed/analysis_cube_70m.zarr`. The cached 66-overpass inventory has
  exact PRISM coverage; tests prove that an absent date remains NaN rather than
  borrowing a neighbor.
- **Residual limitation:** Future source gaps will reduce usable observations;
  there is deliberately no silent imputation policy.

### M5 — Well-sampled primary subset

- **Status:** Implemented, persisted, and used downstream.
- **Implementation:** `sample_label` is stored without deleting rows. Primary
  analyses require `n_tree_valid >= 3`; the full `>=1` pool and stricter floor
  are explicitly labelled sensitivities. Section 14b additionally reapplies the
  floor after complete-case predictor filtering.
- **Verification evidence/artifacts:** `src/section13_master_table.py`,
  `src/section14_threshold.py`, `src/section14b_mixed_effects.py`, focused tests,
  both master Parquets, and `docs/section14_results_note.md`. The daytime primary
  CSI sample is 79 rows/4 BGs versus the full sensitivity's 175 rows/9 BGs.
- **Residual limitation:** The safeguard improves unit quality but exposes the
  binding sample-size problem; it cannot create independent neighborhoods.

### M6 — Drought-band date resolution

- **Status:** Implemented and verified on the cached inventory.
- **Implementation:** Acquisition captures each image's `system:time_start` and
  carries resolved dates beside downloaded bands. Positional/undated band names
  use that metadata; name/metadata mismatches, duplicates, invalid dates, or
  missing dates raise instead of being assigned by order.
- **Verification evidence/artifacts:** `src/section7_precip_drought.py`,
  `src/test_section7_precip_drought.py`, and `gridmet_drought_70m.zarr`. All 1,476
  cached raw drought bands passed date validation. Harmonization leaves the first
  three pilot overpasses NaN because no warm-season pentad contains their dates.
- **Residual limitation:** New undated downloads depend on Earth Engine metadata
  retrieval; absent metadata is a hard failure by design.

### m1 — ET/ESI screening disclosure and ESI range

- **Status:** Implemented, rebuilt offline, and documented.
- **Implementation:** Long names no longer claim generic quality control. The
  exact mask is `isfinite(value) AND cloud == 0 AND water == 0`; no retrieval-QA
  filter is claimed. ESI's advisory range is 0–1, flag-only with no clipping;
  ETinstUncertainty is persisted as unused ensemble spread, not a QA bit. The
  product role is `corroboration-only`.
- **Verification evidence/artifacts:** `src/section3_ecostress_et_esi.py`, its
  focused test, both rebuilt Zarr cubes, and
  `docs/section3_et_esi_qc_note.md`. Rebuilds used 356 ET and 356 ESI tiles,
  produced 45-overpass cubes, and retained 36,048,216 finite cells per variable;
  ESI has zero cells outside 0–1.
- **Residual limitation:** No retrieval-quality QA band is available in this
  pipeline. Rebuilt arrays were numerically equivalent but not byte-identical;
  extrema differed by at most 1.62e-11.

### m2 — Sentinel-2 cloud gate and exact valid-scene counts

- **Status:** Implemented, production-built, and verified.
- **Implementation:** The `<60%` scene-cloud threshold remains a broad request
  prefilter, while per-pixel SCL masking is primary. Sections 4/4b now compute
  exact post-mask integer counts, nearest-neighbor 70 m summaries, separate `<3`
  flags, and resumable count-only retrieval. Count flags are diagnostic and never
  mask NDVI/NDMI; `-1` alone denotes an unavailable time-series count.
- **Verification evidence/artifacts:** `src/section4_sentinel2_indices.py`,
  `src/section4b_ndmi_timeseries.py`, both focused tests, and
  `docs/section4_scene_coverage_note.md`. The static collection had 201 scenes
  before and 182 after the broad prefilter. Both static 70 m products have a
  count range of 0–169 and median 41; 2,493/1,546,545 cells (0.161%) are flagged
  below three. The completed 118-file time-series cache produces observed-window
  counts of 1/9/52 (min/median/max), with 9,240/102,071,970 cells (0.009%) below
  three, and LOYO-climatology counts of 0/55/288, with 3,093,090/102,071,970 cells
  (3.030%) below three. Both count variables have zero unavailable (`-1`) cells.
  The final cube is `data/interim/s2_ndmi_timeseries_70m.zarr`; static count and
  flag rasters are in `data/interim/`, and all 118 raw count GeoTIFFs have unique,
  checksum-matching manifest rows.
- **Residual limitation:** Counts measure usable post-SCL observations, not
  retrieval quality. The `<3` flag exposes thin support but intentionally does
  not change the continuous NDVI/NDMI values or the primary analysis mask.

### m3 — Unequal CSI-weight sensitivity

- **Status:** Implemented, executed, and reported.
- **Implementation:** Five predeclared convex demand/supply weight pairs run on
  the identical daytime-primary rows, common finite mask, BG clusters, and
  honesty gate. The 0.5/0.5 scenario must exactly reproduce the saved baseline.
- **Verification evidence/artifacts:** `src/section12_compound_stress.py`,
  `src/section14_threshold.py`, their focused tests,
  `data/processed/section12_weight_sensitivity.parquet`,
  `data/processed/section14_csi_weight_sensitivity.csv`, and the table in
  `docs/section14_results_note.md`. All five scenarios return “no robust threshold
  detected.”
- **Residual limitation:** Weight robustness does not overcome the four-BG
  primary sample or make CSI the primary detector.

### m4 — ACS/TIGER vintage pinning and desynchronization guard

- **Status:** Implemented, rebuilt from cached raw files, and provenance-audited.
- **Implementation:** ACS5 and TIGER/Line are pinned to matching 2024 vintages;
  URLs/filenames are built from the requested year at call time, mismatches are
  rejected, vintage fields are stored in Parquet, and exact source/checksum
  provenance is written without credentials.
- **Verification evidence/artifacts:** `src/section8_neighborhood_tree.py`,
  `src/test_section8_neighborhood_tree.py`,
  `data/interim/section8_vintage_provenance.json`, and
  `docs/section8_vintage_note.md`. Two cached rebuilds of 2,806 block groups
  produced identical current hashes and zero changed cells between those runs.
- **Residual limitation:** Current stable rasters are not byte/value-identical to
  pre-remediation artifacts; downstream products must be rebuilt or explicitly
  compared. The fixed 2024 vintage is reproducible, not perpetually current.

### m5 — Penalized changepoint, agreement tolerance, and cluster bootstrap

- **Status:** Implemented, executed, and incorporated into the honesty gate.
- **Implementation:** Penalized PELT may return zero breaks; a candidate is no
  longer fabricated when none is supported. Method agreement is tightened to
  10% of the CSI range, and breakpoint uncertainty resamples whole BGs while
  retaining the unchanged IID path when groups are absent.
- **Verification evidence/artifacts:** `src/section14_threshold.py`,
  `src/test_section14_threshold.py`, `docs/section14_results_note.md`, and
  Section 14 figures. PELT selected zero breaks for the primary and all reported
  sensitivity samples; focused tests cover flat/no-break data, whole-cluster
  draws, wider clustered intervals, and agreement/disagreement boundaries.
- **Residual limitation:** With only four primary BGs, bootstrap intervals remain
  broad and breakpoint power is low. “No robust threshold detected” means the
  data do not identify one; it does not prove that no physiological threshold
  exists.

## Reviewer verification summary

- All 17 standalone `src/test_*.py` files passed with
  `/Users/jmlee/miniforge3/envs/urbanv2/bin/python`; no test failure was hidden by
  an aggregate runner.
- The 17-step pipeline registry is contiguous (`0`–`16`) and records the primary
  response surface and pixel mixed model as separate outputs.
- Production notes preserve adverse evidence: four primary BGs, one dominant BG,
  suppressed mixed-model cluster CI, strict missing-date NaNs, the m2 production
  retrieval dependency, and non-byte-identical rebuilds are not presented as
  successes.
- Publication gate still open: the regenerated 60-row visual-validation sample
  has a 58/60 (96.7%) automated cross-check, but `genuine_canopy` remains blank;
  that automated figure is not reported as human agreement.
