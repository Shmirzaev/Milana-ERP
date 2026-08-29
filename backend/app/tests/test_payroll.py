from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models import Employee
from app.tests.conftest import TestSessionLocal


STRONG_PW = "PayrollTest123!"


def _login(client, email: str, password: str = STRONG_PW) -> dict[str, str]:
    r = client.post("/api/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_user_with_permissions(
    client,
    admin_headers,
    *,
    email: str,
    permissions: list[str],
    factory_code: str = "MIL",
) -> dict[str, str]:
    role = client.post(
        "/api/roles",
        json={"name": f"Payroll Role {email}", "permissions": permissions},
        headers=admin_headers,
    )
    assert role.status_code == 201, role.text
    user = client.post(
        "/api/users",
        json={
            "name": email.split("@", 1)[0],
            "email": email,
            "password": STRONG_PW,
            "role_id": role.json()["id"],
            "factory_code": factory_code,
            "is_active": True,
        },
        headers=admin_headers,
    )
    assert user.status_code == 201, user.text
    return _login(client, email)


def _create_employee(client, admin_headers, name: str | None = None) -> dict:
    r = client.post(
        "/api/employees",
        json={
            "full_name": name or f"Payroll Worker {uuid4().hex[:8]}",
            "position": "Operator",
            "status": "active",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_period(client, headers, *, status: str = "open") -> dict:
    now = datetime.now(timezone.utc)
    r = client.post(
        "/api/payroll/periods",
        json={
            "name": f"Payroll {uuid4().hex[:8]}",
            "start_date": (now - timedelta(days=5)).isoformat(),
            "end_date": (now + timedelta(days=5)).isoformat(),
            "status": status,
            "notes": "test period",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_employee_number_is_printable_and_resolves_for_payroll_scan(client, auth_headers):
    employee = _create_employee(client, auth_headers, "Employee Number Worker")
    employee_no = f"EMP-NO-{uuid4().hex[:8].upper()}"
    with TestSessionLocal() as db:
        row = db.get(Employee, employee["id"])
        assert row is not None
        row.employee_no = employee_no
        db.commit()

    listed = client.get("/api/employees", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    listed_employee = next(row for row in listed.json() if row["id"] == employee["id"])
    assert listed_employee["employee_no"] == employee_no

    resolved = client.get(
        "/api/payroll/employees/resolve",
        params={"employee_no": employee_no.lower()},
        headers=auth_headers,
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["type"] == "employee_payroll"
    assert resolved.json()["employee_id"] == employee["id"]
    assert resolved.json()["employee_no"] == employee_no
    assert resolved.json()["badge_id"] == employee_no.lower()

    legacy_token = f"1{employee['id']:08d}"
    legacy = client.get(f"/api/payroll/qr/resolve/{legacy_token}", headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["employee_id"] == employee["id"]
    assert legacy.json()["employee_no"] == employee_no

    missing = client.get(
        "/api/payroll/employees/resolve",
        params={"employee_no": f"MISSING-{uuid4().hex[:12]}"},
        headers=auth_headers,
    )
    assert missing.status_code == 404, missing.text


def test_seeded_payroll_access_policy(client, auth_headers):
    roles = client.get("/api/roles", headers=auth_headers)
    assert roles.status_code == 200, roles.text
    role_by_name = {role["name"]: role for role in roles.json()}

    depts = client.get("/api/departments", headers=auth_headers)
    assert depts.status_code == 200, depts.text
    dept_by_code = {dept["code"]: dept for dept in depts.json()}

    assert "PAY" in dept_by_code
    assert dept_by_code["PAY"]["name"] == "Payroll"
    assert role_by_name["Payroll"]["permissions"] == [
        "payroll.view",
        "payroll.manage",
        "payroll.scan",
        "sewing.daily_reports.view",
    ]

    payroll_locked_roles = [
        "Management",
        "Planning",
        "Cutting",
        "Printing",
        "Sewing",
        "Packaging",
        "Finance",
        "HR",
    ]
    for role_name in payroll_locked_roles:
        assert role_name in role_by_name
        assert not [
            permission for permission in role_by_name[role_name]["permissions"]
            if permission.startswith("payroll.")
        ], role_name


def test_payroll_role_can_access_workspace_and_save_scan_records(client, auth_headers):
    employee = _create_employee(client, auth_headers)

    roles = client.get("/api/roles", headers=auth_headers).json()
    payroll_role_id = next(role["id"] for role in roles if role["name"] == "Payroll")
    depts = client.get("/api/departments", headers=auth_headers).json()
    payroll_dept_id = next(dept["id"] for dept in depts if dept["code"] == "PAY")

    email = f"payroll.role.{uuid4().hex[:8]}@example.com"
    created = client.post(
        "/api/users",
        json={
            "name": "Payroll Scan Counter",
            "email": email,
            "password": STRONG_PW,
            "role_id": payroll_role_id,
            "department_id": payroll_dept_id,
            "is_active": True,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    scanner_headers = _login(client, email)
    record = client.post(
        "/api/payroll/records",
        json=_record_payload(employee["id"], scan_uid=f"payroll-role-{uuid4().hex}"),
        headers=scanner_headers,
    )
    assert record.status_code == 201, record.text

    records = client.get("/api/payroll/records", headers=scanner_headers)
    assert records.status_code == 200, records.text

    summary = client.get("/api/payroll/summary", headers=scanner_headers)
    assert summary.status_code == 200, summary.text

    qr_control = client.get("/api/payroll/qr-labels", headers=scanner_headers)
    assert qr_control.status_code == 200, qr_control.text


def test_seed_removes_legacy_payroll_access_from_non_admins(client, auth_headers):
    email = f"legacy.payroll.{uuid4().hex[:8]}@example.com"
    role = client.post(
        "/api/roles",
        json={
            "name": f"Legacy Payroll Access {uuid4().hex[:8]}",
            "permissions": ["finance.view", "payroll.view", "payroll.scan"],
        },
        headers=auth_headers,
    )
    assert role.status_code == 201, role.text

    user = client.post(
        "/api/users",
        json={
            "name": "Legacy Payroll Extra",
            "email": email,
            "password": STRONG_PW,
            "role_id": role.json()["id"],
            "extra_permissions": ["storage.items", "payroll.manage"],
            "is_active": True,
        },
        headers=auth_headers,
    )
    assert user.status_code == 201, user.text

    from app.db.seed import seed

    seed()

    roles = client.get("/api/roles", headers=auth_headers).json()
    cleaned_role = next(row for row in roles if row["id"] == role.json()["id"])
    assert cleaned_role["permissions"] == ["finance.view"]

    users = client.get("/api/users", headers=auth_headers).json()
    cleaned_user = next(row for row in users if row["email"] == email)
    assert cleaned_user["extra_permissions"] == ["storage.items"]


def _record_payload(employee_id: int, *, scan_uid: str | None = None, scanned_at: datetime | None = None) -> dict:
    uid = scan_uid or f"scan-{uuid4().hex}"
    return {
        "scan_uid": uid,
        "employee": {
            "type": "employee_payroll",
            "employee_id": employee_id,
            "employee_name": f"Employee {employee_id}",
        },
        "work": {
            "type": "process_payroll",
            "label_id": uid,
            "production_no": "PO-PAYROLL-TEST",
            "batch_no": "BT-PAYROLL-01",
            "model_code": "PAY-MODEL",
            "operation_section": "sewing",
            "operation_code": "SEW-PAY",
            "operation_name": "Payroll sewing",
        },
        "employee_id": employee_id,
        "scanned_at": (scanned_at or datetime.now(timezone.utc)).isoformat(),
        "quantity": 10,
        "rate_per_piece": 250,
        "currency": "UZS",
    }


def test_create_payroll_period(client, auth_headers):
    period = _create_period(client, auth_headers)
    assert period["period_no"].startswith("PAY-")
    assert period["status"] == "open"


def test_create_payroll_record(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    r = client.post("/api/payroll/records", json=_record_payload(employee["id"]), headers=auth_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["employee_id"] == employee["id"]
    assert float(body["total_amount"]) == 2500
    assert body["status"] == "recorded"


def test_compact_work_payload_preserves_size(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    payload = _record_payload(employee["id"], scan_uid=f"size-{uuid4().hex}")
    payload["work"] = (
        "MW2*-*PO-SIZE*-*BT-SIZE*1*MODEL-SIZE*sewing*SEW-SIZE*Size sewing*12*250*UZS*1"
        "*-*SO-SIZE*-*-*LABEL-SIZE-L*L*12*SEW-12*Line 12*34*KR-7788"
    )
    payload["quantity"] = None
    payload["rate_per_piece"] = None

    response = client.post("/api/payroll/records", json=payload, headers=auth_headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert float(body["quantity"]) == 12
    assert float(body["rate_per_piece"]) == 250
    assert body["raw_work_json"]["label_id"] == "LABEL-SIZE-L"
    assert body["batch_no"] == "SIZE"
    assert body["raw_work_json"]["batch_no"] == "SIZE"
    assert body["raw_work_json"]["size"] == "L"
    assert body["raw_work_json"]["sewing_flow_id"] == 12
    assert body["raw_work_json"]["sewing_line_code"] == "SEW-12"
    assert body["raw_work_json"]["sewing_line_name"] == "Line 12"
    assert body["raw_work_json"]["cutting_passport_id"] == 34
    assert body["raw_work_json"]["cutting_passport_no"] == "KR-7788"


def test_bulk_create_records_and_scan_uid_idempotency(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    first = _record_payload(employee["id"], scan_uid=f"bulk-{uuid4().hex}")
    second = _record_payload(employee["id"], scan_uid=f"bulk-{uuid4().hex}")

    bulk = client.post("/api/payroll/records/bulk", json={"records": [first, second]}, headers=auth_headers)
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["created_count"] == 2

    duplicate = client.post("/api/payroll/records", json=first, headers=auth_headers)
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["id"] == bulk.json()["records"][0]["id"]


def test_summary_groups_by_employee(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    client.post("/api/payroll/records", json=_record_payload(employee["id"], scan_uid=f"sum-{uuid4().hex}"), headers=auth_headers)
    client.post("/api/payroll/records", json=_record_payload(employee["id"], scan_uid=f"sum-{uuid4().hex}"), headers=auth_headers)

    summary = client.get(f"/api/payroll/summary?employee_id={employee['id']}", headers=auth_headers)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["records_count"] == 2
    assert float(body["quantity"]) == 20
    assert float(body["total_amount"]) == 5000
    assert len(body["employees"]) == 1
    assert body["employees"][0]["employee_id"] == employee["id"]
    assert body["employees"][0]["operations"]


def test_adjustments_affect_summary_totals(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    period = _create_period(client, auth_headers)
    payload = _record_payload(employee["id"], scan_uid=f"adjust-total-{uuid4().hex}")
    payload["payroll_period_id"] = period["id"]
    created = client.post("/api/payroll/records", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text

    bonus = client.post(
        "/api/payroll/adjustments",
        json={
            "payroll_period_id": period["id"],
            "employee_id": employee["id"],
            "adjustment_type": "bonus",
            "amount": 500,
            "reason": "attendance bonus",
        },
        headers=auth_headers,
    )
    assert bonus.status_code == 201, bonus.text
    assert float(bonus.json()["signed_amount"]) == 500

    deduction = client.post(
        "/api/payroll/adjustments",
        json={
            "payroll_period_id": period["id"],
            "employee_id": employee["id"],
            "adjustment_type": "deduction",
            "amount": 200,
            "reason": "advance recovery",
        },
        headers=auth_headers,
    )
    assert deduction.status_code == 201, deduction.text
    assert float(deduction.json()["signed_amount"]) == -200

    summary = client.get(f"/api/payroll/summary?period_id={period['id']}&employee_id={employee['id']}", headers=auth_headers)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["records_count"] == 1
    assert body["adjustment_count"] == 2
    assert float(body["piecework_amount"]) == 2500
    assert float(body["bonus_amount"]) == 500
    assert float(body["deduction_amount"]) == 200
    assert float(body["adjustment_amount"]) == 300
    assert float(body["total_amount"]) == 2800
    employee_total = body["employees"][0]
    assert employee_total["employee_id"] == employee["id"]
    assert employee_total["adjustment_count"] == 2
    assert float(employee_total["piecework_amount"]) == 2500
    assert float(employee_total["adjustment_amount"]) == 300
    assert float(employee_total["total_amount"]) == 2800


@pytest.mark.parametrize("status", ["locked", "approved", "paid", "cancelled"])
def test_adjustments_rejected_for_finalized_periods(client, auth_headers, status):
    employee = _create_employee(client, auth_headers)
    period = _create_period(client, auth_headers)
    if status == "locked":
        response = client.post(f"/api/payroll/periods/{period['id']}/lock", headers=auth_headers)
    elif status == "approved":
        locked = client.post(f"/api/payroll/periods/{period['id']}/lock", headers=auth_headers)
        assert locked.status_code == 200, locked.text
        response = client.post(f"/api/payroll/periods/{period['id']}/approve", headers=auth_headers)
    elif status == "paid":
        locked = client.post(f"/api/payroll/periods/{period['id']}/lock", headers=auth_headers)
        assert locked.status_code == 200, locked.text
        approved = client.post(f"/api/payroll/periods/{period['id']}/approve", headers=auth_headers)
        assert approved.status_code == 200, approved.text
        response = client.post(f"/api/payroll/periods/{period['id']}/mark-paid", headers=auth_headers)
    else:
        response = client.patch(f"/api/payroll/periods/{period['id']}", json={"status": "cancelled"}, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == status

    denied = client.post(
        "/api/payroll/adjustments",
        json={
            "payroll_period_id": period["id"],
            "employee_id": employee["id"],
            "adjustment_type": "bonus",
            "amount": 100,
            "reason": "closed period change",
        },
        headers=auth_headers,
    )
    assert denied.status_code == 409, denied.text


def test_paid_record_reversal_posts_one_audited_deduction_to_open_period(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    source_period = _create_period(client, auth_headers)
    target_period = _create_period(client, auth_headers)
    payload = _record_payload(employee["id"], scan_uid=f"reversal-{uuid4().hex}")
    payload["payroll_period_id"] = source_period["id"]
    created = client.post("/api/payroll/records", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text

    locked = client.post(f"/api/payroll/periods/{source_period['id']}/lock", headers=auth_headers)
    assert locked.status_code == 200, locked.text
    approved = client.post(f"/api/payroll/periods/{source_period['id']}/approve", headers=auth_headers)
    assert approved.status_code == 200, approved.text
    paid = client.post(f"/api/payroll/periods/{source_period['id']}/mark-paid", headers=auth_headers)
    assert paid.status_code == 200, paid.text

    reversal = client.post(
        f"/api/payroll/records/{created.json()['id']}/reverse-as-adjustment",
        json={"target_period_id": target_period["id"], "reason": "Duplicate work confirmed after payment"},
        headers=auth_headers,
    )
    assert reversal.status_code == 201, reversal.text
    body = reversal.json()
    assert body["source_payroll_record_id"] == created.json()["id"]
    assert body["payroll_period_id"] == target_period["id"]
    assert body["employee_id"] == employee["id"]
    assert body["adjustment_type"] == "deduction"
    assert float(body["amount"]) == 2500
    assert float(body["signed_amount"]) == -2500

    duplicate = client.post(
        f"/api/payroll/records/{created.json()['id']}/reverse-as-adjustment",
        json={"target_period_id": target_period["id"], "reason": "Second reversal attempt"},
        headers=auth_headers,
    )
    assert duplicate.status_code == 409, duplicate.text

    source_records = client.get(
        f"/api/payroll/records?period_id={source_period['id']}&employee_id={employee['id']}",
        headers=auth_headers,
    )
    assert source_records.status_code == 200, source_records.text
    assert source_records.json()[0]["status"] == "paid"

    target_summary = client.get(
        f"/api/payroll/summary?period_id={target_period['id']}&employee_id={employee['id']}",
        headers=auth_headers,
    )
    assert target_summary.status_code == 200, target_summary.text
    assert float(target_summary.json()["total_amount"]) == -2500

    from app.models import AuditLog

    with TestSessionLocal() as db:
        audit = db.query(AuditLog).filter(
            AuditLog.action == "create_reversal_adjustment",
            AuditLog.entity_type == "PayrollAdjustment",
            AuditLog.entity_id == body["id"],
        ).one()
        assert audit.new_value_json["source_payroll_record_id"] == created.json()["id"]
        assert audit.new_value_json["target_payroll_period_id"] == target_period["id"]


def test_open_record_must_be_voided_instead_of_reversed(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    source_period = _create_period(client, auth_headers)
    target_period = _create_period(client, auth_headers)
    payload = _record_payload(employee["id"], scan_uid=f"open-reversal-{uuid4().hex}")
    payload["payroll_period_id"] = source_period["id"]
    created = client.post("/api/payroll/records", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text

    denied = client.post(
        f"/api/payroll/records/{created.json()['id']}/reverse-as-adjustment",
        json={"target_period_id": target_period["id"], "reason": "Should use void"},
        headers=auth_headers,
    )
    assert denied.status_code == 409, denied.text
    assert "Use Void" in denied.text


def test_duplicate_work_qr_for_different_employee_is_rejected(client, auth_headers):
    first_employee = _create_employee(client, auth_headers)
    second_employee = _create_employee(client, auth_headers)
    scan_uid = f"same-work-{uuid4().hex}"
    first = client.post("/api/payroll/records", json=_record_payload(first_employee["id"], scan_uid=scan_uid), headers=auth_headers)
    assert first.status_code == 201, first.text

    second_payload = _record_payload(second_employee["id"], scan_uid=scan_uid)
    denied = client.post("/api/payroll/records", json=second_payload, headers=auth_headers)
    assert denied.status_code == 409, denied.text
    assert "already recorded" in denied.text


def test_payroll_qr_control_tracks_issued_and_scanned_labels(client, auth_headers):
    employee = _create_employee(client, auth_headers, "QR Control Worker")
    label_uid = f"PY:{uuid4().hex}"
    issued = client.post(
        "/api/payroll/qr-labels/issue",
        json={
            "labels": [{
                "label_uid": label_uid,
                "payload": "MW2*test",
                "sales_order_no": "SO-QR-CONTROL",
                "batch_no": "BT-QR-CONTROL",
                "model_code": "MODEL-QR",
                "operation_section": "sewing",
                "operation_code": "SEW-QR",
                "operation_name": "QR control sewing",
                "sewing_line_code": "SEW-07",
                "sewing_line_name": "Jalilova",
                "cutting_passport_no": "KR-QR-07",
                "size": "L",
                "copy_index": 1,
                "quantity": 12,
                "rate_per_piece": 250,
                "currency": "UZS",
            }],
        },
        headers=auth_headers,
    )
    assert issued.status_code == 200, issued.text
    assert issued.json()["issued_count"] == 1
    assert issued.json()["created_count"] == 1
    assert issued.json()["existing_count"] == 0
    issued_label = issued.json()["labels"][0]
    assert issued_label["label_uid"] == label_uid
    assert len(issued_label["qr_token"]) == 9
    assert issued_label["qr_token"].isdigit()
    assert issued_label["qr_token"].startswith("2")

    reissued = client.post(
        "/api/payroll/qr-labels/issue",
        json={
            "labels": [{
                "label_uid": label_uid,
                "payload": "MW2*changed",
                "sales_order_no": "SO-SHOULD-NOT-REPLACE",
                "operation_code": "CHANGED",
                "quantity": 999,
                "rate_per_piece": 999,
            }],
        },
        headers=auth_headers,
    )
    assert reissued.status_code == 200, reissued.text
    assert reissued.json()["issued_count"] == 1
    assert reissued.json()["created_count"] == 0
    assert reissued.json()["existing_count"] == 1
    assert reissued.json()["labels"] == [issued_label]

    listed_for_order = client.get(
        "/api/payroll/qr-labels",
        params={"production_order_id": 999999, "limit": 5000},
        headers=auth_headers,
    )
    assert listed_for_order.status_code == 200, listed_for_order.text
    assert listed_for_order.json()["total"] == 0

    listed = client.get(
        "/api/payroll/qr-labels",
        params={"search": label_uid, "limit": 5000},
        headers=auth_headers,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["operation_code"] == "SEW-QR"
    assert float(listed.json()["items"][0]["quantity"]) == 12

    resolved_work = client.get(
        f"/api/payroll/qr/resolve/{issued_label['qr_token']}",
        headers=auth_headers,
    )
    assert resolved_work.status_code == 200, resolved_work.text
    assert resolved_work.json()["type"] == "process_payroll"
    assert resolved_work.json()["label_id"] == label_uid
    assert resolved_work.json()["operation_code"] == "SEW-QR"
    assert float(resolved_work.json()["quantity"]) == 12
    assert resolved_work.json()["sewing_line_code"] == "SEW-07"

    employee_token = f"1{employee['id']:08d}"
    resolved_employee = client.get(
        f"/api/payroll/qr/resolve/{employee_token}",
        headers=auth_headers,
    )
    assert resolved_employee.status_code == 200, resolved_employee.text
    assert resolved_employee.json()["type"] == "employee_payroll"
    assert resolved_employee.json()["employee_id"] == employee["id"]
    assert resolved_employee.json()["employee_name"] == "QR Control Worker"

    available = client.get(f"/api/payroll/qr-labels?search={label_uid}", headers=auth_headers)
    assert available.status_code == 200, available.text
    assert available.json()["total"] == 1
    assert available.json()["items"][0]["status"] == "available"
    assert available.json()["items"][0]["payload"] == "MW2*test"
    assert available.json()["items"][0]["qr_token"] == issued_label["qr_token"]
    assert available.json()["items"][0]["sewing_line_code"] == "SEW-07"
    assert available.json()["items"][0]["sewing_line_name"] == "Jalilova"
    assert available.json()["items"][0]["cutting_passport_no"] == "KR-QR-07"

    order_group = client.get("/api/payroll/qr-labels?order_no=SO-QR-CONTROL&limit=5000", headers=auth_headers)
    assert order_group.status_code == 200, order_group.text
    assert order_group.json()["total"] == 1
    assert order_group.json()["items"][0]["label_uid"] == label_uid

    scan_payload = _record_payload(employee["id"], scan_uid=f"payroll:{label_uid}")
    scan_payload["work"]["label_id"] = label_uid
    scanned = client.post(
        "/api/payroll/records",
        json=scan_payload,
        headers=auth_headers,
    )
    assert scanned.status_code == 201, scanned.text
    assert scanned.json()["scan_uid"] == label_uid

    control = client.get(f"/api/payroll/qr-labels?search={label_uid}", headers=auth_headers)
    row = control.json()["items"][0]
    assert row["status"] == "scanned"
    assert row["employee_id"] == employee["id"]
    assert row["employee_name"] == "QR Control Worker"
    assert row["payroll_record_id"] == scanned.json()["id"]


def test_numeric_work_scan_resolves_and_records_atomically(client, auth_headers):
    employee = _create_employee(client, auth_headers, "Atomic QR Worker")
    other_employee = _create_employee(client, auth_headers, "Other Atomic QR Worker")
    label_uid = f"PY:{uuid4().hex}"
    issued = client.post(
        "/api/payroll/qr-labels/issue",
        json={
            "labels": [{
                "label_uid": label_uid,
                "sales_order_no": "SO-ATOMIC-SCAN",
                "batch_no": "BT-ATOMIC-SCAN",
                "model_code": "MODEL-ATOMIC",
                "operation_section": "sewing",
                "operation_code": "SEW-ATOMIC",
                "operation_name": "Atomic scan sewing",
                "size": "L",
                "copy_index": 1,
                "quantity": 12,
                "rate_per_piece": 250,
                "currency": "UZS",
            }],
        },
        headers=auth_headers,
    )
    assert issued.status_code == 200, issued.text
    qr_token = issued.json()["labels"][0]["qr_token"]
    scanned_at = datetime.now(timezone.utc).isoformat()

    created = client.post(
        "/api/payroll/scan/numeric-work",
        json={"token": qr_token, "employee_id": employee["id"], "scanned_at": scanned_at},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["record"]["duplicate"] is False
    assert body["record"]["employee_id"] == employee["id"]
    assert body["record"]["scan_uid"] == label_uid
    assert body["record"]["operation_code"] == "SEW-ATOMIC"
    assert float(body["record"]["quantity"]) == 12
    assert body["work"]["label_id"] == label_uid
    assert body["work"]["label_status"] == "scanned"

    duplicate = client.post(
        "/api/payroll/scan/numeric-work",
        json={"token": qr_token, "employee_id": employee["id"], "scanned_at": scanned_at},
        headers=auth_headers,
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["record"]["duplicate"] is True
    assert duplicate.json()["record"]["id"] == body["record"]["id"]

    wrong_employee = client.post(
        "/api/payroll/scan/numeric-work",
        json={"token": qr_token, "employee_id": other_employee["id"]},
        headers=auth_headers,
    )
    assert wrong_employee.status_code == 409, wrong_employee.text
    assert "already recorded" in wrong_employee.text

    bad_token = client.post(
        "/api/payroll/scan/numeric-work",
        json={"token": f"1{employee['id']:08d}", "employee_id": employee["id"]},
        headers=auth_headers,
    )
    assert bad_token.status_code == 400, bad_token.text


def test_qr_size_batch_delete_requires_every_label_to_be_never_scanned(client, auth_headers):
    employee = _create_employee(client, auth_headers, "QR Delete Safety Worker")
    order_no = f"SO-QR-DELETE-{uuid4().hex[:8]}"
    small_uids = [f"PY:{uuid4().hex}" for _ in range(2)]
    medium_uids = [f"PY:{uuid4().hex}" for _ in range(2)]
    label_rows = [
        {
            "label_uid": label_uid,
            "sales_order_no": order_no,
            "production_no": f"PO-{order_no}",
            "operation_section": "sewing",
            "operation_code": f"OP-{index + 1}",
            "operation_name": f"Delete-safe operation {index + 1}",
            "size": size,
            "copy_index": 1,
            "quantity": 10,
            "rate_per_piece": 100,
            "currency": "UZS",
        }
        for size, uids in (("S", small_uids), ("M", medium_uids))
        for index, label_uid in enumerate(uids)
    ]
    issued = client.post("/api/payroll/qr-labels/issue", json={"labels": label_rows}, headers=auth_headers)
    assert issued.status_code == 200, issued.text

    listed = client.get(
        "/api/payroll/qr-labels",
        params={"order_no": order_no, "limit": 5000},
        headers=auth_headers,
    )
    assert listed.status_code == 200, listed.text
    rows_by_uid = {row["label_uid"]: row for row in listed.json()["items"]}

    deleted = client.post(
        "/api/payroll/qr-labels/delete-batch",
        json={"size": "M", "label_ids": [rows_by_uid[label_uid]["id"] for label_uid in medium_uids]},
        headers=auth_headers,
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"deleted_count": 2, "size": "M"}

    first_small_uid = small_uids[0]
    scan_payload = _record_payload(employee["id"], scan_uid=first_small_uid)
    scan_payload["work"].update({
        "label_id": first_small_uid,
        "sales_order_no": order_no,
        "production_no": f"PO-{order_no}",
        "size": "S",
    })
    scanned = client.post("/api/payroll/records", json=scan_payload, headers=auth_headers)
    assert scanned.status_code == 201, scanned.text

    blocked = client.post(
        "/api/payroll/qr-labels/delete-batch",
        json={"size": "S", "label_ids": [rows_by_uid[label_uid]["id"] for label_uid in small_uids]},
        headers=auth_headers,
    )
    assert blocked.status_code == 409, blocked.text
    assert "never-scanned" in blocked.text

    remaining = client.get(
        "/api/payroll/qr-labels",
        params={"order_no": order_no, "limit": 5000},
        headers=auth_headers,
    )
    assert remaining.status_code == 200, remaining.text
    assert {row["label_uid"] for row in remaining.json()["items"]} == set(small_uids)


def test_qr_label_edit_keeps_identity_and_split_supersedes_old_qr(client, auth_headers):
    employee = _create_employee(client, auth_headers, "QR Edit Split Worker")
    order_no = f"SO-QR-EDIT-{uuid4().hex[:8]}"
    label_uid = f"OERP-SEW-{uuid4().hex.upper()}"
    issued = client.post(
        "/api/payroll/qr-labels/issue",
        json={
            "labels": [{
                "label_uid": label_uid,
                "sales_order_no": order_no,
                "production_no": f"PO-{order_no}",
                "operation_section": "sewing",
                "operation_code": "OP-EDIT",
                "operation_name": "Original operation",
                "size": "M",
                "copy_index": 1,
                "quantity": 100,
                "rate_per_piece": 200,
                "currency": "UZS",
            }],
        },
        headers=auth_headers,
    )
    assert issued.status_code == 200, issued.text
    original = client.get(
        "/api/payroll/qr-labels",
        params={"order_no": order_no, "limit": 100},
        headers=auth_headers,
    ).json()["items"][0]

    edited = client.patch(
        f"/api/payroll/qr-labels/{original['id']}",
        json={"operation_name": "Corrected operation", "rate_per_piece": 275},
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["qr_token"] == original["qr_token"]
    assert edited.json()["label_uid"] == label_uid
    assert edited.json()["operation_name"] == "Corrected operation"
    assert float(edited.json()["rate_per_piece"]) == 275

    resolved_edit = client.get(f"/api/payroll/qr/resolve/{original['qr_token']}", headers=auth_headers)
    assert resolved_edit.status_code == 200, resolved_edit.text
    assert resolved_edit.json()["operation_name"] == "Corrected operation"
    assert float(resolved_edit.json()["rate_per_piece"]) == 275

    invalid_split = client.post(
        f"/api/payroll/qr-labels/{original['id']}/split",
        json={
            "operation_name": "Split operation",
            "rate_per_piece": 300,
            "quantities": [40, 50],
        },
        headers=auth_headers,
    )
    assert invalid_split.status_code == 409, invalid_split.text

    split = client.post(
        f"/api/payroll/qr-labels/{original['id']}/split",
        json={
            "operation_name": "Split operation",
            "rate_per_piece": 300,
            "quantities": [40, 60],
        },
        headers=auth_headers,
    )
    assert split.status_code == 200, split.text
    split_body = split.json()
    assert split_body["superseded_label_id"] == original["id"]
    assert [int(float(row["quantity"])) for row in split_body["labels"]] == [40, 60]
    assert len({row["id"] for row in split_body["labels"]}) == 2
    assert len({row["qr_token"] for row in split_body["labels"]}) == 2
    assert original["qr_token"] not in {row["qr_token"] for row in split_body["labels"]}
    assert all(row["operation_name"] == "Split operation" for row in split_body["labels"])
    assert all(float(row["rate_per_piece"]) == 300 for row in split_body["labels"])

    old_resolve = client.get(f"/api/payroll/qr/resolve/{original['qr_token']}", headers=auth_headers)
    assert old_resolve.status_code == 409, old_resolve.text
    assert "split labels" in old_resolve.text

    superseded = client.get(
        "/api/payroll/qr-labels",
        params={"order_no": order_no, "status": "superseded", "limit": 100},
        headers=auth_headers,
    )
    assert superseded.status_code == 200, superseded.text
    assert [row["id"] for row in superseded.json()["items"]] == [original["id"]]
    with_tombstone = client.get(
        "/api/payroll/qr-labels",
        params={"order_no": order_no, "include_superseded": True, "limit": 100},
        headers=auth_headers,
    )
    assert with_tombstone.status_code == 200, with_tombstone.text
    assert {row["id"] for row in with_tombstone.json()["items"]} == {
        original["id"],
        *(row["id"] for row in split_body["labels"]),
    }
    active = client.get(
        "/api/payroll/qr-labels",
        params={"order_no": order_no, "limit": 100},
        headers=auth_headers,
    )
    assert active.status_code == 200, active.text
    assert {row["id"] for row in active.json()["items"]} == {
        row["id"] for row in split_body["labels"]
    }

    order_report = client.get(
        "/api/payroll/reports/order-qr-status",
        params={"order_no": order_no, "limit": 100},
        headers=auth_headers,
    )
    assert order_report.status_code == 200, order_report.text
    assert order_report.json()["total_labels"] == 2
    assert float(order_report.json()["total_quantity"]) == 100

    cached_old_payload = _record_payload(employee["id"], scan_uid=label_uid)
    cached_old = client.post("/api/payroll/records", json=cached_old_payload, headers=auth_headers)
    assert cached_old.status_code == 409, cached_old.text

    first_child = split_body["labels"][0]
    child_payload = _record_payload(employee["id"], scan_uid=first_child["label_uid"])
    child_payload["quantity"] = 999
    child_payload["rate_per_piece"] = 1
    child_payload["operation_name"] = "Client override must be ignored"
    child_payload["work"]["operation_name"] = "Client override must be ignored"
    scanned_child = client.post("/api/payroll/records", json=child_payload, headers=auth_headers)
    assert scanned_child.status_code == 201, scanned_child.text
    assert float(scanned_child.json()["quantity"]) == 40
    assert float(scanned_child.json()["rate_per_piece"]) == 300
    assert float(scanned_child.json()["total_amount"]) == 12000
    assert scanned_child.json()["operation_name"] == "Split operation"

    blocked_edit = client.patch(
        f"/api/payroll/qr-labels/{first_child['id']}",
        json={"operation_name": "Unsafe edit", "rate_per_piece": 1},
        headers=auth_headers,
    )
    assert blocked_edit.status_code == 409, blocked_edit.text


def test_order_qr_status_report_filters_exact_order_and_builds_matrix(client, auth_headers):
    employee = _create_employee(client, auth_headers, "Order QR Report Worker")
    order_no = f"SO-QR-REPORT-{uuid4().hex[:8]}"
    other_order = f"{order_no}-OTHER"
    label_rows = [
        {
            "label_uid": f"PY:{uuid4().hex}",
            "sales_order_no": order_no,
            "production_no": "PO-QR-REPORT-1",
            "batch_no": "101",
            "model_code": "QR-MATRIX",
            "operation_section": "sewing",
            "operation_code": "OP-A",
            "operation_name": "Attach collar",
            "size": "S",
            "copy_index": 1,
            "quantity": 40,
            "rate_per_piece": 100,
            "currency": "UZS",
        },
        {
            "label_uid": f"PY:{uuid4().hex}",
            "sales_order_no": order_no,
            "production_no": "PO-QR-REPORT-1",
            "batch_no": "101",
            "model_code": "QR-MATRIX",
            "operation_section": "sewing",
            "operation_code": "OP-A",
            "operation_name": "Attach collar",
            "size": "S",
            "copy_index": 2,
            "quantity": 40,
            "rate_per_piece": 100,
            "currency": "UZS",
        },
        {
            "label_uid": f"PY:{uuid4().hex}",
            "sales_order_no": order_no,
            "production_no": "PO-QR-REPORT-1",
            "batch_no": "101",
            "model_code": "QR-MATRIX",
            "operation_section": "sewing",
            "operation_code": "OP-B",
            "operation_name": "Finish sleeve",
            "size": "M",
            "copy_index": 1,
            "quantity": 30,
            "rate_per_piece": 120,
            "currency": "UZS",
        },
        {
            "label_uid": f"PY:{uuid4().hex}",
            "sales_order_no": other_order,
            "production_no": "PO-QR-REPORT-OTHER",
            "model_code": "QR-OTHER",
            "operation_code": "OP-X",
            "operation_name": "Other order work",
            "size": "L",
            "copy_index": 1,
            "quantity": 99,
            "rate_per_piece": 1,
            "currency": "UZS",
        },
    ]
    issued = client.post("/api/payroll/qr-labels/issue", json={"labels": label_rows}, headers=auth_headers)
    assert issued.status_code == 200, issued.text

    first_uid = label_rows[0]["label_uid"]
    scan_payload = _record_payload(employee["id"], scan_uid=f"payroll:{first_uid}")
    scan_payload["sales_order_no"] = order_no
    scan_payload["production_no"] = "PO-QR-REPORT-1"
    scan_payload["model_code"] = "QR-MATRIX"
    scan_payload["operation_section"] = "sewing"
    scan_payload["operation_code"] = "OP-A"
    scan_payload["operation_name"] = "Attach collar"
    scan_payload["quantity"] = 40
    scan_payload["rate_per_piece"] = 100
    scan_payload["work"].update({
        "label_id": first_uid,
        "sales_order_no": order_no,
        "production_no": "PO-QR-REPORT-1",
        "model_code": "QR-MATRIX",
        "operation_section": "sewing",
        "operation_code": "OP-A",
        "operation_name": "Attach collar",
        "size": "S",
        "quantity": 40,
        "rate_per_piece": 100,
    })
    scanned = client.post("/api/payroll/records", json=scan_payload, headers=auth_headers)
    assert scanned.status_code == 201, scanned.text

    order_options = client.get(
        f"/api/payroll/reports/order-qr-status/orders?search={order_no}",
        headers=auth_headers,
    )
    assert order_options.status_code == 200, order_options.text
    exact_option = next(row for row in order_options.json() if row["order_no"] == order_no)
    assert exact_option["label_count"] == 3
    assert exact_option["production_nos"] == ["PO-QR-REPORT-1"]
    assert exact_option["model_codes"] == ["QR-MATRIX"]

    report = client.get(
        f"/api/payroll/reports/order-qr-status?order_no={order_no}&limit=100",
        headers=auth_headers,
    )
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["total_labels"] == 3
    assert body["scanned_labels"] == 1
    assert body["available_labels"] == 2
    assert float(body["total_quantity"]) == 110
    assert float(body["scanned_quantity"]) == 40
    assert body["sizes"] == ["S", "M"]
    collar = next(row for row in body["operations"] if row["operation_code"] == "OP-A")
    collar_small = next(cell for cell in collar["cells"] if cell["size"] == "S")
    assert collar_small["issued_labels"] == 2
    assert collar_small["scanned_labels"] == 1
    assert collar_small["available_labels"] == 1
    assert float(collar_small["issued_quantity"]) == 80
    assert float(collar_small["scanned_quantity"]) == 40
    assert all(row["sales_order_no"] == order_no for row in body["items"])

    scanned_only = client.get(
        f"/api/payroll/reports/order-qr-status?order_no={order_no}&status=scanned",
        headers=auth_headers,
    )
    assert scanned_only.status_code == 200, scanned_only.text
    assert scanned_only.json()["total"] == 1
    assert scanned_only.json()["items"][0]["employee_name"] == "Order QR Report Worker"
    assert scanned_only.json()["total_labels"] == 3

    scanned_label = scanned_only.json()["items"][0]
    returned = client.post(f"/api/payroll/qr-labels/{scanned_label['id']}/return", headers=auth_headers)
    assert returned.status_code == 200, returned.text
    after_return = client.get(
        f"/api/payroll/reports/order-qr-status?order_no={order_no}",
        headers=auth_headers,
    )
    assert after_return.status_code == 200, after_return.text
    assert after_return.json()["scanned_labels"] == 0
    assert after_return.json()["available_labels"] == 3
    assert float(after_return.json()["available_quantity"]) == 110


def test_returned_payroll_qr_can_be_scanned_for_another_employee(client, auth_headers):
    first_employee = _create_employee(client, auth_headers, "First QR Worker")
    second_employee = _create_employee(client, auth_headers, "Second QR Worker")
    label_uid = f"PY:{uuid4().hex}"
    first = client.post(
        "/api/payroll/records",
        json=_record_payload(first_employee["id"], scan_uid=label_uid),
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text

    control = client.get(f"/api/payroll/qr-labels?search={label_uid}", headers=auth_headers)
    label = control.json()["items"][0]
    returned = client.post(f"/api/payroll/qr-labels/{label['id']}/return", headers=auth_headers)
    assert returned.status_code == 200, returned.text
    assert returned.json()["status"] == "available"
    assert returned.json()["return_count"] == 1

    returned_work = client.get(f"/api/payroll/qr/resolve/{label['qr_token']}", headers=auth_headers)
    assert returned_work.status_code == 200, returned_work.text
    assert returned_work.json()["label_status"] == "available"

    summary = client.get("/api/payroll/summary", headers=auth_headers)
    assert summary.status_code == 200, summary.text
    assert all(row["employee_id"] != first_employee["id"] for row in summary.json()["employees"])

    records = client.get("/api/payroll/records?limit=1000", headers=auth_headers).json()
    old_record = next(row for row in records if row["id"] == first.json()["id"])
    assert old_record["status"] == "voided"
    assert old_record["scan_uid"] is None
    assert old_record["original_scan_uid"] == label_uid

    second = client.post(
        "/api/payroll/records",
        json=_record_payload(second_employee["id"], scan_uid=label_uid),
        headers=auth_headers,
    )
    assert second.status_code == 201, second.text
    assert second.json()["employee_id"] == second_employee["id"]

    reassigned = client.get(f"/api/payroll/qr-labels?search={label_uid}", headers=auth_headers).json()["items"][0]
    assert reassigned["status"] == "scanned"
    assert reassigned["employee_id"] == second_employee["id"]
    assert reassigned["return_count"] == 1


def test_sewing_production_report_filters_and_excludes_returned_work(client, auth_headers):
    first_employee = _create_employee(client, auth_headers, "Report Worker One")
    second_employee = _create_employee(client, auth_headers, "Report Worker Two")
    first_uid = f"PY:{uuid4().hex}"
    second_uid = f"PY:{uuid4().hex}"

    first_payload = _record_payload(first_employee["id"], scan_uid=first_uid)
    first_payload["production_no"] = "PO-REPORT-ONE"
    first_payload["sales_order_no"] = "SO-REPORT-ONE"
    first_payload["work"].update({
        "label_id": first_uid,
        "production_no": "PO-REPORT-ONE",
        "sales_order_no": "SO-REPORT-ONE",
        "sewing_line_code": "SEW-09",
        "sewing_line_name": "Report line",
        "cutting_passport_no": "KR-REPORT-1",
        "size": "L",
    })
    first = client.post("/api/payroll/records", json=first_payload, headers=auth_headers)
    assert first.status_code == 201, first.text

    second_payload = _record_payload(second_employee["id"], scan_uid=second_uid)
    second_payload["production_no"] = "PO-REPORT-TWO"
    second_payload["work"]["production_no"] = "PO-REPORT-TWO"
    second = client.post("/api/payroll/records", json=second_payload, headers=auth_headers)
    assert second.status_code == 201, second.text

    report = client.get(
        f"/api/payroll/reports/sewing-production?employee_id={first_employee['id']}&order_no=REPORT-ONE",
        headers=auth_headers,
    )
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["total"] == 1
    assert float(body["total_quantity"]) == 10
    assert float(body["total_amount"]) == 2500
    assert body["items"][0]["employee_name"] == "Report Worker One"
    assert body["items"][0]["production_no"] == "PO-REPORT-ONE"
    assert body["items"][0]["sewing_line_code"] == "SEW-09"
    assert body["items"][0]["cutting_reference"] == "KR-REPORT-1"
    assert body["items"][0]["size"] == "L"
    assert body["items"][0]["barcode"].isdigit()

    option_values = {
        key: {option["value"] for option in body["options"][key]}
        for key in (
            "employees",
            "operations",
            "sewing_lines",
            "models",
            "orders",
            "cutting_references",
            "sizes",
        )
    }
    assert str(first_employee["id"]) in option_values["employees"]
    assert "SEW-PAY" in option_values["operations"]
    assert "SEW-09" in option_values["sewing_lines"]
    assert "PAY-MODEL" in option_values["models"]
    assert "PO-REPORT-ONE" in option_values["orders"]
    assert "SO-REPORT-ONE" in option_values["orders"]
    assert "KR-REPORT-1" in option_values["cutting_references"]
    assert "L" in option_values["sizes"]
    employee_option = next(
        option for option in body["options"]["employees"]
        if option["value"] == str(first_employee["id"])
    )
    assert "Report Worker One" in employee_option["label"]
    operation_option = next(
        option for option in body["options"]["operations"]
        if option["value"] == "SEW-PAY"
    )
    assert "Payroll sewing" in operation_option["label"]

    line_filtered = client.get(
        "/api/payroll/reports/sewing-production?sewing_line=SEW-09",
        headers=auth_headers,
    )
    assert line_filtered.status_code == 200, line_filtered.text
    assert line_filtered.json()["total"] == 1

    label = client.get(f"/api/payroll/qr-labels?search={first_uid}", headers=auth_headers).json()["items"][0]
    returned = client.post(f"/api/payroll/qr-labels/{label['id']}/return", headers=auth_headers)
    assert returned.status_code == 200, returned.text

    active = client.get(
        f"/api/payroll/reports/sewing-production?employee_id={first_employee['id']}",
        headers=auth_headers,
    )
    assert active.status_code == 200, active.text
    assert active.json()["total"] == 0
    assert str(first_employee["id"]) in {
        option["value"] for option in active.json()["options"]["employees"]
    }

    voided = client.get(
        f"/api/payroll/reports/sewing-production?employee_id={first_employee['id']}&status=voided",
        headers=auth_headers,
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["total"] == 1


def test_sewing_production_report_options_include_reference_data_before_scans(client, auth_headers):
    from app.models import Bundle, Model, ProductionOrder
    from app.tests.conftest import TestSessionLocal

    suffix = uuid4().hex[:8].upper()
    employee = _create_employee(client, auth_headers, f"Reference Worker {suffix}")
    model_code = f"REF-{suffix}"
    operation_code = f"OP-{suffix}"
    production_no = f"PO-REF-{suffix}"

    with TestSessionLocal() as db:
        model = Model(
            code=model_code,
            name=f"Reference model {suffix}",
            status="approved",
            details_json={
                "paid_operations": [{
                    "id": f"ref-{suffix}",
                    "selected": True,
                    "section": "sewing",
                    "code": operation_code,
                    "name": f"Reference operation {suffix}",
                    "rate": "250",
                    "currency": "UZS",
                }],
            },
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=production_no,
            production_type="branded_stock",
            model_id=model.id,
            status="new",
            planned_quantity=10,
        )
        db.add(order)
        db.flush()
        db.add(Bundle(
            bundle_no=f"REF-BND-{suffix}",
            barcode=f"REF-BAR-{suffix}",
            production_order_id=order.id,
            model_id=model.id,
            color="test",
            size="M",
            quantity=10,
            sewing_factory_code="MIL",
            status="created",
        ))
        db.commit()

    report = client.get("/api/payroll/reports/sewing-production", headers=auth_headers)
    assert report.status_code == 200, report.text
    body = report.json()
    assert str(employee["id"]) in {row["value"] for row in body["options"]["employees"]}
    assert operation_code in {row["value"] for row in body["options"]["operations"]}
    assert model_code in {row["value"] for row in body["options"]["models"]}
    assert production_no in {row["value"] for row in body["options"]["orders"]}


def test_sewing_production_report_options_are_scoped_by_factory(client, auth_headers):
    from app.models import Bundle, Department, Employee, Model, ProductionOrder, SewingFlow, WorkOrder
    from app.tests.conftest import TestSessionLocal

    suffix = uuid4().hex[:8].upper()
    with TestSessionLocal() as db:
        departments = {
            code: db.query(Department).filter(Department.code == code).one()
            for code in ("MIL", "ECO")
        }
        models = {}
        orders = {}
        employees = {}
        for factory_code in ("MIL", "ECO"):
            operation_code = f"{factory_code}-OP-{suffix}"
            model = Model(
                code=f"{factory_code}-MODEL-{suffix}",
                name=f"{factory_code} model {suffix}",
                status="approved",
                details_json={
                    "paid_operations": [{
                        "id": f"{factory_code.lower()}-{suffix}",
                        "selected": True,
                        "section": "sewing",
                        "code": operation_code,
                        "name": f"{factory_code} operation {suffix}",
                        "rate": "250",
                        "currency": "UZS",
                        "sewingFactory": "milana" if factory_code == "MIL" else "eco_cotton",
                    }],
                },
            )
            employee = Employee(
                factory_code=factory_code,
                full_name=f"{factory_code} employee {suffix}",
                employee_no=f"{factory_code}-{suffix}",
                department_id=departments[factory_code].id,
                position="Tikuvchi",
                status="active",
            )
            flow = SewingFlow(
                factory_code=factory_code,
                code=f"{factory_code}-LINE-{suffix}",
                name=f"{factory_code} line {suffix}",
                capacity_per_day=100,
                is_active=True,
            )
            db.add_all([model, employee, flow])
            db.flush()
            order = ProductionOrder(
                production_no=f"{factory_code}-PO-{suffix}",
                production_type="branded_stock",
                model_id=model.id,
                status="new",
                planned_quantity=10,
            )
            db.add(order)
            db.flush()
            db.add(Bundle(
                bundle_no=f"{factory_code}-BND-{suffix}",
                barcode=f"{factory_code}-BAR-{suffix}",
                production_order_id=order.id,
                model_id=model.id,
                color="test",
                size="M" if factory_code == "MIL" else "L",
                quantity=10,
                sewing_factory_code=factory_code,
                status="created",
            ))
            db.add(WorkOrder(
                production_order_id=order.id,
                department_id=departments[factory_code].id,
                operation="sewing",
                status="completed",
                planned_input_qty=10,
                planned_output_qty=10,
                actual_input_qty=10,
                actual_output_qty=10,
                passed_qty=10,
            ))
            models[factory_code] = model
            orders[factory_code] = order
            employees[factory_code] = employee
        db.commit()

    milana = client.get(
        "/api/payroll/reports/sewing-production/options?factory_code=MIL",
        headers=auth_headers,
    )
    assert milana.status_code == 200, milana.text
    milana_options = milana.json()
    assert str(employees["MIL"].id) in {row["value"] for row in milana_options["employees"]}
    assert str(employees["ECO"].id) not in {row["value"] for row in milana_options["employees"]}
    assert f"MIL-LINE-{suffix}" in {row["value"] for row in milana_options["sewing_lines"]}
    assert f"ECO-LINE-{suffix}" not in {row["value"] for row in milana_options["sewing_lines"]}
    assert f"MIL-OP-{suffix}" in {row["value"] for row in milana_options["operations"]}
    assert f"ECO-OP-{suffix}" not in {row["value"] for row in milana_options["operations"]}
    assert models["MIL"].code in {row["value"] for row in milana_options["models"]}
    assert models["ECO"].code not in {row["value"] for row in milana_options["models"]}
    assert orders["MIL"].production_no in {row["value"] for row in milana_options["orders"]}
    assert orders["ECO"].production_no not in {row["value"] for row in milana_options["orders"]}

    eco_headers = _create_user_with_permissions(
        client,
        auth_headers,
        email=f"eco.payroll.{suffix.lower()}@example.com",
        permissions=["payroll.view", "payroll.manage", "payroll.scan", "hr.employees"],
        factory_code="ECO",
    )
    eco = client.get(
        "/api/payroll/reports/sewing-production/options?factory_code=ECO",
        headers=eco_headers,
    )
    assert eco.status_code == 200, eco.text
    eco_options = eco.json()
    assert f"ECO-LINE-{suffix}" in {row["value"] for row in eco_options["sewing_lines"]}
    assert f"MIL-LINE-{suffix}" not in {row["value"] for row in eco_options["sewing_lines"]}
    assert f"ECO-OP-{suffix}" in {row["value"] for row in eco_options["operations"]}
    assert f"MIL-OP-{suffix}" not in {row["value"] for row in eco_options["operations"]}

    mil_processes = client.get(
        "/api/process-tracking?page_size=500&sewing_completed_only=true",
        headers=auth_headers,
    )
    eco_processes = client.get(
        "/api/process-tracking?page_size=500&sewing_completed_only=true",
        headers=eco_headers,
    )
    assert mil_processes.status_code == 200, mil_processes.text
    assert eco_processes.status_code == 200, eco_processes.text
    mil_process_numbers = {row["production_no"] for row in mil_processes.json()}
    eco_process_numbers = {row["production_no"] for row in eco_processes.json()}
    assert orders["MIL"].production_no in mil_process_numbers
    assert orders["ECO"].production_no not in mil_process_numbers
    assert orders["ECO"].production_no in eco_process_numbers
    assert orders["MIL"].production_no not in eco_process_numbers

    denied_cross_factory = client.get(
        "/api/payroll/reports/sewing-production/options?factory_code=MIL",
        headers=eco_headers,
    )
    assert denied_cross_factory.status_code == 403


def test_payroll_data_is_hard_scoped_to_login_factory(client, auth_headers):
    suffix = uuid4().hex[:8].upper()
    mil_employee = _create_employee(client, auth_headers, f"MIL isolated worker {suffix}")
    eco_headers = _create_user_with_permissions(
        client,
        auth_headers,
        email=f"eco.isolation.{suffix.lower()}@example.com",
        permissions=["payroll.view", "payroll.manage", "payroll.scan", "hr.employees"],
        factory_code="ECO",
    )
    eco_employee = _create_employee(client, eco_headers, f"ECO isolated worker {suffix}")

    shared_employee_no = f"SHARED-{suffix}"
    with TestSessionLocal() as db:
        mil_row = db.get(Employee, mil_employee["id"])
        eco_row = db.get(Employee, eco_employee["id"])
        assert mil_row and eco_row
        mil_row.employee_no = shared_employee_no
        eco_row.employee_no = shared_employee_no
        db.commit()

    mil_employees = client.get("/api/employees", headers=auth_headers)
    eco_employees = client.get("/api/employees", headers=eco_headers)
    assert mil_employees.status_code == 200
    assert eco_employees.status_code == 200
    assert mil_employee["id"] in {row["id"] for row in mil_employees.json()}
    assert eco_employee["id"] not in {row["id"] for row in mil_employees.json()}
    assert eco_employee["id"] in {row["id"] for row in eco_employees.json()}
    assert mil_employee["id"] not in {row["id"] for row in eco_employees.json()}

    mil_resolved = client.get(
        "/api/payroll/employees/resolve",
        params={"employee_no": shared_employee_no},
        headers=auth_headers,
    )
    eco_resolved = client.get(
        "/api/payroll/employees/resolve",
        params={"employee_no": shared_employee_no},
        headers=eco_headers,
    )
    assert mil_resolved.json()["employee_id"] == mil_employee["id"]
    assert eco_resolved.json()["employee_id"] == eco_employee["id"]

    label_uid = f"FACTORY-MIL-{uuid4().hex}"
    issued = client.post(
        "/api/payroll/qr-labels/issue",
        json={"labels": [{
            "label_uid": label_uid,
            "operation_section": "sewing",
            "operation_code": "MIL-ONLY",
            "operation_name": "MIL only work",
            "quantity": 10,
            "rate_per_piece": 100,
        }]},
        headers=auth_headers,
    )
    assert issued.status_code == 200, issued.text
    qr_token = issued.json()["labels"][0]["qr_token"]
    eco_label_search = client.get(f"/api/payroll/qr-labels?search={label_uid}", headers=eco_headers)
    assert eco_label_search.status_code == 200
    assert eco_label_search.json()["total"] == 0
    assert client.get(f"/api/payroll/qr/resolve/{qr_token}", headers=eco_headers).status_code == 404

    eco_issued = client.post(
        "/api/payroll/qr-labels/issue",
        json={"labels": [{
            "label_uid": label_uid,
            "operation_section": "sewing",
            "operation_code": "ECO-ONLY",
            "operation_name": "ECO only work",
            "quantity": 7,
            "rate_per_piece": 80,
        }]},
        headers=eco_headers,
    )
    assert eco_issued.status_code == 200, eco_issued.text
    eco_qr_token = eco_issued.json()["labels"][0]["qr_token"]
    assert eco_qr_token != qr_token
    eco_resolved_work = client.get(f"/api/payroll/qr/resolve/{eco_qr_token}", headers=eco_headers)
    assert eco_resolved_work.status_code == 200
    assert eco_resolved_work.json()["operation_code"] == "ECO-ONLY"

    period_no = f"PAY-SHARED-{suffix}"
    now = datetime.now(timezone.utc)
    period_payload = {
        "period_no": period_no,
        "name": f"Shared number {suffix}",
        "start_date": (now - timedelta(days=1)).isoformat(),
        "end_date": (now + timedelta(days=1)).isoformat(),
        "status": "open",
    }
    assert client.post("/api/payroll/periods", json=period_payload, headers=auth_headers).status_code == 201
    assert client.post("/api/payroll/periods", json=period_payload, headers=eco_headers).status_code == 201

    mil_same_scan = client.post(
        "/api/payroll/records",
        json=_record_payload(mil_employee["id"], scan_uid=label_uid),
        headers=auth_headers,
    )
    eco_same_scan = client.post(
        "/api/payroll/records",
        json=_record_payload(eco_employee["id"], scan_uid=label_uid),
        headers=eco_headers,
    )
    assert mil_same_scan.status_code == 201, mil_same_scan.text
    assert eco_same_scan.status_code == 201, eco_same_scan.text
    assert mil_same_scan.json()["id"] != eco_same_scan.json()["id"]

    mil_record = client.post(
        "/api/payroll/records",
        json=_record_payload(mil_employee["id"], scan_uid=f"mil-isolated-{uuid4().hex}"),
        headers=auth_headers,
    )
    assert mil_record.status_code == 201, mil_record.text
    cross_employee = client.post(
        "/api/payroll/records",
        json=_record_payload(mil_employee["id"], scan_uid=f"eco-cross-{uuid4().hex}"),
        headers=eco_headers,
    )
    assert cross_employee.status_code == 404
    eco_records = client.get("/api/payroll/records?limit=1000", headers=eco_headers)
    assert mil_record.json()["id"] not in {row["id"] for row in eco_records.json()}

def test_locked_period_rejects_new_records_for_scanner(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    scanner_headers = _create_user_with_permissions(
        client,
        auth_headers,
        email=f"payroll.scan.{uuid4().hex[:8]}@example.com",
        permissions=["payroll.scan"],
    )
    period = _create_period(client, auth_headers)
    locked = client.post(f"/api/payroll/periods/{period['id']}/lock", headers=auth_headers)
    assert locked.status_code == 200, locked.text

    payload = _record_payload(employee["id"], scan_uid=f"locked-{uuid4().hex}")
    payload["payroll_period_id"] = period["id"]
    denied = client.post("/api/payroll/records", json=payload, headers=scanner_headers)
    assert denied.status_code == 409, denied.text


def test_approve_and_mark_paid_permissions(client, auth_headers):
    period = _create_period(client, auth_headers)
    manager_headers = _create_user_with_permissions(
        client,
        auth_headers,
        email=f"payroll.manage.{uuid4().hex[:8]}@example.com",
        permissions=["payroll.manage", "payroll.view"],
    )
    approve_headers = _create_user_with_permissions(
        client,
        auth_headers,
        email=f"payroll.approve.{uuid4().hex[:8]}@example.com",
        permissions=["payroll.approve", "payroll.view"],
    )
    pay_headers = _create_user_with_permissions(
        client,
        auth_headers,
        email=f"payroll.pay.{uuid4().hex[:8]}@example.com",
        permissions=["payroll.pay", "payroll.view"],
    )

    denied_approve = client.post(f"/api/payroll/periods/{period['id']}/approve", headers=manager_headers)
    assert denied_approve.status_code == 403, denied_approve.text

    locked = client.post(f"/api/payroll/periods/{period['id']}/lock", headers=manager_headers)
    assert locked.status_code == 200, locked.text

    approved = client.post(f"/api/payroll/periods/{period['id']}/approve", headers=approve_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    denied_pay = client.post(f"/api/payroll/periods/{period['id']}/mark-paid", headers=approve_headers)
    assert denied_pay.status_code == 403, denied_pay.text

    paid = client.post(f"/api/payroll/periods/{period['id']}/mark-paid", headers=pay_headers)
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "paid"


def test_period_status_cannot_bypass_controlled_actions(client, auth_headers):
    invalid_create = client.post(
        "/api/payroll/periods",
        json={
            "name": "Invalid paid period",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "status": "paid",
        },
        headers=auth_headers,
    )
    assert invalid_create.status_code == 400, invalid_create.text

    period = _create_period(client, auth_headers)
    bypass = client.patch(
        f"/api/payroll/periods/{period['id']}",
        json={"status": "approved"},
        headers=auth_headers,
    )
    assert bypass.status_code == 409, bypass.text

    approve_open = client.post(f"/api/payroll/periods/{period['id']}/approve", headers=auth_headers)
    assert approve_open.status_code == 409, approve_open.text


def test_void_payroll_record(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    created = client.post(
        "/api/payroll/records",
        json=_record_payload(employee["id"], scan_uid=f"void-{uuid4().hex}"),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    voided = client.post(f"/api/payroll/records/{created.json()['id']}/void", headers=auth_headers)
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "voided"

    active_records = client.get("/api/payroll/records?status=active&limit=1000", headers=auth_headers)
    assert active_records.status_code == 200, active_records.text
    assert all(row["id"] != created.json()["id"] for row in active_records.json())

    voided_records = client.get("/api/payroll/records?status=voided&limit=1000", headers=auth_headers)
    assert voided_records.status_code == 200, voided_records.text
    assert any(row["id"] == created.json()["id"] for row in voided_records.json())

    summary = client.get(f"/api/payroll/summary?employee_id={employee['id']}", headers=auth_headers)
    assert summary.status_code == 200, summary.text
    assert summary.json()["records_count"] == 0
    assert float(summary.json()["total_amount"]) == 0


def test_payroll_permission_denied_cases(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    limited_headers = _create_user_with_permissions(
        client,
        auth_headers,
        email=f"payroll.none.{uuid4().hex[:8]}@example.com",
        permissions=["finance.view"],
    )

    denied_list = client.get("/api/payroll/records", headers=limited_headers)
    assert denied_list.status_code == 403, denied_list.text

    denied_create = client.post(
        "/api/payroll/records",
        json=_record_payload(employee["id"], scan_uid=f"denied-{uuid4().hex}"),
        headers=limited_headers,
    )
    assert denied_create.status_code == 403, denied_create.text
