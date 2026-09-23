from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.bundles import _material_images_by_model_id
from app.models import Item, Model, ModelBOM, ModelImage, StockBatch, Warehouse
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("model_count", [1, 50, 401])
def test_bundle_material_image_context_never_reads_image_binaries(model_count):
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        models = [
            Model(
                code=f"PERF35-BUNDLE-IMG-{marker}-{index:04d}",
                name=f"Bundle image model {index:04d}",
                status="approved",
            )
            for index in range(model_count)
        ]
        db.add_all(models)
        db.flush()
        model_ids = [int(model.id) for model in models]
        expected_urls = {
            model_id: f"/storage/model-files/perf35-bundle-{marker}-{index:04d}.webp"
            for index, model_id in enumerate(model_ids)
        }
        db.add_all([
            ModelImage(
                model_id=model_id,
                file_url=expected_urls[model_id],
                file_name=f"perf35-bundle-{marker}-{index:04d}.webp",
                content_type="image/webp",
                file_data=b"unused-bundle-list-image-binary",
                image_type="material",
            )
            for index, model_id in enumerate(model_ids)
        ])
        fallback_item = Item(
            sku=f"PERF35-BUNDLE-ITEM-{marker}",
            name="Bundle fallback material",
            category="fabric",
            unit="m",
            image_url=f"/storage/model-files/item-fallback-{marker}.webp",
        )
        fallback_model = Model(
            code=f"PERF35-BUNDLE-FALLBACK-{marker}",
            name="Bundle fallback image model",
            status="approved",
        )
        warehouse = db.query(Warehouse).first()
        fallback_batch = StockBatch(
            item=fallback_item,
            batch_no=f"BUNDLE-FALLBACK-{marker}",
            quantity=1,
            unit="m",
            warehouse_id=warehouse.id,
            image_url=f"/storage/model-files/batch-fallback-{marker}.webp",
        )
        db.add_all([fallback_model, fallback_item, fallback_batch])
        db.flush()
        model_ids.append(int(fallback_model.id))
        expected_urls[int(fallback_model.id)] = fallback_batch.image_url
        # Material images take precedence over BOM and stock fallbacks.
        db.add(ModelBOM(
            model_id=model_ids[0],
            photo_url="/storage/model-files/bom-fallback.webp",
            quantity_per_piece=1,
            unit="m",
        ))
        db.add(ModelBOM(
            model_id=fallback_model.id,
            item_id=fallback_item.id,
            stock_batch_id=fallback_batch.id,
            quantity_per_piece=1,
            unit="m",
        ))
        db.commit()

    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = _material_images_by_model_id(db, model_ids)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    image_reads = [statement for statement in statements if " from model_images " in statement]
    print(f"Bundle material image context {model_count}: {len(statements)} SELECTs")
    assert result == expected_urls
    assert len(statements) == 3
    assert image_reads
    assert all("model_images.file_data" not in statement for statement in image_reads)
    assert all("models.details_json" not in statement for statement in statements)
    assert all("model_bom.quantity_per_piece" not in statement for statement in statements)
    assert all("items.composition_json" not in statement for statement in statements)
    assert all("stock_batches.roll_weights_kg" not in statement for statement in statements)
