from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models import PayrollPeriod, PayrollQrLabel, PayrollRecord
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_employee, _create_user_with_permissions


def issue(client, headers, quantity=20):
    uid = f"PY:{uuid4().hex}"
    result = client.post("/api/payroll/qr-labels/issue", headers=headers, json={"labels": [{
        "label_uid": uid, "operation_section": "sewing", "operation_name": "Sew", "operation_code": "SEW",
        "quantity": quantity, "rate_per_piece": "1.2345", "currency": "UZS", "size": "L",
    }]})
    assert result.status_code == 200, result.text
    return result.json()["labels"][0]


def scan(client, headers, label, employee, **extra):
    return client.post("/api/payroll/scan/numeric-work", headers=headers, json={
        "token": label["qr_token"], "employee_id": employee["id"], **extra,
    })


def test_split_scanned_qr_credits_employees_once_and_preserves_money(client, auth_headers):
    first = _create_employee(client, auth_headers)
    second = _create_employee(client, auth_headers)
    label = issue(client, auth_headers)
    original = scan(client, auth_headers, label, first).json()["record"]
    body = {"parts": [{"employee_id": first["id"], "quantity": 7}, {"employee_id": second["id"], "quantity": 13}]}
    scanner = _create_user_with_permissions(client, auth_headers, email=f"split-{uuid4().hex}@example.com", permissions=["payroll.scan"])
    endpoint = f"/api/payroll/records/{original['id']}/split"
    response = client.post(endpoint, headers=scanner, json=body)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [(r["employee_id"], Decimal(r["quantity"])) for r in rows] == [(first["id"], 7), (second["id"], 13)]
    assert sum(Decimal(r["total_amount"]) for r in rows) == Decimal(original["total_amount"])
    assert all(r["scanned_at"] == original["scanned_at"] for r in rows)
    retry = client.post(endpoint, headers=scanner, json=body)
    assert retry.status_code == 200, retry.text
    assert [r["id"] for r in retry.json()] == [r["id"] for r in rows]
    assert scan(client, auth_headers, label, first).status_code == 409
    with TestSessionLocal() as db:
        source = db.query(PayrollQrLabel).filter_by(label_uid=label["label_uid"]).one()
        assert db.get(PayrollRecord, original["id"]).status == "voided"
        label_id = source.id
    assert client.post(f"/api/payroll/qr-labels/{label_id}/return", headers=auth_headers).status_code == 409


@pytest.mark.parametrize("invalid", ["quantity", "employee", "paid", "period", "unassigned_period", "permission", "factory"])
def test_split_rejects_unsafe_allocations_atomically(client, auth_headers, invalid):
    worker = _create_employee(client, auth_headers)
    label = issue(client, auth_headers)
    original = scan(client, auth_headers, label, worker).json()["record"]
    body = {"parts": [{"employee_id": worker["id"], "quantity": 10}, {"employee_id": worker["id"], "quantity": 10}]}
    headers = auth_headers
    if invalid == "quantity":
        body["parts"][0]["quantity"] = 11
    if invalid == "employee":
        body["parts"][1]["employee_id"] = 999999
    if invalid in {"permission", "factory"}:
        headers = _create_user_with_permissions(client, auth_headers, email=f"split-{uuid4().hex}@example.com",
                                                permissions=["payroll.view"] if invalid == "permission" else ["payroll.scan"],
                                                factory_code="ECO" if invalid == "factory" else "MIL")
    with TestSessionLocal() as db:
        record = db.get(PayrollRecord, original["id"])
        if invalid == "paid":
            record.status = "paid"
        if invalid in {"period", "unassigned_period"}:
            period = PayrollPeriod(factory_code="MIL", period_no=f"P-{uuid4().hex}", name="Locked", start_date=datetime.now(timezone.utc)-timedelta(days=1), end_date=datetime.now(timezone.utc)+timedelta(days=1), status="locked")
            db.add(period); db.flush()
            if invalid == "period":
                record.payroll_period_id = period.id
        db.commit()
        before = db.query(PayrollRecord).count()
    response = client.post(f"/api/payroll/records/{original['id']}/split", headers=headers, json=body)
    assert response.status_code in {403, 404, 409}, response.text
    with TestSessionLocal() as db:
        assert db.query(PayrollRecord).count() == before
        assert db.query(PayrollQrLabel).filter_by(label_uid=label["label_uid"]).one().status == "scanned"


@pytest.mark.parametrize("period_status", [None, "open", "locked", "approved", "paid"])
def test_chosen_work_date_uses_its_month_not_latest_open_period(client, auth_headers, period_status):
    worker = _create_employee(client, auth_headers)
    label = issue(client, auth_headers)
    with TestSessionLocal() as db:
        if period_status:
            previous = PayrollPeriod(factory_code="MIL", period_no=f"OLD-{uuid4().hex}", name="Previous", start_date=datetime(2025, 1, 1, tzinfo=timezone.utc), end_date=datetime(2025, 2, 1, tzinfo=timezone.utc), status=period_status)
            db.add(previous); db.flush(); previous_id = previous.id
        latest = PayrollPeriod(factory_code="MIL", period_no=f"NEW-{uuid4().hex}", name="New", start_date=datetime(2025, 2, 1, tzinfo=timezone.utc), end_date=datetime(2025, 3, 1, tzinfo=timezone.utc), status="open")
        db.add(latest); db.commit()
    response = scan(client, auth_headers, label, worker, work_date="2025-01-15")
    if period_status not in {None, "open"}:
        assert response.status_code == 409, response.text
    else:
        assert response.status_code == 201, response.text
        row = response.json()["record"]
        assert row["scanned_at"].startswith("2025-01-15T07:00:00")
        assert row["payroll_period_id"] == (previous_id if period_status else None)
        assert not row["created_at"].startswith("2025-01-15")
        split = client.post(f"/api/payroll/records/{row['id']}/split", headers=auth_headers, json={
            "parts": [{"employee_id": worker["id"], "quantity": 10}, {"employee_id": worker["id"], "quantity": 10}],
        })
        assert split.status_code == 200, split.text
        assert all(r["payroll_period_id"] == row["payroll_period_id"] and r["scanned_at"] == row["scanned_at"] for r in split.json())


def test_future_work_date_is_rejected(client, auth_headers):
    worker = _create_employee(client, auth_headers)
    label = issue(client, auth_headers)
    response = scan(client, auth_headers, label, worker, work_date="2099-01-01")
    assert response.status_code == 400, response.text
