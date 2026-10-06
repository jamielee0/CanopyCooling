# Repository operating rules

These rules apply to the entire repository.

## Scope and preservation

- Treat the existing Phoenix pipeline as the legacy `v1` baseline. Do not rewrite it while building the five-city study unless an integration change is explicitly required.
- Put the new feasibility and multi-city work in `src/urban_cooling_v2/`, `docs/v2/`, `configs/v2_cities.toml`, and the git-ignored `data/*/v2` and `figures/v2` output trees.
- The worktree may contain user changes. Inspect before editing, do not discard or overwrite unrelated work, and never use destructive Git commands.
- Do not commit or push unless the user explicitly asks.

## Scientific guardrails

- The canonical specification is `docs/v2/REQUIREMENTS.md`. Each guide deliverable has one canonical ID even where the source document duplicated a row.
- Keep observed, estimated, simulated, and illustrative values visibly distinct in filenames, tables, figures, and prose. Synthetic output must never be presented as empirical evidence.
- Preserve the physical water balance as `pr - eto` in millimetres. When a high-valued dryness axis is needed, derive it explicitly by reversing the within-city wetness rank; do not silently change the sign.
- Antecedent windows end on the day before the target observation. Tests must prevent same-day leakage.
- Resample temporal clusters (whole summers or whole satellite passes), never individual dependent rows, for primary uncertainty estimates.
- Predeclare thresholds, strata, effect sizes, seeds, and minimum-count rules before inspecting thermal outcomes. Record changes in `docs/v2/DECISION_LOG.md`.
- The holdout city remains `UNSELECTED` through Tasks 0-1. It may be selected only after the data-quality audit and before any thermal outcome is inspected. Do not add holdout thermal results to development outputs.
- A failed gate is a valid result. Record it and stop the dependent analysis instead of relaxing rules after looking at outcomes.

## Data access and secrets

- Never print, copy, or commit credentials. Read them only through standard environment variables or the existing git-ignored `.env`/credential stores.
- Catalogue searches may retrieve metadata only. During Steps 1-3, never open or download an ECOSTRESS LST/thermal layer. Quality and geometry layers may be range-read or cached only under a rule frozen in `docs/v2/DECISION_LOG.md`; D0033 permits exhaustive `cloud`-layer measurement, and user-approved D0035 permits the cloud-independent `ECO_L1B_GEO.002` latitude, longitude, and `view_zenith` geometry audit over all 942 metadata candidates followed by exhaustive cloud measurement of the newly sealed geometry candidates.
- Cache fetched inputs under git-ignored `data/raw/v2/` and write provenance (source, query, retrieval time, collection version, and checksum) beside derived outputs.
- Prefer official primary sources and freeze exact dataset IDs and versions in the decision log.

## Verification

- New logic must have network-free synthetic tests. Run the legacy test suite before and after integration as well as every `src/test_v2_*.py` test.
- Use deterministic random seeds in simulations and bootstraps. Full runs may increase replication counts but must not change the seed or model definition.
- A Task 1 deliverable is complete only if its files exist, internal count identities pass, and any failed scientific checks are documented in the corresponding memo.
