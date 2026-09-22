from datetime import date
from uuid import uuid4

from app.db.session import SessionLocal
from app.models import AuditLog, SewingDailyReport


DB_INTEGER_MAX = 2_147_483_647


def _create_flow(client, auth_headers) -> dict:
    marker = uuid4().hex[:12].upper()
    response = client.post(
        "/api/sewing-flows",
        json={
            "name": f"Daily bound {marker}",
            "code": f"DB-{marker}",
            "capacity_per_day": 1,
            "is_active": True,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _manual_payload(flow_id: int, sewn_qty: int) -> dict:
    return {
        "report_date": date.today().isoformat(),
        "sewing_flow_id": flow_id,
        "manual_model_no": "MANUAL-INT32",
        "sewn_qty": sewn_qty,
        "defective_qty": 0,
    }


def _audit_count() -> int:
    db = SessionLocal()
    try:
        return db.query(AuditLog).filter(AuditLog.entity_type == "SewingDailyReport").count()
    finally:
        db.close()


def test_manual_report_accepts_postgres_integer_max(client, auth_headers):
    flow = _create_flow(client, auth_headers)

    response = client.post(
        "/api/sewing-daily-reports",
        json=_manual_payload(flow["id"], DB_INTEGER_MAX),
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()["sewn_qty"] == DB_INTEGER_MAX
    db = SessionLocal()
    try:
        assert db.get(SewingDailyReport, response.json()["id"]).sewn_qty == DB_INTEGER_MAX
    finally:
        db.close()


def test_manual_report_rejects_postgres_integer_overflow_without_writes(client, auth_headers):
    flow = _create_flow(client, auth_headers)
    audit_count = _audit_count()

    response = client.post(
        "/api/sewing-daily-reports",
        json=_manual_payload(flow["id"], DB_INTEGER_MAX + 1),
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "Sewn quantity must fit a 32-bit database integer"
    db = SessionLocal()
    try:
        assert db.query(SewingDailyReport).filter(SewingDailyReport.sewing_flow_id == flow["id"]).count() == 0
    finally:
        db.close()
    assert _audit_count() == audit_count


def test_manual_report_overflow_preserves_auth_and_resource_precedence(client, auth_headers):
    flow = _create_flow(client, auth_headers)
    payload = _manual_payload(flow["id"], DB_INTEGER_MAX + 1)

    unauthorized = client.post("/api/sewing-daily-reports", json=payload)
    missing_flow = client.post(
        "/api/sewing-daily-reports",
        json={**payload, "sewing_flow_id": DB_INTEGER_MAX},
        headers=auth_headers,
    )

    assert unauthorized.status_code == 401, unauthorized.text
    assert missing_flow.status_code == 404, missing_flow.text
    assert missing_flow.json()["detail"] == "Sewing line not found"


def test_manual_report_update_rejects_overflow_without_mutation_or_audit(client, auth_headers):
    flow = _create_flow(client, auth_headers)
    created = client.post(
        "/api/sewing-daily-reports",
        json=_manual_payload(flow["id"], 7),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    report_id = int(created.json()["id"])
    audit_count = _audit_count()

    response = client.patch(
        f"/api/sewing-daily-reports/{report_id}",
        json={
            "report_date": date.today().isoformat(),
            "manual_model_no": "MANUAL-INT32",
            "sewn_qty": DB_INTEGER_MAX + 1,
            "defective_qty": 0,
        },
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "Sewn quantity must fit a 32-bit database integer"
    db = SessionLocal()
    try:
        db.expire_all()
        report = db.get(SewingDailyReport, report_id)
        assert report.sewn_qty == 7
        assert report.manual_model_no == "MANUAL-INT32"
    finally:
        db.close()
    assert _audit_count() == audit_count


def test_missing_report_precedes_update_overflow_validation(client, auth_headers):
    response = client.patch(
        f"/api/sewing-daily-reports/{DB_INTEGER_MAX}",
        json={
            "report_date": date.today().isoformat(),
            "manual_model_no": "MANUAL-INT32",
            "sewn_qty": DB_INTEGER_MAX + 1,
            "defective_qty": 0,
        },
        headers=auth_headers,
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Daily sewing report entry not found"
