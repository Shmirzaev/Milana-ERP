import asyncio
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image

from app.libs.enums.turnstile import GateMode, GatePhotoValidation
from app.models.people import turnstile_photo_service as service


def image_bytes(fmt="JPEG", exif=None):
    output = BytesIO()
    Image.new("RGB", (3, 2), "red").save(output, format=fmt, exif=exif or b"")
    return output.getvalue()


def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(service.settings, "ENV", "development")
    monkeypatch.setattr(service.settings, "TURNSTILE_PROVISIONING_MODE", GateMode.SIMULATOR)
    monkeypatch.setattr(service.settings, "TURNSTILE_PHOTOS_DIR", str(tmp_path))
    monkeypatch.setattr(service.settings, "TURNSTILE_PHOTO_MAX_BYTES", 1024 * 1024)
    monkeypatch.setattr(service.settings, "TURNSTILE_PHOTO_MAX_PIXELS", 100)
    monkeypatch.setattr(service, "authorize_gate_employee", lambda *a, **kw: None)
    monkeypatch.setattr(service, "authorize_gate_actor", lambda *a, **kw: None)
    monkeypatch.setattr(service, "selected_factory_code", lambda actor: "MIL")


class DB:
    def commit(self): pass
    def rollback(self): pass


def run_upload(data, db=None):
    return asyncio.run(service.upload_photo(db or DB(), SimpleNamespace(id=2), 1,
        UploadFile(filename="photo.jpg", file=BytesIO(data))))


def test_normalization_strips_metadata_and_rotates(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private"
    result, width, height = service._normalize(image_bytes(exif=exif))
    assert (width, height) == (2, 3)
    with Image.open(BytesIO(result)) as image:
        assert not image.getexif()


def test_bad_images_and_limits(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    with pytest.raises(HTTPException):
        run_upload(b"\xff\xd8\xffbroken")
    monkeypatch.setattr(service.settings, "TURNSTILE_PHOTO_MAX_BYTES", 10)
    with pytest.raises(HTTPException):
        run_upload(image_bytes())
    monkeypatch.setattr(service.settings, "TURNSTILE_PHOTO_MAX_PIXELS", 5)
    with pytest.raises(HTTPException):
        service._normalize(image_bytes())


def test_file_privacy_and_commit_failure_cleanup(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    untouched = tmp_path / "existing.jpg"
    untouched.write_bytes(b"existing")
    def insert(db, **kw):
        return SimpleNamespace(id=10, created_at=datetime.now(timezone.utc), **kw)
    monkeypatch.setattr(service, "insert_photo_asset", insert)
    result = run_upload(image_bytes())
    assert result.validation is GatePhotoValidation.TECHNICAL_VALIDATED
    assert "stored_name" not in result.model_dump()
    created = next(p for p in tmp_path.iterdir() if p != untouched)
    assert created.stat().st_mode & 0o777 == 0o600
    class Failing(DB):
        def commit(self): raise RuntimeError("commit failed")
    with pytest.raises(RuntimeError):
        run_upload(image_bytes(), Failing())
    assert {created, untouched}.issubset(set(tmp_path.iterdir()))
    assert len(list(tmp_path.iterdir())) == 3  # commit outcome can be uncertain


def test_read_rejects_forged_scope_and_path(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    asset = SimpleNamespace(employee_id=1, factory_code="BST", stored_name="../elsewhere.jpg")
    db = SimpleNamespace(get=lambda *a: asset)
    with pytest.raises(HTTPException):
        service.read_photo(db, SimpleNamespace(id=1), 1)
    asset.factory_code = "MIL"
    with pytest.raises(HTTPException):
        service.read_photo(db, SimpleNamespace(id=1), 1)


def test_precommit_failure_and_cancel_preserve_existing(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    existing = tmp_path / "existing.jpg"
    existing.write_bytes(b"existing")
    def fail_insert(*args, **kwargs):
        raise RuntimeError("insert failed")
    monkeypatch.setattr(service, "insert_photo_asset", fail_insert)
    with pytest.raises(RuntimeError):
        run_upload(image_bytes())
    assert list(tmp_path.iterdir()) == [existing]
    class CancelledUpload:
        filename = "photo.jpg"
        async def read(self, size):
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.upload_photo(DB(), SimpleNamespace(id=2), 1, CancelledUpload()))
    assert list(tmp_path.iterdir()) == [existing]


def test_public_or_disabled_mode_refused(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(service.settings, "TURNSTILE_PROVISIONING_MODE", GateMode.DISABLED)
    with pytest.raises(HTTPException):
        run_upload(image_bytes())
    monkeypatch.setattr(service.settings, "TURNSTILE_PROVISIONING_MODE", GateMode.SIMULATOR)
    monkeypatch.setattr(service.settings, "ENV", "production")
    with pytest.raises(HTTPException):
        run_upload(image_bytes())

def test_photo_read_checks_actor_before_database_lookup(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    def refuse(actor):
        raise HTTPException(403, "Private access required")
    monkeypatch.setattr(service, "authorize_gate_actor", refuse)
    class NeverRead:
        def get(self, *args):
            raise AssertionError("unauthorized actor reached photo lookup")
    with pytest.raises(HTTPException) as error:
        service.read_photo(NeverRead(), SimpleNamespace(id=12), 55)
    assert error.value.status_code == 403
