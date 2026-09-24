from uuid import uuid4

import pytest

from app.models import AuditLog, Item
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize(
    "category",
    ["fabric", "semi_finished", "accessory", "packaging", "finished", "waste"],
)
def test_full_storage_user_can_create_each_canonical_item_category(client, auth_headers, category):
    suffix = uuid4().hex[:10]
    response = client.post(
        "/api/inventory/items",
        headers=auth_headers,
        json={
            "sku": f"CAT-{category[:3].upper()}-{suffix}",
            "name": f"Category test {category} {suffix}",
            "category": category,
            "unit": "pcs",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["category"] == category


def test_invalid_item_category_create_is_rejected_without_item_or_audit_write(client, auth_headers):
    suffix = uuid4().hex[:10]
    sku = f"CAT-BAD-{suffix}"
    with TestSessionLocal() as db:
        before_audit = db.query(AuditLog).filter(AuditLog.entity_type == "Item").count()

    response = client.post(
        "/api/inventory/items",
        headers=auth_headers,
        json={
            "sku": sku,
            "name": f"Invalid category {suffix}",
            "category": "not-a-real-item-kind",
            "unit": "pcs",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid item category"}
    with TestSessionLocal() as db:
        assert db.query(Item).filter(Item.sku == sku).count() == 0
        assert db.query(AuditLog).filter(AuditLog.entity_type == "Item").count() == before_audit


def test_legacy_item_category_can_be_resubmitted_but_not_changed_to_unknown(client, auth_headers):
    suffix = uuid4().hex[:10]
    with TestSessionLocal() as db:
        item = Item(
            sku=f"LEGACY-CAT-{suffix}",
            name=f"Legacy category item {suffix}",
            category="Legacy imported kind",
            unit="pcs",
        )
        db.add(item)
        db.commit()
        item_id = item.id

    unchanged_category = client.patch(
        f"/api/inventory/items/{item_id}",
        headers=auth_headers,
        json={
            "sku": f"LEGACY-CAT-{suffix}",
            "name": f"Renamed legacy category item {suffix}",
            "category": "Legacy imported kind",
            "unit": "pcs",
        },
    )

    assert unchanged_category.status_code == 200, unchanged_category.text
    assert unchanged_category.json()["category"] == "Legacy imported kind"
    assert unchanged_category.json()["name"] == f"Renamed legacy category item {suffix}"

    with TestSessionLocal() as db:
        before_audit = db.query(AuditLog).filter(AuditLog.entity_type == "Item").count()

    changed_to_unknown = client.patch(
        f"/api/inventory/items/{item_id}",
        headers=auth_headers,
        json={
            "sku": f"LEGACY-CAT-{suffix}",
            "name": f"Should not persist {suffix}",
            "category": "Another legacy kind",
            "unit": "pcs",
        },
    )

    assert changed_to_unknown.status_code == 400
    assert changed_to_unknown.json() == {"detail": "Invalid item category"}
    with TestSessionLocal() as db:
        item = db.get(Item, item_id)
        assert item is not None
        assert item.category == "Legacy imported kind"
        assert item.name == f"Renamed legacy category item {suffix}"
        assert db.query(AuditLog).filter(AuditLog.entity_type == "Item").count() == before_audit


def test_item_category_validation_preserves_authentication_precedence(client, auth_headers):
    payload = {
        "sku": f"CAT-UNAUTH-{uuid4().hex[:10]}",
        "name": "Unauthorized invalid category",
        "category": "not-a-real-item-kind",
        "unit": "pcs",
    }

    response = client.post("/api/inventory/items", json=payload)

    assert response.status_code == 401


def test_item_category_validation_preserves_missing_item_precedence(client, auth_headers):
    response = client.patch(
        "/api/inventory/items/2000000000",
        headers=auth_headers,
        json={
            "sku": "MISSING-ITEM-CATEGORY",
            "name": "Missing item",
            "category": "not-a-real-item-kind",
            "unit": "pcs",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Item not found"}

