# D1c 20% matched-pair-share sensitivity

This is a **nonbinding post-support sensitivity** requested after the frozen 70%
result was known. It does not replace D009/D019 or authorize Gate A.

## Result

The ruling is still **DEMOTE_TO_EXPLORATORY_CONFIRMATORY_SUPPORT_RULE_FAILED**. Although the pooled city shares are
45.5% in Phoenix and 31.8% in Los Angeles, the frozen decision structure is not a
pooled-city test: one season window must pass every nonzero year x sensor stratum.

| City | Season window | Nonzero strata | Share failures | Reuse failures | Panel |
|---|---|---:|---:|---:|---|
| Los Angeles | provisional_primary | 14 | 7 | 2 | **FAIL** |
| Los Angeles | sensitivity | 8 | 4 | 1 | **FAIL** |
| Phoenix | provisional_primary | 6 | 3 | 0 | **FAIL** |
| Phoenix | sensitivity | 14 | 6 | 0 | **FAIL** |

Every panel still contains at least one zero-share stratum, which fails even a
20% minimum. Los Angeles also retains three failures of the separate 25%
acquisition-reuse rule. Therefore neither city has a qualifying season window.

## Interpretation boundary

The 20% cutoff is not stated in the professor's documents and was introduced only
as a user-requested sensitivity. This package reads the existing 56-row Fmask
feasibility table only; it opens no HLS reflectance, optical index, ECOSTRESS LST,
or new coefficient. It is D1c lead-lag evidence, not the D1b block-pass
connectivity report.

## Contents

- `tables/d1c_20pct_strata.csv`: all 56 required strata with 20% share and
  unchanged 25% acquisition-reuse evaluations.
- `analysis_manifest.json`: exact input hash, panel summaries, checks, and ruling.
- `checksums.txt`: SHA-256 for every other file in this package.
