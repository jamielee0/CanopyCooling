# D0075 — Gate 3 exclusive-writer correction

## Status

`FROZEN / NONTHERMAL CHECKPOINT-SAFETY CORRECTION`

**Frozen:** `2026-08-14T00:11:29+09:00`

During a D0069 geometry resume, the saved checkpoint count was observed to
increase and then regress while the current runner was still active. This is
consistent with two processes holding stale in-memory checkpoint dictionaries
and replacing the same atomic JSON file in different orders. The current run
was stopped before further continuation. Content-addressed pass evidence and
reconstruction files were preserved; no project data was deleted or relabelled.

The augmentation entrypoint now acquires one non-blocking, process-wide
exclusive file lock before any prepare, geometry, cloud, weather, or finalize
stage can write. A second writer fails immediately instead of waiting or
replacing a newer checkpoint. A network-free known-answer test holds the lock
and verifies that a concurrent acquisition is rejected.

The surviving 320-row checkpoint is not accepted merely because it is the
largest observed count. The existing per-item validators remain authoritative:
on resume, every credited item must reproduce its source binding, evidence
hash, reconstruction hash and size, target-grid identity, and expected pass
identity. Invalid, orphaned, or stale artifacts receive no storage credit and
are recomputed under the unchanged reserve rule.

This correction changes no city, season, predictor, angle threshold, support
rule, or result. No LST/thermal value, holdout datum, or 2026 science data was
opened. The metadata exposures in D0060, D0061, D0073, and D0074 remain
disclosed and excluded.
