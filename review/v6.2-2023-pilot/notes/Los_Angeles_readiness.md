# Los Angeles: readiness and sample limitations

The bounded extension processed six additional Phoenix passes. It did not run a corrected Los Angeles Stage 1 model.

Available locally: seven annual Science TCC rasters (2019–2025), the frozen Census urban-area boundary, a 3DEP elevation raster, a 2024 Annual NLCD raster, acquisition metadata, and historical geometry/cloud/weather audits. These are useful inputs, not evidence that the complete paired LA model has run.

The inherited geometry-audited 2023 table has fourteen unique LA candidates: twelve satisfy the pilot's ≤25° p95 angle and ≥0.95 geometry-coverage condition. This is a previously screened frame, not the complete catalogue. The fresh CMR query finds 72 distinct intersecting June–September 2023 orbit opportunities, including eight at 15:00–18:00 apparent solar time, before geometry and full valid-cell screening.

The existing cloud audit is particularly relevant: the 5 June candidate around 10:57 solar time has a clear-domain fraction of only 0.000864; the 11 June UTC candidate near 16:37 has zero; the 14 June candidate near 14:56 has 0.193. Other afternoon passes have much better coverage. Counts alone therefore exaggerate useful time support. Cloud-screen summaries in `candidate_city_screen.csv` are a separate 300-block-point screen and must not be confused with these full-domain historical fractions.

Next LA work: complete a matched, provenance-checked imperviousness/validity and building-fraction input bundle; acquire consistent paired Collection 2 LST/QC/cloud/water/EmisWB for a nonthermally selected batch; fit the same pooled model; report every selected pass's support/precision or explicit failure; and inspect the pass-level plot before any time fit. Do not quietly omit the building covariate to make LA immediately runnable. Audit registration, native-cell ownership, angle coverage and context dates before treating its results as comparable.

No new LA temperature imagery was downloaded in this extension. Afternoon cloud masks were read for the nonthermal screen. VPD remains descriptive only; the advisor's roughly 0.3 kPa LA common-support figure is a historical diagnostic, not a new LA pilot result.
