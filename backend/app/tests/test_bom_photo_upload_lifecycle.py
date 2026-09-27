import asyncio
from io import BytesIO
from itertools import count
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from PIL import Image

from app.api.routes import catalog
from app.models import AuditLog, Model, User
from app.services import image_storage
from app.tests.conftest import TestSessionLocal
from app.tests.upload_test_support import failing_upload_session_factory


def _png_bytes() -> bytes:
    data = BytesIO()
    Image.new("RGB", (12, 12), "white").save(data, format="PNG")
    return data.getvalue()


def _references() -> tuple[int, int, int]:
    with TestSessionLocal() as db:
        model_id = int(db.query(Model.id).filter(Model.catalog_scope == "standard").first()[0])
        user_id = int(db.query(User.id).filter(User.email == "admin@example.com").one()[0])
        audit_count = db.query(AuditLog).count()
    return model_id, user_id, audit_count


def _stored_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def test_bom_photo_commit_failure_rolls_back_and_removes_only_new_files(tmp_path, monkeypatch):
    model_id, user_id, audit_count = _references()
    existing = tmp_path / "existing-bom-photo.webp"
    existing.write_bytes(b"keep existing photo")
    monkeypatch.setattr(catalog.settings, "MODEL_FILES_DIR", str(tmp_path))
    upload = UploadFile(file=BytesIO(_png_bytes()), filename="material.png")
    try:
        with TestSessionLocal() as db:
            current = db.get(User, user_id)

            monkeypatch.setattr(
                catalog,
                "upload_session_factory",
                lambda _db: failing_upload_session_factory(
                    db,
                    "Synthetic BOM photo commit failure",
                ),
            )
            with pytest.raises(RuntimeError, match="Synthetic BOM photo commit failure"):
                asyncio.run(catalog.upload_bom_photo(model_id, db, upload, current, "standard"))
    finally:
        asyncio.run(upload.close())

    assert existing.read_bytes() == b"keep existing photo"
    assert _stored_files(tmp_path) == {Path(existing.name)}
    with TestSessionLocal() as db:
        assert db.query(AuditLog).count() == audit_count


def test_bom_photo_cancellation_shields_new_file_cleanup(tmp_path, monkeypatch):
    model_id, user_id, audit_count = _references()
    existing = tmp_path / "existing-bom-photo.webp"
    existing.write_bytes(b"keep existing photo")
    monkeypatch.setattr(catalog.settings, "MODEL_FILES_DIR", str(tmp_path))
    upload = UploadFile(file=BytesIO(_png_bytes()), filename="cancelled.png")

    async def run():
        with TestSessionLocal() as db:
            current = db.get(User, user_id)
            def cancel_after_file_write(*_args, **_kwargs):
                raise asyncio.CancelledError

            monkeypatch.setattr(catalog, "log_action", cancel_after_file_write)
            with pytest.raises(asyncio.CancelledError):
                await catalog.upload_bom_photo(model_id, db, upload, current, "standard")

    try:
        asyncio.run(run())
    finally:
        asyncio.run(upload.close())

    assert existing.read_bytes() == b"keep existing photo"
    assert _stored_files(tmp_path) == {Path(existing.name)}
    with TestSessionLocal() as db:
        assert db.query(AuditLog).count() == audit_count


def test_bom_photo_collision_and_failed_commit_preserve_preexisting_files(tmp_path, monkeypatch):
    model_id, user_id, audit_count = _references()
    collision_name = f"model_bom_{model_id}_collision.webp"
    existing_original = tmp_path / collision_name
    existing_original.write_bytes(b"keep collision original")
    existing_thumbnails = {
        tmp_path / "_thumbs" / f"{size}_{collision_name}.webp": f"keep {size}".encode()
        for size in image_storage.PREBUILT_THUMBNAIL_SIZES
    }
    for path, content in existing_thumbnails.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    sequence = count()

    def predictable_uuid():
        number = next(sequence)
        return SimpleNamespace(hex="collision" if number == 0 else f"fresh{number}")

    monkeypatch.setattr(catalog.settings, "MODEL_FILES_DIR", str(tmp_path))
    monkeypatch.setattr(image_storage, "uuid4", predictable_uuid)
    upload = UploadFile(file=BytesIO(_png_bytes()), filename="collision.png")
    try:
        with TestSessionLocal() as db:
            current = db.get(User, user_id)

            monkeypatch.setattr(
                catalog,
                "upload_session_factory",
                lambda _db: failing_upload_session_factory(
                    db,
                    "Synthetic collision commit failure",
                ),
            )
            with pytest.raises(RuntimeError, match="Synthetic collision commit failure"):
                asyncio.run(catalog.upload_bom_photo(model_id, db, upload, current, "standard"))
    finally:
        asyncio.run(upload.close())

    assert existing_original.read_bytes() == b"keep collision original"
    assert all(path.read_bytes() == content for path, content in existing_thumbnails.items())
    assert _stored_files(tmp_path) == {
        Path(collision_name),
        *(path.relative_to(tmp_path) for path in existing_thumbnails),
    }
    with TestSessionLocal() as db:
        assert db.query(AuditLog).count() == audit_count
