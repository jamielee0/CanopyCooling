# Section 2 mandatory-QA `01` coverage audit

Date: 2026-07-17  
Scope: Phoenix pilot, ECOSTRESS `ECO_L2T_LSTE.002`

## Decision and interpretation

The primary Section 2 mask now retains mandatory-QA low-bit classes `00` and
`01`, while rejecting `10` and `11`. This is a professor-approved coverage
decision for a data-limited pilot. It does **not** redefine `01` as equivalent to
best-quality `00`; `01` remains disclosed as potentially degraded.

The following independent gates are unchanged:

- LST must be finite.
- The Collection-2 cloud layer must mark the pixel clear (`cloud == 0`).
- The Collection-2 water layer must mark the pixel as land (`water == 0`).
- Tiles below 1% valid study-area coverage are dropped; out-of-range LST is
  flagged rather than silently clipped.

The cube records the policy and caveat in its attributes. The granule report
records `n_valid_best_only` and `n_recovered_qc01` for every tile, so the expanded
coverage can always be separated from the strict-`00` baseline.

## Direct Section 2 before/after result

| measure | strict `00` baseline | primary `00` + `01` | change |
|---|---:|---:|---:|
| Valid granule pixels | 107,114,822 | 112,237,722 | +5,122,900 (+4.78%) |
| Tiles with any `01` contribution | — | 390 of 525 | audit only |
| Tiles surviving the 1% cutoff | 376 | 377 | +1 |
| Tiles dropped | 149 | 148 | −1 |
| Distinct LST overpasses | 66 | 66 | 0 |

Pixels recovered from `01` are 4.56% of the final primary valid-pixel total.
The one recovered tile is overpass `27836_004_20230603T184936`, tile `12SVC`:
6,371 strict-`00` pixels plus 199 `01` pixels gives 6,570 valid pixels out of
644,864 (1.0188%), moving it just above the 1% tile cutoff. No overpass was newly
created because the same overpass already had another surviving tile.

## Propagation through Sections 9–16

| downstream measure | strict `00` baseline | rebuilt `00` + `01` | change |
|---|---:|---:|---:|
| Tree pixels | 195 | 206 | +11 |
| Strict reference pixels | 1,453 | 1,457 | +4 |
| Paired block groups | 9 | 9 | 0 |
| Master-table rows | 264 | 266 | +2 |
| Represented overpasses in master table | 54 | 54 | 0 |
| Daytime primary CSI rows | 78 | 79 | +1 |
| Daytime primary pixel-model observations | 3,038 | 3,300 | +262 |

The primary conclusion is unchanged: **no robust threshold detected**. The
updated daytime candidate CSI breakpoint is 0.324, penalized PELT selects no
break, and the whole-block-group interval is 0.002–1.178. These values remain
exploratory because only four primary block groups survive.

## Visual-validation status

Section 10 regenerated a 60-pixel review sample from the final paired class-1
tree set. The automated cross-check passes 58/60 pixels (96.7%), but this is not
a human imagery judgment. The `genuine_canopy` column remains blank, so the human
agreement rate is still a manual publication gate and is not fabricated here.

## Review locations

- Policy and per-tile audit: `src/section2_ecostress_lst.py`
- Synthetic bit/polarity checks: `src/test_section2_ecostress_lst.py`
- Per-tile counts: `data/interim/ecostress_lst_granule_report.csv`
- Cube metadata: `data/interim/ecostress_lst_cube`
- Rebuilt class counts: `data/processed/section10_paired_neighborhoods.csv`
- Rebuilt analytical results: `docs/section14_results_note.md` and
  `docs/section14b_mixed_effects_note.md`
