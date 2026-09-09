from uuid import uuid4

import pytest

from app.models import PayrollQrLabel, PayrollRecord
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_employee, _create_user_with_permissions


def _issue(client, headers, **changes):
    label = {
        "label_uid": f"PY:{uuid4().hex}", "sales_order_no": "SO-CONTROL-REVIEW",
        "batch_no": "1", "model_code": "XJ5614", "size": "L",
        "operation_section": "sewing", "operation_code": "SEW-1", "operation_name": "Sew sleeve",
        "quantity": 12, "rate_per_piece": 250, "currency": "UZS",
        **changes,
    }
    result = client.post("/api/payroll/qr-labels/issue", json={"labels": [label]}, headers=headers)
    assert result.status_code == 200, result.text
    return result.json()["labels"][0]


def _preview(client, headers, label, employee):
    result = client.post("/api/payroll/scan/numeric-work", json={
        "token": label["qr_token"], "employee_id": employee["id"],
    }, headers=headers)
    assert result.status_code == 201, result.text
    assert result.json()["record"] is None
    return result.json()["control_preview"]


def _confirmation(label, employee, preview):
    return {"label_uid": label["label_uid"], "employee_id": employee["id"], "review_token": preview["review_token"]}


def test_control_scan_preview_is_read_only_scoped_and_confirm_is_idempotent(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    completed = _issue(client, auth_headers)
    pending = _issue(client, auth_headers, operation_name="Attach buttons", operation_code="SEW-2")
    control = _issue(client, auth_headers, operation_section="control", operation_name="Kontrol", operation_code="QC-1")
    for changes in ({"size": "M"}, {"model_code": "XJ5415"}, {"sales_order_no": "SO-OTHER"}):
        _issue(client, auth_headers, **changes)
    scanned = client.post("/api/payroll/scan/numeric-work", json={
        "token": completed["qr_token"], "employee_id": employee["id"],
    }, headers=auth_headers)
    assert scanned.status_code == 201, scanned.text
    with TestSessionLocal() as db:
        before = db.query(PayrollRecord).count()
    preview = _preview(client, auth_headers, control, employee)
    assert {row["label_uid"] for row in preview["operations"]} == {completed["label_uid"], pending["label_uid"], control["label_uid"]}
    statuses = {row["label_uid"]: row["status"] for row in preview["operations"]}
    assert statuses[completed["label_uid"]] == "scanned"
    assert statuses[pending["label_uid"]] == statuses[control["label_uid"]] == "available"
    # Repeated/cancelled previews never mint a payroll record.
    _preview(client, auth_headers, control, employee)
    with TestSessionLocal() as db:
        assert db.query(PayrollRecord).count() == before
        assert db.query(PayrollQrLabel).filter_by(label_uid=control["label_uid"]).one().status == "available"
    payload = _confirmation(control, employee, preview)
    confirmed = client.post("/api/payroll/scan/control-confirm", json=payload, headers=auth_headers)
    assert confirmed.status_code == 201, confirmed.text
    assert float(confirmed.json()["total_amount"]) == 3000
    assert confirmed.json()["employee_id"] == employee["id"]
    duplicate = client.post("/api/payroll/scan/control-confirm", json=payload, headers=auth_headers)
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["id"] == confirmed.json()["id"]
    other = _create_employee(client, auth_headers)
    other_preview = _preview(client, auth_headers, control, other)
    wrong_employee = client.post("/api/payroll/scan/control-confirm", json=_confirmation(control, other, other_preview), headers=auth_headers)
    assert wrong_employee.status_code == 409, wrong_employee.text
    with TestSessionLocal() as db:
        assert db.query(PayrollRecord).count() == before + 1
        assert db.query(PayrollQrLabel).filter_by(label_uid=pending["label_uid"]).one().status == "available"


@pytest.mark.parametrize("name", ["Control", "Kontrol", "Контроль", "Nazorat"])
def test_control_cannot_bypass_confirmation_through_legacy_single_or_bulk(client, auth_headers, name):
    employee = _create_employee(client, auth_headers)
    control = _issue(client, auth_headers, operation_name=name)
    payload = {"employee_id": employee["id"], "scan_uid": control["label_uid"], "work": {
        "label_id": control["label_uid"], "operation_section": "sewing", "operation_name": "Forged ordinary operation",
        "quantity": 999, "rate_per_piece": 999,
    }, "control_confirmed": True}
    for path, body in (("records", payload), ("records/bulk", {"records": [payload]})):
        response = client.post(f"/api/payroll/{path}", json=body, headers=auth_headers)
        assert response.status_code == 409, response.text
    legacy = client.post("/api/payroll/scan/control-preview", json={
        "label_uid": control["label_uid"], "employee_id": employee["id"],
    }, headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["work"]["operation_name"] == name
    assert float(legacy.json()["work"]["rate_per_piece"]) == 250
    with TestSessionLocal() as db:
        assert db.query(PayrollRecord).filter_by(scan_uid=control["label_uid"]).count() == 0


def test_control_preview_and_confirm_enforce_factory_permission_and_snapshot(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    other_employee = _create_employee(client, auth_headers)
    control = _issue(client, auth_headers, operation_section="control")
    preview = _preview(client, auth_headers, control, employee)
    payload = _confirmation(control, employee, preview)
    changed_employee = client.post("/api/payroll/scan/control-confirm", json={**payload, "employee_id": other_employee["id"]}, headers=auth_headers)
    assert changed_employee.status_code == 409
    unauthorized = _create_user_with_permissions(client, auth_headers, email=f"no-payroll-{uuid4().hex}@example.com", permissions=["dashboard.view"])
    foreign = _create_user_with_permissions(client, auth_headers, email=f"foreign-payroll-{uuid4().hex}@example.com", permissions=["payroll.scan"], factory_code="BST")
    for route in ("control-preview", "control-confirm"):
        denied = client.post(f"/api/payroll/scan/{route}", json=payload, headers=unauthorized)
        assert denied.status_code == 403, denied.text
        denied = client.post(f"/api/payroll/scan/{route}", json=payload, headers=foreign)
        assert denied.status_code == 404, denied.text
    with TestSessionLocal() as db:
        db.query(PayrollQrLabel).filter_by(label_uid=control["label_uid"]).one().quantity = 15
        db.commit()
    stale = client.post("/api/payroll/scan/control-confirm", json=payload, headers=auth_headers)
    assert stale.status_code == 409, stale.text
    with TestSessionLocal() as db:
        assert db.query(PayrollRecord).filter_by(scan_uid=control["label_uid"]).count() == 0


def test_bulk_control_rejection_rolls_back_preceding_ordinary_row(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    ordinary = _issue(client, auth_headers)
    control = _issue(client, auth_headers, operation_section="control")
    result = client.post("/api/payroll/records/bulk", json={"records": [
        {"employee_id": employee["id"], "scan_uid": label["label_uid"], "quantity": 12, "rate_per_piece": 250}
        for label in (ordinary, control)
    ]}, headers=auth_headers)
    assert result.status_code == 409, result.text
    with TestSessionLocal() as db:
        assert db.query(PayrollRecord).filter(PayrollRecord.scan_uid.in_([ordinary["label_uid"], control["label_uid"]])).count() == 0
        assert db.query(PayrollQrLabel).filter_by(label_uid=ordinary["label_uid"]).one().status == "available"


def test_voided_control_cannot_be_confirmed_as_success_or_recredited_without_return(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    control = _issue(client, auth_headers, operation_section="control")
    preview = _preview(client, auth_headers, control, employee)
    payload = _confirmation(control, employee, preview)
    confirmed = client.post("/api/payroll/scan/control-confirm", json=payload, headers=auth_headers)
    assert confirmed.status_code == 201, confirmed.text
    voided = client.post(f"/api/payroll/records/{confirmed.json()['id']}/void", headers=auth_headers)
    assert voided.status_code == 200, voided.text
    for route, body in (
        ("control-preview", payload), ("control-confirm", payload),
        ("numeric-work", {"token": control["qr_token"], "employee_id": employee["id"]}),
    ):
        blocked = client.post(f"/api/payroll/scan/{route}", json=body, headers=auth_headers)
        assert blocked.status_code == 409, blocked.text
    with TestSessionLocal() as db:
        label = db.query(PayrollQrLabel).filter_by(label_uid=control["label_uid"]).one()
        label_id = label.id
    returned = client.post(f"/api/payroll/qr-labels/{label_id}/return", headers=auth_headers)
    assert returned.status_code == 200, returned.text
    stale = client.post("/api/payroll/scan/control-confirm", json=payload, headers=auth_headers)
    assert stale.status_code == 409, stale.text
    fresh = _preview(client, auth_headers, control, employee)
    rescanned = client.post("/api/payroll/scan/control-confirm", json=_confirmation(control, employee, fresh), headers=auth_headers)
    assert rescanned.status_code == 201, rescanned.text
    assert rescanned.json()["status"] == "recorded"
    assert rescanned.json()["id"] != confirmed.json()["id"]
