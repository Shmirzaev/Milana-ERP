from uuid import uuid4

from sqlalchemy import event

from app.models import Model, ModelImage, ProductionOrder
from app.tests.conftest import TestSessionLocal, test_engine


def test_process_tracking_selects_only_model_context_columns(client, auth_headers):
    marker = uuid4().hex[:10]
    model_url = f"https://images.example.invalid/model-{marker}.webp"
    material_url = f"https://images.example.invalid/material-{marker}.webp"
    with TestSessionLocal() as db:
        model = Model(
            code=f"PERF35-PT-{marker}",
            name="Process tracking context projection",
            status="approved",
            details_json={"unused_large_value": "x" * 10_000},
        )
        db.add(model)
        db.flush()
        db.add_all([
            ModelImage(
                model_id=model.id,
                file_url=model_url,
                file_name="model.webp",
                content_type="image/webp",
                image_type="model",
                is_primary=True,
                file_data=b"model preview binary",
            ),
            ModelImage(
                model_id=model.id,
                file_url=material_url,
                file_name="material.webp",
                content_type="image/webp",
                image_type="material",
                file_data=b"material preview binary",
            ),
        ])
        order = ProductionOrder(
            production_no=f"PERF35-PT-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            status="new",
            planned_quantity=1,
        )
        db.add(order)
        db.commit()
        production_no = order.production_no

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            f"/api/process-tracking?include_total=true&page_size=1&q={production_no}",
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    row = response.json()["rows"][0]
    assert row["model_code"] == f"PERF35-PT-{marker}"
    assert row["model_name"] == "Process tracking context projection"
    assert row["model_image_url"] == model_url
    assert row["material_image_url"] == material_url
    model_reads = [statement for statement in statements if " from models " in statement]
    image_reads = [statement for statement in statements if " from model_images " in statement]
    assert len(model_reads) == 1
    assert len(image_reads) == 1
    assert "models.details_json" not in model_reads[0]
    assert "model_images.file_data as model_images_file_data" not in image_reads[0]
