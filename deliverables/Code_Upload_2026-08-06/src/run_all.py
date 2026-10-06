#!/usr/bin/env python3
r"""run_all — end-to-end pipeline driver for the Phoenix urban-canopy thermal pilot.

Inputs : raw downloads + data/interim + data/processed (per-step; see STEPS registry)
Outputs: every pilot deliverable, raw download -> first threshold estimate
         (reference grid, cubes, zarr stores, master_table.parquet, Sec 14 figures)
Key decisions (full rationale in docs/DESIGN_DECISIONS.md, Section run_all):
  - Declarative STEP REGISTRY (ids 0-16) drives selection/plan/execution.
  - Every step runs via `conda run -n canopy python ...` (never the env python directly).
  - Steps 9-14 are the network-free, cleanly re-runnable processing half.
  - Import-safe: registry + selection/build_command have no import-time side effects.
  - Manual touch-points stay manual: S0 logins, S7 PRISM rate-limit, S8 SVI CSV.
Run: python src/run_all.py [--from N] [--to N] [--only a,b] [--dry-run]
                          [--check-deliverables] [--skip-download] [-v/--verbose]
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

# Make the sibling config module importable whether run from repo root or src/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
import config  # noqa: E402

log = logging.getLogger("run_all")


# --- Step registry --------------------------------------------------------- #
@dataclass(frozen=True)
class Step:
    """One pipeline stage in dependency order (id 0-16, exactly one runner)."""

    id: int
    name: str
    outputs: tuple[str, ...]
    module: str | None = None
    notebook: str | None = None
    network: bool = False
    manual: str = ""
    skip_download_flag: str | None = None
    extra_args: tuple[str, ...] = field(default_factory=tuple)


# Output paths are repo-root-relative, resolved against config.BASE_DIR in
# deliverable_paths(). ECOSTRESS cubes are Zarr dirs saved without a .zarr suffix.
STEPS: tuple[Step, ...] = (
    Step(
        id=0,
        name="check_auth",
        module="src/check_auth.py",
        outputs=(),  # smoke test only; produces no file
        network=True,
        manual="S0: the four account logins (Earthdata/EE/CDS/Census) are "
        "one-time interactive and cannot be scripted; check_auth only verifies "
        "they are configured.",
        skip_download_flag=None,
    ),
    Step(
        id=1,
        name="reference_grid",
        module="src/build_reference_grid.py",
        outputs=("data/processed/reference_grid.tif",),
        network=False,
    ),
    Step(
        id=2,
        name="ecostress_lst",
        module="src/section2_ecostress_lst.py",
        outputs=(
            "data/interim/ecostress_lst_cube",
            "data/interim/ecostress_lst_granule_report.csv",
        ),
        network=True,
        skip_download_flag="--skip-download",
    ),
    Step(
        id=3,
        name="ecostress_et_esi",
        module="src/section3_ecostress_et_esi.py",
        outputs=(
            "data/interim/ecostress_et_cube",
            "data/interim/ecostress_esi_cube",
            "data/interim/overpass_links.parquet",
        ),
        network=True,
        skip_download_flag="--skip-download",
    ),
    Step(
        id=4,
        name="sentinel2_indices",
        module="src/section4_sentinel2_indices.py",
        outputs=(
            "data/interim/s2_ndvi_warmseason_median_2023_70m.tif",
            "data/interim/s2_ndmi_warmseason_median_2023_70m.tif",
        ),
        network=True,
        skip_download_flag="--skip-download",
    ),
    Step(
        id=5,
        name="landcover",
        module="src/section5_landcover.py",
        outputs=(
            "data/interim/nlcd_impervious_2021_70m.tif",
            "data/interim/usfs_tcc_canopy_2025_70m.tif",
            "data/interim/nlcd_landcover_class_2021_70m.tif",
        ),
        network=True,
        skip_download_flag="--skip-download",
    ),
    Step(
        id=6,
        name="era5land_vpd_sm",
        module="src/section6_era5land_vpd_sm.py",
        outputs=("data/interim/era5land_vpd_sm_hourly_2018_2024.nc",),
        network=True,
        skip_download_flag="--skip-download",
    ),
    Step(
        id=7,
        name="precip_drought",
        module="src/section7_precip_drought.py",
        outputs=(
            "data/interim/prism_antecedent_precip_70m.zarr",
            "data/interim/prism_tmean_70m.zarr",
            "data/interim/gridmet_drought_70m.zarr",
        ),
        network=True,
        manual="S7: PRISM is rate-limited (2x/IP/day); self-heals via the 800 m "
        "endpoint but a hard wall may need a manual re-run the next day.",
        skip_download_flag="--skip-download",
    ),
    Step(
        id=8,
        name="neighborhood_tree",
        module="src/section8_neighborhood_tree.py",
        outputs=(
            "data/interim/neighborhood_blockgroups_32612.parquet",
            "data/interim/phoenix_tree_inventory.parquet",
            "data/interim/building_footprints_32612.parquet",
            "data/interim/acs_median_income_70m.tif",
            "data/interim/acs_pct_people_of_colour_70m.tif",
            "data/interim/cdc_svi_rpl_themes_70m.tif",
        ),
        network=True,
        manual="S8: the CDC/ATSDR SVI CSV is USER-PLACED in data/raw/svi/ "
        "(not fetched from code).",
        skip_download_flag="--skip-download",
    ),
    Step(
        id=9,
        name="harmonize",
        module="src/section9_harmonize.py",
        outputs=(
            "data/processed/analysis_cube_70m.zarr",
            "data/processed/analysis_overpass_table.parquet",
        ),
        network=False,
    ),
    Step(
        id=10,
        name="classify_pixels",
        module="src/section10_classify_pixels.py",
        outputs=(
            "data/processed/section10_pixel_class_70m.tif",
            "data/processed/section10_paired_neighborhoods.csv",
            "data/processed/section10_threshold_sensitivity.csv",
            "data/processed/section10_validation_sample.csv",
        ),
        network=False,  # only the contextily basemap tiles, which --no-basemap drops
    ),
    Step(
        id=11,
        name="anomalies",
        module="src/section11_anomalies.py",
        outputs=(
            "data/processed/section11_zscores_70m.zarr",
            "data/processed/section11_zscores_overpass_summary.parquet",
        ),
        network=False,
    ),
    Step(
        id=12,
        name="compound_stress",
        module="src/section12_compound_stress.py",
        outputs=(
            "data/processed/section12_csi_70m.zarr",
            "data/processed/section12_csi_overpass_summary.parquet",
            "data/processed/section12_weight_sensitivity.parquet",
        ),
        network=False,
    ),
    Step(
        id=13,
        name="master_table",
        module="src/section13_master_table.py",
        outputs=(
            "data/processed/master_table.parquet",
            "data/processed/master_pixel_table.parquet",  # B3.1 pixel-level paired table
        ),
        network=False,
    ),
    Step(
        id=14,
        name="exploratory_threshold",
        notebook="notebooks/14_exploratory_threshold.ipynb",
        outputs=(
            "notebooks/14_exploratory_threshold.ipynb",
            "docs/section14_results_note.md",
            "data/processed/section14_csi_weight_sensitivity.csv",
            "figures/section14_scatter_ca_vs_csi.png",
            "figures/section14_segmented_and_bootstrap.png",
        ),
        network=False,
    ),
    # B1b: the 2-D VPD_z x SM_z response surface — the primary RQ1 detector
    # (BG-mean descriptive; reads master_table.parquet). Registered AFTER id=14 and
    # BEFORE the id=16 mixed-effects step so ids stay contiguous 0..16.
    Step(
        id=15,
        name="response_surface",
        module="src/section15_response_surface.py",
        outputs=(
            "figures/section15_response_surface_vpdz_smz.png",
            "figures/section15_response_surface_vpdz_smz_day.png",
        ),
        network=False,
    ),
    # B3.2/B3.3: pixel-level crossed-random-effects model + BG cluster bootstrap
    # (reads master_pixel_table.parquet). Needs statsmodels; when absent the step writes
    # a diagnostic note and exits non-zero so blocker verification cannot pass silently.
    Step(
        id=16,
        name="mixed_effects",
        module="src/section14b_mixed_effects.py",
        outputs=("docs/section14b_mixed_effects_note.md",),
        network=False,
    ),
)

# Every non-network step (1 and 9..16) is locally re-runnable; --from 9 selects the
# network-free processing/analysis half used for saved-interim rebuilds.
PROCESSING_HALF: tuple[int, ...] = tuple(s.id for s in STEPS if not s.network)


# --- Pure logic: selection + command construction (no side effects) -------- #
def _steps_by_id() -> dict[int, Step]:
    return {s.id: s for s in STEPS}


def validate_registry(steps: Sequence[Step] = STEPS) -> None:
    """Assert the registry is well-formed (contiguous ids 0..N, one runner each)."""
    ids = [s.id for s in steps]
    assert ids == list(range(len(steps))), f"step ids must be 0..N contiguous, got {ids}"
    for s in steps:
        has_module = s.module is not None
        has_nb = s.notebook is not None
        assert has_module ^ has_nb, f"step {s.id} must have exactly one of module/notebook"
        # Step 0 is a pure smoke test with nothing to download; every other
        # networked step must expose how to skip its download.
        if s.network and s.id != 0:
            assert s.skip_download_flag is not None, (
                f"networked step {s.id} should declare a skip_download_flag"
            )
        if not s.network:
            assert s.skip_download_flag is None, (
                f"non-networked step {s.id} should not declare a skip_download_flag"
            )


def select_steps(
    *,
    from_id: int | None = None,
    to_id: int | None = None,
    only: Sequence[int] | None = None,
    steps: Sequence[Step] = STEPS,
) -> list[Step]:
    """Resolve CLI range/subset flags to an ordered, de-duplicated step list.

    --only overrides --from/--to; no flags returns all. Always sorted by id.
    """
    by_id = {s.id: s for s in steps}
    if only is not None:
        missing = sorted(set(only) - set(by_id))
        if missing:
            raise ValueError(f"--only refers to unknown step id(s): {missing}")
        chosen = sorted(set(only))
    else:
        lo = from_id if from_id is not None else min(by_id)
        hi = to_id if to_id is not None else max(by_id)
        if lo > hi:
            raise ValueError(f"--from {lo} is greater than --to {hi}")
        chosen = [i for i in sorted(by_id) if lo <= i <= hi]
    return [by_id[i] for i in chosen]


def _conda_python() -> list[str]:
    """The `conda run -n canopy python` launcher prefix (never the env python directly).

    conda.exe is discovered from the standard Anaconda location, overridable via CONDA_EXE.
    """
    conda_exe = os.environ.get("CONDA_EXE")
    if not conda_exe:
        userprofile = os.environ.get("USERPROFILE") or str(Path.home())
        conda_exe = str(Path(userprofile) / "anaconda3" / "Scripts" / "conda.exe")
    return [conda_exe, "run", "--no-capture-output", "-n", "canopy", "python"]


def build_command(
    step: Step,
    *,
    skip_download: bool = False,
    verbose: bool = False,
) -> list[str]:
    """Construct the full argv that runs one step in the `canopy` env.

    Modules run as `python <module> [flags]`; the Sec 14 notebook via nbconvert
    --execute (no flags forwarded). --skip-download/-v forwarded only where supported.
    """
    if step.notebook is not None:
        nb = str((config.BASE_DIR / step.notebook).resolve())
        return _conda_python()[:-1] + [
            "-m",
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            "--inplace",
            nb,
        ]

    assert step.module is not None
    mod = str((config.BASE_DIR / step.module).resolve())
    cmd = _conda_python() + [mod]
    cmd += list(step.extra_args)
    if skip_download and step.skip_download_flag:
        cmd.append(step.skip_download_flag)
    # check_auth.py has no -v flag; every section module does.
    if verbose and step.id != 0:
        cmd.append("-v")
    return cmd


def deliverable_paths(step: Step) -> list[Path]:
    """Absolute paths of a step's declared output deliverables."""
    return [(config.BASE_DIR / o).resolve() for o in step.outputs]


# --- Presentation: plan / legend / deliverable audit ----------------------- #
def _runner_str(step: Step) -> str:
    if step.notebook is not None:
        return f"nbconvert --execute {step.notebook}"
    return f"python {step.module}"


def print_plan(selected: Sequence[Step], *, skip_download: bool) -> None:
    """Print the ordered plan + the manual/network legend."""
    print("=" * 78)
    print("URBAN CANOPY THERMAL THRESHOLDS — Phoenix pilot : end-to-end pipeline")
    print("=" * 78)
    print("Dependency order (run top-to-bottom; 9-14 are the network-free half):")
    print("-" * 78)
    print(f"  {'ID':>2}  {'STEP':<22} {'NET':^4} {'MAN':^4}  COMMAND")
    print("-" * 78)
    for s in selected:
        net = "yes" if s.network else " - "
        man = "yes" if s.manual else " - "
        print(f"  {s.id:>2}  {s.name:<22} {net:^4} {man:^4}  {_runner_str(s)}")
    print("-" * 78)
    print("Legend:  NET = needs network/configured auth   MAN = has a manual prerequisite")
    if skip_download:
        print("         --skip-download is ON (steps reuse saved raw/interim where supported)")
    print()
    print("Manual / not-fully-automatable touch-points:")
    for s in selected:
        if s.manual:
            print(f"  [S{s.id}] {s.manual}")
    if not any(s.manual for s in selected):
        print("  (none in this selection)")
    if any(s.network for s in selected):
        print("  [auth] networked steps (2-8) also require the S0 credentials configured")
        print("         (Earthdata netrc, Earth Engine project, ~/.cdsapirc, CENSUS_API_KEY).")
    print()


def check_deliverables(selected: Sequence[Step]) -> bool:
    """Read-only audit of each selected step's outputs; True iff all present.

    Prints a PASS/MISSING table; steps with no output (S0) report N/A and never fail.
    """
    print("=" * 78)
    print("DELIVERABLE AUDIT  (read-only)")
    print("=" * 78)
    print(f"  {'ID':>2}  {'STEP':<22} {'STATUS':<8} OUTPUT")
    print("-" * 78)
    all_ok = True
    for s in selected:
        if not s.outputs:
            print(f"  {s.id:>2}  {s.name:<22} {'N/A':<8} (smoke test — no file output)")
            continue
        for path in deliverable_paths(s):
            exists = path.exists()
            all_ok = all_ok and exists
            status = "PASS" if exists else "MISSING"
            rel = path.relative_to(config.BASE_DIR)
            print(f"  {s.id:>2}  {s.name:<22} {status:<8} {rel}")
    print("-" * 78)
    print("RESULT:", "ALL PRESENT ✓" if all_ok else "SOME MISSING ✗")
    print()
    return all_ok


# --- Execution ------------------------------------------------------------- #
def run_step(
    step: Step,
    *,
    skip_download: bool,
    verbose: bool,
) -> int:
    """Run one step as a subprocess, streaming its output. Returns its exit code."""
    cmd = build_command(step, skip_download=skip_download, verbose=verbose)
    log.info("-" * 70)
    log.info("STEP %d (%s) -> running", step.id, step.name)
    if step.manual:
        log.info("  MANUAL note: %s", step.manual)
    if step.network:
        log.info("  NOTE: this step needs network / configured auth.")
    log.info("  $ %s", " ".join(cmd))
    t0 = time.time()
    # No capture: child stdout/stderr stream straight through so long downloads
    # show live progress; cwd = repo root.
    proc = subprocess.run(cmd, cwd=str(config.BASE_DIR))
    dt = time.time() - t0
    if proc.returncode == 0:
        log.info("STEP %d (%s) -> OK  (%.1fs)", step.id, step.name, dt)
    else:
        log.error(
            "STEP %d (%s) -> FAILED (exit %d, %.1fs)",
            step.id,
            step.name,
            proc.returncode,
            dt,
        )
    return proc.returncode


def run_pipeline(
    selected: Sequence[Step],
    *,
    skip_download: bool,
    verbose: bool,
) -> int:
    """Run the selected steps in order, stopping on the first failure."""
    log.info("Executing %d step(s): %s", len(selected), [s.id for s in selected])
    for s in selected:
        rc = run_step(s, skip_download=skip_download, verbose=verbose)
        if rc != 0:
            log.error(
                "Pipeline STOPPED at step %d (%s); exit code %d. "
                "Fix the cause and re-run, e.g. `--from %d`.",
                s.id,
                s.name,
                rc,
                s.id,
            )
            return rc
    log.info("=" * 70)
    log.info("Pipeline finished: all %d selected step(s) succeeded.", len(selected))
    return 0


# --- CLI ------------------------------------------------------------------- #
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_all.py",
        description="End-to-end pipeline driver (raw download -> threshold) for "
        "the Phoenix pilot. Default with no flags prints the plan and a usage "
        "hint (it does NOT auto-run the multi-hour download pipeline).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sel = p.add_argument_group("step selection")
    sel.add_argument("--from", dest="from_id", type=int, default=None,
                     help="first step id to run (inclusive).")
    sel.add_argument("--to", dest="to_id", type=int, default=None,
                     help="last step id to run (inclusive).")
    sel.add_argument("--only", default=None,
                     help="comma-separated step ids to run (overrides --from/--to).")
    mode = p.add_argument_group("modes")
    mode.add_argument("--dry-run", action="store_true",
                      help="print the ordered plan + manual/network legend and exit "
                           "(execute nothing).")
    mode.add_argument("--check-deliverables", action="store_true",
                      help="read-only audit: print a PASS/MISSING table of each "
                           "selected step's output files and exit.")
    p.add_argument("--skip-download", action="store_true",
                   help="forward the download-skip flag to every step that supports "
                        "it so sections reuse saved raw/interim (the way to re-run "
                        "the processing half from disk).")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="debug logging here + forward -v to each section module.")
    return p


def _parse_only(only: str | None) -> list[int] | None:
    if only is None:
        return None
    out: list[int] = []
    for tok in only.split(","):
        tok = tok.strip()
        if tok:
            out.append(int(tok))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    validate_registry()

    try:
        selected = select_steps(
            from_id=args.from_id,
            to_id=args.to_id,
            only=_parse_only(args.only),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Read-only modes first.
    if args.check_deliverables:
        ok = check_deliverables(selected)
        return 0 if ok else 1

    explicit_selection = (
        args.from_id is not None or args.to_id is not None or args.only is not None
    )

    if args.dry_run or not explicit_selection:
        print_plan(selected, skip_download=args.skip_download)
        if not explicit_selection and not args.dry_run:
            # Default (no flags): show the plan, then a usage hint — do NOT run.
            print("No step selection given — nothing was executed.")
            print("  • re-run the network-free processing half:  "
                  "run_all.py --from 9 --skip-download")
            print("  • run a range / subset:                     "
                  "run_all.py --from 2 --to 8   |   --only 9,12")
            print("  • audit deliverables on disk:               "
                  "run_all.py --check-deliverables")
            print("  • full ordered plan + legend:               "
                  "run_all.py --dry-run")
        return 0

    return run_pipeline(
        selected,
        skip_download=args.skip_download,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    raise SystemExit(main())
