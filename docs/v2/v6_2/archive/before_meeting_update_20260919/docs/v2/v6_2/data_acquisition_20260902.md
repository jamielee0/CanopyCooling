# v6.2 pre-Gate-A input acquisition — 2026-09-02

## Status

The allowed nonthermal inputs acquired in this run are complete in the private
Google Drive folder and have now also been downloaded to the git-ignored local raw
tree for independent checksum verification:
[`Urban_Tree_Cooling_v6_2_raw_inputs_20260902`](https://drive.google.com/drive/folders/1BWuKX2np0_cTVPvVpiFCQXq5Ip6whU1R).
No ECOSTRESS LST/thermal values or HLS reflectance/index values were opened.

| Input | Drive contents | Verification |
|---|---:|---|
| HLS V2 Fmask QA | 149 GeoTIFFs; 161,907,529 bytes | Exact filename set, unique count, and aggregate bytes match the independently rehashed local set. JSON and CSV download manifests are stored in the same subfolder. |
| USFS Science TCC v2025-6 | 14 GeoTIFFs; 211,808,618 bytes | Phoenix and Los Angeles × 2019–2025; all 14 Earth Engine tasks completed. Each file contains both required Science bands. Every Google MD5 matches the downloaded file; local SHA-256 values are recorded. |
| USGS 3DEP 1/3 arc-second DEM | 2 GeoTIFFs; 426,375,529 bytes | One frozen-domain clip per city; both Earth Engine tasks completed. Both Google MD5 values match; local SHA-256 values are recorded. |

Total raster payload in Drive is 800,091,676 bytes. The folder is private and
not shared.

## Frozen source details

### HLS

- Release: HLS V2 (`HLSL30.002` and `HLSS30.002`).
- Scope: the 149 granules selected by the frozen v6.2 acquisition plan.
- Asset downloaded here: `Fmask` only.
- Full HLS reflectance bands remain deferred until Gate A because they are needed
  for the final optical exposure rebuild, not the pre-Gate-A feasibility count.

### Science TCC

- Earth Engine collection:
  `projects/gtac-data-publish/assets/TCC/Product_Version/2025-6`.
- Images: `TCC_v2025-6_CONUS_2019` through
  `TCC_v2025-6_CONUS_2025`.
- Exported bands:
  `Science_Percent_Tree_Canopy_Cover` and
  `Science_Percent_Tree_Canopy_Cover_Standard_Error`.
- The prohibited `NLCD_Percent_Tree_Canopy_Cover` band was not exported.
- Source Byte cover and UInt16 uncertainty were losslessly harmonized to UInt16
  for a two-band GeoTIFF; 65535 is reserved as NoData.
- Exports preserve the product's native 30 m Albers grid and are clipped to the
  frozen Census urban-area geometries.

### 3DEP

- Earth Engine collection: `USGS/3DEP/10m_collection`.
- Band: `elevation`, metres.
- Exports preserve the source-aligned NAD83 1/3 arc-second grid and are clipped
  to the frozen Census urban-area geometries.
- The Earth Engine catalog snapshot ends 2022-05-04. This is the exact source
  snapshot used here; it is not represented as the latest 2026 USGS tile state.

## Reproducibility files

- `data/raw/v2/hls_v2/download_manifest_fmask.json`
- `data/raw/v2/hls_v2/download_manifest_fmask.csv`
- `data/raw/v2/science_tcc_v2025_6/google_drive_export_manifest.json`
- `data/raw/v2/science_tcc_v2025_6/drive_output_verification.json`
- `data/raw/v2/usgs_3dep_10m/google_drive_export_manifest.json`
- `data/raw/v2/usgs_3dep_10m/drive_output_verification.json`
- `src/download_v6_2_drive_exports.py`
- `src/run_v6_2_tcc_export_to_drive.py`
- `src/run_v6_2_3dep_export_to_drive.py`
- `src/wait_v6_2_drive_exports.py`

The two Earth Engine manifests record the source asset IDs, bands, frozen-domain
checksum, native grids, Drive folder ID, task IDs, and final `COMPLETED` states.

The consolidated tracked inventory is
`deliverables/Initial_Package_v6_2_20260902/asset_inventory_and_package_index.xlsx`.
It records the byte count and local SHA-256 for every one of the 165 acquired files;
the 16 Drive-hosted TCC and 3DEP rows also record the matching Google/local MD5 and
the individual Drive URL. Verification-manifest SHA-256 values are:

- HLS Fmask: `62cfc4752f87062eb9f95691d48b77340c4d4fa1c329aa771d1cc89c6bb930ab`
- Science TCC: `265134308e0fcaddde9bbc9ba99f19af55a05a3e92d4f1c4b04323186f611206`
- 3DEP: `cf5e50550146672b57b3715dec099734f7cc3a0f620977d3c73407f9acb86148`

## Boundary for subsequent work

This acquisition closes the current pre-Gate-A HLS-QA, Science-TCC, and elevation
gaps. It does not authorize or supply the post-acceptance full study archive.
After Gate A approval, the final optical exposure still requires the frozen HLS
reflectance bands, and the main thermal study still requires the controlling
ECOSTRESS Collection 3 products and any remaining precipitation/context assets.
