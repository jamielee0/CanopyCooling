#!/usr/bin/env python3
"""Section 15 / response surface — the PRIMARY RQ1 detector (BLOCKER B1b).

A 2-D binned response surface: mean cooling advantage (ΔT_cool) binned by
demand (VPD_z, x) × supply (soil-moisture SM_z, y), each cell coloured by mean
ΔT_cool and labelled with its sample count ``n``. It is deliberately DESCRIPTIVE,
not inferential (Guiding Principles 2 & 6): it shows *where* in VPD_z×SM_z space
cooling weakens and displays sparsity via per-cell ``n``. It is intentionally
BG-MEAN based — it reads ``master_table.parquet`` (one row per paired-BG ×
overpass) and its BG-mean columns — a distinct object from the pixel-level
inferential mixed model (B3.2). CSI is demoted to a secondary cross-city scalar.

Inputs : data/processed/master_table.parquet (Section 13) — BG-mean columns:
         x=mean_vpd_z_tree (demand), y=mean_sm_z_tree (supply / soil moisture),
         colour=cooling_advantage (mean ΔT_cool), count=n_tree_valid; plus the
         persisted day/night columns is_day (bool) / local_hour (int).
         (mean_ndmi_z_tree is the vegetation CHECK, not consumed here.)
Outputs: figures/section15_response_surface_vpdz_smz.png       (day+night pooled sensitivity)
         figures/section15_response_surface_vpdz_smz_day.png   (is_day only, primary)
Run: python src/section15_response_surface.py [--verify-only] [-v/--verbose]
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import namedtuple
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

# Make config (and the sibling plot_style) importable whether run from the repo
# root or from src/ — copied verbatim from the other section modules.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
import config  # noqa: E402

log = logging.getLogger("section15")


# --- Source layer + deliverable names --------------------------------------- #
MASTER_PARQUET = "master_table.parquet"                 # Section 13 master table
FIG_SURFACE = "section15_response_surface_vpdz_smz.png"        # day+night pooled sensitivity
FIG_SURFACE_DAY = "section15_response_surface_vpdz_smz_day.png"  # is_day only (primary)

# Master-table columns consumed (contract; produced by Section 13 / B1a / B4).
# Cross-module supply/naming invariant (see PHOENIX_REMEDIATION_PLAN §2): the
# PRIMARY supply axis is mean_sm_z_tree (from sm_z, soil moisture); the renamed
# mean_ndmi_z_tree is the vegetation CHECK and is NOT consumed by this surface.
X_VAR = "mean_vpd_z_tree"        # x axis — demand (VPD z)
Y_VAR = "mean_sm_z_tree"         # y axis — supply (soil-moisture z; PRIMARY)
COLOR_VAR = "cooling_advantage"  # colour — mean ΔT_cool (K)
COUNT_VAR = "n_tree_valid"       # per-cell sample-size column (contract)
IS_DAY_VAR = "is_day"            # persisted day/night flag (B4)
LOCAL_HOUR_VAR = "local_hour"    # persisted local hour (B4)
SAMPLE_LABEL_VAR = "sample_label"  # primary vs low-tree-count sensitivity (B3)

# Default COARSE bin edges (DECISION 3: coarse 3×3 + per-cell n labels).
VPD_BINS = [-1, 0, 1, 3]         # x edges -> 3 demand bins
SM_BINS = [-3, -1, 0, 1]         # y edges -> 3 supply bins

# Columns that MUST be present for the surface (audited by --verify-only).
REQUIRED_COLUMNS = (X_VAR, Y_VAR, COLOR_VAR, COUNT_VAR, IS_DAY_VAR, SAMPLE_LABEL_VAR)


# A plain container for a binned surface (dict-like via ._asdict()).
Surface = namedtuple("Surface", ["mean_cooling", "n", "vpd_edges", "sm_edges"])


# --- Pure logic (numpy / pandas only; unit-tested without matplotlib) -------- #
def binned_surface(vpd_z, supply_z, cooling, *, vpd_bins=VPD_BINS, sm_bins=SM_BINS
                   ) -> "Surface":
    """Bin paired (vpd_z, supply_z, cooling) triples into a 2-D response surface.

    Returns a :class:`Surface` with:
      - ``mean_cooling[i_sm, j_vpd]`` : mean ΔT_cool per cell (NaN for empty cells),
      - ``n[i_sm, j_vpd]``           : int count of pairs assigned to each cell (0 empty),
      - ``vpd_edges`` / ``sm_edges`` : the bin-edge arrays (x / y respectively).

    Rows are DROPPED pairwise when any of vpd_z / supply_z / cooling is NaN, and
    DROPPED when a value falls OUTSIDE the outer edges (never clamped into the edge
    bin). Points exactly on the top outer edge join the last bin (np.histogram
    convention); everything strictly beyond an outer edge is excluded.
    """
    vpd_edges = np.asarray(vpd_bins, dtype="float64")
    sm_edges = np.asarray(sm_bins, dtype="float64")
    x = np.asarray(vpd_z, dtype="float64").ravel()
    y = np.asarray(supply_z, dtype="float64").ravel()
    c = np.asarray(cooling, dtype="float64").ravel()
    if not (x.size == y.size == c.size):
        raise ValueError("vpd_z, supply_z, cooling must be the same length "
                         f"(got {x.size}, {y.size}, {c.size})")

    n_vpd = vpd_edges.size - 1
    n_sm = sm_edges.size - 1
    if n_vpd < 1 or n_sm < 1:
        raise ValueError("need at least 2 edges per axis")

    sums = np.zeros((n_sm, n_vpd), dtype="float64")
    n = np.zeros((n_sm, n_vpd), dtype="int64")

    # Pairwise finite drop: any NaN in the triple removes the whole pair.
    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(c)

    # digitize -> 1..n_bins for interior bins; 0 below range, n_bins+1 at/above top.
    jx = np.digitize(x, vpd_edges)
    iy = np.digitize(y, sm_edges)
    # Points exactly on the top outer edge fold into the last bin (histogram convention).
    jx = np.where(x == vpd_edges[-1], n_vpd, jx)
    iy = np.where(y == sm_edges[-1], n_sm, iy)

    in_range = (jx >= 1) & (jx <= n_vpd) & (iy >= 1) & (iy <= n_sm)
    keep = finite & in_range
    j = jx[keep] - 1     # -> 0-based x (vpd) bin index
    i = iy[keep] - 1     # -> 0-based y (sm) bin index
    val = c[keep]

    np.add.at(sums, (i, j), val)
    np.add.at(n, (i, j), 1)

    with np.errstate(invalid="ignore", divide="ignore"):
        mean_cooling = np.where(n > 0, sums / np.where(n > 0, n, 1), np.nan)

    return Surface(mean_cooling=mean_cooling, n=n, vpd_edges=vpd_edges, sm_edges=sm_edges)


def day_subset(df: "pd.DataFrame") -> "pd.DataFrame":
    """Rows where ``is_day`` is True — the day-only primary analysis (Principle 1).

    Kept as a thin, testable helper so the day filter can be checked without a plot.
    """
    return df[df[IS_DAY_VAR].astype(bool)]


def primary_subset(df: "pd.DataFrame") -> "pd.DataFrame":
    """Day-only rows that also satisfy the pre-committed tree-pixel floor.

    Section 13 persists ``sample_label`` so every primary downstream analysis uses the
    exact same inclusion rule. The count check is repeated defensively to catch a stale or
    malformed label.
    """
    mask = (df[IS_DAY_VAR].astype(bool)
            & df[SAMPLE_LABEL_VAR].eq("primary")
            & (df[COUNT_VAR] >= config.PRIMARY_MIN_TREE_PIXELS))
    return df[mask]


# --- IO layer (thin so tests can bypass it) --------------------------------- #
def load_master(processed_dir) -> "pd.DataFrame":
    """Read ``master_table.parquet`` from ``processed_dir`` and return the DataFrame.

    Intentionally thin (no logic) so the pure functions above can be unit-tested
    without touching disk.
    """
    return pd.read_parquet(Path(processed_dir) / MASTER_PARQUET)


# --- Figure ----------------------------------------------------------------- #
def plot_response_surface(surface: "Surface", *, out_path,
                          title: str = "Section 15: cooling response surface "
                                       "(VPD_z × SM_z)"):
    """Render a binned response surface to ``out_path`` (headless / Agg backend).

    ``pcolormesh`` over the bin edges, coloured by mean ΔT_cool with a RdBu
    diverging map centred at 0 (white = no cooling), each non-empty cell labelled
    with its count ``n`` (cells with ``n == 0`` are left blank). Styling reuses
    ``plot_style`` (CMAP / diverging_norm / ACCENT) — no local restyling.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from plot_style import CMAP, ACCENT, diverging_norm

    mean_cooling = np.asarray(surface.mean_cooling, dtype="float64")
    n = np.asarray(surface.n)
    vpd_edges = np.asarray(surface.vpd_edges, dtype="float64")
    sm_edges = np.asarray(surface.sm_edges, dtype="float64")

    cmap = CMAP.get("cooling_advantage", "RdBu")
    norm = diverging_norm(mean_cooling, vcenter=0.0)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(7.2, 6.0), constrained_layout=True)
    masked = np.ma.masked_invalid(mean_cooling)
    mesh = ax.pcolormesh(vpd_edges, sm_edges, masked, cmap=cmap, norm=norm,
                         edgecolors="#cccccc", linewidth=0.5, shading="flat")

    # Physically meaningful reference lines: VPD_z=0 (demand) and SM_z=0 (supply).
    zero = ACCENT.get("zero_line", "#000000")
    if vpd_edges[0] < 0 < vpd_edges[-1]:
        ax.axvline(0, color=zero, lw=0.8, ls=":")
    if sm_edges[0] < 0 < sm_edges[-1]:
        ax.axhline(0, color=zero, lw=0.8, ls=":")

    # Overlay per-cell n at cell centres; SKIP empty (n == 0) cells.
    xc = 0.5 * (vpd_edges[:-1] + vpd_edges[1:])
    yc = 0.5 * (sm_edges[:-1] + sm_edges[1:])
    for i in range(n.shape[0]):
        for j in range(n.shape[1]):
            if int(n[i, j]) == 0:
                continue
            ax.text(xc[j], yc[i], f"n={int(n[i, j])}", ha="center", va="center",
                    fontsize=9, fontweight="bold", color="#111111",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none",
                              alpha=0.6))

    cbar = fig.colorbar(mesh, ax=ax)
    cbar.set_label(r"$\Delta T_\mathrm{cool}$ (K)   [reference - tree; + = trees cooler]")
    ax.set_xlabel("VPD$_z$ (demand)  —  mean_vpd_z_tree")
    ax.set_ylabel("SM$_z$ (supply, soil moisture)  —  mean_sm_z_tree")
    ax.set_title(title)

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote figure -> %s", out_path.name)
    return out_path


# --- Verification (audit the input without matplotlib state) ----------------- #
def verify_input(parquet_path: Path) -> int:
    """Check the input parquet exists and carries the required columns.

    Prints a short summary and writes nothing. Returns a process exit code
    (0 = ok, non-zero = missing file or columns) so the pipeline can audit.
    """
    parquet_path = Path(parquet_path)
    if not parquet_path.exists():
        log.error("VERIFY: master table not found -> %s (run Section 13 first)",
                  parquet_path)
        return 1
    df = pd.read_parquet(parquet_path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    log.info("=" * 70)
    log.info("VERIFY (Section 15 input): %s", parquet_path.name)
    log.info("  rows                 : %d", len(df))
    log.info("  required columns     : %s", list(REQUIRED_COLUMNS))
    if missing:
        log.error("  MISSING columns      : %s", missing)
        return 1
    n_day = int(df[IS_DAY_VAR].astype(bool).sum()) if IS_DAY_VAR in df.columns else -1
    n_primary = int(len(primary_subset(df))) if not missing else -1
    log.info("  all required present : yes")
    log.info("  is_day True rows     : %d / %d", n_day, len(df))
    log.info("  primary rows         : %d (day + n_tree_valid >= %d)",
             n_primary, config.PRIMARY_MIN_TREE_PIXELS)
    log.info("  VPD_BINS (x)         : %s", VPD_BINS)
    log.info("  SM_BINS  (y)         : %s", SM_BINS)
    log.info("  OK -> nothing written (verify-only).")
    return 0


# --- Orchestration / CLI ---------------------------------------------------- #
def _log_surface(label: str, surf: "Surface") -> None:
    filled = int((surf.n > 0).sum())
    total = int(surf.n.sum())
    log.info("  %-12s: %d/%d cells filled, %d rows binned",
             label, filled, surf.n.size, total)


def run(verify_only: bool = False) -> int:
    processed = config.PROCESSED_DIR
    parquet_path = processed / MASTER_PARQUET

    if verify_only:
        return verify_input(parquet_path)

    if not parquet_path.exists():
        log.error("master table not found -> %s ; run Section 13 first.", parquet_path)
        return 1

    config.ensure_dirs()
    df = load_master(processed)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        log.error("master table missing required columns: %s ; "
                  "run Section 13 (B1a/B4) first.", missing)
        return 1

    figures = config.FIGURES_DIR
    log.info("=" * 70)
    log.info("Section 15: 2-D response surface (VPD_z x SM_z) — descriptive RQ1 detector")

    # Day+night pooled sensitivity surface (B4); never the headline result.
    surf_all = binned_surface(df[X_VAR].to_numpy(), df[Y_VAR].to_numpy(),
                              df[COLOR_VAR].to_numpy())
    _log_surface("day+night pooled sensitivity", surf_all)
    plot_response_surface(
        surf_all, out_path=figures / FIG_SURFACE,
        title=("Section 15: cooling response surface (VPD$_z$ × SM$_z$) — "
               "day+night pooled sensitivity"))

    # DAY-ONLY + tree-pixel-floor surface (primary; B4 + B3).
    primary = primary_subset(df)
    surf_day = binned_surface(primary[X_VAR].to_numpy(), primary[Y_VAR].to_numpy(),
                              primary[COLOR_VAR].to_numpy())
    _log_surface("primary", surf_day)
    plot_response_surface(
        surf_day, out_path=figures / FIG_SURFACE_DAY,
        title=("Section 15: cooling response surface (VPD$_z$ × SM$_z$) — "
               f"day only, n_tree_valid ≥ {config.PRIMARY_MIN_TREE_PIXELS} (primary)"))

    log.info("=" * 70)
    log.info("Section 15 complete. Deliverables (figures/):")
    log.info("  pooled sensitivity -> %s", FIG_SURFACE)
    log.info("  primary      -> %s", FIG_SURFACE_DAY)
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Section 15 - 2-D binned response surface (VPD_z x SM_z), the "
                    "descriptive primary RQ1 detector (BLOCKER B1b).")
    p.add_argument("--verify-only", action="store_true",
                   help="check the input parquet exists + has the required columns "
                        "(prints a summary, writes nothing).")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    return run(verify_only=args.verify_only)


if __name__ == "__main__":
    raise SystemExit(main())
