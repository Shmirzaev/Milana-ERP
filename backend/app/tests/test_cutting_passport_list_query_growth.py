from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import event

from app.api.routes import cutting_passports
from app.db.session import SessionLocal
from app.models import (
    CuttingPassport,
    Department,
    Item,
    Model,
    ModelBOM,
    ModelImage,
    ProductionOrder,
    SalesOrder,
    StockBatch,
    Warehouse,
    WorkOrder,
)


def _select_trace(db, call):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        result = call()
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return result, statements


def _factory_user(factory="MIL"):
    return SimpleNamespace(
        role=SimpleNamespace(name=""), extra_permissions=["cutting.records"],
        factory_code=factory, session_factory_code=factory,
    )


def _passport_set(db, count):
    suffix = uuid4().hex[:8]
    sales_orders = [
        SalesOrder(order_no=f"SO-PERF14-L-{suffix}-{number:04d}", status="draft", total_amount=0)
        for number in range(count)
    ]
    models = [
        Model(code=f"PERF14-L-{suffix}-{number:04d}", name=f"List model {number}", status="approved")
        for number in range(count)
    ]
    db.add_all([*sales_orders, *models])
    db.flush()
    orders = [
        ProductionOrder(
            production_no=f"PERF14-L-PO-{suffix}-{number:04d}", production_type="client_order",
            sales_order_id=sales_orders[number].id, model_id=models[number].id, planned_quantity=1,
        )
        for number in range(count)
    ]
    db.add_all(orders)
    db.flush()
    passports = [
        CuttingPassport(
            passport_no=f"PERF14-L-CP-{suffix}-{number:04d}",
            date=datetime(2026, 9, 20, tzinfo=timezone.utc),
            production_order_id=orders[number].id, model_code="stale-model-code",
        )
        for number in range(count)
    ]
    db.add_all([
        *passports,
        *[
            ModelImage(
                model_id=model.id, file_url=f"/storage/model-files/{suffix}-{number}.webp",
                file_name=f"{suffix}-{number}.webp", content_type="image/webp",
                file_data=b"binary-image-data-must-stay-deferred", image_type="model", is_primary=True,
            )
            for number, model in enumerate(models)
        ],
    ])
    db.commit()
    return suffix, [passport.id for passport in passports]


def test_passport_list_models_and_sales_references_are_chunk_bounded_without_blobs():
    with SessionLocal() as db:
        one_suffix, one_ids = _passport_set(db, 1)
        fifty_suffix, fifty_ids = _passport_set(db, 50)
        chunked_suffix, chunked_ids = _passport_set(db, 401)

    results = []
    for suffix in (one_suffix, fifty_suffix, chunked_suffix):
        with SessionLocal() as db:
            results.append(_select_trace(
                db,
                lambda suffix=suffix: cutting_passports.list_passports(
                    db, _factory_user(), q=suffix, limit=500,
                ),
            ))

    (one, one_sql), (fifty, fifty_sql), (chunked, chunked_sql) = results
    assert (len(one_sql), len(fifty_sql), len(chunked_sql)) == (4, 4, 7)
    for payload, passport_ids, statements in (
        (one, one_ids, one_sql), (fifty, fifty_ids, fifty_sql), (chunked, chunked_ids, chunked_sql),
    ):
        assert [row["id"] for row in payload] == list(reversed(passport_ids))
        assert all(row["model_name"].startswith("List model ") for row in payload)
        assert all(row["model_image_url"].endswith(".webp") for row in payload)
        assert all(row["order_no"].startswith("SO-PERF14-L-") for row in payload)
        assert "file_data" not in "\n".join(statements).lower()


def test_passport_pages_preserve_legacy_and_scope_model_reads():
    cases = []
    for count in (1, 50, 401):
        with SessionLocal() as db:
            suffix, passport_ids = _passport_set(db, count)
        with SessionLocal() as db:
            page, statements = _select_trace(
                db,
                lambda suffix=suffix: cutting_passports.list_passports(
                    db,
                    _factory_user(),
                    q=suffix,
                    page=1,
                    page_size=50,
                ),
            )
        with SessionLocal() as db:
            legacy = cutting_passports.list_passports(db, _factory_user(), q=suffix, limit=500)
        cases.append((count, passport_ids, page, legacy, statements))

    for count, passport_ids, page, legacy, statements in cases:
        returned_count = min(count, 50)
        assert page["total"] == count
        assert page["page"] == 1
        assert page["page_size"] == 50
        assert page["has_more"] is (count > 50)
        assert [row["id"] for row in page["rows"]] == list(reversed(passport_ids))[:returned_count]
        assert page["rows"] == legacy[:returned_count]
        assert len(statements) == 5, statements
        scoped_reads = [
            statement
            for statement in statements
            if " in (" in statement.lower() and any(
                table in statement.lower()
                for table in ("from models", "from model_images", "from model_bom")
            )
        ]
        assert len(scoped_reads) == 3, statements
        assert all(statement.count("?") == returned_count for statement in scoped_reads), statements


def test_passport_page_response_is_typed_and_bounded(client, auth_headers):
    response = client.get(
        "/api/cutting-passports?q=definitely-missing-passport&page=1&page_size=50",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "rows": [],
        "total": 0,
        "page": 1,
        "page_size": 50,
        "has_more": False,
    }
    assert client.get(
        "/api/cutting-passports?page_size=501",
        headers=auth_headers,
    ).status_code == 422


def test_passport_list_preserves_image_fallbacks_missing_links_and_factory_scope():
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        fabric = Item(
            sku=f"PERF14-L-FAB-{suffix}", name="List fabric",
            category="fabric", unit="kg", image_url=f"/storage/model-files/item-{suffix}.webp",
        )
        models = [
            Model(code=f"PERF14-L-PRIMARY-{suffix}", name="Primary image", status="approved"),
            Model(code=f"PERF14-L-MATERIAL-{suffix}", name="Material image", status="approved"),
            Model(code=f"PERF14-L-BOM-{suffix}", name="BOM image", status="approved"),
            Model(code=f"PERF14-L-BATCH-{suffix}", name="Batch image", status="approved"),
            Model(code=f"PERF14-L-ITEM-{suffix}", name="Item image", status="approved"),
        ]
        sales_orders = [
            SalesOrder(order_no=f"SO-PERF14-S-{suffix}-{number}", status="draft", total_amount=0)
            for number in range(8)
        ]
        db.add_all([fabric, *models, *sales_orders])
        db.flush()
        warehouse_id = db.query(Warehouse.id).order_by(Warehouse.id).first()[0]
        stock_batch = StockBatch(
            item_id=fabric.id, batch_no=f"PERF14-L-BATCH-{suffix}",
            quantity=1, unit="kg", cost_per_unit=1, warehouse_id=warehouse_id,
            qc_status="passed", image_url=f"/storage/model-files/batch-{suffix}.webp",
        )
        db.add(stock_batch)
        db.flush()
        db.add_all([
            ModelImage(
                model_id=models[0].id, file_url=f"/storage/model-files/primary-{suffix}.webp",
                file_name="primary.webp", content_type="image/webp", file_data=b"primary",
                image_type="model", is_primary=True,
            ),
            ModelImage(
                model_id=models[0].id, file_url=f"/storage/model-files/material-secondary-{suffix}.webp",
                file_name="secondary.webp", content_type="image/webp", file_data=b"secondary",
                image_type="material", is_primary=False,
            ),
            ModelImage(
                model_id=models[1].id, file_url=f"/storage/model-files/material-{suffix}.webp",
                file_name="material.webp", content_type="image/webp", file_data=b"material",
                image_type="material", is_primary=False,
            ),
            ModelBOM(
                model_id=models[2].id, item_id=fabric.id,
                photo_url=f"/storage/model-files/bom-{suffix}.webp",
                quantity_per_piece=1, unit="kg", waste_percent=0,
            ),
            ModelBOM(
                model_id=models[3].id, item_id=fabric.id, stock_batch_id=stock_batch.id,
                quantity_per_piece=1, unit="kg", waste_percent=0,
            ),
            ModelBOM(
                model_id=models[4].id, item_id=fabric.id,
                quantity_per_piece=1, unit="kg", waste_percent=0,
            ),
        ])
        order_models = [models[0], models[1], models[2], models[0], None, models[3], models[4], models[1]]
        orders = [
            ProductionOrder(
                production_no=f"PERF14-L-S-{suffix}-{number}", production_type="client_order",
                sales_order_id=sales_orders[number].id,
                model_id=order_models[number].id if order_models[number] else 999_999_999,
                planned_quantity=1,
            )
            for number in range(8)
        ]
        db.add_all(orders)
        db.flush()
        passports = [
            CuttingPassport(
                passport_no=f"PERF14-L-S-{suffix}-{number}",
                date=datetime(2026, 9, 20, tzinfo=timezone.utc),
                production_order_id=order.id,
                model_code="LEGACY-MISSING" if number == 4 else "stale",
            )
            for number, order in enumerate(orders)
        ]
        manual = CuttingPassport(
            passport_no=f"PERF14-L-S-{suffix}-manual",
            date=datetime(2026, 9, 20, tzinfo=timezone.utc),
            model_code="MANUAL-CODE", order_no="MANUAL-ORDER",
            operator_name_manual=f"Needle Operator {suffix}",
        )
        db.add_all([*passports, manual])
        eco = db.query(Department).filter_by(code="ECT").one()
        db.add(WorkOrder(
            production_order_id=orders[7].id, department_id=eco.id,
            operation="cutting", status="in_progress",
        ))
        db.commit()
        passport_ids = [passport.id for passport in passports]
        manual_id = manual.id

    with SessionLocal() as db:
        milana = cutting_passports.list_passports(db, _factory_user(), q=suffix, limit=500)
    by_id = {row["id"]: row for row in milana}
    assert [row["id"] for row in milana] == [manual_id, *reversed(passport_ids[:7])]
    assert by_id[passport_ids[0]]["model_image_url"] == f"/storage/model-files/primary-{suffix}.webp"
    assert by_id[passport_ids[1]]["model_image_url"] == f"/storage/model-files/material-{suffix}.webp"
    assert by_id[passport_ids[2]]["model_image_url"] == f"/storage/model-files/bom-{suffix}.webp"
    assert by_id[passport_ids[3]]["model_image_url"] == f"/storage/model-files/primary-{suffix}.webp"
    assert by_id[passport_ids[4]]["model_name"] == "LEGACY-MISSING"
    assert by_id[passport_ids[5]]["model_image_url"] == f"/storage/model-files/batch-{suffix}.webp"
    assert by_id[passport_ids[6]]["model_image_url"] == f"/storage/model-files/item-{suffix}.webp"
    assert by_id[manual_id]["model_name"] == "MANUAL-CODE"
    assert by_id[manual_id]["order_no"] == "MANUAL-ORDER"

    with SessionLocal() as db:
        eco_rows = cutting_passports.list_passports(db, _factory_user("ECO"), q=suffix, limit=500)
    assert [row["id"] for row in eco_rows] == [passport_ids[7]]
    with SessionLocal() as db:
        limited = cutting_passports.list_passports(db, _factory_user(), q=suffix, limit=2)
        operator_match = cutting_passports.list_passports(
            db, _factory_user(), q=f"Needle Operator {suffix}", limit=500,
        )
    assert [row["id"] for row in limited] == [manual_id, passport_ids[6]]
    assert [row["id"] for row in operator_match] == [manual_id]


def test_passport_list_requires_authentication(client):
    response = client.get("/api/cutting-passports")
    assert response.status_code == 401
