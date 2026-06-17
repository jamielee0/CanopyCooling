# Section 14 — First threshold estimate for Phoenix (results note)

**The first scientific result of the Urban Canopy Thermal Thresholds pilot, and the end of the
data-preparation pipeline.** This note records the pilot threshold estimate, its uncertainty from
two independent methods, the ET corroboration, and — decisively for the interpretation — the
data-adequacy caveats.

> **This is the re-run on branch `temporal-ndmi-supply` (time-varying CSI supply axis).** The CSI
> supply axis was unfrozen: the NDMI water-supply z-score is now a **temporal day-of-year
> leave-one-year-out anomaly** (§4b / §11 / §12) instead of a static-in-time spatial field, so
> `mean_csi_tree` and `mean_water_supply_z_tree` now vary **per overpass and across
> neighborhoods**. `cooling_advantage` (from LST) is unchanged. The original static-NDMI result is
> preserved on `main`, commit `711c7f9`. An explicit **old-vs-new comparison** is in the next
> section. **Headline: the "no robust threshold" verdict persists** — the supply axis is now
> demonstrably richer, but the relationship is still flat and the threshold still not identified;
> the binding limitation is now the (unchanged) thin sample, not the supply freeze.

**Source:** `notebooks/14_exploratory_threshold.ipynb` (steps 72–79), reading only
`data/processed/master_table.parquet` (264 rows × 26 cols; one row per paired neighborhood per
overpass; 9 paired block groups × 54 overpasses). Reusable analysis logic in
`src/section14_threshold.py` (unit-tested in `src/test_section14_threshold.py`).

---

## Headline verdict

> **No robust threshold detected** between the tree cooling advantage and the Compound Stress
> Index (CSI) for the Phoenix pilot — and the verdict is **unchanged** by unfreezing the CSI
> supply axis (the null **persists**).

This is a **valid scientific outcome**, not a failure. The protocol's *common pitfall* warns that
a segmented (piecewise) regression **always** returns a breakpoint — even on a straight line or
pure noise — so a threshold is reported as credible **only if** (i) the two independent methods
agree on a *well-identified* break, (ii) a bend is visible in the binned plot, and (iii) ET
declines beyond the same CSI level. **None of the three criteria is met**, in any of the three
samples tested (full 9-BG sample, modest filter, robust single-BG subset).

---

## Old vs new — did unfreezing the supply axis move the result?

The whole point of this re-run. `cooling_advantage` is identical; only the CSI (its supply half)
changed.

| quantity | **original** (static NDMI, `main` 711c7f9) | **this re-run** (temporal NDMI) | moved? |
|---|---|---|---|
| CA–CSI **Pearson r** (full) | −0.052 (p = 0.40) | **+0.023 (p = 0.71)** | sign flipped, still ≈ 0 |
| Spearman r (full) | −0.082 | **+0.014** | still ≈ 0 |
| OLS slope (full) | −0.78 K / CSI | **+0.28 K / CSI** | still ≈ 0 |
| linear **R²** (full) | 0.003 | **0.0005** | still ≈ 0 |
| segmented **breakpoint** (full) | 0.478 | **0.736** | wanders (flat → unstable) |
| bootstrap **95 % CI** (full) | (0.000, 0.738) = **62 %** of range | **(0.001, 0.919) = 61 %** | still **not identified** |
| `ruptures` **change-point** (full) | 0.523 | **0.630** | — |
| **ΔAIC** seg−lin (full / modest / robust) | +1.35 / +1.52 / +2.09 | **+2.93 / +0.52 / +0.85** | **all still > 0** (line preferred) |
| ET corroboration | absent / inconsistent | **absent / inconsistent** | unchanged |
| **between-BG CSI std** | **0.027** | **0.081** | **~3× richer** ✅ |
| within-BG (temporal) CSI std | 0.264 | 0.316 | larger |
| within/between ratio | **~10×** | **~4×** | **supply axis less dominated by demand** ✅ |
| CSI range (max) | ~1.19 | ~1.50 | wider |
| **VERDICT** | **no robust threshold** | **no robust threshold (persists)** | **unchanged** |

**What genuinely changed:** the CSI axis is now **richer**. Unfreezing the NDMI supply z roughly
**tripled the between-neighborhood (spatial) spread** of BG-mean CSI (0.027 → 0.081) and cut the
within/between ratio from ~10× to ~4×. The "CSI ≈ a pure VPD-demand axis" problem — the deepest
reason the original pilot blamed for the null — **is now fixed**: the supply side contributes real
spatial contrast across the 9 neighborhoods.

**What did *not* change:** the cooling-advantage vs CSI relationship is still flat (|r| ≈ 0.02),
the segmented kink is still not preferred over a straight line (ΔAIC > 0 in all three samples), the
breakpoint is still not identified (bootstrap CI spans 61–99 % of the range), and ET still provides
no consistent corroboration. **Fixing the supply axis did not produce a threshold.**

---

## The two threshold methods and their estimates (new)

For each sample we fit a one-breakpoint segmented regression (`pwlf`, step 76), bootstrap the
breakpoint by resampling rows (1000 resamples, step 77), and independently estimate a single
change point on the CSI-ordered cooling-advantage sequence (`ruptures`, l2 mean-shift, step 78).

| sample | n (rows) | BGs | segmented breakpoint | bootstrap 95 % CI | CI width / CSI range | `ruptures` change-point | well-identified break? |
|---|---|---|---|---|---|---|---|
| **A — full** (`n_tree_valid ≥ 1`) | 264 | 9 | CSI ≈ **0.736** | **(0.001, 0.919)** | **61 %** | 0.630 | **No** — CI not identified |
| **B — modest** (`n_tree_valid ≥ 3`) | 107 | 4 | CSI ≈ 0.053 | (0.050, 0.879) | 75 % | 0.047 | **No** — CI not identified |
| **C — robust** (`n_tree_valid ≥ 10`) | 31 | 1 | CSI ≈ 0.226 | (0.023, 0.925) | 99 % | 0.169 | **No** — CI not identified |

**Interpretation of the uncertainty.** In every sample the bootstrap CI spans **61–99 % of the
observed CSI range** — i.e. the breakpoint is **not identified**: across resamples it jumps between
completely different locations. A "point" breakpoint with a CI that wide is not a measurement of a
threshold; it is what a flat relationship produces. (Note: with the documented tolerance the
`ruptures` change-point now technically lands "within tolerance" of the segmented breakpoint in all
three samples — but only because *both* estimates are unstable on a flat cloud; the
**well-identified** gate, which requires the CI to be < 50 % of the range, rejects every sample. So
there is still **no agreement on a well-identified threshold**.)

---

## Why "no threshold": the supporting evidence (new run)

**1. The relationship is essentially flat (step 72).** Cooling advantage vs CSI, one point per
neighborhood per overpass:

| sample | Pearson r (p) | Spearman r | OLS slope | linear R² |
|---|---|---|---|---|
| A — full | +0.023 (p = 0.71) | +0.014 | +0.28 K / CSI unit | 0.0005 |
| B — modest | (slope −0.99) | — | −0.99 | 0.005 |
| C — robust | (slope +1.13) | — | +1.13 | 0.005 |

All correlations are within ±0.1 of zero with p ≫ 0.05; the line explains ~0 % of the variance.
There is no monotonic decline of cooling advantage with compound stress to put a threshold on.
(`figures/section14_scatter_ca_vs_csi.png`.)

**2. No credible bend in the binned plot (step 73).** Mean cooling advantage is **flat at ≈ +3.3
to +4.3 K across the whole CSI range** (bin sizes n = 100, 58, 40, 33, 22, 6, 2, 3 from CSI ≈ 0.09
out to ≈ 1.40) — it even rises slightly through the mid bins. The only dip is a single sparse bin
near CSI ≈ 1.0 (n = 6 → +2.6 K), and the two highest bins recover to +2.9 / +3.6 K; their error
bars overlap the plateau. **A dip that depends on one sparse bin is not a credible bend** — and it
is absent even though the CSI now extends further (to ≈ 1.5) with real spatial supply contrast.
(`figures/section14_binned_ca_vs_csi.png`.)

**3. The segmented kink is not worth it over a straight line (step 76).** Linear-vs-segmented
comparison:

| sample | ΔR² (segmented − linear) | ΔAIC (segmented − linear) | segmented preferred by AIC? |
|---|---|---|---|
| A — full | +0.004 | **+2.93** | No |
| B — modest | +0.032 | **+0.52** | No |
| C — robust | +0.096 | **+0.85** | No |

In every sample the kink improves R² only trivially and **AIC is *higher* for the segmented model
(ΔAIC > 0)** — the straight line is the better-supported model. The data look like a flat line, not
a kink. (`figures/section14_segmented_and_bootstrap.png`, left panel.)

**4. No ET corroboration (step 74).** The mechanistic signature would be ET falling beyond the same
CSI level. Over the populated CSI bins, **mean ET does not decline systematically with CSI** (≈ 213
→ 183 → 179 → 186 → 194 W m⁻² across the first five bins, then noisy on the sparse high-CSI bins;
ESI near-flat ~0.53–0.60). The coarse below/above-breakpoint ET comparison is weak and
**inconsistent across samples** (full and modest: ET declines above the candidate break — 195.9 →
186.0 and 239.1 → 200.6 W m⁻²; robust subset: ET *rises*, 167.0 → 219.2, on n_above driven by the
single well-sampled BG). There is no CSI level beyond which both cooling advantage and ET clearly
decline together. (`figures/section14_binned_et_esi_overlay.png`.)

---

## Data-adequacy caveats (decisive for the interpretation)

These are not caveats *on* a threshold — they explain *why no robust threshold can be resolved* in
the pilot, and are the reason this section is the gate into the cross-city phase.

- **Thin paired sample (UNCHANGED — now the binding limitation).** The paired design has only **9
  block groups**, and **one** (`040139412001`, ~171 tree pixels) dominates; the other eight rest on
  **1–6 tree pixels** (median `n_good_obs` = 2; ~59.5 % of rows on ≤ 2 valid tree pixels). The most
  extreme cooling advantages (e.g. **+23 K**, **−6.3 K**) rest on a **single** tree pixel — noise
  the count columns expose. We did **not** clip outliers (the protocol's rule); instead we filtered
  by minimum count and reported the sensitivity. **This limitation is identical to the original run
  and is unaffected by the supply-axis fix.**
- **Min-count sensitivity — full vs robust subset (step 75).** A strict filter (`n_tree_valid ≥
  10`) collapses the sample to the **single well-sampled BG**, leaving a ~temporal-only series with
  little spatial contrast to define a threshold (n = 31, 1 BG). The full 9-BG sample is noisy; the
  robust subset is degenerate. **Both** point to no threshold, for complementary reasons — they
  reconcile to the same verdict.
- **The CSI axis is now genuinely two-sided (CHANGED — the fix worked, but didn't help).** With the
  time-varying NDMI supply z, the between-BG spread of BG-mean CSI is now **0.081** (≈ 3× the
  static-NDMI 0.027) and the within/between ratio is **~4×** (was ~10×). So the CSI is **no longer ≈
  a VPD-demand axis** — the supply half now varies in space and time. The original note flagged the
  supply freeze as the deepest reason for the null; **that reason is now removed, and the null still
  stands**, which isolates the thin sample as the remaining cause.
- **Diurnal structure.** The cooling advantage is overwhelmingly a **daytime** effect (mean **+4.8
  K** by day vs **+0.4 K** at night; **39.7 %** of night/pre-dawn rows are negative vs **8.2 %** by
  day). The negatives are concentrated pre-dawn (canopy can be marginally warmer than open built
  surfaces overnight). The threshold analysis pools all overpasses per the protocol ("one point per
  neighborhood per overpass"); the day/night split is noted as a sensitivity.
- **ET coverage.** `mean_et_tree` / `mean_esi_tree` are NaN on ~22.7 % of rows (the non-ET
  overpasses); the ET overlay and below/above check drop these pairwise, never impute.

---

## Conclusion

The Phoenix pilot data **still cannot support a robust cooling-advantage vs compound-stress
threshold**, even with the CSI supply axis unfrozen. The relationship is flat, the segmented kink
is not preferred over a straight line, the breakpoint is not identified by the bootstrap, the two
methods do not agree on a well-identified break, and ET provides no consistent mechanistic
corroboration. **The supply-axis fix worked** — the between-neighborhood CSI spread roughly tripled
(0.027 → 0.081) and the CSI is no longer ≈ a pure VPD-demand axis — **but it did not reveal a
threshold**, which is itself an important finding: it **isolates the thin 9-neighborhood /
one-dominant-BG / median-`n_good_obs`-2 sample** (unchanged here) as the remaining obstacle. A
defensible threshold would require a **denser tree sample across more neighborhoods** — which is
exactly what the **cross-city phase** this section gates into is designed to provide. Reporting "no
robust threshold detected" here, rather than a manufactured breakpoint, is the scientifically
correct outcome and satisfies the protocol's honesty gate.

### Reproducibility

Every number and figure above is produced by `notebooks/14_exploratory_threshold.ipynb` from
`data/processed/master_table.parquet` alone, calling `src/section14_threshold.py`
(`segmented_fit`, `bootstrap_breakpoint`, `changepoint_csi`, `bin_means`, `apply_min_count`,
`et_declines_beyond`, `threshold_verdict`). The analysis logic is unit-tested in
`src/test_section14_threshold.py` (all checks pass), including the protocol's pitfall: the
segmented fit **does** return a breakpoint on a straight line and on pure noise — which is why the
multi-criteria gate, not a single fit, decides the verdict.
