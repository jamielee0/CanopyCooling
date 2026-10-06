# Prior Phoenix thermal-access record

## Disclosure

Earlier Phoenix ECOSTRESS LST values, maps, summaries, and model coefficients were
viewed under designs now retired from this paper. The study is therefore **not globally
outcome-blind**. The defensible boundary is narrower: v6.2 inclusion rules, exposures,
estimator, thresholds, season and cross-city decisions were frozen before any new v6.2
coefficient was viewed. Gate B point estimates must remain sealed during the precision
decision.

| Date | City | What was viewed | Retired design | Why it does not determine the v6.2 coefficient |
|---|---|---|---|---|
| 2026-06-09 to 2026-06-10 | Phoenix | Collection 2 LST rasters, QC layers, coverage, maps, and a 66-overpass LST cube | Whole-city 70 m Phoenix pilot on a custom EPSG:32612 grid | This established data handling and QA, not a v6.2 block-pass coefficient; v6.2 uses Collection 3, native MGRS cells, new seasons, and new block-specific slopes. |
| 2026-06-16 | Phoenix | Tree-versus-reference cooling-advantage values and their distribution at block-group by overpass level | Paired tree/reference purity-threshold design | v6.2 estimates a continuous within-block canopy slope, does not use the paired contrast, and rebuilds cell eligibility and canopy amount. |
| 2026-06-16 | Phoenix | Cooling advantage against compound VPD/soil-supply stress, segmented fits, candidate breakpoints, and day/night contrasts | Compound Stress Index threshold design | CSI, breakpoint detection, pass-equivalent reasoning, and the paired outcome are retired. v6.2 jointly estimates `G`, `W_tree`, and `W_bg` effects on a different response. |
| 2026-06-17 | Phoenix | Re-run of the compound-threshold analysis after time-varying NDMI supply was introduced | Revised compound-stress threshold design | The exposure, outcome, timing rule, background construction, and estimator all differ from v6.2; the old coefficient is neither reused nor a selection criterion. |
| 2026-06-17 | Phoenix | Pixel-level local-pairing and clustering-aware threshold explorations, including response-surface and effective-sample diagnostics | Enlarged paired-pixel threshold design | v6.2 prohibits the paired-pixel response and treats block-passes—not paired pixels—as Stage 2 observations. |
| 2026-07-17 | Phoenix | Uncommitted exploratory pixel-level mixed-effects coefficients and VPD × soil-moisture response-surface outputs | Mundlak/crossed-random-effects extension of the retired paired outcome | These are retained only as disclosed design history. v6.2 uses pass-specific block interactions in Stage 1 and two-way fixed effects on separately built optical components in Stage 2. |
| 2026-09-02 | Phoenix | Five frozen Collection-2 native-grid passes were opened for D1d after D011; processing stopped at the nonthermal 0.20 canopy-span precondition | v6.2 free-check precision census using explicitly nonfinal context proxies | No block-pass passed the span floor, so no new v6.2 coefficient was calculated or viewed. The canonical sealed CSV contains a header and zero rows; only its checksum was exposed. |

## Evidence locations

- `docs/DESIGN_DECISIONS.md`
- `docs/section14_results_note.md`
- `docs/section14b_mixed_effects_note.md`
- `figures/section13_cooling_advantage_distribution.png`
- `figures/section14_*`
- `figures/section15_response_surface_vpdz_smz*.png`
- inherited commits `10d6ec1`, `59e65ed`, `711c7f9`, `ff4ab5e`, and `e32ff06`

The rows above are a conservative disclosure: if a historical thermal artifact is
later found that is not covered by these analysis families, add a new row before Gate B.
Reviewing file names, provenance, hashes, and historical documentation for this freeze
did not compute, display, or open a new v6.2 scientific coefficient.

The D015–D016 official Science TCC screen opened only annual Science TCC cover and
nonthermal native QA/cloud/water/height layers. It did not open LST or HLS reflectance
values and did not calculate or view a coefficient. Acquisition and per-file hashing
likewise accessed no thermal or reflectance values.


## 19 September 2026 documentation update

This update read the supplied meeting/email sources and existing documents only. It did not open thermal rasters, coefficient files or bootstrap draws, fit models, run simulations or unseal results. Earlier disclosures above remain unchanged. Future access to aggregate absolute temperatures for the mixing test must be logged separately from coefficient access.


## 19 September 2026 Authorized limited pooled pilot execution

This entry supersedes only the earlier documentation-only access status. Historical descriptions above refer to retired versions; the current pilot uses one shared canopy slope per city-pass, not block-specific slopes or the deferred optical Stage 2 design. Both current cities use Collection 2.

The authorized code opened native LST and matching wideband-emissivity rasters for exactly five frozen Phoenix and five preselected Atlanta passes, constructed paired cells, and calculated pooled coefficients, bootstrap draws, registration/composition sensitivities and spatial residuals. These values were processed programmatically and stored in access-restricted sealed output directories. Only precision, support, residual dependence and provenance were displayed. No empirical cooling coefficient, effect sign, bootstrap endpoint, fitted prediction or time-contrast value was displayed or inspected by the assistant.

The scale/simulation code separately accesses the observed canopy, absolute-temperature and emissivity distributions. Frozen reference selection uses non-effect canopy support and equal-city/equal-pass absolute medians; their aggregate numerical anchors are permitted public documentation. Block-median and permuted-temperature synthetic outcomes are clearly labeled. Simulation results do not constitute coefficient release. Internal paired time comparisons remain sealed; Reza's numerical tolerance is still pending.

This study is not globally outcome-blind because of the historical Phoenix access documented above. The narrower current boundary is preserved: nonthermal city/pass selection and comparison settings were recorded before empirical effect display; no rules were selected using a newly displayed empirical point estimate.


## 19 September 2026 Limited pass-gradient disclosure

The user explicitly authorized viewing the ten city-pass gradients in this conversation after the sealing consequence was explained. The assistant read the existing pass-level temperature, emitted-energy and standardized temperature-equivalent coefficients; only LST gradients and previously public standard errors are displayed. The empirical time-contrast file remains unopened. No scale-agreement ruling or full-city expansion is authorized. Reza’s tolerance remains unset, so any later tolerance cannot be described as chosen before all effect access. The existing precision-review package and Word documents remain preserved as the pre-disclosure snapshot. Exact scope is recorded in `execution/limited_gradient_disclosure_20260919.json`.

### 21 September 2026 — bounded exploratory extension

User explicitly requested continuation/increased passes. Added Phoenix orbits 28085, 28192, 28970, 29092, 29545, 29606 under the prior nonthermal frame. Paired temperature/emitted-energy fits stored separately. Original ten and added six LST pass gradients/intervals disclosed in the exploratory table/plot under a recorded release; no prior time-contrast file read. New city access comprised canopy, orbital metadata and cloud masks only, without LST. Old paired scale tolerance remains unset; global coefficient blindness cannot be claimed.


### 21 September 2026 — bounded sampling rebalance

The latest user asked to rebalance passes. Nonthermal catalogue, inherited geometry and cloud masks selected seven new Phoenix orbits (06281, 06510, 33496, 33623, 40111, 40192, 40376) before thermal download. This does not erase prior disclosed effects. Authorized code then read matching C2 LST/emissivity and calculated paired Stage 1 fits and spatial bootstrap draws for the seven orbits. New coefficient arrays remain sealed and were not displayed or inspected by the assistant. The verification code read native-cell tables to check unique IDs, emitted-energy physics and common-footprint/canopy support; outputs disclose counts and precision only. No previous sealed time contrast was opened; no new empirical time model was fitted. Synthetic imbalance checks use invented outcomes and metadata only. Scale tolerance remains unset.
