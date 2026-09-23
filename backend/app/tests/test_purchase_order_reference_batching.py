from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.models import Item, PurchaseOrderLine, Supplier, User, Warehouse
from app.services import purchasing
from app.tests.conftest import TestSessionLocal


def _purchase_order_lines(line_count: int) -> list[dict]:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        items = [
            Item(sku=f"PERF28-ORDER-I-{marker}-{index}", name=f"Item {index}", category="accessory", unit="pcs")
            for index in range(line_count)
        ]
        warehouses = [Warehouse(name=f"PERF28-ORDER-W-{marker}-{index}", type="accessory_storage") for index in range(line_count)]
        suppliers = [Supplier(name=f"PERF28-ORDER-S-{marker}-{index}") for index in range(line_count)]
        db.add_all([*items, *warehouses, *suppliers])
        db.flush()
        lines = [
            {
                "item_id": int(item.id),
                "ordered_quantity": index + 1,
                "unit": "pcs",
                "unit_cost": index + 0.25,
                "warehouse_id": int(warehouse.id),
                "supplier_id": int(supplier.id),
            }
            for index, (item, warehouse, supplier) in enumerate(zip(items, warehouses, suppliers))
        ]
        db.commit()
        return lines


@pytest.mark.parametrize("line_count, expected_reference_selects", [(1, 3), (50, 3), (401, 6)])
def test_purchase_order_creation_batches_line_references_and_preserves_rows(
    monkeypatch,
    line_count,
    expected_reference_selects,
):
    lines = _purchase_order_lines(line_count)
    monkeypatch.setattr(purchasing, "notify_department", lambda *_args, **_kwargs: None)
    with TestSessionLocal() as db:
        current = db.query(User).order_by(User.id).first()
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and any(
                f" from {table} " in normalized for table in ("items", "warehouses", "suppliers")
            ):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            order = purchasing.create_purchase_order(
                db,
                data={"status": "draft", "lines": lines},
                current=current,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        persisted_lines = (
            db.query(PurchaseOrderLine)
            .filter(PurchaseOrderLine.purchase_order_id == order.id)
            .order_by(PurchaseOrderLine.id)
            .all()
        )

    assert len(statements) == expected_reference_selects
    assert [int(row.item_id) for row in persisted_lines] == [line["item_id"] for line in lines]
    assert [int(row.warehouse_id) for row in persisted_lines] == [line["warehouse_id"] for line in lines]
    assert [int(row.supplier_id) for row in persisted_lines] == [line["supplier_id"] for line in lines]
    assert [float(row.ordered_quantity) for row in persisted_lines] == [float(line["ordered_quantity"]) for line in lines]


def test_purchase_order_reference_batching_preserves_line_validation_precedence(monkeypatch):
    monkeypatch.setattr(purchasing, "notify_department", lambda *_args, **_kwargs: None)
    with TestSessionLocal() as db:
        item = Item(sku=f"PERF28-ORDER-INVALID-{uuid4().hex[:8]}", name="Item", category="accessory", unit="pcs")
        db.add(item)
        db.flush()
        current = db.query(User).order_by(User.id).first()

        with pytest.raises(HTTPException, match="Ordered quantity must be greater than zero"):
            purchasing.create_purchase_order(
                db,
                data={
                    "status": "draft",
                    "lines": [{
                        "item_id": int(item.id),
                        "ordered_quantity": 0,
                        "warehouse_id": 2_000_000_001,
                        "supplier_id": 2_000_000_002,
                    }],
                },
                current=current,
            )
