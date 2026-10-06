#!/usr/bin/env python3
"""Build the complete, outcome-blind v6.2 D1a demand--geometry package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D

from urban_cooling_v2.demand_geometry_audit import run_audit, write_analysis_json


DEFAULT_OUTPUT = Path("deliverables/D1a_demand_geometry_v6_2_20260830")
NODE = Path(
    "/Users/jmlee/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
)
NODE_MODULES = Path(
    "/Users/jmlee/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
)
BUNDLED_PYTHON = Path(
    "/Users/jmlee/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _draw_wrapped(canvas, text, x, y, width, font="Helvetica", size=9.0, leading=12.0):
    canvas.setFont(font, size)
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if stringWidth(candidate, font, size) <= width:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    for rendered in lines:
        canvas.drawString(x, y, rendered)
        y -= leading
    return y


def build_figure(result: dict, png_path: Path, svg_path: Path) -> None:
    plot = pd.DataFrame(result["plot_rows"])
    plot = plot.loc[plot["view_set_max_deg"] == 25].copy()
    condition = {
        row["city"]: row
        for row in result["condition_rows"]
        if row["view_set_max_deg"] == 25
    }
    city_labels = {"phoenix": "Phoenix", "los_angeles": "Los Angeles"}
    x_columns = ["solar_zenith_deg", "local_solar_time_hours", "day_of_year"]
    x_labels = ["Solar zenith (degrees)", "Local solar time (hours)", "Day of year"]

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
        }
    )
    fig, axes = plt.subplots(2, 3, figsize=(10.5, 7.2), constrained_layout=False)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.875, bottom=0.155, hspace=0.42, wspace=0.20)
    for row_index, city in enumerate(("phoenix", "los_angeles")):
        block = plot.loc[plot["city"] == city]
        primary = block["view_zenith_p95_deg"] <= 15.0
        metrics = condition[city]
        for column_index, (x_column, x_label) in enumerate(zip(x_columns, x_labels)):
            ax = axes[row_index, column_index]
            ax.scatter(
                block.loc[~primary, x_column],
                block.loc[~primary, "vpd_kpa"],
                s=24,
                color="#F59E0B",
                alpha=0.75,
                edgecolor="white",
                linewidth=0.35,
                zorder=3,
            )
            ax.scatter(
                block.loc[primary, x_column],
                block.loc[primary, "vpd_kpa"],
                s=28,
                color="#0F766E",
                alpha=0.85,
                edgecolor="white",
                linewidth=0.35,
                zorder=4,
            )
            if metrics["continuous_support_has_overlap"]:
                ax.axhspan(
                    metrics["continuous_support_low_kpa"],
                    metrics["continuous_support_high_kpa"],
                    color="#2563EB",
                    alpha=0.11,
                    zorder=1,
                )
            else:
                lower = metrics["continuous_support_intersection_lower_bound_kpa"]
                upper = metrics["continuous_support_intersection_upper_bound_kpa"]
                ax.axhspan(upper, lower, color="#DC2626", alpha=0.10, hatch="///", zorder=1)
                ax.text(
                    0.03,
                    0.96,
                    "No common VPD band",
                    transform=ax.transAxes,
                    ha="left",
                    va="top",
                    fontsize=8,
                    color="#991B1B",
                    weight="bold",
                )
            ax.grid(axis="y", color="#E5E7EB", linewidth=0.7, zorder=0)
            ax.set_xlabel(x_label)
            if column_index == 0:
                ax.set_ylabel(f"{city_labels[city]}\nExact-time VPD (kPa)")
            ax.set_title(f"n={len(block)}; common width={metrics['continuous_support_width_kpa']:.3f} kPa")

    legend = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#0F766E", label="Primary ≤15°", markersize=7),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#F59E0B", label="Added 15–25°", markersize=7),
        Line2D([0], [0], color="#2563EB", linewidth=8, alpha=0.18, label="Common VPD support"),
        Line2D([0], [0], color="#DC2626", linewidth=8, alpha=0.18, label="Support gap (no overlap)"),
    ]
    fig.legend(handles=legend, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 0.025))
    fig.suptitle(
        "D1a demand–geometry support (historical nonthermal evidence; binding 25° set)",
        fontsize=13,
        weight="bold",
    )
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(svg_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def build_memo(result: dict, path: Path) -> None:
    from reportlab.pdfgen import canvas

    binding = {row["city"]: row for row in result["binding_rows"]}
    phoenix = binding["phoenix"]
    los_angeles = binding["los_angeles"]
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "BodySmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.4, leading=10.7
    )
    table_header = ParagraphStyle(
        "TableHeader", parent=body, fontName="Helvetica-Bold", textColor=colors.white, alignment=TA_LEFT
    )
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    margin = 0.58 * inch

    def header(page_title: str, page_no: int) -> float:
        c.setFillColor(colors.HexColor("#0F172A"))
        c.rect(0, height - 0.56 * inch, width, 0.56 * inch, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 12.5)
        c.drawString(margin, height - 0.36 * inch, page_title)
        c.setFont("Helvetica", 8)
        c.drawRightString(width - margin, height - 0.36 * inch, f"v6.2 D1a | page {page_no} of 2")
        c.setFillColor(colors.HexColor("#0F172A"))
        return height - 0.82 * inch

    y = header("Demand–geometry support ruling", 1)
    c.setFillColor(colors.HexColor("#FEE2E2"))
    c.roundRect(margin, y - 0.76 * inch, width - 2 * margin, 0.68 * inch, 8, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#991B1B"))
    c.setFont("Helvetica-Bold", 20)
    c.drawString(margin + 0.18 * inch, y - 0.36 * inch, "DROP")
    c.setFont("Helvetica-Bold", 10.3)
    c.drawString(margin + 1.22 * inch, y - 0.27 * inch, "Drop both W_tree × VPD and W_bg × VPD")
    c.setFont("Helvetica", 8.8)
    c.drawString(margin + 1.22 * inch, y - 0.48 * inch, "Remove RQ2; report average daytime effects. This ruling is irreversible after coefficient access.")
    y -= 0.93 * inch

    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(margin, y, "Prospective decision rule")
    y -= 0.18 * inch
    y = _draw_wrapped(
        c,
        "Before these diagnostics were computed, V6.2-D002 required both Gate A cities to have at least 30 complete passes in the 25° candidate design, VPD VIF ≤5, maximum condition index ≤30, leave-one-pass-out nonlinear VPD concurvity R² ≤0.80, residual VPD SD ≥0.25 kPa, and continuously supported VPD width ≥0.50 kPa. Missing required geometry fails closed. Pairwise correlations are descriptive only.",
        margin,
        y,
        width - 2 * margin,
        size=8.7,
        leading=11.2,
    )
    y -= 0.08 * inch

    data = [
        [Paragraph("Binding criterion", table_header), Paragraph("Threshold", table_header), Paragraph("Phoenix", table_header), Paragraph("Los Angeles", table_header)],
        ["Complete full-design passes", "≥30", "0 / 44", "0 / 48"],
        ["VPD VIF", "≤5", "NE (85.05*)", "NE (72.57*)"],
        ["Maximum condition index", "≤30", "NE (37.09*)", "NE (47.80*)"],
        ["Nonlinear concurvity R²", "≤0.80", "NE (0.966*)", "NE (0.987*)"],
        ["Residual VPD SD (kPa)", "≥0.25", "NE (0.308*)", "NE (0.100*)"],
        ["Common VPD width (kPa)", "≥0.50", "2.522", "0.000"],
    ]
    table = Table(data, colWidths=[2.15 * inch, 0.9 * inch, 1.35 * inch, 1.45 * inch], rowHeights=0.29 * inch)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 8.2),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8FAFC")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    table.wrapOn(c, width - 2 * margin, height)
    table.drawOn(c, margin, y - 2.03 * inch)
    y -= 2.17 * inch
    c.setFont("Helvetica-Oblique", 7.7)
    c.setFillColor(colors.HexColor("#475569"))
    c.drawString(margin, y, "* Optimistic reduced-design value after omitting unavailable view and relative azimuth; nonbinding.")
    y -= 0.30 * inch

    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(margin, y, "Why the branch fails")
    y -= 0.19 * inch
    y = _draw_wrapped(
        c,
        y= y,
        text=(
            "Neither city has a single pass with the required view-azimuth and relative sun–sensor azimuth controls (0/44 Phoenix; 0/48 Los Angeles), so the full design cannot be estimated. Even the deliberately favorable reduced check exceeds the VIF, condition-index, and nonlinear-concurvity ceilings in both cities. Los Angeles also fails the residual-SD and continuous-support floors."
        ),
        x=margin,
        width=width - 2 * margin,
        size=8.7,
        leading=11.2,
    )
    c.setFont("Helvetica", 7.4)
    c.setFillColor(colors.HexColor("#64748B"))
    c.drawString(margin, 0.42 * inch, "No ECOSTRESS LST value or new v6.2 coefficient was opened for this ruling.")
    c.showPage()

    y = header("Identification, interpretation, and traceability", 2)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(margin, y, "Variation that would identify the interaction")
    y -= 0.20 * inch
    y = _draw_wrapped(
        c,
        "The VPD interaction would be identified by within-city, cross-pass variation in exact-time VPD that remains after conditioning on exact-time air temperature and actual vapour pressure/dewpoint, local solar time, solar zenith and azimuth, view zenith, relative sun–sensor azimuth, and day of year—and only within a VPD range continuously shared across those time, solar-geometry, viewing-geometry, and seasonal conditions. That independent variation is not demonstrated here.",
        margin,
        y,
        width - 2 * margin,
        size=8.8,
        leading=11.4,
    )
    y -= 0.15 * inch

    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(margin, y, "Supporting numbers")
    y -= 0.20 * inch
    bullet_texts = [
        "Historical nonthermal 25° support: 44 Phoenix passes and 48 Los Angeles passes; 15° sensitivity: 19 and 27.",
        "VPD–air-temperature Pearson r: 0.948 Phoenix and 0.953 Los Angeles. VPD–day-of-year r: −0.039 and 0.495. Correlations alone do not determine the ruling.",
        "Reduced nonlinear VPD predictability is 0.966 and 0.987 out of sample; the unexplained SD is 0.308 and 0.100 kPa.",
        "Common VPD support is 3.504–6.025 kPa in Phoenix (width 2.522); Los Angeles has no intersection (bounds cross at 1.653 versus 1.634 kPa; width 0).",
    ]
    for item in bullet_texts:
        c.setFillColor(colors.HexColor("#0F766E"))
        c.circle(margin + 3, y + 3, 1.6, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#0F172A"))
        y = _draw_wrapped(c, item, margin + 0.16 * inch, y + 6, width - 2 * margin - 0.16 * inch, size=8.5, leading=10.8)
        y -= 0.05 * inch
    y -= 0.08 * inch

    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(margin, y, "Decision and downstream consequence")
    y -= 0.20 * inch
    y = _draw_wrapped(
        c,
        "DROP the demand branch now. Both candidate interactions are removed together; RQ2 does not survive; high-demand p75 contrasts will not be reported; and later Stage 2 work is restricted to average daytime effects. The branch is not retained for publication appeal and cannot be restored after new coefficients are viewed.",
        margin,
        y,
        width - 2 * margin,
        size=8.8,
        leading=11.4,
    )
    y -= 0.18 * inch

    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(margin, y, "Scope and traceability")
    y -= 0.20 * inch
    y = _draw_wrapped(
        c,
        "Evidence is historical pass-level provenance, not the v6.2 study sample. Exact-time HRRR temperature and dewpoint were linearly interpolated from inherited bracketing-hour summaries; actual vapour pressure was computed from dewpoint. Solar coordinates were calculated at the frozen city centroids from local solar time and day of year. A geometry-only recovery read all 92 frozen passes from ECO_L1B_GEO.002 without opening LST: only 4/44 Phoenix and 1/48 Los Angeles passes had view and solar azimuth populated for every mapped view-valid cell. Partial arrays were not imputed or promoted to complete. Controlling sources: Deliverables Schedule p.3; Research Proposal pp.15–18; Working Guide pp.2–4, 7, 11–13. All input and output hashes are recorded in the package.",
        margin,
        y,
        width - 2 * margin,
        size=8.5,
        leading=10.9,
    )
    y -= 0.16 * inch
    c.setFillColor(colors.HexColor("#F1F5F9"))
    c.roundRect(margin, y - 0.58 * inch, width - 2 * margin, 0.52 * inch, 5, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#334155"))
    c.setFont("Helvetica-Bold", 8.4)
    c.drawString(margin + 0.12 * inch, y - 0.23 * inch, "Status: DROP | V6.2-D002 rule | geometry recovery reassessment | D003 unchanged")
    c.setFont("Helvetica", 7.8)
    c.drawString(margin + 0.12 * inch, y - 0.40 * inch, "Generated 2026-09-01 (Asia/Seoul). Historical evidence only; no thermal outcome access.")
    c.setFont("Helvetica", 7.4)
    c.setFillColor(colors.HexColor("#64748B"))
    c.drawString(margin, 0.42 * inch, "D1a demand–geometry support memo | memo.pdf")
    c.save()


def write_text_files(repo_root: Path, output: Path, result: dict, command: str) -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, text=True
    ).stdout.strip()
    inputs = [
        "D1a input evidence (historical nonthermal provenance; not the v6.2 study sample)",
        "No ECOSTRESS LST value or new v6.2 coefficient was opened.",
        "",
    ]
    for item in result["input_evidence"]:
        inputs.append(
            f"{item['name']}\t{item['path']}\tsha256={item['sha256']}\tbytes={item['bytes']}"
        )
    (output / "data" / "input_sources.txt").write_text("\n".join(inputs) + "\n", encoding="utf-8")
    (output / "code_commit.txt").write_text(
        "\n".join(
            [
                f"base_commit={head}",
                "analysis_code_status=UNCOMMITTED_PENDING_REVIEW",
                f"exact_command={command}",
                "outcome_access=NONE",
                "new_v6_2_coefficients_viewed=false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    binding = {row["city"]: row for row in result["binding_rows"]}
    if result["ruling"] == "DROP":
        interpretation = (
            "Both VPD interactions are dropped and RQ2 is removed. The full candidate "
            f"design has {binding['phoenix']['n_full_design_complete']} complete passes in "
            f"Phoenix and {binding['los_angeles']['n_full_design_complete']} in Los Angeles; "
            "reduced-design diagnostics are included only as an optimistic, nonbinding check."
        )
    else:
        interpretation = (
            "Both VPD interactions and RQ2 are retained under the prospectively frozen "
            "support limits because every binding criterion passed in both cities."
        )
    (output / "README.md").write_text(
        "# D1a demand–geometry support\n\n"
        f"Numerical ruling: **{result['ruling']}**. The package uses "
        "historical nonthermal pass evidence only and does not define the v6.2 study sample. "
        "See `memo.pdf` for the ruling and `analysis_manifest.json` for machine-readable traceability.\n\n"
        f"{interpretation}\n",
        encoding="utf-8",
    )


def write_checksums(output: Path) -> None:
    checksum_path = output / "checksums.txt"
    files = sorted(path for path in output.rglob("*") if path.is_file() and path != checksum_path)
    lines = [f"{_sha256(path)}  {path.relative_to(output)}" for path in files]
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else repo_root / args.output
    output.mkdir(parents=True, exist_ok=True)
    for child in ("data", "figures", "tables"):
        (output / child).mkdir(exist_ok=True)

    result = run_audit(repo_root)
    manifest = output / "analysis_manifest.json"
    write_analysis_json(result, manifest)
    build_figure(result, output / "figures" / "d1a_support.png", output / "figures" / "d1a_support.svg")
    subprocess.run(
        [
            str(BUNDLED_PYTHON),
            str(repo_root / "src" / "build_v6_2_d1a_memo.py"),
            str(manifest),
            str(output / "memo.pdf"),
        ],
        cwd=repo_root,
        check=True,
    )

    script = repo_root / "src" / "build_v6_2_d1a_tables.mjs"
    env = os.environ.copy()
    env["NODE_PATH"] = str(NODE_MODULES)
    subprocess.run(
        [
            str(NODE),
            str(script),
            str(manifest),
            str(output / "tables" / "d1a_pairwise.csv"),
            str(output / "tables" / "d1a_condition_index.csv"),
        ],
        cwd=repo_root,
        env=env,
        check=True,
    )

    command = (
        "XDG_CACHE_HOME=/private/tmp/d1a_cache MPLCONFIGDIR=/private/tmp/d1a_mpl PYTHONPATH=src "
        "/Users/jmlee/miniforge3/envs/urbanv2/bin/python "
        "src/run_v6_2_d1a_demand_geometry.py"
    )
    write_text_files(repo_root, output, result, command)
    write_checksums(output)
    print(json.dumps({"output": str(output), "ruling": result["ruling"]}, indent=2))
    return 0 if result["ruling"] in {"KEEP", "DROP"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
