from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.production import _production_order_detail_payload
from app.models import Model, ModelImage, ProductionOrder
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("image_count", [1, 50, 401])
def test_production_order_detail_skips_image_binary_and_preserves_selected_url(image_count):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        model = Model(
            code=f"PERF35-DETAIL-{marker}",
            name="Production detail image projection",
            status="approved",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF35-DETAIL-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=10,
        )
        db.add(order)
        urls = []
        for index in range(image_count):
            url = f"https://images.example.invalid/detail-{marker}-{index}.webp"
            urls.append(url)
            db.add(
                ModelImage(
                    model_id=model.id,
                    file_url=url,
                    file_name=f"image-{index}.webp",
                    content_type="image/webp",
                    image_type="model",
                    is_primary=True,
                    file_data=b"large image binary not needed by detail response",
                )
            )
        db.commit()
        order_id = int(order.id)
        selected_url = urls[-1]

    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = _production_order_detail_payload(db, order_id)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    image_reads = [statement for statement in statements if " from model_images " in statement]
    assert payload["model_image_url"] == selected_url
    assert payload["material_image_url"] is None
    assert len(image_reads) == 1
    assert "model_images.file_data" not in image_reads[0]
