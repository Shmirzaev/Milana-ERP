from app.models import AuditLog, Bundle, BundleScanLog
from app.tests.conftest import TestSessionLocal


def _create_order(client, auth_headers) -> int:
    response = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 1,
            "items": [{
                "model_id": 1,
                "color": "white",
                "size": "M",
                "planned_quantity": 1,
            }],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _bundle_payload(order_id: int, color: str = "Navy", size: str = "M") -> dict:
    return {
        "production_order_id": order_id,
        "model_id": 1,
        "color": color,
        "size": size,
        "quantity": 1,
    }


def _write_counts() -> tuple[int, int, int]:
    with TestSessionLocal() as db:
        return (
            db.query(Bundle).count(),
            db.query(BundleScanLog).count(),
            db.query(AuditLog).filter(AuditLog.entity_type == "Bundle").count(),
        )


def test_bundle_text_storage_boundaries_are_accepted(client, auth_headers):
    order_id = _create_order(client, auth_headers)

    response = client.post(
        "/api/bundles",
        json=_bundle_payload(order_id, color="C" * 64, size="S" * 32),
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text


def test_bundle_text_overflow_is_rejected_before_writes_and_preserves_precedence(
    client,
    auth_headers,
):
    order_id = _create_order(client, auth_headers)
    before = _write_counts()

    for payload in (
        _bundle_payload(order_id, color="C" * 65),
        _bundle_payload(order_id, size="S" * 33),
    ):
        response = client.post("/api/bundles", json=payload, headers=auth_headers)
        assert response.status_code == 422, response.text
        assert _write_counts() == before

    unauthenticated = client.post(
        "/api/bundles",
        json=_bundle_payload(order_id, color="C" * 65),
    )
    assert unauthenticated.status_code == 401

    missing_order = client.post(
        "/api/bundles",
        json=_bundle_payload(2_147_483_647, color="C" * 65),
        headers=auth_headers,
    )
    assert missing_order.status_code == 404
    assert _write_counts() == before
