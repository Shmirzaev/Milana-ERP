"""Purchase request creation accepts only the established draft/approval states."""

from app.db.session import SessionLocal
from app.models import AuditLog, Item, PurchaseRequest, PurchaseRequestLine


def _counts():
    with SessionLocal() as db:
        return (
            db.query(PurchaseRequest).count(),
            db.query(PurchaseRequestLine).count(),
            db.query(AuditLog).count(),
        )


def _payload(status):
    with SessionLocal() as db:
        item_unit = db.query(Item.unit).filter(Item.id == 1).scalar()
    return {
        "status": status,
        "lines": [{"item_id": 1, "unit": item_unit, "requested_quantity": 2}],
    }


def test_purchase_request_creation_accepts_established_and_legacy_normalized_statuses(client, auth_headers):
    before = _counts()

    for offset, (raw_status, expected_status) in enumerate(
        (("draft", "draft"), ("pending_approval", "pending_approval"), (" draft ", "draft"), (None, "pending_approval")),
        start=1,
    ):
        response = client.post(
            "/api/purchasing/requests",
            json=_payload(raw_status),
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        assert response.json()["status"] == expected_status
        assert _counts() == (before[0] + offset, before[1] + offset, before[2] + offset)


def test_purchase_request_creation_rejects_unknown_status_without_writes_and_keeps_auth_precedence(
    client, auth_headers
):
    before = _counts()

    response = client.post(
        "/api/purchasing/requests",
        json=_payload("approved"),
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text
    assert _counts() == before

    unauthenticated = client.post(
        "/api/purchasing/requests",
        json=_payload("approved"),
    )
    assert unauthenticated.status_code == 401
    assert _counts() == before
