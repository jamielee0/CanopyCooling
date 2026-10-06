# Urban Tree Cooling v6.2 initial package — 2026-09-02

This package closes the pre–Gate A checks requested for the first delivery. Start
with `one_page_summary.pdf`; use `asset_inventory_and_package_index.xlsx` for the
per-file inventory and detailed package map.

## Current ruling

Do **not** begin Gate A under the current frozen design. The official Science TCC
screen found zero of 13,509 candidate block-passes meeting the frozen `p10–p90 >=
0.20` canopy-span requirement; the observed maximum was 0.18410. Because this was
an optimistic nonthermal screen, a thermal-complete mask cannot create an eligible
block-pass. No conditional thermal Stage 1 rerun was performed.

The VPD branch is **inactive on hold**, not dropped. The binding full-nuisance check
fails both cities; the nonbinding parsimonious sensitivity passes Phoenix while Los
Angeles misses only the common-support-width floor (0.300 versus 0.500 kPa). A
supervisor keep/drop/amend ruling is still required before the branch can activate.

The lead-lag timing provenance is now repaired with exact HLS V2 dates and IDs.
Fmask screening verifies 41 of 110 pass-window-sensor pairs, but neither city has a
season window meeting every frozen 70% year-sensor stratum rule. The diagnostic
therefore remains exploratory because confirmatory support fails, not because timing
is unobservable.

## Data boundary

The verified inventory contains 149 HLS Fmask files, 14 Science TCC files, and two
3DEP files (165 files; 800,091,676 bytes). Every file has a local SHA-256. The 16
Drive-hosted TCC/3DEP files also match Google MD5 metadata. No new thermal or HLS
reflectance values were opened for acquisition or the TCC screen.

`checksums.sha256` covers the package files; `referenced_artifacts.sha256` covers the
files named by the package index, including files inside indexed evidence directories.
Workbook preview PNGs are temporary visual-QA artifacts and are intentionally excluded.
