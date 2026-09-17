"""Account removal must preserve historical audit identities and hash chains."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from threading import Event
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api.routes import admin
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import AuditLog, Employee, Notification, PasswordResetToken, User
from app.services.audit import export_audit_hash_chain, log_action, verify_audit_hash_chain


def _create_target(*, active=True, session_factory=SessionLocal):
    with session_factory() as db:
        user = User(
            name="Audit history account",
            email=f"audit-history-{uuid4().hex}@example.invalid",
            password_hash="unused-by-synthetic-token-test",
            factory_code="MIL",
            is_active=active,
        )
        db.add(user)
        db.flush()
        employee = Employee(user_id=user.id, full_name="Preserved audit employee")
        notification = Notification(user_id=user.id, title="Account notification")
        reset_token = PasswordResetToken(
            user_id=user.id,
            token_hash=uuid4().hex,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add_all([employee, notification, reset_token])
        db.commit()
        return user.id, [(User, user.id), (Employee, employee.id),
                         (Notification, notification.id), (PasswordResetToken, reset_token.id)]


def _snapshot(references, session_factory=SessionLocal):
    with session_factory() as db:
        rows = {}
        for model, row_id in references:
            row = db.get(model, row_id)
            rows[model.__tablename__] = (
                {column.name: getattr(row, column.name) for column in model.__table__.columns}
                if row else None
            )
        rows["audit_history"] = export_audit_hash_chain(db, limit=5000)
        return rows


@pytest.mark.parametrize("active", [True, False])
@pytest.mark.parametrize("hashed", [True, False])
def test_delete_user_with_audit_history_preserves_all_references(client, auth_headers, active, hashed):
    user_id, references = _create_target(active=active)
    with SessionLocal() as db:
        if hashed:
            entry = log_action(db, db.get(User, user_id), "update", "AuditHistory", 1,
                               old_value={"status": "waiting"}, new_value={"status": "done"})
        else:
            entry = AuditLog(user_id=user_id, action="login", entity_type="User", entity_id=user_id)
            db.add(entry)
        db.commit()
        entry_id = entry.id
        if hashed:
            assert verify_audit_hash_chain(db, start_id=entry_id)["ok"]
        engine = db.get_bind()
    before = _snapshot(references)
    writes = []

    def capture_write(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", capture_write)
    try:
        response = client.delete(f"/api/users/{user_id}", headers=auth_headers)
    finally:
        event.remove(engine, "before_cursor_execute", capture_write)

    with SessionLocal() as db:
        chain = verify_audit_hash_chain(db, start_id=entry_id) if hashed else None
        stored_actor = db.get(AuditLog, entry_id).user_id
    assert response.status_code == 409, (response.text, stored_actor, chain)
    assert response.json()["detail"] == "User has audit history. Deactivate the account instead."
    assert writes == [], "Reject deletion before mutating any linked records"
    assert _snapshot(references) == before
    if hashed:
        assert chain["ok"] is True


def test_user_with_audit_history_can_be_deactivated(client, auth_headers):
    user_id, references = _create_target()
    headers = {"Authorization": f"Bearer {create_access_token(user_id, {'factory_code': 'MIL'})}"}
    with SessionLocal() as db:
        entry = log_action(db, db.get(User, user_id), "login", "User", user_id)
        db.commit()
        entry_id = entry.id
        before = export_audit_hash_chain(db, start_id=entry_id)

    response = client.patch(f"/api/users/{user_id}", json={"is_active": False}, headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    with SessionLocal() as db:
        assert db.get(User, user_id).is_active is False
        for model, row_id in references[1:]:
            assert db.get(model, row_id).user_id == user_id
        after = export_audit_hash_chain(db, start_id=entry_id)
        assert after[:-1] == before
        assert after[-1]["action"] == "update"
        assert after[-1]["entity_id"] == user_id
        assert verify_audit_hash_chain(db, start_id=entry_id)["ok"] is True


def test_delete_unused_user_keeps_other_users_audit_history(client, auth_headers):
    user_id, references = _create_target()
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        entry = log_action(db, actor, "create", "User", user_id)
        db.commit()
        entry_id = entry.id
        before = export_audit_hash_chain(db, start_id=entry_id)

    response = client.delete(f"/api/users/{user_id}", headers=auth_headers)

    assert response.status_code == 204, response.text
    with SessionLocal() as db:
        assert db.get(User, user_id) is None
        assert db.get(Employee, references[1][1]).user_id is None
        assert db.get(Notification, references[2][1]) is None
        assert db.get(PasswordResetToken, references[3][1]) is None
        after = export_audit_hash_chain(db, start_id=entry_id)
        assert after[:-1] == before
        assert after[-1]["action"] == "delete"
        assert after[-1]["entity_id"] == user_id
        assert verify_audit_hash_chain(db, start_id=entry_id)["ok"] is True


@pytest.mark.parametrize("error_kind", ["runtime", "integrity"])
def test_failed_user_delete_rolls_back_reference_cleanup_and_audit(client, auth_headers, monkeypatch, error_kind):
    user_id, references = _create_target()
    before = _snapshot(references)
    original_log_action = admin.log_action
    error = (RuntimeError("synthetic deletion failure after audit flush") if error_kind == "runtime"
             else IntegrityError("synthetic deletion failure", {}, ValueError("unrelated constraint")))

    def fail_after_audit_flush(*args, **kwargs):
        original_log_action(*args, **kwargs)
        raise error

    monkeypatch.setattr(admin, "log_action", fail_after_audit_flush)
    with pytest.raises(type(error), match="synthetic deletion failure"):
        client.delete(f"/api/users/{user_id}", headers=auth_headers)

    assert _snapshot(references) == before


def test_reference_cleanup_never_rewrites_audit_actors():
    """A history row appearing after the API guard must remain FK-protected."""
    user_id, _ = _create_target()
    with SessionLocal() as db:
        entry = log_action(db, db.get(User, user_id), "login", "User", user_id)
        db.commit()
        entry_id = entry.id
        before = export_audit_hash_chain(db, start_id=entry_id)

        admin._detach_user_references(db, user_id)
        db.expire_all()

        assert export_audit_hash_chain(db, start_id=entry_id) == before
        assert verify_audit_hash_chain(db, start_id=entry_id)["ok"] is True
        db.rollback()


@pytest.fixture(scope="module")
def user_history_postgres_engine():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL user-history concurrency coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("User-history concurrency tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"user_history_{uuid4().hex}"
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4, max_overflow=0, isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        # User cleanup intentionally examines all registered FK tables.
        Base.metadata.create_all(engine)
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def test_postgres_audit_committed_after_delete_guard_preserves_history(user_history_postgres_engine, monkeypatch):
    session_factory = sessionmaker(bind=user_history_postgres_engine, autoflush=False, expire_on_commit=False)
    user_id, references = _create_target(session_factory=session_factory)
    with session_factory() as db:
        actor = User(name="History manager", email="history-manager@example.invalid",
                     password_hash="unused", factory_code="MIL", extra_permissions=["admin.users"])
        db.add(actor)
        db.commit()
        actor_id = actor.id
    guard_passed = Event()
    audit_committed = Event()
    original_detach = admin._detach_user_references

    def detach_after_concurrent_audit(db, target_id):
        guard_passed.set()
        assert audit_committed.wait(10), "Concurrent audit did not commit"
        original_detach(db, target_id)

    monkeypatch.setattr(admin, "_detach_user_references", detach_after_concurrent_audit)

    def remove_user():
        with session_factory() as db:
            try:
                admin.delete_user(user_id, db, db.get(User, actor_id))
                return 204
            except HTTPException as rejected:
                assert rejected.detail == "User has audit history. Deactivate the account instead."
                return rejected.status_code

    with ThreadPoolExecutor(max_workers=1) as workers:
        deletion = workers.submit(remove_user)
        try:
            assert guard_passed.wait(10), "Deletion did not reach reference cleanup"
            with session_factory() as db:
                entry = log_action(db, db.get(User, user_id), "login", "User", user_id)
                db.commit()
                entry_id = entry.id
            before = _snapshot(references, session_factory)
        finally:
            audit_committed.set()
        assert deletion.result(timeout=15) == 409

    assert _snapshot(references, session_factory) == before
    with session_factory() as db:
        assert db.get(AuditLog, entry_id).user_id == user_id
        assert verify_audit_hash_chain(db, start_id=entry_id)["ok"] is True
        assert db.query(AuditLog).filter_by(action="delete", entity_type="User", entity_id=user_id).count() == 0
