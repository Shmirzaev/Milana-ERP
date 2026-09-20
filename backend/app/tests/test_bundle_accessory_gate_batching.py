from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes import bundles as bundle_routes
from app.models import Bundle, BundleScanLog, ProductionBatch, SewingAssignment, SewingFlow, User, WorkOrder
from app.services import bundles as bundle_services, inventory
from app.tests.conftest import TestSessionLocal
from app.tests.test_bundle_receiving_factory_scope import _ready_bundle


def _bundle_batch(count):
    first_id, work_order_id, order_id, _ = _ready_bundle("MIL", "created")
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        batch = ProductionBatch(
            production_order_id=order_id,
            batch_no=f"PERF04-{marker}",
            batch_index=1,
            name="Accessory gate batch",
            planned_quantity=count,
        )
        flow = SewingFlow(
            code=f"PERF04-{marker}",
            name=f"Accessory gate line {marker}",
            factory_code="MIL",
            is_active=True,
        )
        db.add_all([batch, flow])
        db.flush()
        first = db.get(Bundle, first_id)
        first.production_batch_id = batch.id
        first.quantity = 1
        db.get(WorkOrder, work_order_id).production_batch_id = batch.id
        extras = [
            Bundle(
                bundle_no=f"PERF04-{marker}-{number:04d}",
                barcode=f"PERF04-BC-{marker}-{number:04d}",
                production_order_id=order_id,
                production_batch_id=batch.id,
                model_id=first.model_id,
                color=first.color,
                size=first.size,
                quantity=1,
                current_department_id=first.current_department_id,
                next_department_id=first.next_department_id,
                sewing_factory_code="MIL",
                status="created",
            )
            for number in range(1, count)
        ]
        db.add_all(extras)
        db.commit()
        return {
            "order_id": int(order_id),
            "batch_id": int(batch.id),
            "flow_id": int(flow.id),
            "work_order_id": int(work_order_id),
            "bundle_ids": [int(first_id), *[int(bundle.id) for bundle in extras]],
        }


def _current_user(db):
    current = db.query(User).filter(User.email == "admin@example.com").one()
    current.session_factory_code = "MIL"
    return current


def _run_bulk(db, case, mode):
    current = _current_user(db)
    if mode == "manual":
        return bundle_routes.manual_receive_sewing(
            bundle_routes.SewingManualReceiveIn(
                production_order_id=case["order_id"],
                production_batch_id=case["batch_id"],
                factory_code="MIL",
            ),
            db,
            current,
        )
    return bundle_routes.accept_sewing_batch(
        case["batch_id"],
        bundle_routes.SewingBatchAcceptIn(sewing_flow_id=case["flow_id"]),
        db,
        current,
    )


@pytest.mark.parametrize("mode", ["manual", "accept"])
@pytest.mark.parametrize("bundle_count", [1, 50])
def test_bulk_sewing_receipt_checks_shared_accessory_gate_once(mode, bundle_count):
    case = _bundle_batch(bundle_count)
    with TestSessionLocal() as db:
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT") and "model_bom" in statement.lower():
                statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = _run_bulk(db, case, mode)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(statements) == 1
    assert result["received_count"] == bundle_count
    if mode == "manual":
        assert result["received_quantity"] == bundle_count
        assert result["bundle_ids"] == case["bundle_ids"]
    else:
        assert result["quantity"] == bundle_count
        assert result["already_accepted"] is False


@pytest.mark.parametrize("mode", ["manual", "accept"])
def test_rejected_shared_accessory_gate_has_no_bundle_or_assignment_writes(monkeypatch, mode):
    case = _bundle_batch(3)

    def reject_gate(_db, production_order_id):
        assert production_order_id == case["order_id"]
        raise HTTPException(409, "Synthetic incomplete accessory gate")

    monkeypatch.setattr(inventory, "ensure_accessories_issued_for_sewing", reject_gate)
    with TestSessionLocal() as db:
        with pytest.raises(HTTPException) as rejected:
            _run_bulk(db, case, mode)
        assert rejected.value.status_code == 409
        assert all(db.get(Bundle, bundle_id).status == "created" for bundle_id in case["bundle_ids"])
        assert db.query(BundleScanLog).filter(BundleScanLog.bundle_id.in_(case["bundle_ids"])).count() == 0
        assert db.query(SewingAssignment).filter_by(production_batch_id=case["batch_id"]).count() == 0
        work_order = db.get(WorkOrder, case["work_order_id"])
        assert work_order.sewing_flow_id is None
        assert work_order.status == "waiting"


def test_shared_accessory_gate_cannot_be_reused_for_another_order():
    first = _bundle_batch(1)
    second = _bundle_batch(1)

    with TestSessionLocal() as db:
        current = _current_user(db)
        gate = bundle_services.verify_sewing_accessory_gate(db, first["order_id"])
        bundle = db.get(Bundle, second["bundle_ids"][0])

        with pytest.raises(HTTPException) as rejected:
            bundle_services.receive_at_sewing(db, bundle, current, gate)

        assert rejected.value.status_code == 409
        assert bundle.status == "created"
        assert db.query(BundleScanLog).filter_by(bundle_id=bundle.id).count() == 0


def test_shared_accessory_gate_cannot_be_reused_after_transaction_ends():
    case = _bundle_batch(1)

    with TestSessionLocal() as db:
        current = _current_user(db)
        bundle = db.get(Bundle, case["bundle_ids"][0])
        gate = bundle_services.verify_sewing_accessory_gate(db, case["order_id"])
        db.rollback()

        with pytest.raises(HTTPException) as rejected:
            bundle_services.receive_at_sewing(db, bundle, current, gate)

        assert rejected.value.status_code == 409
        assert bundle.status == "created"
        assert db.query(BundleScanLog).filter_by(bundle_id=bundle.id).count() == 0


def test_batch_retry_with_every_bundle_received_does_not_recheck_accessories(monkeypatch):
    case = _bundle_batch(3)
    with TestSessionLocal() as db:
        for bundle_id in case["bundle_ids"]:
            db.get(Bundle, bundle_id).status = "received_sewing"
        db.commit()

    def unexpected_gate(_db, _production_order_id):
        raise AssertionError("A batch with no receive transitions must not recheck accessories")

    monkeypatch.setattr(inventory, "ensure_accessories_issued_for_sewing", unexpected_gate)
    with TestSessionLocal() as db:
        result = _run_bulk(db, case, "accept")

    assert result["already_accepted"] is True
    assert result["received_count"] == 0


def test_empty_batch_returns_not_found_without_checking_accessories(monkeypatch):
    case = _bundle_batch(1)
    with TestSessionLocal() as db:
        db.query(Bundle).filter(Bundle.id.in_(case["bundle_ids"])).delete(synchronize_session=False)
        db.commit()

    def unexpected_gate(_db, _production_order_id):
        raise AssertionError("An empty batch must fail before checking accessories")

    monkeypatch.setattr(inventory, "ensure_accessories_issued_for_sewing", unexpected_gate)
    with TestSessionLocal() as db:
        with pytest.raises(HTTPException) as rejected:
            _run_bulk(db, case, "accept")

    assert rejected.value.status_code == 404
