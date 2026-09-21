from datetime import datetime, timezone
from uuid import uuid4

from app.tests.test_payroll import _create_employee, _record_payload


def _create_period(client, headers, *, start: datetime, end: datetime) -> dict:
    response = client.post(
        "/api/payroll/periods",
        headers=headers,
        json={
            "name": f"Date match {uuid4().hex[:8]}",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "status": "open",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_record_period_assignment_requires_date_match_unless_explicit(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    period = _create_period(
        client,
        auth_headers,
        start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end=datetime(2025, 1, 10, 23, 59, tzinfo=timezone.utc),
    )

    matched = client.post(
        "/api/payroll/records",
        headers=auth_headers,
        json=_record_payload(
            employee["id"],
            scan_uid=f"period-match-{uuid4().hex}",
            scanned_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
        ),
    )
    unmatched = client.post(
        "/api/payroll/records",
        headers=auth_headers,
        json=_record_payload(
            employee["id"],
            scan_uid=f"period-unmatched-{uuid4().hex}",
            scanned_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        ),
    )
    explicit_payload = _record_payload(
        employee["id"],
        scan_uid=f"period-explicit-{uuid4().hex}",
        scanned_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
    )
    explicit_payload["payroll_period_id"] = period["id"]
    explicit = client.post("/api/payroll/records", headers=auth_headers, json=explicit_payload)

    assert matched.status_code == 201, matched.text
    assert matched.json()["payroll_period_id"] == period["id"]
    assert unmatched.status_code == 201, unmatched.text
    assert unmatched.json()["payroll_period_id"] is None
    assert explicit.status_code == 201, explicit.text
    assert explicit.json()["payroll_period_id"] == period["id"]


def test_bulk_period_assignment_leaves_only_unmatched_record_unassigned(client, auth_headers):
    employee = _create_employee(client, auth_headers)
    period = _create_period(
        client,
        auth_headers,
        start=datetime(2025, 3, 1, tzinfo=timezone.utc),
        end=datetime(2025, 3, 10, 23, 59, tzinfo=timezone.utc),
    )
    records = [
        _record_payload(
            employee["id"],
            scan_uid=f"bulk-period-match-{uuid4().hex}",
            scanned_at=datetime(2025, 3, 5, tzinfo=timezone.utc),
        ),
        _record_payload(
            employee["id"],
            scan_uid=f"bulk-period-unmatched-{uuid4().hex}",
            scanned_at=datetime(2025, 4, 1, tzinfo=timezone.utc),
        ),
    ]

    response = client.post(
        "/api/payroll/records/bulk",
        headers=auth_headers,
        json={"records": records},
    )

    assert response.status_code == 200, response.text
    assert [row["payroll_period_id"] for row in response.json()["records"]] == [period["id"], None]
