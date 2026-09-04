"""Optional PDF export, generated from the same report dict as JSON/Markdown."""
from __future__ import annotations

import io
from typing import Any, Dict

PDF_AVAILABLE = True
try:  # pragma: no cover - depends on optional dependency
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError:  # pragma: no cover
    PDF_AVAILABLE = False


STATUS_COLOURS = {"PASS": "#1a7f37", "FAIL": "#b42318", "N/A": "#6b7280", "ERROR": "#b45309"}


def to_pdf(report: Dict[str, Any], max_findings: int = 15) -> bytes:
    """Render the report as a PDF. Raises RuntimeError when reportlab is absent."""
    if not PDF_AVAILABLE:
        raise RuntimeError("reportlab is not installed; run: pip install reportlab")

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm, title="Code Review Report",
    )
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small")
    small.fontSize = 7.5
    small.leading = 9.5

    story = [Paragraph("Code Review Report", styles["Title"])]
    score = report.get("overall_score")
    summary = [
        ["Overall Score", "N/A" if score is None else f"{score}/100"],
        ["Quality Gate", report.get("quality_gate", "N/A")],
        ["Dimensions Passed", f"{report.get('dimensions_passed', 0)}/"
                              f"{report.get('dimensions_evaluated', 0)}"],
        ["Files Scanned", str(report.get("files_scanned", 0))],
        ["Total Findings", str(report.get("total_findings", 0))],
        ["Scan ID", str(report.get("scan_id", ""))],
        ["Timestamp", str(report.get("timestamp", ""))],
        ["Path", str(report.get("path", ""))],
    ]
    table = Table(summary, colWidths=[45 * mm, 125 * mm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d7de")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f6f8fa")),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ]))
    story.extend([Spacer(1, 6), table, Spacer(1, 12)])

    story.append(Paragraph("Dimension Summary", styles["Heading2"]))
    rows = [["Dimension", "Weight", "Score", "Status", "Findings"]]
    for dimension in report.get("dimensions", []):
        dimension_score = dimension.get("score")
        rows.append([
            dimension["label"], f"{dimension['weight']:g}",
            "-" if dimension_score is None else f"{dimension_score:g}",
            dimension["status"], str(dimension.get("findings_count", 0)),
        ])
    summary_table = Table(rows, colWidths=[60 * mm, 20 * mm, 20 * mm, 30 * mm, 25 * mm])
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d0d7de")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f6")),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ]
    for index, dimension in enumerate(report.get("dimensions", []), start=1):
        colour = STATUS_COLOURS.get(dimension["status"], "#6b7280")
        style.append(("TEXTCOLOR", (3, index), (3, index), colors.HexColor(colour)))
    summary_table.setStyle(TableStyle(style))
    story.extend([summary_table, PageBreak()])

    story.append(Paragraph("Findings", styles["Heading2"]))
    for dimension in report.get("dimensions", []):
        findings = dimension.get("findings", [])
        if not findings:
            continue
        story.append(Paragraph(f"{dimension['label']} ({len(findings)})", styles["Heading3"]))
        detail = [["File", "Lang", "Line", "Severity", "Issue", "Fix"]]
        for finding in findings[:max_findings]:
            detail.append([
                Paragraph(finding["file"], small), finding["language"], str(finding["line"]),
                finding["severity"], Paragraph(finding["issue"], small),
                Paragraph(finding["fix"], small),
            ])
        detail_table = Table(detail, colWidths=[40 * mm, 15 * mm, 12 * mm, 18 * mm, 45 * mm, 45 * mm])
        detail_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d0d7de")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f6")),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.extend([detail_table, Spacer(1, 10)])

    document.build(story)
    return buffer.getvalue()
