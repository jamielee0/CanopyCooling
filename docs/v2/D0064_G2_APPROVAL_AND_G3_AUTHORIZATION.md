# D0064 — Gate 2 approval and Gate 3 authorization

## Status

`FROZEN / USER-APPROVED G2 / G3 NONTHERMAL WORK AUTHORIZED`

## Approval

On 2026-08-13, after reviewing the Gate-2 packet, the user explicitly instructed:
`approve G2 and go to G3`.

This approval binds the following Gate-2 artifacts:

- `checks.json`: SHA-256
  `842f69d5580299958dcfb424228755c42b8efc20901475a4abd605027ca71716`;
- `review.md`: SHA-256
  `fd6117e9fdaea48a5008799206122484c3cae4182ef1aa5558cc49b0f3610d89`;
- `source_bindings.json`: SHA-256
  `355d4a65430b701c0a623421651a1f82492559bf3de0a0cdd3885404e2f06c4f`;
- generator: SHA-256
  `5e878d1a65e18bc5ee64f773e261c6bb6edc6310dd9123e16bfde86f531c634d`;
  and
- runner: SHA-256
  `9310524894cf1ef5b6fad6c546294488a00d0cca9d4c87f9cf7e8a6a7fc3253e`.

The approval accepts Gate 2's conclusion that 30-day accumulated precipitation is the
cleaner primary Gate-3 wetness candidate; 60-day precipitation remains a window
sensitivity, days since at least 5 mm rain remains a right-censored diagnostic, and
`P - ET0` remains sensitivity-only.

## Authorized scope

Gate 3 may use only 2018–2025 nonthermal metadata, weather, optical vegetation-index,
geolocation, solar/view geometry, cloud-quality, tree-mask, reference-mask, and related
provenance inputs to select a prospective city, season, and view-angle design. Historical,
date-bounded metadata searches and nonthermal quality/geometry reads needed for Denver,
Sacramento, shoulder seasons, and the frozen angle audit are authorized.

Gate 3 must stop for human review. Gate 4 and later gates, Task 2, holdout selection,
temperature/LST access, thermal outcomes, and every 2026 query or science record remain
unauthorized.
