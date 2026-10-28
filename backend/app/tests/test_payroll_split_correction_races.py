"""Real PostgreSQL contention for saved split edits, isolated from business data."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import payroll
from app.db.base import Base
from app.schemas.payroll import (
    PayrollPeriodIn, PayrollPeriodUpdate, PayrollRecordIn, PayrollScanSplitIn,
)
from app.libs.dto.people.payroll_split_correction import SplitAllocationUpdate
from app.services import payroll_split_correction as correction
from app.schemas import AuditLog, Employee, PayrollPeriod, PayrollQrLabel, PayrollRecord, User


STAMP = datetime(2002, 1, 5, tzinfo=timezone.utc)


@pytest.fixture
def split_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL split correction races")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Split correction races require loopback PostgreSQL without connection overrides")
    schema = f"payroll_split_races_{uuid4().hex}"
    engine = create_engine(
        url, pool_size=4, max_overflow=0, isolation_level="READ COMMITTED",
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _seed(sessions, *, assigned=True):
    suffix = uuid4().hex
    with sessions() as db:
        actor = User(name="Split race manager", email=f"split-{suffix}@example.com",
                     password_hash="synthetic", factory_code="MIL",
                     extra_permissions=["payroll.manage", "payroll.approve"])
        employees = [Employee(factory_code="MIL", employee_no=f"S-{suffix[:8]}-{i}",
                              full_name=f"Split race employee {i}", status="active") for i in range(3)]
        db.add_all([actor, *employees])
        db.flush()
        period = PayrollPeriod(factory_code="MIL", period_no=f"P-{suffix}", name="Split race period",
                               start_date=STAMP - timedelta(days=1), end_date=STAMP + timedelta(days=1),
                               status="open", created_by=actor.id) if assigned else None
        label = PayrollQrLabel(factory_code="MIL", label_uid=f"SPLIT-RACE-{suffix}",
                               operation_section="sewing", operation_code="SEW", operation_name="Sew",
                               quantity=20, rate_per_piece=Decimal("250"), currency="UZS",
                               status="available", issued_by=actor.id)
        db.add(label)
        if period:
            db.add(period)
        db.flush()
        record, created = payroll._create_record_from_payload(db, PayrollRecordIn(
            payroll_period_id=period.id if period else None, scan_uid=label.label_uid,
            employee_id=employees[0].id, scanned_at=STAMP, quantity=1, rate_per_piece=1,
        ), current=actor, preserve_unassigned_period=True)
        assert created
        db.commit()
        records = payroll.split_scanned_record(record.id, PayrollScanSplitIn(parts=[
            {"employee_id": employees[0].id, "quantity": 7},
            {"employee_id": employees[1].id, "quantity": 13},
        ]), db, actor)
        child = db.query(PayrollQrLabel).filter_by(split_from_label_id=label.id).order_by(PayrollQrLabel.id).first()
        view = correction.read_split_allocation(db, actor=actor, label_id=child.id)
        payload = SplitAllocationUpdate(revision=view.revision, reason="Correct split allocation",
                                        parts=[{key: getattr(part, key) for key in (
                                            "label_id", "employee_id", "quantity", "operation_name", "rate_per_piece",
                                        )} for part in view.parts])
        payload.parts[0].quantity = 8
        payload.parts[1].quantity = 12
        payload.parts[0].employee_id = employees[2].id
        payload.parts[0].operation_name = "Corrected sew"
        return dict(user_id=actor.id, parent_id=label.id, label_id=child.id,
                    original_id=record.id, record_id=records[0]["id"], employee_id=employees[0].id,
                    period_id=period.id if period else None, payload=payload)


def _run(sessions, seed, operation, pids=None):
    with sessions() as db:
        if pids is not None:
            pids.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
        try:
            return operation(db, db.get(User, seed["user_id"]))
        except Exception as exc:
            db.rollback()
            return exc


def _correct(seed, payload=None):
    return lambda db, actor: correction.correct_split_allocation(
        db, actor=actor, label_id=seed["label_id"], payload=payload or seed["payload"],
    )


def _pause(monkeypatch, module, action):
    ready, release = Event(), Event()
    original = module.log_action

    def paused(db, actor, current_action, *args, **kwargs):
        result = original(db, actor, current_action, *args, **kwargs)
        if current_action == action:
            ready.set()
            assert release.wait(10), "Contending payroll operation was not released"
        return result

    monkeypatch.setattr(module, "log_action", paused)
    return ready, release


def _race(sessions, seed, first, second, ready, release):
    """Prove actual database blocking before releasing the first writer."""
    first_pids, second_pids = Queue(), Queue()
    with ThreadPoolExecutor(max_workers=2) as workers:
        winner = workers.submit(_run, sessions, seed, first, first_pids)
        contender = None
        try:
            assert ready.wait(10), "First operation did not reach its locked audit write"
            first_pid = first_pids.get(timeout=10)
            contender = workers.submit(_run, sessions, seed, second, second_pids)
            second_pid = second_pids.get(timeout=10)
            with sessions() as observer:
                deadline = monotonic() + 8
                while monotonic() < deadline:
                    blockers = observer.execute(text("SELECT pg_blocking_pids(:pid)"),
                                                {"pid": second_pid}).scalar_one()
                    if first_pid in blockers:
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Second payroll operation did not block on the real PostgreSQL writer")
        finally:
            release.set()
        return winner.result(timeout=15), contender.result(timeout=15)


def _snapshot(sessions):
    with sessions() as db:
        return ([tuple(getattr(row, field) for field in (
            "id", "label_uid", "status", "quantity", "rate_per_piece", "operation_name", "payroll_record_id", "return_count",
        )) for row in db.query(PayrollQrLabel).order_by(PayrollQrLabel.id)],
                [tuple(getattr(row, field) for field in (
                    "id", "status", "employee_id", "quantity", "rate_per_piece", "total_amount", "operation_name",
                    "scan_uid", "scanned_at", "payroll_period_id", "raw_work_json", "raw_employee_json",
                )) for row in db.query(PayrollRecord).order_by(PayrollRecord.id)],
                db.query(AuditLog).count())


def _assert_conserved(sessions, seed, *, labels=3, records=3, amount=Decimal("5000"), quantity=20):
    with sessions() as db:
        assert db.query(PayrollQrLabel).count() == labels
        assert db.query(PayrollRecord).count() == records
        original = db.get(PayrollRecord, seed["original_id"])
        assert original.status == "voided"
        assert original.quantity == 20 and original.total_amount == Decimal("5000")
        assert db.get(PayrollQrLabel, seed["parent_id"]).status == "superseded"
        active = db.query(PayrollRecord).filter_by(status="recorded").all()
        assert sum(row.total_amount for row in active) == amount
        assert all(row.scanned_at == STAMP for row in db.query(PayrollRecord))
        assert all(row.payroll_period_id == seed["period_id"] for row in db.query(PayrollRecord))
        for row in active:
            label = db.query(PayrollQrLabel).filter_by(payroll_record_id=row.id).one()
            assert row.scan_uid == label.label_uid
            assert row.quantity == label.quantity and row.rate_per_piece == label.rate_per_piece
        assert sum(row.quantity for row in active) == quantity


@pytest.mark.parametrize("retry", [False, True])
def test_postgres_corrections_serialize_stale_conflict_or_identical_retry(split_postgres_sessions, monkeypatch, retry):
    sessions = split_postgres_sessions
    seed = _seed(sessions)
    other = seed["payload"].model_copy(deep=True)
    if not retry:
        other.parts[0].operation_name = "Stale second edit"
    ready, release = _pause(monkeypatch, correction, "correct_split_allocation")
    first, second = _race(sessions, seed, _correct(seed), _correct(seed, other), ready, release)
    assert not isinstance(first, Exception), first
    if retry:
        assert second == first
    else:
        assert isinstance(second, HTTPException) and second.status_code == 409, second
    _assert_conserved(sessions, seed)
    with sessions() as db:
        assert db.query(AuditLog).filter_by(action="correct_split_allocation").count() == 1
        assert db.get(PayrollRecord, seed["record_id"]).operation_name == "Corrected sew"


@pytest.mark.parametrize("operation", ["return", "split"])
@pytest.mark.parametrize("correction_first", [False, True])
def test_postgres_correction_and_return_or_nested_split_serialize(split_postgres_sessions, monkeypatch, operation, correction_first):
    sessions = split_postgres_sessions
    seed = _seed(sessions)
    if operation == "return":
        other = lambda db, actor: payroll.return_qr_label(seed["label_id"], db, actor)
        action = "return_qr"
    else:
        other = lambda db, actor: payroll.split_scanned_record(seed["record_id"], PayrollScanSplitIn(parts=[
            {"employee_id": seed["employee_id"], "quantity": 3},
            {"employee_id": seed["employee_id"], "quantity": 4},
        ]), db, actor)
        action = "split_scanned_qr"
    ready, release = _pause(monkeypatch, correction if correction_first else payroll,
                            "correct_split_allocation" if correction_first else action)
    first, second = _race(sessions, seed, _correct(seed) if correction_first else other,
                          other if correction_first else _correct(seed), ready, release)
    assert not isinstance(first, Exception), first
    if correction_first and operation == "return":
        assert not isinstance(second, Exception), second
        _assert_conserved(sessions, seed, amount=Decimal("3000"), quantity=12)
    else:
        assert isinstance(second, HTTPException) and second.status_code == 409, second
        if operation == "split" and not correction_first:
            _assert_conserved(sessions, seed, labels=5, records=5)
        elif operation == "return":
            _assert_conserved(sessions, seed, amount=Decimal("3250"), quantity=13)
        else:
            _assert_conserved(sessions, seed)
    with sessions() as db:
        assert db.query(AuditLog).filter_by(action="correct_split_allocation").count() == int(correction_first)
        assert db.get(PayrollQrLabel, seed["label_id"]).return_count == int(operation == "return")


@pytest.mark.parametrize("operation", ["create", "expand", "lock"])
@pytest.mark.parametrize("correction_first", [False, True])
def test_postgres_correction_and_period_schedule_or_lock_serialize(split_postgres_sessions, monkeypatch, operation, correction_first):
    sessions = split_postgres_sessions
    seed = _seed(sessions, assigned=operation == "lock")
    if operation == "create":
        other = lambda db, actor: payroll.create_period(PayrollPeriodIn(
            name="New date period", start_date=STAMP - timedelta(days=1),
            end_date=STAMP + timedelta(days=1), status="draft",
        ), db, actor)
        action = "create"
    elif operation == "expand":
        with sessions.begin() as db:
            period = PayrollPeriod(factory_code="MIL", period_no="EXPAND", name="Expand date range", status="draft",
                                   start_date=STAMP + timedelta(days=10), end_date=STAMP + timedelta(days=20))
            db.add(period)
            db.flush()
            period_id = period.id
        other = lambda db, actor: payroll.update_period(period_id, PayrollPeriodUpdate(
            start_date=STAMP - timedelta(days=1),
        ), db, actor)
        action = "update"
    else:
        other = lambda db, actor: payroll.lock_period(seed["period_id"], db, actor)
        action = "lock"
    before = _snapshot(sessions)
    ready, release = _pause(monkeypatch, correction if correction_first else payroll,
                            "correct_split_allocation" if correction_first else action)
    first, second = _race(sessions, seed, _correct(seed) if correction_first else other,
                          other if correction_first else _correct(seed), ready, release)
    assert not isinstance(first, Exception), first
    if correction_first:
        assert not isinstance(second, Exception), second
        with sessions() as db:
            assert db.get(PayrollRecord, seed["record_id"]).quantity == 8
    else:
        assert isinstance(second, HTTPException) and second.status_code == 409, second
        after = _snapshot(sessions)
        assert after[:2] == before[:2]
    _assert_conserved(sessions, seed)
    with sessions() as db:
        assert db.query(AuditLog).filter_by(action="correct_split_allocation").count() == int(correction_first)


def test_postgres_failed_correction_rolls_back_and_releases_locks_for_retry(split_postgres_sessions, monkeypatch):
    sessions = split_postgres_sessions
    seed = _seed(sessions)
    before = _snapshot(sessions)
    apply = correction.apply_split_part_correction
    calls = []

    def fail_second(*args, **kwargs):
        apply(*args, **kwargs)
        calls.append(kwargs["label"].id)
        if len(calls) == 2:
            raise RuntimeError("Injected PostgreSQL correction failure")

    monkeypatch.setattr(correction, "apply_split_part_correction", fail_second)
    result = _run(sessions, seed, _correct(seed))
    assert isinstance(result, RuntimeError), result
    assert len(calls) == 2
    assert _snapshot(sessions) == before
    monkeypatch.setattr(correction, "apply_split_part_correction", apply)
    with ThreadPoolExecutor(max_workers=1) as workers:
        result = workers.submit(_run, sessions, seed, _correct(seed)).result(timeout=10)
    assert not isinstance(result, Exception), result
    _assert_conserved(sessions, seed)
    with sessions() as db:
        audits = db.query(AuditLog).filter_by(action="correct_split_allocation").all()
        assert len(audits) == 1
        assert audits[0].entry_hash
        assert audits[0].old_value_json["parts"][0]["quantity"] == 7
        assert audits[0].new_value_json["parts"][0]["quantity"] == 8
