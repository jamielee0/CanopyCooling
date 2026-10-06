# D0068 — Gate 3 L1B collection clarification

## Status

`FROZEN / PRE-RECHECK SOURCE CORRECTION`

D0067 named version-002 and version-003 L1B GEO identities for the bounded
archive recheck. The current official CMR collection directory contains
`ECO_L1B_GEO.002` but no `ECO_L1B_GEO.003` collection. Collection 3 currently
applies to the tiled L2T product audited at Gate 1; it is not an alternative
L1B GEO archive whose geometry can replace the exact version-002 inputs.

Therefore, before opening the new recheck result:

- perform the one date-bounded, exact-identity CMR query and bounded endpoint
  access attempt only against `ECO_L1B_GEO.002`, concept
  `C2076087338-LPCLOUD`;
- retain the existing date-bounded `ECO_L2T_LSTE.003` historical audit as
  negative contextual evidence, not as L1B recovery evidence; and
- do not invent or query an `ECO_L1B_GEO.003` identity.

This corrects only D0067's nonexistent-collection reference. Its finite retry,
resolved-unavailable, partial-identification, and fail-closed rules are
unchanged.

Official source:

- https://cmr.earthdata.nasa.gov/search/site/collections/directory/LPCLOUD/gov.nasa.eosdis
