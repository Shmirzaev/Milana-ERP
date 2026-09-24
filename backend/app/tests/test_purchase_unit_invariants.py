"""Purchase quantities must use the referenced catalog item's stock unit."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    Item,
    Model,
    ModelBOM,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    SalesOrder,
    SalesOrderItem,
    User,
)
from app.services import purchasing


def _seed_item_and_actor(db):
    marker = uuid4().hex[:10]
    item = Item(
        sku=f"DB01-UNIT-{marker}",
        name=f"DB01 unit item {marker}",
        category="fabric",
        unit="kg",
        is_active=True,
    )
    actor = db.query(User).filter(User.email == "admin@example.com").one()
    db.add(item)
    db.flush()
    return item, actor, marker


def _write_state(db):
    return (
        db.query(PurchaseRequest).count(),
        db.query(PurchaseRequestLine).count(),
        db.query(PurchaseOrder).count(),
        db.query(PurchaseOrderLine).count(),
        db.query(AuditLog).count(),
    )


def test_manual_purchase_request_rejects_mismatched_unit_without_writes():
    with SessionLocal() as db:
        item, actor, _ = _seed_item_and_actor(db)
        before = _write_state(db)

        with pytest.raises(HTTPException) as error:
            purchasing.create_purchase_request(
                db,
                data={"lines": [{"item_id": item.id, "unit": "m", "requested_quantity": 2}]},
                current=actor,
            )

        assert error.value.status_code == 409
        assert error.value.detail == "Purchase request line unit must match the item unit"
        assert _write_state(db) == before


def test_sales_order_purchase_request_rejects_bom_unit_mismatch_without_writes():
    with SessionLocal() as db:
        item, actor, marker = _seed_item_and_actor(db)
        model = Model(code=f"DB01-UNIT-MODEL-{marker}", name=f"DB01 model {marker}")
        sales_order = SalesOrder(order_no=f"DB01-UNIT-SO-{marker}")
        db.add_all([model, sales_order])
        db.flush()
        db.add_all([
            ModelBOM(
                model_id=model.id,
                item_id=item.id,
                quantity_per_piece=2,
                unit="m",
            ),
            SalesOrderItem(
                sales_order_id=sales_order.id,
                model_id=model.id,
                color="Blue",
                size="M",
                quantity=1,
                unit_price=1,
            ),
        ])
        db.flush()
        before = _write_state(db)

        with pytest.raises(HTTPException) as error:
            purchasing.create_purchase_request_from_sales_order(
                db,
                sales_order_id=sales_order.id,
                current=actor,
            )

        assert error.value.status_code == 409
        assert error.value.detail == "Purchase request line unit must match the item unit"
        assert _write_state(db) == before


def test_direct_purchase_order_rejects_mismatched_unit_without_writes():
    with SessionLocal() as db:
        item, actor, _ = _seed_item_and_actor(db)
        before = _write_state(db)

        with pytest.raises(HTTPException) as error:
            purchasing.create_purchase_order(
                db,
                data={"lines": [{"item_id": item.id, "unit": "m", "ordered_quantity": 2}]},
                current=actor,
            )

        assert error.value.status_code == 409
        assert error.value.detail == "Purchase order line unit must match the item unit"
        assert _write_state(db) == before


def test_purchase_conversion_rejects_legacy_mismatched_request_without_writes():
    with SessionLocal() as db:
        item, actor, marker = _seed_item_and_actor(db)
        request = PurchaseRequest(
            request_no=f"DB01-UNIT-REQ-{marker}",
            status="approved",
            requested_by=actor.id,
        )
        db.add(request)
        db.flush()
        db.add(PurchaseRequestLine(
            purchase_request_id=request.id,
            item_id=item.id,
            unit="m",
            requested_quantity=2,
        ))
        db.flush()
        before = _write_state(db)

        with pytest.raises(HTTPException) as error:
            purchasing.convert_purchase_request_to_order(
                db,
                request_id=request.id,
                data={
                    "expected_date": datetime(2026, 10, 1, tzinfo=timezone.utc),
                    "lines": [{"purchase_request_line_id": request.lines[0].id, "ordered_quantity": 2}],
                },
                current=actor,
            )

        assert error.value.status_code == 409
        assert error.value.detail == "Purchase order line unit must match the item unit"
        assert request.status == "approved"
        assert _write_state(db) == before


def test_purchase_line_unit_validation_preserves_varchar_precedence():
    with SessionLocal() as db:
        item, actor, _ = _seed_item_and_actor(db)

        with pytest.raises(HTTPException) as error:
            purchasing.create_purchase_order(
                db,
                data={
                    "lines": [{
                        "item_id": item.id,
                        "unit": "m" * 33,
                        "ordered_quantity": 2,
                    }],
                },
                current=actor,
            )

        assert error.value.status_code == 422
        assert error.value.detail == "lines[0].unit must be at most 32 characters"


def test_purchase_request_strips_whitespace_and_defaults_to_catalog_unit():
    with SessionLocal() as db:
        item, actor, _ = _seed_item_and_actor(db)

        request = purchasing.create_purchase_request(
            db,
            data={
                "lines": [
                    {"item_id": item.id, "unit": " kg ", "requested_quantity": 1},
                    {"item_id": item.id, "unit": "", "requested_quantity": 1},
                ],
            },
            current=actor,
        )

        assert [line.unit for line in request.lines] == ["kg", "kg"]


def test_purchase_order_strips_whitespace_and_defaults_to_catalog_unit():
    with SessionLocal() as db:
        item, actor, _ = _seed_item_and_actor(db)

        order = purchasing.create_purchase_order(
            db,
            data={
                "lines": [
                    {"item_id": item.id, "unit": " kg ", "ordered_quantity": 1},
                    {"item_id": item.id, "unit": "", "ordered_quantity": 1},
                ],
            },
            current=actor,
        )

        assert [line.unit for line in order.lines] == ["kg", "kg"]
