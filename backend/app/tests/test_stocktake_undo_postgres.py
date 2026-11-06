"""Undo request and transaction regressions on the migrated PostgreSQL fixture."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from app.api.routes import stocktake
from app.models import audit_service, stocktake_service
from app.schemas import AuditLog, User
from app.schemas.inventory.stocktake import WarehouseStocktake, WarehouseStocktakeRow

pytest_plugins = ("app.tests.test_modelcolor_create_postgres",)


def prepare(sessions, case, app):
    actor = case["actors"]["standard"]
    with sessions.begin() as db:
        db.get(User, actor).role.permissions = ["storage.packages"]
        count = WarehouseStocktake(request_key=str(uuid4()), title="undo", created_by=actor)
        db.add(count)
        db.flush()
        rows = [WarehouseStocktakeRow(stocktake_id=count.id, identity=identity, expected=expected,
                category=category, snapshot={"quantity": 3}, scan_snapshot={"quantity": 4},
                scan_code=identity, scanned_at=datetime.now(timezone.utc), scanned_by=actor)
                for identity, expected, category in [("expected", True, "expected"), ("unknown", False, "unknown")]]
        db.add_all(rows)
        db.flush()
        ids = count.id, [row.id for row in rows]
    app.include_router(stocktake.router, prefix="/api")
    return ids


def state(sessions, count_id):
    with sessions() as db:
        rows = db.scalars(select(WarehouseStocktakeRow).where(
            WarehouseStocktakeRow.stocktake_id == count_id).order_by(WarehouseStocktakeRow.id)).all()
        audits = db.scalars(select(AuditLog).where(AuditLog.entity_type == "WarehouseStocktake",
            AuditLog.entity_id == count_id, AuditLog.action == "undo_scan").order_by(AuditLog.id)).all()
        return ([(r.id, r.expected, r.snapshot, r.scan_snapshot, r.scan_code, r.scanned_at, r.scanned_by) for r in rows],
                [(a.user_id, a.old_value_json) for a in audits])


def test_pg_undo_auth_and_selection_refusal_before_mutation(pg_sessions, pg_case, pg_app):
    count_id, ids = prepare(pg_sessions, pg_case, pg_app)
    url = f"/api/warehouse-stocktakes/{count_id}/scans/delete-selected"
    before = state(pg_sessions, count_id)
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        for actor, status in (("anonymous", 401), ("denied", 403)):
            assert client.post(url, headers={"X-Actor": actor}, json={"row_ids": ids}).status_code == status
        assert client.post(url, json={"row_ids": [ids[0], 2147483647]}).status_code == 404
        assert client.delete(f"/api/warehouse-stocktakes/{count_id}/scans/2147483647").status_code == 404
    assert state(pg_sessions, count_id) == before


def test_pg_undo_request_audit_finalization_failure_then_retry(pg_sessions, pg_case, pg_app, monkeypatch):
    count_id, ids = prepare(pg_sessions, pg_case, pg_app)
    url = f"/api/warehouse-stocktakes/{count_id}/scans/delete-selected"
    before = state(pg_sessions, count_id)
    observed = []
    original = audit_service.add_audit_log_rows
    def fail_after_flush(db, entries):
        original(db, entries)
        db.flush()
        observed.extend(entry.action for entry in entries)
        raise RuntimeError("injected audit finalization failure")
    with monkeypatch.context() as patch:
        patch.setattr(audit_service, "add_audit_log_rows", fail_after_flush)
        with TestClient(pg_app, raise_server_exceptions=False) as client:
            response = client.post(url, json={"row_ids": list(reversed(ids))})
    assert response.status_code == 500 and observed == ["undo_scan", "undo_scan"]
    assert state(pg_sessions, count_id) == before
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        retry = client.post(url, json={"row_ids": ids})
    assert retry.status_code == 200 and retry.json() == {"deleted": ids}
    rows, audits = state(pg_sessions, count_id)
    assert rows == [(ids[0], True, {"quantity": 3}, None, None, None, None)]
    assert len(audits) == 2
    assert [a[0] for a in audits] == [pg_case["actors"]["standard"]] * 2
    assert [a[1]["row_id"] for a in audits] == ids


def test_pg_undo_duplicate_and_foreign_selection_and_single_success(pg_sessions, pg_case, pg_app):
    count_id, ids = prepare(pg_sessions, pg_case, pg_app)
    actor_id = pg_case["actors"]["standard"]
    with pg_sessions.begin() as db:
        other = WarehouseStocktake(request_key=str(uuid4()), title="other", created_by=actor_id)
        db.add(other)
        db.flush()
        foreign = WarehouseStocktakeRow(stocktake_id=other.id, identity="foreign", expected=False,
            category="unknown", snapshot={}, scan_code="foreign", scanned_at=datetime.now(timezone.utc),
            scanned_by=actor_id)
        db.add(foreign)
        db.flush()
        other_id, foreign_id = other.id, foreign.id
    before, other_before = state(pg_sessions, count_id), state(pg_sessions, other_id)
    url = f"/api/warehouse-stocktakes/{count_id}"
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        refused = client.post(f"{url}/scans/delete-selected", json={"row_ids": [ids[0], foreign_id]})
        assert refused.status_code == 404
        assert state(pg_sessions, count_id) == before
        assert state(pg_sessions, other_id) == other_before
        duplicate = client.post(f"{url}/scans/delete-selected", json={"row_ids": [ids[0], ids[0]]})
        assert duplicate.status_code == 200 and duplicate.json() == {"deleted": [ids[0]]}
        rows, audits = state(pg_sessions, count_id)
        assert rows[0] == (ids[0], True, {"quantity": 3}, None, None, None, None)
        assert rows[1] == before[0][1]
        assert audits == [(actor_id, {"row_id": ids[0], "code": "expected", "package_id": None})]
        single = client.delete(f"{url}/scans/{ids[1]}")
        assert single.status_code == 200 and single.json() == {"ok": True}
    rows, audits = state(pg_sessions, count_id)
    assert rows == [(ids[0], True, {"quantity": 3}, None, None, None, None)]
    assert audits == [(actor_id, {"row_id": ids[0], "code": "expected", "package_id": None}),
                      (actor_id, {"row_id": ids[1], "code": "unknown", "package_id": None})]
    assert state(pg_sessions, other_id) == other_before


def test_pg_undo_completed_count_refuses_without_mutation(pg_sessions, pg_case, pg_app):
    count_id, ids = prepare(pg_sessions, pg_case, pg_app)
    with pg_sessions.begin() as db:
        db.get(WarehouseStocktake, count_id).completed_at = datetime.now(timezone.utc)
    before = state(pg_sessions, count_id)
    url = f"/api/warehouse-stocktakes/{count_id}"
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        assert client.post(f"{url}/scans/delete-selected", json={"row_ids": ids}).status_code == 409
        assert client.delete(f"{url}/scans/{ids[0]}").status_code == 409
    assert state(pg_sessions, count_id) == before


def test_pg_undo_waits_for_completion_with_preloaded_count(pg_sessions, pg_case, pg_app, monkeypatch):
    count_id, ids = prepare(pg_sessions, pg_case, pg_app)
    actor_id = pg_case["actors"]["standard"]
    before = state(pg_sessions, count_id)
    preloaded, locked, release, selecting = Event(), Event(), Event(), Event()
    pids = {}
    original = stocktake_service.freeze_stocktake_completion

    def pause_completion(db, count, rows, snapshots, completed_at):
        pids["completion"] = db.scalar(text("select pg_backend_pid()"))
        locked.set()
        assert release.wait(20)
        original(db, count, rows, snapshots, completed_at)

    monkeypatch.setattr(stocktake_service, "freeze_stocktake_completion", pause_completion)

    def complete():
        with pg_sessions() as db:
            return stocktake_service.complete_count(db, count_id, db.get(User, actor_id))

    def undo():
        with pg_sessions() as db:
            count = db.get(WarehouseStocktake, count_id)
            assert count.completed_at is None
            actor = db.get(User, actor_id)
            pids["undo"] = db.scalar(text("select pg_backend_pid()"))
            preloaded.set()
            assert locked.wait(20)
            def before_execute(conn, cursor, statement, parameters, context, executemany):
                if "for update" in statement.lower() and "warehouse_stocktakes" in statement.lower():
                    selecting.set()
            event.listen(db.connection(), "before_cursor_execute", before_execute)
            try:
                return stocktake_service.undo_scan(db, count_id, ids[0], actor)
            except HTTPException as exc:
                db.rollback()
                return exc.status_code, exc.detail

    with ThreadPoolExecutor(max_workers=2) as pool:
        contender = pool.submit(undo)
        completion = None
        try:
            assert preloaded.wait(10)
            completion = pool.submit(complete)
            assert locked.wait(10)
            assert selecting.wait(10)
            deadline = monotonic() + 10
            blocked = False
            while monotonic() < deadline:
                with pg_sessions() as db:
                    blocked = pids["completion"] in db.scalar(
                        text("select pg_blocking_pids(:pid)"), {"pid": pids["undo"]})
                if blocked:
                    break
                sleep(.05)
            assert blocked
            assert state(pg_sessions, count_id) == before
        finally:
            release.set()
        assert completion.result(timeout=30)["completed_at"] is not None
        assert contender.result(timeout=30) == (409, "This inventory count is completed")
    assert state(pg_sessions, count_id) == before
    with pg_sessions() as db:
        assert db.get(WarehouseStocktake, count_id).completed_at is not None
        actions = db.scalars(select(AuditLog.action).where(AuditLog.entity_type == "WarehouseStocktake",
            AuditLog.entity_id == count_id).order_by(AuditLog.id)).all()
        assert actions == ["complete"]
