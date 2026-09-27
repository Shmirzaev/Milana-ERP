from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes import cutting_passports
from app.db.session import SessionLocal
from app.models import (
    Department,
    Item,
    Model,
    ProductionOrder,
    ProductionOrderItem,
    ProductionOrderMaterial,
    StockBatch,
    Warehouse,
    WorkOrder,
)


def _select_count(db, call):
    count = 0

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal count
        if statement.lstrip().upper().startswith("SELECT"):
            count += 1

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        result = call()
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return result, count


def _factory_user(factory="MIL"):
    return SimpleNamespace(
        role=SimpleNamespace(name=""), extra_permissions=["cutting.records"],
        factory_code=factory, session_factory_code=factory,
    )


def _material_order(db, material_count):
    suffix = uuid4().hex[:8]
    department = db.query(Department).filter_by(code="CUT").one()
    warehouse_id = db.query(Warehouse.id).order_by(Warehouse.id).first()[0]
    item = Item(
        sku=f"PERF14-I-{suffix}", name="Performance fabric", category="fabric",
        unit="kg", default_cost=2,
    )
    model = Model(code=f"PERF14-M-{suffix}", name="Performance model", status="approved")
    db.add_all([item, model])
    db.flush()
    order = ProductionOrder(
        production_no=f"PERF14-PO-{suffix}", production_type="branded_stock",
        model_id=model.id, status="new", planned_quantity=material_count,
    )
    db.add(order)
    db.flush()
    db.add_all([
        WorkOrder(
            production_order_id=order.id, department_id=department.id,
            operation="cutting", status="in_progress",
        ),
        WorkOrder(
            production_order_id=order.id, department_id=department.id,
            operation="printing", status="waiting",
        ),
        ProductionOrderItem(
            production_order_id=order.id, model_id=model.id, color="navy", size="M",
            planned_quantity=material_count,
        ),
        ProductionOrderItem(
            production_order_id=order.id, model_id=model.id, color="navy", size="L",
            planned_quantity=material_count,
        ),
        ProductionOrderItem(
            production_order_id=order.id, model_id=model.id, color="navy", size="M",
            planned_quantity=material_count,
        ),
    ])
    batches = [
        StockBatch(
            item_id=item.id, batch_no=f"PERF14-B-{suffix}-{number:04d}",
            order_no=f"ORDER-{number:04d}", width=1.5, gsm=.2,
            quantity=number + 1, unit="kg", cost_per_unit=2,
            warehouse_id=warehouse_id, qc_status="passed",
        )
        for number in range(material_count)
    ]
    db.add_all(batches)
    db.flush()
    materials = [
        ProductionOrderMaterial(
            production_order_id=order.id, stock_batch_id=batch.id,
            estimated_quantity=number + 1, unit="kg" if number % 2 == 0 else "m",
            position=number + 1,
        )
        for number, batch in enumerate(batches)
    ]
    db.add_all(reversed(materials))
    db.commit()
    return order.id, [batch.id for batch in batches]


def test_multi_material_defaults_queries_are_chunk_bounded_and_payload_is_stable():
    with SessionLocal() as db:
        one_id, one_batches = _material_order(db, 1)
        fifty_id, fifty_batches = _material_order(db, 50)
        chunked_id, chunked_batches = _material_order(db, 401)

    results = []
    for order_id in (one_id, fifty_id, chunked_id):
        with SessionLocal() as db:
            results.append(_select_count(
                db,
                lambda order_id=order_id: cutting_passports.material_defaults(
                    order_id, db, _factory_user(),
                ),
            ))

    (one, one_count), (fifty, fifty_count), (chunked, chunked_count) = results
    assert (one_count, fifty_count, chunked_count) == (9, 9, 10)
    for payload, batch_ids in ((one, one_batches), (fifty, fifty_batches), (chunked, chunked_batches)):
        assert [row["stock_batch_id"] for row in payload["materials"]] == batch_ids
        assert [row["planned_kg"] for row in payload["materials"][:2]] == (
            [1.0] if len(batch_ids) == 1 else [1.0, None]
        )
        assert all(row["has_print"] is True for row in payload["materials"])
        assert all(row["sizes"] == ["M", "L"] for row in payload["materials"])
        assert all(row["size_range"] == "M, L" for row in payload["materials"])
        assert all(row["size_count"] == 2 for row in payload["materials"])
        assert all(row["material_item_name"] == "Performance fabric" for row in payload["materials"])
        assert payload["stock_batch_id"] == batch_ids[0]
        assert payload["can_add_material"] is True


def test_multi_material_defaults_preserve_missing_batch_and_factory_scope():
    with SessionLocal() as db:
        order_id, batch_ids = _material_order(db, 1)
        db.add(ProductionOrderMaterial(
            production_order_id=order_id, stock_batch_id=999_999_999,
            estimated_quantity=2, unit="m", position=2,
        ))
        db.commit()

    with SessionLocal() as db:
        payload = cutting_passports.material_defaults(order_id, db, _factory_user())
        assert [row["stock_batch_id"] for row in payload["materials"]] == [batch_ids[0], 999_999_999]
        missing = payload["materials"][1]
        assert missing["planned_kg"] is None
        assert missing["batch_id"] is None
        assert missing["material_item_id"] is None
        with pytest.raises(HTTPException) as denied:
            cutting_passports.material_defaults(order_id, db, _factory_user("ECO"))
        assert denied.value.status_code == 403


def test_multi_material_defaults_preserve_distinct_items_and_false_empty_context():
    with SessionLocal() as db:
        order_id, batch_ids = _material_order(db, 2)
        suffix = uuid4().hex[:8]
        second_item = Item(
            sku=f"PERF14-DISTINCT-{suffix}", name="Distinct secondary fabric",
            category="semi_finished", unit="kg", default_cost=3,
        )
        db.add(second_item)
        db.flush()
        db.get(StockBatch, batch_ids[1]).item_id = second_item.id
        db.query(WorkOrder).filter(
            WorkOrder.production_order_id == order_id,
            WorkOrder.operation == "printing",
        ).delete(synchronize_session=False)
        db.query(ProductionOrderItem).filter(
            ProductionOrderItem.production_order_id == order_id,
        ).delete(synchronize_session=False)
        db.commit()

    with SessionLocal() as db:
        payload, count = _select_count(
            db,
            lambda: cutting_passports.material_defaults(order_id, db, _factory_user()),
        )

    assert count == 10
    assert [row["material_item_name"] for row in payload["materials"]] == [
        "Performance fabric", "Distinct secondary fabric",
    ]
    assert all(row["has_print"] is False for row in payload["materials"])
    assert all(row["sizes"] == [] for row in payload["materials"])
    assert all(row["size_range"] is None for row in payload["materials"])
    assert all(row["size_count"] == 0 for row in payload["materials"])


def test_material_defaults_requires_authentication(client):
    response = client.get("/api/cutting-passports/material-defaults?production_order_id=1")
    assert response.status_code == 401
