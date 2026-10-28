"""Brand PATCH against the approved identity-pinned disposable PostgreSQL target."""
from uuid import uuid4
import pytest
from sqlalchemy.exc import IntegrityError
from app.libs.dto.catalog.brand_input import BrandIn
from app.models import audit_service
from app.models.catalog import collections_service
from app.schemas import AuditLog, Brand
from app.tests.test_brand_create_postgres import brand_pg_sessions  # noqa: F401


def test_pg_update_persistence_omission_null_and_chain(brand_pg_sessions):
    name = "Brand " + uuid4().hex
    with brand_pg_sessions() as db:
        row = Brand(name=name, description="old", logo_url="logo", is_active=False)
        db.add(row); db.commit(); bid = row.id
    with brand_pg_sessions() as db:
        updated = collections_service.update_brand(None, db, bid, BrandIn(name="  " + name))
        assert (updated.name, updated.description, updated.logo_url, updated.is_active) == ("  " + name, "old", "logo", False)
    with brand_pg_sessions() as db:
        collections_service.update_brand(None, db, bid, BrandIn(name=name, description=None, logo_url=None, is_active=False))
    with brand_pg_sessions() as db:
        row = db.get(Brand, bid)
        assert (row.name, row.description, row.logo_url, row.is_active) == (name, None, None, False)
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=bid, action="update").count() == 2
        assert audit_service.verify_audit_hash_chain(db)["ok"] is True


def test_pg_duplicate_and_audit_finalize_failure_roll_back_then_retry(brand_pg_sessions, monkeypatch):
    name, taken = "Original " + uuid4().hex, "Taken " + uuid4().hex
    with brand_pg_sessions() as db:
        row = Brand(name=name); db.add_all([row, Brand(name=taken)]); db.commit(); bid = row.id
    with brand_pg_sessions() as db:
        with pytest.raises(IntegrityError):
            collections_service.update_brand(None, db, bid, BrandIn(name=taken))
        db.rollback()
    original = audit_service.add_audit_log_rows
    def fail(*args, **kwargs):
        raise RuntimeError("injected audit finalization failure")
    monkeypatch.setattr(audit_service, "add_audit_log_rows", fail)
    with brand_pg_sessions() as db:
        with pytest.raises(RuntimeError, match="injected audit finalization"):
            collections_service.update_brand(None, db, bid, BrandIn(name="Changed " + name))
        db.rollback()
    monkeypatch.setattr(audit_service, "add_audit_log_rows", original)
    with brand_pg_sessions() as db:
        assert db.get(Brand, bid).name == name
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=bid, action="update").count() == 0
        assert audit_service.verify_audit_hash_chain(db)["ok"] is True
    with brand_pg_sessions() as db:
        collections_service.update_brand(None, db, bid, BrandIn(name="Changed " + name))
    with brand_pg_sessions() as db:
        assert db.get(Brand, bid).name == "Changed " + name
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=bid, action="update").count() == 1
        assert audit_service.verify_audit_hash_chain(db)["ok"] is True


def test_pg_case_variant_update_is_allowed(brand_pg_sessions):
    name = "Case" + uuid4().hex
    with brand_pg_sessions() as db:
        existing, changed = Brand(name=name), Brand(name="Other" + uuid4().hex)
        db.add_all([existing, changed]); db.commit(); bid = changed.id
    with brand_pg_sessions() as db:
        collections_service.update_brand(None, db, bid, BrandIn(name=name.lower()))
    with brand_pg_sessions() as db:
        assert db.get(Brand, bid).name == name.lower()
        assert db.query(Brand).filter(Brand.name.in_([name, name.lower()])).count() == 2
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=bid, action="update").count() == 1
        assert audit_service.verify_audit_hash_chain(db)["ok"] is True
