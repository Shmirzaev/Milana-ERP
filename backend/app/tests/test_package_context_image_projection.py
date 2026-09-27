from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import event

from app.api.routes.packages import _package_context
from app.models import Model, ModelImage
from app.tests.conftest import TestSessionLocal


def test_package_context_preserves_preview_url_without_selecting_image_binary():
    marker = uuid4().hex[:10]
    image_url = f"/storage/model-files/package-context-{marker}.webp"
    with TestSessionLocal() as db:
        model = Model(code=f"PKG-{marker}-V1", name="Package context projection", status="approved")
        db.add(model)
        db.flush()
        db.add(ModelImage(
            model_id=model.id,
            file_url=image_url,
            file_name="preview.webp",
            content_type="image/webp",
            image_type="model",
            is_primary=True,
            file_data=b"large model image binary not needed by package response",
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
            result = _package_context(
                db,
                SimpleNamespace(
                    production_order_id=None,
                    sales_order_id=None,
                    model_id=model_id,
                ),
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    image_reads = [statement for statement in statements if " from model_images " in statement]
    assert result == {
        "production_no": None,
        "sales_order_no": None,
        "order_no": None,
        "customer_name": None,
        "order_type": None,
        "model_code": f"PKG-{marker}-V1",
        "model_name": "Package context projection",
        "model_image_url": image_url,
    }
    assert len(statements) == 3
    assert len(image_reads) == 1
    assert "model_images.file_data" not in image_reads[0]
