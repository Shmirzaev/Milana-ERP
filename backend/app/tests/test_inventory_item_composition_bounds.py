from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, Item


MAX_COMPOSITION_ROWS = 100
MAX_COMPOSITION_NAME_LENGTH = 255


def _item_payload(*, composition, **overrides):
    suffix = uuid4().hex[:10].upper()
    return {
        "sku": f"COMP-{suffix}",
        "name": f"Composition item {suffix}",
        "category": "fabric",
        "unit": "kg",
        "default_cost": 1,
        "reorder_level": 0,
        "track_batch": True,
        "is_active": True,
        "composition": composition,
        **overrides,
    }


def _item_write_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(Item).count(),
            db.query(AuditLog).filter(AuditLog.entity_type == "Item").count(),
        )


def test_item_composition_accepts_100_nonblank_rows_and_255_char_name(client, auth_headers):
    longest_name = "M" * MAX_COMPOSITION_NAME_LENGTH
    composition = [{"name": "   ", "percentage": 100}]
    composition.extend(
        {"name": longest_name if index == 0 else f"Material {index}", "percentage": 0}
        for index in range(MAX_COMPOSITION_ROWS)
    )

    response = client.post(
        "/api/inventory/items",
        headers=auth_headers,
        json=_item_payload(composition=composition),
    )

    assert response.status_code == 201, response.text
    saved = response.json()["composition"]
    assert len(saved) == MAX_COMPOSITION_ROWS
    assert saved[0] == {"name": longest_name, "percentage": 0}


@pytest.mark.parametrize(
    "composition",
    [
        [{"name": f"Material {index}", "percentage": 0} for index in range(MAX_COMPOSITION_ROWS + 1)],
        [{"name": "M" * (MAX_COMPOSITION_NAME_LENGTH + 1), "percentage": 0}],
    ],
    ids=["too-many-rows", "name-too-long"],
)
def test_item_composition_bounds_reject_create_without_item_or_audit_write(client, auth_headers, composition):
    before = _item_write_counts()

    response = client.post(
        "/api/inventory/items",
        headers=auth_headers,
        json=_item_payload(composition=composition),
    )

    assert response.status_code == 422, response.text
    assert _item_write_counts() == before


def test_item_composition_total_error_precedes_new_shape_bounds(client, auth_headers):
    composition = [{"name": f"Material {index}", "percentage": 1} for index in range(MAX_COMPOSITION_ROWS + 1)]
    before = _item_write_counts()

    response = client.post(
        "/api/inventory/items",
        headers=auth_headers,
        json=_item_payload(composition=composition),
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Composition total cannot exceed 100%"
    assert _item_write_counts() == before


def test_item_composition_bounds_reject_patch_without_mutation_or_audit(client, auth_headers):
    create = client.post(
        "/api/inventory/items",
        headers=auth_headers,
        json=_item_payload(composition=[{"name": "Cotton", "percentage": 100}]),
    )
    assert create.status_code == 201, create.text
    item_id = create.json()["id"]
    before = _item_write_counts()
    oversized = [{"name": f"Material {index}", "percentage": 0} for index in range(MAX_COMPOSITION_ROWS + 1)]

    response = client.patch(
        f"/api/inventory/items/{item_id}",
        headers=auth_headers,
        json=_item_payload(composition=oversized, sku=create.json()["sku"], name="Changed item"),
    )

    assert response.status_code == 422, response.text
    assert _item_write_counts() == before
    with SessionLocal() as db:
        saved = db.get(Item, item_id)
        assert saved.name == create.json()["name"]
        assert saved.composition_json == [{"name": "Cotton", "percentage": 100.0}]


def test_unchanged_legacy_composition_remains_patchable_and_readable(client, auth_headers):
    suffix = uuid4().hex[:10].upper()
    legacy_composition = [
        {"name": f"Legacy material {index}", "percentage": 0, "source": "legacy-extension"}
        for index in range(MAX_COMPOSITION_ROWS + 1)
    ]
    legacy_composition[0]["name"] = "L" * (MAX_COMPOSITION_NAME_LENGTH + 1)
    with SessionLocal.begin() as db:
        item = Item(
            sku=f"LEGACY-COMP-{suffix}",
            name=f"Legacy composition {suffix}",
            category="fabric",
            unit="kg",
            default_cost=1,
            reorder_level=0,
            track_batch=True,
            is_active=True,
            composition_json=legacy_composition,
        )
        db.add(item)
        db.flush()
        item_id = item.id

    public_composition = [
        {"name": row["name"], "percentage": row["percentage"]}
        for row in legacy_composition
    ]
    response = client.patch(
        f"/api/inventory/items/{item_id}",
        headers=auth_headers,
        json=_item_payload(
            composition=public_composition,
            sku=f"LEGACY-COMP-{suffix}",
            name=f"Updated legacy composition {suffix}",
        ),
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["composition"]) == MAX_COMPOSITION_ROWS + 1
    assert len(response.json()["composition"][0]["name"]) == MAX_COMPOSITION_NAME_LENGTH + 1
    with SessionLocal() as db:
        saved = db.get(Item, item_id)
        assert saved.name == f"Updated legacy composition {suffix}"
        assert saved.composition_json == legacy_composition
