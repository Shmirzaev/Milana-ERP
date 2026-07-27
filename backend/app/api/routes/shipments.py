from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Header
from sqlalchemy import func

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import (
    FinishedGoodsStock,
    Shipment,
    ShipmentPackage,
    ShipmentScanLog,
    Package,
    PackageScanLog,
    PackageBarcodeAlias,
    SalesOrder,
    StockReservation,
    User,
    Model,
    Customer,
)
from app.schemas.sales import ShipmentIn, ShipmentOut, ShipmentScanIn, ShipmentScanOut
from app.services.audit import log_action
from app.services.idempotency import replay_idempotent_response, store_idempotent_response
from app.services.numbering import next_shipment_no
from app.services.packages import ship_package, mark_delivered
from app.services.legacy_stock import package_legacy_identity
from app.services.workflow import ensure_invoice_for_delivered_shipment, notify_department

router = APIRouter(prefix="/shipments", tags=["shipments"])
_READY_FOR_SHIPMENT_STATUSES = ("received_in_storage", "reserved")
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
        "packages_count": packages_count,
        "total_qty": total_qty,
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
            .outerjoin(Model, Model.id == Package.model_id)
            .filter(Package.id.in_(pkg_ids_from_reservations), Package.status.in_(statuses))
            .order_by(Package.id.asc())
            .all()
        ):
            rows[int(pkg.id)] = (pkg, model)

    for pkg, model in (
        db.query(Package, Model)
        .outerjoin(Model, Model.id == Package.model_id)
        .filter(Package.sales_order_id == sales_order_id, Package.status.in_(statuses))
        .order_by(Package.id.asc())
        .all()
    ):
        rows.setdefault(int(pkg.id), (pkg, model))

    return [rows[k] for k in sorted(rows.keys())]


def _reserved_quantities_by_package(
    db: DbSession,
    sales_order_id: int,
) -> dict[int, int]:
    rows = (
        db.query(
            StockReservation.package_id,
            func.coalesce(func.sum(StockReservation.quantity), 0),
        )
        .filter(
            StockReservation.sales_order_id == sales_order_id,
            StockReservation.package_id.isnot(None),
        )
        .group_by(StockReservation.package_id)
        .all()
    )
    return {
        int(package_id): int(quantity or 0)
        for package_id, quantity in rows
        if package_id is not None and int(quantity or 0) > 0
    }


def _shipment_quantity_for_package(
    db: DbSession,
    *,
    shipment: Shipment,
    package: Package,
) -> int:
    if shipment.sales_order_id:
        reserved = _reserved_quantities_by_package(
            db,
            int(shipment.sales_order_id),
        ).get(int(package.id), 0)
        if reserved > 0:
            return reserved
    return int(package.total_quantity or 0)


def _ship_reserved_package_quantity(
    db: DbSession,
    *,
    shipment: Shipment,
    shipment_package: ShipmentPackage,
    package: Package,
    user_id: int | None,
) -> None:
    """Ship only this order's reserved quantity from an aggregate stock lot."""
    if not shipment.sales_order_id:
        ship_package(db, package, user_id)
        return

    requested = int(shipment_package.quantity or 0)
    if requested <= 0:
        raise HTTPException(409, f"Package {package.package_no} has no shipment quantity")

    reservations = (
        db.query(StockReservation)
        .filter(
            StockReservation.sales_order_id == shipment.sales_order_id,
            StockReservation.package_id == package.id,
        )
        .order_by(StockReservation.id.asc())
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        reservations = reservations.with_for_update(of=StockReservation)
    reservation_rows = reservations.all()

    remaining = requested
    for reservation in reservation_rows:
        if remaining <= 0:
            break
        stock_qry = db.query(FinishedGoodsStock).filter(
            FinishedGoodsStock.id == reservation.finished_goods_stock_id
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            stock_qry = stock_qry.with_for_update(of=FinishedGoodsStock)
        stock = stock_qry.first()
        if not stock:
            raise HTTPException(409, "Reserved finished-goods stock is missing")

        take = min(
            remaining,
            int(reservation.quantity or 0),
            int(stock.reserved_qty or 0),
        )
        if take <= 0:
            continue
        stock.reserved_qty = int(stock.reserved_qty or 0) - take
        stock.sold_qty = int(stock.sold_qty or 0) + take
        if int(stock.available_qty or 0) > 0:
            stock.status = "available"
        elif int(stock.reserved_qty or 0) > 0:
            stock.status = "reserved"
        else:
            stock.status = "sold"
        remaining -= take

    if remaining > 0:
        raise HTTPException(
            409,
            f"Package {package.package_no} is short by {remaining} reserved piece(s)",
        )

    package_stock = (
        db.query(FinishedGoodsStock)
        .filter(FinishedGoodsStock.package_id == package.id)
        .all()
    )
    available = sum(int(row.available_qty or 0) for row in package_stock)
    reserved = sum(int(row.reserved_qty or 0) for row in package_stock)
    if available <= 0 and reserved <= 0:
        package.status = "shipped"
        package.shipped_at = datetime.now(timezone.utc)
        package.storage_cell = None
        package.storage_shelf = None
        package.storage_placed_at = None
    elif available > 0:
        package.status = "received_in_storage"
    else:
        package.status = "reserved"

    db.add(
        PackageScanLog(
            package_id=package.id,
            scanned_by=user_id,
            scan_type="shipped",
            location=f"shipment:{shipment.id};quantity:{requested}",
        )
    )


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
    if scanned_package.model_id is None:
        return None, None
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
        rows = (
            db.query(Package, Model)
            .outerjoin(Model, Model.id == Package.model_id)
            .filter(Package.status.in_(_READY_FOR_SHIPMENT_STATUSES))
            .order_by(Package.id.asc())
            .all()
        )
    result = []
    for p, model in rows:
        identity = package_legacy_identity(db, p) if not model else {}
        result.append({
            "id": p.id,
            "package_no": p.package_no,
            "sales_order_id": p.sales_order_id,
            "model_id": p.model_id,
            "model_code": model.code if model else identity.get("model_code"),
            "color": p.color,
            "total_quantity": p.total_quantity,
            "status": p.status,
            "storage_cell": p.storage_cell,
            "storage_shelf": p.storage_shelf,
        })
    return result


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
        reserved_by_package = _reserved_quantities_by_package(db, int(so.id))
        for pkg, _ in _ready_packages_for_sales_order(db, int(so.id)):
            exists = db.query(ShipmentPackage.id).filter(
                ShipmentPackage.shipment_id == sh.id,
                ShipmentPackage.package_id == pkg.id,
            ).first()
            if exists:
                continue
            quantity = reserved_by_package.get(int(pkg.id), int(pkg.total_quantity or 0))
            if quantity <= 0:
                continue
            db.add(ShipmentPackage(shipment_id=sh.id, package_id=pkg.id, quantity=quantity))
            added += 1
    log_action(db, current, "create", "Shipment", sh.id, new_value={"shipment_no": sh.shipment_no, "packages": added})
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
    if pkg.status not in _READY_FOR_SHIPMENT_STATUSES:
        raise HTTPException(409, f"Package {pkg.package_no} is not ready to ship")
    exists = db.query(ShipmentPackage).filter(
        ShipmentPackage.shipment_id == sh.id, ShipmentPackage.package_id == pkg.id,
    ).first()
    if exists:
        raise HTTPException(409, "Package already attached to this shipment")
    quantity = _shipment_quantity_for_package(db, shipment=sh, package=pkg)
    if quantity <= 0:
        raise HTTPException(409, "Package has no quantity reserved for this shipment")
    db.add(ShipmentPackage(shipment_id=sh.id, package_id=pkg.id, quantity=quantity))
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
    reserved_by_package = _reserved_quantities_by_package(db, int(sh.sales_order_id))
    added = 0
    for p in ready:
        if p.id in attached:
            continue
        quantity = reserved_by_package.get(int(p.id), int(p.total_quantity or 0))
        if quantity <= 0:
            continue
        db.add(ShipmentPackage(shipment_id=sh.id, package_id=p.id, quantity=quantity))
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

    model = db.get(Model, pkg.model_id) if pkg.model_id else None
    legacy_identity = package_legacy_identity(db, pkg) if not model else {}
    package_model_code = model.code if model else legacy_identity.get("model_code")
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
            package_model_code=package_model_code,
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
                    package_model_code=package_model_code,
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
        quantity = _shipment_quantity_for_package(db, shipment=sh, package=pkg)
        if quantity <= 0:
            raise HTTPException(409, "Package has no quantity reserved for this shipment")
        db.add(ShipmentPackage(shipment_id=sh.id, package_id=pkg.id, quantity=quantity))
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
    required_count, scanned_count, remaining_count, is_complete, _, _ = _scan_progress(db, sh)
    response = _scan_response(
        ok=True,
        sign=sign,
        code=matched_code,
        message=msg,
        package=pkg,
        package_model_code=package_model_code,
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
    if str(sh.status or "") in ("shipped", "delivered"):
        raise HTTPException(409, f"Shipment {sh.shipment_no} is already {sh.status}")
    required_count, scanned_count, remaining_count, _, attached_ids, scanned_attached = _scan_progress(db, sh)
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
    sh.status = "shipped"
    sh.shipped_at = datetime.now(timezone.utc)
    for sp in sh.packages:
        pkg = db.get(Package, sp.package_id)
        if pkg and pkg.status in _READY_FOR_SHIPMENT_STATUSES:
            _ship_reserved_package_quantity(
                db,
                shipment=sh,
                shipment_package=sp,
                package=pkg,
                user_id=current.id,
            )
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
    if str(sh.status or "") in ("shipped", "delivered"):
        raise HTTPException(409, f"Shipment {sh.shipment_no} is already {sh.status}")
    if not sh.packages:
        raise HTTPException(400, "Shipment has no packages to ship")
    sh.status = "shipped"
    sh.shipped_at = datetime.now(timezone.utc)
    for sp in sh.packages:
        pkg = db.get(Package, sp.package_id)
        if pkg and pkg.status in _READY_FOR_SHIPMENT_STATUSES:
            _ship_reserved_package_quantity(
                db,
                shipment=sh,
                shipment_package=sp,
                package=pkg,
                user_id=current.id,
            )
    log_action(db, current, "mark_shipped", "Shipment", sh.id)
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
