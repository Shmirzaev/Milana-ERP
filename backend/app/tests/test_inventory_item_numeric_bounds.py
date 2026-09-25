from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, Item
from app.schemas.inventory import ItemIn


MAX_DEFAULT_COST = Decimal("99999999.9999")
MAX_REORDER_LEVEL = Decimal("9999999999.9999")


def _payload(**overrides) -> dict:
    suffix = uuid4().hex[:10].upper()
    return {
        "sku": f"BOUND-{suffix}",
        "name": f"Bounded item {suffix}",
        "category": "fabric",
        "unit": "kg",
        "default_cost": "12.3456",
        "reorder_level": "123.4567",
        **overrides,
    }


def _write_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return db.query(Item).count(), db.query(AuditLog).count()


def test_item_numeric_fields_preserve_valid_values_and_exact_storage_maxima():
    parsed = ItemIn(**_payload(
        default_cost=str(MAX_DEFAULT_COST),
        reorder_level=str(MAX_REORDER_LEVEL),
    ))

    assert parsed.default_cost == MAX_DEFAULT_COST
    assert parsed.reorder_level == MAX_REORDER_LEVEL
    assert ItemIn(**_payload()).default_cost == Decimal("12.3456")
    assert ItemIn(**_payload(default_cost="12.345600")).default_cost == Decimal("12.345600")


@pytest.mark.parametrize("cost", ["12.34567", "0.00001", "99999998.99991"])
def test_item_default_cost_rejects_fractional_digits_that_numeric_would_round(cost):
    with pytest.raises(ValidationError, match="4 decimal places"):
        ItemIn(**_payload(default_cost=cost))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("default_cost", "-0.0001"),
        ("default_cost", "NaN"),
        ("default_cost", "Infinity"),
        ("default_cost", "-Infinity"),
        ("default_cost", "100000000"),
        ("default_cost", "12.34567"),
        ("default_cost", "0.00001"),
        ("reorder_level", "-0.0001"),
        ("reorder_level", "NaN"),
        ("reorder_level", "Infinity"),
        ("reorder_level", "-Infinity"),
        ("reorder_level", "10000000000"),
    ],
)
def test_item_numeric_fields_reject_non_finite_negative_and_overflow(field, value):
    with pytest.raises(ValidationError):
        ItemIn(**_payload(**{field: value}))


def test_item_numeric_storage_maxima_persist_exactly(client, auth_headers):
    response = client.post(
        "/api/inventory/items",
        headers=auth_headers,
        json=_payload(
            default_cost=str(MAX_DEFAULT_COST),
            reorder_level=str(MAX_REORDER_LEVEL),
        ),
    )

    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        item = db.get(Item, response.json()["id"])
        assert item is not None
        assert item.default_cost == MAX_DEFAULT_COST
        assert item.reorder_level == MAX_REORDER_LEVEL


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("default_cost", "NaN"),
        ("default_cost", "Infinity"),
        ("default_cost", "100000000"),
        ("default_cost", "12.34567"),
        ("reorder_level", "-0.0001"),
        ("reorder_level", "10000000000"),
    ],
)
def test_invalid_item_numeric_create_has_no_item_or_audit_side_effects(
    client,
    auth_headers,
    field,
    value,
):
    before = _write_counts()

    response = client.post(
        "/api/inventory/items",
        headers=auth_headers,
        json=_payload(**{field: value}),
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


@pytest.mark.parametrize("invalid_cost", ["Infinity", "12.34567"])
def test_invalid_item_numeric_update_preserves_existing_row_and_audit(client, auth_headers, invalid_cost):
    create = client.post(
        "/api/inventory/items",
        headers=auth_headers,
        json=_payload(default_cost="8.1250", reorder_level="17.5000"),
    )
    assert create.status_code == 201, create.text
    item_id = int(create.json()["id"])
    before = _write_counts()

    response = client.patch(
        f"/api/inventory/items/{item_id}",
        headers=auth_headers,
        json=_payload(default_cost=invalid_cost, reorder_level="20"),
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before
    with SessionLocal() as db:
        item = db.get(Item, item_id)
        assert item is not None
        assert item.default_cost == Decimal("8.1250")
        assert item.reorder_level == Decimal("17.5000")


@pytest.mark.parametrize("invalid_cost", ["Infinity", "12.34567"])
def test_invalid_item_numeric_input_preserves_authentication_precedence(client, invalid_cost):
    before = _write_counts()

    response = client.post(
        "/api/inventory/items",
        json=_payload(default_cost=invalid_cost),
    )

    assert response.status_code == 401, response.text
    assert _write_counts() == before
