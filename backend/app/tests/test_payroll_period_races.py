from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from queue import Queue
from threading import Barrier, BrokenBarrierError, Event, Lock
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import payroll
from app.db.base import Base
from app.models import Employee, PayrollAdjustment, PayrollPeriod, PayrollQrLabel, PayrollRecord, User
from app.schemas.payroll import (
    PayrollAdjustmentIn,
    PayrollControlConfirmIn,
    PayrollControlScanIn,
    PayrollRecordBulkIn,
    PayrollRecordIn,
)
from app.tests.test_payroll import _create_employee, _create_period, _record_payload


@pytest.fixture(scope="module")
def payroll_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL payroll race coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Payroll race tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"payroll_period_races_{uuid4().hex}"
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
        scanned_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        quantity=1,
        rate_per_piece=1,
    )


def test_duplicate_record_replay_survives_period_finalization(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    period = _create_period(client, auth_headers)
    payload = _record_payload(employee["id"], scan_uid=f"period-replay-{uuid4().hex}")
    payload["payroll_period_id"] = period["id"]

    created = client.post("/api/payroll/records", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text
    locked = client.post(f"/api/payroll/periods/{period['id']}/lock", headers=auth_headers)
    assert locked.status_code == 200, locked.text

    replay = client.post("/api/payroll/records", json=payload, headers=auth_headers)
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == created.json()["id"]
    assert replay.json()["duplicate"] is True


def test_postgres_record_writer_serializes_before_period_lock(payroll_postgres_sessions, monkeypatch):
    sessions, _engine = payroll_postgres_sessions
    user_id, employee_id, period_ids, label_uids = _seed(sessions)
    period_id = period_ids[0]
    writer_ready = Event()
    release_writer = Event()
    pids = Queue()
    original_assert = payroll._assert_period_accepts_records

    def pause_after_status_check(period, current):
        original_assert(period, current)
        writer_ready.set()
        assert release_writer.wait(10), "Writer was not released"

    monkeypatch.setattr(payroll, "_assert_period_accepts_records", pause_after_status_check)

    def write_record():
        with sessions() as db:
            pids.put(("writer", db.execute(text("SELECT pg_backend_pid()")).scalar_one()))
            current = db.get(User, user_id)
            try:
                record, created = payroll._create_record_from_payload(
                    db,
                    _record(employee_id, period_id, label_uids[0]),
                    current=current,
                )
                db.commit()
                return record.id, created
            except Exception as exc:
                db.rollback()
                return exc

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
        writer = workers.submit(write_record)
        assert writer_ready.wait(10), "Writer did not reach the post-status pause"
        finalizer = workers.submit(finalize_period)
        process_ids = dict(pids.get(timeout=10) for _ in range(2))
        with sessions() as observer:
            deadline = monotonic() + 10
            while monotonic() < deadline:
                blockers = observer.execute(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": process_ids["finalizer"]},
                ).scalar_one()
                if process_ids["writer"] in blockers:
                    break
                sleep(0.02)
            else:
                pytest.fail("Period finalization overtook a writer that had accepted the open period")
        release_writer.set()
        write_result = writer.result(timeout=10)
        final_result = finalizer.result(timeout=10)

    assert not isinstance(write_result, Exception), write_result
    assert not isinstance(final_result, Exception), final_result
    with sessions() as db:
        assert db.get(PayrollPeriod, period_id).status == "locked"
        assert db.query(PayrollRecord).filter_by(payroll_period_id=period_id).count() == 1


def test_postgres_automatic_writer_rejects_finalized_candidate_without_orphan(payroll_postgres_sessions):
    sessions, _engine = payroll_postgres_sessions
    _manager_id, employee_id, period_ids, label_uids = _seed(sessions)
    period_id = period_ids[0]
    with sessions() as db:
        scanner = User(
            name="Payroll race scanner",
            email=f"payroll-race-scanner-{uuid4().hex}@example.com",
            password_hash="synthetic",
            factory_code="MIL",
            extra_permissions=["payroll.scan"],
        )
        db.add(scanner)
        db.commit()
        scanner_id = int(scanner.id)

    ready = Queue()

    def automatic_write():
        with sessions() as db:
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            current = db.get(User, scanner_id)
            try:
                record, created = payroll._create_record_from_payload(
                    db,
                    _record(employee_id, None, label_uids[0]),
                    current=current,
                )
                db.commit()
                return record.id, created
            except Exception as exc:
                db.rollback()
                return exc

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
        future = workers.submit(automatic_write)
        writer_pid = ready.get(timeout=10)
        deadline = monotonic() + 10
        while monotonic() < deadline:
            blockers = finalizer.execute(
                text("SELECT pg_blocking_pids(:pid)"), {"pid": writer_pid},
            ).scalar_one()
            if finalizer_pid in blockers:
                break
            sleep(0.02)
        else:
            pytest.fail("Automatic writer did not wait on its discovered payroll period")
        finalizer.commit()
        result = future.result(timeout=10)

    assert isinstance(result, HTTPException)
    assert result.status_code == 409
    with sessions() as db:
        assert db.query(PayrollRecord).filter_by(scan_uid=label_uids[0]).count() == 0
        assert db.query(PayrollRecord).filter(PayrollRecord.payroll_period_id.is_(None)).count() == 0
        label = db.query(PayrollQrLabel).filter_by(label_uid=label_uids[0]).one()
        assert label.status == "available" and label.payroll_record_id is None


def test_postgres_reversed_multi_period_bulks_do_not_deadlock(payroll_postgres_sessions):
    sessions, engine = payroll_postgres_sessions
    user_id, employee_id, period_ids, label_uids = _seed(sessions, period_count=2, label_count=2)
    payloads = [
        PayrollRecordBulkIn(records=[
            _record(employee_id, period_ids[0], label_uids[0]),
            _record(employee_id, period_ids[1], label_uids[1]),
        ]),
        PayrollRecordBulkIn(records=[
            _record(employee_id, period_ids[1], label_uids[1]),
            _record(employee_id, period_ids[0], label_uids[0]),
        ]),
    ]
    first_label_barrier = Barrier(2)
    seen_connections = set()
    seen_lock = Lock()

    def align_first_label_lock(connection, _cursor, statement, _parameters, _context, _many):
        normalized = " ".join(statement.lower().split())
        if "from payroll_qr_labels" not in normalized or "for update" not in normalized:
            return
        with seen_lock:
            if id(connection) in seen_connections:
                return
            seen_connections.add(id(connection))
        try:
            first_label_barrier.wait(timeout=5)
        except BrokenBarrierError:
            pass

    def submit(payload):
        with sessions() as db:
            current = db.get(User, user_id)
            try:
                return payroll.create_records_bulk(payload, db, current)
            except Exception as exc:
                db.rollback()
                return exc

    event.listen(engine, "before_cursor_execute", align_first_label_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(submit, payloads))
    finally:
        event.remove(engine, "before_cursor_execute", align_first_label_lock)

    assert not [result for result in results if isinstance(result, Exception)], results
    assert sorted((result["created_count"], result["duplicate_count"]) for result in results) == [(0, 2), (2, 0)]
    for payload, result in zip(payloads, results):
        assert [row["scan_uid"] for row in result["records"]] == [row.scan_uid for row in payload.records]
    with sessions() as db:
        assert db.query(PayrollRecord).filter(PayrollRecord.scan_uid.in_(label_uids)).count() == 2


def test_postgres_adjustment_writer_serializes_before_period_lock(payroll_postgres_sessions, monkeypatch):
    sessions, _engine = payroll_postgres_sessions
    user_id, employee_id, period_ids, _label_uids = _seed(sessions)
    period_id = period_ids[0]
    writer_ready = Event()
    release_writer = Event()
    pids = Queue()
    original_assert = payroll._assert_period_accepts_adjustments

    def pause_after_status_check(period):
        original_assert(period)
        writer_ready.set()
        assert release_writer.wait(10), "Adjustment writer was not released"

    monkeypatch.setattr(payroll, "_assert_period_accepts_adjustments", pause_after_status_check)

    def write_adjustment():
        with sessions() as db:
            pids.put(("writer", db.execute(text("SELECT pg_backend_pid()")).scalar_one()))
            current = db.get(User, user_id)
            try:
                return payroll.create_adjustment(
                    PayrollAdjustmentIn(
                        payroll_period_id=period_id,
                        employee_id=employee_id,
                        adjustment_type="bonus",
                        amount=100,
                        reason="Synthetic race adjustment",
                    ),
                    db,
                    current,
                )
            except Exception as exc:
                db.rollback()
                return exc

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
        writer = workers.submit(write_adjustment)
        assert writer_ready.wait(10), "Adjustment writer did not reach the post-status pause"
        finalizer = workers.submit(finalize_period)
        process_ids = dict(pids.get(timeout=10) for _ in range(2))
        with sessions() as observer:
            deadline = monotonic() + 10
            while monotonic() < deadline:
                blockers = observer.execute(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": process_ids["finalizer"]},
                ).scalar_one()
                if process_ids["writer"] in blockers:
                    break
                sleep(0.02)
            else:
                pytest.fail("Period finalization overtook an accepted adjustment writer")
        release_writer.set()
        write_result = writer.result(timeout=10)
        final_result = finalizer.result(timeout=10)

    assert not isinstance(write_result, Exception), write_result
    assert not isinstance(final_result, Exception), final_result
    with sessions() as db:
        assert db.get(PayrollPeriod, period_id).status == "locked"
        assert db.query(PayrollAdjustment).filter_by(payroll_period_id=period_id).count() == 1


def test_postgres_approval_blocks_void_then_void_rechecks_status(payroll_postgres_sessions):
    sessions, engine = payroll_postgres_sessions
    user_id, employee_id, period_ids, label_uids = _seed(sessions)
    period_id = period_ids[0]
    with sessions() as db:
        current = db.get(User, user_id)
        record, _created = payroll._create_record_from_payload(
            db,
            _record(employee_id, period_id, label_uids[0]),
            current=current,
        )
        db.commit()
        record_id = int(record.id)
        period = db.get(PayrollPeriod, period_id)
        period.status = "locked"
        db.commit()

    approve_ready = Event()
    release_approve = Event()
    pids = Queue()

    def pause_record_approval(_connection, _cursor, statement, _parameters, _context, _many):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("update payroll_records set status="):
            approve_ready.set()
            assert release_approve.wait(10), "Approval was not released"

    def approve():
        with sessions() as db:
            pids.put(("approve", db.execute(text("SELECT pg_backend_pid()")).scalar_one()))
            current = db.get(User, user_id)
            try:
                return payroll.approve_period(period_id, db, current)
            except Exception as exc:
                db.rollback()
                return exc

    def void():
        with sessions() as db:
            pids.put(("void", db.execute(text("SELECT pg_backend_pid()")).scalar_one()))
            current = db.get(User, user_id)
            try:
                return payroll.void_record(record_id, db, current)
            except Exception as exc:
                db.rollback()
                return exc

    event.listen(engine, "before_cursor_execute", pause_record_approval)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            approve_future = workers.submit(approve)
            assert approve_ready.wait(10), "Approval did not reach the record update"
            void_future = workers.submit(void)
            process_ids = dict(pids.get(timeout=10) for _ in range(2))
            with sessions() as observer:
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    blockers = observer.execute(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": process_ids["void"]},
                    ).scalar_one()
                    if process_ids["approve"] in blockers:
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Void did not wait behind period approval")
            release_approve.set()
            approve_result = approve_future.result(timeout=10)
            void_result = void_future.result(timeout=10)
    finally:
        release_approve.set()
        event.remove(engine, "before_cursor_execute", pause_record_approval)

    assert not isinstance(approve_result, Exception), approve_result
    assert isinstance(void_result, Exception)
    assert getattr(void_result, "status_code", None) == 409
    with sessions() as db:
        assert db.get(PayrollPeriod, period_id).status == "approved"
        assert db.get(PayrollRecord, record_id).status == "approved"


def test_postgres_locking_reads_refresh_preloaded_period_and_control_label(payroll_postgres_sessions):
    sessions, _engine = payroll_postgres_sessions
    user_id, employee_id, period_ids, label_uids = _seed(sessions)
    period_id = period_ids[0]
    label_uid = label_uids[0]
    with sessions() as db:
        label = db.query(PayrollQrLabel).filter_by(label_uid=label_uid).one()
        label.operation_name = "Control"
        db.commit()

    with sessions() as db:
        current = db.get(User, user_id)
        preloaded_period = payroll._find_period(
            db,
            period_id,
            datetime(2026, 9, 20, tzinfo=timezone.utc),
            "MIL",
            for_update=False,
        )
        scan = PayrollControlScanIn(label_uid=label_uid, employee_id=employee_id)
        preloaded_label = payroll._load_control_scan(db, scan, current, for_update=False)
        review_token = payroll._control_review_token(preloaded_label, employee_id)

        with sessions() as updater:
            updated_period = updater.get(PayrollPeriod, period_id)
            updated_period.status = "locked"
            updated_label = updater.query(PayrollQrLabel).filter_by(label_uid=label_uid).one()
            updated_label.rate_per_piece = 333
            updater.commit()

        refreshed_period = payroll._find_period(
            db,
            period_id,
            datetime(2026, 9, 20, tzinfo=timezone.utc),
            "MIL",
            for_update=True,
        )
        assert refreshed_period is preloaded_period
        assert refreshed_period.status == "locked"

        with pytest.raises(HTTPException) as rejected:
            payroll.confirm_control_scan(
                PayrollControlConfirmIn(
                    label_uid=label_uid,
                    employee_id=employee_id,
                    review_token=review_token,
                ),
                db,
                current,
            )
        assert rejected.value.status_code == 409
        assert "changed since review" in str(rejected.value.detail)
