# D0082 — Gate-3 second-revision verified result

## Status

`FROZEN / G3 REVISE_REQUIRED / NO DESIGN SELECTED`

**Frozen:** `2026-08-16T21:55:53+09:00`

The user approval recorded in D0078 approved the first-four-items feedback
packet and authorized resumption of the bounded D0069 work. It did not
prospectively approve Gate 3 or override its frozen selector.

The resumed augmentation completed with 762 ledger rows and 734 checksum-bound
geometry reconstructions. The corrected ledger contains 127 complete positive-
map passes, 221 strictly verified zero-map passes, 386 accessible
`AZIMUTH_INCOMPLETE` passes, and 28 `RESOLVED_UNAVAILABLE` rows. Cloud evidence
is complete for all 52 passes qualifying at 25 degrees, and exact HRRR evidence
is complete for those 52 observed passes plus the 12 governed new unavailable
passes.

The packet generator passed all 41 discovered v2 and 17 legacy test programs.
The independent clean-room verifier reproduced source and governance hashes,
all 734 reconstruction/evidence bindings, the geometry-cloud-weather join,
governed pass values, all 117 HRRR shards, the 43-pass unified unavailable
ledger, and the inaccessible-pass bounds. Its verification status is `PASS`.

## Frozen selector result

The scientific result is nevertheless `REVISE_REQUIRED`. None of the permitted
10, 15, 20, or 25 degree thresholds satisfies every D0067/D0069 rule. At the
widest selectable threshold, 25 degrees:

- the observed complete design has 52 passes: Atlanta 11, Denver–Aurora 29,
  Minneapolis–St. Paul 10, and Phoenix 2;
- Denver's 29/52 share is 55.77%, above the frozen 40% cap;
- every primary city-window has zero 10–12 local-time passes;
- only Denver passes the frozen high-demand wet/dry count, VPD-range overlap,
  and day-of-window overlap rules;
- the calculated inaccessible-pass bounds are not invariant; and
- 386 accessible passes remain incomplete because the required source azimuth
  fields are not complete; they were not imputed or silently treated as
  observations.

The narrower thresholds have still less observed support. The packet's
selection remains `UNSELECTED`, and its clean-room-reproduced reason is that no
threshold supplies at least four nonexploratory cities including Denver with
complete eligibility, invariant unavailable-pass bounds, and passing balance
diagnostics.

## Locks and next decision

Gate 3 is not approved. G3A, Gate 4+, Task 2, holdout identity/data,
temperature/LST, thermal outcomes, and 2026 science records remain locked.

A third revision cannot be invented from the opened result. It would require a
new prospective user-authorized scientific amendment or source strategy—for
example, a defensible alternative for the missing source azimuth or a
prospectively justified redesign of the time/balance requirements. Merely
relaxing a threshold because the observed result failed is prohibited.

## Bound evidence

- checks SHA-256: `64626fea5885676b1e2f801252520ca2e3f279148aa137653a9b0ecbd26ce67d`
- selection SHA-256: `e9572ece54bff4b6f4f873b6de3b4e41b401c9702864124ce4fb4c86a645cf2b`
- review SHA-256: `e323a7eddc17811000be8c9b3968940c79036b40d74ba25559c1cedab7b1af2b`
- source-bindings SHA-256: `6420de355c0772fcd3ff4ac3b0f78eed7459e95b7df97ab1c1932e9919e24dea`
- clean-room verification SHA-256: `ac6995f09a9ed5ce0e5a099843bf72c00517f3d3db8e36916a77a33e17821826`
- full regression suite SHA-256: `7f1d6d674fff6b8beb6478f1dc8444f2c105692dd9259d510fed4ea40ee61081`
