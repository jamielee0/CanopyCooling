# D1b — block–pass connectivity report

This package reports all eight Phoenix/Los Angeles × season-window × view-set
combinations required by the v6.2 schedule. The numerical ruling is
`HISTORICAL_PROXY_SUPPORTS_CONNECTIVITY_AT_15_DEGREES`. The single preauthorized 25° incidence widening was
`NOT USED` to obtain the ruling; the 25° panels
are still reported as required.

## Interpretation boundary

- Evidence is the inherited Collection 2 quality/geometry archive for 2019–2025,
  not the new Collection 3 v6.2 study sample.
- Only cloud and view-zenith quality layers were opened. No ECOSTRESS LST value
  and no new v6.2 coefficient was opened.
- An edge requires at least 60 clear native cells in a 1 km block. This is an
  optimistic necessary-condition screen for the later disjoint 30-tree plus
  30-background pixel floors; later canopy/background checks may remove edges.
- Phoenix's May 15–July 10 panel is an observed June 1–July 10 lower bound because
  the inherited archive contains no quality-and-weather-complete May 15–31 pass.
- The 25° incidence result is not fully geometry-admissible until view azimuth is
  resolved. D1b does not authorize Gate A or thermal processing.

## Contents

- `memo.pdf`: two-page-or-shorter decision memo.
- `tables/d1b_connectivity.csv`: the eight required numerical rows.
- `figures/d1b_map.png` and `.svg`: eligible 1 km blocks colored by pass count.
- `figures/d1b_hist.png` and `.svg`: pass-count distributions.
- `data/d1b_block_counts.csv`: block-level panel counts and modal land-use class.
- `data/d1b_edges.csv`: eligible block–pass edges.
- `data/d1b_passes.csv`: selected and edge-surviving passes by panel.
- `analysis_manifest.json`: rules, inputs, coverage notes, and fail-closed checks.
- `checksums.sha256`: hashes for every package file except itself.
