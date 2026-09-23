from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.planning import list_branded_orders
from app.tests.conftest import TestSessionLocal
from app.models import BrandedPlanningOrder, Item, Model, ModelBOM, ProductionOrder


@pytest.mark.parametrize("variant_count", [1, 50, 401])
def test_branded_order_bom_payload_uses_projected_batch_load(variant_count):
    marker = uuid4().hex[:8].upper()
    with TestSessionLocal() as db:
        order = BrandedPlanningOrder(
            order_no=f"PERF35-BOM-ORDER-{marker}",
            ordered_for_type="milana",
            ordered_for_name="Milana",
            status="open",
        )
        db.add(order)
        db.flush()
        models = [
            Model(code=f"PERF35-BOM-M-{marker}-{index:04d}", name=f"BOM model {index:04d}")
            for index in range(variant_count)
        ]
        items = [
            Item(
                sku=f"PERF35-BOM-I-{marker}-{index:04d}",
                name=f"Fabric {index:04d}",
                category="fabric",
                unit="kg",
            )
            for index in range(variant_count)
        ]
        db.add_all([*models, *items])
        db.flush()
        db.add_all(
            ProductionOrder(
                production_no=f"PERF35-BOM-PO-{marker}-{index:04d}",
                production_type="branded_stock",
                planning_order_id=order.id,
                model_id=model.id,
                status="new",
                planned_quantity=index + 1,
            )
            for index, model in enumerate(models)
        )
        db.add_all(
            ModelBOM(
                model_id=model.id,
                item_id=item.id,
                color="navy",
                photo_url=f"/storage/perf35-bom-{marker}.png" if index == 0 else None,
                quantity_per_piece=1.25,
                unit="kg",
                waste_percent=3,
            )
            for index, (model, item) in enumerate(zip(models, items, strict=True))
        )
        db.commit()
        order_id = order.id
        expected_model_ids = [int(model.id) for model in models]

    with TestSessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_branded_orders(db, None, status="open", page=1, page_size=1)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    row = next(item for item in payload["rows"] if item["id"] == order_id)
    productions = row["productions"]
    assert [int(item["model_id"]) for item in productions] == expected_model_ids
    assert [item["model"]["variant_fabric"] for item in productions] == [
        f"Fabric {index:04d} / navy" for index in range(variant_count)
    ]
    assert productions[0]["model"]["primary_image_url"] == f"/storage/perf35-bom-{marker}.png"
    assert productions[0]["model"]["fabric_image_url"] == f"/storage/perf35-bom-{marker}.png"
    assert all(item["model"]["primary_image_url"] is None for item in productions[1:])
    bom_queries = [statement for statement in statements if " from model_bom " in statement]
    assert len(bom_queries) == 1, statements
    assert "quantity_per_piece" not in bom_queries[0]
    assert "waste_percent" not in bom_queries[0]
    assert "model_bom.color" in bom_queries[0]
    assert "category" in bom_queries[0] and "image_url" in bom_queries[0]
