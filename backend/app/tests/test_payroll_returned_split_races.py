"""PostgreSQL races for returned-label metadata edits; historical pay is immutable."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import importlib
from threading import Event

import pytest
from fastapi import HTTPException

from app.api.routes import payroll
from app.schemas import AuditLog, PayrollPeriod, PayrollQrLabel, PayrollRecord, User
from app.schemas.payroll import PayrollRecordIn
from app.libs.dto.people.payroll_split_correction import SplitAllocationUpdate
from app.services import payroll_split_correction as correction
from app.tests.test_payroll_split_correction_races import (
    STAMP, _pause, _race, _run, _seed,
    split_postgres_sessions,  # noqa: F401 - shared loopback-only isolated PostgreSQL fixture
)


AUDIT = "correct_returned_split_labels"


def _service():
    return importlib.import_module("app.models.payroll_returned_split_correction_service")


def _history(sessions):
    with sessions() as db:
        return {row.id: deepcopy({column.name: getattr(row, column.name) for column in PayrollRecord.__table__.columns})
                for row in db.query(PayrollRecord).order_by(PayrollRecord.id)}


def _label_rows(sessions):
    with sessions() as db:
        return {row.id: deepcopy({column.name: getattr(row, column.name) for column in PayrollQrLabel.__table__.columns})
                for row in db.query(PayrollQrLabel).order_by(PayrollQrLabel.id)}


def _returned_seed(sessions, *, all_returned=False):
    seed = _seed(sessions)
    with sessions() as db:
        children = db.query(PayrollQrLabel).filter_by(split_from_label_id=seed["parent_id"]).order_by(PayrollQrLabel.id).all()
        seed["label_ids"] = [row.id for row in children]
        seed["sibling_record_id"] = children[1].payroll_record_id
        seed["uids"] = {row.id: row.label_uid for row in children}
        actor = db.get(User, seed["user_id"])
        for child in children if all_returned else children[:1]:
            payroll.return_qr_label(child.id, db, actor)
        view = correction.read_split_allocation(db, actor=actor, label_id=seed["label_id"])
        seed["payload"] = SplitAllocationUpdate(revision=view.revision, reason="Correct returned label metadata", parts=[
            {field: getattr(part, field) for field in (
                "label_id", "employee_id", "quantity", "operation_name", "rate_per_piece",
            )} for part in view.parts
        ])
    first = seed["payload"].parts[0]
    assert first.employee_id is None, "Returned labels must have no current employee assignment"
    first.operation_name = "Corrected returned sewing"
    first.rate_per_piece = Decimal("300")
    if all_returned:
        seed["payload"].parts[0].quantity = 8
        seed["payload"].parts[1].quantity = 12
    seed["history"] = _history(sessions)
    seed["labels"] = _label_rows(sessions)
    return seed


def _correct(seed, payload=None):
    return lambda db, actor: correction.correct_split_allocation(
        db, actor=actor, label_id=seed["label_id"], payload=payload or seed["payload"],
    )


def _pause_before_metadata_write(monkeypatch):
    # Pause after group/period/record validation but before mapped writes can
    # acquire their own implicit UPDATE locks and hide missing explicit locks.
    service = _service()
    original = service._view
    ready, release = Event(), Event()

    def paused(*args, **kwargs):
        result = original(*args, **kwargs)
        ready.set()
        assert release.wait(10), "Validated returned-label editor was not released"
        return result

    monkeypatch.setattr(service, "_view", paused)
    return ready, release


def _assert_history(sessions, seed, *, except_ids=()):
    current = _history(sessions)
    for record_id, values in seed["history"].items():
        if record_id not in except_ids:
            assert current[record_id] == values, f"Historical payroll record {record_id} was rewritten"


def _assert_labels(sessions, seed):
    with sessions() as db:
        labels = db.query(PayrollQrLabel).filter_by(split_from_label_id=seed["parent_id"]).order_by(PayrollQrLabel.id).all()
        assert db.query(PayrollQrLabel).count() == 3
        assert sum(row.quantity for row in labels) == 20
        assert {row.id: row.label_uid for row in labels} == seed["uids"]
        assert db.get(PayrollQrLabel, seed["parent_id"]).status == "superseded"
        for row in labels:
            assert row.return_count >= seed["labels"][row.id]["return_count"]
            if row.status == "available":
                assert row.payroll_record_id is None


def _assert_only_metadata_changed(sessions, seed):
    allowed = {"quantity", "operation_name", "rate_per_piece", "payload", "updated_at"}
    for label_id, current in _label_rows(sessions).items():
        before = seed["labels"][label_id]
        for column, value in before.items():
            if column not in allowed or before["status"] != "available":
                assert current[column] == value, f"Label {label_id} unexpectedly changed {column}"


@pytest.mark.parametrize("identical_retry", [False, True])
def test_postgres_returned_edits_serialize_stale_conflict_and_exact_retry(split_postgres_sessions, monkeypatch, identical_retry):
    sessions = split_postgres_sessions
    seed = _returned_seed(sessions, all_returned=True)
    other = seed["payload"].model_copy(deep=True)
    if not identical_retry:
        other.parts[0].operation_name = "Stale competing metadata"
    ready, release = _pause(monkeypatch, _service(), AUDIT)
    first, second = _race(sessions, seed, _correct(seed), _correct(seed, other), ready, release)
    assert not isinstance(first, Exception), first
    if identical_retry:
        assert second == first
    else:
        assert isinstance(second, HTTPException) and second.status_code == 409, second
    _assert_history(sessions, seed)
    _assert_labels(sessions, seed)
    _assert_only_metadata_changed(sessions, seed)
    with sessions() as db:
        assert db.query(PayrollRecord).count() == 3
        assert db.query(PayrollRecord).filter_by(status="recorded").count() == 0
        labels = [db.get(PayrollQrLabel, label_id) for label_id in seed["label_ids"]]
        assert [row.quantity for row in labels] == [8, 12]
        assert [row.status for row in labels] == ["available", "available"]
        assert labels[0].rate_per_piece == Decimal("300")
        assert db.query(AuditLog).filter_by(action=AUDIT).count() == 1


@pytest.mark.parametrize("correction_first", [False, True])
def test_postgres_returned_metadata_and_normal_rescan_serialize_without_rewriting_pay(split_postgres_sessions, monkeypatch, correction_first):
    sessions = split_postgres_sessions
    seed = _returned_seed(sessions)

    def rescan(db, actor):
        result = payroll.create_record(PayrollRecordIn(
            scan_uid=seed["uids"][seed["label_id"]], employee_id=seed["employee_id"],
            # Real rescanning can happen after the historical payroll period;
            # no common period row can accidentally mask missing label locks.
            scanned_at=STAMP + timedelta(days=30),
            quantity=1, rate_per_piece=1,
        ), db, actor)
        return result

    ready, release = (_pause_before_metadata_write(monkeypatch) if correction_first
                      else _pause(monkeypatch, payroll, "create"))
    first, second = _race(sessions, seed, _correct(seed) if correction_first else rescan,
                          rescan if correction_first else _correct(seed), ready, release)
    assert not isinstance(first, Exception), first
    if correction_first:
        assert not isinstance(second, Exception), second
    else:
        assert isinstance(second, HTTPException) and second.status_code == 409, second
    _assert_history(sessions, seed)
    _assert_labels(sessions, seed)
    with sessions() as db:
        label = db.get(PayrollQrLabel, seed["label_id"])
        new = db.get(PayrollRecord, label.payroll_record_id)
        assert db.query(PayrollRecord).count() == 4
        assert new.id not in seed["history"] and new.status == "recorded"
        assert new.payroll_period_id is None
        assert label.status == "scanned" and label.return_count == 1
        assert new.quantity == label.quantity == 7
        assert new.rate_per_piece == label.rate_per_piece == Decimal("300" if correction_first else "250")
        assert new.operation_name == label.operation_name == ("Corrected returned sewing" if correction_first else "Sew")
        assert new.total_amount == Decimal("2100" if correction_first else "1750")
        assert sum(row.total_amount for row in db.query(PayrollRecord).filter_by(status="recorded")) == Decimal("5350" if correction_first else "5000")
        assert db.query(AuditLog).filter_by(action=AUDIT).count() == int(correction_first)


@pytest.mark.parametrize("correction_first", [False, True])
def test_postgres_returned_edit_and_active_sibling_return_serialize(split_postgres_sessions, monkeypatch, correction_first):
    sessions = split_postgres_sessions
    seed = _returned_seed(sessions)
    other = lambda db, actor: payroll.return_qr_label(seed["label_ids"][1], db, actor)
    ready, release = _pause(monkeypatch, _service() if correction_first else payroll,
                            AUDIT if correction_first else "return_qr")
    first, second = _race(sessions, seed, _correct(seed) if correction_first else other,
                          other if correction_first else _correct(seed), ready, release)
    assert not isinstance(first, Exception), first
    if correction_first:
        assert not isinstance(second, Exception), second
    else:
        assert isinstance(second, HTTPException) and second.status_code == 409, second
    _assert_history(sessions, seed, except_ids=(seed["sibling_record_id"],))
    _assert_labels(sessions, seed)
    with sessions() as db:
        assert db.query(PayrollRecord).count() == 3
        assert db.query(PayrollRecord).filter_by(status="recorded").count() == 0
        sibling = db.get(PayrollRecord, seed["sibling_record_id"])
        expected = {**seed["history"][sibling.id], "status": "voided", "scan_uid": None,
                    "original_scan_uid": seed["uids"][seed["label_ids"][1]], "updated_at": sibling.updated_at}
        assert _history(sessions)[sibling.id] == expected
        assert all(db.get(PayrollQrLabel, label_id).status == "available" for label_id in seed["label_ids"])
        assert db.query(AuditLog).filter_by(action=AUDIT).count() == int(correction_first)


@pytest.mark.parametrize("correction_first", [False, True])
def test_postgres_returned_metadata_and_historical_period_lock_both_succeed_without_pay_mutation(split_postgres_sessions, monkeypatch, correction_first):
    sessions = split_postgres_sessions
    seed = _returned_seed(sessions, all_returned=True)
    other = lambda db, actor: payroll.lock_period(seed["period_id"], db, actor)
    ready, release = _pause(monkeypatch, _service() if correction_first else payroll,
                            AUDIT if correction_first else "lock")
    first, second = _race(sessions, seed, _correct(seed) if correction_first else other,
                          other if correction_first else _correct(seed), ready, release)
    assert not isinstance(first, Exception), first
    assert not isinstance(second, Exception), second
    _assert_history(sessions, seed)
    _assert_labels(sessions, seed)
    _assert_only_metadata_changed(sessions, seed)
    with sessions() as db:
        assert db.get(PayrollPeriod, seed["period_id"]).status == "locked"
        assert db.query(PayrollRecord).count() == 3
        assert db.query(AuditLog).filter_by(action=AUDIT).count() == 1
        assert db.get(PayrollQrLabel, seed["label_id"]).quantity == 8


def test_postgres_historical_period_reassignment_during_returned_edit_requires_retry(split_postgres_sessions):
    sessions = split_postgres_sessions
    seed = _returned_seed(sessions, all_returned=True)
    with sessions.begin() as db:
        period = PayrollPeriod(factory_code="MIL", period_no="REASSIGN", name="Synthetic competing assignment",
                               start_date=STAMP + timedelta(days=5), end_date=STAMP + timedelta(days=7), status="open")
        db.add(period)
        db.flush()
        target_period_id = period.id
    ready, release = Event(), Event()

    def reassign(db, actor):
        db.query(PayrollPeriod).filter_by(id=seed["period_id"]).with_for_update().one()
        old = db.get(PayrollRecord, seed["record_id"])
        old.payroll_period_id = target_period_id
        db.flush()
        ready.set()
        assert release.wait(10)
        db.commit()
        return True

    first, second = _race(sessions, seed, reassign, _correct(seed), ready, release)
    assert first is True
    assert isinstance(second, HTTPException) and second.status_code == 409, second
    _assert_history(sessions, seed, except_ids=(seed["record_id"],))
    assert _label_rows(sessions) == seed["labels"]
    with sessions() as db:
        assert db.query(AuditLog).filter_by(action=AUDIT).count() == 0


def test_postgres_returned_edit_midwrite_rollback_preserves_history_and_allows_fresh_retry(split_postgres_sessions, monkeypatch):
    sessions = split_postgres_sessions
    seed = _returned_seed(sessions, all_returned=True)
    service = _service()
    apply = service.apply_returned_split_part
    calls = []

    def fail_second(*args, **kwargs):
        apply(*args, **kwargs)
        calls.append(kwargs["label"].id)
        if len(calls) == 2:
            raise RuntimeError("Injected returned-label PostgreSQL persistence failure")

    monkeypatch.setattr(service, "apply_returned_split_part", fail_second)
    result = _run(sessions, seed, _correct(seed))
    assert isinstance(result, RuntimeError), result
    assert len(calls) == 2
    assert _label_rows(sessions) == seed["labels"]
    _assert_history(sessions, seed)
    with sessions() as db:
        assert db.query(AuditLog).filter_by(action=AUDIT).count() == 0
    monkeypatch.setattr(service, "apply_returned_split_part", apply)
    with ThreadPoolExecutor(max_workers=1) as workers:
        result = workers.submit(_run, sessions, seed, _correct(seed)).result(timeout=10)
    assert not isinstance(result, Exception), result
    _assert_history(sessions, seed)
    _assert_labels(sessions, seed)
    _assert_only_metadata_changed(sessions, seed)
    with sessions() as db:
        audits = db.query(AuditLog).filter_by(action=AUDIT).all()
        assert len(audits) == 1 and audits[0].entry_hash
        assert db.query(PayrollRecord).count() == 3
