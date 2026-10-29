"""Brand creation on an explicitly approved, owned PostgreSQL database.

Place this file at backend/app/tests/test_brand_create_postgres.py in the candidate checkout. Run only under the integration owner's reviewed runner with an approved instance.
The fixture fails closed when the required instance configuration is missing.
"""
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.libs.dto.catalog.brand_input import BrandIn
from app.models.catalog import collections_service
from app.schemas import AuditLog, Brand
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target, load_approved_instance,
    owned_target_name, preflight_connection, require_or_skip, target_engine,
)


@pytest.fixture(scope="module")
def brand_pg_sessions():
    # Verify placement before any database mutation. No default database fallback.
    test_path = Path(__file__).resolve()
    backend = test_path.parents[2]
    if test_path.parent.name != "tests" or test_path.parent.parent.name != "app":
        raise RuntimeError("Place test under backend/app/tests before execution")
    alembic_ini = backend / "alembic.ini"
    if not alembic_ini.is_file():
        raise RuntimeError("Candidate backend/alembic.ini not found")
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    target_name = owned_target_name(target)
    engine = None
    sessions = sessionmaker(autoflush=False, expire_on_commit=False)
    try:
        engine = target_engine(target, options="-c statement_timeout=20000 -c lock_timeout=10000")
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(settings, "DATABASE_URL", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
            patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
            command.upgrade(Config(str(alembic_ini)), "head")
        sessions.configure(bind=engine)
        yield sessions
    finally:
        try:
            sessions.configure(bind=None)
        finally:
            finalize_target(target, engine)
            # After successful drop, independently verify exact-name absence on
            # the same identity-pinned server; never search or drop by prefix.
            admin = sa.create_engine(instance.admin_url, connect_args={"connect_timeout": 5}, future=True)
            try:
                with admin.connect() as connection:
                    connection.execute(sa.text("SET TRANSACTION READ ONLY"))
                    preflight_connection(connection, instance, "postgres")
                    exists = connection.execute(
                        sa.text("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = :name)"),
                        {"name": target_name},
                    ).scalar_one()
                    if exists:
                        raise RuntimeError("owned test database still exists after cleanup")
            finally:
                admin.dispose()


def test_pg_create_duplicate_and_audit(brand_pg_sessions):
    name = "Brand " + uuid4().hex
    with brand_pg_sessions() as db:
        brand = collections_service.create_brand(None, db, BrandIn(name=f"  {name}  "))
        brand_id = brand.id
        assert brand.name == name
        assert brand.is_active is True
    with brand_pg_sessions() as db:
        saved = db.get(Brand, brand_id)
        assert saved.name == name and saved.description is None and saved.logo_url is None
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=brand_id, action="create").count() == 1
        with pytest.raises(HTTPException) as duplicate:
            collections_service.create_brand(None, db, BrandIn(name=name.lower()))
        assert duplicate.value.status_code == 409
        db.rollback()
    with brand_pg_sessions() as db:
        assert db.query(Brand).filter_by(name=name).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=brand_id, action="create").count() == 1


def test_pg_audit_failure_rolls_back_then_retry(brand_pg_sessions, monkeypatch):
    name = "Retry " + uuid4().hex
    original = collections_service.log_action
    attempted_ids = []

    def fail_after_audit(db, actor, action, entity_type, entity_id):
        original(db, actor, action, entity_type, entity_id)
        attempted_ids.append(entity_id)
        raise RuntimeError("injected audit participant failure")

    monkeypatch.setattr(collections_service, "log_action", fail_after_audit)
    with brand_pg_sessions() as db:
        with pytest.raises(RuntimeError, match="injected audit"):
            collections_service.create_brand(None, db, BrandIn(name=name))
        db.rollback()
    with brand_pg_sessions() as db:
        assert db.query(Brand).filter_by(name=name).count() == 0
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=attempted_ids[0]).count() == 0
    monkeypatch.setattr(collections_service, "log_action", original)
    with brand_pg_sessions() as db:
        brand = collections_service.create_brand(None, db, BrandIn(name=name))
        brand_id = brand.id
    with brand_pg_sessions() as db:
        assert db.get(Brand, brand_id).name == name
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=brand_id, action="create").count() == 1
