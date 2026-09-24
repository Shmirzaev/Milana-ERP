from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    Item,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    Role,
    Supplier,
    User,
)
from app.schemas.purchasing import PurchaseOrderLineIn, PurchaseRequestLineIn


_VARCHAR_LIMITS = {"unit": 32, "material_name": 255, "photo_url": 500}


@pytest.mark.parametrize(
    ("line_schema", "quantity_field"),
    [
        (PurchaseRequestLineIn, "required_quantity"),
        (PurchaseOrderLineIn, "ordered_quantity"),
    ],
)
def test_purchase_line_varchar_schema_documents_limits_and_preserves_optional_values(
    line_schema, quantity_field
):
    base = {"item_id": 1, quantity_field: 1}
    boundary_values = {name: name[0] * limit for name, limit in _VARCHAR_LIMITS.items()}

    # Length enforcement is deferred until service reference/business checks;
    # schema metadata still advertises each physical VARCHAR limit to clients.
    line = line_schema.model_validate({**base, **boundary_values})
    assert {name: getattr(line, name) for name in _VARCHAR_LIMITS} == boundary_values
    assert line_schema.model_fields["unit"].json_schema_extra == {"maxLength": 32}
    assert line_schema.model_fields["material_name"].json_schema_extra == {"maxLength": 255}
    assert line_schema.model_fields["photo_url"].json_schema_extra == {"maxLength": 500}

    nullable_line = line_schema.model_validate({**base, **dict.fromkeys(_VARCHAR_LIMITS)})
    assert all(getattr(nullable_line, name) is None for name in _VARCHAR_LIMITS)


def _write_counts():
    with SessionLocal() as db:
        return (
            db.query(PurchaseRequest).count(),
            db.query(PurchaseRequestLine).count(),
            db.query(PurchaseOrder).count(),
            db.query(PurchaseOrderLine).count(),
            db.query(AuditLog).count(),
        )


def test_purchase_line_varchar_api_accepts_boundaries_and_rejects_overflow_before_writes(
    client, auth_headers
):
    boundary_values = {name: name[0] * limit for name, limit in _VARCHAR_LIMITS.items()}
    with SessionLocal() as db:
        item = Item(
            sku=f"PURCHASE-UNIT-BOUND-{uuid4().hex}",
            name="Purchase unit boundary item",
            category="fabric",
            unit=boundary_values["unit"],
            is_active=True,
        )
        db.add(item)
        db.commit()
        item_id = int(item.id)
    before = _write_counts()

    request_response = client.post(
        "/api/purchasing/requests",
        json={"status": "draft", "lines": [{"item_id": item_id, **boundary_values}]},
        headers=auth_headers,
    )
    assert request_response.status_code == 201, request_response.text
    assert {name: request_response.json()["lines"][0][name] for name in _VARCHAR_LIMITS} == boundary_values

    order_response = client.post(
        "/api/purchasing/orders",
        json={
            "lines": [{"item_id": item_id, "ordered_quantity": 1, "unit_cost": 1, **boundary_values}]
        },
        headers=auth_headers,
    )
    assert order_response.status_code == 201, order_response.text
    assert {name: order_response.json()["lines"][0][name] for name in _VARCHAR_LIMITS} == boundary_values

    after_valid = _write_counts()
    assert after_valid == (
        before[0] + 1,
        before[1] + 1,
        before[2] + 1,
        before[3] + 1,
        before[4] + 2,
    )

    for field, limit in _VARCHAR_LIMITS.items():
        overlong = "x" * (limit + 1)
        request = client.post(
            "/api/purchasing/requests",
            json={"status": "draft", "lines": [{"item_id": 1, field: overlong}]},
            headers=auth_headers,
        )
        assert request.status_code == 422, (field, request.text)

        order = client.post(
            "/api/purchasing/orders",
            json={"lines": [{"item_id": 1, "ordered_quantity": 1, field: overlong}]},
            headers=auth_headers,
        )
        assert order.status_code == 422, (field, order.text)

    assert _write_counts() == after_valid


def test_purchase_line_varchar_validation_preserves_reference_precedence(client, auth_headers):
    with SessionLocal() as db:
        last_item = db.query(Item.id).order_by(Item.id.desc()).first()
        last_supplier = db.query(Supplier.id).order_by(Supplier.id.desc()).first()
        missing_item_id = (last_item[0] if last_item else 0) + 10_000
        missing_supplier_id = (last_supplier[0] if last_supplier else 0) + 10_000
        before = (
            db.query(PurchaseRequest).count(),
            db.query(PurchaseRequestLine).count(),
            db.query(PurchaseOrder).count(),
            db.query(PurchaseOrderLine).count(),
            db.query(AuditLog).count(),
        )

    oversized = "x" * (_VARCHAR_LIMITS["unit"] + 1)
    missing_item_request = client.post(
        "/api/purchasing/requests",
        json={"status": "draft", "lines": [{"item_id": missing_item_id, "unit": oversized}]},
        headers=auth_headers,
    )
    assert missing_item_request.status_code == 404, missing_item_request.text

    missing_item_order = client.post(
        "/api/purchasing/orders",
        json={"lines": [{"item_id": missing_item_id, "ordered_quantity": 1, "unit": oversized}]},
        headers=auth_headers,
    )
    assert missing_item_order.status_code == 404, missing_item_order.text

    missing_supplier_request = client.post(
        "/api/purchasing/requests",
        json={
            "status": "draft",
            "lines": [{"item_id": 1, "preferred_supplier_id": missing_supplier_id, "photo_url": "x" * 501}],
        },
        headers=auth_headers,
    )
    assert missing_supplier_request.status_code == 404, missing_supplier_request.text

    missing_supplier_order = client.post(
        "/api/purchasing/orders",
        json={
            "supplier_id": missing_supplier_id,
            "lines": [{"item_id": 1, "ordered_quantity": 1, "photo_url": "x" * 501}],
        },
        headers=auth_headers,
    )
    assert missing_supplier_order.status_code == 404, missing_supplier_order.text
    assert _write_counts() == before


def test_purchase_line_varchar_validation_preserves_auth_precedence(client):
    with SessionLocal() as db:
        role = Role(name=f"No purchasing line writes {uuid4().hex}", permissions=[])
        db.add(role)
        db.flush()
        user = User(
            name="Denied purchasing line writer",
            email=f"denied-purchasing-line-{uuid4().hex}@example.invalid",
            password_hash="unused-purchase-line-bound-hash",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(user)
        db.commit()
        denied_headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    oversized_request = {
        "status": "draft",
        "lines": [{"item_id": 1, "unit": "x" * (_VARCHAR_LIMITS["unit"] + 1)}],
    }
    oversized_order = {
        "lines": [{
            "item_id": 1,
            "ordered_quantity": 1,
            "unit": "x" * (_VARCHAR_LIMITS["unit"] + 1),
        }],
    }

    for path, payload in (
        ("/api/purchasing/requests", oversized_request),
        ("/api/purchasing/orders", oversized_order),
    ):
        assert client.post(path, json=payload).status_code == 401
        assert client.post(path, json=payload, headers=denied_headers).status_code == 403
