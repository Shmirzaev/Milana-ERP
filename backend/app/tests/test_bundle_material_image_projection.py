from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.bundles import _material_images_by_model_id
from app.models import Model, ModelBOM, ModelImage
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
        # Material images take precedence over BOM and stock fallbacks.
        db.add(ModelBOM(
            model_id=model_ids[0],
            photo_url="/storage/model-files/bom-fallback.webp",
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
