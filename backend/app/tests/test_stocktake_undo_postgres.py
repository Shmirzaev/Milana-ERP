"""Undo request and transaction regressions on the migrated PostgreSQL fixture."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.routes import stocktake
from app.models import audit_service
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
