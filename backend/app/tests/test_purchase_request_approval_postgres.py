"""Purchase-request approval regressions against an explicitly approved PostgreSQL instance.

A fresh guarded database receives the candidate's full Alembic migration chain.
Migration reference rows are reported; all other business tables must be empty.
Unknown stored status is characterized with a locked-row stub, not as PG data.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4
import time

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import joinedload, sessionmaker

from app.api.routes.purchasing import router as purchasing_router
from app.core.deps import get_current_user, get_db
from app.libs.dto.purchasing.purchase_request_input import PurchaseRequestApprovalIn
from app.models import audit_service, purchasing_service as core
from app.models.purchasing import requests_service as public
from app.schemas import AuditLog, Department, Item, Notification, PurchaseRequest, PurchaseRequestLine, Supplier, User
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine, verify_approved_instance,
)


@pytest.fixture(scope="module")
def sessions():
    try:
        instance = load_approved_instance()
        verify_approved_instance(instance)
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    engine = None
    try:
        engine = target_engine(target, options="-cstatement_timeout=30000 -clock_timeout=30000")
        assert engine.dialect.name == "postgresql"
        with engine.connect() as connection:
            assert sa.inspect(connection).get_table_names(schema="public") == []
        from app.core.config import settings
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        head = ScriptDirectory.from_config(config).get_current_head()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(settings, "DATABASE_URL", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
            patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
            command.upgrade(config, "head")
        with engine.connect() as connection:
            tables = sorted(sa.inspect(connection).get_table_names(schema="public"))
            preparer = connection.dialect.identifier_preparer
            counts = {name: connection.exec_driver_sql("SELECT count(*) FROM " + preparer.quote(name)).scalar_one() for name in tables}
            print("approval PG migration baseline counts:", counts)
            for table in ("sewing_flows", "departments", "warehouses", "roles"):
                print("approval PG migration baseline", table, connection.exec_driver_sql("SELECT * FROM " + preparer.quote(table)).mappings().all())
            assert connection.execute(text("select version_num from alembic_version")).scalars().all() == [head]
            reference_tables = {"alembic_version", "sewing_flows", "departments", "warehouses", "roles"}
            assert all(count == 0 for name, count in counts.items() if name not in reference_tables), counts
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        factory.owned_user_ids = set()
        yield factory
    finally:
        finalize_target(target, engine)


def make_case(sessions, *, status="pending_approval", category="fabric", count=2, recipient=True):
    token = uuid4().hex
    with sessions.begin() as db:
        dept = db.query(Department).filter_by(code="PLN").first()
        if dept is None:
            dept = Department(code="PLN", name="Planning")
            db.add(dept)
            db.flush()
        actor = User(name="Approval actor", email=f"a-{token}@example.invalid", password_hash="unused", department_id=dept.id, is_active=True, extra_permissions=["purchasing.approve"])
        db.add(actor)
        if recipient:
            receiver = User(name="Approval recipient", email=f"r-{token}@example.invalid", password_hash="unused", department_id=dept.id, is_active=True)
            db.add(receiver)
        db.flush()
        sessions.owned_user_ids.add(actor.id)
        if recipient:
            sessions.owned_user_ids.add(receiver.id)
        request = PurchaseRequest(request_no=f"APP-{token}", status=status, requested_by=actor.id)
        db.add(request)
        db.flush()
        payload = []
        for index in range(count):
            item = Item(sku=f"A-{token}-{index}", name="Fixture", category=category, unit="pc")
            supplier = Supplier(name=f"Supplier {token}-{index}")
            db.add_all([item, supplier]); db.flush()
            line = PurchaseRequestLine(purchase_request_id=request.id, item_id=item.id, unit="pc", requested_quantity=1, material_name="before", photo_url="/before")
            db.add(line); db.flush()
            payload.append({"purchase_request_line_id": line.id, "material_name": f"  material {index}  ", "photo_url": f"  /photo-{index}  ", "preferred_supplier_id": supplier.id})
        recipients = {u.id for u in db.query(User).filter_by(department_id=dept.id, is_active=True).all()} - {actor.id}
        return {"id": request.id, "number": request.request_no, "actor": actor.id, "recipient": receiver.id if recipient else None, "lines": payload, "recipients": recipients, "initial": status}


def state(sessions, case):
    with sessions() as db:
        request = db.get(PurchaseRequest, case["id"])
        audits = db.query(AuditLog).filter_by(entity_type="PurchaseRequest", entity_id=request.id).order_by(AuditLog.id).all()
        notifications = db.query(Notification).filter_by(title="Purchase request approved: " + case["number"]).order_by(Notification.id).all()
        return (request.status, request.approved_by, request.approved_at, request.updated_at,
                [(x.id, x.material_name, x.photo_url, x.preferred_supplier_id, x.updated_at) for x in sorted(request.lines, key=lambda x: x.id)],
                [(x.id, x.action, x.old_value_json, x.new_value_json, x.entry_hash) for x in audits],
                [(x.id, x.user_id) for x in notifications])


def invoke(sessions, case, lines=None):
    with sessions() as db:
        return public.approve_purchase_request(db, request_id=case["id"], payload=PurchaseRequestApprovalIn(lines=case["lines"] if lines is None else lines), current=db.get(User, case["actor"]))


def assert_success(sessions, case):
    current = state(sessions, case)
    assert current[0] == "approved" and current[1] == case["actor"] and current[2] is not None
    assert [(x[0], x[1], x[2], x[3]) for x in current[4]] == [(line["purchase_request_line_id"], f"material {i}", f"/photo-{i}", line["preferred_supplier_id"]) for i, line in enumerate(case["lines"])]
    assert len(current[5]) == 1 and current[5][0][1:4] == ("approve", {"status": case["initial"]}, {"status": "approved", "request_no": case["number"]})
    assert {row[1] for row in current[6]} == case["recipients"] and len(current[6]) == len(case["recipients"])
    with sessions() as db:
        row = db.query(AuditLog).filter_by(entity_type="PurchaseRequest", entity_id=case["id"]).one()
        assert row.entry_hash == audit_service._audit_entry_hash(prev_hash=row.prev_hash, user_id=row.user_id, action=row.action, entity_type=row.entity_type, entity_id=row.entity_id, old_value=row.old_value_json, new_value=row.new_value_json)
    return current


@pytest.mark.parametrize("initial", ["draft", "pending_approval"])
def test_approval_commits_actual_rows_audit_and_recipients(sessions, initial):
    case = make_case(sessions, status=initial)
    invoke(sessions, case)
    status, actor, at, _, lines, audits, notices = state(sessions, case)
    assert (status, actor) == ("approved", case["actor"]) and at is not None
    assert [(x[0], x[1], x[2], x[3]) for x in lines] == [(line["purchase_request_line_id"], f"material {i}", f"/photo-{i}", line["preferred_supplier_id"]) for i, line in enumerate(case["lines"])]
    assert len(audits) == 1 and audits[0][1:4] == ("approve", {"status": initial}, {"status": "approved", "request_no": case["number"]}) and audits[0][4]
    assert case["recipient"] in {x[1] for x in notices} and case["actor"] not in {x[1] for x in notices}


def test_late_real_item_denial_rolls_back_flushed_participants_then_retry(sessions, monkeypatch):
    case = make_case(sessions, category="accessory")
    with sessions.begin() as db:
        db.get(User, case["actor"]).extra_permissions = ["purchasing.approve", "inventory.materials_only"]
    before = state(sessions, case)
    real = core.require_purchase_item_access
    seen = []
    def flush_then_delegate(db, user, lines):
        # Instrumentation forces queued writes to database, then delegates actual access policy.
        db.flush(); audit_service._finalize_postgres_audits(db); db.flush()
        assert db.get(PurchaseRequest, case["id"]).status == "approved"
        assert db.query(AuditLog).filter_by(entity_type="PurchaseRequest", entity_id=case["id"]).count() == 1
        assert db.query(Notification).filter_by(title="Purchase request approved: " + case["number"]).count() > 0
        seen.append(True)
        return real(db, user, lines)
    with monkeypatch.context() as patch:
        patch.setattr(core, "require_purchase_item_access", flush_then_delegate)
        with sessions() as db:
            actor = db.query(User).options(joinedload(User.role)).filter_by(id=case["actor"]).one()
            db.expunge(actor)
        app = FastAPI(); app.include_router(purchasing_router)
        def request_session():
            with sessions() as db:
                yield db  # same close/rollback dependency teardown as get_db
        app.dependency_overrides[get_db] = request_session
        app.dependency_overrides[get_current_user] = lambda: actor
        with TestClient(app) as client:
            response = client.post(f"/purchasing/requests/{case['id']}/approve", json={"lines": case["lines"]})
        assert response.status_code == 403
    assert seen and state(sessions, case) == before
    with sessions.begin() as db:
        db.get(User, case["actor"]).extra_permissions = ["purchasing.approve"]
    invoke(sessions, case)
    assert_success(sessions, case)


def test_later_line_failure_rolls_back_first_line_then_retry(sessions):
    case = make_case(sessions)
    before = state(sessions, case)
    invalid = [dict(x) for x in case["lines"]]
    invalid[1]["material_name"] = "  "
    with pytest.raises(HTTPException) as exc:
        invoke(sessions, case, invalid)
    assert exc.value.status_code == 400 and state(sessions, case) == before
    invoke(sessions, case)
    assert_success(sessions, case)


def test_public_approved_retry_ignores_invalid_lines_but_enforces_late_access(sessions):
    case = make_case(sessions, category="accessory")
    invoke(sessions, case)
    approved = assert_success(sessions, case)
    invoke(sessions, case, [])
    assert state(sessions, case) == approved
    with sessions.begin() as db:
        db.get(User, case["actor"]).extra_permissions = ["purchasing.approve", "inventory.materials_only"]
    with pytest.raises(HTTPException) as exc:
        invoke(sessions, case, [])
    assert exc.value.status_code == 403 and state(sessions, case) == approved


def test_empty_request_distinct_from_missing_lines(sessions):
    empty = make_case(sessions, count=0)
    invoke(sessions, empty, [])
    assert_success(sessions, empty)
    nonempty = make_case(sessions)
    before = state(sessions, nonempty)
    with pytest.raises(HTTPException) as exc:
        invoke(sessions, nonempty, [])
    assert exc.value.status_code == 400 and state(sessions, nonempty) == before


@pytest.mark.parametrize("participant", ["apply_purchase_request_line_approval", "apply_purchase_request_approval", "log_action", "notify_department"])
def test_fault_after_real_participant_rolls_back_and_retries(sessions, monkeypatch, participant):
    case = make_case(sessions)
    before = state(sessions, case)
    original = getattr(core, participant)
    def fail_after_real(db, *args, **kwargs):
        result = original(db, *args, **kwargs)
        db.flush()
        raise RuntimeError("injected after real participant")
    with monkeypatch.context() as patch:
        patch.setattr(core, participant, fail_after_real)
        with pytest.raises(RuntimeError, match="injected"):
            invoke(sessions, case)
    assert state(sessions, case) == before
    invoke(sessions, case)
    assert_success(sessions, case)


@pytest.mark.parametrize("second_action", ["approve", "reject"])
def test_observed_row_lock_contention(sessions, monkeypatch, second_action):
    case = make_case(sessions)
    locked, release, second_started = Event(), Event(), Event()
    deadline = time.monotonic() + 20
    def remaining():
        return max(0, deadline - time.monotonic())
    original = core._locked_purchase_request
    pids = {}
    def hold_first(db, request_id):
        result = original(db, request_id)
        if not locked.is_set():
            pids["first"] = db.execute(text("select pg_backend_pid()" )).scalar_one()
            locked.set()
            assert release.wait(remaining() + 5), "release timeout"
        return result
    def first():
        invoke(sessions, case)
    def second():
        with sessions() as db:
            pids["second"] = db.execute(text("select pg_backend_pid()" )).scalar_one()
            second_started.set()
            actor = db.get(User, case["actor"])
            if second_action == "approve":
                public.approve_purchase_request(db, request_id=case["id"], payload=PurchaseRequestApprovalIn(lines=case["lines"]), current=actor)
            else:
                public.reject_purchase_request(db, request_id=case["id"], current=actor)
    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
        patch.setattr(core, "_locked_purchase_request", hold_first)
        a = pool.submit(first)
        try:
            assert locked.wait(remaining())
            b = pool.submit(second)
            assert second_started.wait(remaining())
            observed = False
            with sessions() as observer:
                while time.monotonic() < deadline:
                    row = observer.execute(text("select wait_event_type, pg_blocking_pids(pid) from pg_stat_activity where pid = :pid"), {"pid": pids["second"]}).one()
                    if row[0] == "Lock" and pids["first"] in row[1]:
                        observed = True
                        break
                    time.sleep(0.05)
            assert observed, "did not observe first backend blocking second backend"
        finally:
            release.set()
        a.result(timeout=30); b.result(timeout=30)
    result = state(sessions, case)
    assert result[0] == ("approved" if second_action == "approve" else "rejected")
    assert [x[1] for x in result[5]] == (["approve"] if second_action == "approve" else ["approve", "reject"])


def test_no_active_recipient_and_actor_exclusion(sessions):
    case = make_case(sessions, recipient=False)
    original = {}
    try:
        with sessions.begin() as db:
            dept_id = db.get(User, case["actor"]).department_id
            others = db.query(User).filter(User.department_id == dept_id, User.id != case["actor"]).all()
            assert {u.id for u in others} <= sessions.owned_user_ids, "unexpected non-fixture PLN user"
            original = {u.id: u.is_active for u in others}
            for user in others:
                user.is_active = False
            inactive = User(name="Inactive recipient", email=f"inactive-{uuid4().hex}@example.invalid", password_hash="unused", department_id=dept_id, is_active=False)
            db.add(inactive); db.flush()
            sessions.owned_user_ids.add(inactive.id)
        case["recipients"] = set()
        invoke(sessions, case)
        assert_success(sessions, case)
    finally:
        with sessions.begin() as db:
            for user_id, active in original.items():
                db.get(User, user_id).is_active = active


def test_full_audit_hash_chain(sessions):
    case = make_case(sessions)
    invoke(sessions, case)
    with sessions() as db:
        entries = db.query(AuditLog).order_by(AuditLog.id).all()
        assert any(row.entity_type == "PurchaseRequest" and row.entity_id == case["id"] for row in entries)
        previous = None
        for row in entries:
            assert row.prev_hash == previous
            assert row.entry_hash == audit_service._audit_entry_hash(prev_hash=row.prev_hash, user_id=row.user_id, action=row.action, entity_type=row.entity_type, entity_id=row.entity_id, old_value=row.old_value_json, new_value=row.new_value_json)
            previous = row.entry_hash


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong", "blank_name", "blank_photo", "supplier_zero", "supplier_absent"])
def test_invalid_payload_rolls_back_and_preserves_rows(sessions, mutation):
    case = make_case(sessions)
    before = state(sessions, case)
    lines = [dict(line) for line in case["lines"]]
    if mutation == "missing": lines.pop()
    elif mutation == "duplicate": lines[1]["purchase_request_line_id"] = lines[0]["purchase_request_line_id"]
    elif mutation == "wrong": lines[1]["purchase_request_line_id"] = -1
    elif mutation == "blank_name": lines[1]["material_name"] = "  "
    elif mutation == "blank_photo": lines[1]["photo_url"] = "  "
    elif mutation == "supplier_zero": lines[1]["preferred_supplier_id"] = 0
    else: lines[1]["preferred_supplier_id"] = -1
    with pytest.raises(HTTPException) as exc:
        invoke(sessions, case, lines)
    assert exc.value.status_code == (404 if mutation == "supplier_absent" else 400)
    assert state(sessions, case) == before


@pytest.mark.parametrize("initial", ["rejected", "converted"])
def test_invalid_status_precedes_invalid_lines(sessions, initial):
    case = make_case(sessions, status=initial)
    before = state(sessions, case)
    with pytest.raises(HTTPException) as exc:
        invoke(sessions, case, [])
    assert exc.value.status_code == 409 and state(sessions, case) == before


def test_missing_request_precedes_line_validation(sessions):
    case = make_case(sessions)
    before = state(sessions, case)
    absent = dict(case, id=-987654321)
    with pytest.raises(HTTPException) as exc:
        invoke(sessions, absent, [])
    assert exc.value.status_code == 404 and state(sessions, case) == before


def test_unknown_locked_status_stub_not_stored_pg_proof(sessions, monkeypatch):
    case = make_case(sessions)
    before = state(sessions, case)
    with monkeypatch.context() as patch:
        patch.setattr(core, "_locked_purchase_request", lambda db, request_id: type("Unknown", (), {"status": "legacy_unknown"})())
        with pytest.raises(HTTPException) as exc:
            invoke(sessions, case, [])
    assert exc.value.status_code == 409
    assert exc.value.detail == "Cannot approve purchase request in status 'legacy_unknown'"
    assert state(sessions, case) == before


def test_http_permission_denial_preserves_all_state(sessions):
    case = make_case(sessions)
    before = state(sessions, case)
    with sessions() as db:
        actor = db.query(User).options(joinedload(User.role)).filter_by(id=case["actor"]).one()
        actor.extra_permissions = ["purchasing.view"]
        db.expunge(actor)
    app = FastAPI(); app.include_router(purchasing_router)
    def request_session():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = request_session
    app.dependency_overrides[get_current_user] = lambda: actor
    with TestClient(app) as client:
        response = client.post(f"/purchasing/requests/{case['id']}/approve", json={"lines": case["lines"]})
    assert response.status_code == 403 and state(sessions, case) == before


def test_audit_finalization_failure_rollback_and_retry(sessions, monkeypatch):
    case = make_case(sessions)
    before = state(sessions, case)
    def fail(**kwargs):
        raise RuntimeError("injected hash finalization")
    with monkeypatch.context() as patch:
        patch.setattr(audit_service, "_audit_entry_hash", fail)
        with pytest.raises(RuntimeError, match="injected hash finalization"):
            invoke(sessions, case)
    assert state(sessions, case) == before
    invoke(sessions, case)
    assert_success(sessions, case)
