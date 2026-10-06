"""Plot authorized observed bins and flexible LST curves, not raw coefficients."""
from pathlib import Path
import os
import json
import shutil
import numpy as np
import pandas as pd
os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/canopy-nonlinear-mpl-20260930")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "outputs/v6_2/scientific/nonlinear_association_20260930"
OUT = ROOT / "deliverables/Nonlinear_Canopy_Association_v6_2_20260930"
COLORS = {"phoenix": "#C5652C", "atlanta": "#167D87"}


def main():
    completion = json.loads((RUN / "completion.json").read_text())
    assert completion["fits"] == 16 and not completion["failures"]
    OUT.mkdir(parents=True, exist_ok=True)
    curves = pd.concat([pd.read_csv(p) for p in sorted(RUN.glob("*_curve.csv"))], ignore_index=True)
    bins = pd.concat([pd.read_csv(p) for p in sorted(RUN.glob("*_bins.csv"))], ignore_index=True)
    summary = curves.groupby(["city", "canopy_fraction"], as_index=False).agg(
        mean_cooling_C=("cooling_C", "mean"), minimum_pass_cooling_C=("cooling_C", "min"),
        maximum_pass_cooling_C=("cooling_C", "max"), mean_linear_cooling_C=("linear_cooling_C", "mean"),
        reference_canopy_fraction=("reference_canopy_fraction", "first"),
        contributing_passes=("orbit", "nunique"), minimum_spanning_blocks=("blocks_spanning_reference_and_target", "min"))
    points = bins.groupby(["city", "bin"], as_index=False).agg(
        mean_canopy=("mean_canopy", "mean"), mean_adjusted_cooling_C=("adjusted_cooling_C", "mean"),
        mean_observed_LST_minus_pass_mean_C=("observed_LST_minus_pass_mean_C", "mean"),
        minimum_raw_pass_C=("observed_LST_minus_pass_mean_C", "min"),
        maximum_raw_pass_C=("observed_LST_minus_pass_mean_C", "max"),
        cell_observations=("n_cells", "sum"), contributing_passes=("adjusted_cooling_C", "count"))
    for city, expected in [("phoenix", 11), ("atlanta", 5)]:
        assert summary.loc[summary.city.eq(city), "contributing_passes"].eq(expected).all()
        assert points.loc[points.city.eq(city), "contributing_passes"].eq(expected).all()
    summary.to_csv(OUT / "mean_adjusted_curves.csv", index=False)
    points.to_csv(OUT / "binned_observations.csv", index=False)
    curves.to_csv(OUT / "individual_pass_curves.csv", index=False)
    bins.to_csv(OUT / "individual_pass_bins.csv", index=False)
    increments = []
    for city in COLORS:
        q = summary.loc[summary.city.eq(city)].copy()
        integer = q[np.isclose(q.canopy_fraction*100, np.round(q.canopy_fraction*100), atol=1e-9)].copy()
        integer["canopy_percent"] = np.round(integer.canopy_fraction*100).astype(int)
        integer = integer.set_index("canopy_percent")
        for lower in integer.index:
            if lower+1 in integer.index:
                increments.append({"city": city, "from_canopy_percent": int(lower),
                                   "to_canopy_percent": int(lower+1),
                                   "mean_additional_cooling_C": float(integer.loc[lower+1, "mean_cooling_C"]-integer.loc[lower, "mean_cooling_C"])})
    pd.DataFrame(increments).to_csv(OUT / "cooling_for_each_additional_percentage_point.csv", index=False)

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": "#BAC5CA", "axes.labelcolor": "#263C44",
                         "xtick.color": "#40535B", "ytick.color": "#40535B", "pdf.fonttype": 42})
    fig, axes = plt.subplots(1, 2, figsize=(13, 8.2), facecolor="#FBFAF7")
    for ax, city in zip(axes, COLORS):
        q = summary.loc[summary.city.eq(city)]
        b = points.loc[points.city.eq(city)]
        color = COLORS[city]
        x = q.canopy_fraction.to_numpy()*100
        ref = q.reference_canopy_fraction.iloc[0]*100
        ax.set_facecolor("#FBFAF7")
        ax.fill_between(x, q.minimum_pass_cooling_C.to_numpy(), q.maximum_pass_cooling_C.to_numpy(), color=color, alpha=.13, linewidth=0)
        ax.plot(x, q.mean_linear_cooling_C, color="#718087", ls="--", lw=1.5)
        ax.plot(x, q.mean_cooling_C, color=color, lw=3)
        ax.scatter(b.mean_canopy*100, b.mean_adjusted_cooling_C, s=32,
                   edgecolor=color, facecolor="#FBFAF7", linewidth=1.2, zorder=4)
        ax.axhline(0, color="#9AA8AE", lw=.8)
        ax.set_title(f"{city.title()}  ·  {int(q.contributing_passes.iloc[0])} passes", loc="left",
                     fontweight="bold", fontsize=16, color=color, pad=14)
        ax.text(0, 1.005, f"Reference: {ref:.2f}% canopy", transform=ax.transAxes, fontsize=10, color="#52636B")
        ax.set_xlabel("Canopy cover (%)", labelpad=10)
        ax.set_ylabel("Estimated surface cooling\nrelative to reference canopy (°C)", labelpad=10)
        ax.grid(axis="y", alpha=.2)
        ax.set_axisbelow(True)
        ax.tick_params(length=0, pad=7)
        ax.margins(x=.025)
    fig.suptitle("Canopy cooling, allowing the association to curve", x=.08, y=.955,
                 ha="left", fontsize=22, fontweight="bold", color="#203A43")
    fig.text(.08, .895, "Existing 2023 observations · Original neighborhood and land-cover controls · Exploratory check",
             fontsize=12, color="#52636B")
    legend = [Line2D([0], [0], color="#40535B", lw=2.7, label="Flexible fit: mean across passes"),
              Line2D([0], [0], color="#40535B", marker="o", markerfacecolor="#FBFAF7", ls="", label="Adjusted observations in bins"),
              Line2D([0], [0], color="#718087", ls="--", label="Earlier linear fit"),
              Patch(facecolor="#40535B", alpha=.13, label="Range across passes")]
    fig.legend(handles=legend, loc="lower center", bbox_to_anchor=(.5, .192), ncol=2,
               frameon=False, fontsize=10.5)
    fig.text(.08, .151, "Positive = cooler. Each city's curve starts at its own reference; canopy ranges differ substantially.", fontsize=10.5, color="#40535B")
    fig.text(.08, .108, "Shading shows pass-to-pass variation, not confidence intervals. Dots have block/context adjustment.", fontsize=10.5, color="#40535B")
    fig.text(.08, .065, "The flexible curve is still an estimate. Dates, weather and spatial confounding limit causal interpretation.", fontsize=10.5, color="#40535B")
    fig.subplots_adjust(left=.08, right=.97, top=.81, bottom=.34, wspace=.30)
    fig.savefig(OUT / "adjusted_nonlinear_association.png", dpi=180, facecolor=fig.get_facecolor())
    fig.savefig(OUT / "adjusted_nonlinear_association.pdf", facecolor=fig.get_facecolor())
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(13, 7), facecolor="#FBFAF7")
    for ax, city in zip(axes, COLORS):
        b = points.loc[points.city.eq(city)]
        color = COLORS[city]
        x = b.mean_canopy.to_numpy()*100
        ax.set_facecolor("#FBFAF7")
        ax.fill_between(x, b.minimum_raw_pass_C.to_numpy(), b.maximum_raw_pass_C.to_numpy(), color=color, alpha=.14, linewidth=0)
        ax.plot(x, b.mean_observed_LST_minus_pass_mean_C, marker="o", markersize=4.5, color=color, lw=1.8)
        ax.axhline(0, color="#9AA8AE", lw=.8)
        ax.set_title(city.title(), loc="left", color=color, fontsize=16, fontweight="bold")
        ax.set_xlabel("Canopy cover (%)", labelpad=10)
        ax.set_ylabel("Observed surface temperature\nrelative to each pass's mean (°C)", labelpad=10)
        ax.grid(axis="y", alpha=.2)
        ax.set_axisbelow(True)
        ax.tick_params(length=0, pad=7)
    fig.suptitle("What the observed cell temperatures look like", x=.08, y=.95,
                 ha="left", fontsize=22, fontweight="bold", color="#203A43")
    fig.text(.08, .881, "Canopy-bin averages from actual 2023 observations · Equal weight to each pass · No curve fitted here",
             fontsize=11.5, color="#52636B")
    fig.text(.08, .146, "Lower values = cooler than that pass's average. Points are connected to help follow the bins.", fontsize=10.5, color="#40535B")
    fig.text(.08, .097, "Only pass-wide temperature offsets are removed; neighborhood and land-cover differences remain.", fontsize=10.5, color="#40535B")
    fig.text(.08, .048, "Shading: range across passes, not confidence intervals. This descriptive pattern is not a causal planting effect.", fontsize=10.5, color="#40535B")
    fig.subplots_adjust(left=.08, right=.97, top=.78, bottom=.27, wspace=.30)
    fig.savefig(OUT / "observed_binned_association.png", dpi=180, facecolor=fig.get_facecolor())
    fig.savefig(OUT / "observed_binned_association.pdf", facecolor=fig.get_facecolor())
    plt.close(fig)
    shutil.copy2(RUN / "fit_diagnostics.csv", OUT / "fit_diagnostics.csv")
    findings = {}
    for city in COLORS:
        q = summary.loc[summary.city.eq(city)].sort_values("canopy_fraction")
        findings[city] = {"reference_canopy_percent": float(q.canopy_fraction.iloc[0]*100),
                          "upper_canopy_percent": float(q.canopy_fraction.iloc[-1]*100),
                          "mean_cooling_at_upper_C": float(q.mean_cooling_C.iloc[-1]),
                          "linear_cooling_at_upper_C": float(q.mean_linear_cooling_C.iloc[-1]),
                          "maximum_absolute_curve_linear_difference_C": float((q.mean_cooling_C-q.mean_linear_cooling_C).abs().max()),
                          "minimum_blocks_spanning_reference_and_target": int(q.minimum_spanning_blocks.min())}
    (OUT / "summary.json").write_text(json.dumps(findings, indent=2) + "\n")
    print(json.dumps(findings, indent=2))


if __name__ == "__main__":
    main()
