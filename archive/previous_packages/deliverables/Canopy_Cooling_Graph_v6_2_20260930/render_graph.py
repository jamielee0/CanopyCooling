"""Visualize previously disclosed 2023 LST slopes; fit no new model."""
from pathlib import Path
import os
import json
import hashlib
from datetime import datetime, timezone

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/canopy-graph-matplotlib-20260930")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SOURCE = ROOT / "outputs/v6_2/scientific/exploratory_review_20260921/pass_gradients_exploratory.csv"
RELEASE = SOURCE.with_name("gradient_disclosure.json")
EXPECTED = {
    "phoenix": {27963, 28024, 28085, 28192, 28706, 28828, 28909, 28970, 29092, 29545, 29606},
    "atlanta": {27835, 27896, 27916, 28145, 28598},
}
COLORS = {"phoenix": "#C5652C", "atlanta": "#167D87"}


def cooling_for_increment(signed_gradient_per_10pp, increment_pp):
    # K and degrees C have identical difference units. Positive means cooler.
    return -np.asarray(signed_gradient_per_10pp) * np.asarray(increment_pp) / 10.0


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    # Known-answer checks guard the tenfold unit conversion and cooling sign.
    assert np.isclose(cooling_for_increment(-1.2, 1), 0.12)
    assert np.isclose(cooling_for_increment(-1.2, 10), 1.2)
    assert np.isclose(cooling_for_increment(0.4, 1), -0.04)
    assert cooling_for_increment(-1.2, 0) == 0
    assert np.median([1.0, 2.0, 8.0]) == 2.0
    frame = pd.read_csv(SOURCE)
    assert frame.pass_id.is_unique
    assert len(frame) == 16
    assert (frame.variant == "paired_primary").all()
    assert pd.to_datetime(frame.date).dt.year.eq(2023).all()
    for city, orbits in EXPECTED.items():
        assert set(frame.loc[frame.city.eq(city), "orbit"]) == orbits
    assert np.isfinite(frame.gradient_K_per_10pp).all()
    np.testing.assert_allclose(
        cooling_for_increment(frame.gradient_K_per_10pp, 10),
        frame.cooling_K_per_10pp,
        rtol=1e-12,
    )

    slopes = frame[["city", "orbit", "date", "solar_hour", "run_id",
                    "gradient_K_per_10pp", "cooling_K_per_10pp",
                    "cooling_q025_8km", "cooling_q975_8km"]].copy()
    slopes["cooling_C_per_1pp"] = cooling_for_increment(slopes.gradient_K_per_10pp, 1)
    slopes.to_csv(OUT / "pass_slopes.csv", index=False)

    increments = np.arange(11)
    summaries = {}
    rows = []
    for city in EXPECTED:
        q = slopes.loc[slopes.city.eq(city)]
        values = q.cooling_C_per_1pp.to_numpy()
        summaries[city] = {
            "passes": len(q), "median_cooling_C_per_1pp": float(np.median(values)),
            "min_pass_cooling_C_per_1pp": float(values.min()),
            "max_pass_cooling_C_per_1pp": float(values.max()),
        }
        for x in increments:
            rows.append({"city": city, "canopy_increase_percentage_points": int(x),
                         "median_pass_cooling_C": float(np.median(values) * x),
                         "minimum_pass_cooling_C": float(values.min() * x),
                         "maximum_pass_cooling_C": float(values.max() * x),
                         "number_of_passes": len(q)})
    pd.DataFrame(rows).to_csv(OUT / "cooling_by_increment.csv", index=False)

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": "#BCC2C6", "axes.labelcolor": "#263C44",
                         "xtick.color": "#40535B", "ytick.color": "#40535B",
                         "pdf.fonttype": 42})
    fig = plt.figure(figsize=(12, 8.6), facecolor="#FBFAF7")
    fig.text(.09, .943, "Canopy cover and estimated surface cooling",
             fontsize=23, fontweight="bold", color="#203A43")
    fig.text(.09, .902, "2023 pilot  |  11 Phoenix passes + 5 Atlanta passes  |  LST model",
             fontsize=12, color="#52636B")
    for x, city in [(.09, "phoenix"), (.54, "atlanta")]:
        s = summaries[city]
        fig.text(x, .840, f"{city.upper()}  ·  {s['passes']} PASSES", color=COLORS[city],
                 fontweight="bold", fontsize=11)
        fig.text(x, .803, f"{s['median_cooling_C_per_1pp']:.3f}°C per +1 percentage point",
                 color="#203A43", fontweight="bold", fontsize=16)
    ax = fig.add_axes([.09, .270, .86, .47], facecolor="#FBFAF7")
    for city in EXPECTED:
        s = summaries[city]
        color = COLORS[city]
        median = s["median_cooling_C_per_1pp"] * increments
        ax.fill_between(increments, s["min_pass_cooling_C_per_1pp"] * increments,
                        s["max_pass_cooling_C_per_1pp"] * increments,
                        color=color, alpha=.15, linewidth=0)
        ax.plot(increments, median, color=color, lw=2.8, marker="o", markersize=4,
                markerfacecolor=color, markeredgewidth=0)
        ax.annotate(f"{city.title()}\n{median[-1]:.2f}°C", (10, median[-1]),
                    xytext=(12, -4), textcoords="offset points", ha="left",
                    va="center", color=color, fontsize=12, fontweight="bold")
    ax.set(xlim=(0, 11.6), ylim=(0, 1.85), xticks=increments,
           xlabel="Increase in canopy cover (percentage points)",
           ylabel="Estimated surface cooling (°C)")
    ax.set_yticks(np.arange(0, 1.81, .3))
    ax.tick_params(length=0, pad=8)
    ax.grid(axis="y", color="#CCD3D5", alpha=.65, linewidth=.7)
    ax.set_axisbelow(True)
    ax.xaxis.labelpad = 12
    ax.yaxis.labelpad = 12
    fig.text(.09, .179, "Solid lines: median pass slope. Shading: minimum–maximum across passes, not confidence intervals.",
             fontsize=10.5, color="#40535B")
    fig.text(.09, .141, "+1 percentage point means, for example, 10% → 11% canopy cover. Positive values mean cooler surfaces.",
             fontsize=10.5, color="#40535B")
    fig.text(.09, .103, "Straight lines reflect the current linear model. The x-axis shows a change in cover, not total canopy cover.",
             fontsize=10.5, color="#40535B")
    fig.text(.09, .065, "Exploratory associations; dates and conditions differ. These are not forecasts of the effect of planting trees.",
             fontsize=10.5, color="#40535B")
    fig.savefig(OUT / "canopy_cooling_per_percentage_point.png", dpi=180, facecolor=fig.get_facecolor())
    fig.savefig(OUT / "canopy_cooling_per_percentage_point.pdf", facecolor=fig.get_facecolor())
    plt.close(fig)

    record = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "authorization": "User requested a graph of canopy percentage versus cooling benefit on 30 September 2026.",
        "scope": "Re-express previously disclosed LST slopes from the 11 Phoenix and 5 Atlanta 2023 passes.",
        "source": str(SOURCE.relative_to(ROOT)), "source_sha256": sha256(SOURCE),
        "prior_disclosure": str(RELEASE.relative_to(ROOT)), "prior_disclosure_sha256": sha256(RELEASE),
        "conversion": "cooling_C = -gradient_K_per_10pp * canopy_increase_percentage_points / 10",
        "aggregation": "Unweighted within-city median of the existing pass slopes, for descriptive illustration only.",
        "band": "Minimum to maximum pass slopes; not sampling uncertainty or a confidence interval.",
        "domain": "0 to 10 percentage-point differences; no absolute zero-canopy reference or 0–100% extrapolation.",
        "new_model_fit": False, "new_sealed_coefficients_opened": False,
        "thermal_rasters_opened": False, "time_contrasts_opened": False,
        "common_cell_or_registration_coefficients_opened": False,
        "scale_agreement_ruling": "pending; this is not the emitted-energy comparison",
        "historical_outputs_modified": False,
        "verification": "Known-answer sign/unit checks, exact +10pp source reconciliation, unique pass IDs and 2023 scope verified.",
    }
    (OUT / "disclosure.json").write_text(json.dumps(record, indent=2) + "\n")
    (OUT / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    print(json.dumps({"verification": "passed", "summary": summaries, "figure": str(OUT / "canopy_cooling_per_percentage_point.png")}, indent=2))


if __name__ == "__main__":
    main()
