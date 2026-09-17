import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import auth
from app.core.security import create_access_token, hash_password, verify_password
from app.db.base import Base
from app.models import Department, PasswordResetToken, Role, User
from app.schemas.auth import ResetPasswordIn
from app.services.password_reset import create_password_reset_token, password_reset_hash
from app.tests.conftest import TestSessionLocal


ORIGINAL_PASSWORD = "SyntheticOriginal!2026"
NEW_PASSWORD = "SyntheticReplacement!2026"


@pytest.fixture
def reset_links():
    with TestSessionLocal() as db:
        user = User(
            name="Reset user", email="reset-user@example.com",
            password_hash=hash_password(ORIGINAL_PASSWORD),
            factory_code="MIL", extra_permissions=[], is_active=True,
        )
        db.add(user)
        db.flush()
        links = [create_password_reset_token(db, user) for _ in range(2)]
        db.commit()
        return user.id, links


def _payload(token, password=NEW_PASSWORD):
    return {"token": token, "new_password": password, "confirm_new_password": password}


@pytest.mark.parametrize("chosen", [0, 1])
def test_successful_reset_revokes_all_siblings_and_old_sessions(client, reset_links, chosen):
    user_id, links = reset_links
    old_session = create_access_token(
        user_id, extra={"iat": int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())},
    )
    headers = {"Authorization": f"Bearer {old_session}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    with TestSessionLocal() as db:
        other = User(
            name="Other reset user", email="other-reset@example.com",
            password_hash=hash_password(ORIGINAL_PASSWORD), is_active=True,
        )
        db.add(other)
        db.flush()
        other_link = create_password_reset_token(db, other)
        db.commit()

    response = client.post("/api/auth/reset-password", json=_payload(links[chosen]))
    assert response.status_code == 200, response.text
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    for token in links:
        reused = client.post("/api/auth/reset-password", json=_payload(token, "AnotherPassword!2026"))
        assert reused.status_code == 400, reused.text

    with TestSessionLocal() as db:
        tokens = db.query(PasswordResetToken).filter_by(user_id=user_id).all()
        assert all(token.used_at is not None for token in tokens)
        assert len({token.used_at for token in tokens}) == 1
        user = db.get(User, user_id)
        assert verify_password(NEW_PASSWORD, user.password_hash)
        assert user.tokens_valid_from is not None
        other_token = db.query(PasswordResetToken).filter_by(token_hash=password_reset_hash(other_link)).one()
        assert other_token.used_at is None

    login = client.post(
        "/api/auth/login-json",
        json={"email": "reset-user@example.com", "password": NEW_PASSWORD, "factory_code": "MIL"},
    )
    assert login.status_code == 200, login.text
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/reset-password", json=_payload(other_link)).status_code == 200


@pytest.mark.parametrize("failure", ["unknown_token", "weak_password", "password_mismatch"])
def test_rejected_reset_keeps_outstanding_links_usable(client, reset_links, failure):
    user_id, links = reset_links
    payload = _payload(links[0])
    if failure == "unknown_token":
        payload["token"] = "not-a-real-reset-token"
    elif failure == "weak_password":
        payload = _payload(links[0], "weak")
    else:
        payload["confirm_new_password"] = "MismatchedPassword!2026"
    assert client.post("/api/auth/reset-password", json=payload).status_code == 400

    with TestSessionLocal() as db:
        assert all(token.used_at is None for token in db.query(PasswordResetToken).filter_by(user_id=user_id))
        user = db.get(User, user_id)
        assert verify_password(ORIGINAL_PASSWORD, user.password_hash)
        assert user.tokens_valid_from is None
    assert client.post("/api/auth/reset-password", json=_payload(links[0])).status_code == 200


def test_reset_reloads_token_after_another_session_consumes_sibling(reset_links):
    user_id, links = reset_links
    with TestSessionLocal() as waiting:
        stale_token = waiting.query(PasswordResetToken).filter_by(token_hash=password_reset_hash(links[1])).one()
        assert stale_token.used_at is None
        with TestSessionLocal() as winner:
            auth.reset_password(ResetPasswordIn(**_payload(links[0])), winner)

        with pytest.raises(HTTPException) as rejected:
            auth.reset_password(ResetPasswordIn(**_payload(links[1], "LosingPassword!2026")), waiting)
        assert rejected.value.status_code == 400
        waiting.rollback()
    with TestSessionLocal() as db:
        assert verify_password(NEW_PASSWORD, db.get(User, user_id).password_hash)


@pytest.mark.parametrize("path", ["self_service", "administrator"])
def test_other_password_changes_revoke_outstanding_reset_links(client, reset_links, auth_headers, path):
    user_id, links = reset_links
    if path == "self_service":
        response = client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {create_access_token(user_id)}"},
            json={"current_password": ORIGINAL_PASSWORD, "new_password": NEW_PASSWORD,
                  "confirm_new_password": NEW_PASSWORD},
        )
    else:
        response = client.patch(
            f"/api/users/{user_id}", headers=auth_headers, json={"password": NEW_PASSWORD},
        )
    assert response.status_code == 200, response.text
    for token in links:
        assert client.post("/api/auth/reset-password", json=_payload(token)).status_code == 400
    with TestSessionLocal() as db:
        assert verify_password(NEW_PASSWORD, db.get(User, user_id).password_hash)
        assert all(token.used_at is not None for token in db.query(PasswordResetToken).filter_by(user_id=user_id))


@pytest.mark.parametrize("failure", ["expired", "inactive"])
def test_expired_or_inactive_reset_cannot_mutate_password(client, reset_links, failure):
    user_id, links = reset_links
    with TestSessionLocal() as db:
        if failure == "expired":
            db.query(PasswordResetToken).filter_by(user_id=user_id).update(
                {PasswordResetToken.expires_at: datetime.now(timezone.utc) - timedelta(minutes=1)},
            )
        else:
            db.get(User, user_id).is_active = False
        db.commit()
    assert client.post("/api/auth/reset-password", json=_payload(links[0])).status_code == 400
    with TestSessionLocal() as db:
        assert verify_password(ORIGINAL_PASSWORD, db.get(User, user_id).password_hash)
        assert all(token.used_at is None for token in db.query(PasswordResetToken).filter_by(user_id=user_id))


def test_reset_locks_user_before_refreshing_and_consuming_token(reset_links):
    _, links = reset_links
    observed = []
    with TestSessionLocal() as db:
        def observe(orm):
            if not orm.is_select:
                return
            statement = orm.statement
            sql = str(statement.compile(dialect=postgresql.dialect()))
            if "FOR UPDATE OF users" in sql:
                assert orm.load_options._populate_existing
                observed.append("user_lock")
            elif statement.column_descriptions[0]["expr"] is PasswordResetToken:
                assert observed == ["user_lock"]
                assert orm.load_options._populate_existing
                observed.append("token_recheck")

        event.listen(db, "do_orm_execute", observe)
        auth.reset_password(ResetPasswordIn(**_payload(links[0])), db)
    # SQLite does not implement row locks; this checks emitted PostgreSQL SQL/order only.
    assert observed == ["user_lock", "token_recheck"]


def test_failed_commit_rolls_back_password_and_all_token_changes(reset_links, monkeypatch):
    user_id, links = reset_links
    with TestSessionLocal() as db:
        def fail_commit():
            db.flush()
            raise RuntimeError("synthetic commit failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            auth.reset_password(ResetPasswordIn(**_payload(links[0])), db)
        db.rollback()

    with TestSessionLocal() as db:
        user = db.get(User, user_id)
        assert verify_password(ORIGINAL_PASSWORD, user.password_hash)
        assert user.tokens_valid_from is None
        assert all(token.used_at is None for token in db.query(PasswordResetToken).filter_by(user_id=user_id))
        assert auth.reset_password(ResetPasswordIn(**_payload(links[1])), db) == {"message": "password_reset"}


@pytest.fixture(scope="module")
def reset_postgres_engine():
    """Opt in through the disposable cluster launcher; never use the app DB URL."""
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL reset concurrency coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Reset concurrency tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"reset_revocation_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(
            engine, tables=[Role.__table__, Department.__table__, User.__table__, PasswordResetToken.__table__],
        )
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def test_postgres_concurrent_sibling_resets_only_one_changes_password(reset_postgres_engine):
    engine = reset_postgres_engine
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_factory() as db:
        user = User(
            name="Concurrent reset", email="concurrent-reset@example.com",
            password_hash=hash_password(ORIGINAL_PASSWORD), is_active=True,
        )
        db.add(user)
        db.flush()
        links = [create_password_reset_token(db, user) for _ in range(2)]
        db.commit()
        user_id = user.id

    ready = Queue()
    start = Event()

    def reset(index):
        password = f"ConcurrentReplacement{index}!2026"
        with session_factory() as db:
            # Keep a stale identity-map entry as well as two real transactions.
            cached = db.query(PasswordResetToken).filter_by(token_hash=password_reset_hash(links[index])).one()
            assert cached.used_at is None
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10), "Reset workers were not started"
            try:
                auth.reset_password(ResetPasswordIn(**_payload(links[index], password)), db)
                return 200, password
            except HTTPException as rejected:
                db.rollback()
                return rejected.status_code, password

    with engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        # The old implementation waits only when flushing the password change;
        # the fixed implementation must wait before validating either token.
        holder.execute(text("SELECT id FROM users WHERE id = :id FOR NO KEY UPDATE"), {"id": user_id})
        futures = [workers.submit(reset, index) for index in range(2)]
        try:
            pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if all(
                    bool(holder.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}).scalar_one())
                    for pid in pids
                ):
                    break
                sleep(0.02)
            else:
                pytest.fail("Both reset transactions must reach an actual PostgreSQL lock wait")
        finally:
            start.set()
            holder.rollback()
        results = [future.result(timeout=10) for future in futures]

    assert sorted(status for status, _ in results) == [200, 400]
    winning_password = next(password for status, password in results if status == 200)
    with session_factory() as db:
        user = db.get(User, user_id)
        assert verify_password(winning_password, user.password_hash)
        assert user.tokens_valid_from is not None
        tokens = db.query(PasswordResetToken).filter_by(user_id=user_id).all()
        assert all(token.used_at is not None for token in tokens)
        assert len({token.used_at for token in tokens}) == 1
