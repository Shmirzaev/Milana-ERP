from concurrent.futures import ThreadPoolExecutor
import os
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import auth
from app.core.security import hash_password, verify_password
from app.db.base import Base
from app.models import AuditLog, User
from app.tests.conftest import TestSessionLocal


ORIGINAL_PASSWORD = "ConcurrentOriginal!2026"
FIRST_PASSWORD = "ConcurrentWinnerOne!2026"
SECOND_PASSWORD = "ConcurrentWinnerTwo!2026"


def _payload(current_password, new_password):
    return auth.ChangePasswordIn(
        current_password=current_password,
        new_password=new_password,
        confirm_new_password=new_password,
    )


def test_change_password_refreshes_stale_authenticated_user():
    with TestSessionLocal() as seed:
        user = User(
            name="Stale password user",
            email=f"stale-password-{uuid4().hex}@example.com",
            password_hash=hash_password(ORIGINAL_PASSWORD),
            factory_code="MIL",
            is_active=True,
        )
        seed.add(user)
        seed.commit()
        user_id = int(user.id)

    with TestSessionLocal() as waiting:
        stale_user = waiting.get(User, user_id)
        assert verify_password(ORIGINAL_PASSWORD, stale_user.password_hash)
        with TestSessionLocal() as winner:
            assert auth.change_password(
                _payload(ORIGINAL_PASSWORD, FIRST_PASSWORD),
                winner,
                winner.get(User, user_id),
            ) == {"message": "password_updated"}

        with pytest.raises(HTTPException) as rejected:
            auth.change_password(
                _payload(ORIGINAL_PASSWORD, SECOND_PASSWORD),
                waiting,
                stale_user,
            )
        assert rejected.value.status_code == 400
        waiting.rollback()

    with TestSessionLocal() as db:
        stored = db.get(User, user_id)
        assert verify_password(FIRST_PASSWORD, stored.password_hash)
        assert not verify_password(SECOND_PASSWORD, stored.password_hash)
        assert stored.tokens_valid_from is not None


@pytest.mark.parametrize("concurrent_change", ["inactive", "deleted"])
def test_change_password_rejects_stale_inactive_or_deleted_user(concurrent_change):
    with TestSessionLocal() as seed:
        user = User(
            name="Removed password user",
            email=f"removed-password-{uuid4().hex}@example.com",
            password_hash=hash_password(ORIGINAL_PASSWORD),
            factory_code="MIL",
            is_active=True,
        )
        seed.add(user)
        seed.commit()
        user_id = int(user.id)

    with TestSessionLocal() as waiting:
        stale_user = waiting.get(User, user_id)
        with TestSessionLocal() as concurrent:
            changed_user = concurrent.get(User, user_id)
            if concurrent_change == "inactive":
                changed_user.is_active = False
            else:
                concurrent.delete(changed_user)
            concurrent.commit()

        with pytest.raises(HTTPException) as rejected:
            auth.change_password(
                _payload(ORIGINAL_PASSWORD, FIRST_PASSWORD),
                waiting,
                stale_user,
            )
        assert rejected.value.status_code == 401
        waiting.rollback()

    with TestSessionLocal() as db:
        stored = db.get(User, user_id)
        if concurrent_change == "inactive":
            assert stored is not None
            assert not stored.is_active
            assert verify_password(ORIGINAL_PASSWORD, stored.password_hash)
        else:
            assert stored is None
        assert db.query(AuditLog).filter_by(
            user_id=user_id,
            action="change_password",
        ).count() == 0


@pytest.fixture(scope="module")
def password_change_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL password-change race coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Password-change race tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"password_change_races_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4,
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


def test_postgres_same_current_password_changes_only_once(password_change_postgres_sessions):
    sessions, engine = password_change_postgres_sessions
    with sessions() as db:
        user = User(
            name="Concurrent password user",
            email=f"concurrent-password-{uuid4().hex}@example.com",
            password_hash=hash_password(ORIGINAL_PASSWORD),
            factory_code="MIL",
            is_active=True,
        )
        db.add(user)
        db.commit()
        user_id = int(user.id)

    ready = Queue()
    start = Event()

    def change(new_password):
        with sessions() as db:
            current = db.get(User, user_id)
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10), "Password-change workers were not started"
            try:
                auth.change_password(_payload(ORIGINAL_PASSWORD, new_password), db, current)
                return 200, new_password
            except HTTPException as rejected:
                db.rollback()
                return rejected.status_code, new_password

    with engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
        holder.execute(text("SELECT id FROM users WHERE id = :id FOR NO KEY UPDATE"), {"id": user_id})
        futures = [workers.submit(change, password) for password in (FIRST_PASSWORD, SECOND_PASSWORD)]
        try:
            pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            deadline = monotonic() + 10
            while monotonic() < deadline:
                blockers = [
                    holder.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}).scalar_one()
                    for pid in pids
                ]
                # PostgreSQL may queue the second FOR UPDATE waiter behind the
                # first waiter rather than name the holder as both direct blockers.
                if all(blockers) and holder_pid in {pid for blocked_by in blockers for pid in blocked_by}:
                    break
                sleep(0.02)
            else:
                pytest.fail("Both password changes must reach the same PostgreSQL user lock")
        finally:
            start.set()
            holder.rollback()
        results = [future.result(timeout=10) for future in futures]

    assert sorted(status for status, _password in results) == [200, 400]
    winning_password = next(password for status, password in results if status == 200)
    with sessions() as db:
        stored = db.get(User, user_id)
        assert verify_password(winning_password, stored.password_hash)
        assert stored.tokens_valid_from is not None
        assert db.query(AuditLog).filter_by(
            user_id=user_id,
            action="change_password",
            entity_type="User",
            entity_id=user_id,
        ).count() == 1
