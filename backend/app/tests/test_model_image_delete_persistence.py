"""Route and transaction characterization for model image deletion."""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import catalog, usluga
from app.core.deps import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.models.catalog import models_service
from app.schemas import AuditLog, Model, ModelImage, Role, User
from app.schemas.catalog.model_image_persistence import delete_model_image


@pytest.fixture
def fixture():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions.begin() as db:
        role = Role(name='image editor', permissions=['modeling.models', 'usluga.manage'])
        denied = Role(name='no image permission', permissions=[])
        db.add_all([role, denied])
        db.flush()
        actors = {key: User(name=key, email=f'{key}@example.invalid', password_hash='unused', role_id=(denied.id if key == 'denied' else role.id), factory_code=('ECO' if key == 'usluga' else 'MIL')) for key in ('standard', 'usluga', 'denied')}
        models = {key: Model(code=f'IMAGE-{key}', name=key, catalog_scope=('usluga' if key == 'usluga' else 'standard'), factory_code=('ECO' if key == 'usluga' else 'MIL')) for key in ('standard', 'other', 'usluga')}
        db.add_all([*actors.values(), *models.values()])
        db.flush()
        images = {key: ModelImage(model_id=models[key].id, file_url=f'/files/{key}.png', file_data=b'image') for key in ('standard', 'usluga')}
        db.add_all(images.values())
        db.flush()
        ids = {name: {key: row.id for key, row in rows.items()} for name, rows in [('actors', actors), ('models', models), ('images', images)]}
    app = FastAPI()
    app.include_router(catalog.router, prefix='/api')
    app.include_router(usluga.router, prefix='/api')
    def get_session():
        with sessions() as db:
            yield db
    def get_actor(request: Request):
        with sessions() as db:
            actor = db.get(User, ids['actors'][request.headers.get('X-Actor', 'standard')])
            _ = actor.role, actor.department
            db.expunge_all()
            return actor
    app.dependency_overrides[get_db] = get_session
    app.dependency_overrides[get_current_user] = get_actor
    with TestClient(app, raise_server_exceptions=False) as client:
        yield sessions, ids, client
    engine.dispose()


def path(ids, scope, model=None, image=None):
    prefix = '/api/usluga/models' if scope == 'usluga' else '/api/models'
    return f"{prefix}/{model or ids['models'][scope]}/images/{image or ids['images'][scope]}"


@pytest.mark.parametrize('scope', ['standard', 'usluga'])
def test_delete_route_and_audit(fixture, scope):
    sessions, ids, client = fixture
    response = client.delete(path(ids, scope), headers={'X-Actor': scope})
    assert response.status_code == 204 and response.content == b''
    with sessions() as db:
        assert db.get(ModelImage, ids['images'][scope]) is None
        audit = db.query(AuditLog).one()
        assert (audit.user_id, audit.action, audit.entity_type, audit.entity_id) == (ids['actors'][scope], 'delete', 'ModelImage', ids['images'][scope])
        assert audit.new_value_json == {'model_id': ids['models'][scope], 'file_url': f'/files/{scope}.png'}


def test_denials_and_scoping_do_not_write(fixture):
    sessions, ids, client = fixture
    cases = [(path(ids, 'standard'), 'denied', 403), (path(ids, 'standard', model=999999), 'standard', 404), (path(ids, 'standard', image=999999), 'standard', 404), (path(ids, 'standard', model=ids['models']['other']), 'standard', 404), (path(ids, 'standard', model=ids['models']['usluga']), 'standard', 404), (path(ids, 'usluga'), 'standard', 403)]
    for url, actor, status in cases:
        assert client.delete(url, headers={'X-Actor': actor}).status_code == status
    with sessions() as db:
        assert db.query(ModelImage).count() == 2 and db.query(AuditLog).count() == 0


def test_helper_does_not_flush_or_commit(fixture, monkeypatch):
    sessions, ids, _ = fixture
    with sessions() as db:
        image = db.get(ModelImage, ids['images']['standard'])
        flushes = []
        event.listen(db, 'before_flush', lambda *args: flushes.append(True))
        monkeypatch.setattr(db, 'commit', lambda: pytest.fail('helper committed'))
        delete_model_image(db, image)
        assert image in db.deleted and not flushes
        db.rollback()


def test_late_audit_failure_rolls_back_image_and_audit(fixture, monkeypatch):
    sessions, ids, _ = fixture
    original = models_service.log_action
    def fail_after_audit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('late failure')
    monkeypatch.setattr(models_service, 'log_action', fail_after_audit)
    with sessions() as db:
        with pytest.raises(RuntimeError):
            models_service.delete_image(db.get(User, ids['actors']['standard']), db, ids['models']['standard'], ids['images']['standard'])
        db.rollback()
    with sessions() as db:
        assert db.get(ModelImage, ids['images']['standard']).file_data == b'image'
        assert db.query(AuditLog).count() == 0
