# Input audit and pilot selection

The nonthermal screen sampled 300 fixed 1km blocks per city, with seed 20260919, from blocks at least half inside the Census urban area. This area condition belongs to the comparative screening design, not the native-cell model eligibility rule. The screen used stable 2019–2025 Science TCC v2025-6 at its native 30m grid. It is not a substitute for the actual pass-specific native-cell support table.

| city | valid_blocks | sampled_within_block_variance | max_block_information_share |
| --- | --- | --- | --- |
| phoenix | 300 | 0.00159 | 0.01083 |
| atlanta | 300 | 0.08301 | 0.00629 |
| charlotte | 300 | 0.07189 | 0.00637 |

Atlanta was selected for its greater within-block variation and verified afternoon acquisitions. Its five passes are the first chronological 2023 June–September passes in the inherited inventory with verified L1B domain coverage at least 95% and p95 view zenith at most 25 degrees. This is a reproducible geometry-verified candidate frame; it is not claimed to enumerate every potentially usable pass. Selection was frozen before Atlanta thermal downloads. The second-city input scope is exactly five passes.

| City | Orbit | UTC acquisition | Apparent solar hour | View p95 degrees |
| --- | --- | --- | --- | --- |
| phoenix | 27963 | 2023-06-11T23:39:53.676000+00:00 | 16.212 | 10.777 |
| phoenix | 28024 | 2023-06-15T22:00:38.485000+00:00 | 14.545 | 14.952 |
| phoenix | 28706 | 2023-07-29T20:53:55.753000+00:00 | 13.325 | 10.860 |
| phoenix | 28828 | 2023-08-06T17:40:07.586000+00:00 | 10.102 | 19.065 |
| phoenix | 28909 | 2023-08-11T23:22:47.462000+00:00 | 15.824 | 18.664 |
| atlanta | 27835 | 2023-06-03T17:17:40.910000+00:00 | 11.709 | 9.843 |
| atlanta | 27896 | 2023-06-07T15:39:07.020000+00:00 | 10.055 | 19.712 |
| atlanta | 27916 | 2023-06-08T22:58:37.519000+00:00 | 17.376 | 10.726 |
| atlanta | 28145 | 2023-06-23T17:12:53.787000+00:00 | 11.562 | 20.511 |
| atlanta | 28598 | 2023-07-22T21:46:19.714000+00:00 | 16.042 | 13.485 |

Both pilot cities use Collection 2, including matching-granule wideband EmisWB, LST and QA layers. Every scene/layer must share the exact native 70m grid. The intended final 15-degree rule is not claimed for this inherited 25-degree precision sample. View and relative azimuth completeness remains unresolved for expanded-geometry claims; this is recorded rather than silently treated as complete.

The complete metadata audit reconciled every CMR page and hit count for Collections 2 and 3 in Phoenix, Atlanta and Charlotte. Reapplying the old June–September 2018–2025 filter exactly reproduced 2,600 Phoenix and 4,367 Atlanta granules; no old identifiers were missing. Mission-wide counts are larger because they include other months. Collection 3 does not yet provide consistent historical coverage for the intended study years. The two-city pilot uses Collection 2 throughout, and the expansion product decision remains open.

For spatial ownership, only whole native footprints inside their canonical 100km MGRS core and UTM longitude zone are retained. Cells crossing a seam are excluded; LST is never interpolated. Scene revisions are selected deterministically, same-tile scenes are merged with the frozen conservative cloud/water rule, and surviving duplicate native identities are prohibited. The accompanying count ledger separates raw scene observations, buffered/seam cells rejected, QA-valid unique cells and complete paired-model cells. Multiplying cell counts by 4,900 gives native footprint area; these categories should not all be interpreted as overlap removals.

Census polygons required make_valid topology repair in Phoenix and Atlanta. Equal-area changes were approximately −6,996 m² and −5,446 m² respectively, each less than 0.001% of the corresponding urban area. Original source geometries are preserved. Source geometry and projected geometry are repaired before operations; no simplifying buffer is applied.

Canopy is area-averaged only where the full contributing 30m support is valid and stable, within 1e-6 numerical coverage tolerance. Known-case tests verify area means, metadata scaling, fill values, scene choice, paired masks and seam ownership. Impervious 2021 validity is taken from its companion land-cover grid because the inherited file uses zero for both valid zero imperviousness and nodata. Annual NLCD 2024 and the inherited 3DEP snapshot are retained for matched context. Buildings use a 10m presence raster followed by area averaging, an approximation to exact vector fractions. Context dates differ from the 2023 thermal sample and must remain explicit in later sensitivity work.

A brief optional high-resolution canopy check found Phoenix’s published 2022 canopy summaries at census-tract level and an Atlanta 2018 canopy report. A downloadable, licensed ≤1m canopy layer with suitable dates and coverage was not verified in that brief check, so no validation statistics or replacement primary canopy product are claimed. Sources: [Phoenix canopy layer](https://maps.phoenix.gov/pub/rest/services/public/Shade_Study_Data_CMO_OHR/MapServer/1), [Atlanta canopy report](https://geospatial.gatech.edu/AtlantaUTC/2018FinalReport.pdf). This is not a pilot dependency.

The emitted-energy input follows the [ECOSTRESS Version 2 guide](https://lpdaac.usgs.gov/documents/1574/ECOL2_User_Guide_V2.pdf). Microsoft footprint release and varying imagery vintages are documented by the [producer](https://github.com/microsoft/USBuildingFootprints). Exact query records, export manifests, download checksums and selection freezes are under docs/v2/v6_2/execution and the pilot raw-input directory.
