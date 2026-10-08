"""Authoritative split labels retain their content with long factory identifiers."""
from app.models import PayrollQrLabel, PayrollRecord
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_employee
from app.tests.test_payroll_scan_allocations import issue, scan


def test_split_label_long_identifiers(client, auth_headers, tmp_path):
    employee = _create_employee(client, auth_headers)
    label = issue(client, auth_headers)
    original = scan(client, auth_headers, label, employee).json()["record"]
    endpoint = f'/api/payroll/records/{original["id"]}/split'
    split = client.post(endpoint, headers=auth_headers, json={"parts": [
        {"employee_id": employee["id"], "quantity": 7}, {"employee_id": employee["id"], "quantity": 13},
    ]})
    assert split.status_code == 200, split.text
    with TestSessionLocal() as db:
        for row in db.query(PayrollQrLabel).filter(PayrollQrLabel.split_from_label_id.isnot(None)):
            row.production_no = "MAN-8360-9208-47K4CA-LONG-FACTORY-REFERENCE"
            row.operation_name = "Tugma qadash qolda"
            row.model_code = "PJ1244-V-6230"
        db.commit()
        before = [(r.id, r.total_amount, r.status) for r in db.query(PayrollRecord)]
    printed = client.get(endpoint + '-labels/print', headers=auth_headers)
    assert printed.status_code == 200, printed.text
    assert printed.text.count('<img alt="QR"') == 2
    assert "MAN-8360-9208-47K4CA-LONG-FACTORY-REFERENCE" in printed.text
    assert "Tugma qadash qolda" in printed.text
    (tmp_path / "payroll-split-label.html").write_text(printed.text, encoding="utf-8")
    with TestSessionLocal() as db:
        assert before == [(r.id, r.total_amount, r.status) for r in db.query(PayrollRecord)]
