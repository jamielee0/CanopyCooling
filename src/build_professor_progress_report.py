from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path("/Users/jmlee/Documents/TreeProject/project")
OUT = ROOT / "deliverables" / "Professor_Review_Urban_Tree_Cooling_Progress_2026-08-06_v2.docx"

F1_1 = ROOT / "data/processed/v2/task1/step1/figures/F1.1_joint_30d.png"
F1_2 = ROOT / "data/processed/v2/task1/step1/figures/F1.2_clear_sky_overlay.png"
F1_3 = ROOT / "data/processed/v2/task1/step1/figures/F1.3_corner_counts.png"
F1_4 = ROOT / "data/processed/v2/task1/step1/figures/F1.4_joint_60d.png"
F2_2 = ROOT / "data/processed/v2/task1/step2_definitive_l1b_geo_D0047_archive_available/figures/F2.2_usable_pass_heatmaps.png"
F3_1 = ROOT / "data/processed/v2/task1/step3_preliminary_ceiling/figures/F3.1_power_curves.png"
F3T_1 = ROOT / "data/processed/v2/task1/step3_time_of_day_only_D0056/figures/F3T.1_time_of_day_power.png"
F_PROF = ROOT / "figures/v2/prof_spec_support_grid/F_PROF.1_demand_water_support_grid.png"
F14_1 = ROOT / "figures/v2/illustrative_only/steps02_14/ILLUSTRATIVE_F14.1_PAPER_FIGURE_1_study_design.png"
F14_2 = ROOT / "figures/v2/illustrative_only/steps02_14/ILLUSTRATIVE_F14.2_PAPER_FIGURE_2_primary_result.png"
F14_3 = ROOT / "figures/v2/illustrative_only/steps02_14/ILLUSTRATIVE_F14.3_PAPER_FIGURE_3_hydroclimatic_surface.png"
F14_6 = ROOT / "figures/v2/illustrative_only/steps02_14/ILLUSTRATIVE_F14.6_PAPER_FIGURE_6_robustness.png"

BLUE = "2E74B5"
DARK_BLUE = "1F4D78"
PALE_BLUE = "EAF2F8"
GREEN = "237C4B"
PALE_GREEN = "E9F5EE"
AMBER = "B26A00"
PALE_AMBER = "FFF4D6"
RED = "A61B1B"
PALE_RED = "FDECEC"
GREY = "5B6573"
LIGHT_GREY = "F2F4F7"
MID_GREY = "D7DCE2"
WHITE = "FFFFFF"
BLACK = "1A1A1A"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=80, start=120, bottom=80, end=120) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for edge, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        tag = "w:" + edge
        node = tc_mar.find(qn(tag))
        if node is None:
            node = OxmlElement(tag)
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_cell_width(cell, width_dxa: int) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(width_dxa))
    tc_w.set(qn("w:type"), "dxa")


def set_table_width_and_grid(table, widths_dxa: list[int]) -> None:
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(sum(widths_dxa)))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_layout = tbl_pr.find(qn("w:tblLayout"))
    if tbl_layout is None:
        tbl_layout = OxmlElement("w:tblLayout")
        tbl_pr.append(tbl_layout)
    tbl_layout.set(qn("w:type"), "fixed")
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), "120")
    tbl_ind.set(qn("w:type"), "dxa")
    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths_dxa:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    for row in table.rows:
        for i, cell in enumerate(row.cells):
            set_cell_width(cell, widths_dxa[i])
            set_cell_margins(cell)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_keep_with_next(paragraph, value=True) -> None:
    paragraph.paragraph_format.keep_with_next = value


def set_cell_text(cell, text: str, *, bold=False, color=BLACK, size=8.6, align=WD_ALIGN_PARAGRAPH.LEFT) -> None:
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = align
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    r = p.add_run(text)
    r.bold = bold
    r.font.name = "Calibri"
    r.font.size = Pt(size)
    r.font.color.rgb = RGBColor.from_string(color)


def add_table(doc, headers: list[str], rows: list[list[str]], widths_dxa: list[int], *, font_size=8.6,
              status_col: int | None = None, header_fill=LIGHT_GREY):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    set_table_width_and_grid(table, widths_dxa)
    hdr = table.rows[0]
    set_repeat_table_header(hdr)
    for i, header in enumerate(headers):
        set_cell_shading(hdr.cells[i], header_fill)
        set_cell_text(hdr.cells[i], header, bold=True, color=DARK_BLUE, size=font_size)
    for row_data in rows:
        row = table.add_row()
        for i, value in enumerate(row_data):
            set_cell_text(row.cells[i], str(value), size=font_size)
            if status_col is not None and i == status_col:
                key = str(value).lower()
                if "complete" in key or "empirical" in key and "partial" not in key:
                    set_cell_shading(row.cells[i], PALE_GREEN)
                elif "partial" in key or "preliminary" in key:
                    set_cell_shading(row.cells[i], PALE_AMBER)
                elif "synthetic" in key or "not run" in key or "inactive" in key:
                    set_cell_shading(row.cells[i], PALE_RED)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return table


def set_run_font(run, name="Calibri", size=11, color=BLACK, bold=None, italic=None) -> None:
    run.font.name = name
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def add_body(doc, text: str, *, bold_prefix: str | None = None, color=BLACK, after=6, keep=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = 1.10
    p.paragraph_format.keep_together = keep
    if bold_prefix and text.startswith(bold_prefix):
        r1 = p.add_run(bold_prefix)
        set_run_font(r1, bold=True, color=color)
        r2 = p.add_run(text[len(bold_prefix):])
        set_run_font(r2, color=color)
    else:
        r = p.add_run(text)
        set_run_font(r, color=color)
    return p


def add_bullet(doc, text: str, level=0, color=BLACK):
    p = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    p.paragraph_format.left_indent = Inches(0.5 + 0.25 * level)
    p.paragraph_format.first_line_indent = Inches(-0.25)
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.line_spacing = 1.167
    r = p.add_run(text)
    set_run_font(r, color=color)
    return p


def create_numbering_id(doc: Document) -> int:
    numbering = doc.part.numbering_part.element
    abstract_ids = [int(el.get(qn("w:abstractNumId"))) for el in numbering.findall(qn("w:abstractNum"))]
    num_ids = [int(el.get(qn("w:numId"))) for el in numbering.findall(qn("w:num"))]
    abstract_id = max(abstract_ids, default=0) + 1
    num_id = max(num_ids, default=0) + 1

    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    multi = OxmlElement("w:multiLevelType")
    multi.set(qn("w:val"), "singleLevel")
    abstract.append(multi)
    lvl = OxmlElement("w:lvl")
    lvl.set(qn("w:ilvl"), "0")
    start = OxmlElement("w:start")
    start.set(qn("w:val"), "1")
    lvl.append(start)
    num_fmt = OxmlElement("w:numFmt")
    num_fmt.set(qn("w:val"), "decimal")
    lvl.append(num_fmt)
    lvl_text = OxmlElement("w:lvlText")
    lvl_text.set(qn("w:val"), "%1.")
    lvl.append(lvl_text)
    lvl_jc = OxmlElement("w:lvlJc")
    lvl_jc.set(qn("w:val"), "left")
    lvl.append(lvl_jc)
    p_pr = OxmlElement("w:pPr")
    tabs = OxmlElement("w:tabs")
    tab = OxmlElement("w:tab")
    tab.set(qn("w:val"), "num")
    tab.set(qn("w:pos"), "720")
    tabs.append(tab)
    p_pr.append(tabs)
    ind = OxmlElement("w:ind")
    ind.set(qn("w:left"), "720")
    ind.set(qn("w:hanging"), "360")
    p_pr.append(ind)
    lvl.append(p_pr)
    abstract.append(lvl)
    numbering.append(abstract)

    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    abs_ref = OxmlElement("w:abstractNumId")
    abs_ref.set(qn("w:val"), str(abstract_id))
    num.append(abs_ref)
    numbering.append(num)
    return num_id


def add_number(doc, text: str, num_id: int):
    p = doc.add_paragraph()
    p_pr = p._p.get_or_add_pPr()
    num_pr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    num_pr.append(ilvl)
    num_id_el = OxmlElement("w:numId")
    num_id_el.set(qn("w:val"), str(num_id))
    num_pr.append(num_id_el)
    p_pr.append(num_pr)
    p.paragraph_format.left_indent = Inches(0.5)
    p.paragraph_format.first_line_indent = Inches(-0.25)
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.line_spacing = 1.167
    r = p.add_run(text)
    set_run_font(r)
    return p


def add_heading(doc, text: str, level=1):
    p = doc.add_paragraph(style=f"Heading {level}")
    p.add_run(text)
    set_keep_with_next(p)
    return p


def add_kicker(doc, text: str, color=BLUE):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(5)
    r = p.add_run(text.upper())
    set_run_font(r, size=9, color=color, bold=True)
    r.font.small_caps = True
    return p


def add_callout(doc, title: str, text: str, *, fill=PALE_BLUE, border=BLUE, title_color=DARK_BLUE):
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    set_table_width_and_grid(table, [9360])
    cell = table.cell(0, 0)
    set_cell_shading(cell, fill)
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_borders = tc_pr.find(qn("w:tcBorders"))
    if tc_borders is None:
        tc_borders = OxmlElement("w:tcBorders")
        tc_pr.append(tc_borders)
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "12")
        el.set(qn("w:color"), border)
        tc_borders.append(el)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(title)
    set_run_font(r, size=11.5, color=title_color, bold=True)
    p2 = cell.add_paragraph()
    p2.paragraph_format.space_after = Pt(0)
    p2.paragraph_format.line_spacing = 1.10
    r2 = p2.add_run(text)
    set_run_font(r2, size=10.5, color=BLACK)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return table


def add_figure(doc, path: Path, label: str, caption: str, evidence: str, *, width=6.25):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_together = True
    p.add_run().add_picture(str(path), width=Inches(width))
    cap = doc.add_paragraph()
    cap.paragraph_format.space_before = Pt(0)
    cap.paragraph_format.space_after = Pt(4)
    cap.paragraph_format.keep_together = True
    r1 = cap.add_run(f"{label}. ")
    set_run_font(r1, size=9, color=DARK_BLUE, bold=True)
    r2 = cap.add_run(caption)
    set_run_font(r2, size=9, color=BLACK)
    src = doc.add_paragraph()
    src.paragraph_format.space_before = Pt(0)
    src.paragraph_format.space_after = Pt(8)
    src.paragraph_format.keep_together = True
    r3 = src.add_run(f"Evidence status: {evidence}. Source: {path.relative_to(ROOT)}")
    set_run_font(r3, size=8, color=GREY, italic=True)


def add_page_number(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run("Page ")
    set_run_font(run, size=8.5, color=GREY)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    paragraph._p.append(fld)


def add_hyperlink(paragraph, text, url, color=BLUE, underline=True):
    part = paragraph.part
    r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    new_run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    c = OxmlElement("w:color")
    c.set(qn("w:val"), color)
    r_pr.append(c)
    if underline:
        u = OxmlElement("w:u")
        u.set(qn("w:val"), "single")
        r_pr.append(u)
    new_run.append(r_pr)
    text_node = OxmlElement("w:t")
    text_node.text = text
    new_run.append(text_node)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)
    return hyperlink


def page_break(doc):
    p = doc.add_paragraph()
    p.paragraph_format.page_break_before = True
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)


def configure_document(doc: Document) -> None:
    sec = doc.sections[0]
    sec.page_width = Inches(8.5)
    sec.page_height = Inches(11)
    sec.top_margin = Inches(0.82)
    sec.bottom_margin = Inches(0.78)
    sec.left_margin = Inches(1.0)
    sec.right_margin = Inches(1.0)
    sec.header_distance = Inches(0.40)
    sec.footer_distance = Inches(0.40)

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.font.color.rgb = RGBColor.from_string(BLACK)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.10

    h1 = doc.styles["Heading 1"]
    h1.font.name = "Calibri"
    h1.font.size = Pt(16)
    h1.font.bold = True
    h1.font.color.rgb = RGBColor.from_string(BLUE)
    h1.paragraph_format.space_before = Pt(16)
    h1.paragraph_format.space_after = Pt(8)
    h1.paragraph_format.keep_with_next = True

    h2 = doc.styles["Heading 2"]
    h2.font.name = "Calibri"
    h2.font.size = Pt(13)
    h2.font.bold = True
    h2.font.color.rgb = RGBColor.from_string(BLUE)
    h2.paragraph_format.space_before = Pt(12)
    h2.paragraph_format.space_after = Pt(6)
    h2.paragraph_format.keep_with_next = True

    h3 = doc.styles["Heading 3"]
    h3.font.name = "Calibri"
    h3.font.size = Pt(12)
    h3.font.bold = True
    h3.font.color.rgb = RGBColor.from_string(DARK_BLUE)
    h3.paragraph_format.space_before = Pt(8)
    h3.paragraph_format.space_after = Pt(4)
    h3.paragraph_format.keep_with_next = True

    for style_name in ("List Bullet", "List Bullet 2", "List Number"):
        st = doc.styles[style_name]
        st.font.name = "Calibri"
        st.font.size = Pt(11)


def add_running_header_footer(doc: Document) -> None:
    sec = doc.sections[0]
    header = sec.header
    p = header.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run("URBAN TREE COOLING  |  PROFESSOR REVIEW REPORT")
    set_run_font(r, size=8.5, color=GREY, bold=True)
    bottom = OxmlElement("w:pBdr")
    border = OxmlElement("w:bottom")
    border.set(qn("w:val"), "single")
    border.set(qn("w:sz"), "6")
    border.set(qn("w:space"), "1")
    border.set(qn("w:color"), MID_GREY)
    bottom.append(border)
    p._p.get_or_add_pPr().append(bottom)

    footer = sec.footer
    fp = footer.paragraphs[0]
    fp.paragraph_format.space_before = Pt(0)
    add_page_number(fp)


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for p in (F1_1, F1_2, F1_3, F1_4, F2_2, F3_1, F14_1, F14_2, F14_3, F14_6):
        if not p.exists():
            raise FileNotFoundError(p)

    doc = Document()
    configure_document(doc)
    add_running_header_footer(doc)
    doc.core_properties.title = "Urban Tree Cooling Study: Progress, Deliverables, and Key Results"
    doc.core_properties.subject = "Professor review report"
    doc.core_properties.author = "TreeProject v2 analysis record"
    doc.core_properties.keywords = "urban tree cooling, ECOSTRESS, feasibility, progress report, reproducibility"

    # Cover
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(30)
    p.paragraph_format.space_after = Pt(10)
    r = p.add_run("URBAN TREE COOLING STUDY")
    set_run_font(r, size=11, color=BLUE, bold=True)
    r.font.letter_spacing = Pt(1.2)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run("Progress, Deliverables,\nand Key Results")
    set_run_font(r, size=28, color=DARK_BLUE, bold=True)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(26)
    r = p.add_run("Professor Review Report")
    set_run_font(r, size=16, color=GREY)

    add_callout(
        doc,
        "Canonical scientific status: STOP — feasibility chain complete, outcome negative",
        "The five-city feasibility chain is now finished end to end: Step 1, the full 911/911 geometry census, exhaustive cloud screening, exact-acquisition HRRR, definitive Step 2, and a definitive time-of-day Step 3. Two frozen gates returned STOP — the demand-by-dryness interaction is not estimable, and the time-of-day contrast is not adequately powered. No ECOSTRESS land-surface-temperature or thermal outcome was opened, no real held-out city was selected, and no 2026 observation was opened. Steps 4–14 remain workflow demonstrations.",
        fill=PALE_RED,
        border=RED,
        title_color=RED,
    )

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(22)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run("Prepared for academic review")
    set_run_font(r, size=11, color=GREY, bold=True)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run("Report date: 6 August 2026  |  Version 2.0 — supersedes v1.0 (partial-geometry state)")
    set_run_font(r, size=10.5, color=GREY)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run("Evidence window: summers 2018–2025; 2026 remains sealed")
    set_run_font(r, size=10.5, color=GREY)
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(16)
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run("Prepared from the frozen requirements, append-only decision log, Task 1 gate record, output manifests, and verified deliverables.")
    set_run_font(r, size=9.5, color=GREY, italic=True)

    page_break(doc)

    # Executive summary
    add_kicker(doc, "Executive summary")
    add_heading(doc, "What has been accomplished", 1)
    add_body(doc, "A reproducible five-city v2 study framework was built from the original step-by-step guide, and the entire pre-thermal feasibility chain has now been run on real data. Task 0 is complete; Step 1 is complete; Step 2 is complete through definitive geometry, cloud, exact-acquisition weather, and the final gate; Step 3 has a definitive time-of-day simulation; and every later guide deliverable was demonstrated in a strictly separated synthetic package.")
    add_callout(
        doc,
        "Bottom line for scientific interpretation",
        "The project contains no empirical estimate of urban tree cooling, and under the current design it cannot produce a defensible one. That conclusion is now a completed measurement rather than an open question. Two independent frozen gates failed: the demand-by-dryness interaction lacks the observations needed to identify it, and the time-of-day contrast is confounded with solar geometry severely enough that additional passes do not fix it. The scientific contribution presently available is a quantified sampling-and-identifiability finding for clear-sky thermal remote sensing.",
        fill=PALE_BLUE,
        border=BLUE,
    )

    add_heading(doc, "Key verified results", 2)
    exec_num_id = create_numbering_id(doc)
    add_number(doc, "Only Los Angeles and Minneapolis–St. Paul met the predeclared within-city support screen. The Step 1 decision is cross_city_separation_only, not a within-city interaction claim.", exec_num_id)
    add_number(doc, "Clear-sky availability is highly uneven: 68 of 976 summer days in Miami versus 697 of 976 in Phoenix. This sampling changes the diagnostic corner support directly.", exec_num_id)
    add_number(doc, "The real ECOSTRESS catalogue contains 2,968 unique physical city-orbit passes and a 1,055-pass daytime ceiling. Cloud-independent geometry then completed for all 911 archive-available candidates with zero unresolved, yielding 219 near-nadir passes and 159.087 cloud-weighted expected pass-equivalents.", exec_num_id)
    add_number(doc, "Definitive Step 2 passes all six implementation and data-integrity checks, but fails the frozen count-support gate: the low-demand/dry condition cell holds 0.553 expected pass-equivalents against a required minimum of 10. The demand-by-dryness interaction is therefore not estimable, and no transition-threshold claim is available.", exec_num_id)
    add_number(doc, "With the interaction dropped, time-of-day dependence became the sole primary objective. Its definitive simulation returns 0.110 power for the frozen 1.50 K contrast against a 0.80 requirement, and 0.100–0.145 under every permitted leave-one-city-out. The late-afternoon indicator is 99.42% predictable from the prespecified adjustment design (VIF 173.4), so an 800-pass panel still reaches only 0.395.", exec_num_id)
    add_number(doc, "No LST/thermal result, holdout result, or 2026 result exists. Any cooling curves, interaction surfaces, placebos, or robustness numbers in the Steps 3–14 package are synthetic demonstrations.", exec_num_id)

    add_heading(doc, "Evidence labels used throughout", 2)
    add_table(
        doc,
        ["Label", "Meaning", "May support a scientific finding?"],
        [
            ["Canonical empirical", "Real data; frozen rules; completed and checked", "Yes, within the stated preliminary scope"],
            ["Empirical partial", "Real nonthermal data or a durable processing checkpoint", "Only for availability/process facts; not cooling"],
            ["Preliminary simulation", "Code and planning validation using an uncertified count", "No; planning evidence only"],
            ["Synthetic demonstration", "Deterministic fabricated inputs and visibly labelled outputs", "No; schema/workflow demonstration only"],
        ],
        [1600, 4800, 2960],
        font_size=8.8,
        status_col=0,
    )

    page_break(doc)

    # Scope and governance
    add_kicker(doc, "Study foundation")
    add_heading(doc, "1. Study objective, scope, and guardrails", 1)
    add_body(doc, "The guide asks whether urban tree cooling depends on time of day and hydroclimatic context across Phoenix, Los Angeles, Atlanta, Minneapolis–St. Paul, and Miami. The v2 implementation translated the guide into a one-entry-per-deliverable specification, preserved the existing Phoenix pilot as a regression baseline, and created a separate analysis surface so legacy work was not overwritten.")

    add_heading(doc, "Task 0 — specification and guardrails", 2)
    add_body(doc, "Task 0 is complete. It normalized 109 unique guide deliverable IDs, resolved duplicated/malformed rows in the source document without relaxing scientific requirements, established an append-only decision log, and froze the gates that prevent an incomplete feasibility audit from being mistaken for an outcome study.")
    add_table(
        doc,
        ["Frozen element", "Implemented rule"],
        [
            ["Study domains", "One consistent rule: 2020 Census Urban Areas for all five cities; source and analysis geometry hashes recorded."],
            ["Time window", "Summers 2018–2025 for development and feasibility; the full 2026 season remains unopened."],
            ["Weather axes", "Demand from VPD; antecedent balance from prior-day-ending 30/60-day sums of precipitation minus reference ET; dryness is an explicit reversed percentile."],
            ["Sampling unit", "Pass is the effective unit for weather effects; pixels and matched sets remain clustered within pass."],
            ["Satellite timing", "Daytime is 10:00–18:00 local solar time, initially divided into four two-hour strata."],
            ["Geometry", "Near-nadir requires at least 95% domain coverage and 95th-percentile absolute view zenith no greater than 20°."],
            ["Blinding", "A held-out city is selected on quality evidence before thermal inspection; the holdout remains UNSELECTED."],
            ["Language", "The study uses ‘time-of-day dependence,’ not a same-day diurnal course or hysteresis claim."],
        ],
        [2200, 7160],
        font_size=8.8,
    )

    add_heading(doc, "Source hierarchy for this report", 2)
    add_body(doc, "When files differed in status or naming, this report treated the canonical requirements, the latest append-only decision, the Task 1 gate, and the authoritative run manifest as controlling. Figure appearance alone was never used to upgrade an artifact’s scientific status.")
    add_bullet(doc, "Source guide: StepByStep_Guide_Urban_Tree_Cooling.docx")
    add_bullet(doc, "Canonical requirements: docs/v2/REQUIREMENTS.md")
    add_bullet(doc, "Decision history: docs/v2/DECISION_LOG.md")
    add_bullet(doc, "Active gate: data/processed/v2/task1/TASK1_GATE.md")
    add_bullet(doc, "Illustrative package manifest: data/processed/v2/illustrative_only/steps02_14/run_manifest.json")

    page_break(doc)

    # Completion dashboard
    add_kicker(doc, "Completion dashboard")
    add_heading(doc, "2. What is complete, partial, demonstrated, and not run", 1)
    add_body(doc, "The table below is the shortest accurate summary of the entire guide. ‘Demonstrated’ means that the expected file structure, calculation path, and presentation were exercised with synthetic inputs; it does not mean the empirical analysis was performed.")
    add_table(
        doc,
        ["Stage", "Status / evidence", "Accomplished", "Still required"],
        [
            ["Task 0", "Complete — canonical", "Separate v2 surface; normalized requirements; frozen domains, rules, gates, and decision log.", "Nothing material for Task 0."],
            ["Step 1", "Complete — empirical", "F1.1–F1.4, T1.1–T1.2, M1.1; five cities, eight summers, 4,880 city-days; QA completed.", "Must later be superseded by acquisition-time usable-pass conditions."],
            ["Step 2", "Complete — empirical; gate STOP", "Catalogue, 911/911 L1B GEO geometry, exhaustive official cloud over 219 near-nadir passes, 413/413 exact-acquisition HRRR hours, F2.1–F2.5, T2.1–T2.3; all six checks pass.", "Nothing further under this design. The count-support gate failed at 0.553 pass-equivalents in the low-demand/dry cell."],
            ["Step 3", "Complete — empirical; gate STOP", "Definitive pass-clustered time-of-day simulation on the real 102-pass template; 8 of 11 required checks pass.", "Nothing further under this design. Power is 0.110 against 0.80 and cannot be raised by adding passes."],
            ["Task 2", "Inactive / not run", "No canonical Task 2 input was opened.", "Requires canonical Task 1 PASS and preflight."],
        ],
        [900, 1650, 3500, 3310],
        font_size=8.1,
        status_col=1,
    )

    add_heading(doc, "Steps 4–14", 2)
    add_table(
        doc,
        ["Step", "Demonstrated output", "Empirical work not yet done"],
        [
            ["4", "Native-grid thermal archive, QA layers, histograms, valid counts, band-mode and geolocation schemas.", "No real v2 LST archive or Step 4 source checks."],
            ["5", "Albedo, vegetation-fusion error, radiation, ET/ESI comparisons and inventories.", "No real supporting-product chain or estimates."],
            ["6", "Exact-time meteorology, station validation, HRRR/ERA5 comparison, interpolation and correlations.", "No definitive exact-acquisition HRRR chain."],
            ["7", "Optical timing, image lag, canopy change, land-cover vintages and focal/buffer urban form.", "No empirical multi-city optical/land-cover archive."],
            ["8", "Canopy thresholds, classification, matching balance, registration sensitivity and validation.", "No outcome-blind empirical classifier/matching freeze."],
            ["9", "Analysis-table schema, missingness, distributions, completeness, irrigation evidence and dictionaries.", "No canonical matched-set-by-pass empirical table."],
            ["10", "Time-of-day models, common support, endpoint forest, day/night separation and diagnostics.", "No empirical cooling estimate."],
            ["11", "Leave-one-simulated-city-out checks, quality panels, canopy standardization and holdout schema.", "No real holdout selection or generalization result."],
            ["12", "Demand × dryness surfaces, support masking, slices, model comparisons and transition criteria.", "No empirical surface or threshold claim."],
            ["13", "Placebo, night, sensitivity, radiative attenuation and uncertainty-budget workflows.", "No empirical robustness or detection-limit comparison."],
            ["14", "Six synthetic paper layouts; real STOP memo; confirmatory NOT RUN report; hashed package inventory.", "No empirical manuscript, holdout/2026 confirmation, public scientific release or independent rebuild."],
        ],
        [800, 4350, 4210],
        font_size=8.0,
        status_col=None,
    )

    add_callout(
        doc,
        "Coverage of the source guide",
        "Artifacts occupy all 109 normalized guide ID slots: 7 canonical Step 1 deliverables plus 102 Step 2–14 package IDs. Coverage of an ID proves that the workflow and expected deliverable structure exist; only the evidence label determines whether it is an empirical scientific result.",
        fill=PALE_AMBER,
        border=AMBER,
        title_color=AMBER,
    )

    page_break(doc)

    # Step 1
    add_kicker(doc, "Canonical empirical evidence")
    add_heading(doc, "3. Step 1 — five-city weather-condition feasibility", 1)
    add_body(doc, "Step 1 is the only fully completed empirical scientific stage. It asks whether atmospheric demand and antecedent climatic dryness occupy enough independent combinations to support later interaction analyses. It does not use or estimate land-surface temperature.")
    add_callout(
        doc,
        "Step 1 decision: cross_city_separation_only",
        "The predeclared strong case required adequate clear-sky corner support in at least three cities. Only Los Angeles and Minneapolis–St. Paul passed. The current recommendation is a cross-city/common-support comparison, with an explicit city-confounding limitation and consideration of an additional city.",
        fill=PALE_BLUE,
        border=BLUE,
    )

    add_heading(doc, "City domains and clear-sky availability", 2)
    add_table(
        doc,
        ["City", "Census UA", "Area (km²)", "Summer days", "Clear days", "Clear %"],
        [
            ["Atlanta", "03817", "6,612.80", "976", "133", "13.63%"],
            ["Los Angeles", "51445", "4,242.65", "976", "659", "67.52%"],
            ["Miami", "56602", "3,223.01", "976", "68", "6.97%"],
            ["Minneapolis–St. Paul", "57628", "2,628.48", "976", "263", "26.95%"],
            ["Phoenix", "69184", "2,876.31", "976", "697", "71.41%"],
        ],
        [2100, 1000, 1500, 1500, 1500, 1760],
        font_size=8.8,
    )

    add_heading(doc, "Thirty-day feasibility result", 2)
    add_table(
        doc,
        ["City", "High-demand / wet", "Low-demand / dry", "Combined share", "Clear-sky Spearman ρ (95% CI)", "Within-city support"],
        [
            ["Atlanta", "11", "2", "9.8%", "0.534 (0.249–0.714)", "No"],
            ["Los Angeles", "53", "29", "12.4%", "0.321 (0.135–0.452)", "Yes"],
            ["Miami", "2", "2", "5.9%", "0.328 (0.048–0.613)", "No"],
            ["Minneapolis–St. Paul", "31", "5", "13.7%", "0.540 (0.201–0.678)", "Yes"],
            ["Phoenix", "29", "14", "6.2%", "0.524 (0.421–0.593)", "No"],
        ],
        [1750, 1300, 1200, 1250, 2300, 1560],
        font_size=8.5,
    )
    add_body(doc, "The clear-sky screen used Census-domain mean ERA5 total cloud cover at the hour nearest 14:00 local solar time, with a frozen threshold of 0.25. Spearman intervals use whole-summer blocks rather than treating individual days as independent.")

    page_break(doc)
    add_kicker(doc, "Step 1 visual evidence")
    add_heading(doc, "Clear-sky sampling changes the available joint support", 1)
    add_figure(
        doc,
        F1_2,
        "Figure 1 (F1.2)",
        "Thirty-day atmospheric-demand and antecedent-dryness support across five cities. All summer days are grey and likely clear-sky days are blue; the shaded off-diagonal corners are the diagnostic cells. Clear-sky filtering substantially thins support in Atlanta, Miami, and Phoenix.",
        "Canonical empirical meteorological screening; no thermal outcome",
        width=6.35,
    )
    add_body(doc, "The figure shows why a simple ‘hot versus dry’ interaction is difficult to identify within several cities: demand and dryness are positively correlated, and the rare off-diagonal combinations become even thinner after clear-sky selection. Los Angeles and Minneapolis–St. Paul retain the best within-city support, but the five-city panel does not satisfy the strong three-city rule.")

    add_figure(
        doc,
        F1_3,
        "Figure 2 (F1.3)",
        "Proportions in the two diagnostic corner cells before and after likely clear-sky sampling, with Wilson 95% confidence intervals. These bars describe sampling support, not tree-cooling effects.",
        "Canonical empirical meteorological screening; no thermal outcome",
        width=6.35,
    )

    page_break(doc)
    add_kicker(doc, "Step 1 sensitivity and QA")
    add_heading(doc, "Thirty-day versus sixty-day antecedent windows", 1)
    add_body(doc, "The ≥10% combined corner-share diagnostic changes in three cities between the required 30- and 60-day windows. This is not the full within-city support rule (≥5 days per corner and |ρ|<0.8), so window choice remains a declared sensitivity.")
    add_table(
        doc,
        ["City", "30-day clear-sky corner share", "60-day share", "≥10% share status stable?"],
        [
            ["Atlanta", "9.8%", "11.3%", "No"],
            ["Los Angeles", "12.4%", "12.9%", "Yes"],
            ["Miami", "5.9%", "20.6%", "No"],
            ["Minneapolis–St. Paul", "13.7%", "7.2%", "No"],
            ["Phoenix", "6.2%", "8.2%", "Yes"],
        ],
        [2300, 2500, 1700, 2860],
        font_size=8.8,
    )
    add_figure(
        doc,
        F1_4,
        "Figure 3 (F1.4)",
        "Sixty-day sensitivity version of the five-city joint-support figure. Its differences from the 30-day screen are carried forward as a design sensitivity rather than resolved by selecting a preferred window.",
        "Canonical empirical meteorological sensitivity; no thermal outcome",
        width=5.70,
    )

    add_heading(doc, "Quality checks and documented limitation", 2)
    add_bullet(doc, "Step 1 contains 4,880 unique city-date rows: 976 summer days for each of five cities across eight summers.")
    add_bullet(doc, "Unit, percentile, cell-count, bootstrap, permutation, figure, and geometry-validity checks were completed; the repair changed no clear-day, cell, corner, or gate result.")
    add_bullet(doc, "The analysis used 2,000 whole-summer bootstrap draws and 2,000 permutations with seed 20260801.")
    add_bullet(doc, "Phoenix’s 30-day balance was negative in June in all 8 summers, but July’s median rose above June’s in only 3 of 8. The sign check passed; the stricter annual monsoon-rise diagnostic did not.")

    page_break(doc)

    # Step 2
    add_kicker(doc, "Empirical but incomplete")
    add_heading(doc, "4. Step 2 — satellite catalogue, quality screening, and geometry remediation", 1)
    add_body(doc, "Step 2 was intended to replace the daily weather screen with the actual conditions sampled by usable ECOSTRESS passes. Substantial real-data work was completed, but the definitive usable-pass total does not exist because the cloud-independent geometry audit was stopped before completion.")

    add_heading(doc, "Catalogue results", 2)
    add_table(
        doc,
        ["City", "Daytime catalogue-ceiling passes"],
        [
            ["Atlanta", "213"],
            ["Los Angeles", "212"],
            ["Miami", "120"],
            ["Minneapolis–St. Paul", "298"],
            ["Phoenix", "212"],
            ["Total", "1,055"],
        ],
        [6200, 3160],
        font_size=9.0,
    )
    add_body(doc, "The live search returned 13,577 tiled granules. Provenance-preserving deduplication reduced these to 2,968 physical city-orbit passes, of which 1,055 fell between 10:00 and 18:00 local solar time. Definitive geometry and cloud screening then reduced that daytime ceiling to 219 retained near-nadir passes carrying 159.087 expected pass-equivalents.")
    add_figure(
        doc,
        F2_2,
        "Figure 4 (definitive F2.2)",
        "Usable near-nadir passes by city and year, and by city and local-solar-time stratum, after the complete geometry and cloud screen. These are the counts every later power and support calculation rests on.",
        "Canonical empirical Step-2 output; nonthermal",
        width=6.35,
    )

    page_break(doc)
    add_kicker(doc, "Step 2 remediation record")
    add_heading(doc, "Why the first quality count was rejected", 1)
    add_body(doc, "An initial tiled-product screen left 107 nominal pre-cloud candidates. The exhaustive audit then found that tiled view angle was not cloud independent: across 127 cloud-bearing layer pairs, all 400,414 cloudy pixels had invalid tiled view_zenith values. The earlier 95% view-coverage rule therefore partly measured retrieval availability rather than physical geometry. The provisional expected total of 106.4273 pass-equivalents (floor 106) was retained only as failed diagnostic evidence and was not used as a certified count.")

    add_heading(doc, "Cloud-independent L1B GEO remediation", 2)
    add_table(
        doc,
        ["Checkpoint fact", "Verified value", "Interpretation"],
        [
            ["Original metadata candidates", "942", "Required cloud-independent geometry census under the original rule."],
            ["Exact GEO scene identities", "1,370", "Mission-exact orbit/scene identities resolved from frozen provenance."],
            ["Available / unavailable exact scenes", "1,329 / 41", "Forty-one official objects repeatedly returned 404 while controls succeeded."],
            ["Candidate passes affected", "31", "Excluded before geometry only under the separately approved archive-available profile."],
            ["Archive-available candidates", "911", "Revised estimand; missing scenes were not imputed or replaced."],
            ["Geometry evaluated", "911 / 911", "Completed with zero unresolved candidates; the earlier 710-candidate checkpoint was superseded."],
            ["Near-nadir passes retained", "219", "Passed the frozen 95% coverage and 20° p95 view-zenith rule on cloud-independent geometry."],
            ["Expected pass-equivalents", "159.087", "Exhaustive official cloud fractions, no extrapolation between cities, months, or years."],
            ["Exact-acquisition HRRR hours", "413 / 413", "Four 2018 surface objects absent from the NOAA archive were resolved from the same-cycle official pressure product."],
        ],
        [2600, 1600, 5160],
        font_size=8.5,
    )

    add_callout(
        doc,
        "Active gate: STOP — definitive Step 2 count support",
        "All six Step-2 implementation and data-integrity checks pass, and all 394 post-transition daytime passes carry official five-band metadata. The gate nevertheless fails on frozen count support: demand_low__antecedent_dry holds 0.553 expected pass-equivalents against the required minimum of 10, while demand_high__antecedent_wet holds 26.168. Without both off-diagonal corners the demand-by-dryness interaction cannot be separated from a demand main effect, so no definitive interaction, three-way, or transition-threshold model is permitted.",
        fill=PALE_RED,
        border=RED,
        title_color=RED,
    )

    add_figure(
        doc,
        F_PROF,
        "Figure 4b (condition support, review-specified axes)",
        "The advisory review's demand-by-water grid, rebuilt on the definitive v2 sample. Shading is the number of usable satellite passes, not cooling — no cooling value exists. The corner where the review expected a cooling collapse (high demand, low water) is the best-sampled cell on the plane at 68 passes, but the two off-diagonal corners needed to attribute a collapse to water rather than demand hold 26.17 and 0.55 pass-equivalents against a minimum of 10.",
        "Canonical empirical Step-2 output; nonthermal",
        width=6.35,
    )

    add_heading(doc, "The 41 unavailable GEO objects", 2)
    add_body(doc, "The project repeatedly attempted exact CMR searches, canonical HDF5/DMR++/OPeNDAP endpoints, and authenticated eight-byte HDF5 signature reads. Known-good sibling controls succeeded before and after the batches, while all 41 targets returned HTTP 404. A renewed Earthdata token produced the same result, ruling out token expiry. The missing objects affect 31 candidates—24 in 2020 and 7 in 2024—and were never assigned zero coverage, imputed, or replaced with adjacent scenes. The append-only decision log records that an LP DAAC restoration/re-indexing request was sent with the exact evidence packet; no external delivery receipt is stored in the repository.")
    add_table(
        doc,
        ["City", "Archive-unavailable candidate exclusions"],
        [["Atlanta", "8"], ["Los Angeles", "8"], ["Miami", "1"], ["Minneapolis–St. Paul", "8"], ["Phoenix", "6"]],
        [6200, 3160],
        font_size=9.0,
    )

    page_break(doc)

    # Step 3
    add_kicker(doc, "Planning and code validation")
    add_heading(doc, "5. Step 3 — definitive time-of-day simulation", 1)
    add_body(doc, "Because Step 2 removed the hydroclimatic interaction from the estimable set, the study retained the five-city panel and made time-of-day dependence the sole primary objective — the guide's own predeclared fallback and the endpoint it describes as most likely to succeed. A definitive pass-clustered simulation was then run against the real checksum-bound pass template before any thermal value was opened. It is a genuine gate, not a planning exercise.")
    add_table(
        doc,
        ["Required check", "Result", "Threshold", "Verdict"],
        [
            ["Full-panel power, 1.50 K contrast", "0.110", "at least 0.800", "Fail"],
            ["Power excluding Atlanta", "0.100", "at least 0.800", "Fail"],
            ["Power excluding Los Angeles", "0.145", "at least 0.800", "Fail"],
            ["Power excluding Miami", "0.140", "at least 0.800", "Fail"],
            ["Power excluding Minneapolis–St. Paul", "0.100", "at least 0.800", "Fail"],
            ["Pooled zero-effect rejection rate", "0.090", "at most 0.100; interval must contain 0.050", "Fail"],
            ["Pass-block interval coverage", "0.983", "at least 0.900", "Pass"],
            ["Pass-block minus naive-row coverage", "0.467", "at least 0.100", "Pass"],
            ["Large-sample coefficient bias", "0.024–0.087 K", "at most 0.200 K", "Pass"],
        ],
        [3100, 1700, 2700, 1860],
        font_size=8.3,
        status_col=3,
    )
    add_figure(
        doc,
        F3T_1,
        "Figure 5 (definitive F3T.1)",
        "Detection probability for the late-afternoon minus late-morning cooling contrast against simulated pass counts. The observed floor of 72 pass-equivalents sits far below the count any effect size would require, and the curves flatten well short of 0.80.",
        "Canonical empirical simulation on the real pass template; no thermal value opened",
        width=5.45,
    )
    add_callout(
        doc,
        "Why more data does not fix this",
        "The failure is identification, not sample size. Regressing the late-afternoon indicator on city, demand, antecedent dryness, solar zenith, solar-azimuth sine and cosine, and day of year gives R² = 0.9942, a variance-inflation factor of 173.4; the indicator correlates 0.937 with solar zenith and −0.968 with solar-azimuth sine. Because ECOSTRESS observes different local times on different dates, additional rows inside the same passes add no independent time-or-geometry support. Even the 800-pass simulation scenario reaches only 0.395 power at 1.50 K and 0.730 at 2.25 K.",
        fill=PALE_AMBER,
        border=AMBER,
        title_color=AMBER,
    )
    add_bullet(doc, "Eight of eleven required checks pass; the inference machinery itself is validated — pass-block intervals are correctly conservative relative to naive row-level intervals, and coefficient recovery is unbiased at large counts.")
    add_bullet(doc, "All four permitted leave-one-city-out branches fail power, so the result is not an artifact of the planned holdout choice.")
    add_bullet(doc, "Recovering this endpoint would require a redesign with independent time-of-day and solar-geometry support, or an additional observation source. Dropping the solar-geometry controls or relaxing the thresholds after seeing this result is barred by decision D0058.")

    page_break(doc)

    # Illustrative package
    add_kicker(doc, "Quarantined workflow demonstration")
    add_heading(doc, "6. Steps 4–14 — what the illustrative package accomplishes", 1)
    add_callout(
        doc,
        "Synthetic content is not a study result",
        "While the geometry run was still incomplete, the remaining guide was completed as a deterministic, offline demonstration under illustrative_only/steps02_14. The package shows expected schemas, figures, model outputs, checks, and reporting structure without opening LST/thermal data, selecting a holdout, opening 2026, or activating Task 2. Geometry has since finished, but that does not upgrade any of this content: it remains synthetic and gate-ineligible.",
        fill=PALE_RED,
        border=RED,
        title_color=RED,
    )
    add_table(
        doc,
        ["Workflow block", "What was demonstrated", "Review value"],
        [
            ["Steps 4–6: data products and weather", "Native-grid archive structure; masking and QA; albedo/ET/radiation; exact-time meteorology and station comparisons.", "Lets a reviewer inspect variable definitions, expected checks, and failure handling before expensive downloads."],
            ["Steps 7–9: land cover and analysis table", "Optical timing; canopy change; thresholding and classification; matching balance; registration sensitivity; analysis-table schema.", "Shows how leakage, classification error, covariate imbalance, and missingness would be audited."],
            ["Steps 10–12: primary and interaction models", "Time-of-day estimates; common support; city pooling; leave-one-city-out; demand × dryness surfaces; transition-model criteria.", "Demonstrates the planned inferential presentation and masks unsupported regions."],
            ["Steps 13–14: robustness and reporting", "Placebo/night tests; sensitivity tornado; uncertainty budget; six paper layouts; STOP memo; confirmatory NOT RUN protocol; package inventory.", "Makes the final decision logic and reporting discipline reviewable before empirical outcome access."],
        ],
        [1900, 3900, 3560],
        font_size=8.5,
    )

    add_heading(doc, "Package completeness and reproducibility", 2)
    add_bullet(doc, "102/102 unique Step 2–14 guide IDs present.")
    add_bullet(doc, "120 non-manifest artifacts: 72 visibly labelled figures and 40 origin-labelled CSV tables, plus memos and package records.")
    add_bullet(doc, "All synthetic outputs use seed 20260805 and are package-indexed as gate-ineligible; tables are origin-labelled and marked canonical_eligible=false.")
    add_bullet(doc, "The authoritative manifest records SHA-256 hashes for every non-manifest artifact; source inventory contains 20 hashed code/governance entries.")
    add_bullet(doc, "Manifest SHA-256: 9027f655a9a611c2ee8c6e6e2c17f1a0c5078b670141e9d941496c44c50d7642.")
    add_bullet(doc, "Release archive SHA-256: e457fca0bd26af69115dead7730105ae0fabca518a1c9b7a2d4fa803775a64f2.")

    add_heading(doc, "Illustrative numbers that must not be cited as findings", 2)
    add_body(doc, "For example, the synthetic endpoint table contains a fabricated equal-city late-minus-morning contrast of 0.7355 K (synthetic interval 0.6280–0.8430 K), and the synthetic robustness workflow contains a 0.057 K pavement placebo and −0.715 K night contrast. These values prove only that reporting and sensitivity code paths work. They are not estimates for Phoenix or any other real city.")

    page_break(doc)
    add_kicker(doc, "Illustrative output examples")
    add_heading(doc, "Planned study design and primary-result format", 1)
    add_figure(
        doc,
        F14_1,
        "Figure 6 (illustrative F14.1)",
        "Synthetic roadmap of the intended multi-city matched comparison: generic domains, separation of tree and reference canopy fractions, and nominal local-time coverage.",
        "Fully synthetic conceptual illustration; no empirical evidentiary value",
        width=6.35,
    )
    add_figure(
        doc,
        F14_2,
        "Figure 7 (illustrative F14.2)",
        "Synthetic format for city-specific and pooled cooling contrasts across local-solar-time strata. The apparent later-day increase and every uncertainty interval are fabricated.",
        "Fully synthetic primary-result mock-up; no thermal data opened",
        width=6.35,
    )

    page_break(doc)
    add_kicker(doc, "Illustrative output examples")
    add_heading(doc, "Planned interaction and support display", 1)
    add_figure(
        doc,
        F14_3,
        "Figure 8 (illustrative F14.3)",
        "Synthetic crown-area-by-moisture-deficit response surfaces for four local-time strata. Grey cells demonstrate the rule that unsupported regions must be masked rather than interpreted.",
        "Fully synthetic interaction-surface mock-up",
        width=5.45,
    )
    add_body(doc, "This display is useful because it shows the intended guardrail, not because of its colors: every real surface cell would require adequate independent-pass support before it could contribute to a threshold or interaction claim.")

    page_break(doc)
    add_kicker(doc, "Illustrative output examples")
    add_heading(doc, "Planned robustness dashboard", 1)
    add_figure(
        doc,
        F14_6,
        "Figure 9 (illustrative F14.6)",
        "Synthetic robustness dashboard covering a placebo, day/night comparison, leave-one-city-out stability, and an uncertainty budget. Every point, interval, and contribution is fabricated.",
        "Fully synthetic robustness-summary mock-up",
        width=5.45,
    )
    add_body(doc, "The final empirical study would need all four classes of evidence to behave coherently: a near-zero placebo, an interpretable day/night pattern, city-robust estimates, and an effect that is honestly compared with the combined detection limit.")

    page_break(doc)

    # QA and limitations
    add_kicker(doc, "Auditability")
    add_heading(doc, "7. Quality assurance and reproducibility record", 1)
    add_table(
        doc,
        ["Area", "Completed evidence"],
        [
            ["Requirements control", "One normalized registry; scientific cautions retained; gates and open decisions explicit."],
            ["Decision provenance", "Append-only decisions D0001–D0052 and runs R0001–R0013; superseded evidence retained rather than overwritten."],
            ["Domain provenance", "Official Census Urban Area identifiers, geometry hashes, repaired analysis hashes, areas and tile intersections recorded."],
            ["Step 1 inference", "Whole-summer bootstrap and permutation units; exact cell identities; unit and percentile checks; window sensitivity; figure review."],
            ["Satellite provenance", "Exact scene identities, official endpoints, byte-range controls, checksums and durable checkpoints recorded without exposing credentials."],
            ["Failure discipline", "Missing scenes failed closed; no imputation or adjacent-scene substitution; invalid cloud-conditioned geometry count was rejected."],
            ["Automated verification", "R0013 passed 139/139 v2 tests and all 17 isolated legacy test programs."],
            ["Packaging", "All illustrative artifacts hashed; 20-entry source inventory and rebuild instructions included."],
        ],
        [2400, 6960],
        font_size=8.7,
    )
    add_callout(
        doc,
        "What the testing record does—and does not—prove",
        "The tests provide strong evidence that the implemented schemas, gates, deterministic calculations, and package bookkeeping behave as intended. They cannot substitute for the missing geometry/cloud census, empirical thermal data, real holdout selection, or 2026 confirmation.",
        fill=PALE_AMBER,
        border=AMBER,
        title_color=AMBER,
    )

    add_heading(doc, "No-result safeguards preserved", 2)
    add_bullet(doc, "No ECOSTRESS LST or thermal value was opened in Task 1 or the illustrative continuation.")
    add_bullet(doc, "The held-out city remains UNSELECTED; synthetic sim_city labels do not select a real city.")
    add_bullet(doc, "The full 2026 record remains unopened.")
    add_bullet(doc, "Task 2 remains inactive and the confirmatory report is explicitly NOT RUN.")
    add_bullet(doc, "No synthetic value is eligible for manuscript, causal, policy, or confirmatory interpretation.")

    page_break(doc)
    add_kicker(doc, "Scientific limits")
    add_heading(doc, "8. What can and cannot be concluded now", 1)
    add_table(
        doc,
        ["Supported conclusion", "Unsupported conclusion"],
        [
            ["The five-city weather screen has uneven and often thin clear-sky off-diagonal support.", "Trees have a measured cooling effect of any magnitude in the v2 study."],
            ["Only two cities pass the predeclared within-city weather-support screen.", "Cooling increases later in the day; the plotted later-day increase is synthetic."],
            ["The catalogue supplies broad nominal time coverage, but usable-pass totals remain unknown.", "The 1,055-pass catalogue ceiling is the effective empirical sample size."],
            ["The tiled view-angle screen was cloud-conditioned and correctly rejected.", "The provisional 106-pass floor is a valid or conservative usable-pass count."],
            ["Exact GEO archive gaps are real at the tested endpoints and not caused by token expiry.", "The 41 objects never existed or will never be restored."],
            ["The downstream package demonstrates a coherent analysis and reporting workflow.", "Placebo, night, interaction, radiative, sensitivity or holdout checks passed empirically."],
        ],
        [4680, 4680],
        font_size=8.8,
    )
    add_callout(
        doc,
        "Current scientific recommendation",
        "The feasibility chain is finished and both frozen gates returned STOP, so the decision now belongs to the supervisor rather than to further computation. Three defensible options exist: write up the sampling-and-identifiability result as the contribution; redesign for an endpoint that clear-sky ECOSTRESS can actually identify; or authorise a strictly descriptive thermal look, recorded in advance, accepting that it ends the blind-method claim. Continuing the original design unchanged is not among them.",
        fill=PALE_BLUE,
        border=BLUE,
    )

    page_break(doc)

    # Next steps
    add_kicker(doc, "Path to a canonical result")
    add_heading(doc, "9. Required next work", 1)
    next_num_id = create_numbering_id(doc)
    add_body(doc, "Every computational item from the previous version of this report is now complete: geometry finished 911/911, cloud screening covered all 219 near-nadir passes, exact-acquisition HRRR completed 413/413 hours, and both definitive gates were issued. The remaining work is a supervisory decision, not further processing.")
    add_number(doc, "Decide the study's direction. The feasibility chain cannot be advanced by more computation under the present design, so the next move is a scientific choice about scope and endpoint.", next_num_id)
    add_number(doc, "If writing up the feasibility result: draft the sampling-and-identifiability paper around F1.2/F1.3, the condition-support grid, and the Step-3 power and concurvity diagnostics. This requires no further data access.", next_num_id)
    add_number(doc, "If redesigning: identify an endpoint whose contrast is not collinear with solar geometry, or an observation source that breaks the time-of-day/zenith confound. Record the new design before any thermal value is opened.", next_num_id)
    add_number(doc, "If a descriptive thermal look is wanted: freeze a pre-outcome decision stating that it is descriptive only and not a confirmatory result, then open LST for the 219 retained passes. This permanently ends the blind-method claim, including for the held-out city.", next_num_id)
    add_number(doc, "Keep the holdout unselected and 2026 sealed until whichever path is chosen has an approved, written design.", next_num_id)
    add_number(doc, "If LP DAAC restores the 41 objects, rerun the original 942-candidate exhaustive census as a separately versioned sensitivity analysis.", next_num_id)

    add_heading(doc, "What each path costs and yields", 2)
    add_table(
        doc,
        ["Path", "Cost", "What it yields"],
        [
            ["Write up feasibility", "No new data; writing time only.", "A defensible methods contribution: quantified clear-sky sampling bias and a solar-geometry identifiability limit for ECOSTRESS time-of-day studies."],
            ["Redesign the endpoint", "New design work and a further feasibility pass.", "A route back to a cooling estimate, if an identifiable contrast exists."],
            ["Descriptive thermal look", "Ends blind-method status permanently.", "Exploratory figures only; no confirmatory claim, and the holdout can no longer serve as one."],
            ["Continue unchanged", "Not available.", "Barred by D0058; would produce estimates that cannot survive review."],
        ],
        [1700, 2900, 4760],
        font_size=8.5,
        status_col=0,
    )

    page_break(doc)

    # Review index
    add_kicker(doc, "Professor review index")
    add_heading(doc, "10. Most important files and deliverables", 1)
    add_body(doc, "The following files are the smallest review set that reconstructs the current scientific state. Paths are relative to the project root unless shown otherwise.")
    add_table(
        doc,
        ["Review purpose", "Primary file"],
        [
            ["Controlling scientific requirements", "docs/v2/REQUIREMENTS.md"],
            ["Complete decision and run history", "docs/v2/DECISION_LOG.md"],
            ["Current canonical gate", "data/processed/v2/task1/TASK1_GATE.md"],
            ["Step 1 recommendation", "data/processed/v2/task1/step1/memos/M1.1_feasibility_gate.md"],
            ["Step 1 city/cell statistics", "data/processed/v2/task1/step1/tables/T1.1_city_cell_counts.csv"],
            ["Step 1 domain record", "data/processed/v2/task1/step1/tables/T1.2_city_domains.csv"],
            ["Step 2 catalogue counts", "data/processed/v2/task1/step2_catalogue_audit/tables/T2.1_daytime_catalogue_ceiling_counts.csv"],
            ["Definitive Step 2 gate and checks", "data/processed/v2/task1/step2_definitive_l1b_geo_D0047_archive_available/step2_gate_record.json"],
            ["Definitive Step 2 feasibility memo", "data/processed/v2/task1/step2_definitive_l1b_geo_D0047_archive_available/step2_definitive_feasibility.md"],
            ["Definitive Step 3 gate", "data/processed/v2/task1/step3_time_of_day_only_D0056/step3_time_of_day_gate.json"],
            ["Step 3 stop report", "docs/v2/D0058_TIME_OF_DAY_STEP3_STOP.md"],
            ["Illustrative-package explanation", "data/processed/v2/illustrative_only/steps02_14/README.md"],
            ["Authoritative artifact manifest", "data/processed/v2/illustrative_only/steps02_14/run_manifest.json"],
            ["Step 14 scientific STOP memo", "data/processed/v2/illustrative_only/steps02_14/ILLUSTRATIVE_M14.1_go_adjust_stop_memo.md"],
            ["Confirmatory status", "data/processed/v2/illustrative_only/steps02_14/ILLUSTRATIVE_M14.2_confirmatory_report_NOT_RUN.md"],
        ],
        [2800, 6560],
        font_size=8.3,
    )

    add_heading(doc, "Delivered packages", 2)
    add_body(doc, "Local release archive: deliverables/illustrative_steps02_14_D0052_2026-08-06.zip")
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run("Google Drive package folder: ")
    set_run_font(r, size=10.5, color=BLACK, bold=True)
    add_hyperlink(p, "Open the Steps 2–14 package", "https://drive.google.com/drive/folders/1l-cC0hCnsEqBJjm63h54TIxYeedL2H9a")

    add_heading(doc, "Step 1 deliverable set", 2)
    add_table(
        doc,
        ["ID", "File", "Status"],
        [
            ["F1.1", "step1/figures/F1.1_joint_30d.png", "Canonical empirical"],
            ["F1.2", "step1/figures/F1.2_clear_sky_overlay.png", "Canonical empirical"],
            ["F1.3", "step1/figures/F1.3_corner_counts.png", "Canonical empirical"],
            ["F1.4", "step1/figures/F1.4_joint_60d.png", "Canonical empirical"],
            ["T1.1", "step1/tables/T1.1_city_cell_counts.csv", "Canonical empirical"],
            ["T1.2", "step1/tables/T1.2_city_domains.csv", "Canonical empirical"],
            ["M1.1", "step1/memos/M1.1_feasibility_gate.md", "Canonical empirical"],
        ],
        [900, 5500, 2960],
        font_size=8.8,
        status_col=2,
    )
    add_body(doc, "Base path for the Step 1 entries above: data/processed/v2/task1/.", color=GREY)

    page_break(doc)
    add_kicker(doc, "Appendix")
    add_heading(doc, "A. Additional thirty-day joint-support figure", 1)
    add_figure(
        doc,
        F1_1,
        "Appendix Figure A1 (F1.1)",
        "All-day five-city joint distribution using the 30-day antecedent-dryness window. Tercile boundaries, nine cell counts, diagnostic corners, and Spearman correlations are shown.",
        "Canonical empirical meteorological screening; no thermal outcome",
        width=6.25,
    )

    add_heading(doc, "B. Final state declaration", 1)
    add_callout(
        doc,
        "Professor-review conclusion",
        "The project has a strong governance, feasibility, and reproducibility foundation; a complete pre-thermal empirical chain across Steps 1 to 3; substantial real nonthermal satellite audit work including a documented external archive failure; and a comprehensive synthetic demonstration of the remaining pipeline. It has no empirical urban-tree-cooling result, and under the present design it cannot obtain one. That is now a measured conclusion rather than an open item: both frozen gates have been issued and both returned STOP. Any evaluation should therefore credit the completed design, the Step 1 and Step 2 findings, the archive and geometry remediation, the definitive power and identifiability diagnostics, and the reproducible package — and should treat the choice of what to do next as a scientific decision for the supervisor rather than as remaining computation.",
        fill=PALE_BLUE,
        border=BLUE,
    )

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(24)
    r = p.add_run("END OF REPORT")
    set_run_font(r, size=9, color=GREY, bold=True)

    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build()
