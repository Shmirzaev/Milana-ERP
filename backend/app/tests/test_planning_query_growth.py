from uuid import uuid4

from sqlalchemy import event, text

from app.db.session import SessionLocal
from app.models import (
    Item,
    MaterialReservation,
    Model,
    ModelBOM,
    ProductionOrder,
    SalesOrder,
    SalesOrderItem,
    StockBatch,
    StockMovement,
    Warehouse,
)
from app.services.inventory import available_stock_for_item, available_stock_for_items
from app.services.planning import (
    material_requirements_for_quantity,
    material_requirements_for_sales_order,
    planning_estimate_for_sales_order,
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


def _sales_order(db, line_count):
    suffix = uuid4().hex[:8]
    order = SalesOrder(order_no=f"SO-PERF15-{suffix}", status="draft", total_amount=0)
    db.add(order)
    db.flush()
    expected_ids = []
    for number in range(line_count):
        item = Item(
            sku=f"PERF15-I-{suffix}-{number}", name=f"Material {number}",
            category="fabric", unit="kg", default_cost=2,
            composition_json=[{"name": "Cotton", "percentage": 100}],
        )
        model = Model(
            code=f"PERF15-M-{suffix}-{number}", name=f"Model {number}",
            status="approved", sam_minutes=2.5,
        )
        db.add_all([item, model])
        db.flush()
        db.add_all([
            SalesOrderItem(
                sales_order_id=order.id, model_id=model.id, color="navy", size="M",
                quantity=2, unit_price=1,
            ),
            ModelBOM(
                model_id=model.id, item_id=item.id, color="navy", size="M",
                quantity_per_piece=1.5, unit="kg", waste_percent=0,
            ),
        ])
        expected_ids.append(item.id)
    db.commit()
    return order.id, expected_ids


def test_material_requirements_queries_are_flat_and_order_is_preserved():
    with SessionLocal() as db:
        one_id, one_items = _sales_order(db, 1)
        many_id, many_items = _sales_order(db, 50)
    with SessionLocal() as db:
        one, one_count = _select_count(db, lambda: material_requirements_for_sales_order(db, one_id))
    with SessionLocal() as db:
        many, many_count = _select_count(db, lambda: material_requirements_for_sales_order(db, many_id))

    assert (one_count, many_count) == (6, 6)
    assert [row["item_id"] for row in one] == one_items
    assert [row["item_id"] for row in many] == many_items
    assert all(row["required_quantity"] == 3.0 and row["shortage"] == 3.0 for row in many)
    assert all(row["composition"] == [{"name": "Cotton", "percentage": 100.0}] for row in many)


def test_planning_estimate_batches_cold_session_item_and_model_enrichment():
    with SessionLocal() as db:
        one_id, one_items = _sales_order(db, 1)
        fifty_id, fifty_items = _sales_order(db, 50)
        chunked_id, chunked_items = _sales_order(db, 401)

    results = []
    for order_id in (one_id, fifty_id, chunked_id):
        with SessionLocal() as db:
            results.append(_select_count(db, lambda order_id=order_id: planning_estimate_for_sales_order(db, order_id)))

    (one, one_count), (fifty, fifty_count), (chunked, chunked_count) = results
    assert (one_count, fifty_count, chunked_count) == (9, 9, 15)
    for estimate, expected_ids in ((one, one_items), (fifty, fifty_items), (chunked, chunked_items)):
        assert estimate is not None
        assert [row["item_id"] for row in estimate["materials"]] == expected_ids
        assert estimate["estimated_material_cost"] == 6 * len(expected_ids)
        assert estimate["estimated_lead_time_minutes"] == 5 * len(expected_ids)
        assert estimate["total_quantity"] == 2 * len(expected_ids)


def test_bulk_availability_chunks_and_matches_signed_scalar_semantics():
    with SessionLocal() as db:
        suffix = uuid4().hex[:8]
        items = [Item(sku=f"PERF15-C-{suffix}-{number}", name="Chunk", category="fabric", unit="kg")
                 for number in range(401)]
        db.add_all(items)
        db.flush()
        ids = [item.id for item in items]
        warehouse_id = db.query(Warehouse.id).order_by(Warehouse.id).first()[0]
        db.execute(text("PRAGMA ignore_check_constraints = ON"))
        db.add(StockBatch(
            item_id=ids[0], batch_no=f"PERF15-NEG-{suffix}", quantity=-5,
            unit="kg", cost_per_unit=0, warehouse_id=warehouse_id, qc_status="passed",
        ))
        db.commit()
        db.execute(text("PRAGMA ignore_check_constraints = OFF"))

        one, one_count = _select_count(db, lambda: available_stock_for_items(db, ids[:1]))
        many, many_count = _select_count(db, lambda: available_stock_for_items(db, ids))
        assert (one_count, many_count) == (3, 6)
        assert one[ids[0]] == available_stock_for_item(db, ids[0]) == -5.0
        assert many[ids[0]] == -5.0
        assert all(many[item_id] == 0 for item_id in ids[1:])
        assert available_stock_for_items(db, [None, ids[0], ids[0], 999_999_999]) == {
            None: 0.0, ids[0]: -5.0, 999_999_999: 0.0,
        }


def test_bulk_requirements_match_legacy_stock_and_bom_semantics():
    with SessionLocal() as db:
        suffix = uuid4().hex[:8]
        warehouse_id = db.query(Warehouse.id).order_by(Warehouse.id).first()[0]
        items = [
            Item(sku=f"PERF15-S-{suffix}-{name}", name=name, category="fabric", unit="kg")
            for name in ("shared", "size", "color", "exact", "mismatch")
        ]
        model = Model(code=f"PERF15-SEM-{suffix}", name="Semantic model", status="approved")
        empty_model = Model(code=f"PERF15-EMPTY-{suffix}", name="No BOM", status="approved")
        order = SalesOrder(order_no=f"SO-PERF15-SEM-{suffix}", status="draft", total_amount=0)
        db.add_all([*items, model, empty_model, order])
        db.flush()
        shared, sized, colored, exact, mismatch = items
        db.add_all([
            SalesOrderItem(
                sales_order_id=order.id, model_id=model.id, color="navy", size="M",
                quantity=2, unit_price=1,
            ),
            SalesOrderItem(
                sales_order_id=order.id, model_id=model.id, color="navy", size="L",
                quantity=3, unit_price=1,
            ),
            ModelBOM(model_id=model.id, item_id=shared.id, quantity_per_piece=1, unit="kg"),
            ModelBOM(model_id=model.id, item_id=sized.id, size="M", quantity_per_piece=2, unit="kg"),
            ModelBOM(model_id=model.id, item_id=colored.id, color="navy", quantity_per_piece=.5, unit="kg"),
            ModelBOM(
                model_id=model.id, item_id=exact.id, color="navy", size="M",
                quantity_per_piece=3, unit="kg",
            ),
            ModelBOM(model_id=model.id, item_id=None, quantity_per_piece=.25, unit="kg"),
            ModelBOM(model_id=model.id, item_id=mismatch.id, color="red", quantity_per_piece=100, unit="kg"),
        ])
        batch = StockBatch(
            item_id=shared.id, batch_no=f"PERF15-SHARED-{suffix}", quantity=10,
            unit="kg", cost_per_unit=0, warehouse_id=warehouse_id, qc_status="passed",
        )
        negative_reservation_batch = StockBatch(
            item_id=exact.id, batch_no=f"PERF15-NEG-RES-{suffix}", quantity=4,
            unit="kg", cost_per_unit=0, warehouse_id=warehouse_id, qc_status="passed",
        )
        db.add_all([batch, negative_reservation_batch])
        db.flush()
        db.add_all([
            StockMovement(
                movement_type="produce", item_id=shared.id, quantity=3, unit="kg",
                to_warehouse_id=warehouse_id,
            ),
            StockMovement(
                movement_type="issue", item_id=shared.id, quantity=4, unit="kg",
                from_warehouse_id=warehouse_id,
            ),
            StockMovement(
                movement_type="issue", item_id=shared.id, batch_id=batch.id,
                quantity=100, unit="kg", from_warehouse_id=warehouse_id,
            ),
            StockMovement(
                movement_type="transfer", item_id=shared.id, quantity=100, unit="kg",
                from_warehouse_id=warehouse_id, to_warehouse_id=warehouse_id,
            ),
        ])
        production_order = ProductionOrder(
            production_no=f"PERF15-PO-{suffix}", production_type="branded_stock",
            model_id=model.id, planned_quantity=1,
        )
        db.add(production_order)
        db.flush()
        db.add_all([
            MaterialReservation(
                reservation_no=f"PERF15-RES-A-{suffix}", production_order_id=production_order.id,
                item_id=shared.id, reserved_quantity=2, unit="kg", status="reserved",
            ),
            MaterialReservation(
                reservation_no=f"PERF15-RES-B-{suffix}", production_order_id=production_order.id,
                item_id=shared.id, reserved_quantity=3, consumed_quantity=1, released_quantity=1,
                unit="kg", status="partially_consumed",
            ),
            MaterialReservation(
                reservation_no=f"PERF15-RES-C-{suffix}", production_order_id=production_order.id,
                item_id=shared.id, reserved_quantity=100, unit="kg", status="cancelled",
            ),
        ])
        db.flush()
        db.execute(text("PRAGMA ignore_check_constraints = ON"))
        db.add(MaterialReservation(
            reservation_no=f"PERF15-RES-NEG-{suffix}", production_order_id=production_order.id,
            item_id=exact.id, reserved_quantity=-5, unit="kg", status="reserved",
        ))
        db.flush()
        db.execute(text("PRAGMA ignore_check_constraints = OFF"))
        db.commit()

        rows = material_requirements_for_sales_order(db, order.id)
        by_item = {row["item_id"]: row for row in rows}
        assert [row["item_id"] for row in rows] == [shared.id, sized.id, colored.id, exact.id, None]
        assert {item_id: row["required_quantity"] for item_id, row in by_item.items()} == {
            shared.id: 5.0, sized.id: 4.0, colored.id: 2.5, exact.id: 6.0, None: 1.25,
        }
        assert by_item[shared.id]["available_quantity"] == available_stock_for_item(db, shared.id) == 6.0
        assert by_item[exact.id]["available_quantity"] == available_stock_for_item(db, exact.id) == 4.0
        assert by_item[shared.id]["shortage"] == 0.0
        assert by_item[exact.id]["shortage"] == 2.0
        assert mismatch.id not in by_item

        assert material_requirements_for_quantity(db, empty_model.id, []) == []
        assert material_requirements_for_quantity(
            db, empty_model.id, [{"color": "navy", "size": "M", "quantity": 1}],
        ) == []
        assert material_requirements_for_quantity(
            db, 999_999_999, [{"color": "navy", "size": "M", "quantity": 1}],
        ) == []
        negative = material_requirements_for_quantity(
            db, model.id, [{"color": "navy", "size": "M", "quantity": -2}],
        )
        assert [row["required_quantity"] for row in negative] == [-2.0, -4.0, -1.0, -6.0, -.5]
        assert all(row["shortage"] == 0 for row in negative)


def test_material_requirements_endpoint_requires_authentication(client):
    response = client.get("/api/planning/material-requirements/1")
    assert response.status_code == 401
