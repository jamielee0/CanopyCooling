# v6.2 independent foundation/catalogue audit

**Run time (UTC):** 2026-08-30T12:32:40.097803+00:00  
**Overall status:** `READY_FOR_FOUNDATION_SIGN_OFF`  
**Access boundary:** metadata, nonthermal geometry, and HRRR only; no ECOSTRESS LST/temperature value was opened.  
**Sample boundary:** every inherited count below is historical provenance. None is the v6.2 study sample.

## Bottom line

The physical grouping is reproducible: the historical Collection 2 catalogue has 13,577 raw tiled records; the inherited ledger names 13,575 of those identifiers and groups them into 2,968 city–orbit observations. The independent local-solar-time calculation reproduces 1,055 daytime observations. The inherited nonthermal ledger also reproduces the later 942 metadata-screened, 911 archive-available, 219 geometry-screened, and 102 early/late counts.

The recorded live Collection 3 run contains **72 query rows representing 56 unique query URLs** and returned **18 unique granule metadata records** across the 2018–2025 historical, v6.2 primary-window, and v6.2 sensitivity-window scopes. All granules are dated 23 August 2019. Under the v6.2 primary windows, Phoenix returned **0** and Los Angeles returned **4** tiled records. This is a partial archive population, not a complete v6.2 catalogue and not a study sample. It is a dated availability result, not a permanent-absence claim.

The revision-count terminology is now formally resolved. **13,575 is the inherited ledger provenance count**: the number of distinct tiled identifiers named by that ledger, with no claim that its membership implements a latest-revision rule. **11,880 is the strict latest-build/latest-revision count** independently selected by maximum build and revision per `(city, orbit, scene, tile)`. The inherited ledger omits exactly two of the 13,577 raw rows: ECOv002_L2T_LSTE_29106_004_15TVK_20230824T161518_0710_01, ECOv002_L2T_LSTE_29106_004_15TVK_20230824T161518_0712_02. Both are Minneapolis–St. Paul orbit 29106, scene 004, tile 15TVK; the same physical pass remains represented by scene 005. Neither tiled count is the v6.2 study sample.

## Historical count reconciliation

| Stage | Independent count | Result |
|---|---:|---|
| raw_domain_intersecting_tiled_products | 13577 | PASS |
| inherited_ledger_provenance_products | 13575 | PASS |
| strict_latest_build_revision_products | 11880 | PASS |
| physical_city_orbit_observations | 2968 | PASS |
| daytime_10_18_local_solar | 1055 | PASS |
| geolocation_usable | 1017 | PASS |
| metadata_and_obstruction_screen | 942 | PASS |
| archive_available_pre_geometry | 911 | PASS |
| geometry_pass_historical_20deg | 219 | PASS |
| early_late_stratum_eligible_historical | 102 | PASS |

The tile-to-pass crosswalk retains every raw identifier and records both inherited-ledger membership and a strict native-ID latest-revision flag. Its physical pass key is city plus zero-padded orbit. Adjacent scenes and MGRS tiles never become extra atmospheric observations.

## Exclusions and archive gaps

- The two tiled identifiers above are absent from the inherited canonical ledger but do not remove the Minneapolis–St. Paul orbit-29106 physical observation.
- The historical L1B GEO gap ledger contains **31** passes. The later unified ledger contains **43** passes: the original 31 plus 12 later unavailable passes; **28** were in the old four-window bound calculation.
- No gap is zero-filled, assigned a geometry result, or counted as recovered. The 31 historical gaps are from 2020 or 2024, while every recorded Collection 3 entry is from 2019; the exact orbit comparison recovers **0** of the 43 unified gaps.

## Geometry recovery

- Geometry ledger: **762** rows.
- Checksum-bound reconstruction arrays: **734**.
- Statuses: 127 complete positive maps, 221 verified zero maps, 386 accessible but azimuth-incomplete, and 28 resolved unavailable.
- Every row's expected artifact presence, file hash, embedded city/orbit/window identity, array shape, coverage, valid-view count, view-zenith p95, and azimuth-valid fraction was independently checked. Result: **PASS**.
- The inherited 25-degree joined evidence has **52** geometry/cloud/weather-complete passes. This is design-history evidence, not the v6.2 15/25-degree sample.

## Sampled HRRR joins

The audit independently expands 219 passes to 438 floor/ceiling links and 413 unique HRRR assets. It then selects two SHA-256-ranked passes per city (10 total), recalculates cell VPD from Kelvin temperature and dewpoint, averages over the frozen city domain, and linearly interpolates to acquisition time. **10/10** sampled joins reproduce within 1e-10 kPa; cell-level VPD formula checks reproduce within 1e-12 kPa.

Formula used for each HRRR cell:

`e_s(T) = 0.6108 exp(17.27 T_C / (T_C + 237.3)); VPD = max(e_s(T) - e_s(T_dew), 0)`

## Sign-off consequence

The independent foundation/catalogue audit is ready for foundation sign-off. Every required historical, archive, geometry, and HRRR check passed. The fail-closed readiness guard passed **31/31** required checks and will make the command exit nonzero if any required check fails. The revision-count ambiguity is closed by the formal labels above, and every recorded CMR response required for offline replay is stored under the tracked `source_evidence/` directory and covered by the checksum ledger. The partial Collection 3 population remains a dated catalogue result, not a completeness claim, archive-gap recovery, or v6.2 sample. The 13,575 inherited provenance value remains in the historical record and is explicitly prohibited from becoming the v6.2 study sample.
