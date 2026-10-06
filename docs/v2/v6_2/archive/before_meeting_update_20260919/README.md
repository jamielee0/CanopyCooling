# Urban Tree Cooling — v6.2 active workspace

This folder contains only the current v6.2 redesign, its review evidence, and the
code/tests used for the v6.2 feasibility work. The earlier Phoenix threshold
project and the intermediate multi-city v2 workflow remain in the original
repository and are not controlling here.

## Start here

1. `docs/v2/v6_2/protocol_v6_2.yml` — controlling scientific rules and current
   status.
2. `docs/v2/v6_2/decision_log_v6_2.md` — why each rule or sensitivity exists.
3. `deliverables/README.md` — plain directory map for all current analyses.
4. `deliverables/Professor_Submission_Six_Items_v6_2_20260903/README_FIRST.md`
   — clean snapshot organized around the professor's six requested items.

## Current research design

The v6.2 project estimates a canopy–land-surface-temperature slope separately
within each block and satellite pass, converts that slope to cooling efficiency,
and then studies whether cooling efficiency varies with antecedent greenness and
SWIR-sensitive condition over tree and fixed background populations.

The optional VPD interaction is inactive pending supervisor review. Gate A is not
currently authorized. The controlling 0.20 canopy-span screen produced zero
eligible block-passes; a later, explicitly nonbinding 0.10 sensitivity produced
1,368 block-passes across 331 Phoenix blocks and would justify considering the
sealed five-pass pilot only after prospective supervisor approval.

## Directory map

```text
TreeProject2/
├── README.md                 This guide
├── references/               Professor email and three v6.2 source documents
├── docs/v2/v6_2/             Protocol, decisions, conformance, foundation audit
├── src/                      v6.2 runners, builders, tests, and required helpers
├── configs/                  City configuration used by the current work
├── deliverables/             Current D1 packages and professor submission
├── outputs/v6_2/             Controlled and sealed output locations
└── data -> TreeProject/...   Link to the original 41 GB data tree; no duplicate
```

## Data arrangement

`data` is an absolute symbolic link to:

`/Users/jmlee/Documents/TreeProject/project/data`

The new workspace therefore reads the existing raw, interim, and processed data
without copying it. Do not rename or delete the original data directory while this
link is in use.

## What was intentionally not copied

- The legacy Phoenix `section2`–`section16` pipeline and old root configuration.
- Earlier v2 HITL packages and D00xx decision history, except one pass-detail input
  still referenced by current v6.2 code.
- Old review uploads, illustrative/synthetic packages, notebooks, and figures.
- The superseded centered-product D1c package and the stale initial-package copy.
- Raw/interim/processed data, which remain linked from the original project.

The original repository remains the provenance archive at
`/Users/jmlee/Documents/TreeProject/project`.
