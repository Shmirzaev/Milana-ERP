from datetime import date, datetime, timedelta, timezone
from math import ceil
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.sewing_daily_reports import (
    _line_context,
    _production_kroy_no,
    _production_model_info,
    _report_list,
)
from app.db.session import SessionLocal
from app.models import (
    CuttingPassport,
    Department,
    Item,
    Model,
    ModelBOM,
    ModelImage,
    ProductionOrder,
    SewingDailyReport,
    SewingFlow,
    StockBatch,
    Warehouse,
    WorkOrder,
)


def _select_trace(db, callback):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return result, statements


def _target_select_counts(statements):
    return {
        "models": sum(" from models " in statement for statement in statements),
        "images": sum(" from model_images " in statement for statement in statements),
        "bom": sum(" from model_bom " in statement for statement in statements),
        "passports": sum(" from cutting_passports " in statement for statement in statements),
        "total": len(statements),
    }


def _read_case(db, count):
    suffix = uuid4().hex[:8].upper()
    report_date = date(2098, 7, count % 20 + 1)
    department_id = db.query(Department.id).order_by(Department.id).first()[0]
    flow = SewingFlow(
        factory_code="MIL",
        code=f"PERF17-{suffix}",
        name=f"PERF17 {suffix}",
        capacity_per_day=10_000,
        is_active=True,
    )
    db.add(flow)
    db.flush()

    models = [
        Model(
            code=f"PERF17-M-{suffix}-{number:04d}",
            name=f"PERF17 model {number}",
            details_json={
                "general": {
                    "model_no": f"MODEL-{number:04d}",
                    "variant_no": f"V-{number:04d}",
                },
            },
        )
        for number in range(count)
    ]
    db.add_all(models)
    db.flush()
    db.add_all([
        ModelImage(
            model_id=model.id,
            file_url=f"/storage/model-files/{suffix}-{number:04d}.webp",
            file_name=f"{suffix}-{number:04d}.webp",
            content_type="image/webp",
            image_type="model",
            is_primary=True,
            file_data=b"PERF17 must not be selected by the read path",
        )
        for number, model in enumerate(models)
    ])

    orders = [
        ProductionOrder(
            production_no=f"PERF17-PO-{suffix}-{number:04d}",
            production_type="branded_stock",
            model_id=model.id,
            status="sewing",
            planned_quantity=100,
        )
        for number, model in enumerate(models)
    ]
    db.add_all(orders)
    db.flush()
    work_orders = [
        WorkOrder(
            production_order_id=order.id,
            department_id=department_id,
            sewing_flow_id=flow.id,
            operation="sewing",
            status="waiting",
            planned_input_qty=100,
            planned_output_qty=100,
        )
        for order in orders
    ]
    db.add_all(work_orders)
    db.flush()
    passports = [
        CuttingPassport(
            passport_no=f"PERF17-KROY-{suffix}-{number:04d}",
            date=datetime(2098, 7, 1, tzinfo=timezone.utc),
            production_order_id=order.id,
        )
        for number, order in enumerate(orders)
    ]
    reports = [
        SewingDailyReport(
            report_date=report_date,
            sewing_flow_id=flow.id,
            work_order_id=work_order.id,
            production_order_id=order.id,
            line_code=flow.code,
            line_name=flow.name,
            order_no=order.production_no,
            production_no=order.production_no,
            kroy_no=passport.passport_no,
            sewn_qty=number + 1,
            defective_qty=number % 2,
            created_at=datetime(2098, 7, 1, tzinfo=timezone.utc) + timedelta(seconds=number),
        )
        for number, (order, work_order, passport) in enumerate(
            zip(orders, work_orders, passports, strict=True),
        )
    ]
    db.add_all([*passports, *reports])
    db.commit()
    return {
        "flow_id": flow.id,
        "report_date": report_date,
        "report_ids": [row.id for row in reports],
        "work_order_ids": [row.id for row in work_orders],
    }


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_daily_report_list_and_line_context_batch_read_metadata(row_count):
    with SessionLocal() as db:
        case = _read_case(db, row_count)
        legacy_production_order_sql = str(
            db.query(ProductionOrder).statement.compile(dialect=db.bind.dialect)
        ).lower()

    with SessionLocal() as db:
        listed, list_statements = _select_trace(
            db,
            lambda: _report_list(
                db,
                from_date=case["report_date"],
                to_date=case["report_date"],
                factory_code="MIL",
                sewing_flow_id=case["flow_id"],
            ),
        )
    with SessionLocal() as db:
        page, page_statements = _select_trace(
            db,
            lambda: _report_list(
                db,
                from_date=case["report_date"],
                to_date=case["report_date"],
                factory_code="MIL",
                sewing_flow_id=case["flow_id"],
                page=1,
                page_size=50,
            ),
        )
    with SessionLocal() as db:
        flow = db.get(SewingFlow, case["flow_id"])
        context, context_statements = _select_trace(db, lambda: _line_context(db, flow))

    expected_chunks = ceil(row_count / 400)
    list_counts = _target_select_counts(list_statements)
    page_counts = _target_select_counts(page_statements)
    context_counts = _target_select_counts(context_statements)
    assert list_counts["models"] == expected_chunks, list_counts
    assert list_counts["images"] == expected_chunks, list_counts
    assert list_counts["bom"] == expected_chunks, list_counts
    assert list_counts["passports"] == 0, list_counts
    assert context_counts["models"] == expected_chunks, context_counts
    assert context_counts["images"] == expected_chunks, context_counts
    assert context_counts["bom"] == expected_chunks, context_counts
    assert context_counts["passports"] == expected_chunks, context_counts
    assert list_counts["total"] == (9 if row_count == 401 else 5), list_counts
    production_order_reads = [
        statement for statement in list_statements
        if " from production_orders " in statement
    ]
    assert len(production_order_reads) == expected_chunks, list_statements
    assert all("production_orders.id" in statement for statement in production_order_reads)
    assert all("production_orders.model_id" in statement for statement in production_order_reads)
    assert all(
        field not in statement
        for statement in production_order_reads
        for field in ("printing_attachments", "service_material_notes", "service_handover_notes")
    ), production_order_reads
    assert "printing_attachments" in legacy_production_order_sql
    assert "service_material_notes" in legacy_production_order_sql
    assert page_counts == {
        "models": 1,
        "images": 1,
        "bom": 1,
        "passports": 0,
        "total": 6,
    }
    assert context_counts["total"] == (14 if row_count == 401 else 10), context_counts
    assert all(
        "file_data" not in statement
        for statement in [*list_statements, *page_statements, *context_statements]
    )
    assert max(statement.count("?") for statement in page_statements) <= 50
    assert [row.id for row in listed.rows] == list(reversed(case["report_ids"]))
    assert page.total == row_count
    assert page.page == 1
    assert page.page_size == 50
    assert len(page.rows) == min(row_count, 50)
    assert [row.model_dump() for row in page.rows] == [
        row.model_dump() for row in listed.rows[:50]
    ]
    assert page.total_sewn_qty == sum(row.sewn_qty for row in page.rows)
    assert page.total_defective_qty == sum(row.defective_qty for row in page.rows)
    assert [row.work_order_id for row in context.active_work_orders] == case["work_order_ids"]


def _semantic_case(db):
    suffix = uuid4().hex[:8].upper()
    report_date = date(2098, 8, 17)
    department_id = db.query(Department.id).order_by(Department.id).first()[0]
    warehouse_id = db.query(Warehouse.id).order_by(Warehouse.id).first()[0]
    flow = SewingFlow(
        factory_code="MIL", code=f"PERF17-S-{suffix}", name=f"PERF17 semantics {suffix}",
        capacity_per_day=1000, is_active=True,
    )
    other_flow = SewingFlow(
        factory_code="ECO", code=f"PERF17-E-{suffix}", name=f"PERF17 excluded {suffix}",
        capacity_per_day=1000, is_active=True,
    )
    typed_model = Model(
        code=f"PERF17-TYPED-{suffix}", name="Typed image model",
        details_json={"general": {"model_no": "TYPED", "variant_no": "TV"}},
    )
    item_model = Model(
        code=f"PERF17-ITEM-{suffix}", name="Item fallback model",
        details_json={"general": {"model_no": "ITEM", "variant_no": "IV"}},
    )
    batch_model = Model(
        code=f"PERF17-BATCH-{suffix}", name="Batch fallback model",
        details_json={"general": {"model_no": "BATCH", "variant_no": "BV"}},
    )
    shared_model = Model(
        code=f"PERF17-SHARED-{suffix}", name="Shared model",
        details_json={"general": {"model_no": "SHARED", "variant_no": "SV"}},
    )
    item = Item(
        sku=f"PERF17-I-{suffix}", name="Fabric with item image", category="fabric", unit="kg",
        image_url=f"/storage/model-files/item-{suffix}.webp",
    )
    batch_item = Item(
        sku=f"PERF17-BI-{suffix}", name="Fabric with batch image", category="fabric", unit="kg",
    )
    db.add_all([flow, other_flow, typed_model, item_model, batch_model, shared_model, item, batch_item])
    db.flush()
    stock_batch = StockBatch(
        item_id=batch_item.id,
        batch_no=f"PERF17-SB-{suffix}",
        quantity=1,
        unit="kg",
        cost_per_unit=1,
        warehouse_id=warehouse_id,
        image_url=f"/storage/model-files/batch-{suffix}.webp",
    )
    db.add(stock_batch)
    db.flush()
    db.add_all([
        ModelImage(
            model_id=typed_model.id,
            file_url=f"/storage/model-files/model-{suffix}.webp",
            content_type="image/webp", image_type="model", is_primary=True,
        ),
        ModelImage(
            model_id=typed_model.id,
            file_url=f"/storage/model-files/material-{suffix}.webp",
            content_type="image/webp", image_type="material", is_primary=False,
        ),
        ModelBOM(
            model_id=item_model.id, item_id=item.id, material_name="Item fabric",
            quantity_per_piece=1, unit="kg",
        ),
        ModelBOM(
            model_id=batch_model.id,
            item_id=batch_item.id,
            stock_batch_id=stock_batch.id,
            material_name="Batch fabric",
            quantity_per_piece=1,
            unit="kg",
        ),
    ])
    models = [typed_model, item_model, batch_model, shared_model, shared_model]
    orders = [
        ProductionOrder(
            production_no=f"PERF17-S-PO-{suffix}-{number}",
            production_type="branded_stock", model_id=model.id,
            status="sewing", planned_quantity=20,
        )
        for number, model in enumerate(models)
    ]
    excluded_order = ProductionOrder(
        production_no=f"PERF17-S-EXCLUDED-{suffix}", production_type="branded_stock",
        model_id=typed_model.id, status="sewing", planned_quantity=20,
    )
    db.add_all([*orders, excluded_order])
    db.flush()
    work_orders = [
        WorkOrder(
            production_order_id=order.id, department_id=department_id,
            sewing_flow_id=flow.id, operation="sewing", status="waiting",
            planned_input_qty=20, planned_output_qty=20,
        )
        for order in orders
    ]
    db.add_all(work_orders)
    db.flush()
    passport_rows = []
    for number, order in enumerate(orders):
        passport_rows.extend([
            CuttingPassport(
                passport_no=f"PERF17-OLD-{suffix}-{number}",
                date=datetime(2098, 8, 1, tzinfo=timezone.utc),
                production_order_id=order.id,
            ),
            CuttingPassport(
                passport_no=f"PERF17-LATEST-A-{suffix}-{number}",
                date=datetime(2098, 8, 2, tzinfo=timezone.utc),
                production_order_id=order.id,
            ),
            CuttingPassport(
                passport_no=f"PERF17-LATEST-B-{suffix}-{number}",
                date=datetime(2098, 8, 2, tzinfo=timezone.utc),
                production_order_id=order.id,
            ),
        ])
    db.add_all(passport_rows)
    db.flush()
    reports = []
    for number, (order, work_order) in enumerate(zip(orders, work_orders, strict=True)):
        reports.append(SewingDailyReport(
            report_date=report_date,
            sewing_flow_id=flow.id,
            work_order_id=work_order.id,
            production_order_id=order.id,
            line_code=flow.code,
            line_name=flow.name,
            order_no=order.production_no,
            production_no=order.production_no,
            manual_model_no="MANUAL" if number == 4 else None,
            manual_variant_no="MV" if number == 4 else None,
            kroy_no=f"SAVED-{number}",
            sewn_qty=number + 1,
            defective_qty=0,
        ))
    reports.append(SewingDailyReport(
        report_date=report_date,
        sewing_flow_id=other_flow.id,
        production_order_id=excluded_order.id,
        line_code=other_flow.code,
        line_name=other_flow.name,
        sewn_qty=99,
        defective_qty=0,
    ))
    db.add_all(reports)
    db.commit()
    return {
        "flow_id": flow.id,
        "report_date": report_date,
        "order_ids": [row.id for row in orders],
        "report_ids": [row.id for row in reports[:-1]],
        "work_order_ids": [row.id for row in work_orders],
        "urls": {
            "model": f"/storage/model-files/model-{suffix}.webp",
            "material": f"/storage/model-files/material-{suffix}.webp",
            "item": f"/storage/model-files/item-{suffix}.webp",
            "batch": f"/storage/model-files/batch-{suffix}.webp",
        },
    }


def test_daily_report_batched_reads_match_scalar_fallbacks_and_filters():
    with SessionLocal() as db:
        case = _semantic_case(db)
    with SessionLocal() as db:
        expected_models = {}
        expected_passports = {}
        for order_id in case["order_ids"]:
            order = db.get(ProductionOrder, order_id)
            expected_models[order_id] = _production_model_info(db, order)
            expected_passports[order_id] = _production_kroy_no(db, order_id)

    with SessionLocal() as db:
        listed = _report_list(
            db,
            from_date=case["report_date"],
            to_date=case["report_date"],
            factory_code="MIL",
            sewing_flow_id=case["flow_id"],
        )
    with SessionLocal() as db:
        context = _line_context(db, db.get(SewingFlow, case["flow_id"]))

    assert {row.id for row in listed.rows} == set(case["report_ids"])
    listed_by_order = {row.production_order_id: row.model_dump() for row in listed.rows}
    context_by_order = {row.production_order_id: row for row in context.active_work_orders}
    for order_id in case["order_ids"]:
        expected = expected_models[order_id]
        if listed_by_order[order_id]["manual_model_no"]:
            assert listed_by_order[order_id]["model_no"] == "MANUAL"
            assert listed_by_order[order_id]["variant_no"] == "MV"
            assert listed_by_order[order_id]["model_id"] is None
            assert listed_by_order[order_id]["model_image_url"] is None
            assert listed_by_order[order_id]["fabric_image_url"] is None
        else:
            assert {
                key: listed_by_order[order_id][key]
                for key in expected
            } == expected
        assert {
            key: getattr(context_by_order[order_id], key)
            for key in expected
        } == expected
        assert context_by_order[order_id].kroy_no == expected_passports[order_id]

    assert listed.total_sewn_qty == 15
    assert listed.total_defective_qty == 0
    assert [row.sewing_flow_id for row in listed.summary] == [case["flow_id"]]
    assert listed_by_order[case["order_ids"][0]]["model_image_url"] == case["urls"]["model"]
    assert listed_by_order[case["order_ids"][0]]["fabric_image_url"] == case["urls"]["material"]
    assert listed_by_order[case["order_ids"][1]]["fabric_image_url"] == case["urls"]["item"]
    assert listed_by_order[case["order_ids"][2]]["fabric_image_url"] == case["urls"]["batch"]
    assert set(context_by_order) == set(case["order_ids"])
    assert {row.work_order_id for row in context.active_work_orders} == set(case["work_order_ids"])


def test_daily_report_list_requires_authentication(client):
    response = client.get("/api/sewing-daily-reports?report_date=2098-08-17")
    assert response.status_code == 401


def test_daily_report_pagination_http_contract_and_legacy_shape(client, auth_headers):
    with SessionLocal() as db:
        case = _read_case(db, 1)

    params = {
        "report_date": case["report_date"].isoformat(),
        "factory_code": "MIL",
        "sewing_flow_id": case["flow_id"],
    }
    legacy = client.get("/api/sewing-daily-reports", params=params, headers=auth_headers)
    assert legacy.status_code == 200
    assert set(legacy.json()) == {
        "from_date",
        "to_date",
        "rows",
        "summary",
        "total_sewn_qty",
        "total_defective_qty",
    }

    paged = client.get(
        "/api/sewing-daily-reports",
        params={**params, "page": 1, "page_size": 50},
        headers=auth_headers,
    )
    assert paged.status_code == 200
    body = paged.json()
    assert body["rows"] == legacy.json()["rows"]
    assert body["summary"] == legacy.json()["summary"]
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 50

    invalid = client.get(
        "/api/sewing-daily-reports",
        params={**params, "page_size": 501},
        headers=auth_headers,
    )
    assert invalid.status_code == 422
