"""Bound 1C finance batches before any integration writes begin."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, Invoice, Payment
from app.schemas.integrations import OneCSyncIn


def _rows(kind: str, count: int, marker: str) -> list[dict]:
    prefix = "invoice" if kind == "invoices" else "payment"
    return [
        {"external_id": f"{prefix}-{marker}-{index}", "amount": 1}
        for index in range(count)
    ]


@pytest.mark.parametrize("kind", ["invoices", "payments"])
def test_1c_sync_schema_accepts_500_rows_and_rejects_501(kind):
    marker = uuid4().hex[:8]
    accepted = OneCSyncIn(**{kind: _rows(kind, 500, marker)})
    assert len(getattr(accepted, kind)) == 500

    with pytest.raises(ValidationError):
        OneCSyncIn(**{kind: _rows(kind, 501, marker)})


@pytest.mark.parametrize("kind", ["invoices", "payments"])
def test_1c_sync_api_rejects_oversized_stream_without_writes(client, kind):
    marker = uuid4().hex[:12]
    with SessionLocal() as db:
        before = {
            "invoices": db.query(Invoice).count(),
            "payments": db.query(Payment).count(),
            "audits": db.query(AuditLog).count(),
        }

    response = client.post(
        "/api/finance/integrations/1c/sync",
        headers={"X-1C-Token": "test-1c-token"},
        json={kind: _rows(kind, 501, marker)},
    )

    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.query(Invoice).count() == before["invoices"]
        assert db.query(Payment).count() == before["payments"]
        assert db.query(AuditLog).count() == before["audits"]
        assert db.query(Invoice).filter(Invoice.external_id.like(f"%-{marker}-%")).count() == 0
        assert db.query(Payment).filter(Payment.external_id.like(f"%-{marker}-%")).count() == 0
