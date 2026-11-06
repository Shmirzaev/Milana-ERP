from datetime import datetime, timezone

import pytest

from app.schemas import PayrollPeriod, PayrollQrLabel, PayrollRecord
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_employee
from app.tests.test_payroll_scan_allocations import issue, scan


def _payload(start="2025-10-06T00:00:00+05:00", end="2025-10-31T23:59:59+05:00"):
    return {"name": "October payroll", "start_date": start, "end_date": end}


def _existing(*, status="locked", factory="MIL", period_no="PAY-2025-07"):
    with TestSessionLocal() as db:
        period = PayrollPeriod(
            factory_code=factory, period_no=period_no, name="Legacy payroll",
            start_date=datetime(2025, 8, 1, tzinfo=timezone.utc),
            end_date=datetime(2025, 10, 30, tzinfo=timezone.utc), status=status,
        )
        db.add(period)
        db.commit()
        return period.id


@pytest.mark.parametrize("status", ["draft", "open", "locked", "approved", "paid", "cancelled"])
def test_create_rejects_overlap_with_every_scanner_matching_status(client, auth_headers, status):
    existing_id = _existing(status=status)
    result = client.post("/api/payroll/periods", headers=auth_headers, json=_payload())
    assert result.status_code == 409, result.text
    assert f"PAY-2025-07 ({status})" in result.json()["detail"]
    with TestSessionLocal() as db:
        assert [row.id for row in db.query(PayrollPeriod).all()] == [existing_id]


@pytest.mark.parametrize("start,end", [
    ("2025-07-01T00:00:00Z", "2025-08-01T00:00:00Z"),  # Shared inclusive endpoint.
    ("2025-10-30T05:00:00+05:00", "2025-11-01T00:00:00Z"),
    ("2025-07-01T00:00:00Z", "2025-11-01T00:00:00Z"),  # Encloses existing range.
    ("2025-09-01T00:00:00Z", "2025-09-02T00:00:00Z"),  # Inside existing range.
])
def test_create_rejects_inclusive_and_nested_overlap(client, auth_headers, start, end):
    _existing()
    result = client.post("/api/payroll/periods", headers=auth_headers, json=_payload(start, end))
    assert result.status_code == 409, result.text


def test_adjacent_period_and_same_dates_in_other_factory_are_allowed(client, auth_headers):
    _existing(factory="ECO")
    first = client.post("/api/payroll/periods", headers=auth_headers, json=_payload())
    assert first.status_code == 201, first.text
    second = client.post("/api/payroll/periods", headers=auth_headers, json=_payload(
        "2025-11-01T00:00:00+05:00", "2025-11-30T23:59:59+05:00",
    ))
    assert second.status_code == 201, second.text


def test_date_edit_cannot_introduce_overlap_and_rejection_is_atomic(client, auth_headers):
    _existing()
    created = client.post("/api/payroll/periods", headers=auth_headers, json=_payload(
        "2025-11-01T00:00:00Z", "2025-11-30T23:59:59Z",
    ))
    assert created.status_code == 201, created.text
    endpoint = f"/api/payroll/periods/{created.json()['id']}"
    result = client.patch(endpoint, headers=auth_headers, json={
        "start_date": "2025-10-13T00:00:00Z", "name": "Must not persist",
    })
    assert result.status_code == 409, result.text
    with TestSessionLocal() as db:
        period = db.get(PayrollPeriod, created.json()["id"])
        assert period.start_date.month == 11
        assert period.name == "October payroll"
    # Updating a period's own range must not count itself as a conflict.
    result = client.patch(endpoint, headers=auth_headers, json={"start_date": "2025-11-02T00:00:00Z"})
    assert result.status_code == 200, result.text


def test_legacy_overlap_allows_metadata_edits_and_date_correction(client, auth_headers):
    _existing()
    duplicate_id = _existing(status="open", period_no="PAY-2025-10")
    endpoint = f"/api/payroll/periods/{duplicate_id}"
    result = client.patch(endpoint, headers=auth_headers, json={"notes": "Investigating legacy overlap"})
    assert result.status_code == 200, result.text
    result = client.patch(endpoint, headers=auth_headers, json={"end_date": "2025-10-20T00:00:00Z"})
    assert result.status_code == 200, result.text
    result = client.patch(endpoint, headers=auth_headers, json={
        "start_date": "2025-11-01T00:00:00Z", "end_date": "2025-11-30T23:59:59Z",
    })
    assert result.status_code == 200, result.text


def test_legacy_scan_names_conflicts_without_ignoring_locked_wages(client, auth_headers):
    _existing()
    _existing(status="open", period_no="PAY-2025-10")
    worker = _create_employee(client, auth_headers)
    label = issue(client, auth_headers)
    result = scan(client, auth_headers, label, worker, work_date="2025-10-13")
    assert result.status_code == 409, result.text
    assert "PAY-2025-07 (locked)" in result.json()["detail"]
    assert "PAY-2025-10 (open)" in result.json()["detail"]
    with TestSessionLocal() as db:
        assert db.query(PayrollRecord).count() == 0
        assert db.query(PayrollQrLabel).filter_by(label_uid=label["label_uid"]).one().status == "available"
