"""Real worker-Session CAD persistence, cleanup, scope recheck and bounded load."""
import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.models.catalog import models_service
from app.schemas import AuditLog, Model, ModelImage, User
from app.tests.test_image_upload_scheduling import upload_postgres, _seed_model  # noqa: F401
from app.tests.test_model_pattern_cad_upload import CAD_BYTES


async def upload(sessions, mid, uid, *, scope="standard", filename="QA.GEMX"):
    file = UploadFile(filename=filename, file=BytesIO(CAD_BYTES))
    try:
        with sessions() as db:
            return await models_service.upload_image(db.get(User, uid), db, mid, file=file,
                                                    image_type="pattern", catalog_scope=scope)
    finally:
        await file.close()


@pytest.mark.parametrize("scope", ["standard", "usluga"])
def test_cad_worker_commit_preserves_payload_metadata_and_audit(upload_postgres, tmp_path, monkeypatch, scope):
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    mid, uid = _seed_model(upload_postgres, scope=scope)
    result = asyncio.run(upload(upload_postgres, mid, uid, scope=scope))
    assert (tmp_path / Path(result["file_url"]).name).read_bytes() == CAD_BYTES
    with upload_postgres() as db:
        image = db.get(ModelImage, result["id"])
        assert (image.image_type, image.file_name, image.content_type, image.file_data, image.is_primary) == (
            "pattern", "QA.GEMX", "application/octet-stream", None, False)
        audit = db.query(AuditLog).filter_by(entity_type="ModelImage", entity_id=image.id, action="create").one()
        assert audit.entry_hash and audit.new_value_json["model_id"] == mid


def test_cad_worker_failure_rolls_back_row_audit_and_file(upload_postgres, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    mid, uid = _seed_model(upload_postgres)
    real_create = models_service._create_uploaded_model_image
    def fail(db, **kwargs):
        real_create(db, **kwargs)
        raise RuntimeError("injected CAD transaction failure")
    monkeypatch.setattr(models_service, "_create_uploaded_model_image", fail)
    with pytest.raises(RuntimeError, match="injected CAD transaction failure"):
        asyncio.run(upload(upload_postgres, mid, uid))
    assert not list(tmp_path.iterdir())
    with upload_postgres() as db:
        assert db.query(ModelImage).filter_by(model_id=mid).count() == 0
        assert not db.query(AuditLog).filter(AuditLog.new_value_json["model_id"].as_integer() == mid).first()


def test_cad_scope_is_rechecked_after_opaque_file_write(upload_postgres, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    mid, uid = _seed_model(upload_postgres)
    real_write = models_service._write_new_model_document
    def write_then_move(target, content):
        real_write(target, content)
        with upload_postgres.begin() as db:
            db.get(Model, mid).catalog_scope = "usluga"
    monkeypatch.setattr(models_service, "_write_new_model_document", write_then_move)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(upload(upload_postgres, mid, uid))
    assert refused.value.status_code == 404
    assert not list(tmp_path.iterdir())
    with upload_postgres() as db:
        assert db.query(ModelImage).filter_by(model_id=mid).count() == 0


def test_eight_cad_uploads_at_two_in_flight_keep_unique_files_and_evidence(upload_postgres, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    mid, uid = _seed_model(upload_postgres)
    async def run():
        # Each request and its worker can hold separate connections. Keep this
        # bounded challenge within the fixture's six-connection pool.
        slots = asyncio.Semaphore(2)
        async def attempt(index):
            async with slots:
                return await upload(upload_postgres, mid, uid, filename=f"QA-{index}.gem" if index % 2 else f"QA-{index}.gemx")
        return await asyncio.gather(*(attempt(index) for index in range(8)))
    results = asyncio.run(run())
    assert len({row["id"] for row in results}) == 8
    assert len({row["file_url"] for row in results}) == 8
    assert len(list(tmp_path.iterdir())) == 8
    for row in results:
        assert (tmp_path / Path(row["file_url"]).name).read_bytes() == CAD_BYTES
    with upload_postgres() as db:
        images = db.query(ModelImage).filter_by(model_id=mid).all()
        assert len(images) == 8
        assert all(row.image_type == "pattern" and row.content_type == "application/octet-stream" for row in images)
        assert db.query(AuditLog).filter(AuditLog.entity_type == "ModelImage", AuditLog.entity_id.in_([row.id for row in images])).count() == 8
