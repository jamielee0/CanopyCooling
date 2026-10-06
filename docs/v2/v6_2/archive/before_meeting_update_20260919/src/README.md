# v6.2 source code

Top-level files named `run_v6_2_*`, `build_v6_2_*`, `finalize_v6_2_*`, and
`test_v6_2_*` are the current analysis runners, artifact builders, and network-free
tests. `urban_cooling_v2/` contains only the helper modules required by those v6.2
workflows.

Most scripts infer the repository root from their own location. Because `data/` is
linked to the original project data tree, their expected data paths remain valid.

`run_v6_2_d1a_geometry_recovery.py` deliberately reuses an older checksum-bound
D0069 range-read engine. Its completed result is included, but a full rerun still
depends on the preserved implementation in the original repository. This exception
is documented rather than copying the entire pre-v6.2 engine into the clean folder.
