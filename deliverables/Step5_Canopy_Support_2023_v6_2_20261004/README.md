# Step 5 canopy support and quadratic design audit

Completed 4 October 2026 for the existing eleven Phoenix and five Atlanta 2023 passes. This packet completes the predictor-only audit recommended in Step 4. It reads only canopy, the six controls and physical-cell metadata from the cached paired samples. It does not estimate temperature/flux outcomes or display new effects. The question of proceeding to internal quadratic fitting remains pending clarification; the existing Step 4 fitting hold is preserved.

**All sixteen original samples identify both the linear design and the protected quadratic design. All 32,000 prospectively specified whole-group design resamples are estimable in both designs.** This establishes numerical design feasibility for these samples/draws. It does not establish a cooling curve, statistical evidence of curvature, causal comparability between cities or a scale-agreement ruling.

## Endpoint support

The historical endpoints are canopy fractions 0.028509538620710373 and 0.12850953862071038. Fifteen candidate pairs were frozen before reading predictor values: this pair, four neighbours shifted by ±1/±2 percentage points, and lower endpoints 0%, 10%, …, 90%, each with a +10pp upper endpoint. All candidates are reported; none was selected using outcomes.

Counts are shown at neighbourhood halfwidths of ±1, ±2.5 and ±5 percentage points. Bands are closed and clipped to [0,1]; their actual widths and any shared boundary cells are explicit. These are descriptive settings, not replacement eligibility cutoffs. Exact block spanning requires observed minimum canopy ≤ the lower endpoint and maximum canopy ≥ the upper endpoint. A cell close to an endpoint does not prove support for the endpoint itself.

| Historical-pair support, range across passes | Phoenix | Atlanta |
| --- | ---: | ---: |
| Blocks spanning both exact endpoints | 880–1,479 | 1,174–2,397 |
| Original cells in those blocks | 45.4%–50.3% | 34.2%–38.3% |
| Cells within ±1pp of lower endpoint | 23.7%–24.9% | 4.1%–5.4% |
| Cells within ±1pp of upper endpoint | 2.0%–2.5% | 3.4%–3.6% |

The historical pair has block-range support in every pass, reproducing Step 3's counts exactly. Its upper endpoint is much less densely represented than its lower endpoint in Phoenix. Moving the pair changes reference coverage in opposite directions across the cities. For example, the prospectively listed 20%–30% pair is spanned by only 3–7 Phoenix blocks, representing about 0.10%–0.22% of each original pass, while Atlanta reference coverage is about 91.7%–94.2%. None of the Phoenix blocks spans the listed 30%–40% or higher pairs. The 90%–100% pair is not spanned in either city.

These observations do not justify selecting a different pair to improve an effect result or forcing a common city-ranking estimand. No endpoint pair was reselected, no original cell/pass was removed, and no restricted-support model was fitted.

- [Historical endpoint figure](historical_endpoint_support.png) · [PDF](historical_endpoint_support.pdf)
- [Candidate-pair range-support map](candidate_pair_block_support.png) · [PDF](candidate_pair_block_support.pdf)
- [Endpoint support table](endpoint_support.csv): 720 pass/pair/width rows.

## Covariate and month support

Exact full-band distributions are reported for imperviousness, low vegetation, bare cover, buildings, elevation and distance to water at both historical endpoints and all three widths. A supplementary joint-context diagnostic measures nearest-neighbour distances in the six standardized controls. Scaling gives equal weight to cities and passes using deterministic full-predictor samples. Queries use up to 2,000 cells per pass/band, and each other-city reference pool contains 5,000 unique sampled physical cells. Recurring footprints are deduplicated within each reference pool.

The distance distributions are directional and depend on the recorded standardization and finite sampling. Their median/P5/P95 values are descriptive distributions, not confidence intervals or a validated positivity test. No acceptance distance was chosen. At ±2.5pp around the lower historical endpoint, pass median distances are about 0.62–0.80 for Phoenix queries against Atlanta references and 0.30–0.41 in the reverse direction. These results call for inspecting the represented covariates rather than treating nominal endpoint support as proof that the cities are exchangeable.

The [month/time support record](month_time_support.json) preserves every original acquisition and the existing morning/afternoon descriptive windows. No July or September Phoenix morning pass appears in this pilot. Predictor support does not repair those missing temporal combinations, and no time contrast was computed.

- [Joint context figure](cross_city_context_support.png) · [PDF](cross_city_context_support.pdf)
- [Exact endpoint covariate profiles](endpoint_covariate_profiles.csv): 576 rows.
- [Cross-city context distances](cross_city_context_distances.csv): 96 rows.
- [Reference-pool marginal profiles](cross_city_reference_profiles.csv): 72 rows; [sampling/scaling details](cross_city_reference_sampling.json).

## Protected quadratic design

The audit constructs raw canopy `f` and raw `f²`, then centres each separately within the original 1km blocks. Both canopy terms are mandatory. Context-only rank checks precede the protected basis check, following the inherited rule; a confounded quadratic term is reported non-estimable rather than silently discarded. All six controls remain in every actual design: no context term was removed in this audit.

Linear designs have rank 7 and quadratic designs rank 8 for every pass. Column-normalized quadratic design condition numbers range from about 5.58–5.82 in Phoenix and 11.28–11.62 in Atlanta. These are numerical diagnostics, not acceptance thresholds. Partial curvature information is more geographically concentrated in Phoenix: effective information blocks for `f²` after the other terms range from about 336–952, compared with 2,957–5,747 in Atlanta. The linear and quadratic information totals have different units; effective-block summaries compare concentration, not effect precision.

For each pass, 1,000 whole-1km-group and 1,000 whole-8km-group multiplicity draws were frozen and shared between linear/quadratic designs. Every draw preserves full rank in both designs. No outcome values were used in that assessment. The earlier 48 failures in Step 3 used the all-eleven common footprint and a different draw plan; this original-population audit does not invalidate that result or guarantee every possible resample is estimable. Original Phoenix bare-cover variation occupies 12–17 blocks and 7–10 coarse groups, versus 10 blocks/five coarse groups in the common footprint.

- [Design resampling figure](quadratic_design_rank_support.png) · [PDF](quadratic_design_rank_support.pdf)
- [Design diagnostics](design_diagnostics.csv): 32 rows.
- [Design resampling counts](design_resampling.csv): 32 configurations; [control information](control_information_support.json).

## What is ready and what remains

The historical pair and nearby candidates have an auditable support description, and all16 original samples can identify the specified protected quadratic design under the tested numerical rules. No common city-ranking contrast, alternate primary population, new support cutoff or outcome-model go decision has been selected. Conditional covariate overlap remains a substantive interpretation question; full rank alone does not settle it.

The empirical quadratic fitting component of Step 5 has not run. Accordingly there is no new linear-versus-quadratic effect table, fitted curve, outcome SE or finite-contrast interval in this package. The pending scope clarification concerns whether to proceed with those fits internally while keeping all new effects sealed. Reza's tolerance, effect-based Stage 1 review, new time inference and study expansion remain unresolved under the current instructions.

Twelve network-free known-answer/boundary tests passed. They cover the exact +0.44 K quadratic contrast for `T=305−5f+2f²` over 10%–20%, the error from squaring centred canopy, protected-term confounding, inherited context-rank selection, clipped/overlapping bands, unsupported exact endpoints, physical-group draws, weighted scaling and blocked outcome reads. The 24 frozen source hashes, 7,511,083 original cell-pass observations, unique native identities, six exact CSV roundtrips, historical support reconciliation and public figure checks passed. No outcome columns or coefficient/effect files were read; only approved predictor columns were decoded from the sixteen cached native frames. All existing inputs and results remain preserved.

[Data dictionary](data_dictionary.md) · [machine-readable dictionary](data_dictionary.json) · [execution freeze](../../docs/v2/v6_2/execution/canopy_support_step5_20261004/execution_freeze.json) · [verification](../../docs/v2/v6_2/execution/canopy_support_step5_20261004/verification.json)
