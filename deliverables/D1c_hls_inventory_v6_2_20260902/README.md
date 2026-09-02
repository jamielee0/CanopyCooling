# D1c HLS V2 catalogue inventory

This package queries public NASA CMR metadata for `HLSL30.002` and `HLSS30.002` around the frozen 15-degree D1b candidate thermal passes. It opens no HLS raster, optical value, ECOSTRESS LST value, or v6.2 coefficient.

Catalogue-level pairs are timing potential only. The next step is to retrieve Fmask for the deduplicated selected acquisitions in `tables/hls_fmask_download_plan.csv`, measure usable urban-block coverage, and then rerun the frozen D1c rule. The inherited centered Sentinel-2 object remains prohibited as the final exposure or placebo.
