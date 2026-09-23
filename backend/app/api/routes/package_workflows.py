"""Package workflow routes mounted before /packages/{pid}."""
from fastapi import Query, APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import load_only, selectinload
from app.services.print_response import warehouse_print_response

from app.core.deps import CurrentUser, DbSession, require_permissions, user_permissions
from app.models import Package, PackagePrintRun, PackagePrintRunMember, ProductionOrder, User
from app.schemas.package_workflows import (
    ManualPackageReceiptIn,
    PrintRunCreatePackagesIn,
    PrintRunIn,
    PrintRunOut,
    PrintRunPageOut,
    PrintRunReceiveIn,
)
from app.services import package_workflows as service
from app.services.audit import log_action
from app.services.barcode import qr_png_data_uri
from app.services.idempotency import replay_idempotent_response, store_idempotent_response
from app.services.numbering import next_package_nos
from app.services.packaging_scope import (
    packaging_department_scope,
    packaging_departments_for_order,
    require_package_access,
)
from app.services.packages import (
    PackageWriteContext,
    _packaging_record_totals_by_batch,
    create_package,
    prime_package_batch_memberships,
    prime_packaged_quantity_availability,
)
from app.services.workflow import sync_production_order_status

router = APIRouter()

_PRINT_RUN_LABEL_LIMIT = 200
_OPERATION_PERMISSIONS = {
    "manual-receipt": {"storage.packages", "*"},
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


def _write(db, current, operation, payload, action):
    key = str(payload.request_key)
    scope = f"packages.{operation}.{current.id}"
    service.lock_request(db, current.id, operation, key)
    body = _request_body(operation, payload)
    replay = replay_idempotent_response(db, user=current, scope=scope, key=key, payload=body)
    if replay is not None:
        _validate_package_workflow_replay(db, current, operation, replay)
        return replay
    result = action()
    store_idempotent_response(db, scope=scope, key=key, payload=body, response=result, user=current)
    db.commit()
    return result


def _run(db, current, rid):
    run = db.query(PackagePrintRun).options(load_only(
        PackagePrintRun.id,
        PackagePrintRun.run_no,
        PackagePrintRun.code,
        PackagePrintRun.packaging_department_code,
        PackagePrintRun.package_ids,
        PackagePrintRun.created_at,
        PackagePrintRun.received_at,
        PackagePrintRun.deleted_package_ids,
        PackagePrintRun.deleted_at,
    )).filter(PackagePrintRun.id == rid).first()
    if not run:
        raise HTTPException(404, "Print run not found")
    permissions = set(user_permissions(current))
    if not permissions.intersection({"storage.packages", "storage.shipment", "*"}):
        packaging_department_scope(current, run.packaging_department_code)
    service.require_active_run(run)
    return run


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
    replay = replay_idempotent_response(db, user=current, scope=scope, key=key, payload=body)
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


@router.post("/print-runs/create-packages/reconcile")
def reconcile_packages_and_run(payload: PrintRunCreatePackagesIn, db: DbSession, current: CurrentUser):
    return _reconcile_package_workflow(db, current, "create-packages-run", payload)


@router.get("/print-runs", response_model=list[PrintRunOut] | PrintRunPageOut)
def list_print_runs(db: DbSession, production_order_id: int | None = None,
                    page: int | None = Query(default=None, ge=1),
                    page_size: int | None = Query(default=None, ge=1, le=100),
                    current: User = Depends(require_permissions("packaging.packages", "packaging.records", "storage.packages", "storage.shipment", "*"))):
    query = db.query(PackagePrintRun).options(load_only(
        PackagePrintRun.id,
        PackagePrintRun.run_no,
        PackagePrintRun.code,
        PackagePrintRun.created_at,
        PackagePrintRun.received_at,
        PackagePrintRun.package_ids,
        PackagePrintRun.deleted_package_ids,
        PackagePrintRun.deleted_at,
    )).filter(PackagePrintRun.deleted_at.is_(None))
    if production_order_id:
        query = query.filter(PackagePrintRun.id.in_(db.query(PackagePrintRunMember.run_id).join(
            Package, Package.id == PackagePrintRunMember.package_id).filter(Package.production_order_id == production_order_id)))
    permissions = set(user_permissions(current))
    if not permissions.intersection({"storage.packages", "storage.shipment", "*"}):
        query = query.filter(PackagePrintRun.packaging_department_code == packaging_department_scope(current))
    total = None
    if page is not None or page_size is not None:
        page = page or 1
        page_size = page_size or 100
        total = query.count()
    query = query.order_by(PackagePrintRun.id.desc())
    if total is None:
        runs = query.limit(100).all()
    else:
        runs = query.offset((page - 1) * page_size).limit(page_size).all()
    rows = service.run_list_payload(db, runs)
    if total is None:
        return rows
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


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
    run = db.query(PackagePrintRun).options(load_only(
        PackagePrintRun.id,
        PackagePrintRun.run_no,
        PackagePrintRun.package_ids,
        PackagePrintRun.deleted_package_ids,
        PackagePrintRun.deleted_at,
    )).filter_by(id=rid).with_for_update().first()
    if not run:
        raise HTTPException(404, "Print run not found")
    result = service.delete_manual_run(db, current, run, package_ids)
    db.commit()
    return result


@router.get("/print-runs/{rid}/label", response_class=HTMLResponse)
def print_run_label(rid: int, db: DbSession,
                     current: User = Depends(require_permissions("packaging.packages", "packaging.records", "storage.packages", "storage.shipment", "*"))):
    from app.api.routes.packages import (
        _h,
        _package_label_card_html,
        _package_label_reference_context,
        _PACKAGE_LABEL_CSS,
    )
    run = _run(db, current, rid)
    if len(run.package_ids) > _PRINT_RUN_LABEL_LIMIT:
        raise HTTPException(413, f"A print run label may contain at most {_PRINT_RUN_LABEL_LIMIT} packages")
    members = service.active_run_members(db, run)
    packages_by_id = {
        int(pkg.id): pkg
        for pkg in db.query(Package)
        .options(
            selectinload(Package.items),
            selectinload(Package.batch_allocations),
        )
        .filter(Package.id.in_([int(member.package_id) for member in members]))
        .all()
    } if members else {}
    context = _package_label_reference_context(db, list(packages_by_id.values()))
    cards = []
    current_quantity = 0
    for member in members:
        pkg = packages_by_id.get(int(member.package_id))
        if not pkg:
            raise HTTPException(409, "Print run contains a missing package; review required")
        if not run.received_at and service.contents(pkg) != member.snapshot:
            raise HTTPException(409, "Package changed since printing; review required before receipt")
        current_quantity += pkg.total_quantity
        cards.append(_package_label_card_html(
            db,
            pkg,
            context=context,
            active_label_checked=True,
        ))
    # This cover QR resolves only the persisted run, never an order/time selection.
    cover = f"""<section class='cover'><h1>{_h(run.run_no)}</h1>
    <p>Packages / Упаковки / Qadoqlar: {len(members)}</p>
    <p>Pieces / Изделия / Dona: {current_quantity}</p>
    <img width='180' height='180' src='{qr_png_data_uri(run.code)}' alt='QR'>
    <p>{_h(run.code)}</p><p>{', '.join(_h(m.snapshot['package_no']) for m in members)}</p></section>"""
    return warehouse_print_response(f"""<!doctype html><html><head><meta charset='utf-8'><title>{_h(run.run_no)}</title>
    <style>@page{{size:A4 portrait;margin:5mm}}{_PACKAGE_LABEL_CSS}
    .cover{{font-family:sans-serif;break-after:page;padding:10mm}} .cover p{{overflow-wrap:anywhere}}
    .sheet{{display:grid;grid-template-columns:repeat(2,98.5mm);gap:3mm}}</style></head>
    <body>{cover}<div class='sheet'>{''.join(cards)}</div>
    <button class='print-button' onclick='window.print()'>Print / Печать / Chop etish</button></body></html>""")
