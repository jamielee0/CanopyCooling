# Miami-excluded four-city sensitivity

**Prepared:** 2026-08-17
**Status:** `SENSITIVITY_ONLY / NO FROZEN ARTIFACT MODIFIED`
**Scope:** historical nonthermal counts only. No temperature/LST value, holdout, Task-2
result, or 2026 record was opened.

## Why this exists rather than an edit

The source guide `StepByStep_Guide_Urban_Tree_Cooling.docx` requires five cities but names
none of them; the strings `Miami` and `Denver` do not appear in it. The legacy pilot guide
named four (Phoenix, Los Angeles, Atlanta, Minneapolis–St. Paul). D0003 filled the fifth
slot with Miami on hydroclimatic-spread grounds. The feedback objects that Miami was never
in the declared pool.

Miami is **already excluded from every forward-looking artifact**. The Gate-3 prospective
panel, the Gate-4 high-demand audit, and the Gate-5 time-of-day audit all contain exactly
Atlanta, Denver–Aurora, Minneapolis–St. Paul, and Phoenix. Miami appears in the Gate-3
phenology table only as the record of it being screened out
(`PRIMARY_SCREEN_INCOMPLETE`), and is barred by D0065 (exploratory) and D0067 (cannot
supply the four-city minimum).

Miami therefore survives only in the **historical reconciliation**, and it is not removed
from those artifacts, for three reasons:

1. The feedback asks to reconcile **2,968 records to the final 102**. Those are the
   reviewer's own numbers, taken from the report they read, and they are five-city numbers.
   Silently redefining them to 2,635 and 94 would answer a question nobody asked and make
   the reconciliation unverifiable against the document that requested it.
2. D0078 binds all six first-four-items files by SHA-256 and D0084 binds the closeout.
   Editing any of them voids the audit chain that makes the packet checkable.
3. The decision log is append-only by D0001, and the Gate-0 amendment requires changes of
   this kind to be reported as "a named sensitivity or a new prospective profile" rather
   than merged silently into an existing estimand.

This file is that named sensitivity.

## Result

Removing Miami does not change the finding. The cell the study stopped on is unaffected.

| Quantity | Five-city | Miami | Four-city |
|---|---:|---:|---:|
| Physical city–orbit observations | 2,968 | 333 | 2,635 |
| Daytime 10–18 local solar | 1,055 | 120 | 935 |
| Geolocation usable | 1,017 | 97 | 920 |
| Metadata and obstruction screen | 942 | 91 | 851 |
| Archive available, pre-geometry | 911 | 90 | 821 |
| Geometry p95 ≤ 20° and coverage ≥ 0.95 | 219 | 16 | 203 |
| Early/late stratum eligible | 102 | 8 | 94 |
| Pass-equivalent sum, 219-panel | 159.087084 | 12.444243 | 146.642841 |
| Pass-equivalent sum, 102-panel | 72.689029 | 6.325614 | 66.363415 |

### Condition cells, physical passes

| Demand | Antecedent | Five-city | Miami | Four-city |
|---|---|---:|---:|---:|
| Low | Wet | 18 | 0 | 18 |
| Low | Middle | 6 | 1 | 5 |
| **Low** | **Dry** | **8** | **0** | **8** |
| Middle | Wet | 15 | 1 | 14 |
| Middle | Middle | 13 | 0 | 13 |
| Middle | Dry | 4 | 0 | 4 |
| High | Wet | 34 | 2 | 32 |
| High | Middle | 53 | 7 | 46 |
| High | Dry | 68 | 5 | 63 |

**The low-demand/dry cell is identical in both panels: 8 physical passes and 0.552699
pass-equivalents.** Miami contributed nothing to it. The corner that stopped the study was
never Miami's to fill, and removing Miami neither improves nor worsens it.

Miami's 16 retained passes are concentrated in the high-demand row (14 of 16), which was
already the best-sampled part of the grid. Its single low-demand pass sits in the middle
wetness cell with a pass-equivalent of 0.001184, i.e. effectively fully clouded.

## What this does not do

- It does not supersede R0015 or its STOP, or any Gate-1 through Gate-8 result.
- It does not select or freeze a city set. A prospective four-city restriction requires a
  new append-only decision-log entry, not this file.
- It does not revise the first-four-items packet or the feedback closeout.

## Reproduction

`four_city_sensitivity.csv` in this directory, derived by subtraction from the sealed
Gate-1 artifacts:

- `G1_OBSERVATION_RECONCILIATION/attrition_breakdown.csv` (city dimension)
- `G1_OBSERVATION_RECONCILIATION/pass_quality_219.csv` (per-pass clear/domain weights)
- `G1_OBSERVATION_RECONCILIATION/within_city_wet_dry_support.csv` (per-city condition cells)
