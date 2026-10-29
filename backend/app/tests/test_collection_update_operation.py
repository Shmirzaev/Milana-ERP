"""Characterize Collection PATCH persistence, compatibility and transaction rules."""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.orm import object_session

from app.libs.dto.catalog.collection_input import CollectionIn
from app.libs.enums.catalog import CollectionStatus
from app.models.catalog import collections_service
from app.schemas import AuditLog, Brand, Collection
from app.tests.conftest import TestSessionLocal


def _seed_collection(status: str = "draft") -> tuple[int, int]:
    marker = uuid4().hex
    with TestSessionLocal() as db:
        brand = Brand(name=f"Collection update brand {marker}")
        db.add(brand)
        db.flush()
        collection = Collection(
            brand_id=brand.id,
            name=f"Original {marker}",
            season="Winter",
            year=2025,
            description="Original description",
            status=status,
        )
        db.add(collection)
        db.commit()
        return int(brand.id), int(collection.id)


def test_update_uses_same_session_and_preserves_omitted_fields(monkeypatch):
    brand_id, collection_id = _seed_collection()
    original = collections_service.apply_collection_update
    observed = []

    def spy(db, collection, fields):
        assert object_session(collection) is db
        observed.append((db, collection, dict(fields)))
        original(db, collection, fields)

    monkeypatch.setattr(collections_service, "apply_collection_update", spy)
    with TestSessionLocal() as db:
        updated = collections_service.update_collection(
            None,
            db,
            collection_id,
            CollectionIn(brand_id=brand_id, name="Renamed", year=2026),
        )
        assert observed == [
            (db, updated, {"brand_id": brand_id, "name": "Renamed", "year": 2026})
        ]
        assert (updated.name, updated.season, updated.year, updated.description, updated.status) == (
            "Renamed",
            "Winter",
            2026,
            "Original description",
            "draft",
        )


def test_same_value_canonical_patch_still_appends_update_audit():
    _brand_id, collection_id = _seed_collection()
    with TestSessionLocal() as db:
        row = db.get(Collection, collection_id)
        status_sets = []
        event.listen(
            row,
            "status",
            "set",
            lambda target, value, oldvalue, initiator: status_sets.append(
                (value, oldvalue)
            ),
        )
        before = (
            row.brand_id,
            row.name,
            row.season,
            row.year,
            row.description,
            row.status,
        )
        assert db.query(AuditLog).filter_by(
            entity_type="Collection", entity_id=collection_id, action="update"
        ).count() == 0

        collections_service.update_collection(
            None,
            db,
            collection_id,
            CollectionIn(
                brand_id=row.brand_id,
                name=row.name,
                season=row.season,
                year=row.year,
                description=row.description,
                status="draft",
            ),
        )

        updated = db.get(Collection, collection_id)
        assert (
            updated.brand_id,
            updated.name,
            updated.season,
            updated.year,
            updated.description,
            updated.status,
        ) == before
        assert db.query(AuditLog).filter_by(
            entity_type="Collection", entity_id=collection_id, action="update"
        ).count() == 1
        assert status_sets == [("draft", "draft")]


def test_update_clears_nullable_fields_and_keeps_unchanged_legacy_status():
    brand_id, collection_id = _seed_collection(status="legacy_review_state")
    with TestSessionLocal() as db:
        row = db.get(Collection, collection_id)
        status_sets = []
        event.listen(
            row,
            "status",
            "set",
            lambda target, value, oldvalue, initiator: status_sets.append(
                (value, oldvalue)
            ),
        )
        updated = collections_service.update_collection(
            None,
            db,
            collection_id,
            CollectionIn(
                brand_id=brand_id,
                name="Legacy renamed",
                year=2026,
                season=None,
                description=None,
                status="legacy_review_state",
            ),
        )
        assert (updated.name, updated.season, updated.description, updated.status) == (
            "Legacy renamed",
            None,
            None,
            "legacy_review_state",
        )
        assert db.query(AuditLog).filter_by(
            entity_type="Collection", entity_id=collection_id, action="update"
        ).count() == 1
        assert status_sets == [
            ("legacy_review_state", "legacy_review_state")
        ]


def test_update_command_types_canonical_status_and_preserves_legacy_assignment(monkeypatch):
    _brand_id, collection_id = _seed_collection(status="legacy_review_state")
    original = collections_service.apply_collection_update
    observed = []

    def spy(db, collection, fields):
        observed.append(dict(fields))
        original(db, collection, fields)

    monkeypatch.setattr(collections_service, "apply_collection_update", spy)
    with TestSessionLocal() as db:
        brand_id = db.get(Collection, collection_id).brand_id
        collections_service.update_collection(
            None,
            db,
            collection_id,
            CollectionIn(
                brand_id=brand_id,
                name="Legacy kept",
                year=2026,
                status="legacy_review_state",
            ),
        )
        collections_service.update_collection(
            None,
            db,
            collection_id,
            CollectionIn(
                brand_id=brand_id,
                name="Canonicalized",
                year=2027,
                status="approved",
            ),
        )

    assert observed[0] == {
        "brand_id": brand_id,
        "name": "Legacy kept",
        "year": 2026,
        "unchanged_legacy_status": "legacy_review_state",
    }
    assert observed[1] == {
        "brand_id": brand_id,
        "name": "Canonicalized",
        "year": 2027,
        "status": CollectionStatus.APPROVED,
    }


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"year": 0}, "Year is required"),
        ({"status": "retired"}, "Invalid collection status"),
    ],
)
def test_refusal_does_not_call_writer_or_append_audit(monkeypatch, payload, detail):
    brand_id, collection_id = _seed_collection()

    def unexpected(*args, **kwargs):
        raise AssertionError("persistence writer must not run after validation refusal")

    monkeypatch.setattr(collections_service, "apply_collection_update", unexpected)
    with TestSessionLocal() as db:
        current = db.get(Collection, collection_id)
        before = (current.brand_id, current.name, current.year, current.status)
        request_data = {"brand_id": brand_id, "name": "Must not change", "year": 2026}
        request_data.update(payload)
        request = CollectionIn(**request_data)
        with pytest.raises(HTTPException) as error:
            collections_service.update_collection(None, db, collection_id, request)
        assert error.value.status_code == 400
        assert error.value.detail == detail
        assert (current.brand_id, current.name, current.year, current.status) == before
        assert db.query(AuditLog).filter_by(
            entity_type="Collection", entity_id=collection_id, action="update"
        ).count() == 0
        db.rollback()


def test_audit_failure_rolls_back_update_and_explicit_retry(monkeypatch):
    brand_id, collection_id = _seed_collection()
    original = collections_service.log_action
    with TestSessionLocal() as db:
        row = db.get(Collection, collection_id)
        before = (
            row.brand_id,
            row.name,
            row.season,
            row.year,
            row.description,
            row.status,
            row.created_at,
            row.updated_at,
        )

    def fail_after_audit(db, actor, action, entity_type, entity_id):
        original(db, actor, action, entity_type, entity_id)
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(collections_service, "log_action", fail_after_audit)
    with TestSessionLocal() as db:
        with pytest.raises(RuntimeError, match="injected audit"):
            collections_service.update_collection(
                None,
                db,
                collection_id,
                CollectionIn(brand_id=brand_id, name="Changed", year=2026),
            )
        db.rollback()

    with TestSessionLocal() as db:
        row = db.get(Collection, collection_id)
        assert (
            row.brand_id,
            row.name,
            row.season,
            row.year,
            row.description,
            row.status,
            row.created_at,
            row.updated_at,
        ) == before
        assert db.query(AuditLog).filter_by(
            entity_type="Collection", entity_id=collection_id, action="update"
        ).count() == 0

    monkeypatch.setattr(collections_service, "log_action", original)
    with TestSessionLocal() as db:
        collections_service.update_collection(
            None,
            db,
            collection_id,
            CollectionIn(brand_id=brand_id, name="Changed", year=2026),
        )
    with TestSessionLocal() as db:
        row = db.get(Collection, collection_id)
        assert row.name == "Changed" and row.year == 2026
        assert db.query(AuditLog).filter_by(
            entity_type="Collection", entity_id=collection_id, action="update"
        ).count() == 1
