"""ST01 - retrying an accepted purchase receipt must not add stock twice.

The receive endpoint had no receipt identity, so a retry of an already
accepted receipt created a second StockBatch and a second stock movement.
These tests pin caller/order/payload-scoped replay for the receive endpoint.
"""

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
from app.services.idempotency import bind_idempotency_identity
from app.core.security import create_access_token
from app.db import session as session_module
from app.db.base import Base
from app.models import (
    AuditLog,
    IdempotencyRecord,
    Item,
    PurchaseOrder,
    PurchaseOrderLine,
    Role,
    StockBatch,
    StockMovement,
    User,
    Warehouse,
)
from app.schemas.purchasing import PurchaseOrderOut, PurchaseOrderReceiveIn


def create_receipt_order(session_factory, *, unit_cost=None, ordered_quantity=100):
    suffix = uuid4().hex
    with session_factory() as db:
        item = Item(sku=f"ST01-{suffix}", name="ST01 receipt item", category="accessory", unit="pcs")
        warehouse = Warehouse(name=f"ST01 {suffix}", type="accessory_storage")
        order = PurchaseOrder(po_no=f"ST01-{suffix}", status="sent")
        db.add_all([item, warehouse, order])
        db.flush()
        line = PurchaseOrderLine(
            purchase_order_id=order.id,
            item_id=item.id,
            ordered_quantity=ordered_quantity,
            received_quantity=0,
            unit="pcs",
            unit_cost=unit_cost,
            warehouse_id=warehouse.id,
        )
        db.add(line)
        db.commit()
        return {
            "order_id": order.id,
            "po_no": order.po_no,
            "line_id": line.id,
            "item_id": item.id,
            "warehouse_id": warehouse.id,
            "payload": {
                "lines": [
                    {
                        "purchase_order_line_id": line.id,
                        "received_quantity": 5,
                        "batch_no": f"ST01-BATCH-{suffix}",
                        "warehouse_id": warehouse.id,
                    }
                ]
            },
        }


@pytest.fixture
def receipt_order():
    return create_receipt_order(session_module.SessionLocal)


def receive(client, headers, order, key="st01-receipt", payload=None):
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
            db.query(StockMovement)
            .filter_by(reference_type="PurchaseOrderLine", reference_id=order["line_id"])
            .count(),
            db.query(AuditLog).count(),
            db.query(IdempotencyRecord).count(),
        )


def batch_costs(order):
    with session_module.SessionLocal() as db:
        return [
            str(row.cost_per_unit)
            for row in db.query(StockBatch)
            .filter_by(internal_batch_no=order["po_no"])
            .order_by(StockBatch.id)
            .all()
        ]


# --------------------------------------------------------------------------
# ST01 reproduction: the double-add itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize("close_order", [False, True])
def test_receipt_retry_replays_instead_of_adding_stock_twice(
    client, auth_headers, receipt_order, close_order
):
    """A retried receipt with the same key and body adds stock exactly once."""
    payload = {**receipt_order["payload"], "close_order": close_order}
    before = receipt_state(receipt_order)

    first = receive(client, auth_headers, receipt_order, payload=payload)
    assert first.status_code == 200, first.text
    after_first = receipt_state(receipt_order)
    # Exactly one receipt: 5 units, one batch, one movement, one replay record.
    assert after_first[0] == 5
    assert after_first[2:4] == (1, 1)
    assert after_first[5] == 1
    # Intended audit effects happened once, and only for the first attempt.
    assert after_first[4] > before[4]

    retry = receive(client, auth_headers, receipt_order, payload=payload)
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()
    assert receipt_state(receipt_order) == after_first


def test_receipt_retry_after_lost_response_replays_committed_receipt(client, auth_headers, receipt_order):
    """A retry after a lost response returns the committed result, not a new one."""
    first = receive(client, auth_headers, receipt_order)
    assert first.status_code == 200, first.text
    committed = receipt_state(receipt_order)

    # Simulate the caller never seeing the first response and retrying blindly.
    retry = receive(client, auth_headers, receipt_order)
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()
    assert retry.json()["lines"][0]["received_quantity"] == 5
    assert receipt_state(receipt_order) == committed


# --------------------------------------------------------------------------
# Replay is caller / order / factory scoped
# --------------------------------------------------------------------------


def test_receipt_key_reuse_with_changed_payload_is_conflict(client, auth_headers, receipt_order):
    first = receive(client, auth_headers, receipt_order)
    assert first.status_code == 200, first.text
    after_first = receipt_state(receipt_order)

    changed = {"lines": [{**receipt_order["payload"]["lines"][0], "received_quantity": 6}]}
    conflict = receive(client, auth_headers, receipt_order, payload=changed)
    assert conflict.status_code == 409, conflict.text
    # No partial writes: the rejected reuse changed nothing.
    assert receipt_state(receipt_order) == after_first


def test_receipt_key_is_scoped_to_order(client, auth_headers, receipt_order):
    other = create_receipt_order(session_module.SessionLocal)
    first = receive(client, auth_headers, receipt_order)
    second = receive(client, auth_headers, other)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == receipt_order["order_id"]
    assert second.json()["id"] == other["order_id"]
    assert receipt_state(receipt_order)[0] == receipt_state(other)[0] == 5
    assert receipt_state(other)[5] == 2


def test_receipt_key_is_scoped_to_caller(client, auth_headers, receipt_order):
    with session_module.SessionLocal() as db:
        role = Role(name="ST01 operator", permissions=["purchasing.receive"])
        db.add(role)
        db.flush()
        user = User(
            name="ST01 operator",
            email=f"st01-operator-{uuid4().hex}@example.invalid",
            password_hash="unused",
            role_id=role.id,
            factory_code="MIL",
        )
        db.add(user)
        db.commit()
        other_headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    first = receive(client, auth_headers, receipt_order)
    second = receive(client, other_headers, receipt_order)
    assert first.status_code == second.status_code == 200
    # A different caller must not obtain a replay of another caller's receipt.
    assert first.json()["lines"][0]["received_quantity"] == 5
    assert second.json()["lines"][0]["received_quantity"] == 10
    assert receipt_state(receipt_order)[5] == 2


def test_receipt_key_is_scoped_to_selected_factory(receipt_order):
    responses = []
    for factory_code in ("MIL", "ECO"):
        with session_module.SessionLocal() as db:
            current = db.query(User).filter_by(email="admin@example.com").one()
            current.session_factory_code = factory_code
            bind_idempotency_identity(db, current)
            result = purchasing.receive_order(
                receipt_order["order_id"],
                PurchaseOrderReceiveIn(**receipt_order["payload"]),
                db,
                current=current,
                idempotency_key="st01-factory-scoped",
            )
            responses.append(PurchaseOrderOut.model_validate(result).model_dump(mode="json"))
    # A different selected factory must not obtain a replay.
    assert responses[0]["lines"][0]["received_quantity"] == 5
    assert responses[1]["lines"][0]["received_quantity"] == 10
    assert receipt_state(receipt_order)[5] == 2


def test_receipt_replay_rechecks_current_inventory_authorization(client, auth_headers, receipt_order):
    """Authorization must be re-evaluated before a replay is served."""
    first = receive(client, auth_headers, receipt_order)
    assert first.status_code == 200, first.text
    after_first = receipt_state(receipt_order)

    with session_module.SessionLocal() as db:
        admin = db.query(User).filter_by(email="admin@example.com").one()
        admin.extra_permissions = [*(admin.extra_permissions or []), "inventory.materials_only"]
        db.commit()

    retry = receive(client, auth_headers, receipt_order)
    assert retry.status_code == 403, retry.text
    assert receipt_state(receipt_order) == after_first


# --------------------------------------------------------------------------
# Rollback and backward compatibility
# --------------------------------------------------------------------------


def test_receipt_failure_rolls_back_stock_and_key_then_can_retry(
    client, auth_headers, receipt_order, monkeypatch
):
    before = receipt_state(receipt_order)
    original_store = purchasing.store_idempotent_response

    def fail_after_storing(*args, **kwargs):
        original_store(*args, **kwargs)
        raise HTTPException(503, "Synthetic failure before commit")

    monkeypatch.setattr(purchasing, "store_idempotent_response", fail_after_storing)
    failed = receive(client, auth_headers, receipt_order)
    assert failed.status_code == 503, failed.text
    # No replay row and no stock residue after the failed transaction.
    assert receipt_state(receipt_order) == before

    monkeypatch.setattr(purchasing, "store_idempotent_response", original_store)
    retry = receive(client, auth_headers, receipt_order)
    assert retry.status_code == 200, retry.text
    state = receipt_state(receipt_order)
    assert state[0] == 5
    assert state[2:4] == (1, 1)
    assert state[5] == 1


def test_receipt_without_key_keeps_legacy_multiple_receipts(client, auth_headers, receipt_order):
    first = receive(client, auth_headers, receipt_order, key=None)
    second = receive(client, auth_headers, receipt_order, key=None)
    assert first.status_code == second.status_code == 200
    state = receipt_state(receipt_order)
    assert state[0] == 10
    assert state[2:4] == (2, 2)
    assert state[5] == 0


# --------------------------------------------------------------------------
# Preserved costing behaviour across a replay
# --------------------------------------------------------------------------


def test_receipt_retry_preserves_halves_up_four_decimal_unit_cost(client, auth_headers):
    order = create_receipt_order(session_module.SessionLocal, unit_cost=1)
    priced = {
        "lines": [
            {**order["payload"]["lines"][0], "cost_per_unit": 2.34567},
        ]
    }
    first = receive(client, auth_headers, order, payload=priced)
    assert first.status_code == 200, first.text
    assert batch_costs(order) == ["2.3457"]

    retry = receive(client, auth_headers, order, payload=priced)
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()
    assert batch_costs(order) == ["2.3457"]
    assert receipt_state(order)[2] == 1


def test_omitted_cost_receipt_replays_and_keeps_stored_cost(client, auth_headers):
    """An omitted cost must stay fingerprint-compatible with the first attempt."""
    order = create_receipt_order(session_module.SessionLocal, unit_cost=3.14159)
    first = receive(client, auth_headers, order)
    assert first.status_code == 200, first.text
    assert batch_costs(order) == ["3.1416"]

    retry = receive(client, auth_headers, order)
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()
    assert receipt_state(order)[2:4] == (1, 1)
    assert batch_costs(order) == ["3.1416"]


def test_repeated_line_in_one_receipt_retains_preceding_explicit_price(client, auth_headers):
    order = create_receipt_order(session_module.SessionLocal, unit_cost=1)
    line = order["payload"]["lines"][0]
    payload = {
        "lines": [
            {**line, "batch_no": f"{line['batch_no']}-A", "cost_per_unit": 2.34567},
            {**line, "batch_no": f"{line['batch_no']}-B"},
        ]
    }
    response = receive(client, auth_headers, order, payload=payload)
    assert response.status_code == 200, response.text
    # The second line falls back to the first line's rounded explicit price,
    # not the order line's original cost.
    assert batch_costs(order) == ["2.3457", "2.3457"]


# --------------------------------------------------------------------------
# Real PostgreSQL concurrency (two independent connections). SQLite has no
# FOR UPDATE, so nothing below is provable on the SQLite test engine.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def receipt_postgres_engine():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip(
            "Set STABILIZATION_POSTGRES_URL to a local PostgreSQL 16 instance "
            "for real receipt concurrency coverage (SQLite cannot prove FOR UPDATE)"
        )
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Receipt concurrency tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"st01_receipts_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=6,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {
            StockBatch.__table__,
            StockMovement.__table__,
            PurchaseOrderLine.__table__,
            AuditLog.__table__,
            IdempotencyRecord.__table__,
        }
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
    session_factory = sessionmaker(
        bind=receipt_postgres_engine, autoflush=False, expire_on_commit=False
    )
    order = create_receipt_order(session_factory)
    with session_factory() as db:
        current = User(
            name="ST01 concurrent receiver",
            email=f"st01-concurrent-{uuid4().hex}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
        )
        db.add(current)
        db.commit()
        user_id = current.id

    ready = Queue()
    start = Event()
    errors = []

    def worker(key):
        try:
            with session_factory() as db:
                current = db.get(User, user_id)
                bind_idempotency_identity(db, current)
                ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
                assert start.wait(20), "ST01 receipt workers were not started"
                return purchasing.receive_order(
                    order["order_id"],
                    PurchaseOrderReceiveIn(**order["payload"]),
                    db,
                    current=current,
                    idempotency_key=key,
                )
        except Exception as error:  # noqa: BLE001 - surfaced in the assertion below
            errors.append(repr(error))
            raise

    with session_factory() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(
            text("SELECT id FROM purchase_orders WHERE id = :id FOR UPDATE"),
            {"id": order["order_id"]},
        )
        futures = [
            workers.submit(worker, "st01-concurrent-one" if same_key else f"st01-concurrent-{index}")
            for index in range(2)
        ]
        try:
            pids = [ready.get(timeout=20) for _ in futures]
            start.set()
            deadline = monotonic() + 20
            while monotonic() < deadline:
                if all(
                    bool(
                        holder.execute(
                            text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}
                        ).scalar_one()
                    )
                    for pid in pids
                ):
                    break
                sleep(0.02)
            else:
                pytest.fail("Both ST01 receipt transactions must reach a real PostgreSQL lock wait")
        finally:
            start.set()
            holder.rollback()
        responses = [future.result(timeout=30) for future in futures]

    assert not errors, errors
    if same_key:
        assert responses[0] == responses[1], "same-key concurrent receipts must replay one result"
    else:
        assert sorted(r["lines"][0]["received_quantity"] for r in responses) == [5, 10]

    expected_receipts = 1 if same_key else 2
    with session_factory() as db:
        assert float(db.get(PurchaseOrderLine, order["line_id"]).received_quantity) == 5 * expected_receipts
        assert db.query(StockBatch).filter_by(internal_batch_no=order["po_no"]).count() == expected_receipts
        assert (
            db.query(StockMovement)
            .filter_by(reference_type="PurchaseOrderLine", reference_id=order["line_id"])
            .count()
            == expected_receipts
        )
        assert db.query(IdempotencyRecord).filter_by(user_id=user_id).count() == expected_receipts
