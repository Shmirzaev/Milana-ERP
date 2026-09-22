import os
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import purchasing
from app.core.security import create_access_token
from app.db import session as session_module
from app.db.base import Base
from app.models import AuditLog, IdempotencyRecord, Item, PurchaseOrder, PurchaseOrderLine, Role, StockBatch, StockMovement, User, Warehouse
from app.schemas.purchasing import PurchaseOrderOut, PurchaseOrderReceiveIn


def create_receipt_order(session_factory):
    suffix = uuid4().hex
    with session_factory() as db:
        item = Item(sku=f"RECEIPT-{suffix}", name="Receipt test", category="accessory", unit="pcs")
        warehouse = Warehouse(name=f"Receipt {suffix}", type="accessory_storage")
        order = PurchaseOrder(po_no=f"RECEIPT-{suffix}", status="sent")
        db.add_all([item, warehouse, order])
        db.flush()
        line = PurchaseOrderLine(purchase_order_id=order.id, item_id=item.id, ordered_quantity=100,
                                 received_quantity=0, unit="pcs", warehouse_id=warehouse.id)
        db.add(line)
        db.commit()
        return {
            "order_id": order.id, "po_no": order.po_no, "line_id": line.id, "item_id": item.id,
            "payload": {"lines": [{"purchase_order_line_id": line.id, "received_quantity": 5,
                                    "batch_no": f"RECEIVED-{suffix}", "warehouse_id": warehouse.id}]},
        }


@pytest.fixture
def receipt_order():
    return create_receipt_order(session_module.SessionLocal)


def receive(client, headers, order, key="receipt-test", payload=None):
    return client.post(
        f"/api/purchasing/orders/{order['order_id']}/receive",
        headers={**headers, **({"Idempotency-Key": key} if key is not None else {})},
        json=payload if payload is not None else order["payload"],
    )


def receipt_state(order):
    with session_module.SessionLocal() as db:
        return (
            db.get(PurchaseOrderLine, order["line_id"]).received_quantity,
            db.get(PurchaseOrder, order["order_id"]).status,
            db.query(StockBatch).filter_by(internal_batch_no=order["po_no"]).count(),
            db.query(StockMovement).filter_by(reference_type="PurchaseOrderLine", reference_id=order["line_id"]).count(),
            db.query(AuditLog).count(), db.query(IdempotencyRecord).count(),
        )


@pytest.mark.parametrize("close_order", [False, True])
def test_receipt_retry_replays_original_response_without_more_stock(client, auth_headers, receipt_order, close_order):
    payload = {**receipt_order["payload"], "close_order": close_order}
    first = receive(client, auth_headers, receipt_order, payload=payload)
    assert first.status_code == 200, first.text
    before_retry = receipt_state(receipt_order)
    retry = receive(client, auth_headers, receipt_order, payload=payload)
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()
    assert receipt_state(receipt_order) == before_retry
    assert before_retry[0] == 5
    assert before_retry[2:4] == (1, 1)
    assert before_retry[5] == 1


def test_receipt_key_reuse_with_changed_payload_is_conflict(client, auth_headers, receipt_order):
    first = receive(client, auth_headers, receipt_order)
    assert first.status_code == 200, first.text
    before_retry = receipt_state(receipt_order)
    changed = {"lines": [{**receipt_order["payload"]["lines"][0], "received_quantity": 6}]}
    retry = receive(client, auth_headers, receipt_order, payload=changed)
    assert retry.status_code == 409, retry.text
    assert receipt_state(receipt_order) == before_retry


def test_reconcile_committed_receipt_replays_without_duplicate_stock(client, auth_headers, receipt_order):
    key = f"receipt-reconcile-{uuid4()}"
    created = receive(client, auth_headers, receipt_order, key=key)
    assert created.status_code == 200, created.text
    before = receipt_state(receipt_order)

    reconciled = client.post(
        f"/api/purchasing/orders/{receipt_order['order_id']}/receive/reconcile",
        headers={**auth_headers, "Idempotency-Key": key},
        json=receipt_order["payload"],
    )

    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json() == {"status": "completed", "result": created.json()}
    assert receipt_state(receipt_order) == before


def test_reconcile_rejected_pending_receipt_releases_corrected_submission(client, auth_headers, receipt_order):
    rejected_key = f"receipt-rejected-{uuid4()}"
    before = receipt_state(receipt_order)
    reconciled = client.post(
        f"/api/purchasing/orders/{receipt_order['order_id']}/receive/reconcile",
        headers={**auth_headers, "Idempotency-Key": rejected_key},
        json=receipt_order["payload"],
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json() == {"status": "cancelled"}

    delayed = receive(client, auth_headers, receipt_order, key=rejected_key)
    assert delayed.status_code == 409, delayed.text
    after_cancel = receipt_state(receipt_order)
    assert after_cancel[:5] == before[:5]
    assert after_cancel[5] == before[5] + 1

    corrected = {
        "lines": [{**receipt_order["payload"]["lines"][0], "received_quantity": 6}],
    }
    accepted = receive(
        client,
        auth_headers,
        receipt_order,
        key=f"receipt-corrected-{uuid4()}",
        payload=corrected,
    )
    assert accepted.status_code == 200, accepted.text
    final = receipt_state(receipt_order)
    assert final[0] == 6
    assert final[2:4] == (1, 1)
    assert final[5] == before[5] + 2


def test_receipt_reconciliation_failure_rolls_back_tombstone(client, auth_headers, receipt_order, monkeypatch):
    key = f"receipt-reconcile-rollback-{uuid4()}"
    original_store = purchasing.store_idempotent_response

    def fail_after_storing(*args, **kwargs):
        original_store(*args, **kwargs)
        raise HTTPException(503, "Synthetic reconciliation failure")

    before = receipt_state(receipt_order)
    monkeypatch.setattr(purchasing, "store_idempotent_response", fail_after_storing)
    failed = client.post(
        f"/api/purchasing/orders/{receipt_order['order_id']}/receive/reconcile",
        headers={**auth_headers, "Idempotency-Key": key},
        json=receipt_order["payload"],
    )
    assert failed.status_code == 503, failed.text
    assert receipt_state(receipt_order) == before

    monkeypatch.setattr(purchasing, "store_idempotent_response", original_store)
    accepted = receive(client, auth_headers, receipt_order, key=key)
    assert accepted.status_code == 200, accepted.text
    final = receipt_state(receipt_order)
    assert final[0] == 5
    assert final[2:4] == (1, 1)
    assert final[5] == before[5] + 1


def test_receipt_key_is_scoped_to_order(client, auth_headers, receipt_order):
    other = create_receipt_order(session_module.SessionLocal)
    first = receive(client, auth_headers, receipt_order)
    second = receive(client, auth_headers, other)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == receipt_order["order_id"]
    assert second.json()["id"] == other["order_id"]
    assert receipt_state(receipt_order)[0] == receipt_state(other)[0] == 5
    assert receipt_state(other)[5] == 2


def test_receipt_key_is_scoped_to_actor(client, auth_headers, receipt_order):
    with session_module.SessionLocal() as db:
        role = Role(name="Receipt operator", permissions=["purchasing.receive"])
        db.add(role)
        db.flush()
        user = User(name="Receipt operator", email="receipt-operator@example.invalid", password_hash="unused",
                    role_id=role.id, factory_code="MIL")
        db.add(user)
        db.commit()
        other_headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    first = receive(client, auth_headers, receipt_order)
    second = receive(client, other_headers, receipt_order)
    assert first.status_code == second.status_code == 200
    assert first.json()["lines"][0]["received_quantity"] == 5
    assert second.json()["lines"][0]["received_quantity"] == 10
    assert receipt_state(receipt_order)[5] == 2


def test_receipt_key_is_scoped_to_selected_factory(receipt_order):
    responses = []
    for factory_code in ("MIL", "ECO"):
        with session_module.SessionLocal() as db:
            current = db.query(User).filter_by(email="admin@example.com").one()
            current.session_factory_code = factory_code
            result = purchasing.receive_order(receipt_order["order_id"],
                                              PurchaseOrderReceiveIn(**receipt_order["payload"]), db,
                                              current=current, idempotency_key="factory-scoped")
            responses.append(PurchaseOrderOut.model_validate(result).model_dump(mode="json"))
    assert responses[0]["lines"][0]["received_quantity"] == 5
    assert responses[1]["lines"][0]["received_quantity"] == 10
    assert receipt_state(receipt_order)[5] == 2


def test_receipt_authorizes_each_line_once_before_service_write(monkeypatch, client, auth_headers, receipt_order):
    calls = []
    original = purchasing.inventory_access.require_item

    def tracked(db, user, item_id):
        calls.append(item_id)
        return original(db, user, item_id)

    monkeypatch.setattr(purchasing.inventory_access, "require_item", tracked)
    response = receive(client, auth_headers, receipt_order)
    assert response.status_code == 200, response.text
    assert calls == [receipt_order["item_id"]]
    state = receipt_state(receipt_order)
    assert state[0] == 5 and state[2:4] == (1, 1)


def test_receipt_access_denial_happens_before_service_writes(monkeypatch, client, auth_headers, receipt_order):
    before = receipt_state(receipt_order)

    def deny(*_args, **_kwargs):
        raise HTTPException(403, "Synthetic inventory denial")

    monkeypatch.setattr(purchasing.inventory_access, "require_item", deny)
    response = receive(client, auth_headers, receipt_order)

    assert response.status_code == 403, response.text
    assert receipt_state(receipt_order) == before


def test_receipt_without_key_keeps_legacy_multiple_receipts(client, auth_headers, receipt_order):
    first = receive(client, auth_headers, receipt_order, key=None)
    second = receive(client, auth_headers, receipt_order, key=None)
    assert first.status_code == second.status_code == 200
    state = receipt_state(receipt_order)
    assert state[0] == 10
    assert state[2:4] == (2, 2)
    assert state[5] == 0


def test_receipt_replay_rechecks_current_inventory_authorization(client, auth_headers, receipt_order):
    first = receive(client, auth_headers, receipt_order)
    assert first.status_code == 200, first.text
    with session_module.SessionLocal() as db:
        admin = db.query(User).filter_by(email="admin@example.com").one()
        admin.extra_permissions = [*(admin.extra_permissions or []), "inventory.materials_only"]
        db.commit()
    before_retry = receipt_state(receipt_order)
    retry = receive(client, auth_headers, receipt_order)
    assert retry.status_code == 403, retry.text
    assert receipt_state(receipt_order) == before_retry


def test_receipt_failure_rolls_back_stock_and_key_then_can_retry(client, auth_headers, receipt_order, monkeypatch):
    original_store = purchasing.store_idempotent_response

    def fail_after_storing(*args, **kwargs):
        original_store(*args, **kwargs)
        raise HTTPException(503, "Synthetic failure before commit")

    before = receipt_state(receipt_order)
    monkeypatch.setattr(purchasing, "store_idempotent_response", fail_after_storing)
    failed = receive(client, auth_headers, receipt_order)
    assert failed.status_code == 503, failed.text
    assert receipt_state(receipt_order) == before
    monkeypatch.setattr(purchasing, "store_idempotent_response", original_store)
    retry = receive(client, auth_headers, receipt_order)
    assert retry.status_code == 200, retry.text
    state = receipt_state(receipt_order)
    assert state[0] == 5
    assert state[2:4] == (1, 1)
    assert state[5] == 1


@pytest.fixture(scope="module")
def receipt_postgres_engine():
    """Use only an explicitly configured local server and a disposable schema."""
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL receipt concurrency coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Receipt concurrency tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"purchase_receipts_{uuid4().hex}"
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4, max_overflow=0, isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {StockBatch.__table__, StockMovement.__table__, PurchaseOrderLine.__table__,
                  AuditLog.__table__, IdempotencyRecord.__table__}
        pending = list(tables)
        while pending:
            for foreign_key in pending.pop().foreign_keys:
                target = foreign_key.column.table
                if target not in tables:
                    tables.add(target)
                    pending.append(target)
        Base.metadata.create_all(engine, tables=list(tables))
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


@pytest.mark.parametrize("same_key", [True, False])
def test_postgres_concurrent_receipts_serialize_before_replay(receipt_postgres_engine, same_key):
    session_factory = sessionmaker(bind=receipt_postgres_engine, autoflush=False, expire_on_commit=False)
    order = create_receipt_order(session_factory)
    with session_factory() as db:
        current = User(name="Concurrent receiver", email=f"receipt-{uuid4().hex}@example.invalid",
                       password_hash="unused", factory_code="MIL")
        db.add(current)
        db.commit()
        user_id = current.id
    ready = Queue()
    start = Event()

    def worker(key):
        with session_factory() as db:
            cached = db.get(PurchaseOrder, order["order_id"])
            cached_lines = list(cached.lines)
            current = db.get(User, user_id)
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10), "Receipt workers were not started"
            response = purchasing.receive_order(order["order_id"], PurchaseOrderReceiveIn(**order["payload"]),
                                                db, current=current, idempotency_key=key)
            assert cached_lines[0].id == order["line_id"]
            return response

    with session_factory() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(text("SELECT id FROM purchase_orders WHERE id = :id FOR UPDATE"), {"id": order["order_id"]})
        futures = [workers.submit(worker, key) for key in ("concurrent-one", "concurrent-one" if same_key else "concurrent-two")]
        try:
            worker_pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if all(bool(holder.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}).scalar_one())
                       for pid in worker_pids):
                    break
                sleep(0.02)
            else:
                pytest.fail("Both receipt transactions must reach an actual PostgreSQL lock wait")
        finally:
            start.set()
            holder.rollback()
        responses = [future.result(timeout=10) for future in futures]

    if same_key:
        assert responses[0] == responses[1]
    else:
        assert sorted(response["lines"][0]["received_quantity"] for response in responses) == [5, 10]
    expected_receipts = 1 if same_key else 2
    with session_factory() as db:
        assert db.get(PurchaseOrderLine, order["line_id"]).received_quantity == 5 * expected_receipts
        assert db.query(StockBatch).filter_by(internal_batch_no=order["po_no"]).count() == expected_receipts
        assert db.query(StockMovement).filter_by(reference_type="PurchaseOrderLine", reference_id=order["line_id"]).count() == expected_receipts
        assert db.query(IdempotencyRecord).filter_by(user_id=user_id).count() == expected_receipts


def test_postgres_reconciliation_waits_for_original_receipt_commit(
    receipt_postgres_engine,
    monkeypatch,
):
    session_factory = sessionmaker(bind=receipt_postgres_engine, autoflush=False, expire_on_commit=False)
    order = create_receipt_order(session_factory)
    with session_factory() as db:
        current = User(
            name="Receipt reconciler",
            email=f"receipt-reconcile-{uuid4().hex}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
        )
        db.add(current)
        db.commit()
        user_id = current.id

    original_started = Event()
    release_original = Event()
    reconcile_pid = Queue()
    original_receive = purchasing.receive_purchase_order
    key = f"reconcile-race-{uuid4()}"
    payload = PurchaseOrderReceiveIn(**order["payload"])

    def delayed_receive(*args, **kwargs):
        original_started.set()
        assert release_original.wait(10), "Original receipt was not released"
        return original_receive(*args, **kwargs)

    monkeypatch.setattr(purchasing, "receive_purchase_order", delayed_receive)

    def write_original():
        with session_factory() as db:
            return purchasing.receive_order(
                order["order_id"],
                payload,
                db,
                current=db.get(User, user_id),
                idempotency_key=key,
            )

    def reconcile():
        with session_factory() as db:
            reconcile_pid.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            return purchasing.reconcile_order_receipt(
                order["order_id"],
                payload,
                db,
                current=db.get(User, user_id),
                idempotency_key=key,
            )

    with ThreadPoolExecutor(max_workers=2) as workers:
        original = workers.submit(write_original)
        assert original_started.wait(10), "Original receipt did not reach its locked write"
        reconciled = workers.submit(reconcile)
        waiting_pid = reconcile_pid.get(timeout=10)
        try:
            with session_factory() as observer:
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    if observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiting_pid}).scalar_one():
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Reconciliation must wait on the original receipt order lock")
        finally:
            release_original.set()
        created = original.result(timeout=10)
        recovered = reconciled.result(timeout=10)

    assert recovered == {"status": "completed", "result": created}
    with session_factory() as db:
        assert db.get(PurchaseOrderLine, order["line_id"]).received_quantity == 5
        assert db.query(StockBatch).filter_by(internal_batch_no=order["po_no"]).count() == 1
        assert db.query(StockMovement).filter_by(
            reference_type="PurchaseOrderLine",
            reference_id=order["line_id"],
        ).count() == 1
        assert db.query(IdempotencyRecord).filter_by(user_id=user_id).count() == 1
