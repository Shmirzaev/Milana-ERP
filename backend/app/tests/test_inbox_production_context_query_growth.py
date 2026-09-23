from uuid import uuid4
from types import SimpleNamespace

from sqlalchemy import event

from app.api.routes import inbox
from app.models import Item, Model, ModelBOM, ModelImage, Package, ProductionOrder, StockBatch, Warehouse
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
        normalized_statements = [" ".join(statement.lower().split()) for statement in statements]
        model_reads = [statement for statement in normalized_statements if " from models " in statement]
        assert model_reads
        for statement in model_reads:
            selected_columns = statement.split("from models", 1)[0]
            for column in ("models.id", "models.code", "models.name", "models.details_json"):
                assert column in selected_columns
            for column in ("models.product_type", "models.selling_price", "models.status"):
                assert column not in selected_columns


def test_material_context_defers_material_image_blobs_and_preserves_url():
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(code=f"PERF32-MAT-{suffix}", name="Material model", status="approved")
        item = Item(sku=f"PERF32-ITEM-{suffix}", name="Fabric", category="fabric", unit="m")
        db.add_all([model, item])
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF32-MAT-PO-{suffix}",
            production_type="client_order",
            model_id=model.id,
            planned_quantity=1,
        )
        db.add_all([
            order,
            ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=1, unit="m"),
            ModelImage(model_id=model.id, file_url=f"/material/{suffix}.webp", file_name="material.webp", content_type="image/webp", image_type="material", file_data=b"do-not-select"),
        ])
        db.flush()
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = inbox._material_payload_by_production_order(db, [order.id])
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        assert payload[order.id]["material_image_url"] == f"/material/{suffix}.webp"
        assert "file_data" not in "\n".join(statements).lower()


def _material_reference_case(count: int):
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        warehouse_id = db.query(Warehouse.id).order_by(Warehouse.id).first()[0]
        models = [
            Model(code=f"PERF32-MAP-{suffix}-{index:04d}", name=f"Map model {index}")
            for index in range(count)
        ]
        items = [
            Item(
                sku=f"PERF32-MAP-{suffix}-{index:04d}",
                name=f"Map item {index}",
                category="fabric",
                unit="m",
                image_url=f"/item/{suffix}-{index}.webp",
                composition_json=[{"unused": "must not hydrate"}],
            )
            for index in range(count)
        ]
        db.add_all([*models, *items])
        db.flush()
        batches = [
            StockBatch(
                item_id=item.id,
                batch_no=f"PERF32-MAP-{suffix}-{index:04d}",
                quantity=1,
                unit="m",
                cost_per_unit=1,
                warehouse_id=warehouse_id,
                qc_status="passed",
                image_url=f"/batch/{suffix}-{index}.webp",
                roll_weights_kg=[999],
            )
            for index, item in enumerate(items)
        ]
        db.add_all(batches)
        db.flush()
        orders = [
            ProductionOrder(
                production_no=f"PERF32-MAP-PO-{suffix}-{index:04d}",
                production_type="client_order",
                model_id=model.id,
                planned_quantity=1,
            )
            for index, model in enumerate(models)
        ]
        db.add_all([
            *orders,
            *[
                ModelBOM(
                    model_id=model.id,
                    item_id=item.id,
                    stock_batch_id=batch.id,
                    quantity_per_piece=1,
                    unit="m",
                )
                for model, item, batch in zip(models, items, batches, strict=True)
            ],
        ])
        db.commit()
        return (
            [int(order.id) for order in orders],
            [f"/batch/{suffix}-{index}.webp" for index in range(count)],
        )


def test_material_context_uses_bounded_narrow_reference_maps():
    measurements = []
    for count in (1, 50, 401):
        order_ids, expected_urls = _material_reference_case(count)
        with TestSessionLocal() as db:
            statements = []

            def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
                if statement.lstrip().upper().startswith("SELECT"):
                    statements.append(" ".join(statement.lower().split()))

            event.listen(db.bind, "before_cursor_execute", capture)
            try:
                payload = inbox._material_payload_by_production_order(db, order_ids)
            finally:
                event.remove(db.bind, "before_cursor_execute", capture)
        measurements.append((payload, statements, expected_urls, order_ids))

    assert [len(statements) for _payload, statements, _urls, _ids in measurements] == [4, 4, 8]
    for payload, statements, expected_urls, order_ids in measurements:
        assert [payload[order_id]["material_image_url"] for order_id in order_ids] == expected_urls
        selected = "\n".join(statements)
        assert "items.composition_json" not in selected
        assert "stock_batches.roll_weights_kg" not in selected
        assert "stock_batches.roll_lengths_m" not in selected
        assert "model_images.file_data" not in selected


def test_finished_goods_package_lists_project_only_response_columns(monkeypatch):
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(code=f"INBOX-PKG-{suffix}", name="Inbox package model", status="approved")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"INBOX-PKG-PO-{suffix}",
            production_type="client_order",
            model_id=model.id,
            planned_quantity=2,
        )
        db.add(order)
        db.flush()
        packages = [
            Package(
                package_no=f"INBOX-PKG-{suffix}-{status}",
                barcode=f"INBOX-PKG-{suffix}-{status}",
                production_order_id=order.id,
                model_id=model.id,
                color="navy",
                total_quantity=2,
                status=status,
            )
            for status in ("packed", "reserved")
        ]
        db.add_all(packages)
        db.commit()
        package_ids = {package.status: int(package.id) for package in packages}

    monkeypatch.setattr(inbox, "require_operational_department_access", lambda *_args: None)
    monkeypatch.setattr(inbox, "user_permissions", lambda _user: ["*"])
    statements = []
    with TestSessionLocal() as db:
        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT") and "FROM PACKAGES" in statement.upper():
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = inbox.department_inbox(db, SimpleNamespace(department_id=None), dept="FGS")
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    pending = next(row for row in result["pending_packages"] if row["id"] == package_ids["packed"])
    ready = next(row for row in result["ready_packages"] if row["id"] == package_ids["reserved"])
    assert pending == {
        "id": package_ids["packed"],
        "package_no": f"INBOX-PKG-{suffix}-packed",
        "sales_order_id": None,
        "sales_order_no": None,
        "order_no": None,
        "total_quantity": 2,
    }
    assert ready == {
        "id": package_ids["reserved"],
        "package_no": f"INBOX-PKG-{suffix}-reserved",
        "sales_order_id": None,
        "sales_order_no": None,
        "order_no": None,
        "total_quantity": 2,
        "status": "reserved",
    }
    package_list_reads = [statement for statement in statements if "where packages.status" in statement]
    assert len(package_list_reads) == 2
    assert all("packages.barcode" not in statement for statement in package_list_reads)
    assert all("packages.notes" not in statement for statement in package_list_reads)
    assert all("packages.qr_code_url" not in statement for statement in package_list_reads)


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
