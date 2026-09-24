"""Payroll period creation rejects unknown initial states without side effects."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.tests.conftest import TestSessionLocal
from app.models import AuditLog, PayrollPeriod


def _payload(status: str) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "name": f"DB02 Period {uuid4().hex}",
        "start_date": (now - timedelta(days=1)).isoformat(),
        "end_date": (now + timedelta(days=1)).isoformat(),
        "status": status,
    }


def _counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return db.query(PayrollPeriod).count(), db.query(AuditLog).count()


@pytest.mark.parametrize("status", ["draft", "open"])
def test_create_period_accepts_each_supported_initial_status(client, auth_headers, status):
    before = _counts()

    response = client.post("/api/payroll/periods", json=_payload(status), headers=auth_headers)

    assert response.status_code == 201, response.text
    assert response.json()["status"] == status
    assert _counts() == (before[0] + 1, before[1] + 1)


def test_create_period_rejects_unknown_status_without_writes_and_keeps_auth_precedence(client, auth_headers):
    before = _counts()

    invalid = client.post(
        "/api/payroll/periods",
        json=_payload("approved"),
        headers=auth_headers,
    )
    assert invalid.status_code == 400, invalid.text
    assert invalid.json() == {"detail": "New payroll periods must be draft or open"}
    assert _counts() == before

    unauthenticated = client.post("/api/payroll/periods", json=_payload("approved"))
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert _counts() == before
