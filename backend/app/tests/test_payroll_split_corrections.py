from decimal import Decimal
from uuid import uuid4

import pytest

from app.models import AuditLog, Employee, PayrollPeriod, PayrollQrLabel, PayrollRecord
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_employee, _create_user_with_permissions
from app.tests.test_payroll_scan_allocations import issue, scan


def setup_split(client, headers):
    employees = [_create_employee(client, headers) for _ in range(3)]
    label = issue(client, headers)
    original = scan(client, headers, label, employees[0]).json()["record"]
    response = client.post(f"/api/payroll/records/{original['id']}/split", headers=headers, json={"parts": [
        {"employee_id": employees[0]["id"], "quantity": 7},
        {"employee_id": employees[1]["id"], "quantity": 13},
    ]})
    assert response.status_code == 200, response.text
    with TestSessionLocal() as db:
        parent = db.query(PayrollQrLabel).filter_by(label_uid=label["label_uid"]).one()
        children = db.query(PayrollQrLabel).filter_by(split_from_label_id=parent.id).order_by(PayrollQrLabel.id).all()
        endpoint = f"/api/payroll/qr-labels/{children[0].id}/split-allocation"
    return employees, original, response.json(), endpoint


def correction(client, headers, endpoint):
    response = client.get(endpoint, headers=headers)
    assert response.status_code == 200, response.text
    view = response.json()
    return {"revision": view["revision"], "reason": "Correct operator allocation", "parts": [
        {key: row[key] for key in ("label_id", "employee_id", "quantity", "operation_name", "rate_per_piece")}
        for row in view["parts"]
    ]}


def test_correct_split_all_fields_and_retry_preserves_qrs_dates_and_history(client, auth_headers):
    employees, original, records, endpoint = setup_split(client, auth_headers)
    body = correction(client, auth_headers, endpoint)
    body["parts"][0].update(employee_id=employees[2]["id"], quantity=8, operation_name="Corrected work", rate_per_piece="2.5")
    body["parts"][1].update(quantity=12, operation_name="Other work", rate_per_piece="3")
    response = client.patch(endpoint, headers=auth_headers, json=body)
    assert response.status_code == 200, response.text
    assert [Decimal(row["total_amount"]) for row in response.json()["parts"]] == [Decimal("20"), Decimal("36")]
    with TestSessionLocal() as db:
        audit_count = db.query(AuditLog).filter_by(action="correct_split_allocation").count()
        assert audit_count == 1
        assert db.get(PayrollRecord, original["id"]).status == "voided"
        assert db.get(PayrollRecord, original["id"]).total_amount == Decimal(original["total_amount"])
        for previous, part in zip(records, body["parts"]):
            record = db.get(PayrollRecord, previous["id"])
            label = db.get(PayrollQrLabel, part["label_id"])
            assert record.scan_uid == previous["scan_uid"] == label.label_uid
            assert record.employee_id == part["employee_id"]
            assert record.quantity == label.quantity == part["quantity"]
            assert record.operation_name == label.operation_name == part["operation_name"]
            assert record.raw_work_json["operation_name"] == part["operation_name"]
            assert record.raw_employee_json["employee_id"] == part["employee_id"]
            assert record.scanned_at.isoformat().split("+")[0] == previous["scanned_at"].split("+")[0].rstrip("Z")
    retry = client.patch(endpoint, headers=auth_headers, json=body)
    assert retry.status_code == 200, retry.text
    assert retry.json() == response.json()
    with TestSessionLocal() as db:
        assert db.query(AuditLog).filter_by(action="correct_split_allocation").count() == audit_count
    body["parts"][0]["operation_name"] = "Stale second writer"
    assert client.patch(endpoint, headers=auth_headers, json=body).status_code == 409
    printed = client.get(f"/api/payroll/records/{original['id']}/split-labels/print", headers=auth_headers)
    assert printed.status_code == 200 and "Corrected work" in printed.text and "Other work" in printed.text


@pytest.mark.parametrize("invalid", ["total", "duplicate", "missing", "employee", "paid", "returned", "period", "unassigned_period", "permission", "factory"])
def test_split_correction_refusal_is_atomic(client, auth_headers, invalid):
    employees, original, records, endpoint = setup_split(client, auth_headers)
    body = correction(client, auth_headers, endpoint)
    body["parts"][0]["operation_name"] = "Must not be partially saved"
    headers = auth_headers
    if invalid == "total":
        body["parts"][0]["quantity"] += 1
    elif invalid == "duplicate":
        body["parts"][1]["label_id"] = body["parts"][0]["label_id"]
    elif invalid == "missing":
        body["parts"].pop()
    elif invalid == "employee":
        body["parts"][1]["employee_id"] = 999999
    elif invalid in {"permission", "factory"}:
        headers = _create_user_with_permissions(client, auth_headers, email=f"correction-{uuid4().hex}@example.com", permissions=["payroll.scan"] if invalid == "permission" else ["payroll.manage"], factory_code="ECO" if invalid == "factory" else "MIL")
    with TestSessionLocal() as db:
        record = db.get(PayrollRecord, records[1]["id"])
        if invalid == "paid":
            record.status = "paid"
        elif invalid == "returned":
            db.get(PayrollQrLabel, body["parts"][1]["label_id"]).status = "available"
        elif invalid in {"period", "unassigned_period"}:
            period = PayrollPeriod(factory_code="MIL", period_no=f"P-{uuid4().hex}", name="Locked", start_date=record.scanned_at, end_date=record.scanned_at, status="locked")
            db.add(period)
            db.flush()
            if invalid == "period":
                record.payroll_period_id = period.id
        db.commit()
        before = [(r.id, r.employee_id, r.quantity, r.operation_name, r.total_amount, r.status) for r in db.query(PayrollRecord).order_by(PayrollRecord.id)]
    response = client.patch(endpoint, headers=headers, json=body)
    assert response.status_code in {403, 404, 409, 422}, response.text
    with TestSessionLocal() as db:
        assert before == [(r.id, r.employee_id, r.quantity, r.operation_name, r.total_amount, r.status) for r in db.query(PayrollRecord).order_by(PayrollRecord.id)]
        assert db.query(AuditLog).filter_by(action="correct_split_allocation").count() == 0


def test_split_correction_quantity_only_keeps_rounded_total(client, auth_headers):
    _, original, _, endpoint = setup_split(client, auth_headers)
    body = correction(client, auth_headers, endpoint)
    body["parts"][0]["quantity"] = 8
    body["parts"][1]["quantity"] = 12
    response = client.patch(endpoint, headers=auth_headers, json=body)
    assert response.status_code == 200, response.text
    assert sum(Decimal(row["total_amount"]) for row in response.json()["parts"]) == Decimal(original["total_amount"])


def test_text_or_employee_correction_preserves_each_existing_rounded_earning(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    other = _create_employee(client, auth_headers)
    label = issue(client, auth_headers, quantity=3)
    with TestSessionLocal() as db:
        source = db.query(PayrollQrLabel).filter_by(label_uid=label["label_uid"]).one()
        source.rate_per_piece = Decimal("0.005")
        db.commit()
    original = scan(client, auth_headers, label, employee).json()["record"]
    response = client.post(f"/api/payroll/records/{original['id']}/split", headers=auth_headers, json={"parts": [{"employee_id": employee["id"], "quantity": 1}] * 3})
    assert response.status_code == 200, response.text
    assert [Decimal(row["total_amount"]) for row in response.json()] == [Decimal("0"), Decimal("0"), Decimal("0.02")]
    with TestSessionLocal() as db:
        child = db.query(PayrollQrLabel).filter(PayrollQrLabel.split_from_label_id.isnot(None)).first()
        endpoint = f"/api/payroll/qr-labels/{child.id}/split-allocation"
    body = correction(client, auth_headers, endpoint)
    body["parts"][0].update(operation_name="Corrected description", employee_id=other["id"])
    updated = client.patch(endpoint, headers=auth_headers, json=body)
    assert updated.status_code == 200, updated.text
    assert [Decimal(row["total_amount"]) for row in updated.json()["parts"]] == [Decimal("0"), Decimal("0"), Decimal("0.02")]


def test_existing_nameless_split_can_be_loaded_and_corrected(client, auth_headers):
    _, _, _, endpoint = setup_split(client, auth_headers)
    with TestSessionLocal() as db:
        for label in db.query(PayrollQrLabel).filter(PayrollQrLabel.split_from_label_id.isnot(None)):
            label.operation_name = None
            db.get(PayrollRecord, label.payroll_record_id).operation_name = None
        db.commit()
    body = correction(client, auth_headers, endpoint)
    assert all(part["operation_name"] == "" for part in body["parts"])
    for part in body["parts"]:
        part["operation_name"] = "Named work"
    assert client.patch(endpoint, headers=auth_headers, json=body).status_code == 200


@pytest.mark.parametrize("invalid", ["negative_rate", "nan_rate", "rate_precision", "float_quantity", "unknown_field", "reason"])
def test_correction_input_boundaries(client, auth_headers, invalid):
    _, _, _, endpoint = setup_split(client, auth_headers)
    body = correction(client, auth_headers, endpoint)
    if invalid == "negative_rate":
        body["parts"][0]["rate_per_piece"] = "-1"
    elif invalid == "nan_rate":
        body["parts"][0]["rate_per_piece"] = "NaN"
    elif invalid == "rate_precision":
        body["parts"][0]["rate_per_piece"] = "1.12345"
    elif invalid == "float_quantity":
        body["parts"][0]["quantity"] = 7.5
    elif invalid == "unknown_field":
        body["parts"][0]["total_amount"] = "999999"
    else:
        body["reason"] = "  "
    assert client.patch(endpoint, headers=auth_headers, json=body).status_code == 422


def test_bounded_corrections_and_retries_do_not_mint_labels_records_or_pay(client, auth_headers):
    _, original, _, endpoint = setup_split(client, auth_headers)
    with TestSessionLocal() as db:
        before = (db.query(PayrollQrLabel).count(), db.query(PayrollRecord).count())
    for step in range(20):
        body = correction(client, auth_headers, endpoint)
        body["parts"][0]["quantity"] = 6 + step % 9
        body["parts"][1]["quantity"] = 20 - body["parts"][0]["quantity"]
        response = client.patch(endpoint, headers=auth_headers, json=body)
        assert response.status_code == 200, response.text
        assert sum(Decimal(part["total_amount"]) for part in response.json()["parts"]) == Decimal(original["total_amount"])
        retry = client.patch(endpoint, headers=auth_headers, json=body)
        assert retry.status_code == 200 and retry.json() == response.json()
    with TestSessionLocal() as db:
        assert before == (db.query(PayrollQrLabel).count(), db.query(PayrollRecord).count())
        assert db.query(AuditLog).filter_by(action="correct_split_allocation").count() == 20


@pytest.mark.parametrize(("old_name", "new_name", "expected"), [
    ("Sew", "Control", 409), ("Sew", "Nazorat", 409), ("Sew", "QC", 409),
    ("Control", "Sew", 409), ("Tepa kontrol", "Past kontrol", 200),
    ("Control", "Nazorat", 200),
])
def test_correction_preserves_control_review_classification(client, auth_headers, old_name, new_name, expected):
    _, _, _, endpoint = setup_split(client, auth_headers)
    with TestSessionLocal() as db:
        label = db.get(PayrollQrLabel, int(endpoint.split("/")[-2]))
        label.operation_name = old_name
        db.get(PayrollRecord, label.payroll_record_id).operation_name = old_name
        db.commit()
    body = correction(client, auth_headers, endpoint)
    body["parts"][0]["operation_name"] = new_name
    response = client.patch(endpoint, headers=auth_headers, json=body)
    assert response.status_code == expected, response.text


@pytest.mark.parametrize("employee_state", ["inactive", "other_factory"])
def test_correction_rejects_employee_outside_active_factory(client, auth_headers, employee_state):
    employees, _, _, endpoint = setup_split(client, auth_headers)
    body = correction(client, auth_headers, endpoint)
    body["parts"][0]["employee_id"] = employees[2]["id"]
    with TestSessionLocal() as db:
        employee = db.get(Employee, employees[2]["id"])
        if employee_state == "inactive":
            employee.status = "inactive"
        else:
            employee.factory_code = "ECO"
        db.commit()
    assert client.patch(endpoint, headers=auth_headers, json=body).status_code == 409


def test_mid_write_failure_rolls_back_all_labels_and_records(client, auth_headers, monkeypatch):
    from app.services import payroll_split_correction as service

    _, _, records, endpoint = setup_split(client, auth_headers)
    body = correction(client, auth_headers, endpoint)
    for part in body["parts"]:
        part["operation_name"] = "Must roll back"
    apply = service.apply_split_part_correction
    calls = []

    def failing_apply(*args, **kwargs):
        calls.append(kwargs["label"].id)
        apply(*args, **kwargs)
        if len(calls) == 2:
            raise RuntimeError("Injected persistence failure")

    monkeypatch.setattr(service, "apply_split_part_correction", failing_apply)
    with pytest.raises(RuntimeError, match="Injected persistence failure"):
        client.patch(endpoint, headers=auth_headers, json=body)
    with TestSessionLocal() as db:
        assert len(calls) == 2
        for record in records:
            assert db.get(PayrollRecord, record["id"]).operation_name == record["operation_name"]
        for part in body["parts"]:
            assert db.get(PayrollQrLabel, part["label_id"]).operation_name != "Must roll back"
        assert db.query(AuditLog).filter_by(action="correct_split_allocation").count() == 0


def test_group_split_again_requires_current_leaf_allocations(client, auth_headers):
    employees, _, records, endpoint = setup_split(client, auth_headers)
    body = correction(client, auth_headers, endpoint)
    nested = client.post(f"/api/payroll/records/{records[0]['id']}/split", headers=auth_headers, json={"parts": [
        {"employee_id": employees[0]["id"], "quantity": 3}, {"employee_id": employees[1]["id"], "quantity": 4},
    ]})
    assert nested.status_code == 200, nested.text
    assert client.patch(endpoint, headers=auth_headers, json=body).status_code == 409
