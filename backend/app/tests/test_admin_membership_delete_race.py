"""Administrator membership deletion must preserve the final active member."""

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier, Event, Lock
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import admin
from app.db.base import Base
from app.models import User


@pytest.fixture(scope="module")
def membership_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL membership concurrency coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Membership concurrency tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"admin_membership_{uuid4().hex}"
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
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


@pytest.fixture(autouse=True)
def deactivate_membership_test_users(membership_postgres_sessions):
    yield
    with membership_postgres_sessions.begin() as db:
        db.execute(update(User).values(is_active=False))


def _create_membership_case(session_factory, wildcard_admins: int) -> tuple[int, list[int]]:
    marker = uuid4().hex
    with session_factory.begin() as db:
        actor = User(
            name="Membership super administrator",
            email=f"membership-actor-{marker}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            extra_permissions=["admin.super", "admin.users"],
            is_active=True,
        )
        targets = [
            User(
                name=f"Wildcard administrator {index}",
                email=f"membership-target-{index}-{marker}@example.invalid",
                password_hash="unused",
                factory_code="MIL",
                extra_permissions=["*"],
                is_active=True,
            )
            for index in range(wildcard_admins)
        ]
        db.add_all([actor, *targets])
        db.flush()
        return actor.id, [target.id for target in targets]


def _delete_user(session_factory, actor_id: int, target_id: int) -> tuple[int, str | None]:
    with session_factory() as db:
        try:
            admin.delete_user(target_id, db, db.get(User, actor_id))
            return 204, None
        except HTTPException as rejected:
            db.rollback()
            return rejected.status_code, rejected.detail


def test_delete_rejects_the_only_active_wildcard_administrator(membership_postgres_sessions):
    actor_id, [target_id] = _create_membership_case(membership_postgres_sessions, 1)

    result = _delete_user(membership_postgres_sessions, actor_id, target_id)

    assert result == (400, "Cannot delete the last active administrator")
    with membership_postgres_sessions() as db:
        assert db.get(User, target_id).is_active is True


def test_delete_allows_one_of_two_active_wildcard_administrators(membership_postgres_sessions):
    actor_id, target_ids = _create_membership_case(membership_postgres_sessions, 2)

    result = _delete_user(membership_postgres_sessions, actor_id, target_ids[0])

    assert result == (204, None)
    with membership_postgres_sessions() as db:
        assert db.get(User, target_ids[0]) is None
        assert db.get(User, target_ids[1]).is_active is True


def test_concurrent_deletes_preserve_one_active_wildcard_administrator(
    membership_postgres_sessions, monkeypatch,
):
    actor_id, target_ids = _create_membership_case(membership_postgres_sessions, 2)
    start = Barrier(3)
    count_lock = Lock()
    second_count_finished = Event()
    count_calls = 0
    original_count = admin._count_active_admins

    def align_pre_delete_counts(db, exclude_user_id=None):
        nonlocal count_calls
        result = original_count(db, exclude_user_id=exclude_user_id)
        with count_lock:
            count_calls += 1
            if count_calls == 2:
                second_count_finished.set()
        # Before the fix, both requests reach this point and observe the other
        # administrator. With the shared row lock, the first request times out
        # here, commits, and the waiter then observes the surviving invariant.
        second_count_finished.wait(0.5)
        return result

    monkeypatch.setattr(admin, "_count_active_admins", align_pre_delete_counts)

    def remove(target_id):
        start.wait()
        return _delete_user(membership_postgres_sessions, actor_id, target_id)

    with ThreadPoolExecutor(max_workers=2) as workers:
        deletions = [workers.submit(remove, target_id) for target_id in target_ids]
        start.wait()
        results = [deletion.result(timeout=15) for deletion in deletions]

    assert sorted(results) == [
        (204, None),
        (400, "Cannot delete the last active administrator"),
    ]
    with membership_postgres_sessions() as db:
        survivors = db.query(User).filter(User.id.in_(target_ids), User.is_active.is_(True)).all()
        assert len(survivors) == 1
