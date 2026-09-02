#!/usr/bin/env python3
"""Create the compact two-page v6.2 D1c lead-lag decision memo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
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
    canvas.drawString(0.45 * inch, 0.20 * inch, "v6.2 D1c | count-only optical feasibility")
    canvas.drawRightString(10.55 * inch, 0.20 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build(table_path: Path, manifest_path: Path, output_path: Path) -> None:
    data = pd.read_csv(table_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if len(data) != 58:
        raise ValueError(f"Memo requires 58 D1c rows, found {len(data)}")
    required = data.loc[data["record_role"].eq("required_hls_stratum")]
    legacy = data.loc[data["record_role"].eq("legacy_centered_product_audit")]
    if len(required) != 56 or len(legacy) != 2:
        raise ValueError("Memo requires 56 HLS rows and two legacy audit rows")

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleD1c",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=23,
        textColor=INK,
        alignment=TA_LEFT,
        spaceAfter=5,
    )
    kicker = ParagraphStyle(
        "KickerD1c",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=BLUE,
        spaceAfter=4,
    )
    h2 = ParagraphStyle(
        "H2D1c",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        leading=13.5,
        textColor=INK,
        spaceBefore=4,
        spaceAfter=4,
    )
    body = ParagraphStyle(
        "BodyD1c",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.3,
        textColor=INK,
        spaceAfter=4,
    )
    small = ParagraphStyle(
        "SmallD1c",
        parent=body,
        fontSize=7.2,
        leading=9.2,
        spaceAfter=2,
    )
    callout = ParagraphStyle(
        "CalloutD1c",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=13.5,
        textColor=RED,
        spaceAfter=0,
    )
    metric_value = ParagraphStyle(
        "MetricValue",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=19,
        textColor=INK,
        alignment=TA_CENTER,
        spaceAfter=1,
    )
    metric_label = ParagraphStyle(
        "MetricLabel",
        parent=small,
        fontSize=6.8,
        leading=8.2,
        textColor=MID,
        alignment=TA_CENTER,
        spaceAfter=0,
    )
    cell = ParagraphStyle(
        "CellD1c",
        parent=small,
        fontSize=6.8,
        leading=8.2,
        alignment=TA_CENTER,
        spaceAfter=0,
    )
    cell_left = ParagraphStyle("CellLeftD1c", parent=cell, alignment=TA_LEFT)
    cell_header = ParagraphStyle("CellHeaderD1c", parent=cell, textColor=colors.white)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(output_path),
        pagesize=landscape(letter),
        leftMargin=0.45 * inch,
        rightMargin=0.45 * inch,
        topMargin=0.42 * inch,
        bottomMargin=0.48 * inch,
        title="v6.2 D1c Lead-Lag Feasibility",
        author="Urban Tree Cooling Project",
        subject="Count-only inherited centered optical feasibility audit",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="memo", frames=[frame], onPage=footer)])

    story = [
        Paragraph("D1C | LEAD-LAG FEASIBILITY | 2 SEPTEMBER 2026", kicker),
        Paragraph("Temporal specificity is not confirmatory yet", title),
    ]
    ruling_box = Table(
        [[Paragraph(
            "RULING - DEMOTE TO EXPLORATORY. The inherited centered object can support a "
            "scene-count upper bound, but it cannot verify a matched pre-pass/post-pass pair.",
            callout,
        )]],
        colWidths=[doc.width],
    )
    ruling_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_RED),
                ("BOX", (0, 0), (-1, -1), 0.8, RED),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend([ruling_box, Spacer(1, 7)])

    metrics = [
        ("56", "required city-year-window-sensor HLS rows"),
        (str(manifest["inherited_product"]["axis_records"]), "legacy centered axis records"),
        ("0", "verified pre/post lag records"),
        ("0", "stored optical acquisition IDs"),
    ]
    metric_table = Table(
        [[Paragraph(value, metric_value) for value, _ in metrics],
         [Paragraph(label, metric_label) for _, label in metrics]],
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
        Paragraph("What was run", h2),
        Paragraph(
            "Frozen rule V6.2-D009 was applied to the primary 15-degree historical pass "
            "denominator. The complete reporting grid covers Phoenix and Los Angeles, 2019-2025, "
            "both frozen season windows, and HLSL30.002 plus HLSS30.002. Only coordinates, "
            "attributes, and observed_valid_count were opened from the inherited centered object.",
            body,
        ),
        Paragraph("What came out", h2),
        Paragraph(
            "The object reports COPERNICUS/S2_SR_HARMONIZED, Phoenix only, 2 June to 29 September "
            "2023. It is therefore not the frozen HLS V2 product. Every one of its 66 axis records "
            "has a spatial median centered scene count of at least two, but no source date, sensor "
            "record, or optical acquisition identifier is stored.",
            body,
        ),
    ]
    right = [
        Paragraph("Why count >=2 is not a pair", h2),
        Paragraph(
            "A centered count has no sign. Two contributing scenes may both be before the pass, "
            "both after it, or at very different lags. It also cannot show whether the same optical "
            "acquisition was reused across many thermal passes. Treating count >=2 as a verified "
            "pair would create timing evidence that is not present in the file.",
            body,
        ),
        Paragraph("Interpretation boundary", h2),
        Paragraph(
            "The count is feasibility-only. The centered object is not the final antecedent "
            "exposure and is not the final future placebo. Both must be rebuilt separately from "
            "raw HLS with one-sided timing. No optical index value, ECOSTRESS LST value, or new "
            "v6.2 coefficient was opened. Gate A remains unauthorised.",
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
    story.extend([columns, Spacer(1, 5), Paragraph("Legacy centered count inventory", h2)])

    headers = ["Window", "D1c candidates", "Count >=2 upper bound", "All legacy axes", "Matched axes", "Verified pairs"]
    rows = [[Paragraph(header, cell_header) for header in headers]]
    for record in legacy.sort_values("season_window").itertuples(index=False):
        rows.append(
            [
                Paragraph("Primary" if record.season_window == "provisional_primary" else "Sensitivity", cell_left),
                Paragraph(str(int(record.candidate_passes)), cell),
                Paragraph(str(int(record.centered_count_ge2_passes_upper_bound)), cell),
                Paragraph(str(int(record.inherited_product_axis_records)), cell),
                Paragraph(str(int(record.matched_candidate_axis_records)), cell),
                Paragraph("Not estimable", cell),
            ]
        )
    count_table = Table(rows, colWidths=[1.1 * inch, 1.1 * inch, 1.45 * inch, 1.1 * inch, 1.05 * inch, 1.1 * inch])
    count_table.setStyle(
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
    story.extend(
        [
            count_table,
            Spacer(1, 3),
            Paragraph(
                "D1c candidates are Phoenix 2023 passes in the inherited 15-degree metadata census. "
                "The all-axis column describes the broader legacy object; matched axes are records that "
                "join to those candidate pass orbits. Neither column contains optical source timing.",
                small,
            ),
            PageBreak(),
            Paragraph("D1C | DECISION AND NEXT EVIDENCE", kicker),
            Paragraph("What would restore a confirmatory timing test", title),
        ]
    )

    frozen_box = Table(
        [[Paragraph(
            "Frozen verified-pair rule: distinct acquisitions from the same sensor; one at least "
            "24 hours before and one at least 24 hours after the thermal pass; each 1-15 days away; "
            "absolute lags within 3 days of one another. Choose the least-imbalanced, then shortest pair.",
            body,
        )]],
        colWidths=[doc.width],
    )
    frozen_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_AMBER),
                ("BOX", (0, 0), (-1, -1), 0.8, AMBER),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend([frozen_box, Spacer(1, 7)])

    candidate = manifest["candidate_pass_counts_15deg"]
    year_headers = ["Year", "PHX primary", "PHX sensitivity", "LA primary", "LA sensitivity"]
    year_rows = [[Paragraph(header, cell_header) for header in year_headers]]
    for year in range(2019, 2026):
        year_rows.append(
            [
                Paragraph(str(year), cell),
                Paragraph(str(candidate["phoenix"]["provisional_primary"][str(year)]), cell),
                Paragraph(str(candidate["phoenix"]["sensitivity"][str(year)]), cell),
                Paragraph(str(candidate["los_angeles"]["provisional_primary"][str(year)]), cell),
                Paragraph(str(candidate["los_angeles"]["sensitivity"][str(year)]), cell),
            ]
        )
    year_table = Table(year_rows, colWidths=[0.72 * inch, 1.05 * inch, 1.1 * inch, 1.05 * inch, 1.1 * inch])
    year_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("GRID", (0, 0), (-1, -1), 0.35, GRID),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )

    left2 = [
        Paragraph("Candidate-pass denominator", h2),
        year_table,
        Spacer(1, 3),
        Paragraph(
            "Counts use the D1b historical quality-and-exact-weather-complete pass census at the "
            "primary 15-degree geometry set. They are feasibility denominators, not the new v6.2 sample.",
            small,
        ),
    ]
    right2 = [
        Paragraph("Ruling", h2),
        Paragraph(
            "Demote the temporal-specificity diagnostic to exploratory. The result is about missing "
            "timing provenance, not proof that usable pre/post imagery is absent. A numeric matched-pair "
            "share is deliberately left blank rather than reported as zero.",
            body,
        ),
        Paragraph("What remains unresolved", h2),
        Paragraph(
            "1. Build a source-level HLSL30.002 and HLSS30.002 ledger for both cities and all years, "
            "retaining acquisition ID, source date, sensor, QA, and thermal-pass reuse.<br/>"
            "2. Apply the frozen matched-lag rule and rerun the 56-row table plus the timing histogram.<br/>"
            "3. Rebuild final antecedent and future W separately from raw HLS. Never promote the centered "
            "composite to either role.",
            body,
        ),
        Paragraph("Files to inspect", h2),
        Paragraph(
            "tables/d1c_leadlag.csv contains every required HLS stratum and two labeled legacy audit "
            "rows. figures/d1c_timing.png shows the explicit no-verifiable-lag state. "
            "data/d1c_centered_count_audit.json records every permitted count-only axis read.",
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
    parser.add_argument("table", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.table, args.manifest, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
