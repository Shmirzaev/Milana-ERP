"""DB01: purchase receipts follow the stock-batch warehouse contract."""

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    IdempotencyRecord,
    Item,
    PurchaseOrder,
    PurchaseOrderLine,
    StockBatch,
    StockMovement,
    Warehouse,
)
from app.services.stock_batch_policy import validate_stock_batch_warehouse


@pytest.mark.parametrize(
    ("category", "warehouse_type"),
    [
        ("fabric", "fabric_storage"),
        ("semi_finished", "fabric_storage"),
        ("accessory", "accessory_storage"),
        ("packaging", "accessory_storage"),
        ("waste", "waste"),
    ],
)
def test_shared_stock_batch_warehouse_contract_accepts_matching_categories(
    category, warehouse_type,
):
    item = Item(name="Contract item", category=category)
    warehouse = Warehouse(name="Contract warehouse", type=warehouse_type)

    validate_stock_batch_warehouse(item, warehouse)


@pytest.mark.parametrize(
    ("category", "warehouse_type", "expected_name"),
    [
        ("fabric", "accessory_storage", "Fabric Storage"),
        ("semi_finished", "accessory_storage", "Fabric Storage"),
        ("accessory", "fabric_storage", "Accessory Storage"),
        ("packaging", "packaging", "Accessory Storage"),
    ],
)
def test_shared_stock_batch_warehouse_contract_rejects_crossed_categories(
    category, warehouse_type, expected_name,
):
    item = Item(name="Contract item", category=category)
    warehouse = Warehouse(name="Contract warehouse", type=warehouse_type)

    with pytest.raises(HTTPException) as error:
        validate_stock_batch_warehouse(item, warehouse)

    assert error.value.status_code == 400
    assert error.value.detail == f"Contract item must be received into {expected_name}"


def _seed_purchase_receipt() -> dict[str, int | str]:
    marker = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        item = Item(
            sku=f"DB01-FAB-{marker}",
            name=f"DB01 fabric {marker}",
            category="fabric",
            unit="kg",
            default_cost=1,
            reorder_level=0,
            track_batch=True,
            is_active=True,
        )
        fabric_storage = Warehouse(
            name=f"DB01 fabric storage {marker}", type="fabric_storage",
        )
        accessory_storage = Warehouse(
            name=f"DB01 accessory storage {marker}", type="accessory_storage",
        )
        order = PurchaseOrder(po_no=f"PUR-DB01-{marker}", status="sent")
        db.add_all([item, fabric_storage, accessory_storage, order])
        db.flush()
        line = PurchaseOrderLine(
            purchase_order_id=order.id,
            item_id=item.id,
            ordered_quantity=Decimal("5"),
            received_quantity=Decimal("0"),
            unit="kg",
            unit_cost=1,
            warehouse_id=accessory_storage.id,
        )
        db.add(line)
        db.commit()
        return {
            "order_id": int(order.id),
            "line_id": int(line.id),
            "fabric_warehouse_id": int(fabric_storage.id),
            "accessory_warehouse_id": int(accessory_storage.id),
            "batch_no": f"DB01-BATCH-{marker}",
            "item_name": item.name,
        }


def _payload(case: dict[str, int | str], warehouse_id: int, **line_overrides) -> dict:
    return {
        "lines": [
            {
                "purchase_order_line_id": case["line_id"],
                "received_quantity": 2,
                "batch_no": case["batch_no"],
                "warehouse_id": warehouse_id,
                **line_overrides,
            }
        ]
    }


def _state(case: dict[str, int | str]) -> tuple:
    with SessionLocal() as db:
        order = db.get(PurchaseOrder, int(case["order_id"]))
        line = db.get(PurchaseOrderLine, int(case["line_id"]))
        return (
            order.status,
            line.received_quantity,
            db.query(StockBatch).filter_by(batch_no=case["batch_no"]).count(),
            db.query(StockMovement).filter(
                StockMovement.reference_type == "PurchaseOrderLine",
                StockMovement.reference_id == case["line_id"],
            ).count(),
            db.query(AuditLog).count(),
            db.query(IdempotencyRecord).count(),
        )


def test_purchase_receipt_rejects_crossed_storage_without_writes(client, auth_headers):
    case = _seed_purchase_receipt()
    before = _state(case)

    response = client.post(
        f"/api/purchasing/orders/{case['order_id']}/receive",
        headers=auth_headers,
        json=_payload(case, int(case["accessory_warehouse_id"])),
    )

    assert response.status_code == 400, response.text
    assert response.json() == {
        "detail": f"{case['item_name']} must be received into Fabric Storage",
    }
    assert _state(case) == before


def test_purchase_receipt_warehouse_contract_preserves_auth_and_reference_precedence(
    client, auth_headers,
):
    case = _seed_purchase_receipt()
    crossed_payload = _payload(case, int(case["accessory_warehouse_id"]))
    before = _state(case)

    unauthenticated = client.post(
        f"/api/purchasing/orders/{case['order_id']}/receive",
        json=crossed_payload,
    )
    missing_warehouse = client.post(
        f"/api/purchasing/orders/{case['order_id']}/receive",
        headers=auth_headers,
        json=_payload(case, 2_147_483_647),
    )
    missing_supplier = client.post(
        f"/api/purchasing/orders/{case['order_id']}/receive",
        headers=auth_headers,
        json={
            "supplier_id": 2_147_483_647,
            **crossed_payload,
        },
    )

    assert unauthenticated.status_code == 401, unauthenticated.text
    assert missing_warehouse.status_code == 404, missing_warehouse.text
    assert missing_warehouse.json() == {"detail": "Warehouse 2147483647 not found"}
    assert missing_supplier.status_code == 404, missing_supplier.text
    assert missing_supplier.json() == {"detail": "Supplier 2147483647 not found"}
    assert _state(case) == before


def test_purchase_receipt_accepts_matching_storage_and_keeps_batch_movement_parity(
    client, auth_headers,
):
    case = _seed_purchase_receipt()

    response = client.post(
        f"/api/purchasing/orders/{case['order_id']}/receive",
        headers=auth_headers,
        json=_payload(case, int(case["fabric_warehouse_id"])),
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        batch = db.query(StockBatch).filter_by(batch_no=case["batch_no"]).one()
        movement = db.query(StockMovement).filter_by(
            reference_type="PurchaseOrderLine",
            reference_id=case["line_id"],
        ).one()
        assert batch.item_id == movement.item_id
        assert batch.warehouse_id == movement.to_warehouse_id == case["fabric_warehouse_id"]
        assert batch.quantity == movement.quantity == Decimal("2")
        assert movement.batch_id == batch.id
