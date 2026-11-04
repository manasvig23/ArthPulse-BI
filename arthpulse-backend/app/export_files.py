"""Excel and PDF downloads of the current dashboard."""

from io import BytesIO

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def excel_workbook(sheets: dict[str, list]) -> bytes:
    wb = Workbook()
    first = True
    for name, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = name[:31]
        for row in rows:
            ws.append([_cell(c) for c in row])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return str(v)
    return v


def pdf_report(title: str, lines: list[str], tables: list[tuple[str, list]] | None = None) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title)
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
    for line in lines:
        story.append(Paragraph(line.replace("\n", "<br/>"), styles["BodyText"]))
        story.append(Spacer(1, 6))
    for heading, rows in tables or []:
        story.append(Spacer(1, 10))
        story.append(Paragraph(heading, styles["Heading2"]))
        data = [[str(_cell(c)) for c in row] for row in rows[:40]]
        if not data:
            continue
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f5c45")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ebe6da")),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#faf7f1")),
        ]))
        story.append(t)
    doc.build(story)
    return buf.getvalue()
