# D1d official-Science-TCC canopy-span screen

**Decision IDs:** V6.2-D015 (prospective rule), V6.2-D016 (result)  
**Status:** `RETAIN_STAGE1_STOP_NO_OFFICIAL_TCC_ELIGIBILITY`  
**Access boundary:** official Science TCC cover plus native nonthermal QA, cloud,
water and height layers only. No ECOSTRESS LST or HLS reflectance value was opened.

The seven annual Phoenix Science TCC v2025-6 cover rasters were screened at their
native 30 m grid. A source cell was retained only when all seven years were valid and
the annual maximum-minus-minimum canopy fraction was at most 0.15. Its structural
canopy amount was the 2019-2025 median, area-averaged to native ECOSTRESS cells
without bilinear interpolation.

Across the five frozen D011 orbits, 13,509 block-passes had at least 60 cells under
the optimistic nonthermal mask. Zero met the frozen canopy p10-p90 span floor of
0.20. The maximum span was 0.184100 and the median was 0.066004. Because a complete
thermal mask could only remove cells, the conditional thermal rerun was not executed.
No coefficient, Stage-1 SE or required connected count was calculated.

The result confirms that the D012 failure was not an artifact of the inherited
modified-NLCD proxy. Under the current frozen 1 km-block and 0.20-span design, Stage 1
cannot proceed. Gate A remains unauthorised pending a supervisor stop, reframe, or
prospective protocol-amendment decision.

The machine-readable analysis and every input SHA-256 are in
`analysis_manifest.json`.
