"""PDF helpers for administrative healthcare documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping
from html import escape


def warm_pdf_backend() -> str:
    """Load the preferred PDF engine during agent startup, not first request."""

    try:
        from fpdf import FPDF  # noqa: F401
        return "fpdf2"
    except ImportError:
        from reportlab.pdfgen import canvas  # noqa: F401
        return "reportlab"


def _clean(value: Any) -> str:
    if value is None:
        return "Not recorded"
    return str(value).replace("\u2019", "'").encode("latin-1", "replace").decode("latin-1")


def build_report(
    title: str,
    sections: Iterable[tuple[str, Mapping[str, Any]]],
    output_path: str | Path,
) -> Path:
    try:
        from fpdf import FPDF
    except ImportError:
        return _build_with_reportlab(title, sections, output_path)

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 17)
    pdf.multi_cell(0, 9, _clean(title), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for heading, values in sections:
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 7, _clean(heading), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        for label, value in values.items():
            pdf.multi_cell(
                0,
                6,
                f"{_clean(label)}: {_clean(value)}",
                new_x="LMARGIN",
                new_y="NEXT",
            )
        pdf.ln(2)
    pdf.output(str(destination))
    return destination


def _build_with_reportlab(
    title: str,
    sections: Iterable[tuple[str, Mapping[str, Any]]],
    output_path: str | Path,
) -> Path:
    """Bundled-runtime fallback used when fpdf2 is not installed."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install fpdf2 or reportlab to generate PDF reports") from exc

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(_clean(title)), styles["Title"]), Spacer(1, 0.2 * inch)]
    for heading, values in sections:
        story.append(Paragraph(escape(_clean(heading)), styles["Heading2"]))
        data = [
            [Paragraph(f"<b>{escape(_clean(label))}</b>", styles["BodyText"]), Paragraph(escape(_clean(value)), styles["BodyText"])]
            for label, value in values.items()
        ]
        table = Table(data, colWidths=[1.8 * inch, 4.5 * inch], hAlign="LEFT")
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D9D9")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF2F8")),
        ]))
        story.extend([table, Spacer(1, 0.18 * inch)])
    document = SimpleDocTemplate(
        str(destination), pagesize=LETTER, rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54
    )
    document.build(story)
    return destination

