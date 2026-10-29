"""The create-only enum boundary must not narrow historical edits or reads."""
from typing import get_type_hints
from uuid import uuid4

from fastapi import FastAPI
import pytest
from sqlalchemy import event

from app.api.routes.catalog import router
from app.libs.dto.catalog.collection_input import CollectionCreateIn, CollectionIn
from app.libs.dto.catalog.collection_output import CollectionCreateOut, CollectionOut
from app.libs.enums.catalog import CollectionStatus
from app.models.catalog import collections_service as service
from app.schemas import AuditLog, Brand, Collection, User
from app.schemas.catalog.collection_persistence import insert_collection
from app.tests.conftest import TestSessionLocal


def seed():
    with TestSessionLocal() as db:
        brand = Brand(name="Create contract brand")
        user = User(name="Create contract actor", email=f"collection-contract-{uuid4().hex}@example.invalid", password_hash="unused")
        db.add_all([brand, user]); db.commit()
        return brand.id, user.id


def test_create_contracts_are_actual_enum_types_and_legacy_contracts_remain_strings():
    assert CollectionCreateIn.model_fields['status'].annotation is CollectionStatus
    assert CollectionCreateIn.model_fields['status'].default is CollectionStatus.DRAFT
    assert CollectionCreateOut.model_fields['status'].annotation is CollectionStatus
    assert CollectionIn.model_fields['status'].annotation is str
    assert CollectionOut.model_fields['status'].annotation is str
    assert get_type_hints(service.create_collection)['payload'] is CollectionCreateIn
    assert get_type_hints(service.create_collection)['return'] is CollectionCreateOut
    assert get_type_hints(insert_collection)['status'] is CollectionStatus


def test_post_openapi_is_enum_typed_but_patch_and_reads_remain_legacy():
    app = FastAPI(); app.include_router(router, prefix='/api')
    schema = app.openapi(); models = schema['components']['schemas']
    assert models['CollectionStatus']['enum'] == ['draft','approved','archived']
    assert models['CollectionCreateIn']['properties']['status']['default'] == 'draft'
    assert models['CollectionCreateIn']['properties']['status']['$ref'].endswith('/CollectionStatus')
    assert models['CollectionCreateOut']['properties']['status']['$ref'].endswith('/CollectionStatus')
    assert models['CollectionIn']['properties']['status']['type'] == 'string'
    assert models['CollectionOut']['properties']['status']['type'] == 'string'
    assert schema['paths']['/api/collections']['post']['requestBody']['content']['application/json']['schema']['$ref'].endswith('/CollectionCreateIn')
    assert schema['paths']['/api/collections/{cid}']['patch']['requestBody']['content']['application/json']['schema']['$ref'].endswith('/CollectionIn')


@pytest.mark.parametrize('status', list(CollectionStatus))
def test_enum_reaches_schema_on_same_session_and_result_is_typed(monkeypatch, status):
    brand_id, user_id = seed(); observed = []
    original = service.insert_collection
    with TestSessionLocal() as db:
        def insert(actual_db, **values):
            assert actual_db is db
            assert values['status'] is status
            row = original(actual_db, **values)
            assert type(row.status) is str and row.status == status.value
            observed.append(row.id)
            return row
        monkeypatch.setattr(service, 'insert_collection', insert)
        output = service.create_collection(db.get(User,user_id), db, CollectionCreateIn(brand_id=brand_id,name='Typed',year=2026,status=status))
        assert isinstance(output, CollectionCreateOut) and output.status is status
        assert output.model_dump(mode='json')['status'] == status.value
        assert observed == [output.id]
        assert db.query(AuditLog).filter_by(entity_type='Collection',entity_id=output.id).count() == 1


def test_schema_writer_flushes_without_committing_and_caller_can_rollback():
    brand_id, _ = seed(); commits = []
    with TestSessionLocal() as db:
        event.listen(db, 'after_commit', lambda _: commits.append(True))
        row = insert_collection(db,brand_id=brand_id,name='Rollback',season=None,year=2026,description=None,status=CollectionStatus.DRAFT)
        assert row.id is not None and db.query(Collection).filter_by(id=row.id).count() == 1
        row_id = row.id
        assert commits == []
        db.rollback()
    with TestSessionLocal() as db: assert db.get(Collection,row_id) is None


def test_schema_writer_is_required_before_any_persistence(monkeypatch):
    brand_id, user_id = seed()
    class SchemaMarker(Exception): pass
    def refuse(*args, **kwargs): raise SchemaMarker()
    monkeypatch.setattr(service, 'insert_collection', refuse)
    with TestSessionLocal() as db:
        before = (db.query(Collection).count(), db.query(AuditLog).count())
        with pytest.raises(SchemaMarker):
            service.create_collection(db.get(User,user_id), db, CollectionCreateIn(brand_id=brand_id,name='No bypass',year=2026))
        assert (db.query(Collection).count(), db.query(AuditLog).count()) == before


def test_http_default_omits_status_and_returns_canonical_json(client,auth_headers):
    brand_id, _ = seed()
    response = client.post('/api/collections',headers=auth_headers,json={'brand_id':brand_id,'name':'Default','year':2026})
    assert response.status_code == 201, response.text
    assert response.json()['status'] == 'draft'
