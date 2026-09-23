from app.db.session import SessionLocal
from app.models import AuditLog, ProductionOrder


MAX_ESTIMATED_MATERIAL_AMOUNT = 9_999_999_999.9999


def _write_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(ProductionOrder).count(),
            db.query(AuditLog).count(),
        )


def _payload(model_id: int, amount: object) -> dict:
    return {
        "production_type": "branded_stock",
        "model_id": model_id,
        "estimated_material_amount": amount,
    }


def test_estimated_material_amount_rejects_non_finite_and_numeric_overflow(
    client,
    auth_headers,
):
    before = _write_counts()

    for amount in ("NaN", "Infinity", 10_000_000_000):
        response = client.post(
            "/api/production-orders",
            headers=auth_headers,
            json=_payload(1, amount),
        )

        assert response.status_code == 422, response.text
        assert _write_counts() == before


def test_estimated_material_amount_accepts_storage_maximum(client, auth_headers):
    response = client.post(
        "/api/production-orders",
        headers=auth_headers,
        json=_payload(1, MAX_ESTIMATED_MATERIAL_AMOUNT),
    )

    assert response.status_code == 201, response.text
    assert response.json()["estimated_material_amount"] == MAX_ESTIMATED_MATERIAL_AMOUNT


def test_estimated_material_amount_keeps_auth_and_model_error_precedence(client, auth_headers):
    unauthenticated = client.post(
        "/api/production-orders",
        json=_payload(1, "Infinity"),
    )
    assert unauthenticated.status_code == 401

    missing_model = client.post(
        "/api/production-orders",
        headers=auth_headers,
        json=_payload(2_147_483_647, "Infinity"),
    )
    assert missing_model.status_code == 404
