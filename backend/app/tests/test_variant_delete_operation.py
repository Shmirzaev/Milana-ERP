"""Variant deletion keeps scope, guard ordering, cascades and transaction ownership."""
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes import catalog, usluga
from app.models.catalog import models_service as service
from app.schemas import Model, ModelImage, ModelSize, ModelColor, ModelBOM
from app.schemas.catalog.catalog import Brand, Collection, CollectionModel
from app.schemas.catalog.variant_persistence import delete_variant_rows
from app.tests.conftest import TestSessionLocal


def test_routes_delegate_and_eco_gate(monkeypatch):
    call, eco = Mock(), Mock()
    monkeypatch.setattr(service, 'delete_model_variant', call)
    monkeypatch.setattr(usluga, '_require_eco', eco)
    actor, db = object(), object()
    catalog.delete_model_variant(1, 2, db, actor, 'standard')
    call.assert_called_with(actor, db, 1, 2, 'standard')
    usluga.delete_usluga_model_variant(1, 2, db, actor)
    eco.assert_called_once_with(actor)
    call.assert_called_with(actor, db, 1, 2, 'usluga')
    eco.side_effect = HTTPException(403, 'denied')
    call.reset_mock()
    with pytest.raises(HTTPException):
        usluga.delete_usluga_model_variant(1, 2, db, actor)
    call.assert_not_called()


def test_refusal_order_has_no_writes(monkeypatch):
    db = Mock()
    source = Mock(id=1, code='A', name='A', details_json={'general': {'model_no': 'A'}})
    other = Mock(id=2, code='B', name='B', details_json={'general': {'model_no': 'B'}})
    lookup = Mock(side_effect=[None])
    monkeypatch.setattr(service, '_model_with_variant_relations', lookup)
    with pytest.raises(HTTPException) as exc:
        service.delete_model_variant(object(), db, 1, 2)
    assert (exc.value.status_code, exc.value.detail) == (404, 'Model not found')
    lookup.side_effect = [source, other]
    with pytest.raises(HTTPException) as exc:
        service.delete_model_variant(object(), db, 1, 2)
    assert (exc.value.status_code, exc.value.detail) == (404, 'Variant not found')
    lookup.side_effect = [source, source]
    monkeypatch.setattr(service, '_model_usage_blockers', lambda *_: ['sales orders', 'packages'])
    with pytest.raises(HTTPException) as exc:
        service.delete_model_variant(object(), db, 1, 2)
    assert (exc.value.status_code, exc.value.detail) == (409, 'Variant is in use by: sales orders, packages')
    db.query.assert_not_called()
    db.delete.assert_not_called()
    db.commit.assert_not_called()


def test_persistence_cascades_and_rollback():
    from uuid import uuid4
    key = uuid4().hex
    with TestSessionLocal() as db:
        brand = Brand(name=key)
        collection = Collection(brand=brand, name=key, year=2024)
        model = Model(code=key, name=key, images=[ModelImage(file_url='test')], sizes=[ModelSize(size='M')], colors=[ModelColor(color_name='blue')], bom=[ModelBOM(quantity_per_piece=1, unit='m')])
        db.add_all([collection, model])
        db.flush()
        link = CollectionModel(collection_id=collection.id, model_id=model.id)
        db.add(link)
        db.commit()
        mid, lid = model.id, link.id
        child_ids = [(type(row), row.id) for row in [*model.images, *model.sizes, *model.colors, *model.bom]]
        delete_variant_rows(db, target=model, variant_id=mid)
        db.flush()
        # Query scalar IDs directly: bulk delete intentionally leaves loaded ORM
        # identities unsynchronized until the caller's session ends.
        for cls, row_id in [(Model, mid), (CollectionModel, lid), *child_ids]:
            assert db.scalar(select(cls.id).where(cls.id == row_id)) is None
        db.rollback()
    with TestSessionLocal() as readback:
        for cls, row_id in [(Model, mid), (CollectionModel, lid), *child_ids]:
            assert readback.get(cls, row_id) is not None
    with TestSessionLocal() as db:
        delete_variant_rows(db, target=db.get(Model, mid), variant_id=mid)
        db.commit()
    with TestSessionLocal() as readback:
        for cls, row_id in [(Model, mid), (CollectionModel, lid), *child_ids]:
            assert readback.get(cls, row_id) is None


def test_audit_failure_leaves_outer_transaction_recoverable(monkeypatch):
    from uuid import uuid4
    key = uuid4().hex
    with TestSessionLocal() as db:
        source = Model(code=key + '-1', name='family', details_json={'general': {'model_no': key, 'variant_no': '1'}})
        target = Model(code=key + '-2', name='family', details_json={'general': {'model_no': key, 'variant_no': '2'}}, sizes=[ModelSize(size='L')])
        db.add_all([source, target])
        db.commit()
        sid, tid, size_id = source.id, target.id, target.sizes[0].id
        def fail(*args, **kwargs):
            db.flush()
            raise RuntimeError('audit failed')
        monkeypatch.setattr(service, 'log_action', fail)
        with pytest.raises(RuntimeError, match='audit failed'):
            service.delete_model_variant(object(), db, sid, tid)
        db.rollback()
        assert db.get(Model, tid) is not None
        assert db.get(ModelSize, size_id) is not None


@pytest.mark.parametrize(('scope', 'prefix', 'factory'), [('standard', '/api/models', 'MIL'), ('usluga', '/api/usluga/models', 'ECO')])
def test_http_delete_persists_scope_and_audit(scope, prefix, factory):
    from uuid import uuid4
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.deps import get_current_user
    from app.db.session import get_db
    from app.schemas import AuditLog, Role, User

    key = uuid4().hex
    with TestSessionLocal() as db:
        role = Role(name=key, permissions=['modeling.models', 'usluga.manage'])
        db.add(role)
        db.flush()
        actor = User(name=key, email=key + '@example.invalid', password_hash='unused', role_id=role.id, factory_code=factory, is_active=True)
        source = Model(code=key+'-1', name='family', catalog_scope=scope, factory_code=factory, details_json={'general': {'model_no': key, 'variant_no': '1'}})
        target = Model(code=key+'-2', name='family', catalog_scope=scope, factory_code=factory, details_json={'general': {'model_no': key, 'variant_no': '2'}}, sizes=[ModelSize(size='M')])
        db.add_all([actor, source, target])
        db.commit()
        actor_id, sid, tid, child_id = actor.id, source.id, target.id, target.sizes[0].id
    app = FastAPI()
    app.include_router(catalog.router, prefix='/api')
    app.include_router(usluga.router, prefix='/api')
    def db_override():
        with TestSessionLocal() as db:
            yield db
    def current():
        with TestSessionLocal() as db:
            user = db.get(User, actor_id)
            _ = user.role, user.department
            db.expunge_all()
            return user
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = current
    with TestClient(app) as client:
        response = client.delete(f'{prefix}/{sid}/variants/{tid}')
        assert response.status_code == 204, response.text
        assert client.delete(f'{prefix}/{sid}/variants/{tid}').status_code == 404
    with TestSessionLocal() as db:
        assert db.get(Model, sid) is not None and db.get(Model, tid) is None
        assert db.get(ModelSize, child_id) is None
        audit = db.query(AuditLog).filter_by(action='delete_variant', entity_id=tid).one()
        assert audit.new_value_json['source_model_id'] == sid
        assert audit.new_value_json['code'] == key+'-2'
