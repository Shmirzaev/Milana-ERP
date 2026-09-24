"""The generic production-order editor cannot mutate workflow-owned fields."""

from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.models import AuditLog, Model, ProductionOrder, SalesOrder, User
from app.tests.conftest import TestSessionLocal


STANDARD_STATUSES = (
    "new",
    "planning",
    "waiting_material",
    "cutting",
    "printing",
    "sewing",
    "packaging",
    "storage_transfer",
    "finished_storage",
    "delivered",
    "closed",
    "cancelled",
)


def _update_targets():
    marker = uuid4().hex
    with TestSessionLocal() as db:
        standard_model = Model(
            code=f"PO-UPD-{marker}",
            name="Production update target",
            catalog_scope="standard",
            status="approved",
        )
        usluga_model = Model(
            code=f"PO-UPD-USL-{marker}",
            name="Isolated Usluga model",
            catalog_scope="usluga",
            factory_code="ECO",
            status="approved",
        )
        sales_order = SalesOrder(
            order_no=f"SO-UPD-{marker}",
            order_type="client_order",
            status="confirmed",
            total_amount=0,
        )
        db.add_all([standard_model, usluga_model, sales_order])
        db.flush()
        order = ProductionOrder(
            production_no=f"PO-UPD-SOURCE-{marker}",
            production_type="branded_stock",
            source_type="standard",
            model_id=1,
            status="new",
            planned_quantity=20,
            estimated_material_code="OLD-FABRIC",
            estimated_material_amount=5,
            estimated_material_unit="kg",
            printing_instructions="Old instructions",
            printing_attachments=[{"file_url": "/storage/sales-order-files/old.pdf"}],
        )
        db.add(order)
        db.commit()
        return order.id, standard_model.id, usluga_model.id, sales_order.id


def _stored(order_id):
    with TestSessionLocal() as db:
        row = db.get(ProductionOrder, order_id)
        return {
            "production_no": row.production_no,
            "production_type": row.production_type,
            "source_type": row.source_type,
            "service_customer_name": row.service_customer_name,
            "created_by": row.created_by,
            "model_id": row.model_id,
            "sales_order_id": row.sales_order_id,
            "planned_quantity": row.planned_quantity,
        }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("production_no", "PO-HIJACKED"),
        ("production_type", "service_order"),
        ("source_type", "usluga"),
        ("service_customer_name", "Injected customer"),
        ("created_by", 1),
        ("fabric_batch_id", None),
        ("destination_warehouse_id", None),
        ("items", []),
        ("work_orders", []),
        ("materials", []),
    ],
)
def test_generic_update_rejects_internal_fields(client, auth_headers, field, value):
    order_id, *_ = _update_targets()
    before = _stored(order_id)

    response = client.patch(
        f"/api/production-orders/{order_id}",
        json={field: value},
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert _stored(order_id) == before


def test_generic_update_accepts_documented_fields_and_pydantic_coercion(client, auth_headers):
    order_id, model_id, _, sales_order_id = _update_targets()

    response = client.patch(
        f"/api/production-orders/{order_id}",
        json={
            "status": "new",
            "model_id": str(model_id),
            "sales_order_id": str(sales_order_id),
            "planned_quantity": "42",
            "deadline": "2026-10-01T12:30:00Z",
            "estimated_material_code": "FABRIC-42",
            "estimated_material_amount": "12.5",
            "estimated_material_unit": "kg",
            "printing_instructions": "Use approved artwork",
            "printing_attachments": [{
                "file_url": "/storage/sales-order-files/artwork.pdf?exp=123&sig=secret",
                "file_name": "artwork.pdf",
                "content_type": "application/pdf",
                "ignored_legacy_extra": "not persisted",
            }],
        },
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "new"
    assert body["model_id"] == model_id
    assert body["sales_order_id"] == sales_order_id
    assert body["planned_quantity"] == 42
    assert body["estimated_material_amount"] == 12.5
    assert body["printing_attachments"] == [{
        "file_url": "/storage/sales-order-files/artwork.pdf",
        "file_name": "artwork.pdf",
        "content_type": "application/pdf",
    }]


def test_generic_update_preserves_nullable_clearing(client, auth_headers):
    order_id, *_ = _update_targets()

    response = client.patch(
        f"/api/production-orders/{order_id}",
        json={
            "sales_order_id": None,
            "deadline": None,
            "estimated_material_code": None,
            "estimated_material_amount": None,
            "estimated_material_unit": None,
            "printing_instructions": None,
            "printing_attachments": None,
        },
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    for field in (
        "sales_order_id",
        "deadline",
        "estimated_material_code",
        "estimated_material_amount",
        "estimated_material_unit",
        "printing_instructions",
    ):
        assert body[field] is None
    assert body["printing_attachments"] == []


@pytest.mark.parametrize("status", [value for value in STANDARD_STATUSES if value != "new"])
def test_generic_update_rejects_workflow_status_changes_without_writes(client, auth_headers, status):
    order_id, *_ = _update_targets()
    with TestSessionLocal() as db:
        before_audits = db.query(AuditLog).count()

    response = client.patch(
        f"/api/production-orders/{order_id}",
        json={"status": status, "printing_instructions": "Must not persist"},
        headers=auth_headers,
    )

    assert response.status_code == 409, response.text
    with TestSessionLocal() as db:
        order = db.get(ProductionOrder, order_id)
        assert order.status == "new"
        assert order.printing_instructions == "Old instructions"
        assert db.query(AuditLog).count() == before_audits


def test_generic_update_accepts_unchanged_status_with_metadata(client, auth_headers):
    order_id, *_ = _update_targets()

    response = client.patch(
        f"/api/production-orders/{order_id}",
        json={"status": "new", "printing_instructions": "Updated instructions"},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "new"
    assert response.json()["printing_instructions"] == "Updated instructions"


def test_generic_update_unchanged_status_only_does_not_append_audit(client, auth_headers):
    order_id, *_ = _update_targets()
    with TestSessionLocal() as db:
        before_audits = db.query(AuditLog).count()

    response = client.patch(
        f"/api/production-orders/{order_id}",
        json={"status": "new"},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    with TestSessionLocal() as db:
        assert db.query(AuditLog).count() == before_audits


def test_generic_update_status_guard_keeps_authentication_and_missing_order_precedence(
    client, auth_headers,
):
    payload = {"status": "delivered"}
    assert client.patch("/api/production-orders/999999999", json=payload).status_code == 401
    assert client.patch(
        "/api/production-orders/999999999", json=payload, headers=auth_headers,
    ).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "invented_stage"},
        {"status": None},
        {"model_id": None},
        {"planned_quantity": None},
        {"planned_quantity": -1},
        {"estimated_material_code": "X" * 129},
        {"estimated_material_unit": "X" * 33},
        {"model_id": 2_147_483_648},
        {"sales_order_id": 2_147_483_648},
        {"planned_quantity": 2_147_483_648},
        {"estimated_material_amount": "Infinity"},
        {"estimated_material_amount": "10000000000"},
        {"estimated_material_amount": "1.00001"},
    ],
)
def test_generic_update_rejects_invalid_allowed_values(client, auth_headers, payload):
    order_id, *_ = _update_targets()
    before = _stored(order_id)

    response = client.patch(
        f"/api/production-orders/{order_id}",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert _stored(order_id) == before


@pytest.mark.parametrize("target", ["missing_model", "usluga_model", "missing_sales_order"])
def test_generic_update_validates_foreign_key_targets_atomically(client, auth_headers, target):
    order_id, _, usluga_model_id, _ = _update_targets()
    before = _stored(order_id)
    payload = {"planned_quantity": 99}
    if target == "missing_model":
        payload["model_id"] = 999999
    elif target == "usluga_model":
        payload["model_id"] = usluga_model_id
    else:
        payload["sales_order_id"] = 999999

    response = client.patch(
        f"/api/production-orders/{order_id}",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 404, response.text
    assert _stored(order_id) == before


def test_generic_update_keeps_permission_and_usluga_boundaries(client, auth_headers):
    order_id, *_ = _update_targets()
    before = _stored(order_id)
    with TestSessionLocal() as db:
        cutting = db.query(User).filter_by(email="cutting@example.com").one()
        cutting_headers = {
            "Authorization": "Bearer " + create_access_token(cutting.id, extra={"factory_code": "MIL"}),
        }

    denied = client.patch(
        f"/api/production-orders/{order_id}",
        json={"deadline": None},
        headers=cutting_headers,
    )
    assert denied.status_code == 403, denied.text
    assert _stored(order_id) == before
    with TestSessionLocal() as db:
        assert not db.query(AuditLog).filter_by(
            entity_type="ProductionOrder",
            entity_id=order_id,
            action="update",
        ).first()

    with TestSessionLocal() as db:
        db.get(ProductionOrder, order_id).source_type = "usluga"
        db.commit()
    isolated = client.patch(
        f"/api/production-orders/{order_id}",
        json={"deadline": None},
        headers=auth_headers,
    )
    assert isolated.status_code == 409, isolated.text
