from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import and_, func, exists
from sqlalchemy.orm import selectinload, aliased

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import (
    FinishedGoodsStock,
    Shipment,
    ShipmentPackage,
    ShipmentScanLog,
    Package,
    PackageItem,
    PackageBarcodeAlias,
    SalesOrder,
    SalesOrderItem,
    StockReservation,
    User,
    Model,
    ModelBOM,
    Customer,
    Invoice,
)
from app.schemas.sales import ShipmentIn, ShipmentOut, ShipmentScanIn, ShipmentScanOut
from app.schemas.shipment_review import ShipmentAmountReview, ShipmentPackageRemoval, ShipmentQuantityReview, ShipmentTransportDetails
from app.services.shipment_review import (
    correct_received_quantity, detach_shipment_package, freeze_dispatch_document, locked_shipment,
    invoice_for_frozen_delivery, review_shipment_amount, shipment_document,
)
from app.services.shipment_invoice import render_shipment_invoice
from app.services.audit import log_action
from app.services.idempotency import replay_idempotent_response, store_idempotent_response
from app.services.numbering import next_shipment_no
from app.services.model_images import model_preview_image_url, model_variant_picture_url
from app.services.packages import format_storage_location, ship_package, mark_delivered
from app.services.workflow import notify_department

router = APIRouter(prefix="/shipments", tags=["shipments"])
_READY_FOR_SHIPMENT_STATUSES = ("received_in_storage", "reserved")
_OPEN_SHIPMENT_STATUSES = ("draft", "created")
_SHIPMENT_ORDER_STATUSES = {
    "confirmed",
    "planning",
    "planning_approved",
    "in_production",
    "production",
    "cutting",
    "sewing",
    "packaging",
    "storage",
    "ready_to_ship",
    "ready",
    "reserved",
}


def _shipment_payload(db: DbSession, sh: Shipment, *, scanned_count: int | None = None) -> dict:
    so = db.get(SalesOrder, sh.sales_order_id) if sh.sales_order_id else None
    customer = db.get(Customer, sh.customer_id or (so.customer_id if so else None)) if (sh.customer_id or (so.customer_id if so else None)) else None
    packages_count = len(sh.packages or [])
    total_qty = sum(int(sp.quantity or 0) for sp in (sh.packages or []))
    if scanned_count is None:
        scanned_count = len(
            _matched_package_ids_for_shipment(db, int(sh.id))
            & {int(sp.package_id) for sp in (sh.packages or []) if sp.package_id is not None}
        )
    remaining_count = max(0, packages_count - scanned_count)
    return {
        "id": sh.id,
        "sales_order_id": sh.sales_order_id,
        "customer_id": sh.customer_id,
        "shipment_no": sh.shipment_no,
        "status": sh.status,
        "shipped_at": sh.shipped_at,
        "delivered_at": sh.delivered_at,
        "notes": sh.notes,
        "transport_details": sh.transport_details or {},
        "created_at": sh.created_at,
        "sales_order_no": so.order_no if so else None,
        "customer_name": customer.name if customer else None,
        "shipment_type": "sales_order" if sh.sales_order_id else "warehouse_exit",
        "packages_count": packages_count,
        "total_qty": total_qty,
        "required_count": packages_count,
        "scanned_count": scanned_count,
        "remaining_count": remaining_count,
        "is_complete": packages_count > 0 and remaining_count == 0,
    }


def _model_identity(model: Model | None) -> tuple[str | None, str | None]:
    if not model:
        return None, None
    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general") if isinstance(details.get("general"), dict) else {}
    code = str(model.code or "").strip()
    code_model_no, separator, code_variant_no = code.rpartition("-")
    if not separator:
        code_model_no, code_variant_no = code, ""
    model_no = str(general.get("model_no") or general.get("modelNo") or code_model_no or "").strip()
    variant_no = str(general.get("variant_no") or general.get("variantNo") or code_variant_no or "").strip()
    return model_no or None, variant_no or None


def _preparation_payload(
    db: DbSession,
    *,
    shipment: Shipment | None = None,
    sales_order: SalesOrder | None = None,
) -> dict:
    if shipment is None and sales_order is None:
        raise ValueError("shipment or sales_order is required")

    sales_order_id = int(shipment.sales_order_id) if shipment and shipment.sales_order_id else None
    if sales_order is None and sales_order_id:
        sales_order = db.get(SalesOrder, sales_order_id)
    if sales_order is not None:
        sales_order_id = int(sales_order.id)

    if shipment is not None:
        linked_rows = (
            db.query(ShipmentPackage, Package)
            .join(Package, Package.id == ShipmentPackage.package_id)
            .filter(ShipmentPackage.shipment_id == shipment.id)
            .order_by(Package.id.asc())
            .all()
        )
        package_rows = [(int(link.quantity or 0), package) for link, package in linked_rows]
        scanned_ids = _matched_package_ids_for_shipment(db, int(shipment.id))
    elif sales_order_id:
        package_rows = [
            (int(package.total_quantity or 0), package)
            for package, _model in _ready_packages_for_sales_order(db, sales_order_id)
        ]
        scanned_ids = set()
    else:
        package_rows = []
        scanned_ids = set()

    package_ids = [int(package.id) for _, package in package_rows]
    package_items = (
        db.query(PackageItem)
        .filter(PackageItem.package_id.in_(package_ids))
        .order_by(PackageItem.package_id.asc(), PackageItem.id.asc())
        .all()
        if package_ids
        else []
    )
    package_items_by_id: dict[int, list[PackageItem]] = {}
    for item in package_items:
        package_items_by_id.setdefault(int(item.package_id), []).append(item)

    order_items = (
        db.query(SalesOrderItem)
        .filter(SalesOrderItem.sales_order_id == sales_order_id)
        .order_by(SalesOrderItem.id.asc())
        .all()
        if sales_order_id
        else []
    )
    model_ids = {
        int(model_id)
        for model_id in [
            *(row.model_id for row in order_items),
            *(package.model_id for _, package in package_rows),
            *(row.model_id for row in package_items),
        ]
        if model_id
    }
    models = (
        db.query(Model)
        .options(
            selectinload(Model.images),
            selectinload(Model.bom).joinedload(ModelBOM.item),
        )
        .filter(Model.id.in_(model_ids))
        .all()
        if model_ids
        else []
    )
    model_by_id = {int(model.id): model for model in models}
    prepared_by_variant: dict[tuple[int, str, str], int] = {}
    for package_quantity, package in package_rows:
        items = package_items_by_id.get(int(package.id), [])
        if items:
            for item in items:
                key = (int(item.model_id), str(item.color or "").strip(), str(item.size or "").strip())
                prepared_by_variant[key] = prepared_by_variant.get(key, 0) + int(item.quantity or 0)
        else:
            key = (int(package.model_id), str(package.color or "").strip(), "")
            prepared_by_variant[key] = prepared_by_variant.get(key, 0) + package_quantity

    required_by_variant: dict[tuple[int, str, str], int] = {}
    if order_items:
        for item in order_items:
            key = (int(item.model_id), str(item.color or "").strip(), str(item.size or "").strip())
            required_by_variant[key] = required_by_variant.get(key, 0) + int(item.quantity or 0)
    else:
        required_by_variant.update(prepared_by_variant)

    variant_keys = list(required_by_variant)
    for key in prepared_by_variant:
        if key not in required_by_variant:
            variant_keys.append(key)

    grouped: dict[int, dict] = {}
    for model_id, color, size in variant_keys:
        model = model_by_id.get(model_id)
        model_no, variant_no = _model_identity(model)
        group = grouped.setdefault(
            model_id,
            {
                "model_id": model_id,
                "model_code": model.code if model else None,
                "model_no": model_no,
                "variant_no": variant_no,
                "model_name": model.name if model else None,
                "model_image_url": model_preview_image_url(model) or model_variant_picture_url(model),
                "variant_image_url": model_variant_picture_url(model),
                "required_qty": 0,
                "prepared_qty": 0,
                "packages_count": 0,
                "requested_pack_count": sum(int(getattr(line, "requested_pack_count", None) or 0)
                                             for line in order_items if line.model_id == model_id) or None,
                "scanned_packages_count": 0,
                "lines": [],
            },
        )
        required_qty = int(required_by_variant.get((model_id, color, size), 0))
        prepared_qty = int(prepared_by_variant.get((model_id, color, size), 0))
        group["required_qty"] += required_qty
        group["prepared_qty"] += prepared_qty
        group["lines"].append(
            {
                "color": color or None,
                "size": size or None,
                "required_qty": required_qty,
                "prepared_qty": prepared_qty,
            }
        )

    packages: list[dict] = []
    for package_quantity, package in package_rows:
        model = model_by_id.get(int(package.model_id))
        model_no, variant_no = _model_identity(model)
        item_lines = [
            {
                "color": str(item.color or "").strip() or None,
                "size": str(item.size or "").strip() or None,
                "quantity": int(item.quantity or 0),
            }
            for item in package_items_by_id.get(int(package.id), [])
        ]
        packages.append(
            {
                "id": int(package.id),
                "package_no": package.package_no,
                "model_id": int(package.model_id),
                "model_code": model.code if model else None,
                "model_no": model_no,
                "variant_no": variant_no,
                "model_name": model.name if model else None,
                "model_image_url": model_preview_image_url(model) or model_variant_picture_url(model),
                "variant_image_url": model_variant_picture_url(model),
                "color": package.color,
                "quantity": package_quantity,
                "status": package.status,
                "location": format_storage_location(package.storage_cell, package.storage_shelf),
                "scanned": int(package.id) in scanned_ids,
                "items": item_lines,
                "quantity_items": [{"item_id": item.id, "color": item.color, "size": item.size,
                                    "quantity": item.quantity} for item in package_items_by_id.get(int(package.id), [])],
            }
        )
        group = grouped.get(int(package.model_id))
        if group:
            group["packages_count"] += 1
            if int(package.id) in scanned_ids:
                group["scanned_packages_count"] += 1

    if shipment is not None:
        required_count, scanned_count, remaining_count, is_complete, _, _ = _scan_progress(db, shipment)
        shipment_payload = _shipment_payload(db, shipment, scanned_count=scanned_count)
    else:
        required_count = len(package_rows)
        scanned_count = 0
        remaining_count = required_count
        is_complete = False
        customer = db.get(Customer, sales_order.customer_id) if sales_order and sales_order.customer_id else None
        shipment_payload = {
            "id": 0,
            "sales_order_id": sales_order_id,
            "sales_order_no": sales_order.order_no if sales_order else None,
            "customer_name": customer.name if customer else None,
            "shipment_no": None,
            "status": "not_created",
            "packages_count": required_count,
            "total_qty": sum(quantity for quantity, _package in package_rows),
        }
    return {
        "shipment": shipment_payload,
        "items": list(grouped.values()),
        "packages": packages,
        "required_count": required_count,
        "scanned_count": scanned_count,
        "remaining_count": remaining_count,
        "is_complete": is_complete,
        "is_preview": shipment is None,
        "review": shipment_document(db, shipment, scanned_ids=scanned_ids) if shipment else None,
    }


def _shipment_preparation_payload(db: DbSession, sh: Shipment) -> dict:
    return _preparation_payload(db, shipment=sh)


def _commit_scan_response(
    db: DbSession,
    *,
    current: User,
    idempotency_key: str | None,
    fingerprint_payload: dict,
    response: ShipmentScanOut,
) -> ShipmentScanOut:
    store_idempotent_response(
        db,
        scope="shipments.scan-package",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response.model_dump(mode="json"),
        user=current,
    )
    db.commit()
    return response


def _order_has_ready_packages(db: DbSession, sales_order_id: int) -> bool:
    return len(_ready_packages_for_sales_order(db, sales_order_id)) > 0


def _sales_order_ids_with_shipments(db: DbSession) -> set[int]:
    rows = (
        db.query(Shipment.sales_order_id)
        .filter(Shipment.sales_order_id.isnot(None), Shipment.status != "cancelled")
        .distinct()
        .all()
    )
    return {int(sales_order_id) for (sales_order_id,) in rows if sales_order_id is not None}


def _shipment_exists_for_sales_order(db: DbSession, sales_order_id: int) -> bool:
    return (
        db.query(Shipment.id)
        .filter(Shipment.sales_order_id == sales_order_id, Shipment.status != "cancelled")
        .first()
        is not None
    )


def _other_open_shipment_for_package(
    db: DbSession,
    package_id: int,
    *,
    shipment_id: int | None = None,
) -> Shipment | None:
    qry = (
        db.query(Shipment)
        .join(ShipmentPackage, ShipmentPackage.shipment_id == Shipment.id)
        .filter(
            ShipmentPackage.package_id == package_id,
            Shipment.status.in_(_OPEN_SHIPMENT_STATUSES),
        )
    )
    if shipment_id is not None:
        qry = qry.filter(Shipment.id != shipment_id)
    return qry.order_by(Shipment.id.asc()).first()


def _lock_package(db: DbSession, package: Package) -> Package:
    if db.bind and db.bind.dialect.name == "postgresql":
        return (
            db.query(Package)
            .filter(Package.id == package.id)
            .with_for_update(of=Package)
            .one()
        )
    return package


def _orderless_package_error(db: DbSession, package: Package) -> str | None:
    if package.sales_order_id:
        return f"Package {package.package_no} belongs to a sales order and must use its sales shipment."
    if package.status != "received_in_storage":
        return f"Package {package.package_no} is not unreserved warehouse stock."
    reserved = (
        db.query(StockReservation.id)
        .filter(
            StockReservation.package_id == package.id,
            StockReservation.quantity > 0,
        )
        .first()
    )
    if reserved:
        return f"Package {package.package_no} is reserved for a sales order."
    stock_count, available_qty, reserved_qty = (
        db.query(
            func.count(FinishedGoodsStock.id),
            func.coalesce(func.sum(FinishedGoodsStock.available_qty), 0),
            func.coalesce(func.sum(FinishedGoodsStock.reserved_qty), 0),
        )
        .filter(FinishedGoodsStock.package_id == package.id)
        .one()
    )
    if (
        int(stock_count or 0) <= 0
        or int(available_qty or 0) != int(package.total_quantity or 0)
        or int(reserved_qty or 0) != 0
    ):
        return f"Package {package.package_no} is not fully available in finished-goods stock."
    return None


def _package_attachment_error(db: DbSession, shipment: Shipment, package: Package) -> str | None:
    other = _other_open_shipment_for_package(db, int(package.id), shipment_id=int(shipment.id))
    if other:
        return f"Package {package.package_no} is already attached to shipment {other.shipment_no}."
    if not shipment.sales_order_id:
        return _orderless_package_error(db, package)
    if package.sales_order_id and package.sales_order_id != shipment.sales_order_id:
        return f"Package {package.package_no} belongs to another sales order."
    return None


def _ready_packages_for_sales_order(db: DbSession, sales_order_id: int) -> list[tuple[Package, Model | None]]:
    statuses = _READY_FOR_SHIPMENT_STATUSES
    pkg_ids_from_reservations = [
        int(pid)
        for (pid,) in (
            db.query(StockReservation.package_id)
            .filter(
                StockReservation.sales_order_id == sales_order_id,
                StockReservation.package_id.isnot(None),
            )
            .group_by(StockReservation.package_id)
            .all()
        )
        if pid is not None
    ]

    rows: dict[int, tuple[Package, Model | None]] = {}
    if pkg_ids_from_reservations:
        for pkg, model in (
            db.query(Package, Model)
            .join(Model, Model.id == Package.model_id)
            .filter(Package.id.in_(pkg_ids_from_reservations), Package.status.in_(statuses))
            .order_by(Package.id.asc())
            .all()
        ):
            rows[int(pkg.id)] = (pkg, model)

    for pkg, model in (
        db.query(Package, Model)
        .join(Model, Model.id == Package.model_id)
        .filter(Package.sales_order_id == sales_order_id, Package.status.in_(statuses))
        .order_by(Package.id.asc())
        .all()
    ):
        rows.setdefault(int(pkg.id), (pkg, model))

    return [rows[k] for k in sorted(rows.keys())]


def _scan_code_candidates(raw_code: str) -> list[str]:
    code = (raw_code or "").strip()
    if not code:
        return []
    candidates: list[str] = [code]
    if "|" in code:
        candidates.extend([p.strip() for p in code.split("|") if p.strip()])
    upper = code.upper()
    if upper.startswith("PACKAGE:"):
        payload = code.split(":", 1)[1]
        candidates.extend([p.strip() for p in payload.split("|") if p.strip()])

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        token = candidate.strip()
        if token and token not in seen:
            seen.add(token)
            unique.append(token)
    return unique


def _find_package_for_scan(
    db: DbSession,
    raw_code: str,
    *,
    shipment_id: int | None = None,
) -> tuple[Package | None, str]:
    for candidate in _scan_code_candidates(raw_code):
        pkg = db.query(Package).filter((Package.barcode == candidate) | (Package.package_no == candidate)).first()
        if pkg:
            return pkg, candidate

        alias_package_ids = [
            int(package_id)
            for (package_id,) in (
                db.query(PackageBarcodeAlias.package_id)
                .filter(PackageBarcodeAlias.code == candidate)
                .order_by(PackageBarcodeAlias.package_id.asc())
                .all()
            )
        ]
        if not alias_package_ids:
            continue

        if shipment_id is not None:
            attached_ids = {
                int(package_id)
                for (package_id,) in (
                    db.query(ShipmentPackage.package_id)
                    .filter(
                        ShipmentPackage.shipment_id == shipment_id,
                        ShipmentPackage.package_id.in_(alias_package_ids),
                    )
                    .all()
                )
            }
            already_scanned = _matched_package_ids_for_shipment(db, shipment_id)
            remaining_ids = sorted(attached_ids - already_scanned)
            if remaining_ids:
                return db.get(Package, remaining_ids[0]), candidate

        if len(alias_package_ids) == 1:
            return db.get(Package, alias_package_ids[0]), candidate
    return None, (raw_code or "").strip()


def _valid_matched_scan():
    later = aliased(ShipmentScanLog)
    return and_(ShipmentScanLog.scan_result == "matched", ~exists().where(
        later.shipment_id == ShipmentScanLog.shipment_id,
        later.package_id == ShipmentScanLog.package_id,
        later.scan_result == "detached", later.id > ShipmentScanLog.id,
    ))


def _matched_package_ids_for_shipment(db: DbSession, shipment_id: int) -> set[int]:
    matched_rows = (
        db.query(ShipmentScanLog.package_id)
        .filter(
            ShipmentScanLog.shipment_id == shipment_id,
            _valid_matched_scan(),
            ShipmentScanLog.package_id.isnot(None),
        )
        .group_by(ShipmentScanLog.package_id)
        .all()
    )
    return {int(pid) for (pid,) in matched_rows if pid is not None}


def _scan_progress(db: DbSession, shipment: Shipment) -> tuple[int, int, int, bool, set[int], set[int]]:
    attached_ids = {int(sp.package_id) for sp in shipment.packages if sp.package_id is not None}
    if not attached_ids:
        return 0, 0, 0, False, set(), set()

    matched_scanned_ids = _matched_package_ids_for_shipment(db, int(shipment.id))
    scanned_for_attached = attached_ids & matched_scanned_ids
    required_count = len(attached_ids)
    scanned_count = len(scanned_for_attached)
    remaining_count = max(0, required_count - scanned_count)
    return required_count, scanned_count, remaining_count, remaining_count == 0, attached_ids, scanned_for_attached


def _finished_goods_rows_for_package(db: DbSession, package_id: int, *, available_only: bool = False) -> list[FinishedGoodsStock]:
    qry = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package_id)
    if available_only:
        qry = qry.filter(FinishedGoodsStock.available_qty > 0, FinishedGoodsStock.status == "available")
    if db.bind and db.bind.dialect.name == "postgresql":
        qry = qry.with_for_update(of=FinishedGoodsStock)
    return qry.order_by(FinishedGoodsStock.id.asc()).all()


def _move_package_reservations(
    db: DbSession,
    *,
    sales_order_id: int | None,
    from_package_id: int,
    to_package: Package,
    reserved_by: int | None,
) -> str | None:
    if not sales_order_id:
        return None

    old_reservations = (
        db.query(StockReservation)
        .filter(
            StockReservation.sales_order_id == sales_order_id,
            StockReservation.package_id == from_package_id,
        )
        .order_by(StockReservation.id.asc())
        .all()
    )
    pack_line = db.query(SalesOrderItem).filter_by(sales_order_id=sales_order_id, model_id=to_package.model_id).filter(
        SalesOrderItem.requested_pack_count.isnot(None)).first()
    required_qty = int(to_package.total_quantity) if pack_line else sum(int(row.quantity or 0) for row in old_reservations)
    if required_qty <= 0:
        return None

    new_stock_rows = _finished_goods_rows_for_package(db, int(to_package.id), available_only=True)
    available_qty = sum(int(row.available_qty or 0) for row in new_stock_rows)
    if pack_line and (available_qty != to_package.total_quantity or
                      any(row.reserved_qty or row.sold_qty or row.quantity != row.available_qty for row in new_stock_rows) or
                      (pack_line.brand_id is not None and to_package.brand_id != pack_line.brand_id)):
        return f"Package {to_package.package_no} is not an intact available package for this order."
    if available_qty < required_qty:
        return f"Package {to_package.package_no} matches the model but has only {available_qty} available pcs."

    old_stock_by_id = {
        int(row.id): row
        for row in _finished_goods_rows_for_package(db, from_package_id)
    }
    for reservation in old_reservations:
        qty = int(reservation.quantity or 0)
        old_stock = old_stock_by_id.get(int(reservation.finished_goods_stock_id))
        if old_stock:
            old_stock.reserved_qty = max(0, int(old_stock.reserved_qty or 0) - qty)
            old_stock.available_qty = int(old_stock.available_qty or 0) + qty
            if int(old_stock.available_qty or 0) > 0:
                old_stock.status = "available"
        db.delete(reservation)

    remaining = required_qty
    for stock in new_stock_rows:
        if remaining <= 0:
            break
        take = min(remaining, int(stock.available_qty or 0))
        if take <= 0:
            continue
        stock.available_qty = int(stock.available_qty or 0) - take
        stock.reserved_qty = int(stock.reserved_qty or 0) + take
        if int(stock.available_qty or 0) == 0:
            stock.status = "reserved"
        db.add(
            StockReservation(
                sales_order_id=sales_order_id,
                finished_goods_stock_id=stock.id,
                package_id=to_package.id,
                quantity=take,
                reserved_by=reserved_by,
            )
        )
        remaining -= take

    return None


def _replace_unscanned_same_model_package(
    db: DbSession,
    *,
    shipment: Shipment,
    scanned_package: Package,
    current: User,
) -> tuple[ShipmentPackage | None, str | None]:
    matched_ids = _matched_package_ids_for_shipment(db, int(shipment.id))
    qry = (
        db.query(ShipmentPackage)
        .join(Package, Package.id == ShipmentPackage.package_id)
        .filter(
            ShipmentPackage.shipment_id == shipment.id,
            ShipmentPackage.package_id != scanned_package.id,
            Package.model_id == scanned_package.model_id,
        )
        .order_by(ShipmentPackage.id.asc())
    )
    if matched_ids:
        qry = qry.filter(ShipmentPackage.package_id.notin_(matched_ids))
    slot = qry.first()
    if not slot:
        return None, None

    reservation_error = _move_package_reservations(
        db,
        sales_order_id=int(shipment.sales_order_id) if shipment.sales_order_id else None,
        from_package_id=int(slot.package_id),
        to_package=scanned_package,
        reserved_by=current.id,
    )
    if reservation_error:
        return None, reservation_error

    old_package_id = int(slot.package_id)
    slot.package_id = int(scanned_package.id)
    slot.quantity = int(scanned_package.total_quantity or 0)
    db.flush()
    log_action(
        db,
        current,
        "replace_package_scan",
        "Shipment",
        shipment.id,
        new_value={
            "from_package_id": old_package_id,
            "to_package_id": int(scanned_package.id),
            "model_id": int(scanned_package.model_id),
        },
    )
    return slot, None


def _scan_response(
    *,
    ok: bool,
    sign: str,
    code: str,
    message: str,
    package: Package | None,
    package_model_code: str | None,
    required_count: int,
    scanned_count: int,
    remaining_count: int,
    is_complete: bool,
) -> ShipmentScanOut:
    return ShipmentScanOut(
        ok=ok,
        sign=sign,
        code=code,
        message=message,
        package_id=int(package.id) if package else None,
        package_no=package.package_no if package else None,
        package_model_code=package_model_code,
        required_count=required_count,
        scanned_count=scanned_count,
        remaining_count=remaining_count,
        is_complete=is_complete,
    )


def _ship_verified_packages(db: DbSession, shipment: Shipment, current: User) -> tuple[int, int]:
    if str(shipment.status or "") not in _OPEN_SHIPMENT_STATUSES:
        raise HTTPException(409, f"Shipment {shipment.shipment_no} cannot ship from status '{shipment.status}'")

    required_count, scanned_count, remaining_count, _, attached_ids, scanned_attached = _scan_progress(db, shipment)
    if required_count <= 0:
        raise HTTPException(400, "Shipment has no packages to ship")
    if remaining_count > 0:
        missing_ids = sorted(attached_ids - scanned_attached)
        missing_rows = db.query(Package.package_no).filter(Package.id.in_(missing_ids)).all()
        missing_nos = [str(no) for (no,) in missing_rows if no]
        suffix = ", ".join(missing_nos[:10]) if missing_nos else f"{remaining_count} package(s)"
        raise HTTPException(
            409,
            f"Scan all shipment packages before shipping. Missing scan for: {suffix}",
        )

    db.query(Package).filter(Package.id.in_(attached_ids)).order_by(Package.id).with_for_update().populate_existing().all()
    packages: list[Package] = []
    for shipment_package in sorted(shipment.packages, key=lambda row: row.package_id):
        package = db.get(Package, shipment_package.package_id)
        if not package:
            raise HTTPException(409, f"Shipment package #{shipment_package.package_id} no longer exists")
        package = _lock_package(db, package)
        if package.status not in _READY_FOR_SHIPMENT_STATUSES:
            raise HTTPException(409, f"Package {package.package_no} is no longer ready to ship")
        stocks = _finished_goods_rows_for_package(db, package.id)
        if (shipment_package.quantity != package.total_quantity or not stocks or
                sum(row.available_qty + row.reserved_qty for row in stocks) != package.total_quantity or
                any(row.sold_qty or row.quantity != row.available_qty + row.reserved_qty for row in stocks)):
            raise HTTPException(409, f"Package {package.package_no} quantities do not match warehouse stock")
        foreign_reservation = db.query(StockReservation.id).filter(
            StockReservation.package_id == package.id,
            StockReservation.sales_order_id != shipment.sales_order_id if shipment.sales_order_id else StockReservation.quantity > 0,
        ).first()
        if foreign_reservation:
            raise HTTPException(409, f"Package {package.package_no} is reserved for another order")
        packages.append(package)

    if shipment.sales_order_id:
        order = db.query(SalesOrder).filter_by(id=shipment.sales_order_id).with_for_update().one()
        order_lines = db.query(SalesOrderItem).filter_by(sales_order_id=order.id).with_for_update().all()
        if any(line.requested_pack_count is not None for line in order_lines) and any(
            package.model_id not in {line.model_id for line in order_lines} for package in packages
        ):
            raise HTTPException(409, "Shipment contains a model not requested by this order")
        changed = []
        for line in order_lines:
            requested = getattr(line, "requested_pack_count", None)
            if requested is None:
                continue
            matching = [package for package in packages if package.model_id == line.model_id]
            if len(matching) != requested:
                raise HTTPException(409, f"Model requires exactly {requested} verified packages")
            actual = sum(package.total_quantity for package in matching)
            changed.append({"item_id": line.id, "previous_quantity": line.quantity, "quantity": actual})
            line.quantity = actual
        if changed:
            from decimal import Decimal
            previous_amount = str(order.total_amount)
            order.total_amount = sum(Decimal(str(line.unit_price)) * line.quantity for line in order_lines)
            log_action(db, current, "reconcile_scanned_sales_quantities", "SalesOrder", order.id,
                       old_value={"total_amount": previous_amount},
                       new_value={"items": changed, "total_amount": str(order.total_amount), "shipment_id": shipment.id})
            db.flush()
    shipment.status = "shipped"
    shipment.shipped_at = datetime.now(timezone.utc)
    freeze_dispatch_document(db, shipment)
    for package in packages:
        ship_package(db, package, current.id)
    return required_count, scanned_count


@router.get("", response_model=list[ShipmentOut])
def list_shipments(db: DbSession, _: CurrentUser, sales_order_id: int | None = None):
    qry = db.query(Shipment).options(selectinload(Shipment.packages))
    if sales_order_id:
        qry = qry.filter(Shipment.sales_order_id == sales_order_id)
    rows = qry.order_by(Shipment.id.desc()).all()
    shipment_ids = [int(sh.id) for sh in rows]
    scanned_by_shipment = (
        {
            int(shipment_id): int(count or 0)
            for shipment_id, count in (
                db.query(
                    ShipmentScanLog.shipment_id,
                    func.count(func.distinct(ShipmentScanLog.package_id)),
                )
                .join(
                    ShipmentPackage,
                    and_(
                        ShipmentPackage.shipment_id == ShipmentScanLog.shipment_id,
                        ShipmentPackage.package_id == ShipmentScanLog.package_id,
                    ),
                )
                .filter(
                    ShipmentScanLog.shipment_id.in_(shipment_ids),
                    _valid_matched_scan(),
                )
                .group_by(ShipmentScanLog.shipment_id)
                .all()
            )
        }
        if shipment_ids
        else {}
    )
    return [
        _shipment_payload(db, sh, scanned_count=scanned_by_shipment.get(int(sh.id), 0))
        for sh in rows
    ]


@router.get("/eligible-orders")
def eligible_orders(db: DbSession, _: CurrentUser):
    shipment_so_ids = _sales_order_ids_with_shipments(db)
    package_rows = (
        db.query(Package.sales_order_id, func.coalesce(func.sum(Package.total_quantity), 0))
        .filter(Package.sales_order_id.isnot(None), Package.status.in_(_READY_FOR_SHIPMENT_STATUSES))
        .group_by(Package.sales_order_id)
        .all()
    )
    package_qty_by_so = {
        int(sid): int(qty or 0)
        for sid, qty in package_rows
        if sid is not None and int(sid) not in shipment_so_ids
    }
    so_ids = set(package_qty_by_so.keys())
    qry = db.query(SalesOrder, Customer).outerjoin(Customer, Customer.id == SalesOrder.customer_id)
    if shipment_so_ids:
        qry = qry.filter(SalesOrder.id.notin_(list(shipment_so_ids)))
    if so_ids:
        qry = qry.filter((SalesOrder.status.in_(_SHIPMENT_ORDER_STATUSES)) | (SalesOrder.id.in_(so_ids)))
    else:
        qry = qry.filter(SalesOrder.status.in_(_SHIPMENT_ORDER_STATUSES))
    rows = qry.order_by(SalesOrder.id.desc()).all()
    return [
        {
            "id": so.id,
            "order_no": so.order_no,
            "customer_id": so.customer_id,
            "customer_name": customer.name if customer else None,
            "status": so.status,
            "total_amount": float(so.total_amount or 0),
            "ready_qty": package_qty_by_so.get(int(so.id), 0),
        }
        for so, customer in rows
    ]


@router.get("/ready-packages")
def ready_packages(db: DbSession, _: CurrentUser, sales_order_id: int | None = None):
    if sales_order_id:
        rows = _ready_packages_for_sales_order(db, int(sales_order_id))
    else:
        reserved_package_ids = db.query(StockReservation.package_id).filter(
            StockReservation.package_id.isnot(None),
            StockReservation.quantity > 0,
        )
        attached_package_ids = (
            db.query(ShipmentPackage.package_id)
            .join(Shipment, Shipment.id == ShipmentPackage.shipment_id)
            .filter(Shipment.status.in_(_OPEN_SHIPMENT_STATUSES))
        )
        rows = (
            db.query(Package, Model)
            .join(Model, Model.id == Package.model_id)
            .filter(
                Package.status == "received_in_storage",
                Package.sales_order_id.is_(None),
                Package.id.notin_(reserved_package_ids),
                Package.id.notin_(attached_package_ids),
            )
            .order_by(Package.id.asc())
            .all()
        )
    return [
        {
            "id": p.id,
            "package_no": p.package_no,
            "sales_order_id": p.sales_order_id,
            "model_id": p.model_id,
            "model_code": model.code if model else None,
            "color": p.color,
            "total_quantity": p.total_quantity,
            "status": p.status,
            "storage_cell": p.storage_cell,
            "storage_shelf": p.storage_shelf,
        }
        for p, model in rows
    ]


@router.post("", response_model=ShipmentOut, status_code=201)
def create_shipment(
    payload: ShipmentIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.shipment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = payload.model_dump(mode="json")
    # Serialize every create for this order before replay/existence checks. A
    # waiter must refresh its cached order and see the first transaction's
    # idempotency record or shipment after that transaction commits.
    so = (
        db.query(SalesOrder)
        .filter(SalesOrder.id == payload.sales_order_id)
        .with_for_update(of=SalesOrder)
        .populate_existing()
        .first()
        if payload.sales_order_id else None
    )
    if payload.sales_order_id and not so:
        raise HTTPException(404, "Sales order not found")
    replay = replay_idempotent_response(db, scope="shipments.create", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    if not payload.sales_order_id and not str(payload.notes or "").strip():
        raise HTTPException(400, "Recipient or warehouse exit reference is required")
    if so:
        if _shipment_exists_for_sales_order(db, int(so.id)):
            raise HTTPException(409, f"Shipment already exists for {so.order_no}")
        status_ok = str(so.status or "") in _SHIPMENT_ORDER_STATUSES
        if not status_ok and not _order_has_ready_packages(db, int(so.id)):
            raise HTTPException(409, "Sales order has no ready-to-ship packages")
    sh = Shipment(
        sales_order_id=payload.sales_order_id,
        customer_id=payload.customer_id or (so.customer_id if so else None),
        shipment_no=next_shipment_no(db),
        status="created",
        notes=payload.notes,
        transport_details=payload.transport_details.model_dump() if payload.transport_details else None,
    )
    db.add(sh); db.flush()
    added = 0
    if so:
        for pkg, _ in _ready_packages_for_sales_order(db, int(so.id)):
            exists = db.query(ShipmentPackage.id).filter(
                ShipmentPackage.shipment_id == sh.id,
                ShipmentPackage.package_id == pkg.id,
            ).first()
            if exists:
                continue
            db.add(ShipmentPackage(shipment_id=sh.id, package_id=pkg.id, quantity=pkg.total_quantity))
            added += 1
    log_action(
        db,
        current,
        "create",
        "Shipment",
        sh.id,
        new_value={
            "shipment_no": sh.shipment_no,
            "shipment_type": "sales_order" if sh.sales_order_id else "warehouse_exit",
            "packages": added,
            "notes": sh.notes,
            "transport_details": sh.transport_details,
        },
    )
    db.flush()
    db.refresh(sh)
    response = _shipment_payload(db, sh)
    store_idempotent_response(
        db,
        scope="shipments.create",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
        status_code=201,
    )
    db.commit()
    return response


@router.patch("/{sid}", response_model=ShipmentOut)
def update_shipment(
    sid: int,
    payload: dict,
    db: DbSession,
    current: User = Depends(require_permissions("storage.shipment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = {"shipment_id": sid, "payload": payload}
    replay = replay_idempotent_response(db, scope="shipments.update", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    sh = locked_shipment(db, sid)
    if sh.status not in _OPEN_SHIPMENT_STATUSES:
        raise HTTPException(409, "Dispatched shipment metadata is frozen")
    if set(payload) - {"notes", "transport_details"}:
        raise HTTPException(422, "Only shipment notes and transport details may be edited; use validated workflow actions")
    notes = payload.get("notes", sh.notes)
    if notes is not None and (not isinstance(notes, str) or len(notes) > 4000):
        raise HTTPException(422, "Notes must be text up to 4000 characters")
    if not sh.sales_order_id and not str(notes or "").strip():
        raise HTTPException(422, "Warehouse exit reference is required")
    previous_notes = sh.notes
    previous_transport = sh.transport_details
    if "transport_details" in payload:
        try:
            transport = ShipmentTransportDetails.model_validate(payload["transport_details"]).model_dump() if payload["transport_details"] is not None else None
        except ValidationError:
            raise HTTPException(422, "Transport details allow driver_name, vehicle_info, cargo_name (up to 200 characters), driver_phone (up to 50), or null")
        sh.transport_details = transport if transport and any(transport.values()) else None
    sh.notes = notes
    log_action(db, current, "update", "Shipment", sh.id,
               old_value={"notes": previous_notes, "transport_details": previous_transport},
               new_value={"notes": notes, "transport_details": sh.transport_details})
    db.flush()
    response = _shipment_payload(db, sh)
    store_idempotent_response(
        db,
        scope="shipments.update",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
    )
    db.commit(); db.refresh(sh)
    return response


@router.post("/{sid}/add-package")
def add_package(
    sid: int,
    package_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("storage.shipment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = {"shipment_id": sid, "package_id": package_id}
    replay = replay_idempotent_response(db, scope="shipments.add-package", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    sh = locked_shipment(db, sid)
    if not sh: raise HTTPException(404, "Shipment not found")
    pkg = db.get(Package, package_id)
    if not pkg: raise HTTPException(404, "Package not found")
    pkg = _lock_package(db, pkg)
    if pkg.status not in _READY_FOR_SHIPMENT_STATUSES:
        raise HTTPException(409, f"Package {pkg.package_no} is not ready to ship")
    attachment_error = _package_attachment_error(db, sh, pkg)
    if attachment_error:
        raise HTTPException(409, attachment_error)
    exists = db.query(ShipmentPackage).filter(
        ShipmentPackage.shipment_id == sh.id, ShipmentPackage.package_id == pkg.id,
    ).first()
    if exists:
        raise HTTPException(409, "Package already attached to this shipment")
    db.add(ShipmentPackage(shipment_id=sh.id, package_id=pkg.id, quantity=pkg.total_quantity))
    log_action(db, current, "add_package", "Shipment", sh.id, new_value={"package_id": pkg.id})
    response = {"message": "added"}
    store_idempotent_response(
        db,
        scope="shipments.add-package",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
    )
    db.commit()
    return response


@router.post("/{sid}/add-ready-packages")
def add_ready_packages(
    sid: int,
    db: DbSession,
    current: User = Depends(require_permissions("storage.shipment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = {"shipment_id": sid}
    replay = replay_idempotent_response(db, scope="shipments.add-ready-packages", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    sh = locked_shipment(db, sid)
    if not sh: raise HTTPException(404, "Shipment not found")
    if sh.status not in _OPEN_SHIPMENT_STATUSES:
        raise HTTPException(409, "Packages can only be added before shipment")
    if not sh.sales_order_id:
        raise HTTPException(400, "Shipment has no sales_order_id")
    attached = {sp.package_id for sp in sh.packages}
    ready = [pkg for pkg, _ in _ready_packages_for_sales_order(db, int(sh.sales_order_id))]
    ready_ids = {pkg.id for pkg in ready}
    added = 0
    for p in ready:
        if p.id in attached:
            continue
        db.add(ShipmentPackage(shipment_id=sh.id, package_id=p.id, quantity=p.total_quantity))
        added += 1
    reported = added if added > 0 else len(attached & ready_ids)
    log_action(db, current, "add_ready_packages", "Shipment", sh.id, new_value={"added": added, "ready_attached": reported})
    response = {"added": reported}
    store_idempotent_response(
        db,
        scope="shipments.add-ready-packages",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
    )
    db.commit()
    return response


@router.get("/sales-order/{sales_order_id}/preparation")
def sales_order_preparation(sales_order_id: int, db: DbSession, _: CurrentUser):
    sales_order = db.get(SalesOrder, sales_order_id)
    if not sales_order:
        raise HTTPException(404, "Sales order not found")
    return _preparation_payload(db, sales_order=sales_order)


@router.get("/{sid}/preparation")
def shipment_preparation(sid: int, db: DbSession, _: CurrentUser):
    sh = db.get(Shipment, sid)
    if not sh:
        raise HTTPException(404, "Shipment not found")
    return _shipment_preparation_payload(db, sh)


@router.post("/{sid}/packages/{pid}/quantity")
def review_package_quantity(sid: int, pid: int, payload: ShipmentQuantityReview, db: DbSession,
                            current: User = Depends(require_permissions("storage.shipment", "*"))):
    shipment = locked_shipment(db, sid)
    if pid not in _matched_package_ids_for_shipment(db, sid):
        raise HTTPException(409, "Scan the package before reviewing its quantity")
    correct_received_quantity(db, shipment, pid, payload, current)
    db.commit()
    return _shipment_preparation_payload(db, shipment)


@router.post("/{sid}/review-amount")
def review_amount(sid: int, payload: ShipmentAmountReview, db: DbSession,
                  current: User = Depends(require_permissions("storage.shipment", "*"))):
    shipment = locked_shipment(db, sid)
    document = shipment_document(db, shipment, scanned_ids=_matched_package_ids_for_shipment(db, sid))
    review_shipment_amount(db, shipment, document, payload, current)
    db.commit()
    return _shipment_preparation_payload(db, shipment)


@router.post("/{sid}/packages/{pid}/remove")
def remove_reviewed_package(sid: int, pid: int, payload: ShipmentPackageRemoval, db: DbSession,
                            current: User = Depends(require_permissions("storage.shipment", "*"))):
    shipment = locked_shipment(db, sid)
    detach_shipment_package(db, shipment, pid, payload.reason, current)
    db.commit()
    return _shipment_preparation_payload(db, shipment)


def _printed_document(db: DbSession, shipment: Shipment) -> dict:
    if shipment.status not in {"shipped", "delivered"}:
        raise HTTPException(409, "Invoice printing is available after shipment")
    frozen = (shipment.dispatch_snapshot or {}).get("document")
    if frozen:
        document = dict(frozen)
        if shipment.status == "delivered":
            invoice = db.query(Invoice).filter_by(sales_order_id=shipment.sales_order_id).first() if shipment.sales_order_id else None
            if invoice:
                document["finance_posting_status"] = "posted"
                document["ledger_invoice_no"] = invoice.invoice_no
        return document
    document = shipment_document(db, shipment)
    document["historical_reconstruction"] = True
    return document


@router.get("/{sid}/invoice")
def shipment_invoice(sid: int, db: DbSession,
                      _: User = Depends(require_permissions("storage.shipment", "sales.orders", "finance.view", "*"))):
    shipment = db.get(Shipment, sid)
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    return _printed_document(db, shipment)


@router.get("/{sid}/invoice/print", response_class=HTMLResponse)
def print_shipment_invoice(sid: int, db: DbSession, lang: str = "en",
                            _: User = Depends(require_permissions("storage.shipment", "sales.orders", "finance.view", "*"))):
    shipment = db.get(Shipment, sid)
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    return HTMLResponse(render_shipment_invoice(_printed_document(db, shipment), lang),
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/{sid}/scan-status", response_model=ShipmentScanOut)
def scan_status(sid: int, db: DbSession, _: CurrentUser):
    sh = db.get(Shipment, sid)
    if not sh:
        raise HTTPException(404, "Shipment not found")

    required_count, scanned_count, remaining_count, is_complete, _, _ = _scan_progress(db, sh)
    if required_count <= 0:
        msg = "No packages are attached to this shipment yet."
        return _scan_response(
            ok=False,
            sign="warning",
            code="",
            message=msg,
            package=None,
            package_model_code=None,
            required_count=required_count,
            scanned_count=scanned_count,
            remaining_count=remaining_count,
            is_complete=is_complete,
        )

    if is_complete:
        msg = "All shipment packages are scanned and verified."
        sign = "success"
    else:
        msg = f"Scan pending: {scanned_count}/{required_count} verified."
        sign = "warning"
    return _scan_response(
        ok=is_complete,
        sign=sign,
        code="",
        message=msg,
        package=None,
        package_model_code=None,
        required_count=required_count,
        scanned_count=scanned_count,
        remaining_count=remaining_count,
        is_complete=is_complete,
    )


@router.post("/{sid}/scan-package", response_model=ShipmentScanOut)
def scan_package(
    sid: int,
    payload: ShipmentScanIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.shipment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = {"shipment_id": sid, **payload.model_dump(mode="json")}
    replay = replay_idempotent_response(db, scope="shipments.scan-package", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay

    sh = locked_shipment(db, sid)
    if not sh:
        raise HTTPException(404, "Shipment not found")
    if sh.status not in _OPEN_SHIPMENT_STATUSES:
        raise HTTPException(409, f"Shipment {sh.shipment_no} cannot be scanned from {sh.status}")

    raw_code = (payload.code or "").strip()
    if not raw_code:
        raise HTTPException(400, "Scan code is required")

    pkg, matched_code = _find_package_for_scan(db, raw_code, shipment_id=sh.id)
    if not pkg:
        db.add(
            ShipmentScanLog(
                shipment_id=sh.id,
                package_id=None,
                scanned_code=raw_code,
                scan_result="not_found",
                message="Scanned package was not found.",
                scanned_by=current.id,
            )
        )
        required_count, scanned_count, remaining_count, is_complete, _, _ = _scan_progress(db, sh)
        response = _scan_response(
            ok=False,
            sign="error",
            code=raw_code,
            message="Package not found. Please scan the correct package label.",
            package=None,
            package_model_code=None,
            required_count=required_count,
            scanned_count=scanned_count,
            remaining_count=remaining_count,
            is_complete=is_complete,
        )
        return _commit_scan_response(
            db,
            current=current,
            idempotency_key=idempotency_key,
            fingerprint_payload=fingerprint_payload,
            response=response,
        )

    lock_ids = {pkg.id, *(row.package_id for row in sh.packages)}
    locked_packages = db.query(Package).filter(Package.id.in_(lock_ids)).order_by(Package.id).with_for_update().populate_existing().all()
    pkg = next(row for row in locked_packages if row.id == pkg.id)

    model = db.get(Model, pkg.model_id) if pkg.model_id else None
    if pkg.status not in _READY_FOR_SHIPMENT_STATUSES:
        msg = f"Package {pkg.package_no} is in status '{pkg.status}' and is not ready for shipment."
        db.add(
            ShipmentScanLog(
                shipment_id=sh.id,
                package_id=pkg.id,
                scanned_code=matched_code,
                scan_result="not_ready",
                message=msg,
                scanned_by=current.id,
            )
        )
        required_count, scanned_count, remaining_count, is_complete, _, _ = _scan_progress(db, sh)
        response = _scan_response(
            ok=False,
            sign="error",
            code=matched_code,
            message=msg,
            package=pkg,
            package_model_code=model.code if model else None,
            required_count=required_count,
            scanned_count=scanned_count,
            remaining_count=remaining_count,
            is_complete=is_complete,
        )
        return _commit_scan_response(
            db,
            current=current,
            idempotency_key=idempotency_key,
            fingerprint_payload=fingerprint_payload,
            response=response,
        )

    attachment_error = _package_attachment_error(db, sh, pkg)
    if attachment_error:
        db.add(
            ShipmentScanLog(
                shipment_id=sh.id,
                package_id=pkg.id,
                scanned_code=matched_code,
                scan_result="mismatch",
                message=attachment_error,
                scanned_by=current.id,
            )
        )
        required_count, scanned_count, remaining_count, is_complete, _, _ = _scan_progress(db, sh)
        response = _scan_response(
            ok=False,
            sign="error",
            code=matched_code,
            message=attachment_error,
            package=pkg,
            package_model_code=model.code if model else None,
            required_count=required_count,
            scanned_count=scanned_count,
            remaining_count=remaining_count,
            is_complete=is_complete,
        )
        return _commit_scan_response(
            db,
            current=current,
            idempotency_key=idempotency_key,
            fingerprint_payload=fingerprint_payload,
            response=response,
        )

    link = (
        db.query(ShipmentPackage)
        .filter(ShipmentPackage.shipment_id == sh.id, ShipmentPackage.package_id == pkg.id)
        .first()
    )

    if sh.sales_order_id and not link:
        pack_line = db.query(SalesOrderItem).filter_by(sales_order_id=sh.sales_order_id, model_id=pkg.model_id).filter(
            SalesOrderItem.requested_pack_count.isnot(None)).first()
        if pack_line:
            scanned_model_count = db.query(Package.id).filter(Package.id.in_(
                _matched_package_ids_for_shipment(db, sh.id)), Package.model_id == pkg.model_id).count()
            if scanned_model_count >= pack_line.requested_pack_count:
                raise HTTPException(409, "All requested packages for this model are already scanned")
        allowed_ids = {int(p.id) for p, _ in _ready_packages_for_sales_order(db, int(sh.sales_order_id))}
        if int(pkg.id) not in allowed_ids:
            replacement_link, replacement_error = _replace_unscanned_same_model_package(
                db,
                shipment=sh,
                scanned_package=pkg,
                current=current,
            )
            if replacement_error:
                msg = replacement_error
            elif replacement_link:
                link = replacement_link
                msg = ""
            elif pack_line and db.query(ShipmentPackage).join(Package, Package.id == ShipmentPackage.package_id).filter(
                ShipmentPackage.shipment_id == sh.id, Package.model_id == pkg.model_id).count() < pack_line.requested_pack_count:
                msg = _move_package_reservations(db, sales_order_id=sh.sales_order_id, from_package_id=-1,
                                                 to_package=pkg, reserved_by=current.id) or ""
            else:
                msg = f"Mismatch: package {pkg.package_no} does not match any remaining model in sales order #{sh.sales_order_id}."
            if msg:
                db.add(
                    ShipmentScanLog(
                        shipment_id=sh.id,
                        package_id=pkg.id,
                        scanned_code=matched_code,
                        scan_result="mismatch",
                        message=msg,
                        scanned_by=current.id,
                    )
                )
                required_count, scanned_count, remaining_count, is_complete, _, _ = _scan_progress(db, sh)
                response = _scan_response(
                    ok=False,
                    sign="error",
                    code=matched_code,
                    message=msg,
                    package=pkg,
                    package_model_code=model.code if model else None,
                    required_count=required_count,
                    scanned_count=scanned_count,
                    remaining_count=remaining_count,
                    is_complete=is_complete,
                )
                return _commit_scan_response(
                    db,
                    current=current,
                    idempotency_key=idempotency_key,
                    fingerprint_payload=fingerprint_payload,
                    response=response,
                )
    if not link:
        db.add(ShipmentPackage(shipment_id=sh.id, package_id=pkg.id, quantity=pkg.total_quantity))
        db.flush()
        log_action(db, current, "add_package_scan", "Shipment", sh.id, new_value={"package_id": pkg.id})

    duplicate = pkg.id in _matched_package_ids_for_shipment(db, sh.id)
    if duplicate:
        msg = f"Package {pkg.package_no} was already scanned for this shipment."
        result = "duplicate"
        sign = "warning"
    else:
        msg = f"Package {pkg.package_no} verified for shipment {sh.shipment_no}."
        result = "matched"
        sign = "success"

    db.add(
        ShipmentScanLog(
            shipment_id=sh.id,
            package_id=pkg.id,
            scanned_code=matched_code,
            scan_result=result,
            message=msg,
            scanned_by=current.id,
        )
    )
    db.flush()
    required_count, scanned_count, remaining_count, is_complete, _, _ = _scan_progress(db, sh)
    response = _scan_response(
        ok=True,
        sign=sign,
        code=matched_code,
        message=msg,
        package=pkg,
        package_model_code=model.code if model else None,
        required_count=required_count,
        scanned_count=scanned_count,
        remaining_count=remaining_count,
        is_complete=is_complete,
    )
    return _commit_scan_response(
        db,
        current=current,
        idempotency_key=idempotency_key,
        fingerprint_payload=fingerprint_payload,
        response=response,
    )


@router.post("/{sid}/ship", response_model=ShipmentOut)
def ship_all(
    sid: int,
    db: DbSession,
    current: User = Depends(require_permissions("storage.shipment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = {"shipment_id": sid}
    replay = replay_idempotent_response(db, scope="shipments.ship", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    sh = locked_shipment(db, sid)
    if not sh: raise HTTPException(404, "Shipment not found")
    required_count, scanned_count = _ship_verified_packages(db, sh, current)
    log_action(
        db,
        current,
        "ship",
        "Shipment",
        sh.id,
        new_value={"required_scans": required_count, "verified_scans": scanned_count},
    )
    db.flush()
    response = _shipment_payload(db, sh)
    store_idempotent_response(
        db,
        scope="shipments.ship",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
    )
    db.commit(); db.refresh(sh)
    return response


@router.post("/{sid}/mark-shipped", response_model=ShipmentOut)
def mark_shipped(
    sid: int,
    db: DbSession,
    current: User = Depends(require_permissions("storage.shipment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = {"shipment_id": sid}
    replay = replay_idempotent_response(db, scope="shipments.mark-shipped", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    sh = locked_shipment(db, sid)
    if not sh:
        raise HTTPException(404, "Shipment not found")
    required_count, scanned_count = _ship_verified_packages(db, sh, current)
    log_action(
        db,
        current,
        "mark_shipped",
        "Shipment",
        sh.id,
        new_value={"required_scans": required_count, "verified_scans": scanned_count},
    )
    db.flush()
    response = _shipment_payload(db, sh)
    store_idempotent_response(
        db,
        scope="shipments.mark-shipped",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
    )
    db.commit()
    db.refresh(sh)
    return response


@router.post("/{sid}/deliver", response_model=ShipmentOut)
def deliver(
    sid: int,
    db: DbSession,
    current: User = Depends(require_permissions("storage.shipment", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = {"shipment_id": sid}
    replay = replay_idempotent_response(db, scope="shipments.deliver", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    sh = locked_shipment(db, sid)
    if not sh: raise HTTPException(404, "Shipment not found")
    if str(sh.status or "") != "shipped":
        raise HTTPException(409, "Shipment must be shipped before it can be marked delivered")
    if not sh.packages:
        raise HTTPException(400, "Shipment has no packages to deliver")
    sh.status = "delivered"
    sh.delivered_at = datetime.now(timezone.utc)
    for sp in sh.packages:
        pkg = db.get(Package, sp.package_id)
        if pkg and pkg.status == "shipped":
            mark_delivered(db, pkg, current.id)
    inv = invoice_for_frozen_delivery(db, sh, current)
    if inv:
        notify_department(
            db,
            department_code="FIN",
            title="Shipment delivered - invoice reconciled",
            message=f"Shipment {sh.shipment_no} delivered. Invoice {inv.invoice_no} is ready in Finance.",
            link="/finance",
            exclude_user_id=current.id,
        )
    log_action(db, current, "deliver", "Shipment", sh.id)
    db.flush()
    response = _shipment_payload(db, sh)
    store_idempotent_response(
        db,
        scope="shipments.deliver",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
    )
    db.commit(); db.refresh(sh)
    return response
