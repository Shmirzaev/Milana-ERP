"""Bound purchasing write payloads before they fan out into line rows."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    IdempotencyRecord,
    Item,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    StockBatch,
    StockMovement,
)
from app.schemas.purchasing import (
    PurchaseOrderIn,
    PurchaseOrderReceiveIn,
    PurchaseRequestApprovalIn,
    PurchaseRequestIn,
    PurchaseRequestOrderIn,
)


MAX_LINES = 1000


@pytest.mark.parametrize(
    "model,line",
    [
        (PurchaseRequestIn, {"item_id": 1}),
        (PurchaseOrderIn, {"item_id": 1, "ordered_quantity": 1}),
        (
            PurchaseOrderReceiveIn,
            {"purchase_order_line_id": 1, "received_quantity": 1, "batch_no": "BOUNDARY"},
        ),
        (
            PurchaseRequestApprovalIn,
            {
                "purchase_request_line_id": 1,
                "material_name": "Material",
                "preferred_supplier_id": 1,
                "photo_url": "/purchase.png",
            },
        ),
        (
            PurchaseRequestOrderIn,
            {"purchase_request_line_id": 1, "ordered_quantity": 1},
        ),
    ],
)
def test_purchasing_write_list_accepts_1000_and_rejects_1001(model, line):
    payload = {"lines": [line] * MAX_LINES}
    if model is PurchaseRequestOrderIn:
        payload["expected_date"] = "2027-01-15T00:00:00Z"
    assert len(model.model_validate(payload).lines) == MAX_LINES

    payload["lines"] = []
    assert model.model_validate(payload).lines == []

    payload["lines"] = [line] * (MAX_LINES + 1)
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def _receipt_order():
    with SessionLocal() as db:
        item_id = db.query(Item.id).order_by(Item.id).first()[0]
        order = PurchaseOrder(po_no=f"FN07-LIST-{uuid4().hex[:12]}", status="sent")
        db.add(order)
        db.flush()
        line = PurchaseOrderLine(
            purchase_order_id=order.id,
            item_id=item_id,
            ordered_quantity=10,
            received_quantity=0,
            unit="pcs",
        )
        db.add(line)
        db.commit()
        return int(order.id), int(line.id), int(item_id)


def _write_counts():
    with SessionLocal() as db:
        return (
            db.query(PurchaseRequest).count(),
            db.query(PurchaseRequestLine).count(),
            db.query(PurchaseOrder).count(),
            db.query(PurchaseOrderLine).count(),
            db.query(StockBatch).count(),
            db.query(StockMovement).count(),
            db.query(AuditLog).count(),
            db.query(IdempotencyRecord).count(),
        )


def test_1001_line_request_order_and_receipt_reject_without_writes_or_auth_bypass(
    client, auth_headers
):
    order_id, order_line_id, item_id = _receipt_order()
    before = _write_counts()
    oversized = MAX_LINES + 1
    endpoints = [
        (
            "/api/purchasing/requests",
            {"status": "draft", "lines": [{"item_id": item_id}] * oversized},
        ),
        (
            "/api/purchasing/orders",
            {
                "status": "draft",
                "lines": [{"item_id": item_id, "ordered_quantity": 1}] * oversized,
            },
        ),
        (
            f"/api/purchasing/orders/{order_id}/receive",
            {
                "lines": [
                    {
                        "purchase_order_line_id": order_line_id,
                        "received_quantity": 1,
                        "batch_no": "FN07-LIST-BOUNDARY",
                    }
                ]
                * oversized
            },
        ),
    ]

    for path, payload in endpoints:
        rejected = client.post(path, json=payload, headers=auth_headers)
        assert rejected.status_code == 422, (path, rejected.text)
        assert _write_counts() == before

        unauthenticated = client.post(path, json=payload)
        assert unauthenticated.status_code == 401, (path, unauthenticated.text)
        assert _write_counts() == before
