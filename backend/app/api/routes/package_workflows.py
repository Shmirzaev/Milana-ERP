"""Package workflow routes mounted before /packages/{pid}."""
from fastapi import Query, APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from app.services.print_response import warehouse_print_response

from app.core.deps import DbSession, require_permissions, user_permissions
from app.models import Package, PackagePrintRun, PackagePrintRunMember, ProductionOrder, User
from app.schemas.package_workflows import ManualPackageReceiptIn, PrintRunIn, PrintRunCreatePackagesIn, PrintRunReceiveIn
from app.services import package_workflows as service
from app.services.audit import log_action
from app.services.package_label_pages import label_document
from app.services.idempotency import replay_idempotent_response, store_idempotent_response
from app.services.packaging_scope import packaging_department_for_order, packaging_department_scope, require_package_access
from app.services.packages import create_package, _packaging_record_totals_by_batch

router = APIRouter()


@router.get("/first-grade/balance/{production_order_id}")
def first_grade_balance(production_order_id: int, db: DbSession, production_batch_id: int | None = None,
                        current: User = Depends(require_permissions("packaging.packages", "*"))):
    from app.services.first_grade import size_balance
    order = db.get(ProductionOrder, production_order_id)
    if not order:
        raise HTTPException(404, "Production order not found")
    owner = packaging_department_for_order(db, order.id, production_batch_id)
    packaging_department_scope(current, owner)
    if order.source_type != "standard" or order.sales_order_id:
        raise HTTPException(409, "FIRST_GRADE_CUSTOMER_OWNED")
    return {"sizes": size_balance(db, order.id, production_batch_id)}


@router.get("/warehouse-model/{model_id}")
def warehouse_model_packages(model_id: int, db: DbSession, stock_kind: str = "standard",
                              page: int = Query(1, ge=1),
                              current: User = Depends(require_permissions("storage.packages", "storage.shipment", "sales.orders", "*"))):
    from sqlalchemy.orm import selectinload
    from app.models import Model, FinishedGoodsStock
    from app.services.model_images import warehouse_stock_image_url
    if stock_kind not in {"standard", "first_grade"}:
        raise HTTPException(422, "Invalid stock classification")
    model = db.get(Model, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    query = db.query(Package).filter(Package.model_id == model_id, Package.stock_kind == stock_kind,
                                     Package.status.in_(["packed", "received_in_storage", "reserved"]))
    total = query.count()
    packages = query.options(selectinload(Package.items)).order_by(Package.id.desc()).offset((page - 1) * 50).limit(50).all()
    stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_([p.id for p in packages])).all()
    by_package = {}
    for row in stocks:
        quantities = by_package.setdefault(row.package_id, {"available": 0, "reserved": 0})
        quantities["available"] += row.available_qty
        quantities["reserved"] += row.reserved_qty
    orders = {p.id: p.production_no for p in db.query(ProductionOrder).filter(
        ProductionOrder.id.in_({p.production_order_id for p in packages if p.production_order_id})).all()}
    return {"model_code": model.code, "model_name": model.name, "image_url": warehouse_stock_image_url(model),
            "total": total, "page": page, "page_size": 50,
            "packages": [{"id": p.id, "package_no": p.package_no, "barcode": p.barcode,
                          "production_no": orders.get(p.production_order_id), "quantity": p.total_quantity,
                          "weight_kg": p.weight_kg, "status": p.status, "received_at": p.received_at,
                          "cell": p.storage_cell, "shelf": p.storage_shelf,
                          **by_package.get(p.id, {"available": 0, "reserved": 0}),
                          "items": [{"size": i.size, "color": i.color, "quantity": i.quantity} for i in p.items]}
                         for p in packages]}


def _write(db, current, operation, payload, action):
    key = str(payload.request_key)
    scope = f"packages.{operation}.{current.id}"
    service.lock_request(db, current.id, operation, key)
    body = payload.model_dump(mode="json")
    if operation == "manual-receipt" and body.get("pack_quantities") is None:
        body.pop("pack_quantities", None)
    replay = replay_idempotent_response(db, scope=scope, key=key, payload=body)
    if replay:
        if operation == "manual-receipt":
            run = db.get(PackagePrintRun, replay["print_run"]["id"])
            if run:
                service.require_active_run(run)
                if run.deleted_package_ids:
                    raise HTTPException(410, "Some labels in this manual receipt were deleted")
        return replay
    result = action()
    store_idempotent_response(db, scope=scope, key=key, payload=body, response=result, user=current)
    db.commit()
    return result


def _run(db, current, rid):
    run = db.get(PackagePrintRun, rid)
    if not run:
        raise HTTPException(404, "Print run not found")
    permissions = set(user_permissions(current))
    if not permissions.intersection({"storage.packages", "storage.shipment", "*"}):
        packaging_department_scope(current, run.packaging_department_code)
    service.require_active_run(run)
    return run


@router.post("/manual-receipt", status_code=201)
def create_manual_receipt(payload: ManualPackageReceiptIn, db: DbSession,
                          current: User = Depends(require_permissions("storage.packages", "*"))):
    return _write(db, current, "manual-receipt", payload, lambda: service.manual_receipt(db, current, payload))


@router.post("/print-runs", status_code=201)
def create_print_run(payload: PrintRunIn, db: DbSession,
                     current: User = Depends(require_permissions("packaging.packages", "storage.packages", "*"))):
    def action():
        ids = payload.package_ids
        if any(pid <= 0 for pid in ids) or len(set(ids)) != len(ids):
            raise HTTPException(400, "Select distinct positive package IDs")
        packages = db.query(Package).filter(Package.id.in_(ids)).order_by(Package.id).with_for_update().populate_existing().all()
        if len(packages) != len(ids):
            raise HTTPException(404, "One or more selected packages were not found")
        for pkg in packages:
            require_package_access(current, pkg)
        return service.run_payload(db, service.create_run(db, current, packages))
    return _write(db, current, "print-run", payload, action)


@router.post("/print-runs/create-packages", status_code=201)
def create_packages_and_run(payload: PrintRunCreatePackagesIn, db: DbSession,
                            current: User = Depends(require_permissions("packaging.packages", "*"))):
    def action():
        order_ids = {p.production_order_id for p in payload.packages}
        if len(order_ids) != 1:
            raise HTTPException(400, "Select one production order per packaging action")
        order = db.query(ProductionOrder).filter(ProductionOrder.id.in_(order_ids)).with_for_update().first()
        if not order:
            raise HTTPException(404, "Production order not found")
        if order.source_type == "usluga":
            raise HTTPException(400, "Usluga does not enter warehouse receiving print runs")
        # The existing helper has a legacy no-record fallback. This new path never uses it.
        if not _packaging_record_totals_by_batch(db, order.id):
            raise HTTPException(409, "Save Packaging output before creating packages")
        packages = []
        for row in payload.packages:
            if row.model_id != order.model_id or any(item.model_id != order.model_id for item in row.items):
                raise HTTPException(400, "Package model must match the production order")
            owner = packaging_department_for_order(db, order.id, row.production_batch_id)
            packaging_department_scope(current, owner)
            data = row.model_dump()
            data["packaging_department_code"] = owner
            data["user_id"] = current.id
            data["is_admin"] = False
            data["override_capacity"] = False
            pkg = create_package(db, **data)
            log_action(db, current, "create", "Package", pkg.id, new_value={"package_no": pkg.package_no})
            packages.append(pkg)
        return service.run_payload(db, service.create_run(db, current, packages))
    return _write(db, current, "create-packages-run", payload, action)


@router.get("/print-runs")
def list_print_runs(db: DbSession, production_order_id: int | None = None,
                    current: User = Depends(require_permissions("packaging.packages", "packaging.records", "storage.packages", "storage.shipment", "*"))):
    query = db.query(PackagePrintRun).filter(PackagePrintRun.deleted_at.is_(None))
    if production_order_id:
        query = query.filter(PackagePrintRun.id.in_(db.query(PackagePrintRunMember.run_id).join(
            Package, Package.id == PackagePrintRunMember.package_id).filter(Package.production_order_id == production_order_id)))
    permissions = set(user_permissions(current))
    if not permissions.intersection({"storage.packages", "storage.shipment", "*"}):
        query = query.filter(PackagePrintRun.packaging_department_code == packaging_department_scope(current))
    return [service.run_payload(db, row) for row in query.order_by(PackagePrintRun.id.desc()).limit(100).all()]


@router.get("/print-runs/resolve")
def resolve_print_run(code: str, db: DbSession,
                      current: User = Depends(require_permissions("storage.packages", "*"))):
    if len(code) > 512:
        raise HTTPException(400, "Package code is too long")
    run = service.resolve_run(db, code)
    return {"print_run": service.run_payload(db, run) if run else None}


@router.post("/print-runs/receive")
def receive_print_run(payload: PrintRunReceiveIn, db: DbSession,
                      current: User = Depends(require_permissions("storage.packages", "*"))):
    from app.api.routes.packages import _package_detail_payload
    run, _ = service.receive_run(db, current, payload)
    result = service.run_payload(db, run)
    result["packages"] = [_package_detail_payload(db, db.get(Package, pid)) for pid in result["package_ids"]]
    db.commit()
    return result


@router.get("/print-runs/{rid}")
def get_print_run(rid: int, db: DbSession,
                  current: User = Depends(require_permissions("packaging.packages", "packaging.records", "storage.packages", "storage.shipment", "*"))):
    return service.run_payload(db, _run(db, current, rid))


@router.delete("/print-runs/{rid}/manual-packages")
def delete_manual_packages(rid: int, db: DbSession, package_ids: list[int] | None = Query(default=None),
                           current: User = Depends(require_permissions("storage.packages", "*"))):
    run = db.query(PackagePrintRun).filter_by(id=rid).with_for_update().first()
    if not run:
        raise HTTPException(404, "Print run not found")
    result = service.delete_manual_run(db, current, run, package_ids)
    db.commit()
    return result


@router.get("/print-runs/{rid}/label", response_class=HTMLResponse)
def print_run_label(rid: int, db: DbSession,
                     current: User = Depends(require_permissions("packaging.packages", "packaging.records", "storage.packages", "storage.shipment", "*"))):
    from app.api.routes.packages import _h, _package_label_card_html, _PACKAGE_LABEL_CSS
    run = _run(db, current, rid)
    members = service.active_run_members(db, run)
    cards = []
    current_quantity = 0
    for member in members:
        pkg = db.get(Package, member.package_id)
        if not pkg:
            raise HTTPException(409, "Print run contains a missing package; review required")
        if not run.received_at and service.contents(pkg) != member.snapshot:
            raise HTTPException(409, "Package changed since printing; review required before receipt")
        current_quantity += pkg.total_quantity
        cards.append(_package_label_card_html(db, pkg))
    summary = f"<div class='run-summary'><b>{_h(run.run_no)}</b><p>Packages / Упаковки / Qadoqlar: {len(members)}</p><p>Pieces / Изделия / Dona: {current_quantity}</p></div>"
    return warehouse_print_response(label_document(run.run_no, cards, _PACKAGE_LABEL_CSS, summary))
