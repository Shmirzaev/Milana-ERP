"""Validate purchase-receipt QC commands before stock is committed."""

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


VALID_QC_STATUSES = ("pending", "passed", "failed", "rejected", "hold")


def _order(line_count: int = 1) -> tuple[int, list[int], int]:
    suffix = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        item = db.query(Item).filter(
            Item.category == "fabric", Item.is_active.is_(True),
        ).order_by(Item.id).first()
        warehouse_id = db.query(Warehouse.id).filter(
            Warehouse.type == "fabric_storage",
        ).order_by(Warehouse.id).first()[0]
        order = PurchaseOrder(po_no=f"PUR-DB02-{suffix}", status="sent")
        db.add(order)
        db.flush()
        lines = [
            PurchaseOrderLine(
                purchase_order_id=order.id,
                item_id=item.id,
                ordered_quantity=10,
                received_quantity=0,
                unit=item.unit,
                unit_cost=1,
                warehouse_id=warehouse_id,
            )
            for _ in range(line_count)
        ]
        db.add_all(lines)
        db.commit()
        return int(order.id), [int(line.id) for line in lines], int(warehouse_id)


def _line(line_id: int, warehouse_id: int, qc_status: str, suffix: str) -> dict:
    return {
        "purchase_order_line_id": line_id,
        "received_quantity": 1,
        "batch_no": f"DB02-PUR-QC-{suffix}",
        "warehouse_id": warehouse_id,
        "qc_status": qc_status,
    }


def _snapshot(order_id: int, line_ids: list[int]) -> tuple:
    with SessionLocal() as db:
        order = db.get(PurchaseOrder, order_id)
        return (
            order.status,
            tuple(float(db.get(PurchaseOrderLine, line_id).received_quantity) for line_id in line_ids),
            db.query(StockBatch).count(),
            db.query(StockMovement).count(),
            db.query(AuditLog).count(),
            db.query(IdempotencyRecord).count(),
        )


@pytest.mark.parametrize("qc_status", VALID_QC_STATUSES)
def test_purchase_receipt_preserves_every_supported_qc_status(client, auth_headers, qc_status):
    order_id, line_ids, warehouse_id = _order()
    batch_no = f"VALID-{qc_status}-{uuid4().hex}"

    response = client.post(
        f"/api/purchasing/orders/{order_id}/receive",
        headers=auth_headers,
        json={"lines": [_line(line_ids[0], warehouse_id, qc_status, batch_no)]},
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        batch = db.query(StockBatch).filter(StockBatch.batch_no == f"DB02-PUR-QC-{batch_no}").one()
        assert batch.qc_status == qc_status


def test_purchase_receipt_invalid_later_line_rolls_back_every_write(client, auth_headers):
    order_id, line_ids, warehouse_id = _order(line_count=2)
    before = _snapshot(order_id, line_ids)

    response = client.post(
        f"/api/purchasing/orders/{order_id}/receive",
        headers=auth_headers,
        json={"lines": [
            _line(line_ids[0], warehouse_id, "passed", uuid4().hex),
            _line(line_ids[1], warehouse_id, "released", uuid4().hex),
        ]},
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Invalid QC status"}
    assert _snapshot(order_id, line_ids) == before


def test_purchase_receipt_qc_validation_preserves_authentication(client):
    order_id, line_ids, warehouse_id = _order()
    before = _snapshot(order_id, line_ids)

    response = client.post(
        f"/api/purchasing/orders/{order_id}/receive",
        json={"lines": [_line(line_ids[0], warehouse_id, "released", uuid4().hex)]},
    )

    assert response.status_code == 401
    assert _snapshot(order_id, line_ids) == before


def test_purchase_receipt_qc_validation_preserves_missing_warehouse_precedence(client, auth_headers):
    order_id, line_ids, _ = _order()
    before = _snapshot(order_id, line_ids)

    response = client.post(
        f"/api/purchasing/orders/{order_id}/receive",
        headers=auth_headers,
        json={"lines": [_line(line_ids[0], 2_147_483_647, "released", uuid4().hex)]},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Warehouse 2147483647 not found"}
    assert _snapshot(order_id, line_ids) == before


def test_purchase_receipt_qc_validation_preserves_missing_order_precedence(client, auth_headers):
    response = client.post(
        "/api/purchasing/orders/2147483647/receive",
        headers=auth_headers,
        json={"lines": [_line(2_147_483_647, 2_147_483_647, "released", uuid4().hex)]},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Purchase order not found"}
