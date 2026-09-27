import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, Model, SalesOrder, SalesOrderItem
from app.schemas.sales import SalesOrderItemIn


MAX_INT4 = 2_147_483_647


def _model_id() -> int:
    with SessionLocal() as db:
        return int(db.query(Model.id).filter(Model.catalog_scope == "standard").order_by(Model.id).scalar())


def _line(default_model_id: int, **overrides) -> dict:
    return {
        "model_id": default_model_id,
        "color": "blue",
        "size": "M",
        "quantity": 1,
        "unit_price": 1,
        **overrides,
    }


def _write_counts() -> tuple[int, int, int]:
    with SessionLocal() as db:
        return (
            db.query(SalesOrder).count(),
            db.query(SalesOrderItem).count(),
            db.query(AuditLog).count(),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_id": 0},
        {"model_id": MAX_INT4 + 1},
        {"brand_id": 0},
        {"brand_id": MAX_INT4 + 1},
        {"collection_id": 0},
        {"collection_id": MAX_INT4 + 1},
        {"color": "c" * 65},
        {"size": "s" * 33},
    ],
)
def test_sales_item_rejects_values_outside_storage_bounds(overrides):
    with pytest.raises(ValidationError):
        SalesOrderItemIn(**_line(1, **overrides))


def test_sales_item_preserves_exact_storage_boundaries():
    parsed = SalesOrderItemIn(**_line(
        MAX_INT4,
        brand_id=MAX_INT4,
        collection_id=MAX_INT4,
        color="c" * 64,
        size="s" * 32,
    ))

    assert parsed.model_id == MAX_INT4
    assert parsed.brand_id == MAX_INT4
    assert parsed.collection_id == MAX_INT4
    assert parsed.color == "c" * 64
    assert parsed.size == "s" * 32


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_id": 0},
        {"model_id": MAX_INT4 + 1},
        {"brand_id": MAX_INT4 + 1},
        {"collection_id": MAX_INT4 + 1},
        {"color": "c" * 65},
        {"size": "s" * 33},
    ],
)
def test_invalid_sales_item_storage_values_reject_without_writes(client, auth_headers, overrides):
    before = _write_counts()

    response = client.post(
        "/api/sales-orders",
        headers=auth_headers,
        json={"items": [_line(_model_id(), **overrides)]},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_sales_item_string_boundaries_persist_unchanged(client, auth_headers):
    color = "c" * 64
    size = "s" * 32
    response = client.post(
        "/api/sales-orders",
        headers=auth_headers,
        json={"items": [_line(_model_id(), color=color, size=size)]},
    )

    assert response.status_code == 201, response.text
    order_id = int(response.json()["id"])
    with SessionLocal() as db:
        line = db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == order_id).one()
        assert line.color == color
        assert line.size == size


def test_invalid_sales_item_bounds_preserve_authentication_precedence(client):
    before = _write_counts()

    response = client.post(
        "/api/sales-orders",
        json={"items": [_line(_model_id(), color="c" * 65)]},
    )

    assert response.status_code == 401, response.text
    assert _write_counts() == before
