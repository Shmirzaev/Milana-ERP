from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Item, Role, StockBatch, User, Warehouse, WasteRecord


MAX_WASTE_QUANTITY = Decimal("9999999999.9999")


def _waste_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(WasteRecord).count(),
            db.query(AuditLog).filter(AuditLog.entity_type == "WasteRecord").count(),
        )


def _payload(**overrides) -> dict:
    return {
        "waste_type": "fabric_scrap",
        "quantity": "1.0000",
        "unit": "kg",
        **overrides,
    }


def _cost_item(cost: str) -> int:
    marker = uuid4().hex
    with SessionLocal.begin() as db:
        item = Item(
            sku=f"WASTE-BOUND-{marker}",
            name=f"Waste bound item {marker}",
            category="fabric",
            unit="kg",
            default_cost=Decimal(cost),
            reorder_level=0,
            composition_json=[],
        )
        db.add(item)
        db.flush()
        return item.id


def _unprivileged_headers() -> dict[str, str]:
    marker = uuid4().hex
    with SessionLocal.begin() as db:
        role = Role(name=f"No waste create {marker}", permissions=[])
        db.add(role)
        db.flush()
        user = User(
            name="No waste create",
            email=f"no-waste-create-{marker}@example.invalid",
            password_hash="unused",
            role_id=role.id,
            factory_code="MIL",
        )
        db.add(user)
        db.flush()
        user_id = user.id
    token = create_access_token(user_id, {"factory_code": "MIL"})
    return {"Authorization": f"Bearer {token}"}


def test_waste_create_accepts_exact_quantity_boundary_and_preserves_derived_value(
    client, auth_headers,
):
    maximum = client.post(
        "/api/waste",
        headers=auth_headers,
        json=_payload(quantity=str(MAX_WASTE_QUANTITY)),
    )
    assert maximum.status_code == 201, maximum.text

    item_id = _cost_item("2.5000")
    ordinary = client.post(
        "/api/waste",
        headers=auth_headers,
        json=_payload(quantity="3.0000", item_id=item_id, estimated_value="9999999999.99"),
    )
    assert ordinary.status_code == 201, ordinary.text
    assert ordinary.json()["estimated_value"] == 7.5

    with SessionLocal() as db:
        assert db.get(WasteRecord, maximum.json()["id"]).quantity == MAX_WASTE_QUANTITY
        saved = db.get(WasteRecord, ordinary.json()["id"])
        assert saved.quantity == Decimal("3.0000")
        assert saved.estimated_value == Decimal("7.50")


@pytest.mark.parametrize("quantity", ["0", "-0.0001", "NaN", "Infinity", "-Infinity", "10000000000"])
def test_waste_create_rejects_invalid_quantity_without_writes(
    client, auth_headers, quantity,
):
    before = _waste_counts()

    response = client.post(
        "/api/waste",
        headers=auth_headers,
        json=_payload(quantity=quantity),
    )

    assert response.status_code == 422, response.text
    assert _waste_counts() == before


@pytest.mark.parametrize("quantity", ["1.00005", "1.00004"])
def test_waste_create_rejects_quantity_that_would_round_in_storage_without_writes(
    client, auth_headers, quantity,
):
    before = _waste_counts()

    response = client.post(
        "/api/waste",
        headers=auth_headers,
        json=_payload(quantity=quantity),
    )

    assert response.status_code == 422, response.text
    assert _waste_counts() == before


def test_waste_create_rejects_derived_estimate_overflow_without_writes(
    client, auth_headers,
):
    item_id = _cost_item("100000.0000")
    before = _waste_counts()

    response = client.post(
        "/api/waste",
        headers=auth_headers,
        json=_payload(quantity="100000.0000", item_id=item_id),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "Waste estimated value exceeds supported precision"
    assert _waste_counts() == before


def test_waste_create_checks_authorization_before_invalid_quantity(client):
    before = _waste_counts()

    response = client.post(
        "/api/waste",
        headers=_unprivileged_headers(),
        json=_payload(quantity="Infinity"),
    )

    assert response.status_code == 403, response.text
    assert _waste_counts() == before


def test_waste_create_rejects_cross_item_batch_before_writes(client, auth_headers):
    batch_item_id = _cost_item("4.0000")
    other_item_id = _cost_item("9.0000")
    marker = uuid4().hex
    with SessionLocal.begin() as db:
        warehouse = Warehouse(name=f"Waste mismatch {marker}", type="fabric_storage")
        db.add(warehouse)
        db.flush()
        batch = StockBatch(
            item_id=batch_item_id,
            batch_no=f"WASTE-MISMATCH-{marker}",
            quantity=10,
            unit="kg",
            cost_per_unit=Decimal("4.0000"),
            warehouse_id=warehouse.id,
        )
        db.add(batch)
        db.flush()
        batch_id = batch.id

    before = _waste_counts()
    mismatch = client.post(
        "/api/waste", headers=auth_headers,
        json=_payload(item_id=other_item_id, batch_id=batch_id),
    )
    assert mismatch.status_code == 400, mismatch.text
    assert mismatch.json()["detail"] == "Stock batch does not belong to item"
    assert _waste_counts() == before

    missing_batch = client.post(
        "/api/waste", headers=auth_headers,
        json=_payload(item_id=batch_item_id, batch_id=2_000_000_000),
    )
    assert missing_batch.status_code == 404, missing_batch.text
    assert _waste_counts() == before

    valid = client.post(
        "/api/waste", headers=auth_headers,
        json=_payload(item_id=batch_item_id, batch_id=batch_id),
    )
    assert valid.status_code == 201, valid.text
    assert valid.json()["estimated_value"] == 4.0
