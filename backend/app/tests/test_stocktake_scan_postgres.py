"""Scan transaction regressions using the approved migrated PostgreSQL fixture."""
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
    with sessions.begin() as db:
        db.get(User, case["actors"]["standard"]).role.permissions = ["storage.packages"]
        db.get(User, case["actors"]["eco"]).role.permissions = ["storage.packages"]
        count = WarehouseStocktake(request_key=str(uuid4()), title="scan", created_by=case["actors"]["standard"])
        db.add(count)
        db.flush()
        count_id = count.id
    app.include_router(stocktake.router, prefix="/api")
    return count_id


def state(sessions, count_id):
    with sessions() as db:
        rows = db.scalars(select(WarehouseStocktakeRow).where(
            WarehouseStocktakeRow.stocktake_id == count_id).order_by(WarehouseStocktakeRow.id)).all()
        audits = db.scalars(select(AuditLog).where(AuditLog.entity_type == "WarehouseStocktake",
            AuditLog.entity_id == count_id).order_by(AuditLog.id)).all()
        return ([(r.id, r.identity, r.package_id, r.expected, r.category, r.snapshot,
                  r.scan_snapshot, r.scan_code, r.scanned_at, r.scanned_by) for r in rows],
                [(a.action, a.user_id, a.new_value_json) for a in audits])


def test_pg_scan_auth_duplicate_first_evidence_and_completed_refusal(pg_sessions, pg_case, pg_app):
    count_id = prepare(pg_sessions, pg_case, pg_app)
    url = f"/api/warehouse-stocktakes/{count_id}/scan"
    code = f"unknown-{uuid4()}"
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        for actor, status in (("anonymous", 401), ("denied", 403)):
            assert client.post(url, headers={"X-Actor": actor}, json={"code": code}).status_code == status
        assert state(pg_sessions, count_id) == ([], [])
        first = client.post(url, json={"code": code})
        assert first.status_code == 200 and first.json()["duplicate"] is False
        before_rows, before_audits = state(pg_sessions, count_id)
        assert len(before_rows) == 1 and before_rows[0][2:8] == (None, False, "unknown", {}, None, code)
        assert before_rows[0][8] is not None and before_rows[0][9] == pg_case["actors"]["standard"]
        assert len(before_audits) == 1 and before_audits[0][0:2] == ("scan", pg_case["actors"]["standard"])
        duplicate = client.post(url, headers={"X-Actor": "eco"}, json={"code": code})
        assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True
        rows, audits = state(pg_sessions, count_id)
        assert rows == before_rows
        assert len(audits) == 2 and audits[0] == before_audits[0]
        assert audits[1][0:2] == ("scan_duplicate", pg_case["actors"]["eco"])
        assert audits[1][2]["row_id"] == rows[0][0]
        with pg_sessions.begin() as db:
            db.get(WarehouseStocktake, count_id).completed_at = datetime.now(timezone.utc)
        assert client.post(url, json={"code": "another"}).status_code == 409
        assert state(pg_sessions, count_id) == (rows, audits)


def test_pg_scan_request_audit_finalization_failure_then_retry(pg_sessions, pg_case, pg_app, monkeypatch):
    count_id = prepare(pg_sessions, pg_case, pg_app)
    url = f"/api/warehouse-stocktakes/{count_id}/scan"
    code = f"unknown-{uuid4()}"
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
            assert client.post(url, json={"code": code}).status_code == 500
    assert observed == ["scan"]
    assert state(pg_sessions, count_id) == ([], [])
    with TestClient(pg_app, raise_server_exceptions=False) as client:
        response = client.post(url, json={"code": code})
    assert response.status_code == 200 and response.json()["duplicate"] is False
    rows, audits = state(pg_sessions, count_id)
    assert len(rows) == 1 and rows[0][7] == code and rows[0][9] == pg_case["actors"]["standard"]
    assert len(audits) == 1 and audits[0][0:2] == ("scan", pg_case["actors"]["standard"])
    assert audits[0][2]["row_id"] == rows[0][0]
