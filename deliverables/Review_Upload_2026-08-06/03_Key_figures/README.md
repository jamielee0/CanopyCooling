# Professor-specified stress-axis grid, on the v2 sample

**Status: real, canonical, non-thermal. Not a result figure — a support figure.**

## What the advisory review asked for

> "bin Delta T_cool on a two-dimensional grid: VPD anomaly on one axis and
> water-supply anomaly on the other. Use color for Delta T_cool and label cells
> with n. If the energy-to-water-limited transition is present, it should show up
> as a cooling collapse in the high-VPD/low-water corner."
> — `Advising_Review_Phoenix_Pilot.docx`, §5 "The key design choice: the stress axis"

The review also required the supply axis to be an actual water variable rather
than NDMI. In v2 that construct is the 30-day antecedent climatic water balance
`Σ(pr − eto)` (D0009), not soil moisture and not NDMI.

## What this figure is

The two axes are real and canonical. The colour axis is not, and is left empty:

| Axis | Review's v1 request | v2 realisation | Status |
|---|---|---|---|
| x | `VPD_z` | acquisition-time VPD percentile (HRRR, exact overpass time) | real |
| y | `sm_z` root-zone soil moisture | 30-day antecedent water balance percentile | real |
| colour | mean `ΔT_cool` | — | **unavailable, no LST opened** |
| cell label | n | n passes + cloud-weighted pass-equivalents | real |

Colour therefore shows **observational support**, which is the guide's Step 12
instruction ("plot the fitted surface, and plot where the data actually are,
before computing anything from it") — the F12.2 data-support map with no F12.1.

## Provenance

- Source: canonical run **R0015**, `step3_empirical_template.csv` and
  `step2_definitive_condition_counts.csv` under
  `data/processed/v2/task1/step2_definitive_l1b_geo_D0047_archive_available/tables/`.
- Cells assigned by importing `urban_cooling_v2.step02_catalog.condition_cell` —
  the same function the canonical pipeline used, not a reimplementation.
- The build script asserts that its reconstruction reproduces the published
  per-city cell table exactly (219 passes, 159.087 pass-equivalents, 34 non-empty
  city-cells) and fails if it does not.
- Estimand: the 2018–2025 five-city **archive-available** candidate population
  (D0047); 31 candidates are excluded because their L1B GEO scenes are missing
  from the LP DAAC archive.

## What it shows

1. The corner where the review predicted the cooling collapse — high demand /
   low water — is the **best-sampled cell on the plane**: 68 passes, 58.15
   pass-equivalents.
2. The two off-diagonal identification corners are 26.17 (high demand / wet) and
   **0.55** (low demand / dry) pass-equivalents, against a frozen minimum of 10.
3. So even with the colour axis filled in, a collapse observed in the red corner
   could not be attributed to low water rather than to high demand. That is the
   R0015 `STOP`, shown geometrically.
4. Per-city panels: every city's sample lies along the hot-and-dry diagonal.
   Los Angeles has zero passes in all four low/middle-demand dry and middle
   cells; Miami has 16 usable passes in total.

## F_PROF.2 — window-length robustness

The review's supply axis was soil moisture. v2 has **no soil-moisture data at all** — it was
never fetched, and the guide explicitly forbids ERA5-Land soil moisture as the water variable.
The nearest available robustness question is therefore whether the frozen 30-day antecedent
window drives the result.

`F_PROF.2` rebuilds the same grid on the 60-day window, using the same 219 passes and the same
demand axis. The build asserts that the template's frozen water axis is bit-identical to the
Step-1 30-day column before swapping, so the comparison is like-for-like.

| Condition cell | 30-day | 60-day | Minimum 10 |
|---|---:|---:|---|
| high demand / dry (predicted collapse) | 58.15 | 49.45 | clears |
| high demand / wet (identification) | 26.17 | 34.55 | clears |
| low demand / dry (identification) | **0.55** | **0.25** | fails under both |

The empty corner is not an artefact of the window choice — it is slightly worse at 60 days.
This satisfies the guide's Step-1 check "window length does not decide the answer" at the
pass level, where the count-support gate actually applies.

## Reproduce

```bash
/Users/jmlee/miniforge3/envs/urbanv2/bin/python src/build_prof_spec_support_grid.py
/Users/jmlee/miniforge3/envs/urbanv2/bin/python src/build_window_length_support_check.py
```

## Boundary

Non-canonical output path; does not alter any Task-1 or Task-2 namespace, gate
record or decision. No LST/thermal value, holdout outcome or 2026 record was
opened to build it.
