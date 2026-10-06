# 6. Raw-asset inventory

This section answers only: **which required data are in hand, and which are not?**
It does not contain acquisition code, analysis code, credentials, or raw rasters.

| Product | Status | What is in hand | What is still missing |
|---|---|---|---|
| HLS V2 Fmask | HAVE | 149 verified files for Phoenix and Los Angeles; 2019–2025; individual SHA-256 hashes | Nothing else needed before Gate A for cloud screening |
| HLS V2 reflectance | NOT YET / DEFERRED | No reflectance values were opened | Required bands would be acquired only after Gate A authorization |
| Science TCC v2025-6 | HAVE | 14 verified files; both cities × 2019–2025; canopy cover and standard error | Nothing else needed for the current canopy-span screen |
| USGS 3DEP 10 m elevation | HAVE | 2 verified city-domain files; Earth Engine snapshot ends 2022-05-04 | A newer tile-state refresh only if the supervisor requires it |
| ECOSTRESS Collection 3 thermal | CATALOGUE ONLY | Reproducible catalogue metadata; no new thermal values opened | Approved thermal products have not been acquired |
| ECOSTRESS L1B viewing geometry | PARTIAL | 762 geometry rows checked; 734 recovered reconstruction artifacts verified | Final Collection 3 geometry completeness must be resolved for the study sample |
| HRRR / weather | PARTIAL / HISTORICAL | 219 passes, 438 links, and 413 inherited assets; 10/10 sampled joins passed | Final sample-specific weather must be reacquired and frozen |
| Precipitation | NOT YET | No frozen pre-Gate A precipitation payload | Exact product, release, years, and files remain to be selected and acquired |
| Contextual data | MIXED | Frozen city/block geometry is available; inherited land-use context exists | Final land-use and other contextual releases remain to be frozen where retained |

`raw_asset_inventory.xlsx` contains only two inventory sheets: a product-level
status/gap table and per-file evidence with locations, coverage, byte counts, and
checksums where available. It records 165 verified acquired files totaling
800,091,676 bytes. Missing data are valid inventory findings; they are not presented
as if downloaded.
