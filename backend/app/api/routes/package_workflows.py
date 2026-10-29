"""Package workflow routes mounted before /packages/{pid}."""
from fastapi import Query, APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import selectinload, load_only
from app.models.print_response_service import warehouse_print_response
from app.models.package_dispatch_service import remaining_quantity, remaining_item_quantity

from app.core.deps import CurrentUser, DbSession, require_permissions, user_permissions
from app.schemas import Package, PackagePrintRun, PackagePrintRunMember, ProductionOrder, User
from app.libs.dto.fulfillment.package_workflows import ManualPackageReceiptIn, PrintRunIn, PrintRunCreatePackagesIn, PrintRunReceiveIn, PackageReturnIn
from app.libs.dto.packaging.tracking import PackageChangeRequestIn
from app.libs.dto.packaging.manual_package_input import ManualPackageCreateIn
from app.libs.dto.packaging.manual_package_output import ManualPackageCreateOut, ManualPackageRecoveryOut
from pydantic import BaseModel, ConfigDict, Field
from app.models import package_workflows_service as service
from app.models.audit_service import log_action
from app.models.package_label_pages_service import label_document
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response
from app.models.packaging_scope_service import packaging_department_for_order, packaging_department_scope, require_package_access
from app.models.packages_service import (create_package, _packaging_record_totals_by_batch,
    PackageWriteContext, prime_package_batch_memberships, prime_packaged_quantity_availability)
from app.models.packaging_scope_service import packaging_departments_for_order
from app.models.numbering_service import next_package_nos
from app.models.workflow_service import sync_production_order_status

router = APIRouter()
_PRINT_RUN_LABEL_LIMIT = 200


class ReceiveOrderPackagesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_ids: list[int] = Field(min_length=1, max_length=500)


@router.get("/receiving-orders")
def receiving_orders(db: DbSession, q: str = "", page: int = Query(1, ge=1),
                     current: User = Depends(require_permissions("storage.packages", "*"))):
    from sqlalchemy import func, or_
    from app.schemas import SalesOrder, Model
    from app.models.model_identity_service import model_number_fields
    query = db.query(ProductionOrder.id, ProductionOrder.production_no, SalesOrder.order_no, ProductionOrder.model_id).join(
        Package, Package.production_order_id == ProductionOrder.id).outerjoin(
        SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id).filter(
        Package.status == "packed", ProductionOrder.source_type != "usluga")
    from app.models.factory_scope_service import factory_for_department, user_is_super_admin
    if factory_for_department(getattr(getattr(current, "department", None), "code", None)) or user_is_super_admin(current):
        query = query.filter(Package.packaging_department_code == packaging_department_scope(current, None))
    if q.strip():
        query = query.filter(or_(ProductionOrder.production_no.icontains(q.strip()[:100], autoescape=True),
                                 SalesOrder.order_no.icontains(q.strip()[:100], autoescape=True)))
    orders = query.distinct().order_by(ProductionOrder.id.desc()).offset((page - 1) * 20).limit(21).all()
    ranked = db.query(Package.id, Package.production_order_id,
                      func.row_number().over(partition_by=Package.production_order_id, order_by=Package.id).label("position"),
                      func.count().over(partition_by=Package.production_order_id).label("count"),
                      func.sum(Package.total_quantity).over(partition_by=Package.production_order_id).label("quantity")).filter(
        Package.production_order_id.in_([order.id for order in orders[:20]]), Package.status == "packed")
    if factory_for_department(getattr(getattr(current, "department", None), "code", None)) or user_is_super_admin(current):
        ranked = ranked.filter(Package.packaging_department_code == packaging_department_scope(current, None))
    ranked = ranked.subquery()
    package_rows = db.query(ranked).filter(ranked.c.position <= 501).order_by(ranked.c.id).all()
    rows = []
    models = {model.id: model for model in db.query(Model).filter(Model.id.in_([order.model_id for order in orders[:20]])).all()}
    for oid, number, sales_number, model_id in orders[:20]:
        packs = [p for p in package_rows if p.production_order_id == oid]
        model = models.get(model_id)
        rows.append({"id": oid, "production_no": number, "sales_order_no": sales_number,
                     **model_number_fields(model), "model_name": model.name if model else None,
                     "package_ids": [p.id for p in packs], "count": packs[0].count if packs else 0,
                     "quantity": packs[0].quantity if packs else 0})
    return {"rows": rows, "has_more": len(orders) > 20}


@router.post("/receive-order/{order_id}")
def receive_order(order_id: int, payload: ReceiveOrderPackagesIn, db: DbSession,
                  current: User = Depends(require_permissions("storage.packages", "*"))):
    from app.models.warehouse_packages_service import receive_order_packages
    result = receive_order_packages(db, current, order_id, payload.package_ids)
    db.commit()
    return result


@router.delete("/warehouse/{pid}")
def delete_inventory_package(pid: int, db: DbSession,
                             current: User = Depends(require_permissions("storage.packages", "*"))):
    from app.models.warehouse_packages_service import delete_warehouse_package
    result = delete_warehouse_package(db, current, pid)
    db.commit()
    return result


@router.get("/first-grade/balance/{production_order_id}")
def first_grade_balance(production_order_id: int, db: DbSession, production_batch_id: int | None = None,
                        current: User = Depends(require_permissions("packaging.packages", "*"))):
    from app.models.first_grade_service import size_balance
    order = db.get(ProductionOrder, production_order_id)
    if not order:
        raise HTTPException(404, "Production order not found")
    owner = packaging_department_for_order(db, order.id, production_batch_id)
    packaging_department_scope(current, owner)
    if order.source_type != "standard" or order.sales_order_id:
        raise HTTPException(409, "FIRST_GRADE_CUSTOMER_OWNED")
    return {"sizes": size_balance(db, order.id, production_batch_id)}


class PackagingSizeRowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size: str = Field(min_length=1, max_length=32)
    quantity: int = Field(ge=0, le=2_147_483_647, strict=True)


class PackagingSizeEntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=64, max_length=64)
    sizes: list[PackagingSizeRowIn] = Field(min_length=1, max_length=1000)


def _size_entry_order(db, current, production_order_id, batch_id, *, lock=False):
    from app.schemas import WorkOrder
    if lock:
        # Same upstream-before-downstream order as Packaging output; serialize
        # Sewing changes and package creation while validating the size budget.
        db.query(WorkOrder).filter_by(production_order_id=production_order_id, operation="sewing").order_by(
            WorkOrder.id).with_for_update().all()
    query = db.query(ProductionOrder).filter_by(id=production_order_id)
    order = (query.with_for_update().populate_existing() if lock else query).first()
    if not order:
        raise HTTPException(404, "Production order not found")
    packaging_department_scope(current, packaging_department_for_order(db, order.id, batch_id))
    if order.source_type != "standard" or order.sales_order_id:
        raise HTTPException(409, "FIRST_GRADE_CUSTOMER_OWNED")
    return order


@router.get("/first-grade/size-entry/{production_order_id}")
def get_packaging_size_entry(production_order_id: int, db: DbSession, production_batch_id: int | None = None,
                             current: User = Depends(require_permissions("packaging.packages", "*"))):
    from app.models.first_grade_service import packaging_size_entry
    order = _size_entry_order(db, current, production_order_id, production_batch_id)
    return packaging_size_entry(db, order.id, production_batch_id)


@router.put("/first-grade/size-entry/{production_order_id}")
def put_packaging_size_entry(production_order_id: int, payload: PackagingSizeEntryIn, db: DbSession,
                             production_batch_id: int | None = None,
                             current: User = Depends(require_permissions("packaging.packages", "*"))):
    from app.models.first_grade_service import save_packaging_size_entry
    order = _size_entry_order(db, current, production_order_id, production_batch_id, lock=True)
    result = save_packaging_size_entry(db, order, production_batch_id, payload, current)
    db.commit()
    return result


@router.get("/warehouse-model/{model_id}")
def warehouse_model_packages(model_id: int, db: DbSession, stock_kind: str = "standard",
                              page: int = Query(1, ge=1),
                              current: User = Depends(require_permissions("storage.packages", "storage.shipment", "sales.orders", "*"))):
    from sqlalchemy.orm import selectinload
    from app.schemas import Model, FinishedGoodsStock
    from app.models.model_images_service import warehouse_stock_image_url
    if stock_kind not in {"standard", "first_grade", "second_grade"}:
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
                          "production_no": orders.get(p.production_order_id), "quantity": remaining_quantity(p),
                          "weight_kg": p.weight_kg, "status": p.status, "received_at": p.received_at,
                          "cell": p.storage_cell, "shelf": p.storage_shelf,
                          **by_package.get(p.id, {"available": 0, "reserved": 0}),
                          "items": [{"size": i.size, "color": i.color, "quantity": remaining_item_quantity(p, i)} for i in p.items]}
                         for p in packages]}


_OPERATION_PERMISSIONS = {
    "manual-receipt": {"storage.packages", "*"},
    "resend-corrected": {"packaging.packages", "*"},
    "print-run": {"packaging.packages", "storage.packages", "*"},
    "create-packages-run": {"packaging.packages", "*"},
}


def _request_body(operation, payload):
    body = payload.model_dump(mode="json")
    if operation == "manual-receipt" and body.get("pack_quantities") is None:
        body.pop("pack_quantities", None)
    return body


def _validate_manual_receipt_replay(db, replay):
    if service.is_cancelled_request(replay):
        raise HTTPException(409, "This manual receipt request was cancelled; submit a corrected request with a new key")
    run = db.get(PackagePrintRun, replay["print_run"]["id"])
    if not run:
        raise HTTPException(410, "This manual receipt result is no longer available")
    service.require_active_run(run)
    if run.deleted_package_ids:
        raise HTTPException(410, "Some labels in this manual receipt were deleted")


def _validate_package_workflow_replay(db, current, operation, replay):
    if service.is_cancelled_request(replay):
        raise HTTPException(409, "This package request was cancelled; submit corrected values with a new key")
    if operation == "manual-receipt":
        _validate_manual_receipt_replay(db, replay)
        return
    try:
        run_id = int(replay["id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(410, "This package request result is no longer available")
    _run(db, current, run_id)


def _can_expose_package_workflow_result(current, operation):
    return bool(set(user_permissions(current)).intersection(_OPERATION_PERMISSIONS[operation]))


def _reconcile_package_workflow(db, current, operation, payload):
    key = str(payload.request_key)
    scope = f"packages.{operation}.{current.id}"
    body = _request_body(operation, payload)
    service.lock_request(db, current.id, operation, key)
    replay = replay_idempotent_response(db, scope=scope, key=key, payload=body)
    if replay is not None:
        if service.is_cancelled_request(replay):
            db.commit()
            return {"status": "cancelled"}
        if not _can_expose_package_workflow_result(current, operation):
            db.commit()
            return {"status": "completed_unavailable"}
        try:
            _validate_package_workflow_replay(db, current, operation, replay)
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409, 410}:
                raise
            db.commit()
            return {"status": "completed_unavailable"}
        db.commit()
        return {"status": "completed", "result": replay}
    store_idempotent_response(
        db,
        scope=scope,
        key=key,
        payload=body,
        response=service.cancelled_request_response(),
        user=current,
        status_code=409,
    )
    db.commit()
    return {"status": "cancelled"}



def _write(db, current, operation, payload, action):
    key = str(payload.request_key)
    scope = f"packages.{operation}.{current.id}"
    service.lock_request(db, current.id, operation, key)
    body = _request_body(operation, payload)
    replay = replay_idempotent_response(db, scope=scope, key=key, payload=body)
    if replay is not None:
        _validate_package_workflow_replay(db, current, operation, replay)
        return replay
    result = action()
    store_idempotent_response(db, scope=scope, key=key, payload=body, response=result, user=current)
    db.commit()
    return result



def _run(db, current, rid):
    run = db.query(PackagePrintRun).options(load_only(
        PackagePrintRun.id, PackagePrintRun.run_no, PackagePrintRun.code,
        PackagePrintRun.packaging_department_code, PackagePrintRun.package_ids,
        PackagePrintRun.created_at, PackagePrintRun.received_at,
        PackagePrintRun.deleted_package_ids, PackagePrintRun.deleted_at, PackagePrintRun.returned_at,
        PackagePrintRun.superseded_at,
    )).filter(PackagePrintRun.id == rid).first()
    if not run:
        raise HTTPException(404, "Print run not found")
    permissions = set(user_permissions(current))
    if not permissions.intersection({"storage.packages", "storage.shipment", "*"}):
        packaging_department_scope(current, run.packaging_department_code)
    service.require_active_run(run)
    return run


@router.get("/receiving-options")
def receiving_options(db: DbSession, q: str = "", page: int = Query(1, ge=1),
                      current: User = Depends(require_permissions("storage.packages", "*"))):
    from sqlalchemy import or_
    from app.schemas import Model, SalesOrder
    from app.api.routes.packages import _package_context
    candidates = db.query(Package.id).join(ProductionOrder, ProductionOrder.id == Package.production_order_id).join(
        Model, Model.id == Package.model_id).outerjoin(SalesOrder, SalesOrder.id == Package.sales_order_id).filter(
        Package.status == "packed", ProductionOrder.source_type != "usluga")
    if q.strip():
        term = q.strip()[:100]
        candidates = candidates.filter(or_(*[column.icontains(term, autoescape=True) for column in
                                             (Package.package_no, Package.barcode, Model.code, Model.name, ProductionOrder.production_no, SalesOrder.order_no)]))
    active = service.active_members(db)
    run_ids = active.filter(PackagePrintRunMember.package_id.in_(candidates)).with_entities(PackagePrintRunMember.run_id)
    runs = db.query(PackagePrintRun).filter(PackagePrintRun.id.in_(run_ids), PackagePrintRun.received_at.is_(None),
                                          PackagePrintRun.deleted_at.is_(None)).order_by(PackagePrintRun.id.desc()).offset((page - 1) * 20).limit(21).all()
    singles = db.query(Package).filter(Package.id.in_(candidates), ~Package.id.in_(active.with_entities(PackagePrintRunMember.package_id))).order_by(Package.id.desc()).offset((page - 1) * 20).limit(21).all()
    rows = []
    for run in runs[:20]:
        row = service.run_payload(db, run)
        pkg = db.get(Package, row["package_ids"][0])
        rows.append({**row, "key": f"run-{run.id}", "context": _package_context(db, pkg)})
    for pkg in singles[:20]:
        rows.append({"key": f"package-{pkg.id}", "id": None, "code": None, "run_no": pkg.package_no,
                     "package_ids": [pkg.id], "packages": [{"id": pkg.id, "package_no": pkg.package_no}],
                     "count": 1, "quantity": pkg.total_quantity, "context": _package_context(db, pkg)})
    return {"rows": rows, "has_more": len(runs) > 20 or len(singles) > 20}


@router.post("/return-to-packaging")
def return_to_packaging(payload: PackageReturnIn, db: DbSession,
                        current: User = Depends(require_permissions("storage.packages", "*"))):
    from app.models.package_returns_service import return_packages
    result = return_packages(db, current, payload)
    db.commit()
    return result


@router.post("/{pid}/correct-return")
def correct_return(pid: int, payload: PackageChangeRequestIn, db: DbSession,
                   current: User = Depends(require_permissions("packaging.packages", "*"))):
    from app.models.package_returns_service import correct_returned_package
    result = correct_returned_package(db, current, pid, payload)
    db.commit()
    return result


@router.post("/resend-corrected")
def resend_corrected(payload: PrintRunIn, db: DbSession,
                     current: User = Depends(require_permissions("packaging.packages", "*"))):
    from app.models.package_returns_service import resend_packages
    return _write(db, current, "resend-corrected", payload, lambda: resend_packages(db, current, payload))


@router.post("/manual-packaging", status_code=201, response_model=ManualPackageCreateOut)
def manual_packaging(payload: ManualPackageCreateIn,
                     db: DbSession, current: User = Depends(require_permissions("packaging.packages", "*"))):
    from app.models.packaging.manual_packages_service import create_manual_packages
    return create_manual_packages(db, current, payload)


@router.post("/manual-packaging/reconcile", response_model=ManualPackageRecoveryOut, response_model_exclude_unset=True)
def reconcile_manual_packaging(payload: ManualPackageCreateIn,
                               db: DbSession, current: CurrentUser):
    from app.models.packaging.manual_packages_service import reconcile_manual_packages
    return reconcile_manual_packages(db, current, payload)


@router.delete("/manual-packaging/{rid}")
def cancel_manual_packaging(rid: int, db: DbSession,
                            current: User = Depends(require_permissions("packaging.packages", "*"))):
    from app.models.packaging.manual_packages_service import cancel_manual_packages
    return cancel_manual_packages(db, current, rid)


@router.post("/manual-receipt", status_code=201)
def create_manual_receipt(payload: ManualPackageReceiptIn, db: DbSession,
                          current: User = Depends(require_permissions("storage.packages", "*"))):
    return _write(db, current, "manual-receipt", payload, lambda: service.manual_receipt(db, current, payload))


@router.post("/manual-receipt/reconcile")
def reconcile_manual_receipt(payload: ManualPackageReceiptIn, db: DbSession,
                             current: CurrentUser):
    return _reconcile_package_workflow(db, current, "manual-receipt", payload)


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


@router.post("/print-runs/reconcile")
def reconcile_print_run(payload: PrintRunIn, db: DbSession, current: CurrentUser):
    return _reconcile_package_workflow(db, current, "print-run", payload)


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
        packed_by_batch = _packaging_record_totals_by_batch(db, order.id)
        if not packed_by_batch:
            raise HTTPException(409, "Save Packaging output before creating packages")
        first_row = payload.packages[0]
        if first_row.model_id != order.model_id or any(
            item.model_id != order.model_id for item in first_row.items
        ):
            raise HTTPException(400, "Package model must match the production order")
        batch_ids = {
            int(batch_id)
            for row in payload.packages
            for batch_id in (
                [row.production_batch_id] if row.production_batch_id is not None else []
            ) + [allocation.production_batch_id for allocation in row.batch_allocations]
        }
        owners = packaging_departments_for_order(
            db,
            int(order.id),
            {row.production_batch_id for row in payload.packages},
        )
        write_context = PackageWriteContext.empty()
        write_context.locked_orders[int(order.id)] = order
        prime_package_batch_memberships(
            db,
            write_context,
            production_order_id=int(order.id),
            production_batch_ids=batch_ids,
        )
        prime_packaged_quantity_availability(
            db,
            write_context,
            production_order_id=int(order.id),
            packed_by_batch=packed_by_batch,
        )
        package_numbers = next_package_nos(db, len(payload.packages))
        packages = []
        for index, row in enumerate(payload.packages):
            if row.model_id != order.model_id or any(item.model_id != order.model_id for item in row.items):
                raise HTTPException(400, "Package model must match the production order")
            owner = owners[row.production_batch_id]
            packaging_department_scope(current, owner)
            data = row.model_dump()
            data["packaging_department_code"] = owner
            data["user_id"] = current.id
            data["is_admin"] = False
            data["override_capacity"] = False
            pkg = create_package(
                db,
                **data,
                _write_context=write_context,
                _package_no=package_numbers[index],
                _sync_production=False,
            )
            log_action(db, current, "create", "Package", pkg.id, new_value={"package_no": pkg.package_no})
            packages.append(pkg)
        sync_production_order_status(db, int(order.id))
        return service.run_payload(db, service.create_run(db, current, packages))
    return _write(db, current, "create-packages-run", payload, action)


@router.get("/print-runs")
def list_print_runs(db: DbSession, production_order_id: int | None = None,
                    page: int | None = Query(None, ge=1), page_size: int = Query(50, ge=1, le=100),
                    current: User = Depends(require_permissions("packaging.packages", "packaging.records", "storage.packages", "storage.shipment", "*"))):
    query = db.query(PackagePrintRun).filter(PackagePrintRun.deleted_at.is_(None), PackagePrintRun.returned_at.is_(None), PackagePrintRun.superseded_at.is_(None))
    if production_order_id:
        query = query.filter(PackagePrintRun.id.in_(db.query(PackagePrintRunMember.run_id).join(
            Package, Package.id == PackagePrintRunMember.package_id).filter(Package.production_order_id == production_order_id)))
    permissions = set(user_permissions(current))
    if not permissions.intersection({"storage.packages", "storage.shipment", "*"}):
        query = query.filter(PackagePrintRun.packaging_department_code == packaging_department_scope(current))
    if page is not None:
        total = query.count()
        runs = query.order_by(PackagePrintRun.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return {"rows": service.run_list_payload(db, runs), "total": total, "page": page,
                "page_size": page_size, "has_more": page * page_size < total}
    runs = query.order_by(PackagePrintRun.id.desc()).limit(100).all()
    return service.run_list_payload(db, runs)


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
    from app.api.routes.packages import _package_detail_payloads, _package_details_by_ids
    run, _, members = service.receive_run(db, current, payload)
    result = service.run_payload(db, run, members=members)
    result["packages"] = _package_detail_payloads(
        db,
        _package_details_by_ids(db, result["package_ids"]),
        print_run_ids={int(package_id): int(run.id) for package_id in result["package_ids"]},
    )
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
    from app.api.routes.packages import _h, _package_label_card_html, _PACKAGE_LABEL_CSS, _package_label_reference_context
    run = _run(db, current, rid)
    if len(run.package_ids) > _PRINT_RUN_LABEL_LIMIT:
        raise HTTPException(413, f"A print run label may contain at most {_PRINT_RUN_LABEL_LIMIT} packages")
    members = service.active_run_members(db, run)
    packages_by_id = {int(pkg.id): pkg for pkg in db.query(Package)
        .options(selectinload(Package.items), selectinload(Package.batch_allocations))
        .filter(Package.id.in_([member.package_id for member in members])).all()} if members else {}
    context = _package_label_reference_context(db, list(packages_by_id.values()))
    cards = []
    current_quantity = 0
    for member in members:
        pkg = packages_by_id.get(member.package_id)
        if not pkg:
            raise HTTPException(409, "Print run contains a missing package; review required")
        if not run.received_at and service.contents(pkg) != member.snapshot:
            raise HTTPException(409, "Package changed since printing; review required before receipt")
        current_quantity += pkg.total_quantity
        cards.append(_package_label_card_html(db, pkg, context=context, active_label_checked=True))
    summary = f"<div class='run-summary'><b>{_h(run.run_no)}</b><p>Packages / Упаковки / Qadoqlar: {len(members)}</p><p>Pieces / Изделия / Dona: {current_quantity}</p></div>"
    return warehouse_print_response(label_document(run.run_no, cards, _PACKAGE_LABEL_CSS, summary))


@router.post("/print-runs/create-packages/reconcile")
def reconcile_packages_and_run(payload: PrintRunCreatePackagesIn, db: DbSession, current: CurrentUser):
    return _reconcile_package_workflow(db, current, "create-packages-run", payload)


@router.post("/resend-corrected/reconcile")
def reconcile_resend_corrected(payload: PrintRunIn, db: DbSession, current: CurrentUser):
    return _reconcile_package_workflow(db, current, "resend-corrected", payload)
