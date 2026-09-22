from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, Model, Notification, PriceCalculationRequest
from app.schemas.price_calculation import PriceCalculationFinanceIn


MAX_PRICE = Decimal("9999999999.9999")
MAX_PERCENTAGE = Decimal("999999.99")
MAX_COST_PRICE = Decimal("9999999999999999.99")
SQLITE_SAFE_HIGH_COST_PRICE = Decimal("9999999999999998.00")


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
        model = db.get(Model, request.model_id)
        assert model is not None
        return (
            request.selling_price,
            request.profit_percentage,
            request.exchange_rate,
            request.finance_updated_by_id,
            model.selling_price,
            model.selling_price_source,
            model.selling_price_request_id,
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
        ("cost_price_uzs", "NaN"),
        ("cost_price_uzs", "Infinity"),
        ("cost_price_uzs", "10000000000000000"),
        ("selling_price", "NaN"),
        ("selling_price", "Infinity"),
        ("selling_price", "10000000000"),
        ("profit_percentage", "NaN"),
        ("profit_percentage", "Infinity"),
        ("profit_percentage", "1000000"),
        ("exchange_rate", "NaN"),
        ("exchange_rate", "Infinity"),
        ("exchange_rate", "10000000000"),
    ],
)
def test_finance_fields_reject_non_finite_and_storage_overflow(field, value):
    with pytest.raises(ValidationError):
        PriceCalculationFinanceIn(**{field: value})


def test_finance_fields_preserve_none_zero_ordinary_values_and_storage_maxima():
    assert PriceCalculationFinanceIn().model_dump() == {
        "cost_price_uzs": None,
        "selling_price": None,
        "profit_percentage": None,
        "exchange_rate": None,
    }
    assert PriceCalculationFinanceIn(cost_price_uzs=str(MAX_COST_PRICE)).cost_price_uzs == MAX_COST_PRICE
    assert PriceCalculationFinanceIn(
        selling_price=0,
        profit_percentage="12.25",
        exchange_rate="12750.5",
    ).model_dump(exclude={"cost_price_uzs"}) == {
        "selling_price": 0.0,
        "profit_percentage": 12.25,
        "exchange_rate": 12750.5,
    }
    maximum = PriceCalculationFinanceIn(
        selling_price=str(MAX_PRICE),
        profit_percentage=str(MAX_PERCENTAGE),
        exchange_rate=str(MAX_PRICE),
    )
    assert maximum.selling_price == pytest.approx(float(MAX_PRICE))
    assert maximum.profit_percentage == pytest.approx(float(MAX_PERCENTAGE))
    assert maximum.exchange_rate == pytest.approx(float(MAX_PRICE))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selling_price", "Infinity"),
        ("selling_price", "10000000000"),
        ("profit_percentage", "1000000"),
        ("exchange_rate", "NaN"),
        ("exchange_rate", "10000000000"),
    ],
)
def test_invalid_finance_update_has_no_request_model_audit_or_notification_side_effects(
    client,
    auth_headers,
    field,
    value,
):
    request_id = _create_request(client, auth_headers)
    before = _state(request_id)

    response = client.patch(
        f"/api/price-calculation/requests/{request_id}/finance",
        headers=auth_headers,
        json={"selling_price": 0, "profit_percentage": 12, "exchange_rate": 12750, field: value},
    )

    assert response.status_code == 422, response.text
    assert _state(request_id) == before


def test_finance_non_selling_high_precision_values_persist_exactly(client, auth_headers):
    request_id = _create_request(client, auth_headers)

    response = client.patch(
        f"/api/price-calculation/requests/{request_id}/finance",
        headers=auth_headers,
        json={
            "selling_price": 0,
            "cost_price_uzs": str(SQLITE_SAFE_HIGH_COST_PRICE),
            "profit_percentage": str(MAX_PERCENTAGE),
            "exchange_rate": str(MAX_PRICE),
        },
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        request = db.get(PriceCalculationRequest, request_id)
        assert request is not None
        assert request.cost_price_uzs == SQLITE_SAFE_HIGH_COST_PRICE
        assert request.selling_price == Decimal("0.0000")
        assert request.profit_percentage == MAX_PERCENTAGE
        assert request.exchange_rate == MAX_PRICE


def test_invalid_finance_input_preserves_authentication_precedence(client):
    before = _write_counts()

    response = client.patch(
        "/api/price-calculation/requests/1/finance",
        json={"selling_price": "Infinity"},
    )

    assert response.status_code == 401, response.text
    assert _write_counts() == before
