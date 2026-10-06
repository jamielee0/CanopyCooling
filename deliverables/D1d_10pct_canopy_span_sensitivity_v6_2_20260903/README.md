# D1d 0.10 canopy-span sensitivity

This is a **nonbinding post-support sensitivity**. It preserves the controlling
0.20 D015/D016 rule and opens no ECOSTRESS LST or new coefficient.

## What the threshold means

The rule is not "10% of observations." A block-pass passes when its within-block
Science TCC p90 minus p10 is at least **0.10 canopy fraction**, or ten percentage
points. The purpose is to avoid estimating a canopy-temperature slope from a block
whose canopy values are nearly uniform.

## Result

- Candidate nonthermal block-passes: **13,509**
- Eligible at 0.10: **1,368 (10.1%)**
- Unique eligible Phoenix blocks: **331**
- Median eligible passes per eligible block: **4 of 5**
- Eligible-pass distribution across blocks: 19 blocks on 1 pass, 3 blocks on 2 passes, 51 blocks on 3 passes, 100 blocks on 4 passes, 158 blocks on 5 passes

| Pass | Eligible | Candidate | Share |
|---|---:|---:|---:|
| phoenix:27963 | 220 | 2,828 | 7.8% |
| phoenix:28024 | 282 | 2,684 | 10.5% |
| phoenix:28706 | 311 | 2,876 | 10.8% |
| phoenix:28828 | 311 | 2,876 | 10.8% |
| phoenix:28909 | 244 | 2,245 | 10.9% |

At 0.10, the nonthermal screen is no longer empty. If a supervisor prospectively
approved this threshold, it would be reasonable to consider the same five-pass
sealed thermal Stage-1 pilot. That pilot would still need to demonstrate actual
tree/background cell support, estimable slopes, acceptable uncertainty and
stability. This sensitivity does **not** authorize Gate A.

## Contents

- `tables/d1d_10pct_block_passes.csv`: all 13,509 rows under both thresholds.
- `tables/d1d_10pct_blocks.csv`: eligible-pass counts for the 331 qualifying blocks.
- `analysis_manifest.json`: exact result, checks, and source hash.
- `checksums.txt`: SHA-256 for every other file in this package.
