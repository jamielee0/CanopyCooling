> Current main pilot is 2023 only. Wider-year screening mentioned below is a future design proposal, not an adopted expansion of that pilot.

# U.S. city screen — a data-based shortlist

This screen covers nineteen Census urban areas, including the existing pilot/expansion cities. It uses canopy, orbital metadata and cloud masks; no new-city LST was downloaded. The candidate pool and design were recorded before the screen, and no threshold was chosen to force a preferred number of cities to pass.

## Where to put the next effort

**Strong first candidates: Raleigh, Charlotte, Baltimore and Washington–Arlington.** They combine high sampled within-block canopy heterogeneity with useful 2023 afternoon cloud opportunity. Raleigh and Atlanta's sampling intervals overlap; their point-estimate ranking does not establish a meaningful difference.

**Good candidates for geographic breadth: Seattle, Portland, Minneapolis–St Paul and Chicago.** Seattle and Portland had especially good sampled afternoon clear coverage. Minneapolis has more afternoon opportunities but variable clouds; Chicago's median sampled spatial coverage was only about 60%, so the next audit must address partial footprints. These are still provisional candidates.

**Keep Philadelphia, New York and Boston in the candidate pool.** Their canopy heterogeneity is strong, but the screened 2023 afternoon coverage was less consistent. Boston's median clear fraction was only 0.7% across five opportunities; some individual passes were substantially better. Do not permanently reject a city based on this single-year median. First examine additional years and morning support.

**Houston and Dallas are useful warm-climate alternatives.** Their canopy heterogeneity is lower than the leading eastern candidates, but they had useful afternoon coverage. Dallas especially benefits from its clear-sky opportunity. Sacramento, Denver and Miami remain alternatives with weaker canopy information in this screen. Phoenix and LA remain scientifically useful low-canopy comparisons rather than a model for selecting all new cities.

The eight first candidates above are a proposed next-screen group, not a final set of eight approved cities. The final 8–12 additions should be chosen after the wider-year and full geometry/quality audits. Retain all failed or unsupported candidates in the selection record. Regional diversity follows canopy information and usable afternoon coverage; it is not a claim that this convenience sample represents every U.S. city.

## Observed distributions

| Urban area | Within-block canopy variance | Afternoon passes | Median clear coverage of all sampled points |
|---|---:|---:|---:|
| Raleigh | 0.0846 | 8 | 63.0% |
| Atlanta | 0.0830 | 8 | 39.7% |
| Charlotte | 0.0719 | 7 | 55.7% |
| Boston | 0.0636 | 5 | 0.7% |
| Baltimore | 0.0553 | 7 | 75.3% |
| Washington–Arlington | 0.0542 | 9 | 62.3% |
| Philadelphia | 0.0542 | 6 | 38.0% |
| New York | 0.0441 | 7 | 35.3% |
| Minneapolis–St Paul | 0.0382 | 11 | 32.7% |
| Seattle | 0.0367 | 14 | 94.8% |
| Portland | 0.0293 | 12 | 98.0% |
| Chicago | 0.0225 | 10 | 59.8% |
| Houston | 0.0159 | 8 | 68.3% |
| Dallas | 0.0145 | 9 | 99.3% |
| Miami | 0.0101 | 6 | 38.5% |
| Sacramento | 0.0061 | 6 | 96.8% |
| Denver | 0.0043 | 7 | 35.0% |
| Los Angeles | 0.0040 | 8 | 81.0% |
| Phoenix | 0.0016 | 7 | 71.3% |

[Figure](../figures/candidate_city_screen.png) · [Full numeric table, including sampling intervals and coverage](../tables/candidate_city_screen.csv)

## Exact screen and limitations

- **Domain:** Census urban agglomeration, not administrative city limits. Public TIGERweb identifiers/geometries are saved in the execution directory.
- **Canopy:** Science TCC v2025-6, 2019–2025 median where all seven years are valid and the range is ≤15 percentage points, matching the inherited stability design. Sample up to 300 fixed 1 km UTM blocks with at least half their area inside the domain, seed 20260919. That half-area rule defines the screen's sampling frame; it is not a new thermal-model block inclusion gate. All nineteen cities had 300 sampled blocks. Report normalized within-block Sxx, concentration and 2,000 block-resample sampling intervals. This is a 30 m canopy screen before ECOSTRESS masking and context residualization.
- **Acquisitions:** Complete paginated CMR Collection 2 queries for June–September 2023, exact footprint/domain intersection, latest revision per orbit/scene/tile, unique orbit counts. Apparent solar time is calculated at each urban area's centroid. Afternoon 15:00–18:00 and morning 09:30–11:30 bins are descriptive summaries, not minimum-count or eligibility gates.
- **Clouds:** Catalogue cloud percentages were absent, so 535 distinct cloud-mask files were downloaded and checked. There were no asset failures. At one fixed representative point per sampled block, a pass is observed if at least one mask gives 0/1; any overlapping cloud flag vetoes a clear classification. The screen covers 155 city-pass opportunities and 300 points per city. Median clear coverage uses all sampled points in the denominator, so it incorporates missing spatial coverage as well as clouds. Clear fraction among observed points and observed coverage are also retained separately.
- **What remains:** Full-resolution usable cells, water/thermal QC, near-nadir/azimuth coverage, morning cloud opportunity, and 2019–2025 coverage. These data support a shortlist; they do not certify final usable passes or final 10:30–afternoon support. Cloud sampling errors and canopy-product uncertainty are not captured by the canopy block-resampling intervals.
- **No hidden cutoff:** Continuous diagnostics are retained. The summed clear-area-equivalent count in the CSV is a coverage summary, not a number of independent clear passes and not a power calculation.

Sources: [Census urban-area service](https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Urban/MapServer/0), [USFS canopy product](https://data.fs.usda.gov/geodata/rastergateway/treecanopycover/), [NASA CMR](https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html), and matching ECOSTRESS Collection 2 cloud masks. Exact queries, granules, point records and asset SHA256 hashes are retained under `docs/v2/v6_2/execution/advance_20260921/`.
