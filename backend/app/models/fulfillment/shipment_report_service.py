"""Read-only shipment history, preferring immutable dispatch evidence.

Only dispatched, undeleted shipments enter this report. Current package balances
must never replace the quantities frozen at dispatch (partial/shared packs).
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
from math import ceil
import re
from types import SimpleNamespace

from fastapi import HTTPException
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.page import PageMargins
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session, selectinload

from app.libs.dto.fulfillment.shipment_report import (
    ShipmentReportOut, ShipmentReportPackage, ShipmentReportQuery, ShipmentReportRow,
)
from app.libs.enums.fulfillment import ShipmentStatus
from app.core.model_search import model_code_contains
from app.models.shipment_invoice_service import invoice_model_identity
from app.schemas import Customer, Model, Package, SalesOrder, Shipment, ShipmentPackage

TASHKENT = timezone(timedelta(hours=5))
MAX_SHIPMENTS = 10000
MAX_ROWS = 100000
HEADERS = {
    "en": ["Model", "Variant", "Quantity", "Packages", "Package quantities", "Sizes", "Color", "Order", "Customer", "Shipped at (Tashkent)", "Shipment", "Description", "Historical reconstruction"],
    "ru": ["Модель", "Вариант", "Количество", "Упаковки", "Количество по упаковкам", "Размеры", "Цвет", "Заказ", "Клиент", "Дата отгрузки (Ташкент)", "Отгрузка", "Наименование", "Историческая реконструкция"],
    "uz": ["Model", "Variant", "Miqdor", "Paketlar", "Paketlar bo‘yicha miqdor", "O‘lchamlar", "Rang", "Buyurtma", "Mijoz", "Jo‘natilgan vaqt (Toshkent)", "Jo‘natma", "Nomi", "Tarixiy tiklash"],
}

REPORT_TEXT = {
    "en": {"title": "Warehouse shipment report", "period": "Period", "search": "Search",
           "all_dates": "All dates", "all_shipments": "All shipments", "quantity": "Total quantity",
           "packages": "Packages", "shipments": "Shipments", "empty": "No shipments match these filters.",
           "yes": "Yes", "page": "Page &P of &N"},
    "ru": {"title": "Отчёт об отгрузках со склада", "period": "Период", "search": "Поиск",
           "all_dates": "Все даты", "all_shipments": "Все отгрузки", "quantity": "Общее количество",
           "packages": "Упаковки", "shipments": "Отгрузки", "empty": "Нет отгрузок по выбранным фильтрам.",
           "yes": "Да", "page": "Страница &P из &N"},
    "uz": {"title": "Ombordan jo‘natmalar hisoboti", "period": "Davr", "search": "Qidiruv",
           "all_dates": "Barcha sanalar", "all_shipments": "Barcha jo‘natmalar", "quantity": "Jami miqdor",
           "packages": "Paketlar", "shipments": "Jo‘natmalar", "empty": "Bu filtrlarga mos jo‘natmalar yo‘q.",
           "yes": "Ha", "page": "Sahifa &P / &N"},
}


def _historical_documents(db: Session, shipments: list[Shipment]) -> dict[int, dict]:
    """Retain shipment-link quantities when old records lack frozen breakdowns.

    Dispatched counters describe the current remainder, not historical dispatch.
    A legacy partial shipment has no trustworthy size split: show unknown sizes
    instead of attributing today's package contents to the old shipment.
    """
    if not shipments:
        return {}
    orders = {row.id: row for row in db.query(SalesOrder.id, SalesOrder.order_no, SalesOrder.customer_id)
              .filter(SalesOrder.id.in_({row.sales_order_id for row in shipments if row.sales_order_id})).all()}
    customer_ids = {row.customer_id or (orders[row.sales_order_id].customer_id if row.sales_order_id in orders else None) for row in shipments}
    customers = dict(db.query(Customer.id, Customer.name).filter(Customer.id.in_(customer_ids - {None})).all())
    result = {}
    for shipment in shipments:
        order = orders.get(shipment.sales_order_id)
        customer_id = shipment.customer_id or (order.customer_id if order else None)
        result[shipment.id] = {"customer": customers.get(customer_id, shipment.notes or ""),
                               "sales_order_no": order.order_no if order else "", "lines": []}
    links = (db.query(ShipmentPackage, Package, Model)
             .join(Package, Package.id == ShipmentPackage.package_id)
             .outerjoin(Model, Model.id == Package.model_id)
             .options(selectinload(Package.legacy_receipt))
             .filter(ShipmentPackage.shipment_id.in_(result)).order_by(ShipmentPackage.id).all())
    for link, package, model in links:
        model_no, variant_no = invoice_model_identity(model, package.legacy_receipt.source_payload if package.legacy_receipt else {})
        result[link.shipment_id]["lines"].append({
            "model_no": model_no, "variant_no": variant_no,
            "description": model.name if model else "", "color": package.color,
            "package_no": package.package_no, "quantity": link.quantity, "size": "—",
        })
    return result


def report_rows(db: Session, filters: ShipmentReportQuery) -> list[ShipmentReportRow]:
    if filters.date_from and filters.date_to and filters.date_from > filters.date_to:
        raise HTTPException(422, "Start date must not be after end date")
    query = db.query(Shipment).filter(
        Shipment.deleted_at.is_(None),
        Shipment.status.in_((ShipmentStatus.SHIPPED, ShipmentStatus.DELIVERED)),
        Shipment.shipped_at.isnot(None),
    )
    if filters.date_from and filters.date_from != date.min:
        start = datetime.combine(filters.date_from, time.min, TASHKENT).astimezone(timezone.utc)
        query = query.filter(Shipment.shipped_at >= start)
    if filters.date_to and filters.date_to != date.max:
        end = datetime.combine(filters.date_to + timedelta(days=1), time.min, TASHKENT).astimezone(timezone.utc)
        query = query.filter(Shipment.shipped_at < end)
    shipments = query.order_by(Shipment.shipped_at.desc(), Shipment.id.desc()).limit(MAX_SHIPMENTS + 1).all()
    if len(shipments) > MAX_SHIPMENTS:
        raise HTTPException(422, "Choose a shorter shipment date range")
    result: list[ShipmentReportRow] = []
    historical = _historical_documents(db, [row for row in shipments if not (row.dispatch_snapshot or {}).get("document")])
    needle = filters.q.strip().casefold()
    model_needle = re.sub(r"[\s/]+", "-", re.sub(r"(^|[-/\s])v\s*[-=]\s*(?=\d)", r"\1", needle))
    for shipment in shipments:
        frozen = (shipment.dispatch_snapshot or {}).get("document")
        document = frozen or historical[shipment.id]
        groups: dict[tuple[str, str, str, str], dict] = {}
        for line in document.get("lines", []):
            quantity = int(line.get("quantity") or 0)
            if quantity <= 0:
                continue
            parsed_model, parsed_variant = invoice_model_identity(SimpleNamespace(code=line.get("model_code"), details_json={}))
            model = str(line.get("model_no") or parsed_model or "")
            variant = str(line.get("variant_no") or parsed_variant or "")
            description = str(line.get("description") or "")
            color = str(line.get("color") or "")
            key = (model, variant, description, color)
            group = groups.setdefault(key, {"quantity": 0, "packages": defaultdict(int), "sizes": defaultdict(int)})
            group["quantity"] += quantity
            group["packages"][str(line.get("package_no") or "—")] += quantity
            group["sizes"][str(line.get("size_display") or line.get("size") or "—")] += quantity
        for (model, variant, description, color), group in groups.items():
            row = ShipmentReportRow(
                shipment_id=shipment.id, shipment_no=shipment.shipment_no,
                shipped_at=shipment.shipped_at, status=ShipmentStatus(shipment.status),
                order_no=str(document.get("sales_order_no") or ""),
                customer=str(document.get("customer") or ""),
                model=model, variant=variant, description=description, color=color,
                quantity=group["quantity"],
                packages=[ShipmentReportPackage(package_no=name, quantity=qty) for name, qty in group["packages"].items()],
                sizes=dict(group["sizes"]), historical_reconstruction=not bool(frozen),
            )
            fields = [row.shipment_no, row.order_no, row.customer, model, variant, description, color,
                      *row.sizes, *(package.package_no for package in row.packages)]
            if not needle or any(needle in value.casefold() for value in fields) or model_code_contains(f"{model}-{variant}", model_needle):
                result.append(row)
                if len(result) > MAX_ROWS:
                    raise HTTPException(422, "Choose a shorter shipment date range")
    return result


def shipment_report(db: Session, filters: ShipmentReportQuery) -> ShipmentReportOut:
    rows = report_rows(db, filters)
    start = (filters.page - 1) * filters.page_size
    return ShipmentReportOut(
        rows=rows[start:start + filters.page_size], total=len(rows),
        quantity=sum(row.quantity for row in rows),
        package_count=len({(row.shipment_id, package.package_no) for row in rows for package in row.packages}),
        shipment_count=len({row.shipment_id for row in rows}),
        page=filters.page, page_size=filters.page_size,
    )


def shipment_report_workbook(db: Session, filters: ShipmentReportQuery, lang: str) -> bytes:
    rows = report_rows(db, filters)
    locale = lang if lang in HEADERS else "en"
    text = REPORT_TEXT[locale]
    workbook = Workbook()
    workbook.properties.title = text["title"]
    workbook.properties.creator = "Milana ERP"
    sheet = workbook.active
    sheet.title = "Shipments"
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = 85
    header_row = 8
    first_data_row = header_row + 1
    widths = [18, 16, 12, 11, 28, 20, 17, 23, 28, 24, 23, 32, 24]
    body_font = Font(name="Arial", size=10, color="25231F")
    muted_font = Font(name="Arial", size=10, color="625E56")
    row_rule = Side(style="hair", color="E6E3DD")
    shipment_rule = Side(style="thin", color="CFCAC0")

    def literal(cell, value):
        cell.value = value
        # This includes filter text and every user-supplied identifier/description.
        if isinstance(value, str):
            cell.data_type = "s"

    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.row_dimensions[1].height = 8
    literal(sheet["A2"], text["title"])
    sheet["A2"].font = Font(name="Arial", size=16, bold=True, color="25231F")
    sheet.row_dimensions[2].height = 30
    for column in range(1, len(widths) + 1):
        sheet.cell(2, column).border = Border(bottom=shipment_rule)
    if filters.date_from is None and filters.date_to is None:
        period = text["all_dates"]
    elif filters.date_from == filters.date_to:
        period = filters.date_from.isoformat()
    else:
        period = f"{filters.date_from.isoformat() if filters.date_from else '…'} – {filters.date_to.isoformat() if filters.date_to else '…'}"
    for row_no, label, value in ((3, text["period"], period),
                                 (4, text["search"], filters.q.strip() or text["all_shipments"])):
        literal(sheet.cell(row_no, 1), label)
        literal(sheet.cell(row_no, 2), value)
        sheet.cell(row_no, 1).font = Font(name="Arial", size=10, bold=True, color="625E56")
        sheet.cell(row_no, 2).font = body_font
        sheet.cell(row_no, 2).alignment = Alignment(vertical="center")
        sheet.row_dimensions[row_no].height = 21
    # Match the existing report's totals, including shared packs counted once per
    # shipment rather than summing the per-variant package counts below.
    totals = ((1, text["quantity"], sum(row.quantity for row in rows)),
              (4, text["packages"], len({(row.shipment_id, package.package_no) for row in rows for package in row.packages})),
              (7, text["shipments"], len({row.shipment_id for row in rows})))
    for column, label, value in totals:
        literal(sheet.cell(5, column), label)
        sheet.cell(5, column).font = muted_font
        cell = sheet.cell(6, column, value)
        cell.font = Font(name="Arial", size=14, bold=True, color="25231F")
        cell.number_format = "#,##0"
        cell.alignment = Alignment(horizontal="left", vertical="center")
    sheet.row_dimensions[5].height = 19
    sheet.row_dimensions[6].height = 25
    sheet.row_dimensions[7].height = 10
    for column, heading in enumerate(HEADERS[locale], 1):
        cell = sheet.cell(header_row, column)
        literal(cell, heading)
        cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="353127")
        cell.border = Border(right=Side(style="thin", color="FFFFFF"))
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.row_dimensions[header_row].height = 42
    previous_shipment = None
    shaded = True
    for row_index, row in enumerate(rows, first_data_row):
        timestamp = row.shipped_at
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        values = [row.model, row.variant, row.quantity, len(row.packages),
                  "\n".join(f"{pack.package_no}: {pack.quantity}" for pack in row.packages),
                  "\n".join(f"{size}: {qty}" for size, qty in row.sizes.items()),
                  row.color, row.order_no, row.customer,
                  timestamp.astimezone(TASHKENT).replace(tzinfo=None), row.shipment_no,
                  row.description, text["yes"] if row.historical_reconstruction else ""]
        new_shipment = row.shipment_id != previous_shipment
        if new_shipment:
            shaded = not shaded
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row_index, column)
            literal(cell, value)
            cell.font = body_font
            cell.alignment = Alignment(horizontal="right" if column in (3, 4) else "left",
                                       vertical="top", wrap_text=True)
            cell.border = Border(top=shipment_rule if new_shipment and row_index > first_data_row else Side(), bottom=row_rule)
            if shaded:
                cell.fill = PatternFill("solid", fgColor="F7F6F2")
            if column in (3, 4):
                cell.number_format = "#,##0"
        sheet.cell(row_index, 10).number_format = "yyyy-mm-dd hh:mm"
        lines = max(sum(max(1, ceil(len(part) / (widths[column] - 2))) for part in str(value or "").split("\n"))
                    for column, value in enumerate(values))
        sheet.row_dimensions[row_index].height = min(409, max(24, lines * 14 + 8))
        previous_shipment = row.shipment_id
    last_data_row = header_row + len(rows)
    if not rows:
        literal(sheet.cell(first_data_row, 1), text["empty"])
        sheet.cell(first_data_row, 1).font = Font(name="Arial", size=10, italic=True, color="625E56")
        sheet.row_dimensions[first_data_row].height = 28
    sheet.freeze_panes = "C9"
    sheet.auto_filter.ref = f"A{header_row}:M{last_data_row}"
    sheet.print_title_rows = f"{header_row}:{header_row}"
    sheet.print_title_cols = "A:B"
    sheet.print_area = f"A1:M{max(first_data_row, last_data_row)}"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.print_options.horizontalCentered = True
    sheet.page_margins = PageMargins(left=0.25, right=0.25, top=0.4, bottom=0.4, header=0.15, footer=0.2)
    sheet.oddFooter.left.text = "Milana ERP"
    sheet.oddFooter.center.text = text["title"]
    sheet.oddFooter.right.text = text["page"]
    for footer in (sheet.oddFooter.left, sheet.oddFooter.center, sheet.oddFooter.right):
        footer.size = 8
        footer.font = "Arial"
        footer.color = "625E56"
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
