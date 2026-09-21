from uuid import uuid4

import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import FinishedGoodsStock, Item, Model, ModelBOM, ProductionOrder, StockBatch, Warehouse
from app.services import packages as package_service


def _cost_model(bom_count: int) -> tuple[int, float]:
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        warehouse = db.query(Warehouse).first()
        model = Model(code=f"PERF09-M-{marker}", name=f"PERF09 model {marker}", product_type="shirt")
        db.add(model)
        db.flush()
        item_count = max(1, (bom_count + 1) // 2)
        items = [
            Item(sku=f"PERF09-I-{marker}-{index:04d}", name=f"PERF09 item {index}", category="fabric", unit="kg")
            for index in range(item_count)
        ]
        db.add_all(items)
        db.flush()
        for index, item in enumerate(items):
            db.add(StockBatch(
                item_id=item.id, batch_no=f"PERF09-OLD-{marker}-{index:04d}", quantity=1,
                unit="kg", warehouse_id=warehouse.id, cost_per_unit=99,
            ))
            db.add(StockBatch(
                item_id=item.id, batch_no=f"PERF09-NEW-{marker}-{index:04d}", quantity=1,
                unit="kg", warehouse_id=warehouse.id, cost_per_unit=index + 1,
            ))
        expected = 0.0
        for index in range(bom_count):
            item = items[index % item_count]
            quantity = 1 + (index % 3) / 10
            waste = index % 5
            db.add(ModelBOM(
                model_id=model.id, item_id=item.id, quantity_per_piece=quantity,
                unit="kg", waste_percent=waste,
            ))
            expected += quantity * ((index % item_count) + 1) * (1 + waste / 100)
        db.commit()
        return int(model.id), round(expected, 4)


def _selects(bind, callback):
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(bind, "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(bind, "before_cursor_execute", capture)
    return result, statements


@pytest.mark.parametrize("bom_count", [1, 50, 401])
def test_compute_cost_uses_latest_batch_with_bounded_reads(bom_count):
    model_id, expected = _cost_model(bom_count)
    with SessionLocal() as db:
        result, statements = _selects(db.bind, lambda: package_service._compute_cost(db, model_id))
    assert result == expected
    assert len(statements) == 2
    assert sum(" from stock_batches " in statement for statement in statements) == 1


def test_compute_cost_empty_bom_uses_one_read_and_returns_zero():
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        model = Model(code=f"PERF09-EMPTY-{marker}", name="PERF09 empty BOM", product_type="shirt")
        db.add(model)
        db.commit()
        result, statements = _selects(db.bind, lambda: package_service._compute_cost(db, model.id))
    assert result == 0.0
    assert len(statements) == 1


def test_compute_cost_latest_zero_overrides_older_nonzero_batch():
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        warehouse = db.query(Warehouse).first()
        model = Model(code=f"PERF09-ZERO-{marker}", name="PERF09 zero cost", product_type="shirt")
        item = Item(sku=f"PERF09-ZERO-I-{marker}", name="Zero-cost item", category="fabric", unit="kg")
        db.add_all([model, item])
        db.flush()
        db.add(StockBatch(
            item_id=item.id, batch_no=f"PERF09-ZERO-OLD-{marker}", quantity=1,
            unit="kg", warehouse_id=warehouse.id, cost_per_unit=17,
        ))
        db.add(StockBatch(
            item_id=item.id, batch_no=f"PERF09-ZERO-NEW-{marker}", quantity=1,
            unit="kg", warehouse_id=warehouse.id, cost_per_unit=0,
        ))
        db.add(ModelBOM(
            model_id=model.id, item_id=item.id, quantity_per_piece=3,
            unit="kg", waste_percent=25,
        ))
        db.commit()
        assert package_service._compute_cost(db, model.id) == 0.0


def test_compute_cost_preserves_missing_null_item_and_duplicate_bom_semantics():
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        model = Model(code=f"PERF09-NULL-{marker}", name="PERF09 manual BOM", product_type="shirt")
        missing = Item(sku=f"PERF09-MISSING-{marker}", name="No batches", category="fabric", unit="kg")
        db.add_all([model, missing])
        db.flush()
        db.add_all([
            ModelBOM(model_id=model.id, item_id=missing.id, quantity_per_piece=2, unit="kg", waste_percent=0),
            ModelBOM(model_id=model.id, item_id=missing.id, quantity_per_piece=3, unit="kg", waste_percent=10),
            ModelBOM(model_id=model.id, item_id=None, material_name="Manual", quantity_per_piece=7, unit="kg", waste_percent=5),
        ])
        db.commit()
        assert package_service._compute_cost(db, model.id) == 0.0


def test_create_package_persists_batched_cost(monkeypatch):
    model_id, expected = _cost_model(50)
    marker = uuid4().hex[:8]
    monkeypatch.setattr(package_service, "_enforce_packaged_quantity_available", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(package_service, "save_qr_image", lambda *_args, **_kwargs: "/test/qr.png")
    monkeypatch.setattr(package_service, "save_barcode_image", lambda *_args, **_kwargs: "/test/barcode.png")
    monkeypatch.setattr(package_service, "sync_production_order_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(package_service, "notify_department", lambda *_args, **_kwargs: None)

    with SessionLocal() as db:
        order = ProductionOrder(
            production_no=f"PERF09-PO-{marker}", production_type="branded_stock",
            model_id=model_id, status="packaging", planned_quantity=1,
        )
        db.add(order)
        db.flush()
        package = package_service.create_package(
            db, production_order_id=order.id, model_id=model_id, color="navy",
            items=[{"model_id": model_id, "color": "navy", "size": "M", "quantity": 1}],
            capacity=1, packaging_department_code="PKG",
        )
        stock = db.query(FinishedGoodsStock).filter_by(package_id=package.id).one()
        assert float(stock.cost_per_piece) == expected
