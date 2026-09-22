from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, Model, Notification, PriceCalculationRequest
from app.schemas.price_calculation import PriceCalculationPurchasingIn


MAX_PRICE = Decimal("9999999999.9999")


def _create_request(client, auth_headers) -> int:
    with SessionLocal() as db:
        model_id = int(
            db.query(Model.id)
            .filter(Model.catalog_scope == "standard")
            .order_by(Model.id)
            .scalar()
        )
    response = client.post(
        "/api/price-calculation/requests",
        headers=auth_headers,
        json={"model_id": model_id},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _state(request_id: int) -> tuple:
    with SessionLocal() as db:
        request = db.get(PriceCalculationRequest, request_id)
        assert request is not None
        return (
            request.fabric_price,
            request.sewing_cost,
            request.purchasing_updated_by_id,
            db.query(AuditLog).count(),
            db.query(Notification).count(),
        )


def _write_counts() -> tuple[int, int, int]:
    with SessionLocal() as db:
        return (
            db.query(PriceCalculationRequest).count(),
            db.query(AuditLog).count(),
            db.query(Notification).count(),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fabric_price", "NaN"),
        ("fabric_price", "Infinity"),
        ("fabric_price", "-Infinity"),
        ("fabric_price", "10000000000"),
        ("sewing_cost", "NaN"),
        ("sewing_cost", "Infinity"),
        ("sewing_cost", "-Infinity"),
        ("sewing_cost", "10000000000"),
    ],
)
def test_purchasing_price_fields_reject_non_finite_and_storage_overflow(field, value):
    with pytest.raises(ValidationError):
        PriceCalculationPurchasingIn(**{field: value})


def test_purchasing_price_fields_preserve_none_zero_values_and_storage_maximum():
    assert PriceCalculationPurchasingIn().model_dump() == {
        "fabric_price": None,
        "sewing_cost": None,
    }
    assert PriceCalculationPurchasingIn(fabric_price=0, sewing_cost="0.1674").model_dump() == {
        "fabric_price": 0.0,
        "sewing_cost": 0.1674,
    }
    parsed = PriceCalculationPurchasingIn(
        fabric_price=str(MAX_PRICE),
        sewing_cost=str(MAX_PRICE),
    )
    assert parsed.fabric_price == pytest.approx(float(MAX_PRICE))
    assert parsed.sewing_cost == pytest.approx(float(MAX_PRICE))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fabric_price", "NaN"),
        ("fabric_price", "10000000000"),
        ("sewing_cost", "Infinity"),
        ("sewing_cost", "10000000000"),
    ],
)
def test_invalid_purchasing_price_update_has_no_request_audit_or_notification_side_effects(
    client,
    auth_headers,
    field,
    value,
):
    request_id = _create_request(client, auth_headers)
    before = _state(request_id)

    response = client.patch(
        f"/api/price-calculation/requests/{request_id}/purchasing",
        headers=auth_headers,
        json={"fabric_price": 4.5, "sewing_cost": 0.1674, field: value},
    )

    assert response.status_code == 422, response.text
    assert _state(request_id) == before


def test_purchasing_price_storage_maximum_persists_exactly(client, auth_headers):
    request_id = _create_request(client, auth_headers)

    response = client.patch(
        f"/api/price-calculation/requests/{request_id}/purchasing",
        headers=auth_headers,
        json={"fabric_price": str(MAX_PRICE), "sewing_cost": str(MAX_PRICE)},
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        request = db.get(PriceCalculationRequest, request_id)
        assert request is not None
        assert request.fabric_price == MAX_PRICE
        assert request.sewing_cost == MAX_PRICE


def test_invalid_purchasing_price_input_preserves_authentication_precedence(client):
    before = _write_counts()

    response = client.patch(
        "/api/price-calculation/requests/1/purchasing",
        json={"fabric_price": "Infinity", "sewing_cost": 1},
    )

    assert response.status_code == 401, response.text
    assert _write_counts() == before
