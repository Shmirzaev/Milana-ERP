from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.sales import _history_products
from app.models import Model, ModelImage
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("model_count", [1, 50, 401])
def test_sales_history_products_skip_image_binary_with_constant_query_growth(model_count):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        models = [
            Model(
                code=f"PERF35-HISTORY-{marker}-{index}-V1",
                name=f"History model {index}",
                status="approved",
            )
            for index in range(model_count)
        ]
        db.add_all(models)
        db.flush()
        db.add_all(
            ModelImage(
                model_id=model.id,
                file_url=f"https://images.example.invalid/history-{marker}-{index}.webp",
                file_name="material.webp",
                content_type="image/webp",
                image_type="material",
                file_data=b"large binary not needed by sales history",
            )
            for index, model in enumerate(models)
        )
        db.commit()
        model_ids = {int(model.id) for model in models}
        expected_url = f"https://images.example.invalid/history-{marker}-0.webp"

    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            products = _history_products(db, model_ids)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    image_reads = [statement for statement in statements if " from model_images " in statement]
    assert len(products) == model_count
    first = next(product for product in products if product["picture_url"] == expected_url)
    assert first["picture_url"] == expected_url
    assert len(statements) == 2
    assert len(image_reads) == 1
    assert "model_images.file_data" not in image_reads[0]
