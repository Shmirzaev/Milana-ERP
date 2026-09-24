import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, ProductionOrder, ProductionOrderItem
from app.schemas.production import (
    ProductionOrderIn,
    ProductionOrderItemIn,
    ProductionOrderUpdateIn,
)


MAX_SQL_INTEGER = 2_147_483_647


def _write_counts() -> tuple[int, int, int]:
    with SessionLocal() as db:
        return (
            db.query(ProductionOrder).count(),
            db.query(ProductionOrderItem).count(),
            db.query(AuditLog).count(),
        )


@pytest.mark.parametrize(
    "value",
    [0, MAX_SQL_INTEGER],
)
def test_production_order_quantities_accept_nonnegative_sql_integer_bounds(value):
    assert ProductionOrderIn(production_type="branded_stock", model_id=1, planned_quantity=value).planned_quantity == value
    assert ProductionOrderItemIn(
        model_id=1,
        color="navy",
        size="M",
        planned_quantity=value,
    ).planned_quantity == value
    assert ProductionOrderUpdateIn(planned_quantity=value).planned_quantity == value


@pytest.mark.parametrize("value", [-1, MAX_SQL_INTEGER + 1, 1.5, True])
def test_production_order_quantities_reject_invalid_integer_storage_values(value):
    with pytest.raises(ValidationError):
        ProductionOrderIn(
            production_type="branded_stock",
            model_id=1,
            planned_quantity=value,
        )
    with pytest.raises(ValidationError):
        ProductionOrderItemIn(
            model_id=1,
            color="navy",
            size="M",
            planned_quantity=value,
        )
    with pytest.raises(ValidationError):
        ProductionOrderUpdateIn(planned_quantity=value)


def test_invalid_production_order_quantity_has_no_write_side_effects(client, auth_headers):
    before = _write_counts()
    response = client.post(
        "/api/production-orders",
        headers=auth_headers,
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": MAX_SQL_INTEGER + 1,
        },
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_invalid_production_order_quantity_preserves_authentication_precedence(client):
    before = _write_counts()
    response = client.post(
        "/api/production-orders",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": MAX_SQL_INTEGER + 1,
        },
    )

    assert response.status_code == 401, response.text
    assert _write_counts() == before
