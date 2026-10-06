#!/usr/bin/env python3
"""Build a presentation figure for the official Science TCC canopy-span screen."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def validate_manifest(manifest: Mapping[str, Any]) -> tuple[np.ndarray, list[str], float]:
    rows = list(manifest["rows"])
    spans = np.asarray([float(row["canopy_span_fraction"]) for row in rows])
    passes = [str(row["pass_id"]) for row in rows]
    threshold = float(manifest["canopy_span_fraction"]["frozen_floor"])
    if len(rows) != int(manifest["candidate_block_passes"]):
        raise ValueError("Candidate count does not match row count")
    observed_eligible = int(np.sum(spans >= threshold))
    if observed_eligible != int(manifest["eligible_block_passes"]):
        raise ValueError("Eligible count does not reproduce")
    if not np.isclose(spans.max(), float(manifest["canopy_span_fraction"]["maximum"])):
        raise ValueError("Maximum canopy span does not reproduce")
    return spans, passes, threshold


def build(manifest_path: Path, png_path: Path, svg_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    spans, passes, threshold = validate_manifest(manifest)
    pass_ids = [row["pass_id"] for row in manifest["pass_counts"]]
    by_pass = [spans[np.asarray(passes) == pass_id] for pass_id in pass_ids]

    navy = "#17324D"
    teal = "#0E7490"
    red = "#B91C1C"
    grid = "#CBD5E1"

    fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.2), constrained_layout=True)
    fig.suptitle(
        "Official Science TCC screen: no block-pass reaches the frozen canopy-span floor",
        fontsize=16,
        fontweight="bold",
        color=navy,
    )

    axes[0].hist(spans, bins=np.linspace(0, threshold, 31), color=teal, alpha=0.9)
    axes[0].axvline(threshold, color=red, linewidth=2.2, label="Frozen floor = 0.20")
    axes[0].axvline(np.median(spans), color=navy, linewidth=1.8, linestyle="--", label=f"Median = {np.median(spans):.3f}")
    axes[0].axvline(spans.max(), color="#D97706", linewidth=1.8, linestyle=":", label=f"Maximum = {spans.max():.3f}")
    axes[0].set_title(f"All candidate block-passes (n={len(spans):,})", fontweight="bold")
    axes[0].set_xlabel("Canopy p10-p90 span (fraction)")
    axes[0].set_ylabel("Block-passes")
    axes[0].legend(frameon=False, fontsize=9)

    box = axes[1].boxplot(
        by_pass,
        tick_labels=[str(pass_id).split(":")[-1] for pass_id in pass_ids],
        patch_artist=True,
        showfliers=False,
        whis=(5, 95),
    )
    for patch in box["boxes"]:
        patch.set_facecolor("#BFE3EA")
        patch.set_edgecolor(teal)
    for median in box["medians"]:
        median.set_color(navy)
        median.set_linewidth(1.6)
    axes[1].axhline(threshold, color=red, linewidth=2.2, label="Frozen floor = 0.20")
    axes[1].scatter(
        range(1, len(by_pass) + 1),
        [values.max() for values in by_pass],
        color="#D97706",
        marker="D",
        s=34,
        zorder=3,
        label="Pass maximum",
    )
    axes[1].set_title("Distribution within each preselected native-grid pass", fontweight="bold")
    axes[1].set_xlabel("ECOSTRESS orbit")
    axes[1].set_ylabel("Canopy p10-p90 span (fraction)")
    axes[1].legend(frameon=False, fontsize=9, loc="upper left")

    for axis in axes:
        axis.grid(axis="y", color=grid, linewidth=0.7, alpha=0.8)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.set_ylim(bottom=0)

    fig.text(
        0.5,
        -0.01,
        "Official USFS Science TCC v2025-6; five frozen Phoenix passes; optimistic nonthermal mask; 0 of 13,509 eligible. No LST or coefficient was opened.",
        ha="center",
        fontsize=9,
        color="#475569",
    )
    png_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(svg_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("png", type=Path)
    parser.add_argument("svg", type=Path)
    args = parser.parse_args()
    build(args.manifest, args.png, args.svg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
