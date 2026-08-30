# Conformance memorandum — v6.2 control boundary

**Date:** 30 August 2026  
**Scope:** D0 only; no figures, results, new thermal processing, or new v6.2 coefficient

## Ruling

The repository now has a v6.2 control boundary at branch `v6.2`. Annotated tag
`v2-inherited-pre-v6.2` resolves to commit
`e32ff06aad83f1c8fe87473bf5c95e9e12f155e2`, the last inherited commit. Because the
working tree already contained extensive uncommitted inherited work, the tag freezes
committed history only; `checksums.txt` separately freezes every inherited file that was
present in the working directory. Nothing inherited was discarded, reset, or silently
folded into the tag.

| Disposition | Earlier components | v6.2 treatment |
|---|---|---|
| **Retained** | Repository/environment; raw manifests and hashes; ECOSTRESS catalogue and deduplication; attrition ledger; exact-time HRRR joins; geometry and missing-granule investigations; provenance; block bootstrap and known-answer tests | Preserved as infrastructure and historical evidence. They must be reverified under the frozen v6.2 releases, years, native-grid geometry, and unit conventions. |
| **Revised** | Collection query; city frame; season and geometry screening; canopy product use; optical timing; support and power; demand handling; dependence structure | Collection 3 is primary for LST; Phoenix and Los Angeles run in parallel; native MGRS and 15°/25° sets replace the Phoenix custom grid; raw annual TCC 2019–2025 and one-sided HLS timing replace the inherited proxies; demand remains pending the free check. |
| **Rebuilt** | Outcome/exposure construction and statistical estimator | Build `G`, `W_tree`, and fixed-class `W_bg` separately from raw HLS; fit one block-specific canopy slope per pass; calculate `CE=-0.10*s`; use exact block/pass fixed-effects identifying components, replicate reliability, common-cell/reweighted sensitivity, and full graph simulation. |
| **Archived** | Earlier v2 requirements, baseline, decision log, implementation plans/configs, legacy design decisions, remediation plan, and advisory log | Checksum-preserving copies live in `docs/v2/archive/pre_v6_2_20260830/` and are explicitly superseded. Original locations remain untouched for reproducibility but are not controlling. |
| **Retired** | Compound Stress Index; demand-by-supply surfaces; breakpoints; paired tree/reference purity-threshold outcome; pass-equivalents as sample size; 95% whole-city coverage; citywide MODIS phenology exclusion; early-versus-late contrast; canopy carry-forward; formal 2026 holdout; global-blinding claim | They cannot enter the v6.2 outcome model, progression rules, or scientific output root. Historical artifacts remain readable only as disclosed design history. |
| **Quarantined** | Synthetic and illustrative downstream outputs | Existing paths are classified in `output_isolation_manifest.csv`; all future synthetic material must be written below `tests/fixtures/synthetic_demo/` with `SYNTHETIC_DATA` in names and visible labels. It cannot write below `outputs/v6_2/scientific/`. |

## Frozen conformance points

- The controlling version is v6.2. The professor's email contains one “v6.1” phrase,
  but the attached Working Guide, proposal, schedule, and explicit branch request all say
  v6.2. This discrepancy is disclosed rather than silently ignored.
- The exact current Science TCC release is Product Version 2025-6. The official methods
  report is stored and checksum-frozen. The inherited 2025 raster and 2018–2025
  provenance record use the post-processed `NLCD_Percent_Tree_Canopy_Cover` band, not
  the required raw `Science_Percent_Tree_Canopy_Cover` band; they are explicitly
  nonconforming for v6.2. The full annual 2019–2025 local Science-band inventory is
  truthfully `PENDING_GATE_A` because those assets are not yet on disk.
- Provisional, outcome-blind HLS population rules are `tree >= 0.40`,
  `background <= 0.10`, and a 0.30 excluded mixed gap. The tree value retains the prior
  physical-signal floor but not the retired paired design; the background rule is a new
  fixed pervious/low-vegetation definition. Any amendment requires a prospective,
  supervisor-approved decision-log entry before a corresponding coefficient is viewed.
- Every free-check constant, season, geometry set, unit conversion, formula, predicted
  sign, and gate threshold is filled in. Items that only non-thermal Gate A can determine
  are explicitly `PENDING_GATE_A`, never blank. The optional demand branch is explicitly
  pending the scheduled free-check ruling.
- The four output roots are physically separate and documented in `output_roots.txt`.
  The required output-path guard refuses cross-class writes and path traversal. A
  boundary checker also rejects synthetic/illustrative/retired names inside the
  scientific root and rejects unmarked files in the synthetic or retired roots.

## Deviations and unresolved items

No scientific rule from the Working Guide was intentionally relaxed. Two implementation
facts require supervisor awareness: (1) the baseline tag cannot include the pre-existing
dirty worktree, so the file-level checksum inventory is the reproducible supplement; and
(2) the annual Science-band and precipitation inventories are not complete locally and
are explicit Gate A acquisition items. The methods report itself is present and hashed;
the missing items are the city/year Science-band rasters and local precipitation assets.
The D0 files are intentionally uncommitted because repository policy requires explicit
user permission before a commit. A fresh clone will reproduce the structure only after
these reviewed files are committed. These facts do not authorise Gate A or thermal
processing.

**Current decision:** D0 control boundary prepared; Gate A remains unauthorised until the
full D0–D1d package is reviewed and accepted.
