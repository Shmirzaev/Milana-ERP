"""Synthetic Control-review fixture for an isolated test database only."""
from app.tests.test_payroll import _create_employee
from app.tests.test_payroll_control_confirmation import _issue


def seed_payroll_control(client, headers):
    employee = _create_employee(client, headers, "Durdona Azamova — QA")
    context = {"sales_order_no": "SO-2026-000202", "production_no": "PO-2026-000203", "size": "XL", "quantity": 119}
    sewing = _issue(client, headers, **context, operation_name="Chontak overlo", operation_code="SEW-01")
    pending = _issue(client, headers, **context, operation_name="Chontak kesish", operation_code="SEW-02")
    control = _issue(client, headers, **context, operation_section="control", operation_name="Kontrol", operation_code="QC-01")
    scanned = client.post("/api/payroll/scan/numeric-work", headers=headers, json={
        "token": sewing["qr_token"], "employee_id": employee["id"],
    })
    assert scanned.status_code == 201, scanned.text
    return {"employee_id": employee["id"], "employee_name": employee["full_name"], "control_token": control["qr_token"], "control_label_uid": control["label_uid"], "sewing_token": sewing["qr_token"], "pending_token": pending["qr_token"]}
