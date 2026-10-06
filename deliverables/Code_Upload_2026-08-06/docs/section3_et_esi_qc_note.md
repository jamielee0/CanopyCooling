# Section 3 ET/ESI screening and QC disclosure

Date reviewed: 2026-07-17

## What changed

Section 3 now describes the ECOSTRESS ET, ESI, and PET pixels as **screened**, not
“quality-controlled.” The exact retained-pixel condition is:

```text
isfinite(value) AND cloud == 0 AND water == 0
```

There is no retrieval-quality QA bit or flag in the inputs downloaded by this
pipeline, and no retrieval-quality QA filter is applied. The two saved Zarr
cubes and every ET/ESI/PET variable now persist this disclosure in attributes,
along with the mask conditions and a `retrieval_quality_qa_filter_applied=false`
flag.

The analysis role is also persisted as `corroboration-only`. These products are
supporting evidence and remain unsuitable as primary evidence over built-up
pixels; later use is restricted to high-tree-fraction pixels.

## Advisory ranges

| Variable | Advisory range | Behavior |
|---|---:|---|
| ET (`et`) | 0–900 W m-2 | Diagnostic flag only; never clipped or masked by this range |
| ESI (`esi`) | 0–1, dimensionless | Diagnostic flag only; never clipped or masked by this range |
| PET (`pet`) | None configured | Carried as a corroborating variable; no PET range decision is made |

The ESI upper advisory bound was corrected from 1.5 to 1.0. Range checks affect
only the per-granule `range_flagged`/`n_out_of_range` diagnostics. They are not
part of the pixel mask. A focused test retains synthetic ESI values of -0.25 and
1.25 unchanged while counting and flagging them as outside the 0–1 advisory
range.

## ETinstUncertainty is not a QA bit

`ETinstUncertainty` is the standard deviation, or ensemble spread, across the
multiple L3 JET evapotranspiration estimates. It is not a retrieval-quality QA
bit. The NASA ECOSTRESS tiled-product guide describes the standard deviation
between the estimates as the ET uncertainty: [ECOSTRESS Gridded and Tiled Data
Products User Guide, Version 2](https://lpdaac.usgs.gov/documents/1655/ECO_L1C-4_Grid_Tile_User_Guide_V2.pdf).

This pipeline does not download or use `ETinstUncertainty`. The cached ET input
inventory contains 356 `PTJPLSMinst`, 356 `cloud`, and 356 `water` files, and
zero `ETinstUncertainty` files. The absence and non-use are recorded in the cube
and variable attributes.

Product identities: [ECO_L3T_JET.002](https://doi.org/10.5067/ECOSTRESS/ECO_L3T_JET.002)
and [ECO_L4T_ESI.002](https://doi.org/10.5067/ECOSTRESS/ECO_L4T_ESI.002).

## Why the screening values did not intentionally change

The earlier implementation supplied an all-zero artificial QA array to the
Section 2 mask helper. Because zero is the accepted QA code, that expression
reduced to the same finite/clear/land condition shown above. Section 3 now uses
its own direct three-condition helper so the code no longer implies that a real
retrieval-quality QA band exists. No range condition was added to that helper,
and the resampling/mosaicking logic was not changed.

## Offline rebuild evidence

The ET and ESI products were rebuilt from the existing raw files with download
disabled. The rebuild found 356 primary ET tiles and 356 primary ESI tiles and
produced both 45 x 1,155 x 1,339 cubes. The saved attributes were read back from
Zarr and confirmed to contain the exact screening expression, no-QA flag,
advisory-only policy, corroboration-only role, and ETinstUncertainty disclosure.

| Evidence | ET | ESI | PET |
|---|---:|---:|---:|
| Finite cube cells, before | 36,048,216 | 36,048,216 | 36,048,216 |
| Finite cube cells, rebuilt | 36,048,216 | 36,048,216 | 36,048,216 |
| Minimum, before / rebuilt | 0 / 0 | 0 / 0 | 0 / 0 |
| Maximum, before | 654.1973191864578 | 1.0 | 759.2995393713963 |
| Maximum, rebuilt | 654.1973191864640 | 1.0 | 759.2995393713801 |
| Mean, before | 59.25860443226622 | 0.22555388886152525 | 243.51995212994572 |
| Mean, rebuilt | 59.25860443226619 | 0.22555388886152516 | 243.51995212994560 |

Both granule reports also reproduced exactly: 356 rows, 89 near-empty tiles
dropped, zero range-flagged tiles, and 84,924,311 valid source-grid pixels for
each product. The rebuilt ESI cube contains zero finite cells outside 0–1. The
overpass table contains 66 rows with 45 ET–LST and 45 ESI–LST pairings.

A strict logical-array SHA-256 comparison was attempted. The regenerated hashes
were not byte-identical to the pre-change cubes. The extrema changed by at most
1.62e-11 and the means by at most 1.2e-13, while shapes, finite counts, minima,
and report decisions were unchanged. Therefore this review records numerical
equivalence at the displayed precision, not byte identity. The mask-equivalence
test and code path establish that the disclosure/range changes do not add a
pixel-removal or clipping operation.

## Review checklist

- `src/section3_ecostress_et_esi.py`: exact mask helper, corrected ESI range,
  truthful long names, persistent attributes, and one disclosure warning per
  processed product.
- `src/test_section3_ecostress_et_esi.py`: mask polarity, non-clipping range
  behavior, metadata contract, and explicit non-download of
  `ETinstUncertainty`.
- `python -m py_compile` passed for the implementation and focused test.
- The Section 3 focused self-test completed with all checks passing.
- The offline cached-data rebuild completed for ET and ESI, and saved metadata
  was read back successfully.
