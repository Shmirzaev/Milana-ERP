from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


STRONG_PW = "PayrollTest123!"


def _login(client, email: str, password: str = STRONG_PW) -> dict[str, str]:
    r = client.post("/api/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_user_with_permissions(client, admin_headers, *, email: str, permissions: list[str]) -> dict[str, str]:
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


def test_seeded_payroll_access_policy(client, auth_headers):
    roles = client.get("/api/roles", headers=auth_headers)
    assert roles.status_code == 200, roles.text
    role_by_name = {role["name"]: role for role in roles.json()}

    depts = client.get("/api/departments", headers=auth_headers)
    assert depts.status_code == 200, depts.text
    dept_by_code = {dept["code"]: dept for dept in depts.json()}

    assert "PAY" in dept_by_code
    assert dept_by_code["PAY"]["name"] == "Payroll"
    assert role_by_name["Payroll"]["permissions"] == ["payroll.scan"]

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


def test_payroll_role_can_only_save_scan_records(client, auth_headers):
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

    denied_records = client.get("/api/payroll/records", headers=scanner_headers)
    assert denied_records.status_code == 403, denied_records.text

    denied_summary = client.get("/api/payroll/summary", headers=scanner_headers)
    assert denied_summary.status_code == 403, denied_summary.text


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
        response = client.post(f"/api/payroll/periods/{period['id']}/approve", headers=auth_headers)
    elif status == "paid":
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
    issued_label = issued.json()["labels"][0]
    assert issued_label["label_uid"] == label_uid
    assert len(issued_label["qr_token"]) == 9
    assert issued_label["qr_token"].isdigit()
    assert issued_label["qr_token"].startswith("2")

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

    approved = client.post(f"/api/payroll/periods/{period['id']}/approve", headers=approve_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    denied_pay = client.post(f"/api/payroll/periods/{period['id']}/mark-paid", headers=approve_headers)
    assert denied_pay.status_code == 403, denied_pay.text

    paid = client.post(f"/api/payroll/periods/{period['id']}/mark-paid", headers=pay_headers)
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "paid"


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
