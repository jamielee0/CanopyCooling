#!/usr/bin/env python3
"""Build open, coefficient-free D1d diagnostic figures."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from urban_cooling_v2.stage1_precision_census import required_count


INK = "#183642"
BLUE = "#277DA1"
ORANGE = "#F28E2B"
RED = "#B23A48"
GREEN = "#1B7F5B"
GRID = "#CBD8DD"


def save_both(fig, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(base.with_suffix(".png"), dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(base.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def se_distribution(stage: pd.DataFrame, output: Path) -> None:
    se = pd.to_numeric(stage["spatially_robust_se_K_per_10pp"], errors="coerce").dropna()
    span = pd.to_numeric(stage["canopy_span_p10_p90"], errors="raise").to_numpy()
    if len(se):
        fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.1))
        axes[0].hist(se, bins=35, color=BLUE, alpha=0.88, edgecolor="white")
        ordered = np.sort(se.to_numpy())
        axes[1].step(ordered, np.arange(1, len(ordered) + 1) / len(ordered), where="post", color=BLUE, lw=2)
        for value, label in zip(np.quantile(ordered, [0.25, 0.5, 0.75]), ["P25", "Median", "P75"]):
            for axis in axes:
                axis.axvline(value, color=ORANGE, lw=1.2, ls="--")
        axes[0].set_xlabel("Spatially robust SE (K per 10 pp)")
        axes[0].set_ylabel("Block-passes")
        axes[1].set_xlabel("Spatially robust SE (K per 10 pp)")
        axes[1].set_ylabel("Empirical cumulative share")
        fig.suptitle("D1d spatially robust Stage-1 standard errors", color=INK, weight="bold")
    else:
        fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.1))
        axes[0].hist(span, bins=40, color=BLUE, alpha=0.88, edgecolor="white")
        axes[0].axvline(0.20, color=RED, lw=2, ls="--", label="Frozen 0.20 floor")
        axes[0].set_xlabel("Canopy p10-p90 span (fraction)")
        axes[0].set_ylabel("Candidate block-passes")
        axes[0].legend(frameon=False)
        ordered = np.sort(span)
        axes[1].step(ordered, np.arange(1, len(ordered) + 1) / len(ordered), where="post", color=BLUE, lw=2)
        axes[1].axvline(0.20, color=RED, lw=2, ls="--")
        axes[1].set_xlabel("Canopy p10-p90 span (fraction)")
        axes[1].set_ylabel("Empirical cumulative share")
        fig.suptitle("No Stage-1 SE distribution is estimable", color=RED, weight="bold")
        fig.text(
            0.5,
            0.91,
            "All 13,210 candidate block-passes fall below the frozen 0.20 canopy-span floor; panels show the nonthermal failure diagnostic.",
            ha="center",
            va="center",
            fontsize=9,
            color=INK,
        )
    for axis in axes:
        axis.grid(axis="y", color=GRID, lw=0.6, alpha=0.75)
        axis.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(rect=(0, 0, 1, 0.87))
    save_both(fig, output)


def n_required(power: pd.DataFrame, output: Path) -> None:
    reliabilities = [0.30, 0.50, 0.70]
    sigma = np.linspace(0.01, 1.0, 300)
    maxima = (
        power.groupby("city", as_index=True)["available_connected_block_passes_D1b"]
        .max()
        .to_dict()
    )
    fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.2), sharey=True)
    for axis, reliability in zip(axes, reliabilities):
        detection = np.array([required_count(value, reliability, "detection") for value in sigma])
        equivalence = np.array([required_count(value, reliability, "equivalence") for value in sigma])
        axis.plot(sigma, detection, color=BLUE, lw=2, label="Detection")
        axis.plot(sigma, equivalence, color=ORANGE, lw=2, label="Equivalence")
        axis.axhline(maxima["Phoenix"], color=GREEN, lw=1.4, ls="--", label="Phoenix max D1b")
        axis.axhline(maxima["Los Angeles"], color=INK, lw=1.4, ls=":", label="Los Angeles max D1b")
        axis.set_yscale("log")
        axis.set_xlim(0, 1.0)
        axis.set_ylim(1, max(float(equivalence.max()) * 1.15, max(maxima.values()) * 1.35))
        axis.set_title(f"Reliability {reliability:.2f}", color=INK, weight="bold")
        axis.set_xlabel(r"Hypothetical $\sigma_s$ (K per 10 pp)")
        axis.grid(True, which="both", color=GRID, lw=0.55, alpha=0.7)
        axis.spines[["top", "right"]].set_visible(False)
        axis.text(
            0.04,
            0.96,
            "Observed $\sigma_s$: not estimable",
            transform=axis.transAxes,
            ha="left",
            va="top",
            fontsize=8,
            color=RED,
            bbox={"facecolor": "white", "edgecolor": GRID, "boxstyle": "round,pad=0.25"},
        )
    axes[0].set_ylabel("Required connected block-passes (log scale)")
    handles, labels = axes[-1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle(
        "Closed-form planning curves; the five-pass observed-SE marker is unavailable",
        color=INK,
        weight="bold",
    )
    fig.tight_layout(rect=(0, 0.09, 1, 0.92))
    save_both(fig, output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage_csv", type=Path)
    parser.add_argument("power_csv", type=Path)
    parser.add_argument("figure_dir", type=Path)
    args = parser.parse_args()
    stage = pd.read_csv(args.stage_csv)
    power = pd.read_csv(args.power_csv)
    se_distribution(stage, args.figure_dir / "d1d_se_distribution")
    n_required(power, args.figure_dir / "d1d_n_required")
    print("D1d figures written: 2 PNG + 2 SVG; no coefficient field opened")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

