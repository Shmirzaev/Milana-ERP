from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.planning import list_branded_orders
from app.models import BrandedPlanningOrder, Model, ModelImage, ProductionOrder
from app.tests.conftest import TestSessionLocal


def _seed_branded_order(variant_count: int) -> tuple[int, list[int], list[str]]:
    marker = uuid4().hex[:10].upper()
    with TestSessionLocal() as db:
        planning_order = BrandedPlanningOrder(
            order_no=f"PERF35-PLAN-{marker}",
            ordered_for_type="milana",
            ordered_for_name="Milana",
            status="open",
        )
        models = [
            Model(
                code=f"PERF35-PLAN-M-{marker}-{index:04d}",
                name=f"Planning model {index:04d}",
                status="approved",
            )
            for index in range(variant_count)
        ]
        db.add_all([planning_order, *models])
        db.flush()
        model_ids = [int(model.id) for model in models]
        image_urls = [
            f"/storage/model-files/perf35-planning-{marker}-{index:04d}.webp"
            for index in range(variant_count)
        ]
        db.add_all([
            ModelImage(
                model_id=model.id,
                file_url=image_urls[index],
                file_name=f"perf35-planning-{marker}-{index:04d}.webp",
                content_type="image/webp",
                file_data=b"unused-branded-planning-binary",
                image_type="model",
                is_primary=True,
            )
            for index, model in enumerate(models)
        ])
        db.add_all([
            ProductionOrder(
                production_no=f"PERF35-PLAN-PO-{marker}-{index:04d}",
                production_type="branded_stock",
                planning_order_id=planning_order.id,
                model_id=model.id,
                status="new",
                planned_quantity=index + 1,
            )
            for index, model in enumerate(models)
        ])
        planning_order_id = int(planning_order.id)
        db.commit()
    return planning_order_id, model_ids, image_urls


@pytest.mark.parametrize("variant_count", [1, 50, 401])
def test_branded_order_page_omits_model_image_binaries_at_scale(variant_count):
    planning_order_id, model_ids, image_urls = _seed_branded_order(variant_count)
    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_branded_orders(db, None, status="open", page=1, page_size=1)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert payload["rows"][0]["id"] == planning_order_id
    productions = payload["rows"][0]["productions"]
    image_reads = [statement for statement in statements if " from model_images " in statement]
    print(f"Branded planning variants {variant_count}: {len(statements)} SELECTs")
    assert [int(row["model_id"]) for row in productions] == model_ids
    assert [row["model"]["primary_image_url"] for row in productions] == image_urls
    assert image_reads
    assert all("model_images.file_data" not in statement for statement in image_reads)
    assert len(statements) == 7
