# Current amendment status

The 19 September 2026 entry at the end of this file supersedes conflicting earlier design instructions. Earlier entries are preserved as historical records; their numerical results have not been recomputed. Version 6.2 remains active.

# v6.2 decision log

Use one entry for every proposed change to a frozen rule. A change is not effective
until its entry is complete and the named supervisor has approved it. No rule may be
changed after the corresponding v6.2 coefficient has been viewed.

## Entry 1 — control-boundary freeze

- **Decision ID:** V6.2-D001
- **Recorded:** 2026-08-30T17:58:40+09:00
- **Status:** FROZEN; SUPERVISOR REVIEW PENDING
- **Change:** Establish v6.2 as the controlling design, preserve the last inherited
  commit under annotated tag `v2-inherited-pre-v6.2`, and freeze the product,
  population, timing, geometry, model, sign, power, and gate rules in
  `protocol_v6_2.yml` before any new v6.2 coefficient is viewed.
- **Reason:** The compound-threshold, paired-pixel, and early-versus-late designs failed
  outcome-free feasibility checks. The replacement estimand is a block-pass canopy–LST
  slope modified by separately constructed antecedent `G`, `W_tree`, and `W_bg`.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** yes; disclosed in `prior_thermal_access.md`
- **Files changed:** `docs/v2/v6_2/**`, `docs/v2/archive/pre_v6_2_20260830/**`,
  `outputs/v6_2/**`, `tests/fixtures/synthetic_demo/**`, and v6.2 boundary utilities
- **Gate affected:** free checks
- **Approved by:** PENDING_SUPERVISOR_REVIEW

### Frozen implementation rulings made at D001

- Science TCC is the raw USFS/USGS Product Version 2025-6, stored as fraction 0–1
  for analysis; 2019–2025 stable-cell median is primary.
- Provisional population thresholds are `tree >= 0.40` and `background <= 0.10`;
  the open interval `(0.10, 0.40)` is excluded as mixed.
- The primary background is low-canopy, low-impervious, pervious low vegetation;
  impervious/bare is a placebo, not the primary comparator.
- The primary geometry is native ECOSTRESS MGRS with 1 km blocks and pass-level p95
  absolute view zenith at or below 15 degrees. The predeclared expansion is 25
  degrees only where view azimuth is available.
- Phoenix's provisional primary season is 15 May–10 July; Los Angeles's is 1
  June–30 September. The opposite window is the predeclared sensitivity in each city.
- The Stage 1 implementation must contain `C(block):canopy_c` and emit one slope per
  block-pass. Cooling efficiency is `CE = -0.10 * slope` when canopy is a 0–1 fraction.
- Stage 2 jointly includes `G`, `W_tree`, and `W_bg` with block and pass fixed effects.
  The demand branch is explicitly pending the free-check ruling.
- Expected signs are scientific predictions, never inclusion or progression gates.

## Entry 2 — prospective demand–geometry decision rule

- **Decision ID:** V6.2-D002
- **Recorded:** 2026-08-30T22:14:19+09:00
- **Status:** FROZEN FOR OUTCOME-BLIND RUN; SUPERVISOR REVIEW PENDING
- **Change:** Freeze the numerical keep/drop rule for the optional Stage 2 VPD
  interaction branch before computing support diagnostics. Both Gate A cities must
  pass the complete candidate design at the preauthorized 25-degree geometry set:
  at least 30 complete passes, VPD VIF at most 5, maximum condition index at most
  30, leave-one-pass-out nonlinear VPD concurvity R-squared at most 0.80, residual
  VPD standard deviation at least 0.25 kPa, and a continuously supported VPD width
  of at least 0.50 kPa. Missing air temperature, actual vapour pressure/dewpoint,
  solar time, zenith/azimuth, view zenith/azimuth, relative sun–sensor azimuth, or
  day of year fails closed. The 15-degree set is a reported sensitivity. Pairwise
  correlations are descriptive and nonbinding.
- **Reason:** The proposal requires deciding whether demand variation is separable
  from temperature, humidity, season, solar geometry, and viewing geometry before
  any new coefficient is viewed. Requiring both cities to pass the widest
  preauthorized view set gives the demand branch its most favorable admissible
  support test without relaxing the geometry requirement.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** yes; disclosed, not accessed for this check
- **Files changed:** `docs/v2/v6_2/protocol_v6_2.yml`,
  `docs/v2/v6_2/decision_log_v6_2.md`, and the D1a audit package
- **Gate affected:** free checks
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR_REVIEW

### Frozen implementation details for D002

- The support evidence is historical, pass-level, nonthermal provenance and is not
  declared to be the new v6.2 study sample.
- Exact-time HRRR temperature and dewpoint are linearly interpolated between the
  inherited bracketing-hour summaries. Actual vapour pressure is computed from the
  interpolated dewpoint; VPD remains in kPa.
- Continuous support is the intersection of the within-tertile VPD 10th-to-90th
  percentile ranges for local solar time, solar zenith, and day of year.
- Nonlinear concurvity is out-of-sample R-squared from leave-one-pass-out prediction
  of VPD using four-knot cubic spline terms for continuous nuisance variables,
  sine/cosine circular terms, and ridge penalty 1.0.
- If either city fails any binding criterion, both `W_tree x VPD` and `W_bg x VPD`
  are dropped together, RQ2 is removed, and the branch may not be restored after a
  new v6.2 coefficient is viewed.

## Entry 3 — demand–geometry result and branch ruling

- **Decision ID:** V6.2-D003
- **Recorded:** 2026-08-30T22:31:24+09:00
- **Status:** DROP RULING RECORDED; SUPERVISOR REVIEW PENDING
- **Change:** Apply the prospectively frozen D002 rule and drop both VPD
  interactions. Remove RQ2 and all high-demand contrasts; later Stage 2 work is
  restricted to average daytime effects.
- **Reason:** At the binding 25-degree set, Phoenix has 0 complete candidate-design
  passes out of 44 quality-and-weather-complete passes, and Los Angeles has 0 out of
  48. View azimuth and relative sun–sensor azimuth are unavailable and were not
  imputed. The full VIF, condition-index, concurvity, and residual-variation
  diagnostics are therefore not estimable and fail closed.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** yes; disclosed, not accessed for this check
- **Files changed:** `docs/v2/v6_2/protocol_v6_2.yml`,
  `docs/v2/v6_2/decision_log_v6_2.md`, D1a audit code/tests, and
  `deliverables/D1a_demand_geometry_v6_2_20260830/**`
- **Gate affected:** free checks
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR_REVIEW

### Numerical basis for D003

- The optimistic reduced design omitting unavailable view and relative azimuth is
  reported as nonbinding. Phoenix: VIF 85.0515, maximum condition index 37.0887,
  leave-one-pass-out nonlinear VPD concurvity R-squared 0.965691, residual VPD SD
  0.307653 kPa, and common-support width 2.52152 kPa. Los Angeles: VIF 72.5667,
  maximum condition index 47.8013, nonlinear concurvity R-squared 0.986707,
  residual VPD SD 0.100169 kPa, and common-support width 0.00000 kPa.
- Thus even the reduced check exceeds the VIF, condition-index, and nonlinear
  concurvity ceilings in both cities. Los Angeles additionally misses the residual
  VPD SD and common-support floors.
- Descriptively, VPD–air-temperature Pearson correlations are 0.9484 in Phoenix and
  0.9532 in Los Angeles. Pairwise correlations did not determine the ruling.
- The identifying variation would have been within-city, cross-pass VPD variation
  remaining after temperature, vapour pressure/dewpoint, solar time, solar
  zenith/azimuth, view geometry, and day-of-year adjustment inside shared support.
  That independent variation was not demonstrated.
- No ECOSTRESS LST value and no new v6.2 coefficient was opened. The demand branch
  may not be restored after later coefficient access.

## Entry 4 — parsimonious demand–geometry sensitivity rule

- **Decision ID:** V6.2-D004
- **Recorded:** 2026-08-30T23:05:49+09:00
- **Status:** FROZEN NON-BINDING SENSITIVITY; SUPERVISOR REVIEW PENDING
- **Change:** At the user's request, run a less restrictive, outcome-blind support
  sensitivity without changing the controlling D003 drop. Restrict to the primary
  15-degree near-nadir set; do not require view or relative azimuth completeness;
  adjust VPD for solar zenith, view zenith, and cyclic day of year. Report separate
  temperature-only and actual-vapour-pressure-only additions as non-vetoing
  sensitivities rather than jointly controlling for both mathematical ingredients
  of VPD.
- **Reason:** VPD is derived from temperature and vapour pressure, so requiring VPD
  to be independent of both simultaneously is an overcontrol test. Local solar time,
  solar zenith/azimuth, and day of year also contain redundant geometry information.
  The sensitivity asks whether VPD has usable cross-pass variation after a
  parsimonious time, season, and near-nadir viewing adjustment.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** yes; disclosed, not accessed
- **Files changed:** D1a sensitivity audit code/tests and
  `deliverables/D1a_parsimonious_sensitivity_v6_2_20260830/**`
- **Gate affected:** none; non-binding sensitivity only
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR_REVIEW

### Prospective numerical rule for D004

- Each city must have at least 15 complete primary-set passes.
- In the primary nuisance design, VPD VIF must be at most 5, maximum condition index
  at most 30, leave-one-pass-out nonlinear concurvity R-squared at most 0.80,
  residual VPD SD at least 0.25 kPa, and common VPD support width at least 0.50 kPa.
- The nonlinear basis is additive linear and quadratic terms for solar zenith and
  view zenith plus sine/cosine day of year, with ridge penalty 1.0 and
  leave-one-pass-out predictions.
- Common support is the intersection of within-tertile VPD 10th-to-90th percentile
  ranges across solar zenith and day of year.
- All primary criteria must pass in both cities for a sensitivity `KEEP`. The
  temperature-only and vapour-pressure-only additions are interpretation checks and
  do not veto the primary result.
- This sensitivity cannot replace D003 without a supervisor-approved protocol
  amendment made before any new coefficient is viewed.

## Entry 5 — parsimonious demand–geometry sensitivity result

- **Decision ID:** V6.2-D005
- **Recorded:** 2026-08-30T23:08:40+09:00
- **Status:** NON-BINDING SENSITIVITY DROP; SUPERVISOR REVIEW PENDING
- **Change:** Record the D004 sensitivity result without changing D003. The
  parsimonious cross-city sensitivity remains `DROP`, but it is a near-pass rather
  than a structural non-estimability result.
- **Reason:** Phoenix passes every primary sensitivity criterion. Los Angeles passes
  the count, VIF, condition-index, nonlinear-concurvity, and residual-variation
  criteria but has only 0.300 kPa of common VPD support versus the prospectively
  frozen 0.500 kPa floor.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** yes; disclosed, not accessed
- **Files changed:** `docs/v2/v6_2/protocol_v6_2.yml`,
  `docs/v2/v6_2/decision_log_v6_2.md`, sensitivity code/tests, and
  `deliverables/D1a_parsimonious_sensitivity_v6_2_20260830/**`
- **Gate affected:** none; non-binding sensitivity only
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR_REVIEW

### Numerical basis for D005

- Phoenix primary parsimonious design (`n=19`): VIF 1.036, maximum condition index
  5.105, leave-one-pass-out nonlinear R-squared -0.582, residual VPD SD 2.289 kPa,
  and common-support width 2.417 kPa. All criteria pass.
- Los Angeles primary parsimonious design (`n=27`): VIF 2.086, maximum condition
  index 3.901, nonlinear R-squared 0.290, residual VPD SD 0.816 kPa, and
  common-support width 0.300 kPa. Only the 0.500-kPa support-width criterion fails.
- Adding air temperature alone produces VIF 48.323 and nonlinear R-squared 0.938 in
  Phoenix, and VIF 14.091 and nonlinear R-squared 0.884 in Los Angeles. This confirms
  that temperature and VPD are strongly overlapping descriptions of demand.
- Adding actual vapour pressure alone is less problematic: VIF 7.139 and nonlinear
  R-squared 0.671 in Phoenix; VIF 2.426 and nonlinear R-squared 0.317 in Los Angeles.
  These checks are interpretive and did not veto the primary design.
- The 0.500-kPa support floor was not changed after observing the Los Angeles result.
  No ECOSTRESS LST value and no new v6.2 coefficient was opened.

## Entry 6 — prospective block–pass connectivity rule

- **Decision ID:** V6.2-D006
- **Recorded:** 2026-08-30T23:23:36+09:00
- **Status:** FROZEN FOR OUTCOME-BLIND RUN; SUPERVISOR REVIEW PENDING
- **Change:** Freeze the D1b block–pass incidence construction and numerical ruling
  before computing any connectivity result. Report all eight city × season-window ×
  view-set combinations. Use a fixed 1 km local-UTM grid, retain blocks whose
  centroids lie inside the 2020 Census urban area, and create a block–pass edge only
  when at least 60 clear native 70 m cells remain after canonical MGRS partitioning.
- **Reason:** Sixty clear cells are a necessary but not sufficient upper-bound screen
  for the disjoint planning floors of 30 tree and 30 background cells. The later
  Science TCC, fixed-background, canopy-span, and optical checks can remove edges but
  cannot create support absent from this graph. The rule therefore provides a cheap,
  nonthermal stop check without pretending to be the v6.2 study sample.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** no; quality layers and metadata only
- **Files changed:** `docs/v2/v6_2/protocol_v6_2.yml`,
  `docs/v2/v6_2/decision_log_v6_2.md`, and the D1b audit package
- **Gate affected:** free checks
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR_REVIEW

### Frozen implementation details for D006

- The evidence population is the inherited Collection 2 quality/geometry archive for
  2019–2025, restricted to quality-and-weather-complete passes. It is explicitly a
  historical feasibility proxy, not the new v6.2 Collection 3 sample.
- Census urban-area geometry is repaired deterministically with Shapely `make_valid`
  only when the source multipolygon is topology-invalid, before projection and
  rasterization; the repair does not change any eligibility threshold.
- Season membership uses local-solar acquisition date. View sets use the pass-level
  p95 absolute L1B view-zenith statistic at 15 and 25 degrees.
- The 25-degree set is the single pre-authorised incidence widening. Missing view
  azimuth does not fabricate an incidence edge, and the memo must state that the set
  is not fully geometry-admissible until azimuth is resolved.
- The incidence graph is bipartite. Largest-component share is the share of eligible
  block–pass edges in the largest component. The passes-per-block floor is eight;
  the 10th percentile uses the linear quantile convention.
- Spatial sectors are the four projected quadrants around the Census urban-area
  centroid. Land-use dominance is the largest share of eligible block–pass edges
  assigned to one modal 2024 Annual NLCD Collection 1.1 class.
- A combination passes only with at least 30 eligible blocks, at least three sectors,
  largest-component share at least 0.80, and median passes per block at least eight.
  The free check supports further planning if any city-window combination passes at
  15 degrees or after the one 25-degree widening. It does not authorise Gate A.

## Entry 7 — block–pass connectivity result

- **Decision ID:** V6.2-D007
- **Recorded:** 2026-08-30T23:42:49+09:00
- **Status:** READY FOR D1B REVIEW; SUPERVISOR REVIEW PENDING
- **Change:** Record the outcome-blind D006 connectivity result. The inherited
  historical incidence proxy supports further connectivity planning at 15 degrees;
  the single preauthorised 25-degree widening was not used for the ruling.
- **Reason:** Six of eight required combinations pass. Phoenix sensitivity at 15
  degrees has 2,870 eligible blocks, 15 eligible passes, 39,887 block-passes, median
  and p10 of 14 passes per block, zero blocks below the eight-pass floor, four
  sectors, and largest-component share 1.000. Los Angeles primary at 15 degrees has
  4,286 blocks, 25 passes, 95,544 block-passes, median 22, p10 21, zero blocks below
  the floor, four sectors, and largest-component share 1.000.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** no; quality and view-geometry layers only
- **Files changed:** `docs/v2/v6_2/protocol_v6_2.yml`,
  `docs/v2/v6_2/decision_log_v6_2.md`, D1b audit code/tests, and
  `deliverables/D1b_connectivity_v6_2_20260830/**`
- **Gate affected:** free checks only; Gate A remains unauthorised
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR_REVIEW

### Numerical basis and interpretation for D007

- Phoenix primary at 15 degrees fails because only five eligible passes exist; all
  2,870 eligible blocks are below the eight-pass floor. It passes at 25 degrees with
  13 passes, median 12, p10 11, and zero blocks below the floor.
- Los Angeles sensitivity at 15 degrees fails because median passes per block is six
  (p10 five); all 4,286 eligible blocks are below the floor. It passes at 25 degrees
  with 15 eligible passes, median 12, p10 11, and zero blocks below the floor.
- Every panel has all four projected urban sectors and largest-component share 1.000.
  Developed, Medium Intensity is the largest modal Annual NLCD class in each panel,
  with 60.1% to 64.8% of eligible edges. The maps show broad urban-area coverage,
  not an airport, desert-fringe, or single-park island.
- The inherited five-city archive begins June 1. Phoenix primary and Los Angeles
  sensitivity are therefore June 1–July 10 lower bounds for their nominal May
  15–July 10 windows. The two panels supporting the 15-degree ruling—Phoenix
  sensitivity and Los Angeles primary—use the complete June–September census.
- Evidence remains a Collection 2 historical feasibility proxy. The 60-clear-cell
  edge is an optimistic necessary condition; later Science TCC, fixed-background,
  canopy-span, and optical checks may only remove support. No LST value or new v6.2
  coefficient was opened, and Gate A was not authorised.

## Entry 8 — D1a five-field geometry recovery and reassessment

- **Decision ID:** V6.2-D008
- **Recorded:** 2026-09-01T22:16:36+09:00
- **Status:** RECOVERY COMPLETE; D003 DROP UNCHANGED; SUPERVISOR REVIEW PENDING
- **Change:** Repair the D1a provenance wiring by range-reading the five permitted
  nonthermal `ECO_L1B_GEO.002` geometry arrays for the exact frozen 92-pass
  population, calculate pass-level view and relative azimuth only when every mapped
  view-valid cell has valid source azimuth, and rerun the original numerical rule in
  a separate reassessment package. Preserve the original D003 record.
- **Reason:** The original D1a loader inherited a table that marked azimuth
  unavailable without performing the later five-field source read. All 92 pass
  identities and 139 exact source scenes were processed. Source azimuth arrays are
  fully populated for only 4/44 Phoenix passes and 1/48 Los Angeles passes; 31 passes
  are partially populated and 56 have zero valid azimuth over the mapped domain.
  Partial arrays were preserved as provenance but neither imputed nor promoted to
  full-design completeness. Both cities remain below the frozen 30-pass floor, so
  the reassessed ruling is DROP and D003 is unchanged.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** no; geometry-only retrieval
- **Files changed:** geometry-recovery runner and evidence, D1a loader/tests,
  `docs/v2/v6_2/protocol_v6_2.yml`, this decision log, and
  `deliverables/D1a_geometry_recovery_reassessment_v6_2_20260901/**`
- **Gate affected:** free checks only; no gate is opened
- **Approved by:** USER-DIRECTED GEOMETRY RECOVERY; PENDING_SUPERVISOR_REVIEW

## Entry 9 — prospective lead-lag feasibility rule

- **Decision ID:** V6.2-D009
- **Recorded:** 2026-09-02T00:29:48+09:00
- **Status:** FROZEN FOR COUNT-ONLY OUTCOME-BLIND RUN; SUPERVISOR REVIEW PENDING
- **Change:** Freeze the D1c feasibility count before calculating the inherited
  centered-product result. Report the full Phoenix/Los Angeles, 2019-2025, two-window,
  HLSL30/HLSS30 grid. Use the inherited D1b 15-degree quality-and-weather-complete
  historical pass census only as the denominator. A verified pair requires distinct,
  sensor-specific acquisition identifiers and source dates, one at least 24 hours
  before and one after the thermal pass, each 1-15 days away, with absolute lags
  differing by no more than three days.
- **Reason:** Pixel-level counts from a centered optical composite can show that at
  least two observations contributed, but they cannot prove that one fell on each
  side of a pass, establish comparable lags, identify sensors, or quantify acquisition
  reuse. Missing dates or identifiers therefore fails closed rather than converting a
  count proxy into a temporal-specificity test.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** no; metadata and optical counts only
- **Files changed:** `docs/v2/v6_2/protocol_v6_2.yml`, this decision log, D1c audit
  code/tests, and `deliverables/D1c_leadlag_v6_2_20260902/**`
- **Gate affected:** free checks only; Gate A remains unauthorised
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR_REVIEW

### Frozen implementation details for D009

- The inherited centered product may expose coordinates, attributes and
  `observed_valid_count`; `observed`, `clim_mean` and `clim_std` remain unopened.
- A spatial median centered count of two or more is a necessary-but-not-sufficient
  upper-bound proxy only. It is never reported as a verified pre/post pair.
- The confirmatory diagnostic requires a verified matched-pair share of at least
  0.70 in each city under at least one frozen season window and no one acquisition
  shared by more than 0.25 of candidate passes in its stratum.
- If source dates or acquisition identifiers are absent, temporal specificity is
  demoted to exploratory. The centered product cannot become the final antecedent
  exposure or future placebo; both must be rebuilt from raw HLS with one-sided rules.

## Entry 10 — lead-lag feasibility result

- **Decision ID:** V6.2-D010
- **Recorded:** 2026-09-02T00:37:06+09:00
- **Status:** READY FOR D1C REVIEW; SUPERVISOR REVIEW PENDING
- **Change:** Apply D009 and demote the temporal-specificity diagnostic to
  exploratory. Preserve the centered-product count as an upper-bound inventory only;
  do not promote it to a verified matched-pair share.
- **Reason:** The inherited object identifies itself as
  `COPERNICUS/S2_SR_HARMONIZED`, not HLS V2, and covers Phoenix 2023 only. All 66
  axis records have a spatial median centered count of at least two, including all
  two Phoenix 2023 primary-window and three sensitivity-window candidate passes that
  join to the product. However, the object stores no optical acquisition identifiers,
  source dates, sensor-specific records, or lag signs. A numeric matched-pair share is
  therefore not estimable; it is not zero.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** no; metadata and optical counts only
- **Files changed:** D1c audit code/tests, `docs/v2/v6_2/protocol_v6_2.yml`, this
  decision log, and `deliverables/D1c_leadlag_v6_2_20260902/**`
- **Gate affected:** free checks only; Gate A remains unauthorised
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR_REVIEW

### Numerical basis and interpretation for D010

- The required 56 Phoenix/Los Angeles x 2019-2025 x two-window x HLSL30/HLSS30
  strata are present in `d1c_leadlag.csv`; every verified-pair field is blank and
  explicitly labeled not estimable because no HLS acquisition ledger exists.
- The two additional legacy-audit rows report the permitted centered count proxy.
  Phoenix 2023 primary has two candidate passes, both with count support, across
  three matched legacy axis records; the sensitivity window has three of three
  candidate passes across five matched axis records. The wider legacy object contains
  27 primary-window and 66 sensitivity-window axis records.
- The required timing histogram is emitted in an explicit no-verifiable-lag state:
  zero verified pre-lag records and zero verified post-lag records. Those are counts
  of stored timing evidence, not counts of imagery availability.
- The centered product remains prohibited as either the final antecedent exposure or
  final future placebo. Restoring a confirmatory temporal-specificity diagnostic
  requires rebuilding both one-sided variables from raw HLS under the frozen matched-
  lag rule and retaining acquisition reuse.
- No optical index value, ECOSTRESS LST value, or new v6.2 coefficient was opened.

## Entry 11 — prospective five-pass Stage 1 precision-census rule

- **Decision ID:** V6.2-D011
- **Recorded:** 2026-09-02T21:23:31+09:00
- **Status:** FROZEN FOR SEALED FIVE-PASS RUN; SUPERVISOR REVIEW PENDING
- **Change:** Freeze the D1d pass population, precision-only input proxies, native-grid
  estimator, spatial jackknife, diagnostics, sealed-output boundary, power grid, and
  fail-closed ruling before calculating or viewing any new v6.2 coefficient.
- **Reason:** The complete final-study asset stack is not on disk, but the Working
  Guide explicitly permits previously processed Phoenix passes to be rebuilt on their
  native grids for this precision-only free check. The five passes are the earliest
  already-downloaded 2023 Phoenix orbits in the D1b sensitivity-window 25-degree
  metadata set with complete LST/QC/cloud/water/height bundles: 27963, 28024, 28706,
  28828 and 28909. Selection uses acquisition metadata and file completeness only.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** yes; the inherited Collection-2 Phoenix
  LST files are reused only as permitted precision inputs, never as an effect result
- **Files changed:** `docs/v2/v6_2/protocol_v6_2.yml`, this decision log, D1d code and
  tests, `outputs/v6_2/sealed_coefficients/d1d_coefficients_SEALED_20260902.csv`, and
  `deliverables/D1d_stage1_precision_v6_2_20260902/**`
- **Gate affected:** free checks only; Gate A remains unauthorised
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR_REVIEW

### Frozen implementation details for D011

- Each block-pass is fitted separately on native 70 m MGRS cells. The row floor is
  60 complete clear-land cells and the canopy p10-p90 span floor is 0.20. The model
  contains centered canopy plus the six frozen Model-A context terms; nonconstant
  context terms are centered and scaled only for numerical conditioning.
- Mandatory Collection-2 QC classes 00 and 01 are retained, cloud and water codes
  must both be zero, and LST is never resampled. Complete layer bundles use the
  highest numeric build and revision. When scenes overlap, any observed cloud or
  water invalidates the cell; the latest scene supplies a remaining valid value.
- Spatial uncertainty is a four-replicate delete-one-500 m-quadrant jackknife. A
  block-pass converges only when all four quadrants have at least eight cells and all
  four deletion fits are estimable. Open diagnostics report SE, maximum hat leverage,
  residual Moran's I, information balance and stability, never coefficient signs or
  values.
- Point estimates are written only to the canonical sealed-output root. The sealed
  CSV may be hashed but not opened before the D1d ruling is written.
- The planning grid crosses observed p25/median/p75 Stage-1 SE, reliabilities
  0.30/0.50/0.70, detection and equivalence formulas, and all eight D1b connected
  counts. The optimistic case is p25 SE with reliability 0.70; its required count is
  the larger detection/equivalence count. Stop before Gate A only if that count
  exceeds every D1b available connected count in both cities.
- Precision-only deviations are explicit: Collection 2 rather than final Collection
  3 LST; inherited modified-NLCD canopy rather than annual Science TCC; LSTE height
  rather than 3DEP; NLCD-derived water distance; and a 10 m footprint-fraction
  approximation. None may be promoted to the final v6.2 exposure or context stack.
- During pre-run input inventory, an inherited granule report was printed with stored
  LST minimum, maximum and mean columns. This was a process deviation. It exposed no
  new coefficient and was not used to select the passes, thresholds, model, or ruling;
  the incident is preserved here rather than omitted.

## Entry 12 — five-pass Stage 1 precision-census result

- **Decision ID:** V6.2-D012
- **Recorded:** 2026-09-02T21:36:50+09:00
- **Status:** D1D STOP — NO ESTIMABLE BLOCK-PASS; SUPERVISOR REVIEW PENDING
- **Change:** Apply D011 without relaxation. Stop the D1d calculation before any
  coefficient fit because no candidate block-pass meets the frozen canopy-span floor.
- **Reason:** The five selected passes supply 13,210 block-passes with at least 60
  complete clear-land native cells, but all 13,210 have canopy p10-p90 span below
  0.20. The observed maximum is 0.185551; the median is 0.043041. Therefore no
  spatially robust Stage-1 SE, detection count, or equivalence count is estimable.
- **v6.2 coefficient viewed before change:** no; none was calculated
- **Prior retired thermal work relevant:** yes; five inherited Collection-2 Phoenix
  passes were opened only after D011, and the calculation stopped on the nonthermal
  canopy-span precondition
- **Files changed:** D1d code/tests, `docs/v2/v6_2/protocol_v6_2.yml`, this log,
  `docs/v2/v6_2/prior_thermal_access.md`, the canonical sealed header-only CSV, and
  `deliverables/D1d_stage1_precision_v6_2_20260902/**`
- **Gate affected:** free checks; Gate A remains unauthorised
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR_REVIEW

### Numerical basis and interpretation for D012

- Candidate rows by pass are 2,760 (orbit 27963), 2,651 (28024), 2,807 (28706),
  2,807 (28828), and 2,185 (28909). Complete native-cell counts range from 493,309
  to 684,389 by pass. Candidate block-pass cell counts range from 60 to 450, with
  median 210.
- Canopy-span p25/median/p75 are 0.021918/0.043041/0.065816 and the maximum is
  0.185551. Zero rows meet the 0.20 floor, so estimability, convergence, spatial SE,
  leverage, residual Moran's I and stability cannot be reported beyond their failed
  status. The open table contains no point estimate field.
- `d1d_n_required.csv` retains all 48 D1b city/window/view x reliability x criterion
  cells. Attenuated detection and equivalence targets and D1b available counts are
  shown, but observed sigma and required N are blank with an explicit not-estimable
  status. No number is invented.
- The sealed file is intact, contains its header and zero coefficient rows, and has
  SHA-256 `146b16f85aa89c486d174121d1e3e781ded685d8940f0dc6037e238b090d6004`.
  It was hashed but not opened after creation.
- The free-check ruling is `STOP_BEFORE_GATE_A_NO_ESTIMABLE_BLOCK_PASS_UNDER_FROZEN_CANOPY_SPAN`.
  Because the screen used the inherited canopy asset that v6.2 prohibits as final
  Science TCC, this is a stop on the current D1d/Gate-A package, not a binding claim
  that final annual Science TCC would also yield zero eligible block-passes. Obtain
  raw annual Science TCC, repeat the nonthermal span screen, and seek supervisor
  direction before any further thermal run.
- The three required cautions remain: a Stage-1 SE would be a measurement-error
  floor rather than the Stage-2 residual SD; connected block-passes, not all rows,
  define usable support; and passes sharing an HLS acquisition are dependent.

## Entry 13 — pre-Gate-A input acquisition and local verification

- **Decision ID:** V6.2-D013
- **Recorded:** 2026-09-02T22:57:51+09:00
- **Status:** VERIFIED INPUT ACQUISITION; SUPERVISOR REVIEW PENDING
- **Change:** Record the private-Drive acquisition and independent local verification of
  149 HLS V2 Fmask files, 14 annual Science TCC v2025-6 files and two USGS 3DEP
  frozen-domain files. Preserve full HLS reflectance, ECOSTRESS Collection 3 thermal
  products and precipitation as explicit post-approval or outstanding inventory items.
- **Reason:** The pre-Gate-A package requires a reproducible raw-asset inventory. Each
  Drive raster was downloaded to the git-ignored raw tree, checked against Google Drive
  MD5, independently SHA-256 hashed, and retained without deleting the earlier HLS copy.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** no; no ECOSTRESS thermal value was accessed
- **Files changed:** acquisition scripts and write-up, raw verification manifests,
  `docs/v2/v6_2/protocol_v6_2.yml`, this decision log, and the consolidated inventory
- **Gate affected:** free checks; no gate is opened
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR_REVIEW

### Verified inventory totals for D013

- HLS V2 Fmask: 149 files, 161,907,529 bytes, every local SHA-256 recorded.
- Science TCC v2025-6: 14 files, 211,808,618 bytes, Google MD5 equals local MD5 for
  every file and every local SHA-256 is recorded.
- USGS 3DEP 1/3 arc-second: two files, 426,375,529 bytes, Google MD5 equals local MD5
  for both and both local SHA-256 values are recorded. The frozen source snapshot ends
  2022-05-04 and is not described as the newest 2026 USGS tile state.
- No HLS reflectance or ECOSTRESS thermal value was opened during acquisition or hashing.

## Entry 14 — VPD branch held inactive for supervisor ruling

- **Decision ID:** V6.2-D014
- **Recorded:** 2026-09-02T22:57:51+09:00
- **Status:** INACTIVE HOLD — NO FINAL KEEP/DROP RULING
- **Change:** Replace the operational label `dropped` with `inactive hold pending
  supervisor review`. This does not activate either VPD interaction and does not claim
  that the frozen D003 criteria passed.
- **Reason:** The user requested a status report rather than a final drop. The binding
  full-nuisance D003 test fails in both cities. The nonbinding parsimonious D005
  sensitivity passes all criteria in Phoenix but Los Angeles supplies only 0.300 kPa of
  continuously supported VPD width versus the frozen 0.50 kPa floor. This mixed evidence
  is presented to the supervisor for an explicit keep/drop decision.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** no
- **Files changed:** `docs/v2/v6_2/protocol_v6_2.yml`, this decision log, final summary
- **Gate affected:** free checks; the demand branch is prohibited from the active model
  unless the supervisor approves a protocol amendment before coefficient access
- **Approved by:** USER-DIRECTED STATUS HOLD; PENDING_SUPERVISOR_REVIEW

## Entry 15 — prospective official-Science-TCC canopy-span screen

- **Decision ID:** V6.2-D015
- **Recorded:** 2026-09-02T22:57:51+09:00
- **Status:** FROZEN BEFORE SCIENCE TCC VALUE ACCESS
- **Change:** Freeze an outcome-free repeat of the D1d canopy-span screen using the
  official annual Science TCC v2025-6 cover band for 2019-2025. Stable source cells have
  annual range at most 0.15; their seven-year median canopy fraction is area-averaged to
  native ECOSTRESS cells without bilinear interpolation.
- **Reason:** D012 used a prohibited inherited NLCD-derived proxy. The required product
  is now locally available, so the proxy finding can be confirmed or overturned before
  another thermal calculation.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** no; this first screen is nonthermal
- **Files changed:** `docs/v2/v6_2/protocol_v6_2.yml`, this decision log, TCC screen code,
  tests and open diagnostics
- **Gate affected:** free checks only; Gate A remains unauthorised
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR_REVIEW

### Frozen decision rule for D015

- Use the five D011 Phoenix orbits and an optimistic native mask: mandatory QC 00/01,
  cloud zero, water zero and finite height. Do not read LST during the screen.
- Require at least 60 native cells and canopy p10-p90 span at least 0.20 per block-pass.
- If zero block-passes pass, retain the Stage-1 stop without opening thermal values. If
  any pass, rerun D1d on the same five passes under D011 and write estimates only to a
  new sealed file. No threshold relaxation is permitted.

## Entry 16 — official-Science-TCC canopy-span result

- **Decision ID:** V6.2-D016
- **Recorded:** 2026-09-02T23:02:30+09:00
- **Status:** STAGE 1 STOP CONFIRMED WITH REQUIRED CANOPY PRODUCT; SUPERVISOR REVIEW PENDING
- **Change:** Apply D015 without relaxation. Retain the Stage-1 stop and do not rerun
  the five-pass thermal calculation because no official-Science-TCC block-pass meets
  the frozen canopy-span floor.
- **Reason:** The optimistic nonthermal mask yields 13,509 block-passes with at least
  60 cells. Zero reach p10-p90 canopy span 0.20. The observed maximum is 0.184100 and
  the median is 0.066004, so opening LST could only remove cells and cannot establish
  eligibility under the frozen rule.
- **v6.2 coefficient viewed before change:** no; none was calculated
- **Prior retired thermal work relevant:** no; D015 read Science TCC and nonthermal
  native QA/geometry layers only
- **Files changed:** TCC screen code/tests, `docs/v2/v6_2/protocol_v6_2.yml`, this log,
  and `deliverables/D1d_tcc_span_screen_v6_2_20260902/**`
- **Gate affected:** free checks; Gate A remains unauthorised pending supervisor stop,
  reframe or protocol-amendment decision
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR_REVIEW

### Numerical basis and consequence for D016

- Candidate block-pass counts are 2,828, 2,684, 2,876, 2,876 and 2,245 for orbits
  27963, 28024, 28706, 28828 and 28909, respectively.
- Canopy-span p25/median/p75 are 0.044860/0.066004/0.085309; maximum 0.184100.
- The Science TCC stability screen retains 9,041,017 Phoenix source cells under the
  frozen annual-range-at-most-0.15 rule.
- Because the nonthermal mask is optimistic relative to the complete thermal model,
  zero eligibility is sufficient to stop the conditional rerun without viewing LST.
  No observed Stage-1 SE or required connected count can be computed. The exact
  power-based early-stop rule therefore remains not evaluable; the supervisor must
  choose stop, reframe or a prospectively amended design.

## Entry 17 — verified initial package and current Gate A recommendation

- **Decision ID:** V6.2-D017
- **Recorded:** 2026-09-02T23:12:00+09:00
- **Status:** PACKAGE VERIFIED; SUPERVISOR DECISION REQUIRED
- **Change:** Assemble the consolidated per-file inventory, package index, checksums
  and one-page status summary. Recommend that Gate A not begin under the current
  frozen design; present VPD as inactive on hold rather than formally dropped.
- **Reason:** All 165 acquired files have local SHA-256 values and the 16 Drive
  outputs also match Google MD5 metadata. D016 supplies the controlling Stage-1
  result: zero of 13,509 candidate block-passes meet the official Science TCC span
  floor. The VPD evidence remains mixed across the binding D003 and nonbinding D005
  rules and therefore needs an explicit supervisor ruling before activation.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** disclosed only; no thermal or HLS
  reflectance value was opened during acquisition, hashing, inventory assembly or
  the official TCC screen
- **Files changed:** protocol, decision log, acquisition/access records, TCC screen
  package, consolidated inventory workbook, one-page summary and package checksums
- **Gate affected:** free checks; Gate A remains unauthorised
- **Approved by:** USER-DIRECTED PACKAGE ASSEMBLY; PENDING_SUPERVISOR_REVIEW

### Package and asset locations for D017

- Private Drive root:
  `https://drive.google.com/drive/folders/1BWuKX2np0_cTVPvVpiFCQXq5Ip6whU1R`.
- HLS Fmask Drive subfolder:
  `https://drive.google.com/drive/folders/1_axArxHQ2-6WFZ4k3NOIBE77seXl-Jfs`.
- Consolidated inventory:
  `deliverables/Initial_Package_v6_2_20260902/asset_inventory_and_package_index.xlsx`.
- One-page summary:
  `deliverables/Initial_Package_v6_2_20260902/one_page_summary.pdf`.
- Verification-manifest SHA-256 values: HLS
  `62cfc4752f87062eb9f95691d48b77340c4d4fa1c329aa771d1cc89c6bb930ab`,
  Science TCC
  `265134308e0fcaddde9bbc9ba99f19af55a05a3e92d4f1c4b04323186f611206`,
  and 3DEP
  `cf5e50550146672b57b3715dec099734f7cc3a0f620977d3c73407f9acb86148`.

## Entry 18 — prospective HLS-Fmask lead–lag reassessment

- **Decision ID:** V6.2-D018
- **Recorded:** 2026-09-02T23:40:41+09:00
- **Status:** FROZEN BEFORE HLS FMASK VALUE ACCESS; SUPERVISOR REVIEW PENDING
- **Change:** Reassess D1c using the newly acquired HLS V2 source times,
  acquisition identifiers and 149 Fmask rasters. Retain the D009 timing and
  confirmatory thresholds without relaxation. Define a usable acquisition-block as
  at least 60 clear 30 m HLS cells, and require a matched pre/post pair to share at
  least 30 usable 1 km study blocks.
- **Reason:** The source schedule requires feasible matched observations but does not
  state an image-level cloud cutoff. Sixty cells reuses the frozen optimistic D1b
  support floor and corresponds to the later planning requirement of 30 effective
  tree plus 30 effective background pixels. Thirty common blocks reuses the frozen
  Gate A block-support floor. These are outcome-blind necessary-condition screens;
  canopy and background support may remove blocks later.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** no; only public metadata and manifest
  fields were inspected before this rule was frozen
- **Files changed:** `docs/v2/v6_2/protocol_v6_2.yml`, this decision log, D1c
  Fmask reassessment code/tests and its evidence package
- **Gate affected:** free checks only; Gate A remains unauthorised
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR_REVIEW

### Frozen implementation details for D018

- Use the D1b 1 km local-UTM grid and retain blocks whose centroids lie inside each
  2020 Census urban area.
- A clear HLS cell is non-NoData, has Fmask bits 1–5 all zero, and aerosol bits 6–7
  no greater than two, exactly as already frozen in the product specification.
- For each thermal pass and sensor, enumerate distinct source-identified pairs with
  one acquisition 1–15 days before and one 1–15 days after, and absolute lags within
  three days. Discard pairs with fewer than 30 common usable blocks, then apply the
  D009 lag/identifier tie-breaker.
- Do not open HLS reflectance, an optical index, ECOSTRESS LST or any new v6.2
  coefficient. A computational or manifest-integrity failure exits nonzero; a
  scientific demotion remains a valid completed result.

## Entry 19 — HLS-Fmask lead–lag reassessment result

- **Decision ID:** V6.2-D019
- **Recorded:** 2026-09-02T23:51:39+09:00
- **Status:** D1C TIMING PROVENANCE REPAIRED; CONFIRMATORY SUPPORT FAILED;
  SUPERVISOR REVIEW PENDING
- **Change:** Apply D018 without relaxation. Supersede D010's missing-provenance
  basis with a direct HLS V2 Fmask and source-ledger result. Keep the
  temporal-specificity diagnostic exploratory because neither city has a frozen
  season window meeting every nonzero year-sensor pair-share and acquisition-reuse
  criterion.
- **Reason:** All 149 Fmask files match the frozen manifest and all exact source
  identifiers and times reconcile. Forty-one of 110 candidate pass-window-sensor
  records have a timing-valid pair with at least 30 common QA-usable blocks. Sixty-
  three have timing-valid pairs but fail the shared-block floor, and six have no
  timing-valid pair in the downloaded 149-acquisition plan. The overall 37.3% pair
  share is descriptive; the binding decision uses the frozen stratum-level rule.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** no; only HLS Fmask quality values and
  source metadata were opened
- **Files changed:** D1c Fmask code/tests and evidence, `docs/v2/v6_2/protocol_v6_2.yml`,
  this decision log, and the initial-package index and decision summary
- **Gate affected:** free checks only; Gate A remains unauthorised
- **Approved by:** USER-DIRECTED EXECUTION; PENDING_SUPERVISOR REVIEW

### Numerical basis and interpretation for D019

- Phoenix has 20 quality-screened pairs among 44 candidate records (45.5% pooled):
  5/10 in the primary window and 15/34 in the sensitivity window. Acquisition
  reuse passes every Phoenix stratum, but neither window reaches 70% in every
  nonzero year-sensor stratum.
- Los Angeles has 21 quality-screened pairs among 66 candidate records (31.8%
  pooled): 15/50 in the primary window and 6/16 in the sensitivity window. Neither
  window passes the stratum-level share rule, and three strata also fail the frozen
  acquisition-reuse limit.
- Seventy-seven of 149 acquisitions contain at least 30 usable blocks. Selected
  pairs use 57 unique acquisition identifiers. Median pre/post lags are
  8.157/8.709 days; 90th percentiles are 13.010/13.831 days.
- D010 is superseded only as to why the check is exploratory. Timing direction,
  identity and reuse are now estimable; the current demotion is a numerical support
  failure, not missing provenance and not proof of zero imagery.
- The 149 rasters were selected by the earlier catalogue pairing plan. A failed row
  is therefore conservative with respect to alternative HLS acquisitions whose
  Fmask was not downloaded. Passing rows are directly verified. This free check
  does not authorize Gate A, open reflectance, or create a final exposure/placebo.

## Entry 20 — nonbinding 20% lead-lag support sensitivity

- **Decision ID:** V6.2-D020
- **Recorded:** 2026-09-03T01:27:30+09:00
- **Status:** POST-SUPPORT SENSITIVITY COMPLETE; CONTROLLING D019 UNCHANGED;
  SUPERVISOR REVIEW PENDING
- **Change:** At the user's request, repeat only the D1c matched-pair-share ruling
  at 20% while retaining the all-nonzero-year-by-sensor structure, 25% acquisition-
  reuse limit, and all D018 timing, Fmask, and common-block requirements.
- **Reason:** The 70% support result was already known, so a relaxed cutoff cannot
  replace the frozen D009/D019 decision. A labeled sensitivity can nevertheless
  show whether 20% changes the practical conclusion. It does not: every city-window
  still has one or more zero-share strata, and Los Angeles also retains three reuse
  failures across its two windows.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** no; the sensitivity reads only the
  existing 56-row D1c Fmask feasibility table
- **Files changed:** parameterized D1c ruling logic/tests, protocol, this decision
  log, and `deliverables/D1c_20pct_sensitivity_v6_2_20260903`
- **Gate affected:** free checks only; Gate A remains unauthorised
- **Approved by:** USER-DIRECTED SENSITIVITY; PENDING SUPERVISOR REVIEW

### Numerical basis and scope for D020

- Phoenix primary has three share failures among six nonzero strata; Phoenix
  sensitivity has six among fourteen. Acquisition reuse passes throughout Phoenix.
- Los Angeles primary has seven share and two reuse failures among fourteen
  nonzero strata; its sensitivity window has four share and one reuse failure
  among eight.
- Pooled shares (45.5% Phoenix and 31.8% Los Angeles) exceed 20%, but pooled share
  is not the retained decision rule. The failures are concentrated in year-sensor
  strata with zero verified pairs, which fail any positive percentage threshold.
- This is D1c lead-lag feasibility. It is separate from D1b block-pass connectivity,
  which is the item explicitly requested in the professor's email. D1c appears in
  the attached schedule/guide and may later reduce graph edges when final optical
  eligibility is applied, but it does not answer the baseline connectivity question.

## Entry 21 — nonbinding 0.10 canopy-span sensitivity

- **Decision ID:** V6.2-D021
- **Recorded:** 2026-09-03T01:44:48+09:00
- **Status:** POST-SUPPORT SENSITIVITY COMPLETE; CONTROLLING D016 UNCHANGED;
  SUPERVISOR REVIEW PENDING
- **Change:** At the user's request, reclassify the 13,509 already-recorded D016
  nonthermal block-passes at a p10-p90 canopy-span floor of 0.10 rather than 0.20.
  Do not open LST, fit Stage 1, or replace the controlling D015/D016 result.
- **Reason:** The 0.20 result was already known. A post-support threshold change is
  therefore nonbinding, but it can quantify whether a prospectively approved 0.10
  rule would remove the empty-sample obstruction. It would: 1,368 block-passes
  across 331 Phoenix blocks meet 0.10.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** no; the sensitivity reads only D016's
  already-open nonthermal Science TCC span rows
- **Files changed:** protocol, this decision log, sensitivity code/tests, and
  `deliverables/D1d_10pct_canopy_span_sensitivity_v6_2_20260903`
- **Gate affected:** free checks only; Gate A remains unauthorised
- **Approved by:** USER-DIRECTED SENSITIVITY; PENDING SUPERVISOR REVIEW

### Numerical basis and consequence for D021

- Eligibility by selected Phoenix pass is 220/2,828, 282/2,684, 311/2,876,
  311/2,876 and 244/2,245, respectively: 1,368/13,509 (10.13%) overall.
- The 331 eligible blocks have eligible-pass counts of one for 19 blocks, two for
  3, three for 51, four for 100 and all five for 158; the median is four passes.
- The 0.10 rule means a ten-percentage-point within-block p90-p10 canopy difference,
  not ten percent of observations. Its purpose remains protection against fitting a
  local canopy-temperature slope where canopy is nearly uniform.
- If approved prospectively, this result would clear the nonthermal zero-eligibility
  stop and allow consideration of the same five-pass sealed Stage-1 thermal pilot.
  It does not establish final tree/background support, slope estimability,
  uncertainty, power, Los Angeles feasibility or Gate-A eligibility.

## New-entry template

- **Decision ID:** V6.2-D___
- **Recorded:** YYYY-MM-DDThh:mm:ss±hh:mm
- **Status:** PROPOSED | FROZEN | REJECTED | SUPERSEDED
- **Change:**
- **Reason:**
- **v6.2 coefficient viewed before change:** yes | no
- **Prior retired thermal work relevant:** yes | no
- **Files changed:**
- **Gate affected:** none | free checks | A | B | full analysis
- **Approved by:**


## 19 September 2026 Meeting and follow-up incorporated into v6.2

Source: user-authorized update from the meeting transcript/summary, written Next Steps attachment, and the later email responding to Paper reviews. Source copies and hashes are recorded in references/sources and the current manifest. The meeting date itself was not supplied; this is the documentation date.

Change: use one pooled canopy slope per city-pass with block-specific intercepts, native-cell outcomes and shared within-block canopy term. Remove per-block 0.20/0.10 span gates and the arbitrary eight-pass rule. Set pass-level within-block-information and contributing-block thresholds from observed nonthermal distributions before fitting; determine time-study pass requirements by simulation/power.

Change: focus the primary question on the observation-time pattern. Use the five frozen Phoenix passes plus five equivalent passes in a higher-canopy city selected from Atlanta/Charlotte after a nonthermal screen. Los Angeles moves to the post-review expansion. Keep quality, native-grid, primary canopy, stability, season and uncertainty safeguards where applicable. Audit overlapping ground cells, raster aggregation and the full catalogue metadata.

Change: add identical matched-cell temperature and emitted-energy models, a fully specified reference-anchored prediction/fourth-root transformation, constant-contrast synthetic mixing tests, and a prospectively frozen scale-agreement rule. Keep total observation time primary, including solar geometry; geometry/season standardization is secondary. VPD is descriptive only, the earlier HLS/SWIR condition hypothesis is deferred, and eight-class unmixing is out of scope. Brief high-resolution canopy validation does not replace the primary canopy product.

Change: use the advisor's approximate 0.1 K per 10 percentage points pilot-SE benchmark, with the pass-to-city aggregation rule to be frozen before execution. Report precision only while coefficients remain sealed. Freeze the scale tolerance, supported times/canopy pair, references and time model before recorded review release. The numerical scale tolerance is not specified by the email and is not equated with the pilot-SE benchmark. Full-city scaling remains paused pending pilot review despite the earlier conditional expansion instruction.

Implementation status: documentation complete; new estimator code, audits, nonthermal city selection, threshold setting and pilot execution are not performed in this update. The exact standardization algorithm and bootstrap defaults are analyst operational specifications, not new empirical findings. Pending values are explicitly marked for pre-run freeze rather than fabricated as approved.

Preservation: retain the original sources, old active files, scientific result packages and sealed coefficients. Short decision-log entries, isolation, checksums and access records remain; new conformance packages and formal IDs are set aside. No commit, push, message, meeting action, thermal-data access or unsealing occurs.


## 19 September 2026 Limited pooled pilot implemented and executed

The user authorized implementation and execution, explicitly chose to keep empirical coefficients sealed for precision review, and chose to leave the numerical agreement tolerance pending Reza. This supersedes the earlier documentation-only status and requirement to invent replacement pass-support thresholds. No arbitrary canopy-span, Sxx, contributing-block or four-of-five gate is adopted. Report all ten precision results and support distributions.

Atlanta was selected over Charlotte using a seeded 300-block nonthermal canopy screen and verified acquisition metadata. Orbits 27835, 27896, 27916, 28145 and 28598 were frozen before Atlanta thermal download; Phoenix retains 27963, 28024, 28706, 28828 and 28909. Both cities use matching Collection 2 LST, QA and wideband emissivity at native 70m cells. The pilot retains the inherited p95 25-degree precision exception; it is not the final 15-degree/complete-azimuth set. Full catalogue queries reconcile pagination and reproduce the old seasonal counts. Incomplete Collection 3 historical coverage remains a full-study decision.

Analyst operational settings: one canopy slope per city-pass with six within-block context covariates and block intercepts; scaled pivoted QR selects independent context terms before testing canopy identifiability; 1,000 paired whole-block bootstrap draws, seed 20260919; four cardinal one-cell shifts, exact common cells, 2km groups; separately frozen residual audit and 4/8km group stress checks. Canonical MGRS-core and UTM-zone ownership excludes seam-crossing native cells without LST interpolation. Complete stable-canopy area coverage is required; the retired per-block canopy-span rule is not.

Freeze the supported 0.10 canopy pair by maximizing the minimum supporting reference-block count across passes, with lower-endpoint tie break. Only reference rows need both endpoints; every eligible block remains in the slope model. Equal-city/equal-pass absolute-temperature and emissivity medians define the common anchor; predictions use original training centers, average first and then undergo exact anchored fourth-root conversion. Compare 10:30 and 16:00 apparent solar time using a city-specific linear total-time model; secondary solar-elevation/day-of-year adjustment requires convex-hull overlap and residual degrees of freedom. These are analyst choices recorded before effect access, not numerical settings supplied by Reza.

Synthetic tests use 200 seeded whole blocks/pass, component contrasts 0/2/5/10 K, 100 paired bootstrap draws and seven scenarios. Block-median temperature/emissivity anchors and a within-block temperature permutation prevent the zero-control synthetic output from reproducing the empirical regression. A constant component temperature contrast need not produce a constant energy contrast.

Public outputs contain precision, support, identities and clearly labeled simulations; empirical coefficients, bootstrap draws, prediction levels, effect sensitivity and time contrasts are stored only in the sealed root. No empirical point estimate has been displayed to the user or inspected by the assistant. Internal code reads are authorized for these calculations. The current meeting package records completed run evidence and limitations. The scale ruling remains pending tolerance and recorded release. Full-city scaling remains paused. No commit, push, email or calendar action was taken.

The repaired data link targets the relocated original data tree. Raw sources and historical result packages are preserved. Active documents are amended in place at v6.2; pre-implementation copies are archived with checksums. Phoenix's exact initial frozen code is archived because output-boundary hardening was added before the Atlanta run without changing its statistical estimator.


## 19 September 2026 User-authorized limited gradient disclosure

The user explicitly authorized viewing the ten city-pass gradients in this conversation after the sealing consequence was explained. The assistant read the existing pass-level temperature, emitted-energy and standardized temperature-equivalent coefficients; only LST gradients and previously public standard errors are displayed. The empirical time-contrast file remains unopened. No scale-agreement ruling or full-city expansion is authorized. Reza’s tolerance remains unset, so any later tolerance cannot be described as chosen before all effect access. The existing precision-review package and Word documents remain preserved as the pre-disclosure snapshot. Exact scope is recorded in `execution/limited_gradient_disclosure_20260919.json`.

### 21 September 2026 — user-authorized exploratory advance

User asked to continue, enlarge the sample, review methodological weaknesses and screen US cities. Freeze: `execution/advance_20260921/advance_scope.json`. Expand Phoenix to all eleven 2023 candidates in the inherited verified geometry frame under the existing 25-degree pilot exception (six additional passes). Keep original outputs unchanged. Plot before any new time model. Review LA readiness and screen candidate cities without new-city thermal downloads. Prior gradient disclosure means this is exploratory, not a new blinded preregistration. Reza’s scale tolerance remains unresolved.

### 21 September 2026 — extension findings and method correction

All six added Phoenix passes produced paired fits; 24 primary/spatial fits completed with 1,000 bootstrap replicates each. The original pilot is unchanged. LST-only exploratory gradient figures/table are recorded in `outputs/v6_2/scientific/exploratory_review_20260921/gradient_disclosure.json`; no prior sealed time contrasts were read. The new scatterplot was visually inspected before any new empirical time regression; none was fitted. This does not retroactively repair the original pilot's plot-first sequence deviation.

Screened nineteen frozen Census urban areas with seeded canopy blocks, full-pagination CMR metadata for June–September 2023, then cloud masks at those sampled block points. No new-city LST downloaded. Thresholds were not adjusted to retain cities: all continuous diagnostics and failures are reported. Morning cloud quality, view geometry and multi-year completeness remain to screen before final selection.

Synthetic calibration demonstrates that inherited `pilot_scale.time_contrast` overstates uncertainty when pass resampling is combined with another Stage 1 noise draw. Treat its prior intervals as provisional; preserve old artifacts. Added tested day-cluster benchmark without extra jitter, not run empirically. A separate monotone curved-response demonstration shows canopy-range dependence of linear slopes with identical underlying curves. This motivates a nonlinear sensitivity, not a primary-model switch based on observed effects.

VPD is descriptive only: current existing-hourly-data subsets have six Phoenix and four Atlanta pairs; prior arid-city correlation and LA common-support figures retain their historical labels. The current protocol remains v6.2. Reza's tolerance is pending after prior gradient disclosure, so no blinded agreement ruling is claimed.


### 21 September 2026 — sampling balance corrected with a bounded seven-pass expansion

User requested rebalancing, potentially adding/removing passes. Audited the complete cached 2019–2025 Phoenix June–September C2 catalogue (547 distinct orbits), numeric granule revisions, definitive inherited geometry and 129 cloud masks for 29 relevant passes. No 2023 July or September orbit occurs in the morning 09:30–11:30 solar window. Do not fill those gaps through cross-year pairing or label the eleven-pass frame exhaustive.

The geometry-supported paired year-month candidate groups had common clear sample-point counts 0, 3, 214, 240, 275, 300, 300 of 300. The largest observed gap (3 to 214) determined the upper group prioritized for this bounded batch; it is a documented data-derived acquisition priority, not a universal cloud gate or a chosen target count. Retain the poor-cloud 2021/2022 groups and unresolved geometry in the review ledger. Freeze orbits 06281, 06510, 33496, 33623, 40111, 40192, 40376 before downloading their matched thermal layers. This is exploratory after earlier gradient disclosure. Selection did not use those gradients or the seven new outcomes.

All seven additions completed the unchanged paired Stage 1 models, with 28 fits and 28,000/28,000 estimable paired bootstrap draws. Phoenix has 18 processed passes; Atlanta remains five. Twelve endpoints have both time windows within five year-months (2019-08, 2023-06, 2023-08, 2024-06, 2025-08). Assign each stratum one fifth of each arm's weight, divided among its passes. Retain all eleven original results: three middle-time passes support curve shape; the three July/September passes are descriptive in this matched-season analysis. Do not substitute a weighted window contrast for the exact 10:30-versus-16:00 target.

Native-cell/paired-physics checks passed; common-cell retention within strata is 73.2%–100%. Common-cell refits, registration stress checks and annual-context sensitivity remain needed. New earlier-year acquisitions reuse the frozen stable median canopy/context for estimator comparability, with vintage mismatch explicitly acknowledged. A metadata-only synthetic check removes pure month/year imbalance but retains bias under an uncontrolled within-month trend. No new empirical time regression was fitted; new point estimates stay sealed and scale tolerance is still pending. Version remains 6.2, old outputs preserved, no full-city/multi-city rollout or professor approval inferred. Current evidence: `deliverables/Sampling_Rebalance_v6_2_20260921/README.md`.
