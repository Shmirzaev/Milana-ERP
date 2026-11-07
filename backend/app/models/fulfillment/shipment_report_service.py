"""Read-only shipment history, preferring immutable dispatch evidence.

Only dispatched, undeleted shipments enter this report. Current package balances
must never replace the quantities frozen at dispatch (partial/shared packs).
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
import re
from types import SimpleNamespace

from fastapi import HTTPException
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
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
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Shipments"
    sheet.append(HEADERS.get(lang, HEADERS["en"]))
    for row in rows:
        timestamp = row.shipped_at
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        values = [row.model, row.variant, row.quantity, len(row.packages),
                  "\n".join(f"{pack.package_no}: {pack.quantity}" for pack in row.packages),
                  "\n".join(f"{size}: {qty}" for size, qty in row.sizes.items()),
                  row.color, row.order_no, row.customer,
                  timestamp.astimezone(TASHKENT).replace(tzinfo=None), row.shipment_no,
                  row.description, ("Yes" if row.historical_reconstruction else "") if lang == "en" else
                  ("Да" if row.historical_reconstruction else "") if lang == "ru" else
                  ("Ha" if row.historical_reconstruction else "")]
        sheet.append(values)
        for cell in sheet[sheet.max_row]:
            # User data is always literal, including strings starting with '='.
            if isinstance(cell.value, str):
                cell.data_type = "s"
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        sheet.cell(sheet.max_row, 10).number_format = "yyyy-mm-dd hh:mm"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:M{sheet.max_row}"
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="353127")
        cell.alignment = Alignment(wrap_text=True)
    for index, width in enumerate([20, 18, 14, 12, 34, 24, 20, 23, 30, 25, 25, 35, 24], 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.print_title_rows = "1:1"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
