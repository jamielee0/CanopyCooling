# Section 8 ACS5/TIGER vintage and provenance note

## Decision

The Phoenix pilot is pinned to matching **2024 ACS 5-year** and **2024
TIGER/Line** vintages for its block-group neighborhood layers.

| Input | Pinned value | Release / effective date | Original access date |
|---|---:|---|---|
| ACS 5-year detailed tables | 2024 vintage, representing 2020-2024 | Released 2026-01-29 | 2026-06-12 |
| TIGER/Line block groups | 2024 vintage | Released 2024-09-25; boundaries and names as of 2024-01-01 | 2026-06-12 |

Official Census references:

- [2024 ACS data release](https://www.census.gov/programs-surveys/acs/news/data-releases/2024/release.html)
- [2024 ACS release schedule](https://www.census.gov/programs-surveys/acs/news/data-releases/2024/release-schedule.html)
- [2024 TIGER/Line files](https://www.census.gov/geographies/mapping-files/2024/geo/tiger-line-file.html)

The access dates above come from `data/manifest.csv`; they are not the local
rebuild date. The exact request/download URLs and raw-file SHA-256 checksums are
written to `data/interim/section8_vintage_provenance.json`.

## What changed

Previously, `fetch_block_group_geometries(year=...)` accepted a year but used a
TIGER URL and ZIP filename constructed once from the module's default year. A
caller could therefore request another ACS vintage while silently reading 2024
boundaries and labeling the manifest with the requested year.

Section 8 now:

1. Builds the TIGER URL and filename from the requested year at call time.
2. Checks the ACS5 and TIGER/Line years before any neighborhood processing.
3. Rejects different years, and production runs reject any pair other than the
   pilot's pinned 2024/2024 contract.
4. Adds these fields to `neighborhood_blockgroups_32612.parquet`:
   `acs5_vintage`, `acs5_period`, `acs5_release_date`,
   `tiger_line_vintage`, `tiger_release_date`, and
   `tiger_boundaries_as_of`.
5. Writes `section8_vintage_provenance.json` with the exact credential-free ACS
   request URLs, the exact TIGER ZIP URL, official release pages, release and
   effective dates, original access dates, raw filenames, manifest source text,
   and checksums. Census API keys are deliberately never written to provenance.

## Rebuild and review

The safe local rebuild uses the already checksummed raw inputs and performs no
network download:

```text
python src/section8_neighborhood_tree.py \
  --parts acs,svi,grid --skip-download \
  --acs-year 2024 --tiger-year 2024
```

Reviewers can verify the change in three places:

- the constants, URL builders, and validation guard in
  `src/section8_neighborhood_tree.py`;
- the 2023/2024 URL and mismatch-rejection checks in
  `src/test_section8_neighborhood_tree.py`;
- the resulting JSON and Parquet vintage fields in `data/interim/`.

## Verification outcome (2026-07-17)

The raw-file-only rebuild completed with 2,806 block groups and no downloads. A
second consecutive rebuild produced the same three SHA-256 hashes and arrays
(zero changed cells), so the current outputs are internally deterministic in the
tested `urbanv2` runtime.

The current files are not byte- or value-identical to the artifacts that existed
before this remediation. The code change does not intentionally alter source
records or rasterization rules, so this is recorded as a rebuild/runtime
difference rather than silently treated as equivalence.

| Layer | Pre-remediation SHA-256 | Current stable SHA-256 | Finite-cell change | Sum change | Mean change |
|---|---|---|---:|---:|---:|
| Median income | `3a7943774e4c3ef4110850e2cc461784759162aafa7ba81978c14eab0d8ea024` | `c71689bf0be935a1fa2f074ad7ef729ed07fa79bcf395971121ff94c3cd2e23f` | 0 | +544,228 | +0.463501754 USD |
| Percent POC | `e4321b810bc3e4a238139b14f4d4195e24accf868ac1f9b0c7096c5629c8243a` | `385a661ac76ca97174af3d6b928c55e97846f3cb1c1b18702e927614ca3e2189` | -2 | -508.250252 | -0.000290128 percentage points |
| SVI | `61cc1e257e42d0c5c5b0837e9775b3de71cef2970407b2eb311e153420ddad16` | `5de702018d7bc3cebf7a6da4d9129294924e0f6ead7beb21a2a10201272ceb09` | 0 | -2.177100 | -0.000001491 |

The ranges and grid dimensions are unchanged. Before release, products that
consume these grids should be rebuilt or explicitly compared against the stable
current hashes; the provenance remediation itself should not be used to claim
that older downstream artifacts came from these exact bytes.
