"""Eco send rollback and lock behavior on guarded PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.libs.dto.inventory.eco_fabric_transfer_input import SendIn
from app.models import audit_service
from app.models.inventory import transfers_service
from app.schemas import AuditLog, EcoFabricDispatch, EcoFabricRoll, Item, StockBatch, StockMovement, User, Warehouse
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def make_case(sessions):
    token = uuid4().hex
    with sessions.begin() as db:
        user = User(name="Eco send operator", email=f"{token}@example.invalid", password_hash="unused")
        item = Item(sku=token, name="Eco send fabric", category="fabric", unit="kg")
        warehouse = Warehouse(name=token, type="fabric_storage")
        db.add_all([user, item, warehouse])
        db.flush()
        batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no=token, quantity=15,
                           piece_count=1, roll_weights_kg=[15], unit="kg", cost_per_unit=0)
        db.add(batch)
        db.flush()
        return {"user": user.id, "batch": batch.id, "key": str(uuid4())}


def send(db, case):
    payload = SendIn(request_key=case["key"], codes=[f'B{case["batch"]}-R1'])
    return transfers_service.eco_send_fabric(db, payload, db.get(User, case["user"]))


def assert_saved(sessions, case, expected):
    with sessions() as db:
        batch = db.get(StockBatch, case["batch"])
        dispatch = db.query(EcoFabricDispatch).filter_by(request_key=case["key"]).one_or_none()
        rolls = db.query(EcoFabricRoll).filter_by(batch_id=case["batch"]).all()
        movements = db.query(StockMovement).filter_by(batch_id=case["batch"], reference_type="EcoFabricDispatch").all()
        if expected:
            assert dispatch is not None and batch.quantity == 0 and batch.archived_at and batch.archived_by == case["user"]
            assert len(rolls) == len(movements) == 1
            assert rolls[0].dispatch_id == dispatch.id and rolls[0].quantity == Decimal("15")
            assert movements[0].reference_id == dispatch.id and movements[0].movement_type == "issue"
            assert movements[0].quantity == Decimal("15") and rolls[0].returned_at is None
            audit = db.query(AuditLog).filter_by(entity_type="EcoFabricDispatch", entity_id=dispatch.id, action="send").one()
            assert audit.entry_hash and audit.user_id == case["user"]
        else:
            assert dispatch is None and not rolls and not movements
            assert batch.quantity == Decimal("15") and batch.archived_at is None and batch.archived_by is None
            assert db.query(AuditLog).filter_by(user_id=case["user"], entity_type="EcoFabricDispatch", action="send").count() == 0
        assert batch.roll_weights_kg == [15]


def test_pg_same_key_waits_for_batch_lock_then_replays(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    case = make_case(sessions)
    paused, release, waiter_started = Event(), Event(), Event()
    pids = {}
    original = transfers_service.log_action

    def pause_before_commit(db, *args, **kwargs):
        entry = original(db, *args, **kwargs)
        pids["holder"] = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
        paused.set()
        if not release.wait(timeout=8):
            raise TimeoutError("test did not release sender")
        return entry

    def first():
        with sessions() as db:
            return send(db, case)

    def second():
        with sessions() as db:
            pids["waiter"] = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            waiter_started.set()
            return send(db, case)

    monkeypatch.setattr(transfers_service, "log_action", pause_before_commit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(first)
        try:
            assert paused.wait(timeout=5)
            waiter = pool.submit(second)
            assert waiter_started.wait(timeout=5)
            deadline = monotonic() + 5
            blocked = False
            with sessions() as observer:
                while monotonic() < deadline:
                    blockers = observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pids["waiter"]}).scalar_one()
                    if pids["holder"] in blockers:
                        blocked = True
                        break
                    sleep(0.05)
            assert blocked, "retry never waited on the sending transaction"
        finally:
            release.set()
        assert holder.result(timeout=10) == waiter.result(timeout=10)
    assert_saved(sessions, case, True)
    chain(sessions)


def test_pg_finalized_audit_failure_rolls_back_then_retries(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    case = make_case(sessions)
    original = audit_service._finalize_postgres_audits

    def fail_after_finalization(db):
        original(db)
        db.flush()
        dispatch = db.query(EcoFabricDispatch).filter_by(request_key=case["key"]).one()
        assert db.query(EcoFabricRoll).filter_by(dispatch_id=dispatch.id).count() == 1
        assert db.query(StockMovement).filter_by(reference_type="EcoFabricDispatch", reference_id=dispatch.id).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="EcoFabricDispatch", entity_id=dispatch.id).one().entry_hash
        raise RuntimeError("injected send finalization failure")

    with monkeypatch.context() as patch:
        patch.setattr(audit_service, "_finalize_postgres_audits", fail_after_finalization)
        with sessions() as db, pytest.raises(RuntimeError, match="injected send finalization failure"):
            send(db, case)
    assert_saved(sessions, case, False)
    with sessions() as db:
        send(db, case)
    assert_saved(sessions, case, True)
    chain(sessions)


def test_pg_multibatch_late_refusal_rolls_back_first_line_and_retries(customer_pg_sessions, monkeypatch):
    from fastapi import HTTPException

    sessions = customer_pg_sessions
    first, second = make_case(sessions), make_case(sessions)
    assert first["batch"] < second["batch"]
    with sessions.begin() as db:
        db.get(StockBatch, second["batch"]).quantity = 10
    payload = SendIn(request_key=first["key"], codes=[f'B{second["batch"]}-R1', f'B{first["batch"]}-R1'])
    original_availability = transfers_service.line_availability
    witnessed = []

    def observe_second_line(db, batch_id, *args, **kwargs):
        if batch_id == second["batch"]:
            batch = db.get(StockBatch, first["batch"])
            dispatch = db.query(EcoFabricDispatch).filter_by(request_key=first["key"]).one()
            roll = db.query(EcoFabricRoll).filter_by(dispatch_id=dispatch.id, batch_id=first["batch"]).one()
            movement = db.query(StockMovement).filter_by(
                reference_type="EcoFabricDispatch", reference_id=dispatch.id, batch_id=first["batch"]
            ).one()
            assert batch.quantity == 0 and batch.archived_at and batch.archived_by == first["user"]
            assert roll.quantity == movement.quantity == Decimal("15") and movement.movement_type == "issue"
            witnessed.append(True)
        return original_availability(db, batch_id, *args, **kwargs)

    monkeypatch.setattr(transfers_service, "line_availability", observe_second_line)
    with sessions() as db, pytest.raises(HTTPException) as refusal:
        transfers_service.eco_send_fabric(db, payload, db.get(User, first["user"]))
    assert witnessed == [True]
    assert refusal.value.status_code == 409 and refusal.value.detail == "ecoTransfers.unavailable"
    monkeypatch.setattr(transfers_service, "line_availability", original_availability)
    assert_saved(sessions, first, False)
    with sessions.begin() as db:
        batch = db.get(StockBatch, second["batch"])
        assert batch.quantity == 10 and batch.archived_at is None and batch.archived_by is None and batch.roll_weights_kg == [15]
        assert db.query(EcoFabricRoll).filter_by(batch_id=second["batch"]).count() == 0
        assert db.query(StockMovement).filter_by(batch_id=second["batch"]).count() == 0
        batch.quantity = 15
    with sessions() as db:
        result = transfers_service.eco_send_fabric(db, payload, db.get(User, first["user"]))
    assert [row["code"] for row in result["rows"]] == sorted(payload.codes, key=lambda code: int(code.split('-')[0][1:]))
    with sessions() as db:
        dispatch = db.query(EcoFabricDispatch).filter_by(request_key=first["key"]).one()
        assert db.query(EcoFabricRoll).filter_by(dispatch_id=dispatch.id).count() == 2
        assert db.query(StockMovement).filter_by(reference_type="EcoFabricDispatch", reference_id=dispatch.id).count() == 2
        assert db.query(AuditLog).filter_by(entity_type="EcoFabricDispatch", entity_id=dispatch.id, action="send").count() == 1
        for case in (first, second):
            batch = db.get(StockBatch, case["batch"])
            assert batch.quantity == 0 and batch.archived_by == first["user"] and batch.archived_at
            assert batch.roll_weights_kg == [15]
    chain(sessions)


def test_pg_multibatch_sender_holds_first_lock_while_waiting_for_second(customer_pg_sessions):
    from sqlalchemy.exc import OperationalError

    sessions = customer_pg_sessions
    first, second = make_case(sessions), make_case(sessions)
    assert first["batch"] < second["batch"]
    started = Event()
    pids = {}
    payload = SendIn(request_key=first["key"], codes=[f'B{second["batch"]}-R1', f'B{first["batch"]}-R1'])

    def sender():
        with sessions() as db:
            pids["sender"] = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            started.set()
            return transfers_service.eco_send_fabric(db, payload, db.get(User, first["user"]))

    with sessions() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        blocker_pid = blocker.execute(text("SELECT pg_backend_pid()")).scalar_one()
        blocker.execute(text("SELECT id FROM stock_batches WHERE id = :id FOR UPDATE"), {"id": second["batch"]})
        future = pool.submit(sender)
        try:
            assert started.wait(timeout=5)
            deadline = monotonic() + 5
            with sessions() as observer:
                while monotonic() < deadline:
                    blocking = observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pids["sender"]}).scalar_one()
                    if blocker_pid in blocking:
                        break
                    sleep(0.05)
                else:
                    pytest.fail("sender did not wait on the second batch")
            with sessions() as observer, pytest.raises(OperationalError) as probe_error:
                observer.execute(text("SET LOCAL lock_timeout = '250ms'"))
                observer.execute(text("SELECT id FROM stock_batches WHERE id = :id FOR UPDATE"), {"id": first["batch"]})
            assert getattr(probe_error.value.orig, "pgcode", None) == "55P03"
        finally:
            blocker.rollback()
        result = future.result(timeout=10)
    assert result["sent_rolls"] == 2
    with sessions() as db:
        assert all(db.get(StockBatch, case["batch"]).quantity == 0 for case in (first, second))
        assert db.query(EcoFabricRoll).filter_by(dispatch_id=result["id"]).count() == 2
        assert db.query(StockMovement).filter_by(reference_type="EcoFabricDispatch", reference_id=result["id"]).count() == 2
    chain(sessions)


def test_pg_lock_timeout_rolls_back_and_same_key_retries(customer_pg_sessions):
    from sqlalchemy.exc import OperationalError

    sessions = customer_pg_sessions
    first, second = make_case(sessions), make_case(sessions)
    assert first["batch"] < second["batch"]
    payload = SendIn(request_key=first["key"], codes=[f'B{second["batch"]}-R1', f'B{first["batch"]}-R1'])
    with sessions() as blocker:
        blocker.execute(text("SELECT id FROM stock_batches WHERE id = :id FOR UPDATE"), {"id": second["batch"]})
        try:
            with sessions() as db:
                db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                with pytest.raises(OperationalError) as timeout:
                    transfers_service.eco_send_fabric(db, payload, db.get(User, first["user"]))
                assert getattr(timeout.value.orig, "pgcode", None) == "55P03"
                db.rollback()
            assert_saved(sessions, first, False)
            assert_saved(sessions, second, False)
        finally:
            blocker.rollback()
    with sessions() as db:
        result = transfers_service.eco_send_fabric(db, payload, db.get(User, first["user"]))
    assert result["sent_rolls"] == 2
    with sessions() as db:
        dispatch = db.query(EcoFabricDispatch).filter_by(request_key=first["key"]).one()
        for case in (first, second):
            batch = db.get(StockBatch, case["batch"])
            roll = db.query(EcoFabricRoll).filter_by(dispatch_id=dispatch.id, batch_id=batch.id).one()
            movement = db.query(StockMovement).filter_by(
                reference_type="EcoFabricDispatch", reference_id=dispatch.id, batch_id=batch.id
            ).one()
            assert batch.quantity == 0 and batch.archived_at and batch.archived_by == first["user"]
            assert roll.quantity == movement.quantity == Decimal("15") and movement.movement_type == "issue"
        assert db.query(AuditLog).filter_by(entity_type="EcoFabricDispatch", entity_id=dispatch.id, action="send").count() == 1
    chain(sessions)
