from uuid import uuid4

from sqlalchemy import event

from app.api.routes.production import _work_order_images_by_po
from app.models import Model, ModelImage, ProductionOrder
from app.tests.conftest import TestSessionLocal


def test_work_order_image_context_preserves_urls_without_selecting_image_binary():
    marker = uuid4().hex[:10]
    model_url = f"/storage/model-files/work-order-{marker}.webp"
    material_url = f"/storage/model-files/work-order-material-{marker}.webp"
    with TestSessionLocal() as db:
        model = Model(code=f"WO-{marker}-V1", name="Work order image projection", status="approved")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF35-WO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
        )
        db.add_all([
            order,
            ModelImage(
                model_id=model.id,
                file_url=model_url,
                file_name="model.webp",
                content_type="image/webp",
                image_type="model",
                is_primary=True,
                file_data=b"large model image binary not needed by list response",
            ),
            ModelImage(
                model_id=model.id,
                file_url=material_url,
                file_name="material.webp",
                content_type="image/webp",
                image_type="material",
                file_data=b"large material image binary not needed by list response",
            ),
        ])
        db.commit()
        order_id = int(order.id)

    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = _work_order_images_by_po(db, [order_id])
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    image_reads = [statement for statement in statements if " from model_images " in statement]
    assert result[order_id] == {
        "model_no": f"WO-{marker}",
        "variant_no": "V1",
        "model_image_url": model_url,
        "material_image_url": material_url,
    }
    assert len(statements) == 3
    assert len(image_reads) == 1
    assert "model_images.file_data" not in image_reads[0]
