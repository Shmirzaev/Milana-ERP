from uuid import uuid4

from sqlalchemy import event

from app.api.routes import inbox
from app.models import Item, Model, ModelBOM, ModelImage, ProductionOrder, StockBatch, Warehouse
from app.tests.conftest import TestSessionLocal


def _production_context_case(count: int):
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        models = [
            Model(
                code=f"PERF32-{suffix}-{number:04d}",
                name=f"Inbox model {number}",
                status="approved",
            )
            for number in range(count)
        ]
        db.add_all(models)
        db.flush()
        orders = [
            ProductionOrder(
                production_no=f"PERF32-PO-{suffix}-{number:04d}",
                production_type="client_order",
                model_id=model.id,
                planned_quantity=1,
            )
            for number, model in enumerate(models)
        ]
        db.add_all(orders)
        db.flush()
        db.add_all([
            ModelImage(
                model_id=model.id,
                file_url=f"/storage/model-files/perf32-{suffix}-{number}.webp",
                file_name=f"perf32-{suffix}-{number}.webp",
                content_type="image/webp",
                file_data=b"large-binary-must-not-be-selected",
                image_type="model",
                is_primary=True,
            )
            for number, model in enumerate(models)
        ])
        db.commit()
        return [int(order.id) for order in orders]


def test_production_context_model_assets_have_bounded_queries_without_blobs():
    cases = [_production_context_case(count) for count in (1, 50, 401, 501)]
    results = []
    for order_ids in cases:
        with TestSessionLocal() as db:
            statements: list[str] = []

            def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
                if statement.lstrip().upper().startswith("SELECT"):
                    statements.append(statement)

            event.listen(db.bind, "before_cursor_execute", capture)
            try:
                payload = inbox._production_context_by_production_order(db, order_ids)
            finally:
                event.remove(db.bind, "before_cursor_execute", capture)
            results.append((payload, statements))

    assert [len(statements) for _payload, statements in results] == [6, 6, 6, 8]
    for order_ids, (payload, statements) in zip(cases, results, strict=True):
        assert set(payload) == set(order_ids)
        assert all(row["model_image_url"].endswith(".webp") for row in payload.values())
        assert "file_data" not in "\n".join(statements).lower()


def test_production_context_preserves_model_image_fallback_precedence():
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        models = [
            Model(code=f"PERF32-NONE-{suffix}", name="No image", status="approved"),
            Model(code=f"PERF32-MODEL-{suffix}", name="Model image", status="approved"),
            Model(code=f"PERF32-MATERIAL-{suffix}", name="Material image", status="approved"),
            Model(code=f"PERF32-BOM-{suffix}", name="BOM image", status="approved"),
            Model(code=f"PERF32-BATCH-{suffix}", name="Batch image", status="approved"),
            Model(code=f"PERF32-ITEM-{suffix}", name="Item image", status="approved"),
        ]
        fabric = Item(
            sku=f"PERF32-FABRIC-{suffix}",
            name="Inbox fallback fabric",
            category="fabric",
            unit="m",
            image_url=f"/storage/model-files/item-{suffix}.webp",
        )
        db.add_all([*models, fabric])
        db.flush()
        warehouse_id = db.query(Warehouse.id).order_by(Warehouse.id).first()[0]
        stock_batch = StockBatch(
            item_id=fabric.id,
            batch_no=f"PERF32-BATCH-{suffix}",
            quantity=1,
            unit="m",
            cost_per_unit=1,
            warehouse_id=warehouse_id,
            qc_status="passed",
            image_url=f"/storage/model-files/batch-{suffix}.webp",
        )
        db.add(stock_batch)
        db.flush()
        orders = [
            ProductionOrder(
                production_no=f"PERF32-FALLBACK-{suffix}-{number}",
                production_type="client_order",
                model_id=model.id,
                planned_quantity=1,
            )
            for number, model in enumerate(models)
        ]
        db.add_all(orders)
        db.add_all([
            ModelImage(
                model_id=models[1].id,
                file_url=f"/storage/model-files/model-{suffix}.webp",
                image_type="model",
                is_primary=True,
            ),
            ModelImage(
                model_id=models[1].id,
                file_url=f"/storage/model-files/material-shadowed-{suffix}.webp",
                image_type="material",
                is_primary=False,
            ),
            ModelImage(
                model_id=models[2].id,
                file_url=f"/storage/model-files/material-{suffix}.webp",
                image_type="material",
                is_primary=False,
            ),
            ModelBOM(
                model_id=models[3].id,
                material_name="Fallback fabric",
                photo_url=f"/storage/model-files/bom-{suffix}.webp",
                quantity_per_piece=1,
                unit="m",
            ),
            ModelBOM(
                model_id=models[4].id,
                item_id=fabric.id,
                stock_batch_id=stock_batch.id,
                material_name="Batch fallback fabric",
                quantity_per_piece=1,
                unit="m",
            ),
            ModelBOM(
                model_id=models[5].id,
                item_id=fabric.id,
                material_name="Item fallback fabric",
                quantity_per_piece=1,
                unit="m",
            ),
        ])
        db.commit()
        order_ids = [int(order.id) for order in orders]

    with TestSessionLocal() as db:
        payload = inbox._production_context_by_production_order(db, order_ids)

    assert [payload[order_id]["model_image_url"] for order_id in order_ids] == [
        None,
        f"/storage/model-files/model-{suffix}.webp",
        f"/storage/model-files/material-{suffix}.webp",
        f"/storage/model-files/bom-{suffix}.webp",
        f"/storage/model-files/batch-{suffix}.webp",
        f"/storage/model-files/item-{suffix}.webp",
    ]
