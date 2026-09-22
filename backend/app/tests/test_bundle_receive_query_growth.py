from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes import bundles as bundle_routes
from app.models import Bundle, BundleScanLog, ProductionBatch, ProductionOrder, User, WorkOrder
from app.services import bundles as bundle_services
from app.tests.conftest import TestSessionLocal
from app.tests.test_bundle_accessory_gate_batching import _bundle_batch, _run_bulk


@pytest.mark.parametrize("mode", ["manual", "accept"])
@pytest.mark.parametrize("bundle_count", [1, 50, 401])
def test_bulk_sewing_receipt_has_bounded_shared_context_queries(monkeypatch, mode, bundle_count):
    case = _bundle_batch(bundle_count)
    monkeypatch.setattr(bundle_routes, "log_action", lambda *_args, **_kwargs: None)
    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = _run_bulk(db, case, mode)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert result["received_count"] == bundle_count
    normalized = [statement.lower() for statement in statements]
    department_reads = [statement for statement in normalized if "from departments" in statement]
    received_sum_reads = [
        statement for statement in normalized
        if "sum(" in statement and "bundles.quantity" in statement
    ]
    work_order_reads = [statement for statement in normalized if "from work_orders" in statement]
    production_order_reads = [
        statement for statement in normalized if "from production_orders" in statement
    ]
    assert len(department_reads) <= 2
    assert len(received_sum_reads) <= 1
    # Receipt status synchronization stays live per bundle, but its already
    # loaded order and work-order references are reused for the whole batch.
    assert len(production_order_reads) <= 3
    assert len(work_order_reads) <= 4
    print(f"{mode} {bundle_count}: {len(statements)} SELECTs")
    assert len(statements) == (20 if mode == "manual" else 30)
    with TestSessionLocal() as db:
        bundles = db.query(Bundle).filter(Bundle.id.in_(case["bundle_ids"])).all()
        assert {bundle.status for bundle in bundles} == {"received_sewing"}
        assert db.query(BundleScanLog).filter(
            BundleScanLog.bundle_id.in_(case["bundle_ids"]),
            BundleScanLog.scan_type == "received_sewing",
        ).count() == bundle_count


def _transition_snapshot(case):
    with TestSessionLocal() as db:
        bundles = (
            db.query(Bundle)
            .filter(Bundle.id.in_(case["bundle_ids"]))
            .order_by(Bundle.id)
            .all()
        )
        logs = (
            db.query(BundleScanLog)
            .filter(BundleScanLog.bundle_id.in_(case["bundle_ids"]))
            .order_by(BundleScanLog.bundle_id, BundleScanLog.id)
            .all()
        )
        work_orders = (
            db.query(WorkOrder)
            .filter(WorkOrder.production_order_id == case["order_id"])
            .order_by(WorkOrder.operation, WorkOrder.id)
            .all()
        )
        order = db.get(ProductionOrder, case["order_id"])
        return {
            "bundles": [
                (
                    row.status,
                    row.sewing_factory_code,
                    row.current_department_id,
                    row.next_department_id,
                )
                for row in bundles
            ],
            "logs": [
                (
                    row.scan_type,
                    row.from_department_id,
                    row.to_department_id,
                )
                for row in logs
            ],
            "work_orders": [
                (
                    row.operation,
                    row.status,
                    int(row.actual_input_qty or 0),
                    int(row.actual_output_qty or 0),
                    row.department_id,
                    row.sewing_flow_id,
                )
                for row in work_orders
            ],
            "order_status": order.status,
        }


def _current_user(db):
    current = db.query(User).filter(User.email == "admin@example.com").one()
    current.session_factory_code = "MIL"
    return current


def test_batched_sewing_receipt_matches_scalar_transition_state():
    scalar_case = _bundle_batch(3)
    batched_case = _bundle_batch(3)
    with TestSessionLocal() as db:
        current = _current_user(db)
        gate = bundle_services.verify_sewing_accessory_gate(db, scalar_case["order_id"])
        bundles = [db.get(Bundle, bundle_id) for bundle_id in scalar_case["bundle_ids"]]
        for bundle in bundles:
            bundle_services.receive_at_sewing(db, bundle, current, gate)
        db.commit()

    with TestSessionLocal() as db:
        current = _current_user(db)
        gate = bundle_services.verify_sewing_accessory_gate(db, batched_case["order_id"])
        bundles = [db.get(Bundle, bundle_id) for bundle_id in batched_case["bundle_ids"]]
        received = bundle_services.receive_many_at_sewing(db, bundles, current, gate)
        db.commit()

    assert received == batched_case["bundle_ids"]
    assert _transition_snapshot(batched_case) == _transition_snapshot(scalar_case)


def test_batched_receipt_synchronizes_order_before_each_callback():
    case = _bundle_batch(3)
    observed_statuses = []

    with TestSessionLocal() as db:
        current = _current_user(db)
        gate = bundle_services.verify_sewing_accessory_gate(db, case["order_id"])
        bundles = [db.get(Bundle, bundle_id) for bundle_id in case["bundle_ids"]]

        def capture_status(_bundle):
            observed_statuses.append(db.get(ProductionOrder, case["order_id"]).status)

        bundle_services.receive_many_at_sewing(
            db,
            bundles,
            current,
            gate,
            after_receive=capture_status,
        )

    assert observed_statuses == ["sewing", "sewing", "sewing"]


@pytest.mark.parametrize("topology", ["multiple_batches", "legacy_unbatched", "mixed_route"])
def test_batched_sewing_receipt_matches_scalar_across_route_topologies(topology):
    scalar_case = _bundle_batch(3)
    batched_case = _bundle_batch(3)

    for case in (scalar_case, batched_case):
        with TestSessionLocal() as db:
            bundles = [db.get(Bundle, bundle_id) for bundle_id in case["bundle_ids"]]
            work_order = db.get(WorkOrder, case["work_order_id"])
            if topology == "multiple_batches":
                second_batch = ProductionBatch(
                    production_order_id=case["order_id"],
                    batch_no=f"PERF13-{uuid4().hex[:8]}",
                    batch_index=2,
                    name="Second receipt batch",
                    planned_quantity=1,
                )
                db.add(second_batch)
                db.flush()
                bundles[-1].production_batch_id = second_batch.id
            elif topology == "legacy_unbatched":
                for bundle in bundles:
                    bundle.production_batch_id = None
                work_order.production_batch_id = None
            else:
                sibling = Bundle(
                    bundle_no=f"PERF13-MIX-{uuid4().hex[:8]}",
                    barcode=f"PERF13-MIX-BC-{uuid4().hex[:8]}",
                    production_order_id=case["order_id"],
                    production_batch_id=case["batch_id"],
                    model_id=bundles[0].model_id,
                    color=bundles[0].color,
                    size=bundles[0].size,
                    quantity=1,
                    current_department_id=bundles[0].current_department_id,
                    next_department_id=bundles[0].next_department_id,
                    sewing_factory_code="BST",
                    status="received_sewing",
                )
                db.add(sibling)
            db.commit()

    with TestSessionLocal() as db:
        current = _current_user(db)
        gate = bundle_services.verify_sewing_accessory_gate(db, scalar_case["order_id"])
        for bundle_id in scalar_case["bundle_ids"]:
            bundle_services.receive_at_sewing(db, db.get(Bundle, bundle_id), current, gate)
        db.commit()

    with TestSessionLocal() as db:
        current = _current_user(db)
        gate = bundle_services.verify_sewing_accessory_gate(db, batched_case["order_id"])
        bundles = [db.get(Bundle, bundle_id) for bundle_id in batched_case["bundle_ids"]]
        bundle_services.receive_many_at_sewing(db, bundles, current, gate)
        db.commit()

    assert _transition_snapshot(batched_case) == _transition_snapshot(scalar_case)


def test_batched_sewing_receipt_rejects_context_after_nested_rollback():
    case = _bundle_batch(3)
    with TestSessionLocal() as db:
        current = _current_user(db)
        gate = bundle_services.verify_sewing_accessory_gate(db, case["order_id"])
        nested = db.begin_nested()
        bundles = [db.get(Bundle, bundle_id) for bundle_id in case["bundle_ids"]]
        callbacks = 0

        def rollback_after_first(_bundle):
            nonlocal callbacks
            callbacks += 1
            if callbacks == 1:
                nested.rollback()

        with pytest.raises(HTTPException) as stale:
            bundle_services.receive_many_at_sewing(
                db, bundles, current, gate, after_receive=rollback_after_first
            )
        assert stale.value.status_code == 409
        db.rollback()

    with TestSessionLocal() as db:
        assert all(db.get(Bundle, bundle_id).status == "created" for bundle_id in case["bundle_ids"])
        assert db.query(BundleScanLog).filter(
            BundleScanLog.bundle_id.in_(case["bundle_ids"]),
            BundleScanLog.scan_type == "received_sewing",
        ).count() == 0


def test_batched_sewing_receipt_rolls_back_when_a_later_bundle_is_invalid():
    case = _bundle_batch(3)
    with TestSessionLocal() as db:
        current = _current_user(db)
        bundles = [db.get(Bundle, bundle_id) for bundle_id in case["bundle_ids"]]
        bundles[-1].status = "sent_to_printing"
        db.commit()

    with TestSessionLocal() as db:
        current = _current_user(db)
        bundles = [db.get(Bundle, bundle_id) for bundle_id in case["bundle_ids"]]
        gate = bundle_services.verify_sewing_accessory_gate(db, case["order_id"])
        with pytest.raises(HTTPException) as rejected:
            bundle_services.receive_many_at_sewing(db, bundles, current, gate)

        assert rejected.value.status_code == 400
        db.rollback()

    with TestSessionLocal() as db:
        assert [db.get(Bundle, bundle_id).status for bundle_id in case["bundle_ids"]] == [
            "created", "created", "sent_to_printing",
        ]
        assert db.query(BundleScanLog).filter(
            BundleScanLog.bundle_id.in_(case["bundle_ids"]),
            BundleScanLog.scan_type == "received_sewing",
        ).count() == 0


def test_batched_sewing_receipt_rejects_stale_or_other_order_gate():
    first = _bundle_batch(2)
    second = _bundle_batch(1)
    with TestSessionLocal() as db:
        current = _current_user(db)
        first_bundles = [db.get(Bundle, bundle_id) for bundle_id in first["bundle_ids"]]
        second_gate = bundle_services.verify_sewing_accessory_gate(db, second["order_id"])
        with pytest.raises(HTTPException) as wrong_order:
            bundle_services.receive_many_at_sewing(db, first_bundles, current, second_gate)
        assert wrong_order.value.status_code == 409

        first_gate = bundle_services.verify_sewing_accessory_gate(db, first["order_id"])
        db.rollback()
        with pytest.raises(HTTPException) as stale:
            bundle_services.receive_many_at_sewing(db, first_bundles, current, first_gate)
        assert stale.value.status_code == 409

    with TestSessionLocal() as db:
        assert db.query(BundleScanLog).filter(
            BundleScanLog.bundle_id.in_(first["bundle_ids"]),
            BundleScanLog.scan_type == "received_sewing",
        ).count() == 0


def test_batched_sewing_receipt_preserves_factory_denial_and_rollback():
    case = _bundle_batch(2)
    with TestSessionLocal() as db:
        second = db.get(Bundle, case["bundle_ids"][1])
        second.sewing_factory_code = "ECO"
        db.commit()

    with TestSessionLocal() as db:
        current = _current_user(db)
        bundles = [db.get(Bundle, bundle_id) for bundle_id in case["bundle_ids"]]
        gate = bundle_services.verify_sewing_accessory_gate(db, case["order_id"])
        with pytest.raises(HTTPException) as denied:
            bundle_services.receive_many_at_sewing(db, bundles, current, gate)

        assert denied.value.status_code == 403
        db.rollback()

    with TestSessionLocal() as db:
        assert [db.get(Bundle, bundle_id).status for bundle_id in case["bundle_ids"]] == [
            "created", "created",
        ]
        assert db.query(BundleScanLog).filter(
            BundleScanLog.bundle_id.in_(case["bundle_ids"]),
            BundleScanLog.scan_type == "received_sewing",
        ).count() == 0
        work_order = db.get(WorkOrder, case["work_order_id"])
        assert work_order.status == "waiting"
        assert int(work_order.actual_input_qty or 0) == 0
