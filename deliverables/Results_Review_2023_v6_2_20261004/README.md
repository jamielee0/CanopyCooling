# Existing 2023 results review — Step 2

Completed 4 October 2026 after the user requested “do the next part” of the detailed plan. This packet assembles the previously released sixteen linear temperature results: eleven Phoenix passes and five Atlanta passes, all from 2023. It reuses existing estimates and spatial intervals; it does not fit a time pattern or a new canopy model. Step 3, the spatial-comparison and paired-scale review, remains subsequent work.

## Files and interpretation

- [Full results CSV](pass_results_long.csv): 97 defined fields, exactly 16 `original` rows followed by 48 `spatial_uncertainty_2km`, `spatial_uncertainty_4km` and `spatial_uncertainty_8km` rows. Sensitivities reuse the same point model and cells. They are not 48 additional acquisitions.
- [Readable dictionary](data_dictionary.md) and [machine-readable dictionary](data_dictionary.json): units, field provenance, sign convention and missing-value reasons.
- Phoenix time plot: [PNG](phoenix_cooling_vs_apparent_solar_time.png) / [PDF](phoenix_cooling_vs_apparent_solar_time.pdf).
- Atlanta time plot: [PNG](atlanta_cooling_vs_apparent_solar_time.png) / [PDF](atlanta_cooling_vs_apparent_solar_time.pdf).
- [Missing-input ledger](missing_inputs.json), [descriptive summary](descriptive_summary.json) and [exact plotted-point identities](plot_points.json).
- [Execution freeze](../../docs/v2/v6_2/execution/results_packet_20261004/execution_freeze.json), [final verification](../../docs/v2/v6_2/execution/results_packet_20261004/final_verification.json) and [reuse/access record](../../docs/v2/v6_2/execution/results_packet_20261004/reuse_and_access_record.json).

The quantity is conditional canopy-associated mixed-pixel surface cooling in K per +10 percentage points of canopy. Positive cooling equals minus the signed temperature change, `CE = -0.10 × beta_T`. It is a spatial association under the existing block-intercept/context model, not an isolated tree temperature or causal intervention effect. Temperature differences in K have the same numerical magnitude as differences in °C.

| City | Acquisitions | Cooling range, K/+10pp | Spatial SE range, 1 km | Spatial SE range, 8 km | Linked weather records |
| --- | ---: | ---: | ---: | ---: | ---: |
| Phoenix | 11 | 0.893–1.705 | 0.017–0.054 | 0.033–0.082 | 6/11 |
| Atlanta | 5 | 0.097–0.338 | 0.002–0.009 | 0.005–0.013 | 4/5 |

Phoenix's largest released estimate is July 29 (1.705 K/+10pp); its smallest is June 11 (0.893). Atlanta's largest is June 3 (0.338); its smallest is June 8 (0.097). Every retained 8 km spatial percentile interval lies above zero. These intervals characterize within-pass spatial uncertainty. They do not establish an afternoon-minus-morning contrast, a seasonal pattern, independent temporal replication, or a causal ranking of cities. No expected-sign selection or new stability cutoff was applied.

## How to read the figures

Each city has its own figure and vertical scale; compare numerical values, not relative panel heights across cities. Within a city, both panels use identical axes and point estimates. The first panel uses inherited 1 km spatial-block intervals, the second uses 8 km spatial-group intervals. The CSV includes 2 km and 4 km sensitivities as well. All intervals are the existing 95% percentile intervals from whole-group resampling with original 1 km block intercepts. The larger groups do not prove independence. Each date is labelled; color shows acquisition month and squares identify the six Phoenix passes added to the sample on 21 September 2026. All acquisitions themselves occurred in 2023.

The horizontal coordinate is consistently calculated apparent solar time: UTC fractional hour plus east-positive longitude/15 plus equation of time/60, modulo 24. Longitude is the geographic centroid of each frozen domain: Phoenix −111.9616599788°, Atlanta −84.3363639197°. The harmonic equation-of-time convention follows the repository audit, with leap-year length and fractional acquisition seconds retained. Civil time, computed mean time and all inherited solar-time fields remain separate. The maximum change from the earlier plotted solar hour is 0.943 seconds. No new time model or fitted curve appears.

Phoenix contributes four June, one July, four August and two September acquisitions; Atlanta contributes four June and one July. Phoenix still has no July/September morning acquisitions in the defined 09:30–11:30 solar window. Atlanta's morning and afternoon observations occurred on different dates. The scatter cannot separate observation time from day, season, weather, geometry or changes in represented geography.

## Support, conditions and remaining gaps

The table retains all canopy quantiles, block information summaries and leverage diagnostics without a replacement support threshold. Across passes, Phoenix's cell-level median canopy fraction is 0.0248–0.0301; Atlanta's is 0.2817–0.3361. These distributions describe materially different canopy support. Neither equal canopy contrast units nor a common model specification makes the city populations interchangeable.

Retained native-cell counts range from 341,920–556,675 in Phoenix and 237,294–510,119 in Atlanta. Whole-cell projected footprint area ranges from 1,675.408–2,727.708 km² and 1,162.741–2,499.583 km² respectively. Each area sums the canonical ownership audit's unique retained 70 m cells once; scene counts and overlapping tiles are not multiplied. These are whole selected cell footprints in each city's analysis CRS, not city-clipped polygon areas or usable city-coverage fractions. The predictor snapshot and independent public precision/audit counts reconcile for every pass.

Cached exact-acquisition HRRR air temperature and VPD cover ten passes: six Phoenix and four Atlanta. Each available value was independently checked against the two existing hourly domain means and its fractional UTC interpolation. Six acquisitions lack a bracketing pair: Atlanta June 23; Phoenix June 19, June 26, August 23, September 21 and September 25. Those fields remain blank. Inherited VPD is retained separately, and VPD remains descriptive rather than a fitted adjustment or evidence of a causal cooling response. No weather retrieval occurred here.

Antecedent rainfall totals for 1/3/7 days remain `NOT_ACQUIRED`. Cell-level geometry coverage is `NOT_QUANTIFIED_IN_REUSED_SOURCES`; view-azimuth completeness retains the unresolved frozen pilot exception. The existing p95 sensor angle and 25-degree exception are labelled explicitly rather than treated as complete geometry recovery.

Paired flux changes and temperature-equivalent effects remain blank with `SEALED_NOT_RELEASED`. Their existing public SE/interval-width diagnostics are permitted precision fields. The September 19 numerical temperature/emissivity reference is retained as historical original-ten-pass metadata; applicability to the six additions is not asserted. No new conversion or scale verdict was computed, and Reza's numerical agreement tolerance remains pending.

## Verification and preservation

Fourteen network-free known-answer and boundary tests cover signed units, percentile/draw accounting, composite joins, solar clock, canonical area, support distributions, weather interpolation/missingness, product identity and sealed-output protection. Final verification checks exact CSV roundtrip and agreement with all released estimates, SEs and endpoints; 16 original identities and 2023 dates; plot-to-run mapping; ownership areas; frozen source hashes; and the current data-link target. Both city figures and the sixteen-row table preview were visually inspected. Each spatial configuration retains 1,000 estimable draws per pass with no failed draws; those are reused spatial draws, not a new temporal sample.

The prior CSV had exported collection `002` numerically as `2`; this packet recovers `002` from each exact execution manifest and preserves the original label in `source_collection_label`. Artifact-tool's automatic ISO datetime coercion was avoided through a reversible literal-text authoring prefix; CSV serialization strips that prefix after exact typed-sheet verification. Acquisition offsets and fractional seconds are preserved exactly.

All 24 named input files retain their frozen SHA256 checksums. No sealed model arrays, draw files or native thermal frames were opened, and all prior result packages are preserved. Before the completion documentation was amended, the six Step 1 active documents were archived with checksums under `docs/v2/v6_2/archive/before_results_packet_20261004/`. Earlier checksum manifests retain their historical meanings. No commit, push, external message, meeting or additional-city processing occurred.
