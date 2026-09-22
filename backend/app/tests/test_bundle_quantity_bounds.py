import pytest
from pydantic import ValidationError

from app.models import AuditLog, Bundle
from app.schemas.tracking import BundleIn
from app.tests.conftest import TestSessionLocal


def _payload(quantity: int) -> dict:
    return {
        "production_order_id": 1,
        "model_id": 1,
        "color": "Navy",
        "size": "M",
        "quantity": quantity,
    }


def test_bundle_quantity_accepts_postgresql_integer_maximum():
    parsed = BundleIn.model_validate(_payload(2_147_483_647))

    assert parsed.quantity == 2_147_483_647


def test_bundle_quantity_rejects_postgresql_integer_overflow():
    with pytest.raises(ValidationError):
        BundleIn.model_validate(_payload(2_147_483_648))


def test_bundle_quantity_overflow_rejects_without_writes_and_keeps_auth_precedence(
    client, auth_headers
):
    with TestSessionLocal() as db:
        before = (db.query(Bundle).count(), db.query(AuditLog).count())

    rejected = client.post(
        "/api/bundles",
        json=_payload(2_147_483_648),
        headers=auth_headers,
    )
    assert rejected.status_code == 422, rejected.text

    unauthenticated = client.post("/api/bundles", json=_payload(2_147_483_648))
    assert unauthenticated.status_code == 401, unauthenticated.text

    with TestSessionLocal() as db:
        assert (db.query(Bundle).count(), db.query(AuditLog).count()) == before
