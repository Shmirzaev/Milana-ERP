"""PostgreSQL qualification for initial process QR size setup."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.libs.dto.catalog.process_qr_sizes_input import ProcessQrSizesIn
from app.models.catalog import models_service
from app.schemas import AuditLog, ModelSize, User

pytest_plugins = ("app.tests.test_modelcolor_create_postgres",)


def _read(db, mid):
    sizes = db.scalars(select(ModelSize.size).where(ModelSize.model_id == mid).order_by(ModelSize.id)).all()
    audits = db.scalars(select(AuditLog).where(AuditLog.action == "process_qr_sizes_added", AuditLog.entity_id == mid)).all()
    return sizes, audits


def test_postgres_setup_audit_failure_rolls_back(pg_sessions, pg_case, monkeypatch):
    mid = pg_case["models"]["standard"]
    actor_id = pg_case["actors"]["standard"]
    def fail(*args, **kwargs):
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(models_service, "log_action", fail)
    with pg_sessions() as db:
        with pytest.raises(RuntimeError, match="injected audit failure"):
            models_service.add_process_qr_model_sizes(db.get(User, actor_id), db, mid, ProcessQrSizesIn(sizes=["48", "50"]))
        db.rollback()
    with pg_sessions() as db:
        assert _read(db, mid) == ([], [])


def test_postgres_simultaneous_setup_serializes(pg_sessions, pg_case):
    mid = pg_case["models"]["standard"]
    actor_id = pg_case["actors"]["standard"]
    barrier = Barrier(2, timeout=15)
    def setup(sizes):
        with pg_sessions() as db:
            actor = db.get(User, actor_id)
            barrier.wait()
            try:
                models_service.add_process_qr_model_sizes(actor, db, mid, ProcessQrSizesIn(sizes=sizes))
                return 201
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(setup, sizes) for sizes in (["48", "50"], ["52", "54"])]
        results = [future.result(timeout=40) for future in futures]
    assert sorted(results) == [201, 409]
    with pg_sessions() as db:
        sizes, audits = _read(db, mid)
        assert sizes in (["48", "50"], ["52", "54"])
        assert len(audits) == 1
        assert audits[0].new_value_json == {"sizes": sizes}


def test_postgres_setup_then_generic_writer_waits_on_parent_fk(pg_sessions, pg_case, monkeypatch):
    """Characterize the FK lock: generic insert can add another row after setup."""
    from threading import Event
    from time import monotonic, sleep
    from sqlalchemy import event, text
    from app.libs.dto.catalog.model_size_input import ModelSizeIn

    mid = pg_case["models"]["standard"]
    actor_id = pg_case["actors"]["standard"]
    locked, release, inserting = Event(), Event(), Event()
    pids = {}
    original = models_service.add_initial_model_sizes

    def pause_after_parent_lock(db, model_id, sizes):
        pids["setup"] = db.scalar(text("select pg_backend_pid()"))
        locked.set()
        assert release.wait(20)
        original(db, model_id, sizes)

    monkeypatch.setattr(models_service, "add_initial_model_sizes", pause_after_parent_lock)

    def setup():
        with pg_sessions() as db:
            return models_service.add_process_qr_model_sizes(db.get(User, actor_id), db, mid, ProcessQrSizesIn(sizes=["48"]))

    def generic():
        with pg_sessions() as db:
            actor = db.get(User, actor_id)
            pids["generic"] = db.scalar(text("select pg_backend_pid()"))
            def before_execute(conn, cursor, statement, parameters, context, executemany):
                if statement.lstrip().lower().startswith("insert into model_sizes"):
                    inserting.set()
            event.listen(db.connection(), "before_cursor_execute", before_execute)
            return models_service.add_size(actor, db, mid, ModelSizeIn(size="48"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(setup)
        try:
            assert locked.wait(10)
            second = pool.submit(generic)
            assert inserting.wait(10)
            deadline = monotonic() + 10
            blocked = False
            while monotonic() < deadline:
                with pg_sessions() as observer:
                    blocked = pids["setup"] in observer.scalar(text("select pg_blocking_pids(:pid)"), {"pid": pids["generic"]})
                if blocked:
                    break
                sleep(0.05)
            assert blocked, "generic insert did not reach a parent-lock wait"
            with pg_sessions() as observer:
                assert _read(observer, mid) == ([], [])
        finally:
            release.set()
        assert first.result(timeout=30)["sizes"] == ["48"]
        result = second.result(timeout=30)
    with pg_sessions() as db:
        sizes, audits = _read(db, mid)
        assert sizes == ["48", "48"]
        assert db.get(ModelSize, result["id"]).model_id == mid
        assert len(audits) == 1 and audits[0].new_value_json == {"sizes": ["48"]}


@pytest.mark.parametrize("fault", ["after_flush", "audit_finalize", "before_commit"])
def test_postgres_http_failure_teardown_rolls_back(pg_sessions, pg_case, pg_app, monkeypatch, fault):
    from fastapi.testclient import TestClient
    from sqlalchemy import event
    from app.api.routes import process_qr_setup
    from app.core.deps import get_db
    from app.models import audit_service

    mid = pg_case["models"]["standard"]
    observed = []
    pg_app.include_router(process_qr_setup.router, prefix="/api")

    def fail(*args, **kwargs):
        observed.append("fault")
        raise RuntimeError("injected request failure")

    def request_session():
        with pg_sessions() as db:
            def before_commit(session):
                if fault == "after_flush":
                    session.flush()
                    observed.append("flushed")
                    fail()
                if fault == "before_commit":
                    fail()
            event.listen(db, "before_commit", before_commit)
            yield db

    pg_app.dependency_overrides[get_db] = request_session
    if fault == "audit_finalize":
        original_add = audit_service.add_audit_log_rows
        def fail_after_audit_flush(db, entries):
            original_add(db, entries)
            db.flush()
            observed.append("audit_flushed")
            fail()
        monkeypatch.setattr(audit_service, "add_audit_log_rows", fail_after_audit_flush)
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        response = client.post(f"/api/models/{mid}/process-qr-sizes", json={"sizes": ["48", "50"]})
    assert response.status_code == 500
    assert "fault" in observed
    if fault == "after_flush":
        assert "flushed" in observed
    if fault == "audit_finalize":
        assert "audit_flushed" in observed
    with pg_sessions() as db:
        assert _read(db, mid) == ([], [])
