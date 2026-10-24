"""Read-only Excel rendering of the Process QR editor's current operation list."""
from decimal import Decimal
from io import BytesIO
from textwrap import wrap
from typing import Annotated, Literal

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.page import PageMargins
from pydantic import BaseModel, Field


Text = Annotated[str, Field(max_length=500)]


class ProcessQrExportRow(BaseModel):
    selected: bool
    section: Text
    code: Text
    name: Text
    rate: Decimal = Field(ge=0, le=Decimal("9999999999.9999"), allow_inf_nan=False)
    copies: int = Field(ge=1, le=10000)
    division: Text


class ProcessQrExportIn(BaseModel):
    lang: Literal["en", "ru", "uz"] = "en"
    model: Text
    order: Text = ""
    factory: Literal["MIL", "BST", "ECO"]
    currency: Annotated[str, Field(max_length=10)]
    headers: list[Text] = Field(min_length=8, max_length=8)
    rows: list[ProcessQrExportRow] = Field(min_length=1, max_length=1000)


def build_process_qr_xlsx(payload: ProcessQrExportIn) -> bytes:
    labels = {
        "en": ("Paid processes", "Model", "Order", "Total amount", "Approved by", "Name", "Signature"),
        "ru": ("Платные операции", "Модель", "Заказ", "Общая сумма", "Утверждено", "ФИО", "Подпись"),
        "uz": ("Pullik jarayonlar", "Model", "Buyurtma", "Jami summa", "Tasdiqladi", "F.I.Sh.", "Imzo"),
    }[payload.lang]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Paid processes"
    sheet.sheet_view.showGridLines = False

    def text(cell, value):
        # User-entered text must never become a spreadsheet formula.
        cell.value = ILLEGAL_CHARACTERS_RE.sub("", value)
        cell.data_type = "s"

    sheet.merge_cells("A1:D1")
    text(sheet["A1"], labels[0])
    sheet.merge_cells("A2:C2")
    text(sheet["A2"], f"{labels[1]}: {payload.model}")
    text(sheet["D2"], payload.factory)
    sheet.merge_cells("A3:C3")
    text(sheet["A3"], f"{labels[2]}: {payload.order}" if payload.order else "")
    text(sheet["D3"], payload.currency)
    for column, header in enumerate((payload.headers[i] for i in (0, 2, 4, 5)), 1):
        text(sheet.cell(5, column), header)
    for index, row in enumerate(payload.rows, 1):
        excel_row = index + 5
        sheet.cell(excel_row, 1, index)
        text(sheet.cell(excel_row, 2), row.section)
        text(sheet.cell(excel_row, 3), row.name)
        sheet.cell(excel_row, 4, row.rate).number_format = "#,##0.00##"
        lines = max(sum(max(1, len(wrap(line, width))) for line in value.split("\n"))
                    for value, width in ((row.name, 52), (row.section, 18)))
        sheet.row_dimensions[excel_row].height = max(23, lines * 14 + 8)

    last_data_row = len(payload.rows) + 5
    total_row = last_data_row + 1
    sheet.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=3)
    text(sheet.cell(total_row, 1), f"{labels[3]} ({payload.currency})")
    sheet.cell(total_row, 4, f"=SUM(D6:D{last_data_row})").number_format = "#,##0.00##"
    approval_row = total_row + 3
    sheet.merge_cells(start_row=approval_row, start_column=1, end_row=approval_row, end_column=4)
    text(sheet.cell(approval_row, 1), labels[4])
    for row, label in ((approval_row + 2, labels[5]), (approval_row + 4, labels[6])):
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
        sheet.merge_cells(start_row=row, start_column=3, end_row=row, end_column=4)
        text(sheet.cell(row, 1), label)
        for column in (3, 4):
            sheet.cell(row, column).border = Border(bottom=Side(style="thin", color="64748B"))
        sheet.row_dimensions[row].height = 28

    for row in sheet:
        for cell in row:
            cell.font = Font(name="Arial", size=10, color="202A35")
            cell.alignment = Alignment(vertical="center", wrap_text=True,
                                       horizontal="right" if cell.column in (1, 4) and 6 <= cell.row <= total_row else "left")
    sheet["A1"].font = Font(name="Arial", size=16, bold=True, color="202A35")
    sheet.row_dimensions[1].height = 32
    sheet.row_dimensions[2].height = 25
    sheet.row_dimensions[3].height = 22
    sheet.row_dimensions[4].height = 10
    sheet.row_dimensions[5].height = 28
    sheet.row_dimensions[total_row].height = 29
    sheet.row_dimensions[approval_row].height = 25
    for cell in sheet[5]:
        cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="334155")
    for row in sheet.iter_rows(min_row=6, max_row=last_data_row, max_col=4):
        for cell in row:
            cell.border = Border(bottom=Side(style="hair", color="DDE2E7"))
    for cell in sheet[total_row]:
        cell.font = Font(name="Arial", size=11, bold=True, color="202A35")
        cell.fill = PatternFill("solid", fgColor="E9EDF1")
        cell.border = Border(top=Side(style="thin", color="64748B"))
    sheet.cell(total_row, 1).alignment = Alignment(horizontal="left", vertical="center")
    sheet.cell(approval_row, 1).font = Font(name="Arial", size=11, bold=True, color="202A35")
    for column, width in zip("ABCD", [7, 21, 58, 19]):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A6"
    sheet.auto_filter.ref = f"A5:D{last_data_row}"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "portrait"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.page_margins = PageMargins(left=0.3, right=0.3, top=0.4, bottom=0.4, header=0.15, footer=0.2)
    sheet.print_title_rows = "1:5"
    sheet.print_area = f"A1:D{approval_row + 4}"
    sheet.oddFooter.right.text = "&P / &N"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
