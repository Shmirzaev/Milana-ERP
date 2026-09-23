from uuid import uuid4

from sqlalchemy import event

from app.api.routes.catalog import _model_with_variant_relations, _model_variant_payload
from app.models import Model, ModelImage
from app.tests.conftest import TestSessionLocal


def test_variant_context_reads_preview_metadata_but_keeps_variant_copy_binary_available():
    marker = uuid4().hex[:10]
    image_url = f"/storage/model-files/catalog-variant-{marker}.webp"
    with TestSessionLocal() as db:
        model = Model(code=f"CV-{marker}-V1", name="Variant image projection", status="approved")
        db.add(model)
        db.flush()
        db.add(ModelImage(
            model_id=model.id,
            file_url=image_url,
            file_name="variant.webp",
            content_type="image/webp",
            image_type="model",
            is_primary=True,
            file_data=b"large image binary retained for creating a variant",
        ))
        db.commit()
        model_id = int(model.id)

    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            model = _model_with_variant_relations(db, model_id)
            payload = _model_variant_payload(model)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    image_reads = [statement for statement in statements if " from model_images " in statement]
    assert payload["picture_url"] == image_url
    assert len(image_reads) == 1
    assert "model_images.file_data" not in image_reads[0]

    with TestSessionLocal() as db:
        model = _model_with_variant_relations(db, model_id, include_image_binaries=True)
        assert model.images[0].file_data == b"large image binary retained for creating a variant"
