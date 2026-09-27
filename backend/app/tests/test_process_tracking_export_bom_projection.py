import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.production_extra import export_process_html
from app.db.session import SessionLocal
from app.models import Item, Model, ModelBOM, ProductionOrder


@pytest.mark.parametrize("order_count", [1, 50, 401])
def test_process_tracking_export_batches_bom_fallback_and_projects_columns(order_count):
    suffix = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        item = Item(
            sku=f"PERF35-EXPORT-{suffix}",
            name=f"Export fabric {suffix}",
            category="fabric",
            unit="kg",
        )
        db.add(item)
        db.flush()
        models = [
            Model(code=f"PERF35-EXPORT-M-{suffix}-{index:04d}", name=f"Fallback model {index:04d}")
            for index in range(order_count)
        ]
        db.add_all(models)
        db.flush()
        db.add_all(
            ModelBOM(
                model_id=model.id,
                item_id=item.id,
                photo_url=f"/storage/perf35-{suffix}.png" if index == 0 else None,
                quantity_per_piece=1,
                unit="kg",
            )
            for index, model in enumerate(models)
        )
        orders = [
            ProductionOrder(
                production_no=f"PERF35-EXPORT-PO-{suffix}-{index:04d}",
                production_type="client_order",
                model_id=model.id,
                status="new",
                planned_quantity=index + 1,
            )
            for index, model in enumerate(models)
        ]
        db.add_all(orders)
        db.commit()
        expected_order_numbers = [row.production_no for row in orders]
        expected_model_codes = [row.code for row in models]

    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            response = export_process_html(
                db,
                SimpleNamespace(factory_code="MIL", role=None, extra_permissions=[]),
                page=1,
                page_size=order_count,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    order_numbers = re.findall(r"PERF35-EXPORT-PO-[A-F0-9]+-\d{4}", response.body.decode())
    model_codes = re.findall(r"PERF35-EXPORT-M-[A-F0-9]+-\d{4}", response.body.decode())
    assert order_numbers == list(reversed(expected_order_numbers))
    assert model_codes == list(reversed(expected_model_codes))
    assert f"/storage/perf35-{suffix}.png" in response.body.decode()
    bom_queries = [statement for statement in statements if " from model_bom " in statement]
    assert len(bom_queries) == 1, statements
    assert len(statements) == 7, statements
    assert "category" in bom_queries[0]
    assert "image_url" in bom_queries[0]
    assert "join items" in bom_queries[0]
    assert "join stock_batches" in bom_queries[0]
    assert "model_bom.quantity_per_piece" not in bom_queries[0]
    model_query = next(statement for statement in statements if " from models " in statement)
    assert "models.details_json" not in model_query
    assert "models.code" in model_query and "models.name" in model_query
