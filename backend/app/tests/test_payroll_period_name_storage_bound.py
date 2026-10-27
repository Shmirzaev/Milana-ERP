"""Bound payroll period names to their PostgreSQL VARCHAR(128) column."""

from datetime import datetime, timedelta, timezone


def _period_payload(name: str) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "name": name,
        "start_date": (now - timedelta(days=1)).isoformat(),
        "end_date": (now + timedelta(days=1)).isoformat(),
    }


def test_payroll_period_name_accepts_limit_rejects_overflow_after_reference_check(client, auth_headers):
    created = client.post(
        "/api/payroll/periods",
        headers=auth_headers,
        json=_period_payload("P" * 128),
    )
    assert created.status_code == 201, created.text
    period_id = created.json()["id"]

    missing = client.patch(
        f"/api/payroll/periods/{period_id + 10_000}",
        headers=auth_headers,
        json={"name": "P" * 129},
    )
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Payroll period not found"}

    rejected = client.patch(
        f"/api/payroll/periods/{period_id}",
        headers=auth_headers,
        json={"name": "P" * 129},
    )
    assert rejected.status_code == 422, rejected.text

    periods = client.get("/api/payroll/periods", headers=auth_headers)
    assert periods.status_code == 200, periods.text
    unchanged = next(row for row in periods.json() if row["id"] == period_id)
    assert unchanged["name"] == "P" * 128
