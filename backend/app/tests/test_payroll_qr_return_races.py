from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os

import pytest
from queue import Queue
from threading import Barrier, BrokenBarrierError, Event, Lock
from time import monotonic, sleep
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.schemas.payroll import PayrollRecordIn

from app.api.routes import payroll
from app.models import Employee, PayrollPeriod, PayrollQrLabel, PayrollRecord, User
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_employee, _create_user_with_permissions, _record_payload
@pytest.fixture(scope="module")
def payroll_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL payroll race coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Payroll race tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"payroll_return_races_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=5,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _seed(session_factory, *, period_count=1, label_count=1):
    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    suffix = uuid4().hex
    with session_factory() as db:
        user = User(
            name="Payroll race manager",
            email=f"payroll-race-{suffix}@example.com",
            password_hash="synthetic",
            factory_code="MIL",
            extra_permissions=["payroll.manage", "payroll.approve"],
        )
        employee = Employee(
            factory_code="MIL",
            employee_no=f"RACE-{suffix[:10]}",
            full_name="Payroll race employee",
            status="active",
        )
        db.add_all([user, employee])
        db.flush()
        periods = [
            PayrollPeriod(
                factory_code="MIL",
                period_no=f"RACE-{suffix}-{index}",
                name=f"Race period {index}",
                start_date=now - timedelta(days=1),
                end_date=now + timedelta(days=1),
                status="open",
                created_by=user.id,
            )
            for index in range(period_count)
        ]
        labels = [
            PayrollQrLabel(
                factory_code="MIL",
                label_uid=f"RACE-LABEL-{suffix}-{index}",
                operation_section="sewing",
                operation_code=f"RACE-{index}",
                operation_name=f"Race operation {index}",
                quantity=10,
                rate_per_piece=250,
                currency="UZS",
                status="available",
                issued_by=user.id,
            )
            for index in range(label_count)
        ]
        db.add_all([*periods, *labels])
        db.commit()
        return user.id, employee.id, [row.id for row in periods], [row.label_uid for row in labels]


def _record(employee_id, period_id: int | None, label_uid):
    return PayrollRecordIn(
        payroll_period_id=period_id,
        scan_uid=label_uid,
        employee_id=employee_id,
        quantity=1,
        rate_per_piece=1,
    )




def _seed_scanned_label(session_factory):
    user_id, employee_id, period_ids, label_uids = _seed(session_factory)
    period_id = period_ids[0]
    label_uid = label_uids[0]
    with session_factory() as db:
        current = db.get(User, user_id)
        record, created = payroll._create_record_from_payload(
            db,
            _record(employee_id, period_id, label_uid),
            current=current,
        )
        assert created is True
        db.commit()
        label_id = db.query(PayrollQrLabel.id).filter_by(label_uid=label_uid).scalar()
        return user_id, employee_id, period_id, int(label_id), int(record.id), label_uid


def _return_label(session_factory, user_id, label_id, pids=None):
    with session_factory() as db:
        if pids is not None:
            pids.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
        current = db.get(User, user_id)
        try:
            return payroll.return_qr_label(label_id, db, current)
        except Exception as exc:
            db.rollback()
            return exc


def _wait_for_blocker(observer, waiter_pid, blocker_pid, message):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        blockers = observer.execute(
            text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter_pid},
        ).scalar_one()
        if blocker_pid in blockers:
            return
        sleep(0.02)
    raise AssertionError(message)


def test_paid_qr_return_keeps_manager_denial_and_admin_override(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    manager = _create_user_with_permissions(
        client,
        auth_headers,
        email=f"qr-return-manager-{uuid4().hex}@example.com",
        permissions=["payroll.manage"],
    )
    label_uid = f"PY05:{uuid4().hex}"
    created = client.post(
        "/api/payroll/records",
        headers=manager,
        json=_record_payload(employee["id"], scan_uid=label_uid),
    )
    assert created.status_code == 201, created.text

    with TestSessionLocal() as db:
        record = db.get(PayrollRecord, created.json()["id"])
        record.status = "paid"
        label_id = db.query(PayrollQrLabel.id).filter_by(label_uid=label_uid).scalar()
        db.commit()

    denied = client.post(f"/api/payroll/qr-labels/{label_id}/return", headers=manager)
    assert denied.status_code == 409, denied.text
    with TestSessionLocal() as db:
        label = db.get(PayrollQrLabel, label_id)
        record = db.get(PayrollRecord, created.json()["id"])
        assert label.status == "scanned" and label.return_count == 0
        assert record.status == "paid" and record.scan_uid == label_uid

    overridden = client.post(f"/api/payroll/qr-labels/{label_id}/return", headers=auth_headers)
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["status"] == "available"
    assert overridden.json()["return_count"] == 1


def test_unassigned_qr_return_remains_a_conflict(client, auth_headers):
    label_uid = f"PY05:{uuid4().hex}"
    issued = client.post(
        "/api/payroll/qr-labels/issue",
        headers=auth_headers,
        json={"labels": [{
            "label_uid": label_uid,
            "operation_section": "sewing",
            "operation_code": "PY05",
            "operation_name": "Return compatibility",
            "quantity": 1,
            "rate_per_piece": 1,
        }]},
    )
    assert issued.status_code == 200, issued.text
    with TestSessionLocal() as db:
        label_id = db.query(PayrollQrLabel.id).filter_by(label_uid=label_uid).scalar()

    returned = client.post(f"/api/payroll/qr-labels/{label_id}/return", headers=auth_headers)

    assert returned.status_code == 409, returned.text
    with TestSessionLocal() as db:
        label = db.get(PayrollQrLabel, label_id)
        assert label.status == "available"
        assert label.payroll_record_id is None
        assert label.return_count == 0


def test_postgres_return_and_period_first_writer_do_not_deadlock(payroll_postgres_sessions):
    sessions, _engine = payroll_postgres_sessions
    user_id, _employee_id, period_id, label_id, record_id, _uid = _seed_scanned_label(sessions)
    pids = Queue()
    with sessions() as writer, ThreadPoolExecutor(max_workers=1) as workers:
        writer_pid = writer.execute(text("SELECT pg_backend_pid()")).scalar_one()
        # Competing writer follows PY02's period -> label -> record order.
        writer.execute(text("SELECT id FROM payroll_periods WHERE id=:id FOR UPDATE"), {"id": period_id})
        returned = workers.submit(_return_label, sessions, user_id, label_id, pids)
        return_pid = pids.get(timeout=10)
        try:
            _wait_for_blocker(writer, return_pid, writer_pid, "Return did not wait on the competing period writer")
            # With the old return order, these two real transactions deadlock:
            # return holds label/record waiting on period; writer needs label.
            writer.execute(text("SELECT id FROM payroll_qr_labels WHERE id=:id FOR UPDATE"), {"id": label_id})
            writer.execute(text("SELECT id FROM payroll_records WHERE id=:id FOR UPDATE"), {"id": record_id})
        finally:
            writer.rollback()
        result = returned.result(timeout=15)
    assert not isinstance(result, Exception), result
    with sessions() as db:
        assert db.get(PayrollQrLabel, label_id).return_count == 1
        assert db.get(PayrollRecord, record_id).status == "voided"


def test_postgres_concurrent_qr_returns_mutate_once(payroll_postgres_sessions):
    sessions, engine = payroll_postgres_sessions
    user_id, _employee_id, _period_id, label_id, record_id, _label_uid = _seed_scanned_label(sessions)
    first_label_reads = Barrier(2)
    aligned_connections = set()
    aligned_lock = Lock()

    def align_initial_label_reads(connection, _cursor, statement, _parameters, _context, _many):
        normalized = " ".join(statement.lower().split())
        if "from payroll_qr_labels" not in normalized or "for update" in normalized:
            return
        with aligned_lock:
            identity = id(connection)
            if identity in aligned_connections:
                return
            aligned_connections.add(identity)
        try:
            first_label_reads.wait(timeout=5)
        except BrokenBarrierError:
            pass

    event.listen(engine, "before_cursor_execute", align_initial_label_reads)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = [
                future.result(timeout=15)
                for future in (
                    workers.submit(_return_label, sessions, user_id, label_id),
                    workers.submit(_return_label, sessions, user_id, label_id),
                )
            ]
    finally:
        event.remove(engine, "before_cursor_execute", align_initial_label_reads)

    successes = [result for result in results if isinstance(result, dict)]
    conflicts = [result for result in results if isinstance(result, HTTPException)]
    assert len(successes) == 1, results
    assert len(conflicts) == 1 and conflicts[0].status_code == 409, results
    with sessions() as db:
        label = db.get(PayrollQrLabel, label_id)
        record = db.get(PayrollRecord, record_id)
        assert label.status == "available"
        assert label.payroll_record_id is None
        assert label.return_count == 1
        assert record.status == "voided"
        assert record.scan_uid is None


def test_postgres_qr_return_blocks_period_finalization(payroll_postgres_sessions, monkeypatch):
    sessions, _engine = payroll_postgres_sessions
    user_id, _employee_id, period_id, label_id, record_id, _label_uid = _seed_scanned_label(sessions)
    return_holds_locks = Event()
    release_return = Event()
    pids = Queue()
    original_log_action = payroll.log_action

    def pause_return_audit(db, current, action, *args, **kwargs):
        result = original_log_action(db, current, action, *args, **kwargs)
        if action == "return_qr":
            return_holds_locks.set()
            assert release_return.wait(10), "QR return was not released"
        return result

    monkeypatch.setattr(payroll, "log_action", pause_return_audit)

    def finalize_period():
        with sessions() as db:
            pids.put(("finalizer", db.execute(text("SELECT pg_backend_pid()")).scalar_one()))
            current = db.get(User, user_id)
            try:
                return payroll.lock_period(period_id, db, current)
            except Exception as exc:
                db.rollback()
                return exc

    with ThreadPoolExecutor(max_workers=2) as workers:
        returned = workers.submit(_return_label, sessions, user_id, label_id, pids)
        try:
            assert return_holds_locks.wait(10), "QR return did not reach its locked audit write"
            finalized = workers.submit(finalize_period)
            return_pid = pids.get(timeout=10)
            finalizer_name, finalizer_pid = pids.get(timeout=10)
            assert finalizer_name == "finalizer"
            with sessions() as observer:
                _wait_for_blocker(
                    observer,
                    finalizer_pid,
                    return_pid,
                    "Period finalization was not blocked by the in-flight QR return",
                )
        finally:
            release_return.set()
        return_result = returned.result(timeout=10)
        finalizer_result = finalized.result(timeout=10)

    assert not isinstance(return_result, Exception), return_result
    assert not isinstance(finalizer_result, Exception), finalizer_result
    with sessions() as db:
        assert db.get(PayrollPeriod, period_id).status == "locked"
        assert db.get(PayrollQrLabel, label_id).status == "available"
        assert db.get(PayrollRecord, record_id).status == "voided"


def test_postgres_finalized_period_rejects_waiting_qr_return_without_mutation(payroll_postgres_sessions):
    sessions, _engine = payroll_postgres_sessions
    user_id, _employee_id, period_id, label_id, record_id, label_uid = _seed_scanned_label(sessions)
    pids = Queue()

    with sessions() as finalizer, ThreadPoolExecutor(max_workers=1) as workers:
        finalizer_pid = finalizer.execute(text("SELECT pg_backend_pid()")).scalar_one()
        period = (
            finalizer.query(PayrollPeriod)
            .filter(PayrollPeriod.id == period_id)
            .with_for_update()
            .one()
        )
        period.status = "locked"
        finalizer.flush()
        returned = workers.submit(_return_label, sessions, user_id, label_id, pids)
        return_pid = pids.get(timeout=10)
        try:
            _wait_for_blocker(
                finalizer,
                return_pid,
                finalizer_pid,
                "QR return did not wait for the period finalizer",
            )
        finally:
            finalizer.commit()
        result = returned.result(timeout=10)

    assert isinstance(result, HTTPException)
    assert result.status_code == 409
    with sessions() as db:
        label = db.get(PayrollQrLabel, label_id)
        record = db.get(PayrollRecord, record_id)
        assert label.status == "scanned"
        assert label.payroll_record_id == record_id
        assert label.return_count == 0
        assert record.status == "recorded"
        assert record.scan_uid == label_uid


def test_postgres_new_assignment_during_periodless_return_requires_retry(payroll_postgres_sessions):
    sessions, _engine = payroll_postgres_sessions
    user_id, employee_id, period_ids, label_uids = _seed(sessions)
    period_id = period_ids[0]
    label_uid = label_uids[0]
    pids = Queue()

    with sessions() as scanner, ThreadPoolExecutor(max_workers=1) as workers:
        scanner_pid = scanner.execute(text("SELECT pg_backend_pid()")).scalar_one()
        scanner.query(PayrollPeriod).filter(PayrollPeriod.id == period_id).with_for_update().one()
        label = (
            scanner.query(PayrollQrLabel)
            .filter(PayrollQrLabel.label_uid == label_uid)
            .with_for_update()
            .one()
        )
        returned = workers.submit(_return_label, sessions, user_id, label.id, pids)
        return_pid = pids.get(timeout=10)
        try:
            _wait_for_blocker(
                scanner,
                return_pid,
                scanner_pid,
                "Periodless QR return did not wait for the label assignment",
            )
            current = scanner.get(User, user_id)
            record, created = payroll._create_record_from_payload(
                scanner,
                _record(employee_id, period_id, label_uid),
                current=current,
            )
            assert created is True
            scanner.commit()
        except Exception:
            scanner.rollback()
            raise
        result = returned.result(timeout=10)

    assert isinstance(result, HTTPException)
    assert result.status_code == 409
    with sessions() as db:
        label = db.query(PayrollQrLabel).filter_by(label_uid=label_uid).one()
        record = db.get(PayrollRecord, record.id)
        assert label.status == "scanned"
        assert label.payroll_record_id == record.id
        assert label.return_count == 0
        assert record.status == "recorded"
        assert record.scan_uid == label_uid
