#!/usr/bin/env python3
"""Create the compact two-page D1b connectivity decision memo."""

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
GREEN = colors.HexColor("#1B7F5B")
PALE_GREEN = colors.HexColor("#E8F5EF")
RED = colors.HexColor("#B23A48")
PALE_RED = colors.HexColor("#FBEDEF")
MID = colors.HexColor("#58727D")
GRID = colors.HexColor("#CBD8DD")


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(GRID)
    canvas.line(0.45 * inch, 0.35 * inch, 10.55 * inch, 0.35 * inch)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MID)
    canvas.drawString(0.45 * inch, 0.20 * inch, "v6.2 D1b · nonthermal historical feasibility proxy")
    canvas.drawRightString(10.55 * inch, 0.20 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build(table_path: Path, manifest_path: Path, output_path: Path) -> None:
    data = pd.read_csv(table_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if len(data) != 8:
        raise ValueError(f"Memo requires eight rows, found {len(data)}")

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleD1b",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=23,
        textColor=INK,
        alignment=TA_LEFT,
        spaceAfter=5,
    )
    kicker = ParagraphStyle(
        "Kicker",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=BLUE,
        spaceAfter=4,
    )
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=14,
        textColor=INK,
        spaceBefore=5,
        spaceAfter=5,
    )
    body = ParagraphStyle(
        "BodyD1b",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.4,
        leading=11.2,
        textColor=INK,
        spaceAfter=4,
    )
    small = ParagraphStyle(
        "SmallD1b",
        parent=body,
        fontSize=7.2,
        leading=9.2,
        spaceAfter=2,
    )
    callout = ParagraphStyle(
        "Callout",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=13.5,
        textColor=GREEN,
        alignment=TA_LEFT,
        spaceAfter=0,
    )
    cell = ParagraphStyle(
        "Cell",
        parent=small,
        fontSize=6.7,
        leading=8,
        alignment=TA_CENTER,
        spaceAfter=0,
    )
    cell_left = ParagraphStyle("CellLeft", parent=cell, alignment=TA_LEFT)
    cell_header = ParagraphStyle("CellHeader", parent=cell, textColor=colors.white)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(output_path),
        pagesize=landscape(letter),
        leftMargin=0.45 * inch,
        rightMargin=0.45 * inch,
        topMargin=0.42 * inch,
        bottomMargin=0.48 * inch,
        title="v6.2 D1b Block-Pass Connectivity Report",
        author="Urban Tree Cooling Project",
        subject="Outcome-blind historical connectivity feasibility audit",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="memo", frames=[frame], onPage=footer)])

    story = [
        Paragraph("D1B · CONNECTIVITY REPORT · 30 AUGUST 2026", kicker),
        Paragraph("Block-pass connectivity is supportable at 15°", title),
    ]
    ruling_box = Table(
        [[Paragraph(
            "RULING - The historical incidence proxy passes without using the 25° widening. "
            "Six of eight panels pass the frozen numerical rule; all eight are reported below.",
            callout,
        )]],
        colWidths=[doc.width],
    )
    ruling_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_GREEN),
                ("BOX", (0, 0), (-1, -1), 0.8, GREEN),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend([ruling_box, Spacer(1, 7), Paragraph("All eight required combinations", h2)])

    headers = ["City", "Season window", "View", "Blocks", "Passes", "Block-passes", "Median", "P10", "Blocks <8", "LCC share", "Sectors", "Result"]
    rows = [[Paragraph(h, cell_header) for h in headers]]
    for record in data.itertuples(index=False):
        city = "PHX" if record.city == "Phoenix" else "LA"
        window = "Primary" if record.season_window == "provisional_primary" else "Sensitivity"
        passed = str(record.combination_pass).lower() == "true"
        rows.append(
            [
                Paragraph(city, cell),
                Paragraph(window, cell_left),
                Paragraph(f"≤{int(record.view_zenith_set_deg)}°", cell),
                Paragraph(f"{int(record.eligible_blocks):,}", cell),
                Paragraph(f"{int(record.eligible_passes):,}", cell),
                Paragraph(f"{int(record.block_passes):,}", cell),
                Paragraph(f"{float(record.median_passes_per_block):.1f}", cell),
                Paragraph(f"{float(record.p10_passes_per_block):.1f}", cell),
                Paragraph(f"{int(record.blocks_below_floor):,}", cell),
                Paragraph(f"{float(record.largest_connected_component_share):.3f}", cell),
                Paragraph(f"{int(record.spatial_sectors)}/4", cell),
                Paragraph("PASS" if passed else "FAIL", cell),
            ]
        )
    widths = [0.42, 0.86, 0.45, 0.56, 0.52, 0.75, 0.57, 0.52, 0.67, 0.66, 0.54, 0.53]
    table = Table(rows, colWidths=[w * inch for w in widths], repeatRows=1, hAlign="LEFT")
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for row_index, record in enumerate(data.itertuples(index=False), start=1):
        passed = str(record.combination_pass).lower() == "true"
        style_commands.append(("BACKGROUND", (11, row_index), (11, row_index), PALE_GREEN if passed else PALE_RED))
        style_commands.append(("TEXTCOLOR", (11, row_index), (11, row_index), GREEN if passed else RED))
    table.setStyle(TableStyle(style_commands))
    story.extend(
        [
            table,
            Spacer(1, 7),
            Paragraph(
                "Frozen pass rule: ≥30 blocks, ≥3 sectors, largest-component share ≥0.80, "
                "and median ≥8 passes/block. LCC is the share of all eligible block-pass edges "
                "in the largest bipartite component.",
                small,
            ),
            Paragraph(
                "The two failures are count-limited: Phoenix primary ≤15° has five eligible "
                "passes; Los Angeles sensitivity ≤15° has median 6.0 passes/block. Both pass "
                "after the required 25° sensitivity is displayed, but that widening is not "
                "needed for the overall ruling.",
                body,
            ),
            PageBreak(),
            Paragraph("D1B · INTERPRETATION BOUNDARY", kicker),
            Paragraph("What this report establishes - and what it does not", title),
        ]
    )

    left = [
        Paragraph("Decision", h2),
        Paragraph(
            "Proceed with connectivity planning at the 15° near-nadir set. Do not invoke the "
            "single 25° widening for the ruling. The 25° panels remain incidence sensitivities "
            "and are not fully geometry-admissible until view azimuth is resolved.",
            body,
        ),
        Paragraph("Spatial structure", h2),
        Paragraph(
            "Every panel contains all four projected urban sectors and has an LCC share of "
            "1.000. The maps show broad urban-area coverage rather than an airport, desert-fringe, "
            "or single-park island. The largest modal land-use class is Developed, Medium "
            "Intensity in every panel, accounting for 60.1%-64.8% of eligible edges.",
            body,
        ),
        Paragraph("Files to inspect", h2),
        Paragraph(
            "figures/d1b_map.png maps the eight panels; figures/d1b_hist.png shows their "
            "pass-count distributions; tables/d1b_connectivity.csv is the machine-readable "
            "eight-row result.",
            body,
        ),
    ]
    right = [
        Paragraph("Method in one paragraph", h2),
        Paragraph(
            "The audit uses fixed 1 km local-UTM blocks whose centroids fall within each repaired "
            "2020 Census urban-area boundary. Candidate 2019-2025 passes must be quality-and-"
            "exact-weather complete, fall in the local-solar season, and meet the pass-level p95 "
            "view-zenith set. An edge needs ≥60 clear, valid-view native 70 m cells after canonical "
            "MGRS partitioning and a cloudy-wins overlap rule. Modal 2024 Annual NLCD Collection "
            "1.1 class supplies the descriptive land-use label.",
            body,
        ),
        Paragraph("Mandatory limitations", h2),
        Paragraph(
            "This is inherited Collection 2 quality/geometry evidence - not the new v6.2 Collection "
            "3 study sample. The 60-cell edge is an optimistic necessary condition for later "
            "disjoint 30-tree and 30-background floors; Science TCC, fixed-background, canopy-span, "
            "and optical checks can only remove edges.",
            body,
        ),
        Paragraph(
            "The inherited five-city census begins June 1. Phoenix primary and Los Angeles "
            "sensitivity are therefore June 1-July 10 lower bounds for their nominal May 15-July "
            "10 windows. No quality-and-weather-complete Phoenix May 15-31 augmentation pass was "
            "available.",
            body,
        ),
        Paragraph(
            "No ECOSTRESS LST value and no new v6.2 coefficient was opened. This free check does "
            "not authorize Gate A, sample selection, or thermal processing.",
            body,
        ),
    ]
    columns = Table(
        [[left, right]],
        colWidths=[doc.width / 2 - 0.1 * inch, doc.width / 2 - 0.1 * inch],
        hAlign="LEFT",
    )
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
    story.extend([columns, Spacer(1, 8)])

    land_headers = ["City", "Window", "View", "Dominant modal Annual NLCD class", "Eligible-edge share"]
    land_rows = [[Paragraph(x, cell_header) for x in land_headers]]
    for record in data.itertuples(index=False):
        land_rows.append(
            [
                Paragraph("PHX" if record.city == "Phoenix" else "LA", cell),
                Paragraph("Primary" if record.season_window == "provisional_primary" else "Sensitivity", cell_left),
                Paragraph(f"≤{int(record.view_zenith_set_deg)}°", cell),
                Paragraph(str(record.dominant_land_use_class), cell_left),
                Paragraph(f"{100 * float(record.largest_share_one_land_use_class):.1f}%", cell),
            ]
        )
    land_table = Table(land_rows, colWidths=[0.52 * inch, 0.8 * inch, 0.5 * inch, 2.1 * inch, 0.9 * inch], repeatRows=1)
    land_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.3, GRID),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.extend(
        [
            Paragraph("Land-use dominance detail", h2),
            land_table,
            Spacer(1, 4),
            Paragraph(
                "Annual NLCD source: USGS Annual NLCD Collection 1.1 Land Cover 2024, 30 m, "
                "nearest-neighbor export. Exact city hashes are frozen in analysis_manifest.json.",
                small,
            ),
        ]
    )
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
