#!/usr/bin/env python3
"""Create the compact v6.2 D1c HLS-Fmask reassessment memo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


INK = colors.HexColor("#183642")
BLUE = colors.HexColor("#277DA1")
PALE_BLUE = colors.HexColor("#EAF4F8")
GREEN = colors.HexColor("#2D6A4F")
PALE_GREEN = colors.HexColor("#EAF6EF")
RED = colors.HexColor("#B23A48")
PALE_RED = colors.HexColor("#FBEDEF")
AMBER = colors.HexColor("#B36B00")
PALE_AMBER = colors.HexColor("#FFF4DE")
MID = colors.HexColor("#58727D")
GRID = colors.HexColor("#CBD8DD")


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(GRID)
    canvas.line(0.45 * inch, 0.35 * inch, 10.55 * inch, 0.35 * inch)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MID)
    canvas.drawString(0.45 * inch, 0.20 * inch, "v6.2 D1c | HLS Fmask lead-lag feasibility")
    canvas.drawRightString(10.55 * inch, 0.20 * inch, f"Page {doc.page}")
    canvas.restoreState()


def _display(value, digits=2):
    if value is None:
        return "Not available"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def build(manifest_path: Path, output_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = list(manifest["table_rows"])
    if len(rows) != 56:
        raise ValueError(f"Memo requires 56 D1c rows, found {len(rows)}")
    ruling = str(manifest["ruling"])
    keep = ruling == "KEEP_CONFIRMATORY"
    counts = manifest["counts"]
    lag = manifest["lag_summary_days"]

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleD1cFmask",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=23,
        textColor=INK,
        alignment=TA_LEFT,
        spaceAfter=5,
    )
    kicker = ParagraphStyle(
        "KickerD1cFmask",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=BLUE,
        spaceAfter=4,
    )
    h2 = ParagraphStyle(
        "H2D1cFmask",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        leading=13.5,
        textColor=INK,
        spaceBefore=4,
        spaceAfter=4,
    )
    body = ParagraphStyle(
        "BodyD1cFmask",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.3,
        textColor=INK,
        spaceAfter=4,
    )
    small = ParagraphStyle(
        "SmallD1cFmask", parent=body, fontSize=7.2, leading=9.2, spaceAfter=2
    )
    callout = ParagraphStyle(
        "CalloutD1cFmask",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=13.5,
        textColor=GREEN if keep else RED,
        spaceAfter=0,
    )
    metric_value = ParagraphStyle(
        "MetricValueD1cFmask",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=19,
        textColor=INK,
        alignment=TA_CENTER,
        spaceAfter=1,
    )
    metric_label = ParagraphStyle(
        "MetricLabelD1cFmask",
        parent=small,
        fontSize=6.8,
        leading=8.2,
        textColor=MID,
        alignment=TA_CENTER,
        spaceAfter=0,
    )
    cell = ParagraphStyle(
        "CellD1cFmask",
        parent=small,
        fontSize=6.8,
        leading=8.2,
        alignment=TA_CENTER,
        spaceAfter=0,
    )
    cell_left = ParagraphStyle("CellLeftD1cFmask", parent=cell, alignment=TA_LEFT)
    cell_header = ParagraphStyle("CellHeaderD1cFmask", parent=cell, textColor=colors.white)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(output_path),
        pagesize=landscape(letter),
        leftMargin=0.45 * inch,
        rightMargin=0.45 * inch,
        topMargin=0.42 * inch,
        bottomMargin=0.48 * inch,
        title="v6.2 D1c HLS Fmask Lead-Lag Reassessment",
        author="Urban Tree Cooling Project",
        subject="Quality-screened HLS V2 timing feasibility audit",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="memo", frames=[frame], onPage=footer)])

    status_text = (
        "KEEP CONFIRMATORY. The quality-screened HLS V2 pairs satisfy the frozen city, "
        "share and acquisition-reuse criteria."
        if keep
        else "DEMOTE TO EXPLORATORY. Exact timing is now verifiable, but the quality-screened "
        "pairs do not satisfy every frozen confirmatory-support criterion."
    )
    story = [
        Paragraph("D1C | HLS FMASK REASSESSMENT | 2 SEPTEMBER 2026", kicker),
        Paragraph("Lead-lag timing is now directly testable", title),
    ]
    ruling_box = Table([[Paragraph(f"RULING - {status_text}", callout)]], colWidths=[doc.width])
    ruling_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_GREEN if keep else PALE_RED),
                ("BOX", (0, 0), (-1, -1), 0.8, GREEN if keep else RED),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend([ruling_box, Spacer(1, 7)])

    metrics = [
        (str(counts["fmask_files"]), "Fmask files hash-verified and opened"),
        (str(counts["candidate_pass_window_sensor_rows"]), "candidate pass-window-sensor records"),
        (str(counts["quality_screened_pairs"]), "verified quality-screened pre/post pairs"),
        (f"{100 * counts['quality_screened_pair_share']:.1f}%", "overall paired share; ruling uses frozen strata"),
    ]
    metric_table = Table(
        [
            [Paragraph(value, metric_value) for value, _ in metrics],
            [Paragraph(label, metric_label) for _, label in metrics],
        ],
        colWidths=[doc.width / 4] * 4,
    )
    metric_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
                ("BOX", (0, 0), (-1, -1), 0.5, GRID),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, GRID),
                ("TOPPADDING", (0, 0), (-1, 0), 7),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([metric_table, Spacer(1, 7)])

    left = [
        Paragraph("Quality screen", h2),
        Paragraph(
            "Each HLS V2 Fmask was clipped to the frozen Census urban domain and the non-overlapping "
            "MGRS core. A cell survived when source data were present, Fmask bits 1-5 were zero, and "
            "aerosol bits 6-7 were no greater than two. A 1 km acquisition-block required at least "
            "60 surviving 30 m cells.",
            body,
        ),
        Paragraph("Pair construction", h2),
        Paragraph(
            "For every thermal pass and sensor, the analysis required distinct source identifiers: "
            "one HLS acquisition 1-15 days before and another 1-15 days after, with absolute lags "
            "within three days. A pair also needed at least 30 QA-usable study blocks in common. "
            "The frozen lag and stable-ID tie-breaker was applied after QA.",
            body,
        ),
    ]
    right = [
        Paragraph("What changed from D010", h2),
        Paragraph(
            "D010 could not estimate timing because the inherited centered Sentinel-2 object lacked "
            "source dates and identifiers. The D018 reassessment uses exact HLSL30.002 and HLSS30.002 "
            "metadata plus the acquired Fmask files, so pre/post direction, distinct identity, lag "
            "balance, spatial QA support and acquisition reuse are now measurable.",
            body,
        ),
        Paragraph("Interpretation boundary", h2),
        Paragraph(
            "This remains a feasibility count, not an exposure or outcome analysis. No HLS "
            "reflectance, optical index, ECOSTRESS LST, or v6.2 coefficient was opened. Passing this "
            "check would not authorize Gate A. The final antecedent and future-placebo variables must "
            "still be rebuilt separately from raw HLS reflectance after authorization.",
            body,
        ),
    ]
    columns = Table([[left, right]], colWidths=[doc.width / 2 - 0.1 * inch] * 2)
    columns.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 12),
                ("LEFTPADDING", (1, 0), (1, 0), 12),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("LINEBEFORE", (1, 0), (1, 0), 0.5, GRID),
            ]
        )
    )
    story.extend([columns, PageBreak()])

    story.extend(
        [
            Paragraph("D1C | NUMERICAL BASIS AND DECISION", kicker),
            Paragraph("Support by city and season window", title),
        ]
    )
    headers = ["City", "Window", "Candidates", "Verified pairs", "Share"]
    table_data = [[Paragraph(header, cell_header) for header in headers]]
    for city in ("Phoenix", "Los Angeles"):
        for window in ("provisional_primary", "sensitivity"):
            selected = [
                row for row in rows if row["city"] == city and row["season_window"] == window
            ]
            candidates = sum(int(row["candidate_passes"]) for row in selected)
            pairs = sum(int(row["passes_with_feasible_matched_pre_post"]) for row in selected)
            share = pairs / candidates if candidates else None
            table_data.append(
                [
                    Paragraph(city, cell_left),
                    Paragraph("Primary" if window == "provisional_primary" else "Sensitivity", cell_left),
                    Paragraph(str(candidates), cell),
                    Paragraph(str(pairs), cell),
                    Paragraph(f"{100 * share:.1f}%" if share is not None else "N/A", cell),
                ]
            )
    support_table = Table(
        table_data,
        colWidths=[1.05 * inch, 1.0 * inch, 0.8 * inch, 0.9 * inch, 0.7 * inch],
    )
    support_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("GRID", (0, 0), (-1, -1), 0.35, GRID),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    lag_box = Table(
        [[
            Paragraph(f"Pre median<br/><b>{_display(lag['pre_median'])} d</b>", metric_label),
            Paragraph(f"Pre p90<br/><b>{_display(lag['pre_p90'])} d</b>", metric_label),
            Paragraph(f"Post median<br/><b>{_display(lag['post_median'])} d</b>", metric_label),
            Paragraph(f"Post p90<br/><b>{_display(lag['post_p90'])} d</b>", metric_label),
        ]],
        colWidths=[1.15 * inch] * 4,
    )
    lag_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
                ("GRID", (0, 0), (-1, -1), 0.35, GRID),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    left2 = [
        Paragraph("Aggregated timing potential", h2),
        support_table,
        Spacer(1, 6),
        Paragraph(
            "The formal ruling is not based on these pooled shares. It applies the frozen 70% "
            "criterion to every nonzero city-year-window-sensor stratum and checks acquisition reuse.",
            small,
        ),
    ]
    right2 = [
        Paragraph("Verified lag distribution", h2),
        lag_box,
        Spacer(1, 7),
        Paragraph("Formal ruling", h2),
        Paragraph(
            f"The fail-closed result is <b>{ruling}</b>. "
            + (
                "Both cities have at least one frozen window that meets all nonzero-stratum pair-share "
                "and acquisition-reuse limits."
                if keep
                else "Neither city has a frozen window meeting every nonzero-stratum pair-share "
                "and acquisition-reuse limit. Timing provenance is repaired, but confirmatory support is not."
            ),
            body,
        ),
        Paragraph("Limitations carried forward", h2),
        Paragraph(
            "The 149 rasters came from the catalogue-selected pair plan. A missing pair is therefore "
            "conservative with respect to alternative HLS acquisitions whose Fmask was not downloaded. "
            "The screen is also optimistic because it does not yet require actual tree/background pixels, "
            "reflectance validity, reliability, or the final exposure construction.",
            body,
        ),
        Paragraph("Files to inspect", h2),
        Paragraph(
            "The 56-row table reports all required strata. The timing figure reports every selected "
            "pre/post lag. The JSON evidence retains per-acquisition QA coverage and each candidate-pair result.",
            body,
        ),
    ]
    columns2 = Table([[left2, right2]], colWidths=[doc.width / 2 - 0.1 * inch] * 2)
    columns2.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 12),
                ("LEFTPADDING", (1, 0), (1, 0), 12),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("LINEBEFORE", (1, 0), (1, 0), 0.5, GRID),
            ]
        )
    )
    story.extend([columns2])
    doc.build(story)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.manifest, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
