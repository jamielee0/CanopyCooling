#!/usr/bin/env python3
"""Window-length robustness of the condition-support grid: 30-day vs 60-day antecedent balance.

The guide's Step 1 check "window length does not decide the answer" was run at the daily
level. This runs the same check on the definitive 219-pass sample, which is what the
count-support gate actually depends on.

Both windows are already on disk, so this opens no new data and no thermal value.

Inputs : canonical R0015 pass template + Step-1 condition axes (both windows)
Outputs: F_PROF.2 comparison PNG + backing CSV
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
AXES = PROJECT / "data/processed/v2/step1_condition_axes.csv"
OUTDIR = PROJECT / "figures/v2/prof_spec_support_grid"
OUTDIR.mkdir(parents=True, exist_ok=True)

DEMAND_ORDER = ["low", "middle", "high"]
WATER_ORDER = ["dry", "middle", "wet"]  # bottom row = dry
MIN_CORNER = 10.0


def load() -> pd.DataFrame:
    template = pd.read_csv(BASE / "step3_empirical_template.csv")
    axes = pd.read_csv(AXES)
    template["_d"] = pd.to_datetime(template["local_solar_date"]).dt.date
    axes["_d"] = pd.to_datetime(axes["date"]).dt.date
    merged = template.merge(
        axes[["city", "_d", "antecedent_dryness_30d_pct", "antecedent_dryness_60d_pct"]],
        on=["city", "_d"],
        how="left",
        validate="many_to_one",
    )
    if merged["antecedent_dryness_60d_pct"].isna().any():
        raise ValueError("Every retained pass must join a Step-1 condition row")
    # The template's frozen water axis must be the 30-day column, or the swap is not like-for-like.
    delta = (
        merged["antecedent_dryness_percentile"] - merged["antecedent_dryness_30d_pct"]
    ).abs().max()
    if delta > 1e-12:
        raise ValueError(f"Template water axis is not the 30-day column (max delta {delta})")
    return merged


def grids(frame: pd.DataFrame, dryness_col: str) -> tuple[np.ndarray, np.ndarray]:
    cells = condition_cell(frame["demand_percentile"], frame[dryness_col]).to_numpy()
    demand = [c.split("__")[0].replace("demand_", "") for c in cells]
    water = [c.split("__")[1].replace("antecedent_", "") for c in cells]
    work = frame.assign(_demand=demand, _water=water)
    equiv = np.zeros((3, 3))
    counts = np.zeros((3, 3))
    for r, w in enumerate(WATER_ORDER):
        for c, d in enumerate(DEMAND_ORDER):
            sel = work[(work["_water"] == w) & (work["_demand"] == d)]
            equiv[r, c] = sel["sampling_weight"].sum()
            counts[r, c] = len(sel)
    return equiv, counts


def draw(ax, equiv, counts, title, vmax):
    im = ax.imshow(
        equiv, origin="lower", cmap="Purples", vmin=0, vmax=vmax,
        extent=(0, 3, 0, 3), aspect="auto",
    )
    for r in range(3):
        for c in range(3):
            ax.text(c + 0.5, r + 0.60, f"{int(counts[r, c])} passes", ha="center",
                    va="center", fontsize=10.5, fontweight="bold", color="#1a1a1a",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.6))
            ax.text(c + 0.5, r + 0.34, f"{equiv[r, c]:.2f} eq.", ha="center",
                    va="center", fontsize=9.5, color="#1a1a1a",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.6))
    for edge in (1, 2):
        ax.axvline(edge, color="white", lw=1.2)
        ax.axhline(edge, color="white", lw=1.2)
    ax.add_patch(Rectangle((2, 0), 1, 1, fill=False, edgecolor="#d62728", lw=2.6, zorder=6))
    for col, row in ((0, 0), (2, 2)):
        ax.add_patch(Rectangle((col, row), 1, 1, fill=False, edgecolor="#ff7f0e",
                               lw=2.2, linestyle=(0, (5, 3)), zorder=6))
    ax.set_xticks([0.5, 1.5, 2.5])
    ax.set_xticklabels(["low", "middle", "high"])
    ax.set_yticks([0.5, 1.5, 2.5])
    ax.set_yticklabels(["dry", "middle", "wet"])
    ax.set_xlabel("Atmospheric demand — VPD percentile at acquisition", fontsize=10.5)
    ax.set_title(title, fontsize=13, fontweight="bold", loc="left", pad=8)
    return im


def main() -> None:
    data = load()
    e30, c30 = grids(data, "antecedent_dryness_30d_pct")
    e60, c60 = grids(data, "antecedent_dryness_60d_pct")
    vmax = float(max(e30.max(), e60.max()))

    corners = [
        ("high demand / dry (predicted collapse)", (0, 2)),
        ("high demand / wet (identification)", (2, 2)),
        ("low demand / dry (identification)", (0, 0)),
    ]

    fig = plt.figure(figsize=(13.4, 7.3))
    axa = fig.add_axes([0.075, 0.330, 0.375, 0.455])
    axb = fig.add_axes([0.520, 0.330, 0.375, 0.455])
    im = draw(axa, e30, c30, "A · 30-day antecedent window (frozen)", vmax)
    draw(axb, e60, c60, "B · 60-day antecedent window", vmax)
    axa.set_ylabel("Antecedent water balance percentile\n(low = dry)", fontsize=10.5)
    axb.set_yticklabels([])

    cax = fig.add_axes([0.912, 0.330, 0.013, 0.455])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label("SAMPLE SIZE — expected pass-equivalents\n(NOT cooling)", fontsize=9,
                 fontweight="bold")

    fig.text(0.075, 0.930, "Does the empty corner depend on the window length?", fontsize=17,
             fontweight="bold")
    fig.text(0.075, 0.895,
             "Same 219 definitive passes, same demand axis, only the antecedent water window "
             "changes. Both windows were frozen before any result was opened.",
             fontsize=10.5, color="#444444")

    rows = []
    y = 0.225
    fig.text(0.075, y, "Condition cell", fontsize=10.5, fontweight="bold")
    fig.text(0.470, y, "30-day", fontsize=10.5, fontweight="bold")
    fig.text(0.590, y, "60-day", fontsize=10.5, fontweight="bold")
    fig.text(0.710, y, "Gate minimum = 10", fontsize=10.5, fontweight="bold")
    for label, (r, c) in corners:
        y -= 0.050
        v30, v60 = e30[r, c], e60[r, c]
        colour = "#d62728" if "collapse" in label else "#c25a00"
        verdict = "clears" if min(v30, v60) >= MIN_CORNER else "fails under both windows"
        fig.text(0.075, y, label, fontsize=10.5, color=colour, fontweight="bold")
        fig.text(0.470, y, f"{v30:.2f}", fontsize=10.5)
        fig.text(0.590, y, f"{v60:.2f}", fontsize=10.5)
        fig.text(0.710, y, verdict, fontsize=10.5,
                 color="#1a1a1a" if verdict == "clears" else "#b00020")
        rows.append({
            "condition_cell": label,
            "expected_pass_equivalents_30d": round(float(v30), 6),
            "expected_pass_equivalents_60d": round(float(v60), 6),
            "n_passes_30d": int(c30[r, c]),
            "n_passes_60d": int(c60[r, c]),
            "gate_minimum": MIN_CORNER,
        })

    fig.text(0.075, 0.020,
             "The low-demand / dry corner stays far below the gate minimum under both windows, "
             "so the Step-2 STOP is not an artefact of the 30-day choice.",
             fontsize=10.5, color="#b00020", fontweight="bold")

    out = OUTDIR / "F_PROF.2_window_length_support_check.png"
    fig.savefig(out, dpi=200, facecolor="white")
    plt.close(fig)
    pd.DataFrame(rows).to_csv(OUTDIR / "T_PROF.2_window_length_support.csv", index=False)

    print(f"wrote {out}")
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\ntotals  30d {e30.sum():.3f}   60d {e60.sum():.3f}")


if __name__ == "__main__":
    main()
