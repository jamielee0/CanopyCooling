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
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


NAVY = colors.HexColor("#17324D")
TEAL = colors.HexColor("#0E7490")
PALE_BLUE = colors.HexColor("#EAF4F8")
PALE_AMBER = colors.HexColor("#FFF4D6")
PALE_RED = colors.HexColor("#FDECEC")
SLATE = colors.HexColor("#334155")
LINE = colors.HexColor("#CBD5E1")


def build(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleV62",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18.5,
        leading=21,
        textColor=NAVY,
        alignment=TA_LEFT,
        spaceAfter=3,
    )
    deck = ParagraphStyle(
        "DeckV62",
        parent=styles["BodyText"],
        fontSize=7.6,
        leading=9.2,
        textColor=SLATE,
        spaceAfter=5,
    )
    decision = ParagraphStyle(
        "DecisionV62",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=9.2,
        leading=11.3,
        textColor=colors.HexColor("#7F1D1D"),
        spaceAfter=0,
    )
    section = ParagraphStyle(
        "SectionV62",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10.1,
        leading=11.7,
        textColor=NAVY,
        backColor=PALE_BLUE,
        borderColor=LINE,
        borderWidth=0.45,
        borderPadding=(3, 4, 3, 4),
        spaceBefore=3,
        spaceAfter=4,
    )
    body = ParagraphStyle(
        "BodyV62",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=7.15,
        leading=8.75,
        textColor=colors.black,
        spaceAfter=3,
    )
    small = ParagraphStyle(
        "SmallV62",
        parent=body,
        fontSize=6.35,
        leading=7.6,
        textColor=SLATE,
        spaceAfter=0,
    )

    doc = SimpleDocTemplate(
        str(output),
        pagesize=letter,
        leftMargin=0.42 * inch,
        rightMargin=0.42 * inch,
        topMargin=0.32 * inch,
        bottomMargin=0.30 * inch,
        title="Urban Tree Cooling v6.2 Pre-Gate A Decision Summary",
        author="Urban Tree Cooling Project",
        subject="Expanded six-part pre-Gate A status and decision page",
    )

    story = [
        Paragraph("Urban Tree Cooling v6.2 - Pre-Gate A Decision Summary", title),
        Paragraph(
            "Updated 3 September 2026 | Outcome-blind free checks and nonthermal acquisition closeout | No new v6.2 coefficient viewed",
            deck,
        ),
    ]

    decision_box = Table(
        [[Paragraph(
            "DECISION POSTURE: Do not begin Gate A under the current frozen design. Keep the optional atmospheric-demand branch inactive and on hold pending a supervisor ruling.",
            decision,
        )]],
        colWidths=[7.24 * inch],
        hAlign="LEFT",
    )
    decision_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_RED),
        ("BOX", (0, 0), (-1, -1), 0.9, colors.HexColor("#B91C1C")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([decision_box, Spacer(1, 3)])

    left = [
        Paragraph("What passed", section),
        Paragraph(
            "<b>Foundation and catalogue.</b> The independent Collection 3 audit passed all 31 required checks. Offline reproduction succeeded; all 69 evidence-packet checksums and 12 input hashes matched. Historical counts remain provenance only, not the new study sample.",
            body,
        ),
        Paragraph(
            "<b>Connectivity for planning.</b> All eight Phoenix/Los Angeles combinations of two season windows and 15/25 degree view sets were reported, including block-pass coverage, component share, sectors and land-use dominance. This supports planning, subject to the historical-proxy limitations below.",
            body,
        ),
        Paragraph(
            "<b>Data verification.</b> The inventory contains 149 HLS Fmask, 14 official Science TCC and two 3DEP files: 165 files and 800,091,676 bytes. Every file has a local SHA-256; the 16 Drive TCC/3DEP files also match Google MD5 metadata.",
            body,
        ),
        Paragraph(
            "<b>Checks executed correctly.</b> The official TCC screen and Fmask lead-lag reassessment completed without opening HLS reflectance, ECOSTRESS LST or new coefficients. Exact HLS dates and acquisition IDs are now verified, and 41 distinct cloud-screened pre/post pairs were found.",
            body,
        ),
        Paragraph("What remains unresolved", section),
        Paragraph(
            "<b>Design choice.</b> The supervisor must choose whether to stop, reframe the estimand, or approve a prospective design amendment after the canopy-span failure. The observed result cannot be used to relax the threshold retroactively.",
            body,
        ),
        Paragraph(
            "<b>Deferred inputs.</b> Full HLS reflectance, ECOSTRESS Collection 3 thermal products and precipitation are not yet acquired for the final analysis. HRRR/weather, L1B geometry, land use and other context are partial or inherited and must be frozen against the final sample if work restarts.",
            body,
        ),
        Paragraph(
            "<b>Supervisor confirmations.</b> A keep/drop/amend ruling is still needed for atmospheric demand, and the single email reference to v6.1 should be confirmed as a typo; v6.2 remains controlling because the guide, proposal, schedule and branch conventions all specify v6.2.",
            body,
        ),
        Paragraph("Whether the optional atmospheric-demand branch should remain", section),
        Paragraph(
            "<b>Recommendation: retain only as an inactive, documented option.</b> It should not enter a confirmatory model now. The binding full-nuisance test fails both cities. A less restrictive sensitivity passes Phoenix, while Los Angeles misses the common-support-width floor (0.300 versus 0.500 kPa). This mixed evidence supports supervisor review, not activation.",
            body,
        ),
        Paragraph(
            "If the supervisor wants to retain the scientific question, the revised nuisance design and keep/drop rule must be approved and frozen prospectively before any new coefficient is viewed. Otherwise, follow the binding rule and drop both VPD interactions together.",
            body,
        ),
    ]

    right = [
        Paragraph("What failed", section),
        Paragraph(
            "<b>Stage 1 canopy support - controlling failure.</b> Across the five preselected passes, zero of 13,509 candidate block-passes met the frozen Science TCC p10-p90 canopy-span floor of 0.20. The median span was 0.06600 and the maximum was 0.18410. Because this was an optimistic nonthermal screen, adding thermal-complete masking cannot create an eligible block-pass; the conditional thermal Stage 1 rerun was therefore not performed.",
            body,
        ),
        Paragraph(
            "<b>Lead-lag confirmatory support.</b> Fmask screening verified 41 of 110 candidate pass-window-sensor pairs (37.3%): Phoenix 20/44 and Los Angeles 21/66. Sixty-three candidates had timing-valid images but fewer than 30 shared cloud-free blocks, and six lacked a timing-valid pair in the downloaded plan. Neither city had a season window reaching the frozen 70% requirement in every applicable year-sensor stratum; Los Angeles also failed acquisition reuse in three strata. Lead-lag remains exploratory.",
            body,
        ),
        Paragraph(
            "<b>Atmospheric-demand binding test.</b> The predeclared strict VPD support rule fails both cities after the full temperature, vapour-pressure, time, season and viewing-geometry adjustment. The later parsimonious analysis is explicitly nonbinding and does not reverse that result.",
            body,
        ),
        Paragraph("Whether Gate A should begin", section),
        Paragraph(
            "<b>No - not under the current frozen design.</b> Foundation and connectivity readiness do not overcome the absence of an estimable canopy contrast. With zero eligible block-passes under the required official canopy product, the planned within-block canopy-LST slope cannot enter the requested Stage 1 precision census.",
            body,
        ),
        Paragraph(
            "Gate A can be reconsidered only after supervisor review produces either a defensible reframing or a prospectively frozen amendment. That decision must be logged before acquiring or opening Gate A-only reflectance and thermal outcome data, and the amended design must rerun the affected free checks.",
            body,
        ),
        Paragraph("Any deviations from the Working Guide", section),
        Paragraph(
            "<b>Version discrepancy.</b> One email reference says v6.1; all controlling attachments and repository conventions say v6.2, which is being used pending correction.",
            body,
        ),
        Paragraph(
            "<b>Historical proxies.</b> Connectivity uses inherited Collection 2 incidence rather than a selected Collection 3 v6.2 sample. The first Stage 1 diagnostic used modified NLCD canopy, Collection 2 thermal data, LSTE height and other inherited context proxies; it is superseded and is not the controlling scientific result.",
            body,
        ),
        Paragraph(
            "<b>Lead-lag scope.</b> The reassessment uses Fmask from 149 catalogue-selected acquisitions for feasibility only. It does not construct the Working Guide's final one-sided antecedent exposure or future placebo from raw HLS reflectance, and un-downloaded alternative HLS acquisitions could improve failed rows.",
            body,
        ),
        Paragraph(
            "<b>Pending rather than final VPD ruling.</b> The Working Guide requests a definite keep/drop decision. At the user's direction, the branch is currently held inactive pending supervisor review; this is explicitly disclosed and no interaction may be fitted meanwhile.",
            body,
        ),
        Paragraph(
            "No frozen scientific threshold was silently relaxed. Prior-protocol and synthetic outputs remain archived or isolated, and no new thermal value, reflectance value or coefficient was opened for these free checks.",
            body,
        ),
    ]

    columns = Table([[left, right]], colWidths=[3.59 * inch, 3.65 * inch], hAlign="LEFT")
    columns.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 8),
        ("LEFTPADDING", (1, 0), (1, 0), 8),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("LINEBEFORE", (1, 0), (1, 0), 0.6, LINE),
    ]))
    story.extend([columns, Spacer(1, 3)])

    footer = Table(
        [[Paragraph(
            "Decision basis: protocol v6.2; decisions V6.2-D003/D005/D006-D019; independent foundation audit; D1a-D1d evidence packages; and the verified raw-asset inventory. This is a decision aid, not supervisor approval.",
            small,
        )]],
        colWidths=[7.24 * inch],
    )
    footer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_AMBER),
        ("BOX", (0, 0), (-1, -1), 0.45, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(footer)
    doc.build(story)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.output)


if __name__ == "__main__":
    main()
