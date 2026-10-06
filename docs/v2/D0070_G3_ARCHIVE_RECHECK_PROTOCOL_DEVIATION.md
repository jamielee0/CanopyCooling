# D0070 — Gate 3 archive-recheck protocol deviation

## Status

`RECORDED DEVIATION / NO RETRY AUTHORIZED`

The R0020 archive recheck departed from the finite sequence frozen in D0067.
D0067 allowed an endpoint access attempt only after a date-bounded CMR query
returned an exact asset. Instead, the runner also attempted the predetermined
HDF5 and DMR++ endpoints after CMR returned HTTP 200 with zero exact hits for
each of the 41 scene identities affecting 31 passes.

The extra probes did not broaden the city, date, orbit, scene, collection, or
endpoint identity; every extra request returned HTTP 404. They therefore do not
change the substantive classification `RESOLVED_UNAVAILABLE`, but R0020 cannot
claim clean compliance with D0067's attempt sequence.

Do not repeat these requests. The immutable raw responses and their hashes
remain part of the audit trail. All 31 passes retain their finite
`RESOLVED_UNAVAILABLE` classification and must enter the calculated lower/upper
bounds required by D0069.

## Evidence binding

The one-time target requests are represented by the per-scene request/status
ledger, including each canonicalized CMR-response SHA-256 and the two endpoint
status/prefix fields. The response bodies themselves were not retained as
separate files; this limitation must remain explicit. The immutable evidence
available for review is:

- `docs/v2/hitl/G3_SAMPLING_DESIGN_REVISION/archive_scene_bounded_recheck.csv`
  — SHA-256 `54fba9c8e9d6f2c53f138f352e74615a9fa7f2a4ce4f144ab244edb34acae044`;
- `docs/v2/hitl/G3_SAMPLING_DESIGN_REVISION/archive_pass_bounded_recheck_and_bounds.csv`
  — SHA-256 `f39e3673f901941bf89d27a5ff85fab7120db751f2cdcc948754c4e22ffee6db`;
- `docs/v2/hitl/G3_SAMPLING_DESIGN_REVISION/archive_bounded_recheck_summary.json`
  — SHA-256 `aeb0a16048b92367fcef13619eceb19b7e811e3d9d12c77fb7bc735dbba36360`;
- `src/run_v2_hitl_gate3_archive_recheck.py`
  — reviewed-run SHA-256 `38216eadd8d62ee67d786ad750a485117a46d469cd6d883c0f66438a5a540135`.

The summary records `target_queries_repeated: false` for the reuse path, and
the runner returns from the existing sealed 41-scene ledger instead of issuing
target requests again. Every later Gate-3 packet must bind these exact three
evidence artifacts and must not execute the archive runner.
