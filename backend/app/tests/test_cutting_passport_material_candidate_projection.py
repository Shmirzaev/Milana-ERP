from uuid import uuid4

from sqlalchemy import event

from app.api.routes.cutting_passports import material_defaults
from app.db.session import SessionLocal
from app.models import (
    Department,
    Item,
    Model,
    ModelBOM,
    ProductionOrder,
    StockBatch,
    User,
    Warehouse,
    WorkOrder,
)


def test_material_defaults_projects_candidate_batch_and_item_fields():
    marker = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        item = Item(
            sku=f"PASSPORT-PROJECTION-{marker}",
            name="Projected fabric",
            category="fabric",
            unit="kg",
            default_cost=4,
            composition_json=[{"name": "Cotton", "percentage": 100}],
        )
        model = Model(
            code=f"PASSPORT-MODEL-{marker}",
            name="Passport projection model",
            status="approved",
        )
        db.add_all([item, model])
        db.flush()
        order = ProductionOrder(
            production_no=f"PASSPORT-ORDER-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=12,
            status="planning",
        )
        db.add(order)
        db.flush()
        department_id = db.query(Department.id).filter(Department.code == "CUT").scalar()
        db.add(WorkOrder(
            production_order_id=order.id,
            operation="cutting",
            department_id=department_id,
            status="ready",
        ))
        warehouse_id = db.query(Warehouse.id).order_by(Warehouse.id).first()[0]
        batch = StockBatch(
            item_id=item.id,
            batch_no=f"PASSPORT-BATCH-{marker}",
            order_no="PO-PASSPORT",
            gsm=160,
            width=1.5,
            old_code="MOLD-7",
            quantity=10,
            unit="kg",
            cost_per_unit=4,
            warehouse_id=warehouse_id,
            qc_status="passed",
        )
        db.add(batch)
        db.add(ModelBOM(
            model_id=model.id,
            item_id=item.id,
            quantity_per_piece=0.5,
            unit="kg",
        ))
        db.flush()
        order_id = int(order.id)
        expected_batch_id = int(batch.id)
        current = db.query(User).filter(User.email == "admin@example.com").one()
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from stock_batches " in normalized:
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = material_defaults(order_id, db, current)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert payload["batch_id"] == expected_batch_id
    assert payload["batch_no"] == f"PASSPORT-BATCH-{marker}"
    assert payload["material_item_name"] == "Projected fabric"
    candidate_reads = [
        statement for statement in statements if "order by stock_batches.id desc" in statement
    ]
    assert len(candidate_reads) == 1
    selected = candidate_reads[0].split(" from stock_batches", 1)[0]
    for column in ("id", "item_id", "batch_no", "order_no", "gsm", "width", "old_code"):
        assert f"stock_batches.{column}" in selected
    assert "stock_batches.roll_weights_kg" not in selected
    assert "stock_batches.processes" not in selected
    assert "items.name" in selected
    assert "items.sku" in selected
    assert "items.composition_json" not in selected
