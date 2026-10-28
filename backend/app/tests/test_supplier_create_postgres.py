from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import hashlib
import json

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import object_session, sessionmaker

from app.api.routes.partners import router
from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.libs.dto.catalog.party_input import PartyIn
from app.models import audit_service
from app.models.catalog import partners_service
from app.schemas import AuditLog, Supplier, User
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, owned_target_name, preflight_connection,
    require_or_skip, target_engine,
)


@pytest.fixture(scope="module")
def supplier_pg_sessions():
    test_path = Path(__file__).resolve()
    backend = test_path.parents[2]
    if test_path.parent.name != "tests" or test_path.parent.parent.name != "app":
        raise RuntimeError("Place test under backend/app/tests before execution")
    ini = backend / "alembic.ini"
    if not ini.is_file():
        raise RuntimeError("Candidate backend/alembic.ini not found")
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    target_name = owned_target_name(target)
    engine = None
    sessions = sessionmaker(autoflush=False, expire_on_commit=False)
    try:
        engine = target_engine(target, options="-c statement_timeout=20000 -c lock_timeout=10000")
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(settings, "DATABASE_URL", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
            patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
            command.upgrade(Config(str(ini)), "head")
        sessions.configure(bind=engine)
        yield sessions
    finally:
        try:
            sessions.configure(bind=None)
        finally:
            finalize_target(target, engine)
            admin = sa.create_engine(instance.admin_url, connect_args={"connect_timeout": 5}, future=True)
            try:
                with admin.connect() as connection:
                    connection.execute(sa.text("SET TRANSACTION READ ONLY"))
                    preflight_connection(connection, instance, "postgres")
                    assert not connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = :name)"), {"name": target_name}).scalar_one()
            finally:
                admin.dispose()


def actor(sessions, permissions):
    with sessions.begin() as db:
        user = User(name="Supplier PG actor", email=f"supplier-{uuid4().hex}@example.invalid", password_hash="unused", factory_code="MIL", extra_permissions=permissions, is_active=True)
        db.add(user)
        db.flush()
        return user.id


def client_for(sessions, actor_id=None):
    app = FastAPI()
    app.include_router(router)
    def isolated_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = isolated_db
    if actor_id is not None:
        def current():
            with sessions() as db:
                user = db.get(User, actor_id)
                db.expunge(user)
                return user
        app.dependency_overrides[get_current_user] = current
    return TestClient(app, raise_server_exceptions=False)


def chain(sessions):
    with sessions() as db:
        entries = db.query(AuditLog).order_by(AuditLog.id).all()
        previous = None
        for entry in entries:
            payload = dict(prev_hash=previous, user_id=entry.user_id, action=entry.action, entity_type=entry.entity_type, entity_id=entry.entity_id, old_value=entry.old_value_json, new_value=entry.new_value_json)
            expected = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
            assert entry.prev_hash == previous and entry.entry_hash == expected
            previous = expected


def test_pg_route_saves_all_fields_and_audit_same_session(supplier_pg_sessions, monkeypatch):
    sessions = supplier_pg_sessions
    actor_id = actor(sessions, ["storage.suppliers"])
    fields = dict(name="Supplier " + uuid4().hex, phone="+998 90 123 45 67", email="supplier@example.invalid", address="Factory road", notes="Route create")
    seen = []
    insert = partners_service.insert_supplier
    audit = partners_service.log_action
    def observe_insert(db, **values):
        row = insert(db, **values)
        assert row.id is not None and object_session(row) is db
        seen.append(db)
        return row
    def observe_audit(db, *args, **kwargs):
        assert seen == [db]
        return audit(db, *args, **kwargs)
    monkeypatch.setattr(partners_service, "insert_supplier", observe_insert)
    monkeypatch.setattr(partners_service, "log_action", observe_audit)
    with client_for(sessions, actor_id) as client:
        response = client.post("/suppliers", json=fields)
    assert response.status_code == 201, response.text
    result = response.json()
    assert {key: result[key] for key in fields} == fields
    with sessions() as db:
        saved = db.get(Supplier, result["id"])
        assert {key: getattr(saved, key) for key in fields} == fields
        rows = db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=saved.id, action="create").all()
        assert len(rows) == 1 and rows[0].user_id == actor_id
    chain(sessions)


def test_pg_route_refuses_unauthenticated_and_forbidden_without_writes(supplier_pg_sessions):
    sessions = supplier_pg_sessions
    name = "Denied " + uuid4().hex
    with client_for(sessions) as client:
        assert client.post("/suppliers", json={"name": name}).status_code == 401
    actor_id = actor(sessions, ["sales.view"])
    with client_for(sessions, actor_id) as client:
        assert client.post("/suppliers", json={"name": name}).status_code == 403
    with sessions() as db:
        assert db.query(Supplier).filter_by(name=name).count() == 0
        assert db.query(AuditLog).filter_by(user_id=actor_id, entity_type="Supplier").count() == 0


@pytest.mark.parametrize("point", ["audit_enqueue", "audit_finalize", "commit"])
def test_pg_route_failure_rolls_back_then_retry(supplier_pg_sessions, monkeypatch, point):
    sessions = supplier_pg_sessions
    actor_id = actor(sessions, ["storage.suppliers"])
    name = "Retry " + uuid4().hex
    attempted = []
    original = partners_service.log_action
    def fail(*args, **kwargs):
        raise RuntimeError("injected supplier failure")
    def wrapped(db, user, action, entity_type, entity_id):
        attempted.append(entity_id)
        original(db, user, action, entity_type, entity_id)
        if point == "audit_enqueue":
            fail()
        if point == "commit":
            event.listen(db, "before_commit", fail)
    with monkeypatch.context() as patch:
        patch.setattr(partners_service, "log_action", wrapped)
        if point == "audit_finalize":
            patch.setattr(audit_service, "_audit_entry_hash", fail)
        with client_for(sessions, actor_id) as client:
            assert client.post("/suppliers", json={"name": name}).status_code == 500
    assert len(attempted) == 1
    with sessions() as db:
        assert db.query(Supplier).filter_by(name=name).count() == 0
        assert db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=attempted[0]).count() == 0
    with client_for(sessions, actor_id) as client:
        response = client.post("/suppliers", json={"name": name})
    assert response.status_code == 201, response.text
    with sessions() as db:
        saved = db.get(Supplier, response.json()["id"])
        assert saved.name == name and all(getattr(saved, key) is None for key in ("phone", "email", "address", "notes"))
        assert db.query(Supplier).filter_by(name=name).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=saved.id, action="create", user_id=actor_id).count() == 1
    chain(sessions)


def test_pg_concurrent_suppliers_keep_audit_chain(supplier_pg_sessions):
    sessions = supplier_pg_sessions
    actor_id = actor(sessions, ["storage.suppliers"])
    name = "Concurrent " + uuid4().hex
    barrier = Barrier(4)
    def worker(index):
        with sessions() as db:
            user = db.get(User, actor_id)
            barrier.wait(timeout=10)
            return partners_service.create_supplier(user, db, PartyIn(name=name if index < 2 else f"{name}-{index}")).id
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker, index) for index in range(4)]
        ids = [future.result(timeout=30) for future in futures]
    assert len(set(ids)) == 4
    with sessions() as db:
        assert db.query(Supplier).filter(Supplier.id.in_(ids)).count() == 4
        rows = db.query(AuditLog).filter(AuditLog.entity_type == "Supplier", AuditLog.entity_id.in_(ids), AuditLog.action == "create").all()
        assert len(rows) == 4 and {row.entity_id for row in rows} == set(ids)
        assert all(row.user_id == actor_id for row in rows)
    chain(sessions)


def test_pg_create_preserves_raw_fields_duplicates_and_validation(supplier_pg_sessions):
    sessions = supplier_pg_sessions
    actor_id = actor(sessions, ["storage.suppliers"])
    name = "  Supplier " + uuid4().hex + "  "
    fields = {"name": name, "phone": "", "email": None, "address": "  road  ", "notes": ""}
    with client_for(sessions, actor_id) as client:
        first = client.post("/suppliers", json=fields)
        second = client.post("/suppliers", json=fields)
        missing = client.post("/suppliers", json={})
        too_long = client.post("/suppliers", json={"name": "x" * 256})
    assert first.status_code == second.status_code == 201
    assert missing.status_code == too_long.status_code == 422
    assert first.json()["id"] != second.json()["id"]
    for response in (first, second):
        assert {key: response.json()[key] for key in fields} == fields
    with sessions() as db:
        rows = db.query(Supplier).filter_by(name=name).all()
        assert len(rows) == 2 and all(row.is_active for row in rows)
        assert all({key: getattr(row, key) for key in fields} == fields for row in rows)
        assert db.query(AuditLog).filter(AuditLog.entity_type == "Supplier", AuditLog.entity_id.in_([row.id for row in rows]), AuditLog.action == "create").count() == 2
    chain(sessions)
