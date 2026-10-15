from app.models import PayrollQrLabel, PayrollRecord
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_employee
from app.tests.test_payroll_control_confirmation import _issue, _preview, _confirmation


def test_shagovoy_in_control_section_scans_normally(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    label = _issue(client, auth_headers, operation_section="control", operation_name="Shagovoy")
    response = client.post("/api/payroll/scan/numeric-work", headers=auth_headers,
                           json={"token": label["qr_token"], "employee_id": employee["id"]})
    assert response.status_code == 201, response.text
    assert response.json()["record"]["operation_name"] == "Shagovoy"
    assert not response.json().get("control_preview")


def test_control_closure_keeps_unscanned_without_pay_and_is_idempotent(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    pending = _issue(client, auth_headers)
    other = _issue(client, auth_headers, size="XL")
    control = _issue(client, auth_headers, operation_name="Kontrol")
    preview = _preview(client, auth_headers, control, employee)
    payload = {**_confirmation(control, employee, preview), "close_unscanned": True, "closure_reason": "Worker left"}
    for _ in range(2):
        response = client.post("/api/payroll/scan/control-confirm", headers=auth_headers, json=payload)
        assert response.status_code == 201, response.text
    with TestSessionLocal() as db:
        row = db.query(PayrollQrLabel).filter_by(label_uid=pending["label_uid"]).one()
        assert row.status == "closed" and row.payroll_record_id is None
        assert row.closure_details["reason"] == "Worker left"
        assert db.query(PayrollQrLabel).filter_by(label_uid=other["label_uid"]).one().status == "available"
        assert db.query(PayrollRecord).filter(PayrollRecord.scan_uid.in_([control["label_uid"], pending["label_uid"]])).count() == 1
    scan = client.post("/api/payroll/scan/numeric-work", headers=auth_headers,
                       json={"token": pending["qr_token"], "employee_id": employee["id"]})
    assert scan.status_code == 409
    closed = client.get("/api/payroll/qr-labels?status=closed", headers=auth_headers).json()
    assert closed["closed_count"] == 1
    assert closed["items"][0]["label_uid"] == pending["label_uid"]
    active = client.get("/api/payroll/qr-labels", headers=auth_headers).json()
    assert pending["label_uid"] not in {row["label_uid"] for row in active["items"]}
