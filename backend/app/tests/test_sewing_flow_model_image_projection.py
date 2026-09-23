from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.sewing_flows import _work_order_model_context
from app.models import Model, ModelImage, ProductionOrder
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("order_count", [1, 50, 401])
def test_sewing_flow_context_selects_image_metadata_only_with_constant_growth(order_count):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        models = [
            Model(
                code=f"PERF35-SEW-{marker}-{index}-V1",
                name=f"Sewing context model {index}",
                status="approved",
            )
            for index in range(order_count)
        ]
        db.add_all(models)
        db.flush()
        orders = [
            ProductionOrder(
                production_no=f"PERF35-SEW-PO-{marker}-{index}",
                production_type="branded_stock",
                model_id=model.id,
            )
            for index, model in enumerate(models)
        ]
        db.add_all(orders)
        db.add_all(
            ModelImage(
                model_id=model.id,
                file_url=f"https://images.example.invalid/sewing-{marker}-{index}.webp",
                file_name="material.webp",
                content_type="image/webp",
                image_type="material",
                file_data=b"large binary not needed by sewing-flow context",
            )
            for index, model in enumerate(models)
        )
        db.commit()
        order_ids = [int(order.id) for order in orders]
        expected_urls = {
            order_id: f"https://images.example.invalid/sewing-{marker}-{index}.webp"
            for index, order_id in enumerate(order_ids)
        }

    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            context = _work_order_model_context(db, order_ids)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    image_reads = [statement for statement in statements if " from model_images " in statement]
    assert len(context) == order_count
    assert {
        order_id: row["material_image_url"] for order_id, row in context.items()
    } == expected_urls
    assert len(statements) == 3
    assert len(image_reads) == 1
    assert "model_images.file_data" not in image_reads[0]
