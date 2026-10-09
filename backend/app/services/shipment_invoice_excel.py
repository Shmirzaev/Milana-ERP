"""Read-only Excel version of the same shipment invoice used for printing."""
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from textwrap import wrap

from app.services.variant_display import format_variant_number

from openpyxl import Workbook
from openpyxl.drawing.image import Image
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins

from app.services.shipment_invoice import (
    INVOICE_CONTACT, LABELS, build_invoice_rows, invoice_column_widths, invoice_headers,
    invoice_metadata, invoice_notes, invoice_price_notes, recorded_weight,
)


def shipment_invoice_workbook(document: dict, language: str, *, show_prices: bool = True) -> bytes:
    lang = language if language in LABELS else "en"
    text = LABELS[lang]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Invoice"
    widths = invoice_column_widths()
    last_column = len(widths)
    for column, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(column)].width = width

    def put(row, column, value, *, bold=False, fill=None, color="202124", align="left", size=8):
        cell = sheet.cell(row, column, value)
        # Business text remains literal even when it starts with =, +, - or @.
        if isinstance(value, str):
            cell.data_type = "s"
        cell.font = Font(name="Calibri", size=size, bold=bold, color=color)
        cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=True)
        if fill:
            cell.fill = PatternFill("solid", fgColor=fill)
        return cell

    def merged(row, first, last, value, **style):
        sheet.merge_cells(start_row=row, start_column=first, end_row=row, end_column=last)
        put(row, first, value, **style)

    merged(2, 1, 8, "MILANA PREMIUM", bold=True, color="1F3864", size=24)
    merged(3, 1, 8, text["title"], bold=True, color="2F5597", size=11)
    logo = Image(Path(__file__).resolve().parents[1] / "assets" / "milana-premium-logo.png")
    logo.height = 140 * logo.height / logo.width
    logo.width = 140
    sheet.add_image(logo, "I2")
    sheet.row_dimensions[1].height = 4
    sheet.row_dimensions[2].height = 30
    sheet.row_dimensions[3].height = 35
    for row, (left, lv, right, rv) in enumerate(invoice_metadata(document, text), 4):
        merged(row, 1, 2, left, bold=True, fill="F2F5FA", color="1F3864", size=9)
        merged(row, 3, 4, lv or "—", bold=True)
        merged(row, 5, 6, right, bold=True, fill="F2F5FA", color="4D5656", size=9)
        merged(row, 7, last_column, rv or "—", bold=True)
        for column in range(1, last_column + 1):
            sheet.cell(row, column).border = Border(left=Side(style="thin", color="8EA9DB"), right=Side(style="thin", color="8EA9DB"), top=Side(style="thin", color="8EA9DB"), bottom=Side(style="thin", color="8EA9DB"))
        sheet.row_dimensions[row].height = 20
    sheet.row_dimensions[8].height = 16
    headers = invoice_headers(lang)
    for column, title in enumerate(headers, 1):
        put(9, column, title, bold=True, fill="1F3864" if column in (1, 11) else "2F5597", color="FFFFFF", align="center", size=7)
    sheet.row_dimensions[9].height = 22
    packages = document.get("package_details")
    if packages is None:
        packages = list({line["package_no"]: {"package_no": line["package_no"], "weight_kg": None} for line in document.get("lines", [])}.values())
    rows = document.get("invoice_rows") or build_invoice_rows(document.get("lines", []), packages)
    line = Side(style="thin", color="8EA9DB")
    border = Border(left=line, right=line, top=line, bottom=line)
    for index, item in enumerate(rows, 1):
        row = index + 9
        sizes = item.get("sizes", [])
        multicolor = len({s.get("color") for s in sizes if s.get("color")}) > 1
        size_text = "\n".join((f'{s.get("color") or ""} / ' if multicolor else "") + str(s.get("size") or "") +
                              ("" if s.get("aggregate") else f' ({int(s["quantity"])})') for s in sizes)
        span = item["package_rowspan"]
        weight = float(Decimal(str(item["weight_kg"]))) if item.get("weight_kg") is not None else None
        displayed_weight = weight if weight is not None else "—" if span else None
        values = [index, item.get("model_no"), format_variant_number(item.get("variant_no")), item.get("description"), size_text,
                  item["pack_count"] if span else None, item["quantity"], displayed_weight, displayed_weight]
        if show_prices:
            values.extend(float(Decimal(str(item[key]))) if item.get(key) is not None else "—" for key in ("unit_price", "amount"))
        else:
            values.extend([None, None])
        for column, value in enumerate(values, 1):
            cell = put(row, column, value, fill="FFFFFF",
                       align="right" if column >= 6 else "left" if column in (4, 5) else "center",
                       bold=column in (1, 2, 11), size=7)
            cell.border = border
            if column >= 6:
                cell.number_format = '#,##0.00' if column >= 8 else '#,##0'
        for column in (6, 8, 9):
            if span > 1:
                sheet.merge_cells(start_row=row, end_row=row + span - 1, start_column=column, end_column=column)
        # Column widths use the workbook's 11pt default; invoice text is 7pt.
        line_count = max(sum(max(1, len(wrap(part, max(1, int((width - 1) * 11 / 7))))) for part in str(value or "").split("\n")) for value, width in zip(values, widths))
        sheet.row_dimensions[row].height = max(23.1, line_count * 8.4 + 6)
    total_row = 10 + len(rows)
    merged(total_row, 1, 5, text["total"], bold=True, fill="C6D9F1", color="1F3864")
    for column, value in enumerate([document["packages_count"], document["quantity"], float(recorded_weight(document)), float(recorded_weight(document))], 6):
        cell = put(total_row, column, value, bold=True, fill="C6D9F1", color="1F3864", align="right")
        cell.number_format = '#,##0.00' if column >= 8 else '#,##0'
    put(total_row, 10, None, fill="C6D9F1")
    amount = (float(Decimal(str(document["amount"]))) if document.get("amount") is not None else "—") if show_prices else None
    cell = put(total_row, 11, amount, bold=True, fill="1F3864", color="FFFFFF", align="right", size=7)
    cell.number_format = '#,##0.00'
    sheet.row_dimensions[total_row].height = 22
    signature_row = total_row + 2
    officer = {"en": "Responsible warehouse officer", "ru": "Ответственный кладовщик", "uz": "Mas’ul omborchi"}[lang]
    signature = {"en": "Warehouse signature", "ru": "Подпись кладовщика", "uz": "Omborchi imzosi"}[lang]
    merged(signature_row, 1, 5, officer, bold=True, fill="1F3864", color="FFFFFF", align="center", size=9)
    merged(signature_row, 6, 11, signature, bold=True, fill="2F5597", color="FFFFFF", align="center", size=9)
    merged(signature_row + 1, 1, 5, None, bold=True, fill="F2F5FA", color="1F3864", align="center", size=11)
    merged(signature_row + 1, 6, 11, "________________________________", color="1F3864", align="center")
    sheet.row_dimensions[signature_row].height = 20
    sheet.row_dimensions[signature_row + 1].height = 36
    footer = signature_row + 3
    for (first, last), label in zip([(1, 3), (4, 7), (8, 11)], INVOICE_CONTACT):
        merged(footer, first, last, label, bold=True, fill="1F3864", color="FFFFFF", align="center")
        sheet.cell(footer, first).number_format = "@"
    sheet.row_dimensions[footer].height = 25
    notes = invoice_notes(document, lang)
    if show_prices:
        notes = notes[:-1] + invoice_price_notes(document, lang) + notes[-1:]
    for row, note in enumerate(notes, footer + 2):
        merged(row, 1, last_column, note, color="575E66")
        sheet.row_dimensions[row].height = 24
    # Match the reference's solid grid, navy frames, gold rules and double total.
    outline = Side(style="medium", color="1F3864")
    gold = Side(style="medium", color="D99B26")
    total_bottom = Side(style="double", color="1F3864")
    for first, last, heading in [(4, 7, None), (9, total_row, 9), (signature_row, signature_row + 1, signature_row)]:
        for row in range(first, last + 1):
            for column in range(1, last_column + 1):
                sheet.cell(row, column).border = Border(
                    left=outline if column == 1 else line,
                    right=outline if column == last_column else line,
                    top=outline if row in (first, total_row) else gold if heading == row - 1 else line,
                    bottom=total_bottom if row == total_row else outline if row == last else gold if row == heading else line,
                )
    sheet.freeze_panes = "D10"
    sheet.sheet_view.showGridLines = False
    sheet.print_title_rows = "9:9"
    sheet.print_options.horizontalCentered = True
    sheet.page_setup.orientation = "portrait"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_margins = PageMargins(left=10 / 25.4, right=10 / 25.4, top=10 / 25.4, bottom=10 / 25.4, header=0, footer=5 / 25.4)
    sheet.print_area = f"A1:{get_column_letter(last_column)}{sheet.max_row}"
    sheet.oddFooter.right.text = "&P / &N"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
