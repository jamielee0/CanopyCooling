# Phoenix Pilot — Master Remediation Plan

> **Historical implementation plan (completed 2026-07-17).** This file records the pre-fix
> findings and implementation instructions, so some passages intentionally describe the old
> NDMI-supply baseline. For current behavior and results, use `README.md`,
> `docs/DESIGN_DECISIONS.md`, `docs/section14_results_note.md`, and
> `docs/section14b_mixed_effects_note.md`.
>
> **Post-plan M3 override (2026-07-17):** the professor approved retaining mandatory-QA
> `01` for coverage despite its potentially degraded designation. The production policy is
> now `00`+`01` with a strict-`00` audit baseline; see
> `docs/section2_qc01_coverage_audit.md`. Later historical instructions to skip M3 when `01`
> is degraded are superseded by that explicit decision.

**Status:** implemented and retained as a historical, code-grounded plan. Every file:line anchor below was verified against the pre-remediation source at `/Users/jmlee/Documents/TreeProject/project/`. `config.py` is at the **repo root** (imported as `config`; there is no `src/config.py`). Tests are hand-rolled `check(cond, msg)` harnesses run as `python src/test_sectionN_*.py` — **not pytest**; a new test is a `def test_*()` registered in that module's `main()` `tests=[...]` list. `run_all.py` step ids are contiguous ints (`validate_registry` asserts `ids == range(len(steps))`); `--only` takes a comma list; `--from N`/`--to N` are inclusive; steps 9–14 are `network=False`. Section 4b is **not** in the registry and reads Section 9's cube, so it runs after 9 and is invoked directly.

**Step-id registration (settled — read before wiring any new module).** Two new registry modules are added this round. To satisfy `validate_registry` (`run_all.py:234`, asserts `ids == range(len(steps))`; last existing id is 14) they take **distinct, contiguous** ids:
- **`section15_response_surface.py` = id=15** (B1b; the 2-D response surface; reads `master_table.parquet`).
- **`section14b_mixed_effects.py` = id=16** (B3.2/B3.3; the pixel-level mixed model; reads `master_pixel_table.parquet`).

Register **15 before 16** so ids stay `range(0,17)`. This ordering is repeated in the B1b card, the B3.2 card, and §5 — do not let any single card silently re-use id=15 for both.

---

## 1. Executive Summary

Four blockers, in priority order:

- **B1 — Stress metric / construct validity.** The Compound Stress Index builds its "water-supply" term from `ndmi_z` (a *vegetation* index), not from water supply. Swap the supply axis to root-zone soil moisture `sm_z` (already computed, already in the Section 11 store), demote NDMI to a vegetation check, and make a 2-D VPD_z×SM_z response surface — not the scalar CSI — the primary RQ1 detector.
- **B3 — Sample size & unit of analysis.** The master table is one row per BG-mean per overpass, so pixel-nested-in-BG pseudoreplication cannot be modeled and single-tree-pixel BGs enter at full weight. Persist a pixel-level paired-difference table, fit a mixed-effects model with clustered uncertainty, and make the well-sampled subset primary.
- **B4 — Day/night pooling.** The threshold verdict pools day (+4.8 K) and night (+0.4 K, ~40% negative) overpasses, so the "flat cloud" result is partly a mixing artifact. Persist `local_hour`/`is_day`, make day-only the primary analysis, and report the day/night contrast as a first-class result.
- **B2 — z-score std floor.** `zscore()` divides by a per-pixel climatological std with only a zero/non-finite guard (`min_std=0.0`), so a tiny-but-positive std produces `|z|` in the tens-to-hundreds that flows into `ndmi_z → supply_stress → CSI`. Add a per-variable physical floor that rejects near-constant-climatology pixels to NaN.

**Core message:** treat the current outputs as a clean **Phoenix pilot**, not a null result. Land the correctness fixes (Phase A), rebuild the stress axis and the unit of analysis (Phase B), re-run Phoenix Sections 9–14 from saved interim, regenerate figures — **and only then** scale to LA / Atlanta / MSP. Do not start scale-out until Phoenix settles. None of these fixes will "unlock" a threshold the thin sample (9 paired block groups, one dominant ~171-pixel BG, median `n_good_obs`≈2) cannot support; they make the honest answer honest for the *right* reasons.

---

## 2. Guiding Principles

1. **Day-only is the primary analysis.** Night overpasses (~+0.4 K, ~40% negative) are a labelled contrast, never pooled into the headline verdict.
2. **Pixel-level modeling.** The unit of analysis is the tree pixel (carrying its BG×overpass reference-mean LST), not the BG mean. This is the only grain at which within-BG (temporal) and between-BG (spatial) variation separate. **Scope note:** this pixel grain drives the *inferential* model (B3.2). The *descriptive* 2-D response surface (F4/Section 15) is deliberately BG-mean-based (reads `master_table.parquet`) — see Principle 6 and the B1b card. The two live at different grains on purpose.
3. **Clustered uncertainty.** All CIs resample **whole block groups** (≤9 clusters), not i.i.d. rows. Model-based SEs at this cluster count are unreliable; wrap fits in a BG cluster bootstrap (wild-cluster/Rademacher as the small-cluster fallback).
4. **Supply term = soil moisture.** The water-supply axis is `sm_z` (primary) and/or SPEI; **NDMI is a vegetation check**, not the supply definition. `sm_z`'s sub-unit single-year variance is a real property, not a bug — handle it by robust rescale or by weight, not by "fixing" it upstream.
5. **Keep the honesty gate.** The verdict must remain falsifiable in both directions: a changepoint estimator that can return "no break," an agreement tolerance tight enough to reject two unstable estimates on a flat cloud, and clustered CIs that widen honestly.
6. **The 2-D response surface is the primary RQ1 detector.** It is descriptive, not inferential — it shows *where* in VPD_z×SM_z space cooling weakens and displays sparsity via per-cell `n`. It is intentionally **BG-mean descriptive** (built from `master_table.parquet`, one row per paired-BG × overpass), and is a distinct object from the pixel-level inferential model of B3.2. CSI is demoted to a secondary cross-city scalar.

**Cross-module supply/naming invariant (settle once, applies to B1a + B1b).** After this round two "supply"-named constants point at *different* variables, by design:
- **Section 12 primary supply = `sm_z`** (soil moisture): `config.SUPPLY_VAR="sm_z"`, drives `supply_stress` and the CSI, and is the y-axis of the response surface via the master-table column **`mean_sm_z_tree`**.
- **Section 13 `WATER_SUPPLY_Z_VAR == "ndmi_z"` is the vegetation *check* only.** Its master-table column is **renamed `mean_water_supply_z_tree → mean_ndmi_z_tree`**. It is not consumed by the surface or the CSI supply term; it is carried for corroboration.

State this invariant in code comments where each constant is defined so the two do not get re-merged: §12 supply = `sm_z`; §13 `WATER_SUPPLY_Z_VAR`/`mean_ndmi_z_tree` = vegetation check.

---

## 3. Execution Roadmap (dependency-ordered)

**Phase A — correctness fixes (do first; they change data, so everything downstream re-runs anyway).**
- **B2** (z-score floor) — Section 11.
- **M3** (QC bits, LST keep-mask) — Section 2.
- **M4** (PRISM exact-date match) — Section 9.
- **M6** (drought band-date resolution) — Section 7.
- **M1** (reference set: impervious floor, drop NLCD 21) — Section 10.
- **M2** (pre-committed canopy threshold) — Section 10.
- Land **M1+M2 together** (one `--from 10`).

**Phase B — analysis redesign (after Phase A data settles).** *Ordering constraint: within Phase B, B4 lands before B3.2 because B4 persists `local_hour`/`is_day` as Section 13 columns that B3.2 reads (single source of truth — B3.2 does not re-derive them).*
- **B1a** (supply term → `sm_z`) + **B1b** (2-D response surface, new Section 15 = registry **id=15**) + **m3** (weight sensitivity) — Sections 12/13/15.
- **B3.1** (pixel table) + **M5** (`sample_label` / primary subset) — Section 13.
- **B4** (day-only + persisted `local_hour`/`is_day`) + **m5** (penalized changepoint, tighter tolerance, cluster bootstrap; **m5 owns the `bootstrap_breakpoint` cluster edit**) — Sections 13/14. **B4 must land before B3.2.**
- **B3.2** (mixed-effects model, new Section 14b = registry **id=16**) + **B3.3** (cluster bootstrap — *consumes* the m5 `bootstrap_breakpoint` edit, does not re-implement it) — pure analysis on the pixel table.
- Land **B3.1+M5 together** (one `--from 13`); land **B4+m5 together** (one `--from 13`).

**Re-run Sections 9–14 from saved interim** after Phase A, then again after Phase B (Section 5).

**Figures** (Section 7): regenerate F1–F10, including the four-panel paper figure.

**Phase C — scale-out.** Do **NOT** start until Phoenix settles. LA / Atlanta / MSP re-use the same modular pipeline with city-specific config; CSI is retained precisely as the cross-city scalar.

**Minors with no data impact** (m1 ET/ESI docs, m4 ACS/TIGER vintage held at 2024): land any time; no re-run.

---

## 4. Detailed Fix Cards

> Ordered BLOCKERS FIRST (B2, B1, B3, B4), then M1–M6, then m1–m5. Each card carries file:line anchors, concrete steps, tests, re-run impact, acceptance criteria, and human-decision flags.

---

### B2 — z-score standard-deviation floor  `[BLOCKER]`

**Finding.** `section11_anomalies.py::zscore()` divides an anomaly by a per-pixel climatological std with only an exactly-zero/non-finite guard (`min_std=0.0`, never overridden). A tiny positive `clim_std` (dense evergreen canopy, persistently dry bare soil, one-sided season edges) passes and yields `|z|` in the tens-to-hundreds, inflating `ndmi_z → supply_stress → CSI`. Section 12's record-level guard (`0.7<std<1.3`, span beyond ±1) is far too tolerant to catch a handful of extreme pixels.

**Where.**
- `section11_anomalies.py:121-132` — `def zscore(observed, normal, std, min_std=0.0)`; `bad = ~np.isfinite(s) | (s <= float(min_std))` at `:130`; `min_std` passed at **neither** call site.
- `:280` — call site 1, inside `compute_era5_zscores` (def `:233-236`); `std = np.nanstd(sel, axis=0)` at `:268`, native ERA5 units, pre-regrid; serves **both** `vpd` and `sm` via the `TEMPORAL_VARS=("vpd","sm")` loop at `:452-456`; regrid at `:457-459`.
- `:476` — call site 2, NDMI; `ndmi_cstd` loaded from Section 4b store (`:390`), 70 m grid, dimensionless.
- `:485-487` NDMI log; `:503-504` `meta` dict; `:583-608` `record_zscore_stats`; `:1119-1127` `_meta_from_attrs` (verify-only, will not carry `n_floored`).
- `config.py` — no std floor exists today.
- Tests: `test_section11_anomalies.py:120-146` (`test_anomaly_and_zscore`, `test_zscore_degenerate_std`), `:187-215` (NDMI temporal, hard-code `clim_std=0.05`), `:278-285` (`test_module_constants`), `:290-306` (`main()` registry).

**Design decision.** Floor = **reject-to-NaN** (matches existing `bad→NaN`), not clip-the-std. Clipping fabricates a moderate z from an untrustworthy pixel and keeps it. See human-decision flags.

**Steps.**
1. Extend `zscore()` (`:121-132`) with a real floor + an opt-in count flag so the four single-array call/test sites keep working:
   ```python
   def zscore(observed, normal, std, min_std=0.0, *, return_n_floored=False):
       a = anomaly(observed, normal)
       s = np.asarray(std, dtype="float64")
       nonfinite = ~np.isfinite(s)
       floored = np.isfinite(s) & (s <= float(min_std))
       bad = nonfinite | floored
       z = a / np.where(bad, np.nan, s)
       return (z, int(floored.sum())) if return_n_floored else z
   ```
   At `min_std=0.0` behavior is byte-for-byte preserved.
2. Add per-variable floors to `config.py` near `:110` (values are proposals pending the histogram in flags #1):
   ```python
   MIN_STD_NDMI: float = 0.02   # dimensionless NDMI
   MIN_STD_VPD:  float = 0.05   # kPa, native ERA5
   MIN_STD_SM:   float = 0.005  # m3 m-3, native root-zone SM
   ```
3. Thread through `compute_era5_zscores` (add `min_std` kwarg, accumulate `n_floored` across the overpass loop, return it); select the per-var floor at the `:452-456` caller loop (`config.MIN_STD_VPD if var=="vpd" else config.MIN_STD_SM`). Flooring is applied to the native pre-regrid std — the only correct place, since no re-standardization happens post-regrid and NaN propagates through `reproject_match`.
4. Pass the NDMI floor at `:476` (`min_std=config.MIN_STD_NDMI, return_n_floored=True`); log at `:485-487`; add `ndmi_n_floored` to `meta` (`:503-504`). Verify-only path (`:1119-1127`) will lack it — acceptable; counts live in build-time logs.
5. (Optional) add a max-|z| line to `record_zscore_stats` (`:583-608`) to back a smoke assertion.

**Tests.**
- Extend `test_zscore_degenerate_std` with floor + count cases (below floor → NaN counted; `std==min_std` → NaN via `<=`; above floor divides, not counted).
- New `test_zscore_min_std_floor_caps_extreme_z` (the B2 lock): unfloored tiny std blows up (`|z|>100`); floored → NaN; `nf` counted; no surviving `|z|` in the hundreds. **Register in `main()`.**
- Add a one-line comment to the two NDMI temporal tests (`:187-215`) noting they assume `MIN_STD_NDMI < 0.05`.
- Extend `test_module_constants` to assert the three floors are positive floats.

**Re-run impact.** Changes `section11_zscores_70m.zarr` → re-run **11→12→13→14** (`python src/run_all.py --from 11`). Section 12 reads the finished store (`_assert_inputs_are_zscores` still passes both ndmi guards). Section 13 `_zonal_at` is finite-only and `row_emittable` gates on **LST**, so row count is unchanged; only z zonal means gain NaNs. Steps 0–10 unaffected.

**Acceptance.** `grep min_std= section11_anomalies.py` shows the floor at both former call sites; new + extended tests pass; 11 re-run logs per-variable floored counts; `ndmi_z` record std stays ~1 while max|z| drops to low double digits; Section 12's both ndmi guards and the vpd straddle-0 check still pass.

**Human-decision flags.** (1) Floor **values** are judgment calls — run a one-off histogram of the three `clim_std` fields already in the store and set each at the low-tail degenerate spike (~1st pctile) before committing numbers; plumbing is value-independent. (2) Reject-to-NaN vs clip-the-std. (3) Per-var routing is mandatory (three unit systems). (4) NDMI floor must stay `< 0.05` or the two temporal tests break.

---

### B1a — Supply term must be soil moisture, not NDMI  `[BLOCKER]`

**Finding.** The CSI "water-supply" term is built from `ndmi_z` (vegetation greenness/moisture), while the framing calls it "water supply." NDMI is a mediator/canopy-condition variable, not a water-supply forcing. Use root-zone soil moisture `sm_z` (already in `section11_zscores_70m.zarr`) as the supply term; keep `ndmi_z` as a vegetation check.

**Cross-module naming invariant (see §2).** After this card: §12 primary supply = `sm_z` (`config.SUPPLY_VAR`), consumed by `supply_stress`/CSI/response-surface; §13 `WATER_SUPPLY_Z_VAR=="ndmi_z"` (column renamed `mean_ndmi_z_tree`) is the **vegetation check only**. Two "supply"-named constants, two different variables, by design.

**Where.**
- `section12_compound_stress.py:57` — `SUPPLY_Z_VAR = "ndmi_z"`.
- `supply_stress()` `:80-87` (`np.maximum(-z,0.0)` — sign-correct for any wetness z).
- `load_zscores()` `:135-145`; presence check tuple at `:142`.
- Build read `:211`, applied `:214`, combined `:215-216`.
- `_assert_inputs_are_zscores()` `:148-183` — supply-std band `0.7<nd_std<1.3` (`:161`) and span `nd_min<-1 & nd_max>1` (`:167`). **The trap:** `sm_z` record std ≈0.45 (documented, real single-year property; surfaced at `section11_anomalies.py:603-607` and `:884-885,898-904`) is below 0.7, so the guard as written rejects raw `sm_z`.
- `sm_z` stored via the same VPD/SM temporal LOYO path (`section11_anomalies.py:452-464`, stored `:588,:621,:1018`).
- SPEI alternative: `spei30d`/`spei90d` are per-pentad in `analysis_cube_70m.zarr` (`section9_harmonize.py:91,412`), **not** in the z-store.

**Steps.**
1. Add a supply switch to `config.py` after `WEIGHT_SUPPLY` (`:118`): `SUPPLY_VAR="sm_z"`, `SUPPLY_ROBUST_RESCALE=True`.
2. Repoint `section12:57`: `SUPPLY_Z_VAR = config.SUPPLY_VAR`; add `CHECK_Z_VAR = "ndmi_z"`. Add an inline comment recording the invariant (§12 supply = `sm_z`; `ndmi_z` is the vegetation check). Extend the `load_zscores` presence loop (`:142`) to `(DEMAND_Z_VAR, SUPPLY_Z_VAR, CHECK_Z_VAR)`.
3. Robust-rescale `sm_z` before `supply_stress` (do not raw-divide). Add `robust_unit_scale(z)` after `:88` (divide by IQR/1.349; sign/NaN preserved; `<2` finite → unchanged). Apply in `build_csi_dataset` at `:211-214` behind `config.SUPPLY_ROBUST_RESCALE`. Rationale: raw `max(-sm_z,0)` with std≈0.45 silently de-weights supply against the ~unit-std demand term.
4. Generalize `_assert_inputs_are_zscores()` (`:148-183`) to branch on `SUPPLY_Z_VAR`: for `sm_z` accept `0.3<std<1.3` on the raw stored field and require `min<0<max`; keep the tight NDMI band for the check; add a post-rescale assertion `0.7<nanstd(supply_z)<1.3` in `build_csi_dataset`. Update the log line (`:179-183`) to name the actual supply var. Prefer refactoring the numeric core into a pure `_assert_supply_is_z(arr, var, rescaled)` helper for unit-testability.
5. Update supply annotations/labels (`:280-284,:295-298,:456-457`) per the Naming appendix; keep the data-var name `supply_stress` stable.
6. Carry `ndmi_z` as the check: in `overpass_summary_table()` (`:413-426`) add `ndmi_z_check_spatial_mean`; keep it out of the `csi`/`demand`/`supply` cube so `verify_grid`'s `("csi","demand_stress","supply_stress")` assertions (`:555`) are unchanged.

**Tests.**
- Update `test_module_constants_and_weights` (`:230`) → `SUPPLY_Z_VAR=="sm_z"`, add `CHECK_Z_VAR=="ndmi_z"`.
- Update `test_supply_uses_zscore_not_raw_ndmi` (`:184`) constant to `sm_z`.
- New `test_supply_source_is_soil_moisture` (semantics + `supply_stress([-2,0,2])==[2,0,0]`).
- New `test_robust_unit_scale_restores_unit_spread` (N(0,0.45)×5000 → std∈(0.7,1.3); sign/NaN preserved; `<2` finite unchanged).
- New `test_input_guard_accepts_sm_z_rejects_raw` (via the pure helper).

**Re-run impact.** No upstream re-run (`sm_z` already stored). Re-run **12→13→14** (`--from 12`). Section 13 must re-run (`mean_csi_tree` changes).

**Acceptance.** `csi` differs from the NDMI-supply baseline; `csi>=0` holds; supply still varies in time; generalized guard passes with `sm_z`; summary carries `ndmi_z_check_spatial_mean`; tests pass; copula stub still raises.

**Human-decision flags.** DECISION 1 — supply variable (`sm_z` recommended vs `spei90d` vs augment). DECISION 2 — variance handling (robust IQR rescale vs no rescale + let m3 weights absorb vs re-standardize). CAVEAT — `sm_z` compressed variance is a **real single-year property**; do not "fix" upstream. The rename-only fallback (Naming appendix) only *documents* the gap; recommend against.

---

### B1b — Primary RQ1 detector = 2-D binned response surface  `[BLOCKER redesign]`

**Finding.** A scalar CSI collapses two physically distinct axes (demand VPD, supply SM) and then hunts a 1-D threshold the thin sample cannot support. The primary detector should be a 2-D binned response surface: ΔT_cool binned by VPD_z (x) × SM_z (y), color = mean ΔT_cool, each cell labeled with `n`. Descriptive, not inferential.

**Grain (settled).** This surface is **BG-mean descriptive** — it reads `master_table.parquet` (one row per paired-BG × overpass) and uses the BG-mean column `mean_sm_z_tree`, not the pixel table. It is deliberately distinct from the pixel-level inferential model (B3.2). Principle 6 makes the surface the "primary RQ1 detector" *as a descriptive object*; Principle 2's pixel unit governs the *inferential* model. No contradiction — different grains, stated on purpose.

**Cross-module naming invariant (see §2).** Primary supply axis = `mean_sm_z_tree` (from `sm_z`); the renamed `mean_ndmi_z_tree` is the vegetation check, not consumed by the surface.

**Where.**
- Master-table inputs (per paired-BG × overpass): x `mean_vpd_z_tree` (`section13:445,:495`); y currently `mean_water_supply_z_tree` = mean of `ndmi_z` (`:446`, from `:425`); color `cooling_advantage` (`:437`); count `n_good_obs` (`:463`)/`n_tree_valid` (`:461`).
- No binning/surface code exists. No `local_hour`/`is_day` column; `overpass_timestamp` (`:433`) is UTC (`section9_harmonize.py:528`); Arizona = MST = UTC−7, no DST.
- `report_master_table` NaN-coverage loop is at `:607-613`; the column tuple to touch is `("mean_et_tree",…,"aridity")` at **`:609-611`** (the rename must land on this full tuple, not just one line).

**Steps.**
1. Add `mean_sm_z_tree` (primary supply) and rename the check: `load_grids()` (`:278-293`) add `"sm_z"`; keep `"ndmi_z"` (`:285`); add const `SM_Z_VAR="sm_z"` near `:69`; in `build_master_table` after `:425` add `mean_sm_z,_ = _zonal_at(sm_z[t], trr, trc)`; row dict (`:444-446`) set `mean_sm_z_tree` (primary) and `mean_ndmi_z_tree` (renamed from `mean_water_supply_z_tree`); update `MASTER_COLUMNS` (`:487-503`), `COLUMN_GROUPS` (`:506-515`), and the **`report_master_table` NaN-coverage column tuple at `:609-611`** (the full `("mean_et_tree",…,"aridity")` tuple — the rename must touch this whole tuple, not just `:609-610`, else `KeyError`).
2. Add `local_hour`/`is_day` to the row dict after `:433`: `int((hour-7)%24)` and `bool(7<=...<19)`; add to `MASTER_COLUMNS`/`COLUMN_GROUPS` identifiers. **Owned by B4** (B4 is the single source of truth for these persisted columns and lands before B3.2, which *reads* them). If B4 has already landed, this step is satisfied — do not re-derive; if implementing B1b first, add them here and B4 consumes the same columns. (The 7–19 cut is a heuristic — DECISION 4.)
3. New pure module `src/section15_response_surface.py` with `binned_surface(vpd_z, supply_z, cooling, ...)` (numpy/pandas; digitize into edges, drop out-of-range and NaN pairwise, empty cells NaN/0). Default coarse edges `VPD_BINS=[-1,0,1,3]`, `SM_BINS=[-3,-1,0,1]`.
4. `plot_response_surface(...)` → `figures/section15_response_surface_vpdz_smz.png` (F4) and `..._day.png`. RdBu centered at 0 via `plot_style` (`CMAP["cooling_advantage"]`, `diverging_norm(vcenter=0)`); `pcolormesh` over edges; overlay per-cell `n` (skip `n==0`).
5. Demote CSI to secondary (docstring note in `section12`, `:1-14`); no deletion.
6. Wire Section 15 into `run_all.py` as `Step(id=15, module="src/section15_response_surface.py", outputs=(...), network=False)` **after id=14, before the id=16 mixed-effects step** (see the Step-id registration note at the top of the plan and §5); reads only `master_table.parquet`.

**Tests.** Update `test_section13_master_table.py::test_module_constants_and_schema` (`:176-197`) for the new columns; **keep** `WATER_SUPPLY_Z_VAR=="ndmi_z"` (`:183`, now the check pointer) and add `SM_Z_VAR=="sm_z"`. New `test_section15_response_surface.py`: assignment, NaN-pairwise drop, out-of-range excluded (not clamped), day filter matches `local_hour`.

**Re-run impact.** Column adds → **13→14 (+ new id=15 surface)** (`--from 13`). With B1a, run **12→13→14/15** together (`--from 12`; `--from 12` sweeps registry steps 12, 13, 14, and once registered id=15 — see §5 for the id sweep table).

**Acceptance.** `master_table.parquet` gains the four columns; `verify_master_table` still asserts one row per (neighborhood, overpass); `report_master_table` runs without `KeyError` (the `:609-611` tuple was renamed); F4 + day variant exist with per-cell `n`; day cells show larger positive ΔT_cool than night; tests pass.

**Human-decision flags.** DECISION 3 — bin edges (recommend coarse 3×3 + `n` labels). DECISION 4 — day-only primary vs pooled, and the day/night cut (ISS precessing orbit → consider emitting `local_hour` and letting the analyst choose). DECISION 5 — module (recommended) vs notebook cell.

---

### B3.1 — Persist a pixel-level paired-difference table  `[BLOCKER, enabling change]`

**Finding.** The master table is BG-mean-aggregated, so pixel-nested-in-BG pseudoreplication cannot be modeled. No mixed model can separate within-BG from between-BG variation without a pixel-grain table.

**Where.** `section13_master_table.py:382-470` `build_master_table` (`.mean()` collapse `:416-417`; per-BG index arrays from `static.attrs["tree_px_by_geoid"]`/`["ref_px_by_geoid"]` at `:390-391,:403-404`, stashed `:377-378`); `load_grids` (`:258-298`, all per-pixel grids in hand); constants `:58-60`; `run()` `:722-764`. Per-pixel indices are genuinely available: `tree_px_by_geoid = np.where(tree_mask)` at `section13:325` gives full per-pixel row/col indices per BG — so the pixel table needs no new geometry pass.

**Steps.**
1. Unit = one row per finite tree pixel, carrying that BG×overpass reference **mean** LST. `ΔT_cool_px = mean_ref_lst(BG,overpass) − lst_tree_pixel`.
2. Add `PIXEL_PARQUET="master_pixel_table.parquet"` near `:59` and `PIXEL_COLUMNS` (identifiers incl. `pixel_row,pixel_col`; outcome `tree_lst,mean_lst_reference,cooling_advantage_px`; predictors `vpd_z,ndmi_z,csi,aridity`; counts).
3. New `build_pixel_table(grids, static)` after `:470`, reusing the same `t`-loop, `.attrs` index arrays, `np.concatenate([trr,rfr])`, `_zonal_at`, and `row_emittable`. Predictors `vpd_z/ndmi_z/csi` are **per-pixel** here (the point); `aridity` stays BG-level. Non-finite predictors kept as NaN (model drops pairwise).
4. Wire into `run()` after `write_master_table` (`:754-755`); keep `master_table.parquet` as-is (additive).
5. Add `verify_pixel_table(path)` mirroring `verify_master_table` (`:684-718`): all columns present; unique (`neighborhood_id,overpass_key,pixel_row,pixel_col`); `cooling_advantage_px == mean_lst_reference − tree_lst` (atol 1e-5); `nunique<=9`; every row `n_ref_valid>=1 & n_tree_valid>=1`.
6. Register `"data/processed/master_pixel_table.parquet"` in step-13 `outputs` (`run_all.py:205`).

**Tests.** New `test_pixel_table_shape_and_identity` (tiny synthetic grids+static, hand-set `.attrs`, assert row count = Σ finite tree px over emittable BG×overpass; identity holds; multi-tree BG → multiple rows; NaN-tree row absent; 0-finite-reference emits nothing). Update `test_module_constants_and_schema` for `PIXEL_PARQUET`/`PIXEL_COLUMNS`.

**Re-run impact.** **13→14** only (`--from 13`), then the id=16 model step.

**Acceptance.** `master_pixel_table.parquet` has `Σ n_tree_valid` rows over emittable BG×overpass (dominant BG ≈171 px; eight thin BGs 1–6 each); `verify_pixel_table` passes; day `mean(cooling_advantage_px)` ≈ +4.8 K.

**Human-decision flags.** Pairing semantics (tree-pixel-vs-BG-reference-mean, recommended) vs two-level. Coordinate so the model consumes **B2-floored** `ndmi_z`.

---

### B3.2 — Mixed-effects model with crossed BG and overpass random effects  `[BLOCKER]`

**Finding.** No model separates within-BG (temporal) from between-BG (spatial) variation; the Section 14 pipeline fits a pooled model treating every row as independent.

**Where.** New `src/section14b_mixed_effects.py` (registered as `run_all.py` step **id=16**, `network=False`; **id=15 is the response surface** — do not collide), consuming `master_pixel_table.parquet` filtered to `sample_label=="primary"` (M5) and `is_day`. Does **not** overload `section14_threshold.py`.

**Dependency (settled).** B3.2 **reads** the persisted Section 13 columns `local_hour`/`is_day` — it does **not** re-derive time-of-day. B4 is the single source of truth for these columns and **must land before B3.2**. (The earlier draft's "materialize as persisted Section 13 columns so B3.2 and B4 share one field" is now the binding rule: B4 persists, B3.2 consumes.)

**Steps.**
1. Load the pixel table; **read** the persisted `local_hour`/`is_day` columns (do not recompute from timestamps); primary = `is_day & sample_label=="primary"`.
2. Mundlak/CWC within–between decomposition: for `vpd_z`, `ndmi_z` add `_bg_mean` (group mean) and `_within` (group-centered).
3. Fit crossed random intercepts via `statsmodels` variance components: `(1|block_group)` via `groups`, `(1|overpass)` via `vc_formula={"overpass":"0 + C(overpass_key)"}`. `_within` coefficients = temporal stress response purged of between-BG confounding.
4. Report both variance components + residual.
5. Handle the dominant BG (`040139412001`, ≈95% of rows, all reported): crossed intercept absorbs its mean; inverse-cluster-size weighting; leave-dominant-BG-out refit as sensitivity.
6. Emit `docs/section14b_mixed_effects_note.md` + figures (coefficients±CI, variance components, dominant-BG in/out, day vs day+night).

**Tests.** New `test_section14b_mixed_effects.py` (guard the `statsmodels` import so the file skips gracefully): `test_group_mean_centering` (pure); `test_within_between_decomposition` (recover known within slope); `test_dominant_bg_downweight`. Register in `main()`.

**Re-run impact.** Consumes B3.1's pixel table; run step **id=16** after 13. No cube/z-store recompute.

**Acceptance.** Model converges (REML) on the day-only primary pixel sample; both variance components estimable/reported; leave-dominant-BG-out and day-vs-night contrasts in the note; `vpd_z_within` reported with a cluster-robust CI (B3.3).

**Human-decision flags.** **New dependency `statsmodels`** — not importable in the current env; must be added (`pymer4`/lme4 additionally need R). Crossed RE with ≈9 BGs may hit boundary variance → fallback BG fixed effects + overpass RE, or GEE. `MixedLM` weighting is not first-class (may force pymer4/WLS). Interpretation: the fixed effect effectively generalizes to one neighborhood — say so.

---

### B3.3 — Cluster bootstrap by block group  `[BLOCKER-adjacent]`

**Finding.** Breakpoint CI comes from an i.i.d. **row** bootstrap (`section14_threshold.py:207-257`, `rng.integers(0,n,size=n)` at `:234`) that ignores clustering; with one dominant BG it resamples within that BG.

**Ownership (settled — no duplicate edit).** The `bootstrap_breakpoint` cluster-resampling edit (add `groups=`, forward through `analyze_sample`, pass `groups=df["neighborhood_id"]` from the notebook) is **owned solely by m5**. **B3.3 does NOT re-implement it** — B3.3 *consumes* the m5-provided `groups=` API. If m5 has not yet landed when B3.3 runs, land the m5 `bootstrap_breakpoint` edit first (it is scheduled in the same B4+m5 bundle, before the B3.2/B3.3 step id=16 bundle). Running B3.3 and m5 as separate subagents must not double-apply the same edit.

**Where.** `bootstrap_breakpoint` (`:207-257`); only non-test caller `analyze_sample` (`:449`), passing bare `x,y`. Notebook calls `analyze_sample` (cell 20), never `bootstrap_breakpoint` directly. (The edit itself lands via m5.)

**Steps (consumption + model-side application only).**
1. Rely on the m5-added `groups=None` (keyword-only) parameter on `bootstrap_breakpoint`, its finite-mask filtering of `groups` (`:219-221`), and its whole-cluster resampling (`rng.choice(uniq, size=uniq.size, replace=True)`, concat member indices). Do not re-add these.
2. Rely on the m5-added forwarding of `groups=None` from `analyze_sample` (`:437-462`) at `:449` and the notebook cell-20 pass-through `groups=df["neighborhood_id"].to_numpy()`.
3. Two-way (BG × overpass) option via a `cluster` switch; BG-level is the honest binding constraint given ≤9 BGs.
4. **B3.3's own work:** apply the same BG-cluster resampling to the **B3.2 mixed-model CI** (refit per resample) — this is the piece B3.3 owns and m5 does not touch.
5. Keep `spans_fraction` (`:255`); expect a much wider CI.

**Tests.** (Breakpoint-side tests are owned by m5: `test_bootstrap_breakpoint` wider-with-cluster and `test_cluster_bootstrap_draws_whole_bgs`.) B3.3 adds the mixed-model cluster-CI test in `test_section14b_mixed_effects.py` (BG-resampled CI wider than the naive model SE). Register in `main()`.

**Re-run impact.** **14**/step id=16 only (pure analysis).

**Acceptance.** BG-cluster CI on ΔT_cool and `vpd_z_within` reported and wider than the row CI; verdict gate consumes it; note states cluster-robust by BG.

**Human-decision flags.** ≤9 clusters → recommend **wild cluster bootstrap** (Rademacher) as the small-cluster alternative. Overpass-level clustering under day-only reduces counts further — decide whether to cluster on overpass at all.

---

### B4 — Day/night pooling in the threshold analysis  `[BLOCKER]`

**Finding.** The threshold verdict pools day (+4.8 K) and night (+0.4 K, ~39.7% negative) overpasses, so the "flat cloud" result is partly a mixing artifact (`docs/section14_results_note.md:168-169`).

**Single source of truth (settled).** B4 **persists** `local_hour`/`is_day` as Section 13 master-table (and pixel-table) columns. Every downstream consumer — B3.2's mixed model, the B1b response-surface day variant, the notebook — **reads** these columns and does **not** re-derive time-of-day. The canonical formula lives here, matching notebook cell 4 / line 282: `local_hour = (ts.dt.hour - 7) % 24`, `is_day = 7 <= local_hour < 19` (Arizona MST = UTC−7, no DST). **B4 must land before B3.2.**

**Where.**
- No persisted time-of-day column. `MASTER_COLUMNS` `section13:487-503`; `COLUMN_GROUPS` `:506-515`; `overpass_timestamp` set per row at `:433` from `times[t]` (`grids["time"]` at `:290/:392`).
- Provenance is tz-naive UTC (`section2_ecostress_lst.py:524`; filename parse `:120-121`), so local = UTC−7 exact (Arizona, no DST).
- Day/night already derived in **notebook cell 4** (`local_hour`, `is_day`, `month`, formula at line 282) but never persisted, never fed to the model; used only in QC cell 17. `make_sample(min_count)` (cell 20) filters only on count; `SAMPLES={A_full(1),B_modest(3),C_robust(10)}`.
- Schema test `test_section13_master_table.py:176-196` asserts `MASTER_COLUMNS[:4]==["neighborhood_id","overpass_timestamp","overpass_key","city"]` (`:191-193`).

**Steps.**
1. Persist `local_hour`/`is_day` in `build_master_table` (`:430-464`) after the `overpass_timestamp`/`overpass_key` lines, using the canonical formula `int((pd.Timestamp(times[t]).hour - 7) % 24)` and `bool(7 <= local_hour < 19)`. Comment: Arizona MST=UTC−7, no DST; any DST-state extension must move to `zoneinfo`. This is the **single source of truth**; B3.1's pixel table and B3.2's model read these columns rather than recomputing.
2. **Append** the two columns at the END of the identifiers block **after `city`** in `MASTER_COLUMNS` (`:489`) and `COLUMN_GROUPS["identifiers"]` (`:507`) — appending preserves the `MASTER_COLUMNS[:4]` invariant (`:191-193`), so that assertion does not change; `report_master_table` (`:562-567`) and `verify_master_table` (`:695-696`) stay green. Optionally simplify notebook cell 4 to **read** the persisted columns + keep `month` (removing the independent re-derivation).
3. Add `split_day_night(is_day, keep_mask=None)` to `section14_threshold.py` near `:44` (unit-testable).
4. Make DAY-ONLY primary in notebook cell 20: `make_sample(min_count, part="day")`; `SAMPLES = {A_day_full(1,day)=PRIMARY, B_day_modest(3,day), C_day_robust(10,day), N_night_full(1,night)=CONTRAST, P_pooled_full(1,all)=legacy}`. Report A_day_full as the primary verdict (cells 21/26); label pooled as legacy (`main` commit `711c7f9`).
5. Elevate the day/night contrast (cell 17) from QC to a numbered result; rewrite `docs/section14_results_note.md:168-172` so day-only is primary.
6. (Recommended) add `daynight_contrast(x, y, is_day)` (pure OLS with interaction via `lstsq`) to test whether night flattens the day signal; print `delta_intercept` (expected ≈ +4.8 vs +0.4 K).

**Tests.**
- `test_section13`: extend `test_module_constants_and_schema` with two `check`s for the new columns (do **not** touch the `[:4]` assertion); new `test_local_hour_and_is_day_derivation` (known UTC instants → local_hour + boundary `[7,19)`). Register.
- `test_section14`: new `test_split_day_night`; new `test_night_does_not_flatten_day_signal` (day kink via existing `_kinked` builder + flat night; pooled masks the bend, day-only recovers it, `daynight_contrast delta_intercept` strongly positive); new `test_daynight_contrast`. Register all.

**Re-run impact.** Derived columns only → **13→14** (`--from 13`).

**Acceptance.** `master_table.parquet` has `local_hour` (int) + `is_day` (bool); `verify_master_table` passes; schema test passes incl. unchanged `[:4]`; day/night counts reproduce; primary verdict is day-only; the +4.8/+0.4 split and night frac-neg ≈0.40 stated as a result; `test_night_does_not_flatten_day_signal` passes; B3.2 reads (not re-derives) `is_day`.

**Human-decision flags.** Day/night boundary (`7<=h<19` matches existing convention; a stricter `10<=h<16` "clean day" sensitivity is cheap and recommended; solar-elevation gating needs `astral`/`pvlib`, not recommended for the pilot). Day-only will **likely still be "no robust threshold"** — for the right reason (thin sample), not the wrong one (night dilution); state this. Keep the pooled sample as a labelled legacy contrast.

---

### M1 — Restrict the reference set (impervious floor / drop NLCD 21)  `[MAJOR]`

**Finding.** `reference_mask` (`section10_classify_pixels.py:116-127`) has no impervious floor and `BUILT_CLASSES` includes NLCD 21 (developed open space), so irrigated/vegetated low-canopy open-space pixels qualify as "hot reference," biasing every `cooling_advantage`.

**Where.** `reference_mask` `:116-127` (no `impervious` param); `classify` `:178-207` receives `impervious` but does not pass it to `reference_mask` (`:194-195`); `start_params()` `:356-370`; `config.py:97` `BUILT_CLASSES=(21,22,23,24)`, `:98` `REF_CANOPY_MAX=20.0`, `:91` `IMPERV_THR=20.0`.

**Steps.**
1. Add `REF_IMPERV_MIN=20.0`, `REF_BUILT_CLASSES=(22,23,24)` to `config.py` near `:97-98`; keep `BUILT_CLASSES` unchanged (trees unaffected).
2. Extend `reference_mask` (`:116-127`) with `impervious` positional + `imperv_min=0.0` keyword (default no-op; NaN impervious fails → never reference); add `& (impervious > imperv_min)` (strict `>`).
3. Thread through `classify` (`:178-207`): add `imperv_min=0.0`, `ref_built_classes=None` (fall back to `built_classes`); update the reference call (`:194-195`).
4. Thread from `start_params()` (`:356-370`): add `imperv_min`, `ref_built_classes`.
5. **Update EVERY `classify` caller** to forward the two keys: `sensitivity_row` (`:210-232`), `derive_operating_canopy_thr` (`:388-397`), `run()` live classify (`:796-802`).
6. No Section 13 change (`neighborhood_static` keys off `CLASS_REFERENCE`, `:324`).

**Tests.** Update `_REF_KW` (`:66`) with `imperv_min=20.0`; update `test_reference_rule` (`:120-133`) to pass `impervious`; new `test_reference_requires_impervious` (boundary at 20, strict `>`); new `test_reference_excludes_nlcd21`; update `test_config_constants_present` (`:259-279`); decide whether the two end-to-end tests exercise the strict reference (recommend passing the strict kwargs and confirming counts unchanged for those fixtures).

**Re-run impact.** **10→11→12→13→14** (`--from 10`).

**Acceptance.** `section10_paired_neighborhoods.csv` shows reduced reference counts; recompute the DESIGN_DECISIONS 40%→9 table and report the new paired-BG count; report `cooling_advantage` with vs without M1.

**Human-decision flags.** M1 can drop paired BGs below 9 — the human must accept and report the count. Drop-21 vs impervious-floor vs both (recommend both with documented sensitivity).

---

### M2 — Pre-committed canopy threshold (remove yield-tuning)  `[MAJOR]`

**Finding.** `derive_operating_canopy_thr` (`:380-411`) does **not** simply maximize `n_paired_blockgroups` — its selection is **gated on paired-BG yield via `OP_MIN_PAIRED`**: it builds a `paired_by_ct` map (paired-BG count per candidate) and then, scanning `OP_CANDIDATES` **highest-first**, picks the **highest candidate whose paired-BG count clears the `OP_MIN_PAIRED` floor**, falling back to `OP_FLOOR` if none clears. This is still outcome-adjacent tuning against the study sample — the chosen threshold is a function of paired-BG yield — but the mechanism is a "highest-that-clears-a-floor" rule, not an argmax. The fix must remove the `OP_MIN_PAIRED`-gated selection, not an argmax.

**Where.** `section10_classify_pixels.py:373-377` (constants incl. `OP_CANDIDATES`, `OP_MIN_PAIRED`, `OP_FLOOR`), `:382-411` (function body: the `paired_by_ct` build loop over candidates that calls `classify`/computes paired-BG counts, and the `OP_MIN_PAIRED`-gated highest-first selection loop), `:791-793` (run-time assert); `config.py:89` `CANOPY_THR=40.0`, `:90` `CANOPY_THR_PREREGISTERED=70.0`.

**CRITICAL correction to the naive fix.** The 70 m canopy layer has mean **0.88%**, max **69.53%** (DESIGN_DECISIONS L128-129). A plain P90 over *all* finite pixels lands far below 40% and admits nearly every faintly-green pixel. Any percentile criterion must be over a **canopy-bearing / NDVI-qualifying subpopulation**, not the whole grid.

**Steps.**
1. Delete the yield-selection machinery **inside `:382-411`**: remove the `paired_by_ct` build loop (the per-candidate `classify`/paired-BG-count computation) and the `OP_MIN_PAIRED`-gated highest-first selection loop; keep the function signature (so `run()` `:770` and the assert `:791-793` are untouched). Do not delete by the stale `:388-398,:400-407` line pair — anchor the deletion to the `paired_by_ct` build loop and the `OP_MIN_PAIRED` selection loop within `:382-411`.
2. **(Recommended 2a)** Percentile over the NDVI-qualifying, building-excluded pool: `CANOPY_PCTL=90`; `chosen = percentile(canopy[keep & finite & ndvi>ndvi_thr], 90)`. Property of the canopy/NDVI layers alone, independent of paired-BG count.
   **(Alternative 2b)** Keep a fixed physical constant (e.g. 40% ≈ 45× the mean, the in-code justification) and simply remove the yield-search.
3. Set `config.CANOPY_THR` to the derived value once; keep the run-time equality assert; keep `CANOPY_THR_PREREGISTERED=70.0`.
4. Report the canopy sensitivity (`build_sensitivity_table`/`section10_threshold_sensitivity.csv`, `:414-482`) but never select on it; reframe the LIMITATION log (`:786-790`).

**Tests.** New `test_derive_operating_canopy_thr_is_precommitted` (equals the NDVI-restricted percentile; **invariant to `bg_index`/paired-BG yield** — the decoupling proof, i.e. varying paired-BG counts leaves the chosen threshold unchanged; this function has no unit test today); update `test_config_constants_present` (`:265`) to the derived value (intentionally fails until computed on the real layer) + add `CANOPY_PCTL`. `test_sensitivity_row_monotone_in_canopy` (`:233-256`) unaffected but inherits the M1 kwargs via `start_params()`.

**Re-run impact.** **10→11→12→13→14** (`--from 10`). Land M1+M2 together.

**Acceptance.** Derivation is BG-geometry/paired-yield-independent (2a) or a fixed justified constant (2b); the `OP_MIN_PAIRED`-gated loop is gone; `config.CANOPY_THR` equals the committed value; sensitivity CSV reports paired-BG count without selecting on it; DESIGN_DECISIONS states the rule and resulting N.

**Human-decision flags.** Percentile and floor interact (mean 0.88% may put even the NDVI-restricted P90 below 40%) — decide whether to keep `OP_FLOOR=40` as a hard clamp (recommended) and the percentile value (85/90/95). M1+M2 together may push paired BGs below 9 — accept and report as the binding limitation.

---

### M3 — Widen `build_keep_mask` to keep QC "best + nominal/good"  `[MAJOR]`

**Finding.** `section2` keeps only QC mandatory-bits `00` ("best") and silently discards all `01` ("nominal/good"), shrinking every LST overpass.

**Where.** `section2_ecostress_lst.py:64-65` (`QC_MANDATORY_BITS=0b11`, `QC_BEST_QUALITY=0b00`); `qc_best_quality_mask(qc)` `:142-145` (`==` best); `build_keep_mask()` `:148-159`, called `:464` in `clean_lst_tile`, from `build_cube` `:505`. Test `test_qc_bit_logic` `:102-112`.

**Steps.**
1. **Gating spec check FIRST (human/spec, not code).** Confirm the ECOSTRESS L2 LSTE v002 (`ECOv002_L2T_LSTE`) two-bit mandatory-QA: that `01` = "nominal/good, produced," not a degraded state. Source: v002 User Guide / LP DAAC-VITALS QC tutorial cited at `:63`. **If `01` is degraded, do NOT widen** — record won't-fix with the citation.
2. Add `QC_MAX_KEPT_MANDATORY=0b01` at `:65`.
3. Widen `:142-145` to `(qc & QC_MANDATORY_BITS) <= QC_MAX_KEPT_MANDATORY`; update docstring and the `:63`/`:154` comments.
4. Add a per-granule recovery audit: extend `GranuleStats`/`as_row()` (`:169-200`) with `n_valid_best_only`, compute via a private `_qc_best_only_mask`, thread through `summarize_granule`, surface in `ecostress_lst_granule_report.csv`.

**Tests.** Update `test_qc_bit_logic` (`:108` → `[[True,True],[False,False]]`; `:111` `0b0000_0001` now → `[True,True]`); `test_keep_mask_polarity` (`:115-134`) unchanged but add a `0b01`-kept assertion; new `test_qc_keeps_nominal` (`[0b00,0b01,0b10,0b11]→[T,T,F,F]`); new `test_module_constants` (`QC_MAX_KEPT_MANDATORY==0b01`).

**Re-run impact.** `--only 2 --skip-download` then `--from 9`. LST change affects Section 10 (`obs_count`) and Section 13 (ΔT_cool); Section 11/12 z-scores/CSI are LST-independent (re-running them is a harmless no-op). ET/ESI (`section3`): add `--only 3 --skip-download` **only if** a grep confirms section3 reuses the predicate **and** m1 landed a real ET/ESI QC band (currently all-zeros → no-op).

**Acceptance.** Tests pass with `01→kept`; granule report shows `n_valid >= n_valid_best_only` (strictly greater for ≥1); total finite LST ≥ pre-fix; paired BGs ≥ 9; per-BG `n_tree_valid`/`n_ref_valid` ≥ pre-fix for matching rows.

**Human-decision flags.** Gating spec check is mandatory (step 1) — the one true blocker; rests on a spec not verifiable from code. Widening trades purity for coverage — document.

---

### M4 — PRISM `select_by_time` must fail on a missing date, not attach the nearest  `[MAJOR]`

**Finding.** `section9` matches PRISM antecedent precip/tmean with `sel(method="nearest")` and no tolerance, silently attaching an adjacent day's grid on a gap.

**Where.** `section9_harmonize.py:265-271` `select_by_time`; offending call `:270`; call sites `:344-345` (precip) and `:347-350` (tmean). PRISM zarr `time` and `precip_date` are both midnight-normalized (`section7_precip_drought.py:781,:728`; `section9:146-148,:177`), so exact-label alignment holds for present days.

**Steps.**
1. Choose policy (human; **A recommended**). **A** — explicit NaN: keep `method="nearest", tolerance=pd.Timedelta(0)`, catch `KeyError` → all-NaN grid + warning (xarray raises `KeyError` when nearest exceeds tolerance-0). **B** — hard error: `method=None`, let `KeyError` propagate.
2. Edit `select_by_time` (`:265-271`) per the chosen policy (return all-NaN `(ny,nx)` on `KeyError`, or default indexing).
3. Emit a NaN-substitution count next to the PRISM log (`:351`): `"PRISM: %d/%d overpasses missing an exact date -> NaN"` — a visible tripwire.

**Tests.** New `test_select_by_time_exact_match` (fake `cube[var]` whose `.sel` returns the day on exact match, raises `KeyError` otherwise; assert exact returns values, missing returns all-NaN `(ny,nx)` for A / raises for B). Leave `test_build_overpass_index` untouched unless a read shows it references `select_by_time`.

**Re-run impact.** Step 9 only (`--from 9`). If PRISM is complete (expected), fields are byte-identical and 10–14 are unchanged; the "0 missing" log proves no silent substitution was masking a gap.

**Acceptance.** New test passes; fresh `--from 9` logs "0 overpasses missing" (A) / no `KeyError` (B); a scratch gap yields NaN for exactly that overpass (A) or `KeyError` (B), never a neighbor's day.

**Human-decision flags.** A vs B (recommend A, warning count as tripwire). PRISM provisional-vs-stable can be off-by-one at the season tail — the count log reveals it.

---

### M6 — Resolve `date=None` drought bands from `system:time_start` (or raise)  `[MAJOR]`

**Finding.** When an EE `toBands` build emits positional band names, `parse_drought_band` returns `date=None` and `build_drought_cube` silently `continue`s, dropping pentads; only a *total* wipe is caught by the empty-axis guard.

**Where.** `section7_precip_drought.py:250-264` parser (`date=None` at `:263`; docstring `:254-256` claims caller resolution — unimplemented); `:874` builder loop, silent drop `:876-877`; empty-axis `raise` `:885-886`; date source `:668-671` (`col`/`image`/`band_names`; `system:time_start` never captured); `DroughtDownload` dataclass `:637-644`; return sites `:677`(reuse), `:688-689`(success), `:696`(failure). Test `test_parse_drought_band` `:142-158`.

**Steps.**
1. Capture per-image dates after `:671`: `start_millis = col.aggregate_array("system:time_start").getInfo()`; `image_dates = [...strftime("%Y%m%d")]`. In scope for all four return paths (built before the reuse return at `:675`).
2. Runtime consistency check (validates the `toBands` image-major ordering assumption): for any band that **does** parse to a date, assert it equals `image_dates[b // len(vars_)]`; on mismatch fall back to `<system:index>`-token matching and log loudly.
3. Add `band_dates: list[str]` to `DroughtDownload` (`:637-644`); compute per-band expansion `[d for d in image_dates for _ in vars_]` (assert `len==len(band_names)`); populate in **every** return (`:677,:688-689,:696`).
4. Replace the `:876-877` silent drop: keep `var`-mismatch `continue`, but resolve `None` dates via a helper; assert `len(band_dates)==da.sizes["band"]` before the loop (handles the existing `da.band.values` fallback at `:871-872`).
5. Extract pure `resolve_band_date(name, band_index, parsed_date, band_dates)` — parsed date wins, else `band_dates[index]`, else **raise** (never silently drop). Keep the empty-axis `raise` as a second backstop.
6. Fix the stale parser docstring (`:254-256`).

**Tests.** Keep `test_parse_drought_band` (parser contract unchanged); new `test_resolve_band_date` (parsed wins; fallback resolves; None+None raises; out-of-range raises); new `test_band_dates_expansion` (length + pairing arithmetic); new `DroughtDownload` field test (default `[]`, FAILED branch).

**Re-run impact.** `--only 7 --skip-download` (still needs one EE `getInfo()` for `system:time_start` even offline — optional sidecar-JSON hardening for a truly offline rebuild) then `--from 9`. Drought (`pdsi`) feeds the cube (`section9:361-366`) and `aridity` in Section 13 (`:282,:396,:428,:450`); Section 11/12 do not consume drought.

**Acceptance.** Tests pass incl. raise-on-unresolvable; fresh `--only 7` yields the full pentad count (no missing pentads); docstring matches behavior; a positional-only `band_names` scratch test resolves every pentad; the runtime consistency check passes on a real download.

**Human-decision flags.** `toBands` ordering assumption is unverified statically — the consistency check is the guard. `system:time_start` availability (present for GRIDMET DROUGHT; `resolve_band_date` raises if ever absent — fail-loud). Offline-rebuild caveat (live EE call under `--skip-download`).

---

### M5 — Well-sampled subset PRIMARY; full pool a labelled sensitivity  `[MAJOR]`

**Finding.** `row_emittable` admits `n_tree_valid>=1` (`section13:103-108`), so single-tree-pixel BGs (ΔT_cool +23 K / −6.3 K, `docs/section14_results_note.md:149-155`) enter at equal weight; the notebook reports the full pool (n≈264) as headline.

**Where.** `section13:103-108` `row_emittable`, call sites `:414` + new `build_pixel_table`; `verify_master_table:713-714`; notebook `make_sample`/`SAMPLES` (cell 20), day/night + within/between QC (cells 15–17).

**Steps.**
1. Do **NOT** raise the emission floor (keep `>=1`; full pool stays persisted as the sensitivity sample; `verify_master_table:713-714` and `test_row_emission_rule` unchanged).
2. Add `PRIMARY_MIN_TREE_PX=3` to `config.py` (new Section-13/analysis block near `:98-99`; 3–5 pre-committed).
3. Add `sample_label` to BOTH tables (`"primary"` iff `n_tree_valid>=PRIMARY_MIN_TREE_PX`); add to `MASTER_COLUMNS`/`PIXEL_COLUMNS`, `COLUMN_GROUPS["identifiers"]`.
4. Invert the analysis default (B3.2/B3.3 and notebook cell 20): primary = `make_sample(3)`, sensitivity = `make_sample(1)`, degenerate = `make_sample(10)`; report primary first.
5. **Compute** the exact drop fraction of `n_tree_valid>=3` during implementation (`(mt["n_tree_valid"]<3).mean()`) — do NOT reuse the note's "~59.5%" (that is `n_good_obs<=2`, a different quantity). Default 3; report 5 as sensitivity.

**Tests.** Keep `test_row_emission_rule` (`:106-113`); new `test_sample_label_primary_floor`; update `test_module_constants_and_schema` (`:176-197`) for `sample_label` + `PRIMARY_MIN_TREE_PX in (3,4,5)`.

**Re-run impact.** **13→14** (`--from 13`). Land B3.1+M5 together.

**Acceptance.** Both tables carry `sample_label`; primary = `n_tree_valid>=3`; results note reports primary vs full-pool side by side (full pool explicitly a sensitivity); exact drop fraction computed and stated.

**Human-decision flags.** Floor 3 vs 5 (5 may starve the mixed model — the `>=10` subset already collapses to n=31, 1 BG). Default 3; state the power/validity tradeoff.

---

### m1 — ET/ESI QC status + ESI plausibility bound  `[MINOR]`

**Finding.** Section 3 applies no PT-JPL retrieval-quality filter (keep-mask degenerates to `cloud==0 & water==0 & finite`); "corroboration-only" status is docstring-only; the ESI ceiling 1.5 is unjustified; a dead PET bound sits beside it.

**Where.** `section3_ecostress_et_esi.py:264-268` (zeros_qc → `sec2.build_keep_mask`), `:15` (docstring), `:133` (`plausible={"esi":(0.0,1.5),"pet":(0.0,1200.0)}`), `:281-282` (`decide_range_flag` reads only `plausible[primary_var]`, `primary_var=="esi"` → PET dead), docs `section14_results_note.md:173-174`.

**Steps.**
1. Add module const `ROLE="corroboration"` with a comment (ET/ESI never a primary outcome).
2. `log.warning("Section 3 %s: no retrieval-quality band; keep-mask = cloud/water/finite only (corroboration-only)")` at `:264-268`.
3. Add `ESI_PLAUSIBLE_MAX=1.5` to `config.py` with justification; reference at `:133`; add advisory (flag-not-drop) docstring at `:15`.
4. Delete the dead `"pet":(0.0,1200.0)` (recommended).
5. Docs: add a "Section 3 QC limitations" paragraph.

**Tests.** New `test_config_esi_bound_wired`; `test_esi_product_has_no_dead_pet_bound`; `test_zeros_qc_keeps_only_cloud_water`. (No existing `plausible["esi"]==1.5` assertion to update.)

**Re-run impact.** **None** — docs/const/log only; `ESI_PLAUSIBLE_MAX` stays 1.5 (flag-not-drop → kept granules unchanged); deleting the dead bound changes nothing.

**Acceptance.** Log warning per product; `config.ESI_PLAUSIBLE_MAX` referenced at `:133`; explicit "corroboration-only" in code+docs; dead PET bound gone; tests green.

**Human-decision flags.** A real retrieval-quality filter needs a PT-JPL quality band the download omits (future work). Confirm 1.5 vs 1.2 (modeling choice). Confirm v002 JET/ESI tiles ship no usable retrieval-QC layer (product-doc check).

---

### m2 — Sentinel-2 cloud threshold + per-pixel valid-scene count  `[MINOR]`

**Finding.** Per-scene filter keeps `CLOUDY_PIXEL_PERCENTAGE < 60` (loose); the median composite emits no per-pixel valid-scene count, so NDVI/NDMI medians can rest on a tiny unrecorded N; help/docstring wording drifts from the `lt` operator.

**Where.** `section4_sentinel2_indices.py:58` (`MAX_SCENE_CLOUD_PCT=60.0`), `:203` (`ee.Filter.lt`), `:207-215` (`index_composite`, sole `.median()` reducer), `:329-341` (`reproject_to_grid`), `:591`/`:15` (wording drift). Section 4b inherits via `sec4.MAX_SCENE_CLOUD_PCT` (`section4b:60`) and `sec4.mask_scl_ee` (`:172-173`) — changes automatically.

**Steps.**
1. `:58` `60.0 → 40.0` (no operator change; propagates to 4b).
2. Fix wording (`:591`, `:15`, and 4b docstring): "drop `>= thr`, keep `< thr`."
3. Emit a per-pixel count in `index_composite` (`:207-215`): `nscenes = masked.count().rename(key+"_nscenes")`; return a 2-band image (primary band first so single-band consumers still `select(key)`).
4. Regrid the count with **nearest** and persist `data/interim/s2_{ndvi,ndmi}_nscenes_2023_70m.tif`; add `nscenes_grid_filename` to `IndexProduct` (mirror `:107-109`); verify the 2-band image survives `geemap.download_ee_image`.
5. Register the two `_nscenes` paths in step-4 `outputs` (`run_all.py:100-104`).
6. (Optional follow-up) consume the count in Section 9/13 as QC/weight — not required to close m2.

**Tests.** New `test_scene_gate_threshold_and_wording` (`==40.0`, help says `>=`/keep `<`); `test_valid_scene_count_helper` (pure numpy `valid_scene_count(stack)`); `test_index_product_nscenes_filename`. (No existing `==60` assertion.)

**Re-run impact.** Gate change alters NDVI/NDMI medians **and** Section 4b temporal NDMI (feeds `ndmi_z`, the CSI check): `--only 4 --skip-download` → `--from 9 --skip-download` (produces the cube) → `python src/section4b_ndmi_timeseries.py` (reads the cube; EE download unless raw reused) → `--from 11 --skip-download`.

**Acceptance.** `s2_ndmi_nscenes_2023_70m.tif` + NDVI counterpart exist at 70 m; filter keeps `<40` (4 and inherited 4b); `--check-deliverables` passes the new step-4 outputs; Section 11 still validates the NDMI timeseries input.

**Human-decision flags.** 30 vs 40% (recommend 40 to preserve scene count; the count raster makes low-N visible). Re-pull 4b scenes under the new gate (recommend yes; EE download). Record-only vs act-on low counts (recommend record-only for the MINOR).

---

### m3 — Run the unequal-weight sensitivity and report  `[MINOR]`

**Finding.** CSI uses equal 0.5/0.5 weights; the parameterized hook `compute_csi(demand, supply, w_demand, w_supply)` exists but is never run — only described as "NOT run now" in `_report_sensitivity_hooks()` (`section12:631-632`).

**Where.** `compute_csi()` `:90-100`; `config.WEIGHT_DEMAND/WEIGHT_SUPPLY` `config.py:117-118`; `_report_sensitivity_hooks()` `:625-640`; `test_compute_csi_parameterised_weights` `:105-115`.

**Steps.**
1. Add `run_weight_sensitivity(ds, weight_grid=None)` near `:335`; recompute CSI from the already-built `ds["demand_stress"]`/`ds["supply_stress"]` via `compute_csi` (no re-read) for a grid `[(0.5,0.5),(0.7,0.3),(0.3,0.7),(1.0,0.0),(0.0,1.0)]`; per pair record spatial-mean CSI, top-N extreme dates, heatwave enrichment; return a DataFrame.
2. Report the RQ1-relevant sensitivity: Spearman rank correlation of per-overpass spatial-mean CSI vs baseline, and extreme-date ranking stability across `w_demand∈[0.3,0.7]`.
3. Replace the "NOT run" text (`:628-632`) with the results table; **keep the copula try/except** (`:633-640`).
4. Persist `data/processed/section12_weight_sensitivity.parquet`.
5. (Optional supp figure) spatial-mean CSI per overpass per weight pair.

**Tests.** New `test_weight_sensitivity_runs_and_is_convex` (one row per pair; `(1,0)`=pure demand, `(0,1)`=pure supply; intermediates convex). No change to `test_copula_weights_is_unrun_stub`.

**Re-run impact.** Self-contained in Section 12 (`--only 12`) unless it changes the baseline weights.

**Acceptance.** Section 12 prints a ≥5-pair table + writes the parquet; report states RQ1 stability across `w_demand∈[0.3,0.7]`; new test passes; copula stub still raises.

**Human-decision flags.** DECISION 6 — does sensitivity change the baseline (report either way). Run m3 **after** B1a (rescaled supply makes weight sensitivity isolate conceptual weighting, not variance artifacts).

---

### m4 — ACS/TIGER vintage pinning + geometry/attribute desync bug  `[MINOR + latent bug]`

**Finding.** `ACS_YEAR=2024` is hardcoded, and the TIGER URL/zip are frozen module f-strings built at import; `fetch_block_group_geometries(year=...)` reaches only the manifest, so a non-default year downloads 2024 geometry but records year N.

**Where.** `section8_neighborhood_tree.py:57` (`ACS_YEAR=2024`), `:67-68` (frozen `TIGER_BG_URL`/`TIGER_BG_ZIP`), `:401-423` (`year` reaches only manifest `:413-414`; download uses frozen URL `:408-409`/zip `:406`; county filter `:419` `COUNTYFP=="013"`). ACS is parameterized (`fetch_acs` `:337`).

**Steps.**
1. Remove the frozen `:67-68` strings; build inside `fetch_block_group_geometries` from `year`: `f".../TIGER{year}/BG/tl_{year}_{STATE_FIPS}_bg.zip"` and `f"tl_{year}_{STATE_FIPS}_bg.zip"`; use at `:406,:408-409`; keep manifest `:411-414` on `year`.
2. Disclose vintage: `log.info("Census vintage: ACS5 %d, TIGER/Line %d ...")`.
3. Confirm the ACS5 vintage at run time: wrap the first `http_get` so an unreleased-year response (404, or non-array/HTML body) raises a clear message.
4. Docs: record ACS5 2024 / TIGER 2024 and the run-time confirmation.

**Tests.** New `test_tiger_url_tracks_year` (refactor pure `tiger_bg_url(year)`/`tiger_bg_zip(year)`; 2023 vs 2024 contain the matching year — the regression lock); `test_acs_vintage_pinned`; optional release-check test (mocked released/not-released).

**Re-run impact.** **None** with vintage held at 2024 (byte-identical geometry; bugfix only). If deliberately changed: `--only 8 --skip-download` then `--from 9 --skip-download`.

**Acceptance.** `--acs-year 2023` downloads `tl_2023_04_bg.zip` (not 2024), verified by log/manifest; manifest records matching year; release-check raises cleanly for an unreleased year; default 2024 yields identical geometry; tests green.

**Human-decision flags.** Whether 2024 ACS5 BG tables are actually released is an external fact (step 3 automates the guard, cannot decide) — confirm against api.census.gov. Hold 2024 for reproducibility of the 264-row result (recommended). Keep ACS and TIGER years equal (GEOID join assumes GEOID stability).

---

### m5 — Penalized changepoint + tighter agreement + cluster bootstrap  `[MINOR, invalidates the honesty gate]`

**Finding.** Three crutches make the "no robust threshold" verdict non-falsifiable: (i) a forced single break that can never say "no break"; (ii) an agreement tolerance so wide two unstable estimates "agree" on a flat cloud; (iii) an i.i.d. row bootstrap ignoring the 9-cluster structure.

**Ownership (settled).** **m5 is the sole owner of the `bootstrap_breakpoint` cluster-resampling edit** (add `groups=`, forward through `analyze_sample`, pass `groups=df["neighborhood_id"]` from the notebook). B3.3 *consumes* this API and does not re-implement it; the mixed-model cluster-CI application is B3.3's own piece. Do not double-apply.

**Where.** `section14_threshold.py:261-293` `changepoint_csi` (`penalty_n_bkps:int=1` at `:261` passed to `algo.predict(n_bkps=...)` at `:286` via `rpt.Dynp` `:285`; `max(1,min(split,n-1))` clamp `:287-288`; call `:450`); `AGREE_TOLERANCE_FRACTION=0.20` `:331` (consumed `:353-355`); `bootstrap_breakpoint` `:207-257` (`rng.integers(0,n,size=n)` `:234`, call `:449`). **Key discrepancy:** `penalty_n_bkps` is a *count* mislabeled "penalty"; `Dynp.predict(n_bkps=1)` cannot return zero breaks and the `max(1,...)` clamp re-fabricates an interior split.

**Steps.**
1. Replace the forced-count estimator with a penalized one that can return zero breaks: signature `def changepoint_csi(x, y, *, pen=None, min_size=2)`; `rpt.Pelt(model="l2", min_size, jump=1).fit(signal).predict(pen=penalty)` with BIC-style `pen=2*ln(n)*max(var,1e-12)`; `len(bkps)<=1` → return NaN changepoint / `split_index=-1`; **remove the `max(1,...)` fabrication**; edge breaks → treat as no break. `methods_agree` already returns False on non-finite changepoint (`:346`) — no change at `:404`.
2. Tighten `AGREE_TOLERANCE_FRACTION` `0.20 → 0.10`; primary honesty now from the (widened) cluster-bootstrap CI-membership path; tolerance only absorbs the pwlf-knee-vs-ruptures-shift offset.
3. Cluster-bootstrap by BG in `bootstrap_breakpoint` (**m5 owns this edit**): add `groups=None`, mask identically to `x,y`, resample whole clusters; keep `groups=None` byte-for-byte identical; thread `groups` through `analyze_sample` (`:437-462`, forward at `:449`); notebook cell 20 passes `groups=df["neighborhood_id"].to_numpy()`. (B3.3 consumes this; it does not re-add it.)
4. Remove `penalty_n_bkps` (grep-confirmed only at `:261,:286` — no test/notebook references).

**Tests.** Update `test_changepoint_csi` (`:169-179`; relax exact split, add no-break-on-flat assertion); new `test_changepoint_returns_no_break_on_flat`; new `test_cluster_bootstrap_draws_whole_bgs` + a cluster-wider test (`spans_fraction` wider with groups; `groups=None` unchanged) — **owned by m5** (B3.3 does not duplicate them); update `test_methods_agree_within_tolerance` (`:208-215`; change `cp=0.72→0.62` so offset 0.06 still agrees, add a `0.16`-offset disagree at 0.10); `test_threshold_verdict_robust_case`/`test_verdict_gate_logic_controlled` expected unaffected. Register new functions.

**Re-run impact.** Pure math + notebook: **14 only**; combined with B4 → **13→14** (`--from 13`). Needs `pwlf`+`ruptures` in the venv (neither installed in the review env).

**Acceptance.** Flat inputs → `split_index=-1`, NaN changepoint; cluster `spans_fraction` wider than row; `AGREE_TOLERANCE_FRACTION==0.10` and the 0.16-offset disagrees; suite passes in the venv; verdict still honest (likely "no robust threshold") but now falsifiable.

**Human-decision flags.** Penalty calibration (`2*ln(n)*var` is a judgment call; expose as notebook-tunable, print the chosen penalty + break count; the explicit 0-vs-1-break AIC/BIC wrapper is the fallback if the pinned `ruptures` penalty API is uncertain). Confirm `rpt.Pelt(...).predict(pen=...)` (or `rpt.Binseg`) in the **pinned** `ruptures` — unverifiable in the review env. ≤9 clusters → coarse/jumpy CI (correct; report `n_valid` resamples). Tolerance 0.10 is a chosen number (may drop the tolerance path entirely once the cluster CI widens).

---

## 5. Global Re-run Pipeline

Dependency spine: `10 → 11 → 12 → 13 → 14`, `9` feeds all; **Section 4b is not in the registry** and reads Section 9's `analysis_cube_70m.zarr`, so its slot is **after 9, before 11**, invoked directly. Steps 9–14 are `network=False` (so `--skip-download` is a no-op there and can be omitted for a `--from 9` run). Always bracket with `python src/run_all.py --check-deliverables` (read-only); verify Section 4b's `s2_ndmi_timeseries_70m.zarr` separately (`section4b --verify-only`, not registry-audited).

**New registry step ids (settled).** `section15_response_surface.py = id=15` (reads `master_table.parquet`); `section14b_mixed_effects.py = id=16` (reads `master_pixel_table.parquet`). `--from N`/`--to N` are inclusive over registry ids. **id sweep:** once both are registered, `--from 12` sweeps ids **12, 13, 14, 15** (i.e. it *does* run the id=15 response surface) and `--from 13` sweeps **13, 14, 15**. **id=16 (mixed effects) is NOT swept by `--from 12`/`--from 13`** in the minimal sets below only because we invoke it directly after its input parquet exists — if you instead want the sweep to cover it, use `--from 12` / `--from 13` with no explicit terminal `--to`, which runs through id=16 as well. The minimal sets below invoke id=16 directly for clarity about ordering.

**Minimal re-run set after Phase A (B2, M1, M2, M3, M4, M6):**
```
python src/run_all.py --only 2 --skip-download          # M3 (LST QC bits)
python src/run_all.py --only 7 --skip-download          # M6 (needs one EE getInfo for system:time_start)
#   §8 only if ACS/TIGER vintage actually changes — held at 2024 → SKIP (m4)
python src/run_all.py --from 9                           # M4 + propagate M3/M6/M1/M2/B2 through 9→14
```
(M1/M2 change Section 10, B2 changes Section 11; a single `--from 9` re-runs 9→14 and covers all of them. If M1/M2 are landed alone without any §2/§7/§9 change, `--from 10` suffices. Steps 15/16 do not exist yet in Phase A.)

**Minimal re-run set after Phase B (B1a, B1b, B3.1, M5, B4, m3, m5; B3.2/B3.3 are pure analysis on the pixel table):**
```
python src/run_all.py --from 12                          # B1a supply swap: sweeps ids 12,13,14,15
                                                         #   (12 CSI, 13 master+pixel tables, 14 threshold,
                                                         #    15 response surface). Does NOT run id=16.
#   equivalently, if only 13-level column adds (B3.1, M5, B4) changed and CSI is unchanged:
#   python src/run_all.py --from 13                       # sweeps ids 13,14,15
python src/section14b_mixed_effects.py                   # id=16: B3.2/B3.3 on master_pixel_table.parquet,
                                                         #   invoked directly (its input parquet now exists)
```
Ordering note: because B4 persists `local_hour`/`is_day` in Section 13 and B3.2 (id=16) reads them, the `--from 12`/`--from 13` sweep (which rebuilds Section 13) MUST complete before `section14b_mixed_effects.py` is invoked. The direct invocation of id=16 is deliberate — it makes the "B4-before-B3.2" dependency explicit rather than relying on registry order alone.

**If m2 (S2 gate) is exercised** (rebuilds temporal NDMI → `ndmi_z`):
```
python src/run_all.py --only 4 --skip-download
python src/run_all.py --only 9 --skip-download            # produces the cube 4b needs
python src/section4b_ndmi_timeseries.py                   # reads the cube (EE download unless raw reused)
python src/run_all.py --from 11 --skip-download           # 11→12→13→14/15 with fresh ndmi_z
```

**Stress-axis redesign alone** (nothing upstream of §11 changed): `python src/run_all.py --from 11` (11→12→13→14→15).

---

## 6. Testing & Verification Strategy

**Per-fix unit tests (all hand-rolled `check()` + `main()` registry; register every new `def test_*()`):**
- **B2** `test_section11_anomalies.py`: extend `test_zscore_degenerate_std`; new `test_zscore_min_std_floor_caps_extreme_z`; extend `test_module_constants`.
- **B1a/B1b/m3** `test_section12_compound_stress.py`: `test_supply_source_is_soil_moisture`, `test_robust_unit_scale_restores_unit_spread`, `test_input_guard_accepts_sm_z_rejects_raw`, `test_weight_sensitivity_runs_and_is_convex`; update the supply constant assertions. New `test_section15_response_surface.py`: assignment, NaN-pairwise, out-of-range excluded, day filter.
- **B3.1/M5/B4** `test_section13_master_table.py`: `test_pixel_table_shape_and_identity`, `test_sample_label_primary_floor`, `test_local_hour_and_is_day_derivation`; extend `test_module_constants_and_schema` (keep `[:4]` and `WATER_SUPPLY_Z_VAR=="ndmi_z"`, add `SM_Z_VAR=="sm_z"`).
- **B3.2/B3.3** new `test_section14b_mixed_effects.py` (guard `statsmodels` import): centering, within-between recovery, dominant-BG downweight, and the B3.3 mixed-model BG-cluster-CI-wider test.
- **B3.3/m5/B4** `test_section14_threshold.py`: `test_split_day_night`, `test_night_does_not_flatten_day_signal`, `test_daynight_contrast`, `test_changepoint_returns_no_break_on_flat`, `test_cluster_bootstrap_draws_whole_bgs`/wider (m5-owned); update `test_changepoint_csi`, `test_methods_agree_within_tolerance`, `test_bootstrap_breakpoint`.
- **M1/M2** `test_section10_classify_pixels.py`: `test_reference_requires_impervious`, `test_reference_excludes_nlcd21`, `test_derive_operating_canopy_thr_is_precommitted`; update `_REF_KW`, `test_reference_rule`, `test_config_constants_present`.
- **M3** `test_section2_ecostress_lst.py`: `test_qc_keeps_nominal`, `test_module_constants`; update `test_qc_bit_logic`.
- **M4** `test_section9_harmonize.py`: `test_select_by_time_exact_match`.
- **M6** `test_section7_precip_drought.py`: `test_resolve_band_date`, `test_band_dates_expansion`, `DroughtDownload` field test.
- **m1/m2/m4** section 3/4/8 tests as listed in their cards.

**Reproducibility re-run from interim.** Restore `data/{interim,processed}` from the saved archive (steps 1–8 + §4b's zarr are credential/network-bound and NOT reproducible from placeholders). Audit with `--from 9 --check-deliverables`; rebuild with `--from 9`; verify determinism: `master_table.parquet` = **264 rows × 26 cols, one row per (`neighborhood_id`, `overpass_key`)**, 9 paired neighborhoods, 54 overpasses, median `n_good_obs≈2`, day/night +4.8 K / +0.4 K. Bootstrap non-determinism pinned via `DEFAULT_SEED` threaded through `segmented_fit`/`bootstrap_breakpoint`.

**Tree-pixel visual validation (PENDING USER REVIEW).** Render each sampled pixel (`section10_validation_sample.csv`) over an S2 true-color chip via `make_validation_overlay` (`section10:579`); reviewer marks agree/disagree into a `human_label` column; compute overall + per-class **and per-neighborhood** agreement (the ~171-px BG would otherwise dominate). Acceptance: filled `human_label` for every sampled pixel; a stated rate against a pre-committed bar (recommend ≥90% overall and ≥90% for the tree class); record in `docs/` replacing "PENDING USER REVIEW"; below bar → revisit M1/M2/M5 before closing.

---

## 7. Figure Regeneration Plan

Style is centralized in `src/plot_style.py` (`CMAP`, `ACCENT`, `PIXEL_CLASS_COLORS`, `diverging_norm(vcenter=0)`, `sequential_norm`). **Register every new/edited PNG in the relevant step's `outputs` tuple** so `--check-deliverables` audits it.

| Fig | Content | Hook |
|---|---|---|
| **F1** | Study-area pixel-class map + 9 paired polygons | **Edit** `section10:653 make_classmap_figure` (already writes `section10_pixel_class_map.png`); register the PNG. |
| **F2** | Reference-set composition after M1 (NLCD class × impervious pctl) | **New** QA figure in `section10`; register. |
| **F3** | ΔT_cool day vs night (+4.8 / +0.4 K) | **New cell** in the §14 notebook (near cell 17); `figures/section14_dtcool_day_vs_night.png`; `ACCENT["cooling"]`. |
| **F4** | 2-D response surface VPD_z×SM_z, color=ΔT_cool, cell=`n` (BG-mean descriptive, from `master_table.parquet`) | **New** `section15` id=15 (B1b) `figures/section15_response_surface_vpdz_smz.png` + `..._day.png`; RdBu `diverging_norm(vcenter=0)`. |
| **F5** | z-score distributions + CSI | **Edit** `section11:704 make_distribution_figure` (adds a 4th CSI panel from `section12_csi_70m.zarr`). |
| **F6** | Segmented fit + cluster bootstrap CI on ΔT_cool~CSI | **Edit** `section14_segmented_and_bootstrap.png`; redraw after m5 with cluster CI + zero-break-capable changepoint; annotate CI-width/CSI-range fraction. |
| **F7** | Scatter ΔT_cool vs CSI, colored by `is_day`, sized by `n_tree_valid` | **Edit** §14 `section14_scatter_ca_vs_csi.png`. |
| **F8** | Binned ΔT_cool vs CSI + ET/ESI overlay (corroboration-only) | **Keep** §14 binned figures; label ET/ESI per m1. |
| **F9** | Sample-size / cluster diagnostic (per-BG `n_tree_px`, highlight the ~171-px BG) | **New cell** in §14 notebook. |
| **F10** | S2 valid-scene count map (m2 deliverable) | **New** `make_*` in `section4` for `s2_{ndmi,ndvi}_nscenes_2023_70m.tif`; `sequential_norm` + `CMAP["vegetation"]`. |

**Four-panel paper figure = F1, F3, F4, F7** (study-area map + day/night contrast + 2-D response surface + colored/sized scatter). Assemble as a 2×2 composite once the four source figures regenerate cleanly.

---

## 8. Paste-Ready Subagent Prompts

Each prompt is self-contained: files, exact changes, tests, guardrails (tracked/reviewable edits, run the section's tests in the project venv, re-run only affected sections, **do NOT scale to other cities**).

### Prompt — B2 (z-score std floor)

> Fix BLOCKER B2 in `/Users/jmlee/Documents/TreeProject/project/`. `section11_anomalies.py::zscore()` (`:121-132`) divides by a per-pixel climatological std with only a zero/non-finite guard (`min_std=0.0`, never passed at either production call site `:280`, `:476`), so a tiny positive std yields `|z|` in the hundreds. **Steps:** (1) Extend `zscore(observed, normal, std, min_std=0.0, *, return_n_floored=False)` to also reject finite stds `<= min_std` to NaN and, when `return_n_floored`, return `(z, int(floored.sum()))`; keep `min_std=0.0` byte-for-byte. (2) Add to `config.py` near `:110`: `MIN_STD_NDMI=0.02`, `MIN_STD_VPD=0.05`, `MIN_STD_SM=0.005` (floats, with unit comments). (3) In `compute_era5_zscores` (def `:233-236`, call `:280`) add a `min_std` kwarg, accumulate `n_floored` across the overpass loop, return it; select the per-var floor at the `:452-456` loop (`MIN_STD_VPD` for `vpd`, `MIN_STD_SM` for `sm`). (4) At `:476` pass `min_std=config.MIN_STD_NDMI, return_n_floored=True`; log the count at `:485-487`; add `ndmi_n_floored` to `meta` (`:503-504`). (5) Optionally add a max-|z| line to `record_zscore_stats` (`:583-608`). **Tests (`src/test_section11_anomalies.py`, hand-rolled `check()`/`main()`):** extend `test_zscore_degenerate_std` (floor + count, `<=` boundary); add `test_zscore_min_std_floor_caps_extreme_z` and register it in `main()`; extend `test_module_constants`; add a comment to the two NDMI temporal tests that they assume `MIN_STD_NDMI < 0.05`. **Run** `python src/test_section11_anomalies.py` → ALL CHECKS PASSED. **Re-run** only `python src/run_all.py --from 11` (11→12→13→14). **Guardrails:** tracked/reviewable edits; do not touch Sections 0–10 or any other city. Floor values are placeholders — if a `*_clim_std` histogram is available, note that the human may retune them; the plumbing is value-independent.

### Prompt — B1 (supply term + 2-D response surface)

> Fix BLOCKER B1 in `/Users/jmlee/Documents/TreeProject/project/`. The CSI "water-supply" term uses `ndmi_z` (vegetation), not water supply. **Cross-module naming invariant to preserve:** §12 primary supply = `sm_z` (drives `supply_stress`/CSI/response-surface via `mean_sm_z_tree`); §13 `WATER_SUPPLY_Z_VAR=="ndmi_z"` (column renamed `mean_ndmi_z_tree`) is the vegetation **check only**. Two "supply"-named constants, two variables, by design — add a code comment saying so where each is defined. **B1a:** (1) Add to `config.py` after `:118`: `SUPPLY_VAR="sm_z"`, `SUPPLY_ROBUST_RESCALE=True`. (2) `section12_compound_stress.py:57` → `SUPPLY_Z_VAR=config.SUPPLY_VAR`; add `CHECK_Z_VAR="ndmi_z"`; extend the `load_zscores` presence loop (`:142`) to include `CHECK_Z_VAR`. (3) Add `robust_unit_scale(z)` after `:88` (divide by IQR/1.349; sign/NaN preserved; `<2` finite → unchanged) and apply it at `:211-214` behind `config.SUPPLY_ROBUST_RESCALE`. (4) Generalize `_assert_inputs_are_zscores` (`:148-183`) to branch on `SUPPLY_Z_VAR` (for `sm_z`: accept `0.3<std<1.3` and `min<0<max`; keep the tight NDMI band for the check) plus a post-rescale `0.7<nanstd<1.3` assertion in `build_csi_dataset`; refactor the numeric core into a pure helper for testing. (5) Update supply labels (`:280-284,:295-298,:456-457,:204-206`, docstring `:1-14`). (6) Add `ndmi_z_check_spatial_mean` to `overpass_summary_table` (`:413-426`) without touching the cube. **B1b:** (7) In `section13_master_table.py`: add `SM_Z_VAR="sm_z"` near `:69`; `load_grids` (`:285`) add `"sm_z"`, keep `"ndmi_z"`; in `build_master_table` add `mean_sm_z_tree` (primary) and rename `mean_water_supply_z_tree → mean_ndmi_z_tree`; update `MASTER_COLUMNS`, `COLUMN_GROUPS`, and the `report_master_table` NaN-coverage **column tuple `("mean_et_tree",…,"aridity")` at `:609-611`** (rename must touch the full tuple, not just one line, else `KeyError`). (8) Add `local_hour`/`is_day` columns after `:433` **(these are owned by B4 as the single source of truth; if B4 has landed, they already exist — do not re-derive; if implementing B1b first, add `int((hour-7)%24)` / `7<=h<19`, Arizona MST no DST, and B4 will consume the same columns)**. (9) New `src/section15_response_surface.py` with pure `binned_surface(vpd_z, supply_z, cooling, ...)` (digitize, drop out-of-range + NaN pairwise, empty→NaN/0) and `plot_response_surface(...)` → `figures/section15_response_surface_vpdz_smz.png` + `..._day.png` (RdBu `diverging_norm(vcenter=0)`, per-cell `n`); this surface is **BG-mean descriptive**, reads `master_table.parquet`, uses `mean_sm_z_tree`. (10) Register `Step(id=15, module="src/section15_response_surface.py", outputs=(...), network=False)` **after id=14 and before the id=16 mixed-effects step** in `run_all.py` (id=15 = response surface, id=16 = mixed effects — do NOT reuse id=15 for both); demote CSI to secondary in the `section12` docstring. **Tests:** update the supply-constant assertions in `test_section12_compound_stress.py`; add `test_supply_source_is_soil_moisture`, `test_robust_unit_scale_restores_unit_spread`, `test_input_guard_accepts_sm_z_rejects_raw`; new `test_section15_response_surface.py`; update `test_section13_master_table.py` schema test (keep `WATER_SUPPLY_Z_VAR=="ndmi_z"`, add `SM_Z_VAR=="sm_z"`). **Run** the three section test files. **Re-run** `python src/run_all.py --from 12` (sweeps ids 12→13→14→15). **Guardrails:** tracked/reviewable edits; keep the honesty gate; do NOT scale to other cities.

### Prompt — B3 (pixel-level unit of analysis + mixed model + cluster bootstrap)

> Fix BLOCKER B3 in `/Users/jmlee/Documents/TreeProject/project/`. The master table is BG-mean-aggregated. **B3.1:** (1) In `section13_master_table.py` add `PIXEL_PARQUET="master_pixel_table.parquet"` (`:59`) and `PIXEL_COLUMNS`; add `build_pixel_table(grids, static)` after `:470` — one row per finite tree pixel carrying its BG×overpass reference-mean LST (`cooling_advantage_px = mean_ref_lst − tree_lst`), with **per-pixel** `vpd_z/ndmi_z/csi` and BG-level `aridity`, reusing the same `t`-loop, `static.attrs["tree_px_by_geoid"]`/`["ref_px_by_geoid"]` (per-pixel indices from `tree_px_by_geoid = np.where(tree_mask)` at `:325`), `np.concatenate([trr,rfr])`, `_zonal_at`, and `row_emittable`. (2) Wire into `run()` after `:754-755`; add `verify_pixel_table` (unique `(neighborhood_id,overpass_key,pixel_row,pixel_col)`, identity atol 1e-5, `nunique<=9`, counts `>=1`); register the parquet in step-13 `outputs` (`run_all.py:205`). **M5:** (3) Add `PRIMARY_MIN_TREE_PX=3` to `config.py`; add `sample_label` (`"primary"` iff `n_tree_valid>=3`) to both tables and to `MASTER_COLUMNS`/`PIXEL_COLUMNS`; keep `row_emittable` at `>=1`; compute and log the exact `n_tree_valid<3` drop fraction. **B3.2 (new `src/section14b_mixed_effects.py`, registered as run_all step id=16 — NOT id=15; id=15 is the B1b response surface):** (4) Load `master_pixel_table.parquet` filtered to `sample_label=="primary" & is_day`; **read the persisted `local_hour`/`is_day` columns — do NOT re-derive them (B4 is the single source of truth and must land first)**; Mundlak decomposition (`_within`, `_bg_mean` for `vpd_z`, `ndmi_z`); fit crossed random intercepts via `statsmodels` (`groups=neighborhood_id`, `vc_formula={"overpass":"0 + C(overpass_key)"}`); report both variance components; handle the dominant BG via crossed intercept + inverse-cluster-size weighting + leave-dominant-BG-out refit; emit `docs/section14b_mixed_effects_note.md`. **B3.3 (consumes, does NOT re-implement, the m5 edit):** (5) The `groups=` cluster-resampling on `bootstrap_breakpoint` (`section14_threshold.py:207-257`), its forwarding through `analyze_sample` (`:449`), and the notebook `groups=df["neighborhood_id"]` pass-through are **owned by m5** — do NOT re-add them here; B3.3's own work is applying the same BG-cluster resampling to the **B3.2 mixed-model CI** (refit per resample). If m5 has not landed, land the m5 `bootstrap_breakpoint` edit first. **Tests:** `test_pixel_table_shape_and_identity`, `test_sample_label_primary_floor` (`test_section13`); new `test_section14b_mixed_effects.py` (guard the `statsmodels` import) incl. the mixed-model BG-cluster-CI-wider test. **Run** the affected section test files in the venv. **Re-run** `python src/run_all.py --from 13` (sweeps ids 13→14→15) then `python src/section14b_mixed_effects.py` (id=16, invoked directly after Section 13 rebuilds so B4's `is_day` columns exist). **Guardrails:** `statsmodels` is a NEW dependency — declare it, do not assume it. Consume **B2-floored** `ndmi_z`. Tracked/reviewable edits; do NOT scale to other cities.

### Prompt — B4 (day/night pooling)

> Fix BLOCKER B4 in `/Users/jmlee/Documents/TreeProject/project/`. The threshold verdict pools day (+4.8 K) and night (+0.4 K) overpasses. **B4 is the single source of truth for `local_hour`/`is_day`** — it persists them as Section 13 columns; B3.2's mixed model and B1b's day-variant surface READ these columns and do not re-derive time-of-day. B4 must land before B3.2. (1) In `section13_master_table.py::build_master_table` add persisted `local_hour=int((pd.Timestamp(times[t]).hour-7)%24)` and `is_day=bool(7<=...<19)` (Arizona MST, no DST; `times[t]` is tz-naive UTC — add a comment that any DST-state extension must use `zoneinfo`; this matches notebook cell 4 / line 282). (2) **Append** both to `MASTER_COLUMNS` (`:489`) and `COLUMN_GROUPS["identifiers"]` (`:507`) **after `"city"`** so the `MASTER_COLUMNS[:4]` schema assertion (`test_section13:191-193`) stays valid. (3) Add `split_day_night(is_day, keep_mask=None)` to `section14_threshold.py` near `:44`. (4) In `notebooks/14_exploratory_threshold.ipynb` cell 20, rewrite `make_sample(min_count, part="day")` and `SAMPLES` so day-only is PRIMARY (`A_day_full`) with `N_night_full` and `P_pooled_full` as labelled contrasts; report `A_day_full` as the primary verdict in cells 21/26; optionally simplify cell 4 to READ the persisted `local_hour`/`is_day` (keep `month`). (5) Elevate the day/night contrast (cell 17) to a numbered result; rewrite `docs/section14_results_note.md:168-172`. (6) (Recommended) add pure `daynight_contrast(x, y, is_day)` (OLS interaction via `lstsq`) and print `delta_intercept`. **Tests:** extend `test_module_constants_and_schema` with two `check`s (do NOT touch the `[:4]` assertion); add `test_local_hour_and_is_day_derivation` (`test_section13`); add `test_split_day_night`, `test_night_does_not_flatten_day_signal`, `test_daynight_contrast` (`test_section14`); register all in `main()`. **Run** both test files in the venv (needs `pwlf`+`ruptures`). **Re-run** `python src/run_all.py --from 13`. **Guardrails:** day-only will likely still be "no robust threshold" — that is the *right* reason (thin sample), not the wrong one (night dilution); state it. Tracked/reviewable edits; do NOT scale to other cities.

### Prompt — Phase A (combined correctness fixes)

> Apply Phase A correctness fixes in `/Users/jmlee/Documents/TreeProject/project/` in this order, as separate reviewable commits. **B2** (Section 11) — per-variable z-score std floor (see the B2 prompt). **M3** (`section2_ecostress_lst.py`) — widen `qc_best_quality_mask` (`:142-145`) to `(qc & 0b11) <= 0b01` (keep QC 00 and 01, drop 10/11); add `QC_MAX_KEPT_MANDATORY=0b01` (`:65`) and a per-granule `n_valid_best_only` audit; **FIRST confirm the ECOSTRESS v002 mandatory-QA spec that `01` = nominal/good, not degraded — if degraded, record won't-fix and skip.** **M4** (`section9_harmonize.py:265-271`) — make `select_by_time` fail on a missing PRISM date: `method="nearest", tolerance=pd.Timedelta(0)`, catch `KeyError` → all-NaN grid + warning + a missing-count log (recommended option A). **M6** (`section7_precip_drought.py`) — capture `col.aggregate_array("system:time_start")` at `:668-671`, add `band_dates` to `DroughtDownload` (`:637-644`, populate all four returns), replace the silent `continue` at `:876-877` with a pure `resolve_band_date(...)` that raises on unresolvable, add the runtime consistency check, fix the parser docstring `:254-256`. **M1** (`section10_classify_pixels.py`) — add `REF_IMPERV_MIN=20.0`, `REF_BUILT_CLASSES=(22,23,24)` to `config.py`; thread `impervious`/`imperv_min`/`ref_built_classes` through `reference_mask` (`:116-127`), `classify` (`:194-195`), `start_params` (`:356-370`), and EVERY `classify` caller (`:210-232,:388-397,:796-802`). **M2** (same file) — remove the `OP_MIN_PAIRED`-gated selection in `derive_operating_canopy_thr` (`:382-411`): delete the `paired_by_ct` build loop and the `OP_MIN_PAIRED` highest-first selection loop (this function picks the highest `OP_CANDIDATES` value clearing `OP_MIN_PAIRED`, falling back to `OP_FLOOR` — it is NOT an argmax; do not anchor the deletion to a stale `:388-398,:400-407` line pair); commit a pre-committed criterion (P90 of canopy over NDVI-qualifying, building-excluded pixels — NOT the whole grid, whose mean is 0.88%); keep the `OP_FLOOR` clamp; set `config.CANOPY_THR` to the derived value and keep the run-time equality assert. **Tests:** add/update the per-section tests named in each card (hand-rolled `check()`/`main()`); the M2 test must assert the derived threshold is **invariant to paired-BG yield / `bg_index`**; run each affected `python src/test_sectionN_*.py` in the venv. **Re-run:** `python src/run_all.py --only 2 --skip-download`; `--only 7 --skip-download`; then `--from 9`. **Guardrails:** tracked/reviewable edits; M1+M2 may drop paired BGs below 9 — accept and report the count; do NOT scale to other cities.

---

## 9. Open Decisions for the Human

1. **Supply variable (B1a).** `sm_z` (recommended — computed, physical, lowest-effort) vs `spei90d` (needs a Section 13 column add from the cube; antecedent-90d, coarser) vs augment (mean of both). NDMI stays a vegetation check regardless.
2. **`sm_z` variance handling (B1a).** Robust IQR rescale (recommended) vs no rescale + let m3 weights absorb the variance vs re-standardize over the pilot window. The compressed variance is a real single-year property — do not "fix" upstream.
3. **z-score floor values (B2).** Calibrate `MIN_STD_{NDMI,VPD,SM}` from a histogram of the three `*_clim_std` fields already in the store (set at the low-tail degenerate spike, ~1st pctile); and reject-to-NaN vs clip-the-std.
4. **Canopy threshold criterion (M2).** Percentile value (85/90/95) over the NDVI-qualifying pool vs a fixed justified constant; whether to keep `OP_FLOOR=40` as a hard clamp. Accept that M1+M2 may push paired BGs below 9.
5. **Reference-set restriction (M1).** Impervious floor vs drop NLCD 21 vs both (recommended, with documented `cooling_advantage` sensitivity under each).
6. **ECOSTRESS v002 QC spec (M3).** Confirm that mandatory-QA `01` = nominal/good (not degraded) before widening — the one true blocker to the fix; rests on the v002 User Guide, not the code.
7. **PRISM missing-date policy (M4).** Explicit NaN + tripwire count (recommended) vs hard error.
8. **`ruptures` penalty API (m5).** Confirm `rpt.Pelt(...).predict(pen=...)` (or `rpt.Binseg`) in the pinned version; else use the explicit 0-vs-1-break AIC/BIC wrapper. Also the penalty default and the tightened tolerance (0.10 vs dropping the tolerance path).
9. **Modeling library (B3.2).** `statsmodels` (new dependency, not currently importable) vs `pymer4`/lme4 (needs R). Crossed-RE fallback (BG fixed effects + overpass RE, or GEE) if variance components hit the boundary at ≈9 BGs. Cluster-bootstrap method (wild-cluster/Rademacher for ≤9 clusters).
10. **Primary-sample floor (M5).** `n_tree_valid>=3` (default) vs `>=5` (may starve the mixed model). Day/night cut (`7<=h<19` vs a stricter clean-day window).
11. **ACS/TIGER vintage (m4).** Confirm 2024 ACS5 BG tables are released; hold 2024 for reproducibility of the 264-row result vs bump; keep ACS and TIGER years equal.
12. **S2 cloud gate (m2)** and **ESI ceiling (m1).** 30 vs 40% (and whether to re-pull 4b scenes); 1.5 vs 1.2 ESI advisory ceiling.
13. **Tree-pixel validation bar (reproducibility).** The ≥90% agreement pass bar, and per-neighborhood vs weighted reporting given the one dominant ~171-px BG.

---

**Deliverable status:** master plan complete. Priority path: **Phase A (B2, M3, M4, M6, M1, M2) → re-run 9–14 → Phase B (B1, B3, B4, m3, m5) → re-run 12/13→14→15 + invoke id=16 → figures → close tree-pixel validation → Phase C scale-out.** Registry ids: `section15_response_surface = id=15`, `section14b_mixed_effects = id=16`. Ordering within Phase B: B4 (persists `local_hour`/`is_day`) before B3.2 (reads them); m5 owns the `bootstrap_breakpoint` cluster edit, B3.3 consumes it. Every fix card, test, and re-run command above preserves the concrete file:line anchors for direct execution. Do not begin Phase C until Phoenix settles.
