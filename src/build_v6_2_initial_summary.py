#!/usr/bin/env python3
"""Build the one-page v6.2 pre-Gate A decision summary."""

from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


NAVY = colors.HexColor("#17324D")
TEAL = colors.HexColor("#0E7490")
PALE_BLUE = colors.HexColor("#EAF4F8")
PALE_GREEN = colors.HexColor("#E8F5E9")
PALE_AMBER = colors.HexColor("#FFF4D6")
PALE_RED = colors.HexColor("#FDECEC")
SLATE = colors.HexColor("#334155")
LINE = colors.HexColor("#CBD5E1")


def build(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=19,
        leading=22,
        textColor=NAVY,
        alignment=TA_LEFT,
        spaceAfter=4,
    )
    deck = ParagraphStyle(
        "Deck",
        parent=styles["BodyText"],
        fontSize=8.4,
        leading=10.2,
        textColor=SLATE,
        spaceAfter=6,
    )
    callout = ParagraphStyle(
        "Callout",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=13,
        textColor=colors.HexColor("#7F1D1D"),
        spaceAfter=0,
    )
    section = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=12,
        textColor=NAVY,
        spaceBefore=5,
        spaceAfter=3,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=7.7,
        leading=9.45,
        textColor=colors.black,
        spaceAfter=2,
    )
    small = ParagraphStyle(
        "Small",
        parent=body,
        fontSize=6.8,
        leading=8.1,
        textColor=SLATE,
    )
    cell = ParagraphStyle(
        "Cell",
        parent=body,
        fontSize=7.1,
        leading=8.5,
        spaceAfter=0,
    )
    cell_bold = ParagraphStyle(
        "CellBold",
        parent=cell,
        fontName="Helvetica-Bold",
        textColor=NAVY,
    )

    doc = SimpleDocTemplate(
        str(output),
        pagesize=letter,
        leftMargin=0.42 * inch,
        rightMargin=0.42 * inch,
        topMargin=0.34 * inch,
        bottomMargin=0.32 * inch,
        title="Urban Tree Cooling v6.2 Pre-Gate A Decision Summary",
        author="Urban Tree Cooling Project",
    )

    story = [
        Paragraph("Urban Tree Cooling v6.2 — Pre-Gate A Decision Summary", title),
        Paragraph(
            "Prepared 2 September 2026 · Outcome-blind free checks and nonthermal acquisition closeout · No new coefficient viewed",
            deck,
        ),
    ]

    gate_box = Table(
        [[Paragraph("CURRENT RECOMMENDATION", cell_bold), Paragraph(
            "DO NOT BEGIN GATE A UNDER THE CURRENT FROZEN DESIGN. The required canopy contrast was absent in all five tested passes; supervisor review is needed to stop, reframe, or prospectively amend the design.",
            callout,
        )]],
        colWidths=[1.38 * inch, 5.86 * inch],
        hAlign="LEFT",
    )
    gate_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_RED),
        ("BOX", (0, 0), (-1, -1), 1.1, colors.HexColor("#B91C1C")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [gate_box, Spacer(1, 5)]

    status_data = [
        [Paragraph("Workstream", cell_bold), Paragraph("Current status", cell_bold), Paragraph("Evidence and implication", cell_bold)],
        [Paragraph("Foundation / catalogue", cell_bold), Paragraph("PASS", cell), Paragraph("Independent audit passes 31/31 required checks; 69 packet checksums and 12 input hashes match; offline reproduction passes.", cell)],
        [Paragraph("Connectivity", cell_bold), Paragraph("PASS FOR PLANNING", cell), Paragraph("All eight city × season × view-set combinations reported. The 15° inherited historical incidence proxy supports planning, but it is not the v6.2 sample and does not authorize Gate A.", cell)],
        [Paragraph("Lead–lag", cell_bold), Paragraph("EXPLORATORY / DEMOTED", cell), Paragraph("Feasibility count used only the inherited centred HLS product. It lacks the provenance needed to serve as the final exposure and must be rebuilt if retained.", cell)],
        [Paragraph("VPD branch", cell_bold), Paragraph("INACTIVE HOLD", cell), Paragraph("Strict D003 fails both cities. Nonbinding D005 passes Phoenix; Los Angeles fails only common-support width (0.300 versus frozen 0.500 kPa). No final keep/drop ruling is claimed; supervisor direction is required before activation.", cell)],
        [Paragraph("Stage 1", cell_bold), Paragraph("STOP", cell), Paragraph("Official Science TCC screen: 0/13,509 candidate block-passes meet p10–p90 canopy span ≥0.20; median 0.06600, maximum 0.18410. The optimistic nonthermal mask cannot hide an eligible thermal-complete block-pass, so no thermal rerun occurred.", cell)],
    ]
    status = Table(status_data, colWidths=[1.35 * inch, 1.22 * inch, 4.67 * inch], repeatRows=1)
    status.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TEAL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (1, 1), (1, 2), PALE_GREEN),
        ("BACKGROUND", (1, 3), (1, 4), PALE_AMBER),
        ("BACKGROUND", (1, 5), (1, 5), PALE_RED),
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [status]

    left = [
        Paragraph("Verified inputs", section),
        Paragraph("<b>165 files · 800,091,676 bytes.</b> HLS Fmask: 149 files / 161,907,529 bytes. Science TCC: 14 files / 211,808,618 bytes. 3DEP: 2 files / 426,375,529 bytes. Every file has a local SHA-256; all 16 Drive outputs also match Google MD5 metadata.", body),
        Paragraph("The Science TCC files cover Phoenix and Los Angeles for 2019–2025 and contain canopy cover and standard error. The 3DEP Earth Engine snapshot ends 4 May 2022.", body),
        Paragraph("Remaining data", section),
        Paragraph("HLS reflectance is deferred to Gate A. ECOSTRESS Collection 3 remains catalogue-only/incomplete. Precipitation is not acquired. HRRR/weather, L1B geometry, land-use and other context are partial or inherited and must be frozen for the final sample if Gate A is later authorized.", body),
    ]
    right = [
        Paragraph("What must happen next", section),
        Paragraph("1. Supervisor chooses <b>stop, reframe, or prospective amendment</b> for the canopy-span failure. Threshold relaxation after seeing this result is prohibited.", body),
        Paragraph("2. Supervisor gives a definite VPD keep/drop/amend ruling. Until then the branch stays inactive and no VPD interaction may enter a model.", body),
        Paragraph("3. If a revised design is authorized, freeze the revision before opening any new coefficient or acquiring Gate A-only exposure data.", body),
        Paragraph("Governance / deviations", section),
        Paragraph("The earlier Stage 1 run used NLCD only as a prohibited-proxy diagnostic; the official TCC screen now supplies the controlling result. Lead–lag remains exploratory. Connectivity remains a Collection 2 historical proxy. The user directed VPD to remain on hold, so the professor’s requested final keep/drop ruling is unresolved. No thermal or HLS reflectance values were opened for acquisition or the TCC screen.", body),
    ]
    columns = Table([[left, right]], colWidths=[3.60 * inch, 3.64 * inch], hAlign="LEFT")
    columns.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 8),
        ("LEFTPADDING", (1, 0), (1, 0), 8),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("LINEBEFORE", (1, 0), (1, 0), 0.6, LINE),
    ]))
    story += [columns, Spacer(1, 3)]

    footer = Table(
        [[Paragraph(
            "Decision basis: protocol v6.2, decisions V6.2-D003/D005/D006–D016, independent foundation audit, D1a–D1d packages, and the verified raw-asset inventory. This page is a decision aid, not supervisor approval.",
            small,
        )]],
        colWidths=[7.24 * inch],
    )
    footer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.45, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(KeepTogether(footer))
    doc.build(story)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.output)


if __name__ == "__main__":
    main()
