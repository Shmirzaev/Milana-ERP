"""Synthetic-only PostgreSQL proof. Does not load application DB credentials."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timezone
import os
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.people.bst_master_handoff_service import (
    HandoffRefused, apply_reviewed_plan, capture_plan, fingerprint, preview_plan,
)
from app.schemas import AuditLog, Employee, PayrollQrLabel, PayrollRecord, SewingDailyReport, SewingFlow, User


# Deliberately synthetic: these identifiers and labels do not describe a live roster.
OLD_MASTER_A_ID = 910001
OLD_MASTER_B_ID = 910002
INCOMING_MASTER_A_ID = 910003
INCOMING_MASTER_B_ID = 910004
UNRELATED_MASTER_ID = 910005
FLOW_A_ID = 920001
FLOW_B_ID = 920002
WORKER_A_BASE = 930000
WORKER_B_BASE = 940000


SPECS = [
    {"old_master_id": OLD_MASTER_A_ID, "new_master_id": INCOMING_MASTER_A_ID, "flow_id": FLOW_A_ID, "new_display_name": 'New Gamma'},
    {"old_master_id": OLD_MASTER_B_ID, "new_master_id": INCOMING_MASTER_B_ID, "flow_id": FLOW_B_ID, "new_display_name": 'New Delta'},
]


@pytest.fixture(scope="module")
def sessions():
    url = os.environ.get("BST_HANDOFF_TEST_URL")
    if not url:
        pytest.skip("BST_HANDOFF_TEST_URL required for PostgreSQL lock/integrity checks")
    control = create_engine(url)
    assert control.dialect.name == "postgresql"
    assert control.url.host in {"localhost", "127.0.0.1"}
    assert control.url.database == "bst_handoff_test"
    schema = "bst_handoff_" + uuid4().hex
    with control.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()
        with control.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()


@pytest.fixture
def prepared(sessions):
    with sessions() as db:
        db.execute(text("TRUNCATE employees, sewing_flows, audit_logs RESTART IDENTITY CASCADE"))
        for identity, name, band in ((OLD_MASTER_A_ID, 'Old Alpha', "1-Band"),
                                     (OLD_MASTER_B_ID, 'Beta Old', "4-Band"),
                                     (UNRELATED_MASTER_ID, 'Unrelated master', "2-Band")):
            workplace = 'Old Beta' if identity == OLD_MASTER_B_ID else name
            db.add(Employee(id=identity, factory_code="BST", full_name=name,
                            position=f"{band} master", hr_profile_json={"section": band, "workplace": workplace}))
        db.flush()
        db.add_all([
            Employee(id=INCOMING_MASTER_B_ID, factory_code="BST", full_name='New Delta', manager_employee_id=UNRELATED_MASTER_ID,
                     position='2-Band - Unrelated master', hr_profile_json={"section": "2-Band", "custom": "retained"}),
            Employee(id=INCOMING_MASTER_A_ID, factory_code="BST", full_name='Existing Gamma', manager_employee_id=OLD_MASTER_B_ID,
                     position='4-Band - Old Beta', hr_profile_json={"section": "4-Band", "workplace": 'Old Beta'}),
        ])
        for index in range(42):
            db.add(Employee(id=WORKER_A_BASE+index, factory_code="BST", full_name=f"Band1 worker {index}",
                            manager_employee_id=OLD_MASTER_A_ID, position='1-Band - Old Alpha',
                            salary=123456, hr_profile_json={"section": "1-Band", "workplace": 'Old Alpha', "other": True}))
        for index in range(40):
            db.add(Employee(id=WORKER_B_BASE+index, factory_code="BST", full_name=f"Band4 worker {index}",
                            manager_employee_id=OLD_MASTER_B_ID, position='4-Band - Old Beta',
                            hr_profile_json={"section": "4-Band", "workplace": 'Old Beta'}))
        db.add_all([SewingFlow(id=FLOW_A_ID, factory_code="BST", code='SYNTHETIC-FLOW-A', name='Old Alpha'),
                    SewingFlow(id=FLOW_B_ID, factory_code="BST", code='SYNTHETIC-FLOW-B', name='Old Beta')])
        db.flush()
        db.add(PayrollRecord(factory_code="BST", employee_id=INCOMING_MASTER_A_ID, dedupe_key="unchanged-history",
                             total_amount=12345, scanned_at=datetime.now(timezone.utc),
                             raw_employee_json={"id": INCOMING_MASTER_A_ID, "master": OLD_MASTER_B_ID}, raw_work_json={"line_name": 'Old Beta'}))
        db.add(PayrollQrLabel(factory_code="BST", label_uid="old-qr", sewing_flow_id=FLOW_B_ID,
                             sewing_line_code='SYNTHETIC-FLOW-B', sewing_line_name='Old Beta'))
        db.add(SewingDailyReport(report_date=date(2026, 11, 3), sewing_flow_id=FLOW_A_ID,
                                 line_name='Old Alpha', line_code='SYNTHETIC-FLOW-A', sewn_qty=100))
        db.commit()
        plan = capture_plan(db, SPECS)
        db.rollback()
    return plan


def _protected(db):
    return {table.name: [tuple(row) for row in db.execute(select(table).order_by(*table.primary_key.columns)).all()]
            for table in Base.metadata.sorted_tables
            if table.name not in {"employees", "sewing_flows", "audit_logs"}}


def test_apply_preserves_identity_every_other_table_and_retry(sessions, prepared):
    with sessions() as db:
        before = _protected(db)
        all_people = {row.id: (row.full_name, row.salary, row.user_id, row.status, row.employee_no)
                      for row in db.scalars(select(Employee))}
        result = apply_reviewed_plan(db, prepared, reviewed_sha256=fingerprint(prepared), backup_reference="synthetic-only")
        assert result["worker_counts"] == {str(INCOMING_MASTER_A_ID): 42, str(INCOMING_MASTER_B_ID): 40}
        db.commit()
    with sessions() as db:
        assert _protected(db) == before
        assert {row.id: (row.full_name, row.salary, row.user_id, row.status, row.employee_no)
                for row in db.scalars(select(Employee))} == all_people
        assert db.get(Employee, INCOMING_MASTER_A_ID).manager_employee_id is None
        assert db.get(Employee, INCOMING_MASTER_B_ID).manager_employee_id is None
        assert db.get(Employee, UNRELATED_MASTER_ID).position == "2-Band master"
        assert db.get(Employee, OLD_MASTER_A_ID).full_name == 'Old Alpha'
        assert db.get(Employee, OLD_MASTER_B_ID).full_name == 'Beta Old'
        assert db.get(Employee, WORKER_A_BASE).position == '1-Band - New Gamma'
        assert db.get(Employee, WORKER_B_BASE).hr_profile_json["workplace"] == 'New Delta'
        assert db.get(Employee, INCOMING_MASTER_B_ID).hr_profile_json["custom"] == "retained"
        assert db.get(SewingFlow, FLOW_B_ID).name == 'New Delta'
        assert db.get(SewingFlow, FLOW_A_ID).code == 'SYNTHETIC-FLOW-A'
        assert db.scalars(select(AuditLog)).one().entry_hash
        retry = apply_reviewed_plan(db, prepared, reviewed_sha256=fingerprint(prepared), backup_reference="synthetic-only")
        assert retry["already_applied"]
        db.commit()
        assert len(db.scalars(select(AuditLog)).all()) == 1


@pytest.mark.parametrize("drift", ["name", "manager", "new_worker", "new_leader_child", "flow_name",
                                  "status", "factory", "supervisor", "linked_account"])
def test_stale_plan_refused_without_writes(sessions, prepared, drift):
    with sessions() as db:
        if drift == "name": db.get(Employee, INCOMING_MASTER_A_ID).full_name = "Changed identity"
        if drift == "manager": db.get(Employee, WORKER_A_BASE).manager_employee_id = UNRELATED_MASTER_ID
        if drift == "new_worker": db.add(Employee(factory_code="BST", full_name="New child", manager_employee_id=OLD_MASTER_A_ID))
        if drift == "new_leader_child": db.get(Employee, WORKER_A_BASE).manager_employee_id = INCOMING_MASTER_B_ID
        if drift == "flow_name": db.get(SewingFlow, FLOW_A_ID).name = "Renamed elsewhere"
        if drift == "status": db.get(Employee, INCOMING_MASTER_B_ID).status = "terminated"
        if drift == "factory": db.get(Employee, WORKER_A_BASE).factory_code = "MIL"
        if drift in {"supervisor", "linked_account"}:
            account = User(name="Synthetic account", email=f"{drift}@example.invalid", password_hash="no-login", factory_code="BST")
            db.add(account); db.flush()
            if drift == "supervisor": db.get(SewingFlow, FLOW_A_ID).supervisor_id = account.id
            if drift == "linked_account": db.get(Employee, INCOMING_MASTER_A_ID).user_id = account.id
        db.commit()
        before = [tuple(row) for row in db.execute(select(Employee.__table__).order_by(Employee.id))]
        with pytest.raises(HandoffRefused):
            apply_reviewed_plan(db, prepared, reviewed_sha256=fingerprint(prepared), backup_reference="synthetic-only")
        db.rollback()
        assert [tuple(row) for row in db.execute(select(Employee.__table__).order_by(Employee.id))] == before
        assert not db.scalars(select(AuditLog)).all()


def test_plan_digest_refused_and_dry_run_has_no_writes(sessions, prepared):
    with sessions() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        assert capture_plan(db, SPECS) == prepared
        assert preview_plan(prepared)["worker_counts"] == {str(INCOMING_MASTER_A_ID): 42, str(INCOMING_MASTER_B_ID): 40}
        assert db.get(Employee, INCOMING_MASTER_A_ID).manager_employee_id == OLD_MASTER_B_ID
        db.rollback()
        with pytest.raises(HandoffRefused, match="digest"):
            apply_reviewed_plan(db, prepared, reviewed_sha256="0" * 64, backup_reference="synthetic-only")
        assert not db.scalars(select(AuditLog)).all()


def test_private_profile_fields_never_leave_database_and_hash_detects_drift(sessions, prepared):
    import json
    with sessions() as db:
        db.get(Employee, INCOMING_MASTER_A_ID).hr_profile_json = {"section": "4-Band", "workplace": 'Old Beta',
                                                "passport": "PRIVATE-DOCUMENT", "salary_note": "PRIVATE-PAY"}
        db.commit()
        plan = capture_plan(db, SPECS)
        assert "PRIVATE-" not in json.dumps(plan)
        assert "passport" not in json.dumps(plan)
        assert "PRIVATE-" not in json.dumps(preview_plan(plan))
        apply_reviewed_plan(db, plan, reviewed_sha256=fingerprint(plan), backup_reference="synthetic-only")
        db.commit()
        receipt = db.scalars(select(AuditLog)).one()
        assert "PRIVATE-" not in json.dumps(receipt.old_value_json)
        assert "PRIVATE-" not in json.dumps(receipt.new_value_json)
        assert db.get(Employee, INCOMING_MASTER_A_ID).hr_profile_json["passport"] == "PRIVATE-DOCUMENT"


@pytest.mark.parametrize("reversion", ["manager", "flow_name", "new_child", "private_profile"])
def test_retry_refuses_receipt_after_current_state_drift(sessions, prepared, reversion):
    with sessions() as db:
        apply_reviewed_plan(db, prepared, reviewed_sha256=fingerprint(prepared), backup_reference="synthetic-only")
        db.commit()
        if reversion == "manager": db.get(Employee, WORKER_A_BASE).manager_employee_id = OLD_MASTER_A_ID
        if reversion == "flow_name": db.get(SewingFlow, FLOW_A_ID).name = 'Old Alpha'
        if reversion == "new_child": db.add(Employee(factory_code="BST", full_name="Later child", manager_employee_id=INCOMING_MASTER_B_ID))
        if reversion == "private_profile": db.get(Employee, WORKER_A_BASE).hr_profile_json = {"private": "changed"}
        db.commit()
        with pytest.raises(HandoffRefused, match="after-state has drifted"):
            apply_reviewed_plan(db, prepared, reviewed_sha256=fingerprint(prepared), backup_reference="synthetic-only")
        db.rollback()
        assert len(db.scalars(select(AuditLog)).all()) == 1


def test_audit_failure_rolls_back_whole_handoff(sessions, prepared, monkeypatch):
    from app.models.people import bst_master_handoff_service as service
    def fail(*args, **kwargs): raise RuntimeError("Injected audit failure")
    monkeypatch.setattr(service, "log_action", fail)
    with sessions() as db:
        with pytest.raises(RuntimeError, match="Injected"):
            apply_reviewed_plan(db, prepared, reviewed_sha256=fingerprint(prepared), backup_reference="synthetic-only")
        db.rollback()
        assert capture_plan(db, SPECS) == prepared
        assert not db.scalars(select(AuditLog)).all()


@pytest.mark.parametrize("invalid", ["bool_id", "negative_id", "unknown", "space_name", "same_leader", "duplicate_flow"])
def test_invalid_specification_refused(sessions, prepared, invalid):
    specs = deepcopy(SPECS)
    if invalid == "bool_id": specs[0]["old_master_id"] = True
    if invalid == "negative_id": specs[0]["old_master_id"] = -1
    if invalid == "unknown": specs[0]["unreviewed"] = "value"
    if invalid == "space_name": specs[0]["new_display_name"] = " padded "
    if invalid == "same_leader": specs[1]["new_master_id"] = INCOMING_MASTER_A_ID
    if invalid == "duplicate_flow": specs[1]["flow_id"] = FLOW_A_ID
    with sessions() as db, pytest.raises(HandoffRefused):
        capture_plan(db, specs)


def test_dirty_session_refused_and_unrelated_profile_data_preserved(sessions, prepared):
    with sessions() as db:
        db.get(Employee, WORKER_A_BASE).full_name = "Uncommitted unrelated change"
        with pytest.raises(HandoffRefused, match="clean"):
            apply_reviewed_plan(db, prepared, reviewed_sha256=fingerprint(prepared), backup_reference="synthetic-only")
        db.rollback()
        # Keep intentionally mixed old labels that are not exact matches; never broadly replace text.
        row = db.get(Employee, WORKER_A_BASE)
        row.position = "Legacy role text"
        row.hr_profile_json = {"section": "other section", "workplace": "Other workplace", "custom": 123}
        db.commit()
        plan = capture_plan(db, SPECS)
        apply_reviewed_plan(db, plan, reviewed_sha256=fingerprint(plan), backup_reference="synthetic-only")
        db.commit()
    with sessions() as db:
        row = db.get(Employee, WORKER_A_BASE)
        assert row.manager_employee_id == INCOMING_MASTER_A_ID
        assert row.position == "Legacy role text"
        assert row.hr_profile_json == {"section": "other section", "workplace": "Other workplace", "custom": 123}


def test_write_lock_times_out_and_clean_retry_recovers(sessions, prepared):
    from sqlalchemy.exc import OperationalError
    with sessions() as blocker:
        blocker.execute(text("LOCK TABLE employees IN ROW EXCLUSIVE MODE"))
        with sessions() as db:
            with pytest.raises(OperationalError, match="lock timeout"):
                apply_reviewed_plan(db, prepared, reviewed_sha256=fingerprint(prepared), backup_reference="synthetic-only")
            db.rollback()
        blocker.rollback()
    with sessions() as db:
        assert capture_plan(db, SPECS) == prepared
        assert not db.scalars(select(AuditLog)).all()
        assert not apply_reviewed_plan(db, prepared, reviewed_sha256=fingerprint(prepared), backup_reference="synthetic-only")["already_applied"]
        db.commit()


def test_bounded_two_concurrent_retries_write_once(sessions, prepared):
    def run():
        with sessions() as db:
            result = apply_reviewed_plan(db, prepared, reviewed_sha256=fingerprint(prepared), backup_reference="synthetic-only")
            db.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sum(not row["already_applied"] for row in results) == 1
    with sessions() as db:
        assert len(db.scalars(select(AuditLog)).all()) == 1


def test_concurrent_new_worker_waits_for_handoff_then_is_not_silently_transferred(sessions, prepared):
    locked = Event(); release = Event(); insert_started = Event()
    engine = sessions.kw["bind"]
    def hold(conn, cursor, statement, params, context, many):
        if statement.startswith("LOCK TABLE employees"):
            locked.set()
            assert release.wait(10)
    def started_insert(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO employees"):
            insert_started.set()
    event.listen(engine, "after_cursor_execute", hold)
    event.listen(engine, "before_cursor_execute", started_insert)
    def apply():
        with sessions() as db:
            apply_reviewed_plan(db, prepared, reviewed_sha256=fingerprint(prepared), backup_reference="synthetic-only"); db.commit()
    def insert():
        with sessions() as db:
            db.add(Employee(factory_code="BST", full_name="Concurrent new worker", manager_employee_id=OLD_MASTER_A_ID))
            db.commit()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(apply)
            assert locked.wait(5)
            second = pool.submit(insert)
            assert insert_started.wait(5)
            assert not second.done()
            release.set()
            first.result(timeout=15); second.result(timeout=15)
    finally:
        release.set(); event.remove(engine, "after_cursor_execute", hold)
        event.remove(engine, "before_cursor_execute", started_insert)
    with sessions() as db:
        worker = db.scalars(select(Employee).where(Employee.full_name == "Concurrent new worker")).one()
        assert worker.manager_employee_id == OLD_MASTER_A_ID
        assert len(db.scalars(select(Employee).where(Employee.manager_employee_id == INCOMING_MASTER_A_ID)).all()) == 42
