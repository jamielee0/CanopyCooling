"""Sealed per-pass comparisons and a public precision-only overview."""
import json
import os
from pathlib import Path
import shutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

from .quadratic_sensitivity import sealed_path
from .run_quadratic_sensitivity import ROOT, RUN, EXEC, PACKET, public, sha, write


def draw_comparison(rows, hist, *, title):
    fig, axes = plt.subplots(2, 1, figsize=(9, 7), gridspec_kw={"height_ratios":[3, 1]}, constrained_layout=True)
    for model, color in (("linear", "#697586"), ("quadratic", "#007e87")):
        d = rows[rows.model.eq(model)].sort_values("canopy_fraction")
        x = d.canopy_fraction.to_numpy()*100
        axes[0].plot(x, d.point, color=color, label=model.capitalize(), lw=2)
        axes[0].fill_between(x, d.q025.to_numpy(), d.q975.to_numpy(), color=color, alpha=.18)
    axes[0].axhline(0, color="#999999", lw=.6)
    axes[0].set(title=title, ylabel="Canopy-associated surface cooling (K)", xlabel="Canopy cover (%)")
    axes[0].legend(frameon=False); axes[0].grid(alpha=.15)
    edges = np.asarray(hist["edges"])*100
    axes[1].bar(edges[:-1], hist["cells"], width=np.diff(edges), align="edge", color="#93b6a4")
    axes[1].axvspan(x.min(), x.max(), color="#007e87", alpha=.1)
    axes[1].set(xlabel="Canopy cover (%) — full original sample", ylabel="Native cells")
    axes[1].ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
    fig.supxlabel("Curves relative to city-specific lower reference; bands are pointwise spatial 95% intervals.\n"
                  "Conditional associations; no city ranking, time inference or causal planting interpretation.", fontsize=9)
    return fig


def render():
    os.umask(0o077)
    cfg = json.loads((EXEC/"execution_freeze.json").read_text())
    if sha(Path(__file__)) != cfg["code_sha256"]["src/v6_2_advance/plot_quadratic_sensitivity.py"]:
        raise ValueError("Frozen plotting code changed")
    records = []
    for spec in cfg["passes"]:
        key = f"{spec['city']}_{spec['orbit']}"
        source = sealed_path(ROOT, RUN, key+"_curves_SEALED.json")
        all_rows = pd.DataFrame(json.loads(source.read_text()))
        hist = json.loads(public(key+"_canopy_histogram.json").read_text())
        for size in (1, 8):
            rows = all_rows[all_rows.quantity.eq("temperature") & all_rows.group_km.eq(size)]
            if rows["point"].isna().any() or rows["q025"].isna().any():
                raise ValueError("Non-estimable curve requires explicit figure handling")
            fig = draw_comparison(rows, hist, title=f"{spec['city'].title()} · {spec['date']} · {size} km spatial groups")
            dest = sealed_path(ROOT, RUN, key+f"_{size}km_comparison_SEALED.png")
            if dest.exists(): raise ValueError("Preserve existing sealed figure")
            fig.savefig(dest, dpi=180); plt.close(fig); dest.chmod(0o600)
            # Machine checks only: no empirical effect image is opened for visual review.
            with Image.open(dest) as im:
                im.verify()
            with Image.open(dest) as im:
                pixels = np.asarray(im.convert("RGB"))
                nonblank = bool(pixels.std() > 5)
                shape = [im.width, im.height]
            if not nonblank: raise ValueError("Blank sealed image")
            records.append(dict(path=str(dest.relative_to(ROOT)), sha256=sha(dest), pixels=shape,
                                decodes=True, nonblank=True, visually_reviewed=False, effect_status="SEALED_USER_REQUEST"))
    p = pd.read_csv(public("precision.csv"))
    p = p[p.pair_id.eq("historical") & p.group_km.eq(8) & p.quantity.eq("temperature")]
    fig, axes = plt.subplots(1, 2, figsize=(12, 7), constrained_layout=True)
    labels = ["linear", "quadratic", "quadratic_minus_linear"]
    colors = ["#697586", "#007e87", "#c77a25"]
    for ax, city in zip(axes, ("phoenix", "atlanta")):
        d = p[p.city.eq(city)]; dates = sorted(d.date.unique()); y = np.arange(len(dates))
        for j, (label, color) in enumerate(zip(labels, colors)):
            values = d[d.model.eq(label)].set_index("date").loc[dates, "SE"].to_numpy()
            ax.barh(y+(j-1)*.24, values, height=.22, color=color, label=label.replace("_", " "))
        ax.set(yticks=y, yticklabels=dates, xlabel="Spatial bootstrap SE (K per +10pp canopy)", title=city.title())
        ax.invert_yaxis(); ax.grid(axis="x", alpha=.15)
    axes[0].legend(loc="lower right", fontsize=9, frameon=False)
    fig.suptitle("Step 5: precision only — new cooling estimates remain sealed", fontsize=15)
    fig.supxlabel("Historical 2.85%–12.85% canopy pair · 8 km whole-group resampling\n"
                  "Difference SE uses matched draws. Precision does not establish curvature or scale agreement.", fontsize=10)
    dest = public("historical_contrast_precision.png"); fig.savefig(dest, dpi=180); plt.close(fig)
    shutil.copy2(dest, PACKET/dest.name)
    write(EXEC/"figure_verification.json", dict(sealed_figures=records, public_figure=str(dest.relative_to(ROOT)),
                                               effect_visual_review="DEFERRED_UNDER_SEALING"))
    print(json.dumps(dict(sealed_figures=len(records), public_precision_figures=1, effect_values_displayed=False)), flush=True)


if __name__ == "__main__": render()
