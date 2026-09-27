import pytest

from app.models import AuditLog, SalesOrder
from app.schemas.sales import SalesOrderIn
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("order_type", ["client_order", "branded_stock_sale"])
def test_sales_order_schema_accepts_supported_order_types(order_type):
    parsed = SalesOrderIn(order_type=order_type)

    assert parsed.order_type == order_type


def test_sales_order_schema_rejects_unknown_order_type():
    with pytest.raises(ValueError):
        SalesOrderIn(order_type="service_order")


def _write_counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return (
            db.query(SalesOrder).count(),
            db.query(AuditLog).filter_by(entity_type="SalesOrder").count(),
        )


def test_sales_order_create_rejects_unknown_order_type_without_writes(client, auth_headers):
    before = _write_counts()

    response = client.post(
        "/api/sales-orders",
        headers=auth_headers,
        json={"order_type": "service_order", "items": []},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_sales_order_create_keeps_authentication_precedence_for_unknown_type(client):
    response = client.post(
        "/api/sales-orders",
        json={"order_type": "service_order", "items": []},
    )

    assert response.status_code == 401, response.text
