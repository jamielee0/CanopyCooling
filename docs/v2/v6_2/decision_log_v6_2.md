# v6.2 decision log

Use one entry for every proposed change to a frozen rule. A change is not effective
until its entry is complete and the named supervisor has approved it. No rule may be
changed after the corresponding v6.2 coefficient has been viewed.

## Entry 1 — control-boundary freeze

- **Decision ID:** V6.2-D001
- **Recorded:** 2026-08-30T17:58:40+09:00
- **Status:** FROZEN; SUPERVISOR REVIEW PENDING
- **Change:** Establish v6.2 as the controlling design, preserve the last inherited
  commit under annotated tag `v2-inherited-pre-v6.2`, and freeze the product,
  population, timing, geometry, model, sign, power, and gate rules in
  `protocol_v6_2.yml` before any new v6.2 coefficient is viewed.
- **Reason:** The compound-threshold, paired-pixel, and early-versus-late designs failed
  outcome-free feasibility checks. The replacement estimand is a block-pass canopy–LST
  slope modified by separately constructed antecedent `G`, `W_tree`, and `W_bg`.
- **v6.2 coefficient viewed before change:** no
- **Prior retired thermal work relevant:** yes; disclosed in `prior_thermal_access.md`
- **Files changed:** `docs/v2/v6_2/**`, `docs/v2/archive/pre_v6_2_20260830/**`,
  `outputs/v6_2/**`, `tests/fixtures/synthetic_demo/**`, and v6.2 boundary utilities
- **Gate affected:** free checks
- **Approved by:** PENDING_SUPERVISOR_REVIEW

### Frozen implementation rulings made at D001

- Science TCC is the raw USFS/USGS Product Version 2025-6, stored as fraction 0–1
  for analysis; 2019–2025 stable-cell median is primary.
- Provisional population thresholds are `tree >= 0.40` and `background <= 0.10`;
  the open interval `(0.10, 0.40)` is excluded as mixed.
- The primary background is low-canopy, low-impervious, pervious low vegetation;
  impervious/bare is a placebo, not the primary comparator.
- The primary geometry is native ECOSTRESS MGRS with 1 km blocks and pass-level p95
  absolute view zenith at or below 15 degrees. The predeclared expansion is 25
  degrees only where view azimuth is available.
- Phoenix's provisional primary season is 15 May–10 July; Los Angeles's is 1
  June–30 September. The opposite window is the predeclared sensitivity in each city.
- The Stage 1 implementation must contain `C(block):canopy_c` and emit one slope per
  block-pass. Cooling efficiency is `CE = -0.10 * slope` when canopy is a 0–1 fraction.
- Stage 2 jointly includes `G`, `W_tree`, and `W_bg` with block and pass fixed effects.
  The demand branch is explicitly pending the free-check ruling.
- Expected signs are scientific predictions, never inclusion or progression gates.

## New-entry template

- **Decision ID:** V6.2-D___
- **Recorded:** YYYY-MM-DDThh:mm:ss±hh:mm
- **Status:** PROPOSED | FROZEN | REJECTED | SUPERSEDED
- **Change:**
- **Reason:**
- **v6.2 coefficient viewed before change:** yes | no
- **Prior retired thermal work relevant:** yes | no
- **Files changed:**
- **Gate affected:** none | free checks | A | B | full analysis
- **Approved by:**

