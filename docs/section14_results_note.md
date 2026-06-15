# Section 14 — First threshold estimate for Phoenix (results note)

**The first scientific result of the Urban Canopy Thermal Thresholds pilot, and the end of the
data-preparation pipeline.** This note records the pilot threshold estimate, its uncertainty from
two independent methods, the ET corroboration, and — decisively for the interpretation — the
data-adequacy caveats.

**Source:** `notebooks/14_exploratory_threshold.ipynb` (steps 72–79), reading only
`data/processed/master_table.parquet` (264 rows × 26 cols; one row per paired neighborhood per
overpass; 9 paired block groups × 54 overpasses). Reusable analysis logic in
`src/section14_threshold.py` (unit-tested in `src/test_section14_threshold.py`).

---

## Headline verdict

> **No robust threshold detected** between the tree cooling advantage and the Compound Stress
> Index (CSI) for the Phoenix pilot.

This is a **valid scientific outcome**, not a failure. The protocol's *common pitfall* warns that
a segmented (piecewise) regression **always** returns a breakpoint — even on a straight line or
pure noise — so a threshold is reported as credible **only if** (i) the two independent methods
agree within their uncertainty, (ii) a bend is visible in the binned plot, and (iii) ET declines
beyond the same CSI level. **None of the three criteria is met**, in any of the three samples
tested (full 9-BG sample, modest filter, robust single-BG subset).

---

## The two threshold methods and their estimates

For each sample we fit a one-breakpoint segmented regression (`pwlf`, step 76), bootstrap the
breakpoint by resampling rows (1000 resamples, step 77), and independently estimate a single
change point on the CSI-ordered cooling-advantage sequence (`ruptures`, l2 mean-shift, step 78).

| sample | n (rows) | BGs | segmented breakpoint | bootstrap 95 % CI | CI width / CSI range | `ruptures` change-point | methods agree on a *well-identified* break? |
|---|---|---|---|---|---|---|---|
| **A — full** (`n_tree_valid ≥ 1`) | 264 | 9 | CSI ≈ **0.478** | **(0.000, 0.738)** | **62 %** | 0.523 | **No** — CI not identified |
| **B — modest** (`n_tree_valid ≥ 3`) | 107 | 4 | CSI ≈ 0.709 | (0.000, 0.833) | 88 % | 0.741 | **No** — CI not identified |
| **C — robust** (`n_tree_valid ≥ 10`) | 31 | 1 | CSI ≈ 0.812 | (0.000, 0.867) | 97 % | 0.000 | **No** — methods disagree |

**Interpretation of the uncertainty.** In every sample the bootstrap CI spans **62–97 % of the
observed CSI range** — i.e. the breakpoint is **not identified**: across resamples it jumps
between completely different locations (the full-sample bootstrap distribution is multimodal, with
spikes near 0.0, 0.08, 0.47 and 0.74). A "point" breakpoint of 0.478 with a CI of (0.000, 0.738)
is not a measurement of a threshold; it is what a flat relationship produces. In the robust subset
the two methods do not even coincide (segmented 0.81 vs change-point 0.00). **The two methods do
not agree on a well-identified threshold.**

---

## Why "no threshold": the supporting evidence

**1. The relationship is essentially flat (step 72).** Cooling advantage vs CSI, one point per
neighborhood per overpass:

| sample | Pearson r (p) | Spearman r | OLS slope | linear R² |
|---|---|---|---|---|
| A — full | −0.052 (p = 0.40) | −0.082 | −0.78 K / CSI unit | 0.003 |
| B — modest | −0.093 (p = 0.34) | −0.097 | −1.39 | 0.009 |
| C — robust | +0.038 (p = 0.84) | +0.093 | +0.59 | 0.001 |

All correlations are within ±0.1 of zero with p ≫ 0.05; the line explains ~0 % of the variance.
There is no monotonic decline of cooling advantage with compound stress to put a threshold on.
(`figures/section14_scatter_ca_vs_csi.png`.)

**2. No credible bend in the binned plot (step 73).** Mean cooling advantage is **flat at ≈ +3.5
to +4.5 K from CSI ≈ 0 out to ≈ 0.7** (bin sizes n = 121, 44, 29, 35, 23), then appears to drop —
but the downturn rests entirely on the **two sparsest bins (n ≈ 10 and n = 1)**, whose error bars
overlap the plateau. A bend that depends on the one or two most thinly-populated bins is not a
credible bend. (`figures/section14_binned_ca_vs_csi.png`.)

**3. The segmented kink is not worth it over a straight line (step 76).** Linear-vs-segmented
comparison:

| sample | ΔR² (segmented − linear) | ΔAIC (segmented − linear) | segmented preferred by AIC? |
|---|---|---|---|
| A — full | +0.010 | **+1.35** | No |
| B — modest | +0.023 | **+1.52** | No |
| C — robust | +0.060 | **+2.09** | No |

In every sample the kink improves R² only trivially and **AIC is *higher* for the segmented model
(ΔAIC > 0)** — the straight line is the better-supported model. The data look like a flat line, not
a kink. (`figures/section14_segmented_and_bootstrap.png`, left panel.)

**4. No ET corroboration (step 74).** The mechanistic signature would be ET falling beyond the
same CSI level. Over the populated CSI bins, **mean ET does not decline systematically with CSI**
(it is roughly flat / non-monotonic; ESI is near-flat at ~0.55–0.61). The coarse below/above-
breakpoint ET comparison is weak and inconsistent across samples (full sample: ET 197.7 → 182.6
W m⁻², a small drop on the well-sampled side; modest and robust subsets: ET *rises* above the
candidate break, with only n = 4 and n = 1 ET rows above it). There is no CSI level beyond which
both cooling advantage and ET clearly decline together. (`figures/section14_binned_et_esi_overlay.png`.)

---

## Data-adequacy caveats (decisive for the interpretation)

These are not caveats *on* a threshold — they explain *why no robust threshold can be resolved* in
the pilot, and are the reason this section is the gate into the cross-city phase.

- **Thin paired sample.** The paired design has only **9 block groups**, and **one**
  (`040139412001`, ~171 tree pixels) dominates; the other eight rest on **1–6 tree pixels**
  (median `n_good_obs` = 2; ~59 % of rows on ≤ 2 valid tree pixels). The most extreme cooling
  advantages (e.g. **+23 K**, **−6.3 K**) rest on a **single** tree pixel — noise the count columns
  expose. We did **not** clip outliers (the protocol's rule); instead we filtered by minimum count
  and reported the sensitivity.
- **Min-count sensitivity — full vs robust subset (step 75).** A strict filter (`n_tree_valid ≥
  10`) collapses the sample to the **single well-sampled BG**, leaving a ~temporal-only series with
  no spatial contrast to define a threshold (n = 31, 1 BG; correlation +0.04, p = 0.84). The full
  9-BG sample is noisy; the robust subset is degenerate. **Both** point to no threshold, for
  complementary reasons — they reconcile to the same verdict.
- **The CSI axis is ≈ a VPD-demand axis.** The water-supply (NDMI) z is a **static-in-time spatial**
  field (Section 11/12), so the CSI's row-to-row variation is **almost entirely temporal VPD
  demand**: the between-BG spread of BG-mean CSI (std ≈ 0.027) is ~10× smaller than the within-BG
  temporal std (≈ 0.264). A "threshold in CSI" here would really be a **VPD-demand** threshold —
  and even that is not resolved at this sample size.
- **Diurnal structure.** The cooling advantage is overwhelmingly a **daytime** effect (mean **+4.8
  K** by day vs **+0.4 K** at night; **40 %** of night/pre-dawn rows are negative vs **8 %** by day).
  The negatives are concentrated pre-dawn (canopy can be marginally warmer than open built surfaces
  overnight). The threshold analysis pools all overpasses per the protocol ("one point per
  neighborhood per overpass"); the day/night split is noted as a sensitivity, not a separate model.
- **ET coverage.** `mean_et_tree` / `mean_esi_tree` are NaN on ~22.7 % of rows (the non-ET
  overpasses); the ET overlay and below/above check drop these pairwise, never impute.

---

## Conclusion

The Phoenix pilot data **cannot support a robust cooling-advantage vs compound-stress threshold**.
The relationship is flat, the segmented kink is not preferred over a straight line, the breakpoint
is not identified by the bootstrap, the two methods do not agree on a well-identified break, and ET
provides no mechanistic corroboration. A defensible threshold would require a **denser tree sample
across more neighborhoods** (and a CSI axis with real spatial supply-stress contrast) — which is
exactly what the **cross-city phase** this section gates into is designed to provide. Reporting
"no robust threshold detected" here, rather than a manufactured breakpoint, is the scientifically
correct outcome and satisfies the protocol's honesty gate.

### Reproducibility

Every number and figure above is produced by `notebooks/14_exploratory_threshold.ipynb` from
`data/processed/master_table.parquet` alone, calling `src/section14_threshold.py`
(`segmented_fit`, `bootstrap_breakpoint`, `changepoint_csi`, `bin_means`, `apply_min_count`,
`et_declines_beyond`, `threshold_verdict`). The analysis logic is unit-tested in
`src/test_section14_threshold.py` (all checks pass), including the protocol's pitfall: the
segmented fit **does** return a breakpoint on a straight line and on pure noise — which is why the
multi-criteria gate, not a single fit, decides the verdict.
