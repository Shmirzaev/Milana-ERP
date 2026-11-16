"""Exact and legacy package recovery against an approved migrated PG database."""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes.package_workflows import receive_print_run
from app.libs.dto.fulfillment.package_workflows import PrintRunReceiveIn
from app.models import package_workflows_service as workflows
from app.models.packages_service import _apply_package_delete_request, _apply_package_edit_request, create_package
from app.models.packaging.recovery_guard_service import RECOVERY_REFUSAL
from app.models.warehouse_packages_service import delete_warehouse_package
from app.schemas import (
    AuditLog, FinishedGoodsStock, Package, PackageBatchAllocation, PackageChangeRequest,
    PackageItem, PackagePrintRunMember, PackagingRecord, ProductionBatch, ProductionOrder, User,
)
from app.tests.test_customer_create_postgres import actor, customer_pg_sessions  # noqa: F401
from app.tests.test_package_write_postgres import _seed_packaged_order


def facts(sessions):
    with sessions() as db:
        return {model.__tablename__: [dict(row) for row in db.execute(
            select(model.__table__).order_by(model.id)).mappings()]
            for model in (Package, PackageItem, PackageBatchAllocation, FinishedGoodsStock, AuditLog)}


@pytest.mark.parametrize("exact", [False, True])
def test_pg_recovery_preserves_snapshots_receipt_and_blocks_unsafe_writers(customer_pg_sessions, exact):
    sessions = customer_pg_sessions
    uid = actor(sessions, ["*"])
    oid, mid = _seed_packaged_order(sessions, 2)
    with sessions.begin() as db:
        db.get(ProductionOrder, oid).source_type = "standard"
        batch = ProductionBatch(batch_no=uuid4().hex, production_order_id=oid, planned_quantity=2)
        db.add(batch)
        db.flush()
        batch_id = batch.id
        record = db.query(PackagingRecord).order_by(PackagingRecord.id.desc()).first()
        record.production_batch_id = batch_id
    matrix = [{"model_id": mid, "color": "navy", "size": "M", "quantity": 2}]
    with sessions.begin() as db:
        package = create_package(db, production_order_id=oid, model_id=mid, color="navy", capacity=60,
                                 items=matrix, packaging_department_code="PKG", production_batch_id=batch_id,
                                 batch_allocations=[{"production_batch_id": batch_id, "quantity": 2}])
        pid = package.id
        db.query(PackageBatchAllocation).filter_by(package_id=pid).one().item_breakdown = matrix if exact else None
        db.flush()
        workflows.create_run(db, db.get(User, uid), [package])
        member = db.query(PackagePrintRunMember).filter_by(package_id=pid).one()
        expected = {"package_no": package.package_no, "barcode": package.barcode, "model_id": mid,
                    "color": "navy", "production_order_id": oid, "production_batch_id": batch_id,
                    "manual_receipt_id": None, "legacy_receipt_id": None,
                    "batch_allocations": [{"production_batch_id": batch_id, "quantity": 2,
                                           **({"item_breakdown": matrix} if exact else {})}],
                    "quantity": 2, "weight_kg": None, "items": matrix}
        assert member.snapshot == expected
    with sessions() as db:
        assert workflows.contents(db.get(Package, pid)) == expected
        assert db.query(PackageBatchAllocation).filter_by(package_id=pid).one().item_breakdown == (matrix if exact else None)
        code = db.get(Package, pid).barcode
        receive_print_run(PrintRunReceiveIn(code=code), db, db.get(User, uid))
    before = facts(sessions)
    with sessions() as db:
        receive_print_run(PrintRunReceiveIn(code=code), db, db.get(User, uid))
    assert facts(sessions) == before
    if exact:
        for operation in ("edit", "delete", "warehouse_delete"):
            with sessions() as db:
                request = PackageChangeRequest(package_id=pid, package_no=db.get(Package, pid).package_no,
                                               request_type="edit" if operation == "edit" else "delete", payload_json={})
                with pytest.raises(HTTPException) as refusal:
                    if operation == "edit":
                        _apply_package_edit_request(db, request, uid, allow_printed=True)
                    elif operation == "delete":
                        _apply_package_delete_request(db, request, allow_printed=True)
                    else:
                        delete_warehouse_package(db, db.get(User, uid), pid)
                assert refusal.value.status_code == 409 and refusal.value.detail == RECOVERY_REFUSAL
                db.commit()
            assert facts(sessions) == before
