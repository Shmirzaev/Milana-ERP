"""Daily-report section JSON must contain actual integer quantities."""

from app.db.session import SessionLocal
from app.models import AuditLog, SewingDailyReport


def _report_payload(flow_id, section_quantities):
    return {
        "report_date": "2099-12-25",
        "sewing_flow_id": flow_id,
        "manual_model_no": "STRICT-SECTIONS",
        "sewn_qty": 3,
        "section_quantities": section_quantities,
        "defective_qty": 0,
    }


def test_section_quantities_reject_coercible_json_without_writing(client, auth_headers):
    flows = client.get("/api/sewing-flows", headers=auth_headers)
    assert flows.status_code == 200, flows.text
    flow_id = next(flow["id"] for flow in flows.json() if flow["code"] == "SEW-01")

    valid = client.post(
        "/api/sewing-daily-reports",
        json=_report_payload(flow_id, [1, 1, 1]),
        headers=auth_headers,
    )
    assert valid.status_code == 201, valid.text
    report_id = valid.json()["id"]

    with SessionLocal() as db:
        before_reports = db.query(SewingDailyReport).count()
        before_audits = db.query(AuditLog).count()

    invalid_create = client.post(
        "/api/sewing-daily-reports",
        json=_report_payload(flow_id, ["1", 1, 1]),
        headers=auth_headers,
    )
    assert invalid_create.status_code == 422, invalid_create.text

    invalid_update = client.patch(
        f"/api/sewing-daily-reports/{report_id}",
        json=_report_payload(flow_id, [1.0, 1, 1]),
        headers=auth_headers,
    )
    assert invalid_update.status_code == 422, invalid_update.text

    with SessionLocal() as db:
        assert db.query(SewingDailyReport).count() == before_reports
        assert db.query(AuditLog).count() == before_audits
        assert db.get(SewingDailyReport, report_id).section_quantities == [1, 1, 1]
