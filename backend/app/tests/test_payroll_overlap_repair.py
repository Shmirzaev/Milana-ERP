from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from queue import Queue
from threading import Event
from time import monotonic, sleep

import pytest
from sqlalchemy import text

from app.api.routes import payroll
from app.db import session as session_module
from app.models import PayrollPeriod, PayrollRecord, User
from app.schemas.payroll import PayrollPeriodIn, PayrollPeriodUpdate
from app.tests.test_payroll_period_races import _seed, payroll_postgres_sessions  # noqa: F401
from scripts import repair_payroll_period_overlap_20261013 as repair


def _rows():
    return [
        dict(id=4, factory_code="MIL", period_no="PAY-2026-07", status="locked",
             start_date=repair.ORIGINAL_START, end_date=repair.ORIGINAL_END),
        dict(id=5, factory_code="MIL", period_no="PAY-2026-10", status="open",
             start_date=repair.NEW_ORIGINAL_START, end_date=repair.NEW_END),
    ]


def test_repair_boundary_and_idempotence():
    rows = _rows()
    changes = repair.plan(rows, 0)
    assert len(changes) == 2
    for change in changes:
        next(row for row in rows if row["id"] == change["id"])[change["field"]] = change["after"]
    assert rows[0]["end_date"] < rows[1]["start_date"] == repair.CUTOVER
    assert repair.plan(rows, 0) == []


@pytest.mark.parametrize("changed", ["status", "factory", "date", "dependencies", "third_period"])
def test_repair_rejects_unreviewed_changes(changed):
    rows = _rows()
    if changed == "status":
        rows[0]["status"] = "paid"
    if changed == "factory":
        rows[0]["factory_code"] = "ECO"
    if changed == "date":
        rows[0]["end_date"] += timedelta(days=1)
    if changed == "third_period":
        rows.append(dict(rows[1], id=9, period_no="Unexpected"))
    with pytest.raises(ValueError):
        repair.plan(rows, 1 if changed == "dependencies" else 0)


def test_postgres_repair_preserves_wages_and_is_audited(payroll_postgres_sessions, monkeypatch):
    sessions, _engine = payroll_postgres_sessions
    _user_id, employee_id, _period_ids, _labels = _seed(sessions)
    with sessions() as db:
        db.add_all([PayrollPeriod(**row, name=row["period_no"]) for row in _rows()])
        db.flush()
        db.execute(text("SELECT setval(pg_get_serial_sequence('payroll_periods', 'id'), (SELECT max(id) FROM payroll_periods))"))
        record = PayrollRecord(
            factory_code="MIL", payroll_period_id=4, employee_id=employee_id,
            dedupe_key="repair-preserved-wage", scanned_at=datetime(2026, 10, 13, 7, tzinfo=timezone.utc),
            quantity=10, rate_per_piece=250, total_amount=2500, currency="UZS", status="recorded",
        )
        db.add(record)
        db.commit()
        record_id = record.id
    monkeypatch.setattr(session_module, "SessionLocal", sessions)
    preview = repair.run()
    with pytest.raises(ValueError, match="changed since review"):
        repair.run(True, "stale", "/opt/milana-erp/shared/backups/test.dump")
    result = repair.run(True, preview["fingerprint"], "/opt/milana-erp/shared/backups/test.dump")
    assert len(result["audit_ids"]) == 2
    assert repair.run()["changes"] == []
    with sessions() as db:
        assert db.get(PayrollRecord, record_id).payroll_period_id == 4
        assert db.get(PayrollRecord, record_id).total_amount == 2500
        assert db.get(PayrollPeriod, 4).status == "locked"
        assert db.get(PayrollPeriod, 5).status == "open"
        matches = db.query(PayrollPeriod).filter(
            PayrollPeriod.start_date <= datetime(2026, 10, 13, 7, tzinfo=timezone.utc),
            PayrollPeriod.end_date >= datetime(2026, 10, 13, 7, tzinfo=timezone.utc),
        ).all()
        assert [p.id for p in matches] == [5]


@pytest.mark.parametrize("second_action", ["create", "update"])
def test_postgres_concurrent_period_changes_cannot_overlap(payroll_postgres_sessions, monkeypatch, second_action):
    sessions, _engine = payroll_postgres_sessions
    user_id, _employee, period_ids, _labels = _seed(sessions)
    start = datetime(2030 if second_action == "create" else 2031, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=10)
    ready, release = Event(), Event()
    pids = Queue()
    original = payroll._assert_period_dates_available

    def hold_first(*args, **kwargs):
        original(*args, **kwargs)
        if not ready.is_set():
            ready.set()
            assert release.wait(10)

    monkeypatch.setattr(payroll, "_assert_period_dates_available", hold_first)

    def write(action):
        with sessions() as db:
            pids.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            user = db.get(User, user_id)
            try:
                if action == "update":
                    return payroll.update_period(period_ids[0], PayrollPeriodUpdate(start_date=start, end_date=end), db, user)
                return payroll.create_period(PayrollPeriodIn(name="Concurrent period", start_date=start, end_date=end), db, user)
            except Exception as exc:
                db.rollback()
                return exc

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(write, "create")
        try:
            assert ready.wait(10)
            winner_pid = pids.get(timeout=10)
            second = workers.submit(write, second_action)
            waiter_pid = pids.get(timeout=10)
            with sessions() as observer:
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    blockers = observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter_pid}).scalar_one()
                    if winner_pid in blockers:
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Concurrent period change did not wait for schedule lock")
        finally:
            release.set()
        first_result, second_result = first.result(timeout=10), second.result(timeout=10)
    assert isinstance(first_result, PayrollPeriod), first_result
    assert getattr(second_result, "status_code", None) == 409, second_result
    with sessions() as db:
        assert db.query(PayrollPeriod).filter(PayrollPeriod.start_date <= end, PayrollPeriod.end_date >= start).count() == 1
