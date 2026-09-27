"""Waste sales cannot exceed the locked remaining quantity."""

from concurrent.futures import ThreadPoolExecutor
import os
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import waste
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import AuditLog, IdempotencyRecord, User, WasteDisposalRequest, WasteRecord, WasteSale
from app.tests.conftest import test_engine


def _actor(permissions=("waste.sell",), session_factory=SessionLocal):
    with session_factory() as db:
        actor = User(
            name="Synthetic waste seller",
            email=f"waste-sale-{uuid4().hex}@example.com",
            password_hash="unused-token-fixture",
            factory_code="MIL",
            extra_permissions=list(permissions),
        )
        db.add(actor)
        db.commit()
        return actor.id, {"Authorization": f"Bearer {create_access_token(actor.id)}"}


def _fixture(*, quantity=10, state="received_by_waste_department", sellable=True, session_factory=SessionLocal):
    with session_factory() as db:
        record = WasteRecord(
            waste_type="Synthetic sellable offcuts",
            quantity=quantity,
            unit="kg",
            sellable=sellable,
            estimated_value=25,
            status=state,
        )
        db.add(record)
        db.commit()
        return record.id


def _snapshot(wid, session_factory=SessionLocal):
    with session_factory() as db:
        record = db.get(WasteRecord, wid)
        sales = db.query(WasteSale).filter_by(waste_record_id=wid).order_by(WasteSale.id).all()
        audits = (
            db.query(AuditLog)
            .filter(AuditLog.entity_type == "WasteRecord", AuditLog.entity_id == wid, AuditLog.action == "sell")
            .order_by(AuditLog.id)
            .all()
        )
        return {
            "record": {column.name: getattr(record, column.name) for column in record.__table__.columns},
            "sales": [{column.name: getattr(row, column.name) for column in row.__table__.columns} for row in sales],
            "audits": [row.new_value_json for row in audits],
            "idempotency_count": db.query(IdempotencyRecord).filter(
                IdempotencyRecord.scope.like("waste.sales.%"),
            ).count(),
        }


def _sell(client, headers, wid, *, quantity, unit_price=2.5, buyer_name="Synthetic buyer", key=None):
    if key is None:
        key = f"waste-sale-test-{uuid4().hex}"
    request_headers = {**headers, **({"Idempotency-Key": key} if key else {})}
    return client.post(
        f"/api/waste/{wid}/sell",
        headers=request_headers,
        json={"buyer_name": buyer_name, "quantity": quantity, "unit_price": unit_price},
    )


def _reconcile(client, headers, wid, *, quantity, unit_price=2.5, buyer_name="Synthetic buyer", key=None):
    request_headers = {**headers, **({"Idempotency-Key": key} if key else {})}
    return client.post(
        f"/api/waste/{wid}/sell/reconcile",
        headers=request_headers,
        json={"buyer_name": buyer_name, "quantity": quantity, "unit_price": unit_price},
    )


def test_partial_sales_keep_stock_open_until_exactly_exhausted(client):
    _, headers = _actor()
    wid = _fixture(quantity=10)

    first = _sell(client, headers, wid, quantity=4)
    assert first.status_code == 200, first.text
    assert first.json()["quantity"] == 4 and first.json()["total_amount"] == 10
    after_partial = _snapshot(wid)
    assert after_partial["record"]["status"] == "received_by_waste_department"
    assert [float(row["quantity"]) for row in after_partial["sales"]] == [4]
    assert after_partial["audits"] == [{"quantity": 4.0, "remaining_quantity": 6.0, "amount": 10.0}]

    final = _sell(client, headers, wid, quantity=6, unit_price=3)
    assert final.status_code == 200, final.text
    assert final.json()["quantity"] == 6 and final.json()["total_amount"] == 18
    exhausted = _snapshot(wid)
    assert exhausted["record"]["status"] == "sold"
    assert sum(float(row["quantity"]) for row in exhausted["sales"]) == 10
    assert exhausted["audits"][-1] == {"quantity": 6.0, "remaining_quantity": 0.0, "amount": 18.0}

    retry = _sell(client, headers, wid, quantity=1)
    assert retry.status_code == 400
    assert retry.json() == {"detail": "Cannot sell from status 'sold'"}
    assert _snapshot(wid) == exhausted


def test_sale_response_does_not_reload_persisted_row_after_commit(client):
    _, headers = _actor()
    wid = _fixture()
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from waste_sales " in normalized:
            statements.append(normalized)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = _sell(client, headers, wid, quantity=2, unit_price=3)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert response.json()["quantity"] == 2
    assert response.json()["unit_price"] == 3
    assert response.json()["total_amount"] == 6
    assert len(statements) == 1
    assert statements[0].startswith("select waste_sales.quantity as waste_sales_quantity from waste_sales ")


def test_sale_rejects_quantity_above_aggregate_remaining_without_writes(client):
    _, headers = _actor()
    wid = _fixture(quantity=10)
    assert _sell(client, headers, wid, quantity=3).status_code == 200
    before = _snapshot(wid)

    response = _sell(client, headers, wid, quantity=7.0001, unit_price=0)

    assert response.status_code == 400
    assert response.json() == {"detail": "Sale quantity exceeds remaining waste quantity 7.0000"}
    assert _snapshot(wid) == before


@pytest.mark.parametrize(("field", "value", "detail"), [
    ("quantity", "1.00000000000000001", "Sale quantity supports at most 4 decimal places"),
    ("unit_price", "2.00000000000000001", "Unit price supports at most 2 decimal places"),
])
def test_sale_preserves_decimal_input_precision_when_validating(client, field, value, detail):
    _, headers = _actor()
    wid = _fixture()
    before = _snapshot(wid)

    response = client.post(
        f"/api/waste/{wid}/sell",
        headers={**headers, "Idempotency-Key": f"waste-sale-test-{uuid4().hex}"},
        json={"buyer_name": "Synthetic buyer", "quantity": 1, "unit_price": 2, field: value},
    )
    assert response.status_code == 400, response.text
    assert response.json() == {"detail": detail}
    assert _snapshot(wid) == before


@pytest.mark.parametrize(("field", "value", "detail"), [
    ("quantity", 0, "Sale quantity must be finite and greater than zero"),
    ("quantity", -1, "Sale quantity must be finite and greater than zero"),
    ("quantity", 0.00001, "Sale quantity supports at most 4 decimal places"),
    ("unit_price", -0.01, "Unit price must be finite and nonnegative"),
    ("buyer_name", "   ", "Buyer name is required"),
    ("buyer_name", "x" * 256, "Buyer name must be at most 255 characters"),
    ("unit_price", 2.555, "Unit price supports at most 2 decimal places"),
])
def test_sale_rejects_invalid_payload_values_without_writes(client, field, value, detail):
    _, headers = _actor()
    wid = _fixture()
    before = _snapshot(wid)
    payload = {"buyer_name": "Synthetic buyer", "quantity": 1, "unit_price": 2.5, field: value}

    response = client.post(
        f"/api/waste/{wid}/sell",
        headers={**headers, "Idempotency-Key": f"waste-sale-test-{uuid4().hex}"},
        json=payload,
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": detail}
    assert _snapshot(wid) == before


@pytest.mark.parametrize(("quantity", "unit_price", "detail"), [
    (float("nan"), 1, "Sale quantity must be finite and greater than zero"),
    (float("inf"), 1, "Sale quantity must be finite and greater than zero"),
    (1, float("nan"), "Unit price must be finite and nonnegative"),
    (1, float("inf"), "Unit price must be finite and nonnegative"),
])
def test_sale_rejects_nonfinite_direct_values_without_writes(quantity, unit_price, detail):
    actor_id, _ = _actor()
    wid = _fixture()
    before = _snapshot(wid)
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as rejected:
            waste.sell_waste(
                wid,
                waste.WasteSaleIn(buyer_name="Synthetic buyer", quantity=quantity, unit_price=unit_price),
                db,
                db.get(User, actor_id),
                f"waste-sale-unit-{uuid4().hex}",
            )
    assert rejected.value.status_code == 400 and rejected.value.detail == detail
    assert _snapshot(wid) == before


@pytest.mark.parametrize("state", ["recorded", "sold", "pending_disposal_approval", "disposal_approved", "disposed"])
def test_sale_rejects_non_received_or_terminal_stock_without_writes(client, state):
    _, headers = _actor()
    wid = _fixture(state=state)
    before = _snapshot(wid)

    response = _sell(client, headers, wid, quantity=1)

    assert response.status_code == 400
    assert response.json() == {"detail": f"Cannot sell from status '{state}'"}
    assert _snapshot(wid) == before


def test_sale_requires_sellable_stock_and_permission(client):
    _, permitted = _actor()
    _, restricted = _actor(())
    wid = _fixture(sellable=False)
    before = _snapshot(wid)
    path = f"/api/waste/{wid}/sell"
    payload = {"buyer_name": "Synthetic buyer", "quantity": 1, "unit_price": 2.5}

    assert client.post(path, json=payload).status_code == 401
    assert client.post(path, headers=restricted, json=payload).status_code == 403
    denied = client.post(
        path,
        headers={**permitted, "Idempotency-Key": f"waste-sale-test-{uuid4().hex}"},
        json=payload,
    )
    assert denied.status_code == 400 and denied.json() == {"detail": "Waste is not marked sellable"}
    assert client.post("/api/waste/2000000000/sell", headers=permitted, json=payload).status_code == 404
    assert _snapshot(wid) == before


def test_sale_idempotency_key_distinguishes_retry_from_legitimate_repeat(client):
    _, headers = _actor()
    wid = _fixture(quantity=10)
    key = f"waste-sale-{uuid4().hex}"

    first = _sell(client, headers, wid, quantity=2, key=key)
    replay = _sell(client, headers, wid, quantity=2, key=key)
    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    after_replay = _snapshot(wid)
    assert len(after_replay["sales"]) == 1 and after_replay["idempotency_count"] == 1

    mismatch = _sell(client, headers, wid, quantity=3, key=key)
    assert mismatch.status_code == 409
    assert _snapshot(wid) == after_replay

    legitimate_repeat = _sell(client, headers, wid, quantity=2, key=f"{key}-second")
    assert legitimate_repeat.status_code == 200, legitimate_repeat.text
    assert len(_snapshot(wid)["sales"]) == 2


def test_sale_replay_fails_closed_when_historical_sale_was_removed(client):
    _, headers = _actor()
    wid = _fixture(quantity=5)
    key = f"waste-sale-removed-{uuid4().hex}"
    created = _sell(client, headers, wid, quantity=2, key=key)
    assert created.status_code == 200, created.text

    # Simulate an independently reviewed historical correction. The saved
    # request key must never make a now-absent sale appear completed again.
    with SessionLocal() as db:
        db.query(WasteSale).filter(WasteSale.id == created.json()["id"]).delete()
        db.commit()
    before = _snapshot(wid)

    replay = _sell(client, headers, wid, quantity=2, key=key)
    assert replay.status_code == 410
    assert replay.json() == {
        "detail": "This waste sale result is no longer available; reconcile before retrying",
    }
    assert _snapshot(wid) == before

    reconciled = _reconcile(client, headers, wid, quantity=2, key=key)
    assert reconciled.status_code == 200
    assert reconciled.json() == {"status": "completed_unavailable"}
    assert _snapshot(wid) == before


def test_sale_idempotency_scope_isolated_by_authenticated_user_and_parent(client):
    _, first_headers = _actor()
    _, second_headers = _actor()
    first_wid = _fixture(quantity=5)
    second_wid = _fixture(quantity=5)
    key = f"waste-sale-scope-{uuid4().hex}"

    first = _sell(client, first_headers, first_wid, quantity=1, key=key)
    other_actor = _sell(client, second_headers, first_wid, quantity=1, key=key)
    other_parent = _sell(client, first_headers, second_wid, quantity=1, key=key)

    assert first.status_code == other_actor.status_code == other_parent.status_code == 200
    assert len({first.json()["id"], other_actor.json()["id"], other_parent.json()["id"]}) == 3
    assert len(_snapshot(first_wid)["sales"]) == 2
    assert len(_snapshot(second_wid)["sales"]) == 1


def test_sale_reconciliation_returns_committed_result_without_replaying_sale(client):
    _, headers = _actor()
    wid = _fixture(quantity=5)
    key = f"waste-sale-reconcile-{uuid4().hex}"

    created = _sell(client, headers, wid, quantity=2.25, unit_price=3.5, buyer_name="Exact buyer", key=key)
    assert created.status_code == 200, created.text
    before = _snapshot(wid)

    reconciled = _reconcile(
        client, headers, wid, quantity=2.25, unit_price=3.5, buyer_name="Exact buyer", key=key,
    )

    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json() == {"status": "completed", "result": created.json()}
    assert _snapshot(wid) == before


def test_sale_reconciliation_tombstones_unused_key_before_corrected_sale(client):
    _, headers = _actor()
    wid = _fixture(quantity=5)
    key = f"waste-sale-cancel-{uuid4().hex}"

    missing_key = _reconcile(client, headers, wid, quantity=2)
    assert missing_key.status_code == 400
    assert missing_key.json() == {"detail": "Idempotency-Key is required for waste sale reconciliation"}

    reconciled = _reconcile(client, headers, wid, quantity=2, key=key)
    assert reconciled.status_code == 200 and reconciled.json() == {"status": "cancelled"}
    before = _snapshot(wid)

    delayed = _sell(client, headers, wid, quantity=2, key=key)
    assert delayed.status_code == 409
    assert delayed.json() == {
        "detail": "This waste sale request was cancelled; submit corrected values with a new key",
    }
    assert _snapshot(wid) == before

    corrected = _sell(client, headers, wid, quantity=2, key=f"{key}-corrected")
    assert corrected.status_code == 200, corrected.text
    assert len(_snapshot(wid)["sales"]) == 1


def test_sale_reconciliation_preserves_payload_and_current_authorization(client):
    actor_id, headers = _actor()
    wid = _fixture(quantity=5)
    key = f"waste-sale-auth-{uuid4().hex}"
    created = _sell(client, headers, wid, quantity=2, unit_price=4, buyer_name="Original buyer", key=key)
    assert created.status_code == 200, created.text
    before = _snapshot(wid)

    changed = _reconcile(client, headers, wid, quantity=2, unit_price=4, buyer_name="Changed buyer", key=key)
    assert changed.status_code == 409
    assert changed.json() == {"detail": "Idempotency-Key was already used with a different request payload"}
    assert _snapshot(wid) == before

    with SessionLocal() as db:
        actor = db.get(User, actor_id)
        actor.extra_permissions = []
        db.commit()
    unavailable = _reconcile(
        client, headers, wid, quantity=2, unit_price=4, buyer_name="Original buyer", key=key,
    )
    assert unavailable.status_code == 200
    assert unavailable.json() == {"status": "completed_unavailable"}
    assert _snapshot(wid) == before


def test_sale_preserves_database_rounding_for_fractional_cent_total(client):
    _, headers = _actor()
    wid = _fixture()

    response = _sell(client, headers, wid, quantity=2.75, unit_price=2.5)

    assert response.status_code == 200, response.text
    assert response.json()["total_amount"] == 6.88
    snapshot = _snapshot(wid)
    assert float(snapshot["sales"][0]["total_amount"]) == 6.88
    assert snapshot["record"]["status"] == "received_by_waste_department"


def test_sale_fails_closed_for_corrupt_historical_quantities(client):
    _, headers = _actor()
    negative_parent = _fixture(quantity=-1)
    negative_sale_parent = _fixture(quantity=10)
    with SessionLocal() as db:
        db.add(WasteSale(
            waste_record_id=negative_sale_parent,
            buyer_name="Historical corrupt sale",
            quantity=-1,
            unit_price=1,
            total_amount=-1,
        ))
        db.commit()

    parent_response = _sell(client, headers, negative_parent, quantity=1)
    history_response = _sell(client, headers, negative_sale_parent, quantity=1)

    assert parent_response.status_code == 400
    assert parent_response.json() == {"detail": "Stored waste quantity is invalid"}
    assert history_response.status_code == 400
    assert history_response.json() == {"detail": "Historical waste sale quantity is invalid"}


def test_remaining_quantity_rejects_nonfinite_parent_before_querying_history():
    record = WasteRecord(id=2_000_000_000, quantity=float("nan"))
    with SessionLocal() as db, pytest.raises(HTTPException) as rejected:
        waste._remaining_sale_quantity(db, record)
    assert rejected.value.status_code == 400
    assert rejected.value.detail == "Stored waste quantity is invalid"


def test_partial_sale_cannot_double_dispose_original_quantity(client):
    _, headers = _actor(("waste.sell", "waste.disposal"))
    wid = _fixture(quantity=10)
    assert _sell(client, headers, wid, quantity=4).status_code == 200
    before = _snapshot(wid)

    disposal = client.post(
        f"/api/waste/{wid}/request-disposal",
        headers=headers,
        json={"reason": "Must not dispose a sellable partially sold record"},
    )

    assert disposal.status_code == 400
    assert disposal.json() == {"detail": "Cannot dispose sellable waste; sell it instead"}
    assert _snapshot(wid) == before


def test_sale_requires_idempotency_key_before_business_or_audit_writes(client):
    _, headers = _actor()
    wid = _fixture(quantity=5)
    before = _snapshot(wid)

    response = _sell(client, headers, wid, quantity=2, key="")

    assert response.status_code == 400
    assert response.json() == {"detail": "Idempotency-Key is required for waste sale"}
    assert _snapshot(wid) == before


def test_sale_missing_key_preserves_authentication_and_resource_precedence(client):
    _, permitted = _actor()
    _, restricted = _actor(())
    wid = _fixture()
    payload = {"buyer_name": "Synthetic buyer", "quantity": 1, "unit_price": 2.5}

    assert client.post(f"/api/waste/{wid}/sell", json=payload).status_code == 401
    assert client.post(f"/api/waste/{wid}/sell", headers=restricted, json=payload).status_code == 403
    missing = client.post("/api/waste/2000000000/sell", headers=permitted, json=payload)
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Waste record not found"}


def test_sale_audit_failure_rolls_back_sale_status_and_idempotency(client, monkeypatch):
    _, headers = _actor()
    wid = _fixture(quantity=5)
    before = _snapshot(wid)
    original = waste.log_action

    def fail_audit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic waste sale audit failure")

    monkeypatch.setattr(waste, "log_action", fail_audit)
    with pytest.raises(RuntimeError, match="Synthetic waste sale audit failure"):
        _sell(client, headers, wid, quantity=5, key=f"sale-failure-{uuid4().hex}")
    assert _snapshot(wid) == before


@pytest.fixture(scope="module")
def sale_postgres_engine():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL sale concurrency coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Sale concurrency tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"waste_sale_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {
            WasteRecord.__table__, WasteSale.__table__, WasteDisposalRequest.__table__,
            AuditLog.__table__, IdempotencyRecord.__table__,
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


@pytest.mark.parametrize(("shared_key", "expected_statuses"), [
    (None, [200, 400]),
    ("same-request-retry", [200, 200]),
])
def test_postgres_concurrent_sales_serialize_capacity_and_keyed_retry(
    sale_postgres_engine, shared_key, expected_statuses,
):
    sessions = sessionmaker(bind=sale_postgres_engine, autoflush=False, expire_on_commit=False)
    if shared_key:
        actor_id = _actor(session_factory=sessions)[0]
        actor_ids = [actor_id, actor_id]
    else:
        actor_ids = [_actor(session_factory=sessions)[0] for _ in range(2)]
    wid = _fixture(quantity=10, session_factory=sessions)
    before = _snapshot(wid, sessions)
    ready, start = Queue(), Event()

    def sell(actor_id):
        with sessions() as db:
            actor = db.get(User, actor_id)
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10), "Sale workers were not started"
            request_key = shared_key or f"waste-sale-concurrent-{actor_id}"
            try:
                result = waste.sell_waste(
                    wid,
                    waste.WasteSaleIn(buyer_name=f"Buyer {actor_id}", quantity=6, unit_price=2),
                    db,
                    actor,
                    request_key,
                )
                return 200, result["id"]
            except HTTPException as rejected:
                db.rollback()
                return rejected.status_code, rejected.detail

    with sale_postgres_engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(text("SELECT id FROM waste_records WHERE id = :id FOR NO KEY UPDATE"), {"id": wid})
        futures = [workers.submit(sell, actor_id) for actor_id in actor_ids]
        try:
            pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            deadline = monotonic() + 10
            while monotonic() < deadline:
                blocked = [
                    holder.execute(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid},
                    ).scalar_one()
                    for pid in pids
                ]
                if all(blocked):
                    break
                sleep(0.01)
            else:
                pytest.fail("Both sale transactions did not reach a demonstrable parent-lock wait")
        finally:
            start.set()
            holder.rollback()
        results = [future.result(timeout=20) for future in futures]

    assert sorted(result[0] for result in results) == expected_statuses, results
    if shared_key:
        assert results[0][1] == results[1][1]
    after = _snapshot(wid, sessions)
    assert len(after["sales"]) == 1
    assert sum(float(row["quantity"]) for row in after["sales"]) == 6
    assert after["record"]["status"] == "received_by_waste_department"
    assert len(after["audits"]) == len(before["audits"]) + 1
    assert after["idempotency_count"] == before["idempotency_count"] + 1


def test_postgres_sale_and_disposal_serialize_on_same_parent(sale_postgres_engine):
    sessions = sessionmaker(bind=sale_postgres_engine, autoflush=False, expire_on_commit=False)
    actor_ids = [
        _actor(("waste.sell", "waste.disposal"), session_factory=sessions)[0]
        for _ in range(2)
    ]
    wid = _fixture(quantity=10, session_factory=sessions)
    ready, start = Queue(), Event()

    def mutate(operation, actor_id):
        with sessions() as db:
            actor = db.get(User, actor_id)
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10), "Sale/disposal workers were not started"
            try:
                if operation == "sell":
                    waste.sell_waste(
                        wid,
                        waste.WasteSaleIn(buyer_name=f"Buyer {actor_id}", quantity=4, unit_price=2),
                        db,
                        actor,
                        f"waste-sale-disposal-race-{actor_id}",
                    )
                else:
                    waste.request_disposal(
                        wid,
                        waste.WasteDisposalIn(reason="Concurrent disposal must fail"),
                        db,
                        actor,
                    )
                return 200, operation
            except HTTPException as rejected:
                db.rollback()
                return rejected.status_code, operation

    with sale_postgres_engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(text("SELECT id FROM waste_records WHERE id = :id FOR NO KEY UPDATE"), {"id": wid})
        futures = [
            workers.submit(mutate, operation, actor_id)
            for operation, actor_id in zip(("sell", "dispose"), actor_ids)
        ]
        try:
            pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if all(
                    holder.execute(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid},
                    ).scalar_one()
                    for pid in pids
                ):
                    break
                sleep(0.01)
            else:
                pytest.fail("Sale and disposal did not reach a demonstrable parent-lock wait")
        finally:
            start.set()
            holder.rollback()
        results = [future.result(timeout=20) for future in futures]

    assert sorted(result[0] for result in results) == [200, 400], results
    assert next(result for result in results if result[0] == 200)[1] == "sell"
    after = _snapshot(wid, sessions)
    assert len(after["sales"]) == 1 and float(after["sales"][0]["quantity"]) == 4
    assert after["record"]["status"] == "received_by_waste_department"
    with sessions() as db:
        assert db.query(WasteDisposalRequest).filter_by(waste_record_id=wid).count() == 0


@pytest.mark.parametrize("first_operation", ["sell", "reconcile"])
def test_postgres_sale_reconciliation_serializes_without_replaying_physical_sale(
    sale_postgres_engine, first_operation,
):
    sessions = sessionmaker(bind=sale_postgres_engine, autoflush=False, expire_on_commit=False)
    actor_id = _actor(session_factory=sessions)[0]
    wid = _fixture(quantity=5, session_factory=sessions)
    before = _snapshot(wid, sessions)
    key = f"waste-sale-race-{uuid4().hex}"
    payload = waste.WasteSaleIn(buyer_name="Race buyer", quantity=2, unit_price=3)
    ready = Queue()

    def execute(operation):
        with sessions() as db:
            actor = db.get(User, actor_id)
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            try:
                if operation == "sell":
                    result = waste.sell_waste(wid, payload, db, actor, key)
                    return operation, 200, result["id"]
                result = waste.reconcile_waste_sale(wid, payload, db, actor, key)
                return operation, 200, result["status"]
            except HTTPException as rejected:
                db.rollback()
                return operation, rejected.status_code, rejected.detail

    second_operation = "reconcile" if first_operation == "sell" else "sell"
    with sale_postgres_engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.execute(text("SELECT id FROM waste_records WHERE id = :id FOR NO KEY UPDATE"), {"id": wid})
        first = workers.submit(execute, first_operation)
        first_pid = ready.get(timeout=10)
        deadline = monotonic() + 10
        while monotonic() < deadline:
            if holder.execute(
                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": first_pid},
            ).scalar_one():
                break
            sleep(0.01)
        else:
            pytest.fail("First waste sale operation did not reach the parent lock")

        second = workers.submit(execute, second_operation)
        second_pid = ready.get(timeout=10)
        deadline = monotonic() + 10
        while monotonic() < deadline:
            if holder.execute(
                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": second_pid},
            ).scalar_one():
                break
            sleep(0.01)
        else:
            pytest.fail("Second waste sale operation did not serialize on the request key")
        holder.rollback()
        results = {result[0]: result for result in (first.result(timeout=20), second.result(timeout=20))}

    snapshot = _snapshot(wid, sessions)
    if first_operation == "sell":
        assert results["sell"][1] == 200
        assert results["reconcile"][1:] == (200, "completed")
        assert len(snapshot["sales"]) == 1
        assert len(snapshot["audits"]) == 1
    else:
        assert results["reconcile"][1:] == (200, "cancelled")
        assert results["sell"][1] == 409
        assert snapshot["sales"] == []
        assert snapshot["audits"] == []
    assert snapshot["idempotency_count"] == before["idempotency_count"] + 1
