# D0084 — Feedback-closeout approval and result

## Status

`APPROVED / FEEDBACK-CLOSEOUT RESPONSE / SCIENTIFIC REDIRECT`

**Frozen:** `2026-08-16T22:46:07+09:00`

The user requested that every point in the supplied feedback document be
addressed and that the resulting response be approved. Under D0083's
outcome-blind authorization, the project completed the remaining G4–G8
nonthermal audits, prepared a point-by-point response, independently checked
the implementation, and visually verified the seven-page Word deliverable.

This decision approves the completeness and accuracy of the feedback-closeout
response. It does **not** approve a pooled cooling study, a time-of-day study,
a thermal analysis, or the failed Gate-3 sampling design.

## Disposition of all feedback points

All 37 mapped points have an explicit disposition:

- 26 `ADDRESSED`;
- 8 `ADDRESSED_NEGATIVE_RESULT`;
- 1 `ADDRESSED_BY_FAIL_CLOSED_PREFLIGHT`;
- 1 `ADDRESSED_EQUIVALENT_LABEL`; and
- 1 `PARTIAL_BLOCKED_REPORTED`.

The partial item is F10. Clear/fill fractions are complete, but per-pass usable
tree/reference yield cannot be reported because Gate 3 did not select a design.
The missing quantity is disclosed rather than imputed.

## Gate results

1. **G4 — pooled high-demand wet–dry contrast: not approved.** No frozen
   10°, 15°, 20°, or 25° threshold satisfies the pooled support rule. At the
   widest diagnostic threshold, 25°, 52 complete passes remain and only
   Denver–Aurora has the required within-city counts plus positive VPD and
   seasonal overlap. Denver supplies 55.7692% of those passes, above the 40%
   city-share cap.
2. **G5 — time-of-day comparison: not approved.** At 25° there are zero AM
   passes, 18 PM passes, and zero empirical pre-caliper AM–PM pairs.
3. **G6 — independent verification: passed.** All ten source, count, identity,
   weather, VPD, solar-position, rolling-window, cloud/fill, sign/unit, and
   clean-room checks pass.
4. **G7 — requested simulation profiles: not identifiable.** Each of the three
   empirical profiles fails the frozen preflight, so no new Monte Carlo result
   or minimum-detectable-effect claim was manufactured. The historical D0056
   simulation remains historical only.
5. **G8 — redirect:** `COMPARATIVE_CASE_STUDY_PROPOSAL_ONLY`, with
   Denver–Aurora as the sole candidate. This is a proposal direction, not a
   cooling-effect result.

## Verification and approved artifact

- The closeout runner passes all 37 mapped points.
- The focused known-answer test program passes 4/4 tests.
- The full repository regression suite passes 42/42 v2 and 17/17 legacy test
  programs.
- The Word response was rendered through the canonical document renderer and
  every one of its seven pages was visually inspected; no clipping, overlap,
  blank-page, margin, header, footer, or page-number defect remained.

The approved reviewer-facing artifact is
`docs/v2/hitl/FEEDBACK_CLOSEOUT/Urban_Tree_Cooling_Feedback_Response.docx`.

## Frozen evidence hashes

- Supplied feedback document:
  `4d369a5337a20b2969d4c1ccabb528c56fae9eb19061c72513d301658dc79333`
- Approved Word response:
  `ce3fbe6c1694a6eb2484009611775c66caf1df7475ae867e6f62598e2edd6414`
- Compliance matrix:
  `31a8a30890045933d69991c789b8bd638bd826ac588cc55c9fce6d30f669931b`
- Closeout checks:
  `50e77f9efa5e46dd756ba041ffedb4388342749a1525228be0ccf8377f5f61fe`
- G8 decision:
  `2fd20ff00db306f6fd6bc612a5914639c1d624fad517615552df6608fd74d270`
- Source bindings:
  `447e0567fbbda8f3fcbf13bcecb65eeff9329198e90087d1f4ad513928ba4d1b`
- Regression verification:
  `f471e94c4a9bcc9f0c2ebb32949ad3b33cce322edd4a140ee0cf6b29775470d7`

## Locks preserved

No temperature or LST value was opened; no holdout was selected or inspected;
no Task-2 result-bearing run occurred; and no 2026 record or science value was
opened. Those locks remain binding. Any future attempt to revive pooled,
time-of-day, or thermal inference requires a new prospective design and fresh
authorization; D0084 cannot be cited as approval for those analyses.
