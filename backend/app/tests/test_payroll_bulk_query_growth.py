"""Payroll bulk creation keeps only the required per-record audit read."""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import event

from app.models import PayrollRecord
from app.tests.conftest import TestSessionLocal, test_engine
from app.tests.test_payroll import (
    _create_employee,
    _create_period,
    _create_user_with_permissions,
    _record_payload,
)


def _issue_rows(client, headers, size):
    marker = uuid4().hex
    labels = [
        {
            "label_uid": f"bulk-growth-{marker}-{index}",
            "operation_section": "sewing",
            "operation_code": "PERF06",
            "operation_name": "Bulk query growth",
            "quantity": 1,
            "rate_per_piece": 1,
        }
        for index in range(size)
    ]
    issued = client.post("/api/payroll/qr-labels/issue", headers=headers, json={"labels": labels})
    assert issued.status_code == 200, issued.text
    return [row["label_uid"] for row in labels]


def _bulk_with_statements(client, headers, records):
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.post("/api/payroll/records/bulk", headers=headers, json={"records": records})
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)
    return response, statements


def test_bulk_record_reads_are_bounded_except_for_audit_chain(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    period = _create_period(client, auth_headers)
    measurements = []

    for size in (1, 50, 401):
        label_uids = _issue_rows(client, auth_headers, size)
        response, statements = _bulk_with_statements(
            client,
            auth_headers,
            [{"scan_uid": uid, "employee_id": employee["id"], "quantity": 999, "rate_per_piece": 999}
             for uid in label_uids],
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["created_count"] == size and body["duplicate_count"] == 0
        assert [row["scan_uid"] for row in body["records"]] == label_uids
        assert {row["payroll_period_id"] for row in body["records"]} == {period["id"]}

        selects = [statement for statement in statements if statement.startswith("select")]
        audit_reads = [statement for statement in selects if " from audit_logs" in statement]
        non_audit_reads = len(selects) - len(audit_reads)
        measurements.append((len(selects), len(audit_reads), non_audit_reads))

        # One chained audit lookup per record plus the bulk summary is required.
        assert len(audit_reads) == size + 1
        # Authentication, batched validation/locking, duplicate checks and
        # response serialization must not add one SELECT per record.
    print(f"Payroll bulk SELECTs (total/audit/other) for 1/50/401 rows: {measurements}")
    assert all(non_audit <= 30 for _total, _audit, non_audit in measurements)


def test_same_request_scan_replay_skips_later_payload_validation(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    scan_uid = f"bulk-replay-{uuid4().hex}"
    first = _record_payload(employee["id"], scan_uid=scan_uid)
    malformed_replay = {**first, "production_order_id": 2_000_000_000}

    response = client.post(
        "/api/payroll/records/bulk",
        headers=auth_headers,
        json={"records": [first, malformed_replay]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["created_count"], body["duplicate_count"]) == (1, 1)
    assert body["records"][0]["id"] == body["records"][1]["id"]


def test_same_request_scan_replay_for_another_employee_rolls_back(client, auth_headers):
    first_employee = _create_employee(client, auth_headers)
    second_employee = _create_employee(client, auth_headers)
    scan_uid = f"bulk-conflict-{uuid4().hex}"

    response = client.post(
        "/api/payroll/records/bulk",
        headers=auth_headers,
        json={"records": [
            _record_payload(first_employee["id"], scan_uid=scan_uid),
            _record_payload(second_employee["id"], scan_uid=scan_uid),
        ]},
    )

    assert response.status_code == 409, response.text
    with TestSessionLocal() as db:
        assert db.query(PayrollRecord).filter_by(scan_uid=scan_uid).count() == 0


def test_same_request_manual_dedupe_preserves_result_order(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    row = _record_payload(employee["id"])
    row["scan_uid"] = None
    row["work"].pop("label_id")
    row["scanned_at"] = "2026-09-20T12:00:00Z"

    response = client.post(
        "/api/payroll/records/bulk",
        headers=auth_headers,
        json={"records": [row, row]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["created_count"], body["duplicate_count"]) == (1, 1)
    assert body["records"][0]["id"] == body["records"][1]["id"]


def test_bulk_duplicate_replay_survives_period_finalization(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    period = _create_period(client, auth_headers)
    row = _record_payload(employee["id"], scan_uid=f"bulk-finalized-{uuid4().hex}")
    row["payroll_period_id"] = period["id"]
    created = client.post("/api/payroll/records", headers=auth_headers, json=row)
    assert created.status_code == 201, created.text
    locked = client.post(f"/api/payroll/periods/{period['id']}/lock", headers=auth_headers)
    assert locked.status_code == 200, locked.text

    replay = client.post("/api/payroll/records/bulk", headers=auth_headers, json={"records": [row]})

    assert replay.status_code == 200, replay.text
    assert replay.json()["created_count"] == 0
    assert replay.json()["duplicate_count"] == 1
    assert replay.json()["records"][0]["id"] == created.json()["id"]


def test_scan_only_bulk_uses_trusted_issued_values(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    manager = _create_user_with_permissions(
        client,
        auth_headers,
        email=f"bulk-manager-{uuid4().hex}@example.com",
        permissions=["payroll.manage"],
    )
    scanner = _create_user_with_permissions(
        client,
        auth_headers,
        email=f"bulk-scanner-{uuid4().hex}@example.com",
        permissions=["payroll.scan"],
    )
    scan_uid = f"bulk-trusted-{uuid4().hex}"
    issued = client.post(
        "/api/payroll/qr-labels/issue",
        headers=manager,
        json={"labels": [{
            "label_uid": scan_uid,
            "operation_name": "Trusted bulk operation",
            "quantity": 12,
            "rate_per_piece": 250,
        }]},
    )
    assert issued.status_code == 200, issued.text

    response = client.post(
        "/api/payroll/records/bulk",
        headers=scanner,
        json={"records": [{
            "scan_uid": scan_uid,
            "employee_id": employee["id"],
            "quantity": 999,
            "rate_per_piece": 999,
        }]},
    )

    assert response.status_code == 200, response.text
    record = response.json()["records"][0]
    assert float(record["quantity"]) == 12
    assert float(record["rate_per_piece"]) == 250


def test_bulk_response_uses_database_normalized_decimals(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    row = _record_payload(employee["id"])
    row["quantity"] = "1.23456"
    row["rate_per_piece"] = "2.34567"

    response = client.post(
        "/api/payroll/records/bulk",
        headers=auth_headers,
        json={"records": [row]},
    )

    assert response.status_code == 200, response.text
    body = response.json()["records"][0]
    with TestSessionLocal() as db:
        stored = db.get(PayrollRecord, body["id"])
        assert Decimal(str(body["quantity"])) == stored.quantity
        assert Decimal(str(body["rate_per_piece"])) == stored.rate_per_piece
        assert Decimal(str(body["total_amount"])) == stored.total_amount
