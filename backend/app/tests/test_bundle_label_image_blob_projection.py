import base64
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.bundles import _label_context
from app.models import Bundle, ModelImage
from app.tests.conftest import TestSessionLocal
from app.tests.test_production_flow import _create_bundle_for_scan


@pytest.mark.parametrize("image_count", [1, 50, 401])
def test_bundle_label_loads_only_selected_material_image_blob(client, auth_headers, image_count):
    bundle_data = _create_bundle_for_scan(client, auth_headers)
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        bundle = db.get(Bundle, bundle_data["id"])
        image_bytes = f"selected-bundle-label-image-{marker}".encode()
        for index in range(image_count):
            db.add(
                ModelImage(
                    model_id=bundle.model_id,
                    file_url=f"/storage/model-files/bundle-label-{marker}-{index}.webp",
                    file_name=f"material-{index}.webp",
                    content_type="image/webp",
                    image_type="material",
                    file_data=image_bytes if index == image_count - 1 else b"unselected image BLOB",
                )
            )
        db.commit()
        bundle_id = int(bundle.id)

    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            context = _label_context(db, db.get(Bundle, bundle_id))
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    image_reads = [statement for statement in statements if " from model_images " in statement]
    blob_reads = [statement for statement in image_reads if "model_images.file_data" in statement]
    assert context["material_image_src"] == (
        "data:image/webp;base64," + base64.b64encode(image_bytes).decode()
    )
    assert len(image_reads) == 2
    assert len(blob_reads) == 1
    assert "where model_images.id = ?" in blob_reads[0]


def test_bundle_label_loads_database_only_model_fallback_blob(client, auth_headers):
    bundle_data = _create_bundle_for_scan(client, auth_headers)
    marker = uuid4().hex[:10]
    image_bytes = f"database-only-model-fallback-{marker}".encode()
    with TestSessionLocal() as db:
        bundle = db.get(Bundle, bundle_data["id"])
        db.add(
            ModelImage(
                model_id=bundle.model_id,
                file_url=f"/storage/model-files/missing-model-{marker}.webp",
                file_name="model.webp",
                content_type="image/webp",
                image_type="model",
                is_primary=True,
                file_data=image_bytes,
            )
        )
        db.commit()
        bundle_id = int(bundle.id)

    with TestSessionLocal() as db:
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            context = _label_context(db, db.get(Bundle, bundle_id))
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    blob_reads = [
        statement
        for statement in statements
        if " from model_images " in statement and "model_images.file_data" in statement
    ]
    assert context["material_image_src"] == (
        "data:image/webp;base64," + base64.b64encode(image_bytes).decode()
    )
    assert len(blob_reads) == 1
    assert "where model_images.id = ?" in blob_reads[0]
