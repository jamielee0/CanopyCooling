# 3. Corrected Stage 1 implementation

The code estimates one canopy slope for each block within each pass and uses spatial
resampling for uncertainty. Point estimates remain sealed; the sealed file itself is
not included. `implementation_only/` documents the five-pass implementation run but
uses inherited nonconforming proxies and is not the controlling scientific result.
`current_result/` is the controlling official Science TCC screen: 0 of 13,509
candidate block-passes met the frozen 0.20 canopy-span floor, so no current thermal
Stage 1 rerun or standard error was estimable.
