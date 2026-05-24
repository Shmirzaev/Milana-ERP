from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import func

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import Shipment, ShipmentPackage, ShipmentScanLog, Package, SalesOrder, StockReservation, User, Model, Customer
from app.schemas.sales import ShipmentIn, ShipmentOut, ShipmentScanIn, ShipmentScanOut
from app.services.audit import log_action
from app.services.numbering import next_shipment_no
from app.services.packages import ship_package, mark_delivered
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


def _order_has_ready_packages(db: DbSession, sales_order_id: int) -> bool:
    return len(_ready_packages_for_sales_order(db, sales_order_id)) > 0


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


def _find_package_for_scan(db: DbSession, raw_code: str) -> tuple[Package | None, str]:
    for candidate in _scan_code_candidates(raw_code):
        pkg = db.query(Package).filter((Package.barcode == candidate) | (Package.package_no == candidate)).first()
        if pkg:
            return pkg, candidate
    return None, (raw_code or "").strip()


def _scan_progress(db: DbSession, shipment: Shipment) -> tuple[int, int, int, bool, set[int], set[int]]:
    attached_ids = {int(sp.package_id) for sp in shipment.packages if sp.package_id is not None}
    if not attached_ids:
        return 0, 0, 0, False, set(), set()

    matched_rows = (
        db.query(ShipmentScanLog.package_id)
        .filter(
            ShipmentScanLog.shipment_id == shipment.id,
            ShipmentScanLog.scan_result == "matched",
            ShipmentScanLog.package_id.isnot(None),
        )
        .group_by(ShipmentScanLog.package_id)
        .all()
    )
    matched_scanned_ids = {int(pid) for (pid,) in matched_rows if pid is not None}
    scanned_for_attached = attached_ids & matched_scanned_ids
    required_count = len(attached_ids)
    scanned_count = len(scanned_for_attached)
    remaining_count = max(0, required_count - scanned_count)
    return required_count, scanned_count, remaining_count, remaining_count == 0, attached_ids, scanned_for_attached


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
    package_rows = (
        db.query(Package.sales_order_id, func.coalesce(func.sum(Package.total_quantity), 0))
        .filter(Package.sales_order_id.isnot(None), Package.status.in_(_READY_FOR_SHIPMENT_STATUSES))
        .group_by(Package.sales_order_id)
        .all()
    )
    package_qty_by_so = {int(sid): int(qty or 0) for sid, qty in package_rows if sid is not None}
    so_ids = set(package_qty_by_so.keys())
    qry = db.query(SalesOrder, Customer).outerjoin(Customer, Customer.id == SalesOrder.customer_id)
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
            .join(Model, Model.id == Package.model_id)
            .filter(Package.status.in_(_READY_FOR_SHIPMENT_STATUSES))
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
def create_shipment(payload: ShipmentIn, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
    so = db.get(SalesOrder, payload.sales_order_id) if payload.sales_order_id else None
    if payload.sales_order_id and not so:
        raise HTTPException(404, "Sales order not found")
    if so:
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
    log_action(db, current, "create", "Shipment", sh.id, new_value={"shipment_no": sh.shipment_no, "packages": added})
    db.commit(); db.refresh(sh)
    return _shipment_payload(db, sh)


@router.patch("/{sid}", response_model=ShipmentOut)
def update_shipment(sid: int, payload: dict, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
    sh = db.get(Shipment, sid)
    if not sh: raise HTTPException(404, "Shipment not found")
    for k, v in payload.items():
        if hasattr(sh, k): setattr(sh, k, v)
    log_action(db, current, "update", "Shipment", sh.id)
    db.commit(); db.refresh(sh)
    return _shipment_payload(db, sh)


@router.post("/{sid}/add-package")
def add_package(sid: int, package_id: int, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
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
    db.add(ShipmentPackage(shipment_id=sh.id, package_id=pkg.id, quantity=pkg.total_quantity))
    log_action(db, current, "add_package", "Shipment", sh.id, new_value={"package_id": pkg.id})
    db.commit()
    return {"message": "added"}


@router.post("/{sid}/add-ready-packages")
def add_ready_packages(sid: int, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
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
    db.commit()
    return {"added": reported}


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
):
    sh = db.get(Shipment, sid)
    if not sh:
        raise HTTPException(404, "Shipment not found")
    if str(sh.status or "") in ("shipped", "delivered"):
        raise HTTPException(409, f"Shipment {sh.shipment_no} is already {sh.status}")

    raw_code = (payload.code or "").strip()
    if not raw_code:
        raise HTTPException(400, "Scan code is required")

    pkg, matched_code = _find_package_for_scan(db, raw_code)
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
        db.commit()
        required_count, scanned_count, remaining_count, is_complete, _, _ = _scan_progress(db, sh)
        return _scan_response(
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
        db.commit()
        required_count, scanned_count, remaining_count, is_complete, _, _ = _scan_progress(db, sh)
        return _scan_response(
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

    if sh.sales_order_id:
        allowed_ids = {int(p.id) for p, _ in _ready_packages_for_sales_order(db, int(sh.sales_order_id))}
        if int(pkg.id) not in allowed_ids:
            msg = f"Mismatch: package {pkg.package_no} does not belong to sales order #{sh.sales_order_id}."
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
            db.commit()
            required_count, scanned_count, remaining_count, is_complete, _, _ = _scan_progress(db, sh)
            return _scan_response(
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

    link = (
        db.query(ShipmentPackage)
        .filter(ShipmentPackage.shipment_id == sh.id, ShipmentPackage.package_id == pkg.id)
        .first()
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
    db.commit()

    required_count, scanned_count, remaining_count, is_complete, _, _ = _scan_progress(db, sh)
    return _scan_response(
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


@router.post("/{sid}/ship", response_model=ShipmentOut)
def ship_all(sid: int, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
    sh = db.get(Shipment, sid)
    if not sh: raise HTTPException(404, "Shipment not found")
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
            ship_package(db, pkg, current.id)
    log_action(
        db,
        current,
        "ship",
        "Shipment",
        sh.id,
        new_value={"required_scans": required_count, "verified_scans": scanned_count},
    )
    db.commit(); db.refresh(sh)
    return _shipment_payload(db, sh)


@router.post("/{sid}/mark-shipped", response_model=ShipmentOut)
def mark_shipped(sid: int, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
    sh = db.get(Shipment, sid)
    if not sh:
        raise HTTPException(404, "Shipment not found")
    if not sh.packages:
        raise HTTPException(400, "Shipment has no packages to ship")
    sh.status = "shipped"
    sh.shipped_at = datetime.now(timezone.utc)
    for sp in sh.packages:
        pkg = db.get(Package, sp.package_id)
        if pkg and pkg.status in _READY_FOR_SHIPMENT_STATUSES:
            ship_package(db, pkg, current.id)
    log_action(db, current, "mark_shipped", "Shipment", sh.id)
    db.commit()
    db.refresh(sh)
    return _shipment_payload(db, sh)


@router.post("/{sid}/deliver", response_model=ShipmentOut)
def deliver(sid: int, db: DbSession, current: User = Depends(require_permissions("storage.shipment", "*"))):
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
    db.commit(); db.refresh(sh)
    return _shipment_payload(db, sh)
