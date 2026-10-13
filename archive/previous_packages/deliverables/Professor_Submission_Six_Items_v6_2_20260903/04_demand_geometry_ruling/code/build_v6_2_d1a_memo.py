#!/usr/bin/env python3
"""Render the v6.2 D1a memo from its machine-readable analysis manifest."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


def draw_wrapped(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    font: str = "Helvetica",
    size: float = 8.7,
    leading: float = 11.2,
) -> float:
    pdf.setFont(font, size)
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
        pdf.drawString(x, y, rendered)
        y -= leading
    return y


def draw_table(
    pdf: canvas.Canvas,
    x: float,
    y_top: float,
    rows: list[list[str]],
    widths: list[float],
    row_height: float = 0.29 * inch,
) -> float:
    total_width = sum(widths)
    for row_index, row in enumerate(rows):
        y = y_top - (row_index + 1) * row_height
        fill = colors.HexColor("#334155") if row_index == 0 else colors.HexColor("#F8FAFC")
        pdf.setFillColor(fill)
        pdf.rect(x, y, total_width, row_height, fill=1, stroke=0)
        cursor = x
        for column_index, value in enumerate(row):
            pdf.setStrokeColor(colors.HexColor("#CBD5E1"))
            pdf.rect(cursor, y, widths[column_index], row_height, fill=0, stroke=1)
            pdf.setFillColor(colors.white if row_index == 0 else colors.HexColor("#0F172A"))
            pdf.setFont("Helvetica-Bold" if row_index == 0 else "Helvetica", 8.0)
            pdf.drawString(cursor + 5, y + 0.105 * inch, value)
            cursor += widths[column_index]
    return y_top - len(rows) * row_height


def render_memo(result: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    ruling = str(result["ruling"])
    binding = {row["city"]: row for row in result["binding_rows"]}
    sensitivity = {
        row["city"]: row
        for row in result["condition_rows"]
        if row["view_set_max_deg"] == 15
    }
    phoenix = binding["phoenix"]
    los_angeles = binding["los_angeles"]
    thresholds = result["thresholds"]

    def full_or_reduced(row: dict, full_key: str, reduced_key: str, digits: int) -> str:
        full_value = row[full_key]
        if full_value is not None:
            return f"{full_value:.{digits}f}"
        return f"NE ({row[reduced_key]:.{digits}f}*)"

    def pairwise_r(city: str, variable_2: str) -> float:
        for row in result["pairwise_rows"]:
            if (
                row["city"] == city
                and row["variable_1"] == "exact_time_VPD_kPa"
                and row["variable_2"] == variable_2
            ):
                return float(row["pearson_r"])
        raise ValueError(f"Missing pairwise result for {city}: {variable_2}")

    decision_headline = (
        "Drop both W_tree × VPD and W_bg × VPD"
        if ruling == "DROP"
        else "Keep both W_tree × VPD and W_bg × VPD"
    )
    decision_subline = (
        "Remove RQ2; report average daytime effects. Ruling is irreversible after coefficient access."
        if ruling == "DROP"
        else "Retain RQ2 under the frozen support range. Ruling is irreversible after coefficient access."
    )
    ruling_fill = "#FEE2E2" if ruling == "DROP" else "#DCFCE7"
    ruling_text = "#991B1B" if ruling == "DROP" else "#166534"
    pdf = canvas.Canvas(str(output), pagesize=letter)
    page_width, page_height = letter
    margin = 0.58 * inch

    def header(title: str, page_number: int) -> float:
        pdf.setFillColor(colors.HexColor("#0F172A"))
        pdf.rect(0, page_height - 0.56 * inch, page_width, 0.56 * inch, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 12.5)
        pdf.drawString(margin, page_height - 0.36 * inch, title)
        pdf.setFont("Helvetica", 8)
        pdf.drawRightString(
            page_width - margin,
            page_height - 0.36 * inch,
            f"v6.2 D1a | page {page_number} of 2",
        )
        pdf.setFillColor(colors.HexColor("#0F172A"))
        return page_height - 0.82 * inch

    y = header("Demand–geometry support ruling", 1)
    pdf.setFillColor(colors.HexColor(ruling_fill))
    pdf.roundRect(margin, y - 0.76 * inch, page_width - 2 * margin, 0.68 * inch, 8, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor(ruling_text))
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(margin + 0.18 * inch, y - 0.36 * inch, ruling)
    pdf.setFont("Helvetica-Bold", 10.3)
    pdf.drawString(margin + 1.22 * inch, y - 0.27 * inch, decision_headline)
    pdf.setFont("Helvetica", 8.8)
    pdf.drawString(
        margin + 1.22 * inch,
        y - 0.48 * inch,
        decision_subline,
    )
    y -= 0.93 * inch

    pdf.setFillColor(colors.HexColor("#0F172A"))
    pdf.setFont("Helvetica-Bold", 10.5)
    pdf.drawString(margin, y, "Prospective decision rule")
    y -= 0.18 * inch
    y = draw_wrapped(
        pdf,
        f"Before these diagnostics were computed, V6.2-D002 required both Gate A cities to have at least {thresholds['minimum_complete_passes']} complete passes in the 25° candidate design, VPD VIF ≤{thresholds['maximum_vpd_vif']:.0f}, maximum condition index ≤{thresholds['maximum_condition_index']:.0f}, leave-one-pass-out nonlinear VPD concurvity R² ≤{thresholds['maximum_nonlinear_concurvity_r2']:.2f}, residual VPD SD ≥{thresholds['minimum_residual_vpd_sd_kpa']:.2f} kPa, and continuously supported VPD width ≥{thresholds['minimum_continuous_support_width_kpa']:.2f} kPa. Missing required geometry fails closed. Pairwise correlations are descriptive only.",
        margin,
        y,
        page_width - 2 * margin,
    )
    y -= 0.08 * inch
    rows = [
        ["Binding criterion", "Threshold", "Phoenix", "Los Angeles"],
        [
            "Complete full-design passes",
            f"≥{thresholds['minimum_complete_passes']}",
            f"{phoenix['n_full_design_complete']} / {phoenix['n_quality_weather_passes']}",
            f"{los_angeles['n_full_design_complete']} / {los_angeles['n_quality_weather_passes']}",
        ],
        [
            "VPD VIF",
            f"≤{thresholds['maximum_vpd_vif']:.0f}",
            full_or_reduced(phoenix, "full_vpd_vif", "reduced_vpd_vif_nonbinding", 2),
            full_or_reduced(los_angeles, "full_vpd_vif", "reduced_vpd_vif_nonbinding", 2),
        ],
        [
            "Maximum condition index",
            f"≤{thresholds['maximum_condition_index']:.0f}",
            full_or_reduced(phoenix, "full_max_condition_index", "reduced_max_condition_index_nonbinding", 2),
            full_or_reduced(los_angeles, "full_max_condition_index", "reduced_max_condition_index_nonbinding", 2),
        ],
        [
            "Nonlinear concurvity R²",
            f"≤{thresholds['maximum_nonlinear_concurvity_r2']:.2f}",
            full_or_reduced(phoenix, "full_vpd_nonlinear_cv_concurvity_r2", "reduced_vpd_nonlinear_cv_concurvity_r2_nonbinding", 3),
            full_or_reduced(los_angeles, "full_vpd_nonlinear_cv_concurvity_r2", "reduced_vpd_nonlinear_cv_concurvity_r2_nonbinding", 3),
        ],
        [
            "Residual VPD SD (kPa)",
            f"≥{thresholds['minimum_residual_vpd_sd_kpa']:.2f}",
            full_or_reduced(phoenix, "full_residual_vpd_sd_kpa", "reduced_residual_vpd_sd_kpa_nonbinding", 3),
            full_or_reduced(los_angeles, "full_residual_vpd_sd_kpa", "reduced_residual_vpd_sd_kpa_nonbinding", 3),
        ],
        [
            "Common VPD width (kPa)",
            f"≥{thresholds['minimum_continuous_support_width_kpa']:.2f}",
            f"{phoenix['continuous_support_width_kpa']:.3f}",
            f"{los_angeles['continuous_support_width_kpa']:.3f}",
        ],
    ]
    y = draw_table(
        pdf,
        margin,
        y,
        rows,
        [2.15 * inch, 0.9 * inch, 1.35 * inch, 1.45 * inch],
    )
    y -= 0.16 * inch
    pdf.setFont("Helvetica-Oblique", 7.7)
    pdf.setFillColor(colors.HexColor("#475569"))
    pdf.drawString(
        margin,
        y,
        "* Optimistic reduced-design value after omitting unavailable view and relative azimuth; nonbinding.",
    )
    y -= 0.30 * inch
    pdf.setFillColor(colors.HexColor("#0F172A"))
    pdf.setFont("Helvetica-Bold", 10.5)
    pdf.drawString(margin, y, "Why the branch fails" if ruling == "DROP" else "Why the branch survives")
    y -= 0.19 * inch
    y = draw_wrapped(
        pdf,
        (
            f"Neither city has a complete set of the required view-azimuth and relative sun–sensor azimuth controls ({phoenix['n_full_design_complete']}/{phoenix['n_quality_weather_passes']} Phoenix; {los_angeles['n_full_design_complete']}/{los_angeles['n_quality_weather_passes']} Los Angeles), so the full design cannot be estimated. Even the favorable reduced check exceeds the VIF, condition-index, and nonlinear-concurvity ceilings in both cities. Los Angeles also fails the residual-SD and continuous-support floors."
            if ruling == "DROP"
            else "Both cities meet every prospectively frozen completeness, collinearity, concurvity, residual-variation, and continuous-support criterion in the full candidate design."
        ),
        margin,
        y,
        page_width - 2 * margin,
    )
    pdf.setFont("Helvetica", 7.4)
    pdf.setFillColor(colors.HexColor("#64748B"))
    pdf.drawString(margin, 0.42 * inch, "No ECOSTRESS LST value or new v6.2 coefficient was opened for this ruling.")
    pdf.showPage()

    y = header("Identification and traceability", 2)
    pdf.setFont("Helvetica-Bold", 10.5)
    pdf.drawString(margin, y, "Variation that would identify the interaction")
    y -= 0.20 * inch
    y = draw_wrapped(
        pdf,
        "The VPD interaction would be identified by within-city, cross-pass variation in exact-time VPD that remains after conditioning on exact-time air temperature and actual vapour pressure/dewpoint, local solar time, solar zenith and azimuth, view zenith, relative sun–sensor azimuth, and day of year—and only within a VPD range continuously shared across those time, solar-geometry, viewing-geometry, and seasonal conditions. "
        + ("That independent variation is not demonstrated here." if ruling == "DROP" else "That independent variation meets the frozen support rule."),
        margin,
        y,
        page_width - 2 * margin,
        size=8.8,
        leading=11.4,
    )
    y -= 0.15 * inch
    pdf.setFont("Helvetica-Bold", 10.5)
    pdf.drawString(margin, y, "Supporting numbers")
    y -= 0.20 * inch
    bullet_texts = [
        f"Historical nonthermal 25° support: {phoenix['n_quality_weather_passes']} Phoenix passes and {los_angeles['n_quality_weather_passes']} Los Angeles passes; 15° sensitivity: {sensitivity['phoenix']['n_quality_weather_passes']} and {sensitivity['los_angeles']['n_quality_weather_passes']}.",
        f"VPD–air-temperature Pearson r: {pairwise_r('phoenix', 'exact_time_air_temperature_K'):.3f} Phoenix and {pairwise_r('los_angeles', 'exact_time_air_temperature_K'):.3f} Los Angeles. VPD–day-of-year r: {pairwise_r('phoenix', 'day_of_year'):.3f} and {pairwise_r('los_angeles', 'day_of_year'):.3f}. Correlations alone do not determine the ruling.",
        f"Reduced nonlinear VPD predictability is {phoenix['reduced_vpd_nonlinear_cv_concurvity_r2_nonbinding']:.3f} and {los_angeles['reduced_vpd_nonlinear_cv_concurvity_r2_nonbinding']:.3f} out of sample; unexplained SD is {phoenix['reduced_residual_vpd_sd_kpa_nonbinding']:.3f} and {los_angeles['reduced_residual_vpd_sd_kpa_nonbinding']:.3f} kPa.",
        (
            f"Common VPD support is {phoenix['continuous_support_low_kpa']:.3f}–{phoenix['continuous_support_high_kpa']:.3f} kPa in Phoenix (width {phoenix['continuous_support_width_kpa']:.3f}); Los Angeles has no intersection (bounds cross at {los_angeles['continuous_support_intersection_lower_bound_kpa']:.3f} versus {los_angeles['continuous_support_intersection_upper_bound_kpa']:.3f} kPa; width {los_angeles['continuous_support_width_kpa']:.0f})."
            if not los_angeles["continuous_support_has_overlap"]
            else f"Common VPD support widths are {phoenix['continuous_support_width_kpa']:.3f} kPa in Phoenix and {los_angeles['continuous_support_width_kpa']:.3f} kPa in Los Angeles."
        ),
    ]
    for item in bullet_texts:
        pdf.setFillColor(colors.HexColor("#0F766E"))
        pdf.circle(margin + 3, y + 3, 1.6, fill=1, stroke=0)
        pdf.setFillColor(colors.HexColor("#0F172A"))
        y = draw_wrapped(
            pdf,
            item,
            margin + 0.16 * inch,
            y + 6,
            page_width - 2 * margin - 0.16 * inch,
            size=8.5,
            leading=10.8,
        )
        y -= 0.05 * inch
    y -= 0.08 * inch
    pdf.setFont("Helvetica-Bold", 10.5)
    pdf.drawString(margin, y, "Decision and downstream consequence")
    y -= 0.20 * inch
    y = draw_wrapped(
        pdf,
        (
            "DROP the demand branch now. Both candidate interactions are removed together; RQ2 does not survive; high-demand p75 contrasts will not be reported; and later Stage 2 work is restricted to average daytime effects. The branch is not retained for publication appeal and cannot be restored after new coefficients are viewed."
            if ruling == "DROP"
            else "KEEP both demand interactions under the frozen support interval and retain RQ2. The branch cannot be changed after new coefficients are viewed."
        ),
        margin,
        y,
        page_width - 2 * margin,
        size=8.8,
        leading=11.4,
    )
    y -= 0.18 * inch
    pdf.setFont("Helvetica-Bold", 10.5)
    pdf.drawString(margin, y, "Scope and traceability")
    y -= 0.20 * inch
    y = draw_wrapped(
        pdf,
        "Evidence is historical pass-level provenance, not the v6.2 study sample. Exact-time HRRR temperature and dewpoint were linearly interpolated from inherited bracketing-hour summaries; actual vapour pressure was computed from dewpoint. Solar coordinates were calculated at the frozen city centroids from local solar time and day of year. A geometry-only recovery read all 92 frozen passes from ECO_L1B_GEO.002 without opening LST: only 4/44 Phoenix and 1/48 Los Angeles passes had view and solar azimuth populated for every mapped view-valid cell. Partial arrays were not imputed or promoted to complete. Controlling sources: Deliverables Schedule p.3; Research Proposal pp.15–18; Working Guide pp.2–4, 7, 11–13. All input and output hashes are recorded in the package.",
        margin,
        y,
        page_width - 2 * margin,
        size=8.5,
        leading=10.9,
    )
    y -= 0.16 * inch
    pdf.setFillColor(colors.HexColor("#F1F5F9"))
    pdf.roundRect(margin, y - 0.58 * inch, page_width - 2 * margin, 0.52 * inch, 5, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor("#334155"))
    pdf.setFont("Helvetica-Bold", 8.4)
    pdf.drawString(
        margin + 0.12 * inch,
        y - 0.23 * inch,
        f"Status: {ruling} | V6.2-D002 rule | geometry recovery reassessment | D003 unchanged",
    )
    pdf.setFont("Helvetica", 7.8)
    pdf.drawString(
        margin + 0.12 * inch,
        y - 0.40 * inch,
        "Generated 2026-09-01 (Asia/Seoul). Historical evidence only; no thermal outcome access.",
    )
    pdf.setFont("Helvetica", 7.4)
    pdf.setFillColor(colors.HexColor("#64748B"))
    pdf.drawString(margin, 0.42 * inch, "D1a demand–geometry support memo | memo.pdf")
    pdf.save()


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: build_v6_2_d1a_memo.py ANALYSIS_JSON OUTPUT_PDF")
    result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    render_memo(result, Path(sys.argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
