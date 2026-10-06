#!/usr/bin/env python3
"""Two-page advisory-review progress report: Phoenix pilot (v1) -> five-city study (v2)."""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

FIG = Path(
    "/Users/jmlee/Documents/TreeProject/project/figures/v2/"
    "prof_spec_support_grid/F_PROF.1_demand_water_support_grid.png"
)
OUT = Path(
    "/Users/jmlee/Documents/TreeProject/project/deliverables/"
    "Urban_Tree_Cooling_v1_to_v2_Summary_2026-08-06.docx"
)

FONT = "Calibri"
INK = RGBColor(0x1A, 0x1A, 0x1A)
GREY = RGBColor(0x59, 0x59, 0x59)
RED = RGBColor(0xB0, 0x00, 0x20)
PURPLE = RGBColor(0x4A, 0x14, 0x8C)


def run(paragraph, text, *, size=9.5, bold=False, italic=False, color=INK):
    r = paragraph.add_run(text)
    r.font.name = FONT
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.italic = italic
    r.font.color.rgb = color
    return r


def para(doc, *, before=0, after=5, line=1.08, align=None):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line
    if align is not None:
        pf.alignment = align
    return p


def body(doc, text, **kw):
    p = para(doc, **kw)
    run(p, text)
    return p


def heading(doc, text, *, before=9, page_break=False):
    p = para(doc, before=before, after=3)
    if page_break:
        p.paragraph_format.page_break_before = True
    run(p, text, size=11.5, bold=True)
    return p


def bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    pf = p.paragraph_format
    pf.space_after = Pt(3)
    pf.line_spacing = 1.08
    pf.left_indent = Inches(0.25)
    run(p, text)
    return p


def shade(cell, fill):
    el = OxmlElement("w:shd")
    el.set(qn("w:val"), "clear")
    el.set(qn("w:color"), "auto")
    el.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(el)


def rule(paragraph, edge="bottom"):
    pPr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    b = OxmlElement(f"w:{edge}")
    b.set(qn("w:val"), "single")
    b.set(qn("w:sz"), "6")
    b.set(qn("w:space"), "4")
    b.set(qn("w:color"), "BFBFBF")
    borders.append(b)
    pPr.append(borders)


COMPARE = [
    ("", "v1 — up to 17 July 2026", "v2 — from 1 August 2026"),
    ("What it is", "My Phoenix pilot, plus your review", "My build of the step-by-step guide"),
    ("Cities and years", "Phoenix only, summer 2023", "5 cities, summers 2018–2025, with 2026 sealed"),
    ("City boundaries", "A bounding box I drew myself", "2020 Census Urban Areas, with hashes recorded"),
    (
        "Grid",
        "My own 70 m grid (EPSG:32612)",
        "The satellite's own tile grid, so temperature is never resampled",
    ),
    (
        "What counts as one observation",
        "Pixels and block groups (9 pairs)",
        "One satellite pass. I have 219, worth 159.09 pass-equivalents",
    ),
    (
        "Water variable",
        "Root-zone soil moisture, which was your fix; CSI dropped to secondary",
        "30 and 60-day rainfall minus reference ET. Soil moisture and CSI both gone",
    ),
    (
        "Weather",
        "ERA5-Land, hourly",
        "HRRR, interpolated to the exact second of each overpass (413 of 413 hours)",
    ),
    (
        "Record-keeping",
        "A design-decisions write-up",
        "58 frozen decisions, 17 logged runs, and gates that fail closed",
    ),
    ("Code", "16 modules, 133 tests", "30 modules, about 25k lines, 139 tests"),
    (
        "Cooling result",
        "I got a response surface, but no solid threshold (only 9 block groups)",
        "None. The feasibility checks stopped me before I opened any temperature data",
    ),
]


def main() -> None:
    doc = Document()

    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.6)
    section.left_margin = Inches(0.75)
    section.right_margin = Inches(0.75)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(9.5)

    # ---------------- header ----------------
    p = para(doc, after=2)
    run(p, "Urban Tree Cooling: from my Phoenix pilot to the five-city study", size=16, bold=True)
    p = para(doc, after=6)
    run(p, "Progress summary  ·  6 August 2026  ·  Jamie Lee", size=9, color=GREY)
    rule(p)

    p = para(doc, before=6, after=8)
    run(p, "Where things stand: ", bold=True)
    run(
        p,
        "I finished every check that comes before the real analysis, and they told me to stop. I "
        "have not opened any of the temperature data, I have not picked the held-out city, and "
        "the 2026 season is still sealed.",
        color=RED,
    )

    # ---------------- what changed ----------------
    heading(doc, "What changed", before=0)
    body(
        doc,
        "There were two separate rounds of changes here, and they are easy to mix up. The first "
        "was your review, which I finished on the Phoenix pilot by 17 July. That is what I am "
        "calling v1. I swapped NDMI out for root-zone soil moisture, made the demand by water "
        "surface the main detector instead of the single CSI number, and moved the analysis down "
        "to the pixel level with block-group clustering. All fifteen findings are closed.",
    )
    body(
        doc,
        "Then the step-by-step guide arrived on 1 August, and it asked for a much bigger project: "
        "five cities, eight summers, the satellite's own grid, and a feasibility check before "
        "downloading any temperature data at all. That is v2. I started it the same day and built "
        "it as a separate package, so the Phoenix pilot still runs and still passes its tests.",
        after=6,
    )

    table = doc.add_table(rows=0, cols=3)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    widths = (Inches(1.45), Inches(2.45), Inches(3.1))
    for i, row_data in enumerate(COMPARE):
        cells = table.add_row().cells
        for j, text in enumerate(row_data):
            cells[j].width = widths[j]
            cell_p = cells[j].paragraphs[0]
            cell_p.paragraph_format.space_after = Pt(1)
            cell_p.paragraph_format.space_before = Pt(1)
            cell_p.paragraph_format.line_spacing = 1.0
            run(cell_p, text, size=8.5, bold=(i == 0 or j == 0))
            if i == 0:
                shade(cells[j], "EDEDF2")

    # ---------------- findings ----------------
    heading(doc, "What I ran, and what came back")

    p = para(doc, after=5)
    run(p, "Step 1, checking the conditions. Done. ", bold=True)
    run(
        p,
        "I set up the five city boundaries, pulled the gridMET weather, and worked out demand and "
        "antecedent dryness for every summer day. Everything passed. The answer was that I can "
        "only separate the two effects across cities, not inside them. Only Los Angeles and "
        "Minneapolis–St. Paul passed the within-city test. Clear-sky days are also very uneven: "
        "Miami has 68 usable summer days and Phoenix has 697.",
    )

    p = para(doc, after=5)
    run(p, "Step 2, counting the satellite passes. Done, but it says stop. ", bold=True)
    run(
        p,
        "I started with 2,968 passes, 1,055 of them in daylight, and 942 with the metadata I "
        "needed. Then I found a problem in my own screening. All 400,414 cloudy pixels had broken "
        "view-angle values, which meant my “good geometry” filter was really just measuring "
        "whether it was cloudy. I redid it with the L1B GEO files, which do not have that problem. "
        "That is when I hit something I could not fix: 41 of the files I needed are missing from "
        "the LP DAAC archive. I tried every route I could think of and they all came back 404, so "
        "I sent a restoration request and dropped the 31 affected passes rather than guess at "
        "them. After that the geometry finished for all 911, cloud screening ran on all 219 "
        "near-nadir passes, and the weather finished for all 413 hours. All six checks passed. ",
    )
    run(
        p,
        "The gate still says stop, and this is why: the low-demand and dry box has only 0.553 "
        "pass-equivalents in it, and the rule I set says I need at least 10.",
        bold=True,
    )

    p = para(doc, after=5)
    run(p, "Step 3, the backup plan. Done, also says stop. ", bold=True)
    run(
        p,
        "With the interaction off the table, I switched to time of day as the main question. Using "
        "the 102 real passes I have, the power comes out at 0.110 when I need 0.80, and it stays "
        "between 0.100 and 0.145 no matter which city I drop. The problem is not that I need more "
        "data. The late-afternoon flag is 99.4% predictable from the other things I have to "
        "control for, because it correlates 0.937 with solar zenith. I simulated 800 passes and "
        "still only got to 0.395.",
    )

    p = para(doc, after=0)
    run(p, "Steps 4 to 14, built but not really run. ", bold=True)
    run(
        p,
        "I built all 102 remaining deliverables as clearly labelled demo versions with made-up "
        "data. They show that the code and the file formats work. They do not say anything about "
        "actual trees.",
    )

    # ---------------- page 2 ----------------
    heading(doc, "The grid you asked for, redone with v2 data", before=0, page_break=True)
    body(
        doc,
        "This is the grid from your review: demand along the bottom, water up the side, and n "
        "written in every box. It now holds 219 passes from five cities instead of 66 from "
        "Phoenix. One thing to flag is that v2 uses a climatic water balance on the y-axis instead "
        "of soil moisture, because the guide says not to treat reanalysis soil moisture as the "
        "water variable.",
    )

    p = para(doc, after=6)
    run(p, "One thing to watch: ", bold=True, color=PURPLE)
    run(
        p,
        "the shading is how many passes landed in each box, not how much cooling there was. There "
        "is no cooling number anywhere in v2 yet, which is what the blank panel B is showing.",
        color=PURPLE,
    )

    p = para(doc, after=6, align=WD_ALIGN_PARAGRAPH.CENTER)
    p.add_run().add_picture(str(FIG), width=Inches(5.7))

    heading(doc, "What it shows", before=3)
    bullet(
        doc,
        "The box where you expected the cooling to collapse, high demand and low water, actually "
        "has more data than anywhere else on the grid: 68 passes and 58.15 pass-equivalents.",
    )
    bullet(
        doc,
        "But the two corner boxes I would need to show it is really about water, and not just "
        "about heat, hold 26.17 and 0.55 pass-equivalents when I need 10.",
    )
    bullet(
        doc,
        "So even if I filled in the colours, I could not tell a water effect apart from an "
        "ordinary hot-day effect. Hot spells are dry spells, and throwing out cloudy days makes it "
        "worse, since the wetter days are the cloudy ones.",
    )

    heading(doc, "What I think this means")
    body(
        doc,
        "I do not think this is a wasted result, even though there is no cooling number in it. I "
        "roughly tripled the sample and the interaction still is not identifiable, and the reason "
        "is built into how the satellite works: the observations I would need are the ones a "
        "thermal sensor cannot take. To keep going I would need a different question that is not "
        "tangled up with solar geometry, or data from something other than clear-sky ECOSTRESS. I "
        "did not want to lower my own thresholds after seeing the result, so I stopped.",
        after=0,
    )

    p = para(doc, before=9, after=0)
    rule(p, edge="top")
    run(
        p,
        "Where this comes from: the figure and all the counts are from run R0015. The script that "
        "draws the grid imports the same classifier the pipeline uses, and it checks that it "
        "reproduces the published table exactly, 219 passes and 159.087 pass-equivalents, and "
        "errors out if it does not. The gate records are R0015 for Step 2 and R0016 / D0058 for "
        "Step 3.",
        size=7.5,
        italic=True,
        color=GREY,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
