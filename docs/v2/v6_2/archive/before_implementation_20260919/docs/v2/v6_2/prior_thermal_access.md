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
