from decimal import Decimal
from uuid import uuid4

import pytest

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


MAX_PIECE_COUNT = 2_147_483_647


def _seed_order():
    marker = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        item = Item(
            sku=f"PIECE-COUNT-{marker}",
            name=f"Piece count {marker}",
            category="accessory",
            unit="pcs",
            default_cost=1,
            reorder_level=0,
            track_batch=True,
            is_active=True,
        )
        warehouse = Warehouse(name=f"Piece count {marker}", type="accessory_storage")
        order = PurchaseOrder(po_no=f"PUR-PIECE-{marker}", status="sent")
        db.add_all([item, warehouse, order])
        db.flush()
        line = PurchaseOrderLine(
            purchase_order_id=order.id,
            item_id=item.id,
            ordered_quantity=Decimal("10"),
            unit="pcs",
            unit_cost=1,
            warehouse_id=warehouse.id,
        )
        db.add(line)
        db.commit()
        return {
            "order_id": int(order.id),
            "line_id": int(line.id),
            "warehouse_id": int(warehouse.id),
            "batch_no": f"PIECE-{marker}",
        }


def _payload(order, piece_count):
    return {
        "lines": [
            {
                "purchase_order_line_id": order["line_id"],
                "received_quantity": 1,
                "batch_no": order["batch_no"],
                "warehouse_id": order["warehouse_id"],
                "piece_count": piece_count,
            }
        ]
    }


def _state(order):
    with SessionLocal() as db:
        return (
            db.get(PurchaseOrderLine, order["line_id"]).received_quantity,
            db.query(StockBatch).filter(StockBatch.batch_no == order["batch_no"]).count(),
            db.query(StockMovement).filter(
                StockMovement.reference_type == "PurchaseOrderLine",
                StockMovement.reference_id == order["line_id"],
            ).count(),
            db.query(AuditLog).count(),
            db.query(IdempotencyRecord).count(),
        )


def test_purchase_receipt_persists_stock_batch_integer_maximum(client, auth_headers):
    order = _seed_order()

    response = client.post(
        f"/api/purchasing/orders/{order['order_id']}/receive",
        json=_payload(order, MAX_PIECE_COUNT),
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        batch = db.query(StockBatch).filter_by(batch_no=order["batch_no"]).one()
        assert batch.piece_count == MAX_PIECE_COUNT


@pytest.mark.parametrize("piece_count", [-1, 2_147_483_648, -2_147_483_649])
def test_purchase_receipt_rejects_piece_count_outside_stock_batch_integer_range(
    client, auth_headers, piece_count
):
    order = _seed_order()
    before = _state(order)

    response = client.post(
        f"/api/purchasing/orders/{order['order_id']}/receive",
        json=_payload(order, piece_count),
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert _state(order) == before


def test_purchase_receipt_authentication_precedes_piece_count_range_check(client):
    order = _seed_order()
    before = _state(order)

    response = client.post(
        f"/api/purchasing/orders/{order['order_id']}/receive",
        json=_payload(order, 2_147_483_648),
    )

    assert response.status_code == 401, response.text
    assert _state(order) == before
