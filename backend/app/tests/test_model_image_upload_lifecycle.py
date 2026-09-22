import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from anyio import CancelScope
from fastapi import UploadFile
from PIL import Image

from app.api.routes import catalog
from app.models import AuditLog, Model, ModelImage, User
from app.tests.conftest import TestSessionLocal


def _png_bytes() -> bytes:
    data = BytesIO()
    Image.new("RGB", (12, 12), "white").save(data, format="PNG")
    return data.getvalue()


def _references() -> tuple[int, int, int, int, int]:
    with TestSessionLocal() as db:
        model_id = int(db.query(Model.id).filter(Model.catalog_scope == "standard").first()[0])
        user_id = int(db.query(User.id).filter(User.email == "admin@example.com").one()[0])
        primary = ModelImage(
            model_id=model_id,
            file_url="/storage/model-files/existing-primary.webp",
            file_name="existing-primary.webp",
            content_type="image/webp",
            image_type="model",
            is_primary=True,
        )
        db.add(primary)
        db.commit()
        image_count = db.query(ModelImage).count()
        audit_count = db.query(AuditLog).count()
    return model_id, user_id, int(primary.id), image_count, audit_count


def _stored_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def test_model_image_commit_failure_removes_new_files_and_rolls_back(tmp_path, monkeypatch):
    model_id, user_id, primary_id, image_count, audit_count = _references()
    existing = tmp_path / "existing-model-image.webp"
    existing.write_bytes(b"keep existing image")
    monkeypatch.setattr(catalog.settings, "MODEL_FILES_DIR", str(tmp_path))
    upload = UploadFile(file=BytesIO(_png_bytes()), filename="new-image.png")

    try:
        with TestSessionLocal() as db:
            current = db.get(User, user_id)

            def fail_commit():
                raise RuntimeError("Synthetic model image commit failure")

            monkeypatch.setattr(db, "commit", fail_commit)
            with pytest.raises(RuntimeError, match="Synthetic model image commit failure"):
                asyncio.run(catalog.upload_image(model_id, db, upload, "model", current, "standard"))
    finally:
        asyncio.run(upload.close())

    assert existing.read_bytes() == b"keep existing image"
    assert _stored_files(tmp_path) == {Path(existing.name)}
    with TestSessionLocal() as db:
        assert db.query(ModelImage).count() == image_count
        assert db.get(ModelImage, primary_id).is_primary is True
        assert db.query(AuditLog).count() == audit_count


def test_model_document_commit_failure_removes_new_file_and_rolls_back(tmp_path, monkeypatch):
    model_id, user_id, _primary_id, image_count, audit_count = _references()
    existing = tmp_path / "existing-model-document.pdf"
    existing.write_bytes(b"keep existing document")
    monkeypatch.setattr(catalog.settings, "MODEL_FILES_DIR", str(tmp_path))
    upload = UploadFile(file=BytesIO(b"%PDF-1.4\nsynthetic"), filename="new-document.pdf")

    try:
        with TestSessionLocal() as db:
            current = db.get(User, user_id)

            def fail_commit():
                raise RuntimeError("Synthetic model document commit failure")

            monkeypatch.setattr(db, "commit", fail_commit)
            with pytest.raises(RuntimeError, match="Synthetic model document commit failure"):
                asyncio.run(catalog.upload_image(model_id, db, upload, None, current, "standard"))
    finally:
        asyncio.run(upload.close())

    assert existing.read_bytes() == b"keep existing document"
    assert _stored_files(tmp_path) == {Path(existing.name)}
    with TestSessionLocal() as db:
        assert db.query(ModelImage).count() == image_count
        assert db.query(AuditLog).count() == audit_count


def test_model_image_cancellation_shields_new_file_cleanup(tmp_path, monkeypatch):
    model_id, user_id, primary_id, image_count, audit_count = _references()
    existing = tmp_path / "existing-model-image.webp"
    existing.write_bytes(b"keep existing image")
    monkeypatch.setattr(catalog.settings, "MODEL_FILES_DIR", str(tmp_path))
    upload = UploadFile(file=BytesIO(_png_bytes()), filename="cancelled.png")

    async def run():
        with TestSessionLocal() as db:
            current = db.get(User, user_id)
            with CancelScope() as scope:
                def cancel_after_file_write(*_args, **_kwargs):
                    scope.cancel()
                    raise asyncio.CancelledError

                monkeypatch.setattr(catalog, "log_action", cancel_after_file_write)
                with pytest.raises(asyncio.CancelledError):
                    await catalog.upload_image(model_id, db, upload, "model", current, "standard")
                assert scope.cancel_called

    try:
        asyncio.run(run())
    finally:
        asyncio.run(upload.close())

    assert existing.read_bytes() == b"keep existing image"
    assert _stored_files(tmp_path) == {Path(existing.name)}
    with TestSessionLocal() as db:
        assert db.query(ModelImage).count() == image_count
        assert db.get(ModelImage, primary_id).is_primary is True
        assert db.query(AuditLog).count() == audit_count


def test_model_document_collision_preserves_preexisting_file(tmp_path, monkeypatch):
    model_id, user_id, _primary_id, image_count, audit_count = _references()
    collision = tmp_path / f"model_{model_id}_collision.pdf"
    collision.write_bytes(b"keep collision document")
    monkeypatch.setattr(catalog.settings, "MODEL_FILES_DIR", str(tmp_path))
    monkeypatch.setattr(catalog, "uuid4", lambda: SimpleNamespace(hex="collision"))
    upload = UploadFile(file=BytesIO(b"%PDF-1.4\nreplacement"), filename="document.pdf")

    try:
        with TestSessionLocal() as db:
            current = db.get(User, user_id)
            with pytest.raises(FileExistsError):
                asyncio.run(catalog.upload_image(model_id, db, upload, None, current, "standard"))
    finally:
        asyncio.run(upload.close())

    assert collision.read_bytes() == b"keep collision document"
    assert _stored_files(tmp_path) == {Path(collision.name)}
    with TestSessionLocal() as db:
        assert db.query(ModelImage).count() == image_count
        assert db.query(AuditLog).count() == audit_count
