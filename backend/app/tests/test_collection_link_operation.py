"""Characterize collection link creation and its transaction boundary."""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.models.catalog import collections_service
from app.schemas import Brand, Collection, CollectionModel, Model
from app.tests.conftest import TestSessionLocal


def seed():
    marker = uuid4().hex
    with TestSessionLocal() as db:
        brand = Brand(name=marker)
        db.add(brand)
        db.flush()
        collection = Collection(brand_id=brand.id, name=marker, year=2026)
        standard = Model(code=marker, name=marker, catalog_scope="standard")
        usluga = Model(code=marker + "u", name=marker, catalog_scope="usluga", factory_code="ECO")
        db.add_all([collection, standard, usluga])
        db.commit()
        return collection.id, standard.id, usluga.id


def test_add_links_duplicates_and_commits_once_per_call():
    cid, mid, _ = seed()
    with TestSessionLocal() as db:
        commits = []
        event.listen(db, "after_commit", lambda _: commits.append(True))
        assert collections_service.add_model_to_collection(None, db, cid, mid) == {"message": "added"}
        assert collections_service.add_model_to_collection(None, db, cid, mid) == {"message": "added"}
        assert len(commits) == 2
    with TestSessionLocal() as db:
        assert db.query(CollectionModel).filter_by(collection_id=cid, model_id=mid).count() == 2


def test_missing_collection_precedes_model_and_nonstandard_model_is_rejected():
    cid, _, usluga_id = seed()
    with TestSessionLocal() as db:
        for collection_id, model_id, message in [(0, 0, "Collection not found"), (cid, 0, "Model not found"), (cid, usluga_id, "Model not found")]:
            with pytest.raises(HTTPException) as exc:
                collections_service.add_model_to_collection(None, db, collection_id, model_id)
            assert (exc.value.status_code, exc.value.detail) == (404, message)
        assert db.query(CollectionModel).filter_by(collection_id=cid).count() == 0


def test_schema_writer_stages_without_flush_or_commit_and_rolls_back():
    from app.schemas.catalog.collection_persistence import insert_collection_model

    cid, mid, _ = seed()
    with TestSessionLocal() as db:
        flushes, commits = [], []
        event.listen(db, "after_flush", lambda *_: flushes.append(True))
        event.listen(db, "after_commit", lambda *_: commits.append(True))
        insert_collection_model(db, collection_id=cid, model_id=mid)
        assert len(db.new) == 1
        assert flushes == commits == []
        db.flush()
        db.rollback()
    with TestSessionLocal() as db:
        assert db.query(CollectionModel).filter_by(collection_id=cid, model_id=mid).count() == 0


def _role_headers(client, email):
    response = client.post(
        "/api/auth/token", data={"username": email, "password": "demo12345"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_route_requires_permission_and_model_query_parameter(client):
    cid, mid, _ = seed()
    url = f"/api/collections/{cid}/models"
    denied = _role_headers(client, "storage@example.com")
    authorized = _role_headers(client, "modeling@example.com")
    assert client.post(url, params={"model_id": mid}).status_code == 401
    assert client.post(url, params={"model_id": mid}, headers=denied).status_code == 403
    assert client.post(url, json={"model_id": mid}, headers=authorized).status_code == 422
    with TestSessionLocal() as db:
        assert db.query(CollectionModel).filter_by(collection_id=cid, model_id=mid).count() == 0


def test_route_creates_link_and_returns_expected_404s(client):
    cid, mid, usluga_id = seed()
    headers = _role_headers(client, "modeling@example.com")
    for collection_id, model_id, message in [
        (0, mid, "Collection not found"),
        (cid, 0, "Model not found"),
        (cid, usluga_id, "Model not found"),
    ]:
        response = client.post(
            f"/api/collections/{collection_id}/models",
            params={"model_id": model_id}, headers=headers,
        )
        assert response.status_code == 404, response.text
        assert response.json() == {"detail": message}
    with TestSessionLocal() as db:
        assert db.query(CollectionModel).filter_by(collection_id=cid).count() == 0
    response = client.post(
        f"/api/collections/{cid}/models", params={"model_id": mid}, headers=headers
    )
    assert response.status_code == 201, response.text
    assert response.json() == {"message": "added"}
    with TestSessionLocal() as db:
        assert db.query(CollectionModel).filter_by(collection_id=cid, model_id=mid).count() == 1
