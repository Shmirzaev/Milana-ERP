from uuid import uuid4
from math import ceil

import pytest
from sqlalchemy import event, inspect

from app.models import Model, ModelImage
from app.models.model_family_images_service import family_images_for_models, model_family_image
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("variant_count", [1, 50, 401])
def test_family_photo_hydrates_only_selected_garment_and_caches_transaction(variant_count):
    number = "PHOTO-" + uuid4().hex[:10]
    with TestSessionLocal() as db:
        base = Model(code=number, name="Base garment", details_json={"general": {"model_no": number}})
        base.images = [ModelImage(file_url="https://example.test/base.png", image_type="model",
                                  is_primary=True, file_data=b"base garment")]
        db.add(base)
        db.flush()
        expected_image = base.images[0].id
        for index in range(variant_count):
            variant = Model(code=f"{number}-V{index}", name="Family variant", details_json={
                "general": {"model_no": number, "variant_no": f"V{index}"},
            })
            variant.images = [ModelImage(file_url=f"https://example.test/variant-{index}.png",
                                         image_type="model", file_data=b"off-page image")]
            db.add(variant)
        db.flush()
        variant_id = variant.id
        db.commit()

    with TestSessionLocal() as db:
        variant = db.get(Model, variant_id)
        statements, hydrated_images = [], []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement.lower())

        def loaded(_session, row):
            if isinstance(row, ModelImage):
                hydrated_images.append(row.id)

        event.listen(db.bind, "before_cursor_execute", capture)
        event.listen(db, "loaded_as_persistent", loaded)
        try:
            family_images_for_models(db, [variant])
            image = model_family_image(variant)
            assert image.id == expected_image
            assert image.file_url == "https://example.test/base.png"
            assert "file_data" in inspect(image).unloaded
            assert model_family_image(variant) is image
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
            event.remove(db, "loaded_as_persistent", loaded)

    assert hydrated_images == [expected_image]
    assert len(statements) == 2 + ceil((variant_count + 1) / 400)  # Identity, candidate metadata, winner.
    assert all("file_data" not in statement for statement in statements)
