"""Excel and PDF downloads for ArthPulse dashboard data."""
from io import BytesIO
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    LongTable,
    TableStyle,
    KeepTogether,
)


def _cell(value):
    if value is None:
        return ""

    if isinstance(value, (list, dict)):
        return str(value)

    return value


def excel_workbook(sheets: dict[str, list]) -> bytes:
    """Create an Excel workbook containing all supplied dashboard rows."""

    wb = Workbook()
    first = True

    for name, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = name[:31]

        for row in rows:
            ws.append([_cell(value) for value in row])

        # Style the header.
        if ws.max_row:
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(
                    fill_type="solid",
                    fgColor="1F5C45",
                )
                cell.alignment = Alignment(
                    horizontal="center",
                    vertical="center",
                    wrap_text=True,
                )

            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions

            # Set practical column widths based on the actual contents.
            for column in ws.columns:
                column_letter = get_column_letter(column[0].column)
                max_length = max(
                    (
                        len(str(cell.value))
                        for cell in column
                        if cell.value is not None
                    ),
                    default=10,
                )
                ws.column_dimensions[column_letter].width = min(
                    max(max_length + 2, 12),
                    35,
                )

    if first:
        ws = wb.active
        ws.title = "ArthPulse"
        ws.append(["No data available"])

    buffer = BytesIO()
    wb.save(buffer)

    return buffer.getvalue()


def pdf_report(
    title: str,
    lines: list[str],
    tables: list[tuple[str, list]] | None = None,
) -> bytes:
    """
    Generate a multi-page PDF report.

    All supplied table rows are included. Table headers repeat on
    subsequent pages instead of silently truncating the report.
    """

    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=title,
    )

    styles = getSampleStyleSheet()

    title_style = styles["Title"]

    body_style = ParagraphStyle(
        "ArthPulseBody",
        parent=styles["BodyText"],
        fontSize=9,
        leading=13,
        spaceAfter=4,
    )

    heading_style = ParagraphStyle(
        "ArthPulseHeading",
        parent=styles["Heading2"],
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#1F5C45"),
        spaceBefore=10,
        spaceAfter=6,
    )

    cell_style = ParagraphStyle(
        "ArthPulseCell",
        parent=styles["BodyText"],
        fontSize=7,
        leading=9,
        alignment=TA_LEFT,
        wordWrap="CJK",
    )

    header_style = ParagraphStyle(
        "ArthPulseHeader",
        parent=cell_style,
        textColor=colors.white,
        fontName="Helvetica-Bold",
    )

    story = [
        Paragraph(escape(str(title)), title_style),
        Spacer(1, 10),
    ]

    for line in lines or []:
        safe_line = escape(str(line)).replace("\n", "<br/>")
        story.append(Paragraph(safe_line, body_style))
        story.append(Spacer(1, 4))

    available_width = (
        document.width
        - document.leftMargin
        - document.rightMargin
    )

    for heading, rows in tables or []:
        if not rows:
            continue

        story.append(
            KeepTogether([
                Spacer(1, 8),
                Paragraph(escape(str(heading)), heading_style),
            ])
        )

        column_count = max(
            len(row) for row in rows if row is not None
        )

        if column_count == 0:
            continue

        table_data = []

        for row_index, row in enumerate(rows):
            row = list(row or [])

            # Keep all rows aligned if some rows have fewer columns.
            row.extend([""] * (column_count - len(row)))

            style = header_style if row_index == 0 else cell_style

            table_data.append([
                Paragraph(
                    escape(str(_cell(value))).replace("\n", "<br/>"),
                    style,
                )
                for value in row
            ])

        column_width = available_width / column_count

        table = LongTable(
            table_data,
            colWidths=[column_width] * column_count,
            repeatRows=1,
            splitByRow=1,
            hAlign="LEFT",
        )

        table.setStyle(TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#1F5C45"),
            ),
            (
                "TEXTCOLOR",
                (0, 0),
                (-1, 0),
                colors.white,
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.3,
                colors.HexColor("#D8D8D8"),
            ),
            (
                "BACKGROUND",
                (0, 1),
                (-1, -1),
                colors.HexColor("#FAF7F1"),
            ),
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP",
            ),
            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                4,
            ),
            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                4,
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                4,
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                4,
            ),
        ]))

        story.append(table)

    document.build(story)

    return buffer.getvalue()