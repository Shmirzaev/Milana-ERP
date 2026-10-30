"""Approved PostgreSQL proofs for the worker-owned Model image upload write."""

import asyncio
import hashlib
from io import BytesIO
from pathlib import Path
from threading import Event, Timer
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.api.routes.catalog import router as catalog_router
from app.api.routes.usluga import router as usluga_router
from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.libs.dto.catalog.model_image_input import ModelImageUploadInput
from app.libs.dto.catalog.model_image_output import ModelImageUploadOut
from app.libs.enums.catalog import ModelImageUploadType
from app.libs.types.catalog import ModelImageUploadResult
from app.models.catalog import models_service
from app.models import image_storage_service
from app.schemas import AuditLog, Model, ModelImage, User
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def _png_bytes() -> bytes:
    output = BytesIO()
    with Image.new("RGB", (8, 8), "blue") as image:
        image.save(output, format="PNG")
    return output.getvalue()


def _upload(filename: str = "catalog-image.png") -> UploadFile:
    return UploadFile(file=BytesIO(_png_bytes()), filename=filename)


def _seed_model(
    sessions,
    *,
    scope: str = "standard",
    primary: bool = False,
    permissions: list[str] | None = None,
) -> tuple[int, int, int | None]:
    marker = uuid4().hex
    with sessions.begin() as db:
        user = User(
            name=f"Model image uploader {marker}",
            email=f"model-image-{marker}@example.invalid",
            password_hash="unused",
            factory_code="ECO" if scope == "usluga" else "MIL",
            extra_permissions=(
                permissions
                if permissions is not None
                else ["usluga.manage"] if scope == "usluga" else ["modeling.models"]
            ),
            is_active=True,
        )
        db.add(user)
        db.flush()
        model = Model(
            code=f"IMG-{marker}",
            name=f"Model image {marker}",
            catalog_scope=scope,
            factory_code="ECO" if scope == "usluga" else "MIL",
            created_by=user.id,
        )
        db.add(model)
        db.flush()
        old_image_id = None
        if primary:
            previous = ModelImage(
                model_id=model.id,
                file_url=f"https://example.invalid/{marker}.png",
                file_name=f"{marker}.png",
                content_type="image/png",
                image_type="model",
                is_primary=True,
            )
            db.add(previous)
            db.flush()
            old_image_id = int(previous.id)
        return int(model.id), int(user.id), old_image_id


def _upload_client(sessions, actor_id: int):
    app = FastAPI()
    app.include_router(catalog_router, prefix="/api")
    app.include_router(usluga_router, prefix="/api")
    request_sessions: list[Session] = []

    def isolated_db():
        with sessions() as db:
            request_sessions.append(db)
            yield db

    def current_user():
        with sessions() as db:
            user = db.get(User, actor_id)
            assert user is not None
            db.expunge(user)
            return user

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = current_user
    return TestClient(app, raise_server_exceptions=False), request_sessions


def _file_inventory(root: Path) -> dict[str, tuple[int, str]]:
    """Capture every managed file path, byte count and digest under the root."""
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize(
    ("provided", "expected"),
    [
        (None, None),
        ("   ", None),
        (" MODEL ", ModelImageUploadType.MODEL),
        ("Material", ModelImageUploadType.MATERIAL),
        ("pattern", ModelImageUploadType.PATTERN),
    ],
)
def test_upload_image_type_preserves_null_and_normalization_contract(provided, expected):
    assert TypeAdapter(ModelImageUploadInput).validate_python(provided) is expected


def test_upload_image_type_rejects_values_outside_the_action_subset():
    with pytest.raises(ValidationError):
        TypeAdapter(ModelImageUploadInput).validate_python("print")


def _resolve_openapi_schema(schema: dict, components: dict) -> dict:
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[1]
        return _resolve_openapi_schema(components[name], components)
    if "enum" in schema:
        return schema
    for child in schema.get("anyOf", []):
        try:
            resolved = _resolve_openapi_schema(child, components)
        except (KeyError, StopIteration):
            continue
        if "enum" in resolved:
            return resolved
    return schema


def test_upload_form_openapi_exposes_enum_contract_for_both_catalog_scopes(customer_pg_sessions):
    client, _ = _upload_client(customer_pg_sessions, 1)
    spec = client.app.openapi()
    components = spec["components"]["schemas"]

    for path in ("/api/models/{mid}/images/upload", "/api/usluga/models/{mid}/images/upload"):
        body = spec["paths"][path]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]
        body_schema = _resolve_openapi_schema(body, components)
        upload_type = _resolve_openapi_schema(body_schema["properties"]["image_type"], components)
        assert upload_type["enum"] == ["model", "material", "pattern"]
        assert "image_type" not in body_schema.get("required", [])


def test_upload_response_openapi_preserves_exact_two_key_contract(customer_pg_sessions):
    client, _ = _upload_client(customer_pg_sessions, 1)
    spec = client.app.openapi()
    components = spec["components"]["schemas"]

    for path in ("/api/models/{mid}/images/upload", "/api/usluga/models/{mid}/images/upload"):
        response_schema = spec["paths"][path]["post"]["responses"]["201"]["content"]["application/json"]["schema"]
        resolved = _resolve_openapi_schema(response_schema, components)
        assert set(resolved["properties"]) == {"id", "file_url"}
        assert set(resolved["required"]) == {"id", "file_url"}


def test_upload_response_dto_has_exact_two_key_json_contract():
    result = ModelImageUploadOut(id=17, file_url="/storage/model-files/model_17.webp")
    service_result: ModelImageUploadResult = {
        "id": 17,
        "file_url": "/storage/model-files/model_17.webp",
    }
    assert result.model_dump(mode="json") == {
        "id": 17,
        "file_url": "/storage/model-files/model_17.webp",
    }
    assert service_result == result.model_dump(mode="json")


@pytest.mark.parametrize(("scope", "factory"), [("standard", "MIL"), ("usluga", "ECO")])
def test_pg_upload_form_rejects_unknown_enum_before_storage_or_rows(
    customer_pg_sessions, tmp_path, monkeypatch, scope, factory,
):
    sessions = customer_pg_sessions
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id, _ = _seed_model(sessions, scope=scope, primary=True)
    client, _ = _upload_client(sessions, user_id)

    response = client.post(
        f"/api/{'usluga/' if scope == 'usluga' else ''}models/{model_id}/images/upload",
        data={"image_type": "print"},
        files={"file": ("catalog-image.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 422
    with sessions() as db:
        rows = db.query(ModelImage).filter(ModelImage.model_id == model_id).all()
        assert len(rows) == 1 and rows[0].is_primary is True
        assert _audits_for_model(db, model_id) == []
        assert db.get(Model, model_id).factory_code == factory
    assert _file_inventory(tmp_path) == {}
    chain(sessions)


def _audits_for_model(db: Session, model_id: int) -> list[AuditLog]:
    return [
        audit for audit in db.query(AuditLog).filter(AuditLog.entity_type == "ModelImage").order_by(AuditLog.id)
        if (audit.new_value_json or {}).get("model_id") == model_id
    ]


def _image_and_audits(sessions, model_id: int):
    with sessions() as db:
        images = db.query(ModelImage).filter(ModelImage.model_id == model_id).order_by(ModelImage.id).all()
        return images, _audits_for_model(db, model_id)


@pytest.mark.parametrize(("scope", "factory"), [("standard", "MIL"), ("usluga", "ECO")])
def test_pg_upload_persists_typed_image_through_worker_session_and_audits_once(
    customer_pg_sessions, tmp_path, monkeypatch, scope, factory,
):
    sessions = customer_pg_sessions
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id, old_image_id = _seed_model(sessions, scope=scope, primary=True)
    commits: list[Session] = []
    def record_commit(db: Session) -> None:
        commits.append(db)

    event.listen(Session, "after_commit", record_commit)
    client, request_sessions = _upload_client(sessions, user_id)
    try:
        response = client.post(
            f"/api/{'usluga/' if scope == 'usluga' else ''}models/{model_id}/images/upload",
            data={"image_type": "  MODEL  "},
            files={"file": ("catalog-image.png", _png_bytes(), "image/png")},
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert set(result) == {"id", "file_url"}
        detail_response = client.get(f"/api/{'usluga/' if scope == 'usluga' else ''}models/{model_id}")
        assert detail_response.status_code == 200, detail_response.text
        visible_image = next(
            image for image in detail_response.json()["images"] if image["id"] == result["id"]
        )
        assert visible_image["image_type"] == "model"
        assert visible_image["is_primary"] is True
        assert "file_data" not in visible_image
    finally:
        event.remove(Session, "after_commit", record_commit)

    assert result["id"] > 0
    assert result["file_url"].startswith("/storage/model-files/model_")
    assert len(commits) == 1
    assert commits[0] not in request_sessions  # preflight/request session is never committed
    assert old_image_id is not None
    with sessions() as db:
        old = db.get(ModelImage, old_image_id)
        image = db.get(ModelImage, result["id"])
        assert old is not None and old.is_primary is False
        assert image is not None
        assert (image.model_id, image.file_url, image.file_name, image.content_type) == (
            model_id, result["file_url"], "catalog-image.png", "image/webp",
        )
        assert (image.image_type, image.is_primary, image.file_data) == ("model", True, None)
        assert db.get(Model, model_id).factory_code == factory
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "ModelImage",
            AuditLog.entity_id == image.id,
        ).one()
        assert audit.action == "create"
        assert audit.user_id == user_id
        assert audit.old_value_json is None
        assert audit.new_value_json == {"model_id": model_id, "file_url": result["file_url"]}
    stored_name = Path(result["file_url"]).name
    assert (tmp_path / stored_name).is_file()
    assert (tmp_path / "_thumbs" / f"160_{stored_name}.webp").is_file()
    assert (tmp_path / "_thumbs" / f"320_{stored_name}.webp").is_file()
    assert set(_file_inventory(tmp_path)) == {
        stored_name,
        f"_thumbs/160_{stored_name}.webp",
        f"_thumbs/320_{stored_name}.webp",
    }
    images, audits = _image_and_audits(sessions, model_id)
    assert len(images) == 2 and len(audits) == 1
    chain(sessions)


@pytest.mark.parametrize("scope", ["standard", "usluga"])
def test_pg_upload_route_permission_denial_writes_nothing(customer_pg_sessions, tmp_path, monkeypatch, scope):
    sessions = customer_pg_sessions
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id, _ = _seed_model(sessions, scope=scope, permissions=[])
    client, _ = _upload_client(sessions, user_id)

    response = client.post(
        f"/api/{'usluga/' if scope == 'usluga' else ''}models/{model_id}/images/upload",
        data={"image_type": "model"},
        files={"file": ("catalog-image.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 403
    with sessions() as db:
        assert db.query(ModelImage).filter(ModelImage.model_id == model_id).count() == 0
        assert not [
            audit for audit in db.query(AuditLog).filter(AuditLog.entity_type == "ModelImage")
            if (audit.new_value_json or {}).get("model_id") == model_id
        ]
    assert list(tmp_path.rglob("*")) == []
    chain(sessions)


def test_pg_upload_pattern_type_keeps_nonprimary_contract(customer_pg_sessions, tmp_path, monkeypatch):
    sessions = customer_pg_sessions
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id, old_image_id = _seed_model(sessions, primary=True)

    with sessions() as request_db:
        current = request_db.get(User, user_id)
        result = asyncio.run(models_service.upload_image(
            current, request_db, model_id, file=_upload(), image_type=ModelImageUploadType.PATTERN,
        ))
        assert isinstance(result, dict)
        assert set(result) == {"id", "file_url"}
        assert all(isinstance(result[key], int) if key == "id" else isinstance(result[key], str)
                   for key in result)

    with sessions() as db:
        previous = db.get(ModelImage, old_image_id)
        image = db.get(ModelImage, result["id"])
        assert previous is not None and previous.is_primary is True
        assert image is not None and image.image_type == ModelImageUploadType.PATTERN.value
        assert image.is_primary is False
    chain(sessions)


@pytest.mark.parametrize("provided", [None, "   "])
def test_pg_upload_null_type_preserves_existing_primary(customer_pg_sessions, tmp_path, monkeypatch, provided):
    sessions = customer_pg_sessions
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id, old_image_id = _seed_model(sessions, primary=True)
    client, _ = _upload_client(sessions, user_id)
    form_data = {} if provided is None else {"image_type": provided}
    response = client.post(
        f"/api/models/{model_id}/images/upload",
        data=form_data,
        files={"file": ("catalog-image.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert set(result) == {"id", "file_url"}

    with sessions() as db:
        previous = db.get(ModelImage, old_image_id)
        image = db.get(ModelImage, result["id"])
        assert previous is not None and previous.is_primary is True
        assert image is not None and image.image_type is None and image.is_primary is False
    chain(sessions)


@pytest.mark.parametrize(("scope", "factory"), [("standard", "MIL"), ("usluga", "ECO")])
def test_pg_document_upload_persists_one_managed_file_without_thumbnails(
    customer_pg_sessions, tmp_path, monkeypatch, scope, factory,
):
    sessions = customer_pg_sessions
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id, _ = _seed_model(sessions, scope=scope)
    document_bytes = b"%PDF-1.7 synthetic"
    client, request_sessions = _upload_client(sessions, user_id)
    commits: list[Session] = []

    def record_commit(db: Session) -> None:
        commits.append(db)

    event.listen(Session, "after_commit", record_commit)
    try:
        response = client.post(
            f"/api/{'usluga/' if scope == 'usluga' else ''}models/{model_id}/images/upload",
            data={"image_type": "pattern"},
            files={"file": ("pattern.pdf", document_bytes, "application/pdf")},
        )
    finally:
        event.remove(Session, "after_commit", record_commit)
    assert response.status_code == 201, response.text
    result = response.json()
    assert len(commits) == 1
    assert commits[0] not in request_sessions

    stored_file = tmp_path / Path(result["file_url"]).name
    assert stored_file.read_bytes() == document_bytes
    assert not (tmp_path / "_thumbs").exists()
    assert _file_inventory(tmp_path) == {
        Path(result["file_url"]).name: (len(document_bytes), hashlib.sha256(document_bytes).hexdigest()),
    }
    assert all(not session.in_transaction() for session in request_sessions)
    with sessions() as db:
        image = db.get(ModelImage, result["id"])
        assert image is not None
        assert (image.model_id, image.file_name, image.content_type, image.image_type) == (
            model_id, "pattern.pdf", "application/pdf", "pattern",
        )
        assert db.get(Model, model_id).factory_code == factory
        assert image.file_data is None and image.is_primary is False
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "ModelImage",
            AuditLog.entity_id == image.id,
        ).one()
        assert audit.action == "create" and audit.user_id == user_id
    chain(sessions)


def test_pg_document_upload_precommit_audit_failure_rolls_back_row_and_file(
    customer_pg_sessions, tmp_path, monkeypatch,
):
    sessions = customer_pg_sessions
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id, old_image_id = _seed_model(sessions, primary=True)

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("synthetic precommit audit failure")

    monkeypatch.setattr(models_service, "log_action", fail_audit)
    with sessions() as request_db:
        current = request_db.get(User, user_id)
        with pytest.raises(RuntimeError, match="synthetic precommit audit failure"):
            asyncio.run(models_service.upload_image(
                current,
                request_db,
                model_id,
                file=UploadFile(file=BytesIO(b"%PDF-1.7 synthetic"), filename="pattern.pdf"),
                image_type=ModelImageUploadType.PATTERN,
            ))

    with sessions() as db:
        images = db.query(ModelImage).filter(ModelImage.model_id == model_id).all()
        audits = _audits_for_model(db, model_id)
        assert len(images) == 1 and images[0].id == old_image_id and images[0].is_primary is True
        assert audits == []
    assert list(tmp_path.rglob("*")) == []
    chain(sessions)


def test_pg_document_upload_partial_write_failure_leaves_no_file_or_row(
    customer_pg_sessions, tmp_path, monkeypatch,
):
    """Red baseline: prior direct Path.write_bytes bypassed replace and stranded bytes."""
    sessions = customer_pg_sessions
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id, _ = _seed_model(sessions)

    def fail_replace(_temporary, _destination):
        raise OSError("synthetic document replace failure")

    monkeypatch.setattr(image_storage_service.os, "replace", fail_replace)
    with sessions() as request_db:
        current = request_db.get(User, user_id)
        with pytest.raises(OSError, match="synthetic document replace failure"):
            asyncio.run(models_service.upload_image(
                current,
                request_db,
                model_id,
                file=UploadFile(file=BytesIO(b"%PDF-1.7 synthetic"), filename="pattern.pdf"),
                image_type=ModelImageUploadType.PATTERN,
            ))

    with sessions() as db:
        assert db.query(ModelImage).filter(ModelImage.model_id == model_id).count() == 0
        assert _audits_for_model(db, model_id) == []
    assert list(tmp_path.rglob("*")) == []
    chain(sessions)


def test_pg_cancel_after_worker_commit_keeps_file_and_row(customer_pg_sessions, tmp_path, monkeypatch):
    sessions = customer_pg_sessions
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id, _ = _seed_model(sessions)
    original = models_service._create_uploaded_model_image
    entered = Event()
    release = Event()

    def hold_after_row_and_audit(db, **kwargs):
        result = original(db, **kwargs)
        entered.set()
        release.wait(5)
        return result

    monkeypatch.setattr(models_service, "_create_uploaded_model_image", hold_after_row_and_audit)
    request_db = None
    try:
        with sessions() as request_db:
            current = request_db.get(User, user_id)

            async def upload_then_cancel():
                task = asyncio.create_task(models_service.upload_image(
                    current, request_db, model_id, file=_upload(), image_type=ModelImageUploadType.MODEL,
                ))
                for _ in range(500):
                    if entered.is_set():
                        break
                    await asyncio.sleep(0.01)
                assert entered.is_set(), "the worker did not reach its row/audit boundary"
                task.cancel()
                Timer(0.2, release.set).start()
                with pytest.raises(asyncio.CancelledError):
                    await task

            asyncio.run(upload_then_cancel())
    finally:
        release.set()

    with sessions() as db:
        image = db.query(ModelImage).filter(ModelImage.model_id == model_id).one()
        assert image.is_primary is True
        assert db.query(AuditLog).filter(
            AuditLog.entity_type == "ModelImage",
            AuditLog.entity_id == image.id,
        ).count() == 1
    assert (tmp_path / Path(image.file_url).name).is_file()
    assert (tmp_path / "_thumbs" / f"160_{Path(image.file_url).name}.webp").is_file()
    assert (tmp_path / "_thumbs" / f"320_{Path(image.file_url).name}.webp").is_file()
    chain(sessions)


def test_pg_cancel_during_image_processing_cleans_files_before_database_write(
    customer_pg_sessions, tmp_path, monkeypatch,
):
    sessions = customer_pg_sessions
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id, _ = _seed_model(sessions)
    convert = image_storage_service.convert_image_to_webp
    entered = Event()
    release = Event()

    def held_convert(content):
        entered.set()
        release.wait(5)
        return convert(content)

    monkeypatch.setattr(image_storage_service, "convert_image_to_webp", held_convert)
    try:
        with sessions() as request_db:
            current = request_db.get(User, user_id)

            async def upload_then_cancel():
                task = asyncio.create_task(models_service.upload_image(
                    current, request_db, model_id, file=_upload(), image_type=ModelImageUploadType.MODEL,
                ))
                for _ in range(500):
                    if entered.is_set():
                        break
                    await asyncio.sleep(0.01)
                assert entered.is_set(), "the upload did not enter image processing"
                task.cancel()
                Timer(0.2, release.set).start()
                with pytest.raises(asyncio.CancelledError):
                    await task

            asyncio.run(upload_then_cancel())
    finally:
        release.set()

    with sessions() as db:
        assert db.query(ModelImage).filter(ModelImage.model_id == model_id).count() == 0
        assert _audits_for_model(db, model_id) == []
    assert _file_inventory(tmp_path) == {}
    entries = {
        path.relative_to(tmp_path).as_posix(): path
        for path in tmp_path.rglob("*")
    }
    assert set(entries) == {"_thumbs"}
    assert not entries["_thumbs"].is_symlink()
    assert entries["_thumbs"].is_dir()
    assert not any(entries["_thumbs"].iterdir())
    chain(sessions)


def test_pg_upload_scope_is_rechecked_in_worker_before_mapped_insert(
    customer_pg_sessions, tmp_path, monkeypatch,
):
    sessions = customer_pg_sessions
    monkeypatch.setattr(settings, "MODEL_FILES_DIR", str(tmp_path))
    model_id, user_id, _ = _seed_model(sessions)
    store = models_service.store_uploaded_image

    async def store_then_move_scope(*args, **kwargs):
        saved = await store(*args, **kwargs)
        with sessions.begin() as db:
            db.execute(
                text("UPDATE models SET catalog_scope = 'usluga', factory_code = 'ECO' WHERE id = :model_id"),
                {"model_id": model_id},
            )
        return saved

    monkeypatch.setattr(models_service, "store_uploaded_image", store_then_move_scope)
    with sessions() as request_db:
        current = request_db.get(User, user_id)
        with pytest.raises(HTTPException) as refused:
            asyncio.run(models_service.upload_image(
                current, request_db, model_id, file=_upload(), image_type=ModelImageUploadType.MODEL,
                catalog_scope="standard",
            ))

    assert refused.value.status_code == 404
    with sessions() as db:
        assert db.query(ModelImage).filter(ModelImage.model_id == model_id).count() == 0
        assert _audits_for_model(db, model_id) == []
    assert list(tmp_path.rglob("*.webp")) == []
    chain(sessions)
