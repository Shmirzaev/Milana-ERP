"""PostgreSQL request rollback and concurrent image deletion characterization."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from app.core.deps import get_db
from app.models import audit_service
from app.models.catalog import models_service
from app.schemas import AuditLog, ModelImage, User

pytest_plugins = ("app.tests.test_modelcolor_create_postgres",)


def _image(sessions, mid):
    with sessions.begin() as db:
        row = ModelImage(model_id=mid, file_url="/old.png", file_data=b"old binary")
        db.add(row)
        db.flush()
        return row.id


def _read(sessions, image_id):
    with sessions() as db:
        row = db.get(ModelImage, image_id)
        image = None if row is None else (row.model_id, row.file_url, row.file_data)
        audits = db.scalars(select(AuditLog).where(AuditLog.entity_type == "ModelImage", AuditLog.entity_id == image_id)).all()
        return image, [(a.action, a.new_value_json) for a in audits]


def test_pg_denied_usluga_and_reverse_scope_keep_binary(pg_sessions, pg_case, pg_app):
    standard, eco = pg_case["models"]["standard"], pg_case["models"]["usluga"]
    image_id = _image(pg_sessions, standard)
    eco_id = _image(pg_sessions, eco)
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        assert client.delete(f"/api/usluga/models/{eco}/images/{eco_id}", headers={"X-Actor": "denied"}).status_code == 403
        assert client.delete(f"/api/usluga/models/{standard}/images/{image_id}", headers={"X-Actor": "eco"}).status_code == 404
        assert client.delete(f"/api/models/{eco}/images/{eco_id}", headers={"X-Actor": "standard"}).status_code == 404
    assert _read(pg_sessions, image_id) == ((standard, "/old.png", b"old binary"), [])
    assert _read(pg_sessions, eco_id) == ((eco, "/old.png", b"old binary"), [])


@pytest.mark.parametrize("fault", ["after_audit_flush", "before_commit"])
def test_pg_request_failure_rolls_back_binary_and_audit(pg_sessions, pg_case, pg_app, monkeypatch, fault):
    mid = pg_case["models"]["standard"]
    image_id = _image(pg_sessions, mid)
    observed = []
    def fail(*args, **kwargs):
        observed.append("failure")
        raise RuntimeError("injected delete failure")
    def request_session():
        with pg_sessions() as db:
            if fault == "before_commit":
                event.listen(db, "before_commit", fail)
            yield db
    pg_app.dependency_overrides[get_db] = request_session
    if fault == "after_audit_flush":
        original = audit_service.add_audit_log_rows
        def fail_after_flush(db, entries):
            original(db, entries)
            db.flush()
            observed.append("audit_flushed")
            fail()
        monkeypatch.setattr(audit_service, "add_audit_log_rows", fail_after_flush)
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        response = client.delete(f"/api/models/{mid}/images/{image_id}")
    assert response.status_code == 500 and "failure" in observed
    if fault == "after_audit_flush":
        assert "audit_flushed" in observed
    assert _read(pg_sessions, image_id) == ((mid, "/old.png", b"old binary"), [])


def test_pg_update_then_delete_waits_and_audits_loaded_url(pg_sessions, pg_case):
    """Characterize a stale delete read while an update holds the row lock."""
    mid = pg_case["models"]["standard"]
    actor_id = pg_case["actors"]["standard"]
    image_id = _image(pg_sessions, mid)
    updated, release, deleting = Event(), Event(), Event()
    pids = {}
    def update():
        with pg_sessions.begin() as db:
            pids["update"] = db.scalar(text("select pg_backend_pid()"))
            row = db.get(ModelImage, image_id)
            row.file_url, row.file_data = "/new.png", b"new binary"
            db.flush()
            updated.set()
            assert release.wait(20)
    def delete():
        with pg_sessions() as db:
            actor = db.get(User, actor_id)
            pids["delete"] = db.scalar(text("select pg_backend_pid()"))
            def before_execute(conn, cursor, statement, parameters, context, executemany):
                if statement.lstrip().lower().startswith("delete from model_images"):
                    deleting.set()
            event.listen(db.connection(), "before_cursor_execute", before_execute)
            models_service.delete_image(actor, db, mid, image_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(update)
        try:
            assert updated.wait(10)
            second = pool.submit(delete)
            assert deleting.wait(10)
            deadline = monotonic() + 10
            blocked = False
            while monotonic() < deadline:
                with pg_sessions() as db:
                    blocked = pids["update"] in db.scalar(text("select pg_blocking_pids(:pid)"), {"pid": pids["delete"]})
                if blocked:
                    break
                sleep(0.05)
            assert blocked
            assert _read(pg_sessions, image_id) == ((mid, "/old.png", b"old binary"), [])
        finally:
            release.set()
        first.result(timeout=30)
        second.result(timeout=30)
    assert _read(pg_sessions, image_id) == (None, [("delete", {"model_id": mid, "file_url": "/old.png"})])


def test_pg_deferred_delete_commit_failure_rolls_back_binary_and_audit(pg_sessions, pg_case, pg_app):
    """A fixture-only deferred constraint fails inside PostgreSQL COMMIT."""
    mid = pg_case["models"]["standard"]
    image_id = _image(pg_sessions, mid)
    engine = pg_sessions.kw["bind"]
    observed = []
    with engine.begin() as connection:
        connection.exec_driver_sql("""
            CREATE FUNCTION pr419_reject_deferred_commit() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'fixture deferred commit failure'
                    USING ERRCODE = '23514', CONSTRAINT = 'pr419_deferred_commit_guard';
            END; $$
        """)
        connection.exec_driver_sql(f"""
            CREATE CONSTRAINT TRIGGER pr419_deferred_commit_guard
            AFTER DELETE ON model_images DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW WHEN (OLD.id = {int(image_id)})
            EXECUTE FUNCTION pr419_reject_deferred_commit()
        """)

    def capture_commit_error(context):
        original = context.original_exception
        if getattr(original, "pgcode", None) == "23514":
            observed.append((context.statement, original.diag.constraint_name))

    event.listen(engine, "handle_error", capture_commit_error)
    try:
        with TestClient(pg_app, raise_server_exceptions=False) as client:
            response = client.delete(f"/api/models/{mid}/images/{image_id}")
        assert response.status_code == 500
        assert observed == [(None, "pr419_deferred_commit_guard")]
        assert _read(pg_sessions, image_id) == ((mid, "/old.png", b"old binary"), [])
    finally:
        event.remove(engine, "handle_error", capture_commit_error)
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER pr419_deferred_commit_guard ON model_images")
            connection.exec_driver_sql("DROP FUNCTION pr419_reject_deferred_commit()")
