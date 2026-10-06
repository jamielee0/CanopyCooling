# D0066 — Gate 3 revision authorization

## Status

`FROZEN / USER-DIRECTED G3 REVISION`

At `2026-08-13T19:30:54+09:00`, the user reviewed the initial Gate-3 packet and
returned the verdict `REVISE — do not approve yet`. This decision binds that
review to the following initial-packet evidence:

- Gate-3 checks SHA-256: `1359ae27f670ed07134e433777adb1d32c859b2201a9172a3837532e99a2fa6d`
- Gate-3 review SHA-256: `f696833e396c88af68b35ac1f189da9a8c0fe7046e90606201d1ff7e7daa87e9`
- Gate-3 source bindings SHA-256: `76daa3f4ba2f9f535feb83d67de726d4ff4736f7bca5028755683f10b1102c16`
- Gate-3 generator SHA-256: `6fadd3b29008c208dabb7c82cb505c8463b5c4f1b1033803a296d4a35657e21e`
- Gate-3 runner SHA-256: `d50fec44736651f7db7acd386918ea88ed6551c0150ec0f99b13d1cc34b13c7a`

## Authorized work

The user's binding instruction is:

> REVISE G3: complete the bounded nonthermal geometry/cloud/weather augmentation;
> add QA-rank-0 and tree-masked phenology sensitivities; establish a fail-closed
> rule for permanently unavailable passes; implement and test the
> smallest-eligible-threshold selector and balance diagnostics; then return to
> Gate 3 review without opening LST, thermal outcomes, holdout data, or 2026 data.

This authorizes only the historical 2018–2025, outcome-blind work named above.
The amendment rules in D0067 must be frozen before any newly augmented result is
opened. The revised packet must preserve the initial packet and be separately
identified and hashed.

## Locks

- Temperature/LST and every thermal outcome remain unopened.
- Holdout selection and holdout data remain unopened.
- Every 2026 query and record remains prohibited.
- G3A and Gate 4+ remain locked.
- The revised Gate 3 must stop for a new human approval, even if it selects a
  design automatically under the frozen rules.
