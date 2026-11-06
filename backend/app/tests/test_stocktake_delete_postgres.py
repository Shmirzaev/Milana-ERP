"""Stocktake bulk deletion transaction and lock checks on migrated PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from app.api.routes import stocktake
from app.core.deps import get_db
from app.libs.dto.inventory.warehouse_stocktake_input import DeleteCounts
from app.models import audit_service, stocktake_service
from app.schemas import AuditLog, User
from app.schemas.inventory.stocktake import WarehouseStocktake, WarehouseStocktakeRow

pytest_plugins = ("app.tests.test_modelcolor_create_postgres",)


def setup_counts(sessions, actor_id):
    with sessions.begin() as db:
        counts = [WarehouseStocktake(request_key=str(uuid4()), title=f"count {i}", created_by=actor_id) for i in range(2)]
        db.add_all(counts)
        db.flush()
        for count in counts:
            db.add(WarehouseStocktakeRow(stocktake_id=count.id, identity="fixture", expected=True, category="expected", snapshot={"qty": 3}))
        return [count.id for count in counts]


def read_state(sessions, ids):
    with sessions() as db:
        counts = db.scalars(select(WarehouseStocktake.id).where(WarehouseStocktake.id.in_(ids)).order_by(WarehouseStocktake.id)).all()
        rows = db.scalars(select(WarehouseStocktakeRow.stocktake_id).where(WarehouseStocktakeRow.stocktake_id.in_(ids)).order_by(WarehouseStocktakeRow.stocktake_id)).all()
        audits = db.scalars(select(AuditLog.entity_id).where(AuditLog.entity_type == "WarehouseStocktake", AuditLog.action == "delete", AuditLog.entity_id.in_(ids))).all()
        return counts, rows, audits


def test_pg_request_audit_flush_failure_rolls_back_bulk(pg_sessions, pg_case, pg_app, monkeypatch):
    actor_id = pg_case["actors"]["standard"]
    ids = setup_counts(pg_sessions, actor_id)
    with pg_sessions.begin() as db:
        db.get(User, actor_id).role.permissions = ["storage.packages"]
    pg_app.include_router(stocktake.router, prefix="/api")
    original = audit_service.add_audit_log_rows
    observed = []
    def fail_after_flush(db, entries):
        original(db, entries)
        db.flush()
        observed.append(True)
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(audit_service, "add_audit_log_rows", fail_after_flush)
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        response = client.post("/api/warehouse-stocktakes/delete-selected", json={"count_ids": ids})
    assert response.status_code == 500 and observed == [True]
    assert read_state(pg_sessions, ids) == (ids, ids, [])


def test_pg_overlapping_bulk_deletes_serialize(pg_sessions, pg_case, monkeypatch):
    actor_id = pg_case["actors"]["standard"]
    ids = setup_counts(pg_sessions, actor_id)
    locked, release, selecting = Event(), Event(), Event()
    pids = {}
    original = stocktake_service.delete_stocktake
    def pause(db, count, rows):
        if not locked.is_set():
            pids["first"] = db.scalar(text("select pg_backend_pid()"))
            locked.set()
            assert release.wait(20)
        original(db, count, rows)
    monkeypatch.setattr(stocktake_service, "delete_stocktake", pause)
    def run(first):
        from fastapi import HTTPException
        with pg_sessions() as db:
            actor = db.get(User, actor_id)
            if not first:
                pids["second"] = db.scalar(text("select pg_backend_pid()"))
                def before_execute(conn, cursor, statement, parameters, context, executemany):
                    if "for update" in statement.lower() and "warehouse_stocktakes" in statement.lower():
                        selecting.set()
                event.listen(db.connection(), "before_cursor_execute", before_execute)
            try:
                return stocktake_service.delete_counts(db, DeleteCounts(count_ids=ids), actor)
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, True)
        try:
            assert locked.wait(10)
            second = pool.submit(run, False)
            assert selecting.wait(10)
            deadline = monotonic() + 10
            blocked = False
            while monotonic() < deadline:
                with pg_sessions() as db:
                    blocked = pids["first"] in db.scalar(text("select pg_blocking_pids(:pid)"), {"pid": pids["second"]})
                if blocked:
                    break
                sleep(.05)
            assert blocked
            assert read_state(pg_sessions, ids) == (ids, ids, [])
        finally:
            release.set()
        assert first.result(timeout=30) == {"deleted": ids}
        assert second.result(timeout=30) == 404
    counts, rows, audits = read_state(pg_sessions, ids)
    assert counts == [] and rows == [] and sorted(audits) == ids


def test_pg_deferred_commit_failure_restores_bulk(pg_sessions, pg_case, pg_app):
    actor_id = pg_case["actors"]["standard"]
    ids = setup_counts(pg_sessions, actor_id)
    with pg_sessions.begin() as db:
        db.get(User, actor_id).role.permissions = ["storage.packages"]
    pg_app.include_router(stocktake.router, prefix="/api")
    engine = pg_sessions.kw["bind"]
    observed = []
    with engine.begin() as conn:
        conn.exec_driver_sql("""CREATE FUNCTION pr416_reject_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'fixture commit failure' USING ERRCODE = '23514', CONSTRAINT = 'pr416_commit_guard'; END; $$""")
        conn.exec_driver_sql(f"""CREATE CONSTRAINT TRIGGER pr416_commit_guard AFTER DELETE ON warehouse_stocktakes
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (OLD.id = {int(ids[0])})
            EXECUTE FUNCTION pr416_reject_commit()""")
    def capture(context):
        exc = context.original_exception
        if getattr(exc, "pgcode", None) == "23514":
            observed.append((context.statement, exc.diag.constraint_name))
    event.listen(engine, "handle_error", capture)
    try:
        with TestClient(pg_app, raise_server_exceptions=False) as client:
            response = client.post("/api/warehouse-stocktakes/delete-selected", json={"count_ids": ids})
        assert response.status_code == 500 and observed == [(None, "pr416_commit_guard")]
        assert read_state(pg_sessions, ids) == (ids, ids, [])
    finally:
        event.remove(engine, "handle_error", capture)
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TRIGGER pr416_commit_guard ON warehouse_stocktakes")
            conn.exec_driver_sql("DROP FUNCTION pr416_reject_commit()")


@pytest.mark.parametrize("operation", ["scan", "complete"])
def test_pg_delete_blocks_scan_or_completion(pg_sessions, pg_case, monkeypatch, operation):
    from fastapi import HTTPException
    from app.libs.dto.inventory.warehouse_stocktake_input import ScanCount
    actor_id = pg_case["actors"]["standard"]
    ids = setup_counts(pg_sessions, actor_id)
    locked, release, selecting = Event(), Event(), Event()
    pids = {}
    original = stocktake_service.delete_stocktake
    def pause(db, count, rows):
        if not locked.is_set():
            pids["delete"] = db.scalar(text("select pg_backend_pid()"))
            locked.set()
            assert release.wait(20)
        original(db, count, rows)
    monkeypatch.setattr(stocktake_service, "delete_stocktake", pause)
    def delete():
        with pg_sessions() as db:
            return stocktake_service.delete_counts(db, DeleteCounts(count_ids=ids), db.get(User, actor_id))
    def competing():
        with pg_sessions() as db:
            actor = db.get(User, actor_id)
            pids["other"] = db.scalar(text("select pg_backend_pid()"))
            def before(conn, cursor, statement, parameters, context, executemany):
                if "for update" in statement.lower() and "warehouse_stocktakes" in statement.lower():
                    selecting.set()
            event.listen(db.connection(), "before_cursor_execute", before)
            try:
                if operation == "scan":
                    stocktake_service.scan_count(db, ids[0], ScanCount(code="fixture"), actor)
                else:
                    stocktake_service.complete_count(db, ids[0], actor)
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(delete)
        try:
            assert locked.wait(10)
            second = pool.submit(competing)
            assert selecting.wait(10)
            deadline = monotonic() + 10
            blocked = False
            while monotonic() < deadline:
                with pg_sessions() as db:
                    blocked = pids["delete"] in db.scalar(text("select pg_blocking_pids(:pid)"), {"pid": pids["other"]})
                if blocked:
                    break
                sleep(.05)
            assert blocked
            assert read_state(pg_sessions, ids) == (ids, ids, [])
        finally:
            release.set()
        assert first.result(timeout=30) == {"deleted": ids}
        assert second.result(timeout=30) == 404
    counts, rows, audits = read_state(pg_sessions, ids)
    assert counts == [] and rows == [] and sorted(audits) == ids
