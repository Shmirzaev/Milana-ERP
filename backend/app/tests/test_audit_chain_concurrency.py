from concurrent.futures import ThreadPoolExecutor
import os
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import AuditLog, User
from app.services import audit
from app.services.audit import log_action, verify_audit_hash_chain


@pytest.fixture(scope="module")
def audit_chain_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL audit-chain races")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Audit-chain races require a loopback PostgreSQL URL without connection overrides")
    schema = f"audit_chain_races_{uuid4().hex}"
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


def _clear_chain(sessions):
    with sessions() as db:
        db.query(AuditLog).delete(synchronize_session=False)
        db.query(User).delete(synchronize_session=False)
        db.commit()


def _actor(sessions, marker):
    with sessions() as db:
        actor = User(
            name="Concurrent audit actor",
            email=f"audit-chain-{marker}@example.invalid",
            password_hash="test-only",
            factory_code="MIL",
            is_active=True,
        )
        db.add(actor)
        db.commit()
        return int(actor.id)


def _wait_for_blockers(connection, pids, *, required_pid=None):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        blockers = [
            connection.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}).scalar_one()
            for pid in pids
        ]
        if all(blockers) and (
            required_pid is None
            or required_pid in {pid for blocked_by in blockers for pid in blocked_by}
        ):
            return blockers
        sleep(0.02)
    pytest.fail(f"Expected PostgreSQL blockers for backends {pids}")


@pytest.mark.parametrize("seed_existing_head", [False, True])
def test_postgres_concurrent_audits_keep_one_linear_chain(
    audit_chain_postgres_sessions,
    seed_existing_head,
):
    sessions, engine = audit_chain_postgres_sessions
    _clear_chain(sessions)
    marker = uuid4().hex
    actor_id = _actor(sessions, marker)
    with sessions() as db:
        expected_head = None
        if seed_existing_head:
            seeded = log_action(
                db,
                db.get(User, actor_id),
                "seed",
                "AuditChainRace",
                0,
                new_value={"marker": marker},
            )
            db.commit()
            expected_head = seeded.entry_hash

    ready = Queue()
    start = Event()

    def append(entity_id):
        with sessions() as db:
            actor = db.get(User, actor_id)
            backend_pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            ready.put(backend_pid)
            assert start.wait(10), "Concurrent audit workers were not started"
            entry = log_action(
                db,
                actor,
                "append",
                "AuditChainRace",
                entity_id,
                new_value={"marker": marker},
            )
            db.commit()
            return int(entry.id)

    with engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
        holder.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :resource)"),
            {"namespace": audit._AUDIT_LOCK_NAMESPACE, "resource": audit._AUDIT_LOCK_RESOURCE},
        )
        futures = [workers.submit(append, entity_id) for entity_id in (1, 2)]
        try:
            worker_pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            _wait_for_blockers(holder, worker_pids, required_pid=holder_pid)
        finally:
            start.set()
            holder.rollback()
        inserted_ids = [future.result(timeout=10) for future in futures]

    with sessions() as db:
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.entity_type == "AuditChainRace")
            .order_by(AuditLog.id)
            .all()
        )
        appended = [row for row in rows if row.action == "append"]
        assert len(set(inserted_ids)) == 2
        assert [row.id for row in appended] == sorted(inserted_ids)
        assert appended[0].prev_hash == expected_head
        assert appended[1].prev_hash == appended[0].entry_hash
        assert verify_audit_hash_chain(db)["ok"] is True


def test_postgres_repeated_transaction_and_commit_flag_keep_chain_order(audit_chain_postgres_sessions):
    sessions, _engine = audit_chain_postgres_sessions
    _clear_chain(sessions)
    actor_id = _actor(sessions, uuid4().hex)
    with sessions() as db:
        actor = db.get(User, actor_id)
        first = log_action(db, actor, "first", "AuditLifecycle", 1)
        second = log_action(db, actor, "second", "AuditLifecycle", 2)
        db.commit()
        assert first.id is not None and second.id is not None
        assert second.prev_hash == first.entry_hash

        third = log_action(db, actor, "third", "AuditLifecycle", 3, commit=True)
        assert third.id is not None
        assert third.prev_hash == second.entry_hash
        assert verify_audit_hash_chain(db)["ok"] is True


def test_postgres_nested_commit_promotes_and_nested_rollback_discards(audit_chain_postgres_sessions):
    sessions, _engine = audit_chain_postgres_sessions
    _clear_chain(sessions)
    actor_id = _actor(sessions, uuid4().hex)
    with sessions() as db:
        actor = db.get(User, actor_id)
        log_action(db, actor, "outer_before", "AuditSavepoint", 1)
        with db.begin_nested():
            log_action(db, actor, "nested_kept", "AuditSavepoint", 2)
        with pytest.raises(RuntimeError, match="synthetic savepoint rollback"):
            with db.begin_nested():
                log_action(db, actor, "nested_dropped", "AuditSavepoint", 3)
                raise RuntimeError("synthetic savepoint rollback")
        log_action(db, actor, "outer_after", "AuditSavepoint", 4)
        db.commit()

        rows = db.query(AuditLog).order_by(AuditLog.id).all()
        assert [row.action for row in rows] == ["outer_before", "nested_kept", "outer_after"]
        assert verify_audit_hash_chain(db)["ok"] is True


def test_postgres_commit_with_active_savepoint_finalizes_outer_transaction(audit_chain_postgres_sessions):
    sessions, _engine = audit_chain_postgres_sessions
    _clear_chain(sessions)
    actor_id = _actor(sessions, uuid4().hex)
    with sessions() as db:
        actor = db.get(User, actor_id)
        log_action(db, actor, "outer", "AuditActiveSavepoint", 1)
        db.begin_nested()
        nested = log_action(db, actor, "nested", "AuditActiveSavepoint", 2)
        db.commit()

        assert nested.id is not None
        rows = db.query(AuditLog).order_by(AuditLog.id).all()
        assert [row.action for row in rows] == ["outer", "nested"]
        assert rows[1].prev_hash == rows[0].entry_hash
        assert verify_audit_hash_chain(db)["ok"] is True


def test_postgres_outer_savepoint_rollback_discards_committed_inner_queue(audit_chain_postgres_sessions):
    sessions, _engine = audit_chain_postgres_sessions
    _clear_chain(sessions)
    actor_id = _actor(sessions, uuid4().hex)
    with sessions() as db:
        actor = db.get(User, actor_id)
        outer_savepoint = db.begin_nested()
        log_action(db, actor, "outer_savepoint", "AuditNestedRollback", 1)
        with db.begin_nested():
            log_action(db, actor, "inner_savepoint", "AuditNestedRollback", 2)
        outer_savepoint.rollback()

        log_action(db, actor, "root_kept", "AuditNestedRollback", 3)
        db.commit()
        rows = db.query(AuditLog).order_by(AuditLog.id).all()
        assert [row.action for row in rows] == ["root_kept"]
        assert verify_audit_hash_chain(db)["ok"] is True


def test_postgres_anonymous_audit_is_transient_until_commit(audit_chain_postgres_sessions):
    sessions, _engine = audit_chain_postgres_sessions
    _clear_chain(sessions)
    with sessions() as db:
        entry = log_action(db, None, "anonymous", "AuditVisibility", 1)
        # PostgreSQL rows stay transient so audit IDs are allocated in the same
        # serialized order that the hash verifier reads them after commit.
        assert entry.id is None
        assert db.query(AuditLog).count() == 0
        db.commit()
        assert entry.id is not None
        assert db.query(AuditLog).count() == 1
        assert db.get(AuditLog, entry.id).user_id is None
        assert verify_audit_hash_chain(db)["ok"] is True


def test_postgres_outer_rollback_and_close_do_not_leak_queued_audits(audit_chain_postgres_sessions):
    sessions, _engine = audit_chain_postgres_sessions
    _clear_chain(sessions)
    actor_id = _actor(sessions, uuid4().hex)
    with sessions() as db:
        actor = db.get(User, actor_id)
        log_action(db, actor, "rolled_back", "AuditRollback", 1)
        db.rollback()
        kept = log_action(db, db.get(User, actor_id), "kept", "AuditRollback", 2)
        db.commit()
        assert kept.id is not None

    with sessions() as db:
        log_action(db, db.get(User, actor_id), "closed", "AuditRollback", 3)

    with sessions() as db:
        rows = db.query(AuditLog).order_by(AuditLog.id).all()
        assert [row.action for row in rows] == ["kept"]
        assert verify_audit_hash_chain(db)["ok"] is True


@pytest.mark.parametrize("failure_kind", ["callback", "audit_flush"])
def test_postgres_finalization_failure_rolls_back_and_session_can_be_reused(
    audit_chain_postgres_sessions,
    monkeypatch,
    failure_kind,
):
    sessions, _engine = audit_chain_postgres_sessions
    _clear_chain(sessions)
    actor_id = _actor(sessions, uuid4().hex)
    original_latest = audit._latest_entry_hash
    with sessions() as db:
        actor = db.get(User, actor_id)
        actor.name = "must roll back"
        action = "x" * 65 if failure_kind == "audit_flush" else "callback_failure"
        log_action(db, actor, action, "AuditFailure", 1)
        if failure_kind == "callback":
            monkeypatch.setattr(audit, "_latest_entry_hash", lambda _db: (_ for _ in ()).throw(RuntimeError("callback failed")))
            expected_error = RuntimeError
        else:
            expected_error = DataError
        with pytest.raises(expected_error):
            db.commit()
        db.rollback()
        monkeypatch.setattr(audit, "_latest_entry_hash", original_latest)

        actor = db.get(User, actor_id)
        assert actor.name == "Concurrent audit actor"
        actor.name = "reused session"
        log_action(db, actor, "kept_after_failure", "AuditFailure", 2)
        db.commit()

    with sessions() as db:
        assert db.get(User, actor_id).name == "reused session"
        assert [row.action for row in db.query(AuditLog).all()] == ["kept_after_failure"]
        assert verify_audit_hash_chain(db)["ok"] is True


def test_postgres_late_before_commit_audit_fails_instead_of_being_lost(audit_chain_postgres_sessions):
    sessions, _engine = audit_chain_postgres_sessions
    _clear_chain(sessions)
    actor_id = _actor(sessions, uuid4().hex)
    with sessions() as db:
        actor = db.get(User, actor_id)
        actor.name = "must roll back"
        log_action(db, actor, "normal", "AuditLateCallback", 1)
        statements = []
        late_sql_offset = []

        def capture_sql(_connection, _cursor, statement, *_args):
            statements.append(statement)

        def append_too_late(session):
            late_sql_offset.append(len(statements))
            actor.email = "must-not-flush@example.invalid"
            log_action(session, actor, "late", "AuditLateCallback", 2)

        connection = db.connection()
        event.listen(connection, "before_cursor_execute", capture_sql)
        event.listen(db, "before_commit", append_too_late)
        try:
            with pytest.raises(RuntimeError, match="audit chain was finalized"):
                db.commit()
        finally:
            event.remove(db, "before_commit", append_too_late)
            event.remove(connection, "before_cursor_execute", capture_sql)
        assert late_sql_offset and statements[late_sql_offset[0]:] == []
        db.rollback()

    with sessions() as db:
        assert db.get(User, actor_id).name == "Concurrent audit actor"
        assert db.query(AuditLog).count() == 0


def test_postgres_actor_fk_lock_precedes_audit_chain_lock(audit_chain_postgres_sessions):
    sessions, engine = audit_chain_postgres_sessions
    _clear_chain(sessions)
    actor_id = _actor(sessions, uuid4().hex)
    audit_ready = Queue()
    delete_ready = Queue()

    def append_audit():
        with sessions() as db:
            actor = db.get(User, actor_id)
            audit_ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            log_action(db, actor, "kept", "AuditUserLock", actor_id)
            db.commit()

    def delete_actor():
        with sessions() as db:
            delete_ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            try:
                db.query(User).filter(User.id == actor_id).delete(synchronize_session=False)
                db.commit()
                return "deleted"
            except IntegrityError:
                db.rollback()
                return "fk_rejected"

    with engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
        holder.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :resource)"),
            {"namespace": audit._AUDIT_LOCK_NAMESPACE, "resource": audit._AUDIT_LOCK_RESOURCE},
        )
        audit_future = workers.submit(append_audit)
        delete_future = None
        try:
            audit_pid = audit_ready.get(timeout=10)
            _wait_for_blockers(holder, [audit_pid], required_pid=holder_pid)
            delete_future = workers.submit(delete_actor)
            delete_pid = delete_ready.get(timeout=10)
            _wait_for_blockers(holder, [delete_pid], required_pid=audit_pid)
        finally:
            holder.rollback()
        audit_future.result(timeout=10)
        assert delete_future is not None
        assert delete_future.result(timeout=10) == "fk_rejected"

    with sessions() as db:
        assert db.get(User, actor_id) is not None
        assert db.query(AuditLog).filter_by(action="kept").count() == 1
        assert verify_audit_hash_chain(db)["ok"] is True
