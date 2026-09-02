# D1a parsimonious demand–geometry sensitivity

**Non-binding sensitivity ruling: DROP**

This user-requested sensitivity does not replace the controlling D003 DROP. It uses only the primary ≤15° near-nadir set; adjusts VPD for solar zenith, view zenith, and cyclic day of year; and does not require azimuth completeness. Temperature-only and vapour-pressure-only additions are interpretation checks, not vetoes.

| City | Specification | n | VIF | Condition index | Nonlinear R² | Residual SD (kPa) | Common width (kPa) | Primary pass |
|---|---|---:|---:|---:|---:|---:|---:|---|
| phoenix | primary_time_geometry | 19 | 1.036 | 5.105 | -0.582 | 2.289 | 2.417 | yes |
| phoenix | plus_air_temperature_only | 19 | 48.323 | 15.920 | 0.938 | 0.454 | 2.417 | non-vetoing |
| phoenix | plus_actual_vapour_pressure_only | 19 | 7.139 | 11.524 | 0.671 | 1.043 | 2.417 | non-vetoing |
| los_angeles | primary_time_geometry | 27 | 2.086 | 3.901 | 0.290 | 0.816 | 0.300 | no |
| los_angeles | plus_air_temperature_only | 27 | 14.091 | 9.922 | 0.884 | 0.330 | 0.300 | non-vetoing |
| los_angeles | plus_actual_vapour_pressure_only | 27 | 2.426 | 4.392 | 0.317 | 0.799 | 0.300 | non-vetoing |

## Interpretation

Parsimonious support criteria still fail in at least one city; D003 remains unchanged.

Phoenix passes every binding parsimonious criterion. Los Angeles fails only the common-support-width floor: 0.300 kPa observed versus 0.500 kPa required. Therefore the cross-city sensitivity remains DROP, but the result is a near-pass rather than the structural non-estimability found under the controlling full design.

No ECOSTRESS LST value or new v6.2 coefficient was opened. Historical pass evidence remains provenance-only and is not declared to be the v6.2 study sample.
