"""Real-PostgreSQL receipt rollback, authorization and lock-order coverage.

Uses the repository's approved, migrated PostgreSQL target fixture. It never
uses STABILIZATION_POSTGRES_URL or a developer/default database URL.
"""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes import purchasing
from app.core.deps import get_db
from app.core.security import create_access_token
from app.libs.dto.purchasing.purchase_order_input import PurchaseOrderReceiveIn
from app.libs.enums.inventory import StockBatchQcStatus
from app.libs.types.inventory import PurchaseOrderStockReceiptCommand
from app.models.idempotency_service import bind_idempotency_identity
from app.models.purchasing import receiving_service
from app.schemas import (
    AuditLog,
    IdempotencyRecord,
    Item,
    PurchaseOrder,
    PurchaseOrderLine,
    StockBatch,
    StockMovement,
    User,
    Warehouse,
)
from app.tests.test_customer_create_postgres import customer_pg_sessions, chain  # noqa: F401


def create_receipt_case(sessions):
    marker = uuid4().hex
    with sessions.begin() as db:
        actor = User(
            name="PO receipt PG actor",
            email=f"po-receipt-{marker}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            extra_permissions=["purchasing.receive"],
            is_active=True,
        )
        item = Item(sku=f"PO-RECEIPT-{marker}", name="Receipt material", category="accessory", unit="pcs")
        warehouse = Warehouse(name=f"PO receipt {marker}", type="accessory_storage")
        order = PurchaseOrder(po_no=f"PO-RECEIPT-{marker}", status="sent")
        db.add_all([actor, item, warehouse, order])
        db.flush()
        line = PurchaseOrderLine(
            purchase_order_id=order.id,
            item_id=item.id,
            ordered_quantity=100,
            received_quantity=0,
            unit="pcs",
            unit_cost=1,
            warehouse_id=warehouse.id,
        )
        db.add(line)
        db.flush()
        return {
            "actor_id": actor.id,
            "item_id": item.id,
            "warehouse_id": warehouse.id,
            "order_id": order.id,
            "order_no": order.po_no,
            "line_id": line.id,
            "payload": {
                "lines": [{
                    "purchase_order_line_id": line.id,
                    "received_quantity": 5,
                    "batch_no": f"PO-RECEIPT-BATCH-{marker}",
                    "warehouse_id": warehouse.id,
                    "qc_status": "passed",
                }],
            },
        }


def receive(sessions, case, *, key, payload=None):
    with sessions() as db:
        current = db.get(User, case["actor_id"])
        bind_idempotency_identity(db, current)
        try:
            return receiving_service.receive_purchase_order(
                db,
                order_id=case["order_id"],
                payload=PurchaseOrderReceiveIn.model_validate(payload or case["payload"]),
                current=current,
                idempotency_key=key,
            )
        except Exception:
            db.rollback()
            raise


def snapshot(sessions, case):
    with sessions() as db:
        line = db.get(PurchaseOrderLine, case["line_id"])
        order = db.get(PurchaseOrder, case["order_id"])
        batches = db.query(StockBatch).filter_by(internal_batch_no=case["order_no"]).order_by(StockBatch.id).all()
        movements = db.query(StockMovement).filter_by(
            reference_type="PurchaseOrderLine", reference_id=case["line_id"],
        ).order_by(StockMovement.id).all()
        audits = db.query(AuditLog).filter(
            ((AuditLog.entity_type == "StockBatch") & AuditLog.entity_id.in_([row.id for row in batches]))
            | ((AuditLog.entity_type == "PurchaseOrderLine") & (AuditLog.entity_id == case["line_id"]))
            | ((AuditLog.entity_type == "PurchaseOrder") & (AuditLog.entity_id == case["order_id"]))
        ).order_by(AuditLog.id).all()
        records = db.query(IdempotencyRecord).filter_by(user_id=case["actor_id"]).all()
        return {
            "received_quantity": float(line.received_quantity),
            "order_status": order.status,
            "batches": [
                (row.id, row.batch_no, row.internal_batch_no, row.qc_status, row.length_m, row.roll_lengths_m)
                for row in batches
            ],
            "movements": [
                (row.id, row.batch_id, row.to_warehouse_id, row.quantity, row.unit, row.created_by)
                for row in movements
            ],
            "audits": [
                (row.action, row.entity_type, row.entity_id, row.user_id, row.old_value_json, row.new_value_json)
                for row in audits
            ],
            "idempotency": [(row.key, row.request_hash, row.response_json) for row in records],
        }


def test_pg_route_permission_denial_has_no_receipt_writes(customer_pg_sessions):
    sessions = customer_pg_sessions
    case = create_receipt_case(sessions)
    with sessions.begin() as db:
        actor = db.get(User, case["actor_id"])
        actor.extra_permissions = []

    app = FastAPI()
    app.include_router(purchasing.router)

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    headers = {"Authorization": f"Bearer {create_access_token(str(case['actor_id']))}"}
    with TestClient(app) as client:
        response = client.post(
            f"/purchasing/orders/{case['order_id']}/receive",
            headers=headers,
            json=case["payload"],
        )
    assert response.status_code == 403
    after = snapshot(sessions, case)
    assert after["received_quantity"] == 0
    assert after["order_status"] == "sent"
    assert after["batches"] == after["movements"] == after["audits"] == after["idempotency"] == []


def test_pg_receipt_participant_command_qc_type_is_canonical():
    assert PurchaseOrderStockReceiptCommand.__dataclass_fields__["qc_status"].type is StockBatchQcStatus


def test_pg_receipt_audit_and_idempotency_failure_rolls_back_then_retry_succeeds(
    customer_pg_sessions, monkeypatch,
):
    sessions = customer_pg_sessions
    case = create_receipt_case(sessions)
    before = snapshot(sessions, case)
    original_store = receiving_service.store_idempotent_response

    def fail_after_staging(*args, **kwargs):
        original_store(*args, **kwargs)
        raise RuntimeError("injected before receipt commit")

    monkeypatch.setattr(receiving_service, "store_idempotent_response", fail_after_staging)
    with pytest.raises(RuntimeError, match="injected before receipt commit"):
        receive(sessions, case, key="po-receipt-rollback-retry")
    assert snapshot(sessions, case) == before

    monkeypatch.setattr(receiving_service, "store_idempotent_response", original_store)
    result = receive(sessions, case, key="po-receipt-rollback-retry")
    after = snapshot(sessions, case)
    assert result["id"] == case["order_id"]
    assert after["received_quantity"] == 5
    assert after["order_status"] == "partially_received"
    assert len(after["batches"]) == len(after["movements"]) == 1
    assert after["batches"][0][1:] == (
        case["payload"]["lines"][0]["batch_no"], case["order_no"], "passed", None, [],
    )
    assert after["movements"][0][1:] == (
        after["batches"][0][0], case["warehouse_id"], 5, "pcs", case["actor_id"],
    )
    stock_audit = next(row for row in after["audits"] if row[1] == "StockBatch")
    assert stock_audit[0] == "receive" and stock_audit[3] == case["actor_id"]
    assert stock_audit[5] == {
        "batch_no": case["payload"]["lines"][0]["batch_no"],
        "internal_batch_no": case["order_no"],
        "po_no": case["order_no"],
        "qty": 5.0,
    }
    line_audit = next(row for row in after["audits"] if row[1] == "PurchaseOrderLine")
    assert line_audit[0] == "receive_purchase_order_line" and line_audit[3] == case["actor_id"]
    assert line_audit[5] == {
        "po_no": case["order_no"],
        "batch_no": case["payload"]["lines"][0]["batch_no"],
        "internal_batch_no": case["order_no"],
        "item_id": case["item_id"],
        "received_quantity": 5.0,
        "total_received": 5.0,
    }
    order_audit = next(row for row in after["audits"] if row[1] == "PurchaseOrder")
    assert order_audit[0] == "update_status" and order_audit[3] == case["actor_id"]
    assert order_audit[4] == {"status": "sent"}
    assert order_audit[5] == {"status": "partially_received", "po_no": case["order_no"]}
    assert len(after["idempotency"]) == 1
    chain(sessions)


def test_pg_receipt_replay_rechecks_inventory_access_before_serving_saved_response(customer_pg_sessions):
    sessions = customer_pg_sessions
    case = create_receipt_case(sessions)
    receive(sessions, case, key="po-receipt-access-before-replay")
    committed = snapshot(sessions, case)

    with sessions.begin() as db:
        actor = db.get(User, case["actor_id"])
        actor.extra_permissions = [*(actor.extra_permissions or []), "inventory.materials_only"]

    with pytest.raises(HTTPException) as error:
        receive(sessions, case, key="po-receipt-access-before-replay")
    assert error.value.status_code == 403
    assert snapshot(sessions, case) == committed


@pytest.mark.parametrize("same_key", [True, False])
def test_pg_receipt_same_and_different_key_workers_serialize_on_purchase_order(
    customer_pg_sessions, same_key,
):
    sessions = customer_pg_sessions
    case = create_receipt_case(sessions)
    start = Event()
    ready = Queue()

    def worker(index):
        payload = case["payload"]
        if not same_key:
            payload = {
                "lines": [{
                    **case["payload"]["lines"][0],
                    "batch_no": f"{case['payload']['lines'][0]['batch_no']}-{index}",
                }],
            }
        with sessions() as db:
            current = db.get(User, case["actor_id"])
            bind_idempotency_identity(db, current)
            pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            ready.put(pid)
            assert start.wait(10), "PO receipt workers were not released"
            return receiving_service.receive_purchase_order(
                db,
                order_id=case["order_id"],
                payload=PurchaseOrderReceiveIn.model_validate(payload),
                current=current,
                idempotency_key="po-receipt-same-key" if same_key else f"po-receipt-key-{index}",
            )

    with sessions() as holder, ThreadPoolExecutor(max_workers=2) as pool:
        holder.execute(
            text("SELECT id FROM purchase_orders WHERE id = :id FOR UPDATE"),
            {"id": case["order_id"]},
        )
        futures = [pool.submit(worker, index) for index in range(2)]
        pids = [ready.get(timeout=10) for _ in futures]
        start.set()
        try:
            deadline = monotonic() + 8
            blocked_pids = set()
            while monotonic() < deadline:
                for pid in pids:
                    if holder.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}).scalar_one():
                        blocked_pids.add(pid)
                if len(blocked_pids) == len(pids):
                    break
                sleep(0.02)
            assert blocked_pids == set(pids), "both receipt workers must reach a real PostgreSQL row-lock wait"
        finally:
            holder.rollback()
        results = [future.result(timeout=20) for future in futures]

    if same_key:
        assert results[0] == results[1]
        expected = 1
    else:
        assert sorted(result["lines"][0]["received_quantity"] for result in results) == [5, 10]
        expected = 2

    committed = snapshot(sessions, case)
    assert committed["received_quantity"] == 5 * expected
    assert committed["order_status"] == "partially_received"
    assert len(committed["batches"]) == len(committed["movements"]) == expected
    assert len(committed["idempotency"]) == expected
    assert sum(row[0] == "receive" and row[1] == "StockBatch" for row in committed["audits"]) == expected
    assert sum(row[0] == "receive_purchase_order_line" for row in committed["audits"]) == expected
    assert sum(row[0] == "update_status" and row[1] == "PurchaseOrder" for row in committed["audits"]) == 1
    chain(sessions)
