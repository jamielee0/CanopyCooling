#!/usr/bin/env python3
"""Create the two-page, coefficient-free D1d decision memo."""

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
RED = colors.HexColor("#B23A48")
PALE_RED = colors.HexColor("#FBEDEF")
PALE_BLUE = colors.HexColor("#EAF4F8")
MID = colors.HexColor("#58727D")
GRID = colors.HexColor("#CBD8DD")


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(GRID)
    canvas.line(0.45 * inch, 0.34 * inch, 10.55 * inch, 0.34 * inch)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MID)
    canvas.drawString(0.45 * inch, 0.19 * inch, "v6.2 D1d · five-pass precision free check · coefficients sealed")
    canvas.drawRightString(10.55 * inch, 0.19 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build(manifest_path: Path, stage_path: Path, power_path: Path, output_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stage = pd.read_csv(stage_path)
    power = pd.read_csv(power_path)
    if manifest["status"] != "D1D_STOP_NO_ESTIMABLE_BLOCK_PASS":
        raise ValueError("Memo builder received a non-frozen D1d status")
    if len(stage) != 13210 or len(power) != 48:
        raise ValueError("D1d memo row-count identity failed")
    if stage["convergence_flag"].astype(str).str.casefold().isin({"true", "1"}).any():
        raise ValueError("No-estimability memo cannot contain a converged row")

    styles = getSampleStyleSheet()
    kicker = ParagraphStyle(
        "Kicker", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8,
        leading=10, textColor=BLUE, spaceAfter=4,
    )
    title = ParagraphStyle(
        "Title", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=20,
        leading=23, textColor=INK, alignment=TA_LEFT, spaceAfter=5,
    )
    h2 = ParagraphStyle(
        "H2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11.2,
        leading=13, textColor=INK, spaceBefore=4, spaceAfter=4,
    )
    body = ParagraphStyle(
        "Body", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.2,
        leading=10.8, textColor=INK, spaceAfter=4,
    )
    small = ParagraphStyle("Small", parent=body, fontSize=7.1, leading=9.1, spaceAfter=2)
    callout = ParagraphStyle(
        "Callout", parent=body, fontName="Helvetica-Bold", fontSize=10.2,
        leading=13, textColor=RED, spaceAfter=0,
    )
    cell = ParagraphStyle(
        "Cell", parent=small, fontSize=6.8, leading=8.1, alignment=TA_CENTER, spaceAfter=0,
    )
    cell_left = ParagraphStyle("CellLeft", parent=cell, alignment=TA_LEFT)
    cell_head = ParagraphStyle("CellHead", parent=cell, textColor=colors.white)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(output_path), pagesize=landscape(letter), leftMargin=0.45 * inch,
        rightMargin=0.45 * inch, topMargin=0.42 * inch, bottomMargin=0.47 * inch,
        title="v6.2 D1d Stage 1 Precision Census", author="Urban Tree Cooling Project",
        subject="Five-pass native-grid precision free check with sealed coefficients",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="memo", frames=[frame], onPage=footer)])

    story = [
        Paragraph("D1D · STAGE 1 PRECISION CENSUS · 2 SEPTEMBER 2026", kicker),
        Paragraph("Stop: no block-pass meets the frozen canopy-span floor", title),
    ]
    ruling = Table([[Paragraph(
        "RULING — Do not begin Gate A from the current package. Across five selected native-grid "
        "passes, 13,210 block-passes have at least 60 complete cells, but 0 reach the frozen "
        "0.20 canopy p10–p90 span. No Stage-1 coefficient, spatial SE, or required-N value is estimable.",
        callout,
    )]], colWidths=[doc.width])
    ruling.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_RED), ("BOX", (0, 0), (-1, -1), 0.8, RED),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.extend([ruling, Spacer(1, 6), Paragraph("Five selected passes", h2)])

    rows = [[Paragraph(value, cell_head) for value in [
        "Pass", "Complete native cells", "Candidate block-passes", "Converged", "Stable"
    ]]]
    for item in manifest["pass_counts"]:
        rows.append([
            Paragraph(item["pass_id"], cell_left),
            Paragraph(f"{item['complete_native_cells']:,}", cell),
            Paragraph(f"{item['candidate_block_passes']:,}", cell),
            Paragraph(f"{item['converged_block_passes']:,}", cell),
            Paragraph("0", cell),
        ])
    table = Table(rows, colWidths=[1.35*inch, 1.35*inch, 1.35*inch, 0.9*inch, 0.8*inch], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK), ("GRID", (0, 0), (-1, -1), 0.35, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([
        table, Spacer(1, 6),
        Paragraph("Why the model stopped", h2),
        Paragraph(
            "The pass selection and all thresholds were frozen in D011 before the run. Candidate "
            "cell counts range from 60 to 450 (median 210). Canopy-span p25/median/p75 are "
            "0.021918/0.043041/0.065816; the maximum is 0.185551. Every row therefore stops "
            "before regression and spatial resampling. The requested SE, leverage, residual "
            "Moran’s I and stability columns remain blank/false with the same explicit failure code.",
            body,
        ),
        Paragraph("Sealed boundary", h2),
        Paragraph(
            "The canonical sealed file contains the required header and zero coefficient rows. "
            "SHA-256: <font name='Courier'>146b16f85aa89c486d174121d1e3e781ded685d8940f0dc6037e238b090d6004</font>. "
            "It was hashed but not opened after creation. Open tables contain no point-estimate field.",
            small,
        ),
        PageBreak(),
        Paragraph("D1D · INTERPRETATION AND NEXT ACTION", kicker),
        Paragraph("This is a real failure, but not a final-study effect result", title),
    ])

    left = [
        Paragraph("Acceptance status", h2),
        Paragraph(
            "Passed: exactly five outcome-blind-selected native passes; one candidate row per "
            "block-pass; native LST was not resampled; sealed/open separation and row identities "
            "passed. Failed/not estimable: one slope per block-pass, spatially robust SEs, observed "
            "sigma, and numerical detection/equivalence N. The 48-row planning table keeps both "
            "criteria, three reliabilities, all eight D1b combinations, and their available counts, "
            "but leaves required N blank rather than inventing it.", body,
        ),
        Paragraph("Immediate next action", h2),
        Paragraph(
            "Obtain the annual raw Science TCC 2019–2025 stack and repeat the canopy-span screen "
            "without opening thermal data. If that conforming nonthermal screen still produces no "
            "eligible block-passes, stop or reframe. If it materially changes eligibility, obtain "
            "supervisor approval before another five-pass thermal run. Gate A is not authorized.", body,
        ),
        Paragraph("Files", h2),
        Paragraph(
            "tables/d1d_stage1_se.csv · tables/d1d_n_required.csv · "
            "figures/d1d_se_distribution.png · figures/d1d_n_required.png · "
            "sealed/d1d_coefficients_SEALED.csv", small,
        ),
    ]
    right = [
        Paragraph("Precision-only deviations", h2),
        Paragraph(
            "This free check uses Collection-2 rather than final Collection-3 LST; inherited "
            "modified-NLCD canopy rather than annual Science TCC; the LSTE height layer rather "
            "than USGS 3DEP; NLCD-derived distance to water; and a 10 m subgrid approximation "
            "for building fraction. These were frozen and disclosed before the run. None may be "
            "promoted to the final exposure, context stack, or study sample.", body,
        ),
        Paragraph("Required cautions", h2),
        Paragraph(
            "1. A Stage-1 SE would be a measurement-error floor, not the Stage-2 residual SD.<br/>"
            "2. Connected block-passes—not all rows—define usable support.<br/>"
            "3. Passes sharing one HLS acquisition are dependent.<br/>"
            "4. D1b counts are optimistic historical upper bounds and cannot rescue zero "
            "Stage-1-eligible block-passes.", body,
        ),
        Paragraph("Scope consequence", h2),
        Paragraph(
            "The result stops the current D1d/Gate-A package. It does not establish that the "
            "conforming Science TCC stack will also fail, because the inherited canopy input is "
            "explicitly prohibited for the final v6.2 study. No coefficient sign or value was used "
            "in this ruling.", body,
        ),
    ]
    columns = Table([[left, right]], colWidths=[doc.width/2 - 0.08*inch, doc.width/2 - 0.08*inch])
    columns.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 10), ("LEFTPADDING", (1, 0), (1, -1), 10),
        ("RIGHTPADDING", (1, 0), (1, -1), 0), ("LINEBEFORE", (1, 0), (1, -1), 0.5, GRID),
    ]))
    story.append(columns)
    doc.build(story)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("stage_csv", type=Path)
    parser.add_argument("power_csv", type=Path)
    parser.add_argument("output_pdf", type=Path)
    args = parser.parse_args()
    build(args.manifest, args.stage_csv, args.power_csv, args.output_pdf)
    print(f"D1d memo written: {args.output_pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

