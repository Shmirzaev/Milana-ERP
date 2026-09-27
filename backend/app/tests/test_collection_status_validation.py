from uuid import uuid4

import pytest

from app.models import AuditLog, Brand, Collection
from app.tests.conftest import TestSessionLocal


VALID_STATUSES = ("draft", "approved", "archived")


def _collection_case(status: str = "draft") -> tuple[int, int, str]:
    marker = uuid4().hex[:12]
    with TestSessionLocal() as db:
        brand = Brand(name=f"DB02 collection brand {marker}")
        db.add(brand)
        db.flush()
        collection = Collection(
            brand_id=brand.id,
            name=f"DB02 collection {marker}",
            season="Winter",
            year=2099,
            status=status,
        )
        db.add(collection)
        db.commit()
        return int(brand.id), int(collection.id), marker


@pytest.mark.parametrize("status", VALID_STATUSES)
def test_collection_create_accepts_ui_statuses(client, auth_headers, status):
    brand_id, _, marker = _collection_case()
    response = client.post(
        "/api/collections",
        headers=auth_headers,
        json={
            "brand_id": brand_id,
            "name": f"Created {marker}",
            "season": "Winter",
            "year": 2099,
            "status": status,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == status


@pytest.mark.parametrize("status", VALID_STATUSES)
def test_collection_patch_accepts_ui_statuses(client, auth_headers, status):
    brand_id, collection_id, _ = _collection_case()
    response = client.patch(
        f"/api/collections/{collection_id}",
        headers=auth_headers,
        json={
            "brand_id": brand_id,
            "name": "Updated collection",
            "year": 2099,
            "status": status,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == status


def test_collection_create_rejects_unknown_status_without_write_or_audit(client, auth_headers):
    brand_id, _, marker = _collection_case()
    with TestSessionLocal() as db:
        before = (db.query(Collection).count(), db.query(AuditLog).count())

    response = client.post(
        "/api/collections",
        headers=auth_headers,
        json={
            "brand_id": brand_id,
            "name": f"Rejected {marker}",
            "season": "Winter",
            "year": 2099,
            "status": "retired",
        },
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Invalid collection status"}
    with TestSessionLocal() as db:
        after = (db.query(Collection).count(), db.query(AuditLog).count())
    assert after == before


def test_collection_patch_rejects_unknown_status_without_mutation_or_audit(client, auth_headers):
    brand_id, collection_id, _ = _collection_case()
    with TestSessionLocal() as db:
        before_audits = db.query(AuditLog).count()

    response = client.patch(
        f"/api/collections/{collection_id}",
        headers=auth_headers,
        json={
            "brand_id": brand_id,
            "name": "Must not be written",
            "year": 2099,
            "status": "retired",
        },
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Invalid collection status"}
    with TestSessionLocal() as db:
        collection = db.get(Collection, collection_id)
        assert collection.name.startswith("DB02 collection ")
        assert collection.status == "draft"
        assert db.query(AuditLog).count() == before_audits


def test_collection_patch_allows_unchanged_legacy_status_during_unrelated_edit(client, auth_headers):
    legacy_status = "legacy_review_state"
    brand_id, collection_id, _ = _collection_case(status=legacy_status)
    response = client.patch(
        f"/api/collections/{collection_id}",
        headers=auth_headers,
        json={
            "brand_id": brand_id,
            "name": "Renamed legacy collection",
            "year": 2099,
            "status": legacy_status,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Renamed legacy collection"
    assert response.json()["status"] == legacy_status


def test_collection_patch_rejects_changing_legacy_status_to_unknown_without_write(client, auth_headers):
    legacy_status = "legacy_review_state"
    brand_id, collection_id, _ = _collection_case(status=legacy_status)
    with TestSessionLocal() as db:
        before_audits = db.query(AuditLog).count()

    response = client.patch(
        f"/api/collections/{collection_id}",
        headers=auth_headers,
        json={
            "brand_id": brand_id,
            "name": "Must not be written",
            "year": 2099,
            "status": "retired",
        },
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Invalid collection status"}
    with TestSessionLocal() as db:
        collection = db.get(Collection, collection_id)
        assert collection.name.startswith("DB02 collection ")
        assert collection.status == legacy_status
        assert db.query(AuditLog).count() == before_audits


def test_collection_status_validation_preserves_resource_and_auth_precedence(client, auth_headers):
    missing = client.patch(
        "/api/collections/2147483647",
        headers=auth_headers,
        json={"brand_id": 1, "name": "Missing", "year": 2099, "status": "retired"},
    )
    assert missing.status_code == 404, missing.text

    unauthorized = client.post(
        "/api/collections",
        json={
            "brand_id": 1,
            "name": "Unauthorized",
            "year": 2099,
            "status": "retired",
        },
    )
    assert unauthorized.status_code == 401, unauthorized.text
