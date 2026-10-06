"""Nonthermal public support plots and private sealed comparison figures."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from urban_cooling_v2.v6_2_output_boundary import guarded_output_path

COLORS = {6: "#2878b5", 7: "#d77d00", 8: "#9b4f96", 9: "#25856d"}


def configure():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})


def save(root, run, role, name, fig):
    paths = []
    for extension in ("png", "pdf"):
        path = guarded_output_path(root, role, f"{run}/{name}.{extension}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if role=="sealed": path.parent.chmod(0o700)
        fig.savefig(path, dpi=180)
        if role=="sealed": path.chmod(0o600)
        paths.append(path)
    plt.close(fig)
    return paths


def plot_public_support(root, run, phoenix, support, cdfs, union_xy, common_xy):
    configure()
    fig, axes = plt.subplots(1, 2, figsize=(12, 6), sharex=True, sharey=True)
    for ax, title in zip(axes, ("Union of the eleven original footprints", "Common cells retained across all eleven")):
        ax.scatter(union_xy[:, 0]/1000, union_xy[:, 1]/1000, s=.3, marker="s", c="#c7cdd5", linewidths=0, rasterized=True)
        if ax==axes[1]: ax.scatter(common_xy[:, 0]/1000, common_xy[:, 1]/1000, s=.4, marker="s", c="#25856d", linewidths=0, rasterized=True)
        ax.set_title(title, loc="left", fontsize=11)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel("UTM easting (km)")
    axes[0].set_ylabel("UTM northing (km)")
    fig.suptitle("Phoenix 2023 · exact native-cell footprint", x=.07, ha="left", fontsize=17, weight="bold")
    fig.text(.07, .040, f"Gray: union ({len(union_xy):,} unique cells). Green: all-eleven intersection ({len(common_xy):,} cells; {len(common_xy)*.0049:,.3f} km²).", fontsize=10)
    fig.text(.07, .014, "Cell-centre display in EPSG:32612; no basemap or interpolated thermal layer. Whole footprints are not city-clipped areas.", fontsize=9, color="#475467")
    fig.subplots_adjust(left=.07, right=.98, top=.86, bottom=.16, wspace=.18)
    save(root, run, "scientific", "common_footprint_predictor_map", fig)
    q = sorted([r for r in support if r["city"]=="phoenix"], key=lambda r: r["date"])
    fig, ax = plt.subplots(figsize=(10.4, 6.1))
    y = np.arange(len(q))
    values = np.array([r["common_all11_retained_fraction"] for r in q])
    ax.barh(y, values, color=[COLORS[int(r["date"][5:7])] for r in q], height=.65)
    for i, r in enumerate(q): ax.text(values[i]+.008, i, f"{values[i]:.1%} · {r['original_cells']:,} original cells", va="center", fontsize=9)
    ax.set_yticks(y, [r["date"] for r in q]); ax.invert_yaxis()
    ax.set_xlim(0, .86); ax.set_xticks(np.arange(0, .81, .1)); ax.set_xticklabels([f"{x:.0%}" for x in np.arange(0, .81, .1)])
    ax.set_xlabel("Fraction of each original pass retained in the all-eleven common footprint")
    ax.grid(axis="x", alpha=.18); ax.set_axisbelow(True)
    ax.set_title("Phoenix 2023 · retained geography", loc="left", fontsize=17, weight="bold", pad=16)
    fig.text(.16, .025, "The same 196,090 cells remain in every pass. This is a population/coverage sensitivity, not a replacement inclusion gate.", fontsize=9, color="#475467")
    fig.subplots_adjust(left=.16, right=.98, top=.86, bottom=.14)
    save(root, run, "scientific", "common_footprint_retention", fig)
    variables = ("canopy_fraction", "impervious_fraction", "low_vegetation_fraction", "bare_fraction", "building_fraction", "elevation", "distance_to_water")
    fig, axes = plt.subplots(3, 3, figsize=(13, 9.1))
    for ax, variable in zip(axes.flat, variables):
        records = [r for r in cdfs if r["variable"]==variable]
        retained = next(r for r in records if r["population"]=="retained_all11")
        for r in records:
            if r["population"]=="excluded_from_all11":
                ax.plot(r["quantiles"], r["probabilities"], color=COLORS[int(r["date"][5:7])], alpha=.55, linewidth=.9)
        ax.plot(retained["quantiles"], retained["probabilities"], color="#172b4d", lw=2, label="Retained common cells")
        ax.set_title(variable.replace("_", " ").capitalize(), loc="left", fontsize=11)
        ax.set_xlabel("m" if variable in ("elevation", "distance_to_water") else "Fraction")
        ax.set_ylabel("Cumulative cell fraction"); ax.set_ylim(0, 1); ax.grid(alpha=.15)
        if variable not in ("elevation", "distance_to_water"): ax.set_xlim(0, 1)
    for ax in list(axes.flat)[7:]: ax.axis("off")
    handles = [Line2D([0], [0], color="#172b4d", lw=2, label="Retained: identical predictor values in all 11 passes")]
    handles += [Line2D([0], [0], color=c, lw=1.4, label=f"Excluded cells · {month}") for month, c in (("June", COLORS[6]), ("July", COLORS[7]), ("August", COLORS[8]), ("September", COLORS[9]))]
    axes.flat[7].legend(handles=handles, loc="upper left", frameon=False, fontsize=9)
    axes.flat[8].text(0, .85, "Nonthermal support only\n\nEach excluded curve represents one pass.\nNo canopy replacement cutoff.\n\nFull distributions and original-population\nquantiles are preserved in the table.", va="top", fontsize=10, color="#475467")
    fig.suptitle("Phoenix · retained versus excluded predictor distributions", x=.06, ha="left", fontsize=17, weight="bold")
    fig.text(.06, .018, "Cell-weighted empirical CDFs sampled at 201 quantiles; all source observations enter summaries. The graph does not show cooling effects.", fontsize=9, color="#475467")
    fig.subplots_adjust(left=.06, right=.98, top=.91, bottom=.09, hspace=.58, wspace=.38)
    save(root, run, "scientific", "retained_excluded_predictor_distributions", fig)


def plot_sealed_reviews(root, run, common, fixed, available, scales, references):
    configure()
    files = []
    q1 = sorted([r for r in common if r["group_km"]==1], key=lambda r: r["date"])
    q8 = {r["orbit"]: r for r in common if r["group_km"]==8}
    fig, axes = plt.subplots(3, 1, figsize=(11.7, 11), sharex=True)
    x = np.arange(len(q1))
    for offset, key, label, color in ((-.1, "original", "Original support", "#2878b5"), (.1, "common", "All-eleven common support", "#25856d")):
        point = np.array([r[key]["point"][0] for r in q1])
        low = np.array([r[key]["q025"][0] for r in q1]); high = np.array([r[key]["q975"][0] for r in q1])
        axes[0].vlines(x+offset, low, high, color=color, lw=1.5); axes[0].scatter(x+offset, point, color=color, s=36, label=label)
    axes[0].legend(frameon=False, ncol=2); axes[0].set_ylabel("Cooling (K/+10pp)")
    axes[0].set_title("Unchanged mean models; new joint 1km draw marginals", loc="left", fontsize=11)
    for ax, size in zip(axes[1:], (1, 8)):
        records = q1 if size==1 else [q8[r["orbit"]] for r in q1]
        ax.axhline(0, color="#667085", lw=.8)
        for i, r in enumerate(records):
            s = r["common_minus_original"]
            if s["status"]!="ESTIMABLE": continue
            ax.vlines(i, s["q025"][0], s["q975"][0], color="#9b4f96", lw=1.5); ax.scatter(i, s["point"][0], color="#9b4f96", s=36)
        ax.set_title(f"Common − original · paired {size}km groups", loc="left", fontsize=11)
        ax.set_ylabel("Cooling change (K/+10pp)")
    for ax in axes: ax.grid(axis="y", alpha=.18)
    axes[-1].set_xticks(x, [r["date"][5:] for r in q1]); axes[-1].set_xlabel("Phoenix acquisition date in 2023")
    fig.suptitle("SEALED · common-footprint cooling and paired changes", x=.085, ha="left", fontsize=17, weight="bold")
    fig.text(.085, .025, "95% percentile spatial intervals. No robustness cutoff, time model or practical-agreement ruling.", fontsize=10)
    fig.subplots_adjust(left=.085, right=.985, top=.91, bottom=.095, hspace=.34)
    files += save(root, run, "sealed", "common_footprint_cooling_SEALED", fig)
    fixed = sorted(fixed, key=lambda r: (r["date"], r["variant"]))
    fig, ax = plt.subplots(figsize=(10.6, 9))
    for i, r in enumerate(fixed):
        ax.hlines(i, r["q025"][0], r["q975"][0], color=COLORS[int(r["date"][5:7])], lw=1.5)
        ax.scatter(r["point"][0], i, color=COLORS[int(r["date"][5:7])], s=30)
    ax.axvline(0, color="#667085", lw=.8); ax.invert_yaxis()
    ax.set_yticks(np.arange(len(fixed)), [r["date"][5:]+" · "+r["variant"].split("support_")[1] for r in fixed], fontsize=8)
    ax.set_xlabel("Shifted − unshifted cooling on identical cells (K/+10pp canopy)"); ax.grid(axis="x", alpha=.16)
    ax.set_title("SEALED · fixed-support registration differences", loc="left", fontsize=17, weight="bold", pad=20)
    fig.text(.21, .027, "24 comparisons · existing paired whole-block percentile intervals · no acceptance threshold", fontsize=9)
    fig.subplots_adjust(left=.21, right=.98, top=.9, bottom=.095)
    files += save(root, run, "sealed", "registration_fixed_support_SEALED", fig)
    fig, axes = plt.subplots(1, 2, figsize=(13, 9.8), sharex=True)
    for ax, added in zip(axes, (False, True)):
        records = sorted([r for r in available if ("extension" in r["source_run_id"])==added], key=lambda r: (r["date"], r["variant"]))
        for i, r in enumerate(records): ax.scatter(r["shifted_minus_original"][0], i, color=COLORS[int(r["date"][5:7])], s=32)
        ax.axvline(0, color="#667085", lw=.8); ax.invert_yaxis()
        ax.set_yticks(np.arange(len(records)), [r["date"][5:]+" · "+r["variant"].split("registration_")[1] for r in records], fontsize=8)
        ax.set_title("Six added passes" if added else "Five original passes", loc="left", fontsize=12)
        ax.set_xlabel("Shifted − original cooling (K/+10pp)"); ax.grid(axis="x", alpha=.16)
    fig.suptitle("SEALED · available-support registration point changes", x=.12, ha="left", fontsize=17, weight="bold")
    fig.text(.12, .025, "Changing alignment can change the retained population. Difference intervals are unavailable; separate constituent intervals remain in the sealed table.", fontsize=9)
    fig.subplots_adjust(left=.12, right=.985, top=.92, bottom=.1, wspace=.37)
    files += save(root, run, "sealed", "registration_available_support_SEALED", fig)
    fig, axes = plt.subplots(2, 2, figsize=(12, 9.8))
    for column, city in enumerate(("phoenix", "atlanta")):
        for row, size in enumerate((1, 8)):
            ax = axes[row, column]
            records = [r for r in scales if r["city"]==city and r["group_km"]==size and r["status"]=="ESTIMABLE"]
            for r in records:
                a, b = r["point"]
                color = COLORS[int(r["date"][5:7])]
                ax.hlines(b, r["q025"][0], r["q975"][0], color=color, lw=1)
                ax.vlines(a, r["q025"][1], r["q975"][1], color=color, lw=1)
                ax.scatter(a, b, c=color, s=35)
                ax.annotate(r["date"][5:], (a, b), xytext=(4, 5), textcoords="offset points", fontsize=8)
            if records:
                low = min(min(r["q025"]) for r in records); high = max(max(r["q975"]) for r in records)
                margin = .08*(high-low)
                ax.plot([low-margin, high+margin], [low-margin, high+margin], color="#667085", ls="--", lw=.8)
                ax.set_xlim(low-margin, high+margin); ax.set_ylim(low-margin, high+margin)
            ax.set_title(f"{city.title()} · {size}km spatial groups", loc="left", fontsize=11)
            ax.set_xlabel("Temperature cooling (K/+10pp)"); ax.set_ylabel("Reference-equivalent flux cooling (K/+10pp)")
            ax.grid(alpha=.16)
    fig.suptitle("SEALED · paired temperature and fixed-reference flux diagnostics", x=.08, ha="left", fontsize=16, weight="bold")
    fig.text(.08, .024, "Marginal 95% intervals; paired draws also supply difference intervals in the sealed table. Same retrievals, no independent validation or scale ruling.", fontsize=9)
    fig.subplots_adjust(left=.08, right=.98, top=.91, bottom=.1, wspace=.33, hspace=.34)
    files += save(root, run, "sealed", "paired_scale_diagnostic_SEALED", fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.8))
    for ax, city in zip(axes, ("phoenix", "atlanta")):
        records = sorted([r for r in references if r["city"]==city and r["status"]=="ESTIMABLE"], key=lambda r: (r["date"], r["temperature_offset_K"], r["emissivity_offset"]))
        dates = sorted({r["date"] for r in records})
        for i, date in enumerate(dates):
            q = [r for r in records if r["date"]==date]
            values = [r["point"][1] for r in q]
            ax.vlines(i, min(values), max(values), color=COLORS[int(date[5:7])], lw=3)
            central = next(r for r in q if r["temperature_offset_K"]==r["emissivity_offset"]==0)
            ax.scatter(i, central["point"][1], color="#172b4d", s=32)
        ax.set_xticks(np.arange(len(dates)), [date[5:] for date in dates], rotation=45, ha="right", fontsize=8)
        ax.set_title(city.title(), loc="left", fontsize=12); ax.set_ylabel("Reference-equivalent cooling (K/+10pp)"); ax.grid(axis="y", alpha=.16)
    fig.suptitle("SEALED · fixed-reference sensitivity", x=.08, ha="left", fontsize=17, weight="bold")
    fig.text(.08, .024, "Range over Tref ±10K and emissivity ±0.01 (capped at 0.999); dark point: central reference. Reference dependence, not an agreement ruling.", fontsize=9)
    fig.subplots_adjust(left=.08, right=.98, top=.86, bottom=.18, wspace=.3)
    files += save(root, run, "sealed", "reference_sensitivity_SEALED", fig)
    # Metadata-only QA avoids displaying sealed effect pixels through a tool.
    from PIL import Image
    metadata = []
    for p in files:
        if p.suffix==".png":
            with Image.open(p) as im:
                a = np.asarray(im.convert("RGB"))
                if not np.any(a < 240): raise ValueError("Blank sealed figure")
                metadata.append(dict(file=p.name, pixels=list(im.size), nonblank=True, visually_inspected=False, permissions=oct(p.stat().st_mode & 0o777)))
    path = guarded_output_path(root, "scientific", f"{run}/sealed_figure_qa_metadata.json")
    path.write_text(json.dumps(dict(status="metadata/nonblank checks only; visual review deferred until authorized display", figures=metadata), indent=2)+"\n")
