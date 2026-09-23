from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models import AuditLog, PayrollPeriod
from app.tests.conftest import TestSessionLocal


def _period_payload(period_no: str) -> dict:
    start = datetime.now(timezone.utc)
    return {
        "period_no": period_no,
        "name": f"Storage bound {uuid4().hex[:8]}",
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=1)).isoformat(),
        "status": "open",
    }


def _write_counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return db.query(PayrollPeriod).count(), db.query(AuditLog).count()


def test_payroll_period_number_accepts_exact_varchar_limit(client, auth_headers):
    period_no = f"P{uuid4().hex[:63]}"
    response = client.post(
        "/api/payroll/periods",
        headers=auth_headers,
        json=_period_payload(period_no),
    )

    assert response.status_code == 201, response.text
    assert response.json()["period_no"] == period_no


def test_payroll_period_number_overflow_rejects_create_without_writes(client, auth_headers):
    before = _write_counts()

    response = client.post(
        "/api/payroll/periods",
        headers=auth_headers,
        json=_period_payload("P" * 65),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "Payroll period number exceeds the 64-character storage limit"
    assert _write_counts() == before


def test_payroll_period_number_overflow_rejects_update_without_writes(client, auth_headers):
    created = client.post(
        "/api/payroll/periods",
        headers=auth_headers,
        json=_period_payload(f"P-{uuid4().hex[:12]}"),
    )
    assert created.status_code == 201, created.text
    period_id = created.json()["id"]
    before = _write_counts()

    response = client.patch(
        f"/api/payroll/periods/{period_id}",
        headers=auth_headers,
        json={"period_no": "P" * 65},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before
    with TestSessionLocal() as db:
        assert db.get(PayrollPeriod, period_id).period_no == created.json()["period_no"]


def test_payroll_period_storage_error_preserves_auth_and_resource_precedence(client, auth_headers):
    long_period_no = "P" * 65
    unauthenticated = client.post(
        "/api/payroll/periods",
        json=_period_payload(long_period_no),
    )
    assert unauthenticated.status_code == 401, unauthenticated.text

    response = client.patch(
        "/api/payroll/periods/2147483647",
        headers=auth_headers,
        json={"period_no": long_period_no},
    )
    assert response.status_code == 404, response.text
