#!/usr/bin/env python3
"""Pure-logic tests for src/run_all.py (no pipeline execution, no IO).

Exercises only the import-safe parts of the driver: that the step registry is
well-formed, that the --from/--to/--only selection logic resolves correctly,
that the manual/network flags are set on exactly the steps the protocol calls
out, and that build_command wires --skip-download / -v through correctly. It
NEVER runs a section or touches data on disk.

pytest is not installed in the env, so this is a plain `main()` runner (same
convention as the section test modules). Run:
    conda run -n canopy python src/test_run_all.py
"""

from __future__ import annotations

import importlib
import os
import sys
import traceback
from pathlib import Path

# Same import convention as the section test modules: repo root for `config`,
# the src/ dir for the section/driver modules (top-level, not a `src.` package).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
ra = importlib.import_module("run_all")  # noqa: E402


# --------------------------------------------------------------------------- #
# Tiny assert harness.
# --------------------------------------------------------------------------- #
_PASSED = 0
_FAILED = 0


def check(cond: bool, msg: str) -> None:
    global _PASSED, _FAILED
    if cond:
        _PASSED += 1
    else:
        _FAILED += 1
        print(f"  FAIL: {msg}")


# --------------------------------------------------------------------------- #
# Registry well-formedness.
# --------------------------------------------------------------------------- #
def test_registry_wellformed() -> None:
    # The driver's own validator must pass (contiguous ids, one runner each, etc.).
    ra.validate_registry()  # raises on malformation
    ids = [s.id for s in ra.STEPS]
    check(ids == list(range(15)), f"expected ids 0..14, got {ids}")
    check(len(ra.STEPS) == 15, "expected exactly 15 steps")

    names = [s.name for s in ra.STEPS]
    check(len(set(names)) == len(names), "step names must be unique")
    check(len(set(ids)) == len(ids), "step ids must be unique")

    for s in ra.STEPS:
        has_module = s.module is not None
        has_nb = s.notebook is not None
        check(has_module ^ has_nb, f"step {s.id} needs exactly one runner")
        # Module steps must point at a real source file; the notebook step too.
        target = s.module or s.notebook
        check(target is not None and (config.BASE_DIR / target).exists(),
              f"step {s.id} target {target!r} should exist on disk")


def test_only_step14_is_notebook() -> None:
    by_id = {s.id: s for s in ra.STEPS}
    check(by_id[14].notebook is not None, "step 14 should be a notebook")
    check(by_id[14].module is None, "step 14 should have no module")
    for i in range(14):
        check(by_id[i].module is not None, f"step {i} should be a module")
        check(by_id[i].notebook is None, f"step {i} should not be a notebook")


# --------------------------------------------------------------------------- #
# Network / manual / skip-download flags match the protocol's description.
# --------------------------------------------------------------------------- #
def test_network_flags() -> None:
    by_id = {s.id: s for s in ra.STEPS}
    # Networked steps per the protocol: 0 (auth) + 2..8 (downloads).
    expected_network = {0, 2, 3, 4, 5, 6, 7, 8}
    got_network = {s.id for s in ra.STEPS if s.network}
    check(got_network == expected_network,
          f"network steps {got_network} != expected {expected_network}")

    # The network-free PROCESSING half is exactly 1 + 9..14.
    expected_free = {1, 9, 10, 11, 12, 13, 14}
    got_free = {s.id for s in ra.STEPS if not s.network}
    check(got_free == expected_free,
          f"network-free steps {got_free} != expected {expected_free}")
    check(set(ra.PROCESSING_HALF) == expected_free,
          f"PROCESSING_HALF {set(ra.PROCESSING_HALF)} != {expected_free}")


def test_manual_touchpoints() -> None:
    by_id = {s.id: s for s in ra.STEPS}
    # The three documented manual touch-points: S0 logins, S7 PRISM, S8 SVI CSV.
    for i in (0, 7, 8):
        check(bool(by_id[i].manual), f"step {i} should carry a manual note")
    # No OTHER step should claim a manual prerequisite.
    manual_ids = {s.id for s in ra.STEPS if s.manual}
    check(manual_ids == {0, 7, 8},
          f"manual steps {manual_ids} != expected {{0, 7, 8}}")
    # Content sanity: the notes name their real subject.
    check("login" in by_id[0].manual.lower() or "interactive" in by_id[0].manual.lower(),
          "S0 note should mention the logins")
    check("prism" in by_id[7].manual.lower(), "S7 note should mention PRISM")
    check("svi" in by_id[8].manual.lower(), "S8 note should mention the SVI CSV")


def test_skip_download_flags() -> None:
    by_id = {s.id: s for s in ra.STEPS}
    # Every DOWNLOAD step (2..8) exposes a skip-download flag; 0 and the
    # processing half do not.
    for i in range(2, 9):
        check(by_id[i].skip_download_flag == "--skip-download",
              f"step {i} should expose --skip-download")
    check(by_id[0].skip_download_flag is None, "step 0 has nothing to download")
    for i in ra.PROCESSING_HALF:
        check(by_id[i].skip_download_flag is None,
              f"processing step {i} should not expose a skip-download flag")


# --------------------------------------------------------------------------- #
# Selection logic: --from / --to / --only.
# --------------------------------------------------------------------------- #
def _ids(steps) -> list[int]:
    return [s.id for s in steps]


def test_select_default_is_all() -> None:
    check(_ids(ra.select_steps()) == list(range(15)), "default selection = all 0..14")


def test_select_from_to() -> None:
    check(_ids(ra.select_steps(from_id=9)) == [9, 10, 11, 12, 13, 14],
          "--from 9 = 9..14")
    check(_ids(ra.select_steps(to_id=1)) == [0, 1], "--to 1 = 0,1")
    check(_ids(ra.select_steps(from_id=2, to_id=8)) == [2, 3, 4, 5, 6, 7, 8],
          "--from 2 --to 8 = the download half")
    check(_ids(ra.select_steps(from_id=5, to_id=5)) == [5], "single-step range")


def test_select_only() -> None:
    check(_ids(ra.select_steps(only=[9, 12])) == [9, 12], "--only 9,12")
    # Always returned sorted/deduped regardless of input order.
    check(_ids(ra.select_steps(only=[12, 9, 9])) == [9, 12],
          "--only is sorted + de-duplicated")
    # --only overrides --from/--to.
    check(_ids(ra.select_steps(from_id=0, to_id=14, only=[3])) == [3],
          "--only overrides the range")


def test_select_errors() -> None:
    for bad, label in (
        (dict(only=[99]), "unknown --only id"),
        (dict(from_id=8, to_id=2), "--from > --to"),
    ):
        try:
            ra.select_steps(**bad)
            check(False, f"{label} should raise ValueError")
        except ValueError:
            check(True, label)


def test_parse_only() -> None:
    check(ra._parse_only(None) is None, "no --only -> None")
    check(ra._parse_only("9") == [9], "single id parses")
    check(ra._parse_only("9, 12 ,13") == [9, 12, 13], "whitespace tolerated")
    check(ra._parse_only("") == [], "empty string -> []")


# --------------------------------------------------------------------------- #
# Command construction.
# --------------------------------------------------------------------------- #
def test_build_command_module() -> None:
    by_id = {s.id: s for s in ra.STEPS}
    cmd = ra.build_command(by_id[9])
    check(cmd[:5] == ra._conda_python()[:5] or "conda" in cmd[0].lower(),
          "module command should start with the conda launcher")
    check("run" in cmd and "canopy" in cmd, "command runs in the canopy env")
    check(any(c.endswith("section9_harmonize.py") for c in cmd),
          "step 9 command should target section9_harmonize.py")
    check("-v" not in cmd, "no -v unless requested")
    check("--skip-download" not in cmd, "no --skip-download unless requested")


def test_build_command_verbose_and_skip() -> None:
    by_id = {s.id: s for s in ra.STEPS}
    # Networked step with skip-download requested -> flag present.
    cmd = ra.build_command(by_id[2], skip_download=True, verbose=True)
    check("--skip-download" in cmd, "step 2 should receive --skip-download")
    check("-v" in cmd, "step 2 should receive -v")

    # A processing step has no skip-download flag, so it must NOT get one even
    # when skip_download=True; it still accepts -v.
    cmd = ra.build_command(by_id[12], skip_download=True, verbose=True)
    check("--skip-download" not in cmd, "step 12 must not receive --skip-download")
    check("-v" in cmd, "step 12 should still receive -v")

    # check_auth (step 0) has no -v flag and nothing to skip.
    cmd = ra.build_command(by_id[0], skip_download=True, verbose=True)
    check("-v" not in cmd, "step 0 (check_auth) takes no -v")
    check("--skip-download" not in cmd, "step 0 has nothing to skip")


def test_build_command_notebook() -> None:
    by_id = {s.id: s for s in ra.STEPS}
    cmd = ra.build_command(by_id[14])
    check("nbconvert" in cmd, "step 14 runs via nbconvert")
    check("--execute" in cmd and "--inplace" in cmd, "nbconvert executes inplace")
    check(any(c.endswith("14_exploratory_threshold.ipynb") for c in cmd),
          "step 14 targets the notebook")
    check("-v" not in cmd, "nbconvert call carries no -v")


def test_conda_launcher_respects_env() -> None:
    saved = os.environ.get("CONDA_EXE")
    try:
        os.environ["CONDA_EXE"] = "/custom/conda"
        check(ra._conda_python()[0] == "/custom/conda",
              "CONDA_EXE should override the launcher path")
    finally:
        if saved is None:
            os.environ.pop("CONDA_EXE", None)
        else:
            os.environ["CONDA_EXE"] = saved


def test_deliverable_paths_absolute() -> None:
    by_id = {s.id: s for s in ra.STEPS}
    paths = ra.deliverable_paths(by_id[9])
    check(len(paths) == 2, "step 9 declares 2 outputs")
    check(all(p.is_absolute() for p in paths), "deliverable paths are absolute")
    check(ra.deliverable_paths(by_id[0]) == [], "step 0 declares no outputs")


# --------------------------------------------------------------------------- #
# Runner.
# --------------------------------------------------------------------------- #
def main() -> int:
    tests = [
        test_registry_wellformed,
        test_only_step14_is_notebook,
        test_network_flags,
        test_manual_touchpoints,
        test_skip_download_flags,
        test_select_default_is_all,
        test_select_from_to,
        test_select_only,
        test_select_errors,
        test_parse_only,
        test_build_command_module,
        test_build_command_verbose_and_skip,
        test_build_command_notebook,
        test_conda_launcher_respects_env,
        test_deliverable_paths_absolute,
    ]
    print(f"Running {len(tests)} test functions for run_all.py ...")
    for t in tests:
        try:
            t()
        except Exception:  # noqa: BLE001
            global _FAILED
            _FAILED += 1
            print(f"  ERROR in {t.__name__}:")
            traceback.print_exc()
    print("-" * 60)
    print(f"run_all.py tests: {_PASSED} checks passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
