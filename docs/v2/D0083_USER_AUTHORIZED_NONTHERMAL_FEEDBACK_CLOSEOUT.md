# D0083 — User-authorized nonthermal feedback closeout after failed Gate 3

## Status

`FROZEN / USER-AUTHORIZED / NONTHERMAL FEEDBACK CLOSEOUT`

**Frozen:** `2026-08-16T22:13:26+09:00`

After receiving the verified D0082 Gate-3 `REVISE_REQUIRED` result, the user
instructed the project to “keep going regardless, to address all the points in
the document.” This authorizes completion of the remaining feedback accounting
and outcome-blind diagnostics. It does not rewrite the failed Gate-3 result,
select a city/season/angle design, or convert an infeasible analysis into a
passing one.

## Authorized closeout scope

The closeout may use only already opened historical nonthermal evidence through
2025 and deterministic synthetic calculations. It will:

1. audit the focused high-demand wet–dry contrast at every preregistered angle
   threshold, including within-city demand and seasonal overlap;
2. audit empirical AM–PM availability and the feasibility of matching on solar
   elevation, weather, season, view azimuth, and relative sun–sensor azimuth;
3. consolidate independent reproduction and known-answer checks for counts,
   identities, weather joins, VPD, rolling-window exclusion, solar geometry,
   cloud/fill semantics, and physical units/signs;
4. preregister the requested three simulation profiles and run a fail-closed
   preflight before any Monte Carlo work; and
5. apply the already approved G8 redirect rules once and publish a 37-item
   feedback compliance matrix.

The widest selectable threshold, 25 degrees, may be used as a diagnostic upper
support profile but is not adopted as the primary design. Every table must also
retain the 10, 15, 20, and 25 degree results where the evidence exists.

## Frozen simulation contract

The simulation preflight inherits the outcome-blind D0056 planning values:

- effect sizes: `0.75`, `1.50`, and `2.25 K`, with `1.50 K` primary;
- pass random-effect standard deviation: `0.8 K`;
- matched-set random-effect standard deviation: `0.5 K`;
- row residual standard deviation: `1.5 K`;
- alpha: `0.05`; target power: `0.80`;
- deterministic seed: `20260816` for any new closeout simulation;
- planned Monte Carlo counts if a profile is identifiable: 1,000 power
  replicates per effect, 2,000 null replicates, and 500 interval-coverage
  replicates with 500 whole-pass bootstrap draws; and
- minimum detectable effect: the smallest tested/interpolated absolute effect
  reaching 80% power, otherwise explicitly `not finite/estimable`.

A profile is not identifiable and no Monte Carlo claim may be produced when its
required empirical groups are absent, the design matrix is rank deficient, the
matched-set count is zero, or the nonthermal tree/reference yield needed to
represent pass-level measurement error is unavailable. Historical simulations
may be summarized under their original scopes but do not satisfy a missing
feedback-compliant profile.

## Locks

The feedback document explicitly says not to inspect thermal data and to keep
2026 sealed. Therefore this authorization does not permit:

- any ECOSTRESS LST or other thermal/temperature outcome value;
- holdout identity selection or holdout outcome access;
- Task-2 result-bearing execution;
- any 2026 query, record, or science value; or
- post-result relaxation of the G3, G4, G5, or simulation rules.

If the support audits fail, the closeout must select the corresponding
comparative-case-study or identifiability-paper direction and stop the cooling
outcome study.
