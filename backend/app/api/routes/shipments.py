from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Header
from sqlalchemy import func
from sqlalchemy.orm import selectinload

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
)
from app.schemas.sales import ShipmentIn, ShipmentOut, ShipmentScanIn, ShipmentScanOut
from app.services.audit import log_action
from app.services.idempotency import replay_idempotent_response, store_idempotent_response
from app.services.numbering import next_shipment_no
from app.services.model_images import model_preview_image_url, model_variant_picture_url
from app.services.packages import format_storage_location, ship_package, mark_delivered
from app.services.workflow import ensure_invoice_for_delivered_shipment, notify_department

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


def _shipment_payload(db: DbSession, sh: Shipment) -> dict:
    so = db.get(SalesOrder, sh.sales_order_id) if sh.sales_order_id else None
    customer = db.get(Customer, sh.customer_id or (so.customer_id if so else None)) if (sh.customer_id or (so.customer_id if so else None)) else None
    packages_count = len(sh.packages or [])
    total_qty = sum(int(sp.quantity or 0) for sp in (sh.packages or []))
    return {
        "id": sh.id,
        "sales_order_id": sh.sales_order_id,
        "customer_id": sh.customer_id,
        "shipment_no": sh.shipment_no,
        "status": sh.status,
        "shipped_at": sh.shipped_at,
        "delivered_at": sh.delivered_at,
        "notes": sh.notes,
        "created_at": sh.created_at,
        "sales_order_no": so.order_no if so else None,
        "customer_name": customer.name if customer else None,
        "shipment_type": "sales_order" if sh.sales_order_id else "warehouse_exit",
        "packages_count": packages_count,
        "total_qty": total_qty,
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


def _shipment_preparation_payload(db: DbSession, sh: Shipment) -> dict:
    package_rows = (
        db.query(ShipmentPackage, Package)
        .join(Package, Package.id == ShipmentPackage.package_id)
        .filter(ShipmentPackage.shipment_id == sh.id)
        .order_by(Package.id.asc())
        .all()
    )
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
        .filter(SalesOrderItem.sales_order_id == sh.sales_order_id)
        .order_by(SalesOrderItem.id.asc())
        .all()
        if sh.sales_order_id
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
    scanned_ids = _matched_package_ids_for_shipment(db, int(sh.id))

    prepared_by_variant: dict[tuple[int, str, str], int] = {}
    for shipment_package, package in package_rows:
        items = package_items_by_id.get(int(package.id), [])
        if items:
            for item in items:
                key = (int(item.model_id), str(item.color or "").strip(), str(item.size or "").strip())
                prepared_by_variant[key] = prepared_by_variant.get(key, 0) + int(item.quantity or 0)
        else:
            key = (int(package.model_id), str(package.color or "").strip(), "")
            prepared_by_variant[key] = prepared_by_variant.get(key, 0) + int(shipment_package.quantity or 0)

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
    for shipment_package, package in package_rows:
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
                "quantity": int(shipment_package.quantity or 0),
                "status": package.status,
                "location": format_storage_location(package.storage_cell, package.storage_shelf),
                "scanned": int(package.id) in scanned_ids,
                "items": item_lines,
            }
        )
        group = grouped.get(int(package.model_id))
        if group:
            group["packages_count"] += 1
            if int(package.id) in scanned_ids:
                group["scanned_packages_count"] += 1

    required_count, scanned_count, remaining_count, is_complete, _, _ = _scan_progress(db, sh)
    return {
        "shipment": _shipment_payload(db, sh),
        "items": list(grouped.values()),
        "packages": packages,
        "required_count": required_count,
        "scanned_count": scanned_count,
        "remaining_count": remaining_count,
        "is_complete": is_complete,
    }


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


def _matched_package_ids_for_shipment(db: DbSession, shipment_id: int) -> set[int]:
    matched_rows = (
        db.query(ShipmentScanLog.package_id)
        .filter(
            ShipmentScanLog.shipment_id == shipment_id,
            ShipmentScanLog.scan_result == "matched",
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
    required_qty = sum(int(row.quantity or 0) for row in old_reservations)
    if required_qty <= 0:
        return None

    new_stock_rows = _finished_goods_rows_for_package(db, int(to_package.id), available_only=True)
    available_qty = sum(int(row.available_qty or 0) for row in new_stock_rows)
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

    packages: list[Package] = []
    for shipment_package in shipment.packages:
        package = db.get(Package, shipment_package.package_id)
        if not package:
            raise HTTPException(409, f"Shipment package #{shipment_package.package_id} no longer exists")
        package = _lock_package(db, package)
        if package.status not in _READY_FOR_SHIPMENT_STATUSES:
            raise HTTPException(409, f"Package {package.package_no} is no longer ready to ship")
        packages.append(package)

    shipment.status = "shipped"
    shipment.shipped_at = datetime.now(timezone.utc)
    for package in packages:
        ship_package(db, package, current.id)
    return required_count, scanned_count


@router.get("", response_model=list[ShipmentOut])
def list_shipments(db: DbSession, _: CurrentUser, sales_order_id: int | None = None):
    qry = db.query(Shipment)
    if sales_order_id:
        qry = qry.filter(Shipment.sales_order_id == sales_order_id)
    rows = qry.order_by(Shipment.id.desc()).all()
    return [_shipment_payload(db, sh) for sh in rows]


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
    replay = replay_idempotent_response(db, scope="shipments.create", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    so = db.get(SalesOrder, payload.sales_order_id) if payload.sales_order_id else None
    if payload.sales_order_id and not so:
        raise HTTPException(404, "Sales order not found")
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
    sh = db.get(Shipment, sid)
    if not sh: raise HTTPException(404, "Shipment not found")
    for k, v in payload.items():
        if hasattr(sh, k): setattr(sh, k, v)
    log_action(db, current, "update", "Shipment", sh.id)
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
    sh = db.get(Shipment, sid)
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
    sh = db.get(Shipment, sid)
    if not sh: raise HTTPException(404, "Shipment not found")
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


@router.get("/{sid}/preparation")
def shipment_preparation(sid: int, db: DbSession, _: CurrentUser):
    sh = db.get(Shipment, sid)
    if not sh:
        raise HTTPException(404, "Shipment not found")
    return _shipment_preparation_payload(db, sh)


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

    sh = db.get(Shipment, sid)
    if not sh:
        raise HTTPException(404, "Shipment not found")
    if str(sh.status or "") in ("shipped", "delivered"):
        raise HTTPException(409, f"Shipment {sh.shipment_no} is already {sh.status}")

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

    pkg = _lock_package(db, pkg)

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

    duplicate = (
        db.query(ShipmentScanLog.id)
        .filter(
            ShipmentScanLog.shipment_id == sh.id,
            ShipmentScanLog.package_id == pkg.id,
            ShipmentScanLog.scan_result == "matched",
        )
        .first()
        is not None
    )
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
    sh = db.get(Shipment, sid)
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
    sh = db.get(Shipment, sid)
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
    sh = db.get(Shipment, sid)
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
    inv = ensure_invoice_for_delivered_shipment(db, sales_order_id=sh.sales_order_id)
    if inv:
        notify_department(
            db,
            department_code="FIN",
            title="Shipment delivered - draft invoice created",
            message=f"Shipment {sh.shipment_no} delivered. Invoice {inv.invoice_no} prepared.",
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
