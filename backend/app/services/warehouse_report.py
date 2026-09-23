"""Read-only full ready-product warehouse workbook."""

from datetime import datetime, timedelta, timezone
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import func
from sqlalchemy.orm import load_only, raiseload

from app.models import Model, Package
from app.services.model_identity import model_number_fields


TEXT = {
    "en": ["Ready product warehouse", "Standard stock", "First Grade", "Model number", "Variant number", "Packages", "Pieces", "Total", "All warehouse stock, including reserved and unplaced packages. Page filters do not apply. First Grade packages are individual pieces."],
    "ru": ["Склад готовой продукции", "Основной склад", "Первый сорт", "Номер модели", "Номер варианта", "Упаковки", "Штуки", "Итого", "Все складские остатки, включая резерв и упаковки без места. Фильтры страницы не применяются. Упаковки первого сорта — отдельные изделия."],
    "uz": ["Tayyor mahsulotlar ombori", "Asosiy ombor", "Birinchi sort", "Model raqami", "Variant raqami", "Qop soni", "Dona soni", "Jami", "Barcha ombor qoldiqlari, jumladan band qilingan va joylashtirilmagan qoplar. Sahifa filtrlari qo‘llanmaydi. Birinchi sort qadoqlari alohida donalardir."],
}


def export_warehouse_report(db, lang: str) -> bytes:
    # Match Warehouse Stock's ready statuses, including imported and unplaced stock.
    quantities = (
        db.query(Package.stock_kind, Package.model_id, func.count(Package.id), func.sum(Package.total_quantity))
        .filter(Package.status.in_(["packed", "received_in_storage", "reserved"]))
        .group_by(Package.stock_kind, Package.model_id)
        .all()
    )
    model_ids = {row.model_id for row in quantities if row.model_id is not None}
    models = {
        model.id: model
        for model in db.query(Model).options(
            raiseload("*"), load_only(Model.id, Model.code, Model.details_json),
        ).filter(Model.id.in_(model_ids)).all()
    } if model_ids else {}
    labels = TEXT[lang]
    workbook = Workbook()
    workbook.remove(workbook.active)
    generated = datetime.now(timezone(timedelta(hours=5))).strftime("%Y-%m-%d %H:%M (Tashkent)")
    for kind, title in [("standard", labels[1]), ("first_grade", labels[2])]:
        sheet = workbook.create_sheet(title)
        sheet.merge_cells("A1:E1")
        sheet["A1"] = f"{labels[0]} — {generated}"
        sheet["A1"].font = Font(size=14, bold=True)
        sheet.row_dimensions[1].height = 28
        sheet.merge_cells("A2:E2")
        sheet["A2"] = labels[8]
        sheet["A2"].alignment = Alignment(wrap_text=True, vertical="center")
        sheet.row_dimensions[2].height = 42
        sheet.append(["№", *labels[3:7]])
        rows = [row for row in quantities if row.stock_kind == kind]
        rows.sort(key=lambda row: tuple(str(value or "").casefold() for value in model_number_fields(models.get(row.model_id)).values()))
        for index, (_, model_id, packages, pieces) in enumerate(rows, 1):
            model = models.get(model_id)
            identity = model_number_fields(model)
            sheet.append([index, identity["model_no"], identity["variant_no"], int(packages), int(pieces or 0)])
            row_number = sheet.max_row
            sheet.row_dimensions[row_number].height = 24
            for cell in sheet[row_number]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.alignment = Alignment(vertical="center", wrap_text=True)
                if isinstance(cell.value, int):
                    cell.number_format = "#,##0"
        last = sheet.max_row
        sheet.append([labels[7], None, None,
                      f"=SUM(D4:D{last})" if rows else 0,
                      f"=SUM(E4:E{last})" if rows else 0])
        for number in (3, sheet.max_row):
            for cell in sheet[number]:
                cell.font = Font(bold=True)
                cell.fill = PatternFill("solid", fgColor="E9E5DA")
                cell.alignment = Alignment(vertical="center", wrap_text=True)
                if cell.column >= 4:
                    cell.number_format = "#,##0"
            sheet.row_dimensions[number].height = 30
        for column, width in {"A": 8, "B": 28, "C": 25, "D": 18, "E": 18}.items():
            sheet.column_dimensions[column].width = width
        sheet.freeze_panes = "D4"
        sheet.auto_filter.ref = f"A3:E{last}"
        sheet.sheet_view.showGridLines = False
        sheet.print_title_rows = "1:3"
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
