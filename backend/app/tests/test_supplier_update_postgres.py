"""Supplier PATCH on the approved identity-pinned disposable PostgreSQL target."""
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api.routes.partners import router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.libs.dto.catalog.party_input import PartyIn
from app.models import audit_service
from app.models.catalog import partners_service
from app.schemas import AuditLog, Supplier, Role, User
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def role_actor(sessions, permissions):
    with sessions.begin() as db:
        role = Role(name="Supplier update " + uuid4().hex, permissions=permissions)
        db.add(role)
        db.flush()
        user = User(name="Supplier update actor", email=f"update-{uuid4().hex}@example.invalid",
                    password_hash="unused", factory_code="MIL", role_id=role.id, is_active=True)
        db.add(user)
        db.flush()
        return user.id


def real_auth_client(sessions):
    app = FastAPI()
    app.include_router(router)
    def isolated_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = isolated_db
    return TestClient(app, raise_server_exceptions=False)


def test_pg_patch_fields_permissions_and_audit(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["storage.suppliers"])
    denied_id = role_actor(sessions, ["sales.view"])
    name = "Supplier update " + uuid4().hex
    with sessions.begin() as db:
        row = Supplier(name=name, phone="old", email="old@example.invalid", address="old", notes="old")
        db.add(row)
        db.flush()
        cid = row.id
    with real_auth_client(sessions) as client:
        assert client.patch(f"/suppliers/{cid}", json={"name": "unauthenticated"}).status_code == 401
        denied = {"Authorization": f"Bearer {create_access_token(denied_id)}"}
        assert client.patch(f"/suppliers/{cid}", headers=denied, json={"name": "denied"}).status_code == 403
        with sessions() as db:
            row = db.get(Supplier, cid)
            assert (row.name, row.phone, row.email, row.address, row.notes) == (name, "old", "old@example.invalid", "old", "old")
            assert db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=cid, action="update").count() == 0
        allowed = {"Authorization": f"Bearer {create_access_token(actor_id)}"}
        r = client.patch(f"/suppliers/{cid}", headers=allowed, json={"name": "  " + name, "phone": None, "notes": ""})
        assert r.status_code == 200, r.text
        assert (r.json()["name"], r.json()["phone"], r.json()["email"], r.json()["address"], r.json()["notes"]) == ("  " + name, None, "old@example.invalid", "old", "")
    with sessions() as db:
        row = db.get(Supplier, cid)
        assert (row.name, row.phone, row.email, row.address, row.notes) == ("  " + name, None, "old@example.invalid", "old", "")
        audits = db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=cid, action="update").all()
        assert len(audits) == 1 and audits[0].user_id == actor_id
    chain(sessions)


def test_pg_concurrent_distinct_suppliers_allow_same_name_and_chain(customer_pg_sessions):
    sessions = customer_pg_sessions
    name = "Same supplier name " + uuid4().hex
    with sessions.begin() as db:
        rows = [Supplier(name="Before A"), Supplier(name="Before B")]
        db.add_all(rows)
        db.flush()
        ids = [row.id for row in rows]
    barrier = Barrier(2)
    def worker(cid):
        with sessions() as db:
            barrier.wait(timeout=10)
            partners_service.update_supplier(None, db, cid, PartyIn(name=name))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, cid) for cid in ids]
        for future in futures:
            future.result(timeout=30)
    with sessions() as db:
        assert db.query(Supplier).filter(Supplier.id.in_(ids), Supplier.name == name).count() == 2
        assert db.query(AuditLog).filter(AuditLog.entity_type == "Supplier", AuditLog.action == "update", AuditLog.entity_id.in_(ids)).count() == 2
    chain(sessions)


def test_pg_inactive_direct_update_remains_out_of_active_list(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["storage.suppliers"])
    with sessions.begin() as db:
        row = Supplier(name="Inactive " + uuid4().hex, is_active=False, phone="old")
        db.add(row)
        db.flush()
        sid = row.id
    headers = {"Authorization": f"Bearer {create_access_token(actor_id)}"}
    with real_auth_client(sessions) as client:
        response = client.patch(f"/suppliers/{sid}", headers=headers,
                                json={"name": "Updated inactive", "phone": None, "is_active": True})
        assert response.status_code == 200, response.text
        listing = client.get("/suppliers", headers=headers)
        assert listing.status_code == 200
        assert sid not in {row["id"] for row in listing.json()}
    with sessions() as db:
        row = db.get(Supplier, sid)
        assert (row.name, row.phone, row.is_active) == ("Updated inactive", None, False)
        assert db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=sid, action="update", user_id=actor_id).count() == 1
    chain(sessions)


@pytest.mark.parametrize("point", ["audit_enqueue", "audit_finalize", "before_commit"])
def test_pg_precommit_failure_rolls_back_and_retry(customer_pg_sessions, monkeypatch, point):
    sessions = customer_pg_sessions
    name = "Supplier rollback " + uuid4().hex
    with sessions.begin() as db:
        row = Supplier(name=name, notes="keep")
        db.add(row)
        db.flush()
        cid = row.id
    original_audit = partners_service.log_action
    def fail(*args, **kwargs):
        raise RuntimeError("injected precommit failure")
    def wrapped(db, actor, action, entity_type, entity_id):
        original_audit(db, actor, action, entity_type, entity_id)
        if point == "audit_enqueue":
            fail()
        if point == "before_commit":
            event.listen(db, "before_commit", fail)
    with monkeypatch.context() as patch:
        patch.setattr(partners_service, "log_action", wrapped)
        if point == "audit_finalize":
            patch.setattr(audit_service, "add_audit_log_rows", fail)
        with sessions() as db:
            with pytest.raises(RuntimeError, match="injected precommit failure"):
                partners_service.update_supplier(None, db, cid, PartyIn(name="Changed", notes=None))
            db.rollback()
    with sessions() as db:
        assert (db.get(Supplier, cid).name, db.get(Supplier, cid).notes) == (name, "keep")
        assert db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=cid, action="update").count() == 0
    with sessions() as db:
        partners_service.update_supplier(None, db, cid, PartyIn(name="Changed", notes=None))
    with sessions() as db:
        assert (db.get(Supplier, cid).name, db.get(Supplier, cid).notes) == ("Changed", None)
        assert db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=cid, action="update").count() == 1
    chain(sessions)
