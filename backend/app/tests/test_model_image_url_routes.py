"""Route, audit, and rollback coverage for URL image creation."""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.catalog import router as catalog_router
from app.api.routes.usluga import router as usluga_router
from app.core.deps import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.schemas import AuditLog, Model, ModelImage, Role, User


@pytest.fixture
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions.begin() as db:
        allow = Role(name="Image access", permissions=["modeling.models", "usluga.manage"])
        deny = Role(name="Image denied", permissions=[])
        db.add_all([allow, deny])
        db.flush()
        users = {name: User(name=name, email=f"{name}@example.invalid", password_hash="unused", role_id=role.id, factory_code=factory) for name, role, factory in [("standard", allow, "MIL"), ("usluga", allow, "ECO"), ("wrong", allow, "MIL"), ("denied", deny, "MIL")]}
        models = {name: Model(code=f"IMAGE-{name}", name=name, catalog_scope=scope, factory_code=factory) for name, scope, factory in [("standard", "standard", "MIL"), ("usluga", "usluga", "ECO")]}
        db.add_all([*users.values(), *models.values()])
        db.flush()
        db.add_all([ModelImage(model_id=m.id, file_url="https://old.test/image", is_primary=True) for m in models.values()])
        ids = {"users": {name: u.id for name, u in users.items()}, "models": {name: m.id for name, m in models.items()}}
    app = FastAPI()
    app.include_router(catalog_router, prefix="/api")
    app.include_router(usluga_router, prefix="/api")
    def db_override():
        with sessions() as db:
            yield db
    def actor_override(request: Request):
        with sessions() as db:
            user = db.get(User, ids["users"][request.headers.get("X-Actor", "standard")])
            _ = user.role, user.department
            db.expunge_all()
            return user
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = actor_override
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, sessions, ids, app
    engine.dispose()


def path(scope, model_id):
    prefix = "/api/usluga/models" if scope == "usluga" else "/api/models"
    return f"{prefix}/{model_id}/images"


@pytest.mark.parametrize("scope", ["standard", "usluga"])
def test_route_create_records_real_audit(env, scope):
    client, sessions, ids, _ = env
    response = client.post(path(scope, ids["models"][scope]), headers={"X-Actor": scope}, json={"file_url": " https://example.test/picture ", "image_type": " MODEL ", "is_primary": True})
    assert response.status_code == 201
    with sessions() as db:
        image = db.get(ModelImage, response.json()["id"])
        assert (image.model_id, image.file_url, image.image_type, image.is_primary) == (ids["models"][scope], "https://example.test/picture", "model", True)
        old = db.scalar(select(ModelImage).where(ModelImage.model_id == image.model_id, ModelImage.id != image.id))
        assert not old.is_primary
        audit = db.scalar(select(AuditLog))
        assert (audit.user_id, audit.action, audit.entity_type, audit.entity_id) == (ids["users"][scope], "create", "ModelImage", image.id)
        assert audit.new_value_json == {"model_id": image.model_id, "file_url": image.file_url}
        assert audit.entry_hash


@pytest.mark.parametrize("scope,model,actor,status", [("standard", "standard", "denied", 403), ("usluga", "usluga", "denied", 403), ("usluga", "usluga", "wrong", 403), ("standard", "usluga", "standard", 404), ("usluga", "standard", "usluga", 404)])
def test_denied_and_cross_scope_requests_do_not_write(env, scope, model, actor, status):
    client, sessions, ids, _ = env
    response = client.post(path(scope, ids["models"][model]), headers={"X-Actor": actor}, json={"file_url": "https://example.test/picture", "is_primary": True})
    assert response.status_code == status
    with sessions() as db:
        images = db.scalars(select(ModelImage)).all()
        assert len(images) == 2 and all(image.is_primary for image in images)
        assert db.scalars(select(AuditLog)).all() == []


def test_commit_failure_rolls_back_real_audit_and_image(env):
    client, sessions, ids, app = env
    def failing_db():
        with sessions() as db:
            def fail_commit():
                raise RuntimeError("injected commit failure")
            db.commit = fail_commit
            try:
                yield db
            finally:
                db.rollback()
    app.dependency_overrides[get_db] = failing_db
    response = client.post(path("standard", ids["models"]["standard"]), json={"file_url": "https://example.test/picture", "is_primary": True})
    assert response.status_code == 500
    with sessions() as db:
        images = db.scalars(select(ModelImage)).all()
        assert len(images) == 2 and all(image.is_primary for image in images)
        assert db.scalars(select(AuditLog)).all() == []
