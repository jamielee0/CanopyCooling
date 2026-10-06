# D0071 — User-delegated iterative gate review and continuation

## Status

`FROZEN / USER-AUTHORIZED REVIEW GOVERNANCE`

At `2026-08-13T20:09:12+09:00`, while the D0069 Gate-3 revision was still in
progress and before any new augmentation result was opened, the user directed
the AI to continue through all remaining gates using subagents: an independent
subagent reviews each gate, the primary agent implements the findings, and the
gate is reviewed again until no blocking issue remains; only then may the next
gate begin.

## Required review loop

For every remaining gate:

1. freeze any pre-result choice required by that gate before opening the data
   governed by the choice;
2. generate a checksum-bound packet and run the complete applicable test suite;
3. assign at least one independent subagent that did not implement the packet
   to review scientific compliance, numerical identities, provenance, locks,
   and tests;
4. classify every reviewer finding as blocking, nonblocking, or rejected with
   an evidence-based reason;
5. implement all valid blocking findings and obtain another independent review
   of the revised packet; and
6. proceed only after the recorded reviewer verdict has no unresolved blocking
   finding.

The primary agent remains responsible for implementation and final verification;
review agents do not silently edit the artifact they are judging. Review
records and the exact reviewed hashes must be retained with the gate packet.

## Relationship to prior human pauses

This instruction delegates the previously required per-gate review pause to the
iterative subagent-review process. It authorizes continuation after an
independent `APPROVE` verdict without waiting for a new user message. It does
not retroactively approve Gate 3, alter any scientific threshold, or permit a
gate to approve itself.

## Locks and ordering

All data-access and sequencing locks remain binding until their designated
gate has prospectively frozen and passed its own prerequisites. In particular:

- Gate 3 must pass before G3A or Gate 4 begins;
- holdout identity/data must remain sealed until the designated nonthermal
  holdout-selection checkpoint;
- temperature/LST and other thermal outcomes must remain sealed until their
  authorized outcome gate;
- 2026 records remain sealed until the confirmatory/holdout stage explicitly
  authorizes them; and
- a failed gate remains a valid terminal or revision result and cannot be
  rescued by post-result threshold changes.

If a later gate genuinely requires an external scientific choice that cannot
be resolved prospectively from the frozen specification and non-outcome
evidence, the agents must record the issue and return to the user rather than
inventing authority.
