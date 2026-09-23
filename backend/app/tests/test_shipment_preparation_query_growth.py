from uuid import uuid4

import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import Model, ModelImage, SalesOrder, SalesOrderItem
from app.tests.conftest import test_engine


def _seed_preparation_variants(count: int) -> tuple[int, list[int], list[str]]:
    marker = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        order = SalesOrder(
            order_no=f"PERF35-SHIP-PREP-{marker}",
            order_type="client_order",
            status="ready",
            total_amount=0,
        )
        models = [
            Model(
                code=f"PERF35-SP-{marker}-{index:04d}",
                name=f"Shipment preparation model {index:04d}",
                status="approved",
            )
            for index in range(count)
        ]
        db.add_all([order, *models])
        db.flush()
        model_ids = [int(model.id) for model in models]
        image_urls = [
            f"/storage/model-files/perf35-shipment-{marker}-{index:04d}.webp"
            for index in range(count)
        ]
        db.add_all([
            ModelImage(
                model_id=model.id,
                file_url=image_urls[index],
                file_name=f"perf35-shipment-{marker}-{index:04d}.webp",
                content_type="image/webp",
                file_data=b"unused-shipment-preparation-binary",
                image_type="model",
                is_primary=True,
            )
            for index, model in enumerate(models)
        ])
        db.add_all([
            SalesOrderItem(
                sales_order_id=order.id,
                model_id=model.id,
                color=f"color-{index:04d}",
                size="M",
                quantity=index + 1,
                unit_price=0,
            )
            for index, model in enumerate(models)
        ])
        order_id = int(order.id)
        db.commit()
    return order_id, model_ids, image_urls


@pytest.mark.parametrize("variant_count", [1, 50, 401])
def test_sales_order_preparation_omits_image_binaries_at_scale(
    client,
    auth_headers,
    variant_count,
):
    order_id, model_ids, image_urls = _seed_preparation_variants(variant_count)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            f"/api/shipments/sales-order/{order_id}/preparation",
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    image_reads = [statement for statement in statements if " from model_images " in statement]
    order_item_reads = [
        statement for statement in statements if " from sales_order_items " in statement
    ]
    print(f"Shipment preparation variants {variant_count}: {len(statements)} SELECTs")
    assert [int(item["model_id"]) for item in items] == model_ids
    assert [item["model_image_url"] for item in items] == image_urls
    assert image_reads
    assert all("model_images.file_data" not in statement for statement in image_reads)
    assert len(order_item_reads) == 1
    assert "sales_order_items.unit_price" not in order_item_reads[0]
    assert "sales_order_items.notes" not in order_item_reads[0]
    assert "sales_order_items.requested_pack_count" in order_item_reads[0]
    assert len(statements) == 7
