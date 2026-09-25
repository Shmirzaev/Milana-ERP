from uuid import uuid4

from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import (
    Brand,
    CuttingRecord,
    Customer,
    Department,
    FinishedGoodsStock,
    Item,
    MaterialReservation,
    ModelBOM,
    Model,
    PackagingRecord,
    ProductionOrder,
    SalesOrder,
    SalesOrderItem,
    StockBatch,
    StockMovement,
    Warehouse,
    WasteRecord,
    WorkOrder,
)
from app.services.finance import _recorded_material_cost, branded_stock_value, cost_breakdown, order_profit


def test_order_profit_uses_decimal_for_fractional_revenue():
    with SessionLocal() as db:
        customer = Customer(name=f"Profit precision {uuid4().hex}")
        db.add(customer)
        db.flush()
        order = SalesOrder(
            order_no=f"PROFIT-{uuid4().hex}",
            customer_id=customer.id,
            total_amount=1.3,
        )
        db.add(order)
        db.flush()
        model = Model(code=f"PROFIT-MODEL-{uuid4().hex}", name="Profit precision model")
        db.add(model)
        db.flush()
        item = Item(
            sku=f"PROFIT-ITEM-{uuid4().hex}",
            name="Profit precision material",
            category="material",
            unit="kg",
            composition_json=[],
        )
        db.add(item)
        db.flush()
        warehouse = db.query(Warehouse).order_by(Warehouse.id.asc()).first()
        db.add_all([
            SalesOrderItem(
                sales_order_id=order.id,
                model_id=model.id,
                quantity=7,
                unit_price="0.10",
                color="black",
                size="M",
            ),
            SalesOrderItem(
                sales_order_id=order.id,
                model_id=model.id,
                quantity=3,
                unit_price="0.20",
                color="black",
                size="L",
            ),
        ])
        production = ProductionOrder(
            production_no=f"PO-PROFIT-{uuid4().hex}",
            production_type="client_order",
            sales_order_id=order.id,
            model_id=model.id,
            planned_quantity=3,
        )
        db.add(production)
        db.flush()
        db.add(ModelBOM(
            model_id=model.id,
            item_id=item.id,
            quantity_per_piece="0.10",
            unit="kg",
            waste_percent="10.00",
        ))
        db.add_all([
            StockBatch(
                item_id=item.id,
                batch_no=f"BATCH-PROFIT-OLD-{uuid4().hex}-{number}",
                quantity=10,
                unit="kg",
                cost_per_unit="9.99",
                warehouse_id=warehouse.id,
            )
            for number in range(25)
        ])
        db.flush()
        latest_batch = StockBatch(
            item_id=item.id,
            batch_no=f"BATCH-PROFIT-LATEST-{uuid4().hex}",
            quantity=10,
            unit="kg",
            cost_per_unit="0.20",
            warehouse_id=warehouse.id,
        )
        db.add(latest_batch)
        db.flush()
        db.add(StockMovement(
            movement_type="consume",
            item_id=item.id,
            batch_id=latest_batch.id,
            quantity="0.33",
            unit="kg",
            reference_type="ProductionOrder",
            reference_id=production.id,
            unit_cost_at_movement="0.20",
        ))
        db.add(WasteRecord(
            production_order_id=production.id,
            waste_type="fabric",
            quantity="0.50",
            unit="kg",
            estimated_value="0.10",
        ))
        db.commit()

        statements = []

        def capture_select(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(statement.lower())

        event.listen(db.get_bind(), "before_cursor_execute", capture_select)
        try:
            result = order_profit(db, order.id)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", capture_select)
        db.get(StockBatch, latest_batch.id).cost_per_unit = "9.2500"
        db.commit()
        repriced = order_profit(db, order.id)
        db.add(StockMovement(
            movement_type="consume", item_id=item.id, batch_id=latest_batch.id,
            quantity="0.10", unit="kg", reference_type="ProductionOrder",
            reference_id=production.id,
        ))
        db.commit()
        incomplete_history = order_profit(db, order.id)

    assert result["revenue"] == 1.3
    assert result["material_cost"] == 0.066
    assert result["waste_cost"] == 0.1
    assert result["gross_profit"] == 1.134
    assert result["material_cost_basis"] == "transaction_snapshot"
    assert repriced == result
    assert incomplete_history["material_cost"] is None
    assert incomplete_history["gross_profit"] is None
    assert incomplete_history["material_cost_basis"] == "unavailable"
    sales_query = next(sql for sql in statements if "from sales_orders" in sql)
    sales_item_query = next(sql for sql in statements if "from sales_order_items" in sql)
    production_query = next(sql for sql in statements if "from production_orders" in sql)
    assert "printing_attachments" not in sales_query
    assert "notes" not in sales_item_query
    assert "production_no" not in production_query
    assert not any("from stock_batches" in sql for sql in statements)
    assert not any("from model_bom" in sql for sql in statements)


def test_branded_stock_value_uses_decimal_intermediates():
    with SessionLocal() as db:
        model = Model(code=f"STOCK-PRECISION-{uuid4().hex}", name="Stock precision model")
        brand = Brand(name=f"Stock precision brand {uuid4().hex}")
        db.add_all([model, brand])
        db.flush()
        db.add_all([
            FinishedGoodsStock(model_id=model.id, brand_id=brand.id, color="black", size="S", quantity=3, available_qty=3, cost_per_piece="0.10", selling_price="1.00", status="available"),
            FinishedGoodsStock(model_id=model.id, brand_id=brand.id, color="black", size="M", quantity=7, available_qty=7, cost_per_piece="0.20", selling_price="1.00", status="available"),
        ])
        db.commit()
        value = branded_stock_value(db)

    assert isinstance(value, float)
    assert value == 1.7


def test_recorded_material_cost_resolves_only_linked_consumption_references():
    marker = uuid4().hex
    with SessionLocal() as db:
        model = Model(code=f"PROFIT-REF-{marker}", name="Profit reference model")
        item = Item(sku=f"PROFIT-REF-{marker}", name="Profit reference item", category="fabric", unit="kg")
        department = Department(code=f"PREF-{marker[:8]}", name=f"Profit reference {marker}")
        warehouse = Warehouse(name=f"Profit reference warehouse {marker}", type="fabric_storage")
        db.add_all([model, item, department, warehouse])
        db.flush()
        target = ProductionOrder(
            production_no=f"PO-PROFIT-REF-{marker}", production_type="client_order", model_id=model.id,
        )
        other = ProductionOrder(
            production_no=f"PO-PROFIT-OTHER-{marker}", production_type="client_order", model_id=model.id,
        )
        batch = StockBatch(
            item_id=item.id, batch_no=f"BATCH-PROFIT-REF-{marker}", quantity=20,
            unit="kg", cost_per_unit="1.00", warehouse_id=warehouse.id,
        )
        db.add_all([target, other, batch])
        db.flush()
        cutting_work = WorkOrder(
            production_order_id=target.id, department_id=department.id, operation="cutting",
        )
        packaging_work = WorkOrder(
            production_order_id=target.id, department_id=department.id, operation="packaging",
        )
        db.add_all([cutting_work, packaging_work])
        db.flush()
        cutting = CuttingRecord(work_order_id=cutting_work.id)
        packaging = PackagingRecord(work_order_id=packaging_work.id)
        reservation = MaterialReservation(
            reservation_no=f"PROFIT-RES-{marker}", production_order_id=target.id,
            item_id=item.id, stock_batch_id=batch.id, warehouse_id=warehouse.id,
            reserved_quantity=2, unit="kg",
        )
        db.add_all([cutting, packaging, reservation])
        db.flush()
        for reference_type, reference_id, quantity, cost in (
            ("ProductionOrder", target.id, 2, 1),
            ("CuttingRecord", cutting.id, 3, 2),
            ("PackagingRecord", packaging.id, 1, 4),
            ("MaterialReservation", reservation.id, 2, 5),
            ("ProductionOrder", other.id, 10, 100),
        ):
            db.add(StockMovement(
                movement_type="consume", item_id=item.id, batch_id=batch.id,
                quantity=quantity, unit="kg", reference_type=reference_type,
                reference_id=reference_id, unit_cost_at_movement=cost,
            ))
        db.add(StockMovement(
            movement_type="issue", item_id=item.id, batch_id=batch.id,
            quantity=3, unit="kg", reference_type="ProductionOrder",
            reference_id=target.id,
        ))
        db.flush()
        assert _recorded_material_cost(db, {target.id}) == 22


def test_cost_breakdown_uses_decimal_for_fractional_bom_totals():
    with SessionLocal() as db:
        model = Model(code=f"COGS-PRECISION-{uuid4().hex}", name="COGS precision model")
        fabric = Item(sku=f"COGS-F-{uuid4().hex}", name="Fabric", category="fabric", unit="kg", default_cost="1.00", composition_json=[])
        accessory = Item(sku=f"COGS-A-{uuid4().hex}", name="Accessory", category="accessory", unit="pcs", default_cost="0.10", composition_json=[])
        db.add_all([model, fabric, accessory])
        db.flush()
        db.add(ProductionOrder(production_no=f"COGS-{uuid4().hex}", production_type="client_order", model_id=model.id, planned_quantity=1))
        db.flush()
        db.add_all(
            [
                ModelBOM(model_id=model.id, item_id=fabric.id, quantity_per_piece="0.001", unit="kg", waste_percent="0.00")
                for _ in range(175)
            ]
            + [
                ModelBOM(model_id=model.id, item_id=accessory.id, quantity_per_piece="0.30", unit="pcs", waste_percent="0.00"),
            ]
        )
        db.commit()
        result = cost_breakdown(db)

    assert isinstance(result["fabric_cost"], float)
    assert isinstance(result["accessories_cost"], float)
    # Float accumulation produces 0.17500000000000013 and rounds to 0.18;
    # exact intermediates preserve the existing final float-rounding contract.
    assert result["fabric_cost"] == 0.17
    assert result["accessories_cost"] == 0.03
    assert result["total_cogs"] == 0.2


def test_cost_breakdown_projects_only_calculation_columns():
    with SessionLocal() as db:
        model = Model(code=f"COGS-PROJECTION-{uuid4().hex}", name="COGS projection model")
        fabric = Item(
            sku=f"COGS-PROJECTION-{uuid4().hex}",
            name="Projected fabric",
            category="fabric",
            unit="kg",
            default_cost="0.25",
            composition_json=[{"kind": "ignored"}],
        )
        db.add_all([model, fabric])
        db.flush()
        db.add(ProductionOrder(
            production_no=f"COGS-PROJECTION-{uuid4().hex}",
            production_type="client_order",
            model_id=model.id,
            planned_quantity=4,
        ))
        db.flush()
        db.add(ModelBOM(
            model_id=model.id,
            item_id=fabric.id,
            quantity_per_piece="0.5",
            unit="kg",
            waste_percent="10.00",
        ))
        db.commit()

        statements = []

        def capture_select(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(statement.lower())

        event.listen(db.get_bind(), "before_cursor_execute", capture_select)
        try:
            result = cost_breakdown(db)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", capture_select)

    assert result == {
        "fabric_cost": 0.55,
        "labor_cost": 0.0,
        "accessories_cost": 0.0,
        "total_cogs": 0.55,
    }
    production_query = next(sql for sql in statements if "from production_orders" in sql)
    bom_query = next(sql for sql in statements if "from model_bom" in sql)
    item_query = next(sql for sql in statements if "from items" in sql)
    assert "production_no" not in production_query
    assert "material_name" not in bom_query
    assert "join items" not in bom_query
    assert "join stock_batches" not in bom_query
    assert "image_url" not in item_query
    assert "composition_json" not in item_query


def test_cost_breakdown_ignores_unlinked_bom_notes():
    with SessionLocal() as db:
        model = Model(code=f"COGS-NOTE-{uuid4().hex}", name="COGS note model")
        db.add(model)
        db.flush()
        db.add(ProductionOrder(production_no=f"COGS-NOTE-{uuid4().hex}", production_type="client_order", model_id=model.id, planned_quantity=3))
        db.add(ModelBOM(model_id=model.id, item_id=None, material_name="Manual fabric note", quantity_per_piece="0.10", unit="kg"))
        db.commit()
        result = cost_breakdown(db)

    assert result["fabric_cost"] == 0.0
    assert result["accessories_cost"] == 0.0
