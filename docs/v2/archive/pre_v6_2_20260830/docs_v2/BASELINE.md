# V2 baseline

**Captured:** 2026-08-01, before the v2 feasibility implementation was added  
**Repository:** `/Users/jmlee/Documents/TreeProject/project`  
**Branch:** `temporal-ndmi-supply`

This is a preservation baseline, not a claim that the worktree was clean. It records the
working Phoenix pilot that v2 must not silently overwrite.

## Verified starting state

| Item | Evidence | Interpretation |
|---|---|---|
| Legacy logic tests | `/Users/jmlee/miniforge3/envs/urbanv2/bin/python src/test_run_all.py` reported **133 passed** | The existing runner contract was healthy at capture time. |
| Legacy deliverable audit | `/Users/jmlee/miniforge3/envs/urbanv2/bin/python src/run_all.py --check-deliverables` reported every registered output present | The Phoenix pilot's saved outputs existed at capture time. This is an existence audit, not a scientific revalidation. |
| Working Python | `/Users/jmlee/miniforge3/envs/urbanv2/bin/python`, Python **3.11.15** | Use this interpreter for immediate local verification unless the environment is rebuilt. |
| Declared environment | `environment.yml` names `canopy` | The named `canopy` environment was not installed locally at capture time. Reconcile the declaration and the working `urbanv2` environment before claiming one-command reproducibility. |
| Worktree | 73 modified, deleted, or untracked paths were present before v2 work began | These are user-owned changes. V2 work must preserve them and should use new paths wherever possible. |

## What the legacy pipeline represents

The current code is a Phoenix-only pilot, centred on summer 2023, a custom 70 m reference
grid, ECOSTRESS thermal data, seasonal Sentinel-2 composites, ERA5-Land demand and soil
moisture, and block-group pairing. Its passing tests establish a useful regression baseline;
they do not make the legacy design compliant with the new five-city guide.

The guide explicitly changes the scientific design in material ways:

- five reproducibly defined urban domains and summers 2018–2025;
- the native ECOSTRESS tiled geometry rather than a custom grid;
- a catalogue and weather feasibility gate before thermal analysis;
- local solar time, scene-level quality, obstruction, view-angle, and retrieval-mode records;
- antecedent precipitation minus reference evapotranspiration rather than a compound stress
  index or an assertion of soil water;
- pass-level effective sample size, clustered simulation, and preregistered holdouts;
- 2026 and one city kept unopened for confirmation.

## Preservation boundary

1. Do not rewrite or delete the Phoenix pipeline to implement v2.
2. Put new feasibility code, tests, configuration, documentation, and outputs under clearly
   named v2 paths.
3. Do not treat a passing legacy test as evidence that a v2 scientific gate has passed.
4. Never read, print, commit, or copy `.env`, Earthdata tokens, Earth Engine credentials,
   `.netrc`, or other secrets.
5. Do not commit or discard any pre-existing worktree change unless the user explicitly asks.
6. Re-run the 133-test legacy check after integration; any regression is a release blocker.

## Baseline limitations to resolve

- The declared `canopy` environment and the available `urbanv2` environment disagree.
- The legacy documentation says scale-out to Los Angeles, Atlanta, and Minneapolis–Saint Paul,
  whereas the guide requires five cities. V2 provisionally adds Miami; exact domains still
  require verification and freezing.
- Existing downloads and results cannot substitute for the guide's Steps 1–3 because their
  date range, geometry, scene metadata, water construct, and effective sampling unit differ.
- A complete deliverable audit only shows that files exist. V2 gates require content checks,
  provenance, and documented failures as well.

## Release criterion for preserving the baseline

The v2 feasibility work is safe to hand off when the legacy runner test still reports all 133
checks passing, the legacy deliverable audit remains intact, and `git diff` shows no unintended
changes outside the new v2 surface or explicitly approved dependency updates.
