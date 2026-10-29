"""Collection PATCH on the approved identity-pinned disposable PostgreSQL target."""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.libs.dto.catalog.collection_input import CollectionIn
from app.models import audit_service
from app.models.catalog import collections_service
from app.schemas import AuditLog, Brand, Collection
from app.tests.test_brand_create_postgres import brand_pg_sessions  # noqa: F401


def _seed_collection(sessions, *, status: str = "draft") -> tuple[int, int]:
    marker = uuid4().hex
    with sessions() as db:
        brand = Brand(name=f"Collection update PG brand {marker}")
        db.add(brand)
        db.flush()
        collection = Collection(
            brand_id=brand.id,
            name=f"Original PG {marker}",
            season="Winter",
            year=2025,
            description="Original description",
            status=status,
        )
        db.add(collection)
        db.commit()
        return int(brand.id), int(collection.id)


def test_pg_update_preserves_omissions_and_legacy_status_then_clears_nullables(brand_pg_sessions):
    brand_id, collection_id = _seed_collection(
        brand_pg_sessions, status="legacy_review_state"
    )
    with brand_pg_sessions() as db:
        collections_service.update_collection(
            None,
            db,
            collection_id,
            CollectionIn(brand_id=brand_id, name="Renamed PG", year=2026),
        )

    with brand_pg_sessions() as db:
        row = db.get(Collection, collection_id)
        assert (row.name, row.season, row.year, row.description, row.status) == (
            "Renamed PG",
            "Winter",
            2026,
            "Original description",
            "legacy_review_state",
        )

    with brand_pg_sessions() as db:
        collections_service.update_collection(
            None,
            db,
            collection_id,
            CollectionIn(
                brand_id=brand_id,
                name="Canonical PG",
                year=2027,
                season=None,
                description=None,
                status="approved",
            ),
        )

    with brand_pg_sessions() as db:
        row = db.get(Collection, collection_id)
        assert (row.name, row.season, row.year, row.description, row.status) == (
            "Canonical PG",
            None,
            2027,
            None,
            "approved",
        )
        assert db.query(AuditLog).filter_by(
            entity_type="Collection", entity_id=collection_id, action="update"
        ).count() == 2
        assert audit_service.verify_audit_hash_chain(db)["ok"] is True

    with brand_pg_sessions() as db:
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
        before_audits = db.query(AuditLog).filter_by(
            entity_type="Collection", entity_id=collection_id, action="update"
        ).count()
        with pytest.raises(HTTPException) as error:
            collections_service.update_collection(
                None,
                db,
                collection_id,
                CollectionIn(
                    brand_id=brand_id,
                    name="Rejected PG",
                    year=2028,
                    status="retired",
                ),
            )
        assert error.value.status_code == 400
        assert error.value.detail == "Invalid collection status"
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
        ).count() == before_audits
        db.rollback()


def test_pg_audit_finalization_failure_rolls_back_then_retry(brand_pg_sessions, monkeypatch):
    brand_id, collection_id = _seed_collection(brand_pg_sessions)
    original = audit_service.add_audit_log_rows
    with brand_pg_sessions() as db:
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

    def fail(*args, **kwargs):
        raise RuntimeError("injected audit finalization failure")

    monkeypatch.setattr(audit_service, "add_audit_log_rows", fail)
    with brand_pg_sessions() as db:
        with pytest.raises(RuntimeError, match="injected audit finalization"):
            collections_service.update_collection(
                None,
                db,
                collection_id,
                CollectionIn(brand_id=brand_id, name="Changed PG", year=2026),
            )
        db.rollback()

    monkeypatch.setattr(audit_service, "add_audit_log_rows", original)
    with brand_pg_sessions() as db:
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
        assert audit_service.verify_audit_hash_chain(db)["ok"] is True

    with brand_pg_sessions() as db:
        collections_service.update_collection(
            None,
            db,
            collection_id,
            CollectionIn(brand_id=brand_id, name="Changed PG", year=2026),
        )

    with brand_pg_sessions() as db:
        row = db.get(Collection, collection_id)
        assert row.name == "Changed PG" and row.year == 2026
        assert db.query(AuditLog).filter_by(
            entity_type="Collection", entity_id=collection_id, action="update"
        ).count() == 1
        assert audit_service.verify_audit_hash_chain(db)["ok"] is True
