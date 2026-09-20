from uuid import uuid4

from app.db.session import SessionLocal
from app.models import PayrollQrLabel, PayrollRecord
from app.tests.test_payroll import (
    _create_employee,
    _create_user_with_permissions,
    _record_payload,
)


def _user(client, auth_headers, permission):
    return _create_user_with_permissions(
        client,
        auth_headers,
        email=f"payable-{permission.replace('.', '-')}-{uuid4().hex}@example.com",
        permissions=[permission],
    )


def _label(label_uid):
    return {
        "label_uid": label_uid,
        "operation_section": "sewing",
        "operation_code": "PY03-SEW",
        "operation_name": "Authorized payable operation",
        "quantity": 12,
        "rate_per_piece": 250,
        "currency": "UZS",
    }


def test_scan_only_grant_cannot_set_payable_values(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    scanner = _user(client, auth_headers, "payroll.scan")
    label_uid = f"PY03:{uuid4().hex}"

    issue = client.post(
        "/api/payroll/qr-labels/issue",
        headers=scanner,
        json={"labels": [_label(label_uid)]},
    )
    freeform = client.post(
        "/api/payroll/records",
        headers=scanner,
        json=_record_payload(employee["id"], scan_uid=f"PY03:{uuid4().hex}"),
    )

    assert issue.status_code == 403, issue.text
    assert freeform.status_code == 403, freeform.text
    with SessionLocal() as db:
        assert db.query(PayrollQrLabel).filter(PayrollQrLabel.label_uid == label_uid).count() == 0
        assert db.query(PayrollRecord).count() == 0


def test_scan_only_uses_issued_snapshot_and_mixed_bulk_rolls_back(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    manager = _user(client, auth_headers, "payroll.manage")
    scanner = _user(client, auth_headers, "payroll.scan")
    first_uid = f"PY03:{uuid4().hex}"
    second_uid = f"PY03:{uuid4().hex}"
    issued = client.post(
        "/api/payroll/qr-labels/issue",
        headers=manager,
        json={"labels": [_label(first_uid), _label(second_uid)]},
    )
    assert issued.status_code == 200, issued.text

    trusted = client.post(
        "/api/payroll/records",
        headers=scanner,
        json={
            "scan_uid": first_uid,
            "employee_id": employee["id"],
            "quantity": 999,
            "rate_per_piece": 999,
            "work": {"label_id": first_uid, "quantity": 999, "rate_per_piece": 999},
        },
    )
    assert trusted.status_code == 201, trusted.text
    assert float(trusted.json()["quantity"]) == 12
    assert float(trusted.json()["rate_per_piece"]) == 250
    replay = client.post(
        "/api/payroll/records",
        headers=scanner,
        json={"scan_uid": first_uid, "employee_id": employee["id"], "quantity": 1, "rate_per_piece": 1},
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["duplicate"] is True

    mixed = client.post(
        "/api/payroll/records/bulk",
        headers=scanner,
        json={"records": [
            {"scan_uid": second_uid, "employee_id": employee["id"], "quantity": 1, "rate_per_piece": 1},
            _record_payload(employee["id"], scan_uid=f"PY03:{uuid4().hex}"),
        ]},
    )
    assert mixed.status_code == 403, mixed.text
    with SessionLocal() as db:
        assert db.query(PayrollRecord).filter(PayrollRecord.scan_uid == second_uid).count() == 0
        second = db.query(PayrollQrLabel).filter(PayrollQrLabel.label_uid == second_uid).one()
        assert second.status == "available" and second.payroll_record_id is None


def test_manager_and_admin_keep_manual_payable_workflows(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    manager = _user(client, auth_headers, "payroll.manage")

    manual = client.post(
        "/api/payroll/records",
        headers=manager,
        json=_record_payload(employee["id"], scan_uid=f"PY03:{uuid4().hex}"),
    )
    admin_issue = client.post(
        "/api/payroll/qr-labels/issue",
        headers=auth_headers,
        json={"labels": [_label(f"PY03:{uuid4().hex}")]},
    )

    assert manual.status_code == 201, manual.text
    assert float(manual.json()["quantity"]) == 10
    assert float(manual.json()["rate_per_piece"]) == 250
    assert admin_issue.status_code == 200, admin_issue.text
