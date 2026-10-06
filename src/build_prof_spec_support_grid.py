#!/usr/bin/env python3
"""Professor-specified stress-axis grid, rebuilt on the real v2 five-city pass sample.

The advisory review asked for RQ1 detection on a two-dimensional grid: atmospheric
demand on x, water supply on y, colour = mean cooling advantage, every cell labelled
with n. In v2 the x/y axes exist as real, canonical, non-thermal quantities; the
colour axis does not, because no LST value has been opened (D0050/D0058 STOP).

This script therefore renders the professor's grid with observational support in
place of the colour axis, which is the guide's Step 12 instruction to plot where
the data actually are before computing anything from the surface.

Inputs : canonical R0015 Step-2 tables (219 near-nadir passes, 159.087 pass-equivalents)
Outputs: F_PROF.1 support grid PNG + backing CSV
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from matplotlib.patches import Rectangle

PROJECT = Path("/Users/jmlee/Documents/TreeProject/project")
sys.path.insert(0, str(PROJECT / "src"))
from urban_cooling_v2.step02_catalog import condition_cell  # noqa: E402

BASE = PROJECT / (
    "data/processed/v2/task1/"
    "step2_definitive_l1b_geo_D0047_archive_available/tables"
)
OUTDIR = PROJECT / "figures/v2/prof_spec_support_grid"
OUTDIR.mkdir(parents=True, exist_ok=True)

DEMAND_ORDER = ["low", "middle", "high"]
# Professor's orientation: water supply on y, LOW water at the bottom, so the
# predicted collapse corner (high demand / low water) sits bottom-right.
WATER_ORDER = ["dry", "middle", "wet"]  # index 0 = bottom row
CITY_LABEL = {
    "atlanta": "Atlanta",
    "los_angeles": "Los Angeles",
    "miami": "Miami",
    "minneapolis_st_paul": "Minneapolis–St. Paul",
    "phoenix": "Phoenix",
}
MIN_CORNER = 10.0  # frozen minimum pass-equivalents per identification corner


def load_passes() -> pd.DataFrame:
    template = pd.read_csv(BASE / "step3_empirical_template.csv")
    cells = condition_cell(
        template["demand_percentile"], template["antecedent_dryness_percentile"]
    ).to_numpy()
    template["condition_cell"] = cells
    template["demand_level"] = [c.split("__")[0].replace("demand_", "") for c in cells]
    template["water_level"] = [
        c.split("__")[1].replace("antecedent_", "") for c in cells
    ]
    return template


def verify_against_canonical(template: pd.DataFrame) -> None:
    """Fail loudly if the reconstruction does not reproduce the published table."""
    canonical = pd.read_csv(BASE / "step2_definitive_condition_counts.csv")
    mine = (
        template.groupby(["city", "condition_cell"])
        .agg(n_passes=("condition_cell", "size"), equiv=("sampling_weight", "sum"))
        .reset_index()
    )
    merged = canonical.merge(
        mine, on=["city", "condition_cell"], how="outer", indicator=True
    )
    assert (merged["_merge"] == "both").all(), "cell set differs from canonical table"
    assert (merged["n_passes_x"] - merged["n_passes_y"]).abs().max() == 0
    assert (
        merged["expected_pass_equivalents"] - merged["equiv"]
    ).abs().max() < 1e-9, "pass-equivalents differ from canonical table"


def grid_matrix(frame: pd.DataFrame, value: str) -> np.ndarray:
    """Rows = water level (bottom-up dry→wet), cols = demand level (low→high)."""
    out = np.zeros((3, 3))
    for r, water in enumerate(WATER_ORDER):
        for c, demand in enumerate(DEMAND_ORDER):
            sel = frame[
                (frame["water_level"] == water) & (frame["demand_level"] == demand)
            ]
            out[r, c] = sel[value].sum() if value != "n" else len(sel)
    return out


def draw_grid(
    ax,
    equiv: np.ndarray,
    counts: np.ndarray,
    *,
    title: str,
    vmax: float,
    annotate: bool = True,
    fontsize: int = 11,
    label_bbox: bool = False,
) -> None:
    im = ax.imshow(
        equiv,
        origin="lower",
        cmap="Purples",
        vmin=0.0,
        vmax=vmax,
        extent=(0, 3, 0, 3),
        aspect="auto",
    )
    ax.set_xticks([0.5, 1.5, 2.5])
    ax.set_xticklabels(["low", "middle", "high"])
    ax.set_yticks([0.5, 1.5, 2.5])
    ax.set_yticklabels(["dry", "middle", "wet"])
    for edge in (1, 2):
        ax.axvline(edge, color="white", lw=1.2)
        ax.axhline(edge, color="white", lw=1.2)
    if annotate:
        box = (
            dict(boxstyle="round,pad=0.22", fc="white", ec="none", alpha=0.62)
            if label_bbox
            else None
        )
        for r in range(3):
            for c in range(3):
                shade = equiv[r, c] / vmax if vmax else 0.0
                colour = "white" if (shade > 0.55 and not label_bbox) else "#1a1a1a"
                ax.text(
                    c + 0.5,
                    r + 0.62,
                    f"{int(counts[r, c])} passes",
                    ha="center",
                    va="center",
                    fontsize=fontsize,
                    color=colour,
                    fontweight="bold",
                    bbox=box,
                    zorder=7,
                )
                ax.text(
                    c + 0.5,
                    r + 0.34,
                    f"{equiv[r, c]:.2f} eq.",
                    ha="center",
                    va="center",
                    fontsize=fontsize - 1,
                    color=colour,
                    bbox=box,
                    zorder=7,
                )
    ax.set_title(title, fontsize=fontsize + 1, pad=6)
    ax._im = im


def main() -> None:
    passes = load_passes()
    verify_against_canonical(passes)

    equiv = grid_matrix(passes, "sampling_weight")
    counts = grid_matrix(passes, "n")
    vmax = float(equiv.max())

    fig = plt.figure(figsize=(15.5, 12.5))

    # ---- Panel A: pooled grid + the real 219 passes -------------------------
    ax = fig.add_axes([0.105, 0.560, 0.455, 0.315])
    draw_grid(ax, equiv, counts, title="", vmax=vmax, fontsize=12, label_bbox=True)
    ax.scatter(
        passes["demand_percentile"] * 3,
        (1.0 - passes["antecedent_dryness_percentile"]) * 3,
        s=26,
        facecolor="#d62728",
        edgecolor="white",
        linewidth=0.5,
        alpha=0.85,
        zorder=5,
        label="one usable near-nadir pass (n = 219)",
    )
    ax.set_xlabel("Atmospheric demand — VPD percentile at acquisition time", fontsize=12)
    ax.set_ylabel(
        "Antecedent water balance percentile\n(30-day Σ(pr − eto); low = dry)",
        fontsize=12,
    )
    ax.set_title(
        "A · The stress-axis grid from the advisory review, rebuilt on the v2 sample",
        fontsize=13.5,
        fontweight="bold",
        loc="left",
        pad=9,
    )
    ax.legend(loc="upper left", fontsize=9.5, framealpha=0.92)
    fig.text(
        0.105,
        0.908,
        "Shading = how many usable satellite passes fall in each cell. Darker means MORE OBSERVATIONS, "
        "not more cooling.",
        fontsize=10.5,
        color="#4a148c",
        fontweight="bold",
    )

    # collapse corner predicted by the advisory review
    ax.add_patch(
        Rectangle(
            (2, 0), 1, 1, fill=False, edgecolor="#d62728", lw=3.0, zorder=6
        )
    )
    # the two identification corners
    for col, row in ((0, 0), (2, 2)):
        ax.add_patch(
            Rectangle(
                (col, row),
                1,
                1,
                fill=False,
                edgecolor="#ff7f0e",
                lw=2.4,
                linestyle=(0, (5, 3)),
                zorder=6,
            )
        )

    fig.text(
        0.105,
        0.508,
        "solid red   = corner where the review predicted the cooling collapse (high demand / low water)",
        fontsize=10.5,
        color="#d62728",
        fontweight="bold",
    )
    fig.text(
        0.105,
        0.488,
        "dashed orange = the two identification corners; without both, a collapse cannot be attributed "
        "to water rather than demand",
        fontsize=10.5,
        color="#c25a00",
        fontweight="bold",
    )

    cax = fig.add_axes([0.578, 0.590, 0.013, 0.255])
    cb = fig.colorbar(ax._im, cax=cax)
    cb.set_label(
        "SAMPLE SIZE — expected pass-equivalents\n(NOT cooling, NOT temperature)",
        fontsize=9.5,
        fontweight="bold",
    )

    # ---- Panel B: what the colour axis was supposed to be -------------------
    axb = fig.add_axes([0.665, 0.560, 0.300, 0.315])
    axb.axis("off")
    axb.add_patch(
        Rectangle(
            (0.02, 0.02),
            0.96,
            0.96,
            transform=axb.transAxes,
            facecolor="#f4f4f4",
            edgecolor="#999999",
            lw=1.4,
            hatch="///",
        )
    )
    axb.text(
        0.5,
        0.88,
        "B · The colour axis the review asked for",
        transform=axb.transAxes,
        ha="center",
        fontsize=13,
        fontweight="bold",
    )
    axb.text(
        0.5,
        0.60,
        "mean ΔT$_{cool}$ per cell\n\nNOT AVAILABLE",
        transform=axb.transAxes,
        ha="center",
        va="center",
        fontsize=17,
        color="#b00020",
        fontweight="bold",
        linespacing=1.5,
    )
    axb.text(
        0.5,
        0.28,
        "No ECOSTRESS LST value has been opened.\n"
        "Task 1 is STOP (R0015 demand×dryness; R0016 time-of-day),\n"
        "so no thermal outcome, holdout or 2026 record exists.\n\n"
        "Filling this panel would require exactly the\n"
        "analysis the frozen gates declined to authorise.",
        transform=axb.transAxes,
        ha="center",
        va="center",
        fontsize=10.5,
        color="#333333",
        linespacing=1.55,
    )

    # ---- Panel C: corner support against the frozen minimum ----------------
    axc = fig.add_axes([0.215, 0.335, 0.690, 0.115])
    corner_rows = [
        ("high demand / dry\n(predicted collapse corner)", equiv[0, 2], counts[0, 2], "#d62728"),
        ("high demand / wet\n(identification corner)", equiv[2, 2], counts[2, 2], "#ff7f0e"),
        ("low demand / dry\n(identification corner)", equiv[0, 0], counts[0, 0], "#ff7f0e"),
    ]
    ypos = np.arange(len(corner_rows))[::-1]
    for y, (label, value, n, colour) in zip(ypos, corner_rows, strict=True):
        axc.barh(y, value, height=0.55, color=colour, alpha=0.85)
        axc.text(
            value + 0.9,
            y,
            f"{value:.2f} pass-equivalents  ({int(n)} passes)",
            va="center",
            fontsize=11,
            fontweight="bold",
        )
    axc.axvline(MIN_CORNER, color="#111111", lw=2.0, linestyle="--")
    axc.annotate(
        "frozen minimum = 10",
        xy=(MIN_CORNER + 1.2, 2.62),
        ha="left",
        va="bottom",
        fontsize=10,
        fontweight="bold",
        annotation_clip=False,
    )
    axc.set_yticks(ypos)
    axc.set_yticklabels([r[0] for r in corner_rows], fontsize=10.5)
    axc.set_xlim(0, 82.0)
    axc.set_ylim(-0.55, 2.95)
    axc.set_xlabel("expected pass-equivalents", fontsize=11, labelpad=14)
    axc.set_title(
        "C · Why the surface cannot be estimated: the corner that would prove a water effect is empty",
        fontsize=13.5,
        fontweight="bold",
        loc="left",
        pad=10,
    )
    for spine in ("top", "right"):
        axc.spines[spine].set_visible(False)

    # ---- Panel D: per-city grids -------------------------------------------
    city_vmax = 0.0
    city_grids = {}
    for city, frame in passes.groupby("city"):
        ce = grid_matrix(frame, "sampling_weight")
        cc = grid_matrix(frame, "n")
        city_grids[city] = (ce, cc)
        city_vmax = max(city_vmax, ce.max())

    panel_w = (0.890 - 4 * 0.024) / 5
    for idx, city in enumerate(sorted(city_grids)):
        axd = fig.add_axes(
            [0.075 + idx * (panel_w + 0.024), 0.055, panel_w, 0.170]
        )
        ce, cc = city_grids[city]
        draw_grid(
            axd,
            ce,
            cc,
            title=f"{CITY_LABEL[city]}  ({int(cc.sum())} passes)",
            vmax=city_vmax,
            fontsize=8.5,
        )
        axd.add_patch(
            Rectangle((2, 0), 1, 1, fill=False, edgecolor="#d62728", lw=2.0, zorder=6)
        )
        if idx == 0:
            axd.set_ylabel("water balance", fontsize=9)
        else:
            axd.set_yticklabels([])
        axd.set_xlabel("demand", fontsize=9)
        axd.tick_params(labelsize=8)

    fig.text(
        0.075,
        0.972,
        "Demand × antecedent-water grid — real v2 sample, no thermal outcome",
        fontsize=18,
        fontweight="bold",
    )
    fig.text(
        0.075,
        0.950,
        "Five cities · summers 2018–2025 · 219 usable near-nadir passes · 159.09 cloud-weighted pass-equivalents · "
        "canonical run R0015",
        fontsize=11,
        color="#444444",
    )
    fig.text(
        0.075,
        0.929,
        "Axes and cell counts are canonical Step-2 output. The ΔT$_{cool}$ colour axis is unavailable: "
        "no LST value has been opened.",
        fontsize=10.5,
        color="#b00020",
        fontstyle="italic",
    )
    fig.text(
        0.075,
        0.243,
        "D · The same grid per city — every city's sample sits on the hot-and-dry diagonal",
        fontsize=13.5,
        fontweight="bold",
    )

    out_png = OUTDIR / "F_PROF.1_demand_water_support_grid.png"
    fig.savefig(out_png, dpi=200, facecolor="white")
    plt.close(fig)

    # ---- backing table ------------------------------------------------------
    rows = []
    for r, water in enumerate(WATER_ORDER):
        for c, demand in enumerate(DEMAND_ORDER):
            rows.append(
                {
                    "demand_tercile": demand,
                    "antecedent_water_tercile": water,
                    "condition_cell": f"demand_{demand}__antecedent_{water}",
                    "n_passes": int(counts[r, c]),
                    "expected_pass_equivalents": round(float(equiv[r, c]), 6),
                    "role": (
                        "predicted_collapse_corner"
                        if (demand, water) == ("high", "dry")
                        else "identification_corner"
                        if (demand, water) in {("high", "wet"), ("low", "dry")}
                        else "interior"
                    ),
                }
            )
    table = pd.DataFrame(rows)
    table.to_csv(OUTDIR / "T_PROF.1_demand_water_support.csv", index=False)

    print(f"wrote {out_png}")
    print(table.to_string(index=False))
    print(f"\ntotal passes {int(counts.sum())}  total equivalents {equiv.sum():.5f}")


if __name__ == "__main__":
    main()
